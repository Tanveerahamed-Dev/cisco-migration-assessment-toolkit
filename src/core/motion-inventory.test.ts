/**
 * motion-inventory.test.ts — design brief §4.8 lists every animation the code declares (C6).
 *
 * WHY. §4.8 is titled "every animation, its duration, its justification", and the acceptance
 * report (C6) found it omitted two: the 900 ms infinite `stage-pending-spin` keyframes in App.css
 * and the 300 ms tier cross-fade in scene.ts (`TIER_FADE_MS`). Meanwhile App.css and flow.ts EACH
 * claimed to be "the only looping animation" — at most one of those can be true.
 *
 * The check is structural, not a list of names: it discovers the animations from the code — every
 * `@keyframes` in a stylesheet, and every `*_MS` constant a script feeds into an inline CSS
 * `transition` — and requires §4.8 to name each one with its duration. A new animation added
 * without an inventory row fails here by name.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const PKG = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
const SRC = resolve(PKG, "src");

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const p = join(dir, name);
    return statSync(p).isDirectory() ? walk(p) : [p];
  });
}
const files = walk(SRC).filter((f) => !/\.test\.tsx?$/.test(f));
const rel = (f: string) => relative(PKG, f).split("\\").join("/");

const brief = readFileSync(resolve(PKG, "docs", "design-brief.md"), "utf8");
const s48 = (() => {
  const a = brief.indexOf("### 4.8 ");
  const b = brief.indexOf("### 4.9 ", a);
  expect(a, "design brief §4.8 exists").toBeGreaterThanOrEqual(0);
  return brief.slice(a, b < 0 ? undefined : b);
})();

/** Every `@keyframes name` in a stylesheet, with the durations its `animation:` users declare. */
const keyframes = files
  .filter((f) => f.endsWith(".css"))
  .flatMap((f) => {
    const css = readFileSync(f, "utf8");
    return [...css.matchAll(/@keyframes\s+([\w-]+)/g)].map((m) => {
      const name = m[1]!;
      const uses = [...css.matchAll(new RegExp(`animation:\\s*${name}\\s+(\\d+m?s)([^;]*);`, "g"))];
      return { file: rel(f), name, durations: uses.map((u) => u[1]!), infinite: uses.some((u) => /\binfinite\b/.test(u[2]!)) };
    });
  });

/** Every `*_MS` constant a script interpolates into an inline `transition`, with its value. */
const scriptTransitions = files
  .filter((f) => /\.tsx?$/.test(f))
  .flatMap((f) => {
    const ts = readFileSync(f, "utf8");
    return [...ts.matchAll(/transition\s*=\s*`[^`]*\$\{([A-Z][A-Z0-9_]*_MS)\}/g)].map((m) => {
      const name = m[1]!;
      const value = new RegExp(`const\\s+${name}\\s*=\\s*(\\d+)`).exec(ts)?.[1];
      return { file: rel(f), name, value };
    });
  });

