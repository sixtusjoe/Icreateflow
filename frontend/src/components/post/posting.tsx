"use client";

/** Post Now: sending, then what came back.
 *
 *  `POST /api/posts/{id}/post-now` is one round trip that resolves at the
 *  end, so the sending state shows WHERE it is going, not which of them is
 *  done — claiming per-platform progress would be a lie the backend cannot
 *  back up. It cannot be closed while it runs, because closing would only
 *  lose the result.
 *
 *  The results carry the four states the API actually returns — posted,
 *  posted-as-draft, failed, skipped — each row retryable on its own. A
 *  TikTok cap error is the one failure with a real choice behind it, so it
 *  asks instead of retrying the way that just failed.
 */

import { useEffect, useState } from "react";
import { Check, Clock, Minus, RefreshCw, X } from "lucide-react";
import { retryOutput } from "@/lib/api";
import { PlatformIcon } from "@/components/kit";
import { Dialog, DialogBody, DialogFoot, DialogHead, GhostButton, Hint } from "@/components/kit/dialog";

const MESSAGES = [
  "Uploading the video files…",
  "Connecting to the platforms…",
  "Submitting the posts…",
  "Waiting for confirmation…",
  "Almost there…",
];

const PLAT_NAME: Record<string, string> = {
  tiktok: "TikTok",
  youtube: "YouTube",
  instagram: "Instagram",
  facebook: "Facebook",
};

export type PlatformResult = {
  status: string;
  error?: string;
  friendly_error?: string;
  draft?: boolean;
  reason?: string;
};
export type PostResult = {
  output_id?: number;
  account_name: string;
  platforms: Record<string, PlatformResult>;
};

export const isCapError = (err?: string) =>
  !!err && /reached_active_user_cap|active_user_cap/i.test(err);

/** Someone handing a sheet of paper in over a counter. Line art on
 *  currentColor so it themes itself; stops entirely under reduced motion. */
