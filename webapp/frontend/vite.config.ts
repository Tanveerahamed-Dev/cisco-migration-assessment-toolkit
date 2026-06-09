import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev: proxy the API to the FastAPI backend on :8000 so the SPA and API share one origin.
// Build: emits to dist/, which the backend mounts as static in production.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://127.0.0.1:8000", changeOrigin: true },
    },
  },
  build: { outDir: "dist", sourcemap: false },
});
