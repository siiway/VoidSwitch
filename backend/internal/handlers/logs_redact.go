package handlers

import (
	"net/url"
	"regexp"
	"strings"
)

// urlAuthorityRe matches "scheme://authority" so userinfo can be stripped while
// leaving the rest of a URL (and any surrounding error text) intact.
var urlAuthorityRe = regexp.MustCompile(`(?i)\b(https?://)([^/\s"']+)`)

// redactProxyURL removes credentials from a proxy URL, keeping host and port so
// the export still shows which egress was used.
func redactProxyURL(u string) string {
	parsed, err := url.Parse(u)
	if err != nil || parsed.Host == "" {
		return "<REDACTED:proxy>"
	}
	parsed.User = nil
	return parsed.String()
}

// downloadSafe walks a JSON-ish value and strips the secrets a request-log
// export must never contain: provider keys, bearer tokens, proxy credentials and
// local egress addresses. `includeBodies` is false for non-owner exports, which
// must not carry request/response bodies.
//
// Strings are scrubbed in place rather than collapsed to a generic message, so a
// failing request stays diagnosable ("connect to <REDACTED:proxy> timed out").
func downloadSafe(value any, includeBodies bool, secrets map[string]string) any {
	switch v := value.(type) {
	case []any:
		out := make([]any, 0, len(v))
		for _, item := range v {
			out = append(out, downloadSafe(item, includeBodies, secrets))
		}
		return out
	case map[string]any:
		out := make(map[string]any, len(v))
		for key, item := range v {
			switch key {
			case "proxy_url":
				if item != nil {
					out[key] = redactProxyURL(toStr(item))
					continue
				}
				out[key] = nil
			case "local_address", "key", "api_key", "access_token":
				out[key] = nil
			case "key_preview":
				// A preview is already masked; keeping it makes the export
				// diagnosable ("which key pool served this") without revealing
				// the credential.
				if s := toStr(item); s != "" {
					out[key] = maskKeyPreview(s)
				} else {
					out[key] = nil
				}
			case "req_body", "resp_body":
				if !includeBodies {
					out[key] = nil
					continue
				}
				out[key] = downloadSafe(item, includeBodies, secrets)
			default:
				out[key] = downloadSafe(item, includeBodies, secrets)
			}
		}
		return out
	case string:
		return scrubSecrets(v, secrets)
	}
	return value
}

// scrubSecrets replaces any known secret / egress value inside a free-form
// string, then strips URL userinfo.
func scrubSecrets(s string, secrets map[string]string) string {
	for needle, replacement := range secrets {
		if needle == "" {
			continue
		}
		s = strings.ReplaceAll(s, needle, replacement)
	}
	return urlAuthorityRe.ReplaceAllStringFunc(s, func(match string) string {
		loc := urlAuthorityRe.FindStringSubmatch(match)
		if len(loc) != 3 {
			return match
		}
		authority := loc[2]
		if i := strings.LastIndex(authority, "@"); i >= 0 {
			authority = authority[i+1:]
		}
		return loc[1] + authority
	})
}

func toStr(v any) string {
	if s, ok := v.(string); ok {
		return s
	}
	return ""
}

// maskKeyPreview shows the first and last four characters of a provider key
// preview, hiding the middle. A preview of eight characters or fewer is short
// enough to be meaningless and is returned unchanged, matching the Python
// backend so an operator still recognises the key in the log detail.
func maskKeyPreview(preview string) string {
	// Count runes, not bytes: a preview may already contain "…", and slicing
	// bytes would split it into invalid UTF-8.
	r := []rune(preview)
	if len(r) <= 8 {
		return preview
	}
	return string(r[:4]) + "***" + string(r[len(r)-4:])
}

// redactAttemptSummaries strips the route secrets from persisted attempt
// summaries, keeping the shape so a member still sees which route type was used
// without learning the egress address. Python published "route_type" in place of
// the removed fields rather than silently dropping the information.
func redactAttemptSummaries(value any) any {
	switch v := value.(type) {
	case []any:
		out := make([]any, 0, len(v))
		for _, item := range v {
			out = append(out, redactAttemptSummaries(item))
		}
		return out
	case map[string]any:
		hadProxy := false
		hadLocal := false
		out := make(map[string]any, len(v)+1)
		for key, item := range v {
			switch key {
			case "proxy_url":
				if item != nil && toStr(item) != "" {
					hadProxy = true
				}
				continue
			case "local_address":
				if item != nil && toStr(item) != "" {
					hadLocal = true
				}
				continue
			}
			out[key] = redactAttemptSummaries(item)
		}
		if _, ok := out["route_type"]; !ok {
			if hadProxy {
				out["route_type"] = "proxy"
			} else if hadLocal {
				out["route_type"] = "local"
			}
		}
		return out
	}
	return value
}

// stripAttemptBodies nulls every req_body/resp_body inside the debug attempt
// trail at any depth. Staff may see per-attempt headers but never bodies; the
// skip saves the client from receiving payloads it may not display.
func stripAttemptBodies(value any) any {
	switch v := value.(type) {
	case []any:
		out := make([]any, 0, len(v))
		for _, item := range v {
			out = append(out, stripAttemptBodies(item))
		}
		return out
	case map[string]any:
		out := make(map[string]any, len(v))
		for key, item := range v {
			if key == "req_body" || key == "resp_body" {
				out[key] = nil
				continue
			}
			out[key] = stripAttemptBodies(item)
		}
		return out
	}
	return value
}

// stripAttemptKeys nulls the provider-key identifiers inside a chain summary. A
// member sees their own traffic, but which credential pool served it is an
// operator concern (staff and role-group admins still get the masked preview).
func stripAttemptKeys(value any) any {
	switch v := value.(type) {
	case []any:
		out := make([]any, 0, len(v))
		for _, item := range v {
			out = append(out, stripAttemptKeys(item))
		}
		return out
	case map[string]any:
		out := make(map[string]any, len(v))
		for key, item := range v {
			switch key {
			case "key_preview", "key_id":
				out[key] = nil
			default:
				out[key] = stripAttemptKeys(item)
			}
		}
		return out
	}
	return value
}
