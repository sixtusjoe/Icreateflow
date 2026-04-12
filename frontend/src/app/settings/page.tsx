"use client";

import { useEffect, useState } from "react";
import { Settings, Save, Eye, EyeOff, ChevronDown } from "lucide-react";
import { toast } from "sonner";
import { getSettings, updateSetting, getBrands, updateAccount } from "@/lib/api";

function SecretField({ label, value, onChange, onSave, placeholder, hint }: {
  label: string; value: string;
  onChange: (v: string) => void; onSave: () => void;
  placeholder?: string; hint?: string;
}) {
  const [show, setShow] = useState(false);
  return (
    <div>
      <label className="mb-1.5 block text-sm font-medium">{label}</label>
      <div className="flex gap-2">
        <div className="relative flex-1">
          <input
            type={show ? "text" : "password"}
            value={value}
            onChange={(e) => onChange(e.target.value)}
            placeholder={placeholder}
            className="w-full rounded-lg border border-border bg-background px-4 py-2.5 pr-10 text-sm outline-none transition-colors focus:border-foreground placeholder:text-muted-foreground"
          />
          <button
            className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
            onClick={() => setShow(!show)}
          >
            {show ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
          </button>
        </div>
        <button onClick={onSave}
          className="rounded-lg bg-foreground px-4 py-2.5 text-background transition-opacity hover:opacity-90">
          <Save className="h-4 w-4" />
        </button>
      </div>
      {hint && <p className="mt-1.5 text-xs text-muted-foreground/70">{hint}</p>}
    </div>
  );
}

export default function SettingsPage() {
  const [settings, setSettings] = useState<Record<string, string>>({});
  const [brands, setBrands] = useState<any[]>([]);
  const [selectedBrand, setSelectedBrand] = useState<number | null>(null);
  const [accountTokens, setAccountTokens] = useState<Record<number, Record<string, string>>>({});

  useEffect(() => {
    getSettings().then(setSettings).catch(() => {});
    getBrands().then((data) => {
      setBrands(data);
      if (data.length > 0) setSelectedBrand(data[0].id);
    }).catch(() => {});
  }, []);

  const selectedBrandData = brands.find((b: any) => b.id === selectedBrand);

  useEffect(() => {
    if (selectedBrandData?.accounts) {
      const tokens: Record<number, Record<string, string>> = {};
      for (const acc of selectedBrandData.accounts) {
        tokens[acc.id] = {
          tiktok_token: acc.tiktok_token || "",
          youtube_token: acc.youtube_token || "",
          instagram_token: acc.instagram_token || "",
          facebook_token: acc.facebook_token || "",
        };
      }
      setAccountTokens(tokens);
    }
  }, [selectedBrand, brands]);

  const saveGlobal = async (key: string, value: string) => {
    try { await updateSetting(key, value); toast.success("Saved"); }
    catch { toast.error("Failed to save"); }
  };

  const val = (key: string, fallback = "") => settings[key] ?? fallback;
  const update = (key: string, value: string) => setSettings((s) => ({ ...s, [key]: value }));

  const updateToken = (accountId: number, field: string, value: string) => {
    setAccountTokens((prev) => ({ ...prev, [accountId]: { ...prev[accountId], [field]: value } }));
  };

  const saveAccountToken = async (accountId: number, field: string) => {
    try {
      await updateAccount(accountId, { [field]: accountTokens[accountId]?.[field] || "" });
      toast.success("Token saved");
      const data = await getBrands(); setBrands(data);
    } catch { toast.error("Failed"); }
  };

  const saveAllAccountTokens = async (accountId: number) => {
    try {
      await updateAccount(accountId, accountTokens[accountId] || {});
      toast.success("All tokens saved");
      const data = await getBrands(); setBrands(data);
    } catch { toast.error("Failed"); }
  };

  return (
    <div className="mx-auto max-w-3xl">
      <div className="mb-8">
        <h1 className="text-2xl font-bold tracking-tight">Settings</h1>
        <p className="mt-1 text-sm text-muted-foreground">Configure API keys, platform tokens, and defaults.</p>
      </div>

      {/* AI & OCR */}
      <div className="mb-6 rounded-2xl bg-card p-6">
        <h2 className="mb-5 text-base font-semibold">AI & OCR</h2>
        <div className="space-y-5">
          <SecretField
            label="Google Cloud Vision API Key"
            value={settings["google_vision_api_key"] ?? ""}
            onChange={(v) => update("google_vision_api_key", v)}
            onSave={() => saveGlobal("google_vision_api_key", settings["google_vision_api_key"] || "")}
            placeholder="AIza..."
            hint="Enables OCR text extraction from slides."
          />
          <SecretField
            label="Replicate API Token"
            value={settings["replicate_api_token"] ?? ""}
            onChange={(v) => update("replicate_api_token", v)}
            onSave={() => saveGlobal("replicate_api_token", settings["replicate_api_token"] || "")}
            placeholder="r8_..."
            hint="For AI face generation in variations."
          />
        </div>
      </div>

      {/* Platform Tokens */}
      <div className="mb-6 rounded-2xl bg-card p-6">
        <h2 className="mb-2 text-base font-semibold">Platform API Tokens</h2>
        <p className="mb-5 text-sm text-muted-foreground">Each account needs its own API credentials.</p>

        <div className="mb-5">
          <label className="mb-1.5 block text-sm font-medium">Brand</label>
          <select
            value={selectedBrand ?? ""}
            onChange={(e) => setSelectedBrand(e.target.value ? Number(e.target.value) : null)}
            className="w-full rounded-lg border border-border bg-background px-4 py-2.5 text-sm outline-none focus:border-foreground"
          >
            {brands.length === 0 && <option value="">No brands yet</option>}
            {brands.map((b: any) => <option key={b.id} value={b.id}>{b.name}</option>)}
          </select>
        </div>

        {selectedBrandData?.accounts?.length > 0 ? (
          <div className="space-y-3">
            {selectedBrandData.accounts.map((acc: any) => (
              <details key={acc.id} className="group rounded-xl border border-border overflow-hidden">
                <summary className="flex cursor-pointer items-center justify-between px-4 py-3">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium">{acc.name}</span>
                    <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground uppercase">{acc.role}</span>
                    {(acc.tiktok_token || acc.youtube_token || acc.instagram_token || acc.facebook_token) && (
                      <span className="rounded bg-foreground/10 px-1.5 py-0.5 text-[10px] font-medium">configured</span>
                    )}
                  </div>
                  <ChevronDown className="h-4 w-4 text-muted-foreground transition-transform group-open:rotate-180" />
                </summary>
                <div className="space-y-4 border-t border-border px-4 py-4">
                  {["tiktok", "youtube", "instagram", "facebook"].map((p) => (
                    <div key={p}>
                      <div className="mb-1 flex items-center gap-2">
                        <span className="text-xs font-semibold capitalize">{p}</span>
                        {acc[`${p}_handle`] && <span className="text-xs text-muted-foreground">@{acc[`${p}_handle`].replace(/^@+/, "")}</span>}
                      </div>
                      <SecretField
                        label="Access Token"
                        value={accountTokens[acc.id]?.[`${p}_token`] ?? ""}
                        onChange={(v) => updateToken(acc.id, `${p}_token`, v)}
                        onSave={() => saveAccountToken(acc.id, `${p}_token`)}
                        placeholder={`${p.charAt(0).toUpperCase() + p.slice(1)} access token...`}
                      />
                    </div>
                  ))}
                  <button
                    className="flex w-full items-center justify-center gap-2 rounded-lg bg-foreground px-4 py-2.5 text-sm font-medium text-background transition-opacity hover:opacity-90"
                    onClick={() => saveAllAccountTokens(acc.id)}
                  >
                    <Save className="h-4 w-4" /> Save All Tokens for {acc.name}
                  </button>
                </div>
              </details>
            ))}
          </div>
        ) : (
          <div className="rounded-xl border border-border p-6 text-center text-sm text-muted-foreground">
            {selectedBrandData ? "No accounts for this brand yet." : "Select a brand above."}
          </div>
        )}
      </div>

      {/* Overlay */}
      <div className="mb-6 rounded-2xl bg-card p-6">
        <h2 className="mb-5 text-base font-semibold">Text Overlay Defaults</h2>
        <div className="grid grid-cols-2 gap-4">
          {[
            { label: "Hook Font Size", key: "hook_font_size", fb: "52" },
            { label: "Title Font Size", key: "title_font_size", fb: "44" },
            { label: "Body Font Size", key: "body_font_size", fb: "36" },
          ].map((f) => (
            <div key={f.key}>
              <label className="mb-1.5 block text-sm font-medium">{f.label}</label>
              <input type="number" value={val(f.key, f.fb)} onChange={(e) => update(f.key, e.target.value)}
                className="w-full rounded-lg border border-border bg-background px-4 py-2.5 text-sm outline-none focus:border-foreground" />
            </div>
          ))}
          <div>
            <label className="mb-1.5 block text-sm font-medium">Text Color</label>
            <div className="flex items-center gap-2">
              <label className="relative h-10 w-10 flex-shrink-0 cursor-pointer rounded-lg border border-border" style={{ backgroundColor: val("text_color", "#FFFFFF") }}>
                <input type="color" value={val("text_color", "#FFFFFF")} onChange={(e) => update("text_color", e.target.value)} className="absolute inset-0 cursor-pointer opacity-0" />
              </label>
              <input value={val("text_color", "#FFFFFF")} onChange={(e) => update("text_color", e.target.value)}
                className="flex-1 rounded-lg border border-border bg-background px-4 py-2.5 text-sm outline-none focus:border-foreground" />
            </div>
          </div>
        </div>
        <button className="mt-5 inline-flex items-center gap-2 rounded-lg bg-foreground px-5 py-2.5 text-sm font-medium text-background transition-opacity hover:opacity-90"
          onClick={() => { saveGlobal("hook_font_size", val("hook_font_size", "52")); saveGlobal("title_font_size", val("title_font_size", "44")); saveGlobal("body_font_size", val("body_font_size", "36")); saveGlobal("text_color", val("text_color", "#FFFFFF")); }}>
          <Save className="h-4 w-4" /> Save Overlay Settings
        </button>
      </div>

      {/* Video */}
      <div className="mb-6 rounded-2xl bg-card p-6">
        <h2 className="mb-5 text-base font-semibold">Video Defaults</h2>
        <div className="grid grid-cols-3 gap-4">
          <div>
            <label className="mb-1.5 block text-sm font-medium">Slide Duration (s)</label>
            <input type="number" step="0.5" value={val("slide_duration", "3.0")} onChange={(e) => update("slide_duration", e.target.value)}
              className="w-full rounded-lg border border-border bg-background px-4 py-2.5 text-sm outline-none focus:border-foreground" />
          </div>
          <div>
            <label className="mb-1.5 block text-sm font-medium">Transition (s)</label>
            <input type="number" step="0.1" value={val("transition_duration", "0.5")} onChange={(e) => update("transition_duration", e.target.value)}
              className="w-full rounded-lg border border-border bg-background px-4 py-2.5 text-sm outline-none focus:border-foreground" />
          </div>
          <div>
            <label className="mb-1.5 block text-sm font-medium">FPS</label>
            <input type="number" value={val("fps", "30")} onChange={(e) => update("fps", e.target.value)}
              className="w-full rounded-lg border border-border bg-background px-4 py-2.5 text-sm outline-none focus:border-foreground" />
          </div>
        </div>
        <button className="mt-5 inline-flex items-center gap-2 rounded-lg bg-foreground px-5 py-2.5 text-sm font-medium text-background transition-opacity hover:opacity-90"
          onClick={() => { saveGlobal("slide_duration", val("slide_duration", "3.0")); saveGlobal("transition_duration", val("transition_duration", "0.5")); saveGlobal("fps", val("fps", "30")); }}>
          <Save className="h-4 w-4" /> Save Video Settings
        </button>
      </div>
    </div>
  );
}
