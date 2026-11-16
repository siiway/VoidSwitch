package handlers

import "testing"

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
