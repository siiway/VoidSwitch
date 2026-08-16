# VoidSwitch

## Lint & Typecheck

```bash
# Backend
ruff check backend/
ty check

# Frontend
cd frontend && npm run lint
```

All `ty check` unresolved-import diagnostics are pre-existing (no venv at system level) — only new type errors from changed code should be fixed.

Frontend `npm run lint` is `tsc --noEmit`; also run `npm run build` for anything non-trivial. Backend: `uv run pytest` from `backend/`.

Use `bun` / `bunx` for frontend package and script operations where possible. Do not run commands that regenerate `package-lock.json`; this repo uses `bun.lock`, and mixing npm and Bun lockfiles creates noisy conflicts.

## Database migrations

**Alembic owns the schema.** The app runs `alembic upgrade head` automatically at startup (`core/database.py:run_migrations`), so deploys need no manual migration step — the first revision (`0001_baseline`) creates a fresh schema and heals pre-Alembic databases in one idempotent pass.

When you change a model, you MUST ship a migration with it:

```bash
# 1. edit the SQLAlchemy model (backend/voidswitch/models/db.py)
# 2. generate a candidate migration, then REVIEW it (autogenerate is a draft)
uv run alembic revision --autogenerate -m "describe the change"
# 3. confirm the model and the DB are in sync (CI-friendly check)
uv run alembic check
# 4. commit the model + migration together
```

Rules:

- **Never extend `_ADDED_COLUMNS` / `_ADDED_INDEXES` in `core/database.py`** — they are FROZEN and consumed only by the baseline to heal pre-Alembic databases. New columns/indexes go in an Alembic revision (or declared on the model, e.g. composite indexes in `__table_args__`).
- The URL comes from the app's own settings (`VOIDSWITCH_DATABASE__URL` / `config.yaml`); nothing is hardcoded in `alembic.ini`. Dev/tests run SQLite, prod runs PostgreSQL — the same tree serves both (SQLite ALTERs go through batch mode).
- Postgres nit: boolean defaults must be `DEFAULT false`, **not** `DEFAULT 0` (Postgres rejects `0` as an integer default for a boolean column).
- Alembic runs inside the app's event loop at startup; use `alembic check` before pushing to catch a model/migration drift.

## Documentation

There is a public, bilingual VitePress **usage** site in `docs/`, deployed to
GitHub Pages at `voidswitch.siiway.page` (see `.github/workflows/docs.yml`). When
a change alters user-facing behaviour (a page, a permission, a setting, an
endpoint, a flow), update the relevant `docs/**` page in the same change — keep
it in sync.

**Docs are bilingual**: Simplified Chinese is the root locale (`docs/**`), with
an English mirror under `docs/en/**` (mounted at `/en/`). Chinese is the source
of truth — author/update the `docs/**` page first, then mirror the change into
`docs/en/**` (English internal links carry the `/en` prefix). Chinese remains the
primary language of the platform's users across all regions.

Keep the tone **usage-focused**: how to do things and the caveats that matter to
users/operators. Avoid deep principle/architecture explanations (a short
architecture overview belongs only in `docs/guide/introduction.md`). Don't
document internal implementation detail that a user never touches.

## Permission tiers

Three tiers, enforced on the backend and mirrored in the UI (`useAuth`: `isStaff`, `isOwner`; route `<Protected staff|owner>`; nav `scope`):

- **member** — own resources only.
- **staff** = owner + co-owner + admin (the built-in `moderator` role group). Manages the day-to-day surface (providers, keys, proxies, models, role groups, the user list, logs).
- **owner** = owner + co-owner. Reserved for sensitive actions.

Owner-only (use `require_owner` on the backend and gate the control with `isOwner`): disabling users, global Void-Tokens, deleting providers, provider key-management API, revealing audit secrets, **editing system settings** (`/api/admin/settings` PUT) and **the "clean logs now" action**. Admins may still *view* settings (GET is `require_staff`) — render them read-only for non-owners, hide the Save/action buttons.

## UI conventions

### Action buttons (icon vs. label)

