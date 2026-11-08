package providers

import "testing"

func TestAllAdapterTypesRegistered(t *testing.T) {
	types := AdapterTypes()
	want := []string{"anthropic", "cerebras", "claude-code", "cloudflare", "codex",
		"deepinfra", "deepseek", "fireworks", "gemini", "generic", "github-models",
		"grok", "grok-build", "groq", "hyperbolic", "mimo", "minimax", "mistral",
		"moonshot", "nebius", "novita", "nvidia", "openai", "openai-resp",
		"openrouter", "perplexity", "qwen", "sambanova", "siliconflow", "together",
		"volcengine", "xai", "zhipu"}
	set := map[string]bool{}
	for _, x := range types {
		set[x] = true
	}
	for _, w := range want {
		if !set[w] {
			t.Errorf("missing adapter type %q", w)
		}
	}
}
