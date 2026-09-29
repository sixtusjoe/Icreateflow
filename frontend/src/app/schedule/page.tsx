"use client";

/** The schedule.
 *
 *  `GET /api/schedule` returns posts in status scheduled, generating or
 *  posting — nothing else. Drafts are invisible there, which is how a post
 *  with no time on it gets forgotten, so this page fetches them separately
 *  and lists them rather than pretending they do not exist.
 *
 *  The overdue banner is the point of the page. `dispatch_brand_posts_once`
 *  runs every 60 seconds and skips silently when `oauth_redirect_base` is
 *  not configured: it flips the post to 'posting', finds no public base,
 *  sets it back to 'scheduled' and moves on, with no log and no error. A
 *  post can sit like that for months looking perfectly fine. Anything whose
 *  slot has passed and is still queued says so here.
 *
 *  It does not name the setting or link to Admin. This is a user page; that
 *  setting is site config, which only an admin can read or write, and a
 *  banner that sends the reader to a page refusing them is a dead end
 *  dressed as an instruction. It is also why the banner no longer reads
 *  site config to confirm the cause — a user page should not be calling an
 *  admin endpoint at all. Every other way the dispatcher can fail moves the
 *  post off 'scheduled', so "still queued and overdue" is very nearly proof
 *  on its own; the copy says "nearly always" rather than claiming more than
 *  it checked. An admin sees the confirmed version, with the fix attached,
 *  under "Needs an admin" on the admin Overview.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { toast } from "sonner";
import {
  CalendarClock,
  Clock,
  Eye,
  FileText,
  Plus,
  RefreshCw,
  Send,
  Settings as SettingsIcon,
  Trash2,
  Undo2,
  Info,
} from "lucide-react";
import { getBrands, getPosts, getSchedule, unschedulePost } from "@/lib/api";
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
  Tag,
  TwoCol,
  n,
} from "@/components/kit";
import { ConfirmDialog } from "@/components/kit/dialog";
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

type Brand = { id: number; name: string; timezone?: string; default_post_times?: string };

/** Day before month, and no comma after the weekday — "Monday 13 April".
 *  The locale default reads as a filing reference, not a day. */
const DAY = new Intl.DateTimeFormat("en-GB", { weekday: "long", day: "numeric", month: "long" });
const SHORT = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short" });
const WORDS = ["no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"];
const onDay = (iso: string) => SHORT.format(new Date(`${iso}T00:00:00`));

/** A post's slot as a Date, read in the browser's zone. Close enough to sort
 *  and to say "overdue" — the dispatcher does the real timezone maths. */
const slotOf = (p: Post) => new Date(`${p.date}T${(p.scheduled_time || "00:00").slice(0, 5)}:00`);

