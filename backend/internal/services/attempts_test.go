package services

import (
	"context"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/siiway/voidswitch/internal/config"
	"github.com/siiway/voidswitch/internal/constants"
	"github.com/siiway/voidswitch/internal/cryptoutil"
	"github.com/siiway/voidswitch/internal/database"
)

func TestCaptureBodyRespectsCap(t *testing.T) {
	got := captureBody([]byte(`{"a":1}`), 1024)
	m, ok := got.(map[string]any)
	if !ok || m["a"] != float64(1) {
		t.Fatalf("small json not parsed: %v", got)
	}
	big := []byte(`{"payload":"` + strings.Repeat("x", 100) + `"}`)
	s, ok := captureBody(big, 16).(string)
	if !ok || len(s) != 16+len("…<truncated>") || !strings.HasSuffix(s, "…<truncated>") {
		t.Fatalf("capped body = %v, want a truncated string", captureBody(big, 16))
	}
	if captureBody(nil, 16) != nil {
		t.Fatal("empty body should be nil")
	}
	if got := captureValue(map[string]any{"k": "v"}, 1024); got == nil {
		t.Fatal("captureValue dropped a value")
	}
}

func TestRedactRequestHeadersMasksCredentials(t *testing.T) {
	in := map[string]string{
		"Authorization":   "Bearer sk-secret",
		"x-api-key":       "sk-secret",
		"Cookie":          "sso=sk-secret",
		"x-goog-api-key":  "sk-secret",
		"x-custom-secret": "sk-secret",
		"content-type":    "application/json",
	}
	out := redactRequestHeaders(in)
	for _, name := range []string{"Authorization", "x-api-key", "Cookie", "x-goog-api-key", "x-custom-secret"} {
		if out[name] != "<redacted>" {
			t.Fatalf("%s not masked: %v", name, out)
		}
	}
	if out["content-type"] != "application/json" {
		t.Fatalf("safe header altered: %v", out)
	}
	if in["Authorization"] != "Bearer sk-secret" {
		t.Fatal("input map was mutated")
	}
}

func TestAttemptRecordChainAndFull(t *testing.T) {
	rec := &AttemptRecord{
		Attempt: 1, Provider: strPtr("mock"), URL: strPtr("https://x/v1"),
		ReqHeaders:  map[string]string{"Authorization": "<redacted>"},
		RespHeaders: map[string]string{"content-type": "application/json"},
		ReqBody:     map[string]any{"a": 1}, RespBody: "ok",
	}
	chain := rec.Chain()
	if chain.ReqHeaders != nil || chain.RespHeaders != nil || chain.ReqBody != nil || chain.RespBody != nil {
		t.Fatalf("chain leaked headers/bodies: %+v", chain)
	}
	if chain.Provider == nil || *chain.Provider != "mock" {
		t.Fatal("chain lost the routing identity")
	}
	full := rec.Full()
	if full.ReqHeaders == nil || full.ReqBody == nil || full.RespBody != "ok" {
		t.Fatalf("full lost headers/bodies: %+v", full)
	}

	// A streamed body resolves from the capture buffer.
	streamRec := &AttemptRecord{Attempt: 2, respCapture: newBodyCapture(1024)}
	streamRec.respCapture.write([]byte("data: hello\n\n"))
	if got := streamRec.Full().RespBody; got != "data: hello\n\n" {
		t.Fatalf("stream capture = %v", got)
	}
}

