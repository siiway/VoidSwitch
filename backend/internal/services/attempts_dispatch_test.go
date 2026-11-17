package services

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"gorm.io/gorm"

	"github.com/siiway/voidswitch/internal/config"
	"github.com/siiway/voidswitch/internal/constants"
	"github.com/siiway/voidswitch/internal/database"
)

// attemptDispatchReq builds the dispatch input shared by the attempt-recording
// tests below.
func attemptDispatchReq(db *gorm.DB, cfg *config.Settings, stream, debug bool) *DispatchRequest {
	return &DispatchRequest{
		Ctx: context.Background(), DB: db, Cfg: cfg, Pool: GetPool(),
		ExposedModel: "test-model", InboundStyle: constants.ApiStyleOpenAI,
		Stream: stream, Debug: debug,
		Body: map[string]any{
			"model": "test-model", "stream": stream,
			"messages": []any{map[string]any{"role": "user", "content": "hi"}},
		},
	}
}

// An upstream error often echoes the credential it rejected ("Incorrect API key
// provided: sk-…"). Neither the stored attempt, the returned error to the client
// nor the captured body may carry it.
func TestDispatchRedactsKeyEchoedByUpstream(t *testing.T) {
	const plain = "sk-test-key"
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusUnauthorized)
		w.Write([]byte(`{"error":{"message":"Incorrect API key provided: ` + plain + `"}}`))
	}))
	defer srv.Close()

	db := newTestDB(t)
	const secret = "sec"
	seedDispatch(t, db, srv.URL, secret)
	cfg := &config.Settings{}
	cfg.Server.SecretKey = secret

	disp := NewDispatcher(attemptDispatchReq(db, cfg, false, false))
	_, err := disp.Do()
	if err == nil {
		t.Fatal("expected the dispatch to fail")
	}
	if strings.Contains(err.Error(), plain) {
		t.Fatalf("returned error echoed the key: %q", err.Error())
	}

	attempts := disp.Attempts()
	if len(attempts) == 0 {
		t.Fatal("no attempt recorded")
	}
	last := attempts[len(attempts)-1]
	if last.Error == nil || strings.Contains(*last.Error, plain) {
		t.Fatalf("attempt error echoed the key: %v", last.Error)
	}
	var buf strings.Builder
	enc := json.NewEncoder(&buf)
	enc.SetEscapeHTML(false)
	if err := enc.Encode(last.RespBody); err != nil {
		t.Fatal(err)
	}
	raw := buf.String()
	if strings.Contains(raw, plain) {
		t.Fatalf("captured error body echoed the key: %s", raw)
	}
	// The echo was really there and got masked, so this is not passing by luck.
	if !strings.Contains(raw, "<redacted>") {
		t.Fatalf("captured error body was not scrubbed in place: %s", raw)
	}
	if last.StatusCode == nil || *last.StatusCode != http.StatusUnauthorized {
		t.Fatalf("status = %v, want 401", last.StatusCode)
	}
}

