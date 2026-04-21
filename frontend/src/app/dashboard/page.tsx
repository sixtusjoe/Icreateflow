"use client";

import { useEffect, useState } from "react";
import { Tags, Users, FileText, CalendarClock, TrendingUp, ArrowRight, PlusCircle, Zap, Mic2, Scissors, Video } from "lucide-react";
import { getStats, getSchedule } from "@/lib/api";
import Link from "next/link";
import { useAuth } from "@/lib/auth";

export default function DashboardPage() {
  const { user } = useAuth();
  const [stats, setStats] = useState({
    brands: 0, accounts: 0, posts_today: 0, scheduled: 0, total_posts: 0,
    artists: 0, variations: 0, clips: 0, clip_posts: 0, clip_scheduled: 0,
  });
  const [scheduled, setScheduled] = useState<any[]>([]);

  useEffect(() => {
    getStats().then((s: any) => setStats((prev) => ({ ...prev, ...s }))).catch(() => {});
    getSchedule().then(setScheduled).catch(() => {});
  }, []);

  const brandsCards = [
    { label: "Brands", value: stats.brands, icon: Tags },
    { label: "Accounts", value: stats.accounts, icon: Users },
    { label: "Posts Today", value: stats.posts_today, icon: FileText },
    { label: "Scheduled", value: stats.scheduled, icon: CalendarClock },
    { label: "Total Posts", value: stats.total_posts, icon: TrendingUp },
  ];
  const clippingCards = [
    { label: "Artists", value: stats.artists, icon: Mic2 },
    { label: "Variations", value: stats.variations, icon: Users },
    { label: "Clips", value: stats.clips, icon: Video },
    { label: "Clip Posts", value: stats.clip_posts, icon: Scissors },
    { label: "Clip Scheduled", value: stats.clip_scheduled, icon: CalendarClock },
  ];

  return (
    <div>
      {/* Welcome header */}
      <div className="mb-6 md:mb-8 animate-slide-up">
        <h1 className="text-xl md:text-2xl font-bold tracking-tight text-foreground">
          Welcome back, {user?.name?.split(" ")[0] || "there"}
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">Here&apos;s what&apos;s happening with your content today.</p>
      </div>

      {/* Brands stats */}
      <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Brands</div>
      <div className="mb-6 md:mb-8 grid grid-cols-2 gap-3 md:gap-4 sm:grid-cols-3 lg:grid-cols-5">
        {brandsCards.map((s, i) => (
          <div key={s.label}
            className="group rounded-2xl bg-card p-4 md:p-5 transition-all hover:shadow-md hover:-translate-y-0.5 animate-slide-up"
            style={{ animationDelay: `${i * 0.08}s` }}>
            <div className="flex items-center justify-between gap-2">
              <div className="min-w-0">
                <p className="text-xs font-medium text-muted-foreground truncate">{s.label}</p>
                <p className="mt-1 text-2xl md:text-3xl font-bold tracking-tight text-foreground">{s.value}</p>
              </div>
              <div className="flex h-9 w-9 md:h-10 md:w-10 flex-shrink-0 items-center justify-center rounded-xl bg-foreground transition-transform group-hover:scale-110">
                <s.icon className="h-4 w-4 text-background" />
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Clipping stats */}
      <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Clipping</div>
      <div className="mb-6 md:mb-8 grid grid-cols-2 gap-3 md:gap-4 sm:grid-cols-3 lg:grid-cols-5">
        {clippingCards.map((s, i) => (
          <div key={s.label}
            className="group rounded-2xl bg-card p-4 md:p-5 transition-all hover:shadow-md hover:-translate-y-0.5 animate-slide-up"
            style={{ animationDelay: `${i * 0.08}s` }}>
            <div className="flex items-center justify-between gap-2">
              <div className="min-w-0">
                <p className="text-xs font-medium text-muted-foreground truncate">{s.label}</p>
                <p className="mt-1 text-2xl md:text-3xl font-bold tracking-tight text-foreground">{s.value}</p>
              </div>
              <div className="flex h-9 w-9 md:h-10 md:w-10 flex-shrink-0 items-center justify-center rounded-xl bg-foreground transition-transform group-hover:scale-110">
                <s.icon className="h-4 w-4 text-background" />
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Quick Actions */}
      <div className="mb-8 animate-slide-up delay-300">
        <h2 className="mb-4 text-base font-bold text-foreground">Quick Actions</h2>
        <div className="flex flex-wrap gap-3">
          <Link href="/posts/new"
            className="group inline-flex min-h-[44px] items-center gap-2 rounded-xl bg-foreground px-4 md:px-5 py-2.5 text-sm font-semibold text-background transition-opacity hover:opacity-90">
            <PlusCircle className="h-4 w-4" />
            New Post
            <ArrowRight className="h-3.5 w-3.5 opacity-40 transition-transform group-hover:translate-x-0.5" />
          </Link>
          <Link href="/brands"
            className="inline-flex min-h-[44px] items-center gap-2 rounded-xl border border-border px-4 md:px-5 py-2.5 text-sm font-medium text-foreground transition-colors hover:bg-muted">
            <Tags className="h-4 w-4" />
            Manage Brands
          </Link>
          <Link href="/clipping"
            className="inline-flex min-h-[44px] items-center gap-2 rounded-xl border border-border px-4 md:px-5 py-2.5 text-sm font-medium text-foreground transition-colors hover:bg-muted">
            <Scissors className="h-4 w-4" />
            Clipping
          </Link>
          <Link href="/schedule"
            className="inline-flex min-h-[44px] items-center gap-2 rounded-xl border border-border px-4 md:px-5 py-2.5 text-sm font-medium text-foreground transition-colors hover:bg-muted">
            <CalendarClock className="h-4 w-4" />
            View Schedule
          </Link>
        </div>
      </div>

      {/* Activity / Tip card */}
      <div className="mb-8 rounded-2xl bg-card p-6 animate-slide-up delay-500">
        <div className="flex items-start gap-4">
          <div className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-xl bg-lime">
            <Zap className="h-5 w-5 text-black" />
          </div>
          <div>
            <h3 className="text-sm font-bold text-foreground">Pro Tip</h3>
            <p className="mt-0.5 text-sm text-muted-foreground">
              Upload your TikTok slides and let AI generate unique variations for each account — save hours of manual work every day.
            </p>
          </div>
        </div>
      </div>

      {/* Scheduled */}
      <div className="animate-slide-up delay-700">
        <h2 className="mb-4 text-base font-bold text-foreground">Upcoming Scheduled Posts</h2>
        {scheduled.length === 0 ? (
          <div className="rounded-2xl bg-card p-8 text-center">
            <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-2xl bg-muted">
              <CalendarClock className="h-5 w-5 text-muted-foreground" />
            </div>
            <p className="font-medium text-foreground">No scheduled posts yet</p>
            <p className="mt-1 text-sm text-muted-foreground">Create your first post to get started.</p>
            <Link href="/posts/new"
              className="mt-4 inline-flex items-center gap-2 rounded-xl bg-foreground px-5 py-2.5 text-sm font-semibold text-background transition-opacity hover:opacity-90">
              <PlusCircle className="h-4 w-4" /> Create Post
            </Link>
          </div>
        ) : (
          <div className="space-y-2">
            {scheduled.slice(0, 10).map((post: any, i: number) => (
              <div key={post.id}
                className="flex flex-col gap-2 rounded-xl bg-card px-4 py-3 transition-colors hover:shadow-sm animate-slide-up sm:flex-row sm:items-center sm:justify-between sm:px-5 sm:py-3.5"
                style={{ animationDelay: `${0.8 + i * 0.05}s` }}>
                <div className="flex flex-wrap items-center gap-2 sm:gap-3">
                  <span className="rounded-lg bg-foreground px-2.5 py-1 text-xs font-semibold text-background">
                    {post.brand_name}
                  </span>
                  <span className="text-sm font-medium text-foreground">Post #{post.post_number}</span>
                  <span className="text-sm text-muted-foreground">{post.date}</span>
                </div>
                <div className="flex items-center gap-3">
                  <span className="text-sm text-muted-foreground">{post.scheduled_time || "—"}</span>
                  <span className="rounded-full bg-muted px-2.5 py-0.5 text-xs font-medium capitalize text-foreground">
                    {post.status}
                  </span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
