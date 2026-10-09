"""W48: every consumer that presents a failure-impact value, rank or severity reads it through the engine owner.

``cisco_toolkit/impact_assessability.py`` (W33, with W32's blind-link rule) is the one owner of whether a stored
``failure_impact`` row is a measurement: ``published``, ``lower_bound`` (the worst band and each positive count are
floors; a band below the worst and a zero are not measurements), ``not_assessed`` (a hold: none of the row's values
is a measurement) or ``ambiguous``. W33 moved the projection and the workbook, design, deck, RES-4, dossier and
explorer onto it. W48 moves the rest of the class: the MOP's per-wave blast radius and rollback trigger, the
runbook's §10 Risk Register, the operations handbook's §2.1 keystones, the MCP ``failure_impact`` tool and the
AssessHub dossier recompute.

Two things are pinned here:

1. **A structural guard** (part 1). The class is defined by what a function READS, never by a hand-kept list of
   consumers: every function (or method, or module-level table) under ``cisco_toolkit/``, ``webapp/backend/`` and
   ``COLLECT_PARSE_V3_23_0.py`` that reads the stored ``failure_impact`` section must reach the owner through its
   own code or its call closure (same-module calls, imported project functions, ``module.function`` attributes,
   ``self.method`` and module-level dispatch tables). The owner module itself, the projection (which imports the
   owner) and the AssessHub surfaces (which reach it through ``engine.failure_impact_projection``) are therefore
   admitted by that property, not by name. The only named entries are a RATCHET of the consumers W48 stopped on
   because their output is persisted (see each entry): a new raw reader fails, and fixing a ratchet entry fails
   until the entry and its strict ``xfail`` below are deleted. W50 removed ``protocol_assurance`` from it by
   versioning the receipt contract: new comparisons carry ``cutover_operator_evidence/2`` (owner-valued rows), and
   the raw ``/1`` row copy survives only as ``_rehearsal_impacts_v1_legacy``, which receives the rows and is selected
   solely by a stored receipt that declares ``/1`` (pinned in part 2, since this guard is per function).

   Granularity is the function: a function that reaches the owner for one value could still print another raw
   value. The guard closes the class the W33/W48 sites belonged to -- a consumer with no route to the owner at
   all -- and the behavioural tests in part 2 pin what each moved consumer prints.

2. **Behaviour on the committed sample** (part 2). On the regenerated sample the owner bounds core1 (one
   inter-switch link with no trunk/STP evidence, W32). Each moved consumer must present core1 as the lower bound it
   is, and a held row (core1 with its ``off_scan_gw_vlans`` marker removed: a row older than the marker) as not
   assessed. Every expectation is read from the owner (``table_value`` / ``ranked_value`` / ``ranking_floor`` /
   ``disclose``), never cached from the sample. Each test fails on the pre-W48 code, which printed core1's raw 45.

No test here runs a pipeline. Written for the hosted runners (owner GitHub-only rule); not run locally.
"""
from __future__ import annotations

import ast
import copy
import functools
import io
import json
import os
import pathlib
import re
import tokenize

import pytest

from cisco_toolkit import impact_assessability as ia
from cisco_toolkit import mcp_server

ROOT = pathlib.Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "webapp" / "sample_data" / "sample_fleet.snapshot.json"

# ---------------------------------------------------------------------------------------------------------------
# part 1: the structural guard
# ---------------------------------------------------------------------------------------------------------------
SECTION = "failure_impact"
OWNER = "cisco_toolkit.impact_assessability"
#: (directory, dotted package) roots whose Python modules are scanned, plus the pipeline entry module.
_PACKAGE_ROOTS = (("cisco_toolkit", "cisco_toolkit"), (os.path.join("webapp", "backend"), "webapp.backend"))
_PIPELINE = "COLLECT_PARSE_V3_23_0.py"

#: Raw readers W48 STOPPED on, each because changing what it presents changes persisted output; routed to the
#: supervisor for a hosted regeneration (docs/w48-impact-consumers-validation-2026-10-09.md). Keyed by
#: (module, function). Each has a strict xfail in part 2. Delete the entry when its consumer reads the owner.
_RAW_RATCHET = {
    ("cisco_toolkit.design_advisor", "_signals"): (
        "nobackup_high counts raw High rows with a raw zero backup, so a lower-bound or held row's withheld zero "
        "is counted as a measured no-backup device. Its text and count are stored in the snapshot's "
        "design_blueprint (decisions[topology-triangles-not-squares-rings].evidence.summary and "
        "tradeoff_scorecard[availability].evidence), so the fix needs a hosted sample regeneration."),
}


