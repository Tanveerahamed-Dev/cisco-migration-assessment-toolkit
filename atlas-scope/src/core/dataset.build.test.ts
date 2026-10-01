// @vitest-environment node
/**
 * dataset.build.test.ts — the two builds this package ships, checked on the output THIS checkout
 * produces now (built in a child process with the project's own vite.config.ts, `write: false`).
 *
 *   standalone (`npm run build`, dist/): the bundled sample, no runtime-source declaration.
 *   AssessHub  (`npm run build:hub`, dist-hub/): served by AssessHub at /scope/ OUTSIDE its API guard, so
 *     it must carry NO compiled dataset in any file — the snapshot arrives at run time from the guarded
 *     /api — and it must declare that (the <meta> AssessHub's scope validator requires, and requires
 *     exactly once). No sourcemaps: their sourcesContent would carry every source file verbatim.
 *
 * And for both, acceptance F4's chunk graph: the entry chunk imports no application code statically
 * (the application is `import()`ed after the boot line paints) and no three.js module is in the entry
 * or anything it or index.html loads up front.
 */
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { beforeAll, describe, expect, it } from "vitest";
import { OUTPUTS } from "../../tools/lib/compile-model.mjs";
import { PKG } from "../test-support/dataset/testing";

interface Chunk {
  fileName: string;
  isEntry: boolean;
  isDynamicEntry: boolean;
  imports: string[];
  dynamicImports: string[];
  moduleIds: string[];
  code: string;
}
interface Built {
  base: string;
  outDir: string;
  html: string;
  chunks: Chunk[];
  assets: { fileName: string; source: string }[];
}

function buildBoth(): Record<"standalone" | "hub", Built> {
  const script = `
    import { build, resolveConfig } from "vite";
    const out = {};
    for (const [name, mode] of [["standalone", "production"], ["hub", "hub"]]) {
      const cfg = await resolveConfig({ root: process.cwd(), configFile: "vite.config.ts", mode }, "build");
      const res = await build({ root: process.cwd(), configFile: "vite.config.ts", mode, logLevel: "silent", build: { write: false } });
      const outputs = (Array.isArray(res) ? res : [res]).flatMap((r) => r.output);
      const html = outputs.find((o) => o.type === "asset" && o.fileName === "index.html");
      out[name] = {
        base: cfg.base,
        outDir: cfg.build.outDir,
        html: String(html ? html.source : ""),
        chunks: outputs.filter((o) => o.type === "chunk").map((c) => ({
          fileName: c.fileName, isEntry: c.isEntry, isDynamicEntry: c.isDynamicEntry, imports: c.imports,
          dynamicImports: c.dynamicImports, moduleIds: c.moduleIds.map((m) => m.split("\\\\").join("/")), code: c.code,
        })),
        assets: outputs.filter((o) => o.type === "asset").map((a) => ({
          fileName: a.fileName,
          source: typeof a.source === "string" ? a.source : Buffer.from(a.source).toString("latin1"),
        })),
      };
    }
    process.stdout.write(JSON.stringify(out));
  `;
  const stdout = execFileSync(process.execPath, ["--input-type=module", "-e", script], {
    cwd: PKG,
    encoding: "utf8",
    maxBuffer: 256 * 1024 * 1024,
    timeout: 400_000,
    env: { ...process.env, ATLAS_DATASET_DIR: "" },
  });
  return JSON.parse(stdout) as Record<"standalone" | "hub", Built>;
}

const RUNTIME_META = /<meta\b[^>]*\bname="atlas-scope-snapshot-source"[^>]*>/gi;
/** The keys a compiled document's binding envelope always binds to a string literal (webapp/backend/app.py
    _SCOPE_COMPILED_MODEL_SIGNATURE_KEYS): a bundled compiler NAMES them, only a compiled document binds them. */
const BOUND_TO_LITERAL = (key: string): RegExp => new RegExp(`(?<![A-Za-z0-9_$])${key}(?![A-Za-z0-9_$])\\\\*["'\`]?\\s*:\\s*\\\\*["'\`]`);
/** Every digest the tracked compiled documents carry: if one is in a build, that build carries the sample. */
const TRACKED_DIGESTS = [
  ...new Set(
    OUTPUTS.flatMap((o) => {
      const meta = (JSON.parse(readFileSync(resolve(PKG, o.trackedPath), "utf8")) as { meta: Record<string, unknown> }).meta;
      return [meta.sourceSha256, meta.sourceGitBlob, String(meta.sourceExactSha256).replace(/^sha256:/, "")].map(String);
    }),
  ),
];

