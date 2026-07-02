# Audit & secrets

Every administrative action is recorded in the **audit trail**, viewable on the
**Logs** page under the **Audit** tab (**staff**).

## What's recorded

Each entry captures:

- **actor** — a stable `name#id` label plus the raw subject;
- **action** — a `resource.verb` string (e.g. `provider.update`,
  `announcement.update`, `key.reveal`);
- **scope** — `admin` (management surface), `self` (a user acting on their own
  resources), or `system` (a background task);
- **target**, **detail** (non-secret context), IP, and user agent.

Use the filters (action, scope, actor, target type) and search to narrow the
trail, and "jump to id" to land on a specific entry.

## Secrets (owner-only)

Some actions carry **sensitive context** that must never appear in the plain
trail — for example:

- the plaintext of an added or deleted key / token;
- secret provider auth headers;
- the **before/after content of an edited announcement**.

These are stored **encrypted at rest** and marked with a "sensitive" indicator.
An owner (or co-owner) can **reveal** one behind a secondary confirmation — and
the reveal itself is audited, so there's always a record of who looked.

## Retention

The audit trail is pruned according to the **audit log retention** window in
[Settings](/admin/settings) (`0` = keep forever). Owners can also trigger an
immediate cleanup.
