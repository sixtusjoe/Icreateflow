"use client";

/**
 * Desktop top bar: search, theme, notifications, account.
 *
 * Theme and the account menu used to live at the foot of the sidebar.
 * They moved here because the sidebar's own footer is now the upgrade
 * card, and because these three controls belong together — they act on
 * the session rather than on the page. Nothing is duplicated: the
 * sidebar no longer renders either of them.
 *
 * Hidden below md, where AppShell's existing mobile header already
 * carries the menu button and the brand.
 */

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { Search, Sun, Moon, Bell, User, LogOut } from "lucide-react";
import { useAuth } from "@/lib/auth";

export default function TopBar() {
  const { user, logout } = useAuth();
  const [isDark, setIsDark] = useState(true);
  const [menuOpen, setMenuOpen] = useState(false);
  const wrap = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setIsDark(document.documentElement.classList.contains("dark"));
  }, []);

  // A menu that only closes by clicking its own button is a trap once it
  // overlaps the page it covers.
  useEffect(() => {
    if (!menuOpen) return;
    const onDown = (e: MouseEvent) => {
      if (wrap.current && !wrap.current.contains(e.target as Node)) setMenuOpen(false);
    };
    const onEsc = (e: KeyboardEvent) => e.key === "Escape" && setMenuOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onEsc);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onEsc);
    };
  }, [menuOpen]);

  const toggleTheme = () => {
    const next = !isDark;
    setIsDark(next);
    document.documentElement.classList.toggle("dark", next);
    localStorage.setItem("theme", next ? "dark" : "light");
  };

  if (!user) return null;

  return (
    <div data-chrome className="hidden items-center gap-3 px-[18px] pt-[18px] md:flex">
      <div className="flex max-w-[430px] flex-1 items-center gap-[9px] rounded-[12px] border border-border bg-card px-[13px] py-[9px] text-[13px] text-subtle shadow-card">
        <Search className="h-[15px] w-[15px] flex-none" />
        <span>Search anything...</span>
      </div>

      <div className="ml-auto flex items-center gap-[9px]">
        <button onClick={toggleTheme} aria-label={isDark ? "Switch to light mode" : "Switch to dark mode"}
          className="grid h-[37px] w-[37px] place-items-center rounded-[11px] border border-border bg-card text-muted-foreground shadow-card transition-colors hover:text-foreground">
          {isDark ? <Sun className="h-[17px] w-[17px]" /> : <Moon className="h-[17px] w-[17px]" />}
        </button>

        <button aria-label="Notifications"
          className="grid h-[37px] w-[37px] place-items-center rounded-[11px] border border-border bg-card text-muted-foreground shadow-card transition-colors hover:text-foreground">
          <Bell className="h-[17px] w-[17px]" />
        </button>

        <div className="relative" ref={wrap}>
          <button onClick={() => setMenuOpen((v) => !v)}
            className="flex items-center rounded-full" aria-haspopup="menu" aria-expanded={menuOpen}>
            <span className="grid h-[37px] w-[37px] place-items-center rounded-full border-2 border-card
                             bg-[linear-gradient(140deg,#ffd7a8,#f6a97a)] text-[14px] font-bold text-[#7a4a1e] shadow-card">
              {user.name?.charAt(0).toUpperCase() || "U"}
            </span>
          </button>
          {menuOpen && (
            <div role="menu" className="absolute right-0 top-full z-50 mt-2 w-[184px] rounded-[14px] border border-border bg-popover p-1.5
                            shadow-[0_18px_40px_-16px_rgba(16,24,40,0.45)]">
              <Link href="/account" onClick={() => setMenuOpen(false)}
                className="flex items-center gap-2.5 rounded-[9px] px-2.5 py-2 text-[12.5px] font-semibold text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground">
                <User className="h-4 w-4 flex-none text-subtle" /> Profile
              </Link>
              <div className="my-1.5 h-px bg-line-2" />
              <button onClick={() => { setMenuOpen(false); logout(); }}
                className="flex w-full items-center gap-2.5 rounded-[9px] px-2.5 py-2 text-[12.5px] font-semibold text-bad transition-colors hover:bg-bad/10">
                <LogOut className="h-4 w-4 flex-none" /> Sign Out
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
