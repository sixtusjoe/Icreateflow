"use client";

/**
 * The pieces every outreach page is built from.
 *
 * These were drawn as CSS classes in the preview kit (`.card`, `.ch-head`,
 * `.tag`, `.chip`, `.mini`, `.bar2`); here they are components so the four
 * pages cannot drift apart the way four copies of a class list would.
 *
 * Two rules the preview taught us, and neither is optional:
 *
 *  - **Radius is always literal.** The theme scales its named radii
 *    (`--radius-xl` is `calc(var(--radius) * 1.4)`, so `rounded-xl` is
 *    16.8px, not 12px). Every radius below is an arbitrary value.
 *  - **Weights are snapped.** The design was drawn against a static Geist,
 *    which rounds 550/650/750 up to 600/700/800. Our variable font would
 *    render the true weight and set ~1px narrower, so we ask for what the
 *    design actually shows.
 */

import Link from "next/link";
import { useEffect, useRef, useState , useLayoutEffect } from "react";
import { createPortal } from "react-dom";
import { MoreHorizontal } from "lucide-react";

export const n = (v: number | null | undefined) => (v ?? 0).toLocaleString();

/* ------------------------------------------------------------------ */
/* platforms                                                           */
/* ------------------------------------------------------------------ */

export const PLATFORMS = ["instagram", "tiktok", "x"] as const;
export type Platform = (typeof PLATFORMS)[number];

/** Proper names, not `.title()` — that turns "tiktok" into "Tiktok". */
export const PLATFORM_LABEL: Record<string, string> = {
  instagram: "Instagram",
  tiktok: "TikTok",
  x: "X",
  youtube: "YouTube",
  facebook: "Facebook",
};

export function PlatformIcon({ platform, className = "h-4 w-4" }: { platform: string; className?: string }) {
  const common = { viewBox: "0 0 24 24", className, "aria-hidden": true } as const;
  if (platform === "tiktok")
    return (
      <svg {...common} fill="currentColor">
        <path d="M21 8.6a6.6 6.6 0 0 1-4.6-1.9v7.9a6.2 6.2 0 1 1-5.4-6.1v2.9a3.3 3.3 0 1 0 2.5 3.2V2h2.9A6.6 6.6 0 0 0 21 6.7z" />
      </svg>
    );
  if (platform === "youtube")
    return (
      <svg {...common} fill="currentColor">
        <path d="M23 12s0-3.8-.5-5.6a2.9 2.9 0 0 0-2-2C18.7 4 12 4 12 4s-6.7 0-8.5.5a2.9 2.9 0 0 0-2 2C1 8.2 1 12 1 12s0 3.8.5 5.6a2.9 2.9 0 0 0 2 2C5.3 20 12 20 12 20s6.7 0 8.5-.5a2.9 2.9 0 0 0 2-2C23 15.8 23 12 23 12zM9.8 15.4V8.6l5.8 3.4z" />
      </svg>
    );
  if (platform === "facebook")
    return (
      <svg {...common} fill="currentColor">
        <path d="M22 12a10 10 0 1 0-11.6 9.9v-7h-2.5V12h2.5V9.8c0-2.5 1.5-3.9 3.8-3.9 1.1 0 2.2.2 2.2.2v2.5h-1.3c-1.2 0-1.6.8-1.6 1.6V12h2.8l-.4 2.9h-2.4v7A10 10 0 0 0 22 12z" />
      </svg>
    );
  if (platform === "x")
    return (
      <svg {...common} fill="currentColor">
        <path d="M18.9 2H22l-7 8 8.2 12h-6.4l-5-7.3L5.9 22H2.8l7.5-8.6L2.5 2h6.6l4.5 6.6zm-1.1 18h1.7L7.3 3.8H5.5z" />
      </svg>
    );
  return (
    <svg {...common} fill="none" stroke="currentColor" strokeWidth={1.9}>
      <rect x="3" y="3" width="18" height="18" rx="5" />
      <circle cx="12" cy="12" r="4" />
      <circle cx="17.3" cy="6.7" r="1.1" fill="currentColor" stroke="none" />
    </svg>
  );
}

