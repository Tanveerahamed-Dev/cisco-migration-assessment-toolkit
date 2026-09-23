/**
 * theme-preference.ts — the ONE reader and writer of the stored theme preference, and the one place
 * that turns a preference into the `data-theme` attribute on <html>.
 *
 * It is a separate module, with no imports at all, because two callers need it at very different
 * moments:
 *
 *   - `src/main.tsx`, the entry, applies an explicit stored preference BEFORE the boot line can
 *     paint. The entry is deliberately tiny (acceptance E5: it waits for the boot line to be painted
 *     before importing the application), so it must not pull React or ThemeToggle's control and
 *     stylesheet into the entry chunk just to read one localStorage key.
 *   - `ThemeToggle.tsx`, the control, which reads, writes and re-applies the same preference.
 *
 * Two copies of the storage key or of the "system = no attribute" rule is how the entry and the
 * control come to disagree about which theme the reader asked for. The ONE sanctioned restatement is
 * index.html's inline <head> script, which must run during parsing and so cannot import this module;
 * src/app/theme-boot.test.ts executes it beside `applyTheme(readThemePreference())` over the same
 * storage states and fails on any difference.
 *
 * THE RULE THIS MODULE EXISTS TO KEEP: "system" is not a third palette. It REMOVES `data-theme`,
 * because tokens.css keys its dark block on `prefers-color-scheme` when no attribute is present.
 * No page may therefore ship a hard-coded `data-theme` in its HTML: measured (C4, 2026-09-22) with
 * `<html data-theme="dark">` in index.html, a light-OS reader with no stored preference got a dark
 * boot line (`rgb(8, 10, 14)` at its first paint, t=36 ms) for ~190-330 ms before the application
 * loaded and removed the attribute. `src/app/theme-boot.test.ts` pins both halves.
 */

export type ThemePreference = "light" | "dark" | "system";

export const THEME_STORAGE_KEY = "atlas-scope.theme";

export const isThemePreference = (v: unknown): v is ThemePreference =>
  v === "light" || v === "dark" || v === "system";

/**
 * Reading `localStorage` can THROW, not merely return null: a browser set to block site data
 * raises a SecurityError on access. Falling back to "system" is the honest default — it is what
 * the user already told their operating system.
 */
export function readThemePreference(): ThemePreference {
  try {
    const raw = window.localStorage.getItem(THEME_STORAGE_KEY);
    return isThemePreference(raw) ? raw : "system";
  } catch {
    return "system";
  }
}

/** False when the browser refused to store it; the control says so rather than pretending. */
export function writeThemePreference(p: ThemePreference): boolean {
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, p);
    return true;
  } catch {
    return false;
  }
}

export function applyTheme(p: ThemePreference): void {
  if (typeof document === "undefined") return;
  const root = document.documentElement;
  if (p === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", p);
}
