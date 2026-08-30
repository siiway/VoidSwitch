# Role Groups

A **role group** determines which [models](/en/admin/models) its members can call.
The **Role Groups** page is **staff-only**.

## How membership works

Membership is **assigned automatically at login based on the user's Prism team roles**.
A group defines one or more **mappings**, each in the form:

> Members of team `T` with an effective role of at least `R` are granted this group.

Roles are ordered `owner > co-owner > admin > member`. Automatic membership is recomputed on every login;
a temporary manual removal made while the mapping still matches will be re-granted on the next login.

## Creating a group

1. Open **Role Groups** → **Add**.
2. Give it a name and an optional description.
3. Add a **mapping**: a team ID and a minimum role.
4. Save. Then on the [Models](/en/admin/models) page, list this group under the models it should unlock.

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

## Emergency access removal

From a group's **Members** view, you can temporarily remove a user to immediately cut off their access to that group's models
(useful when you can't disable the account right away). If the mapping still matches, it will be re-granted on the next login —
to make it permanent, remove the mapping or disable the account.
