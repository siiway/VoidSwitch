# Sign in

VoidSwitch uses **Prism** (OAuth / OpenID Connect) for dashboard sign-in. There are no local passwords to manage.

## How to sign in

1. Open the dashboard URL in your browser.
2. Click **Sign in with Prism**.
3. If prompted, authorize the application in Prism.
4. You'll be redirected back and land on the **Dashboard**.

## Who can get in

Signing in with Prism is necessary, but not always sufficient — you also need a reason to exist on the platform. You'll be allowed in if **any** of the following is true:

- You are an owner / co-owner / admin (*moderator*) of the platform's main team;
- Your Prism team membership maps to at least one [role group](/en/admin/role-groups);
- An administrator has explicitly added you, or you are the first user (who becomes the owner).

If none of these apply, sign-in is denied with an **Access denied** message. Contact an administrator to grant you a role or map your team position.

## Sessions

- Your session is a signed token stored in your browser. It expires after the configured time; just sign in again.
- If an administrator disables your account, all of your sessions are invalidated immediately, and your Void-Tokens stop working until you are re-enabled and sign in again.
- Use **Sign out** at the bottom of the sidebar to end the session.

## Emergency login token

Owners, co-owners, and admins can generate a personal login token in **Settings → Personal Settings**. It is used to enter the dashboard when Prism / OAuth is temporarily unavailable:

- On the sign-in page, click **Use login token** at the bottom, enter the token, and you're in;
- Each user has only one login token; after rotation the old token is invalidated immediately;
- The token is shown only once, at generation or rotation; afterward you can only see a secure fingerprint, not the plaintext;
- Regular members cannot generate or use login tokens, to avoid bypassing role-group evaluation.

## Documentation site

This documentation is **public** and hosted on a separate domain (no sign-in required to read it). The **Docs** tab in the dashboard sidebar opens it in a new tab. The docs are available in 中文 and English, switchable with the language menu in the top-right corner of the page.

Next: [Dashboard overview](/en/guide/dashboard).
