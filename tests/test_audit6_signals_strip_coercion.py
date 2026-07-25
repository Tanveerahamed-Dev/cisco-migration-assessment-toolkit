"""[audit-6 leaf-coercion, DICT axis] Two `.strip()` sites in design_advisor._signals coerced a snapshot
string leaf with the `(x or "").strip()` idiom -- which does NOT str()-coerce, so a wrong-typed DICT/LIST
leaf (a recursive dict-poison over an uploaded / --compare / --trend snapshot) reached `.strip()` and raised
`AttributeError: 'dict' object has no attribute 'strip'`: a fail-soft HTTP 500 on the unauthenticated
/design + /architecture_coverage compute endpoints (compute_design_blueprint runs on the uploaded snapshot).

DISTINCT from the two sibling PRs, and precisely the gap they each left open:
  * PR #377 (numeric leaves) -- its whole-class fuzz INTENTIONALLY EXCLUDED the dict variant
    ("surfaces a separate ... axis tracked as its own follow-up").
  * PR #378 (the unhashable set-member / dict-KEY axis) -- its message defers "the residual .strip()/float()
    sites [to] the audit-6 class, PR #377".
These are those residual `.strip()` sites, both reachable ONLY through the dict axis:
  * shadow_infra[<host>][].device_id  (_signals, shadow-infra block)      -- `_did = (_n.get("device_id") or "").strip()`
  * routes[<host>][].next_hop         (_signals, static default-route block) -- `... and (_r.get("next_hop") or "").strip()`

Fix: str()-coerce the leaf before `.strip()` -- the exact pattern PR #377 used for cdp_neighbor / source /
port. Valid string/None data is byte-for-byte unchanged (`str(x or "") == (x or "")` for str and None), so
the static-default and shadow-infra signals keep their meaning; only a malformed leaf now degrades instead of
crashing. The CORE live/parse path (build.py) is untouched.

Non-vacuousness: reverting either one-line `str()` wrap re-raises AttributeError. Proven by the repro harness
in the PR description (pre-fix: both AttributeError; post-fix: both return a dict) and re-verified by a
git-revert run before merge. (Unique basename: pytest derives the module name from the filename, which must
not collide with tests/test_audit6_leaf_coercion.py or any other test module.)"""

import copy

from cisco_toolkit import design_advisor

POISON = {"x": 1}   # the recursive dict-poison fuzz's replacement value: an unhashable, non-str dict leaf


def _snap_static_default(next_hop):
    """Otherwise-valid; the ONLY failure surface is `next_hop`. A STATIC (source 's') 0.0.0.0/0 route with a
    present next-hop is what the static-default-route cutover-dependency detector flags."""
    return {
        "devices": {"SW1": {"hostname": "SW1"}},
        "health_scores": [{"switch": "SW1", "band": "Healthy", "role": "core", "score": 90}],
        "routes": {"SW1": [{"prefix": "0.0.0.0/0", "source": "S", "next_hop": next_hop}]},
    }


def _snap_shadow_infra(device_id):
    """Otherwise-valid; the ONLY failure surface is `device_id`. A shadow-infra neighbour whose canonical
    hostname is not in the assessed set surfaces as undocumented infrastructure."""
    return {
        "devices": {"SW1": {"hostname": "SW1"}},
        "health_scores": [{"switch": "SW1", "band": "Healthy", "role": "core", "score": 90}],
        "shadow_infra": {"SW1": [{"device_id": device_id, "platform": "cat9k", "proto": "cdp",
                                  "local_intf": "Gi1/0/1"}]},
    }


# --- the two named sites: a dict leaf must DEGRADE (no 500) through the real compute entry -------------------
def test_next_hop_dict_leaf_degrades_not_500():
    """[issue#2] routes[host][].next_hop == {'x':1} reached `(_r.get('next_hop') or '').strip()`.
    Non-vacuous: revert the str() wrap -> AttributeError: 'dict' object has no attribute 'strip'."""
    bp = design_advisor.compute_design_blueprint(_snap_static_default(POISON), {})
    assert isinstance(bp, dict)


