/**
 * status-telemetry.test.tsx — the status bar's scene readout is WIRED, and costs the fabric nothing.
 *
 * WHY THIS EXISTS. `StatusBar` declares `stats?: SceneStats | null` with a `null` default and a
 * complete, well-written "not observed" branch behind it. The shell rendered `<StatusBar
 * onOpenCite={…} />` — no `stats` — so the default was the only value that branch ever saw: the bar
 * said "the 3-D subsystem has not reported a frame yet" for the whole life of a session in which
 * the subsystem reported a frame twice a second, at 60 fps, tier high. Nothing failed. The readout
 * was unreachable code behind an honest-looking sentence, which is the one failure shape this
 * product exists to detect, committed by the product itself.
 *
 * So the assertions are: the tier is IN the DOM while the fabric is mounted, it is the tier the
 * scene reported, it follows a step-down, and it returns to "not observed" when the scene is
 * released. A `stats = null` default that renders a plausible absence cannot satisfy any of them.
 *
 * The last test pins the other half of the trade. Re-rendering the bar on every emit cost the
 * fabric 6-7 fps (measured; see `fabric3d/telemetry.ts`), so notifications are throttled to one a
 * second and fire only when what the bar DRAWS changes. The stored reading stays current — a
 * throttle that made readers see stale data would be a different defect from the one being fixed.
 *
 * No renderer is involved and none is mocked: jsdom has no WebGL, and the subject here is the
 * wiring rather than the picture. Readings are pushed through the REAL channel the real scene
 * publishes on — `fabric3d/telemetry`, written by `Fabric3D`'s stats handler — so removing the
 * subscription, or the publish, fails this test.
 *
 * WHAT TWO OF THESE ASSERTIONS USED TO SAY, and why that was a defect. They read
 * `expect(container.querySelector(".sb__fps")?.textContent).toContain("52")` — i.e. they REQUIRED
 * the permanent status line to paint a frame-timing measurement. Acceptance F6 asks for two runs
 * to produce byte-identical captures, and measurement on 2026-09-21 showed 23 of 32 frames
 * differing, entirely inside those digits. So the suite was pinning the exact behaviour that made
 * a release criterion unsatisfiable, and doing it in a file whose subject is honesty of the
 * readout. A test that requires a defect is worse than no test: it converts the fix into a
 * regression.
 *
 * They now assert the property instead of the pixel: the permanent line carries NO digit at any
 * published frame rate, two readings that differ only in frame timing leave its markup identical,
 * and the measurements are still reachable — one click away, in the renderer disclosure. The first
 * of those is stated as "no digit anywhere in the readout", not as "no `.sb__fps` element",
 * because a guard scoped to the one class name that happened to carry the defect is the shape this
 * repository keeps finding and does not want another of.
 */
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { actAsync } from "../test-support/act-turns";

import type { SceneStatsEx } from "../fabric3d/scene";
import { publishSceneStats, readSceneStats, releaseSceneStats } from "../fabric3d/telemetry";
import { App, LiveStatusBar } from "./App";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const mounted: { root: Root; container: HTMLElement }[] = [];

function mount(ui: ReactNode): HTMLElement {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  act(() => root.render(ui));
  mounted.push({ root, container });
  return container;
}

/** A reading in the shape `scene.ts :: snapshot()` returns. Only the published fields are read. */
function reading(over: Partial<SceneStatsEx> = {}): SceneStatsEx {
  return {
    fps: 60,
    frameMs: 16.7,
    worstFrameMs: 17.2,
    drawCalls: 75,
    triangles: 240983,
    programs: 43,
    quality: "high",
    converged: true,
    qualityReasons: ["full quality"],
    qualityAuto: true,
    overBudget: false,
    drawCallBudget: 88,
    activeOutlines: 0,
    missingTokens: [],
    undrawnHops: [],
    labelsShown: 26,
    labelsTotal: 26,
    warmupStage: null,
    programsLinked: 43,
    programsTotal: 43,
    warmupTimedOut: false,
    frameRateBelowBar: false,
    /* Non-zero: this fixture is a SETTLED reading, and `framesTimed: 0` would mean `fps` and
       `frameMs` above are placeholders rather than measurements (scene.ts). */
    framesTimed: 1800,
    ...over,
  };
}

