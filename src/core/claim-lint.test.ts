/**
 * claim-lint.test.ts — the mechanical enforcement behind design-brief.md §6.2.
 *
 * The brief's position, which this file exists to make true: "Honesty that depends on author
 * discipline is not honesty; it is a hope." Six agents wrote UI code in parallel; nobody read all
 * of it. This gate reads all of it, every run.
 *
 * It scans the user-visible string literals in every source file and fails if any of them ASSERTS a
 * forbidden word about network state. It deliberately reuses `forbiddenWordsIn` from claims.ts
 * rather than reimplementing the rule, so the gate and the runtime treatment can never drift apart.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import ts from "typescript";
import { dirname, extname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { FORBIDDEN_CLAIM_WORDS, forbiddenWordsIn } from "./claims";

// fileURLToPath, not URL.pathname: on Windows the latter yields "/C:/..." which path.join mangles.
const SRC = resolve(dirname(fileURLToPath(import.meta.url)), "..");

/**
 * What this gate does NOT scan, and why each exclusion is principled rather than convenient:
 *
 *  - `claims.ts` defines the forbidden list; it necessarily contains every word in it.
 *  - `*.test.ts(x)` are not surfaces. A test NAMED "still qualifies the claim: delivery is proven
 *    only over what was collected" is describing the honesty requirement, not asserting it to a
 *    user. Scanning test names would push authors to name tests badly to satisfy a gate.
 *
 * The exclusion is by FILE ROLE, not by a hand-maintained list of filenames that happened to fail —
 * widening a gate until it goes green is how a gate stops being one.
 */
const EXEMPT = [/claims\.ts$/, /\.test\.tsx?$/];

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) {
      if (name === "node_modules" || name === "data") continue;
      walk(p, out);
    } else if ([".ts", ".tsx"].includes(extname(p))) {
      out.push(p);
    }
  }
  return out;
}

/**
 * Extract the string literals a user could actually see, using TypeScript's own parser.
 *
 * Two hand-written extractors preceded this one and each shipped a false positive on its first
 * real run against the codebase:
 *   - a regex-based version matched prose inside block comments, including a comment arguing FOR
 *     this very doctrine;
 *   - a character scanner then desynchronised on a regex literal containing a quote character
 *     (`/["']/`), swallowed the following code as if it were a string, and reported a variable
 *     name as an overclaim.
 *
 * Both failures were the same mistake: approximating a parser. TypeScript is already a dependency
 * of this project, so the real parser is available and costs nothing. It knows exactly what is a
 * string, what is a comment, what is a regex and what is JSX text — and a gate that cries wolf is
 * a gate people learn to ignore, which is worse than not having one.
 */
interface Extraction {
  strings: string[];
  /** Non-null when the file could not be parsed. A file we could not read is NOT a clean file. */
  parseError: string | null;
}

function userVisibleStrings(source: string, fileName: string): Extraction {
  /* ScriptKind must follow the EXTENSION. Parsing a `.ts` file as TSX makes the parser read a
     generic type parameter — `const groupBy = <T>(items: readonly T[]) => …` — as an unclosed JSX
     tag, which is exactly the ambiguity the two extensions exist to resolve. Getting this wrong
     made three real modules unparseable and, before the unscanned-is-not-clean guard existed,
     would have silently removed them from this gate's coverage. */
  const kind = fileName.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS;
  const sf = ts.createSourceFile(fileName, source, ts.ScriptTarget.ES2023, true, kind);

  /* A syntactically broken file makes the parser's error recovery reinterpret code as string
     content, which yields nonsense findings like a variable name flagged as an overclaim. That
     happens for real here: several agents write to this tree concurrently, so a file can be
     mid-save when the suite runs. Reporting such a file as UNSCANNED is correct; reporting its
     garbage as findings would train people to ignore the gate, and reporting it as clean would be
     the very absence-as-health failure this whole product is built to prevent. */
  const diags = (sf as unknown as { parseDiagnostics?: readonly ts.Diagnostic[] }).parseDiagnostics;
  if (diags && diags.length > 0) {
    const first = diags[0]!;
    const { line } = sf.getLineAndCharacterOfPosition(first.start ?? 0);
    return {
      strings: [],
      parseError: `line ${line + 1}: ${ts.flattenDiagnosticMessageText(first.messageText, " ")}`,
    };
  }

  const out: string[] = [];
  const visit = (node: ts.Node): void => {
    if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) {
      // An import/export specifier is a module path, not prose.
      const p = node.parent;
      const isModulePath =
        (ts.isImportDeclaration(p) && p.moduleSpecifier === node) ||
        (ts.isExportDeclaration(p) && p.moduleSpecifier === node);
      if (!isModulePath) out.push(node.text);
    } else if (ts.isTemplateExpression(node)) {
      /* Join the literal spans into ONE string with a placeholder where each ${...} sat.
         Emitting the spans separately splits a sentence: the engine legitimately writes
         `${n} of ${m} hosts ... so nothing can be proven about them`, whose final span is
         " can be proven about them" — the negation lives in an earlier span, and a gate that
         reads the spans independently sees an assertion where there is a disclaimer. */
      let joined = node.head.text;
      for (const span of node.templateSpans) joined += ` <expr> ${span.literal.text}`;
      out.push(joined);
    } else if (ts.isJsxText(node)) {
      out.push(node.text);
    }
    ts.forEachChild(node, visit);
  };
  visit(sf);
  return { strings: out.filter((s) => s.trim().length > 0), parseError: null };
}

