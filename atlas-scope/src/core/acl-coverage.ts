/**
 * acl-coverage.ts — the honest denominator for "ACL lines this product cannot decide".
 *
 * WHY THIS MODULE EXISTS. Every coverage surface used to read one number,
 * `fabric.coverage.aclLinesUnevaluable`, which is the count of lines carrying the producer's
 * `unevaluable` boolean. That number answered a question nobody asked. Three different sets exist
 * and they are not nested:
 *
 *   A. PRODUCER-FLAGGED    `AclLine.unevaluable` — the collector's parser said it could not model
 *                          the line. On the shipped snapshot: core1 MGMT_IN[0], an object-group
 *                          reference. The ENGINE resolves object groups and decides that line
 *                          perfectly well, so this flag is an upper bound on the producer, not on
 *                          the model that renders the verdicts.
 *   B. SNAPSHOT-INDETERMINATE  the snapshot's own `acl_line_reachability` rows whose verdict is
 *                          `indeterminate` (compiled into `fabric.aclFindings`). A separate
 *                          analysis, run by the producer, over the same lines. On the shipped
 *                          snapshot: five rows, none of them MGMT_IN[0].
 *   C. ENGINE-REFUSED      lines for which THIS engine's `lineEvaluability()` returns
 *                          `evaluable: false`. This is the set that actually bounds a rendered
 *                          verdict: a trace stepping over one of these is reported indeterminate.
 *                          It cannot be computed by the compiler, because the rule lives in the
 *                          engine. On the shipped snapshot: three lines, two of which A never
 *                          flagged.
 *
 * Rendering A alone understated the undecidable surface by 6x AND named a member disjoint from the
 * lines the engine really refuses — so a trace could say "PROTECT_SERVERS line 2 cannot be
 * evaluated" directly above a scope block asserting exactly one unmodellable line, which was a
 * different line. That is the repository's named defect shape: a guard scoped to a hand-maintained
 * subset standing in for the class it means.
 *
 * WHAT IS RENDERED IS THE UNION. Every coverage surface states `undecidable.count` — the size of
 * A ∪ B ∪ C — and can name its members with the reason each one is in it. The union is the only
 * count that is safe to put next to the word "cannot": it is >= C by construction, so the sentence
 * can never be narrower than the set of lines that actually poison a verdict.
 *
 * Nothing here is cached against the compiled `coverage.aclLinesUnevaluable`: that field is still
 * reported, but as ONE contributing figure with its own name, never as the headline.
 */
import { fabric } from "./data";
import { own } from "./own";
import type { AclLine, Cite, Fabric } from "./types";
import { lineEvaluability } from "../forwarding/engine";

/** Why a line is in the undecidable set. A line can carry more than one. */
export type UndecidableSource = "producer" | "snapshot" | "engine";

export interface UndecidableAclLine {
  host: string;
  acl: string;
  index: number;
  raw: string | null;
  cite: Cite;
  /** Every source that puts this line in the set, in stable order. */
  sources: UndecidableSource[];
  /** One clause per source, in the same order — why that source cannot decide the line. */
  reasons: string[];
  /** Short `core1 PROTECT_SERVERS[2]` label, for a member list. */
  label: string;
}

export interface AclUndecidability {
  /** Every collected ACL line, across every host. */
  total: number;
  /** A ∪ B ∪ C — what every surface must state. */
  count: number;
  members: UndecidableAclLine[];
  /** The three contributing sets, by size, so a reader can see where the union came from. */
  bySource: Readonly<Record<UndecidableSource, number>>;
  /** Members of C. Rendered counts must never fall below this — asserted in the tests. */
  engineRefused: UndecidableAclLine[];
}

const keyOf = (host: string, acl: string, index: number): string => JSON.stringify([host, acl, index]);

const SOURCE_ORDER: readonly UndecidableSource[] = ["engine", "producer", "snapshot"];

/**
 * Every ACL line in the fabric, with the host and list name it came from. Exported because more
 * than one surface needs to walk the same flattened list, and two walks that drift are how a
 * denominator and its member list stop describing each other.
 */
export function allAclLines(f: Fabric = fabric): { host: string; acl: string; line: AclLine }[] {
  const out: { host: string; acl: string; line: AclLine }[] = [];
  for (const host of Object.keys(f.acls).sort()) {
    const named = own(f.acls, host);
    if (named === undefined) continue;
    for (const acl of Object.keys(named).sort()) {
      for (const line of own(named, acl) ?? []) out.push({ host, acl, line });
    }
  }
  return out;
}

/**
 * The union of the three undecidability sets, with members named.
 *
 * Deliberately NOT memoised against a module-level singleton: it is cheap (a dozen lines on this
 * snapshot, linear in the corpus) and a stale memo of a coverage figure is precisely the failure
 * this module exists to remove.
 */
