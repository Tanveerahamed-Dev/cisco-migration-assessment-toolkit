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
    assert {d["key"] for d in cat} == {"runbook", "design", "mop", "cutover", "deck"}
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
    assert len(doc.tables) >= 2                         # summary + sequence tables at minimum


def test_bad_upload_rejected(client):
    cid = client.post("/api/campaigns", json={"name": "x"}).json()["id"]
    r = client.post(f"/api/campaigns/{cid}/snapshots",
                    files={"file": ("bad.json", b"not json", "application/json")},
                    data={"label": "bad"})
    assert r.status_code == 400
