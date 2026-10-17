// Parse source as data. Never import, evaluate or execute an inspected application.
import { builtinModules, createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
import { dirname, resolve, posix } from 'node:path';
import { createHash } from 'node:crypto';
import { pathToFileURL } from 'node:url';

const require = createRequire(resolve(process.cwd(), 'atlas-scope/package.json'));
const ts = require('typescript');
if (ts.version !== '5.9.3') throw new Error('The interface detector requires the locked TypeScript 5.9.3 parser');
const parse5Entry = require.resolve('parse5');
const parse5Package = JSON.parse(readFileSync(resolve(dirname(parse5Entry), '..', 'package.json'), 'utf8'));
if (parse5Package.version !== '8.0.1') throw new Error('The interface detector requires the locked parse5 8.0.1 HTML5 parser');
const { parse: parseHtml } = await import(pathToFileURL(parse5Entry).href);
const input = JSON.parse(readFileSync(0, 'utf8'));
const domain = /health|score|band|severit|readiness|verdict|gate|punch|lifecycle|endpoint|device|vlan|flow|route|causal|impact|blast|adjacen|neighbou?r|graph|topolog|coverage/i;
const ownerName = /^(?:counterfactualFailure|failureImpact|tracePath|flowBetween|evalAcl|linkCarries|causalFlows|fleetHealthState|scoreToken|HEALTH_TONE|GAUGE_COLOR|(?:compute|calculate|recount|simulate|evaluate|classify|qualify|count|trace)[A-Z_].*)$/;
const verdicts = new Set(['READY', 'NOT READY', 'CAUTION', 'GO', 'NO-GO', 'CONDITIONAL GO', 'Critical', 'Excellent', 'Good', 'Fair', 'Poor', 'ok', 'watch', 'risk', 'crit', 'healthy', 'permit', 'deny', 'allow', 'block', 'reached', 'unreachable']);
const verdictName = /^(?:can|could|should|is|has|may|must|allow|deny|permit|block|ready|safe|eligible|valid|approved|accepted|rejected|blocked|allowed|denied)(?:_|[A-Z]|$)|(?:^|_)(?:verdict|decision|readiness|ready|allowed|denied|eligible|gate|go_no_go|can_cut_over|ok|pass|fail)$/;
const verdictReturns = new Set([...verdicts, 'yes', 'no', 'true', 'false', 'pass', 'fail', 'approved', 'rejected', 'blocked', 'allowed', 'valid', 'invalid'].map(value => value.toLowerCase().replaceAll('_', '-')));
const hash = text => createHash('sha256').update(text).digest('hex');
// Browser document class, including executable SVG entries and HTML aliases.
// Mirror BROWSER_DOCUMENT_SUFFIXES in the Python source census; controls execute
// discovery, immutable reads, AST and lexical refusal for each spelling.
const browserDocument = path => /\.(?:html?|xhtml|svg)$/i.test(path);
const generatedOpaqueSites = [], generatedOpaqueOccurrences = new Map();
const resourceSchemes = new Set(['http:', 'https:', 'mailto:', 'tel:', 'file:', 'about:']);
const executableSchemes = new Map([
  ['javascript:', url => decodeURIComponent(url.href.slice(url.protocol.length))],
  ['data:', () => { throw new Error('Unsupported executable data URL source'); }],
  ['vbscript:', () => { throw new Error('Unsupported executable VBScript URL source'); }],
]);

function htmlSources(text, depth = 0, baseLine = 0, resolveScript = null, onOpaque = null) {
  if (depth > 8) throw new Error('Nested HTML exceeds the static census depth');
  const document = parseHtml(text, { sourceCodeLocationInfo: true });
  const fragments = [];
  const wrappers = new Map();
  function wrapper(kind) {
    const ordinal = (wrappers.get(kind) ?? 0) + 1; wrappers.set(kind, ordinal);
    return `${kind}_${ordinal}`;
  }
  function visit(node) {
    const attrs = node.attrs ?? [];
    if (node.tagName === 'script') {
      const external = attrs.find(attr => ['src', 'href'].includes(attr.name));
      if (external && !resolveScript?.(external.value)) {
        if (!onOpaque) throw new Error('External script source is not closed by discovery');
        onOpaque(['unresolved-script-src', external.value], baseLine + (node.sourceCodeLocation?.startLine ?? 1));
      }
      const location = node.sourceCodeLocation;
      if (!location?.startTag) throw new Error('Script source location is unavailable');
      if (text.slice(location.startTag.startOffset, location.startTag.endOffset).trimEnd().endsWith('/>')) {
        if (!onOpaque) throw new Error('Self-closing script syntax is ambiguous');
        onOpaque(['self-closing-script-fragment'], baseLine + location.startTag.startLine);
      }
      if (!location.endTag) {
        if (!onOpaque) throw new Error('Unclosed Explorer script');
        onOpaque(['unclosed-script-fragment'], baseLine + location.startTag.startLine);
      }
      if (external) {
        const url = new URL(external.value, 'https://static-census.invalid/');
        if (['http:', 'https:'].includes(url.protocol) && url.origin !== 'https://static-census.invalid') {
          // Uninspected remote code is an explicit, frozen source form, not an
          // empty/clean script. A newly added remote source cannot silently pass.
          if (onOpaque) onOpaque(['remote-script-src', url.href], baseLine + location.startTag.startLine);
          else fragments.push({text: `__atlas_opaque_script_source__(${JSON.stringify(url.href)});`, line: baseLine + location.startTag.endLine - 1});
        }
      }
      const type = attrs.find(attr => attr.name === 'type')?.value?.trim().toLowerCase();
      if (!external && !['application/json', 'application/ld+json', 'importmap'].includes(type)) {
        fragments.push({ text: (node.childNodes ?? []).filter(child => child.nodeName === '#text').map(child => child.value).join(''),
          line: baseLine + location.startTag.endLine - 1 });
      }
    }
    for (const attr of attrs) {
      const line = baseLine + (node.sourceCodeLocation?.attrs?.[attr.name]?.startLine ?? node.sourceCodeLocation?.startLine ?? 1);
      if (attr.name.startsWith('on') && attr.value) fragments.push({ text: `function ${wrapper('html_event_' + attr.name)}() {\n${attr.value}\n}`, line: line - 2 });
      const executableUrl = (['href', 'action', 'formaction'].includes(attr.name) && !['link', 'base'].includes(node.tagName)) ||
        (attr.name === 'src' && ['iframe', 'frame'].includes(node.tagName));
      if (executableUrl && attr.value) {
        const url = new URL(attr.value, 'https://static-census.invalid/');
        if (!resourceSchemes.has(url.protocol)) {
          const reader = executableSchemes.get(url.protocol);
          try {
            if (!reader) throw new Error('Unsupported URL scheme in executable-source census');
            const body = reader(url);
            fragments.push({ text: `function ${wrapper('html_url')}() {\n${body}\n}`, line: line - 2 });
          } catch (error) {
            if (!onOpaque) throw error;
            onOpaque(['opaque-url-source', attr.value], line);
          }
        }
      }
      if (attr.name === 'srcdoc' && attr.value) fragments.push(...htmlSources(attr.value, depth + 1, line - 1, resolveScript, onOpaque));
    }
    for (const child of node.childNodes ?? []) visit(child);
    if (node.content) visit(node.content);
  }
  visit(document);
  return fragments;
}

function propertyResolver(file) {
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
  return keyOf;
}

function scanJavaScript(path, text, occurrences, lineOffset = 0, sharedResolver = null) {
  const lowerPath = path.toLowerCase();
  const file = ts.createSourceFile(path, text, ts.ScriptTarget.Latest, true,
    lowerPath.endsWith('.tsx') ? ts.ScriptKind.TSX : lowerPath.endsWith('.jsx') ? ts.ScriptKind.JSX : /\.[mc]?ts$/.test(lowerPath) ? ts.ScriptKind.TS : ts.ScriptKind.JS);
  if (file.parseDiagnostics.length) throw new Error(`${path}: source parse failed: ${file.parseDiagnostics.map(d => ts.flattenDiagnosticMessageText(d.messageText, ' ')).join('; ')}`);
  const rows = [];
  const structural = new WeakMap();
  const keyOf = sharedResolver ?? propertyResolver(file);
  function name(node) {
    if (node.name && (ts.isIdentifier(node.name) || ts.isStringLiteral(node.name))) return node.name.text;
    if (node.parent && ts.isVariableDeclaration(node.parent)) return ts.isIdentifier(node.parent.name) ? node.parent.name.text : stable(node.parent.name);
    if (node.parent && ts.isPropertyAssignment(node.parent)) return ts.isIdentifier(node.parent.name) ? node.parent.name.text : stable(node.parent.name);
    return '<callback>';
  }
  function stable(node) {
    return structure(node).fingerprint;
  }
  function structure(root) {
    if (structural.has(root)) return structural.get(root);
    // Merkle fingerprints/features visit a subtree once, rather than rescanning
    // its complete spelling for every ancestor expression in a minified bundle.
    const pending = [[root, false]];
    while (pending.length) {
      const [node, visited] = pending.pop();
      if (structural.has(node)) continue;
      const children = [];
      ts.forEachChild(node, child => { children.push(child); });
      if (!visited) {
        pending.push([node, true]);
        for (const child of children) if (!structural.has(child)) pending.push([child, false]);
        continue;
      }
      let value = typeof node.text === 'string' ? node.text : '';
      if (ts.isNumericLiteral(node)) value = String(Number(node.text.replaceAll('_', '')));
      if (ts.isBigIntLiteral(node)) value = String(BigInt(node.text.replaceAll('_', '').replace(/n$/, ''))) + 'n';
      let features = (domain.test(value) ? 1 : 0) |
        (/adjacen|\badj\b|\bnbrs?\b|\bqueue\b|\bvisited\b|\bneighbou?rs\b/i.test(value) ? 2 : 0) |
        (/\d/.test(value) ? 4 : 0) |
        (/Critical|Excellent|Good|Poor|READY|GO|risk|watch|healthy/.test(value) ? 8 : 0);
      const hashes = [];
      for (const child of children) {
        const entry = structural.get(child);
        hashes.push(entry.fingerprint); features |= entry.features;
      }
      const declarationFlags = node.flags & (ts.NodeFlags.Let | ts.NodeFlags.Const | ts.NodeFlags.Using | ts.NodeFlags.AwaitUsing);
      structural.set(node, {fingerprint: hash(JSON.stringify([node.kind, declarationFlags, value, hashes])), features});
    }
    return structural.get(root);
  }
  function literal(node) {
    return ts.isLiteralExpression(node) || [ts.SyntaxKind.TrueKeyword, ts.SyntaxKind.FalseKeyword, ts.SyntaxKind.NullKeyword].includes(node.kind) ||
      (ts.isPrefixUnaryExpression(node) && ts.isNumericLiteral(node.operand));
  }
  function returned(expression, symbol) {
    function visit(child) {
      if (ts.isFunctionLike(child)) return; // its own return is visited in its own scope
      if (ts.isBinaryExpression(child) && comparisonOperators.has(child.operatorToken.kind) && (!literal(child.left) || !literal(child.right))) emit(child, symbol, 'returned-comparison');
      ts.forEachChild(child, visit);
    }
    visit(expression);
    function verdict(node) {
      if (ts.isParenthesizedExpression(node)) return verdict(node.expression);
      if ([ts.SyntaxKind.TrueKeyword, ts.SyntaxKind.FalseKeyword].includes(node.kind)) return true;
      if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) return verdictReturns.has(node.text.toLowerCase().replaceAll('_', '-'));
      if (ts.isIdentifier(node)) return verdictName.test(node.text.replace(/^_+/, ''));
      if (ts.isPropertyAccessExpression(node)) return verdictName.test(node.name.text.replace(/^_+/, ''));
      if (ts.isCallExpression(node)) return verdict(node.expression);
      if (ts.isConditionalExpression(node)) return verdict(node.whenTrue) || verdict(node.whenFalse);
      if (ts.isBinaryExpression(node) && [ts.SyntaxKind.AmpersandAmpersandToken, ts.SyntaxKind.BarBarToken, ts.SyntaxKind.QuestionQuestionToken].includes(node.operatorToken.kind)) return verdict(node.left) || verdict(node.right);
      return false;
    }
    if (verdict(expression)) emit(expression, symbol, 'verdict-return');
  }
  function emit(node, symbol, rule) {
    const fingerprint = hash(stable(node)), key = `${symbol}:${rule}:${fingerprint}`;
    const occurrence = (occurrences.get(key) ?? 0) + 1; occurrences.set(key, occurrence);
    rows.push({ path, symbol, rule, fingerprint, occurrence,
      line: lineOffset + file.getLineAndCharacterOfPosition(node.getStart(file)).line + 1,
      expression: node.getText(file).replace(/\s+/g, ' ').slice(0, 240) });
  }
  function walk(node, scope = '<module>') {
    const functionLike = ts.isFunctionLike(node);
    const own = functionLike ? name(node) : null;
    const symbol = functionLike ? (scope === '<module>' ? own : `${scope}.${own}`) : scope;
    if (functionLike && ownerName.test(own)) emit(node.name ?? node.parent?.name ?? node, symbol, 'analysis-symbol');
    if (functionLike && verdictName.test(own.replace(/^_+/, ''))) emit(node.name ?? node.parent?.name ?? node, symbol, 'verdict-symbol');
    if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name) && verdictName.test(node.name.text.replace(/^_+/, ''))) emit(node.name, symbol, 'verdict-symbol');
    if (ts.isArrowFunction(node) && !ts.isBlock(node.body)) returned(node.body, symbol);
    if (ts.isReturnStatement(node) && node.expression) {
      returned(node.expression, symbol);
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
      if (['reduce', 'reduceRight', 'some', 'every', 'count', 'countBy', 'groupBy', 'sum', 'sumBy', 'mean', 'average'].includes(called)) emit(node, symbol, 'aggregate');
      if (['bfs', 'dfs', 'shortestPath', 'dijkstra', 'reachable', 'floodFill'].includes(called)) emit(node, symbol, 'graph-call');
      if (['eval', 'Function', 'exec', 'compile'].includes(called)) emit(node, symbol, 'dynamic-code');
      if (called === '__atlas_opaque_script_source__') emit(node, symbol, 'opaque-script-source');
      if (callee.kind === ts.SyntaxKind.ImportKeyword && (!node.arguments.length || !(ts.isStringLiteral(node.arguments[0]) || ts.isNoSubstitutionTemplateLiteral(node.arguments[0])))) emit(node, symbol, 'dynamic-module');
      if (ts.isPropertyAccessExpression(callee) && ['Reflect', 'Object'].includes(callee.expression.getText(file)) && ['get', 'getOwnPropertyDescriptor'].includes(called) && ['length', 'size'].includes(keyOf(node.arguments[1]))) emit(node, symbol, 'count');
      if (['push', 'pop', 'shift', 'unshift', 'add', 'set'].includes(called)) emit(node, symbol, 'collection-update');
      if (ts.isPropertyAccessExpression(callee) && callee.name.text === 'keys' && callee.expression.getText(file) === 'Object') emit(node, symbol, 'count-keys');
    }
    if (ts.isNewExpression(node) && node.expression.getText(file) === 'Function') emit(node, symbol, 'dynamic-code');
    if (ts.isBinaryExpression(node)) {
      const op = node.operatorToken.kind;
      if (op === ts.SyntaxKind.SlashToken && !literal(node.left) && !literal(node.right)) emit(node, symbol, 'ratio-arithmetic');
      if (op === ts.SyntaxKind.EqualsToken && ts.isBinaryExpression(node.right) && [ts.SyntaxKind.PlusToken, ts.SyntaxKind.MinusToken].includes(node.right.operatorToken.kind) && stable(node.right.left) === stable(node.left)) emit(node, symbol, 'counter-update');
      if (op === ts.SyntaxKind.EqualsToken && ts.isElementAccessExpression(node.left) && ts.isBinaryExpression(node.right) && node.right.operatorToken.kind === ts.SyntaxKind.PlusToken) emit(node, symbol, 'indexed-counter-update');
      if ([ts.SyntaxKind.BarBarToken, ts.SyntaxKind.QuestionQuestionToken].includes(op) && ts.isNumericLiteral(node.right) && node.right.text === '0' && (structure(node.left).features & 1)) emit(node, symbol, 'fact-default-zero');
      if ([ts.SyntaxKind.GreaterThanToken, ts.SyntaxKind.GreaterThanEqualsToken, ts.SyntaxKind.LessThanToken, ts.SyntaxKind.LessThanEqualsToken].includes(op)
          && (structure(node).features & 4)) emit(node, symbol, 'fact-threshold');
      if ([ts.SyntaxKind.PlusEqualsToken, ts.SyntaxKind.MinusEqualsToken].includes(op)) emit(node, symbol, 'counter-update');
      if ([ts.SyntaxKind.PlusToken, ts.SyntaxKind.MinusToken, ts.SyntaxKind.AsteriskToken, ts.SyntaxKind.SlashToken].includes(op)
          && (structure(node).features & 1)) emit(node, symbol, 'fact-arithmetic');
    }
    if ((ts.isPrefixUnaryExpression(node) || ts.isPostfixUnaryExpression(node)) &&
        [ts.SyntaxKind.PlusPlusToken, ts.SyntaxKind.MinusMinusToken].includes(node.operator)) emit(node, symbol, 'counter-update');
    if (ts.isConditionalExpression(node) && ((structure(node.whenTrue).features | structure(node.whenFalse).features) & 8)) emit(node.condition, symbol, 'fact-decision');
    if ((ts.isForStatement(node) || ts.isForOfStatement(node) || ts.isForInStatement(node) || ts.isWhileStatement(node) || ts.isDoStatement(node)) &&
        (structure(node).features & 2)) emit(node, symbol, 'graph-traversal');
    ts.forEachChild(node, child => walk(child, symbol));
  }
  walk(file);
  return rows;
}

