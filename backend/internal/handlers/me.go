package handlers

import (
	"net/http"
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

// meUsage returns a minimal usage summary for the caller (Phase 1 stub shape).
func (a *App) meUsage(c *gin.Context) {
	uv := core.GetUser(c)
	var total int64
	_ = a.GDB.Model(&database.RequestLog{}).Where("user_sub = ?", uv.User.Sub).Count(&total).Error
	c.JSON(http.StatusOK, gin.H{
		"totals": gin.H{
			"requests": total, "success": 0, "failures": 0,
			"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
		},
		"daily": []any{}, "weekly": []any{}, "monthly": []any{}, "yearly": []any{},
		"by_user": []any{}, "by_token": []any{}, "by_model": []any{},
		"scope": "self",
	})
}

// RegisterMeRoutes wires /api/me/*.
func RegisterMeRoutes(r *gin.RouterGroup, a *App) {
	m := r.Group("/me", core.RequireUser())
	m.GET("", a.authMe)
	m.GET("/tokens", a.meTokens)
	m.GET("/usage", a.meUsage)
	m.GET("/login-token", func(c *gin.Context) {
		c.JSON(http.StatusOK, gin.H{"enabled": false, "prefix": nil})
	})
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
}
