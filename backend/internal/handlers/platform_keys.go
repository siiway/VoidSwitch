package handlers

import (
	"net/http"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/gin-gonic/gin"

	"github.com/siiway/voidswitch/internal/core"
	"github.com/siiway/voidswitch/internal/database"
)

const platformKeyPrefix = "vsapi-"

// platformKeyView is the dashboard/API projection of a platform API key. The
// secret is never part of it: it exists only in the create/rotate response.
type platformKeyView struct {
	ID             int        `json:"id"`
	UserID         int        `json:"user_id"`
	UserName       *string    `json:"user_name"`
	UserNickname   *string    `json:"user_nickname"`
	Name           string     `json:"name"`
	KeyPrefix      string     `json:"key_prefix"`
	Scopes         []string   `json:"scopes"`
	Enabled        bool       `json:"enabled"`
	DisabledReason *string    `json:"disabled_reason"`
	ExpiresAt      *time.Time `json:"expires_at"`
	LastUsedAt     *time.Time `json:"last_used_at"`
	CreatedAt      time.Time  `json:"created_at"`
}

func toPlatformKeyView(k *database.PlatformAPIKey) platformKeyView {
	var scopes []string
	database.DecodeJSON(k.Scopes, &scopes)
	if scopes == nil {
		scopes = []string{}
	}
	return platformKeyView{
		ID: k.ID, UserID: k.UserID, Name: k.Name, KeyPrefix: k.KeyPrefix,
		Scopes: scopes, Enabled: k.Enabled, DisabledReason: k.DisabledReason,
		ExpiresAt: k.ExpiresAt, LastUsedAt: k.LastUsedAt, CreatedAt: k.CreatedAt,
	}
}

// normaliseScopes trims, de-duplicates and validates a requested scope list
// against what the calling session may grant. Unknown or over-broad entries are
// rejected rather than silently dropped, so a client never believes it got a
// scope it did not.
func normaliseScopes(raw []string, role string) ([]string, string) {
	seen := map[string]bool{}
	out := make([]string, 0, len(raw))
	for _, s := range raw {
		s = strings.TrimSpace(s)
		if s == "" {
			continue
		}
		if !scopeGrantableForRole(role, s) {
			return nil, "Scope not permitted for your role: " + s
		}
		if seen[s] {
			continue
		}
		seen[s] = true
		out = append(out, s)
	}
	sort.Strings(out)
	return out, ""
}

// scopeGrantableForRole accepts the wildcard families a role may write plus any
// concrete action they already cover.
func scopeGrantableForRole(role, scope string) bool {
	for _, g := range core.GrantableScopes(role) {
		if g == scope {
			return true
		}
	}
	// Per-provider entries: "provider-key:<slug>.*" / "provider-key:<slug>.<verb>".
	if strings.HasPrefix(scope, core.ProviderScope+":") {
		if !core.IsOwner(role) {
			return false
		}
		rest := strings.TrimPrefix(scope, core.ProviderScope+":")
		slug, verb, ok := strings.Cut(rest, ".")
		if !ok || slug == "" || verb == "" {
			return false
		}
		return true
	}
	// A concrete action inside a granted category ("model.edit" under "model.*").
	action, ok := core.ActionByName(scope)
	if !ok {
		return false
	}
	if action.Tier == core.TierProviderKey {
		return core.IsOwner(role)
	}
	category, _, _ := strings.Cut(scope, ".")
	for _, g := range core.GrantableScopes(role) {
		if g == core.ScopeAll || g == core.ScopeRead && action.Tier == core.TierRead || g == category+".*" {
			return true
		}
	}
	return false
}

func (a *App) mePlatformKeys(c *gin.Context) {
	uv := core.GetUser(c)
	var rows []database.PlatformAPIKey
	if err := a.GDB.Where("user_id = ?", uv.User.ID).Order("id").Find(&rows).Error; err != nil {
		a.internal(c, err)
		return
	}
	out := make([]platformKeyView, 0, len(rows))
	for i := range rows {
		v := toPlatformKeyView(&rows[i])
		v.UserName = uv.User.Username
		v.UserNickname = uv.User.Name
		out = append(out, v)
	}
	c.JSON(http.StatusOK, out)
}

