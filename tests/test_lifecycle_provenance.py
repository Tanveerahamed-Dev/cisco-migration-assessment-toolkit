"""Collection-time provenance for EoL bands + deliverable cover dates (wave R2-1-01 + R2-3-01).

The lifecycle bands and the "Snapshot captured" cover date must anchor to WHEN THE EVIDENCE WAS
COLLECTED, not the wall-clock day the pipeline happens to (re)run. Otherwise a "frozen" assessment
silently re-classifies devices against today's calendar -- the Nexus-5600 LDoS boundary (2026-04-30)
alone flips 15 Meridian devices Near->Past in a single day -- and every regenerated cover claims the network
was sampled on a day nothing was actually collected.
"""
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import COLLECT_PARSE_V3_23_0 as cp                        # noqa: E402
from cisco_toolkit.analyze import compute_lifecycle_risk  # noqa: E402


# --- _derive_collected_at: recover the collection instant on a --no-collect re-analysis ---

def test_derive_collected_at_parses_dir_timestamp():
    """The collection instant is recovered from the dir name's YYYYMMDD_HHMMSS stamp (the canonical case)."""
    iso, defaulted = cp._derive_collected_at(True, "migration_collection_20260613_063201",
                                             "migration_collection_20260613_063201")
    assert iso.startswith("2026-06-13T06:32:01"), iso
    assert defaulted is False


def test_derive_collected_at_live_run_is_now():
    """A live collection legitimately stamps now() and is NOT flagged as defaulted."""
    iso, defaulted = cp._derive_collected_at(False, "", "/anything")
    assert defaulted is False
    assert iso[:4].isdigit() and "T" in iso


def test_derive_collected_at_member_mtime_fallback(tmp_path):
    """No timestamp in the dir name -> earliest member-file mtime is authoritative (not defaulted)."""
    d = tmp_path / "raw_exports"
    d.mkdir()
    f = d / "core1_show_version.txt"
    f.write_text("x", encoding="utf-8")
    early = time.mktime((2021, 3, 10, 8, 0, 0, 0, 0, -1))
    os.utime(f, (early, early))
    iso, defaulted = cp._derive_collected_at(True, str(d), str(d))
    assert iso.startswith("2021-03-10"), iso
    assert defaulted is False


def test_derive_collected_at_unparseable_is_flagged(tmp_path):
    """A --no-collect dir with no timestamp in the name and no member files -> last-resort now(), flagged."""
    d = tmp_path / "exports_no_stamp"
    d.mkdir()
    iso, defaulted = cp._derive_collected_at(True, str(d), str(d))
    assert defaulted is True


# --- collected_at's offset: decided by a DECLARED zone, never by the process TZ of the host that re-renders ---
# F9: the engine-built demo fleet's collected_at took the regenerating host's UTC offset (+03:00 on one
# workstation, +00:00 on a hosted runner), so the same evidence produced different bytes per machine.

_STAMP_DIR = "collection_20260807_000000"


def _host_local(hours):
    """A `datetime` class for a host whose local zone is UTC`hours`: it answers exactly the local-zone reads
    the engine makes when no zone is declared -- naive now()/fromtimestamp() as that host's wall clock, and
    astimezone() with no argument -- and leaves every explicitly zoned call untouched. Patched over
    COLLECT_PARSE's `datetime`, it moves the host zone on every platform (time.tzset is POSIX-only)."""
    local = timezone(timedelta(hours=hours))

    def _as(cls, d):
        return cls(d.year, d.month, d.day, d.hour, d.minute, d.second, d.microsecond, d.tzinfo, fold=d.fold)

    class _HostLocal(datetime):
        @classmethod
        def now(cls, tz=None):
            return _as(cls, datetime.now(local).replace(tzinfo=None) if tz is None else datetime.now(tz))

        @classmethod
        def fromtimestamp(cls, t, tz=None):
            return _as(cls, datetime.fromtimestamp(t, local).replace(tzinfo=None) if tz is None
                       else datetime.fromtimestamp(t, tz))

        def astimezone(self, tz=None):
            target = local if tz is None else tz
            aware = self if self.tzinfo is not None else self.replace(tzinfo=local)
            return datetime.astimezone(aware, target)

    return _HostLocal


def test_the_field_default_reads_a_dir_stamp_in_the_host_zone(monkeypatch):
    """Undeclared -- the field default, unchanged -- a naive stamp is the collecting host's local wall clock
    (main() names a live run's directory from datetime.now()), so it is read in the host's zone. This also
    proves the simulated host zone REACHES the engine's read: without it, the declared-zone tests below
    would pass whatever the engine did."""
    assert cp._COLLECTION_TZ is None, "the engine's field default must stay the host's local zone"
    seen = {}
    for hours in (3, -5):
        monkeypatch.setattr(cp, "datetime", _host_local(hours))
        seen[hours] = cp._derive_collected_at(True, _STAMP_DIR, _STAMP_DIR)
    assert seen == {3: ("2026-08-07T00:00:00+03:00", False), -5: ("2026-08-07T00:00:00-05:00", False)}


