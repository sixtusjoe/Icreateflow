/**
 * The frame of the public pages — announcement bar, nav, footer — around
 * home, Terms and Privacy, built from the approved preview.
 */
import Link from "next/link";
import "./marketing.css";
import Sprite, { Icon } from "./Sprite";
import Nav from "./Nav";
import Effects from "./Effects";
import PublicAssistant from "./PublicAssistant";

// Read outside render (react-hooks/purity forbids the clock in render).
function currentYear() {
  return new Date().getFullYear();
}

export default function MarketingShell({ children }: { children: React.ReactNode }) {
  return (
    <>
    <div className="mk">
      <Sprite />
      <Effects />

      <div className="announce">
        <span className="long">New — Outreach: reply, follow and message from your own accounts, on autopilot. </span>
        <span className="short">New — Outreach on autopilot. </span>
        <Link href="/#outreach"><span className="long">See how it works</span><span className="short">See how</span> →</Link>
      </div>

      <Nav />

      {children}

      <footer>
        <div className="wrap">
          <div className="fgrid">
            <div>
              <Link className="logo" href="/"><span className="tile"><Icon id="mark" size={24} /></span><b>Icreateflow</b></Link>
              <p className="about">The promotion engine for artists, labels, studios and podcast networks. Your catalog, in every feed, until the numbers land.</p>
              <Link className="btn btn-ink" href="/register" style={{ height: 44, fontSize: 14 }}>
                Launch a campaign <Icon id="arr" />
              </Link>
            </div>
            <div>
              <h4 className="mono">Platform</h4>
              <Link href="/#platform">Campaigns</Link>
              <Link href="/#clipping">Clipping studio</Link>
              <Link href="/#clipping">Audio to video</Link>
              <Link href="/#outreach">Outreach</Link>
              <Link href="/#how">Scheduling</Link>
              <Link href="/#pricing">Pricing</Link>
            </div>
            <div>
              <h4 className="mono">Built for</h4>
              <Link href="/#who">Music artists &amp; labels</Link>
              <Link href="/#who">Movies &amp; trailers</Link>
              <Link href="/#who">Podcasts</Link>
              <Link href="/#who">Brand products</Link>
            </div>
            <div>
              <h4 className="mono">Company</h4>
              <Link href="/help">Help &amp; Support</Link>
              <Link href="/terms">Terms &amp; Conditions</Link>
              <Link href="/privacy">Privacy Policy</Link>
              <Link href="/login">Log in</Link>
              <Link href="/register">Sign up</Link>
            </div>
          </div>
          <div className="wm" aria-hidden="true">Icreateflow</div>
          <div className="fbot">
            <span>© {currentYear()} Icreateflow. All rights reserved.</span>
            <span style={{ display: "flex", gap: 16 }} aria-hidden="true">
              <Icon id="tt" size={18} /><Icon id="ig" size={18} /><Icon id="yt" size={18} /><Icon id="xx" size={18} />
            </span>
          </div>
        </div>
      </footer>
    </div>
    {/* Outside .mk, so the public pages' own button and input resets cannot
        reach it — it should render exactly as it does inside the app. */}
    <PublicAssistant />
    </>
  );
}
