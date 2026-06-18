package handlers

import (
	"net/http"
	"strconv"

	"github.com/gin-gonic/gin"
	"gorm.io/gorm"

	"github.com/siiway/voidswitch/internal/config"
	"github.com/siiway/voidswitch/internal/core"
	"github.com/siiway/voidswitch/internal/database"
	"github.com/siiway/voidswitch/internal/models"
)

func RegisterAnnouncementRoutes(router *gin.RouterGroup) {
	router.GET("/announcements", listAnnouncements)
	router.POST("/announcements", createAnnouncement)
	router.PATCH("/announcements/:id", updateAnnouncement)
	router.DELETE("/announcements/:id", deleteAnnouncement)
}

func canManageAnnouncement(user *database.User, ann *database.Announcement) bool {
	if ann.CreatedBy == user.ID {
		return true
	}
	return core.RoleRank(user.Role) > core.RoleRank(ann.CreatedByRole)
}

func announcementToOut(user *database.User, ann *database.Announcement) models.AnnouncementOut {
	return models.AnnouncementOut{
		ID:                ann.ID,
		CreatedAt:         ann.CreatedAt,
		UpdatedAt:         ann.UpdatedAt,
		Title:             ann.Title,
		Body:              ann.Body,
		CreatedBy:         ann.CreatedBy,
		CreatedByName:     ann.CreatedByName,
		CreatedByRole:     ann.CreatedByRole,
		Edited:            ann.Edited,
		CanManage:         canManageAnnouncement(user, ann),
		TargetRoleGroupIDs: ann.TargetRoleGroupIDs,
	}
}

func listAnnouncements(c *gin.Context) {
	user := core.GetUserFromContext(c)
	if user == nil {
		c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"error": "Authentication required."})
		return
	}

	db := database.GetDatabase().DB
	isStaff := core.IsStaff(user)

	var announcements []database.Announcement
	q := db.Order("id DESC")
	if limitStr := c.Query("limit"); limitStr != "" {
		if limit, err := strconv.Atoi(limitStr); err == nil && limit > 0 {
			q = q.Limit(limit)
		}
	}
	q.Find(&announcements)

	out := make([]models.AnnouncementOut, 0, len(announcements))
	for _, a := range announcements {
		if isStaff {
			out = append(out, announcementToOut(user, &a))
			continue
		}
		if len(a.TargetRoleGroupIDs) == 0 {
			out = append(out, announcementToOut(user, &a))
			continue
		}
		userGroupIDs, _ := getUserGroupIDs(db, user.ID)
		if intersects(a.TargetRoleGroupIDs, userGroupIDs) {
			out = append(out, announcementToOut(user, &a))
		}
	}

	c.JSON(http.StatusOK, out)
}

func createAnnouncement(c *gin.Context) {
	user := core.GetUserFromContext(c)
	if user == nil || !core.IsStaff(user) {
		c.AbortWithStatusJSON(http.StatusForbidden, gin.H{"error": "Only staff may publish announcements."})
		return
	}

	var body models.AnnouncementCreate
	if err := c.ShouldBindJSON(&body); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid request body."})
		return
	}

	title := body.Title
	if title == "" {
		c.JSON(http.StatusUnprocessableEntity, gin.H{"error": "title is required."})
		return
	}

	db := database.GetDatabase().DB
	settings := config.Load()
	name := core.ActorDisplayName(user)

	ann := database.Announcement{
		Title:              title,
		Body:               body.Body,
		CreatedBy:          user.ID,
		CreatedByName:      name,
		CreatedByRole:      user.Role,
		TargetRoleGroupIDs: body.TargetRoleGroupIDs,
	}

	if err := db.Create(&ann).Error; err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to create announcement."})
		return
	}

	targetID := strconv.Itoa(ann.ID)
	targetType := "announcement"
	ip := c.ClientIP()
	core.RecordAudit(db, "announcement.create", &user.Sub, &name, &targetType, &targetID,
		map[string]any{"title": ann.Title}, &ip,
		map[string]any{"title": ann.Title, "body": ann.Body}, &settings.Server.SecretKey, "admin")

	c.JSON(http.StatusCreated, announcementToOut(user, &ann))
}

