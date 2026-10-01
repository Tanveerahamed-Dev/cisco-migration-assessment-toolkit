/**
 * journey-scope.test.ts — the declared journeys, the E5 sweep and docs/acceptance.md cannot
 * contradict each other about what is inside a journey.
 *
 * THE DEFECT (acceptance report, E1 overturned PASS -> UNPROVEN, 2026-09-23). `audit-e5-sweep.mjs`
 * says it "drives the interactions the journeys do NOT cover", and it timed "path trace: swap +
 * submit" with the same URL and the same `.pt-form__swap` selector as measure-inp's J4 act, and
 * "select a finding (first selection after page load)" with J1's selectors. acceptance.md then listed
 * swap+submit, the palette open and the first finding selection as "outside the five declared
 * journeys", and in the same paragraph said the first selection was "now inside J1 itself". The only
 * guard (Fabric3D.test.tsx) checked that five journey ids existed.
 *
 * THE RULE (decided 2026-09-23 on the owner's delegated authority): a declared journey is exactly
 * what `review/measure-inp.mjs` times. Every input a journey's measured act performs belongs to that
 * journey. So:
 *   1. no E5 sweep action may time an input a journey act performs — derived here by EXECUTING both
 *      harnesses' acts against a recording page and comparing the inputs they perform, not from a
 *      list of names;
 *   2. acceptance.md's "inside" list is exactly measure-inp's journey ids, and its "outside" list is
 *      exactly the sweep's action names — so the enumeration is the harnesses', and by (1) it names
 *      no journey's act.
 *
 * WHAT AN "INPUT" IS HERE. A pointer input aimed through a selector (the locator chain, `>>`-joined,
 * each comma alternative kept), a keystroke (printable characters are one class, "printable"; any
 * other key or chord by name) with the element it is aimed at — the locator it was pressed on, or the
 * element the recorder last saw focused by a click or locator input — and a `fill`. Two inputs are
 * the same act when they are the same kind (and key) and their targets share a selector alternative;
 * a chord with Control/Meta/Alt is an application shortcut and matches on the chord alone, wherever
 * focus is; an unaimed keystroke matches only an unaimed one. A coordinate click (page.mouse) is one
 * class, "a point on the page": two of them always match. LIMITS, stated: the recorder compares the
 * selector strings the harnesses aim through, so two different selectors for the same element would
 * not be recognised as one — the harnesses share selectors today, and the decided rule makes the
 * comparison stricter, never looser.
 */
import { readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import ts from "typescript";
import { describe, expect, it } from "vitest";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
const INP = join(ROOT, "review", "measure-inp.mjs");
const SWEEP = join(ROOT, "review", "audit-e5-sweep.mjs");
const ACCEPTANCE = join(ROOT, "docs", "acceptance.md");

/* ── the recording page ─────────────────────────────────────────────────────────────────────── */

interface Input {
  kind: "pointer" | "key" | "fill" | "wheel";
  key?: string;
  /** Selector alternatives the input was aimed at; null = not aimed at any selector. */
  target: string[] | null;
}

/** Split a selector list on its top-level commas (not those inside brackets, parens or quotes). */
function alternatives(sel: string): string[] {
  const out: string[] = [];
  let depth = 0;
  let quote: string | null = null;
  let cur = "";
  for (const ch of sel) {
    if (quote !== null) {
      if (ch === quote) quote = null;
    } else if (ch === '"' || ch === "'") quote = ch;
    else if (ch === "[" || ch === "(") depth += 1;
    else if (ch === "]" || ch === ")") depth -= 1;
    else if (ch === "," && depth === 0) {
      out.push(cur);
      cur = "";
      continue;
    }
    cur += ch;
  }
  out.push(cur);
  return out.map((s) => s.trim().replace(/\s+/g, " ")).filter(Boolean);
}

const chain = (parent: string[] | null, sel: string): string[] => {
  const alts = alternatives(sel);
  return parent === null ? alts : parent.flatMap((p) => alts.map((a) => `${p} >> ${a}`));
};

const PRINTABLE_NAMES = /^(Key[A-Z]|Digit\d|Numpad\d|Space|Semicolon|Quote|Comma|Period|Slash|Minus|Equal|BracketLeft|BracketRight|Backslash|Backquote)$/;
/** A key or chord, by class: every printable character is "printable" (Shift+<printable> too). */
function keyClass(spec: string): string {
  const parts = spec.split("+");
  const key = parts[parts.length - 1] ?? spec;
  const mods = parts.slice(0, -1).filter((m) => m !== "Shift");
  const printable = key.length === 1 || PRINTABLE_NAMES.test(key);
  if (mods.length === 0 && printable) return "printable";
  return [...mods.map((m) => (m === "Meta" || m === "ControlOrMeta" ? "Control" : m)).sort(), key.length === 1 ? key.toLowerCase() : key].join("+");
}
const isShortcut = (k: string): boolean => /^(Alt|Control)\+/.test(k);

interface Recorder {
  inputs: Input[];
  focus: string[] | null;
}

/** A page that performs nothing and records every input it is asked to perform. */
function recordingPage(rec: Recorder): unknown {
  const key = (spec: string, target: string[] | null): void => {
    const k = keyClass(spec);
    rec.inputs.push({ kind: "key", key: k, target });
    /* A shortcut may move focus anywhere (Ctrl+K moves it into the palette); the recorder no
       longer knows where it is. */
    if (isShortcut(k)) rec.focus = null;
  };
  const text = (s: string, target: string[] | null): void => {
    for (const ch of s) key(ch, target);
  };
  const locator = (sel: string[]): unknown =>
    new Proxy(
      {},
      {
        get: (_t, prop) => {
          const name = String(prop);
          if (name === "then") return undefined;
          if (name === "first" || name === "last" || name === "nth" || name === "filter") return () => locator(sel);
          if (name === "locator") return (sub: string) => locator(chain(sel, sub));
          if (["click", "dblclick", "tap", "check", "uncheck", "setChecked", "dispatchEvent", "selectOption"].includes(name))
            return async () => {
              rec.inputs.push({ kind: "pointer", target: sel });
              rec.focus = sel;
            };
          if (name === "press")
            return async (k: string) => {
              key(k, sel);
              if (!isShortcut(keyClass(k))) rec.focus = sel;
            };
          if (name === "type" || name === "pressSequentially")
            return async (s: string) => {
              text(s, sel);
              rec.focus = sel;
            };
          if (name === "fill")
            return async () => {
              rec.inputs.push({ kind: "fill", target: sel });
              rec.focus = sel;
            };
          if (name === "focus") return async () => void (rec.focus = sel);
          if (name === "count") return async () => 5;
          if (name === "inputValue" || name === "textContent") return async () => "";
          if (name === "boundingBox") return async () => ({ x: 0, y: 0, width: 400, height: 300 });
          if (name === "isVisible") return async () => false;
          return async () => null;
        },
      },
    );
  const point = (): void => void rec.inputs.push({ kind: "pointer", target: ["(a point on the page)"] });
  return {
    locator: (sel: string) => locator(chain(null, sel)),
    click: async (sel: string) => {
      rec.inputs.push({ kind: "pointer", target: chain(null, sel) });
      rec.focus = chain(null, sel);
    },
    fill: async (sel: string) => {
      rec.inputs.push({ kind: "fill", target: chain(null, sel) });
      rec.focus = chain(null, sel);
    },
    press: async (sel: string, k: string) => key(k, chain(null, sel)),
    type: async (sel: string, s: string) => text(s, chain(null, sel)),
    mouse: {
      click: async () => point(),
      dblclick: async () => point(),
      down: async () => point(),
      up: async () => undefined,
      move: async () => undefined /* a hover is not an interaction */,
      wheel: async () => void rec.inputs.push({ kind: "wheel", target: null }),
    },
    keyboard: {
      press: async (k: string) => key(k, rec.focus),
      down: async (k: string) => key(k, rec.focus),
      up: async () => undefined,
      type: async (s: string) => text(s, rec.focus),
      insertText: async (s: string) => text(s, rec.focus),
    },
    evaluate: async () => null,
    goto: async () => null,
    bringToFront: async () => undefined,
    setViewportSize: async () => undefined,
    waitForTimeout: async () => undefined,
    waitForFunction: async () => ({}),
    waitForSelector: async () => null,
  };
}

const sameTarget = (a: string[] | null, b: string[] | null): boolean =>
  a === null || b === null ? a === b : a.some((x) => b.includes(x));

/** Two inputs are the same act — see the header for the rule. */
function sameInput(a: Input, b: Input): boolean {
  if (a.kind !== b.kind) return false;
  if (a.kind === "wheel") return true;
  if (a.kind === "key") {
    if (a.key !== b.key) return false;
    if (isShortcut(a.key ?? "")) return true;
    return sameTarget(a.target, b.target);
  }
  return sameTarget(a.target, b.target);
}
const show = (i: Input): string => `${i.kind}${i.key ? ` ${i.key}` : ""} @ ${i.target === null ? "(unaimed)" : i.target.join(" | ")}`;

/* ── the harnesses, loaded ──────────────────────────────────────────────────────────────────── */

type Hook = (page: unknown, i?: unknown) => Promise<unknown>;
interface InpModule {
  JOURNEYS: { id: string; prime?: Hook; act: Hook }[];
  FIRST_SELECTION: { id: string; beforeClick: Hook; act: (page: unknown, anchor: { x: number; y: number }) => Promise<unknown> };
  J2_HITS: { id: string; x: number; y: number }[];
  actStepOf?: (taskStart: number, escapeAt: number | undefined) => string;
  prewarmWindows?: (timeline: { state: string; t: number }[]) => { from: number; to: number | null; endedAs: string | null }[];
  overlapsPrewarm?: (windows: { from: number; to: number | null }[], start: number, duration: number, tailMs?: number) => boolean;
  PREWARM_TAIL_MS?: number;
  DECLARED_SAMPLE?: Record<string, unknown>;
  SAMPLE_ENV?: Record<string, string>;
  NON_SAMPLE_ENV?: Record<string, string>;
  sampleOf?: (env: Record<string, string | undefined>) => Record<string, unknown>;
  sampleDeviations?: (sample: Record<string, unknown>) => string[];
  sampleLabel?: (verdict: string, deviations: readonly string[]) => string;
  acceptanceEvidenceOf?: (x: AcceptanceInputs) => boolean;
  acceptanceWhyOf?: (x: AcceptanceInputs) => string;
  windowStatusOf?: (plan: unknown, check: unknown) => string;
  windowFitsOf?: (plan: unknown, check: unknown) => boolean;
  isQuietRunRecord?: (h: Record<string, unknown>, maxHostBusy: number) => boolean;
  e3StableVerdict?: (runs: { journeys?: Record<string, { e3?: string }> }[], id: string, minRuns: number, deviations?: readonly string[]) => { stable: string };
  e3AcrossRunsVerdictOf?: (perJourney: Record<string, { stable: string }>, deviations: readonly string[]) => string;
  e3RunVerdictOf?: (results: { e3Verdict: string }[], deviations: readonly string[]) => string;
  runExitCodeOf?: (results: { verdict: string; e3Verdict: string }[]) => number;
  journeySelectionOf?: (only: readonly string[] | null) => string[];
  FIRST_PALETTE?: { id: string };
}
interface AcceptanceInputs {
  lane: string;
  devServer: boolean;
  softwareRasteriser: boolean;
  rendererKnown: boolean;
  fresh: boolean;
  freshWhy?: string;
  windows: { leg: string; plan: unknown; check: unknown }[];
  headed: boolean;
  hostBusy: number | null;
  maxHostBusy: number;
  powerKnown: boolean;
  powerThrottled: boolean;
  belowFullRate: boolean;
  sampleDeviations: readonly string[];
}

/** A measured trial measure-inp defines OUTSIDE `JOURNEYS` — a first-after-load case run in fresh browsers. */
interface Trial {
  id: string;
  act: (page: unknown, anchor?: unknown) => Promise<unknown>;
  [hook: string]: unknown;
}

/**
 * Every measured trial the harness EXPORTS beside `JOURNEYS`: any exported object with a string `id`
 * and an `act` function (FIRST_SELECTION, FIRST_PALETTE, and whatever is added next). DISCOVERED, not
 * listed: when `J2-first-select-device-3d` was the only one, this file named it, and the next
 * first-after-load case (`J5-first-open-palette`, 2026-09-26) would have been measured and declared
 * nowhere. A trial's untimed hooks are its functions named `before…`.
 */
const exportedTrials = (inp: InpModule): Trial[] =>
  Object.values(inp as unknown as Record<string, unknown>).filter(
    (v): v is Trial => v !== null && typeof v === "object" && !Array.isArray(v) && typeof (v as Trial).id === "string" && typeof (v as Trial).act === "function",
  );
const measuredIds = (inp: InpModule): string[] => [...inp.JOURNEYS.map((j) => j.id), ...exportedTrials(inp).map((t) => t.id)];
interface SweepModule {
  ACTIONS: { name: string; setup?: Hook; fn: (page: unknown, env: { app: string }) => Promise<unknown> }[];
}

const loadInp = async (): Promise<InpModule> => (await import(/* @vite-ignore */ pathToFileURL(INP).href)) as InpModule;

/**
 * The sweep is imported only when it is a module: until 2026-09-23 it ran its measurement at the
 * top level, and importing it would have launched a headed browser from inside the unit suite.
 */
const loadSweep = async (): Promise<SweepModule> => {
  const src = readFileSync(SWEEP, "utf8");
  expect(src, "audit-e5-sweep.mjs must run its measurement only when executed (an `if (IS_MAIN) await main()` guard), so its actions can be read without launching a browser").toMatch(
    /\bif\s*\(\s*IS_MAIN\s*\)\s*await\s+main\s*\(\s*\)/,
  );
  expect(src, "audit-e5-sweep.mjs must export its actions").toMatch(/\bexport\s+const\s+ACTIONS\b/);
  return (await import(/* @vite-ignore */ pathToFileURL(SWEEP).href)) as SweepModule;
};

/** Every journey's measured act, as the inputs it performs (setup and priming excluded). */
async function journeyActs(): Promise<{ id: string; inputs: Input[] }[]> {
  const inp = await loadInp();
  /* Stand in for the run's anchor discovery, so J2's act has somewhere to click. */
  if (inp.J2_HITS.length === 0) for (const id of ["core2", "core1", "dist1"]) inp.J2_HITS.push({ id, x: 10, y: 10 });
  const out: { id: string; inputs: Input[] }[] = [];
  for (const j of inp.JOURNEYS) {
    const rec: Recorder = { inputs: [], focus: null };
    const page = recordingPage(rec);
    if (typeof j.prime === "function") await j.prime(page).catch(() => null);
    const measured: Input[] = [];
    rec.inputs = measured;
    await j.act(page, 0).catch(() => null);
    rec.inputs = [];
    out.push({ id: j.id, inputs: measured });
  }
  for (const t of exportedTrials(inp)) {
    const rec: Recorder = { inputs: [], focus: null };
    const page = recordingPage(rec);
    for (const [name, hook] of Object.entries(t)) if (/^before/.test(name) && typeof hook === "function") await (hook as Hook)(page).catch(() => null);
    const measured: Input[] = [];
    rec.inputs = measured;
    await t.act(page, { x: 10, y: 10 }).catch(() => null);
    rec.inputs = [];
    out.push({ id: t.id, inputs: measured });
  }
  return out;
}

/** The inputs a trial's untimed `before…` hooks perform (they must perform none). */
async function trialSetupInputs(t: Trial): Promise<Input[]> {
  const rec: Recorder = { inputs: [], focus: null };
  const page = recordingPage(rec);
  for (const [name, hook] of Object.entries(t)) if (/^before/.test(name) && typeof hook === "function") await (hook as Hook)(page).catch(() => null);
  return rec.inputs;
}

/** Every sweep action's MEASURED inputs, run in the sweep's own order on one page (focus carries). */
async function sweepActs(): Promise<{ name: string; inputs: Input[] }[]> {
  const { ACTIONS } = await loadSweep();
  const rec: Recorder = { inputs: [], focus: null };
  const page = recordingPage(rec);
  const env = { app: "http://localhost:0" };
  const out: { name: string; inputs: Input[] }[] = [];
  for (const a of ACTIONS) {
    /* Setup is untimed: its inputs are discarded, but the focus it leaves carries into the act. */
    if (typeof a.setup === "function") await a.setup(page, env).catch(() => null);
    const measured: Input[] = [];
    rec.inputs = measured;
    await a.fn(page, env).catch(() => null);
    rec.inputs = [];
    out.push({ name: a.name, inputs: measured });
  }
  return out;
}

/* ── 1. the harnesses ───────────────────────────────────────────────────────────────────────── */

describe("the harness's first-after-load trials are discovered, and each times exactly one journey's act", () => {
  it("discovers FIRST_SELECTION and FIRST_PALETTE among the exports (a discovery that finds nothing pins nothing)", async () => {
    const ids = exportedTrials(await loadInp()).map((t) => t.id);
    expect(ids).toEqual(expect.arrayContaining(["J2-first-select-device-3d", "J5-first-open-palette"]));
  });

  it("J5-first-open-palette performs no input before its press, and its press is J5's act exactly", async () => {
    const inp = await loadInp();
    const t = exportedTrials(inp).find((x) => x.id === "J5-first-open-palette");
    expect(t, "measure-inp measures the first palette open after load in a fresh browser").toBeDefined();
    expect(await trialSetupInputs(t!), "its untimed setup would spend the first open before the measurement").toEqual([]);
    const acts = await journeyActs();
    const cold = acts.find((a) => a.id === "J5-first-open-palette")!;
    const warm = acts.find((a) => a.id === "J5-open-palette")!;
    expect(cold.inputs.length, "its act performs an input").toBeGreaterThan(0);
    expect(cold.inputs.map(show), "the cold trial times the same act as the warm journey, so the two figures compare").toEqual(warm.inputs.map(show));
  });

  it("every discovered trial's untimed setup performs no input", async () => {
    const offenders: string[] = [];
    for (const t of exportedTrials(await loadInp())) {
      const spent = await trialSetupInputs(t);
      if (spent.length > 0) offenders.push(`${t.id}: ${spent.map(show).join(", ")}`);
    }
    expect(offenders).toEqual([]);
  });

  it("the cold palette trial measures more than one viewport and both colour schemes by default", async () => {
    const t = exportedTrials(await loadInp()).find((x) => x.id === "J5-first-open-palette") as unknown as {
      legs: { width: number; height: number; colorScheme: string }[];
      trials: number;
    };
    if (process.env.ATLAS_FIRST_PALETTE_LEGS === undefined) {
      expect(t.legs.map((l) => `${l.width}x${l.height}:${l.colorScheme}`).sort()).toEqual(["1280x800:dark", "1280x800:light", "1920x1080:dark", "1920x1080:light"]);
    } else expect(t.legs.length, "ATLAS_FIRST_PALETTE_LEGS parsed to no leg").toBeGreaterThan(0);
    if (process.env.ATLAS_FIRST_PALETTE_TRIALS === undefined) expect(t.trials, "E2 says over at least 20 repetitions").toBeGreaterThanOrEqual(20);
    else expect(t.trials).toBeGreaterThan(0);
  });
});

describe("the cold palette trial tells the open from the close, and every measured page sees the pre-warm", () => {
  it("a long task is the open's or the close's by TIME against the Escape keydown, not by the first entry it overlaps", async () => {
    const { actStepOf } = await loadInp();
    expect(typeof actStepOf, "measure-inp exports its attribution rule, so it can be pinned").toBe("function");
    /* The shapes the old rule misfiled (verifier V4, 2026-09-26): a task overlapping only the Escape's
       keyup was called the open, and with the Ctrl+K keydown below the Event Timing threshold (no
       entry) the Escape keydown was the ONLY keydown and its task was called the open too. Time
       against the Escape keydown's own timestamp answers both. */
    const escapeAt = 1060;
    expect(actStepOf!(1000, escapeAt), "starts at the Ctrl+K").toMatch(/^open/);
    expect(actStepOf!(1059.9, escapeAt), "starts just before the Escape").toMatch(/^open/);
    expect(actStepOf!(1061, escapeAt), "starts after the Escape (the keyup-overlap case, the lone-keydown case)").toMatch(/^after Escape/);
    expect(actStepOf!(1000, undefined), "no Escape recorded is said, not guessed").toMatch(/^unattributed/);
  });

  it("the pre-warm's drawn window, and which interactions overlapped it (with the GPU tail behind it)", async () => {
    const { prewarmWindows, overlapsPrewarm, PREWARM_TAIL_MS } = await loadInp();
    expect(typeof prewarmWindows).toBe("function");
    expect(typeof overlapsPrewarm).toBe("function");
    expect(PREWARM_TAIL_MS, "a tail for the GPU compile that follows the draw").toBeGreaterThanOrEqual(120);
    const tl = [
      { state: "waiting", t: 100 },
      { state: "scheduled", t: 4000 },
      { state: "mounted", t: 5000 },
      { state: "done", t: 5050 },
    ];
    const w = prewarmWindows!(tl);
    expect(w).toEqual([{ from: 5000, to: 5050, endedAs: "done" }]);
    expect(overlapsPrewarm!(w, 4990, 20), "an interaction spanning the mount").toBe(true);
    expect(overlapsPrewarm!(w, 5100, 40), "one inside the GPU tail").toBe(true);
    expect(overlapsPrewarm!(w, 5050 + PREWARM_TAIL_MS! + 1, 40), "one after the tail").toBe(false);
    expect(overlapsPrewarm!(w, 4000, 100), "one before the draw").toBe(false);
    expect(prewarmWindows!(tl.slice(0, 3)), "still drawn when the record ended: open-ended, not dropped").toEqual([{ from: 5000, to: null, endedAs: null }]);
    expect(overlapsPrewarm!(prewarmWindows!(tl.slice(0, 3)), 90_000, 10)).toBe(true);
    expect(prewarmWindows!([{ state: "waiting", t: 1 }]), "never drawn: no window").toEqual([]);
  });

  it("every page measure-inp instruments also records the pre-warm timeline (the class: every INSTRUMENT install)", () => {
    const src = readFileSync(INP, "utf8");
    const instrumented = src.match(/addInitScript\(INSTRUMENT\)/g) ?? [];
    const recorded = src.match(/addInitScript\(PREWARM_TIMELINE\)/g) ?? [];
    expect(instrumented.length, "precondition: the harness instruments pages (a count of 0 would pin nothing)").toBeGreaterThanOrEqual(3);
    expect(recorded.length, "a measured page that does not record the pre-warm cannot say whether its timed interaction absorbed it").toBe(instrumented.length);
  });
});

describe("the E5 sweep times no input a declared journey's act performs", () => {
  it("every journey's measured act performs an input (a comparison against nothing pins nothing)", async () => {
    const acts = await journeyActs();
    expect(acts.length).toBeGreaterThanOrEqual(5);
    for (const j of acts) expect(j.inputs.length, `${j.id}: its act performed no input the recorder saw`).toBeGreaterThan(0);
  });

  it("the sweep has actions that perform inputs, so the comparison below is not over an empty set", async () => {
    const acts = await sweepActs();
    expect(acts.filter((a) => a.inputs.length > 0).length).toBeGreaterThanOrEqual(3);
  });

  it("the comparison recognises every journey's own act (its red branch, executed)", async () => {
    for (const j of await journeyActs()) {
      const self = j.inputs.filter((x) => j.inputs.some((y) => sameInput(x, y)));
      expect(self.length, j.id).toBe(j.inputs.length);
    }
  });

  it("no sweep action shares an input with any journey's act", async () => {
    const journeys = await journeyActs();
    const shared: string[] = [];
    for (const a of await sweepActs()) {
      for (const j of journeys) {
        const both = a.inputs.filter((x) => j.inputs.some((y) => sameInput(x, y)));
        if (both.length > 0) shared.push(`"${a.name}" times ${[...new Set(both.map(show))].join(", ")} — ${j.id}'s act`);
      }
    }
    expect(shared, "a sweep action re-times a journey's act; it belongs to the journey (move the input into the action's untimed setup, or drop the action)").toEqual([]);
  });
});

/* ── 2. the declaration ─────────────────────────────────────────────────────────────────────── */

/** The "E3's scope" section of acceptance.md. */
function scopeSection(): string {
  const md = readFileSync(ACCEPTANCE, "utf8");
  const start = md.indexOf("### E3's scope");
  expect(start, 'acceptance.md has an "E3\'s scope" section').toBeGreaterThanOrEqual(0);
  const rest = md.slice(start + 1);
  const end = rest.search(/\n#{2,3} /);
  return end < 0 ? rest : rest.slice(0, end);
}

/** The first backticked token of every bullet under the bold lead-in `**<lead>`. */
function listUnder(section: string, lead: string): { item: string; line: string }[] {
  const lines = section.split("\n");
  const at = lines.findIndex((l) => l.startsWith(`**${lead}`));
  expect(at, `acceptance.md "E3's scope" has a list introduced by **${lead}**`).toBeGreaterThanOrEqual(0);
  const out: { item: string; line: string }[] = [];
  for (const line of lines.slice(at + 1)) {
    if (!line.startsWith("- ")) break;
    const m = /`([^`]+)`/.exec(line);
    expect(m, `every bullet under **${lead}** names its subject in backticks: ${line}`).not.toBeNull();
    out.push({ item: m![1]!, line });
  }
  expect(out.length, `the list under **${lead}** is empty`).toBeGreaterThan(0);
  return out;
}

describe("acceptance.md's E3 scope is the harnesses' own lists", () => {
  it("'inside the declared journeys' is exactly measure-inp's journey ids", async () => {
    const inp = await loadInp();
    const ids = measuredIds(inp).sort();
    const inside = listUnder(scopeSection(), "Inside the declared journeys").map((x) => x.item).sort();
    expect(inside).toEqual(ids);
  });

  it("'outside the declared journeys' is exactly the E5 sweep's action names", async () => {
    const { ACTIONS } = await loadSweep();
    const outside = listUnder(scopeSection(), "Outside the declared journeys").map((x) => x.item).sort();
    expect(outside).toEqual(ACTIONS.map((a) => a.name).sort());
  });

  it("no 'outside' item names a journey", async () => {
    const inp = await loadInp();
    const ids = measuredIds(inp);
    const offenders = listUnder(scopeSection(), "Outside the declared journeys").filter((x) =>
      ids.some((id) => x.line.includes(id) || x.line.includes(id.split("-")[0]! + " ") || x.line.includes(`(${id.split("-")[0]!})`)),
    );
    expect(offenders.map((x) => x.line)).toEqual([]);
  });
});

/* ── 3. the sweep counts the application's frames, not a window that stopped presenting ──────
 *
 * Acceptance report, E harness item 12d (2026-09-23): the sweep's "~1,000 ms, 0 ms-blocking rows
 * match the window-not-presenting signature", and it counted them against the 200 ms bar as the
 * application's frames. measure-inp.mjs already refuses a journey whose window was not presenting;
 * the sweep had no such separation. Pinned on the sweep's own exported classifier. */
describe("the E5 sweep separates window-not-presenting frames from the application's", () => {
  interface Frame {
    startTime: number;
    duration: number;
    blockingDuration: number;
    scriptMs: number;
  }
  interface Judged {
    mainOverBar: Frame[];
    stallsOverBar: Frame[];
    notPresenting: string | null;
  }
  const load = async () => (await loadSweep()) as unknown as { judgeFrames(loaf: Frame[], bar?: number): Judged; BAR_MS: number };
  const f = (duration: number, blockingDuration: number, scriptMs: number): Frame => ({ startTime: 0, duration, blockingDuration, scriptMs });

  it("a ~1,000 ms frame with no blocking time and no script is not the application's, and it withholds the verdict", async () => {
    const { judgeFrames, BAR_MS } = await load();
    expect(BAR_MS).toBe(200);
    const j = judgeFrames([f(1003.5, 0, 0)]);
    expect(j.mainOverBar, "not counted against the bar as the app's").toEqual([]);
    expect(j.stallsOverBar).toHaveLength(1);
    expect(j.notPresenting, "the repetition is NOT MEASURED, with the frame named").toMatch(/window-not-presenting signature: a 1003\.5 ms frame with 0 ms blocking/);
  });

  it("a frame that blocked the main thread is the application's, whatever its length", async () => {
    const { judgeFrames } = await load();
    const j = judgeFrames([f(250, 120, 180), f(1003.5, 900, 950)]);
    expect(j.mainOverBar).toHaveLength(2);
    expect(j.notPresenting).toBeNull();
  });

  it("a long frame with no single blocking task but mostly script is still the application's", async () => {
    const { judgeFrames } = await load();
    const j = judgeFrames([f(300, 0, 240)]);
    expect(j.mainOverBar).toHaveLength(1);
    expect(j.notPresenting).toBeNull();
  });

  it("a not-presenting frame under the bar is counted apart and withholds nothing", async () => {
    const { judgeFrames } = await load();
    const j = judgeFrames([f(120, 0, 3)]);
    expect(j.mainOverBar).toEqual([]);
    expect(j.stallsOverBar).toEqual([]);
    expect(j.notPresenting).toBeNull();
  });
});

/* ── the design brief is the other statement of the E1 list ─────────────────────────────────── */

describe("design-brief §8.1/§8.2 say what measure-inp times, like acceptance.md's E3 scope", () => {
  /* The brief lists the five E1 journeys and budgets each in §8.2. When acceptance.md decided that a
     journey is exactly what measure-inp.mjs times, the brief still read "Run a path trace" (submit
     only) and "Open the command palette" (open only), so the two statements of E1 disagreed about
     whether the swap and the Escape are inside a journey. Whitespace is normalised: the brief is
     hard-wrapped prose. */
  const BRIEF = join(ROOT, "docs", "design-brief.md");
  const norm = (s: string) => s.replace(/\s+/g, " ");
  const section = (text: string, from: string, to: string): string => {
    const a = text.indexOf(from);
    const b = text.indexOf(to, a + from.length);
    expect(a, `section "${from}" not found`).toBeGreaterThanOrEqual(0);
    expect(b, `end "${to}" not found`).toBeGreaterThan(a);
    return norm(text.slice(a, b));
  };
  const brief = readFileSync(BRIEF, "utf8");
  const list = section(brief, "The five declared representative journeys", "### 8.2");
  const table = section(brief, "### 8.2", "### 8.3");
  const item = (n: number): string => {
    const m = new RegExp(`(?:^| )${n}\\. (.*?)(?= ${n + 1}\\. |$)`).exec(list);
    expect(m, `§8.1 journey ${n}`).not.toBeNull();
    return m![1]!;
  };
  const row = (n: number): string => {
    const m = new RegExp(`\\| \\*\\*${n}\\. [^|]*\\*\\* \\|([^|]*)\\|`).exec(table);
    expect(m, `§8.2 row ${n}`).not.toBeNull();
    return m![1]!;
  };

  it("journey 1 includes the first selection after load", () => {
    expect(item(1)).toMatch(/first (finding )?selection after (page )?load/i);
  });
  it("journey 4 is the swap, then the submit — both inputs, in §8.1 and in §8.2", () => {
    expect(item(4)).toMatch(/swap/i);
    expect(item(4)).toMatch(/submit/i);
    expect(row(4)).toMatch(/swap/i);
  });
  it("journey 5 is Ctrl+K open and Escape close — both inputs, in §8.1 and in §8.2", () => {
    expect(item(5)).toMatch(/Ctrl\+K/);
    expect(item(5)).toMatch(/Escape/);
    expect(row(5)).toMatch(/Escape|close/i);
  });
});

/* ── 4. an overridden sample is never the verdict (verifier round 2, D3/D4, 2026-09-27) ─────────
 *
 * D3. `ATLAS_FIRST_PALETTE_LEGS=1920x1080:dark,1920x1080:light ATLAS_FIRST_PALETTE_TRIALS=10` on a
 * quiet host exited 0 and printed "PASS E3-PASS J5-first-open-palette … over 20/20 trials" and
 * "ACCEPTANCE EVIDENCE" — no 1280 leg, half E2's ">= 20 repetitions", because the measured threshold
 * (`need = Math.min(MIN_REPS_WITH_SAMPLE, trials)`) fell with the override and the acceptance gate
 * never looked at the sample. The class is EVERY environment knob that shapes a sample, not the two
 * the verifier used: ATLAS_MIN_SAMPLED_REPS, ATLAS_FIRST_TARGETS and ATLAS_E3_MIN_RUNS lower a bar
 * the same way. A knob may still run (a subset is a useful lab probe); it may never print PASS or
 * ACCEPTANCE EVIDENCE. The knobs are DISCOVERED from the harness source and each must be classified.
 *
 * D4. A FIRST_PALETTE leg whose every trial threw before the window check keeps `{checked:false}`,
 * and the receipt said "a headed window is not inside the screen's work area" — it was never checked.
 */
describe("an overridden sample may run, but is never PASS or ACCEPTANCE EVIDENCE (D3)", () => {
  const E2_MIN = 20;
  const ENV_READ = /process\.env\.(ATLAS_[A-Z0-9_]+)/g;

  it("the harness exports its declared sample and the rule over it", async () => {
    const inp = await loadInp();
    for (const k of ["sampleOf", "sampleDeviations", "sampleLabel", "acceptanceEvidenceOf", "acceptanceWhyOf"] as const)
      expect(typeof inp[k], `measure-inp exports ${k}, so the rule can be pinned`).toBe("function");
    expect(inp.DECLARED_SAMPLE, "measure-inp declares its sample").toBeDefined();
  });

  it("every ATLAS_* knob the harness reads is classified: it shapes a sample, or it states why it does not", async () => {
    const inp = await loadInp();
    const src = readFileSync(INP, "utf8").replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/[^\n]*/g, "");
    const sampleKnobs = Object.values(inp.SAMPLE_ENV ?? {});
    const other = Object.keys(inp.NON_SAMPLE_ENV ?? {});
    expect(sampleKnobs.length, "precondition: the harness declares its sample knobs").toBeGreaterThanOrEqual(5);
    expect(Object.keys(inp.SAMPLE_ENV ?? {}).sort(), "every declared sample field has its knob, and every knob a declared field").toEqual(Object.keys(inp.DECLARED_SAMPLE ?? {}).sort());
    /* Every way the source can reach the environment: a direct `process.env.X` read may only be a
       knob that shapes no sample (a sample knob read directly would bypass the sample rule), and
       `process.env` as a whole may only be handed to the one reader the rule is built on. */
    const direct = [...new Set([...src.matchAll(ENV_READ)].map((m) => m[1]!))].sort();
    expect(direct.filter((k) => !other.includes(k)), "an ATLAS_* knob read directly that is not declared as shaping no sample").toEqual([]);
    const whole = [...src.matchAll(/process\.env(?!\.ATLAS_)/g)].map((m) => src.slice(Math.max(0, m.index! - 12), m.index! + 12));
    expect(whole.length, "precondition: the sample is read from the environment").toBeGreaterThan(0);
    expect(whole.filter((ctx) => !/(?:knob|sampleOf)\($/.test(ctx.slice(0, 12))), "process.env handed to something other than the sample reader").toEqual([]);
    const literals = [...new Set([...src.matchAll(/["'`](ATLAS_[A-Z0-9_]+)["'`=]/g)].map((m) => m[1]!))];
    expect(literals.filter((k) => !sampleKnobs.includes(k) && !other.includes(k)), "a knob named in the source that is in neither class").toEqual([]);
    expect(sampleKnobs.filter((k) => other.includes(k)), "a knob in both classes").toEqual([]);
    for (const [k, why] of Object.entries(inp.NON_SAMPLE_ENV ?? {})) expect(why.length, `${k} states why it shapes no sample`).toBeGreaterThan(20);
  });

  it("with no knob set the run IS the declared sample: 4 palette legs, >= 20 repetitions everywhere", async () => {
    const inp = await loadInp();
    const s = inp.sampleOf!({});
    expect(inp.sampleDeviations!(s)).toEqual([]);
    const legs = (s.paletteLegs as { width: number; height: number; colorScheme: string }[]).map((l) => `${l.width}x${l.height}:${l.colorScheme}`).sort();
    expect(legs).toEqual(["1280x800:dark", "1280x800:light", "1920x1080:dark", "1920x1080:light"]);
    expect(s.paletteTrials as number).toBeGreaterThanOrEqual(E2_MIN);
    expect(s.minSampledReps as number).toBeGreaterThanOrEqual(E2_MIN);
    expect(s.reps as number).toBeGreaterThanOrEqual(E2_MIN);
    expect((s.firstTargets as { trials: number }[]).reduce((a, t) => a + t.trials, 0)).toBeGreaterThanOrEqual(E2_MIN);
  });

  it("the verifier's run (1920 legs only, 10 trials) is a subset, and its PASS is not printed as PASS", async () => {
    const inp = await loadInp();
    const d = inp.sampleDeviations!(inp.sampleOf!({ ATLAS_FIRST_PALETTE_LEGS: "1920x1080:dark,1920x1080:light", ATLAS_FIRST_PALETTE_TRIALS: "10" }));
    expect(d.length, "both the dropped legs and the halved trials are named").toBe(2);
    expect(d.join(" ")).toMatch(/1280x800:dark/);
    expect(d.join(" ")).toMatch(/1280x800:light/);
    expect(d.join(" ")).toMatch(/ATLAS_FIRST_PALETTE_TRIALS=10/);
    for (const v of ["PASS", "FLOOR-PASS", "E3-PASS"]) expect(inp.sampleLabel!(v, d), `${v} over a subset`).not.toMatch(/^(FLOOR-)?PASS$|^E3-PASS$/);
    for (const v of ["PASS", "FAIL", "E3-PASS", "E3-FAIL", "NOT MEASURED", "TRANSPORT", "FLOOR-FAIL"]) expect(inp.sampleLabel!(v, []), "a declared sample keeps its verdict").toBe(v);
  });

  it("every knob that LOWERS a sample is a deviation; raising one is not", async () => {
    const inp = await loadInp();
    const dev = (env: Record<string, string>): string[] => inp.sampleDeviations!(inp.sampleOf!(env));
    const lowering: Record<string, string>[] = [
      { ATLAS_FIRST_PALETTE_LEGS: "1280x800:dark" },
      { ATLAS_FIRST_PALETTE_TRIALS: "19" },
      { ATLAS_MIN_SAMPLED_REPS: "3" },
      { ATLAS_REPS: "10" },
      { ATLAS_FIRST_TARGETS: "core2:3" },
      { ATLAS_E3_MIN_RUNS: "1" },
    ];
    for (const env of lowering) expect(dev(env).length, JSON.stringify(env)).toBeGreaterThan(0);
    /* The class, not the list above: every sample knob has a lowering value that is caught. */
    const covered = new Set(lowering.flatMap((e) => Object.keys(e)));
    expect(Object.values(inp.SAMPLE_ENV ?? {}).filter((k) => !covered.has(k)), "a sample knob with no lowering case here").toEqual([]);
    const raising: Record<string, string>[] = [
      { ATLAS_FIRST_PALETTE_TRIALS: "30" },
      { ATLAS_FIRST_PALETTE_LEGS: "1280x800:dark,1280x800:light,1920x1080:dark,1920x1080:light,390x844:dark" },
      { ATLAS_REPS: "40" },
      { ATLAS_E3_MIN_RUNS: "5" },
    ];
    for (const env of raising) expect(dev(env), JSON.stringify(env)).toEqual([]);
  });

  /* Verifier round 3 (V-R6-1, 2026-09-27): the rule measured most fields against E2's FLOOR of 20, not
     the DECLARED sample, so `ATLAS_FIRST_TARGETS=core2:18,core1:1,dist1:1` (core1 and dist1 cut from 3
     trials to 1) and `ATLAS_REPS=20` (declared 25) were each reported as the declared sample. The cases
     below are DERIVED from DECLARED_SAMPLE, one step below every declared number and every declared
     list item, so a field added to the declaration is covered without editing this test. */
  it("a sample below the DECLARED one — not merely below E2's floor — is a subset: every field, one step down", async () => {
    const inp = await loadInp();
    const dev = (env: Record<string, string>): string[] => inp.sampleDeviations!(inp.sampleOf!(env));
    expect(dev({ ATLAS_FIRST_TARGETS: "core2:18,core1:1,dist1:1" }), "the verifier's per-device lowering").not.toEqual([]);
    expect(dev({ ATLAS_REPS: "20" }), "the verifier's reps lowering (declared 25, E2 floor 20)").not.toEqual([]);
    const declared = inp.sampleOf!({});
    type Item = { id?: string; trials?: number; width?: number; height?: number; colorScheme?: string };
    const itemSpec = (field: string, i: Item): string => {
      if (typeof i.id === "string" && typeof i.trials === "number") return `${i.id}:${i.trials}`;
      if (typeof i.width === "number" && typeof i.height === "number" && typeof i.colorScheme === "string") return `${i.width}x${i.height}:${i.colorScheme}`;
      throw new Error(`${field}: a declared list item this test cannot write back as a knob value: ${JSON.stringify(i)}`);
    };
    const cases: { what: string; env: Record<string, string> }[] = [];
    for (const [field, value] of Object.entries(declared)) {
      const knobName = inp.SAMPLE_ENV![field];
      expect(knobName, `${field} has a knob`).toBeDefined();
      if (typeof value === "number") {
        expect(value, `${field}: a declared number that cannot be lowered`).toBeGreaterThan(1);
        cases.push({ what: `${field} ${value} -> ${value - 1}`, env: { [knobName!]: String(value - 1) } });
        continue;
      }
      expect(Array.isArray(value), `${field} is neither a number nor a list, so no lowering can be derived for it`).toBe(true);
      const items = value as Item[];
      items.forEach((it, k) => {
        if (items.length > 1)
          cases.push({ what: `${field} drops ${itemSpec(field, it)}`, env: { [knobName!]: items.filter((_, j) => j !== k).map((x) => itemSpec(field, x)).join(",") } });
        if (typeof it.trials === "number" && it.trials > 1)
          cases.push({
            what: `${field} ${itemSpec(field, it)} -> ${it.trials - 1}`,
            env: { [knobName!]: items.map((x, j) => itemSpec(field, j === k ? { ...x, trials: x.trials! - 1 } : x)).join(",") },
          });
      });
    }
    expect(new Set(cases.map((c) => Object.keys(c.env)[0])).size, "precondition: every declared field produced a lowering").toBe(Object.keys(declared).length);
    const missed = cases.filter((c) => dev(c.env).length === 0).map((c) => `${c.what}  ${JSON.stringify(c.env)}`);
    expect(missed, "a sample below the declared one reported as the declared sample").toEqual([]);
    /* ...and the declared sample written back through the knobs is still the declared sample. */
    const same = Object.fromEntries(
      Object.entries(declared).map(([f, v]) => [inp.SAMPLE_ENV![f]!, typeof v === "number" ? String(v) : (v as Item[]).map((x) => itemSpec(f, x)).join(",")]),
    );
    expect(dev(same)).toEqual([]);
  });

  it("the acceptance gate reads the sample: a subset is never ACCEPTANCE EVIDENCE, and says why", async () => {
    const inp = await loadInp();
    const plan = { fits: true };
    const quiet: AcceptanceInputs = {
      lane: "evidence",
      devServer: false,
      softwareRasteriser: false,
      rendererKnown: true,
      fresh: true,
      windows: [{ leg: "1920x1080 dark", plan, check: { checked: true, inside: true } }],
      headed: true,
      hostBusy: 0.1,
      maxHostBusy: 0.25,
      powerKnown: true,
      powerThrottled: false,
      belowFullRate: false,
      sampleDeviations: [],
    };
    expect(inp.acceptanceEvidenceOf!(quiet), "precondition: a quiet, declared, release run is evidence").toBe(true);
    expect(inp.acceptanceWhyOf!(quiet)).toBe("");
    const subset = { ...quiet, sampleDeviations: ["ATLAS_FIRST_PALETTE_TRIALS=10 is below E2's 20 repetitions"] };
    expect(inp.acceptanceEvidenceOf!(subset)).toBe(false);
    expect(inp.acceptanceWhyOf!(subset)).toMatch(/sample/i);
    expect(inp.acceptanceWhyOf!(subset)).toContain("ATLAS_FIRST_PALETTE_TRIALS=10");
  });

  /* Verifier round 3 (V-R6-3, 2026-09-27): host-env's hostPower returns `{known:false}` with no
     `throttled` field when its probe fails, and the gate read only `throttled` — so a power probe that
     returned nothing counted as "on mains". Observed in a real run: "power: unknown (probe returned
     \"\")" with no qualifier. Unknown power is not a quiet host, in the gate and in the E3 history. */
  it("unknown host power is not a quiet host: it withholds ACCEPTANCE EVIDENCE and says so", async () => {
    const inp = await loadInp();
    const quiet: AcceptanceInputs = {
      lane: "evidence",
      devServer: false,
      softwareRasteriser: false,
      rendererKnown: true,
      fresh: true,
      windows: [{ leg: "1920x1080 dark", plan: { fits: true }, check: { checked: true, inside: true } }],
      headed: true,
      hostBusy: 0.1,
      maxHostBusy: 0.25,
      powerKnown: true,
      powerThrottled: false,
      belowFullRate: false,
      sampleDeviations: [],
    };
    expect(inp.acceptanceEvidenceOf!(quiet), "precondition: known mains power, otherwise quiet, is evidence").toBe(true);
    const unknown = { ...quiet, powerKnown: false };
    expect(inp.acceptanceEvidenceOf!(unknown), "a failed power probe is not 'on mains'").toBe(false);
    expect(inp.acceptanceWhyOf!(unknown)).toMatch(/power .*not known|power could not be read/i);
    const { powerKnown: _omitted, ...absent } = quiet;
    expect(inp.acceptanceEvidenceOf!(absent as AcceptanceInputs), "an absent power reading is not health either").toBe(false);
  });

  it("the E3 history counts a run as quiet only when its power was READ as mains", async () => {
    const inp = await loadInp();
    expect(typeof inp.isQuietRunRecord, "measure-inp exports the quiet-run rule, so it can be pinned").toBe("function");
    const rec = { sample: "declared", hostBusy: 0.1, hostPowerKnown: true, hostPowerThrottled: false, presentationBelowFullRate: false };
    expect(inp.isQuietRunRecord!(rec, 0.25), "precondition: a quiet declared run on known mains counts").toBe(true);
    expect(inp.isQuietRunRecord!({ ...rec, hostPowerKnown: false }, 0.25), "unknown power").toBe(false);
    const { hostPowerKnown: _omitted, ...legacy } = rec;
    expect(inp.isQuietRunRecord!(legacy, 0.25), "a record from before the power-known field cannot claim it").toBe(false);
    expect(inp.isQuietRunRecord!({ ...rec, sample: "subset" }, 0.25)).toBe(false);
    expect(inp.isQuietRunRecord!({ ...rec, hostBusy: 0.3 }, 0.25)).toBe(false);
    expect(inp.isQuietRunRecord!({ ...rec, hostPowerThrottled: true }, 0.25)).toBe(false);
    expect(inp.isQuietRunRecord!({ ...rec, presentationBelowFullRate: true }, 0.25)).toBe(false);
    /* Every field the rule reads is one the run's history record writes (a rule over a field no record
       carries would exclude every run, silently). */
    const src = readFileSync(INP, "utf8").replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/[^\n]*/g, "");
    const rule = /export function isQuietRunRecord\(([a-z]+)[^)]*\)\s*\{([\s\S]*?)\n\}/.exec(src);
    expect(rule, "precondition: the rule's source is found").not.toBeNull();
    const reads = [...new Set([...rule![2]!.matchAll(new RegExp(`\\b${rule![1]}\\.(\\w+)`, "g"))].map((m) => m[1]!))];
    expect(reads.length, "precondition: the rule reads record fields").toBeGreaterThanOrEqual(4);
    const record = /const record = \{([\s\S]*?)\n\s*\};/.exec(src);
    expect(record, "precondition: the history record's source is found").not.toBeNull();
    expect(reads.filter((f) => !new RegExp(`\\b${f}\\b`).test(record![1]!)), "a field the quiet-run rule reads that no record writes").toEqual([]);
  });

  it("every verdict the run assigns goes through the sample rule (the class: every assignment in the source)", () => {
    /* Each record's verdicts are printed the moment they are assigned, so the rule is applied AT the
       assignment — a relabel after the loops would come after the per-journey PASS lines. Only the two
       verdicts that are never a pass may be assigned bare. */
    const src = readFileSync(INP, "utf8").replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/[^\n]*/g, "");
    const sites = [...src.matchAll(/\b\w+\.(verdict|e3Verdict)\s*=(?!=)\s*/g)].map((m) => ({
      field: m[1]!,
      rhs: src.slice(m.index! + m[0].length, m.index! + m[0].length + 40),
    }));
    expect(sites.length, "precondition: the harness assigns verdicts (none found pins nothing)").toBeGreaterThanOrEqual(6);
    const bare = sites.filter((x) => !x.rhs.startsWith("sampleLabel(") && !/^"(NOT MEASURED|TRANSPORT)"/.test(x.rhs));
    expect(bare.map((x) => `${x.field} = ${x.rhs}`), "a verdict that can be PASS is assigned without the sample rule").toEqual([]);
    expect(sites.filter((x) => x.rhs.startsWith("sampleLabel(")).length, "the computed verdicts (journeys, first selection, first palette) are all labelled").toBeGreaterThanOrEqual(6);
  });
});

