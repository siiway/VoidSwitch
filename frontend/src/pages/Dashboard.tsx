import { Badge, Card, Text, tokens } from "@fluentui/react-components";
import { api } from "../api/client";
import type { Stats, SystemInfo } from "../api/types";
import {
  ErrorText,
  Loading,
  PageHeader,
  formatDate,
  useAsync,
} from "../components/ui";

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

export function Dashboard() {
  const stats = useAsync<Stats>(() => api.get("/api/admin/stats"));
  const system = useAsync<SystemInfo>(() => api.get("/api/admin/system"));

  return (
    <div>
      <PageHeader
        title="Dashboard"
        subtitle="Live gateway health and 24-hour activity"
      />
      {stats.loading ? (
        <Loading />
      ) : stats.error ? (
        <ErrorText error={stats.error} />
      ) : (
        stats.data && (
          <>
            <div
              style={{
                display: "flex",
                gap: 12,
                flexWrap: "wrap",
                marginBottom: 24,
              }}
            >
              <Stat label="Providers" value={stats.data.providers} />
              <Stat
                label="Active keys"
                value={`${stats.data.active_keys}/${stats.data.total_keys}`}
                accent={tokens.colorPaletteGreenForeground1}
              />
              <Stat
                label="Active proxies"
                value={`${stats.data.active_proxies}/${stats.data.total_proxies}`}
              />
              <Stat label="Void-Tokens" value={stats.data.tokens} />
            </div>
            <div
              style={{
                display: "flex",
                gap: 12,
                flexWrap: "wrap",
                marginBottom: 24,
              }}
            >
              <Stat label="Requests (24h)" value={stats.data.requests_24h} />
              <Stat
                label="Succeeded (24h)"
                value={stats.data.success_24h}
                accent={tokens.colorPaletteGreenForeground1}
              />
              <Stat
                label="Failed (24h)"
                value={stats.data.failures_24h}
                accent={tokens.colorPaletteRedForeground1}
              />
              <Stat label="Tokens used (24h)" value={stats.data.tokens_24h} />
            </div>
          </>
        )
      )}

      <Text size={500} weight="semibold" block style={{ margin: "8px 0 12px" }}>
        Background tasks
      </Text>
      {system.data?.tasks.map((t) => (
        <Card key={t.name} style={{ padding: 14, marginBottom: 8 }}>
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
            }}
          >
            <div>
              <Text weight="semibold">{t.name}</Text>
              <Text
                size={200}
                block
                style={{ color: tokens.colorNeutralForeground3 }}
              >
                every {t.interval_seconds}s · {t.runs} runs · last{" "}
                {formatDate(t.last_run)}
                {t.last_error ? ` · error: ${t.last_error}` : ""}
              </Text>
            </div>
            <Badge color={t.enabled ? "success" : "subtle"} appearance="filled">
              {t.enabled ? "enabled" : "disabled"}
            </Badge>
          </div>
        </Card>
      ))}
      {system.data ? (
        <Text size={200} style={{ color: tokens.colorNeutralForeground3 }}>
          VoidSwitch v{system.data.version}
        </Text>
      ) : null}
    </div>
  );
}
