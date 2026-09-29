/**
 * emphasis.ts — the recession easing state machine, lifted out of the WebGL-owning closure.
 *
 * WHY IT LIVES HERE. Recession (how far a device or a cable retreats when something else is the
 * subject) is the one animation whose FINAL value is visible in a screenshot. Everything else in
 * the loop either returns to a fixed value or is not part of a settled frame. Acceptance F6 asks
 * for byte-identical captures, which means the value the GPU ends up holding must be a function of
 * the TARGET alone — never of how many frames the easing happened to get, or of what `dt` the
 * scheduler handed each one.
 *
 * That property is a pure state machine over three arrays. It needs no WebGL context, so it does
 * not belong inside one: `createScene` throws without a GPU, which is why the render loop had zero
 * executed coverage and why the defect below survived a green suite.
 *
 * THE DEFECT THIS FILE WAS EXTRACTED TO FIX. The previous version snapped a value to its target
 * once it was inside the epsilon but did NOT mark the frame as moving, so on the LAST frame of an
 * easing — the frame where every remaining device snaps at once — the flush to the buffer
 * attribute was skipped entirely. The CPU array held the target; the GPU held `cur + (tgt-cur)*k`
 * from the previous frame. `converged()` then reported true and the capture harness photographed a
 * frame-timing-dependent residual: 22 of 32 PNGs differed between two runs of `review/capture.mjs`.
 * `animateFades` in scene.ts documents exactly this hazard and handles it correctly; this half did
 * not. Measured after the fix: four independent loads of `?d=core1&s=fabric` produce one canvas
 * hash, where before they produced two.
 *
 * A second instance of the same shape: the cable pass used to sit INSIDE `if (deviceMoved)`, so a
 * cable whose easing outlasted the devices' (a longer distance to travel under the same rate) was
 * abandoned mid-ease. Both passes now advance on their own terms.
 *
 * `emphasis.test.ts` steps this machine with deliberately different `dt` sequences and asserts the
 * uploaded attribute values are bit-identical. That test fails against the old behaviour.
 */
import type { InstancedBufferAttribute } from "three";

/**
 * Resolver passes between two on-screen device labels leaving — shared by the scene's resolver
 * (scene.ts recomputeLabels) and the DOM label layer (FabricLabels.tsx). Counted in FRAMES, not
 * read off a clock, so the pacing is a pure function of the frame sequence (acceptance F6 /
 * determinism.test.ts): at 60 Hz, five collisions resolved by one wheel tick leave over ~0.25 s,
 * lowest priority first, instead of vanishing together in one frame.
 */
export const LABEL_DROP_EVERY_FRAMES = 3;

/* ── THE EASE OWNER ─────────────────────────────────────────────────────────────────────────────
 *
 * Every JavaScript-stepped fade on the fabric — recession (dim/undim), the hover rim, the selection
 * halo, and (since C5 2026-09-26) the quality-tier cross-fade's overlay — is one of the
 * finite-duration eases below, and nothing outside this file steps
 * an ease of its own (`src/core/motion-inventory.test.ts` parses `src/` and fails on any
 * exponential step anywhere else, and on one here).
 *
 * WHY FINITE. These used to be EXPONENTIAL: `k = min(1, dt / RECEDE_MS); cur += (tgt - cur) * k`,
 * snapping inside an epsilon. The "_MS" constant was then a time CONSTANT, not a duration: MEASURED
 * (independent refuter, C6, 2026-09-22) the recession reached 50 % at 167 ms, 99 % at 1,067 ms and
 * settled at 1,350 ms (72.6 % done at 300 ms); the hover settled at ~417 ms and the halo at ~917 ms
 * — against the 240 / 80 / 140 ms that design-brief §4.8 promised. An ease here has an explicit
 * START (the frame its target changes), an explicit DURATION and an explicit CURVE, and it lands
 * EXACTLY on its target on the first frame at or after start + duration. So the stated duration is
 * the duration, and the settled value is the target itself — never a function of how many frames
 * the ease happened to get (acceptance F6).
 *
 * REDUCED MOTION: every ease snaps to its target on the frame its target changes (§4.8's contract:
 * the end state is identical, only the movement is removed).
 *
 * AND BOUNDED PER FRAME (C5, 2026-09-26). A finite ease advanced by the frame delta is still a
 * wall-clock ease: a frame of dt ms covers dt / duration of the curve whatever the frame rate, so ONE
 * long frame is a cut. MEASURED (acceptance grading at 7f67013): the quality-tier cross-fade — then a
 * CSS transition — fell from opacity 1 to 0.64 across one 116.6 ms host frame (bar 0.25), and the
 * same arithmetic here carried the hover rim 80 % of its ease in one 64 ms frame and the ease-out
 * selection rim 0.56 of its span on an ordinary 60 Hz frame. So every fade this owner steps advances
 * its eased FRACTION by at most FADE_MAX_STEP per frame (`capFraction`): after a stall it moves the
 * cap and then catches up with the wall-clock curve, so the fade spans at least 1 / FADE_MAX_STEP
 * frames and a slow frame delays it instead of cutting it.
 *
 * WHERE IT BINDS AT 60 Hz (C5-R2-4, 2026-09-27; measured over every ease below, and emphasis.test.ts
 * holds this paragraph to the measurement): the cap binds at 60 Hz on the first 4 frames of RECEDE_MS,
 * SELECT_MS and HOVER_MS, never on TIER_FADE_MS, and on no ease's landing frame. The two ease-out
 * curves are steep at their start; HOVER_MS is linear over 80 ms, so its curve asks for more than a
 * fifth of its span per 60 Hz frame and it is held to the cap on every 60 Hz frame but its last. The
 * cap never makes an ease end early and never changes its settled value: the fraction still reaches
 * exactly 1 on the first 60 Hz frame at or after `durationMs`, the frame the uncapped curve lands on,
 * so §4.8's settle times are unchanged. Under reduced motion the cap does not apply to an ease that
 * starts under it: the contract there is a swap, not an animation. A tier cross-fade already RUNNING
 * when the driver is handed a `reduced` flag finishes at the cap instead (`createTierFadeDriver`).
 */

