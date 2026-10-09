"""Shared structural scans for the W59 SSH tests (no test functions here; tests/ is on sys.path via conftest.py).

W59 PR-2 review (P3-e): the T8 connection-constructor guard was written twice -- a structural taint scan in
``tests/test_ssh_session.py`` (W59 PR-1 review P3-f) and a named-subset spelling match in
``tests/test_legacy_ssh_consent.py`` that a ``_netmiko.ConnectHandler(...)`` or an aliased class map walked past.
Both now call ONE helper, :func:`connection_constructor_calls`, and both T10 scans share ONE shipped-source
denominator, :func:`shipped_python_files` (the wheel's runtime inventory plus the Atlas bundle's import closure).

Moved verbatim from ``tests/test_ssh_session.py`` (W59 PR-1 review P3-f, closed in its round 2: the scope-aware
shape fixpoint and the argument-site rule), which re-imports these names.
"""
from __future__ import annotations

import ast
import warnings
from pathlib import Path

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
SSH_LIBRARIES = ("netmiko", "paramiko")


def connection_roots(tree):
    """Every name an import of netmiko or paramiko binds (a module, the class map, a driver or client class), derived
    from the import statements, never hand-listed. Exception classes (imported from an exceptions module) construct
    no connection and are not roots."""
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in SSH_LIBRARIES:
                    roots.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            module = node.module or ""
            if module.split(".")[0] in SSH_LIBRARIES and not module.endswith(("exceptions", "ssh_exception")):
                roots.update(alias.asname or alias.name for alias in node.names)
    return roots


# A value's taint SHAPE: False (carries nothing), True (a connection-capable class, callable or module), (_SEQ, (s,
# ...)) a tuple or list display with one shape per element, or (_BAG, s) any other container whose members have shape s.
_SEQ, _BAG = "seq", "bag"
#: calls whose result can be ANY name -- a namespace, an import by string, an evaluated string -- so it is a root
_DYNAMIC_ROOT_CALLS = frozenset({"__import__", "import_module", "globals", "vars", "locals", "eval"})
#: calls that execute code from a string: each is a violation by itself, whatever it is handed
_DYNAMIC_CODE_CALLS = frozenset({"exec", "eval", "compile"})
#: readers the shape model already follows: handing them a tainted value hands it to no code
_READERS = frozenset({"type", "getattr", "isinstance", "issubclass", "hasattr"})
#: container operations that never call what they are given; on an already-tainted container they keep it tainted
_CONTAINER_OPS = frozenset({"get", "setdefault", "pop", "append", "extend", "insert", "add", "update", "index",
                            "count", "remove", "discard", "copy", "items", "keys", "values"})
#: attribute reads that are data, never a class (a class's name, a module's version)
_DATA_DUNDERS = frozenset({"__name__", "__qualname__", "__module__", "__version__", "__doc__"})
_FUNCS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)


def _any(shape):
    if shape is True:
        return True
    if isinstance(shape, tuple):
        return _any(shape[1]) if shape[0] == _BAG else any(_any(e) for e in shape[1])
    return False


def _elem(shape):
    """What iterating, indexing or a container operation on a value of `shape` yields."""
    if shape is True:
        return True
    if isinstance(shape, tuple):
        if shape[0] == _BAG:
            return shape[1]
        out = False
        for e in shape[1]:
            out = _join(out, e)
        return out
    return False


def _join(a, b):
    if a is True or b is True:
        return True
    if not a:
        return b
    if not b:
        return a
    if a == b:
        return a
    if a[0] == b[0] == _SEQ and len(a[1]) == len(b[1]):
        return (_SEQ, tuple(_join(x, y) for x, y in zip(a[1], b[1])))
    return (_BAG, _join(_elem(a), _elem(b)))


def _bag(shape):
    return (_BAG, shape) if _any(shape) else False


def _target_names(target):
    if isinstance(target, ast.Name):
        yield target.id
    elif isinstance(target, (ast.Tuple, ast.List)):
        for e in target.elts:
            yield from _target_names(e)
    elif isinstance(target, ast.Starred):
        yield from _target_names(target.value)


