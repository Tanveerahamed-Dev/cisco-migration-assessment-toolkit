import { expect, test, type Page } from "@playwright/test";
import { deviceFixture, published, topologyFixture, trustFixture } from "../src/test/projectionFixtures";

// The real React shell, d3-force SVG and dossier consume synthetic typed HTTP documents.
// Backend generation/parity and field acceptance remain separate hosted gates.
const HOST = "synthetic-edge-a";
const NODE = "Inspect node synthetic-edge-a: Synthetic engine node presentation";
const TABS = ["Network", "Findings", "Inventory", "Plan", "Change", "Reports"];
function device(sid: number, host: string) {
  const doc = deviceFixture(sid, host);
  const caveat = { id: "synthetic_device_only", owner: "synthetic.device.owner", applies_to: ["/devices/model"], text: "Synthetic device model needs physical confirmation." };
  return { ...doc, limitations: [caveat], payload: { ...doc.payload, identity: { ...doc.payload.identity,
    model: { ...published("Synthetic chassis"), subject: "/devices/model", caveats: [caveat.id] } } } };
}
async function mockNative(page: Page) {
  const calls: URL[] = [], forbidden: string[] = []; let staleDevice = false;
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url()); calls.push(url);
    if (url.pathname === "/api/meta") return route.fulfill({ json: { app: { name: "Atlas", byline: "Migration assessment" } } });
    if (url.pathname === "/api/campaigns") return route.fulfill({ json: [{ id: 1, name: "Synthetic engagement", description: "Synthetic assessment records" }] });
    if (url.pathname === "/api/campaigns/1") return route.fulfill({ json: { id: 1, name: "Synthetic engagement", description: "Synthetic assessment records", snapshots: [{ id: 1, label: "Synthetic baseline", uploaded_at: "2026-10-16T00:00:00Z" }] } });
    const sid = Number(url.pathname.split("/")[3]);
    if (/^\/api\/snapshots\/\d+$/.test(url.pathname)) return route.fulfill({ json: { id: sid, campaign_id: 1, label: "Synthetic baseline", uploaded_at: "2026-10-16T00:00:00Z" } });
    if (url.pathname.endsWith("/ui-projection/topology")) return route.fulfill({ json: topologyFixture(sid) });
    if (url.pathname.endsWith("/ui-projection/trust")) return route.fulfill({ json: trustFixture(sid) });
    if (url.pathname.endsWith("/ui-projection/device")) {
      const doc = device(sid, url.searchParams.get("host")!);
      return route.fulfill({ json: staleDevice ? { ...doc, identity: { ...doc.identity, sha256: `sha256:${"b".repeat(64)}` } } : doc });
    }
    forbidden.push(url.pathname);
    return route.fulfill({ status: 404, json: { detail: "Forbidden legacy or unexpected API route" } });
  });
  return { calls, forbidden, staleDevice: () => { staleDevice = true; } };
}
const map = (page: Page) => page.getByRole("img", { name: "Engine topology diagram" });
const tab = (page: Page, name: string) => page.getByRole("navigation", { name: "Snapshot tabs" }).getByRole("button", { name, exact: true });

