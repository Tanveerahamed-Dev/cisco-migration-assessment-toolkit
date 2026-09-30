/**
 * producer-trust.test.ts — the engine must believe the producer, and must not describe its own
 * model limits as gaps in our evidence.
 *
 * Both failures pinned here were found by an adversarial refuter against the real parser
 * (`cisco_toolkit.parse._acl_rule`) and both are the same underlying mistake: the consumer
 * re-deriving something the producer already decided.
 *
 *  1. EVALUABILITY DRIFT. The producer marks a line `unevaluable` when it could not model it. If
 *     the engine re-derives that from the raw text instead, the two can disagree — and when the
 *     engine's derivation is the more optimistic one, an unknown becomes a confident wrong answer.
 *
 *  2. A MODEL GAP DESCRIBED AS A COLLECTION GAP. `MGMT_IN` references object-group `MGMT_HOSTS`.
 *     The snapshot carries that group with both members. Saying the members "were not collected"
 *     is a false statement about our own evidence, and it is the more damaging direction of error:
 *     it invites someone to go and collect data they already have.
 */
import { describe, expect, it } from "vitest";
import { fabric } from "../core/data";
import { lineEvaluability, suggestedFlows, traceFlow } from "./engine";
import { describeGolden } from "../test-support/golden-sample";
import { GOLDEN_FORWARDING as G } from "../test-support/golden-expectations";

const C1 = G.core1Acls;

describe("the producer's evaluability verdict is authoritative", () => {
  /**
   * The producer's `unevaluable` flag has TWO causes and they are not equally binding:
   *
   *   a QUALIFIER it cannot model (`established`, `icmp_type`, an unresolved port name)
   *     — binding. We hold no information the parser lacked, so overriding it would be pure
   *       optimism, and optimism here converts an unknown into a confident wrong answer.
   *
   *   a REFERENCE it could not resolve (`object-group MGMT_HOSTS`)
   *     — NOT binding, because it is a statement about what one line's parser could see in
   *       isolation, not about what the snapshot contains. The group table is a sibling key in the
   *       same file. Resolving it is reading more of our own evidence, which is the opposite of
   *       drift — and refusing to would understate our coverage, which is its own dishonesty.
   *
   * So an override is legitimate exactly when we actually resolved the reference. That is the rule
   * this test enforces.
   */
  it("overrides the producer only where it resolved a reference the producer could not", () => {
    const unjustified: string[] = [];
    for (const [host, named] of Object.entries(fabric.acls)) {
      for (const [acl, lines] of Object.entries(named)) {
        for (const line of lines) {
          if (!line.unevaluable || !lineEvaluability(line).evaluable) continue;

          const srcGroup = line.src?.group ?? null;
          const dstGroup = line.dst?.group ?? null;
          const resolvedEvery =
            (srcGroup === null || (fabric.objectGroups[host]?.[srcGroup]?.members.length ?? 0) > 0) &&
            (dstGroup === null || (fabric.objectGroups[host]?.[dstGroup]?.members.length ?? 0) > 0);
          const referencedSomething = srcGroup !== null || dstGroup !== null;

          // A qualifier the producer could not model is never overridable.
          const hasBindingQualifier =
            line.established || line.icmpType !== null || line.timeRange !== null || line.unmodeledQualifiers.length > 0;

          if (!referencedSomething || !resolvedEvery || hasBindingQualifier) {
            unjustified.push(
              `${host}.${acl}[${line.index}] — producer said unevaluable, engine says evaluable, ` +
                `with no resolved reference to justify it: ${line.raw}`,
            );
          }
        }
      }
    }
    expect(
      unjustified,
      `the engine overrode the parser without having resolved anything:\n${unjustified.join("\n")}`,
    ).toEqual([]);
  });

  it("citations keep the shape the host is derived from", () => {
    // `hostOfAclLine` reads the host out of `acls.<host>.<name>[<i>]`. If that shape ever changes,
    // object-group resolution silently stops working and every group line quietly reverts to
    // unevaluable — a capability loss that would look like nothing at all.
    for (const [host, named] of Object.entries(fabric.acls))
      for (const [acl, lines] of Object.entries(named))
        for (const line of lines) expect(line.cite).toBe(`acls.${host}.${acl}[${line.index}]`);
  });

  it("gives a reason whenever it declares a line unevaluable", () => {
    for (const [host, named] of Object.entries(fabric.acls)) {
      for (const [acl, lines] of Object.entries(named)) {
        for (const line of lines) {
          const e = lineEvaluability(line);
          if (!e.evaluable) {
            expect(e.reason, `${host}.${acl}[${line.index}] unevaluable with no reason`).toBeTruthy();
          }
        }
      }
    }
  });
});

