package handlers

import (
	"crypto/tls"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
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

// The install script must install the V2 directory plugin by default and the
// single-file V1 plugin when version 1 is requested.
func TestInstallScriptSelectsPluginVersion(t *testing.T) {
	app := &App{Cfg: &config.Settings{}}
	app.Cfg.Server.BaseURL = "https://gw.example"

	c, w := newInstallCtx(t)
	c.Request = httptest.NewRequest(http.MethodGet, "/install.sh", nil)
	app.installScript(c)
	v2 := w.Body.String()
	for _, want := range []string{
		"fetch voidswitch.ts", "fetch voidswitch-rpc.ts", "fetch voidswitch-tui.ts",
	} {
		if !strings.Contains(v2, want) {
			t.Fatalf("v2 script should install all three parts (missing %q):\n%s", want, v2)
		}
	}
	if strings.Contains(v2, "voidswitch-v1.ts") {
		t.Fatalf("v2 script must not fetch the v1 source:\n%s", v2)
	}

	c1, w1 := newInstallCtx(t)
	c1.Request = httptest.NewRequest(http.MethodGet, "/install.sh?v=1", nil)
	app.installScript(c1)
	v1 := w1.Body.String()
	if !strings.Contains(v1, "voidswitch-v1.ts") {
		t.Fatalf("v1 script should fetch voidswitch-v1.ts:\n%s", v1)
	}
	if strings.Contains(v1, "voidswitch-rpc.ts") {
		t.Fatalf("v1 script must not fetch the v2 parts:\n%s", v1)
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

// The two generations must resolve to different files, each containing its own
// entrypoint shape, and V2 must bundle all three directory-plugin parts.
func TestPluginSourcesDiffer(t *testing.T) {
	v2 := pluginSourcePath("v2", 0)
	v1 := pluginSourcePath("v1", 0)
	if v2 == "" || v1 == "" {
		t.Skipf("plugin sources not bundled in this build (v2=%q v1=%q)", v2, v1)
	}
	if v2 == v1 {
		t.Fatalf("v2 and v1 resolved to the same file: %s", v2)
	}
	for i, name := range []string{"index.ts", "rpc.ts", "tui.ts"} {
		path := pluginSourcePath("v2", i)
		if path == "" {
			t.Fatalf("v2 part %d (%s) is not bundled", i, name)
		}
		if filepath.Base(path) != name {
			t.Fatalf("v2 part %d resolved to %s, want %s", i, path, name)
		}
	}
}

// requestBaseURL must prefer proxy headers, then the request Host, and fall
// back to the configured BaseURL — so an installer fetched from a given host
// bakes that host in.
func TestRequestBaseURL(t *testing.T) {
	app := &App{Cfg: &config.Settings{}}
	app.Cfg.Server.BaseURL = "https://gw.example"
	fallback := strings.TrimRight(app.Cfg.Server.BaseURL, "/")

	c, _ := newInstallCtx(t)
	c.Request = httptest.NewRequest(http.MethodGet, "/install.sh", nil)
	c.Request.Header.Set("X-Forwarded-Proto", "https")
	c.Request.Header.Set("X-Forwarded-Host", "proxy.example")
	if got := requestBaseURL(c, fallback); got != "https://proxy.example" {
		t.Fatalf("proxy headers: got %q", got)
	}

	c, _ = newInstallCtx(t)
	c.Request = httptest.NewRequest(http.MethodGet, "/install.sh", nil)
	c.Request.Host = "localhost:7292"
	if got := requestBaseURL(c, fallback); got != "http://localhost:7292" {
		t.Fatalf("request host: got %q", got)
	}

	c, _ = newInstallCtx(t)
	c.Request = httptest.NewRequest(http.MethodGet, "/install.sh", nil)
	c.Request.TLS = new(tls.ConnectionState)
	if got := requestBaseURL(c, fallback); got != "https://"+c.Request.Host {
		t.Fatalf("direct TLS: got %q", got)
	}

	c, _ = newInstallCtx(t)
	if got := requestBaseURL(c, fallback); got != fallback {
		t.Fatalf("no request: got %q, want %q", got, fallback)
	}

	// Client-controlled headers must never reach the generated output: bad
	// schemes and hosts fall back to the configured BaseURL.
	for _, proto := range []string{"javascript:", "ftp", "http;evil"} {
		c, _ = newInstallCtx(t)
		c.Request = httptest.NewRequest(http.MethodGet, "/install.sh", nil)
		c.Request.Header.Set("X-Forwarded-Proto", proto)
		if got := requestBaseURL(c, fallback); got != fallback {
			t.Fatalf("proto %q: got %q, want fallback", proto, got)
		}
	}
	for _, host := range []string{"evil$(id)", "a b", "[not-ipv6]", "evil;id"} {
		c, _ = newInstallCtx(t)
		c.Request = httptest.NewRequest(http.MethodGet, "/install.sh", nil)
		c.Request.Header.Set("X-Forwarded-Proto", "https")
		c.Request.Header.Set("X-Forwarded-Host", host)
		if got := requestBaseURL(c, fallback); got != fallback {
			t.Fatalf("host %q: got %q, want fallback", host, got)
		}
	}

	// Bracketed IPv6 literals and multi-proxy chains stay valid.
	c, _ = newInstallCtx(t)
	c.Request = httptest.NewRequest(http.MethodGet, "/install.sh", nil)
	c.Request.Header.Set("X-Forwarded-Proto", "https, http")
	c.Request.Header.Set("X-Forwarded-Host", "[fe80::1]:8080")
	if got := requestBaseURL(c, fallback); got != "https://[fe80::1]:8080" {
		t.Fatalf("ipv6 multi-hop: got %q", got)
	}
}

// The generated installers must carry the bake step and default GATEWAY to the
// host the request came in on.
func TestInstallersBakeGateway(t *testing.T) {
	app := &App{Cfg: &config.Settings{}}
	app.Cfg.Server.BaseURL = "https://gw.example"

	c, w := newInstallCtx(t)
	c.Request = httptest.NewRequest(http.MethodGet, "/install.sh", nil)
	c.Request.Host = "gw.selfhosted:7292"
	app.installScript(c)
	sh := w.Body.String()
	if !strings.Contains(sh, `GATEWAY="${VOIDSWITCH_GATEWAY:-http://gw.selfhosted:7292}"`) {
		t.Fatalf("sh must default GATEWAY to the request host:\n%s", sh)
	}
	for _, want := range []string{"GATEWAY_ESC", "INSTALL_GATEWAY", "voidswitch-install-host"} {
		if !strings.Contains(sh, want) {
			t.Fatalf("sh must bake the gateway (missing %q):\n%s", want, sh)
		}
	}
	// The V2 layout installs the three directory-plugin parts and moves a
	// leftover single-file install aside (it would load the server part twice).
	for _, want := range []string{
		`fetch voidswitch-rpc.ts "$SUB/rpc.ts"`,
		`fetch voidswitch-tui.ts "$SUB/tui.ts"`,
		`mv -f "$DIR/voidswitch.ts" "$DIR/voidswitch.ts.bak"`,
	} {
		if !strings.Contains(sh, want) {
			t.Fatalf("sh must install the directory layout (missing %q):\n%s", want, sh)
		}
	}

	c, w = newInstallCtx(t)
	c.Request = httptest.NewRequest(http.MethodGet, "/install.sh?v=1", nil)
	c.Request.Host = "gw.selfhosted:7292"
	app.installScript(c)
	v1sh := w.Body.String()
	if !strings.Contains(v1sh, `voidswitch.plugin.ts`) {
		t.Fatalf("v1 script must target the .plugin.ts destination:\n%s", v1sh)
	}
	if strings.Contains(v1sh, "voidswitch-rpc.ts") {
		t.Fatalf("v1 script must not fetch v2 parts:\n%s", v1sh)
	}
	// The V1 branch must bake the gateway into the single file the same way.
	for _, want := range []string{"GATEWAY_ESC", "voidswitch-install-host"} {
		if !strings.Contains(v1sh, want) {
			t.Fatalf("v1 script must bake the gateway (missing %q):\n%s", want, v1sh)
		}
	}

	c, w = newInstallCtx(t)
	c.Request = httptest.NewRequest(http.MethodGet, "/install.ps1", nil)
	app.installPowerShell(c)
	ps := w.Body.String()
	for _, want := range []string{"INSTALL_GATEWAY", "voidswitch-install-host", "UTF8Encoding", "voidswitch-rpc.ts"} {
		if !strings.Contains(ps, want) {
			t.Fatalf("ps1 must install the directory layout (missing %q):\n%s", want, ps)
		}
	}

	c, w = newInstallCtx(t)
	c.Request = httptest.NewRequest(http.MethodGet, "/install.ps1?v=1", nil)
	app.installPowerShell(c)
	v1ps := w.Body.String()
	if !strings.Contains(v1ps, "voidswitch.plugin.ts") {
		t.Fatalf("v1 ps1 must target the .plugin.ts destination:\n%s", v1ps)
	}
	for _, want := range []string{"INSTALL_GATEWAY", "voidswitch-install-host", "UTF8Encoding"} {
		if !strings.Contains(v1ps, want) {
			t.Fatalf("v1 ps1 must bake the gateway (missing %q):\n%s", want, v1ps)
		}
	}
}

// The bake step must survive gateways containing sed metacharacters (&, #, \):
// the escaped value must round-trip to the raw URL in the baked const. Both
// the V2 and V1 install branches bake, into their respective destinations.
func TestInstallScriptBakeEscaping(t *testing.T) {
	if _, err := exec.LookPath("sh"); err != nil {
		t.Skip("sh not available")
	}
	for _, tc := range []struct {
		name, query, dirVar, plugin string
	}{
		{name: "v2", query: "", dirVar: "SUB", plugin: "index.ts"},
		{name: "v1", query: "?v=1", dirVar: "DIR", plugin: "voidswitch.plugin.ts"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			app := &App{Cfg: &config.Settings{}}
			c, w := newInstallCtx(t)
			c.Request = httptest.NewRequest(http.MethodGet, "/install.sh"+tc.query, nil)
			app.installScript(c)

			var escLine, sedLine string
			for _, line := range strings.Split(w.Body.String(), "\n") {
				if strings.HasPrefix(line, "GATEWAY_ESC=") {
					escLine = line
				}
				if strings.Contains(line, "s#.*voidswitch-install-host.*#") {
					sedLine = line
				}
			}
			if escLine == "" || sedLine == "" {
				t.Fatalf("bake lines missing from the generated script:\n%s", w.Body.String())
			}

			wd := t.TempDir()
			if err := os.WriteFile(filepath.Join(wd, tc.plugin),
				[]byte("const INSTALL_GATEWAY = \"\"; // @voidswitch-install-host\n"), 0o644); err != nil {
				t.Fatal(err)
			}
			gateway := "http://127.0.0.1:1/x?a=1&b=2#f"
			runner := "#!/bin/sh\n" +
				"GATEWAY=" + strconv.Quote(gateway) + "\n" +
				escLine + "\n" +
				tc.dirVar + "=" + strconv.Quote(wd) + "\n" +
				sedLine + "\n" +
				"cat \"$" + tc.dirVar + "/" + tc.plugin + "\"\n"
			script := filepath.Join(t.TempDir(), "bake.sh")
			if err := os.WriteFile(script, []byte(runner), 0o755); err != nil {
				t.Fatal(err)
			}
			out, err := exec.Command("sh", script).CombinedOutput()
			if err != nil {
				t.Fatalf("bake failed: %v\n%s", err, out)
			}
			want := `const INSTALL_GATEWAY = "` + gateway + `"; // @voidswitch-install-host`
			if !strings.Contains(string(out), want) {
				t.Fatalf("marker not baked to the raw gateway %q:\n%s", want, string(out))
			}
		})
	}
}

// runInstallScriptE2E generates the installer for query, serves the plugin
// sources from a stub server, runs it for real, and returns the HOME it used
// plus the installed file's bytes. preRun (optional) runs after the plugins
// directory exists but before the script, so callers can seed files.
func runInstallScriptE2E(
	t *testing.T,
	query string,
	routes map[string]string,
	destRel string,
	preRun func(t *testing.T, pluginsDir string),
) (string, []byte) {
	t.Helper()
	if _, err := exec.LookPath("sh"); err != nil {
		t.Skip("sh not available")
	}
	for route, src := range routes {
		if src == "" {
			t.Skipf("plugin source not bundled in this build: %s", route)
		}
	}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		src, ok := routes[r.URL.Path]
		if !ok {
			http.Error(w, "unexpected route "+r.URL.Path, http.StatusNotFound)
			return
		}
		data, err := os.ReadFile(src)
		if err != nil {
			http.Error(w, err.Error(), http.StatusNotFound)
			return
		}
		_, _ = w.Write(data)
	}))
	defer srv.Close()

	app := &App{Cfg: &config.Settings{}}
	c, w := newInstallCtx(t)
	c.Request = httptest.NewRequest(http.MethodGet, "/install.sh"+query, nil)
	app.installScript(c)

	home := t.TempDir()
	script := filepath.Join(t.TempDir(), "install.sh")
	if err := os.WriteFile(script, []byte(w.Body.String()), 0o755); err != nil {
		t.Fatal(err)
	}
	pluginsDir := filepath.Join(home, ".config", "opencode", "plugins")
	if err := os.MkdirAll(pluginsDir, 0o755); err != nil {
		t.Fatal(err)
	}
	if preRun != nil {
		preRun(t, pluginsDir)
	}
	cmd := exec.Command("sh", script)
	cmd.Env = append(os.Environ(),
		"VOIDSWITCH_GATEWAY="+srv.URL,
		"HOME="+home,
		"XDG_CONFIG_HOME=",
	)
	if out, err := cmd.CombinedOutput(); err != nil {
		t.Fatalf("script failed: %v\n%s", err, out)
	}
	installed, err := os.ReadFile(filepath.Join(pluginsDir, destRel))
	if err != nil {
		t.Fatal(err)
	}
	// The gateway must be baked into the installed file, marker intact.
	want := `const INSTALL_GATEWAY = "` + srv.URL + `"; // @voidswitch-install-host`
	if !strings.Contains(string(installed), want) {
		t.Fatalf("marker not baked to %q:\n%s", want, string(installed))
	}
	if strings.Count(string(installed), "voidswitch-install-host") != 1 {
		t.Fatalf("marker must stay unique:\n%s", string(installed))
	}
	return home, installed
}

