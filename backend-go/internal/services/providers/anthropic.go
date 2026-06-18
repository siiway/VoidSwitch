package providers

import (
	"crypto/sha256"
	"fmt"
	"runtime"
	"strings"

	"github.com/siiway/voidswitch/internal/constants"
	"github.com/siiway/voidswitch/internal/database"
)

const (
	CLAUDE_CODE_IDENTITY   = "You are Claude Code, Anthropic's official CLI for Claude."
	OPENCODE_IDENTITY_LINE = "You are OpenCode, the best coding agent on the planet."
	CLAUDE_CODE_VERSION    = "2.1.158"
	ANTHROPIC_SDK_VERSION  = "0.94.0"
)

var opencodeSubstitutions = [][2]string{
	{"https://github.com/anomalyco/opencode", "https://github.com/anthropics/claude-code"},
	{"https://opencode.ai/docs", "https://docs.claude.com/en/docs/claude-code"},
	{"https://opencode.ai", "https://docs.claude.com/en/docs/claude-code"},
	{"OpenCode", "Claude Code"},
	{"opencode", "claude-code"},
	{"voidswitch/", ""},
}

var defaultBetas = []string{"claude-code-20250219", "oauth-2025-04-20"}

type AnthropicProvider struct {
	BaseProvider
}

func NewAnthropicProvider(record *database.Provider) *AnthropicProvider {
	return &AnthropicProvider{
		BaseProvider: BaseProvider{
			Type:             "anthropic",
			Style:            constants.ApiStyleAnthropic,
			DefaultBaseURL:   "https://api.anthropic.com",
			DefaultModels:    []string{"claude-opus-4-8", "claude-opus-4-7", "claude-opus-4-6", "claude-sonnet-4-6", "claude-haiku-4-5-20251001"},
			ChatSuffix:       "/chat/completions",
			MessagesSuffix:   "/v1/messages",
			ModelsSuffix:     "/v1/models",
			AnthropicVersion: "2023-06-01",
			Record:           record,
		},
	}
}

type ClaudeCodeProvider struct {
	AnthropicProvider
}

func NewClaudeCodeProvider(record *database.Provider) *ClaudeCodeProvider {
	return &ClaudeCodeProvider{
		AnthropicProvider: AnthropicProvider{
			BaseProvider: BaseProvider{
				Type:             "claude-code",
				Style:            constants.ApiStyleAnthropic,
				DefaultBaseURL:   "https://api.anthropic.com",
				DefaultModels:    []string{"claude-opus-4-8", "claude-opus-4-7", "claude-opus-4-6", "claude-sonnet-4-6", "claude-haiku-4-5-20251001"},
				ChatSuffix:       "/chat/completions",
				MessagesSuffix:   "/v1/messages",
				ModelsSuffix:     "/v1/models",
				AnthropicVersion: "2023-06-01",
				Record:           record,
			},
		},
	}
}

func (p *ClaudeCodeProvider) Headers(apiKey string, extra map[string]string) map[string]string {
	base := map[string]string{
		"Authorization":                "Bearer " + apiKey,
		"anthropic-version":            p.AnthropicVersion,
		"content-type":                 "application/json",
		"accept":                       "application/json",
		"user-agent":                   "claude-cli/" + CLAUDE_CODE_VERSION + " (external, cli)",
		"x-app":                        "cli",
		"x-claude-code-session-id":     p.sessionID(),
		"x-stainless-lang":             "js",
		"x-stainless-package-version":  ANTHROPIC_SDK_VERSION,
		"x-stainless-os":               stainlessOS(),
		"x-stainless-arch":             stainlessArch(),
		"x-stainless-runtime":          "node",
		"x-stainless-runtime-version":  "v24.0.0",
		"x-stainless-retry-count":      "0",
	}

	merged := make(map[string]string)
	for k, v := range p.Record.ExtraHeaders {
		merged[k] = fmt.Sprintf("%v", v)
	}
	if extra != nil {
		for k, v := range extra {
			merged[k] = v
		}
	}

	var incoming string
	for key := range merged {
		if strings.ToLower(key) == "anthropic-beta" {
			incoming = merged[key]
			delete(merged, key)
		}
	}
	delete(merged, "x-api-key")
	delete(merged, "Authorization")

	betas := make([]string, len(defaultBetas))
	copy(betas, defaultBetas)
	for _, b := range strings.Split(incoming, ",") {
		b = strings.TrimSpace(b)
		if b == "" {
			continue
		}
		found := false
		for _, existing := range betas {
			if existing == b {
				found = true
				break
			}
		}
		if !found {
			betas = append(betas, b)
		}
	}

	for k, v := range merged {
		base[k] = v
	}
	base["anthropic-beta"] = strings.Join(betas, ",")
	return base
}

func (p *ClaudeCodeProvider) PrepareBody(body map[string]any) map[string]any {
	result := make(map[string]any, len(body))
	for k, v := range body {
		result[k] = v
	}

	dropBlock := p.Record.DropOpenCodeIdentityBlock
	system := stripOpenCodeIdentity(result["system"], dropBlock)
	blocks := ensureIdentity(system)
	if len(blocks) > 0 {
		first := make(map[string]any)
		for k, v := range blocks[0] {
			first[k] = v
		}
		first["cache_control"] = map[string]any{"type": "ephemeral"}
		blocks[0] = first
	}
	result["system"] = blocks

	if tools, ok := result["tools"].([]any); ok {
		result["tools"] = scrubOpenCodeTree(tools)
	}

	capCacheControl(result, 4)
	return result
}

