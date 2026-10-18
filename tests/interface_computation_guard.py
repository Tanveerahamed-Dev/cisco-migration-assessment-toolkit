"""ADR 0008 static debt census. Application source is parsed as data, never imported.

This ratchets a closed, named set of detected computation forms, not absence of
computation. Undetected forms require review and are not certified absent.
Existing presentation/infrastructure calculations are conservative exact-site
allowances, not proof of duplicate business logic.
"""
from __future__ import annotations

import ast
import base64
from collections import Counter
import hashlib
import gzip
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

from interface_computation_lex import lexical_counter, lexical_sites, python_source, python_stream, string_payloads
from interface_computation_sources import BROWSER_DOCUMENT_SUFFIXES, SCRIPT_SUFFIXES, compiled_coverage, python_closure, python_module, role_required

ROOT = Path(__file__).resolve().parents[1]
DETECTOR_ROOT = ROOT
REGISTRY = "docs/interface-computation-debt.json"
ORIGIN = "fdd6a7de9b9b2e51fccc54ece5a7b77f6c6a44b1"
SCHEMA = "interface-computation-debt/4"
LEGACY_V3_REGISTER_HEAD = "92490340e3c55c34c7a8d26e878ee5de7c729601"
BOUNDARY_CATEGORIES = frozenset({"transport-bound", "response-identity", "cancellation", "ui-state"})
COLLISION_ADMISSION_CLASSES = frozenset({"transport-serialization", "response-shape-validation",
                                         "user-input-validation", "empty-state-presentation"})
ROLE_ORIGIN = "2efe2fd77a1e67ea3c298408141a466e65cf3945"  # Initial role proposal, pinned independently of future edits.
LEGACY_REGISTER_HEAD = "3d3bca015a24a1d3aeec19471d81ae277043cb48"
LEGACY_V2_REGISTER_HEAD = "2920e79b2a80093e16fb0d9982cb9baf29cebda1"
LEGACY_V3_OBSERVATION_HEAD = "7e0c540a8959fa51a4e3f498c19c727273f08855"
DOMAIN = re.compile(r"health|score|band|severit|readiness|verdict|gate|punch|lifecycle|endpoint|device|vlan|flow|route|causal|impact|blast|adjacen|neighbou?r|graph|topolog|coverage", re.I)
SYMBOL = re.compile(r"^_*(?:count|compute|calculate|recount|simulate|evaluate|classify|qualify|trace|counterfactual|worst_readiness|go_no_go|gate_for)(?:_|[A-Z]|$)")
VERDICTS = frozenset({"READY", "NOT READY", "CAUTION", "GO", "NO-GO", "CONDITIONAL GO", "Critical", "Excellent", "Good", "Fair", "Poor", "ok", "watch", "risk", "crit", "healthy", "permit", "deny", "allow", "block", "reached", "unreachable"})
VERDICT_NAME = re.compile(r"^(?:can|could|should|is|has|may|must|allow|deny|permit|block|ready|safe|eligible|valid|approved|accepted|rejected|blocked|allowed|denied)(?:_|[A-Z]|$)|(?:^|_)(?:verdict|decision|readiness|ready|allowed|denied|eligible|gate|go_no_go|can_cut_over|ok|pass|fail)$")
VERDICT_RETURNS = {value.casefold().replace("_", "-") for value in (*VERDICTS, "yes", "no", "true", "false", "pass", "fail", "approved", "rejected", "blocked", "allowed", "valid", "invalid")}


def git(*args, input=None):
    return subprocess.check_output(["git", "-C", str(ROOT), *args], input=input)


def revision_sources(revision, *, roles_only=False):
    """Read immutable source blobs in one strict cat-file batch, never per-path processes.

    Names still come from the complete Git tree. Only executable/parser inputs
    and module declarations are materialized; large unrelated graph/data blobs
    are not loaded. Git object identity/type/size and batch framing must match.
    Immutable declaration/migration consumers can request the complete role
    class instead of materializing unrelated browser and helper blobs. Names
    still come from the whole tree; the fact-source census uses the full mode.
    Nothing is extracted to disk, imported, evaluated or content-normalized.
    """
    names, selected = [], {}
    for row in git("ls-tree", "-r", "-z", "--full-tree", revision).split(b"\0"):
        if not row:
            continue
        metadata, raw_path = row.split(b"\t", 1)
        mode, kind, oid = metadata.split()
        path = raw_path.decode("utf-8")
        names.append(path)
        wanted = ((role_required(path) or path.endswith(".atlas-role")) if roles_only else
                  (python_module(path) or path.endswith(".atlas-role")
                  or path.lower().endswith((*SCRIPT_SUFFIXES, *BROWSER_DOCUMENT_SUFFIXES))
                  or path.endswith(".json") and ("tsconfig" in path or "jsconfig" in path
                                                or path.endswith(("package.json", "package-lock.json")))))
        if wanted:
            if mode not in {b"100644", b"100755"} or kind != b"blob":
                raise ValueError("Refused nonregular immutable source: " + path)
            selected[path] = oid
    if not selected:
        return sorted(names), {}
    objects = sorted(set(selected.values()))
    batch = git("cat-file", "--batch", input=b"\n".join(objects) + b"\n")
    payloads, cursor = {}, 0
    for oid in objects:
        boundary = batch.find(b"\n", cursor)
        if boundary < 0:
            raise ValueError("Truncated immutable source batch header")
        header = batch[cursor:boundary].split()
        if len(header) != 3 or header[0] != oid or header[1] != b"blob" or not header[2].isdigit():
            raise ValueError("Unexpected immutable source batch object")
        size = int(header[2])
        start, end = boundary + 1, boundary + 1 + size
        if end >= len(batch) or batch[end:end + 1] != b"\n":
            raise ValueError("Truncated immutable source batch payload")
        payloads[oid] = batch[start:end]
        cursor = end + 1
    if cursor != len(batch):
        raise ValueError("Trailing immutable source batch bytes")
    return sorted(names), {path: payloads[oid] for path, oid in selected.items()}


