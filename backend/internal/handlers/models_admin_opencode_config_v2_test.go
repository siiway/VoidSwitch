package handlers

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/gin-gonic/gin"

	"github.com/siiway/voidswitch/internal/core"
	"github.com/siiway/voidswitch/internal/database"
)

// modelAdminApp is the sqlite-backed App the model-admin handlers need: the
// tables they touch beyond the metadata row (routes, categories, audit) must
// exist, otherwise the queries fail noisily even though the handler ignores
// their errors.
func modelAdminApp(t *testing.T) *App {
	t.Helper()
	db := newTestDB(t)
	if err := db.AutoMigrate(
		&database.Route{}, &database.RouteUpstream{},
		&database.ModelCategory{}, &database.AuditLog{},
	); err != nil {
		t.Fatalf("migrate: %v", err)
	}
	return &App{GDB: db}
}

// callModelAdmin invokes a model-admin handler with an authenticated owner, the
// way the dashboard does, and returns the decoded JSON body.
func callModelAdmin(t *testing.T, a *App, handler gin.HandlerFunc, method, target, body string) map[string]any {
	t.Helper()
	gin.SetMode(gin.TestMode)
	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	c.Request = httptest.NewRequest(method, target, strings.NewReader(body))
	c.Request.Header.Set("Content-Type", "application/json")
	c.Set(core.CtxUser, &core.UserView{
		User: &database.User{ID: 1, Sub: "owner-sub", Role: "owner"},
	})
	handler(c)
	if w.Code != http.StatusOK {
		t.Fatalf("%s %s answered %d: %s", method, target, w.Code, w.Body.String())
	}
	var out map[string]any
	if err := json.Unmarshal(w.Body.Bytes(), &out); err != nil {
		t.Fatalf("%s %s returned invalid JSON: %v (%s)", method, target, err, w.Body.String())
	}
	return out
}

// loadModelColumn reads one model row back, so the assertions run against what
// was persisted rather than what the handler echoed.
func loadModelColumn(t *testing.T, a *App, modelID string) database.ExposedModel {
	t.Helper()
	var row database.ExposedModel
	if err := a.GDB.Where("model_id = ?", modelID).First(&row).Error; err != nil {
		t.Fatalf("load %s: %v", modelID, err)
	}
	return row
}

// PUT /api/models must accept, persist and echo the V2 block, and a later edit
// that omits the field must leave the stored block alone (a scripted client only
// sends what it changes). The two blocks must stay independent.
func TestModelUpsertRoundTripsOpencodeConfigV2(t *testing.T) {
	a := modelAdminApp(t)
	body := `{"model_id":"acme/m","display_name":"M",` +
		`"opencode_config":{"name":"v1"},` +
		`"opencode_config_v2":{"capabilities":{"input":["text","pdf"],"tools":true},"variants":[{"id":"max"}]}}`
	out := callModelAdmin(t, a, a.modelsUpsert, http.MethodPut, "/api/models", body)

	v2, ok := out["opencode_config_v2"].(map[string]any)
	if !ok {
		t.Fatalf("the response lost opencode_config_v2: %v", out)
	}
	caps, _ := v2["capabilities"].(map[string]any)
	if caps["tools"] != true {
		t.Fatalf("the response lost the V2 capabilities: %v", v2)
	}
	if input, _ := caps["input"].([]any); len(input) != 2 || input[1] != "pdf" {
		t.Fatalf("the response lost the V2 input list: %v", caps["input"])
	}
	v1, ok := out["opencode_config"].(map[string]any)
	if !ok || v1["name"] != "v1" {
		t.Fatalf("the response lost the V1 block: %v", out["opencode_config"])
	}
	if _, leaked := v1["capabilities"]; leaked {
		t.Fatalf("the V2 block leaked into the V1 one: %v", v1)
	}

	row := loadModelColumn(t, a, "acme/m")
	var stored map[string]any
	if err := json.Unmarshal(row.OpenCodeConfigV2, &stored); err != nil {
		t.Fatalf("stored opencode_config_v2 is invalid JSON: %v (%s)", err, row.OpenCodeConfigV2)
	}
	if variants, _ := stored["variants"].([]any); len(variants) != 1 {
		t.Fatalf("stored opencode_config_v2 = %s, want the V2 variants", row.OpenCodeConfigV2)
	}

	// An edit that only mentions the V1 block must not wipe the V2 one.
	callModelAdmin(t, a, a.modelsUpsert, http.MethodPut, "/api/models",
		`{"model_id":"acme/m","opencode_config":{"name":"v1b"}}`)
	row = loadModelColumn(t, a, "acme/m")
	if !strings.Contains(string(row.OpenCodeConfigV2), `"variants"`) {
		t.Fatalf("an edit without the field wiped the V2 block: %s", row.OpenCodeConfigV2)
	}
	if !strings.Contains(string(row.OpenCodeConfig), "v1b") {
		t.Fatalf("the V1 block was not updated: %s", row.OpenCodeConfig)
	}
}

// The batch dialog offers merge and overwrite for the V2 block; both must reach
// the stored column, and merge must recurse into nested blocks.
func TestModelBatchOpencodeConfigV2MergeAndOverwrite(t *testing.T) {
	a := modelAdminApp(t)
	for _, id := range []string{"acme/one", "acme/two"} {
		row := database.ExposedModel{
			ModelID:             id,
			Enabled:             true,
			OpenCodeConfig:      database.JSONOf(map[string]any{}),
			OpenCodeConfigV2:    database.JSONOf(map[string]any{"name": "keep", "limit": map[string]any{"context": 1000}}),
			AllowedRoleGroupIDs: database.JSONOf([]int{}),
			Capabilities:        database.JSONOf(map[string]any{}),
			Modalities:          database.JSONOf(map[string]any{}),
		}
		if err := a.GDB.Create(&row).Error; err != nil {
			t.Fatalf("seed %s: %v", id, err)
		}
	}

	out := callModelAdmin(t, a, a.modelsBatch, http.MethodPost, "/api/models/batch",
		`{"model_ids":["acme/one","acme/two"],"opencode_config_v2":{"limit":{"output":8}}}`)
	if out["updated"] != float64(2) {
		t.Fatalf("updated = %v, want 2", out["updated"])
	}
	for _, id := range []string{"acme/one", "acme/two"} {
		var stored map[string]any
		row := loadModelColumn(t, a, id)
		if err := json.Unmarshal(row.OpenCodeConfigV2, &stored); err != nil {
			t.Fatalf("%s: stored opencode_config_v2 is invalid JSON: %v (%s)", id, err, row.OpenCodeConfigV2)
		}
		limit, _ := stored["limit"].(map[string]any)
		if limit["context"] != float64(1000) || limit["output"] != float64(8) {
			t.Fatalf("%s limit = %v, want the merged context+output", id, stored["limit"])
		}
		if stored["name"] != "keep" {
			t.Fatalf("%s lost the existing name: %v", id, stored)
		}
	}

	callModelAdmin(t, a, a.modelsBatch, http.MethodPost, "/api/models/batch",
		`{"model_ids":["acme/one"],"opencode_config_v2":{"name":"only"},"opencode_config_mode":"overwrite"}`)
	var stored map[string]any
	row := loadModelColumn(t, a, "acme/one")
	if err := json.Unmarshal(row.OpenCodeConfigV2, &stored); err != nil {
		t.Fatalf("stored opencode_config_v2 is invalid JSON: %v (%s)", err, row.OpenCodeConfigV2)
	}
	if len(stored) != 1 || stored["name"] != "only" {
		t.Fatalf("overwrite must replace the whole block, got %v", stored)
	}
}
