/**
 * PreviewLabel.test.tsx — Atlas Scope is a LABELLED preview, on every surface and at every width.
 *
 * Owner decision, 2026-10-09: Atlas Scope ships in the next release candidate as a labelled preview.
 * This file fails when the label leaves the permanent chrome, moves into the part of the status bar
 * that scrolls sideways, is hidden (the `hidden` attribute, `aria-hidden`, `inert`, the
 * visually-hidden class, an inline style, or a stylesheet rule naming it that takes it out of view),
 * loses its words, or quotes figures its owner (`docs/acceptance-report.md`) no longer states.
 *
 * "Every view, every viewport" is checked on the REAL App, one mount per width at every edge of the
 * layout ladder (read from its owner, `LADDER_REM`, not restated here) with the four surfaces
 * selected in turn: a test that mounted the bar alone could not see a layout that dropped the bar.
 * The 3-D renderer is stubbed exactly as `stage-font-size.test.tsx` stubs it: jsdom has no WebGL, and
 * the subject here is the chrome, not the picture. jsdom applies no stylesheet, so the stylesheet half
 * of "hidden" is read from the CSS sources instead, with a planted proof that the read is live.
 */
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { forbiddenWordsIn } from "../core/claims";
import { useInvestigation } from "../core/store";
import type { SurfaceId } from "../core/types";
import { actAsync } from "../test-support/act-turns";
import { compileGolden } from "../test-support/dataset/testing";
import { installMatchMediaAt } from "../test-support/media-at";
import { ACCEPTANCE_GRADE, PREVIEW_STATEMENT } from "./PreviewLabel";
import { StatusBar } from "./StatusBar";
import { LADDER_REM } from "./surfaces";

vi.mock("../fabric3d/Fabric3D", () => ({ default: () => <div data-testid="fabric-mounted" />, Fabric3D: () => <div /> }));

import { App } from "./App";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const HERE = dirname(fileURLToPath(import.meta.url));
const SRC = resolve(HERE, "..");
const REPORT = resolve(HERE, "..", "..", "docs", "acceptance-report.md");

/* Every surface, by the type: a new SurfaceId fails the type-check here until it is listed. */
const SURFACE_SET: Readonly<Record<SurfaceId, true>> = { fabric: true, findings: true, path: true, evidence: true };
const SURFACES = Object.keys(SURFACE_SET) as SurfaceId[];

/* Both sides of every ladder edge, plus a 320 px and a 390 px phone and a 1920 px desktop. */
const WIDTHS: readonly number[] = [
  ...new Set([320, 390, ...Object.values(LADDER_REM).flatMap((rem) => [rem * 16 - 1, rem * 16]), 1920]),
].sort((a, b) => a - b);

const mounted: { root: Root; container: HTMLElement }[] = [];
function mount(ui: ReactNode): HTMLElement {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  act(() => {
    root.render(ui);
  });
  mounted.push({ root, container });
  return container;
}

const flush = async (): Promise<void> => {
  for (let i = 0; i < 4; i += 1) {
    await actAsync(async () => {
      await new Promise((r) => setTimeout(r, 0));
    });
  }
};