def node_reply(payload):
    """Run the locked source parser; keep its refusal diagnostic visible in CI."""
    node = shutil.which("node")
    if not node:
        raise RuntimeError("Node is required for the interface AST/closure gate")
    try:
        reply = subprocess.run([node, str(DETECTOR_ROOT / ".github/scripts/interface_computation_ast.mjs")],
                               input=json.dumps(payload), cwd=DETECTOR_ROOT,
                               text=True, encoding="utf-8", capture_output=True, check=True, timeout=90)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        diagnostic = error.stderr or ""
        if isinstance(diagnostic, bytes):
            diagnostic = diagnostic.decode("utf-8", errors="replace")
        if diagnostic:
            print(diagnostic, file=sys.stderr)
        raise
    return json.loads(reply.stdout)


class SourceMap(dict):
    """Executable source plus compiled imports covered by a named hosted gate."""

    def __init__(self, sources, compiled=()):
        super().__init__(sources)
        self.compiled = sorted(compiled)


def source_map(revision=None):
    if revision:
        names, snapshot = revision_sources(revision)
        read = lambda path: snapshot[path].decode("utf-8")  # noqa: E731 - a frozen snapshot accessor
    else:
        names = git("ls-files", "-z", "--cached", "--others", "--exclude-standard").decode("utf-8").split("\0")
        read = lambda path: (ROOT / path).read_text(encoding="utf-8")  # noqa: E731 - live source remains uncached
    names = sorted(set(names) - {""})
    # The old fact ceiling predates role declarations. The independently pinned
    # role snapshot is immutable Git source, never current workspace guesses.
    role_names, role_read = None, None
    if revision and ROLE_ORIGIN:
        role_names, role_snapshot = revision_sources(ROLE_ORIGIN, roles_only=True)
        role_read = lambda path: role_snapshot[path].decode("utf-8")  # noqa: E731
    selected = python_closure(names, read, role_read, role_names)
    candidates = {path: read(path) for path in names if path.lower().endswith((*SCRIPT_SUFFIXES, *BROWSER_DOCUMENT_SUFFIXES))
                  or path.endswith(".json") and ("tsconfig" in path or "jsconfig" in path or path.endswith(("package.json", "package-lock.json")))}
    discovered = node_reply(dict(mode="discover", files=candidates, names=names)) if candidates else {"paths": [], "generated": []}
    compiled = compiled_coverage(names, read if not revision else lambda p: (ROOT / p).read_text(encoding="utf-8"), discovered["generated"])
    selected.update(path for path in discovered["paths"] if path not in compiled or path.lower().endswith(BROWSER_DOCUMENT_SUFFIXES))
    return SourceMap({path: read(path) for path in sorted(selected)}, compiled)


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def read_registry(text):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate debt registry key")
            result[key] = value
        return result

    def constant(_value):
        raise ValueError("Nonfinite debt registry value")

    return json.loads(text, object_pairs_hook=unique, parse_constant=constant)


def ast_form(value):
    """Version-neutral semantic AST, independent of ast.dump's debug formatting.

    Empty optional lists (such as 3.12's type_params) add no semantics. Nonempty
    new fields remain bound; literal None/False/zero and byte/complex values stay
    distinct. Locations and comments never enter the fingerprint.
    """
    if isinstance(value, ast.AST):
        return {"type": type(value).__name__, "fields": {
            key: ast_form(item) for key, item in ast.iter_fields(value)
            if not (isinstance(item, list) and not item)}}
    if isinstance(value, list):
        return [ast_form(item) for item in value]
    if isinstance(value, bytes):
        return {"bytes": value.hex()}
    if isinstance(value, complex):
        return {"complex": [value.real.hex(), value.imag.hex()]}
    if isinstance(value, float):
        return {"float": value.hex()}
    if value is Ellipsis:
        return {"literal": "ellipsis"}
    return value


def _python_literal(node):
    return isinstance(node, ast.Constant) or (isinstance(node, ast.UnaryOp) and isinstance(node.operand, ast.Constant))


def _python_return_verdict(value):
    if isinstance(value, ast.Constant):
        return type(value.value) is bool or (isinstance(value.value, str) and value.value.casefold().replace("_", "-") in VERDICT_RETURNS)
    if isinstance(value, ast.Name):
        return bool(VERDICT_NAME.search(value.id.lstrip("_")))
    if isinstance(value, ast.Attribute):
        return bool(VERDICT_NAME.search(value.attr.lstrip("_")))
    if isinstance(value, ast.Call):
        return _python_return_verdict(value.func)
    if isinstance(value, ast.IfExp):
        return _python_return_verdict(value.body) or _python_return_verdict(value.orelse)
    if isinstance(value, ast.BoolOp):
        return any(_python_return_verdict(child) for child in value.values)
    return False