describe("a window that was never checked is reported as not checked, not as outside the screen (D4)", () => {
  it("names each of the states a window can be in, in agreement with the one fit rule", async () => {
    const inp = await loadInp();
    expect(typeof inp.windowStatusOf).toBe("function");
    const fits = { fits: true };
    const cases: [unknown, unknown, string][] = [
      [fits, { checked: true, inside: true }, "fits"],
      [fits, { checked: false }, "not-checked"],
      [fits, undefined, "not-checked"],
      [fits, { checked: true, inside: false }, "outside"],
      [{ fits: false }, { checked: true, inside: true }, "plan-does-not-fit"],
      [null, { checked: true, inside: true }, "no-plan"],
    ];
    for (const [plan, check, want] of cases) {
      expect(inp.windowStatusOf!(plan, check), JSON.stringify({ plan, check })).toBe(want);
      expect(inp.windowFitsOf!(plan, check), "only a window that fits is a measurement environment").toBe(want === "fits");
    }
  });

  it("the receipt for an unchecked window says 'not checked', never 'not inside the screen'", async () => {
    const inp = await loadInp();
    const base: AcceptanceInputs = {
      lane: "evidence",
      devServer: false,
      softwareRasteriser: false,
      rendererKnown: true,
      fresh: true,
      windows: [
        { leg: "1280x800 dark", plan: { fits: true }, check: { checked: false } },
        { leg: "1920x1080 dark", plan: { fits: true }, check: { checked: true, inside: true } },
      ],
      headed: true,
      hostBusy: 0.1,
      maxHostBusy: 0.25,
      powerKnown: true,
      powerThrottled: false,
      belowFullRate: false,
      sampleDeviations: [],
    };
    expect(inp.acceptanceEvidenceOf!(base), "an unchecked window is not known to fit").toBe(false);
    const why = inp.acceptanceWhyOf!(base);
    expect(why).toMatch(/not checked/i);
    expect(why).toContain("1280x800 dark");
    expect(why, "the leg that was checked and fits is not blamed").not.toContain("1920x1080 dark");
    expect(why).not.toMatch(/not inside the screen/i);
    const outside = { ...base, windows: [{ leg: "1920x1080 dark", plan: { fits: true }, check: { checked: true, inside: false } }] };
    expect(inp.acceptanceWhyOf!(outside)).toMatch(/not inside the screen/i);
  });
});

