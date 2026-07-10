import {
  Badge,
  Button,
  Combobox,
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
  Tooltip,
  tokens,
} from "@fluentui/react-components";
import {
  ArrowEnterRegular,
  BugRegular,
  DismissRegular,
  EyeRegular,
  InfoRegular,
  LockClosedRegular,
  PersonRegular,
} from "@fluentui/react-icons";
import { makeStyles } from "@fluentui/react-components";
import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { isRequestLog } from "../api/types";
import type {
  AuditFilterOptions,
  AuditLog,
  Page,
  RequestFilterOptions,
  RequestLog,
  RequestLogAttempt,
  RequestLogDetail,
} from "../api/types";
import type { Translations } from "../i18n/locales/en";
import {
  DataTable,
  ErrorText,
  Loading,
  PageHeader,
  Pager,
  formatDate,
  useAsync,
  useConfirm,
  useNotify,
} from "../components/ui";

const DEFAULT_PAGE = 50;

// Persistent highlight for a row the user jumped to. Unlike a brief flash this
// stays visible (with a strong brand accent + left bar) until the user moves the
// pointer / scrolls / types, so it's easy to spot even after an auto-scroll.
const useHighlightStyles = makeStyles({
  row: {
    backgroundColor: tokens.colorBrandBackground2,
    boxShadow: `inset 4px 0 0 0 ${tokens.colorBrandStroke1}`,
    transition: "background-color 0.5s ease-out, box-shadow 0.5s ease-out",
    // The first cell is sticky with its own opaque background, so it must be
    // repainted too or the highlight would be clipped to columns 2+.
    "& td:first-child": {
      backgroundColor: tokens.colorBrandBackground2,
    },
  },
});

/**
 * Shared "jump to a row by id" behaviour for the log tables:
 *   • auto-scrolls the target row into view once it renders (even when it was
 *     already on the current page but off-screen);
 *   • keeps a strong highlight on it until the user moves the pointer, scrolls,
 *     or types — then it clears on its own.
 *
 * ``dataDep`` should be the current page data, so a jump that changes the page
 * re-runs the scroll once the new rows arrive.
 */
function useIdJump(dataDep: unknown) {
  const [highlightId, setHighlightId] = useState<number | null>(null);
  const [scrollTarget, setScrollTarget] = useState<number | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const autoScrolling = useRef(false);

  // Scroll the target into view once it's present in the DOM. Runs again when
  // the page data changes (i.e. after a cross-page jump reloads the rows).
  useEffect(() => {
    if (scrollTarget == null) return;
    const el = containerRef.current?.querySelector<HTMLElement>(
      `[data-log-row="${scrollTarget}"]`,
    );
    if (el) {
      autoScrolling.current = true;
      el.scrollIntoView({ behavior: "smooth", block: "center" });
      setScrollTarget(null);
    }
  }, [scrollTarget, dataDep]);

  // Clear the highlight on user-initiated interaction (scroll, pointer move,
  // keypress). Ignores scroll events emitted during the auto-scroll animation.
  useEffect(() => {
    if (highlightId == null) return;
    const clear = () => {
      autoScrolling.current = false;
      setHighlightId(null);
    };
    const onScroll = () => {
      if (autoScrolling.current) {
        autoScrolling.current = false;
        return;
      }
      setHighlightId(null);
    };
    const el = containerRef.current;
    if (el) {
      el.addEventListener("scroll", onScroll, { passive: true });
    }
    window.addEventListener("pointermove", clear, { passive: true, once: true });
    window.addEventListener("touchmove", clear, { passive: true, once: true });
    window.addEventListener("keydown", clear, { passive: true, once: true });
    return () => {
      if (el) el.removeEventListener("scroll", onScroll);
      window.removeEventListener("pointermove", clear);
      window.removeEventListener("touchmove", clear);
      window.removeEventListener("keydown", clear);
    };
  }, [highlightId]);

  const markJump = useCallback((id: number) => {
    setHighlightId(id);
    setScrollTarget(id);
  }, []);

  return { highlightId, containerRef, markJump };
}

const useFilterStyles = makeStyles({
  // A table value that fills the matching filter when clicked. Looks like plain
  // text until hovered, so the tables stay readable but every cell is actionable.
  clickable: {
    background: "none",
    border: "none",
    padding: 0,
    margin: 0,
    font: "inherit",
    color: "inherit",
    textAlign: "left",
    cursor: "pointer",
    ":hover": { textDecoration: "underline" },
  },
});

interface SelectOption {
  value: string;
  label: string;
  sublabel?: string | null;
}

/**
 * A "type to search, then pick" filter — the same interaction as the model
 * picker above the chat. Reflects an externally-set value (e.g. filled by
 * clicking a table cell) and clears when emptied.
 */
