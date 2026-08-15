import {
  Button,
  Dropdown,
  Field,
  Input,
  Option,
  SpinButton,
  Spinner,
  Switch,
  Text,
  tokens,
} from "@fluentui/react-components";
import { BroomRegular } from "@fluentui/react-icons";
import { useEffect, useMemo, useState, type ReactElement } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import type { LoginTokenStatus, LoginTokenWithSecret } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import type { Translations } from "../i18n/locales/en";
import {
  ErrorText,
  Loading,
  PageHeader,
  useAsync,
  useConfirm,
  useNotify,
} from "../components/ui";
import { useOverTimeMode, type OverTimeMode } from "../lib/prefs";

type TK = keyof Translations;

interface SettingsResponse {
  values: Record<string, unknown>;
}

// Ordered, grouped layout of the operational settings. Keys absent from every
// section fall into a trailing "Other" card so nothing is ever hidden by accident.
const SECTIONS: { titleKey: string; keys: string[] }[] = [
  {
    titleKey: "settings.sectionProxy",
    keys: [
      "proxy_switching_enabled",
      "static_proxy_url",
      "max_proxy_failures",
      "proxy_probe_interval_seconds",
      "proxy_health_check_enabled",
      "proxy_probe_url",
    ],
  },
  {
    titleKey: "settings.sectionKeys",
    keys: [
      "max_key_failures",
      "auto_disable_zero_balance",
      "balance_probe_enabled",
      "balance_probe_interval_seconds",
      "balance_rescan_enabled",
      "balance_rescan_interval_seconds",
      "balance_scan_rate_per_second",
    ],
  },
  {
    titleKey: "settings.sectionRateLimit",
    keys: ["rate_limit_recovery_seconds", "rate_limit_max_cooldown_seconds"],
  },
  {
    titleKey: "settings.sectionTimeouts",
    keys: [
      "connect_timeout_seconds",
      "request_timeout_seconds",
      "response_timeout_seconds",
      "stream_idle_timeout_seconds",
      "max_retries",
      "max_connections",
      "max_keepalive_connections",
    ],
  },
  {
    titleKey: "settings.sectionSession",
    keys: ["session_ttl_minutes"],
  },
  {
    titleKey: "settings.sectionLogs",
    keys: [
      "logs_page_size",
      "log_stream_max_connections",
      "log_cleanup_enabled",
      "log_cleanup_interval_seconds",
      "audit_log_retention_days",
      "request_log_retention_days",
      "debug_log_retention_days",
      "heatmap_retention_days",
    ],
  },
  {
    titleKey: "settings.sectionOpencode",
    keys: ["opencode_default_model", "opencode_small_model"],
  },
  {
    titleKey: "settings.sectionAnnouncements",
    keys: ["announcements_home_count"],
  },
];

// Abuse rate-limit keys get a bespoke two-inputs-per-line layout (window + max),
// so they're excluded from the generic sections (and the "Other" fallback).
const RATE_LIMIT_KEYS = [
  "operation_rate_limit_window_seconds",
  "operation_rate_limit_max_requests",
  "call_rate_limit_window_seconds",
  "call_rate_limit_max_requests",
];

// Proxy-pool settings that are meaningless when proxy switching is off (an
// external proxy handles egress, so there is no pool to tune, probe, or
// resurrect). Their background tasks are also short-circuited on the backend.
const PROXY_SWITCHING_ONLY = new Set([
  "max_proxy_failures",
  "proxy_probe_interval_seconds",
  "proxy_health_check_enabled",
  "proxy_probe_url",
]);

// The single static upstream proxy URL only applies when switching is OFF; with
// switching on the pool is used instead, so hide it.
const PROXY_SWITCHING_OFF_ONLY = new Set(["static_proxy_url"]);

// Fields that only make sense while their controlling toggle is on. When the
// toggle is explicitly disabled the dependent input is hidden (it would have no
// effect anyway). Keyed by the dependent field → the boolean key that gates it.
const DEPENDENT_ON: Record<string, string> = {
  balance_probe_interval_seconds: "balance_probe_enabled",
  balance_rescan_interval_seconds: "balance_rescan_enabled",
  log_cleanup_interval_seconds: "log_cleanup_enabled",
};

// Keys that were renamed / removed and should never appear in the UI.
const HIDDEN_KEYS = new Set(["proxy_resurrector_enabled"]);

