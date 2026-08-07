/**
 * Offline TypeScript-family syntax adapter.
 *
 * Input is one JSON object on stdin. Repository sources are supplied as text;
 * this process never resolves an import, evaluates source, or reads a project
 * tsconfig. Output is canonical enough for the Python compiler to re-sort and
 * hash before publication.
 */

import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import ts from "typescript";

const SUPPORTED = new Map([
  [".ts", ts.ScriptKind.TS],
  [".mts", ts.ScriptKind.TS],
  [".cts", ts.ScriptKind.TS],
  [".tsx", ts.ScriptKind.TSX],
  [".js", ts.ScriptKind.JS],
  [".mjs", ts.ScriptKind.JS],
  [".cjs", ts.ScriptKind.JS],
  [".jsx", ts.ScriptKind.JSX],
]);

function compareText(left, right) {
  return left < right ? -1 : left > right ? 1 : 0;
}

function sha256(value) {
  return createHash("sha256").update(value, "utf8").digest("hex");
}

function stableId(kind, ...parts) {
  return `urn:atlas:${kind}:${sha256(parts.map(String).join("\x1f")).slice(0, 24)}`;
}

function normalizePath(value) {
  const original = String(value ?? "");
  const path = original.replaceAll("\\", "/");
  const parts = path.split("/");
  if (
    !path ||
    path.startsWith("/") ||
    /^[A-Za-z]:/.test(path) ||
    parts.some((part) => part === "" || part === "." || part === "..")
  ) {
    throw new Error(`PATH_OUTSIDE_ROOT ${original}`);
  }
  return path;
}

function extensionFor(path) {
  const lower = path.toLowerCase();
  for (const extension of [".tsx", ".jsx", ".mts", ".cts", ".mjs", ".cjs", ".ts", ".js"]) {
    if (lower.endsWith(extension)) return extension;
  }
  return "";
}

function flattenMessage(message) {
  return ts.flattenDiagnosticMessageText(message, " ").replace(/\s+/g, " ").trim();
}

function rangeFor(sourceFile, node) {
  const start = node.getStart(sourceFile, false);
  const end = node.getEnd();
  const from = sourceFile.getLineAndCharacterOfPosition(start);
  const to = sourceFile.getLineAndCharacterOfPosition(end);
  return {
    start_line: from.line + 1,
    start_column: from.character,
    end_line: to.line + 1,
    end_column: to.character,
  };
}

function nodeText(sourceFile, node, limit = 500) {
  const value = node.getText(sourceFile).replace(/\s+/g, " ").trim();
  return value.length <= limit ? value : `${value.slice(0, limit - 1)}…`;
}

function modifierOn(node, kind) {
  return Boolean(node.modifiers?.some((modifier) => modifier.kind === kind));
}

function isExported(node) {
  let current = node;
  while (current && !ts.isSourceFile(current)) {
    if (
      modifierOn(current, ts.SyntaxKind.ExportKeyword) ||
      modifierOn(current, ts.SyntaxKind.DefaultKeyword)
    ) {
      return true;
    }
    if (ts.isVariableStatement(current) || ts.isClassDeclaration(current) || ts.isFunctionDeclaration(current)) {
      break;
    }
    current = current.parent;
  }
  return false;
}

