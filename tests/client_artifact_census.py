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
* **Suffix literals.** :func:`suffix_literals` collects every literal appended to an output stem
  (``+``, f-string tails, ``%`` and ``.format`` templates, ``with_suffix``/``with_name``,
  ``str.join``), and each one must be a registered class or a :data:`NON_CLIENT_SUFFIX_LITERALS`
  entry keyed by (file, literal) with a reason.

Bounds, stated rather than implied: a bare file name joined onto a directory for READING is not a
write; dynamic dispatch (``getattr(module, spec.writer_name)``) is tied by the docmeta registry, not
here; files written by a subprocess are the subprocess's own rows; ``.ps1`` and JavaScript writers
are tied by literal checks in ``tests/test_client_artifact_census.py``.

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
import re
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping

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
    if name in _TARGET_FIRST:
        targets = [first] if first is not None else []
        targets += [item.value for item in call.keywords if item.arg in {"dir", "prefix", "suffix", "filename", "base_name", "database"}]
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
            arguments = [] if call is None else [*call.args, *(k.value for k in call.keywords)]
            found.append((f"writer:{target.key}", arguments))
        return found


def _references(node: ast.AST, names: set[str]) -> bool:
    return any(isinstance(leaf, ast.Name) and leaf.id in names for leaf in ast.walk(node))


def scan(root: Path = ROOT) -> tuple[dict[str, int], set[str]]:
    """Return ``({"path::qualname": write count}, {path-parameter writer keys})``."""
    counts, writers, _resolved = analysis(root)
    return counts, writers


def write_sites(root: Path = ROOT) -> dict[str, int]:
    return analysis(root)[0]


# --------------------------------------------------------------------------- resolved names

_FILE_NAME = re.compile(r"[^/\\]*\.[A-Za-z0-9][A-Za-z0-9-]*$")


def _templates(node: ast.AST, resolve, depth: int = 0) -> list[str]:
    """Literal name templates an expression can produce; an unknown part is ``0``."""
    if depth > 4:
        return ["0"]
    text = _constant_text(node)
    if text is not None:
        return [text]
    if isinstance(node, ast.JoinedStr):
        parts = [p.value if isinstance(p, ast.Constant) else "0" for p in node.values]
        return ["".join(str(p) for p in parts)]
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return [a + b for a in _templates(node.left, resolve, depth + 1)
                for b in _templates(node.right, resolve, depth + 1)][:16]
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return _templates(node.right, resolve, depth + 1)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod) and _constant_text(node.left):
        return [re.sub(r"%[-#0 +]*\d*(?:\.\d+)?[sdifrx]", "0", _constant_text(node.left))]
    if isinstance(node, ast.Name):
        values = resolve(node)
        out = [t for value in values for t in _templates(value, resolve, depth + 1)]
        return out[:16] or ["0"]
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "join" and node.args:
            return _templates(node.args[-1], resolve, depth + 1)
        if isinstance(func, ast.Attribute) and func.attr in {"with_suffix", "with_name"} and node.args:
            return ["0" + t if func.attr == "with_suffix" else t for t in _templates(node.args[0], resolve, depth + 1)]
        if isinstance(func, ast.Attribute) and func.attr == "format" and _constant_text(func.value):
            return [re.sub(r"\{[^{}]*\}", "0", _constant_text(func.value))]
        if isinstance(func, ast.Name) and func.id in {"Path", "PurePath", "PurePosixPath", "str"} and node.args:
            return _templates(node.args[-1], resolve, depth + 1)
    if isinstance(node, ast.IfExp):
        return _templates(node.body, resolve, depth + 1) + _templates(node.orelse, resolve, depth + 1)
    if isinstance(node, ast.BoolOp):
        return [t for value in node.values for t in _templates(value, resolve, depth + 1)]
    return ["0"]


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

