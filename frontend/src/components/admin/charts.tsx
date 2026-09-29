"use client";

import { useRef, useState } from "react";

/**
 * The marks the admin pages draw.
 *
 * Two rules hold across all of them:
 *
 *  - Colour on these charts is a *state*, never an identity. Green is a
 *    thing being where it should be, red is a thing being down, amber is a
 *    thing worth a look, and slate is a figure that is none of those — how
 *    many posts are scheduled is information, not a verdict. Every mark
 *    also prints its own number, so colour is never the only thing
 *    carrying the meaning.
 *  - Axis labels and tooltips are HTML, not SVG text. These charts stretch
 *    to their card with `preserveAspectRatio="none"`, which would stretch
 *    any glyph inside them by the same factor.
 */

export type Tone = "good" | "down" | "warn" | "plain";

const STROKE: Record<Tone, string> = {
  good: "var(--good)",
  down: "var(--bad)",
  warn: "var(--warn)",
  plain: "var(--chart-1)",
};

export const pc = (a: number, b: number) => (b ? (a / b) * 100 : 0);
export const num = (v: number | null | undefined) => (v ?? 0).toLocaleString();

/**
 * The small chart on a tile: the same shape as the big one, no furniture.
 *
 * A flat line is a real answer — one account, created in April, is flat
 * from May onward — so a series that never moves draws a rule across the
 * middle. Scaling it to its own maximum pinned it to the ceiling and
 * filled the whole tile, which read as 100% of something rather than as
 * "unchanged".
 */
export function Mini({
  values,
  tone = "plain",
  w = 150,
  h = 42,
  className = "",
}: {
  values: number[];
  tone?: Tone;
  w?: number;
  h?: number;
  className?: string;
}) {
  const stroke = STROKE[tone];
  if (!values.length || Math.max(...values) === 0) {
    return (
      <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" aria-hidden
           className={`block w-full ${className}`} style={{ height: h }}>
        <line x1="0" x2={w} y1={h - 3} y2={h - 3} stroke={stroke} strokeWidth="1.6"
              strokeDasharray="3 3" opacity="0.5" vectorEffect="non-scaling-stroke" />
      </svg>
    );
  }
  const step = w / Math.max(1, values.length - 1);
  const flat = Math.min(...values) === Math.max(...values);
  const top = Math.max(...values) * 1.12;
  const pts = values.map((v, i) => [i * step, flat ? h * 0.46 : h - 3 - (v / top) * (h - 8)] as const);
  const line = pts.map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(1)} ${y.toFixed(1)}`).join(" ");
  const [lx, ly] = pts[pts.length - 1];
  const id = `mini-${tone}`;
  return (
    <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" role="img"
         className={`block w-full ${className}`} style={{ height: h }}
         aria-label={`${values[0]} at the start of the window, ${values[values.length - 1]} now`}>
      <defs>
        <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={stroke} stopOpacity="0.20" />
          <stop offset="100%" stopColor={stroke} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={`${line} L${w} ${h} L0 ${h} Z`} fill={`url(#${id})`} />
      <path d={line} fill="none" stroke={stroke} strokeWidth="1.8" strokeLinejoin="round"
            vectorEffect="non-scaling-stroke" />
      <circle cx={lx} cy={ly} r="2.6" fill={stroke} />
    </svg>
  );
}

