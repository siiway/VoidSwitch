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
pages. Click a request to see its full detail.

## What members can see

- Your own request logs and usage.
- Not: other users' traffic, the audit trail, or debug-level request/response
  bodies (those are staff/owner-only).

## Retention

Old logs may be pruned automatically based on retention windows configured by
owners (see [Settings](/admin/settings)). If retention is set to `0`, logs are
kept indefinitely.
