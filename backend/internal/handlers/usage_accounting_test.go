package handlers

import (
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
	"gorm.io/driver/sqlite"
	"gorm.io/gorm"

	"github.com/siiway/voidswitch/internal/core"
	"github.com/siiway/voidswitch/internal/database"
	"github.com/siiway/voidswitch/internal/services"
)

func logTestDB(t *testing.T) *gorm.DB {
	t.Helper()
	db, err := gorm.Open(sqlite.Open(fmt.Sprintf("file:logreq-%d?mode=memory&cache=shared", time.Now().UnixNano())), &gorm.Config{})
	if err != nil {
		t.Fatal(err)
	}
	if err := db.AutoMigrate(&database.RequestLog{}, &database.VoidToken{},
		&database.UsageDaily{}, &database.SessionSpan{}); err != nil {
		t.Fatal(err)
	}
	return db
}

func logTestContext(t *testing.T) *gin.Context {
	t.Helper()
	gin.SetMode(gin.TestMode)
	c, _ := gin.CreateTestContext(httptest.NewRecorder())
	c.Request = httptest.NewRequest(http.MethodPost, "/v1/chat/completions", nil)
	return c
}

func intRef(n int) *int { return &n }

// logRowFields selects only the columns under test: the sqlite driver cannot
// scan the stored `ts` text back into a time.Time, and it is irrelevant here.
type logRowFields struct {
	ProviderName     *string
	ProviderID       *int
	KeyID            *int
	ProxyID          *int
	UpstreamURL      *string
	ProxyURL         *string
	UpstreamModel    *string
	Attempts         int
	ProviderAttempts int
	NetworkAttempts  int
	TotalTokens      int64
	AttemptsSummary  database.JSON
	DebugAttempts    database.JSON
	Debug            bool
}

func readLogTestRow(t *testing.T, db *gorm.DB) logRowFields {
	t.Helper()
	var id int
	if err := db.Model(&database.RequestLog{}).Order("id desc").Limit(1).Pluck("id", &id).Error; err != nil {
		t.Fatal(err)
	}
	var out logRowFields
	if err := db.Model(&database.RequestLog{}).
		Select("provider_name", "provider_id", "key_id", "proxy_id", "upstream_url", "proxy_url",
			"upstream_model", "attempts", "provider_attempts", "network_attempts", "total_tokens",
			"attempts_summary", "debug_attempts", "debug").
		Where("id = ?", id).Scan(&out).Error; err != nil {
		t.Fatal(err)
	}
	return out
}

