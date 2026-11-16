package services

import (
	"encoding/json"

	"github.com/siiway/voidswitch/internal/database"
)

// modelsDevLimitKeys are the models.dev `limit` fields that map onto an OpenCode
// model block. The registry shape varies across providers, so only the
// intersection we understand is projected.
var modelsDevLimitKeys = []string{"context", "input", "output"}

// deepMerge recursively merges override onto base: nested maps combine, while
// lists and scalars replace. Neither input is mutated.
func deepMerge(base, override map[string]any) map[string]any {
	out := make(map[string]any, len(base)+len(override))
	for k, v := range base {
		out[k] = v
	}
	for k, v := range override {
		existing, ok := out[k]
		if ok {
			em, eok := existing.(map[string]any)
			vm, vok := v.(map[string]any)
			if eok && vok {
				out[k] = deepMerge(em, vm)
				continue
			}
		}
		out[k] = v
	}
	return out
}

// normalizeModelsDevEntry projects a models.dev registry entry onto our config
// vocabulary. Entries vary: some carry name/description, many carry limit, a few
// reasoning. Anything we cannot project is dropped, so a sparse entry simply
// contributes nothing and the operator's values (or the client defaults) win.
func normalizeModelsDevEntry(entry any) map[string]any {
	md, ok := entry.(map[string]any)
	if !ok {
		return map[string]any{}
	}
	out := map[string]any{}
	if name, ok := md["name"].(string); ok && name != "" {
		out["name"] = name
	}
	if desc, ok := md["description"].(string); ok && desc != "" {
		out["description"] = desc
	}
	if limit, ok := md["limit"].(map[string]any); ok {
		lim := map[string]any{}
		for _, key := range modelsDevLimitKeys {
			if n, ok := toPositiveInt(limit[key]); ok {
				lim[key] = n
			}
		}
		if len(lim) > 0 {
			out["limit"] = lim
		}
	}
	if reasoning, ok := md["reasoning"].(bool); ok && reasoning {
		out["reasoning"] = true
	}
	return out
}

// toPositiveInt accepts the numeric shapes encoding/json produces.
func toPositiveInt(v any) (int64, bool) {
	switch n := v.(type) {
	case float64:
		if n > 0 {
			return int64(n), true
		}
	case int64:
		if n > 0 {
			return n, true
		}
	case int:
		if n > 0 {
			return int64(n), true
		}
	case json.Number:
		if i, err := n.Int64(); err == nil && i > 0 {
			return i, true
		}
	}
	return 0, false
}

// BuildOpencodeConfig produces the OpenCode model block advertised by
// `/v1/models`: the merged downstream config a client should apply to this
// model. Precedence, high to low:
//
//	structured fields → custom opencode_config → models.dev placeholder
//
// Plugin/client defaults are applied last on the client, so they are not part of
// this block. Upstream refs are never advertised here.
func BuildOpencodeConfig(m *database.ExposedModel, modelsDevEntry any) map[string]any {
	config := deepMerge(map[string]any{}, normalizeModelsDevEntry(modelsDevEntry))

	var custom any
	if err := json.Unmarshal(m.OpenCodeConfig, &custom); err == nil {
		if cm, ok := custom.(map[string]any); ok {
			config = deepMerge(config, cm)
		}
	}

	if m.DisplayName != nil && *m.DisplayName != "" {
		config["name"] = *m.DisplayName
	}
	limit := map[string]any{}
	if m.LimitContext != nil && *m.LimitContext > 0 {
		limit["context"] = *m.LimitContext
	}
	if m.LimitInput != nil && *m.LimitInput > 0 {
		limit["input"] = *m.LimitInput
	}
	if m.LimitOutput != nil && *m.LimitOutput > 0 {
		limit["output"] = *m.LimitOutput
	}
	if len(limit) > 0 {
		existing, _ := config["limit"].(map[string]any)
		config["limit"] = deepMerge(existing, limit)
	}
	if m.Reasoning != nil {
		config["reasoning"] = *m.Reasoning
	}
	if caps := jsonObject(m.Capabilities); len(caps) > 0 {
		existing, _ := config["capabilities"].(map[string]any)
		config["capabilities"] = deepMerge(existing, caps)
	}
	if mods := jsonObject(m.Modalities); len(mods) > 0 {
		existing, _ := config["modalities"].(map[string]any)
		config["modalities"] = deepMerge(existing, mods)
	}
	return config
}

// jsonObject decodes a JSON object column, returning nil when it is empty or not
// an object.
func jsonObject(raw database.JSON) map[string]any {
	if len(raw) == 0 {
		return nil
	}
	var out map[string]any
	if err := json.Unmarshal(raw, &out); err != nil {
		return nil
	}
	return out
}
