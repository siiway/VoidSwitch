# Models (administration)

The **Models** page is visible to everyone, but staff can curate it. See the
[user-facing Models guide](/guide/models) for the reader's view.

## Per-model metadata

For any model id, staff can set:

- a **display name** and **description**;
- a **public alias** (`mapped_id`) — when set, clients see and must call this id
  instead of the raw upstream id, hiding the upstream and disambiguating clashes;
- a custom **OpenCode config** that the plugin deep-merges into that model;
- **enabled** — hide a model from `/v1/models` and the picker without removing it;
- the **role groups** allowed to call it.

## Batch edits

Apply the same change to many models at once — description, enabled state,
allowed role groups, or OpenCode config. For the OpenCode config choose:

- **merge** — deep-merge into each model's existing config (nested dicts combined,
  lists/scalars replaced); or
- **overwrite** — replace it wholesale.

## Access control

- The built-in **moderator** group (owner/co-owner/admin) can always call every
  model.
- Other users need a [role group](/admin/role-groups) that the model lists.
- An empty allow-list therefore means "moderators only".

## Syncing & cleanup

- **Sync from providers** adds catalog rows for every model id the enabled
  providers currently serve. Staff-only (`/api/models/sync`, `/v1/models/sync`,
  or the OpenCode `/sync-models` command) — members can't reshape the shared
  catalog.
- **Clean unserved** removes metadata rows for models no provider serves anymore.

## Hidden models

Unchecking **Available** hides a model (it shows an "Unavailable (hidden)" badge
for staff). Members never see hidden models — not on the Models page, in
`/v1/models`, or the OpenCode picker.
