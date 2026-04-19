"use client";

import Link from "next/link";
import {
  Megaphone,
  Shield,
  BarChart3,
  Globe,
  Sparkles,
  ArrowRight,
  Check,
  LogIn,
  UserPlus,
  Rocket,
  Target,
  Users,
  Music,
  Film,
  Mic,
  Package,
} from "lucide-react";
import ThemeToggle from "@/components/ThemeToggle";
import Logo from "@/components/Logo";

const features = [
  {
    icon: Megaphone,
    title: "Campaign-driven promotion",
    desc: "Launch a campaign with a clear view target. Our engine keeps pushing the content across every connected account until the number is hit — then stops automatically.",
  },
  {
    icon: Users,
    title: "Variation account network",
    desc: "Fan a single drop across dozens of TikTok, YouTube, Instagram and Facebook handles you control — different angles, different audiences, same catalog.",
  },
  {
    icon: Globe,
    title: "Cross-platform reach",
    desc: "TikTok, YouTube Shorts, Instagram Reels, Facebook — every clip hits every feed from one upload. No re-uploading, no re-captioning per handle.",
  },
  {
    icon: Sparkles,
    title: "AI anti-duplicate engine",
    desc: "For brand slides we generate unique face variations per account and vary overlays so platforms treat each post as original — reach stays high, duplicate flags stay away.",
  },
  {
    icon: BarChart3,
    title: "Live view tracking",
    desc: "Aggregated view counts across every variation, refreshed in the background. Watch a campaign climb toward its target in real time.",
  },
  {
    icon: Shield,
    title: "Auto-pause & auto-resume",
    desc: "Directory runs dry? The system pauses. You upload new clips or sync another Drive folder — it picks up where it left off without missing a slot.",
  },
];

const verticals = [
  { icon: Music, label: "Music artists" },
  { icon: Film, label: "Movies & trailers" },
  { icon: Mic, label: "Podcasts" },
  { icon: Package, label: "Brand products" },
];

