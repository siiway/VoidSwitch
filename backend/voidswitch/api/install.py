"""One-line OpenCode installer.

``curl -fsSL http://host:8080/install | bash`` (macOS/Linux) or
``irm http://host:8080/install | iex`` (Windows PowerShell) merges a VoidSwitch
provider into the user's ``opencode.json``. ``/install`` content-negotiates on
the User-Agent (PowerShell → ``.ps1``, everything else → bash); ``/install.sh``
and ``/install.ps1`` force a specific shell.

The gateway URL is taken from the request (so it matches however the user
reached us) and the optional ``?token=vs-…`` is validated before being embedded
— both are restricted to a safe character set so neither can break out of the
generated script.
"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import PlainTextResponse

from voidswitch.core.config import Settings, get_settings

router = APIRouter(tags=["install"])

# The OpenCode plugin source lives at <repo>/opencode-plugin/src/index.ts. The
# installer downloads it from /opencode/voidswitch.ts so a self-hosted gateway is
# fully self-contained (no npm publish needed). Bun loads the single .ts file
# directly; its only import is type-only and erased at load.
_PLUGIN_PATH = Path(__file__).resolve().parents[3] / "opencode-plugin" / "src" / "index.ts"


def _plugin_source() -> str | None:
    # Read fresh each request so plugin edits are served without a server restart.
    try:
        return _PLUGIN_PATH.read_text(encoding="utf-8")
    except OSError:
        return None


# Tokens are ``vs-`` + url-safe base64; anything else is ignored (treated as no
# token) so it can never inject shell/PowerShell syntax.
_TOKEN_RE = re.compile(r"^vs-[A-Za-z0-9_-]{8,200}$")
_GATEWAY_RE = re.compile(r"^https?://[A-Za-z0-9.\-:\[\]]{1,255}$")


def _safe_gateway(request: Request, settings: Settings) -> str:
    raw = str(request.base_url).rstrip("/")
    if _GATEWAY_RE.match(raw):
        return raw
    return settings.server.base_url.rstrip("/")


def _safe_token(token: str | None) -> str:
    return token if token and _TOKEN_RE.match(token) else ""


# --------------------------------------------------------------------------- #
# Script templates (sentinels replaced after validation — never f-strings, to
# avoid escaping the JSON/here-doc braces below).
# --------------------------------------------------------------------------- #

_BASH = r"""#!/usr/bin/env bash
# VoidSwitch → OpenCode installer (deep integration: effort, fast mode, thinking, 1M)
set -euo pipefail

GATEWAY="${VOIDSWITCH_URL:-__GATEWAY__}"
TOKEN="${VOIDSWITCH_TOKEN:-__TOKEN__}"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/opencode"
DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/opencode"
CONFIG="${OPENCODE_CONFIG:-$CONFIG_DIR/opencode.json}"
AUTH="$DATA_DIR/auth.json"
PLUGIN="$CONFIG_DIR/voidswitch.plugin.ts"

mkdir -p "$CONFIG_DIR" "$DATA_DIR"

# Back up existing config + auth BEFORE touching anything. Timestamped so repeat
# runs never clobber an earlier backup.
STAMP="$(date +%Y%m%d%H%M%S)"
backup() {
  if [ -f "$1" ]; then
    cp -p "$1" "$1.$STAMP.bak"
    echo "✓ backed up $1 → $1.$STAMP.bak"
  fi
}
backup "$CONFIG"
backup "$AUTH"

# --------------------------------------------------------------------------- #
# Manual snippet — shown when automatic merge fails.  Print it so the user
# can copy-paste into their opencode.json by hand.
# --------------------------------------------------------------------------- #
print_manual_snippet() {
  cat <<SNIPPET

╔══════════════════════════════════════════════════════════════════════════════╗
║  Automatic merge failed.  Add this to your opencode.json manually:          ║
╠══════════════════════════════════════════════════════════════════════════════╣
║                                                                              ║
║  1. In "plugin" array, add:                                                  ║
║     "$PLUGIN"                                                                ║
║                                                                              ║
║  2. In "provider" object, add:                                               ║
║     "voidswitch": {                                                          ║
║       "npm": "@ai-sdk/anthropic",                                            ║
║       "name": "VoidSwitch",                                                  ║
║       "options": { "baseURL": "$GATEWAY/v1" },                               ║
║       "models": {                                                            ║
║         "claude-opus-4-8": {}, "claude-opus-4-7": {},                       ║
║         "claude-opus-4-6": {}, "claude-sonnet-4-6": {},                     ║
║         "claude-haiku-4-5": {}                                               ║
║       }                                                                      ║
║     }                                                                        ║
║                                                                              ║
║  3. (optional) In "\$HOME/.local/share/opencode/auth.json":                  ║
║     "voidswitch": { "type": "api", "key": "vs-..." }                         ║
║                                                                              ║
║  Your original config is backed up at $CONFIG.$STAMP.bak                     ║
╚══════════════════════════════════════════════════════════════════════════════╝
SNIPPET
}

