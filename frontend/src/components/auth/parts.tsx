"use client";

/**
 * The form vocabulary of the auth pages. Kept apart from the app kit
 * (`components/kit/dialog.tsx`) on purpose: these are pill fields on a
 * frame, not square fields in a card, and the two should be free to differ.
 */
import { useState } from "react";
import Link from "next/link";
import { AlertCircle, ArrowLeft, ArrowRight, Eye, EyeOff, Loader2 } from "lucide-react";
import s from "./auth.module.css";

export { s as authStyles };

/** Log in / Sign up. Each is its own route, so the thumb slides in from the
 *  tab that was left (see `.thumbLogin` in the stylesheet). */
export function AuthTabs({ active }: { active: "login" | "register" }) {
  return (
    <nav className={s.seg} aria-label="Log in or sign up">
      <span className={`${s.thumb} ${active === "login" ? s.thumbLogin : s.thumbRegister}`} />
      <Link href="/login" aria-current={active === "login" ? "page" : undefined}>Log in</Link>
      <Link href="/register" aria-current={active === "register" ? "page" : undefined}>Sign up</Link>
    </nav>
  );
}

export function AuthHead({ title, children }: { title: string; children?: React.ReactNode }) {
  return (
    <>
      <h1 className={s.title}>{title}</h1>
      {children && <p className={s.lede}>{children}</p>}
    </>
  );
}

export function Field({
  id, label, action, children,
}: { id: string; label: string; action?: React.ReactNode; children: React.ReactNode }) {
  return (
    <div>
      <div className={s.lab}>
        <label htmlFor={id}>{label}</label>
        {action}
      </div>
      {children}
    </div>
  );
}

type InputProps = React.InputHTMLAttributes<HTMLInputElement>;

export function TextInput(props: InputProps) {
  return <div className={s.inp}><input {...props} /></div>;
}

/** A password field with its own show/hide, and an optional slot (the
 *  match tick on Confirm) drawn inside the pill. */
export function PasswordInput({ tick, ...props }: InputProps & { tick?: boolean }) {
  const [shown, setShown] = useState(false);
  return (
    <div className={`${s.inp} ${s.hasBtn}`}>
      <input {...props} type={shown ? "text" : "password"} />
      {tick === undefined ? (
        <button type="button" className={s.eye} onClick={() => setShown((v) => !v)} aria-label={shown ? "Hide password" : "Show password"}>
          {shown ? <EyeOff className="h-[18px] w-[18px]" strokeWidth={1.8} /> : <Eye className="h-[18px] w-[18px]" strokeWidth={1.8} />}
        </button>
      ) : (
        <svg className={`${s.tick} ${tick ? s.tickOn : ""}`} width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" aria-hidden="true">
          <path d="M5 12.5l4.5 4.5L19 7.5" />
        </svg>
      )}
    </div>
  );
}

export function Cta({ busy, children, ...props }: React.ButtonHTMLAttributes<HTMLButtonElement> & { busy?: boolean }) {
  return (
    <button {...props} className={s.cta} disabled={busy || props.disabled}>
      {children}
      <span className={s.arr}>
        {busy ? <Loader2 className="h-[15px] w-[15px] animate-spin" /> : <ArrowRight className="h-[15px] w-[15px]" strokeWidth={2.4} />}
      </span>
    </button>
  );
}

/** A failed attempt. `warn` is for "not yet" (an account still waiting for
 *  approval), which is not the visitor's mistake and should not shake. */
export function AuthError({ children, warn }: { children: React.ReactNode; warn?: boolean }) {
  return (
    <div className={`${s.err} ${warn ? s.warn : ""}`} role="alert">
      <AlertCircle className="h-4 w-4" strokeWidth={2} />
      <span>{children}</span>
    </div>
  );
}

export function BackButton({ onClick, children }: { onClick: () => void; children: React.ReactNode }) {
  return (
    <button type="button" className={s.back} onClick={onClick}>
      <ArrowLeft className="h-3.5 w-3.5" strokeWidth={2.2} />
      {children}
    </button>
  );
}