class _PythonFactWalk(ast.NodeVisitor):
    def __init__(self, path, text, lines, offsets):
        self.path, self.text, self.lines, self.offsets = path, text, lines, offsets
        self.result, self.counts, self.scope = [], Counter(), "<module>"

    def segment(self, node):
        start = self.offsets[node.lineno - 1] + len(self.lines[node.lineno - 1].encode()[:node.col_offset].decode())
        end = self.offsets[node.end_lineno - 1] + len(self.lines[node.end_lineno - 1].encode()[:node.end_col_offset].decode())
        return self.text[start:end]

    def emit(self, node, rule, normalized=None):
        fingerprint = digest(normalized if normalized is not None else json.dumps(ast_form(node), sort_keys=True, separators=(",", ":")))
        key = (self.scope, rule, fingerprint)
        self.counts[key] += 1
        self.result.append(dict(path=self.path, symbol=self.scope, rule=rule, fingerprint=fingerprint,
                           occurrence=self.counts[key], line=node.lineno,
                           expression=self.segment(node).replace("\n", " ")[:240]))

    def visit_FunctionDef(self, node):
        old = self.scope
        self.scope = node.name if old == "<module>" else old + "." + node.name
        if SYMBOL.match(node.name):
            self.emit(node, "analysis-symbol", node.name)
        if VERDICT_NAME.search(node.name.lstrip("_")):
            self.emit(node, "verdict-symbol", node.name)
        self.generic_visit(node)
        self.scope = old

    visit_AsyncFunctionDef = visit_FunctionDef

    def returned(self, node):
        pending = [node]
        while pending:
            child = pending.pop()
            if isinstance(child, (ast.Lambda, ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if isinstance(child, ast.Compare) and any(not _python_literal(n) for n in (child.left, *child.comparators)):
                self.emit(child, "returned-comparison")
            pending.extend(ast.iter_child_nodes(child))

        if _python_return_verdict(node):
            self.emit(node, "verdict-return")

    def visit_Lambda(self, node):
        old = self.scope
        self.scope = old + ".<lambda>"
        self.returned(node.body)
        self.generic_visit(node)
        self.scope = old

    def visit_Call(self, node):
        name = node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else ""
        if name in {"len", "sum", "any", "all", "Counter", "mean", "average", "count", "count_by", "_count_by"}:
            self.emit(node, "aggregate")
        if name in {"bfs", "dfs", "shortest_path", "dijkstra", "reachable", "flood_fill"}:
            self.emit(node, "graph-call")
        if name in {"eval", "exec", "compile", "__import__"}:
            self.emit(node, "dynamic-code")
        if name in {"append", "extend", "pop", "popleft", "add", "update"}:
            self.emit(node, "collection-update")
        if name == "get" and len(node.args) > 1 and isinstance(node.args[1], ast.Constant) and node.args[1].value == 0 and DOMAIN.search(ast.unparse(node)):
            self.emit(node, "fact-default-zero")
        self.generic_visit(node)

    def visit_Return(self, node):
        if node.value is not None and any(isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value in VERDICTS for n in ast.walk(node.value)):
            self.emit(node.value, "fact-decision")
        if node.value is not None:
            self.returned(node.value)
        self.generic_visit(node)

    def visit_Compare(self, node):
        if any(isinstance(n, ast.Constant) and type(n.value) in (int, float) for n in ast.walk(node)):
            self.emit(node, "fact-threshold")
        self.generic_visit(node)

    def visit_BinOp(self, node):
        if isinstance(node.op, (ast.Div, ast.FloorDiv)) and not _python_literal(node.left) and not _python_literal(node.right):
            self.emit(node, "ratio-arithmetic")
        if isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv)) and DOMAIN.search(ast.unparse(node)):
            self.emit(node, "fact-arithmetic")
        self.generic_visit(node)

    def visit_AugAssign(self, node):
        if isinstance(node.op, (ast.Add, ast.Sub)):
            self.emit(node, "counter-update")
        self.generic_visit(node)

    def visit_Assign(self, node):
        for target in node.targets:
            for name in ast.walk(target):
                if isinstance(name, ast.Name) and VERDICT_NAME.search(name.id):
                    self.emit(name, "verdict-symbol", name.id)
        if isinstance(node.value, ast.BinOp) and isinstance(node.value.op, ast.Add):
            self.emit(node, "counter-update")
        self.generic_visit(node)

    def visit_IfExp(self, node):
        if re.search(r"Critical|Excellent|Good|Poor|READY|GO|risk|watch|healthy", ast.unparse(node.body) + ast.unparse(node.orelse)):
            self.emit(node.test, "fact-decision")
        self.generic_visit(node)

    def visit_AnnAssign(self, node):
        for target in ast.walk(node.target):
            if isinstance(target, ast.Name) and VERDICT_NAME.search(target.id):
                self.emit(target, "verdict-symbol", target.id)
        self.generic_visit(node)

    def visit_For(self, node):
        if re.search(r"\badj\b|\bnbrs?\b|\bqueue\b|\bvisited\b|adjacen|neighbou?rs", ast.unparse(node), re.I):
            self.emit(node, "graph-traversal")
        self.generic_visit(node)

    visit_While = visit_For
    visit_AsyncFor = visit_For


def python_sites(path, text):
    # A module-level visitor keeps per-source buffers on an acyclic instance,
    # rather than in a fresh local class's function closures/MRO cycle.
    text, lines, offsets = python_source(text)
    walker = _PythonFactWalk(path, text, lines, offsets)
    walker.visit(ast.parse(text, filename=path))
    return walker.result


