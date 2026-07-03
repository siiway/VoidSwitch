import {
  Badge,
  Button,
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  Input,
  MessageBar,
  MessageBarBody,
  Spinner,
  Table,
  Text,
  Toast,
  ToastBody,
  ToastTitle,
  Toaster,
  Tooltip,
  mergeClasses,
  tokens,
  useId,
  useToastController,
} from "@fluentui/react-components";
import {
  ArrowSyncRegular,
  ChevronLeftRegular,
  ChevronRightRegular,
} from "@fluentui/react-icons";
import { useTranslation } from "react-i18next";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { makeStyles } from "@fluentui/react-components";

// --- async data loading --------------------------------------------------- //

export interface AsyncState<T> {
  data: T | null;
  loading: boolean;
  refreshing: boolean;
  error: string | null;
  reload: () => void;
}

export function useAsync<T>(
  fn: () => Promise<T>,
  deps: unknown[] = [],
): AsyncState<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const hasData = data !== null;

  useEffect(() => {
    let alive = true;
    // Only show the full-page spinner on the very first load; subsequent
    // reloads (e.g. after adding a row) keep the current data on screen.
    if (hasData) setRefreshing(true);
    else setLoading(true);
    setError(null);
    fn()
      .then((d) => alive && setData(d))
      .catch(
        (e) => alive && setError(e instanceof Error ? e.message : String(e)),
      )
      .finally(() => {
        if (!alive) return;
        setLoading(false);
        setRefreshing(false);
      });
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tick, ...deps]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { data, loading, refreshing, error, reload };
}

// --- toasts ---------------------------------------------------------------- //

type Intent = "success" | "error" | "warning" | "info";
type Notify = (title: string, body?: string, intent?: Intent) => void;

const ToastContext = createContext<Notify>(() => {});

export function ToastProvider({ children }: { children: ReactNode }) {
  const toasterId = useId("toaster");
  const { dispatchToast } = useToastController(toasterId);

  const notify: Notify = useCallback(
    (title, body, intent = "info") => {
      dispatchToast(
        <Toast>
          <ToastTitle>{title}</ToastTitle>
          {body ? <ToastBody>{body}</ToastBody> : null}
        </Toast>,
        { intent, timeout: intent === "error" ? 6000 : 3000 },
      );
    },
    [dispatchToast],
  );

  return (
    <ToastContext.Provider value={notify}>
      <Toaster toasterId={toasterId} position="top-end" />
      {children}
    </ToastContext.Provider>
  );
}

export function useNotify(): Notify {
  return useContext(ToastContext);
}

// --- confirmation dialog --------------------------------------------------- //

interface ConfirmOptions {
  title?: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  tone?: "primary" | "danger";
}

type Confirm = (opts: ConfirmOptions) => Promise<boolean>;

const ConfirmContext = createContext<Confirm>(async () => false);

export function ConfirmProvider({ children }: { children: ReactNode }) {
  const { t } = useTranslation();
  const [opts, setOpts] = useState<ConfirmOptions | null>(null);
  const resolver = useRef<((ok: boolean) => void) | null>(null);

  const confirm = useCallback<Confirm>((options) => {
    setOpts(options);
    return new Promise<boolean>((resolve) => {
      resolver.current = resolve;
    });
  }, []);

  const settle = useCallback((ok: boolean) => {
    resolver.current?.(ok);
    resolver.current = null;
    setOpts(null);
  }, []);

  return (
    <ConfirmContext.Provider value={confirm}>
      {children}
      <Dialog
        open={opts !== null}
        modalType="alert"
        onOpenChange={(_, d) => {
          if (!d.open) settle(false);
        }}
      >
        <DialogSurface>
          <DialogBody>
              <DialogTitle>
                {opts?.title ?? t("common.areYouSure")}
              </DialogTitle>
              <DialogContent>{opts?.message}</DialogContent>
              <DialogActions>
                <Button appearance="secondary" onClick={() => settle(false)}>
                  {opts?.cancelLabel ?? t("common.cancel")}
                </Button>
              <Button
                appearance={opts?.tone === "danger" ? "primary" : "primary"}
                style={
                  opts?.tone === "danger"
                    ? {
                        backgroundColor: tokens.colorPaletteRedBackground3,
                        borderColor: tokens.colorPaletteRedBackground3,
                      }
                    : undefined
                }
                onClick={() => settle(true)}
              >
                {opts?.confirmLabel ?? t("common.confirm")}
              </Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </ConfirmContext.Provider>
  );
}

export function useConfirm(): Confirm {
  return useContext(ConfirmContext);
}

// --- small presentational helpers ----------------------------------------- //

const useSpinStyles = makeStyles({
  spin: {
    animationName: {
      from: { transform: "rotate(0deg)" },
      to: { transform: "rotate(360deg)" },
    },
    animationDuration: "0.7s",
    animationIterationCount: "infinite",
    animationTimingFunction: "linear",
  },
});