function Clerk() {
  return (
    <div className="h-[142px] w-[230px] text-muted-foreground" role="img" aria-label="Submitting the posts">
      <svg
        viewBox="0 0 168 104"
        fill="none"
        stroke="currentColor"
        strokeWidth={2.4}
        strokeLinecap="round"
        strokeLinejoin="round"
        className="h-full w-full overflow-visible"
      >
        <path d="M14 93h140" opacity=".22" />
        <g className="pm-tray text-subtle">
          <path d="M108 74v-5a3 3 0 0 1 3-3h32a3 3 0 0 1 3 3v5" opacity=".4" />
          <g className="pm-stack">
            <path d="M110 88h34" className="pm-s1" />
            <path d="M110 83h34" className="pm-s2" />
          </g>
        </g>
        <g className="pm-figure">
          <circle cx="50" cy="27" r="9" />
          <path d="M50 36v27" />
          <path d="M50 63l-9 30M50 63l9 30" />
          <path className="pm-armL" d="M50 43l-12 11" />
          <g className="pm-armR">
            <path d="M50 42l17 6" />
          </g>
        </g>
        <g className="pm-sheet">
          <rect x="61" y="34" width="21" height="26" rx="3" />
          <path d="M66 41h11M66 46h11M66 51h7" strokeWidth={1.8} opacity=".65" />
        </g>
        <g className="pm-tray text-subtle">
          <path d="M102 93V78a4 4 0 0 1 4-4h42a4 4 0 0 1 4 4v15" />
        </g>
      </svg>
      <style>{`
        .pm-figure{animation:pmLean 2.8s cubic-bezier(.4,0,.3,1) infinite;transform-origin:50px 93px}
        @keyframes pmLean{0%,14%{transform:rotate(0)}38%,52%{transform:rotate(5deg)}74%,100%{transform:rotate(0)}}
        .pm-armR{animation:pmPush 2.8s cubic-bezier(.4,0,.3,1) infinite;transform-origin:50px 42px}
        @keyframes pmPush{0%,14%{transform:rotate(0)}40%{transform:rotate(-16deg)}52%{transform:rotate(-19deg)}62%{transform:rotate(-4deg)}76%,100%{transform:rotate(0)}}
        .pm-armL{animation:pmCounter 2.8s cubic-bezier(.4,0,.3,1) infinite;transform-origin:50px 43px}
        @keyframes pmCounter{0%,14%{transform:rotate(0)}44%{transform:rotate(19deg)}70%,100%{transform:rotate(0)}}
        .pm-sheet{animation:pmDeliver 2.8s cubic-bezier(.4,0,.3,1) infinite;transform-origin:71px 47px}
        @keyframes pmDeliver{
          0%,14%{transform:translate(0,0) rotate(0) scale(1);opacity:1}
          40%{transform:translate(30px,-5px) rotate(-10deg);opacity:1}
          53%{transform:translate(48px,-8px) rotate(-16deg) scale(.96);opacity:1}
          61%{transform:translate(55px,4px) rotate(-6deg) scale(.88);opacity:1}
          69%{transform:translate(56px,34px) rotate(0) scale(.62);opacity:1}
          70%,84%{transform:translate(0,0) rotate(0) scale(.9);opacity:0}
          94%,100%{transform:translate(0,0) rotate(0) scale(1);opacity:1}}
        .pm-tray{animation:pmKnock 2.8s ease-out infinite;transform-origin:128px 93px}
        @keyframes pmKnock{0%,61%{transform:translateY(0)}65%{transform:translateY(1.6px)}72%,100%{transform:translateY(0)}}
        .pm-stack path{opacity:0}
        .pm-s1{animation:pmPile 2.8s ease-out infinite}
        .pm-s2{animation:pmPile2 2.8s ease-out infinite}
        @keyframes pmPile{0%,66%{opacity:0}71%,100%{opacity:.8}}
        @keyframes pmPile2{0%,92%{opacity:0}97%,100%{opacity:.5}}
        @media (prefers-reduced-motion:reduce){
          .pm-figure,.pm-armL,.pm-armR,.pm-sheet,.pm-tray,.pm-s1,.pm-s2{animation:none}
          .pm-stack path{opacity:.6}}
      `}</style>
    </div>
  );
}

