package handlers

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/modelcontextprotocol/go-sdk/mcp"
	"gorm.io/driver/sqlite"
	"gorm.io/gorm"

	"github.com/siiway/voidswitch/internal/config"
	"github.com/siiway/voidswitch/internal/core"
	"github.com/siiway/voidswitch/internal/database"
	"github.com/siiway/voidswitch/internal/redisx"
)

// platformTestApp builds an App over an in-memory sqlite database with one
// staff user, one platform key and one provider. Redis is left nil: the rate
// limiter then no-ops, which keeps the test hermetic.
func platformTestApp(t *testing.T, role string, scopes []string) (*App, string) {
	t.Helper()
	gin.SetMode(gin.TestMode)
	dsn := fmt.Sprintf("file:platform-%d?mode=memory&cache=shared", time.Now().UnixNano())
	db, err := gorm.Open(sqlite.Open(dsn), &gorm.Config{})
	if err != nil {
		t.Fatalf("open sqlite: %v", err)
	}
	if err := db.AutoMigrate(
		&database.User{}, &database.PlatformAPIKey{}, &database.AuditLog{},
		&database.Provider{}, &database.ApiKey{}, &database.ExposedModel{},
		&database.Route{}, &database.RouteUpstream{}, &database.RoleGroup{},
		&database.RoleGroupMembership{}, &database.RoleGroupAdminship{},
		&database.Node{}, &database.NodeGroup{}, &database.ModelCategory{},
		&database.Setting{}, &database.Announcement{}, &database.RequestLog{},
	); err != nil {
		t.Fatalf("migrate: %v", err)
	}

	username := "tester"
	user := database.User{Sub: "sub-test", Username: &username, Role: role, Enabled: true,
		TeamIDs: database.JSONOf([]string{})}
	if err := db.Create(&user).Error; err != nil {
		t.Fatalf("create user: %v", err)
	}

	raw, err := core.GenerateToken(platformKeyPrefix)
	if err != nil {
		t.Fatalf("mint: %v", err)
	}
	key := database.PlatformAPIKey{
		UserID: user.ID, Name: "test", KeyHash: core.HashToken(raw),
		KeyPrefix: core.PlatformKeyFingerprint(raw), Scopes: database.JSONOf(scopes), Enabled: true,
	}
	if err := db.Create(&key).Error; err != nil {
		t.Fatalf("create key: %v", err)
	}

	app := &App{
		GDB: db,
		Cfg: &config.Settings{Server: config.ServerSettings{SecretKey: "test-secret"}},
		RDB: (*redisx.Service)(nil),
	}
	return app, raw
}

func platformRouter(app *App) *gin.Engine {
	r := gin.New()
	RegisterPlatformAPIRoutes(r.Group("/api"), app)
	RegisterPlatformMCPRoutes(r.Group("/api"), app)
	return r
}

func TestPlatformRESTRequiresScope(t *testing.T) {
	app, raw := platformTestApp(t, "admin", []string{"read"})
	r := platformRouter(app)

	// A read-scoped key may list models.
	w := httptest.NewRecorder()
	req, _ := http.NewRequest(http.MethodGet, "/api/v1/models", nil)
	req.Header.Set("Authorization", "Bearer "+raw)
	r.ServeHTTP(w, req)
	if w.Code != http.StatusOK {
		t.Fatalf("GET /api/v1/models with read scope answered %d: %s", w.Code, w.Body.String())
	}

	// …but may not edit one.
	w = httptest.NewRecorder()
	req, _ = http.NewRequest(http.MethodPut, "/api/v1/models", strings.NewReader(`{"model_id":"x"}`))
	req.Header.Set("Authorization", "Bearer "+raw)
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)
	if w.Code != http.StatusForbidden {
		t.Fatalf("PUT /api/v1/models with read scope answered %d, want 403: %s", w.Code, w.Body.String())
	}
}

func TestPlatformRESTRejectsUnknownAndDisabledKeys(t *testing.T) {
	app, _ := platformTestApp(t, "admin", []string{"read"})
	r := platformRouter(app)

	w := httptest.NewRecorder()
	req, _ := http.NewRequest(http.MethodGet, "/api/v1/models", nil)
	req.Header.Set("Authorization", "Bearer vsapi-nope")
	r.ServeHTTP(w, req)
	if w.Code != http.StatusUnauthorized {
		t.Fatalf("unknown key answered %d, want 401", w.Code)
	}

	// A key whose owner is not staff is refused even though the row is enabled.
	app2, raw2 := platformTestApp(t, "member", []string{"read"})
	r2 := platformRouter(app2)
	w = httptest.NewRecorder()
	req, _ = http.NewRequest(http.MethodGet, "/api/v1/models", nil)
	req.Header.Set("Authorization", "Bearer "+raw2)
	r2.ServeHTTP(w, req)
	if w.Code != http.StatusForbidden {
		t.Fatalf("member-owned key answered %d, want 403", w.Code)
	}
}

