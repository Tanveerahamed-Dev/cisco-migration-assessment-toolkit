// @vitest-environment node
/**
 * dataset.test.ts — the four compiled documents enter the application through ONE door (core/dataset.ts),
 * and a dataset installed before the application loads is the one every surface reads.
 *
 * Why this is a test and not a convention: a runtime dataset (an AssessHub snapshot, an opened file) is
 * installed by replacing what `core/dataset.ts` exports. A module that kept its own static import of a
 * compiled document would go on rendering the SAMPLE's evidence beside the installed fabric — and its
 * binding check would then turn every answer "unknown" with no error anywhere. So the census below is
 * derived from the compiler's own OUTPUTS (every document it writes), not from a list of today's readers.
 */
import { existsSync, globSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, relative, resolve } from "node:path";
import ts from "typescript";
import { afterEach, describe, expect, it, vi } from "vitest";
import { OUTPUTS } from "../../tools/lib/compile-model.mjs";
import { SOURCE_BINDING_KEYS } from "./types";
import { asOpenedFile, compileGolden, PKG } from "../test-support/dataset/testing";

const SRC = resolve(PKG, "src");
const posix = (p: string): string => p.split("\\").join("/");

afterEach(() => {
  vi.resetModules();
});

describe("the bundled dataset", () => {
  it("is the dataset the runner was pointed at (the tracked sample, or ATLAS_DATASET_DIR)", async () => {
    const { dataset, datasetOrigin, isBundledSample } = await import("./dataset");
    const dir = process.env.ATLAS_DATASET_DIR;
    for (const o of OUTPUTS) {
      const file = dir ? resolve(PKG, dir, o.file) : resolve(PKG, o.trackedPath);
      const onDisk = JSON.parse(readFileSync(file, "utf8")) as { meta: unknown };
      expect(dataset[o.key].meta, `${o.key} is read from ${posix(relative(PKG, file))}`).toEqual(onDisk.meta);
    }
    expect(datasetOrigin).toEqual({ kind: "bundled-sample" });
    expect(isBundledSample).toBe(true);
  });

  it("an AssessHub build (no bundled dataset) with nothing installed refuses to start instead of showing anything", async () => {
    const { selectActiveDataset } = await import("./dataset/select");
    expect(() => selectActiveDataset(null, null)).toThrow(/E_NO_DATASET/);
    const golden = compileGolden();
    expect(selectActiveDataset(null, golden).origin).toEqual({ kind: "bundled-sample" });
    expect(selectActiveDataset(asOpenedFile(golden), null).origin.kind).toBe("opened-file");
    /* And it IS the rule core/dataset.ts applies (not a restatement of it). */
    expect(readFileSync(resolve(SRC, "core", "dataset.ts"), "utf8")).toMatch(/selectActiveDataset\(installed, BUNDLED\)/);
  });
});

describe("a dataset installed before the application loads is the one every reader sees", () => {
  const golden = compileGolden();

  it("core/data.ts builds its model and indexes from the installed fabric", async () => {
    const slot = await import("./dataset/slot");
    slot.installDataset(asOpenedFile(golden));
    const data = await import("./data");
    expect(data.fabric.meta.sourceSha256).toBe(golden.fabric.meta.sourceSha256);
    expect(data.fabric.devices.length).toBe(golden.fabric.devices.length);
    expect([...data.deviceById.keys()].sort()).toEqual(golden.fabric.devices.map((d) => d.id).sort());
    const { datasetOrigin, isBundledSample } = await import("./dataset");
    expect(datasetOrigin.kind).toBe("opened-file");
    expect(isBundledSample).toBe(false);
  });

  it("panels/producer-emission.ts reads the installed sidecar, so it trusts it (same bytes as the fabric)", async () => {
    const slot = await import("./dataset/slot");
    slot.installDataset(asOpenedFile(golden));
    const data = await import("./data");
    const pe = await import("../panels/producer-emission");
    /* Both halves: the fabric IS the installed one, and the sidecar is trusted against it. A module that
       kept its own static import of the sample's sidecar reads false here (sample bytes vs golden bytes). */
    expect(data.fabric.meta.sourceSha256).toBe(golden.fabric.meta.sourceSha256);
    expect(pe.PRODUCER_EMISSION_TRUSTED).toBe(true);
    const [host, fields] = Object.entries(golden.producerEmission.deviceAbsent).find(([, f]) => f.length > 0)!;
    const record = data.fabric.devices.find((d) => d.host === host);
    expect(pe.producerFieldNotEmitted(null, record, fields[0]!)).toContain(host);
  });

  it("an install after the application read its dataset throws rather than being silently invisible", async () => {
    const slot = await import("./dataset/slot");
    await import("./data");
    expect(() => slot.installDataset(asOpenedFile(golden))).toThrow(/after the application had already read/);
    expect(() => slot.noteDatasetNotice({ code: "X", message: "x" })).toThrow(/never be shown/);
  });

  it("a second install for one page is refused", async () => {
    const slot = await import("./dataset/slot");
    slot.installDataset(asOpenedFile(golden));
    expect(() => slot.installDataset(asOpenedFile(golden))).toThrow(/already installed/);
  });

  it("a mixed set (a sidecar bound to other bytes than the fabric) is refused at install, key by key", async () => {
    const slot = await import("./dataset/slot");
    for (const k of SOURCE_BINDING_KEYS) {
      const mixed = structuredClone(golden);
      (mixed.ribEvidence.meta as unknown as Record<string, unknown>)[k] = "other";
      expect(() => slot.installDataset(asOpenedFile(mixed)), `binding key ${k}`).toThrow(/ribEvidence document is bound to other bytes/);
    }
    const missing = structuredClone(golden) as unknown as Record<string, unknown>;
    delete missing.aclBindings;
    expect(() => slot.installDataset(asOpenedFile(missing as never))).toThrow(/aclBindings document is missing/);
  });

  it("the slot's coherence rule names every binding key core/types.ts declares", async () => {
    const slot = await import("./dataset/slot");
    expect([...slot.SLOT_BINDING_KEYS]).toEqual([...SOURCE_BINDING_KEYS]);
  });
});

