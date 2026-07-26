# Announcements

Announcements are short platform-wide notices — maintenance windows, new model launches, policy changes, and so on.

## As a reader (everyone)

- **Sign-in popup** — when you sign in, the **latest** announcement pops up so you don't miss it. Dismissing the popup applies only to the current session;
  it will appear again the next time you sign in.
- **Dashboard panel** — the most recent announcements (3 by default) are listed on the dashboard. The number shown inline can be configured by the owner
  ([Settings](/en/admin/settings) → *Announcements*). If there are more, use **View all** to read the rest.

Each announcement shows its **title**, **content**, **publisher**, publish time, and an **Edited** label if it has been modified.

## Publishing (staff only)

Owners, co-owners, and admins can publish announcements:

1. Go to the **Dashboard**.
2. In the announcements panel, click **Publish**.
3. Enter a **title** (required) and **content**.
4. Optionally, select one or more **target role groups** — only members of those groups will see the announcement. Leave empty to send it to everyone.
5. Click **Publish**.

When target role groups are specified, staff see a small badge on the announcement card (hover to reveal the full list of groups).
Regular users only see announcements targeted at them (or targeted at everyone).

Announcements are visible to their target audience immediately (and pop up the next time they sign in).

## Editing and deleting

- You can **edit** or **delete** announcements you published yourself.
- You can also **delete/edit** announcements published by someone at a **lower tier than you** (for example, an owner can manage an admin's announcements).
  Owners and co-owners share the highest tier, so they cannot manage each other's announcements — only their own.

Every edit is recorded in the [audit log](/en/admin/audit). The full before-and-after content is stored as an **owner-viewable secret**,
so there is a reviewable history without exposing the content to everyone.

::: tip
Keep announcements concise. Content is displayed as plain text (line breaks are preserved), so use short paragraphs.
:::
