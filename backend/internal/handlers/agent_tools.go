package handlers

import (
	"net/http"
	"strings"

	"github.com/gin-gonic/gin"

	"github.com/siiway/voidswitch/internal/core"
)

// toolSpec is one addressable platform operation. The same value feeds three
// consumers: the REST router under /api/v1, the MCP tool registry, and the
// scope picker in the dashboard. Declaring an operation once is what keeps the
// REST surface and the agent surface from drifting apart.
type toolSpec struct {
	// Action is "category.action" — the scope entry that grants it.
	Action string
	// Params documents the tool arguments (path parameters plus body/query).
	Params []paramSpec
	// Method/Path describe the REST form. Path parameters use ":name" and are
	// stripped when the route is registered under /api/v1.
	Method string
	Path   string
	// Handler is the dashboard handler that performs the work.
	Handler gin.HandlerFunc
	// ProviderScoped marks provider-key actions, which need a provider slug in
	// the path to be authorised (and are the reason a scope must name a slug).
	ProviderScoped bool
	// ParamAlias maps an argument name to the path parameter name the handler
	// reads. The handler keeps its own name (some read "id" where the public API
	// says "model_id"), and the bridge registers both.
	ParamAlias map[string]string
}

// fixedParams is the alias map the bridge applies to a path parameter: the value
// the caller supplies under the public name is also registered under the name
// the handler reads.
func (t toolSpec) fixedParams() map[string]string { return t.ParamAlias }

// paramSpec describes one argument of a tool.
type paramSpec struct {
	Name string
	Type string
	Desc string
	// InPath means the argument is a path placeholder rather than a body/query
	// field.
	InPath bool
}

