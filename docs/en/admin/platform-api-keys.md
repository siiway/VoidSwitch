# Platform API Keys

A **Platform API Key** (`vsapi-…`) is an automation credential reserved for staff
(owner / co-owner / admin). One key drives both surfaces:

| Surface | Address | Purpose |
| --- | --- | --- |
| REST | `/api/v1/**` | HTTP endpoints that mirror the MCP tools one-for-one |
| MCP | `/api/v1/mcp` | MCP Streamable HTTP, for AI agents |

It is fully separate from a [Void-Token](/en/admin/tokens): a Void-Token can only
call the gateway (`/v1`), a Platform API Key can only call the management surface.
Neither works on the other.

## Creating one and choosing scopes

Dashboard → **Platform API Keys** → **Create API key**. The secret is shown once,
together with connect snippets you can copy.

Each key carries a set of **scopes**, written `category.action` (e.g. `model.edit`):

| Scope form | Meaning |
| --- | --- |
| `read` | Every read-only action |
| `model.*` | A whole category |
| `model.edit` | A single action |
| `provider-key:acme.*` | Upstream key management for provider slug `acme` (owner-granted only) |

Actions are named `category.verb` and cover models (`model.*`), model categories
(`category.*`), providers (`provider.list/get/edit/update/delete`), provider keys
(`provider-key.*`), nodes (`node.*`), node groups (`node-group.*`), users
(`user.*`), role groups (`role-group.*`), the platform API keys themselves
(`api-key.*`), request logs (`request-log.*`), audit records (`audit-log.*`),
announcements (`announcement.*`), stats (`stats.get`) and settings (`setting.*`).

`*.edit` **creates**, `*.update` **modifies an existing object** — they are
separate scopes. Nothing but `provider.edit` can only create providers; it cannot
change one that already exists.

**A key's permission is its scopes intersected with what its owner's current role
may grant.** In practice:

- The picker only offers what your role may grant (provider key management and
  provider deletion are owner-only).
- If your role is demoted, scopes beyond the new role stop working immediately —
  no key edit needed.
- Losing staff access disables every key you hold ("disabled — staff access lost").
  **Regaining staff access does not re-enable them**; you must do it yourself.

## Permission boundaries

**Nothing reveals a stored secret.** There is no `*.reveal` action: upstream key
plaintext, audit sensitive payloads and Void-Token secrets are unreachable through
a Platform API Key. The upstream key list omits `key_preview` as well — in the
dashboard that field is the first and last four characters of the credential. A
request log's detailed trail is returned in the redacted staff projection, never
with bodies.

**Staff only.** A non-staff caller is refused (403) even if the key row is still
enabled.

**Some actions stay owner-only and cannot be granted.** These already sit behind
`RequireOwner` in the dashboard, and a Platform API Key keeps that gate: an admin
can neither write them into a key nor reach them through a `*` wildcard.

| Action | Why |
| --- | --- |
| `user.edit` | Changes roles / enabled state (prevents self-escalation) |
| `setting.edit` | Changes global settings |
| `provider.delete` | Deletes a provider |
| `node.delete` | Deletes an egress node |
| `role-group.edit` / `.delete` / `.member.remove` | Role group writes |
| `model.route.clear-cooldown` | Clears an upstream cooldown |
| `provider-key:<slug>.*` | Manages one provider's upstream keys |

An admin's `*` and a category wildcard (`model.*`) both **expand to the concrete
actions the current role may still perform**, so neither can carry an owner-only
entry above; `*` also does not collapse to nothing after a demotion.

`api-key.*` reaches **only the caller's own keys** — another staff member's
credential can neither be read nor modified.

The dashboard shows the **stored** scopes; after a demotion the `in effect` count
shrinks, and that effective set is what `/api/v1`, MCP and `/whoami` enforce.

## Calling it

### MCP client

```json
{
  "mcpServers": {
    "voidswitch": {
      "type": "http",
      "url": "https://voidswitch.example.com/api/v1/mcp",
      "headers": { "Authorization": "Bearer vsapi-…" }
    }
  }
}
```

`tools/list` returns exactly the tools the key's scopes cover; tool names are
`vs_` plus the scope with dots turned into underscores (`model.edit` →
`vs_model_edit`). A tool outside the scopes is not listed at all.

### REST

```bash
curl -s https://voidswitch.example.com/api/v1/whoami \
  -H "Authorization: Bearer vsapi-…"

curl -s https://voidswitch.example.com/api/v1/models \
  -H "Authorization: Bearer vsapi-…"
```

`/whoami` returns the owner, role, effective scopes and the actions the key may
call — the cheapest way to check a key before issuing real requests.

### Python SDK

A client ships in the repository (`sdk/python`):

```python
from voidswitch import Client

vs = Client("https://voidswitch.example.com", api_key="vsapi-…")
for model in vs.models.list():
    print(model["model_id"], model["enabled"])
```

## Two levels of log reading

`request-log.get` returns one request row's projection (identity, status, latency,
token counts); `request-log.get-debug` adds the routing and failover trail. Bodies
inside that trail stay owner-only; other roles receive the redacted projection.

## Rate limit

The platform API is rate-limited **per key**, 20 seconds / 30 requests by
default. Both values are configurable in the **Platform API** group of
[Settings](/en/admin/settings) (`0` = unlimited). Exceeding it returns `429`.

## Audit

Actions taken through a Platform API Key are audited like any other, and the row
additionally records:

- **Credential** — the key's fingerprint (`vsapi-ab12cd…wxyz`);
- `via` in the detail — `rest` or `mcp`.

So "who, with which key, over which protocol, did what" is answerable from a
single row.
