"""W65 census: every tracked file-write site, classified for client data.

The two privacy gates (``.github/scripts/verify_repository_privacy.py`` for the committed tree and
``cisco_toolkit/distribution_verify.py`` for the wheel and sdist) refuse files by NAME.  A name
gate is only as complete as its list, and a list kept by hand is the "named subset instead of the
structural class" defect: before W65 the engine wrote ``.protocol-assurance.json``,
``.comparison.json``, ``.trend-comparisons.json`` and ``.phase_timings.json`` sidecars that carry
client hostnames and evidence, and neither gate classified them.

This module closes the class from the producer side, statically (every file is parsed with
:mod:`ast`; nothing is imported or executed):

* **Scope.** Every tracked Python file except test code (:func:`scanned_files`); a new top-level
  directory is in scope the moment it holds a tracked ``.py`` file.
* **Write sites.** Per enclosing function, every call that creates, replaces or moves file bytes
  (:func:`write_primitive`, with ``os``/``shutil``/``tempfile``/``zipfile``/``logging``/``sqlite3``
  module aliases and name imports resolved, and a computed mode or flag set counted as a write),
  plus every reference to a *path-parameter writer*: a function whose parameter flows into a write
  target (derived to a fixed point, so a writer that only forwards its path to another writer is
  one too). A new caller of any such writer is therefore a census row of its own.
* **Classification.** :data:`WRITE_SITE_CENSUS` classifies each function:

  - ``client``: the bytes can carry client evidence, and every name they are published under is a
    class in ``cisco_toolkit.distribution_verify.CLIENT_ARTIFACT_NAME_CLASSES``;
  - ``private-temp``: client bytes that only ever live under the operating-system temporary
    directory (``tempfile`` with no ``dir=``, or a work directory made under it) and are removed by
    the same code path;
  - ``delegated``: a path-parameter writer whose name comes from its caller (each caller is a row);
  - ``operator-path``: bytes written only where the operator points the tool (a ``--out`` path or a
    collection folder rewritten in place); names the operator invents cannot be gated by name, so
    the row names the registered classes the known shapes fall in and says what the bytes are;
  - ``non-client``: the bytes cannot carry client evidence; the row says why.

* **Names actually written.** Wherever a site's target resolves to a literal name (assignments in
  the function and module constants are followed), its class must be one the row names, and a
  ``non-client`` row must resolve to none (:func:`resolved_site_classes`).
  Resolved literals that match no class are retained (:func:`unclassified_site_literals`) and
  refused for ``client`` rows; keeping the write count unchanged cannot hide a renamed artifact.
  Partial templates retain their uncertainty separately (:func:`unresolved_site_templates`);
  an explicit sidecar suffix remains a class obligation. Targets projected from a reviewed
  ``non-client`` helper retain that helper's provenance, rather than becoming client payloads.
* **Suffix literals.** :func:`suffix_literals` collects every literal appended to an output stem
  (``+``, f-string tails, ``%`` and ``.format`` templates, ``with_suffix``/``with_name``,
  ``str.join``), and each one must be a registered class or a :data:`NON_CLIENT_SUFFIX_LITERALS`
  entry keyed by (file, literal) with a reason.

Bounds, stated rather than implied: a bare file name joined onto a directory for READING is not a
write; dynamic dispatch (``getattr(module, spec.writer_name)``) is tied by the docmeta registry, not
  here; files written by a subprocess are the subprocess's own rows; ``.ps1`` and browser writers
are tied by producer-name checks in ``tests/test_client_artifact_census.py``. The browser census
includes every tracked engine HTML file, direct download-helper calls and download attributes;
it is not general JavaScript alias/data-flow analysis. Unknown names require explicit disposition.

:func:`census_problems` and :func:`suffix_literal_problems` are the whole check;
``tests/test_client_artifact_census.py`` asserts both are empty, so a new sidecar fails CI until it
is classified here and, when it is client-bearing, named in the registry. Run
``python tests/client_artifact_census.py`` from the repository root for the same report. The module
lives under ``tests/`` (not ``tools/``) so that it stays outside the byte-custody LF policy domains,
whose tracked-path receipts in ``tests/fixtures/atlas-r2-byte-custody-policy.v1.json`` would
otherwise move with it.
"""

from __future__ import annotations

import ast
import copy
import itertools
import re
import string
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable, Mapping
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]

CLIENT = "client"
PRIVATE_TEMP = "private-temp"
DELEGATED = "delegated"
OPERATOR_PATH = "operator-path"
NON_CLIENT = "non-client"
DISPOSITIONS = frozenset({CLIENT, PRIVATE_TEMP, DELEGATED, OPERATOR_PATH, NON_CLIENT})


def _registry():
    """The owner registry, imported on use so this module imports without the package path."""
    from cisco_toolkit.distribution_verify import CLIENT_ARTIFACT_NAME_CLASSES, client_artifact_class

    return CLIENT_ARTIFACT_NAME_CLASSES, client_artifact_class


# --------------------------------------------------------------------------- scope


#: The only exclusion: test code, which writes under pytest's temporary paths. A path is test code
#: when a directory component is ``tests``, or its file name is ``conftest.py``, ``test_*.py`` or
#: ``*_test.py``.
SCAN_EXCLUSION = "test code (a `tests` directory, conftest.py, test_*.py, *_test.py)"
_SKIPPED_DIRECTORIES = frozenset({"__pycache__", "node_modules", ".git"})


def is_test_path(relative: str) -> bool:
    parts = relative.split("/")
    name = parts[-1]
    return (
        "tests" in parts[:-1]
        or name == "conftest.py"
        or name.startswith("test_")
        or name.endswith("_test.py")
    )


def scanned_files(root: Path = ROOT) -> list[str]:
    """Every tracked non-test ``.py`` file (``git ls-files``); a non-repository tree is walked."""
    if (root / ".git").exists():
        listed = subprocess.run(
            ["git", "ls-files", "-z", "--", "*.py"], cwd=root, check=True, capture_output=True
        ).stdout.decode("utf-8").split("\0")
        candidates = [path for path in listed if path.endswith(".py")]
    else:
        candidates = [
            path.relative_to(root).as_posix()
            for path in root.rglob("*.py")
            if not _SKIPPED_DIRECTORIES & set(path.relative_to(root).parts)
        ]
    return sorted(
        path for path in set(candidates) if not is_test_path(path) and (root / path).is_file()
    )


# --------------------------------------------------------------------------- imports


def _module_name(relative: str) -> str:
    dotted = relative[:-3].replace("/", ".")
    return dotted[: -len(".__init__")] if dotted.endswith(".__init__") else dotted


@dataclass
class _Imports:
    modules: dict[str, str] = field(default_factory=dict)   # local name -> dotted module
    names: dict[str, str] = field(default_factory=dict)     # local name -> dotted module.attr

    def qualify(self, node: ast.AST) -> str | None:
        if isinstance(node, ast.Name):
            return self.names.get(node.id) or self.modules.get(node.id) or node.id
        if isinstance(node, ast.Attribute):
            base = self.qualify(node.value)
            return f"{base}.{node.attr}" if base else None
        return None


def _collect_imports(tree: ast.AST, module: str, is_package: bool) -> _Imports:
    imports = _Imports()
    package = module if is_package else module.rpartition(".")[0]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    imports.modules[alias.asname] = alias.name
                else:
                    head = alias.name.split(".")[0]
                    imports.modules.setdefault(head, head)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                anchor = package.split(".") if package else []
                anchor = anchor[: len(anchor) - (node.level - 1)] if node.level > 1 else anchor
                base = ".".join([*anchor, base] if base else anchor)
            for alias in node.names:
                if alias.name == "*":
                    continue
                imports.names[alias.asname or alias.name] = f"{base}.{alias.name}" if base else alias.name
    return imports


# --------------------------------------------------------------------------- primitives

_WRITE_FLAGS = frozenset({"O_WRONLY", "O_RDWR", "O_CREAT", "O_APPEND", "O_TRUNC", "O_EXCL"})
_MODE_FUNCTIONS = {           # qualified name -> (mode position, default mode)
    "open": (1, "r"), "io.open": (1, "r"), "codecs.open": (1, "r"), "gzip.open": (1, "rb"),
    "bz2.open": (1, "rb"), "lzma.open": (1, "rb"), "tarfile.open": (1, "r"),
    "io.FileIO": (1, "r"), "gzip.GzipFile": (1, "rb"), "bz2.BZ2File": (1, "r"),
    "lzma.LZMAFile": (1, "r"), "zipfile.ZipFile": (1, "r"),
}
_TARGET_SECOND = frozenset({
    "os.replace", "os.rename", "os.renames", "os.link", "os.symlink", "shutil.copy", "shutil.copy2",
    "shutil.copyfile", "shutil.copytree", "shutil.move", "shutil.unpack_archive",
    "urllib.request.urlretrieve",
})
_TARGET_FIRST = frozenset({
    "sqlite3.connect", "logging.FileHandler", "logging.handlers.RotatingFileHandler",
    "logging.handlers.TimedRotatingFileHandler", "logging.handlers.WatchedFileHandler",
    "shutil.make_archive", "tempfile.mkstemp", "tempfile.NamedTemporaryFile",
})
_RECEIVER_TARGET_METHODS = frozenset({"write_text", "write_bytes", "touch", "hardlink_to", "symlink_to"})
_ARGUMENT_TARGET_METHODS = frozenset({"save", "to_csv", "to_excel", "savefig", "write_pdf", "extractall"})


def _constant_text(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _mode_writes(mode: str) -> bool:
    return any(flag in mode for flag in "wax+")


def _no_resolution(_name: ast.Name) -> list[ast.AST]:
    return []


def _argument(call: ast.Call, position: int, keyword: str) -> ast.AST | None:
    for item in call.keywords:
        if item.arg == keyword:
            return item.value
    return call.args[position] if len(call.args) > position else None


def _string_values(node: ast.AST, resolve, depth: int = 0) -> list[str] | None:
    """Every literal string ``node`` can hold, or None when any path is not a literal."""
    text = _constant_text(node)
    if text is not None:
        return [text]
    if isinstance(node, ast.Name) and depth < 4:
        values = resolve(node)
        if not values:
            return None
        found: list[str] = []
        for value in values:
            sub = _string_values(value, resolve, depth + 1)
            if sub is None:
                return None
            found.extend(sub)
        return found
    if isinstance(node, ast.IfExp):
        left = _string_values(node.body, resolve, depth + 1)
        right = _string_values(node.orelse, resolve, depth + 1)
        return None if left is None or right is None else left + right
    return None


def _mode_state(call: ast.Call, position: int, default: str, resolve) -> str:
    """``read``, ``write`` or ``computed`` for the mode argument of an open-like call."""
    node = _argument(call, position, "mode")
    if node is None:
        return "write" if _mode_writes(default) else "read"
    values = _string_values(node, resolve)
    if values is None:
        return "computed"
    return "write" if any(_mode_writes(value) for value in values) else "read"


def _flag_state(node: ast.AST, resolve, depth: int = 0) -> str:
    """``read``, ``write`` or ``computed`` for an ``os.open`` flag expression."""
    if isinstance(node, ast.Attribute) and node.attr.startswith("O_"):
        return "write" if node.attr in _WRITE_FLAGS else "read"
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return "read" if node.value == 0 else "computed"
    if isinstance(node, ast.BinOp):
        states = {_flag_state(node.left, resolve, depth), _flag_state(node.right, resolve, depth)}
    elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "getattr":
        name = _constant_text(node.args[1]) if len(node.args) > 1 else None
        if name is None or not name.startswith("O_"):
            return "computed"
        return "write" if name in _WRITE_FLAGS else "read"
    elif isinstance(node, ast.Name) and depth < 4:
        values = resolve(node)
        if not values:
            return "computed"
        states = {_flag_state(value, resolve, depth + 1) for value in values}
    else:
        return "computed"
    if "computed" in states:
        return "computed"
    return "write" if "write" in states else "read"


def write_primitive(call: ast.Call, qualify=None, resolve=None) -> tuple[str, list[ast.AST]] | None:
    """``(kind, target expressions)`` when ``call`` creates, replaces or moves file bytes.

    A computed mode or flag set counts as a write; a literal read mode, ``open(path)`` and
    directory creation do not. ``qualify`` maps a call target to its dotted name (module aliases
    and name imports resolved); ``resolve`` returns the expressions a Name was assigned.
    """
    qualify = qualify or _Imports().qualify
    resolve = resolve or _no_resolution
    func = call.func
    name = qualify(func) if isinstance(func, (ast.Name, ast.Attribute)) else None
    first = call.args[0] if call.args else None
    if name in _MODE_FUNCTIONS:
        position, default = _MODE_FUNCTIONS[name]
        state = _mode_state(call, position, default, resolve)
        return (name, [first] if first is not None else []) if state != "read" else None
    if name == "os.open":
        flags = _argument(call, 1, "flags")
        if flags is None or _flag_state(flags, resolve) == "read":
            return None
        return name, [first] if first is not None else []
    if name in _TARGET_SECOND:
        target = _argument(call, 1, "dst") or _argument(call, 1, "filename") or _argument(call, 1, "extract_dir")
        return name, [target] if target is not None else list(call.args)
    if name in {"tempfile.mkstemp", "tempfile.NamedTemporaryFile"}:
        offset = 0 if name == "tempfile.mkstemp" else 4
        suffix = _argument(call, offset, "suffix") or ast.Constant("")
        prefix = _argument(call, offset + 1, "prefix") or ast.Constant("tmp")
        directory = _argument(call, offset + 2, "dir") or ast.Constant(None)
        filename = ast.BinOp(left=ast.BinOp(left=prefix, op=ast.Add(), right=ast.Constant("0")),
                             op=ast.Add(), right=suffix)
        # Keep directory flow for writer derivation, but classify the composed leaf only.
        return name, [ast.BinOp(left=directory, op=ast.Div(), right=filename)]
    if name in _TARGET_FIRST:
        targets = [first] if first is not None else []
        targets += [item.value for item in call.keywords if item.arg in {"dir", "prefix", "suffix", "filename", "base_name", "database"}]
        if name == "sqlite3.connect" and targets and any(
            k.arg == "uri" and isinstance(k.value, ast.Constant) and k.value.value is True for k in call.keywords
        ):
            targets = [ast.Call(func=ast.Name(id="__census_sqlite_path", ctx=ast.Load()),
                                args=[targets[0]], keywords=[])]
        return name, targets
    if name == "logging.basicConfig":
        target = _argument(call, 99, "filename")
        return (name, [target]) if target is not None else None
    if isinstance(func, ast.Attribute):
        attr = func.attr
        if attr in {"execute", "executescript"} and first is not None:
            values = _string_values(first, resolve) or []
            if any(re.search(r"\b(?:VACUUM\s+INTO|ATTACH(?:\s+DATABASE)?)\b", v, re.I) for v in values):
                return f".{attr}", list(call.args)
            return None
        if attr in _RECEIVER_TARGET_METHODS:
            return f".{attr}", [func.value]
        if attr in _ARGUMENT_TARGET_METHODS:
            return f".{attr}", list(call.args) or [func.value]
        if attr in {"replace", "rename"} and len(call.args) == 1 and not call.keywords:
            return f".{attr}", [first]
        if attr == "open":
            for item in call.keywords:
                if item.arg == "mode":
                    values = _string_values(item.value, resolve)
                    if values is None or any(_mode_writes(v) for v in values):
                        return ".open", [func.value]
                    return None
            for argument in call.args[:2]:
                values = _string_values(argument, resolve)
                if values is not None and all(set(v) <= set("rwaxbtU+") for v in values):
                    return (".open", [func.value]) if any(_mode_writes(v) for v in values) else None
            for argument in call.args[:1]:
                if isinstance(argument, ast.Name) and "mode" in argument.id.lower() and not resolve(argument):
                    return ".open", [func.value]
            return None
    return None


# --------------------------------------------------------------------------- functions


@dataclass
class _Function:
    key: str                     # "<file>::<qualname>"
    module: str
    qualname: str
    node: ast.AST
    parameters: frozenset[str]
    enclosing: "_Function | None"
    assignments: dict[str, list[ast.AST]] = field(default_factory=dict)
    calls: list[ast.Call] = field(default_factory=list)
    references: list[tuple[ast.AST, ast.Call | None]] = field(default_factory=list)


@dataclass
class _File:
    relative: str
    module: str
    imports: _Imports
    module_assignments: dict[str, list[ast.AST]]
    functions: list[_Function]
    top: _Function            # the module scope as a pseudo-function


_UNTAINTED_PARAMETERS = frozenset({"self", "cls", "argv"})


class _UnknownValue(ast.AST):
    """Internal uncertainty is distinct from an actual literal None or zero filename."""


class _BodyWalker(ast.NodeVisitor):
    """Collect one scope's assignments, calls and name references, without entering nested defs."""

    def __init__(self, function: _Function) -> None:
        self.function = function
        self.call_stack: list[ast.Call] = []

    def visit_FunctionDef(self, node):  # nested scopes are separate functions
        return None

    visit_AsyncFunctionDef = visit_ClassDef = visit_FunctionDef

    def _record_target(self, target: ast.AST, value: ast.AST) -> None:
        for leaf in ast.walk(target):
            if isinstance(leaf, ast.Name):
                self.function.assignments.setdefault(leaf.id, []).append(value)

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            self._record_target(target, node.value)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is not None:
            self._record_target(node.target, node.value)
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        self._record_target(node.target, node.value)
        self.generic_visit(node)

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        self._record_target(node.target, node.value)
        self.generic_visit(node)

    def visit_For(self, node: ast.For) -> None:
        self._record_target(node.target, node.iter)
        self.generic_visit(node)

    visit_AsyncFor = visit_For

    def visit_withitem(self, node: ast.withitem) -> None:
        if node.optional_vars is not None:
            self._record_target(node.optional_vars, node.context_expr)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        self.function.calls.append(node)
        self.call_stack.append(node)
        self.generic_visit(node)
        self.call_stack.pop()

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Load):
            self.function.references.append((node, self.call_stack[-1] if self.call_stack else None))

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if isinstance(node.ctx, ast.Load):
            self.function.references.append((node, self.call_stack[-1] if self.call_stack else None))
        self.generic_visit(node)


