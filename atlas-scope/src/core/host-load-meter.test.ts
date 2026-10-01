// @vitest-environment node
/**
 * host-load-meter.test.ts — acceptance E2/E3 (wave 5): the load meter books ALL of the harness's own
 * CPU to the harness, including the part spent by processes that have already exited.
 *
 * THE DEFECT. `review/host-env.mjs :: createLoadMeter` read the harness as a process TREE, from a
 * `Win32_Process` query, at `start()`, at every `sample()` and at `finish()`. A process that is not
 * alive at a read is not in the tree, so every CPU millisecond a child spent after the last read before
 * it exited was lost — and a lost harness millisecond is not dropped, it is moved: `excess = gross -
 * harness`, so it was booked as OTHER load on the machine, the figure the 25 % quiet-host gate reads.
 * The meter's own contract said "sample() BEFORE each browser.close()", and `measure-inp.mjs` sampled
 * once, before its last close, while closing a scout browser, the 21 fresh first-selection browsers and
 * a context per journey unsampled. An independent sidecar measured Playwright Chromium at 7.2-9.3 % of
 * the host over runs whose report said "harness 0-1 %".
 *
 * A rule every caller must remember is the shape that failed. The meter now reads the harness from a
 * Windows JOB OBJECT that the harness process is placed in at `start()`: every process it spawns from
 * then on (browsers, their GPU and renderer children, grandchildren) is in that job, and the job's
 * accounting keeps the CPU time of processes that have EXITED. No call site can lose a child any more.
 * Where a job cannot be created the meter falls back to the tree, and then every close goes through
 * the meter, which samples first — the second guard below holds that for every harness in review/.
 */
import { spawnSync } from "node:child_process";
import { readdirSync, readFileSync } from "node:fs";
import { cpus } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { describe, expect, it } from "vitest";

const PKG = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
const REVIEW = join(PKG, "review");

interface LoadFigures {
  gross: number | null;
  harness: number | null;
  excess: number | null;
  cores: number;
  harnessMeasured: boolean;
  method?: string | null;
  jobError?: string | null;
}
interface Meter {
  start(): void;
  sample(): void;
  finish(): LoadFigures;
}
const loadEnv = async (): Promise<{ createLoadMeter: () => Meter }> =>
  (await import(/* @vite-ignore */ pathToFileURL(join(REVIEW, "host-env.mjs")).href)) as { createLoadMeter: () => Meter };

/** Burn `ms` of CPU on one core in a child process that then EXITS. The meter is never sampled. */
const burnInAChildThatExits = (ms: number): number => {
  const t0 = Date.now();
  const r = spawnSync(process.execPath, ["-e", `const t=Date.now();let x=0;while(Date.now()-t<${ms}){x++}`], { timeout: 60_000 });
  expect(r.status, "the burning child ran to completion").toBe(0);
  return Date.now() - t0;
};

describe("the load meter books an exited child's CPU to the harness, not to the rest of the machine", () => {
  it.runIf(process.platform === "win32")(
    "a child that burns ~2.5 s of CPU and exits between start() and finish() is harness time",
    async () => {
      const { createLoadMeter } = await loadEnv();
      const meter = createLoadMeter();
      const t0 = Date.now();
      meter.start();
      const burnMs = 2500;
      burnInAChildThatExits(burnMs);
      const load = meter.finish();
      const wallMs = Date.now() - t0;
      expect(load.harnessMeasured, "the harness could be read on this host").toBe(true);
      /* The whole window's core-time is at most wall x cores (the meter's own window is inside it), so
         a child that burned `burnMs` on one core is at least burnMs / (wall x cores) of it. 0.8 allows
         for a child that was descheduled on a contended host; the old accounting booked ~0 here. */
      const floor = (0.8 * burnMs) / (wallMs * cpus().length);
      expect(load.harness ?? 0, `harness share ${load.harness} over a ${wallMs} ms window on ${cpus().length} cores; the child alone is >= ${floor.toFixed(4)}`).toBeGreaterThanOrEqual(floor);
    },
    120_000,
  );

  it.runIf(process.platform === "win32")("on Windows the harness is read from a job object, which keeps an exited process's CPU", async () => {
    const { createLoadMeter } = await loadEnv();
    const meter = createLoadMeter();
    meter.start();
    /* The OS counters tick in ~15 ms steps; an empty window has no figures at all. */
    await new Promise((r) => setTimeout(r, 500));
    const load = meter.finish();
    expect(load.method, `a process-tree read loses every child that exits between reads (jobError: ${load.jobError})`).toBe("job");
  }, 120_000);
});

/* ── the fallback's rule, held for the CLASS of harness, read from the directory ───────────────── */

/**
 * The source with comments and the TEXT of every string blanked (newlines kept, so line numbers hold),
 * and the code inside `${…}` template substitutions kept — page-side code handed to the browser as a
 * string is not Node code, while a substitution is. A small lexer, because a regular expression cannot
 * follow a template literal whose substitution holds another template literal. (A regular-expression
 * literal is read as code; none in review/ contains `.close(`.)
 */
