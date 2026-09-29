"use client";

/**
 * Dashboard — the three pipelines at a glance.
 *
 * Outreach carries the headline row because that is where the volume is,
 * but Brands and Clipping sit directly beneath it at the same level: the
 * product is not only a message sender, and a dashboard that only counts
 * DMs says otherwise.
 *
 * Everything here is read, never written. Three calls fill it:
 * `getStats` (brands + clipping), `listOutreachCampaigns` (the table and
 * the per-campaign counters) and `getOutreachSummary` (lead count, the
 * last fortnight of sends, the weekday split). Each renders independently,
 * so a slow or failed call leaves the rest of the page intact.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import {
  Target, Send, Search, Users, Tag, Scissors, ChevronUp,
  Info, Mic, ArrowUp, Download, CalendarDays,
  ChevronDown, LayoutGrid, MoreHorizontal, Maximize2, Check,
} from "lucide-react";
import { getStats, getOutreachSummary, listOutreachCampaigns } from "@/lib/api";

/* ------------------------------------------------------------------ */
/* types                                                               */
/* ------------------------------------------------------------------ */

type Summary = {
  targets: Record<string, number>;
  total_targets: number;
  sent: number;
  attempted: number;
  delivery_rate: number;
  leads: number;
  latest_search: { id: number; found: number; status: string } | null;
  accounts: Record<string, number>;
  daily_sends: { date: string; count: number }[];
  weekday_sends: Record<string, number>;
  /** The only range-scoped block: everything else on this payload is
   *  all-time, and each card says which it is showing. */
  range: { days: number; sent: number; prev_sent: number };
};

type Campaign = {
  id: number; name: string; platform: string; status: string;
  total_targets?: number; successful_count?: number; progress?: number;
};

const DOW = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
/** Must stay in step with the server's SUMMARY_WINDOWS — it rejects
 *  anything else rather than quietly substituting a window. */
const WINDOWS = [7, 14, 30, 90] as const;
const n = (v: number | undefined) => (v ?? 0).toLocaleString();

/* ------------------------------------------------------------------ */
/* small pieces                                                        */
/* ------------------------------------------------------------------ */

/** The "..." every panel in the design carries. Inert for now — it marks
 *  where per-card actions (hide, refresh, export) will hang. */
function CardMenu() {
  return (
    <button aria-label="Card options"
      className="grid h-[26px] w-[26px] flex-none place-items-center rounded-[7px] text-subtle transition-colors hover:bg-secondary hover:text-foreground">
      <MoreHorizontal className="h-[17px] w-[17px]" />
    </button>
  );
}

function Card({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={`rounded-[18px] border border-border bg-card shadow-card ${className}`}>
      {children}
    </div>
  );
}

function Kpi({ label, value, icon: Icon, tint, delta, sub }: {
  label: string; value: string; icon: any; tint: string;
  delta?: { dir: "up" | "dn"; text: string }; sub?: string;
}) {
  return (
    <Card className="p-4 md:px-[18px] md:py-[17px]">
      <div className="mb-3 flex items-center justify-between">
        <span className="text-[13px] font-semibold text-muted-foreground">{label}</span>
        <span className={`grid h-[26px] w-[26px] place-items-center rounded-[8px] ${tint}`}>
          <Icon className="h-[15px] w-[15px]" strokeWidth={2} />
        </span>
      </div>
      <div className="flex items-baseline gap-[9px]">
        <span className="text-[27px] font-extrabold tracking-[-0.035em] tabular-nums text-foreground">{value}</span>
        {delta && (
          <span className={`inline-flex items-center gap-[3px] rounded-full px-[7px] py-[2.5px] text-[11.5px] font-bold ${
            delta.dir === "up" ? "bg-good/12 text-good" : "bg-bad/12 text-bad"}`}>
            {delta.dir === "up" ? <ChevronUp className="h-[11px] w-[11px]" strokeWidth={3} />
                                : <ChevronDown className="h-[11px] w-[11px]" strokeWidth={3} />}
            {delta.text}
          </span>
        )}
      </div>
      {sub && <p className="mt-[7px] text-[11.5px] text-subtle">{sub}</p>}
    </Card>
  );
}

