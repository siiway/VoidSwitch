package handlers

import (
	"html"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"strings"

	"github.com/gin-gonic/gin"
)

// pluginSources maps a plugin generation to its entry files, in load order
// (server part first). The files are resolved by walking up from the working
// directory, so the handler works both from a repo checkout (backend/, repo
// root, or a test's package dir) and from the container layout (/app with
// /app/opencode-plugin* beside it). V2 ships as a directory plugin: the
// installer drops server + rpc + tui into ~/.config/opencode/plugins/voidswitch/.
var pluginSources = map[string][]string{
	// V2 targets OpenCode 2.x and the @opencode/plugin SDK.
	"v2": {
		"opencode-plugin/src/index.ts",
		"opencode-plugin/src/rpc.ts",
		"opencode-plugin/src/tui.ts",
	},
	// V1 targets OpenCode 1.x and @opencode-ai/plugin; kept for existing installs.
	"v1": {"opencode-plugin-v1/src/index.ts"},
}

// maxRepoSearchDepth bounds the upward walk from the working directory.
const maxRepoSearchDepth = 6

// pluginSourcePath resolves a plugin entry file for a generation ("v2"/"v1");
// part indexes into that generation's file list (0 = server part). It returns
// "" when the generation or part is not bundled in this build.
func pluginSourcePath(version string, part int) string {
	files, ok := pluginSources[version]
	if !ok || part < 0 || part >= len(files) {
		return ""
	}
	rel := files[part]
	dir, err := os.Getwd()
	if err != nil {
		return ""
	}
	for i := 0; i <= maxRepoSearchDepth; i++ {
		candidate := filepath.Join(dir, rel)
		if _, statErr := os.Stat(candidate); statErr == nil {
			abs, _ := filepath.Abs(candidate)
			return abs
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			break
		}
		dir = parent
	}
	return ""
}

// requestedPluginVersion reads the `v` query parameter (or VOIDSWITCH_PLUGIN_V)
// and normalises it. The dedicated `/opencode/voidswitch-v1.ts` route implies V1
// without needing the parameter, so a plain `curl` of that URL gets V1 source.
// The RPC and TUI routes always serve V2 parts — a `?v=1` there must not turn
// into a confusing V1 lookup. Anything unrecognised falls back to V2, the
// recommended generation.
func requestedPluginVersion(c *gin.Context) string {
	path := c.Request.URL.Path
	if strings.Contains(path, "voidswitch-rpc") ||
		strings.Contains(path, "voidswitch-tui") {
		return "v2"
	}
	v := c.Query("v")
	if v == "" && strings.Contains(c.Request.URL.Path, "voidswitch-v1") {
		v = "1"
	}
	if v == "" {
		v = os.Getenv("VOIDSWITCH_PLUGIN_V")
	}
	if v == "1" || strings.EqualFold(v, "v1") {
		return "v1"
	}
	return "v2"
}

// requestedPluginPart maps a plugin source URL to the index within its
// generation's file list (0 = server part).
func requestedPluginPart(path string) int {
	switch {
	case strings.Contains(path, "voidswitch-rpc"):
		return 1
	case strings.Contains(path, "voidswitch-tui"):
		return 2
	default:
		return 0
	}
}

// hostPattern constrains the Host / X-Forwarded-Host values echoed into the
// generated installers: a DNS name or a bracketed IPv6 literal, optionally
// with a port. Header values are client-controlled and end up inside generated
// shell scripts, so anything else (shell or header syntax) falls back to the
// configured BaseURL instead of being baked into the output.
var hostPattern = regexp.MustCompile(
	`^(?:[A-Za-z0-9](?:[A-Za-z0-9.\-]*[A-Za-z0-9])?|\[[0-9A-Fa-f:.]+\])(?::\d+)?$`,
)

// requestBaseURL derives the origin the client actually used to reach this
// server, preferring proxy headers over the configured BaseURL, so an installer
// fetched from a particular host bakes that host into the generated output.
func requestBaseURL(c *gin.Context, fallback string) string {
	if c.Request == nil {
		return fallback
	}
	// Multi-proxy chains append ("https, http"); the hop that reached this
	// server is the first entry.
	scheme := strings.TrimSpace(strings.Split(
		c.GetHeader("X-Forwarded-Proto"), ",")[0])
	if scheme == "" {
		scheme = "http"
		if c.Request.TLS != nil {
			scheme = "https"
		}
	}
	if !strings.EqualFold(scheme, "http") && !strings.EqualFold(scheme, "https") {
		return fallback
	}
	host := strings.TrimSpace(strings.Split(
		c.GetHeader("X-Forwarded-Host"), ",")[0])
	if host == "" {
		host = strings.TrimSpace(c.Request.Host)
	}
	if !hostPattern.MatchString(host) {
		return fallback
	}
	return scheme + "://" + host
}

