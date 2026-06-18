package handlers

import (
	"net/http"
	"strconv"
	"strings"

	"github.com/gin-gonic/gin"

	"github.com/siiway/voidswitch/internal/config"
	"github.com/siiway/voidswitch/internal/core"
	"github.com/siiway/voidswitch/internal/database"
	"github.com/siiway/voidswitch/internal/models"
)

func RegisterProviderAPIRoutes(router *gin.RouterGroup) {
	router.GET("/provider", handleProviderAPIWhoami)
	router.GET("/keys", handleProviderAPIListKeys)
	router.POST("/keys", handleProviderAPIAddKeys)
	router.PATCH("/keys/:id", handleProviderAPIUpdateKey)
	router.DELETE("/keys/:id", handleProviderAPIDeleteKey)
}

func providerAPIAuth(c *gin.Context) *database.Provider {
	auth := c.GetHeader("Authorization")
	xApiKey := c.GetHeader("X-API-Key")
	raw := core.ExtractBearer(auth)
	if raw == "" {
		raw = strings.TrimSpace(xApiKey)
	}
	if raw == "" || !strings.HasPrefix(raw, "vsk-") {
		c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"error": "Missing key-management token."})
		return nil
	}

	hash := core.HashToken(raw)
	db := database.GetDatabase().DB

	var provider database.Provider
	if err := db.Where("key_api_token_hash = ? AND key_api_enabled = ?", hash, true).First(&provider).Error; err != nil {
		c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"error": "Invalid or disabled key-management token."})
		return nil
	}

	if !provider.Enabled {
		c.AbortWithStatusJSON(http.StatusServiceUnavailable, gin.H{"error": "This provider is currently disabled."})
		return nil
	}

	return &provider
}

func handleProviderAPIWhoami(c *gin.Context) {
	provider := providerAPIAuth(c)
	if provider == nil {
		return
	}
	db := database.GetDatabase().DB

	var keyCount, activeKeyCount int64
	db.Model(&database.ApiKey{}).Where("provider_id = ?", provider.ID).Count(&keyCount)
	db.Model(&database.ApiKey{}).Where("provider_id = ? AND status = ?", provider.ID, "active").Count(&activeKeyCount)

	extra := make(map[string]string)
	for k := range provider.ExtraHeaders {
		extra[k] = "***"
	}

	c.JSON(http.StatusOK, gin.H{
		"id":                   provider.ID,
		"name":                 provider.Name,
		"type":                 provider.Type,
		"base_url":             provider.BaseURL,
		"enabled":              provider.Enabled,
		"models":               provider.Models,
		"key_count":            keyCount,
		"active_key_count":     activeKeyCount,
		"key_api_enabled":      false,
		"key_api_token_preview": nil,
		"extra_headers":        extra,
	})
}

func handleProviderAPIListKeys(c *gin.Context) {
	provider := providerAPIAuth(c)
	if provider == nil {
		return
	}

	db := database.GetDatabase().DB
	var keys []database.ApiKey
	db.Where("provider_id = ?", provider.ID).Order("id ASC").Find(&keys)

	out := make([]models.ApiKeyOut, 0, len(keys))
	for _, k := range keys {
		out = append(out, models.ApiKeyOut{
			ID:             k.ID,
			ProviderID:     k.ProviderID,
			KeyPreview:     k.KeyPreview,
			Pool:           k.Pool,
			Status:         k.Status,
			FailedCount:    k.FailedCount,
			Weight:         k.Weight,
			Note:           k.Note,
			Balance:        k.Balance,
			DisabledReason: k.DisabledReason,
			TotalRequests:  k.TotalRequests,
			LastUsedAt:     k.LastUsedAt,
			LastCheckedAt:  k.LastCheckedAt,
			CreatedAt:      k.CreatedAt,
			DisabledSince:  k.DisabledSince,
			AddedBy:        k.AddedBy,
			AddedByName:    k.AddedByName,
		})
	}

	c.JSON(http.StatusOK, out)
}