/**
 * Publish, then let the notification throttle's trailing edge fire.
 *
 * Real timers on purpose: the trailing edge is the part of the throttle a step-down depends on, and
 * faking it away would leave the assertions exercising the immediate path twice.
 */
async function publishAndSettle(next: SceneStatsEx): Promise<void> {
  publishSceneStats(next);
  await actAsync(async () => {
    await new Promise((r) => setTimeout(r, 1100));
  });
}

beforeEach(() => {
  releaseSceneStats();
});

afterEach(() => {
  for (const m of mounted.splice(0)) {
    act(() => m.root.unmount());
    m.container.remove();
  }
  releaseSceneStats();
});

describe("the shell subscribes its status bar to the scene", () => {
  it("shows a reading published while the whole app is mounted", async () => {
    /* The end-to-end shape of the defect: the bar is rendered by App, and App is what did not pass
       the readings on. Mounting the real shell and publishing on the real channel is the only
       assertion that fails if that wiring is removed again. */
    const container = mount(<App />);
    await actAsync(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });
    expect(container.querySelector(".sb__tier")).toBeNull();

    await publishAndSettle(reading({ quality: "balanced", fps: 52 }));
    expect(container.querySelector(".sb__tier")?.textContent).toBe("tier balanced");
    // ...and the reading reaches the bar WITHOUT the frame rate being painted into it (F6).
    expect(container.querySelector(".sb__scene")?.textContent).not.toContain("52");
  });
});

describe("the status bar reports the scene the user is actually being shown", () => {
  it("names the tier and the frame rate the scene published", async () => {
    const container = mount(<LiveStatusBar onOpenCite={() => {}} />);
    await publishAndSettle(reading());

    const tier = container.querySelector(".sb__tier");
    expect(tier).not.toBeNull();
    expect(tier?.textContent).toBe("tier high");
    // The absence sentence must be GONE once a frame has been reported.
    expect(container.textContent).not.toContain("has not reported a frame yet");
  });

  it("follows a step-down, and says it is reduced in words", async () => {
    const container = mount(<LiveStatusBar onOpenCite={() => {}} />);
    await publishAndSettle(reading());
    expect(container.querySelector(".sb__reduced")).toBeNull();

    await publishAndSettle(
      reading({ quality: "low", fps: 41, qualityReasons: ["stepped down to low"], converged: false }),
    );
    expect(container.querySelector(".sb__tier")?.textContent).toBe("tier low");
    expect(container.querySelector(".sb__reduced")?.textContent).toBe("reduced");
    expect(container.querySelector(".sb__converged")?.textContent).toBe("refining");
  });

  it("says not observed only when nothing has been reported, and again once the scene is released", async () => {
    const container = mount(<LiveStatusBar onOpenCite={() => {}} />);
    expect(readSceneStats()).toBeNull();
    expect(container.querySelector(".sb__tier")).toBeNull();
    expect(container.textContent).toContain("has not reported a frame yet");

    await publishAndSettle(reading());
    expect(container.querySelector(".sb__tier")).not.toBeNull();

    /* Releasing the scene must return the bar to "not observed" rather than freezing the last
       reading on screen as though it were live — and it must do so IMMEDIATELY, not on the next
       throttle window, because until it does the bar describes a renderer that is gone. */
    act(() => releaseSceneStats());
    expect(container.querySelector(".sb__tier")).toBeNull();
    expect(container.textContent).toContain("has not reported a frame yet");
  });
});