const code = (t: string): string => {
  const out = t.split("");
  const blank = (a: number, b: number): void => {
    for (let k = a; k < b; k++) if (out[k] !== "\n") out[k] = " ";
  };
  /* A stack of what the lexer is inside: "code" (with the brace depth it must return to) or "tpl". */
  const stack: { kind: "code" | "tpl"; depth: number }[] = [{ kind: "code", depth: 0 }];
  let depth = 0;
  let i = 0;
  while (i < t.length) {
    const top = stack[stack.length - 1]!;
    const c = t[i]!;
    if (top.kind === "tpl") {
      if (c === "\\") { blank(i, i + 2); i += 2; continue; }
      if (c === "`") { stack.pop(); i += 1; continue; }
      if (c === "$" && t[i + 1] === "{") { stack.push({ kind: "code", depth }); depth += 1; i += 2; continue; }
      blank(i, i + 1); i += 1; continue;
    }
    if (c === "/" && t[i + 1] === "*") { const e = t.indexOf("*/", i + 2); const end = e < 0 ? t.length : e + 2; blank(i, end); i = end; continue; }
    if (c === "/" && t[i + 1] === "/") { const e = t.indexOf("\n", i); const end = e < 0 ? t.length : e; blank(i, end); i = end; continue; }
    if (c === '"' || c === "'") {
      let j = i + 1;
      while (j < t.length && t[j] !== c && t[j] !== "\n") j += t[j] === "\\" ? 2 : 1;
      blank(i + 1, j); i = j + 1; continue;
    }
    if (c === "`") { stack.push({ kind: "tpl", depth }); i += 1; continue; }
    if (c === "{") depth += 1;
    if (c === "}") {
      depth -= 1;
      if (stack.length > 1 && top.kind === "code" && depth === top.depth) { stack.pop(); i += 1; continue; }
    }
    i += 1;
  }
  return out.join("");
};

/** Every `.close(` call in `src`, with the expression it is called on (empty when that is not an identifier path). */
const closeCalls = (src: string): { receiver: string; line: number }[] => {
  const out: { receiver: string; line: number }[] = [];
  const re = /([A-Za-z_$][\w$]*(?:\s*\??\.\s*[A-Za-z_$][\w$]*)*)?\s*\??\.\s*close\s*\(/g;
  for (const m of src.matchAll(re)) out.push({ receiver: (m[1] ?? "").replace(/\s+/g, ""), line: src.slice(0, m.index).split("\n").length });
  return out;
};

const reviewFiles = readdirSync(REVIEW).filter((n) => n.endsWith(".mjs"));
const meterUsers = reviewFiles.filter((n) => n !== "host-env.mjs" && /\bcreateLoadMeter\s*\(/.test(code(readFileSync(join(REVIEW, n), "utf8"))));

describe("every close in a metered harness goes through the meter (the tree fallback samples before a child exits)", () => {
  it("finds the metered harnesses — an empty scan is not a pass", () => {
    for (const known of ["measure-inp.mjs", "measure-fps.mjs", "audit-e5-sweep.mjs", "audit-e5-coldload.mjs"]) expect(meterUsers).toContain(known);
  });

  it("no metered harness closes a browser, context or page except through its meter or closeMeasured", () => {
    const bare: string[] = [];
    for (const n of meterUsers) {
      const src = code(readFileSync(join(REVIEW, n), "utf8"));
      /* The meters this file created: `const <name> = createLoadMeter()`. */
      const meters = [...src.matchAll(/\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*createLoadMeter\s*\(/g)].map((m) => m[1]);
      for (const c of closeCalls(src)) if (!meters.includes(c.receiver)) bare.push(`${n}:${c.line} ${c.receiver || "(expression)"}.close(`);
    }
    expect(bare, "a close that bypasses the meter takes the child's CPU with it when the job is unavailable").toEqual([]);
  });

  it("host-env.mjs has exactly one bare close, inside closeMeasured, which samples first", () => {
    const src = code(readFileSync(join(REVIEW, "host-env.mjs"), "utf8"));
    const calls = closeCalls(src);
    expect(calls.map((c) => c.receiver)).toEqual(["target"]);
    const fn = /export\s+async\s+function\s+closeMeasured\s*\(\s*meter\s*,\s*target\s*\)\s*\{([\s\S]*?)\n\}/.exec(src);
    expect(fn, "closeMeasured(meter, target) is exported by host-env.mjs").not.toBeNull();
    const body = fn![1]!;
    expect(body.indexOf("sample()"), "it samples").toBeGreaterThanOrEqual(0);
    expect(body.indexOf("sample()"), "before it closes").toBeLessThan(body.indexOf("target.close("));
  });
});
