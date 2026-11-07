package handlers

import (
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/gin-gonic/gin"

	"github.com/siiway/voidswitch/internal/constants"
	"github.com/siiway/voidswitch/internal/core"
	"github.com/siiway/voidswitch/internal/database"
	"github.com/siiway/voidswitch/internal/services"
)

// ---- role groups ----------------------------------------------------------

type mappingView struct {
	ID      int    `json:"id"`
	TeamID  string `json:"team_id"`
	MinRole string `json:"min_role"`
	Grants  string `json:"grants"`
}

type roleGroupView struct {
	ID                         int           `json:"id"`
	Slug                       *string       `json:"slug"`
	Name                       string        `json:"name"`
	Description                *string       `json:"description"`
	Builtin                    bool          `json:"builtin"`
	MemberCount                int           `json:"member_count"`
	Mappings                   []mappingView `json:"mappings"`
	CallRateLimitWindowSeconds int           `json:"call_rate_limit_window_seconds"`
	CallRateLimitMaxRequests   int           `json:"call_rate_limit_max_requests"`
	CreatedAt                  time.Time     `json:"created_at"`
	UpdatedAt                  time.Time     `json:"updated_at"`
}

type mappingIn struct {
	TeamID  string `json:"team_id"`
	MinRole string `json:"min_role"`
	Grants  string `json:"grants"`
}

type roleGroupPayload struct {
	Name          *string      `json:"name"`
	Description   *string      `json:"description"`
	Mappings      *[]mappingIn `json:"mappings"`
	WindowSeconds *int         `json:"call_rate_limit_window_seconds"`
	MaxRequests   *int         `json:"call_rate_limit_max_requests"`
}

func (a *App) roleGroupOut(g *database.RoleGroup) roleGroupView {
	var mappings []database.RoleGroupMapping
	a.GDB.Where("role_group_id = ?", g.ID).Order("id").Find(&mappings)
	views := make([]mappingView, 0, len(mappings))
	for _, m := range mappings {
		views = append(views, mappingView{ID: m.ID, TeamID: m.TeamID, MinRole: m.MinRole, Grants: m.Grants})
	}
	var members int64
	a.GDB.Model(&database.RoleGroupMembership{}).Where("role_group_id = ?", g.ID).Count(&members)
	return roleGroupView{
		ID: g.ID, Slug: g.Slug, Name: g.Name, Description: g.Description, Builtin: g.Builtin,
		MemberCount: int(members), Mappings: views,
		CallRateLimitWindowSeconds: g.CallRateLimitWindowSeconds,
		CallRateLimitMaxRequests:   g.CallRateLimitMaxRequests,
		CreatedAt:                  g.CreatedAt, UpdatedAt: g.UpdatedAt,
	}
}

func roleGroupSlug(name string) string {
	s := slugify(name)
	if s == "" {
		return "role-group"
	}
	return s
}

func (a *App) uniqueRoleGroupSlug(base string, excludeID int) string {
	slug := roleGroupSlug(base)
	candidate := slug
	n := 2
	for {
		var count int64
		q := a.GDB.Model(&database.RoleGroup{}).Where("slug = ?", candidate)
		if excludeID > 0 {
			q = q.Where("id <> ?", excludeID)
		}
		q.Count(&count)
		if count == 0 {
			return candidate
		}
		candidate = slug + "-" + strconv.Itoa(n)
		n++
	}
}

func (a *App) applyRoleGroupMappings(groupID int, mappings []mappingIn) error {
	if err := a.GDB.Where("role_group_id = ? AND grants = ?", groupID, "member").
		Delete(&database.RoleGroupMapping{}).Error; err != nil {
		return err
	}
	for _, m := range mappings {
		team := strings.TrimSpace(m.TeamID)
		if team == "" || m.MinRole == "" {
			continue
		}
		row := database.RoleGroupMapping{
			RoleGroupID: groupID, TeamID: team, MinRole: m.MinRole, Grants: "member",
		}
		if err := a.GDB.Create(&row).Error; err != nil {
			return err
		}
	}
	return nil
}

func (a *App) roleGroupsList(c *gin.Context) {
	var rows []database.RoleGroup
	if err := a.GDB.Order("id").Find(&rows).Error; err != nil {
		a.internal(c, err)
		return
	}
	out := make([]roleGroupView, 0, len(rows))
	for i := range rows {
		out = append(out, a.roleGroupOut(&rows[i]))
	}
	c.JSON(http.StatusOK, out)
}

