"use client";

/**
 * The glass cards on the right of the home hero. Nobody is signed in on
 * this page, so none of it is anyone's data — a campaign climbing toward
 * its target, the posting queue, outreach replies, one upload fanning out —
 * and the stack is aria-hidden so a screen reader does not read it as fact.
 *
 * Every timer skips its tick while the hero is off screen (Effects marks
 * it .paused), and none starts under reduced motion.
 */
import { useEffect, useRef, useState } from "react";
import { Icon } from "./Sprite";

const TARGET = 1_000_000;
const QUEUE = [
  { t: "Studio session — teaser", s: "Today · 6:30 pm", p: ["tt", "ig"], bg: "linear-gradient(135deg,#d4f33d,#5f7a00)" },
  { t: "“Night Drive” lyric clip", s: "Tomorrow · 9:00 am", p: ["ig", "xx"], bg: "linear-gradient(135deg,#9a8cf0,#3b2f8f)" },
  { t: "Behind the mix, part 2", s: "Fri · 7:15 pm", p: ["tt", "yt", "fb"], bg: "linear-gradient(135deg,#f6a27a,#a8401b)" },
];
const BARS = [36, 52, 44, 66, 58, 74, 88];

export default function HeroStack() {
  const root = useRef<HTMLDivElement>(null);
  const [views, setViews] = useState(0);
  const [q, setQ] = useState<{ on: number; out: number | null }>({ on: 0, out: null });
  const [today, setToday] = useState(3);
  const [grown, setGrown] = useState(false);

  useEffect(() => {
    const live = () => !root.current?.closest(".hero")?.classList.contains("paused");
    const first = setTimeout(() => { setViews(640_000); setGrown(true); }, 700);
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return () => clearTimeout(first);
    const a = setInterval(() => {
      if (live()) setViews((v) => Math.min(TARGET * 0.74, v + Math.round(4000 + Math.random() * 9000)));
    }, 1600);
    const b = setInterval(() => {
      if (live()) setQ((s) => ({ on: (s.on + 1) % QUEUE.length, out: s.on }));
    }, 3400);
    const c = setInterval(() => {
      if (live()) setToday((n) => (n >= 9 ? 3 : n + 1));
    }, 2600);
    return () => { clearTimeout(first); clearInterval(a); clearInterval(b); clearInterval(c); };
  }, []);

  const p = views / TARGET;

  return (
    <div className="stack" aria-hidden="true" ref={root}>
      <div className="g gA">
        <div className="k"><span className="live" />Campaign · Night Drive</div>
        {/* not "ring": that is a Tailwind utility, and it drew an outline here */}
        <div className="gring">
          <svg viewBox="0 0 100 100">
            <circle cx="50" cy="50" r="42" fill="none" stroke="currentColor" strokeOpacity=".14" strokeWidth="10" />
            <circle cx="50" cy="50" r="42" fill="none" stroke="currentColor" strokeWidth="10" strokeLinecap="round"
              strokeDasharray="264" strokeDashoffset={264 * (1 - p)} style={{ transition: "stroke-dashoffset 1s" }} />
          </svg>
          <div><b>{views.toLocaleString()}</b><small>views of a 1,000,000 target</small></div>
        </div>
        <div className="bar"><i style={{ width: `${p * 100}%` }} /></div>
        <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11.5, color: "var(--glass-muted)", marginTop: 8 }}>
          <span>24 handles posting</span><span>on pace</span>
        </div>
      </div>

      <div className="g gB">
        <div className="k"><span className="live" />Up next</div>
        <div className="q">
          {QUEUE.map((it, i) => (
            <div key={it.t} className={`it ${i === q.on ? "on" : i === q.out ? "out" : ""}`}>
              <span className="th2" style={{ background: it.bg }} />
              <div style={{ minWidth: 0 }}>
                <b>{it.t}</b>
                <small>{it.s} {it.p.map((k) => <Icon key={k} id={k} />)}</small>
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="g gD">
        <div className="k">Outreach · replies</div>
        <b>{125 + today}<small>+{today} today</small></b>
        <div className="sp">{BARS.map((h, i) => <i key={i} style={{ height: grown ? `${h}%` : "20%" }} />)}</div>
      </div>

      <div className="g gC">
        <div className="k">One upload → every feed</div>
        <div className="fan">
          <span className="src">MP4</span>
          <svg className="lines" viewBox="0 0 120 60" preserveAspectRatio="none">
            <g fill="none" stroke="var(--glass-muted)" strokeWidth="1.6">
              <path className="dash" d="M0 30 C60 30 60 4 120 4" /><path className="dash" d="M0 30 C60 30 60 22 120 22" />
              <path className="dash" d="M0 30 C60 30 60 40 120 40" /><path className="dash" d="M0 30 C60 30 60 57 120 57" />
            </g>
          </svg>
          <span className="dst">
            {["tt", "yt", "ig", "fb"].map((k) => <span key={k}><Icon id={k} /></span>)}
          </span>
        </div>
      </div>

      <div className="g gE"><span className="ok"><Icon id="chk" size={14} /></span>Target hit — posting paused</div>
    </div>
  );
}
