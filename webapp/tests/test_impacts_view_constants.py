"""W50: the SPA words the engine owner's failure-impact reading with the owner's own phrases, and never shows raw rows.

``components/ComparisonDecision.tsx`` renders an execution receipt's (or trend pair's) failure-impact rows ONLY from
the display-only ``impacts_view`` that AssessHub computes live from the bound evidence. The view carries stable tokens
(reason codes, verdicts, states); the SPA turns codes and verdicts into words through two closed tables it hand-copies
from ``cisco_toolkit/impact_assessability.py`` (``CODE_PHRASES``, ``VERDICT_LABELS``). A code the owner adds, renames
or rewords would otherwise be shown as "unrecognised" or in stale words, so each table is held EXACTLY equal (keys,
values and order) to its owner here, the same pattern as the W47 constants guard. The owner's state words
(``STATE_WORD``) travel inside the view (``state_words``) instead: a TS literal naming ``not_collected`` and
``analysis_unavailable`` would read as a hand list of the protocol receipt's vocabulary
(``tests/test_protocol_assessability.py``), and the SPA then needs no copy of them at all. A last check keeps every SPA
source from reading the receipt's raw ``rehearsal.impacts`` rows, which are evidence, not a presentation.

Written for the hosted runners (owner GitHub-only rule); not run locally.
"""
from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "webapp"))

from backend import engine  # noqa: E402
from cisco_toolkit import impact_assessability as ia  # noqa: E402

_SRC = _REPO / "webapp" / "frontend" / "src"
COMPARISON_DECISION_TSX = _SRC / "components" / "ComparisonDecision.tsx"
#: One module-level constant: ``const NAME[: type] = <value>;``. The value runs to the first ``;`` that ends a line,
#: so a multi-line object literal is read whole.
_TS_CONST = r"^(?:export\s+)?const\s+{name}\b(?:\s*:[^=\n]+)?\s*=\s*(?P<value>.+?);\s*$"
_TS_STRING = r'"((?:[^"\\\n]|\\.)*)"'
_TS_PAIR = re.compile(_TS_STRING + r"\s*:\s*" + _TS_STRING)


def _ts_const(source: str, name: str) -> str:
    found = re.findall(_TS_CONST.format(name=re.escape(name)), source, re.M | re.S)
    assert len(found) == 1, f"ComparisonDecision.tsx must declare `{name}` exactly once, found {len(found)}"
    return found[0].strip()


def _ts_string_table(source: str, name: str) -> list:
    """The constant as an ordered list of ``(key, value)`` string pairs. Fails unless its value is a plain object
    literal of double-quoted string keys and string values: a spread, a computed key, a reference or a template would
    hide what the SPA actually holds."""
    value = _ts_const(source, name)
    assert value.startswith("{") and value.endswith("}"), f"{name} is not an object literal: {value!r}"
    body = value[1:-1]
    residue = _TS_PAIR.sub("", body)
    assert re.fullmatch(r"[\s,]*", residue), f"{name} holds something other than string pairs: {residue!r}"
    pairs = [(json.loads(f'"{key}"'), json.loads(f'"{text}"')) for key, text in _TS_PAIR.findall(body)]
    keys = [key for key, _text in pairs]
    assert len(keys) == len(set(keys)), f"{name} repeats a key: {keys}"
    return pairs


@pytest.mark.parametrize("name, owner", [
    ("IMPACT_REASON_PHRASES", ia.CODE_PHRASES),
    ("IMPACT_VERDICT_LABELS", ia.VERDICT_LABELS),
])
def test_the_spa_phrase_tables_equal_the_owner_in_order(name, owner):
    source = COMPARISON_DECISION_TSX.read_text(encoding="utf-8")
    assert _ts_string_table(source, name) == list(owner.items())


def test_every_token_the_view_carries_has_the_owners_word():
    """Every token the view can carry has a word: the verdicts and every reason code from the pinned SPA tables, the
    three withheld states from the view itself, which publishes the owner's STATE_WORD verbatim."""
    assert tuple(ia.VERDICT_LABELS) == ia.VERDICTS
    assert set(ia.STATE_WORD) == {ia.ANALYSIS_UNAVAILABLE, ia.UNVERIFIED, ia.NOT_COLLECTED}
    view = engine.rehearsal_impacts_view({"failure_impact": []}, source_sha256="sha256:" + "0" * 64)
    assert view["state_words"] == dict(ia.STATE_WORD)
    assert engine.IMPACTS_VIEW_CELLS == (*ia.IMPACT_MEASURES, "detail")
    source = COMPARISON_DECISION_TSX.read_text(encoding="utf-8")
    labels = re.findall(r'\[\s*"(\w+)"\s*,\s*"[^"]*"\s*\]', _ts_const(source, "IMPACT_CELL_LABELS"))
    assert sorted(labels) == sorted(ia.IMPACT_MEASURES), labels
    # the SPA keeps no copy of the state words: they come from the view
    assert "IMPACT_STATE_WORDS" not in source and "state_words" in source


