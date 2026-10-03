/**
 * trace-end.test.ts — the canvas glyph and the label chip mark the SAME hop (acceptance A5).
 *
 * THE DEFECT (independent refuter, A5, 2026-10-02): for 10.0.20.50 -> 10.0.30.10 tcp/22 the open
 * UNDECIDED ring hung over core1 — flow.ts put the glyph on the LAST hop — while the "? UNDECIDED"
 * chip sat on core2's label — Fabric3D.tsx `traceMarkOf` put it on the FIRST hop the claim layer
 * does not call RESOLVED. One trace told two stories about where it ends. Both now take the hop
 * and the ending from `traceEnd.ts :: traceEndOf`; these tests drive the REAL overlay with REAL
 * engine traces over the real cables and compare it with the chip's own function.
 */
import { describe, expect, it } from "vitest";
import fabricJson from "../data/fabric.json";
import type { Device, Flow, Link } from "../core/types";
import { suggestedFlows, traceFlow } from "../forwarding/engine";
import { computeLayout } from "./layout";
import { createFlowOverlay } from "./flow";
import { traceMarkOf } from "./Fabric3D";
import { readTokens } from "./materials";
import { profileFor } from "./quality";
import { buildFabricGraph, traceAnchorIn, tracePolylineIn } from "./scene";
import { traceEndOf } from "./traceEnd";

const devices = fabricJson.devices as Device[];
const links = fabricJson.links as Link[];
const layout = computeLayout({ devices, links, tiers: fabricJson.tiers });
const graph = buildFabricGraph({ devices, links, layout, theme: "dark", profile: profileFor("high") });
const source = {
  polylineBetween: (a: string, b: string) => tracePolylineIn(graph, a, b),
  anchorOf: (h: string) => traceAnchorIn(graph, h),
};

function sweptFlows(): Flow[] {
  const srcs = ["10.0.40.50", "10.0.41.50", "10.0.20.50", "10.0.10.50", "10.0.30.10", "10.0.20.10"];
  const dsts = ["10.0.10.50", "10.0.30.10", "198.51.100.7", "10.0.20.10", "10.0.41.50", "10.0.40.50", "8.8.8.8"];
  const out: Flow[] = [];
  for (const s of srcs) for (const d of dsts) for (const p of [22, 443, 3389]) {
    if (s !== d) out.push({ srcIp: s, dstIp: d, protocol: "tcp", dstPort: p, srcPort: null });
  }
  for (const s of suggestedFlows()) out.push(s.flow);
  return out;
}

/** What the canvas draws as the trace's ending: the glyph's host and which glyph, or null. */
function canvasEnding(flow: Flow): { host: string; glyph: "stop" | "ring" } | null {
  const overlay = createFlowOverlay(readTokens("dark"));
  try {
    overlay.setTrace(traceFlow(flow), 0, source);
    const marker = overlay.terminalMarker();
    if (marker === null) return null;
    const stop = overlay.emissiveObjects().find((o) => o.name === "trace-stop")?.visible === true;
    return { host: marker.host, glyph: stop ? "stop" : "ring" };
  } finally {
    overlay.dispose();
  }
}

describe("the glyph and the chip mark one hop, chosen by one rule (acceptance A5)", () => {
  it("the refuter's flow: the ring and the chip are both on core2", () => {
    const flow: Flow = { srcIp: "10.0.20.50", dstIp: "10.0.30.10", protocol: "tcp", dstPort: 22, srcPort: null };
    const t = traceFlow(flow);
    expect(t.hops.map((h) => h.host)).toEqual(["core2", "core1"]);
    expect(traceMarkOf(t)).toMatchObject({ host: "core2", kind: "undetermined" });
    expect(canvasEnding(flow)).toEqual({ host: "core2", glyph: "ring" });
  });

  it("for every swept flow, the glyph's hop and ending are the chip's", () => {
    const rows = sweptFlows().map((f) => ({ f, t: traceFlow(f) })).filter(({ t }) => t.hops.length > 0);
    // The sweep reaches every ending the canvas can draw, and multi-hop traces where the rules diverged.
    const kinds = new Set(rows.map(({ t }) => traceMarkOf(t)?.kind ?? "none"));
    expect([...kinds].sort()).toEqual(["blocked", "delivered", "undetermined"]);
    expect(rows.filter(({ t }) => (traceEndOf(t)?.index ?? -1) < t.hops.length - 1).length).toBeGreaterThan(0);

    const mismatches: string[] = [];
    for (const { f, t } of rows) {
      const chip = traceMarkOf(t);
      const glyph = canvasEnding(f);
      const want = chip === null || chip.kind === "delivered" ? null : { host: chip.host, glyph: chip.kind === "blocked" ? "stop" : "ring" };
      if (JSON.stringify(glyph) !== JSON.stringify(want)) {
        mismatches.push(`${f.srcIp}>${f.dstIp} tcp/${f.dstPort}: chip ${JSON.stringify(chip)} glyph ${JSON.stringify(glyph)}`);
      }
    }
    expect(mismatches).toEqual([]);
  });
});
