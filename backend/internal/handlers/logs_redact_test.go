package handlers

import (
	"testing"

	"github.com/siiway/voidswitch/internal/core"
	"github.com/siiway/voidswitch/internal/database"
)

// The export must drop credentials and local egress addresses anywhere they
// appear, while keeping the rest of the payload diagnosable.
func TestDownloadSafeRedactsCredentials(t *testing.T) {
	secrets := map[string]string{
		"http://user:pw@10.0.0.5:3128": "<REDACTED:proxy>",
		"10.0.0.5:3128":                "<REDACTED:proxy>",
	}
	payload := map[string]any{
		"id":            float64(7),
		"proxy_url":     "http://user:pw@10.0.0.5:3128",
		"local_address": "127.0.0.1:9",
		"key":           "vs-secret",
		"key_preview":   "vs-abcdefghij",
		"access_token":  "tok",
		"error":         "connect to 10.0.0.5:3128 timed out",
		"req_headers": map[string]any{
			"authorization": "Bearer abc123",
		},
		"req_body": map[string]any{"messages": []any{"hello"}},
	}

	got := downloadSafe(payload, true, secrets).(map[string]any)

	if got["key"] != nil || got["access_token"] != nil {
		t.Fatalf("credentials were not dropped: %v", got)
	}
	// A preview is already masked, so the export keeps it: it tells the reader
	// which key served the request without revealing the credential.
	if s, _ := got["key_preview"].(string); s != "vs-a***ghij" {
		t.Fatalf("key_preview = %q, want the masked preview kept", got["key_preview"])
	}
	if got["local_address"] != nil {
		t.Fatalf("local address was not dropped: %v", got["local_address"])
	}
	if s, _ := got["proxy_url"].(string); s != "http://10.0.0.5:3128" {
		t.Fatalf("proxy_url = %q, want it redacted to the bare host", got["proxy_url"])
	}
	if err, _ := got["error"].(string); err != "connect to <REDACTED:proxy> timed out" {
		t.Fatalf("error text not scrubbed: %q", err)
	}
	if got["id"] != float64(7) {
		t.Fatalf("non-sensitive scalar was altered: %v", got["id"])
	}
}

// Non-owners must not receive request/response bodies.
func TestDownloadSafeOmitsBodiesForNonOwner(t *testing.T) {
	payload := map[string]any{
		"req_body":  map[string]any{"secret": "x"},
		"resp_body": "stream data",
		"model":     "claude-opus-4-8",
	}
	got := downloadSafe(payload, false, nil).(map[string]any)
	if got["req_body"] != nil || got["resp_body"] != nil {
		t.Fatalf("bodies leaked to a non-owner: %v", got)
	}
	if got["model"] != "claude-opus-4-8" {
		t.Fatalf("metadata was dropped: %v", got["model"])
	}

	// An owner keeps them.
	got = downloadSafe(payload, true, nil).(map[string]any)
	if got["resp_body"] != "stream data" {
		t.Fatalf("owner lost the response body: %v", got["resp_body"])
	}
}

// URL userinfo is stripped even when no known secret matches, so a proxy URL
// embedded in free text cannot leak credentials.
func TestScrubSecretsStripsUserinfo(t *testing.T) {
	got := scrubSecrets("via http://admin:hunter2@proxy.internal:8080 failed", nil)
	want := "via http://proxy.internal:8080 failed"
	if got != want {
		t.Fatalf("got %q, want %q", got, want)
	}
}

