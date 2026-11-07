package handlers

import (
	"log/slog"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"time"

	"github.com/gin-gonic/gin"

	"github.com/siiway/voidswitch/internal/core"
	"github.com/siiway/voidswitch/internal/database"
	"github.com/siiway/voidswitch/internal/services"
)

// authConfig is the public /api/auth/config payload the frontend reads at boot.
func (a *App) authConfig(c *gin.Context) {
	configured := a.Cfg.Prism.ClientID != "" && a.Cfg.Prism.ClientSecret != ""
	c.JSON(http.StatusOK, gin.H{
		"configured":             configured,
		"dev_mode":               a.Cfg.DevAuthBypassActive() || a.Cfg.Server.DevMode,
		"issuer":                 a.Cfg.Prism.Issuer,
		"version":                Version,
		"commit":                 CommitID(),
		"chat_preset_questions":  services.GetSetting("chat_preset_questions"),
		"opencode_default_model": services.GetString("opencode_default_model", ""),
	})
}

// authMe returns the current user (or 401 when unauthenticated).
func (a *App) authMe(c *gin.Context) {
	uv := core.GetUser(c)
	if uv == nil {
		a.fail(c, http.StatusUnauthorized, "Not authenticated.")
		return
	}
	view := services.BuildUserView(uv.User)
	view.RoleGroupNames = a.groupNames(uv.GroupIDs)
	if len(uv.AdminGroupIDs) > 0 {
		view.ManagedGroupIDs = uv.AdminGroupIDs
		view.ManagedGroupNames = a.groupNames(uv.AdminGroupIDs)
	}
	c.JSON(http.StatusOK, view)
}

// devLogin mints an owner session for the deterministic dev identity. It is only
// reachable when the dev-only bypass is active.
func (a *App) devLogin(c *gin.Context) {
	if !a.Cfg.DevAuthBypassActive() {
		a.fail(c, http.StatusNotFound, "Not found.")
		return
	}
	var user database.User
	if err := a.GDB.Where("sub = ?", "dev-mode-user").First(&user).Error; err != nil {
		// Ensure the bypass created the identity (middleware may not have run).
		if _, verr := core.EnsureDevUser(a.GDB); verr != nil {
			a.internal(c, verr)
			return
		}
		if err := a.GDB.Where("sub = ?", "dev-mode-user").First(&user).Error; err != nil {
			a.internal(c, err)
			return
		}
	}
	now := time.Now().UTC()
	_ = a.GDB.Model(&user).Update("last_login_at", now).Error
	token, expires, err := core.MintSession(a.Cfg, &user, a.Cfg.Server.SessionTTLMinutes)
	if err != nil {
		a.internal(c, err)
		return
	}
	c.SetCookie("vs_session", token, expires, "/", "", false, true)
	c.JSON(http.StatusOK, gin.H{
		"access_token": token,
		"token_type":   "bearer",
		"expires_in":   expires,
		"user":         services.BuildUserView(&user),
	})
}

// logout clears the session cookie (stateless JWT, so nothing server-side).
func (a *App) logout(c *gin.Context) {
	c.SetCookie("vs_session", "", -1, "/", "", false, true)
	c.JSON(http.StatusOK, gin.H{"ok": true})
}

// tokenLogin signs in with a long-lived login token (vsl-…).
func (a *App) tokenLogin(c *gin.Context) {
	var in struct {
		Token string `json:"token"`
	}
	if err := c.ShouldBindJSON(&in); err != nil || strings.TrimSpace(in.Token) == "" {
		a.fail(c, http.StatusUnauthorized, "Invalid login token.")
		return
	}
	hash := core.HashToken(strings.TrimSpace(in.Token))
	var user database.User
	if err := a.GDB.Where("login_token_hash = ?", hash).First(&user).Error; err != nil {
		a.fail(c, http.StatusUnauthorized, "Invalid login token.")
		return
	}
	if !user.Enabled || !core.IsStaff(user.Role) {
		a.fail(c, http.StatusUnauthorized, "Invalid login token.")
		return
	}
	now := time.Now().UTC()
	a.GDB.Model(&user).Update("last_login_at", now)
	a.issueSession(c, &user)
}

