/**
 * determinism.test.ts — "what is drawn is a pure function of the data", enforced over the whole
 * source tree instead of over two filenames.
 *
 * WHAT THIS REPLACES, AND WHY. The predecessor of this gate lived inside `Inspector.test.tsx` and
 * had three defects, all of the same shape — a check that looks thorough and is scoped to a
 * hand-maintained subset of the thing it means:
 *
 *   1. SCOPE. It iterated `["Inspector.tsx", "JsonView.tsx"]`. The tree holds 50+ non-test source
 *      files. A clock read anywhere else was invisible to it.
 *   2. DETECTOR. It matched the literal strings `Math.random` and `Date.now`. `performance.now`,
 *      `crypto.getRandomValues`, `crypto.randomUUID`, an aliased import and an unpinned
 *      `toLocaleString` were all invisible — so the rule was true only by accident of naming.
 *   3. LIVENESS PROOF. It did not call the detector. It rebuilt a second, DIFFERENT visitor with
 *      no name filter and asserted that visitor found three planted calls. That passed because the
 *      planted string contains three property-access calls, not because the guard's filter works.
 *
 * It missed a real one: `runFlow` in `src/app/commands.ts` interpolated `trace.elapsedMs` — a
 * `performance.now()` delta computed in `src/forwarding/engine.ts` — into the `#sr-status` live
 * region on every trace, while that file's own header declared "NO CLOCK, NO RANDOMNESS".
 *
 * HOW THE RULE IS STATED NOW. Not as a list of forbidden names, and not as a list of exempt files.
 * Any member of the class below must carry an explicit `determinism:` justification AT THE SITE
 * saying why the value cannot reach the render. Seven exist today — two user-timing marks, two
 * halves of one elapsed-time measurement, one rAF timestamp parameter and two `e.timeStamp` reads
 * — and each says so where a reviewer reading that code will see it. A new clock read fails this
 * gate until someone writes down why it is safe, which is the only part a test can honestly ask
 * for.
 *
 * WHAT IT MISSED, AND WHY — the second rewrite (2026-09-21, acceptance F6).
 *
 * The version above detected clock CALL EXPRESSIONS. `src/fabric3d/scene.ts` never calls a clock:
 * its render loop is `function frame(now: number)`, and `requestAnimationFrame` HANDS it the
 * timestamp as a PARAMETER. From that parameter came `fpsEma`, then `SceneStats.fps`, then
 * `Math.round(stats.fps)` painted into the permanent status line of every screen. The gate was
 * green for the whole life of that path, and `grep -rn "Date.now(\|Math.random(" src/` returned
 * zero live call sites — while two consecutive `node review/capture.mjs app` runs differed in 23
 * of 32 frames, every differing pixel inside those digits. The denominator was provably not the
 * property: a gate cannot be exhaustive over "reads a clock" while it only knows one SYNTAX for
 * reading one.
 *
 * So the class is now stated by what a value IS, not by how it arrived:
 *
 *   - CALLS — `performance.now()`, `Date.now()`, `Math.random()`, `crypto.*`, unpinned locales.
 *   - BINDINGS — a clock handed to you. The two that exist in a browser and in this tree are the
 *     `requestAnimationFrame` callback's first parameter and a DOM event's `timeStamp`. Both are
 *     `performance.now()` by another route, and both now need the same written justification.
 *
 * And the value-flow rule below is no longer hard-coded to one field name. It was `elapsedMs`
 * only; `fps` reached a renderer beside it with nothing to stop it. It is now the FRAME-TIMING
 * FIELD CLASS, with a declared owner per field — which is the repair for the shape, rather than a
 * second entry on a list of one.
 *
 * WHAT IT CANNOT DO, stated rather than implied. It is a syntactic gate. It cannot follow a value,
 * so an annotation that lies passes; it reads only `src/`, so `tools/` and `review/` are outside
 * it (they generate artefacts, they do not render the product); and an indirection deliberately
 * built to defeat it — `const f = performance["now"]` — would not be seen. Nor is it the whole of
 * F6: only a real browser produces the bytes F6 speaks about, and `review/capture.mjs twice`
 * captures, re-captures and byte-compares them. This gate is the fast half that names the cause.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, extname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";
import { describe, expect, it } from "vitest";

const SRC = resolve(dirname(fileURLToPath(import.meta.url)), "..");

function sourceFiles(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) {
      if (name === "node_modules") continue;
      sourceFiles(p, out);
    } else if ([".ts", ".tsx"].includes(extname(p)) && !/\.test\.tsx?$/.test(p)) {
      out.push(p);
    }
  }
  return out;
}

/** How many times each distinct text has been parsed — counted, so the scan's cost is asserted rather than timed. */
const parsesOf = new Map<string, number>();
const parsedByText = new Map<string, ts.SourceFile>();

