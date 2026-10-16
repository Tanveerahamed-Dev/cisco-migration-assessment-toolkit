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
const hash = text => createHash('sha256').update(text).digest('hex');

export function scan(path, text) {
  const file = ts.createSourceFile(path, text, ts.ScriptTarget.Latest, true,
    path.endsWith('.tsx') ? ts.ScriptKind.TSX : path.endsWith('.ts') ? ts.ScriptKind.TS : ts.ScriptKind.JS);
  if (file.parseDiagnostics.length) throw new Error(`${path}: source parse failed: ${file.parseDiagnostics.map(d => ts.flattenDiagnosticMessageText(d.messageText, ' ')).join('; ')}`);
  const rows = [], occurrences = new Map();
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
    if ((ts.isPropertyAccessExpression(node) && node.name.text === 'length') ||
        (ts.isElementAccessExpression(node) && ts.isStringLiteral(node.argumentExpression) && node.argumentExpression.text === 'length')) emit(node, symbol, 'count');
    if (ts.isCallExpression(node)) {
      const callee = node.expression;
      const called = ts.isPropertyAccessExpression(callee) ? callee.name.text :
        ts.isElementAccessExpression(callee) && ts.isStringLiteral(callee.argumentExpression) ? callee.argumentExpression.text :
        ts.isIdentifier(callee) ? callee.text : '';
      if (['reduce', 'reduceRight', 'count', 'countBy', 'groupBy', 'sum', 'sumBy', 'mean', 'average'].includes(called)) emit(node, symbol, 'aggregate');
      if (['bfs', 'dfs', 'shortestPath', 'dijkstra', 'reachable', 'floodFill'].includes(called)) emit(node, symbol, 'graph-call');
      if (ts.isPropertyAccessExpression(callee) && callee.name.text === 'keys' && callee.expression.getText(file) === 'Object') emit(node, symbol, 'count-keys');
    }
    if (ts.isBinaryExpression(node)) {
      const op = node.operatorToken.kind;
      if ([ts.SyntaxKind.GreaterThanToken, ts.SyntaxKind.GreaterThanEqualsToken, ts.SyntaxKind.LessThanToken, ts.SyntaxKind.LessThanEqualsToken].includes(op)
          && domain.test(`${symbol} ${node.getText(file)}`) && /\d/.test(node.getText(file))) emit(node, symbol, 'fact-threshold');
      if ([ts.SyntaxKind.PlusEqualsToken, ts.SyntaxKind.MinusEqualsToken].includes(op) && domain.test(node.left.getText(file))) emit(node, symbol, 'counter-update');
      if ([ts.SyntaxKind.PlusToken, ts.SyntaxKind.MinusToken, ts.SyntaxKind.AsteriskToken, ts.SyntaxKind.SlashToken].includes(op)
          && domain.test(node.getText(file))) emit(node, symbol, 'fact-arithmetic');
    }
    if ((ts.isPrefixUnaryExpression(node) || ts.isPostfixUnaryExpression(node)) &&
        [ts.SyntaxKind.PlusPlusToken, ts.SyntaxKind.MinusMinusToken].includes(node.operator) &&
        domain.test(node.operand.getText(file))) emit(node, symbol, 'counter-update');
    if ((ts.isForStatement(node) || ts.isForOfStatement(node) || ts.isForInStatement(node) || ts.isWhileStatement(node) || ts.isDoStatement(node)) &&
        /adjacen|\badj\b|\bnbrs?\b|\bqueue\b|\bvisited\b|\bneighbou?rs\b/i.test(node.getText(file))) emit(node, symbol, 'graph-traversal');
    ts.forEachChild(node, child => walk(child, symbol));
  }
  walk(file);
  return rows;
}

process.stdout.write(JSON.stringify(input.sources.flatMap(source => scan(source.path, source.text))));
