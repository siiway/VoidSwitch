package handlers

import (
	"net/http"

	"github.com/gin-gonic/gin"

	"github.com/siiway/voidswitch/internal/core"
	"github.com/siiway/voidswitch/internal/services"
	"github.com/siiway/voidswitch/internal/services/providers"
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
	_ = a.audit(c, core.AuditInput{
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

// nullableStr maps "" to a nil pointer, so an "absent" string column stores SQL
// NULL rather than an empty string and the dashboard's `?? "—"` fallback fires.
func nullableStr(s string) *string {
	if s == "" {
		return nil
	}
	return &s
}

func strPtr(s string) *string { return &s }

// systemInfo returns version/commit/runtime info.
func (a *App) systemInfo(c *gin.Context) {
	var taskStatus []any
	if a.Tasks != nil {
		for _, s := range a.Tasks.Status() {
			taskStatus = append(taskStatus, s)
		}
	}
	if taskStatus == nil {
		taskStatus = []any{}
	}
	c.JSON(http.StatusOK, gin.H{
		"version":     Version,
		"commit":      CommitID(),
		"environment": a.Cfg.Environment,
		"dev_mode":    a.Cfg.DevAuthBypassActive() || a.Cfg.Server.DevMode,
		"adapters":    providers.AdapterCatalog(),
		"tasks":       taskStatus,
	})
}

// RegisterSettingsRoutes wires settings + system endpoints.
func RegisterSettingsRoutes(admin *gin.RouterGroup, a *App) {
	admin.GET("/settings", a.settingsGet)
	admin.PUT("/settings", core.RequireOwner(), a.settingsUpdate)
	admin.POST("/settings/clean-logs", core.RequireOwner(), a.settingsCleanLogs)
	admin.POST("/settings/test-static-proxy", a.settingsTestStaticProxy)
	admin.GET("/system", a.systemInfo)
}

// settingsCleanLogs prunes old request/audit logs and strips debug bodies that
// exceed the debug retention window. Owner-only per permission policy.
func (a *App) settingsCleanLogs(c *gin.Context) {
	res := services.CleanupLogs(a.GDB)
	uv := core.GetUser(c)
	sub := uv.User.Sub
	_ = a.audit(c, core.AuditInput{
		Action: "logs.cleanup", ActorSub: &sub, ActorName: servicesName(uv),
		Scope: core.AuditScopeAdmin, TargetType: strPtr("logs"),
		Detail: map[string]any{
			"deleted_request_logs":  res.DeletedRequests,
			"deleted_audit_logs":    res.DeletedAudits,
			"stripped_debug_logs":   res.StrippedDebug,
			"deleted_heatmap_days":  res.DeletedHeatmapDays,
			"deleted_session_spans": res.DeletedSpans,
			"deleted_cooldowns":     res.DeletedCooldowns,
			"deleted_node_samples":  res.DeletedNodeSamples,
		},
		IP: strPtr(clientIP(c)),
	})
	c.JSON(http.StatusOK, res)
}

// settingsTestStaticProxy attempts a HEAD/GET through the given proxy URL.
func (a *App) settingsTestStaticProxy(c *gin.Context) {
	var in struct {
		URL string `json:"url"`
	}
	if err := c.ShouldBindJSON(&in); err != nil || in.URL == "" {
		a.fail(c, http.StatusUnprocessableEntity, "url is required.")
		return
	}
	ok, status, latency, errStr := services.ProbeProxy(c.Request.Context(), in.URL)
	resp := gin.H{"ok": ok, "status_code": status, "latency_ms": latency, "error": nil}
	if errStr != "" {
		resp["error"] = errStr
	}
	c.JSON(http.StatusOK, resp)
}
