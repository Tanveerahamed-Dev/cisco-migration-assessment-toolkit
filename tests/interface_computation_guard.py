"""ADR 0008 static debt census. Application source is parsed as data, never imported.

The detector is deliberately conservative: existing presentation/infrastructure
calculations are exact-site allowances, not proof of duplicate business logic.
No new site, changed expression, or resurrected retirement is silently admitted.
"""
from __future__ import annotations

import ast
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = "docs/interface-computation-debt.json"
ORIGIN = "9112a16e4e4d91674ba5cb2881f0d75071c7d78c"
ROOTS = ("webapp/frontend/src/", "webapp/backend/", "atlas-scope/src/")
SPECIAL = ("cisco_toolkit/blast_radius_explorer.html", "cisco_toolkit/excel.py", "cisco_toolkit/docmeta.py",
           "cisco_toolkit/html.py", "atlas-scope/tools/lib/compile-model.mjs")
DOMAIN = re.compile(r"health|score|band|severit|readiness|verdict|gate|punch|lifecycle|endpoint|device|vlan|flow|route|causal|impact|blast|adjacen|neighbou?r|graph|topolog|coverage", re.I)
SYMBOL = re.compile(r"^_*(?:count|compute|calculate|recount|simulate|evaluate|classify|qualify|trace|counterfactual|worst_readiness|go_no_go|gate_for)(?:_|[A-Z]|$)")
VERDICTS = frozenset({"READY", "NOT READY", "CAUTION", "GO", "NO-GO", "CONDITIONAL GO", "Critical", "Excellent", "Good", "Fair", "Poor", "ok", "watch", "risk", "crit", "healthy", "permit", "deny", "allow", "block", "reached", "unreachable"})
PATTERNS = {
    "dynamic-code": re.compile(r"\b(?:eval|exec|Function)\s*\("),
    "graph-worklist": re.compile(r"\b(?:queue|visited|adjacency|neighbours|neighbors)\s*\.\s*(?:shift|pop|popleft|add|push|append)\s*\("),
    "filter-count": re.compile(r"\.filter\s*\([^;\n]{1,200}\)\s*\.length\b"),
    "raw-count": re.compile(r"\.\s*(?:length|size)\b|\b(?:len|sum|Counter)\s*\("),
    "raw-threshold": re.compile(r"(?:>=|<=|>|<)\s*[0-9]+"),
}


def git(*args):
    return subprocess.check_output(["git", "-C", str(ROOT), *args])


