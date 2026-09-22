/**
 * HopList.ingress-reason.test.tsx — an undecided reason never says something false about the host.
 *
 * 2026-09-21 critic (A2/A3), over REAL flows traced by the real engine against the compiled snapshot:
 *  - core1 HAS collected ACLs (PROTECT_SERVERS is bound outbound on Vlan30), yet a hop whose only gap
 *    was an unobserved physical INGRESS PORT printed "no ACLs were collected for core1" — beside the
 *    PROTECT_SERVERS line that decided it. `ingress-port-unobserved` shared the `acl-uncollected`
 *    reason. The reason must name the ingress ports, and "no ACLs were collected" must appear only
 *    for a host with no collected ACLs — checked against the coverage denominator, for every hop of
 *    every flow below, not against a list of host names.
 *  - the trace headline over the undecided tcp/80 denial was the fixed "denied by list text — binding
 *    not observed", while the binding WAS observed. The headline must be built from the actual cause.
 */
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";

import { fabric } from "../core/data";
import type { Flow } from "../core/types";
import { traceFlow, unobservedPolicyInputs } from "../forwarding/engine";
import { ClaimCard } from "./ClaimCard";
import { HopList } from "./HopList";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

afterEach(() => {
  document.body.innerHTML = "";
});

const flow = (srcIp: string, dstIp: string, protocol: Flow["protocol"], dstPort: number | null): Flow => ({
  srcIp,
  dstIp,
  protocol,
  dstPort,
  srcPort: null,
});

function render(f: Flow): HTMLElement {
  const trace = traceFlow(f);
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  act(() =>
    root.render(
      <>
        <ClaimCard trace={trace} />
        <HopList trace={trace} activeIndex={null} onSelect={() => {}} />
      </>,
    ),
  );
  return host;
}

const FLOWS: readonly Flow[] = [
  flow("10.0.10.50", "10.0.30.10", "tcp", 443),
  flow("10.0.10.50", "10.0.30.10", "tcp", 22),
  flow("10.0.10.50", "10.0.30.10", "tcp", 80),
  flow("10.0.10.50", "10.0.20.10", "udp", 5060),
  flow("10.0.30.10", "10.0.10.50", "tcp", 443),
  flow("10.0.20.50", "10.0.10.50", "tcp", 443),
  flow("10.0.10.50", "8.8.8.8", "tcp", 443),
];

const NO_ACLS = /no ACLs were collected for (\S+),/;

