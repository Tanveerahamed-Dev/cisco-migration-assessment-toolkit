/**
 * HopList.undecided.test.tsx — a model gap is never worded as a collection gap.
 *
 * A2, 2026-09-21, over REAL flows traced by the real engine against the compiled snapshot:
 *
 *   tcp 10.0.10.50 -> 8.8.8.8:443 and icmp 10.0.10.50 -> 10.0.30.10 both stop at core1, which HAS
 *   a collected RIB. The route was decided (0.0.0.0/0 via 10.0.10.254; 10.0.30.0/24 connected), and
 *   the hop is undecided only because an ACL line cannot be evaluated. The hop said
 *   "not modelled — nothing was collected here to decide an egress from" and rendered no EGRESS.
 *
 *   tcp 10.0.40.50 -> 10.0.30.10:443 stops at dist1, which has NO RIB, and the hop still said
 *   "No other route in this host's collected RIB matched" — implying a RIB was searched.
 */
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";

import { hasRib } from "../core/data";
import type { Flow } from "../core/types";
import { traceFlow } from "../forwarding/engine";
import { HopList } from "./HopList";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

afterEach(() => {
  document.body.innerHTML = "";
});

const flow = (srcIp: string, dstIp: string, protocol: Flow["protocol"], dstPort: number | null): Flow => ({
  srcIp,
  dstIp,
  protocol,
  dstPort,
  srcPort: null,
});

function render(f: Flow): HTMLElement {
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  act(() => root.render(<HopList trace={traceFlow(f)} activeIndex={null} onSelect={() => {}} onOpenCite={() => {}} />));
  return host;
}

const hopOn = (c: HTMLElement, host: string): HTMLElement => {
  const hop = [...c.querySelectorAll<HTMLElement>(".hop")].find((h) => h.querySelector(".hop__host")?.textContent === host);
  expect(hop, `no hop on ${host} was rendered`).toBeDefined();
  return hop!;
};

const COLLECTION_BLAME = /nothing was collected here|no routing table was collected/i;

describe("an undecided hop on a host WITH a RIB names the model limit, not a collection gap", () => {
  for (const [label, f, egress] of [
    ["tcp 10.0.10.50 -> 8.8.8.8:443", flow("10.0.10.50", "8.8.8.8", "tcp", 443), null],
    ["icmp 10.0.10.50 -> 10.0.30.10", flow("10.0.10.50", "10.0.30.10", "icmp", null), "Vlan30"],
  ] as const) {
    it(label, () => {
      /* The host is read from the trace (the hop left undecided), not named: phase 3, 2026-09-28. */
      const at = traceFlow(f).hops.find((h) => h.verdict === "unmodeled")?.host;
      expect(at, "precondition: the flow stops at an undecided hop").toBeDefined();
      expect(hasRib(at!), `precondition: ${at} carries a collected RIB in this snapshot`).toBe(true);
      const hop = hopOn(render(f), at!);
      const text = hop.textContent ?? "";

      expect(text, "a host whose RIB was collected was described as having nothing collected").not.toMatch(COLLECTION_BLAME);
      const reason = hop.querySelector("[data-undecided-reason]")?.textContent ?? "";
      expect(reason, "the undecided verdict must name the ACL line that cannot be evaluated").toMatch(
        new RegExp(`ACL \\S+ line \\d+ of \\d+ on ${at!.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")} cannot be evaluated`),
      );
      const labels = [...hop.querySelectorAll("dt")].map((d) => d.textContent?.trim().toLowerCase());
      expect(labels, "the route was decided, so the egress it decided must be shown").toContain("egress");
      if (egress !== null) expect(text).toContain(egress);
    });
  }
});

/* "a hop on a host with NO RIB does not imply a RIB was searched" (tcp 10.0.40.50 -> 10.0.30.10:443 at
   dist1) moved 2026-09-28 (phase 3) to HopList.no-rib.counterfactual.test.tsx, unchanged: the regenerated
   sample collected dist1's RIB, and no trace of the real snapshot reaches a host without one any more. */
