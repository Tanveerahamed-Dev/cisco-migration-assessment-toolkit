import { describe, expect, it } from "vitest";
import { COMPARISON_RECEIPT_SUFFIX, safeFilename } from "./ComparisonDecision";

// W65: a downloaded comparison receipt is the "comparison-receipt" client-artifact class
// (cisco_toolkit/distribution_verify.py :: CLIENT_ARTIFACT_NAME_CLASSES). Its file name must end in the
// registered suffix whatever name a caller passes, or the privacy gates and .gitignore cannot see it.
describe("comparison receipt download names", () => {
  it("keeps a name that already ends in the registered suffix", () => {
    expect(COMPARISON_RECEIPT_SUFFIX).toBe(".comparison.json");
    expect(safeFilename("execution-7-receipt-3.comparison.json")).toBe("execution-7-receipt-3.comparison.json");
    expect(safeFilename("Atlas-Campaign-3-1-2.COMPARISON.JSON")).toBe("Atlas-Campaign-3-1-2.COMPARISON.JSON");
  });

  it("appends the suffix to a caller name that lacks it (negative control: the old names)", () => {
    expect(safeFilename("execution-7-comparison-receipt-3.json")).toBe("execution-7-comparison-receipt-3.comparison.json");
    expect(safeFilename("atlas-campaign-3-1-2-comparison.json")).toBe("atlas-campaign-3-1-2-comparison.comparison.json");
    expect(safeFilename("receipt")).toBe("receipt.comparison.json");
  });

  it("falls back to a registered default and strips unsafe characters", () => {
    expect(safeFilename("   ")).toBe("atlas-receipt.comparison.json");
    expect(safeFilename("../a b/c.json")).toBe("..-a-b-c.comparison.json");
    for (const name of ["", "x", "a.json", "a.comparison.json", "../../etc"]) {
      expect(safeFilename(name).toLowerCase().endsWith(COMPARISON_RECEIPT_SUFFIX)).toBe(true);
    }
  });
});
