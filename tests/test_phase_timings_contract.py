"""The `.phase_timings.json` sidecar contract, pinned against a sidecar the REAL engine wrote.

Why this file exists rather than another stubbed case in webapp/tests: the bug it guards was
invisible to stubs by construction.

`webapp/backend/ingest._assert_redaction_phases_ran` refuses a `--redact-folder` run whose scrub
phase failed inside the engine — the check that stops Atlas handing a field engineer a workbook
full of real client data under a "share-safe" banner. It has two independent signals: this sidecar
(`ok: false`) and the engine's `[SKIP] Phase …` line on stderr.

The sidecar arm was DEAD. It iterated the file as a bare list of rows; the engine writes a dict
keyed by "phases". Iterating a dict yields its KEYS, so `str.get(...)` raised `AttributeError`,
which a defensive `except (OSError, ValueError, TypeError, AttributeError): pass` swallowed — on
every real run, silently, leaving one signal where the docstring promised two.

It survived review and two independent refuter waves because the unit test covering it FABRICATED
the sidecar in the shape the buggy parser expected. The stub and the bug agreed with each other.
A hand-written fixture encodes the author's belief about the producer's format — the same belief
that produced the parser bug — so it can only ever confirm it.

The fix for that class of blindness is to test the consumer against the producer's ACTUAL output,
which is what this file does. It lives in tests/ because that is where running the real engine is
the established discipline (webapp/tests deliberately always fakes the subprocess).
"""
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def test_the_consumer_parses_a_sidecar_the_real_engine_wrote(tmp_path):
    """Run the real pipeline with --redact and feed its sidecar to the real parser."""
    pytest.importorskip("fastapi")   # webapp deps are optional in the engine-only CI matrix
    from webapp.backend import ingest as ing
    from test_pipeline_golden import _run_pipeline

    # --redact, because that is the only run whose sidecar this consumer ever reads, and the two
    # phases it keys on exist only under that flag.
    _snap, xlsx = _run_pipeline(tmp_path, extra_args=["--redact"])
    sidecar = os.path.splitext(str(xlsx))[0] + ".phase_timings.json"
    assert os.path.isfile(sidecar), "the engine wrote no phase-timings sidecar"

    with open(sidecar, encoding="utf-8") as f:
        raw = json.load(f)
    rows = ing._phase_rows(raw)
    assert rows, (f"the consumer parsed no rows out of a REAL sidecar (top-level "
                  f"{type(raw).__name__}, keys {sorted(raw) if isinstance(raw, dict) else 'n/a'})")
    assert all(isinstance(r, dict) and "phase" in r and "ok" in r for r in rows), rows[:3]

    # ...and every phase name the refusal keys on is really spelled that way in a real run. A
    # renamed phase would retire the check just as silently as the shape mismatch did.
    names = {str(r["phase"]).lower() for r in rows}
    assert set(ing._REDACTION_PHASES) <= names, (
        f"a phase the redaction check watches for does not appear in a real --redact run.\n"
        f"  watched: {sorted(ing._REDACTION_PHASES)}\n"
        f"  missing: {sorted(set(ing._REDACTION_PHASES) - names)}")


def test_the_refusal_actually_fires_on_a_real_failed_phase(tmp_path):
    """End to end, no stubs: a real sidecar with ok=false on a real phase name must be REFUSED.

    Belt and braces on top of the parser test — it is the refusal, not the parse, that keeps an
    unredacted workbook from being handed over, and only the whole path proves that."""
    pytest.importorskip("fastapi")
    from webapp.backend import ingest as ing
    from test_pipeline_golden import _run_pipeline

    _snap, xlsx = _run_pipeline(tmp_path, extra_args=["--redact"])
    sidecar = os.path.splitext(str(xlsx))[0] + ".phase_timings.json"
    with open(sidecar, encoding="utf-8") as f:
        real = json.load(f)

    # Flip the real run's own row for a watched phase to ok=false — the engine's exact shape,
    # its exact phase spelling, only the outcome changed.
    target = ing._REDACTION_PHASES[0]
    hit = [r for r in real["phases"] if str(r["phase"]).lower() == target]
    assert hit, f"{target!r} not in the real sidecar"
    hit[0]["ok"] = False
    with open(sidecar, "w", encoding="utf-8") as f:
        json.dump(real, f)

    from pathlib import Path
    with pytest.raises(ing.EngineRunError) as e:
        ing._assert_redaction_phases_ran(Path(str(xlsx)), engine_output="")   # stderr arm silent
    assert "REDACTION PHASE FAILED" in str(e.value) and target in str(e.value)


def test_a_clean_real_run_is_not_refused(tmp_path):
    """The other edge: the check must not fire on a healthy run. A guard that cannot stay silent
    is as useless as one that cannot speak, and this one gates every field redaction."""
    pytest.importorskip("fastapi")
    from pathlib import Path

    from webapp.backend import ingest as ing
    from test_pipeline_golden import _run_pipeline

    _snap, xlsx = _run_pipeline(tmp_path, extra_args=["--redact"])
    ing._assert_redaction_phases_ran(Path(str(xlsx)), engine_output="")   # must not raise
