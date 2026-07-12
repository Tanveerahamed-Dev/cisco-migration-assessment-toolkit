"""Tests for the PIR / As-Executed Cutover Record renderer (webapp.backend.pir_docx).

Scope (P3-W2): the module had ZERO direct coverage (Dimension H). This pins the two PURE, user-facing
formatters that render every timestamp and duration in the PIR document — their edge cases (absent ->
"—", invalid passthrough, the h/m rollover) are exactly the kind of silent-wrong-label bug the
deliverable-excellence standard exists to prevent. The full write_pir_docx renderer is an integration
over the execution-state model (cutover.build_plan -> start_run -> a rich snapshot fixture) and is
deferred to a change that focuses on that model, rather than pinned here against a guessed fixture.
"""
from webapp.backend import pir_docx as P


def test_fmt_ts_absent_is_emdash():
    for empty in (None, "", 0):
        assert P._fmt_ts(empty) == "—"          # absent -> em-dash, never a fabricated time


def test_fmt_ts_valid_iso_is_normalized():
    assert P._fmt_ts("2026-07-12T14:30:05") == "2026-07-12 14:30:05"
    assert P._fmt_ts("2026-07-12") == "2026-07-12 00:00:00"   # date-only widens to midnight


def test_fmt_ts_invalid_passes_through():
    # a non-ISO string is shown as-is (better a raw stamp than a crash or a fabricated one)
    assert P._fmt_ts("last Tuesday") == "last Tuesday"


def test_fmt_min_non_int_is_emdash():
    for bad in (None, "abc", object()):
        assert P._fmt_min(bad) == "—"


def test_fmt_min_zero_and_negative():
    assert P._fmt_min(0) == "0 min"
    assert P._fmt_min(-5) == "0 min"                 # clamped, never a negative duration


def test_fmt_min_under_an_hour():
    assert P._fmt_min(1) == "1 min"
    assert P._fmt_min(59) == "59 min"


def test_fmt_min_hour_rollover_zero_pads():
    assert P._fmt_min(60) == "1h00m"
    assert P._fmt_min(90) == "1h30m"
    assert P._fmt_min(125) == "2h05m"                # minutes zero-pad to two digits


def test_fmt_min_accepts_int_like_strings():
    assert P._fmt_min("45") == "45 min"              # int() coercion path
