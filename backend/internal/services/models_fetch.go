package services

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
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
// own code when there is one, otherwise 502 (the relay could not get an answer).
func (e *ModelsFetchError) ErrorStatus() int {
	if e.Status >= 400 {
		return e.Status
	}
	return http.StatusBadGateway
}

// maxFetchErrorBody bounds how much of an upstream body is echoed back.
const maxFetchErrorBody = 2000

// redactedHeaders copies response headers, masking credential-bearing values.
func redactedHeaders(h http.Header) map[string]string {
	out := make(map[string]string, len(h))
	for k, v := range h {
		joined := strings.Join(v, ", ")
		switch strings.ToLower(k) {
		case "set-cookie", "authorization", "proxy-authorization", "x-api-key", "api-key":
			if joined != "" {
				joined = "<redacted>"
			}
		}
		out[k] = joined
	}
	return out
}

// FetchUpstreamModels calls a provider's models endpoint and extracts model ids.
// Used by the "fetch models from API" admin flow. Failures return a
// *ModelsFetchError carrying the upstream status, headers and body.
func FetchUpstreamModels(ctx context.Context, baseURL, method, path, token, keyRef string) ([]string, error) {
	if path == "" {
		path = "/models"
	}
	endpoint := path
	if !strings.HasPrefix(path, "http://") && !strings.HasPrefix(path, "https://") {
		endpoint = strings.TrimRight(baseURL, "/") + "/" + strings.TrimLeft(path, "/")
	}
	if _, err := url.Parse(endpoint); err != nil {
		return nil, &ModelsFetchError{
			Endpoint: endpoint, Method: method, Reason: "invalid URL", Err: err,
		}
	}
	if method == "" {
		method = http.MethodGet
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
	var parsed struct {
		Data []struct {
			ID string `json:"id"`
		} `json:"data"`
		Models []struct {
			Name string `json:"name"`
			ID   string `json:"id"`
		} `json:"models"`
	}
	if err := json.Unmarshal(body, &parsed); err != nil {
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
	seen := map[string]bool{}
	var out []string
	for _, d := range parsed.Data {
		if d.ID != "" && !seen[d.ID] {
			seen[d.ID] = true
			out = append(out, d.ID)
		}
	}
	for _, m := range parsed.Models {
		id := m.ID
		if id == "" {
			id = m.Name
		}
		if id != "" && !seen[id] {
			seen[id] = true
			out = append(out, id)
		}
	}
	return out, nil
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
