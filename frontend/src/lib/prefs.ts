// Small client-side (per-browser) preferences, persisted in localStorage.
import { useEffect, useState } from "react";

// How the Statistics "Over time" section reacts to the page-wide time filter:
//   A — trailing overview, independent of the window (default);
//   B — a single series at an auto-picked granularity for the window;
//   C — the daily/weekly/monthly/yearly tabs, clipped to the window.
export type OverTimeMode = "A" | "B" | "C";

const OVER_TIME_MODE_KEY = "vs.stats.overTimeMode";
const LIVE_LOG_CAP_KEY = "vs.logs.liveLogCap";
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

/** How many rows the live request-log stream keeps before dropping the oldest.
 * A too-large value makes the browser lag rendering the table. */
export const LIVE_LOG_CAP_DEFAULT = 300;

export function getLiveLogCap(): number {
  const raw = localStorage.getItem(LIVE_LOG_CAP_KEY);
  if (raw == null) return LIVE_LOG_CAP_DEFAULT;
  const n = Number(raw);
  return Number.isFinite(n) && n > 0 ? Math.floor(n) : LIVE_LOG_CAP_DEFAULT;
}

export function setLiveLogCap(cap: number): void {
  localStorage.setItem(LIVE_LOG_CAP_KEY, String(cap));
  window.dispatchEvent(new Event(PREFS_EVENT));
}

/** Reactive access to the live-log row cap preference. */
export function useLiveLogCap(): [number, (cap: number) => void] {
  const [cap, setCap] = useState<number>(getLiveLogCap);
  useEffect(() => {
    const sync = () => setCap(getLiveLogCap());
    window.addEventListener(PREFS_EVENT, sync);
    window.addEventListener("storage", sync);
    return () => {
      window.removeEventListener(PREFS_EVENT, sync);
      window.removeEventListener("storage", sync);
    };
  }, []);
  const set = (next: number) => {
    setLiveLogCap(next);
    setCap(next);
  };
  return [cap, set];
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
