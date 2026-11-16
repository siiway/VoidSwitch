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
  MultiSelectFilter,
  PageHeader,
  UserHandle,
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
  const [userFilterRoles, setUserFilterRoles] = useState<Set<string>>(new Set());
  const [userFilterStatus, setUserFilterStatus] = useState("");
  // Group filter for the role-group-admin view. Ignored when the caller is
  // staff (they see everyone, no group scoping happens on the frontend). See
  // CONTEXT.md § "Role groups" for the model.
  const [groupFilters, setGroupFilters] = useState<Set<string>>(new Set());

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
    if (userFilterRoles.size > 0) {
      result = result.filter((u) => userFilterRoles.has(u.role));
    }
    if (userFilterStatus) {
      result = result.filter((u) =>
        userFilterStatus === "enabled" ? u.enabled : !u.enabled,
      );
    }
    // Client-side "narrow to one of my groups" filter for role-group admins.
    // The backend already scopes to the union of managed groups; the dropdown
    // simply lets an admin zoom into one group at a time.
    if (isRoleGroupAdmin && groupFilters.size > 0) {
      const ids = [...groupFilters].map(Number).filter((n) => !Number.isNaN(n));
      result = result.filter((u) =>
        (u.visible_via_group_ids ?? []).some((gid) => ids.includes(gid)),
      );
    }
    return result;
  }, [
    users.data,
    userSearch,
    userFilterRoles,
    userFilterStatus,
    isRoleGroupAdmin,
    groupFilters,
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
              <MultiSelectFilter
                ariaLabel={t("users.userFilterAllRoles" as TK)}
                placeholder={t("users.userFilterAllRoles" as TK)}
                clearLabel={t("common.clearSelection" as TK)}
                options={allRoles.map((role) => ({
                  value: role,
                  label: role,
                }))}
                selected={userFilterRoles}
                onChange={setUserFilterRoles}
                minWidth={130}
              />
            )}
            <Dropdown
              aria-label={t("users.userFilterAllStatus" as TK)}
              style={{ minWidth: 130 }}
              clearable
              placeholder={t("users.userFilterAllStatus" as TK)}
              value={
                userFilterStatus === "enabled"
                  ? t("users.userFilterEnabled" as TK)
                  : userFilterStatus === "disabled"
                    ? t("users.userFilterDisabled" as TK)
                    : t("users.userFilterAllStatus" as TK)
              }
              selectedOptions={userFilterStatus ? [userFilterStatus] : []}
              onOptionSelect={(_, d) =>
                setUserFilterStatus(d.optionValue ?? "")
              }
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
              <MultiSelectFilter
                ariaLabel={t("users.groupFilterAll" as TK)}
                placeholder={t("users.groupFilterAll" as TK)}
                clearLabel={t("common.clearSelection" as TK)}
                options={managedGroupIds.map((gid, idx) => ({
                  value: String(gid),
                  label: managedGroupNames[idx] ?? String(gid),
                }))}
                selected={groupFilters}
                onChange={setGroupFilters}
                minWidth={160}
              />
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
                <TableCell>
                  <UserHandle
                    handle={`${u.username || u.sub || u.name}#${u.id}`}
                    nickname={u.name}
                  />
                </TableCell>
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
