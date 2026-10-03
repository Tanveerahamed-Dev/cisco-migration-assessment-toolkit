/**
 * capturePin.ts — the capture harness's declared opt-in that takes this host's frame rate out of the
 * picture (acceptance F6, and F2's capture delegate).
 *
 * WHY THIS EXISTS. Two things the permanent chrome draws are derived from `requestAnimationFrame`
 * timing: the quality tier (the adaptive step-down moves `high` to `balanced` after a sustained run
 * of slow frames, which changes the post chain, the labels and the status line's "tier" word) and
 * the E4 frame-rate bar (the status line's "below frame-rate bar" words). On a quiet host neither
 * fires, so two captures agree; on a busy one they fire on some loads and not on others. Measured
 * (re-grade refuter F6): `node review/capture.mjs twice 5` on a frozen preview build
 * exited 3, every bad frame `08-path-indeterminate` — tier `balanced` on some runs, "below frame-rate
 * bar" on others — and each of those frame ids had 2-3 distinct hashes across the five runs while
 * the other 28 were byte-identical. Re-measured on this tree before the fix with that state alone:
 * 7 of 20 captures refused, 2 distinct hashes for each of its 4 frame ids.
 *
 * The harness refused those frames, which kept the verdict honest but made F6 a property of the
 * host's load rather than of the product. The scene already has the mechanism that makes the tier a
 * caller's decision rather than a measurement — a PIN (`quality.ts pinQuality`, `auto: false`), which
 * the step-down, the held step-down and the hidden-page step-up all respect — so a capture asks for
 * that pin before the app mounts, the same way it asks for the scene handle
 * (`window.__atlasExposeScene`, ./devHandle).
 *
 * WHAT IT DOES, and only when asked:
 *   - pins the tier at `high`, IF the capability probe chose `high` for this GPU. The probe reads
 *     capabilities, never a clock (quality.ts `chooseQuality`), so its answer is the same on every
 *     load of one machine. A probe that chose less (a software rasteriser, a small texture limit) is
 *     NOT overridden: the pin is then recorded as not applied, the tier stays what the probe chose,
 *     and the harness refuses the frame — a capture that silently forced `high` onto SwiftShader
 *     would photograph a render no user on that machine gets;
 *   - freezes the frame-rate bar for the session: it is not fed, so it never raises its flag. The
 *     bar's measurement is untouched (./stepdown `createFrameRateBar`); the capture simply does not
 *     consult it;
 *   - says so: `stats().capturePin` records the request, whether it is in force and why, and the
 *     tier's own reasons name the pin. The harness copies that record into every frame's index.json
 *     entry and refuses a frame whose pin is absent or not in force.
 *
 * WHAT IT DOES NOT DO. Without the flag nothing here runs: an ordinary visitor — of the production
 * build OR the dev server — gets the adaptive tier and the reporting bar exactly as before
 * (`capturePinRequested` is false, `stats().capturePin` is null). The flag is NOT implied by a
 * development build, unlike the scene handle: the dev server is where the adaptive rule is exercised.
 * And it is not a frame-rate claim: a pinned session's frame rate is not measured against E4 at all,
 * so no harness that measures frame rate (`review/measure-fps.mjs`, `audit-e5-*.mjs`) may set it.
 */
import type { FrameRateBar } from "./stepdown";
import type { QualityDecision } from "./quality";

declare global {
  interface Window {
    /** Set before the app mounts (an init script) to pin the tier and freeze the frame-rate bar for a capture. */
    __atlasCapturePin?: boolean;
  }
}

/** The pre-mount global a capture harness sets, named in one place. */
export const CAPTURE_PIN_GLOBAL = "__atlasCapturePin";

/** The one tier a capture is graded at (acceptance F2's delegate, F6). */
export const CAPTURE_TIER = "high" as const;

/** What `stats().capturePin` reports while a capture asked for the pin. */
export interface CapturePin {
  /** The tier the capture asked for. */
  tier: typeof CAPTURE_TIER;
  /** True when the tier is pinned at `tier`: false when the capability probe chose a lower one. */
  applied: boolean;
  /** True when the frame-rate bar is not being fed (it then never reports "below frame-rate bar"). */
  rateBarFrozen: boolean;
  /** The sentence, for a reader of index.json. */
  reason: string;
}

/**
 * Whether this page was opened by a capture that asked for the pin. Only the pre-mount global counts:
 * no query parameter, no storage key and no development-build default, so nothing a visitor can
 * reach turns it on.
 */
export function capturePinRequested(): boolean {
  if (typeof window === "undefined") return false;
  return window.__atlasCapturePin === true;
}

/**
 * The decision a capture renders with, from the capability probe's own decision.
 *
 * `probe` must be the probe's (auto) decision: a caller-pinned tier is the caller's and is never
 * replaced by this. Returns the probe's decision unchanged, with `applied: false`, when the probe
 * chose a tier other than `high`.
 */
export function pinForCapture(probe: QualityDecision): { decision: QualityDecision; pin: CapturePin } {
  if (probe.tier !== CAPTURE_TIER) {
    return {
      decision: probe,
      pin: {
        tier: CAPTURE_TIER,
        applied: false,
        rateBarFrozen: false,
        reason:
          `capture pin NOT applied: the capability probe chose ${probe.tier} for this GPU (${probe.reasons.join("; ")}), ` +
          `and a capture does not raise a tier the probe refused`,
      },
    };
  }
  const reason =
    `quality tier pinned at ${CAPTURE_TIER} for a capture (window.${CAPTURE_PIN_GLOBAL}): the adaptive step-down and the ` +
    `frame-rate bar are held, so nothing drawn depends on this host's frame times`;
  return {
    decision: { tier: CAPTURE_TIER, reasons: [reason, ...probe.reasons], auto: false },
    pin: { tier: CAPTURE_TIER, applied: true, rateBarFrozen: true, reason },
  };
}

/**
 * A frame-rate bar that is not fed. `push` records nothing and the flag never rises, so the status
 * line's "below frame-rate bar" words cannot appear. `reset` still reaches the real bar, which keeps
 * it empty: nothing measured during a capture can surface later from it.
 */
export function freezeFrameRateBar(bar: FrameRateBar): FrameRateBar {
  return {
    push: () => false,
    below: () => false,
    reportedFps: () => null,
    reason: () => "",
    reset: () => bar.reset(),
  };
}
