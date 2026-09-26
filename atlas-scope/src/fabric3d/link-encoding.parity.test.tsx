/**
 * link-encoding.parity.test.tsx — the Fabric list row states every claim the cable's pattern draws
 * (independent acceptance report 2026-09-22, D6).
 *
 * THE DEFECT. Links L34 and L35 (core2 to AP-floor3-01 and to wan-edge-rtr1.lab) have NO observed
 * operational status. The fabric draws them with the state-unknown pattern (dotted, --state-unknown
 * — geometry/cables.ts), while their Fabric list row said only "centrality not computed". Both facts
 * are TRUE of the data (the snapshot's `isBridge` is null AND `opStatus` is "unknown"; the latter is
 * WHY the former: a link with no observed state is not in the connectivity graph, so nothing could
 * compute its centrality), but the row dropped the one the canvas shows, so a screen-reader user and
 * a sighted user were told different things about the same cable.
 *
 * The oracle is the DRAWN pattern, read back from `classifyLink` (the one owner of the pattern), and
 * the words each pattern means are fixed here by the legend's own vocabulary. Every link is checked,
 * not the two that were caught.
 */
import { act } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it } from "vitest";

import { fabric } from "../core/data";
import { FabricA11yTree, linkCutMeta } from "./FabricA11yTree";
import { classifyLink } from "./geometry/cables";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

/** What each drawn channel asserts, in the words a list row must carry for it. */
function drawnWords(v: ReturnType<typeof classifyLink>): string[] {
  const out: string[] = [];
  if (v.dash === "dotted") out.push("state not observed");
  if (v.dash === "dashed") out.push("state down");
  if (v.dash === "short") out.push("centrality not computed");
  if (v.doubled) out.push("cut partitions");
  return out;
}

describe("a link's Fabric list row states what its cable draws (D6)", () => {
  it("L34 and L35 — the audited pair — are drawn state-unknown and the row says so", () => {
    for (const id of ["L34", "L35"]) {
      const l = fabric.links.find((x) => x.id === id);
      if (!l) throw new Error(`the shipped snapshot has no ${id}; this test pins the audited case`);
      expect(l.opStatus, `${id} precondition`).toBe("unknown");
      expect(l.isBridge, `${id} precondition`).toBeNull();
      expect(classifyLink(l).dash, id).toBe("dotted");
      const meta = linkCutMeta(l);
      expect(meta.text, id).toContain("state not observed");
      // Both are true, so neither is dropped: the centrality gap is still named.
      expect(meta.text, id).toContain("centrality not computed");
      expect(meta.unobserved, id).toBe(true);
    }
  });

  it("every link's row carries every claim its drawn pattern makes", () => {
    let withClaims = 0;
    for (const l of fabric.links) {
      const words = drawnWords(classifyLink(l));
      if (words.length > 0) withClaims += 1;
      const text = linkCutMeta(l).text;
      for (const w of words) expect(text, `${l.id} is drawn "${w}" but its row reads "${text}"`).toContain(w);
    }
    expect(withClaims, "the sweep checked no drawn claim at all").toBeGreaterThan(0);
  });

  it("the rendered tree row for L34 is the same text (no second wording in the DOM)", () => {
    const host = document.createElement("div");
    document.body.appendChild(host);
    const root = createRoot(host);
    act(() =>
      root.render(
        <FabricA11yTree
          devices={fabric.devices}
          links={fabric.links}
          tiers={[fabric.devices.map((d) => d.host)]}
          visible
          onHide={() => {}}
          onFocusDevice={() => {}}
        />,
      ),
    );
    // Link rows sit under their device rows; expand core2 to reach L34.
    const core2 = host.querySelector<HTMLElement>('[data-testid="fabric3d-tree-device"][data-target="core2"]');
    expect(core2).not.toBeNull();
    act(() => core2!.focus());
    act(() => core2!.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true })));
    const rows = [...host.querySelectorAll<HTMLElement>('[data-testid="fabric3d-tree-link"][data-target="L34"]')];
    expect(rows.length).toBeGreaterThan(0);
    const l34 = fabric.links.find((x) => x.id === "L34")!;
    for (const r of rows) expect(r.querySelector(".fabric3d__tree-meta")?.textContent).toBe(linkCutMeta(l34).text);
    act(() => root.unmount());
    host.remove();
  });
});
