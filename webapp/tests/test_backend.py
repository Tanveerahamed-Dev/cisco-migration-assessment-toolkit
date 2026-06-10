"""End-to-end backend tests for AssessHub against an isolated (temp) SQLite store.

Exercises the full flow the frontend depends on: demo seed, campaign + snapshot CRUD, summary
projection, section slicing, explorer render, compare, and trend — all without touching the real DB
or the engine's golden contract.
"""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # make `backend` importable
_ENGINE_TESTS = str(Path(__file__).resolve().parents[2] / "tests")  # engine fixtures (synthetic collection)
if _ENGINE_TESTS not in sys.path:
    sys.path.append(_ENGINE_TESTS)  # append (not insert) so webapp modules keep import priority

from backend.app import create_app  # noqa: E402


@pytest.fixture()
def client(tmp_path):
    app = create_app(db_path=str(tmp_path / "test.db"))
    with TestClient(app) as c:
        yield c


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert r.json()["sample_available"] is True


def test_demo_seed_then_summary(client):
    r = client.post("/api/demo/seed")
    assert r.status_code == 200, r.text
    body = r.json()
    snap_id = body["snapshot"]["id"]

    # campaign listing carries a latest_summary used on dashboard cards
    cl = client.get("/api/campaigns").json()
    assert len(cl) == 1
    assert cl[0]["n_snapshots"] == 1
    assert cl[0]["latest_summary"]["n_switches"] >= 1

    # snapshot meta + derived summary
    meta = client.get(f"/api/snapshots/{snap_id}").json()
    s = meta["summary"]
    assert s["n_switches"] >= 1
    assert s["punchlist"]["total"] >= 1
    assert set(s["bands"]).issubset(set(["Excellent", "Good", "Fair", "Poor", "Critical"]))
    assert isinstance(s["keystones"], list) and s["keystones"]
    # at least the punch-list section is reported present
    assert any(sec["key"] == "punchlist" for sec in s["sections"])


def test_section_slice_and_guard(client):
    snap_id = client.post("/api/demo/seed").json()["snapshot"]["id"]
    r = client.get(f"/api/snapshots/{snap_id}/section/punchlist")
    assert r.status_code == 200
    assert r.json()["section"] == "punchlist"
    assert isinstance(r.json()["data"], list)
    # unknown section is rejected, not silently empty
    assert client.get(f"/api/snapshots/{snap_id}/section/not_a_section").status_code == 400


def test_explorer_render_embeds_snapshot(client):
    snap_id = client.post("/api/demo/seed").json()["snapshot"]["id"]
    r = client.get(f"/api/snapshots/{snap_id}/explorer")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "EMBEDDED_SNAPSHOT" in r.text  # the live snapshot got baked into the template


def test_upload_and_compare(client):
    c = client.post("/api/campaigns", json={"name": "Wave test"}).json()
    cid = c["id"]
    sample = (Path(__file__).resolve().parents[2] / "tests" / "golden" / "snapshot.json")
    raw = sample.read_bytes()

    def upload(label):
        return client.post(f"/api/campaigns/{cid}/snapshots",
                           files={"file": ("snap.json", raw, "application/json")},
                           data={"label": label})

    a = upload("wave0")
    b = upload("wave1")
    assert a.status_code == 201 and b.status_code == 201

    cmp = client.post("/api/compare", json={"old_id": a.json()["id"], "new_id": b.json()["id"]})
    assert cmp.status_code == 200
    assert "verdict" in cmp.json()

    trend = client.get(f"/api/campaigns/{cid}/trend")
    assert trend.status_code == 200
    assert len(trend.json()["timeline"]) == 2


def test_graph_endpoint(client):
    snap_id = client.post("/api/demo/seed").json()["snapshot"]["id"]
    r = client.get(f"/api/snapshots/{snap_id}/graph")
    assert r.status_code == 200
    g = r.json()
    assert g["nodes"] and g["edges"], "graph should have nodes and edges"
    ids = {n["id"] for n in g["nodes"]}
    # every edge connects two known nodes (no dangling APs/phones)
    for e in g["edges"]:
        assert e["source"] in ids and e["target"] in ids
        assert "is_bridge" in e
    # nodes carry the health band used to colour them
    assert any(n.get("band") for n in g["nodes"])
    # 404 for a missing snapshot
    assert client.get("/api/snapshots/999999/graph").status_code == 404


