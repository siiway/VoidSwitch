package services

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

// A failing upstream must yield the upstream's own status plus enough context
// (request, headers, body) to debug it — and must not leak the credential.
func TestFetchUpstreamModelsErrorDetail(t *testing.T) {
	const token = "sk-super-secret-token"
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("X-Request-Id", "req-123")
		w.Header().Set("WWW-Authenticate", "Bearer realm=api")
		w.WriteHeader(http.StatusUnauthorized)
		// An upstream that echoes the credential in its error text.
		w.Write([]byte(`{"error":{"message":"bad key ` + token + `"}}`))
	}))
	defer srv.Close()

	_, err := FetchUpstreamModels(context.Background(), srv.URL, http.MethodGet, "/models", token, "")
	if err == nil {
		t.Fatal("expected an error")
	}

	var fe *ModelsFetchError
	if !errors.As(err, &fe) {
		t.Fatalf("error should be *ModelsFetchError, got %T", err)
	}
	if fe.Status != http.StatusUnauthorized {
		t.Fatalf("status = %d, want 401", fe.Status)
	}
	// The admin API must answer with the upstream's code, not a blanket 502.
	if got := fe.ErrorStatus(); got != http.StatusUnauthorized {
		t.Fatalf("ErrorStatus = %d, want 401", got)
	}

	msg := err.Error()
	for _, want := range []string{
		"request: GET " + srv.URL,
		"status: 401",
		"X-Request-Id: req-123",
		"body: ",
	} {
		if !strings.Contains(msg, want) {
			t.Fatalf("diagnostic missing %q:\n%s", want, msg)
		}
	}
	// Header names are canonicalised by net/http, so match insensitively.
	if !strings.Contains(strings.ToLower(msg), "www-authenticate: bearer realm=api") {
		t.Fatalf("diagnostic missing the auth header:\n%s", msg)
	}
	if strings.Contains(msg, token) {
		t.Fatalf("the credential leaked into the diagnostic:\n%s", msg)
	}
	if !strings.Contains(msg, "<redacted>") {
		t.Fatalf("expected the echoed credential to be redacted:\n%s", msg)
	}
}

// Credential-bearing response headers are masked wholesale.
func TestFetchUpstreamModelsRedactsHeaders(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Set-Cookie", "session=abc")
		w.WriteHeader(http.StatusInternalServerError)
	}))
	defer srv.Close()

	_, err := FetchUpstreamModels(context.Background(), srv.URL, "", "", "", "")
	var fe *ModelsFetchError
	if !errors.As(err, &fe) {
		t.Fatalf("want *ModelsFetchError, got %T", err)
	}
	if fe.Headers["Set-Cookie"] != "<redacted>" {
		t.Fatalf("Set-Cookie should be redacted, got %q", fe.Headers["Set-Cookie"])
	}
}

// A 2xx that is not the model list (an HTML login page, say) still explains
// itself instead of a bare parse error.
func TestFetchUpstreamModelsNonJSON(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/html")
		w.Write([]byte("<html>login required</html>"))
	}))
	defer srv.Close()

	_, err := FetchUpstreamModels(context.Background(), srv.URL, "", "", "", "")
	var fe *ModelsFetchError
	if !errors.As(err, &fe) {
		t.Fatalf("want *ModelsFetchError, got %T", err)
	}
	if !strings.Contains(err.Error(), "login required") {
		t.Fatalf("body should be echoed:\n%s", err.Error())
	}
	// No upstream error status: the relay itself failed to produce a usable answer.
	if got := fe.ErrorStatus(); got != http.StatusBadGateway {
		t.Fatalf("ErrorStatus = %d, want 502", got)
	}
}

// A transport failure reports that specifically, and still names the target.
func TestFetchUpstreamModelsUnreachable(t *testing.T) {
	_, err := FetchUpstreamModels(context.Background(), "http://127.0.0.1:1", "", "", "", "")
	var fe *ModelsFetchError
	if !errors.As(err, &fe) {
		t.Fatalf("want *ModelsFetchError, got %T", err)
	}
	if !strings.Contains(err.Error(), "could not reach the upstream") {
		t.Fatalf("should name the transport failure:\n%s", err.Error())
	}
	if !strings.Contains(err.Error(), "request: GET http://127.0.0.1:1/models") {
		t.Fatalf("should name the endpoint:\n%s", err.Error())
	}
}

