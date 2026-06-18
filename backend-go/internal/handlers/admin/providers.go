package admin

import (
	"encoding/json"
	"fmt"
	"io"
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

func getCurrentUserGin(c *gin.Context) (*database.User, bool) {
	user := core.GetUserFromContext(c)
	if user == nil {
		c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"error": "Authentication required."})
		return nil, false
	}
	return user, true
}

func requireStaffGin(c *gin.Context, user *database.User) bool {
	if !core.StaffRolesSet[user.Role] {
		c.AbortWithStatusJSON(http.StatusForbidden, gin.H{"error": "Admin privileges required."})
		return false
	}
	return true
}

func requireOwnerGin(c *gin.Context, user *database.User) bool {
	if !core.OwnerRolesSet[user.Role] {
		c.AbortWithStatusJSON(http.StatusForbidden, gin.H{"error": "Owner privileges required."})
		return false
	}
	return true
}

func providerToOut(p database.Provider) models.ProviderOut {
	out := models.ProviderOut{
		ID:                        p.ID,
		Name:                      p.Name,
		Type:                      p.Type,
		BaseURL:                   p.BaseURL,
		Enabled:                   p.Enabled,
		Priority:                  p.Priority,
		Weight:                    p.Weight,
		Models:                    p.Models,
		BalanceURL:                p.BalanceURL,
		TimeoutSeconds:            p.TimeoutSeconds,
		DropOpenCodeIdentityBlock: p.DropOpenCodeIdentityBlock,
		ProxyMode:                 p.ProxyMode,
		AddedBy:                   p.AddedBy,
		AddedByName:               p.AddedByName,
		CreatedAt:                 p.CreatedAt,
		UpdatedAt:                 p.UpdatedAt,
		ModelMap:                  anyMapToStringMap(p.ModelMap),
		ExtraHeaders:              anyMapToStringMap(p.ExtraHeaders),
		ProxyIDs:                  anySliceToIntSlice(p.ProxyIDs),
		ModelRoutes:               anySliceToModelRoutes(p.ModelRoutes),
	}
	return out
}

func anyMapToStringMap(m map[string]any) map[string]string {
	result := make(map[string]string, len(m))
	for k, v := range m {
		result[k] = fmt.Sprintf("%v", v)
	}
	return result
}

func anySliceToIntSlice(s []any) []int {
	result := make([]int, 0, len(s))
	for _, v := range s {
		switch id := v.(type) {
		case float64:
			result = append(result, int(id))
		case int:
			result = append(result, id)
		case int64:
			result = append(result, int(id))
		}
	}
	return result
}

func anySliceToModelRoutes(s []any) []models.ModelRoute {
	result := make([]models.ModelRoute, 0, len(s))
	for _, v := range s {
		m, ok := v.(map[string]any)
		if !ok {
			continue
		}
		route := models.ModelRoute{}
		if a, ok := m["alias"].(string); ok {
			route.Alias = a
		}
		if u, ok := m["upstream"].(string); ok {
			route.Upstream = u
		}
		if p, ok := m["pool"].(string); ok {
			route.Pool = p
		}
		result = append(result, route)
	}
	return result
}

func stringMapToAnyMap(m map[string]string) map[string]any {
	result := make(map[string]any, len(m))
	for k, v := range m {
		result[k] = v
	}
	return result
}

func intSliceToAnySlice(s []int) []any {
	result := make([]any, len(s))
	for i, v := range s {
		result[i] = v
	}
	return result
}

func modelRoutesToAnySlice(s []models.ModelRoute) []any {
	result := make([]any, len(s))
	for i, v := range s {
		result[i] = map[string]any{
			"alias":    v.Alias,
			"upstream": v.Upstream,
			"pool":     v.Pool,
		}
	}
	return result
}

func listProviders(c *gin.Context) {
	db := database.GetDatabase().DB
	user, ok := getCurrentUserGin(c)
	if !ok || !requireStaffGin(c, user) {
		return
	}

	var provs []database.Provider
	if err := db.Find(&provs).Error; err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to query providers."})
		return
	}

	result := make([]models.ProviderOut, 0, len(provs))
	for _, p := range provs {
		out := providerToOut(p)

		var keyCount int64
		db.Model(&database.ApiKey{}).Where("provider_id = ?", p.ID).Count(&keyCount)
		out.KeyCount = int(keyCount)

		var activeKeyCount int64
		db.Model(&database.ApiKey{}).Where("provider_id = ? AND status = ?", p.ID, "active").Count(&activeKeyCount)
		out.ActiveKeyCount = int(activeKeyCount)

		adapter := providers.GetAdapter(&p)
		out.SupportsBalance = adapter.GetBalanceURL() != ""

		result = append(result, out)
	}

	c.JSON(http.StatusOK, result)
}

