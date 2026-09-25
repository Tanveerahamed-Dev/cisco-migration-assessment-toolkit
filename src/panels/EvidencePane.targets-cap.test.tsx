/**
 * EvidencePane.targets-cap.test.tsx — step 4 never states a count it does not show, and never cuts
 * an access list.
 *
 * 2026-09-22 critic, A1: step 4 read "The 10 records below…" over a silent `targets.slice(0, 8)`,
 * and the two records cut for F001 were MGMT_IN and INET_RETURN — access lists, the only record kind
 * that carries literal configuration text. These tests render the real pane over the real compiled
 * snapshot, for every finding, and also exercise the stated cap and its reveal.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";
import { fabric } from "../core/data";
import { useInvestigation } from "../core/store";
import { configEvidenceFor, EvidencePane, nearestConfigFor } from "./EvidencePane";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const mounted: { root: Root; container: HTMLElement }[] = [];

function mountFor(findingId: string): HTMLElement {
  act(() => {
    useInvestigation.getState().reset();
    useInvestigation.getState().selectFinding(findingId);
  });
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

const targetsOf = (id: string) => {
  const f = fabric.findings.find((x) => x.id === id)!;
  const named = configEvidenceFor(f);
  return named.length > 0 ? named : nearestConfigFor(f);
};
const buttonsIn = (c: HTMLElement): string[] =>
  [...c.querySelectorAll<HTMLElement>(".ev-cfgactions > button")].map((b) => b.textContent ?? "");

describe("step 4's record list", () => {
  it("F001 shows every access list core1 holds, MGMT_IN and INET_RETURN included", () => {
    const c = mountFor("F001");
    const shown = buttonsIn(c);
    for (const acl of Object.keys(fabric.acls["core1"] ?? {})) {
      expect(shown.some((b) => b.includes(`core1 · ${acl}`)), acl).toBe(true);
    }
  });

  /* EVERY FINDING, ONE TEST EACH (acceptance report F2, 2026-09-23). This was one test mounting the
     real pane for every finding in a loop: 13.5-15.7 s on a green full-suite run and a timeout at
     30 s on a loaded one, so its limit could not tell a hang from a busy host. The cost is React-dev
     + jsdom per mount, not the product's ranking (see EvidencePane.source.test.tsx), so the claim is
     kept whole — every finding with records, each in the real pane — and split one finding per
     test. The cross-finding precondition (at least one list is capped) is gathered as they run and
     asserted after them, together with a count proving every one of them ran. */
  const withTargets = fabric.findings.filter((f) => targetsOf(f.id).length > 0).map((f) => f.id);
  /* SPLIT BY WHAT EACH CASE CAN PROVE (repair wave 7, O38's F2 note). The single per-finding test was
     named "every access list is on screen, and a shorter list states the cap in words", but most
     findings' records hold no access list, so for them the on-screen half asserted over nothing —
     measured at 6a5d830: 116 of 145 cases made exactly one assertion, the cap's. The access-list claim
     now runs over the findings that HAVE access lists, and each case asserts it judged at least one;
     the cap claim runs over every finding with records, and says only that. */
  const withAcls = withTargets.filter((id) => targetsOf(id).some((t) => t.kind === "acl"));
  let aclVisited = 0;
  let capVisited = 0;
  let capped = 0;

  it("the snapshot has findings with records, and findings whose records include an access list (the per-finding tests below are over these lists)", () => {
    expect(withTargets.length).toBeGreaterThan(0);
    expect(withAcls.length, "precondition: a finding whose records include an access list").toBeGreaterThan(0);
  });

  it.each(withAcls)("%s: every one of its access lists is on screen", (id) => {
    const acls = targetsOf(id).filter((t) => t.kind === "acl");
    expect(acls.length, `${id}: selected because it holds an access list`).toBeGreaterThan(0);
    const shown = buttonsIn(mountFor(id));
    const missing = acls.filter((t) => !shown.some((b) => b.includes(t.label))).map((t) => t.label);
    expect(missing, `${id}: access lists cut from step 4's list`).toEqual([]);
    aclVisited += 1;
  });

  it.each(withTargets)("%s: a list shorter than its records states the cap in words, and a whole list states none", (id) => {
    const targets = targetsOf(id);
    const c = mountFor(id);
    const shown = buttonsIn(c);
    const cap = c.querySelector(".ev-cfgactions__cap")?.textContent ?? null;
    if (shown.length < targets.length) {
      capped += 1;
      expect(cap, id).toContain(`Showing ${shown.length} of ${targets.length}`);
    } else {
      expect(shown.length, `${id}: more buttons than records`).toBe(targets.length);
      expect(cap, id).toBeNull();
    }
    capVisited += 1;
  });

  it("precondition, over all of the above: every case ran, and at least one finding holds more records than the cap", () => {
    expect(aclVisited, "every access-list case above ran and passed (a filtered or failed run proves nothing here)").toBe(withAcls.length);
    expect(capVisited, "every cap case above ran and passed (a filtered or failed run proves nothing here)").toBe(withTargets.length);
    expect(capped, "precondition: at least one finding holds more records than the cap").toBeGreaterThan(0);
  });

  it("the cap is reversible: 'Show all' reveals every record", () => {
    const f = fabric.findings.find((x) => targetsOf(x.id).filter((t) => t.kind !== "acl").length > 8);
    expect(f, "precondition: a finding with more than 8 non-ACL records").toBeDefined();
    const c = mountFor(f!.id);
    const more = [...c.querySelectorAll<HTMLElement>(".ev-cfgactions__cap button")].find((b) => b.textContent?.startsWith("Show all"));
    expect(more).toBeDefined();
    act(() => more!.dispatchEvent(new MouseEvent("click", { bubbles: true })));
    expect(buttonsIn(c)).toHaveLength(targetsOf(f!.id).length);
    expect(c.querySelector(".ev-cfgactions__cap")).toBeNull();
  });
});
