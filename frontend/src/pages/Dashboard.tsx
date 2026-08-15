import { Badge, Text, tokens, makeStyles } from "@fluentui/react-components";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import type { HeatmapBundle, Stats, SystemInfo } from "../api/types";
import type { Translations } from "../i18n/locales/en";
import {
  ErrorText,
  Loading,
  PageHeader,
  formatDate,
  useAsync,
} from "../components/ui";
import { AnnouncementsPanel } from "../components/Announcements";
import { Heatmap } from "../components/Heatmap";

type TK = keyof Translations;

function HeatmapSection() {
  const { t } = useTranslation();
  const bundle = useAsync<HeatmapBundle>(() => api.get("/api/usage/heatmap"));

  if (bundle.loading) return <Loading />;
  if (bundle.error) return <ErrorText error={bundle.error} />;
  if (!bundle.data) return null;

  return (
    <div style={{ marginTop: 20 }}>
      {bundle.data.site ? (
        <Heatmap data={bundle.data.site} title={t("heatmap.siteTitle" as TK)} />
      ) : null}
      <Heatmap data={bundle.data.personal} title={t("heatmap.personalTitle" as TK)} />
    </div>
  );
}

interface MyUsage {
  requests: number;
  tokens: number;
  token_count: number;
}

const useStatStyles = makeStyles({
  card: {
    padding: "16px",
    minWidth: "150px",
    flex: "1 1 150px",
    border: `1px solid ${tokens.colorNeutralStroke1}`,
    borderRadius: "10px",
    background: tokens.colorNeutralBackground1,
    transition: "box-shadow 0.15s",
    ":hover": {
      borderTopColor: tokens.colorNeutralForeground1,
      borderRightColor: tokens.colorNeutralForeground1,
      borderBottomColor: tokens.colorNeutralForeground1,
      borderLeftColor: tokens.colorNeutralForeground1,
    },
  },
});

function Stat({
  label,
  value,
  accent,
}: {
  label: string;
  value: number | string;
  accent?: string;
}) {
  const styles = useStatStyles();
  return (
    <div className={styles.card}>
      <Text size={200} style={{ color: tokens.colorNeutralForeground3 }} block>
        {label}
      </Text>
      <Text size={800} weight="bold" style={{ color: accent }}>
        {value}
      </Text>
    </div>
  );
}

const useTaskStyles = makeStyles({
  card: {
    padding: "14px",
    marginBottom: "8px",
    border: `1px solid ${tokens.colorNeutralStroke2}`,
    borderRadius: "10px",
    background: tokens.colorNeutralBackground1,
    transition: "box-shadow 0.15s",
    ":hover": {
      borderTopColor: tokens.colorNeutralForeground1,
      borderRightColor: tokens.colorNeutralForeground1,
      borderBottomColor: tokens.colorNeutralForeground1,
      borderLeftColor: tokens.colorNeutralForeground1,
    },
  },
});

function MemberDashboard() {
  const { t } = useTranslation();
  const usage = useAsync<MyUsage>(() => api.get("/api/me/usage"));

  return (
    <div>
      <PageHeader
        title={t("dashboard.title" as TK)}
        subtitle={t("dashboard.subtitleMember" as TK)}
        onRefresh={usage.reload}
      />
      <AnnouncementsPanel />
      {usage.loading ? (
        <Loading />
      ) : usage.error ? (
        <ErrorText error={usage.error} />
      ) : usage.data ? (
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginBottom: 20 }}>
          <Stat label={t("dashboard.myRequests" as TK)} value={usage.data.requests} />
          <Stat
            label={t("dashboard.myTokens" as TK)}
            value={usage.data.tokens}
            accent={tokens.colorPaletteGreenForeground1}
          />
          <Stat label={t("dashboard.myApiKeys" as TK)} value={usage.data.token_count} />
        </div>
      ) : null}
      <HeatmapSection />
    </div>
  );
}

function StaffDashboard() {
  const { t } = useTranslation();
  const stats = useAsync<Stats>(() => api.get("/api/admin/stats"));
  const system = useAsync<SystemInfo>(() => api.get("/api/admin/system"));
  const taskStyles = useTaskStyles();

  return (
    <div>
      <PageHeader
        title={t("dashboard.title" as TK)}
        subtitle={t("dashboard.subtitle" as TK)}
        onRefresh={() => {
          stats.reload();
          system.reload();
        }}
      />
      <AnnouncementsPanel />
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
                marginBottom: 20,
              }}
            >
              <Stat label={t("dashboard.providers" as TK)} value={stats.data.providers} />
              <Stat
                label={t("dashboard.activeKeys" as TK)}
                value={`${stats.data.active_keys}/${stats.data.total_keys}`}
                accent={tokens.colorPaletteGreenForeground1}
              />
              <Stat label={t("dashboard.voidTokens" as TK)} value={stats.data.tokens} />
            </div>
            <div
              style={{
                display: "flex",
                gap: 12,
                flexWrap: "wrap",
                marginBottom: 20,
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
              <Stat
                label={t("dashboard.successRate24h" as TK)}
                value={`${stats.data.success_rate_24h}%`}
                accent={tokens.colorPaletteGreenForeground1}
              />
              <Stat label={t("dashboard.tokens24h" as TK)} value={stats.data.tokens_24h} />
              <Stat
                label={t("dashboard.avgTtft24h" as TK)}
                value={
                  stats.data.avg_first_token_ms_24h != null
                    ? `${Math.round(stats.data.avg_first_token_ms_24h)}ms`
                    : "—"
                }
              />
              <Stat
                label={t("dashboard.avgTokensPerReq24h" as TK)}
                value={stats.data.avg_tokens_per_request_24h}
              />
            </div>
          </>
        )
      )}

      <Text size={500} weight="semibold" block style={{ margin: "8px 0 12px" }}>
        {t("dashboard.backgroundTasks" as TK)}
      </Text>
      {system.data?.tasks.map((task) => (
        <div key={task.name} className={taskStyles.card}>
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
        </div>
      ))}
      <HeatmapSection />
      {system.data ? (
        <Text
          size={200}
          block
          style={{
            color: tokens.colorNeutralForeground3,
            marginTop: 20,
            textAlign: "center",
          }}
        >
          VoidSwitch v{system.data.version}
          {system.data.commit ? ` (${system.data.commit})` : ""}
        </Text>
      ) : null}
    </div>
  );
}

export function Dashboard() {
  const { isStaff } = useAuth();
  return isStaff ? <StaffDashboard /> : <MemberDashboard />;
}
