"use client";

/**
 * New / edit template.
 *
 * Mirrors `services/outreach/templates.py`: `{{name}}` placeholders, four
 * built-ins always available, 4,000 characters of body, 2,000 of rendered
 * message, and a hard refusal on a malformed brace.
 *
 * The right half renders the message as a target would receive it, with
 * the built-ins standing in for real values. That is the whole argument
 * for a preview: a template is written in tokens and read as prose, and
 * the only way to know the prose works is to see it.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { Check, Upload, User, X as XIcon } from "lucide-react";
import { toast } from "sonner";
import {
  clearTemplateAttachment,
  createOutreachTemplate,
  setTemplateAttachment,
  templateAttachmentUrl,
  updateOutreachTemplate,
  type OutreachTemplate,
} from "@/lib/api";
import {
  Dialog,
  DialogBody,
  DialogFoot,
  DialogHead,
  Field,
  FieldLabel,
  GhostButton,
  Hint,
  Input,
  Textarea,
} from "@/components/kit/dialog";
import { PrimaryButton } from "@/components/kit";
import { BUILTIN_VARIABLES, MAX_BODY_LENGTH, ownVariables, validateTemplate } from "./template";
import { apiErrorMessage } from "@/components/kit/format";

/** Stand-ins for the built-ins, so the preview reads as a real message. */
const SAMPLE: Record<string, string> = {
  username: "azeriakenndiee",
  profile_url: "tiktok.com/@azeriakenndiee",
  campaign_name: "2ND TIKTOK CAMP",
  account_name: "RealMic TikTok",
};

/** The server's own cap on what a rendered message may come to. */
const MAX_RENDERED = 2000;