function symbolDescriptor(node) {
  if (ts.isFunctionDeclaration(node)) return [node.name?.text ?? "default", "function"];
  if (ts.isClassDeclaration(node)) return [node.name?.text ?? "default", "class"];
  if (ts.isInterfaceDeclaration(node)) return [node.name.text, "interface"];
  if (ts.isTypeAliasDeclaration(node)) return [node.name.text, "type_alias"];
  if (ts.isEnumDeclaration(node)) return [node.name.text, "enum"];
  if (ts.isModuleDeclaration(node)) return [node.name.getText(), "module"];
  if (ts.isMethodDeclaration(node)) return [node.name.getText(), "method"];
  if (ts.isConstructorDeclaration(node)) return ["constructor", "constructor"];
  if (ts.isGetAccessorDeclaration(node)) return [node.name.getText(), "getter"];
  if (ts.isSetAccessorDeclaration(node)) return [node.name.getText(), "setter"];
  if (
    ts.isVariableDeclaration(node) &&
    ts.isIdentifier(node.name) &&
    node.initializer &&
    (ts.isArrowFunction(node.initializer) || ts.isFunctionExpression(node.initializer))
  ) {
    return [node.name.text, "function_variable"];
  }
  if (
    ts.isVariableDeclaration(node) &&
    ts.isIdentifier(node.name) &&
    ts.isVariableDeclarationList(node.parent) &&
    Boolean(node.parent.flags & ts.NodeFlags.Const)
  ) {
    return [node.name.text, "constant"];
  }
  return null;
}

function bindingIdentifiers(name) {
  if (ts.isIdentifier(name)) return [name.text];
  if (ts.isObjectBindingPattern(name) || ts.isArrayBindingPattern(name)) {
    const names = [];
    for (const element of name.elements) {
      if (ts.isOmittedExpression(element)) continue;
      names.push(...bindingIdentifiers(element.name));
    }
    return names;
  }
  return [];
}

function symbolDescriptors(node) {
  const descriptor = symbolDescriptor(node);
  if (descriptor) return [descriptor];
  if (
    ts.isVariableDeclaration(node) &&
    ts.isVariableDeclarationList(node.parent) &&
    Boolean(node.parent.flags & ts.NodeFlags.Const)
  ) {
    return bindingIdentifiers(node.name).map((name) => [name, "constant"]);
  }
  return [];
}

function parametersFor(sourceFile, node) {
  if (!("parameters" in node) || !node.parameters) return [];
  return [...node.parameters].map((parameter) => ({
    name: parameter.name.getText(sourceFile),
    kind: parameter.dotDotDotToken ? "variadic" : parameter.questionToken ? "optional" : "parameter",
    annotation: parameter.type ? nodeText(sourceFile, parameter.type, 500) : null,
  }));
}

function literalText(node) {
  if (node && (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node))) return node.text;
  return null;
}

function assertionRecordsFor(sourceFile, node) {
  const assertions = [];
  function visit(candidate) {
    if (ts.isCallExpression(candidate)) {
      const callee = nodeText(sourceFile, candidate.expression);
      if (
        /(?:^|\.)(?:assert|assertEquals|assertStrictEquals|should)(?:\.|$)/.test(callee) ||
        /\.(?:toBe|toEqual|toMatch|toThrow|toContain|toHaveBeenCalled)(?:\.|$)/.test(callee)
      ) {
        assertions.push({
          kind: `assertion_call:${callee}`,
          range: rangeFor(sourceFile, candidate),
          digest: sha256(sourceFile.text.slice(candidate.getStart(sourceFile, false), candidate.getEnd())),
        });
      }
    }
    ts.forEachChild(candidate, visit);
  }
  ts.forEachChild(node, visit);
  assertions.sort((left, right) => {
    const line = left.range.start_line - right.range.start_line;
    if (line !== 0) return line;
    const column = left.range.start_column - right.range.start_column;
    return column !== 0 ? column : compareText(left.kind, right.kind);
  });
  return assertions;
}

