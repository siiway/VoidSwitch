package services

import (
	"encoding/json"
	"testing"

	"github.com/siiway/voidswitch/internal/database"
)

func exposedModel(fields map[string]any) *database.ExposedModel {
	m := &database.ExposedModel{ModelID: "m"}
	for k, v := range fields {
		raw, _ := json.Marshal(v)
		switch k {
		case "opencode_config":
			m.OpenCodeConfig = raw
		case "capabilities":
			m.Capabilities = raw
		case "modalities":
			m.Modalities = raw
		}
	}
	return m
}

// The advertised block follows "structured fields → custom config → models.dev".
func TestBuildOpencodeConfigPrecedence(t *testing.T) {
	name := "Real Name"
	ctx := 1000
	reasoning := true
	m := exposedModel(map[string]any{
		"opencode_config": map[string]any{"name": "Custom Name", "limit": map[string]any{"context": 5, "output": 7}},
		"capabilities":    map[string]any{"tool": true},
		"modalities":      map[string]any{"input": []any{"text"}},
	})
	m.DisplayName = &name
	m.LimitContext = &ctx
	m.Reasoning = &reasoning

	dev := map[string]any{
		"name":        "models.dev Name",
		"description": "from registry",
		"limit":       map[string]any{"context": float64(9), "input": float64(4)},
		"reasoning":   false,
	}

	got := BuildOpencodeConfig(m, dev)

	// Structured display_name beats the custom config, which beats models.dev.
	if got["name"] != "Real Name" {
		t.Fatalf("name = %v, want the structured display name", got["name"])
	}
	if got["description"] != "from registry" {
		t.Fatalf("description = %v, want the models.dev placeholder", got["description"])
	}
	limit, _ := got["limit"].(map[string]any)
	if limit["context"] != 1000 {
		t.Fatalf("limit.context = %v, want the structured 1000", limit["context"])
	}
	// A structured value absent leaves the lower-precedence one intact.
	if limit["output"] != float64(7) {
		t.Fatalf("limit.output = %v, want the custom 7", limit["output"])
	}
	if limit["input"] != int64(4) {
		t.Fatalf("limit.input = %v, want the models.dev 4", limit["input"])
	}
	// Structured reasoning (explicit true) beats the models.dev false.
	if got["reasoning"] != true {
		t.Fatalf("reasoning = %v, want true", got["reasoning"])
	}
	if caps, _ := got["capabilities"].(map[string]any); caps["tool"] != true {
		t.Fatalf("capabilities lost: %v", got["capabilities"])
	}
}

// An empty registry entry and an empty custom config must not fabricate fields.
func TestBuildOpencodeConfigMinimal(t *testing.T) {
	m := exposedModel(map[string]any{"opencode_config": map[string]any{}})
	got := BuildOpencodeConfig(m, nil)
	if len(got) != 0 {
		t.Fatalf("expected an empty block, got %v", got)
	}
}

// models.dev entries vary; normalizeModelsDevEntry keeps only what projects.
func TestNormalizeModelsDevEntry(t *testing.T) {
	got := normalizeModelsDevEntry(map[string]any{
		"name":        "N",
		"description": "D",
		"reasoning":   true,
		"limit":       map[string]any{"context": float64(128000), "input": float64(0), "output": "bad"},
		"family":      "ignored",
	})
	if got["name"] != "N" || got["description"] != "D" || got["reasoning"] != true {
		t.Fatalf("basic fields lost: %v", got)
	}
	limit, _ := got["limit"].(map[string]any)
	if limit["context"] != int64(128000) {
		t.Fatalf("context = %v", limit["context"])
	}
	if _, ok := limit["input"]; ok {
		t.Fatalf("non-positive input should be dropped: %v", limit)
	}
	if _, ok := limit["output"]; ok {
		t.Fatalf("non-numeric output should be dropped: %v", limit)
	}
	if _, ok := got["family"]; ok {
		t.Fatalf("unknown key should be dropped: %v", got)
	}
}
