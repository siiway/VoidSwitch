import {
  Avatar,
  Badge,
  Button,
  Text,
  Tooltip,
  makeStyles,
  mergeClasses,
  shorthands,
  tokens,
} from "@fluentui/react-components";
import {
  BoardRegular,
  ChartMultipleRegular,
  ChatRegular,
  CloudRegular,
  CubeRegular,
  DocumentBulletListRegular,
  KeyRegular,
  NavigationRegular,
  PeopleRegular,
  PlugConnectedRegular,
  SettingsRegular,
  SignOutRegular,
  WeatherMoonRegular,
  WeatherSunnyRegular,
} from "@fluentui/react-icons";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { useTheme } from "../theme/ThemeContext";
import { LANGUAGES } from "../i18n";
import type { Translations } from "../i18n/locales/en";
import { ConfirmProvider, ToastProvider } from "./ui";
import type { ReactElement } from "react";

// "member" = visible to everyone, "staff" = owner/co-owner/admin, "owner" =
// owner/co-owner only.
type NavScope = "member" | "staff" | "owner";

type TranslationKey = keyof Translations;

interface NavItem {
  to: string;
  label: string;
  labelKey: string;
  icon: ReactElement;
  scope: NavScope;
}

interface NavSection {
  heading: string;
  headingKey: string;
  items: NavItem[];
}

const SECTIONS: NavSection[] = [
  {
    heading: "Overview",
    headingKey: "nav.overview",
    items: [
      {
        to: "/dashboard",
        label: "Dashboard",
        labelKey: "nav.dashboard",
        icon: <BoardRegular />,
        scope: "staff",
      },
    ],
  },
  {
    heading: "Routing",
    headingKey: "nav.routing",
    items: [
      {
        to: "/providers",
        label: "Providers",
        labelKey: "nav.providers",
        icon: <PlugConnectedRegular />,
        scope: "member",
      },
      { to: "/models", label: "Models", labelKey: "nav.models", icon: <CubeRegular />, scope: "member" },
      { to: "/proxies", label: "Proxies", labelKey: "nav.proxies", icon: <CloudRegular />, scope: "staff" },
      { to: "/tokens", label: "Tokens", labelKey: "nav.tokens", icon: <KeyRegular />, scope: "owner" },
    ],
  },
  {
    heading: "Operations",
    headingKey: "nav.operations",
    items: [
      { to: "/users", label: "Users", labelKey: "nav.users", icon: <PeopleRegular />, scope: "staff" },
      {
        to: "/stats",
        label: "Statistics",
        labelKey: "nav.statistics",
        icon: <ChartMultipleRegular />,
        scope: "member",
      },
      {
        to: "/logs",
        label: "Logs",
        labelKey: "nav.logs",
        icon: <DocumentBulletListRegular />,
        scope: "member",
      },
      {
        to: "/settings",
        label: "Settings",
        labelKey: "nav.settings",
        icon: <SettingsRegular />,
        scope: "staff",
      },
    ],
  },
  {
    heading: "Account",
    headingKey: "nav.account",
    items: [
      { to: "/chat", label: "Chat", labelKey: "nav.chat", icon: <ChatRegular />, scope: "member" },
      { to: "/token", label: "My API Key", labelKey: "nav.myApiKey", icon: <KeyRegular />, scope: "member" },
    ],
  },
];

