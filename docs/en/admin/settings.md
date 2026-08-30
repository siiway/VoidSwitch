# Settings

The **Settings** page contains operational thresholds and intervals that take effect at runtime — no redeploy required. **Admins can view** settings (read-only);
**editing** and the **"Clean up logs now"** action are **owner-only**.

Settings are rendered generically by type: booleans appear as toggles, numbers as spinners, and strings as input boxes. They are arranged in groups.

## Groups

- **Nodes & Routing** — the proxy-switching master toggle (`proxy_switching_enabled`): `true` = the node /
  node-group routing system is on; `false` = routing is off and every request goes through
  `static_proxy_url` (or the environment). Routing-related settings include `node_default_probe_url` (the probe
  URL used when a node group doesn't set its own — the only probe-URL setting), `node_probe_interval_seconds` (idle health-check interval), `node_rank_alpha/beta/gamma`
  (weights for dynamic node ordering), `node_rank_ewma_half_life_seconds` (decay half-life of a node's EWMA
  latency), `max_retries` (max retries per request), and `max_proxy_failures` (failure threshold before a
  node is disabled).
- **Keys & Balance** — key failure limit, auto-disable for zero-balance keys, and balance probe/rescan cadence and rate.
- **Rate Limiting** — the default recovery window and the cap on any single cooldown.
- **Timeouts & Retries** — connection / request / stream-idle timeouts, the retry budget, plus a
  **response timeout** (`response_timeout_seconds`): a hard wall-clock cap on the whole request (streaming
  included). When a request runs past it, the connection is **force-cut** and the log row is marked
  **Terminated** (已切断). Streaming previously had no total-duration bound — only the idle timeout — so a
  slow-trickling or leaked connection could stay "in progress" forever; this setting cuts such hung
  connections (`0` = disabled). At startup, any leftover "in progress" rows older than this window are also
  reconciled to **Terminated**.
- **Login & Session** — **Session duration** (`session_ttl_minutes`, minutes): how long a dashboard session
  JWT stays valid. `0` (empty) = **follow the `expires_in` Prism returns at login**; a value of at least
  **60** minutes is used as-is; when Prism sends none and nothing is configured, the server config's
  `session_ttl_minutes` is used. A non-zero value below 60 is rejected on save.
- **Logs & Retention** — page size, the auto-cleanup toggle and interval, and the retention windows for request / audit / debug logs
  (`0` = keep forever). Owners can also **clean up now**. After the debug log retention window
  (`debug_log_retention_days`) expires, the detailed debug fields on rows are stripped (request/response headers and bodies, per-attempt records),
  including the response headers and body that are force-recorded for errored requests (upstream 4xx / 5xx). This group also contains **heatmap data retention days**
  (`heatmap_retention_days`): the retention window for the daily usage aggregates that the dashboard activity heatmap relies on, independent of request log retention.
  The default is 365 days; `0` means keep forever, and a non-zero value must not be less than 365 days (validated on save).
- **OpenCode defaults** — the default model and small model published to the plugin.
- **Models & catalog** — the models.dev placeholder-metadata sync interval
  (`models_dev_sync_interval_minutes`, `0` = disabled).
- **Platform info** — how many announcements to show on the dashboard before "View all"
  (`announcements_home_count`), and the **chat preset questions** (`chat_preset_questions`, one per line)
  shown in the chat page's empty state.
- **Rate Limiting** — mutating dashboard actions are throttled at a fixed rate: at most 30 requests
  within 20 seconds per user (hard-coded, not configurable). OpenAI / Anthropic gateway calls
  (`/v1/chat/completions`, `/v1/messages`) are limited **per role group** — see
  [Role Groups](/en/admin/role-groups): default 30 requests per 30s, and the built-in moderator group
  defaults to 50 requests per 30s. Limits are still counted per user; a member of several groups passes
  while any of them still has budget.

## Notes

- Settings that only apply under certain conditions are hidden otherwise (for example, the static proxy URL only appears when **proxy switching / routing** is off, and the node-pool tuning settings only when the routing system is on).
- The **models.dev sync interval** (`models_dev_sync_interval_minutes`) controls how often exposed models'
  models.dev placeholder metadata is refreshed (default `1440` = daily).
- Changes take effect on save; background tasks pick up the new intervals on their next tick.
