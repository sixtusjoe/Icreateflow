"use client";

/**
 * New campaign.
 *
 * The task chosen at the top decides what the rest of the form asks for,
 * because that is what the server does: `create_campaign` validates a
 * message template for `activity == "message"` and skips it entirely for
 * follow and comment. A follow campaign should not be made to fill in a
 * message box whose contents will never be sent.
 *
 * The platform tiles carry live account counts, so "no enabled account on
 * this platform" is said here rather than at Start, where the backend
 * raises it.
 */

import { useEffect, useMemo, useState } from "react";
import { MessageCircle, MessageSquare, Plus, UserMinus, Users, X as XIcon, FileText } from "lucide-react";
import {
  createOutreachCampaign,
  type OutreachAccount,
  type OutreachCampaign,
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
import { Empty, PLATFORMS, PLATFORM_LABEL, PlatformIcon, PrimaryButton, Tabs } from "@/components/kit";
import { MAX_BODY_LENGTH, ownVariables, validateTemplate, varsPayload } from "./template";
import { apiErrorMessage } from "@/components/kit/format";

type Activity = "message" | "follow" | "unfollow" | "comment";

const TASKS: { key: Activity; label: string; icon: React.ComponentType<{ className?: string }>; note: string }[] = [
  { key: "message", label: "Message", icon: MessageCircle, note: "Send a DM to every target" },
  { key: "follow", label: "Follow", icon: Users, note: "Follow every target. No message" },
  { key: "unfollow", label: "Unfollow", icon: UserMinus, note: "Unfollow every target. Never follows anyone" },
  { key: "comment", label: "Comment", icon: MessageSquare, note: "Comment on one post, many times" },
];

/** What the footer says the Create button is about to do. */
const NOTES: Record<Activity, string> = {
  message: "Creates it as a draft — import targets next",
  follow: "Creates it as a draft — import profiles next",
  unfollow: "Creates it as a draft — import the profiles to unfollow next",
  comment: "Creates it as a draft — the post is read when it starts",
};

const DEFAULT_BODY =
  "Hi {{username}}, we came across your content and wanted to reach out about {{offer}}.";

export function NewCampaignDialog({
  open,
  onClose,
  accounts,
  templates,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  accounts: OutreachAccount[];
  templates: OutreachTemplate[];
  onCreated: (c: OutreachCampaign) => void;
}) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [platform, setPlatform] = useState<string>("tiktok");
  const [activity, setActivity] = useState<Activity>("message");
  const [source, setSource] = useState<"write" | "tmpl">("write");
  const [body, setBody] = useState(DEFAULT_BODY);
  const [templateId, setTemplateId] = useState<number | null>(null);
  const [vars, setVars] = useState<Record<string, string>>({});
  const [url, setUrl] = useState("");
  const [commentCount, setCommentCount] = useState("200");
  const [variations, setVariations] = useState<string[]>([""]);
  const [limits, setLimits] = useState({ max_jobs: "", max_jobs_per_account: "", retry_limit: "" });
  const [saving, setSaving] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

  // A dialog that reopens holding the last attempt's half-filled form is
  // a bug report waiting to happen.
  useEffect(() => {
    if (!open) return;
    setName("");
    setDescription("");
    setActivity("message");
    setSource("write");
    setBody(DEFAULT_BODY);
    setTemplateId(null);
    setVars({});
    setUrl("");
    setCommentCount("200");
    setVariations([""]);
    setLimits({ max_jobs: "", max_jobs_per_account: "", retry_limit: "" });
    setFailure(null);
  }, [open]);

  /** Enabled accounts per platform — what can actually send. */
  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const a of accounts) if (a.enabled) c[a.platform] = (c[a.platform] ?? 0) + 1;
    return c;
  }, [accounts]);

  const bodyError = activity === "message" ? validateTemplate(body) : null;
  const own = activity === "message" ? ownVariables(body) : [];
  const liveVariations = variations.map((v) => v.trim()).filter(Boolean);

  const blocked =
    !name.trim()
      ? "Give the campaign a name."
      : activity === "message" && bodyError
        ? bodyError
        : activity === "unfollow" && platform !== "tiktok" && platform !== "instagram"
          ? "Unfollowing works on TikTok and Instagram only, for now."
        : activity === "comment" && !url.trim()
          ? "A comment campaign needs the post to comment on."
          : activity === "comment" && liveVariations.length === 0
            ? "Add at least one comment variation."
            : null;

  const create = async () => {
    setSaving(true);
    setFailure(null);
    try {
      const created = await createOutreachCampaign({
        name: name.trim(),
        description: description.trim() || undefined,
        platform,
        activity,
        // The server ignores what the chosen activity does not use, but
        // sending a message body on a follow campaign would still store
        // it — so each branch sends only its own fields.
        ...(activity === "message"
          ? {
              message_template: body,
              template_id: templateId,
              template_vars: varsPayload(vars),
            }
          : {}),
        ...(activity === "comment"
          ? {
              target_url: url.trim(),
              comment_count: Number(commentCount) || 1,
              comment_variations: liveVariations,
            }
          : {}),
        max_jobs: limits.max_jobs ? Number(limits.max_jobs) : null,
        max_jobs_per_account: limits.max_jobs_per_account ? Number(limits.max_jobs_per_account) : null,
        retry_limit: limits.retry_limit ? Number(limits.retry_limit) : null,
      });
      onCreated(created);
    } catch (e) {
      setFailure(apiErrorMessage(e, "Could not create the campaign."));
    } finally {
      setSaving(false);
    }
  };

  const setVariation = (i: number, v: string) =>
    setVariations((prev) => prev.map((x, j) => (j === i ? v : x)));

  return (
    <Dialog open={open} onClose={onClose} label="New campaign" size="lg">
      <DialogHead
        title="New campaign"
        sub="Nothing sends until you import targets and press Start — this only sets it up."
        onClose={onClose}
      />
      <DialogBody>
        <Field label="Name">
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Q4 creator outreach" />
        </Field>

        <FieldLabel className="mt-4">Platform</FieldLabel>
        <div className="grid grid-cols-3 gap-[9px]">
          {PLATFORMS.map((p) => {
            const on = p === platform;
            const c = counts[p] ?? 0;
            return (
              <button
                key={p}
                type="button"
                onClick={() => setPlatform(p)}
                aria-pressed={on}
                className={`flex flex-col items-center gap-2 rounded-[13px] border bg-card px-2 py-3.5 text-[12.5px] font-semibold leading-normal transition-colors ${
                  on ? "border-primary shadow-[0_0_0_1px_var(--primary)]" : "border-border hover:bg-secondary"
                }`}
              >
                <span
                  className={`grid h-[34px] w-[34px] place-items-center rounded-[10px] border ${
                    on ? "border-primary bg-primary text-primary-foreground" : "border-border bg-secondary text-foreground"
                  }`}
                >
                  <PlatformIcon platform={p} className="h-[17px] w-[17px]" />
                </span>
                <span>{PLATFORM_LABEL[p]}</span>
                <em className="-mt-[3px] text-[10.5px] font-normal not-italic leading-normal text-subtle">
                  {c} account{c === 1 ? "" : "s"}
                </em>
              </button>
            );
          })}
        </div>
        <Hint>
          {(counts[platform] ?? 0) > 0
            ? `${counts[platform]} enabled ${PLATFORM_LABEL[platform]} account${counts[platform] === 1 ? "" : "s"} can send for this campaign.`
            : "No enabled account on this platform yet — add one before this campaign can start."}
        </Hint>

        <FieldLabel className="mt-4">Task</FieldLabel>
        <div className="grid grid-cols-3 gap-[9px]">
          {TASKS.map((t) => {
            const on = t.key === activity;
            return (
              <button
                key={t.key}
                type="button"
                onClick={() => setActivity(t.key)}
                aria-pressed={on}
                className={`flex flex-col gap-2 rounded-[13px] border bg-card p-3 text-left transition-colors ${
                  on ? "border-primary shadow-[0_0_0_1px_var(--primary)]" : "border-border hover:bg-secondary"
                }`}
              >
                <span
                  className={`grid h-7 w-7 place-items-center rounded-[9px] border ${
                    on
                      ? "border-primary bg-primary text-primary-foreground"
                      : "border-border bg-secondary text-muted-foreground"
                  }`}
                >
                  <t.icon className="h-[15px] w-[15px]" />
                </span>
                <span>
                  <span className="block text-[12.5px] font-bold leading-normal text-foreground">{t.label}</span>
                  <span className="mt-0.5 block text-[10.5px] leading-[1.4] text-subtle">{t.note}</span>
                </span>
              </button>
            );
          })}
        </div>

        {/* ---- message ------------------------------------------------ */}
        {activity === "message" && (
          <>
            <FieldLabel className="mt-[18px]">Message</FieldLabel>
            <Tabs
              className="mb-[11px] w-max"
              value={source}
              onChange={(k) => {
                setSource(k as "write" | "tmpl");
                if (k === "write") setTemplateId(null);
              }}
              items={[
                { key: "write", label: "Write it" },
                { key: "tmpl", label: "Use a template" },
              ]}
            />
            {source === "write" ? (
              <>
                <Textarea
                  rows={5}
                  value={body}
                  onChange={(e) => setBody(e.target.value)}
                  className={bodyError ? "border-bad focus:border-bad" : ""}
                />
                <div className="mt-1.5 flex items-start gap-3">
                  {bodyError ? (
                    <span className="flex items-center gap-1.5 text-[11px] leading-normal text-bad">
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className="h-3 w-3 flex-none">
                        <circle cx="12" cy="12" r="10" />
                        <path d="M12 7v6" />
                        <circle cx="12" cy="16.4" r=".8" fill="currentColor" />
                      </svg>
                      {bodyError}
                    </span>
                  ) : null}
                  <span
                    className={`ml-auto flex-none text-[11px] tabular-nums leading-normal ${
                      body.length > MAX_BODY_LENGTH ? "text-bad" : "text-subtle"
                    }`}
                  >
                    {body.length.toLocaleString()} / {MAX_BODY_LENGTH.toLocaleString()}
                  </span>
                </div>
                {own.length > 0 && (
                  <div className="mt-2.5">
                    <span className="text-[11px] leading-[1.5] text-subtle">
                      Give each of your own placeholders a value:
                    </span>
                    <div className="mt-2 flex flex-wrap gap-2">
                      {own.map((k) => (
                        <label
                          key={k}
                          className="flex items-center gap-[7px] rounded-[9px] border border-border bg-secondary py-[5px] pl-2.5 pr-1.5"
                        >
                          <b className="font-mono text-[11px] font-semibold text-chart-1">{`{{${k}}}`}</b>
                          <input
                            value={vars[k] ?? ""}
                            onChange={(e) => setVars((p) => ({ ...p, [k]: e.target.value }))}
                            placeholder={`value for ${k}`}
                            className="w-[150px] border-0 bg-transparent text-xs leading-normal text-foreground outline-none placeholder:text-subtle"
                          />
                        </label>
                      ))}
                    </div>
                  </div>
                )}
              </>
            ) : templates.length === 0 ? (
              <div className="rounded-[13px] border-[1.5px] border-dashed border-border">
                <Empty icon={FileText} title="No templates yet">
                  Write the message here, then save it as a template from the campaign page.
                </Empty>
              </div>
            ) : (
              <div className="flex flex-col gap-2">
                {templates.map((t) => {
                  const on = t.id === templateId;
                  return (
                    <button
                      key={t.id}
                      type="button"
                      onClick={() => {
                        setTemplateId(t.id);
                        setBody(t.body);
                      }}
                      className={`rounded-[12px] border bg-card px-3.5 py-3 text-left transition-colors ${
                        on ? "border-primary shadow-[0_0_0_1px_var(--primary)]" : "border-border hover:bg-secondary"
                      }`}
                    >
                      <span className="block text-[12.5px] font-bold leading-normal text-foreground">{t.name}</span>
                      <span className="mt-1 line-clamp-2 block text-[11.5px] leading-[1.5] text-subtle">{t.body}</span>
                    </button>
                  );
                })}
                {templateId && own.length > 0 && (
                  <div className="mt-1 flex flex-wrap gap-2">
                    {own.map((k) => (
                      <label
                        key={k}
                        className="flex items-center gap-[7px] rounded-[9px] border border-border bg-secondary py-[5px] pl-2.5 pr-1.5"
                      >
                        <b className="font-mono text-[11px] font-semibold text-chart-1">{`{{${k}}}`}</b>
                        <input
                          value={vars[k] ?? ""}
                          onChange={(e) => setVars((p) => ({ ...p, [k]: e.target.value }))}
                          placeholder={`value for ${k}`}
                          className="w-[150px] border-0 bg-transparent text-xs leading-normal text-foreground outline-none placeholder:text-subtle"
                        />
                      </label>
                    ))}
                  </div>
                )}
              </div>
            )}
          </>
        )}

        {/* ---- follow ------------------------------------------------- */}
        {activity === "follow" && (
          <p className="mt-[18px] flex items-start gap-2 text-[12.5px] leading-[1.55] text-subtle">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className="mt-0.5 h-3.5 w-3.5 flex-none">
              <circle cx="12" cy="12" r="10" />
              <path d="M12 8v5" />
              <circle cx="12" cy="16.5" r=".7" fill="currentColor" />
            </svg>
            <span>
              Nothing else to set up. Import a list of profiles and each one gets followed from an assigned account.
            </span>
          </p>
        )}

        {/* ---- unfollow ----------------------------------------------- */}
        {activity === "unfollow" && (
          <p className="mt-[18px] flex items-start gap-2 text-[12.5px] leading-[1.55] text-subtle">
            <UserMinus className="mt-0.5 h-3.5 w-3.5 flex-none" />
            <span>
              Import the profiles to unfollow. Each one is unfollowed from an assigned account, and anyone who is not
              followed is left alone — this campaign never follows anybody. On TikTok, an account with a phone set up
              unfollows in the app.
            </span>
          </p>
        )}

        {/* ---- comment ------------------------------------------------ */}
        {activity === "comment" && (
          <>
            <FieldLabel className="mt-[18px]">The post</FieldLabel>
            <Input
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://www.tiktok.com/@handle/video/1234567890"
            />
            <Hint>One post. Comments are left on it repeatedly, not on each target.</Hint>

            <div className="mt-3.5 grid grid-cols-2 gap-2.5">
              <Field label="How many comments">
                <Input
                  type="number"
                  min={1}
                  value={commentCount}
                  onChange={(e) => setCommentCount(e.target.value)}
                />
              </Field>
              <Field label="Spread across">
                <Input value="every enabled account" disabled />
              </Field>
            </div>

            <FieldLabel className="mt-4">Variations</FieldLabel>
            <div className="flex flex-col gap-[7px]">
              {variations.map((v, i) => (
                <div key={i} className="flex items-center gap-[9px]">
                  <span className="grid h-[19px] w-[19px] flex-none place-items-center rounded-[6px] bg-border text-[10px] font-bold leading-normal text-muted-foreground">
                    {i + 1}
                  </span>
                  <Input
                    value={v}
                    onChange={(e) => setVariation(i, e.target.value)}
                    placeholder="what the comment says"
                  />
                  <button
                    type="button"
                    aria-label={`Remove variation ${i + 1}`}
                    onClick={() => setVariations((p) => (p.length === 1 ? [""] : p.filter((_, j) => j !== i)))}
                    className="grid h-[27px] w-[27px] flex-none place-items-center rounded-[8px] border border-border bg-card text-subtle transition-colors hover:border-bad/35 hover:text-bad"
                  >
                    <XIcon className="h-3 w-3" />
                  </button>
                </div>
              ))}
            </div>
            <button
              type="button"
              onClick={() => setVariations((p) => [...p, ""])}
              className="mt-2 inline-flex items-center gap-1.5 rounded-[9px] border border-border bg-card px-2.5 py-1.5 text-[11.5px] font-semibold leading-normal text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
            >
              <Plus className="h-3 w-3" strokeWidth={2.6} /> Add a variation
            </button>
            <Hint>Comments are drawn from these in turn, so the same line is not posted back to back.</Hint>
          </>
        )}

        {/* ---- shared ------------------------------------------------- */}
        <details className="mt-[18px] border-t border-border pt-3.5 [&[open]_summary_svg]:rotate-180">
          <summary className="flex cursor-pointer list-none items-center gap-[7px] text-[12.5px] font-semibold leading-normal text-muted-foreground [&::-webkit-details-marker]:hidden">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className="h-3.5 w-3.5 text-subtle transition-transform duration-[180ms]">
              <path d="M6 9l6 6 6-6" />
            </svg>
            Limits and notes
            <em className="ml-auto text-[11px] font-normal not-italic leading-normal text-subtle">optional</em>
          </summary>
          <div className="mt-3">
            <div className="grid grid-cols-3 gap-2.5">
              <Field label="Max sends">
                <Input
                  type="number"
                  min={1}
                  placeholder="1000"
                  value={limits.max_jobs}
                  onChange={(e) => setLimits({ ...limits, max_jobs: e.target.value })}
                />
              </Field>
              <Field label="Per account">
                <Input
                  type="number"
                  min={1}
                  placeholder="100"
                  value={limits.max_jobs_per_account}
                  onChange={(e) => setLimits({ ...limits, max_jobs_per_account: e.target.value })}
                />
              </Field>
              <Field label="Retries">
                <Input
                  type="number"
                  min={0}
                  placeholder="3"
                  value={limits.retry_limit}
                  onChange={(e) => setLimits({ ...limits, retry_limit: e.target.value })}
                />
              </Field>
            </div>
            <Field label="Description" className="mt-2.5">
              <Input
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="What this run is for — only you see it"
              />
            </Field>
          </div>
        </details>

        {failure && <Hint tone="bad">{failure}</Hint>}
      </DialogBody>

      <DialogFoot note={blocked ?? NOTES[activity]}>
        <GhostButton onClick={onClose} disabled={saving}>
          Cancel
        </GhostButton>
        <PrimaryButton icon={Plus} onClick={create} disabled={!!blocked || saving}>
          {saving ? "Creating…" : "Create campaign"}
        </PrimaryButton>
      </DialogFoot>
    </Dialog>
  );
}
