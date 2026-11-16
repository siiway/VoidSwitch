package handlers

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/gin-gonic/gin"

	"github.com/siiway/voidswitch/internal/database"
)

// A passthrough model has no metadata row until its metadata is edited, so the
// batch-delete count must come from the whitelist removal too. Reporting only
// RowsAffected told the operator "0 model(s) deleted" after a removal that did
// happen.
func TestModelsBatchDeleteCountsPassthrough(t *testing.T) {
	db := newTestDB(t)
	db.Create(&database.Provider{
		UUID: "u3", Name: "OpenRouter", Slug: "openrouter", Type: "openai",
		Enabled: true, PassthroughEnabled: true,
		Models:                      database.JSONOf([]string{}),
		ModelMap:                    database.JSONOf(map[string]any{}),
		ModelRoutes:                 database.JSONOf([]any{}),
		ExtraHeaders:                database.JSONOf(map[string]any{}),
		PassthroughModels:           database.JSONOf([]string{"stealth/space-bunny-alpha"}),
		UpstreamCooldownStatusCodes: database.JSONOf([]int{}),
		UpstreamRetryAfterHeaders:   database.JSONOf([]string{}),
		SelectiveIgnoreRules:        database.JSONOf([]any{}),
	})

	app := &App{GDB: db}
	gin.SetMode(gin.TestMode)
	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	c.Request = httptest.NewRequest(http.MethodPost, "/api/models/batch-delete",
		strings.NewReader(`{"model_ids":["openrouter/stealth/space-bunny-alpha"]}`))
	c.Request.Header.Set("Content-Type", "application/json")

	app.modelsBatchDelete(c)

	if w.Code != http.StatusOK {
		t.Fatalf("status = %d, body = %s", w.Code, w.Body.String())
	}
	var out struct {
		Deleted  int      `json:"deleted"`
		ModelIDs []string `json:"model_ids"`
	}
	if err := json.Unmarshal(w.Body.Bytes(), &out); err != nil {
		t.Fatalf("decode response: %v", err)
	}
	if out.Deleted != 1 {
		t.Fatalf("deleted = %d, want 1 (body %s)", out.Deleted, w.Body.String())
	}
	if len(out.ModelIDs) != 1 || out.ModelIDs[0] != "openrouter/stealth/space-bunny-alpha" {
		t.Fatalf("model_ids = %v", out.ModelIDs)
	}
}
