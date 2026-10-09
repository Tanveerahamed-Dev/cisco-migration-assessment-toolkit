import { readdirSync, readFileSync, statSync } from "node:fs";
import * as path from "node:path";
import ts from "typescript";
import { describe, expect, it } from "vitest";

// Atlas Scope is a LABELLED PREVIEW (owner decision, 2026-10-09). Every AssessHub entry to Scope must carry the
// Preview qualifier, and the qualifier lives in ONE place: components/ScopePreview.tsx (ScopeEntryLink for a link,
// WithScopePreview for any other entry). This file derives the class of Scope entries from the source instead of
// naming them: a top-level unit (function, const, class) that consumes the Scope capability (any reference to
// `scopeView` or `projectionEmbedUrl` that is not their own definition) or that renders JSX beside a "/scope"
// target literal is an entry, and it must render ScopeEntryLink or WithScopePreview and no raw <a>. A new entry
// that links to Scope any other way fails here, whatever it is called and wherever it lives.

// npm scripts and Vitest both set cwd to this package (see designSyncProps.test.ts for the same choice).
const SRC = path.resolve(process.cwd(), "src");
const QUALIFIERS = new Set(["ScopeEntryLink", "WithScopePreview"]);
const CAPABILITY = new Set(["scopeView", "projectionEmbedUrl"]);
const SCOPE_TARGET = /^\/scope(?:\/|\?|$)/;

interface UnitReport { unit: string; consumer: boolean; qualifiers: number; anchors: number }

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const p = path.join(dir, name);
    return statSync(p).isDirectory() ? walk(p) : [p];
  });
}

/** The application source the guard reads: every .ts/.tsx under src/ except tests, test support and generated types. */
function sourceFiles(): string[] {
  return walk(SRC)
    .filter((p) => /\.tsx?$/.test(p) && !/\.test\.tsx?$/.test(p))
    .filter((p) => {
      const parts = path.relative(SRC, p).split(path.sep);
      return parts[0] !== "test" && parts[0] !== "generated";
    })
    .sort();
}

/** The name an identifier DECLARES (not a reference): a function, property, method, variable or parameter name. */
function isDeclarationName(node: ts.Identifier): boolean {
  const parent = node.parent;
  return (ts.isFunctionDeclaration(parent) || ts.isPropertyAssignment(parent) || ts.isMethodDeclaration(parent)
    || ts.isPropertySignature(parent) || ts.isVariableDeclaration(parent) || ts.isParameter(parent)
    || ts.isImportSpecifier(parent) || ts.isExportSpecifier(parent)) && (parent as { name?: ts.Node }).name === node;
}

function jsxTagName(node: ts.Node): string | null {
  if (ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) return node.tagName.getText();
  return null;
}

function unitName(statement: ts.Statement): string {
  if ((ts.isFunctionDeclaration(statement) || ts.isClassDeclaration(statement)) && statement.name) return statement.name.text;
  if (ts.isVariableStatement(statement)) {
    return statement.declarationList.declarations.map((d) => d.name.getText()).join(",");
  }
  return "<module>";
}

/** One report per top-level unit of one source text. Exported shape is test-local: the controls below feed it too. */
function scanSource(fileName: string, text: string): UnitReport[] {
  const kind = fileName.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS;
  const source = ts.createSourceFile(fileName, text, ts.ScriptTarget.Latest, true, kind);
  const reports: UnitReport[] = [];
  for (const statement of source.statements) {
    // Imports, re-exports and type-only declarations cannot render or call anything.
    if (ts.isImportDeclaration(statement) || ts.isExportDeclaration(statement) || ts.isInterfaceDeclaration(statement)
      || ts.isTypeAliasDeclaration(statement)) continue;
    let capability = false, literal = false, jsx = false, qualifiers = 0, anchors = 0;
    const visit = (node: ts.Node) => {
      if (ts.isIdentifier(node) && CAPABILITY.has(node.text) && !isDeclarationName(node)) capability = true;
      if ((ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node) || ts.isTemplateHead(node))
        && SCOPE_TARGET.test(node.text)) literal = true;
      if (ts.isJsxElement(node) || ts.isJsxSelfClosingElement(node) || ts.isJsxFragment(node)) jsx = true;
      const tag = jsxTagName(node);
      if (tag !== null && QUALIFIERS.has(tag)) qualifiers += 1;
      if (tag === "a") anchors += 1;
      ts.forEachChild(node, visit);
    };
    visit(statement);
    reports.push({ unit: unitName(statement), consumer: capability || (jsx && literal), qualifiers, anchors });
  }
  return reports;
}

