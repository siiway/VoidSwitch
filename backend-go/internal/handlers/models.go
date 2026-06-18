package handlers

import (
	"net/http"
	"strconv"

	"github.com/gin-gonic/gin"

	"github.com/siiway/voidswitch/internal/core"
	"github.com/siiway/voidswitch/internal/database"
	"github.com/siiway/voidswitch/internal/models"
	"github.com/siiway/voidswitch/internal/services"
)

func RegisterModelRoutes(router *gin.RouterGroup) {
	router.GET("/models", handleModelsList)
	router.PUT("/models", handleModelsUpsert)
	router.POST("/models/batch", handleModelsBatch)
	router.POST("/models/sync", handleModelsSync)
	router.POST("/models/clean", handleModelsClean)
	router.DELETE("/models/:id", handleModelsDelete)
}

func handleModelsList(c *gin.Context) {
	user := core.GetUserFromContext(c)
	if user == nil {
		c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"error": "Authentication required."})
		return
	}

	db := database.GetDatabase().DB
	catalog, err := services.BuildCatalog(db)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to build catalog."})
		return
	}

	allParam := c.Query("all")
	if allParam == "true" && core.StaffRolesSet[user.Role] {
		c.JSON(http.StatusOK, catalog)
		return
	}

	filtered := make([]models.ModelOut, 0, len(catalog))
	for _, m := range catalog {
		if m.Served {
			filtered = append(filtered, m)
		}
	}

	c.JSON(http.StatusOK, filtered)
}

func handleModelsUpsert(c *gin.Context) {
	user := core.GetUserFromContext(c)
	if user == nil {
		c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"error": "Authentication required."})
		return
	}
	if !core.StaffRolesSet[user.Role] {
		c.AbortWithStatusJSON(http.StatusForbidden, gin.H{"error": "Admin privileges required."})
		return
	}

	var body models.ModelUpsert
	if err := c.ShouldBindJSON(&body); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid request body."})
		return
	}

	db := database.GetDatabase().DB
	name := core.ActorDisplayName(user)
	entry, err := services.UpsertModel(db, body, &user.ID, &name)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to upsert model."})
		return
	}

	c.JSON(http.StatusOK, modelEntryToOut(entry))
}

func handleModelsBatch(c *gin.Context) {
	user := core.GetUserFromContext(c)
	if user == nil {
		c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"error": "Authentication required."})
		return
	}
	if !core.StaffRolesSet[user.Role] {
		c.AbortWithStatusJSON(http.StatusForbidden, gin.H{"error": "Admin privileges required."})
		return
	}

	var body models.ModelBatchUpdate
	if err := c.ShouldBindJSON(&body); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid request body."})
		return
	}

	db := database.GetDatabase().DB
	name := core.ActorDisplayName(user)

	updated := 0
	for _, modelID := range body.ModelIDs {
		upsert := models.ModelUpsert{
			ModelID:        modelID,
			Description:    body.Description,
			OpenCodeConfig: body.OpenCodeConfig,
			Enabled:        body.Enabled,
		}
		if _, err := services.UpsertModel(db, upsert, &user.ID, &name); err == nil {
			updated++
		}
	}

	c.JSON(http.StatusOK, models.ModelBatchResult{Updated: updated})
}

func handleModelsSync(c *gin.Context) {
	user := core.GetUserFromContext(c)
	if user == nil {
		c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"error": "Authentication required."})
		return
	}
	if !core.StaffRolesSet[user.Role] {
		c.AbortWithStatusJSON(http.StatusForbidden, gin.H{"error": "Admin privileges required."})
		return
	}

	db := database.GetDatabase().DB
	name := core.ActorDisplayName(user)
	result, err := services.SyncCatalog(db, &user.ID, &name)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to sync catalog."})
		return
	}

	c.JSON(http.StatusOK, result)
}

func handleModelsClean(c *gin.Context) {
	user := core.GetUserFromContext(c)
	if user == nil {
		c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"error": "Authentication required."})
		return
	}
	if !core.StaffRolesSet[user.Role] {
		c.AbortWithStatusJSON(http.StatusForbidden, gin.H{"error": "Admin privileges required."})
		return
	}

	db := database.GetDatabase().DB
	result, err := services.CleanUnserved(db)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to clean unserved models."})
		return
	}

	c.JSON(http.StatusOK, result)
}

func handleModelsDelete(c *gin.Context) {
	user := core.GetUserFromContext(c)
	if user == nil {
		c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"error": "Authentication required."})
		return
	}
	if !core.StaffRolesSet[user.Role] {
		c.AbortWithStatusJSON(http.StatusForbidden, gin.H{"error": "Admin privileges required."})
		return
	}

	id, err := strconv.Atoi(c.Param("id"))
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid model ID."})
		return
	}

	db := database.GetDatabase().DB
	if err := services.DeleteModel(db, id); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to delete model."})
		return
	}

	c.Status(http.StatusNoContent)
}

func modelEntryToOut(entry *database.ModelEntry) models.ModelOut {
	publicID := entry.ModelID
	var mappedID *string
	if entry.MappedID != nil && *entry.MappedID != "" {
		mappedID = entry.MappedID
		publicID = *entry.MappedID
	}
	return models.ModelOut{
		ID:             &entry.ID,
		ModelID:        entry.ModelID,
		MappedID:       mappedID,
		PublicID:       publicID,
		DisplayName:    entry.DisplayName,
		Description:    entry.Description,
		OpenCodeConfig: entry.OpenCodeConfig,
		Enabled:        entry.Enabled,
		Served:         false,
		Registered:     true,
		AddedByName:    entry.AddedByName,
		CreatedAt:      &entry.CreatedAt,
		UpdatedAt:      &entry.UpdatedAt,
	}
}
