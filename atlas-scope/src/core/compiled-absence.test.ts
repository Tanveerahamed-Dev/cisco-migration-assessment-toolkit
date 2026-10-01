/**
 * compiled-absence.test.ts — absence must survive compilation.
 *
 * `tools/compile-snapshot.mjs` is the only bridge between the engine snapshot and this
 * application, and it is the one place where an unobserved field can be turned into a
 * measurement without any surface being able to notice. Three shipped instances, all found by an
 * adversarial audit against the REAL producer's output rather than a fixture (2026-09-21):
 *
 *   1. `num()` stripped every non-digit character before calling `Number()`, so `""`, `"N/A"`,
 *      `"unknown"` and `"[NOT OBSERVED]"` all compiled to the number 0. 92 of 122 ports rendered a
 *      clean 0 / 0 / 0 / 0 error profile — 73 of them on ports whose own source record says the
 *      counters were never read.
 *   2. The same helper turned 19 of 44 unobserved cable speeds into `0`, rendered as
 *      "Speed 0 Mbps" and ANNOUNCED as "0 megabit per second", while the cable geometry treated
 *      the identical value as "speed not observed". The same datum, rendered three ways.
 *   3. `arr(c.members).map(String)` stringified the source's member OBJECTS, so every link carried
 *      `["[object Object]"]` — printed verbatim as the "Port channel" value, and, because the array
 *      was never empty, the honest "members not observed" branch was unreachable.
 *
 * These assertions are made against the compiled artefact joined back to the SOURCE snapshot, so
 * they pin the property that matters — "what the snapshot did not say, the model does not say
 * either" — rather than the implementation of a helper.
 */
