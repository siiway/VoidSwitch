# Signing in

VoidSwitch uses **Prism** (OAuth / OpenID Connect) for dashboard sign-in. There
are no local passwords to manage.

## How to sign in

1. Open the dashboard URL in your browser.
2. Click **Sign in with Prism**.
3. Authorize the app in Prism if prompted.
4. You're redirected back and land on the **Dashboard**.

## Who is allowed in

Signing in with Prism is necessary but not always sufficient — you also need a
reason to be on the platform. You'll be admitted if **any** of these is true:

- you're an owner / co-owner / admin of the platform's main team (a *moderator*);
- your Prism team membership maps to at least one [role group](/admin/role-groups);
- an owner added you explicitly, or you're the very first user (who becomes owner).

If none apply, sign-in is refused with an **Access denied** message. Ask a
moderator to grant you a role or map your team position.

## Sessions

- Your session is a signed token stored in the browser. It expires after a
  configured period; just sign in again.
- If an owner disables your account, all your sessions are invalidated
  immediately and your Void-Tokens stop working until you're re-enabled and sign
  in again.
- Use **Sign out** in the sidebar footer to end your session.

## The docs site

This documentation is served privately at `/docs/`. Opening it from the sidebar
**Docs** tab carries your session automatically (in a new tab). If you open a
`/docs/` link without a session you'll get a `401`/`403` — sign in first.

Next: [The dashboard](/guide/dashboard).