def test_a_declared_zone_makes_a_dir_stamp_independent_of_the_host_zone(monkeypatch):
    """Declared, collected_at is a pure function of the stamp: one string under every host zone, with the
    declared zone's explicit offset -- the bytes the demo fleet publishes wherever it is regenerated."""
    monkeypatch.setattr(cp, "_COLLECTION_TZ", timezone.utc)
    for hours in (3, -5, 0):
        monkeypatch.setattr(cp, "datetime", _host_local(hours))
        assert cp._derive_collected_at(True, _STAMP_DIR, _STAMP_DIR) == ("2026-08-07T00:00:00+00:00", False)


def test_a_declared_zone_states_every_other_branch_in_it_and_keeps_true_instants(tmp_path, monkeypatch):
    """The mtime fallback, a live run's now() and the flagged last resort are true instants: a declared zone
    renders them in its own offset (the instant unchanged) instead of the host's."""
    exports = tmp_path / "raw_exports"
    exports.mkdir()
    capture = exports / "core1_show_version.txt"
    capture.write_text("x", encoding="utf-8")
    instant = datetime(2021, 3, 10, 8, 0, 0, tzinfo=timezone.utc)
    os.utime(capture, (instant.timestamp(), instant.timestamp()))
    empty = tmp_path / "exports_no_stamp"
    empty.mkdir()
    monkeypatch.setattr(cp, "_COLLECTION_TZ", timezone.utc)
    for hours in (3, -5):
        monkeypatch.setattr(cp, "datetime", _host_local(hours))
        assert cp._derive_collected_at(True, str(exports), str(exports)) == ("2021-03-10T08:00:00+00:00", False)
        for (iso, defaulted), flagged in ((cp._derive_collected_at(False, "", "/anything"), False),
                                          (cp._derive_collected_at(True, str(empty), str(empty)), True)):
            assert defaulted is flagged
            assert iso.endswith("+00:00"), iso
            assert abs(datetime.fromisoformat(iso) - datetime.now(timezone.utc)) < timedelta(minutes=5), iso


@pytest.mark.skipif(not hasattr(time, "tzset"),
                    reason="the process TZ can be switched at runtime only where time.tzset exists (POSIX); "
                           "the simulated-host tests above cover every platform")
def test_a_declared_zone_holds_under_a_real_process_tz_switch(monkeypatch):
    """The same contract through the REAL C-level local-zone read: the process TZ is switched with the TZ
    environment variable + time.tzset (POSIX offset strings, so no tz database is needed), and restored."""
    stated = {}
    try:
        for spec, host_offset in (("QAT-3", "+03:00"), ("EST+5", "-05:00")):
            monkeypatch.setenv("TZ", spec)
            time.tzset()
            monkeypatch.setattr(cp, "_COLLECTION_TZ", None)
            assert cp._derive_collected_at(True, _STAMP_DIR, _STAMP_DIR)[0] == "2026-08-07T00:00:00" + host_offset
            monkeypatch.setattr(cp, "_COLLECTION_TZ", timezone.utc)
            stated[spec] = cp._derive_collected_at(True, _STAMP_DIR, _STAMP_DIR)
    finally:
        monkeypatch.undo()
        time.tzset()
    assert stated == {"QAT-3": ("2026-08-07T00:00:00+00:00", False),
                      "EST+5": ("2026-08-07T00:00:00+00:00", False)}


# --- compute_lifecycle_risk: bands depend ONLY on the passed asof, which it echoes back (provenance) ---

def test_lifecycle_asof_is_returned_and_pinned():
    # Catalyst 3650 LDoS 2026-10-31 is copied from Cisco EOL13617.
    devs = {"sw1": {"model": "WS-C3650-48P", "sw_version": "16.12.10"}}
    r = compute_lifecycle_risk(devs, asof="2026-11-13")
    assert r["asof"] == "2026-11-13"
    assert r["summary"]["asof"] == "2026-11-13"
    assert r["summary"]["by_band"].get("Past-LDoS") == 1


def test_lifecycle_boundary_drift_guard():
    """The Catalyst-3650 LDoS boundary flips Near->Past across ONE calendar day -- exactly why asof must be
    pinned to collection time rather than wall-clock-at-regen. Locks the boundary so a refactor can't
    silently neutralise the sensitivity."""
    devs = {
        f"sw{i}": {"model": "WS-C3650-48P", "sw_version": "16.12"}
        for i in range(3)
    }
    on_boundary = compute_lifecycle_risk(devs, asof="2026-10-31")["summary"][
        "by_band"
    ]
    day_after = compute_lifecycle_risk(devs, asof="2026-11-01")["summary"][
        "by_band"
    ]
    assert on_boundary.get("Past-LDoS", 0) == 0   # exactly on LDoS, strict '>' -> not yet past
    assert day_after.get("Past-LDoS", 0) == 3     # one day later, all past
    assert on_boundary != day_after
