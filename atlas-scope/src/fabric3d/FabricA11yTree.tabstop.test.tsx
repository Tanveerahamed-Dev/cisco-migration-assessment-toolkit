/**
 * FabricA11yTree.tabstop.test.tsx — the fabric tree is ONE tab stop in every state it can reach.
 *
 * A roving-tabindex composite (APG tree view) must keep exactly one `tabIndex=0` item. The tree
 * derived its roving item as `activeKey ?? first visible row`, which only falls back when
 * `activeKey` is null. When `activeKey` named a row that is NOT among the rendered rows — a key the
 * model no longer contains after its inputs change, or a row hidden under a collapsed ancestor —
 * every item rendered `tabIndex=-1` and Tab skipped the whole tree (WCAG 2.1.1). Reported by the
 * wave-5 keyboard census (K3); the census did not render the tree open, so it could not see it.
 *
 * The fallback must be decided against the rows actually rendered, not against `null`.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { fabric } from "../core/data";
import { useInvestigation } from "../core/store";
import { FabricA11yTree } from "./FabricA11yTree";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

let root: Root | null = null;
let host: HTMLElement | null = null;

const render = (tiers: readonly (readonly string[])[]) =>
  act(() =>
    root!.render(
      <FabricA11yTree
        devices={fabric.devices}
        links={fabric.links}
        tiers={tiers}
        visible
        onHide={() => {}}
        onFocusDevice={() => {}}
      />,
    ),
  );

const tabStops = (): string[] =>
  [...host!.querySelectorAll<HTMLElement>('[role="treeitem"]')]
    .filter((el) => el.tabIndex === 0)
    .map((el) => el.id);

beforeEach(() => {
  useInvestigation.getState().reset();
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root?.unmount());
  host?.remove();
  root = null;
  host = null;
});

describe("the fabric tree keeps exactly one tab stop", () => {
  it("has one on first render (positive control)", () => {
    render([fabric.devices.map((d) => d.host)]);
    expect(host!.querySelectorAll('[role="treeitem"]').length).toBeGreaterThan(1);
    expect(tabStops()).toHaveLength(1);
  });

  it("still has one when the active row leaves the rendered rows (the model changed under it)", () => {
    // Active row starts as the first root, `tier:0`. Re-rendered with no tiers, every device falls
    // into the unobserved group and `tier:0` no longer exists — the active key is stale.
    render([fabric.devices.map((d) => d.host)]);
    expect(tabStops()).toHaveLength(1);
    render([]);
    expect(host!.querySelectorAll('[role="treeitem"]').length).toBeGreaterThan(0);
    expect(tabStops(), "a stale active key must not leave the tree with no tab stop").toHaveLength(1);
  });
});
