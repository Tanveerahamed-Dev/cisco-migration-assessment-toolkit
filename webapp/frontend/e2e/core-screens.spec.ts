import { test, expect } from "@playwright/test";
import { overviewFixture, trustFixture, inventoryFixture, deviceFixture, findingsFixture } from "../src/test/projectionFixtures";

test("core assessment navigation, exact device, evidence keyboard and paging", async ({ page }) => {
  const legacyRequests: string[] = [];
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/api/meta") return route.fulfill({ json: { app: { name: "Atlas", byline: "Migration assessment" } } });
    if (url.pathname.endsWith("/scope-view")) return route.fulfill({ json: { available: true, href: "/scope/?snapshot=1" } });
    const view = url.pathname.match(/ui-projection\/(overview|trust|inventory|device|findings)/)?.[1];
    if (view === "overview") return route.fulfill({ json: overviewFixture() });
    if (view === "trust") return route.fulfill({ json: trustFixture() });
    if (view === "inventory") return route.fulfill({ json: inventoryFixture() });
    if (view === "device") {
      expect(url.searchParams.get("host")).toBe("edge/a~b");
      return route.fulfill({ json: deviceFixture() });
    }
    if (view === "findings") {
      const doc = findingsFixture(1, Number(url.searchParams.get("offset") || "0"));
      return route.fulfill({ json: url.pathname.endsWith("/lists") ? { ...doc, payload: undefined, list: doc.payload.rows } : doc });
    }
    legacyRequests.push(url.pathname);
    return route.fulfill({ status: 404, json: { detail: "Unexpected legacy route" } });
  });
  await page.goto("/snapshots/1");
  await expect(page.getByText("Synthetic fleet needs review")).toBeVisible();
  const evidence = page.getByRole("button", { name: "Evidence for Engine statement" });
  await evidence.click();
  const dialog = page.getByRole("dialog", { name: "Evidence: Engine statement" });
  await expect(dialog).toContainText("Synthetic fleet needs review");
  await page.keyboard.press("Tab");
  await expect(page.getByRole("button", { name: "Close evidence" })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(evidence).toBeFocused();
  await page.getByRole("link", { name: "Trust", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Evidence coverage" })).toBeVisible();
  await page.getByRole("link", { name: "Inventory", exact: true }).click();
  await page.getByRole("link", { name: "edge/a~b ↗" }).click();
  await expect(page.getByRole("heading", { name: "edge/a~b", level: 1 })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Health", exact: true })).toBeVisible();
  await page.getByRole("link", { name: "Findings", exact: true }).click();
  await expect(page.getByText("Synthetic finding", { exact: true })).toBeVisible();
  await page.getByText("Issue, remediation and evidence", { exact: true }).click();
  await expect(page.getByText("Synthetic owner remediation", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Next Findings page" }).click();
  await expect(page.getByText("Next source finding", { exact: true })).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole("navigation", { name: "Snapshot views" })).toBeVisible();
  const layout = await page.evaluate(() => ({ width: window.innerWidth, scroll: document.documentElement.scrollWidth,
    overflow: [...document.querySelectorAll("body *")].filter((node) => node.getBoundingClientRect().right > window.innerWidth + 1)
      .map((node) => ({ tag: node.tagName, className: node.className, right: node.getBoundingClientRect().right })).slice(0, 12) }));
  expect(layout.scroll, JSON.stringify(layout)).toBeLessThanOrEqual(layout.width);
  expect(legacyRequests).toEqual([]);
  expect(errors).toEqual([]);
});