func (a *App) roleGroupCreate(c *gin.Context) {
	uv := core.GetUser(c)
	var in roleGroupPayload
	if err := c.ShouldBindJSON(&in); err != nil || in.Name == nil || strings.TrimSpace(*in.Name) == "" {
		a.fail(c, http.StatusUnprocessableEntity, "name is required.")
		return
	}
	name := strings.TrimSpace(*in.Name)
	var clash int64
	a.GDB.Model(&database.RoleGroup{}).Where("name = ?", name).Count(&clash)
	if clash > 0 {
		a.fail(c, http.StatusConflict, "Role group name already exists.")
		return
	}
	g := database.RoleGroup{
		Slug: strPtr(a.uniqueRoleGroupSlug(name, 0)), Name: name,
		Description:                in.Description,
		CallRateLimitWindowSeconds: 60, CallRateLimitMaxRequests: 0,
	}
	if in.WindowSeconds != nil {
		g.CallRateLimitWindowSeconds = *in.WindowSeconds
	}
	if in.MaxRequests != nil {
		g.CallRateLimitMaxRequests = *in.MaxRequests
	}
	if err := a.GDB.Create(&g).Error; err != nil {
		a.internal(c, err)
		return
	}
	if in.Mappings != nil {
		if err := a.applyRoleGroupMappings(g.ID, *in.Mappings); err != nil {
			a.internal(c, err)
			return
		}
	}
	sub, name2 := uv.User.Sub, services.BuildUserView(uv.User).Username
	tid := strconv.Itoa(g.ID)
	_ = core.RecordAudit(a.GDB, core.AuditInput{
		Action: "role_group.create", ActorSub: &sub, ActorName: name2, Scope: core.AuditScopeAdmin,
		TargetType: strPtr("role_group"), TargetID: &tid, Detail: map[string]any{"name": g.Name},
		IP: strPtr(clientIP(c)),
	})
	c.JSON(http.StatusCreated, a.roleGroupOut(&g))
}

func (a *App) roleGroupUpdate(c *gin.Context) {
	uv := core.GetUser(c)
	id, _ := strconv.Atoi(c.Param("id"))
	var g database.RoleGroup
	if err := a.GDB.First(&g, id).Error; err != nil {
		a.fail(c, http.StatusNotFound, "Role group not found.")
		return
	}
	var in roleGroupPayload
	if err := c.ShouldBindJSON(&in); err != nil {
		a.fail(c, http.StatusUnprocessableEntity, "invalid payload.")
		return
	}
	if in.Name != nil && strings.TrimSpace(*in.Name) != "" && *in.Name != g.Name {
		name := strings.TrimSpace(*in.Name)
		var clash int64
		a.GDB.Model(&database.RoleGroup{}).Where("name = ? AND id <> ?", name, g.ID).Count(&clash)
		if clash > 0 {
			a.fail(c, http.StatusConflict, "Role group name already exists.")
			return
		}
		g.Name = name
		if !g.Builtin {
			g.Slug = strPtr(a.uniqueRoleGroupSlug(name, g.ID))
		}
	}
	if in.Description != nil {
		g.Description = in.Description
	}
	if in.WindowSeconds != nil {
		g.CallRateLimitWindowSeconds = *in.WindowSeconds
	}
	if in.MaxRequests != nil {
		g.CallRateLimitMaxRequests = *in.MaxRequests
	}
	if err := a.GDB.Save(&g).Error; err != nil {
		a.internal(c, err)
		return
	}
	if in.Mappings != nil {
		if err := a.applyRoleGroupMappings(g.ID, *in.Mappings); err != nil {
			a.internal(c, err)
			return
		}
	}
	sub, name := uv.User.Sub, services.BuildUserView(uv.User).Username
	tid := strconv.Itoa(g.ID)
	_ = core.RecordAudit(a.GDB, core.AuditInput{
		Action: "role_group.update", ActorSub: &sub, ActorName: name, Scope: core.AuditScopeAdmin,
		TargetType: strPtr("role_group"), TargetID: &tid, Detail: map[string]any{"name": g.Name},
		IP: strPtr(clientIP(c)),
	})
	c.JSON(http.StatusOK, a.roleGroupOut(&g))
}

