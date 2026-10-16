// Parse source as data. Never import, evaluate or execute an inspected application.
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { createHash } from 'node:crypto';

const require = createRequire(resolve(process.cwd(), 'atlas-scope/package.json'));
const ts = require('typescript');
if (ts.version !== '5.9.3') throw new Error('The interface detector requires the locked TypeScript 5.9.3 parser');
const input = JSON.parse(readFileSync(0, 'utf8'));
const domain = /health|score|band|severit|readiness|verdict|gate|punch|lifecycle|endpoint|device|vlan|flow|route|causal|impact|blast|adjacen|neighbou?r|graph|topolog|coverage/i;
const ownerName = /^(?:counterfactualFailure|failureImpact|tracePath|flowBetween|evalAcl|linkCarries|causalFlows|fleetHealthState|scoreToken|HEALTH_TONE|GAUGE_COLOR|(?:compute|calculate|recount|simulate|evaluate|classify|qualify|count|trace)[A-Z_].*)$/;
const verdicts = new Set(['READY', 'NOT READY', 'CAUTION', 'GO', 'NO-GO', 'CONDITIONAL GO', 'Critical', 'Excellent', 'Good', 'Fair', 'Poor', 'ok', 'watch', 'risk', 'crit', 'healthy', 'permit', 'deny', 'allow', 'block', 'reached', 'unreachable']);
const hash = text => createHash('sha256').update(text).digest('hex');

