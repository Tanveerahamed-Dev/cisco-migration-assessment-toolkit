"""[audit-5 totality-crash batch] Malformed / hostile snapshot sections (a truthy non-list, or a non-dict
ELEMENT inside an otherwise valid list) must DEGRADE, never raise -- several of these paths are reachable from
the UNAUTHENTICATED webapp snapshot-upload / deliverable routes, where a raw exception escapes as an HTTP 500.
Each test plants a non-dict element in a section whose per-row `.get()` previously crashed."""


def test_compute_design_blueprint_tolerates_nondict_section_elements():
    """[#0/#5] _signals + _role_counts iterate _as_list(section) and call .get() directly on each element, so a
    bare string / int / None ROW in l3_forwarding / health_scores / overlay / copp / fhrp_detail crashed the
    unguarded /design + /architecture_coverage endpoints (AttributeError 'str' object has no attribute 'get')."""
    from cisco_toolkit.design_advisor import compute_design_blueprint
    hostile = {
        "devices": {"c": {}},
        "l3_forwarding": ["c v10 single-gateway", None, 7],          # proven repro: string rows
        "health_scores": ["notadict", None, {"role": "core"}],       # _role_counts row
        "overlay": {"h": {"nve_peers": ["x", None], "evpn_neighbors": [1], "nve_vni": [None]}},
        "copp": {"h": ["str", None, {"class": "x", "drops": 5}]},
        "fhrp_detail": {"h": ["str", None]},
    }
    bp = compute_design_blueprint(hostile, {})                       # must NOT raise
    assert isinstance(bp, dict)
