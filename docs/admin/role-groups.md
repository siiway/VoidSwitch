# Role groups

A **role group** ("身份组") determines which [models](/admin/models) its members
may call. The **Role Groups** page is **staff-only**.

## How membership works

Membership is **auto-assigned at sign-in** from a user's Prism **team** roles. A
group defines one or more **mappings**, each of the form:

> members of team `T` whose effective role is at least `R` get this group.

Roles rank `owner > co-owner > admin > member`. Auto memberships are recomputed on
every login; a temporary manual removal is re-granted at the next sign-in if a
mapping still matches.

## Create a group

1. Open **Role Groups** → **Add**.
2. Give it a **name** and optional description.
3. Add **mappings**: a team id and the minimum role.
4. Save. Then, on the [Models](/admin/models) page, list this group under the
   models it should unlock.

## The built-in moderator group

The **moderator** group is seeded on first boot, always grants access to every
model, and can't be edited or deleted. Owner / co-owner / admin belong to it
implicitly — that's why staff can always call any model.

## Emergency access removal

From a group's **members** view you can temporarily remove a user to cut their
access to that group's models immediately (useful when you can't disable the
account right away). It's re-granted at their next login if a mapping still
matches — to make it permanent, remove the mapping or disable the account.