#: Where browser downloads are named: AssessHub's SPA and Atlas Scope (non-test sources).
DOWNLOAD_SOURCE_ROOTS = ("webapp/frontend/src", "atlas-scope/src")
_DOWNLOAD_PATTERNS = (
    re.compile(r"\bdownload=\{\s*(`[^`]*`|\"[^\"]*\"|'[^']*'|[^}]+?)\s*\}"),
    re.compile(r"\bdownload=(\"[^\"]*\")"),
    re.compile(r"\.download\s*=\s*([^;\n]+?)\s*;"),
    re.compile(r"\bexportFilename=\{\s*(`[^`]*`|\"[^\"]*\"|[^}]+?)\s*\}"),
    re.compile(r"\bexportFilename\s*=\s*(`[^`]*`|\"[^\"]*\"|[A-Za-z_$][\w$]*)\s*,"),
    re.compile(r"\bdownloadJsonDocument\(\s*(?:[^;]*?),\s*(`[^`]*`|\"[^\"]*\"|'[^']*'|[A-Za-z_$][\w$.]*(?:\([^()]*\))?)\s*\)",
               re.S),
)
#: Download-name expressions that are not literals, each with why its name still classifies.
DOWNLOAD_NAME_PASSTHROUGH: Mapping[tuple[str, str], str] = {
    ("webapp/frontend/src/receiptExport.ts", "filename"):
        "downloadJsonDocument's own parameter; every caller's name is a scanned download name",
    ("webapp/frontend/src/components/ComparisonDecision.tsx", "safeFilename(filename)"):
        "safeFilename appends COMPARISON_RECEIPT_SUFFIX to any caller name (unit-tested)",
    ("webapp/frontend/src/components/ComparisonDecision.tsx", "DEFAULT_COMPARISON_EXPORT"):
        "atlas-receipt + COMPARISON_RECEIPT_SUFFIX",
}


def _is_frontend_test(relative: str) -> bool:
    name = relative.rsplit("/", 1)[-1]
    return bool(re.search(r"\.(test|spec)\.[cm]?[jt]sx?$", name)) or "/e2e" in relative or "/__tests__/" in relative


def download_names(root: Path = ROOT) -> list[tuple[str, str, str | None]]:
    """Every browser download name: ``(file:line, expression, literal template or None)``."""
    found: list[tuple[str, str, str | None]] = []
    for base in DOWNLOAD_SOURCE_ROOTS:
        directory = root / base
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*")):
            if path.suffix not in {".ts", ".tsx"} or "node_modules" in path.parts:
                continue
            relative = path.relative_to(root).as_posix()
            if _is_frontend_test(relative):
                continue
            text = path.read_text(encoding="utf-8")
            for pattern in _DOWNLOAD_PATTERNS:
                for match in pattern.finditer(text):
                    expression = match.group(1).strip()
                    line = text.count("\n", 0, match.start()) + 1
                    found.append((f"{relative}:{line}", expression, _download_template(expression)))
    return sorted(set(found))