/* ── 5. every verdict the run prints is over the declared sample, or says it is not (verifier R6 round 1, V1/V2, 2026-09-27) ──
 *
 * V1. `ATLAS_E3_MIN_RUNS=1` is a declared sample knob whose only effect is the ACROSS-RUNS E3 verdict,
 * and that verdict never went through the sample rule: over one quiet declared record the run printed
 * "E3 across runs … (1 run(s), need 1): PASS — J5-first-open-palette STABLE PASS" after announcing
 * itself a SUBSET run; under the declared 3-run rule it is INSUFFICIENT RUNS. The source scan above
 * matched `.verdict =` and `.e3Verdict =` only — two property names standing in for "every verdict
 * the run prints". The class here is every PASS the harness SPELLS: every string literal that is a
 * PASS verdict and is not being compared with must be produced through `sampleLabel`, and every
 * function that labels through a parameter must be handed the deviations at every call.
 *
 * V2. `ATLAS_ONLY=zzz-nomatch` selected nothing, exited 0, and printed the across-runs verdict "PASS —"
 * over an empty list (a vacuous `.every`): absence rendered as health.
 */
describe("every verdict the run prints goes through the sample rule, and nothing measured is never a pass (V1, V2)", () => {
  const PASS_SPELLING = /^(?:[A-Z0-9]+[ -])*PASS(?:[ -][A-Z0-9]+)*$/;
  const COMPARE = new Set([ts.SyntaxKind.EqualsEqualsEqualsToken, ts.SyntaxKind.ExclamationEqualsEqualsToken, ts.SyntaxKind.EqualsEqualsToken, ts.SyntaxKind.ExclamationEqualsToken]);

  it("the verifier's run (ATLAS_E3_MIN_RUNS=1 over one quiet record) does not print an across-runs PASS", async () => {
    const inp = await loadInp();
    for (const k of ["e3StableVerdict", "e3AcrossRunsVerdictOf", "e3RunVerdictOf", "runExitCodeOf", "journeySelectionOf"] as const)
      expect(typeof inp[k], `measure-inp exports ${k}, so the rule can be pinned`).toBe("function");
    const d = inp.sampleDeviations!(inp.sampleOf!({ ATLAS_E3_MIN_RUNS: "1" }));
    expect(d.length, "precondition: lowering the across-runs threshold is a subset").toBeGreaterThan(0);
    const oneQuietRun = [{ journeys: { "J5-first-open-palette": { e3: "E3-PASS" } } }];
    const subset = { "J5-first-open-palette": inp.e3StableVerdict!(oneQuietRun, "J5-first-open-palette", 1, d) };
    expect(subset["J5-first-open-palette"].stable, "a per-journey STABLE PASS under a lowered threshold").not.toMatch(/^STABLE PASS$/);
    expect(inp.e3AcrossRunsVerdictOf!(subset, d), "the across-runs roll-up of a subset run").not.toBe("PASS");
    expect(inp.e3AcrossRunsVerdictOf!(subset, d)).toMatch(/SUBSET/);
    /* ...and over the declared sample the rule is unchanged: one run is not enough, three clean runs are. */
    const declared = { "J5-first-open-palette": inp.e3StableVerdict!(oneQuietRun, "J5-first-open-palette", 3, []) };
    expect(inp.e3AcrossRunsVerdictOf!(declared, [])).toBe("INSUFFICIENT RUNS");
    const three = [...oneQuietRun, ...oneQuietRun, ...oneQuietRun];
    expect(inp.e3AcrossRunsVerdictOf!({ J: inp.e3StableVerdict!(three, "J5-first-open-palette", 3, []) }, [])).toBe("PASS");
    const fail = [...oneQuietRun, ...oneQuietRun, { journeys: { "J5-first-open-palette": { e3: "E3-FAIL" } } }];
    expect(inp.e3AcrossRunsVerdictOf!({ J: inp.e3StableVerdict!(fail, "J5-first-open-palette", 3, []) }, [])).toBe("FAIL");
    expect(inp.e3AcrossRunsVerdictOf!({ J: inp.e3StableVerdict!(fail, "J5-first-open-palette", 3, d) }, d), "a violation seen in a subset run is still a violation").toMatch(/FAIL/);
    /* The per-run E3 roll-up too. */
    expect(inp.e3RunVerdictOf!([{ e3Verdict: "E3-PASS" }], [])).toBe("PASS");
    expect(inp.e3RunVerdictOf!([{ e3Verdict: inp.sampleLabel!("E3-PASS", d) }], d)).not.toBe("PASS");
  });

  it("the class: every PASS the harness spells is produced through sampleLabel, handed the deviations at every call", () => {
    const text = readFileSync(INP, "utf8");
    const sf = ts.createSourceFile(INP, text, ts.ScriptTarget.Latest, true, ts.ScriptKind.JS);
    const spelled: ts.StringLiteralLike[] = [];
    const calls: ts.CallExpression[] = [];
    const visit = (n: ts.Node): void => {
      if ((ts.isStringLiteral(n) || ts.isNoSubstitutionTemplateLiteral(n)) && PASS_SPELLING.test(n.text) && !n.text.includes("SUBSET")) spelled.push(n);
      if (ts.isCallExpression(n)) calls.push(n);
      ts.forEachChild(n, visit);
    };
    visit(sf);
    const where = (n: ts.Node): string => `${n.getText(sf)} at line ${sf.getLineAndCharacterOfPosition(n.getStart(sf)).line + 1}`;
    /** The sampleLabel call whose VERDICT argument this literal is (through parentheses and ternary branches), or null. */
    const labelCallOf = (lit: ts.Node): ts.CallExpression | null => {
      let n: ts.Node = lit;
      for (;;) {
        const p = n.parent;
        if (ts.isParenthesizedExpression(p)) n = p;
        else if (ts.isConditionalExpression(p) && (p.whenTrue === n || p.whenFalse === n)) n = p;
        else if (ts.isCallExpression(p) && ts.isIdentifier(p.expression) && p.expression.text === "sampleLabel" && p.arguments[0] === n) return p;
        else return null;
      }
    };
    const produced = spelled.filter((lit) => {
      const p = lit.parent;
      if (ts.isBinaryExpression(p) && COMPARE.has(p.operatorToken.kind)) return false; // compared with, not printed
      if (ts.isPropertyAssignment(p) && p.name === lit) return false; // an object key (the SUBSET spelling table)
      return true;
    });
    expect(produced.length, "precondition: the harness spells PASS verdicts (none found pins nothing)").toBeGreaterThanOrEqual(6);
    expect(produced.filter((lit) => labelCallOf(lit) === null).map(where), "a PASS the harness spells without the sample rule").toEqual([]);
    /* The deviations each label is handed: the run's own, or a parameter of the function it is in — and
       then every call of that function, anywhere in the harness, must hand it on. */
    const labellers = new Map<string, number>();
    for (const lit of produced) {
      const call = labelCallOf(lit)!;
      const dev = call.arguments[1];
      expect(dev !== undefined && ts.isIdentifier(dev), `${where(call)}: sampleLabel is handed its deviations by name`).toBe(true);
      if (dev!.getText(sf) === "RUN_SAMPLE_DEVIATIONS") continue;
      /* The function whose parameter it is: the nearest enclosing one that declares it (a callback in
         between closes over it). */
      let fn: ts.Node | undefined = call.parent;
      const declares = (n: ts.Node): boolean => ts.isFunctionLike(n) && n.parameters.some((prm) => prm.name.getText(sf) === dev!.getText(sf));
      while (fn !== undefined && !declares(fn)) fn = fn.parent;
      const decl = fn as ts.FunctionLikeDeclaration | undefined;
      const at = decl?.parameters.findIndex((prm) => prm.name.getText(sf) === dev!.getText(sf)) ?? -1;
      expect(at, `${where(call)}: its deviations are neither the run's nor a parameter`).toBeGreaterThanOrEqual(0);
      const name =
        decl !== undefined && ts.isFunctionDeclaration(decl) && decl.name ? decl.name.text : decl !== undefined && ts.isVariableDeclaration(decl.parent) ? decl.parent.name.getText(sf) : null;
      expect(name, `${where(call)}: a labelling function the harness cannot name`).not.toBeNull();
      labellers.set(name!, at);
    }
    expect(labellers.size, "precondition: the across-runs rule labels through a parameter").toBeGreaterThan(0);
    const shortCalls = calls.filter((c) => ts.isIdentifier(c.expression) && labellers.has(c.expression.text) && c.arguments.length <= labellers.get(c.expression.text)!);
    expect(shortCalls.map(where), "a labelling function called without the deviations").toEqual([]);
  });

  it("a selection that matches no journey measures nothing: NOT MEASURED, never a pass, and a non-zero exit", async () => {
    const inp = await loadInp();
    const all = inp.journeySelectionOf!(null);
    expect(all, "no selection is every journey, the first selection and the first palette open").toEqual([...inp.JOURNEYS.map((j) => j.id), inp.FIRST_SELECTION.id, inp.FIRST_PALETTE!.id]);
    expect(inp.journeySelectionOf!(["J5-first"])).toEqual([inp.FIRST_PALETTE!.id]);
    expect(inp.journeySelectionOf!(["zzz-nomatch"]), "the verifier's selection").toEqual([]);
    expect(inp.e3AcrossRunsVerdictOf!({}, []), "an across-runs roll-up over no journey").toBe("NOT MEASURED");
    expect(inp.e3RunVerdictOf!([], []), "a per-run roll-up over no journey").toBe("NOT MEASURED");
    expect(inp.runExitCodeOf!([]), "a run that measured nothing").not.toBe(0);
    /* The exit code is a positive rule: every journey passed on both axes, over the declared sample. */
    expect(inp.runExitCodeOf!([{ verdict: "PASS", e3Verdict: "E3-PASS" }])).toBe(0);
    expect(inp.runExitCodeOf!([{ verdict: "FLOOR-PASS", e3Verdict: "E3-PASS" }])).toBe(0);
    for (const bad of [
      { verdict: "PASS", e3Verdict: "E3-FAIL" },
      { verdict: "FAIL", e3Verdict: "E3-PASS" },
      { verdict: "NOT MEASURED", e3Verdict: "NOT MEASURED" },
      { verdict: "TRANSPORT", e3Verdict: "NOT MEASURED" },
      { verdict: "SUBSET-PASS", e3Verdict: "E3-SUBSET-PASS" },
    ])
      expect(inp.runExitCodeOf!([{ verdict: "PASS", e3Verdict: "E3-PASS" }, bad]), JSON.stringify(bad)).not.toBe(0);
    /* ...and it is the run's exit code: main exits through the rule, and takes its selection from the pure one. */
    const src = readFileSync(INP, "utf8").replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/[^\n]*/g, "");
    const exits = [...src.matchAll(/process\.exit\(((?:[^()]|\([^()]*\))*)\)/g)].map((m) => m[1]!.trim());
    expect(exits.length, "precondition: the harness exits explicitly").toBeGreaterThan(0);
    expect(exits.filter((a) => !/^\d+$/.test(a)), "a computed exit code that is not the rule").toEqual(["runExitCodeOf(results)"]);
    expect(src, "main takes its selection from the pure rule").toMatch(/journeySelectionOf\(ONLY\)/);
    expect(inp.NON_SAMPLE_ENV!.ATLAS_ONLY, "the classification says what an empty selection does").toMatch(/no journey/i);
  });
});
