package handlers

import (
	"net/http"
	"strconv"
	"strings"

	"github.com/gin-gonic/gin"

	"github.com/siiway/voidswitch/internal/core"
	"github.com/siiway/voidswitch/internal/database"
	"github.com/siiway/voidswitch/internal/services"
)

const providerAPIProvider = "provider.api"

// providerAPIAuth resolves the provider a vsk- token belongs to, or aborts 401.
func (a *App) providerAPIAuth(c *gin.Context) (*database.Provider, bool) {
	auth := c.GetHeader("Authorization")
	raw := ""
	if strings.HasPrefix(strings.ToLower(auth), "bearer ") {
		raw = strings.TrimSpace(auth[len("bearer "):])
	}
	if raw == "" {
		raw = c.GetHeader("X-API-Key")
	}
	if raw == "" {
		a.fail(c, http.StatusUnauthorized, "Missing key-management token.")
		return nil, false
	}
	var p database.Provider
	err := a.GDB.Where("key_api_token_hash = ?", core.HashToken(raw)).First(&p).Error
	if err != nil || !p.KeyAPIEnabled || p.KeyAPITokenHash == nil {
		a.fail(c, http.StatusUnauthorized, "Invalid or disabled key-management token.")
		return nil, false
	}
	return &p, true
}

// providerAPIWhoami returns the provider this token manages.
func (a *App) providerAPIWhoami(c *gin.Context) {
	p, ok := a.providerAPIAuth(c)
	if !ok {
		return
	}
	var keys []database.ApiKey
	a.GDB.Where("provider_id = ?", p.ID).Find(&keys)
	v := services.BuildProviderView(p, keys)
	// Never echo management-credential state through the token API.
	v.KeyAPIEnabled = false
	v.KeyAPITokenPreview = nil
	c.JSON(http.StatusOK, v)
}

func (a *App) providerAPIListKeys(c *gin.Context) {
	p, ok := a.providerAPIAuth(c)
	if !ok {
		return
	}
	var keys []database.ApiKey
	a.GDB.Where("provider_id = ?", p.ID).Order("sort_order, id").Find(&keys)
	out := make([]apiKeyView, 0, len(keys))
	for i := range keys {
		out = append(out, toApiKeyView(&keys[i]))
	}
	c.JSON(http.StatusOK, out)
}

func (a *App) providerAPIAddKeys(c *gin.Context) {
	p, ok := a.providerAPIAuth(c)
	if !ok {
		return
	}
	var in struct {
		Keys []string `json:"keys"`
		Pool string   `json:"pool"`
		Note *string  `json:"note"`
	}
	if err := c.ShouldBindJSON(&in); err != nil || len(in.Keys) == 0 {
		a.fail(c, http.StatusUnprocessableEntity, "keys are required.")
		return
	}
	// Use the import path which dedupes; returns {keys: [...]}.
	// Synthesise by calling the same core logic through a shared helper.
	created := a.addKeysForProvider(p.ID, in.Keys, in.Pool, in.Note)
	c.JSON(http.StatusCreated, created)
}

func (a *App) providerAPIUpdateKey(c *gin.Context) {
	p, ok := a.providerAPIAuth(c)
	if !ok {
		return
	}
	kid, _ := strconv.Atoi(c.Param("keyId"))
	var k database.ApiKey
	if err := a.GDB.Where("id = ? AND provider_id = ?", kid, p.ID).First(&k).Error; err != nil {
		a.fail(c, http.StatusNotFound, "Key not found.")
		return
	}
	var in struct {
		Key     *string `json:"key"`
		Status  *string `json:"status"`
		Weight  *int    `json:"weight"`
		Note    *string `json:"note"`
		Pool    *string `json:"pool"`
		Enabled *bool   `json:"enabled"`
	}
	_ = c.ShouldBindJSON(&in)
	if in.Status != nil {
		k.Status = *in.Status
	}
	if in.Enabled != nil {
		if *in.Enabled {
			k.Status = "active"
			k.DisabledReason = nil
		} else {
			k.Status = "disabled"
		}
	}
	if in.Weight != nil {
		k.Weight = *in.Weight
	}
	if in.Note != nil {
		k.Note = in.Note
	}
	if in.Pool != nil {
		k.Pool = *in.Pool
	}
	a.GDB.Save(&k)
	c.JSON(http.StatusOK, toApiKeyView(&k))
}

func (a *App) providerAPIDeleteKey(c *gin.Context) {
	p, ok := a.providerAPIAuth(c)
	if !ok {
		return
	}
	kid, _ := strconv.Atoi(c.Param("keyId"))
	a.GDB.Where("id = ? AND provider_id = ?", kid, p.ID).Delete(&database.ApiKey{})
	c.Status(http.StatusNoContent)
}

func (a *App) providerAPIReorder(c *gin.Context) {
	p, ok := a.providerAPIAuth(c)
	if !ok {
		return
	}
	var in struct {
		Order []int `json:"order"`
	}
	_ = c.ShouldBindJSON(&in)
	for idx, id := range in.Order {
		a.GDB.Model(&database.ApiKey{}).Where("id = ? AND provider_id = ?", id, p.ID).Update("sort_order", idx)
	}
	var keys []database.ApiKey
	a.GDB.Where("provider_id = ?", p.ID).Order("sort_order, id").Find(&keys)
	out := make([]apiKeyView, 0, len(keys))
	for i := range keys {
		out = append(out, toApiKeyView(&keys[i]))
	}
	c.JSON(http.StatusOK, out)
}

func (a *App) providerAPIRefreshBalance(c *gin.Context) {
	p, ok := a.providerAPIAuth(c)
	if !ok {
		return
	}
	autoDisable := services.GetBool("auto_disable_zero_balance", true)
	var keys []database.ApiKey
	a.GDB.Where("provider_id = ? AND status = ?", p.ID, "active").Find(&keys)
	for i := range keys {
		services.RefreshKeyBalance(a.GDB, &keys[i], p, a.Cfg.Server.SecretKey, autoDisable)
	}
	out := make([]apiKeyView, 0, len(keys))
	for i := range keys {
		a.GDB.First(&keys[i], keys[i].ID)
		out = append(out, toApiKeyView(&keys[i]))
	}
	c.JSON(http.StatusOK, out)
}

// RegisterProviderAPIRoutes mounts the per-provider key-management API.
func RegisterProviderAPIRoutes(r *gin.Engine, a *App) {
	g := r.Group("/provider-api")
	g.GET("/provider", a.providerAPIWhoami)
	g.GET("/keys", a.providerAPIListKeys)
	g.POST("/keys", a.providerAPIAddKeys)
	g.PATCH("/keys/:keyId", a.providerAPIUpdateKey)
	g.DELETE("/keys/:keyId", a.providerAPIDeleteKey)
	g.POST("/keys/reorder", a.providerAPIReorder)
	g.POST("/keys/refresh-balance", a.providerAPIRefreshBalance)
}