// platformTools is the declaration table. Handlers are bound in platformTools()
// because they are methods on App.
func (a *App) platformTools() []toolSpec {
	return []toolSpec{
		// ---- model -------------------------------------------------------
		{Action: "model.list", Method: http.MethodGet, Path: "/models", Handler: a.modelsList,
			Params: []paramSpec{}},
		{Action: "model.get", Method: http.MethodGet, Path: "/models/:model_id", Handler: a.modelGet,
			Params: []paramSpec{{Name: "model_id", Type: "string", InPath: true, Desc: "Public model id."}}},
		{Action: "model.edit", Method: http.MethodPut, Path: "/models", Handler: a.modelsUpsert,
			Params: []paramSpec{
				{Name: "model_id", Type: "string", Desc: "Public model id to create or update."},
				{Name: "display_name", Type: "string", Desc: "Label shown in the dashboard."},
				{Name: "description", Type: "string", Desc: "Free-form description."},
				{Name: "enabled", Type: "boolean", Desc: "Whether the model is callable."},
				{Name: "allowed_role_group_ids", Type: "array", Desc: "Role group ids permitted to call it."},
				{Name: "limit_context", Type: "integer", Desc: "Context window cap."},
				{Name: "limit_output", Type: "integer", Desc: "Output cap."},
				{Name: "reasoning", Type: "boolean", Desc: "Whether the model reasons."},
				{Name: "category_id", Type: "integer", Desc: "Category id; 0 clears it."},
				{Name: "opencode_config", Type: "object", Desc: "OpenCode V1 overrides."},
				{Name: "opencode_config_v2", Type: "object", Desc: "OpenCode V2 overrides."},
			}},
		{Action: "model.batch", Method: http.MethodPost, Path: "/models/batch", Handler: a.modelsBatch,
			Params: []paramSpec{
				{Name: "model_ids", Type: "array", Desc: "Models to change."},
				{Name: "enabled", Type: "boolean", Desc: "Set enabled state."},
				{Name: "allowed_role_group_ids", Type: "array", Desc: "Set permitted role groups."},
				{Name: "opencode_config_mode", Type: "string", Desc: "\"merge\" (default) or \"overwrite\"."},
			}},
		{Action: "model.delete", Method: http.MethodDelete, Path: "/models/:model_id", Handler: a.modelDeleteByPublicID,
			Params: []paramSpec{{Name: "model_id", Type: "string", InPath: true, Desc: "Public model id."}}},
		{Action: "model.route.get", Method: http.MethodGet, Path: "/models/:model_id/route", Handler: a.modelRouteGet,
			ParamAlias: map[string]string{"model_id": "id"},
			Params:     []paramSpec{{Name: "model_id", Type: "string", InPath: true, Desc: "Public model id."}}},
		{Action: "model.route.edit", Method: http.MethodPut, Path: "/models/:model_id/route", Handler: a.modelRoutePut,
			ParamAlias: map[string]string{"model_id": "id"},
			Params: []paramSpec{
				{Name: "model_id", Type: "string", InPath: true, Desc: "Public model id."},
				{Name: "upstreams", Type: "array", Desc: "Ordered upstream candidates {provider_id, upstream_model, key_pool, position, weight, enabled}."},
				{Name: "upstream_select_mode", Type: "string", Desc: "best / balanced / pinned_best / pinned_balanced."},
				{Name: "max_upstream_attempts", Type: "integer", Desc: "Attempt budget for this route."},
			}},
		{Action: "model.route.clear-cooldown", Method: http.MethodPost,
			Path: "/models/:model_id/route/upstreams/:upstream_id/cooldown", Handler: a.routeClearCooldown,
			ParamAlias: map[string]string{"model_id": "id", "upstream_id": "upstreamId"},
			Params: []paramSpec{
				{Name: "model_id", Type: "string", InPath: true, Desc: "Public model id."},
				{Name: "upstream_id", Type: "integer", InPath: true, Desc: "Route upstream id whose cooldown should be cleared."},
			}},
		{Action: "category.list", Method: http.MethodGet, Path: "/model-categories", Handler: a.categoriesList,
			Params: []paramSpec{}},
		{Action: "category.edit", Method: http.MethodPost, Path: "/model-categories", Handler: a.categoriesCreate,
			Params: []paramSpec{
				{Name: "name", Type: "string", Desc: "Category name."},
				{Name: "position", Type: "integer", Desc: "Sort position."},
			}},

		// ---- provider ----------------------------------------------------
		{Action: "provider.list", Method: http.MethodGet, Path: "/providers", Handler: a.providersList,
			Params: []paramSpec{}},
		{Action: "provider.get", Method: http.MethodGet, Path: "/providers/:id", Handler: a.providerGet,
			Params: []paramSpec{{Name: "id", Type: "integer", InPath: true, Desc: "Provider id."}}},
		{Action: "provider.edit", Method: http.MethodPost, Path: "/providers", Handler: a.providerCreate,
			Params: []paramSpec{
				{Name: "name", Type: "string", Desc: "Provider name."},
				{Name: "type", Type: "string", Desc: "Provider adapter type."},
				{Name: "base_url", Type: "string", Desc: "Upstream base URL."},
				{Name: "enabled", Type: "boolean", Desc: "Whether the provider is usable."},
				{Name: "models", Type: "array", Desc: "Advertised upstream model ids."},
			}},
		{Action: "provider.update", Method: http.MethodPatch, Path: "/providers/:id", Handler: a.providerUpdate,
			Params: []paramSpec{
				{Name: "id", Type: "integer", InPath: true, Desc: "Provider id."},
				{Name: "name", Type: "string", Desc: "Provider name."},
				{Name: "base_url", Type: "string", Desc: "Upstream base URL."},
				{Name: "enabled", Type: "boolean", Desc: "Whether the provider is usable."},
				{Name: "models", Type: "array", Desc: "Advertised upstream model ids."},
			}},
		{Action: "provider.delete", Method: http.MethodDelete, Path: "/providers/:id", Handler: a.providerDelete,
			Params: []paramSpec{{Name: "id", Type: "integer", InPath: true, Desc: "Provider id."}}},

		// ---- provider-key (per provider slug) ----------------------------
		{Action: "provider-key.list", ProviderScoped: true, Method: http.MethodGet,
			Path: "/providers/by-slug/:slug/keys", Handler: a.providerKeysListBySlug,
			Params: []paramSpec{{Name: "slug", Type: "string", InPath: true, Desc: "Provider slug."}}},
		{Action: "provider-key.add", ProviderScoped: true, Method: http.MethodPost,
			Path: "/providers/by-slug/:slug/keys", Handler: a.providerKeysAddBySlug,
			Params: []paramSpec{
				{Name: "slug", Type: "string", InPath: true, Desc: "Provider slug."},
				{Name: "keys", Type: "array", Desc: "Keys to add; each may carry a \"# note\" suffix."},
				{Name: "pool", Type: "string", Desc: "Key pool name."},
				{Name: "note", Type: "string", Desc: "Note applied to every added key."},
			}},
		{Action: "provider-key.edit", ProviderScoped: true, Method: http.MethodPatch,
			Path: "/providers/by-slug/:slug/keys/:key_id", Handler: a.providerKeysUpdateBySlug,
			Params: []paramSpec{
				{Name: "slug", Type: "string", InPath: true, Desc: "Provider slug."},
				{Name: "key_id", Type: "integer", InPath: true, Desc: "Upstream key id."},
				{Name: "pool", Type: "string", Desc: "Key pool."},
				{Name: "weight", Type: "integer", Desc: "Selection weight."},
				{Name: "status", Type: "string", Desc: "active / disabled / invalid."},
				{Name: "note", Type: "string", Desc: "Free-form note."},
			}},
		{Action: "provider-key.delete", ProviderScoped: true, Method: http.MethodDelete,
			Path: "/providers/by-slug/:slug/keys/:key_id", Handler: a.providerKeysDeleteBySlug,
			Params: []paramSpec{
				{Name: "slug", Type: "string", InPath: true, Desc: "Provider slug."},
				{Name: "key_id", Type: "integer", InPath: true, Desc: "Upstream key id."},
			}},
		{Action: "provider-key.reorder", ProviderScoped: true, Method: http.MethodPost,
			Path: "/providers/by-slug/:slug/keys/reorder", Handler: a.providerKeysReorderBySlug,
			Params: []paramSpec{
				{Name: "slug", Type: "string", InPath: true, Desc: "Provider slug."},
				{Name: "ids", Type: "array", Desc: "Key ids in the desired order."},
			}},
		{Action: "provider-key.refresh-balance", ProviderScoped: true, Method: http.MethodPost,
			Path: "/providers/by-slug/:slug/keys/refresh-balance", Handler: a.providerKeysRefreshBySlug,
			Params: []paramSpec{{Name: "slug", Type: "string", InPath: true, Desc: "Provider slug."}}},
		{Action: "provider-key.cleanup", ProviderScoped: true, Method: http.MethodPost,
			Path: "/providers/by-slug/:slug/keys/cleanup", Handler: a.providerKeysCleanupBySlug,
			Params: []paramSpec{{Name: "slug", Type: "string", InPath: true, Desc: "Provider slug."}}},

		// ---- node --------------------------------------------------------
		{Action: "node.list", Method: http.MethodGet, Path: "/nodes", Handler: a.nodesList,
			Params: []paramSpec{}},
		{Action: "node.get", Method: http.MethodGet, Path: "/nodes/:id", Handler: a.nodeGet,
			Params: []paramSpec{{Name: "id", Type: "integer", InPath: true, Desc: "Node id."}}},
		{Action: "node.edit", Method: http.MethodPost, Path: "/nodes", Handler: a.nodesCreate,
			Params: []paramSpec{
				{Name: "url", Type: "string", Desc: "Node URL."},
				{Name: "type", Type: "string", Desc: "direct / http / socks5 / agent."},
				{Name: "enabled", Type: "boolean", Desc: "Whether the node is usable."},
				{Name: "note", Type: "string", Desc: "Free-form note."},
			}},
		{Action: "node.update", Method: http.MethodPatch, Path: "/nodes/:id", Handler: a.nodesUpdate,
			Params: []paramSpec{
				{Name: "id", Type: "integer", InPath: true, Desc: "Node id."},
				{Name: "url", Type: "string", Desc: "Node URL."},
				{Name: "enabled", Type: "boolean", Desc: "Whether the node is usable."},
				{Name: "note", Type: "string", Desc: "Free-form note."},
			}},
		{Action: "node.delete", Method: http.MethodDelete, Path: "/nodes/:id", Handler: a.nodesDelete,
			Params: []paramSpec{{Name: "id", Type: "integer", InPath: true, Desc: "Node id."}}},
		{Action: "node.probe", Method: http.MethodPost, Path: "/nodes/:id/probe", Handler: a.nodesProbe,
			Params: []paramSpec{{Name: "id", Type: "integer", InPath: true, Desc: "Node id."}}},
		{Action: "node-group.edit", Method: http.MethodPost, Path: "/node-groups", Handler: a.nodeGroupsCreate,
			Params: []paramSpec{
				{Name: "name", Type: "string", Desc: "Node group name."},
				{Name: "probe_url", Type: "string", Desc: "Health probe URL."},
			}},
		{Action: "node-group.update", Method: http.MethodPatch, Path: "/node-groups/:id", Handler: a.nodeGroupsUpdate,
			Params: []paramSpec{
				{Name: "id", Type: "integer", InPath: true, Desc: "Node group id."},
				{Name: "name", Type: "string", Desc: "Node group name."},
				{Name: "probe_url", Type: "string", Desc: "Health probe URL."},
			}},
		{Action: "node-group.delete", Method: http.MethodDelete, Path: "/node-groups/:id", Handler: a.nodeGroupsDelete,
			Params: []paramSpec{{Name: "id", Type: "integer", InPath: true, Desc: "Node group id."}}},

		// ---- user --------------------------------------------------------
		{Action: "user.list", Method: http.MethodGet, Path: "/users", Handler: a.usersList,
			Params: []paramSpec{}},
		{Action: "user.get", Method: http.MethodGet, Path: "/users/:id", Handler: a.userGet,
			Params: []paramSpec{{Name: "id", Type: "integer", InPath: true, Desc: "User id."}}},
		{Action: "user.edit", Method: http.MethodPatch, Path: "/users/:id", Handler: a.userUpdate,
			Params: []paramSpec{
				{Name: "id", Type: "integer", InPath: true, Desc: "User id."},
				{Name: "role", Type: "string", Desc: "owner / co-owner / admin / member."},
				{Name: "enabled", Type: "boolean", Desc: "Whether the user may sign in."},
			}},
		{Action: "user.force-logout", Method: http.MethodPost, Path: "/users/:id/force-logout", Handler: a.userForceLogout,
			Params: []paramSpec{{Name: "id", Type: "integer", InPath: true, Desc: "User id."}}},

		// ---- role group --------------------------------------------------
		{Action: "role-group.list", Method: http.MethodGet, Path: "/role-groups", Handler: a.roleGroupsList,
			Params: []paramSpec{}},
		{Action: "role-group.get", Method: http.MethodGet, Path: "/role-groups/:id", Handler: a.roleGroupGet,
			Params: []paramSpec{{Name: "id", Type: "integer", InPath: true, Desc: "Role group id."}}},
		{Action: "role-group.edit", Method: http.MethodPost, Path: "/role-groups", Handler: a.roleGroupCreate,
			Params: []paramSpec{
				{Name: "name", Type: "string", Desc: "Role group name."},
				{Name: "description", Type: "string", Desc: "Free-form description."},
			}},
		{Action: "role-group.delete", Method: http.MethodDelete, Path: "/role-groups/:id", Handler: a.roleGroupDelete,
			Params: []paramSpec{{Name: "id", Type: "integer", InPath: true, Desc: "Role group id."}}},
		{Action: "role-group.member.list", Method: http.MethodGet, Path: "/role-groups/:id/members", Handler: a.roleGroupMembers,
			Params: []paramSpec{{Name: "id", Type: "integer", InPath: true, Desc: "Role group id."}}},
		{Action: "role-group.member.remove", Method: http.MethodDelete, Path: "/role-groups/:id/members/:user_id", Handler: a.roleGroupMemberDelete,
			ParamAlias: map[string]string{"user_id": "userId"},
			Params: []paramSpec{
				{Name: "id", Type: "integer", InPath: true, Desc: "Role group id."},
				{Name: "user_id", Type: "integer", InPath: true, Desc: "User id to remove."},
			}},

		// ---- platform api key --------------------------------------------
		{Action: "api-key.list", Method: http.MethodGet, Path: "/api-keys", Handler: a.mePlatformKeys,
			Params: []paramSpec{}},
		{Action: "api-key.get", Method: http.MethodGet, Path: "/api-keys/:id", Handler: a.mePlatformKeyGet,
			Params: []paramSpec{{Name: "id", Type: "integer", InPath: true, Desc: "Platform API key id."}}},
		{Action: "api-key.edit", Method: http.MethodPatch, Path: "/api-keys/:id", Handler: a.mePlatformKeyUpdate,
			Params: []paramSpec{
				{Name: "id", Type: "integer", InPath: true, Desc: "Platform API key id."},
				{Name: "name", Type: "string", Desc: "New name."},
				{Name: "enabled", Type: "boolean", Desc: "Enable or disable."},
				{Name: "scopes", Type: "array", Desc: "Replacement scope list."},
			}},
		{Action: "api-key.delete", Method: http.MethodDelete, Path: "/api-keys/:id", Handler: a.mePlatformKeyDelete,
			Params: []paramSpec{{Name: "id", Type: "integer", InPath: true, Desc: "Platform API key id."}}},
		{Action: "api-key.rotate", Method: http.MethodPost, Path: "/api-keys/:id/rotate", Handler: a.mePlatformKeyRotate,
			Params: []paramSpec{{Name: "id", Type: "integer", InPath: true, Desc: "Platform API key id."}}},

		// ---- logs --------------------------------------------------------
		{Action: "request-log.list", Method: http.MethodGet, Path: "/request-logs", Handler: a.logsRequestsList,
			Params: []paramSpec{
				{Name: "limit", Type: "integer", Desc: "Page size (default 50, max 500)."},
				{Name: "offset", Type: "integer", Desc: "Page offset."},
				{Name: "model", Type: "string", Desc: "Filter by public model id."},
				{Name: "provider", Type: "string", Desc: "Filter by provider name."},
				{Name: "user_sub", Type: "string", Desc: "Filter by owner subject."},
				{Name: "status", Type: "string", Desc: "Filter by status code or 4xx/5xx range."},
				{Name: "success", Type: "boolean", Desc: "Filter by success."},
				{Name: "start", Type: "string", Desc: "RFC3339 lower bound."},
				{Name: "end", Type: "string", Desc: "RFC3339 upper bound."},
			}},
		{Action: "request-log.get", Method: http.MethodGet, Path: "/request-logs/:id", Handler: a.logsRequestSummary,
			Params: []paramSpec{{Name: "id", Type: "integer", InPath: true, Desc: "Request log id."}}},
		{Action: "request-log.get-debug", Method: http.MethodGet, Path: "/request-logs/:id/debug", Handler: a.logsRequestDebug,
			Params: []paramSpec{{Name: "id", Type: "integer", InPath: true, Desc: "Request log id."}}},
		{Action: "request-log.filters", Method: http.MethodGet, Path: "/request-logs/filters", Handler: a.logsRequestFilters,
			Params: []paramSpec{}},
		{Action: "audit-log.list", Method: http.MethodGet, Path: "/audit-logs", Handler: a.logsAuditList,
			Params: []paramSpec{
				{Name: "limit", Type: "integer", Desc: "Page size."},
				{Name: "offset", Type: "integer", Desc: "Page offset."},
				{Name: "action", Type: "string", Desc: "Filter by action."},
				{Name: "scope", Type: "string", Desc: "Filter by scope."},
				{Name: "target_type", Type: "string", Desc: "Filter by target type."},
				{Name: "start", Type: "string", Desc: "RFC3339 lower bound."},
				{Name: "end", Type: "string", Desc: "RFC3339 upper bound."},
			}},
		{Action: "audit-log.filters", Method: http.MethodGet, Path: "/audit-logs/filters", Handler: a.logsAuditFilters,
			Params: []paramSpec{}},

		// ---- announcement -------------------------------------------------
		{Action: "announcement.list", Method: http.MethodGet, Path: "/announcements", Handler: a.announcementsList,
			Params: []paramSpec{}},
		{Action: "announcement.edit", Method: http.MethodPost, Path: "/announcements", Handler: a.announcementCreate,
			Params: []paramSpec{
				{Name: "title", Type: "string", Desc: "Announcement title."},
				{Name: "body", Type: "string", Desc: "Announcement body."},
				{Name: "target_role_group_ids", Type: "array", Desc: "Audience role groups; empty means everyone."},
			}},
		{Action: "announcement.delete", Method: http.MethodDelete, Path: "/announcements/:id", Handler: a.announcementDelete,
			Params: []paramSpec{{Name: "id", Type: "integer", InPath: true, Desc: "Announcement id."}}},

		// ---- misc ---------------------------------------------------------
		{Action: "stats.get", Method: http.MethodGet, Path: "/stats", Handler: a.statsSummary,
			Params: []paramSpec{}},
		{Action: "setting.get", Method: http.MethodGet, Path: "/settings", Handler: a.settingsGet,
			Params: []paramSpec{}},
		{Action: "setting.edit", Method: http.MethodPut, Path: "/settings", Handler: a.settingsUpdate,
			Params: []paramSpec{{Name: "values", Type: "object", Desc: "Settings key/value map to write."}}},
	}
}

