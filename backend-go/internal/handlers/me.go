package handlers

import (
	"net/http"
	"strconv"
	"github.com/gin-gonic/gin"

	"github.com/siiway/voidswitch/internal/config"
	"github.com/siiway/voidswitch/internal/core"
	"github.com/siiway/voidswitch/internal/database"
	"github.com/siiway/voidswitch/internal/models"
)

func RegisterMeRoutes(router *gin.RouterGroup) {
	router.GET("", handleMeProfile)
	router.GET("/tokens", handleMeListTokens)
	router.POST("/tokens", handleMeCreateToken)
	router.PATCH("/tokens/:id", handleMeUpdateToken)
	router.POST("/tokens/:id/rotate", handleMeRotateToken)
	router.DELETE("/tokens/:id", handleMeDeleteToken)
	router.GET("/usage", handleMeUsage)
}

func handleMeProfile(c *gin.Context) {
	user, err := getCurrentUser(c)
	if err != nil {
		c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"error": err.Error()})
		return
	}
	c.JSON(http.StatusOK, userOut(user))
}

func handleMeListTokens(c *gin.Context) {
	user, err := getCurrentUser(c)
	if err != nil {
		c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"error": err.Error()})
		return
	}

	db := database.GetDatabase().DB
	var tokens []database.VoidToken
	if err := db.Preload("User").Where("user_id = ?", user.ID).Order("id DESC").Find(&tokens).Error; err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to query tokens."})
		return
	}

	items := make([]models.VoidTokenOut, 0, len(tokens))
	for _, t := range tokens {
		items = append(items, tokenToOut(t))
	}

	c.JSON(http.StatusOK, items)
}

func handleMeCreateToken(c *gin.Context) {
	user, err := getCurrentUser(c)
	if err != nil {
		c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"error": err.Error()})
		return
	}

	var body models.VoidTokenCreate
	if err := c.ShouldBindJSON(&body); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid request body."})
		return
	}

	rawToken := core.GenerateVoidToken()
	tokenHash := core.HashToken(rawToken)
	tokenPrefix := rawToken[:len("vs-XXXXXXXX")]

	record := database.VoidToken{
		UserID:        user.ID,
		Name:          body.Name,
		TokenHash:     tokenHash,
		TokenPrefix:   tokenPrefix,
		AllowedModels: body.AllowedModels,
		RpmLimit:      body.RPMLimit,
		DailyQuota:    body.DailyQuota,
		ExpiresAt:     body.ExpiresAt,
	}

	db := database.GetDatabase().DB
	if err := db.Create(&record).Error; err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to create token."})
		return
	}

	settings := config.Load()
	ip := c.ClientIP()
	actorSub := user.Sub
	actorName := actorLabel(user)
	targetID := strconv.Itoa(record.ID)
	targetType := "void_token"
	core.RecordAudit(db, "token.create", &actorSub, &actorName, &targetType, &targetID,
		map[string]any{"name": record.Name}, &ip, nil, &settings.Server.SecretKey, "self")

	out := tokenToOut(record)
	c.JSON(http.StatusOK, models.VoidTokenWithSecret{
		VoidTokenOut: out,
		Token:        rawToken,
	})
}

func handleMeUpdateToken(c *gin.Context) {
	user, err := getCurrentUser(c)
	if err != nil {
		c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"error": err.Error()})
		return
	}

	id, err := strconv.Atoi(c.Param("id"))
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid token ID."})
		return
	}

	db := database.GetDatabase().DB
	var existing database.VoidToken
	if err := db.Where("id = ? AND user_id = ?", id, user.ID).First(&existing).Error; err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "Token not found."})
		return
	}

	var body models.VoidTokenUpdate
	if err := c.ShouldBindJSON(&body); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid request body."})
		return
	}

	if body.Name != nil {
		existing.Name = *body.Name
	}
	if body.Enabled != nil {
		existing.Enabled = *body.Enabled
	}
	if body.AllowedModels != nil {
		existing.AllowedModels = *body.AllowedModels
	}
	if body.RPMLimit != nil {
		existing.RpmLimit = *body.RPMLimit
	}
	if body.DailyQuota != nil {
		existing.DailyQuota = *body.DailyQuota
	}
	if body.ExpiresAt != nil {
		existing.ExpiresAt = body.ExpiresAt
	}

	if err := db.Save(&existing).Error; err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to update token."})
		return
	}

	settings := config.Load()
	ip := c.ClientIP()
	actorSub := user.Sub
	actorName := actorLabel(user)
	targetID := strconv.Itoa(existing.ID)
	targetType := "void_token"
	core.RecordAudit(db, "token.update", &actorSub, &actorName, &targetType, &targetID,
		map[string]any{"name": existing.Name}, &ip, nil, &settings.Server.SecretKey, "self")

	c.JSON(http.StatusOK, tokenToOut(existing))
}