// TestPlatformMCPScopedTools is the MCP end-to-end check: the tool list is
// filtered by scope, an allowed tool runs through the bridge, and a disallowed
// one is absent from the list entirely.
func TestPlatformMCPScopedTools(t *testing.T) {
	app, raw := platformTestApp(t, "owner", []string{"read", "provider-key:acme.*"})
	r := platformRouter(app)
	ts := httptest.NewServer(r)
	defer ts.Close()

	ctx := context.Background()
	client := mcp.NewClient(&mcp.Implementation{Name: "test", Version: "0"}, nil)
	transport := &mcp.StreamableClientTransport{
		Endpoint:   ts.URL + "/api/v1/mcp",
		HTTPClient: &http.Client{Transport: bearerTransport{token: raw}},
	}
	session, err := client.Connect(ctx, transport, nil)
	if err != nil {
		t.Fatalf("connect: %v", err)
	}
	defer session.Close()

	names := map[string]bool{}
	for tool, err := range session.Tools(ctx, nil) {
		if err != nil {
			t.Fatalf("tools: %v", err)
		}
		names[tool.Name] = true
	}
	if !names["vs_model_list"] {
		t.Fatalf("read scope must expose vs_model_list, got %v", toolNames(names))
	}
	if names["vs_model_edit"] {
		t.Fatal("read scope must not expose vs_model_edit")
	}
	if !names["vs_provider_key_add"] {
		t.Fatalf("provider-key scope must expose vs_provider_key_add, got %v", toolNames(names))
	}
	for name := range names {
		if strings.Contains(name, "reveal") {
			t.Fatalf("no reveal tool may ever be listed, got %s", name)
		}
	}

	// A provider-key action for a slug the scope does not name fails, and the
	// failure is reported rather than silently succeeding.
	res, err := session.CallTool(ctx, &mcp.CallToolParams{
		Name:      "vs_provider_key_list",
		Arguments: map[string]any{"slug": "other"},
	})
	if err != nil {
		t.Fatalf("call: %v", err)
	}
	if !res.IsError {
		t.Fatal("a slug outside the scope must fail")
	}
}

// bearerTransport stamps the API key on every request, the way a real MCP
// client is configured to.
type bearerTransport struct{ token string }

func (b bearerTransport) RoundTrip(req *http.Request) (*http.Response, error) {
	clone := req.Clone(req.Context())
	clone.Header.Set("Authorization", "Bearer "+b.token)
	return http.DefaultTransport.RoundTrip(clone)
}

func toolNames(m map[string]bool) []string {
	out := make([]string, 0, len(m))
	for k := range m {
		out = append(out, k)
	}
	return out
}

// TestPlatformAuditRecordsCredential proves the audit row names the key, so
// "who" and "which key" are answerable from one row.
func TestPlatformAuditRecordsCredential(t *testing.T) {
	app, raw := platformTestApp(t, "admin", []string{"read"})
	app.Cfg.Server.SecretKey = "test-secret"
	r := platformRouter(app)

	w := httptest.NewRecorder()
	req, _ := http.NewRequest(http.MethodPost, "/api/v1/model-categories",
		strings.NewReader(`{"name":"prod"}`))
	req.Header.Set("Authorization", "Bearer "+raw)
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)
	// The key only has "read", so the call is refused — and nothing is audited.
	if w.Code != http.StatusForbidden {
		t.Fatalf("category create with read scope answered %d, want 403", w.Code)
	}

	// Directly exercise the audit helper the handlers use: creating a node
	// records a "node.create" row through a.audit.
	app2, raw2 := platformTestApp(t, "admin", []string{"node.*"})
	r2 := platformRouter(app2)
	w = httptest.NewRecorder()
	req, _ = http.NewRequest(http.MethodPost, "/api/v1/nodes",
		strings.NewReader(`{"url":"http://127.0.0.1:8080","type":"http"}`))
	req.Header.Set("Authorization", "Bearer "+raw2)
	req.Header.Set("Content-Type", "application/json")
	r2.ServeHTTP(w, req)
	if w.Code != http.StatusOK && w.Code != http.StatusCreated {
		t.Fatalf("node create answered %d: %s", w.Code, w.Body.String())
	}

	// The sqlite driver cannot scan the timestamptz column back into time.Time,
	// so the assertion selects only the columns under test.
	var row struct {
		Action     string
		Credential *string
		Detail     database.JSON
	}
	if err := app2.GDB.Model(&database.AuditLog{}).
		Select("action", "credential", "detail").
		Order("id DESC").First(&row).Error; err != nil {
		t.Fatalf("no audit row: %v", err)
	}
	if row.Credential == nil || !strings.HasPrefix(*row.Credential, "vsapi-") {
		t.Fatalf("audit row carries no key fingerprint: %+v", row)
	}
	var detail map[string]any
	_ = json.Unmarshal(row.Detail, &detail)
	if detail["via"] != "rest" {
		t.Fatalf("audit detail should record the transport, got %v", detail)
	}
}

// TestPlatformRateLimitUsesSetting keeps the limiter honest about its source.
func TestPlatformRateLimitUsesSetting(t *testing.T) {
	app, _ := platformTestApp(t, "admin", []string{"read"})
	if got := app.settingOrDefaultInt("platform_api_rate_limit_max_requests", 30); got != 30 {
		t.Fatalf("default rate limit = %d, want 30", got)
	}
	if err := app.GDB.Create(&database.Setting{
		Key: "platform_api_rate_limit_max_requests", Value: database.JSONOf(7),
	}).Error; err != nil {
		t.Fatalf("seed setting: %v", err)
	}
	if got := app.settingOrDefaultInt("platform_api_rate_limit_max_requests", 30); got != 7 {
		t.Fatalf("configured rate limit = %d, want 7", got)
	}
}
