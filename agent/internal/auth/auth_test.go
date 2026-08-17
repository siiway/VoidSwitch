package auth

import (
	"net/http/httptest"
	"testing"
)

func TestAuthorizedWithCorrectToken(t *testing.T) {
	v, err := New("s3cret", nil)
	if err != nil {
		t.Fatal(err)
	}
	r := httptest.NewRequest("POST", "/", nil)
	r.Header.Set("Authorization", "Bearer s3cret")
	if !v.Authorized(r) {
		t.Fatal("expected authorized with matching token")
	}
}

func TestAuthorizedRejectsWrongToken(t *testing.T) {
	v, _ := New("s3cret", nil)
	r := httptest.NewRequest("POST", "/", nil)
	r.Header.Set("Authorization", "Bearer wrong")
	if v.Authorized(r) {
		t.Fatal("expected unauthorized with wrong token")
	}
}

func TestAuthorizedRequiresBearer(t *testing.T) {
	v, _ := New("s3cret", nil)
	r := httptest.NewRequest("POST", "/", nil)
	r.Header.Set("Authorization", "s3cret") // missing "Bearer "
	if v.Authorized(r) {
		t.Fatal("expected unauthorized without Bearer scheme")
	}
}

func TestAllowlistBlocksOtherIp(t *testing.T) {
	v, err := New("s3cret", []string{"10.0.0.0/8"})
	if err != nil {
		t.Fatal(err)
	}
	// httptest requests have RemoteAddr 192.0.2.1:1234 by default.
	r := httptest.NewRequest("POST", "/", nil)
	r.Header.Set("Authorization", "Bearer s3cret")
	if v.Authorized(r) {
		t.Fatal("expected source IP outside allowlist to be rejected")
	}
}