/**
 * The most any fade the owner steps may advance in ONE frame, as a fraction of its span (|to - from|).
 * An opacity fading over [0, 1] therefore moves at most 0.2 of opacity per frame. The grading bar was
 * 0.25 per frame. Since C5 (owner decision, 2026-09-26) review/capture-motion.mjs holds all 24 tier
 * fades to this cap, 0.2. It states that number itself and does not read it from here, because the
 * verifier does not take the product's word for its bar. At 60 Hz the cap never binds on the tier
 * fade's ease-in-out (largest ordinary step 0.103). A frame of about 33 ms or more on the steep part of
 * the curve does bind it (see TIER_FADE_MS).
 */
export const FADE_MAX_STEP = 0.2;

/**
 * The eased fraction after one more frame: the wall-clock curve's value at `elapsedMs`, but never more
 * than FADE_MAX_STEP past the fraction the previous frame showed. Every curve here is monotone, so the
 * result never goes backwards. Exactly 1 once the curve has reached 1 and the cap allows it.
 */
function capFraction(prev: number, spec: EaseSpec, elapsedMs: number, reduced: boolean): number {
  if (reduced) return 1;
  const onCurve = elapsedMs >= spec.durationMs ? 1 : easeFraction(spec.curve, elapsedMs / spec.durationMs);
  return Math.min(onCurve, prev + FADE_MAX_STEP);
}

/** An ease's curve. `ease-out` is tokens.css `--ease-out`, cubic-bezier(0.16, 1, 0.3, 1);
 *  `ease-in-out` is CSS's keyword, cubic-bezier(0.42, 0, 0.58, 1). */
export type EaseCurve = "linear" | "ease-out" | "ease-in-out";

export interface EaseSpec {
  /** The constant's name, as design-brief §4.8 names it on the ease's own row. */
  readonly name: string;
  /** Total duration: the value is exactly the target at `elapsed >= durationMs`. */
  readonly durationMs: number;
  readonly curve: EaseCurve;
}

/** Recession eased over this window so the user can see WHICH nodes left the set. */
export const RECEDE_MS = 240;
/** The hover rim: must feel like a cursor property, not a transition (tokens `--dur-instant`). */
export const HOVER_MS = 80;
/** The selection rim + halo: acknowledgement of a click (tokens `--dur-fast`). */
export const SELECT_MS = 140;

export const RECEDE_EASE: EaseSpec = { name: "RECEDE_MS", durationMs: RECEDE_MS, curve: "ease-out" };
export const HOVER_EASE: EaseSpec = { name: "HOVER_MS", durationMs: HOVER_MS, curve: "linear" };
export const SELECT_EASE: EaseSpec = { name: "SELECT_MS", durationMs: SELECT_MS, curve: "ease-out" };
/** The emphasis eases: the ones `stepEaseChannel` / `stepEmphasis` step towards a changing target.
 *  The tier cross-fade's ease (below) is a one-shot the driver runs, so it is not in this list. The
 *  motion inventory does not read this list to decide what to check: it steps EVERY EaseSpec this
 *  file exports against its §4.8 row, cross-checked against this file's source. */
export const EASES: readonly EaseSpec[] = [RECEDE_EASE, HOVER_EASE, SELECT_EASE];