// TestLogRequestPersistsAttemptTrail pins what the handler writes: the chain-
// only summary plus the debug projection, the row-level provider/key/proxy
// backfill a failed dispatch cannot supply, and the streaming token stamp on the
// winning attempt (the dispatcher never sees the drained SSE usage).
func TestLogRequestPersistsAttemptTrail(t *testing.T) {
	db := logTestDB(t)
	app := &App{GDB: db}

	upstreamURL := "https://up.example/v1/chat/completions"
	proxyURL := "http://user:pw@10.0.0.5:3128"
	providerID, keyID, nodeID := 7, 11, 3
	tokenID := 1
	db.Create(&database.VoidToken{
		ID: tokenID, Name: "k", TokenHash: "kh", TokenPrefix: "vs-", UserID: 1,
		AllowedModels: database.JSONOf([]string{}),
	})

	first := &services.AttemptRecord{
		Attempt: 1, Provider: strPtr("mock"), ProviderID: intRef(providerID), KeyID: intRef(keyID),
		KeyPreview: strPtr("sk-…test"), UpstreamModel: strPtr("upstream-model"),
		URL: strPtr("https://bad.example/v1/chat/completions"), StatusCode: intRef(http.StatusInternalServerError),
		RouteType: strPtr("proxy"), ProxyURL: strPtr(proxyURL),
		ReqHeaders: map[string]string{"Authorization": "<redacted>"},
		RespBody:   map[string]any{"error": "boom"},
		NetworkAttempts: []services.NetworkAttempt{{
			Attempt: 1, NodeID: intRef(nodeID), RouteType: strPtr("proxy"),
			StatusCode: intRef(http.StatusInternalServerError),
		}},
	}
	last := &services.AttemptRecord{
		Attempt: 2, Provider: strPtr("good"), ProviderID: intRef(providerID), KeyID: intRef(keyID),
		UpstreamModel: strPtr("upstream-model"), URL: strPtr(upstreamURL),
		StatusCode: intRef(http.StatusOK), RouteType: strPtr("proxy"), ProxyURL: strPtr(proxyURL),
		ReqHeaders:  map[string]string{"Authorization": "<redacted>"},
		RespHeaders: map[string]string{"content-type": "text/event-stream"},
		NetworkAttempts: []services.NetworkAttempt{{
			Attempt: 1, NodeID: intRef(nodeID), RouteType: strPtr("proxy"),
			StatusCode: intRef(http.StatusOK),
		}},
	}

	app.logRequest(logTestContext(t), requestLogInfo{
		TokenID: tokenID, UserSub: "u1", Model: "test-model",
		Inbound: "openai", Stream: true, Start: time.Now().UTC(),
		StatusCode: http.StatusOK, Success: true, Debug: true,
		Attempts: []*services.AttemptRecord{first, last},
		Usage:    services.Usage{PromptTokens: 3, CompletionTokens: 4, TotalTokens: 7},
	})

	row := readLogTestRow(t, db)

	// A failed dispatch supplies no provider/key/upstream; the row falls back to
	// the last attempt in the trail.
	if row.ProviderName == nil || *row.ProviderName != "good" {
		t.Fatalf("provider_name = %v, want the last attempt's provider", row.ProviderName)
	}
	if row.ProviderID == nil || *row.ProviderID != providerID {
		t.Fatalf("provider_id = %v, want %d", row.ProviderID, providerID)
	}
	if row.KeyID == nil || *row.KeyID != keyID {
		t.Fatalf("key_id = %v, want %d", row.KeyID, keyID)
	}
	if row.ProxyID == nil || *row.ProxyID != nodeID {
		t.Fatalf("proxy_id = %v, want the last attempt's node %d", row.ProxyID, nodeID)
	}
	if row.UpstreamURL == nil || *row.UpstreamURL != upstreamURL {
		t.Fatalf("upstream_url = %v, want the last attempt's url", row.UpstreamURL)
	}
	if row.ProxyURL == nil || *row.ProxyURL != proxyURL {
		t.Fatalf("proxy_url = %v", row.ProxyURL)
	}
	if row.UpstreamModel == nil || *row.UpstreamModel != "upstream-model" {
		t.Fatalf("upstream_model = %v", row.UpstreamModel)
	}
	if row.Attempts != 2 || row.ProviderAttempts != 2 {
		t.Fatalf("attempts = %d/%d, want 2/2", row.Attempts, row.ProviderAttempts)
	}
	if row.NetworkAttempts != 2 {
		t.Fatalf("network_attempts = %d, want 2", row.NetworkAttempts)
	}

	var chain, debugTrail []map[string]any
	if err := json.Unmarshal(row.AttemptsSummary, &chain); err != nil {
		t.Fatalf("decode attempts_summary: %v", err)
	}
	if err := json.Unmarshal(row.DebugAttempts, &debugTrail); err != nil {
		t.Fatalf("decode debug_attempts: %v", err)
	}
	if len(chain) != 2 || len(debugTrail) != 2 {
		t.Fatalf("trail lengths = %d/%d, want 2/2", len(chain), len(debugTrail))
	}
	// The always-on summary must never carry headers, bodies or the egress URL.
	for i, a := range chain {
		for _, key := range []string{"req_headers", "resp_headers", "req_body", "resp_body", "proxy_url", "local_address"} {
			if _, ok := a[key]; ok {
				t.Fatalf("attempts_summary[%d] leaked %s: %v", i, key, a)
			}
		}
	}
	// The debug projection keeps the redacted headers and bodies.
	if debugTrail[0]["req_headers"] == nil || debugTrail[0]["resp_body"] == nil {
		t.Fatalf("debug_attempts lost headers/body: %v", debugTrail[0])
	}

	// Streaming usage is only known after the SSE drains, so the handler stamps
	// it on the winning attempt; both projections must carry it.
	if got, _ := debugTrail[1]["total_tokens"].(float64); got != 7 {
		t.Fatalf("debug attempt total_tokens = %v, want 7", debugTrail[1]["total_tokens"])
	}
	if got, _ := chain[1]["total_tokens"].(float64); got != 7 {
		t.Fatalf("chain attempt total_tokens = %v, want 7", chain[1]["total_tokens"])
	}
	if row.TotalTokens != 7 {
		t.Fatalf("row total_tokens = %d, want 7", row.TotalTokens)
	}
}

