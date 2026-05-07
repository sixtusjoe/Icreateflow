"use client";

import { useState } from "react";
import { useAuth } from "@/lib/auth";
import { Save, Lock, Mail, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { updateProfile, changePassword, requestEmailChange, confirmEmailChange } from "@/lib/api";

export default function AccountPage() {
  const { user, updateUser } = useAuth();
  const [name, setName] = useState(user?.name || "");
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");

  // Email change state
  const [newEmail, setNewEmail] = useState("");
  const [emailOtp, setEmailOtp] = useState("");
  const [emailChangeSent, setEmailChangeSent] = useState(false);
  const [emailChangeBusy, setEmailChangeBusy] = useState(false);

  if (!user) return null;

  const handleSaveProfile = async () => {
    try {
      const updated = await updateProfile({ name });
      updateUser(updated);
      toast.success("Profile updated");
    } catch (err: any) {
      toast.error(err.response?.data?.detail || "Failed");
    }
  };

  const handleChangePassword = async () => {
    if (newPassword !== confirmPassword) { toast.error("Passwords do not match"); return; }
    try {
      await changePassword(currentPassword, newPassword);
      toast.success("Password changed");
      setCurrentPassword(""); setNewPassword(""); setConfirmPassword("");
    } catch (err: any) {
      toast.error(err.response?.data?.detail || "Failed");
    }
  };

  const handleRequestEmailChange = async () => {
    if (!newEmail) { toast.error("Enter a new email address"); return; }
    setEmailChangeBusy(true);
    try {
      await requestEmailChange(newEmail);
      setEmailChangeSent(true);
      toast.success("Verification code sent to your new email");
    } catch (err: any) {
      toast.error(err.response?.data?.detail || "Failed to send code");
    } finally { setEmailChangeBusy(false); }
  };

  const handleConfirmEmailChange = async () => {
    if (!emailOtp) { toast.error("Enter the verification code"); return; }
    setEmailChangeBusy(true);
    try {
      await confirmEmailChange(emailOtp);
      updateUser({ ...user, email: newEmail });
      toast.success("Email updated successfully");
      setNewEmail(""); setEmailOtp(""); setEmailChangeSent(false);
    } catch (err: any) {
      toast.error(err.response?.data?.detail || "Invalid or expired code");
    } finally { setEmailChangeBusy(false); }
  };

  return (
    <div className="mx-auto max-w-2xl">
      <div className="mb-6 md:mb-8">
        <h1 className="text-xl md:text-2xl font-bold tracking-tight">My Account</h1>
        <p className="mt-1 text-sm text-muted-foreground">Manage your profile and security settings.</p>
      </div>

      <div className="mb-6 rounded-2xl bg-card p-4 md:p-6">
        <h2 className="mb-5 text-base font-semibold">Profile</h2>
        <div className="space-y-4">
          <div>
            <label className="mb-1.5 block text-sm font-medium">Full Name</label>
            <input value={name} onChange={(e) => setName(e.target.value)}
              className="min-h-[44px] w-full rounded-lg border border-border bg-background px-4 py-2.5 text-base sm:text-sm outline-none focus:border-foreground" />
          </div>
          <div>
            <label className="mb-1.5 block text-sm font-medium">Email</label>
            <p className="text-sm text-muted-foreground mb-3">{user.email}</p>
            <div className="rounded-lg border border-border bg-background/50 p-4 space-y-3">
              <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide flex items-center gap-1.5">
                <Mail className="h-3 w-3" /> Change Email
              </p>
              {!emailChangeSent ? (
                <div className="flex gap-2">
                  <input type="email" value={newEmail} onChange={(e) => setNewEmail(e.target.value)}
                    placeholder="New email address"
                    className="min-h-[40px] flex-1 rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none focus:border-foreground" />
                  <button onClick={handleRequestEmailChange} disabled={emailChangeBusy}
                    className="inline-flex min-h-[40px] items-center gap-1.5 rounded-lg bg-foreground px-4 text-sm font-medium text-background transition-opacity hover:opacity-90 disabled:opacity-50">
                    {emailChangeBusy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Mail className="h-3.5 w-3.5" />}
                    Send Code
                  </button>
                </div>
              ) : (
                <div className="space-y-2">
                  <p className="text-xs text-muted-foreground">Enter the 6-digit code sent to <strong>{newEmail}</strong></p>
                  <div className="flex gap-2">
                    <input type="text" value={emailOtp} onChange={(e) => setEmailOtp(e.target.value)}
                      placeholder="000000" maxLength={6}
                      className="min-h-[40px] w-32 rounded-lg border border-border bg-background px-3 py-2 text-sm text-center tracking-widest font-mono outline-none focus:border-foreground" />
                    <button onClick={handleConfirmEmailChange} disabled={emailChangeBusy}
                      className="inline-flex min-h-[40px] items-center gap-1.5 rounded-lg bg-foreground px-4 text-sm font-medium text-background transition-opacity hover:opacity-90 disabled:opacity-50">
                      {emailChangeBusy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
                      Confirm
                    </button>
                    <button onClick={() => { setEmailChangeSent(false); setEmailOtp(""); }} type="button"
                      className="text-sm text-muted-foreground hover:text-foreground">
                      Cancel
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2 sm:gap-3">
            <span className="rounded-md bg-foreground px-2 py-0.5 text-xs font-medium text-background capitalize">{user.role}</span>
            <span className="text-xs text-muted-foreground">Joined {new Date(user.created_at).toLocaleDateString()}</span>
          </div>
          <button onClick={handleSaveProfile}
            className="inline-flex min-h-[44px] items-center justify-center gap-2 rounded-lg bg-foreground px-5 py-2.5 text-sm font-medium text-background transition-opacity hover:opacity-90">
            <Save className="h-4 w-4" /> Save Profile
          </button>
        </div>
      </div>

      <div className="rounded-2xl bg-card p-4 md:p-6">
        <h2 className="mb-5 flex items-center gap-2 text-base font-semibold">
          <Lock className="h-4 w-4 text-muted-foreground" /> Change Password
        </h2>
        <div className="space-y-4">
          <div>
            <label className="mb-1.5 block text-sm font-medium">Current Password</label>
            <input type="password" value={currentPassword} onChange={(e) => setCurrentPassword(e.target.value)}
              className="min-h-[44px] w-full rounded-lg border border-border bg-background px-4 py-2.5 text-base sm:text-sm outline-none focus:border-foreground" />
          </div>
          <div>
            <label className="mb-1.5 block text-sm font-medium">New Password</label>
            <input type="password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)}
              className="min-h-[44px] w-full rounded-lg border border-border bg-background px-4 py-2.5 text-base sm:text-sm outline-none focus:border-foreground" placeholder="At least 6 characters" />
          </div>
          <div>
            <label className="mb-1.5 block text-sm font-medium">Confirm New Password</label>
            <input type="password" value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)}
              className="min-h-[44px] w-full rounded-lg border border-border bg-background px-4 py-2.5 text-base sm:text-sm outline-none focus:border-foreground" />
          </div>
          <button onClick={handleChangePassword}
            className="inline-flex min-h-[44px] items-center justify-center gap-2 rounded-lg bg-foreground px-5 py-2.5 text-sm font-medium text-background transition-opacity hover:opacity-90">
            <Lock className="h-4 w-4" /> Update Password
          </button>
        </div>
      </div>
    </div>
  );
}