/** Import specifiers are module paths, not prose. */
const isImportPath = (s: string): boolean => /^[.@\w/-]+$/.test(s) && !/\s/.test(s);

describe("no surface asserts a forbidden claim word", () => {
  const files = walk(SRC).filter((f) => !EXEMPT.some((re) => re.test(f)));

  it("finds source files to scan — an empty scan is not a pass", () => {
    // Without this, a broken walk() would make the gate green by having nothing to check: the
    // never-executed-gate failure mode this repository has been bitten by repeatedly.
    expect(files.length).toBeGreaterThan(5);
  });

  it("scans every source file and reports the file and the word", () => {
    const violations: string[] = [];
    const unscanned: string[] = [];
    for (const file of files) {
      const src = readFileSync(file, "utf8");
      const { strings, parseError } = userVisibleStrings(src, file);
      if (parseError !== null) {
        unscanned.push(`${relative(SRC, file)} — ${parseError}`);
        continue;
      }
      for (const s of strings) {
        if (isImportPath(s)) continue;
        const hits = forbiddenWordsIn(s);
        if (hits.length > 0) {
          violations.push(`${relative(SRC, file)}: ${hits.join(", ")} — in ${JSON.stringify(s.slice(0, 120))}`);
        }
      }
    }
    // An unscanned file is not a clean file. Fail loudly with WHICH files, so a syntax error can
    // never quietly shrink this gate's coverage to nothing.
    expect(unscanned, `these files could not be parsed, so they were NOT checked:\n${unscanned.join("\n")}`).toEqual([]);
    expect(violations, `forbidden claim words asserted in UI strings:\n${violations.join("\n")}`).toEqual([]);
  });

  it("a file it cannot parse is reported, never treated as clean", () => {
    /* This branch decides whether a syntax error silently shrinks the gate's coverage to nothing.
       It has to be exercised deliberately: an unexecuted failure path is not a failure path, and
       this repository has been bitten by that exact shape more than once. */
    const broken = 'const label = "the path is healthy"; function ( {';
    const res = userVisibleStrings(broken, "broken.ts");
    expect(res.parseError, "a malformed file must report a parse error").not.toBeNull();
    expect(res.strings, "a file that failed to parse must yield NO findings").toEqual([]);

    // And the well-formed equivalent IS scanned and IS caught, so the guard is not just suppressing.
    const ok = userVisibleStrings('const label = "the path is healthy";', "ok.ts");
    expect(ok.parseError).toBeNull();
    expect(ok.strings.flatMap(forbiddenWordsIn)).toContain("healthy");
  });

  it("a generic in a .ts file parses — the extension picks the ScriptKind", () => {
    // Parsed as TSX, `<T>` reads as an unclosed JSX tag and the whole module becomes unscannable.
    const generic = "const groupBy = <T>(xs: readonly T[]) => xs;\nconst s = \"the link is healthy\";";
    const asTs = userVisibleStrings(generic, "x.ts");
    expect(asTs.parseError).toBeNull();
    expect(asTs.strings.flatMap(forbiddenWordsIn)).toContain("healthy");
  });

  it("a template literal is judged as one sentence, not as disconnected spans", () => {
    /* The engine writes caveats as template literals. Split into spans, the final span of
       `...so nothing can be proven about them` is " can be proven about them" — an assertion with
       its negation in a different span. Joined, it reads as the disclaimer it is. */
    const src = "const c = `Forwarding is modelled for ${n} of ${m} hosts, so nothing can be proven about the rest.`;";
    const res = userVisibleStrings(src, "c.ts");
    expect(res.parseError).toBeNull();
    expect(res.strings).toHaveLength(1);
    expect(res.strings[0]).toContain("nothing can be proven");
    expect(res.strings.flatMap(forbiddenWordsIn)).toEqual([]);
  });

  it("the gate is live — it catches a planted violation", () => {
    // Proves the detector actually fires. A gate whose success path was never executed is not a gate.
    const planted = "the fabric is healthy and all traffic is safe";
    const hits = forbiddenWordsIn(planted);
    expect(hits).toContain("healthy");
    expect(hits).toContain("safe");
    expect(FORBIDDEN_CLAIM_WORDS.length).toBeGreaterThan(5);
  });

  it("the extractor reads strings and ignores comments — proven on a planted sample", () => {
    /* The two false positives this gate produced on its first real run both came from prose inside
       block comments. This pins the fix: a forbidden word in a comment is invisible to the gate, the
       same word in a string is caught, and an apostrophe in a comment does not desynchronise the
       scanner (which is what broke the regex version). */
    const sample = [
      "// this link is safe to cut",
      "/* the curve's apex is healthy, and all traffic is fine */",
      'const label = "this link is safe to cut";',
      'import x from "./safe/thing";',
      "const url = \"https://example.test/a//b\";",
      "const t = `status: ${healthy ? 'a' : 'b'} and the path is healthy`;",
    ].join("\n");

    const { strings, parseError } = userVisibleStrings(sample, "sample.tsx");
    expect(parseError).toBeNull();
    expect(strings).toContain("this link is safe to cut");
    expect(strings.some((s) => s.includes("curve's apex"))).toBe(false);
    expect(strings).toContain("https://example.test/a//b");

    const flagged = strings.filter((s) => !isImportPath(s)).flatMap(forbiddenWordsIn);
    expect(flagged).toContain("safe"); // from the string literal
    expect(flagged).toContain("healthy"); // from the template literal's text, not its expression
    expect(flagged.filter((w) => w === "safe")).toHaveLength(1); // NOT also from the comment or the import
  });
});
