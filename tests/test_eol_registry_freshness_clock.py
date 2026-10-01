"""The retained registries' freshness verdict, proven with an INJECTED clock (never the day the test runs).

`data_authorities` is the pipeline's statement of the tool's registry health TODAY: whether each retained
data-authority registry (the Cisco EoX/EoL fixture among them) is still inside its freshness window
(`registry_integrity.SOURCE_MAX_AGE_DAYS` after its retrieval, and not future-dated beyond
`SOURCE_MAX_FUTURE_SKEW_SECONDS`). That is legitimately wall-clock product behaviour and the engine keeps it so;
the golden (tests/test_pipeline_golden.py) therefore pins this ONE clock to its evidence date instead of
freezing whatever day it was regenerated on. The logic the golden no longer exercises against the real
calendar is proven here, at instants chosen relative to the registry's own retrieval timestamp:

  * the policy function (`registry_integrity.source_freshness`, via its `now=` parameter): fresh, the exact
    boundary instant, the boundary DAY on both sides of it, stale, and both edges of the future-skew bound;
  * what the EoL registry publishes (`eoldb.registry_health`, the dict the pipeline stores verbatim at
    `data_authorities.eol`) at each of those instants -- judged through the module clock
    `registry_integrity.datetime`, which every registry freshness read goes through;
  * what the PIPELINE publishes for a fresh, an exact-boundary and a stale registry clock: data_authorities for
    EVERY published registry, the `assessment_integrity` failed-phase disclosure, the 'Assessment Integrity'
    sheet -- with the process wall clock deliberately on the OTHER side of the window each time, so the verdict
    can only have come from the registry clock (which proves it is the only clock the registries read).

The expected verdicts are derived by plain arithmetic from each registry's published retrieval timestamp and
policy fields -- never by calling the function under test.
"""
import json
import os
from datetime import datetime, timedelta, timezone

import pytest

from cisco_toolkit import eoldb, registry_integrity
from test_pipeline_golden import GOLDEN_DIR, _run_pipeline, _sheet_schema

_ONE_SECOND = timedelta(seconds=1)


def _eol_window():
    retrieved = datetime.fromisoformat(eoldb._EOL_FIXTURE_RETRIEVED_AT.replace("Z", "+00:00"))
    return retrieved, retrieved + timedelta(days=registry_integrity.SOURCE_MAX_AGE_DAYS)


def _expected_status(retrieved, max_age_days, skew_seconds, clock):
    """The policy, restated as arithmetic: stale strictly AFTER retrieval + max age, future-dated strictly
    BEFORE retrieval - skew, fresh on and between both edges."""
    age = (clock - retrieved).total_seconds()
    if age < -skew_seconds:
        return "future-dated"
    if age > max_age_days * 86_400:
        return "stale"
    return "fresh"


def _eol_cases():
    retrieved, boundary = _eol_window()
    skew = timedelta(seconds=registry_integrity.SOURCE_MAX_FUTURE_SKEW_SECONDS)
    boundary_day = boundary.replace(hour=0, minute=0, second=0)
    return [
        ("one day after retrieval", retrieved + timedelta(days=1), "fresh"),
        ("mid-window", retrieved + timedelta(days=90), "fresh"),
        ("boundary day, midnight", boundary_day, "fresh"),
        ("exact boundary instant", boundary, "fresh"),
        ("one second past the boundary", boundary + _ONE_SECOND, "stale"),
        ("boundary day, last second", boundary_day + timedelta(hours=23, minutes=59, seconds=59), "stale"),
        ("a year past the boundary", boundary + timedelta(days=365), "stale"),
        ("retrieval minus the full skew", retrieved - skew, "fresh"),
        ("one second beyond the skew", retrieved - skew - _ONE_SECOND, "future-dated"),
    ]


@pytest.mark.parametrize(("label", "clock", "status"), _eol_cases(), ids=[c[0] for c in _eol_cases()])
def test_source_freshness_policy_at_each_instant(label, clock, status):
    retrieved, _boundary = _eol_window()
    assert _expected_status(retrieved, registry_integrity.SOURCE_MAX_AGE_DAYS,
                            registry_integrity.SOURCE_MAX_FUTURE_SKEW_SECONDS, clock) == status, label
    got = registry_integrity.source_freshness(eoldb._EOL_FIXTURE_RETRIEVED_AT, now=clock)
    assert got["freshness_status"] == status, (label, got)
    assert got["source_fresh"] is (status == "fresh")
    assert got["source_stale"] is (status == "stale")
    assert got["source_future_dated"] is (status == "future-dated")
    assert got["source_age_days"] == round((clock - retrieved).total_seconds() / 86_400, 6)
    assert got["source_max_age_days"] == registry_integrity.SOURCE_MAX_AGE_DAYS
    assert got["source_retrieved_at"] == eoldb._EOL_FIXTURE_RETRIEVED_AT


def _eol_health_at(monkeypatch, instant):
    """eoldb.registry_health() with the registry clock (`registry_integrity.datetime.now`) pinned at `instant`.
    The retained-chain proof is memoised per process, so it is cleared on both sides."""
    class _RegistryClock(registry_integrity.datetime):
        @classmethod
        def now(cls, tz=None):
            return instant if tz is None else instant.astimezone(tz)

    monkeypatch.setattr(registry_integrity, "datetime", _RegistryClock)
    eoldb._runtime_source_proof.cache_clear()
    try:
        return eoldb.registry_health()
    finally:
        monkeypatch.undo()
        eoldb._runtime_source_proof.cache_clear()