/**
 * One TSX parse of `text`, shared by every rule that reads it. Both detectors below read source
 * only through this.
 *
 * Keyed by the TEXT, not the name: the clock rule is handed an absolute path and the frame-timing
 * rule a `src/`-relative one for the same file, and a parse depends on the text and the script kind
 * alone (the kind is fixed here). Nothing either detector reports comes from `sf.fileName` — lines
 * come from the text, owners from the `rel` argument — so a shared tree cannot change a verdict. It
 * can only stop the tree being parsed three times per run, which is what took one of these rules
 * past the 30 s limit on a loaded host (acceptance F2, 2026-09-24).
 */
function parse(fileName: string, text: string): ts.SourceFile {
  const hit = parsedByText.get(text);
  if (hit !== undefined) return hit;
  parsesOf.set(text, (parsesOf.get(text) ?? 0) + 1);
  const sf = ts.createSourceFile(fileName, text, ts.ScriptTarget.ES2023, true, ts.ScriptKind.TSX);
  parsedByText.set(text, sf);
  return sf;
}

/** A justification a human wrote at the call site. Deliberately the only escape hatch. */
const JUSTIFICATION = /determinism\s*:/;

/**
 * Where a justification has to be for this call to count as justified: anywhere in the ENCLOSING
 * FUNCTION at or above the call — its doc comment included — or, outside any function, in the
 * enclosing statement's own leading comment.
 *
 * Scoped to the function rather than to N lines above, because "N lines above" is a guess that
 * breaks the moment someone reformats, and because the unit a reader actually judges is the
 * function: `mark()` in scene.ts reads the clock twice for one measurement, and one note about
 * `mark()` is the honest number of notes. It does mean a justified function covers every clock
 * read inside it, which is why the ratchet below keeps the justified population small.
 */
function justificationWindow(call: ts.Node): { start: number; end: number } {
  let anchor: ts.Node = call;
  let scope: ts.Node | null = null;
  for (let n: ts.Node | undefined = call.parent; n !== undefined; n = n.parent) {
    if (
      ts.isFunctionDeclaration(n) ||
      ts.isFunctionExpression(n) ||
      ts.isArrowFunction(n) ||
      ts.isMethodDeclaration(n)
    ) {
      scope = n;
      break;
    }
    if (ts.isSourceFile(n)) break;
  }
  anchor = scope ?? call;
  // Climb out to the statement that DECLARES it, so a doc comment above `const mark = () => …`
  // counts: an arrow function's own leading trivia begins after the `=`.
  while (
    anchor.parent !== undefined &&
    !ts.isBlock(anchor.parent) &&
    !ts.isSourceFile(anchor.parent) &&
    !ts.isModuleBlock(anchor.parent)
  ) {
    anchor = anchor.parent;
  }
  return { start: anchor.getFullStart(), end: call.getEnd() };
}

