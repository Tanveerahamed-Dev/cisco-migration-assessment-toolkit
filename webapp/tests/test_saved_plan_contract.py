"""R1-R20 hosted contract regressions. Synthetic data; never run on the workstation."""
from __future__ import annotations

import ast
import copy
import inspect
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import app as app_module, deliverables, storage  # noqa: E402
from cisco_toolkit import design_advisor  # noqa: E402
from test_saved_plan_api import _source, _state, _save, _params  # noqa: E402
from test_saved_plan_exports import _snapshot, _plan  # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.delenv("ASSESSHUB_TOKEN", raising=False)
    app = app_module.create_app(db_path=str(tmp_path / "contract-plans.db"))
    with TestClient(app, base_url="http://localhost") as http:
        yield http


def _main_equivalent(requirements):
    """Frozen b8d6029b deliverables.py:523-538 post-processing, default profile."""
    from cisco_toolkit.design_advisor import requirements_from_interview, REQUIREMENTS_FABRIC_MODELS
    from backend.deliverables import SavedPlanError, _saved_plan_json, SAVED_PLAN_REQUIREMENTS_BYTES
    register = {
        key: value for key, value in requirements_from_interview(requirements).items()
        if value is not None and value != "" and value != [] and value != {}
    }
    if requirements.get("fabric_operating_model") and "fabric_operating_model" not in register:
        raise SavedPlanError("Saved plan fabric operating model is unsupported")
    if ("fabric_operating_model" in register
            and register["fabric_operating_model"] not in REQUIREMENTS_FABRIC_MODELS):
        raise SavedPlanError("Saved plan fabric operating model is unsupported")
    # A persisted JSON object has string keys, including the normalizer's integer VLAN keys.
    if "vlan_zones" in register:
        register["vlan_zones"] = {str(vid): zone for vid, zone in register["vlan_zones"].items()}
    encoded = _saved_plan_json(register)
    if len(encoded) > SAVED_PLAN_REQUIREMENTS_BYTES:
        raise SavedPlanError("Normalized saved plan requirements exceed the 64 KiB limit")
    return json.loads(encoded)


_BAD_ROWS = [
    [], ["not a map"], {"raw_rows": []},
    {"raw_rows": [{"zone": "", "vids": "10"}]},
    {"raw_rows": [{"zone": "EXAMPLE", "vids": ""}]},
    {"raw_rows": [{"zone": "", "vids": ""}]},
    {"raw_rows": [{"zone": "EXAMPLE", "vids": "0"}]},
    {"raw_rows": [{"zone": "EXAMPLE", "vids": "4095"}]},
    {"raw_rows": [{"zone": "EXAMPLE", "vids": "１０"}]},
    {"raw_rows": [{"zone": "EXAMPLE", "vids": "1e1"}]},
    {"raw_rows": [{"zone": "EXAMPLE", "vids": "10,,20"}]},
    {"raw_rows": [{"zone": "EXAMPLE", "vids": "10,"}]},
    {"raw_rows": [{"zone": "EXAMPLE", "vids": "10-20"}]},
    {"raw_rows": [{"zone": "EXAMPLE", "vids": 10}]},
    {"raw_rows": [{"zone": "EXAMPLE", "vids": "10", "extra": "PRIVATE_SENTINEL"}]},
    {"raw_rows": [{"zone": "EXAMPLE A", "vids": "10"}, {"zone": "EXAMPLE B", "vids": "010"}]},
    {"raw_rows": [{"zone": "EXAMPLE", "vids": "10"}, {"zone": " EXAMPLE ", "vids": "20"}]},
    {"raw_rows": [{"zone": "EXAMPLE", "vids": "10, 10"}]},
    {"raw_rows": [{"zone": "EXAMPLE", "vids": "10"}], "extra": "PRIVATE_SENTINEL"},
    {"guest": [True]}, {"guest": [10], "storage": [10]}, {"guest": [10], "storage": "invalid"},
]