function lateness(d: Date, now: Date) {
  const mins = Math.floor((now.getTime() - d.getTime()) / 60000);
  if (mins < 0) return null;
  if (mins < 60) return `${mins || 1} min late`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours} hour${hours > 1 ? "s" : ""} late`;
  const days = Math.floor(hours / 24);
  if (days < 60) return `${days} day${days > 1 ? "s" : ""} late`;
  return `${Math.floor(days / 30)} months late`;
}

export default function SchedulePage() {
  const [queued, setQueued] = useState<Post[] | null>(null);
  const [drafts, setDrafts] = useState<Post[]>([]);
  const [slideCounts, setSlideCounts] = useState<Record<number, number>>({});
  const [postTotal, setPostTotal] = useState(0);
  const [reach, setReach] = useState<{ accounts: number; platforms: string[] }>({ accounts: 0, platforms: [] });
  const [brands, setBrands] = useState<Brand[]>([]);
  const [brand, setBrand] = useState("all");
  const [toUnschedule, setToUnschedule] = useState<Post | null>(null);
  const [busy, setBusy] = useState(false);
  // Fixed at first render: a `new Date()` in the body would make every row
  // recompute its lateness on every keystroke elsewhere on the page.
  const [now] = useState(() => new Date());

  const load = useCallback(async () => {
    const id = brand !== "all" ? Number(brand) : undefined;
    try {
      const [sched, all] = await Promise.all([getSchedule(id), getPosts(id ? { brand_id: id } : undefined)]);
      setQueued(sched);
      setDrafts((all as Post[]).filter((p) => p.status === "draft"));
      setSlideCounts(Object.fromEntries((all as Post[]).map((p) => [p.id, p.slides?.length ?? 0])));
      setPostTotal((all as Post[]).length);
    } catch (e) {
      toast.error(apiErrorMessage(e, "Could not load the schedule"));
      setQueued([]);
    }
  }, [brand]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    getBrands()
      .then((bs: (Brand & { accounts?: Record<string, unknown>[] })[]) => {
        setBrands(bs);
        const accounts = bs.flatMap((b) => b.accounts ?? []);
        const platforms = [...new Set(
          accounts.flatMap((a) =>
            (["instagram", "youtube", "tiktok", "facebook"] as const).filter((p) => a[`${p}_handle`]),
          ),
        )];
        setReach({ accounts: accounts.length, platforms });
      })
      .catch(() => {});
  }, []);

  const list = useMemo(() => queued ?? [], [queued]);
  const overdue = list.filter((p) => slotOf(p) < now);
  // The banner is about a stuck loop, and "since when" is the fact that
  // turns it from a warning into something with a size.
  const oldest = overdue.length
    ? overdue.map(slotOf).reduce((a, b) => (a < b ? a : b))
    : null;

  const byDate = useMemo(() => {
    const m = new Map<string, Post[]>();
    for (const p of [...list].sort((a, b) => slotOf(a).getTime() - slotOf(b).getTime())) {
      if (!m.has(p.date)) m.set(p.date, []);
      m.get(p.date)!.push(p);
    }
    return [...m.entries()];
  }, [list]);

  const todayStr = now.toISOString().slice(0, 10);
  const weekEnd = new Date(now.getTime() + 7 * 86400000).toISOString().slice(0, 10);
  const dueToday = list.filter((p) => p.date === todayStr).length;
  const dueWeek = list.filter((p) => p.date > todayStr && p.date <= weekEnd).length;

  const firstBrand = brands.find((b) => (brand === "all" ? true : b.id === Number(brand)));
  const times = (firstBrand?.default_post_times || "").split(",").map((s) => s.trim()).filter(Boolean);
  const taken = new Set(list.map((p) => (p.scheduled_time || "").slice(0, 5)));

  const doUnschedule = async () => {
    if (!toUnschedule) return;
    setBusy(true);
    try {
      await unschedulePost(toUnschedule.id);
      toast.success("Taken off the schedule");
      setToUnschedule(null);
      load();
    } catch (e) {
      toast.error(apiErrorMessage(e, "Could not unschedule that post"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <PageHead>
        <PageTitle title="Schedule" sub="Everything with a time on it, and everything still waiting for one." />
        <PageActions>
          <SelectChip
            label="Brand"
            value={brand}
            onChange={setBrand}
            options={[{ key: "all", label: "All brands" }, ...brands.map((b) => ({ key: String(b.id), label: b.name }))]}
          />
          <Chip href="/posts" icon={FileText}>
            Posts
            <ChipCount>{postTotal}</ChipCount>
          </Chip>
          <PrimaryButton icon={Plus} onClick={() => (window.location.href = "/posts/new")}>
            New Post
          </PrimaryButton>
        </PageActions>
      </PageHead>

      {/* The banner stays — a post that is past its time and has not gone
          out is the thing this page exists to show. What it no longer does
          is send the reader to Admin: that page refuses most of them, and
          the setting behind this is not theirs to change. It names the
          likely cause without claiming to have checked it, because reading
          site config is admin-only and a user page should not be asking. */}
      {overdue.length > 0 && (
        <div className="flex items-start gap-3 rounded-[16px] border border-[rgba(235,104,52,0.32)] bg-[rgba(235,104,52,0.08)] px-4 py-3.5">
          <span className="grid h-[31px] w-[31px] flex-none place-items-center rounded-[10px] bg-[rgba(235,104,52,0.15)] text-[#B25E09] dark:text-[#F2A25C]">
            <Info className="h-[15px] w-[15px]" />
          </span>
          <div className="min-w-0 flex-1">
            <div className="text-[13px] font-bold leading-normal text-[#B25E09] dark:text-[#F2A25C]">
              {overdue.length === 1 ? "A post is past its time" : `${n(overdue.length)} posts are past their time`}
              {" "}and {overdue.length === 1 ? "has" : "have"} not gone out
            </div>
            <div className="mt-0.5 max-w-[78ch] text-[11px] leading-[1.55] text-subtle">
              The scheduler picks {overdue.length === 1 ? "it" : "them"} up every minute and puts{" "}
              {overdue.length === 1 ? "it" : "them"} straight back, writing no log when it does — which is
              why there is nothing to find.
              {oldest ? ` It has been doing that since ${SHORT.format(oldest)}.` : ""} Nearly always this is
              the workspace having no public address set for the video files, which an admin has to fix.
              Ask one; {overdue.length === 1 ? "it" : "they"} will go on the next pass, with nothing to redo
              here.
            </div>
          </div>
        </div>
      )}

      {queued === null ? (
        <div className="flex flex-col gap-4">
          <Skeleton className="h-[200px]" />
          <Skeleton className="h-[160px]" />
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          <TwoCol
            main={
              // Both cards in this row fill it, so the pair ends level.
              <Card className="flex flex-1 flex-col">
                <CardHead
                  title="Waiting to go out"
                  sub="Posts the scheduler is holding"
                  right={
                    <DotsMenu
                      label="Schedule options"
                      items={[{ icon: RefreshCw, label: "Refresh", onClick: load }]}
                    />
                  }
                />
                <CardBody className="flex flex-1 flex-col">
                  <FigureLine value={n(list.length)}>
                    post{list.length === 1 ? "" : "s"} scheduled
                    {overdue.length > 0 && (
                      <>
                        {" · "}
                        <FigureStrong>{n(overdue.length)}</FigureStrong> of them overdue
                      </>
                    )}
                  </FigureLine>
                  <Minis
                    cells={[
                      { label: "TODAY", value: dueToday },
                      { label: "THIS WEEK", value: dueWeek },
                      { label: "OVERDUE", value: overdue.length, tone: overdue.length ? "bad" : undefined },
                      { label: "NO TIME YET", value: drafts.length },
                    ]}
                  />
                  <p className="relative mt-auto pt-4 pl-[19px] text-[11px] leading-[1.5] text-subtle">
                    <Info className="absolute left-0 top-[18px] h-3 w-3" />
                    A post only appears here once it has a date and a time. Drafts are in their own list below so they
                    are not lost.
                  </p>
                </CardBody>
              </Card>
            }
            rail={
              <Card className="flex flex-1 flex-col">
                <CardHead
                  title={firstBrand ? `When ${firstBrand.name} posts` : "Default times"}
                  sub={
                    firstBrand?.timezone
                      ? `Its ${WORDS[times.length] ?? times.length} default times, in ${firstBrand.timezone}`
                      : undefined
                  }
                  right={
                    <DotsMenu
                      label="Default times options"
                      items={[{ icon: SettingsIcon, label: "Change them on Brands", href: "/brands" }]}
                    />
                  }
                />
                <CardBody className="flex flex-1 flex-col pt-3">
                  {times.length === 0 ? (
                    <p className="text-[12.5px] leading-[1.5] text-subtle">This brand has no default times set.</p>
                  ) : (
                    <div className="grid grid-cols-3 gap-2.5">
                      {times.map((t) => {
                        const on = taken.has(t);
                        return (
                          <div
                            key={t}
                            className={`rounded-[12px] border px-2 py-3 text-center text-sm font-bold tabular-nums leading-normal ${
                              on ? "border-primary bg-primary text-primary-foreground" : "border-border bg-secondary"
                            }`}
                          >
                            {t}
                            <span
                              className={`mt-[3px] block text-[10px] font-semibold uppercase leading-normal tracking-[0.04em] ${
                                on ? "opacity-60" : "text-subtle"
                              }`}
                            >
                              {on ? "taken" : "free"}
                            </span>
                          </div>
                        );
                      })}
                    </div>
                  )}
                  <p className="relative mt-auto pt-3.5 pl-[18px] text-[11px] leading-[1.5] text-subtle">
                    <Info className="absolute left-0 top-[16px] h-3 w-3" />
                    These are only what a new post is offered. A post can carry any time you give it.
                  </p>
                </CardBody>
              </Card>
            }
          />

          <SectionHead
            title="Scheduled"
            sub="Soonest first. Times are in each brand's own timezone."
          />

          {byDate.length === 0 ? (
            <Card>
              <Empty
                icon={CalendarClock}
                title="Nothing is queued"
                action={
                  <PrimaryButton icon={Plus} onClick={() => (window.location.href = "/posts/new")}>
                    New Post
                  </PrimaryButton>
                }
              >
                Give a post a date and a time and it will appear here, soonest first.
              </Empty>
            </Card>
          ) : (
            byDate.map(([date, posts]) => {
              const late = lateness(new Date(`${date}T00:00:00`), now);
              return (
                <div key={date}>
                  <div className="flex items-baseline gap-2.5 px-0.5 pb-2">
                    <span className="text-xs font-bold leading-normal tracking-[0.01em]">
                      {DAY.format(new Date(`${date}T00:00:00`))}
                    </span>
                    {late && <em className="text-[11px] not-italic leading-normal text-subtle">{late}</em>}
                  </div>
                  <Card className="py-1">
                    {posts.map((p) => (
                      <QueuedRow
                        key={p.id}
                        post={p}
                        slides={slideCounts[p.id] ?? 0}
                        reach={reach}
                        late={lateness(slotOf(p), now)}
                        onUnschedule={() => setToUnschedule(p)}
                      />
                    ))}
                  </Card>
                </div>
              );
            })
          )}

          {drafts.length > 0 && (
            <>
              <SectionHead
                title="No time yet"
                sub="Built, but never scheduled — the schedule endpoint does not return these at all"
              />
              <Card className="py-1">
                {drafts.map((p) => (
                  <DraftRow key={p.id} post={p} slides={slideCounts[p.id] ?? 0} />
                ))}
              </Card>
            </>
          )}

          <Note>
            Posts that have already gone out are not here — this page is only what is still coming. Look on{" "}
            <Link href="/posts" className="text-muted-foreground underline">
              Posts
            </Link>{" "}
            for the rest.
          </Note>
        </div>
      )}

      <ConfirmDialog
        open={!!toUnschedule}
        onClose={() => setToUnschedule(null)}
        onConfirm={doUnschedule}
        busy={busy}
        title="Take it off the schedule?"
        body={`${toUnschedule?.brand_name ?? "The post"} #${toUnschedule?.post_number ?? ""} goes back to being a draft with no time on it.`}
        bullets={[
          `Its ${(toUnschedule?.scheduled_time ?? "").slice(0, 5)} slot on ${toUnschedule ? onDay(toUnschedule.date) : "that day"}`,
          "Nothing else — the slides, the variations and anything already built stay exactly as they are",
        ]}
        confirmLabel="Take it off"
      />
    </>
  );
}

