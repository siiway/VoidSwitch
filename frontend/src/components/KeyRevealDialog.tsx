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
  Option,
  Spinner,
  Text,
  tokens,
} from "@fluentui/react-components";
import { EyeRegular } from "@fluentui/react-icons";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { Translations } from "../i18n/locales/en";
import { useTranslation } from "react-i18next";

import { useNotify } from "./ui";

type Scope = "provider" | "token" | "all";

interface ProviderMatch {
  provider_id: number;
  provider_name: string;
  key_id: number;
  position: number;
  preview: string;
  comment?: string | null;
  pool: string;
  added_by_name?: string | null;
}

interface TokenMatch {
  token_id: number;
  name: string;
  owner_id: number;
  owner_name?: string | null;
  total_requests: number;
  total_tokens: number;
  enabled: boolean;
  created_at: string;
  deleted: boolean;
}

interface RevealResult {
  provider_matches: ProviderMatch[];
  token_matches: TokenMatch[];
}

export function KeyRevealDialog({
  open,
  defaultScope,
  onClose,
}: {
  open: boolean;
  defaultScope: Scope;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  type TK = keyof Translations;
  const notify = useNotify();
  const navigate = useNavigate();
  const [scope, setScope] = useState<Scope>(defaultScope);
  const [secret, setSecret] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<RevealResult | null>(null);

  async function reveal() {
    setBusy(true);
    try {
      const r = await api.post<RevealResult>("/api/admin/reveal/key", {
        key: secret,
        scope,
      });
      setResult(r);
      setSecret("");
    } catch (e) {
      notify(t("reveal.failed" as TK), e instanceof Error ? e.message : String(e), "error");
    } finally {
      setBusy(false);
    }
  }

  function close() {
    setSecret("");
    setResult(null);
    setScope(defaultScope);
    onClose();
  }

  const total = (result?.provider_matches.length ?? 0) + (result?.token_matches.length ?? 0);

  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && close()}>
      <DialogSurface>
        <DialogBody>
          <DialogTitle>{result ? t("reveal.results" as TK) : t("reveal.title" as TK)}</DialogTitle>
          <DialogContent style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            {result ? (
              total === 0 ? (
                <Text style={{ color: tokens.colorNeutralForeground3 }}>{t("reveal.noMatches" as TK)}</Text>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                  {result.provider_matches.map((m) => (
                    <div key={`p-${m.provider_id}-${m.key_id}`}>
                      <Text weight="semibold" block>
                        {m.provider_name} #{m.position}
                      </Text>
                      <Text size={200} block style={{ color: tokens.colorNeutralForeground3 }}>
                        {m.comment || "-"} · {m.pool || "-"} · {m.added_by_name || "-"}
                      </Text>
                    </div>
                  ))}
                  {result.token_matches.map((m) => (
                    <div key={`t-${m.token_id}`}>
                      <Text weight="semibold" block>
                        {m.name}#{m.token_id}
                      </Text>
                      <Text size={200} block style={{ color: tokens.colorNeutralForeground3 }}>
                        {m.owner_name || `#${m.owner_id}`} · {m.total_requests} / {m.total_tokens} · {m.enabled ? t("common.enabled" as TK) : t("common.disabled" as TK)}
                      </Text>
                      <Button
                        size="small"
                        appearance="subtle"
                        onClick={() => navigate(`/logs?tab=requests&token_id=${m.token_id}`)}
                      >
                        {t("reveal.openRequestLogs" as TK)}
                      </Button>
                      <Button
                        size="small"
                        appearance="subtle"
                        onClick={() => navigate(`/logs?tab=audit&target_type=token`)}
                      >
                        {t("reveal.openAuditLogs" as TK)}
                      </Button>
                    </div>
                  ))}
                </div>
              )
            ) : (
              <>
                <Field label={t("reveal.key" as TK)}>
                  <Input type="text" autoComplete="off" value={secret} onChange={(_, d) => setSecret(d.value)} />
                </Field>
                <Field label={t("reveal.scope" as TK)}>
                  <Dropdown
                    value={t(`reveal.scope_${scope}` as TK)}
                    selectedOptions={[scope]}
                    onOptionSelect={(_, d) => d.optionValue && setScope(d.optionValue as Scope)}
                  >
                    {(["provider", "token", "all"] as Scope[]).map((s) => (
                      <Option key={s} value={s}>{t(`reveal.scope_${s}` as TK)}</Option>
                    ))}
                  </Dropdown>
                </Field>
              </>
            )}
          </DialogContent>
          <DialogActions>
            <Button appearance="secondary" onClick={close}>{t("common.close" as TK)}</Button>
            {!result ? (
              <Button appearance="primary" icon={busy ? <Spinner size="tiny" /> : <EyeRegular />} disabled={busy || !secret.trim()} onClick={reveal}>
                {t("reveal.reveal" as TK)}
              </Button>
            ) : null}
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}
