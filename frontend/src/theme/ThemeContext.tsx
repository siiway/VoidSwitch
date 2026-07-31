import {
  FluentProvider,
  webDarkTheme,
  webLightTheme,
  type Theme,
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

// ── Black-white theme overrides ────────────────────────────────────────
// Override Fluent's neutral background / stroke / shadow / radius tokens
// to match a high-contrast, border-driven ops aesthetic (Kumo-inspired).

const LIGHT = {
  colorNeutralBackground1: "#ffffff",
  colorNeutralBackground1Hover: "#f5f5f5",
  colorNeutralBackground1Pressed: "#e8e8e8",
  colorNeutralBackground1Selected: "#ebebeb",
  colorNeutralBackground2: "#ffffff",
  colorNeutralBackground2Hover: "#f5f5f5",
  colorNeutralBackground2Pressed: "#e8e8e8",
  colorNeutralBackground2Selected: "#ebebeb",
  colorNeutralBackground3: "#f0f0f0",
  colorNeutralBackground3Hover: "#e5e5e5",
  colorNeutralBackground3Pressed: "#dadada",
  colorNeutralBackground3Selected: "#e0e0e0",
  colorNeutralStroke1: "#000000",
  colorNeutralStroke2: "#d0d0d0",
  colorNeutralStroke3: "#e0e0e0",
  colorNeutralStrokeAccessible: "#000000",
  colorNeutralForeground1: "#000000",
  colorNeutralForeground2: "#333333",
  colorNeutralForeground3: "#666666",
  colorNeutralForeground4: "#999999",
};

const DARK = {
  colorNeutralBackground1: "#000000",
  colorNeutralBackground1Hover: "#1a1a1a",
  colorNeutralBackground1Pressed: "#2a2a2a",
  colorNeutralBackground1Selected: "#222222",
  colorNeutralBackground2: "#000000",
  colorNeutralBackground2Hover: "#1a1a1a",
  colorNeutralBackground2Pressed: "#2a2a2a",
  colorNeutralBackground2Selected: "#222222",
  colorNeutralBackground3: "#141414",
  colorNeutralBackground3Hover: "#1f1f1f",
  colorNeutralBackground3Pressed: "#2a2a2a",
  colorNeutralBackground3Selected: "#1a1a1a",
  colorNeutralStroke1: "#333333",
  colorNeutralStroke2: "#2a2a2a",
  colorNeutralStroke3: "#1f1f1f",
  colorNeutralStrokeAccessible: "#666666",
  colorNeutralForeground1: "#ffffff",
  colorNeutralForeground2: "#cccccc",
  colorNeutralForeground3: "#888888",
  colorNeutralForeground4: "#555555",
};

const SHARED = {
  shadow2: "none",
  shadow4: "none",
  shadow8: "none",
  shadow16: "none",
  shadow28: "none",
  shadow64: "none",
  shadow2Brand: "none",
  shadow4Brand: "none",
  shadow8Brand: "none",
  shadow16Brand: "none",
  shadow28Brand: "none",
  shadow64Brand: "none",
  borderRadiusLarge: "10px",
  borderRadiusXLarge: "12px",
  borderRadius2XLarge: "14px",
};

function patchTheme(theme: Theme, dark: boolean): Theme {
  return { ...theme, ...SHARED, ...(dark ? DARK : LIGHT) } as Theme;
}

interface ThemeState {
  mode: Mode;
  scheme: Scheme;
  setMode: (mode: Mode) => void;
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
      if (next === "system") localStorage.removeItem(STORAGE_KEY);
      else localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // ignore storage failures
    }
  }, []);

  const toggle = useCallback(() => {
    setMode(resolveScheme(mode) === "dark" ? "light" : "dark");
  }, [mode, setMode]);

  useEffect(() => {
    const mq = window.matchMedia?.("(prefers-color-scheme: dark)");
    if (!mq) return;
    const onChange = (e: MediaQueryListEvent) =>
      setSystemPref(e.matches ? "dark" : "light");
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  const scheme: Scheme = mode === "system" ? systemPref : mode;

  useEffect(() => {
    document.documentElement.style.colorScheme = scheme;
    document.documentElement.setAttribute("data-theme", scheme);
  }, [scheme]);

  const theme = useMemo(() => {
    const dark = scheme === "dark";
    const base = dark ? webDarkTheme : webLightTheme;
    return patchTheme(base, dark);
  }, [scheme]);

  const value = useMemo<ThemeState>(
    () => ({ mode, scheme, setMode, toggle }),
    [mode, scheme, setMode, toggle],
  );

  return (
    <ThemeContext.Provider value={value}>
      <FluentProvider theme={theme} style={{ height: "100vh" }}>
        {children}
      </FluentProvider>
    </ThemeContext.Provider>
  );
}

export function useTheme(): ThemeState {
  return useContext(ThemeContext);
}
