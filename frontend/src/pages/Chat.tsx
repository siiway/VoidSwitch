import {
  Button,
  Combobox,
  Option,
  Popover,
  PopoverSurface,
  PopoverTrigger,
  Spinner,
  Text,
  Textarea,
  Tooltip,
  makeStyles,
  shorthands,
  tokens,
} from "@fluentui/react-components";
import {
  AddRegular,
  ArrowSyncRegular,
  BotRegular,
  CheckmarkRegular,
  CopyRegular,
  DismissRegular,
  KeyRegular,
  PersonRegular,
  SendRegular,
  SettingsRegular,
  SparkleRegular,
} from "@fluentui/react-icons";
import { useCallback, useEffect, useRef, useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useTranslation, Trans } from "react-i18next";
import type { Translations } from "../i18n/locales/en";
import { api, API_BASE } from "../api/client";
import type { VoidTokenWithSecret } from "../api/types";
import { useNotify } from "../components/ui";

// The composer talks to the *gateway* (`/v1/chat/completions`), authenticated
// with a `vs-…` Void-Token — not the dashboard session — so we keep that token
// in its own localStorage slot.
const CHAT_TOKEN_KEY = "voidswitch.chat_token";

const EXAMPLES = [
  "Explain async/await in Python with a short example",
  "Write a regex to validate an email address",
  "Summarize the CAP theorem in three bullets",
  "Refactor this loop into a list comprehension",
];

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

interface Usage {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
}

interface ModelOption {
  id: string;
  display_name?: string;
  owned_by?: string;
}

// Rank a model against a search query: id matches outrank custom-name matches,
// which outrank provider matches. Returns -1 when nothing matches.
function rankModel(m: ModelOption, query: string): number {
  if (!query) return 0;
  if (m.id.toLowerCase().includes(query)) return 0;
  if ((m.display_name ?? "").toLowerCase().includes(query)) return 1;
  if ((m.owned_by ?? "").toLowerCase().includes(query)) return 2;
  return -1;
}

