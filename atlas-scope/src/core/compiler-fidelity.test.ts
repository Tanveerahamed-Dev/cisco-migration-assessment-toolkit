/**
 * compiler-fidelity.test.ts — the compiled model must not lose what the engine already told us.
 *
 * `tools/compile-snapshot.mjs` is the only bridge between the assessment engine's snapshot and
 * this application. Anything it drops is, from the UI's point of view, evidence that was never
 * collected — and the UI will then either re-derive it from raw text or report it as a collection
 * gap. Both are wrong, and the second is a false statement made to the user.
 *
 * This suite pins the fields whose loss is not merely lossy but MISLEADING, each of which was found
 * by an adversarial refuter against the real producer (`cisco_toolkit.parse._acl_rule`):
 *
 *   - `unevaluable`          the producer's own verdict that a line cannot be modelled. Re-deriving
 *                            it from the raw text is the parser-versus-detector drift this
 *                            repository names explicitly; the producer's answer is the ground truth.
 *   - `unmodeled_qualifiers` which specific qualifier defeated it.
 *   - `established`          a stateful match. A forward-direction model cannot decide it.
 *   - `icmp_type`            an ICMP qualifier the matcher does not model.
 *   - `time_range`           the line is only active inside a named window. A definite verdict on a
 *                            time-ranged rule is an overclaim regardless of how the packet matches.
 *   - `src.group`/`dst.group` an object-group reference, AND the groups themselves, which the
 *                            snapshot does carry. Dropping the groups made the engine report its own
 *                            MODEL gap as a COLLECTION gap: it told the user the members "were not
 *                            collected" when they are present in the source file.
 */
