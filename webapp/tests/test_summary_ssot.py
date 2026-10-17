"""RC8-P1-H: caches cannot manufacture counts, readiness or a second topology.

Runtime execution belongs to GitHub-hosted CI. Stored fixtures are read unchanged.
"""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from fastapi.testclient import TestClient
from webapp.backend.app import create_app
from cisco_toolkit import ui_projection as uip
from webapp.backend import graph, summary

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(db_path=str(tmp_path / "summary.db")), base_url="http://localhost") as value:
        yield value


@pytest.fixture(params=["tests/golden/snapshot.json", "webapp/sample_data/sample_fleet.snapshot.json"])
def stored(request):
    return json.loads((ROOT / request.param).read_text(encoding="utf-8"))


def plain(fact):
    return {k: v for k, v in fact.items() if k != "minimum"}


def test_cache_matches_overview_and_findings_with_every_qualification(stored):
    before = deepcopy(stored)
    cached = summary.summarize(stored)
    admitted = cached["assessment"]
    overview, findings = uip.project_overview(stored), uip.project_findings(stored)
    assert admitted["facts"] == overview["facts"]
    assert admitted["bands"] == overview["fleet_health"]["bands"]
    for facet, field in [("severity", "by_severity"), ("category", "by_category")]:
        assert [{"k": row["k"], "n": plain(row["n"])} for row in admitted["punchlist"][field]] == findings["facets"][facet]
        assert cached["punchlist"][field] == {row["k"]: row["n"]["value"] for row in findings["facets"][facet]}
    assert plain(admitted["punchlist"]["total"]) == findings["total"]
    assert admitted["readiness_source"] == {k: v for k, v in overview["readiness"]["groups"].items() if k != "items"}
    assert stored == before


def test_duplicate_health_subject_withholds_every_bucket(stored):
    assert stored["health_scores"]
    stored["health_scores"].append(deepcopy(stored["health_scores"][0]))
    cached = summary.summarize(stored)
    assert all(row["n"]["state"] == "unverified" and row["n"]["value"] is None
               for row in cached["assessment"]["bands"])
    assert all(value is None for value in cached["bands"].values())


@pytest.mark.parametrize("snap", [{}, {"health_scores": []}, {"health_scores": 7},
                                 {"punchlist": None}, {"punchlist": []}, {"punchlist": [None]}])
def test_missing_empty_and_malformed_are_never_recounted_as_clean(snap):
    result = summary.summarize(snap)
    assert result["assessment"] == uip.project_summary(snap)
    for field in ("crit_high", "total"):
        fact = result["assessment"]["punchlist"][field]
        if fact["state"] != "published":
            assert result["punchlist"][field] is None
    assert all(row["n"]["state"] != "published" for row in result["assessment"]["readiness"])


def test_finding_minimum_is_explicit_and_withheld_zero_stays_null(stored):
    stored["security"] = None
    # Both severities are present, so their positive minimum can be added without
    # treating a withheld bucket as zero. The ordinary zero buckets remain held.
    stored["punchlist"] = [{"severity": severity, "category": "Security", "devices": []}
                           for severity in ("Critical", "High")]
    cached = summary.summarize(stored)
    critical_high = cached["assessment"]["punchlist"]["crit_high"]
    assert critical_high["state"] == "published" and critical_high["value"] == 2
    assert critical_high["minimum"] is True
    rows = {row["k"]: row["n"] for row in cached["assessment"]["punchlist"]["by_severity"]}
    assert rows["Critical"]["minimum"] and rows["High"]["minimum"]
    assert rows["Low"]["state"] != "published" and cached["punchlist"]["by_severity"]["Low"] is None


def test_readiness_is_counted_only_after_the_exact_owner_join(stored):
    assert stored["migration_readiness"]
    groups = uip.project_overview(stored)["readiness"]["groups"]
    result = uip.project_summary(stored)
    for row in result["readiness"]:
        if row["n"]["state"] == "published":
            assert groups["state"] == "published"
            assert row["n"]["value"] == sum(item["readiness"]["value"] == row["k"] for item in groups["items"])
    stored["migration_readiness"].append(deepcopy(stored["migration_readiness"][0]))
    broken = summary.summarize(stored)
    assert all(row["n"]["state"] == "unverified" and row["n"]["value"] is None
               for row in broken["assessment"]["readiness"])


def test_critical_high_uses_admitted_facets_and_never_the_trend_recount(stored, monkeypatch):
    def forbidden(_snapshot):
        raise AssertionError("The summary may not use the old headline recount")
    monkeypatch.setattr(summary.engine, "trend_point", forbidden)
    result = summary.summarize(stored)
    selected = [row["n"] for row in result["assessment"]["punchlist"]["by_severity"]
                if row["k"] in ("Critical", "High")]
    fact = result["assessment"]["punchlist"]["crit_high"]
    assert len(selected) == 2
    if all(row["state"] == "published" for row in selected):
        assert fact["state"] == "published" and fact["value"] == sum(row["value"] for row in selected)
    else:
        assert fact["state"] != "published" and fact["value"] is None
    assert result["punchlist"]["crit_high"] == fact["value"]


def test_graph_is_exactly_the_topology_owner_and_never_uses_cache_hints(stored):
    assert graph.build_graph(stored, ["unowned-cache-host"]) == uip.project_tools_topology(stored)
    baseline = graph.build_graph(stored)
    stored["interfaces"] = {"invented": {"Gi1": {"cdp_neighbor": "invented-peer"}}}
    current = graph.build_graph(stored)
    assert current["topology"]["nodes"] == baseline["topology"]["nodes"]
    assert current["topology"]["cables"] == baseline["topology"]["cables"]
    assert [(n["id"], n["degree"]) for n in current["nodes"]] == [(n["id"], n["degree"]) for n in baseline["nodes"]]
    assert current["topology"] == uip.project_topology(stored)


def test_summary_contract_stamp_invalidates_a_recount_cache(client):
    sid = client.post("/api/demo/seed").json()["snapshot"]["id"]
    store = client.app.state.store
    stale = deepcopy(store.get_snapshot_meta(sid)["summary"])
    stale.pop("summary_contract")
    stale["bands"] = {"Critical": 999999}
    store.update_summary(sid, stale)
    refreshed = client.get(f"/api/snapshots/{sid}").json()["summary"]
    assert refreshed["summary_contract"] == summary.SUMMARY_CONTRACT_VERSION
    assert refreshed["assessment"] == uip.project_summary(store.get_snapshot(sid))
    assert refreshed["bands"] != stale["bands"]
