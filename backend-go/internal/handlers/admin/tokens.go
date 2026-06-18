package admin

import (
	"net/http"
	"strconv"

	"github.com/gin-gonic/gin"

	"github.com/siiway/voidswitch/internal/core"
	"github.com/siiway/voidswitch/internal/database"
	"github.com/siiway/voidswitch/internal/models"
)

func listTokens(c *gin.Context) {
	db := database.GetDatabase().DB
	user, ok := getCurrentUserGin(c)
	if !ok || !requireOwnerGin(c, user) {
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

	q := db.Model(&database.VoidToken{})
	userID := c.Query("user_id")
	if userID != "" {
		q = q.Where("user_id = ?", userID)
	}

	var total int64
	if err := q.Count(&total).Error; err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to count tokens."})
		return
	}

	var tokens []database.VoidToken
	if err := q.Preload("User").Limit(limit).Offset(offset).Order("id DESC").Find(&tokens).Error; err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to query tokens."})
		return
	}

	items := make([]models.VoidTokenOut, 0, len(tokens))
	for _, t := range tokens {
		items = append(items, tokenToOut(t))
	}

	c.JSON(http.StatusOK, models.Page[models.VoidTokenOut]{
		Items:  items,
		Total:  int(total),
		Limit:  limit,
		Offset: offset,
	})
}

func createToken(c *gin.Context) {
	db := database.GetDatabase().DB
	user, ok := getCurrentUserGin(c)
	if !ok || !requireOwnerGin(c, user) {
		return
	}

	var body models.VoidTokenCreate
	if err := c.ShouldBindJSON(&body); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid request body."})
		return
	}

	targetUserID := user.ID
	if body.UserID != nil && *body.UserID != 0 {
		targetUserID = *body.UserID
	}

	var targetUser database.User
	if err := db.First(&targetUser, targetUserID).Error; err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "Target user not found."})
		return
	}

	rawToken := core.GenerateVoidToken()
	tokenHash := core.HashToken(rawToken)
	tokenPrefix := rawToken[:len("vs-XXXXXXXX")]

	record := database.VoidToken{
		UserID:        targetUser.ID,
		Name:          body.Name,
		TokenHash:     tokenHash,
		TokenPrefix:   tokenPrefix,
		AllowedModels: body.AllowedModels,
		RpmLimit:      body.RPMLimit,
		DailyQuota:    body.DailyQuota,
		ExpiresAt:     body.ExpiresAt,
	}

	if err := db.Create(&record).Error; err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to create token."})
		return
	}

	name := core.ActorDisplayName(user)
	targetID := strconv.Itoa(record.ID)
	targetType := "void_token"
	core.RecordAudit(db, "token.create", &user.Sub, &name, &targetType, &targetID,
		map[string]any{"name": record.Name, "user_id": record.UserID}, nil, nil, nil, "admin")

	out := tokenToOut(record)
	c.JSON(http.StatusOK, models.VoidTokenWithSecret{
		VoidTokenOut: out,
		Token:        rawToken,
	})
}

func updateToken(c *gin.Context) {
	db := database.GetDatabase().DB
	user, ok := getCurrentUserGin(c)
	if !ok || !requireOwnerGin(c, user) {
		return
	}

	id, err := strconv.Atoi(c.Param("id"))
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid token ID."})
		return
	}

	var existing database.VoidToken
	if err := db.First(&existing, id).Error; err != nil {
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

	c.JSON(http.StatusOK, tokenToOut(existing))
}

func deleteToken(c *gin.Context) {
	db := database.GetDatabase().DB
	user, ok := getCurrentUserGin(c)
	if !ok || !requireOwnerGin(c, user) {
		return
	}

	id, err := strconv.Atoi(c.Param("id"))
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid token ID."})
		return
	}

	var existing database.VoidToken
	if err := db.First(&existing, id).Error; err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "Token not found."})
		return
	}

	if err := db.Delete(&existing).Error; err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to delete token."})
		return
	}

	name := core.ActorDisplayName(user)
	targetID := strconv.Itoa(id)
	targetType := "void_token"
	core.RecordAudit(db, "token.delete", &user.Sub, &name, &targetType, &targetID,
		map[string]any{"name": existing.Name}, nil, nil, nil, "admin")

	c.Status(http.StatusNoContent)
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

func RegisterTokenRoutes(router *gin.RouterGroup) {
	tokenGroup := router.Group("/tokens")
	{
		tokenGroup.GET("", listTokens)
		tokenGroup.POST("", createToken)
		tokenGroup.PATCH("/:id", updateToken)
		tokenGroup.DELETE("/:id", deleteToken)
	}
}