// The streaming stamp must not overwrite tokens the dispatcher already extracted
// for a non-stream attempt.
func TestLogRequestKeepsDispatcherTokens(t *testing.T) {
	db := logTestDB(t)
	app := &App{GDB: db}
	db.Create(&database.VoidToken{
		ID: 2, Name: "k", TokenHash: "kh2", TokenPrefix: "vs-", UserID: 1,
		AllowedModels: database.JSONOf([]string{}),
	})

	rec := &services.AttemptRecord{
		Attempt: 1, Provider: strPtr("good"), StatusCode: intRef(http.StatusOK),
		PromptTokens: 5, CompletionTokens: 6, TotalTokens: 11,
	}
	app.logRequest(logTestContext(t), requestLogInfo{
		TokenID: 2, UserSub: "u1", Model: "test-model", Inbound: "openai",
		Start: time.Now().UTC(), StatusCode: http.StatusOK, Success: true,
		Attempts: []*services.AttemptRecord{rec},
		Usage:    services.Usage{PromptTokens: 9, CompletionTokens: 9, TotalTokens: 18},
	})

	row := readLogTestRow(t, db)
	var chain []map[string]any
	if err := json.Unmarshal(row.AttemptsSummary, &chain); err != nil {
		t.Fatal(err)
	}
	if got, _ := chain[0]["total_tokens"].(float64); got != 11 {
		t.Fatalf("attempt total_tokens = %v, want the dispatcher's 11", chain[0]["total_tokens"])
	}
}

// The export is the other half of the visibility matrix: staff keep per-attempt
// headers but never bodies, and a role-group admin's export carries the chain
// only.
func TestExportPayloadVisibilityTiers(t *testing.T) {
	db := logTestDB(t)
	app := &App{GDB: db}
	row := database.RequestLog{
		TS:              time.Now().UTC(),
		AttemptsSummary: database.JSON(`[{"attempt":1,"key_preview":"sk-…test","upstream_model":"m"}]`),
		DebugAttempts:   database.JSON(`[{"attempt":1,"key_preview":"sk-…test","req_headers":{"content-type":"application/json"},"req_body":{"a":1},"resp_body":"ok"}]`),
	}
	cases := []struct {
		name        string
		uv          *core.UserView
		wantHeaders bool
	}{
		{"admin", &core.UserView{Role: "admin"}, true},
		{"role-group-admin", &core.UserView{Role: "member", AdminGroupIDs: []int{1}}, false},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			detail := app.buildRequestLogDetail(&row, tc.uv)
			payload := app.exportPayload(&detail, tc.uv, &row).(map[string]any)
			attempt := firstAttempt(payload["attempts"])
			if attempt == nil {
				t.Fatalf("export lost the attempt trail: %v", payload)
			}
			if tc.wantHeaders != (attempt["req_headers"] != nil) {
				t.Fatalf("headers visible=%v, want %v", attempt["req_headers"] != nil, tc.wantHeaders)
			}
			if attempt["req_body"] != nil || attempt["resp_body"] != nil {
				t.Fatalf("bodies leaked into the export: %v", attempt)
			}
			if attempt["key_preview"] == nil {
				t.Fatalf("staff lost the masked key preview: %v", attempt)
			}
		})
	}
}