/** The rounded tile a platform mark sits in, beside a name. */
export function Avatar({ platform, className = "" }: { platform: string; className?: string }) {
  return (
    <span
      title={PLATFORM_LABEL[platform] ?? platform}
      className={`grid h-[31px] w-[31px] flex-none place-items-center rounded-[9px] border border-border bg-secondary text-foreground ${className}`}
    >
      <PlatformIcon platform={platform} className="h-4 w-4" />
    </span>
  );
}

/* ------------------------------------------------------------------ */
/* surfaces                                                            */
/* ------------------------------------------------------------------ */

export function Card({
  children,
  className = "",
  ...rest
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div {...rest} className={`rounded-[18px] border border-border bg-card shadow-card ${className}`}>
      {children}
    </div>
  );
}

/**
 * A card's header. `flush` drops the bottom padding for a body that
 * supplies its own — and when the card is collapsed the padding comes
 * back, because a header with nothing under it needs a floor.
 *
 * The preview learned this the hard way: an inline `padding-bottom:0`
 * beat the collapsed rule, and a shut card sat 20px too tight.
 */
export function CardHead({
  title,
  sub,
  right,
  flush = true,
  collapsed = false,
}: {
  title: React.ReactNode;
  sub?: React.ReactNode;
  right?: React.ReactNode;
  flush?: boolean;
  collapsed?: boolean;
}) {
  const pad = !flush ? "pb-3.5" : collapsed ? "pb-5" : "pb-0";
  return (
    <div className={`flex items-start justify-between gap-3 px-5 pt-[18px] ${pad}`}>
      <div className="min-w-0">
        <div className="text-[16px] font-bold leading-snug tracking-[-0.011em] text-foreground">{title}</div>
        {sub ? <div className="mt-1 text-[12.5px] leading-[1.45] text-subtle">{sub}</div> : null}
      </div>
      {right ? <span className="flex flex-none items-center gap-0.5">{right}</span> : null}
    </div>
  );
}

export function CardBody({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <div className={`px-5 pb-5 pt-3.5 ${className}`}>{children}</div>;
}

/**
 * Which rail boxes are shut, remembered between visits.
 *
 * The set is stored per browser, not per campaign: collapsing "Limits"
 * says you do not want to read limits, and that holds for the next
 * campaign too. Every read and write is guarded — a private window or
 * blocked site data throws on access, and a collapsed box is not worth
 * failing a page over.
 *
 * The stored value is read after mount rather than during render. The
 * server has no localStorage, so seeding state from it would render one
 * thing on the server and another in the browser.
 */
export function useCollapsed(storageKey: string) {
  const [shut, setShut] = useState<Record<string, boolean>>({});

  useEffect(() => {
    try {
      const saved = localStorage.getItem(storageKey);
      // Reading an external store after hydration is what this effect is for.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      if (saved) setShut(JSON.parse(saved));
    } catch {
      /* unreadable or unparseable: everything starts open */
    }
  }, [storageKey]);

  const toggle = (key: string) =>
    setShut((prev) => {
      const next = { ...prev, [key]: !prev[key] };
      try {
        localStorage.setItem(storageKey, JSON.stringify(next));
      } catch {
        /* the box still collapses; it just will not be remembered */
      }
      return next;
    });

  return [shut, toggle] as const;
}

/** The chevron that shuts a rail box. Purely presentational — the page owns the state. */
export function CollapseButton({ open, onToggle, label }: { open: boolean; onToggle: () => void; label: string }) {
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-expanded={open}
      aria-label={`${open ? "Collapse" : "Expand"} ${label}`}
      className="grid h-[26px] w-[26px] place-items-center rounded-[7px] text-subtle transition-colors hover:bg-secondary hover:text-foreground"
    >
      <svg
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth={2}
        className={`h-[15px] w-[15px] transition-transform duration-[180ms] ${open ? "" : "-rotate-90"}`}
      >
        <path d="M6 9l6 6 6-6" />
      </svg>
    </button>
  );
}

