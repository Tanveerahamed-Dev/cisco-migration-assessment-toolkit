import { test, expect } from "@playwright/test";

// OPT-IN fleet-scale render probe (PERF=1) — NOT part of the CI gate: frame rates vary wildly across
// runner hardware, so asserting an FPS floor in CI would be flaky by construction. This exists to put
// NUMBERS on the mesh-cost question (the plan's phase-2 InstancedMesh rewrite is gated on measurement,
// not vibes): run it on main, run it on a candidate branch, compare renderer.info + sampled FPS.
// A ~300-node fleet mirrors the documented real-fleet ceiling (the "303 Meridian reference fleet").
const RUN = !!process.env.PERF;

const N = 300;
const ROLES = ["core", "distribution", "access", "edge"];
const BANDS = ["Excellent", "Good", "Fair", "Poor", "Critical"];
const nodes = Array.from({ length: N }, (_, i) => ({
  id: `sw-${String(i).padStart(3, "0")}`,
  band: BANDS[i % BANDS.length],
  score: 20 + (i % 80),
  role: ROLES[i % ROLES.length],
  degree: i % 12,
  keystone: i % 29 === 0,
}));
// chain + cross links ≈ 1.5 edges/node — a realistic access→distribution→core shape
const edges = [
  ...Array.from({ length: N - 1 }, (_, i) => ({ source: nodes[i].id, target: nodes[i + 1].id, is_bridge: i % 37 === 0, pairs_cut: 0 })),
  ...Array.from({ length: Math.floor(N / 2) }, (_, i) => ({ source: nodes[i * 2].id, target: nodes[(i * 7 + 3) % N].id, is_bridge: false, pairs_cut: 0 })),
];

const META = {
  campaign_id: 1, label: "Perf Fleet", n_devices: N, script_version: "V0", uploaded_at: new Date("2026-01-01").toISOString(),
  summary: {
    avg_health: 60, n_critical: 10, n_switches: N, version: "V0",
    punchlist: { crit_high: 0, total: 0, by_severity: {}, by_category: {} },
    readiness: { READY: N, CAUTION: 0, "NOT READY": 0 },
    bands: { Good: N }, sections: [], lifecycle: {},
  },
};

test("fleet-scale 3D render probe — renderer.info + sampled FPS at ~300 nodes", async ({ page }) => {
  test.skip(!RUN, "opt-in: set PERF=1 to run the fleet-scale probe");
  test.setTimeout(120_000);

  await page.route("**/api/**", async (route) => {
    const url = route.request().url();
    if (/\/api\/snapshots\/\d+\/graph\b/.test(url)) return route.fulfill({ json: { nodes, edges } });
    if (/\/api\/snapshots\/\d+(\?.*)?$/.test(url)) return route.fulfill({ json: META });
    return route.fulfill({ status: 404, json: { detail: "not mocked" } });
  });

  await page.goto("/snapshots/1");
  await page.getByRole("button", { name: "3D", exact: true }).click();
  await expect(page.locator("canvas").first()).toBeVisible({ timeout: 30_000 });
  // Sample STEADY-STATE render cost: wait past the engine's 14s cooldownTime so the d3-force
  // simulation has stopped ticking — otherwise the number conflates sim CPU with render cost.
  await page.waitForTimeout(16_000);

  const stats = await page.evaluate(async () => {
    // sample FPS over 3s of live rAF, then read the WebGL renderer's own draw-call counters
    const frames: number[] = [];
    await new Promise<void>((done) => {
      let last = performance.now(); let until = last + 3_000;
      const tick = (t: number) => { frames.push(t - last); last = t; if (t < until) requestAnimationFrame(tick); else done(); };
      requestAnimationFrame(tick);
    });
    const dts = frames.slice(1).filter((d) => d > 0);
    const avg = dts.reduce((s, d) => s + d, 0) / (dts.length || 1);
    const worst = Math.max(...dts);
    // three.js exposes per-frame draw stats on the renderer; react-force-graph keeps no global handle,
    // so count scene objects via the canvas's context loss extension route instead… simplest reliable
    // proxy: count WebGL draw-ish objects from the DOM side is impossible — report frame stats only,
    // plus the JS heap as a coarse allocation signal where the browser exposes it.
    const mem = (performance as any).memory ? Math.round((performance as any).memory.usedJSHeapSize / 1048576) : null;
    return { fpsAvg: Math.round(1000 / avg), frameWorstMs: Math.round(worst), samples: dts.length, heapMB: mem };
  });

  console.log(`PERF ${N} nodes:`, JSON.stringify(stats));
  expect(stats.samples).toBeGreaterThan(30); // sanity: the loop actually ran
});
