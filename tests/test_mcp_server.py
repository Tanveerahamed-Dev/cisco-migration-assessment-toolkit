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


def test_load_snapshot_rejects_non_object(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(ValueError):
        M.load_snapshot(str(p))


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
