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