function SearchSelect({
  value,
  options,
  onChange,
  placeholder,
  ariaLabel,
  minWidth = 170,
}: {
  value: string;
  options: SelectOption[];
  onChange: (value: string) => void;
  placeholder: string;
  ariaLabel: string;
  minWidth?: number;
}) {
  const selectedLabel = options.find((o) => o.value === value)?.label ?? value ?? "";
  const [text, setText] = useState(selectedLabel);
  const lastSelectedLabel = useRef(selectedLabel);
  const [typing, setTyping] = useState(false);

  // Keep the input in sync when the selection changes from outside (a table-cell
  // click that fills this filter, or a global "clear filters" reset).
  useEffect(() => {
    if (selectedLabel) lastSelectedLabel.current = selectedLabel;
    setText(value ? selectedLabel || lastSelectedLabel.current : "");
    setTyping(false);
  }, [selectedLabel, value]);

  const q = text.trim().toLowerCase();
  const filtered =
    typing && q
      ? options.filter(
          (o) =>
            o.label.toLowerCase().includes(q) || o.value.toLowerCase().includes(q),
        )
      : options;

  return (
    <Combobox
      aria-label={ariaLabel}
      placeholder={placeholder}
      style={{ minWidth }}
      freeform
      clearable
      value={text}
      selectedOptions={value ? [value] : []}
      onOptionSelect={(_, d) => {
        const v = d.optionValue ?? "";
        onChange(v);
        setTyping(false);
        setText(v ? options.find((o) => o.value === v)?.label ?? "" : "");
      }}
      onChange={(e) => {
        setText(e.target.value);
        setTyping(true);
      }}
      onOpenChange={(_, d) => {
        // On close, commit an emptied box as "no filter"; otherwise discard a
        // half-typed query and restore the current selection's label.
        if (!d.open) {
          if (!text.trim()) onChange("");
          else setText(selectedLabel || lastSelectedLabel.current);
          setTyping(false);
        }
      }}
    >
      {filtered.map((o) => (
        <Option key={o.value} value={o.value} text={o.label}>
          <div style={{ display: "flex", flexDirection: "column" }}>
            <span>{o.label}</span>
            {o.sublabel ? (
              <Text size={200} style={{ color: tokens.colorNeutralForeground3 }}>
                {o.sublabel}
              </Text>
            ) : null}
          </div>
        </Option>
      ))}
    </Combobox>
  );
}

export function Logs() {
  const { t } = useTranslation();
  type TK = keyof Translations;
  const { isStaff } = useAuth();
  const [tab, setTab] = useState<"requests" | "audit">("requests");
  const [refreshKey, setRefreshKey] = useState(0);
  const config = useAsync<{ logs_page_size?: number }>(() =>
    api.get("/api/auth/config"),
  );
  const pageSize = Math.max(1, config.data?.logs_page_size || DEFAULT_PAGE);

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
        onRefresh={() => setRefreshKey((k) => k + 1)}
      />
      <TabList
        selectedValue={tab}
        onTabSelect={(_, d) => setTab(d.value as typeof tab)}
      >
        <Tab value="requests">{t("logs.requests" as TK)}</Tab>
        {isStaff ? <Tab value="audit">{t("logs.audit" as TK)}</Tab> : null}
      </TabList>
      <div style={{ marginTop: 16 }}>
        {tab === "requests" ? (
          <RequestLogs refreshKey={refreshKey} pageSize={pageSize} />
        ) : (
          <AuditLogs refreshKey={refreshKey} pageSize={pageSize} />
        )}
      </div>
    </div>
  );
}

interface RequestFilters {
  model: string;
  user_sub: string;
  token_id: string;
  provider: string;
  status: string;
}

const EMPTY_REQUEST_FILTERS: RequestFilters = {
  model: "",
  user_sub: "",
  token_id: "",
  provider: "",
  status: "",
};

// A lone 1-5 digit means "the whole class": expand it to e.g. "4xx" on blur so
// the filter matches every 4xx status. Anything else is left as typed.
function normalizeStatus(value: string): string {
  const s = value.trim();
  return /^[1-5]$/.test(s) ? `${s}xx` : s;
}

