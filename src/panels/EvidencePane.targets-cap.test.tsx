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

  it("for every finding, every access list is on screen and a shorter list states the cap in words", () => {
    let capped = 0;
    for (const f of fabric.findings) {
      const targets = targetsOf(f.id);
      if (targets.length === 0) continue;
      const c = mountFor(f.id);
      const shown = buttonsIn(c);
      for (const t of targets) {
        if (t.kind === "acl") expect(shown.some((b) => b.includes(t.label)), `${f.id}: ${t.label}`).toBe(true);
      }
      const cap = c.querySelector(".ev-cfgactions__cap")?.textContent ?? null;
      if (shown.length < targets.length) {
        capped += 1;
        expect(cap, f.id).toContain(`Showing ${shown.length} of ${targets.length}`);
      } else {
        expect(cap, f.id).toBeNull();
      }
      act(() => mounted.pop()!.root.unmount());
    }
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
