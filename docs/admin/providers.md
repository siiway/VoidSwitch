# Providers

A **provider** is an upstream LLM platform (OpenAI, Anthropic, DeepSeek, and many
presets). The **Providers** page is **staff-only**.

## Add a provider

1. Open **Providers** → **Add provider**.
2. Choose an **adapter type**. Presets fill in a sensible base URL and default
   model list; a generic OpenAI-compatible catch-all is available too.
3. Set the **name**, **base URL**, and the **models** it serves (one per line;
   `*` matches anything).
4. Save, then load its [keys](/admin/keys).

## Key settings

- **Priority / weight** — lower priority is preferred; weight spreads load among
  providers of equal priority.
- **Model map / routes** — remap an inbound model id to an upstream id, optionally
  pinned to a specific key **pool** (e.g. route `-lkd` aliases onto "leaked" keys).
- **Key selection** — how a key is chosen per request: round-robin, random,
  fallback, or per-session pinned modes. All modes fail over to remaining keys.
- **Outbound proxy** — all active proxies, direct only, or a selected set. See
  [Proxies](/admin/proxies).
- **Rate-limit cooldown** — how long a 429'd key waits before retry when the
  upstream sends no `Retry-After`.
- **Extra headers** — custom auth headers. These may contain secrets, so they're
  treated as sensitive and kept owner-only in the audit trail.

## Balance & health

Providers whose adapter supports it show a **balance** column and a "refresh
balances" action. A background probe fast-fails empty keys, and a rescan
re-enables keys that were topped up.

## Deleting

Deleting a provider (and all its keys) is an **owner-only** action.

::: tip Members can't see this
Providers are hidden from members entirely, and the provider/key APIs reject
non-staff requests.
:::
