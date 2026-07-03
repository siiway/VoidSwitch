# Void-Tokens (administration)

The **Tokens** page lets owners manage client **Void-Tokens** across all users —
not just their own. It's **owner / co-owner only**. (Members manage their own
tokens on [My Tokens](/guide/api-keys).)

## What you can do

- **Mint a token for another user** — useful for service accounts or onboarding.
- **Edit** a token's name, model allow-list, RPM limit, daily quota, and expiry.
- **Enable / disable** a token to instantly cut or restore its access.
- **Rotate** a token's secret (shown once).
- **Delete** a token.
- **Debug mode** — when enabled on a token, its requests record the full
  troubleshooting detail: the outbound URL / method / proxy, the request headers
  and body, the response status / headers / body, and a per-attempt trail across
  the entire failover (every provider, key, and proxy tried, with each upstream's
  status and response). Credential values in headers are masked; nothing else is
  redacted. This capture is opened from the dedicated **debug** button on a
  request row in the [logs](/guide/logs-usage) and is **owner / co-owner only**
  (admins see the normal info only).

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