/* ── The quality-tier cross-fade ────────────────────────────────────────────────────────────────
 *
 * scene.ts lays the OLD tier's last frame over the canvas when the tier changes and fades it out once
 * the new tier's frames are ordinary (the hold: `createTierFadeHold`, ./stepdown). The fade used to be
 * a CSS transition (`opacity 280ms ease-in-out`), and a CSS transition runs on the wall clock: the
 * 2026-09-26 grading at 7f67013 measured opacity 1 -> 0.64 across one 116.6 ms host frame. It is now
 * stepped here, by the render loop, once per frame, on the same curve and duration, with the
 * FADE_MAX_STEP cap. The scene removes the overlay on the frame the value reaches exactly 0.
 *
 * NO PATH CUTS IT (C5-R2-1, owner decision 2026-09-27). The cap alone did not make that true: the
 * cap bounds the driver's own steps, and a running overlay could still leave by other paths. A tier
 * change mid-fade (a `setQuality`, or the step-up a tab switch queues for the first frame back)
 * cleared the half-faded overlay in one frame, and the driver's no-frames watchdog removed it after
 * 2.4 s of a hidden tab, so the reader came back to a picture missing the overlay's remaining opacity.
 * Now a new fade HANDS OVER from the running one's current value (`handOverTierFade`: the new overlay
 * is the frame on screen, the running overlay drawn in at its current opacity, `tierFadeCopy`); a tier
 * change asked for while a fade runs through a warm-up WAITS until a copy can be taken
 * (`deferred`), so it too is handed over rather than landing under the fade's partial value; there is
 * no watchdog; and a fade holds on frames that present nothing new. So no presented frame — after a
 * stall, a returning tab, a tier change — moves the overlay's contribution to the screen by more than
 * FADE_MAX_STEP. A `reduced` flag turned on mid-fade is taken at the cap by the driver. It reaches a
 * running scene only through the scene's `setReducedMotion`; a host that instead disposes the scene on
 * a toggle takes the overlay down with the canvas it covers, a new canvas and camera included —
 * scene.test.ts reads which one Fabric3D.tsx does. The overlay's whole life is `createTierFadeSlot`
 * below. What still removes an overlay in one frame is stated there and is not a cut of a running
 * fade: the driver's removal at exactly 0, the reduced-motion swap of an overlay held at exactly 1 that
 * has been up under reduced motion throughout (that contract; one shown under full motion when reduced
 * motion turns on is finished at the cap, R4-VR2-4), and the scene's disposal (the WebGL canvas it covers goes with it). scene.test.ts
 * enumerates every site in scene.ts that touches the DOM, by type, and holds each to a stated reason;
 * emphasis.test.ts executes the class through the slot on a model of the screen.
 *
 * 280 ms, not 300 (acceptance C6, 2026-09-22): the 300 ms fade MEASURED 299.9-300.1 ms — at the
 * ceiling, not under it — and the end state is first on screen up to one 60 Hz frame after the
 * duration: 280 + 16.7 < 300. At 60 Hz this ease lands on the 17th frame (283.3 ms).
 *
 * WHEN THE CAP WINS OVER 300 ms. On ordinary 60 Hz frames the cap never binds on this ease. It binds
 * on any frame of about 33 ms or more that lands on the steep part of the curve, so a single dropped
 * frame can engage it. Once engaged, the fade trails the curve and ends later than 280 ms. MEASURED by
 * an independent run on a contended host (2026-09-26): one 83.3 ms frame near the tail took a fade to
 * 316.6 ms, and one 133.4 ms frame mid-fade took another to 316.7 ms. MODELLED, with 60 Hz frames and
 * one long frame, as the harness measures a fade:
 *   - an 83-100 ms frame adds at most one 60 Hz frame over the uncapped wall-clock fade;
 *   - a 116-133 ms frame adds at most two;
 *   - a 200-250 ms frame adds at most four.
 * The wall-clock fade itself, the old CSS transition included, already reaches 300 ms when one 50 ms
 * frame lands among its last frames. So "under 300 ms" is a property of the product on ordinary
 * frames, and a stall delays the fade. The cap wins there: a cut is what the reader sees, a late
 * fade is not. review/capture-motion.mjs judges it that way. A fade over 300 ms passes only with a
 * host stall inside it, and only if every frame from 300 ms on ends the fade or moves the full cap. */
export const TIER_FADE_MS = 280;
export const TIER_FADE_EASE: EaseSpec = { name: "TIER_FADE_MS", durationMs: TIER_FADE_MS, curve: "ease-in-out" };

/** A tier cross-fade, already STARTED: its value (the overlay's opacity) is 1 and it eases to 0 over
 *  TIER_FADE_EASE from the next `stepTierFade`. */
export function createTierFade(): EaseChannel {
  const fade = createEaseChannel(1);
  stepEaseChannel(fade, TIER_FADE_EASE, 0, 0);
  return fade;
}

/**
 * Advance a tier cross-fade by one frame of `rawMs` — the frame's REAL duration, not the render
 * loop's 64 ms simulation clamp: the curve is the wall clock's, and the cap is the per-frame bound.
 * Returns true while the fade is still moving; `fade.value` is exactly 0 on the frame it ends.
 */
export function stepTierFade(fade: EaseChannel, rawMs: number, reduced = false): boolean {
  return stepEaseChannel(fade, TIER_FADE_EASE, 0, Number.isFinite(rawMs) ? rawMs : 0, reduced);
}

/** What the scene lends the tier-fade driver: the overlay. No DOM, WebGL or timer in here. */
export interface TierFadeHost {
  /** Show the overlay at this opacity (0 < opacity < 1). */
  write(opacity: number): void;
  /** Remove the overlay. The driver calls it at most once, on the frame the fade reaches exactly 0. */
  finish(): void;
}

export interface TierFadeDriver {
  /** One animation frame of `rawMs`, the frame's REAL duration. Returns true while the overlay is up.
   *  `presenting` is false on a frame on which the canvas under the overlay shows nothing new (a
   *  warm-up in progress): the fade then holds where it is. */
  frame(rawMs: number, reduced: boolean, presenting?: boolean): boolean;
  /** Stop without calling `finish` (the scene removed or replaced the overlay itself). Idempotent. */
  dispose(): void;
  /** The overlay's opacity now (exactly 0 once the fade has ended). */
  readonly value: number;
}

/**
 * A STARTED tier cross-fade, as the scene runs it (C5, 2026-09-26). The scene calls `frame` once per
 * animation frame, unconditionally. The driver steps the fade on `rawMs` (stepTierFade, capped at
 * FADE_MAX_STEP per frame) and writes the overlay's opacity. It removes the overlay (`finish`) on the
 * frame the value reaches exactly 0, never while it is above 0 — and nothing else it owns does: it
 * holds no timer.
 *
 * NO WATCHDOG (C5-R2-1, 2026-09-27). It used to remove the overlay after two 1,200 ms windows without
 * a frame (a hidden tab). Nothing is presented while no frame comes, but the NEXT presented frame then
 * lacked a half-faded overlay the last one showed: a cut, the one path by which the driver removed an
 * overlay above 0. Every presented frame is a `frame` call, so after frames resume the fade ends in at
 * most ceil(1 / FADE_MAX_STEP) frames, the first of them carrying the whole hidden span and moving by
 * the cap.
 *
 * NOTHING NEW PRESENTED, NOTHING MOVES (R4-V1-4, 2026-09-27). On a frame whose canvas shows nothing new
 * (`presenting` false: the scene passes its `compiled` flag, false while a warm-up runs) the fade holds
 * where it is. A cross-fade is between two presented pictures; stepped through a warm-up it faded onto
 * a stale frame, could reach 0 and leave, and the next tier's first frame then landed with no overlay
 * at all. Held, that frame lands under the overlay's value, and the fade resumes on the next one.
 *
 * REDUCED MOTION. A driver runs only for an overlay that was on screen under full motion (the slot starts
 * it from a hold it handed out on `presented(false)`), so a `reduced` flag it is handed is a toggle, at
 * whatever value — exactly 1 included (R4-VR2-4) — and the driver takes the rest from the current value
 * at the cap, FADE_MAX_STEP per frame, never in one frame: the least motion that is not a cut. §4.8's
 * swap (not an animation) is the slot's, for an overlay up under reduced motion throughout. The scene passes
 * its `reducedMotion`, which only its `setReducedMotion` changes; whether the host calls that is read
 * by scene.test.ts from Fabric3D.tsx.
 *
 * Executed in emphasis.test.ts. scene.test.ts pins that `frame()` drives it on `raw`.
 */
