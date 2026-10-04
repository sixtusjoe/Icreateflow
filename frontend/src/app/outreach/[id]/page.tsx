"use client";

/**
 * One campaign: what it does, what it has done, and what is holding it up.
 *
 * The layout follows the question order. The header says what state it is
 * in and carries the run controls. Delivery answers "how far along". The
 * target table answers "which ones, and why did those fail". The rail
 * answers "who is sending, what are they sending, and under what limits".
 *
 * Two things here are live rather than loaded once: while the campaign is
 * running a small progress call patches the counters in place every three
 * seconds, and while a watched browser is open its state is polled every
 * two. Neither reloads the page, because a table that jumps under the
 * cursor is worse than a counter that lags.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  Activity,
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  Check,
  ChevronDown,
  Copy,
  Clock,
  Download,
  ExternalLink,
  Eye,
  FileText,
  Info,
  MessageCircle,
  MessageSquare,
  Pause,
  Play,
  Plus,
  RefreshCw,
  RotateCcw,
  Send,
  Sparkles,
  Square,
  Trash2,
  Upload,
  UserMinus,
  Users,
} from "lucide-react";
import { toast } from "sonner";
import {
  assignOutreachAccount,
  campaignAttachmentUrl,
  clearCampaignAttachment,
  deleteOutreachCampaign,
  downloadOutreachResults,
  getOutreachCampaign,
  getOutreachProgress,
  getWatchState,
  listOutreachTargets,
  pauseOutreachCampaign,
  resumeOutreachCampaign,
  retryOutreachFailed,
  unfollowEveryoneFollowed,
  setCampaignAttachment,
  startOutreachCampaign,
  startWatchRun,
  stopOutreachCampaign,
  unassignOutreachAccount,
  updateOutreachCampaign,
  type OutreachAccount,
  type OutreachAudit,
  type OutreachCampaign,
  type OutreachJob,
  type OutreachTarget,
  type WatchState,
} from "@/lib/api";
import { SessionViewer } from "@/components/outreach/SessionViewer";
import {
  Avatar,
  BackLink,
  Band,
  Card,
  CardBody,
  CardHead,
  CAMPAIGN_TONE,
  Chip,
  CollapseButton,
  DotsMenu,
  Empty,
  FigureLine,
  FigureStrong,
  KV,
  Legend,
  MenuItem,
  Minis,
  MONO,
  n,
  PageActions,
  PageHead,
  PageTitle,
  PLATFORM_LABEL,
  PrimaryButton,
  RailLink,
  StackBar,
  Tabs,
  Tag,
  TARGET_TONE,
  TD,
  TH,
  TwoCol,
  useCollapsed,
} from "@/components/kit";
import { ConfirmDialog } from "@/components/kit/dialog";
import { ImportDialog } from "@/components/outreach/import-dialog";
import { ExportDialog } from "@/components/outreach/export-dialog";
import { CommentSetupDialog, MessageSetupDialog } from "@/components/outreach/setup-dialogs";
import { campaignIdFromParam, campaignPath } from "@/components/outreach/campaign-url";
import { LeadFinderDialog } from "./lead-finder";
import { apiErrorMessage, relativeTime } from "@/components/kit/format";

type Detail = {
  campaign: OutreachCampaign;
  target_counts: Record<string, number>;
  job_counts: Record<string, number>;
  success_outcomes?: Record<string, number>;
  recent_jobs: OutreachJob[];
  failed_jobs: OutreachJob[];
  assigned_account_ids: number[];
  eligible_account_ids: number[];
  accounts: OutreachAccount[];
  audit: OutreachAudit[];
  limits: { max_jobs: number; max_jobs_per_account: number; retry_limit: number };
  workers_enabled: boolean;
  driver: string;
};

type Activity3 = "message" | "follow" | "unfollow" | "comment";

/** What a running campaign is doing this second (the progress poll's `live`). */
type LiveNow = {
  jobs: {
    id: number;
    step: string | null;
    step_at: string | null;
    started_at: string | null;
    username: string;
    account_name: string | null;
    account_via: string | null;
  }[];
  next_send_at: string | null;
  last: { status: string; result_status: string | null; completed_at: string; username: string } | null;
};

/** The steps each kind of job goes through, in order, as the driver reports them. */
const LIVE_STEPS: Record<Activity3, { key: string; label: string }[]> = {
  message: [
    { key: "opening_profile", label: "Opening profile" },
    { key: "opening_chat", label: "Clicking Message" },
    { key: "typing", label: "Typing" },
    { key: "sending", label: "Sending" },
    { key: "checking", label: "Checking delivery" },
  ],
  follow: [
    { key: "opening_profile", label: "Opening profile" },
    { key: "following", label: "Following" },
  ],
  unfollow: [
    { key: "opening_profile", label: "Opening profile" },
    { key: "unfollowing", label: "Unfollowing" },
  ],
  comment: [
    { key: "opening_video", label: "Opening the video" },
    { key: "typing", label: "Typing" },
    { key: "posting", label: "Posting" },
  ],
};

/** The headline for a step, said about the person. */
function stepSentence(step: string | null, who: string): string {
  switch (step) {
    case "opening_profile": return `Opening ${who}’s profile`;
    case "following_first": return `Following ${who} first`;
    case "opening_chat": return `Clicking Message on ${who}’s profile`;
    case "typing": return `Typing the message to ${who}`;
    case "sending": return `Sending to ${who}`;
    case "checking": return `Checking it reached ${who}`;
    case "following": return `Following ${who}`;
    case "unfollowing": return `Unfollowing ${who}`;
    case "opening_video": return "Opening the video";
    case "posting": return "Posting the comment";
    case "on_phone": return `Handed to the phone — it’s working on ${who}`;
    default: return `Starting the browser for ${who}`;
  }
}

const DONE_VERB: Record<Activity3, string> = {
  message: "Sent to",
  follow: "Followed",
  unfollow: "Unfollowed",
  comment: "Commented for",
};

function secondsSince(iso: string | null, now: number): number {
  return iso ? Math.max(0, Math.floor((now - new Date(iso).getTime()) / 1000)) : 0;
}

