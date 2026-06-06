import {
  Button,
  Card,
  Field,
  Input,
  SpinButton,
  Switch,
  Text,
  tokens,
} from "@fluentui/react-components";
import { useEffect, useState } from "react";
import { api } from "../api/client";
import {
  ErrorText,
  Loading,
  PageHeader,
  useAsync,
  useNotify,
} from "../components/ui";

interface SettingsResponse {
  values: Record<string, unknown>;
}

const LABELS: Record<string, string> = {
  max_proxy_failures: "Max proxy failures before disable",
  max_key_failures: "Max key failures (soft)",
  proxy_probe_interval_seconds: "Proxy resurrector interval (s)",
  balance_probe_interval_seconds: "Balance probe interval (s)",
  balance_rescan_interval_seconds: "Balance rescan interval (s)",
  balance_scan_rate_per_second: "Manual balance rescan rate (req/s)",
  request_timeout_seconds: "Request timeout (s)",
  connect_timeout_seconds: "Connect timeout (s)",
  max_retries: "Max retries per request",
  stream_idle_timeout_seconds: "Stream idle timeout (s)",
  auto_disable_zero_balance: "Auto-disable keys with zero balance",
  balance_probe_enabled: "Balance probe enabled",
  balance_rescan_enabled: "Balance rescan enabled (re-enable recovered keys)",
  proxy_resurrector_enabled: "Proxy resurrector enabled",
  proxy_probe_url: "Proxy probe URL",
};

export function Settings() {
  const notify = useNotify();
  const loaded = useAsync<SettingsResponse>(() =>
    api.get("/api/admin/settings"),
  );
  const [values, setValues] = useState<Record<string, unknown>>({});
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (loaded.data) setValues(loaded.data.values);
  }, [loaded.data]);

  function set(key: string, value: unknown) {
    setValues((v) => ({ ...v, [key]: value }));
  }

  async function save() {
    setSaving(true);
    try {
      await api.put("/api/admin/settings", { values });
      notify("Settings saved", undefined, "success");
    } catch (e) {
      notify(
        "Save failed",
        e instanceof Error ? e.message : String(e),
        "error",
      );
    } finally {
      setSaving(false);
    }
  }

  if (loaded.loading) return <Loading />;
  if (loaded.error) return <ErrorText error={loaded.error} />;

  return (
    <div>
      <PageHeader
        title="Settings"
        subtitle="Operational thresholds and intervals — applied at runtime"
        action={
          <Button appearance="primary" disabled={saving} onClick={save}>
            Save changes
          </Button>
        }
      />
      <Card
        style={{
          padding: 20,
          maxWidth: 560,
          display: "flex",
          flexDirection: "column",
          gap: 14,
        }}
      >
        {Object.entries(values).map(([key, value]) => {
          const label = LABELS[key] ?? key;
          if (typeof value === "boolean") {
            return (
              <Switch
                key={key}
                label={label}
                checked={value}
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
                  onChange={(_, d) => set(key, d.value ?? value)}
                />
              </Field>
            );
          }
          return (
            <Field key={key} label={label}>
              <Input
                value={String(value)}
                onChange={(_, d) => set(key, d.value)}
              />
            </Field>
          );
        })}
        <Text size={200} style={{ color: tokens.colorNeutralForeground3 }}>
          Changes take effect on the next task tick / request.
        </Text>
      </Card>
    </div>
  );
}

export { Settings as SettingsPage };
