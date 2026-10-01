"""Integrity guard for the project-wide SSOT registry (docs/ssot.md).

The registry is the one index of *where the truth for any fact lives* -- it points to a federated
set of owners (cisco_toolkit/ssot.py, the snapshot, graphify, pyproject.toml, manifest.py, ...) and
its whole value is that those pointers are TRUE. A registry whose pointers have rotted (an owner file
renamed, a symbol removed, a snapshot key the engine no longer publishes, a broken cross-link) is
worse than none: it asserts "the truth is over there" when it isn't.

This is the mechanical enforcement the registry itself calls for (Law 1 / the "correspondence rules"
of ISO/IEC/IEEE 42010 applied to the index): every owner the registry names must resolve to something
that actually exists, checked in CI. It bites the moment a refactor moves an owner without updating
the map. It is deliberately structural -- it asserts on stable anchors (paths, symbol names, snapshot
keys, cross-links), never on prose that legitimately changes.
"""
import functools
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "docs" / "ssot.md"
CONTRACT = ROOT / "docs" / "ssot-contract.md"
GRAPHIFY_IGNORE = ROOT / ".graphifyignore"


def _registry_text() -> str:
    assert REGISTRY.exists(), "docs/ssot.md (the project SSOT registry) is missing"
    return REGISTRY.read_text(encoding="utf-8")


def test_registry_exists_and_is_substantive():
    txt = _registry_text()
    assert len(txt) > 1500, "registry is suspiciously small -- likely truncated"
    # Its load-bearing sections must be present.
    for heading in ("The map", "live in two homes", "federation rule", "Adding a new source of truth"):
        assert heading in txt, f"registry is missing its '{heading}' section"


def test_registry_owner_files_all_exist():
    """Every owner FILE the registry leans on must resolve on disk."""
    # __init__.py holds __version__ but is referenced by SYMBOL, not filename (guarded below), so it
    # is existence-only; the rest must exist AND be cited by name (so dropping a row is caught too).
    must_exist = [
        "cisco_toolkit/ssot.py",
        "docs/ssot-contract.md",
        "cisco_toolkit/manifest.py",
        "cisco_toolkit/unknown_evidence.py",
        "cisco_toolkit/traffic_assurance.py",
        "CHANGELOG.md",
        "pyproject.toml",
        "cisco_toolkit/__init__.py",
        # the freshness guard: four registry rows cite it as their enforcement (2026-07-10)
        "tests/test_registry_freshness.py",
        # the DEC-007 holdout policy owner + its mechanics module (P1-2, 2026-07-10)
        "docs/quality/holdout-contract.md",
        "cisco_toolkit/holdout.py",
        # deliverable-set completeness: the row's enforcement IS this reconciler, so the row and
        # the guard have to fall together or not at all (2026-07-22)
        "tests/test_docmeta_cli_artifacts.py",
        # governed aggregate-only unknown-evidence owner + its privacy/totality reconciler
        "tests/test_unknown_evidence.py",
        "tests/test_traffic_assurance.py",
        "tests/test_traffic_assurance_excel.py",
        # Release 2.0 proof-carrying transition structural-contract owners.
        "cisco_toolkit/transition_contract.py",
        "cisco_toolkit/transition_pack.py",
        "cisco_toolkit/transition_verifier.py",
        "cisco_toolkit/transition_legacy.py",
        "cisco_toolkit/transition_dsl.py",
        "cisco_toolkit/transition_tcb_review.py",
        "cisco_toolkit/transition_runtime_closure.py",
        "cisco_toolkit/transition_runtime_discovery.py",
        "cisco_toolkit/_transition_runtime_debug.py",
        "cisco_toolkit/transition_workload_review.py",
        # Atlas Scope (tracked in this repository since 2026-09-26): the compiled-fabric row's one
        # compiler and run guide, and the /scope enforcement suites the fabric and digest rows cite.
        "atlas-scope/tools/lib/compile-model.mjs",
        "atlas-scope/tools/compile-all.mjs",
        "atlas-scope/README.md",
        "atlas-scope/contracts/engine-contract.v1.json",
        "webapp/tests/test_snapshot_raw.py",
        "webapp/tests/test_scope_mount.py",
    ]
    cited_by_name = [p for p in must_exist if not p.endswith("__init__.py")]
    txt = _registry_text()
    missing_on_disk = [p for p in must_exist if not (ROOT / p).exists()]
    assert not missing_on_disk, f"registry names owners that do not exist on disk: {missing_on_disk}"
    not_cited = [p for p in cited_by_name if p.rsplit("/", 1)[-1] not in txt]
    assert not not_cited, f"owner files exist but are not cited in the registry: {not_cited}"


#: Every backticked citation the registry roots at a top-level directory or FILE of THIS repository
#: (derived from the tree on disk and the top-level names git history renamed or deleted away -- not
#: a list of roots; _repository_roots) must resolve: a directory citation to a directory, a
#: file or glob to at least one file, and every `path :: symbol` pointer to a DEFINITION of that
#: symbol in that file (Python: a def, class or assignment read from the AST, or an SQL table the
#: module creates; other sources: a declaration, an exported name or an object key) -- never merely a
#: word that appears in a comment. A new row citing a renamed file or a vanished symbol fails here.
#:
#: Paths the registry cites that are not checked in BY DESIGN are admitted in exactly two ways:
#: git itself ignores them (derived: `git check-ignore`), or they are one of the run-time artefacts
#: below -- each still cited, and proven not tracked, so this list can only ever hold what really is
#: created at run time or lives outside the repository.
_RUNTIME_ARTIFACT_CITATIONS = {
    ".claude/.../memory/*.md": "machine-local Claude memory cache, outside the repository",
    "docs/engagement-state.json": "per-engagement gate ledger, created by the first approve under "
                                  "--gate-root",
    "docs/quality/holdout_access.jsonl": "append-only holdout access log, created on first read",
}
_CITATION = re.compile(r"^([A-Za-z0-9_.*/%-]+?)\s*(?:::\s*(.+))?$")
_SYMBOL = re.compile(r"^([A-Za-z_]\w*(?:(?:\.|::)[A-Za-z_]\w*)*)(?:\(.*\))?$")


