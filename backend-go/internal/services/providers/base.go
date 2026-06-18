package providers

import (
	"encoding/json"
	"fmt"
	"net/http"
	"strings"

	"github.com/siiway/voidswitch/internal/constants"
	"github.com/siiway/voidswitch/internal/database"
)

type ErrorClass string

const (
	ErrorOK                  ErrorClass = "ok"
	ErrorKeyInvalid          ErrorClass = "key_invalid"
	ErrorInsufficientBalance ErrorClass = "insufficient_balance"
	ErrorRateLimited         ErrorClass = "rate_limited"
	ErrorBadRequest          ErrorClass = "bad_request"
	ErrorServerError         ErrorClass = "server_error"
)

type BalanceResult struct {
	Available bool
	Detail    map[string]any
}

type BaseProvider struct {
	Type             string
	Style            constants.ApiStyle
	DefaultBaseURL   string
	DefaultModels    []string
	ChatSuffix       string
	MessagesSuffix   string
	ModelsSuffix     string
	BalanceSuffix    string
	AnthropicVersion string
	Record           *database.Provider
}

func NewBaseProvider(record *database.Provider) *BaseProvider {
	return &BaseProvider{
		Type:             "base",
		Style:            constants.ApiStyleOpenAI,
		DefaultModels:    []string{},
		ChatSuffix:       "/chat/completions",
		MessagesSuffix:   "/v1/messages",
		ModelsSuffix:     "/models",
		AnthropicVersion: "2023-06-01",
		Record:           record,
	}
}

func (p *BaseProvider) BaseURL() string {
	url := p.Record.BaseURL
	if url == "" {
		url = p.DefaultBaseURL
	}
	return strings.TrimRight(url, "/")
}

func (p *BaseProvider) UpstreamURL() string {
	if p.Style == constants.ApiStyleAnthropic {
		return p.BaseURL() + p.MessagesSuffix
	}
	return p.BaseURL() + p.ChatSuffix
}

func (p *BaseProvider) ModelsURL() string {
	return p.BaseURL() + p.ModelsSuffix
}

func (p *BaseProvider) GetBalanceURL() string {
	if p.Record.BalanceURL != nil && *p.Record.BalanceURL != "" {
		return *p.Record.BalanceURL
	}
	if p.BalanceSuffix != "" {
		return p.BaseURL() + p.BalanceSuffix
	}
	return ""
}

func (p *BaseProvider) Headers(apiKey string, extra map[string]string) map[string]string {
	base := map[string]string{
		"content-type": "application/json",
	}
	if p.Style == constants.ApiStyleAnthropic {
		base["x-api-key"] = apiKey
		base["anthropic-version"] = p.AnthropicVersion
	} else {
		base["Authorization"] = "Bearer " + apiKey
	}
	for k, v := range p.Record.ExtraHeaders {
		base[k] = fmt.Sprintf("%v", v)
	}
	if extra != nil {
		for k, v := range extra {
			base[k] = v
		}
	}
	return base
}

func (p *BaseProvider) MapModel(model string) string {
	if p.Record.ModelMap != nil {
		if mapped, ok := p.Record.ModelMap[model]; ok {
			return fmt.Sprintf("%v", mapped)
		}
	}
	return model
}

func (p *BaseProvider) PrepareBody(body map[string]any) map[string]any {
	return body
}

func (p *BaseProvider) Classify(statusCode int, body any) ErrorClass {
	if statusCode >= 200 && statusCode < 300 {
		return ErrorOK
	}
	if statusCode == 401 || statusCode == 403 {
		return ErrorKeyInvalid
	}
	if statusCode == 402 {
		return ErrorInsufficientBalance
	}
	if statusCode == 429 {
		return ErrorRateLimited
	}
	if statusCode == 408 || statusCode == 409 || statusCode == 425 || statusCode >= 500 {
		return ErrorServerError
	}
	if statusCode >= 400 && statusCode < 500 {
		return ErrorBadRequest
	}
	return ErrorServerError
}

func (p *BaseProvider) FetchBalance(client *http.Client, apiKey string) (*BalanceResult, error) {
	return nil, nil
}

func (p *BaseProvider) GetType() string {
	return p.Type
}

func (p *BaseProvider) GetStyle() constants.ApiStyle {
	return p.Style
}

func (p *BaseProvider) GetRecord() *database.Provider {
	return p.Record
}

func TryJSON(data []byte) any {
	var v any
	if err := json.Unmarshal(data, &v); err != nil {
		return nil
	}
	return v
}