let built: Record<"standalone" | "hub", Built>;
beforeAll(() => {
  built = buildBoth();
}, 420_000);

const texts = (b: Built): { fileName: string; text: string }[] => [
  ...b.chunks.map((c) => ({ fileName: c.fileName, text: c.code })),
  ...b.assets.map((a) => ({ fileName: a.fileName, text: a.source })),
];

describe("the AssessHub build (`vite build --mode hub`)", () => {
  it("is built for the /scope/ mount into dist-hub/, and index.html loads only /scope/assets/", () => {
    const hub = built.hub;
    expect(hub.base).toBe("/scope/");
    expect(hub.outDir.split("\\").join("/")).toMatch(/(^|\/)dist-hub$/);
    const refs = [...hub.html.matchAll(/\b(?:src|href)="([^"]+)"/g)].map((m) => m[1]!).filter((r) => !r.startsWith("data:"));
    expect(refs.length).toBeGreaterThan(0);
    for (const r of refs) expect(r, "every reference is under the /scope/ mount's assets").toMatch(/^\/scope\/assets\/[^/]+$/);
  });

  it("declares the runtime snapshot source exactly once (AssessHub serves /scope only from such a build)", () => {
    const metas = [...built.hub.html.matchAll(RUNTIME_META)].map((m) => m[0]);
    expect(metas).toHaveLength(1);
    expect(metas[0]).toMatch(/\bcontent="assesshub-api-runtime"/);
  });

  it("emits no sourcemap and references none", () => {
    expect(built.hub.assets.filter((a) => a.fileName.endsWith(".map")).map((a) => a.fileName)).toEqual([]);
    for (const t of texts(built.hub)) expect(t.text, t.fileName).not.toMatch(/sourceMappingURL/);
  });

  it("carries NO compiled dataset: no compiled document is a module of it, and no file binds the signature keys or carries a tracked digest", () => {
    const docs = OUTPUTS.map((o) => resolve(PKG, o.trackedPath).split("\\").join("/").toLowerCase());
    const bundledDocs = built.hub.chunks.flatMap((c) => c.moduleIds.filter((m) => docs.includes(m.toLowerCase())));
    expect(bundledDocs).toEqual([]);
    /* Positive control: the same scan DOES find the sample in the standalone build. */
    const standaloneDocs = built.standalone.chunks.flatMap((c) => c.moduleIds.filter((m) => docs.includes(m.toLowerCase())));
    expect(standaloneDocs.length).toBe(OUTPUTS.length);
    const offenders = (b: Built): string[] =>
      texts(b).flatMap((t) => [
        ...(BOUND_TO_LITERAL("sourceGitBlob").test(t.text) ? [`${t.fileName}: sourceGitBlob bound to a literal`] : []),
        ...TRACKED_DIGESTS.filter((d) => t.text.includes(d)).map((d) => `${t.fileName}: ${d.slice(0, 12)}…`),
      ]);
    expect(offenders(built.standalone).length, "positive control: the standalone build carries the sample's digests").toBeGreaterThan(0);
    expect(offenders(built.hub)).toEqual([]);
  });

  it("carries no 64-hex token at all (AssessHub compares each one against every stored snapshot's digest at boot)", () => {
    const tokens = texts(built.hub).flatMap((t) => [...t.text.matchAll(/(?<![0-9a-fA-F])[0-9a-fA-F]{64}(?![0-9a-fA-F])/g)].map((m) => `${t.fileName}: ${m[0].slice(0, 12)}…`));
    expect(tokens).toEqual([]);
  });

  it("carries the one compiler, in a worker that nothing loads up front", () => {
    const compilerIn = built.hub.chunks.filter((c) => c.moduleIds.some((m) => m.endsWith("tools/lib/compile-model.mjs")));
    const workerAssets = built.hub.assets.filter((a) => /compile\.worker/.test(a.fileName));
    /* Vite emits a module worker either as its own chunk or as an asset; the compiler is in it either way. */
    expect(compilerIn.length + workerAssets.length, "the compile worker is in the build").toBeGreaterThan(0);
    const entry = built.hub.chunks.filter((c) => c.isEntry);
    for (const e of entry) expect(e.moduleIds.some((m) => m.endsWith("tools/lib/compile-model.mjs")), `${e.fileName} carries the compiler`).toBe(false);
    /* CONTENT, not a file name (phase 3.5, P3E-V2): an asset merely NAMED compile.worker* satisfied the
       count above. The worker must carry the compiler itself — every refusal code the compiler's source
       throws (read from tools/lib/compile-model.mjs, never typed here) — and the entry must carry none. */
    const compilerSource = readFileSync(resolve(PKG, "tools/lib/compile-model.mjs"), "utf8");
    const codes = [...new Set([...compilerSource.matchAll(/CompileError\(\s*"(E_[A-Z0-9_]+)"/g)].map((m) => m[1]!))].sort();
    expect(codes.length, "the compiler's own refusal codes were read").toBeGreaterThan(5);
    const workerTexts = [...workerAssets.map((a) => a.source), ...compilerIn.map((c) => c.code)];
    const missing = codes.filter((code) => !workerTexts.some((t) => t.includes(`"${code}"`) || t.includes(`'${code}'`) || t.includes(`\`${code}\``)));
    expect(missing, "refusal codes of the compiler absent from the compile worker").toEqual([]);
    for (const e of entry) expect(codes.filter((code) => e.code.includes(code)), `${e.fileName} carries compiler code`).toEqual([]);
  });
});

describe("the standalone build (`npm run build`)", () => {
  it("is the plain build (base /, dist/) and declares no runtime source — it shows the bundled sample", () => {
    expect(built.standalone.base).toBe("/");
    expect(built.standalone.outDir.split("\\").join("/")).toMatch(/(^|\/)dist$/);
    expect([...built.standalone.html.matchAll(RUNTIME_META)]).toHaveLength(0);
  });
});

describe("F4 chunk graph, both builds: the entry imports no application code and no three.js up front", () => {
  for (const name of ["standalone", "hub"] as const) {
    it(`${name}`, () => {
      const b = built[name];
      const byFile = new Map(b.chunks.map((c) => [c.fileName, c]));
      const entries = b.chunks.filter((c) => c.isEntry);
      expect(entries.length).toBe(1);
      const initial = new Set<string>();
      const walk = (f: string): void => {
        if (initial.has(f)) return;
        initial.add(f);
        for (const i of byFile.get(f)?.imports ?? []) walk(i);
      };
      for (const e of entries) walk(e.fileName);
      const preloads = [...b.html.matchAll(/<link\b[^>]*rel="modulepreload"[^>]*href="([^"]+)"/g)].map((m) => m[1]!.replace(/^\/(scope\/)?/, ""));
      for (const p of preloads) walk(p);
      const upFront = [...initial].flatMap((f) => byFile.get(f)?.moduleIds ?? []);
      expect(upFront.filter((m) => /\/src\/app\/App\.tsx$|\/src\/mount\.tsx$/.test(m)), "the application is not in the initial payload").toEqual([]);
      expect(upFront.filter((m) => /\/node_modules\/(three|postprocessing)\//.test(m)), "no three.js in the initial payload").toEqual([]);
      /* The class, not a list of the modules that must stay out: every authored module in the initial
         payload must be one the boot entry is meant to carry (itself, its two stylesheets, the theme
         preference, and the two tiny dataset helpers it calls synchronously). Anything else — the
         runtime-dataset code (boot, hub, opened, the compile client), the compiler, the application —
         is loaded on demand, and a new module that slips into the entry fails here by default. */
      const ENTRY_MAY_CARRY = /\/src\/(main\.tsx|app\/theme-preference\.ts|core\/tokens\.css|app\/shell\.css|core\/dataset\/(marker|refusal)\.ts)$/;
      expect(
        upFront.map((m) => m.replace(/[?#].*$/, "")).filter((m) => /\/src\//.test(m) && !ENTRY_MAY_CARRY.test(m)),
        "only the boot entry's own modules are in the initial payload",
      ).toEqual([]);
      expect(upFront.some((m) => /\/src\/main\.tsx$/.test(m)), "positive control: the entry itself is in the initial payload").toBe(true);
      /* Positive controls: the application and three.js ARE in the build, behind import(). */
      const all = b.chunks.flatMap((c) => c.moduleIds);
      expect(all.some((m) => /\/src\/app\/App\.tsx$/.test(m))).toBe(true);
      expect(all.some((m) => /\/node_modules\/three\//.test(m))).toBe(true);
    });
  }
});
