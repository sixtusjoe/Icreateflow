"use client";

/**
 * The page-wide motion, with no markup of its own:
 *
 * - `.rv` elements (and `.iso`) get `.in` the first time they scroll into
 *   view, which plays their rise-in;
 * - a `[data-count]` inside one counts up from zero when it arrives;
 * - the sections that loop (hero cards, marquee, bands) get `.paused`
 *   while off screen, so nothing animates where nobody is looking. That
 *   is for the visitor's laptop as much as the look — a page full of
 *   endless animations was enough to stall one.
 *
 * Re-run on every route change, since home and the legal pages share it.
 */
import { useEffect } from "react";
import { usePathname } from "next/navigation";

function countUp(el: HTMLElement, reduce: boolean) {
  const to = Number(el.dataset.count);
  const suf = el.dataset.suf ?? "";
  if (reduce) { el.textContent = to.toLocaleString() + suf; return; }
  let t0: number | null = null;
  const step = (ts: number) => {
    t0 ??= ts;
    const p = Math.min(1, (ts - t0) / 1400);
    el.textContent = Math.round(to * (1 - Math.pow(1 - p, 3))).toLocaleString() + suf;
    if (p < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

export default function Effects() {
  const pathname = usePathname();

  useEffect(() => {
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    const reveal = new IntersectionObserver((entries) => {
      for (const e of entries) {
        if (!e.isIntersecting) continue;
        const el = e.target as HTMLElement;
        el.classList.add("in");
        const c = el.querySelector<HTMLElement>("[data-count]");
        if (c && !c.dataset.done) { c.dataset.done = "1"; countUp(c, reduce); }
        reveal.unobserve(el);
      }
    }, { threshold: 0.15 });
    document.querySelectorAll(".mk .rv, .mk .iso").forEach((el) => reveal.observe(el));

    const pause = new IntersectionObserver((entries) => {
      for (const e of entries) e.target.classList.toggle("paused", !e.isIntersecting);
    });
    document.querySelectorAll(".mk .hero, .mk .marq, .mk .dark, .mk .flowband, .mk .split, .mk .cta")
      .forEach((el) => pause.observe(el));

    return () => { reveal.disconnect(); pause.disconnect(); };
  }, [pathname]);

  return null;
}