// Provider credentials can live in Cookie or in operator-supplied extra_headers
// as well as Authorization; all of them must be masked in the trail while the
// real values still reach the upstream.
func TestDispatchRedactsExtraHeaderCredentials(t *testing.T) {
	const (
		cookie = "sso=real-cookie-value"
		goog   = "real-goog-api-key"
		tag    = "keep-me"
	)
	seen := make(chan http.Header, 1)
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		seen <- r.Header.Clone()
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`{"id":"x","object":"chat.completion","choices":[{"index":0,"message":{"role":"assistant","content":"ok"},"finish_reason":"stop"}],"usage":{"prompt_tokens":1,"completion_tokens":1,"total_tokens":2}}`))
	}))
	defer srv.Close()

	db := newTestDB(t)
	const secret = "sec"
	seedDispatch(t, db, srv.URL, secret)
	var provider database.Provider
	if err := db.Where("slug = ?", "mock").First(&provider).Error; err != nil {
		t.Fatal(err)
	}
	db.Model(&provider).Update("extra_headers", database.JSONOf(map[string]any{
		"Cookie": cookie, "X-Goog-Api-Key": goog, "X-Request-Tag": tag,
	}))
	cfg := &config.Settings{}
	cfg.Server.SecretKey = secret

	disp := NewDispatcher(attemptDispatchReq(db, cfg, false, false))
	if _, err := disp.Do(); err != nil {
		t.Fatalf("dispatch: %v", err)
	}

	var sent http.Header
	select {
	case sent = <-seen:
	case <-time.After(2 * time.Second):
		t.Fatal("upstream never received the request")
	}
	if sent.Get("Cookie") != cookie || sent.Get("X-Goog-Api-Key") != goog {
		t.Fatalf("credentials did not reach the upstream: %v", sent)
	}

	attempts := disp.Attempts()
	if len(attempts) != 1 {
		t.Fatalf("recorded %d attempts, want 1", len(attempts))
	}
	got := attempts[0]
	for name, want := range map[string]string{
		"Authorization":  "<redacted>",
		"Cookie":         "<redacted>",
		"X-Goog-Api-Key": "<redacted>",
		"content-type":   "application/json",
		"X-Request-Tag":  tag,
	} {
		if got.ReqHeaders[name] != want {
			t.Fatalf("header %s = %q, want %q (all: %v)", name, got.ReqHeaders[name], want, got.ReqHeaders)
		}
	}
}

// A streamed success is only captured when the token has debug on, the whole
// body still reaches the client, and Full() resolves the captured SSE.
func TestDispatchStreamCaptureGatedByDebug(t *testing.T) {
	const chunk = `{"id":"c1","object":"chat.completion.chunk","created":1,"model":"upstream-model","choices":[{"index":0,"delta":{"content":"hello-stream"},"finish_reason":null}]}`
	sse := "data: " + chunk + "\n\ndata: [DONE]\n\n"

	for _, debug := range []bool{false, true} {
		t.Run(map[bool]string{true: "debug=true", false: "debug=false"}[debug], func(t *testing.T) {
			srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				w.Header().Set("Content-Type", "text/event-stream")
				w.Write([]byte(sse))
			}))
			defer srv.Close()

			db := newTestDB(t)
			const secret = "sec"
			seedDispatch(t, db, srv.URL, secret)
			cfg := &config.Settings{}
			cfg.Server.SecretKey = secret

			disp := NewDispatcher(attemptDispatchReq(db, cfg, true, debug))
			res, err := disp.Do()
			if err != nil {
				t.Fatalf("dispatch: %v", err)
			}
			if res.Stream == nil {
				t.Fatal("no stream returned")
			}
			downstream, _ := io.ReadAll(res.Stream)
			res.Stream.Close()
			if len(downstream) == 0 {
				t.Fatal("the downstream stream was empty")
			}
			if res.UsageReady != nil {
				select {
				case <-res.UsageReady:
				case <-time.After(2 * time.Second):
					t.Fatal("usage never finalised")
				}
			}

			attempts := disp.Attempts()
			if len(attempts) != 1 {
				t.Fatalf("recorded %d attempts, want 1", len(attempts))
			}
			rec := attempts[0]
			if rec.StatusCode == nil || *rec.StatusCode != http.StatusOK {
				t.Fatalf("status = %v, want 200", rec.StatusCode)
			}
			if rec.ReqHeaders["Accept"] != "text/event-stream" {
				t.Fatalf("streaming accept header not recorded: %v", rec.ReqHeaders)
			}
			body := rec.Full().RespBody
			if debug {
				s, ok := body.(string)
				if !ok || !strings.Contains(s, "hello-stream") {
					t.Fatalf("debug stream body = %v, want the captured SSE", body)
				}
			} else if body != nil {
				t.Fatalf("stream body captured without debug: %v", body)
			}
			if rec.Chain().RespBody != nil {
				t.Fatal("chain projection carried the stream body")
			}
		})
	}
}