echo "Note: JSONC comments/trailing-commas in your config will be removed (original preserved in .bak)" >&2

# Download the VoidSwitch plugin (single self-contained .ts file Bun loads directly).
if command -v curl >/dev/null 2>&1; then
  curl -fsSL "$GATEWAY/opencode/voidswitch.ts" -o "$PLUGIN"
elif command -v wget >/dev/null 2>&1; then
  wget -qO "$PLUGIN" "$GATEWAY/opencode/voidswitch.ts"
else
  echo "Need curl or wget to download the plugin." >&2; exit 1
fi

# Merge our entries into the existing JSON — never blast it away. Prefer python3,
# then a JS runtime (node/bun). All of them refuse to overwrite a config that
# exists but can't be parsed; a backup was just made, so nothing is lost.
merge_py() {
  local rc=0
  python3 - "$CONFIG" "$AUTH" "$PLUGIN" "$GATEWAY" "$TOKEN" <<'PY' || rc=$?
import json, os, re, sys
config, auth, plugin, gateway, token = sys.argv[1:6]

def strip_jsonc(text):
    text = re.sub(r'(?<!:)//.*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'/\*[\s\S]*?\*/', '', text)
    text = re.sub(r',(\s*[}\]])', r'\1', text)
    return text

def load(path):
    if not os.path.exists(path):
        return {}, None
    raw = None
    warned = None
    try:
        with open(path) as f:
            raw = f.read()
            data = json.loads(raw)
    except Exception:
        if raw is not None:
            try:
                cleaned = strip_jsonc(raw)
                data = json.loads(cleaned)
                warned = "Note: JSONC comments/trailing-commas were removed from %s (original in backup)" % path
            except Exception:
                sys.stderr.write("Refusing to overwrite unparseable JSON: %s\n" % path)
                sys.exit(2)
        else:
            sys.stderr.write("Refusing to overwrite unparseable JSON: %s\n" % path)
            sys.exit(2)
    if warned:
        sys.stderr.write(warned + "\n")
    return (data if isinstance(data, dict) else {}), warned

cfg, _warn = load(config)
cfg["$schema"] = "https://opencode.ai/config.json"
cfg.setdefault("model", "voidswitch/claude-opus-4-8")
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
provider["voidswitch"] = {
    "npm": "@ai-sdk/anthropic",
    "name": "VoidSwitch",
    "options": {"baseURL": gateway + "/v1"},
    "models": {
        m: {}
        for m in (
            "claude-opus-4-8",
            "claude-opus-4-7",
            "claude-opus-4-6",
            "claude-sonnet-4-6",
            "claude-haiku-4-5",
        )
    },
}

with open(config, "w") as f:
    json.dump(cfg, f, indent=2)

if token:
    a, _ = load(auth)
    a["voidswitch"] = {"type": "api", "key": token}
    with open(auth, "w") as f:
        json.dump(a, f, indent=2)
    print("✓ token stored in " + auth)
print("✓ VoidSwitch plugin merged into " + config)
PY
  if [ $rc -ne 0 ]; then
    if [ $rc -eq 2 ]; then print_manual_snippet; fi
    return $rc
  fi
}

merge_js() {
  local rt="$1" tmp rc=0
  tmp="$(mktemp)"
  cat > "$tmp" <<'JS'
const fs = require("fs");
const [config, auth, plugin, gateway, token] = process.argv.slice(2);

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
        process.stderr.write("Note: JSONC comments/trailing-commas were removed from " + path + " (original in backup)\n");
        return d && typeof d === "object" && !Array.isArray(d) ? d : {};
      } catch {}
    }
    process.stderr.write("Refusing to overwrite unparseable JSON: " + path + "\n");
    process.exit(2);
  }
}