// installScript serves the one-line installer for the OpenCode plugin.
//
// V2 is a directory plugin: the script drops the server, rpc and tui parts
// into `~/.config/opencode/plugins/voidswitch/`, where OpenCode discovers them
// automatically. V1 stays a single file referenced from the `plugin` array in
// opencode.json. Either way the script rewrites the plugin's install-time
// gateway marker to the host it was fetched from, so a self-hosted install
// points at its own gateway without extra configuration.
func (a *App) installScript(c *gin.Context) {
	gateway := requestBaseURL(c, strings.TrimRight(a.Cfg.Server.BaseURL, "/"))
	version := requestedPluginVersion(c)
	var body string
	if version == "v2" {
		// V2 is a directory plugin: the server, rpc and tui parts load together.
		// A leftover single-file install would load the server part twice, so it
		// is moved aside; the gateway is baked into the server part's
		// install-time marker (no-op on a source without the marker).
		body = "#!/bin/sh\n# VoidSwitch OpenCode plugin installer (v2)\n" +
			"set -e\nGATEWAY=\"${VOIDSWITCH_GATEWAY:-" + gateway + "}\"\n" +
			"DIR=\"${XDG_CONFIG_HOME:-$HOME/.config}/opencode/plugins\"\n" +
			"SUB=\"$DIR/voidswitch\"\n" +
			"mkdir -p \"$SUB\"\n" +
			"fetch() { if command -v curl >/dev/null 2>&1; then curl -fsSL \"$GATEWAY/opencode/$1\" -o \"$2\"; else wget -qO \"$2\" \"$GATEWAY/opencode/$1\"; fi; }\n" +
			"fetch voidswitch.ts \"$SUB/index.ts\"\n" +
			"fetch voidswitch-rpc.ts \"$SUB/rpc.ts\"\n" +
			"fetch voidswitch-tui.ts \"$SUB/tui.ts\"\n" +
			"if [ -f \"$DIR/voidswitch.ts\" ]; then mv -f \"$DIR/voidswitch.ts\" \"$DIR/voidswitch.ts.bak\"; fi\n" +
			"GATEWAY_ESC=$(printf '%s' \"$GATEWAY\" | sed \"s/[&\\\\#]/\\\\\\\\&/g\")\n" +
			"if grep -q 'voidswitch-install-host' \"$SUB/index.ts\"; then\n" +
			"  sed -i.bak \"s#.*voidswitch-install-host.*#const INSTALL_GATEWAY = \\\"$GATEWAY_ESC\\\"; // @voidswitch-install-host#\" \"$SUB/index.ts\"\n" +
			"  rm -f \"$SUB/index.ts.bak\"\nfi\n" +
			"echo \"Installed the VoidSwitch v2 plugin to $SUB (default gateway: $GATEWAY)\"\n" +
			"echo \"OpenCode loads it automatically from that directory — restart opencode.\"\n"
	} else {
		// V1 keeps the historical ".plugin.ts" name users already reference from
		// opencode.json.
		body = "#!/bin/sh\n# VoidSwitch OpenCode plugin installer (v1)\n" +
			"set -e\nGATEWAY=\"${VOIDSWITCH_GATEWAY:-" + gateway + "}\"\n" +
			"DIR=\"${XDG_CONFIG_HOME:-$HOME/.config}/opencode/plugins\"\n" +
			"mkdir -p \"$DIR\"\n" +
			"if command -v curl >/dev/null 2>&1; then\n" +
			"  curl -fsSL \"$GATEWAY/opencode/voidswitch-v1.ts\" -o \"$DIR/voidswitch.plugin.ts\"\n" +
			"else\n  wget -qO \"$DIR/voidswitch.plugin.ts\" \"$GATEWAY/opencode/voidswitch-v1.ts\"\nfi\n" +
			// Bake the gateway the same way the V2 branch does, so a self-hosted
			// V1 install points at its own gateway too.
			"GATEWAY_ESC=$(printf '%s' \"$GATEWAY\" | sed \"s/[&\\\\#]/\\\\\\\\&/g\")\n" +
			"if grep -q 'voidswitch-install-host' \"$DIR/voidswitch.plugin.ts\"; then\n" +
			"  sed -i.bak \"s#.*voidswitch-install-host.*#const INSTALL_GATEWAY = \\\"$GATEWAY_ESC\\\"; // @voidswitch-install-host#\" \"$DIR/voidswitch.plugin.ts\"\n" +
			"  rm -f \"$DIR/voidswitch.plugin.ts.bak\"\nfi\n" +
			"echo \"Installed the VoidSwitch v1 plugin to $DIR/voidswitch.plugin.ts (default gateway: $GATEWAY)\"\n" +
			"echo \"Add this to the top-level plugin array in opencode.json:\"\n" +
			"echo \"  $DIR/voidswitch.plugin.ts\"\n"
	}
	c.Header("Content-Type", "text/x-shellscript")
	c.Header("Cache-Control", "no-store")
	c.String(http.StatusOK, body)
}

