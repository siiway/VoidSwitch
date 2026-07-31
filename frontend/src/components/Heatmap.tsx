import { Text, tokens } from "@fluentui/react-components";
import { useTranslation } from "react-i18next";
import type { Translations } from "../i18n/locales/en";
import type { Heatmap as HeatmapData } from "../api/types";

type TK = keyof Translations;

// Full number, grouped by locale — deliberately NOT abbreviated to 万/亿 or K/M,
// per the requirement that the heatmap shows exact token counts.
function fullNumber(n: number): string {
  return n.toLocaleString();
}

// GitHub-style five-step green scale. Level 0 (no activity) uses a neutral tile so
// it reads as "empty" against both light and dark themes.
const EMPTY_COLOR = tokens.colorNeutralBackground3;
const LEVEL_COLORS = [
  "rgba(56, 158, 82, 0.25)",
  "rgba(56, 158, 82, 0.5)",
  "rgba(56, 158, 82, 0.75)",
  "rgba(56, 158, 82, 1)",
];

const CELL = 12; // px, square side
const GAP = 3; // px, between cells

function levelColor(tokensUsed: number, peak: number): string {
  if (tokensUsed <= 0) return EMPTY_COLOR;
  if (peak <= 0) return LEVEL_COLORS[0];
  const idx = Math.min(3, Math.max(0, Math.ceil((tokensUsed / peak) * 4) - 1));
  return LEVEL_COLORS[idx];
}

function utcToday(): Date {
  const n = new Date();
  return new Date(Date.UTC(n.getUTCFullYear(), n.getUTCMonth(), n.getUTCDate()));
}

function isoDay(d: Date): string {
  return d.toISOString().slice(0, 10);
}

interface Cell {
  date: string;
  tokens: number;
  requests: number;
  inRange: boolean;
}

// Build weeks (columns) of 7 days (rows, Sun→Sat) spanning the retention window
// up to today, aligned to week boundaries so the grid is rectangular.
function buildWeeks(data: HeatmapData): { weeks: Cell[][]; monthLabels: (string | null)[] } {
  const byDate = new Map(data.days.map((d) => [d.date, d]));
  const end = utcToday();
  const window = Math.max(1, data.window_days);
  const rangeStart = new Date(end);
  rangeStart.setUTCDate(rangeStart.getUTCDate() - (window - 1));

  // Back the grid start up to the Sunday on/before rangeStart.
  const gridStart = new Date(rangeStart);
  gridStart.setUTCDate(gridStart.getUTCDate() - gridStart.getUTCDay());

  const weeks: Cell[][] = [];
  const monthLabels: (string | null)[] = [];
  const cursor = new Date(gridStart);

  while (cursor <= end) {
    const week: Cell[] = [];
    let labelForWeek: string | null = null;
    for (let i = 0; i < 7; i++) {
      const iso = isoDay(cursor);
      const hit = byDate.get(iso);
      const inRange = cursor >= rangeStart && cursor <= end;
      // The first row of the week decides the month label: show it when this
      // week is the first one that falls inside a new month.
      if (i === 0 && cursor.getUTCDate() <= 7 && inRange) {
        labelForWeek = String(cursor.getUTCMonth() + 1);
      }
      week.push({
        date: iso,
        tokens: hit?.tokens ?? 0,
        requests: hit?.requests ?? 0,
        inRange,
      });
      cursor.setUTCDate(cursor.getUTCDate() + 1);
    }
    weeks.push(week);
    monthLabels.push(labelForWeek);
  }
  return { weeks, monthLabels };
}

function useFormatDuration(): (seconds: number) => string {
  const { t } = useTranslation();
  return (seconds: number) => {
    if (seconds <= 0) return "—";
    const d = Math.floor(seconds / 86400);
    const h = Math.floor((seconds % 86400) / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.floor(seconds % 60);
    const parts: string[] = [];
    if (d) parts.push(`${d}${t("heatmap.unitDay" as TK)}`);
    if (h) parts.push(`${h}${t("heatmap.unitHour" as TK)}`);
    if (m) parts.push(`${m}${t("heatmap.unitMinute" as TK)}`);
    if (!d && !h && !m) parts.push(`${s}${t("heatmap.unitSecond" as TK)}`);
    return parts.join(" ");
  };
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ padding: 14, minWidth: 120, flex: "1 1 120px", border: "1px solid var(--colorNeutralStroke1)", borderRadius: "10px" }}>
      <Text size={200} style={{ color: tokens.colorNeutralForeground3 }} block>
        {label}
      </Text>
      <Text size={600} weight="bold">
        {value}
      </Text>
    </div>
  );
}

