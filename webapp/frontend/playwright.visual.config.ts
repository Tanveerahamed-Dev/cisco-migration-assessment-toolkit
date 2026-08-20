import { defineConfig, devices } from "@playwright/test";
import { DEFAULT_CARD_VIEWPORT, VISUAL_BASELINE_ID } from "./visual-e2e/oracle";

// Pixel baselines are deliberately Windows-specific: the product's typography is `system-ui`, so
// Windows (Segoe UI) and Linux (the runner's fallback face) are different valid products. The hosted
// Windows job is the pre-merge oracle; Ubuntu retains the behavior/WebGL E2E lane.
const PORT = process.env.VISUAL_PORT || "43973";
const ORIGIN = `http://127.0.0.1:${PORT}`;
const UPDATING_SNAPSHOTS = process.env.npm_lifecycle_event === "test:visual:update"
  || process.argv.some((argument) =>
    argument === "--update-snapshots" || argument.startsWith("--update-snapshots="));
const CAPTURING_ORACLE = process.env.VISUAL_ORACLE_CAPTURE === "1";

if (process.platform !== "win32" || process.arch !== "x64") {
  throw new Error(
    `Design visual tests use the ${VISUAL_BASELINE_ID} pixel oracle; run them on Windows x64.`,
  );
}
if (CAPTURING_ORACLE && (
  process.env.GITHUB_ACTIONS !== "true"
  || process.env.RUNNER_OS !== "Windows"
  || process.env.RUNNER_ARCH !== "X64"
)) {
  throw new Error("Canonical visual baselines may only be captured on GitHub Actions Windows x64.");
}

const snapshotPathTemplate = UPDATING_SNAPSHOTS && !CAPTURING_ORACLE
  ? "{testDir}/../test-results/visual-candidates/{platform}/{arg}{ext}"
  : `{testDir}/__screenshots__/${VISUAL_BASELINE_ID}/{arg}{ext}`;

export default defineConfig({
  testDir: "./visual-e2e",
  testMatch: "**/*.visual.spec.ts",
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: 0,
  timeout: 60_000,
  reporter: process.env.CI
    ? [["line"], ["html", { outputFolder: "playwright-report/visual", open: "never" }]]
    : "list",
  outputDir: "test-results/visual",
  snapshotPathTemplate,
  expect: {
    timeout: 15_000,
    toHaveScreenshot: {
      animations: "disabled",
      caret: "hide",
      scale: "css",
      // Pixelmatch's conventional 0.2 threshold can ignore a visible whole-card contrast shift.
      // Keep the general CSS/token ratchet strict; the measured topology raster exception is local.
      threshold: 0.02,
      maxDiffPixels: 0,
    },
  },
  use: {
    ...devices["Desktop Chrome"],
    baseURL: ORIGIN,
    viewport: DEFAULT_CARD_VIEWPORT,
    deviceScaleFactor: 1,
    colorScheme: "dark",
    contextOptions: { reducedMotion: "reduce" },
    locale: "en-US",
    timezoneId: "UTC",
    serviceWorkers: "block",
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { browserName: "chromium" } }],
  webServer: {
    command: `npm run serve:visual -- --port ${PORT} --strictPort`,
    url: `${ORIGIN}/visual-e2e/harness/`,
    timeout: 120_000,
    reuseExistingServer: false,
  },
});
