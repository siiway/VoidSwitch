# Administration overview

This section is for **staff** — owners, co-owners, and admins who run the
platform. If you're a member, the [Guide](/guide/introduction) covers everything
you need.

## Permission tiers

VoidSwitch enforces three tiers on the backend and mirrors them in the UI.

| Tier | Roles | Scope |
| ---- | ----- | ----- |
| **Member** | member | Own resources only (own tokens, own logs/usage). |
| **Staff** | owner, co-owner, admin | The day-to-day management surface: providers, keys, proxies, models, role groups, the user list, logs, settings, and publishing announcements. |
| **Owner** | owner, co-owner | Sensitive actions on top of staff. |

### Owner-only (sensitive) actions

Reserved for owners and co-owners:

- disabling users and toggling global Void-Tokens;
- deleting providers and managing the per-provider key-management API;
- revealing audit secrets (plaintext keys, tokens, announcement edit history);
- **editing** system settings and running **"clean logs now"** (admins may *view*
  settings read-only).

## Where roles come from

Platform tiers are derived from the user's role in the configured **main team**
on Prism (`main_team_id`): the team's **owner → owner**, **co-owner → co-owner**,
**admin → admin**. This is the *only* source of a tier from Prism — a Prism
**instance / site-wide** admin is **not** trusted (being a Prism system admin
doesn't make you a VoidSwitch admin), and other teams never confer a tier (they
can still grant [role groups](/admin/role-groups) for model access).

- **Owner / co-owner** come from the main team's owner/co-owner role, or an
  explicit `owner_subs` / `owner_emails` grant (or the first-user bootstrap).
  They can't be assigned from the dashboard.
- **Admin** comes from the main team's `admin` role, or can be granted locally by
  an owner on the [Users](/admin/users) page (a "local admin override").
- **Member** is the default for anyone else with platform access.

## The management pages

| Page | Tier | What you do |
| ---- | ---- | ----------- |
| [Providers](/admin/providers) | staff | Add upstream platforms and their models. |
| [Upstream keys](/admin/keys) | staff | Load and manage each provider's API keys. |
| [Proxies](/admin/proxies) | staff | Configure egress proxies. |
| [Models](/admin/models) | staff | Curate the model catalog and access. |
| [Role groups](/admin/role-groups) | staff | Map team roles to model access. |
| [Users](/admin/users) | staff/owner | View users; grant admin / disable (owner). |
| [Void-Tokens](/admin/tokens) | owner | Manage client tokens across users. |
| [Settings](/admin/settings) | staff/owner | Tune operational thresholds. |
| [Audit & secrets](/admin/audit) | staff/owner | Review the trail; reveal secrets. |
