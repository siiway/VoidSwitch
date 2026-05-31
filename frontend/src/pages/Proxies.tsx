import {
  Button,
  Field,
  Input,
  TableBody,
  TableCell,
  TableHeader,
  TableHeaderCell,
  TableRow,
  Textarea,
  tokens,
} from "@fluentui/react-components";
import { DeleteRegular, PulseRegular } from "@fluentui/react-icons";
import { useState } from "react";
import { api } from "../api/client";
import type { Proxy } from "../api/types";
import {
  DataTable,
  ErrorText,
  Loading,
  PageHeader,
  StatusBadge,
  formatDate,
  useAsync,
  useConfirm,
  useNotify,
} from "../components/ui";

export function Proxies() {
  const notify = useNotify();
  const confirm = useConfirm();
  const proxies = useAsync<Proxy[]>(() => api.get("/api/admin/proxies"));
  const [bulk, setBulk] = useState("");
  const [localAddr, setLocalAddr] = useState("");
  const [adding, setAdding] = useState(false);

  async function add() {
    const urls = bulk
      .split("\n")
      .map((s) => s.trim())
      .filter(Boolean);
    if (!urls.length) return;
    setAdding(true);
    try {
      const created = await api.post<Proxy[]>("/api/admin/proxies", {
        urls,
        local_address: localAddr.trim() || null,
      });
      notify("Proxies added", `${created.length} new`, "success");
      setBulk("");
      setLocalAddr("");
      proxies.reload();
    } catch (e) {
      notify("Add failed", e instanceof Error ? e.message : String(e), "error");
    } finally {
      setAdding(false);
    }
  }

  async function toggle(p: Proxy) {
    await api.patch(`/api/admin/proxies/${p.id}`, { enabled: !p.enabled });
    proxies.reload();
  }

  async function probe(p: Proxy) {
    try {
      await api.post(`/api/admin/proxies/${p.id}/probe`);
      notify("Probe complete", p.url, "success");
      proxies.reload();
    } catch (e) {
      notify(
        "Probe failed",
        e instanceof Error ? e.message : String(e),
        "error",
      );
    }
  }

  async function remove(p: Proxy) {
    const ok = await confirm({
      title: "Delete proxy",
      message: `Delete proxy ${p.url}?`,
      confirmLabel: "Delete",
      tone: "danger",
    });
    if (!ok) return;
    await api.del(`/api/admin/proxies/${p.id}`);
    proxies.reload();
  }

  return (
    <div>
      <PageHeader
        title="Proxies"
        subtitle="Outbound HTTP/SOCKS proxies (http://, socks5://). Optional source-IP binding."
      />

      <Field label="Proxy URLs (one per line)" style={{ marginBottom: 8 }}>
        <Textarea
          value={bulk}
          rows={3}
          placeholder={"http://user:pass@host:port\nsocks5://host:1080"}
          onChange={(_, d) => setBulk(d.value)}
        />
      </Field>
      <Field
        label="Local source IP (optional, applies to this batch)"
        style={{ marginBottom: 8 }}
      >
        <Input
          value={localAddr}
          placeholder="e.g. 10.0.0.5"
          onChange={(_, d) => setLocalAddr(d.value)}
        />
      </Field>
      <Button
        appearance="primary"
        disabled={adding || !bulk.trim()}
        onClick={add}
        style={{ marginBottom: 24 }}
      >
        Add proxies
      </Button>

      {proxies.loading ? (
        <Loading />
      ) : proxies.error ? (
        <ErrorText error={proxies.error} />
      ) : (
        <DataTable ariaLabel="Proxies">
          <TableHeader>
            <TableRow>
              <TableHeaderCell>URL</TableHeaderCell>
              <TableHeaderCell>Source IP</TableHeaderCell>
              <TableHeaderCell>Status</TableHeaderCell>
              <TableHeaderCell>Fails</TableHeaderCell>
              <TableHeaderCell>Latency</TableHeaderCell>
              <TableHeaderCell>Checked</TableHeaderCell>
              <TableHeaderCell>Actions</TableHeaderCell>
            </TableRow>
          </TableHeader>
          <TableBody>
            {(proxies.data ?? []).map((p) => (
              <TableRow key={p.id}>
                <TableCell style={{ fontFamily: "monospace" }}>
                  {p.url || "(direct)"}
                </TableCell>
                <TableCell>{p.local_address ?? "—"}</TableCell>
                <TableCell>
                  <StatusBadge status={p.enabled ? p.status : "disabled"} />
                </TableCell>
                <TableCell>{p.failed_count}</TableCell>
                <TableCell style={{ color: tokens.colorNeutralForeground3 }}>
                  {p.latency_ms != null
                    ? `${Math.round(p.latency_ms)} ms`
                    : "—"}
                </TableCell>
                <TableCell style={{ color: tokens.colorNeutralForeground3 }}>
                  {formatDate(p.last_checked_at)}
                </TableCell>
                <TableCell>
                  <Button
                    size="small"
                    appearance="subtle"
                    icon={<PulseRegular />}
                    onClick={() => probe(p)}
                  >
                    Probe
                  </Button>
                  <Button
                    size="small"
                    appearance="subtle"
                    onClick={() => toggle(p)}
                  >
                    {p.enabled ? "Disable" : "Enable"}
                  </Button>
                  <Button
                    size="small"
                    appearance="subtle"
                    icon={<DeleteRegular />}
                    onClick={() => remove(p)}
                  />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </DataTable>
      )}
    </div>
  );
}
