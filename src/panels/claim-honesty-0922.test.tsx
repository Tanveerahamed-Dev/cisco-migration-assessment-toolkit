/**
 * claim-honesty-0922.test.tsx — the 2026-09-22 critic's claim-honesty and coverage findings, pinned
 * over REAL engine output and the compiled snapshot (never a synthetic trace). Every guarded branch
 * is counted and required to have run, so no test here can pass with zero assertions.
 *
 *  1. A physical-health row with no measurement renders no risk and no grade (B1 blocker).
 *  2. An empty config-derived field on a port whose running configuration was not collected is
 *     "unknown", never "not in the collected configuration" (B1).
 *  3. An undecided refusal says so in its CLAIM sentence, and the live region speaks the card's
 *     headline word, not the raw outcome (B2).
 *  4. A hop-less trace is explained by the engine's own refusal record (B1).
 *  5. The intent tally never states an undecided outcome as a bare decided word (B1).
 *  6. A port the cable map puts on two cables is disputed, and no blast radius over it is "observed" (B1).
 *  7. B8's decided-counterexample rendering, on a flow whose denial IS decided.
 */
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";

import { failureImpact, linkFailureImpact } from "../analysis/blast";
import { disputesOf, findPortDisputes, PORT_DISPUTES } from "../analysis/port-claims";
import { isDecidedOutcome, undecidedOutcomeWord } from "../core/claims";
import { fabric, interfacesOf, physicalByHost } from "../core/data";
import type { Flow, Link } from "../core/types";
import { counterexample, refusalOf, suggestedFlows, traceFlow } from "../forwarding/engine";
import { ClaimCard, outcomeWordOf } from "./ClaimCard";
import { joinPorts, physHasMeasurement, physUnassessedReason } from "./DevicePane";
import { intentCatalog, runIntentSearch } from "./PathTrace";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const mounted: Root[] = [];
function mount(ui: ReactNode): HTMLElement {
  const el = document.createElement("div");
  document.body.appendChild(el);
  const root = createRoot(el);
  act(() => root.render(ui));
  mounted.push(root);
  return el;
}
afterEach(() => {
  for (const r of mounted.splice(0)) act(() => r.unmount());
  document.body.innerHTML = "";
});

const tcp = (srcIp: string, dstIp: string, dstPort: number): Flow => ({ srcIp, dstIp, protocol: "tcp", dstPort, srcPort: null });

describe("1. a physical row with no measurement is not assessed, whatever the producer stamped", () => {
  it("every row with no status and no counter yields a reason; every measured row yields none", () => {
    let unmeasured = 0;
    let measured = 0;
    for (const p of fabric.physical) {
      if (physHasMeasurement(p)) {
        measured += 1;
        // A measured row keeps its grade unless the producer marked it unassessed itself.
        if (p.risk) expect(physUnassessedReason(p), `${p.host} ${p.port}`).toBeNull();
      } else {
        unmeasured += 1;
        expect(physUnassessedReason(p), `${p.host} ${p.port}`).not.toBeNull();
      }
    }
    expect(unmeasured).toBeGreaterThan(0);
    expect(measured).toBeGreaterThan(0);
  });

  it("the critic's rows: core1 Gi1/0/40 and core2 Eth1/47 carry 'ok'/'Info' over nothing, and are withheld", () => {
    for (const [host, port] of [["core1", "Gi1/0/40"], ["core1", "Gi1/0/26"], ["core2", "Eth1/47"]] as const) {
      const p = (physicalByHost.get(host) ?? []).find((r) => r.port === port);
      expect(p, `${host} ${port}`).toBeDefined();
      expect(p!.risk).toBe("ok");
      expect(physHasMeasurement(p!)).toBe(false);
      expect(physUnassessedReason(p!)).toMatch(/no port status and no error or drop counter was observed/);
      expect(physUnassessedReason(p!)).toMatch(/stamped risk "ok" and severity "Info" over no measurements/);
    }
  });
});

