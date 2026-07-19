// Small client-side (per-browser) preferences, persisted in localStorage.
import { useEffect, useState } from "react";

// How the Statistics "Over time" section reacts to the page-wide time filter:
//   A — trailing overview, independent of the window (default);
//   B — a single series at an auto-picked granularity for the window;
//   C — the daily/weekly/monthly/yearly tabs, clipped to the window.
export type OverTimeMode = "A" | "B" | "C";

const OVER_TIME_MODE_KEY = "vs.stats.overTimeMode";
const PREFS_EVENT = "vs-prefs-changed";

export function getOverTimeMode(): OverTimeMode {
  const v = localStorage.getItem(OVER_TIME_MODE_KEY);
  return v === "B" || v === "C" ? v : "A";
}

export function setOverTimeMode(mode: OverTimeMode): void {
  localStorage.setItem(OVER_TIME_MODE_KEY, mode);
  // Notify listeners in the same tab (the native "storage" event only fires in
  // *other* tabs).
  window.dispatchEvent(new Event(PREFS_EVENT));
}

/** Reactive access to the over-time mode preference. */
export function useOverTimeMode(): [OverTimeMode, (mode: OverTimeMode) => void] {
  const [mode, setMode] = useState<OverTimeMode>(getOverTimeMode);
  useEffect(() => {
    const sync = () => setMode(getOverTimeMode());
    window.addEventListener(PREFS_EVENT, sync);
    window.addEventListener("storage", sync);
    return () => {
      window.removeEventListener(PREFS_EVENT, sync);
      window.removeEventListener("storage", sync);
    };
  }, []);
  const set = (next: OverTimeMode) => {
    setOverTimeMode(next);
    setMode(next);
  };
  return [mode, set];
}
