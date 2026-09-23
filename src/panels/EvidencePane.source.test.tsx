/**
 * EvidencePane.source.test.tsx — a finding's OWN evidence pointer, as the producer published it.
 *
 * WHY (acceptance A1, 2026-09-22). 134 of 146 findings reached only context records. The question
 * was whether that is the snapshot's limit or the compiler's: this project has already shipped a
 * compiler that silently dropped producer fields (object groups; ACL unevaluable flags). Searched:
 * every key on every `punchlist` row of the source snapshot; every section for a reference back to a
 * punchlist row (`punchlist[`, a finding id) — none; `remediation_plan` (122 items, keyed by
 * device + title, computed independently of the punchlist, so joining them would be OUR link, not
 * the producer's); `config_hygiene`, `security`, `capture_integrity` (no per-finding line or
 * interface pointer). The one producer field the compiler dropped was `source_command` — on 33 of
 * 146 rows, the show-command the engine cites as the finding's evidence (engine:
 * `compute_migration_punchlist`, `_PUNCH_SOURCE_COMMAND`). It names a command, not a record, and the
 * snapshot keeps no raw command output, so it does NOT create a route to literal configuration.
 *
 * The first test is the CLASS guard, and it holds no list: every key the producer put on a
 * punchlist row must reach the compiled Finding under its camelCase name. A future producer key the
 * compiler forgets fails here by name, not by someone remembering to look.
 */
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";
import { fabric } from "../core/data";
import { useInvestigation } from "../core/store";
import { EvidencePane } from "./EvidencePane";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const PKG = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
/** The source is the one `fabric.meta.source` names, relative to the repository root. */
const source = JSON.parse(readFileSync(resolve(PKG, "..", fabric.meta.source), "utf8")) as {
  punchlist: Record<string, unknown>[];
};
const camel = (k: string) => k.replace(/_([a-z])/g, (_, c: string) => c.toUpperCase());

describe("the compiler carries every field the producer put on a finding", () => {
  it("every punchlist key reaches the compiled finding under its camelCase name", () => {
    expect(source.punchlist.length).toBe(fabric.findings.length);
    const dropped = new Set<string>();
    source.punchlist.forEach((row, i) => {
      const f = fabric.findings[i] as unknown as Record<string, unknown>;
      for (const k of Object.keys(row)) if (!(camel(k) in f)) dropped.add(k);
    });
    expect([...dropped].sort(), "producer fields the compiler drops from findings").toEqual([]);
  });

  it("carries the engine's cited source command, verbatim, on exactly the rows that have one", () => {
    let cited = 0;
    source.punchlist.forEach((row, i) => {
      const f = fabric.findings[i]!;
      const want = typeof row.source_command === "string" && row.source_command.trim() !== "" ? row.source_command.trim() : null;
      expect(f.sourceCommand ?? null, f.id).toBe(want);
      if (want !== null) cited++;
    });
    // Measured 2026-09-22 on the shipped snapshot. A ratchet over the data, not a target.
    expect(cited, "findings whose producer row names its source command").toBe(33);
  });
});

const mounted: { root: Root; container: HTMLElement }[] = [];
function mountFor(findingId: string): HTMLElement {
  act(() => {
    useInvestigation.getState().reset();
    useInvestigation.getState().selectFinding(findingId);
  });
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  act(() => root.render(<EvidencePane onOpenCite={() => {}} onShowConfig={() => {}} />));
  mounted.push({ root, container });
  return container;
}
afterEach(() => {
  for (const m of mounted.splice(0)) {
    act(() => m.root.unmount());
    m.container.remove();
  }
});

describe("the pane shows the finding's own evidence pointer, and says what it is not", () => {
  it("F017 ('Undefined acl 7') names show running-config as the engine's source, in the header", () => {
    const f = fabric.findings.find((x) => x.id === "F017")!;
    expect(f.sourceCommand, "precondition").toBe("show running-config");
    const c = mountFor("F017");
    const el = c.querySelector<HTMLElement>("[data-finding-source]");
    expect(el, "the source line is rendered").not.toBeNull();
    // In the header: visible on selection, zero further interactions.
    expect(el!.closest(".ev__head")).not.toBeNull();
    expect(el!.dataset.findingSource).toBe("cited");
    const text = el!.textContent ?? "";
    expect(text).toContain("show running-config");
    expect(text).toMatch(/engine cites/);
    // Honest about reach: the output is not in the snapshot, so this is not a route to text.
    expect(text).toMatch(/output is not held in this snapshot/);
  });

  it("a finding whose row cites no command says so, rather than implying one", () => {
    const f = fabric.findings.find((x) => x.sourceCommand === null)!;
    const c = mountFor(f.id);
    const el = c.querySelector<HTMLElement>("[data-finding-source]");
    expect(el?.dataset.findingSource).toBe("uncited");
    expect(el?.textContent ?? "").toMatch(/cites no source command/);
  });

});

/* EVERY FINDING, ONE TEST EACH (acceptance report F2, 2026-09-23). This was one test looping over all
   146 findings, a full pane mount each: 13.5-15.7 s on a green full-suite run and a timeout at 30 s
   on a loaded one — so its 30 s limit could not tell a hang from a busy host. Profiled 2026-09-23
   (one scratch run on a shared, busy host; a CPU profile of the loop agreed), the cost is React-dev +
   jsdom per mount — about 330 elements a pane, ~34 ms of render each, dominated by development-mode
   element creation and DOM construction — not the product's evidence ranking (`configEvidenceFor` +
   `nearestConfigFor` over all 146 findings: ~23 ms in total), so there is nothing in EvidencePane.tsx
   to make cheaper. The claim is unchanged — every
   finding in the snapshot, each rendered in the real pane — but each finding is its own test, so a
   failure names its finding and the runner's timeout guards one mount, not 146. The denominator is
   the snapshot's own list, and the first test pins it non-empty. */
describe("every finding renders exactly one source line, cited or uncited, matching its compiled field", () => {
  it("the snapshot has findings to render (the per-finding tests below are over this list)", () => {
    expect(fabric.findings.length).toBeGreaterThan(0);
  });

  it.each(fabric.findings.map((f) => [f.id, f] as const))("%s", (_id, f) => {
    const c = mountFor(f.id);
    const els = c.querySelectorAll<HTMLElement>("[data-finding-source]");
    expect(els.length, f.id).toBe(1);
    expect(els[0]!.dataset.findingSource, f.id).toBe(f.sourceCommand ? "cited" : "uncited");
  });
});
