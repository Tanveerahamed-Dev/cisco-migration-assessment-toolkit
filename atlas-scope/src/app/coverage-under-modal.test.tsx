/**
 * coverage-under-modal.test.tsx — no overlay may take the coverage figures off the screen (B7).
 *
 * B7 asks for coverage "stated permanently and visibly": how many hosts were collected, how many
 * have RIBs, how many have ACLs. The status bar states it. MEASURED (acceptance report, re-grade of
 * 8eac055, and this cluster's own probe at 390, 320, 768, 1440 and 1920, light and dark): with the
 * Ctrl+K palette or the keyboard reference open, `elementFromPoint` over every figure returned the
 * dialog's scrim or its footer at EVERY width, and at 390/320 the priority queue's "Display" popover
 * sat over the whole group. None of those surfaces said the figures itself, so in those states
 * collected-host and ACL coverage were stated nowhere on screen.
 *
 * The owner's decision (wave 7): while any modal, dialog or popover is open, at every viewport, the
 * figures remain visible — the overlay leaves the bar uncovered, or the overlay states the same
 * figures read from the same owner. Geometry is not decidable in jsdom, so this file proves the
 * second branch for the whole class; `review`-style browser probing proves the pixels.
 *
 * THE CLASS IS DISCOVERED, NOT LISTED. Every source file that renders `<Dialog` or `<Popover` is
 * found by scanning `src`, and every overlay element rendered RAW (role=dialog/alertdialog,
 * aria-modal, the `popover` attribute, showModal) likewise. A consumer this file has no opener for
 * fails the completeness check below rather than being skipped, so a new overlay cannot arrive
 * untested.
 *
 * The oracle is the status bar ITSELF, mounted beside the overlay: the overlay must carry the very
 * strings the permanent line renders, and every segment of the owner's line (`T8_coverageLine`,
 * src/core/claims.ts). No figure is restated in this file.
 */
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { T8_coverageLine } from "../core/claims";
import { useInvestigation } from "../core/store";
import { ribCountQualifier } from "../forwarding/rib-completeness";
import { coverageFigures, Dialog, Popover, withRibQualifier } from "../ui/primitives";
import { CommandPalette } from "./CommandPalette";
import { useAppCommands } from "./commands";
import { Header } from "./Header";
import { clearPendingKeys, setHelpOpen } from "./keyboard";
import { ShortcutHelp } from "./ShortcutHelp";
import { StatusBar } from "./StatusBar";
import { PriorityQueue } from "../panels/PriorityQueue";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const SRC = join(dirname(fileURLToPath(import.meta.url)), "..");
const rel = (f: string): string => relative(SRC, f).split(sep).join("/");

/** Every authored TSX module under src — tests and `_scratch` paths excluded (vitest.config.ts). */
function sourceFiles(dir = SRC): string[] {
  const out: string[] = [];
  for (const name of readdirSync(dir)) {
    if (name.startsWith("_") || name === "node_modules") continue;
    const p = join(dir, name);
    if (statSync(p).isDirectory()) out.push(...sourceFiles(p));
    else if (name.endsWith(".tsx") && !/\.test\.tsx$/.test(name)) out.push(p);
  }
  return out;
}

const PRIMITIVES = "ui/primitives.tsx";
const CONSUMES = /<(Dialog|Popover)\b/;
const RAW_OVERLAY = /role=["{]?["'`]?(?:dialog|alertdialog)\b|aria-modal=|\spopover=|\.showModal\(/;

const files = sourceFiles().map((f) => ({ file: rel(f), text: readFileSync(f, "utf8") }));
const consumers = files.filter((f) => f.file !== PRIMITIVES && CONSUMES.test(f.text)).map((f) => f.file).sort();
const rawOverlays = files.filter((f) => f.file !== PRIMITIVES && RAW_OVERLAY.test(f.text)).map((f) => f.file).sort();

/* ── mounting ─────────────────────────────────────────────────────────────── */

const mounted: { root: Root; container: HTMLElement }[] = [];
function mount(ui: ReactNode): HTMLElement {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  act(() => root.render(ui));
  mounted.push({ root, container });
  return container;
}

const press = (key: string, init: KeyboardEventInit = {}): void => {
  act(() => {
    document.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true, ...init }));
  });
};
const MOD: KeyboardEventInit = /mac|iphone|ipad/i.test(navigator.platform || navigator.userAgent) ? { metaKey: true } : { ctrlKey: true };
const click = (el: Element): void => {
  act(() => {
    el.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
  });
};

