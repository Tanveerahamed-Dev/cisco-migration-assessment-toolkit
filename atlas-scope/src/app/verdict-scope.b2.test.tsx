/**
 * verdict-scope.b2.test.tsx — every surface that states a SUGGESTED flow's forwarding verdict states
 * it with the bounds the engine attached to it (acceptance B2).
 *
 * WHY THIS FILE EXISTS. B2 passed on the engine and failed on the palette: `traceFlow` wrapped every
 * verdict in "Under the collected RIBs of core1 and core2 only (2 of 26 hosts …)" plus 8–13 caveats,
 * and the Ctrl+K palette re-stated the same verdicts as "trace a path — this one ends denied" and
 * "…which is the blocking-hop answer with its exact configuration line" — no scope, no caveat, and a
 * decided-sounding answer for a denial whose own trace says "That denial is not decided". The Path
 * panel's presets printed the same sentence. Each surface re-worded the verdict from the bare outcome
 * enum (or from a prose rationale written when the flow was picked), so none of them carried what
 * the engine said about it.
 *
 * The invariant is stated over the CLASS, not over the two rows the report quoted:
 *
 *   1. Every surface string a suggested flow produces — the palette's grammar example, every palette
 *      command (whatever its id), every row the rendered palette shows for a typed address, every
 *      Path preset, and the live-region announcement a trace makes — that states an outcome carries
 *      the trace's OWN scope clause (read from `trace.claim`, whose denominator is checked against
 *      the compiled coverage) and the trace's own caveat count, and, for a trace whose outcome is not
 *      decided, the claims owner's undecided word — never decided wording.
 *   2. A suggestion's title and rationale NAME a flow; they do not state an outcome. Its outcome is
 *      the trace's, stated through the claims owner. "Verdict wording" is the vocabulary of the
 *      outcome and hop-verdict enums, one family per member, typed `Record<…>` so a new member
 *      fails the compile here until its family is written.
 *   3. A palette command that uses verdict vocabulary but names no traced flow is a verdict with no
 *      trace to bound it, and fails.
 *
 * The companion structural guard (`src/forwarding/verdict-wording.guard.test.ts`) finds an outcome
 * value turned into text anywhere outside the owners, so a NEW surface cannot re-word a verdict
 * without being found; this file proves the surfaces that exist say the right thing.
 */
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { isDecidedOutcome, undecidedOutcomeWord } from "../core/claims";
import { fabric } from "../core/data";
import { useInvestigation } from "../core/store";
import type { Flow, HopVerdict, Trace, TraceOutcome } from "../core/types";
import { suggestedFlows, traceFlow, type SuggestedFlow } from "../forwarding/engine";
import { PathTrace } from "../panels/PathTrace";
import { CommandPalette } from "./CommandPalette";
import { allCommands, formatFlow, grammarExamples, runFlow, useCommandAnnouncement } from "./commands";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const mounted: Root[] = [];
function mount(ui: ReactNode): HTMLElement {
  const el = document.createElement("div");
  document.body.appendChild(el);
  const root = createRoot(el);
  act(() => root.render(ui));
  mounted.push(root);
  return el;
}
beforeEach(() => {
  useInvestigation.getState().reset();
  useInvestigation.getState().setPaletteOpen(false);
});
afterEach(() => {
  for (const r of mounted.splice(0)) act(() => r.unmount());
  document.body.innerHTML = "";
  useInvestigation.getState().setPaletteOpen(false);
});

/* ── the vocabulary of a verdict, one family per enum member ─────────────────────────────── */

/* Typed over the enums, so adding an outcome or a hop verdict without a family is a compile error in
   this file rather than a word the guard silently does not know. */
const OUTCOME_FAMILY: Readonly<Record<TraceOutcome, RegExp>> = {
  delivered: /\bdeliver(s|ed|y|ies)?\b/i,
  dropped: /\bdrop(s|ped)?\b|\bunreachable\b/i,
  denied: /\bden(y|ies|ied|ial)\b|\bblock(s|ed|ing)?\b|\bblocking-hop\b/i,
  indeterminate: /\bindeterminate\b|\bundecid(ed|able)\b|\bnot decided\b|\brefuses? to decide\b|\bcannot be decided\b/i,
  "out-of-scope": /\bout[- ]of[- ]scope\b|\boutside the (collected )?evidence\b/i,
};
const HOP_FAMILY: Readonly<Record<HopVerdict, RegExp>> = {
  forwarded: /\bforward(s|ed)\b/i,
  delivered: OUTCOME_FAMILY.delivered,
  "no-route": /\bno[- ]route\b/i,
  denied: OUTCOME_FAMILY.denied,
  unmodeled: /\bunmodel+ed\b/i,
  loop: /\bloop(s|ed)?\b/i,
  "ttl-exceeded": /\bttl\b/i,
};
const VERDICT_FAMILIES: readonly RegExp[] = [...Object.values(OUTCOME_FAMILY), ...Object.values(HOP_FAMILY)];

