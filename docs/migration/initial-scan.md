# VoidSwitch Go Migration — Initial Scan (Stage 1)

> Status: **Stage 1 deliverable — plan only. No source, Git, package or service
> changes were made.** This report ends with open questions and requires
> explicit approval before any Stage 2 work begins.

Date: 2026-11-07
Repo: `siiway/VoidSwitch`
Branch inspected: `main`

---

## 1. Current Git state

```
$ git status --short --branch
## main...origin/main                (clean, no local changes)

$ git branch --list
* main
  what-ui                           (unrelated local branch)

$ git worktree list
/gh/siiway/VoidSwitch  7878f39 [heads/main]     (single worktree)

$ git remote -v
origin  git@github.com:siiway/VoidSwitch.git (fetch)
origin  git@github.com:siiway/VoidSwitch.git (push)
```

Recent history (most recent first):

```
7878f39 build(deps): bump certifi ... (#17)     <- origin/main, HEAD
022b139 feat(cache): add Redis coordination layer <docker-build>
be7041a fix(usage): widen counters and translate request ID
9297943 feat(health): filter models by status
e7507f8 fix(db): finalize cancelled streams safely
```

- Working tree clean; safe to branch.
- Two branches only; `what-ui` is unmerged local work — **must not be touched**.
- `backend-go/` last changed in `afa408f` (2026-08-01); Python has moved on for
  ~3 months since (Redis layer, routing rewrite, usage widening, announcements).
- No tags inspected yet for the last *release*; the version files are at
  `0.2.2-2026.10.5.5` (dev format), base `0.2.2`.

**Legacy base commit** for the `legacy` branch: `7878f39` (current `main`) — the
last commit that still contains the complete Python implementation.

---

## 2. Scale comparison — Python vs Go

| | Python (`backend/`) | Go (`backend-go/`) |
|---|---|---|
| Source | ~20,100 lines, 80+ modules | ~13,200 lines, 40 files |
| HTTP routes | 94 (incl. path-param variants) | ~55 |
| Provider adapters | **33** (`ADAPTERS` dict) | **30 constructors**, but 27 are thin wrappers in `openai.go`; only 4 real files (`openai`, `anthropic`, `deepseek`, `base`). Missing vs Python: `codex`, `grok`, `grok-build`. |
| DB models | 30 tables, fully modelled | **13 GORM structs** — most with **different table/column names** |
| Migrations | Alembic, 14 revisions | `AutoMigrate` + hand-rolled `addMissingColumns` (SQLite `PRAGMA` only) |
| Redis | Required (rate limits, settings pub/sub, OAuth state, SSE leases, health) | **Not used at all** |
| Database driver | `aiosqlite` / `asyncpg` (SQLite + **PostgreSQL**) | **SQLite only** (`gorm.io/driver/sqlite`, CGO) |
| Tests | 23 files, `uv run pytest` | **Zero `_test.go` files** |
| Toolchain | Python 3.13 + `uv` | `go 1.25.0` (local has **1.24.2**) |

The existing Go rewrite is a **stale, structurally incompatible prototype** from
2026-06. It is not a drop-in replacement and cannot be "promoted" verbatim.

---

## 3. Feature parity audit (requested 18-point scope)

Legend: **A** = present and usable · **P** = partial / divergent · **X** = absent.

