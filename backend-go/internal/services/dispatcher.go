package services

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"strings"
	"time"

	"gorm.io/gorm"

	"github.com/siiway/voidswitch/internal/config"
	"github.com/siiway/voidswitch/internal/constants"
	"github.com/siiway/voidswitch/internal/core"
	"github.com/siiway/voidswitch/internal/database"
	"github.com/siiway/voidswitch/internal/services/providers"
)

// ResolveAccessToken is set by oauth_tokens.go for claude-code OAuth refresh.
var ResolveAccessToken func(*gorm.DB, *database.ApiKey, string, bool) (string, error)

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type DispatchRequest struct {
	InboundStyle       constants.ApiStyle
	Model              string
	Payload            map[string]any
	Stream             bool
	TokenID            *int
	UserSub            *string
	ClientIP           *string
	PassthroughHeaders map[string]string
}

type DispatchResult struct {
	StatusCode    int
	IsStream      bool
	MediaType     string
	Content       []byte
	StreamCh      <-chan []byte
	ProviderName  *string
	UpstreamStyle *string
	Model         *string
	Attempts      int
	Error         *string
}

type attemptResult struct {
	networkError bool
	errorStr     *string
	statusCode   int
	bodyBytes    []byte
	bodyJSON     any
	response     *http.Response
}

// ---------------------------------------------------------------------------
// Main dispatch entry point
// ---------------------------------------------------------------------------

