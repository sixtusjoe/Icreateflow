"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { ArrowLeft, FileText, Plus, Trash2, Save } from "lucide-react";
import { toast } from "sonner";
import {
  listOutreachTemplates,
  createOutreachTemplate,
  updateOutreachTemplate,
  deleteOutreachTemplate,
  previewOutreachTemplate,
  type OutreachTemplate,
  setTemplateAttachment,
  clearTemplateAttachment,
  templateAttachmentUrl,
} from "@/lib/api";
import { ConfirmModal } from "@/components/ui/confirm-modal";
import { PageIcon, inputClass, apiErrorMessage } from "../ui";

const STARTER =
  "Hello {{username}}, we came across your content and wanted to reach out about {{offer}}.";

export default function OutreachTemplatesPage() {
  const [templates, setTemplates] = useState<OutreachTemplate[]>([]);
  const [selected, setSelected] = useState<OutreachTemplate | null>(null);
  const imageRef = useRef<HTMLInputElement>(null);
  const [imageBusy, setImageBusy] = useState(false);
  const [name, setName] = useState("");
  const [body, setBody] = useState(STARTER);
  const [preview, setPreview] = useState("");
  const [error, setError] = useState("");
  const [variables, setVariables] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState<OutreachTemplate | null>(null);
  const [deleting, setDeleting] = useState(false);

  const load = () =>
    listOutreachTemplates()
      .then(setTemplates)
      .catch((e) => toast.error(apiErrorMessage(e, "Failed to load templates")));

  useEffect(() => {
    load();
  }, []);

  // Live validation + preview. Debounced so every keystroke isn't a request.
  useEffect(() => {
    const timer = setTimeout(() => {
      if (!body.trim()) {
        setPreview("");
        setVariables([]);
        setError("");
        return;
      }
      previewOutreachTemplate(body)
        .then((r) => {
          setPreview(r.preview);
          setVariables(r.variables);
          setError("");
        })
        .catch((e) => {
          setPreview("");
          setError(apiErrorMessage(e, "Template is not valid"));
        });
    }, 300);
    return () => clearTimeout(timer);
  }, [body]);

  const startNew = () => {
    setSelected(null);
    setName("");
    setBody(STARTER);
  };

  const select = (template: OutreachTemplate) => {
    setSelected(template);
    setName(template.name);
    setBody(template.body);
  };

  const handleAttach = async (file?: File) => {
    if (!file || !selected) return;
    setImageBusy(true);
    try {
      const updated = await setTemplateAttachment(selected.id, file);
      setSelected(updated);
      toast.success("Image attached — new campaigns from this template get a copy");
      load();
    } catch (e) {
      toast.error(apiErrorMessage(e, "Could not attach that image"));
    } finally {
      setImageBusy(false);
      if (imageRef.current) imageRef.current.value = "";
    }
  };

  const handleClearImage = async () => {
    if (!selected) return;
    setImageBusy(true);
    try {
      const updated = await clearTemplateAttachment(selected.id);
      setSelected(updated);
      toast.success("Image removed");
      load();
    } catch (e) {
      toast.error(apiErrorMessage(e, "Could not remove the image"));
    } finally {
      setImageBusy(false);
    }
  };

  const handleSave = async () => {
    if (!name.trim()) return toast.error("Template name is required");
    setBusy(true);
    try {
      if (selected) {
        await updateOutreachTemplate(selected.id, { name: name.trim(), body });
        toast.success("Template saved");
      } else {
        const created = await createOutreachTemplate({ name: name.trim(), body });
        setSelected(created);
        toast.success("Template created");
      }
      load();
    } catch (e) {
      toast.error(apiErrorMessage(e, "Failed to save template"));
    } finally {
      setBusy(false);
    }
  };

  const handleDelete = async () => {
    if (!confirmDelete) return;
    setDeleting(true);
    try {
      await deleteOutreachTemplate(confirmDelete.id);
      if (selected?.id === confirmDelete.id) startNew();
      setConfirmDelete(null);
      load();
      toast.success("Template deleted");
    } catch (e) {
      toast.error(apiErrorMessage(e, "Failed to delete template"));
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div className="mx-auto max-w-5xl">
      <Link
        href="/outreach"
        className="mb-4 inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="h-4 w-4" /> Outreach
      </Link>

      <div className="mb-6 flex items-center gap-3">
        <PageIcon icon={FileText} />
        <div>
          <h1 className="text-xl md:text-2xl font-bold tracking-tight">Message templates</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Reusable messages with variables. Every campaign freezes its own copy at start.
          </p>
        </div>
      </div>

      <div className="grid gap-6 md:grid-cols-3">
        <div className="rounded-xl border border-border bg-card">
          <div className="flex items-center justify-between border-b border-border px-4 py-3">
            <h2 className="text-sm font-semibold">Saved</h2>
            <button
              onClick={startNew}
              className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs font-medium hover:bg-muted"
            >
              <Plus className="h-3.5 w-3.5" /> New
            </button>
          </div>
          {templates.length === 0 ? (
            <p className="px-4 py-6 text-center text-sm text-muted-foreground">
              No templates yet.
            </p>
          ) : (
            <ul className="divide-y divide-border/60">
              {templates.map((t) => (
                <li key={t.id} className="flex items-center justify-between gap-2 px-4 py-2.5">
                  <button
                    onClick={() => select(t)}
                    className={`min-w-0 flex-1 text-left text-sm ${
                      selected?.id === t.id ? "font-semibold" : ""
                    }`}
                  >
                    <span className="block truncate">{t.name}</span>
                    <span className="block truncate text-xs text-muted-foreground">
                      {(t.variables ?? []).map((v) => `{{${v}}}`).join(" ") || "no variables"}
                    </span>
                  </button>
                  <button
                    onClick={() => setConfirmDelete(t)}
                    aria-label={`Delete ${t.name}`}
                    className="rounded-md p-1.5 text-muted-foreground hover:bg-muted hover:text-destructive"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="space-y-4 md:col-span-2">
          <div>
            <label className="mb-1.5 block text-sm font-medium">Name</label>
            <input
              className={inputClass}
              placeholder="e.g. Creator intro"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </div>
          <div>
            <label className="mb-1.5 block text-sm font-medium">Message</label>
            <textarea
              rows={6}
              className={inputClass}
              value={body}
              onChange={(e) => setBody(e.target.value)}
            />
            <p className="mt-1 text-xs text-muted-foreground">
              {"Built-in variables: {{username}}, {{profile_url}}, {{campaign_name}}, {{account_name}}. Any other name is filled from the campaign's variables."}
            </p>
          </div>

          <div>
            <label className="mb-1.5 block text-sm font-medium">Image</label>
            {!selected ? (
              <p className="text-xs text-muted-foreground">
                Save the template first, then an image can be attached to it.
              </p>
            ) : selected.has_attachment ? (
              <div className="rounded-xl border border-border p-3">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={templateAttachmentUrl(selected.id)}
                  alt={selected.attachment_name || "Template image"}
                  className="max-h-40 w-full rounded-lg object-contain"
                />
                <p className="mt-2 truncate text-xs text-muted-foreground">
                  {selected.attachment_name}
                </p>
                <button
                  onClick={handleClearImage}
                  disabled={imageBusy}
                  className="mt-2 rounded-lg border border-border px-3 py-1.5 text-xs font-medium hover:bg-muted disabled:opacity-50"
                >
                  Remove image
                </button>
              </div>
            ) : (
              <>
                <input
                  ref={imageRef}
                  type="file"
                  accept="image/jpeg,image/png,image/gif,image/webp"
                  className="hidden"
                  onChange={(e) => handleAttach(e.target.files?.[0])}
                />
                <button
                  onClick={() => imageRef.current?.click()}
                  disabled={imageBusy}
                  className="rounded-lg border border-border px-3 py-1.5 text-xs font-medium hover:bg-muted disabled:opacity-50"
                >
                  Add image
                </button>
                <p className="mt-1.5 text-xs text-muted-foreground">
                  Sent with the message. Campaigns made from this template get their
                  own copy, so editing the template later cannot change what a
                  running campaign sends. Instagram only — TikTok&apos;s web
                  composer is text-only.
                </p>
              </>
            )}
          </div>

          {error ? (
            <div className="rounded-xl border border-destructive/40 bg-destructive/10 p-4 text-sm text-destructive">
              {error}
            </div>
          ) : (
            preview && (
              <div className="rounded-xl border border-border bg-card p-4">
                <p className="text-xs uppercase tracking-wide text-muted-foreground">Preview</p>
                <p className="mt-1.5 whitespace-pre-wrap text-sm">{preview}</p>
                {variables.length > 0 && (
                  <p className="mt-3 text-xs text-muted-foreground">
                    Variables: {variables.join(", ")}
                  </p>
                )}
              </div>
            )
          )}

          <button
            onClick={handleSave}
            disabled={busy || !!error}
            className="inline-flex min-h-[44px] items-center gap-2 rounded-lg bg-foreground px-5 text-sm font-medium text-background hover:opacity-90 disabled:opacity-50"
          >
            <Save className="h-4 w-4" />
            {busy ? "Saving…" : selected ? "Save changes" : "Create template"}
          </button>
        </div>
      </div>

      <ConfirmModal
        open={confirmDelete !== null}
        onOpenChange={(open) => !open && setConfirmDelete(null)}
        title="Delete template?"
        description={`“${confirmDelete?.name}” will be removed. Campaigns already using it keep their own copy of the message.`}
        confirmLabel="Delete"
        variant="danger"
        loading={deleting}
        onConfirm={handleDelete}
      />
    </div>
  );
}