// A present-but-empty body must not be echoed as noise.
func TestFetchUpstreamModelsTruncatesBody(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusBadRequest)
		w.Write([]byte(strings.Repeat("x", maxFetchErrorBody*2)))
	}))
	defer srv.Close()

	_, err := FetchUpstreamModels(context.Background(), srv.URL, "", "", "", "")
	if !strings.Contains(err.Error(), "…(truncated)") {
		t.Fatalf("a large body should be truncated:\n%.200s", err.Error())
	}
}

// The path joins onto the base URL's directory, so the common "/v1" base URL
// plus the default "/models" lands on "/v1/models", and "../models" climbs out.
func TestResolveFetchEndpoint(t *testing.T) {
	cases := []struct{ base, path, want string }{
		{"https://api.example.com/v1", "/models", "https://api.example.com/v1/models"},
		{"https://api.example.com/v1/", "models", "https://api.example.com/v1/models"},
		{"https://api.example.com/v1", "", "https://api.example.com/v1/models"},
		{"https://api.example.com/client/v4/accounts/x/ai", "../models", "https://api.example.com/client/v4/accounts/x/models"},
		{"https://api.example.com", "/models", "https://api.example.com/models"},
		{"https://api.example.com/v1", "https://other.example.com/models", "https://other.example.com/models"},
	}
	for _, c := range cases {
		path := c.path
		if path == "" {
			path = "/models"
		}
		got, err := resolveFetchEndpoint(c.base, path)
		if err != nil {
			t.Fatalf("%s + %s: unexpected error %v", c.base, c.path, err)
		}
		if got != c.want {
			t.Fatalf("%s + %q = %s, want %s", c.base, c.path, got, c.want)
		}
	}
}

func TestResolveFetchEndpointRejectsHostless(t *testing.T) {
	if _, err := resolveFetchEndpoint("not-a-url", "/models"); err == nil {
		t.Fatal("a hostless base URL must be rejected")
	}
	if _, err := resolveFetchEndpoint("https://api.example.com/v1", "https://"); err == nil {
		t.Fatal("a hostless absolute URL must be rejected")
	}
}

// Upstreams disagree on the envelope: data, models, result, or a bare array,
// with entries that may be strings.
func TestFetchUpstreamModelsPayloadShapes(t *testing.T) {
	cases := []struct {
		name string
		body string
		want []string
	}{
		{"openai data", `{"data":[{"id":"a"},{"id":"b"}]}`, []string{"a", "b"}},
		{"models with name", `{"models":[{"name":"c"}]}`, []string{"c"}},
		{"result key", `{"result":[{"id":"d"}]}`, []string{"d"}},
		{"bare array", `[{"id":"e"},"f"]`, []string{"e", "f"}},
		{"dedupe", `{"data":[{"id":"g"},{"id":"g"}]}`, []string{"g"}},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				w.Write([]byte(c.body))
			}))
			defer srv.Close()
			got, err := FetchUpstreamModels(context.Background(), srv.URL, "", "", "", "")
			if err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			if strings.Join(got, ",") != strings.Join(c.want, ",") {
				t.Fatalf("ids = %v, want %v", got, c.want)
			}
		})
	}
}

// A JSON document without any known envelope explains itself rather than
// reporting a parse failure.
func TestFetchUpstreamModelsUnexpectedShape(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Write([]byte(`{"error":"nope"}`))
	}))
	defer srv.Close()

	_, err := FetchUpstreamModels(context.Background(), srv.URL, "", "", "", "")
	if err == nil || !strings.Contains(err.Error(), "no data/models/result") {
		t.Fatalf("want an envelope diagnostic, got %v", err)
	}
}

// A timed-out upstream answers 504 so the operator can tell it apart from a
// transport failure.
func TestModelsFetchErrorTimeoutStatus(t *testing.T) {
	fe := &ModelsFetchError{Reason: "timed out", Err: timeoutError{}}
	if got := fe.ErrorStatus(); got != http.StatusGatewayTimeout {
		t.Fatalf("ErrorStatus = %d, want 504", got)
	}
}

type timeoutError struct{}

func (timeoutError) Error() string   { return "i/o timeout" }
func (timeoutError) Timeout() bool   { return true }
func (timeoutError) Temporary() bool { return true }