beforeEach(() => {
  act(() => {
    useInvestigation.getState().reset();
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
  act(() => {
    useInvestigation.getState().reset();
  });
});

/* ── what "shown" means for the label ─────────────────────────────────────── */

/** The words a sighted reader sees: the label's text without its visually-hidden part. */
function seenText(el: HTMLElement): string {
  const copy = el.cloneNode(true) as HTMLElement;
  for (const h of [...copy.querySelectorAll(".visually-hidden")]) h.remove();
  return (copy.textContent ?? "").replace(/\s+/g, " ").trim();
}

/** Why `el` would not be seen, from the DOM alone: it or an ancestor hidden, inert or visually hidden. */
function hiddenBy(el: HTMLElement): string[] {
  const out: string[] = [];
  for (let n: HTMLElement | null = el; n !== null; n = n.parentElement) {
    const what = `${n.tagName.toLowerCase()}${n.id === "" ? "" : `#${n.id}`}${n.classList.length === 0 ? "" : `.${[...n.classList].join(".")}`}`;
    if (n.hidden) out.push(`${what}: the hidden attribute`);
    if (n.getAttribute("aria-hidden") === "true") out.push(`${what}: aria-hidden`);
    if (n.hasAttribute("inert")) out.push(`${what}: inert`);
    if (n.classList.contains("visually-hidden")) out.push(`${what}: visually-hidden`);
    const s = n.style;
    if (s.display === "none" || s.visibility === "hidden" || s.visibility === "collapse" || s.opacity === "0") {
      out.push(`${what}: an inline style hides it`);
    }
  }
  return out;
}

/** The label is the bar's own child, outside the sideways-scrolling region, shown, and says its words. */
function expectLabelled(container: ParentNode, where: string): void {
  const bar = container.querySelector<HTMLElement>("#status-bar");
  expect(bar, `${where}: the status bar is not rendered`).not.toBeNull();
  const labels = [...bar!.children].filter((c): c is HTMLElement => c instanceof HTMLElement && c.hasAttribute("data-preview"));
  expect(labels.length, `${where}: the status bar carries ${labels.length} preview labels as its own children, not exactly one`).toBe(1);
  const label = labels[0]!;
  expect(label.closest(".sb__rest"), `${where}: the label sits in the region that scrolls sideways`).toBeNull();
  expect(hiddenBy(label), `${where}: the label is hidden`).toEqual([]);
  const seen = seenText(label);
  expect(seen, `${where}: the visible words`).toContain("Preview");
  expect(seen, `${where}: the visible words`).toContain("acceptance not complete");
  expect(label.textContent ?? "", `${where}: the accessible statement`).toContain(PREVIEW_STATEMENT);
  expect(label.getAttribute("title"), `${where}: the tooltip`).toBe(PREVIEW_STATEMENT);
}

/* ── the bar, and the real App at every width on every surface ──────────── */

describe("the status bar carries the preview label", () => {
  it("as a shown, worded, direct child of the bar", () => {
    const c = mount(<StatusBar />);
    expectLabelled(c, "StatusBar alone");
  });
});

describe("every surface at every width carries the label (the real App)", () => {
  it("covers the ladder: both sides of every edge, a 320 px phone and a 1920 px desktop", () => {
    expect(WIDTHS[0]).toBe(320);
    expect(WIDTHS[WIDTHS.length - 1]).toBe(1920);
    for (const rem of Object.values(LADDER_REM)) {
      expect(WIDTHS).toContain(rem * 16 - 1);
      expect(WIDTHS).toContain(rem * 16);
    }
    expect(SURFACES).toEqual(["fabric", "findings", "path", "evidence"]);
  });

  for (const width of WIDTHS) {
    it(`${width} px: fabric, findings, path and evidence`, async () => {
      const media = installMatchMediaAt(width, 16);
      try {
        const c = mount(<App />);
        await flush();
        for (const surface of SURFACES) {
          act(() => {
            useInvestigation.getState().setSurface(surface);
          });
          await flush();
          expect(useInvestigation.getState().surface, `precondition: ${surface} is the selected surface`).toBe(surface);
          expectLabelled(c, `${width} px, ${surface}`);
        }
      } finally {
        media.restore();
      }
    });
  }
});

/* ── no stylesheet takes it out of view ─────────────────────────────────── */

type Rule = { file: string; selector: string; body: string };

function rulesOf(file: string, css: string): Rule[] {
  const text = css.replace(/\/\*[\s\S]*?\*\//g, "");
  return [...text.matchAll(/([^{}]+)\{([^{}]*)\}/g)].map((m) => ({ file, selector: (m[1] ?? "").trim(), body: m[2] ?? "" }));
}

/** A selector that can reach the label or one of its parts: its classes, or its data attribute. */
const NAMES_LABEL = /\.sb__preview|\[data-preview/;

/** Declarations that take a box out of view or out of the flow it is read in. */
const HIDING: readonly (readonly [string, RegExp])[] = [
  ["display: none", /(?:^|[;{\s])display\s*:\s*none\b/],
  ["visibility", /(?:^|[;{\s])visibility\s*:\s*(?:hidden|collapse)\b/],
  ["opacity 0", /(?:^|[;{\s])opacity\s*:\s*0*(?:\.0*)?\s*(?:!important\s*)?(?:;|$)/],
  ["content-visibility", /(?:^|[;{\s])content-visibility\s*:\s*hidden\b/],
  ["clip", /(?:^|[;{\s])clip(?:-path)?\s*:/],
  ["zero font size", /(?:^|[;{\s])font-size\s*:\s*0(?![.\d])/],
  ["zero box", /(?:^|[;{\s])(?:max-)?(?:width|height|inline-size|block-size)\s*:\s*0(?![.\d])/],
  ["out of flow", /(?:^|[;{\s])position\s*:\s*(?:absolute|fixed)\b/],
  ["transform", /(?:^|[;{\s])transform\s*:/],
  ["text-indent", /(?:^|[;{\s])text-indent\s*:/],
  ["transparent ink", /(?:^|[;{\s])color\s*:\s*transparent\b/],
];

function hidingRules(rules: readonly Rule[]): string[] {
  return rules
    .filter((r) => NAMES_LABEL.test(r.selector))
    .flatMap((r) => HIDING.filter(([, re]) => re.test(r.body)).map(([what]) => `${r.file} ${r.selector} → ${what}`));
}

function cssFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) return cssFiles(p);
    return p.endsWith(".css") ? [p] : [];
  });
}

describe("no stylesheet takes the label out of view", () => {
  const rules = cssFiles(SRC).flatMap((f) => rulesOf(relative(SRC, f).replace(/\\/g, "/"), readFileSync(f, "utf8")));

  it("finds the label's own rules — an empty read is not a pass", () => {
    const own = rules.filter((r) => NAMES_LABEL.test(r.selector)).map((r) => `${r.file} ${r.selector}`);
    expect(own).toContain("app/chrome.css .sb__preview");
    expect(own).toContain("app/chrome.css .sb__preview-badge");
  });

  it("no rule that names the label hides it, clips it or moves it out of the bar's flow", () => {
    expect(hidingRules(rules)).toEqual([]);
  });

  it("the gate is live — every hiding shape is caught, and the shipped shapes are not", () => {
    const planted = [
      ".sb__preview { display: none; }",
      "@media (max-width: 20rem) { .sb__preview { visibility: hidden } }",
      ".sb__preview-badge { opacity: 0; }",
      ".sb__preview { content-visibility: hidden; }",
      "[data-preview] { clip-path: inset(50%); }",
      ".sb__preview-reason { font-size: 0; }",
      ".sb__preview { max-width: 0; }",
      ".sb__preview { position: absolute; }",
      ".sb__preview { transform: scale(0); }",
      ".sb__preview { text-indent: -999em; }",
      ".sb__preview { color: transparent; }",
    ];
    for (const css of planted) expect(hidingRules(rulesOf("planted.css", css)), css).toHaveLength(1);
    const shipped = ".sb__preview { display: inline-flex; min-width: 0; opacity: 0.9; color: var(--text); white-space: nowrap; }";
    expect(hidingRules(rulesOf("planted.css", shipped))).toEqual([]);
  });
});

/* ── its figures are its owner's ────────────────────────────────────────── */

describe("the label's figures are the acceptance report's", () => {
  const report = readFileSync(REPORT, "utf8").replace(/\r\n/g, "\n");

  it("the cached grade equals the report's Graded date and its one Totals line", () => {
    expect(/^Graded (\S+) against /m.exec(report)?.[1], "the report's latest grade date").toBe(ACCEPTANCE_GRADE.graded);
    const totals = [...report.matchAll(/^Totals: \*\*(\d+) PASS, (\d+) FAIL, (\d+) UNPROVEN\.\*\*$/gm)];
    expect(totals.length, "the report states exactly one Totals line").toBe(1);
    const [, pass, fail, unproven] = totals[0]!;
    expect({ pass: Number(pass), fail: Number(fail), unproven: Number(unproven) }).toEqual({
      pass: ACCEPTANCE_GRADE.pass,
      fail: ACCEPTANCE_GRADE.fail,
      unproven: ACCEPTANCE_GRADE.unproven,
    });
    expect(ACCEPTANCE_GRADE.pass + ACCEPTANCE_GRADE.fail + ACCEPTANCE_GRADE.unproven).toBe(ACCEPTANCE_GRADE.criteria);
    expect(report).toContain(`${ACCEPTANCE_GRADE.fail} of ${ACCEPTANCE_GRADE.criteria} criteria FAIL`);
    expect(ACCEPTANCE_GRADE.report).toBe("atlas-scope/docs/acceptance-report.md");
  });

  it("the statement says them, names the report, and asserts nothing the claim grammar forbids", () => {
    expect(PREVIEW_STATEMENT).toContain("acceptance is not complete");
    expect(PREVIEW_STATEMENT).toContain(`${ACCEPTANCE_GRADE.fail} of ${ACCEPTANCE_GRADE.criteria} criteria as FAIL`);
    expect(PREVIEW_STATEMENT).toContain(`${ACCEPTANCE_GRADE.unproven} as UNPROVEN`);
    expect(PREVIEW_STATEMENT).toContain(ACCEPTANCE_GRADE.report);
    expect(forbiddenWordsIn(PREVIEW_STATEMENT)).toEqual([]);
  });
});

/* ── the hub build's dataset: the banner and the label, side by side ────── */

describe("an AssessHub snapshot (the dataset the /scope hub build shows) keeps the label beside its banner", () => {
  afterEach(() => {
    vi.resetModules();
  });

  it("the dataset banner and the preview label are both on the bar", async () => {
    /* The dataset is read once, at the application's first import, so a fresh module graph is
       installed into before the bar is imported — the pattern of core/dataset.banner.test.ts. */
    vi.resetModules();
    const set = structuredClone(compileGolden());
    for (const doc of [set.fabric, set.aclBindings, set.ribEvidence, set.producerEmission]) {
      Object.assign(doc.meta, { source: "assesshub:snapshot/12", sourceOrigin: "assesshub-store", sourceDigestForm: "assesshub-store-blob" });
    }
    const slot = await import("../core/dataset/slot");
    slot.installDataset({
      set,
      origin: {
        kind: "assesshub",
        snapshotId: "12",
        verification: "verified-in-browser",
        attestedSha256: set.fabric.meta.sourceSha256,
        attestedBytes: set.fabric.meta.sourceBytes,
        warnings: [],
      },
    });
    const fresh = await import("./StatusBar");
    const c = mount(<fresh.StatusBar />);
    expect(c.querySelector(".sb-dataset"), "precondition: the AssessHub dataset banner is shown").not.toBeNull();
    expectLabelled(c, "AssessHub snapshot");
  });
});
