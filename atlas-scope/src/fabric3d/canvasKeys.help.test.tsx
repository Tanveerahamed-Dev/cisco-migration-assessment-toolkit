/**
 * canvasKeys.help.test.tsx — the keyboard sheet lists the fabric canvas's keys, from the same table
 * the canvas handler resolves them from (acceptance D1).
 *
 * The "?" sheet (app/ShortcutHelp.tsx) is generated from the global shortcut registry, and the
 * canvas's own keys — arrow traversal, Enter, Home, zoom, and now orbit and pan — never reached that
 * registry, so the one place a lost user goes listed none of them. canvasKeys.ts is the table; this
 * pins that every row of it is on the sheet, with its keys drawn.
 */
import { act } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it } from "vitest";

import { ShortcutHelp } from "../app/ShortcutHelp";
import { setHelpOpen, shortcutText } from "../app/keyboard";
import { CANVAS_KEYS } from "./canvasKeys";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

describe("the keyboard sheet lists the fabric canvas keys (D1)", () => {
  it("every canvas key row — orbit and pan included — is on the sheet with its keys", () => {
    const host = document.createElement("div");
    document.body.appendChild(host);
    const root = createRoot(host);
    act(() => root.render(<ShortcutHelp />));
    act(() => setHelpOpen(true));
    const sheet = document.querySelector<HTMLElement>('[data-testid="kb-help-canvas"]');
    expect(sheet, "no canvas-keys section on the sheet").not.toBeNull();
    const text = sheet!.textContent ?? "";
    for (const k of CANVAS_KEYS) {
      expect(text, k.label).toContain(k.label);
      expect(text, `${k.label}: keys`).toContain(shortcutText(k.keys));
    }
    expect(CANVAS_KEYS.some((k) => k.action === "orbit")).toBe(true);
    expect(CANVAS_KEYS.some((k) => k.action === "pan")).toBe(true);
    act(() => setHelpOpen(false));
    act(() => root.unmount());
    host.remove();
  });
});
