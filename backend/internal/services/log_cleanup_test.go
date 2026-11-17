package services

import (
	"fmt"
	"testing"
	"time"

	"gorm.io/driver/sqlite"
	"gorm.io/gorm"

	"github.com/siiway/voidswitch/internal/database"
)

// TestStripDebugDetailsKeepsChain covers the retention split: the debug-level
// columns (headers, bodies, attempt detail, egress) are nulled on old rows while
// the chain-only attempts_summary survives, and fresh rows are untouched.
func TestStripDebugDetailsKeepsChain(t *testing.T) {
	db, err := gorm.Open(sqlite.Open(fmt.Sprintf("file:cleanup-%d?mode=memory&cache=shared", time.Now().UnixNano())), &gorm.Config{})
	if err != nil {
		t.Fatal(err)
	}
	if err := db.AutoMigrate(&database.RequestLog{}); err != nil {
		t.Fatal(err)
	}

	old := time.Now().UTC().Add(-48 * time.Hour)
	fresh := time.Now().UTC()
	chain := database.JSON(`[{"attempt":1,"route_type":"proxy"}]`)
	debug := database.JSON(`[{"attempt":1,"req_headers":{"a":"b"},"resp_body":"secret"}]`)
	ids := make([]int, 0, 3)
	for _, ts := range []time.Time{old, old, fresh} {
		row := database.RequestLog{
			TS: ts, AttemptsSummary: chain, DebugAttempts: debug,
			ReqHeaders: database.JSON(`{"a":"b"}`), ReqBody: database.JSON(`{}`),
			UpstreamURL: strPtr("https://x/v1"), ProxyURL: strPtr("http://u:p@h:1"),
			Debug: true,
		}
		if err := db.Create(&row).Error; err != nil {
			t.Fatal(err)
		}
		ids = append(ids, row.ID)
	}

	if n := stripDebugDetails(db, time.Now().UTC().Add(-24*time.Hour)); n != 2 {
		t.Fatalf("stripped %d rows, want 2", n)
	}

	read := func(id int) requestLogDebugFields {
		var got requestLogDebugFields
		// Select only the columns under test: the sqlite driver cannot scan the
		// stored `ts` text back into a time.Time, and it is irrelevant here.
		db.Model(&database.RequestLog{}).
			Select("debug", "debug_attempts", "req_headers", "req_body", "proxy_url", "upstream_url", "attempts_summary").
			Where("id = ?", id).Scan(&got)
		return got
	}

	oldRow := read(ids[0])
	if oldRow.Debug || oldRow.DebugAttempts != nil || oldRow.ReqHeaders != nil ||
		oldRow.ReqBody != nil || oldRow.ProxyURL != nil || oldRow.UpstreamURL != nil {
		t.Fatalf("old row not stripped: %+v", oldRow)
	}
	if oldRow.AttemptsSummary == nil {
		t.Fatal("the chain-only attempts_summary was stripped")
	}

	freshRow := read(ids[2])
	if freshRow.DebugAttempts == nil || freshRow.ReqHeaders == nil {
		t.Fatalf("fresh row was stripped: %+v", freshRow)
	}
}

// TestStripDebugDetailsBatchesMoreThanOnePage pins the bounded-batch loop: the
// attempt trail is captured for every request now, so the matching set can be
// the whole table and one UPDATE must not carry it.
func TestStripDebugDetailsBatchesMoreThanOnePage(t *testing.T) {
	db, err := gorm.Open(sqlite.Open(fmt.Sprintf("file:cleanup-batch-%d?mode=memory&cache=shared", time.Now().UnixNano())), &gorm.Config{})
	if err != nil {
		t.Fatal(err)
	}
	if err := db.AutoMigrate(&database.RequestLog{}); err != nil {
		t.Fatal(err)
	}

	old := time.Now().UTC().Add(-48 * time.Hour)
	const extra = 2
	rows := make([]database.RequestLog, 0, cleanupBatch+extra)
	for i := 0; i < cleanupBatch+extra; i++ {
		rows = append(rows, database.RequestLog{
			TS: old, AttemptsSummary: database.JSON(`[{"attempt":1,"route_type":"proxy"}]`),
			DebugAttempts: database.JSON(`[{"attempt":1,"req_body":{"a":1}}]`),
		})
	}
	if err := db.CreateInBatches(rows, 500).Error; err != nil {
		t.Fatal(err)
	}

	if n := stripDebugDetails(db, time.Now().UTC().Add(-24*time.Hour)); n != cleanupBatch+extra {
		t.Fatalf("stripped %d rows, want %d", n, cleanupBatch+extra)
	}
	var left int64
	db.Model(&database.RequestLog{}).Where("debug_attempts IS NOT NULL OR req_body IS NOT NULL").Count(&left)
	if left != 0 {
		t.Fatalf("%d rows still carry debug detail", left)
	}
	var kept int64
	db.Model(&database.RequestLog{}).Where("attempts_summary IS NULL").Count(&kept)
	if kept != 0 {
		t.Fatalf("%d rows lost the chain-only summary", kept)
	}
}

type requestLogDebugFields struct {
	Debug           bool
	DebugAttempts   database.JSON
	ReqHeaders      database.JSON
	ReqBody         database.JSON
	ProxyURL        *string
	UpstreamURL     *string
	AttemptsSummary database.JSON
}
