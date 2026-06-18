package admin

import (
	"encoding/json"
	"net/http"
	"strconv"
	"time"

	"github.com/gin-gonic/gin"

	"github.com/siiway/voidswitch/internal/config"
	"github.com/siiway/voidswitch/internal/core"
	"github.com/siiway/voidswitch/internal/database"
	"github.com/siiway/voidswitch/internal/models"
	"github.com/siiway/voidswitch/internal/services"
	"github.com/siiway/voidswitch/internal/services/providers"
)

func listKeys(c *gin.Context) {
	db := database.GetDatabase().DB
	user, ok := getCurrentUserGin(c)
	if !ok || !requireStaffGin(c, user) {
		return
	}

	pid, err := strconv.Atoi(c.Param("pid"))
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid provider ID."})
		return
	}

	var provider database.Provider
	if err := db.First(&provider, pid).Error; err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "Provider not found."})
		return
	}

	var keys []database.ApiKey
	if err := db.Where("provider_id = ?", pid).Find(&keys).Error; err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to query keys."})
		return
	}

	result := make([]models.ApiKeyOut, 0, len(keys))
	for _, k := range keys {
		result = append(result, keyToOut(k))
	}

	c.JSON(http.StatusOK, result)
}

func batchAddKeys(c *gin.Context) {
	db := database.GetDatabase().DB
	user, ok := getCurrentUserGin(c)
	if !ok || !requireStaffGin(c, user) {
		return
	}

	pid, err := strconv.Atoi(c.Param("pid"))
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid provider ID."})
		return
	}

	var provider database.Provider
	if err := db.First(&provider, pid).Error; err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "Provider not found."})
		return
	}

	var body models.ApiKeyCreate
	if err := c.ShouldBindJSON(&body); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid request body."})
		return
	}

	if len(body.Keys) == 0 {
		c.JSON(http.StatusBadRequest, gin.H{"error": "No keys provided."})
		return
	}

	settings := config.Load()
	name := core.ActorDisplayName(user)
	var created []models.ApiKeyOut
	var sensitivePayloads []map[string]any

	for _, rawKey := range body.Keys {
		if rawKey == "" {
			continue
		}

		keyHash := core.HashToken(rawKey)
		keyPreview := keyPreview(rawKey)
		ciphertext, err := core.EncryptSecret(rawKey, settings.Server.SecretKey)
		if err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to encrypt key."})
			return
		}

		record := database.ApiKey{
			ProviderID:    provider.ID,
			KeyCiphertext: ciphertext,
			KeyHash:       keyHash,
			KeyPreview:    keyPreview,
			Pool:          body.Pool,
			Weight:        body.Weight,
			Note:          body.Note,
			AddedBy:       &user.ID,
			AddedByName:   &name,
		}

		if err := db.Create(&record).Error; err != nil {
			continue
		}

		created = append(created, keyToOut(record))
		sensitivePayloads = append(sensitivePayloads, map[string]any{
			"key_preview": keyPreview,
		})
	}

	targetID := strconv.Itoa(provider.ID)
	targetType := "provider"
	sensitive := map[string]any{
		"keys_added": len(created),
		"previews":   sensitivePayloads,
	}
	core.RecordAudit(db, "key.create", &user.Sub, &name, &targetType, &targetID,
		map[string]any{"count": len(created)}, nil, sensitive, &settings.Server.SecretKey, "admin")

	c.JSON(http.StatusOK, created)
}

func refreshAllBalances(c *gin.Context) {
	db := database.GetDatabase().DB
	user, ok := getCurrentUserGin(c)
	if !ok || !requireStaffGin(c, user) {
		return
	}

	pid, err := strconv.Atoi(c.Param("pid"))
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid provider ID."})
		return
	}

	var provider database.Provider
	if err := db.First(&provider, pid).Error; err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "Provider not found."})
		return
	}

	var keys []database.ApiKey
	if err := db.Where("provider_id = ?", pid).Find(&keys).Error; err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to query keys."})
		return
	}

	settings := config.Load()
	adapter := providers.GetAdapter(&provider)
	route := services.NewRoute(nil, nil)
	client, err := services.GetPool().Get(route, 15*time.Second, 30*time.Second)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to create HTTP client."})
		return
	}

	ratePerSec := services.GetInt("balance_scan_rate_per_second", 5)
	throttle := time.Second / time.Duration(ratePerSec)
	if throttle < time.Millisecond*50 {
		throttle = time.Millisecond * 50
	}

	updated := 0
	for i := range keys {
		available, err := services.RefreshKeyBalance(&keys[i], &provider, client, settings, true, adapter)
		if err != nil {
			continue
		}
		if available || !available {
			if err := db.Save(&keys[i]).Error; err != nil {
				continue
			}
			updated++
		}
		if i < len(keys)-1 {
			time.Sleep(throttle)
		}
	}

	c.JSON(http.StatusOK, gin.H{"updated": updated})
}

