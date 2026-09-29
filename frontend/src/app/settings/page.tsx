"use client";

/** Settings.
 *
 *  The page leads with which features are actually live, because a missing
 *  key here is a feature that fails silently three pages away — "Make it
 *  with AI" on the Variations step just refuses, and nothing on that screen
 *  says why.
 *
 *  Two facts about scope that the old page got wrong and this one states:
 *
 *  - `anthropic_api_key` and `openai_api_key` are stored per user
 *    (`_PER_USER_SETTING_KEYS` in main.py) and overlaid on the global row
 *    by `GET /api/settings`. Only `google_vision_api_key` is one key for
 *    the workspace. The old copy called all three workspace-wide.
 *  - `oauth_redirect_base` is not a setting at all. It is site_config,
 *    admin-only, written by `PUT /api/admin/oauth-apps/_base` on Admin.
 *    The Schedule banner used to send people here to set it, and there has
 *    never been a field for it. That dead end is closed by naming Admin.
 *
 *  Overlay and video numbers are read from `settings`, which on this
 *  workspace has no row for any of them. The old page printed its own
 *  fallbacks into the boxes as though they had been saved, so every field
 *  looked configured and none of it was. Here the fallbacks are still shown
 *  — you cannot edit a number you cannot see — but the card says they are
 *  built-in and that saving writes them down for the first time.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Check,
  ChevronRight,
  ExternalLink,
  Eye,
  FileText,
  Info,
  RefreshCw,
  Shield,
} from "lucide-react";
import Link from "next/link";
import { toast } from "sonner";
import {
  getBrands,
  getDiscoveryStatus,
  getSettings,
  getUserSettings,
  updateSetting,
  updateUserSetting,
} from "@/lib/api";
import {
  Card,
  CardBody,
  CardHead,
  Chip,
  ChipCount,
  DotsMenu,
  FigureLine,
  FigureStrong,
  Note,
  PageActions,
  PageHead,
  PageTitle,
  PrimaryButton,
  Skeleton,
  Tag,
  TwoCol,
} from "@/components/kit";
import { Input } from "@/components/kit/dialog";
import { apiErrorMessage } from "@/components/kit/format";

/* ------------------------------------------------------------------ */
/* the three keys                                                      */
/* ------------------------------------------------------------------ */

type KeySpec = {
  key: string;
  label: string;
  /** What this key switches on, in the words of the screen it affects. */
  powers: string;
  /** What breaks without it — only shown when it is missing. */
  without: string;
  placeholder: string;
};

const KEYS: KeySpec[] = [
  {
    key: "anthropic_api_key",
    label: "Anthropic",
    powers: "Reading the text off imported slides, and rewriting clip captions per account",
    without: "Slides import with no text, and every caption goes out identical",
    placeholder: "sk-ant-…",
  },
  {
    key: "openai_api_key",
    label: "OpenAI",
    powers: "Making a slide's picture with AI, on the Variations step",
    without: "“Make it with AI” fails; accounts can only keep the original or take an upload",
    placeholder: "sk-…",
  },
  {
    key: "google_vision_api_key",
    label: "Google Vision",
    powers: "The fallback reader when Claude cannot make out a slide",
    without: "A slide Claude cannot read comes back empty instead of being retried",
    placeholder: "AIza…",
  },
];

const TEXT_KEYS = ["hook_font_size", "title_font_size", "body_font_size", "text_color"] as const;
/** The sizes `overlay.py` actually renders at (HOOK_BASE / TITLE_BASE /
 *  BODY_BASE), not the numbers the old page printed. Saving these is a
 *  no-op by construction — which is the point: nothing moves until you
 *  move it. */
const TEXT_FALLBACK: Record<string, string> = {
  hook_font_size: "56",
  title_font_size: "52",
  body_font_size: "38",
  text_color: "#FFFFFF",
};