function RequestLogs({
  refreshKey,
  pageSize,
}: {
  refreshKey: number;
  pageSize: number;
}) {
  const { t: tr } = useTranslation();
  type TK = keyof Translations;
  const { isOwner } = useAuth();
  const hl = useHighlightStyles();
  const cellStyles = useFilterStyles();
  const notify = useNotify();
  const [offset, setOffset] = useState(0);
  const [filters, setFilters] = useState<RequestFilters>(EMPTY_REQUEST_FILTERS);
  const [goToId, setGoToId] = useState("");
  const [detailLog, setDetailLog] = useState<RequestLogDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailMode, setDetailMode] = useState<"info" | "debug">("info");
  const [revealMode, setRevealMode] = useState(false);

  const options = useAsync<RequestFilterOptions>(
    () => api.get("/api/admin/logs/requests/filters"),
    [refreshKey],
  );

  const queryParams = {
    model: filters.model || undefined,
    user_sub: filters.user_sub || undefined,
    token_id: filters.token_id || undefined,
    provider: filters.provider || undefined,
    status_code: filters.status || undefined,
  };

  const logs = useAsync<Page<RequestLog>>(
    () =>
      api.get("/api/admin/logs/requests", {
        limit: pageSize,
        offset,
        ...queryParams,
      }),
    [
      offset,
      refreshKey,
      pageSize,
      filters.model,
      filters.user_sub,
      filters.token_id,
      filters.provider,
      filters.status,
    ],
  );
  const { highlightId, containerRef, markJump } = useIdJump(logs.data);

  function setFilter<K extends keyof RequestFilters>(
    key: K,
    value: RequestFilters[K],
  ) {
    setOffset(0);
    setFilters((f) => ({ ...f, [key]: value }));
  }

  const hasFilters = Object.values(filters).some((v) => v !== "");

  async function jumpToId() {
    const id = Number(goToId.trim());
    if (Number.isNaN(id) || id <= 0) return;
    try {
      const r = await api.get<{ offset: number; found: boolean }>(
        "/api/admin/logs/requests/locate",
        { id, ...queryParams },
      );
      if (!r.found) {
        notify(tr("logs.jumpNotFound" as TK), `#${id}`, "warning");
        return;
      }
      setOffset(Math.floor(r.offset / pageSize) * pageSize);
      markJump(id);
    } catch (e) {
      notify(
        tr("logs.jumpFailed" as TK),
        e instanceof Error ? e.message : String(e),
        "error",
      );
    }
  }

  async function openDetail(r: RequestLog, mode: "info" | "debug") {
    setDetailLoading(true);
    setRevealMode(false);
    setDetailMode(mode);
    try {
      const d = await api.get<unknown>(`/api/admin/logs/requests/${r.id}`);
      // Validate the shape at the boundary rather than trusting a blind cast, so
      // an API change surfaces as a controlled fallback instead of a broken
      // object rendered downstream.
      if (!isRequestLog(d)) throw new Error("unexpected log-detail shape");
      setDetailLog(d as RequestLogDetail);
    } catch {
      // Fallback to the row we already have. RequestLogDetail only adds optional
      // fields on top of RequestLog, so the row is a valid (if sparse) detail —
      // no unsafe cast needed.
      setDetailLog({ ...r });
    } finally {
      setDetailLoading(false);
    }
  }

  if (logs.loading) return <Loading />;
  if (logs.error) return <ErrorText error={logs.error} />;
  const data = logs.data;
  if (!data) return null;

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
        <SearchSelect
          ariaLabel={tr("logs.model" as TK)}
          placeholder={tr("logs.filterModel" as TK)}
          value={filters.model}
          options={(options.data?.models ?? []).map((m) => ({ value: m, label: m }))}
          onChange={(v) => setFilter("model", v)}
        />
        <SearchSelect
          ariaLabel={tr("logs.user" as TK)}
          placeholder={tr("logs.filterUser" as TK)}
          value={filters.user_sub}
          options={(options.data?.users ?? []).map((u) => ({
            value: u.sub,
            label: u.name,
          }))}
          onChange={(v) => setFilter("user_sub", v)}
        />
        <SearchSelect
          ariaLabel={tr("logs.token" as TK)}
          placeholder={tr("logs.filterToken" as TK)}
          value={filters.token_id}
          options={(options.data?.tokens ?? []).map((tk) => ({
            value: String(tk.id),
            label: tk.name,
            sublabel: tk.user_name,
          }))}
          onChange={(v) => setFilter("token_id", v)}
        />
        <Dropdown
          aria-label={tr("logs.provider" as TK)}
          placeholder={tr("logs.filterProvider" as TK)}
          style={{ minWidth: 150 }}
          clearable
          selectedOptions={filters.provider ? [filters.provider] : []}
          value={filters.provider}
          onOptionSelect={(_, d) => setFilter("provider", d.optionValue ?? "")}
        >
          {(options.data?.providers ?? []).map((p) => (
            <Option key={p} value={p} text={p}>
              {p}
            </Option>
          ))}
        </Dropdown>
        <Input
          aria-label={tr("logs.status" as TK)}
          placeholder={tr("logs.filterStatus" as TK)}
          value={filters.status}
          style={{ minWidth: 96, maxWidth: 120 }}
          onChange={(_, d) => setFilter("status", d.value)}
          onBlur={() => setFilter("status", normalizeStatus(filters.status))}
        />
        <Input
          aria-label={tr("logs.goToId" as TK)}
          placeholder={tr("logs.goToId" as TK)}
          value={goToId}
          type="number"
          style={{ minWidth: 120 }}
          onChange={(_, d) => setGoToId(d.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") void jumpToId();
          }}
        />
        <Tooltip content={tr("logs.jump" as TK)} relationship="label">
          <Button
            icon={<ArrowEnterRegular />}
            disabled={!goToId.trim()}
            onClick={() => void jumpToId()}
            aria-label={tr("logs.jump" as TK)}
          >
            {tr("logs.jump" as TK)}
          </Button>
        </Tooltip>
        {hasFilters ? (
          <Button
            appearance="subtle"
            icon={<DismissRegular />}
            onClick={() => {
              setOffset(0);
              setFilters(EMPTY_REQUEST_FILTERS);
            }}
          >
            {tr("logs.clearFilters" as TK)}
          </Button>
        ) : null}
      </div>
      <div ref={containerRef}>
      <DataTable ariaLabel={tr("logs.requests" as TK)} minWidth={960}>
        <TableHeader>
          <TableRow>
            <TableHeaderCell>{tr("logs.id" as TK)}</TableHeaderCell>
            <TableHeaderCell>{tr("logs.time" as TK)}</TableHeaderCell>
            <TableHeaderCell>{tr("logs.user" as TK)}</TableHeaderCell>
            <TableHeaderCell>{tr("logs.token" as TK)}</TableHeaderCell>
            <TableHeaderCell>{tr("logs.model" as TK)}</TableHeaderCell>
            <TableHeaderCell>{tr("logs.status" as TK)}</TableHeaderCell>
            <TableHeaderCell>{tr("logs.tokens" as TK)}</TableHeaderCell>
            <TableHeaderCell>{tr("logs.tries" as TK)}</TableHeaderCell>
            <TableHeaderCell style={{ width: 96 }} />
          </TableRow>
        </TableHeader>
        <TableBody>
          {data.items.map((r) => (
            <TableRow
              key={r.id}
              data-log-row={r.id}
              className={r.id === highlightId ? hl.row : undefined}
            >
              <TableCell
                style={{
                  color: tokens.colorNeutralForeground3,
                  fontFamily: "monospace",
                }}
              >
                {r.id}
              </TableCell>
              <TableCell style={{ color: tokens.colorNeutralForeground3 }}>
                {formatDate(r.ts)}
              </TableCell>
              <TableCell>
                {r.user_sub ? (
                  <button
                    type="button"
                    className={cellStyles.clickable}
                    title={tr("logs.clickToFilter" as TK)}
                    onClick={() => setFilter("user_sub", r.user_sub ?? "")}
                  >
                    {r.user_name ?? r.user_sub}
                  </button>
                ) : (
                  "—"
                )}
              </TableCell>
              <TableCell style={{ color: tokens.colorNeutralForeground3 }}>
                {r.token_id != null ? (
                  <div>
                    <button
                      type="button"
                      className={cellStyles.clickable}
                      title={tr("logs.clickToFilter" as TK)}
                      onClick={() => setFilter("token_id", String(r.token_id))}
                    >
                      {r.token_name ?? `#${r.token_id}`}
                    </button>
                    {r.token_owner_name ? (
                      <Text size={100} block style={{ color: tokens.colorNeutralForeground3 }}>
                        {r.token_owner_name}
                      </Text>
                    ) : null}
                  </div>
                ) : (
                  "—"
                )}
              </TableCell>
              <TableCell>
                {r.model ? (
                  <button
                    type="button"
                    className={cellStyles.clickable}
                    title={tr("logs.clickToFilter" as TK)}
                    onClick={() => setFilter("model", r.model ?? "")}
                  >
                    {r.model}
                  </button>
                ) : (
                  "—"
                )}
              </TableCell>
              <TableCell>
                <button
                  type="button"
                  className={cellStyles.clickable}
                  title={tr("logs.clickToFilter" as TK)}
                  onClick={() =>
                    setFilter(
                      "status",
                      r.status_code != null ? String(r.status_code) : "",
                    )
                  }
                >
                  <Badge
                    color={r.success ? "success" : "danger"}
                    appearance="filled"
                    style={{ cursor: "pointer" }}
                  >
                    {r.status_code ?? "ERR"}
                  </Badge>
                </button>
              </TableCell>
              <TableCell>{r.total_tokens}</TableCell>
              <TableCell>{r.attempts}</TableCell>
              <TableCell>
                <div style={{ display: "flex", gap: 4 }}>
                  <Tooltip content={tr("logs.viewDetail" as TK)} relationship="label">
                    <Button
                      size="small"
                      appearance="subtle"
                      icon={<InfoRegular />}
                      disabled={detailLoading}
                      aria-label={tr("logs.viewDetail" as TK)}
                      onClick={() => openDetail(r, "info")}
                    />
                  </Tooltip>
                  {/* Debug detail is owner / co-owner only, and only exists for
                      rows recorded in debug mode. */}
                  {isOwner && r.debug ? (
                    <Tooltip content={tr("logs.viewDebug" as TK)} relationship="label">
                      <Button
                        size="small"
                        appearance="subtle"
                        icon={<BugRegular />}
                        disabled={detailLoading}
                        aria-label={tr("logs.viewDebug" as TK)}
                        onClick={() => openDetail(r, "debug")}
                      />
                    </Tooltip>
                  ) : null}
                </div>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </DataTable>
      </div>
      <Pager
        total={data.total}
        offset={offset}
        limit={pageSize}
        onChange={setOffset}
      />

      {/* Detail modal */}
      <Dialog
        open={detailLog !== null}
        onOpenChange={(_, d) => { if (!d.open) setDetailLog(null); }}
        modalType="non-modal"
      >
        <DialogSurface style={{ maxWidth: 820, width: "100%" }}>
          <DialogBody>
            <DialogTitle>
              {tr("logs.requestDetailTitle" as TK).replace("{id}", String(detailLog?.id ?? ""))}
              {detailMode === "debug" ? (
                <Badge color="warning" appearance="tint" style={{ marginLeft: 8 }}>debug</Badge>
              ) : null}
            </DialogTitle>
            <DialogContent>
              {detailLog && (
                <div style={{ display: "flex", flexDirection: "column", gap: 12, fontFamily: tokens.fontFamilyBase }}>
                  {/* Summary grid */}
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "4px 16px", fontSize: tokens.fontSizeBase200 }}>
                    <DetailRow label={tr("logs.time" as TK)} value={formatDate(detailLog.ts)} />
                    <DetailRow label={tr("logs.status" as TK)} value={detailLog.success ? `${detailLog.status_code} OK` : `${detailLog.status_code ?? "ERR"}`} />
                    <DetailRow label={tr("logs.user" as TK)} value={detailLog.user_name ?? detailLog.user_sub ?? "—"} />
                    <DetailRow
                      label={tr("logs.token" as TK)}
                      value={
                        detailLog.token_owner_name
                          ? `${detailLog.token_name ?? (detailLog.token_id != null ? `#${detailLog.token_id}` : "—")} (${detailLog.token_owner_name})`
                          : detailLog.token_name ?? (detailLog.token_id != null ? `#${detailLog.token_id}` : "—")
                      }
                    />
                    <DetailRow label={tr("logs.model" as TK)} value={detailLog.model ?? "—"} />
                    {detailLog.upstream_model &&
                    detailLog.upstream_model !== detailLog.model ? (
                      <DetailRow
                        label={tr("logs.modelRoute" as TK)}
                        value={`${detailLog.model ?? "?"} → ${detailLog.upstream_model}`}
                      />
                    ) : null}
                    <DetailRow label={tr("logs.provider" as TK)} value={detailLog.provider_name ?? "—"} />
                    <DetailRow label={tr("logs.key" as TK)} value={detailLog.key_preview ?? (detailLog.key_id != null ? `#${detailLog.key_id}` : "—")} />
                    <DetailRow label={tr("logs.proxy" as TK)} value={detailLog.proxy_url ?? (detailLog.proxy_id != null ? `#${detailLog.proxy_id}` : "—")} />
                    <DetailRow label={tr("logs.route" as TK)} value={`${detailLog.inbound_style ?? "?"}→${detailLog.upstream_style ?? "?"}`} />
                    <DetailRow label={tr("logs.stream" as TK)} value={detailLog.stream ? "yes" : "no"} />
                    <DetailRow label={tr("logs.tries" as TK)} value={String(detailLog.attempts)} />
                    <DetailRow label={tr("logs.tokens" as TK)} value={`${detailLog.prompt_tokens}+${detailLog.completion_tokens}=${detailLog.total_tokens}`} />
                    {detailLog.latency_ms != null && <DetailRow label={tr("logs.latency" as TK)} value={`${Math.round(detailLog.latency_ms)}ms`} />}
                    {detailLog.upstream_url && <DetailRow label={tr("logs.upstreamUrl" as TK)} value={detailLog.upstream_url} />}
                    <DetailRow label={tr("logs.userAgent" as TK)} value={detailLog.user_agent ?? "—"} />
                    <DetailRow label={tr("logs.clientType" as TK)} value={detailLog.client_type ?? "—"} />
                    <DetailRow label={tr("logs.opencode" as TK)} value={detailLog.is_opencode ? "yes" : "no"} />
                  </div>

                  {detailLog.error && (
                    <div>
                      <Text size={200} weight="semibold" block style={{ color: tokens.colorPaletteRedForeground1, marginBottom: 2 }}>
                        {tr("logs.error" as TK)}
                      </Text>
                      <Text size={200} block style={{ color: tokens.colorPaletteRedForeground1, fontFamily: "monospace", whiteSpace: "pre-wrap", wordBreak: "break-all" }}>
                        {detailLog.error}
                      </Text>
                    </div>
                  )}

                  {/* Debug view — owner / co-owner only, only reachable via the
                      dedicated debug button on a debug-recorded row. */}
                  {detailMode === "debug" && (
                    <div style={{ borderTop: `1px solid ${tokens.colorNeutralStroke2}`, paddingTop: 8 }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
                        <Text size={200} weight="semibold">{tr("logs.debugData" as TK)}</Text>
                        {isOwner && (
                          <Button
                            size="small"
                            appearance={revealMode ? "primary" : "subtle"}
                            icon={<EyeRegular />}
                            onClick={() => setRevealMode(!revealMode)}
                          >
                            {revealMode ? tr("logs.revealOn" as TK) : tr("logs.revealSecret" as TK)}
                          </Button>
                        )}
                      </div>
                      {isOwner ? (
                        <>
                          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "4px 16px", fontSize: tokens.fontSizeBase200, marginBottom: 8 }}>
                            <DetailRow label={tr("logs.method" as TK)} value={detailLog.req_method ?? "—"} />
                            <DetailRow label={tr("logs.upstreamUrl" as TK)} value={detailLog.upstream_url ?? "—"} />
                            <DetailRow label={tr("logs.proxy" as TK)} value={detailLog.proxy_url ?? (detailLog.proxy_id != null ? `#${detailLog.proxy_id}` : "—")} />
                            <DetailRow label={tr("logs.key" as TK)} value={detailLog.key_preview ?? (detailLog.key_id != null ? `#${detailLog.key_id}` : "—")} />
                          </div>
                          <CodeBlock label={tr("logs.reqHeaders" as TK)} value={detailLog.req_headers} />
                          <CodeBlock label={tr("logs.reqBody" as TK)} value={detailLog.req_body} />
                          <CodeBlock label={tr("logs.respHeaders" as TK)} value={detailLog.resp_headers} />
                          <CodeBlock label={tr("logs.respBody" as TK)} value={detailLog.resp_body} />
                          {detailLog.debug_attempts && detailLog.debug_attempts.length > 0 ? (
                            <AttemptTrail attempts={detailLog.debug_attempts} />
                          ) : null}
                        </>
                      ) : (
                        <Text size={200} style={{ color: tokens.colorNeutralForeground3 }}>
                          {tr("logs.debugOwnerOnly" as TK)}
                        </Text>
                      )}
                    </div>
                  )}
                </div>
              )}
            </DialogContent>
            <DialogActions>
              <Button appearance="primary" onClick={() => setDetailLog(null)}>
                {tr("common.close" as TK)}
              </Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </>
  );
}

