import { describe, it, expect } from "vitest";
import { czSev, czWidth, wrap } from "./CausalFlow";

// Severity normaliser: maps the engine's free-ish severity strings onto the fixed 5-band scale.
describe("czSev", () => {
  it("maps any 'crit' variant to Critical, case-insensitively", () => {
    expect(czSev("critical")).toBe("Critical");
    expect(czSev("CRITICAL")).toBe("Critical");
    expect(czSev("Crit")).toBe("Critical");
  });

  it("folds high / warning / error into High", () => {
    expect(czSev("high")).toBe("High");
    expect(czSev("HIGH")).toBe("High");
    expect(czSev("warning")).toBe("High");
    expect(czSev("error")).toBe("High");
  });

  it("maps med* to Medium and low* to Low", () => {
    expect(czSev("medium")).toBe("Medium");
    expect(czSev("med")).toBe("Medium");
    expect(czSev("low")).toBe("Low");
  });

  it("passes through an exact canonical band, and defaults unknown/empty to Info", () => {
    expect(czSev("Info")).toBe("Info");
    expect(czSev("")).toBe("Info");
    expect(czSev("banana")).toBe("Info");
  });
});

// Sankey connector width ∝ blast magnitude, on a log scale, clamped so one huge flow can't dominate.
describe("czWidth", () => {
  it("returns the floor width for a zero / missing blast", () => {
    expect(czWidth(0)).toBe(2.6);
    expect(czWidth(undefined as unknown as number)).toBe(2.6);
  });

  it("grows with the log of the blast (rounded to 1dp)", () => {
    expect(czWidth(1)).toBe(3.8); // 2.6 + log2(2)*1.18 = 3.78 → 3.8
    expect(czWidth(3)).toBe(5); // 2.6 + log2(4)*1.18 = 4.96 → 5.0
  });

  it("clamps the log term at 8.6 so a huge flow tops out at 11.2", () => {
    expect(czWidth(1_000_000)).toBe(11.2);
    expect(czWidth(1_000_000_000)).toBe(11.2);
  });

  it("is monotonic non-decreasing in the blast", () => {
    expect(czWidth(10)).toBeLessThanOrEqual(czWidth(100));
    expect(czWidth(100)).toBeLessThanOrEqual(czWidth(1000));
  });
});

// Greedy word-wrap into ≤maxLines lines of ≤maxChars, ellipsising the last line when truncated.
describe("wrap", () => {
  it("returns a single em-dash placeholder for empty / whitespace input", () => {
    expect(wrap("", 10, 2)).toEqual(["—"]);
    expect(wrap("   ", 10, 2)).toEqual(["—"]);
  });

  it("keeps a short string on one line", () => {
    expect(wrap("short", 10, 2)).toEqual(["short"]);
  });

  it("greedily wraps words across lines that fit within maxChars", () => {
    expect(wrap("the quick brown fox", 10, 3)).toEqual(["the quick", "brown fox"]);
  });

  it("ellipsises the last line when content overflows maxLines", () => {
    const out = wrap("one two three four five", 8, 2);
    expect(out).toHaveLength(2);
    expect(out[0]).toBe("one two");
    expect(out[1].endsWith("…")).toBe(true);
  });
});