// Running the generated script must leave the installed directory plugin with
// all three parts, the gateway baked into the server part's marker line, and
// the legacy single file moved aside.
func TestInstallScriptEndToEnd(t *testing.T) {
	home, _ := runInstallScriptE2E(t, "", map[string]string{
		"/opencode/voidswitch.ts":     pluginSourcePath("v2", 0),
		"/opencode/voidswitch-rpc.ts": pluginSourcePath("v2", 1),
		"/opencode/voidswitch-tui.ts": pluginSourcePath("v2", 2),
	}, filepath.Join("voidswitch", "index.ts"),
		func(t *testing.T, pluginsDir string) {
			// A leftover single-file install must be moved aside by the script.
			if err := os.WriteFile(filepath.Join(pluginsDir, "voidswitch.ts"),
				[]byte("old"), 0o644); err != nil {
				t.Fatal(err)
			}
		})
	dir := filepath.Join(home, ".config", "opencode", "plugins")
	for _, name := range []string{"rpc.ts", "tui.ts"} {
		if _, err := os.Stat(filepath.Join(dir, "voidswitch", name)); err != nil {
			t.Fatalf("%s not installed: %v", name, err)
		}
	}
	legacy := filepath.Join(dir, "voidswitch.ts")
	if _, err := os.Stat(legacy); !os.IsNotExist(err) {
		t.Fatalf("legacy single file still present: %v", err)
	}
	if _, err := os.Stat(legacy + ".bak"); err != nil {
		t.Fatalf("legacy single file not preserved as .bak: %v", err)
	}
}

// The V1 branch must install the single file with the gateway baked in too.
func TestInstallScriptV1EndToEnd(t *testing.T) {
	_, _ = runInstallScriptE2E(t, "?v=1", map[string]string{
		"/opencode/voidswitch-v1.ts": pluginSourcePath("v1", 0),
	}, filepath.Join("voidswitch.plugin.ts"), nil)
}