// Staff may see per-attempt headers but never bodies; stripAttemptBodies nulls
// bodies at any depth while leaving the headers intact.
func TestStripAttemptBodies(t *testing.T) {
	in := []any{
		map[string]any{
			"attempt":     float64(1),
			"req_headers": map[string]any{"content-type": "application/json"},
			"req_body":    map[string]any{"messages": []any{"hi"}},
			"resp_body":   "data: hello\n\n",
			"error":       "upstream 500",
		},
	}
	out := stripAttemptBodies(in).([]any)
	m := out[0].(map[string]any)
	if m["req_body"] != nil || m["resp_body"] != nil {
		t.Fatalf("bodies were not stripped: %v", m)
	}
	if m["req_headers"] == nil {
		t.Fatal("headers were stripped too")
	}
	if m["error"] != "upstream 500" {
		t.Fatalf("chain detail was dropped: %v", m)
	}
}

// The always-visible chain must not reveal the egress address, even inside a
// nested per-attempt array; route_type is published in its place.
func TestRedactAttemptSummariesNested(t *testing.T) {
	in := map[string]any{
		"attempts": []any{
			map[string]any{
				"proxy_url":      "http://user:pw@10.0.0.5:3128",
				"upstream_model": "m",
				"network_attempts": []any{
					map[string]any{"local_address": "127.0.0.1:9", "attempt": float64(1)},
				},
			},
		},
	}
	out := redactAttemptSummaries(in).(map[string]any)
	attempt := out["attempts"].([]any)[0].(map[string]any)
	if attempt["proxy_url"] != nil {
		t.Fatalf("proxy_url leaked: %v", attempt)
	}
	if attempt["route_type"] != "proxy" {
		t.Fatalf("route_type = %v, want proxy", attempt["route_type"])
	}
	if attempt["upstream_model"] != "m" {
		t.Fatalf("chain detail was dropped: %v", attempt)
	}
	net := attempt["network_attempts"].([]any)[0].(map[string]any)
	if net["local_address"] != nil || net["route_type"] != "local" {
		t.Fatalf("nested local address not redacted: %v", net)
	}
}

// A member's own chain stays anonymous: the provider key identifies which
// credential pool served the request, an operator concern.
func TestStripAttemptKeys(t *testing.T) {
	in := []any{map[string]any{
		"key_preview":    "sk-…test",
		"key_id":         float64(3),
		"upstream_model": "m",
	}}
	out := stripAttemptKeys(in).([]any)[0].(map[string]any)
	if out["key_preview"] != nil || out["key_id"] != nil {
		t.Fatalf("key identifiers not stripped: %v", out)
	}
	if out["upstream_model"] != "m" {
		t.Fatalf("chain detail was dropped: %v", out)
	}
}

// The download export collapses both projections into one `attempts` array and
// never carries bodies for a non-owner.
func TestExportPayloadUsesAttemptsArray(t *testing.T) {
	v := &requestLogDetailView{
		requestLogView:  requestLogView{ID: 1},
		AttemptsSummary: []any{map[string]any{"attempt": float64(1)}},
		DebugAttempts:   []any{map[string]any{"attempt": float64(1), "req_body": map[string]any{"x": float64(1)}}},
	}
	a := &App{}

	member := a.exportPayload(v, &core.UserView{Role: "member"}, &database.RequestLog{}).(map[string]any)
	if _, ok := member["attempts_summary"]; ok {
		t.Fatal("export kept attempts_summary")
	}
	if _, ok := member["debug_attempts"]; ok {
		t.Fatal("export kept debug_attempts")
	}
	attempts, ok := member["attempts"].([]any)
	if !ok || len(attempts) != 1 {
		t.Fatalf("export attempts = %v", member["attempts"])
	}
	if m := attempts[0].(map[string]any); m["req_body"] != nil {
		t.Fatalf("member export leaked a body: %v", m)
	}

	owner := a.exportPayload(v, &core.UserView{Role: "owner"}, &database.RequestLog{}).(map[string]any)
	ownerAttempts, _ := owner["attempts"].([]any)
	if len(ownerAttempts) != 1 {
		t.Fatalf("owner attempts = %v", owner["attempts"])
	}
	if m := ownerAttempts[0].(map[string]any); m["req_body"] == nil {
		t.Fatalf("owner export lost the body: %v", m)
	}
}
