package core

import (
	"net/http"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"gorm.io/gorm"

	"github.com/siiway/voidswitch/internal/database"
)

// Context keys for a platform API key request.
const (
	CtxPlatformKey = "vs.platformkey"
	// CtxPlatformVia records the transport ("mcp" / "rest") for the audit row.
	CtxPlatformVia = "vs.platformvia"
)

// PlatformCredential is the authenticated automation identity of one request:
// the key row, its owner, and the scopes that survive the owner's current role.
type PlatformCredential struct {
	Key         *database.PlatformAPIKey
	User        *UserView
	Scopes      []string
	ViaMCP      bool
	Fingerprint string
}

// GetPlatformCredential returns the authenticated key, or nil for browser
// sessions and unauthenticated requests.
func GetPlatformCredential(c *gin.Context) *PlatformCredential {
	v, _ := c.Get(CtxPlatformKey)
	kc, _ := v.(*PlatformCredential)
	return kc
}

// Allows reports whether the credential grants an action, honouring the "read"
// shorthand for read-tier actions.
func (p *PlatformCredential) Allows(action string) bool {
	if p == nil {
		return false
	}
	return ReadScopeSatisfied(p.Scopes, action)
}

// AllowsProviderKey reports whether the credential may manage one provider's
// upstream keys.
func (p *PlatformCredential) AllowsProviderKey(slug, action string) bool {
	if p == nil {
		return false
	}
	return ProviderKeyScopeAllows(p.Scopes, slug, action)
}

// bearerToken extracts a bearer token from the Authorization header.
func bearerToken(auth string) string {
	parts := strings.SplitN(strings.TrimSpace(auth), " ", 2)
	if len(parts) == 2 && strings.EqualFold(parts[0], "bearer") {
		return strings.TrimSpace(parts[1])
	}
	return ""
}

// BuildUserView loads the role and role-group memberships for a user.
func BuildUserView(db *gorm.DB, user *database.User) (*UserView, error) {
	uv := &UserView{User: user, Role: user.Role}
	if err := db.Model(&database.RoleGroupMembership{}).Where("user_id = ?", user.ID).
		Pluck("role_group_id", &uv.GroupIDs).Error; err != nil {
		return nil, err
	}
	if err := db.Model(&database.RoleGroupAdminship{}).Where("user_id = ?", user.ID).
		Pluck("role_group_id", &uv.AdminGroupIDs).Error; err != nil {
		return nil, err
	}
	return uv, nil
}

// PlatformKeyAuth authenticates a platform API key (vsapi-…). It loads the owner
// per request — no permission cache — so a role change, a disabled user or a
// disabled key takes effect on the very next call.
//
// Only staff may hold keys: a non-staff owner is rejected even if the key row
// is still enabled, which is the second gate behind the login-time disable.
func PlatformKeyAuth(db *gorm.DB, viaMCP bool) gin.HandlerFunc {
	return func(c *gin.Context) {
		raw := bearerToken(c.GetHeader("Authorization"))
		if raw == "" {
			raw = strings.TrimSpace(c.GetHeader("X-API-Key"))
		}
		if raw == "" {
			c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"detail": "Missing API key."})
			return
		}
		now := time.Now().UTC()
		var key database.PlatformAPIKey
		if err := db.Where("key_hash = ?", HashToken(raw)).First(&key).Error; err != nil {
			c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"detail": "Invalid API key."})
			return
		}
		if !key.Enabled {
			c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"detail": "API key is disabled."})
			return
		}
		if key.ExpiresAt != nil && key.ExpiresAt.Before(now) {
			c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"detail": "API key expired."})
			return
		}
		var user database.User
		if err := db.Where("id = ?", key.UserID).First(&user).Error; err != nil || !user.Enabled {
			c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"detail": "API key owner disabled."})
			return
		}
		if !IsStaff(user.Role) {
			c.AbortWithStatusJSON(http.StatusForbidden, gin.H{"detail": "Platform API keys require staff privileges."})
			return
		}
		uv, err := BuildUserView(db, &user)
		if err != nil {
			c.AbortWithStatusJSON(http.StatusInternalServerError, gin.H{"detail": "Internal Server Error"})
			return
		}
		var scopes []string
		database.DecodeJSON(key.Scopes, &scopes)
		eff := EffectiveScopes(scopes, user.Role)
		if len(eff) == 0 {
			c.AbortWithStatusJSON(http.StatusForbidden, gin.H{"detail": "This API key has no scopes available to your role."})
			return
		}
		cred := &PlatformCredential{
			Key: &key, User: uv, Scopes: eff, ViaMCP: viaMCP,
			Fingerprint: key.KeyPrefix,
		}
		c.Set(CtxUser, uv)
		c.Set(CtxPlatformKey, cred)
		if viaMCP {
			c.Set(CtxPlatformVia, "mcp")
		} else {
			c.Set(CtxPlatformVia, "rest")
		}
		c.Next()
	}
}

// DisablePlatformKeysOnStaffLoss turns off every enabled key of a user who has
// stopped being staff. Re-enabling is manual: a later promotion must not
// silently restore automation access.
func DisablePlatformKeysOnStaffLoss(db *gorm.DB, userID int, role string) error {
	if IsStaff(role) {
		return nil
	}
	reason := database.PlatformAPIKeyDisabledLostStaff
	return db.Model(&database.PlatformAPIKey{}).
		Where("user_id = ? AND enabled = ?", userID, true).
		Updates(map[string]any{"enabled": false, "disabled_reason": reason}).Error
}
