"""Shared structural scans for the W59 SSH tests (no test functions here; tests/ is on sys.path via conftest.py).

W59 PR-2 review (P3-e): the T8 connection-constructor guard was written twice -- a structural taint scan in
``tests/test_ssh_session.py`` (W59 PR-1 review P3-f) and a named-subset spelling match in
``tests/test_legacy_ssh_consent.py`` that a ``_netmiko.ConnectHandler(...)`` or an aliased class map walked past.
Both now call ONE helper, :func:`connection_constructor_calls`, and both T10 scans share ONE shipped-source
denominator, :func:`shipped_python_files` (the wheel's runtime inventory plus the Atlas bundle's import closure).

The scan itself (W59 PR-1 review P3-f, closed in its round 2: the scope-aware shape fixpoint and the argument-site
rule) moved verbatim from ``tests/test_ssh_session.py`` to here, and then, in W59 PR-2 review round 2 (P2), to its one
shipped owner, ``cisco_toolkit.attestation``, whose published ``legacy_ssh_confined`` claim runs it over the legacy
tier. This module keeps the collector's two site maps and re-exports the scan; ``tests/test_ssh_session.py`` and
``tests/test_legacy_ssh_consent.py`` import both from here.
"""
from __future__ import annotations

import ast
import warnings
from pathlib import Path

# The T8 scan's ONE owner is the shipped attestation module (W59 PR-2 review round 2, P2): the published
# `legacy_ssh_confined` claim runs the same fixpoint over the legacy tier. These names re-export it unchanged.
from cisco_toolkit.attestation import (  # the repository root is on sys.path (root conftest.py)
    SSH_CONNECTION_LIBRARIES as SSH_LIBRARIES,
    callee_name,
    connection_constructor_calls,
    connection_roots,
    qualified_owners,
)

__all__ = [
    "CONNECTION_ARGUMENT_SITES", "CONNECTION_CONSTRUCTOR_SITES", "ENGINE", "ROOT", "SSH_LIBRARIES",
    "bundle_python_closure", "callee_name", "connection_constructor_calls", "connection_roots", "engine_tree",
    "parse_source", "qualified_owners", "repo_module_file", "shipped_python_files",
]

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "COLLECT_PARSE_V3_23_0.py"

# ================================================================== T8: one patchable connection factory ===
#: W59 PR-1 review (P3-f): the ONLY sites, by qualified name, that may construct an SSH connection object, each with
#: the callee it constructs through. The factory itself; the platform autodetect probe (SSHDetect connects on
#: construction, outside the observed path by design, section 4.2); and the factory's two internal hooks, which
#: netmiko (``_build_ssh_client``) and paramiko (``SSHClient.connect``) reach only from INSIDE the factory's own driver
#: call -- the first refuses outside its hand-off. Anything else is an unobserved, unpatchable connection.
CONNECTION_CONSTRUCTOR_SITES = {
    "_open_connection": ["driver"],
    "autodetect_platform": ["SSHDetect"],
    "_ObservedClientMixin._get_ssh_client_instance": ["_ObservedSSHClient"],
    "_ObservedSSHClient.connect._transport_factory": ["transport_cls"],
}
#: W59 PR-1 review (P3-f, round 2): the ONLY sites that hand a connection-capable value to other code as a call
#: argument, each with the callee it hands it to. The factory passes the profile's transport class to the cached
#: driver builder; the client hook passes it to the client it constructs; the library probe passes paramiko's stock
#: classes to ``ssh_session.permits_sha1``, which reads their tables and calls nothing. A tainted value handed to any
#: other callee (a helper that calls it, ``functools.partial``, ``setattr``, ``map``, ``sorted(key=...)``) is a route
#: this guard does not follow into, so the hand-over is a violation by itself.
CONNECTION_ARGUMENT_SITES = {
    "_open_connection": ["_observed_driver_for"],
    "_ObservedClientMixin._get_ssh_client_instance": ["_ObservedSSHClient"],
    "_ssh_library_block": ["ssh_session.permits_sha1"],
}


def engine_tree():
    return ast.parse(ENGINE.read_text(encoding="utf-8"))


# ===================================================================== T10: the shipped-source denominator ===
def parse_source(path):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SyntaxWarning)
        return ast.parse(path.read_text(encoding="utf-8"))


def repo_module_file(name):
    """The repository file a dotted module name resolves to (``a/b.py`` or ``a/b/__init__.py``), or None."""
    base = name.replace(".", "/")
    for rel in (f"{base}.py", f"{base}/__init__.py"):
        if (ROOT / rel).is_file():
            return rel
    return None


def bundle_python_closure():
    """The repository Python the Atlas bundle freezes, derived from its owners: the Analysis scripts and runtime hooks
    of ``portable/atlas.spec`` (each a ``ROOT / ... / name.py`` path literal) and ``atlas_bundle.hidden_imports()``,
    closed over their repository-local imports (absolute and relative)."""
    from portable.atlas_bundle import hidden_imports

    spec = ast.parse((ROOT / "portable" / "atlas.spec").read_text(encoding="utf-8"))
    seeds = set()
    for node in ast.walk(spec):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Analysis":
            lists = list(node.args[:1]) + [kw.value for kw in node.keywords if kw.arg == "runtime_hooks"]
            for item in (e for lst in lists if isinstance(lst, ast.List) for e in lst.elts):
                consts = [c for c in ast.walk(item) if isinstance(c, ast.Constant) and isinstance(c.value, str)]
                seeds.add("/".join(c.value for c in sorted(consts, key=lambda c: (c.lineno, c.col_offset))))
    assert "portable/atlas_entry.py" in seeds and any(s.startswith("portable/rthook_") for s in seeds), seeds
    seeds.update(f for f in (repo_module_file(m) for m in hidden_imports()) if f)
    files, queue = set(), sorted(seeds)
    while queue:
        rel = queue.pop()
        if rel in files or not (ROOT / rel).is_file():
            continue
        files.add(rel)
        package = rel.rsplit("/", 1)[0].replace("/", ".") if "/" in rel else ""
        for node in ast.walk(parse_source(ROOT / rel)):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    parent = package.split(".") if package else []
                    parent = parent[:len(parent) - (node.level - 1)] if node.level > 1 else parent
                    base = ".".join(parent + ([node.module] if node.module else []))
                else:
                    base = node.module or ""
                names = [base] + [f"{base}.{a.name}" for a in node.names]
            for name in names:
                target = repo_module_file(name) if name else None
                if target and target not in files:
                    queue.append(target)
    return files


def shipped_python_files():
    """The shipped-source denominator (W59 PR-1 review, P3-f), derived from its owners, never a hand-listed prefix
    tuple: every Python member of the wheel's expected runtime inventory
    (``distribution_verify._expected_runtime_inventory``, the set the wheel audit holds the built archive to) plus
    every repository Python file the Atlas bundle freezes (:func:`bundle_python_closure`). Repository-relative POSIX
    paths, sorted."""
    from cisco_toolkit.distribution_verify import _expected_runtime_inventory

    wheel = {rel for rel in _expected_runtime_inventory(ROOT) if rel.endswith(".py")}
    files = sorted(wheel | bundle_python_closure())
    for required in ("cisco_toolkit/ssh_session.py", "COLLECT_PARSE_V3_23_0.py", "webapp/backend/serve.py",
                     "portable/atlas_entry.py", "portable/network_boundary.py"):
        assert required in files, required                         # non-vacuity: both denominators contribute
    return files
