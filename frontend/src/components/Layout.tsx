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
  PeopleRegular,
  PlugConnectedRegular,
  SettingsRegular,
  SignOutRegular,
  WeatherMoonRegular,
  WeatherSunnyRegular,
} from "@fluentui/react-icons";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { useTheme } from "../theme/ThemeContext";
import { ConfirmProvider, ToastProvider } from "./ui";
import type { ReactElement } from "react";

// "member" = visible to everyone, "staff" = owner/co-owner/admin, "owner" =
// owner/co-owner only.
type NavScope = "member" | "staff" | "owner";

interface NavItem {
  to: string;
  label: string;
  icon: ReactElement;
  scope: NavScope;
}

interface NavSection {
  heading: string;
  items: NavItem[];
}

const SECTIONS: NavSection[] = [
  {
    heading: "Overview",
    items: [
      {
        to: "/dashboard",
        label: "Dashboard",
        icon: <BoardRegular />,
        scope: "staff",
      },
    ],
  },
  {
    heading: "Routing",
    items: [
      {
        to: "/providers",
        label: "Providers",
        icon: <PlugConnectedRegular />,
        scope: "member",
      },
      { to: "/models", label: "Models", icon: <CubeRegular />, scope: "member" },
      { to: "/proxies", label: "Proxies", icon: <CloudRegular />, scope: "staff" },
      { to: "/tokens", label: "Tokens", icon: <KeyRegular />, scope: "owner" },
    ],
  },
  {
    heading: "Operations",
    items: [
      { to: "/users", label: "Users", icon: <PeopleRegular />, scope: "staff" },
      {
        to: "/stats",
        label: "Statistics",
        icon: <ChartMultipleRegular />,
        scope: "member",
      },
      {
        to: "/logs",
        label: "Logs",
        icon: <DocumentBulletListRegular />,
        scope: "member",
      },
      {
        to: "/settings",
        label: "Settings",
        icon: <SettingsRegular />,
        scope: "staff",
      },
    ],
  },
  {
    heading: "Account",
    items: [
      { to: "/chat", label: "Chat", icon: <ChatRegular />, scope: "member" },
      { to: "/token", label: "My API Key", icon: <KeyRegular />, scope: "member" },
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
  sidebar: {
    width: "256px",
    flexShrink: 0,
    display: "flex",
    flexDirection: "column",
    backgroundColor: tokens.colorNeutralBackground2,
    ...shorthands.borderRight("1px", "solid", tokens.colorNeutralStroke2),
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
  },
});

export function Layout() {
  const styles = useStyles();
  const { user, isStaff, isOwner, logout } = useAuth();
  const { mode, toggle } = useTheme();
  const location = useLocation();

  const canSee = (scope: NavScope) =>
    scope === "member" || (scope === "staff" && isStaff) || (scope === "owner" && isOwner);
  const sections = SECTIONS.map((s) => ({
    ...s,
    items: s.items.filter((i) => canSee(i.scope)),
  })).filter((s) => s.items.length > 0);

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
          <aside className={styles.sidebar}>
            <div className={styles.brand}>
              <span className={styles.brandMark}>⚡</span>
              <div>
                <Text size={400} weight="bold" block>
                  VoidSwitch
                </Text>
                <Text
                  size={100}
                  style={{ color: tokens.colorNeutralForeground3 }}
                >
                  LLM API gateway
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
                    {user?.name || user?.username || "User"}
                  </Text>
                  <Badge appearance="tint" color={roleColor} size="small">
                    {user?.role}
                  </Badge>
                </div>
              </div>
              <div className={styles.footerActions}>
                <Tooltip
                  content={mode === "dark" ? "Light mode" : "Dark mode"}
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
                <Button
                  appearance="subtle"
                  icon={<SignOutRegular />}
                  onClick={logout}
                  style={{ flex: 1 }}
                >
                  Sign out
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
