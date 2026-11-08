package providers

import (
	"encoding/base64"
	"encoding/json"
	"fmt"
	"strings"

	"github.com/siiway/voidswitch/internal/constants"
	"github.com/siiway/voidswitch/internal/database"
)

// ---- Codex (OpenAI Codex CLI subscription, Responses API) -----------------

// CodexProvider targets chatgpt.com's Codex backend, which only speaks the
// OpenAI Responses API over SSE and requires store=false.
type CodexProvider struct {
	OpenAIProvider
}

func NewCodexProvider(record *database.Provider) *CodexProvider {
	p := &CodexProvider{
		OpenAIProvider: OpenAIProvider{
			BaseProvider: BaseProvider{
				Type:            "codex",
				Style:           constants.ApiStyleOpenAIResponses,
				DefaultBaseURL:  "https://chatgpt.com/backend-api/codex",
				DefaultModels:   []string{"gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna", "*"},
				ChatSuffix:      "/responses",
				MessagesSuffix:  "/v1/messages",
				ModelsSuffix:    "/models",
				SupportsOAuth:   true,
				SupportsRefresh: true,
				SupportsImport:  true,
				Record:          record,
			},
		},
	}
	return p
}

var codexWireFields = map[string]bool{
	"model": true, "instructions": true, "input": true, "tools": true,
	"tool_choice": true, "parallel_tool_calls": true, "reasoning": true,
	"store": true, "stream": true, "include": true, "service_tier": true,
	"prompt_cache_key": true, "text": true, "truncation": true, "metadata": true,
	"background": true, "conversation": true, "previous_response_id": true, "user": true,
}

// PrepareBody enforces the Codex backend's Responses wire contract: only known
// fields, store=false, streaming, and include reasoning.encrypted_content.
func (p *CodexProvider) PrepareBody(body map[string]any) map[string]any {
	out := make(map[string]any, len(body))
	for k, v := range body {
		if codexWireFields[k] {
			out[k] = v
		}
	}
	out["store"] = false
	out["stream"] = true
	include, _ := out["include"].([]any)
	if include == nil {
		include = []any{}
	}
	hasReasoning := false
	for _, v := range include {
		if v == "reasoning.encrypted_content" {
			hasReasoning = true
		}
	}
	if !hasReasoning {
		include = append(include, "reasoning.encrypted_content")
	}
	out["include"] = include
	return out
}

// Headers adds the codex-cli identity and ChatGPT-Account-Id (from the JWT).
func (p *CodexProvider) Headers(apiKey string, extra map[string]string) map[string]string {
	base := map[string]string{
		"Authorization": "Bearer " + apiKey,
		"content-type":  "application/json",
		"accept":        "text/event-stream",
		"originator":    "codex_cli_rs",
		"User-Agent":    "codex_cli_rs",
	}
	if acct := codexAccountID(apiKey); acct != "" {
		base["ChatGPT-Account-Id"] = acct
	}
	var extraHdr map[string]any
	database.DecodeJSON(p.Record.ExtraHeaders, &extraHdr)
	for k, v := range extraHdr {
		base[k] = fmt.Sprintf("%v", v)
	}
	for k, v := range extra {
		base[k] = v
	}
	return base
}

func codexAccountID(accessToken string) string {
	parts := strings.Split(accessToken, ".")
	if len(parts) < 2 {
		return ""
	}
	raw, err := base64.RawURLEncoding.DecodeString(parts[1])
	if err != nil {
		if raw, err = base64.URLEncoding.DecodeString(parts[1]); err != nil {
			return ""
		}
	}
	var claims map[string]any
	if json.Unmarshal(raw, &claims) != nil {
		return ""
	}
	if auth, ok := claims["https://api.openai.com/auth"].(map[string]any); ok {
		if id, ok := auth["chatgpt_account_id"].(string); ok {
			return id
		}
	}
	return ""
}

// ---- Grok (console.x.ai SSO cookie, Responses API) ------------------------

// GrokProvider talks to console.x.ai's web backend using an sso cookie token.
type GrokProvider struct {
	OpenAIProvider
}

