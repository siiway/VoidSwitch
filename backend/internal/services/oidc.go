package services

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"

	"gorm.io/gorm"

	"github.com/siiway/voidswitch/internal/config"
	"github.com/siiway/voidswitch/internal/constants"
	"github.com/siiway/voidswitch/internal/core"
	"github.com/siiway/voidswitch/internal/database"
)

// ErrLoginDenied means the authenticated identity has no platform access.
var ErrLoginDenied = errors.New("no platform access: not a moderator and no role group applies")

// PrismIdentity is the normalized identity from Prism OAuth.
type PrismIdentity struct {
	Sub              string
	Username         *string
	Email            *string
	Name             *string
	Picture          *string
	Teams            []map[string]any
	ExpiresInSeconds int
}

// BuildAuthorizeURL returns the OAuth authorize URL with a signed PKCE state.
func BuildAuthorizeURL(cfg *config.Settings) (string, string, error) {
	verifier, challenge := pkcePair()
	state, err := core.CreateOAuthState(cfg.Server.SecretKey, verifier, 30)
	if err != nil {
		return "", "", err
	}
	q := url.Values{}
	q.Set("response_type", "code")
	q.Set("client_id", cfg.Prism.ClientID)
	q.Set("redirect_uri", cfg.Prism.RedirectURI)
	q.Set("scope", strings.Join(cfg.Prism.Scopes, " "))
	q.Set("state", state)
	q.Set("code_challenge", challenge)
	q.Set("code_challenge_method", "S256")
	return cfg.Prism.AuthorizeURL() + "?" + q.Encode(), state, nil
}

// oauthHTTPClient returns a client with a sane timeout (system egress).
func oauthHTTPClient() *http.Client {
	return &http.Client{Timeout: 30 * time.Second}
}

// ExchangeCode exchanges an authorization code (using the PKCE verifier from the
// signed state) and loads the user's identity + team memberships.
func ExchangeCode(ctx context.Context, cfg *config.Settings, code, state string) (*PrismIdentity, error) {
	verifier, err := core.DecodeOAuthState(state, cfg.Server.SecretKey)
	if err != nil {
		return nil, fmt.Errorf("unknown or expired login state: %w", err)
	}

	form := url.Values{}
	form.Set("grant_type", "authorization_code")
	form.Set("code", code)
	form.Set("redirect_uri", cfg.Prism.RedirectURI)
	form.Set("client_id", cfg.Prism.ClientID)
	form.Set("code_verifier", verifier)
	if cfg.Prism.ClientSecret != "" {
		form.Set("client_secret", cfg.Prism.ClientSecret)
	}

	client := oauthHTTPClient()
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, cfg.Prism.TokenURL(), strings.NewReader(form.Encode()))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	resp, err := client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("oauth token exchange failed: %d", resp.StatusCode)
	}
	var tokens struct {
		AccessToken string `json:"access_token"`
		IDToken     string `json:"id_token"`
		ExpiresIn   int    `json:"expires_in"`
	}
	if err := json.Unmarshal(body, &tokens); err != nil {
		return nil, err
	}

	info := map[string]any{}
	if tokens.AccessToken != "" {
		uReq, _ := http.NewRequestWithContext(ctx, http.MethodGet, cfg.Prism.UserinfoURL(), nil)
		uReq.Header.Set("Authorization", "Bearer "+tokens.AccessToken)
		if uResp, err := client.Do(uReq); err == nil {
			ub, _ := io.ReadAll(io.LimitReader(uResp.Body, 1<<20))
			uResp.Body.Close()
			if uResp.StatusCode == http.StatusOK {
				_ = json.Unmarshal(ub, &info)
			}
		}
	}

	sub, _ := info["sub"].(string)
	if sub == "" {
		return nil, errors.New("oauth identity missing subject")
	}
	ident := &PrismIdentity{
		Sub:              sub,
		Username:         strField(info, "preferred_username"),
		Email:            strField(info, "email"),
		Name:             strField(info, "name"),
		Picture:          strField(info, "picture"),
		ExpiresInSeconds: tokens.ExpiresIn,
	}
	ident.Teams = fetchTeams(ctx, cfg, tokens.AccessToken)
	return ident, nil
}

func strField(m map[string]any, key string) *string {
	if v, ok := m[key].(string); ok && v != "" {
		return &v
	}
	return nil
}

func fetchTeams(ctx context.Context, cfg *config.Settings, accessToken string) []map[string]any {
	if accessToken == "" {
		return nil
	}
	u := strings.TrimRight(cfg.Prism.Issuer, "/") + "/api/oauth/me/teams"
	req, _ := http.NewRequestWithContext(ctx, http.MethodGet, u, nil)
	req.Header.Set("Authorization", "Bearer "+accessToken)
	resp, err := oauthHTTPClient().Do(req)
	if err != nil {
		return nil
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil
	}
	var data any
	if err := json.NewDecoder(resp.Body).Decode(&data); err != nil {
		return nil
	}
	var list []any
	switch v := data.(type) {
	case []any:
		list = v
	case map[string]any:
		for _, key := range []string{"teams", "data", "items"} {
			if arr, ok := v[key].([]any); ok {
				list = arr
				break
			}
		}
	}
	var out []map[string]any
	for _, item := range list {
		if m, ok := item.(map[string]any); ok {
			out = append(out, m)
		}
	}
	return out
}

