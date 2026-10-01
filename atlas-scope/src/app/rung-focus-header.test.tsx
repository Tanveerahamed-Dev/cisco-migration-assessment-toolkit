/**
 * rung-focus-header.test.tsx — the header's OWN fourth door, pinned without the frame around it
 * (acceptance D3, class D3-R2-1; independent verifier R5-V4).
 *
 * WHY A SEPARATE FILE. focus-return.ts's fourth door is global: the release it schedules acts on
 * whatever last held focus, whichever component declared the door. Mounted inside <App />, the
 * frame's own door (keyed on the rung) also covers every header swap at the 1024 px edge, so
 * removing `useReleaseFocusOnLayoutChange(compact)` from Header.tsx left every behavioural test
 * green — MEASURED by the verifier: 'Tests 13 passed (13)' in rung-focus-crossing.test.tsx with the
 * header's door commented out. Only the static guard (shape 5) held it. Here the header is mounted
 * ALONE, so its door is the only one that can hand focus on when its compact rung swaps the More
 * popover for the inline surface toolbar, and back.
 */
import { act, type ReactElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { useInvestigation } from "../core/store";
import { flushTurns } from "../test-support/act-turns";
import { Header } from "./Header";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const mounted: { root: Root; container: HTMLElement }[] = [];

function mountNode(node: ReactElement): HTMLElement {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  act(() => {
    root.render(node);
  });
  mounted.push({ root, container });
  return container;
}

/* The rem media queries are answered from a mutable width; `resize` is what the ladder re-reads. */
let width = 900;
const realMatchMedia = window.matchMedia;
function answerMedia(): void {
  window.matchMedia = ((q: string) => {
    let matches = true;
    for (const m of q.matchAll(/\((min|max)-width:\s*([\d.]+)rem\)/g)) {
      const bound = Number.parseFloat(m[2] as string) * 16;
      matches &&= m[1] === "min" ? width >= bound : width <= bound;
    }
    if (/prefers-reduced-motion/.test(q)) matches = false;
    return {
      matches,
      media: q,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    } as unknown as MediaQueryList;
  }) as typeof window.matchMedia;
}
function resizeTo(w: number): void {
  width = w;
  act(() => {
    window.dispatchEvent(new Event("resize"));
  });
}
const settle = (): Promise<void> => flushTurns(20, 8);

async function mountHeaderAt(w: number): Promise<HTMLElement> {
  width = w;
  answerMedia();
  const c = mountNode(<Header />);
  await settle();
  return c;
}

const focusOn = (el: HTMLElement | null | undefined, what: string): HTMLElement => {
  expect(el ?? null, `precondition: ${what} is rendered`).not.toBeNull();
  act(() => {
    el!.focus();
  });
  expect(document.activeElement, `precondition: focus is on ${what}`).toBe(el);
  return el!;
};
const where = (): string => {
  const a = document.activeElement;
  if (a === null || a === document.body) return "BODY";
  return `${a.tagName}.${(a as HTMLElement).className} "${(a.getAttribute("aria-label") ?? a.textContent ?? "").trim().slice(0, 40)}"`;
};

beforeEach(() => {
  act(() => {
    useInvestigation.setState(useInvestigation.getInitialState(), true);
  });
});

afterEach(() => {
  for (const m of mounted.splice(0)) {
    act(() => {
      m.root.unmount();
    });
    m.container.remove();
  }
  document.body.innerHTML = "";
  window.matchMedia = realMatchMedia;
  act(() => {
    useInvestigation.setState(useInvestigation.getInitialState(), true);
  });
});

describe("the header alone: its compact swap hands focus on through its own fourth door", () => {
  it("900 -> 1100 with focus on More: More unmounts, focus lands on the inline surface toolbar", async () => {
    const c = await mountHeaderAt(900);
    expect(c.querySelector(".app"), "precondition: no frame (and so no other layout door) is mounted").toBeNull();
    focusOn(c.querySelector<HTMLElement>("button.hdr-more"), "the More button");
    resizeTo(1100);
    await settle();
    expect(c.querySelector("button.hdr-more"), "precondition: More is gone above the compact rung").toBeNull();
    const surfaces = c.querySelector(".hdr-surfaces");
    expect(surfaces, "precondition: the inline surface toolbar rendered").not.toBeNull();
    expect(surfaces!.contains(document.activeElement), `focus is not on the inline surface toolbar (${where()})`).toBe(true);
  });

  it("1100 -> 900 with focus on an inline surface button: it leaves, focus lands on More", async () => {
    const c = await mountHeaderAt(1100);
    const findings = [...c.querySelectorAll<HTMLElement>(".hdr-surfaces button")].find((b) => (b.textContent ?? "").startsWith("Findings"));
    focusOn(findings, "the inline Findings button");
    resizeTo(900);
    await settle();
    expect(document.activeElement, `focus did not land on More (${where()})`).toBe(c.querySelector("button.hdr-more"));
  });

  it("1100 -> 900 with focus on the inline Copy-link button: it moves into the popover, focus lands on More", async () => {
    const c = await mountHeaderAt(1100);
    focusOn(c.querySelector<HTMLElement>('button[aria-label="Copy the link to this investigation"]'), "the inline Copy-link button");
    resizeTo(900);
    await settle();
    expect(document.activeElement, `focus did not land on More (${where()})`).toBe(c.querySelector("button.hdr-more"));
  });
});
