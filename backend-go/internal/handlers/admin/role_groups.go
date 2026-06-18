package admin

import (
	"net/http"
	"strconv"

	"github.com/gin-gonic/gin"
	"gorm.io/gorm"

	"github.com/siiway/voidswitch/internal/constants"
	"github.com/siiway/voidswitch/internal/core"
	"github.com/siiway/voidswitch/internal/database"
	"github.com/siiway/voidswitch/internal/models"
)

func RegisterRoleGroupRoutes(router *gin.RouterGroup) {
	rg := router.Group("/role-groups")
	{
		rg.GET("", listRoleGroups)
		rg.POST("", createRoleGroup)
		rg.PATCH("/:id", updateRoleGroup)
		rg.GET("/:id/members", listRoleGroupMembers)
		rg.DELETE("/:id/members/:userId", removeRoleGroupMember)
		rg.DELETE("/:id", deleteRoleGroup)
	}
}

func validMinRole(value string) string {
	canonical := NormaliseTeamRole(value)
	if canonical == "" || constants.TeamRoleRank[canonical] == 0 {
		return ""
	}
	return canonical
}

func NormaliseTeamRole(value string) string {
	if value == "" {
		return ""
	}
	key := toLower(stripDashes(value))
	switch key {
	case "coowner":
		return "co-owner"
	case "owner":
		return "owner"
	case "admin":
		return "admin"
	case "member":
		return "member"
	}
	return ""
}

func stripDashes(s string) string {
	b := make([]byte, 0, len(s))
	for i := 0; i < len(s); i++ {
		c := s[i]
		if c != '-' && c != '_' && c != ' ' {
			b = append(b, c)
		}
	}
	return string(b)
}

func toLower(s string) string {
	b := make([]byte, len(s))
	for i := 0; i < len(s); i++ {
		c := s[i]
		if c >= 'A' && c <= 'Z' {
			c += 32
		}
		b[i] = c
	}
	return string(b)
}

func memberCounts(db *gorm.DB) map[int]int {
	type result struct {
		RoleGroupID int
		Count       int
	}
	var rows []result
	db.Model(&database.RoleGroupMembership{}).
		Select("role_group_id, COUNT(*) as count").
		Group("role_group_id").
		Scan(&rows)
	m := make(map[int]int, len(rows))
	for _, r := range rows {
		m[r.RoleGroupID] = r.Count
	}
	return m
}

func roleGroupToOut(group *database.RoleGroup, memberCount int) models.RoleGroupOut {
	mappings := make([]models.RoleGroupMappingOut, 0, len(group.Mappings))
	for _, m := range group.Mappings {
		mappings = append(mappings, models.RoleGroupMappingOut{
			ID:      m.ID,
			TeamID:  m.TeamID,
			MinRole: m.MinRole,
		})
	}
	if mappings == nil {
		mappings = []models.RoleGroupMappingOut{}
	}
	return models.RoleGroupOut{
		ID:          group.ID,
		Slug:        group.Slug,
		Name:        group.Name,
		Description: group.Description,
		Builtin:     group.Builtin,
		MemberCount: memberCount,
		Mappings:    mappings,
		CreatedAt:   group.CreatedAt,
		UpdatedAt:   group.UpdatedAt,
	}
}

func listRoleGroups(c *gin.Context) {
	user, ok := getCurrentUserGin(c)
	if !ok || !requireStaffGin(c, user) {
		return
	}

	db := database.GetDatabase().DB
	var groups []database.RoleGroup
	db.Preload("Mappings").Order("builtin DESC, id ASC").Find(&groups)

	counts := memberCounts(db)

	var staffCount int64
	db.Model(&database.User{}).Where("role IN ?", []string{"owner", "co-owner", "admin"}).Count(&staffCount)

	out := make([]models.RoleGroupOut, 0, len(groups))
	for _, g := range groups {
		count := counts[g.ID]
		if g.Builtin {
			count = int(staffCount)
		}
		out = append(out, roleGroupToOut(&g, count))
	}

	c.JSON(http.StatusOK, out)
}

