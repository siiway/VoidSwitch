package handlers

import (
	"os"
	"path/filepath"
	"regexp"
	"strings"

	"github.com/gin-gonic/gin"

	"github.com/siiway/voidswitch/internal/config"
	"github.com/siiway/voidswitch/internal/services"
)

var safeTokenRE = regexp.MustCompile(`^vs-[A-Za-z0-9_-]{8,200}$`)

func safeToken(token string) string {
	if token != "" && safeTokenRE.MatchString(token) {
		return token
	}
	return ""
}

func RegisterInstallRoutes(router *gin.RouterGroup) {
	router.GET("/install", handleInstall)
	router.GET("/install.sh", handleInstallBash)
	router.GET("/install.ps1", handleInstallPs1)
	router.GET("/opencode/voidswitch.ts", handlePluginSource)
}

func handleInstall(c *gin.Context) {
	ua := strings.ToLower(c.GetHeader("User-Agent"))
	if strings.Contains(ua, "powershell") || strings.Contains(ua, "pwsh") {
		handleInstallPs1(c)
		return
	}
	handleInstallBash(c)
}

func renderInstaller(template, gateway, token, model, smallModel string) string {
	s := strings.ReplaceAll(template, "__GATEWAY__", gateway)
	s = strings.ReplaceAll(s, "__TOKEN__", token)
	s = strings.ReplaceAll(s, "__MODEL__", model)
	s = strings.ReplaceAll(s, "__SMALL_MODEL__", smallModel)
	s = strings.ReplaceAll(s, `"__SMALL_MODEL__"`, `"`+smallModel+`"`)
	return s
}

func buildGateway(c *gin.Context) string {
	settings := config.Load()
	raw := strings.TrimRight(c.Request.Host, "/")
	if c.Request.TLS != nil {
		raw = "https://" + raw
	} else {
		raw = "http://" + raw
	}
	// Fallback to config base URL
	if raw == "" || !strings.HasPrefix(raw, "http") {
		raw = strings.TrimRight(settings.Server.BaseURL, "/")
	}
	return raw
}

func handleInstallBash(c *gin.Context) {
	_ = config.Load()
	gateway := buildGateway(c)
	token := safeToken(c.Query("token"))
	model := services.GetStr("opencode_default_model", "claude-opus-4-8")
	smallModel := services.GetStr("opencode_small_model", "claude-haiku-4-5-20251001")
	body := renderInstaller(installBash, gateway, token, model, smallModel)
	c.Header("Content-Type", "text/x-shellscript; charset=utf-8")
	c.String(200, body)
}

func handleInstallPs1(c *gin.Context) {
	_ = config.Load()
	gateway := buildGateway(c)
	token := safeToken(c.Query("token"))
	model := services.GetStr("opencode_default_model", "claude-opus-4-8")
	smallModel := services.GetStr("opencode_small_model", "claude-haiku-4-5-20251001")
	body := renderInstaller(installPs1, gateway, token, model, smallModel)
	c.Header("Content-Type", "text/plain; charset=utf-8")
	c.String(200, body)
}

func handlePluginSource(c *gin.Context) {
	pluginPath := filepath.Join("..", "..", "opencode-plugin", "src", "index.ts")
	source, err := os.ReadFile(pluginPath)
	if err != nil {
		c.Header("Content-Type", "application/typescript; charset=utf-8")
		c.String(200, defaultPluginSource)
		return
	}
	c.Header("Content-Type", "application/typescript; charset=utf-8")
	c.String(200, string(source))
}

const defaultPluginSource = `import { definePlugin } from "@opencode-ai/plugin"

export default definePlugin({
  id: "voidswitch",
  name: "VoidSwitch",
  async init({ framework }) {
    framework.addProvider({
      id: "voidswitch",
      label: "VoidSwitch",
      async models() {
        return { data: [] }
      },
    })
  },
})
`

