"use client";

/**
 * Pick a plan.
 *
 * THE PRICES AND LIMITS ARE PLACEHOLDERS, and the section says so with the
 * "placeholder prices" tag until the owner sets real ones. There is also
 * nothing to buy with yet: no subscriptions table and no payment provider,
 * so every "Start with…" goes to sign-up and the usual admin approval.
 * When billing exists, PLANS is the one place to change.
 */
import { useState } from "react";
import Link from "next/link";
import { Icon } from "./Sprite";

type Plan = {
  name: string; for: string; month: number; year: number; yearTotal: string;
  label: string; items: { text: string; off?: boolean }[]; pop?: boolean;
};

const PLANS: Plan[] = [
  {
    name: "Starter", for: "For one artist or brand getting their first drop out properly.",
    month: 29, year: 24, yearTotal: "$290 billed yearly", label: "What's in it",
    items: [
      { text: "1 artist or brand" }, { text: "Up to 5 connected accounts" },
      { text: "Campaigns with a view target" }, { text: "Clipping studio & audio to video" },
      { text: "Live view tracking" }, { text: "Outreach", off: true },
    ],
  },
  {
    name: "Studio", for: "For labels and teams running several releases at once.", pop: true,
    month: 79, year: 66, yearTotal: "$790 billed yearly", label: "Everything in Starter, plus",
    items: [
      { text: "Up to 5 artists or brands" }, { text: "Up to 25 connected accounts" },
      { text: "AI variations per account" }, { text: "Outreach — replies, follows & messages" },
      { text: "TikTok from your own phone" }, { text: "Auto-pause & auto-resume" },
    ],
  },
  {
    name: "Label", for: "For networks and studios promoting a full catalog every week.",
    month: 199, year: 166, yearTotal: "$1,990 billed yearly", label: "Everything in Studio, plus",
    items: [
      { text: "Unlimited artists and brands" }, { text: "Up to 100 connected accounts" },
      { text: "Several phones for TikTok outreach" }, { text: "Priority help from the team" },
      { text: "Every new feature first" },
    ],
  },
];

export default function Pricing() {
  const [yearly, setYearly] = useState(false);

  return (
    <section className="s" id="pricing" style={{ background: "var(--bg-2)" }}>
      <div className="wrap">
        <div className="ptop">
          <div>
            <span className="mono eyebrow rv">Pick a plan <span className="ph">placeholder prices</span></span>
            <h2 className="h2 rv" style={{ maxWidth: 680 }}>Start with one artist. Grow into a whole roster.</h2>
            <p className="lede rv" style={{ marginTop: 18 }}>
              Every plan runs the same engine. You pay for how many accounts it posts from and how much it does each day.
            </p>
          </div>
          <div className="bill rv" data-on={yearly ? "year" : "month"} role="group" aria-label="Billing period">
            <span className="bt" />
            <button type="button" aria-pressed={!yearly} onClick={() => setYearly(false)}>Monthly</button>
            <button type="button" aria-pressed={yearly} onClick={() => setYearly(true)}>Yearly <em>2 months free</em></button>
          </div>
        </div>

        <div className="plans">
          {PLANS.map((pl) => (
            <div key={pl.name} className={`plan rv ${pl.pop ? "pop" : ""}`}>
              <div className="nm"><b>{pl.name}</b>{pl.pop && <span className="tag">Most picked</span>}</div>
              <p className="for">{pl.for}</p>
              <div className="price">
                <span className="cur">$</span>
                <span className="amt" key={yearly ? "y" : "m"}>{yearly ? pl.year : pl.month}</span>
                <span className="per">/ month</span>
              </div>
              <div className="note">{yearly ? pl.yearTotal : "Billed monthly"}</div>
              <Link className={`btn ${pl.pop ? "btn-lime" : "btn-ghost"}`} href="/register">
                Start with {pl.name}{pl.pop && <> <Icon id="arr" /></>}
              </Link>
              <span className="mono lbl" style={pl.pop ? { color: "#727a8c" } : undefined}>{pl.label}</span>
              <ul>
                {pl.items.map((it) => (
                  <li key={it.text} className={it.off ? "off" : ""}>
                    <i>
                      {it.off
                        ? <svg viewBox="0 0 24 24" aria-hidden="true"><path stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" d="M7 12h10" /></svg>
                        : <Icon id="chk" />}
                    </i>
                    {it.text}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>

        <div className="ent rv">
          <span className="tile" style={{ width: 44, height: 44, borderRadius: 12 }}><Icon id="mark" size={34} /></span>
          <div><b>More than 100 accounts?</b></div>
          <p>Studios and networks running at scale get a plan built around their catalog — talk to us and we&apos;ll size it.</p>
          <Link className="btn btn-ghost" href="/help">Talk to us</Link>
        </div>
        <div className="pfoot rv">
          <span><Icon id="chk" size={14} />Every account reviewed before access</span>
          <span><Icon id="chk" size={14} />Cancel any time</span>
          <span><Icon id="chk" size={14} />Your accounts stay yours</span>
        </div>
      </div>
    </section>
  );
}
