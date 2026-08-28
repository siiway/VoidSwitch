import {
  Badge,
  Button,
  Combobox,
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  Dropdown,
  Input,
  Option,
  TableBody,
  TableCell,
  TableHeader,
  TableHeaderCell,
  TableRow,
  Text,
  Textarea,
  Tooltip,
  tokens,
} from "@fluentui/react-components";
import {
  ArrowEnterRegular,
  BugRegular,
  DismissRegular,
  EyeRegular,
  InfoRegular,
  LiveRegular,
  LockClosedRegular,
  PersonRegular,
  SettingsRegular,
} from "@fluentui/react-icons";
import type { BadgeProps } from "@fluentui/react-components";
import { makeStyles } from "@fluentui/react-components";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactElement } from "react";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router-dom";
import { api, getToken, API_BASE } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { isRequestLog } from "../api/types";
import type {
  AuditFilterOptions,
  AuditLog,
  Page,
  RequestFilterOptions,
  RequestLog,
  RequestLogAttempt,
  RequestLogDetail,
} from "../api/types";
import type { Translations } from "../i18n/locales/en";
import {
  DataTable,
  ErrorText,
  Loading,
  PageHeader,
  Pager,
  formatDate,
  formatDateMs,
  useAsync,
  useConfirm,
  useDebouncedValue,
  useNotify,
} from "../components/ui";

const DEFAULT_PAGE = 50;

// The lifecycle statuses a request log row can be in (req_status). Ordered for
// the filter dropdown; labels come from the i18n ``logs.reqStatus*`` keys.
const REQ_STATUS_VALUES: string[] = [
  "pending",
  "completed",
  "cancelled",
  "error",
  "terminated",
];

// Max rows kept from the live SSE stream before older ones are dropped, so a
// long-lived stream can't grow the table without bound.
const LIVE_ROW_CAP = 200;

const REQ_STATUS_LABEL: Record<string, string> = {
  pending: "logs.reqStatusPending",
  completed: "logs.reqStatusCompleted",
  cancelled: "logs.reqStatusCancelled",
  error: "logs.reqStatusError",
  terminated: "logs.reqStatusTerminated",
};

// Persistent highlight for a row the user jumped to. Unlike a brief flash this
// stays visible (with a strong brand accent + left bar) until the user moves the
// pointer / scrolls / types, so it's easy to spot even after an auto-scroll.
const useHighlightStyles = makeStyles({
  row: {
    backgroundColor: tokens.colorBrandBackground2,
    boxShadow: `inset 4px 0 0 0 ${tokens.colorBrandStroke1}`,
    transition: "background-color 0.5s ease-out, box-shadow 0.5s ease-out",
    // The first cell is sticky with its own opaque background, so it must be
    // repainted too or the highlight would be clipped to columns 2+.
    "& td:first-child": {
      backgroundColor: tokens.colorBrandBackground2,
    },
  },
});

/**
 * Shared "jump to a row by id" behaviour for the log tables:
 *   • auto-scrolls the target row into view once it renders (even when it was
 *     already on the current page but off-screen);
 *   • keeps a strong highlight on it until the user moves the pointer, scrolls,
 *     or types — then it clears on its own.
 *
 * ``dataDep`` should be the current page data, so a jump that changes the page
 * re-runs the scroll once the new rows arrive.
 */
function useIdJump(dataDep: unknown) {
  const [highlightId, setHighlightId] = useState<number | null>(null);
  const [scrollTarget, setScrollTarget] = useState<number | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const autoScrolling = useRef(false);

  // Scroll the target into view once it's present in the DOM. Runs again when
  // the page data changes (i.e. after a cross-page jump reloads the rows).
  useEffect(() => {
    if (scrollTarget == null) return;
    const el = containerRef.current?.querySelector<HTMLElement>(
      `[data-log-row="${scrollTarget}"]`,
    );
    if (el) {
      autoScrolling.current = true;
      el.scrollIntoView({ behavior: "smooth", block: "center" });
      setScrollTarget(null);
    }
  }, [scrollTarget, dataDep]);

  // Clear the highlight on user-initiated interaction (scroll, pointer move,
  // keypress). Ignores scroll events emitted during the auto-scroll animation.
  useEffect(() => {
    if (highlightId == null) return;
    const clear = () => {
      autoScrolling.current = false;
      setHighlightId(null);
    };
    const onScroll = () => {
      if (autoScrolling.current) {
        autoScrolling.current = false;
        return;
      }
      setHighlightId(null);
    };
    const el = containerRef.current;
    if (el) {
      el.addEventListener("scroll", onScroll, { passive: true });
    }
    window.addEventListener("pointermove", clear, { passive: true, once: true });
    window.addEventListener("touchmove", clear, { passive: true, once: true });
    window.addEventListener("keydown", clear, { passive: true, once: true });
    return () => {
      if (el) el.removeEventListener("scroll", onScroll);
      window.removeEventListener("pointermove", clear);
      window.removeEventListener("touchmove", clear);
      window.removeEventListener("keydown", clear);
    };
  }, [highlightId]);

  const markJump = useCallback((id: number) => {
    setHighlightId(id);
    setScrollTarget(id);
  }, []);

  return { highlightId, containerRef, markJump };
}

const useFilterStyles = makeStyles({
  // A table value that fills the matching filter when clicked. Looks like plain
  // text until hovered, so the tables stay readable but every cell is actionable.
  clickable: {
    background: "none",
    border: "none",
    padding: 0,
    margin: 0,
    font: "inherit",
    color: "inherit",
    textAlign: "left",
    cursor: "pointer",
    ":hover": { textDecoration: "underline" },
  },
});

interface SelectOption {
  value: string;
  label: string;
  sublabel?: string | null;
}

/**
 * A "type to search, then pick" filter — the same interaction as the model
 * picker above the chat. Selecting an option applies the filter immediately.
 *
 * The displayed text is derived directly from the committed ``value`` prop
 * (so a table-cell click or a "clear filters" reset reflects instantly), and is
 * only overridden by a local ``draft`` while the user is actively typing. This
 * avoids the earlier race where selecting an option, then blurring, wiped the
 * chosen value.
 */
function SearchSelect({
  value,
  options,
  onChange,
  placeholder,
  ariaLabel,
  minWidth = 170,
}: {
  value: string;
  options: SelectOption[];
  onChange: (value: string) => void;
  placeholder: string;
  ariaLabel: string;
  minWidth?: number;
}) {
  const selectedLabel = options.find((o) => o.value === value)?.label ?? value ?? "";
  // `null` = not typing (show the committed selection); a string = the in-progress
  // query the user is typing.
  const [draft, setDraft] = useState<string | null>(null);
  const typing = draft !== null;
  const display = typing ? draft : selectedLabel;

  const q = (draft ?? "").trim().toLowerCase();
  const filtered =
    typing && q
      ? options.filter(
          (o) =>
            o.label.toLowerCase().includes(q) || o.value.toLowerCase().includes(q),
        )
      : options;

  return (
    <Combobox
      aria-label={ariaLabel}
      placeholder={placeholder}
      style={{ minWidth }}
      freeform
      clearable
      value={display}
      selectedOptions={value ? [value] : []}
      onOptionSelect={(_, d) => {
        // Fires both when picking an option and when hitting the clear (×) icon
        // (with `optionValue === undefined`). Either way apply immediately and
        // drop back to reflecting the committed value.
        onChange(d.optionValue ?? "");
        setDraft(null);
      }}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={() => {
        // A half-typed query that was never picked is discarded; an emptied box
        // clears the filter.
        if (typing && !draft?.trim()) onChange("");
        setDraft(null);
      }}
    >
      {filtered.map((o) => (
        <Option key={o.value} value={o.value} text={o.label}>
          <div style={{ display: "flex", flexDirection: "column" }}>
            <span>{o.label}</span>
            {o.sublabel ? (
              <Text size={200} style={{ color: tokens.colorNeutralForeground3 }}>
                {o.sublabel}
              </Text>
            ) : null}
          </div>
        </Option>
      ))}
    </Combobox>
  );
}

// --- time-range filter ----------------------------------------------------- //

type TimeMode = "" | "1h" | "24h" | "7d" | "30d" | "custom";

// Relative presets, in hours from "now". "custom" is handled separately.
const TIME_PRESETS: { mode: Exclude<TimeMode, "" | "custom">; hours: number }[] = [
  { mode: "1h", hours: 1 },
  { mode: "24h", hours: 24 },
  { mode: "7d", hours: 24 * 7 },
  { mode: "30d", hours: 24 * 30 },
];

// A native <input type="datetime-local"> yields a tz-less local wall-clock
// string ("2024-01-02T15:04"); turn it into an absolute ISO instant (UTC, with
// a `Z`) so the backend receives an unambiguous point in time.
function localInputToIso(value: string): string {
  if (!value) return "";
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? "" : d.toISOString();
}

