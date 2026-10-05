/**
 * own.ts — THE ONE OWNER of a dictionary keyed by names the SNAPSHOT supplies, and of every read of a dictionary by
 * a key that is not a literal.
 *
 * The compiled documents are plain JSON objects, and every name they are keyed by — a host, an ACL, an object
 * group, a severity, a producer field — is untrusted text (a file the reader opened, or one AssessHub served).
 * `dict[name]` answers a name the dictionary does not hold from the PROTOTYPE CHAIN: on a dataset whose hosts
 * were named "toString", "constructor" or "__proto__" the application read a function, the Object constructor or
 * Object.prototype where it should have read "not collected", and so threw (`routes is not iterable`), counted a
 * host with no interface table as collected, or showed "0" ACL lines for a host whose ACLs were never collected —
 * absence rendered as presence (2026-09-30 refuter, after the compiler's own rule, `own` in
 * tools/lib/compile-model.mjs, made compiling such names safe).
 *
 * THE STRUCTURAL GUARANTEE (2026-09-30 refuter, round 3: a guard that trusts declared types missed seven read
 * shapes — `Reflect.get`, a generic helper over `Record<string, T>`, plain assignment to a wider dictionary type or to
 * `any`, …). Every name-keyed dictionary the compiled set carries has NO PROTOTYPE once the set is installed:
 * `core/dataset.ts`, the one door both the bundled sample and a runtime-opened snapshot pass through, hands the
 * selected set to `withoutPrototypes` before any module reads it. A dictionary with no prototype has no inherited
 * member to answer with, so EVERY read shape — a bracket, `?.[]`, `in`, `Reflect.get`, a helper, a cast, `any` —
 * sees only the dictionary's own entries. Which dictionaries those are is not a list kept by hand:
 * `COMPILED_NAME_KEYED_PATHS` must equal, exactly, the NameKeyed paths `own-read.guard.test.ts` derives by walking
 * `CompiledDataset` with the TypeScript checker, so a dictionary added to the documents fails there until it is
 * here. The dictionaries the application builds itself are made the same way, by `nameKeyed`.
 *
 * A COPY IS AN ORDINARY OBJECT AGAIN. Spread, `Object.assign({}, …)`, `Object.fromEntries(Object.entries(…))`,
 * `structuredClone` and a JSON round trip (`JSON.parse(JSON.stringify(…))`) all rebuild the dictionary on
 * Object.prototype, where no run-time structure can follow it — the one read shape this module does not make safe
 * by structure. The guard answers it instead (own-read.guard.test.ts): a JSON round trip of a compiled dictionary is
 * forbidden outright (kind "copy"), and a read of any copy by a non-literal key is flagged where it happens (the
 * copy keeps the brand, is a string-indexed dictionary, or is `any`: kinds "index", "wide-index", "any-index").
 *
 * `own` / `holds` remain the documented reader: they state the intent ("the member this dictionary holds, or
 * none"), work on a dictionary that did not come through the door (a constant table, a test's fixture), and the
 * guard requires every read of a dictionary by a non-literal key — a compiled one or a constant table indexed by a
 * snapshot value (a category, a band, a kind) — to go through them.
 *
 * Why not Maps built at load: the compiled documents are the compiler's byte-exact output and are read as
 * documents too — cited by path (`resolveCite`), shown raw (JsonView, the Inspector), compared binding by binding
 * (dataset/slot.ts) — and `Fabric` is one type shared with the compiler (tools/lib/compile-model.d.mts). A dictionary
 * without a prototype serialises, iterates and cites exactly as before; a Map would fork the contract.
 */
import type { NameKeyed } from "./types";

/** The member `name` of a name-keyed dictionary, or `undefined` when the dictionary does not hold it as its own. */
export function own<T>(dict: Readonly<Record<string, T>> | null | undefined, name: string): T | undefined {
  return dict !== null && dict !== undefined && Object.hasOwn(dict, name) ? dict[name] : undefined;
}

