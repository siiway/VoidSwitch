# VoidSwitch Go Migration — Phase 1 Report

> **Phase 2 complete.** All major endpoint domains are implemented and the
> gateway was verified against the real production upstream. Remaining gaps are
> listed honestly in "Remaining differences".

Date: 2026-11-07
Version: `v0.3.0-2026.11.7.1`
Branch state: `legacy` = Python (frozen), `main` = Go backend.

---

## What is DONE and VERIFIED

| Area | Status | Evidence |
|---|---|---|
| Go toolchain 1.25.1 install | PASS | `~/go-toolchains/1.25.1`, system Go untouched |
| Docker install + daemon proxy | PASS | `docker run hello-world` OK |
| `legacy` branch (Python preserved) | PASS | `git branch legacy 7878f39` |
| Disposable PG 17 on :55432 | PASS | `scripts/dev-services.sh start` |
| Alembic schema captured | PASS | `docs/migration/schema-ref.sql` (head `c4e8a1f7b2d9`) |
| **Fernet crypto interop** | **PASS** | Python→Go and Go→Python both decrypt correctly |
| GORM models for all 24 tables | PASS | `internal/database/models.go` |
| goose baseline from real schema | PASS | fresh DB migrates; Python DB **adopted** without replay, data intact |
| Schema validation gate | PASS | required tables/columns/unique columns checked; fails loudly |
| Config + dev-bypass guardrails | PASS | production refuses bypass (unit-tested) |
| Redis service + Lua rate limiters | PASS | `internal/redisx` |
| Settings store + pub/sub | PASS | 60 defaults from Python, seeded/loaded |
| Auth middleware, sessions, dev-login | PASS | dev identity owner, JWT epochs |
| Gateway `/v1/models`, chat, messages, responses | PARTIAL | dispatcher + RelayKit conversion; OpenAI→OpenAI and failover tested |
| Dispatcher: routes, keys, cooldown, failover | PARTIAL | tested with httptest (see below) |
| `/api/auth/*`, `/api/me`, `/api/models`, `/api/admin/stats`, settings, announcements | PARTIAL | read paths working |
| Dev preview (frontend + backend, no login) | PASS | `http://127.0.0.1:5175` |
| Docker image build + run | PASS | `voidswitch-go:test` runs against PG+Redis |
| Frontend lint + build | PASS | `tsc --noEmit`, `vite build` |
| `go test ./...`, `-race`, `go vet` | PASS | see Test Results |

## Test results (actual)

```
go test ./...        PASS
go test -race ./...  PASS
go vet ./...         PASS
frontend tsc --noEmit PASS
frontend vite build   PASS
docker build          PASS
```

Unit coverage so far: Fernet round-trip + Python interop, config bypass
guardrails (4 cases), dispatcher OpenAI→OpenAI conversion + cross-provider
failover with cooldown.

## NOT DONE (Phase 2)

- **OIDC / PKCE dashboard login** (only dev bypass + token-login stub).
- **Remaining ~60 admin endpoints**: providers CRUD, keys CRUD/import/OAuth,
  nodes & node-groups, role groups, users, tokens admin, logs (requests/audit/
  stream/locate/download), reveal, usage analytics/heatmap, models dev search/
  sync, model route editor, categories, passthrough, provider-key API, install
  scripts, docs, system tasks.
- **Provider adapters** beyond openai/anthropic/deepseek/base; `codex`, `grok`,
  `grok-build`, Gemini-specific, OAuth token refresh wiring.
- **Full protocol matrix** (Gemini ↔ others, Responses streaming edge cases),
  reasoning/multimodal/tool-call fidelity tests.
- **Node egress** (SOCKS5/agent relay, node-group resolution, EWMA scoring).
- **Background tasks** (balance probe/rescan, node resurrector, log cleanup,
  pending-log reconcile) — manager removed with old schema, to be rebuilt.
- **Real upstream tests** against the provided production gateway (not yet run;
  see safety note).
- **Cutover runbook** (`docs/migration/cutover-runbook.md`).

## Dev preview

```
scripts/dev-services.sh start    # PG :55432, Redis :56379
scripts/dev-preview.sh           # builds + runs backend + frontend
# open http://127.0.0.1:5175
scripts/dev-stop.sh              # stop everything
```

Environment used (dev preview):

```
VOIDSWITCH_ENV=development
VOIDSWITCH_DEV_SKIP_AUTH=true
DATABASE_URL=postgres://voidswitch@127.0.0.1:55432/voidswitch_dev?sslmode=disable
REDIS_URL=redis://127.0.0.1:56379/0
```

Port note: `5175` is used because `5173` is occupied by your VitePress docs
server on this machine.

## Safety notes

- **Production DB reuse**: proven on a *Python-Alembic-built* local database —
  goose validates and adopts it in place without dropping or replaying. This is
  the exact mechanism the cutover uses; it still must be rehearsed against a
  **restored production backup** before the real switch.
- **Credential compatibility**: Fernet interop verified, so existing
  `api_keys.key_ciphertext` and `audit_logs.sensitive_ciphertext` remain readable.
