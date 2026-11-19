package handlers

import (
	"net/http"

	"github.com/gin-gonic/gin"

	"github.com/siiway/voidswitch/internal/core"
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
			if !authorizeAction(c, tool.Action) {
				return
			}
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
		c.JSON(http.StatusOK, gin.H{
			"user":   cred.User.User.Sub,
			"role":   cred.User.Role,
			"key":    cred.Key.Name,
			"prefix": cred.Fingerprint,
			"scopes": cred.Scopes,
			"tools":  visibleToolNames(cred),
		})
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

// platformRateLimit applies the platform-API rate limit, counted per key. The
// limit reuses the operations budget (20 s / 30 requests by default) and is
// configurable through the settings page.
func (a *App) platformRateLimit() gin.HandlerFunc {
	return func(c *gin.Context) {
		cred := core.GetPlatformCredential(c)
		if cred == nil || a.RDB == nil {
			c.Next()
			return
		}
		window := float64(a.settingOrDefaultInt("platform_api_rate_limit_window_seconds", 20))
		maximum := a.settingOrDefaultInt("platform_api_rate_limit_max_requests", 30)
		if maximum <= 0 || window <= 0 {
			c.Next()
			return
		}
		ok, err := a.RDB.RateLimiter("rate:platform-api").Acquire(
			c.Request.Context(), cred.Fingerprint, window, maximum)
		if err == nil && !ok {
			c.AbortWithStatusJSON(http.StatusTooManyRequests,
				gin.H{"detail": "Platform API rate limit exceeded. Slow down."})
			return
		}
		c.Next()
	}
}

// settingOrDefaultInt reads an integer setting with a fallback.
func (a *App) settingOrDefaultInt(key string, def int) int {
	if key == "" {
		return def
	}
	if v, ok := a.settingInt(key); ok && v > 0 {
		return v
	}
	return def
}
