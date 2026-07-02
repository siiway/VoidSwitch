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

- **Owner / co-owner** are authoritative from Prism (the main team's owner/co-owner)
  or an explicit owner grant. They can't be assigned from the dashboard.
- **Admin** can be granted locally by an owner on the [Users](/admin/users) page,
  or inherited from a trusted Prism instance admin.
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
