"""Opt-in PSIRT advisory lane in ``self_healing`` — activation test.

Before this, `intel_feed` (load/verify/match_fleet/advisory_drift_items) and
`self_healing.propose_remediation(extra_items=…)` were both built + tested but never connected: nothing loaded
a feed and folded its fleet-matched advisories into the propose-only remediation plan. `advisory_remediation`
(and the CLI ``--intel <dir>``) wires them: a provenance-verified PSIRT feed matched to the CURRENT fleet's
platforms produces ``kind='advisory'`` remediation items (owner/rollback/NRFU), exactly like a snapshot
regression. Coverage-honest: no match / no feed → no items (absence is absence, not "no advisories").
"""
from cisco_toolkit import intel_feed, self_healing

# Baseline == current (no snapshot regression), so any plan item is purely the folded advisory.
_SNAP = {
    "devices": {"sw1": {"platform": "C9300", "sw_version": "17.9"}},
    "health_scores": [{"switch": "sw1", "band": "Good", "score": 90}],
}


def _write_feed(tmp_path, entries):
    (tmp_path / "feed-test.jsonl").write_text(
        intel_feed.build_feed(entries, generated="2026-07-23"), encoding="utf-8")
    return str(tmp_path)


def test_matching_advisory_folds_into_remediation(tmp_path):
    intel_dir = _write_feed(tmp_path, [
        {"id": "CVE-2026-0001", "title": "IOS-XE priv-esc", "severity": "high", "affected": ["C9300"]},
    ])
    bundle = self_healing.advisory_remediation(_SNAP, _SNAP, intel_dir)
    advisory = [p for p in bundle["result"]["plan"] if p["kind"] == "advisory"]
    assert len(advisory) == 1, bundle["result"]["plan"]
    it = advisory[0]
    assert it["subject"] == "CVE-2026-0001"
    assert it["root_cause_owner"] == "config-security-auditor"
    assert it["rollback"] and it["verifier"] and it["proposed_intent"]      # propose-only scaffold present
    assert bundle["hits"] and bundle["hits"][0]["id"] == "CVE-2026-0001"     # feed hit surfaced (coverage-honest)


def test_non_matching_advisory_yields_no_items(tmp_path):
    # advisory affects a platform NOT in the fleet -> honest absence (match_fleet does not guess)
    intel_dir = _write_feed(tmp_path, [
        {"id": "CVE-2026-0002", "title": "NX-OS bug", "severity": "critical", "affected": ["Nexus9000"]},
    ])
    bundle = self_healing.advisory_remediation(_SNAP, _SNAP, intel_dir)
    assert [p for p in bundle["result"]["plan"] if p["kind"] == "advisory"] == []
    assert bundle["hits"] == []


def test_missing_feed_dir_is_honest_absence(tmp_path):
    # an intel dir with no feed at all -> no advisories, and load_feeds says so (not a crash, not a false clean)
    bundle = self_healing.advisory_remediation(_SNAP, _SNAP, str(tmp_path / "empty"))
    assert [p for p in bundle["result"]["plan"] if p["kind"] == "advisory"] == []
    assert bundle["loaded"]["n_feeds"] == 0


def test_plain_path_never_emits_advisory_items():
    # the no --intel path is unchanged: propose_remediation with no extra_items has no advisory kind
    res = self_healing.propose_remediation(_SNAP, _SNAP)
    assert [p for p in res["plan"] if p["kind"] == "advisory"] == []
