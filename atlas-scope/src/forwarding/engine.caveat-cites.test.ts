/**
 * engine.caveat-cites.test.ts — the two caveats deferred from E2 (p25-R2 escalations), held as invariants
 * over whatever fabric is loaded:
 *
 *  1. The binding-coverage sentence ("dist1: 0 interface ACL bindings were observed.") named a device and
 *     cited nothing. A count of zero is a statement about records; every clause of every binding-coverage
 *     sentence that names a device now carries a citation that names a record (acceptance B6).
 *  2. The ingress-choice caveat said "not a guarantee — traffic may enter via dist2" even when the flow had
 *     been TRACED from dist2 and ended the same way with nothing left open, so a SCOPED verdict sat beside
 *     a caveat calling its own ingress unguaranteed. The caveat now names an alternate as traced exactly
 *     when the engine's own alternate-ingress check reproduced the outcome (no `ingress-alternate` gap for
 *     it), and keeps "may enter via" for every alternate that did not.
 */
import { describe, expect, it } from "vitest";
import { claimBadge } from "../core/claims";
import { fabric, resolveCite } from "../core/data";
import type { Flow } from "../core/types";
import { bindingCoverageSentences } from "./bindings";
import { ingressCandidates, suggestedFlows, traceFlow, unobservedPolicyInputs } from "./engine";
import { formatIpv4, hostAddressIn, parseInterfaceAddress, parseIpv4 } from "./ip";
import { lazy, needSome } from "../test-support/test-subjects";

/** Every `cite` a compiled record carries — endpoint and l3 cites are source-snapshot paths resolveCite does not walk. */
const RECORD_CITES: ReadonlySet<string> = (() => {
  const out = new Set<string>();
  const walk = (v: unknown): void => {
    if (Array.isArray(v)) for (const x of v) walk(x);
    else if (v !== null && typeof v === "object") {
      const c = (v as Record<string, unknown>)["cite"];
      if (typeof c === "string") out.add(c);
      for (const x of Object.values(v)) walk(x);
    }
  };
  walk(fabric);
  return out;
})();
const namesARecord = (c: string): boolean => resolveCite(c) !== undefined || RECORD_CITES.has(c);

/** Citation-shaped tokens: a dotted record path, optionally indexed (interfaces.dist1, acls.core1.X[3], l3_forwarding[5]). */
const citationsIn = (s: string): string[] => s.match(/\b(?:[a-z_]+(?:\.[A-Za-z0-9_/-]+)+(?:\[\d+\])?|[a-z_]+\[\d+\])/g) ?? [];

