import {
  Badge,
  Button,
  Checkbox,
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
  Textarea,
  Tooltip,
  tokens,
} from "@fluentui/react-components";
import {
  AddRegular,
  ArrowSyncRegular,
  CheckmarkCircleRegular,
  CopyRegular,
  DeleteRegular,
  EditRegular,
  KeyRegular,
  ProhibitedRegular,
} from "@fluentui/react-icons";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import type { Translations } from "../i18n/locales/en";
import { api, API_BASE } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import type {
  PlatformAPIKey,
  PlatformAPIKeyScopeCatalogue,
  PlatformAPIKeyWithSecret,
} from "../api/types";
import { EmptyState } from "../components/EmptyState";
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
      notify(t("platformApiKeys.copyFailed" as TK), undefined, "error");
    }
  }

  return (
    <div style={{ position: "relative" }}>
      <Button
        size="small"
        appearance="subtle"
        icon={copied ? <CheckmarkCircleRegular /> : <CopyRegular />}
        onClick={copy}
        aria-label={t("platformApiKeys.copy" as TK)}
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

/**
 * The scope picker. Only "read" is offered as a broad shorthand; every other
 * grant is an individual action, grouped by category so a whole category can be
 * selected at once. Per-provider key scopes get one row per provider, because a
 * grant must name the provider it applies to.
 */
function ScopePicker({
  catalogue,
  selected,
  onChange,
}: {
  catalogue: PlatformAPIKeyScopeCatalogue;
  selected: string[];
  onChange: (next: string[]) => void;
}) {
  const { t } = useTranslation();
  type TK = keyof Translations;

  const chosen = useMemo(() => new Set(selected), [selected]);

  function toggle(scope: string, on: boolean) {
    const next = new Set(chosen);
    if (on) next.add(scope);
    else next.delete(scope);
    onChange([...next]);
  }

  function toggleMany(scopes: string[], on: boolean) {
    const next = new Set(chosen);
    for (const s of scopes) {
      if (on) next.add(s);
      else next.delete(s);
    }
    onChange([...next]);
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div>
        <Text weight="semibold" block style={{ marginBottom: 6 }}>
          {t("platformApiKeys.wildcards" as TK)}
        </Text>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 10 }}>
          {catalogue.broad.map((s) => (
            <Checkbox
              key={s.scope}
              checked={chosen.has(s.scope)}
              onChange={(_, d) => toggle(s.scope, d.checked === true)}
              label={s.scope}
            />
          ))}
        </div>
      </div>

      <div>
        <Text weight="semibold" block style={{ marginBottom: 8 }}>
          {t("platformApiKeys.individualActions" as TK)}
        </Text>
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            gap: 12,
            maxHeight: 320,
            overflowY: "auto",
            paddingRight: 4,
          }}
        >
          {catalogue.categories.map((group) => {
            const scopes = group.actions.map((a) => a.scope);
            const all = scopes.every((s) => chosen.has(s));
            return (
              <div key={group.category}>
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 8,
                    marginBottom: 4,
                  }}
                >
                  <Checkbox
                    checked={all}
                    onChange={(_, d) => toggleMany(scopes, d.checked === true)}
                    label={group.category}
                  />
                  <Tooltip
                    content={t("platformApiKeys.selectWholeCategory" as TK)}
                    relationship="description"
                  >
                    <Text size={100} style={{ color: tokens.colorNeutralForeground3 }}>
                      {t("platformApiKeys.actionCount" as TK).replace(
                        "{count}",
                        String(scopes.length),
                      )}
                    </Text>
                  </Tooltip>
                </div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 10, paddingLeft: 26 }}>
                  {group.actions.map((a) => (
                    <Checkbox
                      key={a.scope}
                      checked={chosen.has(a.scope)}
                      onChange={(_, d) => toggle(a.scope, d.checked === true)}
                      label={a.scope}
                    />
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      <div style={{ display: catalogue.can_manage_provider_keys ? "block" : "none" }}>
        <Text weight="semibold" block style={{ marginBottom: 6 }}>
          {t("platformApiKeys.providerKeys" as TK)}
        </Text>
        <Text
          size={200}
          block
          style={{ color: tokens.colorNeutralForeground3, marginBottom: 8 }}
        >
          {t("platformApiKeys.providerKeysHint" as TK)}
        </Text>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 10 }}>
          {catalogue.providers.map((p) => {
            const scope = `provider-key:${p.slug}.*`;
            return (
              <Checkbox
                key={p.slug}
                checked={chosen.has(scope)}
                onChange={(_, d) => toggle(scope, d.checked === true)}
                label={`${p.name} (${p.slug})`}
              />
            );
          })}
        </div>
      </div>
    </div>
  );
}