def scan(sources):
    sites, javascript, payloads = [], [], []
    streams = []
    for path, text in sources.items():
        if python_module(path):
            sites.extend(python_sites(path, text))
            tree = ast.parse(text, filename=path)
            try:
                tokens = python_stream(text, tree)
            except Exception:
                print(f"{path}: Python token normalization failed", file=sys.stderr)
                raise
            streams.append(dict(path=path, symbol="<forbidden-pattern>", tokens=tokens))
            for payload, line in string_payloads(tree):
                if not re.search(r"len|sum|Counter|length|size|filter|eval|exec|Function|queue|visited|adjacency|neighbors|neighbours|[<>]", payload):
                    continue
                try:
                    payload_tree = ast.parse(payload)
                    tokens = python_stream(payload, payload_tree)
                except (SyntaxError, ValueError, IndentationError):
                    payloads.append(dict(path=path, text=payload, line=line - 1))
                else:
                    for token in tokens:
                        token[2] += line - 1
                    streams.append(dict(path=path, symbol="<generated-payload>", tokens=tokens))
        else:
            javascript.append(dict(path=path, text=text))
    if javascript or payloads:
        observed = node_reply(dict(sources=javascript, payloads=payloads, compiled=getattr(sources, "compiled", [])))
        sites.extend(observed["sites"])
        streams.extend(observed["streams"])
    occurrences = lexical_counter()
    for stream in streams:
        sites.extend(lexical_sites(stream["path"], stream["tokens"], stream["symbol"], digest, occurrences))
    return sorted(sites, key=identity)


def identity(row):
    return (row["path"], row["symbol"], row["rule"], row["fingerprint"], row["occurrence"])


def disposition(row):
    if row["path"].startswith("atlas-scope/") or row["path"].endswith("blast_radius_explorer.html"):
        return "retired-with-surface"
    return "legacy-site-review-required"


def proposal(sites, boundary=(), collisions=None):
    """Observe every site; preserve only already-declared, still-present boundary records.

    Unadmitted findings remain visible in sites. This proposal cannot authorize
    debt growth or a boundary admission; validation and independent review do that.
    """
    found = {identity(row) for row in sites}
    boundary_records(list(boundary))
    collision_rows = [] if collisions is None else collisions
    collision_records(collision_rows)
    if {identity(row) for row in boundary} & {identity(row) for row in collision_rows}:
        raise ValueError("Duplicate boundary identity across normal and collision sections")
    retained = [dict(row) for row in boundary if identity(row) in found]
    retained_collisions = [dict(row) for row in collision_rows if identity(row) in found]
    boundary_keys = {identity(row) for row in [*retained, *retained_collisions]}
    record = {"schema": SCHEMA, "origin": ORIGIN, "stage": "active",
            "boundary": retained,
            "sites": [{**{key: row[key] for key in ("path", "symbol", "rule", "fingerprint", "occurrence")},
                       "disposition": disposition(row)} for row in sites if identity(row) not in boundary_keys]}
    if collisions is not None:
        record["collisions"] = retained_collisions
    return record



LEXICAL_MARKERS = frozenset({"<forbidden-pattern>", "<generated-payload>"})


def lexical_rule_vocabulary(lexer_text=None, payload_text=None):
    """Derive the closed marker vocabulary from the frozen emission sites.

    Unresolvable emitter shapes fail closed. The Node-backed producer control
    independently checks the payload rule extraction; detector byte pins remain.
    """
    if lexer_text is None:
        lexer_text = (DETECTOR_ROOT / "tests/interface_computation_lex.py").read_text(encoding="utf-8")
    if payload_text is None:
        payload_text = (DETECTOR_ROOT / ".github/scripts/interface_computation_ast.mjs").read_text(encoding="utf-8")
    lexical = next(node for node in ast.parse(lexer_text).body
                   if isinstance(node, ast.FunctionDef) and node.name == "lexical_sites")
    calls = [node for node in ast.walk(lexical) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Name) and node.func.id == "emit"]
    if not calls or any(len(node.args) != 3 or node.keywords
                        or not isinstance(node.args[2], ast.Constant)
                        or type(node.args[2].value) is not str for node in calls):
        raise ValueError("Unresolvable lexical rule producer")
    rules = {node.args[2].value for node in calls}
    payloads = re.findall(
        r"generatedOpaqueSites\s*\.\s*push\s*\(\s*\{\s*path\s*,\s*symbol:\s*(['\"])([^'\"]+)\1\s*,\s*rule:\s*(['\"])([^'\"]+)\3\s*,",
        payload_text)
    pushes = re.findall(r"\bgeneratedOpaqueSites\s*\.\s*push\s*\(", payload_text)
    if not payloads or len(payloads) != len(pushes) or any(row[1] not in LEXICAL_MARKERS for row in payloads):
        raise ValueError("Unresolvable payload rule producer")
    return frozenset(rules | {row[3] for row in payloads})


LEXICAL_PRODUCER_RULES = lexical_rule_vocabulary()


def lexical_identity(key):
    """A marker alone is forgeable as a JavaScript string-literal method name."""
    return key[1] in LEXICAL_MARKERS and key[2] in LEXICAL_PRODUCER_RULES


