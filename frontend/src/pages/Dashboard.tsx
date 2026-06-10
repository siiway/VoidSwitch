import { Badge, Card, Text, tokens } from "@fluentui/react-components";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import type { Stats, SystemInfo } from "../api/types";
import type { Translations } from "../i18n/locales/en";
import {
  ErrorText,
  Loading,
  PageHeader,
  formatDate,
  useAsync,
} from "../components/ui";

type TK = keyof Translations;

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
  const { t } = useTranslation();
  const stats = useAsync<Stats>(() => api.get("/api/admin/stats"));
  const system = useAsync<SystemInfo>(() => api.get("/api/admin/system"));

  return (
    <div>
      <PageHeader
        title={t("dashboard.title" as TK)}
        subtitle={t("dashboard.subtitle" as TK)}
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
              <Stat label={t("dashboard.providers" as TK)} value={stats.data.providers} />
              <Stat
                label={t("dashboard.activeKeys" as TK)}
                value={`${stats.data.active_keys}/${stats.data.total_keys}`}
                accent={tokens.colorPaletteGreenForeground1}
              />
              <Stat
                label={t("dashboard.activeProxies" as TK)}
                value={`${stats.data.active_proxies}/${stats.data.total_proxies}`}
              />
              <Stat label={t("dashboard.voidTokens" as TK)} value={stats.data.tokens} />
            </div>
            <div
              style={{
                display: "flex",
                gap: 12,
                flexWrap: "wrap",
                marginBottom: 24,
              }}
            >
              <Stat label={t("dashboard.requests24h" as TK)} value={stats.data.requests_24h} />
              <Stat
                label={t("dashboard.success24h" as TK)}
                value={stats.data.success_24h}
                accent={tokens.colorPaletteGreenForeground1}
              />
              <Stat
                label={t("dashboard.failed24h" as TK)}
                value={stats.data.failures_24h}
                accent={tokens.colorPaletteRedForeground1}
              />
              <Stat label={t("dashboard.tokens24h" as TK)} value={stats.data.tokens_24h} />
            </div>
          </>
        )
      )}

      <Text size={500} weight="semibold" block style={{ margin: "8px 0 12px" }}>
        {t("dashboard.backgroundTasks" as TK)}
      </Text>
      {system.data?.tasks.map((task) => (
        <Card key={task.name} style={{ padding: 14, marginBottom: 8 }}>
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
            }}
          >
            <div>
              <Text weight="semibold">{task.name}</Text>
              <Text
                size={200}
                block
                style={{ color: tokens.colorNeutralForeground3 }}
              >
                every {task.interval_seconds}s · {task.runs} runs · last{" "}
                {formatDate(task.last_run)}
                {task.last_error ? ` · error: ${task.last_error}` : ""}
              </Text>
            </div>
            <Badge color={task.enabled ? "success" : "subtle"} appearance="filled">
              {task.enabled ? t("common.enabled" as TK) : t("common.disabled" as TK)}
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
