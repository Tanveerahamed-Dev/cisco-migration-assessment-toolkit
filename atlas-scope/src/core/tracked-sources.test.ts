// @vitest-environment node
/**
 * tracked-sources.test.ts — what the gates measure must be something a commit can reproduce.
 *
 * WHAT WAS WRONG (critic F5, 2026-09-22). The repository held ONE commit, and 55 files under `src/`
 * were untracked — among them two of the compiled data files (`src/forwarding/acl-bindings.json`,
 * `src/forwarding/rib-evidence.json`) and runtime modules the build imports (`src/mount.tsx`, the
 * chunk `main.tsx` loads; `forwarding/bindings.ts`; `fabric3d/stepdown.ts`; …). Every byte-compare
 * `provenance.test.ts` performs and every capture `review/capture.mjs` takes was a property of that
 * working tree, not of any commit, and a clean checkout could not have reproduced any of it.
 *
 * WHAT WAS WRONG WITH THE FIRST VERSION OF THIS GATE (independent refuter, wave 3). It re-implemented
 * the bundler's module resolution: a TypeScript walk of `import`/`export`/`import()` from
 * `index.html`'s one module script. The bundler follows more edges than that walk did —
 * `import.meta.glob` (then in `src/panels/Inspector.tsx`; removed in phase 3), CSS `@import` and `url()`, and the two preview
 * pages the dev server serves — so the gate's denominator was smaller than the build's. Measured in
 * a copy: an untracked `src/forwarding/zz-untracked-probe.json`, matched by Inspector's glob, gave
 * "Tests 3 passed (3)" while `grep` found its marker in the built `mount-*.js`. The clean result on
 * the real tree rested on a coincidence: the two globbed sidecars were ALSO imported statically.
 *
 * THE DENOMINATOR NOW COMES FROM THE BUILD ITSELF, not from a second resolver that can drift from it.
 * `buildGraph()` runs the real Vite build (in memory, `write: false`) over every HTML page the dev
 * server can serve, with a recorder plugin, and takes the union of
 *   - every module id Rolldown put in the graph (`this.getModuleIds()` — code, JSON, CSS, HTML,
 *     including everything any `import.meta.glob` expanded to, eager or lazy, string or array), and
 *   - every file the build's JavaScript plugins READ from disk while it ran (CSS `@import` targets,
 *     inlined `url()` assets — the edges Rolldown never sees as modules), recorded by wrapping
 *     `node:fs`'s read functions for the duration of the build.
 * The HTML pages are the ones Git does not ignore (`git ls-files --cached --others
 * --exclude-standard '*.html'`), so a new preview page is built here without anyone listing it. The
 * compilers' side is the program TypeScript builds from `tsconfig.scripts.json` — every
 * `tools/**\/*.mjs` and everything they import, resolved by the compiler, not by this file.
 *
 * "Tracked" means present in the tree of `HEAD`: a file the working tree has but no commit holds is
 * exactly what the finding names. A file staged but not committed is still red.
 *
 * THE KNOWN-ANSWER PROOF (below) builds a planted project in a temporary directory that mirrors
 * this repository's own tracked paths and adds untracked files reachable ONLY through a lazy array
 * glob, an eager glob and a CSS `@import`; the same gate function must name exactly those files.
 *
 * WHAT THIS DOES NOT CHECK. That the committed copy EQUALS the working copy. A modified tracked file
 * is ordinary development and would make this gate red on every edit; an UNTRACKED one is a file
 * no commit has ever held, which is the property the finding names. Reproducing a measurement from
 * a specific sha is still the reader's job: check out the sha and re-run.
 *
 * WHEN THIS IS RED. Nothing in the code is wrong: the fix is to commit the listed files. That is
 * the repository owner's decision, so this gate reports it rather than doing it — and it must not
 * be weakened into a skip to make a suite green, because an unverifiable reproduction claim that
 * keeps being made is exactly the false-health shape this codebase exists to refuse.
 */
