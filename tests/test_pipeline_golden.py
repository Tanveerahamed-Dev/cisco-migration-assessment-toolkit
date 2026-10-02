"""End-to-end regression test: run the real offline pipeline and assert the
JSON snapshot (the HTML explorer's contract) and the Excel sheet-name/header
schema are unchanged.

The snapshot is the single most important stability contract in the repo, so we
freeze it as a golden file. To intentionally update the goldens after a
reviewed change:

    UPDATE_GOLDEN=1 python -m pytest tests/test_pipeline_golden.py

Harness guarantees (pinned by tests/test_golden_guard.py — Plan A / Move-0.1):
- a MISSING golden FAILS (it is a broken contract, never a fresh baseline);
- UPDATE_GOLDEN=1 refuses to SHRINK the contract vs the git-HEAD baseline
  (removed snapshot sections / sheets / header cells) unless the removal is
  made explicit with ALLOW_GOLDEN_SHRINK=1.

Determinism: we run with --workers 1 (sequential), give the synthetic collection
a fixed collection timestamp (the lifecycle assessment boundary), pin the data-authority
registries' freshness clock to that same evidence date (_GOLDEN_REGISTRY_CLOCK), and strip
the remaining wall-clock stamps (`generated_at`, ...) before comparing. The golden has no
calendar boundary: test_golden_does_not_depend_on_the_wall_clock_past_every_registry_window
re-runs it with the whole process clock past every registry's freshness window.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook

import synthetic_fixtures as fx
from cisco_toolkit.analyze import DOSSIER_AXIS_INPUTS
from cisco_toolkit.multichassis_lag import validate_multichassis_lag_domain_baseline

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "COLLECT_PARSE_V3_23_0.py")
GOLDEN_DIR = os.path.join(ROOT, "tests", "golden")
_GOLDEN_COLLECTION_STAMP = "20260807_000000"
# The golden's EVIDENCE instant, and the one clock the golden pins besides the collection stamp: the retained
# data-authority registries' freshness clock. `data_authorities` is the pipeline's statement of the tool's
# registry health TODAY -- legitimately wall-clock product behaviour, and the engine keeps it so. But a golden
# frozen at whatever day it was last regenerated is a calendar alarm: from the day the first retained registry
# passes registry_integrity.SOURCE_MAX_AGE_DAYS, that verdict turns stale and it CASCADES far beyond
# data_authorities -- measured by running the pipeline 30 days past the windows (see
# test_golden_does_not_depend_on_the_wall_clock_past_every_registry_window): every authority's status /
# authoritative / integrity / error / record-count fields, a new `assessment_integrity` block naming the three
# authority phases as failed, the `schema_census` counting it, `service_map`'s per-service authority flags,
# and a new 'Assessment Integrity' workbook sheet. So normalising only the NOW-RELATIVE fields -- the five
# registry_integrity.source_freshness derives from "now": source_age_days (now - retrieval), source_fresh,
# source_stale, source_future_dated and freshness_status -- cannot make the golden date-independent (measured:
# with exactly those five stripped, a run past the windows still differs in four snapshot sections and one
# sheet), and normalising their effects field by field would be a hand-kept list standing in for its cause (and
# would stop freezing the trust verdict itself). The cause is ONE clock, so the golden pins it -- registry
# health as-of the golden's evidence date, exactly as the lifecycle bands are classified as-of that date -- and
# NO data_authorities field is normalised: each of those five is a pure function of the pin and stays frozen.
# What the pipeline publishes when a registry is fresh, exactly on its boundary, and stale (and what a registry
# publishes when future-dated) is proven with an injected clock in tests/test_eol_registry_freshness_clock.py;
# test_golden_registry_clock_is_inside_every_published_registry_window names the one event that moves the pin.
_GOLDEN_EVIDENCE_DATE = f"{_GOLDEN_COLLECTION_STAMP[0:4]}-{_GOLDEN_COLLECTION_STAMP[4:6]}-{_GOLDEN_COLLECTION_STAMP[6:8]}"
_GOLDEN_REGISTRY_CLOCK = f"{_GOLDEN_EVIDENCE_DATE}T00:00:00+00:00"
_GOLDEN_CLOCKS = {"registry_clock": _GOLDEN_REGISTRY_CLOCK}


def _make_template(path):
    """Minimal template workbook: the loader only needs a header row containing
    hostname/port/status; the script appends the rest of the columns itself."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Interface Data"
    ws.append(["Hostname", "Port", "Status"])
    wb.save(path)


def test_synthetic_collection_bytes_are_platform_stable(tmp_path):
    """Strict owner digests must not depend on the OS that writes the fixture."""
    collection = Path(fx.write_collection(str(tmp_path / "collection")))
    raw = (collection / "access1" / fx.cmd_filename("show running-config")).read_bytes()
    assert b"\n" in raw
    assert b"\r\n" not in raw


