/**
 * The phone canvas moved by exactly the query bar's lost sentence height when selection replaced
 * its wrapped empty statement with one chip. Pin the real state transition and accessibility of
 * the intrinsic reservation here. jsdom proves no pixel geometry; the unchanged hosted A6 browser
 * checks still have to prove selection/clear preserves the canvas origin at every viewport.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { fabric } from "../core/data";
import { useInvestigation } from "../core/store";
import { QueryBar } from "./App";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

let root: Root | null = null;
let container: HTMLDivElement | null = null;

beforeEach(() => {
  useInvestigation.getState().reset();
});
afterEach(() => {
  if (root !== null) act(() => root!.unmount());
  container?.remove();
  root = null;
  container = null;
});

function mount(): HTMLElement {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  act(() => root!.render(<QueryBar />));
  return container;
}

function statement(c: HTMLElement): HTMLParagraphElement {
  const p = c.querySelector<HTMLParagraphElement>(".qbar__empty");
  expect(p, "the complete snapshot statement supplies the intrinsic reservation").not.toBeNull();
  return p!;
}

function click(button: HTMLButtonElement | null | undefined, label: string): void {
  expect(button, `the actual active control ${label} must exist`).toBeTruthy();
  act(() => { button!.dispatchEvent(new MouseEvent("click", { bubbles: true })); });
}

function expectActiveStatement(p: HTMLParagraphElement): void {
  expect(p.hasAttribute("aria-hidden")).toBe(false);
  expect(p.hasAttribute("inert")).toBe(false);
  expect(p.hasAttribute("hidden"), "display:none would discard the intrinsic height").toBe(false);
  expect(p.textContent).toBe(
    `Nothing is selected and no filter is applied, so every record in this snapshot is in scope: all ${fabric.devices.length} devices and all ${fabric.findings.length} findings.`,
  );
}

describe("the query bar reserves its honest wrapped summary across selection and clear", () => {
  it("shows the complete whole-snapshot statement and mounts no inactive controls", () => {
    const c = mount();
    expectActiveStatement(statement(c));
    expect(c.querySelector(".qbar__selection")).toBeNull();
    expect(c.querySelector("button")).toBeNull();
  });

  for (const kind of ["device", "link"] as const) {
    it(`retains the same text-only reservation across ${kind} selection and actual deselection`, () => {
      const id = kind === "device" ? fabric.devices[0]?.id : fabric.links[0]?.id;
      expect(id, `the ${kind} positive control must name a real source record`).toBeTruthy();
      const c = mount();
      const p = statement(c);
      const text = p.textContent;
      act(() => {
        const s = useInvestigation.getState();
        if (kind === "device") s.selectDevice(id!);
        else s.selectLink(id!);
      });

      expect(statement(c)).toBe(p);
      expect(p.textContent).toBe(text);
      expect(p.getAttribute("aria-hidden"), "an active selection must not speak the whole-snapshot claim").toBe("true");
      expect(p.hasAttribute("inert"), "the bound focus owner makes the text reservation inactive").toBe(true);
      expect(p.hasAttribute("hidden"), "the inactive sentence still supplies layout, rather than display:none").toBe(false);
      expect(p.querySelector("button, input, a, [tabindex]"), "the reservation is text only").toBeNull();
      const group = c.querySelector<HTMLElement>('.qbar__tokens[role="group"]');
      expect(group?.textContent).toContain(`${kind} ${id}`);
      expect(c.querySelector(`#${group?.getAttribute("aria-labelledby")}`)?.textContent).toBe("Scope");
      for (const button of c.querySelectorAll("button")) {
        expect(button.closest('[aria-hidden="true"], [inert], [hidden]'), "every actual control remains active").toBeNull();
      }

      const removeLabel = `Deselect ${kind} ${id}`;
      click([...c.querySelectorAll("button")].find((b) => b.getAttribute("aria-label") === removeLabel), removeLabel);
      expect(statement(c)).toBe(p);
      expectActiveStatement(p);
      expect(c.querySelector(".qbar__selection")).toBeNull();
    });
  }

  it("keeps all query/filter text and real remove controls while Clear scope restores the same statement", () => {
    const c = mount();
    const p = statement(c);
    const query = "a long scope question with every word retained and no shortened substitute";
    act(() => {
      const s = useInvestigation.getState();
      s.setQuery(query);
      s.toggleSeverity("Critical");
      s.toggleRole("access");
      s.setOnlyUncollected(true);
    });
    const tokens = c.querySelector<HTMLElement>('.qbar__tokens[role="group"]')!;
    expect(tokens.textContent).toContain(query);
    expect(tokens.textContent).toContain("severity Critical");
    expect(tokens.textContent).toContain("role access");
    expect(tokens.textContent).toContain("only devices the collector never reached");
    expect([...tokens.querySelectorAll("button")].map((b) => b.getAttribute("aria-label"))).toEqual([
      "Remove the free-text query", "Remove the Critical severity filter", "Remove the access role filter",
      "Stop restricting to devices the collector never reached",
    ]);
    expect(statement(c)).toBe(p);
    expect(p.getAttribute("aria-hidden")).toBe("true");
    expect(p.hasAttribute("inert"), "the focus owner applies the same inactive state for filters").toBe(true);

    click(c.querySelector<HTMLButtonElement>(".qbar__clear"), "Clear scope");
    expect(statement(c)).toBe(p);
    expectActiveStatement(p);
    expect(c.querySelector("button")).toBeNull();
    expect(useInvestigation.getState().query).toBe("");
    expect(useInvestigation.getState().severities.size).toBe(0);
    expect(useInvestigation.getState().roles.size).toBe(0);
    expect(useInvestigation.getState().onlyUncollected).toBe(false);
  });
});
