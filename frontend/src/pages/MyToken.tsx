import {
  Button,
  Card,
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
  CheckmarkRegular,
  CopyRegular,
  DeleteRegular,
} from "@fluentui/react-icons";
import { useState } from "react";
import { useTranslation, Trans } from "react-i18next";
import type { Translations } from "../i18n/locales/en";
import { api, API_BASE } from "../api/client";
import type { VoidToken, VoidTokenWithSecret } from "../api/types";
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

const OPENCODE_SNIPPET = (model: string, smallModel: string) => `// ~/.config/opencode/opencode.json
{
  "$schema": "https://opencode.ai/config.json",
  "model": "voidswitch/${model}",${
    smallModel ? `\n  "small_model": "voidswitch/${smallModel}",` : ""
  }
  "provider": {
    "voidswitch": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "VoidSwitch",
      "options": { "baseURL": "${API_BASE}/v1" },
      "models": { "${model}": {}${smallModel && smallModel !== model ? `, "${smallModel}": {}` : ""} }
    }
  }
}`;

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
        t("myToken.copyFailed" as TK),
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
  const { t } = useTranslation();
  type TK = keyof Translations;
  const tokensList = useAsync<VoidToken[]>(() => api.get("/api/me/tokens"));
  const usage = useAsync<Usage>(() => api.get("/api/me/usage"));
  // Public config carries the OpenCode model defaults (non-secret); the
  // staff-only /api/admin/settings would 403 for ordinary members.
  const config = useAsync<{
    opencode_default_model?: string;
    opencode_small_model?: string;
  }>(() => api.get("/api/auth/config"));
  const [name, setName] = useState("default");
  const [secret, setSecret] = useState<VoidTokenWithSecret | null>(null);
  const [client, setClient] = useState("openai");

  const ocModel = config.data?.opencode_default_model || "claude-opus-4-8";
  const ocSmallModel = config.data?.opencode_small_model || "";

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
      message: `Rotate "${token.name}"? The old key stops working immediately.`,
      confirmLabel: t("myToken.rotate" as TK),
      tone: "danger",
    });
    if (!ok) return;
    const rotated = await api.post<VoidTokenWithSecret>(
      `/api/me/tokens/${token.id}/rotate`,
    );
    setSecret(rotated);
    tokensList.reload();
  }

  async function remove(token: VoidToken) {
    const ok = await confirm({
      title: t("myToken.deleteTitle" as TK),
      message: t("myToken.deleteMsg" as TK).replace("{name}", token.name),
      confirmLabel: t("common.delete" as TK),
      tone: "danger",
    });
    if (!ok) return;
    await api.del(`/api/me/tokens/${token.id}`);
    tokensList.reload();
    usage.reload();
  }

  async function toggleDebug(token: VoidToken) {
    await api.patch(`/api/me/tokens/${token.id}`, { debug_enabled: !token.debug_enabled });
    tokensList.reload();
  }

  return (
    <div>
      <PageHeader
        title={t("myToken.title" as TK)}
        subtitle={t("myToken.subtitle" as TK)}
        onRefresh={() => {
          tokensList.reload();
          usage.reload();
          config.reload();
        }}
      />

      <Card style={{ padding: 18, marginBottom: 20 }}>
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

            <details>
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
                <CodeBlock code={OPENCODE_SNIPPET(ocModel, ocSmallModel)} />
                <div
                  style={{ display: "flex", flexDirection: "column", gap: 4 }}
                >
                  <Text
                    size={200}
                    block
                    style={{ color: tokens.colorNeutralForeground3 }}
                  >
                    1. Save the config above — leave out <code>apiKey</code> so
                    OpenCode stores it for you.
                  </Text>
                  <Text
                    size={200}
                    block
                    style={{ color: tokens.colorNeutralForeground3 }}
                  >
                    2. Run <code>/connect</code>; <strong>VoidSwitch</strong>{" "}
                    appears in the provider list (because you saved it) — select
                    it.
                  </Text>
                  <Text
                    size={200}
                    block
                    style={{ color: tokens.colorNeutralForeground3 }}
                  >
                    3. Paste a <code>vs-…</code> token at the <em>API key</em>{" "}
                    prompt, then pick a model.
                  </Text>
                </div>
              </div>
            </details>
          </div>
        ) : null}
      </Card>

      {usage.data ? (
        <div style={{ display: "flex", gap: 12, marginBottom: 20 }}>
          <Card style={{ padding: 14, flex: 1 }}>
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
          </Card>
          <Card style={{ padding: 14, flex: 1 }}>
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
          </Card>
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
                <TableCell style={{ color: tokens.colorNeutralForeground3 }}>
                  {formatDate(token.last_used_at)}
                </TableCell>
                <TableCell>
                  <Button
                    size="small"
                    appearance="subtle"
                    icon={<ArrowSyncRegular />}
                    onClick={() => rotate(token)}
                  >
                    {t("myToken.rotate" as TK)}
                  </Button>
                  <Tooltip
                    content={token.debug_enabled ? t("tokens.debugDisable" as TK) : t("tokens.debugEnable" as TK)}
                    relationship="label"
                  >
                    <Button
                      size="small"
                      appearance={token.debug_enabled ? "primary" : "subtle"}
                      icon={<BugRegular />}
                      onClick={() => toggleDebug(token)}
                    />
                  </Tooltip>
                  <Button
                    size="small"
                    appearance="subtle"
                    icon={<DeleteRegular />}
                    onClick={() => remove(token)}
                  />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </DataTable>
      )}

      <SecretDialog secret={secret} onClose={() => setSecret(null)} />
    </div>
  );
}
