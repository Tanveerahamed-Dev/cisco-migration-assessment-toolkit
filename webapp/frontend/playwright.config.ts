import { defineConfig, devices } from "@playwright/test";

// E2E tier — the honest complement to the Vitest/jsdom unit+integration tests. This runs the REAL
// production build in a REAL Chromium (WebGL available), so it can verify what jsdom fundamentally
// cannot: the SPA actually boots, and the three.js / react-force-graph-3d fabric actually renders a
// WebGL canvas. The API is mocked per-test via page.route — no backend needed.
export default defineConfig({
  testDir: "./e2e",
  testMatch: "**/*.spec.ts",
  fullyParallel: true,
  forbidOnly: !!process.env.CI, // a stray test.only fails CI, never silently narrows the run
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? "line" : "list",
  use: {
    baseURL: "http://localhost:4173",
    trace: "on-first-retry",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  // Serve the actual production build (tsc + vite build), then vite preview — the same bytes users get.
  webServer: {
    command: "npm run build && npm run preview -- --port 4173 --strictPort",
    url: "http://localhost:4173",
    timeout: 180_000,
    reuseExistingServer: !process.env.CI,
  },
});
