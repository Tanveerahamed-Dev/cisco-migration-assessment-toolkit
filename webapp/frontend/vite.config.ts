/// <reference types="vitest/config" />
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// Dev: proxy the API to the FastAPI backend on :8000 so the SPA and API share one origin.
// Build: emits to dist/, which the backend mounts as static in production.
export default defineConfig({
  plugins: [react()],
  // NOTE: do NOT `resolve.dedupe: ["three"]` here. react-force-graph-3d's sub-deps
  // (three-render-objects) import three APIs (e.g. `Timer`) pinned to their own bundled three
  // version; forcing a single top-level three breaks the build. The benign "Multiple instances of
  // Three.js" console warning is expected and harmless — only the library's three is used at runtime. (V3.23.181)
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://127.0.0.1:8000", changeOrigin: true },
    },
  },
  build: { outDir: "dist", sourcemap: false },
  // Vitest: jsdom for the DOM-touching tests; globals so specs read like the rest of the ecosystem;
  // setup registers @testing-library/jest-dom matchers. Tests target the jsdom-SAFE surface + the pure
  // logic of the 3D fabric (the d3-force `layout` and the three.js geometry builder `switchMesh` need
  // no WebGL); the actual WebGL RENDER (react-force-graph-3d) is honestly out of jsdom scope — that is
  // browser-E2E (Playwright) territory, deliberately not faked with a hollow canvas mock.
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    css: false,
    coverage: {
      provider: "v8",
      reporter: ["text-summary", "text"],
      include: ["src/**/*.{ts,tsx}"],
      exclude: ["src/**/*.test.{ts,tsx}", "src/test/**", "src/main.tsx"],
    },
  },
});
