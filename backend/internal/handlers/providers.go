package handlers

import (
	"encoding/json"
	"fmt"
	"net/http"
	"regexp"
	"strconv"
	"strings"

	"github.com/gin-gonic/gin"
	"gorm.io/gorm"

	"github.com/siiway/voidswitch/internal/core"
	"github.com/siiway/voidswitch/internal/cryptoutil"
	"github.com/siiway/voidswitch/internal/database"
	"github.com/siiway/voidswitch/internal/services"
	"github.com/siiway/voidswitch/internal/services/providers"
)

var validKeySelectModes = map[string]bool{
	"round_robin": true, "random": true, "fallback": true,
	"pinned_round_robin": true, "pinned_random": true,
}

func slugify(name string) string {
	var b strings.Builder
	lastDash := false
	for _, r := range strings.ToLower(name) {
		switch {
		case (r >= 'a' && r <= 'z') || (r >= '0' && r <= '9'):
			b.WriteRune(r)
			lastDash = false
		default:
			if !lastDash && b.Len() > 0 {
				b.WriteByte('-')
				lastDash = true
			}
		}
	}
	s := strings.Trim(b.String(), "-")
	if s == "" {
		s = "provider"
	}
	if len(s) > 64 {
		s = s[:64]
	}
	return s
}

func (a *App) uniqueSlug(base string, excludeID int) string {
	slug := slugify(base)
	candidate := slug
	n := 2
	for {
		var count int64
		q := a.GDB.Model(&database.Provider{}).Where("slug = ?", candidate)
		if excludeID > 0 {
			q = q.Where("id <> ?", excludeID)
		}
		q.Count(&count)
		if count == 0 {
			return candidate
		}
		candidate = fmt.Sprintf("%s-%d", slug, n)
		n++
	}
}

func (a *App) providersList(c *gin.Context) {
	uv := core.GetUser(c)
	var rows []database.Provider
	if err := a.GDB.Order("id").Find(&rows).Error; err != nil {
		a.internal(c, err)
		return
	}
	out := make([]services.ProviderView, 0, len(rows))
	for i := range rows {
		p := &rows[i]
		var keys []database.ApiKey
		a.GDB.Where("provider_id = ?", p.ID).Find(&keys)
		v := services.BuildProviderView(p, keys)
		adapter := providers.GetAdapter(p)
		v.SupportsBalance = adapter.GetBalanceURL() != ""
		v.SupportsImport = adapter.CanImport()
		v.SupportsRefresh = adapter.CanRefresh()
		v.SupportsOAuth = adapter.CanOAuth()
		if !uv.IsOwner() {
			// Redact secret config and hide key-api state from non-owners.
			for k := range v.ExtraHeaders {
				v.ExtraHeaders[k] = "***"
			}
			v.KeyAPIEnabled = false
			v.KeyAPITokenPreview = nil
		}
		out = append(out, v)
	}
	c.JSON(http.StatusOK, out)
}

type providerPayload struct {
	Name                           *string          `json:"name"`
	Slug                           *string          `json:"slug"`
	Type                           *string          `json:"type"`
	BaseURL                        *string          `json:"base_url"`
	Enabled                        *bool            `json:"enabled"`
	Models                         *[]string        `json:"models"`
	BalanceURL                     *string          `json:"balance_url"`
	ExtraHeaders                   *map[string]any  `json:"extra_headers"`
	TimeoutSeconds                 *int             `json:"timeout_seconds"`
	RetryOnZeroToken               *bool            `json:"retry_on_zero_token"`
	DropOpenCodeIdentityBlock      *bool            `json:"drop_opencode_identity_block"`
	NormalizeDeveloperRoleToSystem *bool            `json:"normalize_developer_role_to_system"`
	NodeGroupID                    *int             `json:"node_group_id"`
	KeySelectMode                  *string          `json:"key_select_mode"`
	RateLimitCooldownSeconds       *int             `json:"rate_limit_cooldown_seconds"`
	PassthroughEnabled             *bool            `json:"passthrough_enabled"`
	PassthroughModels              *[]string        `json:"passthrough_models"`
	NewAPIMode                     *string          `json:"new_api_mode"`
	ProtectedErrorRetryEnabled     *bool            `json:"protected_error_retry_enabled"`
	SelectiveIgnoreRules           *json.RawMessage `json:"selective_ignore_rules"`
}

