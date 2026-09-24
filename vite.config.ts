import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 4180,
    strictPort: true,
    /* The review apparatus writes thousands of generated files under the root (review/shots alone
       is ~8,000 PNGs, rewritten by every capture run) plus agent scratch in .audit/ and .probe/.
       Vite's default watch-ignore list covers only .git, node_modules, test-results, the cache and
       the outDirs, so all of that was watched: after ~16 h the dev server idled at 1.51 cores and
       every E2-E5 run was refused as "host busy" (0.01 cores after a restart). None of these
       directories holds application source; src/core/dev-watch.test.ts proves nothing the app or
       its pages import lives under them, so an edit to real source still reloads. */
    watch: { ignored: ["**/review/**", "**/.audit/**", "**/.probe/**", "**/shots/**"] },
  },
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
         * surfaces needs it. Keeping it out of the entry chunk and out of every modulepreload means
         * the boot line and the application paint before a renderer is fetched. What it does NOT
         * mean: at 768 px and wider the 3-D stage is the main view and mounts on every load, so
         * three.js IS fetched on every load there — after first paint; only below 768 px is it
         * never fetched. (This comment used to say "a user who never opens the fabric never
         * downloads a renderer", which was true of the narrow layout only.) The build-output half
         * is checked by src/core/acceptance-gates.test.ts.
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
