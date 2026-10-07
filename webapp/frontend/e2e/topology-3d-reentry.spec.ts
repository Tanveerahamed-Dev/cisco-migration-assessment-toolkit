import { test, expect, type ElementHandle, type JSHandle, type Locator, type Page, type TestInfo } from "@playwright/test";
import { writeFile } from "node:fs/promises";

// The existing topology-3d.spec.ts keeps its normal-motion mounted-toggle control unchanged.
// This separate control exercises a real SPA route unmount and fresh library mount on history
// return. Reduced motion is the product's own settled 80-warmup/zero-cooldown/no-particles branch,
// so a stable canvas pair followed by wheel-induced pixels is a meaningful control, not animation.
// It is not a frame-rate, leak, device-scale, or React Activity/StrictMode effect-cycle proof.
const META = {
  campaign_id: 1, label: "Demo Fleet", n_devices: 50, script_version: "V3.23.0",
  uploaded_at: new Date("2026-06-13T06:32:00Z").toISOString(),
  summary: {
    avg_health: 72, n_critical: 3, n_switches: 40, version: "V3.23.0",
    punchlist: { crit_high: 5, total: 20, by_severity: { High: 3, Medium: 2 }, by_category: { Security: 4 } },
    readiness: { READY: 30, CAUTION: 8, "NOT READY": 2 }, bands: { Good: 25, Fair: 10, Critical: 3 },
    sections: [{ key: "overview", label: "Overview" }], lifecycle: { past_eos: 2 },
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

const contextState = (canvas: Locator) => canvas.evaluate((node: HTMLCanvasElement) => {
  const context = node.getContext("webgl2") || node.getContext("webgl");
  return { live: context !== null && !context.isContextLost(), width: context?.drawingBufferWidth ?? 0,
    height: context?.drawingBufferHeight ?? 0 };
});

const layoutState = (canvas: Locator) => canvas.evaluate((node: HTMLCanvasElement) => {
  const r = node.getBoundingClientRect();
  const ancestors: { tag: string; scrollLeft: number; scrollTop: number }[] = [];
  for (let element: Element | null = node; element !== null; element = element.parentElement) {
    ancestors.push({ tag: element.tagName, scrollLeft: element.scrollLeft, scrollTop: element.scrollTop });
  }
  return { box: { x: r.x, y: r.y, width: r.width, height: r.height }, viewport: { width: innerWidth, height: innerHeight },
    windowScroll: { x: scrollX, y: scrollY },
    documentScroll: { x: document.scrollingElement?.scrollLeft ?? null, y: document.scrollingElement?.scrollTop ?? null },
    ancestors };
});

interface CapturedCanvas { pixels: Buffer; filename: string }

async function captureCanvas(canvas: Locator, phase: string, info: TestInfo,
  captures: Record<string, unknown>[]): Promise<CapturedCanvas> {
  const filename = `${phase}-${String(captures.length + 1).padStart(3, "0")}.png`;
  const record: Record<string, unknown> = { phase, attempt: captures.length + 1, captured: false, written: false, attached: false };
  captures.push(record);
  try {
    const pixels = await canvas.screenshot();
    Object.assign(record, { filename, captured: true, bytes: pixels.length });
    // Write the actual PNG into test-results before any later comparison/assertion. Path-based
    // attachment then references durable runner output even with CI's line reporter.
    const output = info.outputPath(filename);
    await writeFile(output, pixels, { flag: "wx" });
    record.written = true;
    await info.attach(filename, { path: output, contentType: "image/png" });
    record.attached = true;
    return { pixels, filename };
  } catch (error) {
    record.error = String(error);
    throw error;
  }
}

async function stableCanvas(canvas: Locator, phase: string, info: TestInfo,
  captures: Record<string, unknown>[]): Promise<CapturedCanvas> {
  let previous: CapturedCanvas | undefined;
  let stable: CapturedCanvas | undefined;
  // No timeout override, fixed sleep, pixel tolerance or golden update. A blank or inert graph
  // may pass stability, but cannot also pass the later real-wheel pixel-change control.
  await expect.poll(async () => {
    const current = await captureCanvas(canvas, `${phase}-stability`, info, captures);
    const identical = previous !== undefined && current.pixels.equals(previous.pixels);
    previous = current;
    if (identical) stable = current;
    return identical;
  }).toBe(true);
  expect(stable).toBeDefined();
  return stable!;
}

async function wheelChangesScene(page: Page, canvas: Locator, phase: string, info: TestInfo,
  observations: Record<string, unknown>[], captures: Record<string, unknown>[]) {
  const wheelSamples: Record<string, unknown>[] = [];
  const observation: Record<string, unknown> = { phase, stage: "scroll-into-view", wheelSamples };
  observations.push(observation);
  await canvas.scrollIntoViewIfNeeded();
  const before = await layoutState(canvas);
  observation.initialLayout = before;
  expect(before.box.width).toBeGreaterThan(0);
  expect(before.box.height).toBeGreaterThan(0);
  expect(before.box.x).toBeGreaterThanOrEqual(0);
  expect(before.box.y).toBeGreaterThanOrEqual(0);
  expect(before.box.x + before.box.width).toBeLessThanOrEqual(before.viewport.width);
  expect(before.box.y + before.box.height).toBeLessThanOrEqual(before.viewport.height);
  // Keep the pointer away from the central nodes and the bottom hint so hover text cannot
  // manufacture a wheel result. Verify that the actual canvas receives this real pointer.
  const point = { x: before.box.x + 20, y: before.box.y + 20 };
  await page.mouse.move(point.x, point.y);
  expect(await canvas.evaluate((node, p) => document.elementFromPoint(p.x, p.y) === node, point)).toBe(true);
  observation.stage = "stability-capture";
  const still = await stableCanvas(canvas, phase, info, captures);
  observation.baselineCapture = still.filename;
  const immediatelyBefore = await layoutState(canvas);
  observation.before = immediatelyBefore;
  expect(immediatelyBefore).toEqual(before);
  const liveBefore = await contextState(canvas);
  observation.liveBefore = liveBefore;
  expect(liveBefore.live).toBe(true);
  expect(liveBefore.width).toBeGreaterThan(0);
  expect(liveBefore.height).toBeGreaterThan(0);
  Object.assign(observation, { stage: "wheel", wheel: { x: 0, y: -240 } });
  await page.mouse.wheel(0, -240);
  let changed: CapturedCanvas | undefined;
  await expect.poll(async () => {
    const sample: Record<string, unknown> = { beforeCapture: await layoutState(canvas) };
    wheelSamples.push(sample);
    // Check before capture as well: screenshot's own scroll-into-view must not erase evidence
    // that an unhandled wheel scrolled the document or an ancestor instead of the graph.
    expect(sample.beforeCapture).toEqual(immediatelyBefore);
    const captured = await captureCanvas(canvas, `${phase}-wheel`, info, captures);
    sample.capture = captured.filename;
    sample.afterCapture = await layoutState(canvas);
    expect(sample.afterCapture).toEqual(immediatelyBefore);
    sample.pixelsChanged = !captured.pixels.equals(still.pixels);
    if (captured.pixels.equals(still.pixels)) return false;
    changed = captured;
    return true;
  }).toBe(true);
  const after = await layoutState(canvas);
  const liveAfter = await contextState(canvas);
  Object.assign(observation, { stage: "final-geometry-and-context", after, liveAfter, pixelsChanged: changed !== undefined,
    changedCapture: changed?.filename ?? null });
  expect(after, "wheel must change canvas content, not viewport, ancestor scroll, clipping or canvas geometry").toEqual(immediatelyBefore);
  expect(liveAfter).toEqual(liveBefore);
  expect(changed).toBeDefined();
  observation.stage = "complete";
}

test("recreates an interactive WebGL graph after Home and real Back/Forward SPA returns", async ({ page }, info) => {
  const errors: string[] = [];
  const navigationRequests: string[] = [];
  const observations: Record<string, unknown>[] = [];
  const captures: Record<string, unknown>[] = [];
  const canvases: ElementHandle<HTMLCanvasElement>[] = [];
  let documentIdentity: JSHandle<Document> | null = null;
  let currentPhase = "setup";
  let listenersInstalled = false;
  let testFailure: string | null = null;
  try {
    page.on("pageerror", (error) => errors.push(error.message));
    page.on("request", (request) => {
      if (request.isNavigationRequest() && request.frame() === page.mainFrame()) navigationRequests.push(request.url());
    });
    listenersInstalled = true;
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.route("**/api/**", async (route) => {
      const url = route.request().url();
      if (/\/api\/snapshots\/\d+\/graph\b/.test(url)) return route.fulfill({ json: GRAPH });
      if (/\/api\/snapshots\/\d+(\?.*)?$/.test(url)) return route.fulfill({ json: META });
      return route.fulfill({ status: 404, json: { detail: "not mocked (unrelated panel)" } });
    });
    // The only document navigation. Early navigation/handle failures still reach evidence cleanup.
    currentPhase = "initial-document-goto";
    await page.goto("/snapshots/1/tools");
    currentPhase = "retain-document-identity";
    documentIdentity = await page.evaluateHandle(() => document);
    const sameDocument = async () => {
      expect(navigationRequests).toHaveLength(1);
      expect(documentIdentity).not.toBeNull();
      expect(await documentIdentity!.evaluate((original) => original === document)).toBe(true);
    };
    const enter = async (phase: string) => {
      currentPhase = phase;
      await expect(page).toHaveURL(/\/snapshots\/1\/tools$/);
      await expect(page.getByRole("heading", { name: /Fleet topology/ })).toBeVisible();
      const controls = page.getByRole("group", { name: "Topology view mode" });
      const three = controls.getByRole("button", { name: "3D", exact: true });
      await expect(three).toBeVisible({ timeout: 15_000 });
      // Whole-route re-entry creates a new panel; it cannot reuse mounted-toggle state.
      await expect(controls.getByRole("button", { name: "2D", exact: true })).toHaveAttribute("aria-pressed", "true");
      await expect(page.locator("canvas")).toHaveCount(0);
      await three.click();
      const canvas = page.locator("canvas");
      await expect(canvas).toHaveCount(1);
      await expect(canvas).toBeVisible({ timeout: 20_000 });
      await expect(three).toHaveAttribute("aria-pressed", "true");
      const handle = await canvas.elementHandle() as ElementHandle<HTMLCanvasElement> | null;
      const priorCanvases = [...canvases];
      if (handle !== null) canvases.push(handle); // Dispose it even if a later identity assertion fails.
      expect(handle).not.toBeNull();
      for (const old of priorCanvases) {
        expect(await old.evaluate((node) => node.isConnected)).toBe(false);
        expect(await handle!.evaluate((node, previous) => node !== previous, old)).toBe(true);
      }
      await sameDocument();
      await wheelChangesScene(page, canvas, phase, info, observations, captures);
      expect(errors).toEqual([]);
      return handle!;
    };
    const homeDetached = async (old: ElementHandle<HTMLCanvasElement>, phase: string) => {
      currentPhase = phase;
      await expect(page).toHaveURL(/\/$/);
      await expect(page.getByRole("button", { name: /Open a sample fleet/ })).toBeVisible();
      await expect(page.locator("canvas")).toHaveCount(0);
      await expect.poll(() => old.evaluate((node) => node.isConnected)).toBe(false);
      await sameDocument();
      observations.push({ phase, oldCanvasDetached: true, navigationRequests: [...navigationRequests] });
      expect(errors).toEqual([]);
    };
    const first = await enter("initial");
    currentPhase = "click-home-link";
    await page.locator("header.topbar").getByRole("link", { name: "Home", exact: true }).click();
    await homeDetached(first, "home-link");
    currentPhase = "first-history-back";
    await page.goBack();
    const second = await enter("first-back");
    // A second real history cycle catches a one-time-only remount without adding or resetting
    // the default overall test timeout. The old normal-motion mounted-toggle test stays separate.
    currentPhase = "history-forward";
    await page.goForward();
    await homeDetached(second, "forward-home");
    currentPhase = "second-history-back";
    await page.goBack();
    await enter("second-back");
    await sameDocument();
    expect(canvases).toHaveLength(3);
    expect(errors).toEqual([]);
    currentPhase = "complete";
  } catch (error) {
    testFailure = String(error);
    throw error;
  } finally {
    const cleanupErrors: string[] = [];
    for (const canvas of canvases) {
      try { await canvas.dispose(); } catch (error) { cleanupErrors.push(String(error)); }
    }
    if (documentIdentity !== null) {
      try { await documentIdentity.dispose(); } catch (error) { cleanupErrors.push(String(error)); }
    }
    // Cleanup attempts are independent of attachment success. No screenshot record claims a
    // completed image when capture failed, and runner/process loss cannot guarantee persistence.
    const report = { reducedMotion: "reduce", currentPhase, listenersInstalled, documentHandleCreated: documentIdentity !== null,
      testFailure, navigationRequests, errors, observations, captures, cleanupErrors };
    try {
      const output = info.outputPath("graph-route-reentry-observations.json");
      await writeFile(output, JSON.stringify(report, null, 2), { flag: "wx" });
      await info.attach("graph-route-reentry-observations.json", { path: output, contentType: "application/json" });
    } catch (error) {
      console.error("Graph re-entry evidence retention failed", String(error));
      if (testFailure === null) throw error;
    }
    if (testFailure === null) {
      expect(errors).toEqual([]);
      if (cleanupErrors.length > 0) throw new Error(`Graph test handle cleanup failed: ${cleanupErrors.join("; ")}`);
    }
  }
});