/* ------------------------------------------------------------------ */
/* the "..." menu                                                      */
/* ------------------------------------------------------------------ */

export type MenuItem =
  | "-"
  | { label: string; group: true }
  | {
      label: string;
      icon?: React.ComponentType<{ className?: string }>;
      onClick?: () => void;
      href?: string;
      danger?: boolean;
      disabled?: boolean;
      kbd?: string;
    };

/**
 * The menu behind every "...". Closes on outside click and on Escape —
 * a menu that only its own button can shut is a trap once it overlaps
 * the thing it covers.
 */
export function DotsMenu({
  items,
  label = "Options",
  trigger,
  align = "right",
}: {
  items: MenuItem[];
  label?: string;
  trigger?: React.ReactNode;
  align?: "right" | "left";
}) {
  const [open, setOpen] = useState(false);
  const wrap = useRef<HTMLSpanElement>(null);
  const menu = useRef<HTMLDivElement>(null);

  /* The menu is rendered into <body> and positioned from the trigger's own
     rectangle. Absolutely positioned inside the page it was a child of
     whatever scroll container it sat in — and a table wrapper is
     `overflow-x-auto`, which the spec turns into `overflow-y: auto` as
     well. So opening a row menu grew a scrollbar and pushed the card out
     instead of floating over it. Nothing in an ancestor can clip or scroll
     a fixed node in <body>.

     Placement writes straight to the node rather than through state: a
     positioner that re-renders on every scroll frame is a positioner that
     stutters. */
  useLayoutEffect(() => {
    if (!open) return;
    const place = () => {
      const t = wrap.current?.getBoundingClientRect();
      const el = menu.current;
      if (!t || !el) return;
      const GAP = 6;
      const EDGE = 8;
      const w = el.offsetWidth;
      const h = el.offsetHeight;
      let left = align === "right" ? t.right - w : t.left;
      left = Math.min(Math.max(EDGE, left), window.innerWidth - w - EDGE);
      // below by default, above when there is no room, and never off-screen
      let top = t.bottom + GAP;
      if (top + h > window.innerHeight - EDGE) {
        const above = t.top - GAP - h;
        top = above >= EDGE ? above : Math.max(EDGE, window.innerHeight - h - EDGE);
      }
      el.style.top = `${Math.round(top)}px`;
      el.style.left = `${Math.round(left)}px`;
      el.style.visibility = "visible";
    };
    place();
    // `true` catches scrolls in any ancestor, not just the window
    window.addEventListener("scroll", place, true);
    window.addEventListener("resize", place);
    return () => {
      window.removeEventListener("scroll", place, true);
      window.removeEventListener("resize", place);
    };
  }, [open, align]);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      const t = e.target as Node;
      // the menu is no longer inside `wrap`, so it needs asking too
      if (wrap.current?.contains(t) || menu.current?.contains(t)) return;
      setOpen(false);
    };
    const onEsc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onEsc);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onEsc);
    };
  }, [open]);

  const itemClass = (danger?: boolean, disabled?: boolean) =>
    [
      "flex w-full items-center gap-2.5 rounded-[9px] px-2.5 py-2 text-left text-[12.5px] font-semibold transition-colors",
      disabled
        ? "cursor-default opacity-45"
        : danger
          ? "text-bad hover:bg-bad/10"
          : "text-muted-foreground hover:bg-secondary hover:text-foreground",
    ].join(" ");

  return (
    <span className="relative inline-flex" ref={wrap}>
      <span
        role="button"
        tabIndex={0}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={label}
        onClick={(e) => {
          e.stopPropagation();
          setOpen((v) => !v);
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            e.stopPropagation();
            setOpen((v) => !v);
          }
        }}
        className={
          // A caller-supplied trigger brings its own box; only the bare
          // "..." wants the 26px hit target, and forcing it on a chip
          // clips the chip to a square.
          trigger
            ? "cursor-pointer"
            : "grid h-[26px] w-[26px] cursor-pointer place-items-center rounded-[7px] text-subtle transition-colors hover:bg-secondary hover:text-foreground"
        }
      >
        {trigger ?? <MoreHorizontal className="h-[17px] w-[17px]" />}
      </span>
      {open &&
        createPortal(
          <div
            ref={menu}
            role="menu"
            onClick={(e) => e.stopPropagation()}
            // hidden until placed, so it never flashes at the top-left
            style={{ visibility: "hidden", top: 0, left: 0 }}
            className="fixed z-[70] w-[212px] rounded-[14px] border border-border bg-popover p-1.5
                       shadow-[0_18px_40px_-16px_rgba(16,24,40,0.45)] dark:shadow-[0_18px_40px_-16px_rgba(0,0,0,0.8)]"
          >
          {items.map((it, i) => {
            if (it === "-") return <div key={i} className="my-1.5 h-px bg-line-2" />;
            if ("group" in it)
              return (
                <div key={i} className="px-2.5 pb-1 pt-[7px] text-[10px] font-bold uppercase tracking-[0.08em] text-subtle">
                  {it.label}
                </div>
              );
            const Icon = it.icon;
            const inner = (
              <>
                {Icon && <Icon className={`h-3.5 w-3.5 flex-none ${it.danger ? "" : "text-subtle"}`} />}
                {it.label}
                {it.kbd && <kbd className="ml-auto font-sans text-[10px] font-bold text-subtle">{it.kbd}</kbd>}
              </>
            );
            if (it.href && !it.disabled)
              return (
                <Link key={i} href={it.href} onClick={() => setOpen(false)} className={itemClass(it.danger)}>
                  {inner}
                </Link>
              );
            return (
              <button
                key={i}
                type="button"
                disabled={it.disabled}
                onClick={() => {
                  setOpen(false);
                  it.onClick?.();
                }}
                className={itemClass(it.danger, it.disabled)}
              >
                {inner}
              </button>
            );
          })}
          </div>,
          document.body,
        )}
    </span>
  );
}