/** Evidence quoted verbatim — `cite ("raw line text")` — is data the ACL holds, not our wording. */
const withoutQuotedEvidence = (s: string): string => s.replace(/\("[^"]*"\)/g, "");
const verdictWordsIn = (s: string): string[] => {
  const bare = withoutQuotedEvidence(s);
  return VERDICT_FAMILIES.flatMap((re) => bare.match(re)?.[0] ?? []);
};

/* ── what the engine attached to each suggested flow ────────────────────────────────────── */

interface Case {
  s: SuggestedFlow;
  t: Trace;
  /** The trace's own scope clause: the claim's opening clause, up to its first comma. */
  scope: string;
}
const cases: Case[] = suggestedFlows().map((s) => {
  const t = traceFlow(s.flow);
  return { s, t, scope: t.claim.slice(0, t.claim.indexOf(",")) };
});

/** The assertions every verdict-stating string must satisfy for its trace. Returns the failures. */
function boundsProblems(where: string, text: string, c: Case): string[] {
  const out: string[] = [];
  const n = c.t.caveats.length;
  if (!text.includes(c.scope)) out.push(`${where}: does not carry the trace's scope clause "${c.scope}"`);
  if (!new RegExp(`\\b${n} caveats?\\b`).test(text)) out.push(`${where}: does not carry the trace's caveat count (${n})`);
  if (!isDecidedOutcome(c.t)) {
    if (/blocking-hop answer/i.test(text)) out.push(`${where}: calls an undecided ${c.t.outcome} "the blocking-hop answer"`);
    if (/\bends (delivered|denied|dropped)\b/i.test(text)) out.push(`${where}: states a bare decided ending for an undecided trace`);
    const word = undecidedOutcomeWord(c.t);
    if (word !== null && !text.includes(word)) out.push(`${where}: does not state the claims owner's undecided word "${word}"`);
  }
  return out;
}

/** The suggested flow a string names in the palette's own flow format, if any (longest match wins). */
function flowNamedBy(text: string): Case | undefined {
  return cases
    .filter((c) => text.includes(formatFlow(c.s.flow)))
    .sort((a, b) => formatFlow(b.s.flow).length - formatFlow(a.s.flow).length)[0];
}

describe("B2 preconditions: the engine's own bounds, which every surface must carry", () => {
  it("offers suggested flows, and every one's claim opens with the 2-of-N-hosts scope clause", () => {
    expect(cases.length).toBeGreaterThan(0);
    for (const c of cases) {
      expect(c.scope, c.s.id).toMatch(/^Under the collected RIBs of /);
      expect(c.scope, c.s.id).toContain(`${fabric.coverage.hostsWithRoutes} of ${fabric.devices.length} hosts`);
      expect(c.t.caveats.length, c.s.id).toBeGreaterThan(0);
    }
  });

  it("and at least one of them is an undecided refusal — the case the palette mis-stated", () => {
    expect(cases.some((c) => c.t.outcome === "denied" && !isDecidedOutcome(c.t))).toBe(true);
  });
});

describe("a suggestion names a flow; it does not state an outcome", () => {
  it("no suggested flow's title or rationale uses verdict wording", () => {
    const offenders = cases.flatMap((c) =>
      [
        ["title", c.s.title],
        ["rationale", c.s.rationale],
      ].flatMap(([field, text]) => {
        const words = verdictWordsIn(text ?? "");
        return words.length === 0 ? [] : [`${c.s.id}.${field}: ${JSON.stringify(words)} in "${text}"`];
      }),
    );
    expect(offenders).toEqual([]);
  });
});

describe("the command palette states a suggested flow's verdict with its bounds", () => {
  it("the grammar example that teaches a trace", () => {
    const examples = grammarExamples().filter((e) => cases.some((c) => e.query.includes(c.s.flow.srcIp) && e.query.includes(c.s.flow.dstIp)));
    expect(examples.length, "the empty palette teaches no trace example").toBeGreaterThan(0);
    const problems = examples.flatMap((e) => {
      const c = cases.find((k) => e.query.includes(k.s.flow.srcIp) && e.query.includes(k.s.flow.dstIp) && (k.s.flow.dstPort === null || e.query.endsWith(`:${k.s.flow.dstPort}`)));
      if (c === undefined) return [`example "${e.query}" names no suggested flow exactly`];
      return verdictWordsIn(e.detail).length === 0 && !/\bends\b/.test(e.detail) ? [] : boundsProblems(`example "${e.query}"`, `${e.query} ${e.detail}`, c);
    });
    expect(problems).toEqual([]);
  });

  it("every command — found by what it says, not by its id — that states an outcome", () => {
    let stating = 0;
    const problems = allCommands().flatMap((cmd) => {
      const text = `${cmd.title} ${cmd.detail ?? ""}`;
      const c = flowNamedBy(text);
      const words = verdictWordsIn(text);
      if (c === undefined) {
        // A verdict word with no traced flow to bound it. Only the outcome enum's own families count
        // here: a hop word ("Next hop") is navigation, not a verdict.
        const outcomeWords = Object.values(OUTCOME_FAMILY).flatMap((re) => withoutQuotedEvidence(text).match(re)?.[0] ?? []);
        return outcomeWords.length === 0 ? [] : [`${cmd.id}: verdict wording ${JSON.stringify(outcomeWords)} with no traced flow named`];
      }
      if (words.length === 0) return [];
      stating += 1;
      return boundsProblems(cmd.id, text, c);
    });
    expect(problems).toEqual([]);
    // Non-vacuity: every suggested flow reaches the palette as a verdict-stating command.
    expect(stating).toBeGreaterThanOrEqual(cases.length);
  });

  it("the rendered rows for a typed source address (the report's own reproduction)", () => {
    mount(<CommandPalette />);
    act(() => useInvestigation.getState().setPaletteOpen(true));
    const input = document.querySelector<HTMLInputElement>(".palette__input");
    expect(input).not.toBeNull();
    let checked = 0;
    const problems: string[] = [];
    for (const src of [...new Set(cases.map((c) => c.s.flow.srcIp))]) {
      act(() => {
        Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set?.call(input, src);
        input!.dispatchEvent(new Event("input", { bubbles: true }));
      });
      for (const row of document.querySelectorAll<HTMLElement>('[role="option"]')) {
        const text = row.textContent ?? "";
        const c = flowNamedBy(text);
        if (c === undefined || verdictWordsIn(text).length === 0) continue;
        checked += 1;
        problems.push(...boundsProblems(`row for "${src}": ${formatFlow(c.s.flow)}`, text, c));
      }
    }
    expect(problems).toEqual([]);
    expect(checked, "no rendered row stated a suggested flow's verdict").toBeGreaterThanOrEqual(cases.length);
  });

  it("the live-region announcement a trace makes", () => {
    let said = "";
    function Probe(): null {
      said = useCommandAnnouncement();
      return null;
    }
    mount(<Probe />);
    const problems = cases.flatMap((c) => {
      act(() => runFlow(c.s.flow as Flow));
      return boundsProblems(`announcement for ${c.s.id}`, said, c);
    });
    expect(problems).toEqual([]);
  });
});

describe("the Path panel's presets state a suggested flow's verdict with its bounds", () => {
  /* WHERE A PRESET STATES ITS VERDICT (acceptance B6, wave 7). The whole card used to be the run
     button, so the button's text WAS the preset's statement and this test read it. The card was split
     so the citations it prints could be controls (a control cannot sit inside a button): the verdict
     and its bounds are now the card's own lines, beside the run button, and the button points at them
     with `aria-describedby`. So each of the two ways a reader meets the preset is asserted, and each
     must carry the bounds whole: the card as it is read, and the run button as it is announced (its
     name and its description together). */
  it("every preset card, in the engine's order", () => {
    const el = mount(<PathTrace />);
    const cards = [...el.querySelectorAll<HTMLElement>(".pt-preset")];
    expect(cards.length).toBe(cases.length);
    const problems = cards.flatMap((p, i) => boundsProblems(`preset ${cases[i]!.s.id}`, p.textContent ?? "", cases[i]!));
    expect(problems).toEqual([]);
  });

  it("every preset's run button, as it is announced: its name and its description", () => {
    const el = mount(<PathTrace />);
    const presets = [...el.querySelectorAll<HTMLElement>(".pt-preset__btn")];
    expect(presets.length).toBe(cases.length);
    const announced = (b: HTMLElement): string =>
      [
        b.textContent ?? "",
        ...(b.getAttribute("aria-describedby") ?? "")
          .split(/\s+/)
          .filter(Boolean)
          .map((id) => document.getElementById(id)?.textContent ?? ""),
      ].join(" ");
    const problems = presets.flatMap((p, i) => boundsProblems(`preset button ${cases[i]!.s.id}`, announced(p), cases[i]!));
    expect(problems).toEqual([]);
  });
});