export function createTierFadeDriver(host: TierFadeHost): TierFadeDriver {
  const fade = createTierFade();
  let done = false;
  return {
    frame(rawMs: number, reduced: boolean, presenting = true): boolean {
      if (done) return false;
      if (!presenting) return true;
      /* Under reduced motion the fade takes the rest at the cap: a frame long enough to reach the end of
         the curve (TIER_FADE_MS), so the cap is the whole step. That holds at exactly 1 too (R4-VR2-4,
         verifier round 2 of R4): a driver starts only from a hold the slot handed out on `presented(false)`,
         so its overlay was on screen under FULL motion and a reduced flag here is a toggle — one of the
         owner's named paths, which may not take an overlay down faster than the cap. It used to swap
         1 -> 0 in one frame. §4.8's swap at exactly 1 is the slot's alone, for an overlay never shown under
         full motion. */
      stepTierFade(fade, reduced ? TIER_FADE_MS : rawMs, false);
      if (fade.value === 0) {
        done = true;
        host.finish();
        return false;
      }
      host.write(fade.value);
      return true;
    },
    dispose(): void {
      done = true;
    },
    get value(): number {
      return fade.value;
    },
  };
}

/* ── Handing a running cross-fade over to the next one (C5-R2-1, 2026-09-27) ───────────────────── */

/** What the scene lends a handover: a new overlay element that already holds the frame the canvas
 *  shows now (the old tier's, re-presented), and a way to draw another overlay over it. */
export interface TierFadeCopy<E> {
  readonly el: E;
  /** Draw `overlay` over this copy at `alpha`. False when it could not be drawn. */
  drawOver(overlay: E, alpha: number): boolean;
}

/** The two members of a 2-D context the compose uses (a `CanvasRenderingContext2D` is one). */
export interface TierFadePainter<E> {
  globalAlpha: number;
  drawImage(image: E, dx: number, dy: number, dw: number, dh: number): void;
}

/**
 * The scene's copy for a handover (R4-V1-2, 2026-09-27): `el` already holds the frame the canvas shows
 * (`width` x `height` device pixels, drawn through `painter`), and `drawOver` paints a running overlay
 * over ALL of it at the overlay's opacity — as the reader sees it: `drawImage` ignores the element's
 * CSS opacity, so the opacity is the painter's `globalAlpha`, and the bitmap is stretched to the whole
 * copy as CSS stretches the overlay (inset: 0). The painter is left at alpha 1 whatever happens; a
 * draw that throws is reported, so `handOverTierFade` keeps the running overlay rather than swapping it
 * for a partial picture. It used to be inline in scene.ts, where no unit test reached it.
 */
export function tierFadeCopy<E>(el: E, painter: TierFadePainter<E>, width: number, height: number): TierFadeCopy<E> {
  return {
    el,
    drawOver(overlay: E, alpha: number): boolean {
      try {
        painter.globalAlpha = alpha;
        painter.drawImage(overlay, 0, 0, width, height);
        return true;
      } catch {
        return false;
      } finally {
        painter.globalAlpha = 1;
      }
    },
  };
}

/** The overlay up when a tier change lands. */
export interface RunningTierFade<E> {
  readonly el: E;
  /** Its opacity on screen now: 1 while held, the driver's value while fading. */
  readonly opacity: number;
  /** True once a driver runs its fade; false while it is held at 1 (waiting for its hold). */
  readonly fading: boolean;
}

/** What the scene does with the overlay on a tier change.
 *   - `none`: nothing was up and no copy could be taken.
 *   - `new`: nothing was up; mount the copy (the old tier's frame) at opacity 1.
 *   - `composed`: mount the copy, which has the running overlay drawn in at `from`, its opacity now, and
 *     remove the running one in the same task: at opacity 1 the new overlay shows exactly the picture
 *     the reader saw, and fades from there.
 *   - `deferred`: a FADING overlay is up while a warm-up runs (a theme change or new data re-linking the
 *     programs), so no copy can be taken now and one will be once that warm-up has presented. The tier
 *     change must WAIT for it (R4-VR1-5): landed now, the new tier's first frame would come up under
 *     the fade's partial value, (1 - that value) of the pop uncovered. The running fade holds meanwhile
 *     (the driver's `presenting`), and the tier change, landed later, is `composed` from its value.
 *   - `kept`: no copy could be taken and waiting would not bring one; the running overlay STAYS as it
 *     is. A held one (`rehold`, still at 1) waits for the new tier's first composed frame again; a
 *     fading one carries on from `from` — reached only when a copy FAILED outright (no 2-D context, a
 *     draw that threw), the host on which, with nothing up, a tier change has no cross-fade at all. */
