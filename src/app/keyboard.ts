/**
 * keyboard.ts — one global keyboard manager, and the single registry every shortcut lives in.
 *
 * Four properties the rest of the app depends on:
 *
 *  1. ONE LISTENER, ONE REGISTRY. Surfaces register bindings; they do not attach their own
 *     document listeners. Two listeners racing for `f` is how a dense tool ends up with a key
 *     that works on Tuesday: the winner depends on mount order, which depends on layout.
 *  2. SCOPE, NOT LUCK. A binding declares the surface it belongs to (`grid`, `fabric`, `dialog`)
 *     and only fires while focus is inside a region that declares that scope via
 *     `data-kb-scope`. `global` fires anywhere. While a modal owns focus, nothing behind it runs.
 *  3. TEXT INPUT IS SACRED. A single unmodified key never reaches a binding while the user is
 *     typing. The only exceptions are declared per binding AND structurally checked here
 *     (`allowInInput` is honoured only for a chord carrying a modifier, or for Escape) — a
 *     mis-declared `f` that fires inside a search box makes the whole app feel broken, and it is
 *     the kind of defect that survives review because the author never typed an `f`.
 *  4. THE HELP SCREEN IS GENERATED. `shortcuts()` is the registry; ShortcutHelp renders it. A
 *     hand-maintained key list rots the first time somebody adds a binding, and then the product
 *     is lying about itself in the one place a user goes when lost.
 *
 * Determinism: no Math.random, no Date.now on any path that affects what is drawn. The sequence
 * timeout uses setTimeout, which schedules — it does not read a clock into rendered output.
 */
import { useEffect, useSyncExternalStore } from "react";
import { recordReturn, returnFocus, type ReturnRecord } from "./focus-return";

/* ══ types ═════════════════════════════════════════════════════════════════ */

export type ShortcutScope = "global" | "grid" | "fabric" | "dialog";

export const SCOPE_LABEL: Readonly<Record<ShortcutScope, string>> = {
  global: "Anywhere",
  grid: "Findings grid",
  fabric: "3-D fabric",
  dialog: "Dialogs and overlays",
};

/** Scope order for the help sheet: broadest first, so the keys that always work read first. */
export const SCOPE_ORDER: readonly ShortcutScope[] = ["global", "grid", "fabric", "dialog"];

export interface Shortcut {
  /** Stable id, e.g. `palette.open`. Used for conflict reporting and for tests. */
  id: string;
  /**
   * Canonical spec. Space separates the steps of a SEQUENCE (`g f`); `+` separates the modifiers
   * of one chord (`mod+k`). `mod` is Cmd on macOS and Ctrl elsewhere — resolved at match time
   * from the platform, never written into the spec.
   */
  keys: string;
  scope: ShortcutScope;
  /** Imperative phrase, e.g. "Go to the fabric". This is what the help sheet shows. */
  label: string;
  /** Grouping inside a scope on the help sheet. */
  group: string;
  run: (e: KeyboardEvent) => void;
  /** Permitted while focus is in a text field. Structurally limited — see `safeInTextEntry`. */
  allowInInput?: boolean;
  /** Defaults to true. Set false for a binding that must not suppress the browser's own key. */
  preventDefault?: boolean;
  /** Hard gate: false means the binding does not exist right now and does not match. */
  when?: () => boolean;
  /**
   * Soft gate: a sentence explaining why the binding cannot act right now. The binding still
   * matches and still appears on the help sheet carrying its reason — a shortcut that silently
   * vanishes teaches the user it was never real.
   */
  unavailable?: () => string | null;
}

interface Chord {
  key: string;
  /** Cmd on macOS, Ctrl elsewhere. */
  mod: boolean;
  ctrl: boolean;
  meta: boolean;
  alt: boolean;
  shift: boolean;
}

/* ══ platform ══════════════════════════════════════════════════════════════ */

interface UserAgentDataLike {
  platform?: string;
}

/**
 * Detected, never assumed. Read on demand rather than cached at module load: the manager is
 * imported before anything renders, and a cached probe taken at import time is exactly the kind
 * of value a test (or a platform-emulating browser tool) cannot correct afterwards.
 */
