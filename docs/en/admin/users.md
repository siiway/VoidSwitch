# Users

The **Users** page lists all users who have logged in, along with their role, status, and last login time. **Viewing** the list is staff-level;
**changing** a user is an **owner-only** operation.

## Roles

- **Grant / revoke admin** (owner only) — promote a member to admin or demote them back.
  The owner and co-owner roles come from the primary team on Prism and cannot be set here.
- The **Team Role** column shows the user's role in the primary team (Prism).
- When someone is a VoidSwitch admin but **not** an admin of the primary team, they are marked "local override" —
  meaning the admin role was granted here rather than coming from Prism.

## Disabling an account (owner only)

Disabling a user:

- immediately invalidates all of their dashboard sessions;
- turns off all of their Void-Tokens, preventing them from calling the gateway.

Re-enabling does not immediately reactivate their tokens. The system only restores tokens that were
**automatically turned off by the account being disabled** after the user next logs in successfully; tokens the user disabled themselves are not turned back on automatically. Their roles and role groups are re-evaluated at login.

## Force logout

Staff can force-log-out users whose **role rank is lower than their own**. This action does not disable the account, but it will:

- immediately invalidate the user's existing dashboard sessions;
- automatically disable the user's currently enabled Void-Tokens;
- require the user to log in again before the tokens that were **automatically disabled** are restored.

This is useful when you need a user to log in again so their Prism team relationships and role group mappings are re-evaluated.

::: warning Peer protection
Owners and co-owners cannot disable each other (peers), and cannot disable or change their own role.
:::
