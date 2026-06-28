// AuthShell — the single owner of the centered-card layout shared by every
// auth-style page (login, callback/error cards, and any future first-run/2FA
// screens). Putting the page background, the calm brand-bloom canvas, the card
// chrome, and the entrance animation here guarantees those flows stay pixel
// identical instead of each page re-deriving its own card styles.
//
// Why a CSS var for padding? Full-bleed children (edge-to-edge dividers) need to
// cancel the card padding with `margin: 0 calc(-1 * var(--auth-card-pad))`. The
// padding shrinks on small screens, so exposing it as a var keeps those children
// correct across the responsive breakpoint without duplicating the value.
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
    backgroundColor: tokens.colorNeutralBackground2,
    overflow: "hidden",
  },
  // Two soft brand blooms from opposite corners. Built from the brand token via
  // color-mix so they track the configured accent and read in both schemes.
  canvas: {
    position: "absolute",
    inset: 0,
    pointerEvents: "none",
    backgroundImage: `radial-gradient(60% 60% at 0% 0%, color-mix(in srgb, ${tokens.colorBrandBackground} 8%, transparent), transparent 70%),
      radial-gradient(60% 60% at 100% 100%, color-mix(in srgb, ${tokens.colorBrandBackground} 8%, transparent), transparent 70%)`,
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
    borderRadius: "12px",
    border: `1px solid ${tokens.colorNeutralStroke3}`,
    backgroundColor: tokens.colorNeutralBackground1,
    boxShadow: tokens.shadow16,
    // Exposed so full-bleed children can stretch edge-to-edge across the
    // responsive padding change below.
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
  // Dynamic, instance-specific values stay inline (griffel can't enumerate them).
  const cardStyle: CSSProperties = { maxWidth, gap: cardGap };

  return (
    <div className={styles.page}>
      <div className={styles.canvas} aria-hidden="true" />
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
