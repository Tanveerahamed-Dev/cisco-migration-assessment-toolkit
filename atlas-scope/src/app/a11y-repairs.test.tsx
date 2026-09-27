/**
 * a11y-repairs.test.tsx — regressions for three independently-found accessibility defects.
 *
 *  D1  WCAG 2.1.4: every single-character binding can be turned off, and "off" is enforced over the
 *      CLASS (derived from each binding's spec), not over a list of keys.
 *  D3  A modal makes the page behind it inert — except live regions — and releases it on close.
 *  D6  Enter on a link under one endpoint keeps focus and selection on THAT copy of the link.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { actAsync } from "../test-support/act-turns";
import { afterEach, describe, expect, it, vi } from "vitest";

import { fabric } from "../core/data";
import { useInvestigation } from "../core/store";
import { FabricA11yTree } from "../fabric3d/FabricA11yTree";
import { Dialog } from "../ui/primitives";
import {
  installKeyboardManager,
  isCharacterKeyBinding,
  registerShortcuts,
  setCharacterKeyShortcuts,
} from "./keyboard";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const press = (key: string, init: KeyboardEventInit = {}): void => {
  document.body.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true, ...init }));
};

describe("D1 — single-character shortcuts can be turned off (WCAG 2.1.4)", () => {
  afterEach(() => setCharacterKeyShortcuts(true));

  it("classifies bindings from their spec", () => {
    for (const k of ["d", "?", "[", "g f", "shift+v"]) expect(isCharacterKeyBinding(k), k).toBe(true);
    for (const k of ["mod+k", "escape", "mod+\\", "alt+d", "arrowdown"]) expect(isCharacterKeyBinding(k), k).toBe(false);
  });

  it("off silences every character binding, including sequences, and leaves modifier chords alone", () => {
    const hits: string[] = [];
    const release = registerShortcuts([
      { id: "t.d", keys: "d", scope: "global", label: "d", group: "t", run: () => hits.push("d") },
      { id: "t.gf", keys: "g f", scope: "global", label: "g f", group: "t", run: () => hits.push("g f") },
      { id: "t.k", keys: "mod+k", scope: "global", label: "k", group: "t", run: () => hits.push("mod+k") },
    ]);
    const uninstall = installKeyboardManager();
    try {
      press("d");
      press("g");
      press("f");
      expect(hits).toEqual(["d", "g f"]);

      hits.length = 0;
      setCharacterKeyShortcuts(false);
      press("d");
      press("g");
      press("f");
      press("k", { ctrlKey: true, metaKey: false });
      press("k", { metaKey: true });
      expect(hits.filter((h) => h !== "mod+k")).toEqual([]);
      expect(hits).toContain("mod+k");
    } finally {
      uninstall();
      release();
    }
  });
});

describe("D3 — a modal makes the page behind it inert", () => {
  /* The page is made inert on the first task after the dialog is presented (perf audit E3, J5 —
     see Dialog in ui/primitives.tsx), so the check waits one frame and one task for it. */
  const afterFirstPaint = (): Promise<void> =>
    actAsync(async () => {
      await new Promise<void>((r) => (typeof requestAnimationFrame === "function" ? requestAnimationFrame(() => r()) : r()));
      await new Promise<void>((r) => setTimeout(r, 0));
    });

  it("inerts everything outside the dialog except live regions, and releases on close", async () => {
    const page = document.createElement("div");
    page.innerHTML =
      '<main><button id="behind">behind</button></main><div id="live" role="status" aria-live="polite"></div>';
    document.body.appendChild(page);
    const mount = document.createElement("div");
    document.body.appendChild(mount);
    const root: Root = createRoot(mount);
    try {
      act(() =>
        root.render(
          <Dialog open onClose={() => {}} title="Modal">
            <button type="button">inside</button>
          </Dialog>,
        ),
      );
      const dialog = document.querySelector('[role="dialog"][aria-modal="true"]');
      expect(dialog).not.toBeNull();
      /* Focus is inside the dialog at once, whatever the inert timing. */
      expect(dialog!.contains(document.activeElement)).toBe(true);
      await afterFirstPaint();
      expect(dialog!.closest("[inert]")).toBeNull();
      expect(page.querySelector("main")!.closest("[inert]")).not.toBeNull();
      expect(page.querySelector("#live")!.closest("[inert]")).toBeNull();

      act(() => root.render(<Dialog open={false} onClose={() => {}} title="Modal">x</Dialog>));
      expect(document.querySelectorAll("[inert]").length).toBe(0);
    } finally {
      act(() => root.unmount());
      mount.remove();
      page.remove();
    }
  });

  it("a dialog closed before the page was made inert leaves nothing inert, then or later", async () => {
    const page = document.createElement("div");
    page.innerHTML = '<main><button id="behind2">behind</button></main>';
    document.body.appendChild(page);
    const mount = document.createElement("div");
    document.body.appendChild(mount);
    const root: Root = createRoot(mount);
    try {
      act(() =>
        root.render(
          <Dialog open onClose={() => {}} title="Modal">
            <button type="button">inside</button>
          </Dialog>,
        ),
      );
      act(() => root.render(<Dialog open={false} onClose={() => {}} title="Modal">x</Dialog>));
      await afterFirstPaint();
      expect(document.querySelectorAll("[inert]").length).toBe(0);
    } finally {
      act(() => root.unmount());
      mount.remove();
      page.remove();
    }
  });
});

describe("D6 — a link selected under one endpoint keeps the reader's place", () => {
  it("Enter on the second copy of a link leaves focus and selection on that copy", () => {
    useInvestigation.getState().reset();
    const host = document.createElement("div");
    document.body.appendChild(host);
    const root = createRoot(host);
    try {
      act(() =>
        root.render(
          <FabricA11yTree
            devices={fabric.devices}
            links={fabric.links}
            tiers={[fabric.devices.map((d) => d.host)]}
            visible
            onHide={() => {}}
            onFocusDevice={vi.fn()}
          />,
        ),
      );
      // A link whose two endpoints both have rows: pick the copy that is NOT first in model order.
      const link = fabric.links.find(
        (l) => fabric.devices.some((d) => d.host === l.a) && fabric.devices.some((d) => d.host === l.b),
      );
      expect(link).toBeDefined();
      const ends = [link!.a, link!.b].sort((x, y) => x.localeCompare(y));
      const second = fabric.devices.find((d) => d.host === ends[1])!;
      const first = fabric.devices.find((d) => d.host === ends[0])!;
      const devRow = (id: string) =>
        [...host.querySelectorAll<HTMLElement>('[data-testid="fabric3d-tree-device"]')].find(
          (r) => r.dataset.target === id,
        )!;

      act(() => devRow(second.id).focus());
      act(() => devRow(second.id).dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true })));
      const copy = [...host.querySelectorAll<HTMLElement>('[data-testid="fabric3d-tree-link"]')].find(
        (r) => r.dataset.target === link!.id && r.id.includes(`device:${second.id}/`),
      )!;
      expect(copy).toBeDefined();
      act(() => copy.focus());
      act(() => copy.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true })));

      expect(useInvestigation.getState().linkId).toBe(link!.id);
      expect(document.activeElement).toBe(copy);
      expect(copy.getAttribute("aria-selected")).toBe("true");
      expect(copy.tabIndex).toBe(0);
      // The other endpoint was not expanded on the reader's behalf.
      expect(devRow(first.id).getAttribute("aria-expanded")).toBe("false");
    } finally {
      act(() => root.unmount());
      host.remove();
    }
  });
});
