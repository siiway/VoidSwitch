package core

import (
	"crypto/rand"
	"crypto/rsa"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"math/big"
	"net/http"
	"net/url"
	"strings"
	"sync"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/golang-jwt/jwt/v5"
	"gorm.io/gorm"

	"github.com/siiway/voidswitch/internal/config"
	"github.com/siiway/voidswitch/internal/constants"
	"github.com/siiway/voidswitch/internal/database"
)

var OwnerRolesSet = map[string]bool{
	string(constants.RoleOwner):   true,
	string(constants.RoleCoOwner): true,
}

var StaffRolesSet = map[string]bool{
	string(constants.RoleOwner):   true,
	string(constants.RoleCoOwner): true,
	string(constants.RoleAdmin):   true,
}

var roleRank = map[string]int{
	string(constants.RoleMember):  1,
	string(constants.RoleAdmin):   2,
	string(constants.RoleCoOwner): 3,
	string(constants.RoleOwner):   3,
}

type PrismIdentity struct {
	Sub       string
	Username  *string
	Email     *string
	Name      *string
	Picture   *string
	PrismRole *string
}

type AuthedToken struct {
	Token *database.VoidToken
	User  *database.User
}

type pendingLogin struct {
	verifier string
	created  time.Time
}

type stateStore struct {
	store map[string]pendingLogin
	ttl   time.Duration
	mu    sync.Mutex
}

func NewStateStore(ttl time.Duration) *stateStore {
	return &stateStore{
		store: make(map[string]pendingLogin),
		ttl:   ttl,
	}
}

func (s *stateStore) Put(state, verifier string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.gc()
	s.store[state] = pendingLogin{verifier: verifier, created: time.Now()}
}

func (s *stateStore) Pop(state string) (string, bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.gc()
	entry, ok := s.store[state]
	if !ok {
		return "", false
	}
	delete(s.store, state)
	return entry.verifier, true
}

func (s *stateStore) gc() {
	cutoff := time.Now().Add(-s.ttl)
	for k, v := range s.store {
		if v.created.Before(cutoff) {
			delete(s.store, k)
		}
	}
}

var loginStateStore = NewStateStore(30 * time.Minute)

func pkcePair() (string, string) {
	b := make([]byte, 32)
	if _, err := rand.Read(b); err != nil {
		panic(fmt.Sprintf("auth: failed to generate PKCE bytes: %v", err))
	}
	verifier := base64.RawURLEncoding.EncodeToString(b)

	hash := sha256.Sum256([]byte(verifier))
	challenge := base64.RawURLEncoding.EncodeToString(hash[:])

	return verifier, challenge
}

func generateState() (string, error) {
	b := make([]byte, 24)
	if _, err := rand.Read(b); err != nil {
		return "", err
	}
	return base64.RawURLEncoding.EncodeToString(b), nil
}

func BuildAuthorizeURL(settings *config.Settings) (string, string) {
	verifier, challenge := pkcePair()
	state, err := generateState()
	if err != nil {
		panic(fmt.Sprintf("auth: failed to generate state: %v", err))
	}

	loginStateStore.Put(state, verifier)

	params := url.Values{}
	params.Set("response_type", "code")
	params.Set("client_id", settings.Prism.ClientID)
	params.Set("redirect_uri", settings.Prism.RedirectURI)
	params.Set("scope", strings.Join(settings.Prism.Scopes, " "))
	params.Set("state", state)
	params.Set("code_challenge", challenge)
	params.Set("code_challenge_method", "S256")

	return fmt.Sprintf("%s?%s", settings.Prism.AuthorizeURL(), params.Encode()), state
}

func ExchangeCode(settings *config.Settings, code, state string) (*PrismIdentity, error) {
	verifier, ok := loginStateStore.Pop(state)
	if !ok {
		return nil, fmt.Errorf("unknown or expired login state")
	}

	data := url.Values{}
	data.Set("grant_type", "authorization_code")
	data.Set("code", code)
	data.Set("redirect_uri", settings.Prism.RedirectURI)
	data.Set("client_id", settings.Prism.ClientID)
	data.Set("code_verifier", verifier)
	if settings.Prism.ClientSecret != "" {
		data.Set("client_secret", settings.Prism.ClientSecret)
	}

	httpClient := &http.Client{
		Timeout: 30 * time.Second,
	}

	req, err := http.NewRequest("POST", settings.Prism.TokenURL(), strings.NewReader(data.Encode()))
	if err != nil {
		return nil, fmt.Errorf("token request: %w", err)
	}
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")

	resp, err := httpClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("token exchange: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != 200 {
		body, _ := io.ReadAll(io.LimitReader(resp.Body, 300))
		return nil, fmt.Errorf("token exchange failed (status %d): %s", resp.StatusCode, string(body))
	}

	var tokens map[string]any
	if err := json.NewDecoder(resp.Body).Decode(&tokens); err != nil {
		return nil, fmt.Errorf("decode token response: %w", err)
	}

	idToken, _ := tokens["id_token"].(string)
	accessToken, _ := tokens["access_token"].(string)

	claims := decodeIDToken(settings, idToken)
	identity := fetchUserinfo(settings, accessToken, claims)

	return identity, nil
}