export function isMacPlatform(): boolean {
  if (typeof navigator === "undefined") return false;
  const nav = navigator as Navigator & { userAgentData?: UserAgentDataLike };
  const declared = nav.userAgentData?.platform ?? nav.platform ?? "";
  if (declared !== "") return /mac|iphone|ipad|ipod/i.test(declared);
  return /mac os x|iphone|ipad|ipod/i.test(nav.userAgent ?? "");
}

/* ══ spec parsing ══════════════════════════════════════════════════════════ */

const KEY_ALIAS: Readonly<Record<string, string>> = {
  esc: "escape",
  return: "enter",
  space: " ",
  spacebar: " ",
  up: "arrowup",
  down: "arrowdown",
  left: "arrowleft",
  right: "arrowright",
  pageup: "pageup",
  pagedown: "pagedown",
};

const normalizeKeyName = (raw: string): string => {
  const k = raw.trim().toLowerCase();
  return KEY_ALIAS[k] ?? k;
};

/** A printable single character, i.e. something a text field would have received. */
const isPrintable = (key: string): boolean => key.length === 1;

/** `?`, `[`, `\` … — keys whose glyph already implies whatever shift state produced it. */
const isSymbol = (key: string): boolean => key.length === 1 && !/[a-z0-9]/.test(key);

function parseChord(token: string): Chord {
  const chord: Chord = { key: "", mod: false, ctrl: false, meta: false, alt: false, shift: false };
  // `+` is itself a legal key, so a token that IS a plus, or ends with one, keeps it as the key
  // rather than splitting into an empty tail.
  const parts = token === "+" ? ["+"] : token.split("+").map((p) => (p === "" ? "+" : p));
  for (let i = 0; i < parts.length; i++) {
    const raw = (parts[i] ?? "").toLowerCase();
    const last = i === parts.length - 1;
    if (!last || raw === "") {
      if (raw === "mod") chord.mod = true;
      else if (raw === "ctrl" || raw === "control") chord.ctrl = true;
      else if (raw === "cmd" || raw === "meta" || raw === "win") chord.meta = true;
      else if (raw === "alt" || raw === "option" || raw === "opt") chord.alt = true;
      else if (raw === "shift") chord.shift = true;
      continue;
    }
    chord.key = normalizeKeyName(raw);
  }
  return chord;
}

const specCache = new Map<string, readonly Chord[]>();

/** Parse a spec into its sequence of chords. Cached: the handler parses on every keystroke. */
export function parseSpec(keys: string): readonly Chord[] {
  const hit = specCache.get(keys);
  if (hit) return hit;
  const chords = keys
    .trim()
    .split(/\s+/)
    .filter((t) => t !== "")
    .map(parseChord);
  specCache.set(keys, chords);
  return chords;
}

const sameChord = (a: Chord, b: Chord): boolean =>
  a.key === b.key &&
  a.mod === b.mod &&
  a.ctrl === b.ctrl &&
  a.meta === b.meta &&
  a.alt === b.alt &&
  a.shift === b.shift;

/** Normalized event key: `ArrowUp` → `arrowup`, `K` → `k`, `?` → `?`. */
const eventKey = (e: KeyboardEvent): string => (e.key === " " ? " " : e.key.toLowerCase());

function matchChord(c: Chord, e: KeyboardEvent): boolean {
  const mac = isMacPlatform();
  const modDown = mac ? e.metaKey : e.ctrlKey;
  const otherModDown = mac ? e.ctrlKey : e.metaKey;
  if (c.mod) {
    // Ctrl+Cmd+K is not Cmd+K: a chord with an extra platform modifier is a different chord, and
    // treating it as a match steals a key combination the OS or the browser may own.
    if (!modDown || otherModDown) return false;
  } else if (e.ctrlKey !== c.ctrl || e.metaKey !== c.meta) {
    return false;
  }
  if (e.altKey !== c.alt) return false;
  // Shift is part of producing `?` on most layouts, so comparing it would make the binding
  // layout-dependent. For letters and digits it is compared exactly: `v` and `shift+v` differ.
  if (!isSymbol(c.key) && e.shiftKey !== c.shift) return false;
  return eventKey(e) === c.key;
}

/**
 * A binding may only claim `allowInInput` when every one of its chords carries a modifier or is
 * Escape. This is checked, not trusted: it is the structural form of "typing must never trigger
 * a command", and the check is what makes that true for bindings this file never saw.
 */
