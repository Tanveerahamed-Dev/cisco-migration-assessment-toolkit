"""The redaction-phase guard, pinned against the REAL producer on both of its arms.

`webapp/backend/ingest._assert_redaction_phases_ran` refuses a `--redact-folder` run whose scrub
phase failed inside the engine — the check that stops Atlas handing a field engineer a workbook
full of real client data under a "share-safe" banner. It has two independent signals: the
`.phase_timings.json` sidecar and the engine's `[SKIP] Phase …` line on stderr.

The sidecar arm was DEAD. It iterated the file as a bare list of rows; the engine writes a dict
keyed by "phases", so `str.get(...)` raised `AttributeError` and a defensive `except` swallowed it.
It survived because the unit test covering it FABRICATED the sidecar in the shape the buggy parser
expected — the stub and the bug agreed with each other. A hand-written fixture encodes the author's
belief about the producer's format, which is the same belief that produced the parser bug, so it
can only ever confirm it.

So this file tests the consumer against the producer's ACTUAL output. It lives in tests/ because
that is where running the real engine is the established discipline (webapp/tests deliberately
always fakes the subprocess), and it deliberately carries NO `importorskip` — see
`test_this_file_is_not_gated_behind_a_web_dependency` for why that is load-bearing rather than
stylistic.
"""
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# NB no importorskip: webapp.backend.ingest imports cleanly without fastapi/httpx/starlette
# (serve.py imports those lazily), and the engine CI matrix installs no web deps.
from webapp.backend import ingest as ing  # noqa: E402
import COLLECT_PARSE_V3_23_0 as cp  # noqa: E402


@pytest.fixture(scope="module")
def redact_run(tmp_path_factory):
    """ONE real `--redact` pipeline run, shared by the whole module.

    Each run is ~25s; per-test it made this file cost more than the rest of the suite's engine
    tests combined. Every test either only reads the artefacts or writes to its own copy."""
    from test_pipeline_golden import _run_pipeline

    tmp = tmp_path_factory.mktemp("redact")
    _snap, xlsx = _run_pipeline(tmp, extra_args=["--redact"])
    sidecar = os.path.splitext(str(xlsx))[0] + ".phase_timings.json"
    assert os.path.isfile(sidecar), "the engine wrote no phase-timings sidecar"
    with open(sidecar, encoding="utf-8") as f:
        raw = json.load(f)
    return {"xlsx": str(xlsx), "sidecar": sidecar, "raw": raw}


# ── the sidecar arm, against the real producer ─────────────────────────────────────────────────
def test_the_consumer_parses_a_sidecar_the_real_engine_wrote(redact_run):
    raw = redact_run["raw"]
    rows = ing._phase_rows(raw)
    assert rows, (f"the consumer parsed no rows out of a REAL sidecar (top-level "
                  f"{type(raw).__name__}, keys {sorted(raw) if isinstance(raw, dict) else 'n/a'})")
    assert all(isinstance(r, dict) and "phase" in r and "ok" in r for r in rows), rows[:3]


def test_every_watched_phase_name_really_occurs_in_a_real_run(redact_run):
    """A renamed phase would retire the check as silently as the shape mismatch did."""
    names = {str(r["phase"]).lower() for r in ing._phase_rows(redact_run["raw"])}
    assert set(ing._REDACTION_PHASES) <= names, (
        f"a phase the redaction check watches for does not appear in a real --redact run.\n"
        f"  watched: {sorted(ing._REDACTION_PHASES)}\n"
        f"  missing: {sorted(set(ing._REDACTION_PHASES) - names)}")


def _sidecar_at(tmp_path, payload):
    """Write `payload` as the sidecar for a throwaway workbook path and return that path."""
    xlsx = tmp_path / "Assessment.xlsx"
    xlsx.write_bytes(b"xlsx")
    (tmp_path / "Assessment.phase_timings.json").write_text(json.dumps(payload), encoding="utf-8")
    return xlsx


@pytest.mark.parametrize("phase", ["redact collected dataclasses", "redact workbook cells"])
def test_the_refusal_fires_on_a_real_failed_phase(redact_run, tmp_path, phase):
    """The real run's own ledger, with one watched phase flipped to failed. Real shape, real
    phase spelling, only the outcome changed. Both phases, because a guard that watches one is
    half a guard."""
    from pathlib import Path

    real = json.loads(json.dumps(redact_run["raw"]))          # deep copy; fixture is shared
    hit = [r for r in real["phases"] if str(r["phase"]).lower() == phase]
    assert hit, f"{phase!r} not in the real sidecar"
    hit[0]["ok"] = False
    xlsx = _sidecar_at(tmp_path, real)

    with pytest.raises(ing.EngineRunError) as e:
        ing._assert_redaction_phases_ran(Path(str(xlsx)), engine_output="")   # stderr arm silent
    assert "REDACTION PHASE FAILED" in str(e.value) and phase in str(e.value)


def test_a_clean_real_run_is_not_refused(redact_run):
    """The other edge: a guard that cannot stay silent is as useless as one that cannot speak.
    Uses the untouched real ledger, so it also proves the fail-closed arms below don't misfire on
    the genuine article."""
    from pathlib import Path

    ing._assert_redaction_phases_ran(Path(redact_run["xlsx"]), engine_output="")   # must not raise


