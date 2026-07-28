"""Plan-A Tier-3 #18: the optional MCP server.

The PURE data layer (cisco_toolkit.mcp_server extractors) is tested UNCONDITIONALLY against
the rich demo snapshot + the frozen golden -- it imports no `mcp`, so this half also runs on
the engine-only CI matrix. The thin FastMCP WIRING is guarded by importorskip('mcp') so the
suite stays green wherever the optional [mcp] extra is not installed.

Content assertions use the rich sample (complete: scale, dossiers, findings, arch-coverage);
the golden exercises the list_devices fallback (it predates device_dossiers) and `{}` proves
coverage-honest degradation -- an absent section reads empty, never raises.
"""
import json
import os

import pytest

from cisco_toolkit import mcp_server as M
from cisco_toolkit import whatif

HERE = os.path.dirname(os.path.abspath(__file__))
GOLDEN = os.path.join(HERE, "golden", "snapshot.json")
RICH = os.path.join(HERE, "..", "webapp", "sample_data", "sample_fleet.snapshot.json")


def _load(p):
    if not os.path.exists(p):
        pytest.skip(f"fixture not present: {p}")
    with open(p, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def golden():
    return _load(GOLDEN)


@pytest.fixture(scope="module")
def rich():
    return _load(RICH)


# --- pure data layer (no `mcp` needed) ------------------------------------------------

def test_overview_reports_real_scale(rich):
    ov = M.overview(rich)
    assert isinstance(ov["scale"].get("n_devices"), int) and ov["scale"]["n_devices"] > 0
    assert isinstance(ov["top_gating"], list)


def test_top_findings_limit_and_severity_filter(rich):
    top = M.top_findings(rich, limit=5)
    assert 0 < len(top) <= 5
    sev = top[0]["severity"]
    filtered = M.top_findings(rich, limit=1000, severity=str(sev).upper())  # case-insensitive
    assert filtered and all(f["severity"] == sev for f in filtered)
    assert M.top_findings(rich, limit=10, severity="__no_such_sev__") == []


def test_failure_impact_and_chokepoints_shape(rich):
    fi = M.failure_impact(rich, limit=3)
    assert 0 < len(fi) <= 3 and all("host" in r for r in fi)
    cp = M.chokepoints(rich, limit=3)
    assert 0 < len(cp) <= 3
    assert ":" in cp[0]["a"] and ":" in cp[0]["b"]      # "a_host:a_port" formatting


def test_list_devices_prefers_dossier_then_falls_back(rich, golden):
    rich_dev = M.list_devices(rich)
    assert rich_dev and all("risk_band" in d for d in rich_dev)   # dossier path
    gold_dev = M.list_devices(golden)                             # golden lacks dossiers -> fallback
    assert gold_dev and all(d.get("host") for d in gold_dev)      # host derived from health_scores


def test_device_detail_hit_is_case_insensitive_and_miss_is_helpful(rich):
    host = M.list_devices(rich)[0]["host"]
    hit = M.device_detail(rich, str(host).upper())
    assert hit.get("host") == host and "error" not in hit
    miss = M.device_detail(rich, "no-such-host-xyz")
    assert "error" in miss and isinstance(miss["available_hosts"], list)


def test_architecture_coverage(rich):
    ac = M.architecture_coverage(rich)
    assert isinstance(ac["classes"], list) and ac["classes"]
    assert all({"key", "label", "channel"} <= set(c) for c in ac["classes"])


def test_every_extractor_degrades_on_empty_snapshot():
    empty = {}
    scale = M.overview(empty)["scale"]
    assert isinstance(scale, dict) and all(v is None for v in scale.values())
    assert M.list_devices(empty) == []
    assert M.top_findings(empty) == []
    assert M.failure_impact(empty) == []
    assert M.chokepoints(empty) == []
    assert M.architecture_coverage(empty)["classes"] == []
    assert "error" in M.device_detail(empty, "x")
    # the L2 failover tools degrade honestly on a snapshot with no collected STP/FHRP state
    assert M.failover_twin(empty, "core1")["available"] is False
    assert M.failover_readiness(empty)["available"] is False


def test_load_snapshot_rejects_non_object(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(ValueError):
        M.load_snapshot(str(p))


# --- 2026 extension: single-finding / search / move-groups / what-if / health ----------

def test_tool_names_pin_and_pure_map_completeness():
    """The declared wire surface is frozen here; _PURE must carry exactly the same names so
    every declared tool has a testable pure implementation (and none is left unwired)."""
    assert M.TOOL_NAMES == [
        "overview", "list_devices", "device_detail", "top_findings",
        "failure_impact", "chokepoints", "architecture_coverage",
        "get_finding", "search_devices", "get_move_groups", "whatif_node", "get_health",
        "failover_twin", "failover_readiness",
    ]
    assert set(M._PURE) == set(M.TOOL_NAMES)


def test_failover_twin_tool_returns_engine_result_verbatim(golden):
    # golden's core1 is a VLAN root; failing it re-elects a new root (result carried verbatim, schema intact)
    res = M.failover_twin(golden, "core1")
    assert res["available"] is True and res["target"] == "core1"
    assert res["result"]["schema"] == "failover_twin/1"
    assert res["result"]["failed_hosts"] == ["core1"]
    assert res["sources"] == ["stp_roots", "fhrp_detail"]


def test_failover_twin_tool_miss_lists_available_hosts(golden):
    res = M.failover_twin(golden, "__no_such_host__")
    assert res["available"] is True                       # the tool ran; the target just matched nothing
    assert res["result"]["failed_hosts"] == []
    assert isinstance(res["available_l2_hosts"], list) and res["available_l2_hosts"]


def test_failover_twin_tool_empty_target_is_helpful(golden):
    res = M.failover_twin(golden, "")
    assert res["available"] is False and "no target" in res["reason"].lower()


def test_failover_readiness_tool_shape(golden):
    res = M.failover_readiness(golden)
    assert res["available"] is True
    r = res["result"]
    assert r["schema"] == "failover_readiness/1"
    assert isinstance(r["n_stp_roots"], int) and isinstance(r["at_risk"], list)


def test_get_finding_by_priority_index(rich):
    row = rich["punchlist"][0]
    for query in (row["priority"], str(row["priority"])):     # int and int-like string
        res = M.get_finding(rich, query)
        assert res["available"] is True and res["matched_by"] == "priority"
        assert res["finding"] == row                          # the FULL row, detail + devices intact
        assert "devices" in res["finding"] and "detail" in res["finding"]
        assert res["sources"] == ["punchlist"]


def test_get_finding_by_title_substring_unique_hit(rich):
    titles = [str(r.get("title", "")) for r in rich["punchlist"]]
    uniq = next(t for t in titles if t and sum(1 for u in titles if t.lower() in u.lower()) == 1)
    res = M.get_finding(rich, uniq)
    assert res["available"] is True and res["matched_by"] == "title"
    assert res["finding"]["title"] == uniq


def test_get_finding_ambiguous_match_is_disambiguated_honestly(rich):
    titles = [str(r.get("title", "")) for r in rich["punchlist"]]
    assert sum(1 for t in titles if "e" in t.lower()) >= 2    # fixture sanity for the ambiguity probe
    res = M.get_finding(rich, "e")
    assert res["available"] is False and res.get("ambiguous") is True
    assert len(res["matches"]) >= 2
    assert all({"priority", "severity", "title"} <= set(m) for m in res["matches"])


def test_get_finding_miss_and_empty_query(rich):
    miss = M.get_finding(rich, "__no_such_finding__")
    assert miss["available"] is False and "no finding" in miss["reason"]
    empty_q = M.get_finding(rich, "")
    assert empty_q["available"] is False and "sources" in empty_q


def test_search_devices_by_hostname_platform_and_ip(rich):
    host = list(rich["devices"].keys())[0]
    by_host = M.search_devices(rich, host)
    assert by_host["available"] is True and by_host["n_matches"] >= 1
    hit = next(m for m in by_host["matches"] if m["host"] == host)
    assert "host" in hit["matched_on"]
    assert hit["health_band"] and hit["risk_band"]            # dossiers present -> risk band shown
    assert "health" in hit["posture"] and "risk" in hit["posture"]

    platform = rich["device_dossiers"]["per_device"][0]["platform"]
    by_platform = M.search_devices(rich, platform[:6])
    assert by_platform["n_matches"] >= 1

    ip = next((r.get("current_switch_ip") for ports in rich["interfaces"].values()
               for r in ports.values() if r.get("current_switch_ip")), None)
    assert ip, "fixture must carry a management IP on some interface row"
    by_ip = M.search_devices(rich, ip)
    assert by_ip["n_matches"] >= 1 and any("ip" in m["matched_on"] for m in by_ip["matches"])
    assert "devices" in by_host["sources"] and "interfaces" in by_ip["sources"]


def test_search_devices_golden_fallback_posture_is_honest(golden):
    host = list(golden["devices"].keys())[0]
    res = M.search_devices(golden, host)
    assert res["available"] is True and res["n_matches"] >= 1
    hit = next(m for m in res["matches"] if m["host"] == host)
    assert hit["health_band"]                                 # from health_scores fallback
    assert hit["risk_band"] is None                           # no dossiers -> never a fabricated risk band
    assert "not-assessed" in hit["posture"]


def test_search_devices_no_match_vs_empty_query(rich):
    none = M.search_devices(rich, "__no_such_device__")
    assert none["available"] is True and none["n_matches"] == 0 and none["matches"] == []
    empty = M.search_devices(rich, "")
    assert empty["available"] is False and "reason" in empty


def test_get_move_groups_joins_readiness_sequencing_and_scenario(rich):
    res = M.get_move_groups(rich)
    assert res["available"] is True
    assert len(res["groups"]) == len(rich["move_groups"])
    verdicts = {r["group"]: r["readiness"] for r in rich["migration_readiness"]}
    scenarios = {r["group"]: r["recommended_scenario"] for r in rich["migration_scenarios"]["per_group"]}
    for g in res["groups"]:
        assert g["switches"]
        assert g["readiness"] == verdicts.get(g["group"], "not-assessed")
        if g["group"] in scenarios:
            assert g["scenario"]["recommended_scenario"] == scenarios[g["group"]]
        if g["gating"]:
            assert {"n_fail", "n_warn", "checks"} <= set(g["gating"])
    assert "move_groups" in res["sources"] and "migration_readiness" in res["sources"]


def test_get_move_groups_without_readiness_reads_not_assessed(rich):
    partial = dict(rich)
    for k in ("migration_readiness", "wave_sequencing", "migration_scenarios"):
        partial.pop(k, None)
    res = M.get_move_groups(partial)
    assert res["available"] is True
    assert all(g["readiness"] == "not-assessed" for g in res["groups"])   # absence is never health
    assert all(g["gating"] is None and g["scenario"] is None for g in res["groups"])


def test_whatif_node_matches_direct_whatif_call(rich):
    host = list(rich["routes"].keys())[0]
    res = M.whatif_node(rich, host)
    assert res["available"] is True and "routes" in res["sources"]
    assert res["result"]["scenario"]["failures"] == [{"type": "node", "id": host}]
    assert host in res["result"]["removed_hosts"]
    direct = whatif.run_scenario(rich, res["result"]["scenario"])         # parity: verbatim passthrough
    assert direct == res["result"]
    s = res["result"]["summary"]
    assert s["pairs_tested"] == s["blocked"] + s["lost_path"] + s["preserved"] \
        + s["inconclusive_other"] + s["other"]


def test_whatif_node_unknown_host_keeps_whatif_wording(rich):
    res = M.whatif_node(rich, "no-such-node-xyz")
    assert res["available"] is True
    assert res["result"]["summary"]["removed"] == 0
    assert res["result"]["note"] == "No device matched the scenario — nothing was removed."
    assert res["available_route_hosts"] == sorted(rich["routes"].keys())


def test_whatif_node_without_routes_or_host_is_honest(rich):
    no_routes = M.whatif_node({}, "core1")
    assert no_routes["available"] is False and "routes" in no_routes["reason"]
    no_host = M.whatif_node(rich, "")
    assert no_host["available"] is False and "host" in no_host["reason"]


def test_get_health_fleet_distribution(rich):
    fleet = M.get_health(rich)
    assert fleet["available"] is True
    assert fleet["n_devices"] == len(rich["health_scores"])
    assert sum(fleet["bands"].values()) == fleet["n_devices"]
    scores = [r["score"] for r in rich["health_scores"]]
    assert fleet["worst"] and fleet["worst"][0]["score"] == min(scores)
    assert fleet["sources"] == ["health_scores"]


def test_get_health_single_device_and_miss(rich):
    row = rich["health_scores"][0]
    one = M.get_health(rich, str(row["switch"]).upper())      # case-insensitive
    assert one["available"] is True and one["host"] == row["switch"]
    assert one["score"] == row["score"] and one["band"] == row["band"]
    assert one["top_issues"] == row["deductions"][:10]
    miss = M.get_health(rich, "no-such-host-xyz")
    assert miss["available"] is False and isinstance(miss["available_hosts"], list)


def test_new_tools_are_coverage_honest_on_empty_snapshot():
    empty = {}
    for res in (M.get_finding(empty, 1), M.search_devices(empty, "core"),
                M.get_move_groups(empty), M.whatif_node(empty, "core1"), M.get_health(empty)):
        assert res["available"] is False
        assert res["reason"]                                  # says WHY, never raises / fabricates
        assert "sources" in res


# --- MCP wiring (needs the optional extra) --------------------------------------------

def test_build_server_registers_the_expected_tools(rich):
    pytest.importorskip("mcp")
    import asyncio
    server = M.build_server(rich)
    names = sorted(t.name for t in asyncio.run(server.list_tools()))
    assert names == sorted(M.TOOL_NAMES), f"wired tools {names} != declared {sorted(M.TOOL_NAMES)}"


def test_build_server_ok_on_empty_snapshot():
    pytest.importorskip("mcp")
    assert M.build_server({}) is not None      # wiring must not touch snapshot contents at build time


def test_each_tool_call_returns_its_pure_function_output(rich):
    """Refute a wrapper mis-binding: drive every tool THROUGH the server and assert it returns
    exactly its pure-function output -- proving each of the twelve near-identical wrappers is
    wired to the RIGHT pure fn and passes its arguments through (registration alone can't)."""
    pytest.importorskip("mcp")
    import asyncio

    def _reassemble(res, expected):
        # FastMCP emits ONE text block per element for a LIST return, a single block for a dict.
        # Reassemble against the expected shape so the comparison reflects the tool's logical value.
        content = res[0] if isinstance(res, tuple) else res
        parsed = [json.loads(b.text) for b in content]
        return parsed if isinstance(expected, list) else (parsed[0] if parsed else None)

    server = M.build_server(rich)
    host = M.list_devices(rich)[0]["host"]
    route_host = list(rich["routes"].keys())[0]
    cases = [
        ("overview", {}, M.overview(rich)),
        ("list_devices", {}, M.list_devices(rich)),
        ("architecture_coverage", {}, M.architecture_coverage(rich)),
        ("top_findings", {"limit": 5}, M.top_findings(rich, 5)),
        ("failure_impact", {"limit": 5}, M.failure_impact(rich, 5)),
        ("chokepoints", {"limit": 5}, M.chokepoints(rich, 5)),
        ("device_detail", {"host": host}, M.device_detail(rich, host)),
        ("get_finding", {"finding": "1"}, M.get_finding(rich, "1")),
        ("search_devices", {"query": host}, M.search_devices(rich, host)),
        ("get_move_groups", {}, M.get_move_groups(rich)),
        ("whatif_node", {"host": route_host}, M.whatif_node(rich, route_host)),
        ("get_health", {}, M.get_health(rich)),                     # defaulted host -> fleet view
        ("get_health", {"host": host}, M.get_health(rich, host)),   # explicit host passes through
    ]
    for name, args, expected in cases:
        got = _reassemble(asyncio.run(server.call_tool(name, args)), expected)
        assert got == expected, f"tool {name!r} returned {got!r} != its pure output {expected!r}"


# --- the socket transports are a listener, not "no egress" (finding #56) ---------------
# `--transport sse|streamable-http` serves the ENTIRE snapshot -- hostnames, mgmt IPs via
# search_devices, punch-list findings, blast radius -- with no authentication, while the
# module docstring said "never hits the network" and the CLI help said "offline, no egress".
# The bind address is the only control there is, so it must be THIS module's pin (the
# installed mcp defaults to loopback, but that is the dependency's promise, not ours).

def test_build_server_pins_the_listener_host_itself(monkeypatch):
    pytest.importorskip("mcp")
    import mcp.server.fastmcp as F
    seen = {}

    class _FakeFastMCP:
        def __init__(self, name=None, **kw):
            seen.update({"name": name}, **kw)

        def tool(self, *a, **k):
            return lambda fn: fn

    monkeypatch.setattr(F, "FastMCP", _FakeFastMCP)
    M.build_server({}, name="probe")
    assert seen.get("host") == M.LISTEN_HOST == "127.0.0.1", (
        "build_server must pass the bind host explicitly -- inheriting the mcp package's "
        f"default leaves an unauthenticated snapshot server one dependency default away "
        f"from 0.0.0.0 (got {seen!r})")
    assert seen.get("port") == M.LISTEN_PORT


def test_cli_help_stops_claiming_no_egress_for_socket_transports(capsys):
    with pytest.raises(SystemExit):
        M.main(["--help"])
    text = capsys.readouterr().out
    assert "UNAUTHENTICATED" in text                     # the exposure is stated, not implied
    assert "offline, no egress)" not in text             # the old unqualified claim is gone
    assert M.LISTEN_HOST in text                         # ...and the bind is disclosed
    assert "UNAUTHENTICATED" in M.__doc__ or "no authentication" in M.__doc__


def test_socket_transport_refuses_a_non_loopback_fastmcp_host(monkeypatch, tmp_path):
    """A FASTMCP_HOST pointing off-host states an intent this server must never honour: it has
    no auth, so it says so and exits instead of silently binding loopback anyway.

    `build_server` is faked for the WHOLE test on purpose: without the guard this path reaches
    `server.run(transport='sse')`, which really does start a listener (that is the finding).
    """
    pytest.importorskip("mcp")
    snap = tmp_path / "s.json"
    snap.write_text("{}", encoding="utf-8")
    calls = {}
    monkeypatch.setattr(M, "build_server", lambda s, name=None: type(
        "S", (), {"run": lambda self, transport=None: calls.setdefault("transport", transport)})())
    monkeypatch.setenv("FASTMCP_HOST", "0.0.0.0")
    with pytest.raises(SystemExit) as ex:
        M.main([str(snap), "--transport", "sse"])
    assert "refusing to serve the snapshot off-host" in str(ex.value)
    assert calls == {}                                  # never reached the listener
    monkeypatch.setenv("FASTMCP_HOST", "127.0.0.1")     # a loopback value is accepted (no exit here)
    M.main([str(snap), "--transport", "sse"])
    assert calls["transport"] == "sse"
