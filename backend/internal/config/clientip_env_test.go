package config

import (
	"os"
	"testing"
)

func TestClientIPHeaderEnv(t *testing.T) {
	os.Setenv("VOIDSWITCH_CLIENT_IP_HEADER", "CF-Connecting-IP")
	defer os.Unsetenv("VOIDSWITCH_CLIENT_IP_HEADER")
	ResetForTesting()
	s := Load()
	if s.Server.ClientIPHeader != "CF-Connecting-IP" {
		t.Fatalf("got %q", s.Server.ClientIPHeader)
	}
}