function violations(reports: UnitReport[]): string[] {
  return reports.filter((r) => r.consumer && (r.qualifiers === 0 || r.anchors > 0)).map((r) =>
    `${r.unit}: ${r.qualifiers === 0 ? "renders no ScopeEntryLink/WithScopePreview" : `renders ${r.anchors} raw <a>`}`);
}

describe("every AssessHub entry to Atlas Scope carries the Preview qualifier (derived from source, not a list)", () => {
  const scanned = sourceFiles().map((file) => ({ file: path.relative(SRC, file).split(path.sep).join("/"),
    reports: scanSource(file, readFileSync(file, "utf8")) }));
  const consumers = scanned.flatMap(({ file, reports }) => reports.filter((r) => r.consumer).map((r) => `${file}::${r.unit}`));

  it("finds the class at all (positive control: an empty discovery would pass vacuously)", () => {
    expect(scanned.length).toBeGreaterThan(20);
    // The entries that exist today must be found by the derivation, not because they are named here.
    for (const known of ["pages/CoreSnapshot.tsx::ScopeLink", "pages/Snapshot.tsx::AtlasScopeLink",
      "pages/core/TopologyScope.tsx::TopologyScope"]) {
      expect(consumers, `the derivation no longer finds ${known}`).toContain(known);
    }
  });

  it("every Scope consumer renders its entry through ScopeEntryLink or WithScopePreview, and no raw <a>", () => {
    const found = scanned.flatMap(({ file, reports }) => violations(reports).map((v) => `${file}::${v}`));
    expect(found).toEqual([]);
  });

  it("the owner and the capability definitions are not consumers (their own names are declarations)", () => {
    const owner = scanned.find(({ file }) => file === "components/ScopePreview.tsx");
    expect(owner?.reports.some((r) => r.consumer)).toBe(false);
    expect(consumers.filter((c) => c.startsWith("api.ts::") || c.startsWith("projectionEmbed.ts::"))).toEqual([]);
  });

  it("negative controls: a new unlabeled entry fails, in each shape the guard claims to catch", () => {
    const bad = {
      capabilityLink: `export function NewEntry({ id }: { id: number }) {
        const [href, setHref] = useState<string | null>(null);
        useEffect(() => { api.scopeView(id).then((v) => setHref(v.href)); }, [id]);
        return href ? <a className="btn" href={href}>Open in Atlas Scope</a> : null;
      }`,
      literalLink: `export const Shortcut = () => <a href="/scope/snapshots/1/">3-D view</a>;`,
      templateLink: "export function T({ sid }: { sid: number }) { return <a href={`/scope/snapshots/${sid}/`}>Scope</a>; }",
      embedFrame: `export function Embed({ href }: { href: string }) {
        const src = projectionEmbedUrl(href, 1, "n", window.location.origin);
        return <iframe src={src ?? undefined} title="Scope" />;
      }`,
      wrappedRawAnchor: `export function Mixed({ href }: { href: string }) {
        void api.scopeView(1);
        return <WithScopePreview><a href={href}>Open</a></WithScopePreview>;
      }`,
    };
    for (const [shape, text] of Object.entries(bad)) {
      expect(violations(scanSource(`${shape}.tsx`, text)), `${shape} must be refused`).toHaveLength(1);
    }
    const good = `export function Ok({ href }: { href: string }) {
      void api.scopeView(1);
      return <ScopeEntryLink href={href}>Open in Atlas Scope</ScopeEntryLink>;
    }
    export function Heading() { return <WithScopePreview><h2>3-D investigation</h2></WithScopePreview>; }
    export function Unrelated() { return <a href="/campaigns/1">Campaign</a>; }`;
    expect(violations(scanSource("good.tsx", good))).toEqual([]);
  });
});
