package admin

import (
	"net/http"
	"strconv"

	"github.com/gin-gonic/gin"

	"github.com/siiway/voidswitch/internal/constants"
	"github.com/siiway/voidswitch/internal/core"
	"github.com/siiway/voidswitch/internal/database"
	"github.com/siiway/voidswitch/internal/models"
)

func listUsers(c *gin.Context) {
	db := database.GetDatabase().DB
	user, ok := getCurrentUserGin(c)
	if !ok || !requireStaffGin(c, user) {
		return
	}

	var users []database.User
	if err := db.Find(&users).Error; err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to query users."})
		return
	}

	result := make([]models.UserOut, 0, len(users))
	for _, u := range users {
		result = append(result, userToOut(u))
	}

	c.JSON(http.StatusOK, result)
}

func updateUser(c *gin.Context) {
	db := database.GetDatabase().DB
	user, ok := getCurrentUserGin(c)
	if !ok || !requireOwnerGin(c, user) {
		return
	}

	id, err := strconv.Atoi(c.Param("id"))
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid user ID."})
		return
	}

	var existing database.User
	if err := db.First(&existing, id).Error; err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "User not found."})
		return
	}

	var body struct {
		Role    *string `json:"role"`
		Enabled *bool   `json:"enabled"`
	}
	if err := c.ShouldBindJSON(&body); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid request body."})
		return
	}

	changes := make(map[string]any)

	if body.Role != nil {
		if *body.Role != string(constants.RoleAdmin) && *body.Role != string(constants.RoleMember) {
			c.JSON(http.StatusBadRequest, gin.H{"error": "Only admin or member roles can be set manually."})
			return
		}
		changes["role"] = map[string]any{"old": existing.Role, "new": *body.Role}
		existing.Role = *body.Role
	}
	if body.Enabled != nil {
		changes["enabled"] = map[string]any{"old": existing.Enabled, "new": *body.Enabled}
		existing.Enabled = *body.Enabled
	}

	if err := db.Save(&existing).Error; err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to update user."})
		return
	}

	cname := core.ActorDisplayName(user)
	targetID := strconv.Itoa(existing.ID)
	targetType := "user"
	core.RecordAudit(db, "user.update", &user.Sub, &cname, &targetType, &targetID, changes, nil, nil, nil, "admin")

	c.JSON(http.StatusOK, userToOut(existing))
}

func userToOut(u database.User) models.UserOut {
	return models.UserOut{
		ID:          u.ID,
		Sub:         u.Sub,
		Username:    u.Username,
		Email:       u.Email,
		Name:        u.Name,
		Picture:     u.Picture,
		Role:        u.Role,
		PrismRole:   u.PrismRole,
		Enabled:     u.Enabled,
		LastLoginAt: u.LastLoginAt,
		CreatedAt:   u.CreatedAt,
	}
}

func RegisterUserRoutes(router *gin.RouterGroup) {
	userGroup := router.Group("/users")
	{
		userGroup.GET("", listUsers)
		userGroup.PATCH("/:id", updateUser)
	}
}
