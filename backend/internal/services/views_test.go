package services

import (
	"testing"

	"github.com/siiway/voidswitch/internal/database"
)

// The models page edits both blocks, so the view must round-trip them verbatim
// and keep them apart: showing the V2 block in the V1 editor (or the reverse)
// would let one editor silently overwrite the other's shape.
func TestBuildModelEntryViewCarriesOpencodeConfigV2(t *testing.T) {
	m := &database.ExposedModel{
		ModelID:             "m",
		OpenCodeConfig:      database.JSONOf(map[string]any{"reasoning": true}),
		OpenCodeConfigV2:    database.JSONOf(map[string]any{"capabilities": map[string]any{"tools": true}, "variants": []any{map[string]any{"id": "max"}}}),
		AllowedRoleGroupIDs: database.JSONOf([]int{}),
		Capabilities:        database.JSONOf(map[string]any{}),
		Modalities:          database.JSONOf(map[string]any{}),
	}

	v := BuildModelEntryView(m, nil)
	v1, ok := v.OpenCodeConfig.(map[string]any)
	if !ok || len(v1) != 1 || v1["reasoning"] != true {
		t.Fatalf("opencode_config = %v, want the V1 block", v.OpenCodeConfig)
	}
	v2, ok := v.OpenCodeConfigV2.(map[string]any)
	if !ok {
		t.Fatalf("opencode_config_v2 = %v, want the V2 block", v.OpenCodeConfigV2)
	}
	caps, _ := v2["capabilities"].(map[string]any)
	if caps["tools"] != true {
		t.Fatalf("V2 capabilities lost: %v", v2["capabilities"])
	}
	if variants, _ := v2["variants"].([]any); len(variants) != 1 {
		t.Fatalf("V2 variants must stay an array: %v", v2["variants"])
	}
	if _, leaked := v2["reasoning"]; leaked {
		t.Fatalf("the V1 block bled into the V2 view field: %v", v2)
	}

	// An empty (or not yet migrated) column must render as {}: the JSON editor
	// shows null otherwise, and the next save would persist it.
	empty := BuildModelEntryView(&database.ExposedModel{ModelID: "empty"}, nil)
	if e, ok := empty.OpenCodeConfigV2.(map[string]any); !ok || len(e) != 0 {
		t.Fatalf("an empty V2 column should render as {}: %v", empty.OpenCodeConfigV2)
	}
}