func (a *App) installPowerShell(c *gin.Context) {
	gateway := requestBaseURL(c, strings.TrimRight(a.Cfg.Server.BaseURL, "/"))
	version := requestedPluginVersion(c)
	var body string
	if version == "v2" {
		body = "# VoidSwitch OpenCode plugin installer (v2, PowerShell)\n" +
			"$Gateway = if ($env:VOIDSWITCH_GATEWAY) { $env:VOIDSWITCH_GATEWAY } else { \"" + gateway + "\" }\n" +
			"$Dir = Join-Path $env:APPDATA \"opencode\\plugins\"\n" +
			"$Sub = Join-Path $Dir \"voidswitch\"\n" +
			"New-Item -ItemType Directory -Force -Path $Sub | Out-Null\n" +
			"Invoke-WebRequest -Uri \"$Gateway/opencode/voidswitch.ts\" -OutFile (Join-Path $Sub \"index.ts\")\n" +
			"Invoke-WebRequest -Uri \"$Gateway/opencode/voidswitch-rpc.ts\" -OutFile (Join-Path $Sub \"rpc.ts\")\n" +
			"Invoke-WebRequest -Uri \"$Gateway/opencode/voidswitch-tui.ts\" -OutFile (Join-Path $Sub \"tui.ts\")\n" +
			"$Legacy = Join-Path $Dir \"voidswitch.ts\"\n" +
			"if (Test-Path $Legacy) { Move-Item -Force $Legacy \"$Legacy.bak\" }\n" +
			"$File = Join-Path $Sub \"index.ts\"\n" +
			"$Text = [System.Text.Encoding]::UTF8.GetString([System.IO.File]::ReadAllBytes($File))\n" +
			"if ($Text -match 'voidswitch-install-host') {\n" +
			"  $Line = 'const INSTALL_GATEWAY = \"' + $Gateway.Replace('$', '$$') + '\"; // @voidswitch-install-host'\n" +
			"  $Text = $Text -replace '(?m)^[^\\r\\n]*voidswitch-install-host[^\\r\\n]*$', $Line\n" +
			"  [System.IO.File]::WriteAllText($File, $Text, [System.Text.UTF8Encoding]::new($false))\n" +
			"}\n" +
			"Write-Host \"Installed the VoidSwitch v2 plugin to $Sub (default gateway: $Gateway)\"\n" +
			"Write-Host \"OpenCode loads it automatically from that directory - restart opencode.\"\n"
	} else {
		body = "# VoidSwitch OpenCode plugin installer (v1, PowerShell)\n" +
			"$Gateway = if ($env:VOIDSWITCH_GATEWAY) { $env:VOIDSWITCH_GATEWAY } else { \"" + gateway + "\" }\n" +
			"$Dir = Join-Path $env:APPDATA \"opencode\\plugins\"\n" +
			"New-Item -ItemType Directory -Force -Path $Dir | Out-Null\n" +
			"$File = Join-Path $Dir \"voidswitch.plugin.ts\"\n" +
			"Invoke-WebRequest -Uri \"$Gateway/opencode/voidswitch-v1.ts\" -OutFile $File\n" +
			// Bake the gateway the same way the V2 branch does.
			"$Text = [System.Text.Encoding]::UTF8.GetString([System.IO.File]::ReadAllBytes($File))\n" +
			"if ($Text -match 'voidswitch-install-host') {\n" +
			"  $Line = 'const INSTALL_GATEWAY = \"' + $Gateway.Replace('$', '$$') + '\"; // @voidswitch-install-host'\n" +
			"  $Text = $Text -replace '(?m)^[^\\r\\n]*voidswitch-install-host[^\\r\\n]*$', $Line\n" +
			"  [System.IO.File]::WriteAllText($File, $Text, [System.Text.UTF8Encoding]::new($false))\n" +
			"}\n" +
			"Write-Host \"Installed the VoidSwitch v1 plugin to $File (default gateway: $Gateway)\"\n" +
			"Write-Host \"Add this to the top-level plugin array in opencode.json:\"\n" +
			"Write-Host \"  $File\"\n"
	}
	c.Header("Content-Type", "text/plain")
	c.Header("Cache-Control", "no-store")
	c.String(http.StatusOK, body)
}