def test_cutover_plan(client):
    snap_id = client.post("/api/demo/seed").json()["snapshot"]["id"]
    r = client.get(f"/api/snapshots/{snap_id}/cutover")
    assert r.status_code == 200, r.text
    plan = r.json()

    s = plan["summary"]
    assert s["verdict"] in ("GO", "CONDITIONAL GO", "NO-GO")
    assert s["n_waves"] == len(plan["waves"]) >= 1
    # n_devices is corroborated against per-wave bucket membership (an independent recount, not its own
    # definition) — this would fail if a switch were double-counted across buckets/waves.
    bucket_devices = {sw for w in plan["waves"] for sw in (w["make_before_break"] + w["hard_cutover"])}
    assert s["n_devices"] == len(bucket_devices)

    waves = plan["waves"]
    # pilot-first sequencing: order is monotonic and never schedules a worse gate before a better one
    rank = {"GO": 0, "CONDITIONAL GO": 1, "NO-GO": 2}
    assert [w["order"] for w in waves] == list(range(1, len(waves) + 1))
    assert [rank[w["gate"]] for w in waves] == sorted(rank[w["gate"]] for w in waves)

    for w in waves:
        assert w["gate"] in rank
        assert w["strategy"] in ("make-before-break", "hard-cutover", "mixed")
        # a make-before-break-only wave is zero-outage; a hard-cutover wave needs a window
        if not w["hard_cutover"]:
            assert w["est_window_minutes"] == 0
        else:
            assert w["est_window_minutes"] > 0
        # every wave carries a PPDIOO run-of-show ending at the rollback gate
        phases = [step["phase"] for step in w["run_of_show"]]
        assert phases[0] == "Baseline capture" and phases[-1] == "Rollback gate"
        # a NO-GO wave is gated by a failing readiness check or a Critical cross-layer hit
        if w["gate"] == "NO-GO":
            assert w["n_fail"] > 0 or w["critical_crosslayer"]

    assert client.get("/api/snapshots/999999/cutover").status_code == 404


def test_cutover_gate_critical_crosslayer_only():
    """A wave that passes every readiness check but is hit by a Critical cross-layer must still be
    NO-GO — the cross-layer-only gating path the API fixture (which fails on readiness) doesn't reach."""
    from backend import cutover

    snap = {
        "devices": {"sw1": {}, "sw2": {}},
        "wave_sequencing": [{"group": "G1", "make_before_break": ["sw1", "sw2"],
                             "hard_cutover": [], "hard_cutover_endpoints": 0}],
        "migration_readiness": [{"group": "G1", "switches": ["sw1", "sw2"], "readiness": "READY",
                                 "n_fail": 0, "n_warn": 0, "checks": []}],
        "move_groups": [{"switches": ["sw1", "sw2"], "endpoints": 10}],
        "cross_layer": [{"id": "CL-1", "severity": "Critical", "title": "x", "layers": "L1+L3",
                         "recommendation": "fix", "hosts": ["sw1"]}],
    }
    plan = cutover.build_plan(snap)
    wave = plan["waves"][0]
    assert wave["n_fail"] == 0 and wave["critical_crosslayer"]      # readiness clean, cross-layer hit
    assert wave["gate"] == "NO-GO"
    assert plan["summary"]["verdict"] == "NO-GO"


