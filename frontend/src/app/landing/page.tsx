"use client";

import Link from "next/link";
import { Zap, Shield, BarChart3, Layers, Globe, Sparkles, ArrowRight, Check, LogIn, UserPlus, Rocket } from "lucide-react";
import ThemeToggle from "@/components/ThemeToggle";

const features = [
  { icon: Layers, title: "Multi-Brand Management", desc: "Manage unlimited brands with separate accounts, handles, and posting strategies from one dashboard." },
  { icon: Zap, title: "Smart OCR Extraction", desc: "AI-powered text extraction reads overlay text from slide images — titles, hooks, CTAs — automatically." },
  { icon: Globe, title: "Cross-Platform Posting", desc: "Post to TikTok, YouTube Shorts, Instagram Reels, and Facebook from a single workflow." },
  { icon: Sparkles, title: "AI Image Generation", desc: "Generate unique face variations for each account using Flux AI — no more duplicate content flags." },
  { icon: BarChart3, title: "Scheduling & Calendar", desc: "Plan your content calendar weeks in advance. Schedule posts with automatic timezone handling." },
  { icon: Shield, title: "Team Collaboration", desc: "Invite team members, assign roles, and manage permissions. Admin controls for full oversight." },
];

export default function LandingPage() {
  return (
    <div className="min-h-screen bg-background">
      {/* Nav */}
      <nav className="sticky top-0 z-50 border-b border-border bg-background/80 backdrop-blur-md">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-4 py-3 md:px-6 md:py-4">
          <Link href="/landing" className="flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-foreground text-xs font-bold text-background">IC</div>
            <span className="text-lg font-bold tracking-tight text-foreground md:text-xl">ICREATE</span>
          </Link>
          <div className="flex items-center gap-2 md:gap-3">
            <ThemeToggle />
            {/* Mobile: icon buttons | Desktop: full buttons */}
            <Link href="/login" className="inline-flex items-center justify-center rounded-xl p-2.5 text-foreground transition-opacity hover:opacity-70 md:px-4 md:py-2" aria-label="Log in">
              <LogIn className="h-4 w-4 md:hidden" />
              <span className="hidden md:inline text-sm font-medium">Log in</span>
            </Link>
            <Link href="/login" className="inline-flex items-center justify-center rounded-xl bg-foreground p-2.5 text-background transition-opacity hover:opacity-90 md:px-5 md:py-2.5" aria-label="Get a demo">
              <Rocket className="h-4 w-4 md:hidden" />
              <span className="hidden md:inline text-sm font-semibold">Get a demo</span>
            </Link>
            <Link href="/register" className="inline-flex items-center justify-center rounded-xl bg-lime p-2.5 text-black transition-all hover:brightness-95 md:px-5 md:py-2.5" aria-label="Sign up free">
              <UserPlus className="h-4 w-4 md:hidden" />
              <span className="hidden md:inline text-sm font-bold">Sign up free</span>
            </Link>
          </div>
        </div>
      </nav>

      {/* Hero */}
      <section className="relative overflow-hidden py-16 md:py-36">
        {/* Floating bg shapes */}
        <div className="absolute top-20 left-[10%] h-32 w-32 rounded-3xl bg-lime/20 blur-3xl animate-float" />
        <div className="absolute bottom-20 right-[15%] h-40 w-40 rounded-full bg-foreground/5 blur-2xl animate-float-slow delay-500" />
        <div className="absolute top-1/2 left-[60%] h-20 w-20 rounded-2xl bg-lime/10 blur-xl animate-float-reverse delay-300" />

        <div className="relative mx-auto max-w-5xl px-5 text-center md:px-6">
          <div className="mb-5 inline-flex items-center gap-2 rounded-full border border-border bg-card px-4 py-1.5 text-sm animate-slide-up">
            <span className="h-2 w-2 rounded-full bg-lime animate-pulse-soft" />
            <span className="font-medium text-foreground">Scale content 10x faster</span>
          </div>

          <h1 className="mb-5 text-3xl font-black leading-[1.1] tracking-tight text-foreground sm:text-4xl md:text-6xl lg:text-7xl animate-slide-up delay-100">
            The content platform for
            <span className="block">smarter, faster scaling</span>
          </h1>

          <p className="mx-auto mb-8 max-w-2xl text-sm text-muted-foreground sm:text-base md:text-lg animate-slide-up delay-200">
            Import TikTok slideshows, generate unique variations for every account,
            and post everywhere — built for content creators.
          </p>

          <div className="flex flex-col items-center gap-3 sm:flex-row sm:justify-center animate-slide-up delay-300">
            <input
              type="email"
              placeholder="Enter your email"
              className="w-full rounded-xl border border-border bg-card px-5 py-3.5 text-sm text-foreground outline-none focus:border-foreground transition-colors placeholder:text-muted-foreground sm:w-72"
            />
            <Link href="/register"
              className="group inline-flex w-full items-center justify-center gap-2 rounded-xl bg-lime px-7 py-3.5 text-sm font-bold text-black hover:brightness-95 transition-all sm:w-auto">
              Get started
              <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
            </Link>
          </div>

          {/* Trust badges */}
          <div className="mt-8 flex flex-wrap items-center justify-center gap-4 text-xs text-muted-foreground sm:gap-6 sm:text-sm animate-slide-up delay-500">
            {["Free forever", "No credit card", "Setup in 2 min"].map((t) => (
              <span key={t} className="flex items-center gap-1.5">
                <Check className="h-3.5 w-3.5 text-foreground" />
                {t}
              </span>
            ))}
          </div>
        </div>
      </section>

      {/* Social proof bar */}
      <section className="border-y border-border bg-card py-6 md:py-8">
        <div className="mx-auto grid max-w-4xl grid-cols-2 gap-6 px-6 md:grid-cols-4">
          {[
            { n: "800+", l: "Content Creators" },
            { n: "50K+", l: "Posts Generated" },
            { n: "4", l: "Platforms" },
            { n: "99.9%", l: "Uptime" },
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
              Everything you need
            </h2>
            <p className="mx-auto max-w-2xl text-sm text-muted-foreground md:text-base">
              From importing to posting — powered by AI.
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
            <h2 className="mb-3 text-2xl font-bold tracking-tight text-foreground md:text-4xl">How it works</h2>
            <p className="text-sm text-muted-foreground md:text-base">Three steps to scale your content empire.</p>
          </div>

          <div className="grid gap-8 md:grid-cols-3">
            {[
              { step: "01", title: "Import", desc: "Paste a TikTok URL or upload your slides. We extract text with OCR automatically." },
              { step: "02", title: "Customize", desc: "Edit text, generate AI face variations for each account, and review everything." },
              { step: "03", title: "Publish", desc: "Generate final content and schedule across TikTok, YouTube, Instagram, and Facebook." },
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
              { stat: "10x", label: "Faster content scaling", desc: "compared to manual workflows" },
              { stat: "4+", label: "Platforms supported", desc: "TikTok, YouTube, Instagram, Facebook" },
              { stat: "100%", label: "Unique variations", desc: "AI-generated per account" },
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

            <h2 className="relative mb-3 text-2xl font-bold tracking-tight md:mb-4 md:text-4xl">
              Ready to scale your content?
            </h2>
            <p className="relative mx-auto mb-6 max-w-xl text-sm text-background/50 md:mb-8 md:text-base">
              Join creators who are multiplying their reach across every platform.
            </p>
            <Link href="/register"
              className="relative inline-flex items-center gap-2 rounded-xl bg-lime px-6 py-3 text-sm font-bold text-black hover:brightness-95 transition-all md:px-8 md:py-3.5">
              Sign up for free <ArrowRight className="h-4 w-4" />
            </Link>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t border-border py-6 md:py-8">
        <div className="mx-auto max-w-6xl px-6 text-center text-xs text-muted-foreground md:text-sm">
          <p>&copy; {new Date().getFullYear()} ICREATE. Built for content creators.</p>
        </div>
      </footer>
    </div>
  );
}
