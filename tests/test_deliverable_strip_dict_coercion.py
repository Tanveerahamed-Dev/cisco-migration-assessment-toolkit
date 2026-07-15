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

_HOSTILE = {
    "devices": {"SW1": {"ps_status": D, "fan_status": D, "temperature_status": D, "model": "C9300"}},
    "interfaces": {"SW1": {"Gi1/0/1": _IFACE}},
    "services": [{"category": D}],
    "service_map": {"services": [{"category": D}]},
    # populate enough of the migration model that mop reaches its per-wave interface loop (mop.py:697).
    "move_groups": [{"name": "g1", "switches": ["SW1"]}],
    "migration_readiness": [{"group": "g1", "readiness": "READY", "switches": ["SW1"]}],
    "wave_sequencing": [{"group": "g1"}],
}


def test_deliverable_generators_tolerate_dict_valued_device_string_fields(tmp_path):
    """crd / design / mop / runbook must degrade a wrong-typed device string-field to a placeholder and still
    emit a valid file, never 500 on the `.strip()`/`.lower()`."""
    pytest.importorskip("docx")
    from cisco_toolkit import crd, design, mop, runbook
    crd.write_crd_docx(str(tmp_path / "c.docx"), _HOSTILE, "AJ")
    design.write_design_doc_docx(str(tmp_path / "d.docx"), _HOSTILE, "AJ")
    mop.write_mop_docx(str(tmp_path / "m.docx"), _HOSTILE, "AJ")
    runbook.write_runbook_docx(str(tmp_path / "r.docx"), _HOSTILE, "AJ")
    assert all((tmp_path / f).exists() for f in ("c.docx", "d.docx", "m.docx", "r.docx"))
