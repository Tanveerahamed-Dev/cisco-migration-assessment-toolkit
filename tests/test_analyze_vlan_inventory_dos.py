"""Stored-DoS guard for the SHARED VLAN derivation, `analyze.vlan_inventory`.

`vlan_inventory(snap)` is the one canonical VLAN recount and it is imported by BOTH deliverable
writers -- `cisco_toolkit/design.py` and `cisco_toolkit/crd.py` -- so a crash here 500s more than one
route. It reads an attacker-controlled snapshot: the upload validates only
`isinstance(snap, dict) and "devices" in snap` and stores the JSON verbatim, then
`deliverables.generate(kind, snap, ...)` re-raises -> HTTP 500. The POST is accepted 201 first, so
this is a *stored* availability DoS.

The bug this pins: the function isinstance-guards the `service_map` and `multicast` CONTAINERS but
then falls back to a falsy-only `or []` for `igmp_queriers` itself, so a truthy non-list survives and
`for q in 5` raises `TypeError: 'int' object is not iterable`. The surrounding loops in the very same
function already do this correctly (`(_ifaces if isinstance(_ifaces, dict) else {})`,
`(_l3f if isinstance(_l3f, list) else [])`) -- this read was the lone holdout.
"""
import pytest

from cisco_toolkit.analyze import vlan_inventory


def _base(**over):
    snap = {"devices": {"sw1": {"hostname": "sw1"}}}
    snap.update(over)
    return snap


@pytest.mark.parametrize("bad", [5, "boom", {"k": 1}, 3.5, True],
                         ids=["int", "str", "dict", "float", "bool"])
def test_vlan_inventory_survives_truthy_nonlist_igmp_queriers(bad):
    """A truthy non-list `igmp_queriers` must degrade to empty, never raise."""
    snap = _base(service_map={"multicast": {"igmp_queriers": bad}})
    vlan_inventory(snap)          # must not raise


@pytest.mark.parametrize("bad", [5, "boom", [1, 2]], ids=["int", "str", "list"])
def test_vlan_inventory_survives_truthy_nondict_multicast(bad):
    """Companion: the `multicast` container itself (already guarded) stays safe."""
    snap = _base(service_map={"multicast": bad})
    vlan_inventory(snap)


# --- the string-leaf axis: a non-str `vlan` / `vlan_name` survives `or ""` and 500s .strip() -------
# A DIFFERENT mechanism from the container class above: the interface record IS a well-formed dict and
# the field IS present -- it is the LEAF type. `as_dict`/`as_list` cannot fix it; the repo's discipline
# is to str()-coerce every device string-field before .strip()/.lower().
_STR_LEAF_POISONS = [5, 1.5, True, [5], [1, 2], {"a": 1}]


@pytest.mark.parametrize("bad", _STR_LEAF_POISONS, ids=lambda v: type(v).__name__)
def test_vlan_inventory_survives_nonstr_vlan_leaf(bad):
    """`interfaces.<host>.<port>.vlan` as a non-str must degrade, not crash `.strip()`."""
    snap = _base(interfaces={"acc1": {"Gi1/0/5": {"switchport_mode": "Access", "vlan": bad}}})
    vlan_inventory(snap)


@pytest.mark.parametrize("bad", _STR_LEAF_POISONS, ids=lambda v: type(v).__name__)
def test_vlan_inventory_survives_nonstr_vlan_name_leaf(bad):
    """The `vlan_name` twin of the read above -- reachable only once `vlan` itself parses as digits,
    which is why a fuzz that stops at the first crash never reaches it."""
    snap = _base(interfaces={"acc1": {"Gi1/0/5": {"switchport_mode": "Access",
                                                  "vlan": "610", "vlan_name": bad}}})
    vlan_inventory(snap)


def test_vlan_inventory_wellformed_all_three_evidence_sources():
    """Non-vacuity companion for the str() coercion: all THREE evidence sources still contribute and
    the VLAN name still survives, so an over-broad guard that empties or blanks them fails here."""
    snap = _base(
        interfaces={"acc1": {"Gi1/0/5": {"switchport_mode": "Access", "vlan": "610",
                                         "vlan_name": "MEDIA"}}},
        l3_forwarding=[{"switch": "acc1", "vlan": "700"}],
        service_map={"multicast": {"igmp_queriers": [{"vlan": "800"}]}})
    assert vlan_inventory(snap) == [(610, "MEDIA"), (700, ""), (800, "")]


def test_vlan_inventory_wellformed_queriers_still_counted():
    """Non-vacuity companion: the isinstance coercion must be a NO-OP on well-formed input -- a real
    querier VLAN must still be inventoried, so an over-broad guard that empties the list fails here."""
    snap = _base(service_map={"multicast": {"igmp_queriers": [{"vlan": "610", "querier": "10.0.0.1"}]}})
    vlans = vlan_inventory(snap)                      # returns ordered [(vid:int, name:str), ...]
    assert 610 in {vid for vid, _name in vlans}, f"well-formed querier VLAN dropped: {vlans}"