import { createHash } from "node:crypto";
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { basename, dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { fabric } from "./data";
import { describeGolden } from "../test-support/golden-sample";

const PKG = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");

interface SourcePort {
  switch?: unknown;
  port?: unknown;
  input_errors?: unknown;
  crc_errors?: unknown;
  output_errors?: unknown;
  output_drops?: unknown;
  late_collisions?: unknown;
  risk?: unknown;
}
interface SourceCable {
  speed?: unknown;
  members?: { a_port?: unknown; b_port?: unknown }[];
  is_pc?: unknown;
}
interface SourceSnapshot {
  physical_health?: SourcePort[];
  cable_map?: { cables?: SourceCable[] };
}

/* The real producer's output, not a fixture shaped like it: a hand-written fixture in the shape
   the compiler expects agrees with the compiler's bugs. */
/* The dataset UNDER TEST is the file the compiled model names — found by the DIGEST the model binds, never by a
   typed path (R7). The model names a repository file by its repository path, and a file outside the repository
   (the rename leg's renamed snapshot, `sourceOrigin: "external-file"`) by its file name only; that one is looked
   for where the phase legs write it (`.local-data/`, Git-ignored) or at ATLAS_DATASET_SOURCE. Every candidate must
   carry the bound bytes (sourceExactSha256, or the LF-normalised sourceSha256 for a checkout that rewrote line
   endings). None found fails the file loudly: a join against the wrong bytes, or no join, is never a pass
   (P3C-V2-3: the rename leg failed here on the file-name-only path). */
function sourceSnapshotPath(): string {
  const sha = (b: Buffer): string => createHash("sha256").update(b).digest("hex");
  const exact = fabric.meta.sourceExactSha256.replace(/^sha256:/, "");
  const carries = (p: string): boolean => {
    /* One read, no exists/stat check first (CodeQL js/file-system-race): nothing there, or a directory, carries nothing. */
    let b: Buffer;
    try {
      b = readFileSync(p);
    } catch (e) {
      if (["ENOENT", "ENOTDIR", "EISDIR"].includes((e as NodeJS.ErrnoException).code ?? "")) return false;
      throw e;
    }
    return sha(b) === exact || sha(Buffer.from(b.toString("utf8").replace(/\r\n/g, "\n"), "utf8")) === fabric.meta.sourceSha256;
  };
  const named = basename(fabric.meta.source);
  const underLocal = (dir: string, depth: number): string[] => {
    if (depth < 0 || !existsSync(dir)) return [];
    return readdirSync(dir, { withFileTypes: true }).flatMap((e) =>
      e.isDirectory() ? underLocal(join(dir, e.name), depth - 1) : e.name === named ? [join(dir, e.name)] : [],
    );
  };
  const candidates = [
    resolve(PKG, "..", fabric.meta.source),
    resolve(PKG, fabric.meta.source),
    ...(process.env.ATLAS_DATASET_SOURCE ? [resolve(process.env.ATLAS_DATASET_SOURCE)] : []),
    ...underLocal(resolve(PKG, ".local-data"), 3),
  ];
  const hit = candidates.find(carries);
  if (hit === undefined) {
    throw new Error(
      `the snapshot the loaded model was compiled from (${fabric.meta.source}, sha256 ${fabric.meta.sourceSha256}) was not found ` +
        `at ${candidates.join(", ")}; set ATLAS_DATASET_SOURCE to it.`,
    );
  }
  return hit;
}
const SNAPSHOT = sourceSnapshotPath();
const source = JSON.parse(readFileSync(SNAPSHOT, "utf8")) as SourceSnapshot;

/** Every way the engine writes "I did not collect this". */
const isAbsent = (v: unknown): boolean =>
  v === undefined ||
  v === null ||
  (typeof v === "string" && (v.trim() === "" || v.trim() === "-" || /^\s*(N\/A|unknown|\[NOT OBSERVED\])/i.test(v.trim())));

type Phys = (typeof fabric.physical)[number] & { lateCollisions?: number | null; riskUnobserved?: string | null };

describe("an uncollected counter is never compiled into a zero", () => {
  it("has both sides to compare — an empty join is not a pass", () => {
    // Non-empty on any dataset; the sample's population (over 100 ports) is pinned in the golden block below.
    expect(source.physical_health?.length ?? 0).toBeGreaterThan(0);
    expect(fabric.physical.length).toBe(source.physical_health!.length);
  });

  it("compiles every absent port counter to null, on every row", () => {
    const pairs: [keyof SourcePort, keyof Phys][] = [
      ["input_errors", "inputErrors"],
      ["crc_errors", "crcErrors"],
      ["output_errors", "outputErrors"],
      ["output_drops", "outputDrops"],
      ["late_collisions", "lateCollisions"],
    ];
    const offenders: string[] = [];
    source.physical_health!.forEach((src, i) => {
      const out = fabric.physical[i] as Phys;
      for (const [from, to] of pairs) {
        if (isAbsent(src[from]) && out[to] !== null && out[to] !== undefined) {
          offenders.push(`physical_health[${i}] ${String(src.switch)} ${String(src.port)}: ${from}=${JSON.stringify(src[from])} compiled to ${JSON.stringify(out[to])}`);
        }
      }
    });
    expect(
      offenders.slice(0, 12),
      `${offenders.length} port counters the collector never read were compiled to a number, and a\n` +
        `number renders as a measurement — 0 errors reads as a healthy port:\n${offenders.slice(0, 12).join("\n")}`,
    ).toEqual([]);
  });

  it("carries the counters the collector DID read, so this is not passing by emptying the model", () => {
    const observed = fabric.physical.filter((p) => p.inputErrors !== null || p.crcErrors !== null || p.outputDrops !== null);
    expect(observed.length).toBeGreaterThan(0);
  });

  it("keeps the engine's own reason for a port with no counters", () => {
    const withReason = fabric.physical.filter((p) => typeof (p as Phys).riskUnobserved === "string");
    expect(withReason.length, "the snapshot's [NOT OBSERVED] risk prose must reach the reader").toBeGreaterThan(0);
    for (const p of withReason) {
      expect(p.inputErrors, `${p.host} ${p.port} says its counters were not read`).toBeNull();
    }
  });
});

describe("an unobserved cable speed is never compiled into 0 Mbps", () => {
  it("compiles every absent speed to null", () => {
    const cables = source.cable_map?.cables ?? [];
    expect(cables.length).toBe(fabric.links.length);
    const offenders = cables
      .map((c, i) => {
        const out = fabric.links[i];
        return out !== undefined && isAbsent(c.speed) && out.speedMbps !== null ? `${out.id}: speed=${JSON.stringify(c.speed)} -> ${out.speedMbps}` : null;
      })
      .filter((x): x is string => x !== null);
    expect(offenders).toEqual([]);
  });

  it("emits no link with speedMbps === 0, which cables.ts already treats as absence", () => {
    /* src/fabric3d/geometry/cables.ts draws `speed === null || speed <= 0` at the absence width,
       while DevicePane and the 3-D live region read a 0 as a measurement. Pinning 0 out of the
       model is what stops those three consumers drifting apart again. */
    expect(fabric.links.filter((l) => l.speedMbps === 0).map((l) => l.id)).toEqual([]);
  });
});

describe("structured source data is never stringified into a label", () => {
  it("contains the literal '[object Object]' nowhere in the compiled model", () => {
    const text = JSON.stringify(fabric);
    const n = text.split("[object Object]").length - 1;
    expect(n, "a .map(String) over an object shipped a stringified placeholder as a rendered value").toBe(0);
  });

  it("compiles port-channel members as the port PAIRS the source carries", () => {
    const cables = source.cable_map?.cables ?? [];
    const pcs = cables.map((c, i) => ({ c, i })).filter(({ c }) => c.is_pc === true);
    expect(pcs.length, "the fabric has port-channels to check").toBeGreaterThan(0);
    for (const { c, i } of pcs) {
      const members = fabric.links[i]?.members ?? [];
      expect(members.length).toBe((c.members ?? []).length);
      for (const m of members) {
        expect(m).not.toContain("[object");
        expect(m).toMatch(/↔/);
      }
    }
  });

  it("leaves members EMPTY when the source names no port, so 'members not observed' is reachable", () => {
    const cables = source.cable_map?.cables ?? [];
    cables.forEach((c, i) => {
      const nameless = (c.members ?? []).filter((m) => isAbsent(m.a_port) && isAbsent(m.b_port)).length;
      expect(fabric.links[i]?.members.length ?? -1).toBe((c.members ?? []).length - nameless);
    });
  });
});

describe("a missing bridge flag is not a safety claim", () => {
  it("never publishes isBridge:false from an absent field", () => {
    /* `Boolean(cen.is_bridge)` on a present-but-empty field renders "Cutting it partitions: no"
       and is announced as "A redundant path exists around this link" — a safety claim derived from
       silence. Not reachable in this snapshot, which is why it needs a test rather than a look. */
    /* The compile logic moved (2026-09-26) from tools/compile-snapshot.mjs into the one pure compiler;
       the pin moves with the code it pins rather than going vacuous on a now-thin wrapper. */
    const compilerSource = readFileSync(resolve(PKG, "tools", "lib", "compile-model.mjs"), "utf8");
    expect(compilerSource).not.toMatch(/isBridge:\s*cen\s*\?\s*Boolean\(/);
    expect(compilerSource).toMatch(/isBridge:\s*cen\s*&&\s*typeof cen\.is_bridge === "boolean"/);
  });
});

describeGolden("compiled absence on the reference sample", () => {
  it("the join is over more than 100 ports", () => {
    expect(source.physical_health?.length ?? 0).toBeGreaterThan(100);
  });
});
