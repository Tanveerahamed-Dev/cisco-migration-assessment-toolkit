/**
 * PathTrace.preset-cites.b6.test.tsx — every citation a Path preset card prints is a working
 * citation control, outside the run-this-flow button, and every verdict word on the card carries the
 * record that decided it (acceptance B6, wave 7).
 *
 * THE DEFECT (acceptance report, B6 overturned PASS -> FAIL at 8eac055). The refuter's preset probe
 * counted `citeButtons 0` on the "Other questions this snapshot can answer" cards, which print
 * `acls.core1.PROTECT_SERVERS[2]`, `l3_forwarding[5]` (twice) and `l3_forwarding[4]` (twice). Clicking
 * the `l3_forwarding[5]` sentence re-ran the preset's flow (the URL moved to
 * `flow=10.0.40.50>10.0.30.10>tcp>443`) and opened no Inspector: the rationale and the provenance note
 * were plain spans INSIDE `<button class="pt-preset__btn" onClick={run}>` — the inert-citation shape
 * `cited-text.tsx` fixed everywhere else, and a citation there could not have been a control anyway,
 * because a button may not contain another. Three of the five cards also stated a verdict word
 * ("denied by list text — not decided…", "indeterminate", "13 caveats on its card") with no citation
 * at all.
 *
 * Nothing here is a fixture: the flows are the engine's `suggestedFlows()`, the verdicts its own
 * traces, the citations whatever the shipped resolver (`citesIn`) finds in the shipped prose. The
 * expected record behind each verdict word is derived here from the trace — the evidence on the hop
 * that ended it, the engine's own refusal record when no device was consulted, and each input that
 * left the outcome undecided — not read back from the component under test.
 */
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { actAsync } from "../test-support/act-turns";
import { outcomeUndecidingGaps } from "../core/claims";
import { fabric } from "../core/data";
import { decodeInvestigation, useInvestigation } from "../core/store";
import type { Cite, Trace } from "../core/types";
import { refusalOf, suggestedFlows, traceFlow } from "../forwarding/engine";
import { verdictStatement } from "./ClaimCard";
import { resolveCitation } from "./Inspector";
import { PathTrace } from "./PathTrace";
import { describeGolden } from "../test-support/golden-sample";
import { citesIn } from "./cited-text";

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
beforeEach(() => {
  act(() => { useInvestigation.getState().reset(); });
});
afterEach(() => {
  for (const m of mounted.splice(0)) {
    act(() => m.root.unmount());
    m.container.remove();
  }
  act(() => { useInvestigation.getState().reset(); });
});

/** One animation frame and a task: the run commit a click would schedule has had its chance. */
async function settleCommit(): Promise<void> {
  await actAsync(async () => {
    await new Promise<void>((r) => requestAnimationFrame(() => setTimeout(r, 0)));
    await new Promise<void>((r) => setTimeout(r, 0));
  });
}

/** Anything a reader can operate. A citation control is one; so is the run button. */
const INTERACTIVE = "button, a[href], input, select, textarea, summary, [role=button], [role=link], [tabindex]:not([tabindex='-1'])";

/** The citation a control opens, read from the accessible name the Cite primitive gives it. */
const citeOf = (b: Element): string | null => /^Open source record (.+)$/.exec(b.getAttribute("aria-label") ?? "")?.[1] ?? null;
const citeControlsIn = (el: Element): HTMLButtonElement[] =>
  [...el.querySelectorAll<HTMLButtonElement>("button")].filter((b) => citeOf(b) !== null);

/**
 * The records behind a trace's verdict word: the evidence that ended the trace (else the engine's
 * record of why no device was consulted, else the coverage matrix), and each input the claims owner
 * says left the outcome undecided.
 */
function recordsBehindVerdict(t: Trace): Cite[] {
  const last = t.hops[t.hops.length - 1];
  const decided = last?.decidedBy?.cite ?? (last === undefined ? refusalOf(t)?.cite : undefined) ?? fabric.coverage.cite;
  return [...new Set([decided, ...outcomeUndecidingGaps(t).map((g) => g.cite)])];
}

/**
 * The citations the element's TEXT prints, one text run at a time. Reading `textContent` whole would
 * glue two adjacent spans into one token ("…on its card.acls.core1.PROTECT_SERVERS[2]"), which the
 * resolver then rightly refuses — and a citation printed inside the button would be missed.
 */
function printedCites(el: Element): string[] {
  const clone = el.cloneNode(true) as Element;
  clone.normalize();
  const out: string[] = [];
  const w = document.createTreeWalker(clone, NodeFilter.SHOW_TEXT);
  for (let n = w.nextNode(); n; n = w.nextNode()) out.push(...citesIn(n.nodeValue ?? ""));
  return out;
}

