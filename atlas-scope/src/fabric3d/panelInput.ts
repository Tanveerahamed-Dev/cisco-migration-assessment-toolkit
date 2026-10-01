/**
 * WHEN the fabric may spend a frame on a composed render while the reader is working in a DOM
 * panel — acceptance E2/E3/E5, 2026-09-21.
 *
 * THE MEASUREMENT. Long Animation Frames attribution on the release build put the fabric's own
 * requestAnimationFrame callback on the interaction path of journeys that never touch the canvas:
 * up to 195-326 ms while typing in the query bar (J3b), 118 ms on a path-trace submit (J4), 331 ms
 * during a findings-grid ArrowDown and 449 ms while the Inspector opened. Each of those keystrokes
 * or clicks re-aimed the fabric too (a highlight, a selection, a trace, a resize), so the scene was
 * dirty and rendered the whole composed chain — outline passes, SSAO, bloom — in the very frames
 * the next keystroke had to wait behind. The existing one-frame yield (`yieldToPage` in scene.ts)
 * moved the render one frame later, which is exactly where the NEXT keystroke of a typed word
 * lands.
 *
 * THE RULE. The scene still owes the render (its dirty flag stays set; `converged` stays false),
 * but while discrete input is arriving on a surface that is NOT the fabric, the owed render waits
 * for a pause of `quietMs`. A burst longer than `maxDeferMs` renders anyway, so a reader who types
 * continuously still sees the fabric follow at least that often — deferral can never become
 * "never". Input ON the fabric (a pick, an orbit, a key in the canvas) is never deferred: there the
 * fabric is the thing being interacted with and its frame IS the acknowledgement.
 *
 * Only WHEN a frame is drawn is decided here. What is drawn — geometry, colour, layout, the target
 * of any animation — is untouched, so a deferred frame and an immediate one converge to the same
 * pixels (acceptance F6).
 */

export interface PanelInputOptions {
  /** A pause in panel input this long lets an owed render land. */
  quietMs: number;
  /** An owed render is never held longer than this, however long the input burst lasts. */
  maxDeferMs: number;
}

/* 250 ms of quiet: comfortably longer than the ~150 ms cadence of a reader typing a word (the J3b
   journey) even when a loaded host stretches the gap between two keydowns — measured 2026-09-21, a
   180 ms window still let an owed render (152 ms) land between two keys of the word on a busy
   host — and still under the pause after a click before the eye travels to the fabric. 1500 ms
   cap: a word typed continuously is not interrupted by the fabric, and a longer burst still sees
   it follow at least that often. */
export const PANEL_INPUT_DEFAULTS: PanelInputOptions = { quietMs: 250, maxDeferMs: 1500 };

export interface PanelInputGate {
  /** Discrete input (key, pointer press/release) arrived on a surface that is not the fabric. */
  noteForeignInput(at: number): void;
  /** Input arrived ON the fabric: whatever it re-aims should be drawn promptly. */
  noteFabricInput(at: number): void;
  /**
   * An owed render is due at `now`. Returns true when it should wait. A render that does land
   * must be reported with `rendered`, so the next burst's cap is measured from its own start.
   */
  shouldDefer(now: number): boolean;
  rendered(): void;
}

export function createPanelInputGate(opts: Partial<PanelInputOptions> = {}): PanelInputGate {
  const o: PanelInputOptions = { ...PANEL_INPUT_DEFAULTS, ...opts };
  let lastForeign = Number.NEGATIVE_INFINITY;
  /** When the render currently being held was first held; null when none is. */
  let heldSince: number | null = null;
  return {
    noteForeignInput(at) {
      if (Number.isFinite(at)) lastForeign = Math.max(lastForeign, at);
    },
    noteFabricInput(at) {
      /* The reader moved to the fabric: anything owed there is now the acknowledgement of THIS
         input, so the panel burst no longer holds it. */
      if (Number.isFinite(at) && at >= lastForeign) lastForeign = Number.NEGATIVE_INFINITY;
    },
    shouldDefer(now) {
      if (now - lastForeign >= o.quietMs) {
        heldSince = null;
        return false;
      }
      if (heldSince === null) heldSince = now;
      if (now - heldSince >= o.maxDeferMs) {
        heldSince = null;
        return false;
      }
      return true;
    },
    rendered() {
      heldSince = null;
    },
  };
}

/**
 * Is `target` inside the fabric's own surface? The surface is the nearest ancestor of the canvas
 * carrying `data-fabric-surface` (the Fabric3D host: canvas, labels, HUD, legend), or the canvas
 * alone when no host declares one — an embed that mounts a bare canvas still counts its own input.
 */
export function isFabricTarget(canvas: HTMLCanvasElement, target: EventTarget | null): boolean {
  if (!(target instanceof Node)) return false;
  const surface: Element = canvas.closest("[data-fabric-surface]") ?? canvas;
  return surface.contains(target);
}
