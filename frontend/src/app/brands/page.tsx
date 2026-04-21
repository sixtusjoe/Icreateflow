"use client";

import { useEffect, useState } from "react";
import { Trash2, Plus, Edit2, Users, Check, X, RefreshCw, ChevronDown, ChevronRight } from "lucide-react";
import { toast } from "sonner";
import {
  getBrands, createBrand, updateBrand, deleteBrand,
  createAccount, updateAccount, deleteAccount,
  refreshAccountProfile,
} from "@/lib/api";
import OAuthTiles from "@/components/OAuthTiles";

export default function BrandsPage() {
  const [brands, setBrands] = useState<any[]>([]);
  const [showNew, setShowNew] = useState(false);
  const [newBrand, setNewBrand] = useState({ name: "", slug: "", background_color: "#000000", timezone: "US/Eastern", default_post_times: "09:00,13:00,18:00" });
  const [showNewAccount, setShowNewAccount] = useState<number | null>(null);
  const [newAccount, setNewAccount] = useState({ name: "", role: "variation", tiktok_handle: "", youtube_handle: "", instagram_handle: "", facebook_handle: "" });
  const [editingBrand, setEditingBrand] = useState<number | null>(null);
  const [editBrandData, setEditBrandData] = useState<any>({});
  const [editingAccount, setEditingAccount] = useState<number | null>(null);
  const [editAccountData, setEditAccountData] = useState<any>({});
  const [collapsed, setCollapsed] = useState<Set<number>>(new Set());
  const toggleCollapsed = (id: number) =>
    setCollapsed((s) => {
      const next = new Set(s);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });

  const load = () => getBrands().then(setBrands).catch(() => toast.error("Failed to load brands"));
  useEffect(() => { load(); }, []);

  const handleCreateBrand = async () => {
    if (!newBrand.name || !newBrand.slug) return toast.error("Name and slug required");
    try {
      await createBrand(newBrand);
      setNewBrand({ name: "", slug: "", background_color: "#000000", timezone: "US/Eastern", default_post_times: "09:00,13:00,18:00" });
      setShowNew(false);
      load();
      toast.success("Brand created");
    } catch { toast.error("Failed to create brand"); }
  };

  const handleDeleteBrand = async (id: number) => {
    if (!confirm("Delete this brand and all its data?")) return;
    try { await deleteBrand(id); load(); toast.success("Brand deleted"); }
    catch { toast.error("Failed to delete"); }
  };

  const startEditBrand = (brand: any) => {
    setEditingBrand(brand.id);
    setEditBrandData({ name: brand.name, slug: brand.slug, background_color: brand.background_color, timezone: brand.timezone, default_post_times: brand.default_post_times });
  };

  const handleSaveBrand = async (id: number) => {
    try { await updateBrand(id, editBrandData); setEditingBrand(null); load(); toast.success("Brand updated"); }
    catch { toast.error("Failed to update brand"); }
  };

  const handleCreateAccount = async (brandId: number) => {
    if (!newAccount.name) return toast.error("Account name required");
    const clean = { ...newAccount };
    for (const key of ["tiktok_handle", "youtube_handle", "instagram_handle", "facebook_handle"] as const) {
      if (clean[key]) clean[key] = clean[key].replace(/^@+/, "");
    }
    try {
      await createAccount(brandId, clean);
      setNewAccount({ name: "", role: "variation", tiktok_handle: "", youtube_handle: "", instagram_handle: "", facebook_handle: "" });
      setShowNewAccount(null);
      load();
      toast.success("Account added");
    } catch { toast.error("Failed to add account"); }
  };

  const handleDeleteAccount = async (id: number) => {
    if (!confirm("Delete this account?")) return;
    try { await deleteAccount(id); load(); toast.success("Account deleted"); }
    catch { toast.error("Failed to delete"); }
  };

  const startEditAccount = (acc: any) => {
    setEditingAccount(acc.id);
    setEditAccountData({ name: acc.name, role: acc.role, tiktok_handle: acc.tiktok_handle || "", youtube_handle: acc.youtube_handle || "", instagram_handle: acc.instagram_handle || "", facebook_handle: acc.facebook_handle || "" });
  };

  const handleSaveAccount = async (id: number) => {
    const clean = { ...editAccountData };
    for (const key of ["tiktok_handle", "youtube_handle", "instagram_handle", "facebook_handle"]) {
      if (clean[key]) clean[key] = clean[key].replace(/^@+/, "");
    }
    try { await updateAccount(id, clean); setEditingAccount(null); load(); toast.success("Account updated"); }
    catch { toast.error("Failed to update account"); }
  };

  const displayHandle = (handle: string) => handle ? handle.replace(/^@+/, "") : "";

  const inputClass = "w-full rounded-lg border border-border bg-background px-4 py-2.5 text-base sm:text-sm outline-none transition-colors focus:border-foreground placeholder:text-muted-foreground";

  return (
    <div className="mx-auto max-w-4xl">
      <div className="mb-6 md:mb-8 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-xl md:text-2xl font-bold tracking-tight">Brands</h1>
          <p className="mt-1 text-sm text-muted-foreground">Manage your brands and their social accounts.</p>
        </div>
        <button onClick={() => setShowNew(true)}
          className="inline-flex min-h-[44px] w-full sm:w-auto items-center justify-center gap-2 rounded-lg bg-foreground px-5 py-2.5 text-sm font-medium text-background transition-opacity hover:opacity-90">
          <Plus className="h-4 w-4" /> Add Brand
        </button>
      </div>

      {/* New Brand Dialog */}
      {showNew && (
        <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/50 backdrop-blur-sm p-4" onClick={() => setShowNew(false)}>
          <div className="w-full max-w-lg max-h-[90vh] overflow-y-auto rounded-2xl bg-card p-5 md:p-6 shadow-xl" onClick={(e) => e.stopPropagation()}>
            <h2 className="mb-5 text-lg font-semibold">New Brand</h2>
            <div className="space-y-4">
              <div>
                <label className="mb-1.5 block text-sm font-medium">Brand Name</label>
                <input placeholder="e.g. FindsByMia" value={newBrand.name}
                  onChange={(e) => setNewBrand({ ...newBrand, name: e.target.value, slug: e.target.value.toLowerCase().replace(/[^a-z0-9]/g, "") })}
                  className={inputClass} />
              </div>
              <div>
                <label className="mb-1.5 block text-sm font-medium">Slug (URL-safe)</label>
                <input value={newBrand.slug} onChange={(e) => setNewBrand({ ...newBrand, slug: e.target.value })} className={inputClass} />
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label className="mb-1.5 block text-sm font-medium">Timezone</label>
                  <input value={newBrand.timezone} onChange={(e) => setNewBrand({ ...newBrand, timezone: e.target.value })} className={inputClass} />
                </div>
                <div>
                  <label className="mb-1.5 block text-sm font-medium">Background Color</label>
                  <div className="flex items-center gap-2">
                    <label className="relative h-10 w-10 flex-shrink-0 cursor-pointer rounded-lg border border-border" style={{ backgroundColor: newBrand.background_color }}>
                      <input type="color" value={newBrand.background_color} onChange={(e) => setNewBrand({ ...newBrand, background_color: e.target.value })} className="absolute inset-0 cursor-pointer opacity-0" />
                    </label>
                    <input value={newBrand.background_color} onChange={(e) => setNewBrand({ ...newBrand, background_color: e.target.value })} className={inputClass} />
                  </div>
                </div>
              </div>
              <div>
                <label className="mb-1.5 block text-sm font-medium">Default Post Times (comma-separated)</label>
                <input value={newBrand.default_post_times} onChange={(e) => setNewBrand({ ...newBrand, default_post_times: e.target.value })} placeholder="09:00,13:00,18:00" className={inputClass} />
              </div>
              <div className="flex gap-2">
                <button onClick={handleCreateBrand}
                  className="flex-1 min-h-[44px] rounded-lg bg-foreground px-5 py-2.5 text-sm font-medium text-background transition-opacity hover:opacity-90">
                  Create Brand
                </button>
                <button onClick={() => setShowNew(false)}
                  className="min-h-[44px] rounded-lg px-5 py-2.5 text-sm font-medium text-muted-foreground hover:text-foreground transition-colors">
                  Cancel
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {brands.length === 0 ? (
        <div className="rounded-2xl bg-card p-8 text-center">
          <p className="text-muted-foreground">No brands yet.</p>
          <p className="mt-1 text-sm text-muted-foreground/60">Click &quot;Add Brand&quot; to get started.</p>
        </div>
      ) : (
        <div className="space-y-4">
          {brands.map((brand: any) => (
            <div key={brand.id} className="rounded-2xl bg-card p-4 md:p-6">
              {/* Brand header */}
              {editingBrand === brand.id ? (
                <div className="mb-4 space-y-3 rounded-xl border border-border p-4">
                  <h4 className="text-sm font-semibold">Edit Brand</h4>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    <div>
                      <label className="mb-1 block text-xs font-medium">Name</label>
                      <input value={editBrandData.name} onChange={(e) => setEditBrandData({ ...editBrandData, name: e.target.value })} className={inputClass} />
                    </div>
                    <div>
                      <label className="mb-1 block text-xs font-medium">Slug</label>
                      <input value={editBrandData.slug} onChange={(e) => setEditBrandData({ ...editBrandData, slug: e.target.value })} className={inputClass} />
                    </div>
                    <div>
                      <label className="mb-1 block text-xs font-medium">Timezone</label>
                      <input value={editBrandData.timezone} onChange={(e) => setEditBrandData({ ...editBrandData, timezone: e.target.value })} className={inputClass} />
                    </div>
                    <div>
                      <label className="mb-1 block text-xs font-medium">Background Color</label>
                      <div className="flex items-center gap-2">
                        <label className="relative h-9 w-9 flex-shrink-0 cursor-pointer rounded-lg border border-border" style={{ backgroundColor: editBrandData.background_color }}>
                          <input type="color" value={editBrandData.background_color} onChange={(e) => setEditBrandData({ ...editBrandData, background_color: e.target.value })} className="absolute inset-0 cursor-pointer opacity-0" />
                        </label>
                        <input value={editBrandData.background_color} onChange={(e) => setEditBrandData({ ...editBrandData, background_color: e.target.value })} className={inputClass} />
                      </div>
                    </div>
                  </div>
                  <div>
                    <label className="mb-1 block text-xs font-medium">Default Post Times</label>
                    <input value={editBrandData.default_post_times} onChange={(e) => setEditBrandData({ ...editBrandData, default_post_times: e.target.value })} className={inputClass} />
                  </div>
                  <div className="flex gap-2">
                    <button onClick={() => handleSaveBrand(brand.id)}
                      className="inline-flex items-center gap-1.5 rounded-lg bg-foreground px-4 py-2 text-xs font-medium text-background transition-opacity hover:opacity-90">
                      <Check className="h-3 w-3" /> Save
                    </button>
                    <button onClick={() => setEditingBrand(null)}
                      className="inline-flex items-center gap-1.5 rounded-lg px-4 py-2 text-xs font-medium text-muted-foreground hover:text-foreground transition-colors">
                      <X className="h-3 w-3" /> Cancel
                    </button>
                  </div>
                </div>
              ) : (
                <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                  <div className="flex flex-wrap items-center gap-2 sm:gap-3">
                    <div className="h-4 w-4 rounded-full" style={{ backgroundColor: brand.background_color }} />
                    <h3 className="text-lg font-semibold">{brand.name}</h3>
                    <span className="rounded-md border border-border px-2 py-0.5 text-[11px] text-muted-foreground">{brand.slug}</span>
                    <span className="rounded-md border border-border px-2 py-0.5 text-[11px] text-muted-foreground">{brand.timezone}</span>
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    <button onClick={() => toggleCollapsed(brand.id)}
                      title={collapsed.has(brand.id) ? "Expand" : "Collapse"}
                      className="inline-flex min-h-[36px] items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-xs font-medium transition-colors hover:bg-muted">
                      {collapsed.has(brand.id) ? <ChevronRight className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
                      {collapsed.has(brand.id) ? `Show (${brand.accounts?.length || 0})` : "Hide"}
                    </button>
                    <button onClick={() => startEditBrand(brand)}
                      className="inline-flex min-h-[36px] items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-xs font-medium transition-colors hover:bg-muted">
                      <Edit2 className="h-3 w-3" /> Edit
                    </button>
                    <button onClick={() => { setCollapsed((s) => { const n = new Set(s); n.delete(brand.id); return n; }); setShowNewAccount(brand.id); }}
                      className="inline-flex min-h-[36px] items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-xs font-medium transition-colors hover:bg-muted">
                      <Plus className="h-3 w-3" /> Add Account
                    </button>
                    <button onClick={() => handleDeleteBrand(brand.id)}
                      className="inline-flex min-h-[36px] min-w-[36px] items-center justify-center rounded-lg p-1.5 text-muted-foreground hover:bg-muted hover:text-destructive transition-colors">
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                </div>
              )}

              {!collapsed.has(brand.id) && (<>
              <div className="mb-3 text-xs text-muted-foreground">
                Default times: {brand.default_post_times}
              </div>

              {/* Accounts */}
              <div className="space-y-2">
                <div className="flex items-center gap-2 text-xs text-muted-foreground">
                  <Users className="h-3.5 w-3.5" /> Accounts ({brand.accounts?.length || 0})
                </div>
                {brand.accounts?.map((acc: any) => (
                  editingAccount === acc.id ? (
                    <div key={acc.id} className="rounded-xl border border-border p-4">
                      <h4 className="mb-3 text-sm font-semibold">Edit Account</h4>
                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                        <div>
                          <label className="mb-1 block text-xs font-medium">Account Name</label>
                          <input value={editAccountData.name} onChange={(e) => setEditAccountData({ ...editAccountData, name: e.target.value })} className={inputClass} />
                        </div>
                        <div>
                          <label className="mb-1 block text-xs font-medium">Role</label>
                          <select value={editAccountData.role} onChange={(e) => setEditAccountData({ ...editAccountData, role: e.target.value })}
                            className="w-full rounded-lg border border-border bg-background px-4 py-2.5 text-base sm:text-sm outline-none focus:border-foreground">
                            <option value="master">Master</option>
                            <option value="variation">Variation</option>
                          </select>
                        </div>
                        {["tiktok", "youtube", "instagram", "facebook"].map((p) => (
                          <div key={p}>
                            <label className="mb-1 block text-xs font-medium capitalize">{p} Handle</label>
                            <input value={editAccountData[`${p}_handle`]}
                              onChange={(e) => setEditAccountData({ ...editAccountData, [`${p}_handle`]: e.target.value })}
                              placeholder="handle (without @)" className={inputClass} />
                          </div>
                        ))}
                      </div>
                      <div className="mt-3 flex gap-2">
                        <button onClick={() => handleSaveAccount(acc.id)}
                          className="inline-flex items-center gap-1.5 rounded-lg bg-foreground px-4 py-2 text-xs font-medium text-background transition-opacity hover:opacity-90">
                          <Check className="h-3 w-3" /> Save
                        </button>
                        <button onClick={() => setEditingAccount(null)}
                          className="inline-flex items-center gap-1.5 rounded-lg px-4 py-2 text-xs font-medium text-muted-foreground hover:text-foreground transition-colors">
                          <X className="h-3 w-3" /> Cancel
                        </button>
                      </div>
                    </div>
                  ) : (
                    <div key={acc.id} className="rounded-xl bg-muted/50 px-4 py-3">
                      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center gap-2 sm:gap-3">
                            <span className={`rounded-md px-2 py-0.5 text-[11px] font-medium ${
                              acc.role === "master" ? "bg-foreground text-background" : "bg-muted text-muted-foreground"
                            }`}>
                              {acc.role}
                            </span>
                            <span className="text-sm font-medium break-all">{acc.name}</span>
                          </div>
                          {(() => {
                            const handles = (["tiktok", "youtube", "instagram", "facebook"] as const)
                              .map((p) => {
                                const h = acc[`${p}_handle`] as string | undefined;
                                return h ? `${p}: @${h.replace(/^@+/, "")}` : null;
                              })
                              .filter(Boolean);
                            return handles.length > 0 ? (
                              <div className="mt-0.5 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-muted-foreground">
                                {handles.map((h, i) => <span key={i}>{h}</span>)}
                              </div>
                            ) : null;
                          })()}
                        </div>
                        <div className="flex items-center gap-1">
                          <button
                            onClick={async () => {
                              try {
                                const r = await refreshAccountProfile(acc.id);
                                const results = (r?.results || {}) as Record<string, { status: string; handles?: Record<string, string>; error?: string }>;
                                const ok: string[] = [];
                                const fail: string[] = [];
                                for (const [p, res] of Object.entries(results)) {
                                  if (res.status === "ok") ok.push(p);
                                  else if (res.status === "failed") fail.push(`${p}: ${res.error || "failed"}`);
                                }
                                if (ok.length) toast.success(`Refreshed: ${ok.join(", ")}`);
                                if (fail.length) toast.error(fail.join(" · "));
                                load();
                              } catch (e: any) {
                                toast.error(e?.response?.data?.detail || "Failed to refresh");
                              }
                            }}
                            className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-muted-foreground hover:text-foreground transition-colors"
                            title="Refresh handles from connected platforms"
                          >
                            <RefreshCw className="h-3.5 w-3.5" />
                          </button>
                          <button onClick={() => startEditAccount(acc)}
                            className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-muted-foreground hover:text-foreground transition-colors">
                            <Edit2 className="h-3.5 w-3.5" />
                          </button>
                          <button onClick={() => handleDeleteAccount(acc.id)}
                            className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-muted-foreground hover:text-destructive transition-colors">
                            <Trash2 className="h-3.5 w-3.5" />
                          </button>
                        </div>
                      </div>
                      <OAuthTiles account={acc} onChange={load} />
                    </div>
                  )
                ))}
              </div>

              {/* Add Account Form */}
              {showNewAccount === brand.id && (
                <div className="mt-4 rounded-xl border border-border p-4">
                  <h4 className="mb-3 text-sm font-semibold">Add Account</h4>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    <div>
                      <label className="mb-1 block text-xs font-medium">Account Name</label>
                      <input value={newAccount.name} onChange={(e) => setNewAccount({ ...newAccount, name: e.target.value })} placeholder="e.g. findsbymia_v2" className={inputClass} />
                    </div>
                    <div>
                      <label className="mb-1 block text-xs font-medium">Role</label>
                      <select value={newAccount.role} onChange={(e) => setNewAccount({ ...newAccount, role: e.target.value })}
                        className="w-full rounded-lg border border-border bg-background px-4 py-2.5 text-base sm:text-sm outline-none focus:border-foreground">
                        <option value="master">Master</option>
                        <option value="variation">Variation</option>
                      </select>
                    </div>
                    {["tiktok", "youtube", "instagram", "facebook"].map((p) => (
                      <div key={p}>
                        <label className="mb-1 block text-xs font-medium capitalize">{p} Handle</label>
                        <input value={newAccount[`${p}_handle` as keyof typeof newAccount]}
                          onChange={(e) => setNewAccount({ ...newAccount, [`${p}_handle`]: e.target.value })}
                          placeholder="handle (without @)" className={inputClass} />
                      </div>
                    ))}
                  </div>
                  <div className="mt-3 flex gap-2">
                    <button onClick={() => handleCreateAccount(brand.id)}
                      className="inline-flex items-center gap-1.5 rounded-lg bg-foreground px-4 py-2 text-xs font-medium text-background transition-opacity hover:opacity-90">
                      Add Account
                    </button>
                    <button onClick={() => setShowNewAccount(null)}
                      className="rounded-lg px-4 py-2 text-xs font-medium text-muted-foreground hover:text-foreground transition-colors">
                      Cancel
                    </button>
                  </div>
                </div>
              )}
              </>)}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
