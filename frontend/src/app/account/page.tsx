"use client";

import { useState } from "react";
import { useAuth } from "@/lib/auth";
import { Save, Lock } from "lucide-react";
import { toast } from "sonner";
import { updateProfile, changePassword } from "@/lib/api";

export default function AccountPage() {
  const { user, updateUser } = useAuth();
  const [name, setName] = useState(user?.name || "");
  const [email, setEmail] = useState(user?.email || "");
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");

  if (!user) return null;

  const handleSaveProfile = async () => {
    try {
      const updated = await updateProfile({ name, email });
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
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)}
              className="min-h-[44px] w-full rounded-lg border border-border bg-background px-4 py-2.5 text-base sm:text-sm outline-none focus:border-foreground" />
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
