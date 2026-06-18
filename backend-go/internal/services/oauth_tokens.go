package services

import (
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"net/http"
	"net/url"
	"strings"
	"sync"
	"time"

	"github.com/siiway/voidswitch/internal/core"
	"github.com/siiway/voidswitch/internal/database"
	"gorm.io/gorm"
)

const (
	claudeClientID          = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
	claudeTokenURL          = "https://platform.claude.com/v1/oauth/token"
	claudeAuthorizeURL      = "https://claude.com/cai/oauth/authorize"
	claudeManualRedirectURL = "https://platform.claude.com/oauth/code/callback"

	refreshNearExpirySeconds = 300
	loginStateTTLSeconds     = 600

	oauthUserAgent = "claude-cli/2.1.150"
)

var refreshScopes = []string{
	"user:profile", "user:inference", "user:sessions:claude_code",
	"user:mcp_servers", "user:file_upload",
}

var loginScopes = []string{
	"org:create_api_key", "user:profile", "user:inference",
	"user:sessions:claude_code", "user:mcp_servers", "user:file_upload",
}

type LoginError struct{ Message string }

func (e *LoginError) Error() string { return e.Message }

type LoginUpstreamError struct{ Message string }

func (e *LoginUpstreamError) Error() string { return e.Message }

type NotRefreshableError struct{ Message string }

func (e *NotRefreshableError) Error() string { return e.Message }

type pendingLogin struct {
	Verifier   string
	ProviderID int
	Created    time.Time
}

type oauthStateStore struct {
	store map[string]pendingLogin
	ttl   time.Duration
	mu    sync.Mutex
}

func init() {
	ResolveAccessToken = resolveOAuthAccessToken
}

var loginStates = &oauthStateStore{
	store: make(map[string]pendingLogin),
	ttl:   time.Duration(loginStateTTLSeconds) * time.Second,
}

var refreshLocks = make(map[int]*sync.Mutex)
var refreshLocksMu sync.Mutex

func lockForKey(keyID int) *sync.Mutex {
	refreshLocksMu.Lock()
	defer refreshLocksMu.Unlock()
	mu, ok := refreshLocks[keyID]
	if !ok {
		mu = &sync.Mutex{}
		refreshLocks[keyID] = mu
	}
	return mu
}

func (s *oauthStateStore) put(state, verifier string, providerID int) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.gc()
	s.store[state] = pendingLogin{Verifier: verifier, ProviderID: providerID, Created: time.Now()}
}

func (s *oauthStateStore) peek(state string) *pendingLogin {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.gc()
	p, ok := s.store[state]
	if !ok {
		return nil
	}
	return &p
}

func (s *oauthStateStore) discard(state string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	delete(s.store, state)
}

func (s *oauthStateStore) gc() {
	cutoff := time.Now().Add(-s.ttl)
	for k, v := range s.store {
		if v.Created.Before(cutoff) {
			delete(s.store, k)
		}
	}
}

func b64url(data []byte) string {
	return base64.RawURLEncoding.EncodeToString(data)
}

func pkcePair() (verifier, challenge string) {
	b := make([]byte, 32)
	if _, err := rand.Read(b); err != nil {
		panic("oauth: failed to generate random bytes: " + err.Error())
	}
	verifier = b64url(b)
	h := sha256.Sum256([]byte(verifier))
	challenge = b64url(h[:])
	return
}

func BeginLogin(providerID int) (authorizeURL string, state string) {
	verifier, challenge := pkcePair()
	stateBytes := make([]byte, 32)
	if _, err := rand.Read(stateBytes); err != nil {
		panic("oauth: failed to generate state: " + err.Error())
	}
	state = b64url(stateBytes)
	loginStates.put(state, verifier, providerID)

	params := url.Values{}
	params.Set("code", "true")
	params.Set("client_id", claudeClientID)
	params.Set("response_type", "code")
	params.Set("redirect_uri", claudeManualRedirectURL)
	params.Set("scope", strings.Join(loginScopes, " "))
	params.Set("code_challenge", challenge)
	params.Set("code_challenge_method", "S256")
	params.Set("state", state)

	authorizeURL = claudeAuthorizeURL + "?" + params.Encode()
	return
}

