import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { expect, test, type Page } from "@playwright/test";
import {
  DEFAULT_CARD_VIEWPORT,
  PRODUCT_PANE_WIDTH,
  VISUAL_BASELINE_ID,
} from "./oracle";

const configPath = fileURLToPath(new URL("../../../.design-sync/config.json", import.meta.url));
const config = JSON.parse(readFileSync(configPath, "utf8")) as {
  componentSrcMap: Record<string, string>;
  overrides?: Record<string, {
    cardMode?: string;
    primaryStory?: string;
    viewport?: string;
  }>;
};

// Explicit on purpose: a new/renamed story must update the reviewed visual contract and its pixels.
const EXPECTED_VARIANTS: Record<string, string[]> = {
  ArchReviewPanel: ["AskTheEngineer"],
  Bars: ["EndpointsByVlan", "FindingsByCategory"],
  CableMap: ["MeridianCabling"],
  CausalFlowPanel: ["AllFindings"],
  CountUp: ["Formats", "StatStrip"],
  CutoverPlanner: ["GatedRunOfShow"],
  DemoDataProvider: ["WrappedDashboardRegion"],
  DesignBlueprintPanel: ["TargetStateBlueprint"],
  ErrorBoundary: ["CatchesRenderError", "PassesChildrenThrough"],
  ErrorBox: ["ApiError", "InDashboardSlot"],
  Gauge: ["BandColours", "HealthTrio"],
  Kpi: ["DashboardRow", "TextValues", "Tones"],
  Loading: ["CustomLabel", "Default"],
  SegBar: ["GateMix", "HealthBands", "StrategySplit"],
  SevChip: ["AllSeverities", "CustomLabels", "InFindingsTable"],
  Skeleton: ["Bars"],
  SkelLines: ["ContextLabel", "Default"],
  SkelTable: ["Default", "DetailSection"],
  TopologyGraph: ["InPanel", "MeridianFleet"],
  VerificationBadge: ["AllStates", "Compact", "InSnapshotHeader", "NeverOverClaims"],
  VerificationWarning: ["InSnapshotPage", "LegacySnapshot", "PartialCoverage", "Unverified"],
};

const COMPONENTS = Object.keys(config.componentSrcMap).sort();
const snapshotDirectory = fileURLToPath(
  new URL(`./__screenshots__/${VISUAL_BASELINE_ID}/`, import.meta.url),
);
const DATA_COMPONENTS = new Set([
  "ArchReviewPanel",
  "CableMap",
  "CausalFlowPanel",
  "CutoverPlanner",
  "DemoDataProvider",
  "DesignBlueprintPanel",
  "TopologyGraph",
]);
const READY_SELECTOR: Record<string, string> = {
  ArchReviewPanel: "[role=tablist]",
  CableMap: "svg",
  CausalFlowPanel: "svg[role=img]",
  CutoverPlanner: ".wave-card",
  DemoDataProvider: "svg",
  DesignBlueprintPanel: "[role=tablist]",
  TopologyGraph: "svg",
};
const EXPECTED_BOUNDARY_ERROR = /render exploded: cannot read snapshot section 'topology'|above error occurred in the <Bomb> component|React will try to recreate this component tree/i;
// Chromium occasionally flips eight perceptually-different anti-alias pixels in the scaled 2D
// topology SVG across fresh processes. Keep that measured exception fixed and local to this card;
// every other component retains the global strict threshold and zero-pixel budget.
const TOPOLOGY_RASTER_BUDGET = 16;

type HarnessState = {
  component: string;
  components: string[];
  variants: string[];
  renderedVariants: string[];
  mode: "grid" | "column" | "single";
  primaryStory: string | null;
  viewport: string;
  error?: string;
};

type CardPresentation = Omit<HarnessState, "component" | "components" | "variants" | "error"> & {
  viewportSize: { width: number; height: number };
};