const safeInTextEntry = (keys: string): boolean =>
  parseSpec(keys).every(
    (c) => c.mod || c.ctrl || c.meta || c.alt || !isPrintable(c.key) || c.key === "escape",
  );

/**
 * WCAG 2.1.4 Character Key Shortcuts: a binding is a CHARACTER-KEY binding when any step of it is
 * a printable character pressed without Ctrl, Alt, Cmd or the platform modifier (Shift does not
 * count — `?` and `Shift+V` are still typed characters). A sequence such as `g f` qualifies on its
 * first step. Derived from the spec, never listed: a binding added next month is covered too.
 */
export const isCharacterKeyBinding = (keys: string): boolean =>
  parseSpec(keys).some((c) => !c.mod && !c.ctrl && !c.meta && !c.alt && isPrintable(c.key));

/* ══ the character-key setting (WCAG 2.1.4) ════════════════════════════════
   The mechanism that lets a user turn every single-character binding off. Speech-input users and
   anyone who brushes the keyboard otherwise fire commands with stray characters. Off, every such
   binding stops matching — enforced in `eligible`, so it covers the whole class rather than a list
   — and each verb stays reachable from the command palette (Ctrl/Cmd+K) and its on-screen control.
   A per-viewer preference: it lives in localStorage, never in the investigation URL. */

const CHARACTER_KEYS_STORAGE = "atlas-scope.characterKeyShortcuts";

function readCharacterKeys(): boolean {
  try {
    return typeof window === "undefined" || window.localStorage.getItem(CHARACTER_KEYS_STORAGE) !== "off";
  } catch {
    return true;
  }
}

let characterKeysOn = readCharacterKeys();
const characterKeyListeners = new Set<() => void>();

export function setCharacterKeyShortcuts(on: boolean): void {
  if (characterKeysOn === on) return;
  characterKeysOn = on;
  try {
    window.localStorage.setItem(CHARACTER_KEYS_STORAGE, on ? "on" : "off");
  } catch {
    /* Site data blocked: the choice still holds for this session. */
  }
  if (!on) setPending([]);
  for (const l of characterKeyListeners) l();
}

export const characterKeyShortcutsEnabled = (): boolean => characterKeysOn;

export function useCharacterKeyShortcuts(): boolean {
  return useSyncExternalStore(
    (cb) => {
      characterKeyListeners.add(cb);
      return () => characterKeyListeners.delete(cb);
    },
    () => characterKeysOn,
    () => true,
  );
}

/* ══ display ═══════════════════════════════════════════════════════════════ */

export interface ShortcutToken {
  text: string;
  /** `then` is the separator between the steps of a sequence, not a key to press. */
  kind: "key" | "then";
}

const MAC_MOD: Readonly<Record<string, string>> = {
  mod: "⌘",
  ctrl: "⌃",
  alt: "⌥",
  shift: "⇧",
};
const PC_MOD: Readonly<Record<string, string>> = {
  mod: "Ctrl",
  ctrl: "Ctrl",
  alt: "Alt",
  shift: "Shift",
};

const KEY_DISPLAY: Readonly<Record<string, string>> = {
  escape: "Esc",
  enter: "Enter",
  arrowup: "↑",
  arrowdown: "↓",
  arrowleft: "←",
  arrowright: "→",
  pageup: "PgUp",
  pagedown: "PgDn",
  " ": "Space",
  backspace: "Backspace",
  tab: "Tab",
  home: "Home",
  end: "End",
};

const displayKey = (key: string): string =>
  KEY_DISPLAY[key] ?? (key.length === 1 ? key.toUpperCase() : key.charAt(0).toUpperCase() + key.slice(1));

/** Render tokens for one chord, platform-correct. */
export function formatChord(c: Chord): ShortcutToken[] {
  const table = isMacPlatform() ? MAC_MOD : PC_MOD;
  const out: ShortcutToken[] = [];
  if (c.ctrl && !c.mod) out.push({ text: table.ctrl ?? "Ctrl", kind: "key" });
  if (c.mod) out.push({ text: table.mod ?? "Ctrl", kind: "key" });
  if (c.alt) out.push({ text: table.alt ?? "Alt", kind: "key" });
  if (c.shift) out.push({ text: table.shift ?? "Shift", kind: "key" });
  if (c.meta && !c.mod) out.push({ text: isMacPlatform() ? "⌘" : "Win", kind: "key" });
  out.push({ text: displayKey(c.key), kind: "key" });
  return out;
}