export interface Nondeterministic {
  /** 1-based line of the call. */
  line: number;
  /** What was called, as written. */
  call: string;
  /** Whether a `determinism:` justification is in scope for this call (see justificationWindow). */
  justified: boolean;
}

/**
 * Every direct clock or randomness source in one file.
 *
 * Parsed, not grepped: both the modules under test and this file DISCUSS these names in prose, and
 * a regex over raw text flags the sentence that states the rule — the approximating-a-parser
 * mistake `claim-lint.test.ts` documents. Takes the text rather than reading it, so the liveness
 * proofs below run the REAL function over planted source instead of re-implementing it.
 */
export function nondeterministic(fileName: string, text: string): Nondeterministic[] {
  const sf = parse(fileName, text);
  const hits: Nondeterministic[] = [];
  /* A rAF callback named once and scheduled from three places is ONE clock binding, not three. */
  const seen = new Set<number>();

  const record = (node: ts.Node, call: string): void => {
    const pos = node.getStart(sf);
    if (seen.has(pos)) return;
    seen.add(pos);
    const line = sf.getLineAndCharacterOfPosition(pos).line;
    const { start, end } = justificationWindow(node);
    hits.push({ line: line + 1, call, justified: JUSTIFICATION.test(text.slice(start, end)) });
  };

  /**
   * Function-like declarations by name, so a callback SCHEDULED by identifier can be resolved back
   * to its signature. `raf = requestAnimationFrame(frame)` is the shape in this tree, and a check
   * that only understood inline arrow callbacks would miss precisely the one that shipped.
   * Same-file resolution only — which is honest about what a single-file syntactic pass can know.
   */
  const declared = new Map<string, ts.SignatureDeclaration>();
  const index = (node: ts.Node): void => {
    if (ts.isFunctionDeclaration(node) && node.name) declared.set(node.name.text, node);
    if (
      ts.isVariableDeclaration(node) &&
      ts.isIdentifier(node.name) &&
      node.initializer !== undefined &&
      (ts.isArrowFunction(node.initializer) || ts.isFunctionExpression(node.initializer))
    ) {
      declared.set(node.name.text, node.initializer);
    }
    ts.forEachChild(node, index);
  };
  index(sf);

  const visit = (node: ts.Node): void => {
    if (ts.isCallExpression(node)) {
      const callee = node.expression.getText(sf);
      /* The CLASS, by the name being called, wherever it hangs from: `performance.now`,
         `Date.now`, `Math.random`, `crypto.getRandomValues`, `crypto.randomUUID`, and the same
         names reached through an alias or a destructured import. */
      const last = callee.split(".").pop() ?? callee;
      if (last === "now" || last === "random" || last === "getRandomValues" || last === "randomUUID") {
        record(node, `${callee}()`);
      }
      /* An unpinned locale formatter renders differently per machine, which is the same defect
         wearing different clothes. Pinned ones (`toLocaleString("en-GB")`) are deterministic and
         are not flagged. */
      if (/^toLocale/.test(last) && node.arguments.length === 0) {
        record(node, `${callee}() with no locale`);
      }
      /* A clock you were HANDED. `requestAnimationFrame(cb)` passes `cb` a DOMHighResTimeStamp —
         the same number `performance.now()` returns, reached without ever naming it. This is the
         route `scene.ts`'s frame rate took to the status bar past the previous detector. */
      if (last === "requestAnimationFrame") {
        const arg = node.arguments[0];
        const fn =
          arg === undefined
            ? undefined
            : ts.isArrowFunction(arg) || ts.isFunctionExpression(arg)
              ? arg
              : ts.isIdentifier(arg)
                ? declared.get(arg.text)
                : undefined;
        const param = fn?.parameters[0];
        if (param !== undefined) {
          record(param, `requestAnimationFrame timestamp parameter \`${param.name.getText(sf)}\``);
        }
      }
    }
    /* The other handed clock: a DOM event's own timestamp. Same value, same consequence. */
    if (ts.isPropertyAccessExpression(node) && node.name.text === "timeStamp") {
      record(node, `${node.getText(sf)}`);
    }
    if (
      ts.isElementAccessExpression(node) &&
      ts.isStringLiteral(node.argumentExpression) &&
      node.argumentExpression.text === "timeStamp"
    ) {
      record(node, `${node.getText(sf)}`);
    }
    if (ts.isNewExpression(node)) {
      const callee = node.expression.getText(sf);
      if (callee === "Date" && (node.arguments?.length ?? 0) === 0) record(node, "new Date()");
      if (callee === "Intl.DateTimeFormat" && (node.arguments?.length ?? 0) === 0) {
        record(node, "new Intl.DateTimeFormat() with no locale");
      }
      if (callee === "Intl.NumberFormat" && (node.arguments?.length ?? 0) === 0) {
        record(node, "new Intl.NumberFormat() with no locale");
      }
    }
    ts.forEachChild(node, visit);
  };
  visit(sf);
  return hits;
}

