import {
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
  Menu,
  MenuItem,
  MenuList,
  MenuPopover,
  MenuTrigger,
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
  ArrowUploadRegular,
  ArrowDownloadRegular,
  CheckmarkCircleRegular,
  DeleteRegular,
  EditRegular,
  EyeOffRegular,
  EyeRegular,
  KeyResetRegular,
  PersonRegular,
  ProhibitedRegular,
  ReOrderDotsVerticalRegular,
} from "@fluentui/react-icons";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import type { ApiKey, AuthImportResult, Provider } from "../api/types";
import type { Translations } from "../i18n/locales/en";
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
  const { t } = useTranslation();
  type TK = keyof Translations;
  const provider = useAsync<Provider[]>(() => api.get("/api/admin/providers"));
  const keys = useAsync<ApiKey[]>(
    () => api.get(`/api/admin/providers/${providerId}/keys`),
    [providerId],
  );
  const [bulk, setBulk] = useState("");
  const [pool, setPool] = useState("");
  const [adding, setAdding] = useState(false);

  // Drag-sort state. ``rows`` mirrors the loaded keys but is locally reorderable;
  // a drag (or the top/bottom menu) persists the new order to the backend.
  const [rows, setRows] = useState<ApiKey[]>([]);
  const [dragId, setDragId] = useState<number | null>(null);
  const [dragOverIdx, setDragOverIdx] = useState<number | null>(null);
  const [reordering, setReordering] = useState(false);
  useEffect(() => {
    setRows(keys.data ?? []);
  }, [keys.data]);

  // Balance-refresh + cleanup state.
  const [refreshingAll, setRefreshingAll] = useState(false);
  const [refreshingId, setRefreshingId] = useState<number | null>(null);
  // Per-key OAuth token-refresh in flight (claude-code / xai providers).
  const [refreshingTokenId, setRefreshingTokenId] = useState<number | null>(null);
  const [cleaning, setCleaning] = useState(false);
  const [cleanDays, setCleanDays] = useState(0);
  // Which pool a "rescan all" targets: "__all__" = whole provider,
  // "__untagged__" = the empty pool, otherwise a specific pool tag.
  const [scanPool, setScanPool] = useState("__all__");
  // Pool scope for cleanup — same semantics as scanPool.
  const [cleanPool, setCleanPool] = useState("__all__");

  // Edit-key dialog state.
  const [editing, setEditing] = useState<ApiKey | null>(null);
  const [editSecret, setEditSecret] = useState("");
  const [editNote, setEditNote] = useState("");
  const [editPool, setEditPool] = useState("");
  const [editBusy, setEditBusy] = useState(false);
  // OAuth bundle editing (Claude Code providers).
  const [editIsBundle, setEditIsBundle] = useState(false);
  const [editAccessToken, setEditAccessToken] = useState("");
  const [editRefreshToken, setEditRefreshToken] = useState("");
  const [editExpiresAt, setEditExpiresAt] = useState("");
  // Cloudflare composite-key editing (account_id@api_token).
  const [editIsCloudflare, setEditIsCloudflare] = useState(false);
  const [editCfAccountId, setEditCfAccountId] = useState("");
  const [editCfToken, setEditCfToken] = useState("");

  // Reveal-inside-edit flow. The current secret is *never* fetched when the
  // edit dialog opens (that would emit an audit record on every edit). Instead a
  // field's plaintext is only pulled after the user clicks its reveal button and
  // confirms the nested dialog. The full key is cached once, so revealing a
  // second part of a multi-part key needs no further confirmation.
  type RevealData = {
    key: string;
    is_bundle?: boolean;
    access_token?: string;
    refresh_token?: string;
    expires_at?: number | null;
  };
  const [editRevealData, setEditRevealData] = useState<RevealData | null>(null);
  const [revealShown, setRevealShown] = useState<Set<string>>(new Set());
  const [revealFetching, setRevealFetching] = useState(false);

  // Add-key helpers.
  const [cfAccountId, setCfAccountId] = useState("");
  const [cfToken, setCfToken] = useState("");
  const [cfComment, setCfComment] = useState("");
  const [claudeAccessToken, setClaudeAccessToken] = useState("");
  const [claudeRefreshToken, setClaudeRefreshToken] = useState("");
  const [claudeExpiresAt, setClaudeExpiresAt] = useState("");
  const [claudeComment, setClaudeComment] = useState("");

  // Import from sub2api / CLIProxyAPI auth files (file upload + paste).
  const [importFiles, setImportFiles] = useState<File[]>([]);
  const [importPaste, setImportPaste] = useState("");
  const [importBusy, setImportBusy] = useState(false);

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
  const isGrokBuild = current?.type === "grok-build";
  const supportsBalance = current?.supports_balance ?? false;
  const supportsImport = current?.supports_import ?? false;
  const supportsRefresh = current?.supports_refresh ?? false;
  const supportsOauth = current?.supports_oauth ?? false;
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
      notify(t("providerKeys.rescanSuccess" as TK), scope, "success");
      keys.reload();
    } catch (e) {
      notify(
        t("providerKeys.rescanFailed" as TK),
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
        t("providerKeys.refreshFailed" as TK),
        e instanceof Error ? e.message : String(e),
        "error",
      );
    } finally {
      setRefreshingId(null);
    }
  }

  // Force an OAuth token refresh for a single key (claude-code / xai). The
  // backend rotates the credential bundle, re-enables the key, and records the
  // action in both the request and audit logs with the acting user.
  async function refreshToken(k: ApiKey) {
    setRefreshingTokenId(k.id);
    try {
      await api.post(
        `/api/admin/providers/${providerId}/keys/${k.id}/refresh-token`,
      );
      notify(t("providerKeys.refreshTokenDone" as TK), k.key_preview, "success");
      keys.reload();
    } catch (e) {
      notify(
        t("providerKeys.refreshTokenFailed" as TK),
        e instanceof Error ? e.message : String(e),
        "error",
      );
    } finally {
      setRefreshingTokenId(null);
    }
  }

  async function cleanup(target: "invalid" | "insufficient_balance") {
    const isBalance = target === "insufficient_balance";
    const label = isBalance ? "no-balance" : "invalid";
    let query = "";
    let scope = "all keys";
    if (cleanPool === "__untagged__") {
      query = "?pool=";
      scope = "untagged pool";
    } else if (cleanPool !== "__all__") {
      query = `?pool=${encodeURIComponent(cleanPool)}`;
      scope = `pool "${cleanPool}"`;
    }
    const ok = await confirm({
      title: `Clear ${label} keys`,
      message: isBalance
        ? `Delete ${scope} with no balance for at least ${cleanDays} day(s)? This cannot be undone.`
        : `Delete ${scope} rejected as invalid? This cannot be undone.`,
      confirmLabel: t("common.delete" as TK),
      tone: "danger",
    });
    if (!ok) return;
    setCleaning(true);
    try {
      const r = await api.post<{ deleted: number }>(
        `/api/admin/providers/${providerId}/keys/cleanup${query}`,
        isBalance
          ? { target, min_days: cleanDays }
          : { target, min_days: 0 },
      );
      notify(
        t("providerKeys.cleanupComplete" as TK),
        `${r.deleted} ${label} key(s) removed`,
        "success",
      );
      keys.reload();
    } catch (e) {
      notify(
        t("providerKeys.cleanupFailed" as TK),
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
        t("providerKeys.oauthStartFailed" as TK),
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
      notify(t("providerKeys.oauthSignedIn" as TK), t("providerKeys.oauthCredentialAdded" as TK), "success");
      setOauthState(null);
      setOauthCode("");
      keys.reload();
    } catch (e) {
      notify(
        t("providerKeys.oauthSignInFailed" as TK),
        e instanceof Error ? e.message : String(e),
        "error",
      );
    } finally {
      setOauthBusy(false);
    }
  }

  async function addHelperKey(line: string) {
    const list = line.trim().split("\n").filter(Boolean);
    if (!list.length) return;
    setAdding(true);
    try {
      const created = await api.post<ApiKey[]>(
        `/api/admin/providers/${providerId}/keys`,
        { keys: list, pool: pool.trim() },
      );
      notify(
        t("providerKeys.created" as TK),
        `${created.length} new key(s)${pool.trim() ? ` in pool "${pool.trim()}"` : ""}`,
        "success",
      );
      keys.reload();
    } catch (e) {
      notify(t("providerKeys.addFailed" as TK), e instanceof Error ? e.message : String(e), "error");
    } finally {
      setAdding(false);
    }
  }

  async function runImport() {
    const sources: string[] = [];
    for (const file of importFiles) {
      const text = (await file.text()).trim();
      if (text) sources.push(text);
    }
    const pasted = importPaste.trim();
    if (pasted) sources.push(pasted);
    if (!sources.length) return;
    setImportBusy(true);
    try {
      const res = await api.post<AuthImportResult>(
        `/api/admin/providers/${providerId}/keys/import`,
        { sources, pool: pool.trim(), note: null },
      );
      notify(
        t("providerKeys.importDone" as TK),
        t("providerKeys.importSummary" as TK, {
          imported: res.imported,
          duplicates: res.duplicates,
          unusable: res.unusable,
        }),
        "success",
      );
      setImportFiles([]);
      setImportPaste("");
      keys.reload();
    } catch (e) {
      notify(
        t("providerKeys.importFailed" as TK),
        e instanceof Error ? e.message : String(e),
        "error",
      );
    } finally {
      setImportBusy(false);
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
        t("providerKeys.created" as TK),
        `${created.length} new key(s)${pool.trim() ? ` in pool "${pool.trim()}"` : ""}`,
        "success",
      );
      setBulk("");
      keys.reload();
    } catch (e) {
      notify(t("providerKeys.addFailed" as TK), e instanceof Error ? e.message : String(e), "error");
    } finally {
      setAdding(false);
    }
  }

  function openEdit(k: ApiKey) {
    setEditing(k);
    setEditSecret("");
    setEditNote(k.note ?? "");
    setEditPool(k.pool ?? "");
    setEditAccessToken("");
    setEditRefreshToken("");
    setEditExpiresAt("");
    setEditCfAccountId("");
    setEditCfToken("");
    // Reset the reveal flow — nothing is fetched until the user asks for it.
    setEditRevealData(null);
    setRevealShown(new Set());
    // Infer the key's shape from its (non-secret) preview / provider type so the
    // right fields render *without* decrypting the stored secret. OAuth bundles
    // carry an "oauth·" preview prefix; Cloudflare keys are always composite.
    setEditIsBundle(k.key_preview.startsWith("oauth·"));
    setEditIsCloudflare(current?.type === "cloudflare");
  }

  // Split a revealed Cloudflare composite key into its (account_id, api_token).
  function splitCf(raw: string): [string, string] {
    const at = raw.indexOf("@");
    return at >= 0 ? [raw.slice(0, at), raw.slice(at + 1)] : ["", raw];
  }

  // Fill a single field's input from already-fetched reveal data and mark it as
  // visible. Only the requested field is populated so revealing one part of a
  // multi-part key doesn't expose the others.
  function fillRevealField(field: string, data: RevealData) {
    if (editIsCloudflare) {
      const [acc, tok] = splitCf(data.key);
      if (field === "cf_account_id") setEditCfAccountId(acc);
      if (field === "cf_token") setEditCfToken(tok);
    } else if (editIsBundle) {
      if (field === "access_token") setEditAccessToken(data.access_token ?? "");
      if (field === "refresh_token") setEditRefreshToken(data.refresh_token ?? "");
    } else if (field === "key") {
      setEditSecret(data.key);
    }
    setRevealShown((s) => new Set(s).add(field));
  }

  // Reveal button handler: toggles off if shown; reveals from cache if the key
  // was already fetched; otherwise fetches (and audits) the plaintext straight
  // away. Clicking the per-field eye button *is* the deliberate, owner-only
  // action, so it no longer pops a second confirmation dialog. Stacking a modal
  // dialog on top of the (modal) edit dialog tore the edit dialog's focus trap
  // down when the inner one closed — the edit inputs then couldn't hold focus
  // (focus escaped to the table behind the modal). Fetching inline avoids that.
  async function onRevealField(field: string) {
    if (revealShown.has(field)) {
      setRevealShown((s) => {
        const next = new Set(s);
        next.delete(field);
        return next;
      });
      return;
    }
    if (editRevealData) {
      fillRevealField(field, editRevealData);
      return;
    }
    if (!editing) return;
    setRevealFetching(true);
    try {
      const r = await api.post<RevealData>(
        `/api/admin/providers/${providerId}/keys/${editing.id}/reveal`,
      );
      setEditRevealData(r);
      // expires_at is not a secret; surface it once the bundle is unlocked.
      if (r.expires_at != null) setEditExpiresAt(String(r.expires_at));
      fillRevealField(field, r);
    } catch (e) {
      notify(
        t("providerKeys.revealFailed" as TK),
        e instanceof Error ? e.message : String(e),
        "error",
      );
    } finally {
      setRevealFetching(false);
    }
  }

  // Render a secret field with an integrated reveal (eye) button. Called as a
  // plain function — not a nested component — so typing doesn't remount it and
  // lose focus.
  function renderRevealField(
    field: string,
    label: string,
    value: string,
    onChange: (v: string) => void,
    opts?: { hint?: string; placeholder?: string },
  ) {
    const shown = revealShown.has(field);
    const toggleLabel = shown
      ? t("common.hidePassword" as TK)
      : t("common.showPassword" as TK);
    return (
      <Field label={label} hint={opts?.hint}>
        <Input
          type={shown ? "text" : "password"}
          value={value}
          autoComplete="current-password"
          placeholder={
            opts?.placeholder ?? `Current: ${editing?.key_preview ?? ""}`
          }
          onChange={(_, d) => onChange(d.value)}
          contentAfter={
            isOwner ? (
              <Tooltip content={toggleLabel} relationship="label">
                <Button
                  appearance="transparent"
                  size="small"
                  tabIndex={-1}
                  disabled={revealFetching}
                  icon={shown ? <EyeOffRegular /> : <EyeRegular />}
                  aria-label={toggleLabel}
                  onClick={() => onRevealField(field)}
                />
              </Tooltip>
            ) : undefined
          }
        />
      </Field>
    );
  }

  async function saveEdit() {
    if (!editing) return;
    setEditBusy(true);
    try {
      const patch: Record<string, unknown> = {
        note: editNote.trim(),
        pool: editPool.trim(),
      };
      if (editIsBundle) {
        // Send individual OAuth bundle fields.
        if (editAccessToken.trim())
          patch.access_token = editAccessToken.trim();
        if (editRefreshToken.trim())
          patch.refresh_token = editRefreshToken.trim();
        if (editExpiresAt.trim())
          patch.expires_at = Number(editExpiresAt.trim());
      } else if (editIsCloudflare) {
        // Rebuild the account_id@api_token composite. A part left blank falls
        // back to the revealed original, so editing just one part keeps the
        // other. Only send it when something actually changed.
        const acc =
          editCfAccountId.trim() ||
          (editRevealData ? splitCf(editRevealData.key)[0] : "");
        const tok =
          editCfToken.trim() ||
          (editRevealData ? splitCf(editRevealData.key)[1] : "");
        const composite = `${acc}@${tok}`;
        if (
          acc &&
          tok &&
          (editCfAccountId.trim() || editCfToken.trim()) &&
          composite !== editRevealData?.key
        ) {
          patch.key = composite;
        }
      } else if (
        editSecret.trim() &&
        editSecret.trim() !== editRevealData?.key.trim()
      ) {
        // Only persist a genuinely new secret — not one that was merely revealed
        // for viewing and left untouched.
        patch.key = editSecret.trim();
      }
      await api.patch(
        `/api/admin/providers/${providerId}/keys/${editing.id}`,
        patch,
      );
      notify(t("providerKeys.updated" as TK), editing.key_preview, "success");
      setEditing(null);
      keys.reload();
    } catch (e) {
      notify(
        t("common.updateFailed" as TK),
        e instanceof Error ? e.message : String(e),
        "error",
      );
    } finally {
      setEditBusy(false);
    }
  }

  async function toggle(k: ApiKey) {
    const enabled = k.status !== "active";
    try {
      await api.patch(`/api/admin/providers/${providerId}/keys/${k.id}`, {
        enabled,
      });
      keys.reload();
    } catch (e) {
      notify(
        t("common.updateFailed" as TK),
        e instanceof Error ? e.message : String(e),
        "error",
      );
    }
  }

  async function remove(k: ApiKey) {
    const ok = await confirm({
      title: t("providerKeys.deleteTitle" as TK),
      message: t("providerKeys.deleteMsg" as TK).replace(
        "{preview}",
        k.key_preview,
      ),
      confirmLabel: t("common.delete" as TK),
      tone: "danger",
    });
    if (!ok) return;
    try {
      await api.del(`/api/admin/providers/${providerId}/keys/${k.id}`);
      keys.reload();
    } catch (e) {
      notify(
        t("common.deleteFailed" as TK),
        e instanceof Error ? e.message : String(e),
        "error",
      );
    }
  }

  async function reveal(k: ApiKey) {
    const ok = await confirm({
      title: t("providerKeys.revealTitle" as TK),
      message: t("providerKeys.revealMsg" as TK),
      confirmLabel: t("providerKeys.revealLabel" as TK),
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
        t("providerKeys.revealFailed" as TK),
        e instanceof Error ? e.message : String(e),
        "error",
      );
    } finally {
      setRevealBusy(false);
    }
  }

  async function toggleProvider() {
    if (!current) return;
    try {
      await api.patch(`/api/admin/providers/${providerId}`, {
        enabled: !current.enabled,
      });
      provider.reload();
    } catch (e) {
      notify(
        t("common.updateFailed" as TK),
        e instanceof Error ? e.message : String(e),
        "error",
      );
    }
  }

  async function persistOrder(ordered: ApiKey[]) {
    setReordering(true);
    try {
      const updated = await api.post<ApiKey[]>(
        `/api/admin/providers/${providerId}/keys/reorder`,
        { order: ordered.map((k) => k.id) },
      );
      setRows(updated);
      keys.reload();
    } catch (e) {
      notify(
        t("providerKeys.reorderFailed" as TK),
        e instanceof Error ? e.message : String(e),
        "error",
      );
      setRows(keys.data ?? []); // revert to the last known-good order
    } finally {
      setReordering(false);
    }
  }

  function onDropRow(targetId: number) {
    const from = rows.findIndex((k) => k.id === dragId);
    const to = rows.findIndex((k) => k.id === targetId);
    setDragId(null);
    if (from < 0 || to < 0 || from === to) return;
    const next = [...rows];
    const [moved] = next.splice(from, 1);
    next.splice(to, 0, moved);
    setRows(next);
    persistOrder(next);
  }

  function moveKey(id: number, where: "top" | "bottom") {
    const from = rows.findIndex((k) => k.id === id);
    if (from < 0) return;
    const next = [...rows];
    const [moved] = next.splice(from, 1);
    if (where === "top") next.unshift(moved);
    else next.push(moved);
    setRows(next);
    persistOrder(next);
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
        title={`${t("providerKeys.title" as TK)} · ${current?.name ?? `#${providerId}`}`}
        subtitle={
          isClaudeCode
            ? t("providerKeys.claudeOAuthHint" as TK)
            : isGrokBuild
              ? t("providerKeys.grokBuildOAuthHint" as TK)
              : t("providerKeys.bulkPasteHint" as TK)
        }
        onRefresh={() => {
          keys.reload();
          provider.reload();
        }}
        action={
          <div style={{ display: "flex", gap: 8, alignItems: "flex-end" }}>
            <Button
              appearance={current?.enabled ? "primary" : "secondary"}
              onClick={toggleProvider}
            >
              {current?.enabled
                ? t("common.disable" as TK)
                : t("common.enable" as TK)}
            </Button>
            {supportsBalance ? (
            <div style={{ display: "flex", gap: 8, alignItems: "flex-end" }}>
              <Field label={t("providerKeys.rescanScope" as TK)}>
                <Dropdown
                  style={{ minWidth: 150 }}
                  selectedOptions={[scanPool]}
                  value={
                    scanPool === "__all__"
                      ? t("providerKeys.allPools" as TK)
                      : scanPool === "__untagged__"
                        ? "(untagged)"
                        : scanPool
                  }
                  onOptionSelect={(_, d) =>
                    setScanPool(d.optionValue ?? "__all__")
                  }
                >
                      <Option value="__all__" text={t("providerKeys.allPools" as TK)}>
                        {t("providerKeys.allPools" as TK)}
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
                {refreshingAll
                  ? t("providerKeys.rescanning" as TK)
                  : t("providerKeys.rescanBalances" as TK)}
              </Button>
            </div>
          ) : null}
          </div>
        }
      />

      {supportsOauth ? (
        <div style={{ marginBottom: 16, padding: 16, gap: 8, border: "1px solid var(--colorNeutralStroke1)", borderRadius: "10px", display: "flex", flexDirection: "column" }}>
          <Text weight="semibold" block>
            {isGrokBuild
              ? t("providerKeys.oauthTitleGrokBuild" as TK)
              : t("providerKeys.oauthTitleClaude" as TK)}
          </Text>
          <Text
            size={200}
            block
            style={{ color: tokens.colorNeutralForeground3 }}
          >
            {isGrokBuild
              ? t("providerKeys.oauthDescGrokBuild" as TK)
              : t("providerKeys.oauthDescClaude" as TK)}
          </Text>
          {oauthState === null ? (
            <Button
              appearance="primary"
              icon={<PersonRegular />}
              disabled={oauthBusy}
              onClick={startOAuth}
              style={{ alignSelf: "flex-start", marginTop: 4 }}
            >
              {t("providerKeys.oauthStart" as TK)}
            </Button>
          ) : (
            <>
              <Field
                label={
                  isGrokBuild
                    ? t("providerKeys.pasteGrokBuildCode" as TK)
                    : t("providerKeys.pasteClaudeCode" as TK)
                }
                style={{ marginTop: 4 }}
              >
                <Input
                  value={oauthCode}
                  placeholder={
                    isGrokBuild
                      ? t("providerKeys.oauthPlaceholderGrokBuild" as TK)
                      : t("providerKeys.oauthPlaceholderClaude" as TK)
                  }
                  onChange={(_, d) => setOauthCode(d.value)}
                />
              </Field>
              <div style={{ display: "flex", gap: 8 }}>
                <Button
                  appearance="primary"
                  disabled={oauthBusy || !oauthCode.trim()}
                  onClick={completeOAuth}
                >
                  {t("providerKeys.oauthComplete" as TK)}
                </Button>
                <Button
                  appearance="subtle"
                  disabled={oauthBusy}
                  onClick={() => {
                    setOauthState(null);
                    setOauthCode("");
                  }}
                >
                  {t("common.cancel" as TK)}
                </Button>
              </div>
            </>
          )}
        </div>
      ) : null}

      {/* Key Helper for Claude Code providers */}
      {isClaudeCode && (
        <details style={{ marginBottom: 8 }}>
          <summary style={{ cursor: "pointer", fontSize: tokens.fontSizeBase200, color: tokens.colorNeutralForeground2 }}>
            {t("providerKeys.addKeyHelper" as TK)}
          </summary>
          <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 8, paddingBottom: 8, borderBottom: `1px solid ${tokens.colorNeutralStroke2}` }}>
            <Field label={t("providerKeys.accessToken" as TK)}>
              <Input value={claudeAccessToken} onChange={(_, d) => setClaudeAccessToken(d.value)} />
            </Field>
            <Field label={t("providerKeys.refreshToken" as TK)}>
              <Input value={claudeRefreshToken} onChange={(_, d) => setClaudeRefreshToken(d.value)} />
            </Field>
            <Field label={t("providerKeys.expiresAt" as TK)} hint={t("providerKeys.expiresAtHint" as TK)}>
              <Input value={claudeExpiresAt} onChange={(_, d) => setClaudeExpiresAt(d.value)} placeholder="1735689600" />
            </Field>
            <Field label={t("providerKeys.commentOpt" as TK)}>
              <Input value={claudeComment} onChange={(_, d) => setClaudeComment(d.value)} />
            </Field>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <code style={{ flex: 1, fontSize: tokens.fontSizeBase100, color: tokens.colorNeutralForeground3, overflowX: "auto", whiteSpace: "nowrap" }}>
                {claudeAccessToken && claudeRefreshToken && claudeExpiresAt
                  ? `${claudeAccessToken}:${claudeRefreshToken}:${claudeExpiresAt}`
                  : claudeAccessToken
                    ? `{"access_token":"${claudeAccessToken.substring(0, 12)}..."...}`
                    : ""}
              </code>
              <Button
                appearance="subtle"
                size="small"
                disabled={adding || !claudeAccessToken}
                onClick={() => {
                  const at = claudeAccessToken.trim();
                  const rt = claudeRefreshToken.trim();
                  const ea = claudeExpiresAt.trim();
                  const comment = claudeComment.trim();
                  // Prefer colon-separated if all 3 fields provided (backend converts to bundle).
                  const entry = (at && rt && ea)
                    ? `${at}:${rt}:${ea}`
                    : (() => {
                        const b: Record<string, unknown> = { access_token: at };
                        if (rt) b.refresh_token = rt;
                        if (ea) b.expires_at = Number(ea);
                        return JSON.stringify(b);
                      })();
                  const line = comment ? `${entry} # ${comment}` : entry;
                  addHelperKey(line).then(() => {
                    setClaudeAccessToken("");
                    setClaudeRefreshToken("");
                    setClaudeExpiresAt("");
                    setClaudeComment("");
                  });
                }}
              >
                {t("providerKeys.addToPool" as TK)}
              </Button>
            </div>
          </div>
        </details>
      )}

      {/* Import auth files exported from sub2api / CLIProxyAPI / cpa */}
      {supportsImport && (
        <details style={{ marginBottom: 8 }}>
          <summary style={{ cursor: "pointer", fontSize: tokens.fontSizeBase200, color: tokens.colorNeutralForeground2 }}>
            {t("providerKeys.importTitle" as TK)}
          </summary>
          <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 8, paddingBottom: 8, borderBottom: `1px solid ${tokens.colorNeutralStroke2}` }}>
            <Text size={200} style={{ color: tokens.colorNeutralForeground3 }}>
              {t("providerKeys.importHint" as TK)}
            </Text>
            <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
              <input
                id="auth-import-file"
                type="file"
                multiple
                accept=".json,.jsonl,application/json"
                style={{ display: "none" }}
                onChange={(e) => setImportFiles(Array.from(e.target.files ?? []))}
              />
              <Button
                appearance="secondary"
                size="small"
                icon={<ArrowUploadRegular />}
                onClick={() => document.getElementById("auth-import-file")?.click()}
              >
                {t("providerKeys.importChooseFiles" as TK)}
              </Button>
              {importFiles.length > 0 && (
                <Text size={200} style={{ color: tokens.colorNeutralForeground3 }}>
                  {t("providerKeys.importFilesSelected" as TK, { count: importFiles.length })}
                </Text>
              )}
            </div>
            <Field label={t("providerKeys.importPasteLabel" as TK)}>
              <Textarea
                value={importPaste}
                onChange={(_, d) => setImportPaste(d.value)}
                placeholder={t("providerKeys.importPastePlaceholder" as TK)}
                resize="vertical"
                rows={4}
              />
            </Field>
            <div>
              <Button
                appearance="primary"
                size="small"
                disabled={importBusy || (importFiles.length === 0 && !importPaste.trim())}
                onClick={runImport}
              >
                {importBusy ? t("providerKeys.importing" as TK) : t("providerKeys.importButton" as TK)}
              </Button>
            </div>
          </div>
        </details>
      )}

      {/* Key Helper for Cloudflare providers */}
      {current?.type === "cloudflare" && (
        <details style={{ marginBottom: 8 }}>
          <summary style={{ cursor: "pointer", fontSize: tokens.fontSizeBase200, color: tokens.colorNeutralForeground2 }}>
            {t("providerKeys.addKeyHelper" as TK)}
          </summary>
          <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 8, paddingBottom: 8, borderBottom: `1px solid ${tokens.colorNeutralStroke2}` }}>
            <Field label={t("providerKeys.accountId" as TK)}>
              <Input value={cfAccountId} onChange={(_, d) => setCfAccountId(d.value)} />
            </Field>
            <Field label={t("providerKeys.apiToken" as TK)}>
              <Input type="text" autoComplete="off" value={cfToken} onChange={(_, d) => setCfToken(d.value)} />
            </Field>
            <Field label={t("providerKeys.commentOpt" as TK)}>
              <Input value={cfComment} onChange={(_, d) => setCfComment(d.value)} />
            </Field>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <code style={{ flex: 1, fontSize: tokens.fontSizeBase100, color: tokens.colorNeutralForeground3, overflowX: "auto", whiteSpace: "nowrap" }}>
                {cfAccountId && cfToken ? `${cfAccountId}@${cfToken}` : ""}
              </code>
              <Button
                appearance="subtle"
                size="small"
                disabled={adding || !cfAccountId || !cfToken}
                onClick={() => {
                  const entry = `${cfAccountId.trim()}@${cfToken.trim()}`;
                  const comment = cfComment.trim();
                  const line = comment ? `${entry} # ${comment}` : entry;
                  addHelperKey(line).then(() => {
                    setCfAccountId("");
                    setCfToken("");
                    setCfComment("");
                  });
                }}
              >
                {t("providerKeys.addToPool" as TK)}
              </Button>
            </div>
          </div>
        </details>
      )}

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
          label={t("providerKeys.keyPoolHint" as TK)}
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
          <Field label={t("providerKeys.rescanScope" as TK)}>
            <Dropdown
              style={{ minWidth: 150 }}
              selectedOptions={[cleanPool]}
              value={
                cleanPool === "__all__"
                  ? t("providerKeys.allPools" as TK)
                  : cleanPool === "__untagged__"
                    ? "(untagged)"
                    : cleanPool
              }
              onOptionSelect={(_, d) =>
                setCleanPool(d.optionValue ?? "__all__")
              }
            >
              <Option value="__all__" text={t("providerKeys.allPools" as TK)}>
                {t("providerKeys.allPools" as TK)}
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
          <Field label={t("providerKeys.noBalanceDays" as TK)}>
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
            content={t("providerKeys.noBalanceDaysHint" as TK)}
            relationship="label"
          >
            <Button
              appearance="secondary"
              icon={<DeleteRegular />}
              disabled={cleaning}
              onClick={() => cleanup("insufficient_balance")}
            >
              {t("providerKeys.clearNoBalance" as TK)}
            </Button>
          </Tooltip>
          <Tooltip
            content={t("providerKeys.deleteAllRejectedTip" as TK)}
            relationship="label"
          >
            <Button
              appearance="secondary"
              icon={<DeleteRegular />}
              disabled={cleaning}
              onClick={() => cleanup("invalid")}
            >
              {t("providerKeys.clearInvalid" as TK)}
            </Button>
          </Tooltip>
        </div>
      </div>
      <Button
        appearance="primary"
        disabled={adding || !bulk.trim()}
        onClick={addKeys}
        data-shortcut="apply"
        style={{ marginBottom: 24 }}
      >
        {t("providerKeys.add" as TK)}
      </Button>

      {keys.loading ? (
        <Loading />
      ) : keys.error ? (
        <ErrorText error={keys.error} />
      ) : (
        <DataTable ariaLabel={t("providerKeys.title" as TK)}>
          <TableHeader>
            <TableRow>
              {isStaff && (
                <TableHeaderCell style={{ width: 44 }}>
                  {t("providerKeys.order" as TK)}
                </TableHeaderCell>
              )}
              <TableHeaderCell>
                {t("providerKeys.key" as TK)}
              </TableHeaderCell>
              <TableHeaderCell>
                {t("providerKeys.comment" as TK)}
              </TableHeaderCell>
              <TableHeaderCell>
                {t("providerKeys.pool" as TK)}
              </TableHeaderCell>
              <TableHeaderCell>
                {t("providerKeys.addedBy" as TK)}
              </TableHeaderCell>
              <TableHeaderCell>
                {t("providerKeys.status" as TK)}
              </TableHeaderCell>
              {supportsBalance && (
                <TableHeaderCell>
                  {t("providerKeys.balance" as TK)}
                </TableHeaderCell>
              )}
              <TableHeaderCell>
                {t("providerKeys.fails" as TK)}
              </TableHeaderCell>
              <TableHeaderCell>
                {t("providerKeys.requests" as TK)}
              </TableHeaderCell>
              <TableHeaderCell>
                {t("providerKeys.lastUsed" as TK)}
              </TableHeaderCell>
              <TableHeaderCell>
                {t("providerKeys.reason" as TK)}
              </TableHeaderCell>
              <TableHeaderCell>
                {t("providerKeys.actions" as TK)}
              </TableHeaderCell>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((k, idx) => (
              <TableRow
                key={k.id}
                onDragOver={(e) => {
                  if (isStaff && dragId != null) {
                    e.preventDefault();
                    setDragOverIdx(idx);
                  }
                }}
                onDragLeave={() => setDragOverIdx(null)}
                onDrop={() => {
                  setDragOverIdx(null);
                  if (isStaff) onDropRow(k.id);
                }}
                style={{
                  ...(dragId === k.id ? { opacity: 0.4 } : undefined),
                  ...(dragId != null && dragOverIdx === idx
                    ? { borderTop: `2px solid ${tokens.colorBrandForeground1}` }
                    : undefined),
                }}
              >
                {isStaff && (
                  <TableCell style={{ width: 44 }}>
                    <Menu>
                      <MenuTrigger disableButtonEnhancement>
                        <Button
                          size="small"
                          appearance="subtle"
                          disabled={reordering}
                          icon={<ReOrderDotsVerticalRegular />}
                          draggable
                          onDragStart={(e) => {
                            setDragId(k.id);
                            e.dataTransfer.effectAllowed = "move";
                          }}
                          onDragEnd={() => setDragId(null)}
                          style={{ cursor: "grab" }}
                          title={t("providerKeys.dragHint" as TK)}
                        />
                      </MenuTrigger>
                      <MenuPopover>
                        <MenuList>
                          <MenuItem
                            icon={<ArrowUploadRegular />}
                            onClick={() => moveKey(k.id, "top")}
                          >
                            {t("providerKeys.moveTop" as TK)}
                          </MenuItem>
                          <MenuItem
                            icon={<ArrowDownloadRegular />}
                            onClick={() => moveKey(k.id, "bottom")}
                          >
                            {t("providerKeys.moveBottom" as TK)}
                          </MenuItem>
                        </MenuList>
                      </MenuPopover>
                    </Menu>
                  </TableCell>
                )}
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
                        content={t("providerKeys.refreshBalanceTip" as TK)}
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
                  {k.status === "rate_limited" && k.rate_limit_until ? (
                    <div style={{ fontSize: tokens.fontSizeBase100 }}>
                      {t("providerKeys.retryAt" as TK)}: {formatDate(k.rate_limit_until)}
                    </div>
                  ) : null}
                </TableCell>
                <TableCell>
                  {isOwner && (
                    <Tooltip content={t("common.reveal" as TK)} relationship="label">
                      <Button
                        size="small"
                        appearance="subtle"
                        icon={<EyeRegular />}
                        disabled={revealBusy}
                        onClick={() => reveal(k)}
                        aria-label={t("common.reveal" as TK)}
                      />
                    </Tooltip>
                  )}
                  {canManage(k) ? (
                    <>
                      <Tooltip content={t("common.edit" as TK)} relationship="label">
                        <Button
                          size="small"
                          appearance="subtle"
                          icon={<EditRegular />}
                          onClick={() => openEdit(k)}
                          aria-label={t("common.edit" as TK)}
                        />
                      </Tooltip>
                      {supportsRefresh && (
                        <Tooltip
                          content={t("providerKeys.refreshTokenTip" as TK)}
                          relationship="label"
                        >
                          <Button
                            size="small"
                            appearance="subtle"
                            icon={<KeyResetRegular />}
                            disabled={refreshingTokenId === k.id}
                            onClick={() => refreshToken(k)}
                            aria-label={t("providerKeys.refreshTokenAction" as TK)}
                          />
                        </Tooltip>
                      )}
                      <Tooltip
                        content={
                          k.status === "active"
                            ? t("common.disable" as TK)
                            : t("common.enable" as TK)
                        }
                        relationship="label"
                      >
                        <Button
                          size="small"
                          appearance="subtle"
                          icon={
                            k.status === "active" ? (
                              <ProhibitedRegular />
                            ) : (
                              <CheckmarkCircleRegular />
                            )
                          }
                          onClick={() => toggle(k)}
                          aria-label={
                            k.status === "active"
                              ? t("common.disable" as TK)
                              : t("common.enable" as TK)
                          }
                        />
                      </Tooltip>
                      <Tooltip content={t("common.delete" as TK)} relationship="label">
                        <Button
                          size="small"
                          appearance="subtle"
                          icon={<DeleteRegular />}
                          onClick={() => remove(k)}
                          aria-label={t("common.delete" as TK)}
                        />
                      </Tooltip>
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
            <DialogTitle>
              {t("providerKeys.editKeyTitle" as TK).replace("{preview}", editing?.key_preview ?? "")}
            </DialogTitle>
            <DialogContent
              style={{ display: "flex", flexDirection: "column", gap: 12 }}
            >
              {editIsBundle ? (
                <>
                  {renderRevealField(
                    "access_token",
                    t("providerKeys.accessToken" as TK),
                    editAccessToken,
                    setEditAccessToken,
                    { hint: t("providerKeys.accessTokenHint" as TK) },
                  )}
                  {renderRevealField(
                    "refresh_token",
                    t("providerKeys.refreshToken" as TK),
                    editRefreshToken,
                    setEditRefreshToken,
                    { hint: t("providerKeys.refreshTokenHint" as TK) },
                  )}
                  <Field
                    label={t("providerKeys.expiresAt" as TK)}
                    hint={t("providerKeys.expiresAtEditHint" as TK)}
                  >
                    <Input
                      value={editExpiresAt}
                      placeholder="Unix timestamp"
                      onChange={(_, d) => setEditExpiresAt(d.value)}
                    />
                  </Field>
                </>
              ) : editIsCloudflare ? (
                <>
                  {renderRevealField(
                    "cf_account_id",
                    t("providerKeys.accountId" as TK),
                    editCfAccountId,
                    setEditCfAccountId,
                    { placeholder: t("providerKeys.editKeyHint" as TK) },
                  )}
                  {renderRevealField(
                    "cf_token",
                    t("providerKeys.apiToken" as TK),
                    editCfToken,
                    setEditCfToken,
                  )}
                </>
              ) : (
                renderRevealField(
                  "key",
                  t("providerKeys.editKeyField" as TK),
                  editSecret,
                  setEditSecret,
                  { hint: t("providerKeys.editKeyHint" as TK) },
                )
              )}
              <Field label={t("providerKeys.comment" as TK)}>
                <Input
                  value={editNote}
                  placeholder="(none)"
                  onChange={(_, d) => setEditNote(d.value)}
                />
              </Field>
              <Field label={t("providerKeys.pool" as TK)}>
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
                {t("common.cancel" as TK)}
              </Button>
              <Button
                appearance="primary"
                disabled={editBusy}
                onClick={saveEdit}
                data-shortcut="save"
              >
                {t("common.save" as TK)}
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
            <DialogTitle>
              {t("providerKeys.keyDetailTitle" as TK).replace("{preview}", revealed?.preview ?? "")}
            </DialogTitle>
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
                {t("common.close" as TK)}
              </Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </div>
  );
}