function extractFile(sourceFile, input) {
  const path = input.path;
  const fileId = input.file_id;
  const language = [".tsx"].includes(extensionFor(path))
    ? "tsx"
    : [".jsx"].includes(extensionFor(path))
      ? "jsx"
      : [".ts", ".mts", ".cts"].includes(extensionFor(path))
        ? "typescript"
        : "javascript";
  const result = {
    parser: "typescript_compiler_api",
    parser_mode: "syntax_ast",
    compiler_version: ts.version,
    line_context: {},
    symbols: [],
    imports: [],
    calls: [],
    markdown: [],
    structured: [],
    routes: [],
    components: [],
    tests: [],
    workflows: [],
    dependencies: [],
    unresolved_reasons: ["syntax_only_no_type_or_module_resolution"],
  };
  const symbolNodes = new Map();

  function walk(node, stack) {
    const descriptors = symbolDescriptors(node);
    let nextStack = stack;
    for (const [descriptorIndex, descriptor] of descriptors.entries()) {
      const [name, kind] = descriptor;
      const qualifiedName = [...stack, name].join(".");
      const location = rangeFor(sourceFile, node);
      const exported = isExported(node);
      const record = {
        id: stableId("symbol", path, qualifiedName, kind, node.getStart(sourceFile), node.getEnd()),
        file_id: fileId,
        path,
        name,
        qualified_name: qualifiedName,
        kind,
        language,
        depth: stack.length,
        range: location,
        decorators: [],
        documentation: "",
        parameters: parametersFor(sourceFile, node),
        return_annotation: "type" in node && node.type ? nodeText(sourceFile, node.type, 500) : null,
        exported,
        digest: sha256(sourceFile.text.slice(node.getStart(sourceFile, false), node.getEnd())),
        entity_type:
          ts.isVariableDeclaration(node) &&
          ts.isVariableDeclarationList(node.parent) &&
          Boolean(node.parent.flags & ts.NodeFlags.Const)
            ? "typescript_constant"
            : `${language}_${kind}`,
        declaration_kind:
          ts.isVariableDeclaration(node) && ts.isVariableDeclarationList(node.parent)
            ? Boolean(node.parent.flags & ts.NodeFlags.Const)
              ? "const"
              : Boolean(node.parent.flags & ts.NodeFlags.Let)
                ? "let"
                : "var"
            : null,
        extraction_disposition: "syntax_ast_structurally_extracted",
        unresolved_reasons: ["syntax_only_no_type_or_module_resolution"],
      };
      result.symbols.push(record);
      if (descriptorIndex === 0) {
        symbolNodes.set(node, qualifiedName);
        nextStack = [...stack, name];
      }
      if (
        /^[A-Z][A-Za-z0-9]*$/.test(name) &&
        ["tsx", "jsx"].includes(language) &&
        ["function", "class", "function_variable"].includes(kind)
      ) {
        result.components.push({
          id: stableId("component", path, qualifiedName, node.getStart(sourceFile), node.getEnd()),
          file_id: fileId,
          path,
          name: qualifiedName,
          kind,
          exported,
          range: location,
          detection: "pascal_case_symbol_in_jsx_capable_file",
          entity_type: "jsx_component_symbol",
          extraction_disposition: "syntax_ast_structurally_extracted",
          unresolved_reasons: ["syntax_only_component_detection"],
        });
      }
    }

    if (ts.isImportDeclaration(node) && ts.isStringLiteral(node.moduleSpecifier)) {
      const module = node.moduleSpecifier.text;
      result.imports.push({
        id: stableId("import", path, node.getStart(sourceFile), "import", module),
        file_id: fileId,
        path,
        module,
        names: node.importClause ? [nodeText(sourceFile, node.importClause)] : [],
        alias: null,
        kind: "import",
        containing_symbol: stack.join(".") || null,
        range: rangeFor(sourceFile, node),
      });
    } else if (ts.isExportDeclaration(node) && node.moduleSpecifier && ts.isStringLiteral(node.moduleSpecifier)) {
      const module = node.moduleSpecifier.text;
      result.imports.push({
        id: stableId("import", path, node.getStart(sourceFile), "re_export", module),
        file_id: fileId,
        path,
        module,
        names: node.exportClause ? [nodeText(sourceFile, node.exportClause)] : [],
        alias: null,
        kind: "re_export",
        containing_symbol: stack.join(".") || null,
        range: rangeFor(sourceFile, node),
      });
    }

    if (ts.isCallExpression(node)) {
      const callee = nodeText(sourceFile, node.expression);
      const staticTarget = ts.isIdentifier(node.expression) || ts.isPropertyAccessExpression(node.expression)
        ? callee
        : null;
      result.calls.push({
        id: stableId("call", path, node.getStart(sourceFile), node.getEnd(), callee),
        file_id: fileId,
        path,
        callee,
        containing_symbol: stack.join(".") || null,
        range: rangeFor(sourceFile, node),
        resolved: false,
        unresolved_reasons: [
          staticTarget ? "static_name_only_no_binding_resolution" : "dynamic_callee_not_resolved",
        ],
      });

      if ((callee === "require" || callee === "import") && node.arguments.length > 0) {
        const module = literalText(node.arguments[0]);
        result.imports.push({
          id: stableId("import", path, node.getStart(sourceFile), callee, module ?? "<dynamic>"),
          file_id: fileId,
          path,
          module,
          names: [],
          alias: null,
          kind: callee === "require" ? "require" : "dynamic_import",
          containing_symbol: stack.join(".") || null,
          range: rangeFor(sourceFile, node),
          unresolved_reasons: module ? [] : ["dynamic_module_specifier"],
        });
      }

      const method = ts.isPropertyAccessExpression(node.expression)
        ? node.expression.name.text.toLowerCase()
        : "";
      const routePath = node.arguments.length > 0 ? literalText(node.arguments[0]) : null;
      if (routePath && ["get", "post", "put", "patch", "delete", "options", "head", "route", "use"].includes(method)) {
        result.routes.push({
          id: stableId("route", "typescript", path, method, routePath, node.getStart(sourceFile)),
          file_id: fileId,
          path,
          route: routePath,
          method: method.toUpperCase(),
          handler: stack.join(".") || callee,
          framework: "javascript_router_call",
          range: rangeFor(sourceFile, node),
          unresolved_reasons: ["framework_not_type_resolved"],
        });
      }

      const inTestFile = path.includes("/tests/") || path.startsWith("tests/") || /\.(?:test|spec)\.[^.]+$/i.test(path);
      const isChainedEachFactory =
        /(?:^|\.)(?:test|it|describe)\.each$/.test(callee) &&
        ts.isCallExpression(node.parent) &&
        node.parent.expression === node;
      if (
        inTestFile &&
        !isChainedEachFactory &&
        /(?:^|\.)(?:test|it|describe)(?:\.|$)/.test(callee)
      ) {
        const testName = node.arguments.length > 0 ? literalText(node.arguments[0]) : null;
        const assertions = assertionRecordsFor(sourceFile, node);
        // Chained APIs such as `it.each(...)(...)` can contain two CallExpression
        // nodes with the same start offset. Bind identity to the complete syntax
        // span and resolved callee so both test entities remain independently
        // accountable in the closed denominator.
        const assertionGroupId = stableId(
          "test",
          path,
          node.getStart(sourceFile),
          node.getEnd(),
          callee,
          "assertion-group",
        );
        result.tests.push({
          id: stableId(
            "test",
            path,
            node.getStart(sourceFile),
            node.getEnd(),
            callee,
            testName ?? callee,
          ),
          file_id: fileId,
          path,
          name: testName ?? callee,
          framework: "javascript_test_api",
          range: rangeFor(sourceFile, node),
          entity_type: /(?:^|\.)describe(?:\.|$)/.test(callee) ? "test_suite" : "test_case",
          assertion_group_id: assertionGroupId,
          assertion_count: assertions.length,
          extraction_disposition: "syntax_ast_structurally_extracted",
          unresolved_reasons: testName ? [] : ["dynamic_test_name"],
        });
        result.tests.push({
          id: assertionGroupId,
          file_id: fileId,
          path,
          name: `${testName ?? callee}::assertions`,
          framework: "typescript_compiler_api",
          range: rangeFor(sourceFile, node),
          entity_type: "test_assertion_group",
          assertion_count: assertions.length,
          assertions,
          extraction_disposition: "syntax_ast_structurally_extracted",
          unresolved_reasons:
            assertions.length > 0
              ? []
              : ["no_static_assertion_found_helper_or_runtime_failure_possible"],
        });
      }
    }

    if (ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) {
      const tagName = node.tagName.getText(sourceFile);
      const attributeNames = node.attributes.properties.map((property) =>
        ts.isJsxAttribute(property) ? property.name.getText(sourceFile) : "spread_attributes");
      result.components.push({
        id: stableId("component", path, "jsx-element", node.getStart(sourceFile), node.getEnd()),
        file_id: fileId,
        path,
        name: tagName,
        kind: "jsx_element",
        entity_type: "jsx_element",
        component_role: /^[a-z]/.test(tagName) ? "intrinsic_element" : "component_reference",
        attribute_names: [...new Set(attributeNames)].sort(),
        exported: false,
        range: rangeFor(sourceFile, node),
        detection: "typescript_compiler_api_jsx_opening_element",
        extraction_disposition: "syntax_ast_structurally_extracted",
        unresolved_reasons: ["jsx_component_binding_and_render_state_not_resolved"],
      });
      if (tagName === "Route" || tagName.endsWith(".Route")) {
        const pathAttribute = node.attributes.properties.find(
          (property) => ts.isJsxAttribute(property) && property.name.getText(sourceFile) === "path",
        );
        let routePath = null;
        if (pathAttribute && ts.isJsxAttribute(pathAttribute)) {
          if (pathAttribute.initializer && ts.isStringLiteral(pathAttribute.initializer)) {
            routePath = pathAttribute.initializer.text;
          } else if (
            pathAttribute.initializer &&
            ts.isJsxExpression(pathAttribute.initializer) &&
            pathAttribute.initializer.expression
          ) {
            routePath = literalText(pathAttribute.initializer.expression);
          }
        }
        result.routes.push({
          id: stableId("route", "jsx", path, node.getStart(sourceFile), routePath ?? "<dynamic>"),
          file_id: fileId,
          path,
          route: routePath,
          method: "VIEW",
          handler: stack.join(".") || tagName,
          framework: "react_router_jsx",
          range: rangeFor(sourceFile, node),
          unresolved_reasons: routePath ? [] : ["dynamic_or_missing_jsx_route_path"],
        });
      }
    }

    ts.forEachChild(node, (child) => walk(child, nextStack));
  }

  walk(sourceFile, []);

  const lineStarts = sourceFile.getLineStarts();
  for (let index = 0; index < lineStarts.length; index += 1) {
    const start = lineStarts[index];
    const end = index + 1 < lineStarts.length ? lineStarts[index + 1] : sourceFile.text.length;
    const segment = sourceFile.text.slice(start, end);
    const nonspace = segment.search(/\S/);
    if (nonspace < 0) continue;
    const position = Math.min(start + nonspace, Math.max(0, sourceFile.text.length - 1));
    const token = ts.getTokenAtPosition(sourceFile, position);
    let current = token;
    let containingSymbol = null;
    let depth = 0;
    while (current && !ts.isSourceFile(current)) {
      if (!containingSymbol && symbolNodes.has(current)) containingSymbol = symbolNodes.get(current);
      current = current.parent;
      depth += 1;
    }
    result.line_context[String(index + 1)] = {
      syntax_kind: ts.SyntaxKind[token.kind] ?? "UnknownToken",
      containing_symbol: containingSymbol,
      depth,
      unresolved_reasons: [],
    };
  }

  for (const key of ["symbols", "imports", "calls", "routes", "components", "tests"]) {
    result[key].sort((left, right) => compareText(left.id, right.id));
  }
  return result;
}