def _module_map(root):
    """dotted module name -> path relative to `root` (POSIX separators)."""
    out = {}
    for base, package in _PACKAGE_ROOTS:
        top = os.path.join(root, base)
        for dirpath, dirnames, filenames in os.walk(top):
            dirnames[:] = sorted(d for d in dirnames if d != "__pycache__")
            for name in sorted(filenames):
                if not name.endswith(".py"):
                    continue
                rel_to_top = os.path.relpath(os.path.join(dirpath, name), top).replace(os.sep, "/")
                dotted = package + "." + rel_to_top[:-3].replace("/", ".")
                if dotted.endswith(".__init__"):
                    dotted = dotted[: -len(".__init__")]
                out[dotted] = os.path.relpath(os.path.join(dirpath, name), root).replace(os.sep, "/")
    if os.path.exists(os.path.join(root, _PIPELINE)):
        out[_PIPELINE[:-3]] = _PIPELINE
    return out


def _resolve_from(module, rel, node):
    """The dotted module an ``ImportFrom`` names, relative imports resolved against `module`."""
    if not node.level:
        return node.module or ""
    package = module if rel.endswith("__init__.py") else module.rpartition(".")[0]
    parts = package.split(".")
    if node.level > 1:
        parts = parts[: len(parts) - (node.level - 1)]
    return ".".join(parts + ([node.module] if node.module else []))


def _aliases(module, rel, tree, modules):
    """Every local name an import binds to a project module or to a name inside one, wherever the import sits
    (lazy imports included): name -> ("module", dotted) | ("name", dotted, attribute)."""
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname and alias.name in modules:
                    out[alias.asname] = ("module", alias.name)
        elif isinstance(node, ast.ImportFrom):
            source = _resolve_from(module, rel, node)
            for alias in node.names:
                local = alias.asname or alias.name
                full = f"{source}.{alias.name}" if source else alias.name
                if full in modules:
                    out[local] = ("module", full)
                elif source in modules:
                    out[local] = ("name", source, alias.name)
    return out


def _units(tree):
    """(unit name, node, kind) for each top-level function, each method of a top-level class, and each module-level
    assignment to a plain name (a dispatch table such as mcp_server._PURE routes through it)."""
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node.name, node, "function"
        elif isinstance(node, ast.ClassDef):
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    yield f"{node.name}.{sub.name}", sub, "method"
        elif isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None:
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    yield target.id, node.value, "data"


def _section_reads(node, functions):
    """Lines where `node` reads the stored section: the section name as a call argument (``snap.get(...)``, a
    reader helper) or a subscript key, a ``.failure_impact`` attribute, or a ``failure_impact`` name that is not
    one of the module's own functions (the rows handed in as a parameter or a local). Docstrings, dict keys,
    comparisons and tuples of section names are not reads."""
    lines = []
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            if any(isinstance(a, ast.Constant) and a.value == SECTION
                   for a in list(sub.args) + [k.value for k in sub.keywords]):
                lines.append(sub.lineno)
        elif isinstance(sub, ast.Subscript) and isinstance(sub.ctx, ast.Load):
            if isinstance(sub.slice, ast.Constant) and sub.slice.value == SECTION:
                lines.append(sub.lineno)
        elif isinstance(sub, ast.Attribute) and sub.attr == SECTION and isinstance(sub.ctx, ast.Load):
            lines.append(sub.lineno)
        elif (isinstance(sub, ast.Name) and sub.id == SECTION and isinstance(sub.ctx, ast.Load)
              and SECTION not in functions):
            lines.append(sub.lineno)
    return sorted(set(lines))


