package services

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"testing"

	"gorm.io/gorm"

	"github.com/siiway/voidswitch/internal/config"
	"github.com/siiway/voidswitch/internal/constants"
	"github.com/siiway/voidswitch/internal/cryptoutil"
	"github.com/siiway/voidswitch/internal/database"
)

// Passthrough entries use the grammar "exposed [=> upstream] [@ pool]".
func TestParsePassthroughEntry(t *testing.T) {
	tests := []struct {
		name, entry             string
		exposed, upstream, pool string
	}{
		{"bare id", "gpt-4o", "gpt-4o", "gpt-4o", ""},
		{"upstream override", "fast-model => gpt-4o-mini", "fast-model", "gpt-4o-mini", ""},
		{"key pool", "gpt-4o @ team-a", "gpt-4o", "gpt-4o", "team-a"},
		{"all three", "fast => gpt-4o-mini @ team-a", "fast", "gpt-4o-mini", "team-a"},
		{"whitespace", "  fast  =>  gpt-4o  @  pool1  ", "fast", "gpt-4o", "pool1"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			exposed, upstream, pool := ParsePassthroughEntry(tt.entry)
			if exposed != tt.exposed || upstream != tt.upstream || pool != tt.pool {
				t.Fatalf("ParsePassthroughEntry(%q) = (%q, %q, %q), want (%q, %q, %q)",
					tt.entry, exposed, upstream, pool, tt.exposed, tt.upstream, tt.pool)
			}
		})
	}
}

// seedPassthrough creates an enabled passthrough provider with one key and the
// given whitelist, and no exposed model / route at all — passthrough models must
// dispatch without either.
func seedPassthrough(t *testing.T, db *gorm.DB, upstreamURL, secret string, entries []string) *database.Provider {
	t.Helper()
	p := database.Provider{
		UUID: "pt-uuid", Name: "pt", Slug: "pt", Type: "openai",
		BaseURL: upstreamURL, Enabled: true, Priority: 100, Weight: 1,
		Models: database.JSONOf([]string{}), ModelMap: database.JSONOf(map[string]any{}),
		ModelRoutes: database.JSONOf([]any{}), ExtraHeaders: database.JSONOf(map[string]any{}),
		KeySelectMode:                  "round_robin",
		PassthroughEnabled:             true,
		PassthroughModels:              database.JSONOf(entries),
		UpstreamCooldownStatusCodes:    database.JSONOf([]int{}),
		UpstreamRetryAfterHeaders:      database.JSONOf([]string{}),
		SelectiveIgnoreRules:           database.JSONOf([]any{}),
		NormalizeDeveloperRoleToSystem: true,
		NewAPIMode:                     "auto",
	}
	if err := db.Create(&p).Error; err != nil {
		t.Fatal(err)
	}
	ct, err := cryptoutil.EncryptSecret("sk-pt-key", secret)
	if err != nil {
		t.Fatal(err)
	}
	if err := db.Create(&database.ApiKey{
		ProviderID: p.ID, KeyCiphertext: ct, KeyHash: "pt-h1", KeyPreview: "sk-…pt",
		Status: string(constants.KeyStatusActive), Weight: 1,
		Balance: database.JSONOf(map[string]any{}),
	}).Error; err != nil {
		t.Fatal(err)
	}
	return &p
}

// A passthrough id must dispatch to the provider and rewrite the outgoing model
// to the entry's upstream id, without any exposed model or route existing.
func TestPassthroughDispatchesWithoutRoute(t *testing.T) {
	var gotModel string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		b, _ := io.ReadAll(r.Body)
		var body map[string]any
		json.Unmarshal(b, &body)
		gotModel, _ = body["model"].(string)
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]any{
			"id": "c1", "object": "chat.completion", "model": gotModel,
			"choices": []any{map[string]any{
				"index": 0, "message": map[string]any{"role": "assistant", "content": "ok"},
				"finish_reason": "stop",
			}},
			"usage": map[string]any{"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
		})
	}))
	defer srv.Close()

	db := newTestDB(t)
	secret := "test-secret"
	seedPassthrough(t, db, srv.URL, secret, []string{"fast-model => upstream-model"})

	cfg := &config.Settings{}
	cfg.Server.SecretKey = secret
	req := &DispatchRequest{
		Ctx: context.Background(), DB: db, Cfg: cfg, Pool: GetPool(),
		ExposedModel: "pt/fast-model", InboundStyle: constants.ApiStyleOpenAI,
		Body: map[string]any{"model": "pt/fast-model", "messages": []any{}},
		Kind: KindChat,
	}
	res, err := NewDispatcher(req).Do()
	if err != nil {
		t.Fatalf("passthrough dispatch failed: %v", err)
	}
	if res.StatusCode != http.StatusOK {
		t.Fatalf("status = %d", res.StatusCode)
	}
	if gotModel != "upstream-model" {
		t.Fatalf("upstream saw model %q, want upstream-model", gotModel)
	}
}

