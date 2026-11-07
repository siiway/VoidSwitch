package cryptoutil

import "testing"

func TestRoundTrip(t *testing.T) {
	for _, secret := range []string{"sec1", "a-very-long-secret-1234567890"} {
		ct, err := EncryptSecret("sk-hello-world-key", secret)
		if err != nil { t.Fatal(err) }
		if len(ct) < 6 || ct[:6] != "gAAAAA" { t.Fatalf("bad magic: %s", ct) }
		pt, err := DecryptSecret(ct, secret)
		if err != nil { t.Fatal(err) }
		if pt != "sk-hello-world-key" { t.Fatalf("got %q", pt) }
	}
	// plaintext passthrough
	if got, _ := DecryptSecret("plain-key", "x"); got != "plain-key" { t.Fatal("passthrough") }
}