func (a *App) providerCreate(c *gin.Context) {
	uv := core.GetUser(c)
	var in providerPayload
	if err := c.ShouldBindJSON(&in); err != nil || in.Name == nil || in.Type == nil {
		a.fail(c, http.StatusUnprocessableEntity, "name and type are required.")
		return
	}
	if in.KeySelectMode != nil && !validKeySelectModes[*in.KeySelectMode] {
		a.fail(c, http.StatusUnprocessableEntity, "invalid key_select_mode.")
		return
	}
	var clash int64
	a.GDB.Model(&database.Provider{}).Where("name = ?", *in.Name).Count(&clash)
	if clash > 0 {
		a.fail(c, http.StatusConflict, "Provider name already exists.")
		return
	}

	p := database.Provider{
		UUID: newUUID(), Name: *in.Name, Type: *in.Type,
		Slug:    a.uniqueSlug(orEmpty(in.Slug, *in.Name), 0),
		Enabled: true, Priority: 100, Weight: 1,
		Models: database.JSONOf([]string{}), ModelMap: database.JSONOf(map[string]any{}),
		ModelRoutes: database.JSONOf([]any{}), ExtraHeaders: database.JSONOf(map[string]any{}),
		PassthroughModels:              database.JSONOf([]string{}),
		UpstreamCooldownStatusCodes:    database.JSONOf([]int{}),
		UpstreamRetryAfterHeaders:      database.JSONOf([]string{}),
		SelectiveIgnoreRules:           database.JSONOf([]any{}),
		NormalizeDeveloperRoleToSystem: true,
		KeySelectMode:                  "round_robin", NewAPIMode: "auto",
	}
	// Adapter defaults.
	adapter := providers.GetAdapter(&p)
	if in.BaseURL != nil && *in.BaseURL != "" {
		p.BaseURL = *in.BaseURL
	} else {
		p.BaseURL = adapter.BaseURL()
	}
	if in.Models != nil {
		p.Models = database.JSONOf(*in.Models)
	}
	applyProviderPatch(&p, &in)

	if err := a.GDB.Create(&p).Error; err != nil {
		a.internal(c, err)
		return
	}
	sub, name := uv.User.Sub, services.BuildUserView(uv.User).Username
	var sensitive map[string]any
	if len(p.ExtraHeaders) > 2 && string(p.ExtraHeaders) != "{}" {
		sensitive = map[string]any{"extra_headers": json.RawMessage(p.ExtraHeaders)}
	}
	tid := strconv.Itoa(p.ID)
	_ = core.RecordAudit(a.GDB, core.AuditInput{
		Action: "provider.create", ActorSub: &sub, ActorName: name, Scope: core.AuditScopeAdmin,
		TargetType: strPtr("provider"), TargetID: &tid,
		Detail:    map[string]any{"name": p.Name, "type": p.Type, "base_url": p.BaseURL},
		Sensitive: sensitive, SecretKey: a.Cfg.Server.SecretKey, IP: strPtr(clientIP(c)),
	})
	var keys []database.ApiKey
	v := services.BuildProviderView(&p, keys)
	ad := providers.GetAdapter(&p)
	v.SupportsBalance = ad.GetBalanceURL() != ""
	v.SupportsImport, v.SupportsRefresh, v.SupportsOAuth = ad.CanImport(), ad.CanRefresh(), ad.CanOAuth()
	c.JSON(http.StatusCreated, v)
}