// Inverse of the above: render an absolute ISO instant back into the
// `datetime-local` field's expected local wall-clock format.
function isoToLocalInput(iso: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(
    d.getHours(),
  )}:${pad(d.getMinutes())}`;
}

/**
 * Time-range picker: a preset dropdown (Any / last hour / 24h / 7d / 30d /
 * custom). Selecting "Custom" reveals two Fluent datetime-local inputs seeded
 * with a default 24h window. Fully controlled via ``mode``/``start``/``end`` so
 * a "clear filters" reset from the parent collapses it back to "Any time".
 */
function TimeRangeFilter({
  mode,
  start,
  end,
  onChange,
}: {
  mode: TimeMode;
  start: string;
  end: string;
  onChange: (next: { timeMode: TimeMode; start: string; end: string }) => void;
}) {
  const { t } = useTranslation();
  type TK = keyof Translations;

  const modeLabel = (m: TimeMode): string => {
    switch (m) {
      case "1h":
        return t("logs.timeLastHour" as TK);
      case "24h":
        return t("logs.timeLast24h" as TK);
      case "7d":
        return t("logs.timeLast7d" as TK);
      case "30d":
        return t("logs.timeLast30d" as TK);
      case "custom":
        return t("logs.timeCustom" as TK);
      default:
        return t("logs.timeAny" as TK);
    }
  };

  const selectMode = (m: TimeMode) => {
    if (m === "custom") {
      // Entering custom: if no explicit range exists yet, seed a sensible,
      // editable default (the last 24h) so the filter takes effect immediately
      // and it's obvious *something* happened — instead of showing two empty
      // fields that quietly match everything. Any range already in place (e.g.
      // carried over from a preset) is preserved untouched.
      if (!start && !end) {
        const now = Date.now();
        onChange({
          timeMode: "custom",
          start: new Date(now - 24 * 3600 * 1000).toISOString(),
          end: new Date(now).toISOString(),
        });
      } else {
        onChange({ timeMode: "custom", start, end });
      }
    } else if (m === "") {
      onChange({ timeMode: "", start: "", end: "" });
    } else {
      // Snapshot the preset to a concrete instant now, so paging/refresh keep a
      // stable window instead of silently drifting with the clock.
      const preset = TIME_PRESETS.find((p) => p.mode === m);
      const hours = preset ? preset.hours : 0;
      const startIso = new Date(Date.now() - hours * 3600 * 1000).toISOString();
      onChange({ timeMode: m, start: startIso, end: "" });
    }
  };

  return (
    <div
      style={{ display: "flex", gap: 8, alignItems: "flex-end", flexWrap: "wrap" }}
    >
      <Dropdown
        aria-label={t("logs.filterTime" as TK)}
        placeholder={t("logs.timeAny" as TK)}
        style={{ minWidth: 150 }}
        selectedOptions={[mode || "any"]}
        value={modeLabel(mode)}
        onOptionSelect={(_, d) => {
          // Fluent v9 has a long-standing footgun where an <Option value="">
          // (empty string) fails to register in the option collection, so
          // selecting *any* option can silently no-op. Use a non-empty "any"
          // sentinel for the "Any time" choice and map it back to "".
          const picked = d.optionValue ?? "any";
          selectMode((picked === "any" ? "" : picked) as TimeMode);
        }}
      >
        <Option value="any" text={t("logs.timeAny" as TK)}>
          {t("logs.timeAny" as TK)}
        </Option>
        <Option value="1h" text={t("logs.timeLastHour" as TK)}>
          {t("logs.timeLastHour" as TK)}
        </Option>
        <Option value="24h" text={t("logs.timeLast24h" as TK)}>
          {t("logs.timeLast24h" as TK)}
        </Option>
        <Option value="7d" text={t("logs.timeLast7d" as TK)}>
          {t("logs.timeLast7d" as TK)}
        </Option>
        <Option value="30d" text={t("logs.timeLast30d" as TK)}>
          {t("logs.timeLast30d" as TK)}
        </Option>
        <Option value="custom" text={t("logs.timeCustom" as TK)}>
          {t("logs.timeCustom" as TK)}
        </Option>
      </Dropdown>
      {mode === "custom" ? (
        <>
          <Input
            type="datetime-local"
            aria-label={t("logs.timeStart" as TK)}
            style={{ minWidth: 200 }}
            value={isoToLocalInput(start)}
            input={{ max: isoToLocalInput(end) || undefined }}
            onChange={(_, d) =>
              onChange({ timeMode: "custom", start: localInputToIso(d.value), end })
            }
          />
          <Text size={200} style={{ color: tokens.colorNeutralForeground3, paddingBottom: 6 }}>
            –
          </Text>
          <Input
            type="datetime-local"
            aria-label={t("logs.timeEnd" as TK)}
            style={{ minWidth: 200 }}
            value={isoToLocalInput(end)}
            input={{ min: isoToLocalInput(start) || undefined }}
            onChange={(_, d) =>
              onChange({ timeMode: "custom", start, end: localInputToIso(d.value) })
            }
          />
        </>
      ) : null}
    </div>
  );
}

export function Logs() {
  const { t } = useTranslation();
  type TK = keyof Translations;
  const { isStaff } = useAuth();
  const [refreshKey, setRefreshKey] = useState(0);
  const [liveEnabled, setLiveEnabled] = useState(false);
  const config = useAsync<{ logs_page_size?: number }>(() =>
    api.get("/api/auth/config"),
  );
  const pageSize = Math.max(1, config.data?.logs_page_size || DEFAULT_PAGE);

  return (
    <div>
      <PageHeader
        title={t("logs.title" as TK)}
        subtitle={
          isStaff
            ? t("logs.subtitleStaff" as TK)
            : t("logs.subtitleMember" as TK)
        }
        onRefresh={() => setRefreshKey((k) => k + 1)}
        extraActions={<LiveStreamToggle enabled={liveEnabled} onToggle={setLiveEnabled} />}
      />
      <div style={{ marginTop: 16 }}>
        <RequestLogs
          refreshKey={refreshKey}
          pageSize={pageSize}
          liveEnabled={liveEnabled}
        />
      </div>
    </div>
  );
}

// Connect / disconnect button for the live request-log stream, rendered next to
// the page's refresh button.
function LiveStreamToggle({
  enabled,
  onToggle,
}: {
  enabled: boolean;
  onToggle: (v: boolean) => void;
}) {
  const { t } = useTranslation();
  type TK = keyof Translations;
  return (
    <Tooltip
      content={enabled ? t("logs.liveDisconnect" as TK) : t("logs.liveConnect" as TK)}
      relationship="label"
    >
      <Button
        size="small"
        appearance={enabled ? "primary" : "subtle"}
        icon={<LiveRegular />}
        onClick={() => onToggle(!enabled)}
        aria-label={
          enabled ? t("logs.liveDisconnect" as TK) : t("logs.liveConnect" as TK)
        }
      >
        {enabled ? t("logs.liveOn" as TK) : t("logs.liveConnect" as TK)}
      </Button>
    </Tooltip>
  );
}

// The administrative audit trail lives on its own top-level route/tab (between
// Logs and Settings) rather than as a sub-tab of Logs, so staff can deep-link to
// it directly and it never gets bounced back to the request view.
export function Audit() {
  const { t } = useTranslation();
  type TK = keyof Translations;
  const [refreshKey, setRefreshKey] = useState(0);
  const config = useAsync<{ logs_page_size?: number }>(() =>
    api.get("/api/auth/config"),
  );
  const pageSize = Math.max(1, config.data?.logs_page_size || DEFAULT_PAGE);

  return (
    <div>
      <PageHeader
        title={t("audit.title" as TK)}
        subtitle={t("audit.subtitle" as TK)}
        onRefresh={() => setRefreshKey((k) => k + 1)}
      />
      <div style={{ marginTop: 16 }}>
        <AuditLogs refreshKey={refreshKey} pageSize={pageSize} />
      </div>
    </div>
  );
}

interface RequestFilters {
  model: string;
  user_sub: string;
  token_id: string;
  provider: string;
  client_ip: string;
  status: string;
  req_status: string;
  // Time window. `timeMode` is UI-only (drives the preset dropdown); `start`/
  // `end` are absolute ISO instants sent to the backend.
  timeMode: TimeMode;
  start: string;
  end: string;
}

const EMPTY_REQUEST_FILTERS: RequestFilters = {
  model: "",
  user_sub: "",
  token_id: "",
  provider: "",
  client_ip: "",
  status: "",
  req_status: "",
  timeMode: "",
  start: "",
  end: "",
};

function requestFiltersFromParams(params: URLSearchParams): RequestFilters {
  return {
    ...EMPTY_REQUEST_FILTERS,
    model: params.get("model") || "",
    user_sub: params.get("user_sub") || "",
    token_id: params.get("token_id") || "",
    provider: params.get("provider") || "",
    client_ip: params.get("client_ip") || "",
    status: params.get("status_code") || "",
    req_status: params.get("req_status") || "",
  };
}

// A lone 1-5 digit means "the whole class": expand it to e.g. "4xx" on blur so
// the filter matches every 4xx status. Anything else is left as typed.
function normalizeStatus(value: string): string {
  const s = value.trim();
  return /^[1-5]$/.test(s) ? `${s}xx` : s;
}

// Backend timestamps may be tz-less (naive UTC from SQLite) — parse them as UTC
// so durations computed against ``Date.now()`` are correct.
function parseLogTs(value?: string | null): number {
  if (!value) return NaN;
  const trimmed = value.trim();
  const hasTz = /(?:[zZ]|[+-]\d{2}:?\d{2})$/.test(trimmed);
  const d = new Date(hasTz ? trimmed : `${trimmed}Z`);
  return d.getTime();
}

// Request duration: fixed once finished. While a request is still in progress
// it only counts up live when the live SSE stream is connected (``liveEnabled``)
// — without it the number would just be a client-side estimate of a stale row,
// so we show "—" instead.
function requestDurationMs(
  r: RequestLog,
  now: number,
  liveEnabled: boolean,
): number | null {
  const start = parseLogTs(r.started_at ?? r.ts);
  if (Number.isNaN(start)) return null;
  if (r.req_status === "pending" && !liveEnabled) return null;
  const end = r.finished_at ? parseLogTs(r.finished_at) : now;
  return Number.isNaN(end) ? null : Math.max(0, end - start);
}

// Live request-log stream over SSE. EventSource can't attach the dashboard's
// Authorization header, so this drives a fetch() ReadableStream and parses the
// SSE ``data:`` frames by hand.
function useLogStream({
  enabled,
  query,
  afterId,
  onRow,
  onError,
}: {
  enabled: boolean;
  // Serialized query params (filters) sent to the stream endpoint. Changing
  // them reconnects the stream so it stays aligned with the current filters.
  query: string;
  // First id the stream should skip (the max id currently displayed).
  afterId: number;
  onRow: (row: RequestLog) => void;
  onError: (message: string) => void;
}): { status: "idle" | "connecting" | "connected" | "error" } {
  const [status, setStatus] = useState<"idle" | "connecting" | "connected" | "error">(
    "idle",
  );
  const onRowRef = useRef(onRow);
  const onErrorRef = useRef(onError);
  const lastIdRef = useRef(afterId);
  useEffect(() => {
    onRowRef.current = onRow;
    onErrorRef.current = onError;
  }, [onRow, onError]);
  useEffect(() => {
    lastIdRef.current = afterId;
  }, [afterId]);

  useEffect(() => {
    if (!enabled) {
      setStatus("idle");
      return;
    }
    const token = getToken();
    if (!token) {
      setStatus("error");
      return;
    }
    let active = true;
    let reconnectTimeout: ReturnType<typeof setTimeout> | null = null;

    async function connect() {
      if (!active) return;
      const controller = new AbortController();
      setStatus("connecting");

      try {
        const params = new URLSearchParams(query);
        params.set("after_id", String(lastIdRef.current));
        const url = `${API_BASE}/api/admin/logs/requests/stream?${params}`;
        const res = await fetch(url, {
          headers: { Authorization: `Bearer ${token}` },
          signal: controller.signal,
          cache: "no-store",
        });
        if (!active) { controller.abort(); return; }
        if (!res.ok) {
          let detail = `HTTP ${res.status}`;
          try {
            const body = await res.json();
            detail = body.detail || detail;
          } catch { /* ignore */ }
          throw new Error(detail);
        }
        if (!res.body) throw new Error("empty stream");
        if (!active) { controller.abort(); return; }
        setStatus("connected");

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          let idx: number;
          while ((idx = buffer.indexOf("\n\n")) !== -1) {
            const frame = buffer.slice(0, idx);
            buffer = buffer.slice(idx + 2);
            for (const line of frame.split("\n")) {
              if (!line.startsWith("data: ")) continue;
              const payload = line.slice(6).trim();
              if (!payload) continue;
              try {
                const row = JSON.parse(payload);
                if (isRequestLog(row)) {
                  lastIdRef.current = Math.max(lastIdRef.current, row.id);
                  onRowRef.current(row);
                }
              } catch { /* skip malformed frame */ }
            }
          }
}
        // Server closed cleanly — not an error, but no reconnect.
        if (active) {
          setStatus("error");
          onErrorRef.current("Live stream ended.");
        }
      } catch (e) {
        if (!active) return;
        if (controller.signal.aborted) return;
        setStatus("error");
        onErrorRef.current(e instanceof Error ? e.message : String(e));
        // Auto-reconnect after a short delay.
        if (active) {
          reconnectTimeout = setTimeout(() => {
            if (active) void connect();
          }, 3000);
        }
      }
    }

    void connect();

    return () => {
      active = false;
      if (reconnectTimeout !== null) clearTimeout(reconnectTimeout);
      setStatus("idle");
    };
  }, [enabled, query]);

  return { status };
}

function formatDuration(ms: number | null): string {
  if (ms == null) return "—";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(1)}s`;
  const m = Math.floor(s / 60);
  const rest = Math.round(s % 60);
  return `${m}m ${rest}s`;
}