func (a *App) mePlatformKeyCreate(c *gin.Context) {
	uv := core.GetUser(c)
	if !uv.IsStaff() {
		a.fail(c, http.StatusForbidden, "Platform API keys require staff privileges.")
		return
	}
	var in struct {
		Name      *string    `json:"name"`
		Scopes    []string   `json:"scopes"`
		ExpiresAt *time.Time `json:"expires_at"`
	}
	if err := c.ShouldBindJSON(&in); err != nil {
		a.fail(c, http.StatusUnprocessableEntity, "invalid payload.")
		return
	}
	scopes, msg := normaliseScopes(in.Scopes, uv.Role)
	if msg != "" {
		a.fail(c, http.StatusUnprocessableEntity, msg)
		return
	}
	if len(scopes) == 0 {
		a.fail(c, http.StatusUnprocessableEntity, "at least one scope is required.")
		return
	}
	raw, err := core.GenerateToken(platformKeyPrefix)
	if err != nil {
		a.internal(c, err)
		return
	}
	name := "default"
	if in.Name != nil && strings.TrimSpace(*in.Name) != "" {
		name = strings.TrimSpace(*in.Name)
	}
	now := time.Now().UTC()
	row := database.PlatformAPIKey{
		UserID: uv.User.ID, Name: name, KeyHash: core.HashToken(raw),
		KeyPrefix: core.PlatformKeyFingerprint(raw), Scopes: database.JSONOf(scopes),
		Enabled: true, ScopesGrantedAt: &now, ExpiresAt: in.ExpiresAt,
	}
	if err := a.GDB.Create(&row).Error; err != nil {
		a.internal(c, err)
		return
	}
	sub, actor := uv.User.Sub, servicesName(uv)
	tid := strconv.Itoa(row.ID)
	_ = a.audit(c, core.AuditInput{
		Action: "platform_key.create", ActorSub: &sub, ActorName: actor,
		Scope: core.AuditScopeSelf, TargetType: strPtr("platform_api_key"), TargetID: &tid,
		Detail: map[string]any{"name": row.Name, "scopes": scopes, "prefix": row.KeyPrefix},
		IP:     strPtr(clientIP(c)),
	})
	c.JSON(http.StatusCreated, gin.H{
		"id": row.ID, "user_id": row.UserID, "name": row.Name, "key_prefix": row.KeyPrefix,
		"scopes": scopes, "enabled": row.Enabled, "expires_at": row.ExpiresAt,
		"created_at": row.CreatedAt, "key": raw,
	})
}

func (a *App) mePlatformKeyUpdate(c *gin.Context) {
	uv := core.GetUser(c)
	id, _ := strconv.Atoi(c.Param("id"))
	var row database.PlatformAPIKey
	if err := a.GDB.Where("id = ?", id).First(&row).Error; err != nil {
		a.fail(c, http.StatusNotFound, "API key not found.")
		return
	}
	var in struct {
		Name      *string    `json:"name"`
		Enabled   *bool      `json:"enabled"`
		Scopes    *[]string  `json:"scopes"`
		ExpiresAt *time.Time `json:"expires_at"`
	}
	if err := c.ShouldBindJSON(&in); err != nil {
		a.fail(c, http.StatusUnprocessableEntity, "invalid payload.")
		return
	}
	if in.Name != nil && strings.TrimSpace(*in.Name) != "" {
		row.Name = strings.TrimSpace(*in.Name)
	}
	if in.Enabled != nil {
		row.Enabled = *in.Enabled
		if *in.Enabled {
			row.DisabledReason = nil
		}
	}
	if in.Scopes != nil {
		scopes, msg := normaliseScopes(*in.Scopes, uv.Role)
		if msg != "" {
			a.fail(c, http.StatusUnprocessableEntity, msg)
			return
		}
		if len(scopes) == 0 {
			a.fail(c, http.StatusUnprocessableEntity, "at least one scope is required.")
			return
		}
		row.Scopes = database.JSONOf(scopes)
	}
	if in.ExpiresAt != nil {
		row.ExpiresAt = in.ExpiresAt
	}
	if err := a.GDB.Save(&row).Error; err != nil {
		a.internal(c, err)
		return
	}
	sub, actor := uv.User.Sub, servicesName(uv)
	tid := strconv.Itoa(row.ID)
	detail := map[string]any{}
	if in.Name != nil {
		detail["name"] = row.Name
	}
	if in.Enabled != nil {
		detail["enabled"] = row.Enabled
	}
	if in.Scopes != nil {
		detail["scopes"] = row.Scopes
	}
	_ = a.audit(c, core.AuditInput{
		Action: "platform_key.update", ActorSub: &sub, ActorName: actor,
		Scope: core.AuditScopeSelf, TargetType: strPtr("platform_api_key"), TargetID: &tid,
		Detail: detail, IP: strPtr(clientIP(c)),
	})
	c.JSON(http.StatusOK, toPlatformKeyView(&row))
}

