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
  tokens,
} from "@fluentui/react-components";
import {
  AddRegular,
  ArrowSyncRegular,
  CheckmarkRegular,
  CopyRegular,
  DeleteRegular,
} from "@fluentui/react-icons";
import { useState } from "react";
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

const OPENCODE_SNIPPET = `// ~/.config/opencode/opencode.json
{
  "$schema": "https://opencode.ai/config.json",
  "model": "voidswitch/claude-opus-4-8",
  "provider": {
    "voidswitch": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "VoidSwitch",
      "options": { "baseURL": "${API_BASE}/v1" },
      "models": { "claude-opus-4-8": {} }
    }
  }
}`;

/** A monospace code block with a one-click copy button. */
function CodeBlock({ code }: { code: string }) {
  const notify = useNotify();
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      notify(
        "Copy failed",
        "Clipboard is unavailable in this browser",
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
        aria-label="Copy to clipboard"
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
  const tokensList = useAsync<VoidToken[]>(() => api.get("/api/me/tokens"));
  const usage = useAsync<Usage>(() => api.get("/api/me/usage"));
  const [name, setName] = useState("default");
  const [secret, setSecret] = useState<VoidTokenWithSecret | null>(null);
  const [client, setClient] = useState("openai");

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
        "Create failed",
        e instanceof Error ? e.message : String(e),
        "error",
      );
    }
  }

  async function rotate(t: VoidToken) {
    const ok = await confirm({
      title: "Rotate token",
      message: `Rotate "${t.name}"? The old key stops working immediately.`,
      confirmLabel: "Rotate",
      tone: "danger",
    });
    if (!ok) return;
    const rotated = await api.post<VoidTokenWithSecret>(
      `/api/me/tokens/${t.id}/rotate`,
    );
    setSecret(rotated);
    tokensList.reload();
  }

  async function remove(t: VoidToken) {
    const ok = await confirm({
      title: "Delete token",
      message: `Delete "${t.name}"?`,
      confirmLabel: "Delete",
      tone: "danger",
    });
    if (!ok) return;
    await api.del(`/api/me/tokens/${t.id}`);
    tokensList.reload();
    usage.reload();
  }

  return (
    <div>
      <PageHeader
        title="My API Key"
        subtitle="Use these tokens to call the gateway"
      />

      <Card style={{ padding: 18, marginBottom: 20 }}>
        <Text weight="semibold" block style={{ marginBottom: 2 }}>
          Connect a client
        </Text>
        <Text
          size={200}
          block
          style={{ color: tokens.colorNeutralForeground3, marginBottom: 8 }}
        >
          Point any client at the gateway using a <code>vs-…</code> token from
          below.
        </Text>

        <TabList
          selectedValue={client}
          onTabSelect={(_, d) => setClient(d.value as string)}
          style={{ marginBottom: 12 }}
        >
          <Tab value="openai">OpenAI SDK</Tab>
          <Tab value="claude">Claude Code</Tab>
          <Tab value="opencode">OpenCode</Tab>
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
              One line adds the VoidSwitch provider to your{" "}
              <code>opencode.json</code> automatically.
            </Text>
            <div>
              <Text
                size={200}
                weight="semibold"
                block
                style={{ marginBottom: 4 }}
              >
                macOS / Linux
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
                Windows (PowerShell)
              </Text>
              <CodeBlock code={`irm ${API_BASE}/install | iex`} />
            </div>
            <Text
              size={200}
              block
              style={{ color: tokens.colorNeutralForeground3 }}
            >
              Then run <code>opencode</code> → <code>/connect</code> →{" "}
              <strong>VoidSwitch</strong> and paste a <code>vs-…</code> token.
              To embed the token instead, append <code>?token=vs-…</code> to the
              URL.
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
                Manual setup (no script)
              </summary>
              <div
                style={{
                  display: "flex",
                  flexDirection: "column",
                  gap: 10,
                  marginTop: 10,
                }}
              >
                <CodeBlock code={OPENCODE_SNIPPET} />
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
        <Field label="New token name" style={{ flex: "0 0 240px" }}>
          <Input value={name} onChange={(_, d) => setName(d.value)} />
        </Field>
        <Button appearance="primary" icon={<AddRegular />} onClick={create}>
          Create token
        </Button>
      </div>

      {tokensList.loading ? (
        <Loading />
      ) : tokensList.error ? (
        <ErrorText error={tokensList.error} />
      ) : (
        <DataTable ariaLabel="My tokens">
          <TableHeader>
            <TableRow>
              <TableHeaderCell>Name</TableHeaderCell>
              <TableHeaderCell>Fingerprint</TableHeaderCell>
              <TableHeaderCell>Requests</TableHeaderCell>
              <TableHeaderCell>Tokens</TableHeaderCell>
              <TableHeaderCell>Last used</TableHeaderCell>
              <TableHeaderCell>Actions</TableHeaderCell>
            </TableRow>
          </TableHeader>
          <TableBody>
            {(tokensList.data ?? []).map((t) => (
              <TableRow key={t.id}>
                <TableCell>{t.name}</TableCell>
                <TableCell style={{ fontFamily: "monospace" }}>
                  {t.token_prefix}
                </TableCell>
                <TableCell>{t.total_requests}</TableCell>
                <TableCell>{t.total_tokens}</TableCell>
                <TableCell style={{ color: tokens.colorNeutralForeground3 }}>
                  {formatDate(t.last_used_at)}
                </TableCell>
                <TableCell>
                  <Button
                    size="small"
                    appearance="subtle"
                    icon={<ArrowSyncRegular />}
                    onClick={() => rotate(t)}
                  >
                    Rotate
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

      <SecretDialog secret={secret} onClose={() => setSecret(null)} />
    </div>
  );
}
