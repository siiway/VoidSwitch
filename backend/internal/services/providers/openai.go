package providers

import (
	"fmt"
	"strings"

	"github.com/siiway/voidswitch/internal/constants"
	"github.com/siiway/voidswitch/internal/database"
)

type OpenAIProvider struct {
	BaseProvider
}

func NewOpenAIProvider(record *database.Provider) *OpenAIProvider {
	return &OpenAIProvider{
		BaseProvider: BaseProvider{
			Type:             "openai",
			Style:            constants.ApiStyleOpenAI,
			DefaultBaseURL:   "https://api.openai.com/v1",
			DefaultModels:    []string{"gpt-4o", "gpt-4o-mini", "gpt-4.1", "o3", "o4-mini"},
			ChatSuffix:       "/chat/completions",
			MessagesSuffix:   "/v1/messages",
			ModelsSuffix:     "/models",
			AnthropicVersion: "2023-06-01",
			Record:           record,
		},
	}
}

type SiliconFlowProvider struct {
	OpenAIProvider
}

func NewSiliconFlowProvider(record *database.Provider) *SiliconFlowProvider {
	return &SiliconFlowProvider{
		OpenAIProvider: OpenAIProvider{
			BaseProvider: BaseProvider{
				Type:             "siliconflow",
				Style:            constants.ApiStyleOpenAI,
				DefaultBaseURL:   "https://api.siliconflow.cn/v1",
				DefaultModels:    []string{"deepseek-ai/DeepSeek-V3", "Qwen/Qwen2.5-72B-Instruct"},
				ChatSuffix:       "/chat/completions",
				MessagesSuffix:   "/v1/messages",
				ModelsSuffix:     "/models",
				AnthropicVersion: "2023-06-01",
				Record:           record,
			},
		},
	}
}

type OpenRouterProvider struct {
	OpenAIProvider
}

func NewOpenRouterProvider(record *database.Provider) *OpenRouterProvider {
	return &OpenRouterProvider{
		OpenAIProvider: OpenAIProvider{
			BaseProvider: BaseProvider{
				Type:             "openrouter",
				Style:            constants.ApiStyleOpenAI,
				DefaultBaseURL:   "https://openrouter.ai/api/v1",
				DefaultModels:    []string{"*"},
				ChatSuffix:       "/chat/completions",
				MessagesSuffix:   "/v1/messages",
				ModelsSuffix:     "/models",
				AnthropicVersion: "2023-06-01",
				Record:           record,
			},
		},
	}
}

type GroqProvider struct {
	OpenAIProvider
}

func NewGroqProvider(record *database.Provider) *GroqProvider {
	return &GroqProvider{
		OpenAIProvider: OpenAIProvider{
			BaseProvider: BaseProvider{
				Type:             "groq",
				Style:            constants.ApiStyleOpenAI,
				DefaultBaseURL:   "https://api.groq.com/openai/v1",
				DefaultModels:    []string{"llama-3.3-70b-versatile", "*"},
				ChatSuffix:       "/chat/completions",
				MessagesSuffix:   "/v1/messages",
				ModelsSuffix:     "/models",
				AnthropicVersion: "2023-06-01",
				Record:           record,
			},
		},
	}
}

type XAIProvider struct {
	OpenAIProvider
}

func NewXAIProvider(record *database.Provider) *XAIProvider {
	return &XAIProvider{
		OpenAIProvider: OpenAIProvider{
			BaseProvider: BaseProvider{
				Type:             "xai",
				Style:            constants.ApiStyleOpenAI,
				DefaultBaseURL:   "https://api.x.ai/v1",
				DefaultModels:    []string{"grok-2", "grok-beta", "*"},
				ChatSuffix:       "/chat/completions",
				MessagesSuffix:   "/v1/messages",
				ModelsSuffix:     "/models",
				AnthropicVersion: "2023-06-01",
				Record:           record,
			},
		},
	}
}

type MoonshotProvider struct {
	OpenAIProvider
}

