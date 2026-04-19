"use client";

import { useState } from "react";
import Link from "next/link";
import { useAuth } from "@/lib/auth";
import { Loader2, UserPlus, LogIn, Check } from "lucide-react";
import ThemeToggle from "@/components/ThemeToggle";

export default function RegisterPage() {
  const { register } = useAuth();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    if (password !== confirmPassword) { setError("Passwords do not match"); return; }
    if (password.length < 6) { setError("Password must be at least 6 characters"); return; }
    setLoading(true);
    try { await register(email, password, name); }
    catch (err: any) { setError(err.message || "Registration failed"); }
    finally { setLoading(false); }
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
            <Link href="/login" className="flex flex-1 items-center justify-center gap-2 py-3 text-sm font-medium text-muted-foreground hover:text-foreground transition-colors">
              <LogIn className="h-4 w-4" />
              Log In
            </Link>
            <div className="flex flex-1 items-center justify-center gap-2 bg-foreground py-3 text-sm font-semibold text-background">
              <UserPlus className="h-4 w-4" />
              Sign Up
            </div>
          </div>

          <h1 className="mb-1 text-xl font-bold tracking-tight text-foreground">Create your account</h1>
          <p className="mb-6 text-sm text-muted-foreground">Free forever. Scale your content across platforms.</p>

          <form onSubmit={handleSubmit} className="space-y-4">
            {error && (
              <div className="rounded-lg border border-red-300 bg-red-50 px-4 py-2.5 text-sm text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-400">
                {error}
              </div>
            )}

            <div>
              <label className="mb-1.5 block text-sm font-semibold text-foreground">Full Name</label>
              <input type="text" value={name} onChange={(e) => setName(e.target.value)} required autoFocus placeholder="Your name"
                className="w-full rounded-xl border border-border bg-background px-4 py-3 text-sm text-foreground outline-none transition-colors focus:border-foreground placeholder:text-muted-foreground" />
            </div>

            <div>
              <label className="mb-1.5 block text-sm font-semibold text-foreground">Email</label>
              <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required placeholder="Work Email"
                className="w-full rounded-xl border border-border bg-background px-4 py-3 text-sm text-foreground outline-none transition-colors focus:border-foreground placeholder:text-muted-foreground" />
            </div>

            <div>
              <label className="mb-1.5 block text-sm font-semibold text-foreground">Password</label>
              <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required placeholder="At least 6 characters"
                className="w-full rounded-xl border border-border bg-background px-4 py-3 text-sm text-foreground outline-none transition-colors focus:border-foreground placeholder:text-muted-foreground" />
            </div>

            <div>
              <label className="mb-1.5 block text-sm font-semibold text-foreground">Confirm Password</label>
              <input type="password" value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} required placeholder="Repeat your password"
                className="w-full rounded-xl border border-border bg-background px-4 py-3 text-sm text-foreground outline-none transition-colors focus:border-foreground placeholder:text-muted-foreground" />
            </div>

            <button type="submit" disabled={loading}
              className="flex w-full items-center justify-center gap-2 rounded-xl bg-lime py-3 text-sm font-bold text-black transition-all hover:brightness-95 disabled:opacity-50">
              {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <UserPlus className="h-4 w-4" />}
              Sign up for free
            </button>
          </form>

          <p className="mt-5 text-center text-sm text-muted-foreground">
            Already have an account?{" "}
            <Link href="/login" className="font-semibold text-foreground hover:underline">Log in</Link>
          </p>
        </div>

        <div className="text-center text-xs text-muted-foreground">
          <p>&copy; {new Date().getFullYear()} Icreateflow. All Rights Reserved.</p>
        </div>
      </div>

      {/* Right — Animated Visual */}
      <div className="hidden flex-1 items-center justify-center bg-[#ddd8f3] lg:flex relative overflow-hidden">
        {/* Floating shapes */}
        <div className="absolute top-16 right-24 h-14 w-14 rounded-2xl bg-white/40 backdrop-blur-sm animate-float delay-200" />
        <div className="absolute bottom-24 left-16 h-10 w-10 rounded-full bg-white/30 backdrop-blur-sm animate-float-slow" />
        <div className="absolute top-1/3 left-20 h-6 w-6 rounded-lg bg-black/10 animate-float-reverse delay-500" />

        <div className="relative z-10 text-center animate-float-slow">
          {/* Big number */}
          <p className="text-8xl font-black tracking-tighter text-black/90 animate-scale-pulse">800+</p>
          <p className="mt-3 max-w-xs text-base font-medium text-black/60">
            Content creators use Icreateflow to scale, automate, and post content faster.
          </p>

          {/* Feature pills */}
          <div className="mt-8 flex flex-wrap justify-center gap-2">
            {["Multi-Brand", "AI Variations", "Auto-Schedule", "4 Platforms"].map((f, i) => (
              <span key={f} className="inline-flex items-center gap-1.5 rounded-full bg-white/70 backdrop-blur-sm px-4 py-2 text-xs font-semibold text-black shadow-sm animate-slide-up" style={{ animationDelay: `${0.3 + i * 0.15}s` }}>
                <Check className="h-3 w-3 text-green-600" />
                {f}
              </span>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
