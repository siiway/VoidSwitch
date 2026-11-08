package services

import (
	"context"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"errors"
	"math/rand"
	"net/url"
	"strings"
	"time"

	"gorm.io/gorm"

	"github.com/siiway/voidswitch/internal/cryptoutil"
	"github.com/siiway/voidswitch/internal/database"
)

// Codex (OpenAI Codex subscription) OAuth: browser PKCE + device code + refresh.
const (
	codexClientID    = "app_EMoamEEZ73f0CkXaXp7hrann"
	codexAuthBase    = "https://auth.openai.com"
	codexTokenURL    = codexAuthBase + "/oauth/token"
	codexDeviceCode  = codexAuthBase + "/api/accounts/deviceauth/usercode"
	codexDeviceToken = codexAuthBase + "/api/accounts/deviceauth/token"
	codexDeviceVerif = "https://chatgpt.com/codex/device"
	codexRedirect    = "http://localhost:1455/auth/callback"
	codexScopes      = "openid profile email offline_access"
	codexUA          = "codex_cli_rs"
)

var (
	codexStates = newLoginStateStore(15 * time.Minute)

	ErrOAuthLogin    = errors.New("invalid or rejected login")
	ErrOAuthUpstream = errors.New("authentication endpoint unreachable")
)

func codexHeaders() map[string]string {
	return map[string]string{"User-Agent": codexUA, "Accept": "application/json"}
}

func pkcePair256() (verifier, challenge string) {
	verifier = b64url(randomBytes(64))
	sum := sha256.Sum256([]byte(verifier))
	challenge = b64url(sum[:])
	return
}

func randomBytes(n int) []byte {
	b := make([]byte, n)
	rand.Read(b)
	return b
}

// CodexBeginLogin starts the browser PKCE flow; the redirected URL is pasted back.
func CodexBeginLogin(providerID int) (authorizeURL, state string) {
	verifier, challenge := pkcePair256()
	state = b64url(randomBytes(32))
	codexStates.put(state, verifier, providerID)
	q := url.Values{}
	q.Set("response_type", "code")
	q.Set("client_id", codexClientID)
	q.Set("redirect_uri", codexRedirect)
	q.Set("scope", codexScopes)
	q.Set("code_challenge", challenge)
	q.Set("code_challenge_method", "S256")
	q.Set("state", state)
	q.Set("audience", "https://api.openai.com/v1")
	q.Set("id_token_add_organizations", "true")
	q.Set("codex_cli_simplified_flow", "true")
	q.Set("originator", codexUA)
	return codexAuthBase + "/oauth/authorize?" + q.Encode(), state
}

// ExtractCode parses a pasted callback URL or bare code.
func CodexExtractCode(raw string) (string, string, error) {
	code, state := extractOAuthCode(raw)
	if code == "" {
		return "", "", errors.New("could not find a code in the pasted callback URL")
	}
	return code, state, nil
}

func codexMakeBundle(data map[string]any, oldRefresh string) (map[string]any, error) {
	access, _ := data["access_token"].(string)
	if access == "" {
		return nil, errors.New("token response missing access_token")
	}
	idToken, _ := data["id_token"].(string)
	claims := jwtClaims(idToken)
	if claims == nil {
		claims = jwtClaims(access)
	}
	var accountID any
	if auth, ok := claims["https://api.openai.com/auth"].(map[string]any); ok {
		accountID = auth["chatgpt_account_id"]
	}
	refresh, _ := data["refresh_token"].(string)
	if refresh == "" {
		refresh = oldRefresh
	}
	expiresIn := 3600.0
	if v, ok := data["expires_in"].(float64); ok && v > 0 {
		expiresIn = v
	}
	scope := codexScopes
	if s, ok := data["scope"].(string); ok && s != "" {
		scope = s
	}
	return map[string]any{
		"access_token":  access,
		"refresh_token": refresh,
		"id_token":      idToken,
		"account_id":    accountID,
		"expires_at":    float64(time.Now().Unix()) + expiresIn,
		"scopes":        strings.Fields(scope),
	}, nil
}

func jwtClaims(token string) map[string]any {
	parts := strings.Split(token, ".")
	if len(parts) < 2 {
		return nil
	}
	raw, err := base64.RawURLEncoding.DecodeString(parts[1])
	if err != nil {
		if raw, err = base64.URLEncoding.DecodeString(parts[1]); err != nil {
			return nil
		}
	}
	var claims map[string]any
	if json.Unmarshal(raw, &claims) != nil {
		return nil
	}
	return claims
}

// CodexCompleteLogin finishes the browser login and returns the bundle.
func CodexCompleteLogin(ctx context.Context, codeInput, state string, providerID int) (map[string]any, error) {
	pending := codexStates.get(state)
	if pending == nil {
		return nil, errors.New("unknown or expired login — start sign-in again")
	}
	if pending.ProviderID != providerID {
		codexStates.discard(state)
		return nil, errors.New("this login was started for a different provider")
	}
	code, embedded, cErr := CodexExtractCode(codeInput)
	if cErr != nil {
		return nil, cErr
	}
	if embedded != "" && embedded != state {
		codexStates.discard(state)
		return nil, errors.New("state mismatch")
	}
	data, status, _, err := postOAuth(ctx, codexTokenURL, codexHeaders(), map[string]string{
		"grant_type":    "authorization_code",
		"client_id":     codexClientID,
		"code":          code,
		"code_verifier": pending.Verifier,
		"redirect_uri":  codexRedirect,
	}, nil)
	if err != nil {
		return nil, ErrOAuthUpstream
	}
	if status != 200 {
		codexStates.discard(state)
		return nil, ErrOAuthLogin
	}
	codexStates.discard(state)
	return codexMakeBundle(data, "")
}