# The pipeline door with its clocks under test control. `python -c` this bootstrap, then the script's own
# argv: it runs COLLECT_PARSE exactly as `python COLLECT_PARSE_V3_23_0.py ...` does (run as __main__, the
# script's directory first on sys.path, so its `sys.exit(main())` exit code is the process exit code), after
# optionally
#   * WALL (argv[1], ISO-8601 with offset, "" = real): moving the WHOLE process wall clock -- datetime.now /
#     utcnow / today, date.today and time.time -- to start at WALL and advance in real time. This is how a
#     test observes what the pipeline does on a future day without waiting for it;
#   * REGISTRY (argv[2], ISO-8601 with offset, "" = real): pinning the one clock the retained data-authority
#     registries judge their freshness by. Every registry freshness read goes through
#     `registry_integrity.source_freshness`, which reads `registry_integrity.datetime.now` (the seam the
#     in-process tests below and tests/test_eol_registry_freshness_clock.py also use, and which that file
#     proves is the only clock the registries read).
_CLOCK_BOOTSTRAP = r"""
import datetime as _dtm, os, runpy, sys, time as _time
_wall, _registry, _script = sys.argv[1], sys.argv[2], sys.argv[3]
sys.argv = sys.argv[3:]
sys.path.insert(0, os.path.dirname(os.path.abspath(_script)))
if _wall:
    _real_dt, _real_date, _real_time = _dtm.datetime, _dtm.date, _time.time
    _offset = _real_dt.fromisoformat(_wall) - _real_dt.now(_dtm.timezone.utc)
    class _DateMeta(type):
        def __instancecheck__(cls, obj):
            return isinstance(obj, _real_date)
    class _DatetimeMeta(type):
        def __instancecheck__(cls, obj):
            return isinstance(obj, _real_dt)
    class _Date(_real_date, metaclass=_DateMeta):
        @classmethod
        def today(cls):
            return (_real_dt.now() + _offset).date()
    class _Datetime(_real_dt, metaclass=_DatetimeMeta):
        @classmethod
        def now(cls, tz=None):
            return _real_dt.now(tz) + _offset
        @classmethod
        def utcnow(cls):
            return _real_dt.utcnow() + _offset
        @classmethod
        def today(cls):
            return _real_dt.today() + _offset
    _dtm.datetime, _dtm.date = _Datetime, _Date
    _time.time = lambda: _real_time() + _offset.total_seconds()
if _registry:
    from cisco_toolkit import registry_integrity as _ri
    _pinned = _ri.datetime.fromisoformat(_registry)
    class _RegistryClock(_ri.datetime):
        @classmethod
        def now(cls, tz=None):
            return _pinned if tz is None else _pinned.astimezone(tz)
    _ri.datetime = _RegistryClock
runpy.run_path(_script, run_name="__main__")
"""


