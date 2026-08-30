import {
  Badge,
  Button,
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  Dropdown,
  Field,
  Input,
  Option,
  SpinButton,
  Text,
  Textarea,
  Tooltip,
  makeStyles,
  shorthands,
  tokens,
} from "@fluentui/react-components";
import {
  AddRegular,
  DeleteRegular,
  EditRegular,
  PeopleListRegular,
  PeopleTeamRegular,
  ShieldRegular,
} from "@fluentui/react-icons";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import type {
  RoleGroup,
  RoleGroupGrants,
  RoleGroupMappingIn,
  RoleGroupMember,
  TeamRole,
} from "../api/types";
import type { Translations } from "../i18n/locales/en";
import {
  ErrorText,
  Loading,
  PageHeader,
  useAsync,
  useConfirm,
  useNotify,
} from "../components/ui";

const TEAM_ROLES: TeamRole[] = ["owner", "co-owner", "admin", "member"];
// Mapping ``grants`` values ordered so "Member" (the historical default) is
// pre-selected in newly-added mapping rows.
const GRANTS: RoleGroupGrants[] = ["member", "admin"];

const useStyles = makeStyles({
  grid: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))",
    gap: "14px",
  },
  card: {
    display: "flex",
    flexDirection: "column",
    gap: "10px",
    ...shorthands.padding("16px"),
    border: `1px solid ${tokens.colorNeutralStroke1}`,
    borderRadius: "10px",
    background: tokens.colorNeutralBackground1,
    transition: "box-shadow 0.15s",
    ":hover": {
      borderTopColor: tokens.colorNeutralForeground1,
      borderRightColor: tokens.colorNeutralForeground1,
      borderBottomColor: tokens.colorNeutralForeground1,
      borderLeftColor: tokens.colorNeutralForeground1,
    },
  },
  head: {
    display: "flex",
    alignItems: "flex-start",
    justifyContent: "space-between",
    gap: "8px",
  },
  title: { display: "flex", alignItems: "center", gap: "8px", minWidth: 0 },
  desc: {
    color: tokens.colorNeutralForeground2,
    minHeight: "18px",
    overflowWrap: "anywhere",
    wordBreak: "break-word",
  },
  badges: { display: "flex", flexWrap: "wrap", gap: "6px", minWidth: 0 },
  mapPill: {
    display: "inline-flex",
    alignItems: "center",
    gap: "4px",
    maxWidth: "100%",
    minWidth: 0,
  },
  mapTeam: {
    maxWidth: "180px",
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  mapRow: {
    display: "flex",
    alignItems: "flex-end",
    gap: "8px",
  },
  mapList: { display: "flex", flexDirection: "column", gap: "8px" },
  actions: { display: "flex", gap: "4px", marginTop: "auto" },
  dim: { color: tokens.colorNeutralForeground3 },
});

interface EditState {
  id: number | null;
  builtin: boolean;
  name: string;
  description: string;
  mappings: RoleGroupMappingIn[];
  call_rate_limit_window_seconds: number;
  call_rate_limit_max_requests: number;
}