| # | Area | Go | Notes |
|---|---|---|---|
| 1 | HTTP routes & contracts | **P** | ~55 of 94. Missing entire groups below. |
| 2 | Auth / JWT / OIDC / PKCE / roles | **P** | Has local JWT + `dev-login`, but **no OIDC** (`golang.org/x/oauth2`, JWT verification, JWKS, PKCE missing), no team→role mapping; trusts `trust_prism_admin` (Python explicitly **distrusts** site-wide Prism roles). |
| 3 | Provider management & credentials | **P** | CRUD exists; fields diverge (`proxy_mode`/`proxy_ids` vs `node_group_id`; no `uuid`, `slug`, `passthrough_*`, health-policy overrides, `new_api_mode`, `selective_ignore_rules`). |
| 4 | Provider adapters / model discovery | **P** | Missing `codex`, `grok`, `grok-build`; `fetch-models` exists but no per-provider `/fetch-models/keys`. |
| 5 | ExposedModel / RouteUpstream / mapping | **X** | **Fundamental model mismatch**: Go uses a flat `models` table with `mapped_id`; Python uses `exposed_models` → `routes` → `route_upstreams` (scored, grouped, cooldowns). Entire routing subsystem absent. |
| 6 | Key pools / rotation / cooldown | **P** | Keys table lacks `pool`, `sort_order`, `rate_limit_until`; no cooldown / pool-aware selection. |
| 7 | Dispatcher / scoring / retry / failover | **P** | 979-line dispatcher exists but built on the obsolete `models` model; no upstream scoring/cooldown/failover. |
| 8 | Quota / RPM / usage accounting | **P** | `redis`-based sliding window absent; RPM enforced locally at best; no `usage_daily` rollup. |
| 9 | OpenAI Chat Completions | **P** | Basic pass-through. |
| 10 | OpenAI Responses | **P** | Adapter exists; protocol conversion incomplete. |
| 11 | Anthropic Messages | **P** | Adapter exists; conversion incomplete. |
| 12 | Gemini `generateContent` | **X** | Adapter constructor is an OpenAI passthrough; no Gemini protocol. |
| 13 | SSE / tools / reasoning / multimodal | **P** | Transform layer is 1,257 lines vs Python's 2,028; no reasoning-state, no media resolver, no cross-protocol conversion matrix. |
| 14 | Egress: direct / SOCKS5 / Agent Relay | **P** | `services/network.go` handles proxies; `agent/` relay protocol and node groups absent. |
| 15 | Redis / shared state | **X** | Not used. |
| 16 | Background tasks / logs / stats / health | **P** | 4 tasks (balance probe/rescan, proxy resurrector, log cleanup) vs Python's 5 incl. node resurrector + pending-log reconciliation; no `node_health_samples`, no request-log SSE stream, no audit reveal. |
| 17 | Frontend API compatibility | **X** (blocking) | Frontend calls **76** `/api/...` endpoints incl. `/admin/node-groups`, `/admin/nodes`, `/models/categories`, `/models/:id/route`, `/models/provider-groups/*`, `/models/passthrough/*`, `/models/batch-delete`, `/usage/heatmap*`, `/admin/logs/requests/stream`, `/admin/reveal/key`. Go implements almost none of these. |
| 18 | OpenCode plugin / install / docs | **P** | `/install`, `/install.sh|.ps1`, `/opencode/voidswitch.ts`, `/docs` exist, but the Go image does **not** bundle `opencode-plugin/src` or the built docs (compose-go.yaml itself notes this). |

**Concrete route groups missing in Go.** Confirmed by comparing the 76 frontend
`/api` paths against the Go router:

- Node routing: `/api/admin/nodes`, `/api/admin/nodes/:id`, `/nodes/:id/probe`,
  `/api/admin/node-groups`, `/node-groups/:id`, `/node-groups/:id/members`.
- Model routing: `/api/models/:model_id/route` (GET/PUT),
  `/route/upstreams/:id/clear-cooldown`, `/api/models/categories*`,
  `/api/models/provider-groups/:slug`, `/api/models/passthrough/*`,
  `/api/models/batch-delete`, `/models-dev/search|sync`.
- Keys: `/providers/:id/keys/import`, `/keys/oauth/*` (codex/claude/xai OAuth),
  `/keys/reorder`, `/keys/:id/refresh-token`, `/keys/:id/reveal`.
- Providers: `/providers/catalog/types` OK; `/providers/:id/key-api*` present;
  `fetch-models/keys` absent.
- Logs/usage: `/admin/logs/requests/stream`, `/requests/:id/download`,
  `/requests/locate`, `/audit/locate`, `/admin/reveal/key`, `/api/usage/heatmap`,
  `/api/usage/heatmap/user`.
- Settings: `/admin/settings/test-static-proxy`, `/admin/settings/clean-logs`.
- Misc: `/api/me/login-token`, `/api/me/login-token/rotate`, `/api/announcements`
  (has basic), `/api/admin/system`.

`docs.go` registers a catch-all `GET /*path` which may mask missing routes with
404s rather than contract errors — needs removal during port.

**Conclusion: parity is roughly 35–40%. The Go backend is not a rewrite of the
current Python backend; it is an earlier prototype of a different (simpler)
product.** Treat Stage 2 as *implementing against the Python source of truth*,
reusing Go scaffolding (config loader, JWT, gin wiring, provider interface,
dispatcher skeleton) where it aligns.

---

## 4. Database schema & Alembic complexity

Python models (`backend/voidswitch/models/db.py`, 954 lines, 30 tables):

