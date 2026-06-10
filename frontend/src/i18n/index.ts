import i18n from "i18next";
import LanguageDetector from "i18next-browser-languagedetector";
import { initReactI18next, useTranslation } from "react-i18next";
import type { Translations } from "./locales/en";
import en from "./locales/en";
import zh from "./locales/zh";

i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources: { en: { translation: en }, zh: { translation: zh } },
    fallbackLng: "en",
    interpolation: { escapeValue: false },
    react: { useSuspense: false },
    detection: {
      order: ["localStorage", "navigator"],
      caches: ["localStorage"],
      lookupLocalStorage: "voidswitch_lang",
    },
  });

export const LANGUAGES = [
  { code: "en", label: "English" },
  { code: "zh", label: "中文" },
] as const;

export type LangCode = (typeof LANGUAGES)[number]["code"];

export function useT() {
  return useTranslation().t as (key: Paths<Translations>) => string;
}

/**
 * Extracts all dot-delimited paths from a nested object type so the `useT`
 * hook offers full autocomplete for every translation key.
 */
type Paths<T, P extends string = ""> = T extends Record<string, unknown>
  ? {
      [K in keyof T & string]: T[K] extends Record<string, unknown>
        ? Paths<T[K], `${P}${K}.`>
        : `${P}${K}`;
    }[keyof T & string]
  : P;

export default i18n;