// CodexDeviceStart begins the device-code flow.
func CodexDeviceStart(ctx context.Context) (map[string]any, error) {
	data, status, _, err := postOAuth(ctx, codexDeviceCode, codexHeaders(), nil,
		map[string]any{"client_id": codexClientID})
	if err != nil {
		return nil, ErrOAuthUpstream
	}
	if status != 200 || data["device_auth_id"] == nil || data["user_code"] == nil {
		return nil, ErrOAuthLogin
	}
	interval := 5
	if v, ok := data["interval"].(float64); ok && v >= 1 {
		interval = int(v)
	}
	expires := 900
	if v, ok := data["expires_in"].(float64); ok && v > 0 {
		expires = int(v)
	}
	verif := codexDeviceVerif
	if s, ok := data["verification_uri"].(string); ok && s != "" {
		verif = s
	}
	return map[string]any{
		"device_auth_id":   data["device_auth_id"],
		"user_code":        data["user_code"],
		"verification_url": verif,
		"interval":         interval,
		"expires_in":       expires,
	}, nil
}

// CodexDeviceComplete polls the device grant once; returns nil until approved.
func CodexDeviceComplete(ctx context.Context, deviceAuthID, userCode string) (map[string]any, error) {
	data, status, raw, err := postOAuth(ctx, codexDeviceToken, codexHeaders(), nil,
		map[string]any{"device_auth_id": deviceAuthID, "user_code": userCode})
	if err != nil {
		return nil, ErrOAuthUpstream
	}
	if status == 403 && strings.Contains(strings.ToLower(string(raw)), "pending") {
		return nil, nil
	}
	if status != 200 {
		return nil, ErrOAuthLogin
	}
	code, _ := data["authorization_code"].(string)
	verifier, _ := data["code_verifier"].(string)
	if code == "" || verifier == "" {
		return nil, ErrOAuthLogin
	}
	tok, tstatus, _, err := postOAuth(ctx, codexTokenURL, codexHeaders(), map[string]string{
		"grant_type":    "authorization_code",
		"client_id":     codexClientID,
		"code":          code,
		"code_verifier": verifier,
		"redirect_uri":  codexRedirect,
	}, nil)
	if err != nil {
		return nil, ErrOAuthUpstream
	}
	if tstatus != 200 {
		return nil, ErrOAuthLogin
	}
	return codexMakeBundle(tok, "")
}

// ParseCodexBundle returns the bundle if plaintext is a JSON OAuth bundle.
func ParseCodexBundle(plaintext string) map[string]any {
	var v map[string]any
	if json.Unmarshal([]byte(plaintext), &v) != nil {
		return nil
	}
	if v["access_token"] != nil || v["refresh_token"] != nil {
		return v
	}
	return nil
}

func bundleNearExpiry(bundle map[string]any) bool {
	exp, ok := bundle["expires_at"].(float64)
	if !ok {
		return false
	}
	return float64(time.Now().Unix())+300 >= exp
}

// CodexResolveAccessToken returns a valid access token, refreshing if needed.
func CodexResolveAccessToken(db *gorm.DB, key *database.ApiKey, secretKey string, forceRefresh bool) (string, error) {
	plain, err := cryptoutil.DecryptSecret(key.KeyCiphertext, secretKey)
	if err != nil {
		return "", err
	}
	bundle := ParseCodexBundle(plain)
	if bundle == nil {
		if forceRefresh {
			return "", errors.New("static token cannot be refreshed")
		}
		return plain, nil
	}
	access, _ := bundle["access_token"].(string)
	refresh, _ := bundle["refresh_token"].(string)
	if refresh == "" {
		if forceRefresh || access == "" {
			return "", errors.New("credential bundle has no refresh token")
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
	if b2["access_token"] != nil && !forceRefresh && !bundleNearExpiry(b2) {
		return b2["access_token"].(string), nil
	}
	rf, _ := b2["refresh_token"].(string)
	if rf == "" {
		a, _ := b2["access_token"].(string)
		if a == "" {
			return "", errors.New("credential bundle has no refresh token")
		}
		return a, nil
	}
	data, status, _, err := postOAuth(context.Background(), codexTokenURL, codexHeaders(), map[string]string{
		"grant_type":    "refresh_token",
		"client_id":     codexClientID,
		"refresh_token": rf,
	}, nil)
	if err != nil {
		return "", ErrOAuthUpstream
	}
	if status != 200 {
		return "", ErrOAuthLogin
	}
	rotated, err := codexMakeBundle(data, rf)
	if err != nil {
		return "", err
	}
	raw, _ := json.Marshal(rotated)
	ct, err := cryptoutil.EncryptSecret(string(raw), secretKey)
	if err != nil {
		return "", err
	}
	db.Model(&database.ApiKey{}).Where("id = ?", key.ID).Updates(map[string]any{
		"key_ciphertext": ct, "last_checked_at": time.Now().UTC(),
	})
	return rotated["access_token"].(string), nil
}
