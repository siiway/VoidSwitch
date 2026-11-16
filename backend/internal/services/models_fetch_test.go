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