func (a *App) roleGroupDelete(c *gin.Context) {
	id, _ := strconv.Atoi(c.Param("id"))
	var g database.RoleGroup
	if err := a.GDB.First(&g, id).Error; err != nil {
		a.fail(c, http.StatusNotFound, "Role group not found.")
		return
	}
	if g.Builtin {
		a.fail(c, http.StatusBadRequest, "Built-in role groups cannot be deleted.")
		return
	}
	if err := a.GDB.Delete(&g).Error; err != nil {
		a.internal(c, err)
		return
	}
	a.GDB.Where("role_group_id = ?", g.ID).Delete(&database.RoleGroupMapping{})
	a.GDB.Where("role_group_id = ?", g.ID).Delete(&database.RoleGroupMembership{})
	a.GDB.Where("role_group_id = ?", g.ID).Delete(&database.RoleGroupAdminship{})
	c.Status(http.StatusNoContent)
}

type roleGroupMemberView struct {
	UserID   int     `json:"user_id"`
	Name     string  `json:"name"`
	Nickname *string `json:"nickname"`
	Email    *string `json:"email"`
	Role     string  `json:"role"`
	Source   string  `json:"source"`
	Enabled  bool    `json:"enabled"`
	IsAdmin  bool    `json:"is_admin"`
}

func (a *App) roleGroupMembers(c *gin.Context) {
	id, _ := strconv.Atoi(c.Param("id"))
	var rows []database.RoleGroupMembership
	if err := a.GDB.Where("role_group_id = ?", id).Order("id").Find(&rows).Error; err != nil {
		a.internal(c, err)
		return
	}
	var admins []database.RoleGroupAdminship
	a.GDB.Where("role_group_id = ?", id).Find(&admins)
	adminSet := map[int]bool{}
	for _, ad := range admins {
		adminSet[ad.UserID] = true
	}
	out := make([]roleGroupMemberView, 0, len(rows))
	for _, m := range rows {
		var u database.User
		if err := a.GDB.First(&u, m.UserID).Error; err != nil {
			continue
		}
		name := ""
		if u.Name != nil {
			name = *u.Name
		} else if u.Username != nil {
			name = *u.Username
		}
		out = append(out, roleGroupMemberView{
			UserID: u.ID, Name: name, Nickname: u.Username, Email: u.Email,
			Role: u.Role, Source: m.Source, Enabled: u.Enabled, IsAdmin: adminSet[u.ID],
		})
	}
	c.JSON(http.StatusOK, out)
}

func (a *App) roleGroupMemberDelete(c *gin.Context) {
	id, _ := strconv.Atoi(c.Param("id"))
	uid, _ := strconv.Atoi(c.Param("userId"))
	res := a.GDB.Where("role_group_id = ? AND user_id = ?", id, uid).
		Delete(&database.RoleGroupMembership{})
	if res.Error != nil {
		a.internal(c, res.Error)
		return
	}
	if res.RowsAffected == 0 {
		a.fail(c, http.StatusNotFound, "Membership not found.")
		return
	}
	c.Status(http.StatusNoContent)
}

// ---- users ----------------------------------------------------------------

func (a *App) usersList(c *gin.Context) {
	var rows []database.User
	if err := a.GDB.Order("id").Find(&rows).Error; err != nil {
		a.internal(c, err)
		return
	}
	out := make([]services.UserView, 0, len(rows))
	for i := range rows {
		v := services.BuildUserView(&rows[i])
		var names []string
		a.GDB.Model(&database.RoleGroupMembership{}).
			Joins("JOIN role_groups ON role_groups.id = role_group_memberships.role_group_id").
			Where("role_group_memberships.user_id = ?", rows[i].ID).
			Pluck("role_groups.name", &names)
		v.RoleGroupNames = names
		out = append(out, v)
	}
	c.JSON(http.StatusOK, out)
}