def literal_verdict_fingerprints(current, candidates, current_sources=None):
    """Prove literal-only returns with the unchanged fingerprint producers.

    Full live sources avoid the census expression preview's truncation. Direct
    validate callers can supply complete expression previews instead; missing or
    unparseable previews provide no exception. No expression is executed.
    """
    paths = {key[0] for key in candidates if key[2] == "verdict-return"}
    if not paths:
        return set()
    expressions, javascript = set(), []
    sources = current_sources or {}
    for path in paths:
        full = path in sources
        texts = [sources[path]] if full else [row.get("expression", "") for row in current
                 if row["path"] == path and row["rule"] == "verdict-return"]
        for text in texts:
            if not text:
                continue
            if python_module(path):
                try:
                    tree = ast.parse(text if full else "def literal_probe():\n return " + text + "\n")
                except (SyntaxError, ValueError):
                    if full:
                        raise
                    continue
                for node in ast.walk(tree):
                    value = node.value if isinstance(node, ast.Return) else node.body if isinstance(node, ast.Lambda) else None
                    if isinstance(value, ast.Constant) and _python_return_verdict(value):
                        expressions.add(ast.get_source_segment(text if full else "def literal_probe():\n return " + text + "\n", value))
            else:
                javascript.append(dict(path=path, text=text if full else "function literal_probe() { return " + text + "; }",
                                       required=full, document=full and path.lower().endswith(BROWSER_DOCUMENT_SUFFIXES)))
    fingerprints = {row["fingerprint"] for expression in expressions
                    for row in python_sites("literal_probe.py", "def literal_probe():\n return " + expression + "\n")
                    if row["rule"] == "verdict-return"}
    if javascript:
        # This policy proof only identifies bare literal nodes. The existing
        # detector remains the sole owner of every resulting fingerprint.
        script = r"""
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
const require = createRequire(resolve(process.cwd(), 'atlas-scope/package.json'));
const ts = require('typescript');
if (ts.version !== '5.9.3') throw new Error('Literal policy proof requires the locked parser');
const inputs = JSON.parse(readFileSync(0, 'utf8'));
const parseHtml = inputs.some(input => input.document) ? (await import(pathToFileURL(require.resolve('parse5')).href)).parse : null;
function documentFragments(text, depth = 0) {
  if (depth > 8) throw new Error('Literal policy HTML depth exceeds the source contract');
  const fragments = [];
  function visit(node) {
    if (node.tagName === 'script') fragments.push((node.childNodes ?? []).filter(child => child.nodeName === '#text').map(child => child.value).join(''));
    for (const attr of node.attrs ?? []) {
      fragments.push(attr.value);
      try {
        const url = new URL(attr.value, 'https://static-census.invalid/');
        if (url.protocol === 'javascript:') fragments.push(decodeURIComponent(url.href.slice(url.protocol.length)));
      } catch { /* An unproved fragment creates no literal exception. */ }
      if (attr.name === 'srcdoc') fragments.push(...documentFragments(attr.value, depth + 1));
    }
    for (const child of node.childNodes ?? []) visit(child);
    if (node.content) visit(node.content);
  }
  visit(parseHtml(text));
  return fragments;
}
const literals = new Set();
for (const {path, text, required, document} of inputs) {
  const lower = path.toLowerCase();
  const kind = lower.endsWith('.tsx') ? ts.ScriptKind.TSX : lower.endsWith('.jsx') ? ts.ScriptKind.JSX : /\.[mc]?ts$/.test(lower) ? ts.ScriptKind.TS : ts.ScriptKind.JS;
  for (const fragment of document ? documentFragments(text) : [text]) {
  let file = ts.createSourceFile(path, fragment, ts.ScriptTarget.Latest, true, kind);
  if (file.parseDiagnostics.length && document) file = ts.createSourceFile(path, 'function literal_probe() {\n' + fragment + '\n}', ts.ScriptTarget.Latest, true, kind);
  if (file.parseDiagnostics.length) {
    if (required && !document) throw new Error('Literal policy source parse failed');
    continue;
  }
  function visit(node) {
    const value = ts.isReturnStatement(node) ? node.expression : ts.isArrowFunction(node) && !ts.isBlock(node.body) ? node.body : null;
    if (value && (ts.isStringLiteral(value) || ts.isNoSubstitutionTemplateLiteral(value) || [ts.SyntaxKind.TrueKeyword, ts.SyntaxKind.FalseKeyword].includes(value.kind))) literals.add(value.getText(file));
    ts.forEachChild(node, visit);
  }
  visit(file);
  }
}
process.stdout.write(JSON.stringify([...literals]));
"""
        node = shutil.which("node")
        if not node:
            raise RuntimeError("Node is required for the literal boundary policy proof")
        result = subprocess.run([node, "--input-type=module", "-e", script], input=json.dumps(javascript),
                                cwd=DETECTOR_ROOT, text=True, encoding="utf-8", capture_output=True, check=True, timeout=90)
        literals = json.loads(result.stdout)
        if literals:
            text = "\n".join("function literal_probe_" + str(index) + "() { return " + value + "; }"
                             for index, value in enumerate(literals))
            fingerprints.update(row["fingerprint"] for row in node_reply(dict(sources=[dict(path="literal_probe.ts", text=text)]))["sites"]
                                if row["rule"] == "verdict-return")
    return fingerprints


def boundary_records(rows):
    """Closed exact-site metadata, never a file/symbol/category-wide exemption."""
    fields = {"path", "symbol", "rule", "fingerprint", "occurrence", "category"}
    if not isinstance(rows, list) or any(not isinstance(row, dict) or set(row) != fields for row in rows):
        raise ValueError("Boundary records require closed exact sites and one category")
    for row in rows:
        if (any(type(row[key]) is not str or not row[key] for key in ("path", "symbol", "rule", "fingerprint"))
                or re.fullmatch(r"[0-9a-f]{64}", row["fingerprint"]) is None
                or type(row["occurrence"]) is not int or row["occurrence"] < 1
                or any("*" in row[key] for key in ("path", "symbol", "rule"))):
            raise ValueError("Boundary identities have malformed exact types")
        if type(row["category"]) is not str or row["category"] not in BOUNDARY_CATEGORIES:
            raise ValueError("Boundary category is missing or unknown")
        if row["rule"] == "dynamic-code":
            raise ValueError("Dynamic code can never be a boundary record")
        if row["symbol"] in LEXICAL_MARKERS and not lexical_identity(identity(row)):
            raise ValueError("Reserved lexical marker has a non-lexical boundary rule")
    keys = [identity(row) for row in rows]
    if len(keys) != len(set(keys)) or keys != sorted(keys):
        raise ValueError("Duplicate or unordered boundary sites")
    return {identity(row): row for row in rows}


