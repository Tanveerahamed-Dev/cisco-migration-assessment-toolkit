/**
 * ThemeToggle.tsx — dark / light / system, persisted, applied as `data-theme` on <html>.
 *
 * Three properties the implementation exists to guarantee:
 *
 *  1. "System" is not a third palette. It REMOVES `data-theme` entirely, because `tokens.css`
 *     keys its dark block on `prefers-color-scheme` when no attribute is present. Writing a
 *     resolved value instead would freeze the theme at the moment the page loaded, and a user who
 *     flips their OS to dark at dusk would sit in a light app until they reloaded.
 *  2. The preference survives a reload, and a browser that refuses storage does not break the
 *     control — it just stops remembering, loudly enough to be visible in the description.
 *  3. The control reports the EFFECTIVE theme, not only the preference, so "System" can say which
 *     way it currently resolves. That is why the media query is subscribed even though CSS does
 *     the actual work.
 *
 * The store is module-level rather than component state because the preference is a property of
 * the document, not of one React subtree: `Fabric3D` watches the same `data-theme` attribute, and
 * two sources of truth for one attribute is how a theme toggle ends up half-applied.
 */
import {
  useCallback,
  useEffect,
  useRef,
  useSyncExternalStore,
  type JSX,
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactElement,
} from "react";
import { IconMoon, IconSun, type IconProps } from "../ui/icons";
import "./chrome.css";

export type ThemePreference = "light" | "dark" | "system";
export type ResolvedTheme = "light" | "dark";

const STORAGE_KEY = "atlas-scope.theme";
const DARK_QUERY = "(prefers-color-scheme: dark)";

const isPreference = (v: unknown): v is ThemePreference =>
  v === "light" || v === "dark" || v === "system";

/**
 * Reading `localStorage` can THROW, not merely return null: a browser set to block site data
 * raises a SecurityError on access. Falling back to "system" is the honest default — it is what
 * the user already told their operating system.
 */
function readPreference(): ThemePreference {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    return isPreference(raw) ? raw : "system";
  } catch {
    return "system";
  }
}