const useStyles = makeStyles({
  shell: {
    display: "flex",
    height: "100vh",
    overflow: "hidden",
    backgroundColor: tokens.colorNeutralBackground1,
  },
  brand: {
    display: "flex",
    alignItems: "center",
    columnGap: "10px",
    ...shorthands.padding("20px", "20px", "16px"),
  },
  brandMark: {
    display: "grid",
    placeItems: "center",
    width: "32px",
    height: "32px",
    borderRadius: tokens.borderRadiusMedium,
    fontSize: "18px",
    color: tokens.colorNeutralForegroundOnBrand,
    background: `linear-gradient(135deg, ${tokens.colorBrandBackground}, ${tokens.colorBrandBackground2})`,
  },
  nav: {
    flex: 1,
    overflowY: "auto",
    ...shorthands.padding("4px", "12px", "12px"),
  },
  section: {
    marginTop: "14px",
  },
  heading: {
    display: "block",
    ...shorthands.padding("4px", "10px"),
    fontSize: tokens.fontSizeBase100,
    fontWeight: tokens.fontWeightSemibold,
    letterSpacing: "0.06em",
    textTransform: "uppercase",
    color: tokens.colorNeutralForeground4,
  },
  item: {
    position: "relative",
    display: "flex",
    alignItems: "center",
    columnGap: "12px",
    height: "38px",
    ...shorthands.padding("0", "10px"),
    marginTop: "2px",
    borderRadius: tokens.borderRadiusMedium,
    color: tokens.colorNeutralForeground2,
    textDecoration: "none",
    fontSize: tokens.fontSizeBase300,
    cursor: "pointer",
    transitionProperty: "background-color, color",
    transitionDuration: tokens.durationFaster,
    ":hover": {
      backgroundColor: tokens.colorNeutralBackground2Hover,
      color: tokens.colorNeutralForeground1,
    },
  },
  itemActive: {
    backgroundColor: tokens.colorBrandBackground2,
    color: tokens.colorBrandForeground1,
    fontWeight: tokens.fontWeightSemibold,
    ":hover": {
      backgroundColor: tokens.colorBrandBackground2Hover,
      color: tokens.colorBrandForeground1,
    },
    "::before": {
      content: '""',
      position: "absolute",
      left: "-12px",
      top: "8px",
      bottom: "8px",
      width: "3px",
      borderRadius: "0 3px 3px 0",
      backgroundColor: tokens.colorBrandForeground1,
    },
  },
  itemIcon: {
    fontSize: "20px",
    display: "grid",
    placeItems: "center",
  },
  footer: {
    ...shorthands.padding("12px"),
    ...shorthands.borderTop("1px", "solid", tokens.colorNeutralStroke2),
    display: "flex",
    flexDirection: "column",
    rowGap: "10px",
  },
  userRow: {
    display: "flex",
    alignItems: "center",
    columnGap: "10px",
    ...shorthands.padding("4px", "6px"),
    minWidth: 0,
  },
  userMeta: {
    minWidth: 0,
    display: "flex",
    flexDirection: "column",
  },
  footerActions: {
    display: "flex",
    columnGap: "6px",
  },
  main: {
    flex: 1,
    overflowY: "auto",
    ...shorthands.padding("28px", "32px"),
    "@media (max-width: 768px)": {
      ...shorthands.padding("52px", "16px", "16px"),
    },
  },
  backdrop: {
    display: "none",
    "@media (max-width: 768px)": {
      display: "block",
      position: "fixed",
      inset: 0,
      zIndex: 90,
      backgroundColor: "rgba(0,0,0,0.45)",
      opacity: 0,
      pointerEvents: "none",
      transitionProperty: "opacity",
      transitionDuration: tokens.durationNormal,
    },
  },
  backdropVisible: {
    "@media (max-width: 768px)": {
      opacity: 1,
      pointerEvents: "auto",
    },
  },
  hamburger: {
    display: "none",
    "@media (max-width: 768px)": {
      display: "flex",
      position: "fixed",
      top: "12px",
      left: "12px",
      zIndex: 80,
    },
  },
  sidebar: {
    width: "256px",
    flexShrink: 0,
    display: "flex",
    flexDirection: "column",
    backgroundColor: tokens.colorNeutralBackground2,
    ...shorthands.borderRight("1px", "solid", tokens.colorNeutralStroke2),
    "@media (max-width: 768px)": {
      position: "fixed",
      top: 0,
      left: 0,
      bottom: 0,
      zIndex: 100,
      transform: "translateX(-100%)",
      transitionProperty: "transform",
      transitionDuration: tokens.durationNormal,
      boxShadow: tokens.shadow64,
    },
  },
  sidebarOpen: {
    "@media (max-width: 768px)": {
      transform: "translateX(0)",
    },
  },
});