export function Heatmap({ data, title }: { data: HeatmapData; title?: string }) {
  const { t } = useTranslation();
  const formatDuration = useFormatDuration();
  const { weeks, monthLabels } = buildWeeks(data);
  const peak = data.stats.peak_tokens;

  const monthTrackHeight = 16;

  return (
    <div style={{ marginBottom: 24 }}>
      {title ? (
        <Text size={500} weight="semibold" block style={{ marginBottom: 12 }}>
          {title}
        </Text>
      ) : null}

      <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginBottom: 16 }}>
        <StatCard
          label={t("heatmap.cumulativeTokens" as TK)}
          value={fullNumber(data.stats.cumulative_tokens)}
        />
        <StatCard
          label={t("heatmap.peakTokens" as TK)}
          value={fullNumber(data.stats.peak_tokens)}
        />
        <StatCard
          label={t("heatmap.longestTask" as TK)}
          value={formatDuration(data.stats.longest_task_seconds)}
        />
        <StatCard
          label={t("heatmap.currentStreak" as TK)}
          value={`${data.stats.current_streak}${t("heatmap.unitDay" as TK)}`}
        />
        <StatCard
          label={t("heatmap.longestStreak" as TK)}
          value={`${data.stats.longest_streak}${t("heatmap.unitDay" as TK)}`}
        />
      </div>

      <div style={{ overflowX: "auto", paddingBottom: 4 }}>
        <div style={{ display: "inline-flex", flexDirection: "column", gap: 4 }}>
          {/* Month labels aligned to their week column. */}
          <div
            style={{
              display: "flex",
              gap: GAP,
              height: monthTrackHeight,
              paddingLeft: 0,
            }}
          >
            {weeks.map((_, wi) => (
              <div
                key={wi}
                style={{
                  width: CELL,
                  fontSize: tokens.fontSizeBase100,
                  color: tokens.colorNeutralForeground3,
                  whiteSpace: "nowrap",
                }}
              >
                {monthLabels[wi]
                  ? t("heatmap.monthLabel" as TK).replace(
                      "{month}",
                      monthLabels[wi] as string,
                    )
                  : ""}
              </div>
            ))}
          </div>

          {/* Week columns. */}
          <div style={{ display: "flex", gap: GAP }}>
            {weeks.map((week, wi) => (
              <div key={wi} style={{ display: "flex", flexDirection: "column", gap: GAP }}>
                {week.map((cell) => {
                  if (!cell.inRange) {
                    return (
                      <div
                        key={cell.date}
                        style={{ width: CELL, height: CELL, borderRadius: 2 }}
                      />
                    );
                  }
                  const tip = t("heatmap.cellTooltip" as TK)
                    .replace("{date}", cell.date)
                    .replace("{tokens}", fullNumber(cell.tokens));
                  return (
                    <div
                      key={cell.date}
                      title={tip}
                      style={{
                        width: CELL,
                        height: CELL,
                        borderRadius: 2,
                        backgroundColor: levelColor(cell.tokens, peak),
                        outline: `1px solid ${tokens.colorNeutralStroke2}`,
                        outlineOffset: -1,
                      }}
                    />
                  );
                })}
              </div>
            ))}
          </div>

          {/* Legend. */}
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 6,
              marginTop: 6,
              fontSize: tokens.fontSizeBase100,
              color: tokens.colorNeutralForeground3,
            }}
          >
            <span>{t("heatmap.less" as TK)}</span>
            <span
              style={{ width: CELL, height: CELL, borderRadius: 2, backgroundColor: EMPTY_COLOR }}
            />
            {LEVEL_COLORS.map((c) => (
              <span
                key={c}
                style={{ width: CELL, height: CELL, borderRadius: 2, backgroundColor: c }}
              />
            ))}
            <span>{t("heatmap.more" as TK)}</span>
          </div>
        </div>
      </div>
    </div>
  );
}
