# VoidSwitch

## Versioning

When no release is being cut, the version number MUST be updated to the dev
format on every change in:

- ``backend/internal/handlers/version.go`` (``Version``)
- ``frontend/package.json`` (``version``)

(On the ``legacy`` branch, also ``backend/voidswitch/__init__.py`` and
``backend/pyproject.toml``.)

**Dev format**: ``v{base}-{date}.{n}`` where:
- ``{base}`` = the last released version (e.g. ``0.2.2``)
- ``{date}`` = ``YYYY.M.D`` (today's date, e.g. ``2026.8.28``)
- ``{n}`` = consecutive modification number for today (``1``, ``2``, …)

Example: ``v0.2.2-2026.8.28.1``

The commit hash (first 7 chars) is resolved *dynamically*, not stored in these
files: ``backend/internal/handlers/version.go:CommitID()`` reads
``VOIDSWITCH_COMMIT`` (docker build arg) or runs ``git rev-parse --short=7 HEAD``,
and surfaces it separately as the ``commit`` field of ``/api/auth/config`` and
the system-info endpoint. A direct run without git simply omits the hash.

``pyproject.toml`` uses ``+`` instead of ``-`` after the base (PEP 440 local
version): ``0.2.2+2026.8.28.1``. The ``__init__.py`` and ``package.json`` use the
display form with hyphens.

## Lint & Typecheck

```bash
# Backend (Go) — requires Go >= 1.26 (see backend/go.mod)
cd backend && go build ./... && go vet ./... && go test ./... && gofmt -l .

# Frontend
cd frontend && bun run lint
```

Frontend `bun run lint` is `tsc --noEmit`; also run `bun run build` for anything
non-trivial.

The **Python** backend (on the `legacy` branch) uses `ruff check` / `ty check` /
`uv run pytest`; those tooling configs are not present on `main`.

Use `bun` / `bunx` for frontend package and script operations where possible. Do not run commands that regenerate `package-lock.json`; this repo uses `bun.lock`, and mixing npm and Bun lockfiles creates noisy conflicts.

## Docker image builds

`.github/workflows/publish-images.yml` builds and pushes the GHCR images. It has three triggers:

- **Tag push (`v*`)** — the release path: tags images with the version (`ghcr.io/siiway/voidswitch:0.2.3` + `:latest`) and creates the GitHub release.
- **Manual `workflow_dispatch` on main** — a snapshot build without a release: images are tagged `sha-<short-sha>` + `:latest`. No git tag is created.
- **Push to main whose head commit message contains `<docker-build>`** — the same snapshot build, triggerable from a commit. Useful for publishing a dev image without cutting a release or opening the Actions UI.

The release job runs **only** on version-tag pushes; snapshot builds never create tags or releases.

## Database migrations

**goose owns the schema (Go backend).** The gateway runs migrations at startup
(`internal/database/db.go:Migrate`). The single baseline revision
`backend/internal/database/migrations/00001_schema_baseline.sql` was generated
from the Python Alembic tree; it either creates a fresh schema or **adopts** an
existing PostgreSQL database in place (validates tables/columns/unique
constraints, then records the baseline without replaying). It never drops or
truncates.

When you change a model (`internal/database/models.go`), you MUST ship a new
forward-only goose revision:

```bash
# 1. edit the model
# 2. add backend/internal/database/migrations/00002_<desc>.sql with
#    -- +goose Up / -- +goose Down blocks (PostgreSQL SQL)
# 3. run against the disposable dev DB (scripts/dev-services.sh)
# 4. commit the model + migration together
```

Rules:

- **Never edit `00001_schema_baseline.sql`** — it is the frozen baseline. New
  columns/indexes go in a new revision.
- Production runs PostgreSQL. Boolean defaults must be `DEFAULT false` (not `0`).
- **Do not use GORM AutoMigrate** in the production path; goose is the only
  schema writer. The schema-faithful models must match the migration DDL.
- Dev/tests: `scripts/dev-services.sh` starts a disposable PostgreSQL on
  `127.0.0.1:55432` + Redis on `:56379`.

The **Python** backend (preserved on the `legacy` branch) still uses Alembic;
that branch's migrations are independent of the Go tree.

## Documentation
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

**Root cause**: Fluent UI's `Dialog` uses a `FocusTrapZone` that re-evaluates focus whenever the set of focusable elements inside the dialog changes. Any DOM mutation that adds or removes focusables — conditional React mounting, hidden `visibility`, native `<details>` opening — makes the trap steal focus back from whichever input the user was editing.

**Rules** (also apply to any wrapper that owns focus management: Popover, Drawer, etc.):

- Never conditionally mount / unmount content inside a Dialog. Toggle visibility with `display: none` / `display: block` (or `visibility: hidden`) so the DOM tree stays stable.
- Never use native `<details>` / `<summary>` inside a Dialog. Toggling `open` on `<details>` shows/hides its children, which counts as the same focusable-set change. Use a controlled collapsible: a `Button` + React state + a `<div style={{ display: open ? "block" : "none" }}>` wrapper.

```tsx
{/* bad — FocusTrapZone re-focuses when fetchOpen flips */}
<DialogContent>
  {fetchOpen && <FetchPanel />}
</DialogContent>

{/* bad — native <details> has the same effect when the user expands it */}
<DialogContent>
  <details>
    <summary>Fetch models</summary>
    <FetchPanel />
  </details>
</DialogContent>

{/* good — DOM stays stable, FocusTrapZone never re-focuses */}
<DialogContent>
  <Button
    appearance="subtle"
    icon={fetchOpen ? <ChevronDownRegular /> : <ChevronRightRegular />}
    onClick={() => setFetchOpen((v) => !v)}
  >
    Fetch models
  </Button>
  <div style={{ display: fetchOpen ? "block" : "none" }}>
    <FetchPanel />
  </div>
</DialogContent>
```
