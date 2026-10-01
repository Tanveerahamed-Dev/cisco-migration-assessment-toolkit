/**
 * FabricA11yTree.parity.test.tsx — each tree gesture drives exactly what the SAME canvas gesture does.
 *
 * A11y audit D6 (2026-09-21): tree Enter and a single canvas click left the same application state
 * but different cameras, because Enter also framed the device. The canvas has two gestures (click
 * selects; double-click or Enter on the stage selects and frames — Fabric3D.tsx), and so does the
 * tree. What was missing was a statement of the mapping; this file pins both the mapping and the
 * statement, so neither can drift from the other.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { fabric } from "../core/data";
import { useInvestigation } from "../core/store";
import { FabricA11yTree, TREE_GESTURES } from "./FabricA11yTree";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

let root: Root | null = null;
let host: HTMLElement | null = null;
const onFocusDevice = vi.fn<(id: string) => void>();

beforeEach(() => {
  useInvestigation.getState().reset();
  onFocusDevice.mockReset();
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  act(() =>
    root!.render(
      <FabricA11yTree
        devices={fabric.devices}
        links={fabric.links}
        tiers={[fabric.devices.map((d) => d.host)]}
        visible
        onHide={() => {}}
        onFocusDevice={onFocusDevice}
      />,
    ),
  );
});

afterEach(() => {
  act(() => root?.unmount());
  host?.remove();
  root = null;
  host = null;
});

function deviceRow(): HTMLElement {
  const row = host!.querySelector<HTMLElement>('[data-testid="fabric3d-tree-device"]');
  expect(row).not.toBeNull();
  return row!;
}

function key(el: HTMLElement, k: string): void {
  // Two acts: focus makes the row the roving active row, and the keydown handler reads that.
  act(() => el.focus());
  act(() => {
    el.dispatchEvent(new KeyboardEvent("keydown", { key: k, bubbles: true }));
  });
}

describe("tree gestures mirror canvas gestures", () => {
  it("click selects without moving the camera, like a canvas click", () => {
    const row = deviceRow();
    act(() => row.click());
    expect(useInvestigation.getState().deviceId).toBe(row.dataset.target);
    expect(onFocusDevice).not.toHaveBeenCalled();
  });

  it("Space selects without moving the camera, like a canvas click", () => {
    const row = deviceRow();
    key(row, " ");
    expect(useInvestigation.getState().deviceId).toBe(row.dataset.target);
    expect(onFocusDevice).not.toHaveBeenCalled();
  });

  it("Enter selects and frames, like a canvas double-click or Enter on the stage", () => {
    const row = deviceRow();
    key(row, "Enter");
    expect(useInvestigation.getState().deviceId).toBe(row.dataset.target);
    expect(onFocusDevice).toHaveBeenCalledWith(row.dataset.target);
  });

  it("double-click selects and frames, like a canvas double-click", () => {
    const row = deviceRow();
    act(() => row.dispatchEvent(new MouseEvent("dblclick", { bubbles: true })));
    expect(useInvestigation.getState().deviceId).toBe(row.dataset.target);
    expect(onFocusDevice).toHaveBeenCalledWith(row.dataset.target);
  });

  it("states the mapping to every user and wires it as the tree's description", () => {
    const tree = host!.querySelector<HTMLElement>('[role="tree"]')!;
    const id = tree.getAttribute("aria-describedby");
    expect(id).toBeTruthy();
    const desc = document.getElementById(id!);
    expect(desc?.textContent).toBe(TREE_GESTURES);
    for (const phrase of ["Click or Space selects", "Double-click or Enter selects and frames"]) {
      expect(TREE_GESTURES).toContain(phrase);
    }
  });
});
