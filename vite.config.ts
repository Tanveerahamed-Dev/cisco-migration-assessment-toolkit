import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: { port: 4180, strictPort: true },
  preview: { port: 4181, strictPort: true },
  build: {
    target: "es2022",
    sourcemap: true,
    rollupOptions: {
      output: {
        /**
         * Vite 8 bundles with Rolldown, which accepts `manualChunks` only as a FUNCTION — the
         * object form silently produces "manualChunks is not a function" at build time. (The
         * object form is a Rollup-ism and is what the first version of this config used.)
         *
         * The split exists for acceptance F4: three.js plus the post-processing chain is the
         * single largest dependency in the app and nothing on the findings, path or evidence
         * surfaces needs it. Keeping it out of the entry chunk means a user who never opens the
         * fabric never downloads a renderer.
         */
        manualChunks(id: string): string | undefined {
          if (!id.includes("node_modules")) return undefined;
          if (/[\\/]node_modules[\\/](three|postprocessing)[\\/]/.test(id)) return "three";
          if (/[\\/]node_modules[\\/](react|react-dom|scheduler)[\\/]/.test(id)) return "react";
          return undefined;
        },
      },
    },
  },
  /* No `test` block here, and no `as any`. This file used to carry a copy of the runner's
     settings and cast the whole config to `any` to get it past the Vite types. The copy was dead:
     Vitest loads vitest.config.ts INSTEAD of this file (which merges this one), and the cast hid
     every other type error in the build config too. vitest.config.ts owns the runner; both files
     are type-checked by tsconfig.config.json. */
});