// IPv4 addresses are at most 15 chars ("255.255.255.255"); reserve a little more
// and truncate anything longer (IPv6) with an ellipsis. The full value is shown
// on hover via the wrapping Tooltip.
const MAX_IP_CHARS = 17;

function truncateIp(ip: string): string {
  return ip.length > MAX_IP_CHARS ? `${ip.slice(0, MAX_IP_CHARS)}…` : ip;
}

function RequestLogs({
  refreshKey,
  pageSize,
  liveEnabled,
}: {
  refreshKey: number;
  pageSize: number;
  liveEnabled: boolean;
}) {
  const { t: tr } = useTranslation();
  type TK = keyof Translations;
  const { isOwner } = useAuth();
  const hl = useHighlightStyles();
  const cellStyles = useFilterStyles();
  const notify = useNotify();
  const [searchParams] = useSearchParams();
  const [offset, setOffset] = useState(0);
  const [filters, setFilters] = useState<RequestFilters>(() =>
    requestFiltersFromParams(searchParams),
  );
  const [goToId, setGoToId] = useState("");
  const [detailLog, setDetailLog] = useState<RequestLogDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailMode, setDetailMode] = useState<"info" | "debug">("info");
  // Guard against a detail fetch resolving after the dialog was closed (or a
  // different row opened): only the latest request may populate the dialog.
  const detailReqRef = useRef<{ id: number; mode: "info" | "debug" } | null>(null);
  const [revealMode, setRevealMode] = useState(false);

  useEffect(() => {
    setFilters(requestFiltersFromParams(searchParams));
    setOffset(0);
  }, [searchParams]);

  const options = useAsync<RequestFilterOptions>(
    () => api.get("/api/admin/logs/requests/filters"),
    [refreshKey],
  );

  // Free-text status filters every keystroke; debounce so we fetch once the
  // value settles (500ms of no typing) instead of firing a request per character.
  const debouncedStatus = useDebouncedValue(filters.status, 500);
  const debouncedIp = useDebouncedValue(filters.client_ip, 500);

  const queryParams = {
    model: filters.model || undefined,
    user_sub: filters.user_sub || undefined,
    token_id: filters.token_id || undefined,
    provider: filters.provider || undefined,
    client_ip: debouncedIp || undefined,
    status_code: debouncedStatus || undefined,
    req_status: filters.req_status || undefined,
    start: filters.start || undefined,
    end: filters.end || undefined,
  };

  const logs = useAsync<Page<RequestLog>>(
    () =>
      api.get("/api/admin/logs/requests", {
        limit: pageSize,
        offset,
        ...queryParams,
      }),
    [
      offset,
      refreshKey,
      pageSize,
      filters.model,
      filters.user_sub,
      filters.token_id,
      filters.provider,
      debouncedIp,
      debouncedStatus,
      filters.req_status,
      filters.start,
      filters.end,
    ],
  );
  const { highlightId, containerRef, markJump } = useIdJump(logs.data);

  // Live request-log stream: new rows matching the current filters are pushed
  // over SSE and prepended to the table while enabled.
  const [liveRows, setLiveRows] = useState<RequestLog[]>([]);
  const [liveNotice, setLiveNotice] = useState<string | null>(null);
  const liveQuery = useMemo(() => {
    const params = new URLSearchParams();
    if (filters.model) params.set("model", filters.model);
    if (filters.user_sub) params.set("user_sub", filters.user_sub);
    if (filters.token_id) params.set("token_id", filters.token_id);
    if (filters.provider) params.set("provider", filters.provider);
    if (debouncedIp) params.set("client_ip", debouncedIp);
    if (debouncedStatus) params.set("status_code", debouncedStatus);
    if (filters.req_status) params.set("req_status", filters.req_status);
    return params.toString();
  }, [filters, debouncedIp, debouncedStatus]);

  // Max id currently shown — new stream rows start strictly after it.
  const maxShownId = useMemo(
    () =>
      logs.data?.items.reduce((m, r) => Math.max(m, r.id), 0) ??
      liveRows.reduce((m, r) => Math.max(m, r.id), 0) ??
      0,
    [logs.data, liveRows],
  );

  const handleLiveRow = useCallback(
    (row: RequestLog) => {
      // Merge by id so a streamed row that also landed in a concurrent reload
      // doesn't duplicate; keep the newest on top, capped to avoid unbounded
      // growth on a long-lived stream.
      setLiveRows((prev) => {
        const next = prev.filter((p) => p.id !== row.id);
        next.unshift(row);
        return next.slice(0, LIVE_ROW_CAP);
      });
      // Jump to page one so the freshly-arrived rows are visible.
      if (offset !== 0) setOffset(0);
    },
    [offset],
  );

  useLogStream({
    enabled: liveEnabled,
    query: liveQuery,
    afterId: liveEnabled ? maxShownId : 0,
    onRow: handleLiveRow,
    onError: (msg) => {
      setLiveNotice(msg);
    },
  });

  // Clear live rows when the stream is disconnected or filters change, and
  // expire the transient error notice.
  useEffect(() => {
    if (!liveEnabled) {
      setLiveRows([]);
      setLiveNotice(null);
    }
  }, [liveEnabled, liveQuery]);

  useEffect(() => {
    if (!liveNotice) return;
    const id = window.setTimeout(() => setLiveNotice(null), 6000);
    return () => window.clearTimeout(id);
  }, [liveNotice]);

  // While live is connected, show ONLY the rows pushed since connect (newest
  // first) — the pre-existing page is stale by definition and would otherwise
  // sit under the live rows. When disconnected, fall back to the fetched page.
  const allRows = useMemo(() => {
    if (liveEnabled) return liveRows;
    return logs.data?.items ?? [];
  }, [liveEnabled, liveRows, logs.data]);

  // Re-render every second while the live stream is connected and any row is
  // still in progress, so the Duration column counts up live; it freezes once
  // the stream is disconnected or the row finalises. Without SSE we deliberately
  // do NOT tick — a pending row's duration would just be a client-side guess.
  const [nowTick, setNowTick] = useState(0);
  useEffect(() => {
    if (!liveEnabled) return;
    const hasPending = (allRows ?? []).some((r) => r.req_status === "pending");
    if (!hasPending) return;
    const id = window.setInterval(() => setNowTick((t) => t + 1), 1000);
    return () => window.clearInterval(id);
  }, [liveEnabled, allRows]);
  void nowTick; // nowTick only exists to force re-renders; time is read live.
  const durationNow = Date.now();

  function setFilter<K extends keyof RequestFilters>(
    key: K,
    value: RequestFilters[K],
  ) {
    setOffset(0);
    setFilters((f) => ({ ...f, [key]: value }));
  }

  const hasFilters = Object.values(filters).some((v) => v !== "");

  async function jumpToId() {
    const id = Number(goToId.trim());
    if (Number.isNaN(id) || id <= 0) return;
    try {
      const r = await api.get<{ offset: number; found: boolean }>(
        "/api/admin/logs/requests/locate",
        { id, ...queryParams },
      );
      if (!r.found) {
        notify(tr("logs.jumpNotFound" as TK), `#${id}`, "warning");
        return;
      }
      setOffset(Math.floor(r.offset / pageSize) * pageSize);
      markJump(id);
    } catch (e) {
      notify(
        tr("logs.jumpFailed" as TK),
        e instanceof Error ? e.message : String(e),
        "error",
      );
    }
  }

  async function openDetail(r: RequestLog, mode: "info" | "debug") {
    const reqId = { id: r.id, mode };
    detailReqRef.current = reqId;
    setDetailLoading(true);
    setRevealMode(false);
    setDetailMode(mode);
    try {
      const d = await api.get<unknown>(`/api/admin/logs/requests/${r.id}`);
      if (detailReqRef.current !== reqId) return; // stale — dialog closed / re-opened
      // Validate the shape at the boundary rather than trusting a blind cast, so
      // an API change surfaces as a controlled fallback instead of a broken
      // object rendered downstream.
      if (!isRequestLog(d)) throw new Error("unexpected log-detail shape");
      setDetailLog(d as RequestLogDetail);
    } catch {
      if (detailReqRef.current !== reqId) return;
      // Fallback to the row we already have. RequestLogDetail only adds optional
      // fields on top of RequestLog, so the row is a valid (if sparse) detail —
      // no unsafe cast needed.
      setDetailLog({ ...r });
    } finally {
      if (detailReqRef.current === reqId) setDetailLoading(false);
    }
  }

  if (logs.loading) return <Loading />;
  if (logs.error) return <ErrorText error={logs.error} />;
  const data = logs.data;
  if (!data) return null;

  return (
    <>
      <div
        style={{
          marginBottom: 12,
          display: "flex",
          flexWrap: "wrap",
          gap: 8,
          alignItems: "flex-end",
        }}
      >
        {/* Field filters + time window + clear, grouped on the left. */}
        <SearchSelect
          ariaLabel={tr("logs.model" as TK)}
          placeholder={tr("logs.filterModel" as TK)}
          value={filters.model}
          options={(options.data?.models ?? []).map((m) => ({ value: m, label: m }))}
          onChange={(v) => setFilter("model", v)}
        />
        <SearchSelect
          ariaLabel={tr("logs.user" as TK)}
          placeholder={tr("logs.filterUser" as TK)}
          value={filters.user_sub}
          options={(options.data?.users ?? []).map((u) => ({
            value: u.sub,
            label: u.name,
          }))}
          onChange={(v) => setFilter("user_sub", v)}
        />
        <SearchSelect
          ariaLabel={tr("logs.token" as TK)}
          placeholder={tr("logs.filterToken" as TK)}
          value={filters.token_id}
          options={(options.data?.tokens ?? []).map((tk) => ({
            value: String(tk.id),
            label: tk.name,
            sublabel: tk.user_name,
          }))}
          onChange={(v) => setFilter("token_id", v)}
        />
        <Dropdown
          aria-label={tr("logs.provider" as TK)}
          placeholder={tr("logs.filterProvider" as TK)}
          style={{ minWidth: 150 }}
          clearable
          selectedOptions={filters.provider ? [filters.provider] : []}
          value={filters.provider}
          onOptionSelect={(_, d) => setFilter("provider", d.optionValue ?? "")}
        >
          {(options.data?.providers ?? []).map((p) => (
            <Option key={p} value={p} text={p}>
              {p}
            </Option>
          ))}
        </Dropdown>
        <Input
          aria-label={tr("logs.ip" as TK)}
          placeholder={tr("logs.filterIp" as TK)}
          value={filters.client_ip}
          style={{ minWidth: 130, maxWidth: 160 }}
          onChange={(_, d) => setFilter("client_ip", d.value)}
        />
        <Input
          aria-label={tr("logs.status" as TK)}
          placeholder={tr("logs.filterStatus" as TK)}
          value={filters.status}
          style={{ minWidth: 96, maxWidth: 120 }}
          onChange={(_, d) => setFilter("status", d.value)}
          onBlur={() => setFilter("status", normalizeStatus(filters.status))}
        />
        <Dropdown
          aria-label={tr("logs.filterReqStatus" as TK)}
          placeholder={tr("logs.filterReqStatus" as TK)}
          style={{ minWidth: 130 }}
          clearable
          selectedOptions={filters.req_status ? [filters.req_status] : []}
          value={filters.req_status ? tr(REQ_STATUS_LABEL[filters.req_status]) : ""}
          onOptionSelect={(_, d) => setFilter("req_status", d.optionValue ?? "")}
        >
          {REQ_STATUS_VALUES.map((s) => (
            <Option key={s} value={s} text={tr(REQ_STATUS_LABEL[s])}>
              {tr(REQ_STATUS_LABEL[s])}
            </Option>
          ))}
        </Dropdown>
        <TimeRangeFilter
          mode={filters.timeMode}
          start={filters.start}
          end={filters.end}
          onChange={(next) => {
            setOffset(0);
            setFilters((f) => ({ ...f, ...next }));
          }}
        />
        {hasFilters ? (
          <Button
            appearance="subtle"
            icon={<DismissRegular />}
            onClick={() => {
              setOffset(0);
              setFilters(EMPTY_REQUEST_FILTERS);
            }}
          >
            {tr("logs.clearFilters" as TK)}
          </Button>
        ) : null}
        {/* Flexible gap pushes the jump-to-id tool cluster to the far right. */}
        <span style={{ flex: "1 1 auto", minWidth: 8 }} />
        <div style={{ display: "flex", gap: 8, alignItems: "flex-end", flexWrap: "nowrap" }}>
          <Input
            aria-label={tr("logs.goToId" as TK)}
            placeholder={tr("logs.goToId" as TK)}
            value={goToId}
            type="number"
            style={{ minWidth: 120 }}
            onChange={(_, d) => setGoToId(d.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void jumpToId();
            }}
          />
          <Tooltip content={tr("logs.jump" as TK)} relationship="label">
            <Button
              icon={<ArrowEnterRegular />}
              disabled={!goToId.trim()}
              onClick={() => void jumpToId()}
              aria-label={tr("logs.jump" as TK)}
            >
              {tr("logs.jump" as TK)}
            </Button>
          </Tooltip>
        </div>
      </div>
      {liveEnabled ? (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            marginBottom: 8,
            padding: "6px 10px",
            borderRadius: 6,
            background: tokens.colorNeutralBackground3,
            color: tokens.colorNeutralForeground2,
            fontSize: 12,
          }}
        >
          <Badge
            color={liveNotice ? "danger" : "success"}
            appearance="filled"
            size="small"
          >
            {liveNotice
              ? tr("logs.liveError" as TK)
              : tr("logs.liveOn" as TK)}
          </Badge>
          <Text size={200} style={{ color: tokens.colorNeutralForeground3 }}>
            {liveNotice ?? tr("logs.liveHint" as TK)}
          </Text>
        </div>
      ) : null}
      <div ref={containerRef}>
      <DataTable ariaLabel={tr("logs.requests" as TK)} minWidth={960}>
        <TableHeader>
          <TableRow>
            <TableHeaderCell>{tr("logs.id" as TK)}</TableHeaderCell>
            <TableHeaderCell>{tr("logs.time" as TK)}</TableHeaderCell>
            <TableHeaderCell>{tr("logs.user" as TK)}</TableHeaderCell>
            <TableHeaderCell>{tr("logs.token" as TK)}</TableHeaderCell>
            <TableHeaderCell>{tr("logs.model" as TK)}</TableHeaderCell>
            <TableHeaderCell>{tr("logs.colClientIp" as TK)}</TableHeaderCell>
            <TableHeaderCell>{tr("logs.colReqStatus" as TK)}</TableHeaderCell>
            <TableHeaderCell>{tr("logs.status" as TK)}</TableHeaderCell>
            <TableHeaderCell>{tr("logs.colTtft" as TK)}</TableHeaderCell>
            <TableHeaderCell>{tr("logs.colDuration" as TK)}</TableHeaderCell>
            <TableHeaderCell>{tr("logs.tokens" as TK)}</TableHeaderCell>
            <TableHeaderCell>{tr("logs.tries" as TK)}</TableHeaderCell>
            <TableHeaderCell style={{ width: 96 }} />
          </TableRow>
        </TableHeader>
        <TableBody>
          {allRows.map((r) => (
            <TableRow
              key={r.id}
              data-log-row={r.id}
              className={r.id === highlightId ? hl.row : undefined}
            >
              <TableCell
                style={{
                  color: tokens.colorNeutralForeground3,
                  fontFamily: "monospace",
                  whiteSpace: "nowrap",
                }}
              >
                {r.id}
              </TableCell>
              <TableCell style={{ color: tokens.colorNeutralForeground3 }}>
                {formatDate(r.started_at ?? r.ts)}
              </TableCell>
              <TableCell>
                {r.user_sub ? (
                  <button
                    type="button"
                    className={cellStyles.clickable}
                    title={tr("logs.clickToFilter" as TK)}
                    onClick={() => setFilter("user_sub", r.user_sub ?? "")}
                  >
                    {r.user_name ?? r.user_sub}
                  </button>
                ) : (
                  "—"
                )}
              </TableCell>
              <TableCell style={{ color: tokens.colorNeutralForeground3 }}>
                {r.token_id != null ? (
                  <div>
                    <button
                      type="button"
                      className={cellStyles.clickable}
                      title={tr("logs.clickToFilter" as TK)}
                      onClick={() => setFilter("token_id", String(r.token_id))}
                    >
                      {r.token_name ?? `#${r.token_id}`}
                    </button>
                    {r.token_owner_name ? (
                      <Text size={100} block style={{ color: tokens.colorNeutralForeground3 }}>
                        {r.token_owner_name}
                      </Text>
                    ) : null}
                  </div>
                ) : (
                  "—"
                )}
              </TableCell>
              <TableCell>
                {r.model ? (
                  <button
                    type="button"
                    className={cellStyles.clickable}
                    title={tr("logs.clickToFilter" as TK)}
                    onClick={() => setFilter("model", r.model ?? "")}
                  >
                    {r.model}
                  </button>
                ) : (
                  "—"
                )}
              </TableCell>
              <TableCell
                style={{
                  color: tokens.colorNeutralForeground3,
                  fontFamily: "monospace",
                  fontSize: 12,
                  // Reserve room for an IPv4 address plus a little slack; longer
                  // values (IPv6) are ellipsized by the cell.
                  maxWidth: 130,
                  whiteSpace: "nowrap",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                }}
              >
                {r.client_ip ? (
                  <button
                    type="button"
                    className={cellStyles.clickable}
                    title={tr("logs.clickToFilter" as TK)}
                    onClick={() => setFilter("client_ip", r.client_ip ?? "")}
                  >
                    {r.client_ip.length > MAX_IP_CHARS ? (
                      <Tooltip content={r.client_ip} relationship="label">
                        <span>{truncateIp(r.client_ip)}</span>
                      </Tooltip>
                    ) : (
                      r.client_ip
                    )}
                  </button>
                ) : (
                  "—"
                )}
              </TableCell>
              <TableCell>
                <Badge
                  color={
                    r.req_status === "completed" ? "success" :
                    r.req_status === "pending" ? "warning" :
                    r.req_status === "cancelled" ? "subtle" :
                    r.req_status === "terminated" ? "danger" :
                    r.req_status === "error" ? "danger" : "subtle"
                  }
                  appearance="filled"
                >
                  {r.req_status === "pending" ? tr("logs.reqStatusPending" as TK) :
                   r.req_status === "completed" ? tr("logs.reqStatusCompleted" as TK) :
                   r.req_status === "cancelled" ? tr("logs.reqStatusCancelled" as TK) :
                   r.req_status === "terminated" ? tr("logs.reqStatusTerminated" as TK) :
                   r.req_status === "error" ? tr("logs.reqStatusError" as TK) :
                   (r.req_status ?? "—")}
                </Badge>
              </TableCell>
              <TableCell>
                <button
                  type="button"
                  className={cellStyles.clickable}
                  title={tr("logs.clickToFilter" as TK)}
                  onClick={() =>
                    setFilter(
                      "status",
                      r.status_code != null ? String(r.status_code) : "",
                    )
                  }
                >
                  <Badge
                    color={r.success ? "success" : "danger"}
                    appearance="filled"
                    style={{ cursor: "pointer" }}
                  >
                    {r.status_code ?? "ERR"}
                  </Badge>
                </button>
              </TableCell>
              <TableCell style={{ color: tokens.colorNeutralForeground3 }}>
                {r.first_token_ms != null ? `${Math.round(r.first_token_ms)}ms` : "—"}
              </TableCell>
              <TableCell
                style={{
                  color: tokens.colorNeutralForeground3,
                  fontFamily: "monospace",
                  fontSize: 12,
                  whiteSpace: "nowrap",
                }}
              >
                {formatDuration(requestDurationMs(r, durationNow, liveEnabled))}
                {r.req_status === "pending" && liveEnabled ? (
                  <Text size={100} style={{ color: tokens.colorNeutralForeground3 }}>
                    {" · …"}
                  </Text>
                ) : null}
              </TableCell>
              <TableCell>{r.total_tokens}</TableCell>
              <TableCell>{r.attempts}</TableCell>
              <TableCell>
                <div style={{ display: "flex", gap: 4 }}>
                  <Tooltip content={tr("logs.viewDetail" as TK)} relationship="label">
                    <Button
                      size="small"
                      appearance="subtle"
                      icon={<InfoRegular />}
                      disabled={detailLoading}
                      aria-label={tr("logs.viewDetail" as TK)}
                      onClick={() => openDetail(r, "info")}
                    />
                  </Tooltip>
                  {/* Debug detail is owner / co-owner only, and only exists for
                      rows recorded in debug mode. */}
                  {isOwner && r.debug ? (
                    <Tooltip content={tr("logs.viewDebug" as TK)} relationship="label">
                      <Button
                        size="small"
                        appearance="subtle"
                        icon={<BugRegular />}
                        disabled={detailLoading}
                        aria-label={tr("logs.viewDebug" as TK)}
                        onClick={() => openDetail(r, "debug")}
                      />
                    </Tooltip>
                  ) : null}
                </div>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </DataTable>
      </div>
      <Pager
        total={data.total}
        offset={offset}
        limit={pageSize}
        onChange={setOffset}
      />

      {/* Detail modal */}
      <Dialog
        open={detailLog !== null}
        onOpenChange={(_, d) => {
          if (!d.open) {
            detailReqRef.current = null;
            setDetailLog(null);
          }
        }}
      >
        <DialogSurface style={{ maxWidth: 820, width: "100%" }}>
          <DialogBody>
            <DialogTitle>
              {tr("logs.requestDetailTitle" as TK).replace("{id}", String(detailLog?.id ?? ""))}
              {detailMode === "debug" ? (
                <Badge color="warning" appearance="tint" style={{ marginLeft: 8 }}>debug</Badge>
              ) : null}
            </DialogTitle>
            <DialogContent>
              {detailLog && (
                <div style={{ display: "flex", flexDirection: "column", gap: 12, fontFamily: tokens.fontFamilyBase }}>
                  {/* Summary grid */}
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "4px 16px", fontSize: tokens.fontSizeBase200 }}>
                    <DetailRow label={tr("logs.time" as TK)} value={formatDate(detailLog.ts)} />
                    <DetailRow label={tr("logs.startedAt" as TK)} value={detailLog.started_at ? formatDateMs(detailLog.started_at) : "—"} />
                    {detailLog.finished_at ? <DetailRow label={tr("logs.finishedAt" as TK)} value={formatDateMs(detailLog.finished_at)} /> : null}
                    {detailLog.first_token_ms != null ? <DetailRow label={tr("logs.colTtft" as TK)} value={`${Math.round(detailLog.first_token_ms)}ms`} /> : null}
                    <DetailRow label={tr("logs.colDuration" as TK)} value={formatDuration(requestDurationMs(detailLog, Date.now(), liveEnabled))} />
                    <DetailRow
                      label={tr("logs.colReqStatus" as TK)}
                      value={
                        detailLog.req_status
                          ? tr(REQ_STATUS_LABEL[detailLog.req_status] ?? "")
                          : "—"
                      }
                    />
                    <DetailRow label={tr("logs.colClientIp" as TK)} value={detailLog.client_ip ?? "—"} />
                    <DetailRow label={tr("logs.status" as TK)} value={detailLog.success ? `${detailLog.status_code} OK` : `${detailLog.status_code ?? "ERR"}`} />
                    <DetailRow label={tr("logs.user" as TK)} value={detailLog.user_name ?? detailLog.user_sub ?? "—"} />
                    <DetailRow
                      label={tr("logs.token" as TK)}
                      value={
                        detailLog.token_owner_name
                          ? `${detailLog.token_name ?? (detailLog.token_id != null ? `#${detailLog.token_id}` : "—")} (${detailLog.token_owner_name})`
                          : detailLog.token_name ?? (detailLog.token_id != null ? `#${detailLog.token_id}` : "—")
                      }
                    />
                    <DetailRow label={tr("logs.model" as TK)} value={detailLog.model ?? "—"} />
                    {detailLog.upstream_model &&
                    detailLog.upstream_model !== detailLog.model ? (
                      <DetailRow
                        label={tr("logs.modelRoute" as TK)}
                        value={`${detailLog.model ?? "?"} → ${detailLog.upstream_model}`}
                      />
                    ) : null}
                    <DetailRow label={tr("logs.provider" as TK)} value={detailLog.provider_name ?? "—"} />
                    <DetailRow label={tr("logs.key" as TK)} value={detailLog.key_preview ?? (detailLog.key_id != null ? `#${detailLog.key_id}` : "—")} />
                    <DetailRow label={tr("logs.proxy" as TK)} value={detailLog.proxy_url ?? (detailLog.proxy_id != null ? `#${detailLog.proxy_id}` : "—")} />
                    <DetailRow label={tr("logs.route" as TK)} value={`${detailLog.inbound_style ?? "?"}→${detailLog.upstream_style ?? "?"}`} />
                    <DetailRow label={tr("logs.stream" as TK)} value={detailLog.stream ? "yes" : "no"} />
                    <DetailRow label={tr("logs.tries" as TK)} value={String(detailLog.attempts)} />
                    <DetailRow label={tr("logs.tokens" as TK)} value={`${detailLog.prompt_tokens}+${detailLog.completion_tokens}=${detailLog.total_tokens}`} />
                    {detailLog.latency_ms != null && <DetailRow label={tr("logs.latency" as TK)} value={`${Math.round(detailLog.latency_ms)}ms`} />}
                    {detailLog.upstream_url && <DetailRow label={tr("logs.upstreamUrl" as TK)} value={detailLog.upstream_url} />}
                    <DetailRow label={tr("logs.userAgent" as TK)} value={detailLog.user_agent ?? "—"} />
                    <DetailRow label={tr("logs.clientType" as TK)} value={detailLog.client_type ?? "—"} />
                    <DetailRow label={tr("logs.opencode" as TK)} value={detailLog.is_opencode ? "yes" : "no"} />
                  </div>

                  {detailLog.error && (
                    <div>
                      <Text size={200} weight="semibold" block style={{ color: tokens.colorPaletteRedForeground1, marginBottom: 2 }}>
                        {tr("logs.error" as TK)}
                      </Text>
                      <Text size={200} block style={{ color: tokens.colorPaletteRedForeground1, fontFamily: "monospace", whiteSpace: "pre-wrap", wordBreak: "break-all" }}>
                        {detailLog.error}
                      </Text>
                    </div>
                  )}

                  {detailLog.attempts_summary && detailLog.attempts_summary.length > 0 ? (
                    <AttemptTrail attempts={detailLog.attempts_summary} />
                  ) : null}

                  {/* Debug view — owner / co-owner only, only reachable via the
                      dedicated debug button on a debug-recorded row. */}
                  {detailMode === "debug" && (
                    <div style={{ borderTop: `1px solid ${tokens.colorNeutralStroke2}`, paddingTop: 8 }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
                        <Text size={200} weight="semibold">{tr("logs.debugData" as TK)}</Text>
                        {isOwner && (
                          <Button
                            size="small"
                            appearance={revealMode ? "primary" : "subtle"}
                            icon={<EyeRegular />}
                            onClick={() => setRevealMode(!revealMode)}
                          >
                            {revealMode ? tr("logs.revealOn" as TK) : tr("logs.revealSecret" as TK)}
                          </Button>
                        )}
                      </div>
                      {isOwner ? (
                        <>
                          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "4px 16px", fontSize: tokens.fontSizeBase200, marginBottom: 8 }}>
                            <DetailRow label={tr("logs.method" as TK)} value={detailLog.req_method ?? "—"} />
                            <DetailRow label={tr("logs.upstreamUrl" as TK)} value={detailLog.upstream_url ?? "—"} />
                            <DetailRow label={tr("logs.proxy" as TK)} value={detailLog.proxy_url ?? (detailLog.proxy_id != null ? `#${detailLog.proxy_id}` : "—")} />
                            <DetailRow label={tr("logs.key" as TK)} value={detailLog.key_preview ?? (detailLog.key_id != null ? `#${detailLog.key_id}` : "—")} />
                          </div>
                          <CodeBlock label={tr("logs.reqHeaders" as TK)} value={detailLog.req_headers} />
                          <CodeBlock label={tr("logs.reqBody" as TK)} value={detailLog.req_body} />
                          <CodeBlock label={tr("logs.respHeaders" as TK)} value={detailLog.resp_headers} />
                          <CodeBlock label={tr("logs.respBody" as TK)} value={detailLog.resp_body} />
                          {detailLog.debug_attempts && detailLog.debug_attempts.length > 0 ? (
                            <AttemptTrail attempts={detailLog.debug_attempts} />
                          ) : null}
                        </>
                      ) : (
                        <Text size={200} style={{ color: tokens.colorNeutralForeground3 }}>
                          {tr("logs.debugOwnerOnly" as TK)}
                        </Text>
                      )}
                    </div>
                  )}
                </div>
              )}
            </DialogContent>
            <DialogActions>
              <Button appearance="primary" onClick={() => { detailReqRef.current = null; setDetailLog(null); }}>
                {tr("common.close" as TK)}
              </Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </>
  );
}