/* ------------------------------------------------------------------ */
/* status                                                              */
/* ------------------------------------------------------------------ */

export type Tone = "done" | "live" | "pause" | "stop" | "draft" | "queue" | "skip";

const TONE_CLASS: Record<Tone, string> = {
  done: "text-good bg-good/11",
  live: "text-chart-1 bg-chart-1/16",
  pause: "text-warn bg-warn/12",
  stop: "text-bad bg-bad/11",
  draft: "text-muted-foreground bg-subtle/16",
  queue: "text-muted-foreground bg-subtle/16",
  skip: "text-warn bg-chart-3/12",
};

/** Campaign status → the tone it wears. */
export const CAMPAIGN_TONE: Record<string, Tone> = {
  completed: "done",
  running: "live",
  paused: "pause",
  stopped: "stop",
  draft: "draft",
};

/** Target status → the tone it wears. */
export const TARGET_TONE: Record<string, Tone> = {
  sent: "done",
  failed: "stop",
  skipped: "skip",
  queued: "queue",
  processing: "live",
  paused: "pause",
};

export function Tag({ tone, children }: { tone: Tone; children: React.ReactNode }) {
  return (
    <span
      className={`inline-flex items-center gap-[5px] rounded-full px-[9px] py-[3px] text-[11px] font-bold leading-normal ${TONE_CLASS[tone]}`}
    >
      <i className="h-[5px] w-[5px] rounded-full bg-current" />
      {children}
    </span>
  );
}

/* ------------------------------------------------------------------ */
/* controls                                                            */
/* ------------------------------------------------------------------ */

