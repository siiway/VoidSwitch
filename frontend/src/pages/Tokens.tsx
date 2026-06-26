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
import { useTranslation } from "react-i18next";
import type { Translations } from "../i18n/locales/en";
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
  const { t: tr } = useTranslation();
  type TK = keyof Translations;
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
        tr("tokens.mintFailed" as TK),
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
      title: tr("tokens.deleteTitle" as TK),
      message: tr("tokens.deleteMsg" as TK).replace("{name}", t.name),
      confirmLabel: tr("common.delete" as TK),
      tone: "danger",
    });
    if (!ok) return;
    await api.del(`/api/admin/tokens/${t.id}`);
    list.reload();
  }

  return (
    <div>
      <PageHeader
        title={tr("tokens.title" as TK)}
        subtitle={tr("tokens.subtitle" as TK)}
        onRefresh={list.reload}
        action={
          <Button
            appearance="primary"
            icon={<AddRegular />}
            onClick={() => setCreating(true)}
          >
            {tr("tokens.mint" as TK)}
          </Button>
        }
      />

      {list.loading ? (
        <Loading />
      ) : list.error ? (
        <ErrorText error={list.error} />
      ) : (
        <DataTable ariaLabel={tr("tokens.title" as TK)}>
          <TableHeader>
            <TableRow>
              <TableHeaderCell>{tr("tokens.name" as TK)}</TableHeaderCell>
              <TableHeaderCell>{tr("tokens.fingerprint" as TK)}</TableHeaderCell>
              <TableHeaderCell>{tr("tokens.user" as TK)}</TableHeaderCell>
              <TableHeaderCell>{tr("tokens.requests" as TK)}</TableHeaderCell>
              <TableHeaderCell>{tr("tokens.tokens" as TK)}</TableHeaderCell>
              <TableHeaderCell>{tr("tokens.status" as TK)}</TableHeaderCell>
              <TableHeaderCell>{tr("tokens.created" as TK)}</TableHeaderCell>
              <TableHeaderCell>{tr("tokens.actions" as TK)}</TableHeaderCell>
            </TableRow>
          </TableHeader>
          <TableBody>
            {(list.data ?? []).map((t) => (
              <TableRow key={t.id}>
                <TableCell>{t.name}</TableCell>
                <TableCell style={{ fontFamily: "monospace" }}>
                  {t.token_prefix}
                </TableCell>
                <TableCell>{t.username ?? `#${t.user_id}`}</TableCell>
                <TableCell>{t.total_requests}</TableCell>
                <TableCell>{t.total_tokens}</TableCell>
                <TableCell>
                  <Badge
                    color={t.enabled ? "success" : "subtle"}
                    appearance="filled"
                  >
                    {t.enabled
                      ? tr("common.enabled" as TK)
                      : tr("common.disabled" as TK)}
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
                    {t.enabled
                      ? tr("common.disable" as TK)
                      : tr("common.enable" as TK)}
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
            <DialogTitle>{tr("tokens.mintTitle" as TK)}</DialogTitle>
            <DialogContent
              style={{ display: "flex", flexDirection: "column", gap: 12 }}
            >
              <Field label={tr("tokens.mintName" as TK)}>
                <Input
                  placeholder={tr("tokens.mintNamePlaceholder" as TK)}
                  value={name}
                  onChange={(_, d) => setName(d.value)}
                />
              </Field>
              <Field label={tr("tokens.userIdHint" as TK)}>
                <Input value={userId} onChange={(_, d) => setUserId(d.value)} />
              </Field>
              <Field label={tr("tokens.allowedModelsHint" as TK)}>
                <Textarea
                  value={allowed}
                  rows={3}
                  onChange={(_, d) => setAllowed(d.value)}
                />
              </Field>
            </DialogContent>
            <DialogActions>
              <Button appearance="secondary" onClick={() => setCreating(false)}>
                {tr("common.cancel" as TK)}
              </Button>
              <Button appearance="primary" onClick={create}>
                {tr("common.create" as TK)}
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
  const { t: tr } = useTranslation();
  type TK = keyof Translations;
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
              {tr("tokens.secretWarning" as TK)}
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
                    notify(tr("tokens.copied" as TK), undefined, "success");
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
