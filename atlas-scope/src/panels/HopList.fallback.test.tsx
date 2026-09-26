/**
 * HopList.fallback.test.tsx — an ACL row on the hop card carries its own qualifier, and a list the
 * address-specificity fallback applied says so on the card.
 *
 * A2, 2026-09-21 critic, over the real trace tcp 10.0.10.50 -> 8.8.8.8:443: the core1 hop card
 * showed a second, NON-deciding ACL row "INET_RETURN line 3 of 3 … deny ip any any" with no
 * qualifier. The engine's own wording for that line ("would match, but an earlier unevaluable line
 * may fire first") sat only inside the collapsed "Evidence consulted" list, and nothing on the card
 * said INET_RETURN is bound to no interface observed on this path — Vlan10 carries no access-group
 * in its observed running config; the list was applied only because the Gi1/0/5 binding is unknown.
 */
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";

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

function hopOn(f: Flow, host: string): HTMLElement {
  const el = document.createElement("div");
  document.body.appendChild(el);
  const root = createRoot(el);
  act(() => root.render(<HopList trace={traceFlow(f)} activeIndex={null} onSelect={() => {}} onOpenCite={() => {}} />));
  const hop = [...el.querySelectorAll<HTMLElement>(".hop")].find((h) => h.querySelector(".hop__host")?.textContent === host);
  expect(hop, `no hop on ${host} was rendered`).toBeDefined();
  return hop!;
}

/** The rendered fact rows only — NOT the collapsed evidence list, which is where the qualifier used to hide. */
const factRows = (hop: HTMLElement): HTMLElement[] => [...hop.querySelectorAll<HTMLElement>(".hop__facts > .hop__fact")];

describe("ACL rows on the hop card", () => {
  const INTERNET = flow("10.0.10.50", "8.8.8.8", "tcp", 443);

  it("a non-deciding ACL row states what the engine said the line does, outside the evidence list", () => {
    const hop = hopOn(INTERNET, "core1");
    const row = factRows(hop).find((f) => f.dataset.decided === undefined && /INET_RETURN line 3 of 3/.test(f.textContent ?? ""));
    expect(row, "precondition: the non-deciding INET_RETURN line 3 row is on the card").toBeDefined();
    expect(row!.textContent).toContain("deny ip any any");
    expect(row!.querySelector("[data-acl-qualifier]")?.textContent).toBe(
      "would match, but an earlier unevaluable line may fire first",
    );
  });

  it("every ACL row on the card carries a qualifier", () => {
    const hop = hopOn(INTERNET, "core1");
    const acls = factRows(hop).filter((f) => f.querySelector("dt")?.textContent?.startsWith("ACL") && f.querySelector(".hop__raw"));
    expect(acls.length).toBeGreaterThan(1);
    for (const r of acls) expect(r.querySelector("[data-acl-qualifier]")?.textContent ?? "").not.toBe("");
  });

  it("a list applied by the specificity fallback says so on the card and names the unobserved binding", () => {
    const hop = hopOn(INTERNET, "core1");
    const note = hop.querySelector(".hop__facts [data-acl-fallback]")?.textContent ?? "";
    expect(note).toContain("address-specificity fallback");
    expect(note).toContain("INET_RETURN");
    expect(note).toContain("the ACL binding at Gi1/0/5 was not observed");
  });

  it("a fallback list is never headlined as what decided the hop (2026-09-22 critic, A2)", () => {
    const hop = hopOn(INTERNET, "core1");
    for (const r of factRows(hop)) {
      if (/INET_RETURN/.test(r.querySelector(".hop__val")?.textContent ?? "") && r.querySelector("dt")?.textContent?.startsWith("ACL")) {
        expect(r.dataset.decided, "an unbound list's row is marked as the decider").toBeUndefined();
        expect(r.querySelector("dt")?.textContent).toContain("hypothesis");
      }
    }
    expect(hop.textContent).not.toContain("this is what decided the hop");
    expect(hop.querySelector("[data-undecided-reason]")?.textContent ?? "").toMatch(/^no observed filter binding on this hop — undecided/);
  });

  it("a list applied by an OBSERVED binding carries no fallback note", () => {
    /* PROTECT_SERVERS is bound outbound on core1 Vlan30 in the observed running configuration. */
    const hop = hopOn(flow("10.0.10.50", "10.0.30.10", "tcp", 443), "core1");
    expect(hop.textContent).toContain("PROTECT_SERVERS");
    expect(hop.querySelector("[data-acl-fallback]")).toBeNull();
  });
});
