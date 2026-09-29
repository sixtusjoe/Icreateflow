"use client";

import { Info } from "lucide-react";

/**
 * The small pieces every admin page uses.
 *
 * Two of them exist to keep the pages honest. `SampleBanner` marks a card
 * whose figures are invented, and `NoEndpoint` marks a control that is
 * drawn but has nothing behind it. Both are deliberate: a screen that
 * quietly omits what it cannot do teaches you it cannot be done, and a
 * screen that pretends is worse. Tagging is how the design says "this is
 * the work" without shipping a lie.
 */

/** A control drawn for a thing the backend cannot do yet. */
export function NoEndpoint({ soft, children = "no endpoint" }: { soft?: boolean; children?: React.ReactNode }) {
  return (
    <span
      className={`ml-[7px] inline-block rounded-full border px-[7px] py-px align-[1px] text-[9.5px] font-bold uppercase tracking-[0.05em] ${
        soft
          ? "border-border bg-secondary text-subtle"
          : "border-warn/30 bg-warn/12 text-warn"
      }`}
    >
      {children}
    </span>
  );
}

/** The strip over a page or card whose content is invented. */
export function SampleBanner({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex items-start gap-2.5 rounded-[13px] border border-warn/25 bg-warn/[0.08] px-3.5 py-3 text-[11.5px] leading-[1.6] text-muted-foreground">
      <Info className="mt-px h-[15px] w-[15px] flex-none text-warn" />
      <span>{children}</span>
    </div>
  );
}

/** A small heading inside a card body. */
export function Sub({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={`mb-2.5 text-[10.5px] font-bold uppercase tracking-[0.07em] text-subtle ${className}`}>
      {children}
    </div>
  );
}

/** One figure with a label under it, on the page's own surface. */
export function Stat({
  value,
  label,
  note,
  tone,
}: {
  value: React.ReactNode;
  label: string;
  note?: React.ReactNode;
  tone?: "warn";
}) {
  const zero = value === 0 || value === "0";
  return (
    <div className="rounded-[14px] border border-border bg-card px-4 py-3.5 shadow-card">
      <div
        className={`text-[24px] font-extrabold leading-[1.15] tracking-[-0.035em] tabular-nums ${
          tone === "warn" ? "text-warn" : zero ? "text-subtle" : "text-foreground"
        }`}
      >
        {value}
      </div>
      <div className="mt-0.5 text-[12px] font-bold text-foreground">{label}</div>
      {note ? <div className="mt-0.5 text-[10.5px] text-subtle">{note}</div> : null}
    </div>
  );
}

/** The person's initial, as an avatar. */
export function Initial({ name, size = 36 }: { name: string; size?: number }) {
  return (
    <span
      className="grid flex-none place-items-center rounded-[11px] bg-[linear-gradient(140deg,#ffd7a8,#f6a97a)] font-extrabold text-[#7a4a1e]"
      style={{ width: size, height: size, fontSize: Math.round(size * 0.42) }}
    >
      {(name || "?").charAt(0).toUpperCase()}
    </span>
  );
}

/** Admin or user, as a pill. */
export function RolePill({ role }: { role: string }) {
  return (
    <span
      className={`inline-block rounded-full border px-[9px] py-[3px] text-[11px] font-semibold ${
        role === "admin"
          ? "border-lime/40 bg-lime/[0.18] text-foreground"
          : "border-border bg-secondary text-muted-foreground"
      }`}
    >
      {role.charAt(0).toUpperCase() + role.slice(1)}
    </span>
  );
}

/** users.status → the tone the kit's Tag wears. */
export const STATUS_TONE: Record<string, "done" | "stop" | "pause"> = {
  active: "done",
  suspended: "stop",
  pending: "pause",
};
