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
SPECIAL = ("cisco_toolkit/blast_radius_explorer.html", "cisco_toolkit/excel.py", "cisco_toolkit/docmeta.py")
DOMAIN = re.compile(r"health|score|band|severit|readiness|verdict|gate|punch|lifecycle|endpoint|device|vlan|flow|route|causal|impact|blast|adjacen|neighbou?r|graph|topolog|coverage", re.I)
SYMBOL = re.compile(r"^_*(?:count|compute|calculate|recount|simulate|evaluate|classify|qualify|trace|counterfactual|worst_readiness|go_no_go|gate_for)(?:_|[A-Z]|$)")
PATTERNS = {
    "dynamic-code": re.compile(r"\b(?:eval|exec|Function)\s*\("),
    "graph-worklist": re.compile(r"\b(?:queue|visited|adjacency|neighbours|neighbors)\s*\.\s*(?:shift|pop|popleft|add|push|append)\s*\("),
    "filter-count": re.compile(r"\.filter\s*\([^;\n]{1,200}\)\s*\.length\b"),
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
        elif path.startswith(ROOTS) and path.endswith((".py", ".js", ".jsx", ".mjs", ".ts", ".tsx")):
            if path == "webapp/backend/engine.py" or "/generated/" in path or "/test/" in path or "/__tests__/" in path or re.search(r"\.(?:test|spec)\.", path):
                continue
            selected.add(path)
    return {path: read(path) for path in sorted(selected)}


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def python_sites(path, text):
    result, counts = [], Counter()

    class Walk(ast.NodeVisitor):
        scope = "<module>"

        def emit(self, node, rule, normalized=None):
            fingerprint = digest(normalized if normalized is not None else ast.dump(node, include_attributes=False))
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
            if name in {"len", "sum", "Counter", "mean", "average", "count", "count_by", "_count_by"}:
                self.emit(node, "aggregate")
            if name in {"bfs", "dfs", "shortest_path", "dijkstra", "reachable", "flood_fill"}:
                self.emit(node, "graph-call")
            self.generic_visit(node)

        def visit_Compare(self, node):
            if any(isinstance(n, ast.Constant) and type(n.value) in (int, float) for n in ast.walk(node)) and DOMAIN.search(self.scope + ast.unparse(node)):
                self.emit(node, "fact-threshold")
            self.generic_visit(node)

        def visit_BinOp(self, node):
            if isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv)) and DOMAIN.search(ast.unparse(node)):
                self.emit(node, "fact-arithmetic")
            self.generic_visit(node)

        def visit_AugAssign(self, node):
            if DOMAIN.search(ast.unparse(node.target)) or (isinstance(node.target, ast.Subscript) and isinstance(node.op, ast.Add)):
                self.emit(node, "counter-update")
            self.generic_visit(node)

        def visit_Assign(self, node):
            if isinstance(node.value, ast.BinOp) and isinstance(node.value.op, ast.Add) and any(isinstance(t, ast.Subscript) for t in node.targets):
                self.emit(node, "counter-update")
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
            if path.endswith(".html"):
                # The template owns one literal script element. A new script is scanned too;
                # unresolved external scripts refuse rather than falling outside the census.
                scripts = list(re.finditer(r"<script\b([^>]*)>(.*?)</script\s*>", text, re.I | re.S))
                if not scripts or any(re.search(r"\bsrc\s*=", m[1], re.I) for m in scripts):
                    raise ValueError("Explorer script census is absent or external")
                text = "\n".join("\n" * text[:m.start(2)].count("\n") + m[2] for m in scripts)
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
            for occurrence, match in enumerate(pattern.finditer(text), 1):
                sites.append(dict(path=path, symbol="<forbidden-pattern>", rule=rule,
                                  fingerprint=digest(match.group()), occurrence=occurrence,
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
    registry = json.loads((ROOT / REGISTRY).read_text(encoding="utf-8"))
    subprocess.run(["git", "-C", str(ROOT), "merge-base", "--is-ancestor", ORIGIN, "HEAD"], check=True)
    current, origin = scan(source_map()), scan(source_map(ORIGIN))
    previous = []
    for commit in git("log", "--format=%H", "HEAD", "--", REGISTRY).decode().splitlines():
        previous.append(json.loads(git("show", commit + ":" + REGISTRY)))
    validate(registry, current, origin, previous)
    return len(current)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--observe":
        observations = scan(source_map())
        Path(sys.argv[2]).write_text(json.dumps({"proposal": proposal(observations), "observations": observations}, indent=2) + "\n", encoding="utf-8")
        print(f"Observed {len(observations)} exact static sites; admission still requires review")
    elif sys.argv[1:] == ["--check"]:
        print(f"Interface computation ratchet passed: {check()} exact sites")
    else:
        raise SystemExit("Use --observe PATH or --check")
