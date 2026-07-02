import {
  Button,
  Card,
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
  Tooltip,
  makeStyles,
  shorthands,
  tokens,
} from "@fluentui/react-components";
import {
  AddRegular,
  DeleteRegular,
  EditRegular,
  MegaphoneRegular,
} from "@fluentui/react-icons";
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import type { Announcement } from "../api/types";
import type { Translations } from "../i18n/locales/en";
import { formatDate, useConfirm, useNotify } from "./ui";

type TK = keyof Translations;

const useStyles = makeStyles({
  panel: {
    display: "flex",
    flexDirection: "column",
    gap: "10px",
    ...shorthands.padding("18px"),
    marginBottom: "24px",
  },
  head: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: "8px",
    flexWrap: "wrap",
  },
  headTitle: { display: "flex", alignItems: "center", gap: "8px", minWidth: 0 },
  list: { display: "flex", flexDirection: "column", gap: "10px" },
  item: {
    display: "flex",
    flexDirection: "column",
    gap: "4px",
    ...shorthands.padding("12px", "14px"),
    borderRadius: tokens.borderRadiusMedium,
    backgroundColor: tokens.colorNeutralBackground2,
    ...shorthands.border("1px", "solid", tokens.colorNeutralStroke2),
  },
  itemHead: {
    display: "flex",
    alignItems: "flex-start",
    justifyContent: "space-between",
    gap: "8px",
  },
  meta: { color: tokens.colorNeutralForeground3 },
  body: {
    whiteSpace: "pre-wrap",
    overflowWrap: "anywhere",
    wordBreak: "break-word",
    color: tokens.colorNeutralForeground2,
    marginTop: "2px",
  },
  actions: { display: "flex", gap: "2px", flexShrink: 0 },
  dim: { color: tokens.colorNeutralForeground3 },
});

function AuthorLine({ a }: { a: Announcement }) {
  const styles = useStyles();
  const { t } = useTranslation();
  return (
    <Text size={200} className={styles.meta}>
      {a.created_by_name
        ? t("announcements.by" as TK).replace("{name}", a.created_by_name)
        : t("common.unknown" as TK)}
      {" · "}
      {formatDate(a.created_at)}
      {a.edited ? ` · ${t("announcements.edited" as TK)}` : ""}
    </Text>
  );
}

function AnnouncementItem({
  a,
  onEdit,
  onDelete,
}: {
  a: Announcement;
  onEdit?: (a: Announcement) => void;
  onDelete?: (a: Announcement) => void;
}) {
  const styles = useStyles();
  const { t } = useTranslation();
  return (
    <div className={styles.item}>
      <div className={styles.itemHead}>
        <div style={{ minWidth: 0 }}>
          <Text weight="semibold" block style={{ overflowWrap: "anywhere" }}>
            {a.title}
          </Text>
          <AuthorLine a={a} />
        </div>
        {a.can_manage && onEdit && onDelete ? (
          <div className={styles.actions}>
            <Tooltip content={t("common.edit" as TK)} relationship="label">
              <Button
                size="small"
                appearance="subtle"
                icon={<EditRegular />}
                onClick={() => onEdit(a)}
                aria-label={t("common.edit" as TK)}
              />
            </Tooltip>
            <Tooltip content={t("common.delete" as TK)} relationship="label">
              <Button
                size="small"
                appearance="subtle"
                icon={<DeleteRegular />}
                onClick={() => onDelete(a)}
                aria-label={t("common.delete" as TK)}
              />
            </Tooltip>
          </div>
        ) : null}
      </div>
      {a.body ? (
        <Text size={300} className={styles.body}>
          {a.body}
        </Text>
      ) : null}
    </div>
  );
}

interface EditState {
  id: number | null;
  title: string;
  body: string;
}