const VIDEO_KEYS = ["slide_duration", "transition_duration", "fps"] as const;
const VIDEO_FALLBACK: Record<string, string> = {
  slide_duration: "3.0",
  transition_duration: "0.5",
  fps: "30",
};

const DISCOVERY = [
  { key: "tiktok", label: "TikTok" },
  { key: "instagram", label: "Instagram" },
  { key: "youtube", label: "YouTube" },
  { key: "facebook", label: "Facebook" },
];

const WORDS = ["no", "one", "two", "three"];
const SHORT = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short" });

/** Enough of a key to recognise it, never enough to use it. */
const mask = (v: string) => (v.length <= 14 ? "•".repeat(v.length) : `${v.slice(0, 7)}…${v.slice(-7)}`);

function ago(iso: string): string {
  const secs = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (secs < 60) return "just now";
  if (secs < 3600) return `${Math.floor(secs / 60)} min ago`;
  if (secs < 86400) return `${Math.floor(secs / 3600)} h ago`;
  return SHORT.format(new Date(iso));
}

/* ------------------------------------------------------------------ */
/* rows                                                                */
/* ------------------------------------------------------------------ */

/** A feature, and whether it can run. The icon tile carries the state so
 *  the row reads at a glance; the sub-line says what it depends on. */
function FeatureRow({ on, name, sub }: { on: boolean; name: string; sub: string }) {
  return (
    <div
      className={`flex items-center gap-2.5 rounded-[12px] border bg-card px-3 py-2.5 ${
        on ? "border-border" : "border-bad/30"
      }`}
    >
      <span
        className={`grid h-[26px] w-[26px] flex-none place-items-center rounded-full ${
          on ? "bg-good/15 text-good" : "bg-bad/[0.13] text-bad"
        }`}
      >
        {on ? (
          <Check className="h-[13px] w-[13px]" strokeWidth={3} />
        ) : (
          <Info className="h-[13px] w-[13px]" strokeWidth={2.2} />
        )}
      </span>
      <span className="flex min-w-0 flex-col gap-px">
        <span className="text-[13px] font-semibold leading-normal text-foreground">{name}</span>
        <span className={`truncate text-[11px] leading-normal ${on ? "text-subtle" : "text-bad"}`}>{sub}</span>
      </span>
    </div>
  );
}

/** A pointer at the page that really owns a setting. */
/** A pointer to where a setting really lives.
 *
 *  `href` is optional because one of these is somewhere the reader may not
 *  be allowed to go. A row that looks like a link and bounces you to the
 *  dashboard is worse than a row that says who to ask. */
function ElsewhereRow({
  href,
  icon: Icon,
  title,
  sub,
}: {
  href?: string;
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  sub: React.ReactNode;
}) {
  const body = (
    <>
      <span className="grid h-[29px] w-[29px] flex-none place-items-center rounded-[9px] border border-border bg-secondary text-muted-foreground">
        <Icon className="h-3.5 w-3.5" />
      </span>
      <span className="flex min-w-0 flex-col gap-px">
        <span className="text-[13px] font-semibold leading-normal text-foreground">{title}</span>
        <span className="truncate text-[11px] leading-normal text-subtle">{sub}</span>
      </span>
      {href && <ChevronRight className="ml-auto h-3.5 w-3.5 flex-none text-subtle" />}
    </>
  );
  const cls = "flex items-center gap-2.5 rounded-[12px] border border-border bg-card px-3 py-2.5";
  return href ? (
    <Link href={href} className={`${cls} transition-colors hover:bg-secondary`}>
      {body}
    </Link>
  ) : (
    <div className={cls}>{body}</div>
  );
}

/** A name, what it is, and the value — the shape both defaults cards use.
 *  A bare box labelled "Title" never said that most slides have none. */
function SettingRow({
  name,
  sub,
  children,
}: {
  name: string;
  sub: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-center gap-3 rounded-[12px] border border-border bg-card px-3 py-[9px]">
      <span className="flex min-w-0 flex-1 flex-col gap-px">
        <span className="text-[13px] font-semibold leading-normal text-foreground">{name}</span>
        <span className="truncate text-[11px] leading-normal text-subtle">{sub}</span>
      </span>
      {children}
    </div>
  );
}