class _Scopes:
    """Python's own name resolution, statically: each function (and lambda) has its locals -- parameters and every
    name it binds, minus its ``global`` / ``nonlocal`` declarations -- and a name resolves to the innermost enclosing
    FUNCTION that binds it (class bodies are skipped, as Python skips them), else to the module. A method's first
    parameter is keyed by its class, so ``self`` in one method is the same object as in another."""

    def __init__(self, tree):
        self.scope_of, self.parent, self.locals, self.kind, self.self_key = {}, {}, {"<module>": set()}, {}, {}
        self.defs = {}                                   # binding key of a def/class -> its node
        self._visit(tree, "<module>")

    def _bound(self, node):
        out = set()
        if isinstance(node, _FUNCS):
            a = node.args
            out |= {x.arg for x in a.posonlyargs + a.args + a.kwonlyargs}
            out |= {x.arg for x in (a.vararg, a.kwarg) if x is not None}
        declared = set()
        body = [node.body] if isinstance(node, ast.Lambda) else node.body
        stack = list(body) if isinstance(body, list) else [body]
        while stack:
            n = stack.pop()
            if isinstance(n, (ast.Global, ast.Nonlocal)):
                declared |= set(n.names)
                continue
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                out.add(n.name)
                stack.extend(n.decorator_list)
                if not isinstance(n, ast.ClassDef):
                    stack.extend(n.args.defaults + [d for d in n.args.kw_defaults if d is not None])
                else:
                    stack.extend(n.bases + [k.value for k in n.keywords])
                continue                                 # its body is its own scope
            if isinstance(n, ast.Lambda):
                stack.extend(n.args.defaults + [d for d in n.args.kw_defaults if d is not None])
                continue
            if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
                out.add(n.id)
            elif isinstance(n, (ast.Import, ast.ImportFrom)):
                out |= {(a.asname or a.name).split(".")[0] for a in n.names}
            elif isinstance(n, ast.ExceptHandler) and n.name:
                out.add(n.name)
            stack.extend(ast.iter_child_nodes(n))
        return out - declared, declared

    def _visit(self, node, scope):
        for child in ast.iter_child_nodes(node):
            self.scope_of[id(child)] = scope
            if isinstance(child, (*_FUNCS, ast.ClassDef)):
                name = getattr(child, "name", f"<lambda@{child.lineno}:{child.col_offset}>")
                inner = name if scope == "<module>" else f"{scope}.{name}"
                if not isinstance(child, ast.Lambda):
                    where = (scope, name) if self.kind.get(scope) == "class" else self.resolve_name(name, scope)
                    self.defs.setdefault(where, []).append(child)
                self.parent[inner] = scope
                self.kind[inner] = "class" if isinstance(child, ast.ClassDef) else "function"
                if isinstance(child, ast.ClassDef):
                    self.locals[inner] = set()
                    for item in child.body:
                        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.args.args:
                            self.self_key[(f"{inner}.{item.name}", item.args.args[0].arg)] = ("<self>", inner)
                else:
                    self.locals[inner], _declared = self._bound(child)
                # decorators, defaults and bases are evaluated in the ENCLOSING scope
                for sub in (getattr(child, "decorator_list", []) + getattr(child, "bases", [])
                            + [k.value for k in getattr(child, "keywords", [])]):
                    self._mark(sub, scope)
                if isinstance(child, _FUNCS):
                    for d in child.args.defaults + [d for d in child.args.kw_defaults if d is not None]:
                        self._mark(d, scope)
                self._visit_body(child, inner)
            else:
                self._visit(child, scope)

    def _mark(self, node, scope):
        for sub in ast.walk(node):
            self.scope_of[id(sub)] = scope
        self._visit(node, scope)

    def _visit_body(self, node, scope):
        body = [node.body] if isinstance(node, ast.Lambda) else node.body
        for stmt in body:
            self.scope_of[id(stmt)] = scope
            if isinstance(stmt, (*_FUNCS, ast.ClassDef)):
                wrapper = ast.Module(body=[stmt], type_ignores=[])
                self._visit(wrapper, scope)
            else:
                self._visit(stmt, scope)

    def resolve_name(self, name, scope):
        """The binding key of `name` read in `scope`."""
        if (scope, name) in self.self_key:
            return self.self_key[(scope, name)]
        s, first = scope, True
        while s != "<module>":
            if (self.kind.get(s) == "function" or first) and name in self.locals.get(s, ()):
                return (s, name)
            first = False
            s = self.parent.get(s, "<module>")
        return ("<module>", name)

    def key(self, node):
        scope = self.scope_of.get(id(node), "<module>")
        # a method's first parameter, anywhere inside that method (nested closures included)
        s = scope
        while s != "<module>":
            if (s, node.id) in self.self_key:
                return self.self_key[(s, node.id)]
            if node.id in self.locals.get(s, ()) and self.kind.get(s) == "function":
                break
            s = self.parent.get(s, "<module>")
        return self.resolve_name(node.id, scope)