func bulkCleanup(c *gin.Context) {
	db := database.GetDatabase().DB
	user, ok := getCurrentUserGin(c)
	if !ok || !requireStaffGin(c, user) {
		return
	}

	pid, err := strconv.Atoi(c.Param("pid"))
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid provider ID."})
		return
	}

	var body models.ApiKeyCleanup
	if err := c.ShouldBindJSON(&body); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid request body."})
		return
	}

	cutoff := time.Now().Add(-time.Duration(body.MinDays) * 24 * time.Hour)
	result := db.Where("provider_id = ? AND status = ? AND updated_at < ?", pid, body.Target, cutoff).Delete(&database.ApiKey{})
	if result.Error != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to delete keys."})
		return
	}

	c.JSON(http.StatusOK, models.ApiKeyCleanupResult{Deleted: int(result.RowsAffected)})
}

func oauthStart(c *gin.Context) {
	db := database.GetDatabase().DB
	user, ok := getCurrentUserGin(c)
	if !ok || !requireStaffGin(c, user) {
		return
	}

	pid, err := strconv.Atoi(c.Param("pid"))
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid provider ID."})
		return
	}

	var provider database.Provider
	if err := db.First(&provider, pid).Error; err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "Provider not found."})
		return
	}

	authorizeURL, state := services.BeginLogin(provider.ID)
	c.JSON(http.StatusOK, models.ClaudeOAuthStart{
		AuthorizeURL: authorizeURL,
		State:        state,
	})
}

func oauthComplete(c *gin.Context) {
	db := database.GetDatabase().DB
	user, ok := getCurrentUserGin(c)
	if !ok || !requireStaffGin(c, user) {
		return
	}

	pid, err := strconv.Atoi(c.Param("pid"))
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid provider ID."})
		return
	}

	var provider database.Provider
	if err := db.First(&provider, pid).Error; err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "Provider not found."})
		return
	}

	var body models.ClaudeOAuthComplete
	if err := c.ShouldBindJSON(&body); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid request body."})
		return
	}

	bundle, err := services.CompleteLogin(body.Code, body.State, provider.ID, db)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}

	bundleJSON, err := json.Marshal(bundle)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to serialize OAuth bundle."})
		return
	}

	settings := config.Load()
	ciphertext, err := core.EncryptSecret(string(bundleJSON), settings.Server.SecretKey)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to encrypt OAuth bundle."})
		return
	}

	name := core.ActorDisplayName(user)
	note := "claude-oauth"
	if body.Note != nil {
		note = *body.Note
	}

	record := database.ApiKey{
		ProviderID:    provider.ID,
		KeyCiphertext: ciphertext,
		KeyHash:       core.HashToken(ciphertext),
		KeyPreview:    "claude-oauth\u2026",
		Pool:          "",
		Weight:        1,
		Note:          &note,
		AddedBy:       &user.ID,
		AddedByName:   &name,
	}

	if err := db.Create(&record).Error; err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to store OAuth key."})
		return
	}

	targetID := strconv.Itoa(provider.ID)
	targetType := "provider"
	core.RecordAudit(db, "key.create_oauth", &user.Sub, &name, &targetType, &targetID,
		map[string]any{"key_id": record.ID}, nil, nil, nil, "admin")

	c.JSON(http.StatusOK, keyToOut(record))
}

func updateKey(c *gin.Context) {
	db := database.GetDatabase().DB
	user, ok := getCurrentUserGin(c)
	if !ok || !requireStaffGin(c, user) {
		return
	}

	pid, err := strconv.Atoi(c.Param("pid"))
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid provider ID."})
		return
	}

	kid, err := strconv.Atoi(c.Param("kid"))
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid key ID."})
		return
	}

	var existing database.ApiKey
	if err := db.Where("id = ? AND provider_id = ?", kid, pid).First(&existing).Error; err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "Key not found."})
		return
	}

	var body models.ApiKeyUpdate
	if err := c.ShouldBindJSON(&body); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid request body."})
		return
	}

	changes := make(map[string]any)

	if body.Key != nil {
		settings := config.Load()
		ciphertext, err := core.EncryptSecret(*body.Key, settings.Server.SecretKey)
		if err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to encrypt key."})
			return
		}
		changes["key"] = map[string]any{"updated": true}
		existing.KeyCiphertext = ciphertext
		existing.KeyHash = core.HashToken(*body.Key)
		existing.KeyPreview = keyPreview(*body.Key)
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
	if body.Pool != nil {
		changes["pool"] = map[string]any{"old": existing.Pool, "new": *body.Pool}
		existing.Pool = *body.Pool
	}
	if body.Enabled != nil {
		changes["enabled"] = map[string]any{"old": existing.Status, "new": *body.Enabled}
		if *body.Enabled {
			existing.Status = "active"
		} else {
			existing.Status = "disabled"
		}
	}
	if body.AccessToken != nil || body.RefreshToken != nil || body.ExpiresAt != nil {
		settings := config.Load()
		// Rebuild the OAuth credential bundle
		bundle := map[string]any{}
		if body.AccessToken != nil {
			bundle["access_token"] = *body.AccessToken
		}
		if body.RefreshToken != nil {
			bundle["refresh_token"] = *body.RefreshToken
		}
		if body.ExpiresAt != nil {
			bundle["expires_at"] = *body.ExpiresAt
		}
		bundleJSON, err := json.Marshal(bundle)
		if err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to marshal OAuth bundle."})
			return
		}
		ciphertext, err := core.EncryptSecret(string(bundleJSON), settings.Server.SecretKey)
		if err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to encrypt OAuth bundle."})
			return
		}
		changes["oauth_bundle"] = map[string]any{"updated": true}
		existing.KeyCiphertext = ciphertext
		existing.KeyHash = ""
		existing.KeyPreview = ""
	}

	if err := db.Save(&existing).Error; err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to update key."})
		return
	}

	cname := core.ActorDisplayName(user)
	targetID := strconv.Itoa(existing.ID)
	targetType := "api_key"
	core.RecordAudit(db, "key.update", &user.Sub, &cname, &targetType, &targetID, changes, nil, nil, nil, "admin")

	c.JSON(http.StatusOK, keyToOut(existing))
}