export function scan(path, text) {
  const occurrences = new Map();
  if (!browserDocument(path)) return scanJavaScript(path, text, occurrences);
  const fragments = htmlSources(text, 0, 0, value => scriptIsClosed(path, value));
  // Classic scripts and inline handlers share document scope. Bind static count
  // property aliases across every fragment, then retain each fragment's source line.
  const whole = ts.createSourceFile(path, fragments.map(fragment => fragment.text).join('\n'), ts.ScriptTarget.Latest, true, ts.ScriptKind.JS);
  const resolver = propertyResolver(whole);
  return fragments.flatMap(fragment => scanJavaScript(path, fragment.text, occurrences, fragment.line, resolver));
}

const comparisonOperators = new Set([ts.SyntaxKind.EqualsEqualsToken, ts.SyntaxKind.EqualsEqualsEqualsToken,
  ts.SyntaxKind.ExclamationEqualsToken, ts.SyntaxKind.ExclamationEqualsEqualsToken, ts.SyntaxKind.GreaterThanToken,
  ts.SyntaxKind.GreaterThanEqualsToken, ts.SyntaxKind.LessThanToken, ts.SyntaxKind.LessThanEqualsToken]);

function tokenValue(scanner, kind) {
  if (kind === ts.SyntaxKind.NumericLiteral) return String(Number(scanner.getTokenValue().replaceAll('_', '')));
  if (kind === ts.SyntaxKind.BigIntLiteral) return String(BigInt(scanner.getTokenValue().replaceAll('_', '').replace(/n$/, ''))) + 'n';
  if ([ts.SyntaxKind.StringLiteral, ts.SyntaxKind.NoSubstitutionTemplateLiteral, ts.SyntaxKind.Identifier].includes(kind)) return scanner.getTokenValue();
  return scanner.getTokenText();
}