@functools.lru_cache(maxsize=None)
def _scan(root):
    """``(readers, routed)``: every unit that reads the stored section (unit -> lines), and every unit that reaches
    the owner (it is the owner, names it, or calls something that does, to a fixpoint). Cached per root: the
    callers only read the result."""
    modules = _module_map(root)
    units, edges, direct, readers = {}, {}, set(), {}
    parsed = {}
    for module, rel in modules.items():
        with open(os.path.join(root, rel), encoding="utf-8") as fh:
            tree = ast.parse(fh.read(), filename=rel)
        parsed[module] = (rel, tree, _aliases(module, rel, tree, modules))
        for name, node, kind in _units(tree):
            units[(module, name)] = (node, kind)
    for module, (rel, tree, aliases) in parsed.items():
        own = {name for (m, name) in units if m == module}
        functions = {name for (m, name), (_n, kind) in units.items() if m == module and kind == "function"}
        for (m, name), (node, _kind) in units.items():
            if m != module:
                continue
            unit = (module, name)
            if module == OWNER:
                direct.add(unit)
            cls = name.split(".")[0] if "." in name else None
            out = set()
            for sub in ast.walk(node):
                if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load):
                    if sub.id in own:
                        out.add((module, sub.id))
                    bound = aliases.get(sub.id)
                    if bound and bound[0] == "name":
                        out.add((bound[1], bound[2]))
                        if bound[1] == OWNER:
                            direct.add(unit)
                    elif bound and bound[1] == OWNER:
                        direct.add(unit)
                elif isinstance(sub, ast.Attribute) and isinstance(sub.value, ast.Name):
                    bound = aliases.get(sub.value.id)
                    if bound and bound[0] == "module":
                        out.add((bound[1], sub.attr))
                        if bound[1] == OWNER:
                            direct.add(unit)
                    elif sub.value.id in ("self", "cls") and cls:
                        out.add((module, f"{cls}.{sub.attr}"))
                elif isinstance(sub, ast.ImportFrom):
                    source = _resolve_from(module, rel, sub)
                    if source == OWNER or any(f"{source}.{a.name}" == OWNER for a in sub.names):
                        direct.add(unit)
            edges[unit] = {e for e in out if e in units and e != unit}
            lines = _section_reads(node, functions)
            if lines:
                readers[unit] = lines
    routed = set(direct)
    changed = True
    while changed:
        changed = False
        for unit, targets in edges.items():
            if unit not in routed and targets & routed:
                routed.add(unit)
                changed = True
    return readers, routed


def _raw(root):
    readers, routed = _scan(root)
    return {unit: lines for unit, lines in readers.items() if unit not in routed}


def test_every_reader_of_the_stored_failure_impact_rows_reaches_the_owner():
    raw = _raw(str(ROOT))
    new = {f"{m}:{n}": lines for (m, n), lines in sorted(raw.items()) if (m, n) not in _RAW_RATCHET}
    assert not new, (
        "these functions read the stored failure_impact rows with no route to the engine owner "
        "(cisco_toolkit.impact_assessability). Read the rows through it (rows_with_verdicts / table_value / "
        "ranked_value / ranks / ranking_floor / disclose, or the projection) so a held row reads as not assessed "
        f"and a lower bound as a lower bound, never as an exact measurement: {new}")
    fixed = sorted(f"{m}:{n}" for (m, n) in _RAW_RATCHET if (m, n) not in raw)
    assert not fixed, ("these ratchet entries now reach the owner or no longer read the section: delete them from "
                       f"_RAW_RATCHET and remove their strict xfail below: {fixed}")


_SECTION_READ_TEXT = re.compile(r"""\.get\(\s*["']failure_impact["']|\[\s*["']failure_impact["']\s*\]""")


def _code_text(text):
    """The source with every comment and docstring blanked (a comment quoting ``snap.get("failure_impact")`` is
    not a read), positions kept."""
    lines = text.splitlines(keepends=True)

    def blank_line(r, lo=0, hi=None):
        body = lines[r - 1].rstrip("\r\n")
        hi = len(body) if hi is None else hi
        lines[r - 1] = body[:lo] + " " * (hi - lo) + body[hi:] + lines[r - 1][len(body):]

    for tok in tokenize.generate_tokens(io.StringIO(text).readline):
        if tok.type == tokenize.COMMENT:                 # tokenize columns are characters; a comment ends its line
            blank_line(tok.start[0], tok.start[1], tok.end[1])
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)):
                for r in range(first.lineno, first.end_lineno + 1):   # a docstring owns its lines
                    blank_line(r)
    return "".join(lines)


def test_the_ast_scan_sees_every_textual_read_of_the_section():
    """Non-vacuity on the real tree: every scanned module whose CODE (comments and docstrings blanked) reads the
    section by text (``.get(...)`` or a ``[...]`` key) holds at least one unit the AST scan calls a reader. A scanner
    that silently stopped seeing a read shape would leave this module out and fail here."""
    readers, _routed = _scan(str(ROOT))
    reading_modules = {module for module, _name in readers}
    missed = []
    for module, rel in _module_map(str(ROOT)).items():
        text = (ROOT / rel).read_text(encoding="utf-8")
        if (module not in reading_modules and _SECTION_READ_TEXT.search(text)
                and _SECTION_READ_TEXT.search(_code_text(text))):
            missed.append(rel)
    assert not missed, missed
    # the scan spans all three roots: the pipeline, the engine and AssessHub each read the section
    assert any(m == _PIPELINE[:-3] for m, _n in readers)
    assert any(m.startswith("cisco_toolkit.") for m, _n in readers)
    assert any(m.startswith("webapp.backend.") for m, _n in readers)