func updateAnnouncement(c *gin.Context) {
	user := core.GetUserFromContext(c)
	if user == nil {
		c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"error": "Authentication required."})
		return
	}

	id, err := strconv.Atoi(c.Param("id"))
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid announcement ID."})
		return
	}

	db := database.GetDatabase().DB
	var ann database.Announcement
	if err := db.First(&ann, id).Error; err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "Announcement not found."})
		return
	}

	if !canManageAnnouncement(user, &ann) {
		c.AbortWithStatusJSON(http.StatusForbidden, gin.H{"error": "You can only edit your own announcements or those of a lower tier."})
		return
	}

	var body models.AnnouncementUpdate
	if err := c.ShouldBindJSON(&body); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid request body."})
		return
	}

	oldTitle, oldBody := ann.Title, ann.Body
	changed := false

	if body.Title != nil {
		title := *body.Title
		if title == "" {
			c.JSON(http.StatusUnprocessableEntity, gin.H{"error": "title cannot be empty."})
			return
		}
		if title != ann.Title {
			ann.Title = title
			changed = true
		}
	}
	if body.Body != nil && *body.Body != ann.Body {
		ann.Body = *body.Body
		changed = true
	}
	if body.TargetRoleGroupIDs != nil && !intSlicesEqual(*body.TargetRoleGroupIDs, ann.TargetRoleGroupIDs) {
		ann.TargetRoleGroupIDs = *body.TargetRoleGroupIDs
		changed = true
	}

	if changed {
		ann.Edited = true
		if err := db.Save(&ann).Error; err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to update announcement."})
			return
		}

		settings := config.Load()
		name := core.ActorDisplayName(user)
		targetID := strconv.Itoa(ann.ID)
		targetType := "announcement"
		ip := c.ClientIP()
		core.RecordAudit(db, "announcement.update", &user.Sub, &name, &targetType, &targetID,
			map[string]any{"title": ann.Title, "author": ann.CreatedByName}, &ip,
			map[string]any{"old_title": oldTitle, "old_body": oldBody, "new_title": ann.Title, "new_body": ann.Body},
			&settings.Server.SecretKey, "admin")
	}

	c.JSON(http.StatusOK, announcementToOut(user, &ann))
}

func deleteAnnouncement(c *gin.Context) {
	user := core.GetUserFromContext(c)
	if user == nil {
		c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"error": "Authentication required."})
		return
	}

	id, err := strconv.Atoi(c.Param("id"))
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid announcement ID."})
		return
	}

	db := database.GetDatabase().DB
	var ann database.Announcement
	if err := db.First(&ann, id).Error; err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "Announcement not found."})
		return
	}

	if !canManageAnnouncement(user, &ann) {
		c.AbortWithStatusJSON(http.StatusForbidden, gin.H{"error": "You can only delete your own announcements or those of a lower tier."})
		return
	}

	if err := db.Delete(&ann).Error; err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to delete announcement."})
		return
	}

	settings := config.Load()
	name := core.ActorDisplayName(user)
	targetID := strconv.Itoa(id)
	targetType := "announcement"
	ip := c.ClientIP()
	core.RecordAudit(db, "announcement.delete", &user.Sub, &name, &targetType, &targetID,
		map[string]any{"title": ann.Title, "author": ann.CreatedByName}, &ip,
		map[string]any{"title": ann.Title, "body": ann.Body}, &settings.Server.SecretKey, "admin")

	c.Status(http.StatusNoContent)
}

func intersects(a, b []int) bool {
	set := make(map[int]bool)
	for _, v := range a {
		set[v] = true
	}
	for _, v := range b {
		if set[v] {
			return true
		}
	}
	return false
}

func intSlicesEqual(a, b []int) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}
	return true
}

func getUserGroupIDs(db *gorm.DB, userID int) ([]int, error) {
	var ids []int
	db.Model(&database.RoleGroupMembership{}).Where("user_id = ?", userID).Pluck("role_group_id", &ids)
	return ids, nil
}
