# VoidSwitch — frontend

A decoupled admin dashboard for VoidSwitch, built with **Nuxt UI v3 + Vue 3**
and managed by **Bun**. Minimalist, high-density, low-animation — fast to render
on low-powered devices.

## Develop

```bash
cd frontend
bun install
bun run dev                 # Nuxt dev server on http://localhost:3000
```

The dev server proxies `/api`, `/v1` and `/healthz` to the backend on
`http://localhost:8080` (see `nuxt.config.ts`). Set `NUXT_PUBLIC_API_BASE` to
point at a backend on another host.

## Build

```bash
bun run build               # static SPA in .output/public/
bun run preview             # serve the built bundle locally
bun run lint                # nuxt typecheck
```

## What it does

- **Prism OAuth** sign-in (redirects to the backend `/api/auth/login`), plus
  staff token login and a dev-mode login when the backend enables it.
- **Dashboard** — live platform stats (staff) or own usage (member).
- **Providers** — browse providers; edit a provider and manage its API keys in
  stacked right-side drawers.
- **Models** — browse exposed models; open the route editor (candidate groups,
  weights, key pools, selection strategy) in a nested drawer.
- **Nodes** — node list with probe, plus node groups.
- **Health** — live model/node health over SSE.
- **Chat** — streaming chat through the gateway with a personal Void-Token.
- **Tokens** — personal API keys (all users) and global Void-Tokens (owner).
- **Users / Role groups** — staff and role-group-admin views.
- **Statistics** — usage analytics with time-window and role-group filters.
- **Logs / Audit** — request logs (live SSE) and the audit trail, with
  owner-only secret reveal.
- **Settings** — system settings (owner-editable, staff read-only) and the
  personal login token.
- **Workbench preferences** (staff) — drawer/full-page mode and command
  palette prefixes; `Ctrl/Cmd+K` quick navigation with `/`, `!`, `@`, `#`
  prefixes.

Members (non-staff) see only the surfaces their role grants them.
