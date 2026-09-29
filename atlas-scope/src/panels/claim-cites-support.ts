/**
 * claim-cites-support.ts — the per-CLAUSE citation checks of acceptance B6, shared by the tests that run
 * them (PathTrace.claim-cites.test.tsx over the real snapshot, and the counterfactual files over the
 * branches the real snapshot no longer reaches).
 *
 * TEST SUPPORT ONLY (imported by `*.test.tsx` files in this directory, never by the product). Moved here
 * unchanged from PathTrace.claim-cites.test.tsx on 2026-09-28 (phase 3), so a counterfactual file can hold
 * a dropped trace to exactly the same rule the real sweep holds every other outcome to.
 */
import { fabric } from "../core/data";
import type { Trace } from "../core/types";
import { scopeClauseOf } from "../forwarding/engine";
import { resolveCitation } from "./Inspector";
import { citesIn } from "./cited-text";

/* What makes a clause a claim about THIS network rather than about the model: it names a collected
   device or an address. Read from the compiled fabric, never listed. */
let hostRe: RegExp | null = null;
function hostPattern(): RegExp {
  if (hostRe !== null) return hostRe;
  const hosts = [...new Set(fabric.devices.map((d) => d.host))].sort((a, b) => b.length - a.length);
  hostRe = new RegExp(`(?<![\\w.-])(?:${hosts.map((h) => h.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})(?![\\w-])`);
  return hostRe;
}
const IPV4_RE = /(?<![\w.])\d{1,3}(?:\.\d{1,3}){3}(?![\w])/;
export const namesEvidence = (clause: string): boolean => hostPattern().test(clause) || IPV4_RE.test(clause);

/**
 * Sentences, then `;`-separated items — the unit a reader quotes, and the unit a citation backs. Only
 * punctuation OUTSIDE parentheses splits: a parenthetical is part of the clause it qualifies.
 */
export function clauses(text: string): string[] {
  /* Citations are masked first so a dotted path never splits a clause. */
  const masked: string[] = [];
  let t = text;
  for (const c of citesIn(text)) t = t.replace(c, () => `\u0001${masked.push(c) - 1}\u0002`);
  const out: string[] = [];
  let depth = 0;
  let cur = "";
  for (let i = 0; i < t.length; i += 1) {
    const ch = t[i]!;
    if (ch === "(") depth += 1;
    if (ch === ")") depth = Math.max(0, depth - 1);
    const next = t.slice(i + 1, i + 3);
    const boundary = depth === 0 && ((ch === ";" && /^\s/.test(next)) || (ch === "." && /^\s[A-Z"]/.test(next)));
    cur += ch;
    if (boundary) {
      out.push(cur);
      cur = "";
    }
  }
  out.push(cur);
  return out.map((s) => s.replace(/\u0001(\d+)\u0002/g, (_, i: string) => masked[Number(i)]!)).filter((s) => s.trim() !== "");
}

export function uncitedClauses(text: string): string[] {
  return clauses(text).filter((c) => namesEvidence(c) && !citesIn(c).some((x) => resolveCitation(x).kind !== "unresolved"));
}

/**
 * A claim's scope clause is the coverage denominator (acceptance B2): it names the RIB hosts, and the
 * record behind it is the coverage matrix the card's own scope block cites beside it ("RIBs" row,
 * checked in the rendered sweep). It is judged there, not here — counted here, its one citation would
 * vouch for every clause after it in the sentence, which is the per-page count again.
 */
export function withoutScope(t: Trace): string {
  const scope = scopeClauseOf(t);
  return scope === null ? t.claim : t.claim.slice(scope.length);
}

const citeOf = (b: Element): string => (b.getAttribute("aria-label") ?? "").replace(/^Open source record /, "");
export const controlsIn = (el: Element): string[] => [...el.querySelectorAll(".ui-cite")].map(citeOf);

/* The rendered side: every prose element of the claim card and the hop list. Each in-text citation is a
   working control (never inert text), and an element that names a device or an address shows at least
   one control that resolves. */
export const PROSE =
  ".claim__sentence, .claim__undetermined, .claim__scope-line, .claim__scope-list > li, .claim__caveats > li, .claim__counter-why, .claim__counter-none, .claim__reasons > li, .claim__pair dd, .hop__note, .hop__ev";

export function renderedOffenders(root: Element): string[] {
  const out: string[] = [];
  for (const el of root.querySelectorAll(PROSE)) {
    const text = el.textContent ?? "";
    const controls = controlsIn(el);
    for (const c of citesIn(text)) if (!controls.includes(c)) out.push(`inert citation ${c} :: ${text}`);
    if (namesEvidence(text) && !controls.some((c) => resolveCitation(c).kind !== "unresolved")) out.push(`no citation :: ${text}`);
  }
  return out;
}
