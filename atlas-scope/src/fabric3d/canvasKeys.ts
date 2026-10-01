/**
 * canvasKeys.ts — the ONE table of keys the focused fabric canvas answers to.
 *
 * The canvas handles its own keydown (Fabric3D.tsx) because its keys only mean something while the
 * canvas has focus. They used to be stated in three hand-kept places — the handler, the canvas's
 * `aria-keyshortcuts`, and a prose paragraph — and the generated shortcut sheet (ShortcutHelp,
 * which renders the global registry) listed none of them. This table is now what the handler
 * resolves view keys from, what `aria-keyshortcuts` is joined from, and what the help sheet lists.
 *
 * THE MODIFIER SCHEME (acceptance D1, 2026-09-22 — "25 keys on the focused canvas changed nothing"
 * while a pointer drag orbited ~90°):
 *   - unmodified arrows  : move the SELECTION to the nearest device in that direction (unchanged);
 *   - Shift + arrows     : ORBIT, as a primary-button drag in that direction (OrbitControls' own
 *                          convention: Shift turns a pan gesture into a rotate);
 *   - Alt + arrows       : PAN, as a secondary-button drag in that direction (Option on macOS).
 * Ctrl+arrows is avoided on purpose: on macOS Ctrl+Left/Right switch Spaces before the page sees
 * them. Alt+Left/Right are the browser's Back/Forward on Windows and Linux; the canvas cancels
 * them (preventDefault) only while it has focus, which is when the user asked for a camera move.
 * No letter keys: single letters (d, t, r, i, g …) are app-wide shortcuts in the registry, and the
 * canvas's keydown bubbles to that manager.
 *
 * Step size: a key press is a drag of a fixed FRACTION of the canvas height in CSS pixels. OrbitControls
 * divides a drag by the element's height, so the angle per press is the same at every canvas size:
 * 2π × rotateSpeed (0.75) × KEY_ORBIT_STEP = 15° per press.
 */
import { own } from "../core/own";

/** Drag distance per orbit key press, as a fraction of the canvas height (15° at rotateSpeed 0.75). */
export const KEY_ORBIT_STEP = 1 / 18;
/** Drag distance per pan key press, as a fraction of the canvas height. */
export const KEY_PAN_STEP = 1 / 16;

export type CanvasKeyAction = "select" | "frame" | "clear" | "home" | "zoom" | "orbit" | "pan";

export interface CanvasKey {
  /** Registry-style spec (keyboard.ts `formatShortcut` grammar) — what the help sheet draws. */
  keys: string;
  /** The WAI-ARIA `aria-keyshortcuts` tokens this row stands for. */
  aria: readonly string[];
  label: string;
  action: CanvasKeyAction;
}

const ARROWS = ["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"] as const;

export const CANVAS_KEYS: readonly CanvasKey[] = [
  { keys: "up", aria: ARROWS, label: "Select the nearest device in that direction (any arrow key)", action: "select" },
  { keys: "enter", aria: ["Enter"], label: "Frame the camera on the selected device", action: "frame" },
  { keys: "escape", aria: ["Escape"], label: "Clear the selection", action: "clear" },
  { keys: "home", aria: ["Home"], label: "Frame the whole fabric", action: "home" },
  { keys: "+", aria: ["Plus", "Minus"], label: "Zoom in (+) and out (−)", action: "zoom" },
  { keys: "shift+left", aria: ARROWS.map((a) => `Shift+${a}`), label: "Orbit the camera (Shift with any arrow key)", action: "orbit" },
  { keys: "alt+left", aria: ARROWS.map((a) => `Alt+${a}`), label: "Pan the camera (Alt/Option with any arrow key)", action: "pan" },
];

/** The canvas's `aria-keyshortcuts`, joined from the table. */
export const CANVAS_ARIA_KEYSHORTCUTS = CANVAS_KEYS.flatMap((k) => k.aria).join(" ");

/** Screen direction of each arrow as a drag delta sign (screen Y grows downward). */
const ARROW_DELTA: Readonly<Record<string, readonly [number, number]>> = {
  ArrowRight: [1, 0],
  ArrowLeft: [-1, 0],
  ArrowUp: [0, -1],
  ArrowDown: [0, 1],
};

/**
 * The camera move a keydown asks for, as a drag in CSS pixels, or null when it is not a view key.
 * Exactly one modifier: Shift+Alt+arrow (a text-selection chord elsewhere) is not claimed.
 */
export function viewKeyMove(
  e: Pick<KeyboardEvent, "key" | "shiftKey" | "altKey" | "ctrlKey" | "metaKey">,
  canvasHeightPx: number,
): { verb: "orbit" | "pan"; dx: number; dy: number } | null {
  const d = own(ARROW_DELTA, e.key);
  if (!d || e.ctrlKey || e.metaKey || e.shiftKey === e.altKey) return null;
  const verb = e.shiftKey ? "orbit" : "pan";
  const step = Math.max(1, canvasHeightPx) * (verb === "orbit" ? KEY_ORBIT_STEP : KEY_PAN_STEP);
  return { verb, dx: d[0] * step, dy: d[1] * step };
}
