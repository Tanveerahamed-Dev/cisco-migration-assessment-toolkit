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
from pathlib import Path
import re
import shutil
import subprocess
import sys

from interface_computation_lex import lexical_counter, lexical_sites, python_source, python_stream, string_payloads
from interface_computation_sources import SCRIPT_SUFFIXES, compiled_coverage, python_closure

ROOT = Path(__file__).resolve().parents[1]
DETECTOR_ROOT = ROOT
REGISTRY = "docs/interface-computation-debt.json"
ORIGIN = "7d9f83639eccb12915f2686aae13a47b44d50df1"
SCHEMA = "interface-computation-debt/2"
ROLE_ORIGIN = "97813d794f8cb8d61b206ba49a52aa4f9142b8e6"  # Reviewed initial roles, pinned independently of future edits.
LEGACY_REGISTER_HEAD = "3d3bca015a24a1d3aeec19471d81ae277043cb48"
DOMAIN = re.compile(r"health|score|band|severit|readiness|verdict|gate|punch|lifecycle|endpoint|device|vlan|flow|route|causal|impact|blast|adjacen|neighbou?r|graph|topolog|coverage", re.I)
SYMBOL = re.compile(r"^_*(?:count|compute|calculate|recount|simulate|evaluate|classify|qualify|trace|counterfactual|worst_readiness|go_no_go|gate_for)(?:_|[A-Z]|$)")
VERDICTS = frozenset({"READY", "NOT READY", "CAUTION", "GO", "NO-GO", "CONDITIONAL GO", "Critical", "Excellent", "Good", "Fair", "Poor", "ok", "watch", "risk", "crit", "healthy", "permit", "deny", "allow", "block", "reached", "unreachable"})
VERDICT_NAME = re.compile(r"^(?:can|could|should|is|has|may|must|allow|deny|permit|block|ready|safe|eligible|valid|approved|accepted|rejected|blocked|allowed|denied)(?:_|[A-Z]|$)|(?:^|_)(?:verdict|decision|readiness|ready|allowed|denied|eligible|gate|go_no_go|can_cut_over|ok|pass|fail)$")
VERDICT_RETURNS = {value.casefold().replace("_", "-") for value in (*VERDICTS, "yes", "no", "true", "false", "pass", "fail", "approved", "rejected", "blocked", "allowed", "valid", "invalid")}


def git(*args):
    return subprocess.check_output(["git", "-C", str(ROOT), *args])


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
    names = (git("ls-tree", "-r", "-z", "--name-only", revision) if revision else
             git("ls-files", "-z", "--cached", "--others", "--exclude-standard")).decode("utf-8").split("\0")
    read = (lambda p: git("show", revision + ":" + p).decode("utf-8")) if revision else lambda p: (ROOT / p).read_text(encoding="utf-8")
    names = sorted(set(names) - {""})
    # The old fact ceiling predates role declarations. Its reviewed role basis is
    # immutable Git source, never inferred from future module names or current roles.
    role_read = (lambda p: git("show", ROLE_ORIGIN + ":" + p).decode("utf-8")) if revision and ROLE_ORIGIN else None
    role_names = (git("ls-tree", "-r", "-z", "--name-only", ROLE_ORIGIN).decode("utf-8").split("\0")) if role_read else None
    selected = python_closure(names, read, role_read, role_names)
    candidates = {path: read(path) for path in names if path.lower().endswith((*SCRIPT_SUFFIXES, ".html"))
                  or path.endswith(".json") and ("tsconfig" in path or "jsconfig" in path or path.endswith(("package.json", "package-lock.json")))}
    discovered = node_reply(dict(mode="discover", files=candidates, names=names)) if candidates else {"paths": [], "generated": []}
    compiled = compiled_coverage(names, read if not revision else lambda p: (ROOT / p).read_text(encoding="utf-8"), discovered["generated"])
    selected.update(path for path in discovered["paths"] if path not in compiled or path.lower().endswith(".html"))
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


