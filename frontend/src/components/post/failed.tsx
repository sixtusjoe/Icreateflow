"use client";

/** What did not go out, still on the page tomorrow.
 *
 *  The same rows the result modal showed, except these come from the
 *  `outputs` table, so a scheduled run that failed overnight is here too.
 *  Clearing them drops the only record of WHY each one was refused, which is
 *  why it asks first — the old page cleared instantly.
 */

import { useState } from "react";
import { AlertCircle, ChevronDown, RefreshCw } from "lucide-react";
import { clearFailedOutputs, retryOutput } from "@/lib/api";
import { PlatformIcon } from "@/components/kit";
import { ConfirmDialog, Dialog, DialogBody, DialogFoot, DialogHead, GhostButton, Hint } from "@/components/kit/dialog";
import { apiErrorMessage } from "@/components/kit/format";
import { isCapError } from "./posting";
import { toast } from "sonner";

const PLAT_NAME: Record<string, string> = {
  tiktok: "TikTok",
  youtube: "YouTube",
  instagram: "Instagram",
  facebook: "Facebook",
};

export type FailedOutput = {
  output_id: number;
  account_name: string;
  platforms: Record<string, { error?: string; friendly_error?: string; draft?: boolean }>;
};

export function FailedSection({
  postId,
  outputs,
  onChange,
}: {
  postId: number;
  outputs: FailedOutput[];
  onChange: () => void;
}) {
  const [open, setOpen] = useState(true);
  const [retrying, setRetrying] = useState<string | null>(null);
  const [clearing, setClearing] = useState(false);
  const [confirmClear, setConfirmClear] = useState(false);
  const [cap, setCap] = useState<{ outputId: number; platform: string } | null>(null);

  const rows = outputs.flatMap((o) =>
    Object.entries(o.platforms).map(([platform, d]) => ({
      outputId: o.output_id,
      account: o.account_name,
      platform,
      why: d.friendly_error || d.error || "Refused",
      draft: !!d.draft,
      cap: isCapError(d.error),
    })),
  );

  if (rows.length === 0) return null;

  const heading = rows.every((r) => r.draft)
    ? "Sitting in drafts"
    : rows.some((r) => r.draft)
      ? "Needs a decision from you"
      : "Still to sort out";

  const retry = async (outputId: number, platform: string, mode: "normal" | "draft" | "delayed") => {
    setRetrying(`${outputId}:${platform}`);
    setCap(null);
    try {
      await retryOutput(outputId, mode);
      toast.success(mode === "delayed" ? "TikTok will be retried in 6 hours" : "Retry sent");
      onChange();
    } catch (e) {
      toast.error(apiErrorMessage(e, "Could not retry that one"));
    } finally {
      setRetrying(null);
    }
  };

  return (
    <>
      <section className="overflow-hidden rounded-[16px] border border-destructive/30 bg-destructive/[0.05]">
        <div className="flex items-center gap-2.5 px-[15px] py-[11px]">
          <button
            type="button"
            onClick={() => setOpen((o) => !o)}
            aria-expanded={open}
            className="flex min-w-0 flex-1 items-center gap-2.5 text-left text-destructive"
          >
            <AlertCircle className="h-[15px] w-[15px] flex-none" />
            <span className="whitespace-nowrap text-[13px] font-bold leading-normal">{heading}</span>
            <span className="rounded-full bg-destructive/15 px-2 py-px text-[11px] font-bold tabular-nums leading-normal">
              {rows.length}
            </span>
            <ChevronDown className={`ml-auto h-[14px] w-[14px] opacity-65 transition-transform ${open ? "" : "-rotate-90"}`} />
          </button>
          <button
            type="button"
            onClick={() => setConfirmClear(true)}
            disabled={clearing}
            className="flex-none text-[11.5px] font-semibold leading-normal text-destructive opacity-75 hover:underline hover:opacity-100 disabled:opacity-40"
          >
            {clearing ? "Clearing…" : "Clear them"}
          </button>
        </div>

        {open && (
          <div className="border-t border-destructive/20">
            {rows.map((r, i) => {
              const busy = retrying === `${r.outputId}:${r.platform}`;
              return (
                <div
                  key={i}
                  className="flex flex-wrap items-center gap-2.5 border-b border-destructive/10 px-[15px] py-[11px] last:border-b-0"
                >
                  <span
                    className={`inline-flex flex-none items-center gap-1.5 rounded-[8px] border px-[9px] py-[3px] text-[11px] font-semibold leading-normal ${
                      r.draft
                        ? "border-[rgba(235,104,52,0.3)] bg-[rgba(235,104,52,0.13)] text-[#B25E09] dark:text-[#F2A25C]"
                        : "border-border bg-secondary text-muted-foreground"
                    }`}
                  >
                    <PlatformIcon platform={r.platform} className="h-3 w-3" />
                    {r.draft ? "Draft" : PLAT_NAME[r.platform] ?? r.platform}
                  </span>
                  <span className="flex-none whitespace-nowrap text-[11.5px] font-semibold leading-normal text-muted-foreground">
                    {r.account}
                  </span>
                  <span
                    title={r.why}
                    className={`min-w-0 flex-1 basis-full truncate text-[11.5px] leading-[1.45] sm:basis-auto ${
                      r.draft ? "text-[#B25E09] dark:text-[#F2A25C]" : "text-destructive"
                    }`}
                  >
                    {r.why}
                  </span>
                  <button
                    type="button"
                    disabled={!!retrying}
                    onClick={() =>
                      r.cap && r.platform === "tiktok"
                        ? setCap({ outputId: r.outputId, platform: r.platform })
                        : retry(r.outputId, r.platform, "normal")
                    }
                    className="inline-flex flex-none items-center gap-1.5 whitespace-nowrap rounded-[9px] border border-border bg-card px-2.5 py-[5px] text-[11px] font-semibold leading-normal text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground disabled:opacity-45"
                  >
                    <RefreshCw className={`h-[11px] w-[11px] ${busy ? "animate-spin" : ""}`} />
                    {busy ? "Retrying…" : r.draft ? "Retry live" : "Retry"}
                  </button>
                </div>
              );
            })}
          </div>
        )}
      </section>

      {cap && (
        <Dialog open onClose={() => setCap(null)} label="TikTok would not take it" size="sm">
          <DialogHead
            title="TikTok would not take it"
            sub="This account has hit TikTok's cap on posts from apps that are not audited yet. Nothing is wrong with the post itself."
            onClose={() => setCap(null)}
          />
          <DialogBody>
            <div className="flex flex-col gap-2">
              {(
                [
                  {
                    mode: "draft" as const,
                    title: "Send it to the TikTok inbox",
                    body: "Arrives now as a draft. You publish it from the app, today",
                  },
                  {
                    mode: "delayed" as const,
                    title: "Try again in 6 hours",
                    body: "The cap is a rolling window. We retry the direct post once, on our own",
                  },
                ]
              ).map((o) => (
                <button
                  key={o.mode}
                  type="button"
                  onClick={() => retry(cap.outputId, cap.platform, o.mode)}
                  className="flex flex-col items-start gap-0.5 rounded-[13px] border border-border bg-card px-3.5 py-3 text-left transition-colors hover:border-subtle hover:bg-secondary"
                >
                  <span className="text-[12.5px] font-semibold leading-normal">{o.title}</span>
                  <span className="text-[11px] leading-[1.45] text-subtle">{o.body}</span>
                </button>
              ))}
            </div>
            <Hint>The other platforms already went out. This is only TikTok, on this one account.</Hint>
          </DialogBody>
          <DialogFoot>
            <GhostButton onClick={() => setCap(null)}>Back</GhostButton>
          </DialogFoot>
        </Dialog>
      )}

      <ConfirmDialog
        open={confirmClear}
        onClose={() => setConfirmClear(false)}
        busy={clearing}
        onConfirm={async () => {
          setClearing(true);
          try {
            await clearFailedOutputs(postId);
            toast.success("Cleared");
            setConfirmClear(false);
            onChange();
          } catch (e) {
            toast.error(apiErrorMessage(e, "Could not clear them"));
          } finally {
            setClearing(false);
          }
        }}
        title="Clear these failures?"
        body="The list goes, and with it the only record of why each one was refused."
        bullets={[
          "The platform's own words for each refusal",
          "Which account and which platform each one was on",
          "Everything that did go out is untouched — nothing posted is affected",
        ]}
        confirmLabel="Clear them"
      />
    </>
  );
}
