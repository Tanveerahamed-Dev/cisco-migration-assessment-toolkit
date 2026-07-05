"""ssot.abstention_reason — the coverage-honest core made callable (universal-best roadmap W3-1 backend).

NotebookLM's "honest abstention" lesson, grounded in our doctrine: absence must NEVER silently read as
"healthy". This distinguishes the three kinds of absence the engine has always cared about but never exposed
as one callable primitive — a device/axis that was never collected (a blind spot) vs collected-but-empty (a
genuine clean result) vs published — plus a device-level override so any fact about an UN-collected device is
'not_collected', not a clean result. Pure presence/absence logic over the snapshot; no model, no egress.
"""
from cisco_toolkit import ssot


def _snap():
    return {
        "collection_completeness": {
            "summary": {"inventory": 3, "complete": 1, "partial": 1, "not_collected": 1},
            "devices": [
                {"host": "CS01", "status": "not collected", "data_quality": 0, "missing": ["show version"]},
                {"host": "DS02", "status": "partial", "data_quality": 50, "missing": ["show vpc"]},
            ]},
        "fhrp": [],                                   # collected, nothing found
        "vpc": {"core1": {"domain_id": 1}},           # collected, non-empty
        "executive_brief": {"scale": {"n_devices": 303, "n_vlans": 202}},
        # stp_roots deliberately ABSENT
    }


def test_abstention_distinguishes_the_kinds_of_absence():
    s = _snap()
    assert ssot.abstention_reason(s, "fhrp") == "collected_but_empty"          # ran, nothing found
    assert ssot.abstention_reason(s, "vpc") == "published"                     # present, non-empty
    assert ssot.abstention_reason(s, "stp_roots") == "not_collected"           # axis absent entirely
    assert ssot.abstention_reason(s, "executive_brief.scale.n_vlans") == "published"   # dotted path, present
    assert ssot.abstention_reason(s, "executive_brief.scale.mtu") == "not_collected"   # dotted path, absent


def test_abstention_device_blind_spot_overrides_the_fact():
    s = _snap()
    # an un-collected device: ANY fact about it is not_collected — never a clean 'no FHRP -> healthy' result
    assert ssot.abstention_reason(s, "vpc", device="CS01") == "not_collected"
    # a PARTIAL device (some data collected) falls through to the fact's own presence
    assert ssot.abstention_reason(s, "vpc", device="DS02") == "published"
    # a fully-collected device (not in the blind-spot list) falls through too
    assert ssot.abstention_reason(s, "vpc", device="core1") == "published"


def test_abstention_is_total_on_bad_input():
    assert ssot.abstention_reason(None, "fhrp") == "not_collected"
    assert ssot.abstention_reason({}, "fhrp") == "not_collected"
    assert ssot.abstention_reason({"fhrp": 0}, "fhrp") == "collected_but_empty"   # zero/empty scalar


def test_abstention_wrapper_of_empties_is_not_published():
    """DEEP-empty, not shallow-falsy (adversarial-review finding, 2026-07-05): a section produced by a
    compute that ALWAYS returns its keys but found nothing — e.g. addressing_conflicts
    {'dup_ip': [], 'dup_subnet': []} (zero conflicts) — is truthy, so a shallow `not val` mislabels it
    'published' (a green "seen" row for a genuinely-empty result — the exact Law-3 inversion this module
    exists to prevent). It must read 'collected_but_empty'."""
    s = {
        "addressing_conflicts": {"dup_ip": [], "dup_subnet": []},           # wrapper of empty lists
        "feature_compliance": {"features": [], "summary": {"n_features": 0}},  # nested all-zero/empty
        "multicast_intelligence": {"groups": [], "querier": {"n_querier_vlans": 0}},
        "vpc": {"core1": {"domain_id": 1}},                                 # a REAL leaf -> stays published
        "qos": {"policies": [{"name": "VOICE"}], "notes": []},              # partial content -> published
    }
    assert ssot.abstention_reason(s, "addressing_conflicts") == "collected_but_empty"
    assert ssot.abstention_reason(s, "feature_compliance") == "collected_but_empty"
    assert ssot.abstention_reason(s, "multicast_intelligence") == "collected_but_empty"
    assert ssot.abstention_reason(s, "vpc") == "published"        # deep-empty must not over-reach
    assert ssot.abstention_reason(s, "qos") == "published"        # any real leaf keeps it published


def test_abstention_device_match_is_case_insensitive():
    """Device names vary in case between devices.json and CDP/show-text hostnames. A blind-spot device must be
    recognised regardless of case — else an un-collected device queried with different case escapes the
    blind-spot guard and its facts read 'published' (false-health). (adversarial-verify finding H-1)"""
    s = {"collection_completeness": {"devices": [{"host": "Switch-01", "status": "not collected"}]},
         "vpc": {"domain": 1}}
    assert ssot.abstention_reason(s, "vpc", device="Switch-01") == "not_collected"   # exact
    assert ssot.abstention_reason(s, "vpc", device="switch-01") == "not_collected"   # lower
    assert ssot.abstention_reason(s, "vpc", device="SWITCH-01") == "not_collected"   # upper
