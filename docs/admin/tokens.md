# Void-Tokens (administration)

The **Tokens** page lets owners manage client **Void-Tokens** across all users —
not just their own. It's **owner / co-owner only**. (Members manage their own
tokens on [My API Key](/guide/api-keys).)

## What you can do

- **Mint a token for another user** — useful for service accounts or onboarding.
- **Edit** a token's name, model allow-list, RPM limit, daily quota, and expiry.
- **Enable / disable** a token to instantly cut or restore its access.
- **Rotate** a token's secret (shown once).
- **Delete** a token.
- **Debug mode** — when enabled on a token, its requests record full
  request/response detail for troubleshooting. This detail is sensitive and only
  visible to owners in the [logs](/guide/logs-usage).

## Token fields recap

| Field | Effect |
| ----- | ------ |
| Allowed models | Empty = all permitted models; otherwise a strict allow-list. |
| RPM limit | Max requests per minute (0 = unlimited). |
| Daily quota | Max requests per day (0 = unlimited). |
| Expiry | Token stops working after this time. |

Every mint, edit, rotate, and delete is recorded in the
[audit trail](/admin/audit); the plaintext secret is kept as an owner-revealable
secret so a lost token can be recovered.
