/**
 * stepdown.fadehold.test.ts — how long a tier change may hold the OLD tier's picture over the canvas.
 *
 * MEASURED by the 2026-09-23 grading (C5 (b)), light/high orbit on a contended host: the automatic
 * step-down landed mid-orbit, and the overlay held opacity 1 for about 1,000 ms (700 ms at
 * high -> balanced) while 126 of 282 moving frames changed nothing on screen — the orbit visibly
 * stopped — then released with a 6.08x one-frame change. The hold waited for three frames under
 * 40 ms, which a busy host does not produce, so only the 1,200 ms backstop ended it; and the picture
 * it held was a view the camera had already left.
 *
 * The rule pinned here (`createTierFadeHold`): the overlay holds only while the frames underneath are
 * the SAME view of the SAME content as the frame it was taken from. The first frame on which the
 * camera moved or the content changed starts the fade — the new tier's frame is then the one
 * presenting motion, and the cross-fade is the only thing between them. A still view keeps the calm
 * wait (the step-up case it was built for), bounded by `maxHoldMs`, the figure design-brief.md §4.8
 * states (src/core/motion-inventory.test.ts holds the row to it).
 */
import { describe, expect, it } from "vitest";
import { TIER_FADE_HOLD_DEFAULTS, createTierFadeHold } from "./stepdown";

/** Frames after the new tier's first presented one (t = 0): returns the hold, in ms, and in frames. */
function holdOf(frames: readonly { ms: number; changed: boolean }[]): { ms: number; frames: number } | null {
  const hold = createTierFadeHold(0);
  let t = 0;
  for (let i = 0; i < frames.length; i += 1) {
    const f = frames[i]!;
    t += f.ms;
    if (hold.frame(t, f.ms, f.changed)) return { ms: t, frames: i + 1 };
  }
  return null;
}

/** The contended host's orbit: 45-60 ms frames, the camera moving on every one. */
const busyOrbit = Array.from({ length: 60 }, (_, i) => ({ ms: 45 + (i % 4) * 5, changed: true }));

describe("the tier cross-fade never holds a view the camera has left (C5 (b))", () => {
  it("an orbit in progress starts the fade on the first frame after the new tier presents", () => {
    const h = holdOf(busyOrbit);
    expect(h, "the hold never ended").not.toBeNull();
    expect(h!.frames, `held ${h!.ms} ms over a moving camera`).toBe(1);
  });

  it("a content change under a still camera releases it the same way (an ease, a selection, a trace)", () => {
    const frames = [{ ms: 16.7, changed: false }, { ms: 48, changed: true }, ...Array.from({ length: 80 }, () => ({ ms: 50, changed: false }))];
    expect(holdOf(frames)?.frames).toBe(2);
  });

  it("a still view keeps the calm wait the step-up needs: a heavy first-use frame does not start it", () => {
    /* The measured low -> high case: one 210 ms frame of program links, then ordinary frames. */
    const frames = [{ ms: 210, changed: false }, ...Array.from({ length: 10 }, () => ({ ms: 16.7, changed: false }))];
    expect(holdOf(frames)?.frames).toBe(1 + TIER_FADE_HOLD_DEFAULTS.calmFrames);
  });

  it("a still view on a host that never presents a calm frame is held no longer than the stated bound", () => {
    const frames = Array.from({ length: 200 }, () => ({ ms: 50, changed: false }));
    const h = holdOf(frames)!;
    expect(h.ms).toBeGreaterThanOrEqual(TIER_FADE_HOLD_DEFAULTS.maxHoldMs);
    expect(h.ms - 50).toBeLessThan(TIER_FADE_HOLD_DEFAULTS.maxHoldMs);
  });
});
