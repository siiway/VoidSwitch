# VoidSwitch Python → Go Cutover Runbook

> **This is a preparation document. No step here has been executed against
> production.** Every production-impacting action requires a separate explicit
> approval at cutover time.

The cutover is **stop-the-world**: the Python gateway is stopped, a final backup
is taken, goose adopts the existing PostgreSQL schema in place, and the Go
gateway takes over. Rollback restores the backup and the Python image.

---

## 0. Preconditions (T-7 days)

- [ ] Go build tested against a **restored production backup**, not just an empty
      DB. Restore the latest prod dump into a scratch PostgreSQL 17 instance,
      point the Go backend at it, and confirm:
      - `migrations ready adopted_existing=true version=1`
      - `/api/auth/config`, `/api/admin/stats`, `/api/models` return real data
      - an existing provider's key decrypts (Fernet interop) — add + reveal a
        throwaway key on a scratch provider
      - an existing Void-Token authenticates a `/v1/models` call
- [ ] Frontend built from this branch and smoke-tested against the restored DB.
- [ ] OIDC login works against Prism with the production client credentials
      (not just the dev bypass).
- [ ] `VOIDSWITCH_SECRET_KEY` is identical to production's existing secret
      (**critical**: changing it makes every `key_ciphertext` /
      `sensitive_ciphertext` undecryptable).
- [ ] Redis reachable (rate limits, settings pub/sub, leases).
- [ ] Rollback image (`ghcr.io/siiway/voidswitch` at the last Python tag) is
      pinned and pullable.
- [ ] Maintenance window agreed; users notified.

## 1. Backup verification requirements

Before stopping anything:

1. Confirm the most recent automated backup exists and its **restore** has been
   tested (a backup you have not restored is not a backup).
2. Record the backup's timestamp and checksum.
3. Record the current schema revision:
   ```sql
   SELECT version_num FROM alembic_version;   -- expect the Python head
   ```
   The Go baseline was generated at Alembic head `c4e8a1f7b2d9`; a newer Python
   revision means the Go baseline must be regenerated first (do not proceed).

## 2. Maintenance mode

- Point the dashboard's reverse proxy / Cloudflare Tunnel at a static
  "maintenance" page, **or** stop the `dashboard` service first so no new user
  traffic reaches the gateway.
- Let in-flight streams drain (watch `request_logs.req_status = 'pending'`).

## 3. Stop the Python backend and all background writers

```bash
docker compose -f compose-python-legacy.yaml stop voidswitch
# Background tasks (balance probe/rescan, node resurrector, log cleanup) live
# inside the Python process, so stopping it stops them. Verify no other writer
# (e.g. a second replica) still touches the DB:
docker ps | grep voidswitch
```

Confirm the database has no active writers before taking the final backup.

## 4. Final backup

```bash
pg_dump -Fc -h <host> -U voidswitch -d voidswitch > voidswitch-pre-cutover-$(date +%Y%m%d%H%M).dump
# verify it restores into a scratch DB before proceeding
pg_restore --list voidswitch-pre-cutover-*.dump | head
```

## 5. Forward-compatible migrations (reviewed)

- The Go binary runs goose at startup. Against the existing Python DB it
  **adopts** the schema: it validates tables/columns/unique constraints, then
  records the baseline **without replaying** (see `database.Migrate`).
- On mismatch it **refuses to start** with a list of problems — it never drops or
  truncates.
- Any future column change must ship as a new forward-only goose revision; never
  edit `00001_schema_baseline.sql`.
- Pre-flight (read-only) check against production after the backup:
  ```bash
  # start the Go binary with VOIDSWITCH_ENV=production; it will fail fast on
  # schema mismatch before serving. Watch the log line:
  #   migrations ready adopted_existing=true version=1
  ```

## 6. Go deployment and health checks

```bash
docker compose -f compose.yaml up -d postgres redis voidswitch dashboard
docker compose -f compose.yaml logs -f voidswitch   # expect "migrations ready" + listener
curl -fsS http://<gateway>/healthz                  # {"status":"ok",...}
```

## 7. Redis verification

```bash
redis-cli -u "$VIRTUAL_REDIS_URL" ping                       # PONG
redis-cli -u "$VIRTUAL_REDIS_URL" --scan --pattern 'voidswitch:*' | head
```

## 8. OIDC and dashboard authentication

- Open the dashboard, complete Prism login (no dev bypass — must be
  `VOIDSWITCH_ENV=production`, bypass refused).
- Confirm the user's role/teams and role-group membership were recomputed.
- Confirm an existing Void-Token still works at `/v1/models`.

## 9. Controlled upstream request

- Send one non-streaming `POST /v1/chat/completions` to a **cheap** model via a
  real provider and verify a valid completion + logged usage.
- Optionally one streaming request; confirm SSE frames stream and the request log
  row finalises (`req_status` moves off `pending`).

## 10. Traffic restoration

- Point the reverse proxy / Tunnel back at the gateway.
- Monitor `/api/admin/logs/requests` for errors, `success_rate`, and key
  cooldowns for 30–60 minutes.

## 11. Safe rollback conditions

Roll back to Python if **any** of:

- The Go binary refuses to start on schema validation (means schema/version
  mismatch — do not force it).
- Existing provider keys fail to decrypt (secret-key mismatch) — stop immediately;
  do not issue requests.
- Auth or the gateway is broken and cannot be fixed inside the window.

**Rollback procedure:**

1. Stop the Go `voidswitch` service.
2. Restore the pre-cutover dump (section 4) into a clean database — this is why
   the snapshot is taken *before* the Go binary runs.
3. Re-deploy the pinned Python image:
   ```bash
   git checkout legacy            # or deploy the pinned Python image tag
   docker compose -f compose-python-legacy.yaml up -d voidswitch dashboard
   ```
4. Verify `/healthz`, auth, and one gateway call.
5. Investigate offline; the Go binary performs **no** destructive migration, so
   the restored dump is byte-for-byte the pre-cutover state.

## Notes on data compatibility

- Credential encryption is Fernet-compatible (verified bidirectionally with the
  Python implementation), so keys and audit secrets remain readable.
- Token lookup hashes are SHA-256 of the raw token (identical), so existing
  Void-Tokens and login tokens keep working.
- Testing against an **empty** local database proves schema creation but **not**
  compatibility with every historical production record — hence the mandatory
  restored-backup rehearsal in section 0.