`users, void_tokens, model_categories, exposed_models, routes, route_upstreams,
upstream_cooldowns, providers, api_keys, nodes, node_health_samples, node_groups,
node_group_members, settings, models_dev_cache, role_groups, role_group_mappings,
role_group_memberships, role_group_adminships, announcements, audit_logs,
request_logs, usage_daily, session_spans` (+ `alembic_version`).

Alembic: 14 revisions, 1,644 lines, head = `f6a3b8c2d1e4` (dynamic upstream
routing). `0001_baseline` is an *idempotent heal* (create_all + frozen
`_ADDED_COLUMNS` + `_ensure_indexes` + uuid backfill) — not a literal DDL tree.

Complexity drivers for a Go/goose cutover onto the **existing production DB**:

1. **Baseline problem.** A fresh local DB must be built to the *exact* Python
   schema. The only trustworthy way is to **run the Python Alembic tree once**
   (against local PG 17) and dump `pg_dump --schema-only` as the goose reference.
   Hand-transcribing 30 tables × ~20 columns invites drift.
2. **Existing-DB detection.** Goose must adopt an already-populated production DB
   without replaying migrations. Plan: a goose `--no-versioning` baseline
   (`0000_schema.sql`, executed only when `to_regclass('public.users') IS NULL`)
   plus a compatibility assertion that writes
   `voidswitch_schema_baseline` (table recording `alembic_head=f6a3b8c2d1e4`).
3. **Schema validation gate.** Before accepting an existing DB, verify a curated
   set of columns/types/indexes/constraints exist; **refuse to start** on
   mismatch (never auto-ALTER a production DB beyond documented forward-only
   migrations).
4. **Type fidelity.** JSON columns (`JSON`/`JSONB`), `BigInteger` counters
   (`c4e8a1f7b2d9`), `TIMESTAMPTZ`, `DEFAULT false` booleans. Go structs must use
   `*int64`, `json.RawMessage`/`datatypes.JSON`, and `NOT NULL DEFAULT false` to
   match.
5. **SQLite dev vs PG prod.** Python supports both; production is PG. Goose SQL
   must be PG-first (the requested target). SQLite support becomes best-effort,
   **not** the schema authority.

Risk: high **only** if we hand-write the baseline. Mitigated by generating it
from the live Python Alembic tree.

---

## 5. Redis compatibility requirements

Python uses Redis for (files: `core/sse.py`, `tasks/manager.py`,
`services/oauth_coordination.py`, `services/settings_store.py`,
`services/upstream_health.py`, `services/selector.py`, `core/ratelimit.py`):

- `rate:call:<group>`, `rate:rpm:<token>`, `rate:operation:<user>` — sliding
  window via **Lua** (`ZADD`/`ZREMRANGEBYSCORE`).
- `settings:snapshot`, `settings:version`, `settings:changed` — pub/sub for
  runtime settings across workers.
- `lease:<name>` — TTL leases for task leader election & SSE.
- OAuth coordination state, upstream health counters.

Go must reproduce the **same key prefix (`voidswitch`) and Lua semantics** if it
could ever share a Redis with Python during a rolling cutover. Since the cutover
is **stop-the-world**, cross-version key sharing is not required; but the Go
implementation must provide equivalent behaviour (go-redis + identical Lua
scripts recommended for test parity). `VOIDSWITCH_REDIS__URL` /
`VOIDSWITCH_REDIS__KEY_PREFIX` config keys must be honoured.

Development: system Redis is **already installed and running** on `:6379`
(leave untouched). A disposable instance on `:56379` is a config choice — see
§9.

---

## 6. Go dependency decisions (proposed, to be pinned)

| Concern | Current | Proposed pinned |
|---|---|---|
| HTTP | gin 1.12.0 | **gin** `v1.10.x` or current stable (keep) |
| ORM | gorm 1.31.1 + sqlite only | **gorm.io/gorm** + **gorm.io/driver/postgres** (pgx v5 underneath) |
| Migrations | AutoMigrate + `addMissingColumns` | **goose** (`github.com/pressly/goose/v3`) — SQL-first, embedded |
| Redis | none | **github.com/redis/go-redis/v9** |
| JWT | golang-jwt/jwt/v5 5.2.2 | keep |
| OIDC | none | **github.com/coreos/go-oidc/v3** + `golang.org/x/oauth2` |
| Logging | `log` | **log/slog** (JSON + dev console handler) |
| Protocol conversion | hand-written `transform.go` | **RelayKit** *if licence approved* (see §7) else keep/extend internal `protocol` package |
| Toolchain | `go 1.25.0` | **must install Go ≥1.25.1** (local is 1.24.2; RelayKit needs 1.25.1) |

