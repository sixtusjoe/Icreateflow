"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { AlertTriangle, ArrowRight, Info, RefreshCw } from "lucide-react";
import { useAuth } from "@/lib/auth";
import {
  Card, CardHead, CardBody, Chip, PageHead, PageTitle, PageActions, SelectChip,
  Note, Tag, TH, TD, MONO, Skeleton, DotsMenu,
} from "@/components/kit";
import { Bars, Funnel, Gauge, Mini, Spark, Stack, TwoLine, num, pc, type Tone } from "@/components/admin/charts";
import { Initial, RolePill, Sub } from "@/components/admin/ui";
import {
  getAdminStats, getUsers, avatarSrc, getAdminErrorLogs, getOAuthApps, getAdminBrands,
  getAdminPosts, getAdminAccounts, getAdminArtists, getOutreachSummary,
  listOutreachAccounts, listOutreachCampaigns,
} from "@/lib/api";

/**
 * Admin — Overview.
 *
 * Every number, percentage and line on this page is read from an endpoint
 * that exists:
 *
 *   /api/admin/stats        counts, the storage split, cpu/mem/disk
 *   /api/admin/error-logs   the newest 200 warnings, their source and day
 *   /api/admin/oauth-apps   whether the public address and the apps are set
 *   /api/outreach/summary   sends by day, target states, the weekday split —
 *                           instance-wide, because the summary scopes to
 *                           NULL for an admin
 *   /api/outreach/accounts  per-account throughput and error counts
 *
 * Two rules the page keeps:
 *
 *  - Every percentage names its denominator on screen. "77.8%" alone is a
 *    number nobody can check; "77.8% — 2,509 of 3,227 attempted" is a claim
 *    with its working shown.
 *  - Where the instance has no data the card says so in words instead of
 *    drawing an empty axis. An axis with no line reads as a system that
 *    stopped, not one that was never used.
 *
 * The one card that breaks the first rule breaks it loudly: payments and
 * subscriptions are marked sample on their face, because no subscriptions
 * table, payment provider or usage log exists anywhere in the backend.
 */

type Row = Record<string, unknown>;
const s = (r: Row, k: string) => (r[k] == null ? "" : String(r[k]));

const PLATFORM_NAME: Record<string, string> = {
  meta: "Meta", instagram: "Instagram", tiktok: "TikTok", youtube: "YouTube",
  x: "X", facebook: "Facebook",
};
const WORDS = ["no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"];
const spell = (k: number) => (k < WORDS.length ? WORDS[k] : num(k));
const plural = (k: number, one: string, many: string) => (k === 1 ? one : many);

/** The sends window. The summary is fetched at 90 days once and sliced, so
 *  changing this costs nothing and the prior period is always available —
 *  which is why 90 is not on the list: comparing it needs 180 days. */
const WINDOWS = [
  { key: "7", label: "Last 7 days" },
  { key: "14", label: "Last 14 days" },
  { key: "30", label: "Last 30 days" },
];

const monthStart = (d: Date, back: number) => {
  const x = new Date(d.getFullYear(), d.getMonth() - back, 1);
  return x;
};

/** How many of a thing existed at the end of each of the last six months.
 *  Cumulative, because the tile shows a count — the line has to end at the
 *  number printed beside it or the two are telling different stories. */
function monthly(rows: Row[], key = "created_at", months = 6): number[] {
  const today = new Date();
  const stamps = rows
    .map((r) => s(r, key).slice(0, 10))
    .filter(Boolean)
    .map((d) => new Date(d + "T00:00:00").getTime());
  const out: number[] = [];
  for (let back = months - 1; back >= 0; back--) {
    const edge = monthStart(today, back - 1).getTime();
    out.push(stamps.filter((t) => t < edge).length);
  }
  return out;
}

const ago = (iso: string | null) => {
  if (!iso) return "never";
  const when = new Date(iso);
  const gap = Math.floor((Date.now() - when.getTime()) / 86_400_000);
  if (gap <= 0) return "today";
  if (gap === 1) return "yesterday";
  if (gap < 31) return `${gap} days ago`;
  return when.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
};

type Summary = {
  targets: Record<string, number>;
  total_targets: number;
  sent: number;
  attempted: number;
  leads: number;
  latest_search: { found: number } | null;
  accounts: Record<string, number>;
  campaigns: Record<string, number>;
  daily_sends: { date: string; count: number }[];
  weekday_sends: Record<string, number>;
};

type Stats = {
  total_users: number; total_brands: number; total_posts: number; total_tracks: number;
  total_artists: number; failed_posts: number; new_users_24h: number; pending_users: number;
  suspended_users: number;
  storage_mb: { uploads: number; output: number; music: number; total: number };
  health: { cpu_percent: number | null; mem_percent: number | null; disk_percent: number | null };
};

type Acct = {
  id: number; name: string; platform: string; status: string; enabled: boolean;
  has_session: boolean; messages_processed: number; consecutive_errors: number;
  purpose?: string; created_at: string;
};

