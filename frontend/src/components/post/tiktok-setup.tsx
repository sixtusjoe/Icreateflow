"use client";

/** TikTok's posting settings, per account, per post.
 *
 *  Every rule here is TikTok's, from their content-sharing guidelines, and
 *  the app is held to all of them:
 *
 *    - no default privacy: it must be chosen, every time, per post.
 *    - draft vs live is a mode, not a checkbox — picking the inbox makes
 *      every other field irrelevant, so they go away.
 *    - a disclosure needs at least one of "your brand" / "branded content".
 *    - branded content cannot be private, so SELF_ONLY disappears AND the
 *      value clears if it was already chosen.
 *    - photo posts cannot be Duet'd or Stitched; the toggles stay visible
 *      but disabled, because hiding them makes the set look shorter.
 *    - consent is captured at the moment of Save, so Post Now stays locked
 *      until saved and re-locks the moment anything is touched.
 */

import { useEffect, useMemo, useState } from "react";
import { AlertCircle, Check, ChevronDown, FileText, Loader2, Send } from "lucide-react";
import {
  ensureOutput,
  getTiktokCreatorInfo,
  updateOutputTiktokSettings,
  type TikTokCreatorInfo,
  type TikTokSettingsPatch,
} from "@/lib/api";
import { PlatformIcon, PrimaryButton, Tag } from "@/components/kit";
import { Checkbox, Hint, Textarea } from "@/components/kit/dialog";
import { apiErrorMessage } from "@/components/kit/format";
import { toast } from "sonner";

const PRIVACY_LABEL: Record<string, string> = {
  PUBLIC_TO_EVERYONE: "Everyone",
  FOLLOWER_OF_CREATOR: "Followers",
  MUTUAL_FOLLOW_FRIENDS: "Friends — people you both follow",
  SELF_ONLY: "Only me",
};
const SELF = "SELF_ONLY";

export type OutputRow = Record<string, unknown> & { id: number; account_id: number };

