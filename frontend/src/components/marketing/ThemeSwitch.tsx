"use client";

/**
 * Light / dark on the public pages. Same key and class as the app's
 * ThemeToggle and the auth pages' switch, so the choice follows the visitor
 * into the app. The current theme is read from <html> rather than copied
 * into state, so it cannot drift from what is on screen.
 */
import { useSyncExternalStore } from "react";

function subscribe(onChange: () => void) {
  const mo = new MutationObserver(onChange);
  mo.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
  return () => mo.disconnect();
}

function setTheme(dark: boolean) {
  document.documentElement.classList.toggle("dark", dark);
  try {
    localStorage.setItem("theme", dark ? "dark" : "light");
  } catch {
    // Storage blocked: the switch still works for this visit.
  }
}

export default function ThemeSwitch() {
  const dark = useSyncExternalStore(subscribe, () => document.documentElement.classList.contains("dark"), () => null);
  return (
    <div className="ts" role="group" aria-label="Colour theme">
      <span className="th" />
      <button type="button" aria-pressed={dark === false} aria-label="Light" onClick={() => setTheme(false)}>
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></svg>
      </button>
      <button type="button" aria-pressed={dark === true} aria-label="Dark" onClick={() => setTheme(true)}>
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" /></svg>
      </button>
    </div>
  );
}
