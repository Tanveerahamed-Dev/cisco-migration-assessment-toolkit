import { readFileSync, existsSync } from "node:fs";
import { dirname, resolve, relative } from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";
import { describe, expect, it } from "vitest";
import { ENGINE_PROJECTION_META, RUNTIME_SOURCE_META } from "../../vite.config";
import { EMBED_PROTOCOL } from "../../../webapp/frontend/src/projectionEmbed";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
function runtimeGraph(entry: string): Set<string> {
  const seen = new Set<string>();
  function visit(path: string): void {
    const relativePath = relative(root, path).split("\\").join("/");
    if (seen.has(relativePath)) return;
    seen.add(relativePath);
    const source = ts.createSourceFile(path, readFileSync(path, "utf8"), ts.ScriptTarget.Latest, true);
    const follow = (name: string): void => {
      if (!name.startsWith(".")) { expect(["react", "three"].some((owner) => name === owner || name.startsWith(owner + "/"))).toBe(true); return; }
      if (name.endsWith(".css")) return;
      const base = resolve(dirname(path), name);
      const file = [base, base + ".ts", base + ".tsx"].find((candidate) => existsSync(candidate));
      expect(file, name).toBeDefined(); if (file) visit(file);
    };
    function walk(node: ts.Node): void {
      if (ts.isImportDeclaration(node) && !node.importClause?.isTypeOnly && ts.isStringLiteral(node.moduleSpecifier)) follow(node.moduleSpecifier.text);
      if (ts.isExportDeclaration(node) && !node.isTypeOnly && node.moduleSpecifier && ts.isStringLiteral(node.moduleSpecifier)) follow(node.moduleSpecifier.text);
      if (ts.isCallExpression(node) && node.expression.kind === ts.SyntaxKind.ImportKeyword) {
        const argument = node.arguments[0]; expect(argument && ts.isStringLiteral(argument)).toBe(true);
        if (argument && ts.isStringLiteral(argument)) follow(argument.text);
      }
      ts.forEachChild(node, walk);
    }
    walk(source);
  }
  visit(resolve(root, entry)); return seen;
}

describe("one hub, separate engine rendering path", () => {
  it("closes the runtime adapter imports over protocol, transport and audited presentation", () => {
    const graph = runtimeGraph("atlas-scope/src/contract-mode/boot.ts");
    expect(graph.has("atlas-scope/src/fabric3d/geometry/chassis.ts")).toBe(true);
    expect(graph.has("webapp/frontend/src/projectionEmbed.ts")).toBe(true);
    const forbidden = [...graph].filter((path) => /(?:\/core\/(?:data|dataset)(?:\.|\/)|\/app\/App\.|\/mount\.|\/forwarding\/|\/analysis\/|\/fabric3d\/(?:scene|flow)\.|\/geometry\/cables\.|\/testing\.|\/test-support\/)/.test(path));
    expect(forbidden).toEqual([]);
    const boot = readFileSync(resolve(root, "atlas-scope/src/contract-mode/boot.ts"), "utf8");
    const loader = readFileSync(resolve(root, "atlas-scope/src/contract-mode/load.ts"), "utf8");
    expect(boot + loader).not.toMatch(/\/raw\b|buildCables|classifyLink|bandOfTrace|compileAll|forwarding\//);
  });
  it("keeps initial mode admission within two pure modules, with no runtime imports beyond their pair", () => {
    const admitted = ["atlas-scope/src/contract-mode/entry.ts", "webapp/frontend/src/projectionEmbed.ts"];
    expect([...runtimeGraph(admitted[0]!)].sort()).toEqual([...admitted].sort());
    const literal = (node: ts.Expression): boolean => {
      if (ts.isAsExpression(node) || ts.isParenthesizedExpression(node)) return literal(node.expression);
      return ts.isStringLiteral(node) || ts.isNumericLiteral(node) || node.kind === ts.SyntaxKind.TrueKeyword ||
        node.kind === ts.SyntaxKind.FalseKeyword || node.kind === ts.SyntaxKind.NullKeyword ||
        (ts.isArrayLiteralExpression(node) && node.elements.every(element => literal(element)));
    };
    const inert = (statement: ts.Statement): boolean => ts.isImportDeclaration(statement) || ts.isTypeAliasDeclaration(statement) ||
      ts.isFunctionDeclaration(statement) || (ts.isVariableStatement(statement) &&
        (statement.declarationList.flags & ts.NodeFlags.BlockScoped) === ts.NodeFlags.Const && statement.declarationList.declarations.every(
          declaration => ts.isIdentifier(declaration.name) && declaration.initializer !== undefined && literal(declaration.initializer)));
    for (const text of ["let value = [];", "await using value = [];", "const [value = sideEffect()] = [];", "const [value] = [];",
      "const value = sideEffect();", "sideEffect();"]) {
      const planted = ts.createSourceFile("planted.ts", text, ts.ScriptTarget.Latest, true);
      expect(inert(planted.statements[0]!), text).toBe(false);
    }
    for (const name of admitted) {
      const source = ts.createSourceFile(name, readFileSync(resolve(root, name), "utf8"), ts.ScriptTarget.Latest, true);
      for (const statement of source.statements) {
        if (ts.isImportDeclaration(statement) && !statement.importClause?.isTypeOnly) {
          expect(name).toBe(admitted[0]);
          expect(ts.isStringLiteral(statement.moduleSpecifier) && statement.moduleSpecifier.text).toBe("../../../webapp/frontend/src/projectionEmbed");
        }
        expect(inert(statement), `${name}: executable top-level statement`).toBe(true);
      }
    }
  });
  it("adds the versioned capability beside the unchanged runtime-source marker", () => {
    expect(ENGINE_PROJECTION_META).toEqual({ name: "atlas-scope-engine-projection", content: EMBED_PROTOCOL });
    expect(RUNTIME_SOURCE_META).toEqual({ name: "atlas-scope-snapshot-source", content: "assesshub-api-runtime" });
  });
});
