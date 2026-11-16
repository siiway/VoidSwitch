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
			case "local_address", "key", "api_key", "access_token", "key_preview":
				out[key] = nil
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
