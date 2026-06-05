import {
  Badge,
  Button,
  Checkbox,
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  Tab,
  TabList,
  TableBody,
  TableCell,
  TableHeader,
  TableHeaderCell,
  TableRow,
  Text,
  Textarea,
  tokens,
} from "@fluentui/react-components";
import { EyeRegular } from "@fluentui/react-icons";
import { useEffect, useState } from "react";
import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import type { AuditLog, Page, RequestLog } from "../api/types";
import {
  DataTable,
  ErrorText,
  Loading,
  PageHeader,
  formatDate,
  useAsync,
  useConfirm,
  useNotify,
} from "../components/ui";

const PAGE = 50;

export function Logs() {
  const { isStaff } = useAuth();
  const [tab, setTab] = useState<"requests" | "audit">("requests");

  // Members never see the administrative audit trail; keep them on Requests.
  useEffect(() => {
    if (!isStaff && tab === "audit") setTab("requests");
  }, [isStaff, tab]);

  return (
    <div>
      <PageHeader
        title="Logs"
        subtitle={
          isStaff
            ? "Request traffic and administrative audit trail"
            : "Your request traffic"
        }
      />
      <TabList
        selectedValue={tab}
        onTabSelect={(_, d) => setTab(d.value as typeof tab)}
      >
        <Tab value="requests">Requests</Tab>
        {isStaff ? <Tab value="audit">Audit</Tab> : null}
      </TabList>
      <div style={{ marginTop: 16 }}>
        {tab === "requests" ? <RequestLogs /> : <AuditLogs />}
      </div>
    </div>
  );
}

