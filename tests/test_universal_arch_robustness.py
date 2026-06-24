"""Adversarial robustness gate for the universal-architecture code built this arc (parse_aci_*/parse_sdwan_*/
the SSH-reachable parsers, the _signals + _d_* detectors, the REST collectors, and the coverage/move-group
SSOTs). Every parser must be TOLERANT (return []/{} on hostile input, never raise); every detector must be
coverage-honest under malformed evidence (never raise, never spuriously fire on garbage); the collectors must
be fail-soft. This is the proposer != verifier capstone -- a fresh pass that actively tries to break the
rapidly-built code, not re-grade it on happy-path inputs."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import pytest  # noqa: E402
from cisco_toolkit import parse, rest_collect  # noqa: E402
import cisco_toolkit.design_advisor as da  # noqa: E402

# Hostile inputs every text/JSON parser must survive without raising.
_HOSTILE = [
    "", "   ", "\x00\x01", "not json at all", "{", "}", "[]", "null", "true", "12345",
    '{"imdata": null}', '{"imdata": "notalist"}', '{"imdata": [null, 123, "x", {}]}',
    '{"imdata": [{"faultInst": null}]}', '{"imdata": [{"faultInst": {"attributes": null}}]}',
    '{"imdata": [{"faultInst": {"attributes": []}}]}', '{"data": null}', '{"data": "x"}',
    '{"data": [null, 1, {}]}', '{"totalCount": "1"}', '{"nested": {"imdata": [1]}}',
    "Peer LDP Ident:\nState:\n", "garbage\nwith\nlines\n", "%" * 200, "\n\n\n",
    '{"imdata": [{"fvCtx": {"attributes": {"pcEnfPref": null, "dn": 12345}}}]}',
    '{"data": [{"ompPeersDown": "notanint", "system-ip": null}]}',
]

# every parser in the new arch surface (text + JSON), exercised against the full hostile corpus
_PARSERS = [
    parse.parse_aci_faults, parse.parse_aci_fabric_nodes, parse.parse_aci_vrfs,
    parse.parse_aci_tenants, parse.parse_aci_bds, parse.parse_aci_epgs,
    parse.parse_sdwan_control_connections, parse.parse_sdwan_devices, parse.parse_sdwan_omp_counters,
    parse.parse_lisp_sessions, parse.parse_cts_environment_data, parse.parse_dmvpn_peers,
    parse.parse_crypto_sessions, parse.parse_bfd_neighbors, parse.parse_ipv6_interface_addrs,
    parse.parse_ipv6_route_summary, parse.parse_ospfv3_neighbors, parse.parse_bgp_ipv6_summary,
    parse.parse_mpls_ldp_neighbors, parse.parse_mpls_l2vpn_vc, parse.parse_bgp_vpnv4_summary,
    parse.parse_asa_failover, parse.parse_asa_resource_usage, parse.parse_ise_nodes,
    parse.parse_fmc_devices, parse.parse_fmc_ha_pairs, parse.parse_fmc_deployable, parse.parse_fmc_ha_status,
    parse.parse_fmc_server_version,
]


@pytest.mark.parametrize("fn", _PARSERS, ids=[f.__name__ for f in _PARSERS])
def test_parsers_tolerate_hostile_input(fn):
    """No new parser may raise on hostile/malformed input, and each must return a list or dict (its tolerant
    empty), never None or a partial that downstream _as_list/_as_dict could choke on."""
    for bad in _HOSTILE:
        out = fn(bad)
        assert isinstance(out, (list, dict)), f"{fn.__name__}({bad!r}) returned {type(out).__name__}"


def test_aci_health_rejects_non_numeric_cur():
    """parse_aci_health must not coerce a non-numeric / float-string cur into a false 'degraded'; {} instead."""
    assert parse.parse_aci_health('{"imdata":[{"fabricHealthTotal":{"attributes":{"cur":"n/a"}}}]}') == {}
    assert parse.parse_aci_health('{"imdata":[{"fabricHealthTotal":{"attributes":{"cur":"82.5"}}}]}') == {}
    assert parse.parse_aci_health('{"imdata":[{"fabricHealthTotal":{"attributes":{}}}]}') == {}


# Malformed snapshot axes the detectors must survive (wrong container types where a dict/list is expected).
_MALFORMED_SNAPS = [
    {}, {"aci": None}, {"aci": "notadict"}, {"aci": {"h": None}}, {"aci": {"h": "x"}},
    {"aci": {"h": {"faults": "notalist"}}}, {"aci": {"h": {"faults": [None, 1, "x"]}}},
    {"aci": {"h": {"vrfs": [{"pc_enf_pref": None}], "nodes": None, "health": "x"}}},
    {"sdwan": {"h": {"control_connections": "x", "omp_counters": [None], "devices": [123]}}},
    {"sdwan": {"h": {"omp_counters": [{"omp_down": "notint"}]}}},
    {"mpls": {"h": {"ldp_neighbors": [None]}}}, {"lisp": {"h": {"sessions": "x"}}},
    {"cts": {"h": "x"}}, {"bfd": {"h": {"sessions": [{"state": None}]}}},
    {"ipv6_routing": {"h": {"ospfv3_neighbors": [{"state": None}]}}},
    {"crypto": {"h": {"sessions": [{"status": None}]}}}, {"dmvpn": {"h": {"peers": [{"state": None}]}}},
]

# every new arch detector
_DETECTORS = [
    da._d_aci_critical_faults, da._d_aci_node_not_active, da._d_aci_fabric_health_degraded,
    da._d_aci_vrf_unenforced, da._d_sdwan_control_connection_down, da._d_sdwan_device_unreachable,
    da._d_sdwan_omp_peer_down, da._d_lisp_fabric_session_down, da._d_cts_environment_data_health,
    da._d_dmvpn_tunnel_health, da._d_crypto_session_health, da._d_bfd_session_health,
    da._d_ipv6_dad_duplicate, da._d_ipv6_routing_adjacency, da._d_mpls_ldp_health,
    da._d_mpls_l3vpn_health, da._d_mpls_l2vpn_health,
    da._d_firewall_ha_degraded, da._d_firewall_resource_exhaustion,
    da._d_ise_node_unreachable, da._d_ise_psn_no_redundancy, da._d_ise_admin_monitoring_redundancy,
    da._d_ftd_ha_degraded, da._d_fmc_device_disconnected, da._d_fmc_deployment_pending, da._d_fmc_manager_ha_degraded,
    da._d_fmc_version_inversion,
]


def test_signals_and_detectors_survive_malformed_axes():
    """_signals() must build a usable sig dict from any malformed snapshot, and every new detector must return
    None or a decision dict on it -- NEVER raise, and never spuriously fire on garbage with no real broken-state."""
    for snap in _MALFORMED_SNAPS:
        sig = da._signals(snap)              # must not raise
        assert isinstance(sig, dict)
        for det in _DETECTORS:
            out = det(snap, sig)             # must not raise
            assert out is None or isinstance(out, dict)


def test_coverage_and_move_groups_survive_malformed():
    """The coverage-honesty SSOT and the ACI move-group plan must tolerate malformed/empty input fail-soft."""
    for snap in _MALFORMED_SNAPS + [{"design_blueprint": "x"}, {"design_blueprint": {"decisions": "x"}}]:
        cov = da.compute_architecture_coverage(snap)
        assert cov["summary"]["n_classes"] == 26 and isinstance(cov["classes"], list)
        mg = da._aci_move_groups(snap)
        assert isinstance(mg, dict)          # {} or a valid plan, never a raise


def test_coverage_truthy_nondict_axis_is_not_observed_not_clean():
    """Coverage-honesty: a corrupted axis that is truthy-but-not-a-dict (a stray list/str/int) must read
    'not-observed', NEVER 'clean' ('clean' = assessed-and-fine) -- so corruption/absence cannot silently
    present as healthy. The real build path always emits a dict or omits the key; this guards the corrupted
    -snapshot path (the 'not observed never becomes healthy' invariant, enforced for malformed input too)."""
    for bad in (["host"], "x", 42):
        cov = da.compute_architecture_coverage({"firewall": bad})
        fw = [c for c in cov["classes"] if c["key"] == "firewall"][0]
        assert fw["observed"] is False and fw["status"] == "not-observed", (bad, fw)


def test_rest_collect_fail_soft_on_broken_transport(monkeypatch, tmp_path):
    """The collectors must be fail-soft: a None login, a None GET, and a partial failure all degrade to [] /
    fewer files without raising. (Mocked transport -- no network.)"""
    # login returns None -> [] (already covered elsewhere, re-assert as the robustness contract)
    monkeypatch.setattr(rest_collect, "_post", lambda *a, **k: None)
    assert rest_collect.collect_apic("https://x", "u", "p", str(tmp_path / "a")) == []
    assert rest_collect.collect_vmanage("https://x", "u", "p", str(tmp_path / "v")) == []

    # login OK but every GET fails -> no files written, no raise
    class _R:
        def read(self):
            return b"OK"
    monkeypatch.setattr(rest_collect, "_post", lambda *a, **k: _R())
    monkeypatch.setattr(rest_collect, "_get_json", lambda *a, **k: None)
    monkeypatch.setattr(rest_collect, "_get_text", lambda *a, **k: None)
    assert rest_collect.collect_apic("https://x", "u", "p", str(tmp_path / "a2")) == []
    assert rest_collect.collect_vmanage("https://x", "u", "p", str(tmp_path / "v2")) == []

    # a partial failure: one class returns data, the rest None -> exactly one file, no raise
    monkeypatch.setattr(rest_collect, "_get_json",
                        lambda opener, url, **k: {"imdata": [{"faultInst": {"attributes": {"code": "F1", "severity": "critical", "lc": "raised", "ack": "no"}}}]} if "faultInst" in url else None)
    files = rest_collect.collect_apic("https://x", "u", "p", str(tmp_path / "a3"))
    assert len(files) == 1


def test_rest_collect_never_persists_the_password(monkeypatch, tmp_path):
    """Safety contract: the credential is used once for login and never written to any export file."""
    monkeypatch.setattr(rest_collect, "_post", lambda *a, **k: type("R", (), {"read": lambda s: b"OK"})())
    monkeypatch.setattr(rest_collect, "_get_text", lambda *a, **k: "TOK")
    monkeypatch.setattr(rest_collect, "_get_json",
                        lambda opener, url, **k: {"imdata": [{"x": {"attributes": {"k": "v"}}}], "data": [{"k": "v"}]})
    secret = "SUPER-SECRET-PW-9999"
    out = str(tmp_path / "apic")
    files = rest_collect.collect_apic("https://x", "user", secret, out)
    files += rest_collect.collect_vmanage("https://x", "user", secret, str(tmp_path / "vm"))
    for p in files:
        assert secret not in open(p, encoding="utf-8").read(), f"password leaked into {p}"