/**
 * Frame-timing fields, and the files that OWN each one.
 *
 * THE CLASS, not the one member of it that got caught first. The predecessor of this rule read
 * `elapsedMs` and nothing else — a `performance.now()` delta that had escaped onto the
 * `#sr-status` live region. It was written as a set of ONE, so when `fps` took the identical route
 * from `scene.ts` to the permanent status line this gate had nothing to say about it, and F6
 * failed with a green suite. A list of one is still a list, and a list standing in for the class
 * it means is the defect shape this repository keeps finding.
 *
 * The class is: a number derived from a clock, carried on a data structure, readable by anything
 * that imports the type. An owner is the file that COMPUTES it or the file that TYPES it.
 * Everywhere else it is a clock heading for the DOM, and the escape hatch is the same one the call
 * sites use — say at the read site why the value cannot make what is drawn depend on this machine.
 *
 * A `Map`, not an object literal: `OWNERS["toString"]` on a literal returns a function and silently
 * exempts a field named `toString` from the whole rule.
 */
const FRAME_TIMING_OWNERS = new Map<string, readonly string[]>([
  ["elapsedMs", ["forwarding/engine.ts", "core/types.ts"]],
  ["fps", ["fabric3d/scene.ts", "fabric3d/contract.ts", "fabric3d/telemetry.ts"]],
  ["frameMs", ["fabric3d/scene.ts", "fabric3d/contract.ts", "fabric3d/telemetry.ts"]],
  ["worstFrameMs", ["fabric3d/scene.ts", "fabric3d/contract.ts", "fabric3d/telemetry.ts"]],
  /* NOT a number, but the same class (critic F6, 2026-09-22): a value DERIVED from rAF frame times.
     `frameRateBelowBar` is the E4 bar's boolean (stepdown.ts createFrameRateBar, fed per frame in
     scene.ts) and StatusBar drew it on the permanent chrome as "below frame-rate bar" while this map
     named only the numbers. `quality` is the tier the step-down rule picks from the same clock, and
     `qualityReasons` the sentence that carries the measurement. Words derived from a clock are a
     clock heading for the DOM exactly as digits are. */
  ["frameRateBelowBar", ["fabric3d/stepdown.ts", "fabric3d/scene.ts", "fabric3d/telemetry.ts"]],
  ["quality", ["fabric3d/scene.ts", "fabric3d/quality.ts", "fabric3d/stepdown.ts", "fabric3d/contract.ts", "fabric3d/telemetry.ts"]],
  ["qualityReasons", ["fabric3d/scene.ts", "fabric3d/quality.ts", "fabric3d/stepdown.ts", "fabric3d/contract.ts", "fabric3d/telemetry.ts"]],
]);

export interface FrameTimingRead {
  line: number;
  /** The read, as written. */
  read: string;
  justified: boolean;
}