func decodeIDToken(settings *config.Settings, idToken string) map[string]any {
	if idToken == "" {
		return map[string]any{}
	}

	claims, err := verifyIDToken(settings, idToken)
	if err == nil {
		return claims
	}

	parser := jwt.NewParser()
	token, _, err := parser.ParseUnverified(idToken, jwt.MapClaims{})
	if err != nil {
		return map[string]any{}
	}
	if claims, ok := token.Claims.(jwt.MapClaims); ok {
		result := make(map[string]any, len(claims))
		for k, v := range claims {
			result[k] = v
		}
		return result
	}
	return map[string]any{}
}

type jwksResponse struct {
	Keys []jwkKey `json:"keys"`
}

type jwkKey struct {
	Kty string `json:"kty"`
	Kid string `json:"kid"`
	Alg string `json:"alg"`
	N   string `json:"n"`
	E   string `json:"e"`
}

func verifyIDToken(settings *config.Settings, idToken string) (map[string]any, error) {
	parsed, _ := jwt.Parse(idToken, nil)
	if parsed == nil {
		return nil, fmt.Errorf("cannot parse id_token header")
	}

	kid, _ := parsed.Header["kid"].(string)

	httpClient := &http.Client{Timeout: 15 * time.Second}
	resp, err := httpClient.Get(settings.Prism.JwksURL())
	if err != nil {
		return nil, fmt.Errorf("jwks fetch: %w", err)
	}
	defer resp.Body.Close()

	var jwks jwksResponse
	if err := json.NewDecoder(resp.Body).Decode(&jwks); err != nil {
		return nil, fmt.Errorf("jwks decode: %w", err)
	}

	var pubKey *rsa.PublicKey
	for _, key := range jwks.Keys {
		if key.Kty != "RSA" {
			continue
		}
		if kid != "" && key.Kid != kid {
			continue
		}

		nBytes, err := base64.RawURLEncoding.DecodeString(key.N)
		if err != nil {
			continue
		}
		eBytes, err := base64.RawURLEncoding.DecodeString(key.E)
		if err != nil {
			continue
		}

		n := new(big.Int).SetBytes(nBytes)
		e := int(new(big.Int).SetBytes(eBytes).Int64())

		pubKey = &rsa.PublicKey{N: n, E: e}
		break
	}

	if pubKey == nil {
		return nil, fmt.Errorf("no matching JWK found")
	}

	parsedToken, err := jwt.Parse(idToken, func(token *jwt.Token) (interface{}, error) {
		if _, ok := token.Method.(*jwt.SigningMethodRSA); !ok {
			return nil, fmt.Errorf("unexpected signing method: %v", token.Header["alg"])
		}
		return pubKey, nil
	}, jwt.WithAudience(settings.Prism.ClientID))

	if err != nil {
		return nil, err
	}

	if claims, ok := parsedToken.Claims.(jwt.MapClaims); ok {
		result := make(map[string]any, len(claims))
		for k, v := range claims {
			result[k] = v
		}
		return result, nil
	}

	return nil, fmt.Errorf("unexpected claims type")
}

func fetchUserinfo(settings *config.Settings, accessToken string, claims map[string]any) *PrismIdentity {
	info := map[string]any{}

	if accessToken != "" {
		httpClient := &http.Client{Timeout: 30 * time.Second}
		req, err := http.NewRequest("GET", settings.Prism.UserinfoURL(), nil)
		if err == nil {
			req.Header.Set("Authorization", "Bearer "+accessToken)
			resp, err := httpClient.Do(req)
			if err == nil {
				defer resp.Body.Close()
				if resp.StatusCode == 200 {
					json.NewDecoder(resp.Body).Decode(&info)
				}
			}
		}
	}

	merged := make(map[string]any, len(claims)+len(info))
	for k, v := range claims {
		merged[k] = v
	}
	for k, v := range info {
		merged[k] = v
	}

	sub := ""
	if s, ok := merged["sub"]; ok {
		sub = fmt.Sprintf("%v", s)
	}
	if sub == "" {
		return &PrismIdentity{Sub: ""}
	}

	return &PrismIdentity{
		Sub:       sub,
		Username:  stringPtr(merged["preferred_username"]),
		Email:     stringPtr(merged["email"]),
		Name:      stringPtr(merged["name"]),
		Picture:   stringPtr(merged["picture"]),
		PrismRole: stringPtr(merged["role"]),
	}
}

