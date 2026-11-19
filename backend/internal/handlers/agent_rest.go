package handlers

import (
	"context"
	"log/slog"
	"net/http"
	"strconv"

	"github.com/gin-gonic/gin"

	"github.com/siiway/voidswitch/internal/core"
	"github.com/siiway/voidswitch/internal/redisx"
	"github.com/siiway/voidswitch/internal/services"
)

// authorizeAction rejects a hand-written /api/v1 route whose scope the key does
// not carry. Routes registered from platformTools() call this through the
// per-tool wrapper; the provider-scoped ones additionally re-check the slug.
func authorizeAction(c *gin.Context, action string) bool {
	cred := core.GetPlatformCredential(c)
	if cred == nil {
		return true
	}
	if !cred.Allows(action) {
		c.AbortWithStatusJSON(http.StatusForbidden,
			gin.H{"detail": "This API key is missing the '" + action + "' scope."})
		return false
	}
	return true
}

// applyParamAlias registers a path parameter under the name the dashboard handler
// reads it by. The public API names a model "model_id"; the handler behind it was
// written for the dashboard, where the same value arrives as "id".
func applyParamAlias(c *gin.Context, alias map[string]string) {
	for argName, handlerName := range alias {
		if argName == handlerName {
			continue
		}
		if v := c.Param(argName); v != "" {
			c.Params = setParam(c.Params, handlerName, v)
		}
	}
}

// authorizeProviderAction checks a provider-key action against the provider named
// in the path.
func authorizeProviderAction(c *gin.Context, action, slug string) bool {
	cred := core.GetPlatformCredential(c)
	if cred == nil {
		return true
	}
	if slug == "" || !cred.AllowsProviderKey(slug, action) {
		c.AbortWithStatusJSON(http.StatusForbidden,
			gin.H{"detail": "This API key is not permitted to manage provider '" + slug + "'."})
		return false
	}
	return true
}

// RegisterPlatformAPIRoutes wires /api/v1/**: the REST form of the platform
// tools. Every route is generated from platformTools(), so a new tool is a
// single table entry rather than three (tool, REST, scope).
//
// The MCP endpoint lives at /api/v1/mcp and is registered separately by
// RegisterPlatformMCPRoutes.
func RegisterPlatformAPIRoutes(r *gin.RouterGroup, a *App) {
	group := r.Group("/v1")
	group.Use(core.PlatformKeyAuth(a.GDB, false), a.platformRateLimit())
	for _, tool := range a.platformTools() {
		tool := tool
		group.Handle(tool.Method, tool.Path, func(c *gin.Context) {
			// A provider-key action is granted per provider, so the decision needs
			// the slug from the path rather than a bare action name.
			if tool.ProviderScoped {
				if !authorizeProviderAction(c, tool.Action, c.Param("slug")) {
					return
				}
			} else if !authorizeAction(c, tool.Action) {
				return
			}
			applyParamAlias(c, tool.ParamAlias)
			tool.Handler(c)
		})
	}
	// Convenience: the caller's own key, so a client can verify a token and see
	// what it may do before issuing real calls.
	group.GET("/whoami", func(c *gin.Context) {
		cred := core.GetPlatformCredential(c)
		if cred == nil {
			c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"detail": "Missing API key."})
			return
		}
		scopes := cred.Scopes
		if scopes == nil {
			scopes = []string{}
		}
		body := gin.H{
			"user":   cred.User.User.Sub,
			"role":   cred.User.Role,
			"key":    cred.Key.Name,
			"prefix": cred.Fingerprint,
			"scopes": scopes,
			"tools":  visibleToolNames(cred),
		}
		if len(cred.Scopes) == 0 {
			body["detail"] = "This key has no scopes its owner's role may still grant; ask an owner to re-scope it."
		}
		c.JSON(http.StatusOK, body)
	})
}

// visibleToolNames lists the actions a credential may call, for self-discovery.
func visibleToolNames(cred *core.PlatformCredential) []string {
	actions := core.Actions()
	out := make([]string, 0, len(actions))
	for _, act := range actions {
		if act.Tier == core.TierProviderKey {
			continue
		}
		if cred.Allows(act.Name) {
			out = append(out, act.Name)
		}
	}
	return out
}

// platformAcquire is the rate-limit primitive the middleware calls. It is a
// variable so the middleware's allow/deny/error branches can be tested without a
// Redis instance; production always uses the sliding-window limiter.
var platformAcquire = func(svc *redisx.Service, ctx context.Context, key string, window float64, max int) (bool, error) {
	return svc.RateLimiter("rate:platform-api").Acquire(ctx, key, window, max)
}

// platformRateLimit applies the platform-API rate limit, counted per key. The
// window and budget come from the settings snapshot (a cache read, not a query
// per request), so a change on the settings page takes effect without a restart.
func (a *App) platformRateLimit() gin.HandlerFunc {
	return func(c *gin.Context) {
		cred := core.GetPlatformCredential(c)
		if cred == nil || a.RDB == nil {
			c.Next()
			return
		}
		window := float64(services.GetInt("platform_api_rate_limit_window_seconds", 20))
		maximum := services.GetInt("platform_api_rate_limit_max_requests", 30)
		if maximum <= 0 || window <= 0 {
			c.Next()
			return
		}
		ok, err := platformAcquire(a.RDB, c.Request.Context(), strconv.Itoa(cred.Key.ID), window, maximum)
		if err != nil {
			// Redis being unreachable must not turn a rate limit into an outage;
			// log once per request path so the failure is visible.
			slog.Warn("platform api rate limit unavailable", "err", err)
			c.Next()
			return
		}
		if !ok {
			c.AbortWithStatusJSON(http.StatusTooManyRequests,
				gin.H{"detail": "Platform API rate limit exceeded. Slow down."})
			return
		}
		c.Next()
	}
}
