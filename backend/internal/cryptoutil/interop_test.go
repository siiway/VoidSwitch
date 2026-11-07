package cryptoutil

import (
	"os"
	"testing"
)

// TestInteropPython verifies that tokens produced by the Python backend's
// `cryptography.fernet` decrypt here, and vice versa. It runs only when the
// caller exports PY_CT with a Fernet token for `interop-secret-abc`; the
// generation script lives in scripts/gen-fernet-fixture.py so this stays
// self-contained in CI without a Python dependency.
func TestInteropPython(t *testing.T) {
	pyCT := os.Getenv("PY_CT")
	if pyCT == "" {
		t.Skip("PY_CT not set; run scripts/fernet-interop.sh to exercise")
	}
	const secret = "interop-secret-abc"
	pt, err := DecryptSecret(pyCT, secret)
	if err != nil {
		t.Fatalf("decrypt python Fernet token: %v", err)
	}
	if pt != "hello-interop" {
		t.Fatalf("got %q, want hello-interop", pt)
	}
}