def _parameters(node: ast.AST) -> frozenset[str]:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
        arguments = node.args
        names = [a.arg for a in [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs]]
        names += [a.arg for a in (arguments.vararg, arguments.kwarg) if a is not None]
        return frozenset(names) - _UNTAINTED_PARAMETERS
    return frozenset()


def _load_file(root: Path, relative: str) -> _File:
    tree = ast.parse((root / relative).read_text(encoding="utf-8"), filename=relative)
    module = _module_name(relative)
    imports = _collect_imports(tree, module, relative.endswith("__init__.py"))
    top = _Function(f"{relative}::<module>", module, "<module>", tree, frozenset(), None)
    _BodyWalker(top).visit(tree)
    functions: list[_Function] = []

    def visit(node: ast.AST, prefix: str, enclosing: _Function | None) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qualname = f"{prefix}{child.name}"
                function = _Function(f"{relative}::{qualname}", module, qualname, child,
                                     _parameters(child), enclosing)
                walker = _BodyWalker(function)
                for statement in child.body:
                    walker.visit(statement)
                for default in [*child.args.defaults, *child.args.kw_defaults]:
                    if default is not None:
                        walker.visit(default)
                functions.append(function)
                visit(child, f"{qualname}.", function)
            elif isinstance(child, ast.ClassDef):
                visit(child, f"{prefix}{child.name}.", enclosing)
            elif not isinstance(child, ast.Lambda):
                visit(child, prefix, enclosing)

    visit(tree, "", None)
    return _File(relative, module, imports, top.assignments, functions, top)


class _Program:
    """Every scanned file, a function index, and the derived path-parameter writers."""

    def __init__(self, root: Path) -> None:
        self.files = [_load_file(root, relative) for relative in scanned_files(root)]
        self.by_name: dict[str, _Function] = {}
        for file in self.files:
            for function in file.functions:
                self.by_name.setdefault(f"{file.module}.{function.qualname}", function)
        self.file_of = {function.key: file for file in self.files for function in [file.top, *file.functions]}
        self.writers = self._derive_writers()

    def resolver(self, function: _Function):
        file = self.file_of[function.key]

        def resolve(name: ast.Name) -> list[ast.AST]:
            scope: _Function | None = function
            while scope is not None:
                if name.id in scope.assignments:
                    return scope.assignments[name.id]
                scope = scope.enclosing
            return file.module_assignments.get(name.id, [])

        return resolve

    def resolve_function(self, function: _Function, node: ast.AST) -> _Function | None:
        file = self.file_of[function.key]
        if isinstance(node, ast.Name):
            dotted = file.imports.names.get(node.id)
            if dotted and dotted in self.by_name:
                return self.by_name[dotted]
            scope: _Function | None = function
            while scope is not None and scope.qualname != "<module>":
                candidate = self.by_name.get(f"{file.module}.{scope.qualname}.{node.id}")
                if candidate is not None:
                    return candidate
                scope = scope.enclosing
            return self.by_name.get(f"{file.module}.{node.id}")
        if isinstance(node, ast.Attribute):
            base = file.imports.qualify(node.value)
            return self.by_name.get(f"{base}.{node.attr}") if base else None
        return None

    def _tainted(self, function: _Function) -> set[str]:
        tainted = set(function.parameters)
        scope = function.enclosing
        while scope is not None:
            tainted |= self._tainted_cache.get(scope.key, set())
            scope = scope.enclosing
        changed = True
        while changed:
            changed = False
            for name, values in function.assignments.items():
                if name not in tainted and any(_references(value, tainted) for value in values):
                    tainted.add(name)
                    changed = True
        return tainted

    def _derive_writers(self) -> set[str]:
        self._tainted_cache: dict[str, set[str]] = {}
        functions = [f for file in self.files for f in file.functions]
        for function in functions:   # enclosing functions precede nested ones in this order
            self._tainted_cache[function.key] = self._tainted(function)
        writers: set[str] = set()
        changed = True
        while changed:
            changed = False
            for function in functions:
                if function.key in writers or not self._tainted_cache[function.key]:
                    continue
                tainted = self._tainted_cache[function.key]
                file = self.file_of[function.key]
                resolve = self.resolver(function)
                for call in function.calls:
                    primitive = write_primitive(call, file.imports.qualify, resolve)
                    if primitive and any(_references(t, tainted) for t in primitive[1]):
                        writers.add(function.key)
                        changed = True
                        break
                    callee = self.resolve_function(function, call.func) if isinstance(call.func, (ast.Name, ast.Attribute)) else None
                    if callee is not None and callee.key in writers and any(
                        _references(arg, tainted) for arg in [*call.args, *(k.value for k in call.keywords)]
                    ):
                        writers.add(function.key)
                        changed = True
                        break
        return writers

    def sites(self, function: _Function) -> list[tuple[str, list[ast.AST]]]:
        """Every write site in ``function``: ``(kind, target expressions)``."""
        file = self.file_of[function.key]
        resolve = self.resolver(function)
        found: list[tuple[str, list[ast.AST]]] = []
        for call in function.calls:
            primitive = write_primitive(call, file.imports.qualify, resolve)
            if primitive:
                found.append(primitive)
        for node, call in function.references:
            target = self.resolve_function(function, node)
            if target is None or target.key not in self.writers or target.key == function.key:
                continue
            if isinstance(node, ast.Name) and node.id in function.assignments:
                continue  # a local rebinding of the name, not the writer
            targets: list[ast.AST] = []
            if call is not None:
                callee = self.resolve_function(function, call.func)
                if callee is target:
                    targets = self._writer_targets(target, call)
                elif callee is not None:
                    targets = self._callback_targets(callee, call, target, node)
                else:
                    # Unknown callback dispatch cannot establish a target-parameter mapping.
                    # Retain its possible literals rather than silently discarding evidence.
                    targets = [*call.args, *(k.value for k in call.keywords)]
            found.append((f"writer:{target.key}", targets))
        return found

    def _bindings(self, function: _Function, call: ast.Call) -> dict[str, ast.AST]:
        args = function.node.args
        parameters = [*args.posonlyargs, *args.args]
        bindings = {parameter.arg: value for parameter, value in zip(parameters, call.args)}
        defaults = dict(zip([p.arg for p in parameters[-len(args.defaults):]], args.defaults)) if args.defaults else {}
        default_scope = function.enclosing or self.file_of[function.key].top
        for name, value in defaults.items():
            bindings.setdefault(name, self._expanded(default_scope, value, {}))
        if args.vararg:
            bindings[args.vararg.arg] = ast.Tuple(elts=call.args[len(parameters):], ctx=ast.Load())
        for keyword in call.keywords:
            if keyword.arg is not None:
                bindings[keyword.arg] = keyword.value
        if args.kwarg:
            extra = [k for k in call.keywords if k.arg is not None and k.arg not in function.parameters]
            bindings[args.kwarg.arg] = ast.Dict(
                keys=[ast.Constant(k.arg) for k in extra], values=[k.value for k in extra])
        for parameter, default in zip(args.kwonlyargs, args.kw_defaults):
            if default is not None:
                bindings.setdefault(parameter.arg, self._expanded(default_scope, default, {}))
        return bindings

    def _expanded(self, function: _Function, node: ast.AST, bindings: dict[str, ast.AST],
                  seen: frozenset[str] = frozenset()) -> ast.AST:
        if isinstance(node, ast.Name):
            if node.id in bindings:
                return bindings[node.id]  # this expression belongs to the caller's scope
            if node.id in seen:
                return _UnknownValue()
            values = self.resolver(function)(node)
            if values:
                expanded = [self._expanded(function, v, bindings, seen | {node.id}) for v in values]
                return expanded[0] if len(expanded) == 1 else ast.BoolOp(op=ast.Or(), values=expanded)
            return _UnknownValue()
        expanded = copy.copy(node)
        for name, value in ast.iter_fields(node):
            if isinstance(node, ast.Call) and name == "func":
                continue  # preserve Path/str/path constructors; substitute their arguments
            if isinstance(value, ast.AST):
                setattr(expanded, name, self._expanded(function, value, bindings, seen))
            elif isinstance(value, list):
                setattr(expanded, name, [self._expanded(function, v, bindings, seen)
                                        if isinstance(v, ast.AST) else v for v in value])
        if (isinstance(expanded, ast.Subscript) and isinstance(expanded.value, (ast.Tuple, ast.List))
                and isinstance(expanded.slice, ast.Constant) and isinstance(expanded.slice.value, int)):
            index = expanded.slice.value
            if -len(expanded.value.elts) <= index < len(expanded.value.elts):
                return expanded.value.elts[index]
        return expanded

    def _expanded_call(self, function: _Function, call: ast.Call,
                       bindings: dict[str, ast.AST]) -> ast.Call:
        args: list[ast.AST] = []
        keywords: list[ast.keyword] = []
        for argument in call.args:
            value = self._expanded(function, argument.value if isinstance(argument, ast.Starred) else argument, bindings)
            if isinstance(argument, ast.Starred) and isinstance(value, (ast.Tuple, ast.List)):
                args.extend(value.elts)
            else:
                args.append(value)
        for keyword in call.keywords:
            value = self._expanded(function, keyword.value, bindings)
            if keyword.arg is None and isinstance(value, ast.Dict):
                keywords.extend(ast.keyword(arg=k.value, value=v) for k, v in zip(value.keys, value.values)
                                if isinstance(k, ast.Constant) and isinstance(k.value, str))
            else:
                keywords.append(ast.keyword(arg=keyword.arg, value=value))
        return ast.Call(func=call.func, args=args, keywords=keywords)

    def _writer_targets(self, function: _Function, call: ast.Call,
                        seen: frozenset[str] = frozenset()) -> list[ast.AST]:
        if function.key in seen:
            return []
        bindings = self._bindings(function, call)
        targets: list[ast.AST] = []
        file = self.file_of[function.key]
        for inner in function.calls:
            primitive = write_primitive(inner, file.imports.qualify, self.resolver(function))
            if primitive:
                for target in primitive[1]:
                    expanded = self._expanded(function, target, bindings)
                    row = WRITE_SITE_CENSUS.get(function.key)
                    if row is not None and row[1] == NON_CLIENT:
                        expanded = copy.copy(expanded)
                        expanded.census_non_client_origin = function.key
                    targets.append(expanded)
            else:
                callee = self.resolve_function(function, inner.func)
                if callee is not None and callee.key in self.writers:
                    targets.extend(self._writer_targets(callee, self._expanded_call(function, inner, bindings),
                                                        seen | {function.key}))
        return targets

    def _callback_targets(self, wrapper: _Function, call: ast.Call, target: _Function,
                          reference: ast.AST, seen: frozenset[str] = frozenset()) -> list[ast.AST]:
        if wrapper.key in seen:
            return []
        bindings = self._bindings(wrapper, call)
        targets: list[ast.AST] = []
        identity = ast.dump(reference, include_attributes=False)
        for inner in wrapper.calls:
            expanded = self._expanded_call(wrapper, inner, bindings)
            if isinstance(inner.func, ast.Name) and inner.func.id in bindings:
                if ast.dump(bindings[inner.func.id], include_attributes=False) == identity:
                    targets.extend(self._writer_targets(target, expanded))
            else:
                callee = self.resolve_function(wrapper, inner.func)
                if callee is not None and any(ast.dump(n, include_attributes=False) == identity
                                              for a in [*expanded.args, *(k.value for k in expanded.keywords)]
                                              for n in ast.walk(a)):
                    targets.extend(self._callback_targets(callee, expanded, target, reference,
                                                          seen | {wrapper.key}))
        return targets


def _references(node: ast.AST, names: set[str]) -> bool:
    return any(isinstance(leaf, ast.Name) and leaf.id in names for leaf in ast.walk(node))


