package services

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"sort"
	"strings"
	"time"
)

// ModelsFetchError explains why "fetch models from API" failed, in enough detail
// to debug the upstream: the exact request, the upstream's status, the response
// headers and body, plus the upstream status code so callers can propagate it
// instead of masking everything as a relay 502.
type ModelsFetchError struct {
	// Endpoint is the URL that was actually requested.
	Endpoint string
	Method   string
	// Status/StatusText are the upstream's, zero when no response arrived.
	Status     int
	StatusText string
	// Headers is a redacted, sorted copy of the response headers.
	Headers map[string]string
	// Body is a redacted, truncated copy of the response body.
	Body string
	// Reason is a short human summary ("upstream returned 401", "connection
	// refused", "response is not JSON").
	Reason string
	// Err carries the underlying transport/parse error when there was one.
	Err error
}

// Error renders a multi-line, copy-pasteable diagnostic.
func (e *ModelsFetchError) Error() string {
	var b strings.Builder
	b.WriteString(e.Reason)
	b.WriteString("\nrequest: ")
	if e.Method != "" {
		b.WriteString(e.Method)
		b.WriteString(" ")
	}
	b.WriteString(e.Endpoint)
	if e.Status != 0 {
		fmt.Fprintf(&b, "\nstatus: %d %s", e.Status, e.StatusText)
	}
	if len(e.Headers) > 0 {
		b.WriteString("\nheaders:")
		keys := make([]string, 0, len(e.Headers))
		for k := range e.Headers {
			keys = append(keys, k)
		}
		sort.Strings(keys)
		for _, k := range keys {
			fmt.Fprintf(&b, "\n  %s: %s", k, e.Headers[k])
		}
	}
	if e.Body != "" {
		b.WriteString("\nbody: ")
		b.WriteString(e.Body)
	}
	if e.Err != nil {
		fmt.Fprintf(&b, "\nerror: %v", e.Err)
	}
	return b.String()
}

// Unwrap exposes the underlying cause to errors.Is/As.
func (e *ModelsFetchError) Unwrap() error { return e.Err }

// StatusCode is the upstream status, or 0 when no response was received.
func (e *ModelsFetchError) StatusCode() int { return e.Status }

// ErrorStatus is the HTTP status the admin API should answer with: the upstream's
// own code when there is one, 504 when the upstream timed out, otherwise 502
// (the relay could not get an answer).
func (e *ModelsFetchError) ErrorStatus() int {
	if e.Status >= 400 {
		return e.Status
	}
	var ne net.Error
	if errors.As(e.Err, &ne) && ne.Timeout() {
		return http.StatusGatewayTimeout
	}
	return http.StatusBadGateway
}

// maxFetchErrorBody bounds how much of an upstream body is echoed back.
const maxFetchErrorBody = 2000

// resolveFetchEndpoint joins a provider base URL and a models path the way the
// Python backend did (urljoin on the base **directory**), so a relative path
// such as "../models" climbs out of the base URL's last segment, and an
// absolute http(s) path is used verbatim.
func resolveFetchEndpoint(baseURL, path string) (string, error) {
	rawPath := strings.TrimSpace(path)
	if strings.HasPrefix(rawPath, "http://") || strings.HasPrefix(rawPath, "https://") {
		u, err := url.Parse(rawPath)
		if err != nil {
			return rawPath, fmt.Errorf("invalid URL: %w", err)
		}
		if u.Host == "" {
			return rawPath, fmt.Errorf("the URL has no host")
		}
		return u.String(), nil
	}

	base, err := url.Parse(strings.TrimSpace(baseURL))
	if err != nil {
		return "", fmt.Errorf("invalid base URL: %w", err)
	}
	if base.Host == "" {
		return "", fmt.Errorf("the base URL has no host")
	}
	// Force a trailing slash so the path resolves against the base directory
	// rather than replacing its last segment ("…/v1" + "models" must not become
	// "…/models").
	if !strings.HasSuffix(base.Path, "/") {
		base.Path += "/"
	}
	ref, err := url.Parse(strings.TrimLeft(rawPath, "/"))
	if err != nil {
		return "", fmt.Errorf("invalid path: %w", err)
	}
	return base.ResolveReference(ref).String(), nil
}

// redactedHeaders copies response headers, masking credential-bearing values.
// Response headers use a narrower credential set than request headers: an
// upstream's rate-limit headers (x-ratelimit-*-tokens) are valuable diagnostic
// data and must not be blanket-redacted by a bare "token" match.
func redactedHeaders(h http.Header) map[string]string {
	out := make(map[string]string, len(h))
	for k, v := range h {
		joined := strings.Join(v, ", ")
		if joined != "" && isSensitiveResponseHeader(k) {
			joined = "<redacted>"
		}
		out[k] = joined
	}
	return out
}

// isSensitiveResponseHeader reports whether a response header name carries a
// credential. Kept in sync with isSensitiveHeader's intent but without the broad
// "key"/"token"/"auth" substrings that would also catch rate-limit headers.
func isSensitiveResponseHeader(name string) bool {
	n := strings.ToLower(strings.TrimSpace(name))
	switch n {
	case "set-cookie", "cookie", "authorization", "proxy-authorization",
		"x-api-key", "api-key", "x-goog-api-key", "x-auth-token":
		return true
	}
	for _, frag := range []string{"secret", "credential", "signature", "private-key"} {
		if strings.Contains(n, frag) {
			return true
		}
	}
	return false
}

