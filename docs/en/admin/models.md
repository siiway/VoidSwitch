# Models (Admin)

The **Models** page is visible to everyone, but staff can manage it. See the
[user-facing models guide](/en/guide/models) for the reader's perspective.

## Exposed models

The **Models** page lists **exposed models** (e.g. `fast-coder`, `astr-chat`) — the **only** ids
users/clients ever see. Upstream model ids (e.g. `deepseek/deepseek-chat`) are never advertised.

Each exposed model has a **route flowchart**:

- The top is the **exposed model** itself;
- below it are ordered **layers** (fallback pools);
- each layer is a **pool** of upstream entries (provider + upstream model + weight), with a per-layer
  **max attempts** (`max_attempts`; `1` = pick one, `>1` = try several).

Failures eligible for fallback (429 rate-limit / 404 model-not-found / 5xx) move down the flow / to the
next upstream; a **400** (client error) is returned as-is; a response definitively out of quota disables
that upstream key.

Route flowcharts are edited on a **dedicated page**: top model → layer pools → upstreams.

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

## Bulk edit

Apply the same change to multiple models at once — description, enabled state, allowed role groups, or
OpenCode config.
You can first filter by search, provider, availability status, or role group, then check **Select current
filter results**. After clearing the filter, the selected models stay selected; click **Clear selection** when
you need to start over.
For OpenCode config, choose:

- **Merge** — deep-merge into each model's existing config (nested dicts merge, lists/scalars replace); or
- **Overwrite** — replace entirely.

## Access control

- The built-in **moderator** group (owner/co-owner/admin) can always call all models.
- Other users need one of the [role groups](/en/admin/role-groups) listed on the model.
- Therefore, an empty allow-list means "moderator only".

## Sync from providers

**Sync from providers** (the button on the Models page, `POST /api/models/sync`) ingests the upstream
models currently served by enabled providers and **reshapes the shared catalog**. This is a **staff-only**
operation; members do not see the button.
(OpenCode's `/sync-models` command — `POST /v1/models/sync` — is open to **all members** and aligns the
plugin's list with the exposed models you **can currently call**; it never touches the shared catalog.)

**Clean up unserved** removes metadata rows no longer served by any upstream model (staff-only).

## Hidden models

Unchecking **Available** hides a model (staff see an "Unavailable (hidden)" badge). Members never see hidden
models — not on the Models page, in `/v1/models`, or in the OpenCode selector.
