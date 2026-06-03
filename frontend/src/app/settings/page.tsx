"use client";

import { useEffect, useState } from "react";
import { Save, Eye, EyeOff, Link2 } from "lucide-react";
import Link from "next/link";
import { toast } from "sonner";
import { getSettings, updateSetting, getUserSettings, updateUserSetting, getDiscoveryStatus } from "@/lib/api";

function timeAgo(iso: string): string {
  const secs = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (secs < 60) return `${secs}s ago`;
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
  return `${Math.floor(secs / 3600)}h ago`;
}

const DISCOVERY_PLATFORMS = [
  { key: "tiktok",    label: "TikTok",    color: "#000000", darkColor: "#ffffff" },
  { key: "instagram", label: "Instagram", color: "#e1306c", darkColor: "#e1306c" },
  { key: "youtube",   label: "YouTube",   color: "#ff0000", darkColor: "#ff0000" },
  { key: "facebook",  label: "Facebook",  color: "#1877f2", darkColor: "#1877f2" },
];

function ToggleRow({ title, desc, on, onToggle }: {
  title: string; desc: string; on: boolean; onToggle: (v: boolean) => void;
}) {
  return (
    <div className="rounded-lg border border-border p-3">
      <div className="mb-1 text-sm font-medium">{title}</div>
      <p className="mb-3 text-xs text-muted-foreground">{desc}</p>
      <label className="inline-flex cursor-pointer items-center gap-3">
        <input
          type="checkbox"
          checked={on}
          onChange={(e) => onToggle(e.target.checked)}
          className="h-4 w-4"
        />
        <span className="text-sm font-medium">{on ? "Enabled" : "Disabled"}</span>
      </label>
    </div>
  );
}


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
            className="w-full rounded-lg border border-border bg-background px-4 py-2.5 pr-10 text-base sm:text-sm outline-none transition-colors focus:border-foreground placeholder:text-muted-foreground"
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
  const [userSettings, setUserSettings] = useState<Record<string, string>>({});
  const [discoveryStatus, setDiscoveryStatus] = useState<{ platforms: { platform: string; last_count: number; last_run_at: string | null }[] } | null>(null);

  useEffect(() => {
    getSettings().then(setSettings).catch(() => {});
    getUserSettings().then(setUserSettings).catch(() => {});
    getDiscoveryStatus().then(setDiscoveryStatus).catch(() => {});
    const iv = setInterval(() => getDiscoveryStatus().then(setDiscoveryStatus).catch(() => {}), 30_000);
    return () => clearInterval(iv);
  }, []);

  const saveGlobal = async (key: string, value: string) => {
    try { await updateSetting(key, value); toast.success("Saved"); }
    catch { toast.error("Failed to save"); }
  };

  const saveUser = async (key: string, value: string) => {
    setUserSettings((s) => ({ ...s, [key]: value }));
    try { await updateUserSetting(key, value); }
    catch { toast.error("Failed to save"); }
  };

  // Truthy parse — default ON for diversify/captions, OFF for catchup.
  const isOn = (key: string, defaultOn: boolean) => {
    const v = userSettings[key];
    if (v === undefined || v === null) return defaultOn;
    return !["0", "false", "False", ""].includes(v);
  };

  const val = (key: string, fallback = "") => settings[key] ?? fallback;
  const update = (key: string, value: string) => setSettings((s) => ({ ...s, [key]: value }));

  const inputNumClass = "w-full rounded-lg border border-border bg-background px-4 py-2.5 text-base sm:text-sm outline-none focus:border-foreground";

  return (
    <div className="mx-auto max-w-3xl">
      <div className="mb-6 md:mb-8">
        <h1 className="text-xl md:text-2xl font-bold tracking-tight">Settings</h1>
        <p className="mt-1 text-sm text-muted-foreground">Configure API keys and defaults.</p>
      </div>

      {/* AI & OCR */}
      <div className="mb-6 rounded-2xl bg-card p-4 md:p-6">
        <h2 className="mb-5 text-base font-semibold">AI & OCR</h2>
        <div className="space-y-5">
          <SecretField
            label="Anthropic API Key (Claude Vision OCR)"
            value={settings["anthropic_api_key"] ?? ""}
            onChange={(v) => update("anthropic_api_key", v)}
            onSave={() => saveGlobal("anthropic_api_key", settings["anthropic_api_key"] || "")}
            placeholder="sk-ant-..."
            hint="Powers AI text extraction from slides using Claude Vision."
          />
          <SecretField
            label="OpenAI API Key"
            value={settings["openai_api_key"] ?? ""}
            onChange={(v) => update("openai_api_key", v)}
            onSave={() => saveGlobal("openai_api_key", settings["openai_api_key"] || "")}
            placeholder="sk-..."
            hint="For AI image generation in variations (gpt-image-1)."
          />
        </div>
      </div>

      {/* Clipping toggles (per-user) */}
      <div className="mb-6 rounded-2xl bg-card p-4 md:p-6">
        <h2 className="mb-5 text-base font-semibold">Clipping behaviour</h2>
        <div className="space-y-5">
          <ToggleRow
            title="Per-variation video diversification"
            desc="Re-encodes each clip with imperceptible video/audio changes per (clip, variation, platform) so the same clip posted across variations looks different to platform reuse detection. Turn off to post raw clips."
            on={isOn("clip_diversification_enabled", true)}
            onToggle={(v) => saveUser("clip_diversification_enabled", v ? "1" : "0")}
          />
          <ToggleRow
            title="Per-variation caption paraphrasing"
            desc="Uses Claude to rewrite each clip's caption per (clip, variation, platform) so the text fingerprint differs across accounts. Cached, so each combo generates once. Requires an Anthropic API key above."
            on={isOn("clip_caption_variants_enabled", true)}
            onToggle={(v) => saveUser("clip_caption_variants_enabled", v ? "1" : "0")}
          />
        </div>
      </div>

      {/* Social connections pointer */}
      <div className="mb-6 rounded-2xl bg-card p-4 md:p-6">
        <h2 className="mb-2 text-base font-semibold">Social Accounts</h2>
        <p className="mb-4 text-sm text-muted-foreground">
          TikTok, YouTube, Instagram, and Facebook are now connected per-account via OAuth — no tokens to paste.
          Open a brand and click <strong>Connect</strong> on each account's platform tile.
        </p>
        <Link href="/brands"
          className="inline-flex min-h-[44px] items-center gap-2 rounded-lg border border-border px-4 py-2.5 text-sm font-medium transition-colors hover:bg-muted">
          <Link2 className="h-4 w-4" /> Go to Brands
        </Link>
      </div>

      {/* Overlay */}
      <div className="mb-6 rounded-2xl bg-card p-4 md:p-6">
        <h2 className="mb-5 text-base font-semibold">Text Overlay Defaults</h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {[
            { label: "Hook Font Size", key: "hook_font_size", fb: "52" },
            { label: "Title Font Size", key: "title_font_size", fb: "44" },
            { label: "Body Font Size", key: "body_font_size", fb: "36" },
          ].map((f) => (
            <div key={f.key}>
              <label className="mb-1.5 block text-sm font-medium">{f.label}</label>
              <input type="number" value={val(f.key, f.fb)} onChange={(e) => update(f.key, e.target.value)}
                className={inputNumClass} />
            </div>
          ))}
          <div>
            <label className="mb-1.5 block text-sm font-medium">Text Color</label>
            <div className="flex items-center gap-2">
              <label className="relative h-10 w-10 flex-shrink-0 cursor-pointer rounded-lg border border-border" style={{ backgroundColor: val("text_color", "#FFFFFF") }}>
                <input type="color" value={val("text_color", "#FFFFFF")} onChange={(e) => update("text_color", e.target.value)} className="absolute inset-0 cursor-pointer opacity-0" />
              </label>
              <input value={val("text_color", "#FFFFFF")} onChange={(e) => update("text_color", e.target.value)}
                className={`flex-1 ${inputNumClass}`} />
            </div>
          </div>
        </div>
        <button className="mt-5 inline-flex min-h-[44px] items-center gap-2 rounded-lg bg-foreground px-5 py-2.5 text-sm font-medium text-background transition-opacity hover:opacity-90"
          onClick={() => { saveGlobal("hook_font_size", val("hook_font_size", "52")); saveGlobal("title_font_size", val("title_font_size", "44")); saveGlobal("body_font_size", val("body_font_size", "36")); saveGlobal("text_color", val("text_color", "#FFFFFF")); }}>
          <Save className="h-4 w-4" /> Save Overlay Settings
        </button>
      </div>

      {/* Post Discovery Status */}
      <div className="mb-6 rounded-2xl bg-card p-4 md:p-6">
        <h2 className="mb-1 text-base font-semibold">Post Discovery</h2>
        <p className="mb-5 text-xs text-muted-foreground">
          Finds videos posted from your phone and adds them for view tracking.
          TikTok runs every 15 min · Instagram, YouTube &amp; Facebook run every hour.
        </p>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          {DISCOVERY_PLATFORMS.map(({ key, label, color }) => {
            const item = discoveryStatus?.platforms?.find((p) => p.platform === key);
            const count = item?.last_count ?? 0;
            const lastRun = item?.last_run_at;
            const radius = 28;
            const circ = 2 * Math.PI * radius;
            // Ring is full once a discovery run has completed; the count in
            // the centre is what that run found. Empty grey ring if never run.
            const fill = lastRun ? 1 : 0;
            return (
              <div key={key} className="flex flex-col items-center gap-2">
                <div className="relative h-20 w-20">
                  <svg viewBox="0 0 72 72" className="h-full w-full -rotate-90">
                    <circle cx="36" cy="36" r={radius} fill="none"
                      stroke="currentColor" strokeWidth="5" className="text-muted-foreground/20" />
                    <circle cx="36" cy="36" r={radius} fill="none"
                      stroke={count > 0 ? color : "currentColor"} strokeWidth="5"
                      className={count > 0 ? "" : "text-muted-foreground/30"}
                      strokeDasharray={circ}
                      strokeDashoffset={circ * (1 - fill)}
                      strokeLinecap="round"
                      style={{ transition: "stroke-dashoffset 0.6s ease" }} />
                  </svg>
                  <span className="absolute inset-0 flex items-center justify-center text-lg font-bold">
                    {count}
                  </span>
                </div>
                <span className="text-xs font-semibold capitalize">{label}</span>
                <span className="text-[11px] text-muted-foreground text-center">
                  {lastRun ? `last: ${timeAgo(lastRun)}` : "not run yet"}
                </span>
              </div>
            );
          })}
        </div>
      </div>

      {/* Video */}
      <div className="mb-6 rounded-2xl bg-card p-4 md:p-6">
        <h2 className="mb-5 text-base font-semibold">Video Defaults</h2>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <div>
            <label className="mb-1.5 block text-sm font-medium">Slide Duration (s)</label>
            <input type="number" step="0.5" value={val("slide_duration", "3.0")} onChange={(e) => update("slide_duration", e.target.value)}
              className={inputNumClass} />
          </div>
          <div>
            <label className="mb-1.5 block text-sm font-medium">Transition (s)</label>
            <input type="number" step="0.1" value={val("transition_duration", "0.5")} onChange={(e) => update("transition_duration", e.target.value)}
              className={inputNumClass} />
          </div>
          <div>
            <label className="mb-1.5 block text-sm font-medium">FPS</label>
            <input type="number" value={val("fps", "30")} onChange={(e) => update("fps", e.target.value)}
              className={inputNumClass} />
          </div>
        </div>
        <button className="mt-5 inline-flex min-h-[44px] items-center gap-2 rounded-lg bg-foreground px-5 py-2.5 text-sm font-medium text-background transition-opacity hover:opacity-90"
          onClick={() => { saveGlobal("slide_duration", val("slide_duration", "3.0")); saveGlobal("transition_duration", val("transition_duration", "0.5")); saveGlobal("fps", val("fps", "30")); }}>
          <Save className="h-4 w-4" /> Save Video Settings
        </button>
      </div>
    </div>
  );
}