export function scan(path, text) {
  const file = ts.createSourceFile(path, text, ts.ScriptTarget.Latest, true,
    path.endsWith('.tsx') ? ts.ScriptKind.TSX : path.endsWith('.jsx') ? ts.ScriptKind.JSX : /\.[mc]?ts$/.test(path) ? ts.ScriptKind.TS : ts.ScriptKind.JS);
  if (file.parseDiagnostics.length) throw new Error(`${path}: source parse failed: ${file.parseDiagnostics.map(d => ts.flattenDiagnosticMessageText(d.messageText, ' ')).join('; ')}`);
  const rows = [], occurrences = new Map();
  const constantKeys = new Map(), declarations = [];
  function remember(name, value) {
    const values = constantKeys.get(name) ?? new Set();
    if (values.has(value)) return false;
    values.add(value); constantKeys.set(name, values); return true;
  }
  function collect(node) {
    if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name) && node.initializer) {
      declarations.push(node);
      if (ts.isStringLiteral(node.initializer)) remember(node.name.text, node.initializer.text);
    }
    ts.forEachChild(node, collect);
  }
  collect(file);
  function keyOf(node) {
    if (!node) return null;
    if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) return node.text;
    if (ts.isIdentifier(node)) {
      const values = constantKeys.get(node.text);
      // A shadowed name is conservative: any possible count property is tracked.
      if (values?.has('length')) return 'length';
      if (values?.has('size')) return 'size';
      return values?.size === 1 ? [...values][0] : null;
    }
    if (ts.isBinaryExpression(node) && node.operatorToken.kind === ts.SyntaxKind.PlusToken) {
      const left = keyOf(node.left), right = keyOf(node.right);
      return left === null || right === null ? null : left + right;
    }
    return null;
  }
  for (let pass = 0; pass <= declarations.length; pass++) {
    let changed = false;
    for (const declaration of declarations) {
      const value = keyOf(declaration.initializer);
      if (value !== null && remember(declaration.name.text, value)) changed = true;
    }
    if (!changed) break;
  }
  function name(node) {
    if (node.name && (ts.isIdentifier(node.name) || ts.isStringLiteral(node.name))) return node.name.text;
    if (node.parent && ts.isVariableDeclaration(node.parent)) return node.parent.name.getText(file);
    if (node.parent && ts.isPropertyAssignment(node.parent)) return node.parent.name.getText(file);
    return '<callback>';
  }
  function stable(node) {
    // Token spelling without comments/whitespace; strings and numeric thresholds stay exact.
    const scanner = ts.createScanner(ts.ScriptTarget.Latest, true, file.languageVariant, node.getText(file));
    const tokens = [];
    for (let token = scanner.scan(); token !== ts.SyntaxKind.EndOfFileToken; token = scanner.scan()) tokens.push([token, scanner.getTokenText()]);
    return JSON.stringify(tokens);
  }
  function emit(node, symbol, rule) {
    const fingerprint = hash(stable(node)), key = `${symbol}:${rule}:${fingerprint}`;
    const occurrence = (occurrences.get(key) ?? 0) + 1; occurrences.set(key, occurrence);
    rows.push({ path, symbol, rule, fingerprint, occurrence,
      line: file.getLineAndCharacterOfPosition(node.getStart(file)).line + 1,
      expression: node.getText(file).replace(/\s+/g, ' ').slice(0, 240) });
  }
  function walk(node, scope = '<module>') {
    const functionLike = ts.isFunctionLike(node);
    const own = functionLike ? name(node) : null;
    const symbol = functionLike ? (scope === '<module>' ? own : `${scope}.${own}`) : scope;
    if (functionLike && ownerName.test(own)) emit(node.name ?? node.parent?.name ?? node, symbol, 'analysis-symbol');
    if (ts.isReturnStatement(node) && node.expression) {
      let decision = false;
      const literals = child => { if (ts.isStringLiteral(child) && verdicts.has(child.text)) decision = true; ts.forEachChild(child, literals); };
      literals(node.expression);
      if (decision) emit(node.expression, symbol, 'fact-decision');
    }
    if ((ts.isPropertyAccessExpression(node) && ['length', 'size'].includes(node.name.text)) ||
        (ts.isElementAccessExpression(node) && ['length', 'size'].includes(keyOf(node.argumentExpression)))) emit(node, symbol, 'count');
    if (ts.isBindingElement(node) && ts.isObjectBindingPattern(node.parent)) {
      const property = node.propertyName;
      const key = property ? ts.isIdentifier(property) ? property.text : keyOf(property) : node.name.getText(file);
      if (['length', 'size'].includes(key)) emit(node, symbol, 'count');
    }
    if (ts.isCallExpression(node)) {
      const callee = node.expression;
      const called = ts.isPropertyAccessExpression(callee) ? callee.name.text :
        ts.isElementAccessExpression(callee) && ts.isStringLiteral(callee.argumentExpression) ? callee.argumentExpression.text :
        ts.isIdentifier(callee) ? callee.text : '';
      if (['reduce', 'reduceRight', 'count', 'countBy', 'groupBy', 'sum', 'sumBy', 'mean', 'average'].includes(called)) emit(node, symbol, 'aggregate');
      if (['bfs', 'dfs', 'shortestPath', 'dijkstra', 'reachable', 'floodFill'].includes(called)) emit(node, symbol, 'graph-call');
      if (['eval', 'Function', 'exec', 'compile'].includes(called)) emit(node, symbol, 'dynamic-code');
      if (ts.isPropertyAccessExpression(callee) && ['Reflect', 'Object'].includes(callee.expression.getText(file)) && ['get', 'getOwnPropertyDescriptor'].includes(called) && ['length', 'size'].includes(keyOf(node.arguments[1]))) emit(node, symbol, 'count');
      if (['push', 'pop', 'shift', 'unshift', 'add', 'set'].includes(called)) emit(node, symbol, 'collection-update');
      if (ts.isPropertyAccessExpression(callee) && callee.name.text === 'keys' && callee.expression.getText(file) === 'Object') emit(node, symbol, 'count-keys');
    }
    if (ts.isNewExpression(node) && node.expression.getText(file) === 'Function') emit(node, symbol, 'dynamic-code');
    if (ts.isBinaryExpression(node)) {
      const op = node.operatorToken.kind;
      if ([ts.SyntaxKind.BarBarToken, ts.SyntaxKind.QuestionQuestionToken].includes(op) && ts.isNumericLiteral(node.right) && node.right.text === '0' && domain.test(node.left.getText(file))) emit(node, symbol, 'fact-default-zero');
      if ([ts.SyntaxKind.GreaterThanToken, ts.SyntaxKind.GreaterThanEqualsToken, ts.SyntaxKind.LessThanToken, ts.SyntaxKind.LessThanEqualsToken].includes(op)
          && /\d/.test(node.getText(file))) emit(node, symbol, 'fact-threshold');
      if ([ts.SyntaxKind.PlusEqualsToken, ts.SyntaxKind.MinusEqualsToken].includes(op)) emit(node, symbol, 'counter-update');
      if ([ts.SyntaxKind.PlusToken, ts.SyntaxKind.MinusToken, ts.SyntaxKind.AsteriskToken, ts.SyntaxKind.SlashToken].includes(op)
          && domain.test(node.getText(file))) emit(node, symbol, 'fact-arithmetic');
    }
    if ((ts.isPrefixUnaryExpression(node) || ts.isPostfixUnaryExpression(node)) &&
        [ts.SyntaxKind.PlusPlusToken, ts.SyntaxKind.MinusMinusToken].includes(node.operator)) emit(node, symbol, 'counter-update');
    if (ts.isConditionalExpression(node) && /Critical|Excellent|Good|Poor|READY|GO|risk|watch|healthy/.test(node.whenTrue.getText(file) + node.whenFalse.getText(file))) emit(node.condition, symbol, 'fact-decision');
    if ((ts.isForStatement(node) || ts.isForOfStatement(node) || ts.isForInStatement(node) || ts.isWhileStatement(node) || ts.isDoStatement(node)) &&
        /adjacen|\badj\b|\bnbrs?\b|\bqueue\b|\bvisited\b|\bneighbou?rs\b/i.test(node.getText(file))) emit(node, symbol, 'graph-traversal');
    ts.forEachChild(node, child => walk(child, symbol));
  }
  walk(file);
  return rows;
}

process.stdout.write(JSON.stringify(input.sources.flatMap(source => scan(source.path, source.text))));
