import {
  Button,
  Card,
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  Link,
  Switch,
  Tab,
  TabList,
  TableBody,
  TableCell,
  TableHeader,
  TableHeaderCell,
  TableRow,
  Text,
  tokens,
} from "@fluentui/react-components";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import type { Translations } from "../i18n/locales/en";
import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
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
    <Card style={{ padding: 18, minWidth: 150, flex: "1 1 150px" }}>
      <Text size={200} style={{ color: tokens.colorNeutralForeground3 }} block>
        {label}
      </Text>
      <Text size={800} weight="bold" style={{ color: accent }}>
        {value}
      </Text>
    </Card>
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

function Breakdown({
  title,
  keyHeader,
  rows,
  t,
  onLabelClick,
}: {
  title: string;
  keyHeader: string;
  rows: UsageGroupRow[];
  t: (key: string) => string;
  // When provided, each row's label becomes a clickable link (used to open a
  // user's activity heatmap from the "By user" breakdown).
  onLabelClick?: (row: UsageGroupRow) => void;
}) {
  const [chart, setChart] = useState(false);

  return (
    <div style={{ marginBottom: 24 }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginBottom: 8,
        }}
      >
        <Text size={400} weight="semibold">
          {title}
        </Text>
        <Switch
          label={chart ? t("stats.chart" as any) : t("stats.table" as any)}
          labelPosition="before"
          checked={chart}
          onChange={(_, d) => setChart(d.checked)}
        />
      </div>
      {rows.length === 0 ? (
        <Text size={200} style={{ color: tokens.colorNeutralForeground3 }}>
          {t("common.noData" as any)}
        </Text>
      ) : chart ? (
        <PieChart rows={rows} valueKey="requests" />
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
            {rows.map((r) => (
              <TableRow key={r.key || r.label}>
                <TableCell>
                  {onLabelClick && r.key ? (
                    <Link as="button" onClick={() => onLabelClick(r)}>
                      {r.label}
                    </Link>
                  ) : (
                    r.label
                  )}
                  {r.sublabel ? (
                    <Text
                      size={100}
                      style={{
                        color: tokens.colorNeutralForeground3,
                        marginLeft: 6,
                      }}
                    >
                      ({r.sublabel})
                    </Text>
                  ) : null}
                </TableCell>
                <TableCell>{nf(r.requests)}</TableCell>
                <TableCell
                  style={{ color: tokens.colorPaletteGreenForeground1 }}
                >
                  {nf(r.success)}
                </TableCell>
                <TableCell
                  style={{ color: tokens.colorPaletteRedForeground1 }}
                >
                  {nf(r.failures)}
                </TableCell>
                <TableCell>{nf(r.total_tokens)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </DataTable>
      )}
    </div>
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
  const { isStaff } = useAuth();
  const [gran, setGran] = useState<Granularity>("daily");
  const [heatmapUser, setHeatmapUser] = useState<{ sub: string; label: string } | null>(
    null,
  );
  const stats = useAsync<UsageAnalytics>(() => api.get("/api/usage"));

  const granularities: { value: Granularity; label: string }[] = [
    { value: "daily", label: t("stats.daily" as TK) },
    { value: "weekly", label: t("stats.weekly" as TK) },
    { value: "monthly", label: t("stats.monthly" as TK) },
    { value: "yearly", label: t("stats.yearly" as TK) },
  ];

  return (
    <div>
      <PageHeader
        title={t("stats.title" as TK)}
        subtitle={t("stats.subtitle" as TK)}
        onRefresh={stats.reload}
      />

      {stats.loading ? (
        <Loading />
      ) : stats.error ? (
        <ErrorText error={stats.error} />
      ) : stats.data ? (
        <>
          <div
            style={{
              display: "flex",
              gap: 12,
              flexWrap: "wrap",
              marginBottom: 24,
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
          </div>

          <Text size={500} weight="semibold" block style={{ marginBottom: 12 }}>
            {t("stats.overTime" as TK)}
          </Text>
          <TabList
            selectedValue={gran}
            onTabSelect={(_, d) => setGran(d.value as Granularity)}
            style={{ marginBottom: 12 }}
          >
            {granularities.map((g) => (
              <Tab key={g.value} value={g.value}>
                {g.label}
              </Tab>
            ))}
          </TabList>
          <div style={{ marginBottom: 28 }}>
            <TimeSeries buckets={stats.data[gran]} t={t as any} />
          </div>

          {isStaff ? (
            <Breakdown
              title={t("stats.byUser" as TK)}
              keyHeader={t("stats.userCol" as TK)}
              rows={stats.data.by_user}
              t={t as any}
              onLabelClick={(row) =>
                setHeatmapUser({ sub: row.key, label: row.label })
              }
            />
          ) : null}
          <Breakdown
            title={t("stats.byToken" as TK)}
            keyHeader={t("stats.tokenCol" as TK)}
            rows={stats.data.by_token}
            t={t as any}
          />
          <Breakdown
            title={t("stats.byModel" as TK)}
            keyHeader={t("stats.modelCol" as TK)}
            rows={stats.data.by_model}
            t={t as any}
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