func (p *ClaudeCodeProvider) sessionID() string {
	digest := sha256.Sum256([]byte(fmt.Sprintf("%d:%s", p.Record.ID, p.Record.Name)))
	h := fmt.Sprintf("%x", digest)
	return fmt.Sprintf("%s-%s-4%s-8%s-%s", h[:8], h[8:12], h[13:16], h[17:20], h[20:32])
}

func stainlessOS() string {
	switch runtime.GOOS {
	case "darwin":
		return "MacOS"
	case "windows":
		return "Windows"
	case "freebsd":
		return "FreeBSD"
	case "openbsd":
		return "OpenBSD"
	case "linux":
		return "Linux"
	case "java":
		return "Unknown"
	default:
		if runtime.GOOS != "" {
			return "Other:" + runtime.GOOS
		}
		return "Unknown"
	}
}

func stainlessArch() string {
	switch runtime.GOARCH {
	case "386":
		return "x32"
	case "amd64":
		return "x64"
	case "arm":
		return "arm"
	case "arm64":
		return "arm64"
	default:
		if runtime.GOARCH != "" {
			return "other:" + runtime.GOARCH
		}
		return "unknown"
	}
}

func applyOpenCodeSubstitutions(text string) string {
	for _, sub := range opencodeSubstitutions {
		text = strings.ReplaceAll(text, sub[0], sub[1])
	}
	return text
}

func scrubOpenCodeText(text string) string {
	if strings.Contains(text, OPENCODE_IDENTITY_LINE) {
		lines := strings.Split(text, "\n")
		var kept []string
		for _, ln := range lines {
			if strings.TrimSpace(ln) != OPENCODE_IDENTITY_LINE {
				kept = append(kept, ln)
			}
		}
		text = strings.TrimLeft(strings.Join(kept, "\n"), "\n")
	}
	return applyOpenCodeSubstitutions(text)
}

func scrubOpenCodeTree(obj any) any {
	switch v := obj.(type) {
	case string:
		return applyOpenCodeSubstitutions(v)
	case []any:
		result := make([]any, len(v))
		for i, item := range v {
			result[i] = scrubOpenCodeTree(item)
		}
		return result
	case map[string]any:
		result := make(map[string]any, len(v))
		for key, val := range v {
			result[key] = scrubOpenCodeTree(val)
		}
		return result
	default:
		return obj
	}
}

func stripOpenCodeIdentity(system any, dropBlock bool) any {
	switch s := system.(type) {
	case string:
		if dropBlock && strings.Contains(s, OPENCODE_IDENTITY_LINE) {
			return ""
		}
		return scrubOpenCodeText(s)
	case []any:
		var out []any
		for _, b := range s {
			block, ok := b.(map[string]any)
			if !ok {
				out = append(out, b)
				continue
			}
			text, _ := block["text"].(string)
			if dropBlock && strings.Contains(text, OPENCODE_IDENTITY_LINE) {
				continue
			}
			scrubbed := scrubOpenCodeText(text)
			if strings.TrimSpace(scrubbed) == "" {
				continue
			}
			nb := make(map[string]any, len(block))
			for k, v := range block {
				nb[k] = v
			}
			nb["text"] = scrubbed
			out = append(out, nb)
		}
		return out
	default:
		return system
	}
}

func ensureIdentity(system any) []map[string]any {
	identity := map[string]any{"type": "text", "text": CLAUDE_CODE_IDENTITY}

	if system == nil {
		return []map[string]any{identity}
	}

	switch s := system.(type) {
	case string:
		if s == "" {
			return []map[string]any{identity}
		}
		return []map[string]any{identity, {"type": "text", "text": s}}
	case []any:
		blocks := make([]map[string]any, 0, len(s))
		for _, b := range s {
			if bm, ok := b.(map[string]any); ok {
				blocks = append(blocks, bm)
			}
		}
		if len(blocks) == 0 {
			return []map[string]any{identity}
		}
		firstText, _ := blocks[0]["text"].(string)
		if strings.HasPrefix(strings.TrimSpace(firstText), CLAUDE_CODE_IDENTITY) {
			return blocks
		}
		return append([]map[string]any{identity}, blocks...)
	default:
		return []map[string]any{identity}
	}
}

func capCacheControl(body map[string]any, limit int) {
	var carriers []map[string]any

	if tools, ok := body["tools"].([]any); ok {
		for _, t := range tools {
			if tm, ok := t.(map[string]any); ok {
				if _, has := tm["cache_control"]; has {
					carriers = append(carriers, tm)
				}
			}
		}
	}

	if system, ok := body["system"].([]any); ok {
		for _, b := range system {
			if bm, ok := b.(map[string]any); ok {
				if _, has := bm["cache_control"]; has {
					carriers = append(carriers, bm)
				}
			}
		}
	}

	if messages, ok := body["messages"].([]any); ok {
		for _, m := range messages {
			if msg, ok := m.(map[string]any); ok {
				if content, ok := msg["content"].([]any); ok {
					for _, c := range content {
						if cm, ok := c.(map[string]any); ok {
							if _, has := cm["cache_control"]; has {
								carriers = append(carriers, cm)
							}
						}
					}
				}
			}
		}
	}

	excess := len(carriers) - limit
	if excess > 0 {
		for i := 0; i < excess; i++ {
			delete(carriers[i], "cache_control")
		}
	}
}