export function Settings() {
  const { t } = useTranslation();
  const notify = useNotify();
  const confirm = useConfirm();
  const { isOwner } = useAuth();
  const [overTimeMode, setOverTimeMode] = useOverTimeMode();
  const loaded = useAsync<SettingsResponse>(() =>
    api.get("/api/admin/settings"),
  );
  const loginToken = useAsync<LoginTokenStatus>(() =>
    api.get("/api/me/login-token"),
  );
  const [values, setValues] = useState<Record<string, unknown>>({});
  const [saving, setSaving] = useState(false);
  const [cleaning, setCleaning] = useState(false);
  const [rotatingLoginToken, setRotatingLoginToken] = useState(false);
  const [newLoginToken, setNewLoginToken] = useState<string | null>(null);
  const [testingProxy, setTestingProxy] = useState(false);
  const [proxyTestResult, setProxyTestResult] = useState<string | null>(null);

  useEffect(() => {
    if (loaded.data) setValues(loaded.data.values);
  }, [loaded.data]);

  function set(key: string, value: unknown) {
    setValues((v) => ({ ...v, [key]: value }));
  }

  // Default-on: treat an unset value (undefined, before settings load) as
  // enabled, matching the backend default. Only an explicit `false` turns it off.
  const proxySwitching = values.proxy_switching_enabled !== false;

  async function save() {
    setSaving(true);
    try {
      await api.put("/api/admin/settings", { values });
      notify(t("common.settingsSaved" as TK), undefined, "success");
    } catch (e) {
      notify(
        t("common.saveFailed" as TK),
        e instanceof Error ? e.message : String(e),
        "error",
      );
    } finally {
      setSaving(false);
    }
  }

  async function cleanLogsNow() {
    const ok = await confirm({
      title: t("settings.cleanNowTitle" as TK),
      message: t("settings.cleanNowMsg" as TK),
      confirmLabel: t("settings.cleanNow" as TK),
      tone: "danger",
    });
    if (!ok) return;
    setCleaning(true);
    try {
      const r = await api.post<{
        deleted_request_logs: number;
        deleted_audit_logs: number;
        stripped_debug_logs: number;
      }>("/api/admin/settings/clean-logs");
      notify(
        t("settings.cleanedTitle" as TK),
        t("settings.cleanedDetail" as TK)
          .replace("{requests}", String(r.deleted_request_logs))
          .replace("{audits}", String(r.deleted_audit_logs))
          .replace("{debug}", String(r.stripped_debug_logs)),
        "success",
      );
    } catch (e) {
      notify(
        t("common.updateFailed" as TK),
        e instanceof Error ? e.message : String(e),
        "error",
      );
    } finally {
      setCleaning(false);
    }
  }

  async function rotateLoginToken() {
    const ok = await confirm({
      title: t("settings.loginTokenRotateTitle" as TK),
      message: t("settings.loginTokenRotateMsg" as TK),
      confirmLabel: t("settings.loginTokenRotate" as TK),
    });
    if (!ok) return;
    setRotatingLoginToken(true);
    try {
      const r = await api.post<LoginTokenWithSecret>(
        "/api/me/login-token/rotate",
      );
      setNewLoginToken(r.token);
      loginToken.reload();
      notify(t("settings.loginTokenRotated" as TK), undefined, "success");
    } catch (e) {
      notify(
        t("common.updateFailed" as TK),
        e instanceof Error ? e.message : String(e),
        "error",
      );
    } finally {
      setRotatingLoginToken(false);
    }
  }

  async function testStaticProxy() {
    const url = String(values.static_proxy_url ?? "").trim();
    if (!url) {
      notify(t("settings.testStaticProxyFail" as TK), "No URL provided", "error");
      return;
    }
    setTestingProxy(true);
    setProxyTestResult(null);
    try {
      const r = await api.post<{ ok: boolean; status_code: number | null; latency_ms: number | null; error: string | null }>(
        "/api/admin/settings/test-static-proxy",
        { url },
      );
      if (r.ok) {
        setProxyTestResult(t("settings.testStaticProxyOk" as TK) + ` (${r.status_code}, ${r.latency_ms}ms)`);
        notify(t("settings.testStaticProxyOk" as TK), `${r.status_code}, ${r.latency_ms}ms`, "success");
      } else {
        setProxyTestResult(`${t("settings.testStaticProxyFail" as TK)}: ${r.error}`);
        notify(t("settings.testStaticProxyFail" as TK), r.error ?? "", "error");
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setProxyTestResult(`${t("settings.testStaticProxyFail" as TK)}: ${msg}`);
      notify(t("settings.testStaticProxyFail" as TK), msg, "error");
    } finally {
      setTestingProxy(false);
    }
  }

  const labels = useMemo<Record<string, string>>(
    () => ({
      max_proxy_failures: t("settings.maxProxyFailures" as TK),
      max_key_failures: t("settings.maxKeyFailures" as TK),
      proxy_probe_interval_seconds: t("settings.proxyProbeInterval" as TK),
      balance_probe_interval_seconds: t("settings.balanceProbeInterval" as TK),
      balance_rescan_interval_seconds: t(
        "settings.balanceRescanInterval" as TK,
      ),
      balance_scan_rate_per_second: t("settings.balanceScanRate" as TK),
      request_timeout_seconds: t("settings.requestTimeout" as TK),
      connect_timeout_seconds: t("settings.connectTimeout" as TK),
      response_timeout_seconds: t("settings.responseTimeout" as TK),
      session_ttl_minutes: t("settings.sessionTtlMinutes" as TK),
      max_retries: t("settings.maxRetries" as TK),
      stream_idle_timeout_seconds: t("settings.streamIdleTimeout" as TK),
      rate_limit_recovery_seconds: t("settings.rateLimitRecovery" as TK),
      rate_limit_max_cooldown_seconds: t("settings.rateLimitMaxCooldown" as TK),
      auto_disable_zero_balance: t("settings.autoDisableZeroBalance" as TK),
      balance_probe_enabled: t("settings.balanceProbeEnabled" as TK),
      balance_rescan_enabled: t("settings.balanceRescanEnabled" as TK),
      proxy_health_check_enabled: t("settings.proxyHealthCheckEnabled" as TK),
      proxy_probe_url: t("settings.proxyProbeUrl" as TK),
      opencode_default_model: t("settings.opencodeDefaultModel" as TK),
      opencode_small_model: t("settings.opencodeSmallModel" as TK),
      audit_log_retention_days: t("settings.auditLogRetentionDays" as TK),
      request_log_retention_days: t("settings.requestLogRetentionDays" as TK),
      debug_log_retention_days: t("settings.debugLogRetentionDays" as TK),
      heatmap_retention_days: t("settings.heatmapRetentionDays" as TK),
      log_cleanup_enabled: t("settings.logCleanupEnabled" as TK),
      log_cleanup_interval_seconds: t("settings.logCleanupInterval" as TK),
      logs_page_size: t("settings.logsPageSize" as TK),
      log_stream_max_connections: t("settings.logStreamMaxConnections" as TK),
      proxy_switching_enabled: t("settings.proxySwitchingEnabled" as TK),
      static_proxy_url: t("settings.staticProxyUrl" as TK),
      max_connections: t("settings.maxConnections" as TK),
      max_keepalive_connections: t("settings.maxKeepaliveConnections" as TK),
      announcements_home_count: t("settings.announcementsHomeCount" as TK),
    }),
    [t],
  );

  function renderField(key: string) {
    if (!(key in values)) return null;
    // Hide proxy-pool settings that don't apply when switching is off,
    // and the static-proxy URL that only applies when switching is off.
    if (!proxySwitching && PROXY_SWITCHING_ONLY.has(key)) return null;
    if (proxySwitching && PROXY_SWITCHING_OFF_ONLY.has(key)) return null;
    // Hide inputs whose controlling toggle is switched off.
    const gate = DEPENDENT_ON[key];
    if (gate && values[gate] === false) return null;
    const value = values[key];
    const label = labels[key] ?? key;

    if (typeof value === "boolean") {
      // The auto-cleanup toggle gets an inline "clean now" action (owner-only).
      if (key === "log_cleanup_enabled") {
        return (
          <div
            key={key}
            style={{ display: "flex", alignItems: "center", gap: 12 }}
          >
            <Switch
              label={label}
              checked={value}
              disabled={!isOwner}
              onChange={(_, d) => set(key, d.checked)}
            />
            {isOwner ? (
              <Button
                size="small"
                icon={<BroomRegular />}
                disabled={cleaning}
                onClick={cleanLogsNow}
              >
                {cleaning ? t("settings.cleaning" as TK) : t("settings.cleanNow" as TK)}
              </Button>
            ) : null}
          </div>
        );
      }
      return (
        <Switch
          key={key}
          label={label}
          checked={value}
          disabled={!isOwner}
          onChange={(_, d) => set(key, d.checked)}
        />
      );
    }
    if (typeof value === "number") {
      return (
        <Field key={key} label={label}>
          <SpinButton
            value={value}
            min={0}
            disabled={!isOwner}
            onChange={(_, d) => {
              const next =
                d.value ?? (d.displayValue ? Number(d.displayValue) : value);
              if (!Number.isNaN(next)) set(key, next);
            }}
          />
        </Field>
      );
    }
    if (typeof value === "string") {
      if (key === "static_proxy_url") {
        return (
          <Field key={key} label={label}>
            <div style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
              <Input
                value={value}
                disabled={!isOwner}
                style={{ flex: 1 }}
                onChange={(_, d) => set(key, d.value)}
              />
              <Button
                size="small"
                disabled={!isOwner || testingProxy || !value}
                icon={testingProxy ? <Spinner size="extra-tiny" /> : undefined}
                onClick={testStaticProxy}
              >
                {testingProxy ? t("settings.testingStaticProxy" as TK) : t("settings.testStaticProxy" as TK)}
              </Button>
            </div>
            {proxyTestResult ? (
              <Text size={200} style={{ color: tokens.colorNeutralForeground3, marginTop: 4, display: "block" }}>
                {proxyTestResult}
              </Text>
            ) : null}
          </Field>
        );
      }
      return (
        <Field key={key} label={label}>
          <Input
            value={value}
            disabled={!isOwner}
            onChange={(_, d) => set(key, d.value)}
          />
        </Field>
      );
    }
    return null;
  }

  function renderRateLimitRow(labelKey: TK, windowKey: string, maxKey: string) {
    const windowVal = Number(values[windowKey] ?? 0);
    const maxVal = Number(values[maxKey] ?? 0);
    return (
      <div
        style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}
      >
        <Text style={{ minWidth: 150 }}>{t(labelKey)}</Text>
        <SpinButton
          value={windowVal}
          min={0}
          disabled={!isOwner}
          style={{ width: 96 }}
          onChange={(_, d) => {
            const next = d.value ?? (d.displayValue ? Number(d.displayValue) : windowVal);
            if (!Number.isNaN(next)) set(windowKey, next);
          }}
        />
        <Text size={200} style={{ color: tokens.colorNeutralForeground3 }}>
          {t("settings.rateLimitWithin" as TK)}
        </Text>
        <SpinButton
          value={maxVal}
          min={0}
          disabled={!isOwner}
          style={{ width: 96 }}
          onChange={(_, d) => {
            const next = d.value ?? (d.displayValue ? Number(d.displayValue) : maxVal);
            if (!Number.isNaN(next)) set(maxKey, next);
          }}
        />
        <Text size={200} style={{ color: tokens.colorNeutralForeground3 }}>
          {t("settings.rateLimitRequests" as TK)}
        </Text>
      </div>
    );
  }

  const hasRateLimitKeys = RATE_LIMIT_KEYS.some((k) => k in values);

  if (loaded.loading) return <Loading />;
  if (loaded.error) return <ErrorText error={loaded.error} />;

  const known = new Set([...SECTIONS.flatMap((s) => s.keys), ...RATE_LIMIT_KEYS, ...HIDDEN_KEYS]);
  const otherKeys = Object.keys(values).filter((k) => !known.has(k));
  const sections = [
    ...SECTIONS,
    ...(otherKeys.length
      ? [{ titleKey: "settings.sectionOther", keys: otherKeys }]
      : []),
  ];

  return (
    <div>
      <PageHeader
        title={t("settings.title" as TK)}
        subtitle={t("settings.subtitle" as TK)}
        onRefresh={loaded.reload}
        action={
          isOwner ? (
            <Button appearance="primary" disabled={saving} onClick={save}>
              {t("common.saveChanges" as TK)}
            </Button>
          ) : undefined
        }
      />
      {!isOwner ? (
        <Text
          size={200}
          block
          style={{ color: tokens.colorNeutralForeground3, marginBottom: 12 }}
        >
          {t("settings.readOnlyNote" as TK)}
        </Text>
      ) : null}

      <div
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 16,
        }}
      >
        <div
          style={{ padding: 16, display: "flex", flexDirection: "column", gap: 14, border: "1px solid var(--colorNeutralStroke1)", borderRadius: "10px" }}
        >
          <Text weight="semibold" size={400}>
            {t("settings.sectionPersonal" as TK)}
          </Text>
          {loginToken.loading ? (
            <Loading />
          ) : loginToken.error ? (
            <ErrorText error={loginToken.error} />
          ) : (
            <>
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  gap: 12,
                  alignItems: "center",
                  flexWrap: "wrap",
                }}
              >
                <div>
                  <Text block>{t("settings.loginToken" as TK)}</Text>
                  <Text size={200} style={{ color: tokens.colorNeutralForeground3 }}>
                    {loginToken.data?.enabled
                      ? t("settings.loginTokenEnabled" as TK).replace(
                          "{prefix}",
                          loginToken.data.prefix ?? "",
                        )
                      : t("settings.loginTokenDisabled" as TK)}
                  </Text>
                </div>
                <Button disabled={rotatingLoginToken} onClick={rotateLoginToken}>
                  {t("settings.loginTokenRotate" as TK)}
                </Button>
              </div>
              {newLoginToken ? (
                <Field label={t("settings.loginTokenNew" as TK)}>
                  <Input readOnly value={newLoginToken} />
                </Field>
              ) : null}
              <Text size={200} style={{ color: tokens.colorNeutralForeground3 }}>
                {t("settings.loginTokenHint" as TK)}
              </Text>
            </>
          )}
          <Field
            label={t("settings.statsOverTimeMode" as TK)}
            hint={t("settings.statsOverTimeModeHint" as TK)}
          >
            <Dropdown
              selectedOptions={[overTimeMode]}
              value={
                overTimeMode === "B"
                  ? t("settings.statsModeB" as TK)
                  : overTimeMode === "C"
                    ? t("settings.statsModeC" as TK)
                    : t("settings.statsModeA" as TK)
              }
              onOptionSelect={(_, d) =>
                setOverTimeMode((d.optionValue as OverTimeMode) ?? "A")
              }
            >
              <Option value="A" text={t("settings.statsModeA" as TK)}>
                {t("settings.statsModeA" as TK)}
              </Option>
              <Option value="B" text={t("settings.statsModeB" as TK)}>
                {t("settings.statsModeB" as TK)}
              </Option>
              <Option value="C" text={t("settings.statsModeC" as TK)}>
                {t("settings.statsModeC" as TK)}
              </Option>
            </Dropdown>
          </Field>
        </div>
        {sections.map((section) => {
          const fields = section.keys
            .map((k) => renderField(k))
            .filter((node): node is ReactElement => node !== null);
          if (fields.length === 0) return null;
          return (
            <div
              key={section.titleKey}
              style={{
                padding: 16,
                display: "flex",
                flexDirection: "column",
                gap: 14,
                border: "1px solid var(--colorNeutralStroke1)",
                borderRadius: "10px",
              }}
            >
              <Text weight="semibold" size={400}>
                {t(section.titleKey as TK)}
              </Text>
              {fields}
            </div>
          );
        })}
        {hasRateLimitKeys ? (
          <div
            style={{ padding: 16, display: "flex", flexDirection: "column", gap: 14, border: "1px solid var(--colorNeutralStroke1)", borderRadius: "10px" }}
          >
            <Text weight="semibold" size={400}>
              {t("settings.sectionAbuseLimits" as TK)}
            </Text>
            {renderRateLimitRow(
              "settings.rateLimitOperation" as TK,
              "operation_rate_limit_window_seconds",
              "operation_rate_limit_max_requests",
            )}
            {renderRateLimitRow(
              "settings.rateLimitCall" as TK,
              "call_rate_limit_window_seconds",
              "call_rate_limit_max_requests",
            )}
            <Text size={200} style={{ color: tokens.colorNeutralForeground3 }}>
              {t("settings.abuseLimitsHint" as TK)}
            </Text>
          </div>
        ) : null}
        <Text size={200} style={{ color: tokens.colorNeutralForeground3 }}>
          {t("common.settingsAppliedNote" as TK)}
        </Text>
      </div>
    </div>
  );
}

export { Settings as SettingsPage };