Notes:
- Remove **CGO/sqlite3** from the production image (use pure-Go PG driver);
  this removes the `gcc/musl` builder requirement.
- `AutoMigrate` must be **deleted from the production path**; goose is the only
  schema writer.

---

## 7. RelayKit integration — licence is the blocker

Facts verified from upstream (2026-11-07):

- Module: `github.com/QuantumNous/new-api/relaykit`; tags exist through
  **`relaykit/v0.3.7`**; releases are `v0.x` (API may change in minor versions).
- **Requires Go ≥ 1.25.1** (its own `go.mod`: `go 1.25.1`).
- Runtime deps: `uuid`, `samber/lo`, `MoeForge/moego v0.1.0-alpha.1`, `testify`.
- Scope: request/response/stream conversion among **OpenAI Chat, OpenAI
  Responses, Anthropic Messages, Gemini** — exactly the matrix you need;
  handles tools, reasoning, multimodal, usage, stream state. HTTP/SSE/keys/billing
  are the host's job (matches VoidSwitch's architecture).
- **Licence: GNU AGPL-3.0**, plus **Section 7 additional terms** in `NOTICE`:
  must preserve *"Frontend design and development by New API contributors."*,
  a visible link to `https://github.com/QuantumNous/new-api`, and mark changes
  (AGPL §7(c)).

**Impact.** VoidSwitch is **MIT** (`backend/pyproject.toml`, no root LICENSE
file). Embedding AGPL-3.0 code into the backend means the **combined Go binary
becomes subject to AGPL-3.0** (strong copyleft, network-use clause). An MIT
project cannot ship an AGPL-linked binary under MIT terms. This is a legal
decision, not an engineering one — **must be confirmed before adoption**.

**Recommendation.** Do **not** adopt RelayKit in the default plan. Instead define
an internal `internal/protocol` interface (already partially present as
`transform.go`) with the four-protocol conversion matrix, modelled on
`transform.py` (the current Python implementation is in-house and MIT-clean).
RelayKit remains a *drop-in adapter* behind that interface for evaluation,
gated on your explicit licence approval. This satisfies "prefer RelayKit behind
an internal VoidSwitch-owned protocol interface" **without** committing the
licence.

---

## 8. Local tool availability

| Tool | Status |
|---|---|
| Go | **1.24.2** (`/usr/bin/go`) — **too old**; go.mod needs 1.25.0, RelayKit 1.25.1. Needs install. |
| PostgreSQL | Server **17** present at `/usr/lib/postgresql/17/bin/`. `initdb`,`pg_ctl` are **not on PATH** (use versioned path). `psql`, `createdb`, `pg_isready`, `pg_dump` on PATH. System cluster **not running** (`:5432` no response). |
| Redis | `redis-server` + `redis-cli` present; **system service active on `:6379`** (leave intact). |
| Node | v24.22.1 · npm 11.19.1 · **bun 1.4.4** (repo uses `bun.lock` → use bun). |
| Docker | **not installed** → Docker image build & compose validation are **NOT RUN** unless you authorise installing Docker (or we use `podman`/skip). |
| uv / Python | `uv 0.13.5`, Python 3.13.3 — available to run the Python Alembic tree to generate the schema baseline. |
| sudo | passwordless available (apt install permitted). |

**Answering prerequisite questions, no installs performed.**

---

## 9. Proposed temporary service setup

All disposable, localhost-only, outside tracked source, never touching the system
PG/Redis services.

**PostgreSQL** (disposable, PG 17):

- Binaries: `/usr/lib/postgresql/17/bin/{initdb,pg_ctl}`.
- Data dir: `${TMPDIR:-/tmp}/voidswitch-dev/pgdata`.
- Bind `127.0.0.1:55432`; socket in `…/pgsock` (dir env var e.g.
  `VOIDSWITCH_PG_ROOT`, default `/tmp/voidswitch-dev`).
- DB `voidswitch_dev`, role `voidswitch` (trust/scram local, **disposable**
  credentials only).
- `scripts/dev-services.sh` → idempotent `initdb` (only if empty) + `pg_ctl
  start -w` + wait `pg_isready`; subcommands `start|stop|status|logs|reset`.
- Fresh baseline: run Python `alembic upgrade head` once against this cluster,
  capture `pg_dump --schema-only` → goose `0000_schema.sql`.

**Redis** (disposable, no persistence):

