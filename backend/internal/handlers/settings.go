package handlers

import (
	"net/http"

	"github.com/gin-gonic/gin"

	"github.com/siiway/voidswitch/internal/core"
	"github.com/siiway/voidswitch/internal/services"
)

type settingsUpdateIn struct {
	Values map[string]any `json:"values"`
}

// settingsUpdate persists settings changes (owner-only, enforced by route group).
func (a *App) settingsUpdate(c *gin.Context) {
	var in settingsUpdateIn
	if err := c.ShouldBindJSON(&in); err != nil {
		a.fail(c, http.StatusBadRequest, "Invalid settings payload.")
		return
	}
	merged, err := services.UpdateSettings(a.GDB, in.Values)
	if err != nil {
		a.internal(c, err)
		return
	}
	uv := core.GetUser(c)
	sub := uv.User.Sub
	name := services.BuildUserView(uv.User).Username
	_ = core.RecordAudit(a.GDB, core.AuditInput{
		Action: "settings.update", ActorSub: &sub, ActorName: name,
		Scope: core.AuditScopeAdmin, TargetType: strPtr("settings"),
		Detail: map[string]any{"keys": keysOf(in.Values)}, IP: strPtr(clientIP(c)),
		SecretKey: a.Cfg.Server.SecretKey,
	})
	c.JSON(http.StatusOK, gin.H{"values": merged})
}

func keysOf(m map[string]any) []string {
	out := make([]string, 0, len(m))
	for k := range m {
		out = append(out, k)
	}
	return out
}

func strPtr(s string) *string { return &s }

// systemInfo returns version/commit/runtime info.
func (a *App) systemInfo(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{
		"version":     Version,
		"commit":      CommitID(),
		"environment": a.Cfg.Environment,
		"dev_mode":    a.Cfg.DevAuthBypassActive() || a.Cfg.Server.DevMode,
	})
}

// RegisterSettingsRoutes wires settings + system endpoints.
func RegisterSettingsRoutes(admin *gin.RouterGroup, a *App) {
	admin.GET("/settings", a.settingsGet)
	admin.PUT("/settings", core.RequireOwner(), a.settingsUpdate)
	admin.GET("/system", a.systemInfo)
}
