"use client";

/**
 * Account — the levers an admin has over a person that are the person's
 * own to pull.
 *
 * The admin user page sets name, email, role, status and the email switch,
 * and deletes. Of those, name, the switch and deleting are the user's here;
 * the address moves only through a code mailed to the *current* address
 * (the old page said the new one, which was wrong), and role and status are
 * shown, not editable. Phone, location, company and time zone have no
 * columns: they are `user_settings` rows (PROFILE_KEYS) that the admin page
 * reads back read-only.
 *
 * The letter box takes a profile picture (camera button). The server crops
 * and re-encodes it; the admin lists and user page show the same picture.
 *
 * Left out on purpose: plan and payment (the admin card is invented sample
 * data, and showing a user a made-up bill is worse than nothing), stuck
 * work and audit history (admin tools), and "sign out everywhere" (sign-ins
 * are stateless tokens; there is no session list to end).
 *
 * The counts along the top come from the user's own rows even when the
 * viewer is an admin: /api/stats and the outreach lists are instance-wide
 * for an admin, so those are filtered or swapped for the per-user source.
 */
import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import Link from "next/link";
import { Camera, Check, Eye, EyeOff, Info, Loader2, LogOut, Mail, Trash2, X } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "@/lib/auth";
import {
  PROFILE_KEYS, type ProfileKey,
  avatarSrc, removeAvatar, uploadAvatar,
  changePassword, confirmEmailChange, deleteMyAccount, getBrands, getPosts, getStats,
  getUserSettings, listOutreachAccounts, listOutreachCampaigns, requestEmailChange,
  updateProfile, updateUserSetting,
} from "@/lib/api";
import {
  Card, CardBody, CardHead, Chip, KV, PageActions, PageHead, PageTitle, PrimaryButton, Tag, TwoCol,
} from "@/components/kit";
import {
  DangerButton, Dialog, DialogBody, DialogFoot, DialogHead, Field, FieldLabel, GhostButton, Input,
} from "@/components/kit/dialog";
import { apiErrorMessage } from "@/components/kit/format";

type Row = Record<string, unknown>;
type Form = { name: string } & Record<ProfileKey, string>;
const EMPTY: Form = { name: "", profile_phone: "", profile_location: "", profile_company: "", profile_timezone: "" };
const CODE_LIFETIME_MS = 15 * 60 * 1000;

/* ------------------------------------------------------------------ clock */

const noSubscribe = () => () => {};
function subscribeMinute(cb: () => void) {
  const id = setInterval(cb, 30_000);
  return () => clearInterval(id);
}
/** The current minute, or null on the server — so "today" and "3:42 pm
 *  now" are read from the visitor's clock without a hydration mismatch. */
function useMinute() {
  return useSyncExternalStore(subscribeMinute, () => Math.floor(Date.now() / 60_000), () => null);
}
function now() {
  return Date.now();
}

function zones(): string[] {
  const intl = Intl as unknown as { supportedValuesOf?: (k: string) => string[] };
  return intl.supportedValuesOf?.("timeZone") ?? ["UTC"];
}
function useBrowserZone() {
  return useSyncExternalStore(noSubscribe, () => Intl.DateTimeFormat().resolvedOptions().timeZone, () => "");
}

function timeIn(zone: string, minute: number) {
  try {
    return new Date(minute * 60_000).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit", timeZone: zone });
  } catch {
    return "";
  }
}

function longDate(iso?: string | null) {
  return iso ? new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "long", year: "numeric" }) : "";
}

