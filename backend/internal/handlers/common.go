// Package handlers wires the HTTP surface. Endpoints are grouped per feature
// file and share an App context carrying the database, config and helpers.
package handlers

import (
	"log/slog"
	"net/http"

	"github.com/gin-gonic/gin"
	"gorm.io/gorm"

	"github.com/siiway/voidswitch/internal/config"
	"github.com/siiway/voidswitch/internal/database"
	"github.com/siiway/voidswitch/internal/redisx"
)

// App holds shared dependencies for every handler.
type App struct {
	DB  *database.DB
	GDB *gorm.DB
	Cfg *config.Settings
	RDB *redisx.Service
}

func (a *App) fail(c *gin.Context, status int, msg string) {
	c.AbortWithStatusJSON(status, gin.H{"detail": msg})
}

func (a *App) internal(c *gin.Context, err error) {
	slog.Error("handler error", "path", c.Request.URL.Path, "err", err)
	c.AbortWithStatusJSON(http.StatusInternalServerError, gin.H{"detail": "Internal Server Error"})
}

// clientIP returns the best-effort client IP honouring X-Forwarded-For.
func clientIP(c *gin.Context) string {
	if xff := c.GetHeader("X-Forwarded-For"); xff != "" {
		return xff
	}
	return c.ClientIP()
}
