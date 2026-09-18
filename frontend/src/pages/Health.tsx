import {
  Badge,
  Button,
  Dropdown,
  Option,
  Tab,
  TabList,
  Text,
  Tooltip,
  makeStyles,
  shorthands,
  tokens,
} from "@fluentui/react-components";
import { LiveRegular } from "@fluentui/react-icons";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { API_BASE, getToken } from "../api/client";
import type { ModelHealth, NodeHealth } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { PageHeader } from "../components/ui";
import type { Translations } from "../i18n/locales/en";

type TK = keyof Translations;
type HealthTab = "models" | "nodes";
type WindowKey = "30m" | "1h" | "3h" | "12h" | "1d" | "3d" | "7d";

const useStyles = makeStyles({
  controls: { display: "flex", alignItems: "center", gap: "10px", flexWrap: "wrap" },
  grid: { display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(340px, 1fr))", gap: "14px", marginTop: "16px" },
  card: { ...shorthands.padding("16px"), border: `1px solid ${tokens.colorNeutralStroke2}`, borderRadius: "12px", background: tokens.colorNeutralBackground1, display: "flex", flexDirection: "column", gap: "10px" },
  metrics: { display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "8px" },
  metric: { ...shorthands.padding("8px"), borderRadius: "8px", background: tokens.colorNeutralBackground2 },
  trend: { display: "flex", height: "46px", alignItems: "flex-end", gap: "2px", overflow: "hidden" },
});

export function Health() {
  const { t } = useTranslation();
  const styles = useStyles();
  const { isStaff } = useAuth();
  const [tab, setTab] = useState<HealthTab>("models");
  const [windowKey, setWindowKey] = useState<WindowKey>("1d");
  const [live, setLive] = useState(true);
  const [models, setModels] = useState<ModelHealth[]>([]);
  const [nodes, setNodes] = useState<NodeHealth[]>([]);
  const [state, setState] = useState<"connecting" | "connected" | "paused" | "error">("connecting");

  useEffect(() => {
    setLive(true);
  }, [tab]);

  useEffect(() => {
    if (!live) { setState("paused"); return; }
    const token = getToken();
    if (!token) return;
    const controller = new AbortController();
    let active = true;
    setState("connecting");
    void (async () => {
      try {
        const response = await fetch(`${API_BASE}/api/health/stream?tab=${tab}&window=${windowKey}`, {
          headers: { Authorization: `Bearer ${token}` }, signal: controller.signal, cache: "no-store",
        });
        if (!response.ok || !response.body) throw new Error(`HTTP ${response.status}`);
        setState("connected");
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        while (active) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
          let boundary = buffer.indexOf("\n\n");
          while (boundary >= 0) {
            const frame = buffer.slice(0, boundary); buffer = buffer.slice(boundary + 2);
            const raw = frame.split("\n").filter((line) => line.startsWith("data:")).map((line) => line.slice(5).trim()).join("\n");
            if (raw) {
              const payload = JSON.parse(raw) as { models?: ModelHealth[]; nodes?: NodeHealth[] };
              if (payload.models) setModels(payload.models);
              if (payload.nodes) setNodes(payload.nodes);
            }
            boundary = buffer.indexOf("\n\n");
          }
        }
      } catch { if (active) setState("error"); }
    })();
    return () => { active = false; controller.abort(); };
  }, [live, tab, windowKey]);

  const actions = (
    <div className={styles.controls}>
      {isStaff && <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value as HealthTab)}><Tab value="models">{t("health.modelsTab" as TK)}</Tab><Tab value="nodes">{t("health.nodesTab" as TK)}</Tab></TabList>}
      {tab === "nodes" && <Dropdown value={windowKey} selectedOptions={[windowKey]} onOptionSelect={(_, d) => setWindowKey((d.optionValue as WindowKey) ?? "1d")}>{(["30m", "1h", "3h", "12h", "1d", "3d", "7d"] as const).map((value) => <Option key={value} value={value}>{value}</Option>)}</Dropdown>}
      <Tooltip content={live ? t("logs.liveDisconnect" as TK) : t("logs.liveConnect" as TK)} relationship="label"><Button appearance={live ? "primary" : "subtle"} icon={<LiveRegular />} onClick={() => setLive((value) => !value)}>{live ? t("logs.liveOn" as TK) : t("logs.liveConnect" as TK)}</Button></Tooltip>
    </div>
  );

  return <div><PageHeader title={t("health.title" as TK)} subtitle={t("health.subtitle" as TK)} extraActions={actions} /><Text size={200}>{t(`health.stream.${state}` as TK)}</Text>{tab === "models" ? <div className={styles.grid}>{models.map((model) => <ModelCard key={model.model_id} model={model} staff={isStaff} />)}</div> : <div className={styles.grid}>{nodes.map((node) => <NodeCard key={node.id} node={node} />)}</div>}</div>;
}

