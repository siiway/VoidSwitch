package handlers

import (
	"net/http"
	"os"
	"path/filepath"
	"strings"

	"github.com/gin-gonic/gin"
)

// pluginSourcePath resolves the OpenCode plugin source relative to the repo.
func pluginSourcePath() string {
	candidates := []string{
		"../opencode-plugin/src/index.ts",
		"opencode-plugin/src/index.ts",
		"/app/opencode-plugin/src/index.ts",
	}
	for _, p := range candidates {
		if _, err := os.Stat(p); err == nil {
			abs, _ := filepath.Abs(p)
			return abs
		}
	}
	return ""
}

// installSnippet serves the one-line installer for the OpenCode plugin.
func (a *App) installScript(c *gin.Context) {
	gateway := strings.TrimRight(a.Cfg.Server.BaseURL, "/")
	body := "#!/bin/sh\n# VoidSwitch OpenCode plugin installer\n" +
		"set -e\nGATEWAY=\"${VOIDSWITCH_GATEWAY:-" + gateway + "}\"\n" +
		"DIR=\"${XDG_CONFIG_HOME:-$HOME/.config}/opencode\"\n" +
		"mkdir -p \"$DIR/plugins\"\n" +
		"if command -v curl >/dev/null 2>&1; then\n" +
		"  curl -fsSL \"$GATEWAY/opencode/voidswitch.ts\" -o \"$DIR/plugins/voidswitch.ts\"\n" +
		"else\n  wget -qO \"$DIR/plugins/voidswitch.ts\" \"$GATEWAY/opencode/voidswitch.ts\"\nfi\n" +
		"echo \"Installed VoidSwitch plugin to $DIR/plugins/voidswitch.ts\"\n"
	c.Header("Content-Type", "text/x-shellscript")
	c.String(http.StatusOK, body)
}

func (a *App) installPowerShell(c *gin.Context) {
	gateway := strings.TrimRight(a.Cfg.Server.BaseURL, "/")
	body := "# VoidSwitch OpenCode plugin installer (PowerShell)\n" +
		"$Gateway = if ($env:VOIDSWITCH_GATEWAY) { $env:VOIDSWITCH_GATEWAY } else { \"" + gateway + "\" }\n" +
		"$Dir = Join-Path $env:APPDATA \"opencode\\plugins\"\n" +
		"New-Item -ItemType Directory -Force -Path $Dir | Out-Null\n" +
		"Invoke-WebRequest -Uri \"$Gateway/opencode/voidswitch.ts\" -OutFile (Join-Path $Dir \"voidswitch.ts\")\n" +
		"Write-Host \"Installed VoidSwitch plugin to $Dir\\voidswitch.ts\"\n"
	c.Header("Content-Type", "text/plain")
	c.String(http.StatusOK, body)
}

// installPage serves the /install landing text.
func (a *App) installPage(c *gin.Context) {
	if strings.Contains(c.GetHeader("Accept"), "text/html") || c.Query("format") == "html" {
		c.Header("Content-Type", "text/html; charset=utf-8")
		c.String(http.StatusOK, "<p>Install the VoidSwitch OpenCode plugin:</p><pre>curl -fsSL "+strings.TrimRight(a.Cfg.Server.BaseURL, "/")+"/install.sh | sh</pre>")
		return
	}
	c.String(http.StatusOK, "VoidSwitch installer:\n  curl -fsSL "+strings.TrimRight(a.Cfg.Server.BaseURL, "/")+"/install.sh | sh\n")
}

// pluginSource serves the OpenCode plugin TypeScript source.
func (a *App) pluginSource(c *gin.Context) {
	path := pluginSourcePath()
	if path == "" {
		a.fail(c, http.StatusNotFound, "Plugin source not bundled in this build.")
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

// RegisterInstallRoutes wires the public install/plugin endpoints.
func RegisterInstallRoutes(r *gin.Engine, a *App) {
	r.GET("/install", a.installPage)
	r.GET("/install.sh", a.installScript)
	r.GET("/install.ps1", a.installPowerShell)
	r.GET("/opencode/voidswitch.ts", a.pluginSource)
}