@pytest.mark.parametrize("zones", _BAD_ROWS)
def test_raw_vlan_rows_refuse_at_the_engine_and_real_route_without_writes(client, zones, caplog):
    with pytest.raises(ValueError):
        design_advisor.requirements_from_interview({"vlan_zones": zones}, profile="saved_plan")
    _, sid = _source(client)
    state = _state(client, sid)
    response = client.post(f"/api/snapshots/{sid}/plans", json={
        "label": "EXAMPLE", "assessment": state["assessment"], "expected_selection_id": 0,
        "requirements": {"vlan_zones": zones},
    })
    assert response.status_code == 400
    assert "PRIVATE_SENTINEL" not in response.text + caplog.text
    assert _state(client, sid) == state


@pytest.mark.parametrize("zones", [
    {"raw_rows": [{"zone": " EXAMPLE ", "vids": " 10, 0020 "}, {"zone": "EXAMPLE B", "vids": "4094"}]},
    {"EXAMPLE": [10, "20"], "EXAMPLE B": [4094]},
    {"10": "EXAMPLE", "20": "EXAMPLE", "4094": "EXAMPLE B"},
])
def test_raw_grouped_and_flat_vlan_inputs_share_unchanged_canonical_storage(client, zones):
    _, sid = _source(client)
    state = _state(client, sid)
    response = client.post(f"/api/snapshots/{sid}/plans", json={
        "label": "EXAMPLE", "assessment": state["assessment"], "expected_selection_id": 0,
        "requirements": {"vlan_zones": zones},
    })
    assert response.status_code == 201, response.text
    first = response.json()
    assert first["projection"]["requirements"] == {"vlan_zones": {
        "10": "EXAMPLE", "20": "EXAMPLE", "4094": "EXAMPLE B",
    }}
    form = first["vlan_form_rows"]
    assert {row["zone"] for row in form} == {"EXAMPLE", "EXAMPLE B"}
    assert len(form) == 2  # Owner groups a zone once so reopen/resave cannot invent duplicate rows.
    again = client.post(f"/api/snapshots/{sid}/plans", json={
        "label": "EXAMPLE reopened", "assessment": state["assessment"],
        "expected_selection_id": first["selection_id"], "requirements": {"vlan_zones": {"raw_rows": form}},
    })
    assert again.status_code == 201, again.text
    assert again.json()["projection"]["requirements"] == first["projection"]["requirements"]
    persisted = client.app.state.store.get_saved_plan_context(
        sid, again.json()["revision"], again.json()["sha256"], again.json()["selection_id"])["plan"]
    assert "vlan_form_rows" not in persisted
    assert persisted["sha256"] == storage.saved_plan_digest(persisted)


@pytest.mark.parametrize("value", [True, 2.0, -1, "0.5", "1e3", "１２", "9007199254740992",
                                  "9007199254740993", "9223372036854775808", (1 << 53)])
def test_convergence_owner_refusals_are_value_free_real_route_400s(client, value, caplog):
    _, sid = _source(client)
    state = _state(client, sid)
    with pytest.raises(ValueError):
        design_advisor.requirements_from_interview({"convergence_budget_ms": value}, profile="saved_plan")
    response = client.post(f"/api/snapshots/{sid}/plans", json={
        "label": "EXAMPLE", "assessment": state["assessment"], "expected_selection_id": 0,
        "requirements": {"convergence_budget_ms": value, "constraints": ["PRIVATE_SENTINEL"]},
    })
    assert response.status_code == 400
    assert "PRIVATE_SENTINEL" not in response.text + caplog.text
    assert _state(client, sid) == state