/** Render tokens for a whole spec, with `then` between the steps of a sequence. */
export function formatShortcut(keys: string): ShortcutToken[] {
  const chords = parseSpec(keys);
  const out: ShortcutToken[] = [];
  chords.forEach((c, i) => {
    if (i > 0) out.push({ text: "then", kind: "then" });
    out.push(...formatChord(c));
  });
  return out;
}

/** Flat text form, for an accessible name or a palette row: "Ctrl K", "G then F". */
export const shortcutText = (keys: string): string =>
  formatShortcut(keys)
    .map((t) => t.text)
    .join(" ");

/* ══ focus context ═════════════════════════════════════════════════════════ */

const TEXT_INPUT_TYPES = new Set([
  "text",
  "search",
  "email",
  "url",
  "tel",
  "password",
  "number",
  "date",
  "time",
  "datetime-local",
  "month",
  "week",
]);

/** True when a key would otherwise be typed into something. */
export function isTextEntry(el: Element | null | undefined): boolean {
  if (!el) return false;
  const tag = el.tagName;
  if (tag === "TEXTAREA" || tag === "SELECT") return true;
  if (tag === "INPUT") {
    const type = (el.getAttribute("type") ?? "text").toLowerCase();
    return TEXT_INPUT_TYPES.has(type);
  }
  if (el instanceof HTMLElement && el.isContentEditable) return true;
  const role = el.getAttribute("role");
  return role === "textbox" || role === "searchbox" || role === "combobox";
}

/**
 * Which scope owns the keyboard right now. A modal wins outright; otherwise the nearest ancestor
 * declaring `data-kb-scope`. Everything else is `global`.
 */
export function activeScope(el: Element | null | undefined): ShortcutScope {
  if (!el) return "global";
  if (el.closest('[role="dialog"][aria-modal="true"]')) return "dialog";
  const declared = el.closest("[data-kb-scope]")?.getAttribute("data-kb-scope");
  return declared === "grid" || declared === "fabric" || declared === "dialog" ? declared : "global";
}

/* ══ registry ══════════════════════════════════════════════════════════════ */

let registry: readonly Shortcut[] = [];
const registryListeners = new Set<() => void>();

const emitRegistry = (): void => {
  for (const l of registryListeners) l();
};

/** Register a batch. Returns the un-registration; call it on unmount. */
export function registerShortcuts(list: readonly Shortcut[]): () => void {
  const added = [...list];
  registry = [...registry, ...added];
  emitRegistry();
  return () => {
    registry = registry.filter((s) => !added.includes(s));
    emitRegistry();
  };
}

export const shortcuts = (): readonly Shortcut[] => registry;

export function useShortcuts(): readonly Shortcut[] {
  return useSyncExternalStore(
    (cb) => {
      registryListeners.add(cb);
      return () => registryListeners.delete(cb);
    },
    shortcuts,
    shortcuts,
  );
}

export type ConflictKind = "duplicate" | "sequence-prefix" | "unsafe-in-input";

export interface ShortcutConflict {
  kind: ConflictKind;
  keys: string;
  ids: string[];
  reason: string;
}

const overlap = (a: ShortcutScope, b: ShortcutScope): boolean =>
  a === b || a === "global" || b === "global";

/**
 * Collisions are REPORTED, never silently resolved. Two bindings on one key in overlapping scopes
 * means one of them is dead, and which one depends on registration order — a defect that presents
 * as "that shortcut stopped working" weeks later. ShortcutHelp renders this list when it is
 * non-empty, so the product tells on itself rather than shipping a lie about its own keys.
 */