export function Layout() {
  const styles = useStyles();
  const { user, isStaff, isOwner, logout } = useAuth();
  const { mode, toggle } = useTheme();
  const { t, i18n } = useTranslation();
  const location = useLocation();

  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [isNarrow, setIsNarrow] = useState(
    () => window.matchMedia("(max-width: 768px)").matches,
  );

  useEffect(() => {
    const mq = window.matchMedia("(max-width: 768px)");
    const handler = (e: MediaQueryListEvent) => {
      setIsNarrow(e.matches);
      if (!e.matches) setSidebarOpen(false);
    };
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, []);

  const toggleSidebar = useCallback(() => setSidebarOpen((p) => !p), []);
  const closeSidebar = useCallback(() => setSidebarOpen(false), []);

  const handleNavClick = useCallback(() => {
    if (isNarrow) closeSidebar();
  }, [isNarrow, closeSidebar]);

  const cycleLang = useCallback(() => {
    const current = LANGUAGES.findIndex((l) => l.code === i18n.language);
    const next = LANGUAGES[(current + 1) % LANGUAGES.length];
    i18n.changeLanguage(next.code);
  }, [i18n]);

  const canSee = (scope: NavScope) =>
    scope === "member" || (scope === "staff" && isStaff) || (scope === "owner" && isOwner);
  const sections = useMemo(
    () =>
      SECTIONS.map((s) => ({
        ...s,
        heading: t(s.headingKey as TranslationKey),
        items: s.items
          .filter((i) => canSee(i.scope))
          .map((i) => ({ ...i, label: t(i.labelKey as TranslationKey) })),
      })).filter((s) => s.items.length > 0),
    [t, isStaff, isOwner],
  );

  const roleColor =
    user?.role === "owner"
      ? "brand"
      : user?.role === "co-owner"
        ? "brand"
        : user?.role === "admin"
          ? "informative"
          : "subtle";

  return (
    <ToastProvider>
      <ConfirmProvider>
        <div className={styles.shell}>
          <div
            className={mergeClasses(
              styles.backdrop,
              sidebarOpen && styles.backdropVisible,
            )}
            onClick={closeSidebar}
          />

          <Button
            appearance="subtle"
            icon={<NavigationRegular />}
            onClick={toggleSidebar}
            className={styles.hamburger}
            aria-label={
                sidebarOpen
                  ? t("nav.closeSidebar" as TranslationKey)
                  : t("nav.openSidebar" as TranslationKey)
              }
          />

          <aside
            className={mergeClasses(
              styles.sidebar,
              sidebarOpen && styles.sidebarOpen,
            )}
          >
            <div className={styles.brand}>
              <span className={styles.brandMark}>⚡</span>
              <div>
                <Text size={400} weight="bold" block>
                  {t("nav.brand" as TranslationKey)}
                </Text>
                <Text
                  size={100}
                  style={{ color: tokens.colorNeutralForeground3 }}
                >
                  {t("nav.tagline" as TranslationKey)}
                </Text>
              </div>
            </div>

            <nav className={styles.nav}>
              {sections.map((section) => (
                <div key={section.heading} className={styles.section}>
                  <Text as="span" className={styles.heading}>
                    {section.heading}
                  </Text>
                  {section.items.map((item) => {
                    const active =
                      location.pathname === item.to ||
                      location.pathname.startsWith(item.to + "/");
                    return (
                      <NavLink
                        key={item.to}
                        to={item.to}
                        className={mergeClasses(
                          styles.item,
                          active ? styles.itemActive : undefined,
                        )}
                        onClick={handleNavClick}
                      >
                        <span className={styles.itemIcon}>{item.icon}</span>
                        {item.label}
                      </NavLink>
                    );
                  })}
                </div>
              ))}
            </nav>

            <div className={styles.footer}>
              <div className={styles.userRow}>
                <Avatar
                  name={user?.name || user?.username || "User"}
                  image={user?.picture ? { src: user.picture } : undefined}
                  size={32}
                />
                <div className={styles.userMeta}>
                  <Text
                    size={200}
                    weight="semibold"
                    truncate
                    wrap={false}
                    block
                  >
                    {user?.username || user?.name || user?.email
                      ? `${user.username || user.name || user.email}#${user.id}`
                      : "User"}
                  </Text>
                  <Badge appearance="tint" color={roleColor} size="small">
                    {user?.role}
                  </Badge>
                </div>
              </div>
              <div className={styles.footerActions}>
                <Tooltip
                  content={
                    mode === "dark"
                      ? t("nav.lightMode" as TranslationKey)
                      : t("nav.darkMode" as TranslationKey)
                  }
                  relationship="label"
                >
                  <Button
                    appearance="subtle"
                    icon={
                      mode === "dark" ? (
                        <WeatherSunnyRegular />
                      ) : (
                        <WeatherMoonRegular />
                      )
                    }
                    onClick={toggle}
                    style={{ flex: 1 }}
                  />
                </Tooltip>
                <Tooltip
                  content={LANGUAGES.find((l) => l.code !== i18n.language)?.label ?? ""}
                  relationship="label"
                >
                  <Button
                    appearance="subtle"
                    size="small"
                    onClick={cycleLang}
                    style={{ fontWeight: 600, width: 36, minWidth: "unset", padding: 0 }}
                  >
                    {i18n.language === "zh" ? "EN" : "中"}
                  </Button>
                </Tooltip>
                <Button
                  appearance="subtle"
                  icon={<SignOutRegular />}
                  onClick={logout}
                  style={{ flex: 1 }}
                >
                  {t("nav.signOut" as TranslationKey)}
                </Button>
              </div>
            </div>
          </aside>

          <main className={styles.main}>
            <Outlet />
          </main>
        </div>
      </ConfirmProvider>
    </ToastProvider>
  );
}
