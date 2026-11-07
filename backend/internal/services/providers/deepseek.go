package providers

import (
	"fmt"
	"io"
	"net/http"
	"strings"

	"github.com/siiway/voidswitch/internal/constants"
	"github.com/siiway/voidswitch/internal/database"
)

type DeepSeekProvider struct {
	BaseProvider
}

func NewDeepSeekProvider(record *database.Provider) *DeepSeekProvider {
	return &DeepSeekProvider{
		BaseProvider: BaseProvider{
			Type:             "deepseek",
			Style:            constants.ApiStyleOpenAI,
			DefaultBaseURL:   "https://api.deepseek.com",
			DefaultModels:    []string{"deepseek-v4-flash", "deepseek-v4-pro"},
			ChatSuffix:       "/chat/completions",
			MessagesSuffix:   "/v1/messages",
			ModelsSuffix:     "/models",
			BalanceSuffix:    "/user/balance",
			AnthropicVersion: "2023-06-01",
			Record:           record,
		},
	}
}

func (p *DeepSeekProvider) Classify(statusCode int, body any) ErrorClass {
	if statusCode == 401 {
		return ErrorKeyInvalid
	}
	if statusCode == 402 {
		return ErrorInsufficientBalance
	}
	if statusCode == 422 {
		text := errorText(body)
		if strings.Contains(text, "insufficient") || strings.Contains(text, "balance") {
			return ErrorInsufficientBalance
		}
		return ErrorBadRequest
	}
	if statusCode == 403 {
		return ErrorKeyInvalid
	}
	if bm, ok := body.(map[string]any); ok {
		if err, ok := bm["error"].(map[string]any); ok {
			if err["type"] == "authentication_error" {
				return ErrorKeyInvalid
			}
		}
	}
	return p.BaseProvider.Classify(statusCode, body)
}

func (p *DeepSeekProvider) FetchBalance(client *http.Client, apiKey string) (*BalanceResult, error) {
	url := p.GetBalanceURL()
	if url == "" {
		return nil, nil
	}

	headers := p.Headers(apiKey, nil)
	req, err := http.NewRequest("GET", url, nil)
	if err != nil {
		return nil, fmt.Errorf("deepseek balance request: %w", err)
	}
	for k, v := range headers {
		req.Header.Set(k, v)
	}

	resp, err := client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("deepseek balance fetch: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode == 401 {
		return &BalanceResult{
			Available: false,
			Detail:    map[string]any{"error": "authentication_error", "status": 401},
		}, nil
	}

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return nil, fmt.Errorf("deepseek balance: unexpected status %d", resp.StatusCode)
	}

	bodyBytes, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("deepseek balance read: %w", err)
	}

	data := TryJSON(bodyBytes)
	if dm, ok := data.(map[string]any); ok {
		isAvail := false
		if v, ok := dm["is_available"]; ok {
			isAvail, _ = v.(bool)
		}
		return &BalanceResult{Available: isAvail, Detail: dm}, nil
	}

	return nil, fmt.Errorf("deepseek balance: unexpected response format")
}

func errorText(body any) string {
	switch b := body.(type) {
	case map[string]any:
		if err, ok := b["error"].(map[string]any); ok {
			if msg, ok := err["message"].(string); ok {
				return strings.ToLower(msg)
			}
			return strings.ToLower(fmt.Sprintf("%v", err))
		}
		return strings.ToLower(fmt.Sprintf("%v", b))
	default:
		return strings.ToLower(fmt.Sprintf("%v", body))
	}
}
