"use client";

/**
 * Log in, and the forgotten-password flow that lives inside it.
 *
 * The flow is four views on one route — log in, ask for a code, enter the
 * code with a new password, done — because the backend's reset is a code
 * mailed to the address (`/api/auth/forgot-password`), valid for fifteen
 * minutes, then spent by `/api/auth/reset-password`. The countdown on the
 * code view is that fifteen minutes, counted from when the code was asked
 * for, so it is honest about when "Send a new code" becomes the only way on.
 *
 * Login refuses an account still waiting for approval with a 403. That is
 * shown in amber and does not shake: it is "not yet", not a wrong password.
 */
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useAuth } from "@/lib/auth";
import { forgotPassword, resetPassword } from "@/lib/api";
import {
  AuthError, AuthHead, AuthTabs, BackButton, Cta, Field, PasswordInput, TextInput, authStyles as s,
} from "@/components/auth/parts";

type View = "login" | "forgot" | "code" | "done";

const CODE_LIFETIME_MS = 15 * 60 * 1000;

function now() {
  return Date.now();
}

/** The backend's sentence for a refused login, said for this page. */
function loginError(message: string): { text: string; warn: boolean } {
  if (/pending/i.test(message)) return { text: "Your account is still waiting for an admin to approve it.", warn: true };
  if (/suspended/i.test(message)) return { text: "This account has been suspended.", warn: false };
  return { text: message || "Login failed", warn: false };
}

function detailOf(err: unknown, fallback: string) {
  const d = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof d === "string" ? d : fallback;
}

