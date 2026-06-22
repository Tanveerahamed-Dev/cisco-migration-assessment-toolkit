"""Collection-time provenance for EoL bands + deliverable cover dates (wave R2-1-01 + R2-3-01).

The lifecycle bands and the "Snapshot captured" cover date must anchor to WHEN THE EVIDENCE WAS
COLLECTED, not the wall-clock day the pipeline happens to (re)run. Otherwise a "frozen" assessment
silently re-classifies devices against today's calendar -- the Nexus-5600 LDoS boundary (2026-04-30)
alone flips 15 [HISTORY-REDACTED] devices Near->Past in a single day -- and every regenerated cover claims the network
was sampled on a day nothing was actually collected.
"""
import os
import sys
import time

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


# --- compute_lifecycle_risk: bands depend ONLY on the passed asof, which it echoes back (provenance) ---

def test_lifecycle_asof_is_returned_and_pinned():
    devs = {"nx1": {"model": "N5K-C5672UP", "sw_version": "7.3(0)N1(1)"}}  # Nexus 5600, ldos 2026-04-30
    r = compute_lifecycle_risk(devs, asof="2026-06-13")
    assert r["asof"] == "2026-06-13"
    assert r["summary"]["asof"] == "2026-06-13"
    assert r["summary"]["by_band"].get("Past-LDoS") == 1  # Jun-13 is past the Apr-30 LDoS


def test_lifecycle_boundary_drift_guard():
    """The Nexus-5600 LDoS boundary flips Near->Past across ONE calendar day -- exactly why asof must be
    pinned to collection time rather than wall-clock-at-regen. Locks the boundary so a refactor can't
    silently neutralise the sensitivity."""
    devs = {f"nx{i}": {"model": "N5K-C5672UP", "sw_version": "7.3"} for i in range(3)}
    on_boundary = compute_lifecycle_risk(devs, asof="2026-04-30")["summary"]["by_band"]
    day_after = compute_lifecycle_risk(devs, asof="2026-05-01")["summary"]["by_band"]
    assert on_boundary.get("Past-LDoS", 0) == 0   # exactly on LDoS, strict '>' -> not yet past
    assert day_after.get("Past-LDoS", 0) == 3     # one day later, all past
    assert on_boundary != day_after