function DetailRow({ label, value }: { label: string; value: string }) {
  return (
    <>
      <Text size={200} weight="semibold" style={{ color: tokens.colorNeutralForeground3 }}>{label}</Text>
      <Text size={200} style={{ wordBreak: "break-all" }}>{value}</Text>
    </>
  );
}

function CodeBlock({ label, value }: { label: string; value: unknown }) {
  if (value == null) return null;
  const str = typeof value === "string" ? value : JSON.stringify(value, null, 2);
  if (!str || str === "{}" || str === "null") return null;
  return (
    <div style={{ marginBottom: 6 }}>
      <Text size={200} weight="semibold" block style={{ color: tokens.colorNeutralForeground3, marginBottom: 2 }}>
        {label}
      </Text>
      <pre style={{
        margin: 0,
        padding: 8,
        fontSize: tokens.fontSizeBase100,
        fontFamily: "monospace",
        background: tokens.colorNeutralBackground3,
        borderRadius: tokens.borderRadiusMedium,
        maxHeight: 240,
        overflow: "auto",
        whiteSpace: "pre-wrap",
        wordBreak: "break-all",
      }}>
        {str}
      </pre>
    </div>
  );
}

function AttemptTrail({ attempts }: { attempts: RequestLogAttempt[] }) {
  const { t } = useTranslation();
  type TK = keyof Translations;
  return (
    <div style={{ marginTop: 8 }}>
      <Text
        size={200}
        weight="semibold"
        block
        style={{ color: tokens.colorNeutralForeground3, marginBottom: 4 }}
      >
        {t("logs.attempts" as TK)} ({attempts.length})
      </Text>
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {attempts.map((a, i) => {
          const ok =
            !a.network_error &&
            a.status_code != null &&
            a.status_code >= 200 &&
            a.status_code < 300;
          const statusLabel = a.network_error
            ? t("logs.networkError" as TK)
            : (a.status_code ?? "ERR");
          return (
            <div
              key={a.attempt ?? i}
              style={{
                border: `1px solid ${tokens.colorNeutralStroke2}`,
                borderRadius: tokens.borderRadiusMedium,
                padding: 8,
              }}
            >
              <div
                style={{
                  display: "flex",
                  flexWrap: "wrap",
                  alignItems: "center",
                  gap: 8,
                  marginBottom: 6,
                }}
              >
                <Badge appearance="tint" color="informative">
                  #{a.attempt ?? i + 1}
                </Badge>
                <Badge appearance="filled" color={ok ? "success" : "danger"}>
                  {statusLabel}
                </Badge>
                {a.error_class ? (
                  <Badge appearance="outline">{a.error_class}</Badge>
                ) : null}
                <Text size={200} style={{ color: tokens.colorNeutralForeground3 }}>
                  {a.provider ?? "—"}
                  {a.upstream_model ? ` · ${a.upstream_model}` : ""}
                  {a.key_preview ? ` · ${a.key_preview}` : ""}
                  {a.proxy_url ? ` · ${a.proxy_url}` : ` · ${t("logs.direct" as TK)}`}
                  {a.duration_ms != null ? ` · ${Math.round(a.duration_ms)}ms` : ""}
                </Text>
              </div>
              <Text
                size={200}
                block
                style={{
                  color: tokens.colorNeutralForeground3,
                  fontFamily: "monospace",
                  wordBreak: "break-all",
                  marginBottom: 4,
                }}
              >
                {`${a.method ?? "POST"} ${a.url ?? "—"}`}
              </Text>
              {a.error ? (
                <Text
                  size={200}
                  block
                  style={{
                    color: tokens.colorPaletteRedForeground1,
                    fontFamily: "monospace",
                    whiteSpace: "pre-wrap",
                    wordBreak: "break-all",
                    marginBottom: 4,
                  }}
                >
                  {a.error}
                </Text>
              ) : null}
              <CodeBlock label={t("logs.reqHeaders" as TK)} value={a.req_headers} />
              <CodeBlock label={t("logs.reqBody" as TK)} value={a.req_body} />
              <CodeBlock label={t("logs.respHeaders" as TK)} value={a.resp_headers} />
              <CodeBlock label={t("logs.respBody" as TK)} value={a.resp_body} />
            </div>
          );
        })}
      </div>
    </div>
  );
}

