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

/** Every `@keyframes name` in one stylesheet, with the durations its `animation:` users declare.
 *  Takes the text rather than reading it, so the liveness proof below runs THIS function over a
 *  planted stylesheet instead of trusting the tree to still contain an example. */
function keyframesIn(file: string, css: string): { file: string; name: string; durations: string[]; infinite: boolean }[] {
  return [...css.matchAll(/@keyframes\s+([\w-]+)/g)].map((m) => {
    const name = m[1]!;
    const uses = [...css.matchAll(new RegExp(`animation:\\s*${name}\\s+(\\d+m?s)([^;]*);`, "g"))];
    return { file, name, durations: uses.map((u) => u[1]!), infinite: uses.some((u) => /\binfinite\b/.test(u[2]!)) };
  });
}
const stylesheets = files.filter((f) => f.endsWith(".css"));
const keyframes = stylesheets.flatMap((f) => keyframesIn(rel(f), readFileSync(f, "utf8")));

/** Every `*_MS` constant a script interpolates into an inline `transition`, with its value. */
function scriptTransitionsIn(file: string, text: string): { file: string; name: string; value: string | undefined }[] {
  return [...text.matchAll(/transition\s*=\s*`[^`]*\$\{([A-Z][A-Z0-9_]*_MS)\}/g)].map((m) => {
    const name = m[1]!;
    const value = new RegExp(`const\\s+${name}\\s*=\\s*(\\d+)`).exec(text)?.[1];
    return { file, name, value };
  });
}
const scriptTransitions = files
  .filter((f) => /\.tsx?$/.test(f))
  .flatMap((f) => scriptTransitionsIn(rel(f), readFileSync(f, "utf8")));

/** One frame at 60 Hz, the display rate every settle figure in §4.8 is stated at. */
const FRAME_60 = 1000 / 60;
/** Acceptance C6: "under 300 ms except deliberate camera moves". */
const C6_BAR_MS = 300;