export type TierFadeHandover<E> =
  | { readonly kind: "none" }
  | { readonly kind: "new"; readonly mount: E }
  | { readonly kind: "composed"; readonly mount: E; readonly remove: E; readonly from: number }
  | { readonly kind: "deferred"; readonly from: number }
  | { readonly kind: "kept"; readonly from: number; readonly rehold: boolean };

/**
 * A tier change's overlay (C5-R2-1). Verifier round 2 found that a tier change landing while a fade
 * ran (`applyQuality` -> `snapshotForTierFade` -> `clearTierFade`) removed the half-faded overlay in one
 * frame, whatever its opacity, and replaced it with a copy of the canvas UNDER it: a cut of 0.4-1.0 of
 * the tier pop the fade exists to hide. A new fade now starts from what is on screen: the running
 * overlay is drawn into the copy at its CURRENT opacity, so the new overlay at 1 is the same picture,
 * and never is a running overlay removed or reset without one. `warming`: a warm-up is running, so the
 * canvas presents nothing new and no copy can be taken (a fading overlay then defers the change, see
 * `deferred`). Pure: the scene lends the copy.
 */
export function handOverTierFade<E>(running: RunningTierFade<E> | null, copy: () => TierFadeCopy<E> | null, warming = false): TierFadeHandover<E> {
  const from = running === null ? 0 : Number.isFinite(running.opacity) ? Math.min(1, Math.max(0, running.opacity)) : 1;
  if (running !== null && running.fading && warming) return { kind: "deferred", from };
  const c = warming ? null : copy();
  if (running === null) return c === null ? { kind: "none" } : { kind: "new", mount: c.el };
  if (c !== null && c.drawOver(running.el, from)) return { kind: "composed", mount: c.el, remove: running.el, from };
  return { kind: "kept", from, rehold: !running.fading };
}

/* ── The overlay's whole life, owned here (R4-VR1-4, 2026-09-27) ─────────────────────────────────── */

/** What the scene lends the tier-fade slot: the page. The slot calls nothing else of it. */
export interface TierFadeSlotHost<E> {
  /** Put a new overlay on the page, over the canvas (it is already at opacity 1). */
  mount(el: E): void;
  /** Take an overlay off the page. */
  unmount(el: E): void;
  /** Show an overlay at this opacity (0 < opacity < 1). */
  write(el: E, opacity: number): void;
}

/** A held overlay's wait for its fade (`TierFadeSlot.presented`). */
export interface TierFadeHoldHandle {
  /** True while this hold is still the overlay's and its fade has not started. */
  readonly live: boolean;
  /** Start the fade. A no-op once the hold is not live (a later tier change re-held or replaced it). */
  start(): void;
}

export interface TierFadeSlot<E> {
  /** A tier change is asked for: apply `handOverTierFade`'s plan and return it. On `deferred` the caller
   *  must not land the change yet (see `TierFadeHandover`). */
  tierChange(copy: () => TierFadeCopy<E> | null, warming: boolean): TierFadeHandover<E>;
  /** A composed frame of the new tier has landed. Under reduced motion a HELD overlay that has been up under
   *  reduced motion throughout is swapped away (§4.8: at exactly 1, a swap, not an animation); one that was on
   *  screen under full motion when reduced motion turned on starts its fade now, at the cap per frame (R4-VR2-4);
   *  either way null is returned. Otherwise a held overlay's hold handle is returned (null when none is held):
   *  the caller decides WHEN it starts. */
  presented(reduced: boolean): TierFadeHoldHandle | null;
  /** One animation frame (the running fade's driver, `createTierFadeDriver`). */
  frame(rawMs: number, reduced: boolean, presenting: boolean): void;
  /** Teardown: the WebGL canvas the overlay covers goes with it. */
  dispose(): void;
  /** "none", "held" (at 1, waiting for the new tier), "waiting" (its hold running) or "fading". */
  readonly state: "none" | "held" | "waiting" | "fading";
  /** The overlay's opacity on screen (0 when none is up). */
  readonly opacity: number;
}

/**
 * The tier cross-fade's overlay, from mount to removal (R4-VR1-4). It used to be a record the scene
 * updated inline, where a unit test could not reach it: disposing the running driver on the `kept`
 * path left the overlay stuck on screen with every test green. Every transition is here and executed
 * in emphasis.test.ts (the class model runs THIS, over a page it can see); scene.ts lends the page
 * (mount, unmount, write), and scene.test.ts pins that it does nothing else to the overlay.
 *
 * The one-step removals it makes, each stated: `unmount` of an overlay replaced by a `new`/`composed`
 * one that already shows its picture, in the same task; the driver's removal at exactly 0; the
 * reduced-motion swap of an overlay HELD at exactly 1 that has been up under reduced motion THROUGHOUT (it
 * never showed under full motion, so no fade is being cut: §4.8); and `dispose`. An overlay that was up under
 * full motion when reduced motion turned on — held, waiting on its hold, or a composed one carrying a running
 * fade's remnant — is finished at the cap like a mid-fade one (R4-VR2-4). The slot learns the preference from
 * the `reduced` its caller passes every frame (and to `presented`); before the first such call it assumes full
 * motion, which can only ever make a swap a capped fade, never the reverse.
 */
