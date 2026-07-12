import { test, expect } from "@playwright/test";

// Tier-1 E2E: the real production build boots in a real browser and the landing route renders +
// behaves. jsdom can assert the component tree; only a browser proves the built SPA actually runs.
test.describe("Landing (real browser, production build)", () => {
  test("the SPA boots and renders the hero call-to-action + all four feature cards", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("button", { name: /Open a sample fleet/ })).toBeVisible();
    // target the card HEADINGS specifically — "keystone devices" also appears in the intro prose
    for (const title of ["Risk cockpit", "Keystone devices", "Campaign timeline", "Deep explorer"]) {
      await expect(page.getByRole("heading", { name: title })).toBeVisible();
    }
  });

  test("boots with no uncaught page errors (the built bundle actually runs)", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await page.goto("/");
    await expect(page.getByRole("button", { name: /Open a sample fleet/ })).toBeVisible();
    expect(errors, `unexpected page errors: ${errors.join("; ")}`).toEqual([]);
  });

  test("seeding the demo (mocked API) navigates to its snapshot", async ({ page }) => {
    await page.route("**/api/**", async (route) => {
      if (route.request().url().includes("/api/demo/seed")) {
        return route.fulfill({ json: { campaign: { id: 1 }, snapshot: { id: 5 } } });
      }
      return route.fulfill({ json: {} }); // benign empty for the snapshot page's other calls
    });
    await page.goto("/");
    await page.getByRole("button", { name: /Open a sample fleet/ }).click();
    await expect(page).toHaveURL(/\/snapshots\/5/); // the seed → navigate flow works end-to-end
  });
});