export function Chat() {
  const styles = useStyles();
  const notify = useNotify();
  const { t } = useTranslation();
  type TK = keyof Translations;

  const [chatToken, setChatToken] = useState<string>(
    () => localStorage.getItem(CHAT_TOKEN_KEY) ?? "",
  );
  const [tokenDraft, setTokenDraft] = useState("");
  const [models, setModels] = useState<ModelOption[]>([]);
  const [model, setModel] = useState<string>("");
  const [modelsError, setModelsError] = useState<string | null>(null);
  const [system, setSystem] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [minting, setMinting] = useState(false);
  const [usage, setUsage] = useState<Usage | null>(null);

  const abortRef = useRef<AbortController | null>(null);
  const threadRef = useRef<HTMLDivElement>(null);
  const composerRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (chatToken) localStorage.setItem(CHAT_TOKEN_KEY, chatToken);
    else localStorage.removeItem(CHAT_TOKEN_KEY);
  }, [chatToken]);

  // Pin to the newest message as it streams.
  useEffect(() => {
    const el = threadRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages]);

  const loadModels = useCallback(async () => {
    if (!chatToken) {
      setModels([]);
      return;
    }
    setModelsError(null);
    try {
      const res = await fetch(`${API_BASE}/v1/models`, {
        headers: { Authorization: `Bearer ${chatToken}` },
        cache: "no-store",
      });
      if (!res.ok) {
        throw new Error(
          res.status === 401
            ? t("chat.tokenRejected" as TK)
            : `Could not load models (HTTP ${res.status}).`,
        );
      }
      const body = (await res.json()) as { data?: ModelOption[] };
      const list = body.data ?? [];
      setModels(list);
      setModel((cur) =>
        cur && list.some((m) => m.id === cur) ? cur : (list[0]?.id ?? ""),
      );
    } catch (e) {
      setModels([]);
      setModelsError(e instanceof Error ? e.message : String(e));
    }
  }, [chatToken, t]);

  useEffect(() => {
    void loadModels();
  }, [loadModels]);

  async function mintToken() {
    setMinting(true);
    try {
      const created = await api.post<VoidTokenWithSecret>("/api/me/tokens", {
        name: "dashboard-chat",
      });
      setChatToken(created.token);
      setTokenDraft("");
      notify(
        t("chat.tokenMinted" as TK),
        t("chat.tokenMintedDesc" as TK),
        "success",
      );
    } catch (e) {
      notify(
        t("chat.mintFailed" as TK),
        e instanceof Error ? e.message : String(e),
        "error",
      );
    } finally {
      setMinting(false);
    }
  }

  function applyToken() {
    const trimmed = tokenDraft.trim();
    if (!trimmed) return;
    setChatToken(trimmed);
    setTokenDraft("");
  }

  function stop() {
    abortRef.current?.abort();
  }

  function newChat() {
    if (busy) stop();
    setMessages([]);
    setUsage(null);
    setInput("");
    composerRef.current?.focus();
  }

  function useExample(text: string) {
    setInput(text);
    composerRef.current?.focus();
  }

  async function send(prompt?: string) {
    const text = (prompt ?? input).trim();
    if (!text || busy) return;
    if (!chatToken) {
      notify(t("chat.noToken" as TK), t("chat.noTokenDesc" as TK), "warning");
      return;
    }
    if (!model) {
      notify(t("chat.noModel" as TK), t("chat.noModelDesc" as TK), "warning");
      return;
    }

    const history = [...messages, { role: "user" as const, content: text }];
    setMessages([...history, { role: "assistant", content: "" }]);
    setInput("");
    setUsage(null);
    setBusy(true);

    const controller = new AbortController();
    abortRef.current = controller;

    const outbound = system.trim()
      ? [{ role: "system", content: system.trim() }, ...history]
      : history;

    try {
      const res = await fetch(`${API_BASE}/v1/chat/completions`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${chatToken}`,
        },
        body: JSON.stringify({
          model,
          messages: outbound,
          stream: true,
          stream_options: { include_usage: true },
        }),
        signal: controller.signal,
        cache: "no-store",
      });

      if (!res.ok || !res.body) {
        throw new Error(await readError(res));
      }

      await consumeStream(res.body, controller.signal, {
        onDelta: (delta) =>
          setMessages((prev) => {
            const next = [...prev];
            const last = next[next.length - 1];
            if (last && last.role === "assistant") {
              next[next.length - 1] = {
                ...last,
                content: last.content + delta,
              };
            }
            return next;
          }),
        onUsage: setUsage,
      });
    } catch (e) {
      if (!controller.signal.aborted) {
        notify(
          t("chat.requestFailed" as TK),
          e instanceof Error ? e.message : String(e),
          "error",
        );
        setMessages((prev) => {
          const last = prev[prev.length - 1];
          if (last && last.role === "assistant" && last.content === "")
            return prev.slice(0, -1);
          return prev;
        });
      }
    } finally {
      setBusy(false);
      abortRef.current = null;
    }
  }

  function onComposerKey(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void send();
    }
  }

  const hasToken = Boolean(chatToken);

  // -- token onboarding (no token yet) ------------------------------------- //
  if (!hasToken) {
    return (
      <div className={styles.gateWrap}>
        <div className={styles.gateCard}>
          <span className={styles.gateMark}>
            <SparkleRegular />
          </span>
          <Text
            size={500}
            weight="semibold"
            block
            style={{ textAlign: "center" }}
          >
            {t("chat.onboardingTitle" as TK)}
          </Text>
          <Text
            size={200}
            align="center"
            style={{ color: tokens.colorNeutralForeground3 }}
          >
            <Trans
              i18nKey="chat.onboardingDesc"
              components={{ code: <code /> }}
            />
          </Text>
          <Button
            appearance="primary"
            size="large"
            icon={minting ? <Spinner size="tiny" /> : <SparkleRegular />}
            onClick={() => void mintToken()}
            disabled={minting}
            style={{ width: "100%" }}
          >
            {t("chat.mintToken" as TK)}
          </Button>
          <div className={styles.gateDivider}>
            <span>{t("chat.orPaste" as TK)}</span>
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <Textarea
              value={tokenDraft}
              onChange={(_, d) => setTokenDraft(d.value)}
              placeholder={t("chat.tokenPlaceholder" as TK)}
              resize="none"
              style={{ flex: 1 }}
              textarea={{ style: { minHeight: 32 } }}
            />
            <Button
              icon={<KeyRegular />}
              onClick={applyToken}
              disabled={!tokenDraft.trim()}
            >
              {t("chat.use" as TK)}
            </Button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className={styles.page}>
      {/* header */}
      <div className={styles.header}>
        <Combobox
          className={styles.modelPick}
          value={model}
          selectedOptions={model ? [model] : []}
          placeholder={t("chat.selectModel" as TK)}
          disabled={models.length === 0}
          freeform
          autoComplete="list"
          onOptionSelect={(_, d) => d.optionValue && setModel(d.optionValue)}
          onChange={(e) => setModel((e.target as HTMLInputElement).value)}
        >
          {models
            .map((m) => ({ m, rank: rankModel(m, model.trim().toLowerCase()) }))
            .filter((x) => x.rank >= 0)
            .sort(
              (a, b) =>
                a.rank - b.rank || a.m.id.localeCompare(b.m.id),
            )
            .map(({ m }) => (
              <Option key={m.id} value={m.id} text={m.id}>
                {m.display_name ? `${m.display_name}  ·  ` : ""}
                {m.id}
                {m.owned_by ? `  ·  ${m.owned_by}` : ""}
              </Option>
            ))}
        </Combobox>

        <div className={styles.headerActions}>
          <Tooltip content={t("chat.reloadModels" as TK)} relationship="label">
            <Button
              appearance="subtle"
              icon={<ArrowSyncRegular />}
              onClick={() => void loadModels()}
            />
          </Tooltip>

          <Popover positioning="below-end" trapFocus>
            <PopoverTrigger disableButtonEnhancement>
              <Tooltip content={t("chat.settingsTooltip" as TK)} relationship="label">
                <Button
                  appearance={system.trim() ? "primary" : "subtle"}
                  icon={<SettingsRegular />}
                />
              </Tooltip>
            </PopoverTrigger>
            <PopoverSurface className={styles.settings}>
              <Text weight="semibold" block>
                {t("chat.systemPromptLabel" as TK)}
              </Text>
              <Textarea
                value={system}
                onChange={(_, d) => setSystem(d.value)}
                placeholder={t("chat.systemPromptHint" as TK)}
                resize="vertical"
                textarea={{ style: { minHeight: 88 } }}
              />
              <Text
                size={100}
                style={{ color: tokens.colorNeutralForeground3 }}
              >
                {t("chat.systemApplied" as TK)}
              </Text>
              <Button
                size="small"
                appearance="subtle"
                icon={<DismissRegular />}
                onClick={() => {
                  setChatToken("");
                  setModelsError(null);
                }}
                style={{ alignSelf: "flex-start", marginTop: 4 }}
              >
                {t("chat.switchToken" as TK)}
              </Button>
            </PopoverSurface>
          </Popover>

          <Tooltip content={t("chat.newChat" as TK)} relationship="label">
            <Button
              appearance="subtle"
              icon={<AddRegular />}
              onClick={newChat}
              disabled={messages.length === 0 && !busy}
            />
          </Tooltip>
        </div>
      </div>

      {modelsError ? (
        <div className={styles.banner}>
          <Text size={200}>{modelsError}</Text>
          <Button
            size="small"
            appearance="subtle"
            onClick={() => {
              setChatToken("");
              setModelsError(null);
            }}
          >
            Switch token
          </Button>
        </div>
      ) : null}

      {/* thread */}
      <div className={styles.threadScroll} ref={threadRef}>
        {messages.length === 0 ? (
          <div className={styles.welcome}>
            <span className={styles.welcomeMark}>
              <SparkleRegular />
            </span>
            <Text
              size={600}
              weight="semibold"
              block
              style={{ textAlign: "center" }}
            >
              {t("chat.greeting" as TK)}
            </Text>
            <div className={styles.examples}>
              {EXAMPLES.map((ex) => (
                <button
                  key={ex}
                  className={styles.example}
                  onClick={() => useExample(ex)}
                >
                  {ex}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className={styles.thread}>
            {messages.map((m, i) => {
              const streaming =
                busy && i === messages.length - 1 && m.role === "assistant";
              return (
                <MessageRow
                  key={i}
                  message={m}
                  streaming={streaming}
                  onCopy={() => copyText(m.content, notify, t)}
                />
              );
            })}
          </div>
        )}
      </div>

      {/* composer */}
      <div className={styles.composerWrap}>
        <div className={styles.composer}>
          <Textarea
            appearance="filled-lighter"
            className={styles.composerInput}
            value={input}
            onChange={(_, d) => setInput(d.value)}
            onKeyDown={onComposerKey}
            placeholder={t("chat.messagePlaceholder" as TK)}
            resize="none"
            textarea={{ ref: composerRef, style: { maxHeight: 200 } }}
          />
          {busy ? (
            <Button
              className={styles.sendBtn}
              shape="circular"
              appearance="secondary"
              icon={<DismissRegular />}
              onClick={stop}
              aria-label={t("chat.stop" as TK)}
            />
          ) : (
            <Button
              className={styles.sendBtn}
              shape="circular"
              appearance="primary"
              icon={<SendRegular />}
              onClick={() => void send()}
              disabled={!input.trim()}
              aria-label={t("chat.send" as TK)}
            />
          )}
        </div>
        <div className={styles.composerHint}>
          <Text size={100}>
            {model || "no model"} · {t("chat.enterToSend" as TK)}
          </Text>
          {usage ? (
            <Text size={100}>
              {usage.prompt_tokens} in · {usage.completion_tokens} out ·{" "}
              {usage.total_tokens} tokens
            </Text>
          ) : null}
        </div>
      </div>
    </div>
  );
}

// --- one message ----------------------------------------------------------- //

function MessageRow({
  message,
  streaming,
  onCopy,
}: {
  message: ChatMessage;
  streaming: boolean;
  onCopy: () => void;
}) {
  const styles = useStyles();
  const { t } = useTranslation();
  type TK = keyof Translations;
  const isUser = message.role === "user";
  return (
    <div className={styles.row}>
      <span
        className={`${styles.avatar} ${isUser ? styles.avatarUser : styles.avatarBot}`}
      >
        {isUser ? <PersonRegular /> : <BotRegular />}
      </span>
      <div className={styles.rowMain}>
        <div className={styles.rowHead}>
          <Text size={200} weight="semibold">
            {isUser ? t("chat.you" as TK) : t("chat.assistant" as TK)}
          </Text>
          {message.content ? (
            <Tooltip content={t("chat.copy" as TK)} relationship="label">
              <Button
                className={`${styles.copyBtn} vs-copy`}
                size="small"
                appearance="subtle"
                icon={<CopyRegular />}
                onClick={onCopy}
                aria-label={t("chat.copyMessage" as TK)}
              />
            </Tooltip>
          ) : null}
        </div>
        {isUser ? (
          <div className={styles.userText}>{message.content}</div>
        ) : message.content ? (
          <div className={styles.markdown}>
            <Markdown remarkPlugins={[remarkGfm]} components={MD_COMPONENTS}>
              {message.content}
            </Markdown>
            {streaming ? <span className={styles.caret} /> : null}
          </div>
        ) : (
          <Spinner size="tiny" />
        )}
      </div>
    </div>
  );
}

// react-markdown renderers: wrap fenced code in a copy-able block; everything
// else is styled via the `.markdown` class.
const MD_COMPONENTS = {
  pre: (props: { children?: React.ReactNode }) => (
    <CodeBlock>{props.children}</CodeBlock>
  ),
};

function CodeBlock({ children }: { children?: React.ReactNode }) {
  const styles = useStyles();
  const notify = useNotify();
  const { t } = useTranslation();
  const ref = useRef<HTMLPreElement>(null);
  const [copied, setCopied] = useState(false);

  async function copy() {
    const text = ref.current?.innerText ?? "";
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1400);
    } catch {
      notify(t("chat.copyFailed"), "Clipboard unavailable", "error");
    }
  }

  return (
    <div className={styles.codeWrap}>
      <Button
        className={`${styles.codeCopy} vs-codecopy`}
        size="small"
        appearance="subtle"
        icon={copied ? <CheckmarkRegular /> : <CopyRegular />}
        onClick={copy}
        aria-label={t("chat.copyCode")}
      />
      <pre ref={ref}>{children}</pre>
    </div>
  );
}

// --- helpers ---------------------------------------------------------------- //

async function copyText(
  text: string,
  notify: ReturnType<typeof useNotify>,
  tFn: (key: string) => string,
) {
  try {
    await navigator.clipboard.writeText(text);
    notify(tFn("chat.copied"), undefined, "success");
  } catch {
    notify(tFn("chat.copyFailed"), "Clipboard unavailable", "error");
  }
}

async function readError(res: Response): Promise<string> {
  try {
    const data = await res.json();
    return (
      data?.error?.message ||
      data?.detail ||
      `Request failed (HTTP ${res.status}).`
    );
  } catch {
    return `Request failed (HTTP ${res.status}).`;
  }
}

/** Read an OpenAI-style SSE stream, surfacing content deltas and final usage. */
async function consumeStream(
  body: ReadableStream<Uint8Array>,
  signal: AbortSignal,
  handlers: { onDelta: (delta: string) => void; onUsage: (u: Usage) => void },
): Promise<void> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (!signal.aborted) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      let sep: number;
      while ((sep = buffer.indexOf("\n\n")) >= 0) {
        const block = buffer.slice(0, sep);
        buffer = buffer.slice(sep + 2);
        for (const raw of block.split("\n")) {
          const line = raw.trim();
          if (!line.startsWith("data:")) continue;
          const data = line.slice(5).trim();
          if (!data || data === "[DONE]") continue;
          try {
            const obj = JSON.parse(data);
            const delta: string | undefined = obj?.choices?.[0]?.delta?.content;
            if (delta) handlers.onDelta(delta);
            if (obj?.usage) {
              handlers.onUsage({
                prompt_tokens: obj.usage.prompt_tokens ?? 0,
                completion_tokens: obj.usage.completion_tokens ?? 0,
                total_tokens: obj.usage.total_tokens ?? 0,
              });
            }
          } catch {
            /* ignore keep-alives / partial frames */
          }
        }
      }
    }
  } finally {
    reader.cancel().catch(() => {});
  }
}

// --- styles ----------------------------------------------------------------- //

const useStyles = makeStyles({
  page: {
    display: "flex",
    flexDirection: "column",
    height: "100%",
    minHeight: 0,
  },
  header: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    paddingBottom: "10px",
    marginBottom: "6px",
    ...shorthands.borderBottom("1px", "solid", tokens.colorNeutralStroke2),
  },
  modelPick: {
    minWidth: "200px",
    maxWidth: "none",
    width: "auto",
    flex: "1 1 auto",
  },
  modelButton: {
    fontWeight: tokens.fontWeightSemibold,
  },
  headerActions: {
    display: "flex",
    columnGap: "4px",
  },
  banner: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    columnGap: "12px",
    ...shorthands.padding("8px", "12px"),
    marginBottom: "8px",
    borderRadius: tokens.borderRadiusMedium,
    backgroundColor: tokens.colorPaletteRedBackground1,
    color: tokens.colorPaletteRedForeground1,
  },
  threadScroll: {
    flex: 1,
    minHeight: 0,
    overflowY: "auto",
  },
  thread: {
    maxWidth: "768px",
    margin: "0 auto",
    width: "100%",
    ...shorthands.padding("12px", "0", "24px"),
  },

  // welcome / empty state
  welcome: {
    height: "100%",
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    justifyContent: "center",
    rowGap: "16px",
    maxWidth: "640px",
    margin: "0 auto",
  },
  welcomeMark: {
    display: "grid",
    placeItems: "center",
    width: "52px",
    height: "52px",
    fontSize: "26px",
    borderRadius: tokens.borderRadiusCircular,
    color: tokens.colorNeutralForegroundOnBrand,
    background: `linear-gradient(135deg, ${tokens.colorBrandBackground}, ${tokens.colorBrandBackground2})`,
  },
  examples: {
    display: "grid",
    gridTemplateColumns: "1fr 1fr",
    gap: "10px",
    width: "100%",
    marginTop: "4px",
  },
  example: {
    textAlign: "left",
    ...shorthands.padding("12px", "14px"),
    borderRadius: tokens.borderRadiusLarge,
    ...shorthands.border("1px", "solid", tokens.colorNeutralStroke2),
    backgroundColor: tokens.colorNeutralBackground1,
    color: tokens.colorNeutralForeground2,
    fontSize: tokens.fontSizeBase300,
    cursor: "pointer",
    transitionProperty: "background-color, border-color",
    transitionDuration: tokens.durationFaster,
    ":hover": {
      backgroundColor: tokens.colorNeutralBackground1Hover,
      ...shorthands.borderColor(tokens.colorNeutralStroke1),
    },
  },

  // a message row
  row: {
    display: "flex",
    columnGap: "14px",
    ...shorthands.padding("18px", "4px"),
    ":hover .vs-copy": {
      opacity: 1,
    },
  },
  avatar: {
    flexShrink: 0,
    display: "grid",
    placeItems: "center",
    width: "30px",
    height: "30px",
    borderRadius: tokens.borderRadiusMedium,
    fontSize: "17px",
  },
  avatarUser: {
    backgroundColor: tokens.colorBrandBackground2,
    color: tokens.colorBrandForeground1,
  },
  avatarBot: {
    color: tokens.colorNeutralForegroundOnBrand,
    background: `linear-gradient(135deg, ${tokens.colorBrandBackground}, ${tokens.colorBrandBackground2})`,
  },
  rowMain: {
    flex: 1,
    minWidth: 0,
  },
  rowHead: {
    display: "flex",
    alignItems: "center",
    columnGap: "6px",
    height: "24px",
    marginBottom: "2px",
  },
  copyBtn: {
    opacity: 0,
    transitionProperty: "opacity",
    transitionDuration: tokens.durationFaster,
  },
  userText: {
    whiteSpace: "pre-wrap",
    overflowWrap: "anywhere",
    fontSize: tokens.fontSizeBase300,
    lineHeight: tokens.lineHeightBase400,
    color: tokens.colorNeutralForeground1,
  },
  caret: {
    display: "inline-block",
    width: "8px",
    height: "1.05em",
    marginLeft: "2px",
    verticalAlign: "text-bottom",
    backgroundColor: tokens.colorBrandForeground1,
    borderRadius: "1px",
    animationName: {
      "0%, 45%": { opacity: 1 },
      "50%, 100%": { opacity: 0 },
    },
    animationDuration: "1s",
    animationIterationCount: "infinite",
  },

  // markdown body
  markdown: {
    fontSize: tokens.fontSizeBase300,
    lineHeight: tokens.lineHeightBase400,
    color: tokens.colorNeutralForeground1,
    overflowWrap: "anywhere",
    "& p": { margin: "0 0 12px" },
    "& > *:last-child": { marginBottom: 0 },
    "& h1, & h2, & h3, & h4": {
      margin: "18px 0 8px",
      lineHeight: tokens.lineHeightBase500,
      fontWeight: tokens.fontWeightSemibold,
    },
    "& h1": { fontSize: tokens.fontSizeBase600 },
    "& h2": { fontSize: tokens.fontSizeBase500 },
    "& h3": { fontSize: tokens.fontSizeBase400 },
    "& ul, & ol": { margin: "0 0 12px", paddingLeft: "22px" },
    "& li": { margin: "3px 0" },
    "& a": { color: tokens.colorBrandForegroundLink, textDecoration: "none" },
    "& a:hover": { textDecoration: "underline" },
    "& blockquote": {
      margin: "0 0 12px",
      paddingLeft: "12px",
      color: tokens.colorNeutralForeground2,
      ...shorthands.borderLeft("3px", "solid", tokens.colorNeutralStroke2),
    },
    "& hr": {
      border: "none",
      ...shorthands.borderTop("1px", "solid", tokens.colorNeutralStroke2),
      margin: "16px 0",
    },
    "& table": {
      borderCollapse: "collapse",
      margin: "0 0 12px",
      display: "block",
      overflowX: "auto",
    },
    "& th, & td": {
      ...shorthands.border("1px", "solid", tokens.colorNeutralStroke2),
      ...shorthands.padding("6px", "10px"),
      textAlign: "left",
    },
    "& th": { backgroundColor: tokens.colorNeutralBackground2 },
    // inline code (block code is handled by CodeBlock)
    "& :not(pre) > code": {
      fontFamily: tokens.fontFamilyMonospace,
      fontSize: "0.875em",
      ...shorthands.padding("1px", "5px"),
      borderRadius: tokens.borderRadiusSmall,
      backgroundColor: tokens.colorNeutralBackground3,
    },
  },
  codeWrap: {
    position: "relative",
    margin: "0 0 12px",
    "& pre": {
      margin: 0,
      ...shorthands.padding("12px", "14px"),
      paddingRight: "40px",
      borderRadius: tokens.borderRadiusMedium,
      backgroundColor: tokens.colorNeutralBackground3,
      overflowX: "auto",
      fontFamily: tokens.fontFamilyMonospace,
      fontSize: tokens.fontSizeBase200,
      lineHeight: tokens.lineHeightBase300,
    },
    "& code": { fontFamily: tokens.fontFamilyMonospace },
    ":hover .vs-codecopy": { opacity: 1 },
  },
  codeCopy: {
    position: "absolute",
    top: "6px",
    right: "6px",
    opacity: 0,
    transitionProperty: "opacity",
    transitionDuration: tokens.durationFaster,
  },

  // composer
  composerWrap: {
    flexShrink: 0,
    maxWidth: "768px",
    width: "100%",
    margin: "0 auto",
    paddingTop: "8px",
  },
  composer: {
    position: "relative",
    display: "flex",
    alignItems: "flex-end",
    ...shorthands.padding("8px"),
    borderRadius: tokens.borderRadiusXLarge,
    backgroundColor: tokens.colorNeutralBackground3,
    ...shorthands.border("1px", "solid", tokens.colorNeutralStroke2),
    ":focus-within": {
      ...shorthands.borderColor(tokens.colorBrandStroke1),
    },
  },
  composerInput: {
    flex: 1,
    backgroundColor: "transparent",
    "&::after": { display: "none" },
    "&::before": { display: "none" },
  },
  sendBtn: {
    flexShrink: 0,
    marginLeft: "6px",
  },
  composerHint: {
    display: "flex",
    justifyContent: "space-between",
    columnGap: "12px",
    ...shorthands.padding("6px", "8px", "0"),
    color: tokens.colorNeutralForeground3,
  },

  // settings popover
  settings: {
    display: "flex",
    flexDirection: "column",
    rowGap: "8px",
    width: "340px",
  },

  // token gate
  gateWrap: {
    height: "100%",
    display: "grid",
    placeItems: "center",
  },
  gateCard: {
    display: "flex",
    flexDirection: "column",
    rowGap: "14px",
    width: "min(420px, 100%)",
    ...shorthands.padding("28px"),
    border: `1px solid ${tokens.colorNeutralStroke1}`,
    borderRadius: "10px",
    background: tokens.colorNeutralBackground1,
  },
  gateMark: {
    alignSelf: "center",
    display: "grid",
    placeItems: "center",
    width: "52px",
    height: "52px",
    fontSize: "26px",
    borderRadius: tokens.borderRadiusCircular,
    color: tokens.colorNeutralForegroundOnBrand,
    background: `linear-gradient(135deg, ${tokens.colorBrandBackground}, ${tokens.colorBrandBackground2})`,
  },
  gateDivider: {
    display: "flex",
    alignItems: "center",
    columnGap: "10px",
    color: tokens.colorNeutralForeground4,
    fontSize: tokens.fontSizeBase100,
    "::before, ::after": {
      content: '""',
      flex: 1,
      height: "1px",
      backgroundColor: tokens.colorNeutralStroke2,
    },
  },
});