func stringPtr(v any) *string {
	if v == nil {
		return nil
	}
	s := fmt.Sprintf("%v", v)
	if s == "" || s == "<nil>" {
		return nil
	}
	return &s
}

var prismRoleMap = map[string]string{
	"owner":   string(constants.RoleOwner),
	"coowner": string(constants.RoleCoOwner),
	"admin":   string(constants.RoleAdmin),
}

func normalisePrismRole(value string) (string, bool) {
	if value == "" {
		return "", false
	}
	key := strings.ToLower(strings.TrimSpace(value))
	key = strings.NewReplacer("-", "", "_", "", " ", "").Replace(key)
	role, ok := prismRoleMap[key]
	return role, ok
}

func resolveRole(settings *config.Settings, identity *PrismIdentity, isFirstUser bool) string {
	admin := settings.Admin

	for _, s := range admin.OwnerSubs {
		if identity.Sub == s {
			return string(constants.RoleOwner)
		}
	}
	if identity.Email != nil {
		for _, e := range admin.OwnerEmails {
			if *identity.Email == e {
				return string(constants.RoleOwner)
			}
		}
	}

	prismRole := ""
	if identity.PrismRole != nil {
		prismRole = *identity.PrismRole
	}
	normalised, ok := normalisePrismRole(prismRole)
	if ok {
		if normalised == string(constants.RoleOwner) || normalised == string(constants.RoleCoOwner) {
			return normalised
		}
		if normalised == string(constants.RoleAdmin) && admin.TrustPrismAdmin {
			return string(constants.RoleAdmin)
		}
	}

	if isFirstUser && admin.BootstrapFirstUser {
		return string(constants.RoleOwner)
	}

	return string(constants.RoleMember)
}

func mergeRole(existing, resolved string) string {
	if resolved == string(constants.RoleOwner) || resolved == string(constants.RoleCoOwner) {
		return resolved
	}
	if roleRank[existing] >= roleRank[resolved] {
		return existing
	}
	return resolved
}

func isOwner(user *database.User) bool {
	return OwnerRolesSet[user.Role]
}

func isStaff(user *database.User) bool {
	return StaffRolesSet[user.Role]
}

func UpsertUser(db *gorm.DB, settings *config.Settings, identity *PrismIdentity) (*database.User, error) {
	var existing *database.User
	if err := db.Where("sub = ?", identity.Sub).First(&existing).Error; err != nil {
		existing = nil
	}

	var totalUsers int64
	db.Model(&database.User{}).Count(&totalUsers)
	isFirstUser := totalUsers == 0 && existing == nil

	role := resolveRole(settings, identity, isFirstUser)

	if existing == nil {
		now := time.Now()
		user := &database.User{
			Sub:         identity.Sub,
			Username:    identity.Username,
			Email:       identity.Email,
			Name:        identity.Name,
			Picture:     identity.Picture,
			Role:        role,
			PrismRole:   identity.PrismRole,
			LastLoginAt: &now,
			Enabled:     true,
		}
		if err := db.Create(user).Error; err != nil {
			return nil, fmt.Errorf("create user: %w", err)
		}
		return user, nil
	}

	if identity.Username != nil {
		existing.Username = identity.Username
	}
	if identity.Email != nil {
		existing.Email = identity.Email
	}
	if identity.Name != nil {
		existing.Name = identity.Name
	}
	if identity.Picture != nil {
		existing.Picture = identity.Picture
	}
	existing.PrismRole = identity.PrismRole
	now := time.Now()
	existing.LastLoginAt = &now
	existing.Role = mergeRole(existing.Role, role)

	if err := db.Save(existing).Error; err != nil {
		return nil, fmt.Errorf("update user: %w", err)
	}

	return existing, nil
}

const devUserSub = "dev-mode-user"