const cfg = load(config);
cfg["$schema"] = "https://opencode.ai/config.json";
if (!cfg.model) cfg.model = "voidswitch/claude-opus-4-8";
delete cfg.small_model;
const ref = (p) => (Array.isArray(p) && p.length ? p[0] : p);
let plugins = Array.isArray(cfg.plugin) ? cfg.plugin : [];
plugins = plugins.filter((p) => !(typeof ref(p) === "string" && ref(p).endsWith("voidswitch.plugin.ts")));
plugins.push(plugin);
cfg.plugin = plugins;
if (typeof cfg.provider !== "object" || cfg.provider === null) cfg.provider = {};
cfg.provider.voidswitch = {
  npm: "@ai-sdk/anthropic",
  name: "VoidSwitch",
  options: { baseURL: gateway + "/v1" },
  models: Object.fromEntries(
    ["claude-opus-4-8", "claude-opus-4-7", "claude-opus-4-6", "claude-sonnet-4-6", "claude-haiku-4-5"].map((m) => [m, {}])
  ),
};
fs.writeFileSync(config, JSON.stringify(cfg, null, 2));
if (token) {
  const a = load(auth);
  a.voidswitch = { type: "api", key: token };
  fs.writeFileSync(auth, JSON.stringify(a, null, 2));
  console.log("✓ token stored in " + auth);
}
console.log("✓ VoidSwitch plugin merged into " + config);
JS
  "$rt" "$tmp" "$CONFIG" "$AUTH" "$PLUGIN" "$GATEWAY" "$TOKEN" || rc=$?
  rm -f "$tmp"
  if [ $rc -ne 0 ]; then
    if [ $rc -eq 2 ]; then print_manual_snippet; fi
    return $rc
  fi
}

if command -v python3 >/dev/null 2>&1; then
  merge_py
elif command -v node >/dev/null 2>&1; then
  merge_js node
elif command -v bun >/dev/null 2>&1; then
  merge_js bun
elif [ -f "$CONFIG" ]; then
  echo "Need python3, node, or bun to merge into an existing $CONFIG without overwriting it." >&2
  echo "Install one and re-run. Your config is untouched (backup at $CONFIG.$STAMP.bak)." >&2
  print_manual_snippet
  exit 1
else
  # No existing config — safe to write a fresh one directly.
  cat > "$CONFIG" <<JSON
{
  "\$schema": "https://opencode.ai/config.json",
  "model": "voidswitch/claude-opus-4-8",
  "plugin": ["$PLUGIN"],
  "provider": {
    "voidswitch": {
      "npm": "@ai-sdk/anthropic",
      "name": "VoidSwitch",
      "options": { "baseURL": "$GATEWAY/v1" },
      "models": {
        "claude-opus-4-8": {}, "claude-opus-4-7": {}, "claude-opus-4-6": {},
        "claude-sonnet-4-6": {}, "claude-haiku-4-5": {}
      }
    }
  }
}
JSON
  if [ -n "$TOKEN" ]; then
    cat > "$AUTH" <<JSON
{ "voidswitch": { "type": "api", "key": "$TOKEN" } }
JSON
  fi
  echo "✓ Wrote fresh $CONFIG."
fi

echo ""
echo "OpenCode is deeply integrated with VoidSwitch (effort, fast mode, thinking, 1M context)."
if [ -z "$TOKEN" ]; then
  echo "Next: run 'opencode', then /connect -> VoidSwitch -> paste a vs-... token."
else
  echo "Next: run 'opencode' and pick a VoidSwitch model (try the :xhigh or :fast variant)."
fi
"""

_PS = r"""# VoidSwitch -> OpenCode installer (PowerShell 5.1+ / 7+)
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

# Back up existing config + auth BEFORE touching anything. Timestamped so repeat
# runs never clobber an earlier backup.
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

# Download the VoidSwitch plugin (single self-contained .ts file Bun loads directly).
Invoke-WebRequest -UseBasicParsing -Uri "$Gateway/opencode/voidswitch.ts" -OutFile $Plugin

# Strip JSONC comments and trailing commas so standard JSON parsers can handle it.
function Strip-Jsonc {
  param([string]$text)
  $text = $text -replace '(?<!:)//.*$', ''
  $text = $text -replace '(?s)/\*.*?\*/', ''
  $text = $text -replace ',(\s*[}\]])', '$1'
  return $text
}