// TestDispatchRecordsAttemptTrail covers the core contract: every failover
// attempt is recorded with its chain, its redacted request headers, the error
// body (always) and — only when debug is on — the request/success bodies.
func TestDispatchRecordsAttemptTrail(t *testing.T) {
	for _, debug := range []bool{false, true} {
		t.Run(fmt.Sprintf("debug=%v", debug), func(t *testing.T) {
			bad := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				w.WriteHeader(http.StatusInternalServerError)
				w.Write([]byte(`{"error":"boom"}`))
			}))
			defer bad.Close()
			good := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				w.Header().Set("Content-Type", "application/json")
				w.Write([]byte(`{"id":"x","object":"chat.completion","choices":[{"index":0,"message":{"role":"assistant","content":"ok"},"finish_reason":"stop"}],"usage":{"prompt_tokens":1,"completion_tokens":1,"total_tokens":2}}`))
			}))
			defer good.Close()

			db := newTestDB(t)
			secret := "sec"
			seedDispatch(t, db, bad.URL, secret)

			p2 := database.Provider{
				UUID: "u2", Name: "good", Slug: "good", Type: "openai", BaseURL: good.URL,
				Enabled: true, KeySelectMode: "round_robin",
				Models: database.JSONOf([]string{}), ModelMap: database.JSONOf(map[string]any{}),
				ModelRoutes: database.JSONOf([]any{}), ExtraHeaders: database.JSONOf(map[string]any{}),
				PassthroughModels:           database.JSONOf([]string{}),
				UpstreamCooldownStatusCodes: database.JSONOf([]int{}),
				UpstreamRetryAfterHeaders:   database.JSONOf([]string{}),
				SelectiveIgnoreRules:        database.JSONOf([]any{}),
			}
			db.Create(&p2)
			ct, _ := cryptoutil.EncryptSecret("sk-good", secret)
			db.Create(&database.ApiKey{ProviderID: p2.ID, KeyCiphertext: ct, KeyHash: "h2", Status: "active", Weight: 1, Balance: database.JSONOf(map[string]any{})})
			var route database.Route
			db.First(&route)
			db.Create(&database.RouteUpstream{RouteID: route.ID, ProviderID: &p2.ID, UpstreamModel: "good-model", Enabled: true, Weight: 1, CooldownStatusCodes: database.JSONOf([]int{})})

			cfg := &config.Settings{}
			cfg.Server.SecretKey = secret
			req := &DispatchRequest{
				Ctx: context.Background(), DB: db, Cfg: cfg, Pool: GetPool(),
				ExposedModel: "test-model", InboundStyle: constants.ApiStyleOpenAI, Debug: debug,
				Body: map[string]any{"model": "test-model", "messages": []any{map[string]any{"role": "user", "content": "hi"}}},
			}
			disp := NewDispatcher(req)
			res, err := disp.Do()
			if err != nil {
				t.Fatalf("dispatch failover: %v", err)
			}
			if res.Provider == nil || res.Provider.Name != "good" {
				t.Fatalf("expected failover to good, got %+v", res.Provider)
			}

			attempts := disp.Attempts()
			if len(attempts) != 2 {
				t.Fatalf("recorded %d attempts, want 2", len(attempts))
			}
			first, second := attempts[0], attempts[1]
			if first.StatusCode == nil || *first.StatusCode != http.StatusInternalServerError {
				t.Fatalf("first attempt status = %v, want 500", first.StatusCode)
			}
			if first.Provider == nil || *first.Provider != "mock" {
				t.Fatalf("first attempt provider = %v", first.Provider)
			}
			if first.Error == nil || *first.Error == "" {
				t.Fatal("first attempt lost its error text")
			}
			if first.ReqHeaders["Authorization"] != "<redacted>" {
				t.Fatalf("request credential not masked: %v", first.ReqHeaders)
			}
			if len(first.NetworkAttempts) != 1 || first.NetworkAttempts[0].StatusCode == nil {
				t.Fatalf("network attempt not recorded: %+v", first.NetworkAttempts)
			}
			// An error body is always captured, debug or not.
			if first.RespBody == nil {
				t.Fatal("error response body was not captured")
			}
			if second.StatusCode == nil || *second.StatusCode != http.StatusOK {
				t.Fatalf("second attempt status = %v, want 200", second.StatusCode)
			}
			if second.TotalTokens != 2 {
				t.Fatalf("second attempt tokens = %d, want 2", second.TotalTokens)
			}
			if debug {
				if first.ReqBody == nil {
					t.Fatal("debug request body was not captured")
				}
				if second.RespBody == nil {
					t.Fatal("debug success response body was not captured")
				}
			} else {
				if first.ReqBody != nil {
					t.Fatal("request body captured without debug")
				}
				if second.RespBody != nil {
					t.Fatal("success response body captured without debug")
				}
			}
		})
	}
}

