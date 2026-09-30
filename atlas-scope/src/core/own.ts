/**
 * own.ts — THE ONE READ of a dictionary keyed by names the SNAPSHOT supplies.
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
 * So a read by a runtime name goes through `own`: only an OWN member answers, and a name the dictionary does not
 * hold reads as `undefined` — "not collected / not observed", never an empty-but-present record and never an
 * inherited member. Such dictionaries are typed `NameKeyed<T>` (core/types.ts), and
 * `src/core/own-read.guard.test.ts` fails when a module other than this one indexes one by bracket, tests
 * membership with `in`, or destructures it by a computed key.
 *
 * Why an accessor and not Maps built at load: the compiled documents are the compiler's byte-exact output and
 * are read as documents too — cited by path (`resolveCite`), shown raw (JsonView, the Inspector), compared
 * binding by binding (dataset/slot.ts) — and `Fabric` is one type shared with the compiler
 * (tools/lib/compile-model.d.mts). Converting them would fork that contract into two shapes and still leave the
 * path walkers needing this rule; one accessor keeps the documents as they are and makes the read safe.
 */

/** The member `name` of a name-keyed dictionary, or `undefined` when the dictionary does not hold it as its own. */
export function own<T>(dict: Readonly<Record<string, T>> | null | undefined, name: string): T | undefined {
  return dict !== null && dict !== undefined && Object.hasOwn(dict, name) ? dict[name] : undefined;
}

/** Whether a name-keyed dictionary holds `name` as its own member (never through its prototype). */
export function holds(dict: Readonly<Record<string, unknown>> | null | undefined, name: string): boolean {
  return dict !== null && dict !== undefined && Object.hasOwn(dict, name);
}