func (a *App) userUpdate(c *gin.Context) {
	uv := core.GetUser(c)
	id, _ := strconv.Atoi(c.Param("id"))
	var u database.User
	if err := a.GDB.First(&u, id).Error; err != nil {
		a.fail(c, http.StatusNotFound, "User not found.")
		return
	}
	var in struct {
		Role    *string `json:"role"`
		Enabled *bool   `json:"enabled"`
	}
	if err := c.ShouldBindJSON(&in); err != nil {
		a.fail(c, http.StatusUnprocessableEntity, "invalid payload.")
		return
	}
	updates := map[string]any{}
	if in.Role != nil {
		switch *in.Role {
		case string(constants.RoleOwner), string(constants.RoleCoOwner),
			string(constants.RoleAdmin), string(constants.RoleMember):
			updates["role"] = *in.Role
		default:
			a.fail(c, http.StatusUnprocessableEntity, "invalid role.")
			return
		}
	}
	if in.Enabled != nil {
		updates["enabled"] = *in.Enabled
		if !*in.Enabled {
			updates["session_epoch"] = u.SessionEpoch + 1
		}
	}
	if len(updates) > 0 {
		if err := a.GDB.Model(&u).Updates(updates).Error; err != nil {
			a.internal(c, err)
			return
		}
	}
	if in.Enabled != nil && !*in.Enabled {
		a.GDB.Model(&database.VoidToken{}).
			Where("user_id = ? AND deleted = ?", u.ID, false).
			Updates(map[string]any{"enabled": false})
	}
	sub, name := uv.User.Sub, services.BuildUserView(uv.User).Username
	tid := strconv.Itoa(u.ID)
	detail := map[string]any{}
	if in.Role != nil {
		detail["role"] = *in.Role
	}
	if in.Enabled != nil {
		detail["enabled"] = *in.Enabled
	}
	_ = core.RecordAudit(a.GDB, core.AuditInput{
		Action: "user.update", ActorSub: &sub, ActorName: name, Scope: core.AuditScopeAdmin,
		TargetType: strPtr("user"), TargetID: &tid, Detail: detail, IP: strPtr(clientIP(c)),
	})
	var fresh database.User
	a.GDB.First(&fresh, u.ID)
	c.JSON(http.StatusOK, services.BuildUserView(&fresh))
}

func (a *App) userForceLogout(c *gin.Context) {
	uv := core.GetUser(c)
	id, _ := strconv.Atoi(c.Param("id"))
	var u database.User
	if err := a.GDB.First(&u, id).Error; err != nil {
		a.fail(c, http.StatusNotFound, "User not found.")
		return
	}
	if core.IsOwner(u.Role) && !uv.IsOwner() && u.ID != uv.User.ID {
		a.fail(c, http.StatusForbidden, "Only an owner may act on an owner.")
		return
	}
	if err := a.GDB.Model(&u).Update("session_epoch", u.SessionEpoch+1).Error; err != nil {
		a.internal(c, err)
		return
	}
	c.JSON(http.StatusOK, gin.H{"ok": true})
}

// ---- admin void tokens ----------------------------------------------------

type adminTokenView struct {
	ID            int        `json:"id"`
	UserID        int        `json:"user_id"`
	Username      *string    `json:"username"`
	UserNickname  *string    `json:"user_nickname"`
	Name          string     `json:"name"`
	TokenPrefix   string     `json:"token_prefix"`
	Enabled       bool       `json:"enabled"`
	AutoDisabled  bool       `json:"auto_disabled"`
	Deleted       bool       `json:"deleted"`
	DeletedAt     *time.Time `json:"deleted_at"`
	AllowedModels []string   `json:"allowed_models"`
	RPMLimit      int        `json:"rpm_limit"`
	DailyQuota    int        `json:"daily_quota"`
	TotalRequests int64      `json:"total_requests"`
	TotalTokens   int64      `json:"total_tokens"`
	LastUsedAt    *time.Time `json:"last_used_at"`
	ExpiresAt     *time.Time `json:"expires_at"`
	CreatedAt     time.Time  `json:"created_at"`
	DebugEnabled  bool       `json:"debug_enabled"`
}

func tokenView(t *database.VoidToken, user *database.User) adminTokenView {
	var models []string
	database.DecodeJSON(t.AllowedModels, &models)
	if models == nil {
		models = []string{}
	}
	v := adminTokenView{
		ID: t.ID, UserID: t.UserID, Name: t.Name, TokenPrefix: t.TokenPrefix,
		Enabled: t.Enabled, AutoDisabled: t.AutoDisabled, Deleted: t.Deleted,
		DeletedAt: t.DeletedAt, AllowedModels: models, RPMLimit: t.RPMLimit,
		DailyQuota: t.DailyQuota, TotalRequests: t.TotalRequests, TotalTokens: t.TotalTokens,
		LastUsedAt: t.LastUsedAt, ExpiresAt: t.ExpiresAt, CreatedAt: t.CreatedAt,
		DebugEnabled: t.DebugEnabled,
	}
	if user != nil {
		v.Username = user.Username
		v.UserNickname = user.Name
	}
	return v
}

