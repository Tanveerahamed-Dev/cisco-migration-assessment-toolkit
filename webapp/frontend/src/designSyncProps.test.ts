import { readFileSync } from "node:fs";
import * as path from "node:path";
import ts from "typescript";
import { beforeAll, describe, expect, it } from "vitest";

// npm scripts and Vitest both set cwd to this package (including `npm --prefix ... test`). Using
// cwd also avoids Vite's transformed, non-file `import.meta.url` inside the jsdom test runtime.
const FRONTEND = path.resolve(process.cwd());
const REPO = path.resolve(FRONTEND, "../..");
const DESIGN_SYNC = path.join(REPO, ".design-sync");
const CONFIG = path.join(DESIGN_SYNC, "config.json");
const ENTRY = path.join(FRONTEND, "ds.entry.ts");
const TSCONFIG = path.join(FRONTEND, "tsconfig.json");
const VIRTUAL = path.join(FRONTEND, "__virtual_design_sync_contracts__.ts");

interface DesignSyncConfig {
  dtsPropsFor?: unknown;
}

interface GuardContext {
  checker: ts.TypeChecker;
  contractNames: string[];
  diagnostics: readonly ts.Diagnostic[];
  entryExports: Map<string, ts.Symbol>;
  virtualExports: Map<string, ts.Symbol>;
  virtualSource: ts.SourceFile;
}

const canonical = (file: string) => {
  const absolute = path.resolve(file);
  return ts.sys.useCaseSensitiveFileNames ? absolute : absolute.toLowerCase();
};

const isInside = (child: string, parent: string) => {
  const relative = path.relative(parent, child);
  return relative === "" || (
    relative !== ".."
    && !relative.startsWith(`..${path.sep}`)
    && !path.isAbsolute(relative)
  );
};

function loadContracts(): Record<string, string> {
  const parsed = JSON.parse(readFileSync(CONFIG, "utf8")) as DesignSyncConfig;
  const value = parsed.dtsPropsFor;
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(".design-sync/config.json dtsPropsFor must be a non-empty object");
  }

  const contracts: Record<string, string> = {};
  for (const [name, body] of Object.entries(value)) {
    if (!ts.isIdentifierText(name, ts.ScriptTarget.ES2021)) {
      throw new Error(`dtsPropsFor has a non-identifier component name: ${name}`);
    }
    if (typeof body !== "string" || !body.trim()) {
      throw new Error(`dtsPropsFor.${name} must be a non-empty string`);
    }
    contracts[name] = body;
  }
  if (!Object.keys(contracts).length) {
    throw new Error(".design-sync/config.json dtsPropsFor must not be empty");
  }
  return contracts;
}

function moduleExports(
  program: ts.Program,
  checker: ts.TypeChecker,
  file: string,
): Map<string, ts.Symbol> {
  const source = program.getSourceFiles().find((candidate) =>
    canonical(candidate.fileName) === canonical(file));
  if (!source) throw new Error(`TypeScript program did not load ${file}`);
  const symbol = checker.getSymbolAtLocation(source);
  if (!symbol) throw new Error(`TypeScript could not resolve the module symbol for ${file}`);
  return new Map(checker.getExportsOfModule(symbol).map((item) => [item.name, item]));
}

