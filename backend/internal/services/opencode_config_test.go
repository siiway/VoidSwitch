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
		case "opencode_config_v2":
			m.OpenCodeConfigV2 = raw
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

// The V2 block must speak the V2 vocabulary: capabilities carry input/tools/
// reasoning, and no V1-only keys leak through.
func TestBuildOpencodeConfigV2Vocab(t *testing.T) {
	name := "Real Name"
	ctx := 1000
	reasoning := true
	m := exposedModel(map[string]any{
		"opencode_config_v2": map[string]any{"description": "custom v2"},
		"capabilities":       map[string]any{"text": true, "image": true, "tool": true},
	})
	m.DisplayName = &name
	m.LimitContext = &ctx
	m.Reasoning = &reasoning

	dev := map[string]any{
		"name":      "models.dev Name",
		"limit":     map[string]any{"context": float64(9), "output": float64(4)},
		"reasoning": true,
	}

	got := BuildOpencodeConfigV2(m, dev)

	if got["name"] != "Real Name" {
		t.Fatalf("name = %v, want the structured display name", got["name"])
	}
	if got["description"] != "custom v2" {
		t.Fatalf("description = %v, want the custom v2 value", got["description"])
	}
	limit, _ := got["limit"].(map[string]any)
	if limit["context"] != 1000 {
		t.Fatalf("limit.context = %v, want the structured 1000", limit["context"])
	}
	if limit["output"] != int64(4) {
		t.Fatalf("limit.output = %v, want the models.dev 4", limit["output"])
	}
	caps, _ := got["capabilities"].(map[string]any)
	if caps["reasoning"] != true || caps["tools"] != true {
		t.Fatalf("capabilities lost: %v", caps)
	}
	input, _ := caps["input"].([]string)
	if len(input) != 2 || input[0] != "text" || input[1] != "image" {
		t.Fatalf("capabilities.input = %v, want [text image]", caps["input"])
	}
	for _, v1 := range []string{"reasoning", "options", "variants"} {
		if _, ok := got[v1]; ok {
			t.Fatalf("V1 key %q must not appear in the V2 block: %v", v1, got)
		}
	}
}

// An empty V2 config must not fabricate fields either.
func TestBuildOpencodeConfigV2Minimal(t *testing.T) {
	m := exposedModel(map[string]any{"opencode_config_v2": map[string]any{}})
	got := BuildOpencodeConfigV2(m, nil)
	if len(got) != 0 {
		t.Fatalf("expected an empty block, got %v", got)
	}
}

// A custom V2 block is the operator's escape hatch: it wins over models.dev but
// loses to the structured fields, and reaches nested keys.
func TestBuildOpencodeConfigV2CustomDeepMerge(t *testing.T) {
	m := exposedModel(map[string]any{
		"opencode_config_v2": map[string]any{
			"limit":        map[string]any{"output": 32},
			"variants":     []any{map[string]any{"id": "fast", "body": map[string]any{"x": 1}}},
			"capabilities": map[string]any{"temperature": true},
		},
	})
	dev := map[string]any{"limit": map[string]any{"context": float64(100)}}

	got := BuildOpencodeConfigV2(m, dev)
	limit, _ := got["limit"].(map[string]any)
	if limit["context"] != int64(100) || limit["output"] != float64(32) {
		t.Fatalf("limit merge lost keys: %v", limit)
	}
	if variants, ok := got["variants"].([]any); !ok || len(variants) != 1 {
		t.Fatalf("variants must stay an array: %v", got["variants"])
	}
	if caps, _ := got["capabilities"].(map[string]any); caps["temperature"] != true {
		t.Fatalf("capabilities merge lost keys: %v", got["capabilities"])
	}
}

