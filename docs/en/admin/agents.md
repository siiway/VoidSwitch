# voidswitch-agent (VS-native relay)

When your VoidSwitch needs to reach overseas AI services, generic HTTP/SOCKS
forward-proxy protocols are often flagged or blocked. **voidswitch-agent** is a
lightweight, VoidSwitch-specific relay: run it on a clean overseas IP, and it
accepts token-authenticated outbound traffic from the gateway and forwards it to
the real upstream.

- High concurrency, low footprint: a Go static binary (~6–10 MB), HTTP/2
  multiplexing, goroutine-per-stream, shared upstream connection pool.
- Dedicated auth: one preshared token per instance (generated at install), not
  an open proxy — less likely to be abused or flagged.
- Path optimisation: upstream connection pool + keep-alive/H2 (lower time to
  first byte), optional source-IP binding, SNI / chained-proxy egress policies.

## How it works

```
VoidSwitch  ──(token auth + X-VS-Upstream-URL)──►  agent  ──►  upstream AI
```

- **relay mode (default, primary)**: the gateway sends its outbound request plus
  an `X-VS-Upstream-URL` target header to the agent; the agent strips it, drops
  hop-by-hop headers and the token, forwards over a shared HTTP/2 transport, and
  streams the response back (SSE-safe).
- **connect mode (fallback)**: `--mode connect` turns the agent into a plain
  HTTP CONNECT forward proxy (token as proxy auth), drop-in compatible.

## Install (three ways)

**One: one-line installer (recommended)**

```bash
curl -fsSL https://…/install.sh | sh
```

The script detects the architecture, downloads the binary, generates a random
token, writes a systemd unit, and prints the connection info (address + token)
to paste into the VoidSwitch Nodes page.

**Two: Docker**

```bash
docker run -d --name vs-agent -p 8443:8443 \
  -e VOIDSWITCH_AGENT_TOKEN=$(openssl rand -hex 24) \
  ghcr.io/siiway/voidswitch-agent
```

**Three: manual**

```bash
./voidswitch-agent --token "$(openssl rand -hex 24)"
```

## Configuration

See `agent/README.md`. Common options:

| Option | Env | Default | Meaning |
| --- | --- | --- | --- |
| `--listen` | `VOIDSWITCH_AGENT_LISTEN` | `:8443` | listen address |
| `--token` | `VOIDSWITCH_AGENT_TOKEN` | required | preshared token |
| `--tls-cert`/`--tls-key` | `…_TLS_CERT`/`…_TLS_KEY` | empty | TLS cert/key. Empty = plain HTTP (terminate TLS at Caddy/nginx in front) |
| `--mode` | `…_MODE` | `relay` | `relay` or `connect` |
| `--upstream-proxy` | `…_UPSTREAM_PROXY` | empty | chain egress through another proxy |
| `--bind-address` | `…_BIND_ADDRESS` | empty | bind outbound to a source IP |
| `--allowlist-ips` | `…_ALLOWLIST_IPS` | empty | CIDR allowlist of callers |

## Wire up VoidSwitch

On the VoidSwitch **Nodes & Groups** page, add an **agent** node:

- **URL**: the agent address, e.g. `https://agent.example.com:8443`
- **Token**: the preshared token (stored encrypted; owner-only reveal)

Requests routed through this node use the custom relay protocol. The node
participates in node-group health checks and dynamic ordering as usual. See
[Nodes & Node Groups](./proxies.md) for the full routing story.

## Security

- Constant-time token comparison; optional CIDR allowlist.
- The token is never forwarded to upstreams.
- Request bodies are not logged — only method / host / status / duration.