def _identifying_suffix(node: ast.AST, resolve, seen: frozenset[str] = frozenset()) -> bool:
    """Only a terminal sidecar suffix is an obligation, never literals inside an input stem."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return bool(_SUFFIX_LITERAL.match(node.value))
    if isinstance(node, ast.Name) and node.id not in seen:
        return any(_identifying_suffix(value, resolve, seen | {node.id}) for value in resolve(node))
    if isinstance(node, ast.JoinedStr) and node.values:
        return _identifying_suffix(node.values[-1], resolve, seen)
    if isinstance(node, ast.FormattedValue):
        return _identifying_suffix(node.value, resolve, seen)
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Div)):
        return _identifying_suffix(node.right, resolve, seen)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
        return bool(_SUFFIX_LITERAL.match(_tail(_constant_text(node.left) or "")))
    if isinstance(node, ast.Call) and node.args:
        if isinstance(node.func, ast.Name) and node.func.id in {"Path", "PurePath", "PurePosixPath", "str"}:
            return _identifying_suffix(node.args[-1], resolve, seen)
        if isinstance(node.func, ast.Attribute):
            if node.func.attr in {"join", "with_suffix", "with_name"}:
                return _identifying_suffix(node.args[-1], resolve, seen)
            if node.func.attr == "format":
                return bool(_SUFFIX_LITERAL.match(_tail(_constant_text(node.func.value) or "")))
    return False


def scan(root: Path = ROOT) -> tuple[dict[str, int], set[str]]:
    """Return ``({"path::qualname": write count}, {path-parameter writer keys})``."""
    counts, writers, _resolved = analysis(root)
    return counts, writers


def write_sites(root: Path = ROOT) -> dict[str, int]:
    return analysis(root)[0]


# --------------------------------------------------------------------------- resolved names

class _NameTemplate(str):
    """Keep literal certainty separate from the placeholder text used for name-class matching."""

    complete: bool
    identifying: bool

    def __new__(cls, text: str, complete: bool = True):
        value = str.__new__(cls, text)
        value.complete = complete
        value.identifying = False
        return value


def _combine_names(left: str | None, right: str | None) -> _NameTemplate | None:
    if left is None and right is None:
        return None
    result = _NameTemplate((left if left is not None else "0") + (right if right is not None else "0"),
                           left is not None and right is not None
                           and getattr(left, "complete", True) and getattr(right, "complete", True))
    result.identifying = getattr(right, "identifying", False)
    return result


_NOT_CLOSED = object()


def _closed_values(node: ast.AST, resolve, depth: int, seen: frozenset[str] = frozenset()) -> list[object] | None:
    _name_depth(depth)
    if isinstance(node, ast.Name):
        if node.id in seen:
            return [_NOT_CLOSED]
        values = resolve(node)
        if not values:
            return None
        out: list[object] = []
        for value in values:
            closed = _closed_values(value, resolve, depth + 1, seen | {node.id})
            out.extend([_NOT_CLOSED] if closed is None else closed)
        return _bounded_names(out)
    if isinstance(node, (ast.Tuple, ast.List, ast.Dict)):
        if isinstance(node, ast.Dict):
            if any(k is None for k in node.keys):
                return None
            children = [*node.keys, *node.values]
        else:
            children = node.elts
        values = [_closed_values(child, resolve, depth + 1, seen) or [_NOT_CLOSED] for child in children]
        combinations = _name_product(*values)
        if isinstance(node, ast.Dict):
            size = len(node.keys)
            return [_NOT_CLOSED if any(p is _NOT_CLOSED for p in parts)
                    else dict(zip(parts[:size], parts[size:])) for parts in combinations]
        return [_NOT_CLOSED if any(p is _NOT_CLOSED for p in parts) else
                tuple(parts) if isinstance(node, ast.Tuple) else list(parts) for parts in combinations]
    try:
        return [ast.literal_eval(node)]
    except (ValueError, TypeError, SyntaxError):
        return None


_NAME_ALTERNATIVES = 256
_NAME_DEPTH = 32
_NAME_BYTES = 16_384


class NameModelLimit(ValueError):
    """An incomplete census is a refusal, never a truncated successful census."""


def _name_depth(depth: int) -> None:
    if depth > _NAME_DEPTH:
        raise NameModelLimit("filename model depth exceeded; review the unresolved target")


def _bounded_names(values: list, *, text_limit: bool = True):
    if len(values) > _NAME_ALTERNATIVES:
        raise NameModelLimit("filename model alternatives exceeded; no target was discarded")
    if text_limit and any(isinstance(value, str) and len(value) > _NAME_BYTES for value in values):
        raise NameModelLimit("filename model output length exceeded")
    return values


def _name_product(*values: list) -> list[tuple]:
    size = 1
    for value in values:
        size *= len(value)
        if size > _NAME_ALTERNATIVES:
            raise NameModelLimit("filename model alternatives exceeded; no target was discarded")
    return list(itertools.product(*values))


def _format_bound(spec: str) -> None:
    if len(spec) > 64 or any(int(n) > 4096 for n in re.findall(r"\d+", spec)):
        raise NameModelLimit("formatted filename specification exceeds the bounded name model")


def _partial_format(pattern: str, *, percent: bool = False) -> _NameTemplate:
    if percent:
        text = re.sub(r"%(?:\([^)]*\))?[-#0 +]*\d*(?:\.\d+)?[A-Za-z]", "0", pattern)
        tail = re.split(r"%(?:\([^)]*\))?[-#0 +]*\d*(?:\.\d+)?[A-Za-z]", pattern)[-1]
        complete = text == pattern and "%" not in pattern
    else:
        pieces = list(string.Formatter().parse(pattern))
        text = "".join(literal + ("0" if field is not None else "") for literal, field, _s, _c in pieces)
        tail = pieces[-1][0] if pieces and pieces[-1][1] is None else ""
        complete = all(field is None for _literal, field, _s, _c in pieces)
    result = _NameTemplate(text, complete)
    result.identifying = bool(_SUFFIX_LITERAL.match(tail))
    return result


def _closed_format(node: ast.AST, resolve, depth: int, seen: frozenset[str]) -> list[str | None] | None:
    """Evaluate only closed builtin format operands, never execute source functions."""
    if isinstance(node, ast.BinOp):
        patterns = _closed_values(node.left, resolve, depth + 1, seen)
        operands = _closed_values(node.right, resolve, depth + 1, seen) or [_NOT_CLOSED]
        if patterns is None:
            return None
        out = []
        for pattern, operand in _name_product(patterns, operands):
            if pattern is _NOT_CLOSED:
                out.append(None)
                continue
            if not isinstance(pattern, str):
                raise NameModelLimit("percent filename pattern is not a string")
            if operand is _NOT_CLOSED:
                out.append(_partial_format(pattern, percent=True))
                continue
            # Bound numeric widths before invoking Python's actual percent semantics.
            for field in re.findall(r"%(?:\([^)]*\))?[-#0 +]*[\d.*]*[A-Za-z%]", pattern):
                _format_bound(field)
                if "*" in field:
                    raise NameModelLimit("dynamic percent width requires a reviewed filename model")
            try:
                out.append(_NameTemplate(pattern % operand))
            except (TypeError, ValueError, KeyError):
                raise NameModelLimit("closed percent filename cannot be evaluated") from None
        return _bounded_names(out)
    assert isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    patterns = _closed_values(node.func.value, resolve, depth + 1, seen)
    positional = [_closed_values(a, resolve, depth + 1, seen) or [_NOT_CLOSED] for a in node.args]
    keywords = [_closed_values(k.value, resolve, depth + 1, seen) or [_NOT_CLOSED] for k in node.keywords]
    if patterns is None:
        return None
    if any(k.arg is None for k in node.keywords) or any(isinstance(a, ast.Starred) for a in node.args):
        return None
    out = []
    formatter = string.Formatter()
    for pattern, *parts in _name_product(patterns, *positional, *keywords):
        if pattern is _NOT_CLOSED:
            out.append(None)
            continue
        if not isinstance(pattern, str):
            raise NameModelLimit("format filename pattern is not a string")
        if any(p is _NOT_CLOSED for p in parts):
            out.append(_partial_format(pattern))
            continue
        args = parts[:len(positional)]
        kwargs = dict(zip((k.arg for k in node.keywords), parts[len(positional):]))
        try:
            for _literal, _field, spec, _conversion in formatter.parse(pattern):
                # Nested width/precision is resolved from the same closed builtin operands.
                if _field is None:
                    continue
                _format_bound(spec)
                _format_bound(formatter.vformat(spec, args, kwargs))
            out.append(_NameTemplate(pattern.format(*args, **kwargs)))
        except (TypeError, ValueError, KeyError, IndexError, AttributeError):
            raise NameModelLimit("closed format filename cannot be evaluated") from None
    return _bounded_names(out)


def _formatted_names(part: ast.FormattedValue, resolve, depth: int, seen: frozenset[str]) -> list[str | None]:
    values = _closed_values(part.value, resolve, depth, seen)
    if values is None:
        return [None]
    specs = ([_NameTemplate("")] if part.format_spec is None
             else _templates(part.format_spec, resolve, depth + 1, seen))
    out: list[str | None] = []
    for value in values:
        if value is _NOT_CLOSED:
            out.append(None)
            continue
        if part.conversion == ord("r"):
            value = repr(value)
        elif part.conversion == ord("s"):
            value = str(value)
        elif part.conversion == ord("a"):
            value = ascii(value)
        for spec in specs:
            if spec is None or not getattr(spec, "complete", True):
                out.append(None)
                continue
            _format_bound(spec)
            try:
                out.append(_NameTemplate(format(value, spec)))
            except (ValueError, TypeError):
                out.append(None)
    return _bounded_names(out)


def _templates(node: ast.AST, resolve, depth: int = 0, seen: frozenset[str] = frozenset()) -> list[str | None]:
    """Literal templates; None is wholly unknown, while a partial unknown is spelled ``0``."""
    _name_depth(depth)
    text = _constant_text(node)
    if text is not None:
        return [_NameTemplate(text)]
    if isinstance(node, ast.JoinedStr):
        out: list[str | None] = [_NameTemplate("")]
        for part in node.values:
            pieces = (_formatted_names(part, resolve, depth + 1, seen) if isinstance(part, ast.FormattedValue)
                      else _templates(part, resolve, depth + 1, seen))
            out = _bounded_names([_combine_names(a, b) for a, b in _name_product(out, pieces)])
        return out
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _bounded_names([_combine_names(a, b) for a, b in _name_product(
            _templates(node.left, resolve, depth + 1, seen), _templates(node.right, resolve, depth + 1, seen))])
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return _templates(node.right, resolve, depth + 1, seen)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
        closed = _closed_format(node, resolve, depth, seen)
        if closed is not None:
            return closed
        if _constant_text(node.left):
            return [_NameTemplate(re.sub(r"%[-#0 +]*\d*(?:\.\d+)?[sdifrx]", "0", _constant_text(node.left)), False)]
    if isinstance(node, ast.Name):
        if node.id in seen:
            return [None]  # cyclic branch is unknown; other concrete alternatives still survive
        values = resolve(node)
        out = [t for value in values for t in _templates(value, resolve, depth + 1, seen | {node.id})]
        return _bounded_names(out) or [None]
    if isinstance(node, (ast.List, ast.Tuple)):
        return _bounded_names([t for value in node.elts for t in _templates(value, resolve, depth + 1, seen)])
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "join" and node.args:
            return _templates(node.args[-1], resolve, depth + 1, seen)
        if isinstance(func, ast.Attribute) and func.attr in {"with_suffix", "with_name"} and node.args:
            return [_NameTemplate("0" + t, False) if func.attr == "with_suffix" and t is not None else t
                    for t in _templates(node.args[0], resolve, depth + 1, seen)]
        if isinstance(func, ast.Attribute) and func.attr == "format":
            closed = _closed_format(node, resolve, depth, seen)
            if closed is not None:
                return closed
            if _constant_text(func.value):
                return [_NameTemplate(re.sub(r"\{[^{}]*\}", "0", _constant_text(func.value)), False)]
        if isinstance(func, ast.Name) and func.id == "__census_sqlite_path" and node.args:
            return [_NameTemplate(unquote(t.removeprefix("file:").split("?", 1)[0]),
                                  getattr(t, "complete", True)) if t is not None else None
                    for t in _templates(node.args[0], resolve, depth + 1, seen)]
        if isinstance(func, ast.Name) and func.id in {"Path", "PurePath", "PurePosixPath", "str"} and node.args:
            return _templates(node.args[-1], resolve, depth + 1, seen)
    if isinstance(node, ast.IfExp):
        return _bounded_names(_templates(node.body, resolve, depth + 1, seen) + _templates(node.orelse, resolve, depth + 1, seen))
    if isinstance(node, ast.BoolOp):
        return _bounded_names([t for value in node.values for t in _templates(value, resolve, depth + 1, seen)])
    return [None]


def resolved_site_classes(root: Path = ROOT) -> dict[str, set[str]]:
    """``{function key: registry classes of every literal name its write sites resolve to}``."""
    return analysis(root)[2]


# --------------------------------------------------------------------------- suffix literals

#: A stem suffix: starts with ".", "_" or "-", has a name part, and ends with an extension. Only "."
#: separates segments, so no input has two ways to match (an earlier "[.-]" separator overlapped
#: the name class and could backtrack exponentially). A bare extension such as ".txt" carries no
#: artifact identity and is not collected.
_SUFFIX_LITERAL = re.compile(r"^[._-][A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*\.[A-Za-z0-9]+$")
_PLACEHOLDER = re.compile(r"%[-#0 +]*\d*(?:\.\d+)?[sdifrx]|\{[^{}]*\}")


def _tail(template: str) -> str:
    """The literal text after the last substitution of a ``%`` or ``.format`` template."""
    pieces = _PLACEHOLDER.split(template)
    return pieces[-1] if len(pieces) > 1 else ""


def suffix_literals(root: Path = ROOT) -> list[tuple[str, str]]:
    """Every ``(file:line, literal)`` appended to an output stem in a scanned file."""
    found: list[tuple[str, str]] = []
    for relative in scanned_files(root):
        tree = ast.parse((root / relative).read_text(encoding="utf-8"), filename=relative)
        for node in ast.walk(tree):
            literals: list[str] = []
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
                literals.append(_constant_text(node.right) or "")
            elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
                literals.append(_tail(_constant_text(node.left) or ""))
            elif (
                isinstance(node, ast.JoinedStr)
                and len(node.values) >= 2
                and isinstance(node.values[-2], ast.FormattedValue)
            ):
                literals.append(_constant_text(node.values[-1]) or "")
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                attr = node.func.attr
                if attr == "format":
                    literals.append(_tail(_constant_text(node.func.value) or ""))
                elif attr in {"with_suffix", "with_name"} and node.args:
                    literals.append(_constant_text(node.args[0]) or "")
                elif attr == "join" and node.args and isinstance(node.args[0], (ast.List, ast.Tuple)):
                    elements = node.args[0].elts
                    literals.append(_constant_text(elements[-1]) if elements else "")
            for literal in literals:
                if literal and _SUFFIX_LITERAL.match(literal):
                    found.append((f"{relative}:{node.lineno}", literal))
    return sorted(set(found))


# --------------------------------------------------------------------------- .gitignore block

GITIGNORE_BEGIN = "# BEGIN GENERATED CLIENT ARTIFACT NAME CLASSES (W65)"
GITIGNORE_END = "# END GENERATED CLIENT ARTIFACT NAME CLASSES"


def _any_case(text: str) -> str:
    return "".join(f"[{c.lower()}{c.upper()}]" if c.isalpha() else c for c in text)


def gitignore_block(classes=None, exceptions=None) -> str:
    """The exact, case-insensitive ``.gitignore`` block for every registered class."""
    if classes is None or exceptions is None:
        from cisco_toolkit.distribution_verify import (
            CLIENT_ARTIFACT_EXCEPTIONS,
            CLIENT_ARTIFACT_NAME_CLASSES,
        )

        classes = CLIENT_ARTIFACT_NAME_CLASSES if classes is None else classes
        exceptions = CLIENT_ARTIFACT_EXCEPTIONS if exceptions is None else exceptions
    lines = [
        GITIGNORE_BEGIN,
        "# Generated from cisco_toolkit/distribution_verify.py :: CLIENT_ARTIFACT_NAME_CLASSES by",
        "# tests/client_artifact_census.py :: gitignore_block; tests/test_client_artifact_census.py",
        "# keeps it exact. Case-insensitive on purpose: a case-sensitive checkout must ignore",
        "# ACME.XLSX as well as acme.xlsx. The negations are the registry's reviewed exceptions.",
    ]
    for _key, match, pattern, *_producer in classes:
        if match == "suffix":
            lines.append(f"*{_any_case(pattern)}")
        elif match == "leaf":
            lines.append(_any_case(pattern))
        elif match == "leaf-prefix":
            lines.append(f"{_any_case(pattern)}*")
        elif match == "contains":
            lines.append(f"*{_any_case(pattern)}*")
        elif match == "capture":
            lines.append(f"{_any_case(pattern)}*{_any_case('.txt')}")
        else:
            raise ValueError(f"unknown client-artifact match {match!r}")
    lines += [f"!/{path}" for path in sorted(exceptions)]
    lines.append(GITIGNORE_END)
    return "\n".join(lines) + "\n"


def gitignore_block_in(text: str) -> str | None:
    """The generated block as it stands in ``.gitignore`` text, or None when absent or duplicated."""
    if text.count(GITIGNORE_BEGIN) != 1 or text.count(GITIGNORE_END) != 1:
        return None
    start = text.index(GITIGNORE_BEGIN)
    end = text.index(GITIGNORE_END) + len(GITIGNORE_END)
    return text[start:end].replace("\r\n", "\n") + "\n"


# --------------------------------------------------------------------------- download names

# Browser source discovery is independent of product roots. Build/vendor outputs are
# derivatives, not authored sources; their source files remain in this scan.
_BROWSER_SUFFIXES = frozenset({".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".html", ".py"})
_BROWSER_DERIVATIVES = frozenset({"dist", "dist-hub", "node_modules", "vendor", "__pycache__"})

#: Download-name expressions that are not literals, each with why its name still classifies.
DOWNLOAD_NAME_PASSTHROUGH: Mapping[tuple[str, str], str] = {
    ("webapp/frontend/src/receiptExport.ts", "filename"):
        "downloadJsonDocument's own parameter; every caller's name is a scanned download name",
    ("webapp/frontend/src/components/ComparisonDecision.tsx", "safeFilename(filename)"):
        "safeFilename appends COMPARISON_RECEIPT_SUFFIX to any caller name (unit-tested)",
    ("webapp/frontend/src/components/ComparisonDecision.tsx", "DEFAULT_COMPARISON_EXPORT"):
        "atlas-receipt + COMPARISON_RECEIPT_SUFFIX",
    ("cisco_toolkit/blast_radius_explorer.html", "filename"):
        "downloadBlob's own parameter; every direct caller's filename is scanned",
}


def _is_frontend_test(relative: str) -> bool:
    name = relative.rsplit("/", 1)[-1]
    return bool(re.search(r"\.(test|spec)\.[cm]?[jt]sx?$", name)) or "/e2e" in relative or "/__tests__/" in relative


def download_sources(root: Path = ROOT) -> list[str]:
    """Every tracked authored browser language and Python HTML/JS generator, in every root."""
    if (root / ".git").exists():
        listed = subprocess.run(["git", "ls-files", "-z"], cwd=root, check=True,
                                capture_output=True).stdout.decode("utf-8").split("\0")
    else:
        listed = [p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()]
    return sorted(p for p in listed if Path(p).suffix in _BROWSER_SUFFIXES
                  and not (set(Path(p).parts) & (_BROWSER_DERIVATIVES | _SKIPPED_DIRECTORIES))
                  and not is_test_path(p) and not _is_frontend_test(p))


def _js_parts(text: str, start: int, stop: str, separator: str) -> list[str]:
    """Split a direct JS argument/concatenation expression without splitting nested values.

    This is a bounded lexical reader, not execution or general JS data-flow inference. Unknown
    expressions remain unknown and require an explicit pass-through declaration.
    """
    parts: list[str] = []
    depth = 0
    quote = ""
    begin = start
    index = start
    while index < len(text):
        char = text[index]
        if quote:
            if char == "\\":
                index += 2
                continue
            if char == quote:
                quote = ""
        elif char in "\"'`":
            quote = char
        elif text[index:index + 2] == "//":
            end = text.find("\n", index + 2)
            index = len(text) if end < 0 else end
            continue
        elif text[index:index + 2] == "/*":
            end = text.find("*/", index + 2)
            index = len(text) if end < 0 else end + 2
            continue
        elif char == stop and depth == 0:
            parts.append(text[begin:index].strip())
            return parts
        elif char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        elif char == separator and depth == 0:
            parts.append(text[begin:index].strip())
            begin = index + 1
        index += 1
    if not stop:
        parts.append(text[begin:].strip())
    return parts


class _HtmlDownloads(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.names: list[tuple[int, str, str | None]] = []
        self.scripts: list[tuple[int, str]] = []
        self.in_script = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "script":
            self.in_script = True
        if "download" in values:
            name = values["download"]
            expression = repr(name) if name else "<implicit browser filename>"
            self.names.append((self.getpos()[0], expression, name or None))

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self.in_script = False

    def handle_data(self, data: str) -> None:
        if self.in_script:
            self.scripts.append((self.getpos()[0], data))


@dataclass(frozen=True)
class _JsToken:
    value: str
    start: int
    end: int
    line: int


def _js_tokens(text: str, *, jsx: bool = False) -> list[_JsToken]:
    """Lex strings/templates/comments as units; formatting and ASI do not hide exits."""
    tokens = []
    index = 0
    line = 1
    jsx_levels = 0
    tag_mode = False
    tag_closing = False
    expression_frames: list[list[int]] = []

    def regex_end(start: int) -> int:
        cursor = start + 1
        in_class = False
        while cursor < len(text):
            if text[cursor] == "\\":
                cursor += 2
                continue
            if text[cursor] == "[":
                in_class = True
            elif text[cursor] == "]":
                in_class = False
            elif text[cursor] == "/" and not in_class:
                cursor += 1
                while cursor < len(text) and text[cursor].isalpha():
                    cursor += 1
                return cursor
            elif text[cursor] == "\n":
                break
            cursor += 1
        raise ValueError("unterminated browser regex literal")

    def quoted_end(start: int, depth: int = 0) -> int:
        if depth > 128:
            raise ValueError("browser token nesting bound exceeded")
        quote = text[start]
        cursor = start + 1
        while cursor < len(text):
            if text[cursor] == "\\":
                cursor += 2
            elif text[cursor] == quote:
                return cursor + 1
            elif quote == "`" and text[cursor:cursor + 2] == "${":
                cursor += 2
                braces = 1
                while cursor < len(text) and braces:
                    if text[cursor:cursor + 2] == "//":
                        end = text.find("\n", cursor + 2)
                        cursor = len(text) if end < 0 else end
                        continue
                    if text[cursor:cursor + 2] == "/*":
                        end = text.find("*/", cursor + 2)
                        if end < 0:
                            raise ValueError("unterminated browser template comment")
                        cursor = end + 2
                        continue
                    if text[cursor] == "/" and text[:cursor].rstrip().endswith((
                        "(", "=", ":", ",", "[", "!", "?", "return", "=>", "&&", "||", "??"
                    )):
                        cursor = regex_end(cursor)
                        continue
                    if text[cursor] in "\"'`":
                        cursor = quoted_end(cursor, depth + 1)
                        continue
                    if text[cursor] == "{":
                        braces += 1
                    elif text[cursor] == "}":
                        braces -= 1
                    cursor += 1
                if braces:
                    raise ValueError("unterminated browser template expression")
            else:
                cursor += 1
        raise ValueError("unterminated browser string")
    while index < len(text):
        begin, first_line = index, line
        char = text[index]
        child_text = jsx_levels > (expression_frames[-1][1] if expression_frames else 0) and not tag_mode
        if jsx and child_text and char not in {"<", "{"}:
            line += char == "\n"
            index += 1
            continue  # JSX prose is not a quoted JS expression, even when it contains apostrophes
        if jsx and char == "<" and index + 1 < len(text) and (
            text[index + 1].isalpha() or text[index + 1] in {"/", ">"}
        ) and (child_text or not tokens or tokens[-1].value in {
            "(", "=", "return", "=>", "?", ":", "&&", "||", "??", ",", "["
        }) and not re.match(r"<[A-Za-z_$][\w$]*(?:\s*,|\s+extends\b|\s*>\s*\()", text[index:]):
            tag_mode = True
            tag_closing = text[index + 1] == "/"
        if jsx and char == "{" and (child_text or tag_mode):
            expression_frames.append([0, jsx_levels, int(tag_mode), int(tag_closing)])
            tag_mode = False
        if jsx and expression_frames and not tag_mode:
            if char == "{":
                expression_frames[-1][0] += 1
            elif char == "}":
                expression_frames[-1][0] -= 1
                if expression_frames[-1][0] == 0:
                    closed = expression_frames.pop()
                    tag_mode, tag_closing = bool(closed[2]), bool(closed[3])
        if jsx and char == ">" and tag_mode:
            if tag_closing:
                jsx_levels -= 1
            elif not tokens or tokens[-1].value != "/":
                jsx_levels += 1
            tag_mode = False
        if char.isspace():
            line += char == "\n"
            index += 1
            continue
        if text[index:index + 2] in {"//", "/*"}:
            if text[index:index + 2] == "//":
                end = text.find("\n", index + 2)
                index = len(text) if end < 0 else end
            else:
                end = text.find("*/", index + 2)
                if end < 0:
                    raise ValueError("unterminated browser comment")
                index = end + 2
            line += text[begin:index].count("\n")
            continue
        if char in "\"'`":
            index = quoted_end(index)
            line += text[begin:index].count("\n")
        elif char == "/" and (not tokens or tokens[-1].value in {
            "(", "=", ":", ",", "[", "!", "?", "return", "=>", "&&", "||", "??"
        }):
            # Regex literals can contain quotes, comment-looking slashes and delimiters.
            # Keep the complete regex as one token; never read its contents as JS exits.
            index = regex_end(index)
        elif char.isalnum() or char in "_$":
            index += 1
            while index < len(text) and (text[index].isalnum() or text[index] in "_$"):
                index += 1
        elif text[index:index + 2] in {"?.", "=>", "==", "!=", "+=", "&&", "||", "??"}:
            index += 2
        else:
            index += 1
        tokens.append(_JsToken(text[begin:index], begin, index, first_line))
    return tokens


def _js_expression(text: str, tokens: list[_JsToken], start: int) -> tuple[str, int]:
    if start >= len(tokens):
        return "<unresolved filename>", start
    stack = []
    index = start
    continuation = {"+", "-", "*", "/", "%", ".", "?.", "?", ":", "&&", "||", "??", "=", ","}
    while index < len(tokens):
        token = tokens[index]
        if (index == start + 1 and tokens[start].value[:1] in {"\"", "'", "`"}
                and token.value not in continuation):
            break
        if not stack:
            if token.value in {";", ",", ")", "]", "}", ">"}:
                break
            if (index > start and token.line > tokens[index - 1].line
                    and token.value not in continuation
                    and tokens[index - 1].value not in continuation):
                break  # automatic semicolon insertion, not a required literal semicolon
        if token.value in {"(", "[", "{"}:
            stack.append(token.value)
        elif token.value in {")", "]", "}"}:
            if not stack:
                break
            stack.pop()
            if not stack and index + 1 < len(tokens) and tokens[index + 1].value not in continuation:
                index += 1
                break
        index += 1
    expression = text[tokens[start].start:tokens[index - 1].end].strip() if index > start else "<unresolved filename>"
    return expression, index


def _js_arguments(text: str, tokens: list[_JsToken], opening: int) -> list[str]:
    """Split calls on token boundaries, so regex/template delimiters are never call syntax."""
    arguments = []
    stack = ["("]
    begin = opening + 1
    for index in range(begin, len(tokens)):
        value = tokens[index].value
        if value in {"(", "[", "{"}:
            stack.append(value)
        elif value in {")", "]", "}"}:
            expected = {")": "(", "]": "[", "}": "{"}[value]
            if not stack or stack.pop() != expected:
                raise ValueError("unbalanced browser call arguments")
            if not stack:
                if index > begin:
                    arguments.append(text[tokens[begin].start:tokens[index - 1].end].strip())
                return arguments
        elif value == "," and len(stack) == 1:
            arguments.append(text[tokens[begin].start:tokens[index - 1].end].strip())
            begin = index + 1
    raise ValueError("unterminated browser call arguments")


def _browser_documents(relative: str, source: str) -> list[tuple[int, str]]:
    if not relative.endswith(".py"):
        return [(1, source)]
    tree = ast.parse(source, filename=relative)
    documents = []
    bindings: dict[str, list[ast.AST]] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name) and node.value is not None:
                    bindings.setdefault(target.id, []).append(node.value)

    def expand(node: ast.AST, seen: frozenset[str] = frozenset(), depth: int = 0) -> list[str]:
        _name_depth(depth)
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return [node.value]
        if isinstance(node, ast.Name) and node.id in bindings and node.id not in seen:
            return _bounded_names([s for value in bindings[node.id]
                                   for s in expand(value, seen | {node.id}, depth + 1)], text_limit=False)
        if isinstance(node, ast.FormattedValue):
            return expand(node.value, seen, depth + 1)
        if isinstance(node, ast.JoinedStr):
            values = [""]
            for part in node.values:
                values = _bounded_names([a + b for a, b in _name_product(values, expand(part, seen, depth + 1))],
                                        text_limit=False)
            return values
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            return _bounded_names([a + b for a, b in _name_product(
                expand(node.left, seen, depth + 1), expand(node.right, seen, depth + 1))], text_limit=False)
        return ["0"]

    def visit(node: ast.AST) -> None:
        if isinstance(node, (ast.Constant, ast.JoinedStr, ast.BinOp)):
            # Language boundary, not a product/file/API subset. Every script-bearing generated
            # HTML string is read, including f-strings without executing the generator.
            for text in expand(node):
                if "<" in text:
                    documents.append((getattr(node, "lineno", 1), text))
            # Also retain independently assembled child fragments. Deduplication is performed
            # after obligations are found, never by discarding possible name alternatives.
        for child in ast.iter_child_nodes(node):
            visit(child)
    visit(tree)
    return documents


def download_names(root: Path = ROOT) -> list[tuple[str, str, str | None]]:
    """Structural direct browser exits. Unknown names remain review obligations.

    Native download assignments/attributes, object download properties (including Object.assign),
    direct download helpers/saveAs and browser-open exits are read from tokens. General aliases
    and interprocedural JS flow remain outside this static model, explicitly, not silently.
    """
    found = []
    for relative in download_sources(root):
        source = (root / relative).read_text(encoding="utf-8")
        documents = _browser_documents(relative, source)
        scripts = []
        for first_line, text in documents:
            # HTMLParser owns native HTML attributes. JS/JSX syntax belongs to tokens.
            parser = _HtmlDownloads()
            if relative.endswith((".html", ".py")):
                parser.feed(text)
                found.extend((f"{relative}:{first_line + line - 1}", expression, template)
                             for line, expression, template in parser.names)
                scripts.extend((first_line + line - 1, script) for line, script in parser.scripts)
            else:
                scripts.append((first_line, text))
        for first_line, text in scripts:
            try:
                tokens = _js_tokens(text, jsx=relative.endswith((".tsx", ".jsx", ".js")))
            except ValueError as error:
                raise ValueError(f"browser census refuses {relative}:{first_line}: {error}") from error
            in_tag = False
            tag_braces = 0
            for index, token in enumerate(tokens):
                if token.value == "<" and index + 1 < len(tokens) and (
                    tokens[index + 1].value[:1].isalpha() or tokens[index + 1].value == "/"
                ):
                    in_tag = True
                elif in_tag and token.value == "{" :
                    tag_braces += 1
                elif in_tag and token.value == "}":
                    tag_braces -= 1
                elif token.value == ">" and not tag_braces:
                    in_tag = False
                value = token.value.strip("\"'")
                after = index + 1
                if after < len(tokens) and tokens[after].value == "]":
                    after += 1  # a["download"] = ...
                if value in {"download", "exportFilename"} and after < len(tokens) and tokens[after].value in {"=", ":"}:
                    receiver_property = index > 0 and tokens[index - 1].value in {".", "?.", "["}
                    object_property = tokens[after].value == ":" and index > 0 and tokens[index - 1].value in {"{", ","}
                    if value == "download" and not (receiver_property or object_property or in_tag):
                        continue  # local download callback/variable is not a browser filename
                    # Native HTML quoted/unquoted attributes were already read by HTMLParser.
                    if relative.endswith((".html", ".py")) and tokens[after].value == "=" and (
                        index == 0 or tokens[index - 1].value not in {".", "?.", "["}
                    ):
                        continue
                    expression, _end = _js_expression(text, tokens, after + 1)
                    if expression.startswith("{") and expression.endswith("}"):
                        expression = expression[1:-1].strip()  # JSX attribute
                    found.append((f"{relative}:{first_line + token.line - 1}", expression,
                                  _download_template(expression)))
                # Direct native/helper calls. Match the download family structurally rather
                # than selecting two helper names; browser open always requires disposition.
                call_start = index + 1
                if call_start < len(tokens) and tokens[call_start].value == "?.":
                    call_start += 1
                if call_start >= len(tokens) or tokens[call_start].value != "(":
                    continue
                if index and tokens[index - 1].value == "function":
                    continue
                if (value.startswith("download") or value == "saveAs"):
                    arguments = _js_arguments(text, tokens, call_start)
                    if len(arguments) < 2:
                        if value in {"saveAs", "downloadBlob", "downloadJsonDocument"}:
                            found.append((f"{relative}:{first_line + token.line - 1}",
                                          "<implicit browser filename>", None))
                        continue  # event handlers with no filename parameter
                    expression = arguments[1]
                elif value == "setAttribute":
                    arguments = _js_arguments(text, tokens, call_start)
                    if not arguments or _download_template(arguments[0]) != "download":
                        continue
                    expression = arguments[1] if len(arguments) >= 2 else "<implicit browser filename>"
                elif value == "open" and index >= 2 and tokens[index - 2].value in {"window", "globalThis"}:
                    arguments = _js_arguments(text, tokens, call_start)
                    expression = "<browser-open:" + (arguments[0] if arguments else "unknown") + ">"
                else:
                    continue
                found.append((f"{relative}:{first_line + token.line - 1}", expression,
                              _download_template(expression)))
    return sorted(set(found))


def _download_template(expression: str) -> str | None:
    expression = expression.strip()
    while expression.startswith("(") and expression.endswith(")"):
        expression = expression[1:-1].strip()
    parts = _js_parts(expression, 0, "", "+")
    templates = []
    literal = False
    for part in parts:
        if part[:1] in {"`", '"', "'"} and part[-1:] == part[:1]:
            literal = True
            if part.startswith("`"):
                templates.append(re.sub(r"\$\{[^{}]*\}", "0", part[1:-1]))
            else:
                try:
                    templates.append(ast.literal_eval(part))
                except (ValueError, SyntaxError):
                    return None
        else:
            templates.append("0")
    return "".join(templates) if literal else None


def response_filenames(root: Path = ROOT) -> list[tuple[str, str, str | None]]:
    """Every ``filename="..."`` the AssessHub backend sends.

    ``(file::function, file:line, literal template or None)``; a name made only of substitutions
    (``{safe}{suffix}``) has no literal and is tied by its caller instead.
    """
    found: list[tuple[str, str, str | None]] = []
    for relative in scanned_files(root):
        if not relative.startswith("webapp/backend/"):
            continue
        tree = ast.parse((root / relative).read_text(encoding="utf-8"), filename=relative)
        scope: list[str] = []

        def visit(node: ast.AST) -> None:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                scope.append(node.name)
                for child in ast.iter_child_nodes(node):
                    visit(child)
                scope.pop()
                return
            text = None
            if isinstance(node, ast.JoinedStr):
                text = "".join(p.value if isinstance(p, ast.Constant) else "\x00" for p in node.values)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                text = node.value
            match = re.search(r'filename="([^"]*)"', text) if text is not None else None
            if match is not None:
                name = match.group(1)
                template = name.replace("\x00", "0") if name.replace("\x00", "") else None
                found.append((f"{relative}::{'.'.join(scope) or '<module>'}", f"{relative}:{node.lineno}", template))
                return
            for child in ast.iter_child_nodes(node):
                visit(child)

        visit(tree)
    return sorted(set(found))


# --------------------------------------------------------------------------- the census

def bundle_artifact_name_shapes(source: str) -> list[tuple[str, str]]:
    """Derive portable's finite name selectors; refuse unfamiliar positive predicate forms.

    Negative full-path/container exceptions constrain shapes rather than adding name classes.
    """
    tree = ast.parse(source)
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                    and n.name == "_forbidden_client_artifact")
    shapes: set[tuple[str, str]] = set()

    def literals(node: ast.AST) -> list[str]:
        value = ast.literal_eval(node)
        values = [value] if isinstance(value, str) else list(value)
        if not values or any(not isinstance(v, str) for v in values):
            raise ValueError("bundle name selector is not a nonempty literal string collection")
        return values

    def visit(node: ast.AST) -> None:
        if isinstance(node, ast.BoolOp):
            for value in node.values:
                visit(value)
            return
        if isinstance(node, ast.Compare) and len(node.ops) == 1:
            left, right, op = node.left, node.comparators[0], node.ops[0]
            if isinstance(left, ast.Name) and left.id in {"suffix", "leaf"} and isinstance(op, ast.In):
                kind = "suffix" if left.id == "suffix" else "leaf"
                shapes.update((kind, value) for value in literals(right))
                return
            if (isinstance(left, ast.Constant) and isinstance(left.value, str)
                    and isinstance(right, ast.Name) and right.id == "leaf" and isinstance(op, ast.In)):
                shapes.add(("contains", left.value))
                return
            if (isinstance(left, ast.Name) and left.id == "folded"
                    and isinstance(op, (ast.NotIn, ast.NotEq))
                    and isinstance(right, ast.Name) and right.id in {"allowed_snapshot", "allowed_container"}):
                return
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name) and node.func.value.id in {"leaf", "relative"}
                and node.func.attr in {"startswith", "endswith"} and len(node.args) == 1):
            if node.func.value.id == "relative" and node.func.attr == "startswith":
                raise ValueError("unrecognised bundle client-name selector: path prefix is contextual")
            kind = "leaf-prefix" if node.func.attr == "startswith" else "suffix"
            shapes.update((kind, value) for value in literals(node.args[0]))
            return
        raise ValueError(f"unrecognised bundle client-name selector: {ast.unparse(node)}")

    # Validate the whole permitted function. Each early positive return contributes its
    # condition; unfamiliar control flow is refused rather than excluded from the corpus.
    bindings = {
        "folded": "relative.casefold()", "leaf": "PurePosixPath(folded).name",
        "suffix": "PurePosixPath(folded).suffix",
    }
    assigned = set()
    for statement in function.body:
        if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant):
            continue  # docstring
        if isinstance(statement, ast.Assign):
            if len(statement.targets) != 1 or not isinstance(statement.targets[0], ast.Name):
                raise ValueError("unrecognised bundle client-name selector: new local binding")
            name = statement.targets[0].id
            if name in assigned:
                raise ValueError("unrecognised bundle client-name selector: reassigned selector binding")
            assigned.add(name)
            if name in bindings:
                expected = ast.parse(bindings[name], mode="eval").body
                if ast.dump(statement.value) != ast.dump(expected):
                    raise ValueError("unrecognised bundle client-name selector: changed selector binding")
            elif name in {"allowed_snapshot", "allowed_container"}:
                literals(statement.value)
            else:
                raise ValueError("unrecognised bundle client-name selector: new local binding")
            continue
        if isinstance(statement, ast.Return):
            visit(statement.value)
            continue
        if (isinstance(statement, ast.If) and not statement.orelse and len(statement.body) == 1
                and isinstance(statement.body[0], ast.Return)
                and isinstance(statement.body[0].value, ast.Constant)
                and statement.body[0].value.value is True):
            visit(statement.test)
            continue
        raise ValueError(f"unrecognised bundle client-name selector: {ast.unparse(statement)}")
    return sorted(shapes)


_CAPTURES = (
    "capture-show", "capture-get-system", "capture-aws", "capture-moquery", "capture-api",
    "capture-ers", "capture-dataservice",
)
_REST_CAPTURES = ("capture-moquery", "capture-api", "capture-ers", "capture-dataservice")
_COLLECTION_SIDECARS = (
    "collection-device-info", "collection-command-index", "collection-capture-meta",
)
#: The name-identifiable shapes of the raw-capture owner's open class
#: (webapp/backend/redaction_verify.py :: is_uncoverable_capture): what an in-place collection
#: rewrite can publish under a registered name.
_RAW_CAPTURE_SHAPES = _CAPTURES + (
    "config-name-running", "config-name-startup", "config-name-confg", "config-file-cfg",
    "config-file-conf", "config-file-config", "command-output", "engine-log",
)
_DOCX = ("word-document",)
_OFFICE = ("word-document", "presentation", "workbook")
_REDACTED_DELIVERY = (
    "word-document", "presentation", "workbook", "protocol-assurance-export", "explorer",
    "snapshot", "run-manifest", "phase-timings", "topology-mermaid", "topology-graphviz",
    "redaction-receipt", "atomic-staging",
)
_REDACTION_RUN = tuple(dict.fromkeys(
    ("devices-inventory", "workbook", "unsafe-marker", "incomplete-set-marker",
     "incomplete-set-fallback") + _REDACTED_DELIVERY + _RAW_CAPTURE_SHAPES
))
_SYSTEM_TEMP = (
    "tempfile.mkstemp with no dir= puts it under the operating-system temporary directory, and "
    "the same function unlinks it after use"
)
_WORKDIR = (
    "inside the job's private work directory, tempfile.mkdtemp(dir=_engine_temp_parent()) under the "
    "operating-system temporary directory, which the job removes when it ends"
)
_IN_PLACE = (
    "rewrites files in place in the operator's collection folder (--redact-collection); the name set "
    "is the raw-capture owner's open class (webapp/backend/redaction_verify.py :: "
    "is_uncoverable_capture: every non-structured file of the folder), so it cannot be enumerated; "
    "the registered keys are its name-identifiable shapes"
)
_REPO_LEDGER = (
    "a tracked repository self-measurement ledger under docs/quality/; no assessment input reaches "
    "it, and the repository gate scans its content"
)
_REFERENCE_PACKS = "the public IANA and IEEE reference packs, their marker and manifest"
_TRANSITION = (
    "Atlas R1/R2 transition tooling over tracked source, pinned public packages and synthetic "
    "fixtures; no assessment input reaches it"
)
_CI_EVIDENCE = (
    "CI review evidence written under the runner's temporary directory from repository source, "
    "GitHub API metadata and public packages; no assessment input reaches it"
)
_MASTER_REFERENCE = (
    "Atlas master-reference compiler and release outputs built from the exact tracked tree; no "
    "assessment input reaches them (master-reference/release/pipeline.py)"
)
_TOOLING = "repository development tooling over tracked source and public inputs; no assessment input"
_RELEASE = (
    "Atlas release or build material produced from tracked source; the runtime bundle itself refuses "
    "client artifacts (portable/release_contract.py :: _forbidden_client_artifact)"
)
_SYNTHETIC = (
    "generated SYNTHETIC fixture data (MERIDIAN-* aliases, documentation addresses); no client input "
    "reaches it, though some names fall in client classes, which the keys list"
)

# The census. Key: "<file>::<enclosing qualname>". Value: (write count, disposition, registry
# class keys, why). Counts are exact so a second write added to a classified function is reviewed.
WRITE_SITE_CENSUS: Mapping[str, tuple[int, str, tuple[str, ...], str]] = {
    # ---- engine CLI (COLLECT_PARSE_V3_23_0.py) --------------------------------------------------
    "COLLECT_PARSE_V3_23_0.py::collect": (
        4, CLIENT, (_CAPTURES + _COLLECTION_SIDECARS) + ('atomic-staging',),
        "live collector: one <command>.txt capture per command under <collection>/<host>/, plus "
        "device_info.json, command_index.json and _capture_meta.json through write_json_file"),
    "COLLECT_PARSE_V3_23_0.py::main.collect_one": (
        1, CLIENT, (_CAPTURES + _COLLECTION_SIDECARS) + ('atomic-staging',), "runs collect() for one device"),
    "COLLECT_PARSE_V3_23_0.py::setup_logging": (
        1, CLIENT, ("engine-log",),
        "engine audit log cisco_migration_autofill_v<version>.log (cisco_toolkit.engine_log_path); "
        "it names devices, addresses and paths"),
    "COLLECT_PARSE_V3_23_0.py::write_json_file": (
        2, DELEGATED, ("atomic-staging",),
        "generic JSON writer; the caller names the file, and the atomic path stages through "
        "_write_json_atomic as <name>.<pid>.tmp"),
    "COLLECT_PARSE_V3_23_0.py::_write_json_atomic": (
        2, DELEGATED, ("atomic-staging",),
        "generic same-directory atomic publish: <name>.<pid>.tmp, fsync, os.replace"),
    "COLLECT_PARSE_V3_23_0.py::_replace_with_retries": (
        1, DELEGATED, (), "generic os.replace with retries; the caller names source and destination"),
    "COLLECT_PARSE_V3_23_0.py::main": (
        20, CLIENT,
        (("pre-change-certificate", "comparison-receipt", "trend-comparisons", "explorer",
         "topology-mermaid", "topology-graphviz", "engagement-gate-state")
        + _OFFICE + _CAPTURES + _COLLECTION_SIDECARS) + ('atomic-staging', 'incomplete-marker', 'protocol-assurance-export', 'receipt-authority-probe', 'run-manifest'),
        "--compare writes <diff>.xlsx, <diff>.precert.json and <diff>.comparison.json; --trend writes "
        "<trend>.xlsx and <trend>.trend-comparisons.json; the assessment run collects, then writes "
        "topology.mmd/.dot, <output>_explorer.html and the DOCX/PPTX family, consulting the gate "
        "ledger, before _stage_finalize"),
    "COLLECT_PARSE_V3_23_0.py::_stage_finalize": (
        14, CLIENT,
        (("protocol-assurance-export", "explorer", "phase-timings", "run-manifest", "snapshot",
         "incomplete-marker", "word-document", "workbook", "redaction-staging")
        + _RAW_CAPTURE_SHAPES) + ('atomic-staging', 'receipt-authority-probe'),
        "<output>.protocol-assurance.json, the BOUND explorer/runbook/MOP/workbook refresh, "
        "<output>.phase_timings.json, <output>.run_manifest.json and <output>.incomplete.json, plus "
        "the --redact-collection in-place scrub"),
    "COLLECT_PARSE_V3_23_0.py::_stage_finalize._publish_snapshot": (
        1, CLIENT, (("snapshot",)) + ('atomic-staging',), "<output>.snapshot.json, the parsed estate"),
    "COLLECT_PARSE_V3_23_0.py::_stage_finalize._save_workbook": (
        1, CLIENT, ("workbook",),
        "the assessment workbook <output>.xlsx (staged as .<stem>.receipt-<nonce>.tmp.xlsx)"),
    "COLLECT_PARSE_V3_23_0.py::_write_incomplete_marker": (
        1, CLIENT, (("incomplete-marker",)) + ('atomic-staging',),
        "<output>.incomplete.json: the run's custody and failure record, written before the seal"),
    "COLLECT_PARSE_V3_23_0.py::_atomic_receipt_refresh": (
        6, CLIENT,
        ("explorer", "word-document", "workbook", "receipt-staging-html", "receipt-previous-html",
         "receipt-authority-probe"),
        "publishes a BOUND explorer, runbook, MOP or workbook through .<stem>.receipt-<nonce>.tmp<ext> "
        "and moves the earlier file aside as .<stem>.receipt-<nonce>.previous<ext>"),
    "COLLECT_PARSE_V3_23_0.py::_atomic_receipt_refresh._restore_previous": (
        1, CLIENT, ("explorer", "word-document", "workbook", "receipt-previous-html"),
        "restores the displaced .previous<ext> file over the artifact after a failed refresh"),
    "COLLECT_PARSE_V3_23_0.py::_verify_bound_receipt_surface": (
        2, CLIENT, ("receipt-authority-probe",),
        "renders the canonical explorer into .protocol-receipt-authority-*.html beside the "
        "artifact for a byte comparison, then unlinks it"),
    # ---- engine deliverable writers (cisco_toolkit) ---------------------------------------------
    "cisco_toolkit/archreview.py::write_archreview_docx": (
        1, CLIENT, _DOCX, "<output>_archreview.docx, or an AssessHub temporary .docx"),
    "cisco_toolkit/crd.py::write_crd_docx": (
        1, CLIENT, _DOCX, "<output>_crd.docx, or an AssessHub temporary .docx"),
    "cisco_toolkit/design.py::write_design_doc_docx": (
        1, CLIENT, _DOCX, "<output>_design.docx, or an AssessHub temporary .docx"),
    "cisco_toolkit/engagement.py::write_engagement_docx": (
        1, CLIENT, _DOCX, "<output>_engagement.docx, or an AssessHub temporary .docx"),
    "cisco_toolkit/mop.py::write_mop_docx": (
        1, CLIENT, _DOCX, "<output>_mop.docx, or an AssessHub temporary .docx"),
    "cisco_toolkit/ops.py::write_ops_handbook_docx": (
        1, CLIENT, _DOCX, "<output>_ops_handbook.docx, or an AssessHub temporary .docx"),
    "cisco_toolkit/runbook.py::write_runbook_docx": (
        1, CLIENT, _DOCX, "<output>_runbook.docx, or an AssessHub temporary .docx"),
    "cisco_toolkit/deck.py::write_executive_deck_pptx": (
        1, CLIENT, ("presentation",), "<output>_executive_deck.pptx, or an AssessHub temporary .pptx"),
    "cisco_toolkit/html.py::write_diff_workbook": (
        1, CLIENT, ("workbook",), "the --compare cutover diff workbook (.xlsx)"),
    "cisco_toolkit/html.py::write_campaign_workbook": (
        1, CLIENT, ("workbook",), "the --trend campaign workbook (.xlsx)"),
    "cisco_toolkit/html.py::write_html_explorer": (
        1, DELEGATED, (),
        "the explorer renderer; its callers name the file (<output>_explorer.html, the receipt "
        "authority probe, or an AssessHub temporary file)"),
    "cisco_toolkit/html.py::redact_collection_dir": (
        2, OPERATOR_PATH, _RAW_CAPTURE_SHAPES + ("redaction-staging",),
        _IN_PLACE + "; it stages each rewrite as <capture>.redacting and skips structured .json"),
    "cisco_toolkit/excel.py::write_topology_diagram": (
        2, CLIENT, ("topology-mermaid", "topology-graphviz"),
        "topology.mmd and topology.dot beside the workbook"),
    "cisco_toolkit/nrfu_export.py::write_nrfu_pack": (
        1, CLIENT, ("nrfu-command-pack",),
        "direct library export <out_dir>/<wave>/<host>.nrfu.txt: host, commands, baselines and citations"),
    "cisco_toolkit/precert.py::main": (
        1, CLIENT, ("readiness-certificate",),
        "<snapshot>.precert-readiness.json (or the operator's --out path)"),
    "cisco_toolkit/rest_collect.py::_write": (
        1, CLIENT, _REST_CAPTURES,
        "controller REST exports under the offline command filename (moquery_*, api_*, ers_*, "
        "dataservice_*.txt) in the collection directory"),
    "cisco_toolkit/rest_collect.py::collect_apic": (1, CLIENT, ("capture-moquery",), "APIC exports"),
    "cisco_toolkit/rest_collect.py::collect_vmanage": (
        1, CLIENT, ("capture-dataservice",), "vManage exports"),
    "cisco_toolkit/rest_collect.py::collect_ise": (
        2, CLIENT, ("capture-api", "capture-ers"), "ISE exports"),
    "cisco_toolkit/rest_collect.py::collect_fmc": (2, CLIENT, ("capture-api",), "FMC exports"),
    "cisco_toolkit/rest_collect.py::<module>": (
        4, CLIENT, _REST_CAPTURES, "the CONTROLLER_COLLECTORS registry of the four collectors"),
    "cisco_toolkit/gate_state.py::save_store": (
        2, CLIENT, ("engagement-gate-state", "atomic-staging"),
        "docs/engagement-state.json under the gate root: engagement identity, approvers and "
        "reasons, staged as engagement-state.json.<random>.tmp"),
    "cisco_toolkit/gate_state.py::_open_lock_fd": (
        1, NON_CLIENT, (), "<store>.lock is an empty mutual-exclusion token; it never holds data"),
    "cisco_toolkit/gate_state.py::_ledger_lock": (
        1, NON_CLIENT, (), "takes the empty <store>.lock token"),
    "cisco_toolkit/gate_state.py::_locked_update": (
        2, CLIENT, ("engagement-gate-state", "atomic-staging"),
        "locked read-modify-write of the engagement gate ledger"),
    "cisco_toolkit/gate_state.py::_append_audit": (
        1, CLIENT, (("engagement-gate-state",)) + ('atomic-staging',), "appends an audit line to the gate ledger"),
    "cisco_toolkit/gate_state.py::_record_refusal": (
        1, CLIENT, (("engagement-gate-state",)) + ('atomic-staging',), "records a refused gate in the ledger"),
    "cisco_toolkit/gate_state.py::record_decision": (
        1, CLIENT, (("engagement-gate-state",)) + ('atomic-staging',), "records an approval or revocation in the ledger"),
    "cisco_toolkit/gate_state.py::bind_engagement": (
        1, CLIENT, (("engagement-gate-state",)) + ('atomic-staging',), "binds the ledger to an engagement identifier"),
    "cisco_toolkit/gate_state.py::enforce": (
        3, CLIENT, (("engagement-gate-state",)) + ('atomic-staging',), "records an override or refusal in the ledger"),
    "cisco_toolkit/gate_state.py::main": (
        2, CLIENT, (("engagement-gate-state",)) + ('atomic-staging',), "the gate-ledger CLI (bind, approve, revoke)"),
    "cisco_toolkit/recall.py::log_query": (
        1, CLIENT, ("query-log",),
        "docs/quality/query_log.jsonl: real retrieval queries, which can name client tokens"),
    "cisco_toolkit/recall.py::main": (
        1, CLIENT, ("query-log",), "the recall CLI logs its query"),
    # ---- repository tooling inside cisco_toolkit -------------------------------------------------
    "cisco_toolkit/clock.py::append_run": (
        1, NON_CLIENT, (), "docs/quality/nightly_runs.jsonl: " + _REPO_LEDGER),
    "cisco_toolkit/clock.py::main": (1, NON_CLIENT, (), "the clock CLI; " + _REPO_LEDGER),
    "cisco_toolkit/scorecard.py::append_row": (
        1, NON_CLIENT, (), "docs/quality/scorecard.jsonl: " + _REPO_LEDGER),
    "cisco_toolkit/scorecard.py::run_hook": (1, NON_CLIENT, (), "scorecard hook; " + _REPO_LEDGER),
    "cisco_toolkit/scorecard.py::main": (3, NON_CLIENT, (), "the scorecard CLI; " + _REPO_LEDGER),
    "cisco_toolkit/retrieval_eval.py::append_pooled_qrels": (
        1, NON_CLIENT, (),
        "docs/quality/d10-pooled-qrels.jsonl: query ids, document ids and grades over the tracked "
        "D10 eval set"),
    "cisco_toolkit/retrieval_eval.py::run_eval": (
        3, NON_CLIENT, (),
        "d10-eval-results-<date>.json and .md plus pooled qrels: retrieval metrics over the tracked "
        "D10 eval set"),
    "cisco_toolkit/retrieval_eval.py::main": (1, NON_CLIENT, (), "the D10 eval CLI"),
    "cisco_toolkit/retrieval_eval.py::invoke_judge_helper": (
        1, PRIVATE_TEMP, (),
        "judge pairs carrying corpus and vault-digest excerpts; " + _SYSTEM_TEMP),
    "cisco_toolkit/holdout.py::_append_access": (
        1, NON_CLIENT, (),
        "docs/quality/holdout_access.jsonl: access events with the declared reviewer and the OS user "
        "name (operator identity, not client evidence; the repository gate scans its content)"),
    "cisco_toolkit/holdout.py::read_holdout": (1, NON_CLIENT, (), "logs one holdout access"),
    "cisco_toolkit/holdout.py::main": (
        2, NON_CLIENT, (),
        "docs/quality/holdout_manifest.json: a hash chain of holdout row digests and policy counts"),
    "cisco_toolkit/memory_guard.py::main": (
        1, OPERATOR_PATH, (),
        "`memory_guard snapshot --out <path>` (default stdout): the agent-memory store path, memory "
        "file names and SHA-256 digests; memory file names can name an engagement"),
    "cisco_toolkit/distribution_verify.py::_write_new_proof": (
        1, NON_CLIENT, (),
        "the distribution proof: digests and measurements of this repository's own wheel and sdist"),
    "cisco_toolkit/distribution_verify.py::main": (
        1, NON_CLIENT, (), "the distribution verifier CLI writes its proof"),
    "cisco_toolkit/registry_integrity.py::_write_temp_bytes": (
        1, NON_CLIENT, ("atomic-staging",), "staging for " + _REFERENCE_PACKS),
    "cisco_toolkit/registry_integrity.py::publish_pack_and_manifest": (
        7, NON_CLIENT, (()) + ('atomic-staging',), _REFERENCE_PACKS),
    "cisco_toolkit/registry_integrity.py::update_manifest": (2, NON_CLIENT, (()) + ('atomic-staging',), _REFERENCE_PACKS),
    "cisco_toolkit/registry_integrity.py::_restore_snapshot": (
        2, NON_CLIENT, (()) + ('atomic-staging',), "rollback of " + _REFERENCE_PACKS),
    "cisco_toolkit/gen_oui_registry.py::write_registry": (1, NON_CLIENT, (()) + ('atomic-staging',), _REFERENCE_PACKS),
    "cisco_toolkit/gen_oui_registry.py::build_authoritative": (1, NON_CLIENT, (()) + ('atomic-staging',), _REFERENCE_PACKS),
    "cisco_toolkit/gen_oui_registry.py::_legacy_main": (1, NON_CLIENT, (()) + ('atomic-staging',), _REFERENCE_PACKS),
    "cisco_toolkit/gen_oui_registry.py::main": (2, NON_CLIENT, (()) + ('atomic-staging',), _REFERENCE_PACKS),
    "cisco_toolkit/data/gen_port_registry.py::build": (1, NON_CLIENT, (()) + ('atomic-staging',), _REFERENCE_PACKS),
    "cisco_toolkit/data/gen_port_registry.py::main": (1, NON_CLIENT, (()) + ('atomic-staging',), _REFERENCE_PACKS),
    "cisco_toolkit/transition_legacy.py::_run_pinned_release1_driver": (
        1, NON_CLIENT, (), "materialises the verified release-1 driver source bundle; " + _TRANSITION),
    "cisco_toolkit/transition_legacy.py::_validate_release1_comparison": (1, NON_CLIENT, (), _TRANSITION),
    "cisco_toolkit/transition_legacy.py::adapt_release1_comparison_bytes": (1, NON_CLIENT, (), _TRANSITION),
    "cisco_toolkit/transition_legacy.py::replay_release1_comparison_bytes": (1, NON_CLIENT, (), _TRANSITION),
    "cisco_toolkit/transition_runtime_discovery.py::_materialize_commit_inputs": (
        1, NON_CLIENT, (), "materialises tracked repository source; " + _TRANSITION),
    "cisco_toolkit/transition_runtime_discovery.py::_materialize_collector_target_script": (
        1, NON_CLIENT, (), "writes the discovery collector's own target script; " + _TRANSITION),
    "cisco_toolkit/transition_runtime_discovery.py::_capture_dynamic": (2, NON_CLIENT, (), _TRANSITION),
    "cisco_toolkit/transition_runtime_discovery.py::_capture_debug_dynamic_on_creator_thread": (
        2, NON_CLIENT, (), _TRANSITION),
    "cisco_toolkit/transition_runtime_discovery.py::_debug_capture_helper_main": (
        1, NON_CLIENT, (), _TRANSITION),
    "cisco_toolkit/transition_runtime_discovery.py::_capture_debug_dynamic": (1, NON_CLIENT, (), _TRANSITION),
    "cisco_toolkit/transition_runtime_discovery.py::capture_windows_runtime_closure_incomplete": (
        1, NON_CLIENT, (), _TRANSITION),
    # ---- AssessHub (webapp/backend) --------------------------------------------------------------
    "webapp/backend/app.py::create_app.execution_report": (
        1, PRIVATE_TEMP, _DOCX, "the PIR download assesshub_pir_*.docx; " + _SYSTEM_TEMP),
    "webapp/backend/app.py::create_app.snapshot_deliverable": (
        1, PRIVATE_TEMP, ("word-document", "presentation"),
        "a snapshot deliverable download through deliverables.generate; " + _SYSTEM_TEMP),
    "webapp/backend/app.py::create_app.snapshot_explorer": (
        1, PRIVATE_TEMP, (), "the snapshot explorer through engine.render_explorer_html; " + _SYSTEM_TEMP),
    "webapp/backend/app.py::create_app.ingest_collection": (
        1, PRIVATE_TEMP, ("devices-inventory", "workbook"),
        "an uploaded collection ZIP, extracted and assessed " + _WORKDIR),
    "webapp/backend/app.py::create_app.ingest_collection_folder": (
        1, PRIVATE_TEMP, ("devices-inventory", "workbook"),
        "a collection folder copied into custody and assessed " + _WORKDIR),
    "webapp/backend/deliverables.py::generate": (
        3, PRIVATE_TEMP, ("word-document", "presentation"),
        "a snapshot deliverable download assesshub_*.<ext>, stamped in place; " + _SYSTEM_TEMP),
    "webapp/backend/deliverables.py::_stamp_unapproved_draft": (
        1, CLIENT, _DOCX, "re-saves the generated DOCX in place with the draft stamp"),
    "webapp/backend/deliverables.py::_stamp_ssot_integrity": (
        2, CLIENT, ("word-document", "presentation"),
        "re-saves the generated DOCX or PPTX in place with the integrity stamp"),
    "webapp/backend/engine.py::render_explorer_html": (
        2, PRIVATE_TEMP, (),
        "the snapshot explorer assesshub_explorer_*.html, read back for the response; " + _SYSTEM_TEMP),
    "webapp/backend/cutover_docx.py::write_cutover_docx": (
        2, CLIENT, _DOCX, "the cutover plan download (.docx)"),
    "webapp/backend/nrfu_docx.py::write_nrfu_docx": (
        1, CLIENT, _DOCX, "the NRFU test plan download (.docx)"),
    "webapp/backend/pir_docx.py::write_pir_docx": (
        1, CLIENT, _DOCX, "the post-implementation review download (.docx)"),
    "webapp/backend/storage.py::Store.__init__": (
        1, CLIENT, ("database", "database-wal", "database-shm", "database-journal"),
        "the AssessHub database assesshub.db (snapshots, executions, evidence) and its SQLite "
        "companions"),
    "webapp/backend/storage.py::Store._boot_hardening": (
        3, CLIENT, ("database", "database-backup-partial", "database-wal", "database-shm", "database-journal"),
        "backups/assesshub-<stamp>.db, staged as assesshub-<stamp>-<pid>-<hex>.db.partial"),
    "webapp/backend/storage.py::_backup_campaign_evidence": (
        1, CLIENT, ("database", "database-wal", "database-shm", "database-journal"),
        "opens an existing database backup read-only and immutable to classify it"),
    "webapp/backend/ingest.py::_safe_extract": (
        1, PRIVATE_TEMP, (), "an uploaded collection ZIP extracted " + _WORKDIR),
    "webapp/backend/ingest.py::_stage_physical_tree": (
        1, PRIVATE_TEMP, (), "a collection folder copied into private custody " + _WORKDIR),
    "webapp/backend/ingest.py::_assess_tree": (
        2, PRIVATE_TEMP, ("devices-inventory", "workbook"),
        "the job's synthesised devices.json and empty template.xlsx " + _WORKDIR),
    "webapp/backend/ingest.py::run_collection_zip": (
        2, PRIVATE_TEMP, ("devices-inventory", "workbook"), "extracts and assesses " + _WORKDIR),
    "webapp/backend/ingest.py::run_collection_folder": (
        2, PRIVATE_TEMP, ("devices-inventory", "workbook"), "copies and assesses " + _WORKDIR),
    "webapp/backend/ingest.py::_write_min_template": (
        1, PRIVATE_TEMP, ("workbook",),
        "an empty minimal workbook template (template.xlsx, no assessment data) " + _WORKDIR),
    "webapp/backend/ingest.py::_copy_back_scrubbed_collection": (
        2, OPERATOR_PATH, _RAW_CAPTURE_SHAPES + ("atomic-staging",),
        _IN_PLACE + "; each copy-back stages as .<capture>.atlas-scrub-<hex>.tmp"),
    "webapp/backend/ingest.py::_promote_verified_delivery": (
        6, CLIENT, _REDACTED_DELIVERY,
        "promotes the verified Assessment_redacted* set into the output folder and writes "
        "Assessment_redacted.redaction.json through .<receipt>.<run_id>.tmp"),
    "webapp/backend/ingest.py::_mark_output_unsafe": (
        1, CLIENT, ("unsafe-marker",),
        "DO-NOT-SEND-NOT-REDACTED.txt, quoting why the run refused to certify the set"),
    "webapp/backend/ingest.py::_mark_output_incomplete": (
        1, CLIENT, ("incomplete-set-marker", "incomplete-set-fallback"),
        "INCOMPLETE-SET.txt (or INCOMPLETE-SET-ATLAS.txt), quoting the engine's gap reasons"),
    "webapp/backend/ingest.py::_run_redaction_folder_locked": (
        13, CLIENT, _REDACTION_RUN,
        "the field redaction run: private custody and workdir, then the verified delivery, the "
        "markers and the optional in-place capture scrub of the operator's folders"),
    "webapp/backend/ingest.py::run_redaction_folder": (
        2, CLIENT, _REDACTION_RUN, "takes the output lock and runs the field redaction"),
    "webapp/backend/ingest.py::_output_dir_lock": (
        1, NON_CLIENT, (), ".atlas-redaction.lock holds only a fixed NUL marker, never client data"),
    "webapp/backend/serve.py::_writable_failure": (
        1, NON_CLIENT, (), "a fixed 'ok' write probe, unlinked immediately; no client data"),
    "webapp/backend/serve.py::run_selftest": (2, NON_CLIENT, (), "write probes of the data folders"),
    "webapp/backend/serve.py::run_redaction": (
        1, CLIENT, _REDACTION_RUN, "Atlas.exe --redact-folder runs the field redaction"),
    "webapp/backend/serve.py::run_database_preflight": (
        1, CLIENT, ("database", "database-wal", "database-shm", "database-journal"),
        "Atlas.exe database preflight over a copy of the operator's database"),
    "webapp/backend/serve.py::_main_scoped": (
        4, CLIENT, _REDACTION_RUN + ("database", "database-wal", "database-shm", "database-journal"),
        "the Atlas.exe entry: self-test probes, database preflight and field redaction"),
    "webapp/backend/export_ui_projection_openapi.py::main": (
        1, NON_CLIENT, (), "the UI projection OpenAPI document generated from code"),
    "webapp/backend/observe_ui_projection_contract.py::emit": (
        1, NON_CLIENT, (), "UI projection schema observations generated from code"),
    "webapp/backend/observe_ui_projection_contract.py::main": (
        5, NON_CLIENT, (), "UI projection schema observations generated from code"),
    "webapp/sample_data/build_sample.py::_write_collection": (
        1, NON_CLIENT, (), "the synthetic sample collection; " + _SYNTHETIC),
    "webapp/sample_data/build_sample.py::_make_template": (
        1, NON_CLIENT, (), "the sample build's empty template; " + _SYNTHETIC),
    "webapp/sample_data/build_sample.py::_write_snapshot": (
        1, NON_CLIENT, (), "the tracked synthetic sample fleet; " + _SYNTHETIC),
    "webapp/sample_data/build_sample.py::main": (
        4, NON_CLIENT, ("devices-inventory", "workbook"),
        "builds webapp/sample_data/sample_fleet.snapshot.json; " + _SYNTHETIC),
    "webapp/frontend/e2e-real/serve_real_backend.py::fresh_run_dir": (
        1, NON_CLIENT, (), "the real-backend E2E run marker; " + _SYNTHETIC),
    "webapp/frontend/e2e-real/serve_real_backend.py::write_collection": (
        2, NON_CLIENT, (), "the real-backend E2E collection; " + _SYNTHETIC),
    "webapp/frontend/e2e-real/serve_real_backend.py::main": (
        2, NON_CLIENT, (), "the real-backend E2E harness; " + _SYNTHETIC),
    # ---- Atlas packaging and qualification (portable) -------------------------------------------
    "portable/database_preflight.py::_open_readonly": (
        1, CLIENT, ("database", "database-wal", "database-shm", "database-journal"),
        "opens the operator's AssessHub database copy read-only (mode=ro, query_only)"),
    "portable/database_preflight.py::census": (
        1, CLIENT, ("database", "database-wal", "database-shm", "database-journal"), "counts rows of that copy"),
    "portable/database_preflight.py::verify_migrated_copy": (
        2, CLIENT, ("database", "database-wal", "database-shm", "database-journal"), "compares that copy after migration"),
    "portable/database_preflight.py::migrate_and_compare": (
        2, CLIENT, ("database", "database-wal", "database-shm", "database-journal"), "migrates and compares that copy"),
    "portable/build_atlas.py::build": (1, NON_CLIENT, (), _RELEASE),
    "portable/build_atlas.py::smoke": (
        2, NON_CLIENT, (), _RELEASE + "; the smoke copy's data directory comes from a synthetic run"),
    "portable/build_atlas.py::_detach_runtime_data": (
        1, NON_CLIENT, (),
        "moves the SMOKE copy's data directory, created by the synthetic field-layout smoke run"),
    "portable/build_release.py::build_release": (2, NON_CLIENT, (()) + ('database', 'capture-show', 'config-file-cfg'), _RELEASE),
    "portable/build_release.py::main": (2, NON_CLIENT, (()) + ('database', 'capture-show', 'config-file-cfg'), _RELEASE),
    "portable/package_signed_release.py::_independent_authenticode": (1, NON_CLIENT, (), _RELEASE),
    "portable/package_signed_release.py::package_signed": (3, NON_CLIENT, (()) + ('database', 'capture-show', 'config-file-cfg'), _RELEASE),
    "portable/package_signed_release.py::main": (2, NON_CLIENT, (()) + ('database', 'capture-show', 'config-file-cfg'), _RELEASE),
    "portable/prepare_signing.py::prepare": (3, NON_CLIENT, (), _RELEASE),
    "portable/prepare_signing.py::main": (1, NON_CLIENT, (), _RELEASE),
    "portable/release_contract.py::_record_build_modules": (1, NON_CLIENT, (), _RELEASE),
    "portable/release_contract.py::_npm_build_attribution": (1, NON_CLIENT, (), _RELEASE),
    "portable/release_contract.py::toolchain_receipt": (1, NON_CLIENT, (), _RELEASE),
    "portable/release_contract.py::_write_checksums": (1, NON_CLIENT, (), _RELEASE),
    "portable/release_contract.py::_write_deterministic_zip": (1, NON_CLIENT, (), _RELEASE),
    "portable/release_contract.py::build_portable_release": (9, NON_CLIENT, (), _RELEASE),
    "portable/qualify_atlas.py::qualify": (3, NON_CLIENT, ("database", "capture-show", "config-file-cfg"), _RELEASE + "; " + _SYNTHETIC),
    "portable/qualify_atlas.py::main": (2, NON_CLIENT, (()) + ('database', 'capture-show', 'config-file-cfg'), "the qualification receipt"),
    "portable/qualify_atlas.py::_redaction": (
        5, NON_CLIENT, ("capture-show", "config-file-cfg"),
        "redaction canaries (SYNTHETIC-CORE1, TEST-ONLY) in a qualification collection; " + _SYNTHETIC),
    "portable/qualify_atlas.py::_database_preflight": (
        3, NON_CLIENT, ("database",),
        "builds the prior-release database from the digest-pinned fixture; " + _SYNTHETIC),
    "portable/qualify_atlas.py::_database_preflight_case": (
        4, NON_CLIENT, ("database",),
        "copies that synthetic database and writes its atlas-db-preflight.json request; " + _SYNTHETIC),
    # ---- other tracked Python (CI, tooling, references, research) --------------------------------
    ".github/scripts/classify_webapp_ci_scope.py::main": (
        1, NON_CLIENT, (), "the webapp CI scope verdict written to $GITHUB_OUTPUT"),
    ".github/scripts/engine_output_handoff.py::<module>": (1, NON_CLIENT, (), _CI_EVIDENCE),
    ".github/scripts/engine_output_handoff.py::write_new": (1, NON_CLIENT, (), _CI_EVIDENCE),
    ".github/scripts/engine_output_handoff.py::phase_before": (1, NON_CLIENT, (), _CI_EVIDENCE),
    ".github/scripts/engine_output_handoff.py::phase_after": (2, NON_CLIENT, (), _CI_EVIDENCE),
    ".github/scripts/engine_output_handoff.py::_write_review_data": (2, NON_CLIENT, (), _CI_EVIDENCE),
    ".github/scripts/engine_output_handoff.py::receive": (1, NON_CLIENT, (), _CI_EVIDENCE),
    ".github/scripts/engine_output_handoff.py::main": (3, NON_CLIENT, (), _CI_EVIDENCE),
    ".github/scripts/frontend_artifact_receive.py::write_new": (1, NON_CLIENT, (), _CI_EVIDENCE),
    ".github/scripts/frontend_artifact_receive.py::record": (1, NON_CLIENT, (), _CI_EVIDENCE),
    ".github/scripts/frontend_artifact_receive.py::GitHub.archive": (1, NON_CLIENT, (), _CI_EVIDENCE),
    ".github/scripts/frontend_artifact_receive.py::bridge": (
        3, NON_CLIENT, ("engine-log",), _CI_EVIDENCE + "; <step>.stderr.log is a bridge's stderr"),
    ".github/scripts/frontend_artifact_receive.py::select_registry": (3, NON_CLIENT, (()) + ('engine-log',), _CI_EVIDENCE),
    ".github/scripts/frontend_artifact_receive.py::candidate": (1, NON_CLIENT, (()) + ('engine-log',), _CI_EVIDENCE),
    ".github/scripts/frontend_artifact_receive.py::patch": (3, NON_CLIENT, (), _CI_EVIDENCE),
    ".github/scripts/frontend_artifact_receive.py::main": (11, NON_CLIENT, (()) + ('engine-log',), _CI_EVIDENCE),
    ".github/scripts/frontend_build_handoff.py::main": (3, NON_CLIENT, (), _CI_EVIDENCE),
    ".github/scripts/frontend_candidate_materials.py::write_new": (1, NON_CLIENT, (), _CI_EVIDENCE),
    ".github/scripts/frontend_candidate_materials.py::emit": (1, NON_CLIENT, (), _CI_EVIDENCE),
    ".github/scripts/frontend_candidate_materials.py::observe_inventory": (1, NON_CLIENT, (), _CI_EVIDENCE),
    ".github/scripts/frontend_candidate_materials.py::main": (6, NON_CLIENT, (), _CI_EVIDENCE),
    ".github/scripts/observe_jsonschema_rs_wheel.py::write_new": (1, NON_CLIENT, (), _CI_EVIDENCE),
    ".github/scripts/observe_jsonschema_rs_wheel.py::record": (1, NON_CLIENT, (), _CI_EVIDENCE),
    ".github/scripts/observe_jsonschema_rs_wheel.py::main": (7, NON_CLIENT, (), _CI_EVIDENCE),
    ".github/scripts/observe_vite_distribution.py::main": (6, NON_CLIENT, (), _CI_EVIDENCE),
    ".github/scripts/observe_vite_distribution.py::main.emit": (1, NON_CLIENT, (), _CI_EVIDENCE),
    ".github/scripts/refresh_visual_baseline_pins.py::_write_atomic": (
        2, NON_CLIENT, ("atomic-staging",), "rewrites the synthetic visual-baseline pins in place"),
    ".github/scripts/refresh_visual_baseline_pins.py::main": (
        1, NON_CLIENT, (()) + ('atomic-staging',), "rewrites the synthetic visual-baseline pins in place"),
    ".github/scripts/scope_compile_handoff.py::_write": (1, NON_CLIENT, (), _CI_EVIDENCE),
    ".github/scripts/scope_compile_handoff.py::main": (2, NON_CLIENT, (), _CI_EVIDENCE),
    "atlas-scope/tools/fixtures/engine-sparse-interfaces.py::<module>": (
        1, NON_CLIENT, (), "the Atlas Scope sparse-interfaces fixture; " + _SYNTHETIC),
    "embed_qbank.py::main": (
        1, NON_CLIENT, ("explorer",),
        "rewrites the explorer TEMPLATE cisco_toolkit/blast_radius_explorer.html (a reviewed "
        "registry exception) with the questionnaire bank"),
    "ollama_judge.py::main": (1, NON_CLIENT, (), "appends a scorecard row; " + _REPO_LEDGER),
    "master-reference/cli/capacity.py::<module>": (1, NON_CLIENT, (), _MASTER_REFERENCE),
    "master-reference/cli/capacity.py::main": (2, NON_CLIENT, (), _MASTER_REFERENCE),
    "master-reference/compiler/__main__.py::main": (1, NON_CLIENT, (), _MASTER_REFERENCE),
    "master-reference/compiler/compiler.py::_write_bytes": (1, NON_CLIENT, (), _MASTER_REFERENCE),
    "master-reference/compiler/compiler.py::_write_failure": (3, NON_CLIENT, (), _MASTER_REFERENCE),
    "master-reference/compiler/compiler.py::_write_success": (6, NON_CLIENT, (), _MASTER_REFERENCE),
    "master-reference/compiler/compiler.py::compile_repository": (2, NON_CLIENT, (), _MASTER_REFERENCE),
    "master-reference/release/model.py::write_bytes": (1, NON_CLIENT, (), _MASTER_REFERENCE),
    "master-reference/release/model.py::StagedOutput.publish": (1, NON_CLIENT, (), _MASTER_REFERENCE),
    "master-reference/release/model.py::deterministic_zip": (1, NON_CLIENT, (), _MASTER_REFERENCE),
    # W64a streams the release family to disk instead of building it in memory: the same
    # deterministic release ZIPs and JSON artifacts, written entry by entry. Release output, not client data.
    "master-reference/release/model.py::_write_deterministic_zip": (1, NON_CLIENT, (), _MASTER_REFERENCE),
    "master-reference/release/model.py::write_deterministic_zip": (2, NON_CLIENT, (), _MASTER_REFERENCE),
    "master-reference/release/pipeline.py::_streamed_json_artifact": (1, NON_CLIENT, (), _MASTER_REFERENCE),
    "master-reference/release/pipeline.py::_zip_artifact": (1, NON_CLIENT, (), _MASTER_REFERENCE),
    "master-reference/release/pdf_report.py::build_master_reference_pdf": (1, NON_CLIENT, (), _MASTER_REFERENCE),
    "master-reference/release/pdf_report.py::generate_master_reference_pdf": (
        1, NON_CLIENT, (), _MASTER_REFERENCE),
    "master-reference/release/pipeline.py::_artifact": (1, NON_CLIENT, (), _MASTER_REFERENCE),
    "master-reference/release/pipeline.py::build_release": (21, NON_CLIENT, (), _MASTER_REFERENCE),
    "master-reference/release/signing.py::sign_manifest": (1, NON_CLIENT, (), _MASTER_REFERENCE),
    "research_lane/producer.py::run": (
        2, NON_CLIENT, ("atomic-staging",),
        "the public-advisory intel feed docs/intel/feed-<date>.jsonl, staged as .intel-feed-*.tmp"),
    "research_lane/producer.py::main": (1, NON_CLIENT, (()) + ('atomic-staging',), "the intel feed CLI"),
    "research_lane/vault_digest.py::run": (
        2, NON_CLIENT, ("atomic-staging",),
        "the Rule-3-sanitised vault digest docs/vault-digest/digest-<date>.jsonl (git-ignored, "
        "ADR 0001 Amendment 1), staged as .vault-digest-*.tmp; sanitisation strips client identifiers"),
    "research_lane/vault_digest.py::main": (1, NON_CLIENT, (()) + ('atomic-staging',), "the vault digest CLI"),
    "tools/build_atlas_r2_authority_candidate.py::_exact_blob_archive": (1, NON_CLIENT, (), _TRANSITION),
    "tools/build_atlas_r2_authority_candidate.py::build_package": (1, NON_CLIENT, (), _TRANSITION),
    "tools/build_atlas_r2_authority_candidate.py::main": (1, NON_CLIENT, (), _TRANSITION),
    "tools/build_atlas_r3_break_this_plan_operator_study.py::_write_member": (1, NON_CLIENT, (), _TRANSITION),
    "tools/build_atlas_r3_break_this_plan_operator_study.py::build": (4, NON_CLIENT, (), _TRANSITION),
    "tools/build_atlas_r3_break_this_plan_operator_study.py::_closed_package": (4, NON_CLIENT, (), _TRANSITION),
    "tools/build_atlas_r3_break_this_plan_operator_study.py::release_phase_a": (1, NON_CLIENT, (), _TRANSITION),
    "tools/build_atlas_r3_break_this_plan_operator_study.py::_write_receipt": (1, NON_CLIENT, (), _TRANSITION),
    "tools/build_atlas_r3_break_this_plan_operator_study.py::lock_response": (1, NON_CLIENT, (), _TRANSITION),
    "tools/build_atlas_r3_break_this_plan_operator_study.py::release_phase_b": (1, NON_CLIENT, (), _TRANSITION),
    "tools/build_atlas_r3_break_this_plan_operator_study.py::release_debrief": (1, NON_CLIENT, (), _TRANSITION),
    "tools/build_atlas_r3_break_this_plan_operator_study.py::main": (6, NON_CLIENT, (), _TRANSITION),
    "tools/build_release1_replay_capsule.py::_extract": (1, NON_CLIENT, (), _TRANSITION),
    "tools/build_release1_replay_capsule.py::_stage": (3, NON_CLIENT, (), _TRANSITION),
    "tools/build_release1_replay_capsule.py::main": (3, NON_CLIENT, (), _TRANSITION),
    "tools/build_reproducible_distributions.py::_canonicalize_sdist": (4, NON_CLIENT, (), _TOOLING),
    "tools/build_reproducible_distributions.py::_extract_sdist": (1, NON_CLIENT, (), _TOOLING),
    "tools/build_reproducible_distributions.py::_build_candidate": (4, NON_CLIENT, (), _TOOLING),
    "tools/build_reproducible_distributions.py::_stage_archives": (1, NON_CLIENT, (), _TOOLING),
    "tools/build_reproducible_distributions.py::_quarantine_published_output": (1, NON_CLIENT, (), _TOOLING),
    "tools/build_reproducible_distributions.py::_publish_staged_archives": (3, NON_CLIENT, (), _TOOLING),
    "tools/build_reproducible_distributions.py::build_reproducible_distributions": (
        4, NON_CLIENT, (), _TOOLING),
    "tools/build_reproducible_distributions.py::main": (1, NON_CLIENT, (), _TOOLING),
    "tools/build_transition_dsl_prototype_assets.py::main": (1, NON_CLIENT, (), _TRANSITION),
    "tools/build_transition_runtime_inventory.py::main": (1, NON_CLIENT, (), _TRANSITION),
    "tools/build_transition_tcb_budget_proposal.py::main": (1, NON_CLIENT, (), _TRANSITION),
    "tools/canonicalize_transition_json.py::main": (1, NON_CLIENT, (), _TRANSITION),
    "tools/census_transition_tcb.py::_embedded_driver": (1, NON_CLIENT, (), _TRANSITION),
    "tools/census_transition_tcb.py::main": (1, NON_CLIENT, (), _TRANSITION),
    "tools/export_graphify_obsidian.py::_worker_export": (
        1, NON_CLIENT, (), "a portable Obsidian vault of the repository's AST code graph"),
    "tools/export_graphify_obsidian.py::export_portable_vault": (
        6, NON_CLIENT, (), "a portable Obsidian vault of the repository's AST code graph"),
    "tools/export_graphify_obsidian.py::main": (
        2, NON_CLIENT, (), "a portable Obsidian vault of the repository's AST code graph"),
    "tools/generate_prior_database_fixture.py::build_fixture": (
        3, NON_CLIENT, ("database",), "the prior-release database fixture; " + _SYNTHETIC),
    "tools/generate_prior_database_fixture.py::main": (
        1, NON_CLIENT, (()) + ('database',), "the prior-release database fixture; " + _SYNTHETIC),
    "tools/graphify_guarded.py::_producer_lock": (
        1, NON_CLIENT, (), "the guarded Graphify producer's empty lock token"),
    "tools/graphify_guarded.py::_write_refresh_receipt": (
        2, NON_CLIENT, ("atomic-staging",), "the guarded Graphify refresh receipt (digests only)"),
    "tools/graphify_guarded.py::_write_exclusive_bytes": (
        1, NON_CLIENT, (), "the repository's AST code graph and report"),
    "tools/graphify_guarded.py::_replace_pair_transactionally": (
        2, NON_CLIENT, (), "the repository's AST code graph and report"),
    "tools/graphify_guarded.py::_maybe_tree_equivalent_rebind": (
        1, NON_CLIENT, (), "the repository's AST code graph and report"),
    "tools/graphify_guarded.py::_handle_refresh_receipt": (
        1, NON_CLIENT, (()) + ('atomic-staging',), "the guarded Graphify refresh receipt (digests only)"),
    "tools/graphify_guarded.py::main": (
        4, NON_CLIENT, (()) + ('atomic-staging',), "the guarded Graphify producer over the repository's own source"),
    "tools/measure_transition_dsl_prototype.py::main": (1, NON_CLIENT, (), _TRANSITION),
    "tools/smoke_installed_transition_runtime.py::main": (2, NON_CLIENT, (), _TRANSITION),
}

#: Suffix literals that are not client artifact names, keyed by (file, literal), with the reason.
NON_CLIENT_SUFFIX_LITERALS: Mapping[tuple[str, str], str] = {
    (".github/scripts/frontend_artifact_receive.py", "-payload.json"): _CI_EVIDENCE,
    (".github/scripts/frontend_artifact_receive.py", ".stdout.json"): _CI_EVIDENCE,
    (".github/scripts/refresh_visual_baseline_pins.py", "-728.png"):
        "the synthetic visual-baseline image at the 728-pixel viewport",
    ("cisco_toolkit/distribution_verify.py", "-py3-none-any.whl"):
        "the name of the wheel distribution_verify inspects",
    ("cisco_toolkit/distribution_verify.py", ".tar.gz"):
        "the name of the sdist archive distribution_verify inspects",
    ("cisco_toolkit/transition_contract.py", ".coverage_scope.window"):
        "a JSON field path in a transition refusal message, not a file name",
    ("cisco_toolkit/transition_contract.py", ".coverage_scope.complete"):
        "a JSON field path in a transition refusal message, not a file name",
    ("cisco_toolkit/transition_tcb_review.py", ".interpreter_source.bytes"):
        "a JSON field path in a TCB review message, not a file name",
    ("cisco_toolkit/transition_tcb_review.py", ".interpreter_source.sha256"):
        "a JSON field path in a TCB review message, not a file name",
    ("portable/release_contract.py", ".manifest.json"): "Atlas release manifest sidecar; " + _RELEASE,
    ("portable/release_contract.py", ".cdx.json"): "Atlas release SBOM sidecar; " + _RELEASE,
    ("portable/release_contract.py", ".toolchain.json"): "Atlas release toolchain sidecar; " + _RELEASE,
    ("portable/release_contract.py", ".signing.json"): "Atlas release signing sidecar; " + _RELEASE,
    ("portable/release_contract.py", ".qualification.json"):
        "Atlas release qualification sidecar; " + _RELEASE,
    ("portable/release_contract.py", ".provenance.json"): "Atlas release provenance sidecar; " + _RELEASE,
    ("portable/release_contract.py", ".third-party-notices.json"):
        "Atlas release notices sidecar; " + _RELEASE,
    ("portable/release_contract.py", ".release.json"): "Atlas release index; " + _RELEASE,
    ("tools/verify_graph_report.py", ".graphify_labels.json"):
        "the Graphify community-label file beside the repository's AST code graph",
    ("webapp/backend/ingest.py", ".atlas-redaction.lock"):
        "the redaction output lock token, which never holds data",
    ("webapp/backend/observe_ui_projection_contract.py", "-schema.json"):
        "UI projection schema observations generated from code",
}

# --------------------------------------------------------------------------- PowerShell writers

#: The PowerShell writer that copies client databases (W65 registry header names it).
POWERSHELL_DATABASE_WRITERS = ("portable/make_stick.ps1",)


def powershell_database_names(root: Path = ROOT) -> list[tuple[str, str]]:
    """Every literal database file name a tracked PowerShell writer builds: ``(file:line, template)``.

    ``"pre-update-$RunId.db"`` becomes ``pre-update-0.db``; a staging name built as
    ``("." + $leaf + ".partial")`` is reported as ``.0.db.partial`` for each ``$leaf`` template.
    """
    found: list[tuple[str, str]] = []
    for relative in POWERSHELL_DATABASE_WRITERS:
        text = (root / relative).read_text(encoding="utf-8")
        for match in re.finditer(r'"([^"\s]+\.(?:db|sqlite3?|partial))"', text):
            template = re.sub(r"\$\{?[A-Za-z_][\w]*\}?", "0", match.group(1))
            line = text.count("\n", 0, match.start()) + 1
            found.append((f"{relative}:{line}", template))
        # Staging names pair with the database leaf assigned in the same PowerShell function.
        offset = 0
        for chunk in re.split(r"(?m)^(?=function\s)", text):
            leaves = [
                re.sub(r"\$\{?[A-Za-z_][\w]*\}?", "0", match.group(1))
                for match in re.finditer(r'(?m)\$leaf\s*=\s*"([^"]+)"\s*$', chunk)
            ]
            for match in re.finditer(r'"\."\s*\+\s*\$leaf\s*\+\s*"(\.[A-Za-z]+)"', chunk):
                line = text.count("\n", 0, offset + match.start()) + 1
                found.extend((f"{relative}:{line}", f".{leaf}{match.group(1)}") for leaf in leaves)
            offset += len(chunk)
    return sorted(set(found))


# --------------------------------------------------------------------------- the check

_ANALYSES: dict[str, tuple[dict[str, int], set[str], dict[str, set[str]]]] = {}
_UNCLASSIFIED_LITERALS: dict[str, dict[str, set[str]]] = {}
_UNRESOLVED_NAME_TEMPLATES: dict[str, dict[str, set[str]]] = {}
_NON_CLIENT_LITERAL_ORIGINS: dict[str, dict[tuple[str, str], str]] = {}
_CLIENT_LITERAL_OBLIGATIONS: dict[str, dict[str, set[str]]] = {}
_NAME_MODEL_PROBLEMS: dict[str, list[str]] = {}


def analysis(root: Path = ROOT) -> tuple[dict[str, int], set[str], dict[str, set[str]]]:
    """``(write counts, path-parameter writers, resolved classes)`` for ``root`` (cached per root)."""
    key = str(Path(root).resolve())
    if key not in _ANALYSES:
        program = _Program(Path(root))
        counts: Counter[str] = Counter()
        resolved: dict[str, set[str]] = {}
        unclassified: dict[str, set[str]] = {}
        unresolved: dict[str, set[str]] = {}
        non_client: dict[tuple[str, str], str] = {}
        client_literals: dict[str, set[str]] = {}
        model_problems: list[str] = []
        _classes, classify = _registry()
        for file in program.files:
            for function in [file.top, *file.functions]:
                sites = program.sites(function)
                if not sites:
                    continue
                counts[function.key] += len(sites)
                resolve = program.resolver(function)
                for _kind, targets in sites:
                    for target in targets:
                        try:
                            templates = _templates(target, resolve)
                        except NameModelLimit as error:
                            model_problems.append(f"filename model refusal at {function.key}: {error}")
                            continue
                        for template in templates:
                            if template is None:
                                continue
                            leaf = re.split(r"[/\\]", template)[-1]
                            if leaf:
                                class_key = classify(f"customer-output/{leaf}")
                                if class_key:
                                    resolved.setdefault(function.key, set()).add(class_key)
                                elif (not getattr(template, "complete", True) and not getattr(template, "identifying", False)
                                      and not _identifying_suffix(target, resolve)):
                                    unresolved.setdefault(function.key, set()).add(leaf)
                                else:
                                    unclassified.setdefault(function.key, set()).add(leaf)
                                    origin = getattr(target, "census_non_client_origin", None)
                                    if origin is not None:
                                        non_client[(function.key, leaf)] = origin
                                    else:
                                        client_literals.setdefault(function.key, set()).add(leaf)
        _ANALYSES[key] = (dict(sorted(counts.items())), set(program.writers), resolved)
        _UNCLASSIFIED_LITERALS[key] = unclassified
        _UNRESOLVED_NAME_TEMPLATES[key] = unresolved
        _NON_CLIENT_LITERAL_ORIGINS[key] = non_client
        _CLIENT_LITERAL_OBLIGATIONS[key] = client_literals
        _NAME_MODEL_PROBLEMS[key] = sorted(set(model_problems))
    return _ANALYSES[key]


def unclassified_site_literals(root: Path = ROOT) -> dict[str, set[str]]:
    """Keep resolved names that match no class, including extension-less fixed names."""
    analysis(root)
    return _UNCLASSIFIED_LITERALS[str(Path(root).resolve())]


def unresolved_site_templates(root: Path = ROOT) -> dict[str, set[str]]:
    """Partially known, unclassified names stay uncertainty evidence rather than invented literals."""
    analysis(root)
    return _UNRESOLVED_NAME_TEMPLATES[str(Path(root).resolve())]


def census_problems(
    root: Path = ROOT,
    census: Mapping[str, tuple[int, str, tuple[str, ...], str]] | None = None,
    registry_keys: Iterable[str] | None = None,
) -> list[str]:
    """Every disagreement between the code's write sites and the census, as readable lines."""
    census = WRITE_SITE_CENSUS if census is None else census
    if registry_keys is None:
        registry_keys = [row[0] for row in _registry()[0]]
    known = frozenset(registry_keys)
    observed, writers, resolved = analysis(root)
    problems: list[str] = list(_NAME_MODEL_PROBLEMS[str(Path(root).resolve())])
    for key in sorted(set(observed) - set(census)):
        problems.append(f"unclassified write site: {key} ({observed[key]} write(s))")
    for key in sorted(set(census) - set(observed)):
        problems.append(f"census row has no write site any more: {key}")
    for key in sorted(set(census) & set(observed)):
        count, disposition, keys, why = census[key]
        if count != observed[key]:
            problems.append(f"write count changed: {key} census={count} observed={observed[key]}")
        if disposition not in DISPOSITIONS:
            problems.append(f"unknown disposition {disposition!r}: {key}")
        if not str(why).strip():
            problems.append(f"census row gives no reason: {key}")
        if disposition == CLIENT and not keys:
            problems.append(f"client write site names no registry class: {key}")
        if disposition == CLIENT:
            for leaf in sorted(_CLIENT_LITERAL_OBLIGATIONS[str(Path(root).resolve())].get(key, set())):
                problems.append(f"client write site resolves to unclassified name {leaf!r}: {key}")
        for class_key in keys:
            if class_key not in known:
                problems.append(f"write site names an unregistered class {class_key!r}: {key}")
        if disposition == DELEGATED and key not in writers:
            problems.append(f"delegated row is not a path-parameter writer: {key}")
        for class_key in sorted(resolved.get(key, set()) - set(keys)):
            problems.append(f"write site resolves to class {class_key!r} its row does not name: {key}")
    return problems


