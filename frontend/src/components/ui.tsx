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
  },
  table: {
    width: "100%",
    // `auto` lets each column size to its content — a short "status" column
    // stays narrow while a long "base URL" column gets the space it needs —
    // instead of `fixed`'s equal-width columns.
    tableLayout: "auto",
    // Keep long, unbreakable strings (URLs, tokens, JSON, errors) wrapping
    // inside their cell instead of spilling across columns.
    "& td, & th": {
      overflowWrap: "anywhere",
      wordBreak: "break-word",
      verticalAlign: "top",
    },
    "& td > *, & th > *": {
      minWidth: 0,
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
  return (
    <div className={styles.scroll}>
      <Table
        aria-label={ariaLabel}
        size="small"
        className={styles.table}
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
