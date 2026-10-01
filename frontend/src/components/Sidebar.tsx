"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useAuth } from "@/lib/auth";
import {
  LayoutDashboard,
  Tag,
  PlusCircle,
  Book,
  Calendar,
  Music,
  Music2,
  Settings,
  Shield,
  Scissors,
  Send,
  PanelLeft,
  HelpCircle,
  Star,
  ArrowRight,
  X,
  Sun,
  Moon,
  LogOut,
} from "lucide-react";
import { cn } from "@/lib/utils";
import Logo from "@/components/Logo";
import { avatarSrc, getOutreachSummary } from "@/lib/api";

const mainLinks = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/posts/new", label: "New Post", icon: PlusCircle },
  { href: "/clipping", label: "Clipping", icon: Scissors },
  { href: "/clipping/audio-to-video", label: "Audio to Video", icon: Music2 },
  { href: "/outreach", label: "Outreach", icon: Send },
];

const libraryLinks = [
  { href: "/posts", label: "Posts", icon: Book },
  { href: "/brands", label: "Brands", icon: Tag },
  { href: "/music", label: "Music", icon: Music },
  { href: "/schedule", label: "Schedule", icon: Calendar },
];

const settingLinks = [
  { href: "/settings", label: "Settings", icon: Settings },
  { href: "/help", label: "Help & Support", icon: HelpCircle },
];

function NavSection({ title, links, pathname, collapsed, done }: {
  title: string;
  links: typeof mainLinks;
  pathname: string;
  collapsed: boolean;
  /** Campaigns that have finished — what the Outreach badge counts. */
  done?: number | null;
}) {
  return (
    <div>
      {/* Collapsed, the heading has nowhere to go and every icon runs into
          the next as one undifferentiated column. A hairline says the same
          thing the word did — these belong together, those are something
          else — in the width the rail actually has. */}
      {title ? (
        collapsed ? (
          <div className="px-2 py-2.5" aria-hidden>
            <span className="mx-auto block h-px w-6 rounded-full bg-border" />
          </div>
        ) : (
          <p className="px-3 pb-1.5 pt-3.5 text-[10.5px] font-bold uppercase tracking-[0.09em] text-subtle">
            {title}
          </p>
        )
      ) : null}
      <div>
        {links.map((link) => {
          // Most-specific match wins: if another link in this section is a
          // longer prefix of pathname, this link should NOT be active.
          const isActive =
            link.href === "/posts"
              ? pathname === "/posts"
              : (pathname === link.href || pathname.startsWith(link.href + "/")) &&
                !links.some(
                  (other) =>
                    other.href !== link.href &&
                    other.href.length > link.href.length &&
                    (pathname === other.href || pathname.startsWith(other.href + "/"))
                );
          return (
            <Link
              key={link.href}
              href={link.href}
              title={collapsed ? link.label : undefined}
              className={cn(
                "group relative flex items-center gap-[11px] rounded-[12px] px-3 py-[9px] text-[13.5px] transition-colors",
                collapsed && "justify-center px-2",
                isActive
                  // Reads as a sheet lifted off the glass — a solid fill would
                  // punch a hole in a panel whose whole point is translucency.
                  ? [
                      "font-bold text-foreground",
                      "bg-[linear-gradient(180deg,rgba(255,255,255,0.92),rgba(255,255,255,0.66))]",
                      "shadow-[0_1px_2px_rgba(16,24,40,0.10),0_6px_16px_-10px_rgba(16,24,40,0.4),inset_0_1px_0_#fff]",
                      "dark:bg-[linear-gradient(180deg,rgba(255,255,255,0.13),rgba(255,255,255,0.06))]",
                      "dark:shadow-[inset_0_1px_0_rgba(255,255,255,0.14)]",
                      // the lime rail, tucked into the panel's padding
                      "before:absolute before:-left-2 before:top-1/2 before:h-[19px] before:w-[3px]",
                      "before:-translate-y-1/2 before:rounded-r-[3px] before:bg-lime before:content-['']",
                    ].join(" ")
                  : "font-semibold text-muted-foreground hover:bg-white/55 hover:text-foreground dark:hover:bg-white/[0.07]"
              )}
            >
              <link.icon className="h-[17px] w-[17px] flex-shrink-0" strokeWidth={1.9} />
              {!collapsed && <span>{link.label}</span>}
              {!collapsed && link.href === "/outreach" && done ? (
                <span
                  title={`${done} campaign${done === 1 ? "" : "s"} completed`}
                  className="ml-auto rounded-full bg-lime px-[7px] py-[2px] text-[11px] font-bold text-black"
                >
                  {done >= 1000 ? `${(done / 1000).toFixed(1)}K` : done}
                </span>
              ) : null}
              {collapsed && (
                <span className="absolute left-full ml-3 hidden whitespace-nowrap rounded-lg border border-border bg-popover px-3 py-1.5 text-xs font-medium text-popover-foreground shadow-lg group-hover:block z-50">
                  {link.label}
                </span>
              )}
            </Link>
          );
        })}
      </div>
    </div>
  );
}

