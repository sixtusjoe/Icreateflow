"use client";

/**
 * Sign up. A new account lands in `pending` and cannot log in until an
 * admin approves it, so the page says that before the form is filled, not
 * only after — and the success view is a "you're on the list" with the
 * three steps spelled out, rather than a welcome that the next login would
 * contradict.
 *
 * The only password rule the backend enforces is six characters. The meter
 * colours past that to nudge towards longer passwords but never blocks one.
 */
import { useState } from "react";
import Link from "next/link";
import { Check, Mail } from "lucide-react";
import { useAuth } from "@/lib/auth";
import {
  AuthError, AuthHead, AuthTabs, Cta, Field, PasswordInput, TextInput, authStyles as s,
} from "@/components/auth/parts";

function strength(p: string) {
  let n = 0;
  if (p.length >= 6) n++;
  if (p.length >= 10) n++;
  if (/[A-Z]/.test(p) && /[a-z]/.test(p)) n++;
  if (/\d|[^\w]/.test(p)) n++;
  const colour = p.length < 6 ? "var(--bad)" : n < 3 ? "var(--warn)" : "var(--good)";
  const short = 6 - p.length;
  const note = !p
    ? "At least 6 characters."
    : short > 0
      ? `${short} more character${short > 1 ? "s" : ""}`
      : n < 3 ? "Okay — longer is stronger" : "Strong password";
  return { lit: p ? Math.max(n, 1) : 0, colour, note };
}

export default function RegisterPage() {
  const { register } = useAuth();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [submitted, setSubmitted] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    if (password.length < 6) { setError("Password must be at least 6 characters"); return; }
    if (password !== confirm) { setError("Passwords do not match"); return; }
    setBusy(true);
    try {
      await register(email, password, name);
      setSubmitted(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Registration failed");
    } finally {
      setBusy(false);
    }
  };

  if (submitted) {
    return (
      <div key="pending" className={`${s.view} ${s.stag}`}>
        <div className={`${s.badge} ${s.badgeWait}`}>
          <span className={s.ring} />
          <svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" aria-hidden="true">
            <circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" />
          </svg>
        </div>
        <AuthHead title="You're on the list">
          Thanks, {name.trim().split(" ")[0] || "there"}. An admin approves every new account by hand. We&apos;ll email <b>{email}</b>{" "}as soon as you&apos;re in.
        </AuthHead>
        <div className={s.steps}>
          <div className={s.step}>
            <span className={`${s.dot} ${s.dotDone}`}><Check className="h-[13px] w-[13px]" strokeWidth={3} /></span>
            <div>Account created<small>Just now</small></div>
          </div>
          <div className={s.step}>
            <span className={`${s.dot} ${s.dotNow}`}><span className={s.pulse} /></span>
            <div>Waiting for an admin<small>You can&apos;t log in until this is done</small></div>
          </div>
          <div className={s.step}>
            <span className={`${s.dot} ${s.dotNext}`}><Mail className="h-[13px] w-[13px]" strokeWidth={2} /></span>
            <div>Approval email<small>Then log in with this address</small></div>
          </div>
        </div>
        <Link href="/login" className={s.ghost}>Back to log in</Link>
      </div>
    );
  }

  const m = strength(password);

  return (
    <div key="register" className={s.view}>
      <AuthTabs active="register" />
      <AuthHead title="Create an account">An admin reviews each new account, and we email you when you&apos;re in.</AuthHead>
      <form className={`${s.form} ${s.stag}`} onSubmit={handleSubmit}>
        {error && <AuthError key={error + String(busy)}>{error}</AuthError>}
        <Field id="rn" label="Full name">
          <TextInput id="rn" value={name} onChange={(e) => setName(e.target.value)} required autoFocus placeholder="Your name" autoComplete="name" />
        </Field>
        <Field id="re" label="Email">
          <TextInput id="re" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required placeholder="you@studio.com" autoComplete="email" />
        </Field>
        <div>
          <Field id="rp" label="Password">
            <PasswordInput id="rp" value={password} onChange={(e) => setPassword(e.target.value)} required
              placeholder="At least 6 characters" autoComplete="new-password" />
          </Field>
          <div className={s.meter} aria-hidden="true">
            {[0, 1, 2, 3].map((i) => <i key={i} style={{ background: i < m.lit ? m.colour : undefined }} />)}
          </div>
          <div className={s.meterNote}>{m.note}</div>
        </div>
        <Field id="rc" label="Confirm password">
          <PasswordInput id="rc" value={confirm} onChange={(e) => setConfirm(e.target.value)} required
            placeholder="Type it again" autoComplete="new-password" tick={!!confirm && confirm === password} />
        </Field>
        <Cta type="submit" busy={busy}>Create account</Cta>
      </form>
      <p className={s.alt}>Already have an account? <Link href="/login">Log in</Link></p>
    </div>
  );
}