export function aclUndecidability(f: Fabric = fabric): AclUndecidability {
  const lines = allAclLines(f);
  const byKey = new Map<string, UndecidableAclLine>();

  const add = (
    host: string,
    acl: string,
    line: AclLine,
    source: UndecidableSource,
    reason: string,
  ): void => {
    /* JSON-encoded tuple rather than a delimiter-joined string: a host or list name containing
       the delimiter would otherwise collide two distinct lines into one member. */
    const key = keyOf(host, acl, line.index);
    const existing = byKey.get(key);
    if (existing === undefined) {
      byKey.set(key, {
        host,
        acl,
        index: line.index,
        raw: line.raw,
        cite: line.cite,
        sources: [source],
        reasons: [reason],
        label: `${host} ${acl}[${line.index}]`,
      });
      return;
    }
    if (existing.sources.includes(source)) return;
    existing.sources.push(source);
    existing.reasons.push(reason);
  };

  /* C first, so the set that actually bounds a verdict leads every member's reason list. */
  for (const { host, acl, line } of lines) {
    const ev = lineEvaluability(line);
    if (!ev.evaluable) {
      add(
        host,
        acl,
        line,
        "engine",
        `this model refuses to evaluate it — ${ev.reason ?? "no reason recorded"}`,
      );
    }
  }

  /* A — the producer's own flag. */
  for (const { host, acl, line } of lines) {
    if (!line.unevaluable) continue;
    const why =
      line.unmodeledQualifiers.length > 0
        ? `the collector's parser could not model it (${line.unmodeledQualifiers.join(", ")})`
        : "the collector's parser could not model it";
    add(host, acl, line, "producer", why);
  }

  /* B — the snapshot's own reachability analysis. Matched back onto the parsed lines by
     host/list/index, so a row naming a line we do not hold cannot invent a member. */
  const lineAt = new Map(lines.map((l) => [keyOf(l.host, l.acl, l.line.index), l]));
  for (const finding of f.aclFindings) {
    if ((finding.verdict ?? "").toLowerCase() !== "indeterminate") continue;
    if (finding.host === null || finding.acl === null || finding.lineIndex === null) continue;
    const found = lineAt.get(keyOf(finding.host, finding.acl, finding.lineIndex));
    if (found === undefined) continue;
    add(
      found.host,
      found.acl,
      found.line,
      "snapshot",
      `the snapshot's own reachability analysis returned indeterminate — ${finding.detail ?? "no detail recorded"}`,
    );
  }

  const members = [...byKey.values()].sort(
    (x, y) => x.host.localeCompare(y.host) || x.acl.localeCompare(y.acl) || x.index - y.index,
  );
  for (const m of members) {
    /* Stable source order regardless of insertion, with reasons carried alongside. */
    const paired = m.sources.map((s, i) => ({ s, r: m.reasons[i] ?? "" }));
    paired.sort((p, q) => SOURCE_ORDER.indexOf(p.s) - SOURCE_ORDER.indexOf(q.s));
    m.sources = paired.map((p) => p.s);
    m.reasons = paired.map((p) => p.r);
  }

  const bySource = {
    producer: members.filter((m) => m.sources.includes("producer")).length,
    snapshot: members.filter((m) => m.sources.includes("snapshot")).length,
    engine: members.filter((m) => m.sources.includes("engine")).length,
  } as const;

  return {
    total: lines.length,
    count: members.length,
    members,
    bySource,
    engineRefused: members.filter((m) => m.sources.includes("engine")),
  };
}

/**
 * The one sentence every surface states about the ACL denominator. Kept here rather than written
 * out at five call sites, so the five cannot drift apart again — the drift is the defect.
 */
export function undecidableAclSentence(u: AclUndecidability = aclUndecidability()): string {
  if (u.total === 0) return "No access-list line was collected, so no ACL verdict is modelled at all.";
  if (u.count === 0) {
    return `${u.total} collected access-list lines, none of which this model, the collector's parser or the snapshot's own reachability analysis reports as undecidable.`;
  }
  return (
    `${u.count} of ${u.total} collected access-list lines cannot be decided: ` +
    `${u.bySource.engine} this model refuses to evaluate, ` +
    `${u.bySource.producer} the collector's parser could not model, ` +
    `${u.bySource.snapshot} the snapshot's own reachability analysis returned indeterminate. ` +
    `Those sets overlap only partly, so the union is the honest figure. ` +
    `A verdict that steps over any of them is indeterminate — not a permit.`
  );
}

/** `core1 MGMT_IN[0], core1 PROTECT_SERVERS[2]` — the members, for a one-line summary. */
export const undecidableLabels = (u: AclUndecidability = aclUndecidability()): string =>
  u.members.map((m) => m.label).join(", ");
