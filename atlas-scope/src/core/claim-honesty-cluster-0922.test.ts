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
import { describeGolden } from "../test-support/golden-sample";
import type { Flow, TraceOutcome } from "./types";

const flow = (srcIp: string, dstIp: string, protocol: Flow["protocol"], dstPort: number | null): Flow => ({
  srcIp,
  dstIp,
  protocol,
  srcPort: null,
  dstPort,
});

/* The named-skip preconditions of this file, at module scope so the golden block at its foot can state that each holds
   on the reference sample (QC-R1-4): a sample change that falsified one must turn red, not into a silent skip. */
const DISPUTED_HOSTS = [...new Set(PORT_DISPUTES.map((d) => d.host))].sort();
/** Hosts whose cable records outnumber what can be real (the sample's AP-floor1: 17 records, at most 1 real). */
const OVERCOUNTED = fabric.devices
  .map((d) => d.host)
  .filter((h) => {
    const acct = hostCableAccount(h, linksByHost.get(h) ?? []);
    return acct.maxReal < acct.records;
  });
/** Every ACL line that names an object-group the snapshot resolved (the sample's core1 MGMT_IN[0], MGMT_HOSTS). */
const GROUP_LINES = Object.entries(fabric.acls).flatMap(([host, acls]) =>
  Object.entries(acls).flatMap(([name, lines]) =>
    lines.flatMap((line) => {
      const group = line.src?.group ?? line.dst?.group ?? null;
      const def = group === null ? undefined : fabric.objectGroups[host]?.[group];
      return def === undefined || group === null ? [] : [{ host, name, lines, line, group, def }];
    }),
  ),
);

