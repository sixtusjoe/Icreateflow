/**
 * Home — the public front door, built line by line from the approved
 * preview (modelled on transcend.io's structure, in our own palette).
 *
 * Honesty rules the copy kept to:
 * - No customer logos, testimonials or newsletter form: there are no real
 *   ones and nothing behind a newsletter. The platform strip and the
 *   "who it's for" cards fill those places.
 * - The 800+ / 50M+ figures were already on the old home page; they are
 *   the owner's claims, carried over unchanged.
 * - Pricing is placeholder and says so (see Pricing.tsx).
 *
 * Server-rendered; the only client islands are the hero cards, the
 * pricing toggle and the page-wide motion in MarketingShell.
 */
import Link from "next/link";
import MarketingShell from "@/components/marketing/MarketingShell";
import HeroStack from "@/components/marketing/HeroStack";
import Pricing from "@/components/marketing/Pricing";
import { Icon } from "@/components/marketing/Sprite";

const PLATFORMS: [string, string][] = [
  ["tt", "TikTok"], ["yt", "YouTube Shorts"], ["ig", "Instagram Reels"], ["fb", "Facebook"], ["xx", "X"],
];

const FEATURES: { title: string; desc: string; icon: React.ReactNode }[] = [
  { title: "Campaign-driven promotion", desc: "Launch with a clear view target. The engine keeps pushing across every connected account until the number is hit — then stops on its own.",
    icon: <><circle cx="12" cy="12" r="9" /><circle cx="12" cy="12" r="5" /><circle cx="12" cy="12" r="1" /></> },
  { title: "Variation account network", desc: "Fan one drop across dozens of TikTok, YouTube, Instagram and Facebook handles you control — different angles, different audiences, same catalog.",
    icon: <><circle cx="18" cy="5" r="3" /><circle cx="6" cy="12" r="3" /><circle cx="18" cy="19" r="3" /><path d="M8.6 13.5l6.8 4M15.4 6.5l-6.8 4" /></> },
  { title: "Cross-platform reach", desc: "TikTok, YouTube Shorts, Instagram Reels, Facebook — every clip hits every feed from one upload. No re-uploading, no re-captioning per handle.",
    icon: <><rect x="2" y="7" width="20" height="14" rx="2" /><path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16" /></> },
  { title: "AI anti-duplicate engine", desc: "Unique variations per account and varied overlays, so platforms treat each post as original — reach stays high and duplicate flags stay low.",
    icon: <path d="M12 3l1.9 5.8L20 10l-5 3.6L16.8 20 12 16.5 7.2 20 9 13.6 4 10l6.1-1.2z" /> },
  { title: "Live view tracking", desc: "Aggregated views across every variation, refreshed in the background. Watch a campaign climb toward its target in real time.",
    icon: <><path d="M3 3v18h18" /><path d="M7 15l4-4 3 3 6-6" /></> },
  { title: "Auto-pause & auto-resume", desc: "Directory runs dry? The system pauses. Upload new clips or sync another Drive folder — it picks up where it left off without missing a slot.",
    icon: <><rect x="6" y="5" width="4" height="14" rx="1" /><rect x="14" y="5" width="4" height="14" rx="1" /></> },
];

const VERTICALS: { title: string; desc: string; icon: React.ReactNode }[] = [
  { title: "Music artists & labels", desc: "Keep a single in rotation for weeks, not hours — clips from the track on every handle until the target lands.",
    icon: <><path d="M9 18V5l12-2v13" /><circle cx="6" cy="18" r="3" /><circle cx="18" cy="16" r="3" /></> },
  { title: "Movies & trailers", desc: "Cut the trailer into moments and run them to opening weekend across every short-form feed.",
    icon: <><rect x="2" y="2" width="20" height="20" rx="2.2" /><path d="M7 2v20M17 2v20M2 12h20M2 7h5M2 17h5M17 17h5M17 7h5" /></> },
  { title: "Podcasts", desc: "Every episode becomes a week of clips, each one pointing back to the full show.",
    icon: <><path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3z" /><path d="M19 10v2a7 7 0 0 1-14 0v-2M12 19v3" /></> },
  { title: "Brand products", desc: "Slide posts with AI variations per account, so one product story reads fresh on every handle.",
    icon: <path d="M21 16V8a2 2 0 0 0-1-1.7l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.7l7 4a2 2 0 0 0 2 0l7-4a2 2 0 0 0 1-1.7z" /> },
];

const FAQ: [string, string][] = [
  ["Do I need my own accounts?", "Yes. Icreateflow posts from TikTok, YouTube, Instagram and Facebook accounts you connect — your network, your audience. Nothing is posted from accounts you don't control."],
  ["What stops platforms flagging the posts as duplicates?", "Each handle gets its own variation — different overlays, captions and, for brand slides, different generated faces — so every post reads as original."],
  ["What happens when the view target is hit?", "Posting stops on its own. If the catalog runs out first, the campaign pauses and picks up again as soon as you add clips or sync another Drive folder."],
  ["Why does TikTok outreach run from a phone?", "TikTok quietly discards follows made from a browser. The Icreateflow Android app does that work from your own phone, where follows actually stick."],
  ["Can I start right away?", "Sign up and an admin reviews the account, and we email you the moment you're in."],
];

function Ico({ children, size = 19 }: { children: React.ReactNode; size?: number }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">{children}</svg>;
}

export default function HomePage() {
  return (
    <MarketingShell>
      <main>
        {/* ---------------------------------------------------------- hero */}
        <section className="hero">
          <div className="shapes"><i /><i /><i /><i /></div>
          <div className="wrap">
            <div>
              <span className="chip"><em>NEW</em>The promotion engine for modern creators</span>
              <h1>The promotion engine behind <span>every drop.</span></h1>
              <p className="sub">
                Artists, labels, studios and podcast networks hand us their catalog. We put it into rotation across your
                TikTok, YouTube, Instagram and Facebook accounts — on schedule, toward a view target, until the numbers land.
              </p>
              {/* A plain GET form: the address arrives on /register already typed in. */}
              <form className="form" action="/register" method="get">
                <input type="email" name="email" placeholder="Your email" aria-label="Your email" autoComplete="email" />
                <button className="btn btn-lime" type="submit">Start promoting <Icon id="arr" /></button>
              </form>
              <div className="after">
                <span><Icon id="chk" size={14} />Set a view target</span>
                <span><Icon id="chk" size={14} />Auto-paces around the clock</span>
                <span><Icon id="chk" size={14} />Four platforms, one upload</span>
              </div>
              <Link className="ghostlink" href="#how">See how a drop goes out <Icon id="arr" size={16} /></Link>
            </div>
            <HeroStack />
          </div>
        </section>

        {/* ------------------------------------------------------- marquee */}
        <div className="marq" aria-label="Platforms we post to">
          <p className="mono">Posts where your audience already is</p>
          <div className="track">
            {[0, 1, 2, 3].flatMap((r) => PLATFORMS.map(([i, n]) => (
              <span key={`${r}-${i}`} className="pf" aria-hidden={r > 0}><Icon id={i} />{n}</span>
            )))}
          </div>
        </div>

        {/* --------------------------------------------------------- stats */}
        <section className="s" style={{ paddingTop: 90, paddingBottom: 90 }}>
          <div className="wrap">
            <div className="stats">
              <div className="stat rv"><b data-count="800" data-suf="+">800+</b><span className="mono">Artists &amp; brands</span></div>
              <div className="stat rv"><b data-count="50" data-suf="M+">50M+</b><span className="mono">Views delivered</span></div>
              <div className="stat rv"><b data-count="4">4</b><span className="mono">Platforms per drop</span></div>
              <div className="stat rv"><b>24/7</b><span className="mono">Always posting</span></div>
            </div>
          </div>
        </section>

        {/* ------------------------------------------------------ pillars */}
        <section className="s" id="platform" style={{ background: "var(--bg-2)" }}>
          <div className="wrap">
            <span className="mono eyebrow rv">One platform, three jobs</span>
            <h2 className="h2 rv" style={{ maxWidth: 900 }}>
              Only Icreateflow cuts the clips, posts them everywhere and works the replies — from the accounts you already own.
            </h2>
            <div className="pillars">
              <div className="pl rv">
                <span className="ic"><Ico size={22}><circle cx="6" cy="6" r="3" /><circle cx="6" cy="18" r="3" /><path d="M20 4 8.1 15.9M14.5 14.5 20 20M8.1 8.1 12 12" /></Ico></span>
                <h3>Clip</h3>
                <p>Turn a set, an album or an episode into a stack of short vertical clips — captions on, the artist attached, ready for every feed.</p>
                <Link className="btn btn-ink" href="/clipping">Open the clipping studio</Link>
                <Link className="btn btn-ghost" href="#clipping">How clipping works</Link>
              </div>
              <div className="pl rv">
                <span className="ic"><Ico size={22}><path d="M4.5 16.5c-1.5 1.3-2 5-2 5s3.7-.5 5-2c.7-.8.7-2.1-.1-2.9a2.2 2.2 0 0 0-2.9-.1z" /><path d="m12 15-3-3a22 22 0 0 1 2-3.9A12.9 12.9 0 0 1 22 2c0 2.7-.8 7.5-6 11a22 22 0 0 1-4 2z" /></Ico></span>
                <h3>Post</h3>
                <p>Set posts-per-day, a window in your timezone and a view target. The scheduler fans the catalog across every handle until the number lands.</p>
                <Link className="btn btn-ink" href="/register">Launch a campaign</Link>
                <Link className="btn btn-ghost" href="#how">How campaigns pace</Link>
              </div>
              <div className="pl rv">
                <span className="ic"><Ico size={22}><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" /></Ico></span>
                <h3>Reach</h3>
                <p>Outreach replies, follows and messages the people already talking about your niche — from your own accounts, at a pace platforms accept.</p>
                <Link className="btn btn-ink" href="/outreach">Start outreach</Link>
                <Link className="btn btn-ghost" href="#outreach">See outreach</Link>
              </div>
            </div>
          </div>
        </section>

        {/* -------------------------------------------------- posting gap */}
        <section className="s dark">
          <div className="wrap gap">
            <div className="rv">
              <span className="mono eyebrow">The posting gap</span>
              <h2 className="h2">One handle, posting by hand, <em>never keeps up</em> with the drop.</h2>
              <p className="lede" style={{ marginTop: 22 }}>
                A release lives or dies in its first weeks. Re-uploading the same clip to every account, re-captioning it,
                tracking which handle is flagged, working out when to stop — that is a full-time job nobody signed up for.
              </p>
              <p className="lede" style={{ marginTop: 16 }}>
                And every platform now treats a repeat as spam, so the cost of doing it badly compounds daily.
              </p>
            </div>
            <div className="bubbles" aria-hidden="true">
              <div className="bb" style={{ left: "6%", top: "4%", animationDelay: "0s" }}>Did the clip go out on every handle?</div>
              <div className="bb dim" style={{ right: "2%", top: "8%", animationDelay: "1s" }}>Which account got flagged?</div>
              <div className="bb hot" style={{ left: "30%", top: "34%", animationDelay: "2s" }}>When do we stop posting?</div>
              <div className="bb dim" style={{ left: 0, top: "62%", animationDelay: "3s" }}>Who&apos;s replying to us?</div>
              <div className="bb" style={{ right: 0, top: "70%", animationDelay: "1.5s" }}>Is this a duplicate to TikTok?</div>
            </div>
          </div>
        </section>

        {/* ------------------------------------------------- how it works */}
        <section className="s" id="how">
          <div className="wrap iso">
            <svg viewBox="0 0 440 420" aria-hidden="true">
              <defs>
                <linearGradient id="hubg" x1="0" x2="1"><stop offset="0" stopColor="#0b0d12" /><stop offset="1" stopColor="#262a33" /></linearGradient>
              </defs>
              <g className="lay l3">
                <path d="M220 250 L400 340 L220 420 L40 340 Z" fill="none" stroke="var(--subtle)" strokeOpacity=".6" />
                <g fill="none" stroke="var(--subtle)" strokeOpacity=".7">
                  <circle cx="160" cy="330" r="12" /><circle cx="220" cy="300" r="12" /><circle cx="280" cy="330" r="12" /><circle cx="220" cy="360" r="12" />
                  <circle cx="110" cy="345" r="12" /><circle cx="330" cy="345" r="12" /><circle cx="220" cy="395" r="10" />
                </g>
                <text x="300" y="400" fontFamily="var(--font-mono)" fontSize="10" fill="var(--subtle)" transform="rotate(-27 300 400)">AUDIENCE</text>
              </g>
              <g className="lay l2">
                <path d="M220 150 L400 240 L220 320 L40 240 Z" fill="var(--card)" stroke="var(--line)" />
                <g fill="var(--fg)" color="var(--fg)">
                  <use href="#tt" x="140" y="220" width="22" height="22" /><use href="#yt" x="190" y="196" width="22" height="22" />
                  <use href="#ig" x="240" y="220" width="22" height="22" /><use href="#fb" x="290" y="244" width="22" height="22" />
                  <use href="#xx" x="190" y="250" width="20" height="20" /><use href="#tt" x="250" y="272" width="18" height="18" />
                </g>
                <text x="300" y="300" fontFamily="var(--font-mono)" fontSize="10" fill="var(--subtle)" transform="rotate(-27 300 300)">YOUR ACCOUNTS</text>
              </g>
              <g className="lay l1">
                <path d="M220 40 L400 130 L220 210 L40 130 Z" fill="url(#hubg)" />
                <use href="#mark" x="180" y="92" width="80" height="80" />
              </g>
              <g stroke="var(--subtle)" strokeDasharray="3 4" strokeOpacity=".7"><path d="M40 140 V340" /><path d="M400 140 V340" /><path d="M220 215 V300" /></g>
            </svg>
            <div>
              <span className="mono eyebrow rv">How it works</span>
              <h2 className="h2 rv">From catalog to every feed in three moves.</h2>
              <ol className="steps-txt" style={{ marginTop: 28 }}>
                <li className="rv"><span className="n">01</span><b>Drop the catalog</b><p>Upload MP4s or paste a public Google Drive folder. Add captions, attach the artist or brand, and connect your network of accounts.</p></li>
                <li className="rv"><span className="n">02</span><b>Set a target</b><p>Pick posts-per-day, a posting window in the artist&apos;s timezone, and a view goal. The scheduler fans the catalog out across every handle.</p></li>
                <li className="rv"><span className="n">03</span><b>Watch it land</b><p>Live view counts roll in from every platform. When the target is hit, posting stops. When the catalog runs dry, it pauses until you add more.</p></li>
              </ol>
            </div>
          </div>
        </section>

        {/* ------------------------------------------------- flow diagram */}
        <section className="s flowband">
          <div className="wrap">
            <span className="mono eyebrow rv" style={{ textAlign: "center", display: "block" }}>Runs on the accounts you already own</span>
            <h2 className="h2 rv" style={{ textAlign: "center", maxWidth: 820, margin: "0 auto" }}>One engine between your catalog and every feed it should be in.</h2>
            <div className="flow">
              <div className="fbox rv">
                <div className="mono" style={{ color: "var(--band-muted)", fontSize: 10.5, marginBottom: 4 }}>You bring</div>
                <div className="t hl">Clips &amp; MP4s</div><div className="t">A Google Drive folder</div><div className="t">Brand slides</div><div className="t">Audio &amp; podcasts</div>
              </div>
              <div className="fmid">
                <svg viewBox="0 0 500 340" preserveAspectRatio="none" aria-hidden="true">
                  <g fill="none" stroke="var(--band-muted)" strokeOpacity=".5" strokeWidth="1.4">
                    <path d="M0 170 H200" /><path d="M300 170 H500" />
                    <path className="dash" stroke="var(--subtle)" strokeOpacity="1" d="M250 125 V60 H120" />
                    <path className="dash" stroke="var(--subtle)" strokeOpacity="1" d="M250 125 V60 H380" />
                    <path className="dash" stroke="var(--subtle)" strokeOpacity="1" d="M250 215 V280 H120" />
                    <path className="dash" stroke="var(--subtle)" strokeOpacity="1" d="M250 215 V280 H380" />
                  </g>
                </svg>
                <div className="hub"><Icon id="mark" size={56} /></div>
                <div className="ch" style={{ left: "2%", top: 0 }}><div className="ics"><span><Icon id="tt" /></span><span><Icon id="yt" /></span></div>Short-form video</div>
                <div className="ch lb" style={{ right: "2%", top: 0 }}><div className="ics"><span><Icon id="ig" /></span><span><Icon id="fb" /></span></div>Reels &amp; feed</div>
                <div className="ch" style={{ left: "2%", bottom: 0 }}><div className="ics"><span><Icon id="xx" /></span><span><Icon id="ig" /></span></div>Replies &amp; DMs</div>
                <div className="ch lb" style={{ right: "2%", bottom: 0 }}><div className="ics"><span><Icon id="tt" /></span></div>Your phone, for TikTok</div>
              </div>
              <div className="outs rv">
                <div><i><Icon id="chk" /></i>A view target, hit</div>
                <div><i><Icon id="chk" /></i>Unique posts per handle</div>
                <div><i><Icon id="chk" /></i>Pauses when the catalog runs dry</div>
                <div><i><Icon id="chk" /></i>Replies from real fans</div>
              </div>
            </div>
          </div>
        </section>

        {/* ----------------------------------------------------- features */}
        <section className="s">
          <div className="wrap">
            <span className="mono eyebrow rv">Everything in the engine</span>
            <h2 className="h2 rv" style={{ maxWidth: 760 }}>Built for a catalog, not a single post.</h2>
            <div className="fg">
              {FEATURES.map((f) => (
                <div key={f.title} className="fi rv">
                  <span className="ic"><Ico>{f.icon}</Ico></span>
                  <h3>{f.title}</h3>
                  <p>{f.desc}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* ------------------------------------------------- split panels */}
        <section className="s" style={{ background: "var(--bg-2)", paddingTop: 100 }}>
          <div className="wrap">
            <div className="split rv" id="clipping">
              <div className="tx">
                <span className="mono eyebrow">Clipping studio</span>
                <h3>Cut once. Post everywhere.</h3>
                <p className="lede" style={{ fontSize: 16 }}>Hand it a long-form set or an album and get back captioned vertical clips, each tied to the artist — then straight into a campaign.</p>
                <ul>
                  <li><b>Audio to video:</b> a track becomes a visual clip, with the words on screen</li>
                  <li><b>Captions per platform:</b> written once, varied per handle</li>
                  <li><b>Straight to schedule:</b> clips land in the artist&apos;s campaign queue</li>
                </ul>
                <Link className="arrow" href="/clipping">Explore clipping <Icon id="arr" size={16} /></Link>
              </div>
              <div className="vis">
                <div className="vcard">
                  <div className="mono" style={{ fontSize: 10.5, color: "rgba(255,255,255,.7)" }}>Audio to video · Night Drive</div>
                  <div className="wave">
                    {Array.from({ length: 42 }, (_, i) => (
                      <i key={i} style={{ height: `${20 + Math.abs(Math.sin(i * 0.7)) * 80}%`, animationDelay: `${(i % 7) * 0.09}s` }} />
                    ))}
                  </div>
                  <div className="vrow"><i>01</i>Hook — 0:12<small>READY</small></div>
                  <div className="vrow"><i>02</i>Chorus — 0:58<small>READY</small></div>
                  <div className="vrow"><i>03</i>Bridge — 2:04<small>RENDERING</small></div>
                  <div className="vfoot"><Icon id="mark" size={16} />Clipped by Icreateflow</div>
                </div>
              </div>
            </div>

            <div className="split rev rv" id="outreach">
              <div className="vis">
                <div className="vcard">
                  <div className="mono" style={{ fontSize: 10.5, color: "rgba(255,255,255,.7)" }}>Outreach · comment reply</div>
                  <div className="msg">this beat is insane, who made it??<small>@kemi.wav · TikTok</small></div>
                  <div className="msg me">It&apos;s Night Drive by Northside — full track on our page 🎧<small>sent from your account</small></div>
                  <div className="msg">following now 🔥<small>@kemi.wav</small></div>
                </div>
              </div>
              <div className="tx">
                <span className="mono eyebrow">Outreach</span>
                <h3>Talk to the people already looking for you.</h3>
                <p className="lede" style={{ fontSize: 16 }}>Point it at a post, a hashtag or a competitor&apos;s comments. It reads the list, then replies, follows and messages — from your accounts, never a bot farm.</p>
                <ul>
                  <li><b>Every reply reworded:</b> a repeat is a reply nobody sees</li>
                  <li><b>Paced like a person:</b> daily limits each platform accepts</li>
                  <li><b>TikTok from your own phone:</b> follows that actually stick</li>
                </ul>
                <Link className="arrow" href="/outreach">See outreach <Icon id="arr" size={16} /></Link>
              </div>
            </div>
          </div>
        </section>

        {/* ------------------------------------------------------- who */}
        <section className="s" id="who">
          <div className="wrap">
            <span className="mono eyebrow rv">Who it&apos;s built for</span>
            <h2 className="h2 rv" style={{ maxWidth: 760 }}>Anyone with a catalog and a release date.</h2>
            <div className="vg">
              {VERTICALS.map((v) => (
                <div key={v.title} className="vt rv">
                  <span className="ic"><Ico size={20}>{v.icon}</Ico></span>
                  <h3>{v.title}</h3>
                  <p>{v.desc}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        <Pricing />

        {/* ------------------------------------------------------- faq */}
        <section className="s" id="faq">
          <div className="wrap faq">
            <div className="rv"><span className="mono eyebrow">Questions</span><h2 className="h2">The things people ask before their first drop.</h2></div>
            <div className="rv">
              {FAQ.map(([q, a], i) => (
                <details key={q} open={i === 0}>
                  <summary>{q}<span>+</span></summary>
                  <p>{a}</p>
                </details>
              ))}
            </div>
          </div>
        </section>

        {/* ------------------------------------------------- closing band */}
        <section className="s cta">
          <div className="shapes"><i /><i /><i /></div>
          <div className="wrap">
            <span className="mono" style={{ display: "block", marginBottom: 18, opacity: 0.7 }}>Your next drop</span>
            <h2 className="rv">Hand us the catalog. We&apos;ll keep it in every feed until the numbers land.</h2>
            <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginTop: 36 }} className="rv">
              <Link className="btn btn-lime" href="/register">Launch a campaign <Icon id="arr" /></Link>
              <Link className="btn btn-ghost" href="/login">Log in</Link>
            </div>
            <div className="cards3">
              <div className="c3 rv"><h3>See it in action</h3><p>Walk through a live campaign — pacing, variations and view tracking — with the team.</p><Link className="btn btn-ink" href="/login">Get a demo</Link></div>
              <div className="c3 rv"><h3>Help &amp; support</h3><p>Guides for connecting accounts, setting targets and running outreach safely.</p><Link className="btn btn-ink" href="/help">Visit help</Link></div>
              <div className="c3 rv"><h3>Already a member?</h3><p>Pick up where your campaigns left off. Everything is still in rotation.</p><Link className="btn btn-ink" href="/login">Log in</Link></div>
            </div>
          </div>
        </section>
      </main>
    </MarketingShell>
  );
}
