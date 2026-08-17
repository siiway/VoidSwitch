import {
  Button,
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  Divider,
  Field,
  Input,
  Tab,
  TabList,
  TableBody,
  TableCell,
  TableHeader,
  TableHeaderCell,
  TableRow,
  Text,
  Tooltip,
  tokens,
} from "@fluentui/react-components";
import {
  AddRegular,
  ArrowSyncRegular,
  BugRegular,
  CheckmarkCircleRegular,
  CheckmarkRegular,
  CopyRegular,
  DeleteRegular,
  EditRegular,
  ProhibitedRegular,
} from "@fluentui/react-icons";
import { useState } from "react";
import { useTranslation, Trans } from "react-i18next";
import type { Translations } from "../i18n/locales/en";
import { api, API_BASE } from "../api/client";
import type { ModelEntry, VoidToken, VoidTokenWithSecret } from "../api/types";
import {
  ErrorText,
  DataTable,
  Loading,
  PageHeader,
  formatDate,
  useAsync,
  useConfirm,
  useNotify,
} from "../components/ui";
import { buildOpencodeConfig, type ModelInfo } from "../lib/opencodeConfig";
import { SecretDialog } from "./Tokens";

interface Usage {
  requests: number;
  tokens: number;
  token_count: number;
}

// Client snippets — `vs-…` is the placeholder for a token minted below.
const OPENAI_SNIPPET = `export OPENAI_BASE_URL=${API_BASE}/v1
export OPENAI_API_KEY=vs-...`;

const CLAUDE_SNIPPET = `export ANTHROPIC_BASE_URL=${API_BASE}
export ANTHROPIC_AUTH_TOKEN=vs-...`;

/** A monospace code block with a one-click copy button. */
function CodeBlock({ code }: { code: string }) {
  const { t } = useTranslation();
  type TK = keyof Translations;
  const notify = useNotify();
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      notify(
        t("chat.copyFailed" as TK),
        t("myToken.clipboardUnavailable" as TK),
        "error",
      );
    }
  }

  return (
    <div style={{ position: "relative" }}>
      <Button
        size="small"
        appearance="subtle"
        icon={copied ? <CheckmarkRegular /> : <CopyRegular />}
        onClick={copy}
        aria-label={t("myToken.copyToClipboard" as TK)}
        style={{ position: "absolute", top: 6, right: 6, zIndex: 1 }}
      />
      <pre
        style={{
          margin: 0,
          background: tokens.colorNeutralBackground3,
          color: tokens.colorNeutralForeground1,
          padding: 12,
          paddingRight: 44,
          borderRadius: 6,
          overflowX: "auto",
          whiteSpace: "pre",
          fontFamily: tokens.fontFamilyMonospace,
          fontSize: tokens.fontSizeBase200,
          lineHeight: tokens.lineHeightBase200,
        }}
      >
        {code}
      </pre>
    </div>
  );
}

