# Proxies

Proxies are optional egress routes the gateway uses to reach upstream providers.
The **Proxies** page is **staff-only**.

## Add proxies

1. Open **Proxies**.
2. Paste one or more proxy URLs, **one per line**, e.g.
   `http://user:pass@host:port` or `socks5://host:port`.
3. Optionally set a **local source IP** (`local_address`), **weight**, and note.

## How proxies are used

- A provider's **outbound proxy** mode decides whether it uses **all** active
  proxies, only **selected** ones, or connects **directly**.
- On a network/timeout error the dispatcher fails over to another proxy and, past
  a dynamic failure threshold, disables the bad one.
- A background **proxy resurrector** periodically re-tests disabled proxies and
  re-enables those that recover. Its interval is tunable in
  [Settings](/admin/settings).

## Proxy switching off

If **proxy switching** is disabled in Settings (because an external proxy such as
mihomo already handles egress), the Proxies tab is hidden and every request uses
the single **static proxy URL** (or a direct connection). No failover or
auto-disable happens in this mode.
