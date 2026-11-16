package handlers

import (
	"fmt"
	"testing"

	"gorm.io/driver/sqlite"
	"gorm.io/gorm"

	"github.com/siiway/voidswitch/internal/database"
)

func newTestDB(t *testing.T) *gorm.DB {
	t.Helper()
	// A per-test DSN: a shared in-memory database would let one test's rows
	// leak into another's assertions.
	dsn := fmt.Sprintf("file:%s?mode=memory&cache=shared", t.Name())
	db, err := gorm.Open(sqlite.Open(dsn), &gorm.Config{})
	if err != nil {
		t.Fatalf("open sqlite: %v", err)
	}
	if err := db.AutoMigrate(&database.Provider{}, &database.ExposedModel{}); err != nil {
		t.Fatalf("migrate: %v", err)
	}
	return db
}

// Deleting a passthrough id must strip the whitelist entry even when the id
// contains slashes and no metadata row exists. This is what the model page's
// "delete selected" sends, and it used to report 0 because only metadata rows
// were considered.
func TestDeletePassthroughEntryRewritesWhitelist(t *testing.T) {
	db := newTestDB(t)
	p := database.Provider{
		UUID: "u1", Name: "OpenRouter", Slug: "openrouter", Type: "openai",
		Enabled: true, PassthroughEnabled: true,
		Models:            database.JSONOf([]string{}),
		ModelMap:          database.JSONOf(map[string]any{}),
		ModelRoutes:       database.JSONOf([]any{}),
		ExtraHeaders:      database.JSONOf(map[string]any{}),
		PassthroughModels: database.JSONOf([]string{"stealth/space-bunny-alpha", "gpt-4o"}),
		// The schema marks these NOT NULL; SQLite enforces it, Postgres too.
		UpstreamCooldownStatusCodes: database.JSONOf([]int{}),
		UpstreamRetryAfterHeaders:   database.JSONOf([]string{}),
		SelectiveIgnoreRules:        database.JSONOf([]any{}),
	}
	if err := db.Create(&p).Error; err != nil {
		t.Fatalf("seed provider: %v", err)
	}

	app := &App{GDB: db}
	removed, err := app.deletePassthroughEntries([]string{"openrouter/stealth/space-bunny-alpha"})
	if err != nil {
		t.Fatalf("deletePassthroughEntries: %v", err)
	}
	if !removed["openrouter/stealth/space-bunny-alpha"] {
		t.Fatalf("the removed id was not reported: %v", removed)
	}

	var after database.Provider
	db.First(&after, p.ID)
	var list []string
	database.DecodeJSON(after.PassthroughModels, &list)
	if len(list) != 1 || list[0] != "gpt-4o" {
		t.Fatalf("whitelist = %v, want only gpt-4o", list)
	}
}

// An id that is not a passthrough entry must not be reported as removed.
func TestDeletePassthroughEntryIgnoresUnknown(t *testing.T) {
	db := newTestDB(t)
	db.Create(&database.Provider{
		UUID: "u2", Name: "P", Slug: "p", Type: "openai", Enabled: true,
		PassthroughEnabled:          true,
		Models:                      database.JSONOf([]string{}),
		ModelMap:                    database.JSONOf(map[string]any{}),
		ModelRoutes:                 database.JSONOf([]any{}),
		ExtraHeaders:                database.JSONOf(map[string]any{}),
		PassthroughModels:           database.JSONOf([]string{"a"}),
		UpstreamCooldownStatusCodes: database.JSONOf([]int{}),
		UpstreamRetryAfterHeaders:   database.JSONOf([]string{}),
		SelectiveIgnoreRules:        database.JSONOf([]any{}),
	})

	app := &App{GDB: db}
	removed, err := app.deletePassthroughEntries([]string{"p/nope", "plain-model"})
	if err != nil {
		t.Fatalf("deletePassthroughEntries: %v", err)
	}
	if len(removed) != 0 {
		t.Fatalf("removed = %v, want nothing", removed)
	}
}
