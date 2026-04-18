"use client";

import { useState, useEffect } from "react";
import { usePathname } from "next/navigation";
import Link from "next/link";
import { Menu } from "lucide-react";
import { useAuth } from "@/lib/auth";
import Sidebar from "./Sidebar";

const PUBLIC_PATHS = ["/login", "/register", "/", "/terms", "/privacy"];

export default function AppShell({ children }: { children: React.ReactNode }) {
  const { user, isLoading } = useAuth();
  const pathname = usePathname();
  const isPublic = PUBLIC_PATHS.includes(pathname);
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  useEffect(() => {
    const check = () => setCollapsed(localStorage.getItem("sidebar_collapsed") === "true");
    check();
    window.addEventListener("storage", check);
    const interval = setInterval(check, 200);
    return () => { window.removeEventListener("storage", check); clearInterval(interval); };
  }, []);

  // Close mobile drawer on route change
  useEffect(() => { setMobileOpen(false); }, [pathname]);

  // Lock body scroll while drawer is open on mobile
  useEffect(() => {
    if (mobileOpen) {
      document.body.style.overflow = "hidden";
    } else {
      document.body.style.overflow = "";
    }
    return () => { document.body.style.overflow = ""; };
  }, [mobileOpen]);

  if (isPublic) {
    return <>{children}</>;
  }

  if (isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-foreground border-t-transparent" />
      </div>
    );
  }

  if (!user) {
    return null;
  }

  return (
    <>
      <Sidebar mobileOpen={mobileOpen} onMobileClose={() => setMobileOpen(false)} />

      {/* Mobile backdrop */}
      {mobileOpen && (
        <div
          className="fixed inset-0 z-30 bg-black/50 backdrop-blur-sm md:hidden"
          onClick={() => setMobileOpen(false)}
          aria-hidden="true"
        />
      )}

      <main className={`min-h-screen transition-all duration-200 ${collapsed ? "md:ml-[60px]" : "md:ml-[240px]"}`}>
        {/* Mobile top bar — hidden on md+ */}
        <header className="sticky top-0 z-20 flex h-14 items-center justify-between border-b border-border bg-background/95 px-4 backdrop-blur md:hidden">
          <button
            onClick={() => setMobileOpen(true)}
            aria-label="Open menu"
            className="-ml-2 inline-flex h-10 w-10 items-center justify-center rounded-md text-foreground hover:bg-muted"
          >
            <Menu className="h-5 w-5" />
          </button>
          <Link href="/dashboard" className="flex items-center gap-2">
            <div className="flex h-6 w-6 items-center justify-center rounded-md bg-foreground text-[9px] font-bold text-background">IC</div>
            <span className="text-sm font-bold tracking-tight text-foreground">ICREATEFLOW</span>
          </Link>
          <div className="w-10" aria-hidden="true" />
        </header>

        <div className="p-4 md:p-8">{children}</div>
      </main>
    </>
  );
}
