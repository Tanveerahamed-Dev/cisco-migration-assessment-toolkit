"""W65 census: every engine, AssessHub and Atlas file-write site, classified for client data.

The two privacy gates (``.github/scripts/verify_repository_privacy.py`` for the committed tree and
``cisco_toolkit/distribution_verify.py`` for the wheel and sdist) refuse files by NAME.  A name
gate is only as complete as its list, and a list kept by hand is the "named subset instead of the
structural class" defect: before W65 the engine wrote ``.protocol-assurance.json``,
``.comparison.json``, ``.trend-comparisons.json`` and ``.phase_timings.json`` sidecars that carry
client hostnames and evidence, and neither gate classified them.

This module closes the class from the producer side.  :func:`write_sites` parses every Python file
under :data:`SCANNED_ROOTS` with :mod:`ast` (nothing is imported or executed) and counts, per
enclosing function, every call that creates or replaces file bytes, plus every reference to a
:data:`DELEGATED_WRITERS` helper whose output name is chosen by its caller.  :data:`WRITE_SITE_CENSUS`
classifies each of those functions:

* ``client`` - the bytes can carry client evidence, and every name they are published under is a
  class in ``cisco_toolkit.distribution_verify.CLIENT_ARTIFACT_NAME_CLASSES`` (both gates refuse it);
* ``private-temp`` - client bytes that only ever live under the operating-system temporary
  directory (``tempfile`` with no ``dir=``, or a work directory made under it) and are removed by
  the same code path, so no repository, output folder or archive can hold them;
* ``delegated`` - a generic writer whose name comes from its caller; every reference to it is
  itself a census row, so the caller is classified instead;
* ``operator-path`` - an operator tool that writes only to a path given explicitly on its command
  line (no default file); a name the operator invents cannot be gated by name, so the row says
  what the bytes are;
* ``non-client`` - the bytes cannot carry client evidence; the row says why.

A second, name-level net covers a changed name inside an already classified function:
:func:`suffix_literals` collects every literal appended to an output stem (``stem + ".x.json"``)
or ending an f-string after a substitution (``f"{stem}.x.json"``), and each one must be a
registered class or a :data:`NON_CLIENT_SUFFIX_LITERALS` entry with a reason. Its bound: a bare
file name joined onto a directory (``os.path.join(out, "name.json")``) is not collected, because
reads use the same shape; the known leaf producers are tied to the registry by constant in the test.

:func:`census_problems` and :func:`suffix_literal_problems` are the whole check: a function whose
write count changed, a new function that writes, a ``client`` row naming a class the registry does
not have, an undeclared delegated writer, or an unclassified suffix literal.
``tests/test_client_artifact_census.py`` asserts both are empty, so a new sidecar fails CI until it
is classified here and, when it is client-bearing, named in the registry.

Run ``python tests/client_artifact_census.py`` from the repository root for the same report. The
module lives under ``tests/`` (not ``tools/``) so that it stays outside the byte-custody LF policy
domains, whose tracked-path receipts in ``tests/fixtures/atlas-r2-byte-custody-policy.v1.json``
would otherwise move with it.
"""

from __future__ import annotations

import ast
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Iterable, Mapping

ROOT = Path(__file__).resolve().parents[1]


def _registry():
    """The owner registry, imported on use so this module imports without the package path."""
    from cisco_toolkit.distribution_verify import CLIENT_ARTIFACT_NAME_CLASSES, client_artifact_class

    return CLIENT_ARTIFACT_NAME_CLASSES, client_artifact_class

#: Every root whose code can write an engine, AssessHub or Atlas artifact.
SCANNED_ROOTS = ("COLLECT_PARSE_V3_23_0.py", "cisco_toolkit", "webapp/backend", "portable")

CLIENT = "client"
PRIVATE_TEMP = "private-temp"
DELEGATED = "delegated"
OPERATOR_PATH = "operator-path"
NON_CLIENT = "non-client"
DISPOSITIONS = frozenset({CLIENT, PRIVATE_TEMP, DELEGATED, OPERATOR_PATH, NON_CLIENT})