// visible reports whether the credential may call one tool. Provider-scoped
// tools stay hidden until a scope names at least one provider: a generic
// "provider-key.*" grants nothing, because managing every provider's credentials
// must be an explicit per-provider decision.
func (t toolSpec) visible(cred *core.PlatformCredential) bool {
	if cred == nil {
		return false
	}
	if !t.ProviderScoped {
		return cred.Allows(t.Action)
	}
	return hasProviderSlugScope(cred.Scopes)
}

// hasProviderSlugScope reports whether any scope entry names a provider slug.
func hasProviderSlugScope(scopes []string) bool {
	for _, s := range scopes {
		if !strings.HasPrefix(s, core.ProviderScope+":") {
			continue
		}
		rest := strings.TrimPrefix(s, core.ProviderScope+":")
		slug, verb, ok := strings.Cut(rest, ".")
		if ok && slug != "" && verb != "" {
			return true
		}
	}
	return false
}

// authorizeProviderScope re-checks a provider-scoped tool against the slug in
// the path. The tool is visible when any provider is granted, but the call must
// still name a provider the key actually covers.
func authorizeProviderScope(c *gin.Context, action, slug string) bool {
	cred := core.GetPlatformCredential(c)
	if cred == nil {
		return true
	}
	if !cred.AllowsProviderKey(slug, action) {
		c.AbortWithStatusJSON(http.StatusForbidden,
			gin.H{"detail": "This API key is not permitted to manage provider '" + slug + "'."})
		return false
	}
	return true
}