func (a *App) adminTokensList(c *gin.Context) {
	var rows []database.VoidToken
	if err := a.GDB.Where("deleted = ?", false).Order("id").Find(&rows).Error; err != nil {
		a.internal(c, err)
		return
	}
	users := map[int]*database.User{}
	out := make([]adminTokenView, 0, len(rows))
	for i := range rows {
		t := &rows[i]
		u, ok := users[t.UserID]
		if !ok {
			var found database.User
			if err := a.GDB.First(&found, t.UserID).Error; err == nil {
				u = &found
			}
			users[t.UserID] = u
		}
		out = append(out, tokenView(t, u))
	}
	c.JSON(http.StatusOK, out)
}

func (a *App) adminTokenCreate(c *gin.Context) {
	uv := core.GetUser(c)
	var in struct {
		Name          *string    `json:"name"`
		AllowedModels *[]string  `json:"allowed_models"`
		RPMLimit      *int       `json:"rpm_limit"`
		DailyQuota    *int       `json:"daily_quota"`
		ExpiresAt     *time.Time `json:"expires_at"`
		UserID        *int       `json:"user_id"`
		DebugEnabled  *bool      `json:"debug_enabled"`
	}
	if err := c.ShouldBindJSON(&in); err != nil {
		a.fail(c, http.StatusUnprocessableEntity, "invalid payload.")
		return
	}
	userID := uv.User.ID
	if in.UserID != nil {
		userID = *in.UserID
	}
	var owner database.User
	if err := a.GDB.First(&owner, userID).Error; err != nil {
		a.fail(c, http.StatusNotFound, "User not found.")
		return
	}
	raw, err := core.GenerateVoidToken()
	if err != nil {
		a.internal(c, err)
		return
	}
	name := "default"
	if in.Name != nil && strings.TrimSpace(*in.Name) != "" {
		name = strings.TrimSpace(*in.Name)
	}
	models := []string{}
	if in.AllowedModels != nil {
		models = *in.AllowedModels
	}
	t := database.VoidToken{
		UserID: userID, Name: name, TokenHash: core.HashToken(raw),
		TokenPrefix: raw[:8], Enabled: true,
		AllowedModels: database.JSONOf(models),
	}
	if in.RPMLimit != nil {
		t.RPMLimit = *in.RPMLimit
	}
	if in.DailyQuota != nil {
		t.DailyQuota = *in.DailyQuota
	}
	t.ExpiresAt = in.ExpiresAt
	if in.DebugEnabled != nil {
		t.DebugEnabled = *in.DebugEnabled
	}
	if err := a.GDB.Create(&t).Error; err != nil {
		a.internal(c, err)
		return
	}
	sub, aname := uv.User.Sub, services.BuildUserView(uv.User).Username
	tid := strconv.Itoa(t.ID)
	_ = core.RecordAudit(a.GDB, core.AuditInput{
		Action: "token.create", ActorSub: &sub, ActorName: aname, Scope: core.AuditScopeAdmin,
		TargetType: strPtr("void_token"), TargetID: &tid,
		Detail: map[string]any{"name": t.Name, "user_id": userID}, IP: strPtr(clientIP(c)),
	})
	view := tokenView(&t, &owner)
	c.JSON(http.StatusCreated, gin.H{
		"id": view.ID, "user_id": view.UserID, "username": view.Username,
		"user_nickname": view.UserNickname, "name": view.Name, "token_prefix": view.TokenPrefix,
		"enabled": view.Enabled, "auto_disabled": view.AutoDisabled, "deleted": view.Deleted,
		"deleted_at": view.DeletedAt, "allowed_models": view.AllowedModels,
		"rpm_limit": view.RPMLimit, "daily_quota": view.DailyQuota,
		"total_requests": view.TotalRequests, "total_tokens": view.TotalTokens,
		"last_used_at": view.LastUsedAt, "expires_at": view.ExpiresAt,
		"created_at": view.CreatedAt, "debug_enabled": view.DebugEnabled,
		"token": raw,
	})
}