#: Generic writers whose output NAME is supplied by the caller. A reference to one of these names
#: anywhere under SCANNED_ROOTS (a call, a callable passed along, an import alias) is a census row of
#: its own, so a new ``write_json_file(base + ".new.json", ...)`` fails the census in its caller.
#: Each name must be defined exactly once under SCANNED_ROOTS, in the file given here.
DELEGATED_WRITERS: Mapping[str, str] = {
    "write_json_file": "COLLECT_PARSE_V3_23_0.py",
    "_write_json_atomic": "COLLECT_PARSE_V3_23_0.py",
    "_replace_with_retries": "COLLECT_PARSE_V3_23_0.py",
    "write_html_explorer": "cisco_toolkit/html.py",
    "write_nrfu_pack": "cisco_toolkit/nrfu_export.py",
}

_WRITE_FLAGS = frozenset({"O_WRONLY", "O_RDWR", "O_CREAT", "O_APPEND", "O_TRUNC", "O_EXCL"})
_SHUTIL_WRITERS = frozenset({"copy", "copy2", "copyfile", "copytree", "move"})
_OS_WRITERS = frozenset({"replace", "rename", "link", "symlink"})
_STREAM_MODULES = frozenset({"io", "gzip", "bz2", "lzma", "tarfile", "codecs"})


