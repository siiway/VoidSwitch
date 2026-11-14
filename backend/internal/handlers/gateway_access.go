package handlers

import (
	"fmt"
	"path/filepath"
	"time"

	"github.com/gin-gonic/gin"

	"github.com/siiway/voidswitch/internal/core"
	"github.com/siiway/voidswitch/internal/database"
	"github.com/siiway/voidswitch/internal/redisx"
	"github.com/siiway/voidswitch/internal/services"
)

// gatewayAccessError carries the HTTP status + message for a denied call.
type gatewayAccessError struct {
	Status int
	Msg    string
}

// checkGatewayAccess enforces the per-token / per-user / per-model gates that
// the Python gateway applied before dispatch. Returns the resolved public model
// id (alias/passthrough preserved) or an error to return to the caller.
func (a *App) checkGatewayAccess(c *gin.Context, uv *core.UserView, token *database.VoidToken, model string) (*gatewayAccessError, string) {
	// 1. allowed_models allow-list (glob-aware; empty = all).
	if !modelAllowedForToken(token, model) {
		return &gatewayAccessError{403, fmt.Sprintf("Model '%s' is not permitted for this token.", model)}, ""
	}

	// 2. RPM limit (sliding 60s window, Redis).
	if token.RPMLimit > 0 && a.RDB != nil {
		ok, err := a.RDB.RateLimiter("rate:rpm").Acquire(c.Request.Context(),
			fmt.Sprintf("rpm:%d", token.ID), 60, token.RPMLimit)
		if err == nil && !ok {
			return &gatewayAccessError{429, fmt.Sprintf("Rate limit exceeded (%d req/min).", token.RPMLimit)}, ""
		}
	}

	// 3. daily quota (count today's logged requests for the token).
	if token.DailyQuota > 0 {
		startOfDay := time.Now().UTC().Truncate(24 * time.Hour)
		var used int64
		a.GDB.Model(&database.RequestLog{}).
			Where("token_id = ? AND ts >= ?", token.ID, startOfDay).Count(&used)
		if used >= int64(token.DailyQuota) {
			return &gatewayAccessError{429, fmt.Sprintf("Daily request quota exceeded (%d requests/day).", token.DailyQuota)}, ""
		}
	}

	// 4. resolve the public model to an exposed-model row (or a passthrough id).
	entry, exposedID, err := a.resolvePublicModel(model)
	if err != nil {
		return &gatewayAccessError{404, err.Error()}, ""
	}
	if entry != nil && !entry.Enabled {
		return &gatewayAccessError{404, fmt.Sprintf("Model '%s' is not available under this id.", model)}, ""
	}

	// 5. role-group model access (moderators always allowed).
	isMod := uv.IsStaff()
	if !isMod {
		if entry == nil || !services.ModelAllowedForGroups(entry, uv.GroupIDs, false) {
			return &gatewayAccessError{403, fmt.Sprintf("Model '%s' is not available to your role group.", model)}, ""
		}
	}

	// 6. per-role-group call rate limit (abuse guard, owners included).
	if a.RDB != nil && len(uv.GroupIDs) > 0 {
		cands := []struct {
			key string
			max int
			win float64
		}{}
		var groups []database.RoleGroup
		a.GDB.Where("id IN ?", uv.GroupIDs).Find(&groups)
		for i := range groups {
			g := &groups[i]
			if g.CallRateLimitMaxRequests <= 0 || g.CallRateLimitWindowSeconds <= 0 {
				continue
			}
			cands = append(cands, struct {
				key string
				max int
				win float64
			}{fmt.Sprintf("call:%d:g%d", uv.User.ID, g.ID), g.CallRateLimitMaxRequests, float64(g.CallRateLimitWindowSeconds)})
		}
		if len(cands) > 0 {
			lims := make([]redisx.LimitCandidate, 0, len(cands))
			for _, c := range cands {
				lims = append(lims, redisx.LimitCandidate{Key: c.key, MaxRequests: c.max, WindowSeconds: c.win})
			}
			ok, err := a.RDB.RateLimiter("rate:call").ReserveAny(c.Request.Context(), lims)
			if err == nil && !ok {
				return &gatewayAccessError{429, "Call rate limit exceeded for all of your role groups. Slow down."}, ""
			}
		}
	}

	return nil, exposedID
}

// modelAllowedForToken reports whether the token's allowed_models permits model.
func modelAllowedForToken(token *database.VoidToken, model string) bool {
	var allowed []string
	database.DecodeJSON(token.AllowedModels, &allowed)
	if len(allowed) == 0 {
		return true
	}
	for _, p := range allowed {
		if p == "*" || p == model {
			return true
		}
		if ok, _ := filepath.Match(p, model); ok {
			return true
		}
	}
	return false
}

// resolvePublicModel maps a public model id to its exposed-model row. Passthrough
// ids ("slug/exposed") are validated against the provider's whitelist and return
// (nil, id, nil) — routed separately. Returns an error for unknown/disabled ids.
func (a *App) resolvePublicModel(model string) (*database.ExposedModel, string, error) {
	if i := indexSlash(model); i >= 0 {
		slug, exposed := model[:i], model[i+1:]
		var p database.Provider
		if err := a.GDB.Where("slug = ?", slug).First(&p).Error; err == nil &&
			p.Enabled && p.PassthroughEnabled {
			var list []string
			database.DecodeJSON(p.PassthroughModels, &list)
			for _, e := range list {
				if parsePassthroughExposed(e) == exposed {
					return nil, model, nil
				}
			}
			return nil, "", fmt.Errorf("Model '%s' is not in this provider's passthrough list.", model)
		}
	}
	var m database.ExposedModel
	if err := a.GDB.Where("model_id = ?", model).First(&m).Error; err != nil {
		return nil, "", fmt.Errorf("Model '%s' is not available under this id.", model)
	}
	return &m, m.ModelID, nil
}

func indexSlash(s string) int {
	for i := 0; i < len(s); i++ {
		if s[i] == '/' {
			return i
		}
	}
	return -1
}

// gatewayUserView builds a UserView (role + role-group membership) for a token's
// owner so the gateway gates can apply without a dashboard session.
func (a *App) gatewayUserView(user *database.User) *core.UserView {
	uv := &core.UserView{User: user, Role: user.Role}
	_ = a.GDB.Model(&database.RoleGroupMembership{}).Where("user_id = ?", user.ID).
		Pluck("role_group_id", &uv.GroupIDs)
	_ = a.GDB.Model(&database.RoleGroupAdminship{}).Where("user_id = ?", user.ID).
		Pluck("role_group_id", &uv.AdminGroupIDs)
	return uv
}