def test_cutover_robust_to_malformed_snapshot():
    """build_plan must degrade gracefully on a malformed (e.g. uploaded) snapshot: a string `hosts`
    field still matches (not split into characters), and non-numeric counters don't crash."""
    from backend import cutover

    snap = {
        "devices": {"sw1": {}},
        "wave_sequencing": [{"group": "G1", "make_before_break": ["sw1"], "hard_cutover": [],
                             "hard_cutover_endpoints": None}],
        "migration_readiness": [{"group": "G1", "switches": ["sw1"], "readiness": "READY",
                                 "n_fail": None, "n_warn": None, "checks": []}],
        "cross_layer": [{"id": "CL-1", "severity": "Critical", "title": "x", "hosts": "sw1"}],  # string
        "failure_impact": [{"host": "sw1", "severity": "High", "stranded": None, "vlans_impacted": "3"}],
    }
    plan = cutover.build_plan(snap)              # must not raise
    wave = plan["waves"][0]
    assert wave["gate"] == "NO-GO"               # the string-host Critical cross-layer still gates
    assert wave["critical_crosslayer"]
    assert wave["blast_radius"]["stranded"] == 0          # None coerced, not crashed
    assert wave["blast_radius"]["vlans_impacted"] == 3    # "3" coerced


def test_deliverables(client):
    snap_id = client.post("/api/demo/seed").json()["snapshot"]["id"]
    cat = client.get("/api/meta").json()["deliverables"]
    assert {d["key"] for d in cat} == {"engagement", "crd", "runbook", "design", "mop", "cutover",
                                       "nrfu", "deck"}
    for d in cat:
        r = client.get(f"/api/snapshots/{snap_id}/deliverable/{d['key']}")
        if d["available"]:
            assert r.status_code == 200, r.text
            assert r.content[:2] == b"PK"          # docx/pptx are ZIP containers
            assert len(r.content) > 1000
            assert d["key"] in r.headers.get("content-disposition", "")
        else:
            assert r.status_code == 503
    assert client.get(f"/api/snapshots/{snap_id}/deliverable/nope").status_code == 400


def test_cutover_deliverable_content(client):
    """The Cutover Plan DOCX is the one deliverable with no engine-side test — validate it actually
    renders the plan (headings + tables), not just that it's a >1KB zip."""
    snap_id = client.post("/api/demo/seed").json()["snapshot"]["id"]
    r = client.get(f"/api/snapshots/{snap_id}/deliverable/cutover")
    if r.status_code == 503:
        pytest.skip("python-docx not installed on this runner")
    assert r.status_code == 200, r.text

    import io

    from docx import Document

    doc = Document(io.BytesIO(r.content))
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "Migration Cutover Plan" in text            # title page
    assert "Recommended wave sequence" in text         # §2 wave table section
    assert "Methodology" in text                       # grounding section
    assert "Run-of-show" in text                       # per-wave run-of-show heading
    assert "Document Control" in text                  # AS-style front matter (V3.23.150)
    assert "Document Acceptance" in text               # closing signature gate
    all_rows = [c.text for t in doc.tables for row in t.rows for c in row.cells]
    assert any("Customer network owner" in c for c in all_rows)   # acceptance roles
    assert len(doc.tables) >= 2                         # summary + sequence tables at minimum
    # V3.23.154: manual step numbering restarts per wave — Word's "List Number" style would
    # continue counting across waves (same defect class as the MOP's e263b6d fix)
    n_ros = sum(1 for p in doc.paragraphs if p.text == "Run-of-show")
    n_first = sum(1 for p in doc.paragraphs if p.text.startswith("1. [Baseline capture]"))
    assert n_ros >= 1 and n_first == n_ros


def test_run_of_show_carries_impact_on_cutover_steps():
    """V3.23.154: the outage/impact callout rides the step that causes it (AS/Barstow convention) —
    an additive `impact` field on the two cutover steps only."""
    from backend.cutover import _run_of_show

    steps = _run_of_show(mbb=["a"], hard=["b"], hard_ep=7, window=45, n_val=3, n_rem=0, blockers=[])
    by_phase = {s["phase"]: s for s in steps}
    assert by_phase["Cutover · make-before-break"]["impact"].startswith("No outage")
    hard = by_phase["Cutover · hard cutover"]["impact"]
    assert hard.startswith("OUTAGE") and "7 endpoint(s)" in hard
    assert "impact" not in by_phase["Baseline capture"]
    assert "impact" not in by_phase["Validation"]


