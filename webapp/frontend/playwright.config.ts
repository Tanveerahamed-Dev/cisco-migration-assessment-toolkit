import { defineConfig, devices } from "@playwright/test";

// E2E tier — the honest complement to the Vitest/jsdom unit+integration tests. This runs the REAL
// production build in a REAL Chromium (WebGL available), so it can verify what jsdom fundamentally
// cannot: the SPA actually boots, and the three.js / react-force-graph-3d fabric actually renders a
// WebGL canvas. The API is mocked per-test via page.route — no backend needed.

// Serve on an uncommon fixed port, NOT vite's default 4173: the CI fleet is the dev box, which may
// already have a `vite preview` (4173) / `vite dev` (5173) of its own bound — a fixed default collides
// ("port already used", the webServer never starts). 41973 dodges both; E2E_PORT overrides it (a CI run
// can inject a per-run port to also stay clear of a concurrent second runner). Kept out of the OS
// ephemeral range (49152+) so it is never auto-assigned to something else.
const PORT = process.env.E2E_PORT || "41973";
const ORIGIN = `http://localhost:${PORT}`;

export default defineConfig({
  testDir: "./e2e",
  testMatch: "**/*.spec.ts",
  fullyParallel: true,
  forbidOnly: !!process.env.CI, // a stray test.only fails CI, never silently narrows the run
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? "line" : "list",
  use: {
    baseURL: ORIGIN,
    trace: "on-first-retry",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  // Serve the actual production build (tsc + vite build), then vite preview — the same bytes users get.
  webServer: {
    command: `npm run build && npm run preview -- --port ${PORT} --strictPort`,
    url: ORIGIN,
    timeout: 180_000,
    reuseExistingServer: !process.env.CI,
  },
});