describe("§4.8 inventories every animation the code declares", () => {
  it("finds the animations it is meant to find (the scan is not vacuous)", () => {
    expect(keyframes.map((k) => k.name)).toContain("stage-pending-spin");
    expect(scriptTransitions.map((t) => t.name)).toContain("TIER_FADE_MS");
  });

  it("names every @keyframes with its duration, and says when it is infinite", () => {
    for (const k of keyframes) {
      expect(s48, `${k.file}: @keyframes ${k.name} is not in §4.8`).toContain(`\`${k.name}\``);
      for (const d of k.durations) expect(s48, `${k.name}: duration ${d} not stated`).toContain(d);
      if (k.infinite) expect(s48, `${k.name} loops forever; §4.8 must say so`).toMatch(new RegExp(`${k.name}[^\\n]*infinite`));
    }
  });

  it("names every script-driven transition with its duration", () => {
    for (const t of scriptTransitions) {
      expect(t.value, `${t.file}: ${t.name} has a literal value`).toBeDefined();
      expect(s48, `${t.file}: ${t.name} is not in §4.8`).toContain(`\`${t.name}\``);
      expect(s48, `${t.name}: ${t.value} ms not stated`).toMatch(new RegExp(`${t.name}[^\\n]*\\b${t.value} ms`));
    }
  });

  it("every inventoried animation states its reduced-motion behaviour on its own row", () => {
    for (const name of [...keyframes.map((k) => k.name), ...scriptTransitions.map((t) => t.name)]) {
      const row = s48.split("\n").find((l) => l.startsWith("|") && l.includes(`\`${name}\``));
      expect(row, `${name} has a table row`).toBeDefined();
      expect(row!, `${name}: reduced-motion behaviour`).toMatch(/reduced motion/i);
    }
  });

  it("every 'only looping animation' claim is about the one loop that runs, the packet marker", () => {
    /* App.css and flow.ts each claimed to be "the only looping animation" — a contradiction. The
       truth, read from the code: two loops are DECLARED (the unbounded `stage-pending-spin`, and
       the packet marker, bounded at PACKET_LOOPS), and only the packet marker ever RUNS, because
       no component renders `.stage-pending__spinner`. So a superlative is true only when it is
       about the packet marker. Discovered from the text, not from a list of files: any comment or
       brief row making the claim is checked, wherever it is. */
    const norm = (t: string) => t.replace(/\s*\*\s*/g, " ").replace(/\s+/g, " ");
    const sources = [
      ...files.filter((f) => /\.(css|tsx?)$/.test(f)).map((f) => ({ where: rel(f), text: norm(readFileSync(f, "utf8")) })),
      { where: "docs/design-brief.md §4.8", text: norm(s48) },
    ];
    const bad: string[] = [];
    let claims = 0;
    for (const { where, text } of sources) {
      for (const m of text.matchAll(/\bonly\s+looping\s+animation\b/gi)) {
        claims++;
        /* The claim's SUBJECT: the ~120 characters before it (a comment's field label, a table
           row's first cell, "the trace packet marker is …") and the rest of its own sentence. Not a
           wide window: a corrected comment that happens to mention the packet a sentence later
           must not excuse a false claim made in the sentence before it. */
        const tail = text.slice(m.index!);
        const end = tail.search(/[.;]\s/);
        const around = text.slice(Math.max(0, m.index! - 120), m.index! + (end < 0 ? tail.length : end));
        if (!/packet/i.test(around)) bad.push(`${where}: …${text.slice(Math.max(0, m.index! - 80), m.index! + 60)}…`);
      }
    }
    expect(bad, "a claim to be the only loop, about something other than the packet marker").toEqual([]);
    expect(claims, "the scan found the claims it is meant to police").toBeGreaterThan(0);
  });

  it("the unbounded spinner is still unrendered, which is what makes the packet the only running loop", () => {
    /* If a component starts rendering the spinner, the packet is no longer the only loop that runs
       and every claim above becomes false: this fails first, so the claims get revisited. */
    const users = files
      .filter((f) => /\.(tsx?|html)$/.test(f))
      .filter((f) => readFileSync(f, "utf8").includes("stage-pending__spinner"))
      .map(rel);
    expect(users).toEqual([]);
  });
});

/* ── rAF-driven eases (C6, independent refuter 2026-09-22) ─────────────────────────────────────
 *
 * WHY. Everything above sees only what CSS animates. The fades a reader actually notices on the
 * fabric — dim/undim, the hover rim, the selection halo — are stepped by JavaScript on every
 * animation frame, and they were EXPONENTIAL: `k = min(1, dt / RECEDE_MS); cur += (tgt - cur) * k`,
 * snapping only inside an epsilon. `RECEDE_MS = 240` was therefore a time CONSTANT, not a duration:
 * measured, the recession settled at 1,350 ms, the hover at ~417 ms and the halo at ~917 ms, while
 * §4.8 promised 240 / 80 / 140 ms. The inventory stayed green because it could not see any of them.
 *
 * So this half is structural too. It parses every source file with the TypeScript compiler and
 * finds every per-frame interpolation of the two shapes an exponential ease takes —
 *   (a) an accumulator stepped towards a target: `x += (t - x) * k`, `x = x + (t - x) * k`;
 *   (b) a rate from a frame delta over a `*_MS` constant: `k = f(dt / SOMETHING_MS)`, and any
 *       `a + (b - a) * k` whose factor is such a rate —
 * and fails on any of them outside the ease owner (`src/fabric3d/emphasis.ts`). Then it steps every
 * ease the owner exports at 60 fps and holds its measured settle time against the row §4.8 states
 * for it, read from the brief itself.
 */
import ts from "typescript";
import { EASES, createEaseChannel, stepEaseChannel } from "../fabric3d/emphasis";

const EASE_OWNER = "src/fabric3d/emphasis.ts";