export function shortcutConflicts(list: readonly Shortcut[] = registry): ShortcutConflict[] {
  const out: ShortcutConflict[] = [];
  const specs = list.map((s) => ({ s, chords: parseSpec(s.keys) }));

  for (let i = 0; i < specs.length; i++) {
    const a = specs[i];
    if (!a) continue;
    if (a.s.allowInInput && !safeInTextEntry(a.s.keys)) {
      out.push({
        kind: "unsafe-in-input",
        keys: a.s.keys,
        ids: [a.s.id],
        reason: `${a.s.id} asks to fire while the user is typing, but "${a.s.keys}" is a plain key. It is ignored inside text fields.`,
      });
    }
    for (let j = i + 1; j < specs.length; j++) {
      const b = specs[j];
      if (!b || !overlap(a.s.scope, b.s.scope)) continue;
      const shorter = a.chords.length <= b.chords.length ? a : b;
      const longer = shorter === a ? b : a;
      const prefixMatch = shorter.chords.every((c, k) => {
        const other = longer.chords[k];
        return other !== undefined && sameChord(c, other);
      });
      if (!prefixMatch) continue;
      out.push(
        shorter.chords.length === longer.chords.length
          ? {
              kind: "duplicate",
              keys: a.s.keys,
              ids: [a.s.id, b.s.id],
              reason: `${a.s.id} and ${b.s.id} both claim "${a.s.keys}" in overlapping scopes; only the first registered will fire.`,
            }
          : {
              kind: "sequence-prefix",
              keys: shorter.s.keys,
              ids: [shorter.s.id, longer.s.id],
              reason: `"${shorter.s.keys}" (${shorter.s.id}) completes immediately, so the sequence "${longer.s.keys}" (${longer.s.id}) can never be reached.`,
            },
      );
    }
  }
  return out;
}

/* ══ pending-sequence state ════════════════════════════════════════════════ */

/**
 * How long a half-typed sequence waits for its next key. Long enough to be typed deliberately,
 * short enough that a forgotten `g` does not silently swallow the next keystroke.
 */
export const SEQUENCE_TIMEOUT_MS = 1500;

const NO_PENDING: readonly string[] = [];

let pendingChords: Chord[] = [];
let pendingSnapshot: readonly string[] = NO_PENDING;
let pendingTimer = 0;
const pendingListeners = new Set<() => void>();

function setPending(chords: Chord[]): void {
  pendingChords = chords;
  pendingSnapshot =
    chords.length === 0
      ? NO_PENDING
      : chords.map((c) =>
          formatChord(c)
            .map((t) => t.text)
            .join(""),
        );
  if (pendingTimer !== 0) {
    clearTimeout(pendingTimer);
    pendingTimer = 0;
  }
  if (chords.length > 0 && typeof setTimeout === "function") {
    pendingTimer = setTimeout(() => setPending([]), SEQUENCE_TIMEOUT_MS) as unknown as number;
  }
  for (const l of pendingListeners) l();
}

/** The keys typed so far in an unfinished sequence, for the on-screen indicator. */
export function usePendingKeys(): readonly string[] {
  return useSyncExternalStore(
    (cb) => {
      pendingListeners.add(cb);
      return () => pendingListeners.delete(cb);
    },
    () => pendingSnapshot,
    () => NO_PENDING,
  );
}

export const pendingKeys = (): readonly string[] => pendingSnapshot;

/** Clear a half-typed sequence — used when a surface takes over, and by tests. */
export const clearPendingKeys = (): void => setPending([]);

/* ══ the help overlay's open state ═════════════════════════════════════════
   It lives here because the overlay is a projection of this registry: the thing that owns the
   bindings owns whether their documentation is on screen. */

let helpOpen = false;
let helpReturn: ReturnRecord | null = null;
const helpListeners = new Set<() => void>();

export function setHelpOpen(v: boolean, focusReturn?: HTMLElement | null): void {
  if (helpOpen === v) return;
  helpOpen = v;
  // Recorded through the focus-return owner at OPEN time, so the invoker's own opener (the menu
  // trigger around a menu item) is captured while it still exists.
  if (v) helpReturn = recordReturn(focusReturn ?? document.activeElement);
  for (const l of helpListeners) l();
  if (!v) {
    // Focus goes back to the exact invoking element (WCAG 2.4.3, acceptance D3), or — when that
    // item has since unmounted — to what opened it; the owner (./focus-return.ts) decides. The
    // Dialog primitive also restores, but only to whatever had focus when it mounted.
    // Returned once now and once after React has unmounted the sheet: while the modal is still
    // mounted the page behind it is `inert` and refuses focus, so the first call can be a no-op.
    const target = helpReturn;
    helpReturn = null;
    returnFocus(target, null);
    if (target && typeof setTimeout === "function") {
      setTimeout(() => {
        returnFocus(target, null);
      }, 0);
    }
  }
}

