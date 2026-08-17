# Providers

A **provider** is an upstream LLM platform (OpenAI, Anthropic, DeepSeek, and many presets).
The **Providers** page is **staff-only**.

## Add a provider

1. Open **Providers** → **Add provider**.
2. Choose an **adapter type**. A preset fills in a sensible Base URL and default model list; a generic
   OpenAI-compatible catch-all is also available. See the [provider catalog](/en/admin/provider-catalog) for all built-in adapters and their support status.
3. Set the **name**, **Base URL**, and the **models** it serves (one per line; `*` matches anything).
4. Save, then load its [keys](/en/admin/keys).

::: tip OpenAI Responses API
For upstreams that use OpenAI's newer
[Responses API](https://developers.openai.com/api/reference/resources/responses)
(`POST /v1/responses`) instead of Chat Completions, choose the **`openai-resp`** adapter.
The gateway transparently converts inbound OpenAI-chat / Anthropic requests into the Responses format
(and converts replies back), so callers do not need to change anything.
:::

::: tip Grok (console.x.ai free models)
- The **`xai`** adapter talks to the official `api.x.ai` REST API. The key can be a standard API Key
  or an xAI **OAuth credential bundle** (containing `access_token` / `refresh_token`).
  When the bundle nears expiry, is missing an access token, or receives a 401, it automatically uses
  the `refresh_token` to exchange for a new access token at `https://auth.x.ai/oauth2/token`
  (the grok-cli client), and writes the rotated bundle back to the key. As a result, Grok accounts
  imported from sub2api that contain only a `refresh_token` also work directly on an `xai` provider.
- The **`grok`** adapter talks to the `console.x.ai` web backend (see
  [grok2api](https://github.com/jiujiu532/grok2api)); the key is an **SSO Token** —
  the value of the browser `sso` cookie after logging in to console.x.ai (with or without the `sso=`
  prefix). It reuses the Responses API conversion, so inbound OpenAI-chat / Anthropic requests likewise
  need no changes.

The exposed model names carry a reasoning-effort suffix, for example `grok-4.3-console` / `-low` / `-medium` /
`-high`, `grok-4.20-multi-agent-console` / `-low` / `-medium` / `-high` / `-xhigh`,
`grok-4.20-0309-console`, `grok-build-console`, and so on. The gateway automatically maps them to the real console model
and injects the reasoning effort and web search tool. If the upstream requires a `cf_clearance`, append it in
**Extra headers** as `Cookie: cf_clearance=...` (it is concatenated after the SSO cookie rather than
overwriting it). An expired SSO Token is recognized as an invalid key (401/403), and anonymous quota
exhaustion (429) triggers a rate-limit cooldown.
:::

## Key settings

- **Priority / weight** — lower priority takes precedence; weight distributes load among providers of
  equal priority.
- **Model mapping / routing** — remap inbound model IDs to upstream IDs, optionally pinned to a specific
  key **pool** (for example, routing a `-lkd` alias to "leaked" keys).
- **Key selection** — how a key is chosen per request: round-robin, random, failover, or a session-pinned
  mode. All modes fail over to the remaining keys.
- **Node group** — which [node group](/en/admin/proxies) this provider's upstream requests use; empty = the **default node group**.
- **Slug** — the provider's stable internal id. Upstream model IDs are applied as `slug/model` (this id is never advertised).
- **Rate-limit cooldown** — how long a 429'd key waits before being retried when the upstream sends no
  `Retry-After`.
- **Auto-retry on 200 OK + 0 tokens** — for flaky upstreams: a **200 response with zero tokens**
  (or a stream that ends before producing any real content) is treated as a transient fault and retried
  through the failover machinery (next key / route / provider); the empty reply is **never** delivered.
  Streamed responses are spooled until the first real content token before being forwarded, so an empty
  reply is retried in-flight on the same connection; normal generations stream live the moment content
  arrives. If every attempt is empty, the client gets an upstream error.
- **Extra headers** — custom authentication headers. These may contain secrets, so they are treated as
  sensitive and are owner-only in audit records.

## Balance and health

Adapter providers that support balance queries show a **Balance** column and a "Refresh balance" action.
A background probe quickly retires empty-balance keys, and a rescan re-enables keys that have been topped up.

## Reveal lookup (owner-only)

The reveal entry point in the top-right of the Providers page lets you enter a key and find matches within
provider keys, Void-Token, or all scopes. When a provider key matches, it shows the owning provider, the
key's index, note, pool, and who added it. This operation is written to the audit records.

## Deletion

Deleting a provider (and all of its keys) is an **owner-only** operation.

::: tip Members cannot see this page
Providers are entirely hidden from members, and the provider/key APIs reject non-staff requests.
:::