def source_map(revision=None):
    names = (git("ls-tree", "-r", "--name-only", revision) if revision else
             git("ls-files", "--cached", "--others", "--exclude-standard")).decode().splitlines()
    read = (lambda p: git("show", revision + ":" + p).decode("utf-8")) if revision else lambda p: (ROOT / p).read_text(encoding="utf-8")
    # Discover document writers from the real registry without importing generators.
    registry = ast.parse(read("cisco_toolkit/docmeta.py"))
    writers = {kw.value.value.replace(".", "/") + ".py"
               for node in ast.walk(registry) if isinstance(node, ast.Call)
               for kw in node.keywords if kw.arg == "writer_module" and isinstance(kw.value, ast.Constant)
               and isinstance(kw.value.value, str)}
    selected = set()
    for path in names:
        if path in SPECIAL or path in writers:
            selected.add(path)
        elif path.startswith(ROOTS) and path.endswith((".py", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts")):
            if path == "webapp/backend/engine.py" or "/test/" in path or "/__tests__/" in path or re.search(r"\.(?:test|spec)\.", path):
                continue
            selected.add(path)
    return {path: read(path) for path in sorted(selected)}


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

    class Walk(ast.NodeVisitor):
        scope = "<module>"

        def emit(self, node, rule, normalized=None):
            fingerprint = digest(normalized if normalized is not None else json.dumps(ast_form(node), sort_keys=True, separators=(",", ":")))
            key = (self.scope, rule, fingerprint)
            counts[key] += 1
            result.append(dict(path=path, symbol=self.scope, rule=rule, fingerprint=fingerprint,
                               occurrence=counts[key], line=node.lineno,
                               expression=(ast.get_source_segment(text, node) or "").replace("\n", " ")[:240]))

        def visit_FunctionDef(self, node):
            old = self.scope
            self.scope = node.name if old == "<module>" else old + "." + node.name
            if SYMBOL.match(node.name):
                self.emit(node, "analysis-symbol", node.name)
            self.generic_visit(node)
            self.scope = old

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_Call(self, node):
            name = node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else ""
            if name in {"len", "sum", "any", "all", "Counter", "mean", "average", "count", "count_by", "_count_by"}:
                self.emit(node, "aggregate")
            if name in {"bfs", "dfs", "shortest_path", "dijkstra", "reachable", "flood_fill"}:
                self.emit(node, "graph-call")
            if name in {"append", "extend", "pop", "popleft", "add", "update"}:
                self.emit(node, "collection-update")
            if name == "get" and len(node.args) > 1 and isinstance(node.args[1], ast.Constant) and node.args[1].value == 0 and DOMAIN.search(ast.unparse(node)):
                self.emit(node, "fact-default-zero")
            self.generic_visit(node)

        def visit_Return(self, node):
            if node.value is not None and any(isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value in VERDICTS for n in ast.walk(node.value)):
                self.emit(node.value, "fact-decision")
            self.generic_visit(node)

        def visit_Compare(self, node):
            if any(isinstance(n, ast.Constant) and type(n.value) in (int, float) for n in ast.walk(node)):
                self.emit(node, "fact-threshold")
            self.generic_visit(node)

        def visit_BinOp(self, node):
            if isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv)) and DOMAIN.search(ast.unparse(node)):
                self.emit(node, "fact-arithmetic")
            self.generic_visit(node)

        def visit_AugAssign(self, node):
            if isinstance(node.op, (ast.Add, ast.Sub)):
                self.emit(node, "counter-update")
            self.generic_visit(node)

        def visit_Assign(self, node):
            if isinstance(node.value, ast.BinOp) and isinstance(node.value.op, ast.Add):
                self.emit(node, "counter-update")
            self.generic_visit(node)

        def visit_IfExp(self, node):
            if re.search(r"Critical|Excellent|Good|Poor|READY|GO|risk|watch|healthy", ast.unparse(node.body) + ast.unparse(node.orelse)):
                self.emit(node.test, "fact-decision")
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
    sites, javascript = [], []
    for path, text in sources.items():
        if path.endswith(".py"):
            sites.extend(python_sites(path, text))
        else:
            javascript.append(dict(path=path, text=text))
    if javascript:
        node = shutil.which("node")
        if not node:
            raise RuntimeError("Node is required for the interface AST gate")
        command = [node, str(ROOT / ".github/scripts/interface_computation_ast.mjs")]
        reply = subprocess.run(command, input=json.dumps(dict(sources=javascript)), cwd=ROOT,
                               text=True, encoding="utf-8", capture_output=True, check=True, timeout=90)
        sites.extend(json.loads(reply.stdout))
    for path, text in sources.items():
        # Separate lexical tripwire also sees generated code held inside string templates.
        # It supplements AST analysis; it is not a replacement for parsing.
        for rule, pattern in PATTERNS.items():
            occurrences = Counter()
            for match in pattern.finditer(text):
                fingerprint = digest(match.group())
                occurrences[fingerprint] += 1
                sites.append(dict(path=path, symbol="<forbidden-pattern>", rule=rule,
                                  fingerprint=fingerprint, occurrence=occurrences[fingerprint],
                                  line=text[:match.start()].count("\n") + 1, expression=match.group()))
    return sorted(sites, key=identity)


def identity(row):
    return (row["path"], row["symbol"], row["rule"], row["fingerprint"], row["occurrence"])


def disposition(row):
    if row["path"].startswith("atlas-scope/") or row["path"].endswith("blast_radius_explorer.html"):
        return "retired-with-surface"
    return "legacy-site-review-required"


def proposal(sites):
    return {"schema": "interface-computation-debt/1", "origin": ORIGIN, "stage": "active",
            "sites": [{**{key: row[key] for key in ("path", "symbol", "rule", "fingerprint", "occurrence")},
                       "disposition": disposition(row)} for row in sites]}


def validate(registry, current, origin, ancestors=()):
    if set(registry) != {"schema", "origin", "stage", "sites"} or registry["schema"] != "interface-computation-debt/1" or registry["origin"] != ORIGIN or registry["stage"] != "active":
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
        if previous.get("stage") == "active" and not registered <= {identity(row) for row in previous["sites"]}:
            raise ValueError("A removed debt/allowance entry reappeared; the register may only shrink")


def check():
    registry = read_registry((ROOT / REGISTRY).read_text(encoding="utf-8"))
    if registry.get("stage") != "active":
        raise ValueError("Debt register requires source-bound active review")
    subprocess.run(["git", "-C", str(ROOT), "merge-base", "--is-ancestor", ORIGIN, "HEAD"], check=True)
    current, origin = scan(source_map()), scan(source_map(ORIGIN))
    previous = []
    for commit in git("log", "--format=%H", "HEAD", "--", REGISTRY).decode().splitlines():
        previous.append(read_registry(git("show", commit + ":" + REGISTRY)))
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
                      "tests/interface_computation_guard.py", ".github/scripts/interface_computation_ast.mjs")},
                  "proposal": proposal(observations), "observations": observations}
        Path(sys.argv[2]).write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        print(f"Observed {len(observations)} exact static sites; admission still requires review")
        print(f"DEBT_CENSUS_FINGERPRINT python={record['python']} platform={record['platform']} sites={len(observations)} sha256={record['sites_sha256']}")
    elif sys.argv[1:] == ["--check"]:
        print(f"Interface computation ratchet passed: {check()} exact sites")
    else:
        raise SystemExit("Use --observe PATH or --check")
