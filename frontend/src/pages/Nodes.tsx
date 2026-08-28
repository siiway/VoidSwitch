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
  CheckmarkCircleRegular,
  ChevronDownRegular,
  ChevronRightRegular,
  CloudOffRegular,
  CloudRegular,
  DeleteRegular,
  EditRegular,
  ProhibitedRegular,
  PulseRegular,
  ReOrderDotsVerticalRegular,
} from "@fluentui/react-icons";
import { Fragment, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import type { Translations } from "../i18n/locales/en";
import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import type { Node, NodeGroup } from "../api/types";
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

interface MemberDraft {
  key: string;
  kind: "node" | "group";
  ref: number;
}

function redactUrl(url: string): string {
  if (!url) return "(direct)";
  return url.replace(/\/\/[^\/:@]+:[^@]+@/, "//***:***@");
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
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [editMembers, setEditMembers] = useState<MemberDraft[]>([]);
  const [dragKey, setDragKey] = useState<string | null>(null);
  const [dragOverIdx, setDragOverIdx] = useState<number | null>(null);
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

  // ---- Inline members ----

  function expandGroup(g: NodeGroup) {
    if (expandedId === g.id) {
      collapseGroup();
      return;
    }
    collapseGroup();
    const draft = g.members.map((m, i) => {
      const isNode = m.node_id != null;
      return {
        key: `m-${i}-${Date.now()}`,
        kind: isNode ? ("node" as const) : ("group" as const),
        ref: isNode ? (m.node_id as number) : (m.source_group_id as number),
      };
    });
    setExpandedId(g.id);
    setEditMembers(draft);
  }

  function collapseGroup() {
    setExpandedId(null);
    setEditMembers([]);
    setDragKey(null);
    setDragOverIdx(null);
  }

  function canEditMembers(g: NodeGroup): boolean {
    if (g.is_system) return isOwner;
    return true;
  }

  function memberNodeInfo(ref: number): Node | undefined {
    return (nodes.data ?? []).find((n) => n.id === ref);
  }

  function memberGroupInfo(ref: number): NodeGroup | undefined {
    return (groups.data ?? []).find((g) => g.id === ref);
  }

  function addMemberDraft(kind: "node" | "group", ref: number) {
    setEditMembers((d) => {
      if (d.some((m) => m.kind === kind && m.ref === ref)) return d;
      return [...d, { key: `${kind}-${ref}-${Date.now()}`, kind, ref }];
    });
  }

  function removeMemberDraft(key: string) {
    setEditMembers((d) => d.filter((m) => m.key !== key));
  }

  async function saveMembers() {
    const group = (groups.data ?? []).find((g) => g.id === expandedId);
    if (!group) return;
    const body = editMembers.map((m, i) =>
      m.kind === "node"
        ? { node_id: m.ref, weight: i + 1 }
        : { source_group_id: m.ref, weight: i + 1 },
    );
    setMembersSaving(true);
    try {
      await api.put(`/api/admin/node-groups/${group.id}/members`, body);
      notify(t("nodes.membersSaved" as TK), group.name, "success");
      collapseGroup();
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

  // ---- Drag sort ----

  function onDragStart(key: string) {
    setDragKey(key);
  }

  function onDragOver(e: React.DragEvent, idx: number) {
    e.preventDefault();
    setDragOverIdx(idx);
  }

  function onDrop(idx: number) {
    if (!dragKey) return;
    const from = editMembers.findIndex((m) => m.key === dragKey);
    if (from < 0 || from === idx) {
      setDragKey(null);
      setDragOverIdx(null);
      return;
    }
    const next = [...editMembers];
    const [moved] = next.splice(from, 1);
    next.splice(idx, 0, moved);
    setEditMembers(next);
    setDragKey(null);
    setDragOverIdx(null);
  }

  function onDragEnd() {
    setDragKey(null);
    setDragOverIdx(null);
  }

  // ---- Combobox helpers ----

  const addedNodeIds = new Set(
    editMembers.filter((m) => m.kind === "node").map((m) => m.ref),
  );
  const addedGroupIds = new Set(
    editMembers.filter((m) => m.kind === "group").map((m) => m.ref),
  );

  const availableNodes = (nodes.data ?? []).filter(
    (n) => !addedNodeIds.has(n.id),
  );
  const availableGroups = (groups.data ?? []).filter(
    (g) => g.id !== expandedId && !addedGroupIds.has(g.id),
  );

  function handleAddNodes(_e: SelectionEvents, d: OptionOnSelectData) {
    for (const id of d.selectedOptions) {
      const nid = Number(id);
      if (!addedNodeIds.has(nid)) {
        addMemberDraft("node", nid);
      }
    }
  }

  function handleAddGroup(_e: SelectionEvents, d: OptionOnSelectData) {
    const gid = Number(d.optionValue);
    if (d.optionValue && !addedGroupIds.has(gid)) {
      addMemberDraft("group", gid);
    }
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
        <Field label={t("nodes.urlsHint" as TK)} style={{ maxWidth: 560 }}>
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
              <TableHeaderCell>{t("nodes.actions" as TK)}</TableHeaderCell>
            </TableRow>
          </TableHeader>
          <TableBody>
            {(groups.data ?? []).map((g) => {
              const isExpanded = expandedId === g.id;
              const canEdit = canEditMembers(g);
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
                        onClick={() => expandGroup(g)}
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
                        colSpan={4}
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
                          <Text size={200} style={{ color: tokens.colorNeutralForeground3 }}>
                            {t("nodes.membersHint" as TK)}
                          </Text>

                          {/* Member list */}
                          <div
                            style={{
                              display: "flex",
                              flexDirection: "column",
                              gap: 0,
                            }}
                          >
                            <Text
                              size={200}
                              weight="semibold"
                              style={{ marginBottom: 4 }}
                            >
                              {t("nodes.membersLabel" as TK)}
                            </Text>
                            {editMembers.length === 0 && (
                              <Text
                                size={200}
                                style={{ color: tokens.colorNeutralForeground3 }}
                              >
                                {t("nodes.membersEmpty" as TK)}
                              </Text>
                            )}
                            {editMembers.map((m, idx) => {
                              const isNode = m.kind === "node";
                              const nodeInfo = isNode
                                ? memberNodeInfo(m.ref)
                                : undefined;
                              const groupInfo = !isNode
                                ? memberGroupInfo(m.ref)
                                : undefined;
                              const showLine =
                                dragKey != null && dragOverIdx === idx;

                              return (
                                <div
                                  key={m.key}
                                  style={{
                                    borderTop: showLine
                                      ? `2px solid ${tokens.colorBrandForeground1}`
                                      : "2px solid transparent",
                                    transition: "border-color 0.15s",
                                  }}
                                >
                                  <div
                                    draggable
                                    onDragStart={() => onDragStart(m.key)}
                                    onDragOver={(e) => onDragOver(e, idx)}
                                    onDrop={() => onDrop(idx)}
                                    onDragEnd={onDragEnd}
                                    style={{
                                      display: "flex",
                                      alignItems: "center",
                                      gap: 8,
                                      padding: "6px 0",
                                      opacity:
                                        dragKey === m.key ? 0.4 : 1,
                                      cursor: "grab",
                                      borderBottom: `1px solid ${tokens.colorNeutralStroke2}`,
                                    }}
                                  >
                                    <Tooltip
                                      content={t("nodes.dragHint" as TK)}
                                      relationship="label"
                                    >
                                      <Button
                                        size="small"
                                        appearance="transparent"
                                        icon={<ReOrderDotsVerticalRegular />}
                                        style={{ cursor: "grab", flexShrink: 0 }}
                                        aria-label={t("nodes.dragHint" as TK)}
                                      />
                                    </Tooltip>

                                    {isNode && nodeInfo ? (
                                      <>
                                        <span
                                          style={{
                                            fontFamily: "monospace",
                                            fontSize: 13,
                                            flex: 1,
                                            minWidth: 0,
                                            overflow: "hidden",
                                            textOverflow: "ellipsis",
                                            whiteSpace: "nowrap",
                                          }}
                                        >
                                          {redactUrl(nodeInfo.url)}
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
                                            minWidth: 40,
                                            textAlign: "right",
                                          }}
                                        >
                                          {nodeInfo.failed_count}
                                        </span>
                                        <span
                                          style={{
                                            fontSize: 13,
                                            color: tokens.colorNeutralForeground3,
                                            minWidth: 60,
                                            textAlign: "right",
                                          }}
                                        >
                                          {nodeInfo.latency_ms != null
                                            ? `${Math.round(nodeInfo.latency_ms)} ms`
                                            : "—"}
                                        </span>
                                        <span
                                          style={{
                                            fontSize: 13,
                                            color: tokens.colorNeutralForeground3,
                                            minWidth: 100,
                                            textAlign: "right",
                                          }}
                                        >
                                          {formatDate(
                                            nodeInfo.last_checked_at,
                                          )}
                                        </span>
                                        <Tooltip
                                          content={t("common.edit")}
                                          relationship="label"
                                        >
                                          <Button
                                            size="small"
                                            appearance="subtle"
                                            icon={<EditRegular />}
                                            aria-label={t("common.edit")}
                                            onClick={() => openRename(nodeInfo)}
                                          />
                                        </Tooltip>
                                        <Tooltip
                                          content={
                                            nodeInfo.enabled
                                              ? t("common.disable")
                                              : t("common.enable")
                                          }
                                          relationship="label"
                                        >
                                          <Button
                                            size="small"
                                            appearance="subtle"
                                            icon={
                                              nodeInfo.enabled ? (
                                                <ProhibitedRegular />
                                              ) : (
                                                <CheckmarkCircleRegular />
                                              )
                                            }
                                            aria-label={
                                              nodeInfo.enabled
                                                ? t("common.disable")
                                                : t("common.enable")
                                            }
                                            onClick={() => toggle(nodeInfo)}
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
                                            onClick={() =>
                                              removeMemberDraft(m.key)
                                            }
                                          />
                                        </Tooltip>
                                      </>
                                    ) : !isNode && groupInfo ? (
                                      <>
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
                                            onClick={() =>
                                              removeMemberDraft(m.key)
                                            }
                                          />
                                        </Tooltip>
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
                                </div>
                              );
                            })}
                            {/* Drop target at the end */}
                            <div
                              style={{
                                borderTop:
                                  dragKey != null &&
                                  dragOverIdx === editMembers.length
                                    ? `2px solid ${tokens.colorBrandForeground1}`
                                    : "2px solid transparent",
                                transition: "border-color 0.15s",
                                minHeight: 4,
                              }}
                              onDragOver={(e) =>
                                onDragOver(e, editMembers.length)
                              }
                              onDrop={() => onDrop(editMembers.length)}
                            />
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
                                  onOptionSelect={handleAddNodes}
                                >
                                  {availableNodes.map((n) => (
                                    <Option
                                      key={n.id}
                                      value={String(n.id)}
                                      text={n.url || "(direct)"}
                                    >
                                      {n.url || "(direct)"}
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
                                  onOptionSelect={handleAddGroup}
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

                          {/* Save / Cancel */}
                          {canEdit && (
                            <div
                              style={{
                                display: "flex",
                                gap: 8,
                                justifyContent: "flex-end",
                              }}
                            >
                              <Button
                                appearance="secondary"
                                onClick={collapseGroup}
                              >
                                {t("common.cancel" as TK)}
                              </Button>
                              <Button
                                appearance="primary"
                                disabled={membersSaving}
                                onClick={saveMembers}
                                data-shortcut="save"
                              >
                                {membersSaving
                                  ? t("nodes.membersSaving" as TK)
                                  : t("common.save" as TK)}
                              </Button>
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