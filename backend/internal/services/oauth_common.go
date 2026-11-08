package services

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"strings"
	"sync"
	"time"
)

// loginState is one pending interactive OAuth login.
type loginState struct {
	Verifier   string
	ProviderID int
	Created    time.Time
}

// loginStateStore is a TTL-bounded store of pending logins keyed by state.
type loginStateStore struct {
	store map[string]loginState
	ttl   time.Duration
	mu    sync.Mutex
}

func newLoginStateStore(ttl time.Duration) *loginStateStore {
	return &loginStateStore{store: map[string]loginState{}, ttl: ttl}
}

func (s *loginStateStore) put(state, verifier string, providerID int) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.gc()
	s.store[state] = loginState{Verifier: verifier, ProviderID: providerID, Created: time.Now()}
}

func (s *loginStateStore) get(state string) *loginState {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.gc()
	v, ok := s.store[state]
	if !ok {
		return nil
	}
	return &v
}

func (s *loginStateStore) discard(state string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	delete(s.store, state)
}

func (s *loginStateStore) gc() {
	cutoff := time.Now().Add(-s.ttl)
	for k, v := range s.store {
		if v.Created.Before(cutoff) {
			delete(s.store, k)
		}
	}
}

// extractOAuthCode parses a pasted callback URL (…?code=…&state=…) or a bare
// code. Returns the code and the embedded state (if any).
func extractOAuthCode(raw string) (code string, embeddedState string) {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return "", ""
	}
	if strings.Contains(raw, "://") || strings.Contains(raw, "code=") {
		q := raw
		if i := strings.Index(raw, "?"); i >= 0 {
			q = raw[i+1:]
		}
		vals := parseQuery(q)
		return vals["code"], vals["state"]
	}
	return raw, ""
}

// parseQuery is a tiny query parser (avoids url.Parse treating the pasted text
// as a path when it has no scheme).
func parseQuery(q string) map[string]string {
	out := map[string]string{}
	for _, pair := range strings.Split(q, "&") {
		if pair == "" {
			continue
		}
		k, v, _ := strings.Cut(pair, "=")
		out[unescape(k)] = unescape(v)
	}
	return out
}

func unescape(s string) string {
	s = strings.ReplaceAll(s, "+", " ")
	s = strings.ReplaceAll(s, "%3A", ":")
	s = strings.ReplaceAll(s, "%2F", "/")
	s = strings.ReplaceAll(s, "%3D", "=")
	return s
}

// postJSONForm posts an application/x-www-form-urlencoded (or JSON) body to an
// OAuth token endpoint and decodes the JSON response.
func postOAuth(ctx context.Context, url string, headers map[string]string, form map[string]string, bodyJSON map[string]any) (map[string]any, int, []byte, error) {
	var reader *strings.Reader
	ct := "application/x-www-form-urlencoded"
	if form != nil {
		vals := make([]string, 0, len(form))
		for k, v := range form {
			vals = append(vals, escape(k)+"="+escape(v))
		}
		reader = strings.NewReader(strings.Join(vals, "&"))
	} else {
		b, _ := json.Marshal(bodyJSON)
		reader = strings.NewReader(string(b))
		ct = "application/json"
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, url, reader)
	if err != nil {
		return nil, 0, nil, err
	}
	req.Header.Set("Content-Type", ct)
	for k, v := range headers {
		req.Header.Set(k, v)
	}
	client := &http.Client{Timeout: 30 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return nil, 0, nil, err
	}
	defer resp.Body.Close()
	raw, _ := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
	var out map[string]any
	if len(raw) > 0 {
		_ = json.Unmarshal(raw, &out)
	}
	return out, resp.StatusCode, raw, nil
}

func escape(s string) string {
	r := strings.NewReplacer("%", "%25", "&", "%26", "=", "%3D", "+", "%2B", " ", "%20", ":", "%3A", "/", "%2F", "\n", "%0A")
	return r.Replace(s)
}