export function PageHeader({
  title,
  subtitle,
  action,
  onRefresh,
  refreshing,
}: {
  title: string;
  subtitle?: string;
  action?: ReactNode;
  onRefresh?: () => void;
  // Keep the icon spinning while an async reload is in flight.
  refreshing?: boolean;
}) {
  const spinStyles = useSpinStyles();
  const { t } = useTranslation();
  const [spinning, setSpinning] = useState(false);
  const spin = spinning || !!refreshing;

  const handleRefresh = useCallback(() => {
    if (!onRefresh) return;
    setSpinning(true);
    onRefresh();
    // Visual feedback even when the reload resolves instantly.
    window.setTimeout(() => setSpinning(false), 700);
  }, [onRefresh]);

  return (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "flex-end",
        marginBottom: 16,
        gap: 12,
        flexWrap: "wrap",
      }}
    >
      <div>
        <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <Text size={600} weight="semibold" as="h1">
            {title}
          </Text>
          {onRefresh ? (
            <Tooltip content={t("common.refresh")} relationship="label">
              <Button
                size="small"
                appearance="subtle"
                icon={
                  <ArrowSyncRegular className={spin ? spinStyles.spin : undefined} />
                }
                onClick={handleRefresh}
                aria-label={t("common.refresh")}
              />
            </Tooltip>
          ) : null}
        </div>
        {subtitle ? (
          <Text size={200} style={{ color: "var(--colorNeutralForeground3)" }}>
            {subtitle}
          </Text>
        ) : null}
      </div>
      {action}
    </div>
  );
}

const STATUS_COLORS: Record<
  string,
  "success" | "danger" | "warning" | "subtle" | "informative"
> = {
  active: "success",
  invalid: "danger",
  insufficient_balance: "warning",
  rate_limited: "warning",
  disabled: "subtle",
};

const useBadgeStyles = makeStyles({
  // Fluent's Badge is a fixed-height pill with `white-space: nowrap`, so a long
  // status like "insufficient balance" overflows and gets clipped. Let it grow
  // and wrap inside its cell instead.
  wrap: {
    height: "auto",
    minHeight: "20px",
    whiteSpace: "normal",
    textAlign: "center",
    overflowWrap: "anywhere",
    paddingTop: "2px",
    paddingBottom: "2px",
    lineHeight: "1.2",
  },
});

export function StatusBadge({ status }: { status: string }) {
  const styles = useBadgeStyles();
  const color = STATUS_COLORS[status] ?? "informative";
  return (
    <Badge
      appearance="filled"
      color={color}
      shape="rounded"
      className={styles.wrap}
    >
      {status.replace(/_/g, " ")}
    </Badge>
  );
}

export function Loading({ label }: { label?: string }) {
  const { t } = useTranslation();
  return (
    <div style={{ display: "grid", placeItems: "center", padding: 48 }}>
      <Spinner label={label ?? t("common.loading")} />
    </div>
  );
}

/**
 * Prominent, page-level error surface. Uses Fluent's MessageBar (intent="error")
 * so theme/accent-aware error styling stays consistent instead of bespoke red
 * Text. Kept named `ErrorText` so existing call sites don't churn.
 */
export function ErrorText({ error }: { error: string }) {
  return (
    <MessageBar intent="error">
      <MessageBarBody>{error}</MessageBarBody>
    </MessageBar>
  );
}

// --- data table ------------------------------------------------------------ //

const useTableStyles = makeStyles({
  scroll: {
    width: "100%",
    maxWidth: "100%",
    overflowX: "auto",
    WebkitOverflowScrolling: "touch",
    scrollBehavior: "smooth",
    backgroundImage: `linear-gradient(to right, ${tokens.colorNeutralBackground1} 30%, transparent),
      linear-gradient(to left, ${tokens.colorNeutralBackground1} 30%, transparent),
      radial-gradient(farthest-side at 0% 50%, rgba(0,0,0,0.12), transparent),
      radial-gradient(farthest-side at 100% 50%, rgba(0,0,0,0.12), transparent)`,
    backgroundPosition: "0 0, 100% 0, 0 0, 100% 0",
    backgroundRepeat: "no-repeat",
    backgroundSize: "40px 100%, 40px 100%, 16px 100%, 16px 100%",
    backgroundAttachment: "local, local, scroll, scroll",
    "&::-webkit-scrollbar": {
      height: "6px",
    },
    "&::-webkit-scrollbar-thumb": {
      backgroundColor: tokens.colorNeutralStroke1,
      borderRadius: "3px",
    },
    "&::-webkit-scrollbar-track": {
      backgroundColor: "transparent",
    },
  },
  table: {
    width: "100%",
    tableLayout: "auto",
    borderCollapse: "separate",
    borderSpacing: 0,
    "& th": {
      whiteSpace: "nowrap",
      verticalAlign: "top",
      position: "relative",
    },
    "& th:first-child": {
      position: "sticky",
      left: 0,
      zIndex: 3,
      backgroundColor: tokens.colorNeutralBackground1,
    },
    "& td": {
      overflowWrap: "anywhere",
      wordBreak: "break-word",
      verticalAlign: "top",
      position: "relative",
    },
    "& td:first-child": {
      position: "sticky",
      left: 0,
      zIndex: 2,
      backgroundColor: tokens.colorNeutralBackground1,
    },
    "& td > *, & th > *": {
      minWidth: 0,
    },
  },
  stickyShadow: {
    "& th:first-child, & td:first-child": {
      boxShadow: "4px 0 12px -6px rgba(0,0,0,0.18)",
      clipPath: "inset(0 -16px 0 0)",
    },
  },
});

