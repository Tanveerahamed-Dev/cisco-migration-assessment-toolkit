/**
 * mock-classification.test.ts — docs/acceptance.md's F2 row must declare EVERY test file that
 * replaces a module, not a hand-picked subset.
 *
 * ── WHY ────────────────────────────────────────────────────────────────────────────────────────
 *
 * F2 asks for tests that exercise the real compiled data and the real renderer. A test that swaps a
 * module out (`vi.mock` / `vi.doMock`) is testing something below or beside the real thing, and
 * F2's evidence has to say so. The row used to NAME such files by hand, and an independent audit
 * (2026-09-22) found the list incomplete: `src/app/reaim-tab-and-restore.test.tsx` mocks
 * `../fabric3d/Fabric3D` and was not named. The audit's own grep (`vi\.mock\(`) also missed
 * `src/forwarding/bindings-trust.test.ts`, which uses `vi.doMock`. Both are the same defect shape:
 * a list of names standing in for the class it means.
 *
 * So the class is derived here from the source, and the doc's declaration must equal it in both
 * directions: a new mocking test that is not declared is red, and a declared file that no longer
 * mocks anything is red (a stale classification is a false statement about the evidence).
 *
 * What this does NOT decide: whether a mocking test is hollow. Several are not (their assertions
 * are about the store or panels, or they inject one altered byte into the REAL sidecar to execute a
 * fail-closed branch). The declaration only makes the mocking visible to whoever reads F2.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const SRC = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const ROOT = resolve(SRC, "..");

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const p = resolve(dir, name);
    return statSync(p).isDirectory() ? walk(p) : [p];
  });
}

/** Block comments and whole-line `//` comments removed, so prose ABOUT mocking is not a mock. */
const stripComments = (text: string): string =>
  text.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");

// Any module-replacement call vitest offers: vi.mock, vi.doMock (and their `unmock` siblings are
// not replacements). Matched on the call shape, not on a list of target modules.
const MODULE_MOCK = /\bvi\s*\.\s*(?:mock|doMock)\s*\(/;

const mockingTestFiles = (): string[] =>
  walk(SRC)
    .filter((p) => /\.test\.tsx?$/.test(p))
    .filter((p) => MODULE_MOCK.test(stripComments(readFileSync(p, "utf8"))))
    .map((p) => relative(ROOT, p).split("\\").join("/"))
    .sort();

const DECLARATION_MARKER = "Module-mocking test files";

function declaredFiles(): string[] {
  const doc = readFileSync(resolve(ROOT, "docs/acceptance.md"), "utf8");
  const f2 = doc.split(/\r?\n/).find((line) => line.startsWith("| F2 |"));
  if (f2 === undefined) throw new Error("docs/acceptance.md has no F2 row");
  const at = f2.indexOf(DECLARATION_MARKER);
  if (at < 0) throw new Error(`the F2 row carries no "${DECLARATION_MARKER}" declaration`);
  // The declaration runs from the marker to the end of its sentence ("." followed by a space/pipe).
  const tail = f2.slice(at);
  const end = tail.search(/\.\s+(?:\*\*|[A-Z|])/);
  const sentence = end < 0 ? tail : tail.slice(0, end);
  // The members follow the parenthetical that names this gate, so the gate's own path is not read
  // as a member: "Module-mocking test files (… this test …): `a`, `b`."
  const colon = sentence.indexOf("):");
  if (colon < 0) throw new Error(`the "${DECLARATION_MARKER}" declaration has no "(…):" member list`);
  const clause = sentence.slice(colon + 2);
  return [...clause.matchAll(/`(src\/[^`]+\.test\.tsx?)`/g)].flatMap((m) => (m[1] === undefined ? [] : [m[1]])).sort();
}

describe("F2 declares every module-mocking test file (derived from source, not a list)", () => {
  it("finds the class at all (positive control — an empty discovery would pass vacuously)", () => {
    expect(mockingTestFiles().length).toBeGreaterThan(0);
  });

  it("does not count prose about mocking as a mock", () => {
    // Built by concatenation so THIS file's source never contains the call shape it looks for.
    const call = (name: string) => "vi" + "." + name + "(";
    expect(MODULE_MOCK.test(stripComments(`/* ${call("mock")}"x") */\n// ${call("doMock")}"y")\nconst a = 1;`))).toBe(false);
    expect(MODULE_MOCK.test(stripComments(`${call("doMock")}"./acl-bindings.json", () => ({}));`))).toBe(true);
  });

  it("every mocking test file is declared in F2, and every declared file still mocks", () => {
    expect(declaredFiles()).toEqual(mockingTestFiles());
  });
});
