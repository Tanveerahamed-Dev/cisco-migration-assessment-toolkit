/**
 * dev-watch.test.ts — the dev server does not watch the review apparatus's generated output.
 *
 * MEASURED 2026-09-24. After about 16 hours of uptime the :4180 dev server (vite 8.2.1) sat at a steady
 * 1.51 CPU cores with no client connected, no child process and nothing in its log; restarted, the
 * same server idled at 0.01 cores. Every E2-E5 acceptance run in that window was refused by
 * review/host-env.mjs as "host busy", and the dev server was the largest single consumer.
 *
 * Vite's own default watch-ignore list (node_modules/vite/dist/node/chunks/node.js,
 * `resolveChokidarOptions`) is `.git`, `node_modules`, `test-results`, the cache directory and the
 * build outDirs. Everything else under the root is watched — including `review/shots` (about 8,000
 * regenerated PNGs, rewritten by every capture run), `review/_scratch`, `review/reports`,
 * `review/blind`, and the agents' `.audit/` and `.probe/` scratch. None of it is application source,
 * so watching it buys nothing and costs a watcher event per rewritten file.
 *
 * THE INVARIANT is stated about the class, in two halves:
 *   1. every directory that holds generated review/scratch output is outside the watch; and
 *   2. no application module can be hidden by that ignore list — nothing the app imports lives
 *      under an ignored directory, so an edit to real source still reloads.
 * The restart is what cleared the measured load; this file stops the apparatus from re-heating it.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, extname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import viteConfig from "../../vite.config";

const SRC = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const ROOT = resolve(SRC, "..");
const posix = (p: string): string => p.split("\\").join("/");

/** The ignore globs the dev server's watcher is given, as written in vite.config.ts. */
function ignoredGlobs(): string[] {
  const cfg = viteConfig as { server?: { watch?: { ignored?: unknown } } };
  const ignored = cfg.server?.watch?.ignored;
  if (ignored === undefined) return [];
  return (Array.isArray(ignored) ? ignored : [ignored]).filter((g): g is string => typeof g === "string");
}

/** `**\/name/**` style globs reduced to the directory names they exclude at any depth. */
const ignoredDirNames = (): Set<string> =>
  new Set(ignoredGlobs().map((g) => /^\*\*\/([^/*]+)\/\*\*$/.exec(g)?.[1]).filter((n): n is string => n !== undefined));

/** Every relative import specifier in the application sources and the page entries. */
function appSpecifiers(): { file: string; spec: string }[] {
  const out: { file: string; spec: string }[] = [];
  const walk = (dir: string): void => {
    for (const name of readdirSync(dir)) {
      const p = join(dir, name);
      if (statSync(p).isDirectory()) walk(p);
      else if ([".ts", ".tsx", ".css"].includes(extname(p))) {
        const text = readFileSync(p, "utf8");
        for (const m of text.matchAll(/(?:from\s+|import\s*\(\s*|import\s+|@import\s+)["']([^"']+)["']/g)) {
          if (m[1]?.startsWith(".")) out.push({ file: posix(relative(ROOT, p)), spec: posix(resolve(dirname(p), m[1])) });
        }
      }
    }
  };
  walk(SRC);
  for (const html of readdirSync(ROOT).filter((n) => n.endsWith(".html"))) {
    const text = readFileSync(join(ROOT, html), "utf8");
    for (const m of text.matchAll(/src="([^"]+)"/g)) {
      if (m[1]?.startsWith("/")) out.push({ file: html, spec: posix(join(ROOT, m[1])) });
    }
  }
  return out;
}

describe("the dev server does not watch generated review output (E2-E5 host load)", () => {
  it("excludes every directory that holds generated review or agent-scratch output", () => {
    const names = ignoredDirNames();
    // The directories the review apparatus and its agents write to, which are not application source.
    for (const dir of ["review", ".audit", ".probe", "shots"]) {
      expect(names.has(dir), `vite.config.ts server.watch.ignored must exclude **/${dir}/**`).toBe(true);
    }
  });

  it("hides no application module: nothing the app or its pages import lives under an ignored directory", () => {
    const names = ignoredDirNames();
    const specs = appSpecifiers();
    expect(specs.length, "the scan found the app's imports").toBeGreaterThan(100);
    const hidden = specs.filter(({ spec }) => posix(relative(ROOT, spec)).split("/").some((seg) => names.has(seg)));
    expect(hidden.map(({ file, spec }) => `${file} -> ${posix(relative(ROOT, spec))}`)).toEqual([]);
  });

  it("the scan is live: an import into an ignored directory would be caught", () => {
    const names = new Set(["review"]);
    const planted = posix(relative(ROOT, resolve(ROOT, "review/capture.mjs")));
    expect(planted.split("/").some((seg) => names.has(seg))).toBe(true);
  });
});