// issueSession mints a session JWT, sets the cookie, and returns SessionOut.
func (a *App) issueSession(c *gin.Context, user *database.User) {
	token, expires, err := core.MintSession(a.Cfg, user, a.Cfg.Server.SessionTTLMinutes)
	if err != nil {
		a.internal(c, err)
		return
	}
	c.SetCookie("vs_session", token, expires, "/", "", false, true)
	c.JSON(http.StatusOK, gin.H{
		"access_token": token,
		"token_type":   "bearer",
		"expires_in":   expires,
		"user":         services.BuildUserView(user),
	})
}

// login starts the Prism OAuth flow (or returns the authorize URL + state).
func (a *App) login(c *gin.Context) {
	if a.Cfg.Prism.ClientID == "" {
		a.fail(c, http.StatusNotImplemented, "OAuth is not configured.")
		return
	}
	authorizeURL, state, err := services.BuildAuthorizeURL(a.Cfg)
	if err != nil {
		a.internal(c, err)
		return
	}
	if c.Query("redirect") == "1" || c.Query("redirect") == "true" {
		c.Redirect(http.StatusFound, authorizeURL)
		return
	}
	c.JSON(http.StatusOK, gin.H{"authorize_url": authorizeURL, "state": state})
}

// callback completes the Prism OAuth flow and redirects to the SPA.
func (a *App) callback(c *gin.Context) {
	frontend := strings.TrimRight(a.Cfg.Server.FrontendURL, "/")
	target := frontend + "/login/callback"
	code := c.Query("code")
	state := c.Query("state")
	if errParam := c.Query("error"); errParam != "" || code == "" || state == "" {
		e := errParam
		if e == "" {
			e = "missing_code"
		}
		c.Redirect(http.StatusFound, target+"#"+url.Values{"error": {e}}.Encode())
		return
	}
	ident, err := services.ExchangeCode(c.Request.Context(), a.Cfg, code, state)
	if err != nil {
		slog.Warn("oauth callback failed", "err", err)
		c.Redirect(http.StatusFound, target+"#"+url.Values{"error": {"login_failed"}}.Encode())
		return
	}
	user, err := services.UpsertUser(a.GDB, a.Cfg, ident)
	if err == services.ErrLoginDenied {
		c.Redirect(http.StatusFound, target+"#"+url.Values{"error": {"access_denied"}}.Encode())
		return
	}
	if err != nil {
		slog.Warn("oauth upsert failed", "err", err)
		c.Redirect(http.StatusFound, target+"#"+url.Values{"error": {"login_failed"}}.Encode())
		return
	}
	token, expires, err := core.MintSession(a.Cfg, user, a.Cfg.Server.SessionTTLMinutes)
	if err != nil {
		c.Redirect(http.StatusFound, target+"#"+url.Values{"error": {"login_failed"}}.Encode())
		return
	}
	c.Redirect(http.StatusFound, target+"#"+url.Values{
		"access_token": {token},
		"expires_in":   {strconv.Itoa(expires)},
	}.Encode())
}

func (a *App) groupNames(ids []int) []string {
	if len(ids) == 0 {
		return nil
	}
	var names []string
	_ = a.GDB.Model(&database.RoleGroup{}).Where("id IN ?", ids).Pluck("name", &names).Error
	return names
}

// RegisterAuthRoutes wires /api/auth/*.
func RegisterAuthRoutes(r *gin.RouterGroup, a *App, sessionMW gin.HandlerFunc) {
	r.GET("/config", a.authConfig)
	r.GET("/me", sessionMW, a.authMe)
	r.POST("/dev-login", a.devLogin)
	r.POST("/logout", a.logout)
	r.POST("/token-login", a.tokenLogin)
	r.GET("/login", a.login)
	r.GET("/callback", a.callback)
}
