"use client";

/**
 * What a campaign actually does, per task.
 *
 * Both are locked rather than hidden while the campaign runs: the server
 * refuses the edit, and a disabled box that says why is kinder than a
 * dialog that saves into an error.
 */

import { useCallback, useEffect, useState } from "react";
import { Plus, X as XIcon } from "lucide-react";
import { toast } from "sonner";
import { updateOutreachCampaign } from "@/lib/api";
import { Dialog, DialogBody, DialogFoot, DialogHead, Field, FieldLabel, GhostButton, Hint, Input, Textarea } from "@/components/kit/dialog";
import { PrimaryButton } from "@/components/kit";
import { BUILTIN_VARIABLES, MAX_BODY_LENGTH, extractVariables, validateTemplate } from "./template";
import { apiErrorMessage } from "@/components/kit/format";

/* ------------------------------------------------------------------ */
/* message                                                             */
/* ------------------------------------------------------------------ */

export function MessageSetupDialog({
  open,
  onClose,
  campaignId,
  template,
  locked,
  onSaved,
}: {
  open: boolean;
  onClose: () => void;
  campaignId: number;
  template: string;
  locked: boolean;
  onSaved: () => void;
}) {
  const [text, setText] = useState(template);
  const [saving, setSaving] = useState(false);

  // Follow the campaign when it reloads underneath, but never overwrite
  // what someone is part-way through typing.
  useEffect(() => {
    setText(template);
  }, [template, open]);

  const error = validateTemplate(text);
  const used = extractVariables(text);
  const unchanged = text.trim() === template.trim();

  /** Drop a placeholder in at the caret, rather than making people type braces. */
  const insert = (name: string) => {
    const el = document.getElementById("msg-body") as HTMLTextAreaElement | null;
    const token = `{{${name}}}`;
    if (!el) return setText((t) => t + token);
    const start = el.selectionStart ?? text.length;
    const end = el.selectionEnd ?? start;
    const next = text.slice(0, start) + token + text.slice(end);
    setText(next);
    requestAnimationFrame(() => {
      el.focus();
      el.setSelectionRange(start + token.length, start + token.length);
    });
  };

  const save = async () => {
    setSaving(true);
    try {
      await updateOutreachCampaign(campaignId, { message_template: text.trim() });
      toast.success("Message saved");
      onSaved();
      onClose();
    } catch (e) {
      toast.error(apiErrorMessage(e, "Could not save the message"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} label="Message">
      <DialogHead title="Message" sub="What each target receives." onClose={onClose} />
      <DialogBody>
        <FieldLabel>The message</FieldLabel>
        <Textarea
          id="msg-body"
          rows={8}
          value={text}
          disabled={locked}
          onChange={(e) => setText(e.target.value)}
          placeholder="Hi {{username}}, we came across your content…"
          className={error ? "border-bad focus:border-bad" : ""}
        />
        <div className="mt-1.5 flex items-start gap-3">
          {error && !locked ? (
            <span className="text-[11px] leading-normal text-bad">{error}</span>
          ) : null}
          <span
            className={`ml-auto flex-none text-[11px] tabular-nums leading-normal ${
              text.length > MAX_BODY_LENGTH ? "text-bad" : "text-subtle"
            }`}
          >
            {text.length.toLocaleString()} / {MAX_BODY_LENGTH.toLocaleString()}
          </span>
        </div>

        {!locked && (
          <>
            <FieldLabel className="mt-4">Insert</FieldLabel>
            <div className="flex flex-wrap gap-1.5">
              {BUILTIN_VARIABLES.map((v) => (
                <button
                  key={v}
                  type="button"
                  onClick={() => insert(v)}
                  className={`rounded-[8px] border px-2 py-1 font-mono text-[11px] font-semibold leading-normal transition-colors ${
                    used.includes(v)
                      ? "border-chart-1/40 bg-chart-1/10 text-chart-1"
                      : "border-border bg-secondary text-muted-foreground hover:bg-card hover:text-foreground"
                  }`}
                >
                  {`{{${v}}}`}
                </button>
              ))}
            </div>
            <Hint>
              These four fill themselves from the target, the campaign and the sending account. Any other name you use
              needs a value on the campaign.
            </Hint>
          </>
        )}
      </DialogBody>
      <DialogFoot
        note={
          locked
            ? "Pause or stop the campaign to change this."
            : "Only changes what is sent from here on — messages already sent stay as they were."
        }
      >
        <GhostButton onClick={onClose} disabled={saving}>
          Cancel
        </GhostButton>
        <PrimaryButton onClick={save} disabled={locked || saving || !!error || unchanged}>
          {saving ? "Saving…" : unchanged ? "No changes" : "Save message"}
        </PrimaryButton>
      </DialogFoot>
    </Dialog>
  );
}

/* ------------------------------------------------------------------ */
/* comment                                                             */
/* ------------------------------------------------------------------ */

export function CommentSetupDialog({
  open,
  onClose,
  campaignId,
  videoUrl,
  count,
  lines,
  locked,
  onSaved,
}: {
  open: boolean;
  onClose: () => void;
  campaignId: number;
  videoUrl: string;
  count: number;
  lines: string[] | string | null;
  locked: boolean;
  onSaved: () => void;
}) {
  // Defensive on purpose. The column holds JSON and the API decodes it,
  // but a backend that has not restarted yet still sends the raw string —
  // and `.map` over a string is a blank list, not a wrong label.
  const asLines = useCallback((value: unknown): string[] => {
    if (Array.isArray(value)) return value.map(String);
    if (typeof value === "string" && value.trim()) {
      try {
        const parsed = JSON.parse(value);
        if (Array.isArray(parsed)) return parsed.map(String);
      } catch {
        // Not JSON: treat it as the lines themselves.
      }
      return value.split("\n");
    }
    return [];
  }, []);

  const [url, setUrl] = useState(videoUrl);
  const [howMany, setHowMany] = useState(String(count || ""));
  const [rows, setRows] = useState<string[]>(() => asLines(lines));
  const [saving, setSaving] = useState(false);

  // Re-sync when the campaign reloads under us, and on each open.
  const joined = asLines(lines).join("\n");
  useEffect(() => {
    setUrl(videoUrl);
    setHowMany(String(count || ""));
    setRows(joined ? joined.split("\n") : [""]);
  }, [videoUrl, count, joined, open]);

  const written = rows.map((l) => l.trim()).filter(Boolean);
  const asked = Number(howMany) || 0;
  const blocked = !url.trim()
    ? "A comment campaign needs the post to comment on."
    : asked < 1
      ? "Say how many comments to leave."
      : written.length === 0
        ? "Add at least one variation."
        : null;

  const save = async () => {
    setSaving(true);
    try {
      await updateOutreachCampaign(campaignId, {
        target_url: url.trim(),
        comment_count: asked,
        comment_variations: written,
      });
      toast.success("Comment setup saved");
      onSaved();
      onClose();
    } catch (e) {
      toast.error(apiErrorMessage(e, "Could not save the comment setup"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} label="Comment setup">
      <DialogHead
        title="Comment setup"
        sub="One post, commented on repeatedly. The variations keep the same line from going up twice in a row."
        onClose={onClose}
      />
      <DialogBody>
        <FieldLabel>The post</FieldLabel>
        <Input
          value={url}
          disabled={locked}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://www.tiktok.com/@handle/video/1234567890"
        />

        <div className="mt-3.5 grid grid-cols-2 gap-2.5">
          <Field label="How many comments">
            <Input
              value={howMany}
              disabled={locked}
              inputMode="numeric"
              onChange={(e) => setHowMany(e.target.value.replace(/[^0-9]/g, ""))}
              placeholder="20"
            />
          </Field>
          <Field label="Spread across">
            <Input value="every enabled account" disabled />
          </Field>
        </div>

        <FieldLabel className="mt-4">Variations</FieldLabel>
        <div className="flex flex-col gap-[7px]">
          {rows.map((v, i) => (
            <div key={i} className="flex items-center gap-[9px]">
              <span className="grid h-[19px] w-[19px] flex-none place-items-center rounded-[6px] bg-border text-[10px] font-bold leading-normal text-muted-foreground">
                {i + 1}
              </span>
              <Input
                value={v}
                disabled={locked}
                onChange={(e) => setRows((p) => p.map((x, j) => (j === i ? e.target.value : x)))}
                placeholder="what the comment says"
              />
              <button
                type="button"
                disabled={locked}
                aria-label={`Remove variation ${i + 1}`}
                onClick={() => setRows((p) => (p.length === 1 ? [""] : p.filter((_, j) => j !== i)))}
                className="grid h-[27px] w-[27px] flex-none place-items-center rounded-[8px] border border-border bg-card text-subtle transition-colors hover:border-bad/35 hover:text-bad disabled:opacity-45"
              >
                <XIcon className="h-3 w-3" />
              </button>
            </div>
          ))}
        </div>
        <button
          type="button"
          disabled={locked}
          onClick={() => setRows((p) => [...p, ""])}
          className="mt-2 inline-flex items-center gap-1.5 rounded-[9px] border border-border bg-card px-2.5 py-1.5 text-[11.5px] font-semibold leading-normal text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground disabled:opacity-45"
        >
          <Plus className="h-3 w-3" strokeWidth={2.6} /> Add a variation
        </button>
        <Hint>
          {written.length === 0
            ? "Add at least one line."
            : `${written.length} line${written.length === 1 ? "" : "s"}, drawn from in turn.`}
        </Hint>
      </DialogBody>
      <DialogFoot note={locked ? "Pause the campaign to change this." : (blocked ?? undefined)}>
        <GhostButton onClick={onClose} disabled={saving}>
          Cancel
        </GhostButton>
        <PrimaryButton onClick={save} disabled={locked || saving || !!blocked}>
          {saving ? "Saving…" : "Save comment setup"}
        </PrimaryButton>
      </DialogFoot>
    </Dialog>
  );
}