func handleProviderAPIAddKeys(c *gin.Context) {
	provider := providerAPIAuth(c)
	if provider == nil {
		return
	}

	var body struct {
		Keys   []string `json:"keys"`
		Weight int      `json:"weight"`
		Note   *string  `json:"note"`
		Pool   string   `json:"pool"`
	}
	if err := c.ShouldBindJSON(&body); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid request body."})
		return
	}

	db := database.GetDatabase().DB
	settings := config.Load()

	var created []models.ApiKeyOut
	for _, rawKey := range body.Keys {
		if rawKey == "" {
			continue
		}
		keyHash := core.HashToken(rawKey)
		ciphertext, err := core.EncryptSecret(rawKey, settings.Server.SecretKey)
		if err != nil {
			continue
		}
		preview := rawKey
		if len(preview) > 8 {
			preview = preview[:4] + "\u2026" + preview[len(preview)-4:]
		} else if len(preview) > 2 {
			preview = preview[:1] + "\u2026"
		}

		record := database.ApiKey{
			ProviderID:    provider.ID,
			KeyCiphertext: ciphertext,
			KeyHash:       keyHash,
			KeyPreview:    preview,
			Pool:          body.Pool,
			Weight:        body.Weight,
			Note:          body.Note,
		}
		if err := db.Create(&record).Error; err != nil {
			continue
		}
		created = append(created, models.ApiKeyOut{
			ID:         record.ID,
			ProviderID: record.ProviderID,
			KeyPreview: record.KeyPreview,
			Pool:       record.Pool,
			Status:     record.Status,
			Weight:     record.Weight,
			Note:       record.Note,
			Balance:    record.Balance,
			CreatedAt:  record.CreatedAt,
		})
	}

	c.JSON(http.StatusCreated, created)
}

func handleProviderAPIUpdateKey(c *gin.Context) {
	provider := providerAPIAuth(c)
	if provider == nil {
		return
	}

	keyID, err := strconv.Atoi(c.Param("id"))
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid key ID."})
		return
	}

	var body models.ApiKeyUpdate
	if err := c.ShouldBindJSON(&body); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid request body."})
		return
	}

	db := database.GetDatabase().DB
	var key database.ApiKey
	if err := db.Where("id = ? AND provider_id = ?", keyID, provider.ID).First(&key).Error; err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "Key not found."})
		return
	}

	settings := config.Load()
	changed := false

	if body.Key != nil {
		ciphertext, err := core.EncryptSecret(*body.Key, settings.Server.SecretKey)
		if err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to encrypt key."})
			return
		}
		key.KeyCiphertext = ciphertext
		key.KeyHash = core.HashToken(*body.Key)
		key.KeyPreview = *body.Key
		if len(key.KeyPreview) > 8 {
			key.KeyPreview = key.KeyPreview[:4] + "\u2026" + key.KeyPreview[len(key.KeyPreview)-4:]
		}
		key.FailedCount = 0
		key.DisabledReason = nil
		changed = true
	}
	if body.Status != nil {
		key.Status = *body.Status
		changed = true
	}
	if body.Weight != nil {
		key.Weight = *body.Weight
		changed = true
	}
	if body.Note != nil {
		key.Note = body.Note
		changed = true
	}
	if body.Pool != nil {
		key.Pool = *body.Pool
		changed = true
	}
	if body.Enabled != nil {
		if *body.Enabled {
			key.Status = "active"
			key.FailedCount = 0
			key.DisabledReason = nil
		} else {
			key.Status = "disabled"
		}
		changed = true
	}

	if changed {
		db.Save(&key)
	}

	sub := "provider-key-api:" + provider.Name
	name := "key-api:" + provider.Name
	targetID := strconv.Itoa(keyID)
	targetType := "api_key"
	core.RecordAudit(db, "key.update", &sub, &name, &targetType, &targetID,
		map[string]any{"updated": true}, nil, nil, nil, "admin")

	c.JSON(http.StatusOK, models.ApiKeyOut{
		ID:             key.ID,
		ProviderID:     key.ProviderID,
		KeyPreview:     key.KeyPreview,
		Pool:           key.Pool,
		Status:         key.Status,
		FailedCount:    key.FailedCount,
		Weight:         key.Weight,
		Note:           key.Note,
		Balance:        key.Balance,
		DisabledReason: key.DisabledReason,
		CreatedAt:      key.CreatedAt,
	})
}

func handleProviderAPIDeleteKey(c *gin.Context) {
	provider := providerAPIAuth(c)
	if provider == nil {
		return
	}

	keyID, err := strconv.Atoi(c.Param("id"))
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid key ID."})
		return
	}

	db := database.GetDatabase().DB
	var key database.ApiKey
	if err := db.Where("id = ? AND provider_id = ?", keyID, provider.ID).First(&key).Error; err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "Key not found."})
		return
	}

	db.Delete(&key)

	sub := "provider-key-api:" + provider.Name
	name := "key-api:" + provider.Name
	targetID := strconv.Itoa(keyID)
	targetType := "api_key"
	core.RecordAudit(db, "key.delete", &sub, &name, &targetType, &targetID,
		map[string]any{"key_preview": key.KeyPreview}, nil, nil, nil, "admin")

	c.Status(http.StatusNoContent)
}