/**
 * Every read of a frame-timing field in one file, outside the files that own it.
 *
 * Parsed, not grepped: a text search flags `commands.ts`'s own comment explaining why it stopped
 * announcing `elapsedMs`, and this file's prose above — precisely the false positives that make a
 * gate get deleted. `rel` is the file's path relative to `src/`, in POSIX form.
 */
export function frameTiming(rel: string, text: string): FrameTimingRead[] {
  const sf = parse(rel, text);
  const out: FrameTimingRead[] = [];
  const visit = (node: ts.Node): void => {
    const field = ts.isPropertyAccessExpression(node)
      ? node.name.text
      : ts.isElementAccessExpression(node) && ts.isStringLiteral(node.argumentExpression)
        ? node.argumentExpression.text
        : ts.isBindingElement(node)
          ? (node.propertyName ?? node.name).getText(sf)
          : null;
    const owners = field === null ? undefined : FRAME_TIMING_OWNERS.get(field);
    if (owners !== undefined && !owners.includes(rel)) {
      const { start, end } = justificationWindow(node);
      out.push({
        line: sf.getLineAndCharacterOfPosition(node.getStart(sf)).line + 1,
        read: node.getText(sf).slice(0, 80),
        justified: JUSTIFICATION.test(text.slice(start, end)),
      });
    }
    ts.forEachChild(node, visit);
  };
  visit(sf);
  return out;
}

const files = sourceFiles(SRC);
/** Each file's text, read once for every rule below. */
const textOf = (() => {
  const texts = new Map<string, string>();
  return (f: string): string => {
    let t = texts.get(f);
    if (t === undefined) {
      t = readFileSync(f, "utf8");
      texts.set(f, t);
    }
    return t;
  };
})();
const relOf = (f: string): string => relative(SRC, f).split("\\").join("/");

/** `fn` per source file, computed on first use and shared by every later reader. */
function perFile<T>(fn: (f: string) => T): (f: string) => T {
  const memo = new Map<string, T>();
  return (f) => {
    if (!memo.has(f)) memo.set(f, fn(f));
    return memo.get(f) as T;
  };
}
/**
 * The two rules, one source file at a time (acceptance F2, 2026-09-24). Each rule used to be ONE test
 * that parsed and walked all ~2.4 MB of the tree — three times per run, once per test — and the
 * frame-timing one took 31.5 s on a loaded host against the 30 s limit. Now each file is parsed once
 * (`parse`, above), each rule walks it once (these memos), and each rule is one test PER FILE, the
 * policy vitest.config.ts states for a large unit of work. The ratchet below reads the same memo, so
 * it still counts the whole tree whether or not the per-file cases ran first.
 */
const clockHitsOf = perFile((f) => nondeterministic(f, textOf(f)));
const timingReadsOf = perFile((f) => frameTiming(relOf(f), textOf(f)));