/** A number with its unit pinned inside the box, so the unit is not a
 *  separate column that has to line up. */
function NumField({
  value,
  unit,
  onChange,
}: {
  value: string;
  unit: string;
  onChange: (v: string) => void;
}) {
  return (
    <span className="relative flex w-[122px] flex-none items-center">
      <Input value={value} onChange={(e) => onChange(e.target.value)} className="pr-[34px]" />
      <em className="pointer-events-none absolute right-[11px] text-[11px] not-italic text-subtle">{unit}</em>
    </span>
  );
}

/** The footer band: the note that qualifies the button, then the button.
 *  It wraps, because the Video card is 372px wide and a note squeezed
 *  beside a button there becomes a five-line column. */
function CardFoot({ note, children }: { note: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-3 border-t border-line-2 pt-3.5">
      <span className="flex min-w-0 flex-[1_1_270px] items-start gap-1.5 text-[11px] leading-[1.45] text-subtle">
        <Info className="mt-0.5 h-3 w-3 flex-none" />
        <span>{note}</span>
      </span>
      <span className="ml-auto flex-none">{children}</span>
    </div>
  );
}

/** A bordered checkbox row — the toggle is the whole row, not a 16px box
 *  with a sentence beside it. */
function BigCheck({
  checked,
  onChange,
  title,
  children,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <label className="flex cursor-pointer items-start gap-2.5 rounded-[13px] border border-border bg-card px-[13px] py-3">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="pointer-events-none absolute opacity-0"
      />
      <span
        className={`mt-px grid h-4 w-4 flex-none place-items-center rounded-[5px] border-[1.5px] transition-colors ${
          checked ? "border-primary bg-primary text-primary-foreground" : "border-border bg-card text-transparent"
        }`}
      >
        <Check className="h-[11px] w-[11px]" strokeWidth={3} />
      </span>
      <span className="flex min-w-0 flex-col gap-px">
        <span className="text-[13px] font-semibold leading-normal text-muted-foreground">{title}</span>
        <span className="text-[11px] leading-[1.5] text-subtle">{children}</span>
      </span>
    </label>
  );
}

/** Never run means an empty ring and a dash. A zero inside a full ring
 *  would read as "ran, found nothing", which is a different fact. */
