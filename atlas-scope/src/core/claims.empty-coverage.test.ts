/**
 * claims.ts over a fleet with NO collected routing table and NO collected ACL (disc-app-sample-assumptions #6).
 *
 * The reference sample always has some RIB and ACL hosts, so every sentence that joins those host lists read
 * well on it and nowhere else: with zero RIB hosts T4 said "(0 of 26 hosts have one: )" and the share payload
 * "RIBs collected for  (0 of 26 hosts)". Every host-list join in claims.ts now goes through the one owner,
 * `listPhrase` (src/core/phrases.ts), which always yields a phrase. This file runs the real claims module over
 * the real compiled fabric with its coverage lists emptied, so the empty case is executed, not assumed.
 */
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";
import { describe, expect, it, vi } from "vitest";

vi.mock("./data", async (importOriginal) => {
  const real = await importOriginal<typeof import("./data")>();
  return {
    ...real,
    fabric: {
      ...real.fabric,
      coverage: { ...real.fabric.coverage, routableHosts: [], hostsWithRoutes: 0, aclHosts: [], hostsWithAcls: 0 },
    },
  };
});

import { T3_outOfScope, T4_unmodelledHost, sharePayload } from "./claims";
import { fabric } from "./data";
import type { Trace } from "./types";

/** The shapes an empty join leaves behind: a doubled space, a list introducer followed by nothing. */
function brokenJoins(s: string): string[] {
  const shapes: [string, RegExp][] = [
    ["double space", / {2,}/],
    ["colon then close", /:\s*[)."]/],
    ["'for' then nothing", /\bfor\s*[(.,]/],
    ["dangling comma", /,\s*[).]/],
  ];
  return shapes.filter(([, re]) => re.test(s)).map(([name]) => name);
}

const outOfScope: Trace = {
  flow: { srcIp: "198.51.100.7", dstIp: "203.0.113.9", protocol: "tcp", dstPort: 443, srcPort: null },
  outcome: "out-of-scope",
  hops: [],
  claim: "",
  caveats: [],
  unmodelledHosts: [],
  elapsedMs: 0,
};

describe("host-list sentences over a fleet with no collected RIB or ACL", () => {
  it("precondition: the mock really emptied the coverage lists the sentences join", () => {
    expect(fabric.coverage.routableHosts).toEqual([]);
    expect(fabric.coverage.aclHosts).toEqual([]);
    expect(fabric.devices.length).toBeGreaterThan(0);
  });

  it("T4 names that no host has a RIB instead of joining an empty list", () => {
    const s = T4_unmodelledHost("some-host");
    expect(brokenJoins(s), s).toEqual([]);
    expect(s).toContain(`(0 of ${fabric.devices.length} hosts have one: none)`);
  });

  it("the share payload's SCOPE line reads 'no host' for both empty lists", () => {
    const p = sharePayload(outOfScope);
    const scope = p.split("\n").find((l) => l.startsWith("SCOPE:"));
    expect(scope).toBeDefined();
    expect(brokenJoins(scope!), scope).toEqual([]);
    expect(scope).toBe(`SCOPE: RIBs collected for no host (0 of ${fabric.devices.length} hosts). ACLs collected for no host.`);
  });

  it("T3 says 'none recorded' when no subnet was observed", () => {
    const s = T3_outOfScope("198.51.100.7", []);
    expect(brokenJoins(s), s).toEqual([]);
    expect(s).toContain("Observed subnets: none recorded.");
  });
});

describe("the class: every name-list join in claims.ts goes through listPhrase", () => {
  /* A guard on the three sentences above would be a named subset standing in for the class. The class is
     "a list of names joined into prose", and its only spelling in this module is `.join(", ")` (the "; "
     joins separate CLAUSES, each of which is itself a phrase, and the "\n" join assembles lines). So the
     module may not contain that spelling at all, nor a hand-rolled `|| "no host"` fallback beside one. */
  const src = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "claims.ts"), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/(^|[^:])\/\/.*$/gm, "$1");
  it("claims.ts has no bare comma join and no local empty-list fallback", () => {
    expect(src.match(/\.join\(\s*["'`],\s*["'`]\s*\)/g) ?? []).toEqual([]);
    expect(src.match(/\|\|\s*["'`]no host["'`]/g) ?? []).toEqual([]);
  });
  it("and it does import the one owner", () => {
    expect(src).toMatch(/import \{[^}]*\blistPhrase\b[^}]*\} from "\.\/phrases";/);
  });
});

/* ── the class across the product (P3C-V2-5, verifier of phase 3) ──
 * The scan above reads claims.ts alone; src/analysis/blast.ts still hand-joined the RIB host list with its own
 * empty case (`routableHosts.join(", ") || "none"`), the same class in another file. The class's syntactic marker
 * is a comma join with a LOCAL fallback beside it — a list of names put into prose with a hand-rolled empty case
 * instead of the owner's — and every non-test source under src/ is scanned for it. Sites in files this cluster does
 * not own are routed to their owners and ratcheted here: each must still match, so the day one is fixed the entry
 * goes red until it is removed. */
describe("the class: no hand-rolled empty case beside a comma join, anywhere in src", () => {
  const SRC = join(dirname(fileURLToPath(import.meta.url)), "..");
  const sources = (dir: string): string[] =>
    readdirSync(dir, { withFileTypes: true }).flatMap((e) =>
      e.isDirectory()
        ? /^(_|node_modules$|data$)/.test(e.name)
          ? []
          : sources(join(dir, e.name))
        : /\.tsx?$/.test(e.name) && !/\.test\.tsx?$/.test(e.name) && !/\.d\.ts$/.test(e.name)
          ? [join(dir, e.name)]
          : [],
    );
  const FALLBACK = /\.join\(\s*["'`],\s*["'`]\s*\)\s*\|\|/g;
  const PENDING: Record<string, number> = {
    "app/CoverageBar.tsx": 1,
    "app/StatusBar.tsx": 2,
    "panels/ClaimCard.tsx": 1,
    "panels/PathTrace.tsx": 1,
  };
  const strip = (s: string): string => s.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:])\/\/.*$/gm, "$1");
  const found = new Map<string, number>();
  for (const f of sources(SRC)) {
    const n = (strip(readFileSync(f, "utf8")).match(FALLBACK) ?? []).length;
    if (n > 0) found.set(f.slice(SRC.length + 1).split("\\").join("/"), n);
  }

  it("scanned the product (the file set is not empty) and the pattern finds its own known answer", () => {
    expect(sources(SRC).length).toBeGreaterThan(50);
    expect('`(${xs.join(", ") || "none"})`'.match(FALLBACK)).toHaveLength(1);
    expect('listPhrase(xs, "none")'.match(FALLBACK)).toBeNull();
  });

  it("no unlisted site", () => {
    expect([...found].filter(([f]) => PENDING[f] === undefined).map(([f, n]) => `${f}: ${n}`)).toEqual([]);
  });

  it("every pending site is still live, at its count (remove the entry once its owner routes it through listPhrase)", () => {
    expect(Object.fromEntries(Object.keys(PENDING).map((f) => [f, found.get(f) ?? 0]))).toEqual(PENDING);
  });

  it("blast.ts names the RIB hosts through the owner, and reads 'no host' when there is none", async () => {
    const { buildAdjacency } = await import("../analysis/blast");
    const a = buildAdjacency().assumptions.find((x) => x.id === "topology-not-forwarding");
    expect(a?.statement).toContain("RIBs were collected for 0 host(s) only (no host).");
  });
});

/* ── the class, read from the syntax tree (QC-R1-2, verifier of phase 3.5) ──
 * The regex above matched one spelling, `.join(", ") ||`, and missed the ternary spelling of the same thing: blast.ts
 * still rendered `alt.length > 0 ? alt.join(", ") : "none"`. The class is a list of names put into prose with a
 * hand-rolled empty case, or a hand-rolled "a, b and c" join — both are listPhrase's job. Read from the TypeScript
 * syntax tree, a SITE is a comma join (`.join(",")` / `.join(", ")`) whose value, through parentheses, `!`, `as` and
 * `satisfies` only, is
 *   (1) the left operand of `||` or `??` — the fallback stands in for the empty list;
 *   (2) one branch of a conditional whose other branch holds no join — the other branch IS the empty wording; or
 *   (3) a `.slice(0, -1)` join — a local copy of listPhrase's "a, b and c".
 * A join nested inside a larger sentence in one branch (`n ? `: ${xs.join(", ")}` : ""`) is a sentence-level choice,
 * not a stand-in for the empty word, and is not a site; nor is a truncating join (`slice(0, 4)` … "and N more").
 * phrases.ts, the owner, is exempt. Sites in files this cluster does not own are ratcheted exactly as above. */
describe("the class through the AST: a comma join with a hand-rolled empty case or 'and', anywhere in src", () => {
  const SRC = join(dirname(fileURLToPath(import.meta.url)), "..");
  const sources = (dir: string): string[] =>
    readdirSync(dir, { withFileTypes: true }).flatMap((e) =>
      e.isDirectory()
        ? /^(_|node_modules$|data$)/.test(e.name)
          ? []
          : sources(join(dir, e.name))
        : /\.tsx?$/.test(e.name) && !/\.test\.tsx?$/.test(e.name) && !/\.d\.ts$/.test(e.name)
          ? [join(dir, e.name)]
          : [],
    );

  type Form = "fallback" | "ternary" | "and-join";
  function sites(fileName: string, text: string): { form: Form; line: number; text: string }[] {
    const sf = ts.createSourceFile(fileName, text, ts.ScriptTarget.Latest, true, fileName.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
    const out: { form: Form; line: number; text: string }[] = [];
    const isCommaJoin = (n: ts.Node): n is ts.CallExpression =>
      ts.isCallExpression(n) &&
      ts.isPropertyAccessExpression(n.expression) &&
      n.expression.name.text === "join" &&
      n.arguments.length === 1 &&
      (ts.isStringLiteral(n.arguments[0]!) || ts.isNoSubstitutionTemplateLiteral(n.arguments[0]!)) &&
      (n.arguments[0] as ts.StringLiteral).text.trim() === ",";
    const holdsJoin = (n: ts.Node): boolean => {
      let hit = false;
      const walk = (m: ts.Node): void => {
        if (hit) return;
        if (ts.isCallExpression(m) && ts.isPropertyAccessExpression(m.expression) && m.expression.name.text === "join") hit = true;
        else ts.forEachChild(m, walk);
      };
      walk(n);
      return hit;
    };
    const isWrapper = (n: ts.Node): boolean =>
      ts.isParenthesizedExpression(n) || ts.isNonNullExpression(n) || ts.isAsExpression(n) || ts.isSatisfiesExpression(n);
    const isMinusOne = (e: ts.Expression): boolean =>
      ts.isPrefixUnaryExpression(e) && e.operator === ts.SyntaxKind.MinusToken && ts.isNumericLiteral(e.operand) && e.operand.text === "1";
    const visit = (n: ts.Node): void => {
      if (isCommaJoin(n)) {
        const at = (form: Form): void => {
          out.push({ form, line: sf.getLineAndCharacterOfPosition(n.getStart(sf)).line + 1, text: n.getText(sf) });
        };
        const recv = (n.expression as ts.PropertyAccessExpression).expression;
        if (
          ts.isCallExpression(recv) &&
          ts.isPropertyAccessExpression(recv.expression) &&
          recv.expression.name.text === "slice" &&
          recv.arguments.length === 2 &&
          isMinusOne(recv.arguments[1]!)
        )
          at("and-join");
        let child: ts.Node = n;
        let p: ts.Node = n.parent;
        while (isWrapper(p)) {
          child = p;
          p = p.parent;
        }
        if (
          ts.isBinaryExpression(p) &&
          p.left === child &&
          (p.operatorToken.kind === ts.SyntaxKind.BarBarToken || p.operatorToken.kind === ts.SyntaxKind.QuestionQuestionToken)
        )
          at("fallback");
        if (ts.isConditionalExpression(p) && (p.whenTrue === child || p.whenFalse === child)) {
          const other = p.whenTrue === child ? p.whenFalse : p.whenTrue;
          if (!holdsJoin(other)) at("ternary");
        }
      }
      ts.forEachChild(n, visit);
    };
    visit(sf);
    return out;
  }

  /* Files this cluster does not own; routed to their owners in the phase-3.5 report. blast.ts (×3) and quality.ts,
     which this cluster owns, now go through listPhrase. */
  const PENDING: Record<string, number> = {
    "app/CoverageBar.tsx": 1,
    "app/StatusBar.tsx": 2,
    "forwarding/ip.ts": 1,
    "panels/ClaimCard.tsx": 1,
    "panels/DevicePane.tsx": 1,
    "panels/EvidencePane.tsx": 1,
    "panels/PathTrace.tsx": 1,
    "panels/PriorityQueue.tsx": 1,
  };
  const found = new Map<string, { form: Form; line: number; text: string }[]>();
  for (const f of sources(SRC)) {
    const rel = f.slice(SRC.length + 1).split("\\").join("/");
    if (rel === "core/phrases.ts") continue;
    const s = sites(rel, readFileSync(f, "utf8"));
    if (s.length > 0) found.set(rel, s);
  }

  it("finds every planted form and none of the planted non-sites (known answers)", () => {
    const forms = (code: string): Form[] => sites("k.ts", code).map((s) => s.form);
    expect(forms('const a = xs.join(", ") || "none";')).toEqual(["fallback"]);
    expect(forms('const a = (xs.join(",")) ?? "none";')).toEqual(["fallback"]);
    expect(forms('const a = xs.length > 0 ? xs.join(", ") : "none";')).toEqual(["ternary"]);
    expect(forms('const a = xs.length === 0 ? "none" : ([...xs].sort().join(", ") as string)!;')).toEqual(["ternary"]);
    expect(forms('const a = `${alt.length > 0 ? alt.join(", ") : "none"}.`;')).toEqual(["ternary"]);
    expect(forms('const a = `${xs.slice(0, -1).join(", ")} and ${xs[xs.length - 1]}`;')).toEqual(["and-join"]);
    // Non-sites: the owner, a sentence-level choice, a truncation, a non-comma join, a join on both branches.
    expect(forms('const a = listPhrase(xs, "none");')).toEqual([]);
    expect(forms('const a = xs.length > 0 ? `: ${xs.join(", ")}` : "";')).toEqual([]);
    expect(forms('const a = n <= 4 ? xs.join(", ") : `${xs.slice(0, 4).join(", ")} and ${n - 4} more`;')).toEqual([]);
    expect(forms('const a = xs.join(" and ") || "none";')).toEqual([]);
  });

  it("scanned the product", () => {
    expect(sources(SRC).length).toBeGreaterThan(50);
  });

  it("no unlisted site", () => {
    expect(
      [...found].filter(([f]) => PENDING[f] === undefined).flatMap(([f, ss]) => ss.map((s) => `${f}:${s.line} ${s.form} ${s.text}`)),
    ).toEqual([]);
  });

  it("every pending site is still live, at its count (remove the entry once its owner routes it through listPhrase)", () => {
    expect(Object.fromEntries(Object.keys(PENDING).map((f) => [f, found.get(f)?.length ?? 0]))).toEqual(PENDING);
  });
});