const CHIP =
  "inline-flex flex-none items-center gap-[7px] whitespace-nowrap rounded-[11px] border border-border bg-card px-[13px] py-2 text-[12.5px] font-semibold leading-normal text-foreground shadow-card transition-colors";
const CHIP_HOVER = "hover:bg-secondary";

export function Chip({
  icon: Icon,
  children,
  href,
  danger,
  className = "",
  ...rest
}: {
  icon?: React.ComponentType<{ className?: string }>;
  children?: React.ReactNode;
  href?: string;
  danger?: boolean;
  className?: string;
} & Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, "children">) {
  const cls = [
    CHIP,
    CHIP_HOVER,
    danger ? "hover:border-bad/35 hover:text-bad" : "",
    rest.disabled ? "cursor-default opacity-50" : "",
    className,
  ].join(" ");
  const inner = (
    <>
      {Icon && <Icon className="h-3.5 w-3.5 flex-none text-subtle" />}
      {children}
    </>
  );
  if (href)
    return (
      <Link href={href} className={cls}>
        {inner}
      </Link>
    );
  return (
    <button type="button" {...rest} className={cls}>
      {inner}
    </button>
  );
}

/** The count that rides on a chip — Accounts · 15. */
export function ChipCount({ children }: { children: React.ReactNode }) {
  return (
    <span className="ml-[1px] rounded-full border border-border bg-secondary px-1.5 py-px text-[11px] font-bold leading-normal text-muted-foreground">
      {children}
    </span>
  );
}

export function PrimaryButton({
  icon: Icon,
  iconRight,
  children,
  className = "",
  ...rest
}: {
  icon?: React.ComponentType<{ className?: string; strokeWidth?: number }>;
  /** An arrow that means "onward" belongs after the label, not before it. */
  iconRight?: boolean;
  children: React.ReactNode;
  className?: string;
} & Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, "children">) {
  return (
    <button
      type="button"
      {...rest}
      className={`inline-flex flex-none items-center gap-[7px] whitespace-nowrap rounded-[11px] bg-primary px-4 py-[9px] text-[12.5px] font-bold leading-normal text-primary-foreground
                  shadow-[0_8px_18px_-9px_rgba(11,13,18,0.55)] transition-[filter,opacity] hover:brightness-110
                  disabled:cursor-default disabled:opacity-45 disabled:hover:brightness-100 ${className}`}
    >
      {Icon && !iconRight && <Icon className="h-3.5 w-3.5 flex-none" strokeWidth={2.4} />}
      {children}
      {Icon && iconRight && <Icon className="h-3.5 w-3.5 flex-none" strokeWidth={2.4} />}
    </button>
  );
}

/** A full-width secondary action at the foot of a rail box. */
export function RailLink({
  icon: Icon,
  children,
  href,
  spin,
  className = "",
  ...rest
}: {
  icon?: React.ComponentType<{ className?: string }>;
  children: React.ReactNode;
  href?: string;
  /** Rotates the icon 180°, for the chevron on a "view all" toggle. */
  spin?: boolean;
  /** `mt-auto` when the card it sits in fills a row and this is its floor. */
  className?: string;
} & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  const cls =
    `mt-3 flex w-full items-center justify-center gap-[7px] whitespace-nowrap rounded-[10px] border border-border bg-card px-3.5 py-[9px] text-[12.5px] font-semibold leading-normal text-foreground transition-colors hover:bg-secondary ${className}`;
  const inner = (
    <>
      {Icon && (
        <Icon className={`h-3.5 w-3.5 flex-none transition-transform duration-[180ms] ${spin ? "rotate-180" : ""}`} />
      )}
      <span>{children}</span>
    </>
  );
  if (href)
    return (
      <Link href={href} className={cls}>
        {inner}
      </Link>
    );
  return (
    <button type="button" {...rest} className={cls}>
      {inner}
    </button>
  );
}

/* ------------------------------------------------------------------ */
/* layout                                                              */
/* ------------------------------------------------------------------ */

