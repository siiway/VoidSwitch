package core

import (
	"sort"
	"strings"
)

// Platform API key scopes are "category.action" strings ("model.edit",
// "request-log.get"). A scope entry may also be "*" (everything) or
// "category.*" (every action in one category). Provider key management is
// per-provider: "provider-key:<slug>.*" / "provider-key:<slug>.add".
//
// A key's effective permission is its scopes intersected with what its owner's
// current platform role may grant, so demoting a user narrows existing keys
// immediately without rewriting them.

// Scope wildcard entries.
const (
	ScopeAll      = "*"
	ScopeSelfAll  = "self.*"
	ScopeRead     = "read"
	ProviderScope = "provider-key"
)

// ActionTier classifies an action for planning and for the "self" audit scope.
type ActionTier int

const (
	// TierRead actions only read platform state.
	TierRead ActionTier = iota
	// TierSelf actions mutate the caller's own resources.
	TierSelf
	// TierProviderKey actions manage one provider's upstream keys.
	TierProviderKey
	// TierAdmin actions mutate platform configuration.
	TierAdmin
)

// Action describes one addressable platform operation. The name doubles as the
// MCP tool suffix and the REST route segment.
type Action struct {
	// Name is "category.action", e.g. "model.edit".
	Name string
	// Tier decides who may grant it and which audit scope it records.
	Tier ActionTier
	// Category groups actions for the picker UI.
	Category string
	// Summary is the one-line description shown in tools/list and the UI.
	Summary string
}

// actionTable is the single source of truth for every exposed operation.
func actionTable() []Action {
	return []Action{
		{"stats.get", TierRead, "stats", "Dashboard overview counters."},

		{"model.list", TierRead, "model", "List exposed models the caller can see."},
		{"model.get", TierRead, "model", "Read one exposed model's metadata and route."},
		{"model.edit", TierAdmin, "model", "Create or update an exposed model's metadata."},
		{"model.batch", TierAdmin, "model", "Apply one metadata change to several models."},
		{"model.delete", TierAdmin, "model", "Delete an exposed model and its route."},
		{"model.route.get", TierRead, "model", "Read a model's routing plan."},
		{"model.route.edit", TierAdmin, "model", "Replace a model's routing plan."},
		{"model.route.clear-cooldown", TierAdmin, "model", "Clear an upstream cooldown."},
		{"category.list", TierRead, "model", "List model categories."},
		{"category.edit", TierAdmin, "model", "Create, rename or delete a model category."},

		{"provider.list", TierRead, "provider", "List providers (secrets redacted)."},
		{"provider.get", TierRead, "provider", "Read one provider (secrets redacted)."},
		{"provider.edit", TierAdmin, "provider", "Create or update a provider. Keys are optional."},
		{"provider.delete", TierAdmin, "provider", "Delete a provider and its keys."},

		{"provider-key.list", TierProviderKey, "provider-key", "List one provider's upstream keys."},
		{"provider-key.add", TierProviderKey, "provider-key", "Add upstream keys to a provider."},
		{"provider-key.edit", TierProviderKey, "provider-key", "Update one upstream key's pool, weight, status or note."},
		{"provider-key.delete", TierProviderKey, "provider-key", "Delete one upstream key."},
		{"provider-key.reorder", TierProviderKey, "provider-key", "Reorder a provider's upstream keys."},
		{"provider-key.refresh-balance", TierProviderKey, "provider-key", "Refresh upstream key balances."},
		{"provider-key.cleanup", TierProviderKey, "provider-key", "Delete unusable upstream keys."},

		{"node.list", TierRead, "node", "List egress nodes and node groups."},
		{"node.get", TierRead, "node", "Read one egress node."},
		{"node.edit", TierAdmin, "node", "Create or update an egress node."},
		{"node.delete", TierAdmin, "node", "Delete an egress node."},
		{"node.probe", TierAdmin, "node", "Probe an egress node's health now."},
		{"node-group.edit", TierAdmin, "node", "Create, update or delete a node group."},

		{"user.list", TierRead, "user", "List users."},
		{"user.get", TierRead, "user", "Read one user."},
		{"user.edit", TierAdmin, "user", "Change a user's role or enabled state."},
		{"user.force-logout", TierAdmin, "user", "Invalidate a user's dashboard sessions."},

		{"role-group.list", TierRead, "role-group", "List role groups."},
		{"role-group.get", TierRead, "role-group", "Read one role group."},
		{"role-group.edit", TierAdmin, "role-group", "Create or update a role group."},
		{"role-group.delete", TierAdmin, "role-group", "Delete a role group."},
		{"role-group.member.list", TierRead, "role-group", "List a role group's members."},
		{"role-group.member.remove", TierAdmin, "role-group", "Remove a member from a role group."},

		{"api-key.list", TierRead, "api-key", "List platform API keys."},
		{"api-key.get", TierRead, "api-key", "Read one platform API key."},
		{"api-key.edit", TierAdmin, "api-key", "Rename, enable, disable or re-scope an API key."},
		{"api-key.delete", TierAdmin, "api-key", "Revoke a platform API key."},
		{"api-key.rotate", TierAdmin, "api-key", "Rotate a platform API key's secret."},

		{"request-log.list", TierRead, "request-log", "Query gateway request logs."},
		{"request-log.get", TierRead, "request-log", "Read one request log (owner-visible fields only)."},
		{"request-log.get-debug", TierRead, "request-log", "Read one request log's full debug trail."},
		{"request-log.filters", TierRead, "request-log", "List the request log filter values."},
		{"audit-log.list", TierRead, "audit-log", "Query audit records."},
		{"audit-log.filters", TierRead, "audit-log", "List the audit filter values."},

		{"announcement.list", TierRead, "announcement", "List announcements."},
		{"announcement.edit", TierAdmin, "announcement", "Create or update an announcement."},
		{"announcement.delete", TierAdmin, "announcement", "Delete an announcement."},

		{"setting.get", TierRead, "setting", "Read runtime settings."},
		{"setting.edit", TierAdmin, "setting", "Change runtime settings."},
	}
}