/** A pipeline strip: five counters and one line saying what is holding it up. */
function Pipeline({ title, kicker, icon: Icon, tint, cells, note }: {
  title: string; kicker: string; icon: any; tint: string;
  cells: { v: number; l: string }[]; note: string;
}) {
  return (
    <Card className="p-4 md:px-[18px] md:pb-[18px] md:pt-4">
      <div className="mb-3.5 flex items-center gap-2.5">
        <span className={`grid h-7 w-7 place-items-center rounded-[9px] ${tint}`}>
          <Icon className="h-[15px] w-[15px]" strokeWidth={2} />
        </span>
        <span className="text-[13.5px] font-bold text-foreground">{title}</span>
        <span className="ml-auto text-[11px] font-semibold text-subtle">{kicker}</span>
      </div>
      <div className="grid grid-cols-5 gap-2">
        {cells.map((c) => (
          <div key={c.l} className="rounded-[10px] bg-secondary px-1 py-[9px] text-center">
            <div className={`text-[18px] leading-[1.15] tracking-[-0.03em] tabular-nums ${
              c.v === 0 ? "font-bold text-subtle" : "font-extrabold text-foreground"}`}>{c.v}</div>
            <div className="mt-[3px] text-[9.5px] font-semibold tracking-[0.01em] text-subtle">{c.l}</div>
          </div>
        ))}
      </div>
      <p className="mt-[11px] flex items-center gap-1.5 text-[11px] text-subtle">
        <Info className="h-3 w-3 flex-none" /> {note}
      </p>
    </Card>
  );
}

