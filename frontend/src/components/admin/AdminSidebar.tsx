"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import {
  LayoutGrid, Users, CheckCircle2, Tag, FileText, AtSign, Star, Music, Calendar,
  Send, MessageSquare, Plug, AlertTriangle, Database, Cog, Shield, PanelLeft,
  ArrowLeft, X, Sun, Moon, LogOut,
} from "lucide-react";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/utils";
import { getAdminStats } from "@/lib/api";

/**
 * The admin area's own rail.
 *
 * Admin is a separate place, not a tab inside the app — it has its own nav
 * and its own way back. What it is *not* is a different product: the panel
 * is the same liquid glass as the user side, it follows the theme, and it
 * carries the same furniture. An ink-black rail was wrong twice over: it
 * ignored the theme, so light mode had a black slab down one side, and it
 * made admin look like somebody else's software.
 *
 * The rows that have not been redesigned yet point at `/admin/tools`, which
 * is the old tabbed page. A nav row that goes nowhere is worse than an
 * unfashionable one.
 */

type Row = { label: string; icon: typeof Users; href: string; badge?: "users" | "pending" };

const NAV: ({ group: string } | Row)[] = [
  { label: "Overview", icon: LayoutGrid, href: "/admin" },
  { group: "People" },
  { label: "Users", icon: Users, href: "/admin/users", badge: "users" },
  { label: "Approvals", icon: CheckCircle2, href: "/admin/approvals", badge: "pending" },
  { group: "Content" },
  { label: "Brands", icon: Tag, href: "/admin/tools?tab=brands" },
  { label: "Posts", icon: FileText, href: "/admin/tools?tab=posts" },
  { label: "Accounts", icon: AtSign, href: "/admin/tools?tab=accounts" },
  { label: "Artists", icon: Star, href: "/admin/tools?tab=artists" },
  { label: "Music", icon: Music, href: "/admin/tools?tab=music" },
  { label: "Schedule", icon: Calendar, href: "/admin/tools?tab=schedule" },
  { group: "Reach" },
  { label: "Outreach", icon: Send, href: "/admin/tools?tab=outreach" },
  { label: "Assistant inbox", icon: MessageSquare, href: "/admin/assistant" },
  { group: "System" },
  { label: "Integrations", icon: Plug, href: "/admin/tools?tab=oauth" },
  // No badge on the error log. `/api/admin/error-logs` returns the newest 200
  // and no total, so any number here would be the page size in the costume of
  // a count.
  { label: "Error log", icon: AlertTriangle, href: "/admin/tools?tab=errors" },
  { label: "Caches & storage", icon: Database, href: "/admin/tools?tab=branding" },
  { label: "Site & email", icon: Cog, href: "/admin/tools?tab=email" },
];

