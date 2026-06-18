package admin

import (
	"net/http"
	"time"

	"github.com/gin-gonic/gin"

	"github.com/siiway/voidswitch/internal/database"
	"github.com/siiway/voidswitch/internal/models"
)

func getStats(c *gin.Context) {
	db := database.GetDatabase().DB
	user, ok := getCurrentUserGin(c)
	if !ok || !requireStaffGin(c, user) {
		return
	}

	var providers int64
	db.Model(&database.Provider{}).Count(&providers)

	var activeKeys int64
	db.Model(&database.ApiKey{}).Where("status = ?", "active").Count(&activeKeys)

	var totalKeys int64
	db.Model(&database.ApiKey{}).Count(&totalKeys)

	var activeProxies int64
	db.Model(&database.Proxy{}).Where("enabled = ?", true).Count(&activeProxies)

	var totalProxies int64
	db.Model(&database.Proxy{}).Count(&totalProxies)

	var tokens int64
	db.Model(&database.VoidToken{}).Count(&tokens)

	since := time.Now().Add(-24 * time.Hour)

	var requests24h int64
	db.Model(&database.RequestLog{}).Where("ts >= ?", since).Count(&requests24h)

	var success24h int64
	db.Model(&database.RequestLog{}).Where("ts >= ? AND success = ?", since, true).Count(&success24h)

	var failures24h int64
	db.Model(&database.RequestLog{}).Where("ts >= ? AND success = ?", since, false).Count(&failures24h)

	var tokens24hRow struct{ TotalTokens int64 }
	db.Model(&database.RequestLog{}).Where("ts >= ?", since).Select("COALESCE(SUM(total_tokens), 0) as total_tokens").Scan(&tokens24hRow)

	c.JSON(http.StatusOK, models.StatsOut{
		Providers:     int(providers),
		ActiveKeys:    int(activeKeys),
		TotalKeys:     int(totalKeys),
		ActiveProxies: int(activeProxies),
		TotalProxies:  int(totalProxies),
		Tokens:        int(tokens),
		Requests24h:   int(requests24h),
		Success24h:    int(success24h),
		Failures24h:   int(failures24h),
		Tokens24h:     int(tokens24hRow.TotalTokens),
	})
}

func RegisterStatsRoutes(router *gin.RouterGroup) {
	router.GET("/stats", getStats)
}