func handleMeRotateToken(c *gin.Context) {
	user, err := getCurrentUser(c)
	if err != nil {
		c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"error": err.Error()})
		return
	}

	id, err := strconv.Atoi(c.Param("id"))
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid token ID."})
		return
	}

	db := database.GetDatabase().DB
	var existing database.VoidToken
	if err := db.Where("id = ? AND user_id = ?", id, user.ID).First(&existing).Error; err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "Token not found."})
		return
	}

	rawToken := core.GenerateVoidToken()
	existing.TokenHash = core.HashToken(rawToken)
	existing.TokenPrefix = rawToken[:len("vs-XXXXXXXX")]

	if err := db.Save(&existing).Error; err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to rotate token."})
		return
	}

	settings := config.Load()
	ip := c.ClientIP()
	actorSub := user.Sub
	actorName := actorLabel(user)
	targetID := strconv.Itoa(existing.ID)
	targetType := "void_token"
	core.RecordAudit(db, "token.rotate", &actorSub, &actorName, &targetType, &targetID,
		map[string]any{"name": existing.Name}, &ip, nil, &settings.Server.SecretKey, "self")

	out := tokenToOut(existing)
	c.JSON(http.StatusOK, models.VoidTokenWithSecret{
		VoidTokenOut: out,
		Token:        rawToken,
	})
}

func handleMeDeleteToken(c *gin.Context) {
	user, err := getCurrentUser(c)
	if err != nil {
		c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"error": err.Error()})
		return
	}

	id, err := strconv.Atoi(c.Param("id"))
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid token ID."})
		return
	}

	db := database.GetDatabase().DB
	var existing database.VoidToken
	if err := db.Where("id = ? AND user_id = ?", id, user.ID).First(&existing).Error; err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "Token not found."})
		return
	}

	if err := db.Delete(&existing).Error; err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to delete token."})
		return
	}

	settings := config.Load()
	ip := c.ClientIP()
	actorSub := user.Sub
	actorName := actorLabel(user)
	targetID := strconv.Itoa(id)
	targetType := "void_token"
	core.RecordAudit(db, "token.delete", &actorSub, &actorName, &targetType, &targetID,
		map[string]any{"name": existing.Name}, &ip, nil, &settings.Server.SecretKey, "self")

	c.Status(http.StatusNoContent)
}

func handleMeUsage(c *gin.Context) {
	user, err := getCurrentUser(c)
	if err != nil {
		c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"error": err.Error()})
		return
	}

	db := database.GetDatabase().DB

	var tokenIDs []int
	db.Model(&database.VoidToken{}).Where("user_id = ?", user.ID).Pluck("id", &tokenIDs)

	var totals models.UsageTotals
	row := db.Model(&database.RequestLog{}).
		Where("token_id IN ?", tokenIDs).
		Select("COALESCE(COUNT(*), 0) as requests, COALESCE(SUM(CASE WHEN success THEN 1 ELSE 0 END), 0) as success, COALESCE(SUM(CASE WHEN NOT success THEN 1 ELSE 0 END), 0) as failures, COALESCE(SUM(prompt_tokens), 0) as prompt_tokens, COALESCE(SUM(completion_tokens), 0) as completion_tokens, COALESCE(SUM(total_tokens), 0) as total_tokens").
		Scan(&totals)

	if row.Error != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to query usage."})
		return
	}

	c.JSON(http.StatusOK, totals)
}

func tokenToOut(t database.VoidToken) models.VoidTokenOut {
	var username *string
	if t.User != nil {
		username = t.User.Username
	}
	return models.VoidTokenOut{
		ID:            t.ID,
		UserID:        t.UserID,
		Username:      username,
		Name:          t.Name,
		TokenPrefix:   t.TokenPrefix,
		Enabled:       t.Enabled,
		AllowedModels: t.AllowedModels,
		RPMLimit:      t.RpmLimit,
		DailyQuota:    t.DailyQuota,
		TotalRequests: t.TotalRequests,
		TotalTokens:   t.TotalTokens,
		LastUsedAt:    t.LastUsedAt,
		ExpiresAt:     t.ExpiresAt,
		CreatedAt:     t.CreatedAt,
	}
}


