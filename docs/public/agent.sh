#!/usr/bin/env bash
# One-line installer for voidswitch-agent, the VoidSwitch outbound relay.
#
#   curl -fsSL https://voidswitch.siiway.page/agent.sh | sudo bash -s -- [flags...]
#
# Every flag after `--` is passed straight through to the agent executable (see
# agent/README.md): --listen, --token, --tls-cert/--tls-key, --mode,
# --upstream-proxy, --bind-address, --allowlist-ips, --idle-timeout,
# --max-streams, --dial-timeout, --log-level, --metrics-path.
#
# The script detects OS/arch, downloads the matching release binary from GitHub,
# installs it, and registers a persistent service (systemd on Linux, launchd on
# macOS). Where no service manager can register a service it prints the exact
# manual command instead.
set -euo pipefail

REPO="siiway/VoidSwitch"
APP="voidswitch-agent"
SERVICE="voidswitch-agent"
API_URL="https://api.github.com/repos/${REPO}/releases?per_page=100"
BIN_URL="https://github.com/${REPO}/releases/download"

info() { printf '\033[1;34m»\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m✓\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!\033[0m %s\n' "$*" >&2; }
fail() { printf '\033[1;31m✗\033[0m %s\n' "$*" >&2; exit 1; }

download() {
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL --retry 3 "$1"
  elif command -v wget >/dev/null 2>&1; then
    wget -qO- "$1"
  else
    return 127
  fi
}

random_token() {
  command -v openssl >/dev/null 2>&1 && openssl rand -hex 24 2>/dev/null && return 0
  if [ -r /dev/urandom ]; then
    od -v -An -N24 -tx1 /dev/urandom 2>/dev/null | tr -d ' \n' && return 0
  fi
  command -v python3 >/dev/null 2>&1 && python3 -c 'import secrets;print(secrets.token_hex(24))' 2>/dev/null && return 0
  return 1
}

has_flag() {
  local name="$1"; shift
  local a
  for a in "$@"; do
    case "$a" in
      "--$name"|"-$name"|"--$name="*|"-$name="*) return 0 ;;
    esac
  done
  return 1
}

flag_value() {
  local name="$1"; shift
  local prev="" a
  for a in "$@"; do
    case "$a" in
      "--$name="*) printf '%s' "${a#--$name=}"; return 0 ;;
      "-$name="*)  printf '%s' "${a#-$name=}";  return 0 ;;
      "--$name"|"-$name") prev=1 ;;
      *) if [ -n "$prev" ]; then printf '%s' "$a"; return 0; fi ;;
    esac
  done
  return 1
}

xml_escape() { printf '%s' "$1" | sed 's/&/\&amp;/g; s/</\&lt;/g; s/>/\&gt;/g'; }

