# Void-Token (Admin)

The **Tokens** page lets owners manage client **Void-Tokens** across all users —
not just their own. It is **owner / co-owner only**. (Members manage their own tokens on [My Tokens](/en/guide/api-keys).)

## What you can do

- **Create tokens for other users** — useful for service accounts or onboarding.
- **Rename / edit** a token's name, model whitelist, RPM limit, daily quota, and expiration.
- **Enable / disable** a token to immediately cut off or restore its access.
- **Rotate** a token's key (shown only once).
- **Delete** a token. A deleted token is invalidated immediately; the system still retains the token ID, name, and creator for display in request logs and audit records.
- **Debug mode** — once enabled on a token, its requests record full troubleshooting details:
  outbound URL / method / proxy, request headers, request body, response status code / response headers / response body,
  as well as a record of every attempt throughout the failover process (the provider, key, and proxy for each attempt,
  plus each upstream's status and response). Credential values in request headers are masked; nothing else is redacted.
  This capture is opened from a dedicated **Debug** button on the request row in the [Logs](/en/guide/logs-usage),
  and is **owner / co-owner only** (admins can only see the regular information).

## Token field recap

| Field | What it does |
| ----- | ------ |
| Allowed models | Empty = all allowed models; otherwise a strict whitelist. |
| RPM limit | Maximum requests per minute (0 = unlimited). |
| Daily quota | Maximum requests per day (0 = unlimited). |
| Expiration | The token stops working after this time. |

Every create, edit, rotate, and delete is recorded in the [audit records](/en/admin/audit).

## Reveal lookup (owner only)

The reveal entry in the top-right corner of the page lets you enter a key and look up matches within Void-Tokens, upstream keys, or all scopes.
A Void-Token shows its name, ID, owner, request count, token usage, enabled state, and creation time; results can link through to the corresponding request log or audit record filtered view.
