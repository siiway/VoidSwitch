package tasks

import (
	"fmt"
	"log"
	"time"

	"gorm.io/gorm"

	"github.com/siiway/voidswitch/internal/core"
	"github.com/siiway/voidswitch/internal/database"
	"github.com/siiway/voidswitch/internal/services"
)

func RunLogCleanup(db *gorm.DB) error {
	if !services.GetBool("log_cleanup_enabled", true) {
		return nil
	}

	auditDays := services.GetInt("audit_log_retention_days", 90)
	requestDays := services.GetInt("request_log_retention_days", 60)
	debugDays := services.GetInt("debug_log_retention_days", 7)

	if auditDays <= 0 && requestDays <= 0 && debugDays <= 0 {
		return nil
	}

	auditCutoff := time.Now().AddDate(0, 0, -auditDays)
	requestCutoff := time.Now().AddDate(0, 0, -requestDays)
	debugCutoff := time.Now().AddDate(0, 0, -debugDays)

	var deleted int64

	auditResult := db.Exec("DELETE FROM audit_logs WHERE created_at < ?", auditCutoff)
	if auditResult.Error != nil {
		log.Printf("[log_cleanup] audit: %v", auditResult.Error)
	} else {
		deleted += auditResult.RowsAffected
	}

	requestResult := db.Exec("DELETE FROM request_logs WHERE created_at < ?", requestCutoff)
	if requestResult.Error != nil {
		log.Printf("[log_cleanup] request: %v", requestResult.Error)
	} else {
		deleted += requestResult.RowsAffected
	}

	debugResult := db.Exec("DELETE FROM debug_logs WHERE created_at < ?", debugCutoff)
	if debugResult.Error != nil {
		log.Printf("[log_cleanup] debug: %v", debugResult.Error)
	} else {
		deleted += debugResult.RowsAffected
	}

	if deleted > 0 {
		sub := "system"
		name := "log-cleanup"
		targetType := "system"
		msg := fmt.Sprintf("Cleaned %d stale log records (audit >%dd, request >%dd, debug >%dd)",
			deleted, auditDays, requestDays, debugDays)
		core.RecordAudit(db, "log.cleanup", &sub, &name, &targetType, nil,
			map[string]any{"deleted": deleted}, nil, nil, &msg, "system")
	}

	return nil
}

func RegisterLogCleanupTask(tm *TaskManager) {
	tm.Register(&PeriodicTask{
		Name:        "log_cleanup",
		Tick:        func() error { return RunLogCleanup(database.GetDatabase().DB) },
		IntervalKey: "log_cleanup_interval_seconds",
		EnabledKey:  strPtr("log_cleanup_enabled"),
		MinInterval: 60,
	})
}

func strPtr(s string) *string {
	return &s
}