func ExtractCode(raw string) (code string, embeddedState *string) {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return "", nil
	}
	if strings.Contains(raw, "://") || strings.Contains(raw, "code=") {
		if u, err := url.Parse(raw); err == nil {
			qs := u.Query()
			if c := qs.Get("code"); c != "" {
				if s := qs.Get("state"); s != "" {
					return c, &s
				}
				return c, nil
			}
		}
	}
	if idx := strings.IndexByte(raw, '#'); idx != -1 {
		c := raw[:idx]
		s := raw[idx+1:]
		if c != "" && s != "" {
			return c, &s
		}
	}
	return raw, nil
}

func CompleteLogin(codeInput string, state string, providerID int, db *gorm.DB) (map[string]any, error) {
	pending := loginStates.peek(state)
	if pending == nil {
		return nil, &LoginError{Message: "Unknown or expired login. Start the sign-in again."}
	}
	if pending.ProviderID != providerID {
		loginStates.discard(state)
		return nil, &LoginError{Message: "This sign-in was started for a different provider."}
	}

	code, embeddedState := ExtractCode(codeInput)
	if code == "" {
		loginStates.discard(state)
		return nil, &LoginError{Message: "No authorization code provided."}
	}
	if embeddedState != nil && *embeddedState != state {
		loginStates.discard(state)
		return nil, &LoginError{Message: "State mismatch — please restart the sign-in."}
	}

	routes, err := selectOAuthRoutes(db)
	if err != nil {
		return nil, &LoginUpstreamError{Message: "Failed to resolve outbound routes: " + err.Error()}
	}

	bundle, err := exchangeCode(code, pending.Verifier, state, routes)
	if err != nil {
		if _, ok := err.(*LoginError); ok {
			loginStates.discard(state)
		}
		return nil, err
	}

	loginStates.discard(state)
	return bundle, nil
}

func exchangeCode(code, verifier, state string, routes []Route) (map[string]any, error) {
	data, err := postToken(map[string]any{
		"grant_type":    "authorization_code",
		"code":          code,
		"redirect_uri":  claudeManualRedirectURL,
		"client_id":     claudeClientID,
		"code_verifier": verifier,
		"state":         state,
	}, routes, "exchange")
	if err != nil {
		return nil, err
	}

	accessToken, _ := data["access_token"].(string)
	refreshToken, _ := data["refresh_token"].(string)
	if accessToken == "" || refreshToken == "" {
		return nil, &LoginError{Message: "Token exchange response was missing the access/refresh token."}
	}

	expiresIn, _ := data["expires_in"].(float64)
	if expiresIn == 0 {
		expiresIn = 3600
	}
	scope, _ := data["scope"].(string)
	var scopes []string
	if scope != "" {
		scopes = strings.Fields(scope)
	} else {
		scopes = loginScopes
	}

	return map[string]any{
		"access_token":  accessToken,
		"refresh_token": refreshToken,
		"expires_at":    float64(time.Now().Unix()) + expiresIn,
		"scopes":        scopes,
	}, nil
}

func ParseBundle(plaintext string) map[string]any {
	var data map[string]any
	if err := json.Unmarshal([]byte(plaintext), &data); err != nil {
		return nil
	}
	if _, ok := data["access_token"]; ok {
		return data
	}
	return nil
}

func nearExpiry(bundle map[string]any) bool {
	expiresAt, ok := bundle["expires_at"].(float64)
	if !ok {
		return false
	}
	return float64(time.Now().Unix())+float64(refreshNearExpirySeconds) >= expiresAt
}