describe("what is drawn is a pure function of the data", () => {
  it("scans the whole source tree — an empty or narrow scan is not a pass", () => {
    // The predecessor scanned 2 files and reported green. Anchor the denominator.
    expect(files.length).toBeGreaterThan(40);
    expect(files.some((f) => f.endsWith("commands.ts"))).toBe(true);
    expect(files.some((f) => f.endsWith("scene.ts"))).toBe(true);
    expect(files.some((f) => f.endsWith("engine.ts"))).toBe(true);
  });

  describe("reads no clock and no random source without a justification at the call site", () => {
    for (const f of files) {
      it(relOf(f), () => {
        const offenders = clockHitsOf(f)
          .filter((hit) => !hit.justified)
          .map((hit) => `${relOf(f)}:${hit.line} — ${hit.call}`);
        expect(
          offenders,
          "these read a clock or a random source with no `determinism:` note saying why the value\n" +
            "cannot reach what is rendered. Either remove the call, or justify it where it is written:\n" +
            offenders.join("\n"),
        ).toEqual([]);
      });
    }
  });

  it("keeps the justified population small enough to read", () => {
    /* A ratchet, not a budget. The escape hatch is only honest while few enough people use it that
       each one is actually reviewed; if this number climbs, the annotation has become a rubber
       stamp and the gate needs a stronger idea than a comment.

       The cap was 6 and is 8, and that is worth being explicit about, because raising a ratchet is
       normally how a gate dies. It did not rise because the escape hatch got looser. It rose
       because the DETECTOR's class got wider: the 2026-09-21 rewrite added clock-valued BINDINGS,
       and three true positives that were previously invisible now have to be annotated —
       `scene.ts`'s rAF timestamp parameter and `interaction.ts`'s two `e.timeStamp` reads. Four
       call-expression justifications plus three binding justifications is seven. Nothing that was
       already visible to this gate became exempt. */
    const justified: string[] = [];
    for (const f of files) {
      for (const hit of clockHitsOf(f)) {
        if (hit.justified) justified.push(`${relOf(f)}:${hit.line} — ${hit.call}`);
      }
    }
    expect(justified.length, `justified nondeterministic calls:\n${justified.join("\n")}`).toBeLessThanOrEqual(8);
    expect(justified.length, "the annotation path itself is never exercised").toBeGreaterThan(0);
  });

  describe("lets no frame-timing measurement reach a consumer unannounced", () => {
    for (const f of files) {
      it(relOf(f), () => {
        const leaks = timingReadsOf(f)
          .filter((leak) => !leak.justified)
          .map((leak) => `${relOf(f)}:${leak.line} — ${leak.read}`);
        expect(
          leaks,
          "a frame-timing measurement is read outside the files that own it, with no `determinism:`\n" +
            "note saying why it cannot make what is drawn depend on this machine:\n" +
            leaks.join("\n"),
        ).toEqual([]);
      });
    }
  });
});

describe("the tree is parsed once, however many rules read it", () => {
  /* ACCEPTANCE F2, 2026-09-24: "lets no frame-timing measurement reach a consumer unannounced" took
     31.5 s on a loaded host against the 30 s limit, and the two clock rules above 13 s and 10 s. Each
     of the three re-read, re-parsed and re-walked all ~2.4 MB of the tree. The cost is pinned as a
     COUNT: once both rules have run over the tree, no source file has been parsed more than once —
     whichever tests ran before this one, and in whatever order. */
  it("both rules over the whole tree together parse each source file once", () => {
    for (const f of files) {
      clockHitsOf(f);
      timingReadsOf(f);
    }
    const reparsed = files.filter((f) => (parsesOf.get(textOf(f)) ?? 0) !== 1).map((f) => `${relOf(f)}: ${parsesOf.get(textOf(f)) ?? 0} parses`);
    expect(reparsed).toEqual([]);
  });
});

