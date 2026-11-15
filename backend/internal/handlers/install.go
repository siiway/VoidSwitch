package handlers

import (
	"net/http"
	"os"
	"path/filepath"
	"strings"

	"github.com/gin-gonic/gin"
)

// pluginSources maps a plugin generation to its entry file name. The file is
// resolved by walking up from the working directory, so the handler works both
// from a repo checkout (backend/, repo root, or a test's package dir) and from
// the container layout (/app with /app/opencode-plugin* beside it).
var pluginSources = map[string]string{
	// V2 targets OpenCode 2.x and the @opencode/plugin SDK.
	"v2": "opencode-plugin/src/index.ts",
	// V1 targets OpenCode 1.x and @opencode-ai/plugin; kept for existing installs.
	"v1": "opencode-plugin-v1/src/index.ts",
}

// maxRepoSearchDepth bounds the upward walk from the working directory.
const maxRepoSearchDepth = 6

// pluginSourcePath resolves the plugin entry file for a generation ("v2"/"v1").
// It returns "" when that generation is not bundled in this build.
func pluginSourcePath(version string) string {
	rel, ok := pluginSources[version]
	if !ok {
		return ""
	}
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
// Anything unrecognised falls back to V2, the recommended generation.
func requestedPluginVersion(c *gin.Context) string {
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

// installSnippet serves the one-line installer for the OpenCode plugin.
//
// V2 plugins are plain `.ts` files discovered from `~/.config/opencode/plugins/`,
// so the script only has to drop the file there. V1 plugins are referenced from
// the `plugin` array in opencode.json, so that path is printed for the user.
func (a *App) installScript(c *gin.Context) {
	gateway := strings.TrimRight(a.Cfg.Server.BaseURL, "/")
	version := requestedPluginVersion(c)
	// V2 is auto-discovered under its own name; V1 keeps the historical
	// ".plugin.ts" name users already reference from opencode.json.
	remote, dest := "voidswitch.ts", "voidswitch.ts"
	if version == "v1" {
		remote, dest = "voidswitch-v1.ts", "voidswitch.plugin.ts"
	}
	body := "#!/bin/sh\n# VoidSwitch OpenCode plugin installer (" + version + ")\n" +
		"set -e\nGATEWAY=\"${VOIDSWITCH_GATEWAY:-" + gateway + "}\"\n" +
		"DIR=\"${XDG_CONFIG_HOME:-$HOME/.config}/opencode/plugins\"\n" +
		"mkdir -p \"$DIR\"\n" +
		"if command -v curl >/dev/null 2>&1; then\n" +
		"  curl -fsSL \"$GATEWAY/opencode/" + remote + "\" -o \"$DIR/" + dest + "\"\n" +
		"else\n  wget -qO \"$DIR/" + dest + "\" \"$GATEWAY/opencode/" + remote + "\"\nfi\n" +
		"echo \"Installed the VoidSwitch " + version + " plugin to $DIR/" + dest + "\"\n"
	if version == "v1" {
		body += "echo \"Add this to the top-level plugin array in opencode.json:\"\n" +
			"echo \"  $DIR/" + dest + "\"\n"
	} else {
		body += "echo \"OpenCode loads it automatically from that directory — restart opencode.\"\n"
	}
	c.Header("Content-Type", "text/x-shellscript")
	c.String(http.StatusOK, body)
}

func (a *App) installPowerShell(c *gin.Context) {
	gateway := strings.TrimRight(a.Cfg.Server.BaseURL, "/")
	version := requestedPluginVersion(c)
	file := "voidswitch.ts"
	dest := "voidswitch.ts"
	if version == "v1" {
		file = "voidswitch-v1.ts"
		dest = "voidswitch.plugin.ts"
	}
	body := "# VoidSwitch OpenCode plugin installer (" + version + ", PowerShell)\n" +
		"$Gateway = if ($env:VOIDSWITCH_GATEWAY) { $env:VOIDSWITCH_GATEWAY } else { \"" + gateway + "\" }\n" +
		"$Dir = Join-Path $env:APPDATA \"opencode\\plugins\"\n" +
		"New-Item -ItemType Directory -Force -Path $Dir | Out-Null\n" +
		"Invoke-WebRequest -Uri \"$Gateway/opencode/" + file + "\" -OutFile (Join-Path $Dir \"" + dest + "\")\n" +
		"Write-Host \"Installed the VoidSwitch " + version + " plugin to $Dir\\" + dest + "\"\n"
	if version == "v1" {
		body += "Write-Host \"Add this to the top-level plugin array in opencode.json:\"\n" +
			"Write-Host \"  $Dir\\" + dest + "\"\n"
	} else {
		body += "Write-Host \"OpenCode loads it automatically from that directory - restart opencode.\"\n"
	}
	c.Header("Content-Type", "text/plain")
	c.String(http.StatusOK, body)
}

// installPage serves the /install landing text.
func (a *App) installPage(c *gin.Context) {
	base := strings.TrimRight(a.Cfg.Server.BaseURL, "/")
	if strings.Contains(c.GetHeader("Accept"), "text/html") || c.Query("format") == "html" {
		c.Header("Content-Type", "text/html; charset=utf-8")
		c.String(http.StatusOK, "<p>Install the VoidSwitch OpenCode plugin (V2, for OpenCode 2.x):</p><pre>curl -fsSL "+base+"/install.sh | sh</pre>"+
			"<p>For OpenCode 1.x, install the V1 plugin instead:</p><pre>curl -fsSL \""+base+"/install.sh?v=1\" | sh</pre>")
		return
	}
	c.String(http.StatusOK, "VoidSwitch installer:\n"+
		"  V2 (OpenCode 2.x):  curl -fsSL "+base+"/install.sh | sh\n"+
		"  V1 (OpenCode 1.x):  curl -fsSL \""+base+"/install.sh?v=1\" | sh\n")
}

// pluginSource serves a plugin's TypeScript source verbatim, so a self-hosted
// gateway always hands out the source matching its own release.
func (a *App) pluginSource(c *gin.Context) {
	version := requestedPluginVersion(c)
	path := pluginSourcePath(version)
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
		available[v] = pluginSourcePath(v) != ""
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
	// Both generations are served; `?v=1` selects the V1 source on either route.
	r.GET("/opencode/voidswitch.ts", a.pluginSource)
	r.GET("/opencode/voidswitch-v1.ts", a.pluginSource)
	r.GET("/opencode/plugin-versions", a.pluginVersionInfo)
}
