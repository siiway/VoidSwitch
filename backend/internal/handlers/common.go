// Package handlers wires the HTTP surface. Endpoints are grouped per feature
// file and share an App context carrying the database, config and helpers.
package handlers

import (
	"log/slog"
	"net/http"
	"strings"

	"github.com/gin-gonic/gin"
	"gorm.io/gorm"

	"github.com/siiway/voidswitch/internal/config"
	"github.com/siiway/voidswitch/internal/core"
	"github.com/siiway/voidswitch/internal/database"
	"github.com/siiway/voidswitch/internal/redisx"
	"github.com/siiway/voidswitch/internal/tasks"
)

// App holds shared dependencies for every handler.
type App struct {
	DB    *database.DB
	GDB   *gorm.DB
	Cfg   *config.Settings
	RDB   *redisx.Service
	Tasks *tasks.Manager
}

func (a *App) fail(c *gin.Context, status int, msg string) {
	c.AbortWithStatusJSON(status, gin.H{"detail": msg})
}

func (a *App) internal(c *gin.Context, err error) {
	slog.Error("handler error", "path", c.Request.URL.Path, "err", err)
	c.AbortWithStatusJSON(http.StatusInternalServerError, gin.H{"detail": "Internal Server Error"})
}

// audit records one audit row, stamping the platform API key that performed the
// action (nil for browser sessions) and the transport it used. Handlers call it
// instead of core.RecordAudit directly so the credential attribution cannot be
// forgotten on a new call site.
func (a *App) audit(c *gin.Context, in core.AuditInput) error {
	if cred := core.GetPlatformCredential(c); cred != nil {
		if in.Credential == nil {
			in.Credential = strPtr(cred.Fingerprint)
		}
		if in.Via == "" {
			if cred.ViaMCP {
				in.Via = "mcp"
			} else {
				in.Via = "rest"
			}
		}
	}
	return core.RecordAudit(a.GDB, in)
}

// clientIPHeader is the inbound header trusted for the real client IP. Defaults
// to X-Forwarded-For; overridable via VOIDSWITCH_CLIENT_IP_HEADER.
var clientIPHeader = "X-Forwarded-For"

// SetClientIPHeader configures which header carries the client IP (call once at
// startup). An empty value keeps the X-Forwarded-For default.
func SetClientIPHeader(header string) {
	if header != "" {
		clientIPHeader = header
	}
}

// clientIP returns the client IP, taking the FIRST entry of the configured header
// (the real client when behind a reverse proxy that appends hops) — matching the
// Python backend, which used only the first X-Forwarded-For value.
func clientIP(c *gin.Context) string {
	if h := c.GetHeader(clientIPHeader); h != "" {
		if i := strings.IndexByte(h, ','); i >= 0 {
			h = h[:i]
		}
		if ip := strings.TrimSpace(h); ip != "" {
			return ip
		}
	}
	return c.ClientIP()
}