- `redis-server --port 56379 --bind 127.0.0.1 --save "" --appendonly no
  --dir <tmp> --pidfile <tmp>/redis.pid --logfile <tmp>/redis.log
  --daemonize yes`.
- `REDIS_URL=redis://127.0.0.1:56379/0`.
- System `:6379` untouched.

**Preview stack** (`scripts/dev-preview.sh`): start services, `go run`/built
binary on `127.0.0.1:8080`, Vite dev server on `127.0.0.1:5173` proxying `/api`,
`/v1`, `/provider-api`, `/healthz` to `:8080`. **URL: http://127.0.0.1:5173**
(login-bypassed via dev identity). `scripts/dev-stop.sh` stops all three.

**Auth bypass safeguards** (`VOIDSWITCH_ENV=development` +
`VOIDSWITCH_DEV_SKIP_AUTH=true`):
- Bypass disabled by default; **startup fails hard** if
  `VOIDSWITCH_ENV=production` (or `VOIDSWITCH_SERVER__DEV_MODE=false` with the
  bypass flag set).
- Deterministic identity `dev-mode-user` (mirrors Python `DEV_USER_SUB`), owner
  role, **local DB only**.
- Never compiled into production image (env-gated, no build tag needed but
  also reject in `docker` unless explicitly dev).
- Clear `slog.Warn` banner on enable.
- Unit test asserting production mode rejects the bypass.

---

## 10. Proposed Git branch transition

1. Re-check `git status` + `git worktree list`; ensure clean.
2. `git branch legacy 7878f39` — snapshot of the last complete Python tree
   (backend/, Dockerfile, compose.yaml, CI). Add a `LEGACY.md` note; keep it
   **independently buildable** (no deletions on that ref).
3. On `main` (Go):
   - `git mv backend-go backend` after archiving Python (the move collides —
     see step 4), or: **remove `backend/` and `git mv backend-go backend`** in
     one commit (legacy ref preserves Python).
   - `git mv compose-go.yaml compose.yaml` (Python compose preserved on
     `legacy`).
   - Update root `Dockerfile` → Go multi-stage (no CGO, embed docs? see §12);
     update `.github/workflows/*`, `.env.example`, `AGENTS.md`, `CONTEXT.md`,
     `README.md`, `docs/**` (+ `docs/en/**`).
   - Keep `agent/` and `frontend/` as-is (contract preserved).
4. No force-push, no history rewrite, no tag deletion, **no push** without
   explicit authorisation. Local commits only.

---

## 11. Risks & unresolved questions

**Risks**
- **R1 Licence (high):** RelayKit AGPL-3.0 vs MIT VoidSwitch. Blocks RelayKit
  unless you approve re-licensing.
- **R2 Schema drift (high):** hand-written goose baseline could mismatch
  production. Mitigation: generate from live Alembic + runtime schema assertion.
- **R3 Parity scope (high):** ~60% of routes absent; this is a large rewrite.
- **R4 Toolchain (med):** Go 1.24.2 local; must install ≥1.25.1 (Downloads or
  distro). Docker absent.
- **R5 Provider coverage (med):** `codex`, `grok`, `grok-build`, `gemini`
  protocol, OAuth token flows need porting.
- **R6 Production-safety (high):** cutover must never run AutoMigrate or drop
  data; validates only, forward-only SQL.

**Unresolved questions for you**
1. **RelayKit licence** — accept AGPL-3.0 (whole backend becomes AGPL, add
   NOTICE + UI attribution) or keep in-house MIT protocol layer? *(blocks §7)*
2. **Parity bar** — must *every* endpoint (nodes/node-groups, model route editor,
   categories, heatmap, log stream, OAuth key imports, provider-key-api) be
   functional for cutover, or is a documented subset acceptable?
3. **Docker** — authorise installing Docker on this machine for image/compose
   validation, or mark those checks NOT RUN?
4. **Go 1.25** — authorise installing Go ≥1.25.1 (official tarball to `/usr/local`
   or `~/go-toolchains`, not touching system Go)?
5. **Schema baseline method** — OK to run Python `alembic upgrade head` on the
   disposable PG to generate the goose baseline (no prod data)?
6. **Real upstream tests** — which providers/creds exist locally?
   (`VOIDSWITCH_*` env / `config.yaml` present?) Which cheapest model?
7. **Preview bypass** — keep it dev-only (recommended) or also add a
   permanent `-tags devpreview` build? *(recommend dev-only)*

---

