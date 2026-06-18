package admin

import (
	"net/http"
	"strconv"

	"github.com/gin-gonic/gin"

	"github.com/siiway/voidswitch/internal/config"
	"github.com/siiway/voidswitch/internal/core"
	"github.com/siiway/voidswitch/internal/database"
	"github.com/siiway/voidswitch/internal/models"
)

func listAuditLogs(c *gin.Context) {
	db := database.GetDatabase().DB
	user, ok := getCurrentUserGin(c)
	if !ok || !requireStaffGin(c, user) {
		return
	}

	limit := 50
	offset := 0

	if l := c.Query("limit"); l != "" {
		if parsed, err := strconv.Atoi(l); err == nil && parsed > 0 {
			limit = parsed
		}
	}
	if o := c.Query("offset"); o != "" {
		if parsed, err := strconv.Atoi(o); err == nil && parsed >= 0 {
			offset = parsed
		}
	}

	q := db.Model(&database.AuditLog{})
	if action := c.Query("action"); action != "" {
		q = q.Where("action = ?", action)
	}
	if scope := c.Query("scope"); scope != "" {
		q = q.Where("scope = ?", scope)
	}

	var total int64
	if err := q.Count(&total).Error; err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to count audit logs."})
		return
	}

	var logs []database.AuditLog
	if err := q.Limit(limit).Offset(offset).Order("ts DESC").Find(&logs).Error; err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to query audit logs."})
		return
	}

	items := make([]models.AuditLogOut, 0, len(logs))
	for _, l := range logs {
		items = append(items, models.AuditLogOut{
			ID:           l.ID,
			TS:           l.Ts,
			ActorSub:     l.ActorSub,
			ActorName:    l.ActorName,
			Action:       l.Action,
			Scope:        l.Scope,
			TargetType:   l.TargetType,
			TargetID:     l.TargetID,
			Detail:       l.Detail,
			IP:           l.IP,
			HasSensitive: l.SensitiveCiphertext != nil,
		})
	}

	c.JSON(http.StatusOK, models.Page[models.AuditLogOut]{
		Items:  items,
		Total:  int(total),
		Limit:  limit,
		Offset: offset,
	})
}

func revealSensitivePayload(c *gin.Context) {
	db := database.GetDatabase().DB
	user, ok := getCurrentUserGin(c)
	if !ok || !requireOwnerGin(c, user) {
		return
	}

	id, err := strconv.Atoi(c.Param("id"))
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid audit log ID."})
		return
	}

	var log database.AuditLog
	if err := db.First(&log, id).Error; err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "Audit log not found."})
		return
	}

	if log.SensitiveCiphertext == nil || *log.SensitiveCiphertext == "" {
		c.JSON(http.StatusNotFound, gin.H{"error": "No sensitive payload for this audit log."})
		return
	}

	settings := config.Load()
	plaintext, _ := core.DecryptSecret(*log.SensitiveCiphertext, settings.Server.SecretKey)

	cname := core.ActorDisplayName(user)
	targetID := strconv.Itoa(log.ID)
	targetType := "audit_log"
	core.RecordAudit(db, "audit.reveal", &user.Sub, &cname, &targetType, &targetID,
		nil, nil, nil, nil, "admin")

	c.JSON(http.StatusOK, gin.H{"payload": plaintext})
}

func listRequestLogs(c *gin.Context) {
	db := database.GetDatabase().DB
	user, ok := getCurrentUserGin(c)
	if !ok {
		return
	}

	isStaff := core.StaffRolesSet[user.Role]

	limit := 50
	offset := 0

	if l := c.Query("limit"); l != "" {
		if parsed, err := strconv.Atoi(l); err == nil && parsed > 0 {
			limit = parsed
		}
	}
	if o := c.Query("offset"); o != "" {
		if parsed, err := strconv.Atoi(o); err == nil && parsed >= 0 {
			offset = parsed
		}
	}

	q := db.Model(&database.RequestLog{})
	if success := c.Query("success"); success != "" {
		if parsed, err := strconv.ParseBool(success); err == nil {
			q = q.Where("success = ?", parsed)
		}
	}
	if model := c.Query("model"); model != "" {
		q = q.Where("model = ?", model)
	}
	if tokenID := c.Query("token_id"); tokenID != "" {
		q = q.Where("token_id = ?", tokenID)
	}

	if !isStaff {
		q = q.Where("user_sub = ?", user.Sub)
	}

	var total int64
	if err := q.Count(&total).Error; err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to count request logs."})
		return
	}

	var logs []database.RequestLog
	if err := q.Limit(limit).Offset(offset).Order("ts DESC").Find(&logs).Error; err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to query request logs."})
		return
	}

	items := make([]models.RequestLogOut, 0, len(logs))
	for _, l := range logs {
		items = append(items, models.RequestLogOut{
			ID:              l.ID,
			TS:              l.Ts,
			UserSub:         l.UserSub,
			TokenID:         l.TokenID,
			ProviderName:    l.ProviderName,
			Model:           l.Model,
			InboundStyle:    l.InboundStyle,
			UpstreamStyle:   l.UpstreamStyle,
			StatusCode:      l.StatusCode,
			Success:         l.Success,
			LatencyMs:       l.LatencyMs,
			PromptTokens:    l.PromptTokens,
			CompletionTokens: l.CompletionTokens,
			TotalTokens:     l.TotalTokens,
			Stream:          l.Stream,
			Attempts:        l.Attempts,
			Error:           l.Error,
		})
	}

	c.JSON(http.StatusOK, models.Page[models.RequestLogOut]{
		Items:  items,
		Total:  int(total),
		Limit:  limit,
		Offset: offset,
	})
}

func RegisterLogRoutes(router *gin.RouterGroup) {
	logGroup := router.Group("/logs")
	{
		logGroup.GET("/audit", listAuditLogs)
		logGroup.POST("/audit/:id/reveal", revealSensitivePayload)
		logGroup.GET("/requests", listRequestLogs)
	}
}
