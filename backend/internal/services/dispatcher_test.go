package services

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"gorm.io/driver/sqlite"
	"gorm.io/gorm"

	"github.com/siiway/voidswitch/internal/config"
	"github.com/siiway/voidswitch/internal/constants"
	"github.com/siiway/voidswitch/internal/cryptoutil"
	"github.com/siiway/voidswitch/internal/database"
)

// newTestDB builds an in-memory SQLite database with the schema the dispatcher
// needs (a subset sufficient for dispatch tests). The production schema is
// PostgreSQL; this is for unit coverage of the dispatcher logic only.
func newTestDB(t *testing.T) *gorm.DB {
	t.Helper()
	dsn := fmt.Sprintf("file:dispatchertest-%d?mode=memory&cache=shared", time.Now().UnixNano())
	db, err := gorm.Open(sqlite.Open(dsn), &gorm.Config{})
	if err != nil {
		t.Fatal(err)
	}
	if err := db.AutoMigrate(&database.Provider{}, &database.ApiKey{},
		&database.ExposedModel{}, &database.Route{}, &database.RouteUpstream{},
		&database.UpstreamCooldown{}); err != nil {
		t.Fatal(err)
	}
	return db
}

func seedDispatch(t *testing.T, db *gorm.DB, upstreamURL, secret string) {
	t.Helper()
	p := database.Provider{
		UUID: "u1", Name: "mock", Slug: "mock", Type: "openai",
		BaseURL: upstreamURL, Enabled: true, Priority: 100, Weight: 1,
		Models: database.JSONOf([]string{}), ModelMap: database.JSONOf(map[string]any{}),
		ModelRoutes: database.JSONOf([]any{}), ExtraHeaders: database.JSONOf(map[string]any{}),
		KeySelectMode:                  "round_robin",
		PassthroughModels:              database.JSONOf([]string{}),
		UpstreamCooldownStatusCodes:    database.JSONOf([]int{}),
		UpstreamRetryAfterHeaders:      database.JSONOf([]string{}),
		SelectiveIgnoreRules:           database.JSONOf([]any{}),
		NormalizeDeveloperRoleToSystem: true,
		NewAPIMode:                     "auto",
	}
	if err := db.Create(&p).Error; err != nil {
		t.Fatal(err)
	}
	ct, err := cryptoutil.EncryptSecret("sk-test-key", secret)
	if err != nil {
		t.Fatal(err)
	}
	key := database.ApiKey{
		ProviderID: p.ID, KeyCiphertext: ct, KeyHash: "h1", KeyPreview: "sk-…test",
		Status: string(constants.KeyStatusActive), Weight: 1,
		Balance: database.JSONOf(map[string]any{}),
	}
	db.Create(&key)

	m := database.ExposedModel{
		ModelID: "test-model", Enabled: true,
		OpenCodeConfig:      database.JSONOf(map[string]any{}),
		AllowedRoleGroupIDs: database.JSONOf([]int{}),
		Capabilities:        database.JSONOf(map[string]any{}),
		Modalities:          database.JSONOf(map[string]any{}),
	}
	db.Create(&m)
	route := database.Route{ExposedModelID: m.ID, UpstreamSelectMode: "best", UpstreamRankAlgorithm: "weighted"}
	db.Create(&route)
	db.Create(&database.RouteUpstream{
		RouteID: route.ID, ProviderID: &p.ID, UpstreamModel: "upstream-model",
		Enabled: true, Weight: 1, KeyPool: "",
		CooldownStatusCodes: database.JSONOf([]int{}),
	})
}

