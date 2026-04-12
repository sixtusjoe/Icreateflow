"use client";

import { useEffect, useState } from "react";
import { useAuth } from "@/lib/auth";
import { useRouter } from "next/navigation";
import { Shield, Users, FileText, Music, Layers, Save } from "lucide-react";
import { toast } from "sonner";
import { getAdminStats, getUsers, updateUser, getSiteConfig, updateSiteConfig } from "@/lib/api";

export default function AdminPage() {
  const { user } = useAuth();
  const router = useRouter();
  const [stats, setStats] = useState<any>(null);
  const [users, setUsers] = useState<any[]>([]);
  const [siteConfig, setSiteConfig] = useState<Record<string, string>>({});
  const [tab, setTab] = useState<"overview" | "users" | "branding">("overview");

  useEffect(() => {
    if (user && user.role !== "admin") { router.push("/"); return; }
    getAdminStats().then(setStats).catch(() => {});
    getUsers().then(setUsers).catch(() => {});
    getSiteConfig().then(setSiteConfig).catch(() => {});
  }, [user]);

  if (!user || user.role !== "admin") return null;

  const handleRoleChange = async (userId: number, role: string) => {
    try {
      await updateUser(userId, { role });
      setUsers((prev) => prev.map((u) => (u.id === userId ? { ...u, role } : u)));
      toast.success("Role updated");
    } catch { toast.error("Failed"); }
  };

  const handleStatusChange = async (userId: number, status: string) => {
    try {
      await updateUser(userId, { status });
      setUsers((prev) => prev.map((u) => (u.id === userId ? { ...u, status } : u)));
      toast.success("Status updated");
    } catch { toast.error("Failed"); }
  };

  const tabs = [
    { id: "overview" as const, label: "Overview" },
    { id: "users" as const, label: "Users" },
    { id: "branding" as const, label: "Branding" },
  ];

  return (
    <div className="mx-auto max-w-4xl">
      <div className="mb-8">
        <h1 className="text-2xl font-bold tracking-tight">Admin Panel</h1>
        <p className="mt-1 text-sm text-muted-foreground">Manage users, branding, and platform settings.</p>
      </div>

      {/* Tabs */}
      <div className="mb-6 flex gap-1 rounded-lg border border-border p-1">
        {tabs.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`flex-1 rounded-md px-4 py-2 text-sm font-medium transition-colors ${
              tab === t.id ? "bg-foreground text-background" : "text-muted-foreground hover:text-foreground"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "overview" && stats && (
        <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
          {[
            { label: "Users", value: stats.total_users, icon: Users },
            { label: "Brands", value: stats.total_brands, icon: Layers },
            { label: "Posts", value: stats.total_posts, icon: FileText },
            { label: "Music", value: stats.total_tracks, icon: Music },
          ].map((s) => (
            <div key={s.label} className="rounded-2xl bg-card p-5">
              <div className="flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-foreground">
                  <s.icon className="h-4 w-4 text-background" />
                </div>
                <div>
                  <p className="text-2xl font-bold tracking-tight">{s.value}</p>
                  <p className="text-xs text-muted-foreground">{s.label}</p>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {tab === "users" && (
        <div className="overflow-hidden rounded-2xl bg-card">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left">
                <th className="px-5 py-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground">Name</th>
                <th className="px-5 py-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground">Email</th>
                <th className="px-5 py-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground">Role</th>
                <th className="px-5 py-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground">Status</th>
                <th className="px-5 py-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground">Joined</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id} className="border-b border-border/50 hover:bg-muted/30 transition-colors">
                  <td className="px-5 py-3 font-medium">{u.name}</td>
                  <td className="px-5 py-3 text-muted-foreground">{u.email}</td>
                  <td className="px-5 py-3">
                    <select
                      value={u.role}
                      onChange={(e) => handleRoleChange(u.id, e.target.value)}
                      disabled={u.id === user.id}
                      className="rounded-md border border-border bg-background px-2 py-1 text-xs outline-none focus:border-foreground"
                    >
                      <option value="user">User</option>
                      <option value="admin">Admin</option>
                    </select>
                  </td>
                  <td className="px-5 py-3">
                    <select
                      value={u.status}
                      onChange={(e) => handleStatusChange(u.id, e.target.value)}
                      disabled={u.id === user.id}
                      className="rounded-md border border-border bg-background px-2 py-1 text-xs outline-none focus:border-foreground"
                    >
                      <option value="active">Active</option>
                      <option value="suspended">Suspended</option>
                    </select>
                  </td>
                  <td className="px-5 py-3 text-muted-foreground">{new Date(u.created_at).toLocaleDateString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {tab === "branding" && (
        <div className="rounded-2xl bg-card p-6">
          <h2 className="mb-5 text-base font-semibold">Site Branding</h2>
          <div>
            <label className="mb-1.5 block text-sm font-medium">Site Name</label>
            <div className="flex gap-2">
              <input
                value={siteConfig.site_name || ""}
                onChange={(e) => setSiteConfig((s) => ({ ...s, site_name: e.target.value }))}
                className="flex-1 rounded-lg border border-border bg-background px-4 py-2.5 text-sm outline-none focus:border-foreground"
              />
              <button
                onClick={async () => { try { await updateSiteConfig("site_name", siteConfig.site_name || ""); toast.success("Saved"); } catch { toast.error("Failed"); } }}
                className="rounded-lg bg-foreground px-4 py-2.5 text-background transition-opacity hover:opacity-90"
              >
                <Save className="h-4 w-4" />
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