def _write(root, rel, text):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_the_guard_flags_a_raw_reader_and_admits_each_route_to_the_owner(tmp_path):
    """The guard is not decoration: on a synthetic tree it flags each raw read shape and admits each route."""
    _write(tmp_path, "cisco_toolkit/__init__.py", "")
    _write(tmp_path, "cisco_toolkit/impact_assessability.py",
           "def rows_with_verdicts(snap):\n    return [(r, None) for r in snap.get('failure_impact') or []]\n")
    _write(tmp_path, "cisco_toolkit/raw_get.py",
           "def render(snap):\n    return [r.get('stranded') for r in snap.get('failure_impact') or []]\n")
    _write(tmp_path, "cisco_toolkit/raw_key.py",
           "def render(snap):\n    return snap['failure_impact'][0]['stranded']\n")
    _write(tmp_path, "cisco_toolkit/raw_param.py",
           "def render(failure_impact):\n    return max(r['stranded'] for r in failure_impact)\n")
    _write(tmp_path, "cisco_toolkit/raw_attr.py",
           "class Writer:\n    def render(self, ctx):\n        return ctx.failure_impact\n")
    _write(tmp_path, "cisco_toolkit/routed_direct.py",
           "from cisco_toolkit import impact_assessability\n"
           "def render(snap):\n    rows = snap.get('failure_impact')\n"
           "    return impact_assessability.rows_with_verdicts(snap), rows\n")
    _write(tmp_path, "cisco_toolkit/routed_lazy.py",
           "def render(snap):\n    from cisco_toolkit.impact_assessability import rows_with_verdicts\n"
           "    return rows_with_verdicts(snap), snap['failure_impact']\n")
    _write(tmp_path, "cisco_toolkit/routed_transitive.py",
           "from . import routed_direct\n"
           "def _helper(snap):\n    return routed_direct.render(snap)\n"
           "def render(snap):\n    rows = snap.get('failure_impact')\n    return _helper(snap), rows\n")
    _write(tmp_path, "cisco_toolkit/routed_method.py",
           "from cisco_toolkit import impact_assessability as ia\n"
           "class Writer:\n    def _owner(self, snap):\n        return ia.rows_with_verdicts(snap)\n"
           "    def render(self, snap):\n        return self._owner(snap), snap['failure_impact']\n")
    _write(tmp_path, "cisco_toolkit/routed_table.py",
           "from cisco_toolkit import impact_assessability\n"
           "def failure_impact(snap):\n    return impact_assessability.rows_with_verdicts(snap)\n"
           "_PURE = {'failure_impact': failure_impact}\n"
           "def serve(snap):\n    return _PURE['failure_impact'](snap)\n")
    _write(tmp_path, "cisco_toolkit/not_a_read.py",
           "SECTIONS = ('failure_impact', 'devices')\n"
           "def name_only(name):\n    return name == 'failure_impact'\n"
           "def literal():\n    return {'failure_impact': []}\n")
    _write(tmp_path, "webapp/backend/__init__.py", "")
    _write(tmp_path, "webapp/backend/engine.py",
           "from cisco_toolkit import routed_direct as _rd\n"
           "def projection(snap):\n    return _rd.render(snap)\n")
    _write(tmp_path, "webapp/backend/view.py",
           "from . import engine\n"
           "def table(snap):\n    return engine.projection(snap), snap.get('failure_impact')\n"
           "def raw_table(snap):\n    return snap.get('failure_impact')\n")
    _write(tmp_path, _PIPELINE,
           "from cisco_toolkit import raw_param\n"
           "def main(failure_impact):\n    return raw_param.render(failure_impact)\n")
    readers, routed = _scan(str(tmp_path))
    raw = {f"{m}:{n}" for (m, n) in readers if (m, n) not in routed}
    assert raw == {"cisco_toolkit.raw_get:render", "cisco_toolkit.raw_key:render", "cisco_toolkit.raw_param:render",
                   "cisco_toolkit.raw_attr:Writer.render", "webapp.backend.view:raw_table",
                   "COLLECT_PARSE_V3_23_0:main"}, raw
    admitted = {f"{m}:{n}" for (m, n) in readers if (m, n) in routed}
    assert {"cisco_toolkit.routed_direct:render", "cisco_toolkit.routed_lazy:render",
            "cisco_toolkit.routed_transitive:render", "cisco_toolkit.routed_method:Writer.render",
            "cisco_toolkit.routed_table:serve", "webapp.backend.view:table",
            "cisco_toolkit.impact_assessability:rows_with_verdicts"} <= admitted, admitted
    assert not any(m == "cisco_toolkit.not_a_read" for m, _n in readers), readers


