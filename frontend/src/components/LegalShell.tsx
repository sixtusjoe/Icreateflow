"use client";

import Link from "next/link";
import { LogIn, UserPlus, Rocket } from "lucide-react";
import ThemeToggle from "@/components/ThemeToggle";
import Logo from "@/components/Logo";

type Props = {
  title: string;
  subtitle?: string;
  lastUpdated: string;
  children: React.ReactNode;
};

/**
 * Shared shell for legal pages (Terms & Conditions, Privacy Policy).
 * Mirrors the landing-page nav and footer so legal content sits inside
 * the same brand chrome without duplicating that markup per page.
 */
export default function LegalShell({ title, subtitle, lastUpdated, children }: Props) {
  return (
    <div className="min-h-screen bg-background">
      {/* Nav — same look as landing */}
      <nav className="sticky top-0 z-50 border-b border-border bg-background/80 backdrop-blur-md">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-4 py-3 md:px-6 md:py-4">
          <Link href="/" className="flex items-center gap-2">
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
            <Link href="/register" className="inline-flex items-center justify-center rounded-xl bg-lime p-2.5 text-black transition-all hover:brightness-95 md:px-5 md:py-2.5" aria-label="Sign up free">
              <UserPlus className="h-4 w-4 md:hidden" />
              <span className="hidden md:inline text-sm font-bold">Sign up free</span>
            </Link>
          </div>
        </div>
      </nav>

      {/* Hero */}
      <header className="border-b border-border bg-card py-14 md:py-20">
        <div className="mx-auto max-w-3xl px-5 text-center md:px-6">
          <p className="mb-3 text-xs font-semibold uppercase tracking-[0.2em] text-muted-foreground">Legal</p>
          <h1 className="text-3xl font-black tracking-tight text-foreground md:text-5xl">{title}</h1>
          {subtitle && (
            <p className="mx-auto mt-4 max-w-2xl text-sm text-muted-foreground md:text-base">
              {subtitle}
            </p>
          )}
          <p className="mt-5 text-xs text-muted-foreground">Last updated: {lastUpdated}</p>
        </div>
      </header>

      {/* Content */}
      <main className="mx-auto max-w-3xl px-5 py-12 md:px-6 md:py-16">
        <article className="legal-prose space-y-6 text-sm leading-relaxed text-foreground/90 md:text-base">
          {children}
        </article>
      </main>

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

export function Section({
  id,
  number,
  title,
  children,
}: {
  id?: string;
  number: string;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section id={id} className="scroll-mt-24">
      <h2 className="mb-3 text-lg font-bold text-foreground md:text-xl">
        <span className="mr-2 text-muted-foreground">{number}.</span>
        {title}
      </h2>
      <div className="space-y-3 text-foreground/80">{children}</div>
    </section>
  );
}
