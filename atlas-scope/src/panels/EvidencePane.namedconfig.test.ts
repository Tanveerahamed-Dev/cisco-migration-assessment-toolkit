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

  it("records how many two-click paths land on literal configuration TEXT rather than parsed fields", () => {
    /* THE SECOND SPLIT INSIDE A1, measured rather than sampled.
       The first split — 6 of 146 findings name their own configuration — was already stated. It is
       not the one a reader feels. The record the two-click path actually OPENS is `targets[0]` in
       the pane, and only the ACL branch carries literal configuration lines: an interface record is
       preserved as parsed fields and the pane says so in its own words ("Its surrounding
       configuration block was not kept, so there is no literal text to show for it"). So a reader
       told "two clicks to the configuration evidence" gets a field table for most findings —
       including every one of the six that literally NAME configuration.
       This measures it over the whole corpus so the A1 evidence row states a census, not a sample,
       and so the sentence there fails with the data rather than rotting silently. */
    let literal = 0;
    let parsed = 0;
    let namedLiteral = 0;
    let named = 0;
    const noTarget: string[] = [];
    for (const f of fabric.findings) {
      const hits = configEvidenceFor(f);
      const targets = hits.length > 0 ? hits : nearestConfigFor(f);
      const first = targets[0];
      /* A finding with nothing to land on is a THIRD category, not a rounding error. It used to be
         silently skipped here, so the census below read "24 + 122 = 146, every finding reaches
         configuration" — true only while F142 was being pointed at something. F142 ("No QoS
         configured anywhere") names no device and quotes no line: its evidence is a fleet-wide
         absence, and there is honestly no single record to open. Counting it explicitly means the
         sentence this census backs cannot overstate reach again. */
      if (first === undefined) {
        noTarget.push(f.id);
        continue;
      }
      if (hits.length > 0) {
        named += 1;
        if (first.kind === "acl") namedLiteral += 1;
      }
      if (first.kind === "acl") literal += 1;
      else parsed += 1;
    }

    expect(fabric.findings.length).toBe(146);
    /* 24 -> 22 and 121 -> 123 on 2026-09-21 (A1): F102 and F109 ("Port err-disabled", "core1: L1
       fault on an L3 gateway switch") used to open core1's first ACL because it happened to be
       listed first; they now open core1 Gi1/0/9, the err-disabled port core1's own deductions name.
       Fewer "literal" landings is the correct direction: the ACL was never the evidence.
       22 -> 2 and 123 -> 143 on 2026-09-22 (A1): the remaining 20 were core1 findings (F004 hardware,
       F100 single gateway, …) opening core1 · VOICE_FILTER only because it is core1's first list.
       Access lists are now ranked by their name's words like everything else; the two that stay
       literal are F106 and F107, which open MGMT_IN because they say "management". */
    expect(literal, "findings whose two-click record carries literal configuration lines").toBe(2);
    expect(parsed, "findings whose two-click record is parsed fields with no literal block").toBe(143);
    expect(noTarget, "findings with no configuration target at all — each must be a fleet-wide conclusion").toEqual(["F142"]);
    expect(literal + parsed + noTarget.length, "every finding is accounted for in exactly one category").toBe(146);
    expect(named).toBe(6);
    expect(namedLiteral, "of the six findings that NAME configuration, how many reach literal text").toBe(0);

    /* RE-MEASURED 2026-09-22 after the compiler began carrying the producer's `source_command`
       (see EvidencePane.source.test.tsx for the search behind it). The numbers above did NOT move,
       and that is the correct result rather than an oversight: the one per-finding evidence pointer
       the producer publishes names a show-COMMAND, on 33 rows, and the snapshot keeps no raw
       command output — so it adds provenance to 33 findings and a route to literal configuration
       to none. No producer field links a finding to an interface, ACL line or config block. Two of
       the 33 (F106, F107) do land on literal text, but through the word-ranked MGMT_IN match that
       existed before this field — not through the citation. */
    const cited = fabric.findings.filter((f) => (f.sourceCommand ?? null) !== null);
    expect(cited.length, "findings whose producer row cites its source command").toBe(33);
    const citedLiteral = cited.filter((f) => {
      const hits = configEvidenceFor(f);
      return (hits.length > 0 ? hits : nearestConfigFor(f))[0]?.kind === "acl";
    });
    expect(citedLiteral.map((f) => f.id), "cited findings whose two-click record is literal text").toEqual(["F106", "F107"]);
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

describe("the nearest record is nearest by a stated measure, not by list order (A1)", () => {
  it("F099 ('L1 risk err-disabled on 6 switches') opens an err-disabled port, not the first port", () => {
    const f = fabric.findings.find((x) => x.id === "F099");
    expect(f, "precondition: F099 exists in the compiled data").toBeDefined();
    expect(configEvidenceFor(f!)).toEqual([]);
    const first = nearestConfigFor(f!)[0];
    expect(first?.kind).toBe("interface");
    if (first?.kind !== "interface") return;
    expect(first.record.status).toBe("err-disabled");
    // and it is one the host's own deductions tie to that state
    const dev = fabric.devices.find((d) => d.host === first.host);
    expect(dev?.deductions.some((d) => d.startsWith("err-disabled @ " + first.record.port))).toBe(true);
    expect(first.how).toMatch(/deductions name it/);
  });

  it("every matched landing is a record whose collected STATUS or the host's deductions the finding states", () => {
    let matched = 0;
    for (const f of fabric.findings) {
      if (configEvidenceFor(f).length > 0) continue;
      const first = nearestConfigFor(f)[0];
      if (first === undefined || first.kind !== "interface" || first.matched !== true) continue;
      matched++;
      expect(first.how, f.id).toMatch(/deductions name it|collected status/);
    }
    expect(matched, "precondition: at least one finding lands on a matched interface record").toBeGreaterThan(0);
  });

  it("an access list is never 'nearest' by list order: F004, F100 and F106 no longer all open core1's first list", () => {
    const firstAcl = Object.keys(fabric.acls["core1"] ?? {})[0];
    expect(firstAcl, "precondition: core1 holds collected access lists").toBeDefined();
    const land = (id: string) => {
      const f = fabric.findings.find((x) => x.id === id);
      expect(f, `precondition: ${id} exists`).toBeDefined();
      return nearestConfigFor(f!)[0];
    };
    // F106 ("VTY transport (telnet) … cleartext management") says "management"; MGMT_IN is that list.
    const f106 = land("F106");
    expect(f106?.label).toBe("core1 · MGMT_IN");
    expect(f106?.kind === "acl" && f106.matched).toBe(true);
    expect(f106?.how).toMatch(/“MGMT”, read as “management”/);
    // F004 (failing hardware) and F100 (single gateway) match nothing we hold: the landing must say so.
    for (const id of ["F004", "F100"]) {
      const first = land(id);
      expect(first?.label, id).not.toBe(`core1 · ${firstAcl}`);
      expect(first?.how, id).toMatch(/not ranked/);
    }
  });

  it("every unmatched nearest record says it is not ranked, and no matched one follows it", () => {
    for (const f of fabric.findings) {
      if (configEvidenceFor(f).length > 0) continue;
      let seenUnmatched = false;
      for (const t of nearestConfigFor(f)) {
        const matched = t.kind !== "route" && t.matched === true;
        if (!matched) {
          seenUnmatched = true;
          expect(t.how, f.id).toMatch(/not ranked/);
        } else {
          expect(seenUnmatched, `${f.id}: a matched record after an unranked one`).toBe(false);
        }
      }
    }
  });
});
