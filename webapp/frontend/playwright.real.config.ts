import { defineConfig, devices } from "@playwright/test";
import {
  REAL_ORIGIN, REAL_PORT, REAL_RUN_DIR, REAL_SPA_DIR, SYNTHETIC_COLLECTION_MANIFEST, SYNTHETIC_COLLECTION_ZIP,
} from "./e2e-real/paths";

// Real-backend E2E tier: the complement of playwright.config.ts, whose specs mock /api per test with
// page.route. Nothing is mocked here. The webServer builds the SPA from this checkout into a scratch
// directory (never the tracked dist/), then e2e-real/serve_real_backend.py starts the REAL FastAPI
// backend through its production entry point (webapp.backend.serve) on a fresh SQLite store, and
// the browser ingests the repository's synthetic collection through the real engine.
//
// Run it (hosted CI runs exactly this in webapp-ci's non-required "Real-backend browser E2E" job):
//   python -m pip install -e ".[dev]"          # once, from the repository root: backend + engine
//   cd webapp/frontend
//   npx playwright test --config playwright.real.config.ts
// The launcher needs a Python that can import this checkout's application dependencies:
// E2E_REAL_PYTHON overrides the default "python" (for example "py -3.12" on Windows). E2E_REAL_PORT
// and E2E_REAL_ROOT override the port and scratch root (e2e-real/paths.ts owns both).
const PYTHON = process.env.E2E_REAL_PYTHON || "python";
const quoted = (value: string) => `"${value}"`;

export default defineConfig({
  testDir: "./e2e-real",
  testMatch: "**/*.real.spec.ts",
  // One stateful walk against one store: serial, single worker, and no retry. A retry would replay
  // the walk into a store that already holds the first attempt, so a failure must stay a failure.
  fullyParallel: false,
  workers: 1,
  retries: 0,
  forbidOnly: !!process.env.CI,
  // Two real engine runs plus server-side projections and one canonical comparison.
  timeout: 20 * 60_000,
  expect: { timeout: 30_000 },
  outputDir: "test-results/real-backend/artifacts",
  reporter: process.env.CI
    ? [["line"], ["json", { outputFile: "test-results/real-backend/report.json" }]]
    : "list",
  use: {
    baseURL: REAL_ORIGIN,
    // Bounded so a missing control fails in a minute, not at the 20-minute test timeout. The two
    // long server waits (engine ingest, canonical comparison) carry their own explicit timeouts.
    actionTimeout: 60_000,
    navigationTimeout: 120_000,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: [
      `npm run build -- --outDir ${quoted(REAL_SPA_DIR)} --emptyOutDir`,
      [
        PYTHON, "e2e-real/serve_real_backend.py",
        "--run-dir", quoted(REAL_RUN_DIR),
        "--collection-zip", quoted(SYNTHETIC_COLLECTION_ZIP),
        "--collection-manifest", quoted(SYNTHETIC_COLLECTION_MANIFEST),
        "--dist", quoted(REAL_SPA_DIR),
        "--port", REAL_PORT,
      ].join(" "),
    ].join(" && "),
    // Liveness is the one /api route the access guard leaves open; the store is opened by then.
    url: `${REAL_ORIGIN}/api/health`,
    timeout: 300_000,
    // Never attach to a server started elsewhere: the walk asserts against a store it created.
    reuseExistingServer: false,
    stdout: "pipe",
    stderr: "pipe",
  },
});