function createContext(overrides: Readonly<Record<string, string>> = {}): GuardContext {
  const liveContracts = loadContracts();
  for (const name of Object.keys(overrides)) {
    if (!(name in liveContracts)) throw new Error(`cannot mutate unknown contract ${name}`);
  }
  const contracts = { ...liveContracts, ...overrides };
  const controls = `
export interface __ControlBaseline { stable: number; maybe?: string }
export interface __ControlMissing { stable: number }
export interface __ControlExtra { stable: number; maybe?: string; added: boolean }
export interface __ControlRequired { stable: number; maybe: string }
export interface __ControlWrong { stable: string; maybe?: string }
export interface __ControlReadonly { readonly stable: number; maybe?: string }
export interface __ControlNestedSafe { items: Array<string> }
export interface __ControlNestedAny { items: Array<any> }
export interface __ControlAny { stable: any }
export interface __ControlUnknown { stable: unknown }
`;
  const virtualText = [
    `import * as React from "react";`,
    ...Object.entries(contracts).map(([name, body]) =>
      `export interface ${name}Props { ${body} }`),
    controls,
  ].join("\n");

  const readResult = ts.readConfigFile(TSCONFIG, ts.sys.readFile);
  if (readResult.error) {
    throw new Error(ts.formatDiagnostic(readResult.error, {
      getCanonicalFileName: canonical,
      getCurrentDirectory: () => REPO,
      getNewLine: () => ts.sys.newLine,
    }));
  }
  const parsed = ts.parseJsonConfigFileContent(
    readResult.config,
    ts.sys,
    FRONTEND,
    { noEmit: true },
    TSCONFIG,
  );
  const options = { ...parsed.options, noEmit: true };
  const host = ts.createCompilerHost(options, true);
  const originalExists = host.fileExists.bind(host);
  const originalRead = host.readFile.bind(host);
  const originalGetSource = host.getSourceFile.bind(host);
  const originalRealpath = host.realpath?.bind(host);

  host.fileExists = (file) => canonical(file) === canonical(VIRTUAL) || originalExists(file);
  host.readFile = (file) => canonical(file) === canonical(VIRTUAL)
    ? virtualText
    : originalRead(file);
  host.getSourceFile = (file, languageVersion, onError, shouldCreateNewSourceFile) =>
    canonical(file) === canonical(VIRTUAL)
      ? ts.createSourceFile(file, virtualText, languageVersion, true, ts.ScriptKind.TS)
      : originalGetSource(file, languageVersion, onError, shouldCreateNewSourceFile);
  if (originalRealpath) {
    host.realpath = (file) => canonical(file) === canonical(VIRTUAL)
      ? VIRTUAL
      : originalRealpath(file);
  }

  const resolutionCache = ts.createModuleResolutionCache(FRONTEND, canonical, options);
  host.resolveModuleNameLiterals = (
    moduleLiterals,
    containingFile,
    redirectedReference,
    compilerOptions,
  ) => moduleLiterals.map((literal) => {
    let result = ts.resolveModuleName(
      literal.text,
      containingFile,
      compilerOptions,
      host,
      resolutionCache,
      redirectedReference,
    );
    const bare = !literal.text.startsWith(".") && !path.isAbsolute(literal.text);
    if (!result.resolvedModule && bare && isInside(containingFile, DESIGN_SYNC)) {
      result = ts.resolveModuleName(
        literal.text,
        path.join(FRONTEND, "__design_sync_resolution_anchor__.tsx"),
        compilerOptions,
        host,
        resolutionCache,
        redirectedReference,
      );
    }
    return result;
  });

  const roots = [...parsed.fileNames, ENTRY, VIRTUAL].filter((file, index, all) =>
    all.findIndex((candidate) => canonical(candidate) === canonical(file)) === index);
  const program = ts.createProgram({ rootNames: roots, options, host });
  const checker = program.getTypeChecker();
  const virtualSource = program.getSourceFiles().find((source) =>
    canonical(source.fileName) === canonical(VIRTUAL));
  if (!virtualSource) throw new Error("TypeScript did not load the virtual props contracts");

  return {
    checker,
    contractNames: Object.keys(contracts).sort(),
    diagnostics: [...parsed.errors, ...ts.getPreEmitDiagnostics(program)]
      .filter((item) => item.category === ts.DiagnosticCategory.Error),
    entryExports: moduleExports(program, checker, ENTRY),
    virtualExports: moduleExports(program, checker, VIRTUAL),
    virtualSource,
  };
}