func createRoleGroup(c *gin.Context) {
	user, ok := getCurrentUserGin(c)
	if !ok || !requireStaffGin(c, user) {
		return
	}

	var body models.RoleGroupCreate
	if err := c.ShouldBindJSON(&body); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid request body."})
		return
	}

	name := body.Name
	if name == "" {
		c.JSON(http.StatusUnprocessableEntity, gin.H{"error": "name is required."})
		return
	}

	db := database.GetDatabase().DB
	var clash database.RoleGroup
	if db.Where("name = ?", name).First(&clash).Error == nil {
		c.JSON(http.StatusConflict, gin.H{"error": "A role group with this name already exists."})
		return
	}

	group := database.RoleGroup{
		Slug:        toSlug(name),
		Name:        name,
		Description: body.Description,
		Builtin:     false,
	}

	tx := db.Begin()
	if err := tx.Create(&group).Error; err != nil {
		tx.Rollback()
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to create role group."})
		return
	}

	for _, m := range body.Mappings {
		teamID := m.TeamID
		if teamID == "" {
			continue
		}
		minRole := validMinRole(m.MinRole)
		if minRole == "" {
			continue
		}
		tx.Create(&database.RoleGroupMapping{
			RoleGroupID: group.ID,
			TeamID:      teamID,
			MinRole:     minRole,
		})
	}
	tx.Commit()

	db.Preload("Mappings").First(&group, group.ID)
	cname := core.ActorDisplayName(user)
	targetID := strconv.Itoa(group.ID)
	targetType := "role_group"
	core.RecordAudit(db, "role_group.create", &user.Sub, &cname, &targetType, &targetID,
		map[string]any{"name": name, "mappings": body.Mappings}, nil, nil, nil, "admin")

	c.JSON(http.StatusCreated, roleGroupToOut(&group, 0))
}

func updateRoleGroup(c *gin.Context) {
	user, ok := getCurrentUserGin(c)
	if !ok || !requireStaffGin(c, user) {
		return
	}

	id, err := strconv.Atoi(c.Param("id"))
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid role group ID."})
		return
	}

	db := database.GetDatabase().DB
	var group database.RoleGroup
	if err := db.Preload("Mappings").First(&group, id).Error; err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "Role group not found."})
		return
	}

	if group.Builtin {
		c.AbortWithStatusJSON(http.StatusBadRequest, gin.H{"error": "The built-in moderator group cannot be edited."})
		return
	}

	var body models.RoleGroupUpdate
	if err := c.ShouldBindJSON(&body); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid request body."})
		return
	}

	changes := make(map[string]any)

	if body.Name != nil {
		name := *body.Name
		if name == "" {
			c.JSON(http.StatusUnprocessableEntity, gin.H{"error": "name cannot be empty."})
			return
		}
		if name != group.Name {
			var clash database.RoleGroup
			if db.Where("name = ? AND id != ?", name, group.ID).First(&clash).Error == nil {
				c.JSON(http.StatusConflict, gin.H{"error": "A role group with this name already exists."})
				return
			}
			group.Name = name
			changes["name"] = name
		}
	}
	if body.Description != nil {
		group.Description = body.Description
		changes["description"] = group.Description
	}

	if body.Mappings != nil {
		db.Where("role_group_id = ?", group.ID).Delete(&database.RoleGroupMapping{})
		var newMappings []map[string]string
		for _, m := range *body.Mappings {
			teamID := m.TeamID
			if teamID == "" {
				continue
			}
			minRole := validMinRole(m.MinRole)
			if minRole == "" {
				continue
			}
			db.Create(&database.RoleGroupMapping{
				RoleGroupID: group.ID,
				TeamID:      teamID,
				MinRole:     minRole,
			})
			newMappings = append(newMappings, map[string]string{"team_id": teamID, "min_role": minRole})
		}
		changes["mappings"] = newMappings
	}

	if len(changes) > 0 {
		db.Save(&group)
		cname := core.ActorDisplayName(user)
		targetID := strconv.Itoa(group.ID)
		targetType := "role_group"
		core.RecordAudit(db, "role_group.update", &user.Sub, &cname, &targetType, &targetID,
			map[string]any{"name": group.Name, "changes": changes}, nil, nil, nil, "admin")
	}

	db.Preload("Mappings").First(&group, group.ID)
	counts := memberCounts(db)
	c.JSON(http.StatusOK, roleGroupToOut(&group, counts[group.ID]))
}