export default function LandingPage() {
  return (
    <div className="min-h-screen bg-background">
      {/* Nav */}
      <nav className="sticky top-0 z-50 border-b border-border bg-background/80 backdrop-blur-md">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-4 py-3 md:px-6 md:py-4">
          <Link href="/landing" className="flex items-center gap-2">
            <Logo size={32} radius={8} />
            <span className="text-lg font-bold tracking-tight text-foreground md:text-xl">Icreateflow</span>
          </Link>
          <div className="flex items-center gap-2 md:gap-3">
            <ThemeToggle />
            <Link href="/login" className="inline-flex items-center justify-center rounded-xl p-2.5 text-foreground transition-opacity hover:opacity-70 md:px-4 md:py-2" aria-label="Log in">
              <LogIn className="h-4 w-4 md:hidden" />
              <span className="hidden md:inline text-sm font-medium">Log in</span>
            </Link>
            <Link href="/login" className="inline-flex items-center justify-center rounded-xl bg-foreground p-2.5 text-background transition-opacity hover:opacity-90 md:px-5 md:py-2.5" aria-label="Get a demo">
              <Rocket className="h-4 w-4 md:hidden" />
              <span className="hidden md:inline text-sm font-semibold">Get a demo</span>
            </Link>
            <Link href="/register" className="inline-flex items-center justify-center rounded-xl bg-lime p-2.5 text-black transition-all hover:brightness-95 md:px-5 md:py-2.5" aria-label="Launch a campaign">
              <UserPlus className="h-4 w-4 md:hidden" />
              <span className="hidden md:inline text-sm font-bold">Launch a campaign</span>
            </Link>
          </div>
        </div>
      </nav>

      {/* Hero */}
      <section className="relative overflow-hidden py-16 md:py-36">
        <div className="absolute top-20 left-[10%] h-32 w-32 rounded-3xl bg-lime/20 blur-3xl animate-float" />
        <div className="absolute bottom-20 right-[15%] h-40 w-40 rounded-full bg-foreground/5 blur-2xl animate-float-slow delay-500" />
        <div className="absolute top-1/2 left-[60%] h-20 w-20 rounded-2xl bg-lime/10 blur-xl animate-float-reverse delay-300" />

        <div className="relative mx-auto max-w-5xl px-5 text-center md:px-6">
          <div className="mb-5 inline-flex items-center gap-2 rounded-full border border-border bg-card px-4 py-1.5 text-sm animate-slide-up">
            <span className="h-2 w-2 rounded-full bg-lime animate-pulse-soft" />
            <span className="font-medium text-foreground">The promotion engine for modern creators</span>
          </div>

          <h1 className="mb-5 text-3xl font-black leading-[1.1] tracking-tight text-foreground sm:text-4xl md:text-6xl lg:text-7xl animate-slide-up delay-100">
            The promotion engine
            <span className="block">behind every drop.</span>
          </h1>

          <p className="mx-auto mb-8 max-w-2xl text-sm text-muted-foreground sm:text-base md:text-lg animate-slide-up delay-200">
            Artists, labels, studios, and podcast networks hand us their catalog.
            We put it into rotation across a network of TikTok, YouTube,
            Instagram and Facebook accounts — on schedule, toward a view target,
            until the numbers land.
          </p>

          <div className="flex flex-col items-center gap-3 sm:flex-row sm:justify-center animate-slide-up delay-300">
            <input
              type="email"
              placeholder="Enter your email"
              className="w-full rounded-xl border border-border bg-card px-5 py-3.5 text-sm text-foreground outline-none focus:border-foreground transition-colors placeholder:text-muted-foreground sm:w-72"
            />
            <Link href="/register"
              className="group inline-flex w-full items-center justify-center gap-2 rounded-xl bg-lime px-7 py-3.5 text-sm font-bold text-black hover:brightness-95 transition-all sm:w-auto">
              Start promoting
              <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
            </Link>
          </div>

          <div className="mt-8 flex flex-wrap items-center justify-center gap-4 text-xs text-muted-foreground sm:gap-6 sm:text-sm animate-slide-up delay-500">
            {["Set a view target", "Auto-paces around the clock", "Four platforms, one upload"].map((t) => (
              <span key={t} className="flex items-center gap-1.5">
                <Check className="h-3.5 w-3.5 text-foreground" />
                {t}
              </span>
            ))}
          </div>
        </div>
      </section>

      {/* Verticals we push */}
      <section className="border-y border-border bg-card py-8 md:py-10">
        <div className="mx-auto max-w-5xl px-5 md:px-6">
          <p className="mb-5 text-center text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Built to promote
          </p>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            {verticals.map((v) => (
              <div key={v.label} className="flex items-center justify-center gap-2 rounded-xl bg-background/60 px-4 py-3">
                <v.icon className="h-4 w-4 text-foreground" />
                <span className="text-sm font-semibold text-foreground">{v.label}</span>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Social proof */}
      <section className="py-6 md:py-8">
        <div className="mx-auto grid max-w-4xl grid-cols-2 gap-6 px-6 md:grid-cols-4">
          {[
            { n: "800+", l: "Artists & brands" },
            { n: "50M+", l: "Views delivered" },
            { n: "4", l: "Platforms per drop" },
            { n: "24/7", l: "Always posting" },
          ].map((s) => (
            <div key={s.l} className="text-center">
              <p className="text-xl font-bold tracking-tight text-foreground md:text-2xl">{s.n}</p>
              <p className="text-xs text-muted-foreground">{s.l}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Features */}
      <section className="py-16 md:py-24">
        <div className="mx-auto max-w-6xl px-5 md:px-6">
          <div className="mb-12 text-center md:mb-16">
            <h2 className="mb-3 text-2xl font-bold tracking-tight text-foreground md:text-4xl">
              A distribution machine, not another scheduler.
            </h2>
            <p className="mx-auto max-w-2xl text-sm text-muted-foreground md:text-base">
              Schedulers post once. Icreateflow keeps a catalog in rotation across
              every handle you own until the numbers come in.
            </p>
          </div>

          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 md:gap-5">
            {features.map((f, i) => (
              <div key={f.title}
                className="group rounded-2xl bg-card p-6 transition-all hover:shadow-lg hover:-translate-y-0.5 animate-slide-up md:p-7"
                style={{ animationDelay: `${i * 0.1}s` }}>
                <div className="mb-4 inline-flex h-11 w-11 items-center justify-center rounded-xl bg-foreground transition-transform group-hover:scale-110 md:mb-5 md:h-12 md:w-12">
                  <f.icon className="h-4 w-4 text-background md:h-5 md:w-5" />
                </div>
                <h3 className="mb-2 text-base font-bold text-foreground md:text-lg">{f.title}</h3>
                <p className="text-sm leading-relaxed text-muted-foreground">{f.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* How it works */}
      <section className="border-t border-border py-16 md:py-24">
        <div className="mx-auto max-w-5xl px-5 md:px-6">
          <div className="mb-12 text-center md:mb-16">
            <h2 className="mb-3 text-2xl font-bold tracking-tight text-foreground md:text-4xl">
              How a campaign runs
            </h2>
            <p className="text-sm text-muted-foreground md:text-base">
              From drop to delivered views, without hand-posting a single clip.
            </p>
          </div>

          <div className="grid gap-8 md:grid-cols-3">
            {[
              {
                step: "01",
                title: "Drop the catalog",
                desc: "Upload MP4s or paste a public Google Drive folder. Add captions, attach the artist or brand, and connect your network of accounts.",
              },
              {
                step: "02",
                title: "Set a target",
                desc: "Pick posts-per-day, a posting window in the artist's timezone, and a view goal. The scheduler fans the catalog out across every handle.",
              },
              {
                step: "03",
                title: "Watch it land",
                desc: "Live view counts roll in from every platform. When the target is hit, posting stops. When the catalog runs dry, it pauses until you add more.",
              },
            ].map((s, i) => (
              <div key={s.step} className="relative text-center animate-slide-up" style={{ animationDelay: `${i * 0.15}s` }}>
                <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-2xl bg-foreground text-lg font-black text-background md:mb-5 md:h-14 md:w-14 md:text-xl">
                  {s.step}
                </div>
                <h3 className="mb-2 text-base font-bold text-foreground md:text-lg">{s.title}</h3>
                <p className="text-sm text-muted-foreground">{s.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Stats */}
      <section className="py-16 md:py-20">
        <div className="mx-auto max-w-6xl px-5 md:px-6">
          <div className="grid gap-4 sm:grid-cols-3 md:gap-5">
            {[
              { stat: "10x", label: "Reach per upload", desc: "vs. posting from a single handle" },
              { stat: "4", label: "Platforms in parallel", desc: "TikTok, YouTube, Instagram, Facebook" },
              { stat: "100%", label: "Target-driven", desc: "campaigns halt the moment the goal lands" },
            ].map((s) => (
              <div key={s.stat} className="rounded-2xl bg-card p-6 md:p-7">
                <p className="text-sm text-muted-foreground">{s.desc}</p>
                <p className="mt-2 text-4xl font-black tracking-tight text-foreground md:mt-3 md:text-5xl">{s.stat}</p>
                <p className="mt-1 text-sm font-semibold text-foreground">{s.label}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className="py-16 md:py-20">
        <div className="mx-auto max-w-4xl px-5 md:px-6">
          <div className="relative overflow-hidden rounded-2xl bg-foreground px-6 py-14 text-center text-background md:rounded-3xl md:px-16 md:py-20">
            <div className="absolute top-6 left-8 h-16 w-16 rounded-2xl bg-white/5 animate-float" />
            <div className="absolute bottom-8 right-12 h-12 w-12 rounded-full bg-white/5 animate-float-slow delay-300" />

            <Target className="relative mx-auto mb-4 h-7 w-7 text-lime md:h-8 md:w-8" />
            <h2 className="relative mb-3 text-2xl font-bold tracking-tight md:mb-4 md:text-4xl">
              Pick a number. We&rsquo;ll chase it.
            </h2>
            <p className="relative mx-auto mb-6 max-w-xl text-sm text-background/60 md:mb-8 md:text-base">
              Whether it&rsquo;s a new single, a movie trailer, a podcast drop or a
              product launch — set the view target and let the engine do the laps.
            </p>
            <Link href="/register"
              className="relative inline-flex items-center gap-2 rounded-xl bg-lime px-6 py-3 text-sm font-bold text-black hover:brightness-95 transition-all md:px-8 md:py-3.5">
              Launch your first campaign <ArrowRight className="h-4 w-4" />
            </Link>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t border-border py-8 md:py-10">
        <div className="mx-auto flex max-w-6xl flex-col items-center gap-4 px-6 text-xs text-muted-foreground md:flex-row md:justify-between md:text-sm">
          <p>&copy; {new Date().getFullYear()} Icreateflow. The promotion engine for artists, brands &amp; creators.</p>
          <nav className="flex flex-wrap items-center justify-center gap-x-6 gap-y-2">
            <Link href="/terms" className="transition-colors hover:text-foreground">Terms &amp; Conditions</Link>
            <Link href="/privacy" className="transition-colors hover:text-foreground">Privacy Policy</Link>
            <Link href="/login" className="transition-colors hover:text-foreground">Log in</Link>
            <Link href="/register" className="transition-colors hover:text-foreground">Sign up</Link>
          </nav>
        </div>
      </footer>
    </div>
  );
}