def _constant_text(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _mode(call: ast.Call, position: int) -> tuple[bool, str | None]:
    """Return ``(present, constant_mode)``; a present but computed mode yields ``(True, None)``."""
    for keyword in call.keywords:
        if keyword.arg == "mode":
            return True, _constant_text(keyword.value)
    if len(call.args) > position:
        return True, _constant_text(call.args[position])
    return False, None


def _mode_writes(mode: str | None) -> bool:
    return mode is None or any(flag in mode for flag in "wax+")


def write_primitive(call: ast.Call) -> str | None:
    """Name the file-writing primitive ``call`` is, or ``None``.

    Conservative where a mode is computed (a builtin ``open`` with a non-literal mode counts as a
    write); exact where the call cannot write (``open(path)``, ``Path.open()``, ``zf.open(info)``).
    Directory creation is not a write: a directory carries no bytes until a counted call adds them.
    """
    func = call.func
    if isinstance(func, ast.Name):
        if func.id == "open":
            present, mode = _mode(call, 1)
            return "open" if present and _mode_writes(mode) else None
        return None
    if not isinstance(func, ast.Attribute):
        return None
    attr = func.attr
    base = func.value.id if isinstance(func.value, ast.Name) else None
    if attr in {"write_text", "write_bytes", "save", "touch"}:
        return attr
    if base == "os":
        if attr in _OS_WRITERS:
            return f"os.{attr}"
        if attr == "open" and len(call.args) > 1:
            flags = {
                node.attr if isinstance(node, ast.Attribute) else getattr(node, "id", None)
                for node in ast.walk(call.args[1])
            }
            return "os.open" if flags & _WRITE_FLAGS else None
        return None
    if base == "shutil" and attr in _SHUTIL_WRITERS:
        return f"shutil.{attr}"
    if base == "tempfile" and attr in {"mkstemp", "NamedTemporaryFile"}:
        return f"tempfile.{attr}"
    if base == "sqlite3" and attr == "connect":
        return "sqlite3.connect"
    if base == "logging" and attr == "FileHandler":
        return "logging.FileHandler"
    if base == "zipfile" and attr == "ZipFile":
        present, mode = _mode(call, 1)
        return "zipfile.ZipFile" if present and mode != "r" and _mode_writes(mode) else None
    if base in _STREAM_MODULES and attr == "open":
        present, mode = _mode(call, 1)
        return f"{base}.open" if present and mode != "r" and _mode_writes(mode) else None
    if attr == "open":
        # Path.open(mode) / ZipFile.open(name, mode). Only a literal writing mode counts: the first
        # argument of ``urllib`` openers and ``ZipFile.open`` is a request or member, not a mode.
        for keyword in call.keywords:
            if keyword.arg == "mode":
                mode = _constant_text(keyword.value)
                return "Path.open" if mode is not None and _mode_writes(mode) and mode != "r" else None
        for argument in call.args[:2]:
            mode = _constant_text(argument)
            if mode is not None and mode != "r" and set(mode) <= set("rwaxbt+") and _mode_writes(mode):
                return "Path.open"
        return None
    return None


#: Generated directories that never hold authored source (``portable/build`` and ``portable/dist``
#: are the PyInstaller work and output trees).
_GENERATED_PARTS = frozenset({"__pycache__", "build", "dist", "node_modules"})


def scanned_files(root: Path = ROOT) -> list[Path]:
    files: list[Path] = []
    for entry in SCANNED_ROOTS:
        path = root / entry
        if path.is_file():
            files.append(path)
        elif path.is_dir():
            files.extend(
                p for p in path.rglob("*.py")
                if not _GENERATED_PARTS & set(p.relative_to(path).parts[:-1])
            )
    return sorted(set(files), key=lambda p: p.relative_to(root).as_posix())


class _SiteVisitor(ast.NodeVisitor):
    """Count write primitives and delegated-writer references per enclosing function."""

    def __init__(self, relative: str, delegated: Iterable[str], aliases: Iterable[str]) -> None:
        self.relative = relative
        self.delegated = frozenset(delegated)
        # A delegated writer imported under another name (``import ... as w``) is referenced by
        # that name, so both spellings count. The import statement itself is not a write.
        self.referenced = self.delegated | frozenset(aliases)
        self.scope: list[str] = []
        self.sites: Counter[str] = Counter()
        self.definitions: list[str] = []

    def _key(self) -> str:
        return f"{self.relative}::{'.'.join(self.scope) or '<module>'}"

    def _enter(self, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> None:
        if node.name in self.delegated and not isinstance(node, ast.ClassDef):
            self.definitions.append(node.name)
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    visit_FunctionDef = visit_AsyncFunctionDef = visit_ClassDef = _enter

    def visit_Call(self, node: ast.Call) -> None:
        if write_primitive(node):
            self.sites[self._key()] += 1
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if node.id in self.referenced:
            self.sites[self._key()] += 1

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr in self.delegated:
            self.sites[self._key()] += 1
        self.generic_visit(node)


def _aliases(tree: ast.AST, delegated: frozenset[str]) -> set[str]:
    return {
        alias.asname
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
        if alias.asname and alias.name.rsplit(".", 1)[-1] in delegated
    }


def scan(root: Path = ROOT, delegated: Iterable[str] = DELEGATED_WRITERS) -> tuple[dict[str, int], dict[str, list[str]]]:
    """Return ``({"path::qualname": count}, {delegated name: [defining files]})``."""
    names = frozenset(delegated)
    sites: Counter[str] = Counter()
    definitions: dict[str, list[str]] = {name: [] for name in sorted(names)}
    for path in scanned_files(root):
        relative = path.relative_to(root).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        visitor = _SiteVisitor(relative, names, _aliases(tree, names))
        visitor.visit(tree)
        sites.update(visitor.sites)
        for name in visitor.definitions:
            definitions[name].append(relative)
    return dict(sorted(sites.items())), definitions


def write_sites(root: Path = ROOT) -> dict[str, int]:
    return scan(root)[0]


_RELEASE = (
    "Atlas release or build material produced from tracked source; the runtime bundle itself refuses "
    "client artifacts (portable/release_contract.py :: _forbidden_client_artifact)"
)

#: A stem suffix: starts with "." or "_", has a name part, and ends with an extension. A bare
#: extension such as ".txt" is not a suffix literal (it carries no artifact identity). Only "."
#: separates segments: "-" is a name character, so no input has two ways to match (CodeQL flagged
#: an earlier "[.-]" separator, which overlapped the name class, as exponential backtracking).
_SUFFIX_LITERAL = re.compile(r"^[._][A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*\.[A-Za-z0-9]+$")

#: Suffix literals under SCANNED_ROOTS that are not client artifact names, with the reason.
NON_CLIENT_SUFFIX_LITERALS: Mapping[str, str] = {
    ".tar.gz": "the name of the sdist archive distribution_verify inspects",
    ".coverage_scope.window": "a JSON field path in a transition refusal message, not a file name",
    ".coverage_scope.complete": "a JSON field path in a transition refusal message, not a file name",
    ".interpreter_source.bytes": "a JSON field path in a TCB review message, not a file name",
    ".interpreter_source.sha256": "a JSON field path in a TCB review message, not a file name",
    ".manifest.json": "Atlas release manifest sidecar; " + _RELEASE,
    ".cdx.json": "Atlas release SBOM sidecar; " + _RELEASE,
    ".toolchain.json": "Atlas release toolchain sidecar; " + _RELEASE,
    ".signing.json": "Atlas release signing sidecar; " + _RELEASE,
    ".qualification.json": "Atlas release qualification sidecar; " + _RELEASE,
    ".provenance.json": "Atlas release provenance sidecar; " + _RELEASE,
    ".third-party-notices.json": "Atlas release notices sidecar; " + _RELEASE,
    ".release.json": "Atlas release index; " + _RELEASE,
    ".atlas-redaction.lock": "the redaction output lock token, which never holds data",
}


def suffix_literals(root: Path = ROOT) -> list[tuple[str, str]]:
    """Every ``(file:line, literal)`` appended to an output stem under SCANNED_ROOTS."""
    found: list[tuple[str, str]] = []
    for path in scanned_files(root):
        relative = path.relative_to(root).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        for node in ast.walk(tree):
            literal = None
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
                literal = _constant_text(node.right)
            elif (
                isinstance(node, ast.JoinedStr)
                and len(node.values) >= 2
                and isinstance(node.values[-2], ast.FormattedValue)
            ):
                literal = _constant_text(node.values[-1])
            if literal is not None and _SUFFIX_LITERAL.match(literal):
                found.append((f"{relative}:{node.lineno}", literal))
    return sorted(found)


def suffix_literal_problems(
    root: Path = ROOT,
    non_client: Mapping[str, str] | None = None,
) -> list[str]:
    non_client = NON_CLIENT_SUFFIX_LITERALS if non_client is None else non_client
    _classes, client_artifact_class = _registry()
    literals = suffix_literals(root)
    problems: list[str] = []
    for location, literal in literals:
        if literal in non_client:
            continue
        if client_artifact_class(f"customer-output/Acme{literal}") is None:
            problems.append(f"unclassified output-name suffix literal {literal!r} at {location}")
    seen = {literal for _location, literal in literals}
    for literal, why in sorted(non_client.items()):
        if literal not in seen:
            problems.append(f"non-client suffix literal no longer appears: {literal!r}")
        if client_artifact_class(f"customer-output/Acme{literal}") is not None:
            problems.append(f"non-client suffix literal is a registered client class: {literal!r}")
        if not str(why).strip():
            problems.append(f"non-client suffix literal gives no reason: {literal!r}")
    return problems


_CAPTURES = (
    "capture-show", "capture-get-system", "capture-aws", "capture-moquery", "capture-api",
    "capture-ers", "capture-dataservice",
)
_REST_CAPTURES = ("capture-moquery", "capture-api", "capture-ers", "capture-dataservice")
_COLLECTION_SIDECARS = (
    "collection-device-info", "collection-command-index", "collection-capture-meta",
)
_DOCX = ("word-document",)
_SYSTEM_TEMP = (
    "tempfile.mkstemp with no dir= puts it under the operating-system temporary directory, and "
    "the same function unlinks it after use"
)
_WORKDIR = (
    "inside the job's private work directory, tempfile.mkdtemp(dir=_engine_temp_parent()) under the "
    "operating-system temporary directory, which the job removes when it ends"
)
_REPO_LEDGER = (
    "a tracked repository self-measurement ledger under docs/quality/; no assessment input reaches "
    "it, and the repository gate scans its content"
)

# The census. Key: "<file>::<enclosing qualname>". Value: (write count, disposition, registry
# class keys, why). Counts are exact so a second write added to a classified function is reviewed.
WRITE_SITE_CENSUS: Mapping[str, tuple[int, str, tuple[str, ...], str]] = {
    # ---- engine CLI (COLLECT_PARSE_V3_23_0.py) --------------------------------------------------
    "COLLECT_PARSE_V3_23_0.py::collect": (
        4, CLIENT, _CAPTURES + _COLLECTION_SIDECARS,
        "live collector: one <command>.txt capture per command under <collection>/<host>/, plus "
        "device_info.json, command_index.json and _capture_meta.json through write_json_file"),
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
        1, DELEGATED, (),
        "generic os.replace with retries; the caller names source and destination"),
    "COLLECT_PARSE_V3_23_0.py::main": (
        4, CLIENT,
        ("pre-change-certificate", "comparison-receipt", "trend-comparisons", "explorer"),
        "--compare writes <diff>.precert.json and <diff>.comparison.json, --trend writes "
        "<trend>.trend-comparisons.json, and the assessment run writes <output>_explorer.html"),
    "COLLECT_PARSE_V3_23_0.py::_stage_finalize": (
        4, CLIENT, ("protocol-assurance-export", "explorer", "phase-timings", "run-manifest"),
        "<output>.protocol-assurance.json, the BOUND <output>_explorer.html refresh, "
        "<output>.phase_timings.json and <output>.run_manifest.json"),
    "COLLECT_PARSE_V3_23_0.py::_stage_finalize._publish_snapshot": (
        1, CLIENT, ("snapshot",), "<output>.snapshot.json, the parsed estate"),
    "COLLECT_PARSE_V3_23_0.py::_stage_finalize._save_workbook": (
        1, CLIENT, ("workbook",),
        "the assessment workbook <output>.xlsx (staged as .<stem>.receipt-<nonce>.tmp.xlsx)"),
    "COLLECT_PARSE_V3_23_0.py::_write_incomplete_marker": (
        1, CLIENT, ("incomplete-marker",),
        "<output>.incomplete.json: the run's custody and failure record, written before the seal"),
    "COLLECT_PARSE_V3_23_0.py::_atomic_receipt_refresh": (
        2, CLIENT,
        ("explorer", "word-document", "workbook", "receipt-staging-html", "receipt-previous-html"),
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
        2, CLIENT, _CAPTURES + _COLLECTION_SIDECARS + ("redaction-staging",),
        "--redact-collection rewrites collected captures in place through <capture>.redacting"),
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
    "cisco_toolkit/gate_state.py::save_store": (
        2, CLIENT, ("engagement-gate-state", "atomic-staging"),
        "docs/engagement-state.json under the gate root: engagement identity, approvers and "
        "reasons, staged as engagement-state.json.<random>.tmp"),
    "cisco_toolkit/gate_state.py::_open_lock_fd": (
        1, NON_CLIENT, (),
        "<store>.lock is an empty mutual-exclusion token; it never holds data"),
    "cisco_toolkit/recall.py::log_query": (
        1, CLIENT, ("query-log",),
        "docs/quality/query_log.jsonl: real retrieval queries, which can name client tokens"),
    # ---- repository tooling inside cisco_toolkit -------------------------------------------------
    "cisco_toolkit/clock.py::append_run": (
        1, NON_CLIENT, (), "docs/quality/nightly_runs.jsonl: " + _REPO_LEDGER),
    "cisco_toolkit/scorecard.py::append_row": (
        1, NON_CLIENT, (), "docs/quality/scorecard.jsonl: " + _REPO_LEDGER),
    "cisco_toolkit/retrieval_eval.py::append_pooled_qrels": (
        1, NON_CLIENT, (),
        "docs/quality/d10-pooled-qrels.jsonl: query ids, document ids and grades over the tracked "
        "D10 eval set"),
    "cisco_toolkit/retrieval_eval.py::run_eval": (
        2, NON_CLIENT, (),
        "d10-eval-results-<date>.json and .md: retrieval metrics over the tracked D10 eval set"),
    "cisco_toolkit/retrieval_eval.py::invoke_judge_helper": (
        1, PRIVATE_TEMP, (),
        "judge pairs carrying corpus and vault-digest excerpts; " + _SYSTEM_TEMP),
    "cisco_toolkit/holdout.py::_append_access": (
        1, NON_CLIENT, (),
        "docs/quality/holdout_access.jsonl: access events with the declared reviewer and the OS user "
        "name (operator identity, not client evidence; the repository gate scans its content)"),
    "cisco_toolkit/holdout.py::main": (
        1, NON_CLIENT, (),
        "docs/quality/holdout_manifest.json: a hash chain of holdout row digests and policy counts"),
    "cisco_toolkit/memory_guard.py::main": (
        1, OPERATOR_PATH, (),
        "`memory_guard snapshot --out <path>` (default stdout): the agent-memory store path, memory "
        "file names and SHA-256 digests; memory file names can name an engagement"),
    "cisco_toolkit/distribution_verify.py::_write_new_proof": (
        1, NON_CLIENT, (),
        "the distribution proof: digests and measurements of this repository's own wheel and sdist"),
    "cisco_toolkit/registry_integrity.py::_write_temp_bytes": (
        1, NON_CLIENT, (), "staging for the public IANA and IEEE reference packs"),
    "cisco_toolkit/registry_integrity.py::publish_pack_and_manifest": (
        3, NON_CLIENT, (), "the public IANA and IEEE reference packs, marker and manifest"),
    "cisco_toolkit/registry_integrity.py::update_manifest": (
        1, NON_CLIENT, (), "the public reference-pack manifest"),
    "cisco_toolkit/registry_integrity.py::_restore_snapshot": (
        1, NON_CLIENT, (), "rollback of the public reference-pack files"),
    "cisco_toolkit/transition_legacy.py::_run_pinned_release1_driver": (
        1, NON_CLIENT, (),
        "materialises the verified release-1 driver source bundle in a temporary directory"),
    "cisco_toolkit/transition_runtime_discovery.py::_materialize_commit_inputs": (
        1, NON_CLIENT, (), "materialises tracked repository source for runtime discovery"),
    "cisco_toolkit/transition_runtime_discovery.py::_materialize_collector_target_script": (
        1, NON_CLIENT, (), "writes the discovery collector's own target script"),
    # ---- AssessHub (webapp/backend) --------------------------------------------------------------
    "webapp/backend/app.py::create_app.execution_report": (
        1, PRIVATE_TEMP, _DOCX, "the PIR download assesshub_pir_*.docx; " + _SYSTEM_TEMP),
    "webapp/backend/deliverables.py::generate": (
        1, PRIVATE_TEMP, ("word-document", "presentation"),
        "a snapshot deliverable download assesshub_*.<ext>; " + _SYSTEM_TEMP),
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
        2, CLIENT, ("database", "database-backup-partial"),
        "backups/assesshub-<stamp>.db, staged as assesshub-<stamp>-<pid>-<hex>.db.partial"),
    "webapp/backend/storage.py::_backup_campaign_evidence": (
        1, CLIENT, ("database", "database-wal", "database-shm"),
        "opens an existing database backup read-only and immutable to classify it"),
    "webapp/backend/ingest.py::_safe_extract": (
        1, PRIVATE_TEMP, (), "an uploaded collection ZIP extracted " + _WORKDIR),
    "webapp/backend/ingest.py::_stage_physical_tree": (
        1, PRIVATE_TEMP, (), "a collection folder copied into private custody " + _WORKDIR),
    "webapp/backend/ingest.py::_assess_tree": (
        1, PRIVATE_TEMP, ("devices-inventory",),
        "the job's synthesised devices.json " + _WORKDIR),
    "webapp/backend/ingest.py::_run_redaction_folder_locked": (
        1, PRIVATE_TEMP, ("devices-inventory",),
        "the redaction job's synthesised devices.json " + _WORKDIR),
    "webapp/backend/ingest.py::_write_min_template": (
        1, NON_CLIENT, (),
        "an empty minimal workbook template (template.xlsx) for the engine child; no assessment "
        "data, and the .xlsx class refuses the name anyway"),
    "webapp/backend/ingest.py::_copy_back_scrubbed_collection": (
        2, CLIENT, _CAPTURES + ("atomic-staging",),
        "--redact-collection copies scrubbed captures back over the operator's collection through "
        ".<capture>.atlas-scrub-<hex>.tmp"),
    "webapp/backend/ingest.py::_promote_verified_delivery": (
        6, CLIENT,
        ("word-document", "presentation", "workbook", "protocol-assurance-export", "explorer",
         "snapshot", "run-manifest", "phase-timings", "topology-mermaid", "topology-graphviz",
         "redaction-receipt", "atomic-staging"),
        "promotes the verified Assessment_redacted* set into the output folder and writes "
        "Assessment_redacted.redaction.json through .<receipt>.<run_id>.tmp"),
    "webapp/backend/ingest.py::_mark_output_unsafe": (
        1, CLIENT, ("unsafe-marker",),
        "DO-NOT-SEND-NOT-REDACTED.txt, quoting why the run refused to certify the set"),
    "webapp/backend/ingest.py::_mark_output_incomplete": (
        1, CLIENT, ("incomplete-set-marker", "incomplete-set-fallback"),
        "INCOMPLETE-SET.txt (or INCOMPLETE-SET-ATLAS.txt), quoting the engine's gap reasons"),
    "webapp/backend/ingest.py::_output_dir_lock": (
        1, NON_CLIENT, (), ".atlas-redaction.lock is an empty lock token; it never holds data"),
    "webapp/backend/serve.py::_writable_failure": (
        1, NON_CLIENT, (), "an empty write probe, unlinked immediately"),
    "webapp/backend/export_ui_projection_openapi.py::main": (
        1, NON_CLIENT, (), "the UI projection OpenAPI document generated from code"),
    "webapp/backend/observe_ui_projection_contract.py::emit": (
        1, NON_CLIENT, (), "UI projection schema observations generated from code"),
    # ---- Atlas packaging and qualification (portable) -------------------------------------------
    "portable/database_preflight.py::_open_readonly": (
        1, CLIENT, ("database", "database-wal", "database-shm"),
        "opens the operator's AssessHub database copy read-only (mode=ro, query_only)"),
    "portable/build_atlas.py::build": (1, NON_CLIENT, (), _RELEASE),
    "portable/build_atlas.py::smoke": (1, NON_CLIENT, (), _RELEASE),
    "portable/build_atlas.py::_detach_runtime_data": (
        1, NON_CLIENT, (),
        "moves the SMOKE copy's data directory, created by the synthetic field-layout smoke run"),
    "portable/build_release.py::main": (1, NON_CLIENT, (), _RELEASE),
    "portable/package_signed_release.py::_independent_authenticode": (1, NON_CLIENT, (), _RELEASE),
    "portable/package_signed_release.py::main": (1, NON_CLIENT, (), _RELEASE),
    "portable/prepare_signing.py::prepare": (2, NON_CLIENT, (), _RELEASE),
    "portable/release_contract.py::_record_build_modules": (1, NON_CLIENT, (), _RELEASE),
    "portable/release_contract.py::_write_checksums": (1, NON_CLIENT, (), _RELEASE),
    "portable/release_contract.py::_write_deterministic_zip": (1, NON_CLIENT, (), _RELEASE),
    "portable/release_contract.py::build_portable_release": (6, NON_CLIENT, (), _RELEASE),
    "portable/qualify_atlas.py::qualify": (1, NON_CLIENT, (), _RELEASE),
    "portable/qualify_atlas.py::main": (1, NON_CLIENT, (), "the qualification receipt"),
    "portable/qualify_atlas.py::_redaction": (
        5, NON_CLIENT, (),
        "synthetic redaction canaries (SYNTHETIC-CORE1, TEST-ONLY) in a qualification collection"),
    "portable/qualify_atlas.py::_database_preflight": (
        1, NON_CLIENT, (),
        "builds the prior-release database from the synthetic, digest-pinned fixture"),
    "portable/qualify_atlas.py::_database_preflight_case": (
        2, NON_CLIENT, (),
        "copies that synthetic database and writes its atlas-db-preflight.json request"),
}


