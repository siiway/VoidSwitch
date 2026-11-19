package core

import (
	"strings"
	"testing"
)

func TestScopeAllows(t *testing.T) {
	cases := []struct {
		name   string
		scopes []string
		action string
		want   bool
	}{
		{"empty", nil, "model.edit", false},
		{"exact", []string{"model.edit"}, "model.edit", true},
		{"other action", []string{"model.edit"}, "model.delete", false},
		{"category wildcard", []string{"model.*"}, "model.edit", true},
		{"provider wildcard never reaches provider keys", []string{"provider.*"}, "provider-key.add", false},
		{"category wildcard does not cross categories", []string{"model.*"}, "provider.edit", false},
		{"blanket wildcard", []string{"*"}, "provider.delete", true},
		{"blanket wildcard still cannot name a provider key action", []string{"*"}, "provider-key.add", false},
		{"read shorthand is not an action match", []string{"read"}, "model.list", false},
		{"read shorthand via ReadScopeSatisfied", []string{"read"}, "model.list", false},
		{"read is not write", []string{"read"}, "model.edit", false},
		{"read via ScopeAllows is not a write", []string{"read"}, "provider.edit", false},
		{"provider key needs a slug", []string{"provider-key.*"}, "provider-key.add", false},
		{"provider key bare is never granted", []string{"provider-key:acme.*"}, "provider-key.add", false},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if got := ScopeAllows(tc.scopes, tc.action); got != tc.want {
				t.Fatalf("ScopeAllows(%v, %q) = %v, want %v", tc.scopes, tc.action, got, tc.want)
			}
		})
	}
}

func TestReadScopeSatisfied(t *testing.T) {
	if !ReadScopeSatisfied([]string{"read"}, "request-log.get") {
		t.Fatal("read should satisfy a read-tier action")
	}
	if ReadScopeSatisfied([]string{"read"}, "setting.edit") {
		t.Fatal("read must not satisfy a write action")
	}
}

func TestProviderKeyScopeAllows(t *testing.T) {
	scopes := []string{"provider-key:acme.*"}
	if !ProviderKeyScopeAllows(scopes, "acme", "provider-key.add") {
		t.Fatal("wildcard slug scope should grant add")
	}
	if !ProviderKeyScopeAllows(scopes, "acme", "provider-key") {
		t.Fatal("whole-family check should pass for the granted slug")
	}
	if ProviderKeyScopeAllows(scopes, "other", "provider-key.add") {
		t.Fatal("a scope for one provider must not reach another")
	}
	if !ProviderKeyScopeAllows([]string{"provider-key:acme.add"}, "acme", "provider-key.add") {
		t.Fatal("verb scope should grant the matching verb")
	}
	if ProviderKeyScopeAllows([]string{"provider-key:acme.add"}, "acme", "provider-key.delete") {
		t.Fatal("verb scope must not grant a different verb")
	}
	if ProviderKeyScopeAllows([]string{"*"}, "", "provider-key.add") {
		t.Fatal("a slug is mandatory")
	}
}

func TestEffectiveScopes(t *testing.T) {
	// An owner keeps everything they were granted.
	ownerScopes := EffectiveScopes([]string{"*", "model.edit"}, "owner")
	if len(ownerScopes) != 2 {
		t.Fatalf("owner effective scopes = %v", ownerScopes)
	}
	// An admin loses the owner-only entries: provider deletion and provider key
	// management both act on provider secrets.
	adminScopes := EffectiveScopes([]string{"read", "provider.delete", "provider-key:acme.*"}, "admin")
	if len(adminScopes) != 1 || adminScopes[0] != "read" {
		t.Fatalf("admin effective scopes = %v, want [read]", adminScopes)
	}
	// A concrete action inside a granted category survives.
	narrowed := EffectiveScopes([]string{"model.edit", "node.edit"}, "admin")
	if len(narrowed) != 2 {
		t.Fatalf("admin explicit actions = %v", narrowed)
	}
	// A member gets nothing at all.
	if got := EffectiveScopes([]string{"*"}, "member"); got != nil {
		t.Fatalf("member effective scopes = %v, want nil", got)
	}
}

