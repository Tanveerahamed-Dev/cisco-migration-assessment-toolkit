import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { expect, test, type Frame, type Page } from "@playwright/test";
import { overviewFixture } from "../src/test/projectionFixtures";

// Same real offline renderer bytes as offline-explorer.spec.ts. Only HTTP delivery and Core
// documents are mocked: this proves workspace/renderer integration, not backend generation parity.
const EXPLORER = readFileSync(fileURLToPath(new URL("../../../cisco_toolkit/blast_radius_explorer.html", import.meta.url)));
const CANONICAL_MODE_COUNT = 14;

async function mockWorkspace(page: Page) {
  const requests: string[] = [];
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/api/meta") return route.fulfill({ json: { app: { name: "Atlas", byline: "Migration assessment" } } });
    if (url.pathname.endsWith("/explorer")) {
      requests.push(url.pathname);
      return route.fulfill({ contentType: "text/html; charset=utf-8", body: EXPLORER });
    }
    if (url.pathname.endsWith("/scope-view")) return route.fulfill({ json: { available: false, href: null } });
    if (url.pathname.endsWith("/ui-projection/overview")) return route.fulfill({ json: overviewFixture() });
    return route.fulfill({ status: 404, json: { detail: "Unexpected test API route" } });
  });
  return requests;
}

async function readyExplorer(page: Page): Promise<Frame> {
  const iframe = page.locator('iframe[title="Network Migration Explorer"]');
  await expect(iframe).toBeVisible();
  const frame = await iframe.contentFrame();
  // Locator.contentFrame is a FrameLocator; an actual Frame allows registry reads without
  // adding a same-origin permission to the production sandbox.
  await expect(frame.locator("#src")).toHaveText("DEMO TOPOLOGY");
  await expect(frame.locator("#coach")).toBeVisible();
  await frame.locator("#coachSkip").click();
  await expect(frame.locator("#coach")).toBeHidden();
  const actual = page.frames().find((candidate) => /\/api\/snapshots\/\d+\/explorer(?:#|$)/.test(candidate.url()));
  if (!actual) throw new Error("The workspace did not load its Explorer frame");
  return actual;
}

test("desktop snapshot opens Cable Map with all registered tools, and retains an investigation across Core tabs", async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 768 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  const requests = await mockWorkspace(page);
  const errors: string[] = [];
  const popups: Page[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("popup", (popup) => popups.push(popup));
  await page.goto("/snapshots/1/");
  const iframe = page.getByTitle("Network Migration Explorer");
  await expect(iframe).toHaveAttribute("src", "/api/snapshots/1/explorer#mode=cablemap");
  await expect(iframe).toHaveAttribute("sandbox", "allow-scripts allow-downloads allow-modals");
  const frame = await readyExplorer(page);
  const desktopBox = await iframe.boundingBox();
  expect(desktopBox).not.toBeNull();
  expect(desktopBox!.height).toBeGreaterThan(400);
  expect(desktopBox!.y + desktopBox!.height).toBeLessThanOrEqual(769);
  await expect(frame.locator('#modes button[data-mode="cablemap"]')).toHaveAttribute("aria-pressed", "true");
  await expect(frame.locator("#svg #vp")).toBeAttached();
  await expect.poll(() => frame.locator("#svg #vp").evaluate((node) => node.childElementCount)).toBeGreaterThan(0);
  const modes = await frame.evaluate("MODES.map(({ key }) => key)") as string[];
  expect(modes).toHaveLength(CANONICAL_MODE_COUNT);
  expect(new Set(modes).size).toBe(modes.length);
  expect(await frame.locator("#modes button[data-mode]").evaluateAll((buttons) => buttons.map((node) => (node as HTMLElement).dataset.mode))).toEqual(modes);
  for (const mode of modes) {
    await test.step(`workspace tool ${mode}`, async () => {
      const button = frame.locator(`#modes button[data-mode="${mode}"]`);
      await button.click();
      await expect(button).toHaveAttribute("aria-pressed", "true");
      await expect(frame.locator('#modes button[aria-pressed="true"]')).toHaveCount(1);
      await expect(frame.locator("#legend h4")).toHaveText(`Legend — ${mode}`);
      await expect(frame.locator("#panel")).toContainText(/\S/);
    });
  }
  const retainedMode = modes[modes.length - 1];
  await test.info().attach("workspace-desktop", { body: await page.screenshot(), contentType: "image/png" });
  await page.getByRole("link", { name: "Overview", exact: true }).click();
  await expect(page.getByText("Synthetic fleet needs review")).toBeVisible();
  await expect(iframe).toBeHidden();
  await expect(page.getByRole("region", { name: "Core assessment" })).toBeVisible();
  await page.getByRole("link", { name: "Network", exact: true }).click();
  await expect(iframe).toBeVisible();
  expect(page.frames()).toContain(frame);
  await expect(frame.locator(`#modes button[data-mode="${retainedMode}"]`)).toHaveAttribute("aria-pressed", "true");
  expect(requests).toEqual(["/api/snapshots/1/explorer"]);
  await page.getByRole("button", { name: "Focus topology" }).click();
  await expect(iframe).toBeFocused();
  await page.getByRole("button", { name: "Reload topology" }).click();
  const replacement = await readyExplorer(page);
  expect(replacement).not.toBe(frame);
  await expect(replacement.locator('#modes button[data-mode="cablemap"]')).toHaveAttribute("aria-pressed", "true");
  expect(requests).toEqual(["/api/snapshots/1/explorer", "/api/snapshots/1/explorer"]);
  expect(popups).toEqual([]);
  expect(errors).toEqual([]);
});

test("narrow application window keeps Network and secondary navigation reachable", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  const requests = await mockWorkspace(page);
  // A Core deep link is lazy: no hidden Explorer generation or first-run tour.
  await page.goto("/snapshots/1?view=overview");
  await expect(page.getByText("Synthetic fleet needs review")).toBeVisible();
  await expect(page.getByTitle("Network Migration Explorer")).toHaveCount(0);
  expect(requests).toEqual([]);
  await page.getByRole("link", { name: "Network", exact: true }).click();
  const frame = await readyExplorer(page);
  const box = await page.getByTitle("Network Migration Explorer").boundingBox();
  expect(box).not.toBeNull();
  expect(box!.width).toBeGreaterThan(300);
  expect(box!.height).toBeGreaterThan(200);
  expect(box!.x + box!.width).toBeLessThanOrEqual(391);
  expect(box!.y + box!.height).toBeLessThanOrEqual(845);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await expect(page.getByRole("navigation", { name: "Snapshot views" })).toBeVisible();
  await page.getByText("Workspace info", { exact: true }).click();
  await expect(page.getByText(/Flow is not canonical Traffic Assurance/)).toBeVisible();
  await page.getByText("Workspace info", { exact: true }).click();
  const modes = await frame.evaluate("MODES.map(({ key }) => key)") as string[];
  expect(modes).toHaveLength(CANONICAL_MODE_COUNT);
  // Scrollable tool row must allow actual clicks even in the smaller application window.
  for (const mode of modes) {
    const button = frame.locator(`#modes button[data-mode="${mode}"]`);
    await button.click();
    await expect(button).toHaveAttribute("aria-pressed", "true");
  }
  await test.info().attach("workspace-narrow", { body: await page.screenshot(), contentType: "image/png" });
  await page.getByRole("link", { name: "Overview", exact: true }).click();
  await expect(page.getByText("Synthetic fleet needs review")).toBeVisible();
  await expect(page.getByTitle("Network Migration Explorer")).toBeHidden();
});