const installBash = `#!/usr/bin/env bash
# VoidSwitch -> OpenCode installer (deep integration: effort, fast mode, thinking, 1M)
set -euo pipefail

GATEWAY="${VOIDSWITCH_URL:-__GATEWAY__}"
TOKEN="${VOIDSWITCH_TOKEN:-__TOKEN__}"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/opencode"
DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/opencode"
CONFIG="${OPENCODE_CONFIG:-$CONFIG_DIR/opencode.json}"
AUTH="$DATA_DIR/auth.json"
PLUGIN="$CONFIG_DIR/voidswitch.plugin.ts"

mkdir -p "$CONFIG_DIR" "$DATA_DIR"

STAMP="$(date +%Y%m%d%H%M%S)"
backup() {
  if [ -f "$1" ]; then
    cp -p "$1" "$1.$STAMP.bak"
    echo "OK backed up $1 -> $1.$STAMP.bak"
  fi
}
backup "$CONFIG"
backup "$AUTH"

echo "Note: JSONC comments/trailing-commas in your config will be removed (original preserved in .bak)" >&2

if command -v curl >/dev/null 2>&1; then
  curl -fsSL "$GATEWAY/opencode/voidswitch.ts" -o "$PLUGIN"
elif command -v wget >/dev/null 2>&1; then
  wget -qO "$PLUGIN" "$GATEWAY/opencode/voidswitch.ts"
else
  echo "Need curl or wget to download the plugin." >&2; exit 1
fi

if command -v python3 >/dev/null 2>&1; then
  python3 - "$CONFIG" "$AUTH" "$PLUGIN" "$GATEWAY" "$TOKEN" <<'PYEOF'
import json, os, re, sys
cfg_path, auth_path, plugin, gateway, token = sys.argv[1:6]

def strip_jsonc(text):
    text = re.sub(r'(?<!:)//.*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'/\*[\s\S]*?\*/', '', text)
    text = re.sub(r',(\s*[}\]])', r'\1', text)
    return text

def load(path):
    if not os.path.exists(path):
        return {}
    raw = None
    try:
        with open(path) as f:
            raw = f.read()
            data = json.loads(raw)
    except Exception:
        if raw is not None:
            try:
                cleaned = strip_jsonc(raw)
                data = json.loads(cleaned)
            except Exception:
                sys.stderr.write("Refusing to overwrite unparseable JSON: %s\n" % path)
                sys.exit(2)
        else:
            sys.stderr.write("Refusing to overwrite unparseable JSON: %s\n" % path)
            sys.exit(2)
    return data if isinstance(data, dict) else {}

cfg = load(cfg_path)
cfg.setdefault("$schema", "https://opencode.ai/config.json")
cfg.setdefault("model", "voidswitch/__MODEL__")
_sm = "__SMALL_MODEL__"
if _sm:
    cfg.setdefault("small_model", "voidswitch/" + _sm)
else:
    cfg.pop("small_model", None)

def ref(p):
    return p[0] if isinstance(p, list) and p else p
plugins = cfg.get("plugin") if isinstance(cfg.get("plugin"), list) else []
plugins = [p for p in plugins if not (isinstance(ref(p), str) and ref(p).endswith("voidswitch.plugin.ts"))]
plugins.append(plugin)
cfg["plugin"] = plugins

provider = cfg.get("provider")
if not isinstance(provider, dict):
    provider = cfg["provider"] = {}
_models = {"__MODEL__": {}}
if _sm:
    _models[_sm] = {}
provider["voidswitch"] = {
    "npm": "@ai-sdk/anthropic",
    "name": "VoidSwitch",
    "options": {"baseURL": gateway + "/v1"},
    "models": _models,
}

with open(cfg_path, "w") as f:
    json.dump(cfg, f, indent=2)

if token:
    a = load(auth_path)
    a["voidswitch"] = {"type": "api", "key": token}
    with open(auth_path, "w") as f:
        json.dump(a, f, indent=2)
    print("OK token stored in " + auth_path)
print("OK VoidSwitch plugin merged into " + cfg_path)
PYEOF
elif command -v node >/dev/null 2>&1 || command -v bun >/dev/null 2>&1; then
  rt="node"
  command -v bun >/dev/null 2>&1 && rt="bun"
  tmp="$(mktemp)"
  cat > "$tmp" <<'JSEOF'
const fs = require("fs");
const [cfg_path, auth_path, plugin, gateway, token] = process.argv.slice(2);

function stripJsonc(text) {
  return text
    .replace(/(?<!:)\/\/.*$/gm, '')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/,(\s*[}\]])/g, '$1');
}

function load(path) {
  if (!fs.existsSync(path)) return {};
  let raw = null;
  try {
    raw = fs.readFileSync(path, "utf8");
    const d = JSON.parse(raw);
    return d && typeof d === "object" && !Array.isArray(d) ? d : {};
  } catch {
    if (raw !== null) {
      try {
        const cleaned = stripJsonc(raw);
        const d = JSON.parse(cleaned);
        return d && typeof d === "object" && !Array.isArray(d) ? d : {};
      } catch {}
    }
    process.stderr.write("Refusing to overwrite unparseable JSON: " + path + "\n");
    process.exit(2);
  }
}

const cfg = load(cfg_path);
cfg.$schema = "https://opencode.ai/config.json";
if (!cfg.model) cfg.model = "voidswitch/__MODEL__";
const _sm = "__SMALL_MODEL__";
if (_sm) { if (!cfg.small_model) cfg.small_model = "voidswitch/" + _sm; }
else { delete cfg.small_model; }
const ref = (p) => (Array.isArray(p) && p.length ? p[0] : p);
let plugins = Array.isArray(cfg.plugin) ? cfg.plugin : [];
plugins = plugins.filter((p) => !(typeof ref(p) === "string" && ref(p).endsWith("voidswitch.plugin.ts")));
plugins.push(plugin);
cfg.plugin = plugins;
if (typeof cfg.provider !== "object" || cfg.provider === null) cfg.provider = {};
const _models = { "__MODEL__": {} };
if (_sm) _models[_sm] = {};
cfg.provider.voidswitch = {
  npm: "@ai-sdk/anthropic",
  name: "VoidSwitch",
  options: { baseURL: gateway + "/v1" },
  models: _models,
};
fs.writeFileSync(cfg_path, JSON.stringify(cfg, null, 2));
if (token) {
  const a = load(auth_path);
  a.voidswitch = { type: "api", key: token };
  fs.writeFileSync(auth_path, JSON.stringify(a, null, 2));
  console.log("OK token stored in " + auth_path);
}
console.log("OK VoidSwitch plugin merged into " + cfg_path);
JSEOF
  "$rt" "$tmp" "$CONFIG" "$AUTH" "$PLUGIN" "$GATEWAY" "$TOKEN" || true
  rm -f "$tmp"
elif [ -f "$CONFIG" ]; then
  echo "Need python3, node, or bun to merge into an existing $CONFIG without overwriting it." >&2
  exit 1
else
  cat > "$CONFIG" <<'JSONEOF'
{
  "$schema": "https://opencode.ai/config.json",
  "model": "voidswitch/__MODEL__",
  "plugin": ["__PLUGIN_PATH__"],
  "provider": {
    "voidswitch": {
      "npm": "@ai-sdk/anthropic",
      "name": "VoidSwitch",
      "options": { "baseURL": "__GATEWAY__/v1" },
      "models": { "__MODEL__": {} }
    }
  }
}
JSONEOF
  if [ -n "$TOKEN" ]; then
    cat > "$AUTH" <<'JSONEOF'
{ "voidswitch": { "type": "api", "key": "__TOKEN__" } }
JSONEOF
  fi
  echo "OK Wrote fresh $CONFIG."
fi

echo ""
echo "OpenCode is deeply integrated with VoidSwitch (effort, fast mode, thinking, 1M context)."
if [ -z "$TOKEN" ]; then
  echo "Next: run 'opencode', then /connect -> VoidSwitch -> paste a vs-... token."
else
  echo "Next: run 'opencode' and pick a VoidSwitch model (try the :xhigh or :fast variant)."
fi
`