function actualPropsType(
  checker: ts.TypeChecker,
  exported: ts.Symbol,
  componentName: string,
): ts.Type {
  const component = exported.flags & ts.SymbolFlags.Alias
    ? checker.getAliasedSymbol(exported)
    : exported;
  const declaration = component.valueDeclaration ?? component.declarations?.[0];
  if (!declaration) throw new Error(`${componentName} has no value declaration`);
  if (component.flags & ts.SymbolFlags.Class) {
    const instance = checker.getDeclaredTypeOfSymbol(component);
    const props = checker.getTypeOfPropertyOfType(instance, "props");
    if (!props) throw new Error(`${componentName} class instances do not expose props`);
    return props;
  }
  const valueType = checker.getTypeOfSymbolAtLocation(component, declaration);
  const calls = valueType.getCallSignatures();
  if (calls.length) {
    if (calls.length !== 1 || calls[0].parameters.length < 1) {
      throw new Error(`${componentName} must have one unambiguous props-bearing call signature`);
    }
    const parameter = calls[0].parameters[0];
    return checker.getTypeOfSymbolAtLocation(
      parameter,
      parameter.valueDeclaration ?? declaration,
    );
  }

  const constructors = valueType.getConstructSignatures();
  if (constructors.length !== 1) {
    throw new Error(`${componentName} is neither a supported function nor class component`);
  }
  const instance = checker.getReturnTypeOfSignature(constructors[0]);
  const props = checker.getTypeOfPropertyOfType(instance, "props");
  if (!props) throw new Error(`${componentName} class instances do not expose props`);
  return props;
}

function declaredType(context: GuardContext, name: string): ts.Type {
  const symbol = context.virtualExports.get(name);
  if (!symbol) throw new Error(`Virtual contract ${name} was not emitted`);
  return context.checker.getDeclaredTypeOfSymbol(symbol);
}

function typeLabel(checker: ts.TypeChecker, type: ts.Type): string {
  return checker.typeToString(type, undefined, ts.TypeFormatFlags.NoTruncation);
}

function isReadonlyProperty(symbol: ts.Symbol): boolean {
  return Boolean(symbol.declarations?.some((declaration) =>
    ts.canHaveModifiers(declaration)
    && ts.getModifiers(declaration)?.some((modifier) =>
      modifier.kind === ts.SyntaxKind.ReadonlyKeyword)));
}

function unsafeResolvedType(
  checker: ts.TypeChecker,
  type: ts.Type,
  seen: Set<ts.Type> = new Set(),
): string | null {
  if (seen.has(type)) return null;
  seen.add(type);
  if (type.flags & ts.TypeFlags.Any) return "any";
  if (type.flags & ts.TypeFlags.Unknown) return "unknown";

  const argumentsToCheck: ts.Type[] = [...(type.aliasTypeArguments ?? [])];
  if (
    type.flags & ts.TypeFlags.Object
    && ((type as ts.ObjectType).objectFlags & ts.ObjectFlags.Reference)
  ) {
    argumentsToCheck.push(...checker.getTypeArguments(type as ts.TypeReference));
  }
  for (const argument of new Set(argumentsToCheck)) {
    const unsafe = unsafeResolvedType(checker, argument, seen);
    if (unsafe) return `type argument contains ${unsafe}`;
  }

  // Trust installed/library declarations themselves, but only after checking explicit type
  // arguments supplied by our source (so Array<any> and ReactElement<any> still fail). Expanding
  // ReactNode's dependency-owned internals would otherwise flag upstream compatibility anys that
  // are not part of this repository's authored props contract.
  const symbol = type.aliasSymbol ?? type.getSymbol();
  const declarations = symbol?.declarations ?? [];
  if (declarations.length && declarations.every((declaration) =>
    declaration.getSourceFile().isDeclarationFile
    && canonical(declaration.getSourceFile().fileName)
      .includes(`${path.sep}node_modules${path.sep}`))) {
    return null;
  }

  if (type.isUnionOrIntersection()) {
    for (const member of type.types) {
      const unsafe = unsafeResolvedType(checker, member, seen);
      if (unsafe) return unsafe;
    }
  }

  if (!(type.flags & ts.TypeFlags.Object)) return null;
  for (const property of checker.getPropertiesOfType(type)) {
    const propertyType = checker.getTypeOfPropertyOfType(type, property.name);
    if (!propertyType) continue;
    const unsafe = unsafeResolvedType(checker, propertyType, seen);
    if (unsafe) return `${property.name} contains ${unsafe}`;
  }
  for (const signature of [
    ...type.getCallSignatures(),
    ...type.getConstructSignatures(),
  ]) {
    for (const parameter of signature.parameters) {
      const declaration = parameter.valueDeclaration ?? parameter.declarations?.[0];
      if (!declaration) continue;
      const unsafe = unsafeResolvedType(
        checker,
        checker.getTypeOfSymbolAtLocation(parameter, declaration),
        seen,
      );
      if (unsafe) return `call parameter contains ${unsafe}`;
    }
    const unsafeReturn = unsafeResolvedType(checker, checker.getReturnTypeOfSignature(signature), seen);
    if (unsafeReturn) return `call return contains ${unsafeReturn}`;
  }
  for (const kind of [ts.IndexKind.String, ts.IndexKind.Number]) {
    const indexed = checker.getIndexTypeOfType(type, kind);
    if (!indexed) continue;
    const unsafe = unsafeResolvedType(checker, indexed, seen);
    if (unsafe) return `${ts.IndexKind[kind].toLowerCase()} index contains ${unsafe}`;
  }
  return null;
}