export function createTierFadeSlot<E>(host: TierFadeSlotHost<E>): TierFadeSlot<E> {
  interface Rec {
    readonly el: E;
    driver: TierFadeDriver | null;
    waiting: boolean;
    /** Up under reduced motion since it was mounted: only then is §4.8's swap at exactly 1 its exit. */
    reducedThroughout: boolean;
  }
  let cur: Rec | null = null;
  /** The motion preference the caller last passed (full motion until told otherwise). */
  let lastReduced = false;
  const seeReduced = (reduced: boolean): void => {
    lastReduced = reduced;
    if (!reduced && cur !== null) cur.reducedThroughout = false;
  };
  const remove = (r: Rec): void => {
    r.driver?.dispose();
    if (cur === r) cur = null;
    host.unmount(r.el);
  };
  return {
    tierChange(copy, warming) {
      const running = cur;
      const plan = handOverTierFade<E>(
        running === null ? null : { el: running.el, opacity: running.driver === null ? 1 : running.driver.value, fading: running.driver !== null },
        copy,
        warming,
      );
      if (plan.kind === "new" || plan.kind === "composed") {
        /* The replacement already shows the picture on screen; it goes up in the same task. A composed one
           carries the running overlay drawn in, so it is swap-exempt only if that one was (R4-VR2-4). */
        if (running !== null) remove(running);
        cur = { el: plan.mount, driver: null, waiting: false, reducedThroughout: lastReduced && (running === null || running.reducedThroughout) };
        host.mount(plan.mount);
      } else if (plan.kind === "kept" && plan.rehold && running !== null) {
        /* The SAME element, still at 1, waits for the new tier's first composed frame again: a fresh
           record, so the old hold's handle is no longer live. */
        cur = { el: running.el, driver: null, waiting: false, reducedThroughout: running.reducedThroughout };
      }
      /* `none`, `deferred`, and `kept` with a fade running: nothing changes; the fade runs on. */
      return plan;
    },
    presented(reduced) {
      seeReduced(reduced);
      const r = cur;
      if (r === null || r.driver !== null || r.waiting) return null;
      const start = (): void => {
        if (cur !== r || r.driver !== null) return;
        r.waiting = false;
        r.driver = createTierFadeDriver({
          write: (opacity) => host.write(r.el, opacity),
          finish: () => {
            if (cur === r) remove(r);
          },
        });
      };
      if (reduced) {
        if (r.reducedThroughout) remove(r);
        else start();
        return null;
      }
      r.waiting = true;
      return {
        get live() {
          return cur === r && r.driver === null;
        },
        start,
      };
    },
    frame(rawMs, reduced, presenting) {
      seeReduced(reduced);
      cur?.driver?.frame(rawMs, reduced, presenting);
    },
    dispose() {
      if (cur !== null) remove(cur);
    },
    get state() {
      return cur === null ? "none" : cur.driver !== null ? "fading" : cur.waiting ? "waiting" : "held";
    },
    get opacity() {
      return cur === null ? 0 : cur.driver === null ? 1 : cur.driver.value;
    },
  };
}

/** cubic-bezier(x1, y1, x2, y2) at time fraction `x`, solved by bisection (monotone in x). */
function cubicBezier(x1: number, y1: number, x2: number, y2: number, x: number): number {
  const bx = (t: number): number => 3 * (1 - t) * (1 - t) * t * x1 + 3 * (1 - t) * t * t * x2 + t * t * t;
  const by = (t: number): number => 3 * (1 - t) * (1 - t) * t * y1 + 3 * (1 - t) * t * t * y2 + t * t * t;
  let lo = 0;
  let hi = 1;
  for (let i = 0; i < 40; i += 1) {
    const mid = (lo + hi) / 2;
    if (bx(mid) < x) lo = mid;
    else hi = mid;
  }
  return by((lo + hi) / 2);
}

/** The eased fraction (0..1) at time fraction `t` (0..1). Exactly 0 at 0 and exactly 1 at 1. */
export function easeFraction(curve: EaseCurve, t: number): number {
  if (t <= 0) return 0;
  if (t >= 1) return 1;
  if (curve === "linear") return t;
  return curve === "ease-in-out" ? cubicBezier(0.42, 0, 0.58, 1, t) : cubicBezier(0.16, 1, 0.3, 1, t);
}

/** One scalar eased channel (the hover rim's opacity, the halo's). */
export interface EaseChannel {
  value: number;
  from: number;
  to: number;
  elapsedMs: number;
  /** The eased fraction (0..1) of the current ease the value shows — what FADE_MAX_STEP caps. */
  fraction: number;
}

export function createEaseChannel(value = 0): EaseChannel {
  return { value, from: value, to: value, elapsedMs: 0, fraction: 1 };
}

/**
 * Advance a channel one frame towards `target`. A changed target STARTS a new ease from wherever
 * the channel is now (so an interrupted fade never jumps). Returns true while the ease is running
 * (the value changed, or has not yet reached `to`), false once it rests on its target.
 *
 * determinism: `ch.elapsedMs` accumulates the render loop's frame delta, which comes from the rAF
 * clock, so a MID-ease value does depend on this machine's frame timing. What is drawn in a SETTLED
 * frame does not: the channel holds `to` itself (not a value near it) once its capped fraction reaches
 * 1 — at once under reduced motion — and this returns true on every frame before that, which
 * keeps the scene dirty, so `converged()` (the settle the F6 captures wait on) cannot be reached
 * while any channel is mid-ease. An interrupted ease restarts from a timing-dependent value but
 * still ends on its target. The settled value is therefore a function of the target alone — pinned
 * by `emphasis.test.ts` ("an ease channel's settled value does not depend on this machine's frame
 * timing": steady, jittery and coarse dt sequences land bit-identically).
 *
 * per-frame bound: the fraction advances by at most FADE_MAX_STEP per call (`capFraction`), so one long
 * `dt` moves the value at most 0.2 of |to - from|; the value is `to` itself once the fraction is 1.
 */