func NewMoonshotProvider(record *database.Provider) *MoonshotProvider {
	return &MoonshotProvider{
		OpenAIProvider: OpenAIProvider{
			BaseProvider: BaseProvider{
				Type:             "moonshot",
				Style:            constants.ApiStyleOpenAI,
				DefaultBaseURL:   "https://api.moonshot.cn/v1",
				DefaultModels:    []string{"moonshot-v1-8k", "kimi-k2", "*"},
				ChatSuffix:       "/chat/completions",
				MessagesSuffix:   "/v1/messages",
				ModelsSuffix:     "/models",
				AnthropicVersion: "2023-06-01",
				Record:           record,
			},
		},
	}
}

type MiMoProvider struct {
	OpenAIProvider
}

func NewMiMoProvider(record *database.Provider) *MiMoProvider {
	return &MiMoProvider{
		OpenAIProvider: OpenAIProvider{
			BaseProvider: BaseProvider{
				Type:             "mimo",
				Style:            constants.ApiStyleOpenAI,
				DefaultBaseURL:   "https://api.xiaomimimo.com/v1",
				DefaultModels:    []string{"mimo-v2.5-pro", "mimo-v2-pro", "mimo-v2-flash", "mimo-v2-omni"},
				ChatSuffix:       "/chat/completions",
				MessagesSuffix:   "/v1/messages",
				ModelsSuffix:     "/models",
				AnthropicVersion: "2023-06-01",
				Record:           record,
			},
		},
	}
}

type NvidiaProvider struct {
	OpenAIProvider
}

func NewNvidiaProvider(record *database.Provider) *NvidiaProvider {
	return &NvidiaProvider{
		OpenAIProvider: OpenAIProvider{
			BaseProvider: BaseProvider{
				Type:             "nvidia",
				Style:            constants.ApiStyleOpenAI,
				DefaultBaseURL:   "https://integrate.api.nvidia.com/v1",
				DefaultModels:    []string{"meta/llama-3.3-70b-instruct", "nvidia/llama-3.1-nemotron-70b-instruct", "*"},
				ChatSuffix:       "/chat/completions",
				MessagesSuffix:   "/v1/messages",
				ModelsSuffix:     "/models",
				AnthropicVersion: "2023-06-01",
				Record:           record,
			},
		},
	}
}

type MistralProvider struct {
	OpenAIProvider
}

func NewMistralProvider(record *database.Provider) *MistralProvider {
	return &MistralProvider{
		OpenAIProvider: OpenAIProvider{
			BaseProvider: BaseProvider{
				Type:             "mistral",
				Style:            constants.ApiStyleOpenAI,
				DefaultBaseURL:   "https://api.mistral.ai/v1",
				DefaultModels:    []string{"mistral-large-latest", "mistral-small-latest", "codestral-latest", "*"},
				ChatSuffix:       "/chat/completions",
				MessagesSuffix:   "/v1/messages",
				ModelsSuffix:     "/models",
				AnthropicVersion: "2023-06-01",
				Record:           record,
			},
		},
	}
}

type TogetherProvider struct {
	OpenAIProvider
}

func NewTogetherProvider(record *database.Provider) *TogetherProvider {
	return &TogetherProvider{
		OpenAIProvider: OpenAIProvider{
			BaseProvider: BaseProvider{
				Type:             "together",
				Style:            constants.ApiStyleOpenAI,
				DefaultBaseURL:   "https://api.together.xyz/v1",
				DefaultModels:    []string{"deepseek-ai/DeepSeek-V3", "meta-llama/Llama-3.3-70B-Instruct-Turbo", "*"},
				ChatSuffix:       "/chat/completions",
				MessagesSuffix:   "/v1/messages",
				ModelsSuffix:     "/models",
				AnthropicVersion: "2023-06-01",
				Record:           record,
			},
		},
	}
}

type FireworksProvider struct {
	OpenAIProvider
}

func NewFireworksProvider(record *database.Provider) *FireworksProvider {
	return &FireworksProvider{
		OpenAIProvider: OpenAIProvider{
			BaseProvider: BaseProvider{
				Type:             "fireworks",
				Style:            constants.ApiStyleOpenAI,
				DefaultBaseURL:   "https://api.fireworks.ai/inference/v1",
				DefaultModels:    []string{"accounts/fireworks/models/llama-v3p3-70b-instruct", "*"},
				ChatSuffix:       "/chat/completions",
				MessagesSuffix:   "/v1/messages",
				ModelsSuffix:     "/models",
				AnthropicVersion: "2023-06-01",
				Record:           record,
			},
		},
	}
}

