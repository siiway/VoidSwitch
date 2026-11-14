package handlers

import (
	"net/http"
	"time"

	"github.com/gin-gonic/gin"

	"github.com/siiway/voidswitch/internal/core"
	"github.com/siiway/voidswitch/internal/database"
	"github.com/siiway/voidswitch/internal/services"
)

var healthWindows = map[string]int{
	"30m": 1800, "1h": 3600, "3h": 10800, "12h": 43200,
	"1d": 86400, "3d": 259200, "7d": 604800,
}

// healthSnapshot returns {tab, models|nodes}.
func (a *App) healthSnapshot(c *gin.Context) {
	uv := core.GetUser(c)
	tab := c.DefaultQuery("tab", "models")
	window := c.DefaultQuery("window", "1d")
	if tab == "nodes" {
		if !uv.IsStaff() {
			a.fail(c, http.StatusForbidden, "Node health is staff-only.")
			return
		}
		c.JSON(http.StatusOK, gin.H{"tab": "nodes", "nodes": a.nodeHealth(window)})
		return
	}
	c.JSON(http.StatusOK, gin.H{"tab": "models", "models": a.modelHealth()})
}

// healthStream pushes snapshots over SSE (2s cadence).
func (a *App) healthStream(c *gin.Context) {
	uv := core.GetUser(c)
	tab := c.DefaultQuery("tab", "models")
	window := c.DefaultQuery("window", "1d")
	if tab == "nodes" && !uv.IsStaff() {
		a.fail(c, http.StatusForbidden, "Node health is staff-only.")
		return
	}
	c.Header("Content-Type", "text/event-stream")
	c.Header("Cache-Control", "no-cache")
	c.Header("Connection", "keep-alive")
	c.Header("X-Accel-Buffering", "no")

	flusher, _ := c.Writer.(http.Flusher)
	emit := func() {
		var payload gin.H
		if tab == "nodes" {
			payload = gin.H{"nodes": a.nodeHealth(window)}
		} else {
			payload = gin.H{"models": a.modelHealth()}
		}
		b, _ := jsonMarshal(payload)
		_, _ = c.Writer.Write([]byte("data: "))
		_, _ = c.Writer.Write(b)
		_, _ = c.Writer.Write([]byte("\n\n"))
		if flusher != nil {
			flusher.Flush()
		}
	}

	ctx := c.Request.Context()
	emit()
	ticker := time.NewTicker(2 * time.Second)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			emit()
		}
	}
}

// modelHealth computes a per-exposed-model health summary from recent request
// logs (success rate, avg ttft) plus any active upstream cooldowns.
func (a *App) modelHealth() []gin.H {
	recentCount := services.GetInt("model_health_recent_request_count", 50)
	since := time.Now().UTC().Add(-24 * time.Hour)
	var models []database.ExposedModel
	a.GDB.Where("enabled = ?", true).Order("model_id").Find(&models)
	out := make([]gin.H, 0, len(models))
	for i := range models {
		m := &models[i]
		var rows []database.RequestLog
		a.GDB.Where("model = ? AND ts >= ?", m.ModelID, since).
			Order("id DESC").Limit(recentCount).Find(&rows)
		var total, success int
		var ttftSum float64
		var ttftN int
		for j := range rows {
			total++
			if rows[j].Success {
				success++
			}
			if rows[j].FirstTokenMs != nil {
				ttftSum += *rows[j].FirstTokenMs
				ttftN++
			}
		}
		status := "learning"
		var rate *float64
		if total > 0 {
			r := float64(success) / float64(total)
			rate = &r
			switch {
			case r >= 0.9:
				status = "healthy"
			case r >= 0.5:
				status = "degraded"
			default:
				status = "unavailable"
			}
		}
		var ttft *float64
		if ttftN > 0 {
			avg := ttftSum / float64(ttftN)
			ttft = &avg
		}
		// Count active cooldowns for this model's route upstreams.
		var cooled int64
		a.GDB.Model(&database.UpstreamCooldown{}).
			Where("until > ? AND upstream_model IN (SELECT ru.upstream_model FROM route_upstreams ru JOIN routes ro ON ro.id = ru.route_id JOIN exposed_models em ON em.id = ro.exposed_model_id WHERE em.model_id = ?)",
				time.Now().UTC(), m.ModelID).Count(&cooled)
		if status == "healthy" && cooled > 0 {
			status = "degraded"
		}
		out = append(out, gin.H{
			"model_id":             m.ModelID,
			"status":               status,
			"recent_success_rate":  rate,
			"recent_request_count": total,
			"recent_avg_ttft_ms":   ttft,
			"sufficient_data":      total >= services.GetInt("upstream_min_samples", 10),
			"best_success_rate":    rate,
			"best_ttft_ms":         ttft,
			"upstreams":            []any{},
		})
	}
	return out
}

