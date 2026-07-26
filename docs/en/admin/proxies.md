# Proxies

Proxies are optional egress routes the gateway uses to connect to upstream providers.
The **Proxies** page is **staff-only**.

## Add a proxy

1. Open **Proxies**.
2. Paste one or more proxy URLs, **one per line**, for example
   `http://user:pass@host:port` or `socks5://host:port`.
3. Optionally set a **local source IP** (`local_address`), a **weight**, and a note.

## How proxies are used

- A provider's **egress proxy** mode decides whether it uses **all** active proxies, only **selected**
  proxies, or a **direct** connection.
- On a network/timeout error, the scheduler fails over to another proxy, and disables a problematic proxy
  after it exceeds a dynamic failure threshold.
- A background **proxy reviver** periodically re-tests disabled proxies and re-enables those that have
  recovered. Its interval can be adjusted in [Settings](/en/admin/settings).

## Proxy switching turned off

If **proxy switching** is disabled in settings (because an external proxy such as mihomo already handles
egress), the Proxies tab is hidden and every request uses a single **static proxy URL** (or a direct
connection). In this mode, no failover or auto-disable occurs.

The token exchange and refresh for Claude Code subscription OAuth also follow this mode: when the static
proxy URL has a value, that proxy is used; when it is empty, the process environment's
`ALL_PROXY` / `HTTPS_PROXY` / `HTTP_PROXY` is used; only when none are set does it connect directly.
