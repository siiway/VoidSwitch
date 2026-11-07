package core

import (
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"gorm.io/gorm"

	"github.com/siiway/voidswitch/internal/config"
	"github.com/siiway/voidswitch/internal/constants"
	"github.com/siiway/voidswitch/internal/database"
)

// Context keys.
const (
	CtxUser  = "vs.user"
	CtxToken = "vs.voidtoken"
)

// UserView is the authenticated user loaded per request.
type UserView struct {
	User            *database.User
	Role            string
	GroupIDs        []int
	AdminGroupIDs   []int
}

func (u *UserView) IsStaff() bool { return IsStaff(u.Role) }
func (u *UserView) IsOwner() bool { return IsOwner(u.Role) }

// GetUser returns the authenticated user from the gin context.
func GetUser(c *gin.Context) *UserView {
	v, _ := c.Get(CtxUser)
	uv, _ := v.(*UserView)
	return uv
}

// bearer extracts a bearer token from the Authorization header.
func bearer(auth string) string {
	if auth == "" {
		return ""
	}
	parts := strings.SplitN(auth, " ", 2)
	if len(parts) == 2 && strings.EqualFold(parts[0], "bearer") {
		return strings.TrimSpace(parts[1])
	}
	return ""
}

// SessionAuth loads the user from a dashboard session JWT (Authorization bearer
// or the vs_session cookie). It does not require a user (use RequireUser).
func SessionAuth(db *gorm.DB, cfg *config.Settings) gin.HandlerFunc {
	return func(c *gin.Context) {
		token := bearer(c.GetHeader("Authorization"))
		if token == "" {
			if ck, err := c.Cookie("vs_session"); err == nil {
				token = ck
			}
		}

		// Dev-only bypass: mint/reuse the synthetic identity.
		if token == "" && cfg.DevAuthBypassActive() {
			if uv, err := devUserView(db); err == nil {
				c.Set(CtxUser, uv)
			}
			c.Next()
			return
		}

		if token == "" {
			c.Next()
			return
		}

		claims, err := DecodeSessionToken(token, cfg.Server.SecretKey)
		if err != nil {
			c.Next()
			return
		}
		sub, _ := claims["sub"].(string)
		if sub == "" {
			c.Next()
			return
		}

		var user database.User
		if err := db.Where("sub = ?", sub).First(&user).Error; err != nil {
			c.Next()
			return
		}
		// Session epoch check: bumping invalidates older sessions.
		if epoch, ok := claims["epoch"].(float64); ok && int(epoch) != user.SessionEpoch {
			c.Next()
			return
		}
		if !user.Enabled {
			c.Next()
			return
		}

		uv, err := buildUserView(db, &user)
		if err != nil {
			c.Next()
			return
		}
		c.Set(CtxUser, uv)
		c.Next()
	}
}

func buildUserView(db *gorm.DB, user *database.User) (*UserView, error) {
	uv := &UserView{User: user, Role: user.Role}
	_ = db.Model(&database.RoleGroupMembership{}).Where("user_id = ?", user.ID).
		Pluck("role_group_id", &uv.GroupIDs).Error
	_ = db.Model(&database.RoleGroupAdminship{}).Where("user_id = ?", user.ID).
		Pluck("role_group_id", &uv.AdminGroupIDs).Error
	return uv, nil
}

// EnsureDevUser ensures the deterministic dev identity exists as an owner.
func EnsureDevUser(db *gorm.DB) (*UserView, error) { return devUserView(db) }

// devUserView ensures the deterministic dev identity exists as an owner.
func devUserView(db *gorm.DB) (*UserView, error) {
	var user database.User
	err := db.Where("sub = ?", constants.DevUserSub).First(&user).Error
	if err == gorm.ErrRecordNotFound {
		now := time.Now().UTC()
		username := "dev"
		email := "dev@voidswitch.local"
		name := "Developer (dev mode)"
		user = database.User{
			Sub:                    constants.DevUserSub,
			Username:               &username,
			Email:                  &email,
			Name:                   &name,
			Role:                   string(constants.RoleOwner),
			Enabled:                true,
			TeamIDs:                database.JSONOf([]string{}),
			LastLoginAt:            &now,
		}
		if err := db.Create(&user).Error; err != nil {
			return nil, err
		}
	} else if err != nil {
		return nil, err
	}
	if user.Role != string(constants.RoleOwner) || !user.Enabled {
		user.Role = string(constants.RoleOwner)
		user.Enabled = true
		_ = db.Model(&user).Updates(map[string]any{"role": user.Role, "enabled": true}).Error
	}
	return buildUserView(db, &user)
}

// RequireUser rejects unauthenticated requests with 401.
func RequireUser() gin.HandlerFunc {
	return func(c *gin.Context) {
		if GetUser(c) == nil {
			c.AbortWithStatusJSON(401, gin.H{"detail": "Not authenticated."})
			return
		}
		c.Next()
	}
}

// RequireStaff rejects non-staff with 403.
func RequireStaff() gin.HandlerFunc {
	return func(c *gin.Context) {
		uv := GetUser(c)
		if uv == nil {
			c.AbortWithStatusJSON(401, gin.H{"detail": "Not authenticated."})
			return
		}
		if !uv.IsStaff() {
			c.AbortWithStatusJSON(403, gin.H{"detail": "Staff privileges required."})
			return
		}
		c.Next()
	}
}

// RequireOwner rejects non-owners with 403.
func RequireOwner() gin.HandlerFunc {
	return func(c *gin.Context) {
		uv := GetUser(c)
		if uv == nil {
			c.AbortWithStatusJSON(401, gin.H{"detail": "Not authenticated."})
			return
		}
		if !uv.IsOwner() {
			c.AbortWithStatusJSON(403, gin.H{"detail": "Owner privileges required."})
			return
		}
		c.Next()
	}
}

// MintSession issues a session JWT for a user with the current epoch.
func MintSession(cfg *config.Settings, user *database.User, ttlMinutes int) (string, int, error) {
	if ttlMinutes < 1 {
		ttlMinutes = cfg.Server.SessionTTLMinutes
	}
	tok, err := CreateSessionToken(cfg.Server.SecretKey, user.Sub, map[string]any{
		"role":  user.Role,
		"name":  deref(user.Name),
		"epoch": user.SessionEpoch,
	}, ttlMinutes)
	if err != nil {
		return "", 0, err
	}
	return tok, ttlMinutes * 60, nil
}

func deref(s *string) string {
	if s == nil {
		return ""
	}
	return *s
}
