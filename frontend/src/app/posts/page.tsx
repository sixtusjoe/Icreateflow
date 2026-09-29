"use client";

/** The posts library.
 *
 *  A post is a stack of slides for one brand on one day, in one of four
 *  states. The run of dates is the spine and the state is what the eye
 *  should catch.
 *
 *  `post_number` restarts on each date, so two posts on different days are
 *  both "#1" and only the date tells them apart. Every row carries its date
 *  for that reason — the old page printed the name alone and left two rows
 *  looking identical.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import {
  ArrowRight,
  Clock,
  Copy,
  Download,
  Eye,
  EyeOff,
  FileText,
  Info,
  Plus,
  RefreshCw,
  Search,
  Trash2,
} from "lucide-react";
import {
  deletePost,
  downloadFile,
  duplicatePost,
  getBrands,
  getPosts,
  schedulePost,
  unschedulePost,
} from "@/lib/api";
import {
  Card,
  CardBody,
  CardHead,
  Chip,
  ChipCount,
  DotsMenu,
  Empty,
  FigureLine,
  FigureStrong,
  Minis,
  Note,
  PageActions,
  PageHead,
  PageTitle,
  PrimaryButton,
  SelectChip,
  Skeleton,
  Tabs,
  Tag,
  TwoCol,
  n,
  type Tone,
} from "@/components/kit";
import { ConfirmDialog, Dialog, DialogBody, DialogFoot, DialogHead, Field, GhostButton, Hint, Input } from "@/components/kit/dialog";
import { apiErrorMessage } from "@/components/kit/format";

type Post = {
  id: number;
  brand_id: number;
  brand_name?: string;
  post_number: number;
  date: string;
  scheduled_time?: string | null;
  status: string;
  slides?: unknown[];
};

type Brand = { id: number; name: string };

const STATES = ["draft", "scheduled", "posted", "failed"] as const;

/** `generating` and `posting` are moments, not resting states — they read as
 *  scheduled here rather than inventing two more tabs for a few seconds. */
const bucket = (s: string) => (s === "generating" || s === "posting" ? "scheduled" : s);

const TONE: Record<string, Tone> = {
  draft: "draft",
  scheduled: "live",
  posted: "done",
  failed: "stop",
};

const MONTH = new Intl.DateTimeFormat(undefined, { month: "long", year: "numeric" });
/** Day before month — "13 Apr". The locale default puts the month first,
 *  and "Apr 13" beside "Apr 14" reads as a pair of codes rather than dates. */
const DAY = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short" });
const asDate = (iso: string) => new Date(`${iso}T00:00:00`);

const WORD = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven"];

/** "five months late" — how overdue the queue is, in the words a person uses.
 *  A date alone does not read as a problem; the phrase after it does. */
function lateBy(when: Date, now: Date) {
  const days = Math.floor((now.getTime() - when.getTime()) / 86400000);
  if (days < 1) return "";
  if (days < 14) return `${WORD[days] ?? days} day${days === 1 ? "" : "s"} late`;
  const months = Math.floor(days / 30);
  if (months < 1) return `${Math.floor(days / 7)} weeks late`;
  return `${WORD[months] ?? months} month${months === 1 ? "" : "s"} late`;
}