describe("'no ACLs were collected' is said only of a host with no collected ACLs", () => {
  it("precondition: core1 carries collected ACLs in this snapshot", () => {
    expect(fabric.coverage.aclHosts).toContain("core1");
  });

  /* Every undecided reason is checked against what the coverage denominator and the engine's own gaps
     say it must read — never skipped. The per-flow tests used to assert only inside
     `if (m !== null)`, and "no ACLs were collected" appears on 1 of the 7 flows, so 6 of them passed
     having checked nothing (critic F2, 2026-09-22). Now, for every hop that renders a reason:
       - a host WITH collected ACLs must not be described as having none, in any wording;
       - a host WITHOUT collected ACLs whose gap is `acl-uncollected` must be named as such.
     Both directions are counted, and each is required to have run somewhere in the suite. */
  function checkReasons(f: Flow): { reasons: number; aclHostReasons: number; noAclReasons: number } {
    const trace = traceFlow(f);
    const gaps = unobservedPolicyInputs(trace);
    const c = render(f);
    const tally = { reasons: 0, aclHostReasons: 0, noAclReasons: 0 };
    for (const hop of c.querySelectorAll<HTMLElement>(".hop")) {
      const host = hop.querySelector(".hop__host")?.textContent ?? "";
      for (const reason of hop.querySelectorAll("[data-undecided-reason]")) {
        tally.reasons += 1;
        const text = reason.textContent ?? "";
        const where = `${host}: ${text}`;
        if (fabric.coverage.aclHosts.includes(host)) {
          tally.aclHostReasons += 1;
          expect(text, `${host} has collected ACLs but was described as having none — ${where}`).not.toMatch(/no ACLs were collected/);
        } else if (gaps.some((g) => g.host === host && g.kind === "acl-uncollected")) {
          tally.noAclReasons += 1;
          expect(NO_ACLS.exec(text)?.[1], where).toBe(host);
        }
        // A reason naming a host other than its own hop is a misattribution either way.
        const named = NO_ACLS.exec(text)?.[1];
        if (named !== undefined) expect(named, where).toBe(host);
      }
    }
    return tally;
  }

  for (const f of FLOWS) {
    it(`${f.protocol} ${f.srcIp} -> ${f.dstIp}:${f.dstPort ?? ""}`, () => {
      const t = checkReasons(f);
      /* Each flow in this list is here because its trace carries an undecided hop; a flow that
         renders no reason at all has stopped exercising the rule and must be replaced, not kept. */
      expect(t.reasons, "this flow no longer renders any undecided reason").toBeGreaterThan(0);
    });
  }

  it("both directions of the rule ran over the flows above", () => {
    const total = FLOWS.map(checkReasons).reduce(
      (a, t) => ({ reasons: a.reasons + t.reasons, aclHostReasons: a.aclHostReasons + t.aclHostReasons, noAclReasons: a.noAclReasons + t.noAclReasons }),
      { reasons: 0, aclHostReasons: 0, noAclReasons: 0 },
    );
    expect(total.aclHostReasons, "no reason on a host WITH collected ACLs was checked").toBeGreaterThan(0);
    expect(total.noAclReasons, "no 'no ACLs were collected' reason was checked").toBeGreaterThan(0);
  });

  it("the core1 ingress-port gap names the unobserved ports instead", () => {
    const f = flow("10.0.10.50", "10.0.30.10", "tcp", 443);
    const kinds = unobservedPolicyInputs(traceFlow(f)).map((g) => [g.host, g.kind]);
    expect(kinds, "precondition: this flow carries an ingress-port gap at core1").toContainEqual(["core1", "ingress-port-unobserved"]);
    const hop = render(f).querySelector<HTMLElement>(".hop")!;
    expect(hop.querySelector(".hop__host")?.textContent).toBe("core1");
    /* UPDATED 2026-09-22 (auditor, B1): this hop is ALSO undecided because the connected route it
       delivers on was chosen from core1's incomplete table, and the verdict word names one cause. Either
       true cause may head it; what it may never say is "no ACLs were collected" (checked below). */
    expect(hop.querySelector(".verdict")?.textContent).toMatch(/ingress filtering unobserved|table incomplete/);
    expect(hop.querySelector(".verdict")?.textContent).not.toMatch(/no ACLs/);
    const reason = hop.querySelector("[data-undecided-reason]")?.textContent ?? "";
    expect(reason).toMatch(/physical ports? whose inbound filtering was not observed/);
    expect(reason).not.toMatch(/no ACLs were collected/);
  });
});

describe("the undecided trace headline is built from the actual cause", () => {
  it("tcp/80 denial at core1: binding observed, so the headline does not claim it unobserved", () => {
    const f = flow("10.0.10.50", "10.0.30.10", "tcp", 80);
    const trace = traceFlow(f);
    const gaps = unobservedPolicyInputs(trace);
    expect(trace.outcome, "precondition").toBe("denied");
    expect(gaps.some((g) => g.kind === "acl-unbound-denial"), "precondition: the denying list's binding was observed").toBe(false);
    const word = render(f).querySelector(".claim__outcome-word")?.textContent ?? "";
    expect(word).toMatch(/^denied by list text — not decided/);
    expect(word).not.toMatch(/binding not observed/);
    for (const g of gaps.filter((x) => x.kind === "ingress-alternate")) expect(word).toContain(`ingress via ${g.host}`);
  });
});
