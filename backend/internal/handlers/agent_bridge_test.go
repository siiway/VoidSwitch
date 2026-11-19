package handlers

import (
	"net/http"
	"net/http/httptest"
	"strconv"
	"strings"
	"testing"

	"github.com/siiway/voidswitch/internal/database"
)

// TestEveryToolDeclaresItsPathParams guards the bridge's contract: every ":name"
// placeholder in a tool's REST path must have a matching entry in Params, so the
// generated tool schema documents the argument the handler needs. A placeholder
// without a parameter is how a tool silently addresses id=0.
func TestEveryToolDeclaresItsPathParams(t *testing.T) {
	app, _ := platformTestApp(t, "owner", []string{"*"})
	for _, tool := range app.platformTools() {
		declared := map[string]bool{}
		for _, p := range tool.Params {
			declared[p.Name] = true
			if !p.InPath {
				continue
			}
			if !strings.Contains(tool.Path, ":"+p.Name) {
				t.Fatalf("%s: param %q is marked InPath but %q has no placeholder",
					tool.Action, p.Name, tool.Path)
			}
		}
		for _, seg := range strings.Split(tool.Path, "/") {
			if !strings.HasPrefix(seg, ":") {
				continue
			}
			name := strings.TrimPrefix(seg, ":")
			if !declared[name] {
				t.Fatalf("%s: path placeholder %q is not declared in Params", tool.Action, name)
			}
		}
		for aliasFrom, aliasTo := range tool.ParamAlias {
			if aliasFrom == aliasTo {
				t.Errorf("%s: alias %q->%q is redundant", tool.Action, aliasFrom, aliasTo)
			}
			if aliasFrom == "" || aliasTo == "" {
				t.Fatalf("%s: empty alias %q->%q", tool.Action, aliasFrom, aliasTo)
			}
		}
	}
}

// TestBridgePopulatesGinParams is the regression test for the bug that made every
// single-object tool resolve to id=0: the synthetic context must carry the path
// parameters the handler reads through c.Param.
func TestBridgePopulatesGinParams(t *testing.T) {
	b := &bridge{alias: map[string]string{}}
	b.alias["model_id"] = "id"

	cases := []struct {
		specPath string
		args     map[string]any
		wantPath string
		want     map[string]string
	}{
		{"/providers/:id", map[string]any{"id": 7}, "/providers/7", map[string]string{"id": "7"}},
		{
			"/models/:model_id/route", map[string]any{"model_id": "fast-coder"},
			"/models/fast-coder/route", map[string]string{"model_id": "fast-coder"},
		},
		{
			"/providers/by-slug/:slug/keys/:key_id",
			map[string]any{"slug": "acme", "key_id": float64(12)},
			"/providers/by-slug/acme/keys/12", map[string]string{"slug": "acme", "key_id": "12"},
		},
		// A handler that reads c.Param("id") while the spec exposes model_id.
		{
			"/models/:model_id/route", map[string]any{"model_id": "x"},
			"/models/x/route", map[string]string{"model_id": "x"},
		},
	}
	for _, tc := range cases {
		path, params, _ := b.split(tc.specPath, tc.args)
		if path != tc.wantPath {
			t.Fatalf("%s: path = %q, want %q", tc.specPath, path, tc.wantPath)
		}
		got := map[string]string{}
		for _, p := range params {
			got[p.Key] = p.Value
		}
		for k, v := range tc.want {
			if got[k] != v {
				t.Fatalf("%s: param %q = %q, want %q (all: %v)", tc.specPath, k, got[k], v, got)
			}
		}
	}
}

// TestProviderKeyListResolvesSlug drives a real handler through the bridge, which
// only works if the slug (and the provider id derived from it) survive the trip.
func TestProviderKeyListResolvesSlug(t *testing.T) {
	app, raw := platformTestApp(t, "owner", []string{"provider-key:acme.*"})
	provider := createTestProvider(t, app, "acme")
	if err := app.GDB.Create(&database.ApiKey{
		ProviderID: provider.ID, KeyCiphertext: "ct", KeyHash: "h1",
		KeyPreview: "sk-a…wxyz", Pool: "", SortOrder: 1, Status: "active",
		Balance: database.JSONOf(map[string]any{}),
	}).Error; err != nil {
		t.Fatalf("seed key: %v", err)
	}

	r := platformRouter(app)
	w := httptest.NewRecorder()
	req, _ := http.NewRequest(http.MethodGet, "/api/v1/providers/by-slug/acme/keys", nil)
	req.Header.Set("Authorization", "Bearer "+raw)
	r.ServeHTTP(w, req)
	if w.Code != http.StatusOK {
		t.Fatalf("provider key list answered %d: %s", w.Code, w.Body.String())
	}
	// The list must not leak a partial plaintext of the upstream credential.
	if strings.Contains(w.Body.String(), "key_preview") {
		t.Fatalf("provider key list leaked key_preview: %s", w.Body.String())
	}
	if !strings.Contains(w.Body.String(), `"id"`) {
		t.Fatalf("provider key list returned no keys: %s", w.Body.String())
	}

	// Another slug is refused before the handler runs.
	w = httptest.NewRecorder()
	req, _ = http.NewRequest(http.MethodGet, "/api/v1/providers/by-slug/other/keys", nil)
	req.Header.Set("Authorization", "Bearer "+raw)
	r.ServeHTTP(w, req)
	if w.Code != http.StatusNotFound && w.Code != http.StatusForbidden {
		t.Fatalf("unknown slug answered %d, want 404/403", w.Code)
	}
}