import { createHash } from "node:crypto";
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { basename, dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { fabric } from "./data";
import { describeGolden } from "../test-support/golden-sample";

const PKG = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");

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
    if (!existsSync(p) || !statSync(p).isFile()) return false;
    const b = readFileSync(p);
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

/** The producer's own ACL rules and object groups, as the source snapshot carries them. */
interface SourceRule {
  unevaluable?: unknown;
  unmodeled_qualifiers?: unknown;
  established?: unknown;
  icmp_type?: unknown;
  time_range?: unknown;
  src?: { group?: unknown } | null;
  dst?: { group?: unknown } | null;
}
interface SourceGroup {
  kind?: unknown;
  members?: { ip?: unknown }[];
}
const source = JSON.parse(readFileSync(SNAPSHOT, "utf8")) as {
  acls?: Record<string, Record<string, SourceRule[]>>;
  object_groups?: Record<string, Record<string, SourceGroup>>;
};
/** Every source rule beside the line the compiler made of it (same host, ACL and position). */
const JOINED = Object.entries(source.acls ?? {}).flatMap(([host, named]) =>
  Object.entries(named).flatMap(([acl, rules]) =>
    rules.map((rule, i) => ({ at: `${host}.${acl}[${i}]`, rule, line: fabric.acls[host]?.[acl]?.[i] })),
  ),
);
const orNull = (v: unknown): unknown => (v === undefined ? null : v);

const allLines = () =>
  Object.entries(fabric.acls).flatMap(([host, named]) =>
    Object.entries(named).flatMap(([acl, lines]) => lines.map((l) => ({ host, acl, l }))),
  );

/** Every port match in the compiled ACLs: how many, how many carry a null value, and which break the property. */
function portCensus(): { ports: number; nullPorts: number; violations: string[] } {
  let ports = 0;
  let nullPorts = 0;
  const violations: string[] = [];
  for (const { host, acl, l } of allLines()) {
    for (const [side, p] of [
      ["sport", l.sport],
      ["dport", l.dport],
    ] as const) {
      if (p === null) continue;
      ports += 1;
      const hasNull = p.val === null || p.val === undefined || ("val2" in p && p.val2 === null);
      if (hasNull) nullPorts += 1;
      const ok = hasNull ? l.unevaluable === true : p.val !== null && p.val !== undefined;
      if (!ok)
        violations.push(
          hasNull
            ? `${host}.${acl}[${l.index}] ${side} has a null port value but is not marked unevaluable`
            : `${host}.${acl}[${l.index}] ${side} has no port value`,
        );
    }
  }
  return { ports, nullPorts, violations };
}

/* The named-skip preconditions of this file, at module scope so the golden block below can state that each holds on
   the reference sample (QC-R1-4): a sample change that falsified one must turn red, not into a silent skip. */
const withField = (pick: (r: SourceRule) => boolean) => JOINED.filter((j) => pick(j.rule));
const fieldCases: [string, (r: SourceRule) => boolean, (j: (typeof JOINED)[number]) => [unknown, unknown]][] = [
  ["keeps the producer's `unevaluable` verdict instead of making the engine re-derive it", (r) => r.unevaluable === true, (j) => [j.line!.unevaluable, true]],
  ["keeps which qualifier defeated the model, not just that one did", (r) => Array.isArray(r.unmodeled_qualifiers) && r.unmodeled_qualifiers.length > 0, (j) => [j.line!.unmodeledQualifiers, j.rule.unmodeled_qualifiers]],
  ["keeps `established`, which a forward-only model cannot decide", (r) => r.established === true, (j) => [j.line!.established, true]],
  ["keeps the ICMP type the matcher does not model", (r) => orNull(r.icmp_type) !== null, (j) => [j.line!.icmpType, j.rule.icmp_type]],
  ["keeps `time_range`, without which a conditional rule reads as unconditional", (r) => orNull(r.time_range) !== null, (j) => [j.line!.timeRange, j.rule.time_range]],
  ["keeps the object-group REFERENCE on the match field", (r) => orNull(r.src?.group) !== null || orNull(r.dst?.group) !== null, (j) => [[j.line!.src?.group ?? null, j.line!.dst?.group ?? null], [orNull(j.rule.src?.group), orNull(j.rule.dst?.group)]]],
];
const GROUPS = Object.entries(source.object_groups ?? {}).flatMap(([host, named]) => Object.entries(named).map(([name, g]) => ({ host, name, g })));

describe("the compiled ACL model preserves the producer's own verdicts", () => {
  it("carries at least one line, so this suite cannot pass on an empty set", () => {
    expect(allLines().length).toBeGreaterThan(5);
  });

  /* RE-EXPRESSED 2026-09-29 (P3C-V2-3): these tests read five lines of the sample by address (core1.MGMT_IN[0],
     core1.PROTECT_SERVERS[2], core1.INET_RETURN[0..1]) and failed on any other dataset. What they stood for is a
     JOIN: every rule the producer wrote beside the line the compiler made of it, field by field, over whatever the
     loaded snapshot holds (the source is read from the bound bytes above, independently of the compiler). Each
     field's population is stated, and a dataset carrying none of a field skips that test BY NAME; the audited lines
     are pinned in the golden block below. */
  it("every producer rule has a compiled line, at its host, ACL and position", () => {
    expect(JOINED.length, "the source snapshot carries ACL rules to join").toBeGreaterThan(0);
    expect(JOINED.filter((j) => j.line === undefined).map((j) => j.at)).toEqual([]);
  });

  for (const [title, pick, pair] of fieldCases) {
    const rows = withField(pick);
    it.runIf(withField(pick).length > 0)(rows.length > 0 ? title : `${title} [skipped: no producer rule in the loaded dataset carries it]`, () => {
      expect(rows.length).toBeGreaterThan(0);
      for (const j of rows) {
        expect(j.line, j.at).toBeDefined();
        const [got, want] = pair(j);
        expect(got, j.at).toEqual(want);
      }
    });
  }

  it("never invents a qualifier the producer did not write", () => {
    for (const j of JOINED) {
      if (j.line === undefined) continue;
      expect(j.line.unevaluable, j.at).toBe(j.rule.unevaluable === true);
      expect(j.line.established, j.at).toBe(j.rule.established === true);
      expect(j.line.icmpType, j.at).toBe(orNull(j.rule.icmp_type));
      expect(j.line.timeRange, j.at).toBe(orNull(j.rule.time_range));
    }
  });

  it.runIf(GROUPS.length > 0)(
    GROUPS.length > 0
      ? "keeps the object groups THEMSELVES, which the snapshot does carry"
      : "keeps the object groups THEMSELVES, which the snapshot does carry [skipped: the loaded dataset carries no object group]",
    () => {
      /* This is the one that produced a false statement to the user. With the groups dropped, the engine could
         not resolve a group and reported "whose members were not collected" — while the source file carries its
         members. A model gap described as a collection gap is a lie about our own evidence. */
      for (const { host, name, g } of GROUPS) {
        const c = fabric.objectGroups[host]?.[name];
        expect(c, `${host}/${name} is present in the source snapshot`).toBeDefined();
        expect(c!.kind, `${host}/${name}`).toBe(g.kind);
        expect(c!.members.map((m) => m.ip), `${host}/${name}`).toEqual((g.members ?? []).map((m) => m.ip));
        expect(c!.cite).toBe(`object_groups.${host}.${name}`);
      }
    },
  );

  it("every line that the producer marked unevaluable says WHY", () => {
    /* The loop below asserts only inside the `unevaluable` branch, so the branch's population is
       pinned first: a snapshot with no unevaluable line would otherwise pass having checked nothing. */
    expect(allLines().filter(({ l }) => l.unevaluable === true).length, "unevaluable lines in the snapshot").toBeGreaterThan(0);
    for (const { host, acl, l } of allLines()) {
      if (l.unevaluable === true) {
        const why = [
          l.unmodeledQualifiers.length > 0,
          l.established === true,
          l.icmpType !== null,
          l.timeRange !== null,
          l.src?.group !== null && l.src?.group !== undefined,
          l.dst?.group !== null && l.dst?.group !== undefined,
        ].some(Boolean);
        expect(why, `${host}.${acl}[${l.index}] is unevaluable with no recorded reason`).toBe(true);
      }
    }
  });

  it("a port match with a null value is never silently treated as a real port", () => {
    /* The refuter's blocker: the producer emits {"op":"eq","val":null} for a port NAME it cannot
       resolve (e.g. `eq citrix`). Compared numerically that is a definite non-match, so a permit
       line silently stops firing and the flow falls through to a deny — a definite "denied" for a
       flow the configuration explicitly permits. Whatever else is true, a null port value must be
       visible in the model rather than erased. */
    /* EVERY port match is judged, not only the null ones: the first version asserted inside
       `if (hasNull)` alone, and this snapshot carries no null port value, so it ran, passed and made
       ZERO assertions (the runtime assertion guard, src/test-setup.ts, found it). Each port now
       either carries a readable value or is marked unevaluable — the property itself, stated for
       the whole population — and the population is pinned so an empty one cannot pass. */
    /* The property is collected as a list of violations and asserted once, so it runs (and asserts) on a
       dataset with no port match at all; the population itself is a fact about ONE snapshot and is pinned in
       the golden tier below, not here. */
    expect(portCensus().violations).toEqual([]);
  });
});

describeGolden("the compiled ACL model of the reference sample", () => {
  it("every field case and the object-group check have rows here, so none is skipped on the sample", () => {
    expect(fieldCases.filter(([, pick]) => withField(pick).length === 0).map(([t]) => t)).toEqual([]);
    expect(GROUPS.map(({ host, name }) => `${host}/${name}`)).toContain("core1/MGMT_HOSTS");
  });

  it("the audited lines keep what the producer wrote (core1's MGMT_IN, PROTECT_SERVERS and INET_RETURN)", () => {
    const acl = (name: string, i: number) => fabric.acls["core1"]?.[name]?.[i];
    expect(acl("MGMT_IN", 0)?.unevaluable).toBe(true);
    expect(acl("MGMT_IN", 0)?.src?.group).toBe("MGMT_HOSTS");
    expect(acl("PROTECT_SERVERS", 2)?.unmodeledQualifiers).toContain("icmp_type");
    expect(acl("PROTECT_SERVERS", 2)?.icmpType).toBe("echo-reply");
    expect(acl("INET_RETURN", 0)?.established).toBe(true);
    expect(acl("INET_RETURN", 1)?.timeRange).toBe("BUSINESS_HOURS");
    const g = fabric.objectGroups["core1"]?.["MGMT_HOSTS"];
    expect(g?.kind).toBe("network");
    expect(g?.members.map((m) => m.ip)).toEqual(["10.0.99.10", "10.0.40.0"]);
  });


  it("carries eight port matches, none with a null value", () => {
    /* Known answer re-derived from the regenerated sample (GOLDEN_SHA). It was six on the sample before the
       phase-3 regeneration; the count is a fact about one snapshot, so it lives here. On THIS data the null
       branch of the property above is empty, and that is a stated, checked fact instead of a silent pass. */
    const { ports, nullPorts } = portCensus();
    expect({ ports, nullPorts }, "port matches in the compiled snapshot").toEqual({ ports: 8, nullPorts: 0 });
  });
});