/**
 * A Fluent Table wrapped in a horizontal-scroll container with cell-level word
 * breaking, so content never leaks out of rows/columns. Pass the table's
 * header/body as children exactly as you would to `<Table>`.
 */
export function DataTable({
  children,
  ariaLabel,
  minWidth,
}: {
  children: ReactNode;
  ariaLabel: string;
  minWidth?: number;
}) {
  const styles = useTableStyles();
  const scrollRef = useRef<HTMLDivElement>(null);
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const check = () => setScrolled(el.scrollLeft > 0);
    check();
    el.addEventListener("scroll", check, { passive: true });
    return () => el.removeEventListener("scroll", check);
  }, []);

  return (
    <div ref={scrollRef} className={styles.scroll}>
      <Table
        aria-label={ariaLabel}
        size="small"
        className={mergeClasses(styles.table, scrolled && styles.stickyShadow)}
        style={minWidth ? { minWidth } : undefined}
      >
        {children}
      </Table>
    </div>
  );
}

// --- pagination ------------------------------------------------------------ //

/**
 * Pager with prev/next, an item-range + page-count readout, and a "jump to
 * page" input. ``offset``/``limit`` are item-based; pages are derived.
 */
export function Pager({
  total,
  offset,
  limit,
  onChange,
}: {
  total: number;
  offset: number;
  limit: number;
  onChange: (offset: number) => void;
}) {
  const { t } = useTranslation();
  const pages = Math.max(1, Math.ceil(total / limit));
  const current = Math.floor(offset / limit) + 1;
  const [draft, setDraft] = useState("");

  const goPage = useCallback(
    (page: number) => {
      const clamped = Math.min(Math.max(1, page), pages);
      onChange((clamped - 1) * limit);
    },
    [pages, limit, onChange],
  );

  function submitJump() {
    const n = Number(draft.trim());
    if (!Number.isNaN(n) && n >= 1) goPage(n);
    setDraft("");
  }

  return (
    <div
      style={{
        display: "flex",
        gap: 10,
        alignItems: "center",
        marginTop: 12,
        flexWrap: "wrap",
      }}
    >
      <Button
        size="small"
        appearance="subtle"
        icon={<ChevronLeftRegular />}
        disabled={offset === 0}
        onClick={() => onChange(Math.max(0, offset - limit))}
        aria-label={t("common.previous")}
      />
      <Button
        size="small"
        appearance="subtle"
        icon={<ChevronRightRegular />}
        disabled={offset + limit >= total}
        onClick={() => onChange(offset + limit)}
        aria-label={t("common.next")}
      />
      <Text size={200} style={{ color: tokens.colorNeutralForeground3 }}>
        {total === 0
          ? t("common.pagerEmpty")
          : t("common.pagerRange")
              .replace("{from}", String(offset + 1))
              .replace("{to}", String(Math.min(offset + limit, total)))
              .replace("{total}", String(total))}
      </Text>
      <span style={{ flex: 1 }} />
      <Text size={200} style={{ color: tokens.colorNeutralForeground3 }}>
        {t("common.pageOf")
          .replace("{current}", String(current))
          .replace("{pages}", String(pages))}
      </Text>
      <Input
        size="small"
        type="number"
        value={draft}
        placeholder={String(current)}
        style={{ width: 84 }}
        onChange={(_, d) => setDraft(d.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") submitJump();
        }}
        aria-label={t("common.goToPage")}
      />
      <Button size="small" onClick={submitJump} disabled={!draft.trim()}>
        {t("common.go")}
      </Button>
    </div>
  );
}

export function formatDate(value?: string | null): string {
  if (!value) return "—";
  // Backend timestamps are UTC, but (on SQLite) may be serialized as a *naive*
  // ISO string with no timezone suffix. `new Date()` would then read them as
  // local time, showing the UTC wall-clock instead of the viewer's timezone.
  // Treat any tz-less value as UTC so `toLocaleString()` renders it in the
  // browser's local timezone; values that already carry a `Z`/±HH:MM offset are
  // left untouched.
  const trimmed = value.trim();
  const hasTz = /(?:[zZ]|[+-]\d{2}:?\d{2})$/.test(trimmed);
  const d = new Date(hasTz ? trimmed : `${trimmed}Z`);
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleString();
}