func TestNoRevealActions(t *testing.T) {
	for _, act := range Actions() {
		if strings.Contains(act.Name, "reveal") {
			t.Fatalf("reveal actions must never be addressable by a platform key: %s", act.Name)
		}
	}
	// Reveal is also unreachable through a wildcard because it is not declared.
	if ScopeAllows([]string{"*"}, "key.reveal") {
		// "*" matches any action name, so the guard is the absence of the
		// declaration: an undeclared action has no handler and no route.
		if _, ok := ActionByName("key.reveal"); ok {
			t.Fatal("key.reveal must not be declared")
		}
	}
}

func TestGrantableScopes(t *testing.T) {
	if len(GrantableScopes("member")) != 0 {
		t.Fatal("members get no platform key scopes")
	}
	admin := GrantableScopes("admin")
	for _, s := range admin {
		if s == "provider.delete" || s == "provider-key:*.*" || s == "*" {
			t.Fatalf("admin must not be offered owner-only scope %q", s)
		}
	}
	owner := GrantableScopes("owner")
	found := false
	for _, s := range owner {
		if s == "provider-key:*.*" {
			found = true
		}
	}
	if !found {
		t.Fatal("owners may grant provider key management")
	}
}

// TestOwnerOnlyActionsNeverGrantableToAdmin pins the escalation guard: an admin
// holding a platform key must not be able to edit users, settings or delete a
// provider, no matter which wildcard the key carries.
func TestOwnerOnlyActionsNeverGrantableToAdmin(t *testing.T) {
	ownerOnly := []string{
		"user.edit", "setting.edit", "provider.delete",
		"node.delete", "role-group.edit", "role-group.delete",
		"role-group.member.remove", "model.route.clear-cooldown",
	}
	for _, action := range ownerOnly {
		if ScopeGrantableBy("admin", action) {
			t.Fatalf("admin must not be able to grant %q", action)
		}
		if AllowsAction([]string{"*"}, "admin", action) {
			t.Fatalf("admin with '*' must not reach %q", action)
		}
		if !ScopeGrantableBy("owner", action) {
			t.Fatalf("owner should be able to grant %q", action)
		}
		if !AllowsAction([]string{"*"}, "owner", action) {
			t.Fatalf("owner with '*' should reach %q", action)
		}
	}
	// A category wildcard stays grantable (it is how a whole category is handed
	// over), but it must not carry the owner-only member of that category.
	admin := EffectiveScopes([]string{"user.*", "node.*"}, "admin")
	for _, s := range admin {
		if s == "user.edit" || s == "node.delete" {
			t.Fatalf("admin wildcard leaked owner-only %q: %v", s, admin)
		}
	}
	if len(admin) == 0 {
		t.Fatal("admin wildcards should still expand to the admin surface")
	}
}

// TestEffectiveScopesExpandsWildcard covers the demotion path: an owner's "*"
// narrows to what an admin may do, rather than collapsing to nothing.
func TestEffectiveScopesExpandsWildcard(t *testing.T) {
	narrowed := EffectiveScopes([]string{"*"}, "admin")
	if len(narrowed) == 0 {
		t.Fatal("a demoted owner keeps the admin surface")
	}
	allow := map[string]bool{}
	for _, s := range narrowed {
		allow[s] = true
	}
	if allow["*"] || allow["provider-key:*.*"] || allow["provider.delete"] {
		t.Fatalf("demotion must drop the owner-only surface: %v", narrowed)
	}
	if !allow["model.edit"] {
		t.Fatalf("demotion must keep the admin surface: %v", narrowed)
	}
}

// TestScopeGrantableByRejectsUnknown keeps the picker honest: a typo or an
// undeclared verb is a 422 rather than a silently inert scope.
func TestScopeGrantableByRejectsUnknown(t *testing.T) {
	cases := []string{"key.reveal", "provider-key:acme.reveal", "provider-key:acme",
		"provider-key:.add", "nonsense"}
	for _, s := range cases {
		if ScopeGrantableBy("owner", s) {
			t.Fatalf("owner must not be able to grant %q", s)
		}
	}
	if !ScopeGrantableBy("owner", "provider-key:acme.add") {
		t.Fatal("owner should grant a per-provider key verb")
	}
	if !ScopeGrantableBy("owner", "provider-key:acme.*") {
		t.Fatal("owner should grant a per-provider wildcard")
	}
}
