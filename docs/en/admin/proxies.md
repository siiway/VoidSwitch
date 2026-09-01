# Nodes & Node Groups

**Nodes** are the egress hops the gateway uses to connect to upstream providers. The old "Proxies"
concept was replaced by a **node + node group** system. The **Nodes & Node Groups** page is **staff-only**.

## Node types

Each node has a **type** that determines how it makes its egress connection:

- **direct** — use the gateway process's own network and connect directly.
- **http** — an HTTP forward proxy.
- **socks5** — a SOCKS5 proxy.
- **agent** — a voidswitch-agent relay, authenticated by token.

## Node groups

A **node group** is a freely-created set of nodes that decides which egress paths a request can take.
A group can:

- pick nodes from the global pool, and/or
- **inherit** other groups (a live reference, like Python class inheritance; cycles are resolved safely).

Each group can set its own `probe_url` and `probe_interval_seconds` for idle health checks.

### Dynamic ordering & failover

Nodes within a group are ordered by health/latency:

- The ordering uses **EWMA latency + failure score**, whose weights are adjustable in Settings
  (`node_rank_alpha/beta/gamma`, with a decay half-life `node_rank_ewma_half_life_seconds`).
- Requests walk the ordered list front-to-back and fall back on failure.
- When all nodes fail and retries are exhausted, a connection error is returned.
- Max retries per request (`max_retries`) and the failure threshold before a node is disabled
  (`max_proxy_failures`) are settings.

### Pinned nodes

In a node group's expanded member list, any node can be **pinned**: pinned nodes **always lead the list**
and are ranked independently of the quality score (they are still ordered by score among themselves).
This makes it easy to force certain nodes to be tried first (e.g. a high-quality dedicated line) without
tweaking their latency/failure metrics. The node-group page no longer offers manual drag-to-reorder —
ordering is determined entirely by the dynamic score above (plus pinning).

### Empty group → direct (lockout-proof)

Requests from a node group with **no usable nodes** **degrade to a direct connection**. No matter how
badly a routing setup is configured, it can never lock an operator out — this is by design; the
**System group / login token** protects login.

### The System node group

The **System group** is the one special group among node groups and carries system requests:

- Prism OAuth, models.dev sync, balance probing, and OAuth token refresh.

Only owner / co-owner may edit its nodes. An empty System group → direct (so login / OAuth always works).

### Default node group

Providers with no explicit group use the **default node group**.

## Proxy switching turned off

If **proxy switching** is disabled in settings (`proxy_switching_enabled=false`, because an external proxy
such as mihomo already handles egress), the routing system is off: every request uses a single
**static proxy URL** (`static_proxy_url`, or the `HTTP(S)_PROXY` environment variables, or direct when
none is set). In this mode there is **no failover** and no auto-disabling of nodes. When routing is off,
the Proxies (nodes) tab is hidden from the navigation.

The token exchange and refresh for Claude Code subscription OAuth follow the same mode: when the static
proxy URL has a value, that proxy is used; when it is empty, the process environment's
`ALL_PROXY` / `HTTPS_PROXY` / `HTTP_PROXY` is used; only when none are set does it connect directly.