func TestDispatchOpenAIToOpenAI(t *testing.T) {
	var gotModel string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if !strings.HasSuffix(r.URL.Path, "/chat/completions") {
			t.Errorf("unexpected path %s", r.URL.Path)
		}
		if r.Header.Get("Authorization") != "Bearer sk-test-key" {
			t.Errorf("bad auth header: %q", r.Header.Get("Authorization"))
		}
		var body map[string]any
		b, _ := io.ReadAll(r.Body)
		json.Unmarshal(b, &body)
		gotModel, _ = body["model"].(string)
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]any{
			"id": "chatcmpl-1", "object": "chat.completion", "model": gotModel,
			"choices": []any{map[string]any{
				"index": 0, "message": map[string]any{"role": "assistant", "content": "hello"},
				"finish_reason": "stop",
			}},
			"usage": map[string]any{"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
		})
	}))
	defer srv.Close()

	db := newTestDB(t)
	secret := "test-secret"
	seedDispatch(t, db, srv.URL, secret)

	cfg := &config.Settings{}
	cfg.Server.SecretKey = secret
	req := &DispatchRequest{
		Ctx: context.Background(), DB: db, Cfg: cfg, Pool: GetPool(),
		ExposedModel: "test-model", InboundStyle: constants.ApiStyleOpenAI,
		Body: map[string]any{
			"model":    "test-model",
			"messages": []any{map[string]any{"role": "user", "content": "hi"}},
		},
	}
	res, err := NewDispatcher(req).Do()
	if err != nil {
		t.Fatalf("dispatch: %v", err)
	}
	if gotModel != "upstream-model" {
		t.Fatalf("upstream model = %q, want upstream-model", gotModel)
	}
	var out map[string]any
	if err := json.Unmarshal(res.Body, &out); err != nil {
		t.Fatalf("response json: %v", err)
	}
	choices, _ := out["choices"].([]any)
	if len(choices) == 0 {
		t.Fatalf("no choices in response: %s", res.Body)
	}
}

func TestDispatchFailsOverOnCooldown(t *testing.T) {
	// First provider returns 500 → cooldown recorded; second provider succeeds.
	callCount := 0
	bad := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		callCount++
		w.WriteHeader(http.StatusInternalServerError)
		w.Write([]byte(`{"error":"boom"}`))
	}))
	defer bad.Close()
	good := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`{"id":"x","object":"chat.completion","choices":[{"index":0,"message":{"role":"assistant","content":"ok"},"finish_reason":"stop"}],"usage":{"prompt_tokens":1,"completion_tokens":1,"total_tokens":2}}`))
	}))
	defer good.Close()

	db := newTestDB(t)
	secret := "sec"
	seedDispatch(t, db, bad.URL, secret)
	// add second provider + upstream
	p2 := database.Provider{
		UUID: "u2", Name: "good", Slug: "good", Type: "openai", BaseURL: good.URL,
		Enabled: true, KeySelectMode: "round_robin",
		Models: database.JSONOf([]string{}), ModelMap: database.JSONOf(map[string]any{}),
		ModelRoutes: database.JSONOf([]any{}), ExtraHeaders: database.JSONOf(map[string]any{}),
		PassthroughModels:           database.JSONOf([]string{}),
		UpstreamCooldownStatusCodes: database.JSONOf([]int{}),
		UpstreamRetryAfterHeaders:   database.JSONOf([]string{}),
		SelectiveIgnoreRules:        database.JSONOf([]any{}),
	}
	db.Create(&p2)
	ct, _ := cryptoutil.EncryptSecret("sk-good", secret)
	db.Create(&database.ApiKey{ProviderID: p2.ID, KeyCiphertext: ct, KeyHash: "h2", Status: "active", Weight: 1, Balance: database.JSONOf(map[string]any{})})
	var route database.Route
	db.First(&route)
	db.Create(&database.RouteUpstream{RouteID: route.ID, ProviderID: &p2.ID, UpstreamModel: "good-model", Enabled: true, Weight: 1, CooldownStatusCodes: database.JSONOf([]int{})})

	cfg := &config.Settings{}
	cfg.Server.SecretKey = secret
	req := &DispatchRequest{
		Ctx: context.Background(), DB: db, Cfg: cfg, Pool: GetPool(),
		ExposedModel: "test-model", InboundStyle: constants.ApiStyleOpenAI,
		Body: map[string]any{"model": "test-model", "messages": []any{map[string]any{"role": "user", "content": "hi"}}},
	}
	res, err := NewDispatcher(req).Do()
	if err != nil {
		t.Fatalf("dispatch failover: %v", err)
	}
	if res.Provider.Name != "good" {
		t.Fatalf("expected failover to %q, got %q", "good", res.Provider.Name)
	}
	if callCount == 0 {
		t.Fatal("expected the bad provider to be attempted")
	}
}
