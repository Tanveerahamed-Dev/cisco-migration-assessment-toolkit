import { test, expect, type Page } from "@playwright/test";

// Dependency compatibility at the real browser boundary: observe the native API without replacing
// its update callback, promises or return value. API data below are explicit shell fixtures, not
// engine facts. This proves interaction/settlement, not intermediate pixels or a frame-time budget.
interface TransitionState {
  supported: boolean;
  started: number;
  updated: number;
  finished: number;
  errors: string[];
}
type ObservedWindow = Window & { __dependencyTransitions?: TransitionState };

const state = (page: Page) => page.evaluate(() => (window as ObservedWindow).__dependencyTransitions);

async function settled(page: Page, before: number, reduced: boolean) {
  if (reduced) {
    // Let the committed route/theme's next paint occur; no fixed delay or latency assertion.
    await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => resolve())));
    expect((await state(page))?.started).toBe(before);
  } else {
    await expect.poll(async () => (await state(page))?.started ?? 0).toBeGreaterThan(before);
    await expect.poll(async () => {
      const value = await state(page);
      return value !== undefined && value.started > before && value.updated === value.started
        && value.finished === value.started;
    }).toBe(true);
  }
  expect((await state(page))?.errors).toEqual([]);
}

for (const reducedMotion of ["no-preference", "reduce"] as const) {
  test(`route and theme retain native transition behavior (${reducedMotion})`, async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.emulateMedia({ reducedMotion });
    await page.addInitScript(() => {
      localStorage.setItem("assesshub-theme", "dark");
      const observed: TransitionState = {
        supported: typeof document.startViewTransition === "function",
        started: 0, updated: 0, finished: 0, errors: [],
      };
      (window as ObservedWindow).__dependencyTransitions = observed;
      if (!observed.supported) return;
      const native = document.startViewTransition.bind(document);
      document.startViewTransition = (...args: Parameters<Document["startViewTransition"]>) => {
        observed.started += 1;
        const transition = native(...args);
        transition.updateCallbackDone.then(
          () => { observed.updated += 1; },
          (error: unknown) => { observed.errors.push(`update: ${String(error)}`); },
        );
        transition.finished.then(
          () => { observed.finished += 1; },
          (error: unknown) => { observed.errors.push(`finish: ${String(error)}`); },
        );
        return transition;
      };
    });
    await page.route("**/api/**", (route) => {
      if (new URL(route.request().url()).pathname === "/api/meta") {
        return route.fulfill({ json: {
          app: { name: "Browser fixture", title: "Dependency compatibility fixture", byline: "Synthetic shell", release: "fixture" },
          engine_schema: "fixture", deliverables: [],
        } });
      }
      return route.fulfill({ status: 404, json: { detail: "Unrelated API is not a test success" } });
    });

    await page.goto("/");
    await expect(page.getByRole("button", { name: /Open a sample fleet/ })).toBeVisible();
    expect((await state(page))?.supported, "the pinned Chromium must exercise the supported native API").toBe(true);
    const header = page.locator("header.topbar");
    let before = (await state(page))!.started;
    await header.getByRole("button", { name: "Toggle theme", exact: true }).click();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
    await settled(page, before, reducedMotion === "reduce");

    before = (await state(page))!.started;
    await header.getByRole("link", { name: "About", exact: true }).click();
    await expect(page).toHaveURL(/\/about$/);
    await expect(page.getByRole("heading", { name: "About", exact: true })).toBeVisible();
    await settled(page, before, reducedMotion === "reduce");

    before = (await state(page))!.started;
    await header.getByRole("link", { name: "Home", exact: true }).click();
    await expect(page).toHaveURL(/\/$/);
    await expect(page.getByRole("button", { name: /Open a sample fleet/ })).toBeVisible();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
    await settled(page, before, reducedMotion === "reduce");
    expect(errors).toEqual([]);
  });
}