/** Whether a name-keyed dictionary holds `name` as its own member (never through its prototype). */
export function holds(dict: Readonly<Record<string, unknown>> | null | undefined, name: string): boolean {
  return dict !== null && dict !== undefined && Object.hasOwn(dict, name);
}

/**
 * A name-keyed dictionary the application builds: no prototype, each entry DEFINED (so a name "__proto__" is an
 * ordinary member, never a prototype assignment). The only way `src/` makes a `NameKeyed` value (the guard's kind
 * "construct").
 */
export function nameKeyed<T>(entries: Iterable<readonly [string, T]> = []): NameKeyed<T> {
  const out = Object.create(null) as NameKeyed<T>;
  for (const [name, value] of entries) Object.defineProperty(out, name, { value, enumerable: true, writable: true, configurable: true });
  return out;
}

/**
 * Where the compiled set holds a dictionary keyed by names the snapshot supplies. A step is a member name, `*` (every
 * value of the dictionary reached so far) or `[]` (every element of the list reached so far).
 * DERIVED, not kept: own-read.guard.test.ts requires this list to equal, exactly, the NameKeyed paths it reaches by
 * walking `CompiledDataset` with the type checker — in both directions.
 */
export const COMPILED_NAME_KEYED_PATHS: readonly string[] = Object.freeze([
  "fabric.routes",
  "fabric.acls",
  "fabric.acls.*",
  "fabric.objectGroups",
  "fabric.objectGroups.*",
  "fabric.interfaces",
  "fabric.coverage.aclSummary",
  "fabric.coverage.unreadableRouteEntries",
  "fabric.evidenceRecords[].value",
  "fabric.evidenceRecords[].cut",
  "aclBindings.hosts",
  "ribEvidence.hosts",
  "producerEmission.meta.aclLineFields",
  "producerEmission.meta.deviceHealthFields",
  "producerEmission.aclLineAbsent",
  "producerEmission.deviceAbsent",
]);

const isDictionary = (v: unknown): v is object => v !== null && typeof v === "object" && !Array.isArray(v);

/** The steps of a path: "fabric.evidenceRecords[].cut" -> ["fabric", "evidenceRecords", "[]", "cut"]. */
const stepsOf = (path: string): string[] => path.split(".").flatMap((s) => (s.endsWith("[]") ? [s.slice(0, -2), "[]"] : [s]));

/**
 * Every value `steps` reaches from `from` (own members only; a value of the wrong shape reaches nothing). Appended
 * ELEMENT BY ELEMENT: `next.push(...list)` passes every element as a call argument, and past ~130,000 evidence
 * records that overflowed the engine's argument limit, so the install door threw `RangeError: Maximum call stack size
 * exceeded` on a large fleet (2026-10-01 refuter; own.scale.test.ts runs 200,000).
 */
function reach(from: unknown, steps: readonly string[]): unknown[] {
  let here: unknown[] = [from];
  for (const step of steps) {
    const next: unknown[] = [];
    for (const v of here) {
      if (step === "[]") {
        if (Array.isArray(v)) for (const x of v as unknown[]) next.push(x);
      } else if (step === "*") {
        if (isDictionary(v)) for (const x of Object.values(v)) next.push(x);
      } else if (isDictionary(v) && Object.hasOwn(v, step)) {
        next.push((v as Record<string, unknown>)[step]);
      }
    }
    here = next;
  }
  return here;
}

/**
 * Remove the prototype of every name-keyed dictionary in a compiled set, in place, and return the set. Called ONCE,
 * by `core/dataset.ts`, on the set the page will show. Idempotent. A path whose value is not a dictionary (a scalar
 * evidence record's `value`, a document a malformed restore lacks) is left alone — the reads of those are the
 * readers' own business, and the coherence check (dataset/slot.ts) has already refused an incomplete set.
 */
export function withoutPrototypes<S extends object>(set: S): S {
  for (const path of COMPILED_NAME_KEYED_PATHS) {
    for (const dict of reach(set, stepsOf(path))) {
      if (isDictionary(dict) && Object.getPrototypeOf(dict) !== null) Object.setPrototypeOf(dict, null);
    }
  }
  return set;
}
