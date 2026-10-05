/**
 * traceEnd.ts — the ONE rule for which hop a trace's ending is drawn on, and which ending it is.
 *
 * Two surfaces mark a trace's ending on the fabric: the DOM chip on a host's label
 * (Fabric3D.tsx `traceMarkOf`) and the billboarded terminal glyph beside the chassis (flow.ts). They
 * used to choose their hop by two different rules — the chip the FIRST hop the claim layer does not
 * call RESOLVED, the glyph the LAST hop — so a trace that crossed core2 -> core1 drew "? UNDECIDED"
 * on core2's label and the open ring over core1 (independent refuter, A5, 2026-10-02): one trace,
 * two places where its story ends. Both now ask this function, so they cannot disagree.
 */
import { bandOfHopIn, bandOfTrace } from "../core/claims";
import type { Trace } from "../core/types";

/**
 * THE FABRIC HAS THREE ENDINGS FOR A TRACE, NOT TWO, AND IT DOES NOT DECIDE THEM HERE.
 *
 * It used to hold a hand-written set of "failing verdicts" with `unmodeled` folded in beside
 * `denied`. The intent was right — a hop the engine could not model is not a hop that succeeded —
 * but the rendering was not: an indeterminate hop was drawn with the denied treatment and the word
 * BLOCKED, byte-for-byte identical to a genuinely denied flow, while the side panel for the very
 * same trace said INDETERMINATE. `claims.ts :: bandOfHop` is the one owner of the
 * verdict -> disposition mapping (REFUTED / UNDETERMINED / RESOLVED), and the fabric asks it.
 */
export type TraceMarkKind =
  /** REFUTED: the traced packet was stopped here, and the engine says by what. */
  | "blocked"
  /** UNDETERMINED: the simulation ran and declined to decide. Not a stop, not a delivery. */
  | "undetermined"
  /** RESOLVED: the traced packet reached its destination at this hop. */
  | "delivered";

export interface TraceEnd {
  /** Index into `trace.hops` of the hop the ending is drawn on. */
  index: number;
  host: string;
  kind: TraceMarkKind;
}

/**
 * Where the traced packet's story ends on the fabric, and WHICH of the three endings it is.
 *
 * The ENDING is the trace's own band (`claims.ts :: bandOfTrace`), so neither mark can promise more
 * or less than the claim card: blocked only for a REFUTED trace, delivered only for a RESOLVED one,
 * undetermined otherwise. The HOP follows hop order, never verdict severity:
 *   - a REFUTED trace ends at the first hop the claim layer calls REFUTED in this trace — the stop
 *     the card names (a hop before it whose own filtering was left open does not move the decided
 *     denial off the host that denies);
 *   - otherwise the story ends at the first hop the claim layer does not call RESOLVED: that is where
 *     the packet stops being decidable;
 *   - a trace every hop of which resolved ends at its last hop: `delivered` only when that hop says
 *     `delivered` and the trace is RESOLVED. A run of `forwarded` hops that simply ran out is not a
 *     delivery, and marking it as one would be this defect with the sign flipped; it is marked as
 *     undetermined when the trace is, and not at all when the trace resolved.
 */
export function traceEndOf(trace: Trace | null): TraceEnd | null {
  if (!trace || trace.hops.length === 0) return null;
  /* The band of each hop IN ITS TRACE (`bandOfHopIn`), never the context-free verdict band. The
     context-free one drew "✓ DELIVERED HERE" on core1 for a delivery whose own card and hop list
     said filtering there was never decided (2026-09-21 critic, B1): the same trace, two answers. */
  const bands = trace.hops.map((h) => bandOfHopIn(h, trace));
  const band = bandOfTrace(trace);
  const at = (index: number, kind: TraceMarkKind): TraceEnd | null => {
    const hop = trace.hops[index];
    return hop === undefined ? null : { index, host: hop.host, kind };
  };
  if (band === "REFUTED") {
    const refuted = bands.indexOf("REFUTED");
    if (refuted >= 0) return at(refuted, "blocked");
  }
  const open = bands.findIndex((b) => b !== "RESOLVED");
  if (open >= 0) return at(open, "undetermined");
  const lastIndex = trace.hops.length - 1;
  if (trace.hops[lastIndex]?.verdict === "delivered") return at(lastIndex, band === "RESOLVED" ? "delivered" : "undetermined");
  return band === "RESOLVED" ? null : at(lastIndex, "undetermined");
}