type PerplexityProvider struct {
	OpenAIProvider
}

func NewPerplexityProvider(record *database.Provider) *PerplexityProvider {
	return &PerplexityProvider{
		OpenAIProvider: OpenAIProvider{
			BaseProvider: BaseProvider{
				Type:             "perplexity",
				Style:            constants.ApiStyleOpenAI,
				DefaultBaseURL:   "https://api.perplexity.ai",
				DefaultModels:    []string{"sonar", "sonar-pro", "sonar-reasoning", "*"},
				ChatSuffix:       "/chat/completions",
				MessagesSuffix:   "/v1/messages",
				ModelsSuffix:     "/models",
				AnthropicVersion: "2023-06-01",
				Record:           record,
			},
		},
	}
}

type CerebrasProvider struct {
	OpenAIProvider
}

func NewCerebrasProvider(record *database.Provider) *CerebrasProvider {
	return &CerebrasProvider{
		OpenAIProvider: OpenAIProvider{
			BaseProvider: BaseProvider{
				Type:             "cerebras",
				Style:            constants.ApiStyleOpenAI,
				DefaultBaseURL:   "https://api.cerebras.ai/v1",
				DefaultModels:    []string{"llama-3.3-70b", "llama3.1-8b", "*"},
				ChatSuffix:       "/chat/completions",
				MessagesSuffix:   "/v1/messages",
				ModelsSuffix:     "/models",
				AnthropicVersion: "2023-06-01",
				Record:           record,
			},
		},
	}
}

type DeepInfraProvider struct {
	OpenAIProvider
}

func NewDeepInfraProvider(record *database.Provider) *DeepInfraProvider {
	return &DeepInfraProvider{
		OpenAIProvider: OpenAIProvider{
			BaseProvider: BaseProvider{
				Type:             "deepinfra",
				Style:            constants.ApiStyleOpenAI,
				DefaultBaseURL:   "https://api.deepinfra.com/v1/openai",
				DefaultModels:    []string{"meta-llama/Llama-3.3-70B-Instruct", "*"},
				ChatSuffix:       "/chat/completions",
				MessagesSuffix:   "/v1/messages",
				ModelsSuffix:     "/models",
				AnthropicVersion: "2023-06-01",
				Record:           record,
			},
		},
	}
}

type GeminiProvider struct {
	OpenAIProvider
}

func NewGeminiProvider(record *database.Provider) *GeminiProvider {
	return &GeminiProvider{
		OpenAIProvider: OpenAIProvider{
			BaseProvider: BaseProvider{
				Type:             "gemini",
				Style:            constants.ApiStyleOpenAI,
				DefaultBaseURL:   "https://generativelanguage.googleapis.com/v1beta/openai",
				DefaultModels:    []string{"gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.0-flash", "*"},
				ChatSuffix:       "/chat/completions",
				MessagesSuffix:   "/v1/messages",
				ModelsSuffix:     "/models",
				AnthropicVersion: "2023-06-01",
				Record:           record,
			},
		},
	}
}

type NovitaProvider struct {
	OpenAIProvider
}

func NewNovitaProvider(record *database.Provider) *NovitaProvider {
	return &NovitaProvider{
		OpenAIProvider: OpenAIProvider{
			BaseProvider: BaseProvider{
				Type:             "novita",
				Style:            constants.ApiStyleOpenAI,
				DefaultBaseURL:   "https://api.novita.ai/v3/openai",
				DefaultModels:    []string{"*"},
				ChatSuffix:       "/chat/completions",
				MessagesSuffix:   "/v1/messages",
				ModelsSuffix:     "/models",
				AnthropicVersion: "2023-06-01",
				Record:           record,
			},
		},
	}
}

type SambaNovaProvider struct {
	OpenAIProvider
}

func NewSambaNovaProvider(record *database.Provider) *SambaNovaProvider {
	return &SambaNovaProvider{
		OpenAIProvider: OpenAIProvider{
			BaseProvider: BaseProvider{
				Type:             "sambanova",
				Style:            constants.ApiStyleOpenAI,
				DefaultBaseURL:   "https://api.sambanova.ai/v1",
				DefaultModels:    []string{"Meta-Llama-3.3-70B-Instruct", "*"},
				ChatSuffix:       "/chat/completions",
				MessagesSuffix:   "/v1/messages",
				ModelsSuffix:     "/models",
				AnthropicVersion: "2023-06-01",
				Record:           record,
			},
		},
	}
}

