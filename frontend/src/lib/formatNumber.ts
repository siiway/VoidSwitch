import { useTranslation } from "react-i18next";

/**
 * Locale-aware integer grouping.
 *
 * - Chinese (`zh`): groups by 4 digits — `1,2345,6789` (the traditional CJK
 *   myriad grouping).
 * - Everything else (`en`, fallback): groups by 3 — `123,456,789`.
 *
 * Non-finite / nullish values render as `0` so callers always get a placeholder.
 */
export function formatGrouped(n: number | null | undefined, lang: string): string {
  const value = n == null || !Number.isFinite(n) ? 0 : Math.trunc(n);
  const negative = value < 0;
  const digits = Math.abs(value).toString();

  const groupSize = lang.startsWith("zh") ? 4 : 3;
  const parts: string[] = [];
  let end = digits.length;
  while (end > 0) {
    const start = Math.max(0, end - groupSize);
    parts.unshift(digits.slice(start, end));
    end = start;
  }
  return (negative ? "-" : "") + parts.join(",");
}

/** Hook form: binds grouping to the current i18n language. */
export function useFormatNumber(): (n: number | null | undefined) => string {
  const { i18n } = useTranslation();
  const lang = i18n.language || "en";
  return (n) => formatGrouped(n, lang);
}