def python_sites(path, text):
    result, counts = [], Counter()
    text, lines, offsets = python_source(text)

    def segment(node):
        start = offsets[node.lineno - 1] + len(lines[node.lineno - 1].encode()[:node.col_offset].decode())
        end = offsets[node.end_lineno - 1] + len(lines[node.end_lineno - 1].encode()[:node.end_col_offset].decode())
        return text[start:end]

    def literal(node):
        return isinstance(node, ast.Constant) or (isinstance(node, ast.UnaryOp) and isinstance(node.operand, ast.Constant))

    class Walk(ast.NodeVisitor):
        scope = "<module>"

        def emit(self, node, rule, normalized=None):
            fingerprint = digest(normalized if normalized is not None else json.dumps(ast_form(node), sort_keys=True, separators=(",", ":")))
            key = (self.scope, rule, fingerprint)
            counts[key] += 1
            result.append(dict(path=path, symbol=self.scope, rule=rule, fingerprint=fingerprint,
                               occurrence=counts[key], line=node.lineno,
                               expression=segment(node).replace("\n", " ")[:240]))

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
                if isinstance(child, ast.Compare) and any(not literal(n) for n in (child.left, *child.comparators)):
                    self.emit(child, "returned-comparison")
                pending.extend(ast.iter_child_nodes(child))

            def verdict(value):
                if isinstance(value, ast.Constant):
                    return type(value.value) is bool or (isinstance(value.value, str) and value.value.casefold().replace("_", "-") in VERDICT_RETURNS)
                if isinstance(value, ast.Name):
                    return bool(VERDICT_NAME.search(value.id.lstrip("_")))
                if isinstance(value, ast.Attribute):
                    return bool(VERDICT_NAME.search(value.attr.lstrip("_")))
                if isinstance(value, ast.Call):
                    return verdict(value.func)
                if isinstance(value, ast.IfExp):
                    return verdict(value.body) or verdict(value.orelse)
                if isinstance(value, ast.BoolOp):
                    return any(verdict(child) for child in value.values)
                return False

            if verdict(node):
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
            if isinstance(node.op, (ast.Div, ast.FloorDiv)) and not literal(node.left) and not literal(node.right):
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

    Walk().visit(ast.parse(text, filename=path))
    return result


def scan(sources):
    sites, javascript, payloads = [], [], []
    streams = []
    for path, text in sources.items():
        if path.endswith(".py"):
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


def proposal(sites):
    return {"schema": SCHEMA, "origin": ORIGIN, "stage": "active",
            "sites": [{**{key: row[key] for key in ("path", "symbol", "rule", "fingerprint", "occurrence")},
                       "disposition": disposition(row)} for row in sites]}


def validate(registry, current, origin, ancestors=()):
    if set(registry) != {"schema", "origin", "stage", "sites"} or registry["schema"] != SCHEMA or registry["origin"] != ORIGIN or registry["stage"] != "active":
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
    registered, found, ceiling = set(keys), {identity(row) for row in current}, {identity(row) for row in origin}
    if found != registered:
        raise ValueError(f"Unregistered or resurrected sites: {sorted(found - registered)[:12]}; remove stale entries: {sorted(registered - found)[:12]}")
    if not registered <= ceiling:
        raise ValueError(f"Register grew beyond the immutable source ceiling: {sorted(registered - ceiling)[:12]}")
    for previous in ancestors:
        if previous.get("schema") != SCHEMA:
            raise ValueError("An unauthorized debt policy/schema appeared in history")
        if previous.get("stage") == "active" and not registered <= {identity(row) for row in previous["sites"]}:
            raise ValueError("A removed debt/allowance entry reappeared; the register may only shrink")


def check():
    registry = read_registry((ROOT / REGISTRY).read_text(encoding="utf-8"))
    if registry.get("stage") != "active":
        raise ValueError("Debt register requires source-bound active review")
    subprocess.run(["git", "-C", str(ROOT), "merge-base", "--is-ancestor", ORIGIN, "HEAD"], check=True)
    current, origin = scan(source_map()), scan(source_map(ORIGIN))
    previous = []
    # Default path history can prune a merge parent when the result matches the
    # other parent, hiding a removal that the merge resurrected.
    for commit in git("log", "--full-history", "--format=%H", "HEAD", "--", REGISTRY).decode().splitlines():
        record = read_registry(git("show", commit + ":" + REGISTRY))
        if record.get("schema") == "interface-computation-debt/1":
            # The supervisor explicitly permits widening/reindexing only the
            # unmerged v1 proposal. No later v1 register may reset this ceiling.
            subprocess.run(["git", "-C", str(ROOT), "merge-base", "--is-ancestor", commit, LEGACY_REGISTER_HEAD], check=True)
            continue
        previous.append(record)
    validate(registry, current, origin, previous)
    return len(current)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--observe":
        observations = scan(source_map())
        record = {"source_commit": git("rev-parse", "HEAD").decode().strip(),
                  "source_tree": git("rev-parse", "HEAD^{tree}").decode().strip(),
                  "python": sys.version.split()[0], "platform": sys.platform,
                  "sites_sha256": digest(json.dumps(proposal(observations), sort_keys=True, separators=(",", ":"))),
                  "detectors": {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in (
                      "tests/interface_computation_guard.py", "tests/interface_computation_lex.py",
                      "tests/interface_computation_sources.py", ".github/scripts/interface_computation_ast.mjs")},
                  "proposal": proposal(observations), "observations": observations}
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