beforeEach(() => {
  useInvestigation.getState().reset();
  useInvestigation.getState().setPaletteOpen(false);
  act(() => setHelpOpen(false));
  clearPendingKeys();
});

afterEach(() => {
  act(() => setHelpOpen(false));
  act(() => useInvestigation.getState().setPaletteOpen(false));
  for (const m of mounted.splice(0)) {
    act(() => m.root.unmount());
    m.container.remove();
  }
  document.body.innerHTML = "";
  clearPendingKeys();
});

/** The app's own wiring (commands + keyboard), the permanent line, and the consumer under test. */
function Harness({ children }: { children?: ReactNode }): ReactNode {
  useAppCommands();
  return (
    <>
      {children}
      <StatusBar />
    </>
  );
}

const norm = (s: string | null | undefined): string => (s ?? "").replace(/\s+/g, " ").trim();

/** The three figures B7 names, as the permanent status line renders them right now. */
function statusFigures(): string[] {
  const group = document.querySelector('#status-bar [role="group"][aria-label="Collection coverage"]');
  const figs = [...(group?.querySelectorAll(".sb__cov") ?? [])].map((b) => norm(b.textContent));
  const find = (re: RegExp): string => {
    const hit = figs.find((t) => re.test(t));
    if (hit === undefined) throw new Error(`the status bar renders no figure matching ${re} (read: ${JSON.stringify(figs)})`);
    return hit;
  };
  return [find(/^\d+\/\d+ collected$/), find(/^RIBs \d+\/\d+/), find(/^ACLs \d+\/\d+$/)];
}

/** Every open overlay element in the document (portalled to <body>), excluding the status bar's. */
const openOverlays = (): HTMLElement[] =>
  [...document.querySelectorAll<HTMLElement>('[role="dialog"], [role="alertdialog"], [aria-modal="true"], [popover]')].filter(
    (el) => el.closest("#status-bar") === null,
  );

/** What an overlay must carry: the status bar's own strings and every segment of the owner's line. */
function expectStatesCoverage(overlay: HTMLElement, where: string): void {
  const statement = overlay.querySelector<HTMLElement>("[data-overlay-coverage]");
  expect(statement, `${where}: the open overlay states no coverage line`).not.toBeNull();
  const text = norm(statement?.textContent);
  for (const f of statusFigures()) expect(text, `${where}: status-bar figure "${f}" is not stated`).toContain(f);
  for (const seg of T8_coverageLine().split(" · ")) expect(text, `${where}: owner segment "${seg}" is not stated`).toContain(seg);
  // Reading the figures must cost no tab stop (D1/D3): the statement is prose, never a control.
  expect(statement?.querySelectorAll("a, button, input, select, textarea, [tabindex]").length ?? 0, `${where}: tab stop in the statement`).toBe(0);
}

/* ── how each discovered consumer opens its overlays ─────────────────────────
   Keyed by the DISCOVERED file. The completeness check below fails when a consumer appears that is
   not keyed here, so this table cannot silently fall behind the class it covers. */

type Opener = () => { opened: number };

const clickEveryPopoverTrigger = (root: HTMLElement, where: string): { opened: number } => {
  const triggers = [...root.querySelectorAll<HTMLElement>('[aria-haspopup="dialog"]')];
  for (const t of triggers) {
    click(t);
    const open = openOverlays();
    expect(open.length, `${where}: "${t.getAttribute("aria-label") ?? norm(t.textContent)}" opened nothing`).toBeGreaterThan(0);
    for (const o of open) expectStatesCoverage(o, `${where} › ${o.getAttribute("aria-label") ?? "popover"}`);
    press("Escape");
  }
  return { opened: triggers.length };
};