func Dispatch(req *DispatchRequest) (*DispatchResult, error) {
	db := database.GetDatabase()
	settings := config.Load()
	pool := GetPool()

	providerList, err := SelectProviders(db.DB, req.Model)
	if err != nil {
		msg := fmt.Sprintf("provider selection failed: %v", err)
		return errorResultD(req.InboundStyle, 502, msg, "internal_error"), nil
	}
	if len(providerList) == 0 {
		return errorResultD(req.InboundStyle, 502, "No provider available for this model", "no_provider"), nil
	}

	proxies, err := ActiveProxies(db.DB)
	if err != nil {
		msg := fmt.Sprintf("proxy selection failed: %v", err)
		return errorResultD(req.InboundStyle, 502, msg, "internal_error"), nil
	}

	maxAttempts := settingsGetInt("max_retries", 6)
	connectTimeout := time.Duration(settingsGetInt("connect_timeout_seconds", 15)) * time.Second
	readTimeout := time.Duration(settingsGetInt("request_timeout_seconds", 300)) * time.Second
	maxProxyFails := settingsGetInt("max_proxy_failures", 3)
	maxKeyFails := settingsGetInt("max_key_failures", 3)
	rateLimitRecovery := settingsGetInt("rate_limit_recovery_seconds", 180)

	attempts := 0

	for pi := range providerList {
		provider := &providerList[pi]
		adapter := providers.GetAdapter(provider)
		upstreamStyle := adapter.GetStyle()
		upstreamModel, keyPool := ResolveModel(provider, req.Model)

		var keyModels []database.ApiKey
		if err := db.DB.Where("provider_id = ?", provider.ID).Find(&keyModels).Error; err != nil {
			continue
		}
		keyPtrs := make([]*database.ApiKey, len(keyModels))
		for i := range keyModels {
			keyPtrs[i] = &keyModels[i]
		}
		activeKeys := SelectKeys(keyPtrs, keyPool, rateLimitRecovery)
		if len(activeKeys) == 0 {
			continue
		}

		routes := RoutesForProvider(provider, proxies)

		for ki := range activeKeys {
			key := activeKeys[ki]

			if attempts >= maxAttempts {
				msg := "max retries exceeded"
				return errorResultD(req.InboundStyle, 502, msg, "retries_exceeded"), nil
			}

			secretKey := settings.Server.SecretKey
			if secretKey == "" {
				secretKey = os.Getenv("VOIDSWITCH_SERVER__SECRET_KEY")
			}

			token, err := resolveToken(db.DB, provider, key, secretKey, false)
			if err != nil {
				disableKeyD(key, constants.KeyStatusInvalid, fmt.Sprintf("token resolution failed: %v", err))
				continue
			}
			if token == "" {
				disableKeyD(key, constants.KeyStatusDisabled, "empty resolved token")
				continue
			}

			body := prepareBodyD(req, adapter, upstreamStyle, upstreamModel)
			headers := adapter.Headers(token, nil)
			for k, v := range req.PassthroughHeaders {
				if _, exists := headers[k]; !exists {
					headers[k] = v
				}
			}

			upstreamURL := adapter.UpstreamURL()
			start := routeStartD(key.ID, len(routes))

			for ri := 0; ri < len(routes); ri++ {
				routeIdx := (start + ri) % len(routes)
				routeInfo := routes[routeIdx]

				if attempts >= maxAttempts {
					msg := "max retries exceeded"
					return errorResultD(req.InboundStyle, 502, msg, "retries_exceeded"), nil
				}

				outcome := makeAttemptD(pool, adapter, routeInfo.Route, upstreamURL, headers, body, req.Stream, connectTimeout, readTimeout)
				attempts++

				if outcome.networkError {
					errStr := "network error"
					if outcome.errorStr != nil {
						errStr = *outcome.errorStr
					}
					if routeInfo.Proxy != nil {
						penalizeProxyD(routeInfo.Proxy, errStr, maxProxyFails)
					}
					continue
				}

				if routeInfo.Proxy != nil && outcome.statusCode > 0 && outcome.statusCode < 500 {
					rewardProxyD(routeInfo.Proxy)
				}

				class := adapter.Classify(outcome.statusCode, outcome.bodyJSON)

				switch class {
				case providers.ErrorOK:
					return finaliseSuccessD(db.DB, req, provider, adapter, key, routeInfo.Proxy, outcome, upstreamModel, attempts)

				case providers.ErrorKeyInvalid, providers.ErrorInsufficientBalance:
					reason := fmt.Sprintf("key returned status %d", outcome.statusCode)
					var ks constants.KeyStatus
					if class == providers.ErrorKeyInvalid {
						ks = constants.KeyStatusInvalid
					} else {
						ks = constants.KeyStatusInsufficientBalance
					}
					disableKeyD(key, ks, reason)

					if provider.Type == "claude-code" && outcome.statusCode == 401 {
						refreshedToken, refreshErr := resolveToken(db.DB, provider, key, secretKey, true)
						if refreshErr == nil && refreshedToken != "" && refreshedToken != token {
							refreshedHeaders := adapter.Headers(refreshedToken, nil)
							for k, v := range req.PassthroughHeaders {
								if _, exists := refreshedHeaders[k]; !exists {
									refreshedHeaders[k] = v
								}
							}
							retryOutcome := makeAttemptD(pool, adapter, routeInfo.Route, upstreamURL, refreshedHeaders, body, req.Stream, connectTimeout, readTimeout)
							attempts++
							if !retryOutcome.networkError {
								retryClass := adapter.Classify(retryOutcome.statusCode, retryOutcome.bodyJSON)
								if retryClass == providers.ErrorOK {
									return finaliseSuccessD(db.DB, req, provider, adapter, key, routeInfo.Proxy, retryOutcome, upstreamModel, attempts)
								}
							}
						}
					}
					goto nextKey

				case providers.ErrorRateLimited:
					reason := "rate limited"
					disableKeyD(key, constants.KeyStatusRateLimited, reason)
					goto nextKey

				case providers.ErrorBadRequest:
					return passthroughErrorD(req, outcome, upstreamStyle), nil

				case providers.ErrorServerError:
					key.FailedCount++
					if key.FailedCount >= maxKeyFails {
						disableKeyD(key, constants.KeyStatusDisabled, fmt.Sprintf("exceeded %d consecutive failures", maxKeyFails))
						goto nextKey
					}
					db.DB.Save(key)
				}
			}

		nextKey:
		}
	}

	errMsg := "all providers exhausted"
	logRequestD(db.DB, req, nil, nil, nil, nil, 502, false, attempts, &errMsg, nil)
	return errorResultD(req.InboundStyle, 502, errMsg, "all_exhausted"), nil
}

// ---------------------------------------------------------------------------
// Request/Response translation
// ---------------------------------------------------------------------------

func translateRequestD(inbound, upstream constants.ApiStyle, payload map[string]any) map[string]any {
	if inbound == upstream {
		return payload
	}
	if inbound == constants.ApiStyleOpenAI && upstream == constants.ApiStyleAnthropic {
		return OpenAIRequestToAnthropic(payload)
	}
	if inbound == constants.ApiStyleAnthropic && upstream == constants.ApiStyleOpenAI {
		return AnthropicRequestToOpenAI(payload)
	}
	return payload
}