def test_the_spa_reads_exactly_the_owners_view_schema_and_cell_kinds():
    """W50 round 4 (P3-4): the SPA renders a view only under the schema the engine publishes, and words only the cell
    kinds the owner publishes (``impact_assessability.CELL_KINDS``); any other schema or kind is shown as
    unrecognised, never guessed at. Both SPA constants are held equal to their owners here."""
    source = COMPARISON_DECISION_TSX.read_text(encoding="utf-8")
    assert json.loads(_ts_const(source, "IMPACTS_VIEW_SCHEMA")) == engine.REHEARSAL_IMPACTS_VIEW_SCHEMA
    assert json.loads(_ts_const(source, "IMPACT_CELL_KINDS")) == list(ia.CELL_KINDS)
    view = engine.rehearsal_impacts_view({"failure_impact": [{"host": "x"}]}, source_sha256="sha256:" + "0" * 64)
    assert view["schema"] == engine.REHEARSAL_IMPACTS_VIEW_SCHEMA
    assert {cell["kind"] for row in view["rows"] for cell in row["cells"].values()} <= set(ia.CELL_KINDS)
    assert {"unranked", "unreadable"} <= set(view)


def test_the_spa_table_reader_is_not_vacuous():
    """The reader must see a drift, a spread, a reference and a duplicate, or its equality proves nothing."""
    drifted = 'const IMPACT_VERDICT_LABELS: Readonly<Record<string, string>> = {\n  "published": "measured",\n};\n'
    assert _ts_string_table(drifted, "IMPACT_VERDICT_LABELS") == [("published", "measured")]
    assert _ts_string_table(drifted, "IMPACT_VERDICT_LABELS") != list(ia.VERDICT_LABELS.items())
    with pytest.raises(AssertionError, match="something other than string pairs"):
        _ts_string_table('const X = {\n  ...OTHER,\n  "a": "b",\n};\n', "X")
    with pytest.raises(AssertionError, match="something other than string pairs"):
        _ts_string_table('const X = {\n  "a": PHRASE,\n};\n', "X")
    with pytest.raises(AssertionError, match="repeats a key"):
        _ts_string_table('const X = {\n  "a": "b",\n  "a": "c",\n};\n', "X")
    with pytest.raises(AssertionError, match="exactly once"):
        _ts_const('const X = {};\nconst X = {};\n', "X")


_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_LINE_COMMENT = re.compile(r"(^|[\s;{}(),])//[^\n]*", re.M)
#: A read of the receipt's raw evidence rows: ``.impacts`` (``rehearsal.impacts``, ``rehearsal?.impacts``) or
#: ``["impacts"]``. ``impacts_view`` does not match (``\b`` stops at the underscore).
_RAW_ROWS_READ = re.compile(r"\.impacts\b|\[\s*[\"']impacts[\"']\s*\]")


def _code(text: str) -> str:
    return _LINE_COMMENT.sub(r"\1", _BLOCK_COMMENT.sub("", text))


def test_no_spa_source_presents_the_receipts_raw_failure_impact_rows():
    """``operator_evidence.rehearsal.impacts`` is raw evidence (a lower bound's count as written, a held zero as a
    zero). The SPA may count it but never read its rows: every presentation goes through ``impacts_view``."""
    offenders = []
    for path in sorted(_SRC.rglob("*.ts*")):
        if path.suffix not in {".ts", ".tsx"} or ".test." in path.name or "test" in path.relative_to(_SRC).parts:
            continue
        for number, line in enumerate(_code(path.read_text(encoding="utf-8")).splitlines(), start=1):
            if _RAW_ROWS_READ.search(line):
                offenders.append(f"{path.relative_to(_REPO).as_posix()}:{number}: {line.strip()}")
    assert not offenders, offenders
    # non-vacuity: the scan sees the pre-W50 raw read, ignores comments and does not mistake impacts_view
    assert _RAW_ROWS_READ.search(_code("const rows = (rehearsal?.impacts || []).slice(0, 8);"))
    assert _RAW_ROWS_READ.search(_code('const rows = rehearsal["impacts"];'))
    assert not _RAW_ROWS_READ.search(_code("// operator_evidence.rehearsal.impacts is evidence"))
    assert not _RAW_ROWS_READ.search(_code("impactsView={latestStored?.impacts_view}"))


# ---------------------------------------------------------------------------------------------------------------
# The same rule for Python (W50 round 4, P3-5): no engine, AssessHub or Atlas code reads the bound raw rows to present
# them. ``impacts`` is the key ``cutover_operator_evidence/1`` binds them under (``rehearsal.impacts``); today no
# production code outside the frozen binder's payload names it at all, so the guard is a closed allowlist.
# ---------------------------------------------------------------------------------------------------------------
_RAW_ROWS_KEY = "impacts"
_PY_ROOTS = ("cisco_toolkit", "webapp/backend", "portable")
_PIPELINE = "COLLECT_PARSE_V3_23_0.py"
#: The only units that may read the bound raw rows by their key: the frozen evidence binder's module unit that WRITES
#: them, and the two storage verifiers, which recompute and compare a stored or incoming receipt whole and never
#: present a row. Keyed by (repository path, unit) where a unit is a top-level function or ``Class.method``.
_RAW_ROWS_ADMITTED = frozenset({
    ("cisco_toolkit/protocol_assurance.py", "_rehearsal_impact_evidence_v1"),
    ("webapp/backend/storage.py", "Store._execution_receipt_authority_locked"),
    ("webapp/backend/storage.py", "Store.append_execution_comparison_if_unchanged"),
})


