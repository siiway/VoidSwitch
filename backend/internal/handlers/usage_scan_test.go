package handlers

import (
	"fmt"
	"testing"
	"time"

	"gorm.io/driver/sqlite"
	"gorm.io/gorm"

	"github.com/siiway/voidswitch/internal/database"
)

// TestUsageBucketScanPopulatesTotals guards the Statistics tables: the grouped
// and bucketed rows embed the totals struct, and an unexported embedded type
// makes GORM skip those columns — which silently zeroed every "requests" cell
// while the non-embedded columns (TTFT) kept working.
func TestUsageBucketScanPopulatesTotals(t *testing.T) {
	db, err := gorm.Open(sqlite.Open(fmt.Sprintf("file:usage-%d?mode=memory&cache=shared", time.Now().UnixNano())), &gorm.Config{})
	if err != nil {
		t.Fatal(err)
	}
	if err := db.AutoMigrate(&database.RequestLog{}); err != nil {
		t.Fatal(err)
	}
	now := time.Now().UTC()
	for i := 0; i < 3; i++ {
		row := database.RequestLog{
			TS: now, Success: true, TotalTokens: 10, PromptTokens: 6, CompletionTokens: 4,
			FirstTokenMs: floatPtrTest(120), Model: strPtrTest("m1"),
			ProviderName: strPtrTest("p1"), UserSub: strPtrTest("u1"),
		}
		if err := db.Create(&row).Error; err != nil {
			t.Fatal(err)
		}
	}

	var buckets []usageBucket
	if err := db.Raw(`SELECT '2026-01-01' AS period,
		COUNT(*) AS requests,
		COALESCE(SUM(CASE WHEN success THEN 1 ELSE 0 END),0) AS success,
		COALESCE(SUM(prompt_tokens),0) AS prompt_tokens,
		COALESCE(SUM(completion_tokens),0) AS completion_tokens,
		COALESCE(SUM(total_tokens),0) AS total_tokens,
		AVG(first_token_ms) AS avg_first_token_ms
		FROM request_logs`).Scan(&buckets).Error; err != nil {
		t.Fatal(err)
	}
	if len(buckets) != 1 {
		t.Fatalf("buckets = %d, want 1", len(buckets))
	}
	b := buckets[0]
	if b.Requests != 3 {
		t.Fatalf("bucket requests = %d, want 3", b.Requests)
	}
	if b.Success != 3 {
		t.Fatalf("bucket success = %d, want 3", b.Success)
	}
	if b.TotalTokens != 30 {
		t.Fatalf("bucket total_tokens = %d, want 30", b.TotalTokens)
	}

	var rows []usageGroupRow
	if err := db.Raw(`SELECT CAST(model AS text) AS key, model AS label,
		COUNT(*) AS requests,
		COALESCE(SUM(CASE WHEN success THEN 1 ELSE 0 END),0) AS success,
		COALESCE(SUM(total_tokens),0) AS total_tokens
		FROM request_logs GROUP BY model`).Scan(&rows).Error; err != nil {
		t.Fatal(err)
	}
	if len(rows) != 1 {
		t.Fatalf("group rows = %d, want 1", len(rows))
	}
	if rows[0].Requests != 3 {
		t.Fatalf("group requests = %d, want 3", rows[0].Requests)
	}
	if rows[0].TotalTokens != 30 {
		t.Fatalf("group total_tokens = %d, want 30", rows[0].TotalTokens)
	}
}

func strPtrTest(s string) *string { return &s }

func floatPtrTest(f float64) *float64 { return &f }
