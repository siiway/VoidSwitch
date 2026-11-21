package core

import (
	"sort"
	"strings"
	"sync"
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
	// OwnerOnly marks an action the dashboard gates behind RequireOwner. A
	// platform key may not perform it unless its owner is an owner, and no admin
	// may grant it — a staff member must not be able to escalate through a key.
	OwnerOnly bool
}

// actionTable is the single source of truth for every exposed operation.
func actionTable() []Action {
	return []Action{
		{Name: "stats.get", Tier: TierRead, Category: "stats", Summary: "Dashboard overview counters."},

		{Name: "model.list", Tier: TierRead, Category: "model", Summary: "List exposed models the caller can see."},
		{Name: "model.get", Tier: TierRead, Category: "model", Summary: "Read one exposed model's metadata and route."},
		{Name: "model.edit", Tier: TierAdmin, Category: "model", Summary: "Create or update an exposed model's metadata."},
		{Name: "model.batch", Tier: TierAdmin, Category: "model", Summary: "Apply one metadata change to several models."},
		{Name: "model.delete", Tier: TierAdmin, Category: "model", Summary: "Delete an exposed model and its route."},
		{Name: "model.route.get", Tier: TierRead, Category: "model", Summary: "Read a model's routing plan."},
		{Name: "model.route.edit", Tier: TierAdmin, Category: "model", Summary: "Replace a model's routing plan."},
		{Name: "model.route.clear-cooldown", Tier: TierAdmin, Category: "model", Summary: "Clear an upstream cooldown.", OwnerOnly: true},
		{Name: "category.list", Tier: TierRead, Category: "model", Summary: "List model categories."},
		{Name: "category.edit", Tier: TierAdmin, Category: "model", Summary: "Create a model category."},

		{Name: "provider.list", Tier: TierRead, Category: "provider", Summary: "List providers (secrets redacted)."},
		{Name: "provider.get", Tier: TierRead, Category: "provider", Summary: "Read one provider (secrets redacted)."},
		{Name: "provider.edit", Tier: TierAdmin, Category: "provider", Summary: "Create a provider (it may start without keys)."},
		{Name: "provider.update", Tier: TierAdmin, Category: "provider", Summary: "Update a provider's settings."},
		{Name: "provider.delete", Tier: TierAdmin, Category: "provider", Summary: "Delete a provider and its keys.", OwnerOnly: true},

		{Name: "provider-key.list", Tier: TierProviderKey, Category: "provider-key", Summary: "List one provider's upstream keys."},
		{Name: "provider-key.add", Tier: TierProviderKey, Category: "provider-key", Summary: "Add upstream keys to a provider."},
		{Name: "provider-key.edit", Tier: TierProviderKey, Category: "provider-key", Summary: "Update one upstream key's pool, weight, status or note."},
		{Name: "provider-key.delete", Tier: TierProviderKey, Category: "provider-key", Summary: "Delete one upstream key."},
		{Name: "provider-key.reorder", Tier: TierProviderKey, Category: "provider-key", Summary: "Reorder a provider's upstream keys."},
		{Name: "provider-key.refresh-balance", Tier: TierProviderKey, Category: "provider-key", Summary: "Refresh upstream key balances."},
		{Name: "provider-key.cleanup", Tier: TierProviderKey, Category: "provider-key", Summary: "Delete unusable upstream keys."},

		{Name: "node.list", Tier: TierRead, Category: "node", Summary: "List egress nodes and node groups."},
		{Name: "node.get", Tier: TierRead, Category: "node", Summary: "Read one egress node."},
		{Name: "node.edit", Tier: TierAdmin, Category: "node", Summary: "Create an egress node."},
		{Name: "node.update", Tier: TierAdmin, Category: "node", Summary: "Update an egress node."},
		{Name: "node.delete", Tier: TierAdmin, Category: "node", Summary: "Delete an egress node.", OwnerOnly: true},
		{Name: "node.probe", Tier: TierAdmin, Category: "node", Summary: "Probe an egress node's health now."},
		{Name: "node-group.edit", Tier: TierAdmin, Category: "node", Summary: "Create a node group."},
		{Name: "node-group.update", Tier: TierAdmin, Category: "node", Summary: "Update a node group."},
		{Name: "node-group.delete", Tier: TierAdmin, Category: "node", Summary: "Delete a node group.", OwnerOnly: true},

		{Name: "user.list", Tier: TierRead, Category: "user", Summary: "List users."},
		{Name: "user.get", Tier: TierRead, Category: "user", Summary: "Read one user."},
		{Name: "user.edit", Tier: TierAdmin, Category: "user", Summary: "Change a user's role or enabled state.", OwnerOnly: true},
		{Name: "user.force-logout", Tier: TierAdmin, Category: "user", Summary: "Invalidate a user's dashboard sessions."},

		{Name: "role-group.list", Tier: TierRead, Category: "role-group", Summary: "List role groups."},
		{Name: "role-group.get", Tier: TierRead, Category: "role-group", Summary: "Read one role group."},
		{Name: "role-group.edit", Tier: TierAdmin, Category: "role-group", Summary: "Create a role group.", OwnerOnly: true},
		{Name: "role-group.delete", Tier: TierAdmin, Category: "role-group", Summary: "Delete a role group.", OwnerOnly: true},
		{Name: "role-group.member.list", Tier: TierRead, Category: "role-group", Summary: "List a role group's members."},
		{Name: "role-group.member.remove", Tier: TierAdmin, Category: "role-group", Summary: "Remove a member from a role group.", OwnerOnly: true},

		{Name: "api-key.list", Tier: TierRead, Category: "api-key", Summary: "List platform API keys."},
		{Name: "api-key.get", Tier: TierRead, Category: "api-key", Summary: "Read one platform API key."},
		{Name: "api-key.edit", Tier: TierAdmin, Category: "api-key", Summary: "Rename, enable, disable or re-scope an API key."},
		{Name: "api-key.delete", Tier: TierAdmin, Category: "api-key", Summary: "Revoke a platform API key."},
		{Name: "api-key.rotate", Tier: TierAdmin, Category: "api-key", Summary: "Rotate a platform API key's secret."},

		{Name: "request-log.list", Tier: TierRead, Category: "request-log", Summary: "Query gateway request logs."},
		{Name: "request-log.get", Tier: TierRead, Category: "request-log", Summary: "Read one request log (owner-visible fields only)."},
		{Name: "request-log.get-debug", Tier: TierRead, Category: "request-log", Summary: "Read one request log's full debug trail."},
		{Name: "request-log.filters", Tier: TierRead, Category: "request-log", Summary: "List the request log filter values."},
		{Name: "audit-log.list", Tier: TierRead, Category: "audit-log", Summary: "Query audit records."},
		{Name: "audit-log.filters", Tier: TierRead, Category: "audit-log", Summary: "List the audit filter values."},

		{Name: "announcement.list", Tier: TierRead, Category: "announcement", Summary: "List announcements."},
		{Name: "announcement.edit", Tier: TierAdmin, Category: "announcement", Summary: "Create an announcement."},
		{Name: "announcement.delete", Tier: TierAdmin, Category: "announcement", Summary: "Delete an announcement."},

		{Name: "setting.get", Tier: TierRead, Category: "setting", Summary: "Read runtime settings."},
		{Name: "setting.edit", Tier: TierAdmin, Category: "setting", Summary: "Change runtime settings.", OwnerOnly: true},
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

// splitCategoryWildcard splits "model.*" into ("model", true, true).
func splitCategoryWildcard(scope string) (category string, wildcard bool, ok bool) {
	head, tail, found := strings.Cut(scope, ".*")
	if !found || tail != "" || head == "" {
		return "", false, false
	}
	return head, true, true
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

// adminGrantableScopes are the scopes a staff member may grant. Actions are
// listed individually wherever a category wildcard would otherwise carry an
// owner-only member, so a category wildcard stays safe: it is expanded at use
// time to the actions the current role may perform. No entry covers
// ProviderScope (a provider-key grant must name a slug and stays owner-only).
func adminGrantableScopes() []string {
	return []string{
		ScopeRead,
		"stats.get",
		"model.list", "model.get", "model.edit", "model.batch", "model.delete",
		"model.route.get", "model.route.edit",
		"category.list", "category.edit",
		"provider.list", "provider.get", "provider.edit", "provider.update",
		"node.list", "node.get", "node.edit", "node.update", "node.probe",
		"node-group.edit", "node-group.update",
		"user.list", "user.get", "user.force-logout",
		"role-group.list", "role-group.get", "role-group.member.list",
		"api-key.*",
		"request-log.list", "request-log.get", "request-log.filters",
		"audit-log.*",
		"announcement.list", "announcement.edit", "announcement.delete",
		"setting.get",
	}
}

// ownerGrantableScopes adds the owner-only surface.
func ownerGrantableScopes() []string {
	return append(adminGrantableScopes(),
		ScopeAll,
		"user.edit", "setting.edit", "provider.delete",
		"node.delete", "node-group.delete",
		"role-group.edit", "role-group.delete", "role-group.member.remove",
		"model.route.clear-cooldown",
		ProviderScope+":*.*",
	)
}

// GrantableScopes returns every scope the given role may put on a platform API
// key. Only staff get any at all. The result is a fresh slice, so a caller may
// modify it.
func GrantableScopes(role string) []string {
	grants, _ := grantableFor(role)
	if len(grants) == 0 {
		return nil
	}
	return append([]string(nil), grants...)
}

var (
	grantableOnce     sync.Once
	grantableAdmin    []string
	grantableOwner    []string
	grantableAdminSet map[string]bool
	grantableOwnerSet map[string]bool
)

// grantableFor returns the grant list plus its set, built once. The lists are
// static, and EffectiveScopes runs on the authentication hot path.
func grantableFor(role string) ([]string, map[string]bool) {
	grantableOnce.Do(func() {
		grantableAdmin = adminGrantableScopes()
		grantableOwner = ownerGrantableScopes()
		grantableAdminSet = toSet(grantableAdmin)
		grantableOwnerSet = toSet(grantableOwner)
	})
	switch {
	case IsOwner(role):
		return grantableOwner, grantableOwnerSet
	case IsStaff(role):
		return grantableAdmin, grantableAdminSet
	default:
		return nil, nil
	}
}

func toSet(list []string) map[string]bool {
	out := make(map[string]bool, len(list))
	for _, s := range list {
		out[s] = true
	}
	return out
}

// ScopeGrantableBy reports whether the role may grant a specific scope entry.
// The entry must be one of the role's grant strings, a concrete action covered by
// one of them, or a per-provider entry for an owner.
func ScopeGrantableBy(role, scope string) bool {
	scope = strings.TrimSpace(scope)
	if scope == "" {
		return false
	}
	grantable, allow := grantableFor(role)
	if len(grantable) == 0 {
		return false
	}
	if allow[scope] {
		return true
	}
	if scope == ScopeAll {
		return allow[ScopeAll]
	}
	// Per-provider entries are granted whole (the slug is part of the entry), so
	// they must be handled before the generic category-wildcard branch below.
	if strings.HasPrefix(scope, ProviderScope+":") {
		if !allow[ProviderScope+":*.*"] {
			return false
		}
		rest := strings.TrimPrefix(scope, ProviderScope+":")
		slug, verb, ok := strings.Cut(rest, ".")
		if !ok || slug == "" || verb == "" {
			return false
		}
		if verb == "*" {
			return true
		}
		_, declared := ActionByName(ProviderScope + "." + verb)
		return declared
	}
	// A category wildcard is grantable when the category still has at least one
	// action this role may grant. The wildcard never widens to an owner-only
	// action: those are filtered out at use time.
	if category, wildcard, ok := splitCategoryWildcard(scope); ok && wildcard {
		for _, act := range Actions() {
			if act.Category != category {
				continue
			}
			if ScopeGrantableBy(role, act.Name) {
				return true
			}
		}
		return false
	}
	action, declared := ActionByName(scope)
	if !declared {
		return false
	}
	if action.OwnerOnly && !IsOwner(role) {
		return false
	}
	return allow[ScopeAll] || allow[scope] || allow[action.Category+".*"] ||
		(allow[ScopeRead] && action.Tier == TierRead)
}

// AllowsAction reports whether a credential with these effective scopes may
// perform an action, applying the owner-only gate. This is the single
// authorisation predicate: the REST router, the MCP registry and the scope
// picker all call it.
func AllowsAction(scopes []string, role, action string) bool {
	if act, ok := ActionByName(action); ok && act.OwnerOnly && !IsOwner(role) {
		return false
	}
	return ReadScopeSatisfied(scopes, action)
}

// EffectiveScopes narrows a key's stored scopes to what its owner's current
// role may still grant. A demoted owner keeps the key but loses the surfaces
// their new role no longer covers, so a role change takes effect on the next
// request without rewriting key rows.
//
// Wildcards are expanded against the role's grantable set rather than matched
// literally: "*" held by a demoted owner must mean "everything an admin may
// do", not "nothing" and not "everything".
func EffectiveScopes(scopes []string, role string) []string {
	grantable, allow := grantableFor(role)
	if len(grantable) == 0 || len(scopes) == 0 {
		return nil
	}
	out := make([]string, 0, len(scopes))
	for _, s := range scopes {
		s = strings.TrimSpace(s)
		if allow[s] {
			out = append(out, s)
			continue
		}
		// "*" expands to the role's whole grantable set.
		if s == ScopeAll {
			out = append(out, grantable...)
			continue
		}
		// Per-provider scopes never survive without an owner grant.
		if strings.HasPrefix(s, ProviderScope+":") {
			if allow[ProviderScope+":*.*"] {
				out = append(out, s)
			}
			continue
		}
		// A category wildcard expands to the concrete actions of that category the
		// role may still perform, so "model.*" cannot carry an owner-only action
		// such as clearing a cooldown.
		if category, wildcard, ok := splitCategoryWildcard(s); ok && wildcard {
			for _, act := range Actions() {
				if act.Category == category && ScopeGrantableBy(role, act.Name) {
					out = append(out, act.Name)
				}
			}
			continue
		}
		// A concrete action inside a granted category stays valid: "model.edit"
		// inside "model.*".
		if category, _, ok := splitAction(s); ok && allow[category+".*"] {
			out = append(out, s)
			continue
		}
	}
	return dedupeSorted(out)
}

func dedupeSorted(in []string) []string {
	if len(in) == 0 {
		return nil
	}
	sort.Strings(in)
	out := in[:1]
	for _, s := range in[1:] {
		if s != out[len(out)-1] {
			out = append(out, s)
		}
	}
	return out
}
