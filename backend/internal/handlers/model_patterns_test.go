package handlers

import (
	"encoding/json"
	"testing"

	"github.com/siiway/voidswitch/internal/database"
)

// The allow-list grammar uses shell wildcards, not path globs: `*` must span
// "/" so "openrouter/*" covers "openrouter/stealth/x". path/filepath.Match
// stopped at the slash and silently denied those ids.
func TestGlobMatchStarSpansSlash(t *testing.T) {
	cases := []struct {
		pattern, name string
		want          bool
	}{
		{"openrouter/*", "openrouter/stealth/space-bunny-alpha", true},
		{"openrouter/*", "openrouter/gpt-4o", true},
		{"openrouter/*", "anthropic/gpt-4o", false},
		{"gpt-*", "gpt-4o", true},
		{"gpt-*", "o1", false},
		{"*", "anything/at/all", true},
		{"*-mini", "gpt-4o-mini", true},
		{"*-mini", "gpt-4o", false},
		{"a?c", "abc", true},
		{"a?c", "a/c", true},
		{"a?c", "ac", false},
	}
	for _, c := range cases {
		if got := globMatch(c.pattern, c.name); got != c.want {
			t.Fatalf("globMatch(%q, %q) = %v, want %v", c.pattern, c.name, got, c.want)
		}
	}
}

// `[!…]` is a negated set in this grammar; a path glob reads it as a literal set
// headed by '!', which flipped the result.
func TestGlobMatchSets(t *testing.T) {
	cases := []struct {
		pattern, name string
		want          bool
	}{
		{"[abc]", "b", true},
		{"[abc]", "d", false},
		{"[a-z]0", "q0", true},
		{"[a-z]0", "Q0", false},
		{"[!abc]", "d", true},
		{"[!abc]", "a", false},
		{"[^abc]", "a", false},
		{"[!a]*", "bcd", true},
		{"[", "[", true},
	}
	for _, c := range cases {
		if got := globMatch(c.pattern, c.name); got != c.want {
			t.Fatalf("globMatch(%q, %q) = %v, want %v", c.pattern, c.name, got, c.want)
		}
	}
}

func TestAllowedModelPatterns(t *testing.T) {
	patterns, ok := allowedModelPatterns(nil)
	if !ok || len(patterns) != 0 {
		t.Fatalf("an absent column means no restriction, got %v ok=%v", patterns, ok)
	}

	patterns, ok = allowedModelPatterns(json.RawMessage(`["gpt-4o", 42]`))
	if !ok || len(patterns) != 2 || patterns[0] != "gpt-4o" || patterns[1] != "42" {
		t.Fatalf("mixed list decoded as %v ok=%v", patterns, ok)
	}

	// A null entry cannot be a pattern, so the column as a whole is treated as
	// malformed and denies rather than silently dropping the entry.
	if _, ok := allowedModelPatterns(json.RawMessage(`["gpt-4o", null]`)); ok {
		t.Fatal("a null entry must be reported as invalid")
	}

	if _, ok := allowedModelPatterns(json.RawMessage(`{"not":"a list"}`)); ok {
		t.Fatal("a malformed column must be reported as invalid, not as empty")
	}
}

// A corrupted allow-list must deny rather than allow everything.
func TestModelAllowedForTokenRejectsMalformed(t *testing.T) {
	token := &database.VoidToken{AllowedModels: database.JSON(`{"oops":true}`)}
	if modelAllowedForToken(token, "gpt-4o") {
		t.Fatal("a malformed allow-list must not fall open")
	}
}

func TestModelAllowedForToken(t *testing.T) {
	empty := &database.VoidToken{AllowedModels: database.JSON(`[]`)}
	if !modelAllowedForToken(empty, "gpt-4o") {
		t.Fatal("an empty allow-list allows everything")
	}
	wildcard := &database.VoidToken{AllowedModels: database.JSON(`["openrouter/*"]`)}
	if !modelAllowedForToken(wildcard, "openrouter/stealth/x") {
		t.Fatal("a slash-spanning wildcard must match")
	}
	if modelAllowedForToken(wildcard, "anthropic/claude") {
		t.Fatal("an unrelated model must be denied")
	}
	exact := &database.VoidToken{AllowedModels: database.JSON(`["gpt-4o"]`)}
	if !modelAllowedForToken(exact, "gpt-4o") || modelAllowedForToken(exact, "gpt-4o-mini") {
		t.Fatal("exact matching must not be a prefix match")
	}
}
