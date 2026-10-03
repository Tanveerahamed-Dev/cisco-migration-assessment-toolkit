import { test, expect, type Page } from "@playwright/test";
import { overviewFixture, pathFixture, topologyFixture } from "../src/test/projectionFixtures";
import { EMBED_PROTOCOL, PROJECTION_SCHEMA, TOPOLOGY_STYLE_SCHEMA } from "../src/projectionEmbed";

// This suite exercises the real AssessHub build with explicitly synthetic owner responses.
// The child refusal case tests a real iframe/message boundary; it does not claim Scope rendering.
async function installProjectionRoutes(page: Page, scope: "unavailable" | "refusal" = "unavailable") {
  const unexpected: string[] = [], errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/api/meta") return route.fulfill({ json: { app: { name: "Atlas", byline: "Migration assessment" } } });
    if (url.pathname === "/api/snapshots/1/scope-view") return route.fulfill({ json: {
      available: true, status: "ready", href: "/scope/snapshots/1/", detail: "Synthetic legacy capability",
      engine_projection: { available: scope === "refusal", protocol: EMBED_PROTOCOL, projection_schema: PROJECTION_SCHEMA,
        style_schema: TOPOLOGY_STYLE_SCHEMA, href: "/scope/snapshots/1/?engine_projection=1",
        detail: "Synthetic current projection build is unavailable. The 2-D map remains available." },
    } });
    if (url.pathname === "/api/snapshots/1/ui-projection/overview") return route.fulfill({ json: overviewFixture() });
    if (url.pathname === "/api/snapshots/1/ui-projection/topology") return route.fulfill({ json: topologyFixture() });
    if (url.pathname === "/api/snapshots/1/ui-projection/topology/path") {
      expect(url.searchParams.get("src_ip")).toBe("192.0.2.10");
      expect(url.searchParams.get("dst_ip")).toBe("198.51.100.10");
      return route.fulfill({ json: pathFixture() });
    }
    unexpected.push(url.pathname);
    return route.fulfill({ status: 404, json: { detail: "Unexpected route: no legacy graph or raw snapshot is permitted" } });
  });
  if (scope === "refusal") await page.route("**/scope/snapshots/1/**", async (route) => route.fulfill({
    contentType: "text/html", body: `<!doctype html><title>Synthetic child refusal</title><script>
      const nonce = new URL(location.href).searchParams.get('projection_nonce');
      parent.postMessage({protocol:${JSON.stringify(EMBED_PROTOCOL)},type:'refused',nonce,
        identity:null,context_digest:null,code:'WEBGL_UNAVAILABLE',request_id:null},location.origin);
    </script>`,
  }));
  return { unexpected, errors };
}

test("fifth tab renders engine styles, evidence and a usable path without legacy fetching", async ({ page }) => {
  const observed = await installProjectionRoutes(page);
  await page.goto("/snapshots/1");
  await page.getByRole("link", { name: "Topology & Paths", exact: true }).click();
  await expect(page.getByText("All projected list pages loaded.", { exact: false })).toBeVisible();
  const map = page.getByRole("img", { name: "Engine topology diagram" });
  await expect(map).toBeVisible();
  const node = page.getByRole("button", { name: "Inspect node synthetic-edge-a: Synthetic engine node presentation" });
  const peer = page.getByRole("button", { name: "Inspect node synthetic-peer-b: Synthetic uncollected peer" });
  await expect(peer).toHaveClass(/topology-tone-muted/);
  await expect(peer).toHaveAttribute("data-stroke", "dotted");
  await node.focus(); await page.keyboard.press("Enter");
  await expect(page.getByRole("region", { name: "Topology record details" })).toContainText("/cable_map/nodes/0");
  await page.getByRole("button", { name: "Evidence for host", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "Evidence: host" })).toContainText("synthetic-edge-a");
  await page.keyboard.press("Escape");
  await page.getByLabel("Source IP", { exact: true }).fill("192.0.2.10");
  await page.getByLabel("Destination IP", { exact: true }).fill("198.51.100.10");
  await page.getByRole("button", { name: "Investigate path", exact: true }).click();
  const result = page.getByRole("region", { name: "Route-model result" });
  await expect(result).toContainText("Synthetic owner: reached with a dropping leg");
  await expect(node).toHaveClass(/path-node/);
  await expect(peer).not.toHaveClass(/path-node/);
  await page.getByText("Complete owner result, including ECMP and MTU details", { exact: true }).click();
  await expect(result).toContainText("egress_interface_not_observed");
  await expect(result).toContainText("observed_discard");
  await page.getByLabel("Destination IP", { exact: true }).fill("198.51.100.20");
  await expect(result).toHaveCount(0); await expect(node).not.toHaveClass(/path-node/);
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(map).toBeVisible();
  const layout = await page.evaluate(() => ({ width: innerWidth, scroll: document.documentElement.scrollWidth }));
  expect(layout.scroll).toBeLessThanOrEqual(layout.width);
  expect(observed.unexpected).toEqual([]); expect(observed.errors).toEqual([]);
});

test("unavailable current Scope retains the map and path form with a visible recovery", async ({ page }) => {
  const observed = await installProjectionRoutes(page);
  await page.goto("/snapshots/1?view=topology");
  await page.getByRole("button", { name: "3-D investigation", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("current projection build is unavailable");
  await expect(page.getByTitle("Atlas Scope engine topology")).toHaveCount(0);
  await expect(page.getByRole("img", { name: "Engine topology diagram" })).toBeVisible();
  await expect(page.getByLabel("Source IP", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Return to 2-D" }).click();
  await expect(page.getByRole("button", { name: "2-D map", exact: true })).toHaveAttribute("aria-pressed", "true");
  expect(observed.unexpected).toEqual([]); expect(observed.errors).toEqual([]);
});

test("real child-window WebGL refusal leaves the 2-D investigation usable", async ({ page }) => {
  const observed = await installProjectionRoutes(page, "refusal");
  await page.goto("/snapshots/1?view=topology");
  await page.getByRole("button", { name: "3-D investigation", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("WebGL is unavailable");
  await expect(page.getByTitle("Atlas Scope engine topology")).toHaveCount(0);
  await expect(page.getByRole("img", { name: "Engine topology diagram" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Return to 2-D" })).toBeEnabled();
  expect(observed.unexpected).toEqual([]); expect(observed.errors).toEqual([]);
});
