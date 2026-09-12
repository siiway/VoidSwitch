# Model catalog

The **Models** page lists all available model IDs on the platform, one card per model. All logged-in users can view it.

## What a card shows

- The **exposed model ID** you use when calling (e.g. `fast-coder`; upstream model IDs are never
  advertised to you).
- An optional **display name** and **description** set by staff.
- A concise live health state — **Healthy / Degraded / Unavailable / Learning** — plus the best
  recent request success rate and average time to first token. The row stays hidden while data is insufficient.
- Regular exposed models use dynamic routing based on recent success, time to first token, and failures.
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

Staff maintain the shared catalog from the **Models** page. Members cannot create, edit, or delete models.

**OpenCode users (including members)** use the `/sync-models` command (`POST /v1/models/sync`)
to have the plugin align its model list with the models they **can currently call** — this step is open to all members, requires no admin
privileges, and does not touch the shared catalog. You only see models you have access to and that are not hidden.

Members usually don't need to sync explicitly — models that are already served and that you have access to already appear in the list and in `/v1/models`.

## Calling a model

Use the model's **exposed model ID** as the `model` field in your request. See [Calling the API](/en/guide/using-the-api).

## Health page

The **Health** page connects live updates automatically. Members only see aggregate health for models
they may call. Staff can switch to Nodes for rank scores, failures, and latency/success trends from
`30m` through `7d`.
