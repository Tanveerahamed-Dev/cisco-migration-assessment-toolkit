"""Meta-guard: no test in this repo may be vacuous in one of the UNAMBIGUOUS ways.

The whole-repo review (2026-07-28, docs/review-findings-2026-07-28.md) found "a test that passes
without proving anything" as a recurring class, and the repo's history is full of it: a release gate
skipped behind an env var nothing ever set, a roster pin that a wildcard walked straight through, a
Stop hook verified only by grepping its own source. Individually each was caught by reading. This
catches the mechanical shapes so the NEXT one cannot be introduced quietly.

Scope is deliberately narrow. It asserts only the three shapes that have **no legitimate use** in
this suite, verified against all 205 test files / 2,772 test functions at the time of writing:

  1. an UNCONDITIONAL module-level skip (``pytestmark = pytest.mark.skip(...)``) — it silently
     un-gates every test in the file, and `collect_ignore_glob`/`-q` make that invisible in a run;
  2. ``@pytest.mark.parametrize`` with an EMPTY argument list — the test body never executes;
  3. an ``assert`` inside a ``try`` whose handler is a bare ``pass``/``continue`` — the assertion
     cannot fail.

Deliberately NOT asserted: "the function body contains an assert". ~25 tests here legitimately use
the must-not-raise idiom (``_dt.date.fromisoformat(x)``, ``render(res).encode("cp1252")``,
``_assert_redaction_phases_ran(...)  # must not raise``) or delegate to a shared ``_case`` helper
that asserts internally. A rule that flagged those would need an allowlist, and an allowlist rots
into exactly the kind of unexamined green this file exists to prevent.

Conditional skips (``skipif``) are also fine and are NOT flagged: this suite legitimately skips the
bash-driven hook tests and the node-driven explorer parity gate where those tools are absent. What
matters is that the condition is real — and `tests/test_ci_gates.py` separately pins that the webapp
suite ANNOUNCES it when it un-collects itself.
"""
import ast
import configparser
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _testpaths():
    """The roots pytest itself collects, read from pytest.ini — so this guard and the gate always
    scan the same tree."""
    ini = configparser.ConfigParser()
    ini.read(os.path.join(ROOT, "pytest.ini"))
    paths = ini["pytest"]["testpaths"].split()
    assert paths, "pytest.ini declares no testpaths"
    return paths


def _test_files():
    """Walk the FILESYSTEM, not `git ls-files`.

    Using git here was a real bug in an earlier cut of this file, and it made the guard vacuous in
    the one case that matters: a newly written test file is UNTRACKED, so `git ls-files` cannot see
    it, and all three assertions below passed over planted violations. Caught by planting each shape
    and observing the guard stay green. pytest collects from the filesystem; so does this."""
    out = []
    for root in _testpaths():
        for dirpath, dirnames, filenames in os.walk(os.path.join(ROOT, root)):
            dirnames[:] = [d for d in dirnames if d not in ("__pycache__", ".pytest_cache")]
            for name in filenames:
                if name.startswith("test_") and name.endswith(".py"):
                    out.append(os.path.relpath(os.path.join(dirpath, name), ROOT)
                               .replace(os.sep, "/"))
    return sorted(out)


def _parsed():
    for rel in _test_files():
        path = os.path.join(ROOT, rel)
        try:
            with open(path, encoding="utf-8") as fh:
                yield rel, ast.parse(fh.read())
        except (OSError, SyntaxError) as e:          # a test file that will not parse is itself red
            raise AssertionError(f"{rel} does not parse: {e}") from e


def _is_unconditional_skip(node):
    """`pytest.mark.skip(...)` or a bare `pytest.mark.skip` — but NOT `skipif`, which carries a
    real condition and is a legitimate, disclosed abstention."""
    func = node.func if isinstance(node, ast.Call) else node
    name = ""
    while isinstance(func, ast.Attribute):
        name = func.attr if not name else f"{func.attr}.{name}"
        func = func.value
    return name.split(".")[-1] == "skip"


def test_no_test_file_is_skipped_at_module_level():
    """An unconditional module-level skip removes every test in the file from the gate while the
    file still sits in the suite looking collected — and with `-q` the run is visually identical to
    a full green one. If a file genuinely cannot run, it needs a `skipif` naming the condition."""
    offenders = []
    for rel, tree in _parsed():
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            if not any(isinstance(t, ast.Name) and t.id == "pytestmark" for t in node.targets):
                continue
            marks = node.value.elts if isinstance(node.value, (ast.List, ast.Tuple)) else [node.value]
            if any(_is_unconditional_skip(m) for m in marks):
                offenders.append(f"{rel}:{node.lineno}")
    assert not offenders, (
        "test file(s) skipped unconditionally at module level — every test in them is silently "
        f"outside the gate: {offenders}. Use skipif with a real condition, or delete the file.")


def test_no_parametrize_has_an_empty_argument_list():
    """`@pytest.mark.parametrize("x", [])` collects zero cases, so the body never runs while the
    test still reports as present."""
    offenders = []
    for rel, tree in _parsed():
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for deco in fn.decorator_list:
                if not isinstance(deco, ast.Call) or "parametrize" not in ast.dump(deco.func):
                    continue
                if any(isinstance(a, (ast.List, ast.Tuple)) and not a.elts for a in deco.args):
                    offenders.append(f"{rel}:{fn.lineno} {fn.name}")
    assert not offenders, f"parametrize with an empty argument list (body never runs): {offenders}"


def test_no_assertion_is_inside_a_swallowing_try():
    """An `assert` whose enclosing `except` is a bare `pass`/`continue` cannot fail — the test
    reports green whatever the code does."""
    offenders = []
    for rel, tree in _parsed():
        for node in ast.walk(tree):
            if not isinstance(node, ast.Try):
                continue
            body = ast.Module(body=node.body, type_ignores=[])
            if not any(isinstance(x, ast.Assert) for x in ast.walk(body)):
                continue
            for handler in node.handlers:
                if all(isinstance(s, (ast.Pass, ast.Continue)) for s in handler.body):
                    offenders.append(f"{rel}:{node.lineno}")
                    break
    assert not offenders, (
        f"assert(s) inside a try whose handler swallows — the assertion cannot fail: {offenders}")


def test_the_guard_itself_is_not_vacuous():
    """The scan must actually reach the suite: if `git ls-files` returns nothing (a bad cwd, a
    non-repo checkout) all three tests above pass over an empty set. Pin the population."""
    files = _test_files()
    assert len(files) > 150, (
        f"only {len(files)} test files discovered — the meta-guard is scanning an empty or partial "
        f"tree, so its three assertions above prove nothing")
    n_tests = sum(1 for _rel, tree in _parsed() for fn in ast.walk(tree)
                  if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))
                  and fn.name.startswith("test"))
    assert n_tests > 2000, f"only {n_tests} test functions discovered — population looks wrong"