func (a *App) providerUpdate(c *gin.Context) {
	uv := core.GetUser(c)
	id, _ := strconv.Atoi(c.Param("id"))
	var p database.Provider
	if err := a.GDB.First(&p, id).Error; err != nil {
		a.fail(c, http.StatusNotFound, "Provider not found.")
		return
	}
	if !uv.IsStaff() && (p.AddedBy == nil || *p.AddedBy != uv.User.ID) {
		a.fail(c, http.StatusForbidden, "You can only modify providers you added.")
		return
	}
	var in providerPayload
	if err := c.ShouldBindJSON(&in); err != nil {
		a.fail(c, http.StatusUnprocessableEntity, "invalid payload.")
		return
	}
	if in.Name != nil && *in.Name != p.Name {
		var clash int64
		a.GDB.Model(&database.Provider{}).Where("name = ? AND id <> ?", *in.Name, p.ID).Count(&clash)
		if clash > 0 {
			a.fail(c, http.StatusConflict, "Provider name already exists.")
			return
		}
	}
	if in.Slug != nil && strings.TrimSpace(*in.Slug) != "" {
		s := a.uniqueSlug(*in.Slug, p.ID)
		p.Slug = s
	}
	applyProviderPatch(&p, &in)
	if err := a.GDB.Save(&p).Error; err != nil {
		a.internal(c, err)
		return
	}
	sub, name := uv.User.Sub, services.BuildUserView(uv.User).Username
	tid := strconv.Itoa(p.ID)
	_ = core.RecordAudit(a.GDB, core.AuditInput{
		Action: "provider.update", ActorSub: &sub, ActorName: name, Scope: core.AuditScopeAdmin,
		TargetType: strPtr("provider"), TargetID: &tid, Detail: map[string]any{"name": p.Name},
		SecretKey: a.Cfg.Server.SecretKey, IP: strPtr(clientIP(c)),
	})
	a.providerOut(c, &p)
}

func (a *App) providerOut(c *gin.Context, p *database.Provider) {
	var keys []database.ApiKey
	a.GDB.Where("provider_id = ?", p.ID).Find(&keys)
	v := services.BuildProviderView(p, keys)
	ad := providers.GetAdapter(p)
	v.SupportsBalance = ad.GetBalanceURL() != ""
	v.SupportsImport, v.SupportsRefresh, v.SupportsOAuth = ad.CanImport(), ad.CanRefresh(), ad.CanOAuth()
	c.JSON(http.StatusOK, v)
}

func (a *App) providerDelete(c *gin.Context) {
	uv := core.GetUser(c)
	id, _ := strconv.Atoi(c.Param("id"))
	var p database.Provider
	if err := a.GDB.First(&p, id).Error; err != nil {
		a.fail(c, http.StatusNotFound, "Provider not found.")
		return
	}
	if err := a.GDB.Delete(&p).Error; err != nil {
		a.internal(c, err)
		return
	}
	sub, name := uv.User.Sub, services.BuildUserView(uv.User).Username
	tid := strconv.Itoa(id)
	_ = core.RecordAudit(a.GDB, core.AuditInput{
		Action: "provider.delete", ActorSub: &sub, ActorName: name, Scope: core.AuditScopeAdmin,
		TargetType: strPtr("provider"), TargetID: &tid, Detail: map[string]any{"name": p.Name},
	})
	c.Status(http.StatusNoContent)
}

var statusRangeRe = regexp.MustCompile(`^\s*(\d{3})\s*(-\s*(\d{3}))?\s*$`)

func (a *App) catalogTypes(c *gin.Context) {
	c.JSON(http.StatusOK, providers.AdapterCatalog())
}

// pickKeyID returns the selected key when the request targets key_id:<id>.
func parseKeyPicker(token string) (int, bool) {
	if strings.HasPrefix(token, "key_id:") {
		if id, err := strconv.Atoi(strings.TrimPrefix(token, "key_id:")); err == nil {
			return id, true
		}
	}
	return 0, false
}

