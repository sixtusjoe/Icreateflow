"use client";

import { useState, useEffect, Suspense } from "react";
import { usePathname } from "next/navigation";
import Link from "next/link";
import { Menu } from "lucide-react";
import { useAuth } from "@/lib/auth";
import Sidebar from "./Sidebar";
import AdminSidebar from "./admin/AdminSidebar";
import TopBar from "./TopBar";
import Logo from "./Logo";
import OAuthReturnHandler from "./OAuthReturnHandler";
import Assistant from "./Assistant";

const PUBLIC_PATHS = ["/login", "/register", "/", "/terms", "/privacy"];

/** The assistant sits on every signed-in page but the dashboard, which is
 *  already a wall of numbers and does not need a box in front of it. It is
 *  admin-only, so it is rendered for nobody else rather than rendered and
 *  refusing. Admin is out too: the panel is where a user asks a question,
 *  and /admin/assistant is where those questions are answered — one screen
 *  should not be both ends of the same conversation. */
const NO_ASSISTANT = ["/dashboard", "/account", "/oauth", "/admin"];

/** Routes already carrying the new design, which drops the top bar.
 *
 *  The redesign is landing a page family at a time. A redesigned page has
 *  no search field, theme button, bell or avatar above it — so the two of
 *  those that are actually session controls move to the foot of the
 *  sidebar for exactly those routes, and nothing is duplicated on either
 *  kind of page. When the last page is converted, `TopBar` goes and the
 *  sidebar carries them everywhere. */
const REDESIGNED = ["/outreach", "/music", "/schedule", "/posts", "/brands", "/settings", "/help", "/admin", "/account"];

/** The admin area, which swaps the rail rather than adding to it.
 *
 *  Admin is a place of its own: its own nav, its own way back, and none of
 *  the user's pages in the panel while you are in it. The old tabbed page
 *  lives at /admin/tools and is reached from that nav, so nothing is
 *  stranded while the rest of it is redesigned a page at a time. */
const ADMIN = "/admin";

export default function AppShell({ children, logoUrl }: { children: React.ReactNode; logoUrl?: string }) {
  const { user, isLoading } = useAuth();
  const pathname = usePathname();
  const isPublic = PUBLIC_PATHS.includes(pathname);
  const bare = REDESIGNED.some((p) => pathname === p || pathname.startsWith(p + "/"));
  const inAdmin = pathname === ADMIN || pathname.startsWith(ADMIN + "/");
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
      <Suspense fallback={null}>
        <OAuthReturnHandler />
      </Suspense>
      {inAdmin ? (
        // `useSearchParams` reads the ?tab= the not-yet-redesigned rows use,
        // and Next wants that behind a boundary so the shell can still be
        // prerendered.
        <Suspense fallback={null}>
          <AdminSidebar mobileOpen={mobileOpen} onMobileClose={() => setMobileOpen(false)} />
        </Suspense>
      ) : (
        <Sidebar
          mobileOpen={mobileOpen}
          onMobileClose={() => setMobileOpen(false)}
          logoUrl={logoUrl}
          session={bare}
        />
      )}

      {/* Mobile backdrop */}
      {mobileOpen && (
        <div
          className="fixed inset-0 z-30 bg-black/25 md:hidden"
          onClick={() => setMobileOpen(false)}
          aria-hidden="true"
        />
      )}

      <main className={`min-h-screen transition-all duration-200 ${collapsed ? "md:ml-[78px]" : "md:ml-[282px]"}`}>
        {/* Mobile top bar — hidden on md+ */}
        <header className="sticky top-0 z-20 flex h-14 items-center justify-between border-b border-border bg-background/95 px-4 backdrop-blur md:hidden">
          <button
            onClick={() => setMobileOpen(true)}
            aria-label="Open menu"
            className="-ml-2 inline-flex h-10 w-10 items-center justify-center rounded-md text-foreground hover:bg-muted"
          >
            <Menu className="h-5 w-5" />
          </button>
          <Link href={inAdmin ? "/admin" : "/dashboard"} className="flex items-center gap-2">
            <Logo size={24} radius={6} src={logoUrl || undefined} />
            <span className="text-sm font-bold tracking-tight text-foreground">
              {inAdmin ? "Admin" : "Icreateflow"}
            </span>
          </Link>
          <div className="w-10" aria-hidden="true" />
        </header>

        {/* Desktop top bar — search, theme, notifications, account. The
            mobile header above covers the same ground below md. Absent on
            the redesigned routes, where the sidebar carries the session
            controls instead. */}
        {!bare && <TopBar />}

        {/* On the redesigned routes the content column is a flex stack with
            a 16px gap, as the design has it. Without it the page header sits
            flush against the first card and a title runs straight into the
            thing it names. The older routes keep their own spacing. */}
        <div
          className={`p-4 md:px-[18px] md:pb-[18px] md:pt-4 ${bare ? "flex flex-col gap-4" : ""}`}
        >
          {children}
        </div>
      </main>

      {user.role === "admin" && !NO_ASSISTANT.some((p) => pathname === p || pathname.startsWith(p + "/")) && (
        <Assistant key={pathname} route={pathname} />
      )}
    </>
  );
}