describe("§4.8 inventories every animation the code declares", () => {
  it("finds the animations it is meant to find (the scan is not vacuous)", () => {
    /* The tree no longer declares any @keyframes (O18: the one it did, the unrendered
       `stage-pending-spin`, was dead CSS and is deleted), so a scan returning [] over the real tree
       proves nothing on its own. Liveness is proven by running the SAME scanner over a planted
       stylesheet — and the denominator by the stylesheets it walked. */
    const planted = keyframesIn(
      "planted.css",
      ".x { animation: planted-spin 900ms linear infinite; }\n@keyframes planted-spin { to { transform: rotate(1turn); } }",
    );
    expect(planted).toEqual([{ file: "planted.css", name: "planted-spin", durations: ["900ms"], infinite: true }]);
    expect(stylesheets.length, "the walk found the stylesheets").toBeGreaterThan(3);
    expect(stylesheets.map(rel)).toContain("src/app/App.css");

    expect(scriptTransitionsIn("planted.ts", "const FOO_MS = 120;\nel.style.transition = `opacity ${FOO_MS}ms linear`;")).toEqual([
      { file: "planted.ts", name: "FOO_MS", value: "120" },
    ]);
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
      /* ...and it is the row's STATED duration — its first bold "**N ms**" — not merely a number that
         appears somewhere in the row: the tier-fade row also quotes the old 300 ms measurement, and
         the looser match above passed with the constant put back to 300. */
      const row = s48.split("\n").find((l) => l.startsWith("|") && l.includes(`\`${t.name}\``));
      expect(/\*\*(\d+(?:\.\d+)?) ms\*\*/.exec(row ?? "")?.[1], `${t.name}: the row's bold duration`).toBe(t.value);
    }
  });

  it("every script-driven transition shows its end state before 300 ms, at 60 Hz (C6)", () => {
    /* A CSS transition of N ms shows its end state on the first frame at or after N — up to one
       frame later. The tier cross-fade was TIER_FADE_MS = 300 and MEASURED 299.9-300.1 ms (the
       acceptance grading, C6): at the ceiling, not under it. Held to the same rule as the rAF eases
       below: the first frame showing the end state lands under the bar. */
    for (const t of scriptTransitions) {
      const ms = Number(t.value);
      expect(
        ms + FRAME_60,
        `${t.file}: ${t.name} = ${t.value} ms can first show its end state at ${(ms + FRAME_60).toFixed(1)} ms`,
      ).toBeLessThan(C6_BAR_MS);
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
       truth, read from the code: the one loop the product declares is the packet marker, bounded at
       PACKET_LOOPS (the unbounded `stage-pending-spin` App.css also declared was never rendered and
       is deleted, O18). So a superlative is true only when it is about the packet marker.
       Discovered from the text, not from a list of files: any comment or brief row making the claim
       is checked, wherever it is. */
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

  it("no stylesheet declares an unbounded loop and nothing renders the deleted spinner, so the packet is the only loop", () => {
    /* What made the claims above true used to be that the unbounded spinner was DECLARED but never
       RENDERED. It is now deleted (O18), so the claims rest on a stronger fact: no @keyframes
       anywhere loops forever. A new `infinite` animation fails here first, so the claims get
       revisited — and §4.8 must not keep a row for an animation the code no longer has. */
    expect(keyframes.filter((k) => k.infinite).map((k) => `${k.file}: ${k.name}`)).toEqual([]);
    const users = files
      .filter((f) => /\.(tsx?|html)$/.test(f))
      .filter((f) => readFileSync(f, "utf8").includes("stage-pending__spinner"))
      .map(rel);
    expect(users).toEqual([]);
    expect(s48, "§4.8 still lists the deleted spinner").not.toMatch(/stage-pending-spin|stage-pending__spinner/);
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
 *       `a + (b - a) * k` whose factor is such a rate;
 *   (c) the same ease behind a library name: any `damp(...)` call (three's `MathUtils.damp` IS an
 *       exponential ease), a self-assigned `x = lerp(x, t, k)`, and its in-place method spelling
 *       `v.lerp(t, k)` / `q.slerp(t, k)` on a receiver not given an explicit start in the same
 *       function —
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
  /** Whether `recv` is given a fresh value earlier in the function enclosing `at` — `recv = …`, or
   *  a three setter on it (`recv.copy(…)`, `recv.set…(…)`, `recv.fromArray(…)`) — so an in-place
   *  lerp of it that follows starts from an explicit value rather than from last frame's. */
  const reinitialisedBefore = (recv: ts.Expression, at: ts.Node): boolean => {
    let fn: ts.Node | undefined = at.parent;
    while (fn !== undefined && !ts.isFunctionLike(fn)) fn = fn.parent;
    if (fn === undefined) return false;
    let found = false;
    const scan = (m: ts.Node): void => {
      if (found || m.getStart(sf) >= at.getStart(sf)) return;
      if (ts.isBinaryExpression(m) && m.operatorToken.kind === ts.SyntaxKind.EqualsToken && same(m.left, recv)) found = true;
      if (
        ts.isCallExpression(m) &&
        ts.isPropertyAccessExpression(m.expression) &&
        /^(copy|set\w*|fromArray)$/.test(m.expression.name.text) &&
        same(m.expression.expression, recv)
      ) {
        found = true;
      }
      ts.forEachChild(m, scan);
    };
    ts.forEachChild(fn, scan);
    return found;
  };
  const rates = new Set<string>();
  const where = (n: ts.Node): string => `${sf.getLineAndCharacterOfPosition(n.getStart(sf)).line + 1}: ${n.getText(sf).replace(/\s+/g, " ").slice(0, 90)}`;
  const visit = (n: ts.Node): void => {
    /* (c) `damp(x, t, lambda, dt)` / `MathUtils.damp(...)`: three's frame-rate-independent
       exponential ease, i.e. shape (a) behind a function name. Any call to it is one. */
    if (ts.isCallExpression(n) && /(^|\.)damp$/i.test(n.expression.getText(sf))) hits.push(where(n));
    /* (c) the METHOD spelling of a self-assigned lerp: `v.lerp(t, k)` / `q.slerp(t, k)` mutate `v`,
       so on a value that persists across frames they are `v = v + (t - v) * k`. A lerp from an
       explicit start is not: a receiver that is itself a call (`v.copy(from).lerp(to, p)`), or one
       re-initialised earlier in the same function (`out.copy(a); …; out.lerp(b, t)`), or the
       two-endpoint forms (`lerpVectors`, `lerpColors`), which the name pattern excludes. */
    if (ts.isCallExpression(n) && ts.isPropertyAccessExpression(n.expression) && /^s?lerp$/.test(n.expression.name.text)) {
      const recv = strip(n.expression.expression);
      if (!ts.isCallExpression(recv) && !reinitialisedBefore(recv, n)) hits.push(where(n));
    }
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
      // (c) the library spelling of (a): `x = lerp(x, t, k)` / `x = MathUtils.lerp(x, t, k)`
      if (op === ts.SyntaxKind.EqualsToken) {
        const call = strip(n.right);
        if (ts.isCallExpression(call) && /(^|\.)lerp$/i.test(call.expression.getText(sf)) && call.arguments[0] !== undefined && same(call.arguments[0], n.left)) {
          hits.push(where(n));
        }
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
      "  halo = MathUtils.damp(halo, target, 12, dt);",
      "  rim = lerp(rim, target, 0.2);",
      "  rig.position.lerp(goal, 0.1);",
      "  orient.slerp(qGoal, kh);",
      "}",
    ].join("\n");
    const hits = findExponentialSteps("planted.ts", planted);
    expect(hits.some((h) => h.startsWith("3:")), `rate not flagged: ${hits.join(" | ")}`).toBe(true);
    expect(hits.some((h) => h.startsWith("4:")), `+= step not flagged: ${hits.join(" | ")}`).toBe(true);
    expect(hits.some((h) => h.startsWith("5:")), `x = x + (t-x)*k not flagged: ${hits.join(" | ")}`).toBe(true);
    expect(hits.some((h) => h.startsWith("6:")), `lerp by a rate not flagged: ${hits.join(" | ")}`).toBe(true);
    expect(hits.some((h) => h.startsWith("7:")), `damp() not flagged: ${hits.join(" | ")}`).toBe(true);
    expect(hits.some((h) => h.startsWith("8:")), `x = lerp(x, t, k) not flagged: ${hits.join(" | ")}`).toBe(true);
    /* The METHOD spelling of a self-assigned lerp: three's Vector3/Color/Quaternion `lerp`/`slerp`
       mutate their receiver, so `v.lerp(t, k)` on a value that persists across calls IS
       `v = v + (t - v) * k` (review 2c: recorded as the scanner's blind spot, now closed). */
    expect(hits.some((h) => h.startsWith("9:")), `in-place v.lerp(t, k) not flagged: ${hits.join(" | ")}`).toBe(true);
    expect(hits.some((h) => h.startsWith("10:")), `in-place q.slerp(t, k) not flagged: ${hits.join(" | ")}`).toBe(true);
    // ...and a finite-duration ease or a geometric lerp is not an exponential step: a lerp from an
    // explicit start (a `copy` chain, or a receiver re-initialised earlier in the same function).
    const finite = [
      "export function f(nowMs: number, start: number, a: number, b: number, t: number) {",
      "  const p = Math.min(1, (nowMs - start) / CAMERA_TWEEN_MS);",
      "  v.copy(from).lerp(to, p);",
      "  return a + (b - a) * t + p;",
      "}",
      "export function tint(out: Color, y: number) {",
      "  out.copy(base);",
      "  out.setHSL(0, 0, 0.5);",
      "  out.lerp(white, 1 - y);",
      "  mid.lerpVectors(a, b, 0.5);",
      "  return out;",
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
