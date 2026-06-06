import {
  Button,
  Card,
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
  ArrowLeftRegular,
  ArrowSyncRegular,
  DeleteRegular,
  EditRegular,
  EyeRegular,
  PersonRegular,
} from "@fluentui/react-icons";
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import type { ApiKey, Provider } from "../api/types";
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

/** Render a key's stored balance blob into a short human string. */
function formatBalance(balance: Record<string, unknown> | undefined): string {
  if (!balance || Object.keys(balance).length === 0) return "—";
  // DeepSeek-style: { is_available, balance_infos: [{ currency, total_balance }] }
  const infos = balance.balance_infos;
  if (Array.isArray(infos) && infos.length) {
    const parts = infos
      .map((i) => {
        const info = i as Record<string, unknown>;
        const amount =
          info.total_balance ?? info.totalBalance ?? info.balance ?? "?";
        const currency = info.currency ?? "";
        return `${amount} ${currency}`.trim();
      })
      .filter(Boolean);
    if (parts.length) return parts.join(", ");
  }
  if (balance.error) return String(balance.error);
  if ("is_available" in balance) {
    return balance.is_available ? "available" : "empty";
  }
  return JSON.stringify(balance);
}

export function ProviderKeys() {
  const { id } = useParams();
  const providerId = Number(id);
  const navigate = useNavigate();
  const notify = useNotify();
  const confirm = useConfirm();
  const { user: me, isStaff, isOwner } = useAuth();
  const canManage = (k: ApiKey) => isStaff || k.added_by === me?.id;
  const provider = useAsync<Provider[]>(() => api.get("/api/admin/providers"));
  const keys = useAsync<ApiKey[]>(
    () => api.get(`/api/admin/providers/${providerId}/keys`),
    [providerId],
  );
  const [bulk, setBulk] = useState("");
  const [pool, setPool] = useState("");
  const [adding, setAdding] = useState(false);

  // Balance-refresh + cleanup state.
  const [refreshingAll, setRefreshingAll] = useState(false);
  const [refreshingId, setRefreshingId] = useState<number | null>(null);
  const [cleaning, setCleaning] = useState(false);
  const [cleanDays, setCleanDays] = useState(0);
  // Which pool a "rescan all" targets: "__all__" = whole provider,
  // "__untagged__" = the empty pool, otherwise a specific pool tag.
  const [scanPool, setScanPool] = useState("__all__");

  // Edit-key dialog state.
  const [editing, setEditing] = useState<ApiKey | null>(null);
  const [editSecret, setEditSecret] = useState("");
  const [editNote, setEditNote] = useState("");
  const [editPool, setEditPool] = useState("");
  const [editBusy, setEditBusy] = useState(false);

  // Reveal-key dialog state (owner-only).
  const [revealed, setRevealed] = useState<{
    preview: string;
    key: string;
  } | null>(null);
  const [revealBusy, setRevealBusy] = useState(false);

  // Claude subscription OAuth login state.
  const [oauthState, setOauthState] = useState<string | null>(null);
  const [oauthCode, setOauthCode] = useState("");
  const [oauthBusy, setOauthBusy] = useState(false);

  // Reset any in-flight login when navigating between providers in place.
  useEffect(() => {
    setOauthState(null);
    setOauthCode("");
  }, [providerId]);

  const current = provider.data?.find((p) => p.id === providerId);
  const isClaudeCode = current?.type === "claude-code";
  const supportsBalance = current?.supports_balance ?? false;
  // Distinct pool tags present among this provider's keys (for the rescan picker).
  const pools = Array.from(
    new Set((keys.data ?? []).map((k) => k.pool ?? "")),
  ).sort();

  async function refreshAllBalances() {
    setRefreshingAll(true);
    try {
      let query = "";
      let scope = "all keys";
      if (scanPool === "__untagged__") {
        query = "?pool=";
        scope = "untagged pool";
      } else if (scanPool !== "__all__") {
        query = `?pool=${encodeURIComponent(scanPool)}`;
        scope = `pool "${scanPool}"`;
      }
      await api.post(
        `/api/admin/providers/${providerId}/keys/refresh-balance${query}`,
      );
      notify("Balances rescanned", scope, "success");
      keys.reload();
    } catch (e) {
      notify(
        "Rescan failed",
        e instanceof Error ? e.message : String(e),
        "error",
      );
    } finally {
      setRefreshingAll(false);
    }
  }

  async function refreshOneBalance(k: ApiKey) {
    setRefreshingId(k.id);
    try {
      await api.post(
        `/api/admin/providers/${providerId}/keys/${k.id}/refresh-balance`,
      );
      keys.reload();
    } catch (e) {
      notify(
        "Refresh failed",
        e instanceof Error ? e.message : String(e),
        "error",
      );
    } finally {
      setRefreshingId(null);
    }
  }

  async function cleanup(target: "invalid" | "insufficient_balance") {
    const isBalance = target === "insufficient_balance";
    const label = isBalance ? "no-balance" : "invalid";
    const ok = await confirm({
      title: `Clear ${label} keys`,
      message: isBalance
        ? `Delete keys with no balance for at least ${cleanDays} day(s)? This cannot be undone.`
        : "Delete all keys whose secret was rejected (invalid)? This cannot be undone.",
      confirmLabel: "Delete",
      tone: "danger",
    });
    if (!ok) return;
    setCleaning(true);
    try {
      const r = await api.post<{ deleted: number }>(
        `/api/admin/providers/${providerId}/keys/cleanup`,
        isBalance
          ? { target, min_days: cleanDays }
          : { target, min_days: 0 },
      );
      notify(
        "Cleanup complete",
        `${r.deleted} ${label} key(s) removed`,
        "success",
      );
      keys.reload();
    } catch (e) {
      notify(
        "Cleanup failed",
        e instanceof Error ? e.message : String(e),
        "error",
      );
    } finally {
      setCleaning(false);
    }
  }

  async function startOAuth() {
    setOauthBusy(true);
    try {
      const r = await api.post<{ authorize_url: string; state: string }>(
        `/api/admin/providers/${providerId}/keys/oauth/start`,
      );
      setOauthState(r.state);
      setOauthCode("");
      window.open(r.authorize_url, "_blank", "noopener,noreferrer");
    } catch (e) {
      notify(
        "Could not start sign-in",
        e instanceof Error ? e.message : String(e),
        "error",
      );
    } finally {
      setOauthBusy(false);
    }
  }

  async function completeOAuth() {
    if (!oauthState || !oauthCode.trim()) return;
    setOauthBusy(true);
    try {
      await api.post(`/api/admin/providers/${providerId}/keys/oauth/complete`, {
        code: oauthCode.trim(),
        state: oauthState,
      });
      notify("Signed in", "Claude subscription credential added", "success");
      setOauthState(null);
      setOauthCode("");
      keys.reload();
    } catch (e) {
      notify(
        "Sign-in failed",
        e instanceof Error ? e.message : String(e),
        "error",
      );
    } finally {
      setOauthBusy(false);
    }
  }

  async function addKeys() {
    const list = bulk
      .split("\n")
      .map((s) => s.trim())
      .filter(Boolean);
    if (!list.length) return;
    setAdding(true);
    try {
      const created = await api.post<ApiKey[]>(
        `/api/admin/providers/${providerId}/keys`,
        { keys: list, pool: pool.trim() },
      );
      notify(
        "Keys added",
        `${created.length} new key(s)${pool.trim() ? ` in pool "${pool.trim()}"` : ""}`,
        "success",
      );
      setBulk("");
      keys.reload();
    } catch (e) {
      notify("Add failed", e instanceof Error ? e.message : String(e), "error");
    } finally {
      setAdding(false);
    }
  }

  function openEdit(k: ApiKey) {
    setEditing(k);
    setEditSecret("");
    setEditNote(k.note ?? "");
    setEditPool(k.pool ?? "");
  }

  async function saveEdit() {
    if (!editing) return;
    setEditBusy(true);
    try {
      const patch: {
        key?: string;
        note: string;
        pool: string;
      } = { note: editNote.trim(), pool: editPool.trim() };
      if (editSecret.trim()) patch.key = editSecret.trim();
      await api.patch(
        `/api/admin/providers/${providerId}/keys/${editing.id}`,
        patch,
      );
      notify("Key updated", editing.key_preview, "success");
      setEditing(null);
      keys.reload();
    } catch (e) {
      notify(
        "Update failed",
        e instanceof Error ? e.message : String(e),
        "error",
      );
    } finally {
      setEditBusy(false);
    }
  }

  async function toggle(k: ApiKey) {
    const enabled = k.status !== "active";
    await api.patch(`/api/admin/providers/${providerId}/keys/${k.id}`, {
      enabled,
    });
    keys.reload();
  }

  async function remove(k: ApiKey) {
    const ok = await confirm({
      title: "Delete key",
      message: `Delete key ${k.key_preview}?`,
      confirmLabel: "Delete",
      tone: "danger",
    });
    if (!ok) return;
    await api.del(`/api/admin/providers/${providerId}/keys/${k.id}`);
    keys.reload();
  }

  async function reveal(k: ApiKey) {
    const ok = await confirm({
      title: "Reveal key",
      message:
        `Show the full plaintext secret for ${k.key_preview}? ` +
        "This reveal is recorded in the audit trail.",
      confirmLabel: "Reveal",
      tone: "danger",
    });
    if (!ok) return;
    setRevealBusy(true);
    try {
      const r = await api.post<{ preview: string; key: string }>(
        `/api/admin/providers/${providerId}/keys/${k.id}/reveal`,
      );
      setRevealed({ preview: r.preview, key: r.key });
    } catch (e) {
      notify(
        "Reveal failed",
        e instanceof Error ? e.message : String(e),
        "error",
      );
    } finally {
      setRevealBusy(false);
    }
  }

  return (
    <div>
      <Button
        appearance="subtle"
        icon={<ArrowLeftRegular />}
        onClick={() => navigate("/providers")}
        style={{ marginBottom: 8 }}
      >
        Back to providers
      </Button>
      <PageHeader
        title={`Keys · ${current?.name ?? `#${providerId}`}`}
        subtitle={
          isClaudeCode
            ? "Sign in with a Claude subscription, or paste setup-tokens / credential bundles below"
            : "Paste one API key per line to add in bulk. Add an inline description with # (e.g. sk-abc # alice's key)"
        }
        action={
          supportsBalance ? (
            <div style={{ display: "flex", gap: 8, alignItems: "flex-end" }}>
              <Field label="Rescan scope">
                <Dropdown
                  style={{ minWidth: 150 }}
                  selectedOptions={[scanPool]}
                  value={
                    scanPool === "__all__"
                      ? "All pools"
                      : scanPool === "__untagged__"
                        ? "(untagged)"
                        : scanPool
                  }
                  onOptionSelect={(_, d) =>
                    setScanPool(d.optionValue ?? "__all__")
                  }
                >
                  <Option value="__all__" text="All pools">
                    All pools
                  </Option>
                  {pools.map((p) => (
                    <Option
                      key={p === "" ? "__untagged__" : p}
                      value={p === "" ? "__untagged__" : p}
                      text={p === "" ? "(untagged)" : p}
                    >
                      {p === "" ? "(untagged)" : p}
                    </Option>
                  ))}
                </Dropdown>
              </Field>
              <Button
                appearance="secondary"
                icon={<ArrowSyncRegular />}
                disabled={refreshingAll}
                onClick={refreshAllBalances}
              >
                {refreshingAll ? "Rescanning…" : "Rescan balances"}
              </Button>
            </div>
          ) : undefined
        }
      />

      {isClaudeCode ? (
        <Card style={{ marginBottom: 16, padding: 16, gap: 8 }}>
          <Text weight="semibold" block>
            Sign in with Claude (OAuth)
          </Text>
          <Text
            size={200}
            block
            style={{ color: tokens.colorNeutralForeground3 }}
          >
            Use a Claude Pro/Max subscription instead of an API key. This opens
            Claude's authorization page in a new tab; after approving, copy the
            code it shows (looks like <code>code#state</code>) and paste it back
            here.
          </Text>
          {oauthState === null ? (
            <Button
              appearance="primary"
              icon={<PersonRegular />}
              disabled={oauthBusy}
              onClick={startOAuth}
              style={{ alignSelf: "flex-start", marginTop: 4 }}
            >
              Start sign-in
            </Button>
          ) : (
            <>
              <Field
                label="Paste the code from Claude"
                style={{ marginTop: 4 }}
              >
                <Input
                  value={oauthCode}
                  placeholder="abc123…#xyz789…"
                  onChange={(_, d) => setOauthCode(d.value)}
                />
              </Field>
              <div style={{ display: "flex", gap: 8 }}>
                <Button
                  appearance="primary"
                  disabled={oauthBusy || !oauthCode.trim()}
                  onClick={completeOAuth}
                >
                  Complete sign-in
                </Button>
                <Button
                  appearance="subtle"
                  disabled={oauthBusy}
                  onClick={() => {
                    setOauthState(null);
                    setOauthCode("");
                  }}
                >
                  Cancel
                </Button>
              </div>
            </>
          )}
        </Card>
      ) : null}

      <Field style={{ marginBottom: 8 }}>
        <Textarea
          value={bulk}
          rows={4}
          placeholder={
            isClaudeCode
              ? 'sk-ant-oat01-...\n{"access_token":...}'
              : "sk-...\nsk-... # optional description\nsk-..."
          }
          onChange={(_, d) => setBulk(d.value)}
        />
      </Field>
      <div
        style={{
          display: "flex",
          gap: 16,
          alignItems: "flex-end",
          flexWrap: "wrap",
          marginBottom: 8,
        }}
      >
        <Field
          label="Key pool (optional tag — e.g. leaked, members)"
          style={{ flex: "1 1 240px", maxWidth: 320 }}
        >
          <Input
            value={pool}
            placeholder="(untagged)"
            onChange={(_, d) => setPool(d.value)}
          />
        </Field>
        {/* Bulk cleanup of dead keys — fills the empty space beside the pool tag. */}
        <div
          style={{
            marginLeft: "auto",
            display: "flex",
            gap: 8,
            alignItems: "flex-end",
            flexWrap: "wrap",
          }}
        >
          <Field label="No balance for ≥ (days)">
            <SpinButton
              value={cleanDays}
              min={0}
              max={365}
              style={{ width: 110 }}
              onChange={(_, d) => {
                const next =
                  d.value ?? (d.displayValue ? Number(d.displayValue) : 0);
                if (!Number.isNaN(next)) setCleanDays(Math.max(0, next));
              }}
            />
          </Field>
          <Tooltip
            content="Delete keys that have had no balance for at least the given number of days"
            relationship="label"
          >
            <Button
              appearance="secondary"
              icon={<DeleteRegular />}
              disabled={cleaning}
              onClick={() => cleanup("insufficient_balance")}
            >
              Clear no-balance
            </Button>
          </Tooltip>
          <Tooltip
            content="Delete every key whose secret was rejected (invalid)"
            relationship="label"
          >
            <Button
              appearance="secondary"
              icon={<DeleteRegular />}
              disabled={cleaning}
              onClick={() => cleanup("invalid")}
            >
              Clear invalid
            </Button>
          </Tooltip>
        </div>
      </div>
      <Button
        appearance="primary"
        disabled={adding || !bulk.trim()}
        onClick={addKeys}
        style={{ marginBottom: 24 }}
      >
        Add keys
      </Button>

      {keys.loading ? (
        <Loading />
      ) : keys.error ? (
        <ErrorText error={keys.error} />
      ) : (
        <DataTable ariaLabel="Keys">
          <TableHeader>
            <TableRow>
              <TableHeaderCell>Key</TableHeaderCell>
              <TableHeaderCell>Comment</TableHeaderCell>
              <TableHeaderCell>Pool</TableHeaderCell>
              <TableHeaderCell>Added by</TableHeaderCell>
              <TableHeaderCell>Status</TableHeaderCell>
              {supportsBalance && (
                <TableHeaderCell>Balance</TableHeaderCell>
              )}
              <TableHeaderCell>Fails</TableHeaderCell>
              <TableHeaderCell>Requests</TableHeaderCell>
              <TableHeaderCell>Last used</TableHeaderCell>
              <TableHeaderCell>Reason</TableHeaderCell>
              <TableHeaderCell>Actions</TableHeaderCell>
            </TableRow>
          </TableHeader>
          <TableBody>
            {(keys.data ?? []).map((k) => (
              <TableRow key={k.id}>
                <TableCell style={{ fontFamily: "monospace" }}>
                  {k.key_preview}
                </TableCell>
                <TableCell style={{ color: tokens.colorNeutralForeground3 }}>
                  {k.note || "—"}
                </TableCell>
                <TableCell style={{ color: tokens.colorNeutralForeground3 }}>
                  {k.pool || "—"}
                </TableCell>
                <TableCell style={{ color: tokens.colorNeutralForeground3 }}>
                  {k.added_by_name ?? "—"}
                </TableCell>
                <TableCell>
                  <StatusBadge status={k.status} />
                </TableCell>
                {supportsBalance && (
                  <TableCell>
                    <div
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 4,
                      }}
                    >
                      <span>{formatBalance(k.balance)}</span>
                      <Tooltip
                        content="Refresh this key's balance"
                        relationship="label"
                      >
                        <Button
                          size="small"
                          appearance="subtle"
                          icon={<ArrowSyncRegular />}
                          disabled={refreshingId === k.id || refreshingAll}
                          onClick={() => refreshOneBalance(k)}
                        />
                      </Tooltip>
                    </div>
                  </TableCell>
                )}
                <TableCell>{k.failed_count}</TableCell>
                <TableCell>{k.total_requests}</TableCell>
                <TableCell style={{ color: tokens.colorNeutralForeground3 }}>
                  {formatDate(k.last_used_at)}
                </TableCell>
                <TableCell style={{ color: tokens.colorNeutralForeground3 }}>
                  {k.disabled_reason ?? "—"}
                </TableCell>
                <TableCell>
                  {isOwner && (
                    <Button
                      size="small"
                      appearance="subtle"
                      icon={<EyeRegular />}
                      disabled={revealBusy}
                      onClick={() => reveal(k)}
                    >
                      Reveal
                    </Button>
                  )}
                  {canManage(k) ? (
                    <>
                      <Button
                        size="small"
                        appearance="subtle"
                        icon={<EditRegular />}
                        onClick={() => openEdit(k)}
                      >
                        Edit
                      </Button>
                      <Button
                        size="small"
                        appearance="subtle"
                        onClick={() => toggle(k)}
                      >
                        {k.status === "active" ? "Disable" : "Enable"}
                      </Button>
                      <Button
                        size="small"
                        appearance="subtle"
                        icon={<DeleteRegular />}
                        onClick={() => remove(k)}
                      />
                    </>
                  ) : (
                    !isOwner && (
                      <span style={{ color: tokens.colorNeutralForeground3 }}>
                        —
                      </span>
                    )
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </DataTable>
      )}

      <Dialog
        open={editing !== null}
        onOpenChange={(_, d) => {
          if (!d.open) setEditing(null);
        }}
      >
        <DialogSurface>
          <DialogBody>
            <DialogTitle>Edit key {editing?.key_preview}</DialogTitle>
            <DialogContent
              style={{ display: "flex", flexDirection: "column", gap: 12 }}
            >
              <Field
                label="Key"
                hint="Leave blank to keep the current secret unchanged"
              >
                <Input
                  value={editSecret}
                  type="password"
                  placeholder={`Current: ${editing?.key_preview ?? ""}`}
                  onChange={(_, d) => setEditSecret(d.value)}
                />
              </Field>
              <Field label="Comment">
                <Input
                  value={editNote}
                  placeholder="(none)"
                  onChange={(_, d) => setEditNote(d.value)}
                />
              </Field>
              <Field label="Pool">
                <Input
                  value={editPool}
                  placeholder="(untagged)"
                  onChange={(_, d) => setEditPool(d.value)}
                />
              </Field>
            </DialogContent>
            <DialogActions>
              <Button
                appearance="subtle"
                disabled={editBusy}
                onClick={() => setEditing(null)}
              >
                Cancel
              </Button>
              <Button
                appearance="primary"
                disabled={editBusy}
                onClick={saveEdit}
              >
                Save
              </Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>

      <Dialog
        open={revealed !== null}
        onOpenChange={(_, d) => !d.open && setRevealed(null)}
      >
        <DialogSurface>
          <DialogBody>
            <DialogTitle>Key · {revealed?.preview}</DialogTitle>
            <DialogContent>
              <Text
                size={200}
                block
                style={{
                  color: tokens.colorNeutralForeground3,
                  marginBottom: 8,
                }}
              >
                Plaintext secret — handle with care.
              </Text>
              <Textarea
                readOnly
                value={revealed?.key ?? ""}
                rows={6}
                style={{ width: "100%", fontFamily: "monospace" }}
              />
            </DialogContent>
            <DialogActions>
              <Button appearance="primary" onClick={() => setRevealed(null)}>
                Close
              </Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </div>
  );
}
