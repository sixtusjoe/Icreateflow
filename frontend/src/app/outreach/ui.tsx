"use client";

import type { LucideIcon } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * Section heading icon. Drawn as a bare glyph in `text-foreground` rather
 * than reversed out of a filled tile, so it inverts with the theme instead
 * of staying a hard black or white block in one of the two.
 */
export function PageIcon({ icon: Icon }: { icon: LucideIcon }) {
  return <Icon className="h-7 w-7 shrink-0 text-foreground" strokeWidth={1.75} />;
}

/**
 * On/off switch.
 *
 * Laid out with padding and a flex child rather than absolute offsets: the
 * track's 2px padding is the gap on both sides, so the knob can't end up
 * closer to one edge than the other. The knob stays white in both themes —
 * `bg-background` would render it near-black against the green in dark mode.
 */
export function Toggle({
  checked,
  onChange,
  label,
  disabled,
}: {
  checked: boolean;
  onChange: () => void;
  label: string;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={onChange}
      className={cn(
        "inline-flex h-6 w-11 shrink-0 items-center rounded-full p-0.5 transition-colors",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-foreground",
        "focus-visible:ring-offset-2 focus-visible:ring-offset-background",
        "disabled:cursor-not-allowed disabled:opacity-50",
        checked ? "bg-emerald-500" : "bg-muted-foreground/30",
      )}
    >
      <span
        className={cn(
          "h-5 w-5 rounded-full bg-white shadow-sm transition-transform duration-200",
          checked ? "translate-x-5" : "translate-x-0",
        )}
      />
    </button>
  );
}

/** Matches the input styling used across the Clipping pages. */
export const inputClass =
  "w-full rounded-lg border border-border bg-background px-4 py-2.5 text-base sm:text-sm outline-none transition-colors focus:border-foreground placeholder:text-muted-foreground";

const TONES: Record<string, string> = {
  // Campaign
  draft: "bg-muted text-muted-foreground",
  running: "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400",
  paused: "bg-amber-500/15 text-amber-600 dark:text-amber-400",
  completed: "bg-blue-500/15 text-blue-600 dark:text-blue-400",
  stopped: "bg-muted text-muted-foreground",
  // Target / job
  queued: "bg-muted text-muted-foreground",
  processing: "bg-blue-500/15 text-blue-600 dark:text-blue-400",
  sent: "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400",
  succeeded: "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400",
  failed: "bg-destructive/15 text-destructive",
  skipped: "bg-muted text-muted-foreground",
  cancelled: "bg-muted text-muted-foreground",
  // Account
  idle: "bg-muted text-muted-foreground",
  active: "bg-blue-500/15 text-blue-600 dark:text-blue-400",
  error: "bg-destructive/15 text-destructive",
};

export function StatusPill({ status, className }: { status: string; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium capitalize",
        TONES[status] ?? "bg-muted text-muted-foreground",
        className,
      )}
    >
      {status}
    </span>
  );
}

/**
 * Two-tone progress: the filled portion is split into delivered (green)
 * and everything else that finished (muted), so a run that is "80% done
 * but mostly failing" reads as exactly that at a glance.
 */
export function ProgressBar({
  processed,
  total,
  successful,
}: {
  processed: number;
  total: number;
  successful: number;
}) {
  const pct = total > 0 ? Math.min(100, (processed / total) * 100) : 0;
  const successPct = total > 0 ? Math.min(100, (successful / total) * 100) : 0;
  return (
    <div>
      <div className="flex items-center justify-between text-xs text-muted-foreground">
        <span className="tabular-nums">
          Processed: {processed.toLocaleString()} / {total.toLocaleString()}
        </span>
        <span className="tabular-nums">{pct.toFixed(0)}%</span>
      </div>
      <div className="mt-1.5 h-2 w-full overflow-hidden rounded-full bg-muted">
        <div className="flex h-full" style={{ width: `${pct}%` }}>
          <div
            className="h-full bg-emerald-500"
            style={{ width: pct > 0 ? `${(successPct / pct) * 100}%` : "0%" }}
          />
          <div className="h-full flex-1 bg-foreground/40" />
        </div>
      </div>
    </div>
  );
}

export function relativeTime(value: string | null | undefined): string {
  if (!value) return "—";
  const then = new Date(value).getTime();
  if (Number.isNaN(then)) return "—";
  const seconds = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return new Date(value).toLocaleDateString();
}

export function apiErrorMessage(error: unknown, fallback: string): string {
  const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data
    ?.detail;
  if (typeof detail === "string") return detail;
  // The start/resume preflight returns {"errors": [...]}.
  const errors = (detail as { errors?: string[] })?.errors;
  if (Array.isArray(errors) && errors.length) return errors.join(" · ");
  return fallback;
}