function DetailRow({ label, value }: { label: string; value: string }) {
  return (
    <>
      <Text size={200} weight="semibold" style={{ color: tokens.colorNeutralForeground3 }}>{label}</Text>
      <Text size={200} style={{ wordBreak: "break-all" }}>{value}</Text>
    </>
  );
}

function CodeBlock({ label, value }: { label: string; value: unknown }) {
  if (value == null) return null;
  const str = typeof value === "string" ? value : JSON.stringify(value, null, 2);
  if (!str || str === "{}" || str === "null") return null;
  return (
    <div style={{ marginBottom: 6 }}>
      <Text size={200} weight="semibold" block style={{ color: tokens.colorNeutralForeground3, marginBottom: 2 }}>
        {label}
      </Text>
      <pre style={{
        margin: 0,
        padding: 8,
        fontSize: tokens.fontSizeBase100,
        fontFamily: "monospace",
        background: tokens.colorNeutralBackground3,
        borderRadius: tokens.borderRadiusMedium,
        maxHeight: 240,
        overflow: "auto",
        whiteSpace: "pre-wrap",
        wordBreak: "break-all",
      }}>
        {str}
      </pre>
    </div>
  );
}

function AttemptTrail({ attempts }: { attempts: RequestLogAttempt[] }) {
  const { t } = useTranslation();
  type TK = keyof Translations;
  return (
    <div style={{ marginTop: 8 }}>
      <Text
        size={200}
        weight="semibold"
        block
        style={{ color: tokens.colorNeutralForeground3, marginBottom: 4 }}
      >
        {t("logs.attempts" as TK)} ({attempts.length})
      </Text>
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {attempts.map((a, i) => {
          const ok =
            !a.network_error &&
            a.status_code != null &&
            a.status_code >= 200 &&
            a.status_code < 300;
          const statusLabel = a.network_error
            ? t("logs.networkError" as TK)
            : (a.status_code ?? "ERR");
          return (
            <div
              key={a.attempt ?? i}
              style={{
                border: `1px solid ${tokens.colorNeutralStroke2}`,
                borderRadius: tokens.borderRadiusMedium,
                padding: 8,
              }}
            >
              <div
                style={{
                  display: "flex",
                  flexWrap: "wrap",
                  alignItems: "center",
                  gap: 8,
                  marginBottom: 6,
                }}
              >
                <Badge appearance="tint" color="informative">
                  #{a.attempt ?? i + 1}
                </Badge>
                <Badge appearance="filled" color={ok ? "success" : "danger"}>
                  {statusLabel}
                </Badge>
                {a.error_class ? (
                  <Badge appearance="outline">{a.error_class}</Badge>
                ) : null}
                <Text size={200} style={{ color: tokens.colorNeutralForeground3 }}>
                  {a.provider ?? "—"}
                  {a.upstream_model ? ` · ${a.upstream_model}` : ""}
                  {a.key_preview ? ` · ${a.key_preview}` : ""}
                  {a.proxy_url ? ` · ${a.proxy_url}` : ` · ${t("logs.direct" as TK)}`}
                  {a.duration_ms != null ? ` · ${Math.round(a.duration_ms)}ms` : ""}
                </Text>
              </div>
              <Text
                size={200}
                block
                style={{
                  color: tokens.colorNeutralForeground3,
                  fontFamily: "monospace",
                  wordBreak: "break-all",
                  marginBottom: 4,
                }}
              >
                {`${a.method ?? "POST"} ${a.url ?? "—"}`}
              </Text>
              {a.error ? (
                <Text
                  size={200}
                  block
                  style={{
                    color: tokens.colorPaletteRedForeground1,
                    fontFamily: "monospace",
                    whiteSpace: "pre-wrap",
                    wordBreak: "break-all",
                    marginBottom: 4,
                  }}
                >
                  {a.error}
                </Text>
              ) : null}
              <CodeBlock label={t("logs.reqHeaders" as TK)} value={a.req_headers} />
              <CodeBlock label={t("logs.reqBody" as TK)} value={a.req_body} />
              <CodeBlock label={t("logs.respHeaders" as TK)} value={a.resp_headers} />
              <CodeBlock label={t("logs.respBody" as TK)} value={a.resp_body} />
            </div>
          );
        })}
      </div>
    </div>
  );
}

