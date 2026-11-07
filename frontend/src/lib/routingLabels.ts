import type { useTranslation } from "react-i18next";
import type { Translations } from "../i18n/locales/en";

type TK = keyof Translations;
type T = ReturnType<typeof useTranslation>["t"];

const SELECT_MODE_KEYS: Record<string, TK> = {
  best: "models.selectModeBest" as TK,
  balanced: "models.selectModeBalanced" as TK,
  pinned_best: "models.selectModePinnedBest" as TK,
  pinned_balanced: "models.selectModePinnedBalanced" as TK,
};
const RANK_KEYS: Record<string, TK> = {
  weighted: "models.rankWeighted" as TK,
  tiered: "models.rankTiered" as TK,
};
const COOLED_KEYS: Record<string, TK> = {
  fail_fast: "models.cooledBehaviorFailFast" as TK,
  ignore_cooldown: "models.cooledBehaviorIgnoreCooldown" as TK,
};

/**
 * Localised label for a routing enum value. `settingKey` selects which enum
 * namespace applies (upstream_select_mode / upstream_rank_algorithm /
 * upstream_all_cooled_behavior). Unknown values fall back to the raw string.
 */
export function routingEnumLabel(settingKey: string, value: string, t: T): string {
  let map: Record<string, TK> | undefined;
  if (settingKey === "upstream_select_mode") map = SELECT_MODE_KEYS;
  else if (settingKey === "upstream_rank_algorithm") map = RANK_KEYS;
  else if (settingKey === "upstream_all_cooled_behavior") map = COOLED_KEYS;
  const key = map?.[value];
  return key ? t(key) : value;
}