def census_problems(
    root: Path = ROOT,
    census: Mapping[str, tuple[int, str, tuple[str, ...], str]] | None = None,
    registry_keys: Iterable[str] | None = None,
    delegated: Mapping[str, str] | None = None,
) -> list[str]:
    """Every disagreement between the code's write sites and the census, as readable lines."""
    census = WRITE_SITE_CENSUS if census is None else census
    delegated = DELEGATED_WRITERS if delegated is None else delegated
    if registry_keys is None:
        registry_keys = [row[0] for row in _registry()[0]]
    known = frozenset(registry_keys)
    observed, definitions = scan(root, delegated)
    problems: list[str] = []
    for name, owner in sorted(delegated.items()):
        if definitions.get(name) != [owner]:
            problems.append(
                f"delegated writer {name!r} must be defined exactly once, in {owner}; "
                f"found {definitions.get(name)}")
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
        if disposition == NON_CLIENT and keys:
            problems.append(f"non-client write site must not name a registry class: {key}")
        for class_key in keys:
            if class_key not in known:
                problems.append(f"write site names an unregistered class {class_key!r}: {key}")
        if disposition == DELEGATED:
            name = key.rsplit("::", 1)[-1].rsplit(".", 1)[-1]
            if delegated.get(name) != key.split("::", 1)[0]:
                problems.append(f"delegated row is not a declared DELEGATED_WRITERS definition: {key}")
    for name, owner in sorted(delegated.items()):
        key = f"{owner}::{name}"
        row = census.get(key)
        if row is not None and row[1] != DELEGATED:
            problems.append(f"declared delegated writer is classified {row[1]!r}: {key}")
    return problems


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] == ["--dump"]:
        for key, count in write_sites(ROOT).items():
            print(f"{count}\t{key}")
        return 0
    problems = census_problems(ROOT) + suffix_literal_problems(ROOT)
    for line in problems:
        print(line)
    sites = write_sites(ROOT)
    print(f"{len(sites)} write site(s) and {len(suffix_literals(ROOT))} suffix literal(s) in "
          f"{len(scanned_files(ROOT))} file(s); {len(problems)} census problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    # Run as a script, sys.path[0] is tests/; the registry import needs the repository root.
    sys.path.insert(0, str(ROOT))
    raise SystemExit(main())
