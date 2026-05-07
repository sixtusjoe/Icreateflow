"use client";

import { useState } from "react";
import Link from "next/link";
import { useAuth } from "@/lib/auth";
import { Loader2, Eye, EyeOff, LogIn, UserPlus, Zap, BarChart3, Layers, ArrowLeft } from "lucide-react";
import ThemeToggle from "@/components/ThemeToggle";
import { forgotPassword, resetPassword } from "@/lib/api";

type View = "login" | "forgot" | "reset";

export default function LoginPage() {
  const { login } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [view, setView] = useState<View>("login");

  // Forgot password state
  const [fpEmail, setFpEmail] = useState("");
  const [fpSent, setFpSent] = useState(false);
  const [fpCode, setFpCode] = useState("");
  const [fpNewPw, setFpNewPw] = useState("");
  const [fpShowPw, setFpShowPw] = useState(false);
  const [fpSuccess, setFpSuccess] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await login(email, password);
    } catch (err: any) {
      setError(err.message || "Login failed");
    } finally {
      setLoading(false);
    }
  };

  const handleForgotSend = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await forgotPassword(fpEmail);
      setFpSent(true);
    } catch {
      setError("Failed to send reset code");
    } finally {
      setLoading(false);
    }
  };

  const handleForgotReset = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await resetPassword(fpEmail, fpCode, fpNewPw);
      setFpSuccess(true);
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Invalid code or expired");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen">
      {/* Left — Form */}
      <div className="flex flex-1 flex-col justify-between bg-background px-8 py-6 md:px-16 lg:px-24">
        <div className="flex items-center justify-between">
          <Link href="/" className="text-lg font-bold tracking-tight text-foreground">Icreateflow</Link>
          <ThemeToggle />
        </div>

        <div className="mx-auto w-full max-w-sm animate-slide-up">
          {/* Tabs with icons */}
          <div className="mb-8 flex rounded-xl border border-border overflow-hidden">
            <div className="flex flex-1 items-center justify-center gap-2 bg-foreground py-3 text-sm font-semibold text-background">
              <LogIn className="h-4 w-4" />
              Log In
            </div>
            <Link href="/register" className="flex flex-1 items-center justify-center gap-2 py-3 text-sm font-medium text-muted-foreground hover:text-foreground transition-colors">
              <UserPlus className="h-4 w-4" />
              Sign Up
            </Link>
          </div>

          {view === "login" && (
            <>
              <form onSubmit={handleSubmit} className="space-y-5">
                {error && (
                  <div className="rounded-lg border border-red-300 bg-red-50 px-4 py-2.5 text-sm text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-400">
                    {error}
                  </div>
                )}

                <div>
                  <label className="mb-1.5 block text-sm font-semibold text-foreground">Email</label>
                  <input
                    type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoFocus
                    className="w-full rounded-xl border border-border bg-background px-4 py-3 text-sm text-foreground outline-none transition-colors focus:border-foreground placeholder:text-muted-foreground"
                    placeholder="Work Email"
                  />
                </div>

                <div>
                  <div className="mb-1.5 flex items-center justify-between">
                    <label className="text-sm font-semibold text-foreground">Password</label>
                    <button type="button" onClick={() => { setView("forgot"); setFpEmail(email); setError(""); }}
                      className="text-xs text-muted-foreground hover:text-foreground">
                      Forgot password?
                    </button>
                  </div>
                  <div className="relative">
                    <input
                      type={showPw ? "text" : "password"} value={password} onChange={(e) => setPassword(e.target.value)} required
                      className="w-full rounded-xl border border-border bg-background px-4 py-3 pr-10 text-sm text-foreground outline-none transition-colors focus:border-foreground placeholder:text-muted-foreground"
                      placeholder="Enter your password"
                    />
                    <button type="button" onClick={() => setShowPw(!showPw)}
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground">
                      {showPw ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                    </button>
                  </div>
                </div>

                <button type="submit" disabled={loading}
                  className="flex w-full items-center justify-center gap-2 rounded-xl bg-lime py-3 text-sm font-bold text-black transition-all hover:brightness-95 disabled:opacity-50">
                  {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <LogIn className="h-4 w-4" />}
                  Log In
                </button>
              </form>

              <p className="mt-5 text-center text-sm text-muted-foreground">
                Don&apos;t have an account?{" "}
                <Link href="/register" className="font-semibold text-foreground hover:underline">Sign up free</Link>
              </p>
            </>
          )}

          {view === "forgot" && (
            <div className="space-y-5">
              <button onClick={() => { setView("login"); setError(""); }}
                className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
                <ArrowLeft className="h-3.5 w-3.5" /> Back to login
              </button>
              <div>
                <h2 className="text-lg font-bold">Reset password</h2>
                <p className="mt-1 text-sm text-muted-foreground">
                  {fpSent ? "Enter the 6-digit code we sent to your email." : "Enter your email to receive a reset code."}
                </p>
              </div>
              {error && (
                <div className="rounded-lg border border-red-300 bg-red-50 px-4 py-2.5 text-sm text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-400">
                  {error}
                </div>
              )}
              {fpSuccess ? (
                <div className="rounded-lg bg-emerald-50 px-4 py-3 text-sm text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-400">
                  Password updated! <button onClick={() => { setView("login"); setFpSent(false); setFpSuccess(false); }} className="font-semibold underline">Log in</button>
                </div>
              ) : !fpSent ? (
                <form onSubmit={handleForgotSend} className="space-y-4">
                  <input type="email" value={fpEmail} onChange={(e) => setFpEmail(e.target.value)} required placeholder="Your email address"
                    className="w-full rounded-xl border border-border bg-background px-4 py-3 text-sm outline-none focus:border-foreground" />
                  <button type="submit" disabled={loading}
                    className="flex w-full items-center justify-center gap-2 rounded-xl bg-foreground py-3 text-sm font-bold text-background disabled:opacity-50">
                    {loading && <Loader2 className="h-4 w-4 animate-spin" />} Send reset code
                  </button>
                </form>
              ) : (
                <form onSubmit={handleForgotReset} className="space-y-4">
                  <input type="text" value={fpCode} onChange={(e) => setFpCode(e.target.value)} required placeholder="6-digit code"
                    maxLength={6} className="w-full rounded-xl border border-border bg-background px-4 py-3 text-sm outline-none focus:border-foreground tracking-widest text-center text-lg font-mono" />
                  <div className="relative">
                    <input type={fpShowPw ? "text" : "password"} value={fpNewPw} onChange={(e) => setFpNewPw(e.target.value)} required
                      placeholder="New password (min 6 chars)" minLength={6}
                      className="w-full rounded-xl border border-border bg-background px-4 py-3 pr-10 text-sm outline-none focus:border-foreground" />
                    <button type="button" onClick={() => setFpShowPw((v) => !v)}
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground">
                      {fpShowPw ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                    </button>
                  </div>
                  <button type="submit" disabled={loading}
                    className="flex w-full items-center justify-center gap-2 rounded-xl bg-foreground py-3 text-sm font-bold text-background disabled:opacity-50">
                    {loading && <Loader2 className="h-4 w-4 animate-spin" />} Set new password
                  </button>
                  <button type="button" onClick={() => setFpSent(false)} className="text-xs text-muted-foreground hover:text-foreground w-full text-center">
                    Didn&apos;t receive the code? Send again
                  </button>
                </form>
              )}
            </div>
          )}
        </div>

        <div className="text-center text-xs text-muted-foreground">
          <p>&copy; {new Date().getFullYear()} Icreateflow. All Rights Reserved.</p>
        </div>
      </div>

      {/* Right — Animated Visual */}
      <div className="hidden flex-1 items-center justify-center bg-[#ddd8f3] lg:flex relative overflow-hidden">
        {/* Floating decorative shapes */}
        <div className="absolute top-20 left-16 h-16 w-16 rounded-2xl bg-white/40 backdrop-blur-sm animate-float" />
        <div className="absolute bottom-32 right-20 h-12 w-12 rounded-full bg-white/30 backdrop-blur-sm animate-float-slow delay-500" />
        <div className="absolute top-1/4 right-16 h-8 w-8 rounded-lg bg-black/10 animate-float-reverse delay-300" />
        <div className="absolute bottom-1/4 left-24 h-10 w-10 rounded-full bg-black/5 animate-float delay-700" />

        {/* Main card */}
        <div className="relative z-10 animate-float-slow">
          <div className="w-80 rounded-2xl bg-white p-6 shadow-2xl shadow-black/10">
            <div className="mb-4 flex items-center gap-2">
              <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-black text-[10px] text-white font-bold">IC</div>
              <span className="text-sm font-bold text-black">Icreateflow</span>
            </div>
            <div className="mb-5 space-y-2.5">
              <div className="h-3 w-3/4 rounded-full bg-gray-200 animate-shimmer" />
              <div className="h-3 w-1/2 rounded-full bg-gray-100" />
              <div className="h-3 w-2/3 rounded-full bg-gray-200 animate-shimmer delay-300" />
            </div>
            <div className="grid grid-cols-3 gap-2">
              {[
                { n: "12", l: "Brands", icon: Layers, delay: "0s" },
                { n: "48", l: "Posts", icon: BarChart3, delay: "0.5s" },
                { n: "4", l: "Platforms", icon: Zap, delay: "1s" },
              ].map((s) => (
                <div key={s.l} className="rounded-xl bg-gray-900 p-3 text-center animate-scale-pulse" style={{ animationDelay: s.delay }}>
                  <s.icon className="mx-auto mb-1 h-3.5 w-3.5 text-gray-400" />
                  <p className="text-lg font-bold text-white">{s.n}</p>
                  <p className="text-[10px] text-gray-400">{s.l}</p>
                </div>
              ))}
            </div>
          </div>

          {/* Floating mini card */}
          <div className="absolute -bottom-6 -right-8 rounded-xl bg-white px-4 py-3 shadow-lg animate-float delay-1000">
            <div className="flex items-center gap-2">
              <div className="h-2 w-2 rounded-full bg-green-400 animate-pulse-soft" />
              <span className="text-xs font-semibold text-black">3 posts scheduled</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