function ModelCard({ model, staff }: { model: ModelHealth; staff: boolean }) {
  const { t } = useTranslation(); const styles = useStyles(); type TK = keyof Translations;
  return <div className={styles.card}><div><Text weight="semibold">{model.model_id}</Text> <Badge color={model.status === "healthy" ? "success" : model.status === "unavailable" ? "danger" : "warning"}>{t(`models.health.${model.status}` as TK)}</Badge></div><div className={styles.metrics}><Metric label={t("health.recentSuccess" as TK)} value={model.recent_success_rate == null ? "--" : `${(model.recent_success_rate * 100).toFixed(1)}%`} /><Metric label={t("health.avgTtft" as TK)} value={model.recent_avg_ttft_ms == null ? "--" : `${Math.round(model.recent_avg_ttft_ms)} ms`} /><Metric label={t("health.samples" as TK)} value={String(model.recent_request_count)} /></div>{staff && model.upstreams?.map((upstream) => <Text key={upstream.upstream_id} size={200}>{upstream.provider_name} / {upstream.upstream_model} · {upstream.samples === 0 ? "--" : `${((upstream.success_rate ?? 0) * 100).toFixed(1)}%`} · {upstream.ttft_ms == null ? "--" : `${Math.round(upstream.ttft_ms)} ms`}</Text>)}</div>;
}

function NodeCard({ node }: { node: NodeHealth }) {
  const { t } = useTranslation(); const styles = useStyles(); type TK = keyof Translations;
  const recent = useMemo(() => node.samples.slice(-48), [node.samples]); const max = Math.max(1, ...recent.map((sample) => sample.latency_ms ?? 0));
  return <div className={styles.card}><div><Text weight="semibold">{node.note || node.url || t("nodes.direct" as TK)}</Text> <Badge color={node.enabled && node.status === "active" ? "success" : "danger"}>{node.status}</Badge></div><Text size={200}>{node.groups.join(" · ")}</Text><div className={styles.metrics}><Metric label={t("health.latency" as TK)} value={node.latency_ewma == null ? "--" : `${Math.round(node.latency_ewma)} ms`} /><Metric label={t("health.score" as TK)} value={node.score.toFixed(1)} /><Metric label={t("health.failures" as TK)} value={String(node.failed_count)} /></div><div className={styles.trend}>{recent.map((sample, index) => <span key={`${sample.ts}-${index}`} title={`${sample.latency_ms ?? 0} ms`} style={{ width: 5, minHeight: 3, height: `${Math.max(6, ((sample.latency_ms ?? 0) / max) * 100)}%`, background: sample.success ? tokens.colorPaletteGreenBackground3 : tokens.colorPaletteRedBackground3, borderRadius: 2 }} />)}</div>{node.disabled_reason && <Text size={200}>{node.disabled_reason}</Text>}</div>;
}

function Metric({ label, value }: { label: string; value: string }) { const styles = useStyles(); return <div className={styles.metric}><Text size={100} block>{label}</Text><Text weight="semibold">{value}</Text></div>; }
