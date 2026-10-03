import { createHash } from "node:crypto";
import { existsSync, readFileSync } from "node:fs";
import { dirname, isAbsolute, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { gunzipSync } from "node:zlib";
import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";
/* The compiler's own list of the documents it writes: the dataset door below is derived from it, never
   from a hand-kept list of file names. */
import { OUTPUTS, SECTIONS_READ, SUPPORTED_SCHEMAS } from "./tools/lib/compile-model.mjs";
import { EMBED_PROTOCOL } from "../webapp/frontend/src/projectionEmbed";

const ROOT = dirname(fileURLToPath(import.meta.url));

/* ── Two builds, one source ─────────────────────────────────────────────────────────────────────
 *
 *   `npm run build`      standalone (mode "production"): dist/, base "/", the bundled sample.
 *   `npm run build:hub`  AssessHub (mode "hub"): dist-hub/, base "/scope/", no sourcemaps, and NO
 *                        compiled dataset in any file. AssessHub serves /scope outside its API guard,
 *                        so the snapshot must arrive at run time from the guarded /api; index.html
 *                        declares that with the one <meta> AssessHub's scope validator requires
 *                        (webapp/backend/app.py `_scope_shell_valid`).
 *
 * The mode-dependent settings are applied by the `atlasDataset` plugin's `config` hook, so this file's
 * default export stays a plain object (src/core/dev-watch.test.ts reads it). */
export const HUB_MODE = "hub";
export const HUB_BASE = "/scope/";
export const HUB_OUT_DIR = "dist-hub";
export const RUNTIME_SOURCE_META = { name: "atlas-scope-snapshot-source", content: "assesshub-api-runtime" } as const;
export const ENGINE_PROJECTION_META = { name: "atlas-scope-engine-projection", content: EMBED_PROTOCOL } as const;

const posix = (p: string): string => p.split("\\").join("/");
/* Module ids are compared case-insensitively on Windows (a drive letter's case varies between resolvers). */
const sameFile = (a: string, b: string): boolean =>
  process.platform === "win32" ? posix(a).toLowerCase() === posix(b).toLowerCase() : posix(a) === posix(b);
const stripQuery = (id: string): string => id.replace(/[?#].*$/, "");

/** Every compiled document the compiler writes, where the standalone build reads it from. */
const COMPILED_DOCUMENTS = OUTPUTS.map((o) => ({ key: o.key, file: o.file, path: resolve(ROOT, o.trackedPath) }));
const DATASET_MODULE = resolve(ROOT, "src/core/dataset.ts");
const BUNDLED_MODULE = resolve(ROOT, "src/core/dataset/bundled.ts");
const BUNDLED_NONE_MODULE = resolve(ROOT, "src/core/dataset/bundled.none.ts");
const VIRTUAL_PREFIX = "\0atlas-dataset:";
const documentAt = (id: string): (typeof COMPILED_DOCUMENTS)[number] | undefined =>
  COMPILED_DOCUMENTS.find((d) => sameFile(d.path, stripQuery(id)));

/**
 * The one compiler's identity: what an opened snapshot's kept compile is stamped with. The first 128
 * bits of a sha256 over its sources, prefixed — deliberately NOT a 64-hex token: AssessHub's scope
 * privacy scan treats every 64-hex token in a build as a possible snapshot digest and hashes every
 * stored snapshot to compare (webapp/backend/app.py `_scope_file_index`).
 */
function compilerId(): string {
  const h = createHash("sha256");
  for (const f of ["tools/lib/compile-model.mjs", "tools/lib/validate-snapshot.mjs", "contracts/engine-contract.v1.json"]) {
    h.update(readFileSync(resolve(ROOT, f)).toString("utf8").replace(/\r\n/g, "\n"));
  }
  return `compiler-${h.digest("hex").slice(0, 32)}`;
}

/**
 * A compiled document's binding envelope binds these keys to string literals; the compiler's code only
 * NAMES them (webapp/backend/app.py `_SCOPE_COMPILED_MODEL_SIGNATURE_KEYS`, pinned there to the
 * compiler's BINDING_KEYS). `sourceGitBlob` bound to a literal is the half no code ever writes.
 */
const bindsLiteral = (key: string): RegExp => new RegExp(`(?<![A-Za-z0-9_$])${key}(?![A-Za-z0-9_$])\\\\*["'\`]?\\s*:\\s*\\\\*["'\`]`);

/** The tracked sample's digests: no hub file may carry one. */
function trackedDigests(): Set<string> {
  const digests = new Set<string>();
  for (const d of COMPILED_DOCUMENTS) {
    const meta = (JSON.parse(readFileSync(d.path, "utf8")) as { meta?: Record<string, unknown> }).meta ?? {};
    for (const k of ["sourceSha256", "sourceGitBlob", "sourceExactSha256"]) {
      const v = meta[k];
      if (typeof v === "string" && v !== "") digests.add(v.replace(/^sha256:/, ""));
    }
  }
  return digests;
}

/* ── AssessHub's compiled-model signatures, ported (phase 3.5, P3E-V6) ─────────────────────────────
 * webapp/backend/app.py `_scope_file_carries_compiled_model` refuses a /scope file that carries: the binding
 * envelope, a compiled RECORD recognised by a snapshot citation bound as data (a bundler drops the envelope:
 * Vite's JSON plugin turns a document's members into named exports), or an engine snapshot itself — in
 * plain text, inside a base64 data: URI, or inside a compressed stream. This build-time scan used to know the
 * envelope and the tracked digests only, so the other forms passed the build and were stopped only when
 * AssessHub indexed the output. The same shapes are recognised here, rooted in the compiler's own exports
 * (SECTIONS_READ for a dotted citation's root, SUPPORTED_SCHEMAS for the snapshot schema family), never a
 * list typed here. A stream the scan cannot open (bzip2, xz: Node has no codec for them) is refused. */
/* Whitespace between JSON tokens, literal or escaped (\n \r \t, once or more deeply escaped). */
const JS_WS = "(?:\\s|\\\\+[nrt])*";
/* One string delimiter in any quoting a build ships ("…", an escaped \"…\", `…`, '…'). */
const JS_QUOTE = "\\\\*[\"'`]";
/* A literal's body with no template substitution. */
const JS_LITERAL_BODY = "(?:[^\"'`\\\\\\r\\n$]|\\$(?!\\{))+";
const escapeRe = (s: string): string => s.replace(/[.*+?^${}()|[\]\\/]/g, "\\$&");
const SNAPSHOT_CITATION =
  JS_QUOTE + String.raw`(?:(?:` + SECTIONS_READ.map(escapeRe).join("|") + String.raw`)[.\[]|/[a-z][a-z0-9_]*/)` + JS_LITERAL_BODY + JS_QUOTE;
const RECORD_CITATION_SIGNATURES: readonly RegExp[] = [
  /* a citation bound to a `cite`-named key (`cite`, `centralityCite`, …) */
  new RegExp(String.raw`(?<![A-Za-z0-9_$])(?:[A-Za-z_$][A-Za-z0-9_$]*)?[Cc]ite` + JS_QUOTE + "?" + JS_WS + ":" + JS_WS + SNAPSHOT_CITATION),
  /* a citation used as an object key (a citation-keyed map) */
  new RegExp(String.raw`[{,]` + JS_WS + SNAPSHOT_CITATION + JS_WS + ":"),
];
const SCHEMA_FAMILIES = [...new Set(SUPPORTED_SCHEMAS.map((s) => s.replace(/[0-9]+$/, "")))];
const RAW_SNAPSHOT_SIGNATURE = new RegExp(
  String.raw`(?<![A-Za-z0-9_$])schema` + JS_QUOTE + "?" + JS_WS + ":" + JS_WS + JS_QUOTE + `(?:${SCHEMA_FAMILIES.map(escapeRe).join("|")})[0-9]+` + JS_QUOTE,
);
const BASE64_DATA_URI = /data:[A-Za-z0-9.+/-]*(?:;[A-Za-z0-9.+/=-]*)*;base64,([A-Za-z0-9+/_-]{16,}={0,2})/g;
const GZIP_MAGIC = Buffer.from([0x1f, 0x8b, 0x08]);
const BZIP2_MAGIC = /BZh[1-9]1AY&SY/;
const XZ_MAGIC = Buffer.from([0xfd, 0x37, 0x7a, 0x58, 0x5a, 0x00]);
const DATA_URI_DEPTH = 3;

/** What in these bytes is snapshot evidence, including inside data: URIs and gzip streams (depth-bounded). */
function evidenceIn(bytes: Buffer, depth: number): string[] {
  const text = bytes.toString("latin1");
  const found: string[] = [];
  if (bindsLiteral("sourceGitBlob").test(text)) found.push("binds sourceGitBlob to a literal (a compiled document's envelope)");
  if (RECORD_CITATION_SIGNATURES.some((re) => re.test(text))) found.push("carries a compiled record (a snapshot citation bound as data)");
  if (RAW_SNAPSHOT_SIGNATURE.test(text)) found.push("carries an engine snapshot (its schema bound to the engine's snapshot schema family)");
  if (BZIP2_MAGIC.test(text) || bytes.includes(XZ_MAGIC)) found.push("carries a compressed stream (bzip2/xz) this scan cannot open");
  if (depth >= DATA_URI_DEPTH) return found;
  for (let at = bytes.indexOf(GZIP_MAGIC); at !== -1; at = bytes.indexOf(GZIP_MAGIC, at + 1)) {
    let inner: Buffer | null = null;
    try {
      inner = gunzipSync(bytes.subarray(at));
    } catch {
      inner = null;
    }
    if (inner !== null) found.push(...evidenceIn(inner, depth + 1).map((f) => `inside a gzip stream: ${f}`));
  }
  for (const m of text.matchAll(BASE64_DATA_URI)) {
    const inner = Buffer.from(m[1]!.replace(/-/g, "+").replace(/_/g, "/"), "base64");
    found.push(...evidenceIn(inner, depth + 1).map((f) => `inside a data: URI: ${f}`));
  }
  return found;
}

/**
 * The hub build's pre-write privacy scan, over every output file (exported so it is tested on planted
 * text as well as on the real build: src/core/dataset.hub-guard.test.ts).
 */
export function hubBundleProblems(
  files: readonly { name: string; bytes: Uint8Array; moduleIds: readonly string[] }[],
  digests: ReadonlySet<string>,
): string[] {
  const problems: string[] = [];
  for (const { name, bytes, moduleIds } of files) {
    if (name.endsWith(".map")) problems.push(`${name}: a sourcemap (its sourcesContent carries every source verbatim)`);
    const buf = Buffer.from(bytes);
    const text = buf.toString("latin1");
    for (const m of moduleIds) if (documentAt(m) !== undefined) problems.push(`${name}: bundles ${posix(relative(ROOT, stripQuery(m)))}`);
    for (const f of new Set(evidenceIn(buf, 0))) problems.push(`${name}: ${f}`);
    for (const d of digests) if (text.includes(d)) problems.push(`${name}: carries the tracked sample's digest ${d.slice(0, 12)}…`);
  }
  return problems;
}

/**
 * THE DATASET DOOR, at build level.
 *
 *  - Every mode except the test runner: an import of a compiled document from any module other than
 *    src/core/dataset/bundled.ts is served by core/dataset.ts (the installed dataset), never by the file.
 *    A module that kept its own static import would otherwise render the SAMPLE's evidence beside an
 *    installed fabric. (The test runner resolves the files themselves: tests mock them by path.) Each
 *    such importer is reported as a warning — it should import from core/dataset.ts by name.
 *  - Hub mode: dataset/bundled.ts resolves to dataset/bundled.none.ts, so no compiled document is in the
 *    output at all, and the bundle is scanned before it is written: a compiled document's signature or
 *    any tracked document's digest in any file fails the build.
 */
function atlasDataset(): Plugin {
  let mode = "production";
  let testRunner = false;
  const redirected = new Set<string>();
  return {
    name: "atlas-scope:dataset",
    enforce: "pre",
    config(cfg, env) {
      const hub = env.mode === HUB_MODE;
      return {
        define: { __ATLAS_COMPILER_ID__: JSON.stringify(compilerId()) },
        /* An explicit --outDir is honoured (a scratch build); the base and the sourcemap rule are not negotiable. */
        ...(hub ? { base: HUB_BASE, build: { outDir: cfg.build?.outDir ?? HUB_OUT_DIR, emptyOutDir: true, sourcemap: false } } : {}),
      };
    },
    configResolved(cfg) {
      mode = cfg.mode;
      /* By MODE, not by the VITEST variable: a build a test spawns inherits that variable and is a real build. */
      testRunner = cfg.mode === "test";
    },
    async resolveId(source, importer, options) {
      if (testRunner || importer === undefined) return null;
      if (!/\.json(?:[?#].*)?$/.test(source) && !/(^|\/)bundled(\.ts)?$/.test(source)) return null;
      const r = await this.resolve(source, importer, { ...options, skipSelf: true });
      if (r === null || r.external) return null;
      if (mode === HUB_MODE && sameFile(stripQuery(r.id), BUNDLED_MODULE)) return BUNDLED_NONE_MODULE;
      const doc = documentAt(r.id);
      if (doc === undefined || stripQuery(r.id) !== r.id) return null;
      if (mode !== HUB_MODE && sameFile(stripQuery(importer), BUNDLED_MODULE)) return null;
      redirected.add(posix(importer).replace(posix(ROOT) + "/", ""));
      return `${VIRTUAL_PREFIX}${doc.key}`;
    },
    load(id) {
      if (!id.startsWith(VIRTUAL_PREFIX)) return null;
      const key = id.slice(VIRTUAL_PREFIX.length);
      return `import { ${key} } from ${JSON.stringify(posix(DATASET_MODULE))};\nexport default ${key};\n`;
    },
    buildEnd() {
      for (const f of [...redirected].sort()) {
        this.warn(`${f} imports a compiled document directly; it is served from src/core/dataset.ts. Import it from there by name.`);
      }
    },
    transformIndexHtml() {
      if (mode !== HUB_MODE) return undefined;
      return [RUNTIME_SOURCE_META, ENGINE_PROJECTION_META].map((marker) => ({
        tag: "meta", attrs: { name: marker.name, content: marker.content }, injectTo: "head" as const,
      }));
    },
    generateBundle(_opts, bundle) {
      if (mode !== HUB_MODE) return;
      const problems = hubBundleProblems(
        Object.entries(bundle).map(([name, out]) => ({
          name,
          bytes: out.type === "chunk" ? Buffer.from(out.code, "utf8") : typeof out.source === "string" ? Buffer.from(out.source, "utf8") : Buffer.from(out.source),
          moduleIds: out.type === "chunk" ? out.moduleIds : [],
        })),
        trackedDigests(),
      );
      if (problems.length > 0) {
        this.error(`the AssessHub build must carry no compiled dataset, and this one does:\n  ${problems.join("\n  ")}`);
      }
    },
  };
}

/**
 * The test runner's dataset override (vitest.config.ts): with ATLAS_DATASET_DIR set to a directory the
 * compiler wrote (`node tools/compile-all.mjs --source <snapshot> --out <dir>`), every import of a
 * compiled document resolves to that directory's file instead of the tracked one — so the whole suite
 * runs against another dataset (the rename leg, the golden-snapshot leg). The directory must hold all
 * four documents bound to ONE source; anything else is a configuration error, never a silent fallback
 * to the sample.
 */
export function datasetDirOverride(dir: string | undefined): Plugin[] {
  if (dir === undefined || dir.trim() === "") return [];
  const abs = isAbsolute(dir) ? dir : resolve(ROOT, dir);
  const metas = COMPILED_DOCUMENTS.map((d) => {
    const file = join(abs, d.file);
    if (!existsSync(file)) {
      throw new Error(
        `ATLAS_DATASET_DIR=${dir} has no ${d.file}. Compile a snapshot into it first: node tools/compile-all.mjs --source <snapshot.json> --out ${dir}`,
      );
    }
    return { doc: d, file, meta: (JSON.parse(readFileSync(file, "utf8")) as { meta?: Record<string, unknown> }).meta ?? {} };
  });
  const bindingKeys = ["source", "sourceOrigin", "sourceDigestForm", "sourceSha256", "sourceBytes", "sourceExactSha256", "sourceGitBlob"];
  for (const m of metas) {
    for (const k of bindingKeys) {
      if (m.meta[k] === undefined || m.meta[k] !== metas[0]!.meta[k]) {
        throw new Error(`ATLAS_DATASET_DIR=${dir}: ${m.doc.file} is bound to other bytes than ${metas[0]!.doc.file} (${k} differs). Recompile the directory as one set.`);
      }
    }
  }
  return [
    {
      name: "atlas-scope:dataset-dir",
      enforce: "pre",
      async resolveId(source, importer, options) {
        if (!/\.json$/.test(source) || importer === undefined) return null;
        const r = await this.resolve(source, importer, { ...options, skipSelf: true });
        if (r === null) return null;
        const hit = metas.find((m) => sameFile(m.doc.path, r.id));
        return hit === undefined ? null : hit.file;
      },
    },
  ];
}

export default defineConfig({
  plugins: [atlasDataset(), react()],
  worker: {
    /* The compile worker (src/core/dataset/compile.worker.ts) is a module worker: it imports the one
       compiler and the engine contract it validates against. */
    format: "es",
  },
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
