import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const frontendRoot = fileURLToPath(new URL(".", import.meta.url));
const repositoryRoot = fileURLToPath(new URL("../..", import.meta.url));
const designSystemEntry = fileURLToPath(new URL("./ds.entry.ts", import.meta.url));

// Test-only Vite surface for the tracked design-sync previews. The generated `.ds-sync` tool and
// `ds-bundle` output are intentionally ignored, so a clean checkout must render the durable sources
// directly. This config never changes the production build or exposes the harness through the app.
export default defineConfig({
  root: frontendRoot,
  plugins: [react()],
  resolve: {
    alias: [{ find: "assesshub-frontend", replacement: designSystemEntry }],
    // Preview/provider files live outside the frontend package. Keep one React/router instance even
    // though normal package resolution would start from `.design-sync/`.
    dedupe: ["react", "react-dom", "react-router"],
  },
  server: {
    host: "127.0.0.1",
    fs: { strict: true, allow: [repositoryRoot] },
  },
  clearScreen: false,
});
