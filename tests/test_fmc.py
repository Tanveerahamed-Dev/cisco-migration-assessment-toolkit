"""Cisco Secure Firewall Management Center (FMC, formerly Firepower Management Center) -- the JSON controller-
REST channel for a centrally-MANAGED FTD fleet (additive over the SSH show-text channel; the APIC/vManage/ISE
template). For an FMC-managed fleet the controller is the source of truth -- you often have no per-device CLI,
so FMC's REST API is the only window onto HA, health, reachability and config-deployment state. Covers the
_fmc_items envelope reader, the four parsers, the _signals FMC extraction, and the four detectors. Contract:
the universal coverage-honesty doctrine, with the verify-pass corrections baked in --
  * the list endpoints WRAP rows as {"items":[...], "paging":{...}}; single-object endpoints return the object;
  * FTD HA currentStatus 'Disabled' is an INTENTIONAL suspended-HA state (operator-suspended for maintenance),
    NOT a failure -- it must NOT fire (the headline cry-wolf the verify-pass caught);
  * a standalone (non-HA) FTD has no ftddevicehapairs entry, and a single (non-HA) FMC has no fmchastatuses --
    absence of HA is coverage-honestly NOT a failure.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from cisco_toolkit import parse  # noqa: E402
import cisco_toolkit.design_advisor as da  # noqa: E402


def _wrap(items):
    return json.dumps({"items": items, "paging": {"count": len(items)}})


_DEVS_HEALTHY = _wrap([
    {"name": "[HISTORY-REDACTED]-FTD-01", "hostName": "10.1.1.10", "model": "FTDv", "sw_version": "7.2.5",
     "isConnected": True, "healthStatus": "green", "deploymentStatus": "DEPLOYED"},
])
_DEVS_BAD = _wrap([
    {"name": "[HISTORY-REDACTED]-FTD-01", "hostName": "10.1.1.10", "model": "FTDv", "sw_version": "7.2.5",
     "isConnected": True, "healthStatus": "green", "deploymentStatus": "DEPLOYED"},
    {"name": "[HISTORY-REDACTED]-FTD-99", "hostName": "10.1.1.99", "model": "FTDv", "sw_version": "7.2.5",
     "isConnected": False, "healthStatus": "red", "deploymentStatus": "WARNING"},
])
_HA_HEALTHY = _wrap([{"name": "HA-Edge", "primaryStatus": {"currentStatus": "Active"},
                      "secondaryStatus": {"currentStatus": "Standby"}}])
_HA_FAILED = _wrap([{"name": "HA-Edge", "primaryStatus": {"currentStatus": "Active"},
                     "secondaryStatus": {"currentStatus": "Failed"}}])
# 'Disabled' = operator-suspended HA (intentional) -> must stay silent (the headline cry-wolf correction).
_HA_DISABLED = _wrap([{"name": "HA-Edge", "primaryStatus": {"currentStatus": "Active"},
                       "secondaryStatus": {"currentStatus": "Disabled"}}])
_DEP_PENDING = _wrap([{"name": "[HISTORY-REDACTED]-FTD-03", "canBeDeployed": True, "upToDate": False, "device": {"name": "[HISTORY-REDACTED]-FTD-03"}}])
_DEP_EMPTY = _wrap([])
# REAL empty shape: an FMC list endpoint with nothing to return can answer with a paging/links envelope that
# OMITS 'items' entirely (not {"items":[]}). The self-authored {"items":[]} fixture hid this; a clean fleet in
# this real form fabricated a phantom nameless row -> _d_fmc_deployment_pending cry-wolfed on a fully-deployed fleet.
_DEP_EMPTY_NOITEMS = json.dumps({"links": {"self": "https://fmc.example/api/.../deployabledevices"},
                                 "paging": {"offset": 0, "limit": 25, "count": 0, "pages": 0}})
# Real /integration/fmchastatuses shape: a LIST endpoint ({"items":[...]}) whose object carries overallStatus +
# syncStatus (the HEALTHY value is 'GOOD', NOT 'Synced') + fmcPrimary/fmcSecondary{role}; HA-not-configured ->
# items []. (The previous fixtures invented fmcHARole/haStatus/syncStatus:'Synced' -- a schema that does not
# exist on a real FMC, which is exactly why the silent-on-healthy test passed against fiction while the detector
# cried wolf on real GOOD/GOOD data.)
_MGR_HEALTHY = _wrap([{"overallStatus": "GOOD", "syncStatus": "GOOD",
                       "fmcPrimary": {"role": "Active"}, "fmcSecondary": {"role": "Standby"},
                       "haStatusMessages": ["Healthy"]}])
_MGR_DEGRADED = _wrap([{"overallStatus": "DEGRADED", "syncStatus": "FAILED",
                        "fmcPrimary": {"role": "Active"}, "fmcSecondary": {"role": "Failed"},
                        "haStatusMessages": ["Synchronization failed"]}])
# syncStatus IN_PROGRESS is a transient mid-sync state -> must NOT fire (non-cry-wolf, mirrors the FTD-HA rule).
_MGR_TRANSIENT = _wrap([{"overallStatus": "GOOD", "syncStatus": "IN_PROGRESS",
                         "fmcPrimary": {"role": "Active"}, "fmcSecondary": {"role": "Standby"}}])
# SPLIT_BRAIN overall (both Active) -> a real degraded manager.
_MGR_SPLIT = _wrap([{"overallStatus": "SPLIT_BRAIN", "syncStatus": "GOOD",
                     "fmcPrimary": {"role": "Active"}, "fmcSecondary": {"role": "Active"}}])


_SV_OK = json.dumps({"items": [{"serverVersion": "7.4.1 (build 172)"}]})    # FMC newer than the FTD fleet
_SV_OLD = json.dumps({"items": [{"serverVersion": "7.0.0 (build 94)"}]})     # FMC OLDER than FTD 7.2.5 -> inversion


def _snap(devices=None, ha=None, dep=None, mgr=None, sv=None, host="FMC-01"):
    b = {}
    if devices is not None:
        b["devices"] = parse.parse_fmc_devices(devices)
    if ha is not None:
        b["ha_pairs"] = parse.parse_fmc_ha_pairs(ha)
    if dep is not None:
        b["deployable"] = parse.parse_fmc_deployable(dep)
    if mgr is not None:
        b["ha_status"] = parse.parse_fmc_ha_status(mgr)
    if sv is not None:
        b["server_version"] = parse.parse_fmc_server_version(sv)
    return {"fmc": {host: b}}


# ============================================================ parsers
def test_parse_fmc_devices_unwraps_items():
    d = parse.parse_fmc_devices(_DEVS_BAD)
    assert len(d) == 2
    bad = [x for x in d if x["name"] == "[HISTORY-REDACTED]-FTD-99"][0]
    assert bad["is_connected"] is False and bad["health_status"] == "red"


def test_parse_fmc_ha_pairs_reads_nested_currentstatus():
    h = parse.parse_fmc_ha_pairs(_HA_FAILED)[0]
    assert h["primary_status"] == "Active" and h["secondary_status"] == "Failed"


def test_parse_fmc_ha_status_real_schema():
    s = parse.parse_fmc_ha_status(_MGR_DEGRADED)
    assert s["ha_status"] == "DEGRADED" and s["sync_status"] == "FAILED"
    # the HEALTHY pair carries overallStatus/syncStatus 'GOOD' (the real value, NOT the fictional 'Synced')
    h = parse.parse_fmc_ha_status(_MGR_HEALTHY)
    assert h["ha_status"] == "GOOD" and h["sync_status"] == "GOOD"
    # standalone FMC (HA not configured) returns no items -> {} (coverage-honest)
    assert parse.parse_fmc_ha_status(_wrap([])) == {}


def test_parse_fmc_deployable_empty_is_empty():
    assert parse.parse_fmc_deployable(_DEP_EMPTY) == []


def test_parse_fmc_deployable_no_items_envelope_is_empty_not_phantom():
    # the REAL empty form (paging/links, no 'items' key) must read as [] -- never a fabricated nameless row.
    assert parse.parse_fmc_deployable(_DEP_EMPTY_NOITEMS) == []


# ============================================================ detector: FTD HA degraded
def test_ftd_ha_degraded_fires_on_failed():
    snap = _snap(ha=_HA_FAILED)
    d = da._d_ftd_ha_degraded(snap, da._signals(snap))
    assert d is not None and d["id"] == "ftd-ha-pair-degraded" and d["priority"] == "Critical"


def test_ftd_ha_degraded_silent_on_healthy_pair():
    snap = _snap(ha=_HA_HEALTHY)
    assert da._d_ftd_ha_degraded(snap, da._signals(snap)) is None


def test_ftd_ha_degraded_silent_on_disabled_intentional_suspend():
    # 'Disabled' = operator-suspended HA (intentional) -> must NOT cry wolf (the headline correction)
    snap = _snap(ha=_HA_DISABLED)
    assert da._d_ftd_ha_degraded(snap, da._signals(snap)) is None


# ============================================================ detector: device disconnected / red health
def test_device_disconnected_fires():
    snap = _snap(devices=_DEVS_BAD)
    d = da._d_fmc_device_disconnected(snap, da._signals(snap))
    assert d is not None and "[HISTORY-REDACTED]-FTD-99" in str(d["evidence"]["summary"])


def test_device_disconnected_silent_on_healthy():
    snap = _snap(devices=_DEVS_HEALTHY)
    assert da._d_fmc_device_disconnected(snap, da._signals(snap)) is None


# ============================================================ detector: deployment pending
def test_deployment_pending_fires_on_staged_changes():
    snap = _snap(dep=_DEP_PENDING)
    d = da._d_fmc_deployment_pending(snap, da._signals(snap))
    assert d is not None and d["id"] == "fmc-deployment-pending"


def test_deployment_pending_silent_when_empty():
    snap = _snap(dep=_DEP_EMPTY)
    assert da._d_fmc_deployment_pending(snap, da._signals(snap)) is None


def test_deployment_pending_silent_on_no_items_clean_fleet():
    # CRY-WOLF FIX: a fully-deployed fleet whose deployabledevices comes back as the real no-'items' empty
    # envelope must NOT raise 'N device(s) with staged undeployed changes'.
    snap = _snap(dep=_DEP_EMPTY_NOITEMS)
    assert da._d_fmc_deployment_pending(snap, da._signals(snap)) is None


# ============================================================ detector: FMC manager HA degraded
def test_manager_ha_fires_on_degraded():
    snap = _snap(mgr=_MGR_DEGRADED)
    assert da._d_fmc_manager_ha_degraded(snap, da._signals(snap)) is not None


def test_manager_ha_silent_on_healthy():
    # GOOD/GOOD on the REAL schema -- the regression guard: the OLD parser+gate cried wolf here because it read
    # the non-existent syncStatus value 'Synced' and fired on anything else (incl. the real 'GOOD').
    snap = _snap(mgr=_MGR_HEALTHY)
    assert da._d_fmc_manager_ha_degraded(snap, da._signals(snap)) is None


def test_manager_ha_silent_on_transient_sync():
    # syncStatus IN_PROGRESS (mid-sync) with GOOD overall -> a transient resync is NOT a fault (non-cry-wolf).
    snap = _snap(mgr=_MGR_TRANSIENT)
    assert da._d_fmc_manager_ha_degraded(snap, da._signals(snap)) is None


def test_manager_ha_fires_on_split_brain():
    snap = _snap(mgr=_MGR_SPLIT)
    assert da._d_fmc_manager_ha_degraded(snap, da._signals(snap)) is not None


# ============================================================ detector: FMC<FTD version inversion
def test_parse_fmc_server_version():
    assert parse.parse_fmc_server_version(_SV_OLD)["server_version"].startswith("7.0.0")


def test_version_inversion_fires_when_fmc_older_than_ftd():
    snap = _snap(devices=_DEVS_HEALTHY, sv=_SV_OLD)   # FMC 7.0.0 < FTD 7.2.5 (Cisco mandates FMC >= FTD)
    d = da._d_fmc_version_inversion(snap, da._signals(snap))
    assert d is not None and d["id"] == "fmc-version-inversion"


def test_version_inversion_silent_when_fmc_newer_or_equal():
    snap = _snap(devices=_DEVS_HEALTHY, sv=_SV_OK)    # FMC 7.4.1 >= FTD 7.2.5
    assert da._d_fmc_version_inversion(snap, da._signals(snap)) is None


def test_version_inversion_silent_when_unparseable():
    snap = _snap(devices=_DEVS_HEALTHY, sv=json.dumps({"items": [{"serverVersion": ""}]}))
    assert da._d_fmc_version_inversion(snap, da._signals(snap)) is None


# ============================================================ coverage-honesty
def test_all_fmc_detectors_silent_when_no_fmc_axis():
    sig = da._signals({})
    for det in (da._d_ftd_ha_degraded, da._d_fmc_device_disconnected, da._d_fmc_deployment_pending,
                da._d_fmc_manager_ha_degraded, da._d_fmc_version_inversion):
        assert det({}, sig) is None


def test_fmc_in_architecture_coverage_registry():
    keys = {axis for axis, *_ in da._ARCH_COVERAGE_REGISTRY}
    assert "fmc" in keys
    cov = da.compute_architecture_coverage(_snap(ha=_HA_FAILED) | {
        "design_blueprint": {"decisions": [{"id": "ftd-ha-pair-degraded"}]}})
    fmc = [c for c in cov["classes"] if c["key"] == "fmc"][0]
    assert fmc["observed"] is True and fmc["status"] == "finding" and fmc["channel"] == "json"


# ============================================================ build
def test_build_fmc_reads_endpoints(tmp_path):
    from cisco_toolkit import build
    files = {"api/fmc_config/v1/devicehapairs/ftddevicehapairs": _HA_FAILED,
             "api/fmc_config/v1/devices/devicerecords": _DEVS_BAD}
    cmd_to_file = {}
    for cmd, content in files.items():
        p = tmp_path / (cmd.replace("/", "_") + ".txt")
        p.write_text(content, encoding="utf-8")
        cmd_to_file[cmd] = str(p)
    fmc = build.build_fmc(cmd_to_file)
    assert any(h["secondary_status"] == "Failed" for h in fmc["ha_pairs"])
    assert any(d["is_connected"] is False for d in fmc["devices"])


def test_build_fmc_empty_when_absent():
    from cisco_toolkit import build
    assert build.build_fmc({}) == {}


# ============================================================ robustness
def test_fmc_parsers_tolerate_hostile_input():
    for fn in (parse.parse_fmc_devices, parse.parse_fmc_ha_pairs, parse.parse_fmc_deployable):
        for bad in ("", None, "not json", "{", "null", "123", '{"items": null}', '{"items": "x"}',
                    '{"items": [null, 1, {}]}', ["x"]):
            assert isinstance(fn(bad), list)
    for bad in ("", None, "{", '{"items": null}', "123"):
        assert isinstance(parse.parse_fmc_ha_status(bad), dict)


def test_fmc_detectors_survive_malformed_axis():
    for snap in [{"fmc": None}, {"fmc": "x"}, {"fmc": {"h": None}}, {"fmc": {"h": {"ha_pairs": "x"}}},
                 {"fmc": {"h": {"ha_pairs": [None, 1, {"primary_status": None}]}}},
                 {"fmc": {"h": {"devices": [{"is_connected": None, "health_status": None}]}}},
                 {"fmc": {"h": {"server_version": {"server_version": None}, "devices": [{"sw_version": None}]}}}]:
        sig = da._signals(snap)
        for det in (da._d_ftd_ha_degraded, da._d_fmc_device_disconnected, da._d_fmc_deployment_pending,
                    da._d_fmc_manager_ha_degraded, da._d_fmc_version_inversion):
            assert det(snap, sig) is None or isinstance(det(snap, sig), dict)


# ============================================================ read-only collector
def test_collect_fmc_https_only_and_password_safe(monkeypatch, tmp_path):
    from cisco_toolkit import rest_collect

    class _Login:
        headers = {"X-auth-access-token": "TOK", "DOMAINS": '[{"uuid": "dom-uuid", "name": "Global"}]'}

        def read(self):
            return b""
    assert rest_collect.collect_fmc("http://fmc", "u", "p", str(tmp_path / "a")) == []   # non-HTTPS refused
    monkeypatch.setattr(rest_collect, "_post", lambda *a, **k: _Login())
    monkeypatch.setattr(rest_collect, "_get_json", lambda *a, **k: {"items": [{"name": "x"}], "paging": {"count": 1}})
    secret = "FMC-SECRET-PW-1"
    files = rest_collect.collect_fmc("https://fmc", "admin", secret, str(tmp_path / "fmc"))
    assert files
    for p in files:
        assert secret not in open(p, encoding="utf-8").read()


def test_rest_collect_safe_url_strips_credentials():
    """[audit-2 L3] credentials embedded in --url (https://user:pass@host) must NOT reach a log line; _safe_url
    strips the userinfo while keeping host/path."""
    from cisco_toolkit.rest_collect import _safe_url
    s = _safe_url("https://rouser:Sup3rSecret@apic.example/api/class/fvTenant.json")
    assert "Sup3rSecret" not in s and "rouser" not in s and "apic.example" in s
    assert _safe_url("https://apic.example/api") == "https://apic.example/api"


def test_collect_fmc_tolerates_null_domains_header(tmp_path, monkeypatch):
    """[audit-2 #6] a 'DOMAINS: null' login header parses to None (no exception) -> 'for d in domains' crashed.
    collect_fmc must degrade, never raise."""
    from cisco_toolkit import rest_collect as rc
    class FakeLogin:
        headers = {"X-auth-access-token": "TOK", "DOMAINS": "null"}
        def close(self):
            pass
    monkeypatch.setattr(rc, "_post", lambda *a, **k: FakeLogin())
    monkeypatch.setattr(rc, "_get_json", lambda *a, **k: {"items": []})
    rc.collect_fmc("https://fmc.example", "u", "p", str(tmp_path))   # must not raise