test("native Engagements opens Network and retains dossier, map geometry and search across all five reserved tabs", async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 768 }); await page.emulateMedia({ reducedMotion: "reduce" });
  const api = await mockNative(page), errors: string[] = []; page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/engagements");
  await expect(page.getByRole("button", { name: /New assessment/ })).toBeDisabled();
  await expect(page.getByRole("complementary", { name: "Engagement rail" })).toContainText("Synthetic engagement");
  await page.getByRole("region", { name: "Engagements", exact: true }).getByRole("link", { name: /Synthetic engagement/ }).click();
  await expect(page).toHaveURL(/\/engagements\/1$/);
  await page.getByRole("region", { name: "Assessment snapshots" }).getByRole("link", { name: /Synthetic baseline/ }).click();
  await expect(map(page)).toBeVisible(); await expect(tab(page, "Network")).toHaveAttribute("aria-current", "page");
  expect(await page.getByRole("navigation", { name: "Snapshot tabs" }).getByRole("button").allTextContents()).toEqual(TABS);
  await expect(page.locator("iframe")).toHaveCount(0); await expect(page.getByRole("link", { name: /Explorer|Scope|Tools|AssessHub/i })).toHaveCount(0);
  const projections = api.calls.filter((url) => url.pathname.includes("/ui-projection/")).map((url) => url.pathname);
  expect(projections.sort()).toEqual(["/api/snapshots/1/ui-projection/topology", "/api/snapshots/1/ui-projection/trust"]);
  await test.info().attach("adr8-network-desktop-default", { body: await page.screenshot(), contentType: "image/png" });
  const originalMap = await map(page).elementHandle();
  await page.getByRole("button", { name: NODE }).click();
  const dossier = page.getByRole("complementary", { name: "Device dossier" }); await expect(dossier.getByText("Synthetic chassis", { exact: true })).toBeVisible();
  expect(api.calls.filter((url) => url.pathname.endsWith("/device")).map((url) => url.searchParams.get("host"))).toEqual([HOST]);
  await page.getByRole("searchbox", { name: "Find device name" }).fill("edge-a");
  const unzoomed = await map(page).getAttribute("viewBox"); await page.getByRole("button", { name: "Zoom in", exact: true }).click();
  const zoomed = await map(page).getAttribute("viewBox"); expect(zoomed).not.toBe(unzoomed);
  for (const name of TABS.slice(1)) {
    await tab(page, name).click(); await expect(page.getByRole("heading", { name, exact: true })).toBeVisible();
    await expect(page.getByText("This tab is reserved for a subsequent reviewed increment.")).toBeVisible();
    await expect(map(page)).toBeHidden();
    await page.getByRole("button", { name: "Return to Network" }).click(); await expect(map(page)).toBeVisible();
    expect(await map(page).evaluate((node, previous) => node === previous, originalMap)).toBe(true);
    await expect(page.getByRole("button", { name: NODE })).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByRole("searchbox", { name: "Find device name" })).toHaveValue("edge-a");
    await expect(map(page)).toHaveAttribute("viewBox", zoomed!); await expect(dossier).toContainText("Synthetic chassis");
  }
  await dossier.getByRole("button", { name: "Info for model", exact: true }).click();
  const drawer = page.getByRole("dialog", { name: "Evidence: model" });
  await expect(drawer).toContainText("Synthetic device model needs physical confirmation.");
  await expect(drawer).toContainText("synthetic.device.owner"); await expect(drawer).toContainText(`sha256:${"a".repeat(64)}`);
  await page.keyboard.press("Escape"); await expect(drawer).toHaveCount(0);
  await expect(dossier.getByRole("button", { name: "Info for model", exact: true })).toBeFocused();
  expect(api.calls.filter((url) => url.pathname.endsWith("/ui-projection/topology"))).toHaveLength(1);
  expect(api.calls.filter((url) => url.pathname.endsWith("/ui-projection/device"))).toHaveLength(1);
  expect(api.forbidden).toEqual([]); expect(errors).toEqual([]);
});

test("narrow application window reaches canvas, selection evidence and every reserved tab without horizontal overflow", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 }); await page.emulateMedia({ reducedMotion: "reduce" });
  const api = await mockNative(page); await page.goto("/snapshots/1"); await expect(map(page)).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  const deviceTools = page.getByRole("group", { name: "Device tools" });
  for (const name of ["If this fails", "Path", "Endpoint", "VLAN"]) await expect(deviceTools.getByRole("button", { name, exact: true })).toBeDisabled();
  await test.info().attach("adr8-network-narrow-default", { body: await page.screenshot(), contentType: "image/png" });
  await page.getByRole("button", { name: NODE }).click();
  const dossier = page.getByRole("complementary", { name: "Device dossier" });
  await dossier.getByRole("region", { name: "Device identity" }).scrollIntoViewIfNeeded();
  await expect(dossier.getByText("Synthetic chassis", { exact: true })).toBeVisible();
  const bounds = await dossier.boundingBox(); expect(bounds).not.toBeNull(); expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(391);
  await dossier.getByRole("button", { name: "Info for model", exact: true }).click();
  const drawer = page.getByRole("dialog", { name: "Evidence: model" }); await expect(drawer).toBeVisible();
  await expect(drawer).toContainText("Synthetic device model needs physical confirmation.");
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await test.info().attach("adr8-dossier-narrow-evidence", { body: await page.screenshot(), contentType: "image/png" });
  await page.getByRole("button", { name: "Close evidence" }).click();
  for (const name of TABS.slice(1)) {
    await tab(page, name).click(); await expect(tab(page, name)).toHaveAttribute("aria-current", "page");
    await expect(page.getByText("This tab is reserved for a subsequent reviewed increment.")).toBeVisible();
    await page.getByRole("button", { name: "Return to Network" }).click();
  }
  await map(page).scrollIntoViewIfNeeded();
  await page.getByRole("checkbox", { name: "Collected devices only" }).check();
  await expect(page.getByRole("button", { name: "Inspect node synthetic-peer-b: Synthetic uncollected peer" })).toHaveCount(0);
  await page.getByRole("checkbox", { name: "Collected devices only" }).uncheck();
  await expect(page.getByRole("button", { name: "Inspect node synthetic-peer-b: Synthetic uncollected peer" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390); expect(api.forbidden).toEqual([]);
});

test("a dossier from a stale stored source is refused without substituting another answer", async ({ page }) => {
  const api = await mockNative(page); api.staleDevice(); await page.goto("/snapshots/1"); await expect(map(page)).toBeVisible();
  await page.getByRole("button", { name: NODE }).click();
  const dossier = page.getByRole("complementary", { name: "Device dossier" });
  await expect(dossier.getByRole("alert")).toContainText("Stored snapshot identity or engine context changed");
  await expect(dossier.getByRole("region", { name: "Device identity" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: NODE })).toHaveAttribute("aria-pressed", "true");
  await expect(dossier.getByRole("button", { name: "Retry device dossier" })).toBeVisible(); expect(api.forbidden).toEqual([]);
});
