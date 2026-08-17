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
  TableBody,
  TableCell,
  TableHeader,
  TableHeaderCell,
  TableRow,
  Text,
  Textarea,
  Tooltip,
  tokens,
} from "@fluentui/react-components";
import {
  AddRegular,
  CloudOffRegular,
  CloudRegular,
  DeleteRegular,
  EditRegular,
  PeopleTeamRegular,
  PulseRegular,
} from "@fluentui/react-icons";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import type { Translations } from "../i18n/locales/en";
import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import type { Node, NodeGroup, NodeGroupMember, NodeType } from "../api/types";
import {
  DataTable,
  ErrorText,
  Loading,
  PageHeader,
  StatusBadge,
  formatDate,
  useAsync,
  useConfirm,
  useNotify,
} from "../components/ui";
import { EmptyState } from "../components/EmptyState";

type TK = keyof Translations;

const NODE_TYPES: NodeType[] = ["direct", "http", "socks5", "agent"];

// A member row while editing: either a direct node or an inherited group.
interface MemberDraft {
  key: string;
  kind: "node" | "group";
  ref: number | null;
  weight: number;
}

export function Nodes() {
  const { t } = useTranslation();
  const notify = useNotify();
  const confirm = useConfirm();
  const navigate = useNavigate();
  const { isOwner } = useAuth();
  const config = useAsync<{ proxy_switching_enabled?: boolean }>(() =>
    api.get("/api/auth/config"),
  );
  const nodes = useAsync<Node[]>(() => api.get("/api/admin/nodes"));
  const groups = useAsync<NodeGroup[]>(() => api.get("/api/admin/node-groups"));

  // ---- Add nodes ----
  const [bulk, setBulk] = useState("");
  const [nodeType, setNodeType] = useState<NodeType>("http");
  const [localAddr, setLocalAddr] = useState("");
  const [token, setToken] = useState("");
  const [nodeNote, setNodeNote] = useState("");
  const [adding, setAdding] = useState(false);

  // ---- Edit node ----
  const [editing, setEditing] = useState<Node | null>(null);
  const [editNote, setEditNote] = useState("");
  const [savingNode, setSavingNode] = useState(false);

  // ---- Node group create/edit ----
  const [groupForm, setGroupForm] = useState<{
    id?: number;
    name: string;
    description: string;
    probe_url: string;
    probe_interval_seconds: number;
  } | null>(null);
  const [savingGroup, setSavingGroup] = useState(false);

  // ---- Members editor ----
  const [membersFor, setMembersFor] = useState<NodeGroup | null>(null);
  const [membersDraft, setMembersDraft] = useState<MemberDraft[]>([]);
  const [membersSaving, setMembersSaving] = useState(false);

  function reload() {
    nodes.reload();
    groups.reload();
  }

  async function add() {
    const urls = bulk
      .split("\n")
      .map((s) => s.trim())
      .filter(Boolean);
    if (!urls.length) return;
    setAdding(true);
    try {
      const created = await api.post<Node[]>("/api/admin/nodes", {
        urls,
        type: nodeType,
        local_address: localAddr.trim() || null,
        weight: 1,
        note: nodeNote.trim() || null,
        token: token.trim() || null,
      });
      notify(t("nodes.added" as TK), `${created.length} new`, "success");
      setBulk("");
      setLocalAddr("");
      setToken("");
      setNodeNote("");
      nodes.reload();
    } catch (e) {
      notify(
        t("nodes.addFailed" as TK),
        e instanceof Error ? e.message : String(e),
        "error",
      );
    } finally {
      setAdding(false);
    }
  }

  async function toggle(n: Node) {
    try {
      await api.patch(`/api/admin/nodes/${n.id}`, { enabled: !n.enabled });
      notify(t("nodes.toggled" as TK), undefined, "success");
      reload();
    } catch (e) {
      notify(
        t("nodes.toggleFailed" as TK),
        e instanceof Error ? e.message : String(e),
        "error",
      );
    }
  }

  async function probe(n: Node) {
    try {
      await api.post(`/api/admin/nodes/${n.id}/probe`);
      notify(t("nodes.probed" as TK), n.url, "success");
      reload();
    } catch (e) {
      notify(
        t("nodes.probeFailed" as TK),
        e instanceof Error ? e.message : String(e),
        "error",
      );
    }
  }

  function openRename(n: Node) {
    setEditing(n);
    setEditNote(n.note ?? "");
  }

  async function saveNode() {
    if (!editing) return;
    setSavingNode(true);
    try {
      await api.patch(`/api/admin/nodes/${editing.id}`, {
        note: editNote.trim() || null,
      });
      notify(t("nodes.renamed" as TK), editNote.trim() || editing.url, "success");
      setEditing(null);
      reload();
    } catch (e) {
      notify(
        t("common.updateFailed" as TK),
        e instanceof Error ? e.message : String(e),
        "error",
      );
    } finally {
      setSavingNode(false);
    }
  }

  async function removeNode(n: Node) {
    const ok = await confirm({
      title: t("nodes.deleteTitle" as TK),
      message: t("nodes.deleteMsg" as TK).replace("{url}", n.url || "(direct)"),
      confirmLabel: t("common.delete" as TK),
      tone: "danger",
    });
    if (!ok) return;
    try {
      await api.del(`/api/admin/nodes/${n.id}`);
      notify(t("nodes.deleted" as TK), n.url, "success");
      reload();
    } catch (e) {
      notify(
        t("common.deleteFailed" as TK),
        e instanceof Error ? e.message : String(e),
        "error",
      );
    }
  }

  function openGroupCreate() {
    setGroupForm({
      name: "",
      description: "",
      probe_url: "",
      probe_interval_seconds: 0,
    });
  }

  function openGroupEdit(g: NodeGroup) {
    setGroupForm({
      id: g.id,
      name: g.name,
      description: g.description ?? "",
      probe_url: g.probe_url ?? "",
      probe_interval_seconds: g.probe_interval_seconds ?? 0,
    });
  }

  async function saveGroup() {
    if (!groupForm) return;
    setSavingGroup(true);
    try {
      const body = {
        name: groupForm.name.trim(),
        description: groupForm.description.trim() || null,
        probe_url: groupForm.probe_url.trim() || null,
        probe_interval_seconds: Math.max(0, groupForm.probe_interval_seconds),
      };
      if (groupForm.id) {
        await api.patch(`/api/admin/node-groups/${groupForm.id}`, body);
        notify(t("nodes.groupUpdated" as TK), groupForm.name, "success");
      } else {
        await api.post("/api/admin/node-groups", body);
        notify(t("nodes.groupCreated" as TK), groupForm.name, "success");
      }
      setGroupForm(null);
      groups.reload();
    } catch (e) {
      notify(
        t("common.saveFailed" as TK),
        e instanceof Error ? e.message : String(e),
        "error",
      );
    } finally {
      setSavingGroup(false);
    }
  }

  async function removeGroup(g: NodeGroup) {
    const ok = await confirm({
      title: t("nodes.groupDeleteTitle" as TK),
      message: t("nodes.groupDeleteMsg" as TK).replace("{name}", g.name),
      confirmLabel: t("common.delete" as TK),
      tone: "danger",
    });
    if (!ok) return;
    try {
      await api.del(`/api/admin/node-groups/${g.id}`);
      notify(t("nodes.groupDeleted" as TK), g.name, "success");
      groups.reload();
    } catch (e) {
      notify(
        t("common.deleteFailed" as TK),
        e instanceof Error ? e.message : String(e),
        "error",
      );
    }
  }

  function openMembers(g: NodeGroup) {
    const draft = g.members.map((m) => {
      const isNode = m.node_id != null;
      return {
        key: `${Date.now()}-${Math.random()}`,
        kind: isNode ? ("node" as const) : ("group" as const),
        ref: isNode ? (m.node_id as number) : (m.source_group_id as number),
        weight: m.weight,
      };
    });
    setMembersFor(g);
    setMembersDraft(draft);
  }

  function canEditMembers(g: NodeGroup): boolean {
    // The System group's members can only be edited by (co-)owners.
    if (g.is_system) return isOwner;
    return true;
  }

  function memberLabel(m: NodeGroupMember): string {
    if (m.node_id != null) return m.node_url ?? `node #${m.node_id}`;
    return m.source_group_name ?? `group #${m.source_group_id}`;
  }

  function addMemberDraft(kind: "node" | "group") {
    setMembersDraft((d) => [
      ...d,
      { key: `${Date.now()}-${Math.random()}`, kind, ref: null, weight: 1 },
    ]);
  }

  function removeMemberDraft(key: string) {
    setMembersDraft((d) => d.filter((m) => m.key !== key));
  }

  function updateMemberDraft(
    key: string,
    patch: Partial<Pick<MemberDraft, "ref" | "weight">>,
  ) {
    setMembersDraft((d) =>
      d.map((m) => (m.key === key ? { ...m, ...patch } : m)),
    );
  }

  async function saveMembers() {
    if (!membersFor) return;
    const valid = membersDraft.filter((m) => m.ref != null);
    const body = valid.map((m) =>
      m.kind === "node"
        ? { node_id: m.ref as number, weight: m.weight }
        : { source_group_id: m.ref as number, weight: m.weight },
    );
    setMembersSaving(true);
    try {
      await api.put(`/api/admin/node-groups/${membersFor.id}/members`, body);
      notify(t("nodes.membersSaved" as TK), membersFor.name, "success");
      setMembersFor(null);
      groups.reload();
    } catch (e) {
      notify(
        t("common.updateFailed" as TK),
        e instanceof Error ? e.message : String(e),
        "error",
      );
    } finally {
      setMembersSaving(false);
    }
  }

  // Proxy switching disabled → an external proxy handles egress. The nav hides
  // this tab, but a direct URL still lands here; show an explicit notice.
  if (config.data?.proxy_switching_enabled === false) {
    return (
      <div>
        <PageHeader
          title={t("nodes.title" as TK)}
          subtitle={t("nodes.subtitle" as TK)}
        />
        <EmptyState
          icon={<CloudOffRegular />}
          title={t("nodes.disabledTitle" as TK)}
          description={t("nodes.disabledDesc" as TK)}
          action={
            <div style={{ display: "flex", gap: 8, justifyContent: "center" }}>
              {isOwner ? (
                <Button
                  appearance="primary"
                  onClick={() => navigate("/settings")}
                >
                  {t("nodes.goToSettings" as TK)}
                </Button>
              ) : null}
              <Button onClick={() => navigate("/")}>
                {t("nodes.goHome" as TK)}
              </Button>
            </div>
          }
        />
      </div>
    );
  }

  return (
    <div>
      <PageHeader
        title={t("nodes.title" as TK)}
        subtitle={t("nodes.subtitle" as TK)}
        onRefresh={reload}
        action={
          <Button
            appearance="primary"
            icon={<AddRegular />}
            onClick={openGroupCreate}
          >
            {t("nodes.addGroup" as TK)}
          </Button>
        }
      />

      <Text size={500} weight="semibold" block style={{ margin: "8px 0 12px" }}>
        {t("nodes.nodesSection" as TK)}
      </Text>

      <div
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 8,
          marginBottom: 16,
        }}
      >
        <div style={{ display: "flex", gap: 12, alignItems: "flex-end", flexWrap: "wrap" }}>
          <Field label={t("nodes.urlsHint" as TK)} style={{ flex: "1 1 280px" }}>
            <Textarea
              value={bulk}
              rows={3}
              placeholder={"http://user:pass@host:port\nsocks5://host:1080\nagent://…"}
              onChange={(_, d) => setBulk(d.value)}
            />
          </Field>
          <Field label={t("nodes.type" as TK)}>
            <Dropdown
              value={nodeType}
              selectedOptions={[nodeType]}
              onOptionSelect={(_, d) =>
                d.optionValue && setNodeType(d.optionValue as NodeType)
              }
            >
              {NODE_TYPES.map((tp) => (
                <Option key={tp} value={tp} text={tp}>
                  {tp}
                </Option>
              ))}
            </Dropdown>
          </Field>
        </div>
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
          <Field label={t("nodes.localSourceIp" as TK)} style={{ flex: "1 1 220px" }}>
            <Input
              value={localAddr}
              placeholder="e.g. 10.0.0.5"
              onChange={(_, d) => setLocalAddr(d.value)}
            />
          </Field>
          <Field label={t("nodes.token" as TK)} style={{ flex: "1 1 220px" }}>
            <Input
              type="password"
              value={token}
              placeholder={t("nodes.tokenPlaceholder" as TK)}
              onChange={(_, d) => setToken(d.value)}
            />
          </Field>
          <Field label={t("nodes.note" as TK)} style={{ flex: "1 1 220px" }}>
            <Input
              value={nodeNote}
              placeholder={t("nodes.notePlaceholder" as TK)}
              onChange={(_, d) => setNodeNote(d.value)}
            />
          </Field>
        </div>
        <div>
          <Button
            appearance="primary"
            disabled={adding || !bulk.trim()}
            onClick={add}
          >
            {adding ? t("nodes.adding" as TK) : t("nodes.add" as TK)}
          </Button>
        </div>
      </div>

      {nodes.loading ? (
        <Loading />
      ) : nodes.error ? (
        <ErrorText error={nodes.error} />
      ) : (nodes.data ?? []).length === 0 ? (
        <EmptyState
          icon={<CloudRegular />}
          title={t("nodes.emptyTitle" as TK)}
          description={t("nodes.emptyDesc" as TK)}
        />
      ) : (
        <DataTable ariaLabel={t("nodes.nodesSection" as TK)}>
          <TableHeader>
            <TableRow>
              <TableHeaderCell>{t("nodes.url" as TK)}</TableHeaderCell>
              <TableHeaderCell>{t("nodes.type" as TK)}</TableHeaderCell>
              <TableHeaderCell>{t("nodes.sourceIp" as TK)}</TableHeaderCell>
              <TableHeaderCell>{t("nodes.status" as TK)}</TableHeaderCell>
              <TableHeaderCell>{t("nodes.fails" as TK)}</TableHeaderCell>
              <TableHeaderCell>{t("nodes.latency" as TK)}</TableHeaderCell>
              <TableHeaderCell>{t("nodes.checked" as TK)}</TableHeaderCell>
              <TableHeaderCell>{t("nodes.actions" as TK)}</TableHeaderCell>
            </TableRow>
          </TableHeader>
          <TableBody>
            {(nodes.data ?? []).map((n) => (
              <TableRow key={n.id}>
                <TableCell style={{ fontFamily: "monospace" }}>
                  {n.url || "(direct)"}
                </TableCell>
                <TableCell>{n.type}</TableCell>
                <TableCell>{n.local_address ?? "—"}</TableCell>
                <TableCell>
                  <StatusBadge status={n.enabled ? n.status : "disabled"} />
                </TableCell>
                <TableCell>{n.failed_count}</TableCell>
                <TableCell style={{ color: tokens.colorNeutralForeground3 }}>
                  {n.latency_ms != null
                    ? `${Math.round(n.latency_ms)} ms`
                    : "—"}
                </TableCell>
                <TableCell style={{ color: tokens.colorNeutralForeground3 }}>
                  {formatDate(n.last_checked_at)}
                </TableCell>
                <TableCell>
                  <Tooltip content={t("nodes.probe" as TK)} relationship="label">
                    <Button
                      size="small"
                      appearance="subtle"
                      icon={<PulseRegular />}
                      onClick={() => probe(n)}
                      aria-label={t("nodes.probe" as TK)}
                    />
                  </Tooltip>
                  <Tooltip content={t("common.edit" as TK)} relationship="label">
                    <Button
                      size="small"
                      appearance="subtle"
                      icon={<EditRegular />}
                      aria-label={t("common.edit" as TK)}
                      onClick={() => openRename(n)}
                    />
                  </Tooltip>
                  <Tooltip
                    content={
                      n.enabled
                        ? t("common.disable" as TK)
                        : t("common.enable" as TK)
                    }
                    relationship="label"
                  >
                    <Button
                      size="small"
                      appearance="subtle"
                      onClick={() => toggle(n)}
                      aria-label={
                        n.enabled
                          ? t("common.disable" as TK)
                          : t("common.enable" as TK)
                      }
                    >
                      {n.enabled ? t("common.disable" as TK) : t("common.enable" as TK)}
                    </Button>
                  </Tooltip>
                  <Tooltip content={t("common.delete" as TK)} relationship="label">
                    <Button
                      size="small"
                      appearance="subtle"
                      icon={<DeleteRegular />}
                      onClick={() => removeNode(n)}
                      aria-label={t("common.delete" as TK)}
                    />
                  </Tooltip>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </DataTable>
      )}

      <Text size={500} weight="semibold" block style={{ margin: "24px 0 12px" }}>
        {t("nodes.groupsSection" as TK)}
      </Text>

      {groups.loading ? (
        <Loading />
      ) : groups.error ? (
        <ErrorText error={groups.error} />
      ) : (groups.data ?? []).length === 0 ? (
        <EmptyState
          icon={<PeopleTeamRegular />}
          title={t("nodes.groupsEmptyTitle" as TK)}
          description={t("nodes.groupsEmptyDesc" as TK)}
        />
      ) : (
        <DataTable ariaLabel={t("nodes.groupsSection" as TK)}>
          <TableHeader>
            <TableRow>
              <TableHeaderCell>{t("nodes.groupName" as TK)}</TableHeaderCell>
              <TableHeaderCell>{t("nodes.groupProbeUrl" as TK)}</TableHeaderCell>
              <TableHeaderCell>{t("nodes.groupMembers" as TK)}</TableHeaderCell>
              <TableHeaderCell>{t("nodes.actions" as TK)}</TableHeaderCell>
            </TableRow>
          </TableHeader>
          <TableBody>
            {(groups.data ?? []).map((g) => (
              <TableRow key={g.id}>
                <TableCell>
                  {g.name}
                  {g.is_system && (
                    <Badge
                      appearance="filled"
                      color="brand"
                      style={{ marginLeft: 8 }}
                    >
                      {t("nodes.systemBadge" as TK)}
                    </Badge>
                  )}
                  {!g.is_system && g.slug === "default" && (
                    <Badge
                      appearance="tint"
                      color="informative"
                      style={{ marginLeft: 8 }}
                    >
                      default
                    </Badge>
                  )}
                </TableCell>
                <TableCell style={{ color: tokens.colorNeutralForeground3 }}>
                  {g.probe_url || "—"}
                </TableCell>
                <TableCell>{g.member_count}</TableCell>
                <TableCell>
                  <Tooltip content={t("nodes.editMembers" as TK)} relationship="label">
                    <Button
                      size="small"
                      appearance="subtle"
                      icon={<PeopleTeamRegular />}
                      disabled={!canEditMembers(g)}
                      onClick={() => openMembers(g)}
                      aria-label={t("nodes.editMembers" as TK)}
                    />
                  </Tooltip>
                  <Tooltip content={t("common.edit" as TK)} relationship="label">
                    <Button
                      size="small"
                      appearance="subtle"
                      icon={<EditRegular />}
                      onClick={() => openGroupEdit(g)}
                      aria-label={t("common.edit" as TK)}
                    />
                  </Tooltip>
                  {isOwner && !g.is_system && g.slug !== "default" && (
                    <Tooltip content={t("common.delete" as TK)} relationship="label">
                      <Button
                        size="small"
                        appearance="subtle"
                        icon={<DeleteRegular />}
                        onClick={() => removeGroup(g)}
                        aria-label={t("common.delete" as TK)}
                      />
                    </Tooltip>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </DataTable>
      )}

      {/* ---- Add / edit node group ---- */}
      <Dialog
        open={groupForm !== null}
        onOpenChange={(_, d) => !d.open && setGroupForm(null)}
      >
        <DialogSurface>
          <DialogBody>
            <DialogTitle>
              {groupForm?.id
                ? t("nodes.editGroupTitle" as TK)
                : t("nodes.addGroupTitle" as TK)}
            </DialogTitle>
            <DialogContent
              style={{
                display: "flex",
                flexDirection: "column",
                gap: 12,
                paddingTop: 8,
              }}
            >
              <Field label={t("nodes.groupName" as TK)} required>
                <Input
                  value={groupForm?.name ?? ""}
                  onChange={(_, d) =>
                    setGroupForm((f) => (f ? { ...f, name: d.value } : f))
                  }
                />
              </Field>
              <Field label={t("nodes.groupDescription" as TK)}>
                <Textarea
                  value={groupForm?.description ?? ""}
                  rows={2}
                  onChange={(_, d) =>
                    setGroupForm((f) => (f ? { ...f, description: d.value } : f))
                  }
                />
              </Field>
              <Field label={t("nodes.groupProbeUrl" as TK)}>
                <Input
                  value={groupForm?.probe_url ?? ""}
                  placeholder="https://api.openai.com/v1/models"
                  onChange={(_, d) =>
                    setGroupForm((f) => (f ? { ...f, probe_url: d.value } : f))
                  }
                />
              </Field>
              <Field label={t("nodes.groupProbeInterval" as TK)}>
                <SpinButton
                  value={groupForm?.probe_interval_seconds ?? 0}
                  min={0}
                  onChange={(_, d) => {
                    const next =
                      d.value ??
                      (d.displayValue ? Number(d.displayValue) : undefined);
                    if (next != null && !Number.isNaN(next))
                      setGroupForm((f) =>
                        f ? { ...f, probe_interval_seconds: Math.max(0, next) } : f,
                      );
                  }}
                />
              </Field>
            </DialogContent>
            <DialogActions>
              <Button appearance="secondary" onClick={() => setGroupForm(null)}>
                {t("common.cancel" as TK)}
              </Button>
              <Button
                appearance="primary"
                disabled={savingGroup || !groupForm?.name.trim()}
                onClick={saveGroup}
              >
                {groupForm?.id ? t("common.save" as TK) : t("common.create" as TK)}
              </Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>

      {/* ---- Rename / edit node note ---- */}
      <Dialog
        open={editing !== null}
        onOpenChange={(_, d) => !d.open && setEditing(null)}
      >
        <DialogSurface>
          <DialogBody>
            <DialogTitle>{t("nodes.editNameTitle" as TK)}</DialogTitle>
            <DialogContent>
              <div
                style={{
                  color: tokens.colorNeutralForeground3,
                  fontFamily: "monospace",
                  marginBottom: 8,
                }}
              >
                {editing?.url || "(direct)"}
              </div>
              <Field label={t("nodes.nameLabel" as TK)}>
                <Input
                  value={editNote}
                  placeholder={t("nodes.notePlaceholder" as TK)}
                  onChange={(_, d) => setEditNote(d.value)}
                />
              </Field>
            </DialogContent>
            <DialogActions>
              <Button
                appearance="subtle"
                disabled={savingNode}
                onClick={() => setEditing(null)}
              >
                {t("common.cancel" as TK)}
              </Button>
              <Button
                appearance="primary"
                disabled={savingNode}
                onClick={saveNode}
              >
                {t("common.save" as TK)}
              </Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>

      {/* ---- Members editor ---- */}
      <Dialog
        open={membersFor !== null}
        onOpenChange={(_, d) => !d.open && setMembersFor(null)}
      >
        <DialogSurface style={{ maxWidth: 560 }}>
          <DialogBody>
            <DialogTitle>
              {t("nodes.membersTitle" as TK).replace(
                "{name}",
                membersFor?.name ?? "",
              )}
            </DialogTitle>
            <DialogContent
              style={{
                display: "flex",
                flexDirection: "column",
                gap: 10,
                paddingTop: 8,
              }}
            >
              <Text size={200} style={{ color: tokens.colorNeutralForeground3 }}>
                {t("nodes.membersHint" as TK)}
              </Text>
              <div style={{ display: "flex", gap: 8 }}>
                <Button
                  size="small"
                  appearance="secondary"
                  onClick={() => addMemberDraft("node")}
                >
                  {t("nodes.addNode" as TK)}
                </Button>
                <Button
                  size="small"
                  appearance="secondary"
                  onClick={() => addMemberDraft("group")}
                >
                  {t("nodes.inheritGroup" as TK)}
                </Button>
              </div>
              <div
                style={{
                  display: "flex",
                  flexDirection: "column",
                  gap: 8,
                  maxHeight: 320,
                  overflowY: "auto",
                }}
              >
                {membersDraft.length === 0 ? (
                  <Text size={200} style={{ color: tokens.colorNeutralForeground3 }}>
                    {t("nodes.membersEmpty" as TK)}
                  </Text>
                ) : (
                  membersDraft.map((m) => (
                    <div
                      key={m.key}
                      style={{
                        display: "flex",
                        gap: 8,
                        alignItems: "flex-end",
                        border: `1px solid ${tokens.colorNeutralStroke2}`,
                        borderRadius: 6,
                        padding: 8,
                      }}
                    >
                      <Field label={t("nodes.memberSource" as TK)} style={{ flex: 1 }}>
                        {m.kind === "node" ? (
                          <Dropdown
                            placeholder={t("nodes.selectNode" as TK)}
                            value={
                              m.ref != null
                                ? (nodes.data ?? []).find((n) => n.id === m.ref)
                                    ?.url ?? `#${m.ref}`
                                : ""
                            }
                            selectedOptions={m.ref != null ? [String(m.ref)] : []}
                            onOptionSelect={(_, d) =>
                              updateMemberDraft(m.key, {
                                ref: d.optionValue ? Number(d.optionValue) : null,
                              })
                            }
                          >
                            {(nodes.data ?? []).map((n) => (
                              <Option key={n.id} value={String(n.id)} text={n.url}>
                                {n.url || "(direct)"}
                                {n.status !== "active" ? ` (${n.status})` : ""}
                              </Option>
                            ))}
                          </Dropdown>
                        ) : (
                          <Dropdown
                            placeholder={t("nodes.selectGroup" as TK)}
                            value={
                              m.ref != null
                                ? (groups.data ?? []).find((g) => g.id === m.ref)
                                    ?.name ?? `#${m.ref}`
                                : ""
                            }
                            selectedOptions={m.ref != null ? [String(m.ref)] : []}
                            onOptionSelect={(_, d) =>
                              updateMemberDraft(m.key, {
                                ref: d.optionValue ? Number(d.optionValue) : null,
                              })
                            }
                          >
                            {(groups.data ?? [])
                              .filter((g) => g.id !== membersFor?.id)
                              .map((g) => (
                                <Option key={g.id} value={String(g.id)} text={g.name}>
                                  {g.name}
                                </Option>
                              ))}
                          </Dropdown>
                        )}
                      </Field>
                      <Field label={t("nodes.memberWeight" as TK)}>
                        <Input
                          type="number"
                          value={String(m.weight)}
                          style={{ width: 80 }}
                          onChange={(_, d) =>
                            updateMemberDraft(m.key, {
                              weight: Math.max(1, Number(d.value) || 1),
                            })
                          }
                        />
                      </Field>
                      <Button
                        size="small"
                        appearance="subtle"
                        icon={<DeleteRegular />}
                        onClick={() => removeMemberDraft(m.key)}
                        aria-label={t("common.delete" as TK)}
                      />
                    </div>
                  ))
                )}
              </div>
              {membersFor && membersFor.members.length > 0 && (
                <div style={{ color: tokens.colorNeutralForeground3, fontSize: 12 }}>
                  {membersFor.members
                    .map((m) => `${memberLabel(m)} (${m.weight})`)
                    .join(" · ")}
                </div>
              )}
            </DialogContent>
            <DialogActions>
              <Button appearance="secondary" onClick={() => setMembersFor(null)}>
                {t("common.cancel" as TK)}
              </Button>
              <Button
                appearance="primary"
                disabled={membersSaving}
                onClick={saveMembers}
              >
                {membersSaving
                  ? t("nodes.membersSaving" as TK)
                  : t("common.save" as TK)}
              </Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </div>
  );
}