describe("B1 — a device's cable count goes through the port-dispute detector", () => {
  /* RE-EXPRESSED 2026-09-29 (P3C-V2-3): these blocks named the sample's audited hosts (AP-floor1, core1, MGMT_IN on
     core1); each is now the CLASS it stood for, over whatever the loaded fabric holds, skipped by name where the
     fabric has none of it, and the audited instances are pinned in the golden block at the foot of this file. */
  it.runIf(DISPUTED_HOSTS.length > 0)(
    DISPUTED_HOSTS.length > 0
      ? "every host whose own port is disputed states a ceiling below its record count"
      : "every host whose own port is disputed states a ceiling below its record count [skipped: the loaded dataset has no disputed port]",
    () => {
    const hosts = DISPUTED_HOSTS;
    expect(hosts.length).toBeGreaterThan(0);
    for (const host of hosts) {
      const acct = hostCableAccount(host, linksByHost.get(host) ?? []);
      expect(acct.maxReal).toBeLessThan(acct.records);
      expect(cableCountPhrase(acct)).toMatch(new RegExp(`at most ${acct.maxReal} can be real`));
    }
    },
  );

  it.runIf(OVERCOUNTED.length > 0)(
    OVERCOUNTED.length > 0
      ? "a host with more cable records than can be real says the ceiling — on the pane phrase, the blast caveat and the announcement"
      : "a host with more cable records than can be real says the ceiling [skipped: the loaded dataset has no such host]",
    () => {
      for (const host of OVERCOUNTED) {
        const acct = hostCableAccount(host, linksByHost.get(host) ?? []);
        const said = describeDevice(host);
        expect(said, host).not.toMatch(new RegExp(`\\b${acct.records} links\\b`));
        expect(said, host).toMatch(new RegExp(`at most ${acct.maxReal} can be real`));
        const caveats = failureImpact(host).caveats.join(" ");
        expect(caveats, host).not.toMatch(new RegExp(`${acct.records} cable\\(s\\) terminate on it`));
        // A never-collected host states the ceiling over its whole record count; a collected one names each port
        // that more cables claim than it can terminate ("at most one is real"). Either way the ceiling is said.
        expect(caveats, host).toMatch(new RegExp(`at most (${acct.maxReal} can be real|one is real)`));
        expect(caveats, host).not.toMatch(/Its cables are real/);
      }
    },
  );

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
  it("every device's qualifier names its certainty and every differing projection", () => {
    let qualified = 0;
    for (const d of fabric.devices) {
      const r = failureImpact(d.host);
      const q = blastQualifier(r.certainty, r.newlyStranded.length, r.alternateProjections);
      if (r.certainty === "observed") {
        expect(q, d.host).toBe("");
        continue;
      }
      qualified += 1;
      expect(q.startsWith(r.certainty), `${d.host}: ${q}`).toBe(true);
      for (const x of r.alternateProjections.filter((y) => y.differs && y.newlyStrandedCount !== r.newlyStranded.length))
        expect(q, d.host).toContain(`${x.newlyStrandedCount} under the`);
    }
    expect(qualified, "some device's radius is not observed, so the qualifier is exercised").toBeGreaterThan(0);
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
  it.runIf(GROUP_LINES.length > 0)(
    GROUP_LINES.length > 0
      ? "a resolved object-group is never called unresolvable"
      : "a resolved object-group is never called unresolvable [skipped: the loaded dataset has no ACL line naming a resolved group]",
    () => {
      let judged = 0;
      for (const { host, name, lines, line, group, def } of GROUP_LINES) {
        /* A flow the line itself speaks about: a member of its group on the group's side, the line's own address
           (or the host's first SVI address, for `any`) on the other, and the line's own port. */
        const member = def.members[0]?.ip ?? null;
        const svi = (fabric.l3.find((r) => r.host === host)?.sviIp ?? "").split(" ")[0] || "192.0.2.1";
        const other = (spec: typeof line.src): string => (spec !== null && spec.ip !== null && spec.ip !== "0.0.0.0" ? spec.ip : svi);
        const src = line.src?.group === group ? member : other(line.src);
        const dst = line.dst?.group === group ? member : other(line.dst);
        if (src === null || dst === null) continue;
        judged += 1;
        const proto = line.proto === "udp" ? "udp" : "tcp";
        const port = line.dport?.op === "eq" ? Number(line.dport.val) : 443;
        expect(lineEvaluability(line).evaluable, line.cite).toBe(true);
        const r = evaluateAcls(host, flow(src, dst, proto, port), parseIpv4(src)!, parseIpv4(dst)!, { [name]: lines });
        const text = r.caveats.join(" ");
        expect(text, line.cite).not.toMatch(/could not be resolved in this snapshot/);
        expect(text, line.cite).toMatch(new RegExp(`object-group ${group}, which resolved`));
      }
      expect(judged, "some group line had a member address to build a flow from").toBeGreaterThan(0);
    },
  );
});

describeGolden("claim honesty on the reference sample (the audited instances)", () => {
  it("every named-skip precondition of this file holds here, so none of its class sweeps is skipped on the sample", () => {
    expect(DISPUTED_HOSTS.length).toBeGreaterThan(0);
    expect(OVERCOUNTED).toContain("AP-floor1");
    expect(GROUP_LINES.some((x) => x.host === "core1" && x.name === "MGMT_IN" && x.group === "MGMT_HOSTS")).toBe(true);
  });

  it("AP-floor1: 17 records, at most 1 real — on the pane phrase, the blast caveat and the announcement", () => {
    const acct = hostCableAccount("AP-floor1", linksByHost.get("AP-floor1") ?? []);
    expect(acct.records).toBe(17);
    expect(acct.maxReal).toBe(1);
    expect(describeDevice("AP-floor1")).toMatch(/at most 1 can be real/);
    expect(failureImpact("AP-floor1").caveats.join(" ")).toMatch(/at most 1 can be real/);
  });

  it("core1's uncertain radius names the all-nodes answer", () => {
    const r = failureImpact("core1");
    expect(blastQualifier(r.certainty, r.newlyStranded.length, r.alternateProjections)).toMatch(/^uncertain/);
  });

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