function lastSeen(iso: string | null | undefined, minute: number | null) {
  if (!iso) return "never";
  const d = new Date(iso);
  if (minute != null) {
    const days = Math.floor((minute * 60_000 - d.getTime()) / 86_400_000);
    const time = d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
    if (days <= 0) return `today, ${time}`;
    if (days === 1) return `yesterday, ${time}`;
  }
  return d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

function strength(p: string) {
  let n = 0;
  if (p.length >= 6) n++;
  if (p.length >= 10) n++;
  if (/[A-Z]/.test(p) && /[a-z]/.test(p)) n++;
  if (/\d|\W/.test(p)) n++;
  return { lit: p ? Math.max(n, 1) : 0, colour: p.length < 6 ? "var(--bad)" : n < 3 ? "var(--warn)" : "var(--good)" };
}

/* ------------------------------------------------------------------- page */

export default function AccountPage() {
  const { user, updateUser, logout } = useAuth();
  const minute = useMinute();
  const myZone = useBrowserZone();

  const [owns, setOwns] = useState<{ brands: number; accounts: number; posts: number; campaigns: number; senders: number } | null>(null);
  const [saved, setSaved] = useState<Form>(EMPTY);
  const [form, setForm] = useState<Form>(EMPTY);
  const [savingProfile, setSavingProfile] = useState(false);
  const [justSaved, setJustSaved] = useState(false);

  const load = useCallback(() => {
    if (!user) return;
    getUserSettings()
      .then((all: Record<string, string>) => {
        const next: Form = { ...EMPTY, name: user.name };
        for (const k of PROFILE_KEYS) next[k] = all[k] ?? "";
        setSaved(next);
        setForm(next);
      })
      .catch(() => {});

    const mine = (rows: Row[]) => rows.filter((r) => Number(r.user_id) === user.id).length;
    Promise.all([
      getBrands() as Promise<Row[]>,
      // /api/stats counts the whole instance for an admin; their own posts
      // list is the per-user number.
      user.role === "admin"
        ? (getPosts() as Promise<Row[]>).then((p) => p.length)
        : getStats().then((s: Row) => Number(s.total_posts ?? 0)),
      listOutreachCampaigns().then((r) => mine(r as unknown as Row[])),
      listOutreachAccounts().then((r) => mine(r as unknown as Row[])),
    ])
      .then(([brands, posts, campaigns, senders]) => setOwns({
        brands: brands.length,
        accounts: brands.reduce((n, b) => n + (Array.isArray(b.accounts) ? b.accounts.length : 0), 0),
        posts, campaigns, senders,
      }))
      .catch(() => {});
  }, [user]);

  useEffect(() => { load(); }, [load]);

  if (!user) return null;

  const dirty = (Object.keys(form) as (keyof Form)[]).some((k) => form[k] !== saved[k]);
  const status = user.status || "active";

  const saveProfile = async () => {
    setSavingProfile(true);
    try {
      if (form.name.trim() !== saved.name) {
        updateUser(await updateProfile({ name: form.name.trim() }));
      }
      for (const k of PROFILE_KEYS) {
        if (form[k] !== saved[k]) await updateUserSetting(k, form[k].trim());
      }
      const next = { ...form, name: form.name.trim() };
      setSaved(next);
      setForm(next);
      setJustSaved(true);
      toast.success("Profile saved");
    } catch (e) {
      toast.error(apiErrorMessage(e, "That did not save."));
    } finally {
      setSavingProfile(false);
    }
  };

  const set = (k: keyof Form) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
    setJustSaved(false);
    setForm({ ...form, [k]: e.target.value });
  };

  return (
    <>
      <PageHead>
        <PageTitle title="Account" sub="Who you are on Icreateflow, how you sign in, and what we email you." />
        <PageActions>
          <Chip icon={LogOut} danger onClick={logout}>Sign out</Chip>
        </PageActions>
      </PageHead>

      {/* ------------------------------------------------------------ who */}
      <Card>
        <div className="flex flex-wrap items-center gap-4 p-5">
          <AvatarBox
            letter={(form.name || user.name || "?").trim().charAt(0).toUpperCase()}
            src={avatarSrc(user.avatar_url)}
            onChange={(avatar_url) => updateUser({ ...user, avatar_url })}
          />
          <div className="min-w-0">
            <h2 className="flex flex-wrap items-center gap-2.5 text-[20px] font-extrabold tracking-[-0.025em] text-foreground">
              {form.name || user.name}
              <Tag tone={status === "active" ? "done" : status === "suspended" ? "stop" : "pause"}>
                {status.replace(/^./, (c) => c.toUpperCase())}
              </Tag>
            </h2>
            <div className="mt-0.5 text-[12.5px] text-subtle">
              {user.email} · member since {longDate(user.created_at)} · last signed in {lastSeen(user.last_login, minute)}
            </div>
          </div>
        </div>
        <div className="grid grid-cols-2 gap-2.5 px-5 pb-5 sm:grid-cols-3 lg:grid-cols-5">
          {([
            ["Brands", owns?.brands, "/brands"],
            ["Posting accounts", owns?.accounts, "/brands"],
            ["Posts", owns?.posts, "/posts"],
            ["Campaigns", owns?.campaigns, "/outreach"],
            ["Sending accounts", owns?.senders, "/outreach/accounts"],
          ] as const).map(([label, v, href]) => (
            <Link key={label} href={href}
              className="rounded-[12px] border border-border bg-secondary px-3.5 py-2.5 transition-[border-color,transform] duration-200 hover:-translate-y-px hover:border-subtle">
              <b className={`block text-[20px] font-extrabold leading-tight tracking-[-0.03em] tabular-nums ${v ? "text-foreground" : "text-subtle"}`}>
                {v == null ? "–" : v.toLocaleString()}
              </b>
              <i className="mt-0.5 block text-[10.5px] not-italic text-subtle">{label}</i>
            </Link>
          ))}
        </div>
      </Card>

      <TwoCol
        main={
          <>
            {/* ------------------------------------------------- profile */}
            <Card>
              <CardHead title="Profile" sub="How you appear in the app, and the details support uses to reach you" />
              <CardBody>
                <div className="grid gap-3.5 sm:grid-cols-2">
                  <Field label="Display name"><Input value={form.name} onChange={set("name")} autoComplete="name" /></Field>
                  <Optional label="Company"><Input value={form.profile_company} onChange={set("profile_company")} placeholder="Your label, studio or company" autoComplete="organization" /></Optional>
                  <Optional label="Phone"><Input value={form.profile_phone} onChange={set("profile_phone")} placeholder="+44 …" type="tel" autoComplete="tel" /></Optional>
                  <Optional label="Location"><Input value={form.profile_location} onChange={set("profile_location")} placeholder="City, country" /></Optional>
                  <Field label="Time zone" className="sm:col-span-2">
                    <select value={form.profile_timezone} onChange={set("profile_timezone")}
                      className="w-full appearance-none rounded-[12px] border border-border bg-card bg-[url('data:image/svg+xml,%3Csvg%20xmlns=%22http://www.w3.org/2000/svg%22%20width=%2212%22%20height=%2212%22%20viewBox=%220%200%2024%2024%22%20fill=%22none%22%20stroke=%22%238b92a3%22%20stroke-width=%222.4%22%3E%3Cpath%20d=%22M6%209l6%206%206-6%22/%3E%3C/svg%3E')] bg-[length:12px] bg-[right_12px_center] bg-no-repeat px-3 py-[9px] pr-8 text-[12.5px] leading-normal text-foreground outline-none transition-colors focus:border-subtle">
                      <option value="">Not set{myZone ? ` — this browser is on ${myZone}` : ""}</option>
                      {zones().map((z) => (
                        <option key={z} value={z}>
                          {z.replace(/_/g, " ")}{z === form.profile_timezone && minute != null ? ` — ${timeIn(z, minute)} now` : ""}
                        </option>
                      ))}
                    </select>
                  </Field>
                </div>
                <Why>Your time zone is for you. Each brand keeps its own posting time zone, which you set on the brand.</Why>
                <div className="mt-4 flex items-center justify-end gap-2">
                  {justSaved && !dirty && (
                    <span className="mr-auto flex items-center gap-1.5 text-[11.5px] font-semibold text-good">
                      <Check className="h-[13px] w-[13px]" strokeWidth={3} />Saved
                    </span>
                  )}
                  <GhostButton type="button" disabled={!dirty || savingProfile} onClick={() => setForm(saved)}
                    className="disabled:cursor-default disabled:opacity-50">Discard</GhostButton>
                  <PrimaryButton icon={Check} onClick={saveProfile} disabled={!dirty || savingProfile || !form.name.trim()}>
                    {savingProfile ? "Saving…" : "Save profile"}
                  </PrimaryButton>
                </div>
              </CardBody>
            </Card>

            <EmailCard current={user.email} onChanged={(email) => updateUser({ ...user, email })} />
            <PasswordCard />
          </>
        }
        rail={
          <>
            <NotificationsCard
              on={user.email_notifications !== false}
              onSaved={(u) => updateUser(u)}
            />

            {/* -------------------------------------------------- access */}
            <Card>
              <CardHead title="Your access" sub="Set by an admin — ask in Help & Support to change these" />
              <CardBody>
                <KV label="Role">{user.role === "admin" ? "Admin" : "User"}</KV>
                <KV label="Status">
                  <Tag tone={status === "active" ? "done" : status === "suspended" ? "stop" : "pause"}>
                    {status.replace(/^./, (c) => c.toUpperCase())}
                  </Tag>
                </KV>
                <KV label="Member since">
                  {user.created_at ? new Date(user.created_at).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" }) : "—"}
                </KV>
                <KV label="Last sign-in">{lastSeen(user.last_login, minute).replace(/^./, (c) => c.toUpperCase())}</KV>
                <KV label="Account id"><span className="font-mono font-medium">#{user.id}</span></KV>
              </CardBody>
            </Card>

            {/* ------------------------------------------------- sign-in */}
            <Card>
              <CardHead title="Signing in" sub="This device" />
              <CardBody>
                <div className="flex items-start gap-2.5 rounded-[12px] border border-border bg-secondary px-3.5 py-3 text-[11.5px] leading-[1.55] text-muted-foreground">
                  <Info className="mt-0.5 h-3.5 w-3.5 flex-none text-subtle" />
                  <span>
                    A sign-in lasts until it expires on its own. There is no list of signed-in devices to end one by
                    one, so after a password change, sign out on any device you no longer use.
                  </span>
                </div>
                <button type="button" onClick={logout}
                  className="mt-3 w-full rounded-[11px] border border-border bg-card px-4 py-[9px] text-[12.5px] font-semibold text-foreground transition-colors hover:border-bad/35 hover:text-bad">
                  Sign out of this device
                </button>
              </CardBody>
            </Card>

            <DeleteCard owns={owns} onDeleted={logout} />
          </>
        }
      />
    </>
  );
}

/* ------------------------------------------------------------ avatar box */

/** The letter box, or their picture, with a camera button to change it. */
function AvatarBox({ letter, src, onChange }: { letter: string; src?: string; onChange: (url: string) => void }) {
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);

  const pick = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setBusy(true);
    try {
      onChange((await uploadAvatar(file)).avatar_url);
      toast.success("Profile picture updated");
    } catch (err) {
      toast.error(apiErrorMessage(err, "That picture did not upload."));
    } finally {
      setBusy(false);
    }
  };
  const remove = async () => {
    setBusy(true);
    try {
      onChange((await removeAvatar()).avatar_url);
      toast.success("Profile picture removed");
    } catch (err) {
      toast.error(apiErrorMessage(err, "That did not go through."));
    } finally {
      setBusy(false);
    }
  };

  return (
    <span className="group relative h-16 w-16 flex-none">
      {src ? (
        // eslint-disable-next-line @next/next/no-img-element -- served by the API, not this app
        <img src={src} alt="Your profile picture" className="h-16 w-16 rounded-[20px] object-cover" />
      ) : (
        <span className="grid h-16 w-16 place-items-center rounded-[20px] bg-[linear-gradient(140deg,#ffd7a8,#f6a97a)] text-[26px] font-extrabold text-[#7a4a1e]">
          {letter}
        </span>
      )}
      {busy && (
        <span className="absolute inset-0 grid place-items-center rounded-[20px] bg-black/45 text-white">
          <Loader2 className="h-5 w-5 animate-spin" />
        </span>
      )}
      <button type="button" onClick={() => input.current?.click()} disabled={busy}
        aria-label={src ? "Change profile picture" : "Add a profile picture"} title={src ? "Change picture" : "Add a picture"}
        className="absolute -bottom-1.5 -right-1.5 grid h-7 w-7 place-items-center rounded-full border-[3px] border-card bg-foreground text-background shadow-[0_4px_10px_-4px_rgba(0,0,0,0.4)] transition-transform hover:scale-110">
        <Camera className="h-3 w-3" strokeWidth={2.4} />
      </button>
      {src && !busy && (
        <button type="button" onClick={remove} aria-label="Remove profile picture" title="Remove picture"
          className="absolute -right-1.5 -top-1.5 grid h-6 w-6 place-items-center rounded-full border-2 border-card bg-secondary text-muted-foreground opacity-0 shadow-sm transition-opacity hover:text-bad focus-visible:opacity-100 group-hover:opacity-100">
          <X className="h-3 w-3" strokeWidth={2.6} />
        </button>
      )}
      <input ref={input} type="file" accept="image/png,image/jpeg,image/webp,image/gif" className="hidden" onChange={pick} />
    </span>
  );
}