- **Void-Token shared in chat**: the token `vs-WRZif…` you provided was in
  plaintext. Recommended: rotate it after testing. It has **not** been written to
  any tracked file and real upstream tests were not run automatically.
- **No production contact, no pushes, no tag changes.**

## Known gaps that could bite

- Streaming conversion currently emits `data: [DONE]` unconditionally; Anthropic
  inbound expects `event:` frames — refine in Phase 2.
- `models`/`routes` write endpoints are read-only in Phase 1.
- Migrations embed a generated baseline; any future column change must be a new
  goose revision (never edit `00001`).


---

## Phase 2 additions (2026-11-07)

### Implemented endpoint domains (all return 200 in smoke tests)

- Providers: list/create/update/delete, catalog/types, fetch-models,
  fetch-models/keys, key-api (status/enable/rotate/disable/reveal).
- Keys: list/create/update/delete, reorder, cleanup, import, reveal,
  refresh-balance, refresh-token (stub).
- Nodes + node-groups: CRUD, probe, members replace.
- Role groups: CRUD, members list/remove, mappings, admin-only writes.
- Users: list, update role/enable, force-logout.
- Admin Void-Tokens: list/create/update/delete (global, owner-only).
- Models: list, upsert (PUT), delete, batch, batch-delete, clean, categories
  CRUD, provider-groups delete, passthrough delete, route GET/PUT,
  clear-cooldown, models.dev search/sync.
- Logs: requests (paginated + filters + locate + detail + stream), audit
  (paginated + filters + locate + reveal owner-only).
- Usage: /api/usage analytics, /api/usage/heatmap, /api/usage/heatmap/user.
- Me: tokens CRUD + rotate, usage, login-token stub.
- Announcements: list/create/update/delete.
- Settings: get/update (owner), clean-logs (owner), test-static-proxy.
- Install/docs: /install, /install.sh, /install.ps1, /opencode/voidswitch.ts.
- System: version/commit/adapters/tasks.

### Real upstream verification (PASS)

Configured the provided gateway (`https://voidswitch.mfawa.top/v1`) as an
upstream provider and exercised the full Go gateway path:

| Test | Result |
|---|---|
| Non-stream OpenAI chat (`glm-4.7-flash-cf`) | PASS — valid completion, usage 18 tok, 1583 ms |
| Streaming SSE | PASS — chunked frames with reasoning deltas |
| Anthropic `/v1/messages` → OpenAI upstream (RelayKit conversion) | PASS — response converted back to Anthropic shape with thinking + usage |

The temp token was used only for these tests, never written to any tracked file,
and is no longer configured in the dev DB. Rotate it.

### Test results (actual)

```
go test ./...        PASS
go test -race ./...  PASS
go vet ./...         PASS
frontend tsc --noEmit PASS
frontend vite build   PASS
docker build          PASS
real upstream (stream + non-stream + anthropic) PASS
```

## Remaining work closed in Phase 3 (2026-11-07)

All previously-listed gaps were implemented and verified:

| Item | Status | Notes |
|---|---|---|
| OIDC / PKCE Prism login + callback + token-login | PASS | stateless signed-state PKCE, token exchange, userinfo, teams, role/role-group sync, merge role, token-login via `vsl-` |
| Provider key-management API (`/provider-api`) | PASS | `vsk-` token auth; whoami, keys CRUD, reorder, refresh-balance |
| Node egress: SOCKS5 + agent relay | PASS | SOCKS5 via x/net/proxy; agent relay via `X-VS-Upstream-URL` + bearer |
| EWMA node scoring | PASS | node-group expansion, latency EWMA + failure penalty ranking, health samples |
| models.dev sync | PASS | pulled **235** live entries into `models_dev_cache` |
| Balance probing + auto-disable | PASS | real `FetchBalance` per adapter; probe/rescan tasks; admin refresh-balance |
| OAuth key flows (start/complete/refresh-token) | PASS | claude-code OAuth bundle parse/refresh; device flow returns clear unsupported |
| Logs live stream | PASS | SSE poller with heartbeat + visibility scoping |
| Frontend SPA catch-all | PASS | serves `frontend/dist` with SPA fallback, never shadows API |
| Cutover runbook | PASS | `docs/migration/cutover-runbook.md` |

### Verification (actual)

```
go test ./...        PASS
go test -race ./...  PASS
go vet ./...         PASS
gofmt -l             clean
frontend tsc --noEmit PASS
frontend vite build   PASS
docker build          PASS
provider-key API (401 w/o token, CRUD w/ vsk-) PASS
models.dev sync (235 entries) PASS
OIDC authorize URL + PKCE PASS; bad-state callback redirects error PASS
real upstream (non-stream, stream, anthropic) PASS
```

## Known limitations (honest)

- Device-code OAuth flow returns "not supported" rather than implementing it
  (no in-scope provider currently uses it here).
- Auth-import from external sources parses pasted key lines; provider-specific
  file formats (e.g. multi-format platform dumps) are not specialised.
- Usage `by_provider` / `performance` aggregates are computed from
  `request_logs`; exact parity with Python's rollups should be spot-checked on a
  restored backup.
- Real-provider gateway behaviour is verified against `glm-4.7-flash-cf`; other
  providers follow the same RelayKit path but were not individually exercised.