func (a *App) providerFetchModels(c *gin.Context) {
	var in struct {
		BaseURL string `json:"base_url"`
		Method  string `json:"method"`
		Path    string `json:"path"`
		Token   string `json:"token"`
		KeyID   *int   `json:"key_id"`
	}
	if err := c.ShouldBindJSON(&in); err != nil {
		a.fail(c, http.StatusUnprocessableEntity, "invalid payload.")
		return
	}
	models, err := services.FetchUpstreamModels(c.Request.Context(), in.BaseURL, in.Method, in.Path, in.Token, "")
	if err != nil {
		a.fail(c, http.StatusBadGateway, err.Error())
		return
	}
	c.JSON(http.StatusOK, gin.H{"models": models})
}

func (a *App) providerFetchModelKeys(c *gin.Context) {
	id, _ := strconv.Atoi(c.Param("id"))
	var keys []database.ApiKey
	if err := a.GDB.Where("provider_id = ?", id).Order("sort_order, id").Find(&keys).Error; err != nil {
		a.internal(c, err)
		return
	}
	out := make([]gin.H, 0, len(keys))
	for i := range keys {
		out = append(out, gin.H{
			"id": keys[i].ID, "index": i, "note": deref(keys[i].Note),
			"pool": keys[i].Pool, "status": keys[i].Status,
		})
	}
	c.JSON(http.StatusOK, out)
}

// key-api credential management (owner-only)
func (a *App) keyAPIStatus(c *gin.Context) {
	id, _ := strconv.Atoi(c.Param("id"))
	var p database.Provider
	if err := a.GDB.First(&p, id).Error; err != nil {
		a.fail(c, http.StatusNotFound, "Provider not found.")
		return
	}
	c.JSON(http.StatusOK, gin.H{
		"provider_id": p.ID, "provider_uuid": p.UUID,
		"enabled": p.KeyAPIEnabled, "token_preview": p.KeyAPITokenPreview,
	})
}

func (a *App) keyAPIAction(c *gin.Context) {
	id, _ := strconv.Atoi(c.Param("id"))
	action := c.Param("action")
	var p database.Provider
	if err := a.GDB.First(&p, id).Error; err != nil {
		a.fail(c, http.StatusNotFound, "Provider not found.")
		return
	}
	switch action {
	case "enable", "rotate":
		raw, _ := core.GenerateProviderAPIToken()
		hash := core.HashToken(raw)
		ct, err := cryptoutil.EncryptSecret(raw, a.Cfg.Server.SecretKey)
		if err != nil {
			a.internal(c, err)
			return
		}
		preview := tokenPreview(raw)
		a.GDB.Model(&p).Updates(map[string]any{
			"key_api_enabled": true, "key_api_token_hash": hash,
			"key_api_token_ciphertext": ct, "key_api_token_preview": preview,
		})
		c.JSON(http.StatusOK, gin.H{
			"provider_id": p.ID, "provider_uuid": p.UUID, "enabled": true,
			"token_preview": preview, "token": raw,
		})
	case "disable":
		a.GDB.Model(&p).Updates(map[string]any{
			"key_api_enabled": false, "key_api_token_hash": nil,
			"key_api_token_ciphertext": nil, "key_api_token_preview": nil,
		})
		c.JSON(http.StatusOK, gin.H{"provider_id": p.ID, "provider_uuid": p.UUID, "enabled": false, "token_preview": nil})
	case "reveal":
		if !p.KeyAPIEnabled || p.KeyAPITokenCiphertext == nil {
			a.fail(c, http.StatusBadRequest, "Key-management API is not enabled for this provider.")
			return
		}
		raw, err := cryptoutil.DecryptSecret(*p.KeyAPITokenCiphertext, a.Cfg.Server.SecretKey)
		if err != nil {
			a.internal(c, err)
			return
		}
		c.JSON(http.StatusOK, gin.H{
			"provider_id": p.ID, "provider_uuid": p.UUID, "enabled": true,
			"token_preview": p.KeyAPITokenPreview, "token": raw,
		})
	default:
		a.fail(c, http.StatusNotFound, "unknown action")
	}
}

