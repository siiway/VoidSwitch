package handlers

import (
	"net/http"
	"strconv"

	"github.com/gin-gonic/gin"

	"github.com/siiway/voidswitch/internal/core"
	"github.com/siiway/voidswitch/internal/database"
)

// The platform API addresses a provider's upstream keys by slug rather than by
// id, because a key's scope names the provider slug ("provider-key:acme.*").
// These adapters resolve the slug, then hand off to the existing id-based
// handlers with the path parameter rewritten — so validation, audit rows and
// error messages stay in one place.

// bySlug rewrites the "slug" path parameter into the "id" one the id-based
// handler expects, and records the provider's id in the gin context so the
// authorisation wrapper already ran against the right provider.
func (a *App) providerIDBySlug(c *gin.Context, slug string) (int, bool) {
	var p database.Provider
	if err := a.GDB.Select("id").Where("slug = ?", slug).First(&p).Error; err != nil {
		a.fail(c, http.StatusNotFound, "Provider not found.")
		return 0, false
	}
	return p.ID, true
}

// withProviderSlug resolves the slug and runs fn with the id in place.
func (a *App) withProviderSlug(c *gin.Context, fn gin.HandlerFunc) {
	slug := c.Param("slug")
	pid, ok := a.providerIDBySlug(c, slug)
	if !ok {
		return
	}
	if !a.platformProviderAllowed(c, slug) {
		return
	}
	c.Params = setParam(c.Params, "id", strconv.Itoa(pid))
	fn(c)
}

// platformProviderAllowed enforces the per-provider scope. Browser sessions have
// no platform credential and are already staff-gated by the dashboard router.
func (a *App) platformProviderAllowed(c *gin.Context, slug string) bool {
	if cred := core.GetPlatformCredential(c); cred != nil {
		return authorizeProviderScope(c, "provider-key", slug)
	}
	return true
}

func setParam(params gin.Params, key, value string) gin.Params {
	for i := range params {
		if params[i].Key == key {
			params[i].Value = value
			return params
		}
	}
	return append(params, gin.Param{Key: key, Value: value})
}

// ---- by-slug adapters ------------------------------------------------------

func (a *App) providerKeysListBySlug(c *gin.Context) {
	a.withProviderSlug(c, a.keysList)
}

func (a *App) providerKeysAddBySlug(c *gin.Context) {
	a.withProviderSlug(c, a.keysCreate)
}

func (a *App) providerKeysUpdateBySlug(c *gin.Context) {
	c.Params = setParam(c.Params, "kid", c.Param("key_id"))
	a.withProviderSlug(c, a.keysUpdate)
}

func (a *App) providerKeysDeleteBySlug(c *gin.Context) {
	c.Params = setParam(c.Params, "kid", c.Param("key_id"))
	a.withProviderSlug(c, a.keysDelete)
}

func (a *App) providerKeysReorderBySlug(c *gin.Context) {
	a.withProviderSlug(c, a.keysReorder)
}

func (a *App) providerKeysRefreshBySlug(c *gin.Context) {
	a.withProviderSlug(c, a.keysRefreshBalance)
}

func (a *App) providerKeysCleanupBySlug(c *gin.Context) {
	a.withProviderSlug(c, a.keysCleanup)
}
