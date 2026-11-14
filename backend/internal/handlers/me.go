package handlers

import (
	"net/http"
	"strconv"
	"time"

	"github.com/gin-gonic/gin"

	"github.com/siiway/voidswitch/internal/core"
	"github.com/siiway/voidswitch/internal/database"
	"github.com/siiway/voidswitch/internal/services"
)

type voidTokenView struct {
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

func toTokenView(t *database.VoidToken, username, nickname *string) voidTokenView {
	var allowed []string
	database.DecodeJSON(t.AllowedModels, &allowed)
	if allowed == nil {
		allowed = []string{}
	}
	return voidTokenView{
		ID: t.ID, UserID: t.UserID, Username: username, UserNickname: nickname,
		Name: t.Name, TokenPrefix: t.TokenPrefix, Enabled: t.Enabled,
		AutoDisabled: t.AutoDisabled, Deleted: t.Deleted, DeletedAt: t.DeletedAt,
		AllowedModels: allowed, RPMLimit: t.RPMLimit, DailyQuota: t.DailyQuota,
		TotalRequests: t.TotalRequests, TotalTokens: t.TotalTokens,
		LastUsedAt: t.LastUsedAt, ExpiresAt: t.ExpiresAt, CreatedAt: t.CreatedAt,
		DebugEnabled: t.DebugEnabled,
	}
}

// meTokens lists the caller's Void-Tokens.
func (a *App) meTokens(c *gin.Context) {
	uv := core.GetUser(c)
	var tokens []database.VoidToken
	if err := a.GDB.Where("user_id = ? AND deleted = ?", uv.User.ID, false).
		Order("id").Find(&tokens).Error; err != nil {
		a.internal(c, err)
		return
	}
	out := make([]voidTokenView, 0, len(tokens))
	for i := range tokens {
		out = append(out, toTokenView(&tokens[i], nil, nil))
	}
	c.JSON(http.StatusOK, out)
}

// meUsage returns the caller's {requests, tokens, token_count} summary. Zeros
// are returned (never null) so the dashboard renders 0 placeholders.
func (a *App) meUsage(c *gin.Context) {
	uv := core.GetUser(c)
	var requests, tokens int64
	a.GDB.Model(&database.RequestLog{}).Where("user_sub = ?", uv.User.Sub).
		Select("COALESCE(COUNT(*),0)").Scan(&requests)
	a.GDB.Model(&database.RequestLog{}).Where("user_sub = ?", uv.User.Sub).
		Select("COALESCE(SUM(total_tokens),0)").Scan(&tokens)
	var tokenCount int64
	a.GDB.Model(&database.VoidToken{}).Where("user_id = ? AND deleted = ?", uv.User.ID, false).Count(&tokenCount)
	c.JSON(http.StatusOK, gin.H{
		"requests": requests, "tokens": tokens, "token_count": tokenCount,
	})
}

// RegisterMeRoutes wires /api/me/*.
func RegisterMeRoutes(r *gin.RouterGroup, a *App) {
	m := r.Group("/me", core.RequireUser())
	m.GET("", a.authMe)
	m.GET("/tokens", a.meTokens)
	m.GET("/usage", a.meUsage)
	m.GET("/login-token", a.meLoginTokenStatus)
	m.POST("/login-token/rotate", a.meLoginTokenRotate)
	m.POST("/tokens", a.meTokenCreate)
	m.PATCH("/tokens/:id", a.meTokenUpdate)
	m.DELETE("/tokens/:id", a.meTokenDelete)
	m.POST("/tokens/:id/rotate", a.meTokenRotate)
	m.GET("/tokens/usage", func(c *gin.Context) { c.JSON(http.StatusOK, gin.H{}) })
}

// announcementsList returns announcements visible to the caller.
func (a *App) announcementsList(c *gin.Context) {
	uv := core.GetUser(c)
	q := a.GDB.Order("id DESC")
	if !uv.IsOwner() {
		q = q.Limit(100)
	}
	var rows []database.Announcement
	if err := q.Find(&rows).Error; err != nil {
		a.internal(c, err)
		return
	}
	out := make([]services.AnnouncementView, 0, len(rows))
	for i := range rows {
		r := &rows[i]
		var targets []int
		database.DecodeJSON(r.TargetRoleGroupIDs, &targets)
		if targets == nil {
			targets = []int{}
		}
		out = append(out, services.AnnouncementView{
			ID: r.ID, Title: r.Title, Body: r.Body, CreatedBy: r.CreatedBy,
			CreatedByName: r.CreatedByName, CreatedByRole: r.CreatedByRole,
			Edited: r.Edited, TargetRoleGroupIDs: targets,
			CreatedAt: r.CreatedAt, UpdatedAt: r.UpdatedAt,
			CanManage: uv.IsStaff(),
		})
	}
	c.JSON(http.StatusOK, out)
}

// RegisterAnnouncementRoutes wires announcements (mounted under any authed group).
func RegisterAnnouncementRoutes(r *gin.RouterGroup, a *App) {
	g := r.Group("/announcements", core.RequireUser())
	g.GET("", a.announcementsList)
	g.POST("", a.announcementCreate)
	g.PATCH("/:id", a.announcementUpdate)
	g.DELETE("/:id", a.announcementDelete)
}

// meTokenCreate creates a new Void-Token for the caller (secret shown once).
func (a *App) meTokenCreate(c *gin.Context) {
	uv := core.GetUser(c)
	var in struct {
		Name          string   `json:"name"`
		AllowedModels []string `json:"allowed_models"`
		RPMLimit      int      `json:"rpm_limit"`
		DailyQuota    int      `json:"daily_quota"`
	}
	_ = c.ShouldBindJSON(&in)
	if in.Name == "" {
		in.Name = "default"
	}
	raw, err := core.GenerateVoidToken()
	if err != nil {
		a.internal(c, err)
		return
	}
	if in.AllowedModels == nil {
		in.AllowedModels = []string{}
	}
	t := database.VoidToken{
		UserID: uv.User.ID, Name: in.Name, TokenHash: core.HashToken(raw),
		TokenPrefix: raw[:8], Enabled: true, AllowedModels: database.JSONOf(in.AllowedModels),
		RPMLimit: in.RPMLimit, DailyQuota: in.DailyQuota, DebugEnabled: false,
	}
	if err := a.GDB.Create(&t).Error; err != nil {
		a.internal(c, err)
		return
	}
	view := toTokenView(&t, uv.User.Username, nil)
	c.JSON(http.StatusCreated, gin.H{
		"id": view.ID, "user_id": view.UserID, "username": view.Username,
		"name": view.Name, "token_prefix": view.TokenPrefix, "enabled": view.Enabled,
		"allowed_models": view.AllowedModels, "rpm_limit": view.RPMLimit,
		"daily_quota": view.DailyQuota, "total_requests": 0, "total_tokens": 0,
		"created_at": view.CreatedAt, "token": raw,
	})
}

func (a *App) meTokenUpdate(c *gin.Context) {
	uv := core.GetUser(c)
	id, _ := strconv.Atoi(c.Param("id"))
	var t database.VoidToken
	if err := a.GDB.Where("id = ? AND user_id = ?", id, uv.User.ID).First(&t).Error; err != nil {
		a.fail(c, http.StatusNotFound, "Token not found.")
		return
	}
	var in struct {
		Name          *string   `json:"name"`
		Enabled       *bool     `json:"enabled"`
		DebugEnabled  *bool     `json:"debug_enabled"`
		AllowedModels *[]string `json:"allowed_models"`
		RPMLimit      *int      `json:"rpm_limit"`
		DailyQuota    *int      `json:"daily_quota"`
	}
	if err := c.ShouldBindJSON(&in); err != nil {
		a.fail(c, http.StatusUnprocessableEntity, "invalid payload.")
		return
	}
	if in.Name != nil {
		t.Name = *in.Name
	}
	if in.Enabled != nil {
		t.Enabled = *in.Enabled
	}
	if in.DebugEnabled != nil {
		t.DebugEnabled = *in.DebugEnabled
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
	if err := a.GDB.Save(&t).Error; err != nil {
		a.internal(c, err)
		return
	}
	c.JSON(http.StatusOK, toTokenView(&t, uv.User.Username, nil))
}

func (a *App) meTokenDelete(c *gin.Context) {
	uv := core.GetUser(c)
	id, _ := strconv.Atoi(c.Param("id"))
	now := time.Now().UTC()
	res := a.GDB.Model(&database.VoidToken{}).
		Where("id = ? AND user_id = ?", id, uv.User.ID).
		Updates(map[string]any{"deleted": true, "deleted_at": now, "enabled": false})
	if res.Error != nil {
		a.internal(c, res.Error)
		return
	}
	c.Status(http.StatusNoContent)
}

func (a *App) meTokenRotate(c *gin.Context) {
	uv := core.GetUser(c)
	id, _ := strconv.Atoi(c.Param("id"))
	var t database.VoidToken
	if err := a.GDB.Where("id = ? AND user_id = ?", id, uv.User.ID).First(&t).Error; err != nil {
		a.fail(c, http.StatusNotFound, "Token not found.")
		return
	}
	raw, err := core.GenerateVoidToken()
	if err != nil {
		a.internal(c, err)
		return
	}
	t.TokenHash = core.HashToken(raw)
	t.TokenPrefix = raw[:8]
	if err := a.GDB.Save(&t).Error; err != nil {
		a.internal(c, err)
		return
	}
	c.JSON(http.StatusOK, gin.H{
		"id": t.ID, "user_id": t.UserID, "username": uv.User.Username, "name": t.Name,
		"token_prefix": t.TokenPrefix, "enabled": t.Enabled,
		"allowed_models": []string{}, "rpm_limit": t.RPMLimit, "daily_quota": t.DailyQuota,
		"created_at": t.CreatedAt, "token": raw,
	})
}

// ---- announcement write --------------------------------------------------

type announcementIn struct {
	Title              *string `json:"title"`
	Body               *string `json:"body"`
	TargetRoleGroupIDs *[]int  `json:"target_role_group_ids"`
}

func (a *App) announcementCreate(c *gin.Context) {
	uv := core.GetUser(c)
	if !uv.IsStaff() {
		a.fail(c, http.StatusForbidden, "Staff privileges required.")
		return
	}
	var in announcementIn
	if err := c.ShouldBindJSON(&in); err != nil || in.Title == nil || *in.Title == "" {
		a.fail(c, http.StatusUnprocessableEntity, "title is required.")
		return
	}
	body := ""
	if in.Body != nil {
		body = *in.Body
	}
	targets := []int{}
	if in.TargetRoleGroupIDs != nil {
		targets = *in.TargetRoleGroupIDs
	}
	row := database.Announcement{
		Title: *in.Title, Body: body, CreatedBy: &uv.User.ID,
		CreatedByName: uv.User.Username, CreatedByRole: uv.Role,
		TargetRoleGroupIDs: database.JSONOf(targets),
	}
	if err := a.GDB.Create(&row).Error; err != nil {
		a.internal(c, err)
		return
	}
	c.JSON(http.StatusCreated, services.AnnouncementView{
		ID: row.ID, Title: row.Title, Body: row.Body, CreatedBy: row.CreatedBy,
		CreatedByName: row.CreatedByName, CreatedByRole: row.CreatedByRole,
		TargetRoleGroupIDs: targets, CreatedAt: row.CreatedAt, UpdatedAt: row.UpdatedAt, CanManage: true,
	})
}

func (a *App) announcementUpdate(c *gin.Context) {
	uv := core.GetUser(c)
	id, _ := strconv.Atoi(c.Param("id"))
	var row database.Announcement
	if err := a.GDB.First(&row, id).Error; err != nil {
		a.fail(c, http.StatusNotFound, "Announcement not found.")
		return
	}
	if !uv.IsStaff() {
		a.fail(c, http.StatusForbidden, "Staff privileges required.")
		return
	}
	var in announcementIn
	if err := c.ShouldBindJSON(&in); err != nil {
		a.fail(c, http.StatusUnprocessableEntity, "invalid payload.")
		return
	}
	if in.Title != nil {
		row.Title = *in.Title
	}
	if in.Body != nil {
		row.Body = *in.Body
	}
	if in.TargetRoleGroupIDs != nil {
		row.TargetRoleGroupIDs = database.JSONOf(*in.TargetRoleGroupIDs)
	}
	row.Edited = true
	if err := a.GDB.Save(&row).Error; err != nil {
		a.internal(c, err)
		return
	}
	var targets []int
	database.DecodeJSON(row.TargetRoleGroupIDs, &targets)
	c.JSON(http.StatusOK, services.AnnouncementView{
		ID: row.ID, Title: row.Title, Body: row.Body, CreatedBy: row.CreatedBy,
		CreatedByName: row.CreatedByName, CreatedByRole: row.CreatedByRole, Edited: row.Edited,
		TargetRoleGroupIDs: targets, CreatedAt: row.CreatedAt, UpdatedAt: row.UpdatedAt, CanManage: true,
	})
}

func (a *App) announcementDelete(c *gin.Context) {
	uv := core.GetUser(c)
	id, _ := strconv.Atoi(c.Param("id"))
	var row database.Announcement
	if err := a.GDB.First(&row, id).Error; err != nil {
		a.fail(c, http.StatusNotFound, "Announcement not found.")
		return
	}
	if !uv.IsStaff() {
		a.fail(c, http.StatusForbidden, "Staff privileges required.")
		return
	}
	a.GDB.Delete(&row)
	c.Status(http.StatusNoContent)
}

// meLoginTokenStatus reports whether the caller (staff) has an emergency login
// token configured.
func (a *App) meLoginTokenStatus(c *gin.Context) {
	uv := core.GetUser(c)
	if !uv.IsStaff() {
		a.fail(c, http.StatusForbidden, "Login tokens are only available to staff.")
		return
	}
	c.JSON(http.StatusOK, gin.H{
		"enabled": uv.User.LoginTokenHash != nil,
		"prefix":  uv.User.LoginTokenPrefix,
	})
}

// meLoginTokenRotate mints a new emergency login token (shown once).
func (a *App) meLoginTokenRotate(c *gin.Context) {
	uv := core.GetUser(c)
	if !uv.IsStaff() {
		a.fail(c, http.StatusForbidden, "Login tokens are only available to staff.")
		return
	}
	secret, err := core.GenerateLoginToken()
	if err != nil {
		a.internal(c, err)
		return
	}
	hash := core.HashToken(secret)
	prefix := core.TokenFingerprint(secret)
	if err := a.GDB.Model(&database.User{}).Where("id = ?", uv.User.ID).
		Updates(map[string]any{"login_token_hash": hash, "login_token_prefix": prefix}).Error; err != nil {
		a.internal(c, err)
		return
	}
	sub := uv.User.Sub
	tid := strconv.Itoa(uv.User.ID)
	_ = core.RecordAudit(a.GDB, core.AuditInput{
		Action: "me.login_token.rotate", ActorSub: &sub, ActorName: uv.User.Username,
		Scope: core.AuditScopeSelf, TargetType: strPtr("user"), TargetID: &tid,
		Detail: map[string]any{"prefix": prefix}, IP: strPtr(clientIP(c)),
	})
	c.JSON(http.StatusOK, gin.H{"enabled": true, "prefix": prefix, "token": secret})
}