export function PostingModal({
  open,
  destinations,
  results,
  onResults,
  onClose,
}: {
  open: boolean;
  /** account name -> the platforms it will be sent to. */
  destinations: { account: string; platforms: string[] }[];
  results: PostResult[] | null;
  onResults: (r: PostResult[]) => void;
  onClose: () => void;
}) {
  const [msg, setMsg] = useState(0);
  const [retrying, setRetrying] = useState<string | null>(null);
  const [cap, setCap] = useState<{ outputId: number; platform: string } | null>(null);

  useEffect(() => {
    if (!open || results) return;
    setMsg(0);
    const iv = setInterval(() => setMsg((i) => (i + 1) % MESSAGES.length), 1400);
    return () => clearInterval(iv);
  }, [open, results]);

  if (!open) return null;
  const done = !!results;

  const retry = async (outputId: number, platform: string, mode: "normal" | "draft" | "delayed") => {
    setRetrying(`${outputId}:${platform}`);
    setCap(null);
    try {
      const res = await retryOutput(outputId, mode);
      onResults(
        (results ?? []).map((r) => {
          if (r.output_id !== outputId) return r;
          const next = { ...r.platforms };
          const got = (res as { platforms?: Record<string, PlatformResult> })?.platforms?.[platform];
          if (got) next[platform] = got;
          else if (mode === "delayed")
            next[platform] = { status: "failed", friendly_error: "Retrying in 6 hours — nothing more to do" };
          return { ...r, platforms: next };
        }),
      );
    } finally {
      setRetrying(null);
    }
  };

  const tally = (results ?? []).flatMap((r) => Object.values(r.platforms));
  const counts = {
    ok: tally.filter((v) => v.status === "posted" && !v.draft).length,
    draft: tally.filter((v) => v.status === "posted" && v.draft).length,
    failed: tally.filter((v) => v.status === "failed").length,
    skipped: tally.filter((v) => v.status === "skipped").length,
  };

  return (
    <>
      <Dialog
        open
        onClose={done ? onClose : () => {}}
        label={done ? "How the posting went" : "Posting"}
        size={done ? "md" : "sm"}
      >
        {!done ? (
          <div className="flex flex-col items-center px-[22px] pb-[30px] pt-[26px]">
            <Clerk />
            <p className="mt-3.5 text-sm font-semibold leading-normal tracking-[-0.01em]">{MESSAGES[msg]}</p>
            <div className="mt-4 flex w-full max-w-[290px] flex-col gap-[7px]">
              {destinations.map((d) => (
                <div
                  key={d.account}
                  className="flex items-center gap-2.5 rounded-[11px] border border-border bg-secondary px-3 py-2"
                >
                  <span className="min-w-0 flex-1 truncate text-xs font-semibold leading-normal text-muted-foreground">
                    {d.account}
                  </span>
                  <span className="flex flex-none gap-[7px]">
                    {d.platforms.map((p, i) => (
                      <span
                        key={p}
                        title={PLAT_NAME[p] ?? p}
                        className="pm-dot grid place-items-center text-subtle"
                        style={{ animationDelay: `${i * 0.14}s` }}
                      >
                        <PlatformIcon platform={p} className="h-[13px] w-[13px]" />
                      </span>
                    ))}
                  </span>
                </div>
              ))}
            </div>
            <p className="mt-4 max-w-[34ch] text-center text-[11px] leading-[1.55] text-subtle">
              This can take up to a minute. Leave it open — the result only shows up here.
            </p>
            <style>{`
              .pm-dot{animation:pmWait 1.5s ease-in-out infinite}
              @keyframes pmWait{0%,100%{opacity:.3}50%{opacity:1}}
              @media (prefers-reduced-motion:reduce){.pm-dot{animation:none;opacity:.7}}
            `}</style>
          </div>
        ) : (
          <>
            <DialogHead
              title={counts.ok || counts.draft ? (counts.failed ? "Posted, with some to sort out" : "All posted") : "Nothing was posted"}
              sub={
                counts.failed
                  ? "What is still red was refused by the platform, not by us. Retry sends only that one again."
                  : "Every connected platform took it."
              }
              onClose={onClose}
            />
            <DialogBody>
              <div className="mb-4 flex flex-wrap gap-[7px]">
                {(
                  [
                    [counts.ok, "posted", "var(--color-good)"],
                    [counts.draft, "in drafts", "#EB6834"],
                    [counts.failed, "refused", "var(--color-destructive)"],
                    [counts.skipped, "skipped", "var(--color-subtle)"],
                  ] as const
                )
                  .filter(([c]) => c > 0)
                  .map(([c, label, colour]) => (
                    <span
                      key={label}
                      className="inline-flex items-center gap-1.5 rounded-full border border-border bg-secondary px-2.5 py-[5px] text-[11.5px] font-semibold tabular-nums leading-normal text-muted-foreground"
                    >
                      <i className="h-[7px] w-[7px] flex-none rounded-full" style={{ background: colour }} />
                      {c} {label}
                    </span>
                  ))}
              </div>

              {(results ?? []).map((r, i) => (
                <div key={i} className="mb-3.5 last:mb-0">
                  <div className="mb-[7px] text-[10.5px] font-bold uppercase leading-normal tracking-[0.08em] text-subtle">
                    {r.account_name}
                  </div>
                  {Object.entries(r.platforms).map(([plat, v]) => (
                    <ResultRow
                      key={plat}
                      platform={plat}
                      result={v}
                      busy={retrying === `${r.output_id}:${plat}`}
                      locked={!!retrying}
                      onRetry={
                        r.output_id
                          ? () =>
                              isCapError(v.error) && plat === "tiktok"
                                ? setCap({ outputId: r.output_id!, platform: plat })
                                : retry(r.output_id!, plat, "normal")
                          : undefined
                      }
                    />
                  ))}
                </div>
              ))}

              <Hint>
                Nothing retries on its own. What went out is up; the rest waits here, and on the post, until you clear
                it.
              </Hint>
            </DialogBody>
            <DialogFoot note="Retrying sends only that one platform again.">
              <GhostButton onClick={onClose}>Close</GhostButton>
            </DialogFoot>
          </>
        )}
      </Dialog>

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
    </>
  );
}