export default function AdminOverviewPage() {
  const { user } = useAuth();
  const router = useRouter();

  const [stats, setStats] = useState<Stats | null>(null);
  const [users, setUsers] = useState<Row[]>([]);
  const [errors, setErrors] = useState<Row[]>([]);
  const [oauth, setOauth] = useState<Row | null>(null);
  const [sum, setSum] = useState<Summary | null>(null);
  const [accts, setAccts] = useState<Acct[]>([]);
  const [camps, setCamps] = useState<Row[]>([]);
  const [brands, setBrands] = useState<Row[]>([]);
  const [posts, setPosts] = useState<Row[]>([]);
  const [postAccts, setPostAccts] = useState<Row[]>([]);
  const [artists, setArtists] = useState<Row[]>([]);
  const [window_, setWindow] = useState("30");
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    // Every call is independent and every failure is survivable — a card
    // with nothing in it is better than a page that refuses to paint.
    const all = [
      getAdminStats().then(setStats),
      getUsers().then(setUsers),
      getAdminErrorLogs({ limit: 200 }).then(setErrors),
      getOAuthApps().then(setOauth),
      getOutreachSummary(90).then(setSum),
      listOutreachAccounts().then(setAccts),
      listOutreachCampaigns().then(setCamps),
      getAdminBrands().then(setBrands),
      getAdminPosts().then(setPosts),
      getAdminAccounts().then(setPostAccts),
      getAdminArtists().then(setArtists),
    ].map((p) => p.catch(() => {}));
    Promise.all(all).finally(() => setBusy(false));
  }, []);

  /** What the Refresh chip does. `load` on its own never touches state
   *  before a request is out, so the first load can run straight from the
   *  effect without a cascading render behind it. */
  const refresh = useCallback(() => { setBusy(true); load(); }, [load]);

  useEffect(() => {
    if (user && user.role !== "admin") { router.push("/dashboard"); return; }
    if (!user) return;
    load();
  }, [user, router, load]);

  if (!user || user.role !== "admin") return null;

  if (!stats || !sum) {
    return (
      <>
        <PageHead>
          <PageTitle title="Overview" sub="The whole instance — every user, not just yours." />
        </PageHead>
        <div className="grid gap-3.5 sm:grid-cols-2 xl:grid-cols-4">
          {[0, 1, 2, 3].map((k) => <Skeleton key={k} className="h-[126px]" />)}
        </div>
        <Skeleton className="h-[260px]" />
      </>
    );
  }

  /* ---------------------------------------------------------------- maths */
  const W = Number(window_);
  const daily = sum.daily_sends ?? [];
  const counts = daily.map((d) => d.count);
  const days = daily.map((d) => d.date);
  const cur = counts.slice(-W);
  const prev = counts.slice(-2 * W, -W);
  const curDays = days.slice(-W);
  const activeDays = cur.filter(Boolean).length;
  const firstSend = curDays[cur.findIndex((v) => v > 0)];
  const lastSend = curDays[cur.length - 1 - [...cur].reverse().findIndex((v) => v > 0)];

  const week = counts.slice(-7).reduce((a, b) => a + b, 0);
  const weekBefore = counts.slice(-14, -7).reduce((a, b) => a + b, 0);
  const weekDelta = weekBefore ? pc(week - weekBefore, weekBefore) : null;

  const t = sum.targets ?? {};
  const totalTargets = sum.total_targets ?? 0;
  const attempted = sum.attempted ?? 0;
  const delivered = sum.sent ?? 0;
  const failed = t.failed ?? 0;
  const skipped = t.skipped ?? 0;
  const queued = t.queued ?? 0;
  const held = t.paused ?? 0;
  const camp = sum.campaigns ?? {};
  const campTotal = Object.values(camp).reduce((a, b) => a + b, 0);

  const clean = accts.filter((a) => !a.consecutive_errors);
  const enabled = accts.filter((a) => a.enabled);
  const processed = accts.reduce((a, b) => a + (b.messages_processed || 0), 0);
  const byPlatform = Object.entries(
    accts.reduce<Record<string, number>>((m, a) => ({ ...m, [a.platform]: (m[a.platform] || 0) + 1 }), {})
  ).sort((a, b) => b[1] - a[1]) as [string, number][];

  const byDay = errors.reduce<Record<string, number>>((m, e) => {
    const d = s(e, "created_at").slice(0, 10);
    return d ? { ...m, [d]: (m[d] || 0) + 1 } : m;
  }, {});
  const warnDays = Object.keys(byDay).sort();
  const bySource = Object.entries(
    errors.reduce<Record<string, number>>((m, e) => {
      const k = s(e, "source") || "unknown";
      return { ...m, [k]: (m[k] || 0) + 1 };
    }, {})
  ).sort((a, b) => b[1] - a[1]) as [string, number][];

  const byStatus = users.reduce<Record<string, number>>((m, u) => {
    const k = s(u, "status") || "active";
    return { ...m, [k]: (m[k] || 0) + 1 };
  }, {});
  const brandsByUser = brands.reduce<Record<string, number>>((m, b) => {
    const k = s(b, "user_id");
    return { ...m, [k]: (m[k] || 0) + 1 };
  }, {});
  const postsByUser = posts.reduce<Record<string, number>>((m, p) => {
    const k = s(p, "user_id");
    return { ...m, [k]: (m[k] || 0) + 1 };
  }, {});

  const POST_PLATFORMS = ["tiktok", "instagram", "youtube", "facebook"];
  const handles = postAccts.reduce(
    (a, x) => a + POST_PLATFORMS.filter((pl) => s(x, `${pl}_handle`)).length, 0);
  const tokens = postAccts.reduce(
    (a, x) => a + POST_PLATFORMS.filter((pl) => s(x, `${pl}_token`)).length, 0);
  const scheduled = posts.filter((p) => s(p, "status") === "scheduled").length;
  const withTrack = posts.filter((p) => p.music_track_id).length;
  const artistsOn = artists.filter((a) => a.is_active).length;

  const WD = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  const wk = sum.weekday_sends ?? {};
  const wkTotal = Object.values(wk).reduce((a, b) => a + b, 0) || 1;

  const st = stats.storage_mb ?? { uploads: 0, output: 0, music: 0, total: 0 };
  const health = stats.health ?? { cpu_percent: null, mem_percent: null, disk_percent: null };

  /* ------------------------------------------------------- joins by month */
  const today = new Date();
  const buckets = Array.from({ length: 6 }, (_, k) => monthStart(today, 5 - k));
  const joins = buckets.map((b) =>
    users.filter((u) => {
      const d = new Date(s(u, "created_at").slice(0, 10) + "T00:00:00");
      return d.getFullYear() === b.getFullYear() && d.getMonth() === b.getMonth();
    }).length);
  const joinTop = Math.max(...joins, 1);

  /* ------------------------------------------------------------- the tiles */
  // Each tile carries its own verdict, because the same percentage means
  // different things: 0% of handles signed in is a platform that cannot
  // post at all, while 50% of posts scheduled is just how many are
  // scheduled. `good` is where it should be, `down` is broken and somebody
  // has to act, `plain` is a figure and not a judgement.
  const TILES: [string, number, number, string, Tone, number[] | null][] = [
    ["Users", users.length, pc(byStatus.active ?? 0, users.length || 1),
      `${byStatus.active ?? 0} of ${users.length} active`,
      (byStatus.active ?? 0) === users.length ? "good" : "down", monthly(users)],
    ["Brands", stats.total_brands, pc(tokens, handles || 1),
      `${tokens} of ${handles} platform handles signed in`,
      tokens === 0 ? "down" : tokens === handles ? "good" : "warn", monthly(brands)],
    ["Posts", stats.total_posts, pc(scheduled, posts.length || 1),
      `${scheduled} of ${posts.length} scheduled, ${stats.failed_posts} failed`,
      stats.failed_posts ? "down" : "plain", monthly(posts)],
    ["Artists", artists.length, pc(artistsOn, artists.length || 1),
      `${artistsOn} of ${artists.length} running`,
      artistsOn === artists.length ? "good" : "down", monthly(artists)],
    ["Campaigns", campTotal, pc(camp.completed ?? 0, campTotal || 1),
      `${camp.completed ?? 0} of ${campTotal} completed`, "plain", monthly(camps)],
    ["Sending accounts", accts.length, pc(enabled.length, accts.length || 1),
      `${enabled.length} of ${accts.length} enabled`,
      pc(enabled.length, accts.length || 1) >= 90 ? "good"
        : pc(enabled.length, accts.length || 1) >= 60 ? "warn" : "down",
      monthly(accts as unknown as Row[])],
    // Leads have no listing of searches over time, and a line drawn for
    // nothing is a line that lies.
    ["Leads found", sum.leads, pc(sum.latest_search?.found ?? 0, sum.leads || 1),
      `${num(sum.latest_search?.found ?? 0)} from the newest search`, "plain", null],
    ["Music tracks", stats.total_tracks, pc(withTrack, posts.length || 1),
      `${withTrack} of ${posts.length} posts carry one`, "plain", []],
  ];

  /* -------------------------------------------------------- needs an admin */
  const oa = (oauth ?? {}) as Record<string, { configured?: boolean } | string | undefined>;
  const needs: [Tone, string, string, string, string][] = [];
  if (!String(oa.redirect_base ?? "").trim()) {
    needs.push(["down", "The public address is unset",
      "The dispatcher picks scheduled posts up every minute, finds nowhere to serve the video from and " +
      "puts them back. It writes no log when it does.", "Set it in Integrations", "/admin/tools?tab=oauth"]);
  }
  const pending = byStatus.pending ?? 0;
  if (pending) {
    needs.push(["warn",
      `${spell(pending).charAt(0).toUpperCase()}${spell(pending).slice(1)} ${plural(pending, "user is", "users are")} waiting for approval`,
      "They cannot sign in until someone approves them.", "Open Approvals", "/admin/approvals"]);
  }
  const unconf = ["meta", "instagram", "tiktok", "youtube"].filter(
    (k) => !(oa[k] as { configured?: boolean } | undefined)?.configured);
  if (unconf.length) {
    const names = unconf.map((k) => PLATFORM_NAME[k]);
    needs.push(["warn",
      unconf.length === 4 ? "All four platforms have no OAuth app"
        : `${spell(unconf.length).charAt(0).toUpperCase()}${spell(unconf.length).slice(1)} of four platforms have no OAuth app`,
      `Accounts cannot sign in to ${names.length > 1 ? names.slice(0, -1).join(", ") + " or " + names[names.length - 1] : names[0]} at all, so nothing posts there.`,
      "Open Integrations", "/admin/tools?tab=oauth"]);
  }
  const hot = accts.filter((a) => a.consecutive_errors);
  if (hot.length) {
    needs.push(["warn",
      `${spell(hot.length).charAt(0).toUpperCase()}${spell(hot.length).slice(1)} sending ${plural(hot.length, "account has", "accounts have")} errors in a row`,
      `At five in a row an account pauses itself and stops taking jobs: ${hot.map((a) => a.name).join(", ")}.`,
      "Open Accounts", "/outreach/accounts"]);
  }
  if (stats.failed_posts) {
    needs.push(["down", `${stats.failed_posts} posts failed`,
      "They stay failed until someone looks.", "Open Posts", "/admin/tools?tab=posts"]);
  }

  const topAccts = [...accts].sort((a, b) => (b.messages_processed || 0) - (a.messages_processed || 0)).slice(0, 6);

  /* ------------------------------------------ payments: nothing behind it */
  // NOTHING BEHIND THIS EXISTS. There is no payment provider, no
  // subscriptions table, no payment record and no per-call usage log
  // anywhere in the backend — the only prices in the codebase are the three
  // cards on the Help page, which are copy. So these figures are invented,
  // the card says so on its face, and the note under it lists what has to
  // be built before a single number in it can be real.
  const PLAN_PRICES: [string, number][] = [["Starter", 29], ["Studio", 79], ["Agency", 199]];
  const SAMPLE_SUBS: [string, number][] = [["Studio", 23], ["Starter", 14], ["Agency", 6]];
  const SAMPLE_MRR = [1180, 1395, 1622, 1870, 2104, 2436];
  const SAMPLE_TOKENS: [string, number, number][] = [
    ["Slides read", 1_284_000, 991], ["Captions rewritten", 412_000, 318],
    ["Images made", 96_000, 74], ["Assistant replies", 38_000, 29],
  ];
  const subsTotal = SAMPLE_SUBS.reduce((a, [, v]) => a + v, 0);
  const mrr = SAMPLE_SUBS.reduce((a, [k, v]) => a + (PLAN_PRICES.find(([p]) => p === k)?.[1] ?? 0) * v, 0);
  const collected = SAMPLE_MRR.reduce((a, b) => a + b, 0);
  const tokTotal = SAMPLE_TOKENS.reduce((a, [, v]) => a + v, 0);
  const tokCalls = SAMPLE_TOKENS.reduce((a, [, , c]) => a + c, 0);

  return (
    <>
      <PageHead>
        <PageTitle title="Overview" sub="The whole instance — every user, not just yours." />
        <PageActions>
          <Chip icon={RefreshCw} onClick={refresh} disabled={busy}>{busy ? "Refreshing…" : "Refresh"}</Chip>
          <SelectChip value={window_} options={WINDOWS} onChange={setWindow} label="Window" />
        </PageActions>
      </PageHead>

      {/* ------------------------------------------------------------ KPIs */}
      <div className="grid gap-3.5 sm:grid-cols-2 xl:grid-cols-4">
        <Kpi label="People on the instance" value={num(users.length)}
             sub={`${byStatus.active ?? 0} active · ${byStatus.pending ?? 0} waiting · ${stats.new_users_24h} joined today`} />
        <Kpi label="Delivery rate" value={`${pc(delivered, attempted || 1).toFixed(1)}%`}
             sub={`${num(delivered)} delivered of ${num(attempted)} attempted, all time`} />
        <Kpi label="Sent this week" value={num(week)} delta={weekDelta}
             sub={`against ${num(weekBefore)} the week before`} spark={counts.slice(-14)} />
        <Kpi label="Accounts without errors" value={`${pc(clean.length, accts.length || 1).toFixed(1)}%`}
             sub={`${clean.length} of ${accts.length} have no run of errors behind them`} />
      </div>

      {/* -------------------------------------- everything on the instance */}
      <Card>
        <CardHead title="Everything on the instance"
                  sub="Counted now, not over a window — each share says what it is a share of"
                  right={<DotsMenu items={[{ label: "Refresh", onClick: load }]} />} />
        <CardBody>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {TILES.map(([label, value, share, sub, tone, series]) => (
              <div key={label}
                   className="relative flex flex-col overflow-hidden rounded-[14px] border border-border bg-secondary px-3.5 pb-3 pt-3">
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <div className={`text-[24px] font-extrabold leading-[1.1] tracking-[-0.035em] tabular-nums ${value ? "text-foreground" : "text-subtle"}`}>
                      {num(value)}
                    </div>
                    <div className="mt-0.5 text-[12px] font-bold text-foreground">{label}</div>
                  </div>
                  <span className={`text-[12.5px] font-bold tabular-nums ${
                    tone === "down" ? "text-bad" : tone === "good" ? "text-good" : tone === "warn" ? "text-warn" : "text-subtle"
                  }`}>
                    {share.toFixed(0)}%
                  </span>
                </div>
                <div className="mt-2.5">
                  {series === null ? (
                    <div className="flex h-[42px] items-center text-[10.5px] leading-[1.45] text-subtle">
                      no history — nothing lists searches over time
                    </div>
                  ) : (
                    <Mini values={series} tone={tone} />
                  )}
                </div>
                <div className="mt-1.5 flex items-start gap-1.5 text-[10.5px] leading-[1.45] text-subtle">
                  {tone === "down" && <i className="mt-[5px] h-[5px] w-[5px] flex-none rounded-full bg-bad" />}
                  {sub}
                </div>
              </div>
            ))}
          </div>
        </CardBody>
      </Card>

      {/* --------------------------------------------------- needs an admin */}
      <Card>
        <CardHead title="Needs an admin" sub="Things nobody else on the instance can fix" />
        <CardBody>
          {needs.length === 0 ? (
            <div className="rounded-[12px] border border-good/25 bg-good/[0.07] px-4 py-3.5 text-[12.5px] font-semibold text-good">
              Nothing is waiting on you.
            </div>
          ) : (
            <div className="flex flex-col gap-2">
              {needs.map(([tone, head, body, act, href]) => (
                <Link key={head} href={href}
                      className="flex items-start gap-3 rounded-[12px] border border-border bg-secondary px-3.5 py-3 transition-colors hover:bg-card">
                  <span className={`mt-px grid h-[30px] w-[30px] flex-none place-items-center rounded-[10px] ${
                    tone === "down" ? "bg-bad/12 text-bad" : "bg-warn/12 text-warn"}`}>
                    {tone === "down" ? <AlertTriangle className="h-[15px] w-[15px]" /> : <Info className="h-[15px] w-[15px]" />}
                  </span>
                  <span className="min-w-0 flex-1">
                    <b className="block text-[12.5px] font-bold text-foreground">{head}</b>
                    <i className="mt-0.5 block text-[11px] not-italic leading-[1.55] text-subtle">{body}</i>
                  </span>
                  <span className="flex flex-none items-center gap-1.5 whitespace-nowrap text-[11.5px] font-semibold text-muted-foreground">
                    {act}<ArrowRight className="h-3.5 w-3.5" />
                  </span>
                </Link>
              ))}
            </div>
          )}
        </CardBody>
      </Card>

      {/* --------------------------------------------------------- people */}
      <Card>
        <CardHead title="People" sub="Who is on the instance, and when they arrived"
                  right={<DotsMenu items={[
                    { label: "Manage users", href: "/admin/users" },
                    { label: "Approve someone", href: "/admin/approvals" },
                  ]} />} />
        <CardBody>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Figure value={num(users.length)} label={plural(users.length, "account", "accounts") + " in total"} />
            <Figure value={num(stats.new_users_24h)} label="joined in 24 hours" />
            <Figure value={num(byStatus.pending ?? 0)} label="waiting for approval" />
            <Figure value={num(byStatus.suspended ?? 0)} label="suspended" />
          </div>

          <div className="mt-5">
            <Sub>Joins by month</Sub>
            <div className="flex items-stretch gap-2">
              {buckets.map((b, k) => (
                <div key={b.toISOString()} className="flex flex-1 flex-col items-center gap-1.5">
                  <span className={`text-[12px] font-bold tabular-nums ${joins[k] ? "text-foreground" : "text-subtle"}`}>
                    {joins[k]}
                  </span>
                  <span className="flex h-[54px] w-full items-end overflow-hidden rounded-[7px] bg-muted">
                    <i className="block w-full rounded-[7px] bg-[var(--chart-1)]"
                       style={{ height: `${(joins[k] / joinTop) * 100}%` }} />
                  </span>
                  <span className="text-[10.5px] text-subtle">
                    {b.toLocaleDateString(undefined, { month: "short" })}
                  </span>
                </div>
              ))}
            </div>
            {users.length <= 3 && users.length > 0 && (
              <div className="mt-2.5 text-[11px] leading-[1.55] text-subtle">
                {spell(users.length).charAt(0).toUpperCase() + spell(users.length).slice(1)}{" "}
                {plural(users.length, "account has", "accounts have")} ever been created here. The chart is the
                shape of that, not a system with no signal.
              </div>
            )}
          </div>

          <div className="mt-5">
            <Sub>Newest accounts</Sub>
            <div className="-mx-1 overflow-x-auto">
              <table className="w-full border-collapse">
                <thead>
                  <tr>
                    <th className={TH}>Person</th><th className={TH}>Role</th><th className={TH}>Status</th>
                    <th className={TH}>Joined</th><th className={TH}>Last seen</th>
                    <th className={`${TH} text-right`}>Brands</th><th className={`${TH} text-right`}>Posts</th>
                  </tr>
                </thead>
                <tbody>
                  {[...users]
                    .sort((a, b) => s(b, "created_at").localeCompare(s(a, "created_at")))
                    .slice(0, 6)
                    .map((u) => (
                      <tr key={s(u, "id")}>
                        <td className={TD}>
                          <Link href={`/admin/users/${s(u, "id")}`} className="flex items-center gap-2.5">
                            <Initial name={s(u, "name")} size={32} src={avatarSrc(u.avatar_url)} />
                            <span className="flex min-w-0 flex-col">
                              <span className="truncate font-semibold text-foreground">{s(u, "name")}</span>
                              <span className="truncate text-[10.5px] text-subtle">{s(u, "email")}</span>
                            </span>
                          </Link>
                        </td>
                        <td className={TD}><RolePill role={s(u, "role") || "user"} /></td>
                        <td className={TD}>
                          <Tag tone={s(u, "status") === "active" ? "done" : s(u, "status") === "suspended" ? "stop" : "pause"}>
                            {(s(u, "status") || "active").replace(/^./, (c) => c.toUpperCase())}
                          </Tag>
                        </td>
                        <td className={TD}><span className={MONO}>{s(u, "created_at").slice(0, 10)}</span></td>
                        <td className={`${TD} text-[11.5px] text-subtle`}>{ago(s(u, "last_login") || null)}</td>
                        <td className={`${TD} text-right font-semibold tabular-nums`}>{brandsByUser[s(u, "id")] ?? 0}</td>
                        <td className={`${TD} text-right font-semibold tabular-nums`}>{postsByUser[s(u, "id")] ?? 0}</td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          </div>
        </CardBody>
      </Card>

      {/* --------------------------------------- payments — nothing is real */}
      <Card className="border-warn/30">
        <CardHead
          title={<span className="flex items-center gap-2">Payments &amp; subscriptions
            <span className="rounded-full border border-warn/30 bg-warn/12 px-2 py-0.5 text-[10px] font-bold uppercase tracking-[0.06em] text-warn">sample</span>
          </span>}
          sub="What this card will hold. Nothing behind it exists yet." />
        <CardBody>
          <div className="grid gap-5 lg:grid-cols-[1.25fr_1fr]">
            <div className="lg:border-r lg:border-line-2 lg:pr-5">
              <div className="grid grid-cols-2 gap-2.5">
                <Pk label="Monthly recurring" value={`£${num(mrr)}`} note={`${subsTotal} paying accounts`} />
                <Pk label="Collected, six months" value={`£${num(collected)}`} note="sum of the line below" />
                <Pk label="Churn this month" value="2" note={`${pc(2, subsTotal).toFixed(1)}% of paying accounts`} />
                <Pk label="Average per account" value={`£${Math.round(mrr / subsTotal)}`} note="across the three plans" />
              </div>
              <Sub className="mt-3.5">Recurring revenue by month</Sub>
              <Mini values={SAMPLE_MRR} tone="plain" w={320} h={76} />
              <div className="mt-1 flex justify-between text-[10px] text-subtle">
                {buckets.map((b) => (
                  <span key={b.toISOString()}>{b.toLocaleDateString(undefined, { month: "short" })}</span>
                ))}
              </div>
            </div>
            <div>
              <Sub>Who is on what</Sub>
              <Bars rows={SAMPLE_SUBS} share labelWidth={72} />
              <div className="mt-2 text-[10.5px] text-subtle">
                {PLAN_PRICES.map(([k, v]) => `${k} £${v}`).join(" · ")}
              </div>
              <Sub className="mt-4">AI tokens this month</Sub>
              <div className="mb-1.5 flex items-baseline gap-2">
                <b className="text-[20px] font-extrabold tracking-[-0.03em] tabular-nums text-foreground">
                  {(tokTotal / 1_000_000).toFixed(2)}M
                </b>
                <span className="text-[11px] text-subtle">tokens over {num(tokCalls)} calls</span>
              </div>
              <Bars rows={SAMPLE_TOKENS.map(([k, v]) => [k, v] as [string, number])} share labelWidth={114} />
            </div>
          </div>
          <div className="mt-4 flex items-start gap-2.5 rounded-[12px] border border-warn/25 bg-warn/[0.07] px-3.5 py-3 text-[11px] leading-[1.55] text-muted-foreground">
            <Info className="mt-px h-[14px] w-[14px] flex-none text-warn" />
            <span>
              Every figure in this card is invented. To make it real: a <b className="text-foreground">subscriptions</b>{" "}
              table (who is on which plan, since when), a payment provider and its webhook so a payment is
              recorded when it happens, and a <b className="text-foreground">usage log</b> written on each AI call —
              the app makes those calls today and keeps no count. The three prices come from the Help page,
              which is copy, not a price list.
            </span>
          </div>
        </CardBody>
      </Card>

      {/* ------------------------------------------------ sends and targets */}
      <div className="grid items-stretch gap-4 xl:grid-cols-[1.42fr_1fr]">
        <Card className="flex flex-col">
          <CardHead title="Messages delivered"
                    sub={`Per day, everyone's campaigns together, against the same length before it`} />
          <CardBody className="flex flex-1 flex-col">
            <TwoLine cur={cur} prev={prev} labels={curDays} seriesName="Messages sent"
                     curLabel={`Last ${W} days`} prevLabel={`The ${W} before`} />
            <div className="mt-3.5 grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-5">
              <Mini2 value={num(cur.reduce((a, b) => a + b, 0))} label={`SENT, ${W} DAYS`} />
              <Mini2 value={(cur.reduce((a, b) => a + b, 0) / W).toFixed(0)} label="A DAY, AVERAGE" />
              <Mini2 value={num(Math.max(...cur, 0))} label="BEST DAY" />
              <Mini2 value={String(activeDays)} label="DAYS THAT SENT" />
              <Mini2 value={`${pc(activeDays, W).toFixed(0)}%`} label="OF THE WINDOW" />
            </div>
            <div className="mt-auto pt-3 text-[11px] leading-[1.55] text-subtle">
              {activeDays === 0 ? (
                <>Nothing has gone out in this window at all. Of {campTotal} campaigns,{" "}
                  {camp.running ? `${camp.running} is running` : "none is running"}.</>
              ) : (
                <>Sending in this window runs from {firstSend} to {lastSend}
                  {prev.reduce((a, b) => a + b, 0) === 0
                    ? ", and the dashed line sits on the floor because the period before it carries no sends at all"
                    : ""}. Of {campTotal} campaigns,{" "}
                  {camp.running ? `${camp.running} is running` : "none is running"}.</>
              )}
            </div>
          </CardBody>
        </Card>

        <Card className="flex flex-col">
          <CardHead title="Where every target ends up" sub={`All ${num(totalTargets)} of them, by what happened`} />
          <CardBody className="flex flex-1 flex-col">
            <Funnel rows={[
              ["Imported", totalTargets, "everything ever loaded into a campaign"],
              ["Attempted", attempted, `${num(queued)} never picked up, ${num(held)} held by a paused account`],
              ["Delivered", delivered, `${pc(delivered, attempted || 1).toFixed(1)}% of what was attempted`],
            ]} />
            <div className="mt-4 grid grid-cols-2 gap-3">
              <Figure value={`${pc(failed, attempted || 1).toFixed(1)}%`}
                      label={`failed — ${num(failed)} of ${num(attempted)} attempted`} />
              <Figure value={`${pc(skipped, attempted || 1).toFixed(1)}%`}
                      label={`skipped — ${num(skipped)} the worker would not send`} />
              <Figure value={`${pc(queued, totalTargets || 1).toFixed(1)}%`}
                      label={`still queued — ${num(queued)} waiting on a run`} />
              <Figure value={num(sum.leads)} label="leads discovery has found, all time" />
            </div>
          </CardBody>
        </Card>
      </div>

      {/* ------------------------------------------------- three-card row */}
      <div className="grid items-stretch gap-4 lg:grid-cols-3">
        <Card className="flex flex-col">
          <CardHead title="Best day to send" sub="Every send ever, by weekday" />
          <CardBody className="flex flex-1 flex-col">
            <Bars rows={WD.map((d) => [d, wk[d] ?? 0] as [string, number])} share labelWidth={44} />
            <div className="mt-auto pt-3 text-[11px] leading-[1.55] text-subtle">
              This is when the campaigns ran, not proof of a better day.
              {delivered - wkTotal > 0 && (
                <> {num(delivered - wkTotal)} sends carry no timestamp and sit in none of these bars.</>
              )}
            </div>
          </CardBody>
        </Card>

        <Card className="flex flex-col">
          <CardHead title="Accounts by platform"
                    sub={`${accts.length} accounts · ${enabled.length} enabled · ${accts.filter((a) => a.has_session).length} signed in`} />
          <CardBody className="flex flex-1 flex-col">
            <Stack rows={byPlatform} label={(k) => PLATFORM_NAME[k] ?? k} />
            <Sub className="mt-5">Campaigns by state</Sub>
            <Bars rows={Object.entries(camp).sort((a, b) => b[1] - a[1]) as [string, number][]} share labelWidth={72} />
          </CardBody>
        </Card>

        <Card className="flex flex-col">
          <CardHead title="Machine" sub="This box, right now"
                    right={<DotsMenu items={[{ label: "Refresh", onClick: load }]} />} />
          <CardBody className="flex flex-1 flex-col">
            <Gauge label="CPU" pct={health.cpu_percent} note="across all cores" />
            <Gauge label="Memory" pct={health.mem_percent} note="of physical RAM" />
            <Gauge label="Disk" pct={health.disk_percent} note="of the root volume" />
            <Sub className="mt-4">Storage written by the app</Sub>
            <Bars rows={[["Uploads", st.uploads], ["Renders", st.output], ["Music", st.music]]} unit=" MB" labelWidth={62} />
            {st.total === 0 && (
              <div className="mt-auto pt-3 text-[11px] leading-[1.55] text-subtle">
                Nothing on disk: no post has been built and no track uploaded here.
              </div>
            )}
          </CardBody>
        </Card>
      </div>

      {/* ---------------------------------------------- accounts & warnings */}
      <div className="grid items-stretch gap-4 lg:grid-cols-2">
        <Card className="flex flex-col">
          <CardHead title="Busiest accounts" sub="By what each one has processed" />
          <CardBody className="flex flex-1 flex-col">
            {topAccts.length === 0 ? (
              <div className="text-[12px] text-subtle">No sending accounts on the instance yet.</div>
            ) : (
              <div className="flex flex-col">
                {topAccts.map((a) => (
                  <div key={a.id} className="flex items-center gap-3 border-b border-line-2 py-2.5 last:border-b-0">
                    <span className="grid h-[30px] w-[30px] flex-none place-items-center rounded-[10px] border border-border bg-secondary text-[11px] font-bold uppercase text-muted-foreground">
                      {(PLATFORM_NAME[a.platform] ?? a.platform).slice(0, 2)}
                    </span>
                    <span className="min-w-0 flex-1">
                      <b className="block truncate text-[12.5px] font-bold text-foreground">{a.name}</b>
                      <i className="block text-[10.5px] not-italic text-subtle">
                        {PLATFORM_NAME[a.platform] ?? a.platform} · {a.status}
                        {a.consecutive_errors ? ` · ${a.consecutive_errors} errors in a row` : ""}
                      </i>
                    </span>
                    <span className="flex-none text-right">
                      <b className="block text-[13px] font-bold tabular-nums text-foreground">{num(a.messages_processed)}</b>
                      <i className="block text-[10.5px] not-italic tabular-nums text-subtle">
                        {pc(a.messages_processed || 0, processed || 1).toFixed(0)}%
                      </i>
                    </span>
                  </div>
                ))}
              </div>
            )}
            {processed !== delivered && topAccts.length > 0 && (
              <div className="mt-auto pt-3 text-[11px] leading-[1.55] text-subtle">
                These counters add up to {num(processed)}, {processed < delivered ? "below" : "above"} the{" "}
                {num(delivered)} sends the targets record. They are kept in different places and need not
                agree — read the order, not the gap.
              </div>
            )}
          </CardBody>
        </Card>

        <Card className="flex flex-col">
          <CardHead title="Warnings logged"
                    sub={`The newest ${num(errors.length)} entries, and the ${spell(warnDays.length)} ${plural(warnDays.length, "day", "days")} they span`} />
          <CardBody className="flex flex-1 flex-col">
            {errors.length === 0 ? (
              <div className="text-[12px] text-subtle">Nothing has been logged.</div>
            ) : (
              <>
                <div className="mb-3.5 flex flex-wrap items-baseline gap-2">
                  <span className="text-[27px] font-extrabold leading-none tracking-[-0.035em] tabular-nums text-foreground">
                    {num(errors.length)}
                  </span>
                  <span className="text-[12px] text-subtle">newest entries · oldest {warnDays[0]}</span>
                </div>
                <Bars
                  rows={warnDays.map((d) => [
                    new Date(d + "T00:00:00").toLocaleDateString(undefined, { weekday: "short", day: "2-digit" }),
                    byDay[d],
                  ] as [string, number])}
                  share labelWidth={58} />
                <Sub className="mt-4">Where they come from</Sub>
                <Bars rows={bySource} share labelWidth={128} />
              </>
            )}
          </CardBody>
        </Card>
      </div>

      {/* ------------------------------------------------- latest warnings */}
      <Card>
        <CardHead title="Latest warnings" sub="Newest first, first line only"
                  right={<DotsMenu items={[{ label: "Open the full log", href: "/admin/tools?tab=errors" }]} />} />
        <div className="overflow-x-auto px-5 pb-1 pt-3.5">
          <table className="w-full border-collapse">
            <thead>
              <tr><th className={TH}>When</th><th className={TH}>Source</th><th className={TH}>What it said</th></tr>
            </thead>
            <tbody>
              {errors.slice(0, 6).map((e, k) => (
                <tr key={k}>
                  <td className={`${TD} whitespace-nowrap`}>
                    <span className={MONO}>{s(e, "created_at").slice(5, 16).replace("T", " ")}</span>
                  </td>
                  <td className={`${TD} whitespace-nowrap text-[11.5px] text-muted-foreground`}>{s(e, "source")}</td>
                  <td className={`${TD} text-[12px] text-muted-foreground`}>
                    {s(e, "message").split("\n")[0].slice(0, 120)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <Link href="/admin/tools?tab=errors"
              className="flex items-center gap-1.5 px-5 py-3.5 text-[12px] font-semibold text-muted-foreground transition-colors hover:text-foreground">
          <ArrowRight className="h-3.5 w-3.5" />Open the full log
        </Link>
      </Card>

      <Note>
        Every percentage above names what it is a percentage of. The log endpoint returns the newest 200
        entries and no total, so anything drawn from it describes those entries rather than the whole log.
        Everything else is instance-wide — the same figures on the user side are scoped to one account and
        will not agree.
      </Note>
    </>
  );
}

/* ------------------------------------------------------------------ bits */

function Kpi({ label, value, sub, delta, spark }: {
  label: string; value: string; sub: string; delta?: number | null; spark?: number[];
}) {
  return (
    <div className="flex flex-col rounded-[16px] border border-border bg-card px-4 pb-3 pt-3.5 shadow-card">
      <div className="flex items-center gap-2 text-[11.5px] font-semibold text-subtle">
        {label}
        {delta !== null && delta !== undefined && (
          <span className={`ml-auto rounded-full px-[7px] py-0.5 text-[10.5px] font-bold tabular-nums ${
            delta >= 0 ? "bg-good/12 text-good" : "bg-bad/12 text-bad"}`}>
            {delta >= 0 ? "▲" : "▼"} {Math.abs(delta).toFixed(0)}%
          </span>
        )}
      </div>
      <div className="mt-1.5 text-[31px] font-extrabold leading-[1.15] tracking-[-0.04em] tabular-nums text-foreground">
        {value}
      </div>
      <div className="mt-1 text-[11px] leading-[1.45] text-subtle">{sub}</div>
      {spark && <Spark values={spark} />}
    </div>
  );
}

/** A figure and the sentence that says what it is of. */
function Figure({ value, label }: { value: React.ReactNode; label: React.ReactNode }) {
  const zero = value === "0" || value === 0;
  return (
    <div className="rounded-[12px] border border-border bg-secondary px-3.5 py-2.5">
      <b className={`block text-[20px] font-extrabold leading-tight tracking-[-0.03em] tabular-nums ${zero ? "text-subtle" : "text-foreground"}`}>
        {value}
      </b>
      <i className="mt-0.5 block text-[10.5px] not-italic leading-[1.45] text-subtle">{label}</i>
    </div>
  );
}

function Mini2({ value, label }: { value: string; label: string }) {
  return (
    <div>
      <div className="text-[17px] font-extrabold leading-tight tracking-[-0.03em] tabular-nums text-foreground">{value}</div>
      <div className="mt-0.5 text-[9.5px] font-bold uppercase tracking-[0.06em] text-subtle">{label}</div>
    </div>
  );
}

function Pk({ label, value, note }: { label: string; value: string; note: string }) {
  return (
    <div className="rounded-[12px] border border-border bg-secondary px-3.5 py-2.5">
      <i className="block text-[10.5px] font-semibold not-italic text-subtle">{label}</i>
      <b className="mt-0.5 block text-[22px] font-extrabold leading-tight tracking-[-0.035em] tabular-nums text-foreground">{value}</b>
      <em className="mt-0.5 block text-[10px] not-italic text-subtle">{note}</em>
    </div>
  );
}