function SectionHead({ title, sub }: { title: string; sub: string }) {
  return (
    <div className="mt-2 px-0.5">
      <div className="text-[14.5px] font-bold leading-normal text-foreground">{title}</div>
      <div className="mt-[3px] text-[11.5px] leading-normal text-subtle">{sub}</div>
    </div>
  );
}

const PLAT_LABEL: Record<string, string> = {
  instagram: "Instagram",
  youtube: "YouTube",
  tiktok: "TikTok",
  facebook: "Facebook",
};

function QueuedRow({
  post,
  slides,
  reach,
  late,
  onUnschedule,
}: {
  post: Post;
  slides: number;
  reach: { accounts: number; platforms: string[] };
  late: string | null;
  onUnschedule: () => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-3 border-b border-line-2 px-[18px] py-[13px] last:border-b-0 hover:bg-secondary">
      <span
        className={`w-[52px] flex-none text-sm font-extrabold tabular-nums leading-normal tracking-[-0.02em] ${
          late ? "text-destructive" : ""
        }`}
      >
        {(post.scheduled_time || "--:--").slice(0, 5)}
      </span>
      <div className="min-w-0 flex-1">
        <div className="text-[13px] font-semibold leading-normal">
          {post.brand_name} #{post.post_number}
        </div>
        <div className="mt-px text-[11px] leading-normal text-subtle">
          {slides ? `${slides} slides` : "no slides yet"}
          {reach.accounts ? ` · ${reach.accounts} accounts` : ""}
          {reach.platforms.length ? ` · ${reach.platforms.map((p) => PLAT_LABEL[p] ?? p).join(", ")}` : ""}
          {post.status === "posting"
            ? " · going out now"
            : post.status === "generating"
              ? " · still building"
              : ""}
        </div>
      </div>
      <Tag tone={late ? "stop" : "live"}>{late ?? "Scheduled"}</Tag>
      <DotsMenu
        label={`${post.brand_name} #${post.post_number} actions`}
        items={[
          { icon: Eye, label: "Open the post", href: `/posts/new?edit=${post.id}` },
          { icon: Clock, label: "Change the time", href: `/posts/new?edit=${post.id}` },
          { icon: Send, label: "Post it now", href: `/posts/new?edit=${post.id}` },
          "-",
          { icon: Undo2, label: "Take it off the schedule", danger: true, onClick: onUnschedule },
        ]}
      />
    </div>
  );
}

function DraftRow({ post, slides }: { post: Post; slides: number }) {
  return (
    <div className="flex flex-wrap items-center gap-3 border-b border-line-2 px-[18px] py-[13px] last:border-b-0 hover:bg-secondary">
      <span className="w-[52px] flex-none text-sm font-semibold tabular-nums leading-normal text-subtle">--:--</span>
      <div className="min-w-0 flex-1">
        <div className="text-[13px] font-semibold leading-normal">
          {post.brand_name} #{post.post_number}
        </div>
        <div className="mt-px text-[11px] leading-normal text-subtle">
          {slides ? `${slides} slides · ` : ""}built for {onDay(post.date)}, never given a time
        </div>
      </div>
      <Chip href={`/posts/new?edit=${post.id}`} icon={Clock}>
        Give it a time
      </Chip>
      <DotsMenu
        label={`${post.brand_name} #${post.post_number} actions`}
        items={[
          { icon: Eye, label: "Open the post", href: `/posts/new?edit=${post.id}` },
          "-",
          { icon: Trash2, label: "Delete post", danger: true, href: `/posts` },
        ]}
      />
    </div>
  );
}
