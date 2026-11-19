package handlers

import (
	"fmt"
	"net/http"
	"strconv"

	"github.com/gin-gonic/gin"

	"github.com/siiway/voidswitch/internal/core"
	"github.com/siiway/voidswitch/internal/database"
	"github.com/siiway/voidswitch/internal/services"
	"github.com/siiway/voidswitch/internal/services/providers"
)

// Singular reads and the provider-slug key routes exist for the platform API
// (/api/v1 and MCP). The dashboard reads whole collections and addresses
// providers by id; an agent works better with a single-object read and with a
// provider slug, because that is what a scope entry names.

// providerGet returns one provider by id.
func (a *App) providerGet(c *gin.Context) {
	uv := core.GetUser(c)
	id, _ := strconv.Atoi(c.Param("id"))
	var p database.Provider
	if err := a.GDB.First(&p, id).Error; err != nil {
		a.fail(c, http.StatusNotFound, "Provider not found.")
		return
	}
	var keys []database.ApiKey
	a.GDB.Where("provider_id = ?", p.ID).Find(&keys)
	v := services.BuildProviderView(&p, keys)
	adapter := providers.GetAdapter(&p)
	v.SupportsBalance = adapter.GetBalanceURL() != ""
	v.SupportsImport = adapter.CanImport()
	v.SupportsRefresh = adapter.CanRefresh()
	v.SupportsOAuth = adapter.CanOAuth()
	if uv == nil || !uv.IsOwner() {
		for k := range v.ExtraHeaders {
			v.ExtraHeaders[k] = "***"
		}
	}
	c.JSON(http.StatusOK, v)
}

// modelGet returns one exposed model's metadata and route.
func (a *App) modelGet(c *gin.Context) {
	modelID := c.Param("model_id")
	var m database.ExposedModel
	if err := a.GDB.Where("model_id = ?", modelID).First(&m).Error; err != nil {
		a.fail(c, http.StatusNotFound, "Model not found.")
		return
	}
	cats := a.categoryLookup()
	refs := []string{}
	var route database.Route
	if err := a.GDB.Where("exposed_model_id = ?", m.ID).First(&route).Error; err == nil {
		var upstreams []database.RouteUpstream
		a.GDB.Where("route_id = ?", route.ID).Find(&upstreams)
		slugByID := map[int]string{}
		var providers []database.Provider
		a.GDB.Select("id", "slug").Find(&providers)
		for _, p := range providers {
			slugByID[p.ID] = p.Slug
		}
		for _, u := range upstreams {
			if u.ProviderID == nil {
				continue
			}
			refs = append(refs, fmt.Sprintf("%s/%s", slugByID[*u.ProviderID], u.UpstreamModel))
		}
	}
	v := services.BuildModelEntryView(&m, refs)
	applyCategory(&v, cats)
	c.JSON(http.StatusOK, v)
}

// nodeGet returns one egress node by id.
func (a *App) nodeGet(c *gin.Context) {
	id, _ := strconv.Atoi(c.Param("id"))
	var n database.Node
	if err := a.GDB.First(&n, id).Error; err != nil {
		a.fail(c, http.StatusNotFound, "Node not found.")
		return
	}
	c.JSON(http.StatusOK, n)
}

// roleGroupGet returns one role group with its member count.
func (a *App) roleGroupGet(c *gin.Context) {
	id, _ := strconv.Atoi(c.Param("id"))
	var g database.RoleGroup
	if err := a.GDB.First(&g, id).Error; err != nil {
		a.fail(c, http.StatusNotFound, "Role group not found.")
		return
	}
	c.JSON(http.StatusOK, a.roleGroupOut(&g))
}

// userGet returns one user.
func (a *App) userGet(c *gin.Context) {
	id, _ := strconv.Atoi(c.Param("id"))
	var u database.User
	if err := a.GDB.First(&u, id).Error; err != nil {
		a.fail(c, http.StatusNotFound, "User not found.")
		return
	}
	c.JSON(http.StatusOK, services.BuildUserView(&u))
}

// mePlatformKeyGet returns one of the caller's platform API keys.
func (a *App) mePlatformKeyGet(c *gin.Context) {
	id, _ := strconv.Atoi(c.Param("id"))
	row, ok := a.platformKeyForCaller(c, id)
	if !ok {
		return
	}
	c.JSON(http.StatusOK, toPlatformKeyView(row))
}

// logsRequestDebug returns one request log with the full debug trail. A platform
// API key never sees more than a staff dashboard session would, and never the
// bodies: the per-attempt trail carries upstream addresses and key previews, so
// it is redacted down to the same projection an admin already gets.
func (a *App) logsRequestDebug(c *gin.Context) {
	if cred := core.GetPlatformCredential(c); cred != nil && !cred.User.IsOwner() {
		id, _ := strconv.Atoi(c.Param("id"))
		var r database.RequestLog
		if err := a.GDB.First(&r, id).Error; err != nil {
			a.fail(c, http.StatusNotFound, "Request log not found.")
			return
		}
		if !a.requestLogVisible(cred.User, r.UserSub) {
			a.fail(c, http.StatusNotFound, "Request log not found.")
			return
		}
		v := a.buildRequestLogDetail(&r, cred.User)
		c.JSON(http.StatusOK, v)
		return
	}
	a.logsRequestDetail(c)
}
