import {
  Badge,
  Button,
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  Dropdown,
  Input,
  Option,
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
import { DismissRegular, EyeRegular } from "@fluentui/react-icons";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import type {
  AuditFilterOptions,
  AuditLog,
  Page,
  RequestLog,
} from "../api/types";
import type { Translations } from "../i18n/locales/en";
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
  const { t } = useTranslation();
  type TK = keyof Translations;
  const { isStaff } = useAuth();
  const [tab, setTab] = useState<"requests" | "audit">("requests");

  useEffect(() => {
    if (!isStaff && tab === "audit") setTab("requests");
  }, [isStaff, tab]);

  return (
    <div>
      <PageHeader
        title={t("logs.title" as TK)}
        subtitle={
          isStaff
            ? t("logs.subtitleStaff" as TK)
            : t("logs.subtitleMember" as TK)
        }
      />
      <TabList
        selectedValue={tab}
        onTabSelect={(_, d) => setTab(d.value as typeof tab)}
      >
        <Tab value="requests">{t("logs.requests" as TK)}</Tab>
        {isStaff ? <Tab value="audit">{t("logs.audit" as TK)}</Tab> : null}
      </TabList>
      <div style={{ marginTop: 16 }}>
        {tab === "requests" ? <RequestLogs /> : <AuditLogs />}
      </div>
    </div>
  );
}