export function RoleGroups() {
  const { t } = useTranslation();
  type TK = keyof Translations;
  const styles = useStyles();
  const notify = useNotify();
  const confirm = useConfirm();
  const { isOwner } = useAuth();
  // Write access — creating, editing, deleting, and removing members — is now
  // owner-only. A platform admin (non-owner staff) still sees the list and
  // members but every action button is hidden / disabled.
  const canWrite = isOwner;
  const groups = useAsync<RoleGroup[]>(() => api.get("/api/admin/role-groups"));

  const [edit, setEdit] = useState<EditState | null>(null);
  const [saving, setSaving] = useState(false);

  // Member list / temporary removal (staff-only emergency access revocation).
  const [membersFor, setMembersFor] = useState<RoleGroup | null>(null);
  const [members, setMembers] = useState<RoleGroupMember[] | null>(null);
  const [membersLoading, setMembersLoading] = useState(false);

  async function openMembers(g: RoleGroup) {
    setMembersFor(g);
    setMembers(null);
    setMembersLoading(true);
    try {
      const list = await api.get<RoleGroupMember[]>(
        `/api/admin/role-groups/${g.id}/members`,
      );
      setMembers(list);
    } catch (e) {
      notify(
        t("common.loading" as TK),
        e instanceof Error ? e.message : String(e),
        "error",
      );
      setMembers([]);
    } finally {
      setMembersLoading(false);
    }
  }

  async function removeMember(m: RoleGroupMember) {
    if (!membersFor) return;
    const ok = await confirm({
      title: t("roleGroups.removeMemberTitle" as TK),
      message: t("roleGroups.removeMemberMsg" as TK)
        .replace("{user}", m.name)
        .replace("{group}", membersFor.name),
      confirmLabel: t("roleGroups.removeMember" as TK),
      tone: "danger",
    });
    if (!ok) return;
    try {
      await api.del(
        `/api/admin/role-groups/${membersFor.id}/members/${m.user_id}`,
      );
      notify(t("roleGroups.memberRemoved" as TK), m.name, "success");
      setMembers((prev) =>
        prev ? prev.filter((x) => x.user_id !== m.user_id) : prev,
      );
      groups.reload();
    } catch (e) {
      notify(
        t("common.deleteFailed" as TK),
        e instanceof Error ? e.message : String(e),
        "error",
      );
    }
  }

  function openNew() {
    setEdit({
      id: null,
      builtin: false,
      name: "",
      description: "",
      mappings: [],
      call_rate_limit_window_seconds: 30,
      call_rate_limit_max_requests: 30,
    });
  }

  function openEdit(g: RoleGroup) {
    setEdit({
      id: g.id,
      builtin: g.builtin,
      name: g.name,
      description: g.description ?? "",
      mappings: g.mappings.map((m) => ({
        team_id: m.team_id,
        min_role: m.min_role,
        // Existing rows created before the ``grants`` column keep the
        // historical "member" meaning.
        grants: m.grants ?? "member",
      })),
      call_rate_limit_window_seconds: g.call_rate_limit_window_seconds,
      call_rate_limit_max_requests: g.call_rate_limit_max_requests,
    });
  }

  function addMapping() {
    setEdit((e) =>
      e
        ? {
            ...e,
            mappings: [
              ...e.mappings,
              { team_id: "", min_role: "admin", grants: "member" },
            ],
          }
        : e,
    );
  }

  function updateMapping(idx: number, patch: Partial<RoleGroupMappingIn>) {
    setEdit((e) =>
      e
        ? {
            ...e,
            mappings: e.mappings.map((m, i) => (i === idx ? { ...m, ...patch } : m)),
          }
        : e,
    );
  }

  function removeMapping(idx: number) {
    setEdit((e) =>
      e ? { ...e, mappings: e.mappings.filter((_, i) => i !== idx) } : e,
    );
  }

  async function save() {
    if (!edit) return;
    const rateLimit = {
      call_rate_limit_window_seconds: Math.max(
        0,
        Math.floor(edit.call_rate_limit_window_seconds || 0),
      ),
      call_rate_limit_max_requests: Math.max(
        0,
        Math.floor(edit.call_rate_limit_max_requests || 0),
      ),
    };
    let payload: Record<string, unknown>;
    let savedName: string;
    if (edit.builtin) {
      // The built-in moderator group only accepts its call rate limit.
      payload = rateLimit;
      savedName = edit.name;
    } else {
      const name = edit.name.trim();
      if (!name) {
        notify(t("common.saveFailed" as TK), t("roleGroups.nameRequired" as TK), "error");
        return;
      }
      const mappings = edit.mappings
        .filter((m) => m.team_id.trim())
        .map((m) => ({
          team_id: m.team_id.trim(),
          min_role: m.min_role,
          grants: m.grants ?? "member",
        }));
      payload = {
        name,
        description: edit.description.trim() || null,
        mappings,
        ...rateLimit,
      };
      savedName = name;
    }
    setSaving(true);
    try {
      if (edit.id == null) {
        await api.post("/api/admin/role-groups", payload);
      } else {
        await api.patch(`/api/admin/role-groups/${edit.id}`, payload);
      }
      notify(t("roleGroups.saved" as TK), savedName, "success");
      setEdit(null);
      groups.reload();
    } catch (e) {
      notify(
        t("common.saveFailed" as TK),
        e instanceof Error ? e.message : String(e),
        "error",
      );
    } finally {
      setSaving(false);
    }
  }

  async function remove(g: RoleGroup) {
    const ok = await confirm({
      title: t("roleGroups.deleteTitle" as TK),
      message: t("roleGroups.deleteMsg" as TK).replace("{name}", g.name),
      confirmLabel: t("common.delete" as TK),
      tone: "danger",
    });
    if (!ok) return;
    try {
      await api.del(`/api/admin/role-groups/${g.id}`);
      notify(t("roleGroups.deleted" as TK), g.name, "success");
      groups.reload();
    } catch (e) {
      notify(
        t("common.deleteFailed" as TK),
        e instanceof Error ? e.message : String(e),
        "error",
      );
    }
  }

  const items = groups.data ?? [];

  return (
    <div>
      <PageHeader
        title={t("roleGroups.title" as TK)}
        subtitle={t("roleGroups.subtitle" as TK)}
        onRefresh={groups.reload}
        action={
          canWrite ? (
            <Button appearance="primary" icon={<AddRegular />} onClick={openNew}>
              {t("roleGroups.add" as TK)}
            </Button>
          ) : (
            <Badge appearance="tint" color="informative">
              {t("roleGroups.readOnly" as TK)}
            </Badge>
          )
        }
      />

      {!canWrite && (
        <Text size={200} className={styles.dim} style={{ display: "block", marginBottom: 12 }}>
          {t("roleGroups.readOnlyHint" as TK)}
        </Text>
      )}

      {groups.loading ? (
        <Loading />
      ) : groups.error ? (
        <ErrorText error={groups.error} />
      ) : (
        <div className={styles.grid}>
          {items.map((g) => (
            <div key={g.id} className={styles.card}>
              <div className={styles.head}>
                <div className={styles.title}>
                  {g.builtin ? <ShieldRegular /> : <PeopleTeamRegular />}
                  <Text weight="semibold" truncate wrap={false}>
                    {g.name}
                  </Text>
                </div>
                <Badge appearance="tint" color={g.builtin ? "brand" : "informative"}>
                  {t("roleGroups.members" as TK).replace("{count}", String(g.member_count))}
                </Badge>
              </div>

              <Text size={200} className={styles.desc}>
                {g.description || (
                  <span className={styles.dim}>{t("roleGroups.noDescription" as TK)}</span>
                )}
              </Text>

              <div className={styles.badges}>
                {g.builtin ? (
                  <Badge appearance="outline" color="success">
                    {t("roleGroups.builtin" as TK)}
                  </Badge>
                ) : g.mappings.length === 0 ? (
                  <Text size={200} className={styles.dim}>
                    {t("roleGroups.noMappings" as TK)}
                  </Text>
                ) : (
                  g.mappings.map((m) => (
                    <span key={m.id} className={styles.mapPill}>
                      <Tooltip content={m.team_id} relationship="label">
                        <Badge
                          appearance="outline"
                          color="informative"
                          className={styles.mapTeam}
                        >
                          {m.team_id.length > 8
                            ? m.team_id.slice(0, 4) + "..." + m.team_id.slice(-4)
                            : m.team_id}
                        </Badge>
                      </Tooltip>
                      <Badge appearance="tint" color="brand">
                        {m.min_role}
                      </Badge>
                      {(m.grants ?? "member") === "admin" ? (
                        // Distinct pastel so admin mappings are legible at a
                        // glance in a mapping wall; ``severe`` reads as an
                        // orange in the light theme and a muted amber in dark.
                        <Badge appearance="tint" color="severe">
                          {t("roleGroups.mappingGrantsAdmin" as TK)}
                        </Badge>
                      ) : null}
                    </span>
                  ))
                )}
              </div>

              <Text size={200} className={styles.dim}>
                {g.call_rate_limit_max_requests > 0
                  ? t("roleGroups.callRateSummary" as TK)
                      .replace("{max}", String(g.call_rate_limit_max_requests))
                      .replace("{window}", String(g.call_rate_limit_window_seconds))
                  : t("roleGroups.callRateUnlimited" as TK)}
              </Text>

              {!g.builtin && (
                <div className={styles.actions}>
                  {/* View-members is always available for staff & role-group
                      admins; edit / delete are owner-only. */}
                  <Tooltip
                    content={t("roleGroups.members" as TK).replace(
                      "{count}",
                      String(g.member_count),
                    )}
                    relationship="label"
                  >
                    <Button
                      size="small"
                      appearance="subtle"
                      icon={<PeopleListRegular />}
                      onClick={() => openMembers(g)}
                      aria-label={t("roleGroups.viewMembers" as TK)}
                    />
                  </Tooltip>
                  {canWrite && (
                    <>
                      <Tooltip content={t("common.edit" as TK)} relationship="label">
                        <Button
                          size="small"
                          appearance="subtle"
                          icon={<EditRegular />}
                          onClick={() => openEdit(g)}
                          aria-label={t("common.edit" as TK)}
                        />
                      </Tooltip>
                      <Tooltip content={t("common.delete" as TK)} relationship="label">
                        <Button
                          size="small"
                          appearance="subtle"
                          icon={<DeleteRegular />}
                          onClick={() => remove(g)}
                          aria-label={t("common.delete" as TK)}
                        />
                      </Tooltip>
                    </>
                  )}
                </div>
              )}
              {g.builtin && canWrite && (
                <div className={styles.actions}>
                  <Tooltip content={t("common.edit" as TK)} relationship="label">
                    <Button
                      size="small"
                      appearance="subtle"
                      icon={<EditRegular />}
                      onClick={() => openEdit(g)}
                      aria-label={t("common.edit" as TK)}
                    />
                  </Tooltip>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      <Dialog open={edit !== null} onOpenChange={(_, d) => !d.open && setEdit(null)}>
        <DialogSurface>
          <DialogBody>
            <DialogTitle>
              {edit?.id == null
                ? t("roleGroups.addTitle" as TK)
                : t("roleGroups.editTitle" as TK)}
            </DialogTitle>
            <DialogContent
              style={{ display: "flex", flexDirection: "column", gap: 12, paddingTop: 8 }}
            >
              {/* The built-in group keeps its identity fields; hide (not unmount)
                  them so the dialog's focus trap never re-evaluates. */}
              <div
                style={{
                  display: edit?.builtin ? "none" : "block",
                }}
              >
                <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                  <Field label={t("roleGroups.name" as TK)}>
                    <Input
                      value={edit?.name ?? ""}
                      placeholder={t("roleGroups.namePlaceholder" as TK)}
                      onChange={(_, d) => setEdit((e) => (e ? { ...e, name: d.value } : e))}
                    />
                  </Field>
                  <Field label={t("roleGroups.description" as TK)}>
                    <Textarea
                      value={edit?.description ?? ""}
                      rows={2}
                      onChange={(_, d) =>
                        setEdit((e) => (e ? { ...e, description: d.value } : e))
                      }
                    />
                  </Field>
                  <Field
                    label={t("roleGroups.mappings" as TK)}
                    hint={t("roleGroups.mappingsHint" as TK)}
                  >
                    <div className={styles.mapList}>
                      {/* Fixed top-of-mappings notice explaining the two
                          "grants" flavours. Chose the dialog-top position (Q13
                          option B) over an inline "on switch" hint so the note
                          is visible even when no admin mapping yet exists. */}
                      <Text size={200} className={styles.dim}>
                        {t("roleGroups.mappingGrantsHint" as TK)}
                      </Text>
                      {(edit?.mappings ?? []).map((m, i) => (
                        <div key={i} className={styles.mapRow}>
                          <Input
                            style={{ flex: 1, minWidth: 0 }}
                            value={m.team_id}
                            placeholder={t("roleGroups.teamIdPlaceholder" as TK)}
                            onChange={(_, d) => updateMapping(i, { team_id: d.value })}
                          />
                          <Dropdown
                            value={m.min_role}
                            selectedOptions={[m.min_role]}
                            style={{ minWidth: 110 }}
                            onOptionSelect={(_, d) =>
                              updateMapping(i, { min_role: d.optionValue as TeamRole })
                            }
                          >
                            {TEAM_ROLES.map((r) => (
                              <Option key={r} value={r}>
                                {r}
                              </Option>
                            ))}
                          </Dropdown>
                          <Dropdown
                            value={
                              (m.grants ?? "member") === "admin"
                                ? t("roleGroups.mappingGrantsAdmin" as TK)
                                : t("roleGroups.mappingGrantsMember" as TK)
                            }
                            selectedOptions={[m.grants ?? "member"]}
                            style={{ minWidth: 120 }}
                            onOptionSelect={(_, d) =>
                              updateMapping(i, {
                                grants: (d.optionValue as RoleGroupGrants) ?? "member",
                              })
                            }
                          >
                            {GRANTS.map((g) => (
                              <Option
                                key={g}
                                value={g}
                                text={
                                  g === "admin"
                                    ? t("roleGroups.mappingGrantsAdmin" as TK)
                                    : t("roleGroups.mappingGrantsMember" as TK)
                                }
                              >
                                {g === "admin"
                                  ? t("roleGroups.mappingGrantsAdmin" as TK)
                                  : t("roleGroups.mappingGrantsMember" as TK)}
                              </Option>
                            ))}
                          </Dropdown>
                          <Button
                            appearance="subtle"
                            icon={<DeleteRegular />}
                            onClick={() => removeMapping(i)}
                          />
                        </div>
                      ))}
                      <Button
                        appearance="subtle"
                        icon={<AddRegular />}
                        onClick={addMapping}
                        style={{ alignSelf: "flex-start" }}
                      >
                        {t("roleGroups.addMapping" as TK)}
                      </Button>
                    </div>
                  </Field>
                </div>
              </div>
              {edit?.builtin ? (
                <Text size={200} className={styles.dim}>
                  {t("roleGroups.builtinEditNote" as TK)}
                </Text>
              ) : null}
              <Field
                label={t("roleGroups.callRateLimit" as TK)}
                hint={t("roleGroups.callRateLimitHint" as TK)}
              >
                <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                  <SpinButton
                    value={edit?.call_rate_limit_window_seconds ?? 30}
                    min={0}
                    style={{ width: 96 }}
                    onChange={(_, d) => {
                      const next =
                        d.value ??
                        (d.displayValue ? Number(d.displayValue) : undefined);
                      if (next != null && !Number.isNaN(next))
                        setEdit((e) =>
                          e ? { ...e, call_rate_limit_window_seconds: next } : e,
                        );
                    }}
                  />
                  <Text size={200} className={styles.dim}>
                    {t("roleGroups.rateLimitWithin" as TK)}
                  </Text>
                  <SpinButton
                    value={edit?.call_rate_limit_max_requests ?? 30}
                    min={0}
                    style={{ width: 96 }}
                    onChange={(_, d) => {
                      const next =
                        d.value ??
                        (d.displayValue ? Number(d.displayValue) : undefined);
                      if (next != null && !Number.isNaN(next))
                        setEdit((e) =>
                          e ? { ...e, call_rate_limit_max_requests: next } : e,
                        );
                    }}
                  />
                  <Text size={200} className={styles.dim}>
                    {t("roleGroups.rateLimitRequests" as TK)}
                  </Text>
                </div>
              </Field>
            </DialogContent>
            <DialogActions>
              <Button appearance="secondary" onClick={() => setEdit(null)}>
                {t("common.cancel" as TK)}
              </Button>
              {canWrite && (
                <Button
                  appearance="primary"
                  disabled={saving}
                  onClick={save}
                  data-shortcut="save"
                >
                  {t("common.save" as TK)}
                </Button>
              )}
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>

      <Dialog
        open={membersFor !== null}
        onOpenChange={(_, d) => {
          if (!d.open) {
            setMembersFor(null);
            setMembers(null);
          }
        }}
      >
        <DialogSurface>
          <DialogBody>
            <DialogTitle>
              {t("roleGroups.membersTitle" as TK).replace(
                "{name}",
                membersFor?.name ?? "",
              )}
            </DialogTitle>
            <DialogContent
              style={{ display: "flex", flexDirection: "column", gap: 8, paddingTop: 8 }}
            >
              <Text size={200} className={styles.dim}>
                {t("roleGroups.membersHelp" as TK)}
              </Text>
              {membersLoading ? (
                <Text size={200} className={styles.dim}>
                  {t("common.loading" as TK)}
                </Text>
              ) : !members || members.length === 0 ? (
                <Text size={200} className={styles.dim}>
                  {t("roleGroups.noMembers" as TK)}
                </Text>
              ) : (
                members.map((m) => (
                  <div
                    key={m.user_id}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 8,
                      justifyContent: "space-between",
                    }}
                  >
                    <div style={{ display: "flex", alignItems: "center", gap: 6, minWidth: 0 }}>
                      <Text size={200} truncate wrap={false}>
                        {m.name}
                      </Text>
                      {!m.enabled && (
                        <Badge appearance="tint" color="danger" size="small">
                          {t("common.disabled" as TK)}
                        </Badge>
                      )}
                      <Badge appearance="outline" size="small">
                        {m.source}
                      </Badge>
                      {m.is_admin && (
                        // Same "admin" mapping colour used on the card wall
                        // so the "you are admin here" signal is consistent.
                        <Badge appearance="tint" color="severe" size="small">
                          {t("roleGroups.memberIsAdmin" as TK)}
                        </Badge>
                      )}
                    </div>
                    {canWrite && (
                      <Tooltip
                        content={t("roleGroups.removeMember" as TK)}
                        relationship="label"
                      >
                        <Button
                          size="small"
                          appearance="subtle"
                          icon={<DeleteRegular />}
                          onClick={() => removeMember(m)}
                          aria-label={t("roleGroups.removeMember" as TK)}
                        />
                      </Tooltip>
                    )}
                  </div>
                ))
              )}
            </DialogContent>
            <DialogActions>
              <Button appearance="primary" onClick={() => setMembersFor(null)}>
                {t("common.close" as TK)}
              </Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </div>
  );
}
