import {
  Button,
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  Dropdown,
  Input,
  Link,
  MessageBar,
  MessageBarBody,
  Option,
  Switch,
  Tab,
  TabList,
  TableBody,
  TableCell,
  TableHeader,
  TableHeaderCell,
  TableRow,
  Text,
  Tooltip,
  tokens,
} from "@fluentui/react-components";
import {
  CalendarLtrRegular,
  ChevronDownRegular,
  ChevronRightRegular,
} from "@fluentui/react-icons";
import { useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import type { Translations } from "../i18n/locales/en";
import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { useOverTimeMode } from "../lib/prefs";
import type {
  Heatmap as HeatmapData,
  UsageAnalytics,
  UsageBucket,
  UsageGroupRow,
} from "../api/types";
import {
  DataTable,
  ErrorText,
  Loading,
  PageHeader,
  useAsync,
} from "../components/ui";
import { Heatmap } from "../components/Heatmap";

type Granularity = "daily" | "weekly" | "monthly" | "yearly";

// Row-count choices for each breakdown section. 0 means "all".
const LIMIT_CHOICES = [5, 10, 15, 30, 50, 100, 0];
const DEFAULT_LIMIT = 15;

// --- page-wide time filter ------------------------------------------------- //

type TimePreset =
  | "today"
  | "week"
  | "month"
  | "year"
  | "all"
  | "pickDay"
  | "pickWeek"
  | "pickMonth"
  | "pickYear"
  | "custom";

interface TimeWindow {
  start?: string;
  end?: string;
}

function startOfDay(d: Date): Date {
  const x = new Date(d);
  x.setHours(0, 0, 0, 0);
  return x;
}
function addDays(d: Date, n: number): Date {
  const x = new Date(d);
  x.setDate(x.getDate() + n);
  return x;
}
function startOfWeek(d: Date): Date {
  // Monday-based week start.
  const x = startOfDay(d);
  const dow = (x.getDay() + 6) % 7;
  return addDays(x, -dow);
}
// Monday of a given ISO week (Jan 4 is always in ISO week 1).
function isoWeekMonday(year: number, week: number): Date {
  const jan4 = new Date(year, 0, 4);
  const jan4Dow = (jan4.getDay() + 6) % 7;
  const week1Monday = addDays(jan4, -jan4Dow);
  return addDays(week1Monday, (week - 1) * 7);
}

// Turn the current preset + picker value into an absolute [start, end) window.
// An empty object means "all time" (no bounds sent to the backend).
function computeWindow(
  preset: TimePreset,
  pick: string,
  customStart: string,
  customEnd: string,
): TimeWindow {
  const now = new Date();
  const iso = (d: Date) => d.toISOString();
  switch (preset) {
    case "all":
      return {};
    case "today": {
      const s = startOfDay(now);
      return { start: iso(s), end: iso(addDays(s, 1)) };
    }
    case "week": {
      const s = startOfWeek(now);
      return { start: iso(s), end: iso(addDays(s, 7)) };
    }
    case "month": {
      const s = new Date(now.getFullYear(), now.getMonth(), 1);
      const e = new Date(now.getFullYear(), now.getMonth() + 1, 1);
      return { start: iso(s), end: iso(e) };
    }
    case "year": {
      const s = new Date(now.getFullYear(), 0, 1);
      const e = new Date(now.getFullYear() + 1, 0, 1);
      return { start: iso(s), end: iso(e) };
    }
    case "pickDay": {
      if (!pick) return {};
      const [y, m, d] = pick.split("-").map(Number);
      if (!y || !m || !d) return {};
      const s = new Date(y, m - 1, d);
      return { start: iso(s), end: iso(addDays(s, 1)) };
    }
    case "pickWeek": {
      const mm = pick.match(/^(\d{4})-W(\d{2})$/);
      if (!mm) return {};
      const s = isoWeekMonday(Number(mm[1]), Number(mm[2]));
      return { start: iso(s), end: iso(addDays(s, 7)) };
    }
    case "pickMonth": {
      const [y, m] = pick.split("-").map(Number);
      if (!y || !m) return {};
      return {
        start: iso(new Date(y, m - 1, 1)),
        end: iso(new Date(y, m, 1)),
      };
    }
    case "pickYear": {
      const y = Number(pick);
      if (!y) return {};
      return { start: iso(new Date(y, 0, 1)), end: iso(new Date(y + 1, 0, 1)) };
    }
    case "custom": {
      const s = customStart ? new Date(customStart) : null;
      const e = customEnd ? new Date(customEnd) : null;
      return {
        start: s && !Number.isNaN(s.getTime()) ? iso(s) : undefined,
        end: e && !Number.isNaN(e.getTime()) ? iso(e) : undefined,
      };
    }
    default:
      return {};
  }
}

// Default picker value when entering a "pick a …" mode, so the filter is valid
// immediately instead of matching nothing.
function defaultPick(preset: TimePreset): string {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  switch (preset) {
    case "pickDay":
      return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
    case "pickWeek": {
      // ISO week number for today.
      const d = startOfDay(now);
      const dow = (d.getDay() + 6) % 7;
      const thursday = addDays(d, 3 - dow);
      const yearStart = new Date(thursday.getFullYear(), 0, 1);
      const week = Math.ceil(((+thursday - +yearStart) / 86400000 + 1) / 7);
      return `${thursday.getFullYear()}-W${pad(week)}`;
    }
    case "pickMonth":
      return `${now.getFullYear()}-${pad(now.getMonth() + 1)}`;
    case "pickYear":
      return String(now.getFullYear());
    default:
      return "";
  }
}

const PIE_COLORS = [
  tokens.colorBrandBackground,
  tokens.colorPaletteBerryForeground1,
  tokens.colorPaletteGreenForeground1,
  tokens.colorPaletteMarigoldForeground1,
  tokens.colorPaletteCranberryForeground2,
  tokens.colorPalettePlumForeground2,
  tokens.colorPaletteTealForeground2,
  tokens.colorPaletteLavenderForeground2,
  tokens.colorPaletteDarkOrangeForeground1,
  tokens.colorPaletteGreenForeground2,
];

function nf(n: number): string {
  return n.toLocaleString();
}

function fmtMs(v?: number | null): string {
  if (v == null) return "—";
  if (v < 1000) return `${Math.round(v)}ms`;
  return `${(v / 1000).toFixed(2)}s`;
}

function Stat({
  label,
  value,
  accent,
}: {
  label: string;
  value: number | string;
  accent?: string;
}) {
  return (
    <div style={{ padding: 16, minWidth: 150, flex: "1 1 150px", border: "1px solid var(--colorNeutralStroke1)", borderRadius: "10px" }}>
      <Text size={200} style={{ color: tokens.colorNeutralForeground3 }} block>
        {label}
      </Text>
      <Text size={800} weight="bold" style={{ color: accent }}>
        {value}
      </Text>
    </div>
  );
}

function Bar({ value, max }: { value: number; max: number }) {
  const pct = max > 0 ? Math.max(2, Math.round((value / max) * 100)) : 0;
  return (
    <div
      style={{
        height: 8,
        width: "100%",
        minWidth: 80,
        borderRadius: 4,
        backgroundColor: tokens.colorNeutralBackground4,
        overflow: "hidden",
      }}
    >
      <div
        style={{
          height: "100%",
          width: `${pct}%`,
          borderRadius: 4,
          backgroundColor: tokens.colorBrandBackground,
        }}
      />
    </div>
  );
}

function TimeSeries({
  buckets,
  t,
}: {
  buckets: UsageBucket[];
  t: (key: string) => string;
}) {
  if (buckets.length === 0) {
    return (
      <Text size={200} style={{ color: tokens.colorNeutralForeground3 }}>
        {t("stats.noActivity" as any)}
      </Text>
    );
  }
  const max = Math.max(...buckets.map((b) => b.requests), 1);
  const rows = [...buckets].reverse();
  return (
    <DataTable ariaLabel={t("stats.overTime" as any)} minWidth={720}>
      <TableHeader>
        <TableRow>
          <TableHeaderCell>{t("stats.period" as any)}</TableHeaderCell>
          <TableHeaderCell>{t("stats.volume" as any)}</TableHeaderCell>
          <TableHeaderCell>{t("stats.requests" as any)}</TableHeaderCell>
          <TableHeaderCell>{t("stats.success" as any)}</TableHeaderCell>
          <TableHeaderCell>{t("stats.failedCol" as any)}</TableHeaderCell>
          <TableHeaderCell>{t("stats.tokensCol" as any)}</TableHeaderCell>
          <TableHeaderCell>{t("stats.ttftCol" as any)}</TableHeaderCell>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((b) => (
          <TableRow key={b.period}>
            <TableCell>{b.period}</TableCell>
            <TableCell style={{ width: 180 }}>
              <Bar value={b.requests} max={max} />
            </TableCell>
            <TableCell>{nf(b.requests)}</TableCell>
            <TableCell style={{ color: tokens.colorPaletteGreenForeground1 }}>
              {nf(b.success)}
            </TableCell>
            <TableCell style={{ color: tokens.colorPaletteRedForeground1 }}>
              {nf(b.failures)}
            </TableCell>
            <TableCell>{nf(b.total_tokens)}</TableCell>
            <TableCell>{fmtMs(b.avg_first_token_ms)}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </DataTable>
  );
}

function polarToCartesian(
  cx: number,
  cy: number,
  r: number,
  angleDeg: number,
): { x: number; y: number } {
  const rad = ((angleDeg - 90) * Math.PI) / 180;
  return { x: cx + r * Math.cos(rad), y: cy + r * Math.sin(rad) };
}

function describeArc(
  cx: number,
  cy: number,
  r: number,
  startAngle: number,
  endAngle: number,
): string {
  const s = polarToCartesian(cx, cy, r, endAngle);
  const e = polarToCartesian(cx, cy, r, startAngle);
  const large = endAngle - startAngle > 180 ? 1 : 0;
  return `M ${cx} ${cy} L ${s.x} ${s.y} A ${r} ${r} 0 ${large} 0 ${e.x} ${e.y} Z`;
}

function PieChart({
  rows,
  valueKey,
}: {
  rows: UsageGroupRow[];
  valueKey: "requests" | "total_tokens";
}) {
  if (rows.length === 0) return null;
  const values = rows.map((r) => r[valueKey] ?? 0);
  const total = values.reduce((a, b) => a + b, 0);
  if (total === 0) return null;

  const size = 220;
  const cx = size / 2;
  const cy = size / 2;
  const r = 90;
  let cumulative = 0;
  const slices: {
    row: UsageGroupRow;
    color: string;
    path: string;
    pct: number;
  }[] = [];

  for (let i = 0; i < rows.length; i++) {
    const pct = values[i] / total;
    if (pct <= 0) continue;
    const startAngle = cumulative * 360;
    cumulative += pct;
    const endAngle = cumulative * 360;
    slices.push({
      row: rows[i],
      // Colour by the slice's own position so it stays in sync with the legend
      // even when zero-value rows are skipped.
      color: PIE_COLORS[slices.length % PIE_COLORS.length],
      path: describeArc(cx, cy, r, startAngle, endAngle),
      pct,
    });
  }

  // A single slice spans the full 360° — an SVG arc whose start and end points
  // coincide is omitted by the renderer, so draw a full circle instead.
  const singleFull = slices.length === 1;

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 24, flexWrap: "wrap" }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        {singleFull ? (
          <circle cx={cx} cy={cy} r={r} fill={slices[0].color} />
        ) : (
          slices.map((s, i) => <path key={i} d={s.path} fill={s.color} />)
        )}
      </svg>
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        {slices.map((s, i) => {
          const pct = (s.pct * 100).toFixed(1);
          return (
            <div
              key={i}
              style={{ display: "flex", alignItems: "center", gap: 8 }}
            >
              <span
                style={{
                  width: 10,
                  height: 10,
                  borderRadius: 2,
                  backgroundColor: s.color,
                  flexShrink: 0,
                }}
              />
              <Text size={200} style={{ maxWidth: 180 }}>
                {s.row.label}
                {s.row.sublabel ? (
                  <Text
                    size={100}
                    style={{ color: tokens.colorNeutralForeground3 }}
                  >
                    {" "}
                    ({s.row.sublabel})
                  </Text>
                ) : null}
              </Text>
              <Text
                size={200}
                weight="semibold"
                style={{ marginLeft: "auto", whiteSpace: "nowrap" }}
              >
                {pct}%
              </Text>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// A collapsible section shell: a chevron toggle + title on the left, optional
// controls on the right (only while expanded). Expanded by default.
function CollapsibleSection({
  title,
  t,
  right,
  children,
}: {
  title: string;
  t: (key: string) => string;
  right?: ReactNode;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(true);
  return (
    <div style={{ marginBottom: 24 }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 8,
          marginBottom: 8,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <Button
            appearance="subtle"
            size="small"
            icon={open ? <ChevronDownRegular /> : <ChevronRightRegular />}
            onClick={() => setOpen((o) => !o)}
            aria-label={open ? t("stats.collapse" as any) : t("stats.expand" as any)}
          />
          <Text size={400} weight="semibold">
            {title}
          </Text>
        </div>
        {open ? right : null}
      </div>
      {open ? children : null}
    </div>
  );
}

// The row-count limiter shown in each breakdown's header (after the chart toggle).
function LimitDropdown({
  value,
  onChange,
  t,
}: {
  value: number;
  onChange: (v: number) => void;
  t: (key: string) => string;
}) {
  const label = (v: number) => (v === 0 ? t("stats.limitAll" as any) : String(v));
  return (
    <Dropdown
      size="small"
      style={{ minWidth: 84 }}
      selectedOptions={[String(value)]}
      value={label(value)}
      aria-label={t("stats.limit" as any)}
      onOptionSelect={(_, d) => onChange(Number(d.optionValue ?? DEFAULT_LIMIT))}
    >
      {LIMIT_CHOICES.map((c) => (
        <Option key={c} value={String(c)} text={label(c)}>
          {label(c)}
        </Option>
      ))}
    </Dropdown>
  );
}

function Breakdown({
  title,
  keyHeader,
  rows,
  t,
  filterKey,
  onHeatmap,
}: {
  title: string;
  keyHeader: string;
  rows: UsageGroupRow[];
  t: (key: string) => string;
  // Which request-log filter this breakdown maps to. Clicking a row's label
  // jumps to the logs page with that filter applied.
  filterKey: "user_sub" | "token_id" | "model" | "provider";
  // Optional per-row action (the user breakdown offers an activity heatmap).
  onHeatmap?: (row: UsageGroupRow) => void;
}) {
  const navigate = useNavigate();
  const [chart, setChart] = useState(false);
  const [limit, setLimit] = useState(DEFAULT_LIMIT);
  const shown = limit === 0 ? rows : rows.slice(0, limit);

  const openInLogs = (row: UsageGroupRow) =>
    navigate(`/logs?${filterKey}=${encodeURIComponent(row.key)}`);

  const controls = (
    <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
      <Switch
        label={chart ? t("stats.chart" as any) : t("stats.table" as any)}
        labelPosition="before"
        checked={chart}
        onChange={(_, d) => setChart(d.checked)}
      />
      <LimitDropdown value={limit} onChange={setLimit} t={t} />
    </div>
  );

  return (
    <CollapsibleSection title={title} t={t} right={controls}>
      {rows.length === 0 ? (
        <Text size={200} style={{ color: tokens.colorNeutralForeground3 }}>
          {t("common.noData" as any)}
        </Text>
      ) : chart ? (
        <PieChart rows={shown} valueKey="requests" />
      ) : (
        <DataTable ariaLabel={t("stats.title" as any) + " - " + title} minWidth={640}>
          <TableHeader>
            <TableRow>
              <TableHeaderCell>{keyHeader}</TableHeaderCell>
              <TableHeaderCell>{t("stats.requests" as any)}</TableHeaderCell>
              <TableHeaderCell>{t("stats.success" as any)}</TableHeaderCell>
              <TableHeaderCell>{t("stats.failedCol" as any)}</TableHeaderCell>
              <TableHeaderCell>{t("stats.tokensCol" as any)}</TableHeaderCell>
            </TableRow>
          </TableHeader>
          <TableBody>
            {shown.map((r) => {
              // Rows with an empty key are synthetic ("<internal>") — greyed and
              // not linkable, since there's no concrete entity to filter on.
              const internal = !r.key;
              return (
                <TableRow key={r.key || r.label}>
                  <TableCell>
                    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                      {internal ? (
                        <Text style={{ color: tokens.colorNeutralForeground3 }}>
                          {r.label}
                        </Text>
                      ) : (
                        <Tooltip content={t("stats.openInLogs" as any)} relationship="label">
                          <Link as="button" onClick={() => openInLogs(r)}>
                            {r.label}
                          </Link>
                        </Tooltip>
                      )}
                      {r.sublabel ? (
                        <Text
                          size={100}
                          style={{ color: tokens.colorNeutralForeground3 }}
                        >
                          ({r.sublabel})
                        </Text>
                      ) : null}
                      {onHeatmap && !internal ? (
                        <Tooltip content={t("stats.viewHeatmap" as any)} relationship="label">
                          <Button
                            appearance="subtle"
                            size="small"
                            icon={<CalendarLtrRegular />}
                            aria-label={t("stats.viewHeatmap" as any)}
                            onClick={() => onHeatmap(r)}
                          />
                        </Tooltip>
                      ) : null}
                    </div>
                  </TableCell>
                  <TableCell>{nf(r.requests)}</TableCell>
                  <TableCell style={{ color: tokens.colorPaletteGreenForeground1 }}>
                    {nf(r.success)}
                  </TableCell>
                  <TableCell style={{ color: tokens.colorPaletteRedForeground1 }}>
                    {nf(r.failures)}
                  </TableCell>
                  <TableCell>{nf(r.total_tokens)}</TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </DataTable>
      )}
    </CollapsibleSection>
  );
}

// The page-wide time-range filter shown in the header.
function TimeFilter({
  preset,
  pick,
  customStart,
  customEnd,
  onChange,
  t,
}: {
  preset: TimePreset;
  pick: string;
  customStart: string;
  customEnd: string;
  onChange: (next: {
    preset: TimePreset;
    pick: string;
    customStart: string;
    customEnd: string;
  }) => void;
  t: (key: string) => string;
}) {
  const presetLabel: Record<TimePreset, string> = {
    today: t("stats.timeToday" as any),
    week: t("stats.timeThisWeek" as any),
    month: t("stats.timeThisMonth" as any),
    year: t("stats.timeThisYear" as any),
    all: t("stats.timeAll" as any),
    pickDay: t("stats.timePickDay" as any),
    pickWeek: t("stats.timePickWeek" as any),
    pickMonth: t("stats.timePickMonth" as any),
    pickYear: t("stats.timePickYear" as any),
    custom: t("stats.timeCustom" as any),
  };
  const order: TimePreset[] = [
    "today",
    "week",
    "month",
    "year",
    "all",
    "pickDay",
    "pickWeek",
    "pickMonth",
    "pickYear",
    "custom",
  ];

  const select = (next: TimePreset) => {
    if (next === "custom") {
      const now = new Date();
      const toLocal = (d: Date) => {
        const pad = (n: number) => String(n).padStart(2, "0");
        return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(
          d.getDate(),
        )}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
      };
      onChange({
        preset: "custom",
        pick,
        customStart: customStart || toLocal(addDays(now, -1)),
        customEnd: customEnd || toLocal(now),
      });
    } else if (next.startsWith("pick")) {
      onChange({ preset: next, pick: defaultPick(next), customStart, customEnd });
    } else {
      onChange({ preset: next, pick, customStart, customEnd });
    }
  };

  const pickType =
    preset === "pickDay"
      ? "date"
      : preset === "pickWeek"
        ? "week"
        : preset === "pickMonth"
          ? "month"
          : preset === "pickYear"
            ? "number"
            : null;

  return (
    <div style={{ display: "flex", gap: 8, alignItems: "flex-end", flexWrap: "wrap" }}>
      <Dropdown
        aria-label={t("stats.timeFilter" as any)}
        style={{ minWidth: 150 }}
        selectedOptions={[preset]}
        value={presetLabel[preset]}
        onOptionSelect={(_, d) => select((d.optionValue as TimePreset) ?? "today")}
      >
        {order.map((p) => (
          <Option key={p} value={p} text={presetLabel[p]}>
            {presetLabel[p]}
          </Option>
        ))}
      </Dropdown>
      {pickType ? (
        <Input
          type={pickType}
          aria-label={presetLabel[preset]}
          style={{ minWidth: pickType === "number" ? 110 : 170 }}
          value={pick}
          input={pickType === "number" ? { min: 2000, max: 2100 } : undefined}
          onChange={(_, d) =>
            onChange({ preset, pick: d.value, customStart, customEnd })
          }
        />
      ) : null}
      {preset === "custom" ? (
        <>
          <Input
            type="datetime-local"
            aria-label={t("stats.customStart" as any)}
            style={{ minWidth: 200 }}
            value={customStart}
            onChange={(_, d) =>
              onChange({ preset, pick, customStart: d.value, customEnd })
            }
          />
          <Text size={200} style={{ color: tokens.colorNeutralForeground3, paddingBottom: 6 }}>
            –
          </Text>
          <Input
            type="datetime-local"
            aria-label={t("stats.customEnd" as any)}
            style={{ minWidth: 200 }}
            value={customEnd}
            onChange={(_, d) =>
              onChange({ preset, pick, customStart, customEnd: d.value })
            }
          />
        </>
      ) : null}
    </div>
  );
}

// The "Over time" section — renders per the user's chosen mode (A/B/C).
function OverTimeSection({
  data,
  mode,
  t,
}: {
  data: UsageAnalytics;
  mode: "A" | "B" | "C";
  t: (key: string) => string;
}) {
  const [gran, setGran] = useState<Granularity>("daily");
  const granularities: { value: Granularity; label: string }[] = [
    { value: "daily", label: t("stats.daily" as any) },
    { value: "weekly", label: t("stats.weekly" as any) },
    { value: "monthly", label: t("stats.monthly" as any) },
    { value: "yearly", label: t("stats.yearly" as any) },
  ];

  const granName: Record<string, string> = {
    hour: t("stats.hourly" as any),
    day: t("stats.daily" as any),
    week: t("stats.weekly" as any),
    month: t("stats.monthly" as any),
    year: t("stats.yearly" as any),
  };

  if (mode === "B") {
    const g = data.windowed_granularity ?? "day";
    return (
      <CollapsibleSection
        title={t("stats.overTime" as any)}
        t={t}
        right={
          <Text size={200} style={{ color: tokens.colorNeutralForeground3 }}>
            {granName[g] ?? g}
          </Text>
        }
      >
        <TimeSeries buckets={data.windowed_series ?? []} t={t} />
      </CollapsibleSection>
    );
  }

  return (
    <CollapsibleSection
      title={t("stats.overTime" as any)}
      t={t}
      right={
        <TabList
          selectedValue={gran}
          onTabSelect={(_, d) => setGran(d.value as Granularity)}
        >
          {granularities.map((g) => (
            <Tab key={g.value} value={g.value}>
              {g.label}
            </Tab>
          ))}
        </TabList>
      }
    >
      <TimeSeries buckets={data[gran]} t={t} />
    </CollapsibleSection>
  );
}

// Staff-only popup: a specific user's activity heatmap, opened by clicking a
// username in the "By user" breakdown.
function UserHeatmapDialog({
  sub,
  label,
  onClose,
}: {
  sub: string;
  label: string;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  type TK = keyof Translations;
  const hm = useAsync<HeatmapData>(() =>
    api.get(`/api/usage/heatmap/user?sub=${encodeURIComponent(sub)}`),
  );
  return (
    <Dialog
      open
      onOpenChange={(_, d) => {
        if (!d.open) onClose();
      }}
      modalType="non-modal"
    >
      <DialogSurface style={{ maxWidth: 940, width: "100%" }}>
        <DialogBody>
          <DialogTitle>
            {t("heatmap.userDialogTitle" as TK).replace("{name}", label)}
          </DialogTitle>
          <DialogContent>
            {hm.loading ? (
              <Loading />
            ) : hm.error ? (
              <ErrorText error={hm.error} />
            ) : hm.data ? (
              <Heatmap data={hm.data} />
            ) : null}
          </DialogContent>
          <DialogActions>
            <Button onClick={onClose}>{t("common.close" as TK)}</Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}

export function Statistics() {
  const { t } = useTranslation();
  type TK = keyof Translations;
  const { isStaff, isRoleGroupAdmin, managedGroupIds, managedGroupNames } = useAuth();
  const [overTimeMode] = useOverTimeMode();
  const [heatmapUser, setHeatmapUser] = useState<{ sub: string; label: string } | null>(
    null,
  );

  // Page-wide time filter. Defaults to "today".
  const [preset, setPreset] = useState<TimePreset>("today");
  const [pick, setPick] = useState("");
  const [customStart, setCustomStart] = useState("");
  const [customEnd, setCustomEnd] = useState("");
  const timeWindow = useMemo(
    () => computeWindow(preset, pick, customStart, customEnd),
    [preset, pick, customStart, customEnd],
  );

  // Role-group-admin group filter. ``null`` = the whole managed set (backend
  // uses this when ``group_ids`` is omitted); a number = only that group. The
  // dropdown only appears when the caller administers >1 group.
  const [groupFilter, setGroupFilter] = useState<number | null>(null);

  const stats = useAsync<UsageAnalytics>(
    () =>
      api.get("/api/usage", {
        start: timeWindow.start,
        end: timeWindow.end,
        time_mode: overTimeMode,
        // Only send group_ids when we've narrowed to one; omitting the param
        // lets the backend use the caller's managed set (staff → all).
        ...(isRoleGroupAdmin && groupFilter != null
          ? { group_ids: String(groupFilter) }
          : {}),
      }),
    [timeWindow.start, timeWindow.end, overTimeMode, isRoleGroupAdmin, groupFilter],
  );

  return (
    <div>
      <PageHeader
        title={t("stats.title" as TK)}
        subtitle={t("stats.subtitle" as TK)}
        onRefresh={stats.reload}
        action={
          <TimeFilter
            preset={preset}
            pick={pick}
            customStart={customStart}
            customEnd={customEnd}
            onChange={(next) => {
              setPreset(next.preset);
              setPick(next.pick);
              setCustomStart(next.customStart);
              setCustomEnd(next.customEnd);
            }}
            t={t as any}
          />
        }
      />

      {/* Role-group admin hint bar — same shape as the Users page bar so the
          "which groups you administer" affordance is consistent across pages. */}
      {isRoleGroupAdmin && managedGroupNames.length > 0 && (
        <MessageBar intent="info" style={{ marginBottom: 12 }}>
          <MessageBarBody>
            {t("stats.roleGroupAdminHint" as TK).replace(
              "{groups}",
              managedGroupNames.join(", "),
            )}
          </MessageBarBody>
        </MessageBar>
      )}
      {isRoleGroupAdmin && managedGroupIds.length > 1 && (
        <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 12 }}>
          <Text size={200}>{t("stats.groupFilter" as TK)}</Text>
          <Dropdown
            style={{ minWidth: 180 }}
            value={
              groupFilter == null
                ? t("stats.groupFilterAll" as TK)
                : managedGroupNames[managedGroupIds.indexOf(groupFilter)] ??
                  String(groupFilter)
            }
            selectedOptions={[groupFilter == null ? "__all__" : String(groupFilter)]}
            onOptionSelect={(_, d) => {
              const v = d.optionValue;
              setGroupFilter(v == null || v === "__all__" ? null : Number(v));
            }}
          >
            <Option value="__all__" text={t("stats.groupFilterAll" as TK)}>
              {t("stats.groupFilterAll" as TK)}
            </Option>
            {managedGroupIds.map((gid, idx) => (
              <Option key={gid} value={String(gid)} text={managedGroupNames[idx] ?? String(gid)}>
                {managedGroupNames[idx] ?? String(gid)}
              </Option>
            ))}
          </Dropdown>
        </div>
      )}

      {stats.loading ? (
        <Loading />
      ) : stats.error ? (
        <ErrorText error={stats.error} />
      ) : stats.data ? (
        <>
          <CollapsibleSection title={t("stats.summary" as TK)} t={t as any}>
            <div
              style={{
                display: "flex",
                gap: 12,
                flexWrap: "wrap",
              }}
            >
              <Stat label={t("stats.totalRequests" as TK)} value={nf(stats.data.totals.requests)} />
              <Stat
                label={t("stats.succeeded" as TK)}
                value={nf(stats.data.totals.success)}
                accent={tokens.colorPaletteGreenForeground1}
              />
              <Stat
                label={t("stats.failed" as TK)}
                value={nf(stats.data.totals.failures)}
                accent={tokens.colorPaletteRedForeground1}
              />
              <Stat
                label={t("stats.tokensUsed" as TK)}
                value={nf(stats.data.totals.total_tokens)}
              />
              <Stat
                label={t("stats.successRate" as TK)}
                value={
                  stats.data.totals.requests > 0
                    ? `${((stats.data.totals.success / stats.data.totals.requests) * 100).toFixed(1)}%`
                    : "—"
                }
                accent={tokens.colorPaletteGreenForeground1}
              />
            </div>
          </CollapsibleSection>

          <CollapsibleSection title={t("stats.performance" as TK)} t={t as any}>
            <div
              style={{
                display: "flex",
                gap: 12,
                flexWrap: "wrap",
              }}
            >
              <Stat
                label={t("stats.avgTtft" as TK)}
                value={fmtMs(stats.data.performance.avg_first_token_ms)}
              />
              <Stat
                label={t("stats.avgLatency" as TK)}
                value={fmtMs(stats.data.performance.avg_latency_ms)}
              />
              <Stat
                label={t("stats.avgTokensPerReq" as TK)}
                value={stats.data.performance.avg_tokens_per_request}
              />
              <Stat
                label={t("stats.tokensPerSec" as TK)}
                value={
                  stats.data.performance.tokens_per_second != null
                    ? nf(stats.data.performance.tokens_per_second)
                    : "—"
                }
              />
            </div>
          </CollapsibleSection>

          <CollapsibleSection title={t("stats.quality" as TK)} t={t as any}>
            <div
              style={{
                display: "flex",
                gap: 12,
                flexWrap: "wrap",
                marginBottom: 16,
              }}
            >
              <Stat
                label={t("stats.streamed" as TK)}
                value={nf(stats.data.performance.stream_requests)}
              />
              <Stat
                label={t("stats.nonStreamed" as TK)}
                value={nf(stats.data.performance.non_stream_requests)}
              />
            </div>
            {stats.data.status_codes.length > 0 ? (
              <DataTable ariaLabel={t("stats.quality" as TK)} minWidth={400}>
                <TableHeader>
                  <TableRow>
                    <TableHeaderCell>{t("stats.statusCode" as TK)}</TableHeaderCell>
                    <TableHeaderCell>{t("stats.statusCodeCount" as TK)}</TableHeaderCell>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {stats.data.status_codes.map((s) => (
                    <TableRow key={s.status_code}>
                      <TableCell>{s.status_code}</TableCell>
                      <TableCell>{nf(s.count)}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </DataTable>
            ) : (
              <Text size={200} style={{ color: tokens.colorNeutralForeground3 }}>
                {t("common.noData" as any)}
              </Text>
            )}
          </CollapsibleSection>

          <OverTimeSection data={stats.data} mode={overTimeMode} t={t as any} />

          {isStaff ? (
            <Breakdown
              title={t("stats.byUser" as TK)}
              keyHeader={t("stats.userCol" as TK)}
              rows={stats.data.by_user}
              t={t as any}
              filterKey="user_sub"
              onHeatmap={(row) =>
                setHeatmapUser({ sub: row.key, label: row.label })
              }
            />
          ) : null}
          <Breakdown
            title={t("stats.byToken" as TK)}
            keyHeader={t("stats.tokenCol" as TK)}
            rows={stats.data.by_token}
            t={t as any}
            filterKey="token_id"
          />
          <Breakdown
            title={t("stats.byModel" as TK)}
            keyHeader={t("stats.modelCol" as TK)}
            rows={stats.data.by_model}
            t={t as any}
            filterKey="model"
          />
          <Breakdown
            title={t("stats.byProvider" as TK)}
            keyHeader={t("stats.providerCol" as TK)}
            rows={stats.data.by_provider}
            t={t as any}
            filterKey="provider"
          />
        </>
      ) : null}

      {heatmapUser ? (
        <UserHeatmapDialog
          sub={heatmapUser.sub}
          label={heatmapUser.label}
          onClose={() => setHeatmapUser(null)}
        />
      ) : null}
    </div>
  );
}
