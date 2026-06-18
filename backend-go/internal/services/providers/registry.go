package providers

import (
	"net/http"
	"sort"

	"github.com/siiway/voidswitch/internal/constants"
	"github.com/siiway/voidswitch/internal/database"
)

type ProviderInterface interface {
	BaseURL() string
	UpstreamURL() string
	ModelsURL() string
	GetBalanceURL() string
	Headers(apiKey string, extra map[string]string) map[string]string
	MapModel(model string) string
	PrepareBody(body map[string]any) map[string]any
	Classify(statusCode int, body any) ErrorClass
	FetchBalance(client *http.Client, apiKey string) (*BalanceResult, error)
	GetType() string
	GetStyle() constants.ApiStyle
	GetRecord() *database.Provider
}

type constructorFunc func(record *database.Provider) ProviderInterface

var constructors = map[string]constructorFunc{
	"openai":        func(r *database.Provider) ProviderInterface { return NewOpenAIProvider(r) },
	"openai-resp":   func(r *database.Provider) ProviderInterface { return NewOpenAIResponsesProvider(r) },
	"anthropic":     func(r *database.Provider) ProviderInterface { return NewAnthropicProvider(r) },
	"claude-code":   func(r *database.Provider) ProviderInterface { return NewClaudeCodeProvider(r) },
	"deepseek":      func(r *database.Provider) ProviderInterface { return NewDeepSeekProvider(r) },
	"siliconflow":   func(r *database.Provider) ProviderInterface { return NewSiliconFlowProvider(r) },
	"openrouter":    func(r *database.Provider) ProviderInterface { return NewOpenRouterProvider(r) },
	"groq":          func(r *database.Provider) ProviderInterface { return NewGroqProvider(r) },
	"xai":           func(r *database.Provider) ProviderInterface { return NewXAIProvider(r) },
	"moonshot":      func(r *database.Provider) ProviderInterface { return NewMoonshotProvider(r) },
	"mimo":          func(r *database.Provider) ProviderInterface { return NewMiMoProvider(r) },
	"nvidia":        func(r *database.Provider) ProviderInterface { return NewNvidiaProvider(r) },
	"mistral":       func(r *database.Provider) ProviderInterface { return NewMistralProvider(r) },
	"together":      func(r *database.Provider) ProviderInterface { return NewTogetherProvider(r) },
	"fireworks":     func(r *database.Provider) ProviderInterface { return NewFireworksProvider(r) },
	"perplexity":    func(r *database.Provider) ProviderInterface { return NewPerplexityProvider(r) },
	"cerebras":      func(r *database.Provider) ProviderInterface { return NewCerebrasProvider(r) },
	"cloudflare":    func(r *database.Provider) ProviderInterface { return NewCloudflareProvider(r) },
	"deepinfra":     func(r *database.Provider) ProviderInterface { return NewDeepInfraProvider(r) },
	"gemini":        func(r *database.Provider) ProviderInterface { return NewGeminiProvider(r) },
	"novita":        func(r *database.Provider) ProviderInterface { return NewNovitaProvider(r) },
	"sambanova":     func(r *database.Provider) ProviderInterface { return NewSambaNovaProvider(r) },
	"hyperbolic":    func(r *database.Provider) ProviderInterface { return NewHyperbolicProvider(r) },
	"nebius":        func(r *database.Provider) ProviderInterface { return NewNebiusProvider(r) },
	"github-models": func(r *database.Provider) ProviderInterface { return NewGitHubModelsProvider(r) },
	"zhipu":         func(r *database.Provider) ProviderInterface { return NewZhipuProvider(r) },
	"qwen":          func(r *database.Provider) ProviderInterface { return NewQwenProvider(r) },
	"volcengine":    func(r *database.Provider) ProviderInterface { return NewVolcengineProvider(r) },
	"minimax":       func(r *database.Provider) ProviderInterface { return NewMiniMaxProvider(r) },
	"generic":       func(r *database.Provider) ProviderInterface { return NewGenericOpenAIProvider(r) },
}

func AdapterTypes() []string {
	types := make([]string, 0, len(constructors))
	for t := range constructors {
		types = append(types, t)
	}
	sort.Strings(types)
	return types
}

func GetAdapter(record *database.Provider) ProviderInterface {
	c, ok := constructors[record.Type]
	if !ok {
		c = constructors["generic"]
	}
	return c(record)
}

func AdapterCatalog() []map[string]any {
	types := AdapterTypes()
	catalog := make([]map[string]any, 0, len(types))
	for _, t := range types {
		p := constructors[t](&database.Provider{Type: t})
		entry := map[string]any{
			"type":              p.GetType(),
			"style":             string(p.GetStyle()),
			"default_base_url":  p.BaseURL(),
			"default_models":    p.GetRecord().Models,
			"supports_balance":  p.GetBalanceURL() != "",
		}
		catalog = append(catalog, entry)
	}
	return catalog
}

var _ ProviderInterface = (*BaseProvider)(nil)
var _ ProviderInterface = (*OpenAIProvider)(nil)
var _ ProviderInterface = (*OpenAIResponsesProvider)(nil)
var _ ProviderInterface = (*AnthropicProvider)(nil)
var _ ProviderInterface = (*ClaudeCodeProvider)(nil)
var _ ProviderInterface = (*DeepSeekProvider)(nil)
var _ ProviderInterface = (*CloudflareProvider)(nil)
var _ ProviderInterface = (*GenericOpenAIProvider)(nil)
