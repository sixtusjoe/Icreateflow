"use client";

import { useState, useEffect } from "react";
import { usePathname } from "next/navigation";
import { useAuth } from "@/lib/auth";
import Sidebar from "./Sidebar";

const PUBLIC_PATHS = ["/login", "/register", "/landing"];

export default function AppShell({ children }: { children: React.ReactNode }) {
  const { user, isLoading } = useAuth();
  const pathname = usePathname();
  const isPublic = PUBLIC_PATHS.includes(pathname);
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    const check = () => setCollapsed(localStorage.getItem("sidebar_collapsed") === "true");
    check();
    window.addEventListener("storage", check);
    // Also poll for same-tab changes
    const interval = setInterval(check, 200);
    return () => { window.removeEventListener("storage", check); clearInterval(interval); };
  }, []);

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
      <Sidebar />
      <main className={`min-h-screen transition-all duration-200 ${collapsed ? "ml-[60px]" : "ml-[240px]"}`}>
        <div className="p-8">{children}</div>
      </main>
    </>
  );
}