def collision_records(rows):
    """Visible exact-site collision proposals, never automatic semantic approval."""
    boundary_fields = {"path", "symbol", "rule", "fingerprint", "occurrence", "category"}
    fields = boundary_fields | {"admission_class", "justification"}
    if not isinstance(rows, list) or any(not isinstance(row, dict) or set(row) != fields for row in rows):
        raise ValueError("Collision records require closed exact sites, admission class and justification")
    boundary_records([{key: row[key] for key in boundary_fields} for row in rows])
    for row in rows:
        if type(row["admission_class"]) is not str or row["admission_class"] not in COLLISION_ADMISSION_CLASSES:
            raise ValueError("Collision admission class is missing or unknown")
        text = row["justification"]
        if type(text) is not str or not text.strip() or text != text.strip() or text.splitlines() != [text]:
            raise ValueError("Collision justification must be nonblank and one line")
    return {identity(row): row for row in rows}


def boundary_sections(record):
    """Legacy omission means no collision exception; explicit malformed data refuses."""
    normal = boundary_records(record["boundary"])
    collisions = collision_records(record.get("collisions", []))
    if normal.keys() & collisions.keys():
        raise ValueError("Duplicate boundary identity across normal and collision sections")
    return {**normal, **collisions}, collisions


def require_retained_boundary_metadata(current, current_collisions, previous, previous_collisions):
    for key in current.keys() & previous.keys():
        if current[key]["category"] != previous[key]["category"]:
            raise ValueError("A retained boundary category changed")
        if (key in current_collisions) != (key in previous_collisions):
            raise ValueError("A retained boundary changed normal/collision section")
        if key in current_collisions and current_collisions[key] != previous_collisions[key]:
            raise ValueError("A retained collision admission changed")


