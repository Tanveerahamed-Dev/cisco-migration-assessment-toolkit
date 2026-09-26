/**
 * claim-honesty-cluster-0922.test.ts — pins the 2026-09-22 claim-honesty findings (B1, B2, B4, B5)
 * over the SHIPPED snapshot, structurally rather than by named host where the finding was a class.
 */
import { describe, expect, it } from "vitest";
import { failureImpact } from "../analysis/blast";
import { cableCountPhrase, hostCableAccount, PORT_DISPUTES } from "../analysis/port-claims";
import { describeDevice, blastQualifier } from "../fabric3d/Fabric3D";
import { evaluateAcls, lineEvaluability, traceFlow } from "../forwarding/engine";
import { parseIpv4 } from "../forwarding/ip";
import { FLEET_CONSTANTS } from "../panels/DevicePane";
import { claimBadge, isInvalidInput, T1_verdict, type ClaimBadge } from "./claims";
import { fabric, linksByHost } from "./data";
import type { Flow, TraceOutcome } from "./types";

const flow = (srcIp: string, dstIp: string, protocol: Flow["protocol"], dstPort: number | null): Flow => ({
  srcIp,
  dstIp,
  protocol,
  srcPort: null,
  dstPort,
});

describe("B1 — a device's cable count goes through the port-dispute detector", () => {
  it("every host whose own port is disputed states a ceiling below its record count", () => {
    const hosts = new Set(PORT_DISPUTES.map((d) => d.host));
    expect(hosts.size).toBeGreaterThan(0);
    for (const host of hosts) {
      const acct = hostCableAccount(host, linksByHost.get(host) ?? []);
      expect(acct.maxReal).toBeLessThan(acct.records);
      expect(cableCountPhrase(acct)).toMatch(new RegExp(`at most ${acct.maxReal} can be real`));
    }
  });

  it("AP-floor1: 17 records, at most 1 real — on the pane phrase, the blast caveat and the announcement", () => {
    const acct = hostCableAccount("AP-floor1", linksByHost.get("AP-floor1") ?? []);
    expect(acct.records).toBe(17);
    expect(acct.maxReal).toBe(1);
    const said = describeDevice("AP-floor1");
    expect(said).not.toMatch(/\b17 links\b/);
    expect(said).toMatch(/at most 1 can be real/);
    const caveats = failureImpact("AP-floor1").caveats.join(" ");
    expect(caveats).not.toMatch(/17 cable\(s\) terminate on it/);
    expect(caveats).toMatch(/at most 1 can be real/);
    expect(caveats).not.toMatch(/Its cables are real/);
  });

  it("a host with no disputed cable keeps the plain count", () => {
    const clean = fabric.devices.find((d) => (linksByHost.get(d.host) ?? []).length > 0 && hostCableAccount(d.host, linksByHost.get(d.host) ?? []).disputedLinkIds.length === 0);
    expect(clean, "precondition: the fleet holds a cabled host with no disputed cable").toBeDefined();
    expect(cableCountPhrase(hostCableAccount(clean!.host, linksByHost.get(clean!.host) ?? []))).toMatch(/^\d+ cables? in the cable map$/);
  });
});

describe("B1 — the fleet-constant detector runs over every numeric producer field", () => {
  it("finds data_quality (1 on every inventoried device) without being told its name", () => {
    const inv = fabric.devices.filter((d) => d.inventoried);
    const dq = new Set(inv.map((d) => d.dataQuality));
    expect(dq.size, "precondition: data_quality is one value across the inventoried fleet").toBe(1);
    expect(typeof [...dq][0], "precondition: that one value is numeric").toBe("number");
    expect(FLEET_CONSTANTS.get("dataQuality")).toBe([...dq][0]);
    // And it does not flag a field that varies.
    for (const [k] of FLEET_CONSTANTS) {
      const vals = new Set(inv.map((d) => (d as unknown as Record<string, unknown>)[k]));
      expect(vals.size).toBe(1);
    }
  });
});

