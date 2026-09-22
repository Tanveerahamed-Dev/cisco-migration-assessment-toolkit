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
      expect(hasRib("core1"), "precondition: core1 carries a collected RIB in this snapshot").toBe(true);
      const hop = hopOn(render(f), "core1");
      const text = hop.textContent ?? "";

      expect(text, "a host whose RIB was collected was described as having nothing collected").not.toMatch(COLLECTION_BLAME);
      const reason = hop.querySelector("[data-undecided-reason]")?.textContent ?? "";
      expect(reason, "the undecided verdict must name the ACL line that cannot be evaluated").toMatch(
        /ACL \S+ line \d+ of \d+ on core1 cannot be evaluated/,
      );
      const labels = [...hop.querySelectorAll("dt")].map((d) => d.textContent?.trim().toLowerCase());
      expect(labels, "the route was decided, so the egress it decided must be shown").toContain("egress");
      if (egress !== null) expect(text).toContain(egress);
    });
  }
});

describe("a hop on a host with NO RIB does not imply a RIB was searched", () => {
  it("tcp 10.0.40.50 -> 10.0.30.10:443 at dist1", () => {
    expect(hasRib("dist1"), "precondition: dist1 has no collected RIB in this snapshot").toBe(false);
    const hop = hopOn(render(flow("10.0.40.50", "10.0.30.10", "tcp", 443)), "dist1");
    expect(hop.textContent).not.toMatch(/collected RIB matched/);
    expect(hop.textContent, "the no-RIB case keeps its collection-gap wording").toMatch(/no routing table was collected/);
  });
});