func (a *App) adminTokenUpdate(c *gin.Context) {
	id, _ := strconv.Atoi(c.Param("id"))
	var t database.VoidToken
	if err := a.GDB.Where("id = ? AND deleted = ?", id, false).First(&t).Error; err != nil {
		a.fail(c, http.StatusNotFound, "Token not found.")
		return
	}
	var in struct {
		Enabled       *bool      `json:"enabled"`
		DebugEnabled  *bool      `json:"debug_enabled"`
		Name          *string    `json:"name"`
		AllowedModels *[]string  `json:"allowed_models"`
		RPMLimit      *int       `json:"rpm_limit"`
		DailyQuota    *int       `json:"daily_quota"`
		ExpiresAt     *time.Time `json:"expires_at"`
	}
	if err := c.ShouldBindJSON(&in); err != nil {
		a.fail(c, http.StatusUnprocessableEntity, "invalid payload.")
		return
	}
	if in.Enabled != nil {
		t.Enabled = *in.Enabled
		if *in.Enabled {
			t.AutoDisabled = false
		}
	}
	if in.DebugEnabled != nil {
		t.DebugEnabled = *in.DebugEnabled
	}
	if in.Name != nil && strings.TrimSpace(*in.Name) != "" {
		t.Name = strings.TrimSpace(*in.Name)
	}
	if in.AllowedModels != nil {
		t.AllowedModels = database.JSONOf(*in.AllowedModels)
	}
	if in.RPMLimit != nil {
		t.RPMLimit = *in.RPMLimit
	}
	if in.DailyQuota != nil {
		t.DailyQuota = *in.DailyQuota
	}
	if in.ExpiresAt != nil {
		t.ExpiresAt = in.ExpiresAt
	}
	if err := a.GDB.Save(&t).Error; err != nil {
		a.internal(c, err)
		return
	}
	var owner database.User
	if err := a.GDB.First(&owner, t.UserID).Error; err == nil {
		c.JSON(http.StatusOK, tokenView(&t, &owner))
		return
	}
	c.JSON(http.StatusOK, tokenView(&t, nil))
}

func (a *App) adminTokenDelete(c *gin.Context) {
	id, _ := strconv.Atoi(c.Param("id"))
	var t database.VoidToken
	if err := a.GDB.First(&t, id).Error; err != nil {
		a.fail(c, http.StatusNotFound, "Token not found.")
		return
	}
	now := time.Now().UTC()
	if err := a.GDB.Model(&t).Updates(map[string]any{
		"deleted": true, "deleted_at": now, "enabled": false,
	}).Error; err != nil {
		a.internal(c, err)
		return
	}
	c.Status(http.StatusNoContent)
}

// RegisterRoleGroupRoutes wires /api/admin/role-groups.
func RegisterRoleGroupRoutes(g *gin.RouterGroup, a *App) {
	g.GET("/role-groups", a.roleGroupsList)
	g.POST("/role-groups", core.RequireOwner(), a.roleGroupCreate)
	g.PATCH("/role-groups/:id", core.RequireOwner(), a.roleGroupUpdate)
	g.DELETE("/role-groups/:id", core.RequireOwner(), a.roleGroupDelete)
	g.GET("/role-groups/:id/members", a.roleGroupMembers)
	g.DELETE("/role-groups/:id/members/:userId", core.RequireOwner(), a.roleGroupMemberDelete)
}

// RegisterUserRoutes wires /api/admin/users.
func RegisterUserRoutes(g *gin.RouterGroup, a *App) {
	g.GET("/users", a.usersList)
	g.PATCH("/users/:id", core.RequireOwner(), a.userUpdate)
	g.POST("/users/:id/force-logout", a.userForceLogout)
}

// RegisterAdminTokenRoutes wires /api/admin/tokens.
func RegisterAdminTokenRoutes(g *gin.RouterGroup, a *App) {
	g.GET("/tokens", a.adminTokensList)
	g.POST("/tokens", core.RequireOwner(), a.adminTokenCreate)
	g.PATCH("/tokens/:id", core.RequireOwner(), a.adminTokenUpdate)
	g.DELETE("/tokens/:id", core.RequireOwner(), a.adminTokenDelete)
}