/** The one-time secret dialog, with the connect snippets next to it. */
function SecretDialog({
  created,
  onClose,
}: {
  created: PlatformAPIKeyWithSecret | null;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  type TK = keyof Translations;
  const notify = useNotify();
  const [tab, setTab] = useState("mcp");

  const key = created?.key ?? "vsapi-...";
  const mcpConfig = `{
  "mcpServers": {
    "voidswitch": {
      "type": "http",
      "url": "${API_BASE}/api/v1/mcp",
      "headers": { "Authorization": "Bearer ${key}" }
    }
  }
}`;
  const curlSnippet = `curl -s ${API_BASE}/api/v1/whoami \\
  -H "Authorization: Bearer ${key}"

curl -s ${API_BASE}/api/v1/models \\
  -H "Authorization: Bearer ${key}"`;

  return (
    <Dialog open={created !== null} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface style={{ maxWidth: 720 }}>
        <DialogBody>
          <DialogTitle>{t("platformApiKeys.secretTitle" as TK)}</DialogTitle>
          <DialogContent>
            <Text
              block
              style={{ color: tokens.colorNeutralForeground3, marginBottom: 8 }}
            >
              {t("platformApiKeys.secretWarning" as TK)}
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
                marginBottom: 14,
              }}
            >
              <Text font="monospace" style={{ flex: 1 }}>
                {key}
              </Text>
              <Button
                icon={<CopyRegular />}
                aria-label={t("platformApiKeys.copy" as TK)}
                onClick={() => {
                  void navigator.clipboard.writeText(key);
                  notify(t("platformApiKeys.copied" as TK), undefined, "success");
                }}
              />
            </div>

            <TabList
              selectedValue={tab}
              onTabSelect={(_, d) => setTab(d.value as string)}
              style={{ marginBottom: 10 }}
            >
              <Tab value="mcp">{t("platformApiKeys.mcpClient" as TK)}</Tab>
              <Tab value="curl">{t("platformApiKeys.restApi" as TK)}</Tab>
            </TabList>
            {tab === "mcp" ? (
              <>
                <Text
                  size={200}
                  block
                  style={{ color: tokens.colorNeutralForeground3, marginBottom: 8 }}
                >
                  {t("platformApiKeys.mcpHint" as TK)}
                </Text>
                <CodeBlock code={mcpConfig} />
              </>
            ) : (
              <>
                <Text
                  size={200}
                  block
                  style={{ color: tokens.colorNeutralForeground3, marginBottom: 8 }}
                >
                  {t("platformApiKeys.restHint" as TK)}
                </Text>
                <CodeBlock code={curlSnippet} />
              </>
            )}
          </DialogContent>
          <DialogActions>
            <Button appearance="primary" onClick={onClose}>
              {t("platformApiKeys.secretDone" as TK)}
            </Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}

// Connect snippets, shown the same way the Void-Token page shows them: one
// placeholder key, three clients. The placeholder is spelled out in every snippet
// so a copied block is never runnable by accident.
function connectSnippets() {
  const key = "vsapi-...";
  return {
    mcp: `{
  "mcpServers": {
    "voidswitch": {
      "type": "http",
      "url": "${API_BASE}/api/v1/mcp",
      "headers": { "Authorization": "Bearer ${key}" }
    }
  }
}`,
    rest: `export VOIDSWITCH_BASE_URL=${API_BASE}/api/v1
export VOIDSWITCH_API_KEY=${key}

curl -s "$VOIDSWITCH_BASE_URL/whoami" \
  -H "Authorization: Bearer $VOIDSWITCH_API_KEY"

curl -s "$VOIDSWITCH_BASE_URL/models" \
  -H "Authorization: Bearer $VOIDSWITCH_API_KEY"`,
    python: `from voidswitch import Client

vs = Client("${API_BASE}", api_key="${key}")

print(vs.whoami())            # owner, role and the scopes in effect
for model in vs.models.list():
    print(model["model_id"], model["enabled"])`,
  };
}

// effective returns the set of scopes the key can actually exercise: the stored
// scopes intersected with what its owner's role may still grant.
function effective(key: PlatformAPIKey): Set<string> {
  return new Set(key.effective_scopes);
}