def _download_template(expression: str) -> str | None:
    if expression[:1] in {"`", '"', "'"} and expression[-1:] == expression[:1]:
        return re.sub(r"\$\{[^{}]*\}", "0", expression[1:-1])
    return None


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
        4, CLIENT, _CAPTURES + _COLLECTION_SIDECARS,
        "live collector: one <command>.txt capture per command under <collection>/<host>/, plus "
        "device_info.json, command_index.json and _capture_meta.json through write_json_file"),
    "COLLECT_PARSE_V3_23_0.py::main.collect_one": (
        1, CLIENT, _CAPTURES + _COLLECTION_SIDECARS, "runs collect() for one device"),
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
        ("pre-change-certificate", "comparison-receipt", "trend-comparisons", "explorer",
         "topology-mermaid", "topology-graphviz", "engagement-gate-state")
        + _OFFICE + _CAPTURES + _COLLECTION_SIDECARS,
        "--compare writes <diff>.xlsx, <diff>.precert.json and <diff>.comparison.json; --trend writes "
        "<trend>.xlsx and <trend>.trend-comparisons.json; the assessment run collects, then writes "
        "topology.mmd/.dot, <output>_explorer.html and the DOCX/PPTX family, consulting the gate "
        "ledger, before _stage_finalize"),
    "COLLECT_PARSE_V3_23_0.py::_stage_finalize": (
        14, CLIENT,
        ("protocol-assurance-export", "explorer", "phase-timings", "run-manifest", "snapshot",
         "incomplete-marker", "word-document", "workbook", "redaction-staging")
        + _RAW_CAPTURE_SHAPES,
        "<output>.protocol-assurance.json, the BOUND explorer/runbook/MOP/workbook refresh, "
        "<output>.phase_timings.json, <output>.run_manifest.json and <output>.incomplete.json, plus "
        "the --redact-collection in-place scrub"),
    "COLLECT_PARSE_V3_23_0.py::_stage_finalize._publish_snapshot": (
        1, CLIENT, ("snapshot",), "<output>.snapshot.json, the parsed estate"),
    "COLLECT_PARSE_V3_23_0.py::_stage_finalize._save_workbook": (
        1, CLIENT, ("workbook",),
        "the assessment workbook <output>.xlsx (staged as .<stem>.receipt-<nonce>.tmp.xlsx)"),
    "COLLECT_PARSE_V3_23_0.py::_write_incomplete_marker": (
        1, CLIENT, ("incomplete-marker",),
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
        1, DELEGATED, (),
        "per-device NRFU command files <out_dir>/<wave>/<host>.txt in a caller-owned directory; no "
        "caller exists today, so the first one becomes its own census row"),
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
        1, CLIENT, ("engagement-gate-state",), "appends an audit line to the gate ledger"),
    "cisco_toolkit/gate_state.py::_record_refusal": (
        1, CLIENT, ("engagement-gate-state",), "records a refused gate in the ledger"),
    "cisco_toolkit/gate_state.py::record_decision": (
        1, CLIENT, ("engagement-gate-state",), "records an approval or revocation in the ledger"),
    "cisco_toolkit/gate_state.py::bind_engagement": (
        1, CLIENT, ("engagement-gate-state",), "binds the ledger to an engagement identifier"),
    "cisco_toolkit/gate_state.py::enforce": (
        3, CLIENT, ("engagement-gate-state",), "records an override or refusal in the ledger"),
    "cisco_toolkit/gate_state.py::main": (
        2, CLIENT, ("engagement-gate-state",), "the gate-ledger CLI (bind, approve, revoke)"),
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
        7, NON_CLIENT, (), _REFERENCE_PACKS),
    "cisco_toolkit/registry_integrity.py::update_manifest": (2, NON_CLIENT, (), _REFERENCE_PACKS),
    "cisco_toolkit/registry_integrity.py::_restore_snapshot": (
        2, NON_CLIENT, (), "rollback of " + _REFERENCE_PACKS),
    "cisco_toolkit/gen_oui_registry.py::write_registry": (1, NON_CLIENT, (), _REFERENCE_PACKS),
    "cisco_toolkit/gen_oui_registry.py::build_authoritative": (1, NON_CLIENT, (), _REFERENCE_PACKS),
    "cisco_toolkit/gen_oui_registry.py::_legacy_main": (1, NON_CLIENT, (), _REFERENCE_PACKS),
    "cisco_toolkit/gen_oui_registry.py::main": (2, NON_CLIENT, (), _REFERENCE_PACKS),
    "cisco_toolkit/data/gen_port_registry.py::build": (1, NON_CLIENT, (), _REFERENCE_PACKS),
    "cisco_toolkit/data/gen_port_registry.py::main": (1, NON_CLIENT, (), _REFERENCE_PACKS),
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
        3, CLIENT, ("database", "database-backup-partial", "database-wal", "database-shm"),
        "backups/assesshub-<stamp>.db, staged as assesshub-<stamp>-<pid>-<hex>.db.partial"),
    "webapp/backend/storage.py::_backup_campaign_evidence": (
        1, CLIENT, ("database", "database-wal", "database-shm"),
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
        1, NON_CLIENT, (), ".atlas-redaction.lock is an empty lock token; it never holds data"),
    "webapp/backend/serve.py::_writable_failure": (
        1, NON_CLIENT, (), "an empty write probe, unlinked immediately"),
    "webapp/backend/serve.py::run_selftest": (2, NON_CLIENT, (), "write probes of the data folders"),
    "webapp/backend/serve.py::run_redaction": (
        1, CLIENT, _REDACTION_RUN, "Atlas.exe --redact-folder runs the field redaction"),
    "webapp/backend/serve.py::run_database_preflight": (
        1, CLIENT, ("database", "database-wal", "database-shm"),
        "Atlas.exe database preflight over a copy of the operator's database"),
    "webapp/backend/serve.py::_main_scoped": (
        4, CLIENT, _REDACTION_RUN + ("database", "database-wal", "database-shm"),
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
        1, CLIENT, ("database", "database-wal", "database-shm"),
        "opens the operator's AssessHub database copy read-only (mode=ro, query_only)"),
    "portable/database_preflight.py::census": (
        1, CLIENT, ("database", "database-wal", "database-shm"), "counts rows of that copy"),
    "portable/database_preflight.py::verify_migrated_copy": (
        2, CLIENT, ("database", "database-wal", "database-shm"), "compares that copy after migration"),
    "portable/database_preflight.py::migrate_and_compare": (
        2, CLIENT, ("database", "database-wal", "database-shm"), "migrates and compares that copy"),
    "portable/build_atlas.py::build": (1, NON_CLIENT, (), _RELEASE),
    "portable/build_atlas.py::smoke": (
        2, NON_CLIENT, (), _RELEASE + "; the smoke copy's data directory comes from a synthetic run"),
    "portable/build_atlas.py::_detach_runtime_data": (
        1, NON_CLIENT, (),
        "moves the SMOKE copy's data directory, created by the synthetic field-layout smoke run"),
    "portable/build_release.py::build_release": (2, NON_CLIENT, (), _RELEASE),
    "portable/build_release.py::main": (2, NON_CLIENT, (), _RELEASE),
    "portable/package_signed_release.py::_independent_authenticode": (1, NON_CLIENT, (), _RELEASE),
    "portable/package_signed_release.py::package_signed": (3, NON_CLIENT, (), _RELEASE),
    "portable/package_signed_release.py::main": (2, NON_CLIENT, (), _RELEASE),
    "portable/prepare_signing.py::prepare": (3, NON_CLIENT, (), _RELEASE),
    "portable/prepare_signing.py::main": (1, NON_CLIENT, (), _RELEASE),
    "portable/release_contract.py::_record_build_modules": (1, NON_CLIENT, (), _RELEASE),
    "portable/release_contract.py::_npm_build_attribution": (1, NON_CLIENT, (), _RELEASE),
    "portable/release_contract.py::toolchain_receipt": (1, NON_CLIENT, (), _RELEASE),
    "portable/release_contract.py::_write_checksums": (1, NON_CLIENT, (), _RELEASE),
    "portable/release_contract.py::_write_deterministic_zip": (1, NON_CLIENT, (), _RELEASE),
    "portable/release_contract.py::build_portable_release": (9, NON_CLIENT, (), _RELEASE),
    "portable/qualify_atlas.py::qualify": (3, NON_CLIENT, ("database", "capture-show", "config-file-cfg"), _RELEASE + "; " + _SYNTHETIC),
    "portable/qualify_atlas.py::main": (2, NON_CLIENT, (), "the qualification receipt"),
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
    ".github/scripts/frontend_artifact_receive.py::select_registry": (3, NON_CLIENT, (), _CI_EVIDENCE),
    ".github/scripts/frontend_artifact_receive.py::candidate": (1, NON_CLIENT, (), _CI_EVIDENCE),
    ".github/scripts/frontend_artifact_receive.py::patch": (3, NON_CLIENT, (), _CI_EVIDENCE),
    ".github/scripts/frontend_artifact_receive.py::main": (11, NON_CLIENT, (), _CI_EVIDENCE),
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
        1, NON_CLIENT, (), "rewrites the synthetic visual-baseline pins in place"),
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
    "master-reference/release/pdf_report.py::build_master_reference_pdf": (1, NON_CLIENT, (), _MASTER_REFERENCE),
    "master-reference/release/pdf_report.py::generate_master_reference_pdf": (
        1, NON_CLIENT, (), _MASTER_REFERENCE),
    "master-reference/release/pipeline.py::_artifact": (1, NON_CLIENT, (), _MASTER_REFERENCE),
    "master-reference/release/pipeline.py::build_release": (21, NON_CLIENT, (), _MASTER_REFERENCE),
    "master-reference/release/signing.py::sign_manifest": (1, NON_CLIENT, (), _MASTER_REFERENCE),
    "research_lane/producer.py::run": (
        2, NON_CLIENT, ("atomic-staging",),
        "the public-advisory intel feed docs/intel/feed-<date>.jsonl, staged as .intel-feed-*.tmp"),
    "research_lane/producer.py::main": (1, NON_CLIENT, (), "the intel feed CLI"),
    "research_lane/vault_digest.py::run": (
        2, NON_CLIENT, ("atomic-staging",),
        "the Rule-3-sanitised vault digest docs/vault-digest/digest-<date>.jsonl (git-ignored, "
        "ADR 0001 Amendment 1), staged as .vault-digest-*.tmp; sanitisation strips client identifiers"),
    "research_lane/vault_digest.py::main": (1, NON_CLIENT, (), "the vault digest CLI"),
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
        1, NON_CLIENT, (), "the prior-release database fixture; " + _SYNTHETIC),
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
        1, NON_CLIENT, (), "the guarded Graphify refresh receipt (digests only)"),
    "tools/graphify_guarded.py::main": (
        4, NON_CLIENT, (), "the guarded Graphify producer over the repository's own source"),
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


def analysis(root: Path = ROOT) -> tuple[dict[str, int], set[str], dict[str, set[str]]]:
    """``(write counts, path-parameter writers, resolved classes)`` for ``root`` (cached per root)."""
    key = str(Path(root).resolve())
    if key not in _ANALYSES:
        program = _Program(Path(root))
        counts: Counter[str] = Counter()
        resolved: dict[str, set[str]] = {}
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
                        for template in _templates(target, resolve):
                            leaf = re.split(r"[/\\]", template)[-1]
                            if leaf and leaf != "0" and _FILE_NAME.search(leaf):
                                class_key = classify(f"customer-output/{leaf}")
                                if class_key:
                                    resolved.setdefault(function.key, set()).add(class_key)
        _ANALYSES[key] = (dict(sorted(counts.items())), set(program.writers), resolved)
    return _ANALYSES[key]


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
    problems: list[str] = []
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