interface AuditFilters {
  scope: string;
  action: string;
  target_type: string;
  actor_sub: string;
  ip: string;
  user_agent: string;
  // Time window. `timeMode` is UI-only (drives the preset dropdown); `start`/
  // `end` are absolute ISO instants sent to the backend.
  timeMode: TimeMode;
  start: string;
  end: string;
}

const EMPTY_FILTERS: AuditFilters = {
  scope: "",
  action: "",
  target_type: "",
  actor_sub: "",
  ip: "",
  user_agent: "",
  timeMode: "",
  start: "",
  end: "",
};

function auditFiltersFromParams(params: URLSearchParams): AuditFilters {
  return {
    ...EMPTY_FILTERS,
    scope: params.get("scope") || "",
    action: params.get("action") || "",
    target_type: params.get("target_type") || "",
    actor_sub: params.get("actor_sub") || "",
    ip: params.get("ip") || "",
    user_agent: params.get("user_agent") || "",
  };
}

function AuditLogs({
  refreshKey,
  pageSize,
}: {
  refreshKey: number;
  pageSize: number;
}) {
  const { t: ta } = useTranslation();
  type TK = keyof Translations;
  const { isOwner } = useAuth();
  const confirm = useConfirm();
  const notify = useNotify();
  const hl = useHighlightStyles();
  const cellStyles = useFilterStyles();
  const [searchParams] = useSearchParams();
  const [offset, setOffset] = useState(0);
  const [filters, setFilters] = useState<AuditFilters>(() =>
    auditFiltersFromParams(searchParams),
  );
  const [goToId, setGoToId] = useState("");
  const [revealed, setRevealed] = useState<{
    action: string;
    sensitive: unknown;
  } | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setFilters(auditFiltersFromParams(searchParams));
    setOffset(0);
  }, [searchParams]);

  const options = useAsync<AuditFilterOptions>(
    () => api.get("/api/admin/logs/audit/filters"),
    [],
  );

  // Free-text IP / user-agent filter every keystroke; debounce so we fetch once
  // each value settles (500ms of no typing) instead of firing a request per character.
  const debouncedIp = useDebouncedValue(filters.ip, 500);
  const debouncedUa = useDebouncedValue(filters.user_agent, 500);

  const queryParams = {
    scope: filters.scope || undefined,
    action: filters.action || undefined,
    target_type: filters.target_type || undefined,
    actor_sub: filters.actor_sub || undefined,
    ip: debouncedIp || undefined,
    user_agent: debouncedUa || undefined,
    start: filters.start || undefined,
    end: filters.end || undefined,
  };

  const logs = useAsync<Page<AuditLog>>(
    () =>
      api.get("/api/admin/logs/audit", {
        limit: pageSize,
        offset,
        ...queryParams,
      }),
    [
      offset,
      filters.scope,
      filters.action,
      filters.target_type,
      filters.actor_sub,
      debouncedIp,
      debouncedUa,
      filters.start,
      filters.end,
      refreshKey,
      pageSize,
    ],
  );
  const { highlightId, containerRef, markJump } = useIdJump(logs.data);

  async function jumpToId() {
    const id = Number(goToId.trim());
    if (Number.isNaN(id) || id <= 0) return;
    try {
      const r = await api.get<{ offset: number; found: boolean }>(
        "/api/admin/logs/audit/locate",
        { id, ...queryParams },
      );
      if (!r.found) {
        notify(ta("logs.jumpNotFound" as TK), `#${id}`, "warning");
        return;
      }
      setOffset(Math.floor(r.offset / pageSize) * pageSize);
      markJump(id);
    } catch (e) {
      notify(
        ta("logs.jumpFailed" as TK),
        e instanceof Error ? e.message : String(e),
        "error",
      );
    }
  }

  function setFilter<K extends keyof AuditFilters>(
    key: K,
    value: AuditFilters[K],
  ) {
    setOffset(0);
    setFilters((f) => ({ ...f, [key]: value }));
  }

  const hasFilters = Object.values(filters).some((v) => v !== "");
  const opts = options.data;
  const scopeLabel = (s: string) =>
    s === "admin"
      ? ta("common.admin" as TK)
        : s === "self"
          ? ta("common.self" as TK)
        : s === "system"
          ? ta("common.system" as TK)
          : s;
  // Each scope renders as a coloured pill wrapping its own icon, so the three
  // are told apart at a glance: admin (privileged) red, self (own action) blue,
  // system (automated/background) amber. Unknown scopes fall back to a neutral
  // text badge.
  const scopeMeta = (
    s: string,
  ): { icon: ReactElement; color: BadgeProps["color"] } | null => {
    if (s === "admin") return { icon: <LockClosedRegular />, color: "danger" };
    if (s === "self") return { icon: <PersonRegular />, color: "informative" };
    if (s === "system") return { icon: <SettingsRegular />, color: "warning" };
    return null;
  };

  async function reveal(a: AuditLog) {
    const ok = await confirm({
      title: ta("logs.revealTitle" as TK),
      message: ta("logs.revealMsg" as TK),
      confirmLabel: ta("logs.revealLabel" as TK),
      tone: "danger",
    });
    if (!ok) return;
    setBusy(true);
    try {
      const r = await api.post<{ action: string; sensitive: unknown }>(
        `/api/admin/logs/audit/${a.id}/reveal`,
      );
      setRevealed({ action: r.action, sensitive: r.sensitive });
    } catch (e) {
      notify(
        ta("logs.revealFailed" as TK),
        e instanceof Error ? e.message : String(e),
        "error",
      );
    } finally {
      setBusy(false);
    }
  }

  const data = logs.data;

  return (
    <>
      <div
        style={{
          marginBottom: 12,
          display: "flex",
          flexWrap: "wrap",
          gap: 8,
          alignItems: "flex-end",
        }}
      >
        <Dropdown
          aria-label={ta("logs.scope" as TK)}
          placeholder={ta("logs.filterScope" as TK)}
          style={{ minWidth: 120 }}
          selectedOptions={filters.scope ? [filters.scope] : []}
          value={filters.scope ? scopeLabel(filters.scope) : ""}
          onOptionSelect={(_, d) => setFilter("scope", d.optionValue ?? "")}
        >
          {(opts?.scopes ?? []).map((s) => (
            <Option key={s} value={s} text={scopeLabel(s)}>
              {scopeLabel(s)}
            </Option>
          ))}
        </Dropdown>
        <Dropdown
          aria-label={ta("logs.action" as TK)}
          placeholder={ta("logs.filterAction" as TK)}
          style={{ minWidth: 170 }}
          selectedOptions={filters.action ? [filters.action] : []}
          value={filters.action}
          onOptionSelect={(_, d) => setFilter("action", d.optionValue ?? "")}
        >
          {(opts?.actions ?? []).map((a) => (
            <Option key={a} value={a} text={a}>
              {a}
            </Option>
          ))}
        </Dropdown>
        <Dropdown
          aria-label={ta("logs.target" as TK)}
          placeholder={ta("logs.filterTarget" as TK)}
          style={{ minWidth: 130 }}
          selectedOptions={filters.target_type ? [filters.target_type] : []}
          value={filters.target_type}
          onOptionSelect={(_, d) =>
            setFilter("target_type", d.optionValue ?? "")
          }
        >
          {(opts?.target_types ?? []).map((tt) => (
            <Option key={tt} value={tt} text={tt}>
              {tt}
            </Option>
          ))}
        </Dropdown>
        <SearchSelect
          ariaLabel={ta("logs.actor" as TK)}
          placeholder={ta("logs.filterActor" as TK)}
          value={filters.actor_sub}
          options={(opts?.actors ?? []).map((a) => ({
            value: a.sub,
            label: a.name,
          }))}
          onChange={(v) => setFilter("actor_sub", v)}
        />
        <Input
          aria-label={ta("logs.ip" as TK)}
          placeholder={ta("logs.filterIp" as TK)}
          value={filters.ip}
          style={{ minWidth: 130 }}
          onChange={(_, d) => setFilter("ip", d.value)}
        />
        <Input
          aria-label={ta("logs.userAgent" as TK)}
          placeholder={ta("logs.filterUa" as TK)}
          value={filters.user_agent}
          style={{ minWidth: 150 }}
          onChange={(_, d) => setFilter("user_agent", d.value)}
        />
        <TimeRangeFilter
          mode={filters.timeMode}
          start={filters.start}
          end={filters.end}
          onChange={(next) => {
            setOffset(0);
            setFilters((f) => ({ ...f, ...next }));
          }}
        />
        {hasFilters ? (
          <Button
            appearance="subtle"
            icon={<DismissRegular />}
            onClick={() => {
              setOffset(0);
              setFilters(EMPTY_FILTERS);
            }}
          >
            {ta("logs.clearFilters" as TK)}
          </Button>
        ) : null}
        {/* Flexible gap pushes the jump-to-id tool cluster to the far right. */}
        <span style={{ flex: "1 1 auto", minWidth: 8 }} />
        <div style={{ display: "flex", gap: 8, alignItems: "flex-end", flexWrap: "nowrap" }}>
          <Input
            aria-label={ta("logs.goToId" as TK)}
            placeholder={ta("logs.goToId" as TK)}
            value={goToId}
            type="number"
            style={{ minWidth: 120 }}
            onChange={(_, d) => setGoToId(d.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void jumpToId();
            }}
          />
          <Tooltip content={ta("logs.jump" as TK)} relationship="label">
            <Button
              icon={<ArrowEnterRegular />}
              disabled={!goToId.trim()}
              onClick={() => void jumpToId()}
              aria-label={ta("logs.jump" as TK)}
            >
              {ta("logs.jump" as TK)}
            </Button>
          </Tooltip>
        </div>
      </div>

      {logs.loading ? (
        <Loading />
      ) : logs.error ? (
        <ErrorText error={logs.error} />
      ) : !data ? null : (
        <>
          <div ref={containerRef}>
          <DataTable ariaLabel={ta("logs.audit" as TK)} minWidth={1020}>
            <TableHeader>
              <TableRow>
                <TableHeaderCell>{ta("logs.id" as TK)}</TableHeaderCell>
                <TableHeaderCell>{ta("logs.time" as TK)}</TableHeaderCell>
                <TableHeaderCell>{ta("logs.actor" as TK)}</TableHeaderCell>
                <TableHeaderCell>{ta("logs.scope" as TK)}</TableHeaderCell>
                <TableHeaderCell>{ta("logs.action" as TK)}</TableHeaderCell>
                <TableHeaderCell>{ta("logs.target" as TK)}</TableHeaderCell>
                <TableHeaderCell>{ta("logs.detail" as TK)}</TableHeaderCell>
                <TableHeaderCell>{ta("logs.ip" as TK)}</TableHeaderCell>
                <TableHeaderCell>{ta("logs.userAgent" as TK)}</TableHeaderCell>
                {isOwner ? <TableHeaderCell>{ta("logs.sensitive" as TK)}</TableHeaderCell> : null}
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.items.map((a) => (
                <TableRow
                  key={a.id}
                  data-log-row={a.id}
                  className={a.id === highlightId ? hl.row : undefined}
                >
                  <TableCell style={{ color: tokens.colorNeutralForeground3, fontFamily: "monospace" }}>
                    {a.id}
                  </TableCell>
                  <TableCell style={{ color: tokens.colorNeutralForeground3 }}>
                    {formatDate(a.ts)}
                  </TableCell>
                  <TableCell>
                    {a.actor_sub ? (
                      <button
                        type="button"
                        className={cellStyles.clickable}
                        title={ta("logs.clickToFilter" as TK)}
                        onClick={() => setFilter("actor_sub", a.actor_sub ?? "")}
                      >
                        {a.actor_name ?? a.actor_sub}
                      </button>
                    ) : (
                      "—"
                    )}
                  </TableCell>
                  <TableCell>
                    <button
                      type="button"
                      className={cellStyles.clickable}
                      title={ta("logs.clickToFilter" as TK)}
                      onClick={() => setFilter("scope", a.scope)}
                    >
                      <Tooltip content={scopeLabel(a.scope)} relationship="label">
                        {(() => {
                          const meta = scopeMeta(a.scope);
                          return meta ? (
                            <Badge
                              appearance="tint"
                              color={meta.color}
                              icon={meta.icon}
                              aria-label={scopeLabel(a.scope)}
                            />
                          ) : (
                            <Badge appearance="tint">{scopeLabel(a.scope)}</Badge>
                          );
                        })()}
                      </Tooltip>
                    </button>
                  </TableCell>
                  <TableCell>
                    <button
                      type="button"
                      className={cellStyles.clickable}
                      title={ta("logs.clickToFilter" as TK)}
                      onClick={() => setFilter("action", a.action)}
                    >
                      {a.action}
                    </button>
                  </TableCell>
                  <TableCell>
                    {a.target_type ? (
                      <button
                        type="button"
                        className={cellStyles.clickable}
                        title={ta("logs.clickToFilter" as TK)}
                        onClick={() => setFilter("target_type", a.target_type ?? "")}
                      >
                        {`${a.target_type}#${a.target_id ?? ""}`}
                      </button>
                    ) : (
                      "—"
                    )}
                  </TableCell>
                  <TableCell style={{ maxWidth: 280 }}>
                    <DetailCell detail={a.detail} />
                  </TableCell>
                  <TableCell>
                    {a.ip ? (
                      <button
                        type="button"
                        className={cellStyles.clickable}
                        title={ta("logs.clickToFilter" as TK)}
                        onClick={() => setFilter("ip", a.ip ?? "")}
                      >
                        {a.ip}
                      </button>
                    ) : (
                      "—"
                    )}
                  </TableCell>
                  <TableCell>
                    {a.user_agent ? (
                      <Tooltip content={a.user_agent} relationship="label" positioning="above">
                        <button
                          type="button"
                          className={cellStyles.clickable}
                          title={ta("logs.clickToFilter" as TK)}
                          onClick={() => setFilter("user_agent", a.user_agent ?? "")}
                          style={{ color: tokens.colorNeutralForeground3 }}
                        >
                          {a.user_agent.length > 20 ? `${a.user_agent.slice(0, 20)}…` : a.user_agent}
                        </button>
                      </Tooltip>
                    ) : "—"}
                  </TableCell>
                  {isOwner ? (
                    <TableCell>
                      {a.has_sensitive ? (
                        <Tooltip
                          content={ta("common.reveal" as TK)}
                          relationship="label"
                        >
                          <Button
                            size="small"
                            appearance="subtle"
                            icon={<EyeRegular />}
                            disabled={busy}
                            onClick={() => reveal(a)}
                            aria-label={ta("common.reveal" as TK)}
                          />
                        </Tooltip>
                      ) : (
                        "—"
                      )}
                    </TableCell>
                  ) : null}
                </TableRow>
              ))}
            </TableBody>
          </DataTable>
          </div>
          <Pager
            total={data.total}
            offset={offset}
            limit={pageSize}
            onChange={setOffset}
          />
        </>
      )}

      <Dialog
        open={revealed !== null}
        onOpenChange={(_, d) => !d.open && setRevealed(null)}
      >
        <DialogSurface>
          <DialogBody>
            <DialogTitle>{`${ta("logs.sensitiveTitle" as TK)} · ${revealed?.action}`}</DialogTitle>
            <DialogContent>
              <Text
                size={200}
                block
                style={{ color: tokens.colorNeutralForeground3, marginBottom: 8 }}
              >
                {ta("logs.sensitiveHint" as TK)}
              </Text>
              <Textarea
                readOnly
                value={
                  revealed ? JSON.stringify(revealed.sensitive, null, 2) : ""
                }
                rows={12}
                style={{ width: "100%", fontFamily: "monospace" }}
              />
            </DialogContent>
            <DialogActions>
              <Button appearance="primary" onClick={() => setRevealed(null)}>
                {ta("common.close" as TK)}
              </Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </>
  );
}

function DetailCell({ detail }: { detail: Record<string, unknown> }) {
  const str = JSON.stringify(detail);
  if (str.length <= 30) {
    return (
      <Text size={200} style={{ color: tokens.colorNeutralForeground3 }}>
        {str}
      </Text>
    );
  }
  return (
    <Tooltip content={str} relationship="label" positioning="above" withArrow>
      <Text
        size={200}
        style={{
          color: tokens.colorNeutralForeground3,
          cursor: "default",
          display: "-webkit-box",
          WebkitLineClamp: 2,
          WebkitBoxOrient: "vertical",
          overflow: "hidden",
          textOverflow: "ellipsis",
        }}
      >
        {str}
      </Text>
    </Tooltip>
  );
}