const OPENERS: Record<string, Opener> = {
  "app/CommandPalette.tsx": () => {
    mount(
      <Harness>
        <CommandPalette />
      </Harness>,
    );
    press("k", MOD);
    const open = openOverlays();
    expect(document.querySelector(".palette"), "Ctrl/Cmd+K did not open the palette").not.toBeNull();
    for (const o of open) expectStatesCoverage(o, "command palette");
    return { opened: open.length };
  },
  "app/ShortcutHelp.tsx": () => {
    mount(
      <Harness>
        <ShortcutHelp />
      </Harness>,
    );
    press("?");
    const open = openOverlays();
    expect(document.querySelector(".kb-help"), "? did not open the keyboard reference").not.toBeNull();
    for (const o of open) expectStatesCoverage(o, "keyboard reference");
    return { opened: open.length };
  },
  "app/Header.tsx": () => {
    const wide = mount(
      <Harness>
        <Header />
      </Harness>,
    );
    const atWide = clickEveryPopoverTrigger(wide.querySelector("header") ?? wide, "header");
    for (const m of mounted.splice(0)) {
      act(() => m.root.unmount());
      m.container.remove();
    }
    /* The header lays out differently at narrow widths — its controls fold into a "More controls"
       popover that exists ONLY there, and that is where the bar is most likely to be covered. So it
       is opened as a narrow viewport would: every max-width query matches, every min-width does not.
       Popover triggers found inside an opened popover are opened in turn. */
    const real = window.matchMedia;
    window.matchMedia = ((q: string) =>
      ({
        matches: /max-width/.test(q) && !/min-width/.test(q),
        media: q,
        onchange: null,
        addEventListener: () => {},
        removeEventListener: () => {},
        addListener: () => {},
        removeListener: () => {},
        dispatchEvent: () => false,
      }) as unknown as MediaQueryList) as typeof window.matchMedia;
    try {
      const narrow = mount(
        <Harness>
          <Header />
        </Harness>,
      );
      const header = narrow.querySelector("header") ?? narrow;
      expect(header.querySelector(".hdr-more"), "the narrow header rendered no More control — the narrow layout was not reached").not.toBeNull();
      let opened = 0;
      for (const t of [...header.querySelectorAll<HTMLElement>('[aria-haspopup="dialog"]')]) {
        click(t);
        const open = openOverlays();
        expect(open.length, `narrow header: "${t.getAttribute("aria-label") ?? norm(t.textContent)}" opened nothing`).toBeGreaterThan(0);
        for (const o of open) {
          expectStatesCoverage(o, `narrow header › ${o.getAttribute("aria-label") ?? "popover"}`);
          opened++;
          for (const inner of [...o.querySelectorAll<HTMLElement>('[aria-haspopup="dialog"]')]) {
            click(inner);
            for (const o2 of openOverlays()) expectStatesCoverage(o2, `narrow header › nested ${o2.getAttribute("aria-label") ?? "popover"}`);
            opened++;
            press("Escape");
          }
        }
        press("Escape");
      }
      expect(opened, "the narrow header opened no overlay").toBeGreaterThan(0);
      return { opened: atWide.opened + opened };
    } finally {
      window.matchMedia = real;
    }
  },
  "panels/PriorityQueue.tsx": () => {
    const c = mount(
      <Harness>
        <PriorityQueue debounceMs={0} />
      </Harness>,
    );
    return clickEveryPopoverTrigger(c.querySelector("section.pq") ?? c, "priority queue");
  },
};

