/**
 * App.test.tsx — the shell's own contracts.
 *
 * These are the properties nothing else can check, because they belong to the wiring rather than
 * to any one surface: the URL envelope, the scheduler that flushes it, and the error boundary's
 * containment.
 *
 * Two of them exist because the defect they describe was observed in the RUNNING application and
 * by no unit test: an animation-frame flush that never fires in a hidden tab, and a history
 * restore that left view fields behind. Both are named where they are asserted.
 *
 * No testing-library: React's own `act` over a real `createRoot` in jsdom, matching
 * `src/app/Header.test.tsx` and `src/ui/primitives.test.tsx`.
 */
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { actAsync } from "../test-support/act-turns";

import { fabric } from "../core/data";
import { useInvestigation } from "../core/store";
import { ErrorBoundary } from "./ErrorBoundary";
import { encodeUrl, readUrl, snapshotTag, URL_SCHEMA_VERSION, useUrlSync } from "./urlSync";

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

const click = (el: Element): void => {
  act(() => {
    el.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
  });
};

/** Let the flush scheduler's timeout run, inside `act` so the resulting render is flushed too. */
const settle = async (): Promise<void> => {
  await actAsync(async () => {
    await new Promise((r) => setTimeout(r, 20));
  });
};

beforeEach(() => {
  const s = useInvestigation.getState();
  s.reset();
  s.setSurface("fabric");
  s.setEvidenceTab("summary");
  s.setInspectorOpen(false);
});

afterEach(() => {
  for (const m of mounted.splice(0)) {
    act(() => m.root.unmount());
    m.container.remove();
  }
  vi.restoreAllMocks();
});

/* ══ the URL envelope ══════════════════════════════════════════════════════ */

describe("the link carries an envelope, and a link it cannot read is refused", () => {
  it("writes the schema version and the snapshot tag on every link", () => {
    useInvestigation.getState().selectFinding("F001");
    const p = new URLSearchParams(encodeUrl(useInvestigation.getState()));
    expect(p.get("v")).toBe(String(URL_SCHEMA_VERSION));
    expect(p.get("snap")).toBe(fabric.meta.sourceSha256.slice(0, 12));
    expect(p.get("f")).toBe("F001");
  });

  it("round-trips a full investigation through its own link", () => {
    const s = useInvestigation.getState();
    s.selectFinding("F001");
    s.selectDevice("core1");
    s.setQuery("severity:Critical");
    s.toggleSeverity("Critical");
    s.setEvidenceTab("routing");
    s.setFlow({ srcIp: "10.0.10.50", dstIp: "10.0.30.10", protocol: "tcp", dstPort: 3389, srcPort: null });

    const back = readUrl(encodeUrl(useInvestigation.getState()));
    expect(back.problem).toBeNull();
    expect(back.patch.findingId).toBe("F001");
    expect(back.patch.deviceId).toBe("core1");
    expect(back.patch.query).toBe("severity:Critical");
    expect(back.patch.evidenceTab).toBe("routing");
    expect([...(back.patch.severities ?? [])]).toEqual(["Critical"]);
    expect(back.patch.flow?.dstPort).toBe(3389);
  });

  it("refuses a link written in a schema version it does not implement, and applies NOTHING", () => {
    /* Partial credit is the dangerous outcome: a half-reconstructed investigation still looks like
       a successful reproduction, so the reader draws conclusions from a state the link never
       recorded. */
    const read = readUrl(`v=${URL_SCHEMA_VERSION + 1}&f=F001&d=core1`);
    expect(read.problem?.kind).toBe("unknown-version");
    expect(read.patch).toEqual({});
    expect(read.problem?.message).toContain("Nothing from it has been applied");
  });

  it("refuses a link minted against a different snapshot, and names both sides", () => {
    const read = readUrl(`v=${URL_SCHEMA_VERSION}&snap=000000000000&f=F001`);
    expect(read.problem?.kind).toBe("snapshot-mismatch");
    expect(read.patch).toEqual({});
    expect(read.problem?.message).toContain("000000000000");
    expect(read.problem?.message).toContain(snapshotTag());
  });

  it("accepts a link with no envelope at all as the current grammar", () => {
    // Hand-typed links are real. Refusing them would make the shortest useful URL an error.
    const read = readUrl("f=F001");
    expect(read.problem).toBeNull();
    expect(read.patch.findingId).toBe("F001");
  });

  it("the refusal gate is live — it accepts the envelope it claims to accept", () => {
    // A gate that refuses everything and a gate that refuses the right thing are indistinguishable
    // from the failing side alone.
    expect(readUrl(`v=${URL_SCHEMA_VERSION}&f=F001`).problem).toBeNull();
    expect(readUrl(`v=${URL_SCHEMA_VERSION}&snap=${snapshotTag()}&f=F001`).problem).toBeNull();
  });
});

/* ══ the flush scheduler ═══════════════════════════════════════════════════ */

function UrlSyncProbe(): null {
  useUrlSync();
  return null;
}