@pytest.mark.parametrize(("label", "clock", "status"), _eol_cases(), ids=[c[0] for c in _eol_cases()])
def test_eol_registry_publishes_its_verdict_at_each_instant(monkeypatch, label, clock, status):
    """What `data_authorities.eol` says at each instant. Fresh (the exact boundary instant included): verified
    and authoritative, every row fixture-bound, usable. Stale or future-dated: the retained chain is refused
    with the reason named, nothing is authoritative, no row is fixture-bound, and the pack is NOT usable (which
    is what makes the pipeline disclose a failed phase) -- a registry too old or too new is never rendered as
    healthy."""
    retrieved, _boundary = _eol_window()
    health = _eol_health_at(monkeypatch, clock)
    assert health["freshness_status"] == status, (label, health)
    assert health["source_age_days"] == round((clock - retrieved).total_seconds() / 86_400, 6)
    if status == "fresh":
        assert health["status"] == "verified-authoritative", health
        assert health["authoritative"] is health["source_authoritative"] is True
        assert health["integrity_verified"] is health["retained_source_bytes_verified"] is True
        assert health["fixture_bound_rows"] == health["row_count"] > 0
        assert health["error"] == ""
        assert registry_integrity.pack_is_usable(health) is True
    else:
        assert health["status"] == "semantic-build-provenance-source-unverified", health
        assert health["authoritative"] is health["source_authoritative"] is False
        assert health["integrity_verified"] is health["retained_source_bytes_verified"] is False
        assert health["fixture_bound_rows"] == 0
        assert health["evidence_distribution"] == "unverified"
        assert f"Cisco EoL fixture is {status}" in health["error"], health["error"]
        assert registry_integrity.pack_is_usable(health) is False


def _pipeline_cases():
    retrieved, boundary = _eol_window()
    far_future = boundary + timedelta(days=400)
    inside = retrieved + timedelta(days=1)
    # (label, registry clock, process wall clock -- always on the OTHER side of the EoL window, eol status)
    return [
        ("fresh", retrieved + timedelta(days=90), far_future, "fresh"),
        ("exact-boundary", boundary, far_future, "fresh"),
        ("stale", boundary + _ONE_SECOND, inside, "stale"),
    ]


@pytest.mark.parametrize(("label", "registry_clock", "wall_clock", "eol_status"), _pipeline_cases(),
                         ids=[c[0] for c in _pipeline_cases()])
def test_pipeline_publishes_each_registry_verdict_at_the_injected_clock(
        tmp_path, label, registry_clock, wall_clock, eol_status):
    snap, xlsx = _run_pipeline(tmp_path, registry_clock=registry_clock.isoformat(),
                               wall_clock=wall_clock.isoformat())
    with open(os.path.splitext(xlsx)[0] + ".snapshot.json", encoding="utf-8") as f:
        written = json.load(f)
    ran_at = datetime.fromisoformat(written["generated_at"]).astimezone(timezone.utc)
    # non-vacuity: the process really ran on the other side of the EoL window from the registry clock
    retrieved, boundary = _eol_window()
    assert (ran_at > boundary) is (eol_status == "fresh"), (label, written["generated_at"])

    authorities = snap["data_authorities"]
    assert "eol" in authorities, sorted(authorities)
    stale_errors = []
    for name, health in authorities.items():
        published_retrieved = datetime.fromisoformat(health["source_retrieved_at"].replace("Z", "+00:00"))
        expected = _expected_status(published_retrieved, health["source_max_age_days"],
                                    health["source_max_future_skew_seconds"], registry_clock)
        assert health["freshness_status"] == expected, (label, name, health)
        assert health["source_age_days"] == round((registry_clock - published_retrieved).total_seconds()
                                                  / 86_400, 6), (label, name)
        assert registry_integrity.pack_is_usable(health) is (expected == "fresh"), (label, name, health)
        if expected != "fresh":
            assert expected in health["error"], (label, name, health["error"])
            stale_errors.append(health["error"])
    assert authorities["eol"]["freshness_status"] == eol_status, authorities["eol"]
    assert authorities["eol"]["authoritative"] is (eol_status == "fresh")

    integrity = snap.get("assessment_integrity")
    sheets = _sheet_schema(xlsx)
    if stale_errors:
        assert integrity, f"{label}: a registry is out of its window but no failed phase is disclosed"
        assert len(integrity["failed_phases"]) == len(stale_errors), integrity
        assert sorted(integrity["phase_errors"].values()) == sorted(stale_errors), integrity
        assert "Assessment Integrity" in sheets, sorted(sheets)
    else:
        assert integrity is None, integrity
        assert "Assessment Integrity" not in sheets, sorted(sheets)
    eol_phase = "EoL knowledge-base authority"
    if eol_status == "fresh":
        assert eol_phase not in ((integrity or {}).get("failed_phases") or []), integrity
    else:
        assert integrity["phase_errors"][eol_phase] == "Cisco EoL fixture is stale", integrity

    # The registry-health verdict never leaks into the lifecycle fold: the dossiers are the golden's in every case
    # (their bands are judged at the evidence date -- see test_pipeline_golden's dossier tests).
    with open(os.path.join(GOLDEN_DIR, "snapshot.json"), encoding="utf-8") as f:
        golden = json.load(f)
    assert snap["device_dossiers"] == golden["device_dossiers"], label
