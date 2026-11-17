package handlers

import (
	"math"
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

	// Average time-to-first-token over the same 24h window. Only streaming
	// requests record first_token_ms, and AVG ignores NULL, so a window with no
	// streamed request leaves this nil for the dashboard to render as "—".
	var avgTTFT *float64
	a.GDB.Model(&database.RequestLog{}).
		Where("ts >= ? AND first_token_ms IS NOT NULL", since).
		Select("AVG(first_token_ms)").Scan(&avgTTFT)

	successRate := 0.0
	if reqs > 0 {
		successRate = math.Round(float64(succ)/float64(reqs)*1000) / 10
	}

	// Throughput over the same window: tokens divided by the summed wall-clock
	// duration of those requests — the same expression the Statistics page uses,
	// so the two pages never disagree.
	var totalSeconds *float64
	a.GDB.Model(&database.RequestLog{}).Where("ts >= ?", since).
		Select("COALESCE(SUM(EXTRACT(EPOCH FROM (finished_at - started_at))),0)").
		Scan(&totalSeconds)
	c.JSON(http.StatusOK, gin.H{
		"providers": providers, "active_keys": activeKeys, "total_keys": totalKeys,
		"active_proxies": activeProxies, "total_proxies": totalProxies,
		"users": users, "tokens": tokens,
		"requests_24h": reqs, "success_24h": succ, "failures_24h": reqs - succ,
		"tokens_24h": tokens24, "success_rate_24h": successRate,
		"avg_first_token_ms_24h":     avgTTFT,
		"avg_tokens_per_request_24h": avgTokensPerReq(tokens24, reqs),
		"tokens_per_second_24h":      tokensPerSecond(tokens24, totalSeconds),
	})
}

// tokensPerSecond is the shared throughput formula: total tokens over the total
// request seconds. Nil when the window recorded no measurable duration, so the
// UI renders "—" instead of a fabricated zero.
func tokensPerSecond(tokens int64, seconds *float64) *float64 {
	if seconds == nil || *seconds <= 0 {
		return nil
	}
	tps := math.Round(float64(tokens)/(*seconds)*100) / 100
	return &tps
}

func avgTokensPerReq(total, n int64) float64 {
	if n == 0 {
		return 0
	}
	return math.Round(float64(total)/float64(n)*10) / 10
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
