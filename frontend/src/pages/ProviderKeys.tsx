import {
  Button,
  Card,
  Field,
  Input,
  TableBody,
  TableCell,
  TableHeader,
  TableHeaderCell,
  TableRow,
  Text,
  Textarea,
  tokens,
} from "@fluentui/react-components";
import {
  ArrowLeftRegular,
  DeleteRegular,
  PersonRegular,
} from "@fluentui/react-icons";
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
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

export function ProviderKeys() {
  const { id } = useParams();
  const providerId = Number(id);
  const navigate = useNavigate();
  const notify = useNotify();
  const confirm = useConfirm();
  const provider = useAsync<Provider[]>(() => api.get("/api/admin/providers"));
  const keys = useAsync<ApiKey[]>(
    () => api.get(`/api/admin/providers/${providerId}/keys`),
    [providerId],
  );
  const [bulk, setBulk] = useState("");
  const [adding, setAdding] = useState(false);

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
        { keys: list },
      );
      notify("Keys added", `${created.length} new key(s)`, "success");
      setBulk("");
      keys.reload();
    } catch (e) {
      notify("Add failed", e instanceof Error ? e.message : String(e), "error");
    } finally {
      setAdding(false);
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
            : "Paste one API key per line to add in bulk"
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
              : "sk-...\nsk-...\nsk-..."
          }
          onChange={(_, d) => setBulk(d.value)}
        />
      </Field>
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
              <TableHeaderCell>Status</TableHeaderCell>
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
                <TableCell>
                  <StatusBadge status={k.status} />
                </TableCell>
                <TableCell>{k.failed_count}</TableCell>
                <TableCell>{k.total_requests}</TableCell>
                <TableCell style={{ color: tokens.colorNeutralForeground3 }}>
                  {formatDate(k.last_used_at)}
                </TableCell>
                <TableCell style={{ color: tokens.colorNeutralForeground3 }}>
                  {k.disabled_reason ?? "—"}
                </TableCell>
                <TableCell>
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
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </DataTable>
      )}
    </div>
  );
}
