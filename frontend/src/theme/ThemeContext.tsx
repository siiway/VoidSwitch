import {
  FluentProvider,
  webDarkTheme,
  webLightTheme,
} from "@fluentui/react-components";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

// Theme model: users pick an explicit scheme OR "system" (follow the OS).
// "system" is represented as the ABSENCE of the storage key, so fresh visitors
// and users who reset back to "system" share one state — and the FOUC script in
// index.html can mirror this exact logic to avoid a theme flash on first paint.
type Mode = "system" | "light" | "dark";
type Scheme = "light" | "dark";

const STORAGE_KEY = "voidswitch.theme";

function readStoredMode(): Mode {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved === "light" || saved === "dark") return saved;
  } catch {
    // localStorage may be blocked (privacy mode); fall through to "system".
  }
  return "system";
}

function systemScheme(): Scheme {
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";
}

function resolveScheme(mode: Mode): Scheme {
  return mode === "system" ? systemScheme() : mode;
}

interface ThemeState {
  /** The user's chosen mode, including "system". */
  mode: Mode;
  /** The effective light/dark scheme actually applied to the UI. */
  scheme: Scheme;
  setMode: (mode: Mode) => void;
  /** Convenience toggle between explicit light/dark (used by the simple switch). */
  toggle: () => void;
}

const ThemeContext = createContext<ThemeState>({
  mode: "system",
  scheme: "light",
  setMode: () => {},
  toggle: () => {},
});

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [mode, setModeState] = useState<Mode>(readStoredMode);
  const [systemPref, setSystemPref] = useState<Scheme>(systemScheme);

  const setMode = useCallback((next: Mode) => {
    setModeState(next);
    try {
      // "system" is the absence of the key, so a reset and a fresh visit match.
      if (next === "system") localStorage.removeItem(STORAGE_KEY);
      else localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // ignore storage failures — the in-memory choice still applies this session
    }
  }, []);

  const toggle = useCallback(() => {
    setMode(resolveScheme(mode) === "dark" ? "light" : "dark");
  }, [mode, setMode]);

  // Track OS changes so "system" mode updates live (and so an explicit choice
  // still resolves correctly if the OS flips underneath it).
  useEffect(() => {
    const mq = window.matchMedia?.("(prefers-color-scheme: dark)");
    if (!mq) return;
    const onChange = (e: MediaQueryListEvent) =>
      setSystemPref(e.matches ? "dark" : "light");
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  const scheme: Scheme = mode === "system" ? systemPref : mode;

  // Keep the document in sync with the RESOLVED scheme so areas outside the
  // React tree (global CSS, overscroll, load flash) render the right colors.
  useEffect(() => {
    document.documentElement.style.colorScheme = scheme;
    document.documentElement.setAttribute("data-theme", scheme);
  }, [scheme]);

  const value = useMemo<ThemeState>(
    () => ({ mode, scheme, setMode, toggle }),
    [mode, scheme, setMode, toggle],
  );

  return (
    <ThemeContext.Provider value={value}>
      <FluentProvider
        theme={scheme === "dark" ? webDarkTheme : webLightTheme}
        style={{ height: "100vh" }}
      >
        {children}
      </FluentProvider>
    </ThemeContext.Provider>
  );
}

export function useTheme(): ThemeState {
  return useContext(ThemeContext);
}
