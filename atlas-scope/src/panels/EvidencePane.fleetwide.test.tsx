/**
 * EvidencePane.fleetwide.test.tsx — a finding about the whole fleet is not a collection gap.
 *
 * F142 ("No QoS configured anywhere") is the only finding in this snapshot that names no device.
 * Its evidence is an ABSENCE observed across every assessable device: configuration WAS collected
 * on all of them, and the finding is precisely that none of them carries a QoS policy.
 *
 * The pane rendered it as:
 *
 *   configuration evidence: not observed — no access list, interface record or route entry was
 *   collected for the hosts this finding names
 *
 * That sentence is false twice. The finding names no hosts, and the configuration it rests on was
 * collected. It turns a conclusion drawn from a complete sweep into a statement that we are missing
 * data — the same model-gap-as-collection-gap defect already fixed once in the compiler, where the
 * application told users that object-group members "were not collected" while the source file held
 * them. It is the more damaging direction of the error: it sends an engineer to collect evidence
 * the snapshot already contains, and it quietly weakens a finding that is actually well-founded.
 *
 * These tests render the real pane against the real compiled snapshot.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";
import { fabric, findingById } from "../core/data";
import { useInvestigation } from "../core/store";
import { describeGolden } from "../test-support/golden-sample";
import { EvidencePane } from "./EvidencePane";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const mounted: { root: Root; container: HTMLElement }[] = [];

function mountFor(findingId: string): HTMLElement {
  useInvestigation.getState().reset();
  useInvestigation.getState().selectFinding(findingId);
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  act(() => root.render(<EvidencePane onOpenCite={() => {}} onShowConfig={() => {}} />));
  mounted.push({ root, container });
  return container;
}

afterEach(() => {
  for (const m of mounted.splice(0)) {
    act(() => m.root.unmount());
    m.container.remove();
  }
});

/* Derived from the data rather than hard-coded, so the suite still points at the right record if
   the snapshot changes — and fails loudly if there stops being one to point at. */
const fleetWide = fabric.findings.filter((f) => f.devices.length === 0);

describe("a finding that names no device", () => {
  it("exists in this snapshot, so the assertions below are about something", () => {
    expect(fleetWide.length, "no device-less finding left to test — re-derive this suite").toBeGreaterThan(0);
  });

  it("never claims configuration was not COLLECTED for hosts it does not name", () => {
    for (const f of fleetWide) {
      const text = mountFor(f.id).textContent ?? "";
      expect(
        /was collected for the hosts this finding names/i.test(text),
        `${f.id} tells the reader configuration is missing for hosts it does not name`,
      ).toBe(false);
      expect(
        /no access list, interface record or route entry was collected/i.test(text),
        `${f.id} describes a fleet-wide conclusion as a collection gap`,
      ).toBe(false);
    }
  });

  it("says plainly that it is a conclusion across the fleet, not a quotation from one device", () => {
    for (const f of fleetWide) {
      const text = mountFor(f.id).textContent ?? "";
      expect(text, `${f.id} should explain why there is no single record to show`).toMatch(
        /across the (whole )?fleet|every assessable device|no single (device|record)/i,
      );
    }
  });

  it("still renders an explicit absence rather than a blank, so nothing reads as clean", () => {
    for (const f of fleetWide) {
      const c = mountFor(f.id);
      expect(
        c.querySelector('[data-unobserved="true"]'),
        `${f.id} has no configuration target and must still say so`,
      ).not.toBeNull();
    }
  });
});

describeGolden("the reference sample's fleet-wide finding", () => {
  it("is F137 ('No QoS configured anywhere')", () => {
    expect(fleetWide.map((f) => f.id)).toContain("F137");
  });
});

describe("the ordinary case is untouched", () => {
  it("a finding that DOES name a host with no collected configuration still reports the gap", () => {
    /* The fix must be scoped to the device-less case. Where a finding names hosts and we genuinely
       hold nothing for them, "not collected" is TRUE and must keep being said.

       The shipped snapshot has NO such finding (every host a finding names has at least one access
       list, interface record or route entry), so this test used to find nothing and `return`
       before its only `expect` — green while asserting nothing. The branch is exercised with a
       FIXTURE instead: a real finding cloned onto a host name the snapshot has never heard of,
       registered in the same `findingById` map the pane resolves selections through, and removed
       again afterwards. The precondition is asserted, not assumed, so the fixture cannot drift into
       exercising the other branch. */
    const base = fabric.findings.find((f) => f.devices.length > 0);
    expect(base, "no host-naming finding to clone").toBeDefined();
    const ghost = "zz-fixture-host-never-collected";
    expect(fabric.acls[ghost] ?? null).toBeNull();
    expect(fabric.interfaces[ghost]?.length ?? 0).toBe(0);
    expect(fabric.routes[ghost] ?? null).toBeNull();
    const fixture = { ...base!, id: "FIXTURE-GAP", devices: [ghost] };
    const registry = findingById as Map<string, (typeof fabric.findings)[number]>;
    registry.set(fixture.id, fixture);
    try {
      const c = mountFor(fixture.id);
      const text = c.textContent ?? "";
      expect(text).toContain(`no access list, interface record or route entry was collected for ${ghost}`);
      expect(text).not.toMatch(/across the (whole )?fleet/i);
      expect(c.querySelector('[data-unobserved="true"]')).not.toBeNull();
    } finally {
      registry.delete(fixture.id);
    }
  });
});