interface AuditFilters {
  scope: string;
  action: string;
  target_type: string;
  actor_sub: string;
  ip: string;
  user_agent: string;
}

const EMPTY_FILTERS: AuditFilters = {
  scope: "",
  action: "",
  target_type: "",
  actor_sub: "",
  ip: "",
  user_agent: "",
};

function AuditLogs({
  refreshKey,
  pageSize,
}: {
  refreshKey: number;
  pageSize: number;
}) {
  const { t: ta } = useTranslation();
  type TK = keyof Translations;
  const { isOwner } = useAuth();
  const confirm = useConfirm();
  const notify = useNotify();
  const hl = useHighlightStyles();
  const cellStyles = useFilterStyles();
  const [offset, setOffset] = useState(0);
  const [filters, setFilters] = useState<AuditFilters>(EMPTY_FILTERS);
  const [goToId, setGoToId] = useState("");
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
        limit: pageSize,
        offset,
        scope: filters.scope || undefined,
        action: filters.action || undefined,
        target_type: filters.target_type || undefined,
        actor_sub: filters.actor_sub || undefined,
        ip: filters.ip || undefined,
        user_agent: filters.user_agent || undefined,
      }),
    [
      offset,
      filters.scope,
      filters.action,
      filters.target_type,
      filters.actor_sub,
      filters.ip,
      filters.user_agent,
      refreshKey,
      pageSize,
    ],
  );
  const { highlightId, containerRef, markJump } = useIdJump(logs.data);

  async function jumpToId() {
    const id = Number(goToId.trim());
    if (Number.isNaN(id) || id <= 0) return;
    try {
      const r = await api.get<{ offset: number; found: boolean }>(
        "/api/admin/logs/audit/locate",
        {
          id,
          scope: filters.scope || undefined,
          action: filters.action || undefined,
          target_type: filters.target_type || undefined,
          actor_sub: filters.actor_sub || undefined,
          ip: filters.ip || undefined,
          user_agent: filters.user_agent || undefined,
        },
      );
      if (!r.found) {
        notify(ta("logs.jumpNotFound" as TK), `#${id}`, "warning");
        return;
      }
      setOffset(Math.floor(r.offset / pageSize) * pageSize);
      markJump(id);
    } catch (e) {
      notify(
        ta("logs.jumpFailed" as TK),
        e instanceof Error ? e.message : String(e),
        "error",
      );
    }
  }

  function setFilter<K extends keyof AuditFilters>(
    key: K,
    value: AuditFilters[K],
  ) {
    setOffset(0);
    setFilters((f) => ({ ...f, [key]: value }));
  }

  const hasFilters = Object.values(filters).some((v) => v !== "");
  const opts = options.data;
  const scopeLabel = (s: string) =>
    s === "admin"
      ? ta("common.admin" as TK)
        : s === "self"
          ? ta("common.self" as TK)
        : s === "system"
          ? ta("common.system" as TK)
          : s;
  const scopeIcon = (s: string) =>
    s === "admin" ? <LockClosedRegular /> : s === "self" ? <PersonRegular /> : null;

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
        <SearchSelect
          ariaLabel={ta("logs.actor" as TK)}
          placeholder={ta("logs.filterActor" as TK)}
          value={filters.actor_sub}
          options={(opts?.actors ?? []).map((a) => ({
            value: a.sub,
            label: a.name,
          }))}
          onChange={(v) => setFilter("actor_sub", v)}
        />
        <Input
          aria-label={ta("logs.ip" as TK)}
          placeholder={ta("logs.filterIp" as TK)}
          value={filters.ip}
          style={{ minWidth: 130 }}
          onChange={(_, d) => setFilter("ip", d.value)}
        />
        <Input
          aria-label={ta("logs.userAgent" as TK)}
          placeholder={ta("logs.filterUa" as TK)}
          value={filters.user_agent}
          style={{ minWidth: 150 }}
          onChange={(_, d) => setFilter("user_agent", d.value)}
        />
        <Input
          aria-label={ta("logs.goToId" as TK)}
          placeholder={ta("logs.goToId" as TK)}
          value={goToId}
          type="number"
          style={{ minWidth: 120 }}
          onChange={(_, d) => setGoToId(d.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") void jumpToId();
          }}
        />
        <Tooltip content={ta("logs.jump" as TK)} relationship="label">
          <Button
            icon={<ArrowEnterRegular />}
            disabled={!goToId.trim()}
            onClick={() => void jumpToId()}
            aria-label={ta("logs.jump" as TK)}
          >
            {ta("logs.jump" as TK)}
          </Button>
        </Tooltip>
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
          <div ref={containerRef}>
          <DataTable ariaLabel={ta("logs.audit" as TK)} minWidth={1020}>
            <TableHeader>
              <TableRow>
                <TableHeaderCell>{ta("logs.id" as TK)}</TableHeaderCell>
                <TableHeaderCell>{ta("logs.time" as TK)}</TableHeaderCell>
                <TableHeaderCell>{ta("logs.actor" as TK)}</TableHeaderCell>
                <TableHeaderCell>{ta("logs.scope" as TK)}</TableHeaderCell>
                <TableHeaderCell>{ta("logs.action" as TK)}</TableHeaderCell>
                <TableHeaderCell>{ta("logs.target" as TK)}</TableHeaderCell>
                <TableHeaderCell>{ta("logs.detail" as TK)}</TableHeaderCell>
                <TableHeaderCell>{ta("logs.ip" as TK)}</TableHeaderCell>
                <TableHeaderCell>{ta("logs.userAgent" as TK)}</TableHeaderCell>
                {isOwner ? <TableHeaderCell>{ta("logs.sensitive" as TK)}</TableHeaderCell> : null}
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.items.map((a) => (
                <TableRow
                  key={a.id}
                  data-log-row={a.id}
                  className={a.id === highlightId ? hl.row : undefined}
                >
                  <TableCell style={{ color: tokens.colorNeutralForeground3, fontFamily: "monospace" }}>
                    {a.id}
                  </TableCell>
                  <TableCell style={{ color: tokens.colorNeutralForeground3 }}>
                    {formatDate(a.ts)}
                  </TableCell>
                  <TableCell>
                    {a.actor_sub ? (
                      <button
                        type="button"
                        className={cellStyles.clickable}
                        title={ta("logs.clickToFilter" as TK)}
                        onClick={() => setFilter("actor_sub", a.actor_sub ?? "")}
                      >
                        {a.actor_name ?? a.actor_sub}
                      </button>
                    ) : (
                      "—"
                    )}
                  </TableCell>
                  <TableCell>
                    <button
                      type="button"
                      className={cellStyles.clickable}
                      title={ta("logs.clickToFilter" as TK)}
                      onClick={() => setFilter("scope", a.scope)}
                    >
                      <Tooltip content={scopeLabel(a.scope)} relationship="label">
                        {scopeIcon(a.scope) ?? (
                          <Badge appearance="tint">{scopeLabel(a.scope)}</Badge>
                        )}
                      </Tooltip>
                    </button>
                  </TableCell>
                  <TableCell>
                    <button
                      type="button"
                      className={cellStyles.clickable}
                      title={ta("logs.clickToFilter" as TK)}
                      onClick={() => setFilter("action", a.action)}
                    >
                      {a.action}
                    </button>
                  </TableCell>
                  <TableCell>
                    {a.target_type ? (
                      <button
                        type="button"
                        className={cellStyles.clickable}
                        title={ta("logs.clickToFilter" as TK)}
                        onClick={() => setFilter("target_type", a.target_type ?? "")}
                      >
                        {`${a.target_type}#${a.target_id ?? ""}`}
                      </button>
                    ) : (
                      "—"
                    )}
                  </TableCell>
                  <TableCell style={{ maxWidth: 280 }}>
                    <DetailCell detail={a.detail} />
                  </TableCell>
                  <TableCell>
                    {a.ip ? (
                      <button
                        type="button"
                        className={cellStyles.clickable}
                        title={ta("logs.clickToFilter" as TK)}
                        onClick={() => setFilter("ip", a.ip ?? "")}
                      >
                        {a.ip}
                      </button>
                    ) : (
                      "—"
                    )}
                  </TableCell>
                  <TableCell>
                    {a.user_agent ? (
                      <Tooltip content={a.user_agent} relationship="label" positioning="above">
                        <button
                          type="button"
                          className={cellStyles.clickable}
                          title={ta("logs.clickToFilter" as TK)}
                          onClick={() => setFilter("user_agent", a.user_agent ?? "")}
                          style={{ color: tokens.colorNeutralForeground3 }}
                        >
                          {a.user_agent.length > 20 ? `${a.user_agent.slice(0, 20)}…` : a.user_agent}
                        </button>
                      </Tooltip>
                    ) : "—"}
                  </TableCell>
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
          </div>
          <Pager
            total={data.total}
            offset={offset}
            limit={pageSize}
            onChange={setOffset}
          />
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

function DetailCell({ detail }: { detail: Record<string, unknown> }) {
  const str = JSON.stringify(detail);
  if (str.length <= 30) {
    return (
      <Text size={200} style={{ color: tokens.colorNeutralForeground3 }}>
        {str}
      </Text>
    );
  }
  return (
    <Tooltip content={str} relationship="label" positioning="above" withArrow>
      <Text
        size={200}
        style={{
          color: tokens.colorNeutralForeground3,
          cursor: "default",
          display: "-webkit-box",
          WebkitLineClamp: 2,
          WebkitBoxOrient: "vertical",
          overflow: "hidden",
          textOverflow: "ellipsis",
        }}
      >
        {str}
      </Text>
    </Tooltip>
  );
}