export default function PostsPage() {
  const [posts, setPosts] = useState<Post[] | null>(null);
  const [brands, setBrands] = useState<Brand[]>([]);
  const [brand, setBrand] = useState("all");
  const [state, setState] = useState("all");
  const [query, setQuery] = useState("");
  const [order, setOrder] = useState("newest");
  const [toDelete, setToDelete] = useState<Post | null>(null);
  const [toUnschedule, setToUnschedule] = useState<Post | null>(null);
  const [toSchedule, setToSchedule] = useState<Post | null>(null);
  const [busy, setBusy] = useState(false);
  const [now] = useState(() => new Date());
  // Hiding a card is a "not now", not a setting — it comes back on reload,
  // so nothing can be lost behind a menu the operator has forgotten about.
  const [hidden, setHidden] = useState<Record<string, boolean>>({});

  const load = useCallback(async () => {
    try {
      setPosts(await getPosts(brand !== "all" ? { brand_id: Number(brand) } : undefined));
    } catch (e) {
      toast.error(apiErrorMessage(e, "Could not load your posts"));
      setPosts([]);
    }
  }, [brand]);

  useEffect(() => {
    load();
  }, [load]);
  useEffect(() => {
    getBrands().then(setBrands).catch(() => {});
  }, []);

  const list = useMemo(() => posts ?? [], [posts]);
  const counts = useMemo(
    () => Object.fromEntries(STATES.map((s) => [s, list.filter((p) => bucket(p.status) === s).length])) as Record<
      (typeof STATES)[number],
      number
    >,
    [list],
  );
  const slideTotal = list.reduce((a, p) => a + (p.slides?.length ?? 0), 0);

  // The soonest thing still queued, and whether its slot has already passed.
  const next = useMemo(() => {
    const queued = list
      .filter((p) => bucket(p.status) === "scheduled" && p.scheduled_time)
      .sort((a, b) =>
        `${a.date}T${a.scheduled_time}`.localeCompare(`${b.date}T${b.scheduled_time}`),
      );
    return queued[0] ?? null;
  }, [list]);
  const nextLate = next ? asDate(next.date) < new Date(now.toDateString()) : false;

  const shown = list.filter((p) => {
    if (state !== "all" && bucket(p.status) !== state) return false;
    if (!query) return true;
    const hay = `${p.brand_name ?? ""} #${p.post_number} ${p.date}`.toLowerCase();
    return hay.includes(query.toLowerCase());
  });

  // Newest first, grouped by the month they were built for.
  const groups = useMemo(() => {
    const m = new Map<string, Post[]>();
    // newest: b before a. oldest: the same comparison, flipped.
    const dir = order === "newest" ? 1 : -1;
    for (const p of [...shown].sort((a, b) => dir * b.date.localeCompare(a.date))) {
      const key = MONTH.format(asDate(p.date));
      if (!m.has(key)) m.set(key, []);
      m.get(key)!.push(p);
    }
    // The rows are already in order, so the months fall out in order too.
    return [...m.entries()];
  }, [shown, order]);

  const exportCsv = () => {
    const head = ["Brand", "Post", "Date", "Time", "Slides", "State"];
    const cell = (v: string) => (/[",\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v);
    const body = list.map((p) =>
      [
        p.brand_name ?? "",
        `#${p.post_number}`,
        p.date,
        (p.scheduled_time || "").slice(0, 5),
        String(p.slides?.length ?? 0),
        bucket(p.status),
      ]
        .map(cell)
        .join(","),
    );
    const url = URL.createObjectURL(
      new Blob([[head.join(","), ...body].join("\n")], { type: "text/csv;charset=utf-8" }),
    );
    const a = document.createElement("a");
    a.href = url;
    a.download = `posts-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const duplicate = async (p: Post) => {
    try {
      const copy = await duplicatePost(p.id);
      toast.success("Duplicated as a draft");
      load();
      if (copy?.id) window.location.href = `/posts/new?edit=${copy.id}`;
    } catch (e) {
      toast.error(apiErrorMessage(e, "Could not duplicate that post"));
    }
  };

  const act = async (fn: () => Promise<unknown>, done: string, fail: string) => {
    setBusy(true);
    try {
      await fn();
      toast.success(done);
      setToDelete(null);
      setToUnschedule(null);
      setToSchedule(null);
      load();
    } catch (e) {
      toast.error(apiErrorMessage(e, fail));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <PageHead>
        <PageTitle
          title="Posts"
          sub="Every post you have built, newest first. A post is a stack of slides for one brand on one day."
        />
        <PageActions>
          <Chip href="/brands" icon={FileText}>
            Brands
            <ChipCount>{brands.length}</ChipCount>
          </Chip>
          <SelectChip
            label="Brand"
            value={brand}
            onChange={setBrand}
            options={[{ key: "all", label: "All brands" }, ...brands.map((b) => ({ key: String(b.id), label: b.name }))]}
          />
          <PrimaryButton icon={Plus} onClick={() => (window.location.href = "/posts/new")}>
            New Post
          </PrimaryButton>
        </PageActions>
      </PageHead>

      {posts === null ? (
        <div className="flex flex-col gap-4">
          <Skeleton className="h-[220px]" />
          <Skeleton className="h-[240px]" />
        </div>
      ) : list.length === 0 ? (
        <Card>
          <Empty
            icon={FileText}
            title="No posts yet"
            action={
              <PrimaryButton icon={Plus} onClick={() => (window.location.href = "/posts/new")}>
                Build your first post
              </PrimaryButton>
            }
          >
            Import a TikTok photo post or upload your own slides, and it lands here.
          </Empty>
        </Card>
      ) : (
        <div className="flex flex-col gap-4">
          <TwoCol
            main={
              hidden.library ? null : (
              // `flex-1` on both cards of this row, so whichever has less in
              // it grows to the other rather than leaving a ragged edge.
              <Card className="flex flex-1 flex-col">
                <CardHead
                  title="Your library"
                  sub={`Everything built so far, across ${brands.length} brand${brands.length === 1 ? "" : "s"}`}
                  right={
                    <DotsMenu
                      label="Library options"
                      items={[
                        { icon: RefreshCw, label: "Refresh", onClick: load },
                        { icon: Download, label: "Export as CSV", onClick: exportCsv },
                        "-",
                        { icon: EyeOff, label: "Hide this card", onClick: () => setHidden((h) => ({ ...h, library: true })) },
                      ]}
                    />
                  }
                />
                <CardBody className="flex flex-1 flex-col">
                  <FigureLine value={n(list.length)}>
                    post{list.length === 1 ? "" : "s"} · <FigureStrong>{n(slideTotal)}</FigureStrong> slides between them
                  </FigureLine>
                  <Minis
                    cells={[
                      { label: "DRAFT", value: counts.draft },
                      { label: "SCHEDULED", value: counts.scheduled },
                      { label: "POSTED", value: counts.posted },
                      { label: "FAILED", value: counts.failed, tone: counts.failed ? "bad" : undefined },
                      { label: "SLIDES", value: slideTotal },
                    ]}
                  />
                  <p className="relative mt-auto pt-4 pl-[19px] text-[11px] leading-[1.5] text-subtle">
                    <Info className="absolute left-0 top-[18px] h-3 w-3" />
                    A draft has no time on it yet. Scheduling one hands it to the poster; nothing leaves your account
                    until then.
                  </p>
                </CardBody>
              </Card>
              )
            }
            rail={
              hidden.next ? null : (
              <Card className="flex flex-1 flex-col">
                <CardHead
                  title="Next out the door"
                  sub="The soonest scheduled post"
                  right={
                    <DotsMenu
                      label="Next post options"
                      items={[
                        { icon: Clock, label: "Open the schedule", href: "/schedule" },
                        "-",
                        { icon: EyeOff, label: "Hide this card", onClick: () => setHidden((h) => ({ ...h, next: true })) },
                      ]}
                    />
                  }
                />
                <CardBody className="flex flex-1 flex-col pt-2.5">
                  {!next ? (
                    <p className="text-[12.5px] leading-[1.5] text-subtle">Nothing is scheduled.</p>
                  ) : (
                    <div className="flex items-center gap-3">
                      <span className="grid h-[42px] w-[42px] flex-none place-items-center rounded-[12px] border border-border bg-secondary text-[13px] font-bold tabular-nums text-subtle">
                        {next.slides?.length ?? 0}
                      </span>
                      <div className="min-w-0">
                        <div className="text-[13.5px] font-bold leading-normal">
                          {next.brand_name} #{next.post_number}
                        </div>
                        <div className={`text-[11px] leading-normal ${nextLate ? "text-bad" : "text-subtle"}`}>
                          {next.slides?.length ?? 0} slides · {nextLate ? "was due" : "due"} {DAY.format(asDate(next.date))}{" "}
                          at {(next.scheduled_time || "").slice(0, 5)}
                          {nextLate && ` — ${lateBy(asDate(next.date), now)}`}
                        </div>
                      </div>
                    </div>
                  )}
                  {/* On the floor of the card, so the height this row
                      shares reads as a card that is full rather than one
                      with a hole in it. */}
                  <div className="mt-auto pt-3.5">
                    <Chip href="/schedule" icon={ArrowRight} className="w-full justify-center">
                      Open the schedule
                    </Chip>
                  </div>
                </CardBody>
              </Card>
              )
            }
          />

          <div className="flex flex-wrap items-center gap-2">
            <Tabs
              value={state}
              onChange={setState}
              items={[
                { key: "all", label: "All", count: list.length },
                { key: "draft", label: "Drafts", count: counts.draft },
                { key: "scheduled", label: "Scheduled", count: counts.scheduled },
                { key: "posted", label: "Posted", count: counts.posted },
                { key: "failed", label: "Failed", count: counts.failed },
              ]}
            />
            <label className="ml-auto flex items-center gap-2 rounded-[11px] border border-border bg-card px-3 py-2 shadow-card">
              <Search className="h-[13px] w-[13px] text-subtle" />
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search posts"
                aria-label="Search posts"
                className="w-[140px] bg-transparent text-[12.5px] leading-normal outline-none placeholder:text-subtle"
              />
            </label>
            <SelectChip
              label="Order"
              value={order}
              onChange={setOrder}
              options={[
                { key: "newest", label: "Newest first" },
                { key: "oldest", label: "Oldest first" },
              ]}
            />
          </div>

          <Card>
            {groups.length === 0 ? (
              <Empty icon={FileText} title="Nothing in this state">
                Change the filter to see the rest.
              </Empty>
            ) : (
              <div className="px-1.5 pb-2 pt-4">
                <div className="flex items-center gap-3 border-b border-border px-3.5 pb-2.5 text-[10.5px] font-bold uppercase leading-normal tracking-[0.08em] text-subtle">
                  <span className="flex-1">Post</span>
                  <span className="hidden w-[132px] flex-none sm:block">Brand</span>
                  <span className="hidden w-[118px] flex-none sm:block">Time</span>
                  <span className="w-[86px] flex-none">State</span>
                  <span className="w-[26px] flex-none" />
                </div>
                {groups.map(([month, ps]) => (
                  <div key={month}>
                    <div className="flex items-baseline gap-2 border-b border-border px-3.5 pb-1.5 pt-4">
                      <span className="text-[10.5px] font-bold uppercase leading-normal tracking-[0.08em] text-subtle">
                        {month}
                      </span>
                      <em className="text-[10.5px] font-bold not-italic leading-normal tabular-nums text-subtle opacity-60">
                        {ps.length}
                      </em>
                    </div>
                    {ps.map((p) => (
                      <PostRow
                        key={p.id}
                        post={p}
                        onDelete={() => setToDelete(p)}
                        onUnschedule={() => setToUnschedule(p)}
                        onSchedule={() => setToSchedule(p)}
                        onDuplicate={() => duplicate(p)}
                      />
                    ))}
                  </div>
                ))}
              </div>
            )}
          </Card>

          <Note>
            A draft has no time on it yet. Scheduling one hands it to the poster — nothing leaves your account before
            then.
          </Note>
        </div>
      )}

      <ConfirmDialog
        open={!!toDelete}
        onClose={() => setToDelete(null)}
        onConfirm={() => act(() => deletePost(toDelete!.id), "Post deleted", "Could not delete that post")}
        busy={busy}
        title="Delete post?"
        body="Everything this post is made of goes with it. This cannot be undone."
        bullets={[
          `Its ${toDelete?.slides?.length ?? 0} slides, and every account's versions of them`,
          "The rendered video, if one was built",
          ...(toDelete && bucket(toDelete.status) === "scheduled"
            ? [`Its place in the schedule — nothing goes out at ${(toDelete.scheduled_time || "").slice(0, 5)}`]
            : []),
        ]}
        keeps={[
          "The brand, its fonts and its saved settings",
          "Every other post built from that brand",
          "Anything already posted — that stays up on the platforms",
        ]}
        confirmLabel="Delete post"
      />

      <ConfirmDialog
        open={!!toUnschedule}
        onClose={() => setToUnschedule(null)}
        onConfirm={() =>
          act(() => unschedulePost(toUnschedule!.id), "Taken off the schedule", "Could not unschedule that post")
        }
        busy={busy}
        title="Take it off the schedule?"
        body={`${toUnschedule?.brand_name ?? "The post"} #${toUnschedule?.post_number ?? ""} goes back to being a draft with no time on it.`}
        bullets={[
          `Its ${(toUnschedule?.scheduled_time || "").slice(0, 5)} slot on ${toUnschedule ? DAY.format(asDate(toUnschedule.date)) : "that day"}`,
        ]}
        keeps={["The slides, and anything already built from them", "The caption and the music it was given"]}
        confirmLabel="Take it off"
      />

      <ScheduleDialog
        post={toSchedule}
        busy={busy}
        onClose={() => setToSchedule(null)}
        onSave={(time) =>
          act(
            () => schedulePost(toSchedule!.id, { scheduled_time: time }),
            "Scheduled",
            "Could not schedule that post",
          )
        }
      />
    </>
  );
}

