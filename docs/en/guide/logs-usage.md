# Logs and usage

VoidSwitch records every request so you can see what happened and how much was used.

## Stats

The **Stats** page shows usage analytics. Members view **their own** traffic; staff view platform-wide totals broken down by user, token, and model,
across day, week, month, and year windows.

In the staff **by user** breakdown, usernames are clickable: clicking one opens a popup with that user's **activity heatmap**
(the same heatmap as at the bottom of the dashboard — daily token usage, cumulative / peak, longest task duration, and streak).

## Logs

The **Logs** page has two views:

- **Requests** — one row per gateway call: time, model, provider, status, latency, token counts, and any error. Members only see their own requests;
  staff see everyone's.
- **Audit** *(staff)* — an administrative record of who changed what.

Use filters to narrow the results, and use the paginator to browse pages:

- **Request** logs can be filtered by **model**, **user**, **token** (all "search + select" dropdowns where you can type a keyword to filter and then select),
  **provider** (a plain dropdown selection), and **status code**. For the status code you can enter a specific number (e.g. `404`),
  or enter just a single digit `2` / `3` / `4` / `5` and blur the field, and it will be auto-completed to `2xx` / `3xx` / `4xx` / `5xx`,
  matching all status codes in that class.
- **Audit** logs can be filtered by **scope**, **action**, **target type**, **actor** (search + select), and **IP** / **User-Agent**
  text. IP and UA are partial matches and support the `*` (matches any characters) and `?` (matches a single character) wildcards,
  e.g. `10.0.*` or `curl/*`.
- Both views support filtering by **time range**: the **Time** dropdown offers quick ranges such as "All time / Last 1 hour / Last 24 hours /
  Last 7 days / Last 30 days"; selecting "Custom" expands two date-time inputs so you can specify the exact start and end moments.
  When you pick a quick range, the current moment is fixed as the window boundary, so the range stays stable across paging or refresh and does not silently drift over time.
- **Click** any value directly in the table (for requests: user / token / model / status; for audit: actor / scope / action / target /
  IP / UA) to fill it into the corresponding filter.
- Text filters (the request status code, and the audit IP / User-Agent) are **debounced** as you type, only issuing a query a moment after you stop typing,
  so filtering-as-you-type is smoother and doesn't refresh on every keystroke. When any filter (including the time range) is active,
  a **Clear filters** button appears on the right of the filter bar to restore the unfiltered state in one click.

Token exchanges for Claude Code subscription OAuth are also counted in the **Requests** log. They are not model inference requests, so the model column shows a special value
such as `<cc-refresh-token>` or `<cc-exchange-token>`; these records usually have no user and no Void-Token.

Every request row has an **info** button (ℹ) that opens its regular details —
time, caller, token, model, provider, key, proxy, status, tokens, and any error.
When a model is routed (aliased to a different upstream ID), the details show the **model route** (e.g. `codex-gpt-5.5 → gpt-5.5`),
making it easy to trace the mapping. Even if a request failed on all providers, the details still show the last attempted provider, key, and route.

### Debug details (owner / co-owner only)

Requests made with a **debug-enabled token** get a second **debug** button (🐞),
visible only to **owner / co-owner**. It opens the full capture: the outbound URL and method, the proxy used, request headers
and body, response status code, response headers and body — plus a **record of each attempt** across the entire failover process
(the provider / key / proxy for each attempt, along with its upstream status and response). This lets you go from a vague "upstream 500"
to pinpointing the specific problem. Credential values in request headers are always masked; nothing else is redacted. Admins can only see the info button,
and never the debug capture.

Even without a **debug-enabled** token, as long as a request **errors** (upstream 4xx / 5xx), that error's
**response headers and body** are force-recorded (but not the request headers / body, and no per-attempt records), so any upstream error is traceable.
This data is also considered debug information: only owner / co-owner can view it via the debug button, and it is cleaned up automatically according to the **debug log retention window**
(`debug_log_retention_days`, see [Settings](/en/admin/settings)).

## What members can see

- Your own request logs and usage.
- Not: other users' traffic, audit records, or debug-level request/response bodies (these are limited to staff/owner).

## Retention

Old logs may be cleaned up automatically according to the retention window configured by the owner (see [Settings](/en/admin/settings)).
If retention is set to `0`, logs are kept indefinitely.

The daily usage rollups that the heatmap relies on are **independent** of request log retention; they are cleaned up separately by the **heatmap data retention days**
(`heatmap_retention_days`), so the heatmap is preserved even if you tighten request log retention. This value defaults to 365 days and
is configurable, but may not be less than 365 days (`0` means keep forever).
