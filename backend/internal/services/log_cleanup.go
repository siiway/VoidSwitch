package services

import (
	"time"

	"gorm.io/gorm"

	"github.com/siiway/voidswitch/internal/database"
)

// CleanupLogs applies the configured retention windows to every log-ish table.
//
// The periodic task and the dashboard's "clean now" action previously ran two
// different subsets of this, so the retention settings only partly took effect
// (and the scheduled run applied none of them). Both now call this one function.
func CleanupLogs(db *gorm.DB) LogCleanupResult {
	now := time.Now().UTC()
	var res LogCleanupResult

	// Expired cooldowns whose backoff counter has wound down are history; a
	// cooled upstream still mid-backoff keeps its row.
	res.DeletedCooldowns = deleteWhere(db, &database.UpstreamCooldown{},
		"until < ? AND consecutive_trips = ?", now.AddDate(0, 0, -7), 0)

	nodeDays := GetInt("node_health_history_retention_days", 7)
	if nodeDays < 1 {
		nodeDays = 7
	}
	res.DeletedNodeSamples = deleteWhere(db, &database.NodeHealthSample{},
		"ts < ?", now.AddDate(0, 0, -nodeDays))

	if days := GetInt("request_log_retention_days", 0); days > 0 {
		res.DeletedRequests = deleteWhere(db, &database.RequestLog{},
			"ts < ?", now.AddDate(0, 0, -days))
	}
	if days := GetInt("audit_log_retention_days", 0); days > 0 {
		res.DeletedAudits = deleteWhere(db, &database.AuditLog{},
			"ts < ?", now.AddDate(0, 0, -days))
	}
	if days := GetInt("debug_log_retention_days", 0); days > 0 {
		cutoff := now.AddDate(0, 0, -days)
		// Strip the per-attempt headers/bodies *and* the egress details: a proxy
		// URL can carry credentials, and this detail is meant to expire entirely.
		// Headers and the attempt trail are captured for every request now (not
		// only debug rows), so the strip applies to any row that still carries
		// them; the chain-only attempts_summary is left intact.
		res.StrippedDebug = stripDebugDetails(db, cutoff)
	}
	if days := GetInt("heatmap_retention_days", 0); days > 0 {
		cutoff := now.AddDate(0, 0, -days)
		res.DeletedHeatmapDays = deleteWhere(db, &database.UsageDaily{},
			"day < ?", cutoff.Format("2006-01-02"))
		res.DeletedSpans = deleteWhere(db, &database.SessionSpan{},
			"last_at < ?", cutoff)
	}
	return res
}

// stripDebugDetails nulls the per-attempt headers/bodies and egress details on
// rows older than cutoff, walking them in bounded id batches. Because the attempt
// trail is now captured for every request, the matching set can be the whole
// table; a single UPDATE would hold a long transaction and bloat WAL.
func stripDebugDetails(db *gorm.DB, cutoff time.Time) int64 {
	var total int64
	for {
		var ids []int
		if err := db.Model(&database.RequestLog{}).
			Where("ts < ? AND (debug = ? OR debug_attempts IS NOT NULL OR req_headers IS NOT NULL)",
				cutoff, true).
			Order("id").Limit(cleanupBatch).Pluck("id", &ids).Error; err != nil {
			return total
		}
		if len(ids) == 0 {
			return total
		}
		res := db.Model(&database.RequestLog{}).
			Where("id IN ?", ids).
			Updates(map[string]any{
				"debug": false, "req_headers": nil, "req_body": nil, "resp_headers": nil,
				"resp_body": nil, "debug_attempts": nil, "upstream_url": nil, "proxy_url": nil,
			})
		if res.Error != nil || res.RowsAffected == 0 {
			return total
		}
		total += res.RowsAffected
		if len(ids) < cleanupBatch {
			return total
		}
	}
}

// LogCleanupResult reports what a cleanup run removed or stripped.
type LogCleanupResult struct {
	DeletedRequests    int64 `json:"deleted_request_logs"`
	DeletedAudits      int64 `json:"deleted_audit_logs"`
	StrippedDebug      int64 `json:"stripped_debug_logs"`
	DeletedHeatmapDays int64 `json:"deleted_heatmap_days"`
	DeletedSpans       int64 `json:"deleted_session_spans"`
	DeletedCooldowns   int64 `json:"deleted_cooldowns"`
	DeletedNodeSamples int64 `json:"deleted_node_samples"`
}

// cleanupBatch bounds how many rows one DELETE removes, so a first cleanup on a
// large table cannot hold a long-lived lock.
const cleanupBatch = 5000

// deleteWhere removes matching rows in bounded batches and reports the total.
// It keeps going on error (returning what it managed) rather than aborting the
// whole cleanup run because one table is locked.
func deleteWhere(db *gorm.DB, model any, query string, args ...any) int64 {
	var total int64
	for {
		res := db.Where(query, args...).Limit(cleanupBatch).Delete(model)
		if res.Error != nil {
			return total
		}
		if res.RowsAffected == 0 {
			return total
		}
		total += res.RowsAffected
		if res.RowsAffected < cleanupBatch {
			return total
		}
	}
}