def suffix_literal_problems(
    root: Path = ROOT,
    non_client: Mapping[tuple[str, str], str] | None = None,
) -> list[str]:
    non_client = NON_CLIENT_SUFFIX_LITERALS if non_client is None else non_client
    _classes, classify = _registry()
    literals = suffix_literals(root)
    problems: list[str] = []
    seen: set[tuple[str, str]] = set()
    for location, literal in literals:
        relative = location.rsplit(":", 1)[0]
        seen.add((relative, literal))
        if (relative, literal) in non_client:
            continue
        if classify(f"customer-output/Acme{literal}") is None:
            problems.append(f"unclassified output-name suffix literal {literal!r} at {location}")
    for (relative, literal), why in sorted(non_client.items()):
        if (relative, literal) not in seen:
            problems.append(f"non-client suffix literal no longer appears: {literal!r} in {relative}")
        if classify(f"customer-output/Acme{literal}") is not None:
            problems.append(f"non-client suffix literal is a registered client class: {literal!r} in {relative}")
        if not str(why).strip():
            problems.append(f"non-client suffix literal gives no reason: {literal!r} in {relative}")
    return problems


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] == ["--dump"]:
        counts, writers, resolved = analysis(ROOT)
        for key, count in counts.items():
            mark = "W" if key in writers else " "
            print(f"{count}\t{mark}\t{key}\t{sorted(resolved.get(key, set()))}")
        return 0
    problems = census_problems(ROOT) + suffix_literal_problems(ROOT)
    for line in problems:
        print(line)
    counts, writers, _resolved = analysis(ROOT)
    print(f"{len(counts)} write site function(s) ({sum(counts.values())} writes, {len(writers)} "
          f"path-parameter writers) and {len(suffix_literals(ROOT))} suffix literal(s) in "
          f"{len(scanned_files(ROOT))} file(s); {len(problems)} census problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    # Run as a script, sys.path[0] is tests/; the registry import needs the repository root.
    sys.path.insert(0, str(ROOT))
    raise SystemExit(main())
