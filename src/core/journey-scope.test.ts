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
}
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
  const rec: Recorder = { inputs: [], focus: null };
  const page = recordingPage(rec);
  await inp.FIRST_SELECTION.beforeClick(page).catch(() => null);
  const measured: Input[] = [];
  rec.inputs = measured;
  await inp.FIRST_SELECTION.act(page, { x: 10, y: 10 }).catch(() => null);
  rec.inputs = [];
  out.push({ id: inp.FIRST_SELECTION.id, inputs: measured });
  return out;
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
    const ids = [...inp.JOURNEYS.map((j) => j.id), inp.FIRST_SELECTION.id].sort();
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
    const ids = [...inp.JOURNEYS.map((j) => j.id), inp.FIRST_SELECTION.id];
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