var grokConsoleModels = []string{
	"grok-4.3-console", "grok-4.3-low", "grok-4.3-medium", "grok-4.3-high",
	"grok-4.20-0309-reasoning-console", "grok-4.20-0309-console",
	"grok-4.20-0309-non-reasoning-console", "grok-4.20-multi-agent-console",
	"grok-4.20-multi-agent-low", "grok-4.20-multi-agent-medium",
	"grok-4.20-multi-agent-high", "grok-4.20-multi-agent-xhigh",
	"grok-build-console", "*",
}

func NewGrokProvider(record *database.Provider) *GrokProvider {
	return &GrokProvider{
		OpenAIProvider: OpenAIProvider{
			BaseProvider: BaseProvider{
				Type:           "grok",
				Style:          constants.ApiStyleOpenAIResponses,
				DefaultBaseURL: "https://console.x.ai/v1",
				DefaultModels:  grokConsoleModels,
				ChatSuffix:     "/responses",
				MessagesSuffix: "/v1/messages",
				ModelsSuffix:   "/models",
				SupportsImport: true,
				Record:         record,
			},
		},
	}
}

// Headers sends the SSO token as a Cookie, appending any configured Cookie
// (e.g. cf_clearance) from extra headers.
func (p *GrokProvider) Headers(apiKey string, extra map[string]string) map[string]string {
	token := strings.TrimPrefix(strings.TrimSpace(apiKey), "sso=")
	base := map[string]string{
		"content-type": "application/json",
		"Cookie":       "sso=" + token,
	}
	var extraHdr map[string]any
	database.DecodeJSON(p.Record.ExtraHeaders, &extraHdr)
	for k, v := range extraHdr {
		if strings.EqualFold(k, "cookie") {
			base["Cookie"] = base["Cookie"] + "; " + fmt.Sprintf("%v", v)
			continue
		}
		base[k] = fmt.Sprintf("%v", v)
	}
	for k, v := range extra {
		base[k] = v
	}
	return base
}

// ---- Grok Build (xAI grok CLI subscription proxy) -------------------------

const (
	grokBuildClientVersion   = "0.2.111"
	grokBuildClientID        = "grok-shell"
	grokBuildUserAgent       = "grok-shell/0.2.111 (linux; x86_64)"
	grokBuildTokenAuthMarker = "xai-grok-cli"
)

// GrokBuildProvider serves xAI's grok CLI subscription via cli-chat-proxy.grok.com.
type GrokBuildProvider struct {
	XAIProvider
}

func NewGrokBuildProvider(record *database.Provider) *GrokBuildProvider {
	return &GrokBuildProvider{
		XAIProvider: XAIProvider{
			OpenAIProvider: OpenAIProvider{
				BaseProvider: BaseProvider{
					Type:            "grok-build",
					Style:           constants.ApiStyleOpenAI,
					DefaultBaseURL:  "https://cli-chat-proxy.grok.com/v1",
					DefaultModels:   []string{"grok-4.5", "grok-code-fast-1", "*"},
					ChatSuffix:      "/chat/completions",
					MessagesSuffix:  "/v1/messages",
					ModelsSuffix:    "/models",
					SupportsOAuth:   true,
					SupportsRefresh: true,
					Record:          record,
				},
			},
		},
	}
}

// Headers emulates the grok-shell client the CLI-chat proxy requires.
func (p *GrokBuildProvider) Headers(apiKey string, extra map[string]string) map[string]string {
	base := map[string]string{
		"Authorization":    "Bearer " + apiKey,
		"content-type":     "application/json",
		"X-XAI-Token-Auth": grokBuildTokenAuthMarker,
		"User-Agent":       grokBuildUserAgent,
		"X-Grok-Client-Id": grokBuildClientID,
		"X-Grok-Version":   grokBuildClientVersion,
	}
	var extraHdr map[string]any
	database.DecodeJSON(p.Record.ExtraHeaders, &extraHdr)
	for k, v := range extraHdr {
		base[k] = fmt.Sprintf("%v", v)
	}
	for k, v := range extra {
		base[k] = v
	}
	return base
}
