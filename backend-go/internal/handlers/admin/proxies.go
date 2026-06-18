package admin

import (
	"net/http"
	"strconv"
	"time"

	"github.com/gin-gonic/gin"

	"github.com/siiway/voidswitch/internal/core"
	"github.com/siiway/voidswitch/internal/database"
	"github.com/siiway/voidswitch/internal/models"
	"github.com/siiway/voidswitch/internal/services"
)

func listProxies(c *gin.Context) {
	db := database.GetDatabase().DB
	user, ok := getCurrentUserGin(c)
	if !ok || !requireStaffGin(c, user) {
		return
	}

	var proxies []database.Proxy
	if err := db.Find(&proxies).Error; err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to query proxies."})
		return
	}

	result := make([]models.ProxyOut, 0, len(proxies))
	for _, p := range proxies {
		result = append(result, proxyToOut(p))
	}

	c.JSON(http.StatusOK, result)
}

func batchAddProxies(c *gin.Context) {
	db := database.GetDatabase().DB
	user, ok := getCurrentUserGin(c)
	if !ok || !requireStaffGin(c, user) {
		return
	}

	var body models.ProxyCreate
	if err := c.ShouldBindJSON(&body); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid request body."})
		return
	}

	if len(body.URLs) == 0 {
		c.JSON(http.StatusBadRequest, gin.H{"error": "No URLs provided."})
		return
	}

	name := core.ActorDisplayName(user)
	var created []models.ProxyOut

	for _, url := range body.URLs {
		if url == "" {
			continue
		}
		record := database.Proxy{
			URL:          url,
			LocalAddress: body.LocalAddress,
			Weight:       body.Weight,
			Note:         body.Note,
		}
		if err := db.Create(&record).Error; err != nil {
			continue
		}
		created = append(created, proxyToOut(record))
	}

	core.RecordAudit(db, "proxy.create", &user.Sub, &name, nil, nil,
		map[string]any{"count": len(created)}, nil, nil, nil, "admin")

	c.JSON(http.StatusOK, created)
}

func updateProxy(c *gin.Context) {
	db := database.GetDatabase().DB
	user, ok := getCurrentUserGin(c)
	if !ok || !requireStaffGin(c, user) {
		return
	}

	id, err := strconv.Atoi(c.Param("id"))
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid proxy ID."})
		return
	}

	var existing database.Proxy
	if err := db.First(&existing, id).Error; err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "Proxy not found."})
		return
	}

	var body models.ProxyUpdate
	if err := c.ShouldBindJSON(&body); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid request body."})
		return
	}

	changes := make(map[string]any)

	if body.URL != nil {
		changes["url"] = map[string]any{"old": existing.URL, "new": *body.URL}
		existing.URL = *body.URL
	}
	if body.LocalAddress != nil {
		changes["local_address"] = map[string]any{"old": existing.LocalAddress, "new": *body.LocalAddress}
		existing.LocalAddress = body.LocalAddress
	}
	if body.Enabled != nil {
		changes["enabled"] = map[string]any{"old": existing.Enabled, "new": *body.Enabled}
		existing.Enabled = *body.Enabled
	}
	if body.Status != nil {
		changes["status"] = map[string]any{"old": existing.Status, "new": *body.Status}
		existing.Status = *body.Status
	}
	if body.Weight != nil {
		changes["weight"] = map[string]any{"old": existing.Weight, "new": *body.Weight}
		existing.Weight = *body.Weight
	}
	if body.Note != nil {
		changes["note"] = map[string]any{"old": existing.Note, "new": *body.Note}
		existing.Note = body.Note
	}

	if err := db.Save(&existing).Error; err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to update proxy."})
		return
	}

	cname := core.ActorDisplayName(user)
	targetID := strconv.Itoa(existing.ID)
	targetType := "proxy"
	core.RecordAudit(db, "proxy.update", &user.Sub, &cname, &targetType, &targetID, changes, nil, nil, nil, "admin")

	c.JSON(http.StatusOK, proxyToOut(existing))
}

func deleteProxy(c *gin.Context) {
	db := database.GetDatabase().DB
	user, ok := getCurrentUserGin(c)
	if !ok || !requireStaffGin(c, user) {
		return
	}

	id, err := strconv.Atoi(c.Param("id"))
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid proxy ID."})
		return
	}

	var existing database.Proxy
	if err := db.First(&existing, id).Error; err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "Proxy not found."})
		return
	}

	if err := db.Delete(&existing).Error; err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to delete proxy."})
		return
	}

	cname := core.ActorDisplayName(user)
	targetID := strconv.Itoa(id)
	targetType := "proxy"
	core.RecordAudit(db, "proxy.delete", &user.Sub, &cname, &targetType, &targetID,
		map[string]any{"url": existing.URL}, nil, nil, nil, "admin")

	c.Status(http.StatusNoContent)
}

func probeProxy(c *gin.Context) {
	db := database.GetDatabase().DB
	user, ok := getCurrentUserGin(c)
	if !ok || !requireStaffGin(c, user) {
		return
	}

	id, err := strconv.Atoi(c.Param("id"))
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid proxy ID."})
		return
	}

	var existing database.Proxy
	if err := db.First(&existing, id).Error; err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "Proxy not found."})
		return
	}

	probeURL := services.GetCached("proxy_probe_url", "https://api.openai.com/v1/models")
	if s, ok := probeURL.(string); ok {
		probeURL = s
	}
	targetURL, _ := probeURL.(string)
	if targetURL == "" {
		targetURL = "https://api.openai.com/v1/models"
	}

	route := services.NewRoute(&existing.URL, existing.LocalAddress)
	okRoute, latencyMs, statusCode, errStr := services.ProbeRoute(route, targetURL, nil, 15*time.Second)

	now := time.Now()
	existing.LastCheckedAt = &now
	existing.LatencyMs = &latencyMs

	if okRoute {
		if existing.Status == "disabled" {
			existing.Status = "active"
			existing.FailedCount = 0
			existing.DisabledReason = nil
		}
	} else {
		existing.FailedCount++
		maxFailures := services.GetInt("max_proxy_failures", 3)
		if existing.FailedCount >= maxFailures {
			existing.Status = "disabled"
			existing.DisabledReason = &errStr
		}
	}

	if err := db.Save(&existing).Error; err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to update proxy status."})
		return
	}

	c.JSON(http.StatusOK, gin.H{
		"ok":          okRoute,
		"latency_ms":  latencyMs,
		"status_code": statusCode,
		"error":       errStr,
		"proxy":       proxyToOut(existing),
	})
}

func proxyToOut(p database.Proxy) models.ProxyOut {
	return models.ProxyOut{
		ID:             p.ID,
		URL:            p.URL,
		LocalAddress:   p.LocalAddress,
		Enabled:        p.Enabled,
		Status:         p.Status,
		FailedCount:    p.FailedCount,
		Weight:         p.Weight,
		LatencyMs:      p.LatencyMs,
		Note:           p.Note,
		DisabledReason: p.DisabledReason,
		LastUsedAt:     p.LastUsedAt,
		LastCheckedAt:  p.LastCheckedAt,
		CreatedAt:      p.CreatedAt,
	}
}

func RegisterProxyRoutes(router *gin.RouterGroup) {
	proxyGroup := router.Group("/proxies")
	{
		proxyGroup.GET("", listProxies)
		proxyGroup.POST("", batchAddProxies)
		proxyGroup.PATCH("/:id", updateProxy)
		proxyGroup.DELETE("/:id", deleteProxy)
		proxyGroup.POST("/:id/probe", probeProxy)
	}
}