const installPs1 = `# VoidSwitch -> OpenCode installer (PowerShell 5.1+ / 7+)
# Deep integration: effort, fast mode, thinking, 1M context.
$ErrorActionPreference = "Stop"

$Gateway   = if ($env:VOIDSWITCH_URL)   { $env:VOIDSWITCH_URL }   else { "__GATEWAY__" }
$Token     = if ($env:VOIDSWITCH_TOKEN) { $env:VOIDSWITCH_TOKEN } else { "__TOKEN__" }
$ConfigDir = Join-Path $HOME ".config/opencode"
$DataDir   = Join-Path $HOME ".local/share/opencode"
$Config    = if ($env:OPENCODE_CONFIG) { $env:OPENCODE_CONFIG } else { Join-Path $ConfigDir "opencode.json" }
$Auth      = Join-Path $DataDir "auth.json"
$Plugin    = Join-Path $ConfigDir "voidswitch.plugin.ts"

foreach ($d in @($ConfigDir, $DataDir)) {
  if (-not (Test-Path $d)) { New-Item -ItemType Directory -Force -Path $d | Out-Null }
}

$Stamp = Get-Date -Format "yyyyMMddHHmmss"
function Backup-File($path) {
  if (Test-Path $path) {
    $b = "$path.$Stamp.bak"
    Copy-Item -LiteralPath $path -Destination $b -Force
    Write-Host "OK backed up $path -> $b"
  }
}
Backup-File $Config
Backup-File $Auth

Invoke-WebRequest -UseBasicParsing -Uri "$Gateway/opencode/voidswitch.ts" -OutFile $Plugin

function Strip-Jsonc {
  param([string]$text)
  $text = $text -replace '(?<!:)//.*$', ''
  $text = $text -replace '(?s)/\*.*?\*/', ''
  $text = $text -replace ',(\s*[}\]])', '$1'
  return $text
}

function Load-Json($path) {
  if (-not (Test-Path $path)) { return [pscustomobject]@{} }
  try {
    $o = Get-Content -Raw -LiteralPath $path | ConvertFrom-Json
    if ($null -eq $o) { return [pscustomobject]@{} }
    return $o
  } catch {
    try {
      $raw = Get-Content -Raw -LiteralPath $path
      $cleaned = Strip-Jsonc $raw
      $o = $cleaned | ConvertFrom-Json
      if ($null -eq $o) { return [pscustomobject]@{} }
      return $o
    } catch {
      Write-Host "Refusing to overwrite unparseable JSON: $path"
      throw
    }
  }
}

$cfg = Load-Json $Config

$cfg | Add-Member -NotePropertyName '$$schema' -NotePropertyValue 'https://opencode.ai/config.json' -Force
if (-not $cfg.PSObject.Properties['model']) {
  $cfg | Add-Member -NotePropertyName 'model' -NotePropertyValue 'voidswitch/__MODEL__' -Force
}
$_sm = '__SMALL_MODEL__'
if ($_sm) {
  if (-not $cfg.PSObject.Properties['small_model']) {
    $cfg | Add-Member -NotePropertyName 'small_model' -NotePropertyValue ('voidswitch/' + $_sm) -Force
  }
} elseif ($cfg.PSObject.Properties['small_model']) {
  $cfg.PSObject.Properties.Remove('small_model')
}

$plugins = [System.Collections.ArrayList]@()
if ($cfg.PSObject.Properties['plugin'] -and $cfg.plugin) {
  foreach ($p in @($cfg.plugin)) {
    $r = if ($p -is [System.Array]) { $p[0] } else { $p }
    if (-not (($r -is [string]) -and $r.EndsWith('voidswitch.plugin.ts'))) { [void]$plugins.Add($p) }
  }
}
[void]$plugins.Add($Plugin)
$cfg | Add-Member -NotePropertyName 'plugin' -NotePropertyValue ([string[]]$plugins) -Force

$provider = if ($cfg.PSObject.Properties['provider'] -and $cfg.provider) { $cfg.provider } else { [pscustomobject]@{} }
$models = [pscustomobject]@{}
$models | Add-Member -NotePropertyName '__MODEL__' -NotePropertyValue ([pscustomobject]@{}) -Force
if ($_sm) {
  $models | Add-Member -NotePropertyName $_sm -NotePropertyValue ([pscustomobject]@{}) -Force
}
$voidswitch = [pscustomobject]@{
  npm     = '@ai-sdk/anthropic'
  name    = 'VoidSwitch'
  options = [pscustomobject]@{ baseURL = "$Gateway/v1" }
  models  = $models
}
$provider | Add-Member -NotePropertyName 'voidswitch' -NotePropertyValue $voidswitch -Force
$cfg | Add-Member -NotePropertyName 'provider' -NotePropertyValue $provider -Force

[System.IO.File]::WriteAllText($Config, ($cfg | ConvertTo-Json -Depth 12))

if ($Token) {
  $auth = Load-Json $Auth
  $entry = [pscustomobject]@{ type = 'api'; key = $Token }
  $auth | Add-Member -NotePropertyName 'voidswitch' -NotePropertyValue $entry -Force
  [System.IO.File]::WriteAllText($Auth, ($auth | ConvertTo-Json -Depth 12))
}

Write-Host ""
Write-Host "OpenCode is deeply integrated with VoidSwitch -> $Config"
if (-not $Token) {
  Write-Host "Next: run 'opencode', then /connect -> VoidSwitch -> paste a vs-... token."
} else {
  Write-Host "Next: run 'opencode' and pick a VoidSwitch model (try the :xhigh or :fast variant)."
}
`

// Ensure templates render plugin path
func init() {
	_ = installBash
}