export function TikTokSetupCard({
  output,
  postId,
  accountId,
  accountName,
  handle,
  connected,
  onValidity,
}: {
  /** Null until the post has been built — the settings are still chosen
   *  now, and the row is created on the first save. */
  output: OutputRow | null;
  postId: number;
  accountId: number;
  accountName: string;
  handle?: string | null;
  /** A handle names the account; a token is what lets us post to it. The
   *  settings are worth saving either way, but the card says which it is. */
  connected?: boolean;
  onValidity: (key: string, valid: boolean) => void;
}) {
  const validityKey = `acct:${accountId}`;
  const [outputId, setOutputId] = useState<number | null>(output?.id ?? null);
  const [open, setOpen] = useState(true);
  const [info, setInfo] = useState<TikTokCreatorInfo | null>(null);
  const [infoError, setInfoError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  const [draft, setDraft] = useState(!!output?.tiktok_post_as_draft);
  const [privacy, setPrivacy] = useState((output?.tiktok_privacy_level as string) || "");
  const [disclose, setDisclose] = useState(!!output?.tiktok_disclosure_enabled);
  const [ownBrand, setOwnBrand] = useState(!!output?.tiktok_disclose_your_brand);
  const [branded, setBranded] = useState(!!output?.tiktok_disclose_branded_content);
  const [comment, setComment] = useState(!!output?.tiktok_allow_comment);
  const [title, setTitle] = useState((output?.tiktok_title as string) || "");
  const [savedAt, setSavedAt] = useState<string | null>((output?.tiktok_consent_at as string) || null);

  /** The state at the last successful save. Validity is anchored here, not
   *  to what is on screen — typing valid values is not consent. */
  const [snapshot, setSnapshot] = useState({
    draft: !!output?.tiktok_post_as_draft,
    privacy: (output?.tiktok_privacy_level as string) || "",
    disclose: !!output?.tiktok_disclosure_enabled,
    ownBrand: !!output?.tiktok_disclose_your_brand,
    branded: !!output?.tiktok_disclose_branded_content,
    comment: !!output?.tiktok_allow_comment,
    consent: (output?.tiktok_consent_at as string) || null,
  });

  // Only an account that is actually signed in has creator info to fetch.
  // Asking for one that is not connected returns an error that says
  // nothing the card does not already know.
  useEffect(() => {
    if (!open || !connected || info || loading || infoError) return;
    setLoading(true);
    getTiktokCreatorInfo(accountId, "brand_account")
      .then((d) => (d?.creator_blocked ? setInfoError(d.detail || "This TikTok account cannot post right now") : setInfo(d)))
      .catch((e) => setInfoError(apiErrorMessage(e, "Could not reach TikTok for this account")))
      .finally(() => setLoading(false));
  }, [open, connected, info, loading, infoError, accountId]);

  // Branded content and "Only me" cannot both stand.
  useEffect(() => {
    if (branded && privacy === SELF) setPrivacy("");
  }, [branded, privacy]);
  useEffect(() => {
    if (!disclose) {
      setOwnBrand(false);
      setBranded(false);
    }
  }, [disclose]);

  const problem = useMemo(() => {
    if (draft) return null;
    if (!privacy) return "Pick who can see it.";
    if (disclose && !ownBrand && !branded)
      return "Say whether the post promotes your own brand, someone else's, or both.";
    if (branded && privacy === SELF) return "Branded content cannot be set to Only me.";
    return null;
  }, [draft, privacy, disclose, ownBrand, branded]);

  const dirty =
    draft !== snapshot.draft ||
    privacy !== snapshot.privacy ||
    disclose !== snapshot.disclose ||
    ownBrand !== snapshot.ownBrand ||
    branded !== snapshot.branded ||
    comment !== snapshot.comment;

  const persistedValid = useMemo(() => {
    if (!snapshot.consent) return false;
    if (snapshot.draft) return true;
    if (!snapshot.privacy) return false;
    if (snapshot.disclose && !snapshot.ownBrand && !snapshot.branded) return false;
    if (snapshot.branded && snapshot.privacy === SELF) return false;
    return true;
  }, [snapshot]);

  const ready = persistedValid && !dirty;
  useEffect(() => {
    onValidity(validityKey, ready);
  }, [ready, validityKey, onValidity]);

  const ALL_LEVELS = ["PUBLIC_TO_EVERYONE", "FOLLOWER_OF_CREATOR", "MUTUAL_FOLLOW_FRIENDS", SELF];
  // TikTok's own list narrows this per account — until we have it, offer
  // the full set rather than an empty select the operator cannot use.
  const options = (info?.privacy_level_options?.length ? info.privacy_level_options : ALL_LEVELS).filter(
    (o) => !(branded && o === SELF),
  );

  const save = async () => {
    setSaving(true);
    try {
      const patch: TikTokSettingsPatch = {
        tiktok_post_as_draft: draft,
        tiktok_privacy_level: draft ? (null as unknown as string) : privacy,
        tiktok_disclosure_enabled: disclose,
        tiktok_disclose_your_brand: disclose ? ownBrand : false,
        tiktok_disclose_branded_content: disclose ? branded : false,
        tiktok_allow_comment: comment,
        // A photo post cannot be Duet'd or Stitched, so never imply consent.
        tiktok_allow_duet: false,
        tiktok_allow_stitch: false,
        tiktok_title: title.trim() || undefined,
      };
      // The row may not exist yet — the build is what usually makes it.
      let id = outputId;
      if (id === null) {
        const row = await ensureOutput(postId, accountId);
        id = row.id as number;
        setOutputId(id);
      }
      await updateOutputTiktokSettings(id, patch);
      const stamp = new Date().toISOString();
      setSavedAt(stamp);
      setSnapshot({
        draft,
        privacy: draft ? "" : privacy,
        disclose,
        ownBrand: disclose ? ownBrand : false,
        branded: disclose ? branded : false,
        comment,
        consent: stamp,
      });
      toast.success(`TikTok settings saved for ${accountName}`);
    } catch (e) {
      toast.error(apiErrorMessage(e, "Could not save the TikTok settings"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="overflow-hidden rounded-[16px] border border-border bg-card">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full items-center gap-2.5 px-[15px] py-[13px] text-left transition-colors hover:bg-secondary"
      >
        <span className="grid h-[31px] w-[31px] flex-none place-items-center rounded-[10px] border border-border bg-secondary text-foreground">
          <PlatformIcon platform="tiktok" className="h-[15px] w-[15px]" />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block text-[13px] font-semibold leading-normal">{accountName}</span>
          <span className="block truncate text-[11px] leading-normal text-subtle">
            {`Posting as @${info?.creator_nickname || info?.creator_username || handle || accountName} · photo post`}
          </span>
        </span>
        <Tag tone={ready ? "live" : "skip"}>{ready ? "Saved and ready" : savedAt ? "Unsaved changes" : "Not saved yet"}</Tag>
        <ChevronDown
          className={`h-[15px] w-[15px] flex-none text-subtle transition-transform ${open ? "" : "-rotate-180"}`}
        />
      </button>

      {open && (
        <div className="border-t border-line-2 px-[15px] pb-[15px] pt-1">
          {loading && (
            <p className="mt-3.5 flex items-center gap-2 text-[11.5px] text-subtle">
              <Loader2 className="h-3 w-3 animate-spin" /> Asking TikTok about this account…
            </p>
          )}
          {connected === false && (
            <p className="mt-3.5 rounded-[11px] bg-[rgba(235,104,52,0.1)] px-3 py-2.5 text-[11.5px] leading-[1.5] text-[#B25E09] dark:text-[#F2A25C]">
              <AlertCircle className="mr-1.5 inline h-3 w-3" />
              TikTok is not connected for {accountName}, so nothing can go out there yet. These settings still save, and
              apply the moment it is connected.
            </p>
          )}
          {infoError && (
            <p className="mt-3.5 rounded-[11px] bg-[rgba(235,104,52,0.1)] px-3 py-2.5 text-[11.5px] leading-[1.5] text-[#B25E09] dark:text-[#F2A25C]">
              <AlertCircle className="mr-1.5 inline h-3 w-3" />
              {infoError}
            </p>
          )}

          <div className="mt-3.5 grid grid-cols-1 gap-2.5 xl:grid-cols-2">
            {(
              [
                {
                  key: false,
                  icon: Send,
                  title: "Publish to the profile",
                  body: `Goes out on ${accountName} at the scheduled time`,
                },
                {
                  key: true,
                  icon: FileText,
                  title: "Send to the TikTok inbox",
                  body: "Lands as a draft. You finish and publish it in the TikTok app",
                },
              ] as const
            ).map((m) => {
              const on = draft === m.key;
              const Icon = m.icon;
              return (
                <button
                  key={String(m.key)}
                  type="button"
                  onClick={() => setDraft(m.key)}
                  aria-pressed={on}
                  className={`flex items-start gap-2.5 rounded-[13px] border px-3.5 py-3 text-left transition-colors ${
                    on ? "border-primary shadow-[0_0_0_1px_var(--color-primary)]" : "border-border hover:bg-secondary"
                  }`}
                >
                  <span
                    className={`grid h-[30px] w-[30px] flex-none place-items-center rounded-[9px] border ${
                      on ? "border-primary bg-primary text-primary-foreground" : "border-border bg-secondary text-subtle"
                    }`}
                  >
                    <Icon className="h-[14px] w-[14px]" />
                  </span>
                  <span className="min-w-0">
                    <span className="block text-[12.5px] font-semibold leading-normal">{m.title}</span>
                    <span className="block text-[11px] leading-[1.45] text-subtle">{m.body}</span>
                  </span>
                  {on && <Check className="ml-auto h-[14px] w-[14px] flex-none" />}
                </button>
              );
            })}
          </div>

          {!draft && (
            <>
              <label className="mt-4 block">
                <span className="mb-[5px] block text-[11.5px] font-semibold leading-normal text-muted-foreground">
                  Title on TikTok
                </span>
                <Textarea
                  rows={2}
                  plain
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  placeholder="Shown above the caption on the post"
                />
              </label>

              <label className="mt-4 block">
                <span className="mb-[5px] block text-[11.5px] font-semibold leading-normal text-muted-foreground">
                  Who can see it
                </span>
                <select
                  value={privacy}
                  onChange={(e) => setPrivacy(e.target.value)}
                  className="w-full rounded-[12px] border border-border bg-card px-3 py-[9px] text-[12.5px] leading-normal outline-none focus:border-subtle disabled:opacity-50"
                >
                  <option value="">Choose who can see it</option>
                  {options.map((o) => (
                    <option key={o} value={o}>
                      {PRIVACY_LABEL[o] ?? o}
                    </option>
                  ))}
                </select>
              </label>
              {branded && (info?.privacy_level_options || []).includes(SELF) && (
                <Hint>Branded content cannot be set to Only me, so that option is not offered while it is on.</Hint>
              )}

              <div className="mt-4">
                <div className="mb-2 text-[10.5px] font-bold uppercase leading-normal tracking-[0.09em] text-subtle">
                  Let viewers
                </div>
                <div className="flex flex-wrap gap-2">
                  <Toggle label="Comment" checked={comment} disabled={!!info?.comment_disabled} onChange={setComment} />
                  <Toggle label="Duet" checked={false} disabled reason="not on photo posts" onChange={() => {}} />
                  <Toggle label="Stitch" checked={false} disabled reason="not on photo posts" onChange={() => {}} />
                </div>
              </div>

              <div className="mt-4 rounded-[13px] border border-border bg-card px-3.5 py-3">
                <Checkbox checked={disclose} onChange={setDisclose}>
                  <span>
                    <span className="block text-[13px] font-semibold leading-normal text-foreground">
                      This post is paid or promotional
                    </span>
                    <span className="block text-[11px] leading-[1.5] text-subtle">
                      Tick it if the post promotes goods or services in return for anything of value
                    </span>
                  </span>
                </Checkbox>
              </div>

              {disclose && (
                <div className="mt-2.5 flex flex-col gap-1 rounded-[13px] border border-border bg-secondary px-3.5 py-2.5">
                  <Checkbox checked={ownBrand} onChange={setOwnBrand}>
                    <span>
                      <span className="block text-[12.5px] font-semibold leading-normal text-foreground">
                        Your own brand
                      </span>
                      <span className="block text-[11px] leading-[1.45] text-subtle">
                        Promoting yourself or your own business
                      </span>
                    </span>
                  </Checkbox>
                  <Checkbox checked={branded} onChange={setBranded}>
                    <span>
                      <span className="block text-[12.5px] font-semibold leading-normal text-foreground">
                        Someone else&apos;s brand
                      </span>
                      <span className="block text-[11px] leading-[1.45] text-subtle">
                        A paid partnership with a third party —{" "}
                        <a
                          href="https://www.tiktok.com/legal/page/global/bc-policy/en"
                          target="_blank"
                          rel="noopener noreferrer"
                          className="underline"
                        >
                          Branded Content Policy
                        </a>
                      </span>
                    </span>
                  </Checkbox>
                  {(ownBrand || branded) && (
                    <p className="mt-1.5 rounded-[9px] border border-border bg-card px-2.5 py-[7px] text-[11px] leading-normal text-muted-foreground">
                      TikTok will label this post &ldquo;{branded ? "Paid partnership" : "Promotional content"}&rdquo;.
                    </p>
                  )}
                </div>
              )}
            </>
          )}

          {draft && (
            <p className="mt-4 flex items-start gap-2.5 rounded-[12px] bg-good/10 px-3.5 py-3 text-[12px] leading-[1.5] text-muted-foreground">
              <Check className="mt-0.5 h-[15px] w-[15px] flex-none text-good" strokeWidth={2.4} />
              Nothing else to set. Privacy, comments and disclosure are chosen inside the TikTok app when you publish the
              draft.
            </p>
          )}

          {problem && (
            <p className="mt-4 rounded-[11px] bg-[rgba(235,104,52,0.1)] px-3 py-2.5 text-[11.5px] leading-[1.5] text-[#B25E09] dark:text-[#F2A25C]">
              <AlertCircle className="mr-1.5 inline h-3 w-3" />
              {problem}
            </p>
          )}

          <div className="mt-4 flex flex-wrap items-center gap-3">
            <p className="min-w-[180px] flex-1 text-[11px] leading-[1.5] text-subtle">
              By posting you accept TikTok&apos;s{" "}
              {branded && (
                <>
                  <a
                    href="https://www.tiktok.com/legal/page/global/bc-policy/en"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="underline"
                  >
                    Branded Content Policy
                  </a>{" "}
                  and{" "}
                </>
              )}
              <a
                href="https://www.tiktok.com/legal/page/global/music-usage-confirmation/en"
                target="_blank"
                rel="noopener noreferrer"
                className="underline"
              >
                Music Usage Confirmation
              </a>
              .
            </p>
            <PrimaryButton icon={Check} onClick={save} disabled={!!problem || saving || loading}>
              {saving ? "Saving…" : "Save TikTok settings"}
            </PrimaryButton>
          </div>
          {savedAt && (
            <p className="mt-2 text-[10.5px] leading-normal text-subtle">
              Last saved {new Date(savedAt).toLocaleString()} — the consent stamp is what unlocks posting.
            </p>
          )}
        </div>
      )}
    </div>
  );
}

function Toggle({
  label,
  checked,
  disabled,
  reason,
  onChange,
}: {
  label: string;
  checked: boolean;
  disabled?: boolean;
  reason?: string;
  onChange: (v: boolean) => void;
}) {
  return (
    <label
      title={disabled ? reason ?? "off in TikTok" : undefined}
      className={`inline-flex items-center gap-[7px] rounded-[10px] border border-border bg-card px-[11px] py-[7px] text-xs leading-normal text-muted-foreground ${
        disabled ? "cursor-not-allowed opacity-50" : "cursor-pointer hover:bg-secondary"
      }`}
    >
      <input
        type="checkbox"
        checked={checked && !disabled}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
        className="pointer-events-none absolute opacity-0"
      />
      <span
        className={`grid h-4 w-4 flex-none place-items-center rounded-[5px] border-[1.5px] transition-colors ${
          checked && !disabled ? "border-primary bg-primary text-primary-foreground" : "border-border bg-card text-transparent"
        }`}
      >
        <Check className="h-[11px] w-[11px]" strokeWidth={3} />
      </span>
      {label}
      {disabled && reason && <em className="not-italic text-[10.5px] text-subtle">{reason}</em>}
    </label>
  );
}
