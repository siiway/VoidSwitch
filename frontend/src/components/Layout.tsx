import {
  Avatar,
  Badge,
  Button,
  Menu,
  MenuItemRadio,
  MenuList,
  MenuPopover,
  MenuTrigger,
  Text,
  Tooltip,
  makeStyles,
  mergeClasses,
  shorthands,
  tokens,
} from "@fluentui/react-components";
import {
  BoardRegular,
  BookRegular,
  ChartMultipleRegular,
  ChatRegular,
  CloudRegular,
  CubeRegular,
  DesktopRegular,
  DocumentBulletListRegular,
  KeyRegular,
  KeyMultipleRegular,
  NavigationRegular,
  OpenRegular,
  PeopleRegular,
  PeopleTeamRegular,
  PlugConnectedRegular,
  SettingsRegular,
  ShieldTaskRegular,
  SignOutRegular,
  WeatherMoonRegular,
  WeatherSunnyRegular,
  ChevronLeftRegular,
  ChevronRightRegular,
} from "@fluentui/react-icons";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { api } from "../api/client";
import { useShortcuts } from "../lib/useShortcuts";
import { useAuth } from "../auth/AuthContext";
import { useTheme } from "../theme/ThemeContext";
import { LANGUAGES } from "../i18n";
import type { Translations } from "../i18n/locales/en";
import { AnnouncementsPopup } from "./Announcements";
import { ConfirmProvider, ToastProvider } from "./ui";
import type { ReactElement } from "react";

// Ordered visibility gate for nav items:
//   member < role_group_admin < staff < owner
// An item scoped to a level is visible to *anyone at that level or above*.
// See CONTEXT.md § "Platform roles".
type NavScope = "member" | "role_group_admin" | "staff" | "owner";

type TranslationKey = keyof Translations;

const DOCS_URL = "https://voidswitch.siiway.page/";