def test_cutover_no_waves_still_carries_acceptance(tmp_path):
    """A degenerate snapshot (no derivable waves) takes the early-return path — the document must
    still carry the full furniture, including the closing acceptance gate (review fix, V3.23.151)."""
    pytest.importorskip("docx")
    from docx import Document

    from backend.cutover_docx import write_cutover_docx

    out = str(tmp_path / "cutover_empty.docx")
    write_cutover_docx(out, {"devices": {}}, "Empty Fleet")
    text = "\n".join(p.text for p in Document(out).paragraphs)
    assert "No migration waves were derived" in text
    assert "Document Control" in text
    assert "Document Acceptance" in text


def test_nrfu_deliverable_content(client):
    """The NRFU / Acceptance Test Plan is a web-layer synthesis with no engine test — validate it
    renders the document-control front matter and all three test phases, not just a valid zip."""
    snap_id = client.post("/api/demo/seed").json()["snapshot"]["id"]
    r = client.get(f"/api/snapshots/{snap_id}/deliverable/nrfu")
    if r.status_code == 503:
        pytest.skip("python-docx not installed on this runner")
    assert r.status_code == 200, r.text
    assert "nrfu" in r.headers.get("content-disposition", "")

    import io

    from docx import Document

    doc = Document(io.BytesIO(r.content))
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "Network Ready-For-Use" in text
    assert "Document control" in text and "Sign-off" in text     # front matter
    assert "Related documents" in text                           # family cross-reference (V3.23.150)
    assert "Phase I" in text and "Phase II" in text and "Phase III" in text
    assert "Entry criteria" in text and "Exit criteria" in text
    # Phase II reuses the engine's validation_plan — its test rows carry a command + expected baseline
    all_rows = [c.text for t in doc.tables for row in t.rows for c in row.cells]
    assert any("NRFU-II-" in c for c in all_rows)                # generated test IDs
    assert any("show " in c for c in all_rows)                   # runnable commands


def test_execution_run_lifecycle(client):
    """The war-room flow end to end: start a run from the cutover plan, check off a step, record
    validation results, scribe a deviation, close out a wave, finish — then the run is read-only."""
    snap_id = client.post("/api/demo/seed").json()["snapshot"]["id"]

    r = client.post(f"/api/snapshots/{snap_id}/executions", json={"label": "", "operator": "lead"})
    assert r.status_code == 201, r.text
    ex = r.json()
    eid = ex["id"]
    assert ex["label"] == "Cutover run 1"            # auto-labelled
    assert ex["status"] == "in_progress" and ex["outcome"] is None

    # the run froze the plan: same wave groups, pilot-first order, steps/checks all pending
    plan = client.get(f"/api/snapshots/{snap_id}/cutover").json()
    assert [w["group"] for w in ex["waves"]] == [w["group"] for w in plan["waves"]]
    w0 = ex["waves"][0]
    assert [s["phase"] for s in w0["steps"]] == [s["phase"] for s in plan["waves"][0]["run_of_show"]]
    assert all(s["status"] == "pending" for w in ex["waves"] for s in w["steps"])
    assert len(w0["checks"]) == len(plan["waves"][0]["validation"])
    assert ex["progress"]["pct"] == 0

    g = w0["group"]
    # step check-off is timestamped and attributed
    ex = client.post(f"/api/executions/{eid}/step",
                     json={"wave": g, "index": 0, "status": "done", "operator": "lead"}).json()
    s0 = ex["waves"][0]["steps"][0]
    assert s0["status"] == "done" and s0["at"] and s0["by"] == "lead"
    assert ex["progress"]["n_steps_done"] == 1 and ex["progress"]["pct"] > 0

    # a failing validation check is recorded AND auto-scribed as a deviation
    ex = client.post(f"/api/executions/{eid}/check",
                     json={"wave": g, "index": 0, "result": "fail",
                           "observed": "neighbor missing", "operator": "lead"}).json()
    assert ex["waves"][0]["checks"][0]["result"] == "fail"
    assert ex["progress"]["checks"]["fail"] == 1
    assert any(e["kind"] == "deviation" and "neighbor missing" in e["text"] for e in ex["events"])

    # explicit deviation + wave closeout
    client.post(f"/api/executions/{eid}/event",
                json={"kind": "deviation", "text": "re-seated SFP", "wave": g})
    ex = client.post(f"/api/executions/{eid}/closeout",
                     json={"wave": g, "decision": "COMPLETE", "note": "with workaround"}).json()
    assert ex["waves"][0]["closeout"]["decision"] == "COMPLETE"
    assert ex["progress"]["waves"][0]["state"] == "complete"

    # finish: outcome derives PARTIAL (other waves never closed), then the run is immutable
    ex = client.post(f"/api/executions/{eid}/finish", json={"status": "completed"}).json()
    assert ex["status"] == "completed" and ex["outcome"] == "PARTIALLY IMPLEMENTED"
    r = client.post(f"/api/executions/{eid}/step", json={"wave": g, "index": 1, "status": "done"})
    assert r.status_code == 409

    # listed under the snapshot; bad inputs rejected; deletable
    runs = client.get(f"/api/snapshots/{snap_id}/executions").json()
    assert [(x["id"], x["status"]) for x in runs] == [(eid, "completed")]
    assert client.post(f"/api/executions/{eid + 99}/step",
                       json={"wave": g, "index": 0, "status": "done"}).status_code == 404
    assert client.delete(f"/api/executions/{eid}").status_code == 204
    assert client.get(f"/api/executions/{eid}").status_code == 404