/* ------------------------------------------------------------ email card */

function EmailCard({ current, onChanged }: { current: string; onChanged: (email: string) => void }) {
  const [step, setStep] = useState<0 | 1 | 2>(0);
  const [newEmail, setNewEmail] = useState("");
  const [digits, setDigits] = useState<string[]>(["", "", "", "", "", ""]);
  const [busy, setBusy] = useState(false);
  const [sentAt, setSentAt] = useState(0);
  const [clock, setClock] = useState(0);
  const boxes = useRef<(HTMLInputElement | null)[]>([]);

  useEffect(() => {
    if (step !== 2) return;
    const id = setInterval(() => setClock(now()), 1000);
    return () => clearInterval(id);
  }, [step]);

  const send = async () => {
    const email = newEmail.trim().toLowerCase();
    if (!email || email === current) { toast.error("Enter the new address you want to use."); return; }
    setBusy(true);
    try {
      await requestEmailChange(email);
      const t = now();
      setSentAt(t);
      setClock(t);
      setDigits(["", "", "", "", "", ""]);
      setStep(2);
    } catch (e) {
      toast.error(apiErrorMessage(e, "We couldn't send a code."));
    } finally {
      setBusy(false);
    }
  };

  const confirm = async () => {
    const code = digits.join("");
    if (code.length < 6) { toast.error("Enter all 6 digits of the code."); return; }
    setBusy(true);
    try {
      await confirmEmailChange(code);
      onChanged(newEmail.trim().toLowerCase());
      toast.success(`Email changed to ${newEmail.trim().toLowerCase()}`);
      setStep(0);
      setNewEmail("");
    } catch (e) {
      toast.error(apiErrorMessage(e, "That code is wrong or has expired."));
    } finally {
      setBusy(false);
    }
  };

  const setDigit = (i: number, raw: string) => {
    const v = raw.replace(/\D/g, "").slice(-1);
    setDigits((d) => d.map((x, j) => (j === i ? v : x)));
    if (v) boxes.current[i + 1]?.focus();
  };
  const paste = (e: React.ClipboardEvent) => {
    const code = e.clipboardData.getData("text").replace(/\D/g, "").slice(0, 6);
    if (!code) return;
    e.preventDefault();
    setDigits(Array.from({ length: 6 }, (_, j) => code[j] ?? ""));
    boxes.current[Math.min(code.length, 5)]?.focus();
  };

  const left = Math.max(0, sentAt + CODE_LIFETIME_MS - clock);
  const mmss = `${String(Math.floor(left / 60000)).padStart(2, "0")}:${String(Math.floor((left % 60000) / 1000)).padStart(2, "0")}`;

  return (
    <Card>
      <CardHead title="Email address" sub="What you sign in with, and where we write to you" />
      <CardBody>
        <div className="flex items-center gap-3 rounded-[12px] border border-border bg-secondary px-3.5 py-3">
          <span className="grid h-8 w-8 flex-none place-items-center rounded-[10px] border border-border bg-card text-muted-foreground">
            <Mail className="h-[15px] w-[15px]" />
          </span>
          <div className="min-w-0">
            <b className="block truncate text-[13px] font-bold text-foreground">{current}</b>
            <small className="text-[11px] text-subtle">Current address</small>
          </div>
          {step === 0 && <Chip className="ml-auto" onClick={() => setStep(1)}>Change</Chip>}
        </div>

        {step > 0 && (
          <div className="mb-3 mt-4 flex gap-1.5">
            <span className="h-[3px] flex-1 rounded-full bg-foreground" />
            <span className={`h-[3px] flex-1 rounded-full ${step === 2 ? "bg-foreground" : "bg-line-2"}`} />
          </div>
        )}

        {step === 1 && (
          <>
            <Field label="New email address">
              <Input type="email" value={newEmail} onChange={(e) => setNewEmail(e.target.value)} placeholder="you@newaddress.com"
                autoComplete="email" onKeyDown={(e) => { if (e.key === "Enter") send(); }} />
            </Field>
            <Why>
              We send a 6-digit code to your <b className="font-semibold text-foreground">current</b> address, so nobody can
              move your account without access to it. The code lasts 15 minutes.
            </Why>
            <div className="mt-4 flex justify-end gap-2">
              <GhostButton type="button" onClick={() => setStep(0)}>Cancel</GhostButton>
              <PrimaryButton onClick={send} disabled={busy}>{busy ? "Sending…" : "Send code"}</PrimaryButton>
            </div>
          </>
        )}

        {step === 2 && (
          <>
            <FieldLabel>Code sent to {current}</FieldLabel>
            <div className="grid grid-cols-6 gap-[7px]" onPaste={paste}>
              {digits.map((d, i) => (
                <input key={i} ref={(el) => { boxes.current[i] = el; }} value={d} inputMode="numeric" maxLength={1}
                  aria-label={`Digit ${i + 1}`} autoComplete={i === 0 ? "one-time-code" : "off"}
                  onChange={(e) => setDigit(i, e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Backspace" && !d) boxes.current[i - 1]?.focus(); }}
                  className="h-11 min-w-0 rounded-[12px] border border-border bg-card text-center font-mono text-[18px] font-semibold text-foreground outline-none focus:border-subtle" />
              ))}
            </div>
            <div className="mt-1.5 flex justify-between gap-3 text-[11px] leading-[1.5] text-subtle">
              <span>
                Moving to <b className="font-semibold text-foreground">{newEmail.trim().toLowerCase()}</b> ·{" "}
                {left > 0 ? <>expires in <b className="font-mono font-semibold text-foreground">{mmss}</b></> : "this code has expired"}
              </span>
              <button type="button" onClick={send} disabled={busy} className="flex-none font-semibold text-foreground hover:underline">
                Send again
              </button>
            </div>
            <div className="mt-4 flex justify-end gap-2">
              <GhostButton type="button" onClick={() => setStep(0)}>Cancel</GhostButton>
              <PrimaryButton onClick={confirm} disabled={busy}>{busy ? "Checking…" : "Confirm change"}</PrimaryButton>
            </div>
          </>
        )}
      </CardBody>
    </Card>
  );
}

/* --------------------------------------------------------- password card */

function PasswordCard() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [again, setAgain] = useState("");
  const [busy, setBusy] = useState(false);
  const m = strength(next);
  const ready = !!current && next.length >= 6 && next === again;

  const submit = async () => {
    setBusy(true);
    try {
      await changePassword(current, next);
      toast.success("Password updated");
      setCurrent(""); setNext(""); setAgain("");
    } catch (e) {
      toast.error(apiErrorMessage(e, "That did not change."));
    } finally {
      setBusy(false);
    }
  };

  return (
    // Fills the column, so it ends level with the rail beside it.
    <Card className="flex flex-1 flex-col">
      <CardHead title="Password" sub="You need your current one to set a new one" />
      <CardBody className="flex flex-1 flex-col">
        <div className="grid gap-3.5 sm:grid-cols-2">
          <SecretField label="Current password" className="sm:col-span-2" value={current} onChange={setCurrent}
            placeholder="Your current password" autoComplete="current-password" />
          <div>
            <SecretField label="New password" value={next} onChange={setNext}
              placeholder="At least 6 characters" autoComplete="new-password" />
            <div className="mt-[7px] flex gap-1" aria-hidden="true">
              {[0, 1, 2, 3].map((i) => (
                <i key={i} className="h-[3px] flex-1 rounded-full bg-line-2 transition-colors"
                  style={{ background: i < m.lit ? m.colour : undefined }} />
              ))}
            </div>
          </div>
          <SecretField label="Confirm new password" value={again} onChange={setAgain}
            placeholder="Type it again" autoComplete="new-password" />
        </div>
        <Why>Forgotten your current one? Sign out and use “Forgot password?” on the log-in page — it mails you a code.</Why>
        <div className="mt-auto flex justify-end pt-4">
          <PrimaryButton onClick={submit} disabled={!ready || busy}>{busy ? "Updating…" : "Update password"}</PrimaryButton>
        </div>
      </CardBody>
    </Card>
  );
}

/** A password field with show/hide. A div and htmlFor rather than Field's
 *  wrapping <label>, because the label would also catch the eye button. */
function SecretField({ label, value, onChange, placeholder, autoComplete, className = "" }: {
  label: string; value: string; onChange: (v: string) => void; placeholder: string; autoComplete: string; className?: string;
}) {
  const [shown, setShown] = useState(false);
  const id = `pw-${label.toLowerCase().replace(/\W+/g, "-")}`;
  return (
    <div className={`flex flex-col gap-[5px] ${className}`}>
      <label htmlFor={id} className="text-[11.5px] font-semibold leading-normal text-muted-foreground">{label}</label>
      <span className="relative block">
      <Input id={id} type={shown ? "text" : "password"} value={value} onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder} autoComplete={autoComplete} className="pr-10" />
      <button type="button" onClick={() => setShown((v) => !v)} aria-label={shown ? "Hide password" : "Show password"}
        className="absolute right-1.5 top-1/2 grid h-7 w-7 -translate-y-1/2 place-items-center rounded-[8px] text-subtle hover:bg-secondary hover:text-foreground">
        {shown ? <EyeOff className="h-[15px] w-[15px]" /> : <Eye className="h-[15px] w-[15px]" />}
      </button>
      </span>
    </div>
  );
}

