/**
 * EvidencePane.namedconfig.test.ts — the two branches of `configEvidenceFor` that this snapshot's
 * own findings never reach.
 *
 * WHY THIS FILE EXISTS. `configEvidenceFor` has three branches: interface, ACL and route. Measured
 * over the real compiled data, exactly 6 of 146 findings resolve to literally-named configuration
 * and ALL SIX go through the interface branch. Zero findings name a collected ACL by name; zero
 * name a prefix that a collected host routes. So on the shipped data the ACL and route branches
 * have never executed, in the app or in the suite — a regression in either would have been
 * invisible, and A1's "the configuration evidence behind a finding" was being graded on a path
 * that fires for 4 % of findings.
 *
 * WHAT IS FIXTURE AND WHAT IS REAL. The finding text is synthetic — it has to be, because no real
 * finding names an ACL — but every configuration record the branch resolves to, every name it
 * matches on, and every prefix and citation it returns come from the REAL `fabric.json`, read here
 * at test time. A hand-shaped ACL record would only prove the branch agrees with a fixture built
 * to its own expectations. The first test below states the coverage fact itself, so the day the
 * data changes, the claim in `docs/acceptance.md` fails with it rather than quietly rotting.
 */
import { describe, expect, it } from "vitest";
import { fabric, hasRib, routesOf } from "../core/data";
import type { Finding } from "../core/types";
import { configEvidenceFor, nearestConfigFor } from "./EvidencePane";

const findingNaming = (devices: string[], title: string, detail: string | null = null): Finding => ({
  id: "TEST",
  severity: "High",
  rank: null,
  priority: null,
  category: null,
  devices,
  wave: null,
  title,
  detail,
  remediation: null,
  cite: "punchlist[0]",
});

/** The one host with collected ACLs, and its first collected list, read from the real data. */
const aclHost = Object.keys(fabric.acls)[0];
const aclName = aclHost === undefined ? undefined : Object.keys(fabric.acls[aclHost] ?? {})[0];

/** A host with a RIB and a routed prefix, read from the real data. */
const ribHost = Object.keys(fabric.routes).find((h) => routesOf(h).length > 0);
const routedPrefix = ribHost === undefined ? undefined : routesOf(ribHost)[0]?.prefix;

describe("the named-configuration path, and how much of the punchlist actually reaches it", () => {
  it("records which branch the real findings reach, so the acceptance claim cannot rot silently", () => {
    const kinds: Record<string, number> = {};
    let named = 0;
    for (const f of fabric.findings) {
      const hits = configEvidenceFor(f);
      if (hits.length === 0) continue;
      named += 1;
      for (const h of hits) kinds[h.kind] = (kinds[h.kind] ?? 0) + 1;
    }
    // A RATCHET over the real data, not a target. `docs/acceptance.md` states this ratio in the A1
    // evidence row; if the data gains a finding that names an ACL or a prefix, this fails and the
    // sentence there has to be re-measured rather than left standing.
    expect(named, "findings resolving to literally-named configuration").toBe(6);
    expect(Object.keys(kinds).sort(), "the branches the real data reaches").toEqual(["interface"]);
    expect(named).toBeLessThan(fabric.findings.length);
  });

  it("resolves an ACL the finding names, against the real collected list", () => {
    expect(aclHost, "this snapshot must hold at least one collected ACL").toBeDefined();
    expect(aclName).toBeDefined();
    const lines = fabric.acls[aclHost!]![aclName!]!;

    const f = findingNaming([aclHost!], `Permissive rule in ${aclName} at line ${lines[1]?.index ?? 1}`);
    const hits = configEvidenceFor(f);
    const acl = hits.find((h) => h.kind === "acl");

    expect(acl, "a finding naming a collected access list must resolve to it").toBeDefined();
    if (acl?.kind !== "acl") throw new Error("unreachable");
    expect(acl.host).toBe(aclHost);
    expect(acl.label).toContain(aclName!);
    // The lines are the real record, not a copy: same count, same citations, same literal text.
    expect(acl.lines).toHaveLength(lines.length);
    expect(acl.lines.map((l) => l.cite)).toEqual(lines.map((l) => l.cite));
    expect(acl.focusIndex, "the line index named in the finding is carried through").toBe(lines[1]?.index ?? 1);
    expect(acl.how).toContain(aclName!);
    // And it is NOT the nearest-record path — that is the distinction A1 turns on.
    expect(acl.how).not.toContain("not named by this finding");
  });

  it("leaves focusIndex null when the finding names the list but no line", () => {
    const f = findingNaming([aclHost!], `${aclName} is applied nowhere`);
    const acl = configEvidenceFor(f).find((h) => h.kind === "acl");
    if (acl?.kind !== "acl") throw new Error("expected an acl hit");
    expect(acl.focusIndex).toBeNull();
  });

  it("does not resolve an ACL name that was never collected", () => {
    /* The shape of the real F017, "Undefined acl '7'": the finding names a list, but the list is
       not in the evidence. Inventing a record for it would be the worst possible answer. */
    const f = findingNaming([aclHost!], "Undefined acl '7' referenced by an interface");
    expect(configEvidenceFor(f).some((h) => h.kind === "acl")).toBe(false);
    // The pane then falls back to the nearest records, which say so in their own words.
    for (const n of nearestConfigFor(f)) expect(n.how).toContain("not named by this finding");
  });

  it("resolves a prefix the finding names, against the real routing table", () => {
    expect(ribHost, "this snapshot must hold at least one collected RIB").toBeDefined();
    expect(routedPrefix).toBeDefined();
    expect(hasRib(ribHost!)).toBe(true);

    const f = findingNaming([ribHost!], `Suboptimal path for ${routedPrefix}`);
    const route = configEvidenceFor(f).find((h) => h.kind === "route");

    expect(route, "a finding naming a routed prefix must resolve to the route").toBeDefined();
    if (route?.kind !== "route") throw new Error("unreachable");
    expect(route.host).toBe(ribHost);
    expect(route.entries.length).toBeGreaterThan(0);
    for (const e of route.entries) {
      expect(e.prefix).toBe(routedPrefix);
      // The citation is the real one from the compiled table, not a constructed string.
      expect(routesOf(ribHost!).some((r) => r.cite === e.cite)).toBe(true);
    }
  });

  it("does not resolve a prefix on a host that holds no routing table", () => {
    const noRib = fabric.devices.find((d) => !hasRib(d.host));
    expect(noRib, "this snapshot must hold a device with no RIB").toBeDefined();
    const f = findingNaming([noRib!.host], `Suboptimal path for ${routedPrefix}`);
    // Absence of a RIB is absence: no route record may be produced for a host we never collected.
    expect(configEvidenceFor(f).some((h) => h.kind === "route")).toBe(false);
  });

  it("does not resolve a prefix the collected table does not carry", () => {
    const f = findingNaming([ribHost!], "Suboptimal path for 203.0.113.0/24");
    expect(configEvidenceFor(f).some((h) => h.kind === "route")).toBe(false);
  });
});
