/**
 * reduced-motion.test.ts — the WebGL half of `prefers-reduced-motion`, exercised.
 *
 * WHY THIS FILE EXISTS. The CSS half of the preference is inspectable in any stylesheet dump, so
 * it reviews as "present" at a glance. The WebGL half is a JavaScript boolean threaded from
 * `useReducedMotion()` into `createScene({ reducedMotion })` and on into the camera rig and the
 * flow overlay — and nothing executed it. An audit that reads the media blocks and stops has
 * verified the half that cannot silently break. UNPROVEN is not PASS, so these tests drive the
 * two branches that actually remove motion:
 *
 *   - camera.ts: `moveTo` takes the immediate branch, so the camera lands on its target pose in
 *     the same call and no tween is ever in flight;
 *   - flow.ts:  the packet never starts and the path is drawn complete rather than drawn on.
 *
 * Each assertion is paired with its CONTROL at `reducedMotion: false`, because a test that only
 * checks the reduced case passes just as happily against a renderer that animates nothing at all.
 *
 * The trace fixture comes from the REAL producer (`traceFlow` over the compiled snapshot), not
 * from a hand-written object in the shape flow.ts expects.
 */
import { describe, expect, it } from "vitest";
import { PerspectiveCamera } from "three";

import { traceFlow } from "../forwarding/engine";
import { createCameraRig } from "./camera";
import { createFlowOverlay, type TraceSegmentSource } from "./flow";
import { readTokens } from "./materials";

const FRAMING = {
  position: [0, 120, 260] as [number, number, number],
  target: [0, 0, 0] as [number, number, number],
};

const rigOptions = (reducedMotion: boolean) => ({
  framing: FRAMING,
  sphere: { center: [0, 0, 0] as [number, number, number], radius: 140 },
  reducedMotion,
  width: 1160,
  height: 962,
});

const TARGET = {
  position: [200, 90, 40] as [number, number, number],
  target: [10, 5, -10] as [number, number, number],
};

/** A straight 2-segment path with real length, so `totalLength > 0` is satisfied honestly. */
const segmentSource = (): TraceSegmentSource => ({
  polylineBetween: () => new Float32Array([0, 10, 0, 60, 10, 0, 120, 10, 0]),
  anchorOf: (host: string) => ({ x: host.length * 10, y: 0, z: 0, top: 12 }),
});

describe("prefers-reduced-motion — camera tween (camera.ts)", () => {
  it("jumps to the target pose in one call and never tweens", () => {
    const canvas = document.createElement("canvas");
    const rig = createCameraRig(canvas, rigOptions(true));
    try {
      rig.moveTo(TARGET);
      expect(rig.isTweening()).toBe(false);
      // The END STATE is the same as the animated one: motion is removed, information is not.
      expect(rig.camera.position.toArray().map(Math.round)).toEqual(TARGET.position);
      expect(rig.controls.target.toArray().map(Math.round)).toEqual(TARGET.target);
      // A frame later there is still nothing in flight.
      rig.update(16);
      expect(rig.isTweening()).toBe(false);
    } finally {
      rig.dispose();
    }
  });

  it("CONTROL: with motion allowed the same call starts a tween and arrives later", () => {
    const canvas = document.createElement("canvas");
    const rig = createCameraRig(canvas, rigOptions(false));
    try {
      const before = rig.camera.position.clone();
      rig.moveTo(TARGET);
      expect(rig.isTweening()).toBe(true);
      // Still short of the target on the first frame — this is what the reduced case removes.
      rig.update(16);
      expect(rig.camera.position.distanceTo(before)).toBeLessThan(
        before.distanceTo({ x: TARGET.position[0], y: TARGET.position[1], z: TARGET.position[2] } as never),
      );
      expect(rig.isTweening()).toBe(true);
    } finally {
      rig.dispose();
    }
  });

  it("turning the preference on mid-tween lands the camera immediately", () => {
    const canvas = document.createElement("canvas");
    const rig = createCameraRig(canvas, rigOptions(false));
    try {
      rig.moveTo(TARGET);
      expect(rig.isTweening()).toBe(true);
      rig.setReducedMotion(true);
      expect(rig.isTweening()).toBe(false);
      expect(rig.camera.position.toArray().map(Math.round)).toEqual(TARGET.position);
    } finally {
      rig.dispose();
    }
  });
});