def admission_base():
    """Use the immutable hosted event's PR base, not a caller-selected comparison.

    A main push rechecks the merged delta against its before SHA. Other contexts
    use HEAD's merge-base with main for retention only, never new admissions.
    Review approval is a separate human gate; this checks structural eligibility.
    """
    event_name = os.environ.get("GITHUB_EVENT_NAME")
    def retained_only():
        return git("merge-base", "HEAD", "origin/main").decode().strip(), False

    if event_name not in {"pull_request", "push"}:
        return retained_only()
    try:
        event = read_registry(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
        if event_name == "pull_request":
            if event["pull_request"]["base"]["ref"] != "main":
                return retained_only()
            if event["pull_request"]["base"]["repo"]["full_name"] != os.environ["GITHUB_REPOSITORY"]:
                raise ValueError("Boundary admission requires this repository's main PR base")
            base, head = event["pull_request"]["base"]["sha"], event["pull_request"]["head"]["sha"]
        else:
            if event["ref"] != "refs/heads/main":
                return retained_only()
            base, head = event["before"], event["after"]
        if any(type(value) is not str or re.fullmatch(r"[0-9a-f]{40}", value) is None
               or value == "0" * 40 for value in (base, head)):
            raise ValueError("Boundary PR/base identities are malformed")
    except (KeyError, TypeError, OSError, UnicodeError) as error:
        raise ValueError("Boundary PR/base context is missing or malformed") from error
    git("cat-file", "-e", base + "^{commit}")
    checkout = git("rev-parse", "HEAD").decode().strip()
    if checkout != head:
        parents = git("rev-list", "--parents", "-n", "1", "HEAD").decode().split()
        if (event_name != "pull_request" or checkout != os.environ.get("GITHUB_SHA")
                or parents != [checkout, base, head]):
            raise ValueError("Boundary PR/base event does not bind the checked-out source")
    return base, True


def legacy_v3_carried(commit):
    """An unchanged v3 continuation is not a new policy event or a v4 rollback."""
    blob = git("rev-parse", commit + ":" + REGISTRY).strip()
    carried = False
    for parent in git("rev-list", "--parents", "-n", "1", commit).decode().split()[1:]:
        entry = git("ls-tree", parent, "--", REGISTRY).split()
        if not entry:
            continue
        raw = read_registry(git("show", parent + ":" + REGISTRY))
        if raw.get("schema") not in {"interface-computation-debt/1", "interface-computation-debt/2",
                                     "interface-computation-debt/3"}:
            return False  # A v4/unknown parent cannot be downgraded via the other parent.
        if (entry[2] == blob and raw.get("schema") == "interface-computation-debt/3"
                and raw.get("stage") == "active" and raw.get("origin") == ORIGIN):
            carried = True
    return carried


def policy_record(commit, record, *, historical=True):
    """Read history without resetting the debt floor or reopening a legacy policy."""
    schema = record.get("schema")
    legacy_heads = {"interface-computation-debt/1": LEGACY_REGISTER_HEAD,
                    "interface-computation-debt/2": LEGACY_V2_REGISTER_HEAD}
    if schema in legacy_heads:
        if historical:
            git("merge-base", "--is-ancestor", commit, legacy_heads[schema])
        return None
    if schema == "interface-computation-debt/3" and record.get("stage") == "observation_required":
        if historical:
            git("merge-base", "--is-ancestor", commit, LEGACY_V3_OBSERVATION_HEAD)
        return None
    if schema == "interface-computation-debt/3":
        if historical:
            try:
                git("merge-base", "--is-ancestor", commit, LEGACY_V3_REGISTER_HEAD)
            except subprocess.CalledProcessError as error:
                if error.returncode != 1 or not legacy_v3_carried(commit):
                    raise
        if (set(record) != {"schema", "origin", "stage", "sites"}
                or record.get("origin") != ORIGIN or record.get("stage") != "active"):
            raise ValueError("An unauthorized legacy v3 policy appeared in history")
        return {**record, "schema": SCHEMA, "boundary": []}
    fields = {"schema", "origin", "stage", "sites", "boundary"}
    if (schema != SCHEMA or record.get("origin") != ORIGIN or record.get("stage") != "active"
            or set(record) not in (fields, fields | {"collisions"})):
        raise ValueError("An unauthorized debt policy/schema appeared in history")
    boundary_sections(record)
    return record


def validate(registry, current, origin, ancestors=(), *, base=None, base_sites=None,
             removed_boundary=(), historic_debt=(), allow_new_boundary=True, current_sources=None):
    fields = {"schema", "origin", "stage", "sites", "boundary"}
    if set(registry) not in (fields, fields | {"collisions"}) or registry["schema"] != SCHEMA or registry["origin"] != ORIGIN or registry["stage"] != "active":
        raise ValueError("Debt register requires source-bound active review")
    expected_keys = {"path", "symbol", "rule", "fingerprint", "occurrence", "disposition"}
    rows = registry["sites"]
    if not isinstance(rows, list) or any(not isinstance(row, dict) or set(row) != expected_keys for row in rows):
        raise ValueError("Debt entries are not closed exact call sites")
    if any(any(not isinstance(row[key], str) or not row[key] for key in ("path", "symbol", "rule", "fingerprint", "disposition"))
           or re.fullmatch(r"[0-9a-f]{64}", row["fingerprint"]) is None
           or type(row["occurrence"]) is not int or row["occurrence"] < 1 for row in rows):
        raise ValueError("Debt call-site identities have malformed exact types")
    keys = [identity(row) for row in rows]
    if len(set(keys)) != len(keys) or keys != sorted(keys):
        raise ValueError("Debt entries repeat or are not deterministically ordered")
    if any(row["disposition"] != disposition(row) for row in rows):
        raise ValueError("Debt disposition changed without its owner")
    boundary, collisions = boundary_sections(registry)
    ancestors = list(ancestors)
    registered, found, ceiling = set(keys), {identity(row) for row in current}, {identity(row) for row in origin}
    debt_history = registered | set(historic_debt)
    if base is not None:
        debt_history.update(identity(row) for row in base["sites"])
    if not registered <= ceiling:
        raise ValueError(f"Register grew beyond the immutable source ceiling: {sorted(registered - ceiling)[:12]}")
    for previous in ancestors:
        if (previous.get("schema") != SCHEMA or previous.get("origin") != ORIGIN
                or previous.get("stage") != "active"):
            raise ValueError("An unauthorized debt policy/schema appeared in history")
        prior_boundary, prior_collisions = boundary_sections(previous)
        debt_history.update(identity(row) for row in previous["sites"])
        if not registered <= {identity(row) for row in previous["sites"]}:
            raise ValueError("A removed debt/allowance entry reappeared; the register may only shrink")
        require_retained_boundary_metadata(boundary, collisions, prior_boundary, prior_collisions)
    if set(boundary) & debt_history:
        raise ValueError("Debt-to-boundary moves/reclassification are forbidden, including historical debt")
    if set(boundary) & set(removed_boundary):
        raise ValueError("A removed boundary record was resurrected")
    admitted = registered | set(boundary)
    if found != admitted:
        raise ValueError(f"Unregistered or resurrected sites: {sorted(found - admitted)[:12]}; remove stale entries: {sorted(admitted - found)[:12]}")
    if boundary:
        if base is None:
            raise ValueError("Boundary records require an exact PR base")
        prior, prior_collisions = boundary_sections(base)
        require_retained_boundary_metadata(boundary, collisions, prior, prior_collisions)
        introduced = set(boundary) - set(prior)
        # A reserved symbol is lexical only with a producer-emitted lexer rule.
        # Name-only rows and proved bare literals carry no computation alone:
        # exclude them from form matching only, never exact/same-symbol checks.
        ast_debt = {key for key in debt_history if not lexical_identity(key)}
        debt_forms = {(key[2], key[3]) for key in ast_debt
                      if key[2] not in {"verdict-symbol", "analysis-symbol"}}
        literal_forms = literal_verdict_fingerprints(current,
            [key for key in introduced if (key[2], key[3]) in debt_forms], current_sources)
        current_debt_rows = {identity(row): row for row in rows}
        for key in introduced & collisions.keys():
            # A new exception needs an active base witness, while every base
            # debt row with the fingerprint must survive the same change intact.
            # Retained collisions do not prevent later genuine debt retirement.
            witnesses = [row for row in base["sites"] if row["fingerprint"] == key[3]]
            if (lexical_identity(key) or (key[2], key[3]) not in debt_forms
                    or not any(row["rule"] == key[2] for row in witnesses)
                    or key[2] == "verdict-return" and key[3] in literal_forms):
                raise ValueError("Collision admission requires a substantive active-base debt form")
            if any(current_debt_rows.get(identity(row)) != row for row in witnesses):
                raise ValueError("Collision admission removes or modifies matching debt")
        removed_debt = {identity(row) for row in base["sites"]} - registered
        removed_symbols = {(key[0], key[1], key[2]) for key in removed_debt if not lexical_identity(key)}
        for key in introduced:
            if lexical_identity(key):
                continue
            if ((key[2], key[3]) in debt_forms and not (key[2] == "verdict-return" and key[3] in literal_forms)
                    and key not in collisions):
                raise ValueError("Debt-to-boundary AST form moved/copied from current or historical debt")
            if (key[0], key[1], key[2]) in removed_symbols:
                raise ValueError("Debt-to-boundary rewrite of a debt symbol removed by this PR")
        if introduced and not allow_new_boundary:
            raise ValueError("New boundary admissions require the PR/base event, not a manual run")
        if introduced and base_sites is None:
            raise ValueError("New boundary admissions require the PR base's source sites")
        if introduced & {identity(row) for row in base_sites or ()}:
            raise ValueError("Boundary file/symbol site is unchanged versus the PR base")


def check():
    registry = read_registry((ROOT / REGISTRY).read_text(encoding="utf-8"))
    if registry.get("stage") != "active":
        raise ValueError("Debt register requires source-bound active review")
    subprocess.run(["git", "-C", str(ROOT), "merge-base", "--is-ancestor", ORIGIN, "HEAD"], check=True)
    current_sources = source_map()
    current, origin = scan(current_sources), scan(source_map(ORIGIN))
    previous = []
    historic_debt = set()
    blobs = {}
    boundary, _collisions = boundary_sections(registry)
    base, allow_new = admission_base() if boundary else (None, True)

    def read_record(commit, *, historical=False):
        entry = git("ls-tree", commit, "--", REGISTRY).split()
        present = bool(entry)
        blob = entry[2].decode("ascii") if present else None
        if present and blob not in blobs:
            raw = read_registry(git("show", commit + ":" + REGISTRY))
            if boundary:
                historic_debt.update(identity(row) for row in raw["sites"])
            if (raw.get("schema") in {"interface-computation-debt/1", "interface-computation-debt/2"}
                    or raw.get("schema") == "interface-computation-debt/3"
                    and raw.get("stage") == "observation_required"):
                raw = {"schema": raw["schema"], "stage": raw.get("stage")}
            blobs[blob] = raw
        raw = blobs[blob] if present else None
        # Arbitrary parents/base revisions may carry unchanged legacy bytes.
        # Cutoffs bind every register-change COMMIT in the full history below,
        # even when a replay reuses a cached blob. Bootstrap payloads need not
        # remain live; their identities suffice for no-transfer.
        return present, policy_record(commit, raw, historical=historical) if raw is not None else None

    removed_boundary = set()
    # Default path history can prune a merge parent when the result matches the
    # other parent, hiding a removal that the merge resurrected.
    roots = ["HEAD", base] if base is not None else ["HEAD"]
    for commit in git("log", "--full-history", "--format=%H", *roots, "--", REGISTRY).decode().splitlines():
        present, record = read_record(commit, historical=True)
        if not present:
            raise ValueError("The closed register was removed in history")
        if record is None:
            continue
        previous.append(record)
        if boundary:
            here = set(boundary_sections(record)[0])
            for parent in git("rev-list", "--parents", "-n", "1", commit).decode().split()[1:]:
                _present, prior = read_record(parent)
                if prior is not None:
                    removed_boundary.update(set(boundary_sections(prior)[0]) - here)
    base_record, base_sites = None, None
    if boundary:
        _present, base_record = read_record(base)
        if base_record is None:
            raise ValueError("Boundary PR base has no active register")
        introduced = set(boundary) - set(boundary_sections(base_record)[0])
        if introduced:
            base_sources = source_map(base)
            # Compare the full base file even when it was not in that revision's
            # import closure. Adding an import cannot launder an unchanged helper.
            _names, source_bytes = revision_sources(base)
            for path in {key[0] for key in introduced}:
                if path in source_bytes and path not in base_sources:
                    base_sources[path] = source_bytes[path].decode("utf-8")
            base_sites = scan(base_sources)
    validate(registry, current, origin, previous, base=base_record, base_sites=base_sites,
             historic_debt=historic_debt, removed_boundary=removed_boundary, allow_new_boundary=allow_new,
             current_sources=current_sources)
    return len(current)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--observe":
        observations = scan(source_map())
        registry = read_registry((ROOT / REGISTRY).read_text(encoding="utf-8"))
        observed_proposal = proposal(observations, registry["boundary"], registry.get("collisions", []))
        record = {"source_commit": git("rev-parse", "HEAD").decode().strip(),
                  "source_tree": git("rev-parse", "HEAD^{tree}").decode().strip(),
                  "python": sys.version.split()[0], "platform": sys.platform,
                  "sites_sha256": digest(json.dumps(observed_proposal, sort_keys=True, separators=(",", ":"))),
                  "detectors": {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in (
                      "tests/interface_computation_guard.py", "tests/interface_computation_lex.py",
                      "tests/interface_computation_sources.py", ".github/scripts/interface_computation_ast.mjs")},
                  "proposal": observed_proposal, "observations": observations}
        Path(sys.argv[2]).write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        print(f"Observed {len(observations)} exact static sites; admission still requires review")
        print(f"DEBT_CENSUS_FINGERPRINT python={record['python']} platform={record['platform']} sites={len(observations)} sha256={record['sites_sha256']}")
        # Source-only proposal transport, not an archive upload before the
        # distribution audit. One bounded line per chunk avoids log line limits.
        encoded = base64.b64encode(gzip.compress(json.dumps({k: v for k, v in record.items() if k != "observations"}, separators=(",", ":")).encode(), mtime=0)).decode()
        print("DEBT_PROPOSAL_BEGIN")
        for offset in range(0, len(encoded), 4000):
            print("DEBT_PROPOSAL_CHUNK " + encoded[offset:offset + 4000])
        print("DEBT_PROPOSAL_END")
    elif sys.argv[1:] == ["--check"]:
        print(f"Interface computation ratchet passed: {check()} exact sites")
    else:
        raise SystemExit("Use --observe PATH or --check")
