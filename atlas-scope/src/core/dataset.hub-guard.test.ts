// @vitest-environment node
/**
 * dataset.hub-guard.test.ts — the hub build's own pre-write privacy scan (vite.config.ts
 * `hubBundleProblems`) recognises a compiled snapshot model by EVERY signature AssessHub's /scope indexer
 * refuses (webapp/backend/app.py `_scope_file_carries_compiled_model`), not only by a `sourceGitBlob` literal
 * and a tracked digest (phase 3.5, P3E-V6).
 *
 * Why: AssessHub serves /scope OUTSIDE its API guard. The build refusing to write a file that carries
 * snapshot evidence is the first line; AssessHub's indexer is the second. When the first line knew only the
 * binding envelope, a bundler that dropped the envelope (Vite's JSON plugin turns a document's members into
 * named exports, and `meta` goes) or a copy of the engine snapshot itself passed the build and was stopped
 * only at serve time. The signatures here are the indexer's, rooted in the compiler's own exports
 * (SECTIONS_READ, SUPPORTED_SCHEMAS) rather than a list typed in this file.
 *
 * Each form is planted, and the positive control is the REAL producer's output: the tracked compiled fabric
 * as the compiler wrote it and as a bundler would inline its records. The negative control is the compiler's
 * own code shape (citations built from template literals), which the real hub build carries in its worker
 * and which must not trip the scan — src/core/dataset.build.test.ts builds the hub bundle through this very
 * guard, so a false positive there fails that build.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { gzipSync } from "node:zlib";
import { describe, expect, it } from "vitest";
import { hubBundleProblems } from "../../vite.config";
import { PKG } from "../test-support/dataset/testing";

const scan = (name: string, text: string | Uint8Array): string[] =>
  hubBundleProblems([{ name, bytes: typeof text === "string" ? Buffer.from(text, "utf8") : text, moduleIds: [] }], new Set());

const fabricText = readFileSync(resolve(PKG, "src", "data", "fabric.json"), "utf8");
const fabricDoc = JSON.parse(fabricText) as { devices: { cite: string }[] };

describe("a compiled record is recognised by its snapshot citation, as AssessHub's indexer recognises it", () => {
  it("a citation bound to a cite-named key, in the bundler's object-literal form", () => {
    expect(scan("a.js", 'const d=[{host:"core1",cite:"devices.core1"}];')).not.toEqual([]);
    expect(scan("b.js", 'const r={centralityCite:"link_centrality[3]"};')).not.toEqual([]);
  });

  it("a citation used as an object key (a citation-keyed map)", () => {
    expect(scan("c.js", 'const m={"interfaces.core1.Gi1/0/1":{acl:null}};')).not.toEqual([]);
  });

  it("the engine's JSON-Pointer citation form", () => {
    expect(scan("d.js", 'const f={evidenceCite:"/interfaces/core1/Gi1~10~11"};')).not.toEqual([]);
  });

  it("a JSON document escaped inside a JS string, pretty or compact", () => {
    expect(scan("e.js", 'const s=JSON.parse("{\\"cite\\":\\"routes.core1[0]\\"}");')).not.toEqual([]);
    expect(scan("f.js", 'const s="{\\n  \\"cite\\": \\"acls.core1.PROTECT_SERVERS[2]\\"\\n}";')).not.toEqual([]);
  });

  it("an engine snapshot itself (its schema bound to the engine's snapshot schema family)", () => {
    expect(scan("g.json", '{"schema":"collect_parse_snapshot/1","devices":{}}')).not.toEqual([]);
  });

  it("inside a base64 data: URI, and inside a gzip stream", () => {
    const payload = Buffer.from('{"cite":"devices.core1"}', "utf8").toString("base64");
    expect(scan("h.js", `const u="data:application/json;base64,${payload}";`)).not.toEqual([]);
    expect(scan("i.js.gz", gzipSync(Buffer.from('const d=[{cite:"devices.core1"}];', "utf8")))).not.toEqual([]);
  });

  it("a compressed stream this scan cannot open (bzip2, xz) is refused, never read as clean", () => {
    expect(scan("j.bin", Buffer.concat([Buffer.from("BZh91AY&SY"), Buffer.alloc(16)]))).not.toEqual([]);
    expect(scan("k.bin", Buffer.concat([Buffer.from([0xfd, 0x37, 0x7a, 0x58, 0x5a, 0x00]), Buffer.alloc(16)]))).not.toEqual([]);
  });
});

describe("controls", () => {
  it("positive, from the real producer: the tracked compiled fabric, whole and as inlined records", () => {
    expect(scan("fabric.json", fabricText)).not.toEqual([]);
    const inlined = `const devices=${JSON.stringify(fabricDoc.devices.slice(0, 2))};`;
    expect(scan("inlined.js", inlined), "a bundler that drops `meta` still ships the records' citations").not.toEqual([]);
  });

  it("negative: the compiler's own code shape — citations from template literals, the binding keys only NAMED", () => {
    const code = [
      "const c=`interfaces.${host}.${port}`;",
      "const r={cite:`routes.${h}[${i}]`};",
      'const KEYS=["source","sourceOrigin","sourceDigestForm","sourceSha256","sourceBytes","sourceExactSha256","sourceGitBlob"];',
      'const label={sourceDigestForm:"assesshub-store-blob"};',
      'const msg="the cite of a record";',
    ].join("\n");
    expect(scan("worker.js", code)).toEqual([]);
  });
});