# Load existing JSON, but REFUSE to overwrite a file that exists yet can't be
# parsed (a backup was just made) — so we never silently wipe a real config.
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
      Write-Host "Note: JSONC comments/trailing-commas were removed from $path (original in backup)"
      if ($null -eq $o) { return [pscustomobject]@{} }
      return $o
    } catch {
      Write-Host ""
      Write-Host "Could not parse $path (backup at $path.$Stamp.bak)"
      Write-Host "Add this to your opencode.json manually:"
      Write-Host "  1. In 'plugin' array, add: '$Plugin'"
      Write-Host "  2. In 'provider' object, add:"
      Write-Host '     "voidswitch": {'
      Write-Host '       "npm": "@ai-sdk/anthropic",'
      Write-Host '       "name": "VoidSwitch",'
      Write-Host "       ""options"": { ""baseURL"": ""$Gateway/v1"" },"
      Write-Host '       "models": { "claude-opus-4-8":{}, "claude-opus-4-7":{},'
      Write-Host '                  "claude-opus-4-6":{}, "claude-sonnet-4-6":{},'
      Write-Host '                  "claude-haiku-4-5":{} } }'
      throw "Refusing to overwrite unparseable JSON: $path"
    }
  }
}

$cfg = Load-Json $Config

$cfg | Add-Member -NotePropertyName '$schema' -NotePropertyValue 'https://opencode.ai/config.json' -Force
if (-not $cfg.PSObject.Properties['model']) {
  $cfg | Add-Member -NotePropertyName 'model' -NotePropertyValue 'voidswitch/claude-opus-4-8' -Force
}
if ($cfg.PSObject.Properties['small_model']) {
  $cfg.PSObject.Properties.Remove('small_model')
}

# plugin: drop any prior voidswitch.plugin.ts entry, then append ours (plain path).
$plugins = [System.Collections.ArrayList]@()
if ($cfg.PSObject.Properties['plugin'] -and $cfg.plugin) {
  foreach ($p in @($cfg.plugin)) {
    $r = if ($p -is [System.Array]) { $p[0] } else { $p }
    if (-not (($r -is [string]) -and $r.EndsWith('voidswitch.plugin.ts'))) { [void]$plugins.Add($p) }
  }
}
[void]$plugins.Add($Plugin)
$cfg | Add-Member -NotePropertyName 'plugin' -NotePropertyValue ([string[]]$plugins) -Force

# Full provider block (Anthropic dialect). The models map is REQUIRED — OpenCode
# drops a provider with no models, so it would never appear in /connect.
$provider = if ($cfg.PSObject.Properties['provider'] -and $cfg.provider) { $cfg.provider } else { [pscustomobject]@{} }
$models = [pscustomobject]@{}
foreach ($m in @('claude-opus-4-8','claude-opus-4-7','claude-opus-4-6','claude-sonnet-4-6','claude-haiku-4-5')) {
  $models | Add-Member -NotePropertyName $m -NotePropertyValue ([pscustomobject]@{}) -Force
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

# Token -> auth store, so the plugin's loader (and effort/thinking rewriting) runs.
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
"""


def _render(template: str, gateway: str, token: str) -> str:
    return template.replace("__GATEWAY__", gateway).replace("__TOKEN__", token)


def _bash(request: Request, settings: Settings, token: str | None) -> PlainTextResponse:
    body = _render(_BASH, _safe_gateway(request, settings), _safe_token(token))
    return PlainTextResponse(body, media_type="text/x-shellscript; charset=utf-8")


def _powershell(request: Request, settings: Settings, token: str | None) -> PlainTextResponse:
    body = _render(_PS, _safe_gateway(request, settings), _safe_token(token))
    return PlainTextResponse(body, media_type="text/plain; charset=utf-8")


@router.get("/install", response_class=PlainTextResponse)
async def install(
    request: Request,
    token: str | None = None,
    settings: Settings = Depends(get_settings),
) -> PlainTextResponse:
    """Serve the right installer for the calling shell (UA-sniffed)."""
    ua = request.headers.get("user-agent", "").lower()
    if "powershell" in ua or "pwsh" in ua:
        return _powershell(request, settings, token)
    return _bash(request, settings, token)


@router.get("/install.sh", response_class=PlainTextResponse)
async def install_sh(
    request: Request,
    token: str | None = None,
    settings: Settings = Depends(get_settings),
) -> PlainTextResponse:
    return _bash(request, settings, token)


@router.get("/install.ps1", response_class=PlainTextResponse)
async def install_ps1(
    request: Request,
    token: str | None = None,
    settings: Settings = Depends(get_settings),
) -> PlainTextResponse:
    return _powershell(request, settings, token)


@router.get("/opencode/voidswitch.ts", response_class=PlainTextResponse)
async def opencode_plugin() -> PlainTextResponse:
    """Serve the VoidSwitch OpenCode plugin source (downloaded by the installer)."""
    source = _plugin_source()
    if source is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Plugin source not bundled with this server."
        )
    return PlainTextResponse(source, media_type="application/typescript; charset=utf-8")
