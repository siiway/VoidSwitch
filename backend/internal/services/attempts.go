package services

import (
	"encoding/json"
	"io"
	"net/http"
	"net/url"
	"strings"
	"sync"
)

// AttemptRecord is one entry in a request's failover trail. The same struct is
// serialized two ways: the always-on attempts_summary (chain only, kept for the
// life of the row) and the debug_attempts (chain + redacted headers + captured
// bodies, stripped by the debug retention window).
type AttemptRecord struct {
	Attempt          int               `json:"attempt"`
	ProviderAttempt  *int              `json:"provider_attempt,omitempty"`
	Skipped          bool              `json:"skipped,omitempty"`
	Reason           *string           `json:"reason,omitempty"`
	Provider         *string           `json:"provider,omitempty"`
	ProviderID       *int              `json:"provider_id,omitempty"`
	KeyID            *int              `json:"key_id,omitempty"`
	KeyPreview       *string           `json:"key_preview,omitempty"`
	Pool             *string           `json:"pool,omitempty"`
	UpstreamModel    *string           `json:"upstream_model,omitempty"`
	Method           *string           `json:"method,omitempty"`
	URL              *string           `json:"url,omitempty"`
	ProxyURL         *string           `json:"proxy_url,omitempty"`
	LocalAddress     *string           `json:"local_address,omitempty"`
	RouteType        *string           `json:"route_type,omitempty"`
	ReqHeaders       map[string]string `json:"req_headers,omitempty"`
	ReqBody          any               `json:"req_body,omitempty"`
	StatusCode       *int              `json:"status_code,omitempty"`
	ErrorClass       *string           `json:"error_class,omitempty"`
	NetworkError     bool              `json:"network_error,omitempty"`
	Error            *string           `json:"error,omitempty"`
	RespHeaders      map[string]string `json:"resp_headers,omitempty"`
	RespBody         any               `json:"resp_body,omitempty"`
	PromptTokens     int64             `json:"prompt_tokens,omitempty"`
	CompletionTokens int64             `json:"completion_tokens,omitempty"`
	TotalTokens      int64             `json:"total_tokens,omitempty"`
	DurationMs       *float64          `json:"duration_ms,omitempty"`
	// ConnectMs is how long it took to obtain a usable upstream connection
	// (DNS + TCP + TLS). Nil when unmeasured (the agent path, or a failure
	// before the dial started).
	ConnectMs       *float64         `json:"connect_ms,omitempty"`
	NetworkAttempts []NetworkAttempt `json:"network_attempts,omitempty"`

	// respCapture holds the upstream SSE accumulated while a streaming response
	// drains. Full() resolves it into RespBody at log time.
	respCapture *bodyCapture
}

// NetworkAttempt is one network call inside an attempt. The dispatcher currently
// makes exactly one call per attempt; the array keeps the shape the UI renders
// (and the history a future per-provider network retry would add).
type NetworkAttempt struct {
	Attempt         int      `json:"attempt"`
	NodeID          *int     `json:"node_id,omitempty"`
	RouteType       *string  `json:"route_type,omitempty"`
	StatusCode      *int     `json:"status_code,omitempty"`
	Error           *string  `json:"error,omitempty"`
	PoolTimeout     bool     `json:"pool_timeout,omitempty"`
	DeadlineTimeout bool     `json:"deadline_timeout,omitempty"`
	DurationMs      *float64 `json:"duration_ms,omitempty"`
}

// Chain returns the always-visible projection of an attempt: routing identity,
// status, error and timing, with every header/body and the egress address (which
// can carry proxy credentials) removed. The coarse RouteType is kept so the UI
// can still say which egress class was used.
func (r *AttemptRecord) Chain() AttemptRecord {
	out := *r
	out.ReqHeaders = nil
	out.ReqBody = nil
	out.RespHeaders = nil
	out.RespBody = nil
	out.ProxyURL = nil
	out.LocalAddress = nil
	out.respCapture = nil
	return out
}

// Full returns the debug projection of an attempt: the chain plus the redacted
// headers already captured and, when debug capture was on, the bodies. A
// streamed body is read out of the capture buffer here.
func (r *AttemptRecord) Full() AttemptRecord {
	out := *r
	if out.RespBody == nil && r.respCapture != nil {
		if s := r.respCapture.String(); s != "" {
			out.RespBody = s
		}
	}
	out.respCapture = nil
	return out
}

// logBodyCaptureMax returns the configured cap (bytes) for a captured body. A
// non-positive value means "no cap".
func logBodyCaptureMax() int {
	return GetInt("log_body_capture_max_bytes", 262144)
}