func (a *App) mePlatformKeyDelete(c *gin.Context) {
	uv := core.GetUser(c)
	id, _ := strconv.Atoi(c.Param("id"))
	res := a.GDB.Where("id = ? AND user_id = ?", id, uv.User.ID).
		Delete(&database.PlatformAPIKey{})
	if res.Error != nil {
		a.internal(c, res.Error)
		return
	}
	if res.RowsAffected == 0 {
		a.fail(c, http.StatusNotFound, "API key not found.")
		return
	}
	sub, actor := uv.User.Sub, servicesName(uv)
	tid := strconv.Itoa(id)
	_ = a.audit(c, core.AuditInput{
		Action: "platform_key.delete", ActorSub: &sub, ActorName: actor,
		Scope: core.AuditScopeSelf, TargetType: strPtr("platform_api_key"), TargetID: &tid,
		IP: strPtr(clientIP(c)),
	})
	c.Status(http.StatusNoContent)
}

// mePlatformKeyRotate mints a fresh secret for an existing key, keeping its
// scopes and settings. The old secret stops working immediately.
func (a *App) mePlatformKeyRotate(c *gin.Context) {
	uv := core.GetUser(c)
	id, _ := strconv.Atoi(c.Param("id"))
	var row database.PlatformAPIKey
	if err := a.GDB.Where("id = ? AND user_id = ?", id, uv.User.ID).First(&row).Error; err != nil {
		a.fail(c, http.StatusNotFound, "API key not found.")
		return
	}
	raw, err := core.GenerateToken(platformKeyPrefix)
	if err != nil {
		a.internal(c, err)
		return
	}
	now := time.Now().UTC()
	row.KeyHash = core.HashToken(raw)
	row.KeyPrefix = core.PlatformKeyFingerprint(raw)
	row.ScopesGrantedAt = &now
	if err := a.GDB.Save(&row).Error; err != nil {
		a.internal(c, err)
		return
	}
	sub, actor := uv.User.Sub, servicesName(uv)
	tid := strconv.Itoa(row.ID)
	_ = a.audit(c, core.AuditInput{
		Action: "platform_key.rotate", ActorSub: &sub, ActorName: actor,
		Scope: core.AuditScopeSelf, TargetType: strPtr("platform_api_key"), TargetID: &tid,
		Detail: map[string]any{"prefix": row.KeyPrefix}, IP: strPtr(clientIP(c)),
	})
	var scopes []string
	database.DecodeJSON(row.Scopes, &scopes)
	c.JSON(http.StatusOK, gin.H{
		"id": row.ID, "user_id": row.UserID, "name": row.Name, "key_prefix": row.KeyPrefix,
		"scopes": scopes, "enabled": row.Enabled, "expires_at": row.ExpiresAt,
		"created_at": row.CreatedAt, "key": raw,
	})
}

// mePlatformKeyScopes reports the scope catalogue, marking which entries the
// caller may grant. The dashboard renders only the grantable ones.
func (a *App) mePlatformKeyScopes(c *gin.Context) {
	uv := core.GetUser(c)
	grantable := core.GrantableScopes(uv.Role)
	allowed := make(map[string]bool, len(grantable))
	for _, g := range grantable {
		allowed[g] = true
	}
	actions := core.Actions()
	out := make([]gin.H, 0, len(actions)+len(grantable))
	for _, g := range grantable {
		out = append(out, gin.H{"scope": g, "summary": wildcardScopeSummary(g), "grantable": true})
	}
	for _, act := range actions {
		grantable := allowed[act.Name] || allowed[act.Category+".*"] ||
			(act.Tier == core.TierRead && allowed[core.ScopeRead])
		out = append(out, gin.H{
			"scope": act.Name, "summary": act.Summary,
			"category": act.Category, "grantable": grantable,
		})
	}
	var providers []database.Provider
	a.GDB.Select("slug", "name").Order("slug").Find(&providers)
	c.JSON(http.StatusOK, gin.H{
		"scopes": out, "role": uv.Role,
		"can_manage_provider_keys": core.IsOwner(uv.Role),
		"providers":                providers,
	})
}

func wildcardScopeSummary(scope string) string {
	switch scope {
	case core.ScopeAll:
		return "Every action this key's owner may perform."
	case core.ScopeRead:
		return "Every read-only action."
	case core.ProviderScope + ":*.*":
		return "Manage any provider's upstream keys."
	case core.ProviderScope + ".*":
		return "Manage the upstream keys of the providers listed below."
	}
	if category, ok := strings.CutSuffix(scope, ".*"); ok {
		return "Every " + category + " action."
	}
	return ""
}

// RegisterMePlatformKeyRoutes wires /api/me/api-keys.
func RegisterMePlatformKeyRoutes(r *gin.RouterGroup, a *App) {
	g := r.Group("/api-keys", core.RequireUser(), core.RequireStaff())
	g.GET("", a.mePlatformKeys)
	g.GET("/scopes", a.mePlatformKeyScopes)
	g.POST("", a.mePlatformKeyCreate)
	g.PATCH("/:id", a.mePlatformKeyUpdate)
	g.DELETE("/:id", a.mePlatformKeyDelete)
	g.POST("/:id/rotate", a.mePlatformKeyRotate)
}
