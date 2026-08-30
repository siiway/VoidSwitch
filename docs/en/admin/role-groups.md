# Role Groups

A **role group** carries two orthogonal capabilities:

- **Membership** — determines which [models](/en/admin/models) its members can call.
- **Adminship** — grants a **read-only observer** view: see the group's users, statistics, and logs. Does **not** grant model access.

The **Role Groups** page is visible to owner / co-owner / admin, but **only owner / co-owner may edit**; a platform admin gets a read-only view over the list and members.

## How membership and adminship work

Both are **assigned automatically at login from the user's Prism team roles**. Each group defines one or more **mappings** in the form:

> Members of team `T` with an effective role of at least `R` are granted this group's **`grants`** capability.

`grants` takes one of two values:

- `member` — regular membership (model call access).
- `admin` — adminship (read-only observer view).

Roles are ordered `owner > co-owner > admin > member`. **Adminship does not imply membership** — to grant both, add **two** mapping rows for the same (team, min_role) pair, one `as Member` and one `as Admin`.

Automatic memberships and adminships are recomputed on every login; a temporary manual removal is re-granted on the next login if the mapping still matches. Manual (`source="manual"`) rows are not touched by the auto sync.

## Creating a group

1. Open **Role Groups** → **Add** (visible only to owner / co-owner).
2. Give it a name and an optional description.
3. Add mappings: team ID, minimum role, and `as Member / Admin`.
   > A standing hint at the top of the mapping editor reminds you that admin mappings do NOT grant model access.
4. Save. Then on the [Models](/en/admin/models) page, list this group under the models it should unlock.

## The role-group admin view

A **role-group admin** (who need not be a platform moderator) sees **Users / Statistics / Logs / Audit** in the sidebar, but the content is **scoped to the members of the groups they administer**:

- **Users** — only lists those groups' members. An info bar above the search box says "You administer A, B — this list shows only their members"; a dropdown lets an admin who manages more than one group narrow the view. The platform role column is hidden (only the Prism team role is shown), and roles can't be edited nor accounts enabled/disabled. **Force-logout** is allowed for the group's non-staff members (never for staff or another admin of a shared group).
- **Statistics** — the `/api/usage` data is scoped to the managed groups' members. Same info bar and group selector.
- **Logs / Audit** — request logs are limited to the group's users; audit logs to entries whose `target=user` (a group member) or `target=role_group` (a managed group). Request-log detail exposes headers and per-attempt debug trails, but **not request/response bodies** — those remain owner / co-owner only. All `reveal` actions stay owner-only.

::: warning
**A role-group admin is a read-only role** (with force-logout as the sole write action). They can't edit role groups, modify users, or reveal any secret or plaintext Void-Token.
:::

## Call rate limits

Every role group carries its own **call rate limit**: "at most X requests within N seconds"
for its members on the OpenAI / Anthropic gateway endpoints
(`/v1/chat/completions`, `/v1/messages`). New groups default to 30 requests per 30s;
setting the max requests to `0` disables the limit for that group. Limits are still
**counted per user**: a member of several groups passes while any of them (that is allowed
to call the model) still has budget.

Edit a group's limit in its edit dialog. The built-in **moderator** group can't be renamed
or remapped, but its limit can be adjusted (default 50 requests per 30s).

::: tip
The dashboard's mutating-action limit (add/edit/delete/save) is fixed (30 requests per 20s)
and is not configured here.
:::

## The built-in moderator group

The **moderator** group is created on first startup, always grants access to all models, and cannot be renamed or deleted
(but its call rate limit can be adjusted).
Owner / co-owner / admin belong to it implicitly — this is why staff can always call any model.

The built-in group **does not accept** `grants="admin"` mappings — its administrative power comes from the platform role itself and needs no additional grant.

## Emergency access removal

From a group's **Members** view, owner / co-owner can temporarily remove a user to immediately cut off their access to that group's models
(useful when you can't disable the account right away). If the mapping still matches, it will be re-granted on the next login —
to make it permanent, remove the mapping or disable the account.
