package providers

import (
	"strings"
	"testing"

	"github.com/siiway/voidswitch/internal/database"
)

// TestCloudflareURLUsesAccountFromKey covers the ordering bug that made every
// Cloudflare request 404: the dispatcher builds the URL before the headers, so
// the account id cannot be learned inside Headers.
func TestCloudflareURLUsesAccountFromKey(t *testing.T) {
	p := NewCloudflareProvider(&database.Provider{BaseURL: ""})
	got := p.UpstreamURLFor("acct123@token456")
	want := "https://api.cloudflare.com/client/v4/accounts/acct123/ai/v1/chat/completions"
	if got != want {
		t.Fatalf("upstream URL = %q, want %q", got, want)
	}
	if strings.Contains(got, "{account_id}") {
		t.Fatal("account id placeholder survived")
	}
}

// TestCloudflareURLHonoursCustomBase keeps an operator-supplied template working.
func TestCloudflareURLHonoursCustomBase(t *testing.T) {
	p := NewCloudflareProvider(&database.Provider{
		BaseURL: "https://example.test/accounts/{account_id}/ai/v1",
	})
	got := p.UpstreamURLFor("acct@token")
	if got != "https://example.test/accounts/acct/ai/v1/chat/completions" {
		t.Fatalf("upstream URL = %q", got)
	}
}

// TestCloudflarePlainKeyKeepsTemplate documents the fallback: a key without the
// composite account prefix leaves the template in place rather than inventing one.
func TestCloudflarePlainKeyKeepsTemplate(t *testing.T) {
	p := NewCloudflareProvider(&database.Provider{BaseURL: ""})
	if got := p.UpstreamURLFor("token-only"); !strings.Contains(got, "{account_id}") {
		t.Fatalf("URL = %q, want the unresolved template", got)
	}
}