func tokenPreview(raw string) string {
	if len(raw) > 14 {
		return raw[:8] + "…" + raw[len(raw)-4:]
	}
	return raw[:4] + "***"
}

// applyProviderPatch applies non-nil payload fields to the provider row.
func applyProviderPatch(p *database.Provider, in *providerPayload) {
	if in.Name != nil {
		p.Name = *in.Name
	}
	if in.Type != nil {
		p.Type = *in.Type
	}
	if in.BaseURL != nil {
		p.BaseURL = *in.BaseURL
	}
	if in.Enabled != nil {
		p.Enabled = *in.Enabled
	}
	if in.Models != nil {
		p.Models = database.JSONOf(*in.Models)
	}
	if in.BalanceURL != nil {
		v := *in.BalanceURL
		p.BalanceURL = &v
	}
	if in.ExtraHeaders != nil {
		p.ExtraHeaders = database.JSONOf(*in.ExtraHeaders)
	}
	if in.TimeoutSeconds != nil {
		p.TimeoutSeconds = *in.TimeoutSeconds
	}
	if in.RetryOnZeroToken != nil {
		p.RetryOnZeroToken = *in.RetryOnZeroToken
	}
	if in.DropOpenCodeIdentityBlock != nil {
		p.DropOpenCodeIdentityBlock = *in.DropOpenCodeIdentityBlock
	}
	if in.NormalizeDeveloperRoleToSystem != nil {
		p.NormalizeDeveloperRoleToSystem = *in.NormalizeDeveloperRoleToSystem
	}
	if in.NodeGroupID != nil {
		p.NodeGroupID = in.NodeGroupID
	}
	if in.KeySelectMode != nil {
		p.KeySelectMode = *in.KeySelectMode
	}
	if in.RateLimitCooldownSeconds != nil {
		v := *in.RateLimitCooldownSeconds
		if v < 0 {
			v = 0
		}
		p.RateLimitCooldownSeconds = v
	}
	if in.PassthroughEnabled != nil {
		p.PassthroughEnabled = *in.PassthroughEnabled
	}
	if in.PassthroughModels != nil {
		p.PassthroughModels = database.JSONOf(*in.PassthroughModels)
	}
	if in.NewAPIMode != nil {
		p.NewAPIMode = *in.NewAPIMode
	}
	if in.ProtectedErrorRetryEnabled != nil {
		p.ProtectedErrorRetryEnabled = *in.ProtectedErrorRetryEnabled
	}
	if in.SelectiveIgnoreRules != nil {
		p.SelectiveIgnoreRules = database.JSON(*in.SelectiveIgnoreRules)
	}
}

// RegisterProviderRoutes wires /api/admin/providers.
func RegisterProviderRoutes(g *gin.RouterGroup, a *App) {
	g.GET("/providers", a.providersList)
	g.POST("/providers", a.providerCreate)
	g.GET("/providers/catalog/types", a.catalogTypes)
	g.POST("/providers/fetch-models", a.providerFetchModels)
	g.PATCH("/providers/:id", a.providerUpdate)
	g.DELETE("/providers/:id", core.RequireOwner(), a.providerDelete)
	g.GET("/providers/:id/fetch-models/keys", a.providerFetchModelKeys)
	g.GET("/providers/:id/key-api", core.RequireOwner(), a.keyAPIStatus)
	g.POST("/providers/:id/key-api/:action", core.RequireOwner(), a.keyAPIAction)
}

var _ = gorm.ErrRecordNotFound

func orEmpty(p *string, def string) string {
	if p != nil && strings.TrimSpace(*p) != "" {
		return *p
	}
	return def
}