def _python_units(tree):
    """node -> its unit: the top-level function or ``Class.method`` that holds it (``<module>`` otherwise). A nested
    function belongs to the unit that defines it."""
    owner = {}

    def visit(node, unit):
        for child in ast.iter_child_nodes(node):
            inner = unit
            if unit == "<module>" and isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                inner = child.name
            elif unit == "<module>" and isinstance(child, ast.ClassDef):
                inner = f"{child.name}."
            elif unit.endswith(".") and isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                inner = unit + child.name
            owner[child] = inner
            visit(child, inner)
    visit(tree, "<module>")
    return owner


def _raw_rows_reads(tree):
    """``(line, unit)`` of every READ of the ``impacts`` key: a subscript load (``x["impacts"]``), the key as a call
    argument (``x.get("impacts")``, ``getattr(x, "impacts")``, ``operator.itemgetter("impacts")``,
    ``x.pop("impacts")``), an attribute load (``x.impacts``) or a ``match`` mapping-pattern key. Building
    ``{"impacts": rows}`` and every other key that merely contains the word (``n_impacts_total``) are not reads."""
    owner = _python_units(tree)
    found = []
    for node in ast.walk(tree):
        hit = False
        if isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Load):
            hit = isinstance(node.slice, ast.Constant) and node.slice.value == _RAW_ROWS_KEY
        elif isinstance(node, ast.Call):
            hit = any(isinstance(arg, ast.Constant) and arg.value == _RAW_ROWS_KEY
                      for arg in list(node.args) + [keyword.value for keyword in node.keywords])
        elif isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
            hit = node.attr == _RAW_ROWS_KEY
        elif isinstance(node, ast.MatchMapping):
            hit = any(isinstance(key, ast.Constant) and key.value == _RAW_ROWS_KEY for key in node.keys)
        if hit:
            found.append((node.lineno, owner.get(node, "<module>")))
    return found


def _python_sources():
    for base in _PY_ROOTS:
        for path in sorted((_REPO / base).rglob("*.py")):
            if "__pycache__" not in path.parts:
                yield path.relative_to(_REPO).as_posix(), path
    if (_REPO / _PIPELINE).exists():
        yield _PIPELINE, _REPO / _PIPELINE


def test_no_python_source_presents_the_receipts_raw_failure_impact_rows():
    """Every read of the bound raw rows' key in the engine, AssessHub and Atlas sources sits in an admitted unit: the
    frozen binder or a receipt verifier. A presenter that reads ``rehearsal.impacts`` (a PIR writer, a workbook diff
    tab, an API decorator) fails here; it must present the owner's ``impacts_view`` instead."""
    offenders, units = [], set()
    for rel, path in _python_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        units.update((rel, unit) for unit in set(_python_units(tree).values()))
        for line, unit in _raw_rows_reads(tree):
            if (rel, unit) not in _RAW_ROWS_ADMITTED:
                offenders.append(f"{rel}:{line} in {unit}")
    assert not offenders, ("these read the receipt's raw failure-impact rows (rehearsal.impacts), which are evidence, "
                           f"not a presentation; read webapp.backend.engine.rehearsal_impacts_view: {offenders}")
    # the allowlist names live units, so it cannot outlive what it admits
    assert _RAW_ROWS_ADMITTED <= units, sorted(_RAW_ROWS_ADMITTED - units)


def test_the_python_raw_rows_scan_is_not_vacuous():
    """Each read shape is seen, in the unit that holds it; a write, a longer key and a docstring are not reads."""
    source = (
        "import operator\n"
        "def a(c):\n    return c['operator_evidence']['rehearsal']['impacts']\n"
        "def b(r):\n    return r.get('impacts') or []\n"
        "def c(r):\n    return getattr(r, 'impacts')\n"
        "def d(r):\n    return operator.itemgetter('impacts')(r)\n"
        "class W:\n    def e(self, r):\n        def inner():\n            return r.impacts\n        return inner()\n"
        "def f(r):\n    match r:\n        case {'impacts': rows}:\n            return rows\n"
        "def ok(rows):\n    '''reads rehearsal.impacts? no'''\n"
        "    return {'impacts': rows, 'n_impacts_total': len(rows)}, rows\n"
    )
    assert sorted(_raw_rows_reads(ast.parse(source))) == [
        (3, "a"), (5, "b"), (7, "c"), (9, "d"), (13, "W.e"), (17, "f")]
