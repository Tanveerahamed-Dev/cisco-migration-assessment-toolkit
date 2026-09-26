/**
 * Header.focus-return.test.tsx — acceptance D3 regression: Escape in the query bar never drops
 * focus to <body>.
 *
 * MEASURED (acceptance-report D3, 2 of 2): open the snapshot popover, press Tab, press Escape; one
 * second later `document.activeElement` was BODY. Tab off the popover's last control closes the
 * popover and moves focus to the next tab stop after the trigger — the query input — so the input's
 * `focus` event records the popover's Copy button as where focus came FROM. The popover then
 * unmounts, the recorded target is disconnected, and the Escape handler's else-arm called
 * `blur()`. Focus must instead go to the element that opened the surface (the snapshot trigger).
 *
 * Keys are dispatched so they reach the listener that owns them: the popover's Tab handler is a
 * capture listener on `document`, so Tab is dispatched ON document (a dispatch on `window` would
 * exercise nothing, R11). Escape belongs to the input's React handler, which only sees an event
 * whose target is the input; it is dispatched there and bubbles through document like a real key.
 */
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useInvestigation } from "../core/store";
import { Header } from "./Header";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const mounted: { root: Root; container: HTMLElement }[] = [];

function mount(ui: ReactNode): HTMLElement {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  act(() => root.render(ui));
  mounted.push({ root, container });
  return container;
}

const key = (target: EventTarget, k: string, init: KeyboardEventInit = {}): void => {
  act(() => {
    target.dispatchEvent(new KeyboardEvent("keydown", { key: k, bubbles: true, cancelable: true, ...init }));
  });
};

beforeEach(() => {
  useInvestigation.getState().reset();
  /* jsdom lays nothing out, so every element reports zero client rects and the popover's
     "next VISIBLE tab stop after the trigger" search finds nothing. Give every element one rect so
     the real Tab path runs, exactly as it does in a browser. */
  vi.spyOn(HTMLElement.prototype, "getClientRects").mockImplementation(
    () => [{ x: 0, y: 0, width: 10, height: 10 }] as unknown as DOMRectList,
  );
});

afterEach(() => {
  for (const m of mounted.splice(0)) {
    act(() => m.root.unmount());
    m.container.remove();
  }
  vi.restoreAllMocks();
  document.body.innerHTML = "";
});

describe("D3: Escape in the query bar never drops focus to <body>", () => {
  it("snapshot popover, then Tab, then Escape returns focus to the popover's trigger", () => {
    const c = mount(<Header />);
    const trigger = c.querySelector<HTMLButtonElement>(".hdr-snap")!;
    const input = c.querySelector<HTMLInputElement>(".hdr-query__input")!;
    act(() => trigger.click());

    const panel = document.querySelector('[role="dialog"][aria-label="Snapshot provenance"]');
    expect(panel).not.toBeNull();
    expect(panel!.contains(document.activeElement)).toBe(true);

    /* Tab until focus leaves the panel (it holds one or more controls). */
    for (let i = 0; i < 10 && panel!.isConnected && panel!.contains(document.activeElement); i += 1) {
      key(document, "Tab");
    }
    expect(document.querySelector('[role="dialog"][aria-label="Snapshot provenance"]')).toBeNull();
    expect(document.activeElement).toBe(input);

    key(document.activeElement!, "Escape");
    expect(document.activeElement).not.toBe(document.body);
    expect(document.activeElement).toBe(trigger);
  });

  it("Escape with no recorded origin still never lands on <body>", () => {
    const c = mount(<Header />);
    const input = c.querySelector<HTMLInputElement>(".hdr-query__input")!;
    act(() => input.focus()); // arrived from nowhere: relatedTarget is null
    key(input, "Escape");
    expect(document.activeElement).not.toBe(document.body);
    expect(document.activeElement).not.toBe(input);
  });

  it("Escape returns to a recorded origin that is still connected (the existing contract)", () => {
    const c = mount(<Header />);
    const input = c.querySelector<HTMLInputElement>(".hdr-query__input")!;
    const origin = document.createElement("button");
    document.body.appendChild(origin);
    act(() => origin.focus());
    act(() => input.focus());
    key(input, "Escape");
    expect(document.activeElement).toBe(origin);
  });
});
