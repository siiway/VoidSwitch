# Settings

The **Settings** page contains operational thresholds and intervals that take effect at runtime — no redeploy required. **Admins can view** settings (read-only);
**editing** and the **"Clean up logs now"** action are **owner-only**.

Settings are rendered generically by type: booleans appear as toggles, numbers as spinners, and strings as input boxes. They are arranged in groups.

## Groups

- **Proxy & Routing** — proxy toggle, static proxy URL, failure thresholds, probe interval and URL, and the reviver toggle.
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
- **Announcements** — how many announcements to show on the dashboard before showing "View all".
- **Rate Limiting (abuse protection)** — two per-user sliding-window limits, each set as
  "at most X requests within N seconds" (0 = unlimited):
  - **Operational actions** — mutating dashboard actions (add/edit/delete/save).
  - **OpenAI / Anthropic calls** — gateway endpoints
    (`/v1/chat/completions`, `/v1/messages`).

  Both apply to **everyone, including owners**, and are counted independently per user. To prevent lockout, an overly low
  action limit (below roughly 20 actions/minute) **is rejected** on save.

## Notes

- Settings that only apply under certain conditions are hidden otherwise (for example, the static proxy URL only appears when the proxy toggle is off).
- Changes take effect on save; background tasks pick up the new intervals on their next tick.