func translateResponseD(inbound, upstream constants.ApiStyle, body map[string]any, model string) map[string]any {
	if inbound == upstream {
		return body
	}
	if inbound == constants.ApiStyleOpenAI && upstream == constants.ApiStyleAnthropic {
		return AnthropicResponseToOpenAI(body, model)
	}
	if inbound == constants.ApiStyleAnthropic && upstream == constants.ApiStyleOpenAI {
		return OpenAIResponseToAnthropic(body, model)
	}
	return body
}

func translateStreamD(inbound, upstream constants.ApiStyle, byteCh <-chan []byte, model string) <-chan []byte {
	if inbound == upstream {
		return byteCh
	}
	if inbound == constants.ApiStyleOpenAI && upstream == constants.ApiStyleAnthropic {
		return AnthropicStreamToOpenAI(byteCh, model)
	}
	if inbound == constants.ApiStyleAnthropic && upstream == constants.ApiStyleOpenAI {
		return OpenAIStreamToAnthropic(byteCh, model)
	}
	return byteCh
}

// ---------------------------------------------------------------------------
// Error helpers
// ---------------------------------------------------------------------------

func errorBodyD(style constants.ApiStyle, message, errType string) []byte {
	switch style {
	case constants.ApiStyleAnthropic:
		body := map[string]any{
			"type": "error",
			"error": map[string]any{
				"type":    errType,
				"message": message,
			},
		}
		b, _ := json.Marshal(body)
		return b
	default:
		body := map[string]any{
			"error": map[string]any{
				"message": message,
				"type":    errType,
			},
		}
		b, _ := json.Marshal(body)
		return b
	}
}

func errorResultD(style constants.ApiStyle, statusCode int, message, errType string) *DispatchResult {
	content := errorBodyD(style, message, errType)
	strMessage := message
	return &DispatchResult{
		StatusCode: statusCode,
		IsStream:   false,
		MediaType:  "application/json",
		Content:    content,
		Attempts:   0,
		Error:      &strMessage,
	}
}

func errorMessageD(body any) string {
	if body == nil {
		return "unknown error"
	}
	m, ok := body.(map[string]any)
	if !ok {
		return "unknown error"
	}
	if errObj, ok := m["error"]; ok {
		if errMap, ok := errObj.(map[string]any); ok {
			if msg, ok := errMap["message"].(string); ok {
				return msg
			}
		}
		if msg, ok := errObj.(string); ok {
			return msg
		}
	}
	if msg, ok := m["message"].(string); ok {
		return msg
	}
	return "unknown error"
}

func passthroughErrorD(req *DispatchRequest, outcome *attemptResult, upstreamStyle constants.ApiStyle) *DispatchResult {
	body := outcome.bodyBytes
	mediaType := "application/json"
	errStr := fmt.Sprintf("upstream error %d", outcome.statusCode)
	statusCode := outcome.statusCode

	if outcome.bodyJSON != nil {
		errStr = errorMessageD(outcome.bodyJSON)
	}

	if req.InboundStyle == constants.ApiStyleAnthropic && upstreamStyle == constants.ApiStyleOpenAI {
		if outcome.bodyJSON != nil {
			if m, ok := outcome.bodyJSON.(map[string]any); ok {
				translated := OpenAIResponseToAnthropic(m, req.Model)
				b, err := json.Marshal(translated)
				if err == nil {
					body = b
				}
			}
		}
	} else if req.InboundStyle == constants.ApiStyleOpenAI && upstreamStyle == constants.ApiStyleAnthropic {
		if outcome.bodyJSON != nil {
			if m, ok := outcome.bodyJSON.(map[string]any); ok {
				translated := AnthropicResponseToOpenAI(m, req.Model)
				b, err := json.Marshal(translated)
				if err == nil {
					body = b
				}
			}
		}
	}

	if body == nil {
		body = errorBodyD(req.InboundStyle, errStr, "upstream_error")
	}

	return &DispatchResult{
		StatusCode: statusCode,
		IsStream:   false,
		MediaType:  mediaType,
		Content:    body,
		Attempts:   1,
		Error:      &errStr,
	}
}