/** Sparkline with a crosshair. One series — the title names it, so no legend. */
function SendsChart({ data }: { data: { date: string; count: number }[] }) {
  const [hover, setHover] = useState<number | null>(null);
  const W = 640, H = 186, P = { t: 12, r: 10, b: 26, l: 34 };
  const iw = W - P.l - P.r, ih = H - P.t - P.b;
  const peak = Math.max(1, ...data.map((d) => d.count));
  const max = Math.ceil(peak / 100) * 100 || 100;
  const X = (i: number) => P.l + (i * iw) / Math.max(1, data.length - 1);
  const Y = (v: number) => P.t + ih - (v / max) * ih;
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => Math.round(max * f));
  const last = data.length - 1;
  const ticksX = new Set(
    last <= 0 ? [0] : [0, 0.25, 0.5, 0.75, 1].map((f) => Math.round(last * f)));
  const line = data.map((d, i) => `${i ? "L" : "M"}${X(i)},${Y(d.count)}`).join(" ");
  const label = (s: string) =>
    new Date(s + "T00:00:00").toLocaleDateString(undefined, { month: "short", day: "numeric" });

  if (!data.length) {
    return <div className="grid h-[186px] place-items-center text-sm text-muted-foreground">No sends in the last 14 days.</div>;
  }
  return (
    <div className="relative min-w-0 flex-1">
      <svg viewBox={`0 0 ${W} ${H}`} className="block w-full overflow-visible"
        role="img" aria-label={`Messages sent per day. Peak ${peak}.`}
        onPointerMove={(e) => {
          const r = e.currentTarget.getBoundingClientRect();
          const sx = (e.clientX - r.left) * (W / r.width);
          setHover(Math.max(0, Math.min(data.length - 1, Math.round((sx - P.l) / (iw / Math.max(1, data.length - 1))))));
        }}
        onPointerLeave={() => setHover(null)}>
        <defs>
          <linearGradient id="sendsFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--chart-1)" stopOpacity=".22" />
            <stop offset="100%" stopColor="var(--chart-1)" stopOpacity="0" />
          </linearGradient>
        </defs>
        {ticks.map((v) => (
          <g key={v}>
            <line x1={P.l} y1={Y(v)} x2={W - P.r} y2={Y(v)} className="stroke-line-2" strokeWidth={1} />
            <text x={P.l - 8} y={Y(v) + 3.5} textAnchor="end" className="fill-subtle text-[10.5px]">{v}</text>
          </g>
        ))}
        <path d={`${line} L${X(data.length - 1)},${Y(0)} L${X(0)},${Y(0)} Z`} fill="url(#sendsFill)" />
        <path d={line} fill="none" stroke="var(--chart-1)" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
        {data.map((d, i) =>
          // Five evenly spaced labels: enough to read the span, few enough
          // that they never collide. Derived from the ends inwards rather
          // than by modulo — at 90 days a stride of 22 put a tick one slot
          // short of the last one, and the two dates printed on top of
          // each other.
          ticksX.has(i) ? (
            <text key={d.date} x={X(i)} y={H - 7} textAnchor="middle" className="fill-subtle text-[10.5px]">{label(d.date)}</text>
          ) : null)}
        {hover !== null && (
          <>
            <line x1={X(hover)} y1={P.t} x2={X(hover)} y2={P.t + ih} className="stroke-muted-foreground" strokeWidth={1} strokeDasharray="3 3" opacity={0.65} />
            <circle cx={X(hover)} cy={Y(data[hover].count)} r={5} fill="var(--chart-1)" className="stroke-card" strokeWidth={2} />
          </>
        )}
      </svg>
      {hover !== null && (
        <div className="pointer-events-none absolute z-10 whitespace-nowrap rounded-[11px] border border-border bg-card px-[11px] py-[9px] text-[11.5px] shadow-[0_12px_26px_-12px_rgba(16,24,40,0.45)]"
          style={{ left: `${(X(hover) / W) * 100}%`, top: `${(Y(data[hover].count) / H) * 100}%`, transform: "translate(-50%,-115%)" }}>
          <b className="mb-[5px] block text-xs font-bold text-foreground">{label(data[hover].date)}</b>
          <span className="flex items-center gap-[7px] text-muted-foreground">
            <i className="h-[2.5px] w-[9px] rounded-[2px]" style={{ background: "var(--chart-1)" }} />
            Messages sent
            <b className="ml-auto pl-2 font-extrabold tabular-nums text-foreground">{n(data[hover].count)}</b>
          </span>
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */

export default function DashboardPage() {
  const [stats, setStats] = useState({
    brands: 0, accounts: 0, posts_today: 0, scheduled: 0, total_posts: 0,
    artists: 0, variations: 0, clips: 0, clip_posts: 0, clip_scheduled: 0,
    drafts: 0,
  });
  const [sum, setSum] = useState<Summary | null>(null);
  const [camps, setCamps] = useState<Campaign[]>([]);
  const [days, setDays] = useState<number>(14);
  const [rangeOpen, setRangeOpen] = useState(false);
  const rangeRef = useRef<HTMLDivElement>(null);

  // A menu that only closes by clicking its own button is a trap once it
  // covers the cards behind it.
  useEffect(() => {
    if (!rangeOpen) return;
    const onDown = (e: MouseEvent) => {
      if (rangeRef.current && !rangeRef.current.contains(e.target as Node)) setRangeOpen(false);
    };
    const onEsc = (e: KeyboardEvent) => e.key === "Escape" && setRangeOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onEsc);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onEsc);
    };
  }, [rangeOpen]);

  useEffect(() => {
    getStats().then((s: any) => setStats((p) => ({ ...p, ...s }))).catch(() => {});
    listOutreachCampaigns().then(setCamps).catch(() => {});
  }, []);

  // Re-fetched on every window change: the server does the arithmetic, so
  // the page never derives a windowed figure from data it was not given.
  useEffect(() => {
    getOutreachSummary(days).then(setSum).catch(() => {});
  }, [days]);

  /* This window against the one immediately before it, both counted by
     the server. With no prior window there is nothing to compare, and
     inventing a baseline would be a lie — so the chip is simply absent. */
  const wow = useMemo(() => {
    const r = sum?.range;
    if (!r || !r.prev_sent) return null;
    const pct = ((r.sent - r.prev_sent) / r.prev_sent) * 100;
    return {
      dir: (pct >= 0 ? "up" : "dn") as "up" | "dn",
      text: `${Math.abs(pct).toFixed(1)}%`,
      curr: r.sent, prev: r.prev_sent, days: r.days,
    };
  }, [sum]);

  /* The span the chart actually covers, named rather than assumed. */
  const span = useMemo(() => {
    const d = sum?.daily_sends ?? [];
    if (!d.length) return "last 14 days";
    const f = (s: string) => new Date(s + "T00:00:00")
      .toLocaleDateString(undefined, { month: "short", day: "numeric" });
    const yr = new Date(d[d.length - 1].date + "T00:00:00").getFullYear();
    return `${f(d[0].date)} – ${f(d[d.length - 1].date)} ${yr}`;
  }, [sum]);

  /* The window every figure on this page is bounded by. Taken from the
     data itself where there is any, so the label can never disagree with
     the chart beside it. */
  const range = useMemo(() => {
    const d = sum?.daily_sends ?? [];
    const fmt = (x: Date) => x.toLocaleDateString(undefined, { month: "short", day: "numeric" });
    const end = d.length ? new Date(d[d.length - 1].date + "T00:00:00") : new Date();
    const start = d.length ? new Date(d[0].date + "T00:00:00")
                           : new Date(Date.now() - (days - 1) * 864e5);
    return `${fmt(start)} – ${fmt(end)}, ${end.getFullYear()}`;
  }, [sum, days]);

  /* Export is a real download, not a decorative button: the campaign table
     as CSV, built in the browser from what is already loaded. */
  const exportHref = useMemo(() => {
    const esc = (v: string) => `"${String(v).replace(/"/g, '""')}"`;
    const rows = [
      ["id", "name", "platform", "status", "sent", "total_targets"],
      ...camps.map((c) => [c.id, c.name, c.platform, c.status,
                           c.successful_count ?? 0, c.total_targets ?? 0]),
    ];
    const csv = rows.map((r) => r.map((x) => esc(String(x))).join(",")).join("\n");
    return `data:text/csv;charset=utf-8,${encodeURIComponent(csv)}`;
  }, [camps]);

  const periodTotal = sum?.range?.sent ?? 0;
  /* The weekday split can only see sends that carry a `sent_at`. Some do
     not — campaign 14 holds 248 marked sent by a bulk status change that
     never stamped a time — so where the two disagree the card states its
     own coverage rather than claiming a total it is short of. */
  const wdTotal = DOW.reduce((a, d) => a + (sum?.weekday_sends?.[d] ?? 0), 0);
  const wdComplete = !sum || wdTotal === (sum.sent ?? 0);
  const rate = sum ? Math.round(sum.delivery_rate * 1000) / 10 : 0;
  const wdMax = Math.max(1, ...DOW.map((d) => sum?.weekday_sends?.[d] ?? 0));
  const top = [...camps]
    .sort((a, b) => (b.successful_count ?? 0) - (a.successful_count ?? 0))
    .slice(0, 6);
  const idle = sum?.accounts?.idle ?? 0;
  const accTotal = Object.values(sum?.accounts ?? {}).reduce((a, b) => a + b, 0);

  const t = sum?.targets ?? {};
  const segs = [
    { v: t.queued ?? 0, l: "Queued", c: "var(--chart-1)" },
    { v: t.sent ?? 0, l: "Sent", c: "var(--chart-2)" },
    { v: (t.paused ?? 0) + (t.skipped ?? 0) + (t.failed ?? 0), l: "Paused, skipped & failed", c: "var(--chart-3)" },
  ];
  const segTotal = segs.reduce((a, b) => a + b.v, 0) || 1;

  return (
    <div data-metrics className="flex flex-col gap-4">
      {/* header */}
      <div className="flex flex-wrap items-center gap-2.5">
        <h1 className="text-[25px] font-extrabold tracking-[-0.03em] text-foreground">Dashboard</h1>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          {/* The window these figures describe, stated rather than implied —
              every number on this page is bounded by it. */}
          <span className="flex items-center gap-[7px] rounded-[11px] border border-border bg-card px-[13px] py-2 text-[12.5px] font-semibold text-foreground shadow-card">
            <CalendarDays className="h-3.5 w-3.5 text-subtle" /> {range}
          </span>
          <div className="relative" ref={rangeRef}>
            <button onClick={() => setRangeOpen((v) => !v)} aria-haspopup="listbox" aria-expanded={rangeOpen}
              className="flex items-center gap-[7px] rounded-[11px] border border-border bg-card px-[13px] py-2 text-[12.5px] font-semibold text-foreground shadow-card transition-colors hover:bg-secondary">
              Last {days} days
              <ChevronDown className={`h-3.5 w-3.5 text-subtle transition-transform ${rangeOpen ? "rotate-180" : ""}`} />
            </button>
            {rangeOpen && (
              <div role="listbox" className="absolute right-0 top-full z-50 mt-2 w-[150px] rounded-[14px] border border-border bg-popover p-1.5
                              shadow-[0_18px_40px_-16px_rgba(16,24,40,0.45)]">
                {WINDOWS.map((d) => (
                  <button key={d} role="option" aria-selected={d === days}
                    onClick={() => { setDays(d); setRangeOpen(false); }}
                    className={`flex w-full items-center justify-between rounded-[9px] px-2.5 py-2 text-[12.5px] transition-colors hover:bg-secondary ${
                      d === days ? "font-bold text-foreground" : "font-semibold text-muted-foreground"}`}>
                    Last {d} days
                    {d === days && <Check className="h-3.5 w-3.5 text-[var(--chart-1)]" strokeWidth={3} />}
                  </button>
                ))}
              </div>
            )}
          </div>
          <span className="flex items-center gap-[7px] rounded-[11px] border border-border bg-card px-[13px] py-2 text-[12.5px] font-semibold text-foreground shadow-card">
            <LayoutGrid className="h-3.5 w-3.5 text-subtle" /> Add widget
          </span>
          <a href={exportHref} download="dashboard.csv"
            className="flex items-center gap-[7px] rounded-[11px] bg-foreground px-4 py-[9px] text-[12.5px] font-bold text-primary-foreground shadow-[0_8px_18px_-9px_rgba(11,13,18,0.55)] transition-opacity hover:opacity-90">
            <Download className="h-3.5 w-3.5" /> Export
          </a>
        </div>
      </div>

      {/* outreach KPIs */}
      <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-2 xl:grid-cols-4">
        <Kpi label="Total Targets" value={n(sum?.total_targets)} icon={Target}
          tint="bg-[var(--chart-1)]/16 text-[var(--chart-1)]"
          sub={`across ${camps.length} campaign${camps.length === 1 ? "" : "s"}`} />
        {/* Scoped to the selected window, like the chart below it. The
            all-time send total is the Delivery Rate card's business. */}
        <Kpi label={`Messages Sent · ${days}d`} value={n(periodTotal)} icon={Send}
          tint="bg-[var(--chart-2)]/12 text-[var(--chart-2)]"
          delta={wow ? { dir: wow.dir, text: wow.text } : undefined}
          sub={wow ? `vs. ${n(wow.prev)} the previous ${days} days`
                   : `no prior ${days} days to compare`} />
        <Kpi label="Leads Found" value={n(sum?.leads)} icon={Search}
          tint="bg-[var(--chart-3)]/14 text-[var(--chart-3)]"
          delta={sum?.leads ? { dir: "up", text: "New" } : undefined}
          sub={sum?.latest_search?.found ? `${n(sum.latest_search.found)} from the latest sweep` : "from lead discovery"} />
        <Kpi label="Sending Accounts" value={n(accTotal)} icon={Users}
          tint="bg-subtle/14 text-muted-foreground"
          sub={accTotal ? (idle === accTotal ? "all idle · none paused" : `${idle} idle · ${accTotal - idle} in use or paused`) : "none added yet"} />
      </div>

      {/* the other two pipelines */}
      <div className="grid grid-cols-1 gap-3.5 lg:grid-cols-2">
        <Pipeline title="Brands" kicker="Scheduled posting" icon={Tag}
          tint="bg-[var(--chart-1)]/16 text-[var(--chart-1)]"
          cells={[
            { v: stats.brands, l: "BRANDS" }, { v: stats.accounts, l: "ACCOUNTS" },
            { v: stats.posts_today, l: "TODAY" }, { v: stats.scheduled, l: "SCHEDULED" },
            { v: stats.total_posts, l: "TOTAL" },
          ]}
          note={stats.posts_today
            ? `${stats.posts_today} post${stats.posts_today === 1 ? "" : "s"} going out today.`
            : stats.drafts
              ? `${stats.drafts} post${stats.drafts === 1 ? "" : "s"} still in draft — nothing goes out today.`
              : "Nothing goes out today."} />
        <Pipeline title="Clipping" kicker="Artist fan-out" icon={Scissors}
          tint="bg-[var(--chart-2)]/14 text-[var(--chart-2)]"
          cells={[
            { v: stats.artists, l: "ARTISTS" }, { v: stats.variations, l: "VARIATIONS" },
            { v: stats.clips, l: "CLIPS" }, { v: stats.clip_posts, l: "POSTED" },
            { v: stats.clip_scheduled, l: "SCHEDULED" },
          ]}
          note={stats.variations ? `${stats.variations} variation${stats.variations === 1 ? "" : "s"} fanning out.` : "No variations yet — a clip needs one to fan out."} />
      </div>

      {/* chart + rail */}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[1fr_372px]">
        <div className="flex min-w-0 flex-col gap-4">
          <Card>
            <div className="flex items-start justify-between px-5 pt-[18px]">
              <div>
                <div className="text-[14.5px] font-bold text-foreground">Messages Sent</div>
                <div className="mt-[3px] text-[11.5px] text-subtle">Daily, {span}</div>
              </div>
              <CardMenu />
            </div>
            <div className="flex flex-wrap items-end gap-[22px] px-5 pb-[18px] pt-3.5">
              <div className="min-w-[150px] flex-none">
                <div className="text-[34px] font-extrabold leading-[1.05] tracking-[-0.04em] tabular-nums text-foreground">{n(periodTotal)}</div>
                {wow && (
                  <div className="mt-[9px] flex flex-wrap items-center gap-2">
                    <span className={`inline-flex items-center gap-[3px] rounded-full px-[7px] py-[2.5px] text-[11.5px] font-bold ${
                      wow.dir === "up" ? "bg-good/12 text-good" : "bg-bad/12 text-bad"}`}>
                      {wow.dir === "up" ? <ChevronUp className="h-[11px] w-[11px]" strokeWidth={3} />
                                        : <ChevronDown className="h-[11px] w-[11px]" strokeWidth={3} />}{wow.text}
                    </span>
                    <span className="text-[11.5px] text-subtle">vs. previous {days} days</span>
                  </div>
                )}
              </div>
              <SendsChart data={sum?.daily_sends ?? []} />
            </div>

            {/* targets by state */}
            <div className="mx-5 mb-[18px] rounded-[14px] border border-border px-4 py-[15px]">
              <div className="mb-[13px] flex items-center justify-between">
                <span className="text-[13px] font-bold text-foreground">Targets by state</span>
                <CardMenu />
              </div>
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                {segs.map((s) => (
                  <div key={s.l}>
                    <div className="mb-[3px] flex items-center gap-[7px]">
                      <span className="h-[9px] w-[9px] flex-none rounded-[3px]" style={{ background: s.c }} />
                      <span className="text-[19px] font-extrabold tracking-[-0.03em] tabular-nums text-foreground">{n(s.v)}</span>
                    </div>
                    <div className="mb-[9px] text-[11.5px] text-subtle">{s.l}</div>
                    <div className="h-[5px] overflow-hidden rounded-full bg-border">
                      <i className="block h-full rounded-full" style={{ width: `${(s.v / segTotal) * 100}%`, background: s.c }} />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </Card>

          {/* top campaigns */}
          <Card>
            <div className="flex items-start justify-between px-5 pb-3.5 pt-[18px]">
              <span className="text-[14.5px] font-bold text-foreground">Top Campaigns</span>
              <CardMenu />
            </div>
            <div className="overflow-x-auto px-1.5 pb-2">
              <table className="w-full border-collapse">
                <thead>
                  <tr className="border-b border-border">
                    {([["ID", "w-[62px]"], ["Name", ""], ["Sent", "w-[96px]"],
                       ["Progress", "w-[170px]"], ["Status", "w-[118px]"]] as const).map(([h, w]) => (
                      <th key={h} className={`px-3.5 pb-2.5 text-left text-[10.5px] font-bold uppercase tracking-[0.07em] text-subtle ${w}`}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {top.length === 0 && (
                    <tr><td colSpan={5} className="px-3.5 py-8 text-center text-sm text-muted-foreground">No campaigns yet.</td></tr>
                  )}
                  {top.map((c) => {
                    // Against *sent*, not `progress`. The server's progress is
                    // processed/total, which counts skipped and failed as
                    // done — so a campaign that delivered 763 of 1,000 read
                    // as 100%, directly contradicting the Sent column beside it.
                    const total = c.total_targets ?? 0;
                    const pct = total ? (((c.successful_count ?? 0) / total) * 100).toFixed(1) : "0.0";
                    const tone = c.status === "completed" ? "bg-good/11 text-good"
                      : c.status === "paused" ? "bg-warn/12 text-warn"
                      : c.status === "running" ? "bg-[var(--chart-1)]/15 text-[var(--chart-1)]"
                      : "bg-bad/11 text-bad";
                    return (
                      <tr key={c.id} className="border-b border-line-2 text-[13px] last:border-0 hover:bg-secondary">
                        <td className="px-3.5 py-[13px] font-mono text-[12.5px] tabular-nums text-subtle">#{c.id}</td>
                        <td className="px-3.5 py-[13px]">
                          <div className="flex min-w-0 items-center gap-[11px]">
                            <span className="grid h-[31px] w-[31px] flex-none place-items-center rounded-[9px] border border-border bg-secondary text-foreground">
                              <PlatformIcon platform={c.platform} />
                            </span>
                            <span className="truncate text-[13px] font-semibold text-foreground">{c.name}</span>
                          </div>
                        </td>
                        <td className="px-3.5 py-[13px] font-mono text-[12.5px] font-bold tabular-nums text-foreground">{n(c.successful_count)}</td>
                        <td className="px-3.5 py-[13px]">
                          <div className="flex min-w-[132px] items-center gap-[9px]">
                            <div className="h-[5px] flex-1 overflow-hidden rounded-full bg-border">
                              <i className="block h-full rounded-full" style={{ width: `${pct}%`, background: "var(--chart-1)" }} />
                            </div>
                            <span className="w-[38px] text-right text-[11.5px] font-bold tabular-nums text-muted-foreground">{pct}%</span>
                          </div>
                        </td>
                        <td className="px-3.5 py-[13px]">
                          <span className={`inline-flex items-center gap-[5px] rounded-full px-[9px] py-[3px] text-[11px] font-bold capitalize ${tone}`}>
                            <i className="h-[5px] w-[5px] rounded-full bg-current" />{c.status}
                          </span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </Card>
        </div>

        {/* right rail */}
        <div className="flex flex-col gap-4">
          <Card>
            <div className="flex items-start justify-between px-5 pb-1 pt-[18px]">
              <div>
                <div className="text-[14.5px] font-bold text-foreground">Most Active Day</div>
                <div className="mt-[3px] text-[11.5px] text-subtle">
                  {wdComplete ? "Sends by weekday, all time"
                              : `Weekday split of ${n(wdTotal)} timestamped sends`}
                </div>
              </div>
              <CardMenu />
            </div>
            <div className="flex h-[168px] items-end justify-between gap-2 px-5 pb-3 pt-1.5">
              {DOW.map((d) => {
                const v = sum?.weekday_sends?.[d] ?? 0;
                const on = v === wdMax && v > 0;
                return (
                  <div key={d} className="group flex h-full flex-1 flex-col items-center justify-end" title={`${d}: ${n(v)} sends`}>
                    <span className={`mb-1.5 text-[11.5px] font-extrabold tabular-nums opacity-0 transition-opacity group-hover:opacity-100 ${on ? "opacity-100 text-foreground" : "text-muted-foreground"}`}>{n(v)}</span>
                    <span className={`w-full max-w-[34px] rounded-[7px] transition-colors ${on ? "bg-lime" : "bg-border group-hover:bg-[#cfd5e0] dark:group-hover:bg-[#333a48]"}`}
                      style={{ height: `${Math.max((v / wdMax) * 100, 5)}%` }} />
                    <span className={`mt-[9px] text-[11.5px] ${on ? "font-bold text-foreground" : "font-semibold text-subtle"}`}>{d}</span>
                  </div>
                );
              })}
            </div>
          </Card>

          <Card>
            <div className="flex items-start justify-between px-5 pt-[18px]">
              <div>
                <div className="text-[14.5px] font-bold text-foreground">Delivery Rate</div>
                <div className="mt-[3px] text-[11.5px] text-subtle">Sent vs. attempted, all time</div>
              </div>
              <CardMenu />
            </div>
            <div className="flex flex-col items-center px-5 pb-5 pt-1">
              <Gauge pct={sum?.delivery_rate ?? 0} />
              <p className="mt-1.5 text-center text-[11.5px] leading-[1.4] text-subtle">
                <b className="font-bold tabular-nums text-muted-foreground">{n(sum?.sent)}</b> delivered of{" "}
                <b className="font-bold tabular-nums text-muted-foreground">{n(sum?.attempted)}</b> attempted
              </p>
              <Link href="/outreach"
                className="mt-3 inline-block rounded-[10px] border border-border bg-card px-4.5 py-2 text-[12.5px] font-semibold text-foreground transition-colors hover:bg-secondary">
                Show details
              </Link>
            </div>
          </Card>

          <Card>
            <div className="flex items-start justify-between px-5 pt-[18px]">
              <span className="text-[14.5px] font-bold text-foreground">AI Assistant</span>
              <button aria-label="Expand assistant"
                className="grid h-[26px] w-[26px] flex-none place-items-center rounded-[7px] text-subtle transition-colors hover:bg-secondary hover:text-foreground">
                <Maximize2 className="h-[17px] w-[17px]" />
              </button>
            </div>
            <div className="flex flex-col items-center px-5 pb-5 pt-[18px] text-center">
              {/* The assistant's mark: a four-point star with a smaller one
                  trailing it, in the brand gradient, breathing slowly. */}
              <span className="mb-[11px] mt-0.5 grid h-[46px] w-[46px] place-items-center">
                <svg viewBox="0 0 24 24" fill="none" aria-hidden
                  className="animate-twinkle h-[38px] w-[38px] drop-shadow-[0_3px_10px_rgba(138,138,0,0.45)] dark:drop-shadow-[0_3px_12px_rgba(215,215,0,0.5)]">
                  <defs>
                    <linearGradient id="aiStar" x1="0" y1="0" x2="1" y2="1">
                      <stop offset="0%" stopColor="var(--lime)" />
                      <stop offset="100%" stopColor="var(--chart-1)" />
                    </linearGradient>
                  </defs>
                  <path d="M12 1.6c.5 4.9 3.9 8.3 8.8 8.8v.1c-4.9.5-8.3 3.9-8.8 8.8h-.1c-.5-4.9-3.9-8.3-8.8-8.8v-.1c4.9-.5 8.3-3.9 8.8-8.8z" fill="url(#aiStar)" />
                  <path d="M19.4 16.2c.2 1.7 1.3 2.9 3 3.1v.05c-1.7.2-2.8 1.4-3 3.1h-.05c-.2-1.7-1.3-2.9-3-3.1v-.05c1.7-.2 2.8-1.4 3-3.1z" fill="var(--lime)" opacity=".75" />
                </svg>
              </span>
              <h3 className="mb-1 text-[14.5px] font-bold text-foreground">Ask about your campaigns</h3>
              <p className="mb-[15px] text-xs leading-[1.5] text-subtle">
                “Which campaign has the best delivery rate?”<br />“Why did sends drop this week?”
              </p>
              <div className="flex w-full items-center gap-[9px] rounded-[13px] border border-border bg-secondary py-2 pl-[13px] pr-[9px]">
                <input placeholder="Ask me anything..." aria-label="Ask the AI assistant"
                  className="min-w-0 flex-1 bg-transparent text-[12.5px] text-foreground outline-none placeholder:text-subtle" />
                <Mic className="h-4 w-4 flex-none text-subtle" />
                <button aria-label="Send" className="grid h-[31px] w-[31px] flex-none place-items-center rounded-[9px] bg-lime">
                  <ArrowUp className="h-[15px] w-[15px] text-black" strokeWidth={2.4} />
                </button>
              </div>
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}

/** The dial: ticks rather than a solid arc, so the value is countable. */
function Gauge({ pct }: { pct: number }) {
  const N = 54, cx = 120, cy = 118, r1 = 58, r2 = 88;
  return (
    <div className="relative w-[240px]">
      <svg viewBox="0 0 240 142" className="block w-full overflow-visible" role="img"
        aria-label={`Delivery rate ${(pct * 100).toFixed(1)} percent.`}>
        {Array.from({ length: N }, (_, i) => {
          const a = Math.PI + (i / (N - 1)) * Math.PI;
          const on = i / (N - 1) <= pct;
          return (
            <line key={i}
              x1={cx + Math.cos(a) * r1} y1={cy + Math.sin(a) * r1}
              x2={cx + Math.cos(a) * r2} y2={cy + Math.sin(a) * r2}
              stroke={on ? "var(--chart-1)" : "var(--border)"}
              strokeWidth={3.2} strokeLinecap="round"
              opacity={on ? 0.45 + 0.55 * (i / (N - 1)) : 1} />
          );
        })}
      </svg>
      <div className="absolute inset-x-0 top-[56%] text-center">
        <div className="text-[22px] font-extrabold leading-[1.1] tracking-[-0.03em] text-foreground">
          {(pct * 100).toFixed(1)}%
        </div>
      </div>
    </div>
  );
}

/** Platform marks in ink, matching the sidebar's monochrome icons. */
function PlatformIcon({ platform }: { platform: string }) {
  const p = (platform || "").toLowerCase();
  if (p === "instagram")
    return (
      <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth={1.9} aria-hidden>
        <rect x="3" y="3" width="18" height="18" rx="5" /><circle cx="12" cy="12" r="4" />
        <circle cx="17.3" cy="6.7" r="1.1" fill="currentColor" stroke="none" />
      </svg>
    );
  if (p === "x" || p === "twitter")
    return (
      <svg viewBox="0 0 24 24" className="h-4 w-4" fill="currentColor" aria-hidden>
        <path d="M18.9 2H22l-7 8 8.2 12h-6.4l-5-7.3L5.9 22H2.8l7.5-8.6L2.5 2h6.6l4.5 6.6zm-1.1 18h1.7L7.3 3.8H5.5z" />
      </svg>
    );
  return (
    <svg viewBox="0 0 24 24" className="h-4 w-4" fill="currentColor" aria-hidden>
      <path d="M21 8.6a6.6 6.6 0 0 1-4.6-1.9v7.9a6.2 6.2 0 1 1-5.4-6.1v2.9a3.3 3.3 0 1 0 2.5 3.2V2h2.9A6.6 6.6 0 0 0 21 6.7z" />
    </svg>
  );
}