interface NavItem {
  to: string;
  label: string;
  labelKey: string;
  icon: ReactElement;
  scope: NavScope;
  external?: boolean;
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
        scope: "member",
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
        scope: "staff",
      },
      { to: "/models", label: "Models", labelKey: "nav.models", icon: <CubeRegular />, scope: "member" },
      { to: "/nodes", label: "Nodes", labelKey: "nav.nodes", icon: <CloudRegular />, scope: "staff" },
      { to: "/tokens", label: "Tokens", labelKey: "nav.tokens", icon: <KeyRegular />, scope: "owner" },
      {
        to: "/api-keys",
        label: "Platform API Keys",
        labelKey: "nav.platformApiKeys",
        icon: <KeyMultipleRegular />,
        scope: "staff",
      },
    ],
  },
  {
    heading: "Operations",
    headingKey: "nav.operations",
    items: [
      { to: "/users", label: "Users", labelKey: "nav.users", icon: <PeopleRegular />, scope: "role_group_admin" },
      {
        to: "/role-groups",
        label: "Role Groups",
        labelKey: "nav.roleGroups",
        icon: <PeopleTeamRegular />,
        scope: "staff",
      },
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
        to: "/audit",
        label: "Audit",
        labelKey: "nav.audit",
        icon: <ShieldTaskRegular />,
        scope: "role_group_admin",
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

function docsUrlForLang(base: string, lang: string): string {
  return lang === "en" ? `${base}en/` : base;
}

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
    ...shorthands.padding("16px", "16px"),
  },
  brandText: {
    minWidth: 0,
  },
  // The tagline doubles as the version affordance: hovering lifts the line a
  // little so the version tooltip has a visible anchor, keeping the header
  // quiet until someone actually looks for the build.
  tagline: {
    display: "inline-block",
    color: tokens.colorNeutralForeground3,
    transitionProperty: "transform",
    transitionDuration: tokens.durationNormal,
    transitionTimingFunction: tokens.curveEasyEase,
  },
  taglineRaised: {
    transform: "translateY(-2px)",
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
    ...shorthands.padding("4px", "10px", "10px"),
  },
  section: {
    marginTop: "12px",
    ":first-child": {
      marginTop: 0,
    },
    borderTopWidth: "1px",
    borderTopStyle: "solid",
    borderTopColor: tokens.colorNeutralStroke2,
    paddingTop: "10px",
    ":first-of-type": {
      borderTopWidth: 0,
      paddingTop: 0,
    },
  },
  heading: {
    display: "block",
    ...shorthands.padding("4px", "8px"),
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
    height: "36px",
    ...shorthands.padding("0", "10px"),
    marginTop: "1px",
    borderRadius: "6px",
    color: tokens.colorNeutralForeground2,
    textDecoration: "none",
    fontSize: tokens.fontSizeBase300,
    cursor: "pointer",
    transition: "background-color 120ms, color 120ms",
    ":hover": {
      backgroundColor: tokens.colorNeutralBackground1Hover,
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
      left: "-10px",
      top: "6px",
      bottom: "6px",
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
    ...shorthands.padding("10px"),
    borderTopWidth: "2px",
    borderTopStyle: "solid",
    borderTopColor: tokens.colorNeutralStroke1,
    display: "flex",
    flexDirection: "column",
    rowGap: "8px",
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
    width: "100%",
    boxSizing: "border-box",
    ...shorthands.padding("20px", "24px"),
    "@media (max-width: 768px)": {
      ...shorthands.padding("52px", "12px", "12px"),
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
    backgroundColor: tokens.colorNeutralBackground1,
    borderRightWidth: "2px",
    borderRightStyle: "solid",
    borderRightColor: tokens.colorNeutralStroke1,
    "@media (max-width: 768px)": {
      position: "fixed",
      top: 0,
      left: 0,
      bottom: 0,
      zIndex: 100,
      transform: "translateX(-100%)",
      transitionProperty: "transform",
      transitionDuration: tokens.durationNormal,
    },
  },
  sidebarOpen: {
    "@media (max-width: 768px)": {
      transform: "translateX(0)",
    },
  },
  // Desktop collapse: a narrow icon rail. `sidebarPeek` temporarily widens it
  // when the pointer touches the left edge, floating above the main content so
  // nothing reflows while the peek is showing.
  sidebarCollapsed: {
    width: "64px",
    ...shorthands.padding("0"),
    transitionProperty: "width",
    transitionDuration: tokens.durationNormal,
  },
  sidebarPeek: {
    width: "256px",
    position: "fixed",
    top: 0,
    bottom: 0,
    left: 0,
    zIndex: 100,
    boxShadow: tokens.shadow16,
  },
  // Holds the rail's 64px of flow space while the peek is out of flow, so the
  // main column does not jump left and right as the pointer crosses the edge.
  railSpacer: {
    width: "64px",
    flexShrink: 0,
  },
  brandCollapsed: {
    justifyContent: "center",
    columnGap: 0,
    ...shorthands.padding("16px", "8px"),
  },
  itemCollapsed: {
    justifyContent: "center",
    columnGap: 0,
    ...shorthands.padding("0"),
  },
  sectionCollapsed: {
    borderTopColor: tokens.colorNeutralStroke2,
  },
  headingHidden: {
    display: "none",
  },
  footerCollapsed: {
    ...shorthands.padding("10px", "6px"),
    alignItems: "stretch",
  },
  footerActionsCollapsed: {
    flexDirection: "column",
    alignItems: "center",
    rowGap: "6px",
  },
  userRowCollapsed: {
    justifyContent: "center",
    ...shorthands.padding("4px", "0"),
  },
});

const COLLAPSE_KEY = "voidswitch.nav.collapsed";

export function Layout() {
  const styles = useStyles();
  const { user, isStaff, isOwner, isRoleGroupAdmin, logout } = useAuth();
  const { mode, scheme, setMode } = useTheme();
  const { t, i18n } = useTranslation();
  const location = useLocation();
  useShortcuts();

  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [isNarrow, setIsNarrow] = useState(
    () => window.matchMedia("(max-width: 768px)").matches,
  );
  // Desktop rail state, persisted so the choice survives a reload. The peek is
  // transient: it only exists while the pointer sits at the left edge.
  const [collapsed, setCollapsed] = useState(() => {
    try {
      return localStorage.getItem(COLLAPSE_KEY) === "1";
    } catch {
      return false;
    }
  });
  const [peeking, setPeeking] = useState(false);
  const [proxySwitching, setProxySwitching] = useState(true);
  // Build string shown when the sidebar header is hovered. It comes from the
  // same public config call the shell already makes, so no extra request.
  const [build, setBuild] = useState("");
  const [brandHover, setBrandHover] = useState(false);

  useEffect(() => {
    api
      .get<{
        proxy_switching_enabled?: boolean;
        version?: string;
        commit?: string | null;
      }>("/api/auth/config")
      .then((c) => {
        setProxySwitching(c.proxy_switching_enabled !== false);
        if (c.version) {
          setBuild(`v${c.version}${c.commit ? ` (${c.commit})` : ""}`);
        }
      })
      .catch(() => {});
  }, [location.pathname]);

  useEffect(() => {
    const mq = window.matchMedia("(max-width: 768px)");
    const handler = (e: MediaQueryListEvent) => {
      setIsNarrow(e.matches);
      if (!e.matches) setSidebarOpen(false);
    };
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, []);

  useEffect(() => {
    try {
      localStorage.setItem(COLLAPSE_KEY, collapsed ? "1" : "0");
    } catch {
      /* ignore */
    }
  }, [collapsed]);

  // Edge peek: while the rail is collapsed, hovering the rail itself slides the
  // full sidebar out as an overlay (the pointer is already on it, so no hunting
  // for a 6px strip). Leaving the sidebar folds it back. Desktop only — the
  // narrow layout uses its own drawer.
  useEffect(() => {
    if (isNarrow || !collapsed) setPeeking(false);
  }, [isNarrow, collapsed]);

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

  // Visibility ladder: member < role_group_admin < staff < owner. An item at
  // scope X is shown to anyone at that level or above.
  const canSee = (scope: NavScope) =>
    scope === "member" ||
    (scope === "role_group_admin" && (isRoleGroupAdmin || isStaff || isOwner)) ||
    (scope === "staff" && isStaff) ||
    (scope === "owner" && isOwner);
  const sections = useMemo(
    () =>
      SECTIONS.map((s) => ({
        ...s,
        heading: t(s.headingKey as TranslationKey),
        items: s.items
          .filter((i) => canSee(i.scope))
          .filter((i) => proxySwitching || i.to !== "/proxies")
          .map((i) => ({ ...i, label: t(i.labelKey as TranslationKey) })),
      })).filter((s) => s.items.length > 0),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [t, isStaff, isOwner, isRoleGroupAdmin, proxySwitching],
  );

  const roleColor =
    user?.role === "owner"
      ? "brand"
      : user?.role === "co-owner"
        ? "brand"
        : user?.role === "admin"
          ? "informative"
          : "subtle";

  // The rail only exists on desktop; the narrow layout keeps its drawer.
  const rail = collapsed && !isNarrow && !peeking;

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

          {/* The peek is out of flow, so hold the rail's width here; without
              this the main column would jump as the pointer crosses the edge. */}
          {!isNarrow && collapsed && peeking ? (
            <div className={styles.railSpacer} />
          ) : null}

          <aside
            className={mergeClasses(
              styles.sidebar,
              sidebarOpen && styles.sidebarOpen,
              !isNarrow && collapsed && styles.sidebarCollapsed,
              !isNarrow && collapsed && peeking && styles.sidebarPeek,
            )}
            onMouseEnter={() => {
              if (!isNarrow && collapsed) setPeeking(true);
            }}
            onMouseLeave={() => setPeeking(false)}
          >
            <div
              className={mergeClasses(
                styles.brand,
                rail && styles.brandCollapsed,
              )}
            >
              <span className={styles.brandMark}>⚡</span>
              <div
                className={styles.brandText}
                style={{ display: rail ? "none" : "block" }}
              >
                <Text size={400} weight="bold" block>
                  {t("nav.brand" as TranslationKey)}
                </Text>
                <Tooltip
                  content={
                    build
                      ? `${t("nav.brand" as TranslationKey)} ${build}`
                      : t("nav.tagline" as TranslationKey)
                  }
                  relationship="description"
                  withArrow
                >
                  <Text
                    as="span"
                    size={100}
                    className={mergeClasses(
                      styles.tagline,
                      brandHover && styles.taglineRaised,
                    )}
                    onMouseEnter={() => setBrandHover(true)}
                    onMouseLeave={() => setBrandHover(false)}
                  >
                    {t("nav.tagline" as TranslationKey)}
                  </Text>
                </Tooltip>
              </div>
            </div>

            <nav className={styles.nav}>
              {sections.map((section) => (
                <div key={section.heading} className={styles.section}>
                  <Text
                    as="span"
                    className={mergeClasses(
                      styles.heading,
                      rail && styles.headingHidden,
                    )}
                  >
                    {section.heading}
                  </Text>
                  {section.items.map((item) => {
                    const active =
                      location.pathname === item.to ||
                      location.pathname.startsWith(item.to + "/");
                    const link = (
                      <NavLink
                        key={item.to}
                        to={item.to}
                        className={mergeClasses(
                          styles.item,
                          active ? styles.itemActive : undefined,
                          rail && styles.itemCollapsed,
                        )}
                        onClick={handleNavClick}
                      >
                        <span className={styles.itemIcon}>{item.icon}</span>
                        {rail ? null : item.label}
                      </NavLink>
                    );
                    return rail ? (
                      <Tooltip key={item.to} content={item.label} relationship="label" withArrow>
                        {link}
                      </Tooltip>
                    ) : (
                      link
                    );
                  })}
                </div>
              ))}
            </nav>

            <div className={mergeClasses(styles.footer, rail && styles.footerCollapsed)}>
              <a
                href={docsUrlForLang(DOCS_URL, i18n.language)}
                target="_blank"
                rel="noopener noreferrer"
                className={mergeClasses(styles.item, rail && styles.itemCollapsed)}
                aria-label={t("nav.docs" as TranslationKey)}
              >
                <span className={styles.itemIcon}>
                  <BookRegular />
                </span>
                {rail ? null : (
                  <>
                    <span style={{ flex: 1 }}>{t("nav.docs" as TranslationKey)}</span>
                    <OpenRegular fontSize={16} />
                  </>
                )}
              </a>
              <div
                className={mergeClasses(
                  styles.userRow,
                  rail && styles.userRowCollapsed,
                )}
              >
                <Avatar
                  name={user?.name || user?.username || "User"}
                  image={user?.picture ? { src: user.picture } : undefined}
                  size={32}
                />
                <div className={styles.userMeta} style={{ display: rail ? "none" : "flex" }}>
                  {user?.name ? (
                    <Tooltip content={user.name} relationship="label">
                      <Text
                        size={200}
                        weight="semibold"
                        truncate
                        wrap={false}
                        block
                      >
                        {user?.username || user?.sub || user?.email || user?.name
                          ? `${user.username || user.sub || user.email || user.name}#${user.id}`
                          : "User"}
                      </Text>
                    </Tooltip>
                  ) : (
                    <Text
                      size={200}
                      weight="semibold"
                      truncate
                      wrap={false}
                      block
                    >
                      {user?.username || user?.sub || user?.email || user?.name
                        ? `${user.username || user.sub || user.email || user.name}#${user.id}`
                        : "User"}
                    </Text>
                  )}
                  <Badge appearance="tint" color={roleColor} size="small">
                    {user?.role}
                  </Badge>
                </div>
              </div>
              <div
                className={mergeClasses(
                  styles.footerActions,
                  rail && styles.footerActionsCollapsed,
                )}
              >
                {!rail ? (
                  <Tooltip
                    content={
                      collapsed
                        ? t("nav.expandSidebar" as TranslationKey)
                        : t("nav.collapseSidebar" as TranslationKey)
                    }
                    relationship="label"
                  >
                    <Button
                      appearance="subtle"
                      icon={
                        collapsed ? (
                          <ChevronRightRegular />
                        ) : (
                          <ChevronLeftRegular />
                        )
                      }
                      onClick={() => setCollapsed((c) => !c)}
                      aria-label={
                        collapsed
                          ? t("nav.expandSidebar" as TranslationKey)
                          : t("nav.collapseSidebar" as TranslationKey)
                      }
                    />
                  </Tooltip>
                ) : null}
                <Menu
                  checkedValues={{ theme: [mode] }}
                  onCheckedValueChange={(_, data) => {
                    const next = data.checkedItems[0];
                    if (
                      next === "system" ||
                      next === "light" ||
                      next === "dark"
                    )
                      setMode(next);
                  }}
                >
                  <MenuTrigger disableButtonEnhancement>
                    <Tooltip
                      content={t("theme.label" as TranslationKey)}
                      relationship="label"
                    >
                      <Button
                        appearance="subtle"
                        aria-label={t("theme.label" as TranslationKey)}
                        icon={
                          mode === "system" ? (
                            <DesktopRegular />
                          ) : scheme === "dark" ? (
                            <WeatherMoonRegular />
                          ) : (
                            <WeatherSunnyRegular />
                          )
                        }
                        style={{ flex: rail ? "0 0 auto" : 1 }}
                      />
                    </Tooltip>
                  </MenuTrigger>
                  <MenuPopover>
                    <MenuList>
                      <MenuItemRadio
                        name="theme"
                        value="system"
                        icon={<DesktopRegular />}
                      >
                        {t("theme.system" as TranslationKey)}
                      </MenuItemRadio>
                      <MenuItemRadio
                        name="theme"
                        value="light"
                        icon={<WeatherSunnyRegular />}
                      >
                        {t("theme.light" as TranslationKey)}
                      </MenuItemRadio>
                      <MenuItemRadio
                        name="theme"
                        value="dark"
                        icon={<WeatherMoonRegular />}
                      >
                        {t("theme.dark" as TranslationKey)}
                      </MenuItemRadio>
                    </MenuList>
                  </MenuPopover>
                </Menu>
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
                <Tooltip
                  content={t("nav.signOut" as TranslationKey)}
                  relationship="label"
                >
                  <Button
                    appearance="subtle"
                    icon={<SignOutRegular />}
                    onClick={logout}
                    style={{ flex: rail ? "0 0 auto" : 1 }}
                    aria-label={t("nav.signOut" as TranslationKey)}
                  >
                    {rail ? null : t("nav.signOut" as TranslationKey)}
                  </Button>
                </Tooltip>
                {rail ? (
                  <Tooltip
                    content={t("nav.expandSidebar" as TranslationKey)}
                    relationship="label"
                  >
                    <Button
                      appearance="subtle"
                      icon={<ChevronRightRegular />}
                      onClick={() => setCollapsed(false)}
                      aria-label={t("nav.expandSidebar" as TranslationKey)}
                    />
                  </Tooltip>
                ) : null}
              </div>
            </div>
          </aside>

          <main className={styles.main}>
            <Outlet />
          </main>
        </div>
        <AnnouncementsPopup />
      </ConfirmProvider>
    </ToastProvider>
  );
}