// ---------------------------------------------------------------------------
// Key / Proxy management
// ---------------------------------------------------------------------------

func disableKeyD(key *database.ApiKey, status constants.KeyStatus, reason string) {
	now := time.Now()
	key.Status = string(status)
	key.DisabledReason = &reason
	if key.DisabledSince == nil {
		key.DisabledSince = &now
	}
	db := database.GetDatabase()
	db.DB.Save(key)
}

func penalizeProxyD(proxy *database.Proxy, reason string, threshold int) {
	if proxy == nil {
		return
	}
	proxy.FailedCount++
	db := database.GetDatabase()
	if proxy.FailedCount >= threshold {
		proxy.Status = string(constants.ProxyStatusDisabled)
		proxy.DisabledReason = &reason
	}
	db.DB.Save(proxy)
}

func rewardKeyD(key *database.ApiKey) {
	if key == nil {
		return
	}
	if key.Status == string(constants.KeyStatusRateLimited) {
		key.Status = string(constants.KeyStatusActive)
		key.FailedCount = 0
		key.DisabledReason = nil
		key.DisabledSince = nil
	}
	now := time.Now()
	key.LastUsedAt = &now
}

func rewardProxyD(proxy *database.Proxy) {
	if proxy == nil {
		return
	}
	if proxy.FailedCount > 0 {
		proxy.FailedCount = 0
	}
	now := time.Now()
	proxy.LastUsedAt = &now
	db := database.GetDatabase()
	db.DB.Save(proxy)
}

// ---------------------------------------------------------------------------
// Token resolution
// ---------------------------------------------------------------------------

func resolveToken(db *gorm.DB, provider *database.Provider, key *database.ApiKey, secretKey string, forceRefresh bool) (string, error) {
	if provider.Type == "claude-code" && ResolveAccessToken != nil {
		return ResolveAccessToken(db, key, secretKey, forceRefresh)
	}
	return core.DecryptSecret(key.KeyCiphertext, secretKey)
}

// ---------------------------------------------------------------------------
// Body preparation
// ---------------------------------------------------------------------------

func prepareBodyD(req *DispatchRequest, adapter providers.ProviderInterface, upstreamStyle constants.ApiStyle, upstreamModel string) map[string]any {
	translated := translateRequestD(req.InboundStyle, upstreamStyle, req.Payload)

	body := make(map[string]any, len(translated)+2)
	for k, v := range translated {
		body[k] = v
	}

	body["model"] = upstreamModel

	if req.Stream {
		body["stream"] = true
	}

	if adapter.GetType() != "generic" && adapter.GetType() != "base" {
		body = adapter.PrepareBody(body)
	}

	provider := adapter.GetRecord()
	if provider != nil && provider.DropOpenCodeIdentityBlock {
		body = dropOpenCodeIdentityD(body, upstreamStyle)
	}

	return body
}

func dropOpenCodeIdentityD(body map[string]any, style constants.ApiStyle) map[string]any {
	switch style {
	case constants.ApiStyleAnthropic:
		if sys, ok := body["system"]; ok {
			if s, ok := sys.(string); ok && strings.Contains(s, "<opencode>") {
				delete(body, "system")
			}
		}
	default:
		messages, _ := body["messages"].([]any)
		if messages == nil {
			return body
		}
		filtered := make([]any, 0, len(messages))
		for _, m := range messages {
			msg, ok := m.(map[string]any)
			if !ok {
				filtered = append(filtered, m)
				continue
			}
			role, _ := msg["role"].(string)
			if role == "system" {
				content := msg["content"]
				if s, ok := content.(string); ok && strings.Contains(s, "<opencode>") {
					continue
				}
				if arr, ok := content.([]any); ok {
					hasOC := false
					for _, part := range arr {
						if pm, ok := part.(map[string]any); ok {
							if fmt.Sprint(pm["text"]) == "<opencode>" {
								hasOC = true
								break
							}
						}
					}
					if hasOC {
						continue
					}
				}
			}
			filtered = append(filtered, m)
		}
		body["messages"] = filtered
	}
	return body
}

// ---------------------------------------------------------------------------
// HTTP attempt
// ---------------------------------------------------------------------------

