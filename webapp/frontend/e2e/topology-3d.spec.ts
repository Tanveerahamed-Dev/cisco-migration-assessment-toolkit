import { test, expect } from "@playwright/test";

// THE crown-jewel E2E — and the reason this tier exists: verify the three.js / react-force-graph-3d
// fabric ACTUALLY renders a WebGL canvas in a real browser. jsdom cannot create a WebGL context, so
// this is fundamentally unreachable by the Vitest suite; the pure logic (layout/switchMesh) is unit-
// tested headless, and THIS proves the render. The API is mocked so no backend is needed.

const META = {
  campaign_id: 1,
  label: "Demo Fleet",
  n_devices: 50,
  script_version: "V3.23.0",
  uploaded_at: new Date("2026-06-13T06:32:00Z").toISOString(),
  summary: {
    avg_health: 72,
    n_critical: 3,
    n_switches: 40,
    version: "V3.23.0",
    punchlist: { crit_high: 5, total: 20, by_severity: { High: 3, Medium: 2 }, by_category: { Security: 4 } },
    readiness: { READY: 30, CAUTION: 8, "NOT READY": 2 },
    bands: { Good: 25, Fair: 10, Critical: 3 },
    sections: [{ key: "overview", label: "Overview" }],
    lifecycle: { past_eos: 2 },
  },
};

const GRAPH = {
  nodes: [
    { id: "core1", band: "Good", score: 80, role: "core", degree: 3, keystone: true },
    { id: "acc1", band: "Fair", score: 60, role: "access", degree: 1, keystone: false },
    { id: "acc2", band: "Critical", score: 20, role: "access", degree: 1, keystone: false },
  ],
  edges: [
    { source: "core1", target: "acc1", is_bridge: true, pairs_cut: 2 },
    { source: "core1", target: "acc2", is_bridge: false, pairs_cut: 0 },
  ],
};

test("renders the WebGL 3D topology fabric in a real browser (jsdom cannot)", async ({ page }) => {
  await page.route("**/api/**", async (route) => {
    const url = route.request().url();
    if (/\/api\/snapshots\/\d+\/graph\b/.test(url)) return route.fulfill({ json: GRAPH });
    if (/\/api\/snapshots\/\d+(\?.*)?$/.test(url)) return route.fulfill({ json: META });
    // Everything else → an ERROR, so each unrelated panel takes its clean useAsync .catch/ErrorBox
    // path. A benign empty-object success would instead let a panel .map() undefined and crash the
    // whole route (app-level ErrorBoundary), hiding the topology. We only need meta + graph real.
    return route.fulfill({ status: 404, json: { detail: "not mocked (unrelated panel)" } });
  });

  await page.goto("/snapshots/1");

  // the topology panel renders; its 2D/3D toggle appears once the (mocked) graph has loaded
  await expect(page.getByRole("heading", { name: /Fleet topology/ })).toBeVisible();
  const toggle3d = page.getByRole("button", { name: "3D", exact: true });
  await expect(toggle3d).toBeVisible({ timeout: 15_000 }); // TopologyGraph settled its 2D view + controls

  // toggle to 3D → react-force-graph-3d lazy-loads and mounts a REAL WebGL canvas
  await toggle3d.click();
  const canvas = page.locator("canvas").first();
  await expect(canvas).toBeVisible({ timeout: 20_000 });

  // and it genuinely has a live WebGL context — the thing jsdom fundamentally cannot provide
  const hasWebGL = await canvas.evaluate(
    (c: HTMLCanvasElement) => !!(c.getContext("webgl2") || c.getContext("webgl")),
  );
  expect(hasWebGL, "the 3D fabric's canvas should hold a live WebGL context").toBe(true);
});