describe("B1 — the blast qualifier carries certainty and the differing projection", () => {
  it("core1's uncertain radius names the all-nodes answer", () => {
    const r = failureImpact("core1");
    const q = blastQualifier(r.certainty, r.newlyStranded.length, r.alternateProjections);
    if (r.certainty === "observed") expect(q).toBe("");
    else {
      expect(q).toMatch(/^uncertain/);
      for (const a of r.alternateProjections.filter((x) => x.differs && x.newlyStrandedCount !== r.newlyStranded.length))
        expect(q).toContain(`${a.newlyStrandedCount} under the`);
    }
  });
});

describe("B2 — no simulated verdict wears the word OBSERVED", () => {
  it("over a sweep of flows, the badge and the T1 scope line never say OBSERVED", () => {
    /* The badge half used to assert `claimBadge(t) !== "OBSERVED"` — a type-level constant, since
       the ClaimBadge union has no such member (critic F2, 2026-09-22). It is now a per-outcome
       WHITELIST, which can fail: a badge a trace's outcome does not license — OBSERVED or any other
       word, SCOPED on an indeterminate trace, OUT OF SCOPE on a malformed question — is caught at
       runtime whatever the type says. The sweep must also reach more than one badge, or it pins
       one branch of claimBadge and calls it the class. */
    const licensed: Readonly<Record<TraceOutcome, readonly ClaimBadge[]>> = {
      delivered: ["SCOPED", "PARTIAL", "INDETERMINATE"],
      denied: ["SCOPED", "PARTIAL", "INDETERMINATE"],
      dropped: ["SCOPED", "PARTIAL", "INDETERMINATE"],
      indeterminate: ["INDETERMINATE"],
      "out-of-scope": ["OUT OF SCOPE"],
    };
    const addrs = ["10.0.10.50", "10.0.30.10", "10.0.30.1", "10.0.10.2", "10.0.99.10", "10.0.20.5", "198.51.100.7", "10.0.10.3/24"];
    const seen = new Set<string>();
    for (const s of addrs)
      for (const d of addrs) {
        if (s === d) continue;
        for (const [p, port] of [["tcp", 443], ["tcp", 22], ["udp", 53]] as const) {
          const t = traceFlow(flow(s, d, p, port));
          const badge = claimBadge(t);
          seen.add(badge);
          const allowed = isInvalidInput(t) ? ["INVALID INPUT"] : licensed[t.outcome];
          expect(allowed, `${s} -> ${d} ${p}/${port} (${t.outcome})`).toContain(badge);
          expect(T1_verdict(t)).not.toMatch(/^OBSERVED:/);
        }
      }
    expect(seen.size, [...seen].join(", ")).toBeGreaterThan(2);
  });
});

describe("B4 — invalid input is its own result, not out of scope", () => {
  it("10.0.10.3/24 as an address is INVALID INPUT", () => {
    const t = traceFlow(flow("10.0.10.50", "10.0.10.3/24", "tcp", 443));
    expect(claimBadge(t)).toBe("INVALID INPUT");
    expect(T1_verdict(t)).toMatch(/^INVALID INPUT: .* is not a valid flow/);
  });
  it("an address outside the observed subnets stays OUT OF SCOPE", () => {
    expect(claimBadge(traceFlow(flow("198.51.100.7", "10.0.30.10", "tcp", 443)))).toBe("OUT OF SCOPE");
  });
});

describe("B5 — the not-applied caveat agrees with lineEvaluability about object-groups", () => {
  it("MGMT_IN's resolved MGMT_HOSTS group is not called unresolvable", () => {
    const lines = fabric.acls.core1?.MGMT_IN ?? [];
    expect(lines.length).toBeGreaterThan(0);
    expect(lineEvaluability(lines[0]!).evaluable).toBe(true);
    const r = evaluateAcls("core1", flow("10.0.99.10", "10.0.10.2", "tcp", 22), parseIpv4("10.0.99.10")!, parseIpv4("10.0.10.2")!, { MGMT_IN: lines });
    const text = r.caveats.join(" ");
    expect(text).not.toMatch(/could not be resolved in this snapshot/);
    expect(text).toMatch(/object-group MGMT_HOSTS, which resolved/);
  });
});
