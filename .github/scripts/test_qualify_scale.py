"""Hosted failure controls for scale qualification; no customer inputs."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location("qualification", Path(__file__).with_name("qualify_scale.py"))
qualification = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qualification)


def test_hosted_runner_is_required(monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("RUNNER_ENVIRONMENT", "self-hosted")
    with pytest.raises(RuntimeError, match="GitHub-hosted"):
        qualification.hosted_only()


def test_exact_ceiling_and_each_breach():
    budget = qualification.BUDGETS["fixture"]
    assert qualification.breaches(dict(budget), budget) == []
    for key in budget:
        values = {**budget, key: budget[key] + 1}
        assert qualification.breaches(values, budget) == [key]


def test_ingest_fail_soft_phase_cannot_qualify():
    with pytest.raises(AssertionError, match="failed analysis phases"):
        qualification.fleet_check({"assessment_integrity": {"failed_phases": ["Synthetic failed phase"]}}, {})


@pytest.mark.skipif(sys.platform != "linux", reason="Pinned Linux RSS contract")
@pytest.mark.parametrize("failure", ["execution", "artifact_bytes", "wall_seconds", "peak_rss_bytes"])
def test_actual_child_failure_is_retained(tmp_path, monkeypatch, failure):
    work, reports = tmp_path / "work", tmp_path / "reports"
    work.mkdir()
    reports.mkdir()
    budget = {"wall_seconds": 5, "peak_rss_bytes": 128 * qualification.MIB, "artifact_bytes": 1024}
    source = "print('preserved-negative-evidence'); raise SystemExit(7)"
    if failure == "artifact_bytes":
        budget["artifact_bytes"] = 1
        source = f"from pathlib import Path; Path({str(work / 'fixture/large')!r}).write_bytes(b'abc')"
    elif failure == "wall_seconds":
        budget["wall_seconds"] = 0.1
        source = "import time; time.sleep(5)"
    elif failure == "peak_rss_bytes":
        budget["peak_rss_bytes"] = 1
        source = "import time; time.sleep(5)"
    monkeypatch.setitem(qualification.BUDGETS, "fixture", budget)
    row = qualification.measured("fixture", [sys.executable, "-u", "-c", source], work, reports)
    assert row["status"] == "fail"
    if failure == "execution":
        assert row["exit_code"] == 7 and not row["breaches"]
        assert "preserved-negative-evidence" in row["log_tail"]
    else:
        assert failure in row["breaches"]
    assert row["metrics"]["peak_rss_bytes"] > 0
    assert row["budgets"] == budget
    assert (reports / "fixture.log").exists()


def test_fleet_has_distinct_physical_ports_and_reciprocal_inventory():
    from webapp.sample_data.build_scale import ROLE_COUNTS, VLAN_IDS, addresses_for, layout
    roles, links = layout()
    assert len(roles) == sum(ROLE_COUNTS.values()) == 300
    assert len(VLAN_IDS) == 200 and len(links) == 1500
    ports = [(link[side], link[side + "_port"]) for link in links for side in ("a", "b")]
    assert len(ports) == len(set(ports))
    assert all(link["a"] != link["b"] for link in links)
    assert sum(link["b"] not in roles for link in links) == 868
    assert layout() == (roles, links)
    addresses = addresses_for(roles, links)
    assert len(addresses) == len(set(addresses.values())) == 1168
    assert addresses == addresses_for(roles, links)


def test_captures_are_substantial_deterministic_and_pod_consistent():
    from webapp.sample_data.build_scale import addresses_for, captures, layout
    roles, links = layout()
    addresses = addresses_for(roles, links)
    outputs = []
    for host, idx in (("access001", 0), ("distribution001", 240)):
        neighbours = []
        for link in links:
            for side, other in (("a", "b"), ("b", "a")):
                if link[side] == host:
                    neighbours.append((link[side + "_port"], link[other], link[other + "_port"]))
        args = (host, roles[host], idx, neighbours, roles, addresses)
        first = captures(*args)
        assert first == captures(*args)
        assert sum(len(text.encode()) for text in first.values()) > 250_000
        assert "100" in first["show vlan brief"] and "109" in first["show vlan brief"]
        assert "110" not in first["show vlan brief"]
        outputs.append(first)
    assert "Device ID: distribution001.lab" in outputs[0]["show cdp neighbors detail"]
    assert "Device ID: access001.lab" in outputs[1]["show cdp neighbors detail"]
    assert "Device ID: phone-001-1\n" in outputs[0]["show cdp neighbors detail"]
    assert "Platform: cisco IP Phone 8841," in outputs[0]["show cdp neighbors detail"]
    assert "IP address: 10.0.102.100" in outputs[0]["show cdp neighbors detail"]


def test_workflows_have_no_automatic_pr_qualification():
    def read(relative):
        return yaml.load((ROOT / relative).read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    weekly = read(".github/workflows/scale-qualification.yml")
    assert set(weekly["on"]) == {"workflow_dispatch", "schedule"}
    assert weekly["on"]["schedule"] == [{"cron": "23 2 * * 1"}]
    assert weekly["permissions"] == {"contents": "read"}
    job = weekly["jobs"]["qualify"]
    assert job["runs-on"] == "ubuntu-24.04"
    ci = read(".github/workflows/ci.yml")
    bootstrap = ci["jobs"]["scale-qualification"]
    assert bootstrap["if"] == "${{ github.event_name == 'workflow_dispatch' && inputs.measure_scale_qualification }}"
    assert ci["on"]["workflow_dispatch"]["inputs"]["measure_scale_qualification"]["default"] == "false"
    assert job["steps"][1]["uses"] == bootstrap["steps"][1]["uses"] == "./.github/actions/scale-qualification"
    composite = read(".github/actions/scale-qualification/action.yml")
    steps = composite["runs"]["steps"]
    assert steps[-1]["if"] == "${{ always() }}"
    assert "test \"$RUNNER_ENVIRONMENT\" = github-hosted" in steps[0]["run"]
    assert "test \"$EXPECTED_SOURCE_COMMIT\" = \"$GITHUB_SHA\"" in steps[0]["run"]
    for step in steps:
        if "uses" in step:
            action, sha = step["uses"].split("@")
            assert action.startswith("actions/") and len(sha) == 40


def test_architecture_dependencies_are_exact_harness_paths():
    contract = json.loads((ROOT / "master-reference/governance/architecture.json").read_text())
    assert ["release_distribution", "assesshub_backend"] not in contract["allowed_edges"]
    assert ["release_distribution", "analysis"] not in contract["allowed_edges"]
    pairs = {(row["source_path"], row["target_path"]) for row in contract["allowed_static_path_edges"]
             if row["source_path"].startswith(".github/scripts/") and "qualify_scale" in row["source_path"]}
    assert pairs == {
        (".github/scripts/qualify_scale.py", "cisco_toolkit/analyze.py"),
        (".github/scripts/qualify_scale.py", "webapp/backend/app.py"),
        (".github/scripts/qualify_scale.py", "webapp/backend/ui_projection_api.py"),
        (".github/scripts/qualify_scale.py", "webapp/sample_data/build_scale.py"),
        (".github/scripts/test_qualify_scale.py", "webapp/sample_data/build_scale.py"),
    }


def test_report_keeps_failed_and_skipped_stages():
    report = {"status": "fail", "source_commit": "a" * 40, "runner_os": "Linux", "image_version": "test",
              "stages": [{"stage": "fixture", "status": "fail", "budgets": qualification.BUDGETS["fixture"],
                          "metrics": {"wall_seconds": 61, "peak_rss_bytes": 10, "artifact_bytes": 20},
                          "breaches": ["wall_seconds"], "log_tail": ["negative evidence"]},
                         {"stage": "engine", "status": "skipped", "budgets": qualification.BUDGETS["engine"], "breaches": []}]}
    text = qualification.summary(report)
    assert "FAIL" in text and "negative evidence" in text and "not run" in text
    assert json.loads(json.dumps(report))["stages"][0]["breaches"] == ["wall_seconds"]