describe("the permanent line is a function of the DATA, not of this machine (acceptance F6)", () => {
  /* The unit-level half of F6. The whole-frame half — capture, re-capture, byte-compare — lives in
     `review/capture.mjs twice`, because only a real browser can produce the bytes F6 talks about.
     This half fails in milliseconds and names the cause, which is what stops the measurement from
     reaching a reviewer as 23 mysteriously differing PNGs. */

  it("draws no digit in the scene readout, at any frame rate the scene can report", async () => {
    const container = mount(<LiveStatusBar onOpenCite={() => {}} />);
    /* Stated as "no digit", not as "no .sb__fps": the defect was a frame-timing value on a
       rendered path, and naming the one element that carried it would leave the class open. */
    for (const fps of [60, 52, 41, 7, 143]) {
      await publishAndSettle(reading({ fps, quality: "high", converged: true }));
      /* The readout must be THERE and say something: "no digit" in an element that vanished, or
         that renders empty, is a pass that proves nothing (independent refuter, wave 3). */
      const el = container.querySelector(".sb__scene");
      expect(el, `the scene readout is not rendered at ${fps} fps`).not.toBeNull();
      const line = el!.textContent ?? "";
      expect(line.trim().length, `the scene readout is empty at ${fps} fps`).toBeGreaterThan(0);
      expect(line, `the scene readout drew a digit at ${fps} fps: "${line}"`).not.toMatch(/\d/);
    }
  });

  it("renders identical markup for two readings that differ only in frame timing", async () => {
    const container = mount(<LiveStatusBar onOpenCite={() => {}} />);
    await publishAndSettle(reading({ fps: 43, frameMs: 23.2, worstFrameMs: 61.0, drawCalls: 75 }));
    const first = container.querySelector(".sb__scene")?.outerHTML;

    await publishAndSettle(reading({ fps: 56, frameMs: 17.8, worstFrameMs: 19.4, drawCalls: 81 }));
    const second = container.querySelector(".sb__scene")?.outerHTML;

    /* The two values measured in the real double-capture that failed F6: "fabric 43 fps" against
       "fabric 56 fps". Same data, same tier, same convergence — so the same markup. */
    expect(first).toBeTruthy();
    expect(second).toBe(first);
  });

  it("still lets a reader reach the measurements — one click away, not hidden", async () => {
    const container = mount(<LiveStatusBar onOpenCite={() => {}} />);
    await publishAndSettle(reading({ fps: 43, frameMs: 23.2, drawCalls: 75 }));

    const control = container.querySelector<HTMLButtonElement>(".sb__scene--btn");
    expect(control, "the scene readout must be a control, not a dead caption").not.toBeNull();
    expect(control?.getAttribute("aria-expanded")).toBe("false");

    act(() => control?.click());
    expect(control?.getAttribute("aria-expanded")).toBe("true");

    // The panel is portalled to <body>, which is where the numbers now live.
    const diag = document.querySelector(".covpanel__renderer")?.textContent ?? "";
    expect(diag).toContain("43 fps");
    expect(diag).toContain("23.2 ms");
    expect(diag).toContain("75");
  });
});

describe("the readout does not put the fabric back on React's frame path", () => {
  it("stores every reading but re-renders only when a drawn value changes", async () => {
    let mutations = 0;
    const container = mount(<LiveStatusBar onOpenCite={() => {}} />);
    await publishAndSettle(reading());
    const observer = new MutationObserver(() => {
      mutations += 1;
    });
    observer.observe(container, { childList: true, subtree: true, characterData: true });

    // A burst at the scene's own emit rate, with every DRAWN value unchanged.
    await actAsync(async () => {
      for (let i = 0; i < 10; i++) {
        publishSceneStats(reading({ fps: 60.04, frameMs: 16.7 + i / 100, drawCalls: 75 + i }));
        await new Promise((r) => setTimeout(r, 30));
      }
      await new Promise((r) => setTimeout(r, 1100));
    });
    observer.disconnect();

    /* Nothing the bar draws changed — fps still rounds to 60 — so nothing re-rendered, and the
       diagnostic fields that did change reached no renderer. */
    expect(mutations).toBe(0);
    // ...while the stored reading is the LATEST one, not the one that happened to notify.
    expect(readSceneStats()?.drawCalls).toBe(84);
  });
});
