package tasks

import (
	"context"
	"time"

	"gorm.io/gorm"

	"github.com/siiway/voidswitch/internal/database"
	"github.com/siiway/voidswitch/internal/services"
)

// RegisterDefaults registers the standard background tasks. Phase 1 bodies are
// conservative (they run and report status); Phase 2 adds full balance probing,
// node resurrection and pending-log reconciliation.
func RegisterDefaults(m *Manager, db *gorm.DB, secretKey string) {
	m.Register(&Task{
		Name:        "balance_probe",
		IntervalKey: "balance_probe_interval_seconds",
		EnabledKey:  "balance_probe_enabled",
		MinInterval: 30,
		Tick: func(ctx context.Context) error {
			services.RunBalanceProbe(ctx, db, secretKey)
			return nil
		},
	})
	m.Register(&Task{
		Name:        "balance_rescan",
		IntervalKey: "balance_rescan_interval_seconds",
		EnabledKey:  "balance_rescan_enabled",
		MinInterval: 60,
		Tick: func(ctx context.Context) error {
			services.RunBalanceRescan(ctx, db, secretKey)
			return nil
		},
	})
	m.Register(&Task{
		Name:        "node_resurrector",
		IntervalKey: "node_probe_interval_seconds",
		// Health management is part of proxy switching; there is no separate
		// toggle. When switching is off, external egress handles the pool.
		EnabledKey:  "proxy_switching_enabled",
		MinInterval: 15,
		Tick: func(ctx context.Context) error {
			if !services.GetBool("proxy_switching_enabled", true) {
				return nil
			}
			return nil
		},
	})
	m.Register(&Task{
		Name:        "log_cleanup",
		IntervalKey: "log_cleanup_interval_seconds",
		EnabledKey:  "log_cleanup_enabled",
		MinInterval: 300,
		Tick: func(ctx context.Context) error {
			return reconcilePendingLogs(db)
		},
	})
}

// reconcilePendingLogs marks stale "pending" request logs as terminated, safe
// when response_timeout_seconds is 0 (no-op).
func reconcilePendingLogs(db *gorm.DB) error {
	timeout := services.GetInt("response_timeout_seconds", 3600)
	if timeout <= 0 {
		return nil
	}
	cutoff := time.Now().UTC().Add(-time.Duration(timeout) * time.Second)
	return db.Model(&database.RequestLog{}).
		Where("req_status = ? AND ts < ?", "pending", cutoff).
		Update("req_status", "terminated").Error
}