function diffProps(
  checker: ts.TypeChecker,
  actual: ts.Type,
  contract: ts.Type,
): string[] {
  const issues: string[] = [];
  const actualProperties = new Map(
    checker.getPropertiesOfType(actual).map((property) => [property.name, property]),
  );
  const contractProperties = new Map(
    checker.getPropertiesOfType(contract).map((property) => [property.name, property]),
  );
  const names = [...new Set([...actualProperties.keys(), ...contractProperties.keys()])].sort();

  for (const name of names) {
    const actualProperty = actualProperties.get(name);
    const contractProperty = contractProperties.get(name);
    if (!actualProperty) {
      issues.push(`source is missing contract prop ${name}`);
      continue;
    }
    if (!contractProperty) {
      issues.push(`contract is missing source prop ${name}`);
      continue;
    }
    const actualOptional = Boolean(actualProperty.flags & ts.SymbolFlags.Optional);
    const contractOptional = Boolean(contractProperty.flags & ts.SymbolFlags.Optional);
    if (actualOptional !== contractOptional) {
      issues.push(
        `${name} optionality differs (source=${actualOptional}, contract=${contractOptional})`,
      );
    }
    const actualReadonly = isReadonlyProperty(actualProperty);
    const contractReadonly = isReadonlyProperty(contractProperty);
    if (actualReadonly !== contractReadonly) {
      issues.push(
        `${name} readonly differs (source=${actualReadonly}, contract=${contractReadonly})`,
      );
    }
    const actualType = checker.getTypeOfPropertyOfType(actual, name);
    const contractType = checker.getTypeOfPropertyOfType(contract, name);
    if (!actualType || !contractType) {
      issues.push(`${name} could not be resolved on both sides`);
      continue;
    }
    const actualUnsafe = unsafeResolvedType(checker, actualType);
    const contractUnsafe = unsafeResolvedType(checker, contractType);
    if (actualUnsafe || contractUnsafe) {
      issues.push(
        `${name} resolves to unsafe type (source=${actualUnsafe ?? "safe"}, `
        + `contract=${contractUnsafe ?? "safe"})`,
      );
      continue;
    }
    if (
      !checker.isTypeAssignableTo(actualType, contractType)
      || !checker.isTypeAssignableTo(contractType, actualType)
    ) {
      issues.push(
        `${name} type differs (source=${typeLabel(checker, actualType)}, `
        + `contract=${typeLabel(checker, contractType)})`,
      );
    }
  }

  for (const kind of [ts.IndexKind.String, ts.IndexKind.Number]) {
    const actualIndex = checker.getIndexTypeOfType(actual, kind);
    const contractIndex = checker.getIndexTypeOfType(contract, kind);
    if (Boolean(actualIndex) !== Boolean(contractIndex)) {
      issues.push(`${ts.IndexKind[kind].toLowerCase()} index signature presence differs`);
    } else if (actualIndex && contractIndex && (
      !checker.isTypeAssignableTo(actualIndex, contractIndex)
      || !checker.isTypeAssignableTo(contractIndex, actualIndex)
    )) {
      issues.push(`${ts.IndexKind[kind].toLowerCase()} index signature type differs`);
    }
  }
  return issues;
}

