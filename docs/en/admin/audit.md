# Audit & Secrets

Every administrative action is recorded in the **audit records**, viewable in the **Audit** tab under the **Logs** page (**staff**).

## What is recorded

Each record contains:

- **Actor** — a stable `name#id` label plus the raw subject;
- **Action** — a `resource.verb` string (for example `provider.update`,
  `announcement.update`, `key.reveal`);
- **Scope** — `admin` (admin interface), `self` (a user acting on their own resources), or `system` (background tasks);
- **Target**, **details** (non-secret context), IP, and User Agent.

Sign-ins are recorded too, and the method is distinguished: an interactive Prism login (`auth.login`) versus a **login-token** sign-in (`auth.token_login`, whose detail carries `method: login_token` and the token fingerprint). So when someone enters the dashboard with an emergency login token, the audit trail makes that explicit.

Use the filters (action, scope, actor, target type, IP / User-Agent, and **time range**) and search to narrow down records,
and use "Jump to ID" to locate a specific record. The time range supports quick intervals like the last 1 hour / 24 hours / 7 days / 30 days,
or a custom exact start and end time.

Void-Tokens in request logs are shown as `name#id`, with the creator in small text below; even if the token is later deleted,
this identifying information is retained so the source of the call can be traced.

## Secrets (owner only)

Some actions carry **sensitive context** that must never appear in plaintext records — for example:

- the plaintext of added or removed keys/tokens;
- confidential provider authentication headers;
- **the before and after contents of an edited announcement**.

This information is **stored encrypted at rest** and marked with a "sensitive" indicator.
An owner (or co-owner) can **reveal** one after a secondary confirmation — the reveal action is itself audited,
so there is always a record of who viewed what.

## Retention

Audit records are cleaned up according to the **audit log retention** window in [Settings](/en/admin/settings)
(`0` = keep forever). Owners can also trigger an immediate cleanup.