## 12. Expected files (modified / created)

**Go backend (`backend/`)**
- `cmd/voidswitch/main.go`, `internal/{config,core,database,handlers,services,tasks}`
  — extensive additions; new `internal/protocol`, `internal/migrate` (goose),
  `internal/redisx`, `internal/oidc`.
- `go.mod`, `go.sum` — new deps, pinned; remove sqlite driver from prod path.
- `migrations/*.sql` (goose), `migrations/embed.go`.
- Tests: `*_test.go` across handlers/services/protocol (httptest), migration &
  Redis integration tests, auth-bypass-rejection test.

**Repo root**
- `Dockerfile` (Go), `compose.yaml` (from `compose-go.yaml`, + Redis, PG-aware),
  `.env.example`, `go.work`? (no).
- `scripts/dev-services.sh`, `scripts/dev-preview.sh`, `scripts/dev-stop.sh`.
- `AGENTS.md`, `CONTEXT.md`, `README.md`, `docs/**` + `docs/en/**`.
- `.github/workflows/publish-images.yml` (Go build context), docs workflow unchanged.

**Migration docs**
- `docs/migration/initial-scan.md` *(this file)*
- `docs/migration/cutover-runbook.md` (Stage 2)
- `docs/migration/final-report.md` (Stage 2)

---

## 13. Ordered implementation plan (Stage 2)

1. **Prereqs:** confirm answers; install Go ≥1.25.1 (and Docker if authorised).
2. **Legacy branch:** `git branch legacy 7878f39`; verify buildable ref.
3. **Schema baseline:** start disposable PG → Python `alembic upgrade head` →
   `pg_dump --schema-only` → author goose `0000_schema.sql` + forward migrations
   from revision history; add `voidswitch_schema_baseline` + validation gate.
4. **Promote & clean:** `git rm -r backend`, `git mv backend-go backend`,
   `git mv compose-go.yaml compose.yaml`.
5. **DB layer:** replace GORM models with a schema-faithful set (30 tables);
   PG driver; **delete AutoMigrate/addMissingColumns**; goose at startup.
6. **Core:** config (add Redis/admin fields), slog, JWT sessions, **OIDC+PKCE**,
   team→role mapping, permission tiers (`require_staff`/`require_owner`),
   audit.
7. **Services:** redisx + Lua rate limiters, settings store pub/sub, routing
   (routes/route_upstreams/cooldowns), selector+scoring, key pools/rotation,
   node groups/egress (direct/socks5/agent), usage rollup, health snapshot,
   models.dev.
8. **Protocol:** internal 4-protocol conversion (or RelayKit behind interface if
   approved); SSE, tools, reasoning, multimodal, usage accounting.
9. **HTTP:** implement the full 94-endpoint contract; remove `/*path` catch-all;
   frontend compat pass.
10. **Tasks:** all 5 background tasks incl. pending-log reconcile.
11. **Dev preview:** scripts + dev-skip-auth guards + tests.
12. **Tests:** `go test ./...`, `-race`, `go vet`, integration PG+Redis,
    optional real upstream (gated), frontend `lint`+`build`.
13. **Cutover runbook + final report**; verification matrix with honest statuses.

---

## 14. Acceptance criteria

- [ ] Go backend compiles & runs against **PostgreSQL 17**; no AutoMigrate.
- [ ] Goose adopts a Python-Alembic-produced DB **without** replaying ALTERs or
      dropping data; schema validation passes; mismatch fails safely.
- [ ] All 94 Python routes implemented with matching request/response contracts
      (or a documented, approved subset).
- [ ] Frontend `tsc` + `vite build` pass; all 76 `/api` calls serve 2xx.
- [ ] Redis integration proven (rate limits, settings pub/sub, leases) against
      disposable `:56379`.
- [ ] `go test ./...`, `go test -race ./...`, `go vet ./...` green.
- [ ] Dev preview at `http://127.0.0.1:5173` login-bypassed; bypass rejected in
      production mode (tested).
- [ ] `legacy` branch preserves and builds the Python backend.
- [ ] No production contact, no pushes, no tag changes.
- [ ] `docs/migration/{cutover-runbook,final-report}.md` delivered with honest
      PASS / PARTIAL / FAIL / NOT RUN statuses.

---

## STOP

Stage 1 complete. **No Stage 2 action taken** — no source edits beyond this
report, no installs, no services started, no branch changes, no commits.

Please review and answer questions §11.1–§11.7, then explicitly approve to begin
Stage 2.