export function MyToken() {
  const notify = useNotify();
  const confirm = useConfirm();
  const { t, i18n } = useTranslation();
  type TK = keyof Translations;
  // Public docs site (English lives under /en/); track the dashboard language.
  const docsBase =
    i18n.language === "en"
      ? "https://voidswitch.siiway.page/en"
      : "https://voidswitch.siiway.page";
  const tokensList = useAsync<VoidToken[]>(() => api.get("/api/me/tokens"));
  const usage = useAsync<Usage>(() => api.get("/api/me/usage"));
  const [name, setName] = useState("default");
  const [secret, setSecret] = useState<VoidTokenWithSecret | null>(null);
  const [client, setClient] = useState("openai");
  const [editing, setEditing] = useState<VoidToken | null>(null);
  const [editName, setEditName] = useState("");

  // The manual (no-script) OpenCode config is only built once the user expands
  // that section, and the catalog + defaults are fetched fresh from the API each
  // time it's opened so the snippet always reflects the latest synced models.
  const [manual, setManual] = useState<{
    loading: boolean;
    error?: string;
    config?: string;
  }>({ loading: false });

  async function loadManualConfig() {
    setManual({ loading: true });
    try {
      const [cfg, catalog] = await Promise.all([
        api.get<{
          opencode_default_model?: string;
          opencode_small_model?: string;
        }>("/api/auth/config"),
        api.get<ModelEntry[]>("/api/models"),
      ]);
      const infos: ModelInfo[] = catalog
        .filter((m) => m.enabled)
        .map((m) => ({
          id: m.model_id,
          display_name: m.display_name ?? undefined,
          description: m.description ?? undefined,
          opencode:
            m.opencode_config && Object.keys(m.opencode_config).length
              ? m.opencode_config
              : undefined,
        }));
      const config = buildOpencodeConfig(
        cfg.opencode_default_model || "claude-opus-4-8",
        cfg.opencode_small_model || "",
        infos,
        API_BASE,
      );
      setManual({ loading: false, config });
    } catch (e) {
      setManual({
        loading: false,
        error: e instanceof Error ? e.message : String(e),
      });
    }
  }

  async function create() {
    try {
      const created = await api.post<VoidTokenWithSecret>("/api/me/tokens", {
        name,
      });
      setSecret(created);
      setName("default");
      tokensList.reload();
      usage.reload();
    } catch (e) {
      notify(
        t("myToken.createFailed" as TK),
        e instanceof Error ? e.message : String(e),
        "error",
      );
    }
  }

  async function rotate(token: VoidToken) {
    const ok = await confirm({
      title: t("myToken.rotateTitle" as TK),
      message: t("myToken.rotateMsg" as TK).replace("{name}", token.name),
      confirmLabel: t("myToken.rotate" as TK),
      tone: "danger",
    });
    if (!ok) return;
    try {
      const rotated = await api.post<VoidTokenWithSecret>(
        `/api/me/tokens/${token.id}/rotate`,
      );
      setSecret(rotated);
      tokensList.reload();
    } catch (e) {
      notify(
        t("common.updateFailed" as TK),
        e instanceof Error ? e.message : String(e),
        "error",
      );
    }
  }

  async function remove(token: VoidToken) {
    const ok = await confirm({
      title: t("myToken.deleteTitle" as TK),
      message: t("myToken.deleteMsg" as TK).replace("{name}", token.name),
      confirmLabel: t("common.delete" as TK),
      tone: "danger",
    });
    if (!ok) return;
    try {
      await api.del(`/api/me/tokens/${token.id}`);
      tokensList.reload();
      usage.reload();
    } catch (e) {
      notify(
        t("common.deleteFailed" as TK),
        e instanceof Error ? e.message : String(e),
        "error",
      );
    }
  }

  async function toggleDebug(token: VoidToken) {
    try {
      await api.patch(`/api/me/tokens/${token.id}`, { debug_enabled: !token.debug_enabled });
      tokensList.reload();
    } catch (e) {
      notify(
        t("common.updateFailed" as TK),
        e instanceof Error ? e.message : String(e),
        "error",
      );
    }
  }

  async function toggleEnabled(token: VoidToken) {
    try {
      await api.patch(`/api/me/tokens/${token.id}`, { enabled: !token.enabled });
      tokensList.reload();
    } catch (e) {
      notify(
        t("common.updateFailed" as TK),
        e instanceof Error ? e.message : String(e),
        "error",
      );
    }
  }

  function openEdit(token: VoidToken) {
    setEditing(token);
    setEditName(token.name);
  }

  async function saveEdit() {
    if (!editing) return;
    try {
      await api.patch(`/api/me/tokens/${editing.id}`, { name: editName.trim() || "default" });
      setEditing(null);
      tokensList.reload();
    } catch (e) {
      notify(
        t("common.updateFailed" as TK),
        e instanceof Error ? e.message : String(e),
        "error",
      );
    }
  }

  return (
    <div>
      <PageHeader
        title={t("myToken.title" as TK)}
        subtitle={t("myToken.subtitle" as TK)}
        onRefresh={() => {
          tokensList.reload();
          usage.reload();
        }}
      />

      <div style={{ padding: 16, marginBottom: 20, border: "1px solid var(--colorNeutralStroke1)", borderRadius: "10px" }}>
        <Text weight="semibold" block style={{ marginBottom: 2 }}>
          {t("myToken.connect" as TK)}
        </Text>
        <Text
          size={200}
          block
          style={{ color: tokens.colorNeutralForeground3, marginBottom: 8 }}
        >
          <Trans
            i18nKey="myToken.connectDesc"
            components={{ code: <code /> }}
          />
        </Text>

        <TabList
          selectedValue={client}
          onTabSelect={(_, d) => setClient(d.value as string)}
          style={{ marginBottom: 12 }}
        >
          <Tab value="openai">{t("myToken.openaiSdk" as TK)}</Tab>
          <Tab value="claude">{t("myToken.claudeCode" as TK)}</Tab>
          <Tab value="opencode">{t("myToken.opencode" as TK)}</Tab>
        </TabList>

        {client === "openai" ? <CodeBlock code={OPENAI_SNIPPET} /> : null}
        {client === "claude" ? <CodeBlock code={CLAUDE_SNIPPET} /> : null}
        {client === "opencode" ? (
          <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            <Text
              size={200}
              block
              style={{ color: tokens.colorNeutralForeground3 }}
            >
              <Trans
                i18nKey="myToken.opencodeDesc"
                components={{ code: <code /> }}
              />
            </Text>
            <div>
              <Text
                size={200}
                weight="semibold"
                block
                style={{ marginBottom: 4 }}
              >
                {t("myToken.macosLinux" as TK)}
              </Text>
              <CodeBlock code={`curl -fsSL ${API_BASE}/install | bash`} />
            </div>
            <div>
              <Text
                size={200}
                weight="semibold"
                block
                style={{ marginBottom: 4 }}
              >
                {t("myToken.windowsPs" as TK)}
              </Text>
              <CodeBlock code={`irm ${API_BASE}/install | iex`} />
            </div>
            <Text
              size={200}
              block
              style={{ color: tokens.colorNeutralForeground3 }}
            >
              <Trans
                i18nKey="myToken.opencodeAfter"
                components={{
                  code: <code />,
                  strong: <strong />,
                }}
              />
            </Text>

            <Divider />

            <details
              onToggle={(e) => {
                // Fetch + build the config fresh every time it's opened so it
                // always reflects the latest synced models.
                if ((e.currentTarget as HTMLDetailsElement).open) {
                  void loadManualConfig();
                }
              }}
            >
              <summary
                style={{
                  cursor: "pointer",
                  fontSize: tokens.fontSizeBase200,
                  color: tokens.colorNeutralForeground2,
                }}
              >
                {t("myToken.manual" as TK)}
              </summary>
              <div
                style={{
                  display: "flex",
                  flexDirection: "column",
                  gap: 10,
                  marginTop: 10,
                }}
              >
                <Text
                  size={200}
                  block
                  style={{ color: tokens.colorNeutralForeground3 }}
                >
                  <Trans
                    i18nKey="myToken.manualIntro"
                    components={{ code: <code /> }}
                  />
                </Text>
                {manual.loading ? (
                  <Loading />
                ) : manual.error ? (
                  <ErrorText error={manual.error} />
                ) : manual.config ? (
                  <CodeBlock code={manual.config} />
                ) : null}
                <div
                  style={{ display: "flex", flexDirection: "column", gap: 4 }}
                >
                  <Text
                    size={200}
                    block
                    style={{ color: tokens.colorNeutralForeground3 }}
                  >
                    <Trans i18nKey="myToken.manualStep1" components={{ code: <code /> }} />
                  </Text>
                  <Text
                    size={200}
                    block
                    style={{ color: tokens.colorNeutralForeground3 }}
                  >
                    <Trans
                      i18nKey="myToken.manualStep2"
                      components={{ code: <code />, strong: <strong /> }}
                    />
                  </Text>
                  <Text
                    size={200}
                    block
                    style={{ color: tokens.colorNeutralForeground3 }}
                  >
                    <Trans
                      i18nKey="myToken.manualStep3"
                      components={{ code: <code />, em: <em /> }}
                    />
                  </Text>
                </div>

                <Divider />

                <Text size={200} weight="semibold" block>
                  {t("myToken.pluginTitle" as TK)}
                </Text>
                <Text
                  size={200}
                  block
                  style={{ color: tokens.colorNeutralForeground3 }}
                >
                  <Trans
                    i18nKey="myToken.pluginIntro"
                    components={{ code: <code />, strong: <strong /> }}
                  />
                </Text>
                <Text
                  size={200}
                  block
                  style={{ color: tokens.colorNeutralForeground3 }}
                >
                  <Trans
                    i18nKey="myToken.pluginNote"
                    components={{
                      code: <code />,
                      strong: <strong />,
                      docs: <a href={`${docsBase}/guide/opencode`} target="_blank" rel="noreferrer" />,
                    }}
                  />
                </Text>
              </div>
            </details>
          </div>
        ) : null}
      </div>

      {usage.data ? (
        <div style={{ display: "flex", gap: 12, marginBottom: 20 }}>
          <div style={{ padding: 14, flex: 1, border: "1px solid var(--colorNeutralStroke2)", borderRadius: "10px" }}>
            <Text
              size={200}
              style={{ color: tokens.colorNeutralForeground3 }}
              block
            >
              Total requests
            </Text>
            <Text size={700} weight="bold">
              {usage.data.requests}
            </Text>
          </div>
          <div style={{ padding: 14, flex: 1, border: "1px solid var(--colorNeutralStroke2)", borderRadius: "10px" }}>
            <Text
              size={200}
              style={{ color: tokens.colorNeutralForeground3 }}
              block
            >
              Total tokens
            </Text>
            <Text size={700} weight="bold">
              {usage.data.tokens}
            </Text>
          </div>
        </div>
      ) : null}

      <div
        style={{
          display: "flex",
          gap: 8,
          alignItems: "flex-end",
          marginBottom: 20,
        }}
      >
        <Field label={t("myToken.newTokenName" as TK)} style={{ flex: "0 0 240px" }}>
          <Input value={name} onChange={(_, d) => setName(d.value)} />
        </Field>
        <Button appearance="primary" icon={<AddRegular />} onClick={create}>
          {t("myToken.createToken" as TK)}
        </Button>
      </div>

      {tokensList.loading ? (
        <Loading />
      ) : tokensList.error ? (
        <ErrorText error={tokensList.error} />
      ) : (
        <DataTable ariaLabel={t("myToken.title" as TK)}>
          <TableHeader>
            <TableRow>
              <TableHeaderCell>{t("myToken.name" as TK)}</TableHeaderCell>
              <TableHeaderCell>{t("myToken.fingerprint" as TK)}</TableHeaderCell>
              <TableHeaderCell>{t("myToken.requests" as TK)}</TableHeaderCell>
              <TableHeaderCell>{t("myToken.tokens" as TK)}</TableHeaderCell>
              <TableHeaderCell>{t("tokens.status" as TK)}</TableHeaderCell>
              <TableHeaderCell>{t("myToken.lastUsed" as TK)}</TableHeaderCell>
              <TableHeaderCell>{t("myToken.actions" as TK)}</TableHeaderCell>
            </TableRow>
          </TableHeader>
          <TableBody>
            {(tokensList.data ?? []).map((token) => (
              <TableRow key={token.id}>
                <TableCell>{token.name}</TableCell>
                <TableCell style={{ fontFamily: "monospace" }}>
                  {token.token_prefix}
                </TableCell>
                <TableCell>{token.total_requests}</TableCell>
                <TableCell>{token.total_tokens}</TableCell>
                <TableCell>
                  {token.enabled ? t("common.enabled" as TK) : t("common.disabled" as TK)}
                </TableCell>
                <TableCell style={{ color: tokens.colorNeutralForeground3 }}>
                  {formatDate(token.last_used_at)}
                </TableCell>
                <TableCell>
                  <Tooltip content={t("common.edit" as TK)} relationship="label">
                    <Button
                      size="small"
                      appearance="subtle"
                      icon={<EditRegular />}
                      onClick={() => openEdit(token)}
                      aria-label={t("common.edit" as TK)}
                    />
                  </Tooltip>
                  <Tooltip content={token.enabled ? t("common.disable" as TK) : t("common.enable" as TK)} relationship="label">
                    <Button
                      size="small"
                      appearance="subtle"
                      icon={token.enabled ? <ProhibitedRegular /> : <CheckmarkCircleRegular />}
                      onClick={() => toggleEnabled(token)}
                      aria-label={token.enabled ? t("common.disable" as TK) : t("common.enable" as TK)}
                    />
                  </Tooltip>
                  <Tooltip content={t("myToken.rotate" as TK)} relationship="label">
                    <Button
                      size="small"
                      appearance="subtle"
                      icon={<ArrowSyncRegular />}
                      onClick={() => rotate(token)}
                      aria-label={t("myToken.rotate" as TK)}
                    />
                  </Tooltip>
                  <Tooltip
                    content={token.debug_enabled ? t("tokens.debugDisable" as TK) : t("tokens.debugEnable" as TK)}
                    relationship="label"
                  >
                    <Button
                      size="small"
                      appearance={token.debug_enabled ? "primary" : "subtle"}
                      icon={<BugRegular />}
                      onClick={() => toggleDebug(token)}
                      aria-label={t("tokens.debugEnable" as TK)}
                    />
                  </Tooltip>
                  <Tooltip content={t("common.delete" as TK)} relationship="label">
                    <Button
                      size="small"
                      appearance="subtle"
                      icon={<DeleteRegular />}
                      onClick={() => remove(token)}
                      aria-label={t("common.delete" as TK)}
                    />
                  </Tooltip>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </DataTable>
      )}

      <SecretDialog secret={secret} onClose={() => setSecret(null)} />
      <Dialog open={editing !== null} onOpenChange={(_, d) => !d.open && setEditing(null)}>
        <DialogSurface>
          <DialogBody>
            <DialogTitle>{t("tokens.renameTitle" as TK)}</DialogTitle>
            <DialogContent>
              <Field label={t("myToken.name" as TK)}>
                <Input value={editName} onChange={(_, d) => setEditName(d.value)} />
              </Field>
            </DialogContent>
            <DialogActions>
              <Button appearance="secondary" onClick={() => setEditing(null)}>
                {t("common.cancel" as TK)}
              </Button>
              <Button appearance="primary" onClick={saveEdit}>
                {t("common.save" as TK)}
              </Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </div>
  );
}