/* ---------------------------------------------------- notifications card */

function NotificationsCard({ on, onSaved }: { on: boolean; onSaved: (u: Awaited<ReturnType<typeof updateProfile>>) => void }) {
  const [busy, setBusy] = useState(false);
  const flip = async () => {
    setBusy(true);
    try {
      onSaved(await updateProfile({ email_notifications: !on }));
      toast.success(on ? "Emails off — codes still arrive" : "Emails on");
    } catch (e) {
      toast.error(apiErrorMessage(e, "That did not change."));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Card>
      <CardHead title="Email notifications" sub="One switch — the app has no per-type preferences" />
      <CardBody className="pt-1.5">
        <div className="flex items-center gap-3 py-3">
          <div className="min-w-0 flex-1">
            <b className="block text-[12.5px] font-bold text-foreground">Send me emails</b>
            <small className="mt-px block text-[11px] leading-[1.45] text-subtle">
              Approvals, finished renders and campaign updates. Password and email-change codes always arrive.
            </small>
          </div>
          <button type="button" role="switch" aria-checked={on} aria-label="Send me emails" onClick={flip} disabled={busy}
            className={`relative h-[22px] w-[38px] flex-none rounded-full border transition-colors disabled:opacity-60 ${
              on ? "border-good bg-good" : "border-border bg-line-2"}`}>
            <span className={`absolute left-[2px] top-[2px] h-4 w-4 rounded-full bg-white shadow-[0_1px_3px_rgba(0,0,0,0.25)] transition-transform duration-[250ms] ${
              on ? "translate-x-4" : ""}`} />
          </button>
        </div>
        <Why>The unsubscribe link in our emails flips this same switch, so you can always turn it back on here.</Why>
      </CardBody>
    </Card>
  );
}

/* ----------------------------------------------------------- delete card */

function DeleteCard({ owns, onDeleted }: {
  owns: { brands: number; accounts: number; posts: number; campaigns: number; senders: number } | null;
  onDeleted: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [typed, setTyped] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const armed = typed === "DELETE" && password.length > 0;

  const close = () => { setOpen(false); setTyped(""); setPassword(""); };
  const go = async () => {
    setBusy(true);
    try {
      await deleteMyAccount(password);
      toast.success("Your account has been deleted.");
      onDeleted();
    } catch (e) {
      toast.error(apiErrorMessage(e, "That did not go through."));
      setBusy(false);
    }
  };

  return (
    <Card className="flex flex-1 flex-col border-bad/30">
      <CardHead title="Delete your account" sub="Immediately, with no undo" />
      <CardBody className="flex flex-1 flex-col">
        <div className="text-[12px] leading-[1.6] text-muted-foreground">
          Removes your brands, posts, posting accounts, artists and clips, outreach campaigns and sending accounts,
          music, and the account itself.
        </div>
        <div className="mt-auto pt-3.5">
          <DangerButton type="button" onClick={() => setOpen(true)}>
            <Trash2 className="h-3.5 w-3.5" />Delete my account
          </DangerButton>
        </div>
      </CardBody>

      <Dialog open={open} onClose={close} label="Delete your account">
        <DialogHead title="Delete your account?" onClose={close}
          sub="This happens immediately and cannot be undone." />
        <DialogBody>
          <div className="text-[12.5px] leading-[1.6] text-muted-foreground">
            It takes with it:
            <ul className="mt-1.5 list-disc space-y-0.5 pl-5 text-[12px]">
              {owns ? (
                <>
                  <li>{owns.brands} brands and their {owns.posts} posts</li>
                  <li>{owns.accounts} posting accounts</li>
                  <li>{owns.campaigns} outreach campaigns and {owns.senders} sending accounts</li>
                  <li>your artists, clips, music and settings</li>
                </>
              ) : (
                <li>everything you have made here</li>
              )}
            </ul>
          </div>
          <div className="mt-4 flex flex-col gap-3">
            <Field label="Type DELETE to confirm">
              <Input value={typed} onChange={(e) => setTyped(e.target.value)} placeholder="DELETE" autoComplete="off" />
            </Field>
            <Field label="Your password">
              <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)}
                placeholder="So nobody else can do this from your session" autoComplete="current-password" />
            </Field>
          </div>
        </DialogBody>
        <DialogFoot>
          <GhostButton type="button" onClick={close}>Keep my account</GhostButton>
          <DangerButton type="button" disabled={!armed || busy} onClick={go}>
            {busy ? "Deleting…" : "Delete everything"}
          </DangerButton>
        </DialogFoot>
      </Dialog>
    </Card>
  );
}

/* ------------------------------------------------------------------ bits */

/** A field marked optional on the right of its label, as in the preview. */
function Optional({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-[5px]">
      <span className="flex items-baseline justify-between text-[11.5px] font-semibold leading-normal text-muted-foreground">
        {label}<em className="text-[11px] font-medium not-italic text-subtle">optional</em>
      </span>
      {children}
    </label>
  );
}

/** The sentence under a control that says what it will actually do. */
function Why({ children }: { children: React.ReactNode }) {
  return <div className="mt-1.5 text-[11px] leading-[1.5] text-subtle">{children}</div>;
}