function Ring({ label, count, lastRun }: { label: string; count: number; lastRun: string | null }) {
  return (
    <div className="flex flex-col items-center gap-1.5">
      <div className="relative h-[74px] w-[74px]">
        <svg viewBox="0 0 72 72" className="h-full w-full -rotate-90">
          <circle cx="36" cy="36" r="28" fill="none" stroke="currentColor" strokeWidth="5" className="text-border" />
        </svg>
        <span
          className={`absolute inset-0 grid place-items-center text-[17px] font-extrabold tabular-nums ${
            lastRun ? "text-foreground" : "text-subtle"
          }`}
        >
          {lastRun ? count : "—"}
        </span>
      </div>
      <span className="text-[11.5px] font-semibold leading-normal text-foreground">{label}</span>
      <span className="text-[10.5px] leading-normal text-subtle">{lastRun ? ago(lastRun) : "never run"}</span>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* the key rows                                                        */
/* ------------------------------------------------------------------ */

function KeyRow({
  spec,
  saved,
  revealed,
  onReveal,
  last,
}: {
  spec: KeySpec;
  saved: string;
  revealed: boolean;
  onReveal: (v: boolean) => void;
  last: boolean;
}) {
  const [draft, setDraft] = useState(saved);
  const [busy, setBusy] = useState(false);

  // The server is the source of truth: a save elsewhere on the page, or a
  // re-check from the menu, has to land in the box.
  useEffect(() => setDraft(saved), [saved]);

  const set = !!saved.trim();
  // An unset key has nothing to hide, so it is always an open field.
  const open = revealed || !set;
  const dirty = draft !== saved;

  const save = async () => {
    setBusy(true);
    try {
      await updateSetting(spec.key, draft.trim());
      toast.success(draft.trim() ? `${spec.label} key saved` : `${spec.label} key cleared`);
      window.dispatchEvent(new Event("settings:changed"));
    } catch (e) {
      toast.error(apiErrorMessage(e, "Could not save the key"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={`py-[13px] ${last ? "pb-1" : "border-b border-line-2"} first:pt-0`}>
      <div className="mb-[9px] flex items-center gap-2.5">
        <span className="flex min-w-0 flex-1 flex-col gap-px">
          <span className="text-[13px] font-semibold leading-normal text-foreground">{spec.label}</span>
          <span className="truncate text-[11px] leading-normal text-subtle">{spec.powers}</span>
        </span>
        <Tag tone={set ? "done" : "stop"}>{set ? "Set" : "Not set"}</Tag>
      </div>

      <div className="flex items-center gap-2">
        <Input
          value={open ? draft : mask(saved)}
          readOnly={!open}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={set ? spec.placeholder : "Paste the key to switch this on"}
          spellCheck={false}
          autoComplete="off"
          className={`min-w-0 flex-1 font-mono text-xs ${set ? "" : "border-bad/30"}`}
        />
        {set && (
          <Chip icon={Eye} onClick={() => onReveal(!revealed)}>
            {revealed ? "Hide" : "Reveal"}
          </Chip>
        )}
        <Chip icon={Check} onClick={save} disabled={busy || !dirty}>
          Save
        </Chip>
      </div>

      {!set && (
        <div className="mt-2 flex items-start gap-[7px] text-[11px] leading-[1.5] text-bad">
          <Info className="mt-0.5 h-3 w-3 flex-none" />
          <span>Without it: {spec.without}</span>
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* page                                                                */
/* ------------------------------------------------------------------ */

type DiscoveryRow = { platform: string; last_count: number; last_run_at: string | null };
export default function SettingsPage() {
  const [settings, setSettings] = useState<Record<string, string> | null>(null);
  const [userSettings, setUserSettings] = useState<Record<string, string>>({});
  const [discovery, setDiscovery] = useState<DiscoveryRow[] | null>(null);
  const [brandCount, setBrandCount] = useState<number | null>(null);
  const [revealed, setRevealed] = useState<Record<string, boolean>>({});

  const [text, setText] = useState<Record<string, string>>(TEXT_FALLBACK);
  const [video, setVideo] = useState<Record<string, string>>(VIDEO_FALLBACK);
  const [savingText, setSavingText] = useState(false);
  const [savingVideo, setSavingVideo] = useState(false);

  const loadSettings = useCallback(async () => {
    try {
      const cfg: Record<string, string> = await getSettings();
      setSettings(cfg);
      setText(Object.fromEntries(TEXT_KEYS.map((k) => [k, cfg[k] ?? TEXT_FALLBACK[k]])));
      setVideo(Object.fromEntries(VIDEO_KEYS.map((k) => [k, cfg[k] ?? VIDEO_FALLBACK[k]])));
    } catch (e) {
      toast.error(apiErrorMessage(e, "Could not read the settings"));
      setSettings({});
    }
  }, []);

  useEffect(() => {
    loadSettings();
    getUserSettings().then(setUserSettings).catch(() => {});
    getDiscoveryStatus()
      .then((d: { platforms: DiscoveryRow[] }) => setDiscovery(d.platforms ?? []))
      .catch(() => setDiscovery([]));
    getBrands().then((b: unknown[]) => setBrandCount(b.length)).catch(() => {});
  }, [loadSettings]);

  // A key saved in one row changes what the feature card says about it.
  useEffect(() => {
    const onChanged = () => loadSettings();
    window.addEventListener("settings:changed", onChanged);
    return () => window.removeEventListener("settings:changed", onChanged);
  }, [loadSettings]);

  const has = useCallback((k: string) => !!(settings?.[k] ?? "").trim(), [settings]);

  const features = useMemo(() => {
    const anthropic = has("anthropic_api_key");
    return [
      {
        name: "Reading slide text",
        on: anthropic,
        sub: !anthropic
          ? "Needs an Anthropic key — there is none"
          : has("google_vision_api_key")
            ? "Claude Vision, with Google Vision behind it"
            : "Claude Vision, with no fallback reader behind it",
      },
      {
        name: "Rewriting captions",
        on: anthropic,
        sub: anthropic
          ? "One caption per account, so the text differs"
          : "Needs an Anthropic key — there is none",
      },
      {
        name: "Making images with AI",
        on: has("openai_api_key"),
        sub: has("openai_api_key")
          ? "gpt-image-1, on the Variations step"
          : "Needs an OpenAI key — there is none",
      },
    ];
  }, [has]);

  const keysSet = KEYS.filter((k) => has(k.key)).length;
  const off = features.filter((f) => !f.on).length;

  // Truthy parse — both clipping toggles default ON when nothing is stored.
  const isOn = (key: string) => {
    const v = userSettings[key];
    if (v === undefined || v === null) return true;
    return !["0", "false", "False", ""].includes(v);
  };

  const toggle = async (key: string, v: boolean) => {
    const before = userSettings[key];
    setUserSettings((s) => ({ ...s, [key]: v ? "1" : "0" }));
    try {
      await updateUserSetting(key, v ? "1" : "0");
    } catch (e) {
      setUserSettings((s) => ({ ...s, [key]: before ?? "" }));
      toast.error(apiErrorMessage(e, "Could not save that"));
    }
  };

  const saveMany = async (
    entries: [string, string][],
    setBusy: (v: boolean) => void,
    what: string,
  ) => {
    setBusy(true);
    try {
      for (const [k, v] of entries) await updateSetting(k, v);
      toast.success(`${what} saved`);
      loadSettings();
    } catch (e) {
      toast.error(apiErrorMessage(e, `Could not save the ${what.toLowerCase()}`));
    } finally {
      setBusy(false);
    }
  };

  const textDirty = TEXT_KEYS.some((k) => (settings?.[k] ?? TEXT_FALLBACK[k]) !== text[k]);
  const videoDirty = VIDEO_KEYS.some((k) => (settings?.[k] ?? VIDEO_FALLBACK[k]) !== video[k]);
  const textStored = TEXT_KEYS.some((k) => settings?.[k] !== undefined);
  const videoStored = VIDEO_KEYS.some((k) => settings?.[k] !== undefined);

  // A slide renders 1080px wide; the preview box is 176. At true scale a
  // 52px hook would be 8px on screen and unreadable, so the specimen keeps
  // the ratio between the three and not the absolute size.
  const SPECIMEN = 0.29;
  const px = (k: string) => Math.max(6, (Number(text[k]) || Number(TEXT_FALLBACK[k])) * SPECIMEN);

  const seconds = Number(video.slide_duration) || 0;
  const allRevealed = KEYS.every((k) => !has(k.key) || revealed[k.key]);

  return (
    <>
      <PageHead>
        <PageTitle
          title="Settings"
          sub="The keys this app runs on, and the defaults every new post starts from."
        />
        <PageActions>
          <Chip href="/brands" icon={FileText}>
            Brands
            {brandCount !== null && <ChipCount>{brandCount}</ChipCount>}
          </Chip>
        </PageActions>
      </PageHead>

      <TwoCol
        main={
          // Both cards fill the row, so the pair ends level.
          <Card className="flex flex-1 flex-col">
            <CardHead
              title="What is switched on"
              sub="A missing key is not an empty box — it is a feature that fails quietly somewhere else"
              right={<DotsMenu items={[{ label: "Re-check the keys", icon: RefreshCw, onClick: loadSettings }]} />}
            />
            <CardBody className="flex flex-1 flex-col">
              {settings === null ? (
                <div className="flex flex-col gap-2">
                  <Skeleton className="h-[46px]" />
                  <Skeleton className="h-[46px]" />
                  <Skeleton className="h-[46px]" />
                </div>
              ) : (
                <>
                  <FigureLine value={String(keysSet)}>
                    of <FigureStrong>{KEYS.length}</FigureStrong> keys set ·{" "}
                    {off === 0
                      ? "every feature is on"
                      : `${WORDS[off]} feature${off > 1 ? "s are" : " is"} off`}
                  </FigureLine>
                  <div className="flex flex-col gap-2">
                    {features.map((f) => (
                      <FeatureRow key={f.name} {...f} />
                    ))}
                  </div>
                </>
              )}
              <div className="mt-3.5 flex items-start gap-1.5 text-[11px] leading-[1.5] text-subtle">
                <Info className="mt-0.5 h-3 w-3 flex-none" />
                <span>
                  These three keys switch features on across the whole app. Per-brand look and
                  posting times live on <b className="font-semibold text-muted-foreground">Brands</b>;
                  the platform sign-ins are set once for the whole workspace, by an admin.
                </span>
              </div>
            </CardBody>
          </Card>
        }
        rail={
          <Card className="flex flex-1 flex-col">
            <CardHead title="Set somewhere else" sub="Not everything belongs here" />
            <CardBody className="flex flex-1 flex-col gap-2 pt-2.5">
              <ElsewhereRow
                href="/brands"
                icon={FileText}
                title="Colour, timezone, posting times"
                sub="Per brand, on Brands"
              />
              <ElsewhereRow
                icon={Shield}
                title="Platform sign-ins, and the public address"
                sub="Set by an admin for the whole workspace, not here"
              />
            </CardBody>
          </Card>
        }
      />

      <Card>
        <CardHead
          title="Keys"
          sub="Each one switches on the feature named beside it"
          right={
            <DotsMenu
              items={[
                {
                  label: allRevealed ? "Hide every key" : "Reveal every key",
                  icon: Eye,
                  onClick: () =>
                    setRevealed(
                      allRevealed ? {} : Object.fromEntries(KEYS.map((k) => [k.key, true])),
                    ),
                },
              ]}
            />
          }
        />
        <CardBody className="pt-3">
          {settings === null ? (
            <Skeleton className="h-[240px]" />
          ) : (
            KEYS.map((spec, i) => (
              <KeyRow
                key={spec.key}
                spec={spec}
                saved={settings[spec.key] ?? ""}
                revealed={!!revealed[spec.key]}
                onReveal={(v) => setRevealed((r) => ({ ...r, [spec.key]: v }))}
                last={i === KEYS.length - 1}
              />
            ))
          )}
          <div className="mt-2 flex items-start gap-1.5 text-[11px] leading-[1.5] text-subtle">
            <Info className="mt-0.5 h-3 w-3 flex-none" />
            <span>
              Anthropic and OpenAI are stored against your account — another user sets their own.
              Google Vision is one key for the workspace. None of them is sent anywhere but the
              service it belongs to.
            </span>
          </div>
        </CardBody>
      </Card>

      <Card>
        <CardHead
          title="Clipping behaviour"
          sub="How the same clip is made to differ between accounts"
        />
        <CardBody className="flex flex-col gap-2.5 pt-3">
          <BigCheck
            checked={isOn("clip_diversification_enabled")}
            onChange={(v) => toggle("clip_diversification_enabled", v)}
            title="Re-encode each account's copy"
          >
            Imperceptible changes per account and platform, so the same clip does not arrive twice
            as the same file. Off, the raw clip is posted everywhere.
          </BigCheck>
          <BigCheck
            checked={isOn("clip_caption_variants_enabled")}
            onChange={(v) => toggle("clip_caption_variants_enabled", v)}
            title="Rewrite each account's caption"
          >
            Claude rewrites the caption per account and platform, cached so each pair is written
            once. Needs the Anthropic key above.
          </BigCheck>
        </CardBody>
      </Card>

      <TwoCol
        main={
          <Card className="flex flex-1 flex-col">
            <CardHead
              title="Text on the slides"
              sub="What a new post starts with — changing it does not touch a post already built"
              right={
                <DotsMenu
                  items={[
                    {
                      label: "Back to the built-in defaults",
                      icon: RefreshCw,
                      onClick: () => setText(TEXT_FALLBACK),
                    },
                  ]}
                />
              }
            />
            <CardBody className="flex flex-1 flex-col pt-3">
              <div className="grid flex-1 items-stretch gap-[18px] xl:grid-cols-[1fr_176px]">
                <div className="flex flex-col justify-between gap-2">
                  <SettingRow name="Hook" sub="The big line at the top">
                    <NumField
                      value={text.hook_font_size}
                      unit="px"
                      onChange={(v) => setText((t) => ({ ...t, hook_font_size: v }))}
                    />
                  </SettingRow>
                  <SettingRow name="Title" sub="Slides without one just skip it">
                    <NumField
                      value={text.title_font_size}
                      unit="px"
                      onChange={(v) => setText((t) => ({ ...t, title_font_size: v }))}
                    />
                  </SettingRow>
                  <SettingRow name="Body" sub="Everything under the hook">
                    <NumField
                      value={text.body_font_size}
                      unit="px"
                      onChange={(v) => setText((t) => ({ ...t, body_font_size: v }))}
                    />
                  </SettingRow>
                  <SettingRow name="Colour" sub="One colour for all three blocks">
                    <span className="relative flex w-[122px] flex-none items-center">
                      <label
                        className="absolute left-[9px] h-[13px] w-[13px] cursor-pointer rounded-[4px] border border-border"
                        style={{ background: text.text_color }}
                      >
                        <input
                          type="color"
                          value={/^#[0-9a-f]{6}$/i.test(text.text_color) ? text.text_color : "#FFFFFF"}
                          onChange={(e) => setText((t) => ({ ...t, text_color: e.target.value.toUpperCase() }))}
                          className="absolute inset-0 cursor-pointer opacity-0"
                        />
                      </label>
                      <Input
                        value={text.text_color}
                        onChange={(e) => setText((t) => ({ ...t, text_color: e.target.value }))}
                        className="pl-[29px] font-mono text-xs"
                      />
                    </span>
                  </SettingRow>
                </div>

                <div className="flex flex-col">
                  <div className="mb-[7px] text-[10.5px] font-bold uppercase leading-normal tracking-[0.09em] text-subtle">
                    How it reads
                  </div>
                  <div
                    className="mt-auto flex aspect-[3/4] w-full max-w-[200px] flex-col items-center justify-center gap-[9px] rounded-[12px] border border-border bg-[#2c3138] p-3.5 text-center"
                    style={{ color: text.text_color }}
                  >
                    <span
                      className="font-extrabold leading-[1.25] [text-shadow:0_1px_3px_rgba(0,0,0,.6)]"
                      style={{ fontSize: px("hook_font_size") }}
                    >
                      Hygiene products I wish I knew sooner
                    </span>
                    <span
                      className="font-bold leading-[1.3] [text-shadow:0_1px_3px_rgba(0,0,0,.6)]"
                      style={{ fontSize: px("title_font_size") }}
                    >
                      Tongue scraper
                    </span>
                    <span
                      className="font-semibold leading-[1.35] opacity-[0.92] [text-shadow:0_1px_3px_rgba(0,0,0,.6)]"
                      style={{ fontSize: px("body_font_size") }}
                    >
                      Two seconds, every morning
                    </span>
                  </div>
                </div>
              </div>

              <CardFoot
                note={
                  textStored
                    ? "A number scales its role on every slide shape, so the smaller title on a call-to-action slide moves with this one. A post already built keeps its slides until it is rebuilt."
                    : "Nothing is stored here yet, so these are the sizes the renderer already uses. A number scales its role on every slide shape, and a post already built keeps its slides until it is rebuilt."
                }
              >
                <PrimaryButton
                  icon={Check}
                  disabled={savingText || (textStored && !textDirty)}
                  onClick={() =>
                    saveMany(
                      TEXT_KEYS.map((k) => [k, text[k]] as [string, string]),
                      setSavingText,
                      "Text defaults",
                    )
                  }
                >
                  Save the text defaults
                </PrimaryButton>
              </CardFoot>
            </CardBody>
          </Card>
        }
        rail={
          <Card className="flex flex-1 flex-col">
            <CardHead title="Video" sub="For the 9:16 renders" />
            <CardBody className="flex flex-1 flex-col pt-3">
              <div className="flex flex-col gap-2">
                <SettingRow name="Seconds per slide" sub="How long each one holds">
                  <NumField
                    value={video.slide_duration}
                    unit="s"
                    onChange={(v) => setVideo((s) => ({ ...s, slide_duration: v }))}
                  />
                </SettingRow>
                <SettingRow name="Crossfade" sub="The fade between two slides">
                  <NumField
                    value={video.transition_duration}
                    unit="s"
                    onChange={(v) => setVideo((s) => ({ ...s, transition_duration: v }))}
                  />
                </SettingRow>
                <SettingRow name="Frames per second" sub="30 is right for every platform">
                  <NumField
                    value={video.fps}
                    unit="fps"
                    onChange={(v) => setVideo((s) => ({ ...s, fps: v }))}
                  />
                </SettingRow>
              </div>
              <CardFoot
                note={
                  <>
                    {seconds > 0
                      ? `Seven slides at ${video.slide_duration}s is a ${Math.round(seconds * 7)} second video. `
                      : ""}
                    A platform render still shortens the dwell when the total would overrun that
                    platform&rsquo;s cap — 60s for Shorts, 90s for Reels. TikTok gets a photo set
                    rather than a video, so none of this reaches it.
                  </>
                }
              >
                <PrimaryButton
                  icon={Check}
                  disabled={savingVideo || (videoStored && !videoDirty)}
                  onClick={() =>
                    saveMany(
                      VIDEO_KEYS.map((k) => [k, video[k]] as [string, string]),
                      setSavingVideo,
                      "Video defaults",
                    )
                  }
                >
                  Save the video defaults
                </PrimaryButton>
              </CardFoot>
            </CardBody>
          </Card>
        }
      />

      <Card>
        <CardHead
          title="Post discovery"
          sub="Finds videos posted from your phone and adds them for view tracking — part of Clipping, not a setting"
          right={
            <DotsMenu
              items={[
                {
                  label: "Check again",
                  icon: RefreshCw,
                  onClick: () =>
                    getDiscoveryStatus()
                      .then((d: { platforms: DiscoveryRow[] }) => setDiscovery(d.platforms ?? []))
                      .catch(() => {}),
                },
                { label: "Open Clipping", icon: ExternalLink, href: "/clipping" },
              ]}
            />
          }
        />
        <CardBody className="pt-3.5">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {DISCOVERY.map(({ key, label }) => {
              const row = discovery?.find((p) => p.platform === key);
              return (
                <Ring
                  key={key}
                  label={label}
                  count={row?.last_count ?? 0}
                  lastRun={row?.last_run_at ?? null}
                />
              );
            })}
          </div>
          <div className="mt-3.5 flex items-start gap-1.5 text-[11px] leading-[1.5] text-subtle">
            <Info className="mt-0.5 h-3 w-3 flex-none" />
            <span>
              {discovery?.some((p) => p.last_run_at)
                ? "Each ring is what that platform's last run found, and when it ran."
                : "It has never run on this workspace, so there is nothing to show yet. A run fills in what it found and when."}
            </span>
          </div>
        </CardBody>
      </Card>

      <Note>Every value on this page is read from your database.</Note>
    </>
  );
}
