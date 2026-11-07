# Migrating an existing deployment to the Go gateway

This is the practical companion to `cutover-runbook.md`, tailored to a
deployment that already runs the Python gateway with **PostgreSQL** (via
`VOIDSWITCH_DATABASE_URL`), **Redis**, and joins external `ai-network` /
`db-network`.

## What changes

- The gateway image becomes the **Go** build (`ghcr.io/siiway/voidswitch`).
- The dashboard image stays `ghcr.io/siiway/voidswitch-dashboard`.
- The database stays the **same PostgreSQL database** — do not migrate or dump
  it into a new one. On first boot the Go gateway **adopts** the existing schema
  (validates + records its baseline) and does not touch data.
- Redis is reused unchanged.
- The dashboard service name the gateway expects is still `voidswitch`.

## What MUST stay identical

`VOIDSWITCH_SERVER__SECRET_KEY` — the Go gateway decrypts stored provider keys
and audit secrets with it (Fernet-compatible with the Python backend). If it
differs, keys become unreadable. Confirm the current value before switching.

## The compose files

Base `compose.yaml` (bundled Postgres + Redis + gateway + dashboard) plus your
site override `compose.override.yaml` (external networks, no bundled DB). To use
**only** the gateway + dashboard with your external Postgres/Redis:

```bash
docker compose -f compose.yaml -f compose.override.yaml up -d voidswitch dashboard
```

If you keep using the bundled Redis, leave the `redis` service in (drop the
`bundled` profile note) — but your override removes bundled datastores, so
point `VOIDSWITCH_REDIS_URL` at your Redis explicitly.

## Your `.env` (prod)

```env
VOIDSWITCH_PORT=7292
VOIDSWITCH_BASE_URL=https://<your-domain>
# Same secret the Python gateway used:
VOIDSWITCH_SECRET_KEY=<existing-secret>
VOIDSWITCH_PRISM_ISSUER=https://prism.siiway.org
VOIDSWITCH_PRISM_CLIENT_ID=<...>
VOIDSWITCH_PRISM_CLIENT_SECRET=<...>
VOIDSWITCH_MAIN_TEAM_ID=63d4761c78c2dec09a002233e1b7c06c

# Existing PostgreSQL (reached over db-network) — NOT a fresh database:
VOIDSWITCH_DATABASE_URL=postgres://<user>:<pass>@<db-host>:5432/<db>?sslmode=disable
# Existing Redis:
VOIDSWITCH_REDIS_URL=redis://<redis-host>:6379/0

VS_IMAGE_TAG=<go-image-tag>   # e.g. 0.3.0-2026.11.8.1, or latest
```

## Cutover steps (stop-the-world)

1. **Back up Postgres** and verify the dump restores:
   ```bash
   pg_dump -Fc "$DB_URL" > voidswitch-pre-go-$(date +%Y%m%d%H%M).dump
   ```
2. Record the current schema revision:
   ```sql
   SELECT version_num FROM alembic_version;   -- record it
   ```
3. Stop the old gateway (stops its background writers):
   ```bash
   docker compose -f compose.yaml -f compose.override.yaml stop voidswitch
   ```
4. Pull the new image and start only the gateway first:
   ```bash
   docker compose -f compose.yaml -f compose.override.yaml pull voidswitch
   docker compose -f compose.yaml -f compose.override.yaml up -d voidswitch
   docker logs -f voidswitch      # expect: "migrations ready adopted_existing=true version=1"
   ```
   If it logs a schema-validation error instead, **stop** and roll back (below) —
   do not force it.
5. Verify health + auth + one gateway call:
   ```bash
   curl -fsS http://<gateway>:8080/healthz
   # then log into the dashboard and send one /v1/chat/completions
   ```
6. Start the dashboard with the same tag:
   ```bash
   docker compose -f compose.yaml -f compose.override.yaml up -d dashboard
   ```

## Rollback

1. `docker compose ... stop voidswitch dashboard`
2. Restore the pre-cutover dump into a clean database.
3. Deploy the pinned **Python** images (from the `legacy` branch / previous
   `VS_IMAGE_TAG`) and start.

The Go gateway performs no destructive migration, so the restored dump returns
you to the exact pre-cutover state.

## Notes

- Credentials (provider keys, audit secrets) are Fernet-compatible, so existing
  rows keep working.
- Void-Tokens / login tokens use the same SHA-256 lookup hash, so they keep
  working.
- Rehearse the whole procedure on a **restored copy** of the production
  database first (see `cutover-runbook.md` §0).