// Actions returns every addressable action.
func Actions() []Action { return actionTable() }

// ActionByName looks an action up by its "category.action" name.
func ActionByName(name string) (Action, bool) {
	for _, a := range actionTable() {
		if a.Name == name {
			return a, true
		}
	}
	return Action{}, false
}

// ScopeAllows reports whether a scope list grants the given "category.action".
//
// Matching is exact, "category.*", or the blanket "*". Provider key scopes are
// per-provider: "provider-key:acme.add" grants action provider-key.add for
// provider "acme", "provider-key:acme.*" grants every provider key action for
// it, and "provider-key.add" alone grants nothing (a key must never manage
// every provider by accident). Callers pass the provider slug through
// providerKeyScopeAction.
func ScopeAllows(scopes []string, action string) bool {
	if len(scopes) == 0 || action == "" {
		return false
	}
	// Provider key actions: the checked string is "provider-key.<verb>" and the
	// grant is "provider-key:<slug>.<verb>" or "provider-key:<slug>.*".
	if strings.HasPrefix(action, ProviderScope+".") {
		// A bare "provider-key.*" / "provider-key" grants nothing: the slug is
		// mandatory so one key can never reach every provider's credentials.
		return false
	}
	category, _, ok := splitAction(action)
	if !ok {
		return false
	}
	for _, s := range scopes {
		s = strings.TrimSpace(s)
		if s == "" {
			continue
		}
		if s == ScopeAll {
			return true
		}
		if s == action || s == category+".*" {
			return true
		}
	}
	return false
}