export function TemplateDialog({
  open,
  onClose,
  template,
  usedBy,
  onSaved,
}: {
  open: boolean;
  onClose: () => void;
  /** Null for a new template. */
  template: OutreachTemplate | null;
  usedBy: number;
  onSaved: () => void;
}) {
  const [name, setName] = useState("");
  const [body, setBody] = useState("");
  const [defaults, setDefaults] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const bodyRef = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    setName(template?.name ?? "");
    setBody(template?.body ?? "Hi {{username}}, we came across your content and wanted to reach out about {{offer}}.");
    let parsed: Record<string, string> = {};
    if (template?.defaults) {
      try {
        const d = JSON.parse(template.defaults);
        if (d && typeof d === "object") parsed = d;
      } catch {
        // A defaults blob that will not parse is not worth failing over —
        // the fields simply start empty.
      }
    }
    setDefaults(parsed);
  }, [open, template]);

  const error = validateTemplate(body);
  const own = ownVariables(body);

  /** The message as a target would receive it. */
  const preview = useMemo(
    () =>
      body.replace(/\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}/g, (whole, key: string) =>
        SAMPLE[key] ?? defaults[key] ?? whole,
      ),
    [body, defaults],
  );
  const unfilled = own.filter((k) => !defaults[k]?.trim());

  /** Drop a placeholder in at the caret, rather than making people type braces. */
  const insert = (token: string) => {
    const el = bodyRef.current;
    if (!el) return setBody((b) => b + token);
    const start = el.selectionStart ?? body.length;
    const end = el.selectionEnd ?? start;
    setBody(body.slice(0, start) + token + body.slice(end));
    requestAnimationFrame(() => {
      el.focus();
      el.setSelectionRange(start + token.length, start + token.length);
    });
  };

  const save = async () => {
    if (!name.trim()) return toast.error("Give the template a name");
    setSaving(true);
    try {
      const payload = { name: name.trim(), body, defaults };
      const saved = template
        ? await updateOutreachTemplate(template.id, payload)
        : await createOutreachTemplate(payload);
      // The template has to exist before an image can hang off it, so a
      // pending file is a second call rather than part of the save.
      const pending = fileRef.current?.files?.[0];
      if (pending) {
        try {
          await setTemplateAttachment(saved.id, pending);
        } catch (e) {
          toast.error(apiErrorMessage(e, "Template saved, but the image did not attach"));
        }
      }
      toast.success(template ? "Template saved" : `Template “${saved.name}” created`);
      onSaved();
      onClose();
    } catch (e) {
      toast.error(apiErrorMessage(e, "Could not save the template"));
    } finally {
      setSaving(false);
    }
  };

  const chip = (token: string, note: string, custom = false) => (
    <button
      key={token}
      type="button"
      onClick={() => insert(`{{${token}}}`)}
      title={`Insert {{${token}}}`}
      className={`flex items-center gap-1.5 rounded-[8px] border px-2 py-1 font-mono text-[11px] font-semibold leading-normal transition-colors ${
        custom
          ? "border-chart-2/35 bg-chart-2/10 text-chart-2 hover:bg-chart-2/15"
          : "border-border bg-secondary text-muted-foreground hover:bg-card hover:text-foreground"
      }`}
    >
      {`{{${token}}}`}
      <em className="font-sans text-[10px] font-normal not-italic opacity-70">{note}</em>
    </button>
  );

  return (
    <Dialog open={open} onClose={onClose} label={template ? "Edit template" : "New template"} size="xl">
      <DialogHead
        title={template ? "Edit template" : "New template"}
        sub={
          <>
            A message body with <code className="font-mono">{"{{placeholders}}"}</code>. Nothing is sent with an
            unfilled placeholder — the run stops instead.
          </>
        }
        onClose={onClose}
      />
      <DialogBody className="grid grid-cols-1 gap-5 md:grid-cols-[1fr_300px]">
        {/* ---- left: the template ---- */}
        <div className="min-w-0">
          <Field label="Name">
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Creator intro — short" />
          </Field>

          <FieldLabel className="mt-4">Message</FieldLabel>
          <Textarea
            ref={bodyRef}
            rows={9}
            value={body}
            onChange={(e) => setBody(e.target.value)}
            className={error ? "border-bad focus:border-bad" : ""}
          />
          <div className="mt-1.5 flex items-start gap-3">
            {error && <span className="text-[11px] leading-normal text-bad">{error}</span>}
            <span
              className={`ml-auto flex-none text-[11px] tabular-nums leading-normal ${
                body.length > MAX_BODY_LENGTH ? "text-bad" : "text-subtle"
              }`}
            >
              {body.length.toLocaleString()} / {MAX_BODY_LENGTH.toLocaleString()}
            </span>
          </div>

          <FieldLabel className="mt-4">Insert a placeholder</FieldLabel>
          <div className="flex flex-wrap gap-1.5">{BUILTIN_VARIABLES.map((k) => chip(k, SAMPLE[k]))}</div>
          {own.length > 0 && (
            <div className="mt-1.5 flex flex-wrap gap-1.5">{own.map((k) => chip(k, "set per campaign", true))}</div>
          )}
          <Hint>
            The four on top are filled automatically from the target, the campaign and the sending account. Your own
            variables get their value on the campaign — a default here is only a starting point.
          </Hint>

          {own.length > 0 && (
            <>
              <FieldLabel className="mt-4">Default values</FieldLabel>
              <div className="flex flex-wrap gap-2">
                {own.map((k) => (
                  <label
                    key={k}
                    className="flex items-center gap-[7px] rounded-[9px] border border-border bg-secondary py-[5px] pl-2.5 pr-1.5"
                  >
                    <b className="font-mono text-[11px] font-semibold text-chart-2">{`{{${k}}}`}</b>
                    <input
                      value={defaults[k] ?? ""}
                      onChange={(e) => setDefaults((p) => ({ ...p, [k]: e.target.value }))}
                      placeholder={`value for ${k}`}
                      className="w-[150px] border-0 bg-transparent text-xs leading-normal text-foreground outline-none placeholder:text-subtle"
                    />
                  </label>
                ))}
              </div>
            </>
          )}

          <FieldLabel className="mt-4">Attachment</FieldLabel>
          <input ref={fileRef} type="file" accept="image/jpeg,image/png,image/gif,image/webp" className="hidden" />
          {template?.has_attachment ? (
            <div className="flex items-center gap-2.5 rounded-[12px] border border-border bg-secondary px-3 py-2.5">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={templateAttachmentUrl(template.id)}
                alt={template.attachment_name || "Template attachment"}
                className="h-10 w-10 flex-none rounded-[8px] border border-border object-cover"
              />
              <span className="min-w-0 truncate text-[12px] leading-normal text-muted-foreground">
                {template.attachment_name}
              </span>
              <button
                type="button"
                aria-label="Remove image"
                onClick={async () => {
                  try {
                    await clearTemplateAttachment(template.id);
                    toast.success("Image removed");
                    onSaved();
                  } catch (e) {
                    toast.error(apiErrorMessage(e, "Could not remove the image"));
                  }
                }}
                className="ml-auto grid h-[27px] w-[27px] flex-none place-items-center rounded-[8px] border border-border bg-card text-subtle transition-colors hover:border-bad/35 hover:text-bad"
              >
                <XIcon className="h-3 w-3" />
              </button>
            </div>
          ) : (
            <button
              type="button"
              onClick={() => fileRef.current?.click()}
              className="flex w-full items-center gap-2.5 rounded-[12px] border-[1.5px] border-dashed border-border bg-secondary px-3 py-2.5 text-left transition-colors hover:border-subtle hover:bg-card"
            >
              <Upload className="h-3.5 w-3.5 flex-none text-muted-foreground" strokeWidth={1.8} />
              <span className="flex min-w-0 flex-col">
                <span className="text-[12.5px] font-semibold leading-normal text-foreground">Add an image</span>
                <span className="text-[10.5px] leading-normal text-subtle">
                  Sent alongside the message, where the platform allows it
                </span>
              </span>
            </button>
          )}
        </div>

        {/* ---- right: the preview ---- */}
        <div className="min-w-0">
          <FieldLabel>Preview</FieldLabel>
          <div className="overflow-hidden rounded-[16px] border border-border bg-card">
            <div className="flex items-center gap-2.5 border-b border-border px-3 py-2.5">
              <span className="grid h-[31px] w-[31px] flex-none place-items-center rounded-[9px] border border-border bg-secondary text-muted-foreground">
                <User className="h-4 w-4" />
              </span>
              <span className="flex min-w-0 flex-col gap-px">
                <span className="truncate text-[12.5px] font-bold leading-normal text-foreground">
                  @{SAMPLE.username}
                </span>
                <span className="truncate text-[10.5px] leading-normal text-subtle">
                  TikTok · {SAMPLE.account_name}
                </span>
              </span>
            </div>
            <div className="min-h-[148px] bg-secondary px-3 py-3.5">
              <div className="max-w-full whitespace-pre-wrap break-words rounded-[14px] rounded-br-[4px] bg-primary px-3.5 py-2.5 text-[12.5px] leading-[1.5] text-primary-foreground">
                {preview || "…"}
              </div>
            </div>
          </div>
          <div className="mt-2 flex items-baseline gap-2">
            <span
              className={`text-[11.5px] font-bold tabular-nums leading-normal ${
                preview.length > MAX_RENDERED ? "text-bad" : "text-foreground"
              }`}
            >
              {preview.length.toLocaleString()} / {MAX_RENDERED.toLocaleString()}
            </span>
            <span className="text-[10.5px] leading-normal text-subtle">Rendered length, against the cap</span>
          </div>
          {unfilled.length > 0 && (
            <Hint>
              {unfilled.map((k) => `{{${k}}}`).join(", ")} {unfilled.length === 1 ? "has" : "have"} no default. A
              campaign using this template must supply {unfilled.length === 1 ? "it" : "them"}, or the run stops rather
              than sending the raw token.
            </Hint>
          )}
        </div>
      </DialogBody>
      <DialogFoot
        note={
          template
            ? usedBy
              ? `Used by ${usedBy} campaign${usedBy === 1 ? "" : "s"} — saving updates all of them`
              : "Not used by any campaign yet"
            : "Available to every campaign once saved"
        }
      >
        <GhostButton onClick={onClose} disabled={saving}>
          Cancel
        </GhostButton>
        <PrimaryButton icon={Check} onClick={save} disabled={saving || !!error || !name.trim()}>
          {saving ? "Saving…" : "Save template"}
        </PrimaryButton>
      </DialogFoot>
    </Dialog>
  );
}