// captureBody turns raw response bytes into the value stored on a log row:
// parsed JSON when it fits under the cap, otherwise a byte-truncated string so
// one large body cannot bloat the row.
func captureBody(raw []byte, max int) any {
	if len(raw) == 0 {
		return nil
	}
	if max > 0 && len(raw) > max {
		return string(raw[:max]) + "…<truncated>"
	}
	var v any
	if err := json.Unmarshal(raw, &v); err == nil {
		return v
	}
	return string(raw)
}

// captureValue is captureBody for an already-decoded value (a request body that
// was built as a map).
func captureValue(v any, max int) any {
	if v == nil {
		return nil
	}
	raw, err := json.Marshal(v)
	if err != nil {
		return nil
	}
	return captureBody(raw, max)
}

// isSensitiveHeader reports whether a header name carries a credential. It is
// pattern-based rather than an allowlist: providers stash keys in many shapes
// (Cookie: sso=…, x-goog-api-key, x-auth-token) and operators can add arbitrary
// ones through extra_headers, so enumerating the safe set is not viable.
func isSensitiveHeader(name string) bool {
	n := strings.ToLower(strings.TrimSpace(name))
	switch n {
	case "authorization", "proxy-authorization", "cookie", "set-cookie", "www-authenticate":
		return true
	}
	for _, frag := range []string{"key", "token", "secret", "auth", "signature", "credential", "password", "session"} {
		if strings.Contains(n, frag) {
			return true
		}
	}
	return false
}

// redactRequestHeaders masks credential-bearing outbound header values while
// keeping the header names, so the trail still shows which auth scheme a
// provider used without persisting the key.
func redactRequestHeaders(h map[string]string) map[string]string {
	if h == nil {
		return nil
	}
	out := make(map[string]string, len(h))
	for k, v := range h {
		if isSensitiveHeader(k) {
			out[k] = "<redacted>"
		} else {
			out[k] = v
		}
	}
	return out
}

// routeTypeOf maps an egress to the coarse route type the UI shows. It mirrors
// what redactAttemptSummaries derives after stripping proxy_url/local_address.
func routeTypeOf(e Egress) string {
	switch e.NodeKind {
	case "agent":
		return "agent"
	case "http", "socks5":
		return "proxy"
	default:
		if e.LocalAddress != nil && *e.LocalAddress != "" {
			return "local"
		}
		return "direct"
	}
}

// redactEgressText removes the resolved egress address (proxy URL, agent URL or
// local bind address) from an error string before it is stored. Go's proxy dial
// errors carry the host:port, which a non-owner must not see in the failover
// trail; each attempt may pick a different node, so stripping at the source is
// the only reliable point.
func redactEgressText(s string, e Egress) string {
	if s == "" {
		return s
	}
	for _, raw := range []string{egressStr(e.ProxyURL), e.AgentURL, egressStr(e.LocalAddress)} {
		if raw == "" {
			continue
		}
		s = strings.ReplaceAll(s, raw, "<REDACTED:egress>")
		if u, err := url.Parse(raw); err == nil && u.Host != "" {
			s = strings.ReplaceAll(s, u.Host, "<REDACTED:egress>")
		}
	}
	return s
}

func egressStr(p *string) string {
	if p == nil {
		return ""
	}
	return *p
}

// bodyCapture accumulates a streamed upstream body up to a byte cap.
type bodyCapture struct {
	mu  sync.Mutex
	buf []byte
	max int
}

func newBodyCapture(max int) *bodyCapture { return &bodyCapture{max: max} }

func (c *bodyCapture) write(p []byte) {
	if c == nil || len(p) == 0 {
		return
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.max > 0 {
		if len(c.buf) >= c.max {
			return
		}
		if remain := c.max - len(c.buf); len(p) > remain {
			p = p[:remain]
		}
	}
	c.buf = append(c.buf, p...)
}

func (c *bodyCapture) String() string {
	if c == nil {
		return ""
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	return string(c.buf)
}

// captureReader tees a streamed upstream body into a bodyCapture.
type captureReader struct {
	src io.ReadCloser
	c   *bodyCapture
}

func (r *captureReader) Read(p []byte) (int, error) {
	n, err := r.src.Read(p)
	if n > 0 {
		r.c.write(p[:n])
	}
	return n, err
}

func (r *captureReader) Close() error { return r.src.Close() }

// redactedResponseHeaders copies response headers, masking credential-bearing
// values. Reuses redactedHeaders so a Set-Cookie or auth echo cannot leak.
func redactedResponseHeaders(h http.Header) map[string]string {
	if h == nil {
		return nil
	}
	return redactedHeaders(h)
}

func strPtr(s string) *string { return &s }

func intPtr(n int) *int { return &n }

func intPtrOrNil(n int) *int {
	if n == 0 {
		return nil
	}
	return &n
}

func nullableString(s string) *string {
	if s == "" {
		return nil
	}
	return &s
}