// TestDebugCaptureIsConditional pins the default source → level mapping: a debug
// token wins over the outcome, otherwise the outcome decides, and a successful
// call from a token without debug keeps the routing chain and nothing else.
func TestDebugCaptureIsConditional(t *testing.T) {
	policy := services.CapturePolicy{Success: 1, Debug: 3, Error: 4}
	cases := []struct {
		tokenDebug bool
		success    bool
		want       int
	}{
		{true, true, 3},
		{true, false, 3},
		{false, true, 1},
		{false, false, 4},
	}
	for _, tc := range cases {
		if got := policy.LevelFor(tc.tokenDebug, !tc.success); got != tc.want {
			t.Fatalf("LevelFor(debug=%v, failed=%v) = %d, want %d",
				tc.tokenDebug, !tc.success, got, tc.want)
		}
	}
}

// TestSuccessfulRequestWithoutDebugKeepsNoTrail is the regression for a
// successful non-debug call storing the full debug projection anyway.
func TestSuccessfulRequestWithoutDebugKeepsNoTrail(t *testing.T) {
	db := logTestDB(t)
	app := &App{GDB: db}
	db.Create(&database.VoidToken{
		ID: 1, Name: "k", TokenHash: "kh", TokenPrefix: "vs-", UserID: 1,
		AllowedModels: database.JSONOf([]string{}),
	})

	app.logRequest(logTestContext(t), requestLogInfo{
		TokenID: 1, UserSub: "u1", Model: "test-model", Inbound: "openai",
		Start: time.Now().UTC(), StatusCode: http.StatusOK, Success: true, Debug: false,
		Attempts: []*services.AttemptRecord{{
			Attempt: 1, Provider: strPtr("mock"), StatusCode: intRef(http.StatusOK),
			ReqBody:  map[string]any{"messages": []any{}},
			RespBody: map[string]any{"choices": []any{}},
		}},
		Usage: services.Usage{TotalTokens: 5},
	})

	row := readLogTestRow(t, db)
	if row.Debug {
		t.Fatal("a successful non-debug request must not be flagged as a debug row")
	}
	if len(row.AttemptsSummary) == 0 {
		t.Fatal("the routing chain should still be recorded")
	}
	if len(row.DebugAttempts) != 0 {
		t.Fatalf("debug trail stored for a successful non-debug request: %s", row.DebugAttempts)
	}
}

// TestFailedRequestWithoutDebugKeepsResponseBodyOnly covers the failure
// exception: the response body is kept so the error can be read, but the request
// body is not (nobody opted into capturing it).
func TestFailedRequestWithoutDebugKeepsResponseBodyOnly(t *testing.T) {
	db := logTestDB(t)
	app := &App{GDB: db}
	db.Create(&database.VoidToken{
		ID: 1, Name: "k", TokenHash: "kh", TokenPrefix: "vs-", UserID: 1,
		AllowedModels: database.JSONOf([]string{}),
	})
	msg := "upstream mock returned 500: boom"

	app.logRequest(logTestContext(t), requestLogInfo{
		TokenID: 1, UserSub: "u1", Model: "test-model", Inbound: "openai",
		Start: time.Now().UTC(), StatusCode: http.StatusBadGateway, Success: false,
		Err:   &msg,
		Debug: false,
		Attempts: []*services.AttemptRecord{{
			Attempt: 1, Provider: strPtr("mock"), StatusCode: intRef(http.StatusInternalServerError),
			RespBody: map[string]any{"error": "boom"},
			Error:    strPtr(msg),
		}},
	})

	row := readLogTestRow(t, db)
	if !row.Debug {
		t.Fatal("a failed request should be flagged as a debug row")
	}
	if len(row.DebugAttempts) == 0 {
		t.Fatal("a failed request should keep the debug trail")
	}
	trail := string(row.DebugAttempts)
	if !strings.Contains(trail, "resp_body") {
		t.Fatalf("response body missing from the failure trail: %s", trail)
	}
	if strings.Contains(trail, "req_body") {
		t.Fatalf("request body recorded for a non-debug failure: %s", trail)
	}
}