func makeAttemptD(pool *ClientPool, adapter providers.ProviderInterface, route Route, urlStr string, headers map[string]string, body map[string]any, stream bool, connectTimeout, readTimeout time.Duration) *attemptResult {
	client, err := pool.Get(route, connectTimeout, readTimeout)
	if err != nil {
		errStr := err.Error()
		return &attemptResult{networkError: true, errorStr: &errStr}
	}

	bodyBytes, err := json.Marshal(body)
	if err != nil {
		errStr := fmt.Sprintf("body marshal: %v", err)
		return &attemptResult{networkError: true, errorStr: &errStr}
	}

	req, err := http.NewRequest("POST", urlStr, bytes.NewReader(bodyBytes))
	if err != nil {
		errStr := err.Error()
		return &attemptResult{networkError: true, errorStr: &errStr}
	}

	for k, v := range headers {
		req.Header.Set(k, v)
	}

	if stream {
		req.Header.Set("Accept", "text/event-stream")
	} else {
		req.Header.Set("Accept", "application/json")
	}

	resp, err := client.Do(req)
	if err != nil {
		return classifyNetworkErrorD(err)
	}

	if stream && resp.StatusCode >= 200 && resp.StatusCode < 300 {
		return &attemptResult{
			networkError: false,
			statusCode:   resp.StatusCode,
			response:     resp,
		}
	}

	defer resp.Body.Close()

	rawBody, err := io.ReadAll(resp.Body)
	if err != nil {
		errStr := fmt.Sprintf("body read: %v", err)
		return &attemptResult{networkError: true, errorStr: &errStr}
	}

	var parsed any
	if len(rawBody) > 0 {
		parsed = providers.TryJSON(rawBody)
	}

	return &attemptResult{
		networkError: false,
		statusCode:   resp.StatusCode,
		bodyBytes:    rawBody,
		bodyJSON:     parsed,
		response:     resp,
	}
}

func classifyNetworkErrorD(err error) *attemptResult {
	errStr := err.Error()
	result := &attemptResult{networkError: true, errorStr: &errStr}

	if os.IsTimeout(err) {
		return result
	}

	if ue, ok := err.(*url.Error); ok {
		if os.IsTimeout(ue.Err) {
			return result
		}
		if _, ok := ue.Err.(*net.OpError); ok {
			return result
		}
		return result
	}

	if _, ok := err.(*net.OpError); ok {
		return result
	}

	if strings.Contains(errStr, "connection refused") ||
		strings.Contains(errStr, "no such host") ||
		strings.Contains(errStr, "connect:") ||
		strings.Contains(errStr, "i/o timeout") ||
		strings.Contains(errStr, "EOF") ||
		strings.Contains(errStr, "connection reset") {
		return result
	}

	return result
}

// ---------------------------------------------------------------------------
// Finalise success
// ---------------------------------------------------------------------------

