# VoidSwitch — Domain Context

This is the shared glossary and conceptual model for the platform. It contains
**no implementation detail**. When a term is used in code, comments, docs, or
UI, it must line up with the definitions here — if a design causes the terms to
drift, update this file first, then the code.

The file is deliberately terse: it exists so a new contributor (or a future you)
can read the entire platform's vocabulary in a couple of minutes.

## What VoidSwitch is

A production-grade multi-provider LLM API reverse proxy. A **user** presents a
**Void-Token** to the **gateway**; the gateway looks up their access, picks a
**route** for the requested **exposed model**, and forwards the call to an
upstream **provider** through a chosen egress **node**, with **key failover**
across the provider's **API keys**. Every call is captured as a **request log**;
every management action is captured as an **audit log**.

## People

- **User** — an authenticated identity. Backed by a Prism OAuth account
  (``sub``). Users have a single **platform role** and any number of **role
  group memberships** and **role group adminships**.
- **Prism** — the external OIDC identity provider. Also organises users into
  **teams** with **team roles**.
- **Team role** (Prism) — ``owner`` / ``co-owner`` / ``admin`` / ``member``.
  Effective (inherited) role is used; VoidSwitch never uses instance/site-wide
  Prism roles.
- **Main team** — the one Prism team whose team role determines the caller's
  platform role. Configured by ``admin.main_team_id``.

## Platform roles

Four tiers, ordered by increasing privilege:

- **member** — the default. Sees only their own resources.
- **role group admin** — a **read-only observer** for one or more custom role
  groups. Sees the users, statistics, and logs that belong to their groups (see
  "Role groups" below). Not a platform role stored on the user row — it is
  derived from role-group **adminship** rows. May be held simultaneously with
  any of the tiers below.
- **staff** — the platform moderators: ``admin`` + ``co-owner`` + ``owner``.
  Manages the day-to-day surface (providers, keys, nodes, models, users, logs,
  role groups except for editing).
- **owner** — ``owner`` + ``co-owner``. Reserved for sensitive actions:
  disabling users, editing role groups, deleting providers, revealing secrets,
  editing system settings.

The role hierarchy for visibility gates is ``member < role_group_admin < staff
< owner``. A user's ``role_group_admin`` capability is orthogonal to their
platform role: a platform admin who is also role-group-admin of group X still
sees group X's admin view (though for platform admins the view is a subset of
what staff already sees).

## Role groups (身份组)

A **role group** ("身份组") gates which **exposed models** its members may call
and provides an organisational lens for cross-organisation deployments (where
one platform serves multiple client organisations).

Two special properties:

- **Membership** grants model access — a member of group G may call any model
  whose ``allowed_role_group_ids`` includes G.
- **Adminship** grants a read-only observer view — an admin of group G sees
  group G's members, their statistics, and their request/audit logs, *without*
  being a platform moderator.

**Adminship never implies membership.** A user who is only an admin of group G
does *not* automatically gain model access to G's models. To grant both, add
two mapping rules (one ``grants=member``, one ``grants=admin``).

### Group mapping

A **mapping** is an auto-assignment rule of the form "members of Prism team *T*
whose effective role is at least *R* get group *G* as ``grants``", where
``grants`` is ``member`` or ``admin``. Membership and adminship are recomputed
from mappings at every login and persisted as separate rows so the gateway can
authorise calls without re-contacting Prism.

**A change to mappings takes effect for a given user at their next login** —
not immediately.

### The built-in moderator group

There is one built-in group, ``moderator`` (``slug="moderator"``,
``builtin=True``), whose membership is *derived* from the platform role (owner /
co-owner / admin) — its members are never stored. It always grants access to
every model. It cannot be renamed, deleted, or given mappings — only its call
rate limit is editable. It never accepts ``grants=admin`` mappings.

## Access permission summary

| Surface | member | role_group_admin | staff (admin) | owner / co-owner |
|---|---|---|---|---|
| See own dashboard, own tokens, own usage | ✓ | ✓ | ✓ | ✓ |
| See Users list | — | scoped to managed groups' members | all | all |
| See Statistics | own | scoped to managed groups' members | all | all |
| See Logs (audit + request) | own (request only) | scoped to managed groups | all | all |
| Force-logout | — | own group's non-staff members | lower tier | lower tier |
| See Role Groups list | — | — | ✓ (read-only) | ✓ |
| Edit Role Groups | — | — | — | ✓ |
| See request log **headers** and **debug attempts** | — | ✓ | ✓ | ✓ |
| See request log **bodies** | — | — | — | ✓ |
| Reveal any secret (audit, key, void-token) | — | — | — | ✓ |
| Edit users (role, enable) | — | — | — | ✓ |
| Edit system settings | — | — | — | ✓ |

**Sensitive values are never accessible to role-group admins.** They see the
same redacted key preview as platform admins; audit ``reveal`` is owner-only and
they cannot reach it.

## Void-Token

The long-lived client credential (``vs-…``) used to call the gateway. Belongs
to exactly one user. May carry per-token quota, allowed-model list, and a debug
flag that captures request/response detail (bodies are owner-visible only).

## Exposed model

The only model id clients see (e.g. ``fast-coder``). Routed through
``Route → RouteLayer → RoutePoolEntry`` to a real upstream provider. Access is
gated by ``allowed_role_group_ids``.

## Node / node group

Egress paths (direct / HTTP proxy / SOCKS5). Providers and system requests
(OAuth, userinfo) each pick a **node group**; failover between nodes is
transparent.

## Audit vs request log

- **Request log** — one row per API call through the gateway. Captures user,
  token, model, provider, key, node, status, tokens, latency. Bodies are only
  stored (and only visible) under the strictest conditions.
- **Audit log** — one row per management action. Captures actor, action,
  target, and (when present) an encrypted sensitive payload owner-revealable.
