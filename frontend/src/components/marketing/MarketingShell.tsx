/**
 * The frame of the public pages — announcement bar, nav, footer — around
 * home, Terms and Privacy, built from the approved preview.
 *
 * Nav items are plain links to the home page's sections. The preview drew
 * a chevron beside two of them; there are no menus behind them, and a
 * chevron promises one, so they are left off.
 */
import Link from "next/link";
import "./marketing.css";
import Sprite, { Icon } from "./Sprite";
import ThemeSwitch from "./ThemeSwitch";
import Effects from "./Effects";
import HelpChat from "./HelpChat";

// Read outside render (react-hooks/purity forbids the clock in render).
function currentYear() {
  return new Date().getFullYear();
}

export default function MarketingShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="mk">
      <Sprite />
      <Effects />
      <HelpChat />

      <div className="announce">
        New — Outreach: reply, follow and message from your own accounts, on autopilot.{" "}
        <Link href="/#outreach">See how it works →</Link>
      </div>

      <header className="nav">
        <div className="wrap">
          <Link className="logo" href="/" aria-label="Icreateflow home">
            <span className="tile"><Icon id="mark" size={24} /></span><b>Icreateflow</b>
          </Link>
          <ul>
            <li><Link href="/#platform">Platform</Link></li>
            <li><Link href="/#who">Who it&apos;s for</Link></li>
            <li><Link href="/#how">How it works</Link></li>
            <li><Link href="/#pricing">Pricing</Link></li>
            <li><Link href="/#faq">FAQ</Link></li>
          </ul>
          <div className="right">
            <ThemeSwitch />
            <Link className="btn btn-ghost" href="/login">Log in</Link>
            <Link className="btn btn-ink" href="/register">
              <span className="long">Launch a campaign</span><span className="short">Start</span>
            </Link>
          </div>
        </div>
      </header>

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
  );
}