_COMPATIBILITY = [
    {}, {"critical_apps": " , "}, {"growth_horizon": " "},
    {"critical_apps": " voice, video "}, {"critical_apps": ["voice", " video "]},
    {"constraints": "cost, security"}, {"constraints": ["cost"]},
    {"data_classification": "EXAMPLE A,EXAMPLE B"}, {"data_classification": ["EXAMPLE A"]},
    {"address_space": "192.0.2.0/24"}, {"growth_horizon": "EXAMPLE three years"},
    {"vlan_zones": {"EXAMPLE": [10, "20"]}}, {"vlan_zones": {"10": "EXAMPLE"}},
    {"convergence_budget_ms": 0}, {"convergence_budget_ms": (1 << 53) - 1},
    *[{"availability_tier": tier} for tier in design_advisor.REQUIREMENTS_AVAILABILITY_TIERS],
    *[{"fabric_operating_model": model} for model in design_advisor.REQUIREMENTS_FABRIC_MODELS],
]


@pytest.mark.parametrize("requirements", _COMPATIBILITY)
def test_main_equivalent_records_remain_byte_canonical_and_get_select_export_compatible(client, monkeypatch, requirements):
    _, sid = _source(client)
    store = client.app.state.store
    snapshot, binding = store.get_bound_snapshot(sid)
    expected = _main_equivalent(requirements)
    assert deliverables._saved_plan_requirements(expected) == expected
    # Produce a genuinely default-profile projection; do not use the strict profile as its own oracle.
    with monkeypatch.context() as local:
        local.setattr(deliverables, "_saved_plan_requirements", _main_equivalent)
        projection = deliverables.prepare_saved_plan(snapshot, requirements)
    assert json.dumps(projection["requirements"], sort_keys=True) == json.dumps(expected, sort_keys=True)
    saved_bytes = store.save_plan_revision(sid, "EXAMPLE main-equivalent", projection, binding, 0,
        admit=lambda record: app_module._prepare_new_saved_plan(snapshot, record),
        finalize=app_module._finish_saved_plan)
    saved = json.loads(saved_bytes)
    response = client.get(f"/api/snapshots/{sid}/plans/1", params=_params(saved))
    assert response.status_code == 200 and response.content == saved_bytes
    selected = client.post(f"/api/snapshots/{sid}/plans/1/select", json={
        "plan_sha256": saved["sha256"], "expected_selection_id": saved["selection_id"],
    })
    assert selected.status_code == 200, selected.text
    reopened = client.get(f"/api/snapshots/{sid}/plans/1", params=_params(selected.json()))
    assert reopened.content == selected.content
    assert reopened.json()["projection"] == projection
    exported = client.get(f"/api/snapshots/{sid}/plans/1/deliverable/nrfu", params=_params(selected.json()))
    assert exported.status_code == 200, exported.text[:300]
    assert exported.headers["x-atlas-plan-sha256"] == saved["sha256"]


def test_compatibility_parameter_set_covers_every_owner_requirement_key():
    assert set().union(*(row.keys() for row in _COMPATIBILITY)) == set(design_advisor.REQUIREMENTS_KEYS)


def test_previously_exportable_above_bound_record_is_preserved_and_withheld(client, monkeypatch):
    _, sid = _source(client)
    store = client.app.state.store
    snapshot, binding = store.get_bound_snapshot(sid)
    with monkeypatch.context() as local:
        local.setattr(deliverables, "_saved_plan_requirements", _main_equivalent)
        projection = deliverables.prepare_saved_plan(snapshot, {"convergence_budget_ms": 1 << 53})
    assert projection["requirements"]["convergence_budget_ms"] == 1 << 53
    record = store.save_plan_revision(sid, "EXAMPLE legacy bound", projection, binding, 0,
        admit=lambda candidate: candidate, finalize=lambda _candidate, row: row)
    before = store._conn.execute("SELECT plan_json FROM plan_revisions").fetchone()[0]
    # List performs no per-revision semantic validation.
    assert client.get(f"/api/snapshots/{sid}/plans").status_code == 200
    opened = client.get(f"/api/snapshots/{sid}/plans/1", params=_params(record))
    assert opened.status_code == 409 and opened.json()["cause"] == "PLAN_CONTENT_NOT_ADMITTED"
    exported = client.get(f"/api/snapshots/{sid}/plans/1/deliverable/mop", params=_params(record))
    assert exported.status_code == 409
    assert store._conn.execute("SELECT plan_json FROM plan_revisions").fetchone()[0] == before