function LiveCard({ live, activity }: { live: LiveNow | null; activity: Activity3 }) {
  // One clock for the elapsed and countdown figures between the 3s polls.
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const iv = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(iv);
  }, []);

  const steps = LIVE_STEPS[activity];
  const jobs = live?.jobs ?? [];
  const wait = live?.next_send_at ? Math.ceil((new Date(live.next_send_at).getTime() - now) / 1000) : 0;
  const last = live?.last;

  return (
    <div className="mb-4 rounded-xl border border-emerald-500/30 bg-emerald-500/[0.06] p-4" aria-live="polite">
      <div className="flex items-center gap-2">
        <span className="relative flex h-2.5 w-2.5">
          <span className="absolute inline-flex h-full w-full rounded-full bg-emerald-500 opacity-60 motion-safe:animate-ping" />
          <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-emerald-500" />
        </span>
        <p className="text-sm font-semibold">Running now</p>
      </div>

      {jobs.length === 0 ? (
        <p className="mt-2 text-sm text-muted-foreground">
          {wait > 0
            ? `Resting between sends — next one in ${wait}s.`
            : "Picking the next person…"}
        </p>
      ) : (
        <div className="mt-3 flex flex-col gap-3">
          {jobs.map((j) => {
            const who = `@${j.username}`;
            const at = steps.findIndex((st) => st.key === (j.step === "following_first" ? "opening_profile" : j.step));
            return (
              <div key={j.id} className="min-w-0">
                <p className="text-sm font-medium">
                  {stepSentence(j.step, who)}
                  <span className="font-normal text-muted-foreground">
                    {" "}· {secondsSince(j.step_at ?? j.started_at, now)}s
                  </span>
                </p>
                {j.account_name && (
                  <p className="text-xs text-muted-foreground">from {j.account_name}</p>
                )}
                {j.step !== "on_phone" && (
                  <ol className="mt-2 flex flex-wrap gap-1.5">
                    {steps.map((st, i) => {
                      const state = i < at ? "done" : i === at ? "now" : "todo";
                      return (
                        <li
                          key={st.key}
                          className={`rounded-full border px-2.5 py-0.5 text-[11.5px] ${
                            state === "done"
                              ? "border-emerald-500/40 bg-emerald-500/15 text-foreground"
                              : state === "now"
                                ? "border-emerald-500 bg-emerald-500 font-semibold text-white motion-safe:animate-pulse"
                                : "border-border text-muted-foreground"
                          }`}
                        >
                          {state === "done" ? "✓ " : ""}
                          {st.label}
                        </li>
                      );
                    })}
                  </ol>
                )}
              </div>
            );
          })}
        </div>
      )}

      {last && (
        <p className="mt-3 border-t border-emerald-500/20 pt-2 text-xs text-muted-foreground">
          Last:{" "}
          {last.status === "succeeded"
            ? `${DONE_VERB[activity]} @${last.username}`
            : `didn’t reach @${last.username}${last.result_status ? ` (${last.result_status.replace(/_/g, " ")})` : ""}`}
          {" "}· {relativeTime(last.completed_at)}
        </p>
      )}
    </div>
  );
}

const TARGET_TABS = ["all", "queued", "processing", "sent", "failed", "skipped", "paused"] as const;
/**
 * Rows per page.
 *
 * It was 100, from when the targets were the only thing on the page. With
 * a rail of five cards beside them, 100 rows made the column seven
 * screenfuls against the rail's one and a half — so the page was mostly a
 * list nobody scrolls, with the pager stranded at the bottom of it. Twenty
 * keeps the two columns roughly the same height and makes the pager the
 * way through the list, which is what it is for.
 */
const TARGET_PAGE_SIZE = 20;
/** The log is a symptom list, not an archive — the CSV export is the archive. */
const ERROR_LOG_SHOWN = 8;

const TASKS: { key: Activity3; label: string; icon: React.ComponentType<{ className?: string }> }[] = [
  { key: "message", label: "Message", icon: MessageCircle },
  { key: "follow", label: "Follow", icon: Users },
  { key: "unfollow", label: "Unfollow", icon: UserMinus },
  { key: "comment", label: "Comment", icon: MessageSquare },
];

/** The delivery card counts a different act in each mode, so it says so. */
const DELIVERY_SUB: Record<Activity3, string> = {
  message: "Messages sent against every target imported",
  follow: "Follows completed against every target imported",
  unfollow: "Unfollows completed against every target imported",
  comment: "Comments left against the run's comment count",
};

const when = (s: string | null | undefined) => (s ? relativeTime(s) : "—");

/** Time left on a platform cooldown, ticking once a second.
 *
 *  The deadline comes from the server on every poll rather than being a
 *  duration the browser started counting when the page happened to open —
 *  a tab left open overnight would otherwise show a countdown that ran out
 *  hours ago, or never.
 */
function RefusedNotice({
  reason,
  stillRefused,
  accountRefused,
}: {
  reason: string;
  stillRefused: boolean;
  accountRefused: boolean;
}) {
  const red = stillRefused || accountRefused;
  return (
    <div
      className={`mb-4 rounded-xl border p-4 ${
        red ? "border-red-500/40 bg-red-500/10" : "border-border bg-muted/40"
      }`}
    >
      <p className="text-sm font-medium">
        {accountRefused
          ? "Paused — the platform is refusing this sending account"
          : stillRefused
            ? "Paused — the message was refused"
            : "Message changed — ready to resume"}
      </p>
      <p className="mt-1 text-sm text-muted-foreground">{reason}</p>
      <p className="mt-1 text-xs text-muted-foreground">
        {accountRefused
          ? "A different message from the same account was refused too, so editing the wording will not help. Give the campaign another account, then resume."
          : stillRefused
            ? "This could be the wording or the account. The campaign will not start again on the same words — edit the message, then resume. If the new message is refused too, the account is the problem."
            : "The new wording has not been tried yet. Resume when you are ready."}
      </p>
    </div>
  );
}

function LimitCountdown({ until, reason }: { until: string; reason?: string | null }) {
  const target = new Date(until).getTime();
  const [left, setLeft] = useState(() => target - Date.now());

  useEffect(() => {
    const iv = setInterval(() => setLeft(target - Date.now()), 1000);
    return () => clearInterval(iv);
  }, [target]);

  // The 3s poll flips the campaign back to running and this unmounts; until
  // then, say it is finishing rather than counting into the negative.
  if (left <= 0) {
    return (
      <div className="mb-4 rounded-xl border border-border bg-muted/40 p-4">
        <p className="text-sm font-medium">The wait is over — resuming shortly.</p>
      </div>
    );
  }

  const total = Math.floor(left / 1000);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const sec = total % 60;
  const clock = h > 0
    ? `${h}h ${String(m).padStart(2, "0")}m ${String(sec).padStart(2, "0")}s`
    : `${m}m ${String(sec).padStart(2, "0")}s`;

  return (
    <div className="mb-4 rounded-xl border border-amber-500/40 bg-amber-500/10 p-4">
      <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="text-sm font-medium">Paused — the platform set a limit</p>
          {reason ? (
            <p className="mt-1 text-sm text-muted-foreground">&ldquo;{reason}&rdquo;</p>
          ) : null}
          <p className="mt-1 text-xs text-muted-foreground">
            The sending account is untouched and can still be used by other
            campaigns. This one resumes itself when the clock runs out.
          </p>
        </div>
        <p className="shrink-0 text-2xl font-semibold tabular-nums">{clock}</p>
      </div>
    </div>
  );
}

