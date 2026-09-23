/**
 * acceptance-gates.test.ts — every command docs/acceptance.md names as a criterion's EVIDENCE must
 * be able to return a failing verdict.
 *
 * ── WHY ────────────────────────────────────────────────────────────────────────────────────────
 *
 * This is the same defect shape three times over, found by an external audit on 2026-09-21:
 *
 *   - `review/measure-inp.mjs`'s E3 axis once measured long tasks and never exited on them. Its
 *     header now documents that it "used to be unable to fail".
 *   - `review/audit-e5-coldload.mjs` (then `_audit_e5_coldload.mjs`), cited as E5's evidence, printed its numbers
 *     and ended on `writeFileSync`. A run reporting a 956 ms blocking frame and a 1024 ms keystroke
 *     exited 0, exactly like a clean one.
 *   - `review/audit-e5-sweep.mjs` (then `_audit_e5_sweep.mjs`) printed "7 of 16 actions produced an animation frame over
 *     200 ms" and exited 0.
 *
 * Each was individually fixed, and fixing them individually is not a fix: the shape recurs because
 * nothing checks for it. A probe becomes a GATE the moment a document cites it as evidence, and a
 * gate whose success path is the only path it has is decoration — someone runs it in a release
 * check, sees exit 0, and records the criterion green off an instrument that cannot say otherwise.
 *
 * ── WHAT IS CHECKED, AND WHAT IS NOT ───────────────────────────────────────────────────────────
 *
 * The subjects are taken from acceptance.md itself, not from a hand-maintained list here — a guard
 * scoped to a list of names stands in for the class it means and drifts away from it the first time
 * someone adds a criterion. Each cited script must:
 *
 *   1. exist, and not be gitignored (a file that exists only on the workstation that wrote it is
 *      not evidence anyone else can re-run);
 *   2. state a verdict IN CODE (a `verdict` binding or a printed `verdict:` line, comments
 *      stripped), so the reader is told the answer rather than left to compute it from the numbers;
 *   3. carry a non-zero `process.exit(N)` or `process.exitCode = N` OUTSIDE its usage-error branch,
 *      so the answer reaches a caller that is not a human reading stdout.
 *
 * This is STRUCTURAL, and it is stated honestly: it proves an exit path exists, not that the
 * threshold behind it is the right one, and not that the failing branch has ever been executed.
 * Those are different questions and this test does not answer them. It closes the one hole that
 * recurred: an instrument with no failing branch at all.
 */
import { execFileSync } from "node:child_process";
import { existsSync, readFileSync, readdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
const ACCEPTANCE = join(ROOT, "docs", "acceptance.md");

/** Every `node review/<something>.mjs` acceptance.md cites, de-duplicated, in document order. */
function citedEvidenceScripts(): string[] {
  const md = readFileSync(ACCEPTANCE, "utf8");
  const out: string[] = [];
  for (const m of md.matchAll(/node\s+(review\/[A-Za-z0-9_.\-/]+\.mjs)/g)) {
    const p = m[1]!;
    if (!out.includes(p)) out.push(p);
  }
  return out;
}

describe("a criterion's named evidence command can return a failing verdict", () => {
  const scripts = citedEvidenceScripts();

  it("acceptance.md still names evidence commands at all", () => {
    /* If this ever reads zero the test above would vacuously pass — the "green tests that pin
       nothing" trap. The denominator is asserted so the guard cannot quietly stop covering
       anything. */
    expect(scripts.length).toBeGreaterThanOrEqual(3);
  });

  it.each(citedEvidenceScripts())("%s exists, is tracked, states a verdict, and exits non-zero on it", (rel) => {
    const abs = join(ROOT, rel);
    expect(existsSync(abs), `${rel} is cited as acceptance evidence but does not exist`).toBe(true);
    /* EXISTS HERE is not EXISTS IN A CLONE. Two cited E5 scripts were `review/_audit_*.mjs`, matched
       by the `.gitignore` rule `review/_*`: present on the workstation that wrote them, absent from
       every fresh clone, so this test was green only where it was least needed. */
    if (GIT_CHECKOUT) {
      expect(isGitIgnored(rel), `${rel} is cited as acceptance evidence but .gitignore excludes it — a clone will not have it`).toBe(false);
    }
    const code = stripComments(readFileSync(abs, "utf8"));
    /* A verdict the CODE states — a `verdict` binding or a printed `verdict:` line — not the word in
       a comment or in an unrelated message. capture.mjs once satisfied the old `\bverdict\b` check
       with "no forwarding verdict rendered", a message about the product's path verdict. */
    expect(code, `${rel} never states a verdict — a reader is left to compute the answer from the numbers`).toMatch(
      /\b(?:const|let|var)\s+verdict\b|\.verdict\s*=|\bverdict:\s/,
    );
    const exits = nonZeroExitsOutsideUsage(code);
    expect(
      exits.length,
      `${rel} is cited as evidence for an acceptance criterion but has no non-zero exit outside its usage branch, so it cannot go red however bad the measurement is`,
    ).toBeGreaterThan(0);
  });
});

/** Comments removed, so prose cannot satisfy a structural check. Strings are kept: messages are code. */
function stripComments(src: string): string {
  return src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:"'`\\])\/\/[^\n]*/g, "$1");
}

/**
 * Every `process.exit(N)` / `process.exitCode = N` that can signal failure: not a literal 0, and not
 * inside the usage-error branch (an exit within three lines of a `usage` message). The old check
 * accepted ANY `process.exit(` — and in capture.mjs the only one was `process.exit(2)` after the
 * usage line, while the real verdict path used `process.exitCode = 3`, which it could not see.
 */
function nonZeroExitsOutsideUsage(code: string): string[] {
  const lines = code.split("\n");
  const out: string[] = [];
  lines.forEach((line, i) => {
    const m = /process\.exit\s*\(\s*([^)]*)\)|process\.exitCode\s*=\s*([^;\n]+)/.exec(line);
    if (m === null) return;
    const arg = (m[1] ?? m[2] ?? "").trim();
    if (arg === "0" || arg === "") return;
    const context = lines.slice(Math.max(0, i - 3), i + 1).join("\n");
    if (/\busage\b/i.test(context)) return;
    out.push(line.trim());
  });
  return out;
}