/** Every exponential-ease shape in one source text, as `line: text` strings. */
function findExponentialSteps(fileName: string, text: string): string[] {
  const sf = ts.createSourceFile(fileName, text, ts.ScriptTarget.Latest, true, fileName.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
  const hits: string[] = [];
  const strip = (e: ts.Expression): ts.Expression => {
    let x = e;
    while (ts.isParenthesizedExpression(x) || ts.isAsExpression(x) || ts.isNonNullExpression(x)) x = x.expression;
    return x;
  };
  const same = (a: ts.Node, b: ts.Node): boolean => a.getText(sf).replace(/\s+/g, "") === b.getText(sf).replace(/\s+/g, "");
  /** Whether identifier `id` is a parameter of a function enclosing it — the per-frame delta a
   *  step function is handed (`step(dt)`), as opposed to a local elapsed time (`now - start`). */
  const isEnclosingParam = (id: ts.Identifier): boolean => {
    for (let p: ts.Node | undefined = id.parent; p !== undefined; p = p.parent) {
      if (ts.isFunctionLike(p) && p.parameters.some((q) => ts.isIdentifier(q.name) && q.name.text === id.text)) return true;
    }
    return false;
  };
  /** `dt / FOO_MS` inside `e` (not inside a nested function): a frame delta over a millisecond
   *  constant, i.e. a per-frame RATE — the signature of an exponential ease. */
  const hasRate = (e: ts.Node): boolean => {
    let found = false;
    const visit = (n: ts.Node): void => {
      if (found || (n !== e && ts.isFunctionLike(n))) return;
      if (ts.isBinaryExpression(n) && n.operatorToken.kind === ts.SyntaxKind.SlashToken) {
        const l = strip(n.left);
        const r = strip(n.right);
        if (ts.isIdentifier(l) && ts.isIdentifier(r) && /_MS$/.test(r.text) && isEnclosingParam(l)) found = true;
      }
      ts.forEachChild(n, visit);
    };
    visit(e);
    return found;
  };
  /** `(t - x) * k` or `k * (t - x)`: returns [x, k] when it is one. */
  const towards = (e: ts.Expression): [ts.Expression, ts.Expression] | null => {
    const m = strip(e);
    if (!ts.isBinaryExpression(m) || m.operatorToken.kind !== ts.SyntaxKind.AsteriskToken) return null;
    for (const [d, k] of [[m.left, m.right], [m.right, m.left]] as const) {
      const diff = strip(d);
      if (ts.isBinaryExpression(diff) && diff.operatorToken.kind === ts.SyntaxKind.MinusToken) return [diff.right, k];
    }
    return null;
  };
  const rates = new Set<string>();
  const where = (n: ts.Node): string => `${sf.getLineAndCharacterOfPosition(n.getStart(sf)).line + 1}: ${n.getText(sf).replace(/\s+/g, " ").slice(0, 90)}`;
  const visit = (n: ts.Node): void => {
    // (b) a rate: `const k = Math.min(1, dt / RECEDE_MS)` (declaration or assignment)
    if (ts.isVariableDeclaration(n) && n.initializer !== undefined && hasRate(n.initializer)) {
      hits.push(where(n));
      if (ts.isIdentifier(n.name)) rates.add(n.name.text);
    }
    if (ts.isBinaryExpression(n)) {
      const op = n.operatorToken.kind;
      if (op === ts.SyntaxKind.EqualsToken && hasRate(n.right)) {
        hits.push(where(n));
        if (ts.isIdentifier(n.left)) rates.add(n.left.text);
      }
      // (a) `x += (t - x) * k`
      if (op === ts.SyntaxKind.PlusEqualsToken) {
        const t = towards(n.right);
        if (t !== null && same(t[0], n.left)) hits.push(where(n));
      }
      // (a) `x = x + (t - x) * k`, and (b) `a + (b - a) * k` with a rate factor
      if (op === ts.SyntaxKind.PlusToken) {
        const t = towards(n.right);
        if (t !== null && same(t[0], n.left)) {
          const parent = n.parent;
          const selfAssign =
            ts.isBinaryExpression(parent) && parent.operatorToken.kind === ts.SyntaxKind.EqualsToken && parent.right === n && same(parent.left, n.left);
          const k = strip(t[1]);
          const rateFactor = hasRate(k) || (ts.isIdentifier(k) && rates.has(k.text));
          if (selfAssign || rateFactor) hits.push(where(n));
        }
      }
    }
    ts.forEachChild(n, visit);
  };
  visit(sf);
  return [...new Set(hits)];
}

describe("§4.8 sees rAF-driven eases: no exponential step outside the ease owner", () => {
  it("the scanner is live: it flags an exponential step planted in a synthetic source", () => {
    const planted = [
      "const HOVER_MS = 80;",
      "export function step(dt: number) {",
      "  const kh = Math.min(1, dt / HOVER_MS);",
      "  hoverAlpha += (hoverTarget - hoverAlpha) * kh;",
      "  cur = cur + (tgt - cur) * 0.2;",
      "  const next = cur + (tgt - cur) * kh;",
      "}",
    ].join("\n");
    const hits = findExponentialSteps("planted.ts", planted);
    expect(hits.some((h) => h.startsWith("3:")), `rate not flagged: ${hits.join(" | ")}`).toBe(true);
    expect(hits.some((h) => h.startsWith("4:")), `+= step not flagged: ${hits.join(" | ")}`).toBe(true);
    expect(hits.some((h) => h.startsWith("5:")), `x = x + (t-x)*k not flagged: ${hits.join(" | ")}`).toBe(true);
    expect(hits.some((h) => h.startsWith("6:")), `lerp by a rate not flagged: ${hits.join(" | ")}`).toBe(true);
    // ...and a finite-duration ease or a geometric lerp is not an exponential step.
    const finite = [
      "export function f(nowMs: number, start: number, a: number, b: number, t: number) {",
      "  const p = Math.min(1, (nowMs - start) / CAMERA_TWEEN_MS);",
      "  return a + (b - a) * t + p;",
      "}",
    ].join("\n");
    expect(findExponentialSteps("finite.ts", finite)).toEqual([]);
  });

  it("finds none anywhere in src/ except the ease owner", () => {
    const offenders = files
      .filter((f) => /\.tsx?$/.test(f) && rel(f) !== EASE_OWNER)
      .flatMap((f) => findExponentialSteps(f, readFileSync(f, "utf8")).map((h) => `${rel(f)}:${h}`));
    expect(offenders, "a per-frame exponential ease outside src/fabric3d/emphasis.ts").toEqual([]);
  });

  it("the ease owner itself steps no exponential ease either: every ease there is finite", () => {
    const own = findExponentialSteps(EASE_OWNER, readFileSync(resolve(PKG, EASE_OWNER), "utf8"));
    expect(own, "the owner still carries an exponential step").toEqual([]);
  });
});

describe("§4.8 states, for every ease the owner exports, the settle time the ease actually has", () => {
  /** 60 fps, the display rate §4.8's settle figures are stated at. */
  const DT = 1000 / 60;
  /** Step one ease 0 -> 1 at 60 fps; the time of the first frame whose value IS the target. */
  const settleMs = (spec: (typeof EASES)[number], reduced = false): number => {
    const ch = createEaseChannel(0);
    for (let frames = 1; frames <= 10_000; frames += 1) {
      stepEaseChannel(ch, spec, 1, DT, reduced);
      if (ch.value === 1) return frames * DT;
    }
    return Infinity;
  };
  const rowOf = (name: string): string | undefined =>
    s48.split("\n").find((l) => l.startsWith("|") && l.includes("`" + name + "`"));

  it("the owner exports the eases the fabric steps (the check is not vacuous)", () => {
    expect(EASES.map((e) => e.name).sort()).toEqual(["HOVER_MS", "RECEDE_MS", "SELECT_MS"]);
  });

  for (const spec of EASES) {
    it(`${spec.name}: the §4.8 row's duration is the ease's, and its stated settle time is the measured one`, () => {
      const row = rowOf(spec.name);
      expect(row, `§4.8 has no row naming \`${spec.name}\``).toBeDefined();
      const duration = /\*\*(\d+(?:\.\d+)?) ms\*\*/.exec(row!)?.[1];
      expect(Number(duration), `${spec.name}: the row's bold duration`).toBe(spec.durationMs);
      const stated = /settles in \*\*(\d+(?:\.\d+)?) ms\*\* at 60 fps/.exec(row!)?.[1];
      expect(stated, `${spec.name}: the row states "settles in **N ms** at 60 fps"`).toBeDefined();
      // Rounded to the microsecond: 15 frames of 1000/60 ms is 250.00000000000003 in doubles.
      const measured = Math.round(settleMs(spec) * 1000) / 1000;
      // No later than stated, and stated no more than a millisecond of rounding above it.
      expect(measured, `${spec.name} settles at ${measured.toFixed(2)} ms, later than §4.8 states`).toBeLessThanOrEqual(Number(stated));
      expect(Number(stated) - measured, `${spec.name}: §4.8 overstates the settle time`).toBeLessThan(1);
      // And the C6 bar itself: under 300 ms.
      expect(measured).toBeLessThan(300);
      expect(row!, `${spec.name}: reduced-motion behaviour`).toMatch(/reduced motion/i);
    });

    it(`${spec.name}: under reduced motion the ease lands on its target in the frame it starts`, () => {
      expect(settleMs(spec, true)).toBe(DT);
    });
  }
});
