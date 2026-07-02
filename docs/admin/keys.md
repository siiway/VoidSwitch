# Upstream keys

Each provider has a pool of **upstream API keys** the gateway rotates through.
Manage them from a provider's **Keys** page (**staff-only**).

## Add keys

1. Open **Providers** → a provider → its **Keys**.
2. Paste one or more keys, **one per line**. Add an inline note after `#`
   (e.g. `sk-abc… # alice`).
3. Optionally tag the batch with a **pool** (used by model routes) and a **weight**.

## Manage keys

- **Status** — active, invalid, insufficient balance, rate-limited, or disabled.
  The gateway updates these automatically based on upstream responses.
- **Enable / disable**, **edit** the note/pool/weight, or **replace** the secret.
- **Drag-sort** to set the order used by the "fallback" and pinned key-select modes.
- **Refresh balance** — for providers that support it.
- **Cleanup** — bulk-delete dead keys (`invalid` or `insufficient_balance`), with
  an optional minimum-age filter for empty keys.

## Claude Code subscription keys

For `claude-code` providers you can add a key via **subscription OAuth**: start
the login, authorize, and paste the code back. VoidSwitch stores the resulting
credential bundle as a key and refreshes it automatically.

## Revealing a key (owner-only)

Owners can reveal a stored key's plaintext behind a confirmation. Every reveal is
recorded in the [audit trail](/admin/audit).

## Programmatic key management

Owners can enable a per-provider **key-management API** (a `vsk-…` token) so an
external integration can manage *that provider's* keys. The token is minted,
rotated, revealed, and disabled from the provider row; its Swagger UI lives at
`/provider-api/docs`.
