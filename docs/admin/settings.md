# Settings

The **Settings** page holds operational thresholds and intervals, applied at
runtime — no redeploy needed. **Admins can view** settings (read-only);
**editing** and the **"clean logs now"** action are **owner-only**.

Settings render generically by type: booleans as switches, numbers as spin
buttons, strings as inputs. They're grouped into sections.

## Sections

- **Proxy & routing** — proxy switching on/off, the static proxy URL, failure
  thresholds, probe interval and URL, and the resurrector toggle.
- **Keys & balance** — key failure limits, auto-disable of zero-balance keys, and
  the balance probe/rescan cadence and rate.
- **Rate limiting** — default recovery window and a cap on any single cooldown.
- **Timeouts & retries** — connect/request/stream-idle timeouts and the retry
  budget.
- **Logs & retention** — page size, auto-clean toggle and interval, and retention
  windows for request/audit/debug logs (`0` = keep forever). Owners can also
  **clean now**.
- **OpenCode defaults** — the default and small model advertised to the plugin.
- **Announcements** — how many announcements show on the dashboard before
  "view all".

## Notes

- Settings that only matter under some condition are hidden otherwise (e.g. the
  static proxy URL only shows when proxy switching is off).
- Changes take effect on save; background tasks pick up new intervals on their
  next tick.