const compiledPaths = new Set(input.compiled ?? []);
const sourcePaths = new Set([...(input.sources ?? []).map(source => source.path), ...compiledPaths]);
function scriptIsClosed(path, value) {
  value = value.trim();
  const url = new URL(value, 'https://static-census.invalid/');
  if (!['http:', 'https:'].includes(url.protocol)) return false;
  if (url.origin !== 'https://static-census.invalid') return true; // Third-party dependency, not repository source.
  const name = decodeURIComponent(value.split(/[?#]/)[0]);
  let folder = posix.dirname(path);
  for (;;) {
    const candidate = posix.normalize(posix.join(folder, name.replace(/^\//, '')));
    if (sourcePaths.has(candidate)) return true;
    if (!name.startsWith('/') || folder === '.') break;
    folder = posix.dirname(folder);
  }
  return false;
}

function tokenStreams(path, text, symbol = '<forbidden-pattern>', lineOffset = 0, depth = 0) {
  if (depth > 8) throw new Error('Generated payload exceeds static census depth');
  const lowerPath = path.toLowerCase();
  const file = ts.createSourceFile(path, text, ts.ScriptTarget.Latest, true,
    lowerPath.endsWith('.tsx') ? ts.ScriptKind.TSX : lowerPath.endsWith('.jsx') ? ts.ScriptKind.JSX : /\.[mc]?ts$/.test(lowerPath) ? ts.ScriptKind.TS : ts.ScriptKind.JS);
  const masks = new Map(), payloads = [];
  function collect(node) {
    if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) {
      masks.set(node.getStart(file), {end: node.end, text: node.text});
      payloads.push({text: node.text, line: lineOffset + file.getLineAndCharacterOfPosition(node.getStart(file)).line});
      return;
    }
    if (ts.isTemplateExpression(node)) {
      masks.set(node.getStart(file), {end: node.end, text: '<interpolated-payload>'});
      payloads.push({text: node.head.text + node.templateSpans.map(span => '__census_interpolation__' + span.literal.text).join(''),
        line: lineOffset + file.getLineAndCharacterOfPosition(node.getStart(file)).line});
    }
    if (ts.isRegularExpressionLiteral(node)) masks.set(node.getStart(file), {end: node.end, text: null});
    if (ts.isJsxText(node)) masks.set(node.pos, {end: node.end, text: null});
    ts.forEachChild(node, collect);
  }
  collect(file);
  const ranges = [...masks].map(([start, mask]) => ({start, ...mask}))
    .filter(mask => mask.end > mask.start).sort((left, right) => left.start - right.start || right.end - left.end);
  let rangeIndex = 0;
  const scanner = ts.createScanner(ts.ScriptTarget.Latest, true, file.languageVariant, text);
  const tokens = [];
  for (let kind = scanner.scan(); kind !== ts.SyntaxKind.EndOfFileToken; kind = scanner.scan()) {
    const start = scanner.getTokenPos();
    while (rangeIndex < ranges.length && ranges[rangeIndex].end <= start) rangeIndex++;
    const candidate = ranges[rangeIndex];
    const mask = candidate && candidate.start <= start && start < candidate.end ? candidate : null;
    const line = lineOffset + file.getLineAndCharacterOfPosition(start).line + 1;
    if (mask) {
      if (mask.text !== null) tokens.push(['string', mask.text, line]);
      scanner.setTextPos(mask.end);
      continue;
    }
    const type = kind === ts.SyntaxKind.Identifier ? 'name' : kind === ts.SyntaxKind.NumericLiteral ? 'number' : 'op';
    tokens.push([type, tokenValue(scanner, kind), line]);
  }
  const streams = [{path, symbol, tokens}];
  for (const payload of payloads) {
    if (!/len|sum|Counter|length|size|filter|eval|exec|Function|queue|visited|adjacency|neighbors|neighbours|[<>]/.test(payload.text)) continue;
    streams.push(...payloadStreams(path, payload.text, payload.line, depth + 1));
  }
  return streams;
}

function payloadStreams(path, text, line = 0, depth = 0) {
  try {
    if (/<(?:!doctype|html|script|body|div|button|iframe)\b/i.test(text)) {
      const opaque = (descriptor, sourceLine) => {
        const fingerprint = hash(JSON.stringify(descriptor)), key = `${path}:${fingerprint}`;
        const occurrence = (generatedOpaqueOccurrences.get(key) ?? 0) + 1;
        generatedOpaqueOccurrences.set(key, occurrence);
        generatedOpaqueSites.push({path, symbol: '<generated-payload>', rule: 'opaque-generated-source',
          fingerprint, occurrence, line: sourceLine, expression: descriptor.join(' ').slice(0, 240)});
      };
      return htmlSources(text, depth, line, value => scriptIsClosed(path, value), opaque)
        .flatMap(fragment => tokenStreams(path, fragment.text, '<generated-payload>', fragment.line, depth + 1));
    }
    return tokenStreams(path, text, '<generated-payload>', line, depth);
  } catch (error) {
    throw new Error(`${path}:${line + 1}: generated-payload inspection failed`, {cause: error});
  }
}

function discoverSourcePaths(files, names) {
  const script = path => /\.(?:[mc]?[jt]s|[jt]sx)$/i.test(path);
  const paths = new Set(names), selected = new Set(), pending = [];
  const packages = new Map(), locks = new Map(), configurations = new Map(), optionCache = new Map();
  const absolute = path => '/repo/' + path;
  const relative = path => posix.normalize(path) === '/repo' ? '.' : posix.normalize(path).replace(/^\/repo\//, '');
  for (const [path, text] of Object.entries(files)) {
    if (path.endsWith('package.json')) packages.set(posix.dirname(path), JSON.parse(text));
    if (path.endsWith('package-lock.json')) locks.set(posix.dirname(path), JSON.parse(text));
    if (/(?:tsconfig|jsconfig).*\.json$/.test(path)) {
      const parsed = ts.parseConfigFileTextToJson(path, text);
      if (parsed.error) throw new Error('Cannot parse module-resolution configuration: ' + path);
      configurations.set(path, parsed.config);
    }
  }
  function options(path, visiting = new Set()) {
    if (optionCache.has(path)) return optionCache.get(path);
    if (visiting.has(path)) throw new Error('Cyclic module-resolution configuration');
    visiting.add(path);
    const config = configurations.get(path), parentOptions = {};
    for (const parent of config.extends ? Array.isArray(config.extends) ? config.extends : [config.extends] : []) {
      const base = posix.normalize(posix.join(posix.dirname(path), parent));
      const resolved = configurations.has(base) ? base : base + '.json';
      if (!configurations.has(resolved)) throw new Error('Unclosed module-resolution configuration: ' + parent);
      Object.assign(parentOptions, options(resolved, new Set(visiting)));
    }
    const converted = ts.convertCompilerOptionsFromJson(config.compilerOptions ?? {}, absolute(posix.dirname(path)));
    if (converted.errors.length) throw new Error('Invalid module-resolution configuration: ' + path);
    const value = {moduleResolution: ts.ModuleResolutionKind.Bundler, allowJs: true, resolveJsonModule: true, ...parentOptions, ...converted.options};
    if (config.compilerOptions?.paths) value.pathsBasePath = absolute(posix.dirname(path));
    optionCache.set(path, value); return value;
  }
  function packageFor(path) {
    let folder = posix.dirname(path);
    for (;;) {
      if (packages.has(folder)) return folder;
      if (folder === '.') return null;
      folder = posix.dirname(folder);
    }
  }
  const browserRoots = [...packages].filter(([_root, pkg]) => {
    const deps = {...pkg.dependencies, ...pkg.devDependencies, ...pkg.peerDependencies};
    return pkg.browser || ['react-dom', 'vite', 'vinext', 'next', 'webpack', 'vue', 'svelte'].some(name => name in deps);
  }).map(([root]) => root);
  // A directory named build can contain authored build tools (as in the
  // reference project). Compiler-declared output directories are generated;
  // generic build-named source is fully inspected rather than silently skipped.
  const outputRoots = [...configurations.keys()].map(path => options(path))
    .filter(opts => opts.outDir && !opts.noEmit).map(opts => relative(opts.outDir).replace(/\/$/, '') + '/');
  const generated = new Set([...paths].filter(path =>
    /(?:^|\/)(?:dist|dist-hub|\.next)(?:\/|$)/.test(path) || outputRoots.some(root => path.startsWith(root))));
  const authored = path => !generated.has(path) && !/(?:^|\/)(?:node_modules|test|tests|__tests__|fixtures)(?:\/|$)/.test(path) && !/\.(?:test|spec)\./.test(path);
  for (const path of paths) {
    if (browserDocument(path) || (script(path) && authored(path) && browserRoots.some(root => path.startsWith(root + '/')))) pending.push(path);
  }
  const directories = new Set(['.']);
  for (const path of paths) {
    let folder = posix.dirname(path);
    while (folder !== '.') { directories.add(folder); folder = posix.dirname(folder); }
  }
  const host = {
    fileExists: path => paths.has(relative(path)),
    readFile: path => files[relative(path)],
    directoryExists: directory => directories.has(relative(directory).replace(/\/$/, '')),
    getCurrentDirectory: () => '/repo',
    realpath: path => path,
  };
  function variants(stem) {
    const matches = [];
    const base = stem.replace(/\.(?:[mc]?js|jsx)$/, '');
    for (const candidate of [stem, ...['.ts', '.tsx', '.mts', '.cts', '.js', '.jsx', '.mjs', '.cjs', '.d.ts'].map(ext => base + ext),
      ...['index.ts', 'index.tsx', 'index.js', 'index.jsx', 'index.mjs', 'index.cjs'].map(name => posix.join(stem, name))]) {
      if (paths.has(candidate) && script(candidate)) matches.push(candidate);
    }
    return matches;
  }
  function dependency(from, original, html = false) {
    if (html) original = original.trim();
    if (/^(?:https?:|node:|virtual:)/.test(original) || builtinModules.includes(original)) return [];
    if (/^[a-z][a-z\d+.-]*:/i.test(original)) throw new Error('Unsupported executable module source: ' + original);
    const specifier = decodeURIComponent(original.split(/[?#]/)[0]);
    const found = new Set();
    if (html || specifier.startsWith('.') || specifier.startsWith('/')) {
      let folder = posix.dirname(from);
      for (;;) {
        for (const path of variants(posix.normalize(posix.join(folder, specifier.replace(/^\//, ''))))) found.add(path);
        if (!html || !specifier.startsWith('/') || folder === '.') break;
        folder = posix.dirname(folder);
      }
    }
    const root = packageFor(from);
    const configs = [...configurations.keys()].filter(path => root === null || path.startsWith(root + '/'));
    for (const config of [null, ...configs]) {
      const opts = config === null ? {moduleResolution: ts.ModuleResolutionKind.Bundler, allowJs: true, resolveJsonModule: true} : options(config);
      const resolved = ts.resolveModuleName(specifier, absolute(from), opts, host).resolvedModule?.resolvedFileName;
      if (resolved && script(relative(resolved))) found.add(relative(resolved));
    }
    if (found.size) return [...found];
    // Data/style imports contain no executable module. Their bytes are still
    // governed by existing product/build contracts, not parsed as JavaScript.
    if (/\.(?:css|scss|sass|less|json|svg|png|jpe?g|webp|woff2?|ttf|wasm)$/.test(specifier)) return [];
    const packageName = specifier.startsWith('@') ? specifier.split('/').slice(0, 2).join('/') : specifier.split('/')[0];
    for (const [folder, pkg] of packages) {
      if (pkg.name === packageName) return [...paths].filter(path => path.startsWith(folder + '/') && script(path));
    }
    for (const [folder, lock] of locks) {
      if (root !== null && folder !== root) continue;
      const entries = Object.entries(lock.packages ?? {}).filter(([name]) => name === 'node_modules/' + packageName || name.endsWith('/node_modules/' + packageName));
      for (const [_name, record] of entries) {
        if (record.link || record.resolved?.startsWith('file:')) {
          const target = posix.normalize(posix.join(folder, (record.resolved ?? '').replace(/^file:/, '')));
          const local = [...paths].filter(path => path.startsWith(target + '/') && script(path));
          if (!local.length) throw new Error('Unclosed file-linked module source: ' + packageName);
          return local;
        }
      }
      if (entries.length) return []; // pinned third-party install graph, not repository source
    }
    for (const pkg of root === null ? packages.values() : [packages.get(root)]) {
      if (Object.hasOwn({...pkg.dependencies, ...pkg.devDependencies, ...pkg.peerDependencies, ...pkg.optionalDependencies}, packageName)) return [];
    }
    throw new Error(`Unclosed repository module edge: ${from} -> ${original}`);
  }
  while (pending.length) {
    const path = pending.pop();
    if (selected.has(path) || (generated.has(path) && !browserDocument(path))) continue;
    if (!(path in files)) throw new Error('Executable source is unavailable: ' + path);
    selected.add(path);
    let fragments;
    if (browserDocument(path)) {
      fragments = htmlSources(files[path], 0, 0, value => {
        pending.push(...dependency(path, value, true)); return true;
      });
    } else fragments = [{text: files[path]}];
    for (const fragment of fragments) {
      const imports = ts.preProcessFile(fragment.text, true, true);
      for (const imported of [...imports.importedFiles, ...imports.referencedFiles]) pending.push(...dependency(path, imported.fileName));
      const file = ts.createSourceFile(path, fragment.text, ts.ScriptTarget.Latest, true);
      const visit = node => {
        if (ts.isCallExpression(node) && ts.isPropertyAccessExpression(node.expression) &&
            ['glob', 'globEager'].includes(node.expression.name.text) && ts.isMetaProperty(node.expression.expression) &&
            node.expression.expression.keywordToken === ts.SyntaxKind.ImportKeyword) {
          const argument = node.arguments[0];
          const patterns = argument && ts.isArrayLiteralExpression(argument) ? [...argument.elements] : [argument];
          for (const pattern of patterns) {
            if (!pattern || !(ts.isStringLiteral(pattern) || ts.isNoSubstitutionTemplateLiteral(pattern))) throw new Error('Unclosed module glob');
            if (pattern.text.startsWith('!')) continue; // conservative union; exclusions cannot hide a positive edge
            const root = pattern.text.startsWith('/') ? packageFor(path) ?? '.' : posix.dirname(path);
            const target = posix.normalize(posix.join(root, pattern.text.replace(/^\//, '')));
            const wildcard = target.search(/[*?{\[]/);
            if (wildcard < 0) pending.push(...dependency(path, pattern.text));
            else {
              const prefix = target.slice(0, wildcard);
              const folder = prefix.endsWith('/') ? prefix.slice(0, -1) : posix.dirname(prefix);
              // A conservative directory union closes every glob match without
              // duplicating the bundler's filename-pattern grammar.
              pending.push(...[...paths].filter(candidate => script(candidate) && (folder === '.' || candidate.startsWith(folder + '/'))));
            }
          }
        }
        if (ts.isNewExpression(node) && ts.isIdentifier(node.expression) && node.expression.text === 'URL' && node.arguments?.length && ts.isStringLiteral(node.arguments[0])) {
          const value = node.arguments[0].text;
          if (/\.(?:[mc]?[jt]s|[jt]sx)(?:[?#]|$)/.test(value)) pending.push(...dependency(path, value));
        }
        if (ts.isCallExpression(node) && (node.expression.kind === ts.SyntaxKind.ImportKeyword || (ts.isIdentifier(node.expression) && node.expression.text === 'require'))) {
          if (node.arguments.length && (ts.isStringLiteral(node.arguments[0]) || ts.isNoSubstitutionTemplateLiteral(node.arguments[0]))) {
            pending.push(...dependency(path, node.arguments[0].text));
          } else {
            // A dynamic selector can reach any authored module class in the
            // repository; do not limit it to this package's current src folder.
            pending.push(...[...paths].filter(candidate => script(candidate) && authored(candidate) && browserRoots.some(root => candidate.startsWith(root + '/'))));
          }
        }
        ts.forEachChild(node, visit);
      };
      visit(file);
    }
  }
  return {paths: [...selected].sort(), generated: [...generated].filter(path => script(path) || browserDocument(path)).sort()};
}

if (input.mode === 'discover') {
  process.stdout.write(JSON.stringify(discoverSourcePaths(input.files, input.names ?? Object.keys(input.files))));
  process.exit(0);
}

const sites = [], streams = [];
for (const source of input.sources ?? []) {
  process.stderr.write('DEBT_AST_START ' + source.path + '\n');
  sites.push(...scan(source.path, source.text));
  process.stderr.write('DEBT_LEX_START ' + source.path + '\n');
  const observed = browserDocument(source.path)
    ? htmlSources(source.text, 0, 0, value => scriptIsClosed(source.path, value)).flatMap(fragment => tokenStreams(source.path, fragment.text, '<forbidden-pattern>', fragment.line))
    : tokenStreams(source.path, source.text);
  streams.push(...observed);
  process.stderr.write('DEBT_FILE_DONE ' + source.path + '\n');
}
for (const payload of input.payloads ?? []) streams.push(...payloadStreams(payload.path, payload.text, payload.line));
sites.push(...generatedOpaqueSites);
process.stdout.write(JSON.stringify({sites, streams}));