export function PageHead({ children }: { children: React.ReactNode }) {
  return <div className="flex flex-wrap items-center gap-2.5">{children}</div>;
}

/**
 * The "back" crumb over a sub-page.
 *
 * It sits above the whole header row rather than inside the title block,
 * so that `PageHead`'s centring lines the actions up with the page title
 * itself. Nested in the title, the crumb made the block two lines tall and
 * the action row floated half a line high.
 */
export function BackLink({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <Link
      href={href}
      className="-mb-1 inline-flex w-max items-center gap-1.5 text-xs font-semibold leading-normal text-subtle transition-colors hover:text-foreground"
    >
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className="h-[13px] w-[13px]">
        <path d="M19 12H5M11 18l-6-6 6-6" />
      </svg>
      {children}
    </Link>
  );
}

export function PageTitle({ title, sub, above }: { title: string; sub?: React.ReactNode; above?: React.ReactNode }) {
  return (
    <div className="min-w-0">
      {above}
      <h1 className="text-[25px] font-extrabold leading-normal tracking-[-0.03em] text-foreground">{title}</h1>
      {sub ? <p className="mt-1 text-[12.5px] leading-normal text-subtle">{sub}</p> : null}
    </div>
  );
}

export function PageActions({ children }: { children: React.ReactNode }) {
  return <div className="ml-auto flex flex-wrap items-center gap-2">{children}</div>;
}

/**
 * The two-column body: content left, rail right, stacking under 1180px.
 *
 * `items-stretch`, not `items-start`. Both columns are the height of the
 * row, so a card that asks to fill its column — `flex flex-col` on the card
 * and `flex-1` on it — ends level with the one beside it. Cards that do not
 * ask are left at their own height, which is what a rail holding a stack of
 * three wants. Started as `items-start`, which made that impossible: the
 * column was only ever as tall as its contents, so nothing had a height to
 * grow into and every one of these rows ended ragged.
 */
