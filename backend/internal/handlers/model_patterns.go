package handlers

import (
	"encoding/json"
	"strconv"
)

// allowedModelPatterns decodes a token's model allow-list into patterns.
//
// The column is user-supplied JSON, so it may hold numbers or nulls. Coercing
// each entry to a string (as the Python backend did) keeps a bad entry from
// silently widening access: an undecodable value yields ok=false, which callers
// treat as "deny" rather than "no allow-list means everything".
func allowedModelPatterns(raw []byte) (patterns []string, ok bool) {
	if len(raw) == 0 {
		return nil, true
	}
	var anyList []any
	if err := json.Unmarshal(raw, &anyList); err == nil {
		out := make([]string, 0, len(anyList))
		for _, v := range anyList {
			switch t := v.(type) {
			case string:
				out = append(out, t)
			case float64:
				out = append(out, strconv.FormatFloat(t, 'f', -1, 64))
			default:
				// null / object / bool: the column does not hold the pattern
				// grammar, so deny rather than reason about a partial list.
				return nil, false
			}
		}
		return out, true
	}
	var strList []string
	if err := json.Unmarshal(raw, &strList); err == nil {
		return strList, true
	}
	return nil, false
}

// globMatch reports whether name matches an fnmatch-style pattern.
//
// The allow-list grammar is the one the plugin and dashboard document — shell
// wildcards where `*` matches anything including `/` (so `openrouter/*` covers
// `openrouter/stealth/x`), `?` matches one character, `[abc]`/`[a-z]` is a set,
// and `[!abc]` negates it. path/filepath's Match is *not* usable here: it stops
// `*` at a slash and reads `[!…]` as a literal set, both of which change which
// models a token may call.
func globMatch(pattern, name string) bool {
	return globMatchRunes([]rune(pattern), []rune(name))
}

func globMatchRunes(p, n []rune) bool {
	for len(p) > 0 {
		switch p[0] {
		case '*':
			// Collapse consecutive wildcards, then try every split point.
			for len(p) > 1 && p[1] == '*' {
				p = p[1:]
			}
			if len(p) == 1 {
				return true
			}
			for i := 0; i <= len(n); i++ {
				if globMatchRunes(p[1:], n[i:]) {
					return true
				}
			}
			return false
		case '?':
			if len(n) == 0 {
				return false
			}
			p, n = p[1:], n[1:]
		case '[':
			if len(n) == 0 {
				return false
			}
			matched, rest, ok := matchSet(p, n[0])
			if !ok {
				// An unterminated set is a literal '['.
				if n[0] != '[' {
					return false
				}
				p, n = p[1:], n[1:]
				continue
			}
			if !matched {
				return false
			}
			p, n = rest, n[1:]
		default:
			if len(n) == 0 || p[0] != n[0] {
				return false
			}
			p, n = p[1:], n[1:]
		}
	}
	return len(n) == 0
}

// matchSet evaluates a `[...]` set at the head of pattern against r, returning
// the remaining pattern. ok is false when the set is unterminated.
func matchSet(p []rune, r rune) (matched bool, rest []rune, ok bool) {
	i := 1
	negate := false
	if i < len(p) && (p[i] == '!' || p[i] == '^') {
		negate = true
		i++
	}
	found := false
	first := true
	for i < len(p) {
		if p[i] == ']' && !first {
			if negate {
				return !found, p[i+1:], true
			}
			return found, p[i+1:], true
		}
		first = false
		// A range like a-z, but a trailing '-' is a literal.
		if i+2 < len(p) && p[i+1] == '-' && p[i+2] != ']' {
			if p[i] <= r && r <= p[i+2] {
				found = true
			}
			i += 3
			continue
		}
		if p[i] == r {
			found = true
		}
		i++
	}
	return false, nil, false
}