def test_every_ratchet_entry_is_still_a_raw_reader_with_a_stated_reason():
    raw = _raw(str(ROOT))
    for unit, reason in _RAW_RATCHET.items():
        assert unit in raw, unit
        assert len(reason) > 80, unit


# ---------------------------------------------------------------------------------------------------------------
# part 2: behaviour on the committed sample
# ---------------------------------------------------------------------------------------------------------------
_RISK_FIELDS = ("severity", "vlans_impacted", "stranded", "hard", "backup", "fhrp")   # runbook §10 column order
_KEYSTONE_FIELDS = ("severity", "stranded", "vlans_impacted")                         # ops §2.1 column order


@pytest.fixture(scope="module")
def sample():
    if not SAMPLE.exists():
        pytest.skip("sample_fleet.snapshot.json not present")
    return json.loads(SAMPLE.read_text(encoding="utf-8"))


def _core1(snap):
    """core1's stored row and the owner's verdict on it."""
    pairs = [(row, verdict) for row, verdict in ia.rows_with_verdicts(snap) if row.get("host") == "core1"]
    assert len(pairs) == 1, pairs
    return pairs[0]


@pytest.fixture(scope="module")
def bounded(sample):
    """The committed sample. Precondition, read from the owner: core1 is a lower bound with a positive floor."""
    row, verdict = _core1(sample)
    assert verdict.assessable == ia.LOWER_BOUND, verdict.as_dict()
    assert ia.ranking_floor(verdict) == row["stranded"] > 0, verdict.as_dict()
    return sample


@pytest.fixture(scope="module")
def held(sample):
    """The sample with core1's off_scan_gw_vlans marker removed: a row older than the marker, which the owner holds.
    Precondition, read from the owner: core1 is not assessed."""
    snap = copy.deepcopy(sample)
    stored = next(r for r in snap["failure_impact"] if isinstance(r, dict) and r.get("host") == "core1")
    del stored["off_scan_gw_vlans"]
    _row, verdict = _core1(snap)
    assert verdict.assessable == ia.NOT_ASSESSED and "legacy_row" in verdict.codes, verdict.as_dict()
    return snap


def _docx_lines(path):
    """Every paragraph, then every table row with its cells joined by ' | '."""
    from docx import Document
    doc = Document(path)
    lines = [p.text for p in doc.paragraphs]
    for table in doc.tables:
        for row in table.rows:
            lines.append(" | ".join(c.text.replace("\n", " ") for c in row.cells))
    return lines


def _raw_row(row, fields):
    """The row as the pre-W48 writers printed it: the stored values verbatim."""
    return " | ".join([str(row["host"])] + [str(row[f]) for f in fields])


# --- MOP: the per-wave max blast radius and its quantified rollback trigger ---------------------------------------
def _mop_core1_wave(tmp_path, snap, name):
    pytest.importorskip("docx")
    from cisco_toolkit.mop import write_mop_docx
    out = str(tmp_path / name)
    write_mop_docx(out, snap, "W48 Fleet")
    lines = _docx_lines(out)
    start = next(i for i, ln in enumerate(lines) if ln.startswith("Devices in scope | ")
                 and "core1" in ln.split(" | ", 1)[1].split(", "))
    blast = next(ln for ln in lines[start:] if ln.startswith("Max blast radius"))
    trigger = next(ln for ln in lines[start:] if ln.startswith("Blast-radius / outage overrun"))
    return lines, blast.split(" | ", 1)[1], trigger