function RequestLogs() {
  const [offset, setOffset] = useState(0);
  const logs = useAsync<Page<RequestLog>>(
    () => api.get("/api/admin/logs/requests", { limit: PAGE, offset }),
    [offset],
  );

  if (logs.loading) return <Loading />;
  if (logs.error) return <ErrorText error={logs.error} />;
  const data = logs.data;
  if (!data) return null;

  return (
    <>
      <DataTable ariaLabel="Requests" minWidth={1040}>
        <TableHeader>
          <TableRow>
            <TableHeaderCell>Time</TableHeaderCell>
            <TableHeaderCell>User</TableHeaderCell>
            <TableHeaderCell>Token</TableHeaderCell>
            <TableHeaderCell>Model</TableHeaderCell>
            <TableHeaderCell>Provider</TableHeaderCell>
            <TableHeaderCell>Route</TableHeaderCell>
            <TableHeaderCell>Status</TableHeaderCell>
            <TableHeaderCell>Tokens</TableHeaderCell>
            <TableHeaderCell>Tries</TableHeaderCell>
            <TableHeaderCell>Error</TableHeaderCell>
          </TableRow>
        </TableHeader>
        <TableBody>
          {data.items.map((r) => (
            <TableRow key={r.id}>
              <TableCell style={{ color: tokens.colorNeutralForeground3 }}>
                {formatDate(r.ts)}
              </TableCell>
              <TableCell>{r.user_name ?? r.user_sub ?? "—"}</TableCell>
              <TableCell style={{ color: tokens.colorNeutralForeground3 }}>
                {r.token_name ?? (r.token_id != null ? `#${r.token_id}` : "—")}
              </TableCell>
              <TableCell>{r.model ?? "—"}</TableCell>
              <TableCell>{r.provider_name ?? "—"}</TableCell>
              <TableCell style={{ color: tokens.colorNeutralForeground3 }}>
                {r.inbound_style}→{r.upstream_style} {r.stream ? "·stream" : ""}
              </TableCell>
              <TableCell>
                <Badge
                  color={r.success ? "success" : "danger"}
                  appearance="filled"
                >
                  {r.status_code ?? "ERR"}
                </Badge>
              </TableCell>
              <TableCell>{r.total_tokens}</TableCell>
              <TableCell>{r.attempts}</TableCell>
              <TableCell
                style={{
                  color: tokens.colorPaletteRedForeground1,
                  maxWidth: 240,
                }}
              >
                {r.error ?? ""}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </DataTable>
      <Pager total={data.total} offset={offset} onChange={setOffset} />
    </>
  );
}

function AuditLogs() {
  const { isOwner } = useAuth();
  const confirm = useConfirm();
  const notify = useNotify();
  const [offset, setOffset] = useState(0);
  // When checked, restrict the trail to administrative actions and hide ordinary
  // self-service ones (sign-in/out, a user's own Void-Tokens).
  const [adminOnly, setAdminOnly] = useState(false);
  const [revealed, setRevealed] = useState<{
    action: string;
    sensitive: unknown;
  } | null>(null);
  const [busy, setBusy] = useState(false);
  const logs = useAsync<Page<AuditLog>>(
    () =>
      api.get("/api/admin/logs/audit", {
        limit: PAGE,
        offset,
        ...(adminOnly ? { scope: "admin" } : {}),
      }),
    [offset, adminOnly],
  );

  async function reveal(a: AuditLog) {
    const ok = await confirm({
      title: "Reveal sensitive data",
      message:
        "This shows protected secrets (e.g. plaintext API keys). The reveal is " +
        "recorded in the audit trail. Continue?",
      confirmLabel: "Reveal",
      tone: "danger",
    });
    if (!ok) return;
    setBusy(true);
    try {
      const r = await api.post<{ action: string; sensitive: unknown }>(
        `/api/admin/logs/audit/${a.id}/reveal`,
      );
      setRevealed({ action: r.action, sensitive: r.sensitive });
    } catch (e) {
      notify(
        "Reveal failed",
        e instanceof Error ? e.message : String(e),
        "error",
      );
    } finally {
      setBusy(false);
    }
  }

  const data = logs.data;

  return (
    <>
      <div style={{ marginBottom: 12 }}>
        <Checkbox
          label="Administrative actions only"
          checked={adminOnly}
          onChange={(_, d) => {
            setOffset(0);
            setAdminOnly(Boolean(d.checked));
          }}
        />
      </div>

      {logs.loading ? (
        <Loading />
      ) : logs.error ? (
        <ErrorText error={logs.error} />
      ) : !data ? null : (
        <>
          <DataTable ariaLabel="Audit" minWidth={960}>
            <TableHeader>
              <TableRow>
                <TableHeaderCell>Time</TableHeaderCell>
                <TableHeaderCell>Actor</TableHeaderCell>
                <TableHeaderCell>Scope</TableHeaderCell>
                <TableHeaderCell>Action</TableHeaderCell>
                <TableHeaderCell>Target</TableHeaderCell>
                <TableHeaderCell>Detail</TableHeaderCell>
                <TableHeaderCell>IP</TableHeaderCell>
                {isOwner ? <TableHeaderCell>Sensitive</TableHeaderCell> : null}
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.items.map((a) => (
                <TableRow key={a.id}>
                  <TableCell style={{ color: tokens.colorNeutralForeground3 }}>
                    {formatDate(a.ts)}
                  </TableCell>
                  <TableCell>{a.actor_name ?? a.actor_sub ?? "—"}</TableCell>
                  <TableCell>
                    <Badge
                      appearance="tint"
                      color={a.scope === "admin" ? "brand" : "informative"}
                    >
                      {a.scope === "admin" ? "admin" : "self"}
                    </Badge>
                  </TableCell>
                  <TableCell>{a.action}</TableCell>
                  <TableCell>
                    {a.target_type
                      ? `${a.target_type}#${a.target_id ?? ""}`
                      : "—"}
                  </TableCell>
                  <TableCell
                    style={{
                      color: tokens.colorNeutralForeground3,
                      maxWidth: 280,
                    }}
                  >
                    {JSON.stringify(a.detail)}
                  </TableCell>
                  <TableCell>{a.ip ?? "—"}</TableCell>
                  {isOwner ? (
                    <TableCell>
                      {a.has_sensitive ? (
                        <Button
                          size="small"
                          appearance="subtle"
                          icon={<EyeRegular />}
                          disabled={busy}
                          onClick={() => reveal(a)}
                        >
                          Reveal
                        </Button>
                      ) : (
                        "—"
                      )}
                    </TableCell>
                  ) : null}
                </TableRow>
              ))}
            </TableBody>
          </DataTable>
          <Pager total={data.total} offset={offset} onChange={setOffset} />
        </>
      )}

      <Dialog
        open={revealed !== null}
        onOpenChange={(_, d) => !d.open && setRevealed(null)}
      >
        <DialogSurface>
          <DialogBody>
            <DialogTitle>Sensitive data · {revealed?.action}</DialogTitle>
            <DialogContent>
              <Text
                size={200}
                block
                style={{ color: tokens.colorNeutralForeground3, marginBottom: 8 }}
              >
                Handle with care — these are plaintext secrets.
              </Text>
              <Textarea
                readOnly
                value={
                  revealed ? JSON.stringify(revealed.sensitive, null, 2) : ""
                }
                rows={12}
                style={{ width: "100%", fontFamily: "monospace" }}
              />
            </DialogContent>
            <DialogActions>
              <Button appearance="primary" onClick={() => setRevealed(null)}>
                Close
              </Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </>
  );
}

function Pager({
  total,
  offset,
  onChange,
}: {
  total: number;
  offset: number;
  onChange: (n: number) => void;
}) {
  return (
    <div
      style={{ display: "flex", gap: 12, alignItems: "center", marginTop: 12 }}
    >
      <Button
        size="small"
        disabled={offset === 0}
        onClick={() => onChange(Math.max(0, offset - PAGE))}
      >
        Previous
      </Button>
      <Text size={200} style={{ color: tokens.colorNeutralForeground3 }}>
        {offset + 1}–{Math.min(offset + PAGE, total)} of {total}
      </Text>
      <Button
        size="small"
        disabled={offset + PAGE >= total}
        onClick={() => onChange(offset + PAGE)}
      >
        Next
      </Button>
    </div>
  );
}