// ProviderKeyScopeAllows reports whether scopes grant one provider key action
// for a specific provider slug. Scopes must name the provider. The action may be
// the generic "provider-key" (the whole family for this provider) or one verb
// such as "provider-key.add".
func ProviderKeyScopeAllows(scopes []string, slug, action string) bool {
	if slug == "" || !strings.HasPrefix(action, ProviderScope) {
		return false
	}
	prefix := ProviderScope + ":" + slug
	wildcard := prefix + ".*"
	exact := prefix + strings.TrimPrefix(action, ProviderScope)
	if action == ProviderScope {
		exact = wildcard
	}
	for _, s := range scopes {
		s = strings.TrimSpace(s)
		if s == ScopeAll || s == wildcard || s == exact {
			return true
		}
	}
	return false
}

func splitAction(action string) (category, verb string, ok bool) {
	i := strings.LastIndexByte(action, '.')
	if i <= 0 || i == len(action)-1 {
		return "", "", false
	}
	return action[:i], action[i+1:], true
}

// ReadScopeSatisfied reports whether scopes grant read access to an action that
// only reads state. "read" is a shorthand for every tier-read action.
func ReadScopeSatisfied(scopes []string, action string) bool {
	if ScopeAllows(scopes, action) {
		return true
	}
	a, ok := ActionByName(action)
	return ok && a.Tier == TierRead && containsScope(scopes, ScopeRead)
}

func containsScope(scopes []string, want string) bool {
	for _, s := range scopes {
		if strings.TrimSpace(s) == want {
			return true
		}
	}
	return false
}

// adminGrantableScopes are the scopes a staff member may grant. Nothing here
// reaches a stored secret: there is deliberately no *.reveal action, no provider
// deletion (it destroys credentials), and no provider-key scope (it can rotate
// upstream credentials) — those stay owner-only.
func adminGrantableScopes() []string {
	return []string{
		ScopeRead,
		"stats.get",
		"model.*",
		"provider.list", "provider.get", "provider.edit",
		"node.*", "node-group.*",
		"user.*", "role-group.*", "api-key.*", "request-log.*", "audit-log.*",
		"announcement.*", "setting.get", "setting.edit", "category.*",
	}
}

// ownerGrantableScopes adds the owner-only surface.
func ownerGrantableScopes() []string {
	return append(adminGrantableScopes(), ScopeAll, "provider.delete", ProviderScope+":*.*")
}

// GrantableScopes returns every scope the given role may put on a platform API
// key. Only staff get any at all.
func GrantableScopes(role string) []string {
	if IsOwner(role) {
		return ownerGrantableScopes()
	}
	if IsStaff(role) {
		return adminGrantableScopes()
	}
	return nil
}

// ScopeGrantableBy reports whether the role may grant a specific scope entry.
// Provider key scopes are owner-only because they can rotate upstream
// credentials.
func ScopeGrantableBy(role, scope string) bool {
	scope = strings.TrimSpace(scope)
	if scope == "" {
		return false
	}
	for _, g := range GrantableScopes(role) {
		if g == scope {
			return true
		}
	}
	// Wildcard families: "model.*" covers "model.edit", but the grant string is
	// what gets written to the key, so only listed grant strings are accepted.
	return false
}

// EffectiveScopes narrows a key's stored scopes to what its owner's current
// role may still grant. A demoted owner keeps the key but loses the surfaces
// their new role no longer covers, so a role change takes effect on the next
// request without rewriting key rows.
func EffectiveScopes(scopes []string, role string) []string {
	grantable := GrantableScopes(role)
	if len(grantable) == 0 || len(scopes) == 0 {
		return nil
	}
	allow := make(map[string]bool, len(grantable))
	for _, g := range grantable {
		allow[g] = true
	}
	out := make([]string, 0, len(scopes))
	for _, s := range scopes {
		s = strings.TrimSpace(s)
		if allow[s] {
			out = append(out, s)
			continue
		}
		// A concrete action inside a granted category stays valid: "model.edit"
		// inside "model.*".
		if category, _, ok := splitAction(s); ok && allow[category+".*"] {
			out = append(out, s)
			continue
		}
		// Per-provider scopes survive only for the role that may manage keys.
		if strings.HasPrefix(s, ProviderScope+":") {
			if allow[ProviderScope+":*.*"] {
				out = append(out, s)
			}
			continue
		}
	}
	sort.Strings(out)
	return out
}
