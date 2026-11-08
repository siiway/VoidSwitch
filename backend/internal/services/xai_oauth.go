package services

import (
	"context"
	"encoding/json"
	"errors"
	"net/url"
	"strings"
	"time"

	"gorm.io/gorm"

	"github.com/siiway/voidswitch/internal/cryptoutil"
	"github.com/siiway/voidswitch/internal/database"
)

// xAI / Grok Build OAuth: interactive PKCE login + refresh.
const (
	xaiClientID     = "b1a00492-073a-47ea-816f-4c329264a828"
	xaiTokenURL     = "https://auth.x.ai/oauth2/token"
	xaiAuthorizeURL = "https://auth.x.ai/oauth2/authorize"
	xaiRedirectURI  = "http://127.0.0.1:56121/callback"
	xaiUA           = "grok-cli/1.0.0"
	xaiDefaultTTL   = 21600
)

var (
	xaiStates        = newLoginStateStore(10 * time.Minute)
	xaiRefreshScopes = []string{
		"openid", "profile", "email", "offline_access",
		"grok-cli:access", "api:access",
		"conversations:read", "conversations:write",
	}
	xaiLoginScopes = []string{
		"openid", "profile", "email", "offline_access",
		"grok-cli:access", "api:access",
	}
)

func xaiHeaders() map[string]string { return map[string]string{"User-Agent": xaiUA} }

// XAIBeginLogin starts the Grok Build interactive login.
func XAIBeginLogin(providerID int) (authorizeURL, state string) {
	verifier, challenge := pkcePair256()
	state = b64url(randomBytes(32))
	xaiStates.put(state, verifier, providerID)
	q := url.Values{}
	q.Set("response_type", "code")
	q.Set("client_id", xaiClientID)
	q.Set("redirect_uri", xaiRedirectURI)
	q.Set("scope", strings.Join(xaiLoginScopes, " "))
	q.Set("code_challenge", challenge)
	q.Set("code_challenge_method", "S256")
	q.Set("state", state)
	return xaiAuthorizeURL + "?" + q.Encode(), state
}

// XAIExtractCode parses a pasted callback URL or bare code.
func XAIExtractCode(raw string) (string, string, error) {
	code, st := extractOAuthCode(raw)
	if code == "" {
		return "", "", errors.New("could not find a code in the pasted callback URL")
	}
	return code, st, nil
}

// XAICompleteLogin finishes the interactive login and returns the bundle.
func XAICompleteLogin(ctx context.Context, codeInput, state string, providerID int) (map[string]any, error) {
	pending := xaiStates.get(state)
	if pending == nil {
		return nil, errors.New("unknown or expired login — start sign-in again")
	}
	if pending.ProviderID != providerID {
		xaiStates.discard(state)
		return nil, errors.New("this login was started for a different provider")
	}
	code, embedded, err := XAIExtractCode(codeInput)
	if err != nil {
		return nil, err
	}
	if embedded != "" && embedded != state {
		xaiStates.discard(state)
		return nil, errors.New("state mismatch")
	}
	data, status, _, perr := postOAuth(ctx, xaiTokenURL, xaiHeaders(), map[string]string{
		"grant_type":    "authorization_code",
		"code":          code,
		"redirect_uri":  xaiRedirectURI,
		"client_id":     xaiClientID,
		"code_verifier": pending.Verifier,
	}, nil)
	if perr != nil {
		return nil, ErrOAuthUpstream
	}
	if status != 200 {
		xaiStates.discard(state)
		return nil, ErrOAuthLogin
	}
	access, _ := data["access_token"].(string)
	refresh, _ := data["refresh_token"].(string)
	if access == "" || refresh == "" {
		xaiStates.discard(state)
		return nil, errors.New("login response missing tokens")
	}
	xaiStates.discard(state)
	scopes := xaiLoginScopes
	if s, ok := data["scope"].(string); ok && s != "" {
		scopes = strings.Fields(s)
	}
	ttl := xaiDefaultTTL
	if v, ok := data["expires_in"].(float64); ok && v > 0 {
		ttl = int(v)
	}
	return map[string]any{
		"access_token":  access,
		"refresh_token": refresh,
		"expires_at":    float64(time.Now().Unix()) + float64(ttl),
		"scopes":        scopes,
	}, nil
}

// XAIResolveAccessToken returns a usable xAI access token (refreshing if needed).
// A plain non-JSON secret (a static xai- API key) is returned as-is.
func XAIResolveAccessToken(db *gorm.DB, key *database.ApiKey, secretKey string, forceRefresh bool) (string, error) {
	plain, err := cryptoutil.DecryptSecret(key.KeyCiphertext, secretKey)
	if err != nil {
		return "", err
	}
	bundle := ParseCodexBundle(plain) // same {access_token, refresh_token, expires_at} shape
	if bundle == nil {
		if forceRefresh {
			return "", errors.New("static API key cannot be refreshed")
		}
		return plain, nil
	}
	access, _ := bundle["access_token"].(string)
	refresh, _ := bundle["refresh_token"].(string)
	if refresh == "" {
		if access == "" {
			return "", errors.New("credential bundle has neither access nor refresh token")
		}
		if forceRefresh {
			return "", errors.New("no refresh_token in credential bundle")
		}
		return access, nil
	}
	if access != "" && !forceRefresh && !bundleNearExpiry(bundle) {
		return access, nil
	}
	mu := lockForKey(key.ID)
	mu.Lock()
	defer mu.Unlock()

	var fresh database.ApiKey
	if err := db.First(&fresh, key.ID).Error; err != nil {
		return "", errors.New("key no longer exists")
	}
	plain2, _ := cryptoutil.DecryptSecret(fresh.KeyCiphertext, secretKey)
	b2 := ParseCodexBundle(plain2)
	if b2 == nil {
		return plain2, nil
	}
	if a2, _ := b2["access_token"].(string); a2 != "" && !forceRefresh && !bundleNearExpiry(b2) {
		return a2, nil
	}
	rf, _ := b2["refresh_token"].(string)
	if rf == "" {
		a2, _ := b2["access_token"].(string)
		if a2 == "" {
			return "", errors.New("credential bundle has no refresh token")
		}
		return a2, nil
	}
	data, status, _, perr := postOAuth(context.Background(), xaiTokenURL, xaiHeaders(), map[string]string{
		"grant_type":    "refresh_token",
		"refresh_token": rf,
		"client_id":     xaiClientID,
		"scope":         strings.Join(xaiRefreshScopes, " "),
	}, nil)
	if perr != nil {
		return "", ErrOAuthUpstream
	}
	if status != 200 {
		return "", ErrOAuthLogin
	}
	access2, _ := data["access_token"].(string)
	if access2 == "" {
		return "", errors.New("xAI refresh response missing access_token")
	}
	newRefresh, _ := data["refresh_token"].(string)
	if newRefresh == "" {
		newRefresh = rf
	}
	ttl := xaiDefaultTTL
	if v, ok := data["expires_in"].(float64); ok && v > 0 {
		ttl = int(v)
	}
	newBundle := map[string]any{
		"access_token":  access2,
		"refresh_token": newRefresh,
		"expires_at":    float64(time.Now().Unix()) + float64(ttl),
	}
	raw, _ := json.Marshal(newBundle)
	ct, err := cryptoutil.EncryptSecret(string(raw), secretKey)
	if err != nil {
		return "", err
	}
	db.Model(&database.ApiKey{}).Where("id = ?", key.ID).Updates(map[string]any{
		"key_ciphertext": ct, "last_checked_at": time.Now().UTC(),
	})
	return access2, nil
}
