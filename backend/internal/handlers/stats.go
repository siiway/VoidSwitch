package handlers

import (
	"net/http"
	"time"

	"github.com/gin-gonic/gin"

	"github.com/siiway/voidswitch/internal/constants"
	"github.com/siiway/voidswitch/internal/database"
	"github.com/siiway/voidswitch/internal/services"
)

// statsSummary returns the dashboard overview counters.
func (a *App) statsSummary(c *gin.Context) {
	var providers, activeKeys, totalKeys, activeProxies, totalProxies, users, tokens int64
	a.GDB.Model(&database.Provider{}).Count(&providers)
	a.GDB.Model(&database.ApiKey{}).Where("status = ?", string(constants.KeyStatusActive)).Count(&activeKeys)
	a.GDB.Model(&database.ApiKey{}).Count(&totalKeys)
	a.GDB.Model(&database.Node{}).Where("enabled = ? AND status = ?", true, string(constants.NodeStatusActive)).Count(&activeProxies)
	a.GDB.Model(&database.Node{}).Count(&totalProxies)
	a.GDB.Model(&database.User{}).Count(&users)
	a.GDB.Model(&database.VoidToken{}).Where("deleted = ?", false).Count(&tokens)

	since := time.Now().UTC().Add(-24 * time.Hour)
	var reqs, succ int64
	var tokens24 int64
	a.GDB.Model(&database.RequestLog{}).Where("ts >= ?", since).Count(&reqs)
	a.GDB.Model(&database.RequestLog{}).Where("ts >= ? AND success = ?", since, true).Count(&succ)
	a.GDB.Model(&database.RequestLog{}).Where("ts >= ?", since).Select("COALESCE(SUM(total_tokens),0)").Scan(&tokens24)

	successRate := 0.0
	if reqs > 0 {
		successRate = float64(succ) / float64(reqs)
	}
	c.JSON(http.StatusOK, gin.H{
		"providers": providers, "active_keys": activeKeys, "total_keys": totalKeys,
		"active_proxies": activeProxies, "total_proxies": totalProxies,
		"users": users, "tokens": tokens,
		"requests_24h": reqs, "success_24h": succ, "failures_24h": reqs - succ,
		"tokens_24h": tokens24, "success_rate_24h": successRate,
		"avg_tokens_per_request_24h": avgPerReq(tokens24, reqs),
	})
}

func avgPerReq(total, n int64) int64 {
	if n == 0 {
		return 0
	}
	return total / n
}

// settingsGet returns all settings (staff).
func (a *App) settingsGet(c *gin.Context) {
	values, err := services.LoadSettings(a.GDB)
	if err != nil {
		a.internal(c, err)
		return
	}
	c.JSON(http.StatusOK, gin.H{"values": values})
}

// RegisterStatsRoutes wires /api/admin/stats.
func RegisterStatsRoutes(r *gin.RouterGroup, a *App) {
	r.GET("/stats", a.statsSummary)
}