def test_mop_sizes_the_wave_holding_core1_as_a_lower_bound(tmp_path, bounded):
    row, verdict = _core1(bounded)
    lines, cell, trigger = _mop_core1_wave(tmp_path, bounded, "mop_bounded.docx")
    match = re.match(r"^≥ (\d+) " + re.escape(ia.LOWER_BOUND_MARK) + " — ", cell)
    assert match, cell                                   # pre-W48: the bare count '45'
    assert int(match.group(1)) >= ia.ranking_floor(verdict)
    assert f"core1 (strands at least {row['stranded']} endpoint(s); {verdict.summary})" in cell, cell
    # §1's overview column carries the short form of the same figure
    overview = [ln.split(" | ") for ln in lines if ln.startswith(("Wave ", "Group ")) and ln.count(" | ") == 6]
    assert any(cells[5] == f"≥ {match.group(1)} {ia.LOWER_BOUND_MARK}" for cells in overview), overview
    assert "more endpoints than the" in trigger and "only a lower bound" in trigger, trigger


def test_mop_names_a_held_core1_as_not_assessed_and_never_sizes_on_its_45(tmp_path, held):
    row, verdict = _core1(held)
    _lines, cell, _trigger = _mop_core1_wave(tmp_path, held, "mop_held.docx")
    assert f"core1 ({verdict.summary})" in cell, cell     # pre-W48: the bare count '45'
    assert cell.strip() != str(row["stranded"]), cell
    assert not cell.startswith(f"≥ {row['stranded']} "), cell


# --- runbook §10 Risk Register ------------------------------------------------------------------------------------
def _runbook_lines(tmp_path, snap, name):
    pytest.importorskip("docx")
    from cisco_toolkit.runbook import write_runbook_docx
    out = str(tmp_path / name)
    write_runbook_docx(out, snap, "W48 Fleet")
    return _docx_lines(out)


def test_runbook_risk_register_writes_core1_as_a_lower_bound(tmp_path, bounded):
    row, verdict = _core1(bounded)
    lines = _runbook_lines(tmp_path, bounded, "rb_bounded.docx")
    expected = " | ".join(["core1"] + [str(ia.ranked_value(verdict, f)) for f in _RISK_FIELDS])
    assert f"≥ {row['stranded']} {ia.LOWER_BOUND_MARK}" in expected      # the expectation itself is a floor
    assert expected in lines, [ln for ln in lines if ln.startswith("core1 | ")]
    assert _raw_row(row, _RISK_FIELDS) not in lines                       # pre-W48: 'core1 | High | 3 | 45 | ...'
    assert any("publish their counts only as lower bounds" in ln
               and f"core1 (strands at least {row['stranded']} endpoint(s); {verdict.summary})" in ln
               for ln in lines)


def test_runbook_risk_register_names_a_held_core1_as_not_assessed(tmp_path, held):
    row, verdict = _core1(held)
    lines = _runbook_lines(tmp_path, held, "rb_held.docx")
    assert _raw_row(row, _RISK_FIELDS) not in lines                       # pre-W48: ranked first, raw
    assert any("are not ranked above" in ln and f"core1 ({verdict.summary})" in ln for ln in lines), \
        [ln for ln in lines if "not ranked" in ln]


# --- operations handbook §2.1 keystones ---------------------------------------------------------------------------
def _ops_lines(tmp_path, snap, name):
    pytest.importorskip("docx")
    from cisco_toolkit.ops import write_ops_handbook_docx
    out = str(tmp_path / name)
    write_ops_handbook_docx(out, snap, "W48 Fleet")
    return _docx_lines(out)


def test_ops_keystones_write_core1_as_a_lower_bound(tmp_path, bounded):
    row, verdict = _core1(bounded)
    lines = _ops_lines(tmp_path, bounded, "ops_bounded.docx")
    expected = " | ".join(["core1"] + [str(ia.ranked_value(verdict, f)) for f in _KEYSTONE_FIELDS])
    assert expected in lines, [ln for ln in lines if ln.startswith("core1 | ")]
    assert _raw_row(row, _KEYSTONE_FIELDS) not in lines                   # pre-W48: 'core1 | High | 45 | 3'
    assert any("publish their counts only as lower bounds" in ln and f"core1 (strands at least {row['stranded']}"
               in ln for ln in lines)


def test_ops_keystones_name_a_held_core1_as_not_assessed(tmp_path, held):
    row, verdict = _core1(held)
    lines = _ops_lines(tmp_path, held, "ops_held.docx")
    assert _raw_row(row, _KEYSTONE_FIELDS) not in lines                   # pre-W48: the top keystone, raw
    assert any("not ranked as keystones" in ln and f"core1 ({verdict.summary})" in ln for ln in lines), \
        [ln for ln in lines if "keystone" in ln.lower()]