// UpsertUser resolves the platform role + role groups and persists the user.
// Returns ErrLoginDenied when the identity has no platform access.
func UpsertUser(db *gorm.DB, cfg *config.Settings, ident *PrismIdentity) (*database.User, error) {
	var existing database.User
	found := db.Where("sub = ?", ident.Sub).First(&existing).Error == nil

	var total int64
	db.Model(&database.User{}).Count(&total)
	isFirst := total == 0 && !found

	role := resolveRole(cfg, ident, isFirst)
	autoGroups, _ := EvaluateAutoGroupIDs(db, ident.Teams)
	autoAdmins, _ := EvaluateAutoAdminGroupIDs(db, ident.Teams)
	mainTeamRole := effectiveTeamRoleOrNil(ident.Teams, cfg.Admin.MainTeamID)
	teamIDs := teamIDList(ident.Teams)

	privileged := core.IsStaff(role)
	explicit := containsStr(cfg.Admin.OwnerSubs, ident.Sub) ||
		(ident.Email != nil && containsStr(cfg.Admin.OwnerEmails, *ident.Email)) ||
		(isFirst && cfg.Admin.BootstrapFirstUser)
	if !privileged && !explicit && len(autoGroups) == 0 && len(autoAdmins) == 0 {
		return nil, ErrLoginDenied
	}

	now := time.Now().UTC()
	if !found {
		existing = database.User{
			Sub: ident.Sub, Username: ident.Username, Email: ident.Email, Name: ident.Name,
			Picture: ident.Picture, Role: role, PrismRole: mainTeamRole,
			TeamIDs: database.JSONOf(teamIDs), Enabled: true, LastLoginAt: &now,
		}
		if err := db.Create(&existing).Error; err != nil {
			return nil, err
		}
	} else {
		if ident.Username != nil {
			existing.Username = ident.Username
		}
		if ident.Email != nil {
			existing.Email = ident.Email
		}
		if ident.Name != nil {
			existing.Name = ident.Name
		}
		if ident.Picture != nil {
			existing.Picture = ident.Picture
		}
		existing.PrismRole = mainTeamRole
		existing.TeamIDs = database.JSONOf(teamIDs)
		existing.LastLoginAt = &now
		existing.Role = mergeRole(existing.Role, role)
		if err := db.Save(&existing).Error; err != nil {
			return nil, err
		}
	}

	_ = SyncAutoMemberships(db, existing.ID, autoGroups)
	_ = SyncAutoAdminships(db, existing.ID, autoAdmins)
	restoreAutoDisabledTokens(db, &existing)
	return &existing, nil
}

func restoreAutoDisabledTokens(db *gorm.DB, user *database.User) {
	if !user.Enabled || !user.VoidTokensAdminDisabled {
		return
	}
	db.Model(&database.VoidToken{}).
		Where("user_id = ? AND deleted = ? AND auto_disabled = ?", user.ID, false, true).
		Updates(map[string]any{"enabled": true, "auto_disabled": false})
	db.Model(user).Update("void_tokens_admin_disabled", false)
}

func resolveRole(cfg *config.Settings, ident *PrismIdentity, isFirst bool) string {
	if containsStr(cfg.Admin.OwnerSubs, ident.Sub) {
		return string(constants.RoleOwner)
	}
	if ident.Email != nil && containsStr(cfg.Admin.OwnerEmails, *ident.Email) {
		return string(constants.RoleOwner)
	}
	if r := resolveMainTeamRole(cfg.Admin.MainTeamID, ident.Teams); r != "" {
		return r
	}
	if isFirst && cfg.Admin.BootstrapFirstUser {
		return string(constants.RoleOwner)
	}
	return string(constants.RoleMember)
}

func mergeRole(existing, resolved string) string {
	if resolved == string(constants.RoleOwner) || resolved == string(constants.RoleCoOwner) {
		return resolved
	}
	if core.RoleRank(existing) >= core.RoleRank(resolved) {
		return existing
	}
	return resolved
}

func resolveMainTeamRole(mainTeamID string, teams []map[string]any) string {
	if mainTeamID == "" {
		return ""
	}
	role := effectiveTeamRoleOrNil(teams, mainTeamID)
	if role == nil {
		return ""
	}
	switch *role {
	case string(constants.RoleOwner), string(constants.RoleCoOwner), string(constants.RoleAdmin):
		return *role
	default:
		return ""
	}
}

func effectiveTeamRoleOrNil(teams []map[string]any, teamID string) *string {
	if teamID == "" {
		return nil
	}
	best, bestRank := "", 0
	for _, t := range teams {
		id, _ := t["id"].(string)
		if id != teamID {
			continue
		}
		role, _ := t["role"].(string)
		canon := NormaliseTeamRole(role)
		if r := TeamRoleRank(canon); r > bestRank {
			bestRank, best = r, canon
		}
	}
	if best == "" {
		return nil
	}
	return &best
}

func teamIDList(teams []map[string]any) []string {
	out := make([]string, 0, len(teams))
	for _, t := range teams {
		if id, ok := t["id"].(string); ok {
			out = append(out, id)
		}
	}
	return out
}

func containsStr(list []string, v string) bool {
	for _, x := range list {
		if x == v {
			return true
		}
	}
	return false
}