function presentationFor(component: string): CardPresentation {
  const override = config.overrides?.[component] || {};
  if (override.cardMode && override.cardMode !== "column" && override.cardMode !== "single") {
    throw new Error(`Unsupported cardMode "${override.cardMode}" for ${component}`);
  }

  const variants = EXPECTED_VARIANTS[component];
  if (override.primaryStory && !variants.includes(override.primaryStory)) {
    throw new Error(`Unknown primaryStory "${override.primaryStory}" for ${component}`);
  }

  const rawViewport = override.viewport
    || `${DEFAULT_CARD_VIEWPORT.width}x${DEFAULT_CARD_VIEWPORT.height}`;
  const viewportMatch = rawViewport.match(/^([1-9]\d*)x([1-9]\d*)$/);
  if (!viewportMatch) {
    throw new Error(`Invalid viewport "${rawViewport}" for ${component}`);
  }
  const viewportSize = {
    width: Math.min(Number(viewportMatch[1]), 2000),
    height: Math.min(Number(viewportMatch[2]), 2000),
  };
  const mode = (override.cardMode || "grid") as CardPresentation["mode"];
  const primaryStory = override.primaryStory || null;
  const renderedVariants = [...variants];
  if (mode === "column" && primaryStory) {
    const primaryIndex = renderedVariants.indexOf(primaryStory);
    if (primaryIndex > 0) {
      renderedVariants.unshift(renderedVariants.splice(primaryIndex, 1)[0]);
    }
  } else if (mode === "single") {
    renderedVariants.splice(0, renderedVariants.length, primaryStory || variants[0]);
  }

  return {
    mode,
    primaryStory,
    renderedVariants,
    viewport: `${viewportSize.width}x${viewportSize.height}`,
    viewportSize,
  };
}

async function waitForStableCard(page: Page, component: string) {
  const card = page.getByTestId("design-card");
  const presentation = presentationFor(component);
  await expect(card).toHaveAttribute("data-component", component);
  await expect(card.locator(".ds-variant")).toHaveCount(presentation.renderedVariants.length);
  expect(await card.locator(".ds-variant").evaluateAll((elements) =>
    elements.map((element) => element.getAttribute("data-variant"))))
    .toEqual(presentation.renderedVariants);

  if (DATA_COMPONENTS.has(component)) {
    await expect(card.locator(READY_SELECTOR[component]).first()).toBeVisible();
    await expect(card.locator(".loading")).toHaveCount(0);
  }

  await page.evaluate(async () => {
    await document.fonts.ready;
    await Promise.all(
      Array.from(document.images, (image) => image.complete ? Promise.resolve() : image.decode()),
    );
    await new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
  });

  let previous = "";
  let consecutiveStableSamples = 0;
  await expect.poll(async () => {
    const signature = await card.evaluate((element) => {
      const boxes = Array.from(element.querySelectorAll(".ds-variant"), (cell) => {
        const rect = cell.getBoundingClientRect();
        return [rect.x, rect.y, rect.width, rect.height, cell.innerHTML];
      });
      const rect = element.getBoundingClientRect();
      return JSON.stringify([rect.width, rect.height, boxes]);
    });
    consecutiveStableSamples = signature === previous ? consecutiveStableSamples + 1 : 0;
    previous = signature;
    return consecutiveStableSamples;
  }, {
    intervals: [100, 150, 200, 250],
    message: `${component} layout did not settle`,
  }).toBeGreaterThanOrEqual(2);

  return card;
}

test("the visual manifest is exactly the configured 21 components and 42 variants", () => {
  test.skip(process.env.VISUAL_ORACLE_CAPTURE === "1", "capture writes pixels before manifest validation");
  expect(COMPONENTS).toEqual(Object.keys(EXPECTED_VARIANTS).sort());
  expect(COMPONENTS).toHaveLength(21);
  expect(Object.values(EXPECTED_VARIANTS).flat()).toHaveLength(42);
  expect(readdirSync(snapshotDirectory).filter((name) => name.endsWith(".png")).sort())
    .toEqual(COMPONENTS.flatMap((name) => [`${name}-728.png`, `${name}.png`]).sort());
});