# --- MCP failure_impact tool --------------------------------------------------------------------------------------
def _mcp_core1(snap):
    items = [item for item in mcp_server.failure_impact(snap, limit=10_000) if item.get("host") == "core1"]
    assert len(items) == 1, items
    return items[0]


def test_mcp_failure_impact_hands_the_assistant_core1_as_a_lower_bound(bounded):
    row, verdict = _core1(bounded)
    item = _mcp_core1(bounded)
    assert item.get("assessable") == ia.LOWER_BOUND and item.get("why") == verdict.why, item
    assert item["stranded"] == f"≥ {row['stranded']}", item                # pre-W48: the raw 45
    for field in ia.IMPACT_MEASURES:
        assert item[field] == ia.table_value(verdict, field), (field, item)
    assert item["severity"] != row["severity"] and item["backup"] == ia.NOT_ASSESSED_CELL, item


def test_mcp_failure_impact_hands_the_assistant_a_held_core1_as_not_assessed(held):
    row, verdict = _core1(held)
    item = _mcp_core1(held)
    assert item.get("assessable") == ia.NOT_ASSESSED, item
    assert all(item[field] == ia.NOT_ASSESSED_CELL for field in ia.IMPACT_MEASURES), item
    assert row["detail"] not in item["detail"] and item["detail"] == ia.table_detail(verdict), item


# --- the consumer W48 STOPPED on (persisted output; see _RAW_RATCHET) ---------------------------------------------
_STOPPED = pytest.mark.xfail(
    strict=True, raises=AssertionError,
    reason="W48 STOP: persisted output, routed to the supervisor for a hosted regeneration (see _RAW_RATCHET). "
           "When the consumer reads the owner this XPASSes: delete this marker and the ratchet entry.")


@_STOPPED
@pytest.mark.parametrize("variant", ["bounded", "held"])
def test_design_advisor_never_counts_a_withheld_zero_as_a_measured_no_backup_device(variant, request):
    from cisco_toolkit.design_advisor import _signals
    snap = request.getfixturevalue(variant)
    measured = sum(1 for row, verdict in ia.rows_with_verdicts(snap)
                   if not verdict.withholds("severity") and row.get("severity") == "High"
                   and not verdict.withholds("backup") and row.get("backup") == 0)
    _row, verdict = _core1(snap)
    assert verdict.withholds("backup")                  # core1's zero is not a measurement in either variant
    assert _signals(snap)["nobackup_high"] == measured


# --- protocol_assurance.cutover_operator_evidence: the versioned receipt contract (W50) ---------------------------
# W48 stopped here because rehearsal.impacts is persisted in every AssessHub execution receipt and re-verified on
# every read. W50 versions the contract: a new comparison carries cutover_operator_evidence/2 (owner-valued rows);
# a stored /1 receipt re-verifies against the legacy raw-row recomputation, selected only by its declared /1.
@pytest.mark.parametrize("variant", ["bounded", "held"])
def test_cutover_operator_evidence_carries_the_owner_values_for_core1(variant, request):
    from cisco_toolkit.protocol_assurance import cutover_operator_evidence
    snap = request.getfixturevalue(variant)
    _row, verdict = _core1(snap)
    impacts = [r for r in cutover_operator_evidence(snap)["rehearsal"]["impacts"] if r.get("host") == "core1"]
    assert len(impacts) == 1, impacts
    assert impacts[0].get("assessable") == verdict.assessable, impacts[0]
    assert impacts[0].get("severity") == ia.table_value(verdict, "severity"), impacts[0]
    assert impacts[0].get("stranded") == ia.table_value(verdict, "stranded"), impacts[0]


def _v2_core1(snap):
    from cisco_toolkit import protocol_assurance as pa
    evidence = pa.cutover_operator_evidence(snap)
    assert evidence["schema"] == pa.CUTOVER_OPERATOR_EVIDENCE_SCHEMA == pa.CUTOVER_OPERATOR_EVIDENCE_SCHEMA_V2
    rows = [r for r in evidence["rehearsal"]["impacts"] if r.get("host") == "core1"]
    assert len(rows) == 1, rows
    return evidence, rows[0]


