"use client";

/**
 * OAuth popup-landing page.
 * The backend /api/oauth/{platform}/callback already returns an HTML page
 * that posts a message + closes itself. This route exists only as a
 * fallback in case we ever redirect to the frontend instead of the API.
 */
import { useEffect } from "react";

export default function OAuthCallbackPage() {
  useEffect(() => {
    try {
      const params = new URLSearchParams(window.location.search);
      const status = params.get("status") || (params.get("error") ? "error" : "success");
      const message = params.get("message") || params.get("error") || "";
      window.opener?.postMessage({ type: "oauth", status, message }, "*");
    } catch {}
    const t = setTimeout(() => { try { window.close(); } catch {} }, 600);
    return () => clearTimeout(t);
  }, []);
  return (
    <div className="flex min-h-screen items-center justify-center bg-background text-foreground">
      <div className="text-center">
        <h2 className="text-lg font-bold">Connecting…</h2>
        <p className="mt-1 text-sm text-muted-foreground">You can close this window.</p>
      </div>
    </div>
  );
}