describe("the detector is live — proven by running IT, not a copy of it", () => {
  /* The predecessor's liveness proof built a second visitor and asserted that one worked. These
     call `nondeterministic` itself, which is the only thing that proves the shipped filter fires. */

  it("catches every member of the class it claims to cover", () => {
    const planted = [
      "const a = Math.random();",
      "const b = Date.now();",
      "const c = performance.now();",
      "const d = crypto.getRandomValues(new Uint8Array(4));",
      "const e = crypto.randomUUID();",
      "const f = (123).toLocaleString();",
      "const g = new Date();",
      "const h = new Intl.NumberFormat();",
    ].join("\n");
    const hits = nondeterministic("planted.tsx", planted);
    expect(hits.map((h) => h.line)).toEqual([1, 2, 3, 4, 5, 6, 7, 8]);
    expect(hits.every((h) => !h.justified)).toBe(true);
  });

  it("sees a clock reached through an alias, which a literal-name match cannot", () => {
    const aliased = ["const clock = performance;", "const t = clock.now();", "const r = rng.random();"].join("\n");
    expect(nondeterministic("aliased.ts", aliased).map((h) => h.call)).toEqual(["clock.now()", "rng.random()"]);
  });

  it("does not flag prose that merely names them", () => {
    // The failure mode a grep has: every file that DOCUMENTS this rule would fail its own gate.
    const prose = [
      "/* Nothing here reads Date.now() or Math.random() on a rendered path. */",
      'const label = "performance.now()";',
      "const pinned = (1).toLocaleString('en-GB');",
      "const dated = new Date(snapshot.capturedAt);",
    ].join("\n");
    expect(nondeterministic("prose.ts", prose)).toEqual([]);
  });

  it("accepts a justified call and only a justified call", () => {
    const withNote = ["/* determinism: profiling only, never rendered. */", "const t = performance.now();"].join("\n");
    const without = ["/* a note that justifies nothing */", "const t = performance.now();"].join("\n");
    expect(nondeterministic("ok.ts", withNote).map((h) => h.justified)).toEqual([true]);
    expect(nondeterministic("bad.ts", without).map((h) => h.justified)).toEqual([false]);
  });

  it("reads a note in the enclosing function's doc comment, and does not leak it to the next one", () => {
    /* The attachment rule, asserted directly: one note covers the function it documents — the two
       clock reads of a single measurement — and stops at that function's closing brace. */
    const src = [
      "/** determinism: profiling only. */",
      "const mark = (fn) => {",
      "  const t0 = performance.now();",
      "  const out = fn();",
      "  performance.measure('x', { start: t0, end: performance.now() });",
      "  return out;",
      "};",
      "function label() {",
      "  return Date.now();",
      "}",
    ].join("\n");
    const hits = nondeterministic("scope.ts", src);
    expect(hits.map((h) => [h.line, h.justified])).toEqual([
      [3, true],
      [5, true],
      [9, false],
    ]);
  });

  it("sees a clock it was HANDED — the rAF parameter that carried the fps to the status bar", () => {
    /* The exact shape `scene.ts` has, and the exact reason the previous detector was blind to it:
       the callback is named, scheduled by identifier, and never calls anything. A call-expression
       detector returns [] for all three of these. */
    const scheduledByName = [
      "function frame(now: number): void {",
      "  raf = requestAnimationFrame(frame);",
      "  fpsEma = fpsEma * 0.9 + (1000 / Math.max(1, now - lastNow)) * 0.1;",
      "}",
      "raf = requestAnimationFrame(frame);",
    ].join("\n");
    const hits = nondeterministic("scene.ts", scheduledByName);
    // ONE binding, though it is scheduled from two places.
    expect(hits.map((h) => [h.line, h.call, h.justified])).toEqual([
      [1, "requestAnimationFrame timestamp parameter `now`", false],
    ]);

    const inline = "requestAnimationFrame((t) => { last = t; });";
    expect(nondeterministic("inline.ts", inline).map((h) => h.call)).toEqual([
      "requestAnimationFrame timestamp parameter `t`",
    ]);

    // A callback that does NOT take the timestamp is not a clock read, and must not be flagged.
    const noParam = ["const tick = () => { draw(); };", "frame = requestAnimationFrame(tick);"].join("\n");
    expect(nondeterministic("noparam.ts", noParam)).toEqual([]);
  });

  it("sees an event's own timestamp, and accepts a justification for it", () => {
    const raw = ["const onDown = (e) => { downAt = e.timeStamp; };"].join("\n");
    expect(nondeterministic("ev.ts", raw).map((h) => [h.call, h.justified])).toEqual([
      ["e.timeStamp", false],
    ]);
    const noted = ["/* determinism: click-vs-drag threshold only, never rendered. */", "const onDown = (e) => { downAt = e.timeStamp; };"].join("\n");
    expect(nondeterministic("ev2.ts", noted).map((h) => h.justified)).toEqual([true]);
    // Prose naming it is still not a read.
    expect(nondeterministic("prose2.ts", '/* e.timeStamp is a clock. */\nconst s = "e.timeStamp";')).toEqual([]);
  });

  it("the frame-timing rule fires on both values that actually escaped, and exempts their owners", () => {
    /* Liveness proven by running the REAL function over the REAL shapes. `elapsedMs` on the live
       region is the defect the previous rewrite was written after; `fps` in the status line is the
       one it could not see. An empty owner map, a typo'd field name or a silently empty walk would
       pass the tree scan above and fail here. */
    const announce = 'live.textContent = `traced in ${trace.elapsedMs} ms`;';
    expect(frameTiming("app/commands.ts", announce).map((h) => [h.read, h.justified])).toEqual([
      ["trace.elapsedMs", false],
    ]);

    const statusLine = "return <span className=\"sb__fps\">{Math.round(stats.fps)}</span>;";
    expect(frameTiming("app/StatusBar.tsx", statusLine).map((h) => [h.read, h.justified])).toEqual([
      ["stats.fps", false],
    ]);

    /* The clock-derived WORDS are the same class (critic F6, 2026-09-22): the E4 bar's flag and the
       step-down tier on the status line, flagged at StatusBar and exempt only at their owners. */
    const barLine = 'return stats.frameRateBelowBar === true ? "below frame-rate bar" : null;';
    expect(frameTiming("app/StatusBar.tsx", barLine).map((h) => [h.read, h.justified])).toEqual([
      ["stats.frameRateBelowBar", false],
    ]);
    expect(frameTiming("fabric3d/stepdown.ts", barLine)).toEqual([]);
    expect(frameTiming("app/StatusBar.tsx", "const t = `tier ${stats.quality}`;").map((h) => h.read)).toEqual(["stats.quality"]);

    // Destructuring is the same read wearing different clothes.
    expect(frameTiming("app/X.tsx", "const { fps, frameMs } = stats;").map((h) => h.read)).toEqual([
      "fps",
      "frameMs",
    ]);

    /* The owner is exempt where it is the owner, and only there. Same source text, two paths. */
    const read = "publish(stats.fps);";
    expect(frameTiming("fabric3d/telemetry.ts", read)).toEqual([]);
    expect(frameTiming("fabric3d/other.ts", read).map((h) => h.read)).toEqual(["stats.fps"]);

    /* PRODUCING the field is not reading it: `{ fps: … }` in the scene's own snapshot is a
       property assignment, and flagging it would make every owner file fail its own rule. Stated
       so the boundary of this detector is a decision rather than an accident. */
    expect(frameTiming("app/X.tsx", "return { fps: Math.round(ema) };")).toEqual([]);

    // A read at a justified site is recorded and marked justified, never silently dropped.
    const annotated = ["/* determinism: behind a disclosure no capture opens. */", "const f = stats.fps;"].join("\n");
    expect(frameTiming("app/StatusBar.tsx", annotated).map((h) => h.justified)).toEqual([true]);
  });

  it("the frame-timing rule is not exempted by an inherited object property", () => {
    /* `OWNERS["toString"]` on an object literal returns Function — truthy — which would exempt a
       field called `toString` from the rule everywhere. The Map cannot do that; asserted so the
       next person who "simplifies" it back to a literal finds out here. */
    expect(frameTiming("app/X.tsx", "const s = o.toString;")).toEqual([]);
    expect(FRAME_TIMING_OWNERS.get("toString")).toBeUndefined();
  });

  it("finds the justified calls that are actually in the tree", () => {
    // Anchors the scan to reality: if the walk silently stopped returning files, every assertion
    // above would pass on an empty set. This one cannot.
    const engine = resolve(SRC, "forwarding", "engine.ts");
    const hits = nondeterministic(engine, readFileSync(engine, "utf8"));
    expect(hits.length).toBeGreaterThanOrEqual(2);
    expect(hits.every((h) => h.justified)).toBe(true);
  });
});
