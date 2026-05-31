import {
  Badge,
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
  SpinButton,
  Switch,
  TableBody,
  TableCell,
  TableHeader,
  TableHeaderCell,
  TableRow,
  Textarea,
  tokens,
} from "@fluentui/react-components";
import {
  AddRegular,
  DeleteRegular,
  EditRegular,
  KeyRegular,
} from "@fluentui/react-icons";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { AdapterMeta, Provider } from "../api/types";
import {
  DataTable,
  ErrorText,
  Loading,
  PageHeader,
  useAsync,
  useConfirm,
  useNotify,
} from "../components/ui";

interface FormState {
  id?: number;
  name: string;
  type: string;
  base_url: string;
  models: string;
  priority: number;
  weight: number;
  enabled: boolean;
  drop_opencode_identity_block: boolean;
}

const EMPTY: FormState = {
  name: "",
  type: "openai",
  base_url: "",
  models: "",
  priority: 100,
  weight: 1,
  enabled: true,
  drop_opencode_identity_block: false,
};

export function Providers() {
  const navigate = useNavigate();
  const notify = useNotify();
  const confirm = useConfirm();
  const providers = useAsync<Provider[]>(() => api.get("/api/admin/providers"));
  const catalog = useAsync<AdapterMeta[]>(() =>
    api.get("/api/admin/providers/catalog/types"),
  );
  const [form, setForm] = useState<FormState | null>(null);
  const [saving, setSaving] = useState(false);

  function openCreate() {
    setForm({ ...EMPTY });
  }

  function openEdit(p: Provider) {
    setForm({
      id: p.id,
      name: p.name,
      type: p.type,
      base_url: p.base_url,
      models: p.models.join("\n"),
      priority: p.priority,
      weight: p.weight,
      enabled: p.enabled,
      drop_opencode_identity_block: p.drop_opencode_identity_block,
    });
  }

  function applyType(type: string) {
    const meta = catalog.data?.find((c) => c.type === type);
    setForm((f) =>
      f
        ? {
            ...f,
            type,
            base_url: f.base_url || meta?.default_base_url || "",
            models: f.models || (meta?.default_models.join("\n") ?? ""),
          }
        : f,
    );
  }

  async function save() {
    if (!form) return;
    const models = form.models
      .split(/[\n,]/)
      .map((s) => s.trim())
      .filter(Boolean);
    const payload = {
      name: form.name,
      type: form.type,
      base_url: form.base_url,
      models,
      priority: form.priority,
      weight: form.weight,
      enabled: form.enabled,
      drop_opencode_identity_block: form.drop_opencode_identity_block,
    };
    setSaving(true);
    try {
      if (form.id) {
        await api.patch(`/api/admin/providers/${form.id}`, payload);
        notify("Provider updated", form.name, "success");
      } else {
        await api.post("/api/admin/providers", payload);
        notify("Provider created", form.name, "success");
      }
      setForm(null);
      providers.reload();
    } catch (e) {
      notify(
        "Save failed",
        e instanceof Error ? e.message : String(e),
        "error",
      );
    } finally {
      setSaving(false);
    }
  }

  async function remove(p: Provider) {
    const ok = await confirm({
      title: "Delete provider",
      message: `Delete "${p.name}" and all its keys? This cannot be undone.`,
      confirmLabel: "Delete",
      tone: "danger",
    });
    if (!ok) return;
    try {
      await api.del(`/api/admin/providers/${p.id}`);
      notify("Provider deleted", p.name, "success");
      providers.reload();
    } catch (e) {
      notify(
        "Delete failed",
        e instanceof Error ? e.message : String(e),
        "error",
      );
    }
  }

  return (
    <div>
      <PageHeader
        title="Providers"
        subtitle="Upstream LLM platforms and the models they serve"
        action={
          <Button
            appearance="primary"
            icon={<AddRegular />}
            onClick={openCreate}
          >
            Add provider
          </Button>
        }
      />

      {providers.loading ? (
        <Loading />
      ) : providers.error ? (
        <ErrorText error={providers.error} />
      ) : (
        <DataTable ariaLabel="Providers">
          <TableHeader>
            <TableRow>
              <TableHeaderCell>Name</TableHeaderCell>
              <TableHeaderCell>Type</TableHeaderCell>
              <TableHeaderCell>Base URL</TableHeaderCell>
              <TableHeaderCell>Keys</TableHeaderCell>
              <TableHeaderCell>Priority</TableHeaderCell>
              <TableHeaderCell>Status</TableHeaderCell>
              <TableHeaderCell>Actions</TableHeaderCell>
            </TableRow>
          </TableHeader>
          <TableBody>
            {(providers.data ?? []).map((p) => (
              <TableRow key={p.id}>
                <TableCell>{p.name}</TableCell>
                <TableCell>{p.type}</TableCell>
                <TableCell style={{ color: tokens.colorNeutralForeground3 }}>
                  {p.base_url}
                </TableCell>
                <TableCell>
                  {p.active_key_count}/{p.key_count}
                </TableCell>
                <TableCell>{p.priority}</TableCell>
                <TableCell>
                  <Badge
                    color={p.enabled ? "success" : "subtle"}
                    appearance="filled"
                  >
                    {p.enabled ? "enabled" : "disabled"}
                  </Badge>
                </TableCell>
                <TableCell>
                  <Button
                    size="small"
                    icon={<KeyRegular />}
                    appearance="subtle"
                    onClick={() => navigate(`/providers/${p.id}/keys`)}
                  >
                    Keys
                  </Button>
                  <Button
                    size="small"
                    icon={<EditRegular />}
                    appearance="subtle"
                    onClick={() => openEdit(p)}
                  />
                  <Button
                    size="small"
                    icon={<DeleteRegular />}
                    appearance="subtle"
                    onClick={() => remove(p)}
                  />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </DataTable>
      )}

      <Dialog
        open={form !== null}
        onOpenChange={(_, d) => !d.open && setForm(null)}
      >
        <DialogSurface>
          <DialogBody>
            <DialogTitle>
              {form?.id ? "Edit provider" : "Add provider"}
            </DialogTitle>
            <DialogContent
              style={{
                display: "flex",
                flexDirection: "column",
                gap: 12,
                paddingTop: 8,
              }}
            >
              <Field label="Name" required>
                <Input
                  value={form?.name ?? ""}
                  disabled={!!form?.id}
                  onChange={(_, d) =>
                    setForm((f) => (f ? { ...f, name: d.value } : f))
                  }
                />
              </Field>
              <Field label="Adapter type">
                <Dropdown
                  value={form?.type ?? ""}
                  selectedOptions={form ? [form.type] : []}
                  onOptionSelect={(_, d) =>
                    d.optionValue && applyType(d.optionValue)
                  }
                >
                  {(catalog.data ?? []).map((c) => (
                    <Option key={c.type} value={c.type} text={c.type}>
                      {c.type} ({c.style})
                    </Option>
                  ))}
                </Dropdown>
              </Field>
              <Field label="Base URL">
                <Input
                  value={form?.base_url ?? ""}
                  onChange={(_, d) =>
                    setForm((f) => (f ? { ...f, base_url: d.value } : f))
                  }
                />
              </Field>
              <Field label="Models (one per line; use * for any)">
                <Textarea
                  value={form?.models ?? ""}
                  rows={4}
                  onChange={(_, d) =>
                    setForm((f) => (f ? { ...f, models: d.value } : f))
                  }
                />
              </Field>
              <div style={{ display: "flex", gap: 12 }}>
                <Field label="Priority (lower = preferred)">
                  <SpinButton
                    value={form?.priority ?? 100}
                    onChange={(_, d) =>
                      setForm((f) =>
                        f ? { ...f, priority: d.value ?? f.priority } : f,
                      )
                    }
                  />
                </Field>
                <Field label="Weight">
                  <SpinButton
                    value={form?.weight ?? 1}
                    min={1}
                    onChange={(_, d) =>
                      setForm((f) =>
                        f ? { ...f, weight: d.value ?? f.weight } : f,
                      )
                    }
                  />
                </Field>
              </div>
              <Switch
                label="Enabled"
                checked={form?.enabled ?? true}
                onChange={(_, d) =>
                  setForm((f) => (f ? { ...f, enabled: d.checked } : f))
                }
              />
              {form?.type === "claude-code" && (
                <Switch
                  label="Drop OpenCode identity block (send only the Claude Code identity, not the caller's system prompt)"
                  checked={form?.drop_opencode_identity_block ?? false}
                  onChange={(_, d) =>
                    setForm((f) =>
                      f ? { ...f, drop_opencode_identity_block: d.checked } : f,
                    )
                  }
                />
              )}
            </DialogContent>
            <DialogActions>
              <Button appearance="secondary" onClick={() => setForm(null)}>
                Cancel
              </Button>
              <Button
                appearance="primary"
                disabled={saving || !form?.name}
                onClick={save}
              >
                {form?.id ? "Save" : "Create"}
              </Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </div>
  );
}
