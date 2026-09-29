/**
 * The two helpers the outreach pages share that are not components.
 *
 * They used to live in `app/outreach/ui.tsx` alongside a set of widgets —
 * `Modal`, `Panel`, `StatusPill`, `Toggle`, `Select`, `ProgressBar` — that
 * the redesign replaced with the components in `kit.tsx` and `dialog.tsx`.
 * Keeping the file for two pure functions would have kept the widgets
 * alive too, so the functions moved and the file went.
 */

/** "3m ago", falling back to a date once it is no longer a useful distance. */
export function relativeTime(value: string | null | undefined): string {
  if (!value) return "—";
  const then = new Date(value).getTime();
  if (Number.isNaN(then)) return "—";
  const seconds = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return new Date(value).toLocaleDateString();
}

/** What the server said went wrong, or the caller's fallback. */
export function apiErrorMessage(error: unknown, fallback: string): string {
  const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  if (typeof detail === "string") return detail;
  // The start/resume preflight returns {"errors": [...]}.
  const errors = (detail as { errors?: string[] })?.errors;
  if (Array.isArray(errors) && errors.length) return errors.join(" · ");
  return fallback;
}