def _run_pipeline(tmp_path, out_xlsx=None, extra_args=None, *, registry_clock=None, wall_clock=None):
    """Run the real offline pipeline. `registry_clock` / `wall_clock` (ISO-8601 with an offset) pin the
    data-authority registries' freshness clock / move the whole process clock -- see _CLOCK_BOOTSTRAP. With
    neither, the plain `python COLLECT_PARSE_V3_23_0.py` door runs, untouched."""
    # The collection-dir stamp is the pipeline's authoritative lifecycle `asof`. A plain temporary
    # directory falls back to member mtimes, so lifecycle-derived punch-list/compound-risk rows drift
    # as the test date crosses a retained LDoS. Pin the evidence date, not just the sections stripped
    # below, because those sections have legitimate downstream consumers that remain in the golden.
    collection = fx.write_collection(str(tmp_path / _GOLDEN_COLLECTION_STAMP))
    devices = tmp_path / "devices.json"
    devices.write_text(json.dumps(fx.DEVICES), encoding="utf-8")
    template = tmp_path / "template.xlsx"
    _make_template(str(template))
    if out_xlsx is None:
        out_xlsx = tmp_path / "out.xlsx"

    argv = ["--no-collect", "--collection-dir", collection,
            "--devices-file", str(devices), "--template", str(template),
            "--output", str(out_xlsx), "--no-html", "--workers", "1"]
    if extra_args:
        argv += list(extra_args)
    if registry_clock or wall_clock:
        cmd = [sys.executable, "-c", _CLOCK_BOOTSTRAP, wall_clock or "", registry_clock or "", SCRIPT, *argv]
    else:
        cmd = [sys.executable, SCRIPT, *argv]
    proc = subprocess.run(cmd, cwd=str(tmp_path), capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, f"pipeline failed:\nSTDOUT\n{proc.stdout}\nSTDERR\n{proc.stderr}"
    snap_path = os.path.splitext(str(out_xlsx))[0] + ".snapshot.json"
    assert os.path.isfile(snap_path), "snapshot.json was not produced"
    with open(snap_path, encoding="utf-8") as f:
        snap = json.load(f)
    snap.pop("generated_at", None)            # volatile: wall-clock timestamp
    # data_authorities: every field is KEPT when the registry clock is pinned (the golden run -- see
    # _GOLDEN_REGISTRY_CLOCK): its freshness verdict and the trust fields derived from it are then a pure
    # function of the pin, source_age_days included. Only an UNPINNED run (a real-clock run such as
    # test_import_inventory_reconcile's) publishes a source_age_days that advances every second, so only there
    # is it excluded; such runs are never compared with the golden's data_authorities.
    if registry_clock is None:
        for health in (snap.get("data_authorities") or {}).values():
            if isinstance(health, dict):
                health.pop("source_age_days", None)
    # collection-time provenance: now() on a live run, dir-stamp/mtime on --no-collect -> volatile like
    # generated_at; exclude it (its consumer lifecycle_risk is already excluded below). (provenance R2-1-01)
    snap.pop("collected_at", None)
    # lifecycle_risk is date-dependent (bands/years shift relative to 'today') -> exclude from the frozen
    # golden; its logic is pinned deterministically by tests/test_lifecycle.py with a fixed asof. (V3.23.117)
    snap.pop("lifecycle_risk", None)
    # executive_brief rolls up lifecycle (its EoL headline is date-relative) -> exclude too; pinned by
    # tests/test_executive_brief.py with synthetic summaries. (V3.23.120)
    snap.pop("executive_brief", None)
    # device_dossiers is KEPT (owner decision, golden self-consistency): compound-risk punch-list rows point
    # INTO it, so a golden without it could not back its own citations. What is and is NOT deterministic,
    # measured rather than assumed: compute_device_dossiers itself reads no clock, and the lifecycle bands it
    # folds are dated as-of the pipeline's evidence date (the collection-dir stamp above pins it --
    # test_lifecycle_fold_is_dated_by_the_pinned_evidence_date_not_the_wall_clock). The one wall-clock read
    # that used to sit upstream of them -- eoldb's retained-EoX-registry freshness gate, evaluated at "now" --
    # is judged at the EVIDENCE date by compute_lifecycle_risk (R1V-1: fixed at the band's source, not
    # characterised): test_dossiers_do_not_depend_on_the_wall_clock_even_past_the_eol_registry_window.
    # data_authorities (the tool's registry health TODAY) is judged by the pinned registry clock in the golden
    # run, so the golden has no calendar boundary:
    # test_golden_does_not_depend_on_the_wall_clock_past_every_registry_window.
    # design_blueprint folds the date-relative lifecycle/EoL bands (its EoL decision count shifts as dates
    # pass) -> exclude like its lifecycle source; the blueprint logic is pinned deterministically by
    # tests/test_design_blueprint.py and its SSOT publish by tests/test_pipeline_inprocess.py. (design engine)
    snap.pop("design_blueprint", None)
    # design_nrfu is derived purely from design_blueprint (same date-relative folding) -> exclude it too;
    # its SSOT publish is locked by tests/test_pipeline_inprocess.py alongside the blueprint. (design engine)
    snap.pop("design_nrfu", None)
    # architecture_coverage is derived from design_blueprint (its findings shift with the date-relative blueprint)
    # -> exclude it too; its SSOT publish is locked by tests/test_pipeline_inprocess.py. (architecture coverage)
    snap.pop("architecture_coverage", None)
    # coverage_matrix (Plan-A #5) is COMPOSED from architecture_coverage -> inherits its date-relativity;
    # exclude it too, its SSOT publish is locked in tests/test_pipeline_inprocess.py. (coverage matrix)
    snap.pop("coverage_matrix", None)
    # fact_lineage (J2) embeds the canonical headline VALUES (n_past_ldos / avg_health / ... are
    # date-relative via lifecycle/executive_brief) -> exclude like its value sources; its shape +
    # coverage-honest state are pinned deterministically by tests/test_fact_lineage.py. (fact lineage)
    snap.pop("fact_lineage", None)
    # schema_census (J3) is intentionally KEPT in the golden: it records only presence/absence +
    # structural shape of the sections (no dates, no headline values), so it is non-volatile and
    # frozen here; its logic is also pinned by tests/test_schema_census.py.
    # attestation.generated_at is the one NESTED wall-clock stamp; strip just it (like the
    # top-level generated_at) — the re-derived trust CLAIMS themselves are deterministic and
    # must stay frozen in the golden. (roadmap D3)
    if isinstance(snap.get("attestation"), dict):
        snap["attestation"].pop("generated_at", None)
    return snap, str(out_xlsx)


def _sheet_schema(xlsx_path):
    wb = load_workbook(xlsx_path, read_only=True)
    schema = {}
    for name in wb.sheetnames:
        ws = wb[name]
        header = [c.value for c in next(ws.iter_rows(min_row=1, max_row=1))] if ws.max_row else []
        schema[name] = header
    wb.close()
    return schema


def _git_head_golden(name):
    """The golden as committed at git HEAD — the shrink guard's baseline. None when it
    is not tracked there (brand-new golden) or git is unavailable: nothing to shrink
    against, so the guard stands down rather than blocking legitimate first baselines."""
    try:
        proc = subprocess.run(["git", "show", f"HEAD:tests/golden/{name}"], cwd=ROOT,
                              capture_output=True, text=True, timeout=30)
        if proc.returncode != 0:
            return None
        return json.loads(proc.stdout)
    except Exception:
        return None


def _contract_shrinkage(name, baseline, produced):
    """Contract surface REMOVED between the HEAD golden and its replacement: top-level
    keys (snapshot sections / workbook sheets) always; for the sheet schema also header
    cells lost from a retained sheet. Additions and value changes are the additive norm
    and are not shrinkage (exact equality is the golden assertion's job)."""
    if not isinstance(baseline, dict) or not isinstance(produced, dict):
        return []
    lost = [f"top-level key removed: {k!r}" for k in baseline if k not in produced]
    if name == "sheet_schema.json":
        for sheet, header in baseline.items():
            new_header = produced.get(sheet)
            if isinstance(header, list) and isinstance(new_header, list):
                lost += [f"sheet {sheet!r} lost header {h!r}"
                         for h in header if h not in new_header]
    return lost


def _golden(name, produced):
    path = os.path.join(GOLDEN_DIR, name)
    if os.environ.get("UPDATE_GOLDEN") != "1":
        if not os.path.isfile(path):
            pytest.fail(
                f"golden {name} is MISSING — refusing to auto-generate a fresh baseline "
                f"(that would silently re-bless the contract). Restore it "
                f"(git checkout -- tests/golden/{name}) or regenerate deliberately with "
                f"UPDATE_GOLDEN=1.", pytrace=False)
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    # UPDATE_GOLDEN=1: a deliberate re-baseline — but refuse to silently SHRINK the
    # contract vs git HEAD; removals must be explicit (ALLOW_GOLDEN_SHRINK=1).
    baseline = _git_head_golden(name)
    if baseline is not None and os.environ.get("ALLOW_GOLDEN_SHRINK") != "1":
        lost = _contract_shrinkage(name, baseline, produced)
        if lost:
            pytest.fail(
                f"UPDATE_GOLDEN would SHRINK the {name} contract vs git HEAD:\n  - "
                + "\n  - ".join(lost)
                + "\nRemoving contract surface must be explicit: re-run with "
                  "ALLOW_GOLDEN_SHRINK=1 after review.", pytrace=False)
    os.makedirs(GOLDEN_DIR, exist_ok=True)
    # newline="\n": the tracked goldens are LF; a text-mode write on Windows would rewrite every line.
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        # sort_keys=False: preserve meaningful order (snapshot key order is
        # code-defined; Excel sheet order is the workbook tab order).
        json.dump(produced, f, indent=1, sort_keys=False)
    return None


@pytest.fixture(scope="module")
def golden_run(tmp_path_factory):
    """ONE real pipeline run, shared by the tests that only READ its artifacts. It runs with the golden's
    registry clock pinned (_GOLDEN_CLOCKS), so what it publishes does not depend on the day it runs.

    Seven tests here invoked `_run_pipeline` with identical arguments at ~30 s each — ~210 s, most of
    this file and a large share of the whole suite. They produce byte-identical output by
    construction, so running it seven times measured the same thing seven times.

    ONLY the zero-argument callers share this. `test_import_inventory_reconcile`,
    `test_optin_engines_emit_keys_and_sheets` and `test_missing_output_directory_is_created` pass
    different arguments and keep their own runs.

    Sharing is safe here, verified rather than assumed — the hazard is a test that MUTATES the shared
    artifacts, which is exactly what made three `test_phase_timings_contract` tests look like a
    staleness defect (see the handoff's §5.13/§6.1). The two tamper tests below LOOK like mutators;
    they are not. Each writes a SEPARATE `tampered.run_manifest.json` and leaves the produced
    manifest untouched. The other five are pure reads (golden compare, sheet schema,
    `load_workbook(read_only=True)`, manifest reads).

    If you add a test here that writes to the run's own output, give it its own `_run_pipeline`
    rather than widening this fixture — a shared artifact mutated by one test is a defect the others
    inherit silently.
    """
    return _run_pipeline(tmp_path_factory.mktemp("golden"), **_GOLDEN_CLOCKS)


def test_snapshot_matches_golden(golden_run):
    snap, _xlsx = golden_run
    golden = _golden("snapshot.json", snap)
    if golden is None:
        return
    # compare as objects (key order irrelevant); pinpoint drift by section
    assert set(snap) == set(golden), "snapshot top-level keys changed"
    for key in golden:
        assert snap[key] == golden[key], f"snapshot section '{key}' changed vs golden"


def test_every_evidence_pointer_in_the_golden_file_resolves_in_the_golden_file_itself():
    """Owner decision (a): the golden is a SELF-CONSISTENT document. Every evidence_ref it carries (punch
    list + every upstream section that publishes refs) resolves, to the record it claims, INSIDE the
    committed tests/golden/snapshot.json -- no section a pointer names may be stripped from it."""
    from test_punchlist_evidence_refs import punchlist_evidence_problems

    with open(os.path.join(GOLDEN_DIR, "snapshot.json"), encoding="utf-8") as f:
        golden = json.load(f)
    n_refs = sum(len(row.get("evidence_refs") or []) for row in golden.get("punchlist") or [])
    assert n_refs > 0, "the golden carries no evidence refs -- the check would be vacuous"
    assert any(ref["ref"].startswith("/device_dossiers/") for row in golden["punchlist"]
               for ref in row["evidence_refs"]), "no compound-risk ref into device_dossiers -- vacuous"
    problems = punchlist_evidence_problems(golden, "golden file")
    assert not problems, "\n".join(problems[:40])


def test_lifecycle_fold_is_dated_by_the_pinned_evidence_date_not_the_wall_clock(golden_run):
    """The lifecycle bands the kept dossiers fold are CLASSIFIED as-of the EVIDENCE date (the collection-dir
    stamp), never the day the test runs: if the pipeline fell back to the wall clock, `asof` would be today.
    Whether the retained EoX registry may drive a band at all is judged at the same evidence date -- see
    test_dossiers_do_not_depend_on_the_wall_clock_even_past_the_eol_registry_window."""
    _snap, xlsx = golden_run
    with open(os.path.splitext(xlsx)[0] + ".snapshot.json", encoding="utf-8") as f:
        written = json.load(f)
    stamp = _GOLDEN_COLLECTION_STAMP
    evidence_date = f"{stamp[0:4]}-{stamp[4:6]}-{stamp[6:8]}"
    assert written["lifecycle_risk"]["asof"] == evidence_date
    assert written["collected_at"][:10] == evidence_date
    assert _snap["device_dossiers"] == written["device_dossiers"]          # kept, not stripped


# The dossier inputs the pipeline's ctx-adapter (COLLECT_PARSE `_device_dossiers`) passes, by the snapshot key
# each is published under -- lifecycle_risk excepted: the golden strips it, so it is recomputed below.
_DOSSIER_SECTIONS = tuple(dict.fromkeys(
    section for sections in (*DOSSIER_AXIS_INPUTS.values(), ("failure_impact", "stp_roots", "vpc", "move_groups"))
    for section in sections if section != "lifecycle_risk"))


def _golden_dossiers_under_wall_clock(monkeypatch, instant, evidence_date=None, *, break_chain=False):
    """Recompute the committed golden's device_dossiers in-process with the wall clock pinned at `instant`
    (every `datetime.now` the EoX registry's freshness policy can read) and the lifecycle classified as-of
    `evidence_date` (default: the golden's pinned evidence date). `break_chain` makes the retained-source
    byte/semantic verification fail, whatever the date. Returns (lifecycle_risk, device_dossiers, golden)."""
    from datetime import datetime

    from cisco_toolkit import analyze, eoldb, registry_integrity, ssot

    class _PinnedClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant if tz is None else instant.astimezone(tz)

    with open(os.path.join(GOLDEN_DIR, "snapshot.json"), encoding="utf-8") as f:
        golden = json.load(f)
    stamp = _GOLDEN_COLLECTION_STAMP
    evidence_date = evidence_date or f"{stamp[0:4]}-{stamp[4:6]}-{stamp[6:8]}"
    devices = {d["host"]: {"model": d["model"], "sw_version": d["sw_version"]}
               for d in golden["device_dossiers"]["per_device"]}
    monkeypatch.setattr(registry_integrity, "datetime", _PinnedClock)
    if break_chain:
        def _tampered(*_a, **_k):
            raise registry_integrity.PackIntegrityError("retained Cisco EoL fixture digest mismatch (test)")
        monkeypatch.setattr(eoldb, "verify_retained_eol_source_chain", _tampered)
    eoldb._runtime_source_proof.cache_clear()          # the proof is memoized per process
    try:
        lifecycle = analyze.compute_lifecycle_risk(devices, asof=evidence_date)
        dossiers = analyze.compute_device_dossiers(
            lifecycle_risk=lifecycle, input_failures=ssot.failed_sections(golden),
            **{k: golden.get(k) for k in _DOSSIER_SECTIONS})
    finally:
        monkeypatch.undo()
        eoldb._runtime_source_proof.cache_clear()
    return lifecycle, dossiers, golden


def _eol_freshness_window():
    from datetime import datetime, timedelta

    from cisco_toolkit import eoldb, registry_integrity
    retrieved = datetime.fromisoformat(eoldb._EOL_FIXTURE_RETRIEVED_AT.replace("Z", "+00:00"))
    return retrieved, retrieved + timedelta(days=registry_integrity.SOURCE_MAX_AGE_DAYS)


def test_dossiers_do_not_depend_on_the_wall_clock_even_past_the_eol_registry_window(monkeypatch):
    """R1V-1 (owner decision (a): fix the wall-clock read at its SOURCE). Whether the retained Cisco EoX registry
    may drive a lifecycle band is judged at the EVIDENCE date, never at the day the pipeline runs: the golden's
    dossiers are reproduced EXACTLY at instants inside the registry's freshness window AND long past it. Before
    the fix, one day past the window withheld every matched band (Unknown) and the dossiers differed."""
    from datetime import timedelta

    retrieved, boundary = _eol_freshness_window()
    instants = (retrieved + timedelta(hours=1), boundary - timedelta(hours=1),
                boundary + timedelta(days=1), boundary + timedelta(days=3650))
    results = [_golden_dossiers_under_wall_clock(monkeypatch, t) for t in instants]
    golden = results[0][2]
    matched = [d for d in results[0][0]["per_device"] if d["match_kind"] != "none"]
    assert matched and all(d["band"] != "Unknown" for d in matched), "no EoX-matched golden device -- vacuous"
    for (lifecycle, dossiers, _g), instant in zip(results, instants):
        assert lifecycle["per_device"] == results[0][0]["per_device"], f"lifecycle drifts at {instant}"
        assert dossiers == golden["device_dossiers"], f"dossiers drift with the wall clock at {instant}"
        for d in lifecycle["per_device"]:
            if d["match_kind"] != "none":
                assert d["citation_status"] == "retained-primary-fixture", (instant, d)


def test_current_dossiers_are_wall_clock_invariant_without_rewriting_the_golden(monkeypatch):
    """Exercise the current producer independently of a deliberately deferred fixture refresh."""
    from datetime import datetime, timezone

    current = _golden_dossiers_under_wall_clock(monkeypatch, datetime(2026, 7, 30, tzinfo=timezone.utc))[1]
    future = _golden_dossiers_under_wall_clock(monkeypatch, datetime(2027, 7, 30, tzinfo=timezone.utc))[1]
    assert current["per_device"]
    assert current == future


def test_eol_registry_staleness_is_judged_at_the_evidence_date_and_fails_closed(monkeypatch):
    """The coverage the old wall-clock characterisation provided, moved to the evidence date: evidence dated past
    the registry's freshness window withholds every matched band (Unknown, no unverified dates published) even
    while the wall clock is inside the window; evidence dated on the last fresh day still bands. And judging at
    the evidence date never bypasses integrity: a retained chain that fails verification withholds the band
    whatever the wall clock or the evidence date says."""
    from datetime import timedelta

    retrieved, boundary = _eol_freshness_window()
    inside_clock = retrieved + timedelta(days=8)
    last_fresh_day = (boundary - timedelta(days=1)).date().isoformat()
    stale_day = (boundary + timedelta(days=1)).date().isoformat()

    banded, _d, _g = _golden_dossiers_under_wall_clock(monkeypatch, inside_clock, last_fresh_day)
    matched = [d for d in banded["per_device"] if d["match_kind"] != "none"]
    assert matched and all(d["band"] != "Unknown" and d["ldos"] for d in matched), matched

    stale, stale_dossiers, _g = _golden_dossiers_under_wall_clock(monkeypatch, inside_clock, stale_day)
    by_host = {d["host"]: d for d in stale["per_device"]}
    for d in matched:
        row = by_host[d["host"]]
        assert row["band"] == "Unknown" and row["eos"] == row["ldos"] == "", row
        assert row["citation_status"] == "primary-url-unverified", row
        assert "evidence date" in row["status"], row["status"]
    dossier_by_host = {d["host"]: d for d in stale_dossiers["per_device"]}
    assert all(dossier_by_host[d["host"]]["eol_band"] == "Unknown" for d in matched)

    for clock in (inside_clock, boundary + timedelta(days=30)):
        broken, _d, _g = _golden_dossiers_under_wall_clock(monkeypatch, clock, last_fresh_day, break_chain=True)
        rows = {d["host"]: d for d in broken["per_device"]}
        assert all(rows[d["host"]]["band"] == "Unknown" and rows[d["host"]]["ldos"] == "" for d in matched), clock


def _registry_windows(golden):
    """(authority, retrieved, stale-after) for EVERY data authority the golden publishes, read from the policy
    fields each one publishes -- never a hand-kept list of registries."""
    from datetime import datetime, timedelta

    windows = []
    for name, health in golden["data_authorities"].items():
        retrieved = datetime.fromisoformat(health["source_retrieved_at"].replace("Z", "+00:00"))
        windows.append((name, retrieved, retrieved + timedelta(days=health["source_max_age_days"])))
    return windows


def test_golden_does_not_depend_on_the_wall_clock_past_every_registry_window(tmp_path):
    """The golden has no calendar boundary. The WHOLE pipeline process runs with its wall clock moved 30 days
    past the LAST retained data-authority registry's freshness window -- the day CI would otherwise start
    failing -- and the golden comparison (every snapshot section + the workbook sheet schema) still holds
    exactly. Every other wall-clock read the pipeline makes really ran at that date (asserted), so this is the
    whole-snapshot audit, not a list of fields someone remembered."""
    from datetime import datetime, timedelta

    with open(os.path.join(GOLDEN_DIR, "snapshot.json"), encoding="utf-8") as f:
        golden = json.load(f)
    with open(os.path.join(GOLDEN_DIR, "sheet_schema.json"), encoding="utf-8") as f:
        golden_sheets = json.load(f)
    windows = _registry_windows(golden)
    assert any(name == "eol" for name, _r, _b in windows), windows
    late = max(boundary for _n, _r, boundary in windows) + timedelta(days=30)

    snap, xlsx = _run_pipeline(tmp_path, wall_clock=late.isoformat(), **_GOLDEN_CLOCKS)
    with open(os.path.splitext(xlsx)[0] + ".snapshot.json", encoding="utf-8") as f:
        written = json.load(f)
    ran_at = datetime.fromisoformat(written["generated_at"]).astimezone()
    assert ran_at > max(boundary for _n, _r, boundary in windows), (
        f"the pipeline did not run past the registry windows (generated_at {written['generated_at']}) -- vacuous")
    assert set(snap) == set(golden), "snapshot top-level keys differ from the golden past the registry windows"
    for key in golden:
        assert snap[key] == golden[key], f"snapshot section '{key}' depends on the wall clock (ran at {ran_at})"
    assert _sheet_schema(xlsx) == golden_sheets, f"the workbook sheet schema depends on the wall clock ({ran_at})"


def test_golden_registry_clock_is_inside_every_published_registry_window(golden_run):
    """The pin is not a calendar boundary, but it is a DATA boundary: the golden's registry clock must sit inside
    the freshness window of every registry the pipeline publishes. A registry REFRESH (a new retrieval) is the
    one event that can move a registry out of it -- a retrieval after the pin reads future-dated at the pin --
    and it would otherwise surface as an opaque data_authorities / assessment_integrity diff. Every published
    authority is read from the run (never a hand-kept list), and its verdict is re-derived here by arithmetic."""
    from datetime import datetime, timedelta

    snap, _xlsx = golden_run
    pin = datetime.fromisoformat(_GOLDEN_REGISTRY_CLOCK)
    authorities = snap["data_authorities"]
    assert authorities and all(isinstance(h, dict) for h in authorities.values()), authorities
    for name, health in authorities.items():
        retrieved = datetime.fromisoformat(health["source_retrieved_at"].replace("Z", "+00:00"))
        inside = (retrieved - timedelta(seconds=health["source_max_future_skew_seconds"])
                  <= pin <= retrieved + timedelta(days=health["source_max_age_days"]))
        assert inside and health["freshness_status"] == "fresh", (
            f"data authority {name!r} (retrieved {health['source_retrieved_at']}) is "
            f"{health['freshness_status']} at the golden's registry clock {_GOLDEN_REGISTRY_CLOCK}: a registry "
            "refresh moved it out of the pinned window. Move _GOLDEN_COLLECTION_STAMP (the evidence date the pin "
            "follows) to an instant inside every registry's window, then regenerate with UPDATE_GOLDEN=1.")
    assert "assessment_integrity" not in snap, snap.get("assessment_integrity")


def test_every_punchlist_evidence_pointer_resolves_on_the_published_snapshot(golden_run):
    """Per-finding evidence pointers (docs/ssot.md): over EVERY punch-list row of this real run --
    never a named subset -- the basis is in the enum and allowed for the category, and every
    RFC 6901 ref resolves to the record it claims (not merely a non-null node) in the snapshot AS
    WRITTEN (sparsified, compact), after the whole-snapshot redaction, and in the explorer embed of
    both (which re-filters lists). The committed golden file itself is checked separately
    (test_every_evidence_pointer_in_the_golden_file_resolves_in_the_golden_file_itself)."""
    from test_punchlist_evidence_refs import published_forms, punchlist_evidence_problems

    _snap, xlsx = golden_run
    with open(os.path.splitext(xlsx)[0] + ".snapshot.json", encoding="utf-8") as f:
        written = json.load(f)
    problems = []
    for form, snap in published_forms(None, written):
        problems += punchlist_evidence_problems(snap, f"golden {form}")
    assert not problems, "\n".join(problems[:40])


def test_stp_topology_owner_and_schema_census_ship_fail_closed(golden_run):
    """The real pipeline publishes typed STP rows without inventing missing counters."""
    from cisco_toolkit.stp_topology import validate_stp_topology_baseline

    snap, _xlsx = golden_run
    observations = snap["stp_topology_observations"]
    baseline = snap["stp_topology_baseline"]

    assert set(observations) == set(snap["devices"])
    assert all(
        row["schema"] == "stp_topology_observation/1"
        and row["state_capture_state"] == "usable"
        and row["detail_capture_state"] == "missing"
        and row["roles"]
        and {role["namespace"] for role in row["roles"]} == {"pvst_vlan"}
        and "topology_counter_missing" in row["finding_codes"]
        for row in observations.values()
    )
    assert validate_stp_topology_baseline(
        baseline,
        observations=observations,
        legacy_roots=snap["stp_roots"],
        devices=snap["devices"],
    )["valid"] is True
    assert baseline["verdict"] == "INDETERMINATE"
    assert all(row["topology_change_count"] is None for row in baseline["rows"])
    assert all(cell["status"] == "not_verified" for cell in baseline["coverage"])

    census = {row["key"]: row for row in snap["schema_census"]["sections"]}
    assert census["stp_topology_observations"]["state"] == "published"
    assert census["stp_topology_baseline"]["state"] == "published"


def test_etherchannel_operational_owner_ships_source_bound_and_fail_closed(golden_run):
    """The pipeline publishes typed depth without upgrading incomplete legacy fixtures."""
    from cisco_toolkit.etherchannel import validate_etherchannel_operational_evidence

    snap, _xlsx = golden_run
    evidence = snap["etherchannel_operational_evidence"]
    view = validate_etherchannel_operational_evidence(evidence)

    assert view["valid"] is True
    assert evidence["projection_custody"] == "embedded_unverified"
    assert evidence["verdict"] == "INDETERMINATE"
    assert {row["switch"] for row in evidence["rows"]} == {"core1", "core2"}
    assert all(row["status"] in {"review", "not_verified"} for row in evidence["rows"])
    assert all(
        row["member_failure_rehearsal"]["service_path_survival"] == "not_verified"
        for row in evidence["rows"]
    )
    census = {row["key"]: row for row in snap["schema_census"]["sections"]}
    assert census["etherchannel_operational_evidence"]["state"] == "published"


def test_multichassis_raw_producer_blocks_ship_fail_closed(golden_run):
    """The real offline pipeline publishes both audit input and its canonical stored baseline.

    The synthetic EOS fixture has the existing standard ``show mlag`` capture but not the newly
    required explicit peer-identity/LACP files, so custody is exact while assurance abstains.
    """
    snap, _xlsx = golden_run
    typed = snap["multichassis_lag_typed_observations"]
    baseline = snap["multichassis_lag_domain_baseline"]

    assert len(typed["observations"]) == 1
    assert typed["observations"][0]["switch"] == "core2"
    assert typed["observations"][0]["source"]["capture_status"] == "incomplete"
    assert typed["observations"][0]["source"]["commands"] == ["show mlag"]
    assert baseline["projection_custody"] == "current_run_source_bound"
    assert baseline["reciprocal_peer_pairs"] == []
    assert baseline["reconciled_attachments"] == []
    local = baseline["local_observations"][0]
    assert local["health_state"] == "degraded"  # fixture also has an explicit config-sanity fault
    assert {finding["code"] for finding in local["findings"]} >= {
        "source_capture_incomplete", "local_identity_missing", "peer_identity_missing",
    }
    assert validate_multichassis_lag_domain_baseline(baseline)["valid"] is True


def test_excel_sheet_schema_matches_golden(golden_run):
    _snap, xlsx = golden_run
    schema = _sheet_schema(xlsx)
    golden = _golden("sheet_schema.json", schema)
    if golden is None:
        return
    assert list(schema.keys()) == list(golden.keys()), "Excel sheet set/order changed"
    for sheet, header in golden.items():
        assert schema[sheet] == header, f"header row of sheet '{sheet}' changed"


def test_move_group_endpoint_label_is_honest_per_switch_mac_sum(golden_run):
    """B3 (audit fix): move_groups[].endpoints is the per-SWITCH sum of learned MACs (an endpoint seen on
    N of the group's switches counts N times), so a large L2-coupled group can EXCEED the distinct fleet
    endpoint total (executive_brief.scale.n_endpoints / Endpoint Census). The workbook must label it as a
    per-switch MAC sum -- never the bare 'Endpoints'/'endpoint(s)' -- so it cannot be misread as a
    competing fleet endpoint total. Refutes the relabel silently reverting."""
    _snap, xlsx = golden_run
    wb = load_workbook(xlsx, read_only=True)
    try:
        mg_hdr = [c.value for c in next(wb["Move Groups"].iter_rows(min_row=1, max_row=1))]
        assert "# Endpoint MACs (per-switch sum)" in mg_hdr, f"Move Groups header not relabeled: {mg_hdr}"
        assert "# Endpoints" not in mg_hdr, "bare '# Endpoints' must not return (misreads as fleet total)"
        # Migration Scenarios carries the same per-group figure; its column header is row 2 (row 1 is the
        # fleet-recommendation banner), so scan the top rows for the honest label.
        ms_top = [str(v) for row in wb["Migration Scenarios"].iter_rows(min_row=1, max_row=3, values_only=True)
                  for v in row if v]
        assert any("Endpoint MACs (per-switch sum)" in v for v in ms_top), \
            f"Migration Scenarios endpoint column not relabeled: {ms_top}"
    finally:
        wb.close()


def test_run_manifest_emitted_and_sealed(golden_run):
    """roadmap D2: the pipeline emits a sealed run-manifest (chain-of-custody) next to the workbook —
    a hash-chained step ledger + per-artifact sha256 + chain_root that verify_manifest() reconciles."""
    from cisco_toolkit import manifest as M
    _snap, xlsx = golden_run
    man_path = os.path.splitext(xlsx)[0] + ".run_manifest.json"
    assert os.path.isfile(man_path), "run_manifest.json was not produced"
    with open(man_path, encoding="utf-8") as f:
        man = json.load(f)
    assert man.get("chain_root") and man.get("artifacts"), "manifest missing seal/artifacts"
    ok, broken = M.verify_manifest(man)
    assert ok, f"manifest chain broken at rows {broken}"
    names = [a["name"] for a in man["artifacts"]]
    assert any(n.endswith(".snapshot.json") for n in names), f"snapshot not hashed: {names}"
    assert any(n.endswith(".xlsx") for n in names), f"workbook not hashed: {names}"
    assert "abstention_ledger" in man        # coverage-honest provenance is part of the seal


def test_shipped_verify_verb_passes_the_real_pipeline_manifest(golden_run, capsys):
    """The CI check on the seal. The test above calls the library function; this runs the command an
    AUDITOR actually has — `python -m cisco_toolkit.manifest verify` — against a manifest the real
    pipeline produced, not a hand-built fixture. A verb that only ever sees synthetic manifests can
    agree with a producer bug; this is the arm that would catch the engine emitting a chain the
    shipped verifier rejects.

    Also proves the artifact hashes reconcile against the deliverables ON DISK, which is the actual
    chain-of-custody question ("is this the workbook that was sealed?") and which no test covered."""
    from cisco_toolkit import manifest as M
    _snap, xlsx = golden_run
    man_path = os.path.splitext(xlsx)[0] + ".run_manifest.json"

    assert M.main(["verify", man_path]) == 0, capsys.readouterr().out
    assert capsys.readouterr().out.startswith("OK: ")
    # --artifacts re-hashes every deliverable the engine listed, from the run's own output folder.
    assert M.main(["verify", man_path, "--artifacts"]) == 0, capsys.readouterr().out
    assert "hash to the seal" in capsys.readouterr().out


def test_shipped_verify_verb_rejects_a_tampered_pipeline_manifest(golden_run, tmp_path, capsys):
    """Non-vacuity for the check above: prove the exit code moves. Two independent edits an auditor
    must catch — a rewritten step, and a deliverable swapped after the run."""
    from cisco_toolkit import manifest as M
    _snap, xlsx = golden_run
    man_path = os.path.splitext(xlsx)[0] + ".run_manifest.json"
    with open(man_path, encoding="utf-8") as f:
        man = json.load(f)

    # (1) rewrite a sealed step — the "we collected everything" edit
    tampered = os.path.join(str(tmp_path), "tampered.run_manifest.json")
    edited = json.loads(json.dumps(man))
    edited["chain"][0]["collected"] = 99999
    with open(tampered, "w", encoding="utf-8") as f:
        json.dump(edited, f)
    assert M.main(["verify", tampered]) == 4
    assert "INTEGRITY" in capsys.readouterr().out

    # (2) leave the ledger alone, swap a delivered file — caught by safe-default byte verification
    with open(xlsx, "ab") as f:
        f.write(b"\n<appended after sealing>")
    assert M.main(["verify", man_path]) == 4
    assert "[MISMATCH]" in capsys.readouterr().out
    assert M.main(["verify", man_path, "--metadata-only"]) == 0
    capsys.readouterr()
    assert M.main(["verify", man_path, "--artifacts"]) == 4
    assert "[MISMATCH]" in capsys.readouterr().out


def test_import_inventory_reconcile(tmp_path):
    """roadmap B: --import-inventory ingests a declared inventory (CMDB/NetBox CSV) and reconciles it against
    the collected evidence -> snap['external_reconcile'] + a 'SoT Reconcile' workbook sheet (opt-in)."""
    inv = tmp_path / "cmdb.csv"
    inv.write_text("hostname,device_type\nGHOST-NOT-IN-FLEET,C9999\n", encoding="utf-8")
    snap, xlsx = _run_pipeline(tmp_path, extra_args=["--import-inventory", str(inv)])
    er = snap.get("external_reconcile")
    assert er and er.get("summary"), "external_reconcile missing from snapshot"
    assert er["summary"]["MISSING_DEVICE"] == 1          # the declared ghost is not observed
    assert er["summary"]["UNDOCUMENTED_DEVICE"] >= 1     # observed devices absent from the (ghost-only) SoT
    wb = load_workbook(xlsx, read_only=True)
    try:
        assert "SoT Reconcile" in wb.sheetnames
    finally:
        wb.close()


def test_default_run_optin_engines_absent_but_capture_integrity_present(golden_run):
    """Opt-in engines add no result on a default run; always-on evidence/sheet surfaces stay explicit."""
    snap, xlsx = golden_run
    for key in (
        "external_reconcile",
        "whatif",
        "path_intents",
        "state_assertions",
        "traffic_assurance",
    ):
        assert key not in snap, f"{key} must be opt-in / absent by default"
    assert "capture_integrity" in snap            # always-on
    custody = snap.get("traffic_evidence_custody")
    assert isinstance(custody, dict)
    assert custody.get("schema") == "traffic_evidence_custody/1"
    wb = load_workbook(xlsx, read_only=True)
    try:
        for sheet in ("SoT Reconcile", "Failure What-If", "Path Assertions"):
            assert sheet not in wb.sheetnames
        assert "Capture Integrity" in wb.sheetnames   # always-on
        assert "Traffic Assurance" in wb.sheetnames   # explicit not-supplied projection
        ws = wb["Traffic Assurance"]
        columns = {cell.value: cell.column for cell in ws[1]}
        assert ws.cell(2, columns["Projection State"]).value == "not_supplied"
    finally:
        wb.close()


def test_optin_engines_emit_keys_and_sheets(tmp_path):
    """roadmap G4 / G3 / A1+H2: --scenario, --path-intents and --assert-pack each compute over the snapshot and
    emit their result (sheet and/or snapshot key) when supplied."""
    scen = tmp_path / "scen.json"
    scen.write_text(json.dumps([{"name": "edge-fail", "failures": [{"type": "node", "id": "no-such-host"}]}]), encoding="utf-8")
    intents = tmp_path / "intents.json"
    intents.write_text(json.dumps([{"id": "i1", "src": "10.0.0.1", "dst": "10.0.0.2", "expect": "REACHES"}]), encoding="utf-8")
    pack = tmp_path / "pack.json"
    pack.write_text(json.dumps({"assertions": [
        {"id": "a1", "subject": "collection_completeness", "all_of": [{"type": "contains", "value": "summary"}]}]}), encoding="utf-8")
    snap, xlsx = _run_pipeline(tmp_path, extra_args=[
        "--scenario", str(scen), "--path-intents", str(intents), "--assert-pack", str(pack)])
    assert isinstance(snap.get("whatif"), list)
    assert "results" in (snap.get("path_intents") or {})
    sa = snap.get("state_assertions") or {}
    assert "summary" in sa
    a1 = [r for r in sa.get("results", []) if r.get("id") == "a1"]
    assert a1 and a1[0]["status"] == "pass"        # 'collection_completeness' exists -> contains 'summary' -> pass
    wb = load_workbook(xlsx, read_only=True)
    try:
        assert "Failure What-If" in wb.sheetnames and "Path Assertions" in wb.sheetnames
    finally:
        wb.close()


def test_missing_output_directory_is_created(tmp_path):
    """FIX-V3.23.103: a non-existent --output directory must be created up-front,
    not crash openpyxl's save() AFTER all the heavy compute. Point --output at a
    nested directory that does not exist and assert every output lands there."""
    out_xlsx = tmp_path / "does" / "not" / "exist" / "out.xlsx"
    assert not out_xlsx.parent.exists()           # precondition: dir is missing
    _snap, xlsx = _run_pipeline(tmp_path, out_xlsx=out_xlsx)
    assert os.path.isfile(xlsx), "workbook was not written into the created directory"
    snap_path = os.path.splitext(xlsx)[0] + ".snapshot.json"
    assert os.path.isfile(snap_path), "snapshot was not written into the created directory"
