import {
  Badge,
  Button,
  Dropdown,
  Input,
  MessageBar,
  MessageBarBody,
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
import { useMemo, useState } from "react";
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

// "All my groups" sentinel for the group filter dropdown. Not a real group id,
// but a stable value the Dropdown can key on.
const ALL_GROUPS = "__all__";

export function Users() {
  const { t } = useTranslation();
  type TK = keyof Translations;
  const notify = useNotify();
  const {
    user: me,
    isOwner,
    isStaff,
    isRoleGroupAdmin,
    managedGroupIds,
    managedGroupNames,
  } = useAuth();
  const users = useAsync<User[]>(() => api.get("/api/admin/users"));
  const [userSearch, setUserSearch] = useState("");
  const [userFilterRole, setUserFilterRole] = useState("");
  const [userFilterStatus, setUserFilterStatus] = useState("");
  // Group filter for the role-group-admin view. Ignored when the caller is
  // staff (they see everyone, no group scoping happens on the frontend). See
  // CONTEXT.md § "Role groups" for the model.
  const [groupFilter, setGroupFilter] = useState<string>(ALL_GROUPS);

  const filteredUsers = useMemo(() => {
    if (!users.data) return [];
    let result = users.data;
    const s = userSearch.trim().toLowerCase();
    if (s) {
      result = result.filter(
        (u) =>
          (u.name ?? "").toLowerCase().includes(s) ||
          (u.username ?? "").toLowerCase().includes(s) ||
          (u.email ?? "").toLowerCase().includes(s) ||
          (u.sub ?? "").toLowerCase().includes(s) ||
          String(u.id).includes(s),
      );
    }
    if (userFilterRole) {
      result = result.filter((u) => u.role === userFilterRole);
    }
    if (userFilterStatus === "enabled") {
      result = result.filter((u) => u.enabled);
    } else if (userFilterStatus === "disabled") {
      result = result.filter((u) => !u.enabled);
    }
    // Client-side "narrow to one of my groups" filter for role-group admins.
    // The backend already scopes to the union of managed groups; the dropdown
    // simply lets an admin zoom into one group at a time.
    if (isRoleGroupAdmin && groupFilter !== ALL_GROUPS) {
      const gid = Number(groupFilter);
      if (!Number.isNaN(gid)) {
        result = result.filter((u) =>
          (u.visible_via_group_ids ?? []).includes(gid),
        );
      }
    }
    return result;
  }, [
    users.data,
    userSearch,
    userFilterRole,
    userFilterStatus,
    isRoleGroupAdmin,
    groupFilter,
  ]);

  const allRoles = useMemo(() => {
    const roles = new Set<string>();
    (users.data ?? []).forEach((u) => roles.add(u.role));
    return [...roles].sort();
  }, [users.data]);

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

  // Role-group-admin specific view knobs: hide the platform role column
  // (they may not see it per spec, "无法查看角色，但能查看团队角色"), hide the
  // enable/disable action (owner-only anyway), keep force-logout with extra
  // disable rules the backend also enforces.
  const showRoleColumn = !isRoleGroupAdmin || isStaff;
  const showEnableAction = isOwner || isStaff;

  return (
    <div>
      <PageHeader
        title={t("users.title" as TK)}
        subtitle={t("users.subtitle" as TK)}
        onRefresh={users.reload}
      />
      {/* Hint bar: only shown to a *pure* role-group admin (isRoleGroupAdmin
          is already gated on !isStaff), so a staff user with adminship on the
          side never sees the "you administer …" bar — their view is the full
          platform view. */}
      {isRoleGroupAdmin && managedGroupNames.length > 0 && (
        <MessageBar intent="info" style={{ marginBottom: 12 }}>
          <MessageBarBody>
            {t("users.roleGroupAdminHint" as TK).replace(
              "{groups}",
              managedGroupNames.join(", "),
            )}
          </MessageBarBody>
        </MessageBar>
      )}
      {users.loading ? (
        <Loading />
      ) : users.error ? (
        <ErrorText error={users.error} />
      ) : (
        <>
          <div
            style={{
              display: "flex",
              gap: 12,
              flexWrap: "wrap",
              alignItems: "center",
              marginBottom: 12,
            }}
          >
            <Input
              placeholder={t("users.userFilterSearch" as TK)}
              style={{ flex: "1 1 240px", minWidth: 200 }}
              value={userSearch}
              onChange={(_, d) => setUserSearch(d.value)}
            />
            {showRoleColumn && (
              <Dropdown
                style={{ minWidth: 130 }}
                placeholder={t("users.userFilterAllRoles" as TK)}
                value={userFilterRole ? userFilterRole : t("users.userFilterAllRoles" as TK)}
                selectedOptions={userFilterRole ? [userFilterRole] : []}
                onOptionSelect={(_, d) => setUserFilterRole(d.optionValue ?? "")}
              >
                {allRoles.map((role) => (
                  <Option key={role} value={role} text={role}>
                    {role}
                  </Option>
                ))}
              </Dropdown>
            )}
            <Dropdown
              style={{ minWidth: 130 }}
              placeholder={t("users.userFilterAllStatus" as TK)}
              value={
                userFilterStatus === "enabled"
                  ? t("users.userFilterEnabled" as TK)
                  : userFilterStatus === "disabled"
                    ? t("users.userFilterDisabled" as TK)
                    : t("users.userFilterAllStatus" as TK)
              }
              selectedOptions={userFilterStatus ? [userFilterStatus] : []}
              onOptionSelect={(_, d) => setUserFilterStatus(d.optionValue ?? "")}
            >
              <Option value="enabled" text={t("users.userFilterEnabled" as TK)}>
                {t("users.userFilterEnabled" as TK)}
              </Option>
              <Option value="disabled" text={t("users.userFilterDisabled" as TK)}>
                {t("users.userFilterDisabled" as TK)}
              </Option>
            </Dropdown>
            {isRoleGroupAdmin && managedGroupIds.length > 1 && (
              // Only surface the "narrow to one group" dropdown when there's
              // more than one group to choose from — a single-group admin's
              // view is already unambiguous.
              <Dropdown
                style={{ minWidth: 160 }}
                value={
                  groupFilter === ALL_GROUPS
                    ? t("users.groupFilterAll" as TK)
                    : managedGroupNames[
                        managedGroupIds.indexOf(Number(groupFilter))
                      ] ?? String(groupFilter)
                }
                selectedOptions={[groupFilter]}
                onOptionSelect={(_, d) => setGroupFilter(d.optionValue ?? ALL_GROUPS)}
              >
                <Option value={ALL_GROUPS} text={t("users.groupFilterAll" as TK)}>
                  {t("users.groupFilterAll" as TK)}
                </Option>
                {managedGroupIds.map((gid, idx) => (
                  <Option key={gid} value={String(gid)} text={managedGroupNames[idx] ?? String(gid)}>
                    {managedGroupNames[idx] ?? String(gid)}
                  </Option>
                ))}
              </Dropdown>
            )}
          </div>
          <DataTable ariaLabel={t("users.title" as TK)}>
          <TableHeader>
            <TableRow>
              <TableHeaderCell>{t("users.user" as TK)}</TableHeaderCell>
              <TableHeaderCell>{t("users.email" as TK)}</TableHeaderCell>
              {showRoleColumn && (
                <TableHeaderCell>{t("users.role" as TK)}</TableHeaderCell>
              )}
              <TableHeaderCell>{t("users.prismRole" as TK)}</TableHeaderCell>
              <TableHeaderCell>{t("users.status" as TK)}</TableHeaderCell>
              <TableHeaderCell>{t("users.lastLogin" as TK)}</TableHeaderCell>
              <TableHeaderCell>{t("users.actions" as TK)}</TableHeaderCell>
            </TableRow>
          </TableHeader>
          <TableBody>
            {filteredUsers.map((u) => (
              <TableRow key={u.id}>
                <TableCell>{(u.name || u.username || u.sub)}#{u.id}</TableCell>
                <TableCell style={{ color: tokens.colorNeutralForeground3 }}>
                  {u.email ?? "—"}
                </TableCell>
                {showRoleColumn && (
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
                )}
                <TableCell style={{ color: tokens.colorNeutralForeground3 }}>
                  {u.prism_role ? (
                    <>
                      {u.prism_role}
                      {u.role === "admin" && u.prism_role !== "admin" ? (
                        <Badge
                          appearance="outline"
                          size="small"
                          style={{ marginLeft: 6 }}
                        >
                          {t("common.localOverride" as TK)}
                        </Badge>
                      ) : null}
                    </>
                  ) : u.role_group_names && u.role_group_names.length > 0 ? (
                    // Not in the main team: show the role group(s) that grant
                    // access. For a role-group-admin viewer the backend has
                    // already filtered ``role_group_names`` to the caller's
                    // managed intersection, so we render them as inline chips
                    // (the "visible via X, Y" hint requested in Q4). Staff
                    // callers see the full list, still rendered as chips for
                    // visual parity.
                    <span
                      style={{ display: "inline-flex", gap: 4, flexWrap: "wrap" }}
                      aria-label={t("users.visibleVia" as TK)}
                    >
                      {u.role_group_names.map((name) => (
                        <Tooltip
                          key={name}
                          content={
                            u.team_ids && u.team_ids.length > 0
                              ? t("users.teamsTooltip" as TK).replace(
                                  "{ids}",
                                  u.team_ids.join(", "),
                                )
                              : t("users.noTeamInfo" as TK)
                          }
                          relationship="label"
                        >
                          <Badge appearance="outline" size="small">
                            {name}
                          </Badge>
                        </Tooltip>
                      ))}
                    </span>
                  ) : (
                    "—"
                  )}
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
                      // Staff must rank strictly above target. Role-group
                      // admin (non-staff) can bounce a member of their group
                      // as long as the target isn't staff / another admin of
                      // a shared group — the backend enforces the "shared
                      // admin" case; the frontend catches the easy ones.
                      disabled={
                        u.id === me?.id ||
                        !me ||
                        (isStaff && ROLE_RANK[me.role] <= ROLE_RANK[u.role]) ||
                        (isRoleGroupAdmin && OWNER_TIER.has(u.role)) ||
                        (isRoleGroupAdmin && u.role === "admin")
                      }
                      onClick={() => forceLogout(u)}
                      aria-label={t("users.forceLogout" as TK)}
                    />
                  </Tooltip>
                  {showEnableAction && (
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
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
          </DataTable>
        </>
      )}
    </div>
  );
}
