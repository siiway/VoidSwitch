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
import type {
  RoleGroup,
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
  name: string;
  description: string;
  mappings: RoleGroupMappingIn[];
}

export function RoleGroups() {
  const { t } = useTranslation();
  type TK = keyof Translations;
  const styles = useStyles();
  const notify = useNotify();
  const confirm = useConfirm();
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
    setEdit({ id: null, name: "", description: "", mappings: [] });
  }

  function openEdit(g: RoleGroup) {
    setEdit({
      id: g.id,
      name: g.name,
      description: g.description ?? "",
      mappings: g.mappings.map((m) => ({ team_id: m.team_id, min_role: m.min_role })),
    });
  }

  function addMapping() {
    setEdit((e) =>
      e ? { ...e, mappings: [...e.mappings, { team_id: "", min_role: "admin" }] } : e,
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
    const name = edit.name.trim();
    if (!name) {
      notify(t("common.saveFailed" as TK), t("roleGroups.nameRequired" as TK), "error");
      return;
    }
    const mappings = edit.mappings
      .filter((m) => m.team_id.trim())
      .map((m) => ({ team_id: m.team_id.trim(), min_role: m.min_role }));
    const payload = { name, description: edit.description.trim() || null, mappings };
    setSaving(true);
    try {
      if (edit.id == null) {
        await api.post("/api/admin/role-groups", payload);
      } else {
        await api.patch(`/api/admin/role-groups/${edit.id}`, payload);
      }
      notify(t("roleGroups.saved" as TK), name, "success");
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
          <Button appearance="primary" icon={<AddRegular />} onClick={openNew}>
            {t("roleGroups.add" as TK)}
          </Button>
        }
      />

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
                    </span>
                  ))
                )}
              </div>

              {!g.builtin && (
                <div className={styles.actions}>
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
                  {(edit?.mappings ?? []).map((m, i) => (
                    <div key={i} className={styles.mapRow}>
                      <Input
                        style={{ flex: 1 }}
                        value={m.team_id}
                        placeholder={t("roleGroups.teamIdPlaceholder" as TK)}
                        onChange={(_, d) => updateMapping(i, { team_id: d.value })}
                      />
                      <Dropdown
                        value={m.min_role}
                        selectedOptions={[m.min_role]}
                        style={{ minWidth: 120 }}
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
            </DialogContent>
            <DialogActions>
              <Button appearance="secondary" onClick={() => setEdit(null)}>
                {t("common.cancel" as TK)}
              </Button>
              <Button appearance="primary" disabled={saving} onClick={save} data-shortcut="save">
                {t("common.save" as TK)}
              </Button>
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
                    </div>
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