/** Sentences, then `;`-separated items, splitting only OUTSIDE parentheses — the unit a citation backs. */
function clauses(text: string): string[] {
  const out: string[] = [];
  let depth = 0;
  let cur = "";
  for (let i = 0; i < text.length; i += 1) {
    const ch = text[i]!;
    if (ch === "(") depth += 1;
    if (ch === ")") depth = Math.max(0, depth - 1);
    cur += ch;
    const next = text.slice(i + 1, i + 3);
    if (depth === 0 && ((ch === ";" && /^\s/.test(next)) || (ch === "." && /^\s[A-Z"]/.test(next)))) {
      out.push(cur);
      cur = "";
    }
  }
  out.push(cur);
  return out.filter((c) => c.trim() !== "");
}

const HOSTS = [...new Set(fabric.devices.map((d) => d.host))];
const namesDevice = (clause: string): boolean => HOSTS.some((h) => new RegExp(`(?<![\\w.-])${h.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}(?![\\w-])`).test(clause));

describe("E2 deferred: the binding-coverage sentence cites the records it counted", () => {
  const sentencesOf = lazy(() => bindingCoverageSentences());

  it("there is one sentence per host holding collected ACLs (the precondition)", (ctx) => {
    const sentences = sentencesOf();
    const aclHosts = Object.keys(fabric.acls).filter((h) => Object.keys(fabric.acls[h] ?? {}).length > 0);
    expect(sentences.length).toBe(aclHosts.length);
    needSome(ctx, sentences.length, "host holding collected ACLs");
  });

  it("every clause that names a device carries a citation naming a record", (ctx) => {
    const offenders: string[] = [];
    let named = 0;
    for (const s of sentencesOf())
      for (const c of clauses(s)) {
        if (!namesDevice(c)) continue;
        named += 1;
        if (!citationsIn(c).some(namesARecord)) offenders.push(c);
      }
    expect(offenders).toEqual([]);
    needSome(ctx, named, "binding-coverage clause naming a device");
  });

  it("a host with NO observed binding still cites what the zero was counted over", (ctx) => {
    let zeros = 0;
    for (const s of sentencesOf()) {
      const m = /^(\S+): 0 interface ACL bindings were observed/.exec(s);
      if (m === null) continue;
      zeros += 1;
      const first = clauses(s)[0]!;
      expect(citationsIn(first).some(namesARecord), first).toBe(true);
    }
    /* The 7-device golden snapshot binds an ACL somewhere on every ACL host, so this ran ZERO assertions there
       (2026-09-28 verifier, D2): the branch is now required on the reference sample and named elsewhere. */
    needSome(ctx, zeros, "ACL-holding host with zero observed interface ACL bindings");
  });
});

/** Sources: one host address in every observed SVI subnet, plus every suggested flow's source. */
function flows(): Flow[] {
  const srcs = new Set<string>(suggestedFlows().map((s) => s.flow.srcIp));
  const dsts = new Set<string>(suggestedFlows().map((s) => s.flow.dstIp));
  for (const r of fabric.l3) {
    const a = r.sviIp === null ? null : parseInterfaceAddress(r.sviIp);
    const h = a === null ? null : hostAddressIn(a.prefix, 50);
    const d = a === null ? null : hostAddressIn(a.prefix, 10);
    if (h !== null) srcs.add(formatIpv4(h));
    if (d !== null) dsts.add(formatIpv4(d));
  }
  const out: Flow[] = suggestedFlows().map((s) => s.flow);
  for (const s of srcs) for (const d of dsts) for (const p of [22, 443, 3389]) if (s !== d) out.push({ srcIp: s, dstIp: d, protocol: "tcp", dstPort: p, srcPort: null });
  return out;
}

describe("E2 deferred: the ingress-choice caveat says what the alternate-ingress check found", () => {
  const tracesOf = lazy(() => flows().map(traceFlow));

  it("an alternate is called 'may enter via' exactly when the trace carries an ingress-alternate gap for it, and 'traced' otherwise", (ctx) => {
    const traces = tracesOf();
    let withChoice = 0;
    let traced = 0;
    let open = 0;
    for (const t of traces) {
      const src = parseIpv4(t.flow.srcIp);
      const first = t.hops[0];
      if (src === null || first === undefined) continue;
      const cands = ingressCandidates(src);
      if (cands.length < 2 || cands[0]!.host !== first.host) continue;
      const caveat = t.caveats.find((c) => c.includes("was taken as ingress") && c.includes("collected SVIs"));
      if (caveat === undefined) continue;
      withChoice += 1;
      const gapHosts = new Set(unobservedPolicyInputs(t).filter((g) => g.kind === "ingress-alternate").map((g) => g.host));
      const where = `${JSON.stringify(t.flow)} :: ${caveat}`;
      for (const alt of cands.slice(1)) {
        const mayEnter = new RegExp(`may enter via [^.;]*\\b${alt.host}\\b`).test(caveat);
        const tracedWith = new RegExp(`traced with [^.;]*\\b${alt.host}\\b[^.;]* as its ingress`).test(caveat);
        if (gapHosts.has(alt.host)) {
          expect(mayEnter, `${where}: ${alt.host} has an ingress gap, so it may be the ingress`).toBe(true);
          expect(tracedWith, where).toBe(false);
          open += 1;
        } else if (tracedWith) {
          expect(mayEnter, `${where}: ${alt.host} was traced and reproduced the result`).toBe(false);
          traced += 1;
        } else {
          /* Neither a gap nor a traced reproduction: the alternate could not be placed as ingress. */
          expect(mayEnter, where).toBe(true);
        }
      }
      if (gapHosts.size === 0 && cands.slice(1).every((a) => new RegExp(`traced with [^.;]*\\b${a.host}\\b`).test(caveat))) {
        expect(caveat, where).not.toMatch(/not a guarantee|may (instead )?enter via/);
      }
    }
    /* Each branch is a property of the data: all three are required on the reference sample; on a fleet with
       no FHRP choice, or none whose alternate reproduces the outcome, the missing branch is named. */
    needSome(ctx, withChoice, "trace resting on an FHRP / shared-subnet ingress choice");
    needSome(ctx, open, "alternate ingress that did NOT reproduce the outcome (the 'may enter via' branch)");
    needSome(ctx, traced, "alternate ingress that DID reproduce the outcome (the 'traced' branch)");
  });

  it("no SCOPED trace carries an ingress caveat calling its own ingress unguaranteed", (ctx) => {
    let scoped = 0;
    for (const t of tracesOf()) {
      if (claimBadge(t) !== "SCOPED") continue;
      scoped += 1;
      expect(t.caveats.some((c) => /may (instead )?enter via|not a guarantee/.test(c)), JSON.stringify(t.flow)).toBe(false);
    }
    needSome(ctx, scoped, "SCOPED trace in the sweep");
  });
});