describe("B7: every overlay states the coverage figures while it is open", () => {
  it("discovers the overlay class from the source (and the discovery is not empty)", () => {
    expect(files.some((f) => f.file === PRIMITIVES), "the scan did not reach ui/primitives.tsx").toBe(true);
    expect(consumers.length, "no <Dialog/<Popover consumer found — the scan is broken").toBeGreaterThanOrEqual(2);
  });

  it("has an opener for every discovered <Dialog/<Popover consumer, and none for a file that is not one", () => {
    expect(Object.keys(OPENERS).sort()).toEqual(consumers);
  });

  it("the Dialog primitive states the figures", () => {
    mount(
      <Harness>
        <Dialog open onClose={() => {}} title="Probe">
          <p>body</p>
        </Dialog>
      </Harness>,
    );
    const d = openOverlays();
    expect(d.length).toBe(1);
    for (const o of d) expectStatesCoverage(o, "Dialog primitive");
  });

  it("the Popover primitive states the figures", () => {
    mount(
      <Harness>
        <Popover label="Probe" open trigger={<button type="button">t</button>}>
          <p>body</p>
        </Popover>
      </Harness>,
    );
    const p = openOverlays();
    expect(p.length).toBe(1);
    for (const o of p) expectStatesCoverage(o, "Popover primitive");
  });

  it("the RIB count keeps its completeness qualifier wherever it is stated", () => {
    mount(
      <Harness>
        <Dialog open onClose={() => {}} title="Probe">
          <p>body</p>
        </Dialog>
      </Harness>,
    );
    const text = norm(openOverlays()[0]?.querySelector("[data-overlay-coverage]")?.textContent);
    const q = ribCountQualifier();
    // Guard against a vacuous pass: on this snapshot both collected tables are shown incomplete.
    expect(q, "the snapshot's RIB qualifier is empty; this check would prove nothing").not.toBe("");
    expect(text).toMatch(new RegExp(`RIBs \\d+/\\d+ ${q.replace(/[()]/g, "\\$&")}`));
  });

  it("the qualifier is never dropped: it rides on the RIB segment, or stands alone when there is none", () => {
    expect(withRibQualifier(["a", "RIBs 1/2", "c"], "(q)")).toEqual(["a", "RIBs 1/2 (q)", "c"]);
    expect(withRibQualifier(["a", "c"], "(q)")).toEqual(["a", "c", "RIBs (q)"]);
    expect(withRibQualifier(["a", "RIBs 1/2"], "")).toEqual(["a", "RIBs 1/2"]);
    expect(coverageFigures().join(" · ")).toContain(T8_coverageLine().split(" · ")[0] ?? "\u0000");
  });

  for (const file of consumers) {
    it(`${file}: every overlay it opens states the figures`, () => {
      const opener = OPENERS[file];
      expect(opener, `no opener for ${file}`).toBeDefined();
      const { opened } = opener?.() ?? { opened: 0 };
      expect(opened, `${file}: nothing was opened, so nothing was checked`).toBeGreaterThan(0);
    });
  }

  /* Overlays built WITHOUT the primitive inherit nothing from it, so each must render the shared
     statement itself. The last known case was `app/StatusBar.tsx`'s coverage disclosure
     (`.covpanel`): at <= 767 px it is docked over the whole bar (chrome.css `inset: auto 0 0 0`) and
     stated the figures only as table cells. It now renders the statement in its head (merged-tree
     gate, wave 7), so the list is empty and a new raw overlay without the statement turns it red. */
  it("every overlay rendered without the primitive renders the shared statement itself", () => {
    const missing = files
      .filter((f) => rawOverlays.includes(f.file) && !/<CoverageStatement\b/.test(f.text))
      .map((f) => f.file);
    expect(missing).toEqual([]);
  });

  /* The source check above proves the tag is written; this proves it is RENDERED in the open panel.
     Every control on the permanent line that opens the coverage disclosure is clicked (discovered by
     `aria-expanded` on the bar, not listed), and the open panel must state the bar's own strings. */
  it("app/StatusBar.tsx: the coverage disclosure, opened from every control on the bar, states the figures", () => {
    const root = mount(<Harness />);
    const toggles = [...root.querySelectorAll<HTMLElement>("#status-bar button[aria-expanded]")];
    expect(toggles.length, "the status bar renders no disclosure control").toBeGreaterThan(0);
    let opened = 0;
    for (const t of toggles) {
      click(t);
      const panel = document.querySelector<HTMLElement>(".covpanel");
      expect(panel, `"${norm(t.textContent)}" opened no coverage disclosure`).not.toBeNull();
      if (panel) {
        expectStatesCoverage(panel, `status bar "${norm(t.textContent)}"`);
        opened += 1;
      }
      click(t);
    }
    expect(opened).toBe(toggles.length);
  });
});
