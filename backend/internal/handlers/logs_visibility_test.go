package handlers

import (
	"fmt"
	"testing"
	"time"

	"gorm.io/driver/sqlite"
	"gorm.io/gorm"

	"github.com/siiway/voidswitch/internal/core"
	"github.com/siiway/voidswitch/internal/database"
)

func firstAttempt(v any) map[string]any {
	list, ok := v.([]any)
	if !ok || len(list) == 0 {
		return nil
	}
	m, _ := list[0].(map[string]any)
	return m
}

// TestBuildRequestLogDetailVisibility pins the four-tier matrix: owner sees
// headers and bodies; admin sees headers only; a role-group admin sees the chain
// (with the masked key preview) but no headers/bodies; a member sees the chain
// with the key identifiers stripped.
func TestBuildRequestLogDetailVisibility(t *testing.T) {
	db, err := gorm.Open(sqlite.Open(fmt.Sprintf("file:vis-%d?mode=memory&cache=shared", time.Now().UnixNano())), &gorm.Config{})
	if err != nil {
		t.Fatal(err)
	}
	if err := db.AutoMigrate(&database.RequestLog{}); err != nil {
		t.Fatal(err)
	}
	row := database.RequestLog{
		TS:              time.Now().UTC(),
		Success:         true,
		AttemptsSummary: database.JSON(`[{"attempt":1,"key_preview":"sk-…test","route_type":"proxy","upstream_model":"m"}]`),
		DebugAttempts:   database.JSON(`[{"attempt":1,"key_preview":"sk-…test","req_headers":{"content-type":"application/json"},"resp_headers":{"content-type":"application/json"},"req_body":{"a":1},"resp_body":"ok"}]`),
	}
	if err := db.Create(&row).Error; err != nil {
		t.Fatal(err)
	}
	app := &App{GDB: db}

	cases := []struct {
		name        string
		uv          *core.UserView
		wantDebug   bool
		wantHeaders bool
		wantBodies  bool
		wantKey     bool
	}{
		{"owner", &core.UserView{Role: "owner"}, true, true, true, true},
		{"admin", &core.UserView{Role: "admin"}, true, true, false, true},
		{"role-group-admin", &core.UserView{Role: "member", AdminGroupIDs: []int{1}}, false, false, false, true},
		{"member", &core.UserView{Role: "member"}, false, false, false, false},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			got := app.buildRequestLogDetail(&row, tc.uv)
			summary := firstAttempt(got.AttemptsSummary)
			if summary == nil {
				t.Fatal("no attempts_summary")
			}
			if tc.wantKey != (summary["key_preview"] != nil) {
				t.Fatalf("key_preview visible=%v, want %v", summary["key_preview"] != nil, tc.wantKey)
			}
			debug := firstAttempt(got.DebugAttempts)
			if tc.wantDebug != (debug != nil) {
				t.Fatalf("debug_attempts present=%v, want %v", debug != nil, tc.wantDebug)
			}
			if debug == nil {
				return
			}
			if tc.wantHeaders != (debug["req_headers"] != nil) {
				t.Fatalf("headers visible=%v, want %v", debug["req_headers"] != nil, tc.wantHeaders)
			}
			if tc.wantBodies != (debug["req_body"] != nil) {
				t.Fatalf("req_body visible=%v, want %v", debug["req_body"] != nil, tc.wantBodies)
			}
		})
	}
}