describe("2. an unobserved running configuration is not an observed absence", () => {
  it("the ports the critic named have runConfigObserved false and no channel/description", () => {
    const rows = joinPorts("core1").filter((r) => r.intf !== null && r.intf.runConfigObserved === false && r.intf.description === null);
    expect(rows.length).toBeGreaterThan(0);
    expect(rows.map((r) => r.port)).toContain("Gi1/0/40");
    // And the compiled data does carry ports whose config WAS observed, so both branches are live.
    expect(interfacesOf("core1").some((i) => i.runConfigObserved === true)).toBe(true);
  });
});

describe("3. an undecided refusal is undecided in its own sentence", () => {
  it("every suggested denied/dropped flow that is not decided carries 'is not decided' in its claim", () => {
    let undecidedRefusals = 0;
    for (const s of suggestedFlows()) {
      const t = traceFlow(s.flow);
      if (t.outcome !== "denied" && t.outcome !== "dropped") continue;
      if (isDecidedOutcome(t)) {
        expect(t.claim, s.id).not.toMatch(/is not decided/);
      } else {
        undecidedRefusals += 1;
        expect(t.claim, s.id).toMatch(/That (denial|drop) is not decided: /);
      }
    }
    expect(undecidedRefusals).toBeGreaterThan(0);
  });

  it("the critic's case: core2 Vlan20 to the internet names the incomplete table in the claim, and the headline word is the undecided one", () => {
    const t = traceFlow(tcp("10.0.20.50", "198.51.100.7", 443));
    expect(t.outcome).toBe("dropped");
    expect(t.claim).toMatch(/That drop is not decided: .*core2/);
    expect(t.claim).toMatch(/not a decided absence of a route/);
    expect(outcomeWordOf(t)).toBe(undecidedOutcomeWord(t));
    expect(outcomeWordOf(t)).toMatch(/^dropped for want of a collected route — not decided/);
  });
});

describe("4. a hop-less trace carries the engine's own reason", () => {
  it("intra-subnet flows inside an observed subnet are not called 'outside every observed subnet'", () => {
    const intra = traceFlow(tcp("10.0.10.50", "10.0.10.1", 443));
    expect(intra.hops.length).toBe(0);
    expect(refusalOf(intra)?.kind).toBe("intra-subnet");
    expect(refusalOf(intra)?.reason).toMatch(/10\.0\.10\.0\/24/);
    expect(refusalOf(intra)?.reason).not.toMatch(/outside every subnet/);
    const outside = traceFlow(tcp("198.51.100.7", "10.0.30.10", 443));
    expect(outside.hops.length).toBe(0);
    expect(refusalOf(outside)?.kind).toBe("outside-observed-subnets");
    const bad = traceFlow(tcp("not-an-ip", "10.0.30.10", 443));
    expect(refusalOf(bad)?.kind).toBe("invalid-address");
    const net = traceFlow(tcp("10.0.10.0", "10.0.30.10", 443));
    expect(refusalOf(net)?.kind).toBe("not-a-host-address");
    // Every trace that consulted a device has no refusal record.
    expect(refusalOf(traceFlow(tcp("10.0.10.50", "10.0.30.10", 443)))).toBeNull();
  });

  it("the gateway intent's undecided reasons name intra-subnet L2, not an unobserved subnet", () => {
    const gw = intentCatalog().find((i) => i.kind === "all-reach" && i.claim.includes("10.0.10.0/24"));
    expect(gw, "the snapshot must still offer the VLAN 10 gateway intent").toBeDefined();
    const v = runIntentSearch(gw!);
    const text = JSON.stringify(v);
    expect(text).not.toMatch(/outside every subnet this collection observed/);
    expect(text).toMatch(/intra-subnet L2 forwarding/);
  });
});

describe("5. the intent tally never states an undecided outcome as decided", () => {
  it("with 0 decided flows, no outcome in the tally is a bare word", () => {
    let checked = 0;
    for (const intent of intentCatalog()) {
      const v = runIntentSearch(intent);
      const line = v.collateral.find((c) => c.startsWith("Outcomes inside the searched space"));
      expect(line, intent.id).toBeDefined();
      const decided = v.searched - v.undecided;
      expect(line, intent.id).toContain(`${decided} of ${v.searched} decided`);
      if (decided === 0) {
        checked += 1;
        expect(line, intent.id).not.toMatch(/\(decided\)/);
        expect(line, intent.id).toMatch(/not decided/);
      }
    }
    expect(checked).toBeGreaterThan(0);
  });
});

