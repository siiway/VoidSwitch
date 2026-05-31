# VoidSwitch — frontend

A decoupled admin dashboard for VoidSwitch, built with **React 19 + Fluent UI v9**
and managed by **Bun**. Minimalist, high-density, low-animation — fast to render
on low-powered devices.

## Develop

```bash
cd frontend
bun install
cp .env.example .env        # point VITE_API_BASE at your backend if not :8080
bun run dev                 # Vite dev server on http://localhost:5173
```

The backend must allow the dev origin in `server.cors_origins` (it allows
`http://localhost:5173` and `:4173` by default).

## Build

```bash
bun run build               # type-check (tsc -b) + production bundle to dist/
bun run preview             # serve the built bundle on :4173
```

## What it does

- **Prism OAuth** sign-in (redirects to the backend `/api/auth/login`).
- **Dashboard** — live key/proxy health and 24h request stats + background task status.
- **Providers** — add/edit providers (adapter-type picker), manage their model lists.
- **Keys** — batch-add API keys (one per line), see live status, enable/disable.
- **Proxies** — batch-add HTTP/SOCKS proxies, optional source-IP, manual probe.
- **Tokens** — mint/rotate/revoke Void-Tokens for any user (staff) or yourself.
- **Users** — role management (owner/admin/member) and enable/disable.
- **Settings** — tune failure thresholds and probe intervals at runtime.
- **Logs** — request traffic and the administrative audit trail.

Members (non-staff) see only **My API Key** — their tokens, usage, and connection
snippets.
