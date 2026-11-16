package services

import "testing"

// The registry maps provider id → provider object, and a model's stable id is
// "provider/model". These fixtures mirror the shape of the real api.json.
func modelsDevFixture() []modelsDevEntry {
	return []modelsDevEntry{
		{ID: "openrouter", Data: map[string]any{
			"name": "OpenRouter",
			"models": map[string]any{
				"deepseek/deepseek-v4-pro": map[string]any{"name": "DeepSeek V4 Pro"},
			},
		}},
		{ID: "deepseek", Data: map[string]any{
			"name": "DeepSeek",
			"models": map[string]any{
				"deepseek-v4-pro": map[string]any{"name": "DeepSeek V4 Pro"},
			},
		}},
		{ID: "openai", Data: map[string]any{
			"name": "OpenAI",
			"models": map[string]any{
				"gpt-5": map[string]any{"name": "GPT-5"},
			},
		}},
		{ID: "anthropic", Data: map[string]any{
			"name": "Anthropic",
			"models": map[string]any{
				"claude-opus-4-6": map[string]any{
					"name":      "Claude Opus 4.6",
					"family":    "claude-opus",
					"reasoning": true,
				},
			},
		}},
	}
}

func modelsDevIDs(results []map[string]any) []string {
	out := make([]string, 0, len(results))
	for _, r := range results {
		provider, _ := r["provider"].(string)
		id, _ := r["id"].(string)
		out = append(out, provider+"/"+id)
	}
	return out
}

// Searching a bare model id leads with the provider's own listing, not an
// alphabetical third-party aggregate of the same model.
func TestModelsDevSearchPrefersOfficialExactMatch(t *testing.T) {
	ids := modelsDevIDs(searchModelsDevEntries(modelsDevFixture(), "deepseek-v4-pro", 50))
	if len(ids) == 0 || ids[0] != "deepseek/deepseek-v4-pro" {
		t.Fatalf("first result = %v, want deepseek/deepseek-v4-pro first", ids)
	}
	if len(ids) < 2 || ids[1] != "openrouter/deepseek/deepseek-v4-pro" {
		t.Fatalf("aggregate should follow the official entry, got %v", ids)
	}
}

// A full "provider/model" query is an exact match and must rank first.
func TestModelsDevSearchFullIDExactMatchWins(t *testing.T) {
	ids := modelsDevIDs(searchModelsDevEntries(modelsDevFixture(), "deepseek/deepseek-v4-pro", 50))
	if len(ids) == 0 || ids[0] != "deepseek/deepseek-v4-pro" {
		t.Fatalf("first result = %v, want deepseek/deepseek-v4-pro", ids)
	}
}

// A provider-name-only query still surfaces that provider's models, so the
// provider id is part of the match surface.
func TestModelsDevSearchProviderMatch(t *testing.T) {
	ids := modelsDevIDs(searchModelsDevEntries(modelsDevFixture(), "deepseek", 50))
	want := map[string]bool{
		"deepseek/deepseek-v4-pro":            true,
		"openrouter/deepseek/deepseek-v4-pro": true,
	}
	if len(ids) != len(want) {
		t.Fatalf("got %v, want both deepseek listings", ids)
	}
	for _, id := range ids {
		if !want[id] {
			t.Fatalf("unexpected result %q in %v", id, ids)
		}
	}
}

// The regression that motivated this: a model-name query must match. The old Go
// implementation only ILIKE'd provider ids, so "claude" returned nothing.
func TestModelsDevSearchMatchesModelName(t *testing.T) {
	ids := modelsDevIDs(searchModelsDevEntries(modelsDevFixture(), "claude", 50))
	if len(ids) != 1 || ids[0] != "anthropic/claude-opus-4-6" {
		t.Fatalf("got %v, want the claude model", ids)
	}
	// Display-name matching must work too, not just the id.
	ids = modelsDevIDs(searchModelsDevEntries(modelsDevFixture(), "Claude Opus", 50))
	if len(ids) != 1 || ids[0] != "anthropic/claude-opus-4-6" {
		t.Fatalf("display-name search got %v", ids)
	}
}

