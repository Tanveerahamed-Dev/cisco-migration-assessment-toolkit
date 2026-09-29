/**
 * golden-expectations.test.ts — every golden value is READ by some test.
 *
 * A value stored in ./golden-expectations.ts that no test reads is a number that can go stale unnoticed on
 * the next re-derivation: the file says it was measured, and nothing measures it (2026-09-28 verifier, D3:
 * `depthRatchet.decidedOutcomes`, `refusals` and `counterexamplesFound` were stored and read by nothing).
 * This walks the WHOLE object — every key at every depth of every plain object, not a list of the keys
 * someone remembered — and requires each key's name to occur as an identifier in the test sources that
 * read the golden tier (the forwarding tests and flow-terminal.counterfactual).
 *
 * What it does not do: a key whose name is a common word ("flow", "hops") is satisfied by any use of that
 * word, so this proves an unread DISTINCTIVE key cannot hide; it does not prove each common-word key is
 * read at the site it was written for. The golden blocks' own assertions do that.
 */
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { GOLDEN_FORWARDING } from "./golden-expectations";

/** A Flow is one value (a question), read whole; its fields are not separate golden facts. */
const isFlow = (v: unknown): boolean => v !== null && typeof v === "object" && "srcIp" in v && "dstIp" in v && "protocol" in v;

/** Every key path of every plain (non-array, non-Flow) object in the value. */
function keyPaths(v: unknown, prefix: string[] = []): string[][] {
  if (v === null || typeof v !== "object" || Array.isArray(v) || isFlow(v)) return [];
  return Object.entries(v as Record<string, unknown>).flatMap(([k, child]) => [[...prefix, k], ...keyPaths(child, [...prefix, k])]);
}

const READERS = [
  ...readdirSync(import.meta.dirname)
    .filter((n) => /\.test\.tsx?$/.test(n) && n !== "golden-expectations.test.ts")
    .map((n) => join(import.meta.dirname, n)),
  join(import.meta.dirname, "..", "fabric3d", "flow-terminal.counterfactual.test.ts"),
];

describe("every golden value is read by a test", () => {
  it("each key of GOLDEN_FORWARDING, at every depth, is named in a test that reads the golden tier", () => {
    /* Code only: a name in a comment or a test title is not a read. Block comments, line comments and
       string-quoted titles are blanked (a rough strip is enough — it can only make a key look UNREAD). */
    const code = READERS.map((f) =>
      readFileSync(f, "utf8")
        .replace(/\/\*[\s\S]*?\*\//g, " ")
        .replace(/(^|[^:"'`])\/\/[^\n]*/g, "$1 ")
        .replace(/"(?:[^"\\\n]|\\.)*"/g, '""'),
    );
    const paths = keyPaths(GOLDEN_FORWARDING);
    expect(paths.length, "the golden object has keys").toBeGreaterThan(20);
    // Numeric keys (a histogram's depths) are data, not names.
    /* Read as a property (`.name`) or destructured (`{ a, name } = …`). An object read WHOLE (`.name` not
       followed by a further `.x` / `[i]`, as in `toEqual(G.neverADefinitePermit)`) reads all its children;
       one only ever dereferenced (`G.depthRatchet.traces`) must have each child read by name. An alias
       (`const C1 = G.core1Acls;`) is not a whole read: its children are read through the alias. */
    const asProperty = (name: string) => new RegExp(`\\.${name}(?![\\w$])`);
    const destructured = (name: string) => new RegExp(`\\{[^{}=]*(?<![\\w$])${name}(?![\\w$])[^{}=]*\\}\\s*=`);
    const whole = (name: string) => new RegExp(`\\.${name}(?![\\w$.\\[!;])`);
    const read = (name: string) => code.some((s) => asProperty(name).test(s) || destructured(name).test(s));
    const readWhole = (name: string) => code.some((s) => whole(name).test(s));
    const unread = paths
      .filter((p) => !/^\d+$/.test(p.at(-1)!))
      .filter((p) => !p.slice(0, -1).some((ancestor) => readWhole(ancestor)))
      .filter((p) => !read(p.at(-1)!))
      .map((p) => p.join("."));
    expect(unread, "golden values no test reads: assert them, or delete them").toEqual([]);
  });
});