// TestDispatchRecordsAllFailedAttempts checks the trail is still available when
// every candidate fails (the gateway logs it from the dispatcher, not a result).
func TestDispatchRecordsAllFailedAttempts(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusBadGateway)
		w.Write([]byte(`{"error":"down"}`))
	}))
	defer srv.Close()

	db := newTestDB(t)
	secret := "sec"
	seedDispatch(t, db, srv.URL, secret)

	cfg := &config.Settings{}
	cfg.Server.SecretKey = secret
	req := &DispatchRequest{
		Ctx: context.Background(), DB: db, Cfg: cfg, Pool: GetPool(),
		ExposedModel: "test-model", InboundStyle: constants.ApiStyleOpenAI,
		Body: map[string]any{"model": "test-model", "messages": []any{map[string]any{"role": "user", "content": "hi"}}},
	}
	disp := NewDispatcher(req)
	if _, err := disp.Do(); err == nil {
		t.Fatal("expected the dispatch to fail")
	}
	attempts := disp.Attempts()
	if len(attempts) == 0 {
		t.Fatal("no attempts recorded on a total failure")
	}
	if attempts[len(attempts)-1].StatusCode == nil || *attempts[len(attempts)-1].StatusCode != http.StatusBadGateway {
		t.Fatalf("last attempt status = %v", attempts[len(attempts)-1].StatusCode)
	}
}

// TestCaptureReaderFeedsFull checks the streaming tee: the reader must pass the
// whole body through while the capture is capped, and Full() must resolve the
// captured SSE into RespBody.
func TestCaptureReaderFeedsFull(t *testing.T) {
	const body = "data: hello\n\n"
	rec := &AttemptRecord{Attempt: 1, respCapture: newBodyCapture(8)}
	cr := &captureReader{src: io.NopCloser(strings.NewReader(body)), c: rec.respCapture}
	buf := make([]byte, 64)
	total := 0
	for {
		n, err := cr.Read(buf)
		total += n
		if err != nil {
			break
		}
	}
	if total != len(body) {
		t.Fatalf("read %d bytes, want %d", total, len(body))
	}
	if got := rec.respCapture.String(); len(got) != 8 {
		t.Fatalf("cap not applied: %q", got)
	}
	if got := rec.Full().RespBody; got != body[:8] {
		t.Fatalf("Full() = %v, want the capped SSE", got)
	}
}

// TestRedactEgressText keeps the resolved egress address out of stored network
// errors; each attempt may pick a different node, so the export's per-row scrub
// cannot cover the others.
func TestRedactEgressText(t *testing.T) {
	proxy := "http://user:pass@10.0.0.5:3128"
	msg := `Post "https://api.example.com/v1": proxyconnect tcp: dial tcp 10.0.0.5:3128: connect: connection refused`
	if got := redactEgressText(msg, Egress{NodeKind: "http", ProxyURL: &proxy}); strings.Contains(got, "10.0.0.5") {
		t.Fatalf("proxy host leaked: %q", got)
	}

	agent := "http://agent.internal:8080"
	if got := redactEgressText("dial http://agent.internal:8080/ failed", Egress{NodeKind: "agent", AgentURL: agent}); strings.Contains(got, "agent.internal") {
		t.Fatalf("agent host leaked: %q", got)
	}

	local := "127.0.0.1:9"
	if got := redactEgressText("bind 127.0.0.1:9 failed", Egress{NodeKind: "direct", LocalAddress: &local}); strings.Contains(got, "127.0.0.1") {
		t.Fatalf("local address leaked: %q", got)
	}
}

// TestRedactedResponseHeaders checks the response-side credential set: echoed
// API-key headers are masked while rate-limit headers stay readable.
func TestRedactedResponseHeaders(t *testing.T) {
	out := redactedResponseHeaders(http.Header{
		"X-Goog-Api-Key":               {"sk-secret"},
		"Set-Cookie":                   {"sso=sk-secret"},
		"X-Ratelimit-Remaining-Tokens": {"99"},
		"Content-Type":                 {"application/json"},
	})
	if out["X-Goog-Api-Key"] != "<redacted>" || out["Set-Cookie"] != "<redacted>" {
		t.Fatalf("credential headers not masked: %v", out)
	}
	if out["X-Ratelimit-Remaining-Tokens"] != "99" {
		t.Fatalf("rate-limit header was redacted: %v", out)
	}
	if out["Content-Type"] != "application/json" {
		t.Fatalf("safe header altered: %v", out)
	}
}