function PostRow({
  post,
  onDelete,
  onUnschedule,
  onSchedule,
  onDuplicate,
}: {
  post: Post;
  onDelete: () => void;
  onUnschedule: () => void;
  onSchedule: () => void;
  onDuplicate: () => void;
}) {
  const slides = post.slides?.length ?? 0;
  const st = bucket(post.status);
  const label = st.charAt(0).toUpperCase() + st.slice(1);

  const download = async () => {
    try {
      await downloadFile(post.id);
    } catch (e) {
      toast.error(apiErrorMessage(e, "Nothing to download yet — build the post first"));
    }
  };

  return (
    <div className="flex flex-wrap items-center gap-3 border-b border-line-2 px-3.5 py-[13px] last:border-b-0 hover:bg-secondary">
      <span className="grid h-[31px] w-[31px] flex-none place-items-center rounded-[9px] border border-border bg-secondary text-[11px] font-bold tabular-nums text-subtle">
        {slides}
      </span>
      <div className="min-w-0 flex-1">
        <div className="text-[13px] font-semibold leading-normal">
          {post.brand_name} #{post.post_number}
        </div>
        {/* A failed post is the only one that owes an explanation, so it is
            the only one whose second line is not just a count and a date. */}
        <div className={`mt-px text-[11px] leading-normal ${st === "failed" ? "text-bad" : "text-subtle"}`}>
          {st === "failed"
            ? `${slides} slides · ${DAY.format(asDate(post.date))} — it did not go out; open it to see which account`
            : `${slides} slide${slides === 1 ? "" : "s"} · ${DAY.format(asDate(post.date))}`}
        </div>
      </div>
      <span className="hidden w-[132px] flex-none truncate text-xs font-semibold leading-normal text-muted-foreground sm:block">
        {post.brand_name}
      </span>
      <span className="hidden w-[118px] flex-none text-xs leading-normal tabular-nums text-muted-foreground sm:block">
        {post.scheduled_time ? (
          <span className="inline-flex items-center gap-1.5">
            <Clock className="h-[13px] w-[13px] text-subtle" />
            {(post.scheduled_time || "").slice(0, 5)}
          </span>
        ) : (
          <span className="text-subtle">—</span>
        )}
      </span>
      <span className="w-[86px] flex-none">
        <Tag tone={TONE[st] ?? "draft"}>{label}</Tag>
      </span>
      <DotsMenu
        label={`${post.brand_name} #${post.post_number} actions`}
        items={[
          { icon: Eye, label: "Open in the editor", href: `/posts/new?edit=${post.id}`, kbd: "↵" },
          { icon: Download, label: "Download the video", onClick: download },
          ...(st === "scheduled" ? [{ icon: Clock, label: "Move back to draft", onClick: onUnschedule }] : []),
          ...(st === "draft" ? [{ icon: Clock, label: "Schedule it", onClick: onSchedule }] : []),
          ...(st === "failed"
            ? [{ icon: RefreshCw, label: "Try again", href: `/posts/new?edit=${post.id}` }]
            : []),
          "-",
          { icon: Copy, label: "Duplicate", onClick: onDuplicate },
          { icon: Trash2, label: "Delete post", danger: true, onClick: onDelete },
        ]}
      />
    </div>
  );
}

