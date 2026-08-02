"""[audit-6 finding-#3 class, extended to the deliverable generators]

A device STRING-field in an externally-supplied snapshot (an interface vrf / switchport_mode / acl_in / acl_out
/ cdp_neighbor / port_channel / sw_version, a device ps_status / fan_status / temperature_status, a service
category) can be a truthy NON-string — a dict / list / number in a malformed or hostile upload. The idiom
`(x or "").strip()` / `.lower()` does NOT str-coerce, so a truthy non-str reaches `.strip()`/`.lower()` and
raises AttributeError, 500-ing the deliverable generator (fail-soft doctrine violation).

audit-6 finding #3 fixed exactly this class, but only in analyze.py (the cable map). This closes the identical
class in the crd / design / mop / runbook generators (str-coerce every device string-field before the string
op; byte-identical for a real str/None). Proven non-vacuous: reverting the str() coercions crashes each
generator with AttributeError at crd.py:41 / design.py:60 / mop.py:697 / runbook.py:332 (verified via
`git stash`)."""
import pytest

D = {"x": 1}   # a truthy dict where a device string-field is expected

_IFACE = {"switchport_mode": D, "vrf": D, "acl_in": D, "acl_out": D, "svi_ip": "10.0.0.1",
          "end_host_mac": D, "end_host_ip": D, "cdp_neighbor": D, "port_channel": D, "sw_version": D}

def _snap(iface, devices=None, services=None):
    return {
        "devices": {"SW1": devices or {"ps_status": D, "fan_status": D,
                                       "temperature_status": D, "model": "C9300"}},
        "interfaces": {"SW1": {"Gi1/0/1": iface}},
        "services": services or [{"category": D}],
        "service_map": {"services": services or [{"category": D}]},
        # populate enough of the migration model that mop reaches its per-wave interface loop.
        "move_groups": [{"name": "g1", "switches": ["SW1"]}],
        "migration_readiness": [{"group": "g1", "readiness": "READY", "switches": ["SW1"]}],
        "wave_sequencing": [{"group": "g1"}],
    }


_HOSTILE = _snap(_IFACE)

#: Every interface field the module docstring claims is coerced, poisoned ONE AT A TIME.
#:
#: NON-VACUITY (mutation-proved, 2026-07-28). `_IFACE` poisons them all at once — including
#: `switchport_mode`, which every other coercion site is GATED BEHIND. With `switchport_mode`
#: rendered as the string "{'x': 1}", runbook's `if (d.get("switchport_mode") or "") != "Access":
#: continue` skips the row outright, and mop's `mode == "access"` / `mode == "trunk"` are both
#: False, so the right-hand operands of those `and` chains never evaluate. Traced result: NOT ONE
#: live `.strip()`/`.lower()` on end_host_mac, end_host_ip, port_channel, cdp_neighbor, vrf,
#: acl_in or acl_out was reached, and reverting runbook's `str(_ehm or "")` coercion to
#: `(_ehm or "").strip()` left this file GREEN. The all-at-once case below is kept as a smoke
#: test; these parametrised cases are what actually reach the sites.
_POISONED = ("switchport_mode", "vrf", "acl_in", "acl_out", "end_host_mac", "end_host_ip",
             "cdp_neighbor", "port_channel", "sw_version")
_GENERATORS = ("crd", "design", "mop", "runbook")


def _write_all(snap, tmp_path, tag):
    from cisco_toolkit import crd, design, mop, runbook
    names = {"crd": f"c{tag}.docx", "design": f"d{tag}.docx",
             "mop": f"m{tag}.docx", "runbook": f"r{tag}.docx"}
    crd.write_crd_docx(str(tmp_path / names["crd"]), snap, "Meridian")
    design.write_design_doc_docx(str(tmp_path / names["design"]), snap, "Meridian")
    mop.write_mop_docx(str(tmp_path / names["mop"]), snap, "Meridian")
    runbook.write_runbook_docx(str(tmp_path / names["runbook"]), snap, "Meridian")
    for g in _GENERATORS:
        p = tmp_path / names[g]
        assert p.exists() and p.stat().st_size > 0, f"{g} produced no file for {tag}"


@pytest.mark.parametrize("mode", ["Access", "Trunk"])
@pytest.mark.parametrize("field", _POISONED)
def test_one_poisoned_field_at_a_time_still_reaches_every_coercion(field, mode, tmp_path):
    """crd / design / mop / runbook must degrade a wrong-typed device string-field to a placeholder
    and still emit a valid file, never 500 on the `.strip()`/`.lower()`.

    Both switchport modes are driven because the access-port and trunk-port branches coerce
    DIFFERENT fields (end_host_mac/end_host_ip on access; cdp_neighbor/port_channel on trunk), so a
    single mode leaves half the sites unreached."""
    pytest.importorskip("docx")
    iface = {"switchport_mode": mode, "vlan": "10", "vrf": "", "acl_in": "", "acl_out": "",
             "svi_ip": "10.0.0.1", "end_host_mac": "aabb.ccdd.eeff", "end_host_ip": "10.0.0.9",
             "cdp_neighbor": "SW2", "neighbor_port": "Gi1/0/2", "port_channel": "Po1",
             "sw_version": "16.12.4", "status": "connected"}
    iface[field] = D
    _write_all(_snap(iface), tmp_path, f"{field}_{mode}")


def test_deliverable_generators_tolerate_dict_valued_device_string_fields(tmp_path):
    """Smoke case: EVERY field wrong-typed at once. Kept because a real hostile upload looks like
    this — but on its own it proves far less than the parametrised cases above (see _POISONED)."""
    pytest.importorskip("docx")
    _write_all(_HOSTILE, tmp_path, "all")