def test_execution_outcome_vocabulary(client):
    """Outcome derivation follows the PIR vocabulary: a clean run is SUCCESSFUL, a rolled-back wave
    dominates, and an abort is ABORTED regardless of progress."""
    snap_id = client.post("/api/demo/seed").json()["snapshot"]["id"]

    def run():
        return client.post(f"/api/snapshots/{snap_id}/executions", json={}).json()

    def close_all(eid, ex, decision):
        for w in ex["waves"]:
            ex = client.post(f"/api/executions/{eid}/closeout",
                             json={"wave": w["group"], "decision": decision}).json()
        return ex

    # every wave completed, nothing skipped/failed -> SUCCESSFUL
    ex = run()
    ex = close_all(ex["id"], ex, "COMPLETE")
    ex = client.post(f"/api/executions/{ex['id']}/finish", json={"status": "completed"}).json()
    assert ex["outcome"] == "SUCCESSFUL"

    # a rolled-back wave dominates the verdict, even when every other wave completed
    ex = run()
    eid = ex["id"]
    ex = client.post(f"/api/executions/{eid}/closeout",
                     json={"wave": ex["waves"][0]["group"], "decision": "ROLLED BACK"}).json()
    for w in ex["waves"]:
        if not w["closeout"]["decision"]:
            ex = client.post(f"/api/executions/{eid}/closeout",
                             json={"wave": w["group"], "decision": "COMPLETE"}).json()
    ex = client.post(f"/api/executions/{eid}/finish", json={"status": "completed"}).json()
    assert ex["outcome"] == "ROLLED BACK"

    # an aborted run is ABORTED
    ex = run()
    ex = client.post(f"/api/executions/{ex['id']}/finish", json={"status": "aborted"}).json()
    assert ex["outcome"] == "ABORTED"


def test_execution_record_integrity_guards(client):
    """The as-executed record is an audit artifact: negative indexes must not address from the end,
    and a closed-out wave's steps/checks are part of the signed record (409, like a finished run)."""
    snap_id = client.post("/api/demo/seed").json()["snapshot"]["id"]
    ex = client.post(f"/api/snapshots/{snap_id}/executions", json={}).json()
    eid, g = ex["id"], ex["waves"][0]["group"]

    # negative index -> 400, and no step was touched
    r = client.post(f"/api/executions/{eid}/step", json={"wave": g, "index": -1, "status": "done"})
    assert r.status_code == 400
    ex = client.get(f"/api/executions/{eid}").json()
    assert all(s["status"] == "pending" for s in ex["waves"][0]["steps"])

    # close the wave out, then late mutations are conflicts and the record is unchanged
    client.post(f"/api/executions/{eid}/closeout", json={"wave": g, "decision": "COMPLETE"})
    r = client.post(f"/api/executions/{eid}/step", json={"wave": g, "index": 0, "status": "done"})
    assert r.status_code == 409
    r = client.post(f"/api/executions/{eid}/check", json={"wave": g, "index": 0, "result": "pass"})
    assert r.status_code == 409
    r = client.post(f"/api/executions/{eid}/closeout", json={"wave": g, "decision": "ROLLED BACK"})
    assert r.status_code == 409
    ex = client.get(f"/api/executions/{eid}").json()
    assert ex["waves"][0]["closeout"]["decision"] == "COMPLETE"
    assert all(s["status"] == "pending" for s in ex["waves"][0]["steps"])


