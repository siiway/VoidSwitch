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
- **New API error detection** — for providers that reach model services through New API or a similar
  relay. The relay remains an ordinary provider; you do not, and cannot, configure a separate "origin
  provider," origin key, or origin route in VoidSwitch. The three modes are **Auto** (default), which
  enables detection only when the current response has a non-empty `X-New-Api-Version` header;
  **Enabled**, which enables it regardless of that header; and **Disabled**, which never enables it.
  Auto-detection is performed per response and does not remember earlier results or infer the service
  from request IDs, Server headers, or response bodies.
- **Repeat request after a protected error** — optional and off by default. After a protection policy
  matches, retry the same provider, upstream model, key, and request content once before moving to the
  next route-upstream candidate. This can cause **duplicate generation or duplicate billing**, so enable
  it only when that risk is acceptable. The repeat also consumes the provider-attempt budget.
- **Selective-ignore rules** — match specific HTTP statuses and/or error-body text in order and apply
  protected handling to the first matching rule. Rules work for every provider independently of New API
  mode. See the full matching semantics and examples below.
- **Extra headers** — custom authentication headers. These may contain secrets, so they are treated as
  sensitive and are owner-only in audit records.

## Relay error protection

When New API detection is active, VoidSwitch reads the non-empty string `error.type` from a structured
error response:

- `new_api_error` means the error belongs to the New API relay, so normal status-based handling remains
  in effect. For example, New API's own 401/403 can disable the relay key, 402 can mark it as out of
  balance, and 429 can put it into key rate-limit cooldown.
- Any other non-empty `error.type` means the error belongs to the origin model service. Origin
  **401, 402, 403, and 429** responses are protected: they do not disable the relay key, mark it as out
  of balance, put it into key cooldown, or increase its failure count. The failure still counts toward
  route-upstream health and can trigger upstream cooldown under the existing cooldown-status settings.
- A non-JSON body, a missing/blank/non-string `error.type`, or a malformed error object has unknown
  provenance and retains the adapter's normal handling. Other origin statuses also retain normal
  handling unless a selective-ignore rule matches.

This feature improves error attribution only. It does not automatically restore keys that were already
disabled or marked as out of balance; operators must inspect and restore those keys manually.

### Selective-ignore rules

Every rule needs a name and at least one condition:

- **Status codes** accept individual values and inclusive ranges, such as `400-403, 409, 451`.
- **Body substrings** may contain multiple values; any one can match (**OR**). Matching is a
  case-insensitive literal-text search, not a regular expression. For JSON responses, all nested string
  values are inspected (keys are not); for non-JSON responses, decoded text is inspected.
- When both status and body conditions are present, both must match (**AND**). Rules are checked in UI
  order, and the first enabled match wins; disabled rules are skipped. Body matching examines at most
  the first 64 KiB of aggregate UTF-8 text.

For example, a rule named `Temporary content screening` with statuses `400-403` and body substrings
`content policy` and `safety system` matches only when the status is from 400 through 403 and the body
contains either substring. To protect any status containing `upstream overloaded`, leave statuses empty
and enter only that body substring.

Custom rules take priority over New API provenance detection. A match leaves key state unchanged,
records a route-upstream failure, applies the existing cooldown policy, and moves directly to the next
route-upstream candidate—or first repeats the identical request once when **Repeat request after a
protected error** is enabled. A policy match alone never rotates to another key within the same
route-upstream candidate.

::: warning Streaming limitation
When a `stream=true` request receives a non-2xx error before SSE begins, the error body is still buffered,
so rule matching, protection, and failover can run. Once the upstream has returned HTTP 200 and the SSE
stream has begun, VoidSwitch does not inspect later in-stream errors and never retries after downstream
headers or any stream bytes have been committed.
:::

If protected failover exhausts every candidate, the client receives the **last upstream HTTP status and
body** (using the existing error-format conversion when protocols differ), rather than a generic 502
solely because the error was protected.

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
