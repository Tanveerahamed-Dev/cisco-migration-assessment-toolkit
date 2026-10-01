// @vitest-environment node
/**
 * stage-inspector-narrow.test.ts — an open Inspector is never inside a hidden box.
 *
 * THE DEFECT (merged-tree gate, wave 5, 2026-09-24). The Inspector is docked inside the stage
 * (`surfaces.tsx :: Stage`), and below 768 px shell.css collapses the stage with `display: none`
 * until the reader asks for the fabric (design brief 2.5). So at 390, 600 and 767 px, the `i`
 * shortcut and Enter on any evidence citation opened an Inspector that was in the DOM and never on
 * screen: `getClientRects()` empty, focus left on the invoker. MEASURED on the production preview
 * (scratch inspprobe.mjs): 6 of 6 narrow cases not shown, 2 of 2 at 1440 shown with focus in the
 * tablist; `review/audit-d3-focus.mjs` reported "phone/inspector (i|citation) :: NOT DRIVEN".
 *
 * THE RULE held here, from the stylesheets rather than a list of widths: in EVERY media block that
 * hides `.app__stage`, the same block must show the stage again while it carries
 * `.app__stage--with-inspector`, and must hide everything in it except the Inspector while the
 * fabric is collapsed — the reader asked for a record, not for the fabric.
 *
 * WHAT THIS DOES NOT PROVE: layout. jsdom computes none. The rendered evidence is the probe above
 * and `node review/audit-d3-focus.mjs` (its phone and tablet inspector passes).
 */
import { readdirSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const SRC = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const strip = (s: string): string => s.replace(/\/\*[\s\S]*?\*\//g, "");

type Rule = { media: string; selector: string; body: string; file: string };

/** Flat list of style rules with the @media prelude they sit in ("" at top level). */
function rules(file: string, css: string): Rule[] {
  const out: Rule[] = [];
  const walk = (text: string, media: string): void => {
    let i = 0;
    while (i < text.length) {
      const open = text.indexOf("{", i);
      if (open < 0) return;
      const prelude = text.slice(i, open).trim();
      let depth = 1;
      let j = open + 1;
      for (; j < text.length && depth > 0; j += 1) {
        if (text[j] === "{") depth += 1;
        else if (text[j] === "}") depth -= 1;
      }
      const inner = text.slice(open + 1, j - 1);
      if (prelude.startsWith("@media")) walk(inner, prelude);
      else if (!prelude.startsWith("@")) out.push({ media, selector: prelude, body: inner, file });
      i = j;
    }
  };
  walk(strip(css), "");
  return out;
}

const all: Rule[] = readdirSync(resolve(SRC, "app"))
  .filter((f) => f.endsWith(".css"))
  .flatMap((f) => rules(`app/${f}`, readFileSync(resolve(SRC, "app", f), "utf8")));

const selectors = (r: Rule): string[] => r.selector.split(",").map((s) => s.trim());
const display = (r: Rule): string | null => /(?:^|;)\s*display\s*:\s*([^;]+)/.exec(r.body)?.[1]?.trim() ?? null;

describe("the Inspector is shown wherever the stage is collapsed", () => {
  /* Every WIDTH-conditioned collapse. `@media print` also hides the stage, deliberately and for a
     different reason (a printout carries no interactive dock), so it is not a width rung. */
  const hiding = all.filter((r) => selectors(r).includes(".app__stage") && display(r) === "none" && /width/.test(r.media));

  it("finds the collapse at all (positive control)", () => {
    expect(hiding.length).toBeGreaterThan(0);
  });

  it("every media block that hides the stage shows it again while the Inspector is open", () => {
    const missing = hiding.filter(
      (h) =>
        !all.some(
          (r) =>
            r.media === h.media &&
            // The stage ITSELF, while it carries the modifier — not a descendant of it.
            selectors(r).some((s) => /\.app__stage--with-inspector$/.test(s)) &&
            display(r) !== null &&
            display(r) !== "none",
        ),
    );
    expect(missing.map((h) => `${h.file} ${h.media}`)).toEqual([]);
  });

  it("with the fabric collapsed, the open stage shows the Inspector and nothing else", () => {
    const missing = hiding.filter(
      (h) =>
        !all.some(
          (r) =>
            r.media === h.media &&
            selectors(r).some((s) => /\[data-fabric3d="off"\]\s+\.app__stage--with-inspector\s*>\s*:not\(#inspector\)/.test(s)) &&
            display(r) === "none",
        ),
    );
    expect(missing.map((h) => `${h.file} ${h.media}`)).toEqual([]);
  });
});

describe("an open evidence drawer never covers the Inspector", () => {
  /* THE DEFECT (D3 drawer pass, 1024–1279 px): Rail B becomes an overlay drawer over the stage, and the
     Inspector is docked inside that stage, so an open drawer painted over it. MEASURED: the Inspector's
     close button 0/9 hit-testable at 1024, 1152 and 1270, its tab panels 3/9 or 6/9. THE RULE, from the
     stylesheets: in every media block where an open drawer is shown, the same block docks the Inspector
     to the drawer's left edge — a margin equal to the drawer's own width. Layout proof is rendered
     evidence (`node review/audit-d3-focus.mjs --vp=1152`), not this test. */
  const prop = (r: Rule, name: string): string | null =>
    new RegExp(`(?:^|;)\\s*${name}\\s*:\\s*([^;]+)`).exec(r.body)?.[1]?.trim() ?? null;
  const openDrawer = all.filter((r) => selectors(r).includes('.app[data-drawer="open"] .rail--b') && /width/.test(r.media));

  it("finds the drawer at all (positive control)", () => {
    expect(openDrawer.length).toBeGreaterThan(0);
  });

  it("every block that opens the drawer docks the Inspector beside it, by the drawer's own width", () => {
    const missing = openDrawer.filter((d) => {
      const width = all.find((r) => r.media === d.media && selectors(r).includes(".rail--b") && prop(r, "width") !== null);
      const dock = all.find((r) => r.media === d.media && selectors(r).includes('.app[data-drawer="open"] #inspector'));
      return width === undefined || dock === undefined || prop(dock, "margin-inline-end") !== prop(width, "width");
    });
    expect(missing.map((d) => `${d.file} ${d.media}`)).toEqual([]);
  });
});
