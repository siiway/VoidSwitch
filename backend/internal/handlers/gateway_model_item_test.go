package handlers

import (
	"encoding/json"
	"strings"
	"testing"

	"github.com/siiway/voidswitch/internal/database"
)

// gatewayModelItem must advertise both plugin generations: `opencode` in the V1
// vocabulary and `opencode_v2` in the V2 one. They are derived from the same
// metadata but must not be identical — V2 carries variants as an array and
// capabilities as input/tools lists.
func TestGatewayModelItemShipsBothBlocks(t *testing.T) {
	name := "Display Name"
	m := &database.ExposedModel{
		ModelID:          "m",
		DisplayName:      &name,
		OpenCodeConfig:   database.JSONOf(map[string]any{"reasoning": true}),
		OpenCodeConfigV2: database.JSONOf(map[string]any{"variants": []any{map[string]any{"id": "max"}}}),
		Capabilities:     database.JSONOf(map[string]any{"text": true, "tool": true}),
	}

	item := gatewayModelItem("m", 1, m, nil, nil)
	v1, ok := item["opencode"].(map[string]any)
	if !ok {
		t.Fatalf("opencode block missing: %v", item)
	}
	if v1["reasoning"] != true {
		t.Fatalf("opencode should carry the V1 reasoning flag: %v", v1)
	}
	v2, ok := item["opencode_v2"].(map[string]any)
	if !ok {
		t.Fatalf("opencode_v2 block missing: %v", item)
	}
	if v2["name"] != "Display Name" {
		t.Fatalf("opencode_v2.name = %v, want the structured display name", v2["name"])
	}
	if _, leaked := v2["reasoning"]; leaked {
		t.Fatalf("opencode_v2 must not carry the V1 reasoning flag: %v", v2)
	}
	if variants, ok := v2["variants"].([]any); !ok || len(variants) != 1 {
		t.Fatalf("opencode_v2 variants must stay an array: %v", v2["variants"])
	}
	caps, _ := v2["capabilities"].(map[string]any)
	if caps["tools"] != true {
		t.Fatalf("opencode_v2 capabilities lost the tool flag: %v", v2["capabilities"])
	}
	if input, _ := caps["input"].([]string); len(input) != 1 || input[0] != "text" {
		t.Fatalf("opencode_v2 capabilities.input = %v, want [text]", caps["input"])
	}
}

// The plugin decides between the V2 block and the V1 projection by testing
// `opencode_v2` for object-ness and emptiness, so a bare model must still carry
// both blocks as empty objects on the wire — never null.
func TestGatewayModelItemEmitsEmptyBlocks(t *testing.T) {
	m := &database.ExposedModel{ModelID: "bare"}
	item := gatewayModelItem("bare", 1, m, nil, nil)
	for _, key := range []string{"opencode", "opencode_v2"} {
		block, ok := item[key].(map[string]any)
		if !ok {
			t.Fatalf("%s must be an object, got %#v", key, item[key])
		}
		if len(block) != 0 {
			t.Fatalf("%s should be empty for a model with no metadata: %v", key, block)
		}
	}
	raw, err := json.Marshal(item)
	if err != nil {
		t.Fatalf("marshal the item: %v", err)
	}
	for _, want := range []string{`"opencode":{}`, `"opencode_v2":{}`} {
		if !strings.Contains(string(raw), want) {
			t.Fatalf("wire form missing %s: %s", want, raw)
		}
	}
}