interface SidebarProps {
  mobileOpen?: boolean;
  onMobileClose?: () => void;
  logoUrl?: string;
  /** True on the routes that have no top bar, where the theme toggle and
   *  sign-out have nowhere else to live. Off elsewhere so neither control
   *  appears twice on one page. */
  session?: boolean;
}

export default function Sidebar({ mobileOpen = false, onMobileClose, logoUrl, session = false }: SidebarProps) {
  const pathname = usePathname();
  const { user, logout } = useAuth();
  const [collapsed, setCollapsed] = useState(false);
  //: Completed campaigns, on the Outreach row. Failure is silent on
  //  purpose — a badge is decoration, and navigation must not depend on it.
  const [done, setDone] = useState<number | null>(null);
  const [isDark, setIsDark] = useState(true);

  useEffect(() => {
    // Reading browser-only state after hydration is exactly what this
    // effect is for: the server has no localStorage, so seeding from it
    // during render would paint one thing and hydrate another.
    const saved = localStorage.getItem("sidebar_collapsed");
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (saved === "true") setCollapsed(true);
    // The theme is applied by the inline script in layout.tsx before paint.
    // Reading the stored value here keeps a light stamp from being lost on
    // navigation, and seeds the toggle below with what is actually on.
    const theme = localStorage.getItem("theme");
    if (theme === "light") document.documentElement.classList.remove("dark");
    setIsDark(document.documentElement.classList.contains("dark"));
    getOutreachSummary()
      // The summary only carries the states that exist, so "no completed
      // campaigns yet" arrives as a missing key rather than a zero.
      .then((d: { campaigns?: Record<string, number> }) =>
        setDone(d?.campaigns?.completed ?? null))
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

  // On mobile, the collapsed state is ignored — the drawer is always full-width when open.
  // On md+ screens, collapsed controls the inline width.
  return (
    <aside
      data-chrome
      className={cn(
        // A floating glass panel rather than a flush rail: inset from the
        // edges, rounded, and translucent so the page colour behind it
        // shows through. `backdrop-blur` needs something to blur, which is
        // why the shell paints a soft wash behind it.
        "fixed z-40 flex flex-col transition-transform duration-200 md:transition-all",
        "left-0 top-0 h-screen border-r border-border bg-background",
        "md:left-[18px] md:top-[18px] md:h-[calc(100vh-36px)] md:rounded-[26px] md:border",
        "md:bg-[var(--glass)] md:backdrop-blur-[26px] md:backdrop-saturate-[1.9]",
        "md:border-[var(--glass-border)] md:shadow-[var(--glass-shadow)]",
        // Mobile: fixed 280px width, slide in/out
        "w-[280px]",
        mobileOpen ? "translate-x-0" : "-translate-x-full",
        // Desktop: always visible, width depends on collapsed
        "md:translate-x-0",
        collapsed ? "md:w-[60px]" : "md:w-[264px]"
      )}
    >
      {/* Header */}
      <div className={cn(
        "relative z-10 flex items-center px-[22px] pb-4 pt-4",
        collapsed ? "md:justify-center" : "justify-between"
      )}>
        {!collapsed ? (
          <Link href="/dashboard" className="flex items-center gap-2.5">
            <Logo size={24} radius={6} src={logoUrl || undefined} />
            <span className="text-[16px] font-extrabold tracking-[-0.02em] text-foreground">Icreateflow</span>
          </Link>
        ) : (
          <Link href="/dashboard" className="hidden md:inline-flex">
            <Logo size={28} radius={7} src={logoUrl || undefined} />
          </Link>
        )}
        <div className="flex items-center gap-1">
          {/* Close button — mobile only */}
          <button
            onClick={onMobileClose}
            aria-label="Close menu"
            className="inline-flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground md:hidden"
          >
            <X className="h-4 w-4" />
          </button>
          {/* Collapse button — desktop only */}
          {!collapsed && (
            <button
              onClick={toggleCollapse}
              aria-label="Collapse sidebar"
              className="hidden md:inline-flex rounded-md p-1 text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
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
          className="relative z-10 hidden md:inline-flex mx-auto mt-2 rounded-md p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
        >
          <PanelLeft className="h-[17px] w-[17px]" />
        </button>
      )}

      {/* The light catching the top edge of the panel. Without it the glass
          reads as flat translucency rather than a surface. */}
      <span aria-hidden className="pointer-events-none absolute inset-x-0 top-0 hidden h-[42%] rounded-t-[26px]
                     bg-[linear-gradient(180deg,rgba(255,255,255,0.42),rgba(255,255,255,0))]
                     dark:bg-[linear-gradient(180deg,rgba(255,255,255,0.10),rgba(255,255,255,0))] md:block" />

      {/* Navigation */}
      <nav className="relative z-10 flex-1 overflow-y-auto px-3 py-3 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
        <NavSection title="" links={mainLinks} pathname={pathname} collapsed={collapsed} done={done} />
        <NavSection title="Library" links={libraryLinks} pathname={pathname} collapsed={collapsed} done={done} />
        <NavSection title="Workspace" links={settingLinks} pathname={pathname} collapsed={collapsed} done={done} />

        {/* The switch into admin. Not a nav row: admin is a different place
            with its own rail, and a row in this list would promise that
            pressing it keeps you here. It sits under the menu, separated by
            a rule, so it reads as leaving rather than as one more page. */}
        {user.role === "admin" && (
          <div className="mt-4 border-t border-border/60 pt-3">
            <Link
              href="/admin"
              title={collapsed ? "Switch to admin" : undefined}
              className={cn(
                "group relative flex items-center gap-[11px] rounded-[12px] border border-border bg-card px-3 py-[9px]",
                "shadow-card transition-colors hover:bg-muted",
                collapsed && "justify-center px-2"
              )}
            >
              <span className="grid h-[22px] w-[22px] flex-none place-items-center rounded-[7px] bg-lime text-black">
                <Shield className="h-[13px] w-[13px]" strokeWidth={2.2} />
              </span>
              {!collapsed && (
                <span className="flex min-w-0 flex-col leading-tight">
                  <span className="text-[12.5px] font-bold text-foreground">Switch to admin</span>
                  <span className="text-[10.5px] text-subtle">Everyone&apos;s data, not just yours</span>
                </span>
              )}
              {!collapsed && (
                <ArrowRight className="ml-auto h-[15px] w-[15px] flex-none text-subtle" strokeWidth={2.1} />
              )}
              {collapsed && (
                <span className="absolute left-full z-50 ml-3 hidden whitespace-nowrap rounded-lg border border-border bg-popover px-3 py-1.5 text-xs font-medium text-popover-foreground shadow-lg group-hover:block">
                  Switch to admin
                </span>
              )}
            </Link>
          </div>
        )}
      </nav>

      {/* Session controls, on the routes whose top bar is gone. Theme and
          sign-out are the only two of those four that do anything, and
          they act on the session rather than the page — so they sit at the
          foot of the one panel that is on every page. */}
      {session && (
        <div className="relative z-10 border-t border-border/60 px-3 pt-3">
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
                {/* Their picture from the Account page, else the letter. */}
                {avatarSrc(user.avatar_url) ? (
                  // eslint-disable-next-line @next/next/no-img-element -- served by the API, not this app
                  <img src={avatarSrc(user.avatar_url)} alt="" className="h-[31px] w-[31px] flex-none rounded-full border-2 border-card object-cover" />
                ) : (
                  <span className="grid h-[31px] w-[31px] flex-none place-items-center rounded-full border-2 border-card bg-[linear-gradient(140deg,#ffd7a8,#f6a97a)] text-[13px] font-bold text-[#7a4a1e]">
                    {user.name?.charAt(0).toUpperCase() || "U"}
                  </span>
                )}
                <span className="flex min-w-0 flex-col">
                  <span className="truncate text-[12.5px] font-bold leading-tight text-foreground">
                    {user.name || "Account"}
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
      )}

      {/* Upgrade card. It is dropped entirely when collapsed — a 60px rail
          has no room for it. */}
      {!collapsed && (
        <div className="relative z-10 px-3 pb-4 pt-3">
          <div className="relative overflow-hidden rounded-[18px] p-4 text-white shadow-[0_12px_26px_-14px_rgba(0,0,0,0.8),inset_0_1px_0_rgba(255,255,255,0.16)]
                          [background:linear-gradient(160deg,#1c1f27_0%,#0b0d12_52%,#15180f_100%)]
                          dark:border dark:border-lime/[0.34]">
            <span aria-hidden className="pointer-events-none absolute inset-0
                          [background:radial-gradient(9rem_7rem_at_82%_8%,rgba(215,215,0,0.34),transparent_62%)]" />
            <div className="relative">
              <span className="mb-2.5 grid h-[30px] w-[30px] place-items-center rounded-[9px] bg-lime">
                <Star className="h-[17px] w-[17px] text-black" strokeWidth={2} />
              </span>
              <h4 className="mb-1 text-[13.5px] font-extrabold">Upgrade to Premium!</h4>
              <p className="mb-3 text-[11.5px] leading-[1.45] text-white/80">
                Unlock unlimited campaigns, priority sending and the full AI assistant.
              </p>
              <button className="w-full rounded-[11px] bg-lime py-[9px] text-[12.5px] font-bold text-black transition-[filter] hover:brightness-110">
                Upgrade premium
              </button>
            </div>
          </div>
        </div>
      )}
    </aside>
  );
}