// TestProviderKeyDeleteOnlyTouchesOneKey is the regression test for the "kid=0"
// class of bug: deleting one key must leave the provider's other keys alone.
func TestProviderKeyDeleteOnlyTouchesOneKey(t *testing.T) {
	app, raw := platformTestApp(t, "owner", []string{"provider-key:acme.*"})
	provider := createTestProvider(t, app, "acme")
	keys := []database.ApiKey{
		{ProviderID: provider.ID, KeyCiphertext: "ct1", KeyHash: "k1", KeyPreview: "a",
			SortOrder: 1, Status: "active", Balance: database.JSONOf(map[string]any{})},
		{ProviderID: provider.ID, KeyCiphertext: "ct2", KeyHash: "k2", KeyPreview: "b",
			SortOrder: 2, Status: "active", Balance: database.JSONOf(map[string]any{})},
	}
	for i := range keys {
		if err := app.GDB.Create(&keys[i]).Error; err != nil {
			t.Fatalf("seed key: %v", err)
		}
	}

	r := platformRouter(app)
	w := httptest.NewRecorder()
	req, _ := http.NewRequest(http.MethodDelete,
		"/api/v1/providers/by-slug/acme/keys/"+strconv.Itoa(keys[0].ID), nil)
	req.Header.Set("Authorization", "Bearer "+raw)
	r.ServeHTTP(w, req)
	if w.Code != http.StatusNoContent {
		t.Fatalf("delete answered %d: %s", w.Code, w.Body.String())
	}
	var remaining int64
	app.GDB.Model(&database.ApiKey{}).Where("provider_id = ?", provider.ID).Count(&remaining)
	if remaining != 1 {
		t.Fatalf("%d keys remain, want 1", remaining)
	}
	var survivor database.ApiKey
	app.GDB.Where("provider_id = ?", provider.ID).First(&survivor)
	if survivor.ID != keys[1].ID {
		t.Fatalf("deleted the wrong key: survivor id %d, want %d", survivor.ID, keys[1].ID)
	}
}

// TestAdminCannotEscalateThroughUserEdit is the regression test for the
// privilege-escalation path: an admin's platform key must not be able to promote
// anyone (itself included) to owner, because the dashboard route for user edits
// is owner-only.
func TestAdminCannotEscalateThroughUserEdit(t *testing.T) {
	app, raw := platformTestApp(t, "admin", []string{"user.list", "user.get", "user.force-logout"})
	platform := platformRouter(app)

	w := httptest.NewRecorder()
	req, _ := http.NewRequest(http.MethodPatch, "/api/v1/users/1",
		strings.NewReader(`{"role":"owner"}`))
	req.Header.Set("Authorization", "Bearer "+raw)
	req.Header.Set("Content-Type", "application/json")
	platform.ServeHTTP(w, req)
	if w.Code != http.StatusForbidden {
		t.Fatalf("admin key promoted a user with status %d: %s", w.Code, w.Body.String())
	}

	// Even if the key somehow carried the scope, the owner-only gate must hold.
	app2, raw2 := platformTestApp(t, "admin", []string{"user.edit"})
	platform2 := platformRouter(app2)
	w = httptest.NewRecorder()
	req, _ = http.NewRequest(http.MethodPatch, "/api/v1/users/1",
		strings.NewReader(`{"role":"owner"}`))
	req.Header.Set("Authorization", "Bearer "+raw2)
	req.Header.Set("Content-Type", "application/json")
	platform2.ServeHTTP(w, req)
	if w.Code != http.StatusForbidden {
		t.Fatalf("owner-only gate failed for admin: %d %s", w.Code, w.Body.String())
	}
}

func createTestProvider(t *testing.T, app *App, slug string) database.Provider {
	t.Helper()
	p := database.Provider{
		UUID: "uuid-" + slug, Name: slug, Slug: slug, Type: "openai",
		BaseURL: "https://example.test", Enabled: true, Priority: 100, Weight: 1,
		Models: database.JSONOf([]string{}), ModelMap: database.JSONOf(map[string]any{}),
		ModelRoutes:                    database.JSONOf([]any{}),
		ExtraHeaders:                   database.JSONOf(map[string]any{}),
		PassthroughModels:              database.JSONOf([]string{}),
		SelectiveIgnoreRules:           database.JSONOf([]any{}),
		UpstreamCooldownStatusCodes:    database.JSONOf([]int{}),
		UpstreamRetryAfterHeaders:      database.JSONOf([]string{}),
		NormalizeDeveloperRoleToSystem: true,
		KeySelectMode:                  "round_robin", NewAPIMode: "auto",
	}
	if err := app.GDB.Create(&p).Error; err != nil {
		t.Fatalf("create provider: %v", err)
	}
	return p
}