class _Env:
    """Shapes of every binding key, of every (receiver, attribute) store, and of what every def returns."""

    def __init__(self, tree):
        self.scopes = _Scopes(tree)
        self.names = {("<module>", name): True for name in connection_roots(tree)}
        for node in ast.walk(tree):                      # a root bound inside a function is that function's local
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                scope = self.scopes.scope_of.get(id(node), "<module>")
                for alias in node.names:
                    bound = (alias.asname or alias.name).split(".")[0]
                    if bound in connection_roots(ast.Module(body=[node], type_ignores=[])):
                        self.names[self.scopes.resolve_name(bound, scope)] = True
        self.attrs, self.returns, self.methods = {}, {}, {}
        self.changed = False

    def key(self, node):
        return self.scopes.key(node)

    def receiver(self, node):
        return self.key(node) if isinstance(node, ast.Name) else ast.unparse(node)

    def put(self, table, key, shape):
        if not shape:
            return
        old = table.get(key, False)
        new = _join(old, shape)
        if new != old:
            table[key] = new
            self.changed = True

    # ------------------------------------------------------------------------------------------- shapes ---
    def shape(self, node):
        if node is None:
            return False
        if isinstance(node, ast.Name):
            key = self.key(node)
            own = self.names.get(key, False)
            for (recv, _attr), s in self.attrs.items():
                if recv == key:                     # an object carrying a tainted attribute, used whole
                    own = _join(own, _bag(s))
            return own
        if isinstance(node, ast.Attribute):
            if node.attr in _DATA_DUNDERS:
                return False
            base = self.names.get(self.key(node.value), False) if isinstance(node.value, ast.Name) \
                else self.shape(node.value)
            if base is True:
                return True
            return self.attrs.get((self.receiver(node.value), node.attr), False)
        if isinstance(node, ast.Subscript):
            if ast.unparse(node.value) in ("sys.modules", "modules"):
                key = node.slice
                return not (isinstance(key, ast.Constant) and isinstance(key.value, str)) \
                    or key.value.split(".")[0] in SSH_LIBRARIES
            base = self.shape(node.value)
            if isinstance(base, tuple) and base[0] == _SEQ and isinstance(node.slice, ast.Constant) \
                    and isinstance(node.slice.value, int) and -len(base[1]) <= node.slice.value < len(base[1]):
                return base[1][node.slice.value]
            return _elem(base)
        if isinstance(node, (ast.Tuple, ast.List)):
            if any(isinstance(e, ast.Starred) for e in node.elts):
                out = False
                for e in node.elts:
                    out = _join(out, _elem(self.shape(e.value)) if isinstance(e, ast.Starred) else self.shape(e))
                return _bag(out)
            elts = tuple(self.shape(e) for e in node.elts)
            return (_SEQ, elts) if any(_any(e) for e in elts) else False
        if isinstance(node, ast.Set):
            out = False
            for e in node.elts:
                out = _join(out, self.shape(e))
            return _bag(out)
        if isinstance(node, ast.Dict):
            out = False
            for k, v in zip(node.keys, node.values):
                out = _join(out, self.shape(k) if k is not None else False)
                out = _join(out, self.shape(v) if k is not None else _elem(self.shape(v)))
            return _bag(out)
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp)):
            return _bag(self.shape(node.elt))
        if isinstance(node, ast.DictComp):
            return _bag(_join(self.shape(node.key), self.shape(node.value)))
        if isinstance(node, ast.IfExp):
            return _join(self.shape(node.body), self.shape(node.orelse))
        if isinstance(node, ast.BoolOp):
            out = False
            for v in node.values:
                out = _join(out, self.shape(v))
            return out
        if isinstance(node, (ast.NamedExpr, ast.Starred, ast.Await, ast.YieldFrom)):
            return self.shape(node.value)
        if isinstance(node, ast.Lambda):
            return True if _any(self.shape(node.body)) else False
        if isinstance(node, ast.Call):
            return self.call_shape(node)
        return False

    @staticmethod
    def callee_name(func):
        return func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else None

    def defs_of(self, call):
        """The defs a call reaches: a resolvable name's own def (a class's ``__init__``), or every method of that
        name for an attribute call (the receiver's class is not resolved statically, so all of them)."""
        func = call.func
        if isinstance(func, ast.Name):
            for node in self.scopes.defs.get(self.key(func), ()):
                if isinstance(node, ast.ClassDef):
                    for item in node.body:
                        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == "__init__":
                            yield item, True
                else:
                    yield node, False
        elif isinstance(func, ast.Attribute):
            for key, nodes in self.scopes.defs.items():
                if key[1] == func.attr and self.scopes.kind.get(key[0]) == "class":
                    for node in nodes:
                        if not isinstance(node, ast.ClassDef):
                            yield node, True

    def call_shape(self, node):
        func = node.func
        name = self.callee_name(func)
        if name == "type" and len(node.args) >= 2:
            return True if _any(self.shape(node.args[1])) else False
        if name == "getattr" and isinstance(func, ast.Name) and node.args:
            attr = node.args[1] if len(node.args) >= 2 else None
            if isinstance(attr, ast.Constant) and attr.value in _DATA_DUNDERS:
                return False
            base = self.names.get(self.key(node.args[0]), False) if isinstance(node.args[0], ast.Name) \
                else self.shape(node.args[0])
            if base is True:
                return True
            if isinstance(attr, ast.Constant) and isinstance(attr.value, str):
                return self.attrs.get((self.receiver(node.args[0]), attr.value), False)
            return _elem(self.shape(node.args[0]))     # a computed attribute name: whatever the object carries
        if name in ("__import__", "import_module"):
            arg = node.args[0] if node.args else None
            return not (isinstance(arg, ast.Constant) and isinstance(arg.value, str)) \
                or arg.value.split(".")[0] in SSH_LIBRARIES
        if name in _DYNAMIC_ROOT_CALLS and isinstance(func, ast.Name):
            return True
        if name == "partial" and node.args and _any(self.shape(node.args[0])):
            return True
        out = False
        for fn, _method in self.defs_of(node):
            out = _join(out, self.returns.get(id(fn), False))
        if out:
            return out
        if self.shape(func) is True:
            return False                           # calling a class builds an instance, which taints nothing
        if isinstance(func, ast.Attribute) and name in _CONTAINER_OPS:
            recv = self.shape(func.value)
            if isinstance(recv, tuple):
                return _elem(recv)                 # a container operation hands back what the container holds
        return False

    # ------------------------------------------------------------------------------------------ binding ---
    def bind(self, target, shape, value=None):
        if isinstance(target, ast.Name):
            key = self.key(target)
            self.put(self.names, key, shape)
            if isinstance(value, ast.Name):        # an alias of an object carrying tainted attributes
                src = self.key(value)
                for (recv, attr), s in list(self.attrs.items()):
                    if recv == src:
                        self.put(self.attrs, (key, attr), s)
        elif isinstance(target, (ast.Tuple, ast.List)):
            starred = any(isinstance(e, ast.Starred) for e in target.elts)
            if not starred and isinstance(shape, tuple) and shape[0] == _SEQ and len(shape[1]) == len(target.elts):
                vals = value.elts if isinstance(value, (ast.Tuple, ast.List)) and len(value.elts) == len(
                    target.elts) else [None] * len(target.elts)
                for e, s, v in zip(target.elts, shape[1], vals):
                    self.bind(e, s, v)
            else:
                for e in target.elts:
                    self.bind(e, _bag(_elem(shape)) if isinstance(e, ast.Starred) else _elem(shape))
        elif isinstance(target, ast.Starred):
            self.bind(target.value, shape)
        elif isinstance(target, ast.Attribute):
            self.put(self.attrs, (self.receiver(target.value), target.attr), shape)
        elif isinstance(target, ast.Subscript):
            root = target.value                    # storing into a container taints the container
            if isinstance(root, ast.Name):
                self.put(self.names, self.key(root), _bag(shape))
            elif isinstance(root, ast.Attribute):
                self.put(self.attrs, (self.receiver(root.value), root.attr), _bag(shape))

    def bind_params(self, fn, call, skip_self):
        scope = self.scopes.scope_of.get(id(fn.body[0] if isinstance(fn.body, list) else fn.body), None)
        args = fn.args
        params = [a.arg for a in args.posonlyargs + args.args]
        if skip_self and params:
            params = params[1:]

        def put(param, shape):
            self.put(self.names, (scope, param), shape)

        for i, a in enumerate(call.args):
            if isinstance(a, ast.Starred):
                for q in params[i:]:
                    put(q, _elem(self.shape(a.value)))
                if args.vararg is not None:
                    put(args.vararg.arg, _bag(_elem(self.shape(a.value))))
                break
            if i < len(params):
                put(params[i], self.shape(a))
            elif args.vararg is not None:
                put(args.vararg.arg, _bag(self.shape(a)))
        named = set(params) | {a.arg for a in args.kwonlyargs}
        for kw in call.keywords:
            if kw.arg is None:
                for q in named:
                    put(q, _elem(self.shape(kw.value)))
                if args.kwarg is not None:
                    put(args.kwarg.arg, self.shape(kw.value))
            elif kw.arg in named:
                put(kw.arg, self.shape(kw.value))
            elif args.kwarg is not None:
                put(args.kwarg.arg, _bag(self.shape(kw.value)))

    def step(self, tree):
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                if any(_any(self.shape(b)) for b in list(node.bases) + [k.value for k in node.keywords]):
                    self.put(self.names, self.scopes.resolve_name(node.name, self.scopes.scope_of.get(
                        id(node), "<module>")), True)
            elif isinstance(node, ast.Assign):
                s = self.shape(node.value)
                for t in node.targets:
                    self.bind(t, s, node.value)
            elif isinstance(node, (ast.AnnAssign, ast.AugAssign)) and node.value is not None:
                self.bind(node.target, self.shape(node.value), node.value)
            elif isinstance(node, ast.NamedExpr):
                self.bind(node.target, self.shape(node.value), node.value)
            elif isinstance(node, (ast.For, ast.AsyncFor, ast.comprehension)):
                self.bind(node.target, _elem(self.shape(node.iter)))
            elif isinstance(node, (ast.With, ast.AsyncWith)):
                for item in node.items:
                    if item.optional_vars is not None:
                        self.bind(item.optional_vars, self.shape(item.context_expr))
            elif isinstance(node, _FUNCS):
                args = node.args
                positional = args.posonlyargs + args.args
                inner = self.scopes.scope_of.get(id(node.body[0] if isinstance(node.body, list) else node.body))
                for a, d in zip(positional[len(positional) - len(args.defaults):], args.defaults):
                    self.put(self.names, (inner, a.arg), self.shape(d))
                for a, d in zip(args.kwonlyargs, args.kw_defaults):
                    if d is not None:
                        self.put(self.names, (inner, a.arg), self.shape(d))
                if not isinstance(node, ast.Lambda):
                    out = False
                    stack = list(node.body)
                    while stack:
                        r = stack.pop()
                        if isinstance(r, (*_FUNCS, ast.ClassDef)):
                            continue                 # a nested def's returns are its own
                        if isinstance(r, ast.Return) and r.value is not None:
                            out = _join(out, self.shape(r.value))
                        elif isinstance(r, (ast.Yield, ast.YieldFrom)) and r.value is not None:
                            out = _join(out, _bag(self.shape(r.value)))
                        stack.extend(ast.iter_child_nodes(r))
                    self.put(self.returns, id(node), out)
            elif isinstance(node, ast.Call):
                for fn, skip_self in self.defs_of(node):
                    self.bind_params(fn, node, skip_self)


