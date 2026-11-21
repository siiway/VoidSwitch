import {
  Button,
  Checkbox,
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  Field,
  Input,
  Text,
  Textarea,
  tokens,
} from "@fluentui/react-components";
import { AddRegular } from "@fluentui/react-icons";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../api/client";
import type { ModelEntry } from "../api/types";
import { EmptyState } from "./EmptyState";
import { ErrorText, Loading, useAsync } from "./ui";
import type { Translations } from "../i18n/locales/en";

type TK = keyof Translations;

/**
 * The allowed-models editor shared by both Void-Token pages: a multi-line field
 * (patterns are allowed) plus a picker that lists the platform catalog grouped the
 * same way the Models page groups it.
 *
 * The picker only ever *adds*: existing lines that are not platform models (a glob
 * such as `openrouter/*`) are kept as written, because a checkbox list cannot
 * express them.
 */
export function ModelSelectField({
  label,
  hint,
  value,
  onChange,
  disabled,
}: {
  label: string;
  hint?: string;
  value: string;
  onChange: (next: string) => void;
  disabled?: boolean;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);

  return (
    <Field label={label} hint={hint}>
      <Textarea
        value={value}
        rows={4}
        disabled={disabled}
        placeholder={t("tokens.allowedModelsPlaceholder" as TK)}
        onChange={(_, d) => onChange(d.value)}
      />
      <div style={{ marginTop: 8 }}>
        <Button
          icon={<AddRegular />}
          disabled={disabled}
          onClick={() => setOpen(true)}
        >
          {t("tokens.selectModels" as TK)}
        </Button>
      </div>
      {open ? (
        <ModelPickerDialog
          current={value}
          onClose={() => setOpen(false)}
          onConfirm={(next) => {
            onChange(next);
            setOpen(false);
          }}
        />
      ) : null}
    </Field>
  );
}

interface Group {
  key: string;
  label: string;
  models: ModelEntry[];
}

/** groupModels buckets the catalog by category, then provider passthrough, then
 * anything left over, matching the Models page's ordering. */
function groupModels(models: ModelEntry[]): Group[] {
  const groups = new Map<string, Group>();
  for (const m of models) {
    let key = "uncategorized";
    let label = "uncategorized";
    if (m.provider) {
      const slug = m.model_id.split("/")[0] ?? m.model_id;
      key = `provider:${slug}`;
      label = slug;
    } else if (m.category_name) {
      key = `cat:${m.category_name}`;
      label = m.category_name;
    }
    const existing = groups.get(key) ?? { key, label, models: [] };
    existing.models.push(m);
    groups.set(key, existing);
  }
  const order = (g: Group) =>
    g.key === "uncategorized" ? 2 : g.key.startsWith("provider:") ? 1 : 0;
  return [...groups.values()].sort(
    (a, b) => order(a) - order(b) || a.label.localeCompare(b.label),
  );
}

function ModelPickerDialog({
  current,
  onClose,
  onConfirm,
}: {
  current: string;
  onClose: () => void;
  onConfirm: (next: string) => void;
}) {
  const { t } = useTranslation();
  const models = useAsync<ModelEntry[]>(() => api.get("/api/models"), []);
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<Set<string>>(() => new Set());
  const currentLines = useMemo(
    () =>
      new Set(
        current
          .split(/[\n,]/)
          .map((s) => s.trim())
          .filter(Boolean),
      ),
    [current],
  );

  const groups = useMemo(() => {
    const all = (models.data ?? []).filter((m) => m.enabled);
    return groupModels(all);
  }, [models.data]);

  const visible = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return groups;
    return groups
      .map((g) => ({
        ...g,
        models: g.models.filter(
          (m) =>
            m.model_id.toLowerCase().includes(q) ||
            (m.display_name ?? "").toLowerCase().includes(q),
        ),
      }))
      .filter((g) => g.models.length > 0);
  }, [groups, search]);

  function toggle(id: string, on: boolean) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });
  }

  function confirm() {
    const before = [...currentLines];
    const known = new Set((models.data ?? []).map((m) => m.model_id));
    // Keep patterns and ids the catalog does not know about (a wildcard cannot be
    // expressed by a checkbox), then union with the picked ids.
    const kept = before.filter((line) => !known.has(line));
    const merged = [...new Set([...kept, ...selected])];
    onConfirm(merged.join("\n"));
  }

  return (
    <Dialog open onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface style={{ maxWidth: 760, width: "100%" }}>
        <DialogBody>
          <DialogTitle>{t("tokens.selectModelsTitle" as TK)}</DialogTitle>
          <DialogContent>
            <Text
              size={200}
              block
              style={{ color: tokens.colorNeutralForeground3, marginBottom: 10 }}
            >
              {t("tokens.selectModelsHint" as TK)}
            </Text>
            <Input
              value={search}
              placeholder={t("tokens.searchModels" as TK)}
              style={{ width: "100%", marginBottom: 10 }}
              onChange={(_, d) => setSearch(d.value)}
            />
            <div
              style={{
                display: "flex",
                flexDirection: "column",
                gap: 14,
                maxHeight: 380,
                overflowY: "auto",
                paddingRight: 6,
              }}
            >
              {models.loading ? (
                <Loading />
              ) : models.error ? (
                <ErrorText error={models.error} />
              ) : visible.length === 0 ? (
                <EmptyState
                  title={t("tokens.noModelsToPick" as TK)}
                  description={t("tokens.noModelsToPickHint" as TK)}
                />
              ) : (
                visible.map((group) => (
                  <div key={group.key}>
                    <Text weight="semibold" size={300} block style={{ marginBottom: 4 }}>
                      {group.key === "uncategorized"
                        ? t("models.filterUncategorized" as TK)
                        : group.label}
                    </Text>
                    <div style={{ display: "flex", flexDirection: "column", gap: 2, paddingLeft: 4 }}>
                      {group.models.map((m) => (
                        <Checkbox
                          key={m.model_id}
                          checked={selected.has(m.model_id) || currentLines.has(m.model_id)}
                          onChange={(_, d) => toggle(m.model_id, d.checked === true)}
                          label={
                            <span style={{ display: "flex", flexDirection: "column" }}>
                              <Text>{m.display_name || m.model_id}</Text>
                              <Text
                                size={100}
                                style={{ color: tokens.colorNeutralForeground3 }}
                              >
                                {m.model_id}
                              </Text>
                            </span>
                          }
                        />
                      ))}
                    </div>
                  </div>
                ))
              )}
            </div>
          </DialogContent>
          <DialogActions>
            <Button appearance="secondary" onClick={onClose}>
              {t("common.cancel" as TK)}
            </Button>
            <Button appearance="primary" onClick={confirm}>
              {t("tokens.addSelected" as TK)}
            </Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}