// An operator block written in the V1 vocabulary must not reach the V2 output:
// OpenCode 2 rejects the whole provider block (and its cached models) when a
// recognised field has the wrong shape, which is the bug this split fixes.
func TestBuildOpencodeConfigV2SanitizesV1Keys(t *testing.T) {
	m := exposedModel(map[string]any{
		"opencode_config_v2": map[string]any{
			"options":   map[string]any{"reasoning_effort": "max"},
			"reasoning": true,
			"variants":  map[string]any{"max": map[string]any{"reasoningEffort": "max"}},
			"capabilities": map[string]any{
				"text":        true,
				"tool":        true,
				"temperature": true,
			},
		},
	})

	got := BuildOpencodeConfigV2(m, nil)
	for _, leaked := range []string{"options", "reasoning"} {
		if _, ok := got[leaked]; ok {
			t.Fatalf("V1 key %q leaked into the V2 block: %v", leaked, got)
		}
	}
	if _, ok := got["variants"]; ok {
		t.Fatalf("dict variants must be dropped, got %v", got["variants"])
	}
	caps, _ := got["capabilities"].(map[string]any)
	if caps["temperature"] != true {
		t.Fatalf("legitimate V2 capability lost: %v", caps)
	}
	if caps["tools"] != true {
		t.Fatalf("V1 tool flag must map to capabilities.tools: %v", caps)
	}
	if input, _ := caps["input"].([]string); len(input) != 1 || input[0] != "text" {
		t.Fatalf("V1 text flag must map to capabilities.input: %v", caps["input"])
	}
	for _, v1 := range v1CapabilityKeys {
		if _, ok := caps[v1]; ok {
			t.Fatalf("V1 capability key %q leaked: %v", v1, caps)
		}
	}
}

// The V2 block is derived from the V2 custom field only; the V1 custom block is
// not migrated implicitly (the plugin projects it when it has to).
func TestBuildOpencodeConfigV2DoesNotReuseV1Custom(t *testing.T) {
	m := exposedModel(map[string]any{
		"opencode_config": map[string]any{"name": "v1 custom", "limit": map[string]any{"context": 7}},
	})
	got := BuildOpencodeConfigV2(m, nil)
	if len(got) != 0 {
		t.Fatalf("V1 custom must not populate the V2 block, got %v", got)
	}
}

// V2 wants the media types as an `input` list and tool use as a `tools` flag.
// Every structured media flag must project — audio and pdf included — while an
// explicit false must not invent one.
func TestBuildOpencodeConfigV2CapabilitiesMapping(t *testing.T) {
	cases := []struct {
		name     string
		caps     map[string]any
		wantIn   []string
		wantTool bool
	}{
		{"all flags", map[string]any{"text": true, "image": true, "audio": true, "pdf": true, "tool": true}, []string{"text", "image", "audio", "pdf"}, true},
		{"audio and pdf", map[string]any{"audio": true, "pdf": true}, []string{"audio", "pdf"}, false},
		{"pdf only", map[string]any{"pdf": true}, []string{"pdf"}, false},
		{"tool only", map[string]any{"tool": true}, nil, true},
		{"explicit false", map[string]any{"text": false, "image": false, "tool": false}, nil, false},
		{"empty", map[string]any{}, nil, false},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			got := BuildOpencodeConfigV2(exposedModel(map[string]any{"capabilities": c.caps}), nil)
			caps, _ := got["capabilities"].(map[string]any)
			input, _ := caps["input"].([]string)
			if len(input) != len(c.wantIn) {
				t.Fatalf("capabilities.input = %v, want %v", caps["input"], c.wantIn)
			}
			for i := range c.wantIn {
				if input[i] != c.wantIn[i] {
					t.Fatalf("capabilities.input = %v, want %v", input, c.wantIn)
				}
			}
			tools, hasTools := caps["tools"]
			if hasTools != c.wantTool || (hasTools && tools != true) {
				t.Fatalf("capabilities.tools = %v (present=%v), want present=%v", tools, hasTools, c.wantTool)
			}
			if len(c.wantIn) == 0 && !c.wantTool && len(caps) != 0 {
				t.Fatalf("an empty capability set must not add a block: %v", caps)
			}
		})
	}
}