describe("prefers-reduced-motion — packet and draw-on (flow.ts)", () => {
  const real = traceFlow({
    srcIp: "10.0.10.50",
    dstIp: "10.0.30.10",
    protocol: "tcp",
    dstPort: 3389,
    srcPort: null,
  });
  const camera = new PerspectiveCamera(45, 1.2, 1, 1000);

  /**
   * The packet is drawn ALONG a path, so it needs two hops to exist at all — and this snapshot
   * cannot produce a second hop (RIBs exist for 2 hosts and core1's non-connected next hops belong
   * to no collected device). Rather than hand-write a Trace in the shape flow.ts expects, the
   * second hop is DERIVED from the real producer's hop, so every field but the identity comes from
   * `traceFlow`. This pins the RENDERER's reduced-motion behaviour; it does not claim the engine
   * can currently emit a multi-hop trace, and the test below states that limit positively.
   */
  const firstHop = real.hops[0];
  const trace =
    firstHop === undefined
      ? real
      : {
          ...real,
          hops: [
            { ...firstHop, nextHost: "core2" },
            { ...firstHop, index: 1, host: "core2", nextHost: null },
          ],
        };

  it("the fixture is a real trace with at least one hop", () => {
    // Guard the guard: a zero-hop trace would make every assertion below vacuous.
    expect(real.hops.length).toBeGreaterThan(0);
    expect(trace.hops.length).toBe(2);
  });

  it("records that the real snapshot's traces are single-hop, so the packet never runs on them", () => {
    // Not a reduced-motion assertion: it is why the fixture above has to be derived, and it fails
    // loudly the day the snapshot grows a second RIB — at which point this file should use it.
    const overlay = createFlowOverlay(readTokens("dark"));
    try {
      overlay.setReducedMotion(false);
      overlay.setTrace(real, 0, segmentSource());
      const packet = overlay.emissiveObjects().find((o) => o.name === "trace-packet");
      expect(real.hops.length).toBe(1);
      expect(packet?.visible).toBe(false);
    } finally {
      overlay.dispose();
    }
  });

  it("never starts the packet and asks for no further frames", () => {
    const overlay = createFlowOverlay(readTokens("dark"));
    try {
      overlay.setReducedMotion(true);
      overlay.setTrace(trace, 0, segmentSource());
      const packet = overlay.emissiveObjects().find((o) => o.name === "trace-packet");
      expect(packet).toBeDefined();
      expect(packet?.visible).toBe(false);
      // Nothing is owed a frame: no draw-on, no packet loop.
      expect(overlay.update(1000, camera)).toBe(false);
      expect(overlay.update(2600, camera)).toBe(false);
      expect(packet?.visible).toBe(false);
    } finally {
      overlay.dispose();
    }
  });

  it("CONTROL: with motion allowed the packet runs and frames are owed", () => {
    const overlay = createFlowOverlay(readTokens("dark"));
    try {
      overlay.setReducedMotion(false);
      overlay.setTrace(trace, 0, segmentSource());
      const packet = overlay.emissiveObjects().find((o) => o.name === "trace-packet");
      expect(packet?.visible).toBe(true);
      expect(overlay.update(1000, camera)).toBe(true);
    } finally {
      overlay.dispose();
    }
  });

  it("switching the preference on while the packet is running stops it", () => {
    const overlay = createFlowOverlay(readTokens("dark"));
    try {
      overlay.setReducedMotion(false);
      overlay.setTrace(trace, 0, segmentSource());
      const packet = overlay.emissiveObjects().find((o) => o.name === "trace-packet");
      expect(packet?.visible).toBe(true);
      overlay.setReducedMotion(true);
      expect(packet?.visible).toBe(false);
      expect(overlay.update(1200, camera)).toBe(false);
    } finally {
      overlay.dispose();
    }
  });
});
