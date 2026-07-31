package admin

import (
	"net/http"

	"github.com/gin-gonic/gin"

	"github.com/siiway/voidswitch/internal/core"
	"github.com/siiway/voidswitch/internal/database"
	"github.com/siiway/voidswitch/internal/models"
	"github.com/siiway/voidswitch/internal/services"
)

func getSettings(c *gin.Context) {
	db := database.GetDatabase().DB
	user, ok := getCurrentUserGin(c)
	if !ok || !requireStaffGin(c, user) {
		return
	}

	values, err := services.GetAll(db)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to load settings."})
		return
	}

	c.JSON(http.StatusOK, models.SettingsOut{Values: values})
}

func updateSettings(c *gin.Context) {
	db := database.GetDatabase().DB
	user, ok := getCurrentUserGin(c)
	if !ok || !requireOwnerGin(c, user) {
		return
	}

	var body models.SettingsUpdate
	if err := c.ShouldBindJSON(&body); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid request body."})
		return
	}

	values, err := services.Update(db, body.Values)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to update settings."})
		return
	}

	name := core.ActorDisplayName(user)
	core.RecordAudit(db, "settings.update", &user.Sub, &name, nil, nil,
		body.Values, nil, nil, nil, "admin")

	c.JSON(http.StatusOK, models.SettingsOut{Values: values})
}

func RegisterSettingsRoutes(router *gin.RouterGroup) {
	settingsGroup := router.Group("/settings")
	{
		settingsGroup.GET("", getSettings)
		settingsGroup.PUT("", updateSettings)
	}
}