const GIT_CHECKOUT = (() => {
  try {
    execFileSync("git", ["rev-parse", "--is-inside-work-tree"], { cwd: ROOT, stdio: "pipe" });
    return true;
  } catch {
    return false;
  }
})();

function isGitIgnored(rel: string): boolean {
  try {
    execFileSync("git", ["check-ignore", "-q", "--no-index", rel], { cwd: ROOT, stdio: "pipe" });
    return true; // exit 0: a rule matches
  } catch {
    return false; // exit 1: not ignored
  }
}

/**
 * A HARNESS'S NAMED PIN EXISTS. An evidence harness that says "pinned by <test>" is telling its
 * reader where the rule it depends on is enforced. `review/measure-inp.mjs` cited
 * `src/fabric3d/measure-inp.harness.test.ts` twice (acceptance report, E harness item 12b,
 * 2026-09-23); no such file ever existed — the pin lived in `Fabric3D.test.tsx` — so a reader
 * following the citation found nothing and could fairly conclude the rule was unpinned. The class,
 * not the instance: every tracked `review/*.mjs` (the underscore prefix is gitignored scratch) is
 * read, and every `src/<dir>/<name>.test.ts(x)` path it names must exist.
 */
describe("every test a tracked review harness cites as its pin exists", () => {
  const REVIEW = join(ROOT, "review");
  const harnesses = readdirSync(REVIEW).filter((n) => n.endsWith(".mjs") && !n.startsWith("_"));
  const cited = harnesses.flatMap((n) =>
    [...readFileSync(join(REVIEW, n), "utf8").matchAll(/\bsrc\/[A-Za-z0-9_./-]+\.test\.tsx?\b/g)].map((m) => ({ harness: n, test: m[0] })),
  );

  it("the harnesses do cite tests (a scan that finds none pins nothing)", () => {
    expect(harnesses.length).toBeGreaterThanOrEqual(5);
    expect(cited.length).toBeGreaterThanOrEqual(5);
  });

  it("no cited test is missing", () => {
    const missing = cited.filter((c) => !existsSync(join(ROOT, c.test))).map((c) => `${c.harness} cites ${c.test}`);
    expect([...new Set(missing)]).toEqual([]);
  });
});

describe("the exit-path check can fail — its red branch, executed", () => {
  it("rejects a script whose only non-zero exit is the usage branch", () => {
    const usageOnly = [
      "const verdict = x ? 'PASS' : 'FAIL';",
      "if (mode === 'a') run();",
      "else {",
      "  console.error('usage: node thing.mjs a');",
      "  process.exit(2);",
      "}",
    ].join("\n");
    expect(nonZeroExitsOutsideUsage(usageOnly)).toEqual([]);
  });

  it("rejects a script that only ever exits 0", () => {
    expect(nonZeroExitsOutsideUsage("process.exit(0);\nprocess.exitCode = 0;")).toEqual([]);
  });

  it("accepts a verdict path that sets exitCode rather than calling exit", () => {
    expect(nonZeroExitsOutsideUsage("if (verdict !== 'PASS') process.exitCode = 3;")).toHaveLength(1);
  });

  it("the ignore check runs, or the run fails until someone acknowledges that it could not", () => {
    /* This used to end `else expect(GIT_CHECKOUT).toBe(false)`: outside a checkout it asserted the
       environment constant it had just branched on, so it could never fail and the tracked-file
       check in the table above was skipped without a trace. Outside a checkout it is now RED unless
       the run says, explicitly, that it knows the tracking check did not run. */
    if (!GIT_CHECKOUT) {
      expect(
        process.env.ATLAS_SCOPE_NO_GIT,
        "not inside a Git checkout, so no cited evidence script was checked against .gitignore; " +
          "set ATLAS_SCOPE_NO_GIT=1 to acknowledge that this run did not establish it",
      ).toBe("1");
      return;
    }
    // Both directions, so the probe is shown to discriminate rather than to answer one way always.
    expect(isGitIgnored("review/_definitely_scratch.mjs")).toBe(true);
    expect(isGitIgnored("review/capture.mjs")).toBe(false);
  });
});
