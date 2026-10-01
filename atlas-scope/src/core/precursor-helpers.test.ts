import { describe, expect, it } from "vitest";
import { GOLDEN_SHA, SAMPLE_SOURCE, describeGolden, isGoldenSample } from "../test-support/golden-sample";
import { fabric } from "./data";
import { listPhrase } from "./phrases";
import { normalizeRole, roleGlyphClass } from "./roles";

describe("golden tier binding (an invariant: holds on any dataset)", () => {
  it("isGoldenSample() is exactly digest equality, and the tracked sample can only ever load as golden", () => {
    expect(isGoldenSample()).toBe(fabric.meta.sourceSha256 === GOLDEN_SHA);
    // Reaching this line on the tracked sample proves the import-time guard let it through, i.e. it IS golden.
    expect(fabric.meta.source !== SAMPLE_SOURCE || isGoldenSample()).toBe(true);
  });
});

describeGolden("the reference sample", () => {
  it("runs the golden tier (this block is skipped by name on any other dataset)", () => {
    expect(fabric.meta.source).toBe(SAMPLE_SOURCE);
    expect(fabric.meta.sourceSha256).toBe(GOLDEN_SHA);
  });
});

describe("roles: one owner for how an observed role reads", () => {
  it("normalises case and whitespace, and treats missing/blank/non-string as not observed", () => {
    expect(normalizeRole("  Core ")).toBe("core");
    expect(normalizeRole("DISTRIBUTION")).toBe("distribution");
    for (const absent of [null, undefined, "", "   ", 7, {}]) expect(normalizeRole(absent)).toBeNull();
  });
  it("an observed role outside access/distribution is 'other', never 'unobserved'", () => {
    for (const r of ["core", "Spine", "superspine", "backbone", "wan-edge"]) expect(roleGlyphClass(r)).toBe("other");
    expect(roleGlyphClass("Access")).toBe("access");
    expect(roleGlyphClass(" distribution")).toBe("distribution");
    expect(roleGlyphClass(null)).toBe("unobserved");
  });
});

describe("listPhrase: one owner for joining names into prose", () => {
  it("always yields a phrase, with the empty wording when there is nothing", () => {
    expect(listPhrase([])).toBe("no host");
    expect(listPhrase(["", ""])).toBe("no host");
    expect(listPhrase([], "no device")).toBe("no device");
    expect(listPhrase(["core1"])).toBe("core1");
    expect(listPhrase(["core1", "core2"])).toBe("core1 and core2");
    expect(listPhrase(["a", "b", "c"])).toBe("a, b and c");
  });
});