describe("6. one port, one cable", () => {
  it("L7 and L26 both claim core1 Gi1/0/40, and each is marked disputed naming the other", () => {
    const d = PORT_DISPUTES.find((x) => x.host === "core1" && x.port === "Gi1/0/40");
    expect(d).toBeDefined();
    expect(d!.claims.map((c) => c.linkId).sort()).toEqual(["L26", "L7"]);
    expect(disputesOf("L7").length).toBeGreaterThan(0);
    expect(disputesOf("L26").length).toBeGreaterThan(0);
    // core1's own table confirms L26 (both ends); L7 rests on access16 alone.
    expect(d!.claims.find((c) => c.linkId === "L26")?.confirmedByOwner).toBe(true);
    expect(d!.claims.find((c) => c.linkId === "L7")?.confirmedByOwner).toBe(false);
  });

  it("no link blast radius over a disputed cable is 'observed' or names stranded hosts", () => {
    let disputedCarrying = 0;
    for (const link of fabric.links) {
      const r = linkFailureImpact(link.id);
      if (disputesOf(link.id).length === 0) continue;
      expect(r.certainty, link.id).toBe("not-determinable");
      expect(r.newlyStranded, link.id).toEqual([]);
      expect(r.caveats.join(" "), link.id).toMatch(/A port terminates one cable/);
      if (r.presence === "carrying") disputedCarrying += 1;
    }
    expect(disputedCarrying).toBeGreaterThan(0);
    const l7 = linkFailureImpact("L7");
    expect(l7.claim).toMatch(/disputed/);
    expect(l7.caveats.join(" ")).toMatch(/L26/);
  });

  it("a host radius computed with a disputed cable in reach is not 'observed'", () => {
    const r = failureImpact("core1");
    expect(r.certainty).not.toBe("observed");
    expect(r.caveats.join(" ")).toMatch(/core1 Gi1\/0\/40 is placed on 2 cables/);
  });

  it("the detector is structural: a synthetic map with a shared member port is caught, a clean one is not", () => {
    const base: Link = { id: "X1", a: "h1", aPort: "Po1", b: "h2", bPort: "Po1", isPortChannel: true, members: ["Gi1 ↔ Gi1"], speedMbps: null, opStatus: "up", confirmation: "Both ends", betweenness: null, isBridge: null, pairsCut: null, centralityRank: null, cite: "x" };
    const other: Link = { ...base, id: "X2", aPort: "Gi1", b: "h3", bPort: "Gi9", isPortChannel: false, members: [], confirmation: "One end (h3)" };
    expect(findPortDisputes([base]).length).toBe(0);
    const found = findPortDisputes([base, other]);
    expect(found.map((d) => `${d.host} ${d.port}`)).toEqual(["h1 Gi1"]);
  });
});

describe("7. B8 — a decided denial offers a real counterexample, rendered as one", () => {
  it("the flow that used to be the only decided denial is router-originated, and is offered nothing", () => {
    /* REVERSED 2026-09-22 (auditor, B2). tcp 10.0.20.2 -> 10.0.10.50:22 was measured as the only flow
       reaching the decided-counterexample branch — because the engine applied core1 Vlan20's INBOUND
       list to a packet core1 itself originates. It is now refused, so no counterexample is offered and
       the card cannot be headed "Counterexample". The decided-counterexample card is pinned on a
       host-sourced denial in decided-surfaces.counterfactual.test.tsx. */
    const t = traceFlow(tcp("10.0.20.2", "10.0.10.50", 22));
    expect(t.outcome).toBe("indeterminate");
    expect(isDecidedOutcome(t)).toBe(false);
    const ce = counterexample(t.flow, t);
    expect(ce.found).toBe(false);
    const el = mount(<ClaimCard trace={t} counterexample={ce} />);
    expect(el.textContent ?? "").not.toMatch(/Counterexample — the nearest flow that behaves differently/);
    expect(el.querySelector(".claim__counter-outcome")).toBeNull();
  });
});