export function stepEaseChannel(ch: EaseChannel, spec: EaseSpec, target: number, dt: number, reduced = false): boolean {
  if (target !== ch.to) {
    ch.from = ch.value;
    ch.to = target;
    ch.elapsedMs = 0;
    ch.fraction = 0;
  }
  if (ch.value === ch.to) return false;
  ch.elapsedMs += Math.max(0, dt);
  ch.fraction = capFraction(ch.fraction, spec, ch.elapsedMs, reduced);
  const next = ch.fraction >= 1 ? ch.to : ch.from + (ch.to - ch.from) * ch.fraction;
  const moved = next !== ch.value;
  ch.value = next;
  /* Still easing counts as motion even on a frame whose value happened not to change (a flat
     stretch of the curve at float precision): the caller keeps rendering until the ease ENDS. */
  return moved || ch.value !== ch.to;
}

/** How far a node recedes when something else is the subject. Never to zero: context survives. */
export const RECEDE_DEPTH = 0.62;
export const RECEDE_NEIGHBOUR = 0.3;

/* The structural minimum this machine needs from the scene graph. Written as its own interfaces
   rather than importing FabricGraph so the module has no dependency on the WebGL half; FabricGraph
   satisfies them structurally, and a test can satisfy them with three buffer attributes and a
   handful of plain objects. */

export interface RecedeGroup {
  recede: InstancedBufferAttribute | null;
  ghostRecede: InstancedBufferAttribute | null;
}

export interface RecedeSlot {
  /** Global index, into the current/target arrays. */
  index: number;
  /** Index into the solid or ghost instance array of the slot's group. */
  slot: number;
  ghost: boolean;
  group: RecedeGroup;
}

export interface RecedeBatch {
  /** Link id for every segment, parallel to the attribute's instance array. */
  segmentLinkIds: readonly string[];
  recede: InstancedBufferAttribute;
}

/**
 * A per-device instanced mesh built OUTSIDE the chassis groups — the state rings and the role
 * glyphs — whose instance i belongs to device `deviceIndex[i]`. Their materials are emphasis-patched
 * like the chassis, but the rings and glyphs never carried the recession attribute, so the patch read
 * zero and they stayed at full strength while their chassis desaturated (C5 audit: with one device
 * selected the brightest things on screen were the NON-selected green rings). Registering them here
 * makes them recede from the same clock and the same per-device value as the chassis they sit on.
 */
export interface RecedeMirror {
  attr: InstancedBufferAttribute;
  deviceIndex: readonly number[];
}

export interface EmphasisScene {
  order: readonly RecedeSlot[];
  groups: { values(): Iterable<RecedeGroup> };
  cables: { batches: readonly RecedeBatch[] };
  mirrors?: readonly RecedeMirror[];
}

export interface EmphasisState {
  /** Per-device recession as currently uploaded. */
  current: Float32Array;
  /** Per-device recession being eased towards. */
  target: Float32Array;
  /** Per-link recession target; a link absent from the map recedes to 0. */
  linkTarget: Map<string, number>;
  /** Force one flush of both passes — set after a rebuild or a target change. */
  dirty: boolean;
  /**
   * True once a whole cable pass changed nothing. Cables carry no CPU-side mirror array, so this
   * is what keeps an idle loop from re-scanning every segment of every batch on every rAF tick.
   * Any target change clears it; `stepEmphasis` sets it again when the pass comes up empty.
   */
  cablesSettled: boolean;
  /**
   * The RECEDE_EASE bookkeeping per device: where its current ease started (`from`), towards what
   * (`to` — NaN until a first target is seen, so a state whose `current` was written from outside
   * starts its ease from that value) and how long ago (`elapsed`, ms). A `target` that differs from
   * `to` starts a new ease from `current` on the next step.
   */
  from: Float32Array;
  to: Float32Array;
  elapsed: Float64Array;
  /** The eased fraction each device's value shows — what FADE_MAX_STEP caps per frame. */
  fraction: Float64Array;
  /** The same per cable segment, keyed by batch (allocated once per batch, never per frame). */
  segments: WeakMap<RecedeBatch, { from: Float32Array; to: Float32Array; elapsed: Float64Array; fraction: Float64Array }>;
}

export function createEmphasisState(deviceCount: number): EmphasisState {
  return {
    current: new Float32Array(deviceCount),
    target: new Float32Array(deviceCount),
    linkTarget: new Map<string, number>(),
    dirty: true,
    cablesSettled: false,
    from: new Float32Array(deviceCount),
    to: new Float32Array(deviceCount).fill(Number.NaN),
    elapsed: new Float64Array(deviceCount),
    fraction: new Float64Array(deviceCount),
    segments: new WeakMap(),
  };
}

/** Call after writing `target` or `linkTarget`: both passes must run again, and flush. */
export function markEmphasisDirty(state: EmphasisState): void {
  state.dirty = true;
  state.cablesSettled = false;
}

/**
 * Advance one frame by `dt` ms along RECEDE_EASE. Returns true when anything moved — the caller
 * uses that to keep rendering. Under `reduced` motion every value lands on its target at once.
 *
 * determinism: `state.elapsed` and each segment's `elapsed` accumulate the rAF frame delta, exactly
 * as `stepEaseChannel`'s `elapsedMs` does (see the note there), and the same argument holds: the
 * last frame of every ease writes the target itself and reports motion, so the uploaded values a
 * settled frame draws are the targets alone (`emphasis.test.ts`: three dt sequences, bit-identical).
 *
 * Allocates nothing per frame: `frame()` runs on every rAF tick and a per-frame allocation there
 * is a garbage-collection pause in the middle of an interaction. (A cable batch's bookkeeping is
 * allocated the first time the batch is seen, once.)
 */
