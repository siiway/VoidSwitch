import {
  Badge,
  Button,
  Combobox,
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
  type OptionOnSelectData,
  type SelectionEvents,
} from "@fluentui/react-components";
import {
  AddRegular,
  ChevronDownRegular,
  ChevronRightRegular,
  CloudOffRegular,
  CloudRegular,
  DeleteRegular,
  EditRegular,
  PinRegular,
  PinOffRegular,
  PulseRegular,
} from "@fluentui/react-icons";
import { Fragment, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import type { Translations } from "../i18n/locales/en";
import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import type { Node, NodeGroup, NodeGroupMember } from "../api/types";
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

function redactUrl(url: string): string {
  if (!url) return "(direct)";
  return url.replace(/\/\/[^\/:@]+:[^@]+@/, "//***:***@");
}

const COLLAPSED_KEY = "voidswitch.nodes.collapsedGroups";

function loadCollapsed(): Set<number> {
  try {
    const raw = localStorage.getItem(COLLAPSED_KEY);
    if (raw == null) return new Set();
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return new Set();
    return new Set(parsed.filter((x): x is number => typeof x === "number"));
  } catch {
    return new Set();
  }
}

function persistCollapsed(set: Set<number>): void {
  try {
    localStorage.setItem(COLLAPSED_KEY, JSON.stringify([...set]));
  } catch {
    /* ignore */
  }
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

  // ---- Inline members editor ----
  const [collapsedIds, setCollapsedIds] = useState<Set<number>>(loadCollapsed);
  const [savingGroupId, setSavingGroupId] = useState<number | null>(null);

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
      });
      notify(t("nodes.added" as TK), `${created.length} new`, "success");
      setBulk("");
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

  // ---- Inline members (immediate-edit) ----

  function setCollapsed(next: Set<number>) {
    setCollapsedIds(next);
    persistCollapsed(next);
  }

  function expandGroup(g: NodeGroup) {
    const next = new Set(collapsedIds);
    next.delete(g.id);
    setCollapsed(next);
  }

  function collapseGroup(g: NodeGroup) {
    const next = new Set(collapsedIds);
    next.add(g.id);
    setCollapsed(next);
  }

  function toggleGroup(g: NodeGroup) {
    if (collapsedIds.has(g.id)) {
      expandGroup(g);
    } else {
      collapseGroup(g);
    }
  }

  function canEditMembers(g: NodeGroup): boolean {
    if (g.is_system) return isOwner;
    return true;
  }

  // The member list is edited directly against the group's live members: every
  // add / remove / pin persists immediately (no draft + save flow).
  function memberBody(m: NodeGroupMember): Record<string, unknown> {
    if (m.node_id != null) {
      return { node_id: m.node_id, pinned: !!m.pinned };
    }
    return { source_group_id: m.source_group_id, pinned: false };
  }

  async function persistMembers(g: NodeGroup, members: NodeGroupMember[]) {
    if (!canEditMembers(g)) return;
    setSavingGroupId(g.id);
    try {
      await api.put(`/api/admin/node-groups/${g.id}/members`, members.map(memberBody));
      notify(t("nodes.membersSaved" as TK), g.name, "success");
      groups.reload();
    } catch (e) {
      notify(
        t("common.updateFailed" as TK),
        e instanceof Error ? e.message : String(e),
        "error",
      );
    } finally {
      setSavingGroupId(null);
    }
  }

  function nodeInfoOf(m: NodeGroupMember): Node | undefined {
    return (nodes.data ?? []).find((n) => n.id === m.node_id);
  }

  function groupInfoOf(m: NodeGroupMember): NodeGroup | undefined {
    return (groups.data ?? []).find((g) => g.id === m.source_group_id);
  }

  function addNodeMembers(g: NodeGroup, refs: number[]) {
    const members = [...g.members];
    const existing = new Set(g.members.map((m) => m.node_id).filter((id) => id != null));
    for (const ref of refs) {
      if (existing.has(ref)) continue;
      members.push({ node_id: ref, pinned: false, weight: 1 });
      existing.add(ref);
    }
    if (members.length !== g.members.length) void persistMembers(g, members);
  }

  function addInheritedGroup(g: NodeGroup, ref: number) {
    const members = [...g.members];
    if (members.some((m) => m.source_group_id === ref)) return;
    members.push({ source_group_id: ref, weight: 1 });
    void persistMembers(g, members);
  }

  function removeMember(g: NodeGroup, m: NodeGroupMember) {
    const members = g.members.filter(
      (x) => !(x.node_id != null && x.node_id === m.node_id) &&
        !(x.source_group_id != null && x.source_group_id === m.source_group_id),
    );
    void persistMembers(g, members);
  }

  function togglePin(g: NodeGroup, m: NodeGroupMember) {
    if (m.node_id == null) return;
    const members = g.members.map((x) =>
      x.node_id === m.node_id ? { ...x, pinned: !x.pinned } : x,
    );
    void persistMembers(g, members);
  }

  // ---- Combobox helpers ----

  function handleAddNodes(
    gId: number,
    _e: SelectionEvents,
    d: OptionOnSelectData,
  ) {
    const group = (groups.data ?? []).find((g) => g.id === gId);
    if (!group) return;
    const refs = d.selectedOptions.map(Number).filter((n) => Number.isFinite(n));
    addNodeMembers(group, refs);
  }

  function handleAddGroup(
    gId: number,
    _e: SelectionEvents,
    d: OptionOnSelectData,
  ) {
    const group = (groups.data ?? []).find((g) => g.id === gId);
    if (!group || !d.optionValue) return;
    addInheritedGroup(group, Number(d.optionValue));
  }

  // Proxy switching disabled
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
        <Field label={t("nodes.urlsHint" as TK)}>
          <Textarea
            value={bulk}
            rows={5}
            placeholder={
              "http://user:pass@host:port\nsocks5://host:port # comment\nhttp+agent://host:port?token-here\ndirect"
            }
            onChange={(_, d) => setBulk(d.value)}
          />
        </Field>
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
              <TableHeaderCell>{t("nodes.note" as TK)}</TableHeaderCell>
              <TableHeaderCell>{t("nodes.url" as TK)}</TableHeaderCell>
              <TableHeaderCell>{t("nodes.type" as TK)}</TableHeaderCell>
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
                <TableCell style={{ maxWidth: 220 }}>
                  <span
                    style={{
                      display: "block",
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                    title={n.note ?? ""}
                  >
                    {n.note || <span style={{ color: tokens.colorNeutralForeground3 }}>—</span>}
                  </span>
                </TableCell>
                <TableCell style={{ fontFamily: "monospace" }}>
                  {n.url || "(direct)"}
                </TableCell>
                <TableCell>{n.type}</TableCell>
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
          icon={<AddRegular />}
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
              <TableHeaderCell>{t("nodes.groupInherits" as TK)}</TableHeaderCell>
              <TableHeaderCell>{t("nodes.actions" as TK)}</TableHeaderCell>
            </TableRow>
          </TableHeader>
          <TableBody>
            {(groups.data ?? []).map((g) => {
              const isExpanded = !collapsedIds.has(g.id);
              const canEdit = canEditMembers(g);
              const addedNodeIds = new Set(
                g.members
                  .map((m) => m.node_id)
                  .filter((id): id is number => id != null),
              );
              const addedGroupIds = new Set(
                g.members
                  .map((m) => m.source_group_id)
                  .filter((id): id is number => id != null),
              );
              const availableNodes = (nodes.data ?? []).filter(
                (n) => !addedNodeIds.has(n.id),
              );
              const availableGroups = (groups.data ?? []).filter(
                (grp) => grp.id !== g.id && !addedGroupIds.has(grp.id),
              );
              const inheritCount = g.members.filter(
                (m) => m.source_group_id != null,
              ).length;
              return (
                <Fragment key={g.id}>
                  <TableRow>
                    <TableCell>
                      <Button
                        size="small"
                        appearance="transparent"
                        icon={
                          isExpanded ? (
                            <ChevronDownRegular />
                          ) : (
                            <ChevronRightRegular />
                          )
                        }
                        onClick={() => toggleGroup(g)}
                        style={{ fontWeight: 600, padding: 0 }}
                      >
                        {g.name}
                      </Button>
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
                          {t("nodes.defaultBadge" as TK)}
                        </Badge>
                      )}
                    </TableCell>
                    <TableCell style={{ color: tokens.colorNeutralForeground3 }}>
                      {g.probe_url || "—"}
                    </TableCell>
                    <TableCell>{g.member_count}</TableCell>
                    <TableCell>{inheritCount}</TableCell>
                    <TableCell>
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
                  {isExpanded && (
                    <TableRow key={`${g.id}-expanded`}>
                      <TableCell
                        colSpan={5}
                        style={{
                          backgroundColor: tokens.colorNeutralBackground1Pressed,
                          padding: "12px 16px",
                        }}
                      >
                        <div
                          style={{
                            display: "flex",
                            flexDirection: "column",
                            gap: 12,
                          }}
                        >
                          {/* Node list (ranked automatically; pinned first) */}
                          <div
                            style={{
                              display: "flex",
                              flexDirection: "column",
                              gap: 0,
                            }}
                          >
                            {g.members.length === 0 && (
                              <Text
                                size={200}
                                style={{ color: tokens.colorNeutralForeground3 }}
                              >
                                {t("nodes.membersEmpty" as TK)}
                              </Text>
                            )}
                            {g.members.map((m) => {
                              const isNode = m.node_id != null;
                              const nodeInfo = isNode ? nodeInfoOf(m) : undefined;
                              const groupInfo = !isNode
                                ? groupInfoOf(m)
                                : undefined;
                              const paused = savingGroupId === g.id;
                              return (
                                <div
                                  key={isNode ? `n-${m.node_id}` : `g-${m.source_group_id}`}
                                  style={{
                                    display: "flex",
                                    alignItems: "center",
                                    gap: 8,
                                    padding: "6px 0",
                                    opacity: paused ? 0.5 : 1,
                                    borderBottom: `1px solid ${tokens.colorNeutralStroke2}`,
                                  }}
                                >
                                  {isNode && nodeInfo ? (
                                    <>
                                      <span
                                        style={{
                                          fontSize: 12,
                                          color: tokens.colorNeutralForeground3,
                                          minWidth: 24,
                                          textAlign: "center",
                                          fontWeight: 600,
                                        }}
                                      >
                                        {m.rank != null ? m.rank + 1 : "—"}
                                      </span>
                                      <span
                                        style={{
                                          flex: 1,
                                          fontSize: 13,
                                          minWidth: 0,
                                          overflow: "hidden",
                                          textOverflow: "ellipsis",
                                          whiteSpace: "nowrap",
                                        }}
                                        title={nodeInfo.note || redactUrl(nodeInfo.url)}
                                      >
                                        {nodeInfo.note || redactUrl(nodeInfo.url)}
                                      </span>
                                      <StatusBadge
                                        status={
                                          nodeInfo.enabled
                                            ? nodeInfo.status
                                            : "disabled"
                                        }
                                      />
                                      <span
                                        style={{
                                          fontSize: 13,
                                          color: tokens.colorNeutralForeground3,
                                          minWidth: 70,
                                          textAlign: "right",
                                        }}
                                      >
                                        {nodeInfo.latency_ms != null
                                          ? `${Math.round(nodeInfo.latency_ms)} ms`
                                          : "—"}
                                      </span>
                                      {canEdit && (
                                        <>
                                          <Tooltip
                                            content={t("nodes.pinHint" as TK)}
                                            relationship="label"
                                          >
                                            <Button
                                              size="small"
                                              appearance={
                                                m.pinned ? "primary" : "subtle"
                                              }
                                              icon={
                                                m.pinned ? (
                                                  <PinRegular />
                                                ) : (
                                                  <PinOffRegular />
                                                )
                                              }
                                              aria-label={
                                                m.pinned
                                                  ? t("nodes.unpin" as TK)
                                                  : t("nodes.pin" as TK)
                                              }
                                              onClick={() => togglePin(g, m)}
                                            />
                                          </Tooltip>
                                          <Tooltip
                                            content={t("nodes.removeMember" as TK)}
                                            relationship="label"
                                          >
                                            <Button
                                              size="small"
                                              appearance="subtle"
                                              icon={<DeleteRegular />}
                                              aria-label={t(
                                                "nodes.removeMember" as TK,
                                              )}
                                              onClick={() => removeMember(g, m)}
                                            />
                                          </Tooltip>
                                        </>
                                      )}
                                    </>
                                  ) : !isNode && groupInfo ? (
                                    <>
                                      <span style={{ width: 24, flexShrink: 0 }} />
                                      <span
                                        style={{
                                          flex: 1,
                                          fontSize: 13,
                                          fontWeight: 600,
                                        }}
                                      >
                                        {groupInfo.name}
                                      </span>
                                      {groupInfo.is_system && (
                                        <Badge
                                          appearance="filled"
                                          color="brand"
                                        >
                                          {t("nodes.systemBadge" as TK)}
                                        </Badge>
                                      )}
                                      {canEdit && (
                                        <Tooltip
                                          content={t("nodes.removeMember" as TK)}
                                          relationship="label"
                                        >
                                          <Button
                                            size="small"
                                            appearance="subtle"
                                            icon={<DeleteRegular />}
                                            aria-label={t(
                                              "nodes.removeMember" as TK,
                                            )}
                                            onClick={() => removeMember(g, m)}
                                          />
                                        </Tooltip>
                                      )}
                                    </>
                                  ) : (
                                    <Text
                                      size={200}
                                      style={{
                                        color: tokens.colorNeutralForegroundDisabled,
                                      }}
                                    >
                                      (removed)
                                    </Text>
                                  )}
                                </div>
                              );
                            })}
                          </div>

                          {/* Add controls */}
                          {canEdit && (
                            <div
                              style={{
                                display: "flex",
                                gap: 12,
                                flexWrap: "wrap",
                                alignItems: "flex-end",
                              }}
                            >
                              <Field
                                label={t("nodes.addNode" as TK)}
                                style={{ minWidth: 260 }}
                              >
                                <Combobox
                                  multiselect
                                  placeholder={t(
                                    "nodes.addNodePlaceholder" as TK,
                                  )}
                                  selectedOptions={[]}
                                  onOptionSelect={(e, d) =>
                                    handleAddNodes(g.id, e, d)
                                  }
                                >
                                  {availableNodes.map((n) => (
                                    <Option
                                      key={n.id}
                                      value={String(n.id)}
                                      text={n.note || n.url || "(direct)"}
                                    >
                                      {n.note || n.url || "(direct)"}
                                      {n.status !== "active"
                                        ? ` (${n.status})`
                                        : ""}
                                    </Option>
                                  ))}
                                </Combobox>
                              </Field>
                              <Field
                                label={t("nodes.inheritGroup" as TK)}
                                style={{ minWidth: 200 }}
                              >
                                <Dropdown
                                  placeholder={t(
                                    "nodes.inheritGroupPlaceholder" as TK,
                                  )}
                                  onOptionSelect={(e, d) => handleAddGroup(g.id, e, d)}
                                >
                                  {availableGroups.map((grp) => (
                                    <Option
                                      key={grp.id}
                                      value={String(grp.id)}
                                      text={grp.name}
                                    >
                                      {grp.name}
                                      {grp.is_system
                                        ? ` (${t("nodes.systemBadge")})`
                                        : ""}
                                    </Option>
                                  ))}
                                </Dropdown>
                              </Field>
                            </div>
                          )}
                        </div>
                      </TableCell>
                    </TableRow>
                  )}
                </Fragment>
              );
            })}
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
                data-shortcut={groupForm?.id ? "save" : "apply"}
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
                data-shortcut="save"
              >
                {t("common.save" as TK)}
              </Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </div>
  );
}