def qualified_owners(tree):
    """id(node) -> the qualified name of its innermost enclosing function ('<module>' at module level)."""
    owners = {}

    def visit(node, qual, in_function):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                inner = f"{qual}.{child.name}" if qual else child.name
                owners[id(child)] = qual if in_function else (qual or "<module>")
                visit(child, inner, in_function or not isinstance(child, ast.ClassDef))
            else:
                owners[id(child)] = qual if in_function else "<module>"
                visit(child, qual, in_function)

    visit(tree, "", False)
    return owners


def connection_constructor_calls(tree):
    """``(constructs, hands_over, tainted, factories)`` over the module `tree`: ``{qualified owner: sorted callee
    sources}`` for every call that constructs through a connection-capable callee (and every ``exec`` / ``eval`` /
    ``compile``), the same for every call a connection-capable value is handed to as an argument (the readers and the
    container operations the shape model follows excepted), the set of tainted binding keys ``(scope, name)``, and the
    names of the defs that return a tainted value. The taint is a fixpoint over the whole module (see the T8 test)."""
    env = _Env(tree)
    for _ in range(64):
        env.changed = False
        env.step(tree)
        if not env.changed:
            break
    else:
        raise AssertionError("the taint fixpoint did not converge")
    owners = qualified_owners(tree)
    found, passes = {}, {}
    for node in ast.walk(tree):
        owner = owners.get(id(node), "<module>")
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            for dec in node.decorator_list:
                if env.shape(dec.func if isinstance(dec, ast.Call) else dec) is True:
                    found.setdefault(owner, []).append("@" + ast.unparse(dec))
        if not isinstance(node, ast.Call):
            continue
        name = env.callee_name(node.func)
        if isinstance(node.func, ast.Name) and name in _DYNAMIC_CODE_CALLS:
            found.setdefault(owner, []).append(name)
            continue
        if env.shape(node.func) is True and not (isinstance(node.func, ast.Name) and name in _READERS):
            found.setdefault(owner, []).append(ast.unparse(node.func))
        if isinstance(node.func, ast.Name) and name in _READERS:
            continue
        if isinstance(node.func, ast.Attribute) and name in _CONTAINER_OPS and isinstance(
                env.shape(node.func.value), tuple):
            continue
        if any(_any(env.shape(a)) for a in node.args) or any(_any(env.shape(k.value)) for k in node.keywords):
            passes.setdefault(owner, []).append(ast.unparse(node.func))
    factories = {n.name for n in ast.walk(tree)
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and env.returns.get(id(n))}
    return ({o: sorted(c) for o, c in found.items()}, {o: sorted(c) for o, c in passes.items()},
            {key for key, shape in env.names.items() if _any(shape)}, factories)


def engine_tree():
    return ast.parse(ENGINE.read_text(encoding="utf-8"))


#: The callee spelling the scan keys a call by (a name, or an attribute's last segment).
callee_name = _Env.callee_name


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