/** The innermost elements whose text shows `phrase`. */
function showing(root: Element, phrase: string): Element[] {
  return [...root.querySelectorAll("*")].filter(
    (e) => (e.textContent ?? "").includes(phrase) && ![...e.children].some((k) => (k.textContent ?? "").includes(phrase)),
  );
}

const cases = suggestedFlows().map((s) => {
  const t = traceFlow(s.flow);
  return { s, t, verdict: verdictStatement(t), behind: recordsBehindVerdict(t) };
});

/** The two places the presets are drawn: under the empty form, and under a result. */
const PLACES: readonly (readonly [string, string])[] = [
  ["Questions this snapshot can answer (no flow yet)", "?s=path"],
  ["Other questions this snapshot can answer (under state 06's result)", "?s=path&flow=10.0.10.50>10.0.30.10>tcp>3389&hop=0"],
];

async function mountPresets(search: string, onOpenCite: (c: Cite) => void): Promise<HTMLElement[]> {
  act(() => { useInvestigation.getState().hydrate(decodeInvestigation(search)); });
  const c = mount(<PathTrace onOpenCite={onOpenCite} />);
  await settleCommit();
  const cards = [...c.querySelectorAll<HTMLElement>(".pt-presets .pt-preset")];
  return cards;
}

describe("B6 wave 7: the preset cards' citations", () => {
  /* RE-EXPRESSED 2026-09-28 (phase 3). This pinned the refuter's printed citations by name
     (acls.core1.PROTECT_SERVERS[2], l3_forwarding[5], l3_forwarding[4]). The last two were printed by the
     no-route preset from core2's subnet and a pod-subnet preset; the regenerated sample gave core2 a default
     route (no no-route preset is offered) and the engine now derives its presets from the new multi-hop
     paths, so which cards exist is the engine's choice, not evidence. The invariant is what the refuter's
     probe meant: the cards print citations and each one resolves, as does every record behind every
     card's verdict word (each is then checked as a working control, per card, by the tests below). The
     refuter's own record that is still printed on this sample is pinned in the golden block. */
  it("the data this rests on: the cards print citations, and every one of them and every verdict record resolves", () => {
    const printed = cases.flatMap(({ s }) => [...citesIn(s.rationale), ...citesIn(s.srcProvenance.note)]);
    expect(printed.length, "the cards print citations at all").toBeGreaterThan(0);
    for (const c of printed) expect(resolveCitation(c).kind, c).not.toBe("unresolved");
    for (const { behind } of cases) for (const c of behind) expect(resolveCitation(c).kind, c).not.toBe("unresolved");
  });

  describeGolden("the refuter's records on the reference sample", () => {
    it("the undecidable ICMP card still prints the unevaluable PROTECT_SERVERS line it rests on", () => {
      const printed = cases.flatMap(({ s }) => [...citesIn(s.rationale), ...citesIn(s.srcProvenance.note)]);
      expect(printed).toContain("acls.core1.PROTECT_SERVERS[2]");
    });
  });

  for (const [where, search] of PLACES) {
    describe(where, () => {
      it("every citation the card prints is a citation control, and none is inside the run button", async () => {
        const opened: Cite[] = [];
        const cards = await mountPresets(search, (c) => opened.push(c));
        expect(cards.length, "one card per suggested flow, in the engine's order").toBe(cases.length);
        const problems: string[] = [];
        cards.forEach((card, i) => {
          const { s } = cases[i]!;
          const run = card.querySelector<HTMLElement>(".pt-preset__btn");
          if (run === null) {
            problems.push(`${s.id}: no run button`);
            return;
          }
          /* The run button holds no control and no citation: a citation inside it can only be inert. */
          if (run.querySelector(INTERACTIVE) !== null) problems.push(`${s.id}: a control is nested inside the run button`);
          for (const c of printedCites(run)) problems.push(`${s.id}: ${c} is printed inside the run button`);
          /* Every citation the rationale and the provenance note carry has its own control, as many
             times as the prose prints it. */
          const printed = [...citesIn(s.rationale), ...citesIn(s.srcProvenance.note)];
          const controls = citeControlsIn(card).map(citeOf);
          for (const c of new Set(printed)) {
            const want = printed.filter((x) => x === c).length;
            const have = controls.filter((x) => x === c).length;
            if (have < want) problems.push(`${s.id}: ${c} is printed ${want}x and is a control ${have}x`);
          }
          /* And nothing citation-shaped is left as text anywhere on the card. */
          const clone = card.cloneNode(true) as HTMLElement;
          for (const b of citeControlsIn(clone)) b.remove();
          for (const c of printedCites(clone)) problems.push(`${s.id}: ${c} is inert text on the card`);
        });
        expect(problems).toEqual([]);
      });

      it("clicking each citation opens that record and does not run the preset's flow", async () => {
        const opened: Cite[] = [];
        const cards = await mountPresets(search, (c) => opened.push(c));
        expect(cards.length).toBe(cases.length);
        const flowBefore = useInvestigation.getState().flow;
        const panel = cards[0]!.closest(".pathtrace")!;
        const resultBefore = panel.querySelector(".pt-result .claim__outcome-word")?.textContent ?? null;
        let clicked = 0;
        const problems: string[] = [];
        for (const [i, card] of cards.entries()) {
          for (const b of citeControlsIn(card)) {
            const cite = citeOf(b)!;
            opened.length = 0;
            act(() => b.click());
            clicked += 1;
            await settleCommit();
            if (opened.join("|") !== cite) problems.push(`${cases[i]!.s.id}: ${cite} opened [${opened.join(", ")}]`);
            if (useInvestigation.getState().flow !== flowBefore) problems.push(`${cases[i]!.s.id}: clicking ${cite} ran a flow`);
            if ((panel.querySelector(".pt-result .claim__outcome-word")?.textContent ?? null) !== resultBefore)
              problems.push(`${cases[i]!.s.id}: clicking ${cite} replaced the panel's result`);
          }
        }
        /* The refuter's probe, verbatim: click the SENTENCE that prints the citation, not a control.
           It used to be part of the run button, so it re-ran the preset's flow. */
        for (const [i, card] of cards.entries()) {
          const { s } = cases[i]!;
          for (const sentence of [s.rationale, s.srcProvenance.note]) {
            if (citesIn(sentence).length === 0) continue;
            const head = sentence.slice(0, 24);
            for (const el of showing(card, head)) {
              act(() => el.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true })));
              await settleCommit();
              if (useInvestigation.getState().flow !== flowBefore) problems.push(`${s.id}: clicking the sentence "${head}…" ran a flow`);
              if ((panel.querySelector(".pt-result .claim__outcome-word")?.textContent ?? null) !== resultBefore)
                problems.push(`${s.id}: clicking the sentence "${head}…" replaced the panel's result`);
            }
          }
        }
        expect(problems).toEqual([]);
        /* The refuter's five, at least, and the verdict records below. */
        expect(clicked).toBeGreaterThanOrEqual(cases.flatMap(({ s }) => [...citesIn(s.rationale), ...citesIn(s.srcProvenance.note)]).length);
      });

      it("every verdict word and its bounds carry the record that decided them, outside the run button", async () => {
        const cards = await mountPresets(search, () => {});
        expect(cards.length).toBe(cases.length);
        const problems: string[] = [];
        cards.forEach((card, i) => {
          const { s, verdict, behind } = cases[i]!;
          const run = card.querySelector(".pt-preset__btn");
          for (const [what, phrase, need] of [
            ["verdict word", verdict.word, behind],
            ["bounds", verdict.bounds, [fabric.coverage.cite]],
          ] as const) {
            const shown = showing(card, phrase);
            if (shown.length === 0) {
              problems.push(`${s.id}: the ${what} "${phrase}" is not on the card`);
              continue;
            }
            for (const el of shown) {
              if (run?.contains(el)) problems.push(`${s.id}: the ${what} is inside the run button`);
              /* The line the phrase is on: its nearest block that is not the card itself. */
              const line = el.closest("p, div, li") ?? el;
              const have = citeControlsIn(line === card ? el : line).map(citeOf);
              for (const c of need) if (!have.includes(c)) problems.push(`${s.id}: the ${what} "${phrase.slice(0, 40)}…" carries no control for ${c}`);
            }
          }
        });
        expect(problems).toEqual([]);
      });

      it("the run button is still one button per card, and running a card still traces its flow", async () => {
        const cards = await mountPresets(search, () => {});
        const runs = cards.map((c) => c.querySelectorAll(".pt-preset__btn"));
        expect(runs.every((r) => r.length === 1)).toBe(true);
        /* The run button's accessible name and description together carry the verdict and its
           bounds, so a reader who reaches the button alone still hears what running it will answer
           (acceptance B2 — the button used to hold the verdict in its own text). */
        cards.forEach((card, i) => {
          const run = card.querySelector<HTMLElement>(".pt-preset__btn")!;
          const described = (run.getAttribute("aria-describedby") ?? "")
            .split(/\s+/)
            .filter(Boolean)
            .map((id) => card.ownerDocument.getElementById(id)?.textContent ?? "")
            .join(" ");
          const heard = `${run.textContent ?? ""} ${described}`;
          expect(heard, cases[i]!.s.id).toContain(cases[i]!.verdict.word);
          expect(heard, cases[i]!.s.id).toContain(cases[i]!.t.claim.slice(0, cases[i]!.t.claim.indexOf(",")));
        });
        const target = cases[cases.length - 1]!;
        act(() => cards[cards.length - 1]!.querySelector<HTMLElement>(".pt-preset__btn")!.click());
        await settleCommit();
        expect(useInvestigation.getState().flow).toEqual(target.s.flow);
      });
    });
  }
});