function RequestLogs() {
  const { t: tr } = useTranslation();
  type TK = keyof Translations;
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
      <DataTable ariaLabel={tr("logs.requests" as TK)} minWidth={1040}>
        <TableHeader>
          <TableRow>
            <TableHeaderCell>{tr("logs.time" as TK)}</TableHeaderCell>
            <TableHeaderCell>{tr("logs.user" as TK)}</TableHeaderCell>
            <TableHeaderCell>{tr("logs.token" as TK)}</TableHeaderCell>
            <TableHeaderCell>{tr("logs.model" as TK)}</TableHeaderCell>
            <TableHeaderCell>{tr("logs.provider" as TK)}</TableHeaderCell>
            <TableHeaderCell>{tr("logs.route" as TK)}</TableHeaderCell>
            <TableHeaderCell>{tr("logs.status" as TK)}</TableHeaderCell>
            <TableHeaderCell>{tr("logs.tokens" as TK)}</TableHeaderCell>
            <TableHeaderCell>{tr("logs.tries" as TK)}</TableHeaderCell>
            <TableHeaderCell>{tr("logs.error" as TK)}</TableHeaderCell>
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

interface AuditFilters {
  scope: string;
  action: string;
  target_type: string;
  actor_sub: string;
  q: string;
}

const EMPTY_FILTERS: AuditFilters = {
  scope: "",
  action: "",
  target_type: "",
  actor_sub: "",
  q: "",
};

function AuditLogs() {
  const { t: ta } = useTranslation();
  type TK = keyof Translations;
  const { isOwner } = useAuth();
  const confirm = useConfirm();
  const notify = useNotify();
  const [offset, setOffset] = useState(0);
  const [filters, setFilters] = useState<AuditFilters>(EMPTY_FILTERS);
  const [revealed, setRevealed] = useState<{
    action: string;
    sensitive: unknown;
  } | null>(null);
  const [busy, setBusy] = useState(false);

  const options = useAsync<AuditFilterOptions>(
    () => api.get("/api/admin/logs/audit/filters"),
    [],
  );

  const logs = useAsync<Page<AuditLog>>(
    () =>
      api.get("/api/admin/logs/audit", {
        limit: PAGE,
        offset,
        scope: filters.scope || undefined,
        action: filters.action || undefined,
        target_type: filters.target_type || undefined,
        actor_sub: filters.actor_sub || undefined,
        q: filters.q || undefined,
      }),
    [
      offset,
      filters.scope,
      filters.action,
      filters.target_type,
      filters.actor_sub,
      filters.q,
    ],
  );

  function setFilter<K extends keyof AuditFilters>(
    key: K,
    value: AuditFilters[K],
  ) {
    setOffset(0);
    setFilters((f) => ({ ...f, [key]: value }));
  }

  const hasFilters = Object.values(filters).some((v) => v !== "");
  const opts = options.data;
  const actorLabel = (sub: string) =>
    opts?.actors.find((a) => a.sub === sub)?.name ?? sub;
  const scopeLabel = (s: string) =>
    s === "admin"
      ? ta("common.admin" as TK)
      : s === "self"
        ? ta("common.self" as TK)
        : s === "system"
          ? ta("common.system" as TK)
          : s;

  async function reveal(a: AuditLog) {
    const ok = await confirm({
      title: ta("logs.revealTitle" as TK),
      message: ta("logs.revealMsg" as TK),
      confirmLabel: ta("logs.revealLabel" as TK),
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
        ta("logs.revealFailed" as TK),
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
      <div
        style={{
          marginBottom: 12,
          display: "flex",
          flexWrap: "wrap",
          gap: 8,
          alignItems: "flex-end",
        }}
      >
        <Dropdown
          aria-label={ta("logs.scope" as TK)}
          placeholder={ta("logs.filterScope" as TK)}
          style={{ minWidth: 120 }}
          selectedOptions={filters.scope ? [filters.scope] : []}
          value={filters.scope ? scopeLabel(filters.scope) : ""}
          onOptionSelect={(_, d) => setFilter("scope", d.optionValue ?? "")}
        >
          {(opts?.scopes ?? []).map((s) => (
            <Option key={s} value={s} text={scopeLabel(s)}>
              {scopeLabel(s)}
            </Option>
          ))}
        </Dropdown>
        <Dropdown
          aria-label={ta("logs.action" as TK)}
          placeholder={ta("logs.filterAction" as TK)}
          style={{ minWidth: 170 }}
          selectedOptions={filters.action ? [filters.action] : []}
          value={filters.action}
          onOptionSelect={(_, d) => setFilter("action", d.optionValue ?? "")}
        >
          {(opts?.actions ?? []).map((a) => (
            <Option key={a} value={a} text={a}>
              {a}
            </Option>
          ))}
        </Dropdown>
        <Dropdown
          aria-label={ta("logs.target" as TK)}
          placeholder={ta("logs.filterTarget" as TK)}
          style={{ minWidth: 130 }}
          selectedOptions={filters.target_type ? [filters.target_type] : []}
          value={filters.target_type}
          onOptionSelect={(_, d) =>
            setFilter("target_type", d.optionValue ?? "")
          }
        >
          {(opts?.target_types ?? []).map((tt) => (
            <Option key={tt} value={tt} text={tt}>
              {tt}
            </Option>
          ))}
        </Dropdown>
        <Dropdown
          aria-label={ta("logs.user" as TK)}
          placeholder={ta("logs.filterUser" as TK)}
          style={{ minWidth: 170 }}
          selectedOptions={filters.actor_sub ? [filters.actor_sub] : []}
          value={filters.actor_sub ? actorLabel(filters.actor_sub) : ""}
          onOptionSelect={(_, d) => setFilter("actor_sub", d.optionValue ?? "")}
        >
          {(opts?.actors ?? []).map((a) => (
            <Option key={a.sub} value={a.sub} text={a.name}>
              {a.name}
            </Option>
          ))}
        </Dropdown>
        <Input
          aria-label={ta("logs.filterSearch" as TK)}
          placeholder={ta("logs.filterSearch" as TK)}
          value={filters.q}
          style={{ minWidth: 160 }}
          onChange={(_, d) => setFilter("q", d.value)}
        />
        {hasFilters ? (
          <Button
            appearance="subtle"
            icon={<DismissRegular />}
            onClick={() => {
              setOffset(0);
              setFilters(EMPTY_FILTERS);
            }}
          >
            {ta("logs.clearFilters" as TK)}
          </Button>
        ) : null}
      </div>

      {logs.loading ? (
        <Loading />
      ) : logs.error ? (
        <ErrorText error={logs.error} />
      ) : !data ? null : (
        <>
          <DataTable ariaLabel={ta("logs.audit" as TK)} minWidth={960}>
            <TableHeader>
              <TableRow>
                <TableHeaderCell>{ta("logs.time" as TK)}</TableHeaderCell>
                <TableHeaderCell>{ta("logs.actor" as TK)}</TableHeaderCell>
                <TableHeaderCell>{ta("logs.scope" as TK)}</TableHeaderCell>
                <TableHeaderCell>{ta("logs.action" as TK)}</TableHeaderCell>
                <TableHeaderCell>{ta("logs.target" as TK)}</TableHeaderCell>
                <TableHeaderCell>{ta("logs.detail" as TK)}</TableHeaderCell>
                <TableHeaderCell>{ta("logs.ip" as TK)}</TableHeaderCell>
                {isOwner ? <TableHeaderCell>{ta("logs.sensitive" as TK)}</TableHeaderCell> : null}
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
                      color={
                        a.scope === "admin"
                          ? "brand"
                          : a.scope === "system"
                            ? "warning"
                            : "informative"
                      }
                    >
                      {scopeLabel(a.scope)}
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
                          {ta("common.reveal" as TK)}
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
            <DialogTitle>{`${ta("logs.sensitiveTitle" as TK)} · ${revealed?.action}`}</DialogTitle>
            <DialogContent>
              <Text
                size={200}
                block
                style={{ color: tokens.colorNeutralForeground3, marginBottom: 8 }}
              >
                {ta("logs.sensitiveHint" as TK)}
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
                {ta("common.close" as TK)}
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