# ── fail CLOSED: everything the guard cannot positively confirm ────────────────────────────────
@pytest.mark.parametrize("label, payload", [
    ("renamed 'phases' key", {"n_devices": 1, "timed_phases": [
        {"phase": "redact workbook cells", "ok": True}]}),
    ("rows keyed by name", {"phases": {"redact workbook cells": {"ok": True}}}),
    ("phases nested deeper", {"ledger": {"phases": [{"phase": "redact workbook cells", "ok": True}]}}),
    ("rows as tuples", {"phases": [["redact workbook cells", 0.1, True]]}),
    ("phases is null", {"phases": None}),
    ("a watched phase never ran", {"phases": [{"phase": "redact collected dataclasses", "ok": True}]}),
])
def test_a_ledger_that_cannot_be_understood_refuses(tmp_path, label, payload):
    """Every one of these used to read EXACTLY like a clean run. That is the dict/list bug one
    level up: the guard quietly stops applying and nothing says so."""
    from pathlib import Path

    xlsx = _sidecar_at(tmp_path, payload)
    with pytest.raises(ing.EngineRunError) as e:
        ing._assert_redaction_phases_ran(Path(str(xlsx)), engine_output="")
    assert "COULD NOT BE VERIFIED" in str(e.value), f"{label}: {e.value}"


@pytest.mark.parametrize("ok_value", [False, 0, "false", "False", None, ""])
def test_any_non_success_ok_value_is_treated_as_failure(tmp_path, ok_value):
    """`ok is False` missed `0`, `"false"` and a missing key — all of which a JSON ledger written
    by another program can legitimately produce."""
    from pathlib import Path

    payload = {"phases": [{"phase": p, "seconds": 0.1, "ok": ok_value}
                          for p in ing._REDACTION_PHASES]}
    xlsx = _sidecar_at(tmp_path, payload)
    with pytest.raises(ing.EngineRunError):
        ing._assert_redaction_phases_ran(Path(str(xlsx)), engine_output="")


def test_an_absent_sidecar_is_tolerated(tmp_path):
    """The one case that must NOT refuse: the sidecar's write is fail-soft in the engine, so its
    absence proves nothing and the stderr arm carries the run alone."""
    from pathlib import Path

    xlsx = tmp_path / "Assessment.xlsx"
    xlsx.write_bytes(b"xlsx")
    ing._assert_redaction_phases_ran(Path(str(xlsx)), engine_output="")   # must not raise


# ── the parser's own defensive branches ────────────────────────────────────────────────────────
def test_a_bare_list_sidecar_still_parses():
    """The back-compat branch the docstring promises. Unpinned, a dict-only rewrite would pass
    every other test here and silently restore the original AttributeError on a list."""
    rows = ing._phase_rows([{"phase": "redact workbook cells", "seconds": 0.1, "ok": False}])
    assert [r["phase"] for r in rows] == ["redact workbook cells"]


def test_non_dict_rows_are_filtered_not_fatal():
    assert ing._phase_rows({"phases": [{"phase": "a", "ok": True}, "junk", None, 7]}) == \
        [{"phase": "a", "ok": True}]


# ── the stderr arm, against the real producer ──────────────────────────────────────────────────
@pytest.mark.parametrize("phase", ["redact collected dataclasses", "redact workbook cells"])
def test_the_stderr_needle_matches_what_run_phase_actually_logs(caplog, phase):
    """The scrape was the ONLY working signal for the whole life of the sidecar bug, and it was
    itself pinned by nothing but a fabricated fixture in webapp/tests. Tie it to the producer: a
    change to `_run_phase`'s log string must fail here rather than silently retire the last arm."""
    def boom(*_a, **_k):
        raise RuntimeError("nope")

    with caplog.at_level("ERROR"):
        cp._run_phase(phase, boom)
    assert f"[skip] phase '{phase}'" in caplog.text.lower(), (
        f"ingest's scrape needle no longer matches the engine's own log line.\n"
        f"  needle: [skip] phase '{phase}'\n  logged: {caplog.text.strip()[:200]}")


# ── the meta-test that would have caught this file being a no-op ───────────────────────────────
def test_this_file_is_not_gated_behind_a_web_dependency():
    """This file guards the field redaction path, so it has to RUN where that path is tested.

    It originally opened each test with `pytest.importorskip("fastapi")`. fastapi is in neither
    requirements.txt nor requirements-dev.txt, so the ci.yml matrix skipped all of it; webapp-ci
    installs fastapi but runs only `webapp/tests`. The file therefore executed in ZERO CI jobs
    while reporting green locally — an asset sitting outside the gate, which is the same class of
    defect as the bug it exists to pin (see tests/test_ci_gates.py)."""
    import ast

    tree = ast.parse(open(os.path.abspath(__file__), encoding="utf-8").read())
    # AST, not text: this test's own docstring names the call it forbids, and a prose mention
    # must not read as the thing itself.
    gated = [n.args[0].value for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and n.func.attr == "importorskip" and n.args
             and isinstance(n.args[0], ast.Constant)]
    assert not gated, (f"this file skips itself when {gated} is absent, which is every job in the "
                       f"engine CI matrix — it would run nowhere")
