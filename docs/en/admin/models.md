# Models (Admin)

The **Models** page is visible to everyone, but staff can manage it. See the
[user-facing models guide](/en/guide/models) for the reader's perspective.

## Per-model metadata

For any model ID, staff can set:

- **Display name** and **description**;
- **Public alias** (`mapped_id`) — once set, clients see and must use this ID instead of the original
  upstream ID, hiding the upstream and eliminating ambiguity conflicts;
- Custom **OpenCode config**, which the plugin deep-merges into that model;
- **Enable** — hide the model from `/v1/models` and the selector without deleting it;
- The **role groups** allowed to call it.

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

## Sync and cleanup

There are **two mutually independent** "syncs" here:

- **Sync from providers** (the button on the Models page, `POST /api/models/sync`) adds catalog rows for all
  model IDs currently served by enabled providers, **reshaping the shared catalog**. This is a **staff-only**
  operation; members do not see the button.
- **OpenCode sync** (`POST /v1/models/sync`, i.e. OpenCode's `/sync-models` command) is open to **all members**.
  It does *not* reshape the shared catalog; it merely reports the set of models that token **can currently
  call** (applying role-group access and the token's allow-list, and excluding hidden/disabled models), so the
  plugin can align its own model list with the permissions the user actually holds. So members can sync without
  admin privileges.
- **Clean up unserved** removes model metadata rows that no provider serves anymore (staff-only).

## Hidden models

Unchecking **Available** hides a model (staff see an "Unavailable (hidden)" badge). Members never see hidden
models — not on the Models page, in `/v1/models`, or in the OpenCode selector.
