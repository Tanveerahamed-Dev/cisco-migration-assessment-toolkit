// @vitest-environment node
/**
 * wrap-licence.test.ts — the token-break licence gate runs in the unit suite, not only in a capture
 * (acceptance C2 regression, repair wave 8).
 *
 * WHAT WENT WRONG. Commit 34bd435 added `overflow-wrap: anywhere` to `.palette__matched` — a prose
 * block — and reported "vitest 3699/3699" while `node review/capture.mjs text` failed C2 with
 * "wrap licence without justification: src/app/CommandPalette.css:276". The licence scan lived ONLY
 * in the capture script, which needs a running server and was not run, so the suite that was run
 * could not see it. `anywhere` on prose is what split "(num_power_supplie / s)" (the "wrapping"
 * owner in src/ui/primitives.css).
 *
 * THE GATE. `node review/capture.mjs wrap` is static — it reads src/ and starts no browser and no
 * server — so it runs here, through the real script rather than a copy of its rule: a second copy
 * of the rule would drift from the one the capture enforces. Asserted on the script's own exit code
 * and its own verdict line, both of which it prints only after scanning every stylesheet and module.
 */
import { spawnSync } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");

describe("every token-break licence in src/ is justified (C2, capture.mjs wrap)", () => {
  it("`node review/capture.mjs wrap` exits 0 and prints its PASS line", () => {
    const run = spawnSync(process.execPath, ["review/capture.mjs", "wrap"], { cwd: ROOT, encoding: "utf8", timeout: 120_000 });
    const out = `${run.stdout ?? ""}${run.stderr ?? ""}`;
    expect(run.error, `the wrap gate did not run: ${String(run.error)}`).toBeUndefined();
    expect(out, "the wrap gate printed no verdict line — it did not scan").toMatch(/^(PASS|FAIL) {2}wrap /m);
    expect(out.split("\n").filter((l) => /^\s*BAD\b/.test(l)), "unjustified token-break licences").toEqual([]);
    expect(out).toMatch(/^PASS {2}wrap /m);
    expect(run.status, out).toBe(0);
  });
});