func deleteKey(c *gin.Context) {
	db := database.GetDatabase().DB
	user, ok := getCurrentUserGin(c)
	if !ok || !requireStaffGin(c, user) {
		return
	}

	pid, err := strconv.Atoi(c.Param("pid"))
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid provider ID."})
		return
	}

	kid, err := strconv.Atoi(c.Param("kid"))
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid key ID."})
		return
	}

	var existing database.ApiKey
	if err := db.Where("id = ? AND provider_id = ?", kid, pid).First(&existing).Error; err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "Key not found."})
		return
	}

	cname := core.ActorDisplayName(user)
	targetID := strconv.Itoa(kid)
	targetType := "api_key"
	sensitive := map[string]any{
		"key_preview": existing.KeyPreview,
	}
	settings := config.Load()
	core.RecordAudit(db, "key.delete", &user.Sub, &cname, &targetType, &targetID,
		map[string]any{"provider_id": pid}, nil, sensitive, &settings.Server.SecretKey, "admin")

	if err := db.Delete(&existing).Error; err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to delete key."})
		return
	}

	c.Status(http.StatusNoContent)
}

func refreshSingleBalance(c *gin.Context) {
	db := database.GetDatabase().DB
	user, ok := getCurrentUserGin(c)
	if !ok || !requireStaffGin(c, user) {
		return
	}

	pid, err := strconv.Atoi(c.Param("pid"))
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid provider ID."})
		return
	}

	kid, err := strconv.Atoi(c.Param("kid"))
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid key ID."})
		return
	}

	var key database.ApiKey
	if err := db.Where("id = ? AND provider_id = ?", kid, pid).First(&key).Error; err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "Key not found."})
		return
	}

	var prov database.Provider
	if err := db.First(&prov, pid).Error; err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "Provider not found."})
		return
	}

	settings := config.Load()
	adapter := providers.GetAdapter(&prov)
	route := services.NewRoute(nil, nil)
	client, err := services.GetPool().Get(route, 15*time.Second, 30*time.Second)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to create HTTP client."})
		return
	}

	available, err := services.RefreshKeyBalance(&key, &prov, client, settings, true, adapter)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}

	if err := db.Save(&key).Error; err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to save key balance."})
		return
	}

	_ = available
	c.JSON(http.StatusOK, keyToOut(key))
}

func revealKey(c *gin.Context) {
	db := database.GetDatabase().DB
	user, ok := getCurrentUserGin(c)
	if !ok || !requireOwnerGin(c, user) {
		return
	}

	kid, err := strconv.Atoi(c.Param("kid"))
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid key ID."})
		return
	}

	var key database.ApiKey
	if err := db.First(&key, kid).Error; err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "Key not found."})
		return
	}

	settings := config.Load()
	plaintext, _ := core.DecryptSecret(key.KeyCiphertext, settings.Server.SecretKey)

	cname := core.ActorDisplayName(user)
	targetID := strconv.Itoa(kid)
	targetType := "api_key"
	core.RecordAudit(db, "key.reveal", &user.Sub, &cname, &targetType, &targetID,
		map[string]any{"key_preview": key.KeyPreview}, nil, nil, nil, "admin")

	c.JSON(http.StatusOK, gin.H{"key": plaintext})
}

func keyToOut(k database.ApiKey) models.ApiKeyOut {
	return models.ApiKeyOut{
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
	}
}

func keyPreview(raw string) string {
	if len(raw) <= 4 {
		return raw[:1] + "\u2026"
	}
	return raw[:4] + "\u2026"
}

func RegisterKeyRoutes(router *gin.RouterGroup) {
	keysGroup := router.Group("/providers/:pid/keys")
	{
		keysGroup.GET("", listKeys)
		keysGroup.POST("", batchAddKeys)
		keysGroup.POST("/refresh-balance", refreshAllBalances)
		keysGroup.POST("/cleanup", bulkCleanup)
		keysGroup.POST("/oauth/start", oauthStart)
		keysGroup.POST("/oauth/complete", oauthComplete)
		keysGroup.PATCH("/:kid", updateKey)
		keysGroup.DELETE("/:kid", deleteKey)
		keysGroup.POST("/:kid/refresh-balance", refreshSingleBalance)
	}
	router.POST("/keys/:kid/reveal", revealKey)
}
