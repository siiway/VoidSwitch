import {
  Badge,
  Button,
  Dropdown,
  Option,
  TableBody,
  TableCell,
  TableHeader,
  TableHeaderCell,
  TableRow,
  Tooltip,
  tokens,
} from "@fluentui/react-components";
import {
  CheckmarkCircleRegular,
  SignOutRegular,
  ProhibitedRegular,
} from "@fluentui/react-icons";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { OWNER_ROLES } from "../auth/constants";
import type { Role, User } from "../api/types";
import type { Translations } from "../i18n/locales/en";
import {
  DataTable,
  ErrorText,
  Loading,
  PageHeader,
  formatDate,
  useAsync,
  useNotify,
} from "../components/ui";

const ASSIGNABLE_ROLES: Role[] = ["admin", "member"];
// Owner tier reused from the shared role constants (see src/auth/constants.ts).
const OWNER_TIER = OWNER_ROLES;
const ROLE_RANK: Record<Role, number> = { member: 1, admin: 2, "co-owner": 3, owner: 3 };

export function Users() {
  const { t } = useTranslation();
  type TK = keyof Translations;
  const notify = useNotify();
  const { user: me, isOwner } = useAuth();
  const users = useAsync<User[]>(() => api.get("/api/admin/users"));

  async function setRole(u: User, role: Role) {
    try {
      await api.patch(`/api/admin/users/${u.id}`, { role });
      notify(t("users.roleUpdated" as TK), `${u.username ?? u.sub}#${u.id} → ${role}`, "success");
      users.reload();
    } catch (e) {
      notify(
        t("common.updateFailed" as TK),
        e instanceof Error ? e.message : String(e),
        "error",
      );
    }
  }

  async function toggle(u: User) {
    try {
      await api.patch(`/api/admin/users/${u.id}`, { enabled: !u.enabled });
      users.reload();
    } catch (e) {
      notify(
        t("common.updateFailed" as TK),
        e instanceof Error ? e.message : String(e),
        "error",
      );
    }
  }

  async function forceLogout(u: User) {
    try {
      await api.post(`/api/admin/users/${u.id}/force-logout`);
      users.reload();
      notify(t("users.forceLogoutDone" as TK), `${u.username ?? u.sub}#${u.id}`, "success");
    } catch (e) {
      notify(
        t("common.updateFailed" as TK),
        e instanceof Error ? e.message : String(e),
        "error",
      );
    }
  }

  return (
    <div>
      <PageHeader
        title={t("users.title" as TK)}
        subtitle={t("users.subtitle" as TK)}
        onRefresh={users.reload}
      />
      {users.loading ? (
        <Loading />
      ) : users.error ? (
        <ErrorText error={users.error} />
      ) : (
        <DataTable ariaLabel={t("users.title" as TK)}>
          <TableHeader>
            <TableRow>
              <TableHeaderCell>{t("users.user" as TK)}</TableHeaderCell>
              <TableHeaderCell>{t("users.email" as TK)}</TableHeaderCell>
              <TableHeaderCell>{t("users.role" as TK)}</TableHeaderCell>
              <TableHeaderCell>{t("users.prismRole" as TK)}</TableHeaderCell>
              <TableHeaderCell>{t("users.status" as TK)}</TableHeaderCell>
              <TableHeaderCell>{t("users.lastLogin" as TK)}</TableHeaderCell>
              <TableHeaderCell>{t("users.actions" as TK)}</TableHeaderCell>
            </TableRow>
          </TableHeader>
          <TableBody>
            {(users.data ?? []).map((u) => (
              <TableRow key={u.id}>
                <TableCell>{(u.name || u.username || u.sub)}#{u.id}</TableCell>
                <TableCell style={{ color: tokens.colorNeutralForeground3 }}>
                  {u.email ?? "—"}
                </TableCell>
                <TableCell>
                  {isOwner && !OWNER_TIER.has(u.role) && u.id !== me?.id ? (
                    <Dropdown
                      value={u.role}
                      selectedOptions={[u.role]}
                      onOptionSelect={(_, d) =>
                        d.optionValue && setRole(u, d.optionValue as Role)
                      }
                      style={{ minWidth: 120 }}
                    >
                      {ASSIGNABLE_ROLES.map((r) => (
                        <Option key={r} value={r}>
                          {r}
                        </Option>
                      ))}
                    </Dropdown>
                  ) : (
                    <Badge
                      appearance="tint"
                      color={OWNER_TIER.has(u.role) ? "brand" : undefined}
                    >
                      {u.role}
                    </Badge>
                  )}
                </TableCell>
                <TableCell style={{ color: tokens.colorNeutralForeground3 }}>
                  {u.prism_role ?? "—"}
                  {u.role === "admin" && u.prism_role !== "admin" ? (
                    <Badge
                      appearance="outline"
                      size="small"
                      style={{ marginLeft: 6 }}
                    >
                      {t("common.localOverride" as TK)}
                    </Badge>
                  ) : null}
                </TableCell>
                <TableCell>
                  <Badge
                    color={u.enabled ? "success" : "danger"}
                    appearance="filled"
                  >
                    {u.enabled ? t("common.active" as TK) : t("common.disabled" as TK)}
                  </Badge>
                </TableCell>
                <TableCell style={{ color: tokens.colorNeutralForeground3 }}>
                  {formatDate(u.last_login_at)}
                </TableCell>
                <TableCell>
                  <Tooltip content={t("users.forceLogout" as TK)} relationship="label">
                    <Button
                      size="small"
                      appearance="subtle"
                      icon={<SignOutRegular />}
                      disabled={
                        u.id === me?.id ||
                        !me ||
                        ROLE_RANK[me.role] <= ROLE_RANK[u.role]
                      }
                      onClick={() => forceLogout(u)}
                      aria-label={t("users.forceLogout" as TK)}
                    />
                  </Tooltip>
                  <Tooltip
                    content={
                      u.enabled
                        ? t("common.disable" as TK)
                        : t("common.enable" as TK)
                    }
                    relationship="label"
                  >
                    <Button
                      size="small"
                      appearance="subtle"
                      icon={
                        u.enabled ? <ProhibitedRegular /> : <CheckmarkCircleRegular />
                      }
                      disabled={
                        u.id === me?.id ||
                        !isOwner ||
                        // Same-tier peers (owner/co-owner) can't disable each other.
                        (u.enabled && OWNER_TIER.has(u.role))
                      }
                      onClick={() => toggle(u)}
                      aria-label={
                        u.enabled
                          ? t("common.disable" as TK)
                          : t("common.enable" as TK)
                      }
                    />
                  </Tooltip>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </DataTable>
      )}
    </div>
  );
}