export default function AdminSidebar({
  mobileOpen = false,
  onMobileClose,
}: {
  mobileOpen?: boolean;
  onMobileClose?: () => void;
}) {
  const pathname = usePathname();
  const params = useSearchParams();
  const { user, logout } = useAuth();
  const [collapsed, setCollapsed] = useState(false);
  const [isDark, setIsDark] = useState(true);
  //: What is waiting for you, not how much of a thing exists. Silent on
  //  failure — a badge is decoration and navigation must not depend on it.
  const [counts, setCounts] = useState<{ users: number | null; pending: number | null }>({
    users: null,
    pending: null,
  });

  useEffect(() => {
    const saved = localStorage.getItem("sidebar_collapsed");
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (saved === "true") setCollapsed(true);
    const theme = localStorage.getItem("theme");
    if (theme === "light") document.documentElement.classList.remove("dark");
    setIsDark(document.documentElement.classList.contains("dark"));
    getAdminStats()
      .then((s: { total_users?: number; pending_users?: number }) =>
        setCounts({ users: s?.total_users ?? null, pending: s?.pending_users ?? null }))
      .catch(() => {});
  }, []);

  const toggleTheme = () => {
    const next = !isDark;
    setIsDark(next);
    document.documentElement.classList.toggle("dark", next);
    localStorage.setItem("theme", next ? "dark" : "light");
  };

  const toggleCollapse = () => {
    const next = !collapsed;
    setCollapsed(next);
    localStorage.setItem("sidebar_collapsed", String(next));
  };

  if (!user) return null;

  const currentTab = params.get("tab");
  const isOn = (href: string) => {
    const [path, query] = href.split("?");
    if (query) return pathname === path && currentTab === query.slice(4);
    // `/admin` must not light up on `/admin/users`; everything else owns
    // its subtree.
    if (path === "/admin") return pathname === "/admin";
    if (path === "/admin/tools") return pathname === path && !currentTab;
    return pathname === path || pathname.startsWith(path + "/");
  };

  return (
    <aside
      data-chrome
      className={cn(
        "fixed z-40 flex flex-col transition-transform duration-200 md:transition-all",
        "left-0 top-0 h-screen border-r border-border bg-background",
        "md:left-[18px] md:top-[18px] md:h-[calc(100vh-36px)] md:rounded-[26px] md:border",
        "md:bg-[var(--glass)] md:backdrop-blur-[26px] md:backdrop-saturate-[1.9]",
        "md:border-[var(--glass-border)] md:shadow-[var(--glass-shadow)]",
        "w-[280px]",
        mobileOpen ? "translate-x-0" : "-translate-x-full",
        "md:translate-x-0",
        collapsed ? "md:w-[60px]" : "md:w-[264px]"
      )}
    >
      {/* The light catching the top edge. Without it the glass reads as flat
          translucency rather than a surface. */}
      <span aria-hidden className="pointer-events-none absolute inset-x-0 top-0 hidden h-[42%] rounded-t-[26px]
                     bg-[linear-gradient(180deg,rgba(255,255,255,0.42),rgba(255,255,255,0))]
                     dark:bg-[linear-gradient(180deg,rgba(255,255,255,0.10),rgba(255,255,255,0))] md:block" />

      <div className={cn(
        "relative z-10 flex items-center px-[22px] pb-3 pt-4",
        collapsed ? "md:justify-center" : "justify-between"
      )}>
        <Link href="/admin" className="flex items-center gap-2.5">
          <span className="grid h-[26px] w-[26px] flex-none place-items-center rounded-[7px] bg-lime text-black">
            <Shield className="h-[15px] w-[15px]" strokeWidth={2.1} />
          </span>
          {!collapsed && (
            <span className="flex flex-col leading-none">
              <span className="text-[15px] font-extrabold tracking-[-0.02em] text-foreground">Icreateflow</span>
              <span className="mt-[3px] text-[10px] font-bold uppercase tracking-[0.09em] text-warn">
                Admin area
              </span>
            </span>
          )}
        </Link>
        <div className="flex items-center gap-1">
          <button
            onClick={onMobileClose}
            aria-label="Close menu"
            className="inline-flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground md:hidden"
          >
            <X className="h-4 w-4" />
          </button>
          {!collapsed && (
            <button
              onClick={toggleCollapse}
              aria-label="Collapse sidebar"
              className="hidden rounded-md p-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground md:inline-flex"
            >
              <PanelLeft className="h-[17px] w-[17px]" />
            </button>
          )}
        </div>
      </div>

      {collapsed && (
        <button
          onClick={toggleCollapse}
          aria-label="Expand sidebar"
          className="relative z-10 mx-auto mt-1 hidden rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground md:inline-flex"
        >
          <PanelLeft className="h-[17px] w-[17px]" />
        </button>
      )}

      {/* The way out. It sits above the nav rather than under it because
          leaving is not the last thing on a list of admin pages — it is the
          thing you want when you opened this by accident. */}
      <div className="relative z-10 px-3 pb-2">
        <Link
          href="/dashboard"
          title={collapsed ? "Back to user dash" : undefined}
          className={cn(
            "flex items-center justify-center gap-2 rounded-[12px] border border-border bg-card px-3 py-[9px]",
            "text-[12.5px] font-semibold text-foreground shadow-card transition-colors hover:bg-muted",
            collapsed && "px-0"
          )}
        >
          <ArrowLeft className="h-[15px] w-[15px] flex-none text-subtle" strokeWidth={2.2} />
          {!collapsed && "Back to user dash"}
        </Link>
      </div>

      <nav className="relative z-10 flex-1 overflow-y-auto px-3 pb-3 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
        {NAV.map((row) => {
          if ("group" in row) {
            // Collapsed, a heading has nowhere to go. A hairline says the same
            // thing the word did, in the width the rail actually has.
            return collapsed ? (
              <div key={row.group} className="px-2 py-2.5" aria-hidden>
                <span className="mx-auto block h-px w-6 rounded-full bg-border" />
              </div>
            ) : (
              <p key={row.group} className="px-3 pb-1.5 pt-3.5 text-[10.5px] font-bold uppercase tracking-[0.09em] text-subtle">
                {row.group}
              </p>
            );
          }
          const active = isOn(row.href);
          const badge = row.badge ? counts[row.badge] : null;
          return (
            <Link
              key={row.href}
              href={row.href}
              title={collapsed ? row.label : undefined}
              className={cn(
                "group relative flex items-center gap-[11px] rounded-[12px] px-3 py-[9px] text-[13.5px] transition-colors",
                collapsed && "justify-center px-2",
                active
                  ? [
                      "font-bold text-foreground",
                      "bg-[linear-gradient(180deg,rgba(255,255,255,0.92),rgba(255,255,255,0.66))]",
                      "shadow-[0_1px_2px_rgba(16,24,40,0.10),0_6px_16px_-10px_rgba(16,24,40,0.4),inset_0_1px_0_#fff]",
                      "dark:bg-[linear-gradient(180deg,rgba(255,255,255,0.13),rgba(255,255,255,0.06))]",
                      "dark:shadow-[inset_0_1px_0_rgba(255,255,255,0.14)]",
                      "before:absolute before:-left-2 before:top-1/2 before:h-[19px] before:w-[3px]",
                      "before:-translate-y-1/2 before:rounded-r-[3px] before:bg-lime before:content-['']",
                    ].join(" ")
                  : "font-semibold text-muted-foreground hover:bg-white/55 hover:text-foreground dark:hover:bg-white/[0.07]"
              )}
            >
              <row.icon className="h-[17px] w-[17px] flex-shrink-0" strokeWidth={1.9} />
              {!collapsed && <span>{row.label}</span>}
              {!collapsed && badge ? (
                <span
                  className={cn(
                    "ml-auto rounded-full px-[7px] py-[2px] text-[11px] font-bold",
                    row.badge === "pending"
                      ? "bg-warn/15 text-warn"
                      : "border border-border bg-muted text-muted-foreground"
                  )}
                >
                  {badge}
                </span>
              ) : null}
              {collapsed && (
                <span className="absolute left-full z-50 ml-3 hidden whitespace-nowrap rounded-lg border border-border bg-popover px-3 py-1.5 text-xs font-medium text-popover-foreground shadow-lg group-hover:block">
                  {row.label}
                </span>
              )}
            </Link>
          );
        })}
      </nav>

      <div className="relative z-10 border-t border-border/60 px-3 py-3">
        {collapsed ? (
          <div className="hidden flex-col items-center gap-1 md:flex">
            <button
              onClick={toggleTheme}
              title={isDark ? "Switch to light mode" : "Switch to dark mode"}
              aria-label={isDark ? "Switch to light mode" : "Switch to dark mode"}
              className="grid h-9 w-9 place-items-center rounded-[11px] text-muted-foreground transition-colors hover:bg-white/55 hover:text-foreground dark:hover:bg-white/[0.07]"
            >
              {isDark ? <Sun className="h-[17px] w-[17px]" /> : <Moon className="h-[17px] w-[17px]" />}
            </button>
            <button
              onClick={logout}
              title="Sign out"
              aria-label="Sign out"
              className="grid h-9 w-9 place-items-center rounded-[11px] text-muted-foreground transition-colors hover:bg-bad/10 hover:text-bad"
            >
              <LogOut className="h-[17px] w-[17px]" />
            </button>
          </div>
        ) : (
          <div className="flex items-center gap-2.5">
            <Link
              href="/account"
              className="flex min-w-0 flex-1 items-center gap-2.5 rounded-[12px] px-1.5 py-1.5 transition-colors hover:bg-white/55 dark:hover:bg-white/[0.07]"
            >
              <span className="grid h-[31px] w-[31px] flex-none place-items-center rounded-full border-2 border-card bg-[linear-gradient(140deg,#ffd7a8,#f6a97a)] text-[13px] font-bold text-[#7a4a1e]">
                {user.name?.charAt(0).toUpperCase() || "A"}
              </span>
              <span className="flex min-w-0 flex-col">
                <span className="truncate text-[12.5px] font-bold leading-tight text-foreground">
                  {user.name || "Admin"}
                </span>
                <span className="truncate text-[10.5px] leading-tight text-subtle">{user.email}</span>
              </span>
            </Link>
            <button
              onClick={toggleTheme}
              title={isDark ? "Switch to light mode" : "Switch to dark mode"}
              aria-label={isDark ? "Switch to light mode" : "Switch to dark mode"}
              className="grid h-8 w-8 flex-none place-items-center rounded-[10px] text-muted-foreground transition-colors hover:bg-white/55 hover:text-foreground dark:hover:bg-white/[0.07]"
            >
              {isDark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
            </button>
            <button
              onClick={logout}
              title="Sign out"
              aria-label="Sign out"
              className="grid h-8 w-8 flex-none place-items-center rounded-[10px] text-muted-foreground transition-colors hover:bg-bad/10 hover:text-bad"
            >
              <LogOut className="h-4 w-4" />
            </button>
          </div>
        )}
      </div>
    </aside>
  );
}