func createProvider(c *gin.Context) {
	db := database.GetDatabase().DB
	user, ok := getCurrentUserGin(c)
	if !ok || !requireStaffGin(c, user) {
		return
	}

	var body models.ProviderCreate
	if err := c.ShouldBindJSON(&body); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid request body."})
		return
	}

	name := core.ActorDisplayName(user)
	record := database.Provider{
		Name:                      body.Name,
		Type:                      body.Type,
		BaseURL:                   body.BaseURL,
		Priority:                  body.Priority,
		Weight:                    body.Weight,
		Models:                    body.Models,
		ModelMap:                  stringMapToAnyMap(body.ModelMap),
		BalanceURL:                body.BalanceURL,
		ExtraHeaders:              stringMapToAnyMap(body.ExtraHeaders),
		TimeoutSeconds:            body.TimeoutSeconds,
		ProxyMode:                 body.ProxyMode,
		ProxyIDs:                  intSliceToAnySlice(body.ProxyIDs),
		ModelRoutes:               modelRoutesToAnySlice(body.ModelRoutes),
		AddedBy:                   &user.ID,
		AddedByName:               &name,
	}
	if body.Enabled != nil {
		record.Enabled = *body.Enabled
	}
	if body.DropOpenCodeIdentityBlock != nil {
		record.DropOpenCodeIdentityBlock = *body.DropOpenCodeIdentityBlock
	}

	if err := db.Create(&record).Error; err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to create provider."})
		return
	}

	targetID := strconv.Itoa(record.ID)
	targetType := "provider"
	core.RecordAudit(db, "provider.create", &user.Sub, &name, &targetType, &targetID,
		map[string]any{"name": record.Name, "type": record.Type}, nil, nil, nil, "admin")

	c.JSON(http.StatusOK, providerToOut(record))
}

func updateProvider(c *gin.Context) {
	db := database.GetDatabase().DB
	user, ok := getCurrentUserGin(c)
	if !ok || !requireStaffGin(c, user) {
		return
	}

	id, err := strconv.Atoi(c.Param("id"))
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid provider ID."})
		return
	}

	var existing database.Provider
	if err := db.First(&existing, id).Error; err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "Provider not found."})
		return
	}

	var body models.ProviderUpdate
	if err := c.ShouldBindJSON(&body); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid request body."})
		return
	}

	changes := make(map[string]any)

	if body.Name != nil {
		changes["name"] = map[string]any{"old": existing.Name, "new": *body.Name}
		existing.Name = *body.Name
	}
	if body.Type != nil {
		changes["type"] = map[string]any{"old": existing.Type, "new": *body.Type}
		existing.Type = *body.Type
	}
	if body.BaseURL != nil {
		changes["base_url"] = map[string]any{"old": existing.BaseURL, "new": *body.BaseURL}
		existing.BaseURL = *body.BaseURL
	}
	if body.Enabled != nil {
		changes["enabled"] = map[string]any{"old": existing.Enabled, "new": *body.Enabled}
		existing.Enabled = *body.Enabled
	}
	if body.Priority != nil {
		changes["priority"] = map[string]any{"old": existing.Priority, "new": *body.Priority}
		existing.Priority = *body.Priority
	}
	if body.Weight != nil {
		changes["weight"] = map[string]any{"old": existing.Weight, "new": *body.Weight}
		existing.Weight = *body.Weight
	}
	if body.Models != nil {
		changes["models"] = map[string]any{"old": existing.Models, "new": *body.Models}
		existing.Models = *body.Models
	}
	if body.ModelMap != nil {
		changes["model_map"] = map[string]any{"old": existing.ModelMap, "new": *body.ModelMap}
		existing.ModelMap = stringMapToAnyMap(*body.ModelMap)
	}
	if body.BalanceURL != nil {
		changes["balance_url"] = map[string]any{"old": existing.BalanceURL, "new": *body.BalanceURL}
		existing.BalanceURL = body.BalanceURL
	}
	if body.ExtraHeaders != nil {
		changes["extra_headers"] = map[string]any{"old": existing.ExtraHeaders, "new": *body.ExtraHeaders}
		existing.ExtraHeaders = stringMapToAnyMap(*body.ExtraHeaders)
	}
	if body.TimeoutSeconds != nil {
		changes["timeout_seconds"] = map[string]any{"old": existing.TimeoutSeconds, "new": *body.TimeoutSeconds}
		existing.TimeoutSeconds = *body.TimeoutSeconds
	}
	if body.DropOpenCodeIdentityBlock != nil {
		changes["drop_opencode_identity_block"] = map[string]any{"old": existing.DropOpenCodeIdentityBlock, "new": *body.DropOpenCodeIdentityBlock}
		existing.DropOpenCodeIdentityBlock = *body.DropOpenCodeIdentityBlock
	}
	if body.ProxyMode != nil {
		changes["proxy_mode"] = map[string]any{"old": existing.ProxyMode, "new": *body.ProxyMode}
		existing.ProxyMode = *body.ProxyMode
	}
	if body.ProxyIDs != nil {
		changes["proxy_ids"] = map[string]any{"old": existing.ProxyIDs, "new": *body.ProxyIDs}
		existing.ProxyIDs = intSliceToAnySlice(*body.ProxyIDs)
	}
	if body.ModelRoutes != nil {
		changes["model_routes"] = map[string]any{"old": existing.ModelRoutes, "new": *body.ModelRoutes}
		existing.ModelRoutes = modelRoutesToAnySlice(*body.ModelRoutes)
	}

	if err := db.Save(&existing).Error; err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to update provider."})
		return
	}

	cname := core.ActorDisplayName(user)
	targetID := strconv.Itoa(existing.ID)
	targetType := "provider"
	core.RecordAudit(db, "provider.update", &user.Sub, &cname, &targetType, &targetID, changes, nil, nil, nil, "admin")

	c.JSON(http.StatusOK, providerToOut(existing))
}