export function stepEmphasis(scene: EmphasisScene, state: EmphasisState, dt: number, reduced = false): boolean {
  const force = state.dirty;
  state.dirty = false;
  const step = Math.max(0, dt);

  let devicesMoved = false;
  for (const s of scene.order) {
    const i = s.index;
    const cur = state.current[i] ?? 0;
    const tgt = state.target[i] ?? 0;
    if (!Object.is(state.to[i], tgt)) {
      // A new target STARTS a new ease, from wherever the value is now.
      state.from[i] = cur;
      state.to[i] = tgt;
      state.elapsed[i] = 0;
      state.fraction[i] = 0;
    }
    if (cur === tgt) continue;
    const elapsed = (state.elapsed[i] ?? 0) + step;
    state.elapsed[i] = elapsed;
    /* The last frame of an ease writes the TARGET itself and reports motion, which is what flushes
       it to the attribute below (the F6 defect was a snap that was not flushed). The fraction is
       capped per frame (FADE_MAX_STEP), so a long frame recedes a device by at most 0.2 of its span. */
    const f = capFraction(state.fraction[i] ?? 0, RECEDE_EASE, elapsed, reduced);
    state.fraction[i] = f;
    const from = state.from[i] ?? cur;
    state.current[i] = f >= 1 ? tgt : from + (tgt - from) * f;
    devicesMoved = true;
  }

  if (devicesMoved || force) {
    for (const s of scene.order) {
      const attr = s.ghost ? s.group.ghostRecede : s.group.recede;
      if (attr === null) continue;
      attr.setX(s.slot, state.current[s.index] ?? 0);
    }
    for (const group of scene.groups.values()) {
      if (group.recede !== null) group.recede.needsUpdate = true;
      if (group.ghostRecede !== null) group.ghostRecede.needsUpdate = true;
    }
    for (const mirror of scene.mirrors ?? []) {
      for (let i = 0; i < mirror.deviceIndex.length; i += 1) {
        mirror.attr.setX(i, state.current[mirror.deviceIndex[i] ?? -1] ?? 0);
      }
      mirror.attr.needsUpdate = true;
    }
  }

  /* Cables follow the same easing from the same clock, so a dim and an undim on either side of a
     selection change stay in step — but on their OWN termination, not the devices'. */
  let cablesMoved = false;
  if (!state.cablesSettled || force) {
    for (const batch of scene.cables.batches) {
      const attr = batch.recede;
      let track = state.segments.get(batch);
      if (track === undefined) {
        const n = batch.segmentLinkIds.length;
        track = { from: new Float32Array(n), to: new Float32Array(n).fill(Number.NaN), elapsed: new Float64Array(n), fraction: new Float64Array(n) };
        state.segments.set(batch, track);
      }
      let changed = false;
      for (let i = 0; i < batch.segmentLinkIds.length; i += 1) {
        const id = batch.segmentLinkIds[i];
        if (id === undefined) continue;
        /* fround, because the comparison below decides TERMINATION and the two sides must live in
           the same precision. `linkTarget` holds doubles; the attribute is a Float32Array, so
           `getX` returns the rounded value. Without this, a snapped segment reads back as
           0.6200000047683716 against a target of 0.62, counts as changed on every single frame,
           and the loop never settles — which `converged()` would then never report. (The device
           pass is safe for free: its target lives in a Float32Array too.) */
        const tgt = Math.fround(state.linkTarget.get(id) ?? 0);
        const cur = attr.getX(i);
        if (!Object.is(track.to[i], tgt)) {
          track.from[i] = cur;
          track.to[i] = tgt;
          track.elapsed[i] = 0;
          track.fraction[i] = 0;
        }
        if (cur === tgt) continue;
        const elapsed = (track.elapsed[i] ?? 0) + step;
        track.elapsed[i] = elapsed;
        const f = capFraction(track.fraction[i] ?? 0, RECEDE_EASE, elapsed, reduced);
        track.fraction[i] = f;
        const from = track.from[i] ?? cur;
        const next = f >= 1 ? tgt : from + (tgt - from) * f;
        attr.setX(i, next);
        /* Motion until the ease ENDS, even across a frame whose float32 value did not change. */
        changed = true;
      }
      if (changed || force) attr.needsUpdate = true;
      if (changed) cablesMoved = true;
    }
    state.cablesSettled = !cablesMoved;
  }

  return devicesMoved || cablesMoved;
}

/**
 * The convergence rule, as a value rather than as a closure over the renderer.
 *
 * `converged()` in scene.ts is the single predicate the whole F6 capture protocol waits on, and it
 * could not be executed by a test because it lived inside a closure that needs a GPU. It is a
 * statement about four booleans; those four are what this takes.
 */
export interface ConvergenceInputs {
  /** Shaders are compiled — before that, the first rendered frame is not the settled one. */
  compiled: boolean;
  /** A state change is still waiting to be rendered. */
  dirty: boolean;
  /** Frames rendered since the last change. */
  stillFrames: number;
  /** The camera is mid-tween. */
  cameraTweening: boolean;
}

/** At least this many still frames must follow the last change before a frame counts as final. */
export const STILL_FRAMES_FOR_CONVERGENCE = 2;

export function isConverged(x: ConvergenceInputs): boolean {
  return (
    x.compiled &&
    !x.dirty &&
    x.stillFrames >= STILL_FRAMES_FOR_CONVERGENCE &&
    !x.cameraTweening
  );
}