// A bare entry (no "=>") sends the exposed id itself upstream.
func TestPassthroughBareEntryKeepsID(t *testing.T) {
	var gotModel string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		b, _ := io.ReadAll(r.Body)
		var body map[string]any
		json.Unmarshal(b, &body)
		gotModel, _ = body["model"].(string)
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]any{
			"id": "c1", "object": "chat.completion", "model": gotModel,
			"choices": []any{map[string]any{
				"index": 0, "message": map[string]any{"role": "assistant", "content": "ok"},
				"finish_reason": "stop",
			}},
			"usage": map[string]any{"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
		})
	}))
	defer srv.Close()

	db := newTestDB(t)
	secret := "test-secret"
	seedPassthrough(t, db, srv.URL, secret, []string{"gpt-4o"})

	cfg := &config.Settings{}
	cfg.Server.SecretKey = secret
	req := &DispatchRequest{
		Ctx: context.Background(), DB: db, Cfg: cfg, Pool: GetPool(),
		ExposedModel: "pt/gpt-4o", InboundStyle: constants.ApiStyleOpenAI,
		Body: map[string]any{"model": "pt/gpt-4o", "messages": []any{}},
		Kind: KindChat,
	}
	if _, err := NewDispatcher(req).Do(); err != nil {
		t.Fatalf("bare passthrough dispatch failed: %v", err)
	}
	if gotModel != "gpt-4o" {
		t.Fatalf("upstream saw model %q, want gpt-4o", gotModel)
	}
}

// An id that is not in the whitelist must be rejected, not silently dispatched.
func TestPassthroughUnknownIDRejected(t *testing.T) {
	db := newTestDB(t)
	seedPassthrough(t, db, "http://127.0.0.1:1", "test-secret", []string{"allowed-model"})

	cfg := &config.Settings{}
	cfg.Server.SecretKey = "test-secret"
	req := &DispatchRequest{
		Ctx: context.Background(), DB: db, Cfg: cfg, Pool: GetPool(),
		ExposedModel: "pt/not-allowed", InboundStyle: constants.ApiStyleOpenAI,
		Body: map[string]any{"model": "pt/not-allowed"}, Kind: KindChat,
	}
	if _, err := NewDispatcher(req).Do(); err == nil {
		t.Fatal("expected an error for a model outside the whitelist")
	}
}

// A disabled provider must reject even a whitelisted model.
func TestPassthroughDisabledProviderRejected(t *testing.T) {
	db := newTestDB(t)
	p := seedPassthrough(t, db, "http://127.0.0.1:1", "test-secret", []string{"m1"})
	db.Model(&database.Provider{}).Where("id = ?", p.ID).Update("enabled", false)

	cfg := &config.Settings{}
	cfg.Server.SecretKey = "test-secret"
	req := &DispatchRequest{
		Ctx: context.Background(), DB: db, Cfg: cfg, Pool: GetPool(),
		ExposedModel: "pt/m1", InboundStyle: constants.ApiStyleOpenAI,
		Body: map[string]any{"model": "pt/m1"}, Kind: KindChat,
	}
	if _, err := NewDispatcher(req).Do(); err == nil {
		t.Fatal("expected an error for a disabled provider")
	}
}

// A non-passthrough provider must not be treated as one.
func TestPassthroughRequiresProviderFlag(t *testing.T) {
	db := newTestDB(t)
	p := seedPassthrough(t, db, "http://127.0.0.1:1", "test-secret", []string{"m1"})
	db.Model(&database.Provider{}).Where("id = ?", p.ID).Update("passthrough_enabled", false)

	cfg := &config.Settings{}
	cfg.Server.SecretKey = "test-secret"
	req := &DispatchRequest{
		Ctx: context.Background(), DB: db, Cfg: cfg, Pool: GetPool(),
		ExposedModel: "pt/m1", InboundStyle: constants.ApiStyleOpenAI,
		Body: map[string]any{"model": "pt/m1"}, Kind: KindChat,
	}
	if _, err := NewDispatcher(req).Do(); err == nil {
		t.Fatal("expected an error when passthrough is disabled on the provider")
	}
}