// Family matching is the weakest tier but must still resolve.
func TestModelsDevSearchFamilyMatch(t *testing.T) {
	ids := modelsDevIDs(searchModelsDevEntries(modelsDevFixture(), "claude-opus", 50))
	if len(ids) != 1 || ids[0] != "anthropic/claude-opus-4-6" {
		t.Fatalf("family search got %v", ids)
	}
}

func TestModelsDevSearchNoMatchIsEmpty(t *testing.T) {
	if got := searchModelsDevEntries(modelsDevFixture(), "zzz-nothing", 50); len(got) != 0 {
		t.Fatalf("expected no results, got %v", modelsDevIDs(got))
	}
	if got := searchModelsDevEntries(modelsDevFixture(), "   ", 50); len(got) != 0 {
		t.Fatalf("blank query must return nothing, got %v", modelsDevIDs(got))
	}
}

// Entries must carry the provider id/name so the dashboard can render a brand.
func TestModelsDevSearchAugmentsProvider(t *testing.T) {
	results := searchModelsDevEntries(modelsDevFixture(), "gpt-5", 50)
	if len(results) != 1 {
		t.Fatalf("got %d results", len(results))
	}
	if results[0]["provider"] != "openai" || results[0]["provider_name"] != "OpenAI" {
		t.Fatalf("missing provider augmentation: %v", results[0])
	}
	if _, ok := results[0]["id"]; !ok {
		t.Fatalf("entry lost its id: %v", results[0])
	}
}

// The limit must cap the result set.
func TestModelsDevSearchHonoursLimit(t *testing.T) {
	rows := modelsDevFixture()
	got := searchModelsDevEntries(rows, "deepseek", 1)
	if len(got) != 1 {
		t.Fatalf("limit=1 returned %d results", len(got))
	}
}

// The regression this fixed: the old handler only matched provider ids, so a
// model-name query over a realistic registry returned nothing. Guard the shape
// that made it visible — many providers, model entries nested under each.
func TestModelsDevSearchAcrossManyProviders(t *testing.T) {
	rows := []modelsDevEntry{
		{ID: "anthropic", Data: map[string]any{
			"name": "Anthropic",
			"models": map[string]any{
				"claude-opus-4-6": map[string]any{"name": "Claude Opus 4.6"},
			},
		}},
		{ID: "openrouter", Data: map[string]any{
			"name": "OpenRouter",
			"models": map[string]any{
				"anthropic/claude-opus-4.7": map[string]any{"name": "Claude Opus 4.7"},
			},
		}},
		{ID: "bumo", Data: map[string]any{
			"name": "Bumo",
			"models": map[string]any{
				"claude-opus-4-6": map[string]any{"name": "Claude Opus 4.6"},
			},
		}},
	}
	// A bare model id leads with providers whose own listing it is, ahead of any
	// aggregate. Both official entries tie on score, so the shorter full id wins;
	// what matters is that no aggregated listing outranks them.
	got := modelsDevIDs(searchModelsDevEntries(rows, "claude-opus-4-6", 100))
	if len(got) < 2 {
		t.Fatalf("expected both official listings, got %v", got)
	}
	official := map[string]bool{"anthropic/claude-opus-4-6": true, "bumo/claude-opus-4-6": true}
	for _, id := range got[:2] {
		if !official[id] {
			t.Fatalf("official listing should lead, got %v", got)
		}
	}
	// A family/provider-prefixed query still finds the aggregated listing.
	got = modelsDevIDs(searchModelsDevEntries(rows, "claude-opus-4.7", 100))
	if len(got) != 1 || got[0] != "openrouter/anthropic/claude-opus-4.7" {
		t.Fatalf("publisher-prefixed listing not found: %v", got)
	}
}