def test_v2_receipt_impacts_carry_core1_as_the_lower_bound_it_is(bounded):
    row, verdict = _core1(bounded)
    evidence, item = _v2_core1(bounded)
    assert item["assessable"] == ia.LOWER_BOUND and item["why"] == verdict.why and item["why"], item
    assert item["stranded"] == f"≥ {row['stranded']}", item                 # /1 stored the raw 45 as exact
    assert item["severity"] == f"{row['severity']} (lower bound)", item
    for field in ia.IMPACT_MEASURES:
        assert item[field] == ia.table_value(verdict, field), (field, item)
    assert item["backup"] == ia.NOT_ASSESSED_CELL, item                        # a bounded zero is not a measured 0
    assert item["detail"] == ia.table_detail(verdict) and item["detail"] != row["detail"], item
    assert set(item) == {"host", "assessable", "why", "detail", *ia.IMPACT_MEASURES}, item
    rehearsal = evidence["rehearsal"]
    assert rehearsal["impacts_owner"] == ia.SCHEMA
    assert rehearsal["n_impacts_total"] == len(ia.rows_with_verdicts(bounded))
    assert rehearsal["n_impacts_by_assessable"] == {
        k: sum(1 for _r, v in ia.rows_with_verdicts(bounded) if v.assessable == k) for k in ia.VERDICTS}
    assert rehearsal["n_impacts_by_assessable"][ia.LOWER_BOUND] >= 1


def test_v2_receipt_impacts_carry_a_held_core1_as_not_assessed(held):
    row, verdict = _core1(held)
    _evidence, item = _v2_core1(held)
    assert item["assessable"] == ia.NOT_ASSESSED and item["why"] == verdict.why, item
    assert all(item[field] == ia.NOT_ASSESSED_CELL for field in ia.IMPACT_MEASURES), item
    assert row["detail"] not in item["detail"] and item["detail"] == ia.table_detail(verdict), item


@pytest.mark.parametrize("variant", ["bounded", "held"])
def test_the_legacy_v1_recomputation_is_the_verbatim_raw_row_copy_and_only_on_request(variant, request):
    """A stored /1 receipt keeps re-verifying only if /1 still recomputes byte-for-byte what /1 stored: every stored
    object row copied raw, the pre-W50 rehearsal keys and nothing the owner added. It is reachable only by naming
    /1 explicitly; the default is /2, and an unknown or missing-type contract is refused, never computed."""
    from cisco_toolkit import protocol_assurance as pa
    snap = request.getfixturevalue(variant)
    legacy = pa.cutover_operator_evidence(snap, schema=pa.CUTOVER_OPERATOR_EVIDENCE_SCHEMA_V1)
    assert legacy["schema"] == "cutover_operator_evidence/1"
    rehearsal = legacy["rehearsal"]
    assert rehearsal["impacts"] == [dict(r) for r in snap["failure_impact"] if isinstance(r, dict)]
    assert set(rehearsal) == {"status", "assurance_level", "source_owner", "n_impacts_total", "impacts",
                              "l2_failure_rehearsal", "note"}, sorted(rehearsal)
    current = pa.cutover_operator_evidence(snap)
    assert current["schema"] == "cutover_operator_evidence/2"
    # everything but the versioned impacts block is shared, so the gate recomputes identically under either
    for key in ("owner", "owns_verdict", "current_baseline_blocker_export", "rollback"):
        assert legacy[key] == current[key], key
    for key in ("status", "assurance_level", "source_owner", "n_impacts_total", "l2_failure_rehearsal", "note"):
        assert rehearsal[key] == current["rehearsal"][key], key
    for unknown in ("cutover_operator_evidence/3", "cutover_operator_evidence/0", "", 2, ["cutover_operator_evidence/2"]):
        with pytest.raises(ValueError, match="unsupported operator-evidence contract"):
            pa.cutover_operator_evidence(snap, schema=unknown)


def test_a_stored_comparison_names_its_contract_or_reads_as_unverified():
    from cisco_toolkit import protocol_assurance as pa
    v1, v2 = pa.CUTOVER_OPERATOR_EVIDENCE_SCHEMA_V1, pa.CUTOVER_OPERATOR_EVIDENCE_SCHEMA_V2
    assert pa.stored_operator_evidence_schema({"operator_evidence": {"schema": v1}}) == v1
    assert pa.stored_operator_evidence_schema({"operator_evidence": {"schema": v2}}) == v2
    for stored in (None, [], {}, {"operator_evidence": None}, {"operator_evidence": {}},
                   {"operator_evidence": {"schema": None}}, {"operator_evidence": {"schema": "cutover_operator_evidence/3"}},
                   {"operator_evidence": {"schema": "cutover_operator_evidence"}}, {"operator_evidence": {"schema": 1}},
                   {"operator_evidence": [{"schema": v2}]}):
        assert pa.stored_operator_evidence_schema(stored) is None, stored
