"use client";

/**
 * Light / dark for the auth pages. Writes the same `theme` key and `.dark`
 * class as the app's ThemeToggle, so the choice made here is the one the
 * app opens in after logging in.
 *
 * The current theme is read from the `<html>` class through
 * useSyncExternalStore rather than copied into state, so it cannot drift
 * from what is on screen and needs no effect to set itself on mount.
 */
import { useSyncExternalStore } from "react";
import { Moon, Sun } from "lucide-react";
import s from "./auth.module.css";

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
  const dark = useSyncExternalStore(
    subscribe,
    () => document.documentElement.classList.contains("dark"),
    () => null,
  );

  return (
    <div className={s.theme} role="group" aria-label="Colour theme">
      <span className={s.themeThumb} />
      <button type="button" aria-pressed={dark === false} aria-label="Light" onClick={() => setTheme(false)}>
        <Sun className="h-4 w-4" strokeWidth={1.9} />
      </button>
      <button type="button" aria-pressed={dark === true} aria-label="Dark" onClick={() => setTheme(true)}>
        <Moon className="h-4 w-4" strokeWidth={1.9} />
      </button>
    </div>
  );
}
