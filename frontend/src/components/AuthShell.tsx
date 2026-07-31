import {
  Text,
  makeStyles,
  tokens,
} from "@fluentui/react-components";
import { useTranslation } from "react-i18next";
import type { CSSProperties, ReactNode } from "react";
import type { Translations } from "../i18n/locales/en";

type TK = keyof Translations;

const useStyles = makeStyles({
  page: {
    position: "relative",
    minHeight: "100vh",
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    justifyContent: "center",
    gap: "20px",
    padding: "32px 16px",
    backgroundColor: tokens.colorNeutralBackground1,
    overflow: "hidden",
  },
  brand: {
    position: "relative",
    display: "flex",
    alignItems: "center",
    gap: "10px",
    zIndex: 1,
  },
  brandMark: {
    display: "grid",
    placeItems: "center",
    width: "36px",
    height: "36px",
    borderRadius: tokens.borderRadiusMedium,
    fontSize: "20px",
    color: tokens.colorNeutralForegroundOnBrand,
    background: `linear-gradient(135deg, ${tokens.colorBrandBackground}, ${tokens.colorBrandBackground2})`,
  },
  card: {
    position: "relative",
    zIndex: 1,
    width: "100%",
    display: "flex",
    flexDirection: "column",
    boxSizing: "border-box",
    borderRadius: "14px",
    border: `2px solid ${tokens.colorNeutralStroke1}`,
    backgroundColor: tokens.colorNeutralBackground1,
    "--auth-card-pad": "40px",
    padding: "var(--auth-card-pad)",
    animationName: {
      from: { opacity: 0, transform: "translateY(10px)" },
      to: { opacity: 1, transform: "translateY(0)" },
    },
    animationDuration: "0.35s",
    animationTimingFunction: "cubic-bezier(0.33, 1, 0.68, 1)",
    "@media (prefers-reduced-motion: reduce)": {
      animationName: "none",
    },
    "@media (max-width: 480px)": {
      "--auth-card-pad": "28px",
    },
  },
});

export function AuthShell({
  children,
  maxWidth = 400,
  cardGap = 20,
  hideBrand = false,
}: {
  children: ReactNode;
  maxWidth?: number;
  cardGap?: number;
  hideBrand?: boolean;
}) {
  const styles = useStyles();
  const { t } = useTranslation();
  const cardStyle: CSSProperties = { maxWidth, gap: cardGap };

  return (
    <div className={`${styles.page} auth-grid`}>
      {hideBrand ? null : (
        <div className={styles.brand}>
          <span className={styles.brandMark}>⚡</span>
          <Text size={500} weight="bold">
            {t("nav.brand" as TK)}
          </Text>
        </div>
      )}
      <div className={styles.card} style={cardStyle}>
        {children}
      </div>
    </div>
  );
}
