package handlers

import (
	"encoding/json"
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

// ---- model id adapter ------------------------------------------------------

// modelDeleteByPublicID resolves a public model id to its primary key and then
// calls the dashboard handler, which deletes by id. Passing the public id
// straight through would treat "fast-coder" as id 0 and, worse, let a numeric
// public id delete an unrelated model.
func (a *App) modelDeleteByPublicID(c *gin.Context) {
	modelID := c.Param("model_id")
	var m database.ExposedModel
	if err := a.GDB.Select("id").Where("model_id = ?", modelID).First(&m).Error; err != nil {
		a.fail(c, http.StatusNotFound, "Model not found.")
		return
	}
	c.Params = setParam(c.Params, "id", strconv.Itoa(m.ID))
	a.modelDelete(c)
}

// ---- by-slug adapters ------------------------------------------------------

// providerKeysListBySlug lists one provider's upstream keys. The projection is
// narrowed for platform callers: the dashboard's key preview (first four and
// last four characters) is a partial plaintext, and a platform key must not be
// able to read any part of a stored credential.
func (a *App) providerKeysListBySlug(c *gin.Context) {
	if core.GetPlatformCredential(c) == nil {
		a.withProviderSlug(c, a.keysList)
		return
	}
	a.withProviderSlug(c, func(ctx *gin.Context) {
		w := &platformKeyRedactingWriter{ResponseWriter: ctx.Writer, hidePreview: true}
		ctx.Writer = w
		a.keysList(ctx)
	})
}

// platformKeyRedactingWriter strips fields a platform API key must never see
// from a handler's JSON response.
type platformKeyRedactingWriter struct {
	gin.ResponseWriter
	hidePreview bool
}

func (w *platformKeyRedactingWriter) Write(b []byte) (int, error) {
	if !w.hidePreview {
		return w.ResponseWriter.Write(b)
	}
	var items []map[string]any
	if err := json.Unmarshal(b, &items); err != nil {
		return w.ResponseWriter.Write(b)
	}
	for _, item := range items {
		delete(item, "key_preview")
	}
	redacted, err := json.Marshal(items)
	if err != nil {
		return w.ResponseWriter.Write(b)
	}
	return w.ResponseWriter.Write(redacted)
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
