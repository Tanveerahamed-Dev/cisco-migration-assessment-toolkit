import * as path from "node:path";
import ts from "typescript";
import { beforeAll, describe, expect, it } from "vitest";

// Atlas Scope is a LABELLED PREVIEW (owner decision, 2026-10-09). Every AssessHub entry to Scope must carry the
// Preview qualifier from ONE place, components/ScopePreview.tsx: a link goes through ScopeEntryLink; any other entry
// (the embedded view) names a ScopePreviewTag / WithScopePreview qualifier through aria-describedby.
//
// WHAT THIS FILE DERIVES (from the TypeScript program, never from a list of names):
//   * A Scope TARGET is any string or template span (head, middle or tail; absolute or relative) naming a `scope` or
//     `scope-view` path segment: "/scope/…", "scope/…", `${origin}/scope/…`, `/api/snapshots/${id}/scope-view`.
//   * A Scope-VALUED declaration is any variable, function, hook, object property or method whose own value (its
//     initializer, or its body less the bodies of declarations nested in it) holds a Scope target or references a
//     Scope-valued declaration, through dot or bracket access and across files (imports resolve to the declaration).
//     Components (a body that renders JSX) are where entries live, not values, so they are not propagated. Values
//     also flow, to a fixed point, into: the parameters of a callback handed to a call on a Scope-valued callee
//     (`x.then(v => …)`); the state of a `useState`/`useReducer` setter called with a Scope-valued argument; and every
//     parameter of a component rendered with a Scope-valued attribute (`<Child href={scopeHref}>`).
//   * An ENTRY SITE is a JSX `a`, `area`, `iframe`, `frame`, `embed`, `object`, `Link`, `NavLink` or `Navigate` (or
//     ScopeEntryLink itself), a `navigate(…)`, `open(…)` / `window.open(…)`, `location.assign|replace(…)`,
//     `history.pushState|replaceState(…)` call, or an assignment to `location`, `location.href` or
//     `window.location[.href]`. It is a SCOPE entry when its target (href / to / src / data, a spread, or the call's
//     arguments) holds a Scope target or a Scope-valued reference.
//   * Each Scope entry is checked on its own: ScopeEntryLink is the qualified link; a raw JSX entry must carry
//     aria-describedby naming a ScopePreviewTag `id` or WithScopePreview `qualifierId` in the same file (sitting
//     inside WithScopePreview is not enough: a screen reader would not hear the label with the link); a programmatic
//     navigation to Scope is never qualified.
//
// WHAT IT DOES NOT CLAIM: data flow it does not model is not seen. That is a value smuggled through an untyped
// `any` cast to an unrelated name, a module-level mutable container written from one place and read in another (a
// ref, a store, a context), a string assembled from pieces none of which names a `scope` segment, or a navigation
// API not listed above. The negative controls below are the shapes it is proven to catch.

const FRONTEND = path.resolve(process.cwd());
const SRC = path.join(FRONTEND, "src");
const TSCONFIG = path.join(FRONTEND, "tsconfig.json");
const OWNER = path.join(SRC, "components", "ScopePreview.tsx");
const CONTROLS = path.join(SRC, "__scope_entry_controls__");