export default function OutreachCampaignPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  // The path segment reads as the campaign's name and ends in its id.
  // Either shape resolves, so links made before this still work.
  const id = campaignIdFromParam(params?.id);

  const [detail, setDetail] = useState<Detail | null>(null);
  const [live, setLive] = useState<LiveNow | null>(null);
  const [targets, setTargets] = useState<OutreachTarget[]>([]);
  const [targetTab, setTargetTab] = useState<string>("all");
  const [targetPage, setTargetPage] = useState(0);
  const [targetTotal, setTargetTotal] = useState(0);
  const [busy, setBusy] = useState(false);
  const [watch, setWatch] = useState<WatchState | null>(null);
  const [lastRefresh, setLastRefresh] = useState<number>(Date.now());

  const [showImport, setShowImport] = useState(false);
  const [showExport, setShowExport] = useState(false);
  const [showFind, setShowFind] = useState(false);
  const [showMessage, setShowMessage] = useState(false);
  const [showComments, setShowComments] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [showAll, setShowAll] = useState(false);

  /** Which rail boxes are shut. Remembered, so a box you closed stays
   *  closed on the next campaign and the next visit. */
  const [shut, toggle] = useCollapsed("outreach_campaign_rail");

  const imageRef = useRef<HTMLInputElement>(null);

  // A renamed campaign leaves a stale name in the path. The id is what
  // resolved the page, so the slug is corrected in place rather than
  // navigated — no new history entry for something nobody asked for.
  const loadedName = detail?.campaign.name;
  useEffect(() => {
    if (!loadedName || !Number.isFinite(id)) return;
    const want = campaignPath({ id, name: loadedName });
    if (window.location.pathname !== want) {
      window.history.replaceState(null, "", want + window.location.search);
    }
  }, [loadedName, id]);

  // `?import=1` opens the import dialog — that is how the campaign list's
  // "Import targets" arrives here. Read from the URL rather than with
  // `useSearchParams`, which would need its own Suspense boundary to
  // prerender and buys nothing for a flag consulted once.
  useEffect(() => {
    if (new URLSearchParams(window.location.search).get("import") === "1") setShowImport(true);
  }, []);

  const loadDetail = useCallback(async () => {
    if (!Number.isFinite(id)) return;
    try {
      setDetail(await getOutreachCampaign(id));
      setLastRefresh(Date.now());
    } catch (e) {
      toast.error(apiErrorMessage(e, "Failed to load campaign"));
    }
  }, [id]);

  const loadTargets = useCallback(async () => {
    if (!Number.isFinite(id)) return;
    try {
      const data = await listOutreachTargets(id, {
        status: targetTab === "all" ? undefined : targetTab,
        limit: TARGET_PAGE_SIZE,
        offset: targetPage * TARGET_PAGE_SIZE,
      });
      setTargets(data.targets);
      // The tab decides what is being counted: "all" is everything, a
      // status tab is only that status.
      setTargetTotal(targetTab === "all" ? data.total : (data.counts?.[targetTab] ?? 0));
    } catch {
      /* the detail call already surfaced any auth/404 problem */
    }
  }, [id, targetTab, targetPage]);

  // A different tab is a different list; staying on page 7 of it shows an
  // empty table and looks like the targets are gone.
  useEffect(() => {
    setTargetPage(0);
  }, [targetTab]);

  useEffect(() => {
    loadDetail();
  }, [loadDetail]);
  useEffect(() => {
    loadTargets();
  }, [loadTargets]);

  // Live monitoring: while a campaign is running the counters move on their
  // own, so poll the small progress endpoint every 3s and patch the
  // campaign in place — no full page reload, no flicker.
  const running = detail?.campaign.status === "running";
  useEffect(() => {
    if (!running || !Number.isFinite(id)) return;
    const iv = setInterval(async () => {
      try {
        const p = await getOutreachProgress(id);
        setLastRefresh(Date.now());
        setDetail((prev) =>
          prev
            ? {
                ...prev,
                campaign: {
                  ...prev.campaign,
                  status: p.status,
                  total_targets: p.total_targets,
                  queued_count: p.queued_count,
                  processed_count: p.processed_count,
                  successful_count: p.successful_count,
                  failed_count: p.failed_count,
                  paused_until: p.paused_until,
                  paused_reason: p.paused_reason,
                  message_refused: p.message_refused,
                  account_refused: p.account_refused,
                },
                target_counts: p.target_counts,
                success_outcomes: p.success_outcomes,
                recent_jobs: p.recent_jobs,
              }
            : prev,
        );
        setLive(p.live ?? null);
        if (p.status !== "running") await loadDetail();
        await loadTargets();
      } catch {
        /* transient — the next tick retries */
      }
    }, 3000);
    return () => clearInterval(iv);
  }, [running, id, loadDetail, loadTargets]);

  // Can this host open a window, and is one open right now?
  useEffect(() => {
    let live = true;
    getWatchState(id)
      .then((w) => live && setWatch(w))
      .catch(() => live && setWatch(null));
    return () => {
      live = false;
    };
  }, [id]);

  // While a window is open, poll it. A run outlives the request that
  // started it — a puzzle alone can hold the page for five minutes.
  useEffect(() => {
    if (!watch?.running) return;
    const iv = setInterval(async () => {
      try {
        const next = await getWatchState(id);
        setWatch(next);
        if (next.watch?.done) {
          if (next.watch.status === "failed") toast.error(next.watch.message);
          else toast.success(next.watch.message);
          await loadDetail();
          await loadTargets();
        }
      } catch {
        /* a dropped poll is not a failed run */
      }
    }, 2000);
    return () => clearInterval(iv);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, watch?.running]);

  const act = async (fn: () => Promise<unknown>, message: string) => {
    setBusy(true);
    try {
      await fn();
      toast.success(message);
      await loadDetail();
      await loadTargets();
    } catch (e) {
      toast.error(apiErrorMessage(e, "Action failed"));
    } finally {
      setBusy(false);
    }
  };

  const handleWatch = async () => {
    try {
      const started = await startWatchRun(id);
      setWatch((prev) => (prev ? { ...prev, running: true, watch: started } : prev));
      toast.success("A browser window is opening — watch it work");
    } catch (e) {
      toast.error(apiErrorMessage(e, "Could not start a watched run"));
    }
  };

  const handleAttach = async (file?: File) => {
    if (!file) return;
    setBusy(true);
    try {
      await setCampaignAttachment(id, file);
      toast.success("Image attached — it will be sent with every message");
      await loadDetail();
    } catch (e) {
      toast.error(apiErrorMessage(e, "Could not attach that image"));
    } finally {
      setBusy(false);
      if (imageRef.current) imageRef.current.value = "";
    }
  };

  /** Opens the options rather than downloading everything on the spot. */
  const handleExport = () => setShowExport(true);

  const accountsById = useMemo(() => {
    const map = new Map<number, OutreachAccount>();
    detail?.accounts.forEach((a) => map.set(a.id, a));
    return map;
  }, [detail]);

  if (!detail) {
    return (
      <div className="flex min-h-[50vh] items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-foreground border-t-transparent" />
      </div>
    );
  }

  const c = detail.campaign;
  const status = c.status;
  const activity: Activity3 = (c.activity ?? "message") as Activity3;
  const locked = busy || status === "running";

  /* ---------------- delivery ---------------- */

  const total = c.total_targets ?? 0;
  const counts = detail.target_counts;
  const sent = counts.sent ?? 0;
  const skipped = counts.skipped ?? 0;
  const failed = counts.failed ?? 0;
  const queued = Math.max(total - sent - skipped - failed, 0);
  const attempted = sent + skipped + failed;
  const pct = total ? (sent / total) * 100 : 0;

  // A "sent" count answers less than it looks for a follow campaign. Only
  // `sent` moved the account's following number; `already_following` means
  // the profile was followed before we arrived and nothing was pressed,
  // and `follow_requested` is a private account waiting on a person. A run
  // showing 56 sent while the account gained 16 follows is not broken — it
  // is 40 of these — but there was no way to see that.
  const outcomes = detail.success_outcomes ?? {};
  const actuallyDid = outcomes.sent ?? 0;
  const alreadyDone = (outcomes.already_following ?? 0) + (outcomes.not_following ?? 0);
  const awaitingAccept = outcomes.follow_requested ?? 0;
  const showOutcomes = alreadyDone > 0 || awaitingAccept > 0;

  const bands: Band[] = [
    { label: "Queued", value: queued, color: "var(--chart-1)" },
    { label: "Sent", value: sent, color: "var(--chart-2)" },
    { label: "Skipped & failed", value: skipped + failed, color: "var(--chart-3)" },
  ];

  /* ---------------- accounts ---------------- */

  const assigned = new Set(detail.assigned_account_ids);
  const eligible = new Set(detail.eligible_account_ids);
  const platformAccounts = detail.accounts;
  const visibleAccounts = showAll ? platformAccounts : platformAccounts.filter((a) => assigned.has(a.id));

  /** Why an assigned account still cannot send. Null when it can. */
  const blockedReason = (a: OutreachAccount) => {
    if (!a.enabled) return "Disabled — cannot send";
    if (a.status === "paused") return a.paused_reason || "Paused after repeated failures";
    // A phone account never has a browser session — the phone app is its
    // sign-in — and it only does follows (services/outreach/accounts.py:fits).
    if (a.via === "phone") {
      if (a.platform !== "tiktok" || (activity !== "follow" && activity !== "message" && activity !== "unfollow"))
        return "Phone accounts only do TikTok follows, unfollows and messages for now";
      if (activity === "message" && c.has_attachment) return "Phone accounts can’t send images yet";
      return a.companion_device ? null : "On phone — no phone has linked it yet";
    }
    if (!a.has_session && !a.session_reference) return "No browser session";
    return null;
  };

  const assignSub = assigned.size
    ? `${[...assigned].filter((x) => eligible.has(x)).length} of ${assigned.size} assigned accounts can send`
    : `No accounts pinned — any enabled ${PLATFORM_LABEL[c.platform] ?? c.platform} account may send`;

  /* ---------------- header ---------------- */

  const runButtons = () => {
    if (status === "draft" || status === "stopped" || status === "completed")
      return (
        <PrimaryButton
          icon={Play}
          disabled={busy}
          onClick={async () => {
            await act(() => startOutreachCampaign(id), "Campaign started");
            // A comment campaign is watched from the first comment. The
            // whole point of commenting from several accounts is seeing
            // what lands under the video, and the browser runs wherever
            // the backend does.
            if (activity === "comment") await handleWatch();
          }}
        >
          Start campaign
        </PrimaryButton>
      );
    if (status === "running")
      return (
        <>
          <Chip icon={Pause} disabled={busy} onClick={() => act(() => pauseOutreachCampaign(id), "Campaign paused")}>
            Pause
          </Chip>
          <PrimaryButton icon={Square} disabled={busy} onClick={() => act(() => stopOutreachCampaign(id), "Campaign stopped")}>
            Stop
          </PrimaryButton>
        </>
      );
    if (status === "paused")
      return (
        <>
          <Chip icon={Square} disabled={busy} onClick={() => act(() => stopOutreachCampaign(id), "Campaign stopped")}>
            Stop
          </Chip>
          <PrimaryButton icon={Play} disabled={busy} onClick={() => act(() => resumeOutreachCampaign(id), "Campaign resumed")}>
            Resume
          </PrimaryButton>
        </>
      );
    return null;
  };

  const moreMenu: MenuItem[] = [
    { label: "Refresh now", icon: RefreshCw, onClick: () => void loadDetail() },
    { label: "Find profiles", icon: Sparkles, onClick: () => setShowFind(true) },
    {
      label: "Retry failed",
      icon: RotateCcw,
      disabled: busy || failed === 0,
      onClick: () => act(() => retryOutreachFailed(id), "Failed targets re-queued"),
    },
    ...(watch?.available && !watch.sender_running
      ? [
          {
            label: watch.running ? "Watching…" : "Watch a send",
            icon: Eye,
            disabled: busy || watch.running || watch.busy_elsewhere,
            onClick: handleWatch,
          } as MenuItem,
        ]
      : []),
    // Undo exactly this campaign's own follows: a draft unfollow campaign of
    // the people counted as Followed, on the same accounts.
    ...(activity === "follow" && (c.platform === "tiktok" || c.platform === "instagram")
      ? [
          {
            label: "Unfollow everyone it followed",
            icon: UserMinus,
            disabled: busy || actuallyDid === 0,
            onClick: async () => {
              try {
                const made = await unfollowEveryoneFollowed(id);
                toast.success(
                  made.created
                    ? `Unfollow campaign made with ${made.people} people — start it when you’re ready`
                    : made.people > 0
                      ? `Added ${made.people} newly followed ${made.people === 1 ? "person" : "people"} to “${made.campaign.name}” — start or resume it`
                      : `Nobody new since last time — everyone followed is already on “${made.campaign.name}”`,
                );
                router.push(`/outreach/${made.campaign.id}`);
              } catch (e) {
                toast.error(apiErrorMessage(e, "Could not make the unfollow campaign"));
              }
            },
          } as MenuItem,
        ]
      : []),
    "-",
    { label: "Export as CSV", icon: Download, onClick: handleExport },
    { label: "Delete campaign", icon: Trash2, danger: true, onClick: () => setConfirmDelete(true) },
  ];

  /* ---------------- the task panel ---------------- */

  const railHead = (key: string, title: string, sub: React.ReactNode, menu: MenuItem[]) => (
    <CardHead
      title={title}
      sub={sub}
      collapsed={!!shut[key]}
      right={
        <>
          <CollapseButton open={!shut[key]} onToggle={() => toggle(key)} label={title} />
          <DotsMenu label={`${title} options`} items={menu} />
        </>
      }
    />
  );

  return (
    <div className="flex flex-col gap-4" data-metrics>
      <BackLink href="/outreach">All campaigns</BackLink>

      <PageHead>
        <PageTitle title={c.name} />
        <PageActions>
          <span className="text-[10.5px] font-bold uppercase leading-normal tracking-[0.09em] text-subtle">Task</span>
          <Tabs
            value={activity}
            onChange={(k) =>
              act(
                () => updateOutreachCampaign(id, { activity: k as Activity3 }),
                k === "follow"
                  ? "Now following"
                  : k === "unfollow"
                    ? "Now unfollowing"
                    : k === "comment"
                      ? "Now commenting"
                      : "Now messaging",
              )
            }
            items={TASKS.map((t) => ({ key: t.key, label: t.label, icon: t.icon }))}
            iconOnly
            // Switching mid-flight would leave some targets messaged and
            // some followed, with nothing recording which was which. The
            // server allows the edit on a running campaign — unlike the
            // message template, which it refuses — so the guard is here.
            // Once anyone is done, the rest of the list was picked for this
            // task: switched, a follow list ran its unfollowed half as
            // unfollows (2026-09-28). The server refuses that too.
            locked={
              running
                ? "Pause the campaign to change what it does"
                : c.processed_count > 0
                  ? activity === "follow"
                    ? "It has already followed people — to undo them, use “Unfollow everyone it followed” in the menu"
                    : "It has already worked on people — start a new campaign to do something else"
                  : busy
                    ? "Working…"
                    : undefined
            }
          />
          <span className="mx-[3px] h-[22px] w-px bg-border" />
          <Chip icon={Upload} onClick={() => setShowImport(true)} disabled={busy}>
            Import
          </Chip>
          {runButtons()}
          <DotsMenu
            label="More campaign actions"
            items={moreMenu}
            trigger={
              <span className="grid h-[37px] w-[37px] place-items-center rounded-[11px] border border-border bg-card text-muted-foreground shadow-card transition-colors hover:bg-secondary hover:text-foreground">
                <ChevronDown className="h-3.5 w-3.5" />
              </span>
            }
          />
        </PageActions>
      </PageHead>

      <div className="-mt-1 flex flex-wrap items-center gap-[9px]">
        <Tag tone={CAMPAIGN_TONE[status] ?? "draft"}>{status[0].toUpperCase() + status.slice(1)}</Tag>
        <span className="inline-flex items-center gap-1.5 text-xs leading-normal text-subtle">
          <Send className="h-[13px] w-[13px]" />
          {PLATFORM_LABEL[c.platform] ?? c.platform}
        </span>
        <span className="inline-flex items-center gap-1.5 text-xs leading-normal text-subtle">
          <Clock className="h-[13px] w-[13px]" />
          Created {c.created_at.slice(0, 10)}
        </span>
        <span className="inline-flex items-center gap-1.5 text-xs leading-normal text-subtle">
          <Activity className="h-[13px] w-[13px]" />
          {running ? "Live" : "Idle"} · updated {when(new Date(lastRefresh).toISOString())}
        </span>
        {c.description && <span className="text-xs leading-normal text-subtle">· {c.description}</span>}
      </div>

      {/* The watched run's own screen. The browser runs wherever the
          backend does, so on a server there was no way to see it — which
          left a verification puzzle solvable by someone with an SSH tunnel
          and by nobody else. */}
      {watch?.running && !watch.watch?.done && (
        <Card className="overflow-hidden">
          <CardHead title="Watching this run" sub={watch.watch?.message ?? "Opening…"} flush={false} />
          {watch.watch?.on_screen ? (
            <div className="flex h-[min(60vh,540px)] flex-col px-5 pb-5">
              <SessionViewer campaignId={id} />
            </div>
          ) : (
            <p className="px-5 pb-5 text-[12.5px] leading-[1.55] text-muted-foreground">
              The browser is open on the machine running the backend — look for the Chromium window. There is no screen
              to stream here.
            </p>
          )}
        </Card>
      )}

      {!detail.workers_enabled && (
        <div className="flex items-start gap-2 rounded-[14px] border border-warn/40 bg-warn/10 px-4 py-3.5 text-[12.5px] leading-[1.55] text-muted-foreground">
          <AlertTriangle className="mt-0.5 h-4 w-4 flex-none text-warn" />
          <p>
            All outreach workers are stopped by an administrator. Jobs stay queued until workers are re-enabled in the
            admin panel.
          </p>
        </div>
      )}

      <TwoCol
        main={
          <>
            <Card>
              <CardHead
                title="Delivery"
                sub={DELIVERY_SUB[activity]}
                right={
                  <DotsMenu
                    label="Delivery options"
                    items={[
                      { label: "Refresh now", icon: RefreshCw, onClick: () => void loadDetail() },
                      { label: "Export report", icon: Download, onClick: handleExport },
                      "-",
                      {
                        label: "Retry failed",
                        icon: RotateCcw,
                        disabled: busy || failed === 0,
                        onClick: () => act(() => retryOutreachFailed(id), "Failed targets re-queued"),
                      },
                    ]}
                  />
                }
              />
              <CardBody>
                <FigureLine value={`${pct.toFixed(1)}%`}>
                  <FigureStrong>{n(sent)}</FigureStrong> delivered of {n(total)} targets · {n(attempted)} attempted
                </FigureLine>
                <StackBar bands={bands} total={total} />
                <Legend bands={bands} />
                <Minis
                  cells={[
                    { label: "QUEUED", value: queued },
                    { label: "SENT", value: sent },
                    { label: "SKIPPED", value: skipped },
                    { label: "FAILED", value: failed },
                    {
                      label: "ATTEMPTS",
                      value: (detail.job_counts.succeeded ?? 0) + (detail.job_counts.failed ?? 0),
                    },
                  ]}
                />
                {showOutcomes && (
                  <div className="mt-4 rounded-lg border border-border bg-muted/40 p-4">
                    <p className="text-sm font-medium">What the successes were</p>
                    <div className="mt-3 grid gap-3 sm:grid-cols-3">
                      <div>
                        <p className="text-lg font-semibold tabular-nums">{n(actuallyDid)}</p>
                        <p className="text-xs text-muted-foreground">
                          {c.activity === "follow"
                            ? "Followed just now"
                            : c.activity === "unfollow"
                              ? "Unfollowed just now"
                              : "Delivered"}
                        </p>
                      </div>
                      <div>
                        <p className="text-lg font-semibold tabular-nums">{n(alreadyDone)}</p>
                        <p className="text-xs text-muted-foreground">
                          {c.activity === "unfollow"
                            ? "Not followed — nothing to undo"
                            : "Already followed — nothing pressed"}
                        </p>
                      </div>
                      <div>
                        <p className="text-lg font-semibold tabular-nums">{n(awaitingAccept)}</p>
                        <p className="text-xs text-muted-foreground">
                          Requested — private, awaiting acceptance
                        </p>
                      </div>
                    </div>
                    <p className="mt-3 text-xs text-muted-foreground">
                      Only the first number moved the account&apos;s following count. The
                      other two are successes with nothing done on the platform, which is
                      why a campaign can report more sent than the account gained.
                    </p>
                  </div>
                )}
              </CardBody>
            </Card>

            {c.status === "running" ? <LiveCard live={live} activity={activity} /> : null}
            {c.status === "paused" && c.paused_until ? (
              <LimitCountdown until={c.paused_until} reason={c.paused_reason} />
            ) : null}
            {/* A refusal has a reason and no clock — it waits for the words
                to change, not for time to pass. */}
            {c.status === "paused" && !c.paused_until && c.paused_reason ? (
              <RefusedNotice
                reason={c.paused_reason}
                stillRefused={!!c.message_refused}
                accountRefused={!!c.account_refused}
              />
            ) : null}

            <Card>
              <CardHead
                title="Targets"
                sub={`${n(total)} imported · showing ${targets.length}`}
                flush={false}
                right={
                  <DotsMenu
                    label="Targets options"
                    items={[
                      { label: "Import more", icon: Upload, onClick: () => setShowImport(true) },
                      { label: "Find profiles", icon: Sparkles, onClick: () => setShowFind(true) },
                      { label: "Export targets", icon: Download, onClick: handleExport },
                      "-",
                      {
                        label: "Retry every failure",
                        icon: RotateCcw,
                        disabled: busy || failed === 0,
                        onClick: () => act(() => retryOutreachFailed(id), "Failed targets re-queued"),
                      },
                    ]}
                  />
                }
              />
              <div className="px-5 pb-3.5">
                <Tabs
                  value={targetTab}
                  onChange={setTargetTab}
                  items={TARGET_TABS.map((k) => ({
                    key: k,
                    label: k === "all" ? "All" : k[0].toUpperCase() + k.slice(1),
                    count: k === "all" ? total : (counts[k] ?? 0),
                  }))}
                />
              </div>

              {targets.length === 0 ? (
                <Empty
                  icon={Upload}
                  title={targetTab === "all" ? "No targets yet" : `Nothing ${targetTab}`}
                  action={
                    targetTab === "all" ? (
                      <PrimaryButton icon={Upload} onClick={() => setShowImport(true)}>
                        Import targets
                      </PrimaryButton>
                    ) : undefined
                  }
                >
                  {targetTab === "all"
                    ? "Import a list of profiles, or let a discovery account find them for you."
                    : "Change the filter to see the rest of the list."}
                </Empty>
              ) : (
                <>
                  <div className="overflow-x-auto px-1.5 pb-2">
                    <table className="w-full table-fixed border-collapse">
                      <thead>
                        <tr>
                          <th className={TH}>Target</th>
                          <th className={`${TH} w-[118px]`}>State</th>
                          <th className={`${TH} w-[150px] max-md:hidden`}>Account</th>
                          <th className={`${TH} w-[82px] text-right max-md:hidden`}>Tries</th>
                          <th className={`${TH} w-[132px] pl-[18px] max-md:hidden`}>Last activity</th>
                        </tr>
                      </thead>
                      <tbody>
                        {targets.map((t) => (
                          <tr key={t.id} className="transition-colors last:[&>td]:border-b-0 hover:bg-secondary">
                            <td className={TD}>
                              <div className="flex min-w-0 flex-col gap-px">
                                <a
                                  href={t.profile_url}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  className="truncate font-semibold text-foreground hover:underline"
                                >
                                  @{t.username}
                                </a>
                                <span
                                  className={`truncate text-[11px] leading-normal ${
                                    t.error_message ? "text-bad" : "text-subtle"
                                  }`}
                                >
                                  {t.error_message || t.profile_url.replace("https://www.", "")}
                                </span>
                                {/* Phones drop the Account, Tries and Last activity columns, so they ride here. */}
                                <span className="truncate text-[11px] leading-normal text-subtle md:hidden">
                                  {t.assigned_account_id ? (accountsById.get(t.assigned_account_id)?.name ?? "—") : "—"} ·{" "}
                                  {t.attempts} {t.attempts === 1 ? "try" : "tries"} · {when(t.sent_at || t.last_attempt_at)}
                                </span>
                              </div>
                            </td>
                            <td className={TD}>
                              <Tag tone={TARGET_TONE[t.status] ?? "queue"}>
                                {t.status[0].toUpperCase() + t.status.slice(1)}
                              </Tag>
                            </td>
                            <td className={`${TD} text-xs text-muted-foreground max-md:hidden`}>
                              {t.assigned_account_id ? (accountsById.get(t.assigned_account_id)?.name ?? "—") : "—"}
                            </td>
                            <td className={`${TD} ${MONO} text-right max-md:hidden`}>{t.attempts}</td>
                            <td className={`${TD} pl-[18px] text-xs text-subtle max-md:hidden`}>
                              {when(t.sent_at || t.last_attempt_at)}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>

                  {targetTotal > TARGET_PAGE_SIZE && (
                    <div className="flex items-center justify-between border-t border-line-2 px-5 pb-4 pt-3 text-[11.5px] leading-normal text-subtle">
                      <span className="tabular-nums">
                        {(targetPage * TARGET_PAGE_SIZE + 1).toLocaleString()}–
                        {Math.min((targetPage + 1) * TARGET_PAGE_SIZE, targetTotal).toLocaleString()} of{" "}
                        {targetTotal.toLocaleString()}
                      </span>
                      <span className="flex gap-[7px]">
                        <button
                          type="button"
                          aria-label="Previous page"
                          onClick={() => setTargetPage((p) => Math.max(0, p - 1))}
                          disabled={targetPage === 0}
                          className="grid h-[30px] w-[30px] place-items-center rounded-[9px] border border-border bg-card text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground disabled:cursor-default disabled:opacity-40 disabled:hover:bg-card"
                        >
                          <ArrowLeft className="h-3.5 w-3.5" />
                        </button>
                        <button
                          type="button"
                          aria-label="Next page"
                          onClick={() => setTargetPage((p) => p + 1)}
                          disabled={(targetPage + 1) * TARGET_PAGE_SIZE >= targetTotal}
                          className="grid h-[30px] w-[30px] place-items-center rounded-[9px] border border-border bg-card text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground disabled:cursor-default disabled:opacity-40 disabled:hover:bg-card"
                        >
                          <ArrowRight className="h-3.5 w-3.5" />
                        </button>
                      </span>
                    </div>
                  )}
                </>
              )}
            </Card>

            {detail.failed_jobs.length > 0 && (
              <Card>
                {railHead(
                  "errors",
                  "Error log",
                  detail.failed_jobs.length > ERROR_LOG_SHOWN
                    ? `Newest ${ERROR_LOG_SHOWN} of ${n(detail.failed_jobs.length)} recent failures`
                    : `${detail.failed_jobs.length} recent failure${detail.failed_jobs.length === 1 ? "" : "s"}`,
                  [
                    {
                      label: "Retry every failure",
                      icon: RotateCcw,
                      disabled: busy || failed === 0,
                      onClick: () => act(() => retryOutreachFailed(id), "Failed targets re-queued"),
                    },
                    { label: "Export as CSV", icon: Download, onClick: handleExport },
                  ],
                )}
                {!shut.errors && (
                  <CardBody className="pt-2">
                    {detail.failed_jobs.slice(0, ERROR_LOG_SHOWN).map((job) => (
                      <div key={job.id} className="border-b border-line-2 py-2.5 last:border-b-0">
                        <div className="flex items-center justify-between gap-3">
                          <span className="font-mono text-[11px] text-subtle">
                            job #{job.id} · {job.result_status ?? "error"}
                          </span>
                          <span className="text-[11px] leading-normal text-subtle">{when(job.completed_at)}</span>
                        </div>
                        <p className="mt-0.5 text-[12.5px] leading-[1.5] text-bad">{job.error_message}</p>
                      </div>
                    ))}
                  </CardBody>
                )}
              </Card>
            )}
          </>
        }
        rail={
          <>
            {/* ---- sending from ---- */}
            <Card>
              {railHead("accounts", "Sending from", assignSub, [
                { label: "Add an account", icon: Plus, href: "/outreach/accounts?add=1" },
                { label: "Manage accounts", icon: Users, href: "/outreach/accounts" },
                "-",
                {
                  label: "Unassign all",
                  icon: Trash2,
                  danger: true,
                  disabled: busy || assigned.size === 0,
                  onClick: () =>
                    act(
                      () => Promise.all([...assigned].map((a) => unassignOutreachAccount(id, a))),
                      "Every account unassigned",
                    ),
                },
              ])}
              {!shut.accounts && (
                <CardBody className="pt-2.5">
                  {platformAccounts.length === 0 ? (
                    <p className="py-1 text-[12.5px] leading-[1.55] text-subtle">
                      No {PLATFORM_LABEL[c.platform] ?? c.platform} accounts yet.
                    </p>
                  ) : visibleAccounts.length === 0 ? (
                    <p className="py-1 text-[12.5px] leading-[1.55] text-subtle">
                      Nothing pinned — every enabled {PLATFORM_LABEL[c.platform] ?? c.platform} account is eligible.
                    </p>
                  ) : (
                    visibleAccounts.map((a) => {
                      const on = assigned.has(a.id);
                      const why = blockedReason(a);
                      return (
                        <div key={a.id} className="flex items-center gap-[11px] border-b border-line-2 py-[9px] last:border-b-0">
                          <Avatar platform={a.platform} />
                          <span className="flex min-w-0 flex-col gap-px">
                            <span className="truncate text-[13px] font-semibold leading-normal text-foreground">
                              {a.name}
                            </span>
                            <span className={`truncate text-[11px] leading-normal ${on && why ? "text-bad" : "text-subtle"}`}>
                              {on && why
                                ? why
                                : `${a.via === "phone" ? "Phone · " : ""}${n(a.messages_processed)} sent · ${n(a.error_count)} failed tries`}
                            </span>
                          </span>
                          <button
                            type="button"
                            disabled={busy}
                            aria-pressed={on}
                            onClick={() =>
                              act(
                                () => (on ? unassignOutreachAccount(id, a.id) : assignOutreachAccount(id, a.id)),
                                on ? "Account unassigned" : "Account assigned",
                              )
                            }
                            className={`ml-auto inline-flex flex-none items-center gap-[5px] whitespace-nowrap rounded-full border px-[11px] py-[5px] text-[11.5px] font-bold leading-normal transition-colors disabled:opacity-50 ${
                              on
                                ? "border-primary bg-primary text-primary-foreground"
                                : "border-border bg-card text-muted-foreground hover:bg-secondary hover:text-foreground"
                            }`}
                          >
                            {on && <Check className="h-3 w-3" strokeWidth={2.6} />}
                            {on ? "Assigned" : "Assign"}
                          </button>
                        </div>
                      );
                    })
                  )}
                  {platformAccounts.length > 0 && (
                    <RailLink icon={ChevronDown} spin={showAll} onClick={() => setShowAll((v) => !v)}>
                      {showAll
                        ? "Show assigned only"
                        : `View all ${platformAccounts.length} ${PLATFORM_LABEL[c.platform] ?? c.platform} accounts`}
                    </RailLink>
                  )}
                </CardBody>
              )}
            </Card>

            {/* ---- what it sends ---- */}
            {activity === "message" && (
              <Card>
                {railHead("task", "Message", "What each target receives", [
                  { label: "Edit message", icon: FileText, onClick: () => setShowMessage(true) },
                  {
                    label: "Copy text",
                    icon: Copy,
                    onClick: () => {
                      void navigator.clipboard.writeText(c.message_template ?? "");
                      toast.success("Message copied");
                    },
                  },
                ])}
                {!shut.task && (
                  <CardBody className="pt-3">
                    <div className="max-h-[132px] overflow-auto rounded-[12px] border border-border bg-secondary px-3.5 py-3 text-[12.5px] leading-[1.55] text-muted-foreground">
                      {c.message_template || "No message yet."}
                    </div>
                    <RailLink icon={FileText} onClick={() => setShowMessage(true)}>
                      Edit message
                    </RailLink>
                  </CardBody>
                )}
              </Card>
            )}

            {activity === "follow" && (
              <Card>
                {railHead("task", "Follow", "No message is sent", [
                  { label: "Import profiles", icon: Upload, onClick: () => setShowImport(true) },
                ])}
                {!shut.task && (
                  <CardBody className="pt-3">
                    <p className="flex items-start gap-2 text-[12.5px] leading-[1.55] text-subtle">
                      <Info className="mt-0.5 h-3.5 w-3.5 flex-none" />
                      <span>
                        Each target is followed from an assigned account. Nothing is written, so this campaign needs no
                        message and no template.
                      </span>
                    </p>
                  </CardBody>
                )}
              </Card>
            )}

            {activity === "unfollow" && (
              <Card>
                {railHead("task", "Unfollow", "Never follows anyone", [
                  { label: "Import profiles", icon: Upload, onClick: () => setShowImport(true) },
                ])}
                {!shut.task && (
                  <CardBody className="pt-3">
                    <p className="flex items-start gap-2 text-[12.5px] leading-[1.55] text-subtle">
                      <Info className="mt-0.5 h-3.5 w-3.5 flex-none" />
                      <span>
                        Each target is unfollowed from an assigned account. A profile that is not followed is left
                        alone, and an unfollow only counts once a reload of the profile shows Follow.
                      </span>
                    </p>
                  </CardBody>
                )}
              </Card>
            )}

            {activity === "comment" && (
              <Card>
                {railHead(
                  "task",
                  "Comments",
                  `${n(c.comment_count)} comment${c.comment_count === 1 ? "" : "s"} on one post`,
                  [
                    { label: "Comment setup", icon: FileText, onClick: () => setShowComments(true) },
                    ...(c.target_url
                      ? [{ label: "Open the post", icon: ExternalLink, href: c.target_url } as MenuItem]
                      : []),
                  ],
                )}
                {!shut.task && (
                  <CardBody className="pt-3">
                    {c.target_url ? (
                      <>
                        <div className="flex items-center justify-between gap-3 border-b border-line-2 py-[7px] text-[12.5px] leading-normal text-subtle">
                          <span>Post</span>
                          <a
                            href={c.target_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="max-w-[216px] truncate font-mono text-[11.5px] text-chart-2 hover:underline"
                          >
                            {c.target_url.split("?")[0].replace("https://www.", "")}
                          </a>
                        </div>
                        <KV label="Comments to leave">{n(c.comment_count)}</KV>
                        <KV label="Variations">{c.comment_variations?.length ?? 0}</KV>
                        <div className="mt-3 flex flex-col gap-[7px]">
                          {(c.comment_variations ?? []).map((v, i) => (
                            <div
                              key={i}
                              className="flex items-start gap-[9px] rounded-[10px] border border-border bg-secondary px-[11px] py-[9px] text-xs leading-[1.5] text-muted-foreground"
                            >
                              <span className="grid h-[17px] w-[17px] flex-none place-items-center rounded-[5px] bg-border text-[10px] font-bold leading-normal">
                                {i + 1}
                              </span>
                              <span>{v}</span>
                            </div>
                          ))}
                        </div>
                      </>
                    ) : (
                      <p className="text-[12.5px] leading-[1.55] text-subtle">
                        No post set yet — a comment campaign needs one video and at least one line to post.
                      </p>
                    )}
                    <PrimaryButton
                      icon={FileText}
                      className="mt-3 w-full justify-center"
                      onClick={() => setShowComments(true)}
                    >
                      Comment setup
                    </PrimaryButton>
                  </CardBody>
                )}
              </Card>
            )}

            {/* ---- image ---- */}
            {activity === "message" && (
              <Card>
                {railHead("image", "Image", c.has_attachment ? c.attachment_name || "Attached" : "None attached", [
                  {
                    label: c.has_attachment ? "Replace image" : "Add image",
                    icon: Plus,
                    onClick: () => imageRef.current?.click(),
                  },
                  ...(c.has_attachment
                    ? [
                        {
                          label: "Remove image",
                          icon: Trash2,
                          danger: true,
                          disabled: busy,
                          onClick: () => act(() => clearCampaignAttachment(id), "Image removed"),
                        } as MenuItem,
                      ]
                    : []),
                ])}
                {!shut.image && (
                  <CardBody className="pt-3">
                    <input
                      ref={imageRef}
                      type="file"
                      accept="image/jpeg,image/png,image/gif,image/webp"
                      className="hidden"
                      onChange={(e) => handleAttach(e.target.files?.[0])}
                    />
                    {c.has_attachment ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img
                        src={campaignAttachmentUrl(id)}
                        alt={c.attachment_name || "Campaign attachment"}
                        className="max-h-40 w-full rounded-[12px] border border-border object-contain"
                      />
                    ) : (
                      <>
                        <p className="text-[12.5px] leading-[1.55] text-subtle">
                          Sent with every message in this campaign. JPEG, PNG, GIF or WebP, up to 8MB.
                        </p>
                        {c.platform === "tiktok" && (
                          <p className="mt-1.5 text-[11.5px] leading-[1.5] text-warn">
                            TikTok&apos;s web composer sends text only — a campaign with an image will fail rather than
                            send without it.
                          </p>
                        )}
                      </>
                    )}
                    <RailLink icon={Plus} onClick={() => imageRef.current?.click()}>
                      {c.has_attachment ? "Replace image" : "Add image"}
                    </RailLink>
                  </CardBody>
                )}
              </Card>
            )}

            {/* ---- recent activity ---- */}
            <Card>
              {railHead("audit", "Recent activity", "Newest first", [
                { label: "Refresh now", icon: RefreshCw, onClick: () => void loadDetail() },
                { label: "Export as CSV", icon: Download, onClick: handleExport },
              ])}
              {!shut.audit && (
                <CardBody className="pt-2">
                  {detail.audit.length === 0 ? (
                    <p className="py-1 text-[12.5px] leading-normal text-subtle">Nothing yet.</p>
                  ) : (
                    detail.audit.slice(0, 6).map((a) => (
                      <div key={a.id} className="flex items-start gap-2.5 border-b border-line-2 py-[9px] last:border-b-0">
                        <span className="mt-[5px] h-1.5 w-1.5 flex-none rounded-full bg-chart-1" />
                        <span className="flex min-w-0 flex-col gap-px">
                          <span className="text-[12.5px] font-semibold leading-normal text-foreground">
                            {a.action.replace(/\./g, " · ").replace(/_/g, " ")}
                          </span>
                          {a.detail && <span className="truncate text-[11px] leading-normal text-subtle">{a.detail}</span>}
                        </span>
                        <span className="ml-auto whitespace-nowrap text-[11px] leading-normal text-subtle">
                          {when(a.created_at)}
                        </span>
                      </div>
                    ))
                  )}
                </CardBody>
              )}
            </Card>

            {/* ---- limits ---- */}
            <Card>
              {railHead("limits", "Limits", `Driver: ${detail.driver}`, [
                { label: "Refresh now", icon: RefreshCw, onClick: () => void loadDetail() },
              ])}
              {!shut.limits && (
                <CardBody className="pt-2">
                  <KV label="Max jobs">{n(detail.limits.max_jobs)}</KV>
                  <KV label="Per account">{n(detail.limits.max_jobs_per_account)}</KV>
                  <KV label="Retry limit">{detail.limits.retry_limit}</KV>
                  <KV label="Workers">{detail.workers_enabled ? "Enabled" : "Off"}</KV>
                  {watch?.sender_running && (
                    <KV label="This machine">{watch.sender_busy ? "Sending…" : "Auto-sending"}</KV>
                  )}
                </CardBody>
              )}
            </Card>
          </>
        }
      />

      <ExportDialog
        open={showExport}
        onClose={() => setShowExport(false)}
        campaignId={id}
        platform={c.platform}
        counts={counts}
      />
      <ImportDialog
        open={showImport}
        onClose={() => setShowImport(false)}
        campaignId={id}
        platform={c.platform}
        onImported={() => {
          void loadDetail();
          void loadTargets();
        }}
      />

      <LeadFinderDialog
        open={showFind}
        onClose={() => setShowFind(false)}
        campaignId={id}
        platform={c.platform}
        onImported={() => {
          setShowFind(false);
          void loadDetail();
          void loadTargets();
        }}
      />

      <MessageSetupDialog
        open={showMessage}
        onClose={() => setShowMessage(false)}
        campaignId={id}
        template={c.message_template ?? ""}
        locked={locked}
        onSaved={loadDetail}
      />

      <CommentSetupDialog
        open={showComments}
        onClose={() => setShowComments(false)}
        campaignId={id}
        videoUrl={c.target_url ?? ""}
        count={c.comment_count ?? 0}
        lines={c.comment_variations ?? []}
        locked={locked}
        onSaved={loadDetail}
      />

      <ConfirmDialog
        open={confirmDelete}
        onClose={() => setConfirmDelete(false)}
        onConfirm={async () => {
          setDeleting(true);
          try {
            await deleteOutreachCampaign(id);
            toast.success("Campaign deleted");
            window.location.href = "/outreach";
          } catch (e) {
            toast.error(apiErrorMessage(e, "Failed to delete"));
            setDeleting(false);
          }
        }}
        title="Delete campaign?"
        confirmLabel="Delete campaign"
        confirmText={c.name}
        busy={deleting}
        body={
          <>
            <b className="font-bold text-foreground">“{c.name}”</b> is removed for good, along with everything it
            produced. This cannot be undone.
          </>
        }
        bullets={[
          `${n(total)} imported targets, including the ${n(sent)} already delivered`,
          "Every job, result and error message from its runs",
          "Its entry in the audit log",
        ]}
      />
    </div>
  );
}