function writePreference(p: ThemePreference): boolean {
  try {
    window.localStorage.setItem(STORAGE_KEY, p);
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

/* ── the preference store ──────────────────────────────────────────────────── */

let preference: ThemePreference = typeof window === "undefined" ? "system" : readPreference();
let persisted = true;
const listeners = new Set<() => void>();

/* Applied at module load, before the first React render, so an explicit override does not paint
   one frame of the OS theme first. `index.html` is frozen, so an inline pre-paint script is not
   available to us; this is the earliest point we own. */
applyTheme(preference);

export function setThemePreference(next: ThemePreference): void {
  preference = next;
  persisted = writePreference(next);
  applyTheme(next);
  for (const l of listeners) l();
}

export function useThemePreference(): ThemePreference {
  return useSyncExternalStore(
    (cb) => {
      listeners.add(cb);
      return () => listeners.delete(cb);
    },
    () => preference,
    () => "system",
  );
}

/* Not cached at module scope: `matchMedia` hands back a new MediaQueryList per call, so the
   subscription below closes over the exact object it registered on and its cleanup removes the
   listener it actually added. A cached instance would also pin whatever `matchMedia` existed at
   import time. */
const systemQuery = (): MediaQueryList | null =>
  typeof window === "undefined" || !window.matchMedia ? null : window.matchMedia(DARK_QUERY);

/** Live: an OS theme change mid-session moves this without a reload. */
export function useSystemPrefersDark(): boolean {
  return useSyncExternalStore(
    (cb) => {
      const mq = systemQuery();
      mq?.addEventListener("change", cb);
      return () => mq?.removeEventListener("change", cb);
    },
    () => systemQuery()?.matches ?? false,
    () => false,
  );
}

export const resolveTheme = (p: ThemePreference, systemDark: boolean): ResolvedTheme =>
  p === "system" ? (systemDark ? "dark" : "light") : p;

/* ── the control ───────────────────────────────────────────────────────────── */

/**
 * A half-filled disc: the "follow the system" option needs a silhouette of its own, distinct from
 * both the sun and the moon, so the three choices are separable without reading their labels.
 */
function IconSystem({ size = "1em", className }: IconProps): JSX.Element {
  return (
    <svg
      viewBox="0 0 16 16"
      width={size}
      height={size}
      className={className}
      aria-hidden="true"
      focusable="false"
    >
      <circle cx="8" cy="8" r="5.6" fill="none" stroke="currentColor" strokeWidth="1.6" />
      <path fill="currentColor" d="M8 2.4a5.6 5.6 0 0 1 0 11.2z" />
    </svg>
  );
}

interface Option {
  id: ThemePreference;
  label: string;
  Icon: (p: IconProps) => JSX.Element;
}

const OPTIONS: readonly Option[] = [
  { id: "light", label: "Light", Icon: IconSun },
  { id: "dark", label: "Dark", Icon: IconMoon },
  { id: "system", label: "System", Icon: IconSystem },
];

/**
 * `Cmd/Ctrl + \` (design brief §7.1), bound independently of the control.
 *
 * It is a hook rather than a prop on the toggle because at narrow viewports the control lives
 * inside a popover that is only mounted while it is open — binding the key to the component would
 * quietly remove the shortcut at exactly the width where reaching the control costs the most
 * taps. The frame calls this once; the component itself binds nothing by default, so one
 * keystroke can never reach two handlers.
 */
export function useThemeShortcut(enabled = true): void {
  const preferenceNow = useThemePreference();
  const systemDark = useSystemPrefersDark();
  const resolved = resolveTheme(preferenceNow, systemDark);

  useEffect(() => {
    if (!enabled) return;
    const onKey = (e: KeyboardEvent): void => {
      /* `defaultPrevented` is the cooperation protocol with every other global binding in the
         app: whoever handles a key first marks it, and nobody else acts on it. */
      if (e.defaultPrevented || e.key !== "\\" || !(e.ctrlKey || e.metaKey)) return;
      e.preventDefault();
      /* Toggling flips the EFFECTIVE theme, so the result is always the opposite of what is on
         screen. Cycling the three-way preference instead would make one keystroke a no-op
         whenever "system" already resolved to the theme it moved to. */
      setThemePreference(resolved === "dark" ? "light" : "dark");
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [enabled, resolved]);
}

export interface ThemeToggleProps {
  /** Bind `Cmd/Ctrl + \` from the component. Off by default: the frame owns the binding. */
  bindShortcut?: boolean;
  className?: string;
}

/**
 * An APG radio group, not three independent toggles: the three options are mutually exclusive, so
 * a group of `aria-pressed` buttons would let a screen reader report two of them as "pressed" for
 * the frame between writes, and would cost three tab stops instead of one.
 */
export function ThemeToggle({ bindShortcut = false, className }: ThemeToggleProps): ReactElement {
  const preferenceNow = useThemePreference();
  const systemDark = useSystemPrefersDark();
  const resolved = resolveTheme(preferenceNow, systemDark);
  const groupRef = useRef<HTMLDivElement>(null);

  const select = useCallback((p: ThemePreference) => setThemePreference(p), []);

  useThemeShortcut(bindShortcut);

  const onKeyDown = (e: ReactKeyboardEvent<HTMLDivElement>): void => {
    const step =
      e.key === "ArrowRight" || e.key === "ArrowDown"
        ? 1
        : e.key === "ArrowLeft" || e.key === "ArrowUp"
          ? -1
          : 0;
    if (step === 0) return;
    e.preventDefault();
    const at = OPTIONS.findIndex((o) => o.id === preferenceNow);
    const next = OPTIONS[(((at === -1 ? 0 : at) + step) % OPTIONS.length + OPTIONS.length) % OPTIONS.length];
    if (!next) return;
    select(next.id);
    const buttons = groupRef.current?.querySelectorAll<HTMLElement>('[role="radio"]');
    buttons?.[OPTIONS.indexOf(next)]?.focus();
  };

  return (
    <div
      ref={groupRef}
      role="radiogroup"
      aria-label="Colour theme"
      className={className ? `thm ${className}` : "thm"}
      onKeyDown={onKeyDown}
    >
      {OPTIONS.map(({ id, label, Icon }) => {
        const checked = id === preferenceNow;
        const name =
          id === "system"
            ? `System theme, currently ${resolved}${persisted ? "" : " — this choice cannot be stored by this browser"}`
            : `${label} theme${persisted ? "" : " — this choice cannot be stored by this browser"}`;
        return (
          <button
            key={id}
            type="button"
            role="radio"
            aria-checked={checked}
            aria-label={name}
            /* Roving tabindex: the group is one tab stop and the arrows move inside it. */
            tabIndex={checked ? 0 : -1}
            className="thm__opt"
            onClick={() => select(id)}
          >
            <Icon className="thm__glyph" />
          </button>
        );
      })}
    </div>
  );
}