type HyperbolicProvider struct {
	OpenAIProvider
}

func NewHyperbolicProvider(record *database.Provider) *HyperbolicProvider {
	return &HyperbolicProvider{
		OpenAIProvider: OpenAIProvider{
			BaseProvider: BaseProvider{
				Type:             "hyperbolic",
				Style:            constants.ApiStyleOpenAI,
				DefaultBaseURL:   "https://api.hyperbolic.xyz/v1",
				DefaultModels:    []string{"*"},
				ChatSuffix:       "/chat/completions",
				MessagesSuffix:   "/v1/messages",
				ModelsSuffix:     "/models",
				AnthropicVersion: "2023-06-01",
				Record:           record,
			},
		},
	}
}

type NebiusProvider struct {
	OpenAIProvider
}

func NewNebiusProvider(record *database.Provider) *NebiusProvider {
	return &NebiusProvider{
		OpenAIProvider: OpenAIProvider{
			BaseProvider: BaseProvider{
				Type:             "nebius",
				Style:            constants.ApiStyleOpenAI,
				DefaultBaseURL:   "https://api.studio.nebius.com/v1",
				DefaultModels:    []string{"*"},
				ChatSuffix:       "/chat/completions",
				MessagesSuffix:   "/v1/messages",
				ModelsSuffix:     "/models",
				AnthropicVersion: "2023-06-01",
				Record:           record,
			},
		},
	}
}

type GitHubModelsProvider struct {
	OpenAIProvider
}

func NewGitHubModelsProvider(record *database.Provider) *GitHubModelsProvider {
	return &GitHubModelsProvider{
		OpenAIProvider: OpenAIProvider{
			BaseProvider: BaseProvider{
				Type:             "github-models",
				Style:            constants.ApiStyleOpenAI,
				DefaultBaseURL:   "https://models.github.ai/inference",
				DefaultModels:    []string{"gpt-4o", "gpt-4o-mini", "*"},
				ChatSuffix:       "/chat/completions",
				MessagesSuffix:   "/v1/messages",
				ModelsSuffix:     "/models",
				AnthropicVersion: "2023-06-01",
				Record:           record,
			},
		},
	}
}

type ZhipuProvider struct {
	OpenAIProvider
}

func NewZhipuProvider(record *database.Provider) *ZhipuProvider {
	return &ZhipuProvider{
		OpenAIProvider: OpenAIProvider{
			BaseProvider: BaseProvider{
				Type:             "zhipu",
				Style:            constants.ApiStyleOpenAI,
				DefaultBaseURL:   "https://open.bigmodel.cn/api/paas/v4",
				DefaultModels:    []string{"glm-4.6", "glm-4.5", "glm-4-flash", "*"},
				ChatSuffix:       "/chat/completions",
				MessagesSuffix:   "/v1/messages",
				ModelsSuffix:     "/models",
				AnthropicVersion: "2023-06-01",
				Record:           record,
			},
		},
	}
}

type QwenProvider struct {
	OpenAIProvider
}

func NewQwenProvider(record *database.Provider) *QwenProvider {
	return &QwenProvider{
		OpenAIProvider: OpenAIProvider{
			BaseProvider: BaseProvider{
				Type:             "qwen",
				Style:            constants.ApiStyleOpenAI,
				DefaultBaseURL:   "https://dashscope.aliyuncs.com/compatible-mode/v1",
				DefaultModels:    []string{"qwen-max", "qwen-plus", "qwen-turbo", "*"},
				ChatSuffix:       "/chat/completions",
				MessagesSuffix:   "/v1/messages",
				ModelsSuffix:     "/models",
				AnthropicVersion: "2023-06-01",
				Record:           record,
			},
		},
	}
}

type VolcengineProvider struct {
	OpenAIProvider
}