// FetchUpstreamModels calls a provider's models endpoint and extracts model ids.
// Used by the "fetch models from API" admin flow. Failures return a
// *ModelsFetchError carrying the upstream status, headers and body.
func FetchUpstreamModels(ctx context.Context, baseURL, method, path, token, keyRef string) ([]string, error) {
	if path == "" {
		path = "/models"
	}
	if method == "" {
		method = http.MethodGet
	}
	endpoint, err := resolveFetchEndpoint(baseURL, path)
	if err != nil {
		return nil, &ModelsFetchError{
			Endpoint: endpoint, Method: method, Reason: err.Error(), Err: err,
		}
	}
	req, err := http.NewRequestWithContext(ctx, method, endpoint, nil)
	if err != nil {
		return nil, &ModelsFetchError{
			Endpoint: endpoint, Method: method, Reason: "cannot build the request", Err: err,
		}
	}
	if token != "" {
		req.Header.Set("Authorization", "Bearer "+token)
	}
	client := &http.Client{Timeout: 20 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return nil, &ModelsFetchError{
			Endpoint: endpoint, Method: method,
			Reason: "the gateway could not reach the upstream", Err: err,
		}
	}
	defer resp.Body.Close()
	body, readErr := io.ReadAll(io.LimitReader(resp.Body, 4<<20))
	bodyText := redactSecrets(string(body), token)

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return nil, &ModelsFetchError{
			Endpoint: endpoint, Method: method,
			Status: resp.StatusCode, StatusText: resp.Status,
			Headers: redactedHeaders(resp.Header),
			Body:    truncateBody(bodyText),
			Reason:  fmt.Sprintf("upstream returned %d", resp.StatusCode),
			Err:     readErr,
		}
	}
	var payload any
	if err := json.Unmarshal(body, &payload); err != nil {
		// The most common cause is an HTML error/login page served with 200.
		return nil, &ModelsFetchError{
			Endpoint: endpoint, Method: method,
			Status: resp.StatusCode, StatusText: resp.Status,
			Headers: redactedHeaders(resp.Header),
			Body:    truncateBody(bodyText),
			Reason:  "the response is not the expected JSON model list",
			Err:     err,
		}
	}
	items, ok := modelListItems(payload)
	if !ok {
		return nil, &ModelsFetchError{
			Endpoint: endpoint, Method: method,
			Status: resp.StatusCode, StatusText: resp.Status,
			Headers: redactedHeaders(resp.Header),
			Body:    truncateBody(bodyText),
			Reason:  "the response has no data/models/result model list",
		}
	}
	seen := map[string]bool{}
	var out []string
	for _, item := range items {
		id := modelItemID(item)
		if id != "" && !seen[id] {
			seen[id] = true
			out = append(out, id)
		}
	}
	return out, nil
}

// modelListItems locates the model array in an upstream payload. Upstreams
// disagree: OpenAI returns {"data":[…]}, some return {"models":[…]}, a few wrap
// it in "result", and a handful return a bare array.
func modelListItems(payload any) ([]any, bool) {
	switch v := payload.(type) {
	case []any:
		return v, true
	case map[string]any:
		for _, key := range []string{"data", "models", "result"} {
			if items, ok := v[key].([]any); ok {
				return items, true
			}
		}
	}
	return nil, false
}

// modelItemID reads an id (falling back to name) from one list entry, which may
// be a bare string on some upstreams.
func modelItemID(item any) string {
	switch v := item.(type) {
	case string:
		return v
	case map[string]any:
		for _, key := range []string{"id", "name"} {
			if s, ok := v[key].(string); ok && s != "" {
				return s
			}
		}
	}
	return ""
}

// truncateBody caps a body echo so a huge error page cannot flood the response.
func truncateBody(s string) string {
	s = strings.TrimSpace(s)
	if len(s) > maxFetchErrorBody {
		return s[:maxFetchErrorBody] + " …(truncated)"
	}
	return s
}

// redactSecrets removes a credential from a free-form string. The token is known
// here because the gateway itself sent it, so an upstream echoing it back (some
// do, in error text) must not reach the admin UI.
func redactSecrets(s, token string) string {
	if token == "" {
		return s
	}
	return strings.ReplaceAll(s, token, "<redacted>")
}

// ProbeProxy checks whether a proxy URL can reach a well-known endpoint.
func ProbeProxy(ctx context.Context, proxyURL string) (ok bool, status int, latencyMs float64, errStr string) {
	pu, err := url.Parse(proxyURL)
	if err != nil {
		return false, 0, 0, err.Error()
	}
	transport := &http.Transport{Proxy: http.ProxyURL(pu)}
	client := &http.Client{Transport: transport, Timeout: 10 * time.Second}
	start := time.Now()
	resp, err := client.Get("https://www.gstatic.com/generate_204")
	elapsed := float64(time.Since(start).Milliseconds())
	if err != nil {
		return false, 0, elapsed, err.Error()
	}
	defer resp.Body.Close()
	return resp.StatusCode < 400, resp.StatusCode, elapsed, ""
}
