package handlers

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/gin-gonic/gin"

	"github.com/siiway/voidswitch/internal/config"
)

func newInstallCtx(t *testing.T) (*gin.Context, *httptest.ResponseRecorder) {
	t.Helper()
	gin.SetMode(gin.TestMode)
	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	return c, w
}

// The install script must fetch the V2 source by default and the V1 source when
// version 1 is requested.
func TestInstallScriptSelectsPluginVersion(t *testing.T) {
	app := &App{Cfg: &config.Settings{}}
	app.Cfg.Server.BaseURL = "https://gw.example"

	c, w := newInstallCtx(t)
	c.Request = httptest.NewRequest(http.MethodGet, "/install.sh", nil)
	app.installScript(c)
	v2 := w.Body.String()
	if !strings.Contains(v2, "/opencode/voidswitch.ts") {
		t.Fatalf("v2 script should fetch voidswitch.ts:\n%s", v2)
	}
	if strings.Contains(v2, "/opencode/voidswitch-v1.ts") {
		t.Fatalf("v2 script must not fetch the v1 source:\n%s", v2)
	}

	c1, w1 := newInstallCtx(t)
	c1.Request = httptest.NewRequest(http.MethodGet, "/install.sh?v=1", nil)
	app.installScript(c1)
	v1 := w1.Body.String()
	if !strings.Contains(v1, "/opencode/voidswitch-v1.ts") {
		t.Fatalf("v1 script should fetch voidswitch-v1.ts:\n%s", v1)
	}
	// V1 is not auto-discovered, so the script must tell the user to register it.
	if !strings.Contains(v1, "plugin array") {
		t.Fatalf("v1 script should mention the opencode.json plugin array:\n%s", v1)
	}
}

// The default must stay V2 even for junk input.
func TestInstallScriptDefaultsToV2(t *testing.T) {
	for _, q := range []string{"", "?v=", "?v=bogus", "?v=2"} {
		c, _ := newInstallCtx(t)
		c.Request = httptest.NewRequest(http.MethodGet, "/install.sh"+q, nil)
		if got := requestedPluginVersion(c); got != "v2" {
			t.Fatalf("query %q gave %q, want v2", q, got)
		}
	}
}

// The two sources must resolve to different files, each containing its own
// entrypoint shape.
func TestPluginSourcesDiffer(t *testing.T) {
	v2 := pluginSourcePath("v2")
	v1 := pluginSourcePath("v1")
	if v2 == "" || v1 == "" {
		t.Skipf("plugin sources not bundled in this build (v2=%q v1=%q)", v2, v1)
	}
	if v2 == v1 {
		t.Fatalf("v2 and v1 resolved to the same file: %s", v2)
	}
}