func NewVolcengineProvider(record *database.Provider) *VolcengineProvider {
	return &VolcengineProvider{
		OpenAIProvider: OpenAIProvider{
			BaseProvider: BaseProvider{
				Type:             "volcengine",
				Style:            constants.ApiStyleOpenAI,
				DefaultBaseURL:   "https://ark.cn-beijing.volces.com/api/v3",
				DefaultModels:    []string{"*"},
				ChatSuffix:       "/chat/completions",
				MessagesSuffix:   "/v1/messages",
				ModelsSuffix:     "/models",
				AnthropicVersion: "2023-06-01",
				Record:           record,
			},
		},
	}
}

type MiniMaxProvider struct {
	OpenAIProvider
}

func NewMiniMaxProvider(record *database.Provider) *MiniMaxProvider {
	return &MiniMaxProvider{
		OpenAIProvider: OpenAIProvider{
			BaseProvider: BaseProvider{
				Type:             "minimax",
				Style:            constants.ApiStyleOpenAI,
				DefaultBaseURL:   "https://api.minimax.io/v1",
				DefaultModels:    []string{"MiniMax-M2", "*"},
				ChatSuffix:       "/chat/completions",
				MessagesSuffix:   "/v1/messages",
				ModelsSuffix:     "/models",
				AnthropicVersion: "2023-06-01",
				Record:           record,
			},
		},
	}
}

type CloudflareProvider struct {
	OpenAIProvider
	cfAccountID string
	cfToken     string
}

func NewCloudflareProvider(record *database.Provider) *CloudflareProvider {
	return &CloudflareProvider{
		OpenAIProvider: OpenAIProvider{
			BaseProvider: BaseProvider{
				Type:             "cloudflare",
				Style:            constants.ApiStyleOpenAI,
				DefaultBaseURL:   "https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1",
				DefaultModels:    []string{"*"},
				ChatSuffix:       "/chat/completions",
				MessagesSuffix:   "/v1/messages",
				ModelsSuffix:     "/models",
				AnthropicVersion: "2023-06-01",
				Record:           record,
			},
		},
	}
}

func parseCFKey(plaintext string) (accountID, token string) {
	if idx := strings.Index(plaintext, "@"); idx >= 0 {
		return plaintext[:idx], plaintext[idx+1:]
	}
	return "", plaintext
}

func (p *CloudflareProvider) BaseURL() string {
	raw := strings.TrimRight(p.Record.BaseURL, "/")
	if raw == "" {
		raw = p.DefaultBaseURL
	}
	if p.cfAccountID != "" {
		raw = strings.Replace(raw, "{account_id}", p.cfAccountID, 1)
	}
	return raw
}

func (p *CloudflareProvider) Headers(apiKey string, extra map[string]string) map[string]string {
	p.cfAccountID, p.cfToken = parseCFKey(apiKey)
	return p.OpenAIProvider.Headers(p.cfToken, extra)
}

type OpenAIResponsesProvider struct {
	OpenAIProvider
}

func NewOpenAIResponsesProvider(record *database.Provider) *OpenAIResponsesProvider {
	return &OpenAIResponsesProvider{
		OpenAIProvider: OpenAIProvider{
			BaseProvider: BaseProvider{
				Type:             "openai-resp",
				Style:            constants.ApiStyleOpenAIResponses,
				DefaultBaseURL:   "https://api.openai.com/v1",
				DefaultModels:    []string{"gpt-5", "gpt-5-mini", "gpt-4.1", "o3", "o4-mini"},
				ChatSuffix:       "/responses",
				MessagesSuffix:   "/v1/messages",
				ModelsSuffix:     "/models",
				AnthropicVersion: "2023-06-01",
				Record:           record,
			},
		},
	}
}

func (p *OpenAIResponsesProvider) UpstreamURL() string {
	return p.BaseURL() + "/responses"
}

type GenericOpenAIProvider struct {
	OpenAIProvider
}

func NewGenericOpenAIProvider(record *database.Provider) *GenericOpenAIProvider {
	return &GenericOpenAIProvider{
		OpenAIProvider: OpenAIProvider{
			BaseProvider: BaseProvider{
				Type:             "generic",
				Style:            constants.ApiStyleOpenAI,
				DefaultBaseURL:   "",
				DefaultModels:    []string{"*"},
				ChatSuffix:       "/chat/completions",
				MessagesSuffix:   "/v1/messages",
				ModelsSuffix:     "/models",
				AnthropicVersion: "2023-06-01",
				Record:           record,
			},
		},
	}
}

func init() {
	_ = fmt.Sprintf
}