// An explicit structured reasoning=false is a decision, not an absent value: it
// must reach V2 as capabilities.reasoning=false and beat the registry entry.
func TestBuildOpencodeConfigV2ReasoningPrecedence(t *testing.T) {
	yes, no := true, false
	cases := []struct {
		name      string
		reasoning *bool
		dev       any
		want      any
	}{
		{"models.dev placeholder", nil, map[string]any{"reasoning": true}, true},
		{"structured true", &yes, nil, true},
		{"structured false beats models.dev", &no, map[string]any{"reasoning": true}, false},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			m := exposedModel(nil)
			m.Reasoning = c.reasoning
			got := BuildOpencodeConfigV2(m, c.dev)
			if _, leaked := got["reasoning"]; leaked {
				t.Fatalf("V2 must carry reasoning under capabilities: %v", got)
			}
			caps, _ := got["capabilities"].(map[string]any)
			if v, ok := caps["reasoning"]; !ok || v != c.want {
				t.Fatalf("capabilities.reasoning = %v (present=%v), want %v", v, ok, c.want)
			}
		})
	}
}

// The structured limits are the dashboard's own fields: they must win over both
// the custom block and the registry, and each one maps to its own key.
func TestBuildOpencodeConfigV2LimitPrecedence(t *testing.T) {
	ctx, in, out := 1000, 100, 200
	m := exposedModel(map[string]any{
		"opencode_config_v2": map[string]any{"limit": map[string]any{"output": 32}},
	})
	m.LimitContext, m.LimitInput, m.LimitOutput = &ctx, &in, &out
	dev := map[string]any{
		"limit": map[string]any{"context": float64(9), "input": float64(4), "output": float64(8)},
	}
	got := BuildOpencodeConfigV2(m, dev)
	limit, _ := got["limit"].(map[string]any)
	if limit["context"] != 1000 || limit["input"] != 100 || limit["output"] != 200 {
		t.Fatalf("structured limits must win: %v", limit)
	}

	// Without structured limits the custom value still beats models.dev.
	m = exposedModel(map[string]any{
		"opencode_config_v2": map[string]any{"limit": map[string]any{"output": 32}},
	})
	got = BuildOpencodeConfigV2(m, dev)
	limit, _ = got["limit"].(map[string]any)
	if limit["output"] != float64(32) || limit["context"] != int64(9) {
		t.Fatalf("custom must beat models.dev, and the registry fills the rest: %v", limit)
	}
}

// One models.dev entry is decoded once and shared by every model in a request
// (and cached across requests), so building a block must never write into it —
// a leak here would corrupt the vocabulary for every other model.
func TestBuildOpencodeConfigV2DoesNotMutateModelsDevEntry(t *testing.T) {
	dev := map[string]any{
		"name":        "N",
		"description": "D",
		"reasoning":   true,
		"limit":       map[string]any{"context": float64(9)},
	}
	before, err := json.Marshal(dev)
	if err != nil {
		t.Fatalf("marshal the fixture: %v", err)
	}
	m := exposedModel(map[string]any{
		"opencode_config_v2": map[string]any{
			"options":      map[string]any{"reasoningEffort": "max"},
			"variants":     map[string]any{"max": map[string]any{"id": "max"}},
			"capabilities": map[string]any{"text": true},
		},
	})

	first, _ := json.Marshal(BuildOpencodeConfigV2(m, dev))
	second, _ := json.Marshal(BuildOpencodeConfigV2(m, dev))
	after, _ := json.Marshal(dev)
	if string(before) != string(after) {
		t.Fatalf("the shared models.dev entry was mutated: %s → %s", before, after)
	}
	if string(first) != string(second) {
		t.Fatalf("repeated builds differ: %s vs %s", first, second)
	}
}

// A malformed or non-object stored block is ignored rather than fatal: an
// operator's typo must not blank the structured metadata or panic the handler.
func TestBuildOpencodeConfigV2IgnoresUnusableCustomBlock(t *testing.T) {
	name := "Display"
	cases := []struct {
		name string
		raw  database.JSON
	}{
		{"truncated", database.JSON(`{"limit":`)},
		{"null", database.JSON(`null`)},
		{"array", database.JSON(`[1,2]`)},
		{"string", database.JSON(`"text"`)},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			m := &database.ExposedModel{ModelID: "m", OpenCodeConfigV2: c.raw, DisplayName: &name}
			got := BuildOpencodeConfigV2(m, nil)
			if len(got) != 1 || got["name"] != "Display" {
				t.Fatalf("only the structured fields should remain, got %v", got)
			}
		})
	}
}