describe("the URL keeps tracking the investigation even when no frame is painted", () => {
  it("flushes through the timeout when requestAnimationFrame never fires", async () => {
    /* REGRESSION, observed in the running application: with the browser pane hidden, rAF was never
       called, the pending-flush guard stayed armed, and the address bar stopped mirroring the
       investigation for the rest of the session while the app kept working. A URL that silently
       stops being the investigation is the exact failure this module exists to prevent.

       So rAF is stubbed to a function that schedules nothing — which is what a hidden tab does. */
    const dropped = vi.spyOn(window, "requestAnimationFrame").mockImplementation(() => 1);
    const replace = vi.spyOn(window.history, "replaceState");
    const push = vi.spyOn(window.history, "pushState");

    mount(<UrlSyncProbe />);
    replace.mockClear();
    push.mockClear();

    act(() => { useInvestigation.getState().setQuery("severity:Critical"); });
    await settle();

    const urls = [...replace.mock.calls, ...push.mock.calls].map((c) => String(c[2]));
    expect(dropped).toHaveBeenCalled();
    expect(urls.some((u) => u.includes("q=severity%3ACritical"))).toBe(true);
  });

  it("a selection pushes a history entry; a keystroke replaces one", async () => {
    /* Design brief 5.4: Back must traverse investigative steps, not keystrokes. */
    const replace = vi.spyOn(window.history, "replaceState");
    const push = vi.spyOn(window.history, "pushState");
    mount(<UrlSyncProbe />);
    replace.mockClear();
    push.mockClear();

    act(() => { useInvestigation.getState().setQuery("core"); });
    await settle();
    const pushesAfterTyping = push.mock.calls.length;
    const replacesAfterTyping = replace.mock.calls.length;

    act(() => { useInvestigation.getState().selectDevice("core1"); });
    await settle();

    expect(pushesAfterTyping).toBe(0);
    expect(replacesAfterTyping).toBeGreaterThan(0);
    expect(push.mock.calls.length).toBe(1);
  });

  it("coalesces a burst of writes into one history entry", async () => {
    const push = vi.spyOn(window.history, "pushState");
    const replace = vi.spyOn(window.history, "replaceState");
    mount(<UrlSyncProbe />);
    push.mockClear();
    replace.mockClear();

    act(() => {
      const s = useInvestigation.getState();
      s.selectFinding("F001");
      s.selectDevice("core1");
      s.setEvidenceTab("ports");
    });
    await settle();

    expect(push.mock.calls.length + replace.mock.calls.length).toBe(1);
  });
});

/* ══ the error boundary ════════════════════════════════════════════════════ */

function Boom(): never {
  throw new Error("the renderer tripped over a null");
}

describe("a surface that throws costs that surface and nothing else", () => {
  beforeEach(() => {
    // React logs the caught error itself; the boundary logs the component stack. Neither is the
    // subject of these tests, and both would drown the run.
    vi.spyOn(console, "error").mockImplementation(() => {});
  });

  it("names the region, prints the error verbatim, and keeps its siblings mounted", () => {
    const c = mount(
      <div>
        <ErrorBoundary surface="The priority queue">
          <Boom />
        </ErrorBoundary>
        <p>the rest of the investigation</p>
      </div>,
    );

    const alert = c.querySelector('[role="alert"]');
    expect(alert?.textContent).toContain("The priority queue stopped rendering");
    expect(alert?.textContent).toContain("the renderer tripped over a null");
    expect(c.textContent).toContain("the rest of the investigation");
  });

  it("reports the failure to the frame, so it can reach the assertive live region", () => {
    const seen: string[] = [];
    mount(
      <ErrorBoundary surface="The path panel" onError={(where, err) => seen.push(`${where}: ${err.message}`)}>
        <Boom />
      </ErrorBoundary>,
    );
    expect(seen).toEqual(["The path panel: the renderer tripped over a null"]);
  });

  it("the retry control re-mounts the subtree rather than re-rendering the broken tree", () => {
    /* The failure is driven by a flag rather than a render counter: React re-invokes a throwing
       component in development to collect a better stack, so a "throw on the first render only"
       component recovers inside the same commit and the boundary is never exercised at all. That
       test would pass while proving nothing. */
    let failing = true;
    function FailsWhileFlagged(): ReactNode {
      if (failing) throw new Error("the record was not there yet");
      return <p>recovered content</p>;
    }
    const c = mount(
      <ErrorBoundary surface="The inspector">
        <FailsWhileFlagged />
      </ErrorBoundary>,
    );
    const retry = c.querySelector(".surface-error__retry");
    expect(retry).not.toBeNull();

    failing = false;
    if (retry) click(retry);
    expect(c.textContent).toContain("recovered content");
    expect(c.querySelector(".surface-error")).toBeNull();
  });

  it("passes children through untouched when nothing throws", () => {
    // The boundary sits on the render path of every surface; a wrapper element here would change
    // the layout of all of them to serve an error path that is normally idle.
    const c = mount(
      <ErrorBoundary surface="The stage">
        <p>fine</p>
      </ErrorBoundary>,
    );
    expect(c.innerHTML).toBe("<p>fine</p>");
  });

  it("its copy does not claim anything about the network", () => {
    /* The replacement text is about a RENDERER failure. Saying or implying that the data is
       absent would convert "we could not draw it" into "there is nothing there", which is the
       same lie in a different costume. */
    const c = mount(
      <ErrorBoundary surface="The priority queue">
        <Boom />
      </ErrorBoundary>,
    );
    const text = c.textContent ?? "";
    expect(text).toContain("What is missing here is the drawing of the data, not the data");
    expect(text).not.toMatch(/no data|nothing to show|empty/i);
  });
});