import { execFileSync } from "node:child_process";
import fs, { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { syncBuiltinESMExports } from "node:module";
import { tmpdir } from "node:os";
import { dirname, isAbsolute, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";
import { build, type Plugin } from "vite";
import { afterAll, beforeAll, describe, expect, it } from "vitest";

const HERE = dirname(fileURLToPath(import.meta.url));
const PKG = resolve(HERE, "..", ".."); // atlas-scope/

function git(args: string[]): string {
  try {
    return execFileSync("git", args, { cwd: PKG, encoding: "utf8", maxBuffer: 64 * 1024 * 1024 });
  } catch (e) {
    throw new Error(`git could not be asked which files are tracked, so reproducibility is unverifiable: ${String(e)}`);
  }
}

/** Every HTML page the dev server can serve that is part of the tree (tracked or merely unignored). */
export function htmlPages(): string[] {
  return git(["ls-files", "--cached", "--others", "--exclude-standard", "-z", "--", "*.html"])
    .split("\0")
    .filter((s) => s.length > 0)
    .sort();
}

/** The paths the tree of HEAD holds. */
function committed(): Set<string> {
  return new Set(git(["ls-tree", "-r", "-z", "--name-only", "HEAD"]).split("\0").filter((s) => s.length > 0));
}

export interface BuildGraph {
  /** Every file inside `root` (outside node_modules) the build loaded or read, as root-relative POSIX paths. */
  files: string[];
  /** For each module, the root-relative files it imports after every transform (glob expansion included). */
  importsOf: Map<string, string[]>;
  /** Each module's source text BEFORE any transform, so an edge can be attributed to its syntax. */
  originalSource: Map<string, string>;
}

/**
 * Run the real Vite build over `inputs` (in memory) and return everything it loaded or read under
 * `root`. `configFile` is the project's config for the real graph, or `false` for a planted fixture.
 */
export async function buildGraph(root: string, configFile: string | false, inputs: readonly string[]): Promise<BuildGraph> {
  const toRel = (raw: string): string | null => {
    if (raw.startsWith("\0")) return null; // a virtual module: no file on disk
    const clean = raw.replace(/[?#].*$/, "");
    if (!isAbsolute(clean)) return null;
    const rel = relative(root, resolve(clean)).split("\\").join("/");
    if (rel.startsWith("../") || rel === ".." || isAbsolute(rel)) return null;
    if (rel.split("/").includes("node_modules")) return null; // a package: owned by the lockfile
    return rel;
  };

  const files = new Set<string>();
  const importsOf = new Map<string, string[]>();
  const originalSource = new Map<string, string>();

  const record: Plugin = {
    name: "atlas-scope:record-build-graph",
    enforce: "pre",
    transform(code, id) {
      const rel = toRel(id);
      if (rel !== null && !originalSource.has(rel)) originalSource.set(rel, code);
      return null;
    },
    generateBundle(_options, bundle) {
      for (const id of this.getModuleIds()) {
        const rel = toRel(id);
        if (rel === null) continue;
        files.add(rel);
        const info = this.getModuleInfo(id);
        const edges = [...(info?.importedIds ?? []), ...(info?.dynamicallyImportedIds ?? [])]
          .map(toRel)
          .filter((r): r is string => r !== null);
        importsOf.set(rel, edges.sort());
      }
      // Assets the build emitted from a source file (a CSS url() target above the inline limit).
      for (const out of Object.values(bundle)) {
        if (out.type !== "asset") continue;
        for (const o of out.originalFileNames ?? []) {
          const rel = toRel(isAbsolute(o) ? o : resolve(root, o));
          if (rel !== null) files.add(rel);
        }
      }
    },
  };

  /* Every file a JavaScript plugin reads while the build runs. Rolldown loads ordinary modules in
     native code (those are in getModuleIds above); what it never sees as a module — a CSS @import
     target, an inlined url() asset — is read by Vite's plugins through node:fs. */
  const reads = new Set<string>();
  const note = (p: unknown): void => {
    const s = p instanceof URL ? fileURLToPath(p) : typeof p === "string" ? p : Buffer.isBuffer(p) ? p.toString() : null;
    if (s !== null) reads.add(s);
  };
  const orig = { readFileSync: fs.readFileSync, readFile: fs.readFile, promisesReadFile: fs.promises.readFile };
  const patched = {
    readFileSync: ((p: unknown, ...a: unknown[]) => {
      note(p);
      return (orig.readFileSync as (...x: unknown[]) => unknown)(p, ...a);
    }) as typeof fs.readFileSync,
    readFile: ((p: unknown, ...a: unknown[]) => {
      note(p);
      return (orig.readFile as (...x: unknown[]) => unknown)(p, ...a);
    }) as typeof fs.readFile,
    promisesReadFile: ((p: unknown, ...a: unknown[]) => {
      note(p);
      return (orig.promisesReadFile as (...x: unknown[]) => unknown)(p, ...a);
    }) as typeof fs.promises.readFile,
  };
  fs.readFileSync = patched.readFileSync;
  fs.readFile = patched.readFile;
  fs.promises.readFile = patched.promisesReadFile;
  syncBuiltinESMExports();
  try {
    await build({
      root,
      configFile,
      logLevel: "silent",
      build: {
        write: false,
        minify: false,
        sourcemap: false,
        reportCompressedSize: false,
        copyPublicDir: false,
        rollupOptions: { input: Object.fromEntries(inputs.map((p, i) => [`page${i}`, resolve(root, p)])) },
      },
      plugins: [record],
    });
  } finally {
    fs.readFileSync = orig.readFileSync;
    fs.readFile = orig.readFile;
    fs.promises.readFile = orig.promisesReadFile;
    syncBuiltinESMExports();
  }
  for (const r of reads) {
    const rel = toRel(r);
    if (rel !== null) files.add(rel);
  }
  return { files: [...files].sort(), importsOf, originalSource };
}

/** How many times this file has built the compilers' program — counted, so its cost is asserted. */
let programsBuilt = 0;

/** tsconfig.scripts.json, parsed exactly as `tsc -p` parses it. */
export function scriptsConfig(): ts.ParsedCommandLine {
  const config = resolve(PKG, "tsconfig.scripts.json");
  const raw = ts.readConfigFile(config, (p) => readFileSync(p, "utf8"));
  return ts.parseJsonConfigFileContent(raw.config, ts.sys, PKG, undefined, config);
}

/**
 * The only two options the gate's program changes from the config, and why they cannot narrow it.
 *
 * WHAT THEY COST, MEASURED (acceptance F2, 2026-09-24). The program the config describes parsed 178
 * files to report 5: the other 173 were the default libraries (`lib.dom.d.ts` alone is 1.9 MB) and
 * the automatically included `@types/node` — 1.5 s on a quiet host, 7.7-12.6 s on a busy one, and
 * it was built twice per run. Every one of those 173 was then dropped by the `node_modules` filter
 * below, so none of them was ever part of the denominator.
 *
 * WHY THAT HOLDS BY CONSTRUCTION, not by this tree's luck. `noLib` stops TypeScript loading the
 * default libraries, which live in the compiler's own package (`getDefaultLibFilePath`); `types: []`
 * stops the AUTOMATIC inclusion of type packages, which come from `typeRoots`. Module resolution —
 * every `import`, `export … from`, `import()` and `/// <reference path>` the compilers write, and
 * any `/// <reference types>` they write themselves — is untouched, because every other option is
 * the config's own, spread unchanged. The preconditions test below asserts the two facts the
 * argument rests on: the default library directory and every configured type directive resolve
 * inside `node_modules`, and no `typeRoots` points outside it. If either stops being true the
 * gate goes red instead of quietly narrowing. Measured on this tree: the same 5 files either way.
 */
export const PROGRAM_OVERRIDES = Object.freeze({ noLib: true, types: [] as string[] });

let program: ts.Program | undefined;

/** The compilers' program: TypeScript's own resolution from tsconfig.scripts.json's roots, built once. */
export function compilerProgram(): ts.Program {
  if (program !== undefined) return program;
  const parsed = scriptsConfig();
  programsBuilt += 1;
  program = ts.createProgram(parsed.fileNames, { ...parsed.options, ...PROGRAM_OVERRIDES });
  return program;
}

/** The compilers' side: every file in the program TypeScript builds from tsconfig.scripts.json. */
export function compilerGraph(): string[] {
  return compilerProgram()
    .getSourceFiles()
    .map((sf) => relative(PKG, sf.fileName).split("\\").join("/"))
    .filter((r) => !r.startsWith("..") && !r.split("/").includes("node_modules"))
    .sort();
}

/** The gate itself: every file in `graph` that the tree of HEAD does not hold. */
export function notCommitted(graph: readonly string[], held: ReadonlySet<string>): string[] {
  return graph.filter((f) => !held.has(f)).sort();
}

/** Module-level static specifiers (`import`/`export … from`/`import()`), for attributing an edge. */
export function specifiersOf(file: string, text: string): string[] {
  const sf = ts.createSourceFile(file, text, ts.ScriptTarget.ES2023, true, file.endsWith("x") ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
  const out: string[] = [];
  const visit = (n: ts.Node): void => {
    if ((ts.isImportDeclaration(n) || ts.isExportDeclaration(n)) && n.moduleSpecifier && ts.isStringLiteral(n.moduleSpecifier)) {
      out.push(n.moduleSpecifier.text);
    }
    if (ts.isCallExpression(n) && n.expression.kind === ts.SyntaxKind.ImportKeyword) {
      const a = n.arguments[0];
      if (a !== undefined && (ts.isStringLiteral(a) || ts.isNoSubstitutionTemplateLiteral(a))) out.push(a.text);
    }
    ts.forEachChild(n, visit);
  };
  visit(sf);
  return out;
}

describe("everything the build loads and the compilers import is committed", () => {
  let real: BuildGraph;
  let pages: string[];
  beforeAll(async () => {
    pages = htmlPages();
    real = await buildGraph(PKG, resolve(PKG, "vite.config.ts"), pages);
  }, 120_000);

  it("builds every page the dev server serves, not only index.html", () => {
    expect(pages).toContain("index.html");
    expect(pages).toContain("fabric-preview.html");
    expect(pages).toContain("panels-preview.html");
    for (const p of pages) expect(real.files, `${p} was not an entry of the recorded build`).toContain(p);
    // Each preview page's own entry module is in the graph.
    expect(real.files).toContain("src/dev/preview.tsx");
    expect(real.files).toContain("src/dev/panels-preview.tsx");
  });

  it("the recorded graph is the real application, not an empty or entry-only set", () => {
    expect(real.files).toContain("src/main.tsx");
    expect(real.files).toContain("src/mount.tsx");
    expect(real.files).toContain("src/data/fabric.json");
    expect(real.files).toContain("src/core/tokens.css");
    expect(real.files.filter((f) => f.startsWith("src/forwarding/")).length).toBeGreaterThan(5);
    expect(real.files.filter((f) => f.startsWith("src/fabric3d/")).length).toBeGreaterThan(10);
    expect(real.files.length).toBeGreaterThan(80);
  });

  /* RE-EXPRESSED 2026-09-30 (phase 3.5 close). This case used to pin Inspector's
     `import.meta.glob("../forwarding/*.json")` edge. Phase 3 (1061fdea) removed that glob on purpose —
     it bound the Inspector to the BUNDLED sample's sidecars whatever dataset was installed, a second
     door src/core/dataset.test.ts now forbids — and the sidecars reach the standalone build through the
     one door, `core/dataset/bundled.ts`. The case asserted an edge the tree no longer has, so it was red
     from 1061fdea on. That the gate follows glob edges at all stays proved on a planted project below
     ("names exactly the planted files…": an eager glob and a lazy array glob); this case now pins the
     real tree's actual edge, and that the retired glob edge has not come back. */
  it("the two forwarding sidecars are reached through the dataset's one door, and Inspector no longer globs them", () => {
    const door = "src/core/dataset/bundled.ts";
    const doorSource = real.originalSource.get(door);
    expect(doorSource, "the build transformed the bundled-dataset door").toBeDefined();
    const doorStatics = specifiersOf(door, doorSource!);
    const inspector = "src/panels/Inspector.tsx";
    const inspectorSource = real.originalSource.get(inspector);
    expect(inspectorSource, "the build transformed Inspector.tsx").toBeDefined();
    expect(inspectorSource!).not.toMatch(/import\.meta\.glob\s*\(/);
    for (const sidecar of ["acl-bindings.json", "rib-evidence.json"]) {
      expect(doorStatics, `the door imports ${sidecar} statically`).toContain(`../../forwarding/${sidecar}`);
      expect(real.importsOf.get(door), `the edge ${door} -> ${sidecar}`).toContain(`src/forwarding/${sidecar}`);
      expect(real.importsOf.get(inspector) ?? [], `Inspector reaches ${sidecar} directly`).not.toContain(`src/forwarding/${sidecar}`);
      expect(real.files).toContain(`src/forwarding/${sidecar}`);
    }
  });

  it("the compilers' program reaches every compiler and what they import", () => {
    const tools = compilerGraph();
    expect(tools).toContain("tools/compile-snapshot.mjs");
    expect(tools).toContain("tools/source-binding.mjs");
    expect(tools.filter((f) => /^tools\/compile-.*\.mjs$/.test(f)).length).toBeGreaterThanOrEqual(4);
  });

  it("no file the build loads or the compilers import is missing from HEAD", () => {
    const missing = notCommitted([...new Set([...real.files, ...compilerGraph()])], committed());
    expect(
      missing,
      "these files are loaded by the build or imported by the compilers, and HEAD does not hold them —\n" +
        "every gate that reads them measures this working tree, not a reproducible revision.\n" +
        "The fix is to COMMIT them (the repository owner's decision), not to weaken this test:\n" +
        missing.join("\n"),
    ).toEqual([]);
  });
});

describe("the compilers' program is built once, and parses only what the gate counts", () => {
  /* ACCEPTANCE F2, 2026-09-24: "the compilers' program reaches every compiler…" took 35.6 s and "no
     file the build loads…" 31.4 s on a loaded host, against the 30 s limit — and each of them built
     the whole program again. Counted here rather than timed. */
  it("builds one program however many tests read the compilers' side", () => {
    const before = programsBuilt;
    const first = compilerGraph();
    const second = compilerGraph();
    expect(second).toEqual(first);
    expect(programsBuilt - before, "the compilers' program was built more than once").toBeLessThanOrEqual(1);
  });

  it("parses no default library and no automatically included type package: they are never counted", () => {
    const program = compilerProgram();
    const parsed = program.getSourceFiles();
    const lib = parsed.filter((sf) => program.isSourceFileDefaultLibrary(sf)).map((sf) => sf.fileName);
    const ambientTypes = parsed.filter((sf) => /[\/]node_modules[\/]@types[\/]/.test(sf.fileName)).map((sf) => sf.fileName);
    expect(lib, "default-library files parsed only to be filtered out").toEqual([]);
    expect(ambientTypes, "ambient type packages parsed only to be filtered out").toEqual([]);
  });

  it("what the two overrides leave out can only be a file the node_modules filter drops anyway", () => {
    const inModules = (p: string): boolean => p.split(/[\/]/).includes("node_modules");
    const parsed = scriptsConfig();
    expect(Object.keys(PROGRAM_OVERRIDES).sort(), "the program differs from the config in these options only").toEqual(["noLib", "types"]);
    // The default libraries noLib skips come from the compiler's own package.
    expect(inModules(ts.getDefaultLibFilePath(parsed.options)), ts.getDefaultLibFilePath(parsed.options)).toBe(true);
    // The type packages types: [] skips: no local typeRoots, and every configured one resolves inside node_modules.
    for (const root of parsed.options.typeRoots ?? []) expect(inModules(root), `typeRoots entry ${root}`).toBe(true);
    const configured = parsed.options.types ?? [];
    expect(configured.length, "precondition: the config names its type packages").toBeGreaterThan(0);
    for (const name of configured) {
      const hit = ts.resolveTypeReferenceDirective(name, resolve(PKG, "tsconfig.scripts.json"), parsed.options, ts.sys).resolvedTypeReferenceDirective;
      expect(hit?.resolvedFileName, `type package "${name}" did not resolve`).toBeDefined();
      expect(inModules(hit!.resolvedFileName!), `type package "${name}" resolved outside node_modules: ${hit?.resolvedFileName}`).toBe(true);
    }
  });
});

describe("known answer: a planted untracked file reachable only through a glob or a CSS @import turns the gate red", () => {
  /* A temporary project whose paths MIRROR files this repository commits (index.html, src/main.tsx,
     src/app/App.css, the two sidecars), plus planted files HEAD cannot hold. It is judged against the
     real HEAD, by the same functions the gate above uses. Nothing is written inside the repository. */
  let dir: string;
  const planted = [
    "src/forwarding/zz-untracked-probe-7f3a.json", // eager string glob, the refuter's case
    "src/fabric3d/zz-untracked-lazy-7f3a.ts", // lazy ARRAY glob, never statically imported
    "src/app/zz-untracked-import-7f3a.css", // CSS @import: never a module id, only a read
  ];
  beforeAll(() => {
    dir = mkdtempSync(join(tmpdir(), "atlas-tracked-"));
    const put = (rel: string, text: string): void => {
      mkdirSync(dirname(join(dir, rel)), { recursive: true });
      writeFileSync(join(dir, rel), text);
    };
    put("index.html", '<!doctype html><html><body><script type="module" src="/src/main.tsx"></script></body></html>');
    put(
      "src/main.tsx",
      [
        'import "./app/App.css";',
        'const sidecars = import.meta.glob("./forwarding/*.json", { eager: true, import: "default" });',
        'const lazy = import.meta.glob(["./fabric3d/zz-*.ts"]);',
        "console.log(sidecars, lazy);",
      ].join("\n"),
    );
    put("src/app/App.css", '@import "./zz-untracked-import-7f3a.css";\n.a { color: red; }\n');
    put("src/forwarding/acl-bindings.json", '{"a":1}');
    put("src/forwarding/rib-evidence.json", '{"b":2}');
    put(planted[0]!, '{"marker":"UNTRACKED_GLOB_PROBE_7f3a"}');
    put(planted[1]!, "export const lazyMarker = 1;\n");
    put(planted[2]!, ".planted { color: blue; }\n");
  });
  afterAll(() => {
    if (dir !== undefined) rmSync(dir, { recursive: true, force: true });
  });

  it("names exactly the planted files, and passes the mirrored committed ones", async () => {
    const held = committed();
    // Preconditions: the mirrored paths ARE in HEAD and the planted ones are not.
    for (const f of ["index.html", "src/main.tsx", "src/app/App.css", "src/forwarding/acl-bindings.json", "src/forwarding/rib-evidence.json"]) {
      expect(held.has(f), `${f} is committed`).toBe(true);
    }
    for (const f of planted) expect(held.has(f), `${f} must not be committed`).toBe(false);

    const g = await buildGraph(dir, false, ["index.html"]);
    expect(g.files).toContain("src/forwarding/acl-bindings.json");
    expect(g.files).toContain("src/forwarding/rib-evidence.json");
    expect(notCommitted(g.files, held)).toEqual([...planted].sort());
  }, 120_000);
});
