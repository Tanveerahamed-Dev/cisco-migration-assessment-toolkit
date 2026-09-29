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
import { describe, expect, it } from "vitest";
import { fabric } from "./data";
import { describeGolden } from "../test-support/golden-sample";

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

describe("the compiled ACL model preserves the producer's own verdicts", () => {
  it("carries at least one line, so this suite cannot pass on an empty set", () => {
    expect(allLines().length).toBeGreaterThan(5);
  });

  it("keeps the producer's `unevaluable` verdict instead of making the engine re-derive it", () => {
    // core1.MGMT_IN[0] — "permit tcp object-group MGMT_HOSTS any eq 22"
    const line = fabric.acls["core1"]?.["MGMT_IN"]?.[0];
    expect(line, "core1.MGMT_IN[0] should exist in the compiled model").toBeDefined();
    expect(line!.unevaluable, "the producer marked this line unevaluable").toBe(true);
  });

  it("keeps which qualifier defeated the model, not just that one did", () => {
    // core1.PROTECT_SERVERS[2] — "permit icmp any 10.0.30.0 0.0.0.255 echo-reply"
    const line = fabric.acls["core1"]?.["PROTECT_SERVERS"]?.[2];
    expect(line).toBeDefined();
    expect(line!.unmodeledQualifiers).toContain("icmp_type");
    expect(line!.icmpType).toBe("echo-reply");
  });

  it("keeps `established`, which a forward-only model cannot decide", () => {
    // core1.INET_RETURN[0] — "permit tcp any any established"
    const line = fabric.acls["core1"]?.["INET_RETURN"]?.[0];
    expect(line).toBeDefined();
    expect(line!.established).toBe(true);
  });

  it("keeps `time_range`, without which a conditional rule reads as unconditional", () => {
    // core1.INET_RETURN[1] — "... eq 443 time-range BUSINESS_HOURS"
    const line = fabric.acls["core1"]?.["INET_RETURN"]?.[1];
    expect(line).toBeDefined();
    expect(line!.timeRange).toBe("BUSINESS_HOURS");
  });

  it("keeps the object-group REFERENCE on the match field", () => {
    const line = fabric.acls["core1"]?.["MGMT_IN"]?.[0];
    expect(line!.src?.group).toBe("MGMT_HOSTS");
  });

  it("keeps the object groups THEMSELVES, which the snapshot does carry", () => {
    /* This is the one that produced a false statement to the user. With the groups dropped, the
       engine could not resolve MGMT_HOSTS and reported "whose members were not collected" — while
       the source file carries both members, one of which (10.0.40.0/24) is a real VLAN in this
       very fabric. A model gap described as a collection gap is a lie about our own evidence. */
    const g = fabric.objectGroups["core1"]?.["MGMT_HOSTS"];
    expect(g, "core1/MGMT_HOSTS is present in the source snapshot").toBeDefined();
    expect(g!.kind).toBe("network");
    expect(g!.members.length).toBe(2);
    expect(g!.members.map((m) => m.ip)).toContain("10.0.40.0");
    expect(g!.cite).toBe("object_groups.core1.MGMT_HOSTS");
  });

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
  it("carries eight port matches, none with a null value", () => {
    /* Known answer re-derived from the regenerated sample (GOLDEN_SHA). It was six on the sample before the
       phase-3 regeneration; the count is a fact about one snapshot, so it lives here. On THIS data the null
       branch of the property above is empty, and that is a stated, checked fact instead of a silent pass. */
    const { ports, nullPorts } = portCensus();
    expect({ ports, nullPorts }, "port matches in the compiled snapshot").toEqual({ ports: 8, nullPorts: 0 });
  });
});