describe("ATLAS_DATASET_DIR (vitest.config.ts): the suite reads another compiled directory, or refuses to run", () => {
  const writeSet = (dir: string, set: Record<string, unknown>): void => {
    mkdirSync(dir, { recursive: true });
    for (const o of OUTPUTS) writeFileSync(join(dir, o.file), JSON.stringify(set[o.key]));
  };
  type Resolver = (this: { resolve: (s: string, i: string) => Promise<{ id: string } | null> }, s: string, i: string, o: object) => Promise<string | null>;

  it("unset or empty: no override", async () => {
    const { datasetDirOverride } = await import("../../vite.config");
    expect(datasetDirOverride(undefined)).toEqual([]);
    expect(datasetDirOverride("")).toEqual([]);
  });

  it("a directory missing a document is a configuration error, never a fallback to the sample", async () => {
    const { datasetDirOverride } = await import("../../vite.config");
    const dir = mkdtempSync(join(tmpdir(), "atlas-ds-"));
    try {
      writeFileSync(join(dir, "fabric.json"), "{}");
      expect(() => datasetDirOverride(dir)).toThrow(/has no acl-bindings\.json/);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("a directory whose documents are bound to different bytes is refused", async () => {
    const { datasetDirOverride } = await import("../../vite.config");
    const dir = mkdtempSync(join(tmpdir(), "atlas-ds-"));
    try {
      const mixed = structuredClone(compileGolden()) as unknown as Record<string, { meta: Record<string, unknown> }>;
      mixed.ribEvidence!.meta.sourceSha256 = "0".repeat(64);
      writeSet(dir, mixed);
      expect(() => datasetDirOverride(dir)).toThrow(/rib-evidence\.json is bound to other bytes/);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("a whole set: every import of a tracked compiled document resolves to the directory's file", async () => {
    const { datasetDirOverride } = await import("../../vite.config");
    const dir = mkdtempSync(join(tmpdir(), "atlas-ds-"));
    try {
      writeSet(dir, compileGolden() as unknown as Record<string, unknown>);
      const [plugin] = datasetDirOverride(dir);
      const hook = plugin!.resolveId as unknown as Resolver;
      const ctx = { resolve: async (s: string, i: string) => ({ id: resolve(join(i, ".."), s) }) };
      for (const o of OUTPUTS) {
        const importer = resolve(PKG, o.trackedPath, "..", "x.ts");
        expect(await hook.call(ctx, `./${o.file}`, importer, {}), o.file).toBe(join(dir, o.file));
      }
      expect(await hook.call(ctx, "./other.json", resolve(PKG, "src/core/x.ts"), {})).toBeNull();
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });
});

describe("documentsByFile", () => {
  it("is keyed by exactly the file names the compiler writes, each the same document the named exports carry", async () => {
    const d = await import("./dataset");
    expect(Object.keys(d.documentsByFile).sort()).toEqual(OUTPUTS.map((o) => o.file).sort());
    for (const o of OUTPUTS) expect(d.documentsByFile[o.file], o.file).toBe(d.dataset[o.key]);
  });
});

/**
 * THE CENSUS. Every authored, non-test module under src/ that reaches one of the compiler's output
 * documents (by the resolved path of OUTPUTS[].trackedPath) by ANY form Vite resolves to a file: a static
 * or dynamic import or re-export (with or without a `?query`), an `import.meta.glob` pattern (expanded
 * against the file system, exactly as Vite expands it), or a `new URL("…", import.meta.url)` asset
 * reference. Exactly one module may: dataset/bundled.ts.
 */
/** The resolved path of every compiled document, keyed case-insensitively (Windows paths). */
const TRACKED = new Map(OUTPUTS.map((o) => [posix(resolve(PKG, o.trackedPath)).toLowerCase(), o.trackedPath]));
const literalsOf = (n: ts.Node): string[] =>
  ts.isStringLiteralLike(n) ? [n.text] : ts.isArrayLiteralExpression(n) ? n.elements.flatMap(literalsOf) : [];

/**
 * THE CENSUS'S ONE SCAN: every compiled document one module's source text reaches, and by which form. It is
 * a function of (path, text) so the planted positive control below runs THIS scan — not a copy of it — over
 * a text holding every form (phase 3.5, P3E-V1: the control used to re-implement the visitor, so a
 * regression in the census's own glob or URL detection could not turn it red).
 */
function reachedDocuments(absPath: string, text: string): { doc: string; via: string }[] {
  const out: { doc: string; via: string }[] = [];
  const here = join(absPath, "..");
  const hit = (target: string, via: string): void => {
    const doc = TRACKED.get(posix(target).toLowerCase());
    if (doc !== undefined) out.push({ doc, via });
  };
  for (const f of ts.preProcessFile(text, true, true).importedFiles) {
    if (f.fileName.startsWith(".")) hit(resolve(here, f.fileName.replace(/[?#].*$/, "")), "import");
  }
  const sf = ts.createSourceFile(absPath, text, ts.ScriptTarget.ES2023, true, absPath.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
  const visit = (n: ts.Node): void => {
    if (ts.isCallExpression(n) && ts.isPropertyAccessExpression(n.expression) && n.expression.getText(sf).replace(/\s/g, "") === "import.meta.glob") {
      for (const pattern of n.arguments[0] ? literalsOf(n.arguments[0]) : []) {
        if (pattern.startsWith("!")) continue;
        for (const m of globSync(pattern, { cwd: here })) hit(resolve(here, m), "import.meta.glob");
      }
    }
    if (ts.isNewExpression(n) && n.expression.getText(sf) === "URL" && n.arguments?.[0] && ts.isStringLiteralLike(n.arguments[0])) {
      hit(resolve(here, n.arguments[0].text), "new URL");
    }
    ts.forEachChild(n, visit);
  };
  visit(sf);
  return out;
}

describe("one door: no application module but dataset/bundled.ts reaches a compiled document", () => {
  const importers: { file: string; doc: string; via: string }[] = [];
  let scanned = 0;
  const walk = (dir: string): void => {
    /* The entry's type comes from the directory read itself — no second stat of the path before it is read. */
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const name = entry.name;
      if (name.startsWith("_") || name === "node_modules") continue;
      const p = join(dir, name);
      if (entry.isDirectory()) {
        walk(p);
        continue;
      }
      if (!/\.(ts|tsx)$/.test(name) || /\.test\.tsx?$/.test(name) || name.endsWith(".d.ts")) continue;
      scanned += 1;
      for (const r of reachedDocuments(p, readFileSync(p, "utf8"))) importers.push({ file: posix(relative(PKG, p)), ...r });
    }
  };
  walk(SRC);

  it("the scan read the application and found the bundled module's imports (positive control)", () => {
    expect(scanned).toBeGreaterThan(50);
    for (const o of OUTPUTS) {
      expect(existsSync(resolve(PKG, o.trackedPath)), o.trackedPath).toBe(true);
      expect(importers).toContainEqual({ file: "src/core/dataset/bundled.ts", doc: o.trackedPath, via: "import" });
    }
  });

  it("every form is recognised by the census's own scan (planted, not assumed)", () => {
    const planted = [
      'import fabric from "../data/fabric.json";',
      'const a = import.meta.glob("../forwarding/*.json", { eager: true });',
      'const b = import . meta . glob(["!../forwarding/*.json", "../panels/producer-emission.json"]);',
      'const c = new URL("../data/fabric.json", import.meta.url);',
      'const d = () => import("../forwarding/rib-evidence.json?raw");',
    ].join("\n");
    const found = reachedDocuments(join(SRC, "core", "planted.ts"), planted);
    const key = (r: { doc: string; via: string }): string => `${r.via} ${r.doc}`;
    expect(found.map(key).sort()).toEqual(
      [
        "import src/data/fabric.json",
        "import src/forwarding/rib-evidence.json",
        "import.meta.glob src/forwarding/acl-bindings.json",
        "import.meta.glob src/forwarding/rib-evidence.json",
        "import.meta.glob src/panels/producer-emission.json",
        "new URL src/data/fabric.json",
      ].sort(),
    );
    /* And a text that reaches nothing reports nothing (the scan is not merely permissive). */
    expect(reachedDocuments(join(SRC, "core", "planted.ts"), 'import x from "./types";\nconst u = new URL("./other.json", import.meta.url);')).toEqual([]);
  });

  it("no other module imports one", () => {
    expect(importers.filter((i) => i.file !== "src/core/dataset/bundled.ts")).toEqual([]);
  });
});