func DevLoginUser(db *gorm.DB, settings *config.Settings) (*database.User, error) {
	if !settings.Server.DevMode {
		return nil, fmt.Errorf("dev mode is not enabled")
	}

	var user database.User
	if err := db.Where("sub = ?", devUserSub).First(&user).Error; err != nil {
		now := time.Now()
		username := "dev"
		email := "dev@voidswitch.local"
		name := "Developer (dev mode)"
		role := string(constants.RoleOwner)

		user = database.User{
			Sub:         devUserSub,
			Username:    &username,
			Email:       &email,
			Name:        &name,
			Role:        role,
			LastLoginAt: &now,
			Enabled:     true,
		}
		if err := db.Create(&user).Error; err != nil {
			return nil, fmt.Errorf("create dev user: %w", err)
		}
		return &user, nil
	}

	user.Role = string(constants.RoleOwner)
	user.Enabled = true
	now := time.Now()
	user.LastLoginAt = &now

	if err := db.Save(&user).Error; err != nil {
		return nil, fmt.Errorf("update dev user: %w", err)
	}

	return &user, nil
}

const currentUserKey = "currentUser"

func GetCurrentUser(db *gorm.DB, settings *config.Settings) gin.HandlerFunc {
	return func(c *gin.Context) {
		auth := c.GetHeader("Authorization")
		token := ExtractBearer(auth)
		if token == "" {
			c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"error": "Missing bearer token."})
			return
		}

		claims, err := DecodeSessionToken(token, settings.Server.SecretKey)
		if err != nil {
			c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"error": "Invalid session token."})
			return
		}

		sub := ""
		if s, ok := claims["sub"]; ok {
			sub = fmt.Sprintf("%v", s)
		}

		var user database.User
		if err := db.Where("sub = ? AND enabled = ?", sub, true).First(&user).Error; err != nil {
			c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"error": "User not found or disabled."})
			return
		}

		c.Set(currentUserKey, &user)
		c.Next()
	}
}

func RequireStaff() gin.HandlerFunc {
	return func(c *gin.Context) {
		user, _ := c.Get(currentUserKey)
		u, ok := user.(*database.User)
		if !ok || !StaffRolesSet[u.Role] {
			c.AbortWithStatusJSON(http.StatusForbidden, gin.H{"error": "Admin privileges required."})
			return
		}
		c.Next()
	}
}

func RequireOwner() gin.HandlerFunc {
	return func(c *gin.Context) {
		user, _ := c.Get(currentUserKey)
		u, ok := user.(*database.User)
		if !ok || !OwnerRolesSet[u.Role] {
			c.AbortWithStatusJSON(http.StatusForbidden, gin.H{"error": "Owner privileges required."})
			return
		}
		c.Next()
	}
}

func GetUserFromContext(c *gin.Context) *database.User {
	user, exists := c.Get(currentUserKey)
	if !exists {
		return nil
	}
	u, ok := user.(*database.User)
	if !ok {
		return nil
	}
	return u
}

func ExtractBearer(authorization string) string {
	if authorization == "" {
		return ""
	}
	parts := strings.SplitN(authorization, " ", 2)
	if len(parts) == 2 && strings.EqualFold(parts[0], "bearer") {
		return strings.TrimSpace(parts[1])
	}
	return strings.TrimSpace(authorization)
}

func AuthenticateVoidToken(db *gorm.DB, authorization string, xApiKey string) (*AuthedToken, error) {
	raw := ExtractBearer(authorization)
	if raw == "" {
		raw = strings.TrimSpace(xApiKey)
	}
	if raw == "" {
		return nil, fmt.Errorf("missing API key")
	}

	hash := HashToken(raw)

	var token database.VoidToken
	if err := db.Where("token_hash = ? AND enabled = ?", hash, true).First(&token).Error; err != nil {
		return nil, fmt.Errorf("invalid API key")
	}

	if token.ExpiresAt != nil && token.ExpiresAt.Before(time.Now()) {
		return nil, fmt.Errorf("API key expired")
	}

	var user database.User
	if err := db.Where("id = ? AND enabled = ?", token.UserID, true).First(&user).Error; err != nil {
		return nil, fmt.Errorf("token owner disabled")
	}

	return &AuthedToken{Token: &token, User: &user}, nil
}

func IsStaff(user *database.User) bool {
	return StaffRolesSet[user.Role]
}

func RoleRank(role string) int {
	return roleRank[role]
}

func ActorDisplayName(user *database.User) string {
	label := ""
	if user.Username != nil {
		label = *user.Username
	} else if user.Name != nil {
		label = *user.Name
	} else if user.Email != nil {
		label = *user.Email
	} else {
		label = user.Sub
	}
	return fmt.Sprintf("%s#%d", label, user.ID)
}