def test_execution_duplicate_wave_groups_disambiguated():
    """Uploaded snapshots can carry duplicate/missing wave group names — the run must give every
    wave a unique address or mutations for the second wave land on the first."""
    from backend import execution

    snap = {
        "devices": {"sw1": {}, "sw2": {}},
        "wave_sequencing": [{"make_before_break": ["sw1"], "hard_cutover": []},
                            {"make_before_break": ["sw2"], "hard_cutover": []}],
    }
    state = execution.start_run(snap, "run", "")
    groups = [w["group"] for w in state["waves"]]
    assert len(set(groups)) == len(groups) and all(groups)
    execution.apply_step(state, groups[1], 0, "done", "", "op")
    assert state["waves"][1]["steps"][0]["status"] == "done"
    assert state["waves"][0]["steps"][0]["status"] == "pending"


def test_execution_pir_report(client):
    """The PIR / as-executed record renders the run: outcome, planned-vs-actual, the timestamped
    deviation log, and the per-wave validation results."""
    snap_id = client.post("/api/demo/seed").json()["snapshot"]["id"]
    ex = client.post(f"/api/snapshots/{snap_id}/executions",
                     json={"label": "Window 7", "operator": "tanveer"}).json()
    eid = ex["id"]
    g = ex["waves"][0]["group"]
    client.post(f"/api/executions/{eid}/step", json={"wave": g, "index": 0, "status": "done",
                                                     "operator": "tanveer"})
    client.post(f"/api/executions/{eid}/check", json={"wave": g, "index": 0, "result": "pass",
                                                      "operator": "tanveer"})
    client.post(f"/api/executions/{eid}/event",
                json={"kind": "deviation", "text": "uplink LED amber, re-seated SFP", "wave": g})
    client.post(f"/api/executions/{eid}/closeout", json={"wave": g, "decision": "COMPLETE"})
    client.post(f"/api/executions/{eid}/finish", json={"status": "completed"})

    r = client.get(f"/api/executions/{eid}/report")
    if r.status_code == 503:
        pytest.skip("python-docx not installed on this runner")
    assert r.status_code == 200, r.text
    assert r.content[:2] == b"PK"
    assert "pir" in r.headers.get("content-disposition", "")

    import io

    from docx import Document

    doc = Document(io.BytesIO(r.content))
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "Post-Implementation Review" in text
    assert "Window 7" in text
    assert "Planned vs actual" in text
    assert "Timeline & deviation log" in text
    assert "Related documents" in text                            # family cross-reference (V3.23.150)
    all_rows = [c.text for t in doc.tables for row in t.rows for c in row.cells]
    assert any("re-seated SFP" in c for c in all_rows)         # the scribed deviation is in the log
    assert any("PASS" in c for c in all_rows)                  # the recorded validation result
    assert any("tanveer" in c for c in all_rows)               # actions are attributed


def _fixture_collection_zip(tmp_path, wrap="export/fleet", include_devices_json=False) -> bytes:
    """A real offline-collection ZIP built from the engine test-suite's synthetic fixtures."""
    import io
    import zipfile

    import synthetic_fixtures as fx

    root = tmp_path / "zipsrc"
    coll = root / wrap if wrap else root
    fx.write_collection(str(coll))
    if include_devices_json:
        import json
        (coll / "devices.json").write_text(json.dumps(fx.DEVICES), encoding="utf-8")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for p in root.rglob("*"):
            if p.is_file():
                zf.write(p, p.relative_to(root).as_posix())
    return buf.getvalue()