function EditorDialog({
  state,
  onClose,
  onSaved,
}: {
  state: EditState | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { t } = useTranslation();
  const notify = useNotify();
  const [saving, setSaving] = useState(false);
  const [draft, setDraft] = useState<EditState>({ id: null, title: "", body: "" });

  useEffect(() => {
    if (state) setDraft(state);
  }, [state]);

  async function save() {
    const title = draft.title.trim();
    if (!title) {
      notify(t("common.saveFailed" as TK), t("announcements.titleRequired" as TK), "error");
      return;
    }
    setSaving(true);
    try {
      if (draft.id == null) {
        await api.post("/api/announcements", { title, body: draft.body });
        notify(t("announcements.published" as TK), title, "success");
      } else {
        await api.patch(`/api/announcements/${draft.id}`, { title, body: draft.body });
        notify(t("announcements.saved" as TK), title, "success");
      }
      onClose();
      onSaved();
    } catch (e) {
      notify(
        t("common.saveFailed" as TK),
        e instanceof Error ? e.message : String(e),
        "error",
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={state !== null} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface>
        <DialogBody>
          <DialogTitle>
            {state?.id == null
              ? t("announcements.newTitle" as TK)
              : t("announcements.editTitle" as TK)}
          </DialogTitle>
          <DialogContent
            style={{ display: "flex", flexDirection: "column", gap: 12, paddingTop: 8 }}
          >
            <Field label={t("announcements.fieldTitle" as TK)}>
              <Input
                value={draft.title}
                placeholder={t("announcements.titlePlaceholder" as TK)}
                onChange={(_, d) => setDraft((s) => ({ ...s, title: d.value }))}
              />
            </Field>
            <Field label={t("announcements.fieldBody" as TK)}>
              <Textarea
                value={draft.body}
                rows={6}
                placeholder={t("announcements.bodyPlaceholder" as TK)}
                onChange={(_, d) => setDraft((s) => ({ ...s, body: d.value }))}
              />
            </Field>
          </DialogContent>
          <DialogActions>
            <Button appearance="secondary" onClick={onClose}>
              {t("common.cancel" as TK)}
            </Button>
            <Button appearance="primary" disabled={saving} onClick={save}>
              {state?.id == null ? t("announcements.publish" as TK) : t("common.save" as TK)}
            </Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}

/**
 * The dashboard home announcements panel: a preview of the latest few (count
 * from ``announcements_home_count``), with "view all" for the rest, plus publish
 * / edit / delete for staff (edit/delete gated by the backend's tier rules).
 */
export function AnnouncementsPanel() {
  const styles = useStyles();
  const { t } = useTranslation();
  const { isStaff } = useAuth();
  const notify = useNotify();
  const confirm = useConfirm();

  const [items, setItems] = useState<Announcement[]>([]);
  const [homeCount, setHomeCount] = useState(3);
  const [showAll, setShowAll] = useState(false);
  const [edit, setEdit] = useState<EditState | null>(null);

  const load = useCallback(async () => {
    try {
      const list = await api.get<Announcement[]>("/api/announcements", { limit: 200 });
      setItems(list);
    } catch {
      /* silent — the panel is non-critical */
    }
  }, []);

  useEffect(() => {
    void load();
    api
      .get<{ announcements_home_count?: number }>("/api/auth/config")
      .then((c) =>
        setHomeCount(
          typeof c.announcements_home_count === "number" ? c.announcements_home_count : 3,
        ),
      )
      .catch(() => {});
  }, [load]);

  async function remove(a: Announcement) {
    const ok = await confirm({
      title: t("announcements.deleteTitle" as TK),
      message: t("announcements.deleteMsg" as TK).replace("{title}", a.title),
      confirmLabel: t("common.delete" as TK),
      tone: "danger",
    });
    if (!ok) return;
    try {
      await api.del(`/api/announcements/${a.id}`);
      notify(t("announcements.deleted" as TK), a.title, "success");
      void load();
    } catch (e) {
      notify(
        t("common.deleteFailed" as TK),
        e instanceof Error ? e.message : String(e),
        "error",
      );
    }
  }

  const preview = homeCount > 0 ? items.slice(0, homeCount) : [];
  const hasMore = items.length > preview.length;

  return (
    <Card className={styles.panel}>
      <div className={styles.head}>
        <div className={styles.headTitle}>
          <MegaphoneRegular />
          <Text size={500} weight="semibold">
            {t("announcements.title" as TK)}
          </Text>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          {items.length > 0 ? (
            <Button size="small" appearance="subtle" onClick={() => setShowAll(true)}>
              {t("announcements.viewAll" as TK).replace("{count}", String(items.length))}
            </Button>
          ) : null}
          {isStaff ? (
            <Button
              size="small"
              appearance="primary"
              icon={<AddRegular />}
              onClick={() => setEdit({ id: null, title: "", body: "" })}
            >
              {t("announcements.publish" as TK)}
            </Button>
          ) : null}
        </div>
      </div>

      {items.length === 0 ? (
        <Text size={200} className={styles.dim}>
          {t("announcements.empty" as TK)}
        </Text>
      ) : (
        <div className={styles.list}>
          {preview.map((a) => (
            <AnnouncementItem
              key={a.id}
              a={a}
              onEdit={(x) => setEdit({ id: x.id, title: x.title, body: x.body })}
              onDelete={remove}
            />
          ))}
          {hasMore ? (
            <Text size={200} className={styles.dim}>
              {t("announcements.moreHidden" as TK).replace(
                "{count}",
                String(items.length - preview.length),
              )}
            </Text>
          ) : null}
        </div>
      )}

      <EditorDialog state={edit} onClose={() => setEdit(null)} onSaved={load} />

      <Dialog open={showAll} onOpenChange={(_, d) => !d.open && setShowAll(false)}>
        <DialogSurface>
          <DialogBody>
            <DialogTitle>{t("announcements.allTitle" as TK)}</DialogTitle>
            <DialogContent
              style={{
                display: "flex",
                flexDirection: "column",
                gap: 10,
                paddingTop: 8,
                maxHeight: "60vh",
                overflowY: "auto",
              }}
            >
              {items.map((a) => (
                <AnnouncementItem
                  key={a.id}
                  a={a}
                  onEdit={(x) => {
                    setShowAll(false);
                    setEdit({ id: x.id, title: x.title, body: x.body });
                  }}
                  onDelete={remove}
                />
              ))}
            </DialogContent>
            <DialogActions>
              <Button appearance="primary" onClick={() => setShowAll(false)}>
                {t("common.close" as TK)}
              </Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </Card>
  );
}

// sessionStorage flag set at login (callback / dev-login) so the popup shows
// once per fresh sign-in, per the "popup on every login" requirement.
export const ANNOUNCE_POPUP_FLAG = "voidswitch.announce.pending";

/**
 * The login popup: shown once after a fresh sign-in if any announcements exist.
 * Read-only — publishing/editing happens from the dashboard panel.
 */
export function AnnouncementsPopup() {
  const { t } = useTranslation();
  const [items, setItems] = useState<Announcement[] | null>(null);

  useEffect(() => {
    if (sessionStorage.getItem(ANNOUNCE_POPUP_FLAG) !== "1") return;
    sessionStorage.removeItem(ANNOUNCE_POPUP_FLAG);
    api
      .get<Announcement[]>("/api/announcements", { limit: 20 })
      .then((list) => {
        if (list.length > 0) setItems(list);
      })
      .catch(() => {});
  }, []);

  const open = items !== null && items.length > 0;
  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && setItems(null)}>
      <DialogSurface>
        <DialogBody>
          <DialogTitle>
            <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
              <MegaphoneRegular />
              {t("announcements.popupTitle" as TK)}
            </span>
          </DialogTitle>
          <DialogContent
            style={{
              display: "flex",
              flexDirection: "column",
              gap: 10,
              paddingTop: 8,
              maxHeight: "60vh",
              overflowY: "auto",
            }}
          >
            {(items ?? []).map((a) => (
              <AnnouncementCardReadonly key={a.id} a={a} />
            ))}
          </DialogContent>
          <DialogActions>
            <Button appearance="primary" onClick={() => setItems(null)}>
              {t("common.close" as TK)}
            </Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}

function AnnouncementCardReadonly({ a }: { a: Announcement }) {
  return <AnnouncementItem a={a} />;
}

/** Marks that the announcements popup should show on the next dashboard load. */
export function armAnnouncementsPopup(): void {
  sessionStorage.setItem(ANNOUNCE_POPUP_FLAG, "1");
}
