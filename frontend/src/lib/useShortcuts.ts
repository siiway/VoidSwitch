import { useEffect } from "react";

export type ShortcutAction = "save" | "apply" | "refresh";

const EDITABLE_SELECTOR =
  'input, textarea, select, [contenteditable="true"], [contenteditable=""]';

function isEditable(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return target.isContentEditable || target.matches(EDITABLE_SELECTOR);
}

function isClickable(el: HTMLElement): boolean {
  if (el.matches(":disabled")) return false;
  const rect = el.getBoundingClientRect();
  return rect.width > 0 && rect.height > 0;
}

function clickIfSingle(action: ShortcutAction): void {
  const matches = Array.from(
    document.querySelectorAll<HTMLElement>(`[data-shortcut="${action}"]`),
  ).filter(isClickable);
  if (matches.length === 1) matches[0].click();
}

/**
 * Global keyboard shortcuts:
 *  - Ctrl/Cmd+S  -> click the single visible `[data-shortcut="save"]` button
 *  - Ctrl/Cmd+Enter -> click the single visible `[data-shortcut="apply"]` button
 *  - R           -> click the single visible `[data-shortcut="refresh"]` button
 *
 * Buttons opt in by adding the matching `data-shortcut` attribute. Shortcuts
 * are ignored while the user is typing in an input/textarea/select or a
 * contenteditable element.
 */
export function useShortcuts(): void {
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (isEditable(e.target)) return;

      const mod = e.ctrlKey || e.metaKey;
      const key = e.key.toLowerCase();

      if (mod && key === "s") {
        e.preventDefault();
        clickIfSingle("save");
      } else if (mod && key === "enter") {
        e.preventDefault();
        clickIfSingle("apply");
      } else if (!mod && !e.shiftKey && !e.altKey && key === "r") {
        clickIfSingle("refresh");
      }
    };

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);
}

/** Append a shortcut label to a tooltip string, on its own line. */
export function shortcutHint(text: string, shortcut: string): string {
  return `${text}\n${shortcut}`;
}