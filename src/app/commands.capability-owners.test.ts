/**
 * commands.capability-owners.test.ts — an advertised verb must be a built verb.
 *
 * THE DEFECT THIS PINS. `acl.toggleCounterfactual` sat in the `Capability` union with a palette
 * row, a keyword list and the shortcut `M` for the life of the build. Nothing anywhere registered
 * a target or published a `data-atlas-command` owner for it, so `capabilityAvailable()` was
 * permanently false — and the palette therefore explained the absence with
 * `capabilityReason()`: "the path panel is not on screen in this layout, so this action has
 * nothing to act on." That sentence was rendered WITH the path panel on screen and a trace drawn.
 * An unbuilt feature was presented as a situational one, with a reason that was false on the
 * reader's screen.
 *
 * WHY THIS TEST IS SOURCE-LEVEL RATHER THAN RUNTIME. A runtime test would have to mount every
 * surface in every layout to prove a capability has an owner somewhere, and a capability whose
 * owner only mounts in a layout the test forgot would pass. The question is not "is this owned on
 * this screen" — `capabilityAvailable()` answers that, correctly, at render time. The question is
 * "does an owner exist AT ALL in the product", and that is a property of the source text.
 *
 * It is deliberately a whole-class check, not a list of known-good capabilities: a fix that is a
 * slightly longer allowlist is not a fix.
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const SRC = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const COMMANDS = join(SRC, "app", "commands.ts");

/** Every `.ts`/`.tsx` file under `src/` that is NOT a test — a test may not own a capability. */
function sourceFiles(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      out.push(...sourceFiles(full));
      continue;
    }
    if (!/\.tsx?$/.test(entry)) continue;
    if (/\.test\.tsx?$/.test(entry)) continue;
    out.push(full);
  }
  return out;
}

/** The `Capability` union, read from the source of truth rather than restated here. */
function declaredCapabilities(): string[] {
  const src = readFileSync(COMMANDS, "utf8");
  const block = /export type Capability =([\s\S]*?);/.exec(src);
  expect(block, "the Capability union must be declared in commands.ts").not.toBeNull();
  const names = [...(block?.[1] ?? "").matchAll(/"([^"]+)"/g)].map((m) => m[1] ?? "");
  expect(names.length, "the Capability union parsed as empty — the regex has drifted").toBeGreaterThan(0);
  return names;
}

describe("every declared capability has an owner in the product", () => {
  const capabilities = declaredCapabilities();
  const files = sourceFiles(SRC).filter((f) => f !== COMMANDS);
  const corpus = files.map((f) => readFileSync(f, "utf8")).join("\n");

  it.each(capabilities)("%s is registered or published by a non-test source file", (cap) => {
    const registered = corpus.includes(`registerCommandTarget("${cap}"`);
    const domOwned =
      corpus.includes(`data-atlas-command="${cap}"`) || corpus.includes(`"data-atlas-command": "${cap}"`);
    expect(
      registered || domOwned,
      `Capability "${cap}" has no registerCommandTarget() call and no data-atlas-command owner in src/. ` +
        `A palette row for it would render as merely unavailable, explaining an UNBUILT feature as a ` +
        `layout condition. Either build an owner or remove the capability.`,
    ).toBe(true);
  });

  it("scanned a corpus that could actually have contained an owner", () => {
    /* A greppable-corpus test that silently walked an empty directory would pass forever. */
    expect(files.length).toBeGreaterThan(20);
    expect(corpus).toContain("registerCommandTarget(");
    expect(corpus).toContain("data-atlas-command=");
  });
});
