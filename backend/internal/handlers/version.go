package handlers

import (
	"os"
	"os/exec"
	"strings"
)

// Version is the build version (dev format, e.g. v0.3.0-2026.11.7.1). It is set
// via -ldflags at build time; a sensible default keeps dev runs informative.
var Version = "0.3.0-2026.11.8.5"

// CommitID resolves the short git hash (VOIDSWITCH_COMMIT or git rev-parse).
func CommitID() string {
	if v := strings.TrimSpace(os.Getenv("VOIDSWITCH_COMMIT")); v != "" {
		return v
	}
	out, err := exec.Command("git", "rev-parse", "--short=7", "HEAD").Output()
	if err != nil {
		return ""
	}
	return strings.TrimSpace(string(out))
}