export function PlatformAPIKeys() {
  const { t } = useTranslation();
  type TK = keyof Translations;
  const notify = useNotify();
  const confirm = useConfirm();
  const { isOwner } = useAuth();
  const list = useAsync<PlatformAPIKey[]>(() => api.get("/api/me/api-keys"));
  const catalogue = useAsync<PlatformAPIKeyScopeCatalogue>(() =>
    api.get("/api/me/api-keys/scopes"),
  );

  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("default");
  const [scopes, setScopes] = useState<string[]>(["read"]);
  const [created, setCreated] = useState<PlatformAPIKeyWithSecret | null>(null);
  const [client, setClient] = useState("mcp");
  const [editing, setEditing] = useState<PlatformAPIKey | null>(null);
  const [editName, setEditName] = useState("");
  const [editScopes, setEditScopes] = useState<string[]>([]);

  function openCreate() {
    setName("default");
    setScopes(["read"]);
    setCreating(true);
  }

  async function create() {
    if (scopes.length === 0) {
      notify(t("platformApiKeys.needScope" as TK), undefined, "error");
      return;
    }
    try {
      const made = await api.post<PlatformAPIKeyWithSecret>("/api/me/api-keys", {
        name,
        scopes,
      });
      setCreated(made);
      setCreating(false);
      list.reload();
    } catch (e) {
      notify(
        t("platformApiKeys.createFailed" as TK),
        e instanceof Error ? e.message : String(e),
        "error",
      );
    }
  }

  async function toggleEnabled(key: PlatformAPIKey) {
    try {
      await api.patch(`/api/me/api-keys/${key.id}`, { enabled: !key.enabled });
      list.reload();
    } catch (e) {
      notify(
        t("common.updateFailed" as TK),
        e instanceof Error ? e.message : String(e),
        "error",
      );
    }
  }

  async function rotate(key: PlatformAPIKey) {
    const ok = await confirm({
      title: t("platformApiKeys.rotateTitle" as TK),
      message: t("platformApiKeys.rotateMsg" as TK).replace("{name}", key.name),
      confirmLabel: t("platformApiKeys.rotate" as TK),
      tone: "danger",
    });
    if (!ok) return;
    try {
      const rotated = await api.post<PlatformAPIKeyWithSecret>(
        `/api/me/api-keys/${key.id}/rotate`,
      );
      setCreated(rotated);
      list.reload();
    } catch (e) {
      notify(
        t("common.updateFailed" as TK),
        e instanceof Error ? e.message : String(e),
        "error",
      );
    }
  }

  async function remove(key: PlatformAPIKey) {
    const ok = await confirm({
      title: t("platformApiKeys.deleteTitle" as TK),
      message: t("platformApiKeys.deleteMsg" as TK).replace("{name}", key.name),
      confirmLabel: t("common.delete" as TK),
      tone: "danger",
    });
    if (!ok) return;
    try {
      await api.del(`/api/me/api-keys/${key.id}`);
      list.reload();
    } catch (e) {
      notify(
        t("common.deleteFailed" as TK),
        e instanceof Error ? e.message : String(e),
        "error",
      );
    }
  }

  function openEdit(key: PlatformAPIKey) {
    setEditing(key);
    setEditName(key.name);
    setEditScopes(key.scopes);
  }

  async function saveEdit() {
    if (!editing) return;
    try {
      await api.patch(`/api/me/api-keys/${editing.id}`, {
        name: editName.trim() || "default",
        scopes: editScopes,
      });
      setEditing(null);
      list.reload();
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
        title={t("platformApiKeys.title" as TK)}
        subtitle={t("platformApiKeys.subtitle" as TK)}
        onRefresh={() => {
          list.reload();
          catalogue.reload();
        }}
      />

      <div
        style={{
          padding: 16,
          marginBottom: 20,
          border: "1px solid var(--colorNeutralStroke1)",
          borderRadius: "10px",
        }}
      >
        <Text weight="semibold" block style={{ marginBottom: 2 }}>
          {t("platformApiKeys.connect" as TK)}
        </Text>
        <Text
          size={200}
          block
          style={{ color: tokens.colorNeutralForeground3, marginBottom: 10 }}
        >
          {t("platformApiKeys.connectDesc" as TK)}
        </Text>

        <TabList
          selectedValue={client}
          onTabSelect={(_, d) => setClient(d.value as string)}
          style={{ marginBottom: 10 }}
        >
          <Tab value="mcp">{t("platformApiKeys.mcpClient" as TK)}</Tab>
          <Tab value="rest">{t("platformApiKeys.restApi" as TK)}</Tab>
          <Tab value="python">{t("platformApiKeys.pythonSdk" as TK)}</Tab>
        </TabList>

        {client === "mcp" ? (
          <>
            <Text
              size={200}
              block
              style={{ color: tokens.colorNeutralForeground3, marginBottom: 8 }}
            >
              {t("platformApiKeys.mcpHint" as TK)}
            </Text>
            <CodeBlock code={connectSnippets().mcp} />
          </>
        ) : null}
        {client === "rest" ? (
          <>
            <Text
              size={200}
              block
              style={{ color: tokens.colorNeutralForeground3, marginBottom: 8 }}
            >
              {t("platformApiKeys.restHint" as TK)}
            </Text>
            <CodeBlock code={connectSnippets().rest} />
          </>
        ) : null}
        {client === "python" ? (
          <>
            <Text
              size={200}
              block
              style={{ color: tokens.colorNeutralForeground3, marginBottom: 8 }}
            >
              {t("platformApiKeys.pythonHint" as TK)}
            </Text>
            <CodeBlock code={connectSnippets().python} />
          </>
        ) : null}
      </div>

      <div
        style={{
          display: "flex",
          gap: 8,
          alignItems: "flex-end",
          marginBottom: 20,
        }}
      >
        <Button
          appearance="primary"
          icon={<AddRegular />}
          onClick={openCreate}
          data-shortcut="apply"
        >
          {t("platformApiKeys.create" as TK)}
        </Button>
      </div>

      {list.loading ? (
        <Loading />
      ) : list.error ? (
        <ErrorText error={list.error} />
      ) : (list.data ?? []).length === 0 ? (
        <EmptyState
          title={t("platformApiKeys.emptyTitle" as TK)}
          description={t("platformApiKeys.emptyDesc" as TK)}
        />
      ) : (
        <DataTable ariaLabel={t("platformApiKeys.title" as TK)}>
          <TableHeader>
            <TableRow>
              <TableHeaderCell>{t("platformApiKeys.name" as TK)}</TableHeaderCell>
              <TableHeaderCell>{t("platformApiKeys.prefix" as TK)}</TableHeaderCell>
              <TableHeaderCell style={{ width: 240 }}>{t("platformApiKeys.scopes" as TK)}</TableHeaderCell>
              <TableHeaderCell style={{ width: 120 }}>{t("platformApiKeys.status" as TK)}</TableHeaderCell>
              <TableHeaderCell style={{ width: 190 }}>{t("platformApiKeys.lastUsed" as TK)}</TableHeaderCell>
              <TableHeaderCell>{t("platformApiKeys.actions" as TK)}</TableHeaderCell>
            </TableRow>
          </TableHeader>
          <TableBody>
            {(list.data ?? []).map((key) => (
              <TableRow key={key.id}>
                <TableCell>{key.name}</TableCell>
                <TableCell style={{ fontFamily: "monospace" }}>
                  {key.key_prefix}
                </TableCell>
                <TableCell>
                  <Tooltip
                    content={
                      <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                        {key.scopes.map((s) => (
                          <span key={s}>
                            {effective(key).has(s)
                              ? s
                              : t("platformApiKeys.scopeInactive" as TK).replace("{scope}", s)}
                          </span>
                        ))}
                      </div>
                    }
                    relationship="description"
                  >
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                      {key.scopes.slice(0, 3).map((s) => (
                        <Badge
                          key={s}
                          appearance={effective(key).has(s) ? "tint" : "outline"}
                          color={effective(key).has(s) ? undefined : "subtle"}
                          size="small"
                        >
                          {s}
                        </Badge>
                      ))}
                      {key.scopes.length > 3 ? (
                        <Badge appearance="outline" size="small">
                          +{key.scopes.length - 3}
                        </Badge>
                      ) : null}
                    </div>
                  </Tooltip>
                </TableCell>
                <TableCell>
                  <Badge
                    color={key.enabled ? "success" : "subtle"}
                    appearance="filled"
                  >
                    {key.enabled
                      ? t("common.enabled" as TK)
                      : t("common.disabled" as TK)}
                  </Badge>
                  {key.disabled_reason === "lost_staff" ? (
                    <Text
                      size={100}
                      block
                      style={{ color: tokens.colorPaletteRedForeground1 }}
                    >
                      {t("platformApiKeys.lostStaff" as TK)}
                    </Text>
                  ) : null}
                </TableCell>
                <TableCell style={{ color: tokens.colorNeutralForeground3 }}>
                  {formatDate(key.last_used_at)}
                </TableCell>
                <TableCell>
                  <Tooltip content={t("common.edit" as TK)} relationship="label">
                    <Button
                      size="small"
                      appearance="subtle"
                      icon={<EditRegular />}
                      onClick={() => openEdit(key)}
                      aria-label={t("common.edit" as TK)}
                    />
                  </Tooltip>
                  <Tooltip
                    content={
                      key.enabled ? t("common.disable" as TK) : t("common.enable" as TK)
                    }
                    relationship="label"
                  >
                    <Button
                      size="small"
                      appearance="subtle"
                      icon={
                        key.enabled ? <ProhibitedRegular /> : <CheckmarkCircleRegular />
                      }
                      onClick={() => toggleEnabled(key)}
                      aria-label={
                        key.enabled ? t("common.disable" as TK) : t("common.enable" as TK)
                      }
                    />
                  </Tooltip>
                  <Tooltip content={t("platformApiKeys.rotate" as TK)} relationship="label">
                    <Button
                      size="small"
                      appearance="subtle"
                      icon={<ArrowSyncRegular />}
                      onClick={() => rotate(key)}
                      aria-label={t("platformApiKeys.rotate" as TK)}
                    />
                  </Tooltip>
                  <Tooltip content={t("common.delete" as TK)} relationship="label">
                    <Button
                      size="small"
                      appearance="subtle"
                      icon={<DeleteRegular />}
                      onClick={() => remove(key)}
                      aria-label={t("common.delete" as TK)}
                    />
                  </Tooltip>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </DataTable>
      )}

      <SecretDialog created={created} onClose={() => setCreated(null)} />

      <Dialog open={creating} onOpenChange={(_, d) => !d.open && setCreating(false)}>
        <DialogSurface style={{ maxWidth: 760 }}>
          <DialogBody>
            <DialogTitle>{t("platformApiKeys.createTitle" as TK)}</DialogTitle>
            <DialogContent>
              <Field label={t("platformApiKeys.name" as TK)} style={{ marginBottom: 14 }}>
                <Input value={name} onChange={(_, d) => setName(d.value)} />
              </Field>
              <Divider style={{ marginBottom: 12 }} />
              <Text weight="semibold" block style={{ marginBottom: 8 }}>
                {t("platformApiKeys.pickScopes" as TK)}
              </Text>
              {catalogue.loading ? (
                <Loading />
              ) : catalogue.error ? (
                <ErrorText error={catalogue.error} />
              ) : catalogue.data ? (
                <ScopePicker
                  catalogue={catalogue.data}
                  selected={scopes}
                  onChange={setScopes}
                />
              ) : null}
              {!isOwner ? (
                <Text
                  size={200}
                  block
                  style={{ color: tokens.colorNeutralForeground3, marginTop: 10 }}
                >
                  {t("platformApiKeys.ownerOnlyHint" as TK)}
                </Text>
              ) : null}
            </DialogContent>
            <DialogActions>
              <Button appearance="secondary" onClick={() => setCreating(false)}>
                {t("common.cancel" as TK)}
              </Button>
              <Button appearance="primary" icon={<KeyRegular />} onClick={create}>
                {t("common.create" as TK)}
              </Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>

      <Dialog
        open={editing !== null}
        onOpenChange={(_, d) => !d.open && setEditing(null)}
      >
        <DialogSurface style={{ maxWidth: 760 }}>
          <DialogBody>
            <DialogTitle>{t("platformApiKeys.editTitle" as TK)}</DialogTitle>
            <DialogContent>
              <Field label={t("platformApiKeys.name" as TK)} style={{ marginBottom: 14 }}>
                <Input value={editName} onChange={(_, d) => setEditName(d.value)} />
              </Field>
              <Divider style={{ marginBottom: 12 }} />
              {catalogue.data ? (
                <ScopePicker
                  catalogue={catalogue.data}
                  selected={editScopes}
                  onChange={setEditScopes}
                />
              ) : (
                <Textarea
                  value={editScopes.join("\n")}
                  onChange={(_, d) =>
                    setEditScopes(
                      d.value
                        .split("\n")
                        .map((s) => s.trim())
                        .filter(Boolean),
                    )
                  }
                />
              )}
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