_MISSING = object()


@pytest.mark.parametrize("selection", [_MISSING, None, 0, -1, 1.0, True, "1"])
def test_default_selection_guard_refuses_every_renderer_and_existing_facade(selection):
    snapshot = _snapshot()
    plan = _plan(snapshot)
    if selection is _MISSING:
        del plan["selection_id"]
    else:
        plan["selection_id"] = selection
    with pytest.raises(deliverables.SavedPlanError):
        deliverables.render_saved_plan(snapshot, plan)
    with pytest.raises(deliverables.SavedPlanError):
        deliverables.generate_saved_plan("nrfu", snapshot, "EXAMPLE", plan)
    with pytest.raises(app_module.PlanContentError):
        app_module._prepare_existing_saved_plan(snapshot, plan)


@pytest.mark.parametrize("changes", [
    {"schema": "PRIVATE_SENTINEL"}, {"status": "APPROVED"}, {"revision": 0}, {"revision": 65},
    {"revision": True}, {"revision": "1"}, {"extra": "PRIVATE_SENTINEL"}, {"selection_id": None},
])
def test_absent_mode_wraps_the_complete_envelope_guard(changes):
    snapshot = _snapshot()
    plan = _plan(snapshot)
    del plan["selection_id"]
    plan.update(changes)
    with pytest.raises(app_module.PlanCandidateError):
        app_module._prepare_new_saved_plan(snapshot, plan)


