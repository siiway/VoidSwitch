import {
  Badge,
  Button,
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  Spinner,
  Table,
  Text,
  Toast,
  ToastBody,
  ToastTitle,
  Toaster,
  makeStyles,
  mergeClasses,
  tokens,
  useId,
  useToastController,
} from "@fluentui/react-components";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";

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
            <DialogTitle>{opts?.title ?? "Are you sure?"}</DialogTitle>
            <DialogContent>{opts?.message}</DialogContent>
            <DialogActions>
              <Button appearance="secondary" onClick={() => settle(false)}>
                {opts?.cancelLabel ?? "Cancel"}
              </Button>
              <Button
                appearance="primary"
                style={
                  opts?.tone === "danger"
                    ? {
                        backgroundColor: "var(--colorPaletteRedBackground3)",
                        borderColor: "var(--colorPaletteRedBackground3)",
                      }
                    : undefined
                }
                onClick={() => settle(true)}
              >
                {opts?.confirmLabel ?? "Confirm"}
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

export function PageHeader({
  title,
  subtitle,
  action,
}: {
  title: string;
  subtitle?: string;
  action?: ReactNode;
}) {
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
        <Text size={600} weight="semibold" as="h1" block>
          {title}
        </Text>
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
  return (
    <div style={{ display: "grid", placeItems: "center", padding: 48 }}>
      <Spinner label={label ?? "Loading…"} />
    </div>
  );
}

export function ErrorText({ error }: { error: string }) {
  return (
    <Text style={{ color: "var(--colorPaletteRedForeground1)" }} block>
      {error}
    </Text>
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

export function formatDate(value?: string | null): string {
  if (!value) return "—";
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleString();
}