export function useHelpOpen(): boolean {
  return useSyncExternalStore(
    (cb) => {
      helpListeners.add(cb);
      return () => helpListeners.delete(cb);
    },
    () => helpOpen,
    () => false,
  );
}

export const isHelpOpen = (): boolean => helpOpen;

/* ══ the manager ═══════════════════════════════════════════════════════════ */

interface Candidate {
  s: Shortcut;
  chords: readonly Chord[];
}

function eligible(s: Shortcut, scope: ShortcutScope, inText: boolean): boolean {
  const allowed = s.allowInInput === true && safeInTextEntry(s.keys);
  if (inText && !allowed) return false;
  if (!characterKeysOn && isCharacterKeyBinding(s.keys)) return false;
  // Behind a modal, only the modal's own bindings and the explicitly-global ones (Escape, the
  // palette) may act. A `g f` that navigated the app behind an open dialog would leave the user
  // reading a surface they can no longer see.
  if (scope === "dialog") {
    if (s.scope !== "dialog" && !allowed) return false;
  } else if (s.scope !== "global" && s.scope !== scope) {
    return false;
  }
  return s.when === undefined || s.when();
}

function fire(s: Shortcut, e: KeyboardEvent): void {
  if (s.preventDefault !== false) e.preventDefault();
  s.run(e);
}

/** Returns true when the event was consumed. Split out so a failed sequence can retry cleanly. */
function dispatch(e: KeyboardEvent, candidates: Candidate[], prefix: Chord[]): boolean {
  const depth = prefix.length;
  const live = candidates.filter(
    (c) =>
      c.chords.length > depth &&
      prefix.every((p, i) => {
        const other = c.chords[i];
        return other !== undefined && sameChord(p, other);
      }),
  );

  const exact = live.find((c) => {
    const next = c.chords[depth];
    return c.chords.length === depth + 1 && next !== undefined && matchChord(next, e);
  });
  if (exact) {
    setPending([]);
    fire(exact.s, e);
    return true;
  }

  const continues = live.find((c) => {
    const next = c.chords[depth];
    return c.chords.length > depth + 1 && next !== undefined && matchChord(next, e);
  });
  if (continues) {
    const next = continues.chords[depth];
    if (next) {
      setPending([...prefix, next]);
      e.preventDefault();
      return true;
    }
  }
  return false;
}

function onKeyDown(e: KeyboardEvent): void {
  // An IME composition delivers keydown with keyCode 229; acting on it steals keys from the
  // composition and makes the app unusable in Japanese, Chinese and Korean input.
  if (e.isComposing || e.keyCode === 229) return;
  if (e.defaultPrevented) return;

  const target = e.target instanceof Element ? e.target : null;
  const active = document.activeElement;
  const focused = active && active !== document.body ? active : target;
  const inText = isTextEntry(focused);
  const scope = activeScope(focused);

  const candidates: Candidate[] = [];
  for (const s of registry) {
    if (!eligible(s, scope, inText)) continue;
    candidates.push({ s, chords: parseSpec(s.keys) });
  }
  if (candidates.length === 0) {
    if (pendingChords.length > 0) setPending([]);
    return;
  }

  if (dispatch(e, candidates, pendingChords)) return;

  // The sequence did not continue. Drop it and let this key stand on its own, so `g` followed by
  // an unrelated key does not silently eat that key.
  if (pendingChords.length > 0) {
    setPending([]);
    dispatch(e, candidates, []);
  }
}

let installs = 0;

/**
 * Attach the single document listener. Ref-counted and idempotent, so both the App shell and the
 * palette may ask for it without racing: whoever arrives first installs, the last to leave
 * removes. Bubble phase, at the document, so a surface that legitimately owns a key can stop
 * propagation before the global model sees it.
 */
export function installKeyboardManager(): () => void {
  if (typeof document === "undefined") return () => {};
  installs += 1;
  if (installs === 1) document.addEventListener("keydown", onKeyDown);
  return () => {
    installs -= 1;
    if (installs === 0) {
      document.removeEventListener("keydown", onKeyDown);
      setPending([]);
    }
  };
}

/** React entry point. Safe to call from more than one component: installs are ref-counted. */
export function useGlobalKeyboard(): void {
  useEffect(() => installKeyboardManager(), []);
}
