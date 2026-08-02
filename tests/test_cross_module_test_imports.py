"""A test module importing a name from a sibling test module must import one that exists.

WHY THIS IS ITS OWN FILE, AND WHY IT USES THE AST.

`from test_ssot_registry import ROOT, _main_checkout_root, _registry_text` executes at IMPORT time.
When `_main_checkout_root` was deleted from `test_ssot_registry.py` during privacy sanitization, the
consequence was not one failing test — pytest reported

    ERROR tests/test_registry_freshness.py
    !!! Interrupted: 1 error during collection !!!

and **collected nothing at all**. The entire suite stopped being evidence, repository-wide, from a
single stale name. That is the defect class this guard exists for: a fatal that is invisible as a
test result because it happens before any test runs.

Two design constraints follow, and both are load-bearing:

* **It lives in its own module.** A guard placed inside `test_registry_freshness.py` would be killed
  by exactly the breakage it is meant to report — it would never execute to fail.
* **It reads the AST; it imports nothing.** Importing the modules to check them reintroduces the
  original failure mode (and would drag in every heavy dependency those modules pull). Parsing means
  a broken module is *reported*, not *propagated*.

Scope, stated honestly: this checks names imported from SIBLING TEST MODULES only. It cannot verify
imports from `cisco_toolkit` or third-party packages — those fail loudly at their own call sites and
are covered by the ordinary suite. It also cannot protect its own import line, which is why it has
none beyond the standard library.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

_TESTS_DIR = pathlib.Path(__file__).resolve().parent


def _module_paths() -> dict[str, pathlib.Path]:
    """Importable sibling test modules, by module name (they are imported flat, not as a package)."""
    return {p.stem: p for p in sorted(_TESTS_DIR.glob("*.py")) if p.stem != "__init__"}


def _tree(path: pathlib.Path) -> ast.Module | None:
    try:
        return ast.parse(path.read_text(encoding="utf-8", errors="replace"), filename=str(path))
    except SyntaxError:
        return None            # a syntax error is the ordinary suite's problem, not this guard's


def _top_level_names(tree: ast.Module) -> set[str]:
    """Every name a sibling module exposes at module level — defs, classes, assignments, imports.

    Deliberately generous: this guard is for names that are ABSENT, never for names it merely
    failed to recognise. A false positive here would block the suite, which is the very outcome the
    guard exists to prevent.
    """
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    names.add(t.id)
                elif isinstance(t, (ast.Tuple, ast.List)):
                    names.update(e.id for e in t.elts if isinstance(e, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for a in node.names:
                names.add(a.asname or a.name.split(".")[0])
        elif isinstance(node, ast.Try):          # conditional definition blocks
            for sub in [*node.body, *node.orelse, *node.finalbody,
                        *[s for h in node.handlers for s in h.body]]:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    names.add(sub.name)
                elif isinstance(sub, ast.Assign):
                    for t in sub.targets:
                        if isinstance(t, ast.Name):
                            names.add(t.id)
    return names


def _cross_module_imports() -> list[tuple[str, str, str, int]]:
    """(importer, target module, imported name, lineno) for every sibling-test-module import."""
    mods = _module_paths()
    out: list[tuple[str, str, str, int]] = []
    for name, path in mods.items():
        tree = _tree(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module in mods:
                for alias in node.names:
                    if alias.name != "*":
                        out.append((name, node.module, alias.name, node.lineno))
    return out


def test_the_scan_actually_finds_cross_module_imports():
    """Guard the guard. If the discovery returns nothing — a moved directory, a changed layout —
    the parametrized test below silently becomes zero cases and pins nothing."""
    mods = _module_paths()
    assert len(mods) > 150, f"only {len(mods)} test modules found under {_TESTS_DIR}"
    found = _cross_module_imports()
    assert found, ("no sibling-test-module imports discovered at all — this guard has gone inert; "
                   "check the AST walk against the real layout")


@pytest.mark.parametrize(
    "importer,target,name,lineno",
    _cross_module_imports(),
    ids=lambda v: str(v) if not isinstance(v, int) else f"L{v}",
)
def test_every_name_imported_from_a_sibling_test_module_exists(importer, target, name, lineno):
    tree = _tree(_module_paths()[target])
    assert tree is not None, f"{target}.py does not parse — fix that first"
    available = _top_level_names(tree)
    assert name in available, (
        f"{importer}.py:{lineno} imports {name!r} from {target}.py, which no longer defines it.\n"
        f"This is a COLLECTION-time failure: pytest aborts the whole run "
        f"('Interrupted: 1 error during collection') and no suite is evidence until it is fixed.\n"
        f"Fix by defining the name where it is used, or by restoring it in {target}.py — "
        f"do not re-add logic that was deliberately removed."
    )