func resolveOAuthAccessToken(db *gorm.DB, key *database.ApiKey, secretKey string, forceRefresh bool) (string, error) {
	plaintext, _ := core.DecryptSecret(key.KeyCiphertext, secretKey)
	bundle := ParseBundle(plaintext)

	if bundle == nil {
		if forceRefresh {
			return "", &NotRefreshableError{Message: "static token cannot be refreshed"}
		}
		return plaintext, nil
	}

	refreshToken, _ := bundle["refresh_token"].(string)
	if refreshToken == "" {
		if forceRefresh {
			return "", &NotRefreshableError{Message: "no refresh_token in credential bundle"}
		}
		accessToken, _ := bundle["access_token"].(string)
		return accessToken, nil
	}

	if !forceRefresh && !nearExpiry(bundle) {
		accessToken, _ := bundle["access_token"].(string)
		return accessToken, nil
	}

	mu := lockForKey(key.ID)
	mu.Lock()
	defer mu.Unlock()

	if err := db.First(key, key.ID).Error; err != nil {
		log.Printf("oauth: orm_refresh_skipped key_id=%d error=%v", key.ID, err)
		if errors.Is(err, gorm.ErrRecordNotFound) {
			accessToken, _ := bundle["access_token"].(string)
			return accessToken, nil
		}
	}
	plaintext, _ = core.DecryptSecret(key.KeyCiphertext, secretKey)
	bundle = ParseBundle(plaintext)
	if bundle == nil {
		if forceRefresh {
			return "", &NotRefreshableError{Message: "static token cannot be refreshed"}
		}
		return plaintext, nil
	}

	rt, _ := bundle["refresh_token"].(string)
	if rt == "" {
		if forceRefresh {
			return "", &NotRefreshableError{Message: "no refresh_token in credential bundle"}
		}
		accessToken, _ := bundle["access_token"].(string)
		return accessToken, nil
	}
	if !forceRefresh && !nearExpiry(bundle) {
		accessToken, _ := bundle["access_token"].(string)
		return accessToken, nil
	}

	routes, err := selectOAuthRoutes(db)
	if err != nil {
		return "", &LoginUpstreamError{Message: "Failed to resolve outbound routes: " + err.Error()}
	}

	newBundle, err := refreshTokenCall(rt, routes)
	if err != nil {
		return "", err
	}

	bundleJSON, err := json.Marshal(newBundle)
	if err != nil {
		return "", fmt.Errorf("marshal refreshed bundle: %w", err)
	}
	ciphertext, err := core.EncryptSecret(string(bundleJSON), secretKey)
	if err != nil {
		return "", fmt.Errorf("encrypt refreshed bundle: %w", err)
	}

	key.KeyCiphertext = ciphertext
	now := time.Now().UTC()
	key.LastCheckedAt = &now

	if err := db.Save(key).Error; err != nil {
		return "", fmt.Errorf("save refreshed key: %w", err)
	}

	log.Printf("oauth: token_refreshed key_id=%d", key.ID)
	accessToken, _ := newBundle["access_token"].(string)
	return accessToken, nil
}

func refreshTokenCall(refreshToken string, routes []Route) (map[string]any, error) {
	data, err := postToken(map[string]any{
		"grant_type":    "refresh_token",
		"refresh_token": refreshToken,
		"client_id":     claudeClientID,
		"scope":         strings.Join(refreshScopes, " "),
	}, routes, "refresh")
	if err != nil {
		return nil, err
	}

	accessToken, _ := data["access_token"].(string)
	newRefreshToken, _ := data["refresh_token"].(string)
	if newRefreshToken == "" {
		newRefreshToken = refreshToken
	}
	expiresIn, _ := data["expires_in"].(float64)
	if expiresIn == 0 {
		expiresIn = 3600
	}

	return map[string]any{
		"access_token":  accessToken,
		"refresh_token": newRefreshToken,
		"expires_at":    float64(time.Now().Unix()) + expiresIn,
	}, nil
}

