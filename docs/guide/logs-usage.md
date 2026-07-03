# Logs & usage

VoidSwitch records every request so you can see what happened and how much you've
used.

## Statistics

The **Statistics** page shows usage analytics. Members see **their own** traffic;
staff see platform-wide totals broken down by user, token, and model, over daily,
weekly, monthly, and yearly windows.

## Logs

The **Logs** page has two views:

- **Requests** — one row per gateway call: time, model, provider, status,
  latency, token counts, and any error. Members see only their own requests;
  staff see everyone's.
- **Audit** *(staff)* — the administrative trail of who changed what.

Use the search box and filters to narrow results, and the pager to move through
pages.

Each request row has an **info** button (ℹ) that opens its normal detail —
time, caller, token, model, provider, key, proxy, status, tokens, and any error.
When a model was routed (an alias to a different upstream id), the detail shows
the **model route** (e.g. `codex-gpt-5.5 → gpt-5.5`) so the mapping is easy to
trace. Even a request that failed over every provider still names the provider,
key, and route it last tried.

### Debug detail (owner / co-owner)

Requests made with a **debug-enabled token** get a second **debug** button (🐞),
visible to **owner / co-owner only**. It opens the full capture: the outbound
URL and method, the proxy used, the request headers and body, the response
status, headers, and body — plus a **per-attempt trail** across the whole
failover (each provider / key / proxy tried, with its upstream status and
response). This is what turns a bare "upstream 500" into something you can
pinpoint. Credential values in headers are always masked; nothing else is
redacted. Admins see only the info button and never the debug capture.

## What members can see

- Your own request logs and usage.
- Not: other users' traffic, the audit trail, or debug-level request/response
  bodies (those are staff/owner-only).

## Retention

Old logs may be pruned automatically based on retention windows configured by
owners (see [Settings](/admin/settings)). If retention is set to `0`, logs are
kept indefinitely.