for (const component of COMPONENTS) {
  test(`${component} composite card matches its reviewed pixels`, async ({ page, baseURL }) => {
    const pageErrors: string[] = [];
    const consoleErrors: string[] = [];
    const blockedRequests: string[] = [];
    const blockedWebSockets: string[] = [];
    const localUrl = new URL(baseURL!);
    const localOrigin = localUrl.origin;
    const presentation = presentationFor(component);

    page.on("pageerror", (error) => pageErrors.push(error.message));
    page.on("console", (message) => {
      if (message.type() === "error") consoleErrors.push(message.text());
    });
    await page.route("**/*", async (route) => {
      const url = new URL(route.request().url());
      if (url.origin === localOrigin || url.protocol === "data:" || url.protocol === "blob:") {
        await route.continue();
      } else {
        blockedRequests.push(url.href);
        await route.abort("blockedbyclient");
      }
    });
    await page.routeWebSocket(/.*/, async (webSocket) => {
      const url = new URL(webSocket.url());
      if (url.hostname === localUrl.hostname && url.port === localUrl.port) {
        webSocket.connectToServer();
      } else {
        blockedWebSockets.push(url.href);
        await webSocket.close({ code: 1008, reason: "Visual previews are offline-only" });
      }
    });

    await page.clock.setFixedTime("2026-06-13T06:32:00.000Z");
    await page.setViewportSize(presentation.viewportSize);
    await page.goto(`/visual-e2e/harness/?component=${encodeURIComponent(component)}`);
    const card = await waitForStableCard(page, component);
    expect(await page.evaluate(() => matchMedia("(prefers-reduced-motion: reduce)").matches))
      .toBe(true);

    const state = await page.evaluate(() => (window as any).__VISUAL_HARNESS__) as HarnessState;
    expect(state.error).toBeUndefined();
    expect(state.component).toBe(component);
    expect(state.components).toEqual(COMPONENTS);
    expect(state.variants).toEqual(EXPECTED_VARIANTS[component]);
    expect(state.renderedVariants).toEqual(presentation.renderedVariants);
    expect(state.mode).toBe(presentation.mode);
    expect(state.primaryStory).toBe(presentation.primaryStory);
    expect(state.viewport).toBe(presentation.viewport);

    if (component === "TopologyGraph") {
      await expect(card.locator("canvas")).toHaveCount(0);
      const twoDimensionalToggles = card.getByRole("button", { name: "2D", exact: true });
      await expect(twoDimensionalToggles).toHaveCount(2);
      expect(await twoDimensionalToggles.evaluateAll((buttons) =>
        buttons.map((button) => button.getAttribute("aria-pressed"))))
        .toEqual(["true", "true"]);
    }

    const screenshotOptions = component === "TopologyGraph"
      ? { threshold: 0.2, maxDiffPixels: TOPOLOGY_RASTER_BUDGET }
      : undefined;
    await expect(card).toHaveScreenshot(`${component}.png`, screenshotOptions);

    // The documented product-pane bound gets its own reviewed pixels as well as overflow proof.
    await page.setViewportSize({ width: PRODUCT_PANE_WIDTH, height: DEFAULT_CARD_VIEWPORT.height });
    const responsiveCard = await waitForStableCard(page, component);
    await expect(responsiveCard).toHaveScreenshot(`${component}-728.png`, screenshotOptions);
    const overflow = await page.evaluate(() => ({
      page: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      cells: Array.from(document.querySelectorAll<HTMLElement>(".ds-cell"), (cell) =>
        cell.scrollWidth - cell.clientWidth),
    }));
    expect(overflow.page, `${component} creates horizontal page overflow at 728px`).toBeLessThanOrEqual(1);
    expect(Math.max(0, ...overflow.cells), `${component} overflows a design card cell at 728px`).toBeLessThanOrEqual(1);
    expect(blockedRequests, "visual previews must remain offline/local-only").toEqual([]);
    expect(blockedWebSockets, "visual previews must not open external WebSockets").toEqual([]);

    if (component === "ErrorBoundary") {
      const boundaryErrors = [...pageErrors, ...consoleErrors];
      expect(boundaryErrors.length, "the recovery preview must exercise its intentional render failure").toBeGreaterThan(0);
      expect(boundaryErrors.every((message) => EXPECTED_BOUNDARY_ERROR.test(message))).toBe(true);
    } else {
      expect(pageErrors, `unexpected ${component} page errors`).toEqual([]);
      expect(consoleErrors, `unexpected ${component} console errors`).toEqual([]);
    }
  });
}
