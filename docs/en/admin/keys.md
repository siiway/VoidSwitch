# Upstream Keys

Every provider has a pool of **upstream API keys** that the gateway rotates through.
Manage them from the provider's **Keys** page (**staff-only**).

## Add keys

1. Open **Providers** → select a provider → its **Keys**.
2. Paste one or more keys, **one per line**. Add an inline note after `#`
   (for example `sk-abc… # alice`).
3. Optionally tag the batch with a **pool** (used by model routing) and a **weight**.

## Manage keys

- **Status** — active, invalid, insufficient balance, rate-limited, or disabled.
  The gateway updates these statuses automatically based on upstream responses.
- **Enable / disable**, **edit** note/pool/weight, or **replace** a key.
- **Drag to reorder** to set the order used by "failover" and pinned key-selection modes.
- **Refresh balance** — for providers that support it.
- **Refresh token** — for providers that support refresh tokens (Claude Code, xAI).
  Each key row offers a refresh button; clicking it immediately uses its refresh token to exchange for a new
  access token, rotates and re-encrypts the credential bundle, and resets the key to **active** (clearing the
  failure count and disable reason).
  This operation is recorded in both the [request logs](/en/admin/logs) and the [audit records](/en/admin/audit), along with the executing user's info.
- **Clean up** — bulk-delete failed keys (`invalid` or `insufficient_balance`),
  with an optional minimum-lifetime filter for empty-balance keys.

## Claude Code subscription keys

For `claude-code` providers, you can add keys via **subscription OAuth**: start the login, authorize,
then paste the callback code back. VoidSwitch stores the resulting credential bundle as a key and refreshes it
automatically.

## OpenAI Codex subscription keys

A `codex` provider supports two ChatGPT subscription login methods:

- **Browser login**: after approval the browser redirects to `http://localhost:1455/auth/callback`. A failed-to-load
  page is expected; copy the complete URL from the address bar and paste it into the keys page.
- **Device-code login**: enter the short code on the opened OpenAI page, approve it, then return and click
  **Check approval**.

Both methods store an automatically refreshed OAuth credential.

## Import sub2api / CLIProxyAPI Auth files

For import-capable providers such as `claude-code`, `grok`, and `xai`, you can directly import Auth credentials
exported from [sub2api](https://github.com/Wei-Shaw/sub2api) or
[CLIProxyAPI](https://github.com/router-for-me/CLIProxyAPI) (cpa),
without manually organizing access_token / refresh_token one by one. The credential import panel appears on
these providers' keys pages.

Expand **Import Auth file** on the keys page, then:

1. **Choose files** to upload one or more `.json` / `.jsonl` files, or **paste** the contents directly into the
   text box. Both methods can be used at the same time and will be imported together.
2. Optionally fill in a **pool** tag; the imported keys will be placed in that pool.
3. Click **Import**. When finished, you'll see the imported count, duplicate count, and skipped count.

Supported formats:

- **CLIProxyAPI (cpa)** — a single account JSON from the `auths/` directory, a JSON array of multiple accounts,
  or JSONL with one JSON per line. OAuth accounts are restored to credential bundles (with automatic refresh
  based on expiry), and API Key accounts are imported as static keys.
- **sub2api** — the data file obtained from the backend **export** (containing an `accounts` array), or a single
  account object. Please use the file obtained from the **export** endpoint: credentials returned by the regular
  endpoint are masked and cannot be imported.

Notes:

- VoidSwitch can automatically refresh OAuth credentials for **Claude** and **xAI (Grok)**; OAuth for other
  platforms is imported as static tokens and must be re-imported after expiry.
- **Grok (xAI)** — a single Grok account may have two usable credentials; imports are handled by the following
  priority:
  - If the account contains a **raw SSO Token** (`sso_token` / `ssoToken` / `sso` field, with or without the
    `sso=` prefix), that token is extracted first. Import these credentials into a `grok` provider, because the
    `console.x.ai` adapter uses the SSO cookie. cpa's xai accounts usually contain this token directly.
  - If the account has no SSO and only xAI's **OAuth credentials** (`access_token` / `refresh_token`, for example
    a Grok account where sub2api exports only the `refresh_token`), it is packaged into an OAuth credential bundle
    for import. Import these credentials into an `xai` provider (the official `api.x.ai`), which will refresh them
    automatically when nearing expiry or receiving a 401.
  - Only when an account has neither SSO nor an access/refresh token is the entry skipped.
- Imports are **automatically deduplicated** by key fingerprint; duplicate credentials are skipped rather than
  added again.
- Entries that cannot be recognized or that lack usable credentials are counted as **skipped**.

## Reveal keys (owner-only)

Owners can view the plaintext of stored keys after confirming. Each reveal is recorded in the [audit records](/en/admin/audit).

## Programmatic key management

Owners can enable a **key management API** (a `vsk-…` token) per provider, so that external integrations can
manage *that provider's* keys. Tokens are created, rotated, revealed, and disabled from the provider row;
its Swagger UI is at `/provider-api/docs`.