describeGolden("the producer's evaluability verdict — the one override on the reference sample", () => {
  it("does override MGMT_IN, because MGMT_HOSTS is carried — and this is the only override", () => {
    // Pins the override to a specific, justified case rather than leaving the rule abstract.
    const overridden: string[] = [];
    for (const [host, named] of Object.entries(fabric.acls))
      for (const [acl, lines] of Object.entries(named))
        for (const line of lines)
          if (line.unevaluable && lineEvaluability(line).evaluable) overridden.push(`${host}.${acl}[${line.index}]`);
    expect(overridden).toEqual([...C1.mgmtIn.overrides]);
  });
});

/* Golden (phase 3): the two blocks below read core1's MGMT_HOSTS and INET_RETURN[1] by name. */
describeGolden("our own model limits are not described as gaps in the collection", () => {
  it("never tells a user that object-group members were not collected when they were", () => {
    const group = fabric.objectGroups[C1.host]?.[C1.mgmtIn.group];
    expect(group, `the snapshot carries ${C1.host}/${C1.mgmtIn.group}`).toBeDefined();
    expect(group!.members.length).toBeGreaterThan(0);

    // Gather every sentence the engine can put in front of a user about core1's ACLs.
    const prose: string[] = [];
    for (const s of suggestedFlows()) {
      const t = traceFlow(s.flow);
      prose.push(t.claim, ...t.caveats);
      for (const h of t.hops) {
        if (h.decidedBy) prose.push(h.decidedBy.label);
        for (const ev of h.evidence) prose.push(ev.label);
      }
    }
    const line = fabric.acls[C1.host]?.[C1.mgmtIn.name]?.[0];
    expect(line, `${C1.mgmtIn.lineCite} exists`).toBeDefined();
    prose.push(lineEvaluability(line!).reason ?? "");

    const falseClaims = prose.filter(
      (p) => p.includes(C1.mgmtIn.group) && /not collected|were not collected|no members/i.test(p),
    );
    expect(
      falseClaims,
      `the engine says these members were not collected, but the snapshot carries ${group!.members.length}:\n${falseClaims.join("\n")}`,
    ).toEqual([]);
  });
});

describeGolden("a conditional rule never yields an unconditional verdict", () => {
  it("treats a time-ranged line as conditional rather than always-active", () => {
    // core1.INET_RETURN[1] is "... eq 443 time-range BUSINESS_HOURS".
    const line = fabric.acls[C1.host]?.[C1.inetReturn.name]?.[1];
    expect(line?.cite).toBe(C1.inetReturn.timeRangedCite);
    expect(line?.timeRange, "this fixture depends on a real time-ranged rule").toBe(C1.inetReturn.timeRange);
    const e = lineEvaluability(line!);
    expect(e.evaluable, "a rule that is only active inside a window cannot be evaluated flatly").toBe(false);
    expect(/time[- ]range/i.test(e.reason ?? "") || (e.reason ?? "").includes(C1.inetReturn.timeRange), e.reason ?? "").toBe(true);
  });
});

describe("a null port value is never compared as a number", () => {
  it("marks any line carrying an unresolved port name as unevaluable", () => {
    /* The refuter's blocker, reproduced structurally: the producer emits {"op":"eq","val":null}
       for `eq citrix`. Comparing that numerically gives a definite non-match, so a permit stops
       firing and the flow silently falls through to a deny. The synthetic line below is shaped
       exactly like the real producer's output for that case. */
    const line = {
      index: 0,
      action: "permit",
      raw: "permit tcp any any eq citrix",
      proto: "tcp",
      src: { ip: "0.0.0.0", wild: "255.255.255.255", group: null },
      dst: { ip: "0.0.0.0", wild: "255.255.255.255", group: null },
      sport: null,
      dport: { op: "eq", val: null },
      unevaluable: true,
      unmodeledQualifiers: ["unresolved_port_name"],
      established: false,
      icmpType: null,
      timeRange: null,
      cite: "synthetic",
    };
    const e = lineEvaluability(line);
    expect(e.evaluable, "an unresolved port name must not be evaluated").toBe(false);
  });

  it("also catches it when the producer forgot the flag but the value is null", () => {
    // Defence in depth: the null value alone is sufficient evidence that we cannot decide.
    const line = {
      index: 0,
      action: "permit",
      raw: "permit udp any any range 16384 dynamic",
      proto: "udp",
      src: { ip: "0.0.0.0", wild: "255.255.255.255", group: null },
      dst: { ip: "0.0.0.0", wild: "255.255.255.255", group: null },
      sport: null,
      dport: { op: "range", val: 16384, val2: null },
      unevaluable: false,
      unmodeledQualifiers: [],
      established: false,
      icmpType: null,
      timeRange: null,
      cite: "synthetic",
    };
    const e = lineEvaluability(line);
    expect(e.evaluable, "a range with an unresolved bound cannot be evaluated").toBe(false);
  });
});
