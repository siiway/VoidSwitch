# Model catalog

The **Models** page lists all available model IDs on the platform, one card per model. All logged-in users can view it.

## What a card shows

- The **public ID** you use when calling (which may be an alias of an upstream ID).
- An optional **display name** and **description** set by staff.
- Which **providers** currently serve it, and whether it is **being served**.
- Whether you are **allowed** to call it (based on your role group).

## Search and filter

The top toolbar lets you search by keyword (with an optional choice of which fields to match), and filter by **provider** and **availability**.
Filtering by **role group** is staff-only; members do not see that filter.

## Which models can I call?

- **Staff** (owner / co-owner / admin) can call all models.
- **Members** can call a model if one of their [role groups](/en/admin/role-groups) is allowed to access it. Membership is assigned automatically at login based on your team role.

If a model you expect is missing, it may be that no enabled provider currently serves it, your role group may not have been granted access,
or it may have been **hidden** (disabled) by staff — hidden models are not shown to members at all. If you think a model should be available, ask an admin.

## Refreshing the catalog

**Reshaping the shared catalog** (registering catalog rows for newly served model IDs) is a **staff-only** action
(admin / co-owner / owner), done via the **Sync from providers** button on the **Models** page
(`POST /api/models/sync`). Members do not see that button.

**OpenCode users (including members)** use the `/sync-models` command (`POST /v1/models/sync`)
to have the plugin align its model list with the models they **can currently call** — this step is open to all members, requires no admin
privileges, and does not touch the shared catalog. You only see models you have access to and that are not hidden.

Members usually don't need to sync explicitly — models that are already served and that you have access to already appear in the list and in `/v1/models`.

## Calling a model

Use the model's **public ID** as the `model` field in your request. See [Calling the API](/en/guide/using-the-api).