def _python_definitions(source: str) -> set[str]:
    """Every name a Python module DEFINES -- functions, classes (qualified through their nesting),
    module/class/conditional-block assignments -- plus the SQL tables it creates."""
    import ast

    names: set[str] = set()

    def walk(node, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.update({child.name, prefix + child.name})
                walk(child, f"{prefix}{child.name}.")
            elif isinstance(child, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                targets = child.targets if isinstance(child, ast.Assign) else [child.target]
                for target in targets:
                    for leaf in ast.walk(target):
                        if isinstance(leaf, ast.Name):
                            names.update({leaf.id, prefix + leaf.id})
            elif isinstance(child, (ast.If, ast.Try, ast.With, ast.For, ast.While)):
                walk(child, prefix)
    walk(ast.parse(source), "")
    names.update(re.findall(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([A-Za-z_]\w*)", source,
                            re.IGNORECASE))
    return names


def _defines(path: pathlib.Path, symbol: str) -> bool:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".py":
        return symbol in _python_definitions(text)
    name = re.escape(symbol.rsplit(".", 1)[-1])
    # A line starting with `name(` is a definition only when it OPENS A BODY on that line (a method,
    # accessor or generator: `name(args) {`, `static async name(a): T {`); otherwise it is a call
    # (QF-V2-2). `name:` / `name =` at the start of a line stay definitions: an object or type key,
    # a class field, a TOML/INI/YAML key.
    return re.search(
        rf"\b(?:function\*?|class|const|let|var|interface|type|enum|def)\s+{name}\b"
        rf"|\bexport\s*\{{[^}}]*\b{name}\b|^[ \t]*(?:async\s+)?{name}\s*[:=]"
        rf"|^[ \t]*(?:(?:static|async|get|set|public|private|protected|override)\s+)*\*?{name}"
        rf"\s*(?:<[^>\n]*>)?\([^()\n]*\)\s*(?::\s*[^{{}};=\n]+)?\{{"
        rf"|[\"']{name}[\"']\s*:",
        text, re.MULTILINE) is not None


def _git_ignored(path: str) -> bool | None:
    """Whether git's ignore rules exclude ``path`` (None: git could not answer -- never 'ignored')."""
    import subprocess

    try:
        proc = subprocess.run(["git", "-C", str(ROOT), "check-ignore", "-q", "--no-index", path],
                              capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    return {0: True, 1: False}.get(proc.returncode)


@functools.lru_cache(maxsize=None)
def _repository_history(root: pathlib.Path = ROOT) -> tuple[frozenset[str], bool]:
    """(every top-level name git history shows was tracked and then deleted or renamed away, whether
    that history is COMPLETE). A shallow checkout -- actions/checkout's default fetch-depth 1 --
    holds no deletion at all, so its answer is declared incomplete rather than read as "nothing was
    ever renamed" (RQF-V1-1): absence of history is not evidence of absence."""
    import subprocess

    def git(*args: str) -> str:
        proc = subprocess.run(["git", "-c", "core.quotepath=off", "-C", str(root), *args],
                              capture_output=True, text=True, encoding="utf-8", timeout=120)
        assert proc.returncode == 0, f"git {args[0]} could not answer: {proc.stderr}"
        return proc.stdout

    shallow = git("rev-parse", "--is-shallow-repository").strip()
    assert shallow in ("true", "false"), f"git could not say whether the history is shallow: {shallow!r}"
    names = set()
    for path in git("log", "--format=", "--name-only", "-z", "--no-renames", "--diff-filter=D",
                    "HEAD").split("\0"):
        path = path.strip("\n")
        if path:
            head, separator, _rest = path.partition("/")
            names.add(head + ("/" if separator else ""))
    return frozenset(names), shallow == "false"


@functools.lru_cache(maxsize=None)
def _repository_roots(root: pathlib.Path = ROOT) -> frozenset[str]:
    """Every top-level entry a registry citation can be rooted at: each file and directory on disk
    (a directory spelt `name/`), plus every top-level name git history shows was tracked and then
    deleted or renamed away -- so a citation of a renamed owner is still checked (and fails)
    instead of silently falling out of scope with its name (QF-V2-2). On a shallow checkout the
    historical half is empty and _repository_history says so; the one test that depends on it
    declines visibly there. `.git` is git's own metadata (a directory in a checkout, a FILE in a
    linked worktree), never a repository path."""
    names = {entry.name + ("/" if entry.is_dir() else "") for entry in root.iterdir()}
    return frozenset((names | _repository_history(root)[0]) - {".git", ".git/"})


def _rooted(span: str) -> bool:
    """Whether a backticked span is a repository path: it starts at a top-level directory (`dir/`),
    or IS a top-level file, optionally followed by a ` :: symbol` or `:line` part."""
    return any(span.startswith(root) if root.endswith("/")
               else re.match(re.escape(root) + r"(?=$|\s|:)", span) is not None
               for root in _repository_roots())


_LINE_CITATION = re.compile(r"^[A-Za-z0-9_.*/%-]+:\d+(?:[/,-]\d+)*$")


def _line_citations(text: str) -> list[str]:
    """Every rooted `path:line` citation (test_no_registry_citation_pins_a_line_number)."""
    return [span.strip() for span in re.findall(r"`([^`\n]+)`", text)
            if _rooted(span.strip()) and _LINE_CITATION.match(span.strip())]


def _cited_source_problems(text: str) -> tuple[list[str], int]:
    problems, checked = [], 0
    for span in re.findall(r"`([^`\n]+)`", text):
        span = span.strip()
        if not _rooted(span) or _LINE_CITATION.match(span):
            continue  # a `path:line` citation is refused by its own test, never passed here
        match = _CITATION.match(span)
        if not match:
            problems.append(f"unreadable citation {span!r}")
            continue
        checked += 1
        path, symbols = match.groups()
        if path in _RUNTIME_ARTIFACT_CITATIONS:
            continue
        if path.endswith("/"):
            if not (ROOT / path).is_dir():
                problems.append(f"{path} is not a directory")
            continue
        found = [p for p in (sorted(ROOT.glob(path)) if "*" in path else [ROOT / path])
                 if p.is_file()]
        if not found:
            ignored = _git_ignored(path)
            if ignored is not True:
                problems.append(f"{path} does not exist" + (
                    " (git could not say whether it is ignored)" if ignored is None else ""))
            continue
        for raw in re.split(r"\s*/\s*", symbols or ""):
            if not raw:
                continue
            symbol = _SYMBOL.match(raw.strip())
            if symbol is None:
                problems.append(f"unreadable symbol {raw!r} in {span!r}")
            elif not any(_defines(p, symbol.group(1).replace("::", ".")) for p in found):
                problems.append(f"{path} defines no {symbol.group(1)}")
    return problems, checked


def test_every_cited_repository_path_and_symbol_resolves():
    problems, checked = _cited_source_problems(_registry_text())
    assert not problems, problems
    assert checked >= 300, checked


def test_the_citation_checker_bites_on_every_root_and_on_mentions_that_are_not_definitions(
        tmp_path):
    """QF-R1-3: the checker is not scoped to a hand-picked pair of roots, and a symbol that survives
    only as a word in a comment or docstring is reported as vanished."""
    doctored, checked = _cited_source_problems(
        "`atlas-scope/tools/lib/compile-model-renamed.mjs` `cisco_toolkit/ssot_renamed.py` "
        "`portable/atlas_bundle_renamed.py` `tools/no_such_tool.py` `webapp/no-such-dir/` "
        "`webapp/backend/app.py :: _no_such_scope_symbol` "
        "`cisco_toolkit/ssot.py :: reconcile / no_such_reconcile`")
    assert checked == 7 and len(doctored) == 7, doctored
    module = tmp_path / "owner.py"
    module.write_text('"""ghost is only mentioned here."""\n# ghost_too, in a comment\n'
                      "class Real:\n    def method(self):\n        return 'ghost'\n"
                      "CONSTANT = 1\nif True:\n    GUARDED = 2\n"
                      'SQL = "CREATE TABLE IF NOT EXISTS rows (id INTEGER)"\n', encoding="utf-8")
    for defined in ("Real", "Real.method", "CONSTANT", "GUARDED", "rows"):
        assert _defines(module, defined), defined
    for mentioned in ("ghost", "ghost_too", "method.Real"):
        assert not _defines(module, mentioned), mentioned
    script = tmp_path / "owner.mjs"
    script.write_text("// ghost lives in a comment\nexport function compileAll() {}\n"
                      "const OUTPUTS = [];\nexport { OUTPUTS };\n", encoding="utf-8")
    assert _defines(script, "compileAll") and _defines(script, "OUTPUTS")
    assert not _defines(script, "ghost")


def test_a_call_at_the_start_of_a_line_is_not_a_definition(tmp_path):
    """QF-V2-2: for a non-Python source, a line that starts with ``name(`` is a CALL unless it opens
    a method body -- ``compileAll(a);`` mentions compileAll, it does not define it."""
    calls = tmp_path / "calls.mjs"
    calls.write_text("import { compileAll, run } from './x.mjs';\ncompileAll(a);\n"
                     "  run(() => {\n  });\n  describeThing('x', () => {});\n", encoding="utf-8")
    for called in ("compileAll", "run", "describeThing"):
        assert not _defines(calls, called), called
    methods = tmp_path / "methods.ts"
    methods.write_text("class Owner {\n  compileAll(a: string): void {\n  }\n"
                       "  static async run(x) {\n  }\n  get size() { return 1; }\n}\n"
                       "const table = {\n  key: 1,\n  method(a) { return a; },\n};\n",
                       encoding="utf-8")
    for defined in ("compileAll", "run", "size", "key", "method"):
        assert _defines(methods, defined), defined


def test_citations_rooted_at_a_top_level_file_are_checked():
    """QF-V2-2: a top-level FILE is a root too (`COLLECT_PARSE_V3_23_0.py :: ...`,
    `pyproject.toml :: ...`, `AGENTS.md`, ...). Needs no history: it holds on a shallow checkout."""
    doctored, checked = _cited_source_problems(
        "`COLLECT_PARSE_V3_23_0.py :: _no_such_stage` `pyproject.toml :: no_such_key` "
        "`ollama_recall.py :: no_such_recall`")
    assert checked == 3 and len(doctored) == 3, doctored
    clean, checked = _cited_source_problems(
        "`COLLECT_PARSE_V3_23_0.py :: _stage_finalize` `pyproject.toml :: version` `AGENTS.md` "
        "`RELEASING.md` `CHANGELOG.md` `CLAUDE.md` `ollama_recall.py`")
    assert checked == 7 and not clean, clean
    # `.git` is git's own metadata (a directory in a checkout, a file in a linked worktree)
    assert ".git" not in _repository_roots()


def test_a_citation_of_a_top_level_name_the_repository_renamed_away_is_checked():
    """QF-V2-2: a top-level name the repository tracked and has since renamed or deleted is a root
    too -- a citation of it must fail, not fall out of scope because the name is no longer on disk.
    The historical roots are read from git, so this needs the history: on a shallow checkout
    (actions/checkout's default fetch-depth 1) it DECLINES VISIBLY instead of asserting a name only
    deep history holds (RQF-V1-1) -- and the whole-tree check there covers the disk roots only."""
    import pytest

    deleted, complete = _repository_history()
    if not complete:
        pytest.skip("shallow checkout: git holds no deleted top-level name here, so a citation of a "
                    "renamed-away owner cannot be told from prose (fetch the full history, e.g. "
                    "actions/checkout fetch-depth: 0, to run this half of the citation check)")
    assert "traffic-intents.example.json" in deleted and "traffic-intents.example.json" in \
        _repository_roots()
    assert not (ROOT / "traffic-intents.example.json").exists()
    doctored, checked = _cited_source_problems("`traffic-intents.example.json`")
    assert checked == 1 and doctored == ["traffic-intents.example.json does not exist"], doctored


def _ci_jobs(text: str) -> dict[str, str]:
    """ci.yml's jobs, each name to its block, read by indentation (two spaces under `jobs:`)."""
    body = text.split("\njobs:\n", 1)[1]
    jobs: dict[str, str] = {}
    name = None
    for line in body.splitlines():
        head = re.fullmatch(r"  ([A-Za-z0-9_-]+):\s*", line)
        if head:
            name = head.group(1)
            jobs[name] = ""
        elif name is not None:
            jobs[name] += line + "\n"
    return jobs


def _runs_the_default_suite(job: str) -> bool:
    """A job runs the whole default suite when some `python -m pytest` in it names no test path:
    every word after it (on its line, or on the folded lines that continue it) is an option."""
    lines = job.splitlines()
    for i, line in enumerate(lines):
        match = re.search(r"python -m pytest\b(.*)$", line)
        if not match:
            continue
        words = match.group(1).split()
        indent = len(line) - len(line.lstrip())
        for more in lines[i + 1:]:
            if not more.strip() or len(more) - len(more.lstrip()) != indent:
                break
            words += more.split()
        if all(w.startswith("-") for w in words):
            return True
    return False


def test_every_ci_leg_that_runs_the_default_suite_fetches_the_history_the_citation_check_needs():
    """RQF-V1-1: at actions/checkout's default depth 1 the renamed-away citation check above
    skips (visibly), so on that leg a registry citation of a renamed or deleted top-level owner is
    not caught. Every ci.yml job that runs the whole default suite -- found by what it runs, not by
    name -- checks out the full history."""
    jobs = _ci_jobs((ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    suite = sorted(name for name, job in jobs.items() if _runs_the_default_suite(job))
    assert {"test", "coverage"} <= set(suite), suite  # not vacuous: the two known full-suite legs
    shallow = []
    for name in suite:
        checkout = re.search(r"- uses: actions/checkout@\S+[^\n]*\n((?:\s{8,}\S[^\n]*\n)*)", jobs[name])
        assert checkout, f"{name} has no actions/checkout step"
        if not re.search(r"^\s+fetch-depth:\s*0\s*$", checkout.group(1), re.M):
            shallow.append(name)
    assert not shallow, f"these default-suite legs check out a shallow history: {shallow}"
    # The reader is not blind: a path-scoped run is not the default suite.
    assert not _runs_the_default_suite("      - run: python -m pytest webapp/tests -q\n")
    assert _runs_the_default_suite("        run: >-\n          python -m pytest\n          --cov=x\n")


def test_the_history_roots_are_gits_and_a_shallow_history_is_declared_incomplete(tmp_path):
    """RQF-V1-1, measured on a real repository and a real shallow clone of it: the full history
    names the top-level file it deleted, and the depth-1 clone -- which holds no deletion -- says
    its history is incomplete instead of answering "nothing was ever renamed"."""
    import subprocess

    def git(cwd, *args):
        proc = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                               "-c", "commit.gpgsign=false", *args], cwd=cwd, capture_output=True,
                              text=True, timeout=120)
        assert proc.returncode == 0, (args, proc.stderr)

    full = tmp_path / "full"
    full.mkdir()
    git(full, "init", "-q")
    (full / "kept.md").write_text("kept\n", encoding="utf-8")
    (full / "gone.json").write_text("{}\n", encoding="utf-8")
    (full / "pkg").mkdir()
    (full / "pkg" / "owner.py").write_text("X = 1\n", encoding="utf-8")
    git(full, "add", "-A")
    git(full, "commit", "-q", "-m", "one")
    git(full, "rm", "-q", "gone.json")
    git(full, "mv", "pkg", "moved")
    git(full, "commit", "-q", "-m", "two")
    assert _repository_history(full) == (frozenset({"gone.json", "pkg/"}), True)
    assert {"gone.json", "pkg/", "kept.md", "moved/"} <= _repository_roots(full)
    shallow = tmp_path / "shallow"
    git(tmp_path, "clone", "-q", "--depth", "1", full.as_uri(), str(shallow))
    assert _repository_history(shallow) == (frozenset(), False)
    assert "gone.json" not in _repository_roots(shallow)


def test_no_registry_citation_pins_a_line_number():
    """A `path:line` citation cannot be checked: the line moves on every edit above it, and nothing
    says what it should hold, so a bound check would pass a line that now holds something else.
    Measured: `COLLECT_PARSE_V3_23_0.py:2485/2624/2629` was meant to be where the engine publishes
    cable_map, architecture_coverage and coverage_matrix; line 2485 is now blank and they are
    assigned in `main` near 5178/5421/5426. A registry row cites the owning SYMBOL instead
    (`path :: name`), which the checker above resolves to a definition."""
    pinned = sorted(set(_line_citations(_registry_text())))
    assert not pinned, pinned
    assert _line_citations("`COLLECT_PARSE_V3_23_0.py:2485/2624/2629` `webapp/backend/app.py:12`") \
        == ["COLLECT_PARSE_V3_23_0.py:2485/2624/2629", "webapp/backend/app.py:12"]


def test_a_missing_citation_is_admitted_as_ignored_only_when_git_says_so(monkeypatch):
    """Absence is never admitted on silence: a cited path that is not on disk passes only when git
    positively reports it ignored — not when git says no, and not when git cannot answer."""
    import sys

    module = sys.modules[__name__]
    for answer, admitted in ((True, True), (False, False), (None, False)):
        monkeypatch.setattr(module, "_git_ignored", lambda _path, _answer=answer: _answer)
        problems, checked = _cited_source_problems("`docs/quality/query_log.jsonl`")
        assert checked == 1 and (not problems) is admitted, (answer, problems)
    monkeypatch.undo()
    assert _git_ignored("docs/quality/query_log.jsonl") is True  # what git itself answers here


def test_every_runtime_artifact_citation_is_cited_and_not_tracked():
    """The admitted run-time artefacts stay honest: each is still cited by the registry and git
    tracks nothing at that path (a tracked one belongs under the existence check instead)."""
    import subprocess

    text = _registry_text()
    for path in _RUNTIME_ARTIFACT_CITATIONS:
        assert f"`{path}`" in text, path
        proc = subprocess.run(["git", "-C", str(ROOT), "ls-files", "--", path],
                              capture_output=True, text=True, timeout=60)
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.strip() == "", (path, proc.stdout)


def test_registry_owner_symbols_are_real():
    """The symbols the registry leans on (the assessment-facts contract, the version, the ledger)
    must exist in the code it points at -- import them / read them, don't trust the prose."""
    from cisco_toolkit import detector_schema, manifest, parse, ssot, traffic_assurance, unknown_evidence
    import cisco_toolkit

    assert hasattr(ssot, "CANONICAL_FACTS") and isinstance(ssot.CANONICAL_FACTS, dict)
    assert hasattr(ssot, "canonical_facts") and callable(ssot.canonical_facts)
    assert hasattr(ssot, "reconcile") and callable(ssot.reconcile)
    # the coverage/provenance-schema owners (J3/J2/J1) the registry gained on 2026-07-05 must resolve too,
    # else a refactor that moved one without updating docs/ssot.md would slip past this guard.
    assert hasattr(ssot, "compute_schema_census") and callable(ssot.compute_schema_census)
    assert hasattr(ssot, "compute_fact_lineage") and callable(ssot.compute_fact_lineage)
    assert hasattr(detector_schema, "compute_detector_schema") and callable(detector_schema.compute_detector_schema)
    assert hasattr(unknown_evidence, "compute_unknown_evidence") and callable(unknown_evidence.compute_unknown_evidence)
    assert unknown_evidence.SCHEMA == "unknown_evidence/1"
    assert unknown_evidence.EVENT_SCHEMA == "unknown_evidence_event/1"
    assert callable(traffic_assurance.assess_flow) and callable(traffic_assurance.assess_flows)
    assert callable(traffic_assurance.build_traffic_evidence_custody)
    assert traffic_assurance.TRAFFIC_ASSURANCE_SET_SCHEMA == "traffic_assurance_set/1"
    assert traffic_assurance.TRAFFIC_EVIDENCE_CUSTODY_SCHEMA == "traffic_evidence_custody/1"
    assert parse.FORWARDING_GATE_SYNTAX_REGISTRY
    assert len({row.family for row in parse.FORWARDING_GATE_SYNTAX_REGISTRY}) == len(
        parse.FORWARDING_GATE_SYNTAX_REGISTRY
    )
    assert isinstance(getattr(cisco_toolkit, "__version__", None), str), "schema __version__ owner is gone"
    # manifest.py is the hash-chained chain-of-custody ledger the registry cites for run provenance.
    assert hasattr(manifest, "GENESIS"), "manifest.py no longer exposes the hash-chain GENESIS"


def test_registry_transition_contract_owners_are_real_and_bounded():
    """The R2.0 row resolves to its owners and retains its non-promotion boundaries."""
    from cisco_toolkit import (
        _transition_runtime_debug,
        transition_contract,
        transition_dsl,
        transition_legacy,
        transition_pack,
        transition_runtime_closure,
        transition_runtime_discovery,
        transition_tcb_review,
        transition_verifier,
        transition_workload_review,
    )

    expected = {
        transition_contract: (
            "bind_transition_case_bytes",
            "validate_transition_case",
            "validate_qualification_denominator",
        ),
        transition_pack: (
            "bind_pack_manifest_bytes",
            "bind_tcb_manifest_bytes",
            "verify_qualification_evidence",
            "qcp_001_must_remain_experimental",
        ),
        transition_runtime_closure: (
            "validate_transition_runtime_closure_evidence",
            "bind_transition_runtime_closure_evidence_bytes",
            "verify_transition_runtime_closure_review",
            "require_verified_transition_runtime_closure_review",
        ),
        transition_runtime_discovery: (
            "RuntimeClosureDiscoverySubject",
            "CapturedIncompleteRuntimeClosureEvidence",
            "validate_windows_runtime_discovery_trace",
            "validate_windows_debug_runtime_discovery_trace",
            "validate_windows_debug_runtime_discovery_v3_trace",
            "validate_windows_debug_execution_environment_manifest",
            "validate_windows_debug_execution_environment_v3_manifest",
            "capture_windows_runtime_closure_incomplete",
            "capture_windows_debug_runtime_closure_incomplete",
            "capture_windows_debug_runtime_closure_v3_incomplete",
        ),
        _transition_runtime_debug: (
            "DebugEventCapture",
            "DebugEventRecord",
            "WindowsDebugEventSession",
        ),
        transition_verifier: (
            "verify_transition_case",
            "map_authoritative_gate",
            "compute_invalidation_receipt",
        ),
        transition_legacy: (
            "verify_release1_semantic_bundle",
            "adapt_release1_comparison_bytes",
            "replay_release1_comparison_bytes",
        ),
        transition_dsl: (
            "bind_packaged_dsl_prototype_bytes",
            "run_bound_pack_abi",
        ),
        transition_tcb_review: (
            "verify_tcb_budget_review_evidence",
        ),
        transition_workload_review: (
            "bind_transition_workload_evidence_bytes",
            "verify_transition_workload_review",
            "require_verified_transition_workload_review",
        ),
    }
    for module, names in expected.items():
        for name in names:
            assert callable(getattr(module, name, None)), f"{module.__name__}.{name} owner is missing"

    row = next(
        line
        for line in _registry_text().splitlines()
        if "Proof-carrying transition structural contract" in line
    )
    assets = (
        "cisco_toolkit/schemas/atlas-transition-contract-v1.schema.json",
        "cisco_toolkit/schemas/atlas-r2-structural-tcb-census-v1.schema.json",
        "cisco_toolkit/data/qcp-001.experimental.json",
        "cisco_toolkit/data/atlas-r2-structural-tcb-census.v1.json",
        "cisco_toolkit/data/atlas-r2-dsl-prototype-denominator.v1.json",
        "cisco_toolkit/data/atlas-r2-dsl-prototype-input.v1.json",
        "cisco_toolkit/data/atlas-r2-dsl-prototype-pack.experimental.json",
        "cisco_toolkit/data/atlas-r2-dsl-prototype-program.v1.json",
        "cisco_toolkit/data/atlas-r2-dsl-prototype-tcb.v2.json",
        "cisco_toolkit/data/atlas-r2-dsl-prototype-measurements.v1.json",
        "cisco_toolkit/schemas/atlas-r2-execution-evidence-v1.schema.json",
        "cisco_toolkit/schemas/atlas-r2-transition-runtime-closure-v2.schema.json",
        "cisco_toolkit/schemas/atlas-r2-transition-workload-review-v1.schema.json",
        "cisco_toolkit/data/atlas-r1-executable-bundle.json",
        "cisco_toolkit/data/atlas-r1-source-bundle.json",
        "cisco_toolkit/data/atlas-r1-retrospective-before.json",
        "cisco_toolkit/data/atlas-r1-retrospective-after.json",
        "cisco_toolkit/data/atlas-r1-retrospective-comparison.json",
    )
    for relative in assets:
        assert (ROOT / relative).is_file(), f"R2.0 SSOT asset is missing: {relative}"
        assert relative.rsplit("/", 1)[-1] in row, f"R2.0 SSOT row does not cite {relative}"

    for boundary in (
        "closed three-state vocabularies",
        "closed four-state vocabularies",
        "EXPERIMENTAL",
        "CONTRACT_ONLY",
        "REFERENCE_NOT_REWRITE",
        "AUDIT_ONLY",
        "null Release 2 gate",
        "no authenticated historical fixture",
        "same-checkout self-check only",
        "cannot execute QCP-001",
        "not a Wasm runtime",
        "sandbox claim",
        "PARTIAL_NONPORTABLE_PROTOTYPE",
        "COMPLETE_EXACT_RUNTIME_CLOSURE",
        "runtime-closure `/2` module and schema are protocol structure only",
        "Windows live discovery emits only non-authoritative `COLLECTED_INCOMPLETE` evidence",
        "no closure-capable collector, capture corpus, or authority",
        "No trust policy, reviewer key, signature, or signed closure-review receipt is bundled",
        "do not change the runtime-inventory `/1` roster",
        "freeze `/1` remains unchanged and blocked",
        "Representative-workload evidence is non-authoritative",
        "evidence state is never `ADEQUATE`",
        "No representative-workload corpus, reviewer key, trust policy, or signed review receipt is bundled",
        "existing freeze `/1` remains explicitly blocked",
        "does not make runtime inventory `COMPLETE`",
        "qualify a pack",
        "authorize promotion",
        "budgets, reviewed resource ceilings, independent review evidence, and selected commit remain pending/null",
        "No R2.1+ or Release 3 capability",
    ):
        assert boundary in row, f"R2.0 SSOT row lost boundary {boundary!r}"

    registry = " ".join(
        line.lstrip("> ").strip() for line in _registry_text().splitlines()
    )
    for runtime_closure_authority_boundary in (
        "review signature authenticates the canonical receipt, not its trust policy",
        "Every authority use must obtain the current canonical policy bytes",
        "digest argument proves only exact equality to the caller's selection",
        "cannot establish external selection",
        "policy issuer/namespace/succession",
        "reviewer-key identity/custody",
        "trusted time",
        "global freshness or anti-rollback",
        "artifact semantic truth",
        "real-world capture completeness",
        "Any authority gate must consume only that fresh return value",
        "independently compare and bind its `bindings_digest`, `policy_digest`, and `evaluated_at`",
        "gate-selected commit/tree, evidence digest and states, and mapped evidence digests",
        "a retained `.complete` value is historical state, not authority",
        "No such current policy, key, signature, or receipt is bundled",
    ):
        assert runtime_closure_authority_boundary in registry

    for workload_authority_boundary in (
        "workload-review `/1` signature authenticates the canonical receipt, not its replaceable trust policy",
        "current canonical workload-policy bytes and exact digest",
        "call `require_verified_transition_workload_review` again",
        "rejects an evaluation-time rollback",
        "current key authorization, subject authorization, receipt lifetime, and revocation",
        "cannot authenticate policy selection, succession, custody, trusted time, global anti-rollback",
        "must use only the fresh return value",
        "Retained `.adequate` is historical state, not authority",
        "No current workload policy, key, signature, receipt, or representative-workload corpus is bundled",
    ):
        assert workload_authority_boundary in registry

    for tcb_budget_authority_boundary in (
        "budget-review `/2` signature authenticates its canonical receipt, not the replaceable trust policy",
        "does not by itself make the signed budget decision current authority",
        "current canonical TCB-budget policy bytes and exact digest",
        "call `require_verified_tcb_budget_review` again",
        "rejects an evaluation-time rollback",
        "current key authorization, source-subject authorization, receipt lifetime, and revocation",
        "cannot authenticate policy selection, namespace or succession, custody, trusted time, global anti-rollback",
        "must use only the fresh return value",
        "serialized freeze retains the decision-time `review_trust_policy_digest`",
        "separately held current review is ephemeral authorization",
        "must never rewrite those historical bytes",
        "No current TCB-budget policy, key, signature, receipt, independently approved budget, or positive freeze is bundled",
    ):
        assert tcb_budget_authority_boundary in registry


def test_registry_windows_debug_v3_row_is_distinct_target_only_and_nonpromoting():
    lines = _registry_text().splitlines()
    v2 = next(
        line
        for line in lines
        if "Release 2.0 Windows debug-event capture tranche" in line
    )
    v3 = next(
        line
        for line in lines
        if "Release 2.0 Windows target-endpoint reconciliation tranche" in line
    )

    assert v2 != v3
    assert "(`/2`, incomplete only)" in v2
    assert "(`/3`, incomplete only)" in v3
    assert "capture_windows_debug_runtime_closure_incomplete" in v2
    assert "capture_windows_debug_runtime_closure_v3_incomplete" in v3

    v2_assets = (
        "atlas-r2-windows-debug-runtime-discovery-v2.schema.json",
        "atlas-r2-windows-execution-environment-manifest-v2.schema.json",
    )
    v3_assets = (
        "cisco_toolkit/schemas/atlas-r2-windows-debug-runtime-discovery-v3.schema.json",
        "cisco_toolkit/schemas/atlas-r2-windows-execution-environment-manifest-v3.schema.json",
    )
    for basename in v2_assets:
        assert basename in v2
        assert basename not in v3
    for relative in v3_assets:
        assert (ROOT / relative).is_file(), f"R2.0 /3 SSOT asset is missing: {relative}"
        basename = relative.rsplit("/", 1)[-1]
        assert basename in v3
        assert basename not in v2

    for unchanged_v2_boundary in (
        "deliberately incomplete image-event observation",
        "event-stream continuity, start/end reconciliation",
        "OS loss counters remain null",
    ):
        assert unchanged_v2_boundary in v2

    for v3_boundary in (
        "sealed 12-artifact `/3` envelope",
        "target_start_end_snapshot_reconciled=true",
        "collector_sequence_kind=LOCAL_APPEND_ORDINAL",
        "collector_ledger_contiguous=true",
        "collector_sequence_gap_count=0",
        "event_stream_contiguous=false",
        "start_end_snapshot_reconciled=false",
        "os_event_sequence_available=false",
        "os_loss_counter_available=false",
        "OS/global loss counters remain null",
        "Endpoint equality cannot detect an omitted balanced load/unload pair",
        "Later target teardown image activity remains serialized and debug-projected but is outside END checkpoint reconciliation",
        "`LOAD_LIBRARY_AS_DATAFILE`",
        "Only `process_tree_captured_before_first_instruction_through_final_descendant` and `execution_environment_argv_cwd_and_inputs_bound` may be true",
        "Runtime inventory `/1` remains `PARTIAL_NONPORTABLE_PROTOTYPE`",
        "`/2` remains unchanged",
        "No budget, authority, signature, qualification, promotion, R2.1+, or Release 3 effect",
    ):
        assert v3_boundary in v3


def test_registry_windows_debug_v4_row_binds_only_stable_on_disk_bytes_and_stays_nonpromoting():
    lines = _registry_text().splitlines()
    v3 = next(
        line
        for line in lines
        if "Release 2.0 Windows target-endpoint reconciliation tranche" in line
    )
    v4 = next(
        line
        for line in lines
        if "Release 2.0 Windows debug-file identity/on-disk-byte tranche" in line
    )

    assert v3 != v4
    assert "(`/3`, incomplete only)" in v3
    assert "(`/4`, incomplete only)" in v4
    assert "capture_windows_debug_runtime_closure_v4_incomplete" in v4
    assert "validate_windows_debug_runtime_discovery_v4_trace" in v4
    assert "validate_windows_debug_execution_environment_v4_manifest" in v4

    v4_assets = (
        "cisco_toolkit/schemas/atlas-r2-windows-debug-runtime-discovery-v4.schema.json",
        "cisco_toolkit/schemas/atlas-r2-windows-execution-environment-manifest-v4.schema.json",
    )
    for relative in v4_assets:
        assert (ROOT / relative).is_file(), f"R2.0 /4 SSOT asset is missing: {relative}"
        basename = relative.rsplit("/", 1)[-1]
        assert basename in v4
        assert basename not in v3

    for v4_boundary in (
        "sealed 13-artifact `/4` envelope",
        "borrowed debug-event image-handle trace",
        "fixed capture fails closed unless every received CREATE_PROCESS or LOAD_DLL image row supplies a non-null debug-event `hFile`",
        "joins one-to-one by source debug sequence and mapping tokens",
        "borrows but never closes, retains, or transfers that handle",
        "`FILE_ID_INFO`",
        "exactly two equal SHA-256 whole-file reads from offset zero through that same handle",
        "Raw paths and filenames are not disclosed",
        "File identifiers are machine-local and can be reused over time",
        "protective guards only, never approved budgets",
        "stable handle-addressed **on-disk** bytes only",
        "does not prove mapped or loaded memory bytes",
        "Debug-event image handles can be null outside this fail-closed fixed capture",
        "persistent_file_identity_and_loaded_bytes_bound=false",
        "mapped_or_loaded_memory_bytes_bound=false",
        "event_stream_contiguous=false",
        "start_end_snapshot_reconciled=false",
        "Only `process_tree_captured_before_first_instruction_through_final_descendant` and `execution_environment_argv_cwd_and_inputs_bound` may be true",
        "Runtime inventory `/1` remains `PARTIAL_NONPORTABLE_PROTOTYPE`",
        "`/2` and `/3` remain unchanged",
        "No budget, authority, signature, qualification, promotion, R2.1+, or Release 3 effect",
    ):
        assert v4_boundary in v4


def test_registry_windows_debug_v5_row_scopes_event_coincident_memory_and_stays_nonpromoting():
    lines = _registry_text().splitlines()
    v4 = next(
        line
        for line in lines
        if "Release 2.0 Windows debug-file identity/on-disk-byte tranche" in line
    )
    v5 = next(
        line
        for line in lines
        if "Release 2.0 Windows event-coincident mapped-image-byte tranche" in line
    )

    assert v4 != v5
    assert "(`/4`, incomplete only)" in v4
    assert "(`/5`, incomplete only)" in v5
    assert "capture_windows_debug_runtime_closure_v5_incomplete" in v5
    assert "validate_windows_debug_runtime_discovery_v5_trace" in v5
    assert "validate_windows_debug_execution_environment_v5_manifest" in v5

    v5_assets = (
        "cisco_toolkit/schemas/atlas-r2-windows-debug-runtime-discovery-v5.schema.json",
        "cisco_toolkit/schemas/atlas-r2-windows-execution-environment-manifest-v5.schema.json",
    )
    for relative in v5_assets:
        assert (ROOT / relative).is_file(), f"R2.0 /5 SSOT asset is missing: {relative}"
        basename = relative.rsplit("/", 1)[-1]
        assert basename in v5
        assert basename not in v4

    for v5_boundary in (
        "sealed 13-artifact `/5` envelope",
        "fresh non-inheritable least-privilege query/read duplicate",
        "retained CREATE_PROCESS debug-event `hProcess` for that process",
        "closes the duplicate and event-owned file handle before `ContinueDebugEvent`",
        "walks exactly `[mapping_base, mapping_base + SizeOfImage)` twice",
        "Each pass must independently form",
        "contiguous same-allocation-base partition",
        "`MEM_COMMIT` + `MEM_IMAGE`",
        "every `ReadProcessMemory` call must return its exact requested bytes",
        "equal whole-span SHA-256 digests and equal retained PE-header prefixes",
        "topology, protection, and per-region digest stability are not claimed",
        "No raw path, filename, process handle, or runtime address is serialized",
        "512 memory regions per image read pass, 16,384 total emitted memory regions across both passes",
        "protective guards only, never approved budgets",
        "mapped_or_loaded_memory_bytes_bound=true",
        "event_coincident_mem_image_bytes_bound=true",
        "received image event at its suspended pre-continue instant",
        "persistent_file_identity_and_loaded_bytes_bound=false",
        "runtime-closure envelope does not gain a broad loaded-byte closure bit",
        "not disk/memory byte equality",
        "point reads do not prove allocation exhaustion, lifetime immutability, or complete mapping history",
        "manual/anonymous mappings",
        "Only `process_tree_captured_before_first_instruction_through_final_descendant` and `execution_environment_argv_cwd_and_inputs_bound` may be true",
        "Runtime inventory `/1` remains `PARTIAL_NONPORTABLE_PROTOTYPE`",
        "`/2`, `/3`, and `/4` remain unchanged",
        "No budget, authority, signature, qualification, promotion, R2.1+, or Release 3 effect",
    ):
        assert v5_boundary in v5


def test_registry_cited_snapshot_keys_are_published_by_the_engine():
    """The snapshot blocks the registry names as owners must be assigned by the engine source.
    Source-level guard (the blocks don't exist on every historical snapshot; the CONTRACT is the
    assignment in the producer). Matches the repo's existing source-grep guard pattern."""
    txt = _registry_text()
    engine = (ROOT / "COLLECT_PARSE_V3_23_0.py").read_text(encoding="utf-8", errors="ignore")
    analyze = (ROOT / "cisco_toolkit" / "analyze.py").read_text(encoding="utf-8", errors="ignore")
    src = engine + "\n" + analyze
    for key in ("architecture_coverage", "cable_map", "coverage_matrix", "unknown_evidence", "design_blueprint",
                "traffic_assurance", "traffic_evidence_custody", "schema_census", "fact_lineage",
                "detector_schema"):
        assert key in txt, f"registry stopped citing the {key!r} owner path"
        assigned = re.search(rf'["\']{re.escape(key)}["\']\]\s*=', src)
        assert assigned, f"registry cites snap[{key!r}] but the engine source never assigns it"


def test_registry_and_contract_are_cross_linked_both_ways():
    """The umbrella registry and the assessment-facts contract must point at each other, so neither
    is orphaned when one moves (Law 1 -- one consistent structure)."""
    reg = _registry_text()
    con = CONTRACT.read_text(encoding="utf-8")
    assert "ssot-contract.md" in reg, "registry does not link down to the assessment-facts contract"
    assert "ssot.md" in con, "the assessment-facts contract does not link up to the umbrella registry"


def test_registry_names_the_core_federated_owners():
    """Coverage guard: the registry must still name each core domain owner token, so a future edit
    that silently drops a domain from the map is caught."""
    txt = _registry_text()
    for token in ("ssot.py", "graphify", "pyproject.toml", "__version__", "CHANGELOG.md",
                  "manifest.py", "AGENTS.md", "learnings.md", "CLAUDE.md"):
        assert token in txt, f"registry no longer names the '{token}' owner"


def test_arch_coverage_cached_counts_match_registry():
    """Reconcile guard for the architecture-coverage headline. The docs cache the fact ("N ...
    architecture-class detectors across M classes"); the in-code registry
    (`design_advisor._ARCH_COVERAGE_REGISTRY`) owns it. A cached count that drifts from its owner is
    the exact rot Law 1 exists to prevent — caught live 2026-07-10, when both docs still said 40/23
    while the registry held 46 probe-ids across 27 class axes. Asserts every doc that states the
    headline states the registry's numbers, and that the headline is still present at all (dropping
    the phrase entirely would silently retire this guard)."""
    from cisco_toolkit.design_advisor import _ARCH_COVERAGE_REGISTRY as reg
    detectors = sum(len(pids) for _axis, _label, _channel, pids in reg)
    classes = len({axis for axis, *_rest in reg})
    headline = re.compile(
        r"(\d+)\s+(?:coverage-honest\s+)?architecture-class\s+detectors\s+across\s+(\d+)\s+classes")
    for doc in (ROOT / "CLAUDE.md", ROOT / "docs" / "universal-architecture-coverage.md"):
        txt = doc.read_text(encoding="utf-8")
        hits = headline.findall(txt)
        assert hits, f"{doc.name} no longer states the coverage headline — reconcile it or update this guard"
        for n, m in hits:
            assert (int(n), int(m)) == (detectors, classes), (
                f"{doc.name} caches {n} detectors / {m} classes but the registry "
                f"(design_advisor._ARCH_COVERAGE_REGISTRY) holds {detectors} / {classes} — "
                "update the doc from the owner (a copy is a cache and must match)")


# --- Side engagements ---------------------------------------------------------------------------
#
# The pushable registry records fictional aliases and the ownership boundary, never real client
# names or owner-machine paths. The private inventory is the authority for resolving those aliases.

SIDE_ENGAGEMENT_ALIASES = [
    "Reference_DC_Design",
    "Reference_CCTV_PS_Proposal",
]


def test_side_engagement_row_cites_only_public_aliases():
    """The public registry retains ownership without publishing private on-disk pointers."""
    txt = _registry_text()
    not_cited = [alias for alias in SIDE_ENGAGEMENT_ALIASES if alias not in txt]
    assert not_cited == [], f"'Side engagements' row no longer cites: {not_cited}"


def test_side_engagement_row_omits_owner_machine_paths():
    row = next(
        line for line in _registry_text().splitlines()
        if "Side engagements" in line
    )
    assert "private inventory" in row
    assert not re.search(r"[A-Za-z]:[\\/]", row)


def test_graphify_ignore_uses_a_generic_private_engagement_pattern():
    txt = GRAPHIFY_IGNORE.read_text(encoding="utf-8")
    assert "*_DC_Design/" in txt


def test_graphify_ignore_excludes_registered_codex_worktrees():
    """Linked Codex worktrees are full repository copies, never graph corpus members."""
    txt = GRAPHIFY_IGNORE.read_text(encoding="utf-8")
    assert ".codex-worktrees/" in txt


# --------------------------------------------------------- the reconcile guard must cover EVERY band
def test_every_lifecycle_band_the_producer_emits_has_a_raw_basis_guard():
    """`ssot._LIFECYCLE_BANDS` is the map from summary field -> the band reconcile() re-derives from
    `lifecycle_risk.per_device`. It listed four of the producer's FIVE bands; "Unknown" was missing.

    That omission was the worst possible one: `n_unknown` IS a registered CANONICAL_FACT, so it is
    published, cited and rendered as a headline -- but with no entry here it had NO raw-basis guard
    at all. The one canonical fact whose entire job is to say "not determined" was the only lifecycle
    fact nothing verified.

    This asserts COMPLETENESS against the producer's own vocabulary rather than a hand-kept list, so
    a new band added upstream cannot land here unguarded.
    """
    from cisco_toolkit import ssot
    from cisco_toolkit.analyze import _LIFECYCLE_BAND_RANK
    guarded = set(ssot._LIFECYCLE_BANDS.values())
    produced = set(_LIFECYCLE_BAND_RANK)
    assert produced - guarded == set(), (
        f"lifecycle band(s) with no reconcile guard: {sorted(produced - guarded)}")
    assert guarded - produced == set(), (
        f"reconcile guards a band the producer cannot emit: {sorted(guarded - produced)}")
    # every guarded field must also be a canonical fact or the guard has no published value to check
    assert "n_unknown" in ssot.CANONICAL_FACTS
    unknown_description = ssot.CANONICAL_FACTS["n_unknown"][1]
    assert "no exact EoX row matched" in unknown_description
    assert "source/date authority was withheld" in unknown_description


def _lc_snapshot(**summary):
    return {"lifecycle_risk": {"summary": dict(n_devices=3, **summary),
                               "per_device": [{"host": "a", "band": "Past-LDoS"},
                                              {"host": "b", "band": "Unknown"},
                                              {"host": "c", "band": "Unknown"}]}}


def test_reconcile_catches_a_falsified_n_unknown():
    """Measured before the fix: mutating summary.n_unknown from 2 to 99 returned reconcile() == []
    (silently accepted) while the same mutation to n_past_ldos was caught."""
    from cisco_toolkit import ssot
    assert ssot.reconcile(_lc_snapshot(n_past_ldos=1, n_unknown=2)) == [], "the truthful snapshot must be clean"
    v = ssot.reconcile(_lc_snapshot(n_past_ldos=1, n_unknown=99))
    assert v and any("n_unknown" in s for s in v), f"a falsified n_unknown was accepted: {v}"
    # NON-VACUITY: the sibling guard still works and the truthful case still passes, so this is not
    # an always-fire check.
    v2 = ssot.reconcile(_lc_snapshot(n_past_ldos=99, n_unknown=2))
    assert v2 and any("n_past_ldos" in s for s in v2), v2