function ResultRow({
  platform,
  result,
  busy,
  locked,
  onRetry,
}: {
  platform: string;
  result: PlatformResult;
  busy: boolean;
  locked: boolean;
  onRetry?: () => void;
}) {
  const ok = result.status === "posted" && !result.draft;
  const draft = result.status === "posted" && !!result.draft;
  const failed = result.status === "failed";
  // A cap error is TikTok telling us the app is still in review, not a
  // problem with this post. The raw code says nothing to whoever is
  // reading it, so the row says what it means and the retry asks how.
  const capped = failed && isCapError(result.error);
  const text = ok
    ? "Posted live"
    : draft
      ? `Sent to drafts — open ${PLAT_NAME[platform] ?? platform} to publish`
      : capped
        ? "TikTok is capping this app's live posts — it can go to your drafts instead"
        : failed
          ? result.friendly_error || result.error || "Refused"
          : result.reason
            ? result.reason
            : "skipped";

  const tone = ok
    ? "border-border"
    : draft
      ? "border-[rgba(235,104,52,0.34)]"
      : failed
        ? "border-destructive/35"
        : "border-border opacity-60";

  return (
    <div className={`mb-1.5 flex items-center gap-2.5 rounded-[12px] border bg-card px-3 py-[9px] last:mb-0 ${tone}`}>
      <span className="grid h-[27px] w-[27px] flex-none place-items-center rounded-[9px] border border-border bg-secondary text-muted-foreground">
        <PlatformIcon platform={platform} className="h-[13px] w-[13px]" />
      </span>
      <div className="min-w-0 flex-1">
        <div className="text-[12.5px] font-semibold leading-normal">{PLAT_NAME[platform] ?? platform}</div>
        <div
          className={`text-[11px] leading-[1.45] ${
            failed ? "text-destructive" : draft ? "text-[#B25E09] dark:text-[#F2A25C]" : "text-subtle"
          }`}
        >
          {text}
        </div>
      </div>
      {(failed || draft) && onRetry && (
        <button
          type="button"
          onClick={onRetry}
          disabled={locked}
          className="inline-flex flex-none items-center gap-1.5 whitespace-nowrap rounded-[9px] border border-border bg-card px-2.5 py-[5px] text-[11px] font-semibold leading-normal text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground disabled:opacity-45"
        >
          <RefreshCw className={`h-[11px] w-[11px] ${busy ? "animate-spin" : ""}`} />
          {busy ? "Retrying…" : draft ? "Retry live" : capped ? "Choose how" : "Retry"}
        </button>
      )}
      <span
        className={`grid h-[19px] w-[19px] flex-none place-items-center rounded-full ${
          ok
            ? "bg-good/15 text-good"
            : draft
              ? "bg-[rgba(235,104,52,0.14)] text-[#B25E09] dark:text-[#F2A25C]"
              : failed
                ? "bg-destructive/15 text-destructive"
                : "bg-secondary text-subtle"
        }`}
      >
        {ok ? (
          <Check className="h-[11px] w-[11px]" strokeWidth={3} />
        ) : draft ? (
          <Clock className="h-[11px] w-[11px]" />
        ) : failed ? (
          <X className="h-[11px] w-[11px]" strokeWidth={3} />
        ) : (
          <Minus className="h-[11px] w-[11px]" strokeWidth={3} />
        )}
      </span>
    </div>
  );
}
