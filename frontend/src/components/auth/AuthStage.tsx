"use client";

/**
 * The photo half of the auth pages, with glass cards that each show one
 * thing the product does: the posting queue, outreach replies, the posting
 * week, clipping, and follower growth.
 *
 * Nobody is signed in here, so nothing on this side is anyone's data — the
 * titles and figures are illustrations, and the stage is `aria-hidden` so a
 * screen reader does not read them out as facts. The week strip alone is
 * real (it is this week's dates), because a calendar showing some other
 * week reads as broken rather than as an example.
 *
 * Each card is its own component so its timer re-renders only itself; the
 * clip card ticks about nine times a second. Under reduced motion no timer
 * starts and every card holds its first frame.
 */
import { useEffect, useState, useSyncExternalStore } from "react";
import Image from "next/image";
import Link from "next/link";
import { X } from "lucide-react";
import { PlatformIcon } from "@/components/kit";
import s from "./auth.module.css";

function prefersReducedMotion() {
  return typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

export default function AuthStage() {
  return (
    <section className={s.stage} aria-hidden="true">
      <div className={s.photo}>
        <Image src="/auth/team.jpg" alt="" fill priority sizes="(max-width: 1023px) 100vw, 56vw" />
      </div>
      <div className={s.glow} />
      <div className={s.shade} />
      <div className={s.notch}>
        <Link href="/" className={s.home} tabIndex={-1} aria-label="Back to the site">
          <X className="h-5 w-5" strokeWidth={1.8} />
        </Link>
      </div>
      <QueueCard />
      <RepliesCard />
      <WeekCard />
      <ClipCard />
      <FollowersCard />
    </section>
  );
}

/* ---------------------------------------------------------------- */

const POSTS = [
  { t: "Studio session — teaser", s: "Today · 6:30 pm", p: ["tiktok", "instagram"], bg: "linear-gradient(135deg,#d4f33d,#5f7a00)" },
  { t: "“Night Drive” lyric clip", s: "Tomorrow · 9:00 am", p: ["instagram", "x"], bg: "linear-gradient(135deg,#9a8cf0,#3b2f8f)" },
  { t: "Behind the mix, part 2", s: "Fri · 7:15 pm", p: ["tiktok", "x", "instagram"], bg: "linear-gradient(135deg,#f6a27a,#a8401b)" },
];

function QueueCard() {
  // `out` is the post leaving, so it can slide up while the next slides in.
  const [{ on, out }, setQ] = useState<{ on: number; out: number | null }>({ on: 0, out: null });
  useEffect(() => {
    if (prefersReducedMotion()) return;
    const id = setInterval(() => setQ((q) => ({ on: (q.on + 1) % POSTS.length, out: q.on })), 3400);
    return () => clearInterval(id);
  }, []);

  return (
    <div className={`${s.g} ${s.c1}`}>
      <div className={s.k}><span className={s.live} />Up next</div>
      <div className={s.rot}>
        {POSTS.map((p, i) => (
          <div key={p.t} className={`${s.item} ${i === on ? s.itemOn : i === out ? s.itemOut : ""}`}>
            <span className={s.thumbnail} style={{ background: p.bg }} />
            <div className="min-w-0">
              <div className={s.itemT}>{p.t}</div>
              <div className={s.itemS}>
                {p.s}
                <span className={s.plats}>
                  {p.p.map((k) => <PlatformIcon key={k} platform={k} className="h-3 w-3" />)}
                </span>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------- */

const BARS = [38, 52, 44, 66, 58, 74, 88];

function RepliesCard() {
  const [today, setToday] = useState(3);
  const [grown, setGrown] = useState(false);
  useEffect(() => {
    const t = setTimeout(() => setGrown(true), 900);
    if (prefersReducedMotion()) return () => clearTimeout(t);
    const id = setInterval(() => setToday((n) => (n >= 9 ? 3 : n + 1)), 2600);
    return () => { clearTimeout(t); clearInterval(id); };
  }, []);
  const extra = today - 3;

  return (
    <div className={`${s.g} ${s.c2}`}>
      <div className={s.k}>Outreach · replies</div>
      <div className={s.num}>{125 + today}<small>+{today} today</small></div>
      <div className={s.sub}>from 1,940 people reached</div>
      <div className={s.bars}>
        {BARS.map((h, i) => (
          <i key={i} style={{ height: grown ? `${i === BARS.length - 1 ? Math.min(100, h + extra * 3) : h}%` : "20%" }} />
        ))}
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------- */

const DAY_NAMES = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const POSTING_DAYS = [1, 2, 4, 5];
const noSubscribe = () => () => {};

/** Today as "y-m-d", or null while rendering on the server — so the week is
 *  drawn from the visitor's clock, not the server's, without a mismatch. */
function useDayKey() {
  return useSyncExternalStore(
    noSubscribe,
    () => {
      const d = new Date();
      return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
    },
    () => null,
  );
}

function WeekCard() {
  const key = useDayKey();
  const [step, setStep] = useState(0);
  useEffect(() => {
    if (prefersReducedMotion()) return;
    const id = setInterval(() => setStep((n) => n + 1), 2800);
    return () => clearInterval(id);
  }, []);

  let days: { name: string; date: number }[] = [];
  let hl = 0;
  if (key) {
    const [y, m, d] = key.split("-").map(Number);
    const today = new Date(y, m, d);
    const dow = today.getDay();
    days = DAY_NAMES.map((name, i) => {
      const x = new Date(y, m, d - dow + i);
      return { name, date: x.getDate() };
    });
    // The highlight starts on today, then visits each posting day in turn.
    const order = [dow, ...POSTING_DAYS.filter((p) => p !== dow)];
    hl = order[step % order.length];
  }

  return (
    <div className={`${s.g} ${s.c3}`}>
      <div className={s.k} style={{ padding: "0 6px" }}>Posting this week</div>
      <div className={s.week}>
        {key && <span className={s.hl} style={{ left: `calc(${hl} * 100% / 7)` }} />}
        {days.map((d, i) => (
          <div key={d.name} className={`${s.d} ${i === hl ? s.dOn : ""}`}>
            <span>{d.name}</span>
            <b>{d.date}</b>
            {POSTING_DAYS.includes(i) && <em className={s.pip} />}
          </div>
        ))}
      </div>
      <div className={s.hatch} />
    </div>
  );
}

/* ---------------------------------------------------------------- */

const CLIP_TITLES = ["Live at Ohm — 6 clips", "Podcast ep. 14 — 6 clips", "Album listening party — 6 clips"];

function ClipCard() {
  const [prog, setProg] = useState(0);
  const [title, setTitle] = useState(0);
  useEffect(() => {
    if (prefersReducedMotion()) {
      const t = setTimeout(() => setProg(100), 0);
      return () => clearTimeout(t);
    }
    let p = 0;
    let t: ReturnType<typeof setTimeout>;
    const tick = () => {
      p = Math.min(100, p + 1.6);
      setProg(p);
      if (p < 100) {
        t = setTimeout(tick, 110);
      } else {
        // Hold on "Ready", then start the next job.
        t = setTimeout(() => {
          p = 0;
          setProg(0);
          setTitle((n) => (n + 1) % CLIP_TITLES.length);
          t = setTimeout(tick, 500);
        }, 2200);
      }
    };
    t = setTimeout(tick, 1400);
    return () => clearTimeout(t);
  }, []);

  return (
    <div className={`${s.g} ${s.solid} ${s.c4}`}>
      <div className={s.k}>Clipping</div>
      <div className={s.clipRow}>
        <b>{CLIP_TITLES[title]}</b>
        <span className={s.pct}>{prog >= 100 ? "Ready" : `${Math.round(prog)}%`}</span>
      </div>
      <div className={s.track}><div className={s.fill} style={{ width: `${prog}%` }} /></div>
      <div className={s.clips}>
        {[1, 2, 3, 4, 5, 6].map((n) => <i key={n} className={prog >= (n * 100) / 6 ? s.ready : ""} />)}
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------- */

function FollowersCard() {
  const [n, setN] = useState(214);
  const [bump, setBump] = useState(false);
  useEffect(() => {
    if (prefersReducedMotion()) return;
    let off: ReturnType<typeof setTimeout>;
    const id = setInterval(() => {
      setN((v) => v + 1 + (v % 3));
      setBump(true);
      off = setTimeout(() => setBump(false), 300);
    }, 3100);
    return () => { clearInterval(id); clearTimeout(off); };
  }, []);

  return (
    <div className={`${s.g} ${s.c5}`}>
      <div className={s.ava}>
        <i style={{ background: "oklch(0.85 0.2 110)" }}>JM</i>
        <i style={{ background: "#c9c2f0" }}>KA</i>
        <i style={{ background: "#f4b69c" }}>TS</i>
      </div>
      <div>
        <div className={s.folT}><span className={`${s.plus} ${bump ? s.bump : ""}`}>+{n}</span> new followers</div>
        <div className={s.folS}>across 3 accounts this week</div>
      </div>
    </div>
  );
}
