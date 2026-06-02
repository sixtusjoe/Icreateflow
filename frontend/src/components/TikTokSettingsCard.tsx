"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";
import {
  ChevronDown,
  ChevronRight,
  AlertCircle,
  ExternalLink,
  Save,
  Loader2,
} from "lucide-react";
import {
  getTiktokCreatorInfo,
  type TikTokCreatorInfo,
  type TikTokSettingsPatch,
} from "@/lib/api";

/**
 * TikTokSettingsCard
 *
 * Shared between the Brand `/posts/new` Generate tab (per-(post, variation)
 * settings on the `outputs` row) and the Clipping `VariationExtras`
 * (per-variation settings on the `artist_accounts` row).
 *
 * The component encodes every required UX rule from
 * developers.tiktok.com/doc/content-sharing-guidelines:
 *
 *   - creator_info is fetched lazily on first expand (server caches 5 min).
 *   - Display the creator nickname so the user knows which TikTok account.
 *   - Block submission with an amber notice if creator_info reports the
 *     creator can't post right now.
 *   - Privacy dropdown options come from creator_info.privacy_level_options.
 *     NO default value — placeholder is "Select privacy"; user must pick.
 *   - Allow Comment / Duet / Stitch checkboxes default unchecked. Each
 *     is disabled+greyed when creator_info reports the creator has that
 *     interaction off at the account level.
 *   - "Disclose video content" master toggle defaults OFF. When ON,
 *     "Your Brand" + "Branded Content" appear; at least one must be
 *     ticked or Save is disabled with a hover tooltip.
 *   - Branded Content checked → SELF_ONLY removed from the privacy
 *     dropdown options (TikTok rejects this combo). Privacy is also
 *     cleared if branded is toggled on while SELF_ONLY was selected.
 *   - Selection prompt below sub-options shows the label hint
 *     ('Promotional content' / 'Paid partnership').
 *   - Music Usage Confirmation declaration above Save (auto-extends to
 *     "and Branded Content Policy" when Branded Content is on).
 *   - Save calls the parent-provided onSave; parent handles which
 *     endpoint (outputs vs variations).
 *   - Reports validity to parent via onValidityChange so Post Now /
 *     Save Schedule can be disabled when any card is misconfigured.
 *
 * The component is uncontrolled — initial values are read from
 * `initialValues` once, then held in local state until the user clicks Save.
 */

const PRIVACY_LABELS: Record<string, string> = {
  PUBLIC_TO_EVERYONE: "Public — Everyone",
  MUTUAL_FOLLOW_FRIENDS: "Friends — Mutual follows",
  FOLLOWER_OF_CREATOR: "Followers",
  SELF_ONLY: "Private — Only me",
};

export type TikTokSettingsValues = {
  tiktok_post_as_draft?: boolean | null;
  tiktok_privacy_level?: string | null;
  tiktok_disclosure_enabled?: boolean | null;
  tiktok_disclose_your_brand?: boolean | null;
  tiktok_disclose_branded_content?: boolean | null;
  tiktok_allow_comment?: boolean | null;
  tiktok_allow_duet?: boolean | null;
  tiktok_allow_stitch?: boolean | null;
  tiktok_consent_at?: string | null;
  tiktok_title?: string | null;
};