def test_shadow_infra_device_id_dict_leaf_degrades_not_500():
    """[issue#3] shadow_infra[host][].device_id == {'x':1} reached `(_n.get('device_id') or '').strip()`.
    Non-vacuous: revert the str() wrap -> AttributeError: 'dict' object has no attribute 'strip'."""
    bp = design_advisor.compute_design_blueprint(_snap_shadow_infra(POISON), {})
    assert isinstance(bp, dict)


# --- the happy path is unchanged: str(x or "") is a drop-in for (x or "") on real string data ---------------
def test_valid_string_data_signals_unchanged():
    """The str()-coercion must not change valid-data behavior. A STATIC default with a real next-hop still
    flags the host; a non-static (source 'C') default still does NOT; a real shadow device_id still surfaces
    verbatim. (Grounded against _signals, the detector layer compute_design_blueprint consumes.)"""
    sig = design_advisor._signals(_snap_static_default("10.0.0.1"))
    assert sig["static_default_hosts"] == ["SW1"] and sig["static_default_n"] == 1

    sig_c = design_advisor._signals(
        {"devices": {"SW1": {}}, "routes": {"SW1": [{"prefix": "0.0.0.0/0", "source": "C",
                                                     "next_hop": "10.0.0.1"}]}})
    assert sig_c["static_default_hosts"] == []          # connected default is not a static-cutover dependency

    shadow = design_advisor._signals(_snap_shadow_infra("GHOST-SW"))["shadow_infra"]
    assert len(shadow) == 1 and shadow[0]["name"] == "GHOST-SW"


# --- whole reachable class (within scope): dict-poison EACH leaf individually, driven end-to-end -----------
def _leaf_paths(obj, _path=()):
    """Yield the path to every scalar leaf (str/int/float, not bool). Poisoning ONE leaf at a time (rest
    valid) is the faithful 'poison each leaf' fuzz -- and it stays non-vacuous for a gated field: poisoning
    the whole subtree at once would let a guarded sibling (a str()-coerced prefix/source) short-circuit the
    row BEFORE the field under test, hiding its regression."""
    if isinstance(obj, bool) or not isinstance(obj, (str, int, float, dict, list)):
        return
    if isinstance(obj, (str, int, float)):
        yield _path
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from _leaf_paths(v, _path + (k,))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _leaf_paths(v, _path + (i,))


def _set_path(obj, path, val):
    cur = obj
    for p in path[:-1]:
        cur = cur[p]
    cur[path[-1]] = val


def test_each_dict_poisoned_leaf_of_owned_sections_degrades():
    """Dict-poison EACH leaf of the two sections this fix owns (routes, shadow_infra) one at a time, keeping
    the rest valid, and drive the real compute_design_blueprint -- no single malformed leaf may 500 the
    /design + /architecture_coverage endpoints. Covers the target leaves (next_hop / device_id -- non-vacuous)
    AND their siblings (prefix / source / platform / proto / local_intf). Scoped to these two sections: a
    blanket golden-snapshot dict-poison also trips the still-open PR #377 / #378 sites, so it is not a clean
    whole-snapshot guard until those merge."""
    exercised = 0
    for base in (_snap_static_default("10.0.0.1"), _snap_shadow_infra("GHOST-SW")):
        for section in ("routes", "shadow_infra"):
            if section not in base:
                continue
            for path in _leaf_paths(base[section], (section,)):
                snap = copy.deepcopy(base)
                _set_path(snap, path, POISON)
                bp = design_advisor.compute_design_blueprint(snap, {})
                assert isinstance(bp, dict), f"HTTP-500 class: single-leaf dict-poison at {path} crashed compute"
                exercised += 1
    assert exercised >= 6      # routes: prefix/source/next_hop; shadow_infra: device_id/platform/proto/local_intf
