# Models catalog

The **Models** page lists every model id available across the platform, one card
per model. It's visible to every signed-in user.

## What a card shows

- The **public id** you call it by (this may be an alias of the upstream id).
- An optional **display name** and **description** set by staff.
- Which **providers** currently serve it, and whether it's **served** right now.
- Whether you're **allowed** to call it (based on your role groups).

## Which models can I call?

- **Staff** (owner / co-owner / admin) can call every model.
- **Members** can call a model if one of their [role groups](/admin/role-groups)
  is permitted for it. Membership is assigned automatically from your team roles
  at sign-in.

If a model you expect is missing, it may not be served by any enabled provider
right now, your role groups may not grant access, or it may be **hidden**
(disabled) by staff — hidden models are not shown to members at all. Ask a
moderator if you think a model should be available.

## Refreshing the catalog

Refreshing the catalog (registering newly-served model ids) is **staff-only**
(admin / co-owner / owner):

- the refresh/sync action on the **Models** page,
- `POST /v1/models/sync`, or
- the OpenCode `/sync-models` command (with a staff member's token).

Members don't need to sync — served models already appear in the list and via
`/v1/models`.

## Calling a model

Use the model's **public id** as the `model` field in your request. See
[Calling the API](/guide/using-the-api).