// An exposed model whose id contains a slash must keep its own route. It must
// not be captured by a provider whose slug happens to match its prefix — that
// was the bug that made such models lose route editing.
func TestExposedSlashModelBeatsPassthrough(t *testing.T) {
	var gotModel string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		b, _ := io.ReadAll(r.Body)
		var body map[string]any
		json.Unmarshal(b, &body)
		gotModel, _ = body["model"].(string)
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]any{
			"id": "c1", "object": "chat.completion", "model": gotModel,
			"choices": []any{map[string]any{
				"index": 0, "message": map[string]any{"role": "assistant", "content": "ok"},
				"finish_reason": "stop",
			}},
			"usage": map[string]any{"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
		})
	}))
	defer srv.Close()

	db := newTestDB(t)
	secret := "test-secret"
	// The provider also whitelists the same id as a passthrough model.
	p := seedPassthrough(t, db, srv.URL, secret, []string{"routed-model"})

	// A real exposed model owns "pt/routed-model" and routes to a different
	// upstream model.
	m := database.ExposedModel{
		ModelID: "pt/routed-model", Enabled: true,
		OpenCodeConfig:      database.JSONOf(map[string]any{}),
		AllowedRoleGroupIDs: database.JSONOf([]int{}),
		Capabilities:        database.JSONOf(map[string]any{}),
		Modalities:          database.JSONOf(map[string]any{}),
	}
	db.Create(&m)
	route := database.Route{ExposedModelID: m.ID, UpstreamSelectMode: "best", UpstreamRankAlgorithm: "weighted"}
	db.Create(&route)
	db.Create(&database.RouteUpstream{
		RouteID: route.ID, ProviderID: &p.ID, UpstreamModel: "routed-upstream",
		Enabled: true, Weight: 1, KeyPool: "",
		CooldownStatusCodes: database.JSONOf([]int{}),
	})

	cfg := &config.Settings{}
	cfg.Server.SecretKey = secret
	req := &DispatchRequest{
		Ctx: context.Background(), DB: db, Cfg: cfg, Pool: GetPool(),
		ExposedModel: "pt/routed-model", InboundStyle: constants.ApiStyleOpenAI,
		Body: map[string]any{"model": "pt/routed-model", "messages": []any{}},
		Kind: KindChat,
	}
	if _, err := NewDispatcher(req).Do(); err != nil {
		t.Fatalf("exposed model with a slash failed to dispatch: %v", err)
	}
	if gotModel != "routed-upstream" {
		t.Fatalf("upstream saw model %q, want routed-upstream (the route must win over passthrough)", gotModel)
	}
}

// Setting role groups on a passthrough model creates an exposed row for its id
// but no route. That row must not divert the request into route resolution —
// the model is still served by the passthrough whitelist.
func TestPassthroughWithAccessRowStillDispatches(t *testing.T) {
	var gotModel string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		b, _ := io.ReadAll(r.Body)
		var body map[string]any
		json.Unmarshal(b, &body)
		gotModel, _ = body["model"].(string)
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]any{
			"id": "c1", "object": "chat.completion", "model": gotModel,
			"choices": []any{map[string]any{
				"index": 0, "message": map[string]any{"role": "assistant", "content": "ok"},
				"finish_reason": "stop",
			}},
			"usage": map[string]any{"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
		})
	}))
	defer srv.Close()

	db := newTestDB(t)
	secret := "test-secret"
	seedPassthrough(t, db, srv.URL, secret, []string{"member-model"})

	// The model card created an access row (role groups set) but no route.
	db.Create(&database.ExposedModel{
		ModelID: "pt/member-model", Enabled: true,
		OpenCodeConfig:      database.JSONOf(map[string]any{}),
		AllowedRoleGroupIDs: database.JSONOf([]int{3}),
		Capabilities:        database.JSONOf(map[string]any{}),
		Modalities:          database.JSONOf(map[string]any{}),
	})

	cfg := &config.Settings{}
	cfg.Server.SecretKey = secret
	req := &DispatchRequest{
		Ctx: context.Background(), DB: db, Cfg: cfg, Pool: GetPool(),
		ExposedModel: "pt/member-model", InboundStyle: constants.ApiStyleOpenAI,
		Body: map[string]any{"model": "pt/member-model", "messages": []any{}},
		Kind: KindChat,
	}
	if _, err := NewDispatcher(req).Do(); err != nil {
		t.Fatalf("passthrough with an access row failed to dispatch: %v", err)
	}
	if gotModel != "member-model" {
		t.Fatalf("upstream saw model %q, want member-model", gotModel)
	}
}