/** A bare line under a KPI. No axis, no labels — it is a direction, not a reading. */
export function Spark({ values, h = 34 }: { values: number[]; h?: number }) {
  const w = 132;
  const top = Math.max(...values, 1);
  const step = w / Math.max(1, values.length - 1);
  const d = values
    .map((v, i) => `${i === 0 ? "M" : "L"}${(i * step).toFixed(1)} ${(h - (v / top) * (h - 4) - 2).toFixed(1)}`)
    .join(" ");
  return (
    <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" aria-hidden
         className="mt-2.5 block w-full" style={{ height: h }}>
      <path d={d} fill="none" stroke="var(--chart-1)" strokeWidth="1.6" strokeLinejoin="round"
            vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

/**
 * This window against the one before it, with a crosshair on hover.
 *
 * The prior period is a dashed line rather than a second colour: it is the
 * same measure, not a second series, and two hues would say otherwise.
 */
export function TwoLine({
  cur,
  prev,
  labels,
  curLabel,
  prevLabel,
  seriesName,
}: {
  cur: number[];
  prev: number[];
  labels: string[];
  curLabel: string;
  prevLabel: string;
  seriesName: string;
}) {
  const w = 700;
  const h = 168;
  const pad = 22;
  const plot = useRef<HTMLDivElement>(null);
  const [at, setAt] = useState<number | null>(null);

  const raw = Math.max(Math.max(...cur, 0), Math.max(...prev, 0)) || 1;
  const stepsize = 10 ** (String(Math.trunc(raw)).length - 1);
  const top = (Math.trunc(raw / stepsize) + 1) * stepsize;
  const step = (w - pad * 2) / Math.max(1, cur.length - 1);

  const path = (vals: number[]) =>
    vals
      .map((v, i) => `${i === 0 ? "M" : "L"}${(pad + i * step).toFixed(1)} ${(h - pad - (v / top) * (h - pad * 2)).toFixed(1)}`)
      .join(" ");

  const curPath = path(cur);
  const marks = [0, Math.floor(labels.length / 3), Math.floor((2 * labels.length) / 3), labels.length - 1];
  const day = (iso: string) =>
    new Date(iso + "T00:00:00").toLocaleDateString(undefined, { day: "numeric", month: "short" });

  const onMove = (e: React.MouseEvent) => {
    const box = plot.current?.getBoundingClientRect();
    if (!box) return;
    const x = ((e.clientX - box.left) / box.width) * w;
    const i = Math.round((x - pad) / step);
    setAt(i >= 0 && i < cur.length ? i : null);
  };

  const left = at === null ? 0 : ((pad + at * step) / w) * 100;
  const tipTop = at === null ? 0 : ((h - pad - (cur[at] / top) * (h - pad * 2)) / h) * 100;

  return (
    <>
      <div className="mb-3 flex flex-wrap items-center gap-x-5 gap-y-1.5 text-[11.5px] text-subtle">
        <span className="flex items-center gap-1.5">
          <i className="h-[3px] w-3.5 rounded-full bg-[var(--chart-1)]" />
          {curLabel}
          <b className="font-bold tabular-nums text-foreground">{num(cur.reduce((a, b) => a + b, 0))}</b>
        </span>
        <span className="flex items-center gap-1.5">
          <i className="h-[3px] w-3.5 rounded-full bg-subtle/60"
             style={{ backgroundImage: "repeating-linear-gradient(90deg,currentColor 0 4px,transparent 4px 7px)" }} />
          {prevLabel}
          <b className="font-bold tabular-nums text-foreground">{num(prev.reduce((a, b) => a + b, 0))}</b>
        </span>
      </div>
      <div className="flex gap-2">
        <div className="relative w-9 flex-none" style={{ height: h }}>
          {[0, 1, 2, 3, 4].map((k) => (
            <span key={k} className="absolute right-0 translate-y-1/2 text-[10px] tabular-nums text-subtle"
                  style={{ bottom: `${(((k / 4) * (h - pad * 2) + pad) / h) * 100}%` }}>
              {num(Math.round((top * k) / 4))}
            </span>
          ))}
        </div>
        <div
          ref={plot}
          className="relative min-w-0 flex-1"
          onMouseMove={onMove}
          onMouseLeave={() => setAt(null)}
        >
          <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" role="img" className="block w-full"
               style={{ height: h }}
               aria-label={`${seriesName} per day for ${curLabel.toLowerCase()} against ${prevLabel.toLowerCase()}, peaking at ${num(Math.max(...cur))}`}>
            <g stroke="var(--line-2)" strokeWidth="1" vectorEffect="non-scaling-stroke">
              {[0, 1, 2, 3, 4].map((k) => {
                const y = h - pad - (k / 4) * (h - pad * 2);
                return <line key={k} x1={pad} x2={w - pad} y1={y} y2={y} />;
              })}
            </g>
            <defs>
              <linearGradient id="twoline" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="var(--chart-1)" stopOpacity="0.18" />
                <stop offset="100%" stopColor="var(--chart-1)" stopOpacity="0" />
              </linearGradient>
            </defs>
            <path d={`${curPath} L${(pad + (cur.length - 1) * step).toFixed(1)} ${h - pad} L${pad} ${h - pad} Z`}
                  fill="url(#twoline)" />
            <path d={path(prev)} fill="none" stroke="var(--subtle)" strokeWidth="1.6" strokeDasharray="4 4"
                  vectorEffect="non-scaling-stroke" opacity="0.75" />
            <path d={curPath} fill="none" stroke="var(--chart-1)" strokeWidth="2" strokeLinejoin="round"
                  vectorEffect="non-scaling-stroke" />
          </svg>
          {at !== null && (
            <>
              <span className="pointer-events-none absolute top-0 w-px bg-border"
                    style={{ left: `${left}%`, height: h }} />
              <span className="pointer-events-none absolute h-2 w-2 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-card bg-[var(--chart-1)]"
                    style={{ left: `${left}%`, top: `${tipTop}%` }} />
              <div className="pointer-events-none absolute z-10 -translate-x-1/2 -translate-y-[130%] whitespace-nowrap rounded-[10px] border border-border bg-popover px-2.5 py-1.5 text-[11px] shadow-lg"
                   style={{ left: `${left}%`, top: `${tipTop}%` }}>
                <b className="block font-bold text-foreground">{day(labels[at])}</b>
                <span className="mt-0.5 flex items-center gap-1.5 text-subtle">
                  <i className="h-[3px] w-3 rounded-full bg-[var(--chart-1)]" />
                  {seriesName}
                  <b className="font-bold tabular-nums text-foreground">{num(cur[at])}</b>
                </span>
              </div>
            </>
          )}
          <div className="relative mt-1 h-4">
            {marks.map((i) => (
              <span key={i}
                    className="absolute -translate-x-1/2 text-[10px] text-subtle first:translate-x-0"
                    style={{ left: `${((pad + i * step) / w) * 100}%` }}>
                {day(labels[i])}
              </span>
            ))}
          </div>
        </div>
      </div>
    </>
  );
}

/** A labelled row of bars. `share` adds each row's percentage of the total. */
export function Bars({
  rows,
  unit = "",
  share = false,
  labelWidth = 92,
  toneOf,
}: {
  rows: [string, number][];
  unit?: string;
  share?: boolean;
  labelWidth?: number;
  toneOf?: (key: string) => Tone;
}) {
  const top = Math.max(...rows.map(([, v]) => v), 1);
  const total = rows.reduce((a, [, v]) => a + v, 0) || 1;
  return (
    <div className="flex flex-col gap-[7px]">
      {rows.map(([k, v]) => (
        <div key={k} className="grid items-center gap-2.5"
             style={{ gridTemplateColumns: `${labelWidth}px 1fr 58px${share ? " 34px" : ""}` }}>
          <span className="truncate text-[11.5px] text-muted-foreground">{k}</span>
          <span className="h-[7px] overflow-hidden rounded-full bg-muted">
            <i className="block h-full rounded-full"
               style={{ width: `${(v / top) * 100}%`, background: STROKE[toneOf ? toneOf(k) : "plain"] }} />
          </span>
          <span className="text-right text-[11.5px] font-semibold tabular-nums text-foreground">
            {num(v)}{unit}
          </span>
          {share && (
            <span className="text-right text-[11px] tabular-nums text-subtle">{pc(v, total).toFixed(0)}%</span>
          )}
        </div>
      ))}
    </div>
  );
}

/** One bar, one segment per category, with 2px of surface between them. */
export function Stack({ rows, label }: { rows: [string, number][]; label?: (k: string) => string }) {
  const total = rows.reduce((a, [, v]) => a + v, 0) || 1;
  const hue = ["var(--chart-1)", "var(--chart-2)", "var(--chart-3)", "var(--chart-4)", "var(--chart-5)"];
  return (
    <>
      <div className="flex h-[26px] gap-[2px] overflow-hidden rounded-[8px]">
        {rows.map(([k, v], i) => (
          <i key={k} title={`${label ? label(k) : k}: ${num(v)}`}
             style={{ width: `${pc(v, total).toFixed(2)}%`, background: hue[i % hue.length] }} />
        ))}
      </div>
      <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1.5">
        {rows.map(([k, v], i) => (
          <span key={k} className="flex items-center gap-1.5 text-[11.5px] text-muted-foreground">
            <i className="h-2 w-2 rounded-[3px]" style={{ background: hue[i % hue.length] }} />
            {label ? label(k) : k}
            <b className="font-bold tabular-nums text-foreground">{num(v)}</b>
            <em className="not-italic text-subtle">{pc(v, total).toFixed(0)}%</em>
          </span>
        ))}
      </div>
    </>
  );
}

/** CPU, memory, disk. Amber from 70%, red from 85% — the number is printed either way. */
export function Gauge({ label, pct: value, note }: { label: string; pct: number | null; note: string }) {
  if (value === null || value === undefined) {
    return (
      <div className="border-b border-line-2 py-2.5 last:border-b-0">
        <div className="flex items-baseline justify-between text-[12px]">
          <span className="font-semibold text-foreground">{label}</span>
          <b className="text-subtle">not reported</b>
        </div>
        <div className="mt-1.5 text-[10.5px] text-subtle">
          psutil is not installed on this box, so nothing measures it.
        </div>
      </div>
    );
  }
  const colour = value >= 85 ? "var(--bad)" : value >= 70 ? "var(--warn)" : "var(--chart-1)";
  return (
    <div className="border-b border-line-2 py-2.5 last:border-b-0">
      <div className="flex items-baseline justify-between text-[12px]">
        <span className="font-semibold text-foreground">{label}</span>
        <b className="tabular-nums" style={{ color: colour }}>{value.toFixed(0)}%</b>
      </div>
      <div className="mt-1.5 h-[7px] overflow-hidden rounded-full bg-muted">
        <i className="block h-full rounded-full" style={{ width: `${value}%`, background: colour }} />
      </div>
      <div className="mt-1 text-[10.5px] text-subtle">{note}</div>
    </div>
  );
}

/**
 * A measure narrowing in steps.
 *
 * One hue in three steps, not three colours: these are the same quantity
 * at three points, and a categorical palette would claim they are three
 * different things.
 */
export function Funnel({ rows }: { rows: [string, number, string][] }) {
  const first = rows[0]?.[1] || 1;
  const fade = ["1", "0.72", "0.48"];
  return (
    <div className="flex flex-col gap-3.5">
      {rows.map(([label, v, note], i) => (
        <div key={label}>
          <div className="flex items-baseline justify-between">
            <b className="text-[12.5px] font-bold text-foreground">{label}</b>
            <span className="text-[12.5px] font-semibold tabular-nums text-foreground">{num(v)}</span>
          </div>
          <div className="mt-1.5 h-[9px] overflow-hidden rounded-full bg-muted">
            <i className="block h-full rounded-full"
               style={{ width: `${pc(v, first).toFixed(2)}%`, background: "var(--chart-1)", opacity: fade[i] }} />
          </div>
          <div className="mt-1 text-[10.5px] text-subtle">
            {pc(v, first).toFixed(1)}% of every target · {note}
          </div>
        </div>
      ))}
    </div>
  );
}