function unsafeTypeSyntax(source: ts.SourceFile, interfaceNames: ReadonlySet<string>): string[] {
  const issues: string[] = [];
  for (const statement of source.statements) {
    if (!ts.isInterfaceDeclaration(statement) || !interfaceNames.has(statement.name.text)) continue;
    const visit = (node: ts.Node): void => {
      if (node.kind === ts.SyntaxKind.AnyKeyword || node.kind === ts.SyntaxKind.UnknownKeyword) {
        const location = source.getLineAndCharacterOfPosition(node.getStart(source));
        issues.push(`${statement.name.text} uses ${node.getText(source)} at line ${location.line + 1}`);
      }
      ts.forEachChild(node, visit);
    };
    ts.forEachChild(statement, visit);
  }
  return issues;
}

function formatDiagnostics(diagnostics: readonly ts.Diagnostic[]): string[] {
  return diagnostics.map((diagnostic) => ts.formatDiagnostic(diagnostic, {
    getCanonicalFileName: canonical,
    getCurrentDirectory: () => REPO,
    getNewLine: () => ts.sys.newLine,
  }).trim());
}

function contractFailures(context: GuardContext): string[] {
  const failures = formatDiagnostics(context.diagnostics)
    .map((diagnostic) => `compiler: ${diagnostic}`);
  const contractInterfaces = new Set(context.contractNames.map((name) => `${name}Props`));
  failures.push(...unsafeTypeSyntax(context.virtualSource, contractInterfaces)
    .map((issue) => `contract syntax: ${issue}`));

  for (const name of context.contractNames) {
    const exported = context.entryExports.get(name);
    if (!exported) {
      failures.push(`${name}: missing from ds.entry.ts`);
      continue;
    }
    try {
      const actual = actualPropsType(context.checker, exported, name);
      const contract = declaredType(context, `${name}Props`);
      failures.push(...diffProps(context.checker, actual, contract)
        .map((issue) => `${name}: ${issue}`));
    } catch (error) {
      failures.push(`${name}: ${error instanceof Error ? error.message : String(error)}`);
    }
  }
  return failures;
}

describe("design-sync props contracts", () => {
  let context: GuardContext;
  let mutatedContext: GuardContext;

  beforeAll(() => {
    context = createContext();
    mutatedContext = createContext({
      Kpi: "value: number; label?: string; bogus: boolean; tone?: any;",
    });
  }, 60_000);

  it("matches all public component props through the real TypeScript barrel", () => {
    expect(context.contractNames).toContain("DemoDataProvider");
    expect(contractFailures(context)).toEqual([]);
  });

  it("rejects a real contract mutated through the complete config-to-barrel path", () => {
    const failures = contractFailures(mutatedContext).join("\n");
    expect(failures).toMatch(/Kpi: contract is missing source prop hint/);
    expect(failures).toMatch(/Kpi: source is missing contract prop bogus/);
    expect(failures).toMatch(/Kpi: label optionality differs/);
    expect(failures).toMatch(/Kpi: value type differs/);
    expect(failures).toMatch(/KpiProps uses any/);
  });

  it("ratchets nested unsafe types and readonly exactness in the comparator", () => {
    const baseline = declaredType(context, "__ControlBaseline");
    expect(diffProps(context.checker, baseline, declaredType(context, "__ControlMissing")))
      .toContain("contract is missing source prop maybe");
    expect(diffProps(context.checker, baseline, declaredType(context, "__ControlExtra")))
      .toContain("source is missing contract prop added");
    expect(diffProps(context.checker, baseline, declaredType(context, "__ControlRequired")).join("\n"))
      .toMatch(/maybe optionality differs/);
    expect(diffProps(context.checker, baseline, declaredType(context, "__ControlWrong")).join("\n"))
      .toMatch(/stable type differs/);
    expect(diffProps(context.checker, baseline, declaredType(context, "__ControlReadonly")).join("\n"))
      .toMatch(/stable readonly differs/);
    expect(diffProps(
      context.checker,
      declaredType(context, "__ControlNestedSafe"),
      declaredType(context, "__ControlNestedAny"),
    ).join("\n")).toMatch(/items resolves to unsafe type/);
    expect(unsafeTypeSyntax(context.virtualSource, new Set(["__ControlAny"])).join("\n"))
      .toMatch(/uses any/);
    expect(unsafeTypeSyntax(context.virtualSource, new Set(["__ControlUnknown"])).join("\n"))
      .toMatch(/uses unknown/);
  });
});
