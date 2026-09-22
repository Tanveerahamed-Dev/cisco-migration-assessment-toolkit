/**
 * Uppercase labels are tracked open, everywhere.
 *
 * A critic found the CRITICAL / HIGH group headers indistinguishable from the rows under them: set
 * in capitals at the 11px floor with the body's 0.01em tracking, a group header read as one more
 * line of metadata. The fix is a token, `--ls-caps`, and it is only a fix if it holds for the
 * CLASS — every rule that sets `text-transform: uppercase` — not for the one header that was
 * reported. So this walks every stylesheet under src/ and checks each such rule, rather than
 * naming the selectors that were changed.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const SRC = join(__dirname, "..");

function cssFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) return cssFiles(p);
    return p.endsWith(".css") ? [p] : [];
  });
}

interface Rule {
  file: string;
  selector: string;
  body: string;
}

function rules(file: string): Rule[] {
  const text = readFileSync(file, "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
  const out: Rule[] = [];
  // Innermost `selector { declarations }` blocks: a body containing no braces.
  for (const m of text.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    out.push({ file, selector: m[1]!.trim(), body: m[2]! });
  }
  return out;
}

describe("uppercase labels carry the caps tracking token", () => {
  const all = cssFiles(SRC).flatMap(rules);
  const caps = all.filter((r) => /text-transform:\s*uppercase/.test(r.body));

  it("finds uppercase rules to check (the walk is not vacuous)", () => {
    expect(caps.length).toBeGreaterThan(10);
  });

  it("every `text-transform: uppercase` rule sets letter-spacing: var(--ls-caps)", () => {
    const bad = caps
      .filter((r) => !/letter-spacing:\s*var\(--ls-caps\)/.test(r.body))
      .map((r) => `${r.file.slice(SRC.length + 1)} :: ${r.selector}`);
    expect(bad).toEqual([]);
  });

  it("the token is defined once in tokens.css, at a value that actually opens the tracking", () => {
    const tokens = readFileSync(join(SRC, "core", "tokens.css"), "utf8");
    const defs = [...tokens.matchAll(/--ls-caps:\s*([\d.]+)em;/g)];
    expect(defs).toHaveLength(1);
    expect(Number(defs[0]![1])).toBeGreaterThanOrEqual(0.05);
  });
});