// installPage serves the /install landing text.
func (a *App) installPage(c *gin.Context) {
	base := requestBaseURL(c, strings.TrimRight(a.Cfg.Server.BaseURL, "/"))
	c.Header("Cache-Control", "no-store")
	if strings.Contains(c.GetHeader("Accept"), "text/html") || c.Query("format") == "html" {
		// Escaped defensively: base comes from request headers even though
		// requestBaseURL validates them.
		c.Header("Content-Type", "text/html; charset=utf-8")
		escaped := html.EscapeString(base)
		c.String(http.StatusOK, "<p>Install the VoidSwitch OpenCode plugin (V2, for OpenCode 2.x):</p><pre>curl -fsSL "+escaped+"/install.sh | sh</pre>"+
			"<p>For OpenCode 1.x, install the V1 plugin instead:</p><pre>curl -fsSL \""+escaped+"/install.sh?v=1\" | sh</pre>")
		return
	}
	c.String(http.StatusOK, "VoidSwitch installer:\n"+
		"  V2 (OpenCode 2.x):  curl -fsSL "+base+"/install.sh | sh\n"+
		"  V1 (OpenCode 1.x):  curl -fsSL \""+base+"/install.sh?v=1\" | sh\n")
}

// pluginSource serves a plugin part's TypeScript source verbatim, so a
// self-hosted gateway always hands out the source matching its own release.
func (a *App) pluginSource(c *gin.Context) {
	version := requestedPluginVersion(c)
	path := pluginSourcePath(version, requestedPluginPart(c.Request.URL.Path))
	if path == "" {
		a.fail(c, http.StatusNotFound, "The "+version+" plugin source is not bundled in this build.")
		return
	}
	data, err := os.ReadFile(path)
	if err != nil {
		a.fail(c, http.StatusNotFound, "Plugin source unavailable.")
		return
	}
	c.Header("Content-Type", "text/plain; charset=utf-8")
	c.Data(http.StatusOK, "text/plain; charset=utf-8", data)
}

// pluginVersionInfo reports which plugin sources this build can serve, so the
// dashboard can hide an install tab the server cannot back.
func (a *App) pluginVersionInfo(c *gin.Context) {
	available := map[string]bool{}
	for v := range pluginSources {
		available[v] = pluginSourcePath(v, 0) != ""
	}
	c.JSON(http.StatusOK, gin.H{
		"v2": available["v2"],
		"v1": available["v1"],
	})
}

// RegisterInstallRoutes wires the public install/plugin endpoints.
func RegisterInstallRoutes(r *gin.Engine, a *App) {
	r.GET("/install", a.installPage)
	r.GET("/install.sh", a.installScript)
	r.GET("/install.ps1", a.installPowerShell)
	// The V2 directory plugin's three parts and the single-file V1 source.
	// The rpc/tui routes always serve V2 parts; `?v=1` selects V1 on the
	// server-part routes (`voidswitch.ts`) and the installers.
	r.GET("/opencode/voidswitch.ts", a.pluginSource)
	r.GET("/opencode/voidswitch-rpc.ts", a.pluginSource)
	r.GET("/opencode/voidswitch-tui.ts", a.pluginSource)
	r.GET("/opencode/voidswitch-v1.ts", a.pluginSource)
	r.GET("/opencode/plugin-versions", a.pluginVersionInfo)
}