func finaliseSuccessD(db *gorm.DB, req *DispatchRequest, provider *database.Provider, adapter providers.ProviderInterface, key *database.ApiKey, proxy *database.Proxy, outcome *attemptResult, upstreamModel string, attempts int) (*DispatchResult, error) {
	upstreamStyle := adapter.GetStyle()
	var usage map[string]int

	now := time.Now()
	key.LastUsedAt = &now
	key.TotalRequests++
	if key.FailedCount > 0 {
		key.FailedCount = 0
	}
	db.Save(key)

	if proxy != nil {
		proxy.LastUsedAt = &now
		db.Save(proxy)
	}

	if req.Stream {
		styleUpstream := upstreamStyle
		logID := logRequestD(db, req, provider, key, proxy, &styleUpstream, 200, true, attempts, nil, nil)

		streamCh := buildStreamD(outcome.response, req.InboundStyle, upstreamStyle, req.Model, logID, req.TokenID)

		providerName := provider.Name
		upstreamStyleStr := string(upstreamStyle)
		modelVal := upstreamModel

		return &DispatchResult{
			StatusCode:   200,
			IsStream:     true,
			MediaType:    "text/event-stream",
			StreamCh:     streamCh,
			ProviderName: &providerName,
			UpstreamStyle: &upstreamStyleStr,
			Model:        &modelVal,
			Attempts:     attempts,
		}, nil
	}

	var responseBody map[string]any
	if outcome.bodyJSON != nil {
		if m, ok := outcome.bodyJSON.(map[string]any); ok {
			responseBody = m
		}
	}
	if responseBody == nil {
		responseBody = map[string]any{}
	}

	usage = extractUsageD(responseBody, upstreamStyle)
	translated := translateResponseD(req.InboundStyle, upstreamStyle, responseBody, req.Model)

	content, err := json.Marshal(translated)
	if err != nil {
		errMsg := fmt.Sprintf("response marshal: %v", err)
		return errorResultD(req.InboundStyle, 500, errMsg, "internal_error"), nil
	}

	styleUpstream := upstreamStyle
	logRequestD(db, req, provider, key, proxy, &styleUpstream, 200, true, attempts, nil, usage)

	if req.TokenID != nil && usage != nil {
		totalTokens := usage["total_tokens"]
		if totalTokens == 0 {
			totalTokens = usage["prompt_tokens"] + usage["completion_tokens"]
		}
		bumpTokenUsageD(db, req.TokenID, totalTokens)
	}

	providerName := provider.Name
	upstreamStyleStr := string(upstreamStyle)
	modelVal := upstreamModel

	return &DispatchResult{
		StatusCode:    200,
		IsStream:      false,
		MediaType:     "application/json",
		Content:       content,
		ProviderName:  &providerName,
		UpstreamStyle: &upstreamStyleStr,
		Model:         &modelVal,
		Attempts:      attempts,
	}, nil
}

// ---------------------------------------------------------------------------
// Streaming
// ---------------------------------------------------------------------------

func buildStreamD(response *http.Response, inbound, upstream constants.ApiStyle, model string, logID int, tokenID *int) <-chan []byte {
	rawCh := make(chan []byte, 32)

	go func() {
		defer close(rawCh)
		defer response.Body.Close()
		buf := make([]byte, 8192)
		for {
			n, err := response.Body.Read(buf)
			if n > 0 {
				data := make([]byte, n)
				copy(data, buf[:n])
				rawCh <- data
			}
			if err != nil {
				if err != io.EOF {
					_ = err
				}
				return
			}
		}
	}()

	translated := translateStreamD(inbound, upstream, rawCh, model)

	usage := make(map[string]int)
	captured := captureUsageD(translated, &usage)

	outCh := make(chan []byte, 32)
	go func() {
		defer close(outCh)
		for chunk := range captured {
			outCh <- chunk
		}
		persistStreamUsageD(logID, tokenID, usage)
	}()

	return outCh
}

func captureUsageD(raw <-chan []byte, usage *map[string]int) <-chan []byte {
	out := make(chan []byte, 32)
	go func() {
		defer close(out)
		for chunk := range raw {
			out <- chunk
			sniffUsageD(string(chunk), usage)
		}
	}()
	return out
}

func sniffUsageD(block string, usage *map[string]int) {
	if len(block) == 0 {
		return
	}
	var payload map[string]any
	if err := json.Unmarshal([]byte(block), &payload); err != nil {
		return
	}
	if u, ok := payload["usage"]; ok {
		if um, ok := u.(map[string]any); ok {
			extracted := extractUsageMapD(um)
			if extracted["total_tokens"] > 0 || extracted["prompt_tokens"] > 0 || extracted["completion_tokens"] > 0 {
				*usage = extracted
			}
		}
	}
	for _, line := range strings.Split(block, "\n") {
		trimmed := strings.TrimSpace(line)
		if !strings.HasPrefix(trimmed, "data:") {
			continue
		}
		dataStr := strings.TrimPrefix(trimmed, "data:")
		dataStr = strings.TrimSpace(dataStr)
		if dataStr == "[DONE]" || dataStr == "" {
			continue
		}
		var chunk map[string]any
		if err := json.Unmarshal([]byte(dataStr), &chunk); err != nil {
			continue
		}
		if u, ok := chunk["usage"]; ok {
			if um, ok := u.(map[string]any); ok {
				extracted := extractUsageMapD(um)
				if extracted["total_tokens"] > 0 || extracted["prompt_tokens"] > 0 || extracted["completion_tokens"] > 0 {
					*usage = extracted
				}
			}
		}
	}
}

