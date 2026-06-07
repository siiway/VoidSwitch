import {
  Card,
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
import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import type {
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

type Granularity = "daily" | "weekly" | "monthly" | "yearly";

const GRANULARITIES: { value: Granularity; label: string }[] = [
  { value: "daily", label: "Daily" },
  { value: "weekly", label: "Weekly" },
  { value: "monthly", label: "Monthly" },
  { value: "yearly", label: "Yearly" },
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

// A horizontal proportional bar used inside the time-series table to make
// volume differences scannable at a glance.
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

function TimeSeries({ buckets }: { buckets: UsageBucket[] }) {
  if (buckets.length === 0) {
    return (
      <Text size={200} style={{ color: tokens.colorNeutralForeground3 }}>
        No activity in this range yet.
      </Text>
    );
  }
  const max = Math.max(...buckets.map((b) => b.requests), 1);
  // Newest first reads better for a period overview.
  const rows = [...buckets].reverse();
  return (
    <DataTable ariaLabel="Usage over time" minWidth={720}>
      <TableHeader>
        <TableRow>
          <TableHeaderCell>Period</TableHeaderCell>
          <TableHeaderCell>Volume</TableHeaderCell>
          <TableHeaderCell>Requests</TableHeaderCell>
          <TableHeaderCell>Success</TableHeaderCell>
          <TableHeaderCell>Failed</TableHeaderCell>
          <TableHeaderCell>Tokens</TableHeaderCell>
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

function Breakdown({
  title,
  keyHeader,
  rows,
}: {
  title: string;
  keyHeader: string;
  rows: UsageGroupRow[];
}) {
  return (
    <div style={{ marginBottom: 24 }}>
      <Text size={400} weight="semibold" block style={{ marginBottom: 8 }}>
        {title}
      </Text>
      {rows.length === 0 ? (
        <Text size={200} style={{ color: tokens.colorNeutralForeground3 }}>
          No data yet.
        </Text>
      ) : (
        <DataTable ariaLabel={title} minWidth={640}>
          <TableHeader>
            <TableRow>
              <TableHeaderCell>{keyHeader}</TableHeaderCell>
              <TableHeaderCell>Requests</TableHeaderCell>
              <TableHeaderCell>Success</TableHeaderCell>
              <TableHeaderCell>Failed</TableHeaderCell>
              <TableHeaderCell>Tokens</TableHeaderCell>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((r) => (
              <TableRow key={r.key || r.label}>
                <TableCell>{r.label}</TableCell>
                <TableCell>{nf(r.requests)}</TableCell>
                <TableCell style={{ color: tokens.colorPaletteGreenForeground1 }}>
                  {nf(r.success)}
                </TableCell>
                <TableCell style={{ color: tokens.colorPaletteRedForeground1 }}>
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

export function Statistics() {
  const { isStaff } = useAuth();
  const [gran, setGran] = useState<Granularity>("daily");
  const stats = useAsync<UsageAnalytics>(() => api.get("/api/usage"));

  return (
    <div>
      <PageHeader
        title="Statistics"
        subtitle={
          isStaff
            ? "Platform-wide call volume, by period, user, token, and model"
            : "Your call volume, by period, token, and model"
        }
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
            <Stat label="Total requests" value={nf(stats.data.totals.requests)} />
            <Stat
              label="Succeeded"
              value={nf(stats.data.totals.success)}
              accent={tokens.colorPaletteGreenForeground1}
            />
            <Stat
              label="Failed"
              value={nf(stats.data.totals.failures)}
              accent={tokens.colorPaletteRedForeground1}
            />
            <Stat
              label="Tokens used"
              value={nf(stats.data.totals.total_tokens)}
            />
          </div>

          <Text size={500} weight="semibold" block style={{ marginBottom: 12 }}>
            Over time
          </Text>
          <TabList
            selectedValue={gran}
            onTabSelect={(_, d) => setGran(d.value as Granularity)}
            style={{ marginBottom: 12 }}
          >
            {GRANULARITIES.map((g) => (
              <Tab key={g.value} value={g.value}>
                {g.label}
              </Tab>
            ))}
          </TabList>
          <div style={{ marginBottom: 28 }}>
            <TimeSeries buckets={stats.data[gran]} />
          </div>

          {isStaff ? (
            <Breakdown
              title="By user"
              keyHeader="User"
              rows={stats.data.by_user}
            />
          ) : null}
          <Breakdown
            title="By token"
            keyHeader="Token"
            rows={stats.data.by_token}
          />
          <Breakdown
            title="By model"
            keyHeader="Model"
            rows={stats.data.by_model}
          />
        </>
      ) : null}
    </div>
  );
}
