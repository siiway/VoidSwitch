# Users

The **Users** page lists everyone who has signed in, with their role, status, and
last login. **Viewing** the list is staff-level; **mutating** a user is
**owner-only**.

## Roles

- **Grant / revoke admin** (owner-only) — promote a member to admin or demote back.
  Owner and co-owner roles come from the main team on Prism and can't be set here.
- The **Team role** column shows the user's role in the main team (Prism).
- A "local override" is flagged when someone is a VoidSwitch admin but is **not**
  an admin of the main team — i.e. the admin role was granted here rather than
  coming from Prism.

## Disabling an account (owner-only)

Disabling a user:

- immediately invalidates all their dashboard sessions;
- turns off all their Void-Tokens so they can't call the gateway.

Re-enabling doesn't reactivate their tokens right away — they come back at the
user's next successful sign-in, which re-evaluates their role and role groups.

::: warning Same-tier protection
Owners and co-owners can't disable one another (same tier), and you can't disable
or change your own role.
:::
