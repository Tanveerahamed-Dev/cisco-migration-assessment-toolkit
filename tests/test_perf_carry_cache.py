"""Plan-A #12: the model-scoped `_carry` cache memoizes the pure `_link_carries` primitive that
compute_failure_impact and compute_causality_chains re-ask O(H) times per (link, vid). Pins
OUTPUT-equivalence (cache == direct call) and that it truly memoizes (deterministic, not timing).
The pipeline golden is the second oracle: failure_impact + causality stay byte-identical."""
import json
import os

from cisco_toolkit import analyze
from cisco_toolkit.model import InterfaceData

HERE = os.path.dirname(os.path.abspath(__file__))


def _model():
    with open(os.path.join(HERE, "golden", "snapshot.json"), encoding="utf-8") as f:
        snap = json.load(f)
    ai = {h: {p: InterfaceData.from_sparse(r) for p, r in ports.items()}
          for h, ports in snap["interfaces"].items()}
    m = analyze.build_network_model(ai)
    m.pop("_carry_cache", None)
    return m


def test_carry_is_equivalent_to_link_carries_for_every_link_vid():
    m = _model()
    assert m["links"] and m["vlans"], "golden model must carry links + vlans to exercise _carry"
    for vid in m["vlans"]:
        for link in m["links"]:
            assert analyze._carry(m, link, vid) == analyze._link_carries(link, vid)


def test_carry_cache_memoizes_and_never_recomputes():
    m = _model()
    link, vid = m["links"][0], sorted(m["vlans"])[0]
    r = analyze._carry(m, link, vid)
    assert (vid, id(link)) in m["_carry_cache"] and m["_carry_cache"][(vid, id(link))] == r
    n = len(m["_carry_cache"])
    for _ in range(100):
        assert analyze._carry(m, link, vid) == r          # repeated calls return the cached value
    assert len(m["_carry_cache"]) == n                     # and add no new entries (pure memoization)


def test_not_carried_empty_string_is_cached_not_treated_as_absent():
    """'' (not-carried) is a real cached value; the None sentinel means 'not yet computed'. A link that
    carries a given VLAN under no path must still cache '' and not be recomputed. Uses a bogus VLAN id that
    no link carries so the '' branch is GUARANTEED to exercise (the old golden-scan asserted nothing when
    every real (link,vid) happened to be carried)."""
    m = _model()
    link = m["links"][0]
    bogus_vid = 999999                                       # a VLAN no link is configured to carry
    assert analyze._link_carries(link, bogus_vid) == ""      # precondition: genuinely not carried (fails loud if not)
    m.pop("_carry_cache", None)
    assert analyze._carry(m, link, bogus_vid) == ""          # returns the empty string...
    assert m["_carry_cache"][(bogus_vid, id(link))] == ""    # ...and CACHES it (not re-treated as the absent None)
    n = len(m["_carry_cache"])
    assert analyze._carry(m, link, bogus_vid) == "" and len(m["_carry_cache"]) == n   # 2nd call: no recompute