export default function LoginPage() {
  const { login } = useAuth();
  const [view, setView] = useState<View>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<{ text: string; warn: boolean } | null>(null);
  const [busy, setBusy] = useState(false);

  // Reset flow
  const [fpEmail, setFpEmail] = useState("");
  const [digits, setDigits] = useState<string[]>(["", "", "", "", "", ""]);
  const [newPw, setNewPw] = useState("");
  const [sentAt, setSentAt] = useState(0);
  const [clock, setClock] = useState(0);
  const boxes = useRef<(HTMLInputElement | null)[]>([]);

  useEffect(() => {
    if (view !== "code") return;
    const id = setInterval(() => setClock(now()), 1000);
    return () => clearInterval(id);
  }, [view]);

  const go = (v: View) => { setError(null); setView(v); };

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await login(email, password);
    } catch (err) {
      setError(loginError(err instanceof Error ? err.message : ""));
    } finally {
      setBusy(false);
    }
  };

  const sendCode = async () => {
    setError(null);
    setBusy(true);
    try {
      await forgotPassword(fpEmail);
      const t = now();
      setSentAt(t);
      setClock(t);
      setDigits(["", "", "", "", "", ""]);
      setView("code");
    } catch {
      setError({ text: "We couldn't send a code. Try again in a moment.", warn: false });
    } finally {
      setBusy(false);
    }
  };

  const handleReset = async (e: React.FormEvent) => {
    e.preventDefault();
    const code = digits.join("");
    if (code.length < 6) { setError({ text: "Enter all 6 digits of the code.", warn: false }); return; }
    if (newPw.length < 6) { setError({ text: "Password must be at least 6 characters.", warn: false }); return; }
    setError(null);
    setBusy(true);
    try {
      await resetPassword(fpEmail, code, newPw);
      setNewPw("");
      setView("done");
    } catch (err) {
      setError({ text: detailOf(err, "That code is wrong or has expired."), warn: false });
    } finally {
      setBusy(false);
    }
  };

  const setDigit = (i: number, raw: string) => {
    const v = raw.replace(/\D/g, "").slice(-1);
    setDigits((d) => d.map((x, j) => (j === i ? v : x)));
    if (v) boxes.current[i + 1]?.focus();
  };
  const pasteCode = (e: React.ClipboardEvent) => {
    const code = e.clipboardData.getData("text").replace(/\D/g, "").slice(0, 6);
    if (!code) return;
    e.preventDefault();
    setDigits(Array.from({ length: 6 }, (_, j) => code[j] ?? ""));
    boxes.current[Math.min(code.length, 5)]?.focus();
  };

  const left = Math.max(0, sentAt + CODE_LIFETIME_MS - clock);
  const mmss = `${String(Math.floor(left / 60000)).padStart(2, "0")}:${String(Math.floor((left % 60000) / 1000)).padStart(2, "0")}`;

  if (view === "forgot") {
    return (
      <div key="forgot" className={s.view}>
        <BackButton onClick={() => go("login")}>Back to log in</BackButton>
        <AuthHead title="Reset your password">Enter your email and we&apos;ll send you a 6-digit code.</AuthHead>
        <form className={`${s.form} ${s.stag}`} onSubmit={(e) => { e.preventDefault(); sendCode(); }}>
          {error && <AuthError warn={error.warn}>{error.text}</AuthError>}
          <Field id="fe" label="Email">
            <TextInput id="fe" type="email" value={fpEmail} onChange={(e) => setFpEmail(e.target.value)} required autoFocus
              placeholder="you@studio.com" autoComplete="email" />
          </Field>
          <Cta type="submit" busy={busy}>Send code</Cta>
        </form>
      </div>
    );
  }

  if (view === "code") {
    return (
      <div key="code" className={s.view}>
        <BackButton onClick={() => go("forgot")}>Use a different email</BackButton>
        <AuthHead title="Check your email">We sent a 6-digit code to <b>{fpEmail}</b>.</AuthHead>
        <form className={`${s.form} ${s.stag}`} onSubmit={handleReset}>
          {error && <AuthError>{error.text}</AuthError>}
          <div>
            <div className={s.lab} style={{ marginBottom: 9 }}><span>Code</span></div>
            <div className={s.otp} onPaste={pasteCode}>
              {digits.map((d, i) => (
                <input key={i} ref={(el) => { boxes.current[i] = el; }} value={d} inputMode="numeric" maxLength={1}
                  autoComplete={i === 0 ? "one-time-code" : "off"} autoFocus={i === 0} aria-label={`Digit ${i + 1}`}
                  className={d ? s.filled : ""} onChange={(e) => setDigit(i, e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Backspace" && !d) boxes.current[i - 1]?.focus(); }} />
              ))}
            </div>
            <div className={s.expiry}>
              <span>{left > 0 ? <>Code expires in <b>{mmss}</b></> : "This code has expired"}</span>
              <button type="button" onClick={sendCode} disabled={busy}>Send a new code</button>
            </div>
          </div>
          <Field id="np" label="New password">
            <PasswordInput id="np" value={newPw} onChange={(e) => setNewPw(e.target.value)} required minLength={6}
              placeholder="At least 6 characters" autoComplete="new-password" />
          </Field>
          <Cta type="submit" busy={busy}>Set new password</Cta>
        </form>
      </div>
    );
  }

  if (view === "done") {
    return (
      <div key="done" className={`${s.view} ${s.stag}`}>
        <div className={`${s.badge} ${s.badgeOk}`}>
          <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M5 12.5l4.5 4.5L19 7.5" />
          </svg>
        </div>
        <AuthHead title="Password updated">Your new password works now. Log in with it to pick up where you left off.</AuthHead>
        <div style={{ height: 30 }} />
        <Cta type="button" onClick={() => { setEmail(fpEmail); setPassword(""); go("login"); }}>Log in</Cta>
      </div>
    );
  }

  return (
    <div key="login" className={s.view}>
      <AuthTabs active="login" />
      <AuthHead title="Welcome back">Log in to schedule posts, cut clips and run your outreach.</AuthHead>
      <form className={`${s.form} ${s.stag}`} onSubmit={handleLogin}>
        {error && <AuthError key={error.text + String(busy)} warn={error.warn}>{error.text}</AuthError>}
        <Field id="le" label="Email">
          <TextInput id="le" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoFocus
            placeholder="you@studio.com" autoComplete="email" />
        </Field>
        <Field id="lp" label="Password" action={
          <button type="button" className={s.labAction} onClick={() => { setFpEmail(email); go("forgot"); }}>Forgot password?</button>
        }>
          <PasswordInput id="lp" value={password} onChange={(e) => setPassword(e.target.value)} required
            placeholder="Your password" autoComplete="current-password" />
        </Field>
        <Cta type="submit" busy={busy}>Log in</Cta>
      </form>
      <p className={s.alt}>New to Icreateflow? <Link href="/register">Create an account</Link></p>
    </div>
  );
}