// nodeHealth builds the node health view (score + samples) for staff.
func (a *App) nodeHealth(window string) []gin.H {
	secs := healthWindows[window]
	if secs == 0 {
		secs = 86400
	}
	since := time.Now().UTC().Add(-time.Duration(secs) * time.Second)

	var nodes []database.Node
	a.GDB.Order("id").Find(&nodes)

	// group membership names per node
	memberships := map[int][]string{}
	var groups []database.NodeGroup
	a.GDB.Find(&groups)
	for i := range groups {
		for _, n := range services.ExpandGroupNodes(a.GDB, groups[i].ID) {
			memberships[n.ID] = append(memberships[n.ID], groups[i].Name)
		}
	}

	var samples []database.NodeHealthSample
	a.GDB.Where("ts >= ?", since).Order("ts asc").Find(&samples)
	byNode := map[int][]database.NodeHealthSample{}
	for _, s := range samples {
		byNode[s.NodeID] = append(byNode[s.NodeID], s)
	}

	alpha := services.GetFloat("node_rank_alpha", 1.0)
	beta := services.GetFloat("node_rank_beta", 100.0)
	gamma := services.GetFloat("node_rank_gamma", 1000.0)
	threshold := float64(services.GetInt("max_proxy_failures", 3))
	if threshold < 1 {
		threshold = 1
	}

	out := make([]gin.H, 0, len(nodes))
	for i := range nodes {
		n := &nodes[i]
		latency := 0.0
		if n.LatencyEWMA != nil {
			latency = *n.LatencyEWMA
		}
		score := alpha*latency + beta*float64(n.FailedCount)
		fc := float64(n.FailedCount) / threshold
		if fc > 1 {
			fc = 1
		}
		score += gamma * fc

		grpNames := memberships[n.ID]
		if grpNames == nil {
			grpNames = []string{}
		}
		ns := byNode[n.ID]
		samplesOut := make([]gin.H, 0, len(ns))
		for _, s := range ns {
			samplesOut = append(samplesOut, gin.H{
				"ts": s.TS, "success": s.Success, "latency_ms": s.LatencyMs,
				"source": s.Source, "status_code": s.StatusCode,
			})
		}
		out = append(out, gin.H{
			"id": n.ID, "url": n.URL, "type": n.Type, "note": n.Note,
			"enabled": n.Enabled, "status": n.Status, "failed_count": n.FailedCount,
			"weight": n.Weight, "latency_ms": n.LatencyMs, "latency_ewma": n.LatencyEWMA,
			"score": score, "groups": grpNames,
			"last_used_at": n.LastUsedAt, "last_checked_at": n.LastCheckedAt,
			"disabled_reason": n.DisabledReason, "samples": samplesOut,
			"created_at": n.CreatedAt,
		})
	}
	return out
}

// RegisterHealthRoutes wires /api/health + /api/health/stream (authenticated).
func RegisterHealthRoutes(authed *gin.RouterGroup, a *App) {
	g := authed.Group("/health", core.RequireUser())
	g.GET("", a.healthSnapshot)
	g.GET("/stream", a.healthStream)
}