- **Row-level / secondary actions** are **icon-only**: a `<Button icon={…} appearance="subtle" />` wrapped in a `<Tooltip content={…} relationship="label">`, with a matching `aria-label`. The text shows only on hover. Applies to edit, delete, rotate, debug-toggle, role-group access, members, key-API, enable/disable, view-detail, etc.
- **Primary / page-level CTAs keep their text label**: Add, Save / Save changes, Sync, Apply, Clean now, the modal confirm/cancel buttons.
- Canonical icons: `EditRegular` (edit), `DeleteRegular` (delete), `ArrowSyncRegular` (rotate / reload), `PeopleTeamRegular` (role-group access), `PeopleListRegular` (member list), `BugRegular` (debug), `KeyRegular` (keys), `ProhibitedRegular`/`CheckmarkCircleRegular` (disable/enable), `BroomRegular` (clean), `CloudOffRegular` (proxy off). Reuse these before introducing new ones.
- Every user-facing string is an i18next key present in **both** `locales/en.ts` and `locales/zh.ts` (zh is typed `Translations`, so missing keys fail `tsc`). Dotted keys are cast `as TK` at the call site, matching existing code.

### Shared building blocks (`components/ui.tsx`)

- `PageHeader` owns the refresh button — pass `onRefresh`; the icon auto-spins for feedback (and while `refreshing` is true). Don't roll a bespoke refresh button.
- `Pager` is the one paginator (prev/next, range, "Page X / Y", jump-to-page). Item-based `offset`/`limit`; the Logs page size is the runtime `logs_page_size` setting, surfaced on the public `/api/auth/config`.
- Use `useAsync`, `useNotify`, `useConfirm`, `DataTable`, `EmptyState`, `Loading`, `ErrorText` rather than re-implementing.

### Settings page

- New operational settings: add to `constants.DEFAULT_SETTINGS` (they're migrated/seeded automatically). They render generically (bool→Switch, number→SpinButton, string→Input); add a label in `Settings.tsx` `labels` and place the key in the right `SECTIONS` group (unlisted keys fall into "Other"). Save button is unchanged.
- Settings that only matter under some condition (e.g. proxy-pool tuning when proxy switching is on) are hidden via `renderField`.

### Role groups & model access

- `moderator` (staff) can always call every model. Other users need a role group that the model lists in `allowed_role_group_ids`; membership is auto-evaluated from Prism team mappings at login. Per-model and batch model edits both go through `/api/models` / `/api/models/batch`.
- Batch OpenCode config edits support **merge** (deep-merge into each model's existing config — `_deep_merge`, nested dicts combined, lists/scalars replaced) and **overwrite**.

### Proxy switching

- `proxy_switching_enabled=false` means an external proxy (e.g. mihomo) handles egress: every request uses `static_proxy_url` (or direct / `HTTP(S)_PROXY` env), no failover, and no proxy is auto-disabled. When off, the Proxies tab is hidden from the nav and a direct URL shows an explicit disabled notice; the proxy-pool tuning settings are hidden too.

## Focus loss in Dialogs

**Root cause**: Fluent UI's `Dialog` uses a `FocusTrapZone` that re-focuses when the DOM subtree inside the dialog changes. If a section inside the dialog is conditionally mounted (`{cond && <JSX>}`), the `FocusTrapZone` re-evaluates its focus target when the conditional content appears/disappears, stealing focus from whichever input the user was interacting with.

**Fix**: never conditionally mount/unmount content inside a Dialog. Use `display: none` / `display: block` (or `visibility`) to hide/show instead:

```tsx
{/* bad — FocusTrapZone re-focuses when fetchOpen flips */}
<DialogContent>
  {fetchOpen && <FetchPanel />}
</DialogContent>

{/* good — DOM stays stable, FocusTrapZone never re-focuses */}
<DialogContent>
  <div style={{ display: fetchOpen ? "block" : "none" }}>
    <FetchPanel />
  </div>
</DialogContent>
```

This also applies to any wrapper that owns focus management (Popover, Drawer, etc.).