export function TikTokSettingsCard({
  entityId,
  entityLabel,
  creatorInfoAccountId,
  creatorInfoKind,
  initialValues,
  onSave,
  onValidityChange,
  defaultOpen = false,
  mediaType = "video",
}: {
  /** Stable id for the card; used as key in onValidityChange. */
  entityId: number;
  /** Header label, e.g. "Vibesofmoon" or "Account: Moonisgod". */
  entityLabel: string;
  /** Account id passed to GET /api/oauth/tiktok/creator-info. */
  creatorInfoAccountId: number;
  /** Whether the creator_info call queries Brand `accounts` or Clipping
   *  `artist_accounts`. */
  creatorInfoKind: "brand_account" | "variation";
  /** Per TikTok's required UX: photo posts cannot be Duet'd or Stitched,
   *  so those toggles must NOT appear at all on photo flows. Brand TikTok
   *  always posts as a slideshow (photo); Clipping posts videos.
   *  Defaults to "video" for back-compat with the original Clipping
   *  callsite.
   */
  mediaType?: "video" | "photo";
  /** Initial state from the row (null for unset). */
  initialValues: TikTokSettingsValues;
  /** Save handler — parent decides which endpoint to call. */
  onSave: (payload: TikTokSettingsPatch) => Promise<void>;
  /** Reports validity up so the parent can disable Post Now / Save Schedule. */
  onValidityChange: (entityId: number, valid: boolean) => void;
  /** Optional: open the panel by default (Clipping uses true so the
   *  variation card surfaces "needs setup" without a click). */
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const [info, setInfo] = useState<TikTokCreatorInfo | null>(null);
  const [infoLoading, setInfoLoading] = useState(false);
  const [infoError, setInfoError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const [postAsDraft, setPostAsDraft] = useState(!!initialValues.tiktok_post_as_draft);
  const [privacy, setPrivacy] = useState<string>(initialValues.tiktok_privacy_level || "");
  const [discloseOn, setDiscloseOn] = useState(!!initialValues.tiktok_disclosure_enabled);
  const [yourBrand, setYourBrand] = useState(!!initialValues.tiktok_disclose_your_brand);
  const [brandedContent, setBrandedContent] = useState(!!initialValues.tiktok_disclose_branded_content);
  const [allowComment, setAllowComment] = useState(!!initialValues.tiktok_allow_comment);
  const [allowDuet, setAllowDuet] = useState(!!initialValues.tiktok_allow_duet);
  const [allowStitch, setAllowStitch] = useState(!!initialValues.tiktok_allow_stitch);
  const [tiktokTitle, setTiktokTitle] = useState<string>(initialValues.tiktok_title || "");
  const [lastSavedAt, setLastSavedAt] = useState<string | null>(initialValues.tiktok_consent_at || null);

  // Snapshot of values at the last successful Save (or initial mount).
  // The reported validity is anchored to this snapshot, NOT the live
  // form state — so Post Now stays disabled until the user clicks Save,
  // even if the form has typed in valid values. Re-locks on any edit.
  const [savedSnapshot, setSavedSnapshot] = useState({
    postAsDraft: !!initialValues.tiktok_post_as_draft,
    privacy: initialValues.tiktok_privacy_level || "",
    discloseOn: !!initialValues.tiktok_disclosure_enabled,
    yourBrand: !!initialValues.tiktok_disclose_your_brand,
    brandedContent: !!initialValues.tiktok_disclose_branded_content,
    allowComment: !!initialValues.tiktok_allow_comment,
    allowDuet: !!initialValues.tiktok_allow_duet,
    allowStitch: !!initialValues.tiktok_allow_stitch,
    consentAt: initialValues.tiktok_consent_at || null,
  });

  useEffect(() => {
    if (!open || info || infoLoading || infoError) return;
    setInfoLoading(true);
    getTiktokCreatorInfo(creatorInfoAccountId, creatorInfoKind)
      .then((d) => {
        if (d?.creator_blocked) {
          setInfoError(d.detail || "TikTok creator can't post right now");
        } else {
          setInfo(d);
        }
      })
      .catch((e) => setInfoError(e?.response?.data?.detail || "Failed to load TikTok creator info"))
      .finally(() => setInfoLoading(false));
  }, [open, info, infoLoading, infoError, creatorInfoAccountId, creatorInfoKind]);

  useEffect(() => {
    if (brandedContent && privacy === "SELF_ONLY") setPrivacy("");
  }, [brandedContent, privacy]);

  useEffect(() => {
    if (!discloseOn) {
      setYourBrand(false);
      setBrandedContent(false);
    }
  }, [discloseOn]);

  // Form-level validity: does the CURRENT in-form state pass TikTok's UX
  // rules? Used to enable/disable the Save button itself.
  const formValid = (() => {
    if (postAsDraft) return true;
    if (!privacy) return false;
    if (discloseOn && !yourBrand && !brandedContent) return false;
    if (brandedContent && privacy === "SELF_ONLY") return false;
    return true;
  })();

  // Has the user edited anything since the last successful Save? While
  // dirty, Post Now stays locked even if the form is "valid" — TikTok
  // requires consent be captured at the moment of Save (the consent_at
  // stamp is the music-usage acknowledgement).
  const dirty = (
    postAsDraft     !== savedSnapshot.postAsDraft     ||
    privacy         !== savedSnapshot.privacy         ||
    discloseOn      !== savedSnapshot.discloseOn      ||
    yourBrand       !== savedSnapshot.yourBrand       ||
    brandedContent  !== savedSnapshot.brandedContent  ||
    allowComment    !== savedSnapshot.allowComment    ||
    allowDuet       !== savedSnapshot.allowDuet       ||
    allowStitch     !== savedSnapshot.allowStitch
  );

  // Persisted-validity: does the LAST SAVED state pass the rules? This
  // is the value parents (Brand /posts/new) gate Post Now / Save Schedule
  // on. We treat "saved" as "consent_at set on the snapshot."
  const persistedValid = (() => {
    if (!savedSnapshot.consentAt) return false;
    if (savedSnapshot.postAsDraft) return true;
    if (!savedSnapshot.privacy) return false;
    if (savedSnapshot.discloseOn && !savedSnapshot.yourBrand && !savedSnapshot.brandedContent) return false;
    if (savedSnapshot.brandedContent && savedSnapshot.privacy === "SELF_ONLY") return false;
    return true;
  })();

  // What we report up: only valid when the saved row is valid AND the
  // user hasn't dirtied it since.
  const reportedValid = persistedValid && !dirty;
  useEffect(() => {
    onValidityChange(entityId, reportedValid);
  }, [reportedValid, entityId, onValidityChange]);

  const privacyOptions = (info?.privacy_level_options || []).filter((opt) => {
    if (brandedContent && opt === "SELF_ONLY") return false;
    return true;
  });

  const declaration = (() => {
    if (postAsDraft) return null;
    if (!discloseOn) return "By posting, you agree to TikTok's Music Usage Confirmation.";
    if (brandedContent) return "By posting, you agree to TikTok's Branded Content Policy and Music Usage Confirmation.";
    return "By posting, you agree to TikTok's Music Usage Confirmation.";
  })();

  const labelHint = (() => {
    if (!discloseOn) return null;
    if (brandedContent) return "Your photo/video will be labeled as 'Paid partnership'";
    if (yourBrand) return "Your photo/video will be labeled as 'Promotional content'";
    return null;
  })();

  const validationMsg = (() => {
    if (postAsDraft) return null;
    if (!privacy) return "Pick a privacy level (or enable Post as draft).";
    if (discloseOn && !yourBrand && !brandedContent) {
      return "You need to indicate if your content promotes yourself, a third party, or both.";
    }
    if (brandedContent && privacy === "SELF_ONLY") {
      return "Branded content visibility cannot be set to private.";
    }
    return null;
  })();

  const onSaveClick = async () => {
    setSaving(true);
    try {
      const payload: TikTokSettingsPatch = {
        tiktok_post_as_draft: postAsDraft,
        tiktok_privacy_level: postAsDraft ? (null as unknown as string) : privacy,
        tiktok_disclosure_enabled: discloseOn,
        tiktok_disclose_your_brand: discloseOn ? yourBrand : false,
        tiktok_disclose_branded_content: discloseOn ? brandedContent : false,
        tiktok_allow_comment: allowComment,
        // Photo posts can't be Duet'd or Stitched. Don't send anything
        // that implies the user opted into them.
        tiktok_allow_duet:   mediaType === "video" ? allowDuet   : false,
        tiktok_allow_stitch: mediaType === "video" ? allowStitch : false,
        tiktok_title: tiktokTitle.trim() || undefined,
      };
      await onSave(payload);
      const stampIso = new Date().toISOString();
      setLastSavedAt(stampIso);
      // Re-anchor the persisted snapshot so dirty=false and reportedValid
      // re-evaluates against what's now in the DB. Post Now unlocks here.
      setSavedSnapshot({
        postAsDraft,
        privacy: postAsDraft ? "" : privacy,
        discloseOn,
        yourBrand: discloseOn ? yourBrand : false,
        brandedContent: discloseOn ? brandedContent : false,
        allowComment,
        allowDuet:   mediaType === "video" ? allowDuet   : false,
        allowStitch: mediaType === "video" ? allowStitch : false,
        consentAt: stampIso,
      });
      toast.success(`TikTok settings saved for ${entityLabel}`);
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(detail || "Failed to save TikTok settings");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="rounded-xl border border-border bg-muted/30 p-3">
      <button
        onClick={() => setOpen((s) => !s)}
        className="flex w-full items-center justify-between gap-2 text-sm font-medium hover:opacity-80"
        aria-expanded={open}
      >
        <span className="flex items-center gap-2">
          {open ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
          TikTok posting settings — {entityLabel}
        </span>
        {!reportedValid && (
          <span className="inline-flex items-center gap-1 rounded-full bg-amber-500/15 px-2 py-0.5 text-xs text-amber-700 dark:text-amber-400">
            <AlertCircle className="h-3 w-3" />
            {dirty ? "unsaved changes" : "needs setup"}
          </span>
        )}
      </button>

      {open && (
        <div className="mt-3 space-y-4">
          {infoLoading && (
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <Loader2 className="h-3 w-3 animate-spin" /> Loading TikTok account info…
            </div>
          )}
          {infoError && (
            <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-700 dark:text-amber-400">
              <AlertCircle className="mr-1 inline h-3 w-3" /> {infoError}
            </div>
          )}
          {info && !infoError && (
            <p className="text-xs text-muted-foreground">
              Posting as <span className="font-medium text-foreground">@{info.creator_nickname || info.creator_username || "(no nickname)"}</span>
              {info.max_video_post_duration_sec ? <> · max {info.max_video_post_duration_sec}s per video</> : null}
            </p>
          )}

          {/* Title — TikTok UX guideline Point 2a: editable title field.
              font-size ≥ 16px prevents iOS Safari from auto-zooming on focus. */}
          <div>
            <label className="mb-1 block text-xs font-medium">Title</label>
            <textarea
              value={tiktokTitle}
              onChange={(e) => setTiktokTitle(e.target.value)}
              placeholder="Add a title for this TikTok post…"
              rows={2}
              style={{ fontSize: "16px" }}
              className="w-full resize-none rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-foreground/30"
            />
          </div>

          <label className="flex items-start gap-2 text-sm">
            <input
              type="checkbox"
              checked={postAsDraft}
              onChange={(e) => setPostAsDraft(e.target.checked)}
              className="mt-0.5 h-4 w-4 accent-foreground"
            />
            <span>
              <span className="font-medium">Post as draft</span>
              <span className="block text-xs text-muted-foreground">
                Sends to your TikTok inbox. You'll edit privacy, captions, and disclosure inside the TikTok app before publishing.
              </span>
            </span>
          </label>

          {!postAsDraft && info && !infoError && (
            <div className="space-y-4 border-t border-border/50 pt-3">
              <div>
                <label className="mb-1 block text-xs font-medium">Who can view this post</label>
                <select
                  value={privacy}
                  onChange={(e) => setPrivacy(e.target.value)}
                  className="min-h-[40px] w-full rounded-lg border border-border bg-background px-3 text-base sm:text-sm"
                >
                  <option value="">Select privacy</option>
                  {privacyOptions.map((opt) => (
                    <option key={opt} value={opt}>{PRIVACY_LABELS[opt] || opt}</option>
                  ))}
                </select>
                {brandedContent && info.privacy_level_options.includes("SELF_ONLY") && (
                  <p className="mt-1 text-[11px] text-muted-foreground">
                    Branded content visibility cannot be set to private.
                  </p>
                )}
              </div>

              <div>
                <label className="mb-1 block text-xs font-medium">Allow users to</label>
                <div className="flex flex-wrap gap-3">
                  <Toggle label="Comment" checked={allowComment} disabled={!!info.comment_disabled} onChange={setAllowComment} />
                  {/* Duet/Stitch: shown for all post types but disabled for photo posts.
                      TikTok's UX guideline requires all three to be visible; photo posts
                      cannot use Duet/Stitch so they render grayed out. */}
                  <Toggle
                    label="Duet"
                    checked={allowDuet}
                    disabled={!!info.duet_disabled || mediaType !== "video"}
                    disabledReason={mediaType !== "video" ? "Not available for photo posts" : undefined}
                    onChange={setAllowDuet}
                  />
                  <Toggle
                    label="Stitch"
                    checked={allowStitch}
                    disabled={!!info.stitch_disabled || mediaType !== "video"}
                    disabledReason={mediaType !== "video" ? "Not available for photo posts" : undefined}
                    onChange={setAllowStitch}
                  />
                </div>
              </div>

              <div>
                <label className="flex items-start gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={discloseOn}
                    onChange={(e) => setDiscloseOn(e.target.checked)}
                    className="mt-0.5 h-4 w-4 accent-foreground"
                  />
                  <span>
                    <span className="font-medium">Disclose video content</span>
                    <span className="block text-xs text-muted-foreground">
                      Turn on if this video promotes goods or services in exchange for value. Promotes yourself, a third party, or both.
                    </span>
                  </span>
                </label>

                {discloseOn && (
                  <div className="mt-2 space-y-2 rounded-lg border border-border/50 bg-background/50 px-3 py-2">
                    <label className="flex items-start gap-2 text-sm">
                      <input
                        type="checkbox"
                        checked={yourBrand}
                        onChange={(e) => setYourBrand(e.target.checked)}
                        className="mt-0.5 h-4 w-4 accent-foreground"
                      />
                      <span>
                        <span className="font-medium">Your Brand</span>
                        <span className="block text-[11px] text-muted-foreground">Promoting yourself or your own business.</span>
                      </span>
                    </label>
                    <label className="flex items-start gap-2 text-sm">
                      <input
                        type="checkbox"
                        checked={brandedContent}
                        onChange={(e) => setBrandedContent(e.target.checked)}
                        className="mt-0.5 h-4 w-4 accent-foreground"
                      />
                      <span>
                        <span className="font-medium">Branded Content</span>
                        <span className="block text-[11px] text-muted-foreground">
                          Promoting another brand or third party.{" "}
                          <a href="https://www.tiktok.com/legal/page/global/bc-policy/en" target="_blank" rel="noopener noreferrer"
                             className="underline hover:text-foreground">
                            Branded Content Policy <ExternalLink className="inline h-2.5 w-2.5" />
                          </a>
                        </span>
                      </span>
                    </label>
                    {labelHint && (
                      <p className="rounded-md bg-muted/60 px-2 py-1.5 text-[11px] text-muted-foreground">
                        {labelHint}
                      </p>
                    )}
                  </div>
                )}
              </div>
            </div>
          )}

          {validationMsg && (
            <p className="text-[11px] text-amber-700 dark:text-amber-400">
              <AlertCircle className="mr-1 inline h-3 w-3" /> {validationMsg}
            </p>
          )}

          {declaration && (
            <p className="text-[11px] text-muted-foreground">
              {declaration.split(/(Music Usage Confirmation|Branded Content Policy)/g).map((seg, i) => {
                if (seg === "Music Usage Confirmation") return (
                  <a key={i} href="https://www.tiktok.com/legal/page/global/music-usage-confirmation/en"
                     target="_blank" rel="noopener noreferrer"
                     className="underline hover:text-foreground">{seg}</a>
                );
                if (seg === "Branded Content Policy") return (
                  <a key={i} href="https://www.tiktok.com/legal/page/global/bc-policy/en"
                     target="_blank" rel="noopener noreferrer"
                     className="underline hover:text-foreground">{seg}</a>
                );
                return <span key={i}>{seg}</span>;
              })}
            </p>
          )}

          <button
            onClick={onSaveClick}
            disabled={!formValid || saving || infoLoading}
            className="inline-flex min-h-[36px] items-center gap-2 rounded-lg bg-foreground px-4 py-2 text-sm font-medium text-background disabled:opacity-50"
          >
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
            Save TikTok settings
          </button>
          {dirty && persistedValid && (
            <p className="text-[11px] text-amber-700 dark:text-amber-400">
              Unsaved changes — Post Now stays disabled until you click Save.
            </p>
          )}
          {lastSavedAt && (
            <p className="text-[10px] text-muted-foreground">
              Last saved {new Date(lastSavedAt).toLocaleString()}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

function Toggle({
  label, checked, disabled, onChange, disabledReason,
}: {
  label: string;
  checked: boolean;
  disabled?: boolean;
  onChange: (b: boolean) => void;
  disabledReason?: string;
}) {
  return (
    <label
      title={disabled && disabledReason ? disabledReason : undefined}
      className={`flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-xs ${disabled ? "cursor-not-allowed opacity-50" : "cursor-pointer hover:bg-muted/40"}`}
    >
      <input
        type="checkbox"
        checked={checked && !disabled}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
        className="h-3.5 w-3.5 accent-foreground"
      />
      {label}
      {disabled && (
        <span className="ml-1 text-[10px] text-muted-foreground">
          ({disabledReason ?? "off in TikTok"})
        </span>
      )}
    </label>
  );
}
