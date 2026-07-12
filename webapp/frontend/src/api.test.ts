import { describe, expect, it } from "vitest";
import { bandColor, gateColor, readyColor, sevColor, sevSoft } from "./api";

// The shared colour helpers map the engine's category vocabulary onto CSS custom-property names
// (with a fallback var). The contract worth pinning: the label is squashed into a token, and the
// fallback / suffix differ per family — a drift here silently mis-colours every severity chip, band,
// and gate in the cockpit. (src/api.ts colour helpers.)
describe("colour token helpers", () => {
  it("sevColor squashes whitespace into the --sev token with a faint fallback", () => {
    expect(sevColor("High")).toBe("var(--sev-High, var(--text-faint))");
    expect(sevColor("High Risk")).toBe("var(--sev-HighRisk, var(--text-faint))");
    expect(sevColor("High   Risk")).toBe("var(--sev-HighRisk, var(--text-faint))"); // \s+ collapses runs
  });

  it("sevSoft carries the -soft suffix and a DIFFERENT (surface) fallback", () => {
    expect(sevSoft("High Risk")).toBe("var(--sev-HighRisk-soft, var(--surface-3))");
  });

  it("bandColor and readyColor use their own token families", () => {
    expect(bandColor("Band A")).toBe("var(--band-BandA, var(--text-faint))");
    expect(readyColor("Not Ready")).toBe("var(--ready-NotReady, var(--text-faint))");
  });

  it("gateColor ALSO strips hyphens — the one helper that does (GO/NO-GO gate labels)", () => {
    expect(gateColor("GO")).toBe("var(--gate-GO, var(--text-faint))");
    expect(gateColor("NO-GO")).toBe("var(--gate-NOGO, var(--text-faint))");
    expect(gateColor("NO GO")).toBe("var(--gate-NOGO, var(--text-faint))");
  });

  it("the hyphen behaviour is what distinguishes gateColor from the others", () => {
    // a hyphen SURVIVES in the sev token but is stripped in the gate token — the meaningful contrast
    expect(sevColor("A-B")).toBe("var(--sev-A-B, var(--text-faint))");
    expect(gateColor("A-B")).toBe("var(--gate-AB, var(--text-faint))");
  });

  it("an empty label still yields a well-formed var() (no crash, honest empty token)", () => {
    expect(sevColor("")).toBe("var(--sev-, var(--text-faint))");
  });
});