resolve_version() {
  local v="${VOIDSWITCH_AGENT_VERSION:-}"
  if [ -n "$v" ] && [ "$v" != "latest" ]; then
    printf '%s' "${v#agent-v}"
    return 0
  fi
  local body tag
  body="$(download "$API_URL")" || {
    warn "could not reach GitHub API"
    return 1
  }
  tag="$(printf '%s' "$body" | grep -o '"tag_name":"agent-v[^"]*"' | head -n1 | sed 's/"tag_name":"agent-v//; s/"$//')"
  if [ -z "$tag" ]; then
    warn "no agent-v* release found"
    return 1
  fi
  printf '%s' "$tag"
}

print_manual() {
  local listen cmd
  listen="$(flag_value listen "$@" 2>/dev/null || true)"
  [ -n "$listen" ] || listen=":8443"
  cmd="${BIN}"
  [ -n "${ARGS_PRINT:-}" ] && cmd="${cmd} ${ARGS_PRINT% }"
  cat <<EOF

No service manager could register a persistent service. Run the agent yourself:

  export VOIDSWITCH_AGENT_TOKEN='${TOKEN}'
  nohup ${cmd} >"${RUN_LOG}" 2>&1 &

Wrap it in whatever supervisor you use (systemd, supervisord, pm2, ...) so it is
restarted on exit. On a systemd host, a minimal unit looks like:

  [Service]
  ExecStart=${BIN} ${ARGS_PRINT% }
  Environment=VOIDSWITCH_AGENT_TOKEN=${TOKEN}
  Restart=on-failure
EOF
}

install_linux_service() {
  if ! command -v systemctl >/dev/null 2>&1; then
    warn "no systemd on this system"
    print_manual "$@"
    return
  fi
  local unit
  if [ "$(id -u)" -eq 0 ]; then
    unit="/etc/systemd/system/${SERVICE}.service"
    cat > "$unit" <<EOF
[Unit]
Description=voidswitch-agent (VoidSwitch outbound relay)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=${RUN_SCRIPT}
EnvironmentFile=-${ENV_FILE}
Restart=on-failure
RestartSec=5
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
EOF
    systemctl daemon-reload
    systemctl enable "${SERVICE}" >/dev/null 2>&1
    if systemctl restart "${SERVICE}" 2>/dev/null; then
      ok "systemd service '${SERVICE}' registered and started"
      SERVICE_HINT="manage with: systemctl {status,restart,stop} ${SERVICE}; logs: journalctl -u ${SERVICE} -f"
    else
      warn "service registered but failed to start — check: journalctl -u ${SERVICE}"
    fi
  else
    unit="$HOME/.config/systemd/user/${SERVICE}.service"
    mkdir -p "$(dirname "$unit")"
    cat > "$unit" <<EOF
[Unit]
Description=voidswitch-agent (VoidSwitch outbound relay)

[Service]
Type=simple
ExecStart=${RUN_SCRIPT}
EnvironmentFile=-${ENV_FILE}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
EOF
    if systemctl --user daemon-reload 2>/dev/null \
        && systemctl --user enable "${SERVICE}" >/dev/null 2>&1 \
        && systemctl --user restart "${SERVICE}" 2>/dev/null; then
      ok "systemd --user service '${SERVICE}' registered and started"
      warn "run 'loginctl enable-linger $(id -u)' to keep it running after logout"
      SERVICE_HINT="manage with: systemctl --user {status,restart,stop} ${SERVICE}; logs: journalctl --user -u ${SERVICE} -f"
    else
      warn "could not register a systemd --user service"
      print_manual "$@"
    fi
  fi
}

install_macos_service() {
  local plist label log target run_esc tok_esc
  label="com.siiway.${SERVICE}"
  if [ "$(id -u)" -eq 0 ]; then
    plist="/Library/LaunchDaemons/${label}.plist"
    log="/var/log/${SERVICE}.log"
    target="system"
  else
    mkdir -p "$HOME/Library/LaunchAgents"
    plist="$HOME/Library/LaunchAgents/${label}.plist"
    log="$HOME/${SERVICE}.log"
    target="gui/$(id -u)"
  fi
  run_esc="$(xml_escape "$RUN_SCRIPT")"
  tok_esc="$(xml_escape "$TOKEN")"
  cat > "$plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>${label}</string>
  <key>ProgramArguments</key><array><string>${run_esc}</string></array>
  <key>EnvironmentVariables</key>
  <dict><key>VOIDSWITCH_AGENT_TOKEN</key><string>${tok_esc}</string></dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>${log}</string>
  <key>StandardErrorPath</key><string>${log}</string>
</dict>
</plist>
EOF
  launchctl bootout "$target" "$plist" >/dev/null 2>&1 || true
  if launchctl bootstrap "$target" "$plist" 2>/dev/null; then
    ok "launchd service '${label}' registered and started"
    SERVICE_HINT="manage with: launchctl {print,stop,start} ${label}"
  else
    warn "launchctl bootstrap failed"
    print_manual "$@"
  fi
}

print_summary() {
  local listen
  listen="$(flag_value listen "$@" 2>/dev/null || true)"
  [ -n "$listen" ] || listen=":8443"
  printf '\n'
  ok "installed ${APP} v${version} (${os}/${arch}) → ${BIN}"
  cat <<EOF

  Address: ${listen}
  Token:   ${TOKEN}

Add an "agent" node in VoidSwitch (Nodes & Groups) with the URL
(https://<host>:<port> if you terminate TLS in front of it) and this token.
${SERVICE_HINT}
EOF
}

os=""; arch=""
case "$(uname -s)" in Linux) os=linux;; Darwin) os=darwin;; esac
case "$(uname -m)" in x86_64|amd64) arch=amd64;; arm64|aarch64) arch=arm64;; esac
[ -n "$os" ] && [ -n "$arch" ] || fail "unsupported platform $(uname -s)/$(uname -m) (supported: linux/darwin on amd64/arm64)"

version="$(resolve_version)" || fail "could not determine the latest agent version — pin one with VOIDSWITCH_AGENT_VERSION=0.1.0"

if [ "$(id -u)" -eq 0 ]; then
  BINDIR="/usr/local/bin"
  SYSCONFDIR="/etc/${SERVICE}"
  RUN_LOG="/var/log/${SERVICE}.log"
else
  BINDIR="$HOME/.local/bin"
  SYSCONFDIR="$HOME/.config/${SERVICE}"
  RUN_LOG="$HOME/${SERVICE}.log"
fi
BIN="${BINDIR}/${APP}"
ENV_FILE="${SYSCONFDIR}/env"
TOKEN_FILE="${SYSCONFDIR}/token"
RUN_SCRIPT="${SYSCONFDIR}/run"
SERVICE_HINT=""

mkdir -p "$BINDIR" "$SYSCONFDIR"
info "installing ${APP} v${version} (${os}/${arch}) to ${BIN}"

if has_flag token "$@"; then
  TOKEN="$(flag_value token "$@")"
else
  TOKEN="$(cat "$TOKEN_FILE" 2>/dev/null || true)"
  if [ -z "$TOKEN" ]; then
    TOKEN="$(random_token)" || fail "cannot generate a token (need openssl, od, or python3)"
  fi
fi
printf '%s\n' "$TOKEN" > "$TOKEN_FILE"
chmod 600 "$TOKEN_FILE"
printf 'VOIDSWITCH_AGENT_TOKEN=%s\n' "$TOKEN" > "$ENV_FILE"
chmod 600 "$ENV_FILE"

tmp="$(mktemp)"
trap 'rm -f "${tmp}"' EXIT
url="${BIN_URL}/agent-v${version}/${APP}-${os}-${arch}"
info "downloading ${url}"
download "$url" > "$tmp" || fail "download failed: ${url}"
chmod 0755 "$tmp"
if command -v install >/dev/null 2>&1; then
  install -m 0755 "$tmp" "$BIN"
else
  mv -f "$tmp" "$BIN"
  chmod 0755 "$BIN"
fi

ARGS_PRINT=""
for a in "$@"; do
  ARGS_PRINT="${ARGS_PRINT}$(printf '%q ' "$a")"
done
{
  printf '#!/usr/bin/env bash\n'
  printf "exec '%s'" "$BIN"
  [ -n "$ARGS_PRINT" ] && printf ' %s' "${ARGS_PRINT% }"
  printf '\n'
} > "$RUN_SCRIPT"
chmod 700 "$RUN_SCRIPT"

case "$os" in
  linux)  install_linux_service "$@" ;;
  darwin) install_macos_service "$@" ;;
esac

print_summary "$@"