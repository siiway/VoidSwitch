import {
  Badge,
  Button,
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
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
import { AddRegular, CopyRegular, DeleteRegular } from "@fluentui/react-icons";
import { useState } from "react";
import { api } from "../api/client";
import type { VoidToken, VoidTokenWithSecret } from "../api/types";
import {
  DataTable,
  ErrorText,
  Loading,
  PageHeader,
  formatDate,
  useAsync,
  useConfirm,
  useNotify,
} from "../components/ui";

export function Tokens() {
  const notify = useNotify();
  const confirm = useConfirm();
  const list = useAsync<VoidToken[]>(() => api.get("/api/admin/tokens"));
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("default");
  const [allowed, setAllowed] = useState("");
  const [userId, setUserId] = useState("");
  const [secret, setSecret] = useState<VoidTokenWithSecret | null>(null);

  async function create() {
    const allowed_models = allowed
      .split(/[\n,]/)
      .map((s) => s.trim())
      .filter(Boolean);
    try {
      const created = await api.post<VoidTokenWithSecret>("/api/admin/tokens", {
        name,
        allowed_models,
        user_id: userId ? Number(userId) : undefined,
      });
      setSecret(created);
      setCreating(false);
      setName("default");
      setAllowed("");
      setUserId("");
      list.reload();
    } catch (e) {
      notify(
        "Create failed",
        e instanceof Error ? e.message : String(e),
        "error",
      );
    }
  }

  async function toggle(t: VoidToken) {
    await api.patch(`/api/admin/tokens/${t.id}`, { enabled: !t.enabled });
    list.reload();
  }

  async function remove(t: VoidToken) {
    const ok = await confirm({
      title: "Delete token",
      message: `Delete token "${t.name}"? Clients using it will stop working.`,
      confirmLabel: "Delete",
      tone: "danger",
    });
    if (!ok) return;
    await api.del(`/api/admin/tokens/${t.id}`);
    list.reload();
  }

  return (
    <div>
      <PageHeader
        title="Void-Tokens"
        subtitle="Client credentials for the gateway, across all users"
        action={
          <Button
            appearance="primary"
            icon={<AddRegular />}
            onClick={() => setCreating(true)}
          >
            Mint token
          </Button>
        }
      />

      {list.loading ? (
        <Loading />
      ) : list.error ? (
        <ErrorText error={list.error} />
      ) : (
        <DataTable ariaLabel="Tokens">
          <TableHeader>
            <TableRow>
              <TableHeaderCell>Name</TableHeaderCell>
              <TableHeaderCell>Fingerprint</TableHeaderCell>
              <TableHeaderCell>User</TableHeaderCell>
              <TableHeaderCell>Requests</TableHeaderCell>
              <TableHeaderCell>Tokens</TableHeaderCell>
              <TableHeaderCell>Status</TableHeaderCell>
              <TableHeaderCell>Created</TableHeaderCell>
              <TableHeaderCell>Actions</TableHeaderCell>
            </TableRow>
          </TableHeader>
          <TableBody>
            {(list.data ?? []).map((t) => (
              <TableRow key={t.id}>
                <TableCell>{t.name}</TableCell>
                <TableCell style={{ fontFamily: "monospace" }}>
                  {t.token_prefix}
                </TableCell>
                <TableCell>{t.user_id}</TableCell>
                <TableCell>{t.total_requests}</TableCell>
                <TableCell>{t.total_tokens}</TableCell>
                <TableCell>
                  <Badge
                    color={t.enabled ? "success" : "subtle"}
                    appearance="filled"
                  >
                    {t.enabled ? "enabled" : "disabled"}
                  </Badge>
                </TableCell>
                <TableCell style={{ color: tokens.colorNeutralForeground3 }}>
                  {formatDate(t.created_at)}
                </TableCell>
                <TableCell>
                  <Button
                    size="small"
                    appearance="subtle"
                    onClick={() => toggle(t)}
                  >
                    {t.enabled ? "Disable" : "Enable"}
                  </Button>
                  <Button
                    size="small"
                    appearance="subtle"
                    icon={<DeleteRegular />}
                    onClick={() => remove(t)}
                  />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </DataTable>
      )}

      <Dialog open={creating} onOpenChange={(_, d) => setCreating(d.open)}>
        <DialogSurface>
          <DialogBody>
            <DialogTitle>Mint Void-Token</DialogTitle>
            <DialogContent
              style={{ display: "flex", flexDirection: "column", gap: 12 }}
            >
              <Field label="Name">
                <Input value={name} onChange={(_, d) => setName(d.value)} />
              </Field>
              <Field label="User ID (blank = yourself)">
                <Input value={userId} onChange={(_, d) => setUserId(d.value)} />
              </Field>
              <Field label="Allowed models (blank = all; one per line)">
                <Textarea
                  value={allowed}
                  rows={3}
                  onChange={(_, d) => setAllowed(d.value)}
                />
              </Field>
            </DialogContent>
            <DialogActions>
              <Button appearance="secondary" onClick={() => setCreating(false)}>
                Cancel
              </Button>
              <Button appearance="primary" onClick={create}>
                Create
              </Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>

      <SecretDialog secret={secret} onClose={() => setSecret(null)} />
    </div>
  );
}

export function SecretDialog({
  secret,
  onClose,
}: {
  secret: VoidTokenWithSecret | null;
  onClose: () => void;
}) {
  const notify = useNotify();
  return (
    <Dialog
      open={secret !== null}
      onOpenChange={(_, d) => !d.open && onClose()}
    >
      <DialogSurface>
        <DialogBody>
          <DialogTitle>Your new API key</DialogTitle>
          <DialogContent>
            <Text
              block
              style={{ color: tokens.colorNeutralForeground3, marginBottom: 8 }}
            >
              Copy it now — it will not be shown again.
            </Text>
            <div
              style={{
                display: "flex",
                gap: 8,
                alignItems: "center",
                background: tokens.colorNeutralBackground3,
                padding: 12,
                borderRadius: 6,
                wordBreak: "break-all",
              }}
            >
              <Text font="monospace" style={{ flex: 1 }}>
                {secret?.token}
              </Text>
              <Button
                icon={<CopyRegular />}
                onClick={() => {
                  if (secret) {
                    void navigator.clipboard.writeText(secret.token);
                    notify("Copied", undefined, "success");
                  }
                }}
              />
            </div>
          </DialogContent>
          <DialogActions>
            <Button appearance="primary" onClick={onClose}>
              Done
            </Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}