func selectOAuthRoutes(db *gorm.DB) ([]Route, error) {
	if db == nil {
		return []Route{NewRoute(nil, nil)}, nil
	}
	proxies, err := ActiveProxies(db)
	if err != nil {
		return nil, err
	}
	if len(proxies) == 0 {
		return []Route{NewRoute(nil, nil)}, nil
	}
	routes := make([]Route, 0, len(proxies)+1)
	for _, p := range proxies {
		routes = append(routes, NewRoute(&p.URL, p.LocalAddress))
	}
	routes = append(routes, NewRoute(nil, nil))
	return routes, nil
}

func postToken(payload map[string]any, routes []Route, op string) (map[string]any, error) {
	form := url.Values{}
	for k, v := range payload {
		form.Set(k, fmt.Sprint(v))
	}
	bodyStr := form.Encode()

	lastStatus := -1
	lastReason := "no outbound route available"

	if len(routes) == 0 {
		routes = []Route{NewRoute(nil, nil)}
	}

	for _, route := range routes {
		label := "direct"
		if route.ProxyURL != nil {
			label = *route.ProxyURL
		}

		client, err := GetPool().Get(route, 15*time.Second, 30*time.Second)
		if err != nil {
			lastStatus = -1
			lastReason = fmt.Sprintf("client error: %v", err)
			log.Printf("oauth: token_network_error op=%s route=%s error=%v", op, label, err)
			continue
		}

		req, err := http.NewRequest("POST", claudeTokenURL, strings.NewReader(bodyStr))
		if err != nil {
			lastStatus = -1
			lastReason = fmt.Sprintf("request build error: %v", err)
			log.Printf("oauth: token_network_error op=%s route=%s error=%v", op, label, err)
			continue
		}
		req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
		req.Header.Set("User-Agent", oauthUserAgent)

		resp, err := client.Do(req)
		if err != nil {
			lastStatus = -1
			lastReason = fmt.Sprintf("network error: %v", err)
			log.Printf("oauth: token_network_error op=%s route=%s error=%v", op, label, err)
			continue
		}

		respBody, _ := io.ReadAll(resp.Body)
		resp.Body.Close()

		if resp.StatusCode == 200 {
			var data map[string]any
			if err := json.Unmarshal(respBody, &data); err != nil {
				lastStatus = -1
				lastReason = "json parse error"
				continue
			}
			return data, nil
		}

		lastStatus = resp.StatusCode
		lastReason = shortReason(respBody)

		truncated := string(respBody)
		if len(truncated) > 300 {
			truncated = truncated[:300]
		}
		log.Printf("oauth: token_http_error op=%s route=%s status=%d body=%s", op, label, resp.StatusCode, truncated)

		if resp.StatusCode == 403 || resp.StatusCode == 408 || resp.StatusCode == 425 || resp.StatusCode == 429 || resp.StatusCode >= 500 {
			continue
		}
		return nil, &LoginError{Message: fmt.Sprintf("Claude rejected the %s (HTTP %d: %s).", op, resp.StatusCode, lastReason)}
	}

	detail := lastReason
	if lastStatus >= 0 {
		detail = fmt.Sprintf("HTTP %d: %s", lastStatus, lastReason)
	}
	return nil, &LoginUpstreamError{Message: fmt.Sprintf(
		"Could not reach Claude's token endpoint via any route (last: %s). Check the provider's proxies and retry.", detail,
	)}
}

func shortReason(body []byte) string {
	var data map[string]any
	if err := json.Unmarshal(body, &data); err != nil {
		return "rejected"
	}
	errField, ok := data["error"]
	if !ok {
		return "rejected"
	}
	switch e := errField.(type) {
	case map[string]any:
		if msg, ok := e["message"]; ok {
			return fmt.Sprint(msg)
		}
		if typ, ok := e["type"]; ok {
			return fmt.Sprint(typ)
		}
		return "rejected"
	case string:
		return e
	default:
		return "rejected"
	}
}
