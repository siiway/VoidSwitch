// Package core holds cross-cutting helpers: sessions, tokens, roles, audits.
package core

import (
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/base64"
	"encoding/hex"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/golang-jwt/jwt/v5"

	"github.com/siiway/voidswitch/internal/constants"
)

const (
	VoidTokenPrefix      = "vs-"
	ProviderKeyAPIPrefix = "vsk-"
	LoginTokenPrefix     = "vsl-"
)

// GenerateToken produces an opaque high-entropy token with the given prefix,
// using the same charset family as Python's secrets.token_urlsafe.
func GenerateToken(prefix string) (string, error) {
	b := make([]byte, 32)
	if _, err := rand.Read(b); err != nil {
		return "", err
	}
	return prefix + base64.RawURLEncoding.EncodeToString(b), nil
}

func GenerateVoidToken() (string, error)        { return GenerateToken(VoidTokenPrefix) }
func GenerateProviderAPIToken() (string, error) { return GenerateToken(ProviderKeyAPIPrefix) }
func GenerateLoginToken() (string, error)       { return GenerateToken(LoginTokenPrefix) }

// HashToken is a deterministic SHA-256 hex hash for constant-time DB lookup.
func HashToken(token string) string {
	h := sha256.Sum256([]byte(token))
	return hex.EncodeToString(h[:])
}

// TokenFingerprint is a short non-reversible label (hash head + last 4).
func TokenFingerprint(token string) string {
	tail := token
	if len(token) >= 4 {
		tail = token[len(token)-4:]
	}
	head := HashToken(token)[:6]
	return head + "…" + tail
}

func ConstantTimeEquals(a, b string) bool {
	return subtle.ConstantTimeCompare([]byte(a), []byte(b)) == 1
}

// ---- session JWT (HS256, iss=voidswitch) ----------------------------------

func CreateSessionToken(secret, subject string, extra map[string]any, ttlMinutes int) (string, error) {
	now := time.Now().UTC()
	claims := jwt.MapClaims{
		"iss": "voidswitch",
		"sub": subject,
		"iat": now.Unix(),
		"exp": now.Add(time.Duration(ttlMinutes) * time.Minute).Unix(),
	}
	for k, v := range extra {
		switch k {
		case "iss", "sub", "iat", "exp":
			continue
		}
		claims[k] = v
	}
	return jwt.NewWithClaims(jwt.SigningMethodHS256, claims).SignedString([]byte(secret))
}

func DecodeSessionToken(tokenString, secret string) (map[string]any, error) {
	parsed, err := jwt.Parse(tokenString, func(t *jwt.Token) (any, error) {
		if _, ok := t.Method.(*jwt.SigningMethodHMAC); !ok {
			return nil, fmt.Errorf("unexpected signing method %v", t.Header["alg"])
		}
		return []byte(secret), nil
	}, jwt.WithIssuer("voidswitch"), jwt.WithValidMethods([]string{"HS256"}))
	if err != nil {
		return nil, err
	}
	claims, ok := parsed.Claims.(jwt.MapClaims)
	if !ok || !parsed.Valid {
		return nil, errors.New("invalid session token")
	}
	out := make(map[string]any, len(claims))
	for k, v := range claims {
		out[k] = v
	}
	return out, nil
}

// ---- OAuth state (stateless, embeds PKCE verifier) -----------------------

const oauthStateType = "oauth_state"

func CreateOAuthState(secret, verifier string, ttlMinutes int) (string, error) {
	now := time.Now().UTC()
	nonce := make([]byte, 12)
	_, _ = rand.Read(nonce)
	claims := jwt.MapClaims{
		"typ":   oauthStateType,
		"vfr":   verifier,
		"nonce": base64.RawURLEncoding.EncodeToString(nonce),
		"iat":   now.Unix(),
		"exp":   now.Add(time.Duration(ttlMinutes) * time.Minute).Unix(),
		"iss":   "voidswitch",
	}
	return jwt.NewWithClaims(jwt.SigningMethodHS256, claims).SignedString([]byte(secret))
}

func DecodeOAuthState(state, secret string) (string, error) {
	parsed, err := jwt.Parse(state, func(t *jwt.Token) (any, error) {
		return []byte(secret), nil
	}, jwt.WithIssuer("voidswitch"), jwt.WithValidMethods([]string{"HS256"}))
	if err != nil {
		return "", err
	}
	claims, ok := parsed.Claims.(jwt.MapClaims)
	if !ok || claims["typ"] != oauthStateType {
		return "", errors.New("not an OAuth state token")
	}
	v, _ := claims["vfr"].(string)
	if v == "" {
		return "", errors.New("OAuth state missing PKCE verifier")
	}
	return v, nil
}

// ---- roles ----------------------------------------------------------------

func RoleRank(r string) int {
	switch r {
	case string(constants.RoleOwner), string(constants.RoleCoOwner):
		return 3
	case string(constants.RoleAdmin):
		return 2
	case string(constants.RoleMember):
		return 1
	default:
		return 0
	}
}

func IsOwner(role string) bool {
	return role == string(constants.RoleOwner) || role == string(constants.RoleCoOwner)
}

func IsStaff(role string) bool {
	return IsOwner(role) || role == string(constants.RoleAdmin)
}

// ActorDisplayName returns a human label for audit rows.
func ActorDisplayName(username, name, email *string) *string {
	for _, p := range []*string{username, name, email} {
		if p != nil && strings.TrimSpace(*p) != "" {
			return p
		}
	}
	return nil
}
