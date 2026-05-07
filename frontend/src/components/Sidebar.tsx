"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useAuth } from "@/lib/auth";
import {
  LayoutDashboard,
  Tags,
  PlusCircle,
  Library,
  CalendarClock,
  Music,
  Settings,
  Shield,
  Scissors,
  ChevronLeft,
  ChevronRight,
  LogOut,
  User,
  ChevronDown,
  Sun,
  Moon,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";
import Logo from "@/components/Logo";

const mainLinks = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/posts/new", label: "New Post", icon: PlusCircle },
  { href: "/clipping", label: "Clipping", icon: Scissors },
];

const libraryLinks = [
  { href: "/posts", label: "Posts", icon: Library },
  { href: "/brands", label: "Brands", icon: Tags },
  { href: "/music", label: "Music", icon: Music },
  { href: "/schedule", label: "Schedule", icon: CalendarClock },
];

const settingLinks = [
  { href: "/settings", label: "Settings", icon: Settings },
];

const adminLinks = [
  { href: "/admin", label: "Admin", icon: Shield },
];

function NavSection({ title, links, pathname, collapsed }: {
  title: string;
  links: typeof mainLinks;
  pathname: string;
  collapsed: boolean;
}) {
  return (
    <div className="mb-4">
      {!collapsed && (
        <p className="mb-1.5 px-3 text-[10px] font-semibold uppercase tracking-[0.15em] text-muted-foreground/50">
          {title}
        </p>
      )}
      <div className="space-y-0.5">
        {links.map((link) => {
          const isActive =
            link.href === "/posts"
              ? pathname === "/posts"
              : pathname === link.href || pathname.startsWith(link.href + "/");
          return (
            <Link
              key={link.href}
              href={link.href}
              title={collapsed ? link.label : undefined}
              className={cn(
                "group relative flex items-center gap-3 rounded-lg px-3 py-2.5 text-[13px] font-medium transition-colors",
                collapsed && "justify-center px-2",
                isActive
                  ? "bg-foreground text-background"
                  : "text-muted-foreground hover:bg-muted hover:text-foreground"
              )}
            >
              <link.icon className="h-4 w-4 flex-shrink-0" />
              {!collapsed && <span>{link.label}</span>}
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
}

export default function Sidebar({ mobileOpen = false, onMobileClose, logoUrl }: SidebarProps) {
  const pathname = usePathname();
  const { user, logout } = useAuth();
  const [collapsed, setCollapsed] = useState(false);
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const [isDark, setIsDark] = useState(true);

  useEffect(() => {
    const saved = localStorage.getItem("sidebar_collapsed");
    if (saved === "true") setCollapsed(true);
    const theme = localStorage.getItem("theme");
    if (theme === "light") {
      setIsDark(false);
      document.documentElement.classList.remove("dark");
    } else {
      setIsDark(document.documentElement.classList.contains("dark"));
    }
  }, []);

  const toggleCollapse = () => {
    const next = !collapsed;
    setCollapsed(next);
    localStorage.setItem("sidebar_collapsed", String(next));
  };

  const toggleTheme = () => {
    const next = !isDark;
    setIsDark(next);
    document.documentElement.classList.toggle("dark", next);
    localStorage.setItem("theme", next ? "dark" : "light");
  };

  if (!user) return null;

  // On mobile, the collapsed state is ignored — the drawer is always full-width when open.
  // On md+ screens, collapsed controls the inline width.
  return (
    <aside
      className={cn(
        "fixed left-0 top-0 z-40 flex h-screen flex-col border-r border-border bg-background transition-transform duration-200 md:transition-all",
        // Mobile: fixed 280px width, slide in/out
        "w-[280px]",
        mobileOpen ? "translate-x-0" : "-translate-x-full",
        // Desktop: always visible, width depends on collapsed
        "md:translate-x-0",
        collapsed ? "md:w-[60px]" : "md:w-[240px]"
      )}
    >
      {/* Header */}
      <div className={cn(
        "flex h-14 items-center border-b border-border px-3",
        collapsed ? "md:justify-center" : "justify-between"
      )}>
        {!collapsed ? (
          <Link href="/dashboard" className="flex items-center gap-2 px-1">
            <Logo size={24} radius={6} src={logoUrl || undefined} />
            <span className="text-sm font-bold tracking-tight text-foreground">Icreateflow</span>
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
              <ChevronLeft className="h-4 w-4" />
            </button>
          )}
        </div>
      </div>

      {collapsed && (
        <button
          onClick={toggleCollapse}
          aria-label="Expand sidebar"
          className="hidden md:inline-flex mx-auto mt-2 rounded-md p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
        >
          <ChevronRight className="h-4 w-4" />
        </button>
      )}

      {/* Navigation */}
      <nav className="flex-1 overflow-y-auto px-2 py-3">
        <NavSection title="Main" links={mainLinks} pathname={pathname} collapsed={collapsed} />
        <NavSection title="Library" links={libraryLinks} pathname={pathname} collapsed={collapsed} />
        <NavSection title="Settings" links={settingLinks} pathname={pathname} collapsed={collapsed} />
        {user.role === "admin" && (
          <NavSection title="Admin" links={adminLinks} pathname={pathname} collapsed={collapsed} />
        )}
      </nav>

      {/* Bottom */}
      <div className="border-t border-border p-2 space-y-1">
        <button
          onClick={toggleTheme}
          className={cn(
            "flex w-full items-center gap-2.5 rounded-lg px-3 py-2.5 text-[13px] text-muted-foreground hover:bg-muted hover:text-foreground transition-colors",
            collapsed && "md:justify-center md:px-2"
          )}
        >
          {isDark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
          {!collapsed && <span>{isDark ? "Light Mode" : "Dark Mode"}</span>}
        </button>

        <div className="relative">
          <button
            onClick={() => setUserMenuOpen(!userMenuOpen)}
            className={cn(
              "flex w-full items-center gap-2.5 rounded-lg px-3 py-2.5 text-sm hover:bg-muted transition-colors",
              collapsed && "md:justify-center md:px-2"
            )}
          >
            <div className="flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-full bg-foreground text-[11px] font-semibold text-background">
              {user.name?.charAt(0).toUpperCase() || "U"}
            </div>
            {!collapsed && (
              <>
                <div className="flex-1 text-left min-w-0">
                  <p className="truncate text-[13px] font-medium">{user.name}</p>
                </div>
                <ChevronDown className={cn("h-3.5 w-3.5 text-muted-foreground transition-transform", userMenuOpen && "rotate-180")} />
              </>
            )}
          </button>

          {userMenuOpen && (
            <div className={cn(
              "absolute bottom-full mb-1 rounded-lg border border-border bg-popover py-1 shadow-lg",
              collapsed ? "md:left-full md:ml-1 md:w-40 left-0 right-0" : "left-0 right-0"
            )}>
              <Link
                href="/account"
                onClick={() => setUserMenuOpen(false)}
                className="flex items-center gap-2.5 px-3 py-2.5 text-[13px] text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
              >
                <User className="h-4 w-4" /> Profile
              </Link>
              <button
                onClick={() => { setUserMenuOpen(false); logout(); }}
                className="flex w-full items-center gap-2.5 px-3 py-2.5 text-[13px] text-destructive hover:bg-muted transition-colors"
              >
                <LogOut className="h-4 w-4" /> Sign Out
              </button>
            </div>
          )}
        </div>
      </div>
    </aside>
  );
}
