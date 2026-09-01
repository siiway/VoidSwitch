# Admin Overview

This section is for **staff** — the owners, co-owners, and admins who operate the platform.
If you are a member, the [guide](/en/guide/introduction) covers everything you need.

## Permission tiers

VoidSwitch enforces four tiers on the backend and reflects them in the UI. The
ladder, low to high: `member < role-group admin < staff < owner`.

| Tier | Roles | Scope |
| ---- | ----- | ----- |
| **Member** | member | Only their own resources (their own tokens, their own logs/usage). |
| **Role-group admin** | Derived from a [role group](/en/admin/role-groups) `grants="admin"` mapping | Read-only observer: sees only the users, stats, logs, and audit trail of the **groups they administer**. Not a platform role, and does not grant model access. |
| **Staff** | owner, co-owner, admin | Day-to-day admin surfaces: providers, keys, nodes / node groups, models, role groups (**read-only**, owner-only for edits), user list, logs, settings, and publishing announcements. |
| **Owner** | owner, co-owner | Sensitive operations on top of staff. |

### Owner-only (sensitive) operations

Reserved for owners and co-owners:

- Disabling users and toggling the global Void-Token;
- Deleting providers and managing the per-provider key management API;
- Revealing audit secrets (plaintext keys, tokens, announcement edit history);
- **Creating / editing / deleting role groups** (including temporary member removal);
- **Viewing request / response bodies in request logs** (headers and debug attempts are visible to admin & role-group admin too);
- **Editing** system settings and running **"Clean logs now"** (admins can only *view* the read-only settings).

## Where roles come from

Platform tiers are derived from a user's role in the **main team**
they configured on Prism (`main_team_id`): the team's **owner → owner**, **co-owner → co-owner**,
**admin → admin**. This is the *only* source from which tiers are drawn from Prism — Prism's
**instance / site-wide** admins are **not** trusted (being a Prism system admin does not make you a
VoidSwitch admin), and other teams never grant tiers (they can still grant [role groups](/en/admin/role-groups) for model access).

- **Owner / co-owner** come from the main team's owner/co-owner roles, or from an explicit
  `owner_subs` / `owner_emails` grant (or first-user bootstrap). They cannot be assigned from the dashboard.
- **Admin** comes from the main team's `admin` role, or can be granted locally by an owner on the
  [Users](/en/admin/users) page ("local admin override").
- **Member** is the default role for any other user with platform access.

## Admin pages

| Page | Tier | Function |
| ---- | ---- | ----------- |
| [Providers](/en/admin/providers) | Staff | Add upstream platforms and their models. |
| [Upstream keys](/en/admin/keys) | Staff | Load and manage each provider's API keys. |
| [Nodes & Node Groups](/en/admin/proxies) | Staff | Configure egress nodes and node groups. |
| [Models](/en/admin/models) | Staff | Manage the model catalog and access. |
| [Role groups](/en/admin/role-groups) | Staff (read-only) / Owner | Map team roles to model access, or to role-group adminship. |
| [Users](/en/admin/users) | Staff/Owner | View users; grant admin / disable (owner). |
| [Void-Token](/en/admin/tokens) | Owner | Manage client tokens across users. |
| [Settings](/en/admin/settings) | Staff/Owner | Adjust operational thresholds. |
| [Audit & secrets](/en/admin/audit) | Staff/Owner | Review records; reveal secrets. |
