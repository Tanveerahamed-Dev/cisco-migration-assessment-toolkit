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


def test_vlan_inventory_wellformed_queriers_still_counted():
    """Non-vacuity companion: the isinstance coercion must be a NO-OP on well-formed input -- a real
    querier VLAN must still be inventoried, so an over-broad guard that empties the list fails here."""
    snap = _base(service_map={"multicast": {"igmp_queriers": [{"vlan": "610", "querier": "10.0.0.1"}]}})
    vlans = vlan_inventory(snap)                      # returns ordered [(vid:int, name:str), ...]
    assert 610 in {vid for vid, _name in vlans}, f"well-formed querier VLAN dropped: {vlans}"
