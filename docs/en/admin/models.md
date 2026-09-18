# Models (Admin)

The **Models** page is visible to everyone, but staff can manage it. See the
[user-facing models guide](/en/guide/models) for the reader's perspective.

## Exposed models

The **Models** page lists **exposed models** (e.g. `fast-coder`, `astr-chat`) — the **only** ids
users/clients ever see. Upstream model ids (e.g. `deepseek/deepseek-chat`) are never advertised.

Each exposed model route directly contains a set of upstream candidates. VoidSwitch dynamically ranks
them from call success rate, time to first token, and consecutive failures instead of using static layers.
Routes can always choose the best upstream, balance among the best candidates, or pin a conversation to
either choice. Weight only affects balancing and score ties.

429, 529, configured 5xx responses, and network errors can cool an upstream down. Cooldowns are shared
platform-wide by provider, upstream model, and key pool, so every exposed model referencing that same
upstream avoids it. Retry-After/provider retry headers take precedence over route, provider, and global
fallback cooldowns. Key rate limiting and upstream cooldown are separate states.
The default **ignore cooldown** policy tries normal candidates first but retains cooled candidates as
last-resort fallbacks. This allows routing to continue when a higher-ranked normal candidate has no
eligible key or outbound node. If a restored cooled candidate only has rate-limited keys, those keys
are also eligible as the final fallback so the request does not fail before any upstream attempt.
A route's max-upstream-attempts budget counts only upstreams that actually send a request: a candidate
skipped because it has no eligible keys, its provider is disabled, or it has no outbound node does not
consume the budget, so one unusable lead candidate cannot fail the whole request early. Skipped
candidates are recorded in the request detail's attempt list for diagnosis.

The Models page receives a recent health summary with its normal catalog request and no longer keeps
an SSE connection open. The dedicated Health page connects live updates automatically; staff see
per-upstream details and node history, while owners can still clear cooldowns from the route page.

## Creating models

Staff can click **Create model** to register a new `model_id` (leave the display name
empty and a placeholder is auto-generated from the `model_id`). Optionally, pick a
**provider + upstream model** to pre-fill the first upstream candidate. A group can be
assigned at creation time (the **Create group** button sits between **Clean up unserved**
and **Create model** at the top of the page).

Groups group models (e.g. "Coding", "Writing"). The **Models** page supports
filtering by group; models without a group are **Ungrouped**. Provider passport-through
models appear under their **provider's name** (not its id/slug) as a virtual group with a
**Provider** badge.

## Provider passthrough models

Passthrough models are served directly by their provider and bypass the routing system, so they
**have no Route button**. To delete one, click its **Delete** button: this removes the model from the
provider's passthrough list and cleans up any residual model metadata.

Passthrough models also support metadata editing and role-group access — both **Edit** and **Access**
buttons are available. Saving either creates an `ExposedModel` row lazily, and the passthrough entry
then participates in the same `/v1/models` rendering and access filtering as regular models. As a
result, a passthrough model without any configured role group is invisible to non-moderators (see
**Access control** below). The passthrough whitelist itself is configured in the **Providers** edit
dialog (the "Model passthrough" switch + "Passthrough models" list).

## Per-exposed-model metadata

For any exposed model, staff can set:

- **Display name** and **description**;
- The structured fields **limit_context / limit_input / limit_output / reasoning /
  capabilities (text/image/audio/tool) / modalities**;
- A custom **OpenCode config** (`opencode_config`);
- **Enable** — hide the model from `/v1/models` and the selector without deleting it;
- The **role groups** allowed to call it.

### models.dev integration

- Search **models.dev** on the Models page and **map** a model onto the exposed model;
- its data is used as **placeholder metadata** (anything you fill in overrides it);
- the sync interval is the `models_dev_sync_interval_minutes` setting (default `1440` = daily);
- endpoints: `/api/models/models-dev/search?q=`, `/api/models/models-dev/sync`.

### Downstream config precedence (OpenCode plugin)

Structured fields **>** custom `opencode_config` **>** models.dev placeholder **>** defaults.

## Bulk edit / delete

Apply the same change to multiple models at once — description, enabled state, allowed role groups,
OpenCode config, capabilities, reasoning, limits, or category.
You can first filter by search, provider, availability status, or role group, then check **Select current
filter results**. After clearing the filter, the selected models stay selected; click **Clear selection** when
you need to start over.
For OpenCode config, choose:

- **Merge** — deep-merge into each model's existing config (nested dicts merge, lists/scalars replace); or
- **Overwrite** — replace entirely.

With a selection you can also **Delete selected**: exposed models leave the catalog; passthrough models
are removed from their provider's whitelist (`POST /api/models/batch-delete`).

## Access control

- The built-in **moderator** group (owner/co-owner/admin) can always call all models.
- Other users need one of the [role groups](/en/admin/role-groups) listed on the model.
- Therefore, an empty allow-list means "moderator only".

## Sync from providers

Previously the Models page had a **Sync from providers** button (`POST /api/models/sync`)
that ingested the upstream models currently served by enabled providers and reshaped the
shared catalog. The button has been removed — use **Create model** to manually expose models.
(OpenCode's `/sync-models` command — `POST /v1/models/sync` — is open to **all members** and
aligns the plugin's list with the exposed models you **can currently call**; it never touches
the shared catalog.)

**Clean up unserved** removes metadata rows no longer served by any upstream model (staff-only).

## Hidden models

Unchecking **Available** hides a model (staff see an "Unavailable (hidden)" badge). Members never see hidden
models — not on the Models page, in `/v1/models`, or in the OpenCode selector.