func deleteProvider(c *gin.Context) {
	db := database.GetDatabase().DB
	user, ok := getCurrentUserGin(c)
	if !ok || !requireOwnerGin(c, user) {
		return
	}

	id, err := strconv.Atoi(c.Param("id"))
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid provider ID."})
		return
	}

	var existing database.Provider
	if err := db.First(&existing, id).Error; err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "Provider not found."})
		return
	}

	if err := db.Delete(&existing).Error; err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to delete provider."})
		return
	}

	cname := core.ActorDisplayName(user)
	targetID := strconv.Itoa(id)
	targetType := "provider"
	core.RecordAudit(db, "provider.delete", &user.Sub, &cname, &targetType, &targetID,
		map[string]any{"name": existing.Name}, nil, nil, nil, "admin")

	c.Status(http.StatusNoContent)
}

func catalogTypes(c *gin.Context) {
	user, ok := getCurrentUserGin(c)
	if !ok || !requireStaffGin(c, user) {
		return
	}

	c.JSON(http.StatusOK, providers.AdapterCatalog())
}

func fetchModels(c *gin.Context) {
	db := database.GetDatabase().DB
	user, ok := getCurrentUserGin(c)
	if !ok || !requireStaffGin(c, user) {
		return
	}

	var body struct {
		ProviderID int `json:"provider_id"`
	}
	if err := c.ShouldBindJSON(&body); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid request body."})
		return
	}

	var prov database.Provider
	if err := db.First(&prov, body.ProviderID).Error; err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "Provider not found."})
		return
	}

	adapter := providers.GetAdapter(&prov)

	var key database.ApiKey
	if err := db.Where("provider_id = ? AND status = ?", prov.ID, "active").First(&key).Error; err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "No active key found for this provider."})
		return
	}

	settings := config.Load()
	plaintext, _ := core.DecryptSecret(key.KeyCiphertext, settings.Server.SecretKey)

	route := services.NewRoute(nil, nil)
	client, err := services.GetPool().Get(route, 15*time.Second, 30*time.Second)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to create HTTP client."})
		return
	}

	req, err := http.NewRequest("GET", adapter.ModelsURL(), nil)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to build request."})
		return
	}

	headers := adapter.Headers(plaintext, nil)
	for k, v := range headers {
		req.Header.Set(k, v)
	}

	resp, err := client.Do(req)
	if err != nil {
		c.JSON(http.StatusBadGateway, gin.H{"error": fmt.Sprintf("Upstream request failed: %v", err)})
		return
	}
	defer resp.Body.Close()

	respBody, err := io.ReadAll(resp.Body)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to read upstream response."})
		return
	}

	var modelsList any
	if err := json.Unmarshal(respBody, &modelsList); err != nil {
		c.Data(resp.StatusCode, "application/json", respBody)
		return
	}

	c.JSON(resp.StatusCode, modelsList)
}

func RegisterProviderRoutes(router *gin.RouterGroup) {
	providersGroup := router.Group("/providers")
	{
		providersGroup.GET("", listProviders)
		providersGroup.POST("", createProvider)
		providersGroup.GET("/catalog/types", catalogTypes)
		providersGroup.POST("/fetch-models", fetchModels)
		providersGroup.PATCH("/:id", updateProvider)
		providersGroup.DELETE("/:id", deleteProvider)
	}
}