const SCOPE_TARGET = /(?:^scope(?:-view)?[/?#])|(?:\/scope(?:-view)?(?:[/?#]|$))/;
const ENTRY_TAGS: Readonly<Record<string, readonly string[]>> = {
  a: ["href"], area: ["href"], iframe: ["src"], frame: ["src"], embed: ["src"], object: ["data"],
  Link: ["to"], NavLink: ["to"], Navigate: ["to"],
};
const PROGRAMMATIC = new Set(["navigate", "open", "window.open", "location.assign", "location.replace",
  "window.location.assign", "window.location.replace", "history.pushState", "history.replaceState",
  "window.history.pushState", "window.history.replaceState"]);
const LOCATION_TARGETS = new Set(["location", "location.href", "window.location", "window.location.href",
  "document.location", "document.location.href"]);

const canonical = (file: string) => {
  const absolute = path.resolve(file);
  return ts.sys.useCaseSensitiveFileNames ? absolute : absolute.toLowerCase();
};
const inside = (file: string, dir: string) => {
  const relative = path.relative(dir, file);
  return relative !== "" && !relative.startsWith("..") && !path.isAbsolute(relative);
};

interface EntryReport { file: string; unit: string; line: number; kind: string; qualified: boolean; why: string }

function createProgram(virtual: Readonly<Record<string, string>> = {}): ts.Program {
  const read = ts.readConfigFile(TSCONFIG, ts.sys.readFile);
  if (read.error) throw new Error(ts.flattenDiagnosticMessageText(read.error.messageText, "\n"));
  const parsed = ts.parseJsonConfigFileContent(read.config, ts.sys, FRONTEND, { noEmit: true }, TSCONFIG);
  const options = { ...parsed.options, noEmit: true };
  const host = ts.createCompilerHost(options, true);
  const files = new Map(Object.entries(virtual).map(([name, text]) => [canonical(path.join(CONTROLS, name)), text]));
  const exists = host.fileExists.bind(host);
  const readFile = host.readFile.bind(host);
  const getSource = host.getSourceFile.bind(host);
  const directoryExists = host.directoryExists?.bind(host) ?? ts.sys.directoryExists;
  // Module resolution skips probing a directory it believes absent, so the virtual control directory must exist.
  host.directoryExists = (dir) => (files.size > 0 && canonical(dir) === canonical(CONTROLS)) || directoryExists(dir);
  host.fileExists = (file) => files.has(canonical(file)) || exists(file);
  host.readFile = (file) => files.get(canonical(file)) ?? readFile(file);
  host.getSourceFile = (file, version, onError, fresh) => {
    const text = files.get(canonical(file));
    return text === undefined ? getSource(file, version, onError, fresh)
      : ts.createSourceFile(file, text, version, true, file.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
  };
  const roots = [...parsed.fileNames, ...Object.keys(virtual).map((name) => path.join(CONTROLS, name))];
  return ts.createProgram({ rootNames: roots, options, host });
}

function scan(program: ts.Program): EntryReport[] {
  const checker = program.getTypeChecker();
  const sources = program.getSourceFiles().filter((s) => inside(s.fileName, SRC) && !s.isDeclarationFile);
  const marked = new Set<ts.Node>();
  let changed = true;

  const isTypeLevel = (node: ts.Node) => ts.isTypeNode(node) || ts.isInterfaceDeclaration(node)
    || ts.isTypeAliasDeclaration(node) || ts.isImportDeclaration(node) || ts.isExportDeclaration(node);
  const targetText = (node: ts.Node): boolean =>
    (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node) || ts.isTemplateHead(node)
      || ts.isTemplateMiddle(node) || ts.isTemplateTail(node)) && SCOPE_TARGET.test(node.text);
  const resolved = (symbol: ts.Symbol | undefined): ts.Symbol | undefined =>
    symbol && symbol.flags & ts.SymbolFlags.Alias ? checker.getAliasedSymbol(symbol) : symbol;
  const declarationsOf = (node: ts.Node): readonly ts.Node[] => {
    let symbol: ts.Symbol | undefined;
    if (ts.isShorthandPropertyAssignment(node)) symbol = checker.getShorthandAssignmentValueSymbol(node);
    else if (ts.isElementAccessExpression(node) && ts.isStringLiteralLike(node.argumentExpression)) {
      symbol = checker.getSymbolAtLocation(node.argumentExpression)
        ?? checker.getPropertyOfType(checker.getTypeAtLocation(node.expression), node.argumentExpression.text);
    } else if (ts.isIdentifier(node)) symbol = checker.getSymbolAtLocation(node);
    return resolved(symbol)?.declarations ?? [];
  };
  const markedRef = (node: ts.Node) => declarationsOf(node).some((d) => marked.has(d));
  const mark = (node: ts.Node) => { if (!marked.has(node)) { marked.add(node); changed = true; } };

  /** Does `node` (deeply) hold a Scope target or a Scope-valued reference? `stop` prunes nested declarations. */
  function holds(node: ts.Node, stop: (n: ts.Node) => boolean = () => false): boolean {
    let found = false;
    const visit = (n: ts.Node) => {
      if (found || isTypeLevel(n) || (n !== node && stop(n))) return;
      if (targetText(n) || ((ts.isIdentifier(n) || ts.isShorthandPropertyAssignment(n)
        || ts.isElementAccessExpression(n)) && markedRef(n))) { found = true; return; }
      ts.forEachChild(n, visit);
    };
    visit(node);
    return found;
  }
  function rendersJsx(node: ts.Node, stop: (n: ts.Node) => boolean): boolean {
    let found = false;
    const visit = (n: ts.Node) => {
      if (found || (n !== node && stop(n))) return;
      if (ts.isJsxElement(n) || ts.isJsxSelfClosingElement(n) || ts.isJsxFragment(n)) { found = true; return; }
      ts.forEachChild(n, visit);
    };
    visit(node);
    return found;
  }
  const nestedDeclaration = (n: ts.Node) => ts.isVariableDeclaration(n) || ts.isFunctionDeclaration(n)
    || ts.isPropertyAssignment(n) || ts.isShorthandPropertyAssignment(n) || ts.isMethodDeclaration(n)
    || ts.isPropertyDeclaration(n) || ts.isClassDeclaration(n) || ts.isParameter(n) || ts.isGetAccessorDeclaration(n);
  const bindingNames = (name: ts.BindingName, into: ts.Node[]) => {
    if (ts.isIdentifier(name)) return;
    for (const element of name.elements) {
      if (ts.isOmittedExpression(element)) continue;
      if (ts.isIdentifier(element.name)) into.push(element);
      else bindingNames(element.name, into);
    }
  };
  const parameterDeclarations = (fn: ts.SignatureDeclaration): ts.Node[] => {
    const out: ts.Node[] = [];
    for (const p of fn.parameters) { if (ts.isIdentifier(p.name)) out.push(p); else bindingNames(p.name, out); }
    return out;
  };
  const functionOf = (decl: ts.Node): ts.SignatureDeclaration | undefined => {
    if (ts.isFunctionDeclaration(decl) || ts.isMethodDeclaration(decl)) return decl;
    if (ts.isVariableDeclaration(decl) && decl.initializer
      && (ts.isArrowFunction(decl.initializer) || ts.isFunctionExpression(decl.initializer))) return decl.initializer;
    return undefined;
  };
  const isStateCall = (expr: ts.Expression | undefined) =>
    !!expr && ts.isCallExpression(expr) && /(?:^|\.)use(?:State|Reducer)$/.test(expr.expression.getText());

  // ---- propagate Scope-valued declarations to a fixed point ----
  while (changed) {
    changed = false;
    for (const source of sources) {
      const visit = (node: ts.Node) => {
        if (isTypeLevel(node)) return;
        // R1: a declaration whose own value holds Scope (and which is not a component).
        let region: ts.Node | undefined;
        if ((ts.isVariableDeclaration(node) || ts.isPropertyAssignment(node) || ts.isPropertyDeclaration(node))
          && node.initializer) region = node.initializer;
        else if ((ts.isFunctionDeclaration(node) || ts.isMethodDeclaration(node) || ts.isGetAccessorDeclaration(node))
          && node.body) {
          region = node.body;
        }
        if (region && !marked.has(node) && holds(region, nestedDeclaration) && !rendersJsx(region, nestedDeclaration)) {
          if (ts.isVariableDeclaration(node) && !ts.isIdentifier(node.name)) {
            const names: ts.Node[] = []; bindingNames(node.name, names); names.forEach(mark);
          }
          mark(node);
        }
        if (ts.isShorthandPropertyAssignment(node) && !marked.has(node) && markedRef(node)) mark(node);
        if (ts.isCallExpression(node)) {
          // R2: callbacks handed to a call on a Scope-valued callee receive Scope values.
          if (holds(node.expression)) {
            for (const arg of node.arguments) {
              if (ts.isArrowFunction(arg) || ts.isFunctionExpression(arg)) parameterDeclarations(arg).forEach(mark);
            }
          }
          // R3: a state setter called with a Scope value makes the state Scope-valued.
          for (const decl of declarationsOf(node.expression)) {
            const pattern = decl.parent;
            if (ts.isBindingElement(decl) && pattern && ts.isArrayBindingPattern(pattern)
              && pattern.elements.indexOf(decl) === 1 && ts.isVariableDeclaration(pattern.parent)
              && isStateCall(pattern.parent.initializer)) {
              const state = pattern.elements[0];
              if (state && ts.isBindingElement(state) && !marked.has(state) && node.arguments.some((arg) => holds(arg))) {
                mark(state);
              }
            }
          }
        }
        // R4: a component rendered with a Scope-valued attribute receives Scope values in every parameter.
        if (ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) {
          const components = declarationsOf(node.tagName).map(functionOf).filter((fn): fn is ts.SignatureDeclaration => !!fn);
          const params = components.flatMap(parameterDeclarations).filter((d) => !marked.has(d));
          if (params.length && node.attributes.properties.some((attr) => holds(attr))) params.forEach(mark);
        }
        ts.forEachChild(node, visit);
      };
      visit(source);
    }
  }

  // ---- check every entry site on its own ----
  const ownerDeclaration = (tag: ts.Node, name: string) => declarationsOf(tag).some((d) =>
    canonical(d.getSourceFile().fileName) === canonical(OWNER)
    && (ts.isFunctionDeclaration(d) || ts.isVariableDeclaration(d)) && d.name?.getText() === name);
  const attribute = (el: ts.JsxOpeningLikeElement, name: string) => el.attributes.properties.find((p): p is ts.JsxAttribute =>
    ts.isJsxAttribute(p) && p.name.getText() === name);
  const attributeExpression = (attr: ts.JsxAttribute | undefined) =>
    !attr?.initializer ? undefined : ts.isJsxExpression(attr.initializer) ? attr.initializer.expression : attr.initializer;
  const references = (node: ts.Node | undefined): Set<ts.Node> => {
    const out = new Set<ts.Node>();
    const visit = (n: ts.Node) => {
      if (ts.isIdentifier(n)) declarationsOf(n).forEach((d) => out.add(d));
      ts.forEachChild(n, visit);
    };
    if (node) visit(node);
    return out;
  };
  const unitOf = (node: ts.Node): string => {
    let top: ts.Node = node;
    while (top.parent && !ts.isSourceFile(top.parent)) top = top.parent;
    if ((ts.isFunctionDeclaration(top) || ts.isClassDeclaration(top)) && top.name) return top.name.text;
    if (ts.isVariableStatement(top)) return top.declarationList.declarations.map((d) => d.name.getText()).join(",");
    return "<module>";
  };

  const reports: EntryReport[] = [];
  for (const source of sources) {
    const file = path.relative(SRC, source.fileName).split(path.sep).join("/");
    const qualifierIds: ts.Node[] = [];
    const collect = (node: ts.Node) => {
      if (ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) {
        const id = ownerDeclaration(node.tagName, "ScopePreviewTag") ? attributeExpression(attribute(node, "id"))
          : ownerDeclaration(node.tagName, "WithScopePreview") ? attributeExpression(attribute(node, "qualifierId")) : undefined;
        if (id) qualifierIds.push(id);
      }
      ts.forEachChild(node, collect);
    };
    collect(source);
    const qualifierRefs = new Set<ts.Node>(qualifierIds.flatMap((id) => [...references(id)]));
    const describesQualifier = (expr: ts.Node | undefined) => !!expr && [...references(expr)].some((d) => qualifierRefs.has(d));

    const report = (node: ts.Node, kind: string, qualified: boolean, why: string) => reports.push({
      file, unit: unitOf(node), line: source.getLineAndCharacterOfPosition(node.getStart()).line + 1, kind, qualified, why,
    });
    const visit = (node: ts.Node) => {
      if (isTypeLevel(node)) return;
      if (ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) {
        const tag = node.tagName.getText();
        if (ownerDeclaration(node.tagName, "ScopeEntryLink")) {
          if (holds(node.attributes)) report(node, "ScopeEntryLink", true, "the qualified link");
        } else if (tag in ENTRY_TAGS) {
          const targets = [
            ...ENTRY_TAGS[tag].map((name) => attributeExpression(attribute(node, name))),
            ...node.attributes.properties.filter(ts.isJsxSpreadAttribute).map((s) => s.expression),
          ].filter((t): t is ts.Expression => !!t);
          if (targets.some((t) => holds(t))) {
            const tied = describesQualifier(attributeExpression(attribute(node, "aria-describedby")));
            report(node, `<${tag}>`, tied, tied ? "aria-describedby names a Preview qualifier"
              : "a raw Scope entry without aria-describedby naming a Preview qualifier (use ScopeEntryLink)");
          }
        }
      } else if (ts.isCallExpression(node) && PROGRAMMATIC.has(node.expression.getText().replace(/\s+/g, ""))
        && node.arguments.some((arg) => holds(arg))) {
        report(node, `${node.expression.getText()}()`, false, "a programmatic navigation to Scope carries no Preview qualifier");
      } else if (ts.isBinaryExpression(node) && node.operatorToken.kind === ts.SyntaxKind.EqualsToken
        && LOCATION_TARGETS.has(node.left.getText().replace(/\s+/g, "")) && holds(node.right)) {
        report(node, `${node.left.getText()} =`, false, "a programmatic navigation to Scope carries no Preview qualifier");
      }
      ts.forEachChild(node, visit);
    };
    visit(source);
  }
  return reports;
}

const violations = (reports: EntryReport[]) => reports.filter((r) => !r.qualified)
  .map((r) => `${r.file}::${r.unit}:${r.line} ${r.kind}: ${r.why}`);

// Negative and positive controls: real modules under a virtual directory inside src/, compiled in one program with the
// application so imports resolve to the real api, ScopePreview and react-router declarations.
const CONTROL_PREAMBLE = `import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router";
import { api } from "../api";
import { projectionEmbedUrl } from "../projectionEmbed";
import { ScopeEntryLink, ScopePreviewTag, WithScopePreview } from "../components/ScopePreview";
void useEffect; void useState; void Link; void useNavigate; void api; void projectionEmbedUrl;
void ScopeEntryLink; void ScopePreviewTag; void WithScopePreview;
`;
const BAD: Readonly<Record<string, string>> = {
  "scopeRoot.ts": `export const SCOPE_ROOT = "/scope/snapshots/";\n`,
  "badModuleConst.tsx": `${CONTROL_PREAMBLE}import { SCOPE_ROOT } from "./scopeRoot";
export function ModuleConst({ sid }: { sid: number }) { return <a href={\`\${SCOPE_ROOT}\${sid}/\`}>3-D</a>; }\n`,
  "badHelper.tsx": `${CONTROL_PREAMBLE}function scopeHref(sid: number) { return \`/scope/snapshots/\${sid}/\`; }
export function Helper({ sid }: { sid: number }) { return <a href={scopeHref(sid)}>3-D</a>; }\n`,
  "badOrigin.tsx": `${CONTROL_PREAMBLE}export function Origin({ sid }: { sid: number }) {
  return <a href={\`\${window.location.origin}/scope/snapshots/\${sid}/\`}>3-D</a>; }\n`,
  "badRelative.tsx": `${CONTROL_PREAMBLE}export function Relative({ sid }: { sid: number }) { return <a href={"scope/snapshots/" + sid}>3-D</a>; }\n`,
  "badHookOpen.tsx": `${CONTROL_PREAMBLE}export function useOpenScope() { return (sid: number) => window.open(\`/scope/snapshots/\${sid}/\`); }\n`,
  "badFetch.tsx": `${CONTROL_PREAMBLE}export function Fetched({ sid }: { sid: number }) {
  const [h, setH] = useState("");
  useEffect(() => { fetch(\`/api/snapshots/\${sid}/scope-view\`).then((r) => r.json()).then((v) => setH(v.href)); }, [sid]);
  return <a href={h}>3-D</a>; }\n`,
  "badBracket.tsx": `${CONTROL_PREAMBLE}export function Bracket({ sid }: { sid: number }) {
  const [h, setH] = useState<string | null>(null);
  useEffect(() => { api["scopeView"](sid).then((v) => setH(v.href ?? null)); }, [sid]);
  return h ? <a href={h}>3-D</a> : null; }\n`,
  "badHookReturn.tsx": `${CONTROL_PREAMBLE}function useScopeHref(sid: number) {
  const [h, setH] = useState<string | null>(null);
  useEffect(() => { api.scopeView(sid).then((v) => setH(v.href ?? null)); }, [sid]);
  return h; }
export function HookReturn({ sid }: { sid: number }) { const h = useScopeHref(sid); return h ? <Link to={h}>3-D</Link> : null; }\n`,
  "badWindowOpenBeside.tsx": `${CONTROL_PREAMBLE}export function Both({ sid }: { sid: number }) {
  const [href, setHref] = useState<string | null>(null);
  useEffect(() => { api.scopeView(sid).then((v) => setHref(v.href ?? null)); }, [sid]);
  return href ? <><ScopeEntryLink href={href}>Open in Atlas Scope</ScopeEntryLink>
    <button onClick={() => window.open(href)}>Pop out</button></> : null; }\n`,
  "badLinkInWrapper.tsx": `${CONTROL_PREAMBLE}export function Wrapped({ sid }: { sid: number }) {
  const [href, setHref] = useState<string | null>(null);
  useEffect(() => { api.scopeView(sid).then((v) => setHref(v.href ?? null)); }, [sid]);
  return href ? <WithScopePreview><Link to={href}>3-D</Link></WithScopePreview> : null; }\n`,
  "badChild.tsx": `${CONTROL_PREAMBLE}function Child({ to }: { to: string }) { return <a href={to}>3-D</a>; }
export function Parent({ sid }: { sid: number }) {
  const [href, setHref] = useState<string | null>(null);
  useEffect(() => { api.scopeView(sid).then((v) => setHref(v.href ?? null)); }, [sid]);
  return href ? <Child to={href} /> : null; }\n`,
  "badNavigate.tsx": `${CONTROL_PREAMBLE}export function Go({ sid }: { sid: number }) {
  const navigate = useNavigate();
  return <button onClick={() => navigate(\`/scope/snapshots/\${sid}/\`)}>3-D</button>; }\n`,
  "badEmbed.tsx": `${CONTROL_PREAMBLE}export function Embed({ href }: { href: string }) {
  const src = projectionEmbedUrl(href, 1, "n", window.location.origin);
  return <WithScopePreview><iframe src={src ?? undefined} title="Scope" /></WithScopePreview>; }\n`,
};
const BAD_FILES = Object.keys(BAD).filter((name) => name !== "scopeRoot.ts");
const GOOD: Readonly<Record<string, string>> = {
  "good.tsx": `${CONTROL_PREAMBLE}import { useId } from "react";
export function Ok({ sid }: { sid: number }) {
  const [href, setHref] = useState<string | null>(null);
  useEffect(() => { api.scopeView(sid).then((v) => setHref(v.href ?? null)); }, [sid]);
  return href ? <ScopeEntryLink href={href}>Open in Atlas Scope</ScopeEntryLink> : null; }
export function Embedded({ href }: { href: string }) {
  const q = useId();
  const src = projectionEmbedUrl(href, 1, "n", window.location.origin);
  return <WithScopePreview qualifierId={q}><h2 aria-describedby={q}>3-D</h2><iframe src={src ?? undefined} title="Scope" aria-describedby={q} /></WithScopePreview>; }
export function Unrelated() { const navigate = useNavigate(); return <><a href="/campaigns/1">Campaign</a><button onClick={() => navigate("/campaigns")}>Back</button></>; }\n`,
};

describe("every AssessHub entry to Atlas Scope carries the Preview qualifier (derived from source, not a list)", () => {
  let real: EntryReport[];
  let controls: EntryReport[];
  beforeAll(() => {
    real = scan(createProgram());
    controls = scan(createProgram({ ...BAD, ...GOOD }));
  }, 120_000);

  it("finds the real Scope entries (positive control: an empty discovery would pass vacuously)", () => {
    const found = real.map((r) => `${r.file}::${r.unit} ${r.kind}`);
    for (const known of [
      "pages/CoreSnapshot.tsx::ScopeLink ScopeEntryLink",
      "pages/Snapshot.tsx::AtlasScopeLink ScopeEntryLink",
      "pages/core/TopologyScope.tsx::TopologyScope <iframe>",
      "components/ScopePreview.tsx::ScopeEntryLink <a>",
    ]) {
      expect(found, `the derivation no longer finds ${known}`).toContain(known);
    }
  });

  it("every real Scope entry is qualified", () => {
    expect(violations(real)).toEqual([]);
  });

  it("negative controls: each unlabeled shape is refused, in its own file", () => {
    const flagged = new Set(controls.filter((r) => !r.qualified && r.file.startsWith("__scope_entry_controls__/"))
      .map((r) => r.file.slice("__scope_entry_controls__/".length)));
    for (const name of BAD_FILES) expect(flagged.has(name), `${name} must be refused`).toBe(true);
  });

  it("positive controls: a ScopeEntryLink, a described embed and unrelated links pass", () => {
    const good = controls.filter((r) => r.file === "__scope_entry_controls__/good.tsx");
    expect(good.filter((r) => !r.qualified)).toEqual([]);
    expect(good.map((r) => r.kind).sort()).toEqual(["<iframe>", "ScopeEntryLink"]);
  });
});