def test_ingest_collection_runs_real_engine(client, tmp_path):
    """The flagship ingest path: a ZIP of raw show outputs (wrapped in a folder, NO devices.json —
    platforms autodetect) is run through the real engine and stored as a first-class snapshot."""
    raw = _fixture_collection_zip(tmp_path)
    cid = client.post("/api/campaigns", json={"name": "ingest"}).json()["id"]
    r = client.post(f"/api/campaigns/{cid}/ingest",
                    files={"file": ("fleet.zip", raw, "application/zip")},
                    data={"label": "Ingested wave"})
    assert r.status_code == 201, r.text
    meta = r.json()
    assert meta["label"] == "Ingested wave"
    assert meta["n_devices"] == 3                       # core1 / core2 / access1
    assert meta["ingest"]["devices_json"] == "synthesized"
    assert sorted(meta["ingest"]["devices"]) == ["access1", "core1", "core2"]

    # the stored snapshot is the engine's own: summary derives and the cutover plan synthesizes
    s = meta["summary"]
    assert s["n_switches"] == 3 and s["punchlist"]["total"] >= 1
    plan = client.get(f"/api/snapshots/{meta['id']}/cutover").json()
    assert plan["summary"]["n_waves"] >= 1


def test_ingest_mismatched_devices_json_falls_back(client, tmp_path):
    """A bundled devices.json whose hostnames match no folder must not be trusted blindly: the run
    falls back to folder-name synthesis (assessing what is actually in the archive) instead of
    pointing the engine at non-existent directories and storing an empty snapshot."""
    import io
    import json
    import zipfile

    import synthetic_fixtures as fx

    root = tmp_path / "zipsrc" / "fleet"
    fx.write_collection(str(root))
    # FQDN hostnames that match no folder
    (root / "devices.json").write_text(json.dumps(
        [{"hostname": f"{h}.example.net", "platform": "ios"} for h in ("core1", "core2", "access1")]),
        encoding="utf-8")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for p in (tmp_path / "zipsrc").rglob("*"):
            if p.is_file():
                zf.write(p, p.relative_to(tmp_path / "zipsrc").as_posix())

    cid = client.post("/api/campaigns", json={"name": "mismatch"}).json()["id"]
    r = client.post(f"/api/campaigns/{cid}/ingest",
                    files={"file": ("fleet.zip", buf.getvalue(), "application/zip")})
    assert r.status_code == 201, r.text
    meta = r.json()
    assert meta["ingest"]["devices_json"] == "synthesized"      # the useless file was not trusted
    assert meta["n_devices"] == 3
    # the snapshot carries REAL parsed data (the empty-snapshot failure mode)
    assert meta["summary"]["punchlist"]["total"] >= 1


def test_ingest_rejects_bad_archives(client, tmp_path):
    import io
    import zipfile

    cid = client.post("/api/campaigns", json={"name": "x"}).json()["id"]

    def post(content, name="c.zip"):
        return client.post(f"/api/campaigns/{cid}/ingest",
                           files={"file": (name, content, "application/zip")})

    # not a zip at all
    assert post(b"definitely not a zip").status_code == 400
    # path traversal entry is refused before anything runs
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../evil.txt", "x")
    r = post(buf.getvalue())
    assert r.status_code == 400 and "traversal" in r.json()["detail"]
    # show outputs at the archive root (no per-device folders) get an actionable message
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("show_interface_status.txt", "Port Name Status")
    r = post(buf.getvalue())
    assert r.status_code == 400 and "own folder" in r.json()["detail"]
    # a zip with no device outputs at all
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("readme.md", "hello")
    r = post(buf.getvalue())
    assert r.status_code == 400 and "No device outputs" in r.json()["detail"]
    # unknown campaign
    raw = _fixture_collection_zip(tmp_path)
    assert client.post("/api/campaigns/999999/ingest",
                       files={"file": ("c.zip", raw, "application/zip")}).status_code == 404


def test_bad_upload_rejected(client):
    cid = client.post("/api/campaigns", json={"name": "x"}).json()["id"]
    r = client.post(f"/api/campaigns/{cid}/snapshots",
                    files={"file": ("bad.json", b"not json", "application/json")},
                    data={"label": "bad"})
    assert r.status_code == 400