def test_absent_mode_is_internal_and_has_one_exact_production_call_site():
    root = Path(__file__).resolve().parents[2]
    calls = []
    for source in (root / "webapp/backend").glob("*.py"):
        tree = ast.parse(source.read_text(encoding="utf-8"))
        for definition in ast.walk(tree):
            if isinstance(definition, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for node in ast.walk(definition):
                    if isinstance(node, ast.Call) and getattr(node.func, "attr", None) == "_validated_saved_plan":
                        if any(k.arg == "context" for k in node.keywords):
                            calls.append((source.name, definition.name, ast.unparse(node)))
    assert len(calls) == 1 and calls[0][:2] == ("app.py", "_prepare_new_saved_plan")
    assert 'context="absent"' in calls[0][2] or "context='absent'" in calls[0][2]
    assert "context" not in app_module.SavedPlanIn.model_fields
    assert "context" not in app_module.SavedPlanSelectionIn.model_fields
    assert "context" not in inspect.getsource(storage.Store.list_saved_plans)
    assert "_validated_saved_plan" not in inspect.getsource(storage.Store.list_saved_plans)


def test_revision_two_admission_has_no_placeholder_and_response_uses_actual_event(client, monkeypatch):
    _, sid = _source(client)
    original = deliverables._validated_saved_plan
    seen = []

    def capture(snapshot, record, *, context=None):
        if context == "absent":
            assert "selection_id" not in record
            seen.append(record["revision"])
        return original(snapshot, record, context=context)

    monkeypatch.setattr(deliverables, "_validated_saved_plan", capture)
    first = _save(client, sid, _state(client, sid))
    second = _save(client, sid, _state(client, sid), "nxos-evpn")
    assert seen == [1, 2]
    event = client.app.state.store._conn.execute(
        "SELECT id FROM plan_selection_events WHERE snapshot_id=? ORDER BY id DESC LIMIT 1", (sid,)).fetchone()[0]
    assert second["revision"] == 2 and second["selection_id"] == event > first["selection_id"]


def test_paused_admission_does_not_hold_the_store_lock(client, monkeypatch):
    _, sid = _source(client)
    state = _state(client, sid)
    entered, release = threading.Event(), threading.Event()
    original = app_module._prepare_new_saved_plan

    def pause(snapshot, record):
        entered.set()
        assert release.wait(5), "test admission was not released"
        return original(snapshot, record)

    monkeypatch.setattr(app_module, "_prepare_new_saved_plan", pause)
    with ThreadPoolExecutor(max_workers=2) as pool:
        saving = pool.submit(client.post, f"/api/snapshots/{sid}/plans", json={
            "label": "EXAMPLE", "requirements": {}, "assessment": state["assessment"], "expected_selection_id": 0,
        })
        try:
            assert entered.wait(5)
            read = pool.submit(client.app.state.store.list_saved_plans, sid)
            assert read.result(timeout=2)["revisions"] == []
        finally:
            release.set()
        assert saving.result(timeout=10).status_code == 201


def test_pir_has_no_saved_plan_basis_and_the_route_refuses(client):
    assert deliverables.saved_plan_basis("pir") is None
    _, sid = _source(client)
    plan = _save(client, sid, _state(client, sid))
    response = client.get(f"/api/snapshots/{sid}/plans/1/deliverable/pir", params=_params(plan))
    assert response.status_code in (400, 409)


@pytest.mark.parametrize("selection", [_MISSING, None, -1, 1.0, True, "1"])
@pytest.mark.parametrize("operation", ["get", "select", "export"])
def test_default_facade_paths_never_infer_absent_mode_from_record_content(client, monkeypatch, selection, operation):
    _, sid = _source(client)
    plan = _save(client, sid, _state(client, sid))
    store = client.app.state.store
    context = store.get_saved_plan_context(sid, 1, plan["sha256"], plan["selection_id"])
    wrong = copy.deepcopy(context["plan"])
    if selection is _MISSING:
        del wrong["selection_id"]
    else:
        wrong["selection_id"] = selection
    before = store._conn.execute("SELECT COUNT(*) FROM plan_selection_events").fetchone()[0]
    if operation == "select":
        monkeypatch.setattr(store, "_plan_selection_input", lambda *_args: wrong)
        response = client.post(f"/api/snapshots/{sid}/plans/1/select", json={
            "plan_sha256": plan["sha256"], "expected_selection_id": plan["selection_id"],
        })
    else:
        monkeypatch.setattr(store, "get_saved_plan_context", lambda *_args: {**context, "plan": wrong})
        suffix = "/deliverable/nrfu" if operation == "export" else ""
        response = client.get(f"/api/snapshots/{sid}/plans/1{suffix}", params=_params(plan))
    assert response.status_code == 409, response.text
    assert store._conn.execute("SELECT COUNT(*) FROM plan_selection_events").fetchone()[0] == before


@pytest.mark.parametrize("defect", ["digest", "n_items", "requirements"])
def test_server_candidate_not_admitted_has_distinct_safe_cause_and_writes_nothing(client, monkeypatch, defect, caplog):
    _, sid = _source(client)
    state = _state(client, sid)
    original = app_module._prepare_new_saved_plan

    def broken(snapshot, candidate):
        if defect == "digest":
            candidate["sha256"] = "sha256:" + "f" * 64
        else:
            if defect == "n_items":
                candidate["projection"]["sections"]["design_nrfu"]["n_items"] += 1
            else:
                candidate["projection"]["requirements"]["critical_apps"] = "PRIVATE_SENTINEL"
            candidate["sha256"] = storage.saved_plan_digest(candidate)
        return original(snapshot, candidate)

    monkeypatch.setattr(app_module, "_prepare_new_saved_plan", broken)
    response = client.post(f"/api/snapshots/{sid}/plans", json={
        "label": "EXAMPLE", "requirements": {}, "assessment": state["assessment"], "expected_selection_id": 0,
    })
    assert response.status_code == 400
    assert response.json() == {
        "detail": "The server-derived plan candidate was not admitted. Nothing was saved.",
        "cause": "PLAN_CANDIDATE_NOT_ADMITTED",
    }
    assert "PRIVATE_SENTINEL" not in response.text + caplog.text
    assert _state(client, sid) == state
    for table in ("plan_revisions", "plan_revision_authority", "plan_selection_events"):
        assert client.app.state.store._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


def test_sixty_fifth_save_stays_storage_413_before_envelope_or_admission(client, monkeypatch):
    _, sid = _source(client)
    for _ in range(64):
        _save(client, sid, _state(client, sid))
    state = _state(client, sid)

    def forbidden(*_args, **_kwargs):
        pytest.fail("65th save constructed or admitted a candidate")

    monkeypatch.setattr(app_module, "_prepare_new_saved_plan", forbidden)
    monkeypatch.setattr(storage, "_saved_plan_envelope_bytes", forbidden)
    response = client.post(f"/api/snapshots/{sid}/plans", json={
        "label": "EXAMPLE 65", "requirements": {}, "assessment": state["assessment"],
        "expected_selection_id": state["selection_id"],
    })
    assert response.status_code == 413
    assert "revision limit (64)" in response.text
    store = client.app.state.store
    assert tuple(store._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                 for table in ("plan_revisions", "plan_revision_authority", "plan_selection_events")) == (64, 64, 64)


@pytest.mark.parametrize("label", ["😀" * 200, "\u001cEXAMPLE\ufeff"])
def test_label_echo_is_server_owned_and_renderable_without_browser_normalization(client, label):
    _, sid = _source(client)
    state = _state(client, sid)
    response = client.post(f"/api/snapshots/{sid}/plans", json={
        "label": label, "requirements": {}, "assessment": state["assessment"], "expected_selection_id": 0,
    })
    assert response.status_code == 201, response.text
    assert response.json()["label"] == label.strip()
    opened = client.get(f"/api/snapshots/{sid}/plans/1", params=_params(response.json()))
    assert opened.content == response.content


def test_label_above_two_hundred_code_points_still_refuses(client):
    _, sid = _source(client)
    state = _state(client, sid)
    response = client.post(f"/api/snapshots/{sid}/plans", json={
        "label": "😀" * 201, "requirements": {}, "assessment": state["assessment"], "expected_selection_id": 0,
    })
    assert response.status_code == 422
    assert _state(client, sid) == state


def test_wire_id_exhaustion_is_permanent_413_with_no_publication(client):
    _, sid = _source(client)
    state = _state(client, sid)
    store = client.app.state.store
    store._conn.execute("INSERT INTO sqlite_sequence(name,seq) VALUES (?,?)",
                        ("plan_selection_events", (1 << 53) - 1))
    store._conn.commit()
    for _ in range(2):
        response = client.post(f"/api/snapshots/{sid}/plans", json={
            "label": "EXAMPLE", "requirements": {}, "assessment": state["assessment"], "expected_selection_id": 0,
        })
        assert response.status_code == 413
        assert response.json()["cause"] == "PLAN_WIRE_ID_LIMIT"
        assert _state(client, sid) == state
    assert store._conn.execute("SELECT seq FROM sqlite_sequence WHERE name='plan_selection_events'").fetchone()[0] == (1 << 53) - 1
    # Request limits are still I64, independent of response/allocated limits.
    assert app_module.SavedPlanSelectionIn(plan_sha256="sha256:" + "a" * 64, expected_selection_id=(1 << 63) - 1)
    assert app_module.SavedPlanIn(label="EXAMPLE", assessment={}, expected_selection_id=(1 << 63) - 1)


def test_payload_finite_only_and_minimal_dto_are_distinct_from_semantic_admission():
    snapshot = _snapshot()
    plan = _plan(snapshot)
    plan["projection"]["sections"]["design_blueprint"]["opaque_finite"] = float("nan")
    # An unrenderable extra is not silently coerced to an empty substitute.
    with pytest.raises(ValueError):
        app_module._plan_payload(plan)


def test_fresh_app_structure_has_only_owner_shapes_and_runtime_domains(client, tmp_path):
    fresh = app_module.create_app(db_path=str(tmp_path / "fresh-structure.db"))
    try:
        schema = fresh.openapi()
        owner = design_advisor.requirements_structure()
        component = schema["components"]["schemas"]["SavedPlanRequirements"]
        assert component == owner
        assert set(component["properties"]) == set(design_advisor.REQUIREMENTS_KEYS)
        encoded = json.dumps(component)
        for forbidden in ('"minimum"', '"maximum"', '"enum"', '"gold"', '"nxos-evpn"', "9007199254740991"):
            assert forbidden not in encoded
        contract = client.get("/api/saved-plan-contract")
        assert contract.status_code == 200 and contract.headers["cache-control"] == "no-store"
        assert contract.json()["requirements"] == design_advisor.requirements_contract()
        assert contract.json()["requirements"]["convergence_budget_ms"]["maximum"] == (1 << 53) - 1
        assert all(type(row["saved_plan_supported"]) is bool for row in contract.json()["catalogue"])
    finally:
        fresh.state.store.close()




def test_storage_schema_all_checks_triggers_and_frozen_saved_plan_policy(client):
    import re
    import sqlite3
    from collections import Counter

    baseline = json.loads((Path(__file__).parent / "fixtures/saved-plan-storage-parity.json").read_text())
    source = Path(storage.__file__).read_text()
    tree = ast.parse(source)
    assert storage._SCHEMA == baseline["schema"]  # Every CHECK and every trigger, not selected examples.
    envelope = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_saved_plan_envelope_bytes")
    assert ast.get_source_segment(source, envelope) == baseline["envelope_source"]
    for fragment in [*baseline["save_guards"], baseline["revision_increment"], baseline["marker_migration"]]:
        assert source.count(fragment) == 1

    def tokens(sql):
        return [match.group() for match in re.finditer(
            r"'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|--[^\n]*|/\*.*?\*/|[A-Za-z_]\w*|[^\s]", sql, re.S)
            if not match.group().startswith(("--", "/*"))]

    def checks(sql):
        items, result = tokens(sql), []
        for pos, token in enumerate(items):
            if token.upper() != "CHECK":
                continue
            assert items[pos + 1] == "("
            depth, part = 0, []
            for token in items[pos + 1:]:
                part.append(token)
                if token == "(":
                    depth += 1
                elif token == ")":
                    depth -= 1
                if depth == 0:
                    break
            assert depth == 0 and part[-1] == ")"
            result.append(tuple(part))
        return result

    expected = sqlite3.connect(":memory:")
    try:
        expected.executescript(baseline["schema"])
        expected_rows = expected.execute(
            "SELECT type,name,sql FROM sqlite_master WHERE type IN ('table','trigger') AND sql IS NOT NULL").fetchall()
        actual_rows = client.app.state.store._conn.execute(
            "SELECT type,name,sql FROM sqlite_master WHERE type IN ('table','trigger') AND sql IS NOT NULL").fetchall()
        expected_checks = Counter(check for kind, _name, sql in expected_rows if kind == "table" for check in checks(sql))
        actual_checks = Counter(check for kind, _name, sql in actual_rows if kind == "table" for check in checks(sql))
        assert expected_checks and actual_checks == expected_checks
        expected_triggers = {name: tokens(sql) for kind, name, sql in expected_rows if kind == "trigger"}
        actual_triggers = {name: tokens(sql) for kind, name, sql in actual_rows if kind == "trigger"}
        assert expected_triggers and actual_triggers == expected_triggers
        # Resolve both durable revision bounds from the complete mechanical census.
        revision_checks = [check for check in actual_checks if "revision" in check or "saved_plan_revision_count" in check]
        assert len(revision_checks) == 2
        assert all("64" in check for check in revision_checks)
        contract = client.get("/api/saved-plan-contract").json()["display_limits"]
        assert contract["revision_maximum"] == storage.SAVED_PLAN_MAX_REVISIONS == 64
        label_guard = baseline["save_guards"][0]
        label_bound = int(re.search(r"len\(label\) <= (\d+)", label_guard).group(1))
        assert contract["label_maximum_code_points"] == app_module._LEN_NAME == label_bound
    finally:
        expected.close()
def test_real_owner_definitions_are_coherent_and_structure_covers_future_list_keys(monkeypatch):
    contract = design_advisor.requirements_contract()
    assert len(contract["keys"]) == len(set(contract["keys"]))
    assert set(contract["list_fields"]) <= set(contract["keys"])
    assert len(contract["availability_tiers"]) == len(set(contract["availability_tiers"]))
    assert len(contract["fabric_models"]) == len(set(contract["fabric_models"]))
    assert contract["vlan_id"]["minimum"] <= contract["vlan_id"]["maximum"]
    monkeypatch.setattr(design_advisor, "REQUIREMENTS_KEYS", tuple(design_advisor.REQUIREMENTS_KEYS) + ("future_list",))
    monkeypatch.setattr(design_advisor, "REQUIREMENTS_LIST_KEYS", tuple(design_advisor.REQUIREMENTS_LIST_KEYS) + ("future_list",))
    assert design_advisor.requirements_structure(canonical=True)["properties"]["future_list"] == {
        "type": "array", "items": {"type": "string"},
    }
    assert "future_list" in design_advisor.requirements_contract()["list_fields"]


def test_semantically_admitted_but_unrenderable_data_has_safe_distinct_route_refusal(client, monkeypatch, caplog):
    _, sid = _source(client)
    plan = _save(client, sid, _state(client, sid))
    store = client.app.state.store
    context = store.get_saved_plan_context(sid, 1, plan["sha256"], plan["selection_id"])
    record = copy.deepcopy(context["plan"])
    record["projection"]["sections"]["design_blueprint"]["summary"]["headline"] = {"PRIVATE_SENTINEL": "not text"}
    record["sha256"] = storage.saved_plan_digest(record)
    deliverables._validated_saved_plan(context["snapshot"], record)
    monkeypatch.setattr(store, "get_saved_plan_context", lambda *_args: {**context, "plan": record})
    response = client.get(f"/api/snapshots/{sid}/plans/1", params=_params(record))
    assert response.status_code == 409 and response.json()["cause"] == "PLAN_RENDER_REFUSED"
    assert "PRIVATE_SENTINEL" not in response.text + caplog.text


def test_declarative_response_policy_retains_server_only_positivity_and_posture():
    from pydantic import ValidationError

    plan = _plan(_snapshot())
    for field in ("snapshot_id", "campaign_id", "bytes"):
        with pytest.raises(ValidationError):
            app_module.SavedPlanAssessmentResponse.model_validate({**plan["assessment"], field: 0})
    metadata = {key: plan[key] for key in ("schema", "revision", "label", "created_at", "sha256", "status")}
    with pytest.raises(ValidationError):
        app_module.SavedPlanMetaResponse.model_validate({**metadata, "status": "APPROVED"})


def test_internal_selection_mode_is_not_an_input_or_configuration_option(client):
    _, sid = _source(client)
    state = _state(client, sid)
    response = client.post(f"/api/snapshots/{sid}/plans", json={
        "label": "EXAMPLE", "assessment": state["assessment"], "requirements": {},
        "expected_selection_id": 0, "context": "absent",
    })
    assert response.status_code == 422
    snapshot = _snapshot()
    record = _plan(snapshot)
    with pytest.raises(deliverables.SavedPlanError):
        deliverables._validated_saved_plan(snapshot, record, context="request-selected")
