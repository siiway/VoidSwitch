package handlers

import (
	"fmt"
	"math"
	"net/http"
	"sort"
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
	ModelCount                 int           `json:"model_count"`
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
		MemberCount: int(members), ModelCount: a.modelCountByGroup()[g.ID], Mappings: views,
		CallRateLimitWindowSeconds: g.CallRateLimitWindowSeconds,
		CallRateLimitMaxRequests:   g.CallRateLimitMaxRequests,
		CreatedAt:                  g.CreatedAt, UpdatedAt: g.UpdatedAt,
	}
}

// modelCountByGroup tallies, for every role group, how many exposed models list
// it in allowed_role_group_ids. One query covers the whole list, so rendering
// the group cards does not run a query per card.
func (a *App) modelCountByGroup() map[int]int {
	var rows []database.ExposedModel
	a.GDB.Select("id", "allowed_role_group_ids").Find(&rows)
	counts := make(map[int]int, len(rows))
	for i := range rows {
		var ids []int
		database.DecodeJSON(rows[i].AllowedRoleGroupIDs, &ids)
		for _, id := range ids {
			counts[id]++
		}
	}
	return counts
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
	counts := a.modelCountByGroup()
	for i := range rows {
		v := a.roleGroupOut(&rows[i])
		v.ModelCount = counts[rows[i].ID]
		out = append(out, v)
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
	_ = a.audit(c, core.AuditInput{
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
	_ = a.audit(c, core.AuditInput{
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
	uv := core.GetUser(c)
	sub := uv.User.Sub
	tid := strconv.Itoa(g.ID)
	_ = a.audit(c, core.AuditInput{
		Action: "role_group.delete", ActorSub: &sub, ActorName: servicesName(uv),
		Scope: core.AuditScopeAdmin, TargetType: strPtr("role_group"), TargetID: &tid,
		Detail: map[string]any{"name": g.Name}, IP: strPtr(clientIP(c)),
	})
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
	uv := core.GetUser(c)
	id, _ := strconv.Atoi(c.Param("id"))
	if !uv.IsStaff() {
		allowed := false
		for _, gid := range uv.AdminGroupIDs {
			if gid == id {
				allowed = true
				break
			}
		}
		if !allowed {
			a.fail(c, http.StatusForbidden, "You do not administer this role group.")
			return
		}
	}
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
	uv := core.GetUser(c)
	sub := uv.User.Sub
	tid := strconv.Itoa(id)
	_ = a.audit(c, core.AuditInput{
		Action: "role_group.member_remove", ActorSub: &sub, ActorName: servicesName(uv),
		Scope: core.AuditScopeAdmin, TargetType: strPtr("role_group"), TargetID: &tid,
		Detail: map[string]any{"user_id": uid}, IP: strPtr(clientIP(c)),
	})
	c.Status(http.StatusNoContent)
}

// userInGroups reports whether the user is a member of any of the groups.
func (a *App) userInGroups(userID int, groupIDs []int) bool {
	if len(groupIDs) == 0 {
		return false
	}
	var n int64
	a.GDB.Model(&database.RoleGroupMembership{}).
		Where("user_id = ? AND role_group_id IN ?", userID, groupIDs).Count(&n)
	return n > 0
}

// ---- users ----------------------------------------------------------------

// usersList lists users. Staff see everyone; a role-group admin sees only the
// union of their managed groups' members, so the page can be opened by the tier
// that is actually documented to have it.
func (a *App) usersList(c *gin.Context) {
	uv := core.GetUser(c)
	q := a.GDB.Order("id")
	if !uv.IsStaff() {
		managed := uv.AdminGroupIDs
		if len(managed) == 0 {
			c.JSON(http.StatusOK, []services.UserView{})
			return
		}
		members := a.GDB.Model(&database.RoleGroupMembership{}).
			Where("role_group_id IN ?", managed).Distinct().Select("user_id")
		q = q.Where("id IN (?)", members)
	}
	var rows []database.User
	if err := q.Find(&rows).Error; err != nil {
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
	// Demoting a user out of staff also disables their platform API keys; the
	// auth middleware would reject them anyway, but a disabled row is what the
	// API Keys page shows.
	if in.Role != nil {
		if err := core.DisablePlatformKeysOnStaffLoss(a.GDB, u.ID, *in.Role); err != nil {
			a.internal(c, err)
			return
		}
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
	_ = a.audit(c, core.AuditInput{
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
	// A role-group admin's authority stops at their own groups' members.
	if !uv.IsStaff() && u.ID != uv.User.ID {
		if !a.userInGroups(u.ID, uv.AdminGroupIDs) {
			a.fail(c, http.StatusForbidden, "This user is not a member of a role group you administer.")
			return
		}
	}
	if err := a.GDB.Model(&u).Update("session_epoch", u.SessionEpoch+1).Error; err != nil {
		a.internal(c, err)
		return
	}
	sub, actor := uv.User.Sub, servicesName(uv)
	tid := strconv.Itoa(u.ID)
	_ = a.audit(c, core.AuditInput{
		Action: "user.force_logout", ActorSub: &sub, ActorName: actor,
		Scope: core.AuditScopeAdmin, TargetType: strPtr("user"), TargetID: &tid,
		Detail: map[string]any{"sub": u.Sub}, IP: strPtr(clientIP(c)),
	})
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
	_ = a.audit(c, core.AuditInput{
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
	uv := core.GetUser(c)
	sub := uv.User.Sub
	tid := strconv.Itoa(t.ID)
	_ = a.audit(c, core.AuditInput{
		Action: "token.update", ActorSub: &sub, ActorName: servicesName(uv),
		Scope: core.AuditScopeAdmin, TargetType: strPtr("void_token"), TargetID: &tid,
		Detail: map[string]any{"name": t.Name, "enabled": t.Enabled},
		IP:     strPtr(clientIP(c)),
	})
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
	uv := core.GetUser(c)
	sub := uv.User.Sub
	tid := strconv.Itoa(t.ID)
	_ = a.audit(c, core.AuditInput{
		Action: "token.delete", ActorSub: &sub, ActorName: servicesName(uv),
		Scope: core.AuditScopeAdmin, TargetType: strPtr("void_token"), TargetID: &tid,
		Detail: map[string]any{"name": t.Name}, IP: strPtr(clientIP(c)),
	})
	c.Status(http.StatusNoContent)
}

// roleGroupStats aggregates 24h traffic for the union of members of the
// requested role groups — the scoped card a role-group admin sees instead of the
// platform-wide dashboard. Provider/key/proxy counts are deliberately absent:
// those are platform concerns, not per-group ones.
func (a *App) roleGroupStats(c *gin.Context) {
	uv := core.GetUser(c)
	managed := uv.AdminGroupIDs

	// group_ids is the requested scope; when it is present but contains no
	// usable id the answer is an empty scope, not "everything I administer".
	params := c.QueryArray("group_ids")
	var effective []int
	for _, id := range parseIDQuery(c, "group_ids") {
		effective = append(effective, id)
	}
	if len(params) == 0 && len(managed) > 0 {
		effective = append(effective, managed...)
	} else if len(params) == 0 && uv.IsStaff() {
		// Staff without an adminship would otherwise degenerate to "everyone";
		// the platform-wide endpoint is what they want.
		a.fail(c, http.StatusBadRequest,
			"Staff callers must pass an explicit group_ids= (or use /api/admin/stats).")
		return
	}
	sort.Ints(effective)

	if !uv.IsStaff() {
		allowed := map[int]bool{}
		for _, id := range managed {
			allowed[id] = true
		}
		var outside []int
		for _, id := range effective {
			if !allowed[id] {
				outside = append(outside, id)
			}
		}
		if len(outside) > 0 {
			a.fail(c, http.StatusForbidden, fmt.Sprintf("Not an admin of role group(s): %v.", outside))
			return
		}
	}

	var groups []database.RoleGroup
	if len(effective) > 0 {
		if err := a.GDB.Where("id IN ?", effective).Order("id").Find(&groups).Error; err != nil {
			a.internal(c, err)
			return
		}
		if len(groups) != len(effective) {
			found := map[int]bool{}
			for i := range groups {
				found[groups[i].ID] = true
			}
			var missing []int
			for _, id := range effective {
				if !found[id] {
					missing = append(missing, id)
				}
			}
			a.fail(c, http.StatusNotFound, fmt.Sprintf("Role group(s) not found: %v.", missing))
			return
		}
	}

	names := make([]string, 0, len(groups))
	for i := range groups {
		names = append(names, groups[i].Name)
	}
	out := gin.H{
		"group_ids":                  effective,
		"group_names":                names,
		"users":                      0,
		"tokens":                     0,
		"requests_24h":               0,
		"success_24h":                0,
		"failures_24h":               0,
		"tokens_24h":                 0,
		"success_rate_24h":           0.0,
		"avg_first_token_ms_24h":     nil,
		"avg_tokens_per_request_24h": 0.0,
	}
	if len(effective) == 0 {
		c.JSON(http.StatusOK, out)
		return
	}

	// One subquery for the member ids keeps the aggregates off a round trip per
	// id, and a member of several selected groups is counted once.
	memberIDs := a.GDB.Model(&database.RoleGroupMembership{}).
		Where("role_group_id IN ?", effective).Distinct()
	var userCount, tokenCount int64
	a.GDB.Model(&database.User{}).Where("id IN (?)", memberIDs.Select("user_id")).Count(&userCount)
	a.GDB.Model(&database.VoidToken{}).
		Where("deleted = ? AND user_id IN (?)", false, memberIDs.Select("user_id")).Count(&tokenCount)

	var subs []string
	a.GDB.Model(&database.User{}).Where("id IN (?)", memberIDs.Select("user_id")).Pluck("sub", &subs)
	out["users"] = userCount
	out["tokens"] = tokenCount

	if len(subs) > 0 {
		since := time.Now().UTC().Add(-24 * time.Hour)
		var reqs, succ, tokens24 int64
		base := a.GDB.Model(&database.RequestLog{}).Where("ts >= ? AND user_sub IN ?", since, subs)
		base.Count(&reqs)
		a.GDB.Model(&database.RequestLog{}).
			Where("ts >= ? AND user_sub IN ? AND success = ?", since, subs, true).Count(&succ)
		a.GDB.Model(&database.RequestLog{}).
			Where("ts >= ? AND user_sub IN ?", since, subs).
			Select("COALESCE(SUM(total_tokens),0)").Scan(&tokens24)
		var avgTTFT *float64
		a.GDB.Model(&database.RequestLog{}).
			Where("ts >= ? AND user_sub IN ? AND success = ? AND stream = ? AND first_token_ms IS NOT NULL",
				since, subs, true, true).
			Select("AVG(first_token_ms)").Scan(&avgTTFT)

		out["requests_24h"] = reqs
		out["success_24h"] = succ
		out["failures_24h"] = reqs - succ
		out["tokens_24h"] = tokens24
		if reqs > 0 {
			out["success_rate_24h"] = math.Round(float64(succ)/float64(reqs)*1000) / 10
			out["avg_tokens_per_request_24h"] = math.Round(float64(tokens24)/float64(reqs)*10) / 10
		}
		if avgTTFT != nil {
			out["avg_first_token_ms_24h"] = math.Round(*avgTTFT*10) / 10
		}
	}
	c.JSON(http.StatusOK, out)
}

// RegisterRoleGroupRoutes wires /api/admin/role-groups.
func RegisterRoleGroupRoutes(g *gin.RouterGroup, a *App) {
	g.GET("/role-groups", a.roleGroupsList)
	g.POST("/role-groups", core.RequireOwner(), a.roleGroupCreate)
	g.PATCH("/role-groups/:id", core.RequireOwner(), a.roleGroupUpdate)
	g.DELETE("/role-groups/:id", core.RequireOwner(), a.roleGroupDelete)
	g.DELETE("/role-groups/:id/members/:userId", core.RequireOwner(), a.roleGroupMemberDelete)
}

// RegisterRoleGroupScopedRoutes wires the admin reads a *role-group admin* is
// entitled to (not just staff): the scoped dashboard card, the member list of
// the groups they administer, and the user list narrowed to those members.
//
// They are registered outside the staff-gated /admin group on purpose — a group
// middleware runs before the route handler, so a route-level
// RequireStaffOrRoleGroupAdmin cannot rescue a member who was already rejected
// by the group.
func RegisterRoleGroupScopedRoutes(g *gin.RouterGroup, a *App) {
	scoped := g.Group("", core.RequireStaffOrRoleGroupAdmin())
	scoped.GET("/role-groups/stats", a.roleGroupStats)
	scoped.GET("/role-groups/:id/members", a.roleGroupMembers)
	scoped.GET("/users", a.usersList)
}

// RegisterUserRoutes wires /api/admin/users.
func RegisterUserRoutes(g *gin.RouterGroup, a *App) {
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