export function TwoCol({ main, rail }: { main: React.ReactNode; rail: React.ReactNode }) {
  return (
    <div className="grid grid-cols-1 items-stretch gap-4 xl:grid-cols-[1fr_372px]">
      <div className="flex min-w-0 flex-col gap-4">{main}</div>
      <div className="flex flex-col gap-4">{rail}</div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* filters                                                             */
/* ------------------------------------------------------------------ */

export function Tabs({
  items,
  value,
  onChange,
  className = "",
  locked,
  iconOnly = false,
}: {
  items: { key: string; label: string; count?: number; icon?: React.ComponentType<{ className?: string }> }[];
  value: string;
  onChange: (k: string) => void;
  className?: string;
  /** Why the other choices cannot be taken right now. The strip still
   *  shows all of them — hiding them would make the set look shorter than
   *  it is — but only the current one is live, and the rest carry the
   *  reason as a tooltip. */
  locked?: string;
  /** Show only each item's icon; its label slides out beside it on hover
   *  (or keyboard focus) and folds away again after. The label stays the
   *  accessible name throughout. */
  iconOnly?: boolean;
}) {
  return (
    <div
      // `w-fit`: the strip is a set of choices, not a bar. As a block-level
      // flex child it would stretch to the column and the pill would float
      // in a field of empty track.
      className={`flex w-fit flex-wrap items-center gap-[3px] rounded-[12px] border border-border bg-card p-[3px] shadow-card ${className}`}
    >
      {items.map((it) => {
        const on = it.key === value;
        const Icon = it.icon;
        return (
          <button
            key={it.key}
            type="button"
            onClick={() => onChange(it.key)}
            aria-pressed={on}
            aria-label={iconOnly ? it.label : undefined}
            disabled={!!locked && !on}
            title={locked && !on ? locked : undefined}
            className={`group flex items-center whitespace-nowrap rounded-[9px] ${
              iconOnly && Icon ? "px-[9px]" : "gap-1.5 px-[11px]"
            } py-1.5 text-[12.5px] font-semibold leading-normal transition-colors ${
              on
                ? "bg-primary text-primary-foreground"
                : locked
                  ? "cursor-default text-muted-foreground opacity-40"
                  : "text-muted-foreground hover:bg-secondary hover:text-foreground"
            }`}
          >
            {Icon && <Icon className={iconOnly ? "h-[15px] w-[15px] flex-none" : "h-[13px] w-[13px]"} />}
            {iconOnly && Icon ? (
              // Folded to nothing until hovered; max-width rather than
              // width so each label opens only as far as its own text.
              <span
                aria-hidden
                className="max-w-0 overflow-hidden opacity-0 transition-all duration-200 ease-out group-hover:ml-1.5 group-hover:max-w-[120px] group-hover:opacity-100 group-focus-visible:ml-1.5 group-focus-visible:max-w-[120px] group-focus-visible:opacity-100"
              >
                {it.label}
              </span>
            ) : (
              it.label
            )}
            {it.count !== undefined && (
              <span className="text-[10.5px] font-bold tabular-nums opacity-65">{it.count}</span>
            )}
          </button>
        );
      })}
    </div>
  );
}

/** A chip that opens a short list of choices — platform, sort order. */
export function SelectChip({
  value,
  options,
  onChange,
  label,
}: {
  value: string;
  options: { key: string; label: string }[];
  onChange: (k: string) => void;
  label: string;
}) {
  const current = options.find((o) => o.key === value);
  return (
    <DotsMenu
      label={label}
      items={options.map((o) => ({
        label: o.label,
        onClick: () => onChange(o.key),
      }))}
      trigger={
        <span className={`${CHIP} ${CHIP_HOVER} w-max`}>
          {current?.label ?? label}
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className="h-3.5 w-3.5 text-subtle">
            <path d="M6 9l6 6 6-6" />
          </svg>
        </span>
      }
    />
  );
}

/* ------------------------------------------------------------------ */
/* figures                                                             */
/* ------------------------------------------------------------------ */

/** The headline over a stacked bar: one figure, one sentence. */
export function FigureLine({ value, children }: { value: string; children: React.ReactNode }) {
  return (
    <div className="mb-3.5 flex flex-wrap items-baseline gap-[9px]">
      <span className="text-[27px] font-extrabold leading-normal tracking-[-0.035em] tabular-nums text-foreground">
        {value}
      </span>
      <span className="text-[12.5px] leading-normal text-subtle">{children}</span>
    </div>
  );
}

export function FigureStrong({ children }: { children: React.ReactNode }) {
  return <b className="font-bold tabular-nums text-muted-foreground">{children}</b>;
}

export type Band = { label: string; value: number; color: string };

/**
 * One bar, three states. The 2px gap between fills is the design system's
 * surface spacer — without it two adjacent colours read as one mark.
 */
export function StackBar({ bands, total }: { bands: Band[]; total: number }) {
  const t = total || 1;
  return (
    <div className="flex h-2.5 gap-0.5 overflow-hidden rounded-full bg-border">
      {bands
        .filter((b) => b.value > 0)
        .map((b, i, arr) => (
          <i
            key={b.label}
            title={`${b.label}: ${n(b.value)}`}
            style={{ width: `${(b.value / t) * 100}%`, background: b.color }}
            className={`block h-full ${i === 0 ? "rounded-l-full" : ""} ${i === arr.length - 1 ? "rounded-r-full" : ""}`}
          />
        ))}
    </div>
  );
}

/** The bar's legend. Always present — identity is never colour alone. */
export function Legend({ bands }: { bands: Band[] }) {
  return (
    <div className="mt-[11px] flex flex-wrap gap-3.5">
      {bands.map((b) => (
        <span key={b.label} className="flex items-center gap-[7px] text-[11.5px] leading-normal text-subtle">
          <i className="h-[9px] w-[9px] flex-none rounded-[3px]" style={{ background: b.color }} />
          {b.label}
          <b className="font-bold tabular-nums text-foreground">{n(b.value)}</b>
        </span>
      ))}
    </div>
  );
}

/** Five small counters under the bar. */
const MINI_COLS: Record<number, string> = {
  3: "grid-cols-3",
  4: "grid-cols-4",
  5: "grid-cols-5",
};

export function Minis({
  cells,
  className = "",
}: {
  cells: { label: string; value: number; tone?: "bad" }[];
  /** `mt-auto` when this is the last thing in a card that fills a row. */
  className?: string;
}) {
  return (
    <div className={`mt-4 grid gap-2 ${MINI_COLS[cells.length] ?? "grid-cols-5"} ${className}`}>
      {cells.map((c) => (
        <div key={c.label} className="rounded-[10px] bg-secondary px-1 py-[9px] text-center">
          <div
            className={`text-[18px] leading-[1.15] tracking-[-0.03em] tabular-nums ${
              c.tone === "bad"
                ? "font-extrabold text-destructive"
                : c.value === 0
                  ? "font-bold text-subtle"
                  : "font-extrabold text-foreground"
            }`}
          >
            {n(c.value)}
          </div>
          <div className="mt-[3px] text-[9.5px] font-semibold leading-normal tracking-[0.01em] text-subtle">
            {c.label}
          </div>
        </div>
      ))}
    </div>
  );
}

export function Progress({ pct }: { pct: number }) {
  return (
    <div className="flex min-w-[132px] items-center gap-[9px] max-md:min-w-0">
      <div className="h-[5px] flex-1 overflow-hidden rounded-full bg-border">
        <i className="block h-full rounded-full bg-chart-1" style={{ width: `${Math.min(100, pct).toFixed(1)}%` }} />
      </div>
      <span className="w-[38px] text-right text-[11.5px] font-bold tabular-nums leading-normal text-muted-foreground">
        {pct.toFixed(1)}%
      </span>
    </div>
  );
}

/** A label/value row in a rail box. */
export function KV({ label, children }: { label: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-line-2 py-[7px] text-[12.5px] leading-normal text-subtle last:border-b-0">
      <span>{label}</span>
      <b className="font-bold tabular-nums text-foreground">{children}</b>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* tables & empties                                                    */
/* ------------------------------------------------------------------ */

export const TH =
  "border-b border-border px-3.5 pb-2.5 text-left text-[10.5px] font-bold uppercase leading-normal tracking-[0.07em] text-subtle";
export const TD = "border-b border-line-2 px-3.5 py-[13px] align-middle text-[13px] leading-normal";
export const MONO = "font-mono text-[12.5px] tabular-nums";

export function Empty({
  icon: Icon,
  title,
  children,
  action,
}: {
  icon: React.ComponentType<{ className?: string; strokeWidth?: number }>;
  title: string;
  children?: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <div className="px-5 py-[52px] text-center">
      <div className="mx-auto grid h-[46px] w-[46px] place-items-center rounded-[14px] border border-border bg-secondary">
        <Icon className="h-[21px] w-[21px] text-subtle" strokeWidth={1.7} />
      </div>
      <p className="mt-[13px] text-sm font-bold leading-normal text-foreground">{title}</p>
      {children && (
        <span className="mx-auto mt-[5px] block max-w-[380px] text-xs leading-[1.55] text-subtle">{children}</span>
      )}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

/** The one-line caveat under a table. */
export function Note({ children }: { children: React.ReactNode }) {
  return <div className="px-0.5 pb-1.5 text-[11px] leading-normal text-subtle">{children}</div>;
}

/* ------------------------------------------------------------------ */
/* loading                                                             */
/* ------------------------------------------------------------------ */

/** A card-shaped placeholder, so the layout does not jump when data lands. */
export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`animate-pulse rounded-[10px] bg-secondary ${className}`} />;
}