function run() {
  const packageJson = JSON.parse(readFileSync(new URL("../package.json", import.meta.url), "utf8"));
  const declaredVersion = packageJson?.devDependencies?.typescript;
  if (typeof declaredVersion !== "string" || !/^\d+\.\d+\.\d+$/.test(declaredVersion) || declaredVersion !== ts.version) {
    throw new Error(`TYPESCRIPT_VERSION_MISMATCH declared=${declaredVersion ?? "<missing>"} actual=${ts.version}`);
  }

  const request = JSON.parse(readFileSync(0, "utf8"));
  if (!request || !Array.isArray(request.files)) throw new Error("INVALID_REQUEST files must be an array");
  const files = request.files.map((file) => ({
    path: normalizePath(file.path),
    file_id: String(file.file_id),
    text: String(file.text),
  }));
  files.sort((left, right) => compareText(left.path, right.path));
  const seen = new Set();
  const seenFolded = new Set();
  for (const file of files) {
    if (seen.has(file.path)) throw new Error(`DUPLICATE_SOURCE_ID ${file.path}`);
    const folded = file.path.toLowerCase();
    if (seenFolded.has(folded)) throw new Error(`DUPLICATE_SOURCE_ID case-fold collision ${file.path}`);
    seen.add(file.path);
    seenFolded.add(folded);
    if (!SUPPORTED.has(extensionFor(file.path))) throw new Error(`UNSUPPORTED_EXTENSION ${file.path}`);
  }

  const sourceFiles = new Map();
  for (const file of files) {
    sourceFiles.set(
      file.path,
      ts.createSourceFile(
        file.path,
        file.text,
        ts.ScriptTarget.ESNext,
        true,
        SUPPORTED.get(extensionFor(file.path)),
      ),
    );
  }
  const options = {
    allowJs: true,
    checkJs: false,
    noEmit: true,
    noResolve: true,
    noLib: true,
    types: [],
    jsx: ts.JsxEmit.Preserve,
    target: ts.ScriptTarget.ESNext,
    module: ts.ModuleKind.ESNext,
  };
  const host = {
    getSourceFile: (name) => sourceFiles.get(name),
    getDefaultLibFileName: () => "lib.d.ts",
    writeFile: () => {},
    getCurrentDirectory: () => ".",
    getDirectories: () => [],
    fileExists: (name) => sourceFiles.has(name),
    readFile: (name) => sourceFiles.get(name)?.text,
    getCanonicalFileName: (name) => name,
    useCaseSensitiveFileNames: () => true,
    getNewLine: () => "\n",
    directoryExists: () => true,
    realpath: (name) => name,
  };
  const program = ts.createProgram(files.map((file) => file.path), options, host);
  const diagnostics = [];
  for (const file of files) {
    const sourceFile = program.getSourceFile(file.path);
    if (!sourceFile) throw new Error(`MISSING_SOURCE_FILE ${file.path}`);
    for (const diagnostic of program.getSyntacticDiagnostics(sourceFile)) {
      const location = diagnostic.start == null
        ? { line: 0, character: 0 }
        : sourceFile.getLineAndCharacterOfPosition(diagnostic.start);
      diagnostics.push({
        path: file.path,
        line: location.line + 1,
        column: location.character + 1,
        code: diagnostic.code,
        message: flattenMessage(diagnostic.messageText),
      });
    }
  }
  diagnostics.sort((left, right) =>
    compareText(left.path, right.path) ||
    left.line - right.line ||
    left.column - right.column ||
    left.code - right.code ||
    compareText(left.message, right.message),
  );
  if (diagnostics.length) {
    const message = diagnostics
      .map((item) => `${item.path}:${item.line}:${item.column} TS${item.code}: ${item.message}`)
      .join(" | ");
    throw new Error(`SYNTAX_DIAGNOSTIC ${message}`);
  }

  const results = {};
  for (const file of files) results[file.path] = extractFile(program.getSourceFile(file.path), file);
  return { ok: true, compiler_version: ts.version, results };
}

try {
  process.stdout.write(`${JSON.stringify(run())}\n`);
} catch (error) {
  process.stdout.write(`${JSON.stringify({ ok: false, errors: [String(error?.message ?? error)] })}\n`);
  process.exitCode = 2;
}