func listRoleGroupMembers(c *gin.Context) {
	user, ok := getCurrentUserGin(c)
	if !ok || !requireStaffGin(c, user) {
		return
	}

	id, err := strconv.Atoi(c.Param("id"))
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid role group ID."})
		return
	}

	db := database.GetDatabase().DB
	var group database.RoleGroup
	if err := db.First(&group, id).Error; err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "Role group not found."})
		return
	}

	if group.Builtin {
		c.AbortWithStatusJSON(http.StatusBadRequest, gin.H{"error": "The built-in moderator group has no stored members."})
		return
	}

	type memberRow struct {
		UserID     int     `gorm:"column:user_id"`
		Username   *string `gorm:"column:username"`
		Name       *string `gorm:"column:name"`
		Email      *string `gorm:"column:email"`
		Role       string  `gorm:"column:role"`
		Source     string  `gorm:"column:source"`
		Enabled    bool    `gorm:"column:enabled"`
	}
	var rows []memberRow
	db.Table("role_group_memberships").
		Select("role_group_memberships.user_id, users.username, users.name, users.email, users.role, role_group_memberships.source, users.enabled").
		Joins("JOIN users ON users.id = role_group_memberships.user_id").
		Where("role_group_memberships.role_group_id = ?", id).
		Order("users.id ASC").
		Scan(&rows)

	out := make([]models.RoleGroupMemberOut, 0, len(rows))
	for _, r := range rows {
		label := ""
		if r.Username != nil {
			label = *r.Username
		} else if r.Name != nil {
			label = *r.Name
		} else if r.Email != nil {
			label = *r.Email
		}
		out = append(out, models.RoleGroupMemberOut{
			UserID:  r.UserID,
			Name:    label,
			Email:   r.Email,
			Role:    r.Role,
			Source:  r.Source,
			Enabled: r.Enabled,
		})
	}

	c.JSON(http.StatusOK, out)
}

func removeRoleGroupMember(c *gin.Context) {
	user, ok := getCurrentUserGin(c)
	if !ok || !requireStaffGin(c, user) {
		return
	}

	groupID, err := strconv.Atoi(c.Param("id"))
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid role group ID."})
		return
	}

	userID, err := strconv.Atoi(c.Param("userId"))
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid user ID."})
		return
	}

	db := database.GetDatabase().DB
	var group database.RoleGroup
	if err := db.First(&group, groupID).Error; err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "Role group not found."})
		return
	}

	if group.Builtin {
		c.AbortWithStatusJSON(http.StatusBadRequest, gin.H{"error": "Cannot remove members from the built-in moderator group."})
		return
	}

	var membership database.RoleGroupMembership
	if err := db.Where("role_group_id = ? AND user_id = ?", groupID, userID).First(&membership).Error; err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "User is not in this role group."})
		return
	}

	db.Delete(&membership)

	cname := core.ActorDisplayName(user)
	targetID := strconv.Itoa(groupID)
	targetType := "role_group"
	core.RecordAudit(db, "role_group.member_remove", &user.Sub, &cname, &targetType, &targetID,
		map[string]any{"group": group.Name, "user_id": userID, "was_source": membership.Source, "temporary": true},
		nil, nil, nil, "admin")

	c.Status(http.StatusNoContent)
}

func deleteRoleGroup(c *gin.Context) {
	user, ok := getCurrentUserGin(c)
	if !ok || !requireStaffGin(c, user) {
		return
	}

	id, err := strconv.Atoi(c.Param("id"))
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid role group ID."})
		return
	}

	db := database.GetDatabase().DB
	var group database.RoleGroup
	if err := db.First(&group, id).Error; err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "Role group not found."})
		return
	}

	if group.Builtin {
		c.AbortWithStatusJSON(http.StatusBadRequest, gin.H{"error": "The built-in moderator group cannot be deleted."})
		return
	}

	name := group.Name
	db.Delete(&group)

	cname := core.ActorDisplayName(user)
	targetID := strconv.Itoa(id)
	targetType := "role_group"
	core.RecordAudit(db, "role_group.delete", &user.Sub, &cname, &targetType, &targetID,
		map[string]any{"name": name}, nil, nil, nil, "admin")

	c.Status(http.StatusNoContent)
}

func toSlug(s string) string {
	b := make([]byte, 0, len(s))
	for i := 0; i < len(s); i++ {
		c := s[i]
		if c >= 'A' && c <= 'Z' {
			c += 32
		}
		if (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '-' {
			b = append(b, c)
		} else if c == ' ' || c == '_' {
			b = append(b, '-')
		}
	}
	return string(b)
}
