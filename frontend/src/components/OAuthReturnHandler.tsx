"use client";

import { useEffect } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { toast } from "sonner";

/**
 * Mounted once at the app shell level. When the standalone-IG redirect
 * flow returns to the page (?oauth_status=success|error&oauth_platform=...
 * &oauth_message=...), this:
 *
 *   1. shows the appropriate toast,
 *   2. strips the oauth_* params from the URL so a refresh doesn't re-fire
 *      the toast,
 *   3. dispatches a window CustomEvent("oauth-returned", { detail }) that
 *      OAuthTiles listens for to refetch account state.
 *
 * The popup flow doesn't go through this — it postMessages directly back
 * to OAuthTiles. Only the redirect flow (used by standalone IG, and any
 * future provider that can't postMessage from a popup) lands here.
 */
export default function OAuthReturnHandler() {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    const status = params.get("oauth_status");
    if (!status) return;
    const platform = params.get("oauth_platform") || "";
    const message = params.get("oauth_message") || "";
    const platformLabel =
      platform === "instagram" ? "Instagram"
        : platform === "meta" ? "Facebook"
        : platform === "youtube" ? "YouTube"
        : platform === "tiktok" ? "TikTok"
        : platform || "Account";

    if (status === "success") {
      toast.success(`${platformLabel} connected`);
    } else {
      toast.error(message || `${platformLabel} connection failed`);
    }

    window.dispatchEvent(
      new CustomEvent("oauth-returned", { detail: { status, platform, message } }),
    );

    const next = new URLSearchParams(params.toString());
    next.delete("oauth_status");
    next.delete("oauth_platform");
    next.delete("oauth_message");
    const qs = next.toString();
    router.replace(qs ? `${pathname}?${qs}` : pathname);
  }, [params, router, pathname]);

  return null;
}
