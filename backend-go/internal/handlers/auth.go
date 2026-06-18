package handlers

import (
	"fmt"
	"net/http"
	"strings"

	"github.com/gin-gonic/gin"

	"github.com/siiway/voidswitch/internal/config"
	"github.com/siiway/voidswitch/internal/core"
	"github.com/siiway/voidswitch/internal/database"
	"github.com/siiway/voidswitch/internal/models"
)

func getCurrentUser(c *gin.Context) (*database.User, error) {
	auth := c.GetHeader("Authorization")
	token := extractBearer(auth)
	if token == "" {
		return nil, fmt.Errorf("missing bearer token")
	}

	settings := config.Load()
	claims, err := core.DecodeSessionToken(token, settings.Server.SecretKey)
	if err != nil {
		return nil, fmt.Errorf("invalid session token")
	}

	sub := ""
	if s, ok := claims["sub"]; ok {
		sub = fmt.Sprintf("%v", s)
	}
	if sub == "" {
		return nil, fmt.Errorf("missing sub claim")
	}

	var user database.User
	db := database.GetDatabase().DB
	if err := db.Where("sub = ? AND enabled = ?", sub, true).First(&user).Error; err != nil {
		return nil, fmt.Errorf("user not found or disabled")
	}

	return &user, nil
}

func userOut(user *database.User) models.UserOut {
	return models.UserOut{
		ID:          user.ID,
		Sub:         user.Sub,
		Username:    user.Username,
		Email:       user.Email,
		Name:        user.Name,
		Picture:     user.Picture,
		Role:        user.Role,
		PrismRole:   user.PrismRole,
		Enabled:     user.Enabled,
		LastLoginAt: user.LastLoginAt,
		CreatedAt:   user.CreatedAt,
	}
}

func actorLabel(user *database.User) string {
	if user.Name != nil {
		return *user.Name
	}
	if user.Username != nil {
		return *user.Username
	}
	return user.Sub
}

func RegisterAuthRoutes(router *gin.RouterGroup) {
	router.GET("/config", handleAuthConfig)
	router.POST("/dev-login", handleDevLogin)
	router.GET("/login", handleLogin)
	router.GET("/callback", handleCallback)
	router.GET("/me", handleMe)
	router.POST("/logout", handleLogout)
}

func handleAuthConfig(c *gin.Context) {
	settings := config.Load()
	configured := settings.Prism.ClientID != "" && !strings.Contains(settings.Prism.ClientID, "your-prism")
	c.JSON(http.StatusOK, gin.H{
		"configured": configured,
		"dev_mode":   settings.Server.DevMode,
		"issuer":     settings.Prism.Issuer,
		"login_url":  strings.TrimRight(settings.Server.BaseURL, "/") + "/api/auth/login?redirect=1",
	})
}

func handleDevLogin(c *gin.Context) {
	settings := config.Load()
	if !settings.Server.DevMode {
		c.AbortWithStatusJSON(http.StatusNotFound, gin.H{"error": "Not found."})
		return
	}

	db := database.GetDatabase().DB
	user, err := core.DevLoginUser(db, settings)
	if err != nil {
		c.AbortWithStatusJSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}

	ip := c.ClientIP()
	actorSub := user.Sub
	actorName := actorLabel(user)
	core.RecordAudit(db, "auth.dev_login", &actorSub, &actorName, nil, nil, nil, &ip, nil, &settings.Server.SecretKey, "self")

	token, err := core.CreateSessionToken(settings.Server.SecretKey, user.Sub, map[string]any{
		"role": user.Role,
		"name": user.Name,
	}, settings.Server.SessionTTLMinutes)
	if err != nil {
		c.AbortWithStatusJSON(http.StatusInternalServerError, gin.H{"error": "failed to create session"})
		return
	}

	c.JSON(http.StatusOK, models.SessionOut{
		AccessToken: token,
		TokenType:   "bearer",
		ExpiresIn:   settings.Server.SessionTTLMinutes * 60,
		User:        userOut(user),
	})
}

func handleLogin(c *gin.Context) {
	settings := config.Load()
	authorizeURL, state := core.BuildAuthorizeURL(settings)
	c.JSON(http.StatusOK, models.LoginStart{
		AuthorizeURL: authorizeURL,
		State:        state,
	})
}

func handleCallback(c *gin.Context) {
	code := c.Query("code")
	state := c.Query("state")
	errorParam := c.Query("error")

	if errorParam != "" || code == "" || state == "" {
		errMsg := errorParam
		if errMsg == "" {
			errMsg = "missing_code"
		}
		_ = errMsg
		c.AbortWithStatusJSON(http.StatusBadRequest, gin.H{"error": errorParam})
		return
	}

	settings := config.Load()
	db := database.GetDatabase().DB

	identity, err := core.ExchangeCode(settings, code, state)
	if err != nil {
		c.AbortWithStatusJSON(http.StatusBadRequest, gin.H{"error": "login_failed", "detail": err.Error()})
		return
	}

	user, err := core.UpsertUser(db, settings, identity)
	if err != nil {
		c.AbortWithStatusJSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}

	ip := c.ClientIP()
	actorSub := user.Sub
	actorName := actorLabel(user)
	core.RecordAudit(db, "auth.login", &actorSub, &actorName, nil, nil, nil, &ip, nil, &settings.Server.SecretKey, "self")

	token, err := core.CreateSessionToken(settings.Server.SecretKey, user.Sub, map[string]any{
		"role": user.Role,
		"name": user.Name,
	}, settings.Server.SessionTTLMinutes)
	if err != nil {
		c.AbortWithStatusJSON(http.StatusInternalServerError, gin.H{"error": "failed to create session"})
		return
	}

	c.JSON(http.StatusOK, models.SessionOut{
		AccessToken: token,
		TokenType:   "bearer",
		ExpiresIn:   settings.Server.SessionTTLMinutes * 60,
		User:        userOut(user),
	})
}

func handleMe(c *gin.Context) {
	user, err := getCurrentUser(c)
	if err != nil {
		c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"error": err.Error()})
		return
	}
	c.JSON(http.StatusOK, userOut(user))
}

func handleLogout(c *gin.Context) {
	user, err := getCurrentUser(c)
	if err != nil {
		c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"error": err.Error()})
		return
	}

	settings := config.Load()
	db := database.GetDatabase().DB
	ip := c.ClientIP()
	actorSub := user.Sub
	actorName := actorLabel(user)
	core.RecordAudit(db, "auth.logout", &actorSub, &actorName, nil, nil, nil, &ip, nil, &settings.Server.SecretKey, "self")

	c.JSON(http.StatusOK, gin.H{"ok": true})
}
