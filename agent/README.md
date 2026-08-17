# voidswitch-agent

A minimal, single-binary outbound **relay** for VoidSwitch. It runs on a clean
overseas IP and accepts token-authenticated outbound traffic from the gateway,
then forwards it to the real upstream — giving you a clean egress, upstream
connection pooling, and a VS-native authenticated transport that avoids the
fingerprinting that plagues generic public HTTP/SOCKS proxies.

- **Custom relay (primary)** — the gateway sends its request with an
  `X-VS-Upstream-URL` header; the agent strips it and forwards over a pooled
  HTTP/2 transport, streaming SSE back.
- **CONNECT mode (fallback)** — `--mode connect` turns the agent into a plain
  HTTP CONNECT forward proxy (token = proxy auth), drop-in compatible.
- High concurrency, low footprint: a Go static binary (~6–10 MB), HTTP/2
  multiplexing, goroutine-per-stream, pooled upstream connections.

## Quick start

```bash
# 1. download the binary (or use Docker / your package manager)
curl -fsSL https://…/install.sh | sh          # auto: arch, token, systemd unit
#    or run directly:
./voidswitch-agent --token "$(openssl rand -hex 24)"

# 2. add it as a Node in VoidSwitch (type = agent, token = the above)
```

The install script writes a systemd unit and prints the address + token to paste
into the VoidSwitch **Nodes** page.

### Docker

```bash
docker run -d --name vs-agent -p 8443:8443 \
  -e VOIDSWITCH_AGENT_TOKEN=$(openssl rand -hex 24) \
  ghcr.io/siiway/voidswitch-agent
```

## Configuration

Flags, environment variables, then defaults (flag wins). All options:

| Flag | Env | Default | Meaning |
| --- | --- | --- | --- |
| `--listen` | `VOIDSWITCH_AGENT_LISTEN` | `:8443` | listen address |
| `--token` | `VOIDSWITCH_AGENT_TOKEN` | *(required)* | preshared auth token |
| `--tls-cert` / `--tls-key` | `…_TLS_CERT` / `…_TLS_KEY` | *(empty)* | TLS cert/key. Empty = plain HTTP (terminate TLS at Caddy/nginx in front). |
| `--mode` | `…_MODE` | `relay` | `relay` (X-VS-Upstream-URL) or `connect` (CONNECT proxy) |
| `--upstream-proxy` | `…_UPSTREAM_PROXY` | *(empty)* | chain egress through another http/socks proxy |
| `--bind-address` | `…_BIND_ADDRESS` | *(empty)* | bind outbound sockets to a source IP |
| `--allowlist-ips` | `…_ALLOWLIST_IPS` | *(empty)* | comma-separated CIDR allowlist of callers |
| `--idle-timeout` | `…_IDLE_TIMEOUT` | `120` | idle / stream seconds |
| `--max-streams` | `…_MAX_STREAMS` | `0` | max concurrent H2 streams (0 = server default) |
| `--dial-timeout` | `…_DIAL_TIMEOUT` | `15` | outbound dial seconds |
| `--log-level` | `…_LOG_LEVEL` | `info` | debug / info / warn / error |
| `--metrics-path` | `…_METRICS_PATH` | `/metrics` | Prometheus-style metrics endpoint |

## Endpoints

- `GET /healthz` — liveness (no auth).
- `GET /metrics` — request/byte/stream/auth counters (token-authenticated).
- Relay: any `POST/GET/…` to `/` with `Authorization: Bearer <token>` plus
  `X-VS-Upstream-URL: https://host/path`. Hop-by-hop headers and the token are
  stripped before forwarding.

## Integration with VoidSwitch

In the VoidSwitch **Nodes & Groups** page, add an **agent** node:

- **URL**: the agent's address, e.g. `https://agent.example.com:8443`.
- **Token**: the preshared token (stored encrypted; owner-only reveal).

Requests that route through this node are sent to the agent using the custom
relay protocol. The node participates in node-group health checks normally (the
gateway probes it). See `docs/admin/proxies.md` (节点与节点组) for the full
routing story.

## Build

```bash
# cross-compile a static binary
CGO_ENABLED=0 go build -trimpath -o voidswitch-agent ./cmd/voidswitch-agent
```

Requires Go ≥ 1.23. The Dockerfile is a multi-stage scratch build.

## Security

- Constant-time token comparison; optional CIDR allowlist.
- The token is never forwarded to upstreams.
- Request bodies are not logged (only method / host / status / duration).
