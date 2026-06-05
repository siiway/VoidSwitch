import {
  Badge,
  Button,
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
      <DataTable ariaLabel="Requests" minWidth={900}>
        <TableHeader>
          <TableRow>
            <TableHeaderCell>Time</TableHeaderCell>
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
  const [offset, setOffset] = useState(0);
  const logs = useAsync<Page<AuditLog>>(
    () => api.get("/api/admin/logs/audit", { limit: PAGE, offset }),
    [offset],
  );

  if (logs.loading) return <Loading />;
  if (logs.error) return <ErrorText error={logs.error} />;
  const data = logs.data;
  if (!data) return null;

  return (
    <>
      <DataTable ariaLabel="Audit" minWidth={900}>
        <TableHeader>
          <TableRow>
            <TableHeaderCell>Time</TableHeaderCell>
            <TableHeaderCell>Actor</TableHeaderCell>
            <TableHeaderCell>Action</TableHeaderCell>
            <TableHeaderCell>Target</TableHeaderCell>
            <TableHeaderCell>Detail</TableHeaderCell>
            <TableHeaderCell>IP</TableHeaderCell>
          </TableRow>
        </TableHeader>
        <TableBody>
          {data.items.map((a) => (
            <TableRow key={a.id}>
              <TableCell style={{ color: tokens.colorNeutralForeground3 }}>
                {formatDate(a.ts)}
              </TableCell>
              <TableCell>{a.actor_name ?? a.actor_sub ?? "—"}</TableCell>
              <TableCell>{a.action}</TableCell>
              <TableCell>
                {a.target_type ? `${a.target_type}#${a.target_id ?? ""}` : "—"}
              </TableCell>
              <TableCell
                style={{ color: tokens.colorNeutralForeground3, maxWidth: 280 }}
              >
                {JSON.stringify(a.detail)}
              </TableCell>
              <TableCell>{a.ip ?? "—"}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </DataTable>
      <Pager total={data.total} offset={offset} onChange={setOffset} />
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