/** Giving a draft a time is the whole of "schedule it" — the date was
 *  fixed when the post was built, so asking for it again would only offer
 *  the operator a way to contradict themselves. */
function ScheduleDialog({
  post,
  busy,
  onClose,
  onSave,
}: {
  post: Post | null;
  busy?: boolean;
  onClose: () => void;
  onSave: (time: string) => void;
}) {
  const [time, setTime] = useState("09:00");
  const key = post?.id ?? 0;
  const seen = useRef(key);
  if (seen.current !== key) {
    seen.current = key;
    setTime((post?.scheduled_time || "09:00").slice(0, 5));
  }

  if (!post) return null;

  return (
    <Dialog open onClose={onClose} label="Schedule this post" size="sm">
      <DialogHead
        title="Schedule it"
        sub={`${post.brand_name} #${post.post_number} goes out on ${DAY.format(asDate(post.date))}, at the time you set here.`}
        onClose={onClose}
      />
      <DialogBody>
        <Field label="Time of day">
          <Input type="time" value={time} onChange={(e) => setTime(e.target.value)} className="w-[140px]" />
        </Field>
        <Hint>
          The poster checks every minute. Nothing leaves your account before {time || "the time you set"} on{" "}
          {DAY.format(asDate(post.date))}.
        </Hint>
      </DialogBody>
      <DialogFoot>
        <GhostButton onClick={onClose} disabled={busy}>
          Cancel
        </GhostButton>
        <PrimaryButton icon={Clock} onClick={() => onSave(time)} disabled={busy || !time}>
          {busy ? "Saving…" : "Schedule it"}
        </PrimaryButton>
      </DialogFoot>
    </Dialog>
  );
}