func persistStreamUsageD(logID int, tokenID *int, usage map[string]int) {
	if len(usage) == 0 {
		return
	}
	db := database.GetDatabase()
	var logEntry database.RequestLog
	if err := db.DB.First(&logEntry, logID).Error; err != nil {
		return
	}
	logEntry.PromptTokens = usage["prompt_tokens"]
	logEntry.CompletionTokens = usage["completion_tokens"]
	logEntry.TotalTokens = usage["total_tokens"]
	db.DB.Save(&logEntry)
	if tokenID != nil {
		totalTokens := usage["total_tokens"]
		if totalTokens == 0 {
			totalTokens = usage["prompt_tokens"] + usage["completion_tokens"]
		}
		bumpTokenUsageD(db.DB, tokenID, totalTokens)
	}
}

// ---------------------------------------------------------------------------
// Usage extraction
// ---------------------------------------------------------------------------

func extractUsageD(body any, upstream constants.ApiStyle) map[string]int {
	result := make(map[string]int)
	if body == nil {
		return result
	}
	m, ok := body.(map[string]any)
	if !ok {
		return result
	}
	usage, _ := m["usage"].(map[string]any)
	if usage == nil {
		return result
	}
	return extractUsageMapD(usage)
}

func extractUsageMapD(usage map[string]any) map[string]int {
	result := make(map[string]int)
	if v := toInt(usage["prompt_tokens"]); v > 0 {
		result["prompt_tokens"] = v
	}
	if v := toInt(usage["input_tokens"]); v > 0 {
		result["prompt_tokens"] = v
	}
	if v := toInt(usage["completion_tokens"]); v > 0 {
		result["completion_tokens"] = v
	}
	if v := toInt(usage["output_tokens"]); v > 0 {
		result["completion_tokens"] = v
	}
	if v := toInt(usage["total_tokens"]); v > 0 {
		result["total_tokens"] = v
	}
	if result["total_tokens"] == 0 {
		result["total_tokens"] = result["prompt_tokens"] + result["completion_tokens"]
	}
	return result
}

// ---------------------------------------------------------------------------
// Logging
// ---------------------------------------------------------------------------

func logRequestD(db *gorm.DB, req *DispatchRequest, provider *database.Provider, key *database.ApiKey, proxy *database.Proxy, upstreamStyle *constants.ApiStyle, statusCode int, success bool, attempts int, errMsg *string, usage map[string]int) int {
	var keyID, proxyID, providerID *int
	var providerName *string
	var upstreamStyleStr *string

	if provider != nil {
		id := provider.ID
		providerID = &id
		name := provider.Name
		providerName = &name
	}
	if key != nil {
		id := key.ID
		keyID = &id
	}
	if proxy != nil {
		id := proxy.ID
		proxyID = &id
	}
	if upstreamStyle != nil {
		s := string(*upstreamStyle)
		upstreamStyleStr = &s
	}

	inboundStyleStr := string(req.InboundStyle)
	modelStr := req.Model

	entry := database.RequestLog{
		TokenID:        req.TokenID,
		UserSub:        req.UserSub,
		ProviderID:     providerID,
		ProviderName:   providerName,
		KeyID:          keyID,
		ProxyID:        proxyID,
		Model:          &modelStr,
		InboundStyle:   &inboundStyleStr,
		UpstreamStyle:  upstreamStyleStr,
		StatusCode:     &statusCode,
		Success:        success,
		Stream:         req.Stream,
		Attempts:       attempts,
		Error:          errMsg,
	}

	if usage != nil {
		entry.PromptTokens = usage["prompt_tokens"]
		entry.CompletionTokens = usage["completion_tokens"]
		entry.TotalTokens = usage["total_tokens"]
	}

	db.Create(&entry)
	return entry.ID
}

func bumpTokenUsageD(db *gorm.DB, tokenID *int, tokens int) {
	if tokenID == nil || tokens <= 0 {
		return
	}
	var voidToken database.VoidToken
	if err := db.First(&voidToken, *tokenID).Error; err != nil {
		return
	}
	voidToken.TotalTokens += tokens
	db.Save(&voidToken)
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

func routeStartD(seed int, n int) int {
	if n <= 0 {
		return 0
	}
	return seed % n
}

func settingsGetInt(key string, def int) int {
	return GetInt(key, def)
}


