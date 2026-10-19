"""Saved-plan HTTP integration: source custody, immutable revisions and export identity.

Run on the existing GitHub-hosted application/source gates. No workstation execution.
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path
import threading
import xml.etree.ElementTree as ET
import zipfile

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import app as app_module  # noqa: E402
from backend import deliverables  # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.delenv("ASSESSHUB_TOKEN", raising=False)
    app = app_module.create_app(db_path=str(tmp_path / "plans.db"))
    with TestClient(app, base_url="http://localhost") as http:
        yield http


def _source(client, script_version="V3.23.0"):
    campaign = client.post("/api/campaigns", json={"name": "Saved-plan integration"})
    assert campaign.status_code == 201, campaign.text
    cid = campaign.json()["id"]
    raw = json.dumps({
        "script_version": script_version,
        "devices": {"synthetic-switch": {"model": "C9300", "sw_version": "17.9"}},
        "interfaces": {},
    }).encode()
    response = client.post(f"/api/campaigns/{cid}/snapshots", data={"label": "Synthetic source"},
                           files={"file": ("source.json", raw, "application/json")})
    assert response.status_code == 201, response.text
    return cid, response.json()["id"]


def _state(client, sid):
    response = client.get(f"/api/snapshots/{sid}/plans")
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    return response.json()


def _save(client, sid, state, model="aci"):
    response = client.post(f"/api/snapshots/{sid}/plans", json={
        "label": f"Saved {model} plan",
        "requirements": {"fabric_operating_model": model, "convergence_budget_ms": 0},
        "assessment": state["assessment"], "expected_selection_id": state["selection_id"],
    })
    assert response.status_code == 201, response.text
    return response.json()


def _params(plan):
    return {"plan_sha256": plan["sha256"], "selection_id": plan["selection_id"]}


def _document_text(response):
    assert response.status_code == 200, response.text[:500]
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        tree = ET.fromstring(archive.read("word/document.xml"))
        texts = list(tree.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"))
        return " ".join(node.text or "" for node in texts)


def test_saved_plan_reopens_with_matching_mop_nrfu_and_unchanged_raw_source(client):
    _cid, sid = _source(client)
    before = client.get(f"/api/snapshots/{sid}/raw")
    assert before.status_code == 200
    initial = _state(client, sid)
    assert initial["selection_id"] == 0 and initial["selected_revision"] is None
    assert initial["revisions"] == []
    plan = _save(client, sid, initial)
    assert plan["status"] == "UNAPPROVED_DRAFT"
    assert plan["projection"]["requirements"]["convergence_budget_ms"] == 0
    reopened = client.get(f"/api/snapshots/{sid}/plans/{plan['revision']}", params=_params(plan))
    assert reopened.status_code == 200, reopened.text
    assert reopened.json() == plan
    assert plan["assessment"] == initial["assessment"]
    for kind in ("mop", "nrfu"):
        exported = client.get(
            f"/api/snapshots/{sid}/plans/{plan['revision']}/deliverable/{kind}", params=_params(plan),
        )
        text = _document_text(exported)
        assert "UNAPPROVED DRAFT" in text
        assert plan["sha256"] in text and plan["assessment"]["sha256"] in text
        assert f"Revision {plan['revision']}" in text
        assert f"Selection {plan['selection_id']}" in text
        assert exported.headers["x-atlas-assessment-sha256"] == plan["assessment"]["sha256"]
        assert exported.headers["x-atlas-plan-sha256"] == plan["sha256"]
        assert exported.headers["x-atlas-plan-revision"] == str(plan["revision"])
        assert exported.headers["x-atlas-plan-selection"] == str(plan["selection_id"])
        assert exported.headers["x-atlas-plan-status"] == "UNAPPROVED_DRAFT"
    after = client.get(f"/api/snapshots/{sid}/raw")
    assert after.content == before.content
    assert after.headers["x-snapshot-sha256"] == before.headers["x-snapshot-sha256"]
    assert _state(client, sid)["selected_revision"] == plan["revision"]


def test_saved_plan_stale_save_selection_aba_and_cross_snapshot_refuse(client):
    _cid, sid = _source(client)
    initial = _state(client, sid)
    first = _save(client, sid, initial)
    stale = client.post(f"/api/snapshots/{sid}/plans", json={
        "label": "Stale save", "requirements": {}, "assessment": initial["assessment"],
        "expected_selection_id": initial["selection_id"],
    })
    assert stale.status_code == 409
    second = _save(client, sid, _state(client, sid), "nxos-evpn")
    assert second["revision"] != first["revision"]
    assert client.get(f"/api/snapshots/{sid}/plans/{first['revision']}", params=_params(first)).status_code == 409
    selected = client.post(f"/api/snapshots/{sid}/plans/{first['revision']}/select", json={
        "plan_sha256": first["sha256"], "expected_selection_id": second["selection_id"],
    })
    assert selected.status_code == 200, selected.text
    back_to_first = selected.json()
    assert back_to_first["sha256"] == first["sha256"]
    assert back_to_first["selection_id"] != first["selection_id"]
    assert client.get(f"/api/snapshots/{sid}/plans/{first['revision']}", params=_params(first)).status_code == 409
    assert client.get(f"/api/snapshots/{sid}/plans/{first['revision']}", params=_params(back_to_first)).status_code == 200
    _other_cid, other_sid = _source(client)
    cross = client.get(f"/api/snapshots/{other_sid}/plans/{first['revision']}", params=_params(back_to_first))
    assert cross.status_code in (404, 409)
    assert len(_state(client, sid)["revisions"]) == 2


def test_saved_plans_refuse_caller_sections_malformed_requirements_and_duplicate_keys(client):
    _cid, sid = _source(client)
    initial = _state(client, sid)
    body = {"label": "Invalid", "requirements": {}, "assessment": initial["assessment"],
            "expected_selection_id": 0}
    assert client.post(f"/api/snapshots/{sid}/plans", json={**body, "projection": {}}).status_code == 422
    for requirements in ({"invented_option": "value"}, {"convergence_budget_ms": True},
                         {"vlan_zones": ["not a map"]}):
        response = client.post(f"/api/snapshots/{sid}/plans", json={**body, "requirements": requirements})
        assert response.status_code == 400, response.text
    response = client.post(f"/api/snapshots/{sid}/plans", json={**body, "expected_selection_id": False})
    assert response.status_code == 422
    duplicate = json.dumps(body).replace('"expected_selection_id": 0',
                                        '"expected_selection_id": 0, "expected_selection_id": 1')
    assert client.post(f"/api/snapshots/{sid}/plans", content=duplicate,
                       headers={"content-type": "application/json"}).status_code == 400
    assert not _state(client, sid)["revisions"]
    assert client.get("/api/snapshots/-1/plans").status_code == 422


@pytest.mark.parametrize("owner", [None, 3, ""])
def test_missing_or_invalid_script_owner_refuses_before_any_revision(client, owner):
    _cid, sid = _source(client, script_version=owner)
    initial = _state(client, sid)
    response = client.post(f"/api/snapshots/{sid}/plans", json={
        "label": "Unsupported source", "requirements": {}, "assessment": initial["assessment"],
        "expected_selection_id": 0,
    })
    assert response.status_code == 400
    assert _state(client, sid)["revisions"] == []
    assert client.get(f"/api/snapshots/{sid}/raw").status_code == 200


def test_deep_json_refuses_without_decoding_or_saving_a_plan(client):
    _cid, sid = _source(client)
    wire = ('{"requirements":' + '[' * 2000 + '0' + ']' * 2000 + '}').encode()
    response = client.post(f"/api/snapshots/{sid}/plans", content=wire,
                           headers={"content-type": "application/json"})
    assert response.status_code == 400
    assert _state(client, sid)["revisions"] == []


@pytest.mark.parametrize("content_type", ["application/json", "application/vnd.atlas+json", None])
@pytest.mark.parametrize("suffix", ["", "/1/select"])
def test_plan_depth_guard_precedes_decoding_for_every_json_transport(client, monkeypatch, content_type, suffix):
    _cid, sid = _source(client)
    wire = ('{"requirements":' + '[' * 2000 + '0' + ']' * 2000 + '}').encode()

    def forbidden_decode(*_args, **_kwargs):
        raise AssertionError("Excessive plan nesting reached a JSON decoder")

    with monkeypatch.context() as patch:
        patch.setattr(app_module.json, "loads", forbidden_decode)
        response = client.post(f"/api/snapshots/{sid}/plans{suffix}", content=wire,
                               headers={} if content_type is None else {"content-type": content_type})
    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid JSON request body"}
    assert _state(client, sid)["revisions"] == []


@pytest.mark.parametrize("encoding", ["utf-8", "utf-16", "utf-32"])
def test_plan_depth_guard_ignores_escaped_quotes_and_brackets_in_real_requirements(client, encoding):
    _cid, sid = _source(client)
    state = _state(client, sid)
    text = 'Literal [ { bracket and "quoted" text with \\ slash } ] ' * 100
    wire = json.dumps({
        "label": "Quoted requirements", "requirements": {"constraints": text},
        "assessment": state["assessment"], "expected_selection_id": 0,
    }).encode(encoding)
    response = client.post(f"/api/snapshots/{sid}/plans", content=wire,
                           headers={"content-type": "application/json"})
    assert response.status_code == 201, response.text
    assert response.json()["projection"]["requirements"]["constraints"] == [text.strip()]
    assert len(_state(client, sid)["revisions"]) == 1


def test_saved_plan_routes_inherit_origin_and_auth_guards(client):
    _cid, sid = _source(client)
    state = _state(client, sid)
    path = f"/api/snapshots/{sid}/plans"
    assert client.get(path, headers={"sec-fetch-site": "cross-site"}).status_code == 403
    response = client.post(path, json={
        "label": "Forbidden", "requirements": {}, "assessment": state["assessment"],
        "expected_selection_id": 0,
    }, headers={"origin": "https://foreign.invalid", "sec-fetch-site": "cross-site"})
    assert response.status_code == 403
    assert not _state(client, sid)["revisions"]


def test_plan_bound_sources_cannot_be_deleted(client):
    cid, sid = _source(client)
    _save(client, sid, _state(client, sid))
    assert client.delete(f"/api/snapshots/{sid}").status_code == 409
    assert client.delete(f"/api/campaigns/{cid}").status_code == 409
    assert client.get(f"/api/snapshots/{sid}/raw").status_code == 200


def test_plan_generation_capacity_is_released_and_original_gates_are_retained(client, monkeypatch):
    _cid, sid = _source(client)
    plan = _save(client, sid, _state(client, sid))
    semaphore = threading.BoundedSemaphore(1)
    client.app.state.generation_semaphore = semaphore
    assert semaphore.acquire(blocking=False)
    try:
        response = client.get(f"/api/snapshots/{sid}/plans/{plan['revision']}/deliverable/mop",
                              params=_params(plan))
        assert response.status_code == 503 and response.headers["retry-after"] == "5"
    finally:
        semaphore.release()
    observed = []
    original = deliverables.generate_saved_plan
    def capture(*args, **kwargs):
        observed.append(kwargs["document_gate"])
        return original(*args, **kwargs)
    monkeypatch.setattr(deliverables, "generate_saved_plan", capture)
    gate = {"generator": "mop", "status": "pending", "verified": False,
            "missing": ["lld_approved"], "revoked": [], "summary": "Review pending"}
    monkeypatch.setattr(deliverables, "gate_disclosure", lambda *_args, **_kwargs: gate)
    response = client.get(f"/api/snapshots/{sid}/plans/{plan['revision']}/deliverable/mop",
                          params=_params(plan))
    assert response.status_code == 200, response.text[:500]
    assert observed == [gate]
    assert response.headers["x-gate-status"] == "pending:lld_approved"
    assert "UNAPPROVED DRAFT" in _document_text(response)
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        core = ET.fromstring(archive.read("docProps/core.xml"))
        keywords = core.find("{http://schemas.openxmlformats.org/package/2006/metadata/core-properties}keywords")
        assert keywords is not None
        assert keywords.text == "atlas_gate_status=pending;missing=lld_approved;revoked="
    assert semaphore.acquire(blocking=False)
    semaphore.release()


def test_export_selection_race_refuses_and_cleans_generated_file(client, monkeypatch):
    _cid, sid = _source(client)
    first = _save(client, sid, _state(client, sid))
    second = _save(client, sid, _state(client, sid), "nxos-evpn")
    original = deliverables.generate_saved_plan
    generated = []
    def change_selection(*args, **kwargs):
        path = original(*args, **kwargs)
        generated.append(path)
        selected = client.app.state.store.select_plan_revision(
            sid, first["revision"], first["sha256"], second["selection_id"],
            expected_binding=first["assessment"],
            admit=lambda candidate: app_module._prepare_existing_saved_plan(
                client.app.state.store.get_bound_snapshot(sid)[0], candidate),
            finalize=app_module._finish_saved_plan,
        )
        assert selected is not None
        return path
    monkeypatch.setattr(deliverables, "generate_saved_plan", change_selection)
    response = client.get(f"/api/snapshots/{sid}/plans/{second['revision']}/deliverable/mop",
                          params=_params(second))
    assert response.status_code == 409
    assert generated and all(not Path(path).exists() for path in generated)


def test_actual_openapi_and_offline_export_share_fresh_engine_requirements_contract(client, monkeypatch):
    from cisco_toolkit import design_advisor
    from backend import ui_projection_api
    from backend.export_ui_projection_openapi import export_schema

    owner_calls = []
    original_definitions = ui_projection_api.openapi_owner_definitions

    def counted_definitions():
        owner_calls.append(True)
        return original_definitions()

    monkeypatch.setattr(ui_projection_api, "openapi_owner_definitions", counted_definitions)

    expected = design_advisor.requirements_contract()
    assert expected["scope"] == "saved_plan_admission"
    assert client.app.openapi_schema is None
    schema = client.app.openapi()
    native_schemas = schema["components"]["schemas"]
    native_bytes = json.dumps(native_schemas, sort_keys=True)
    assert schema["x-atlas-requirements-contract"] == expected
    assert export_schema()["x-atlas-requirements-contract"] == expected
    assert len(owner_calls) == 2  # The runtime app and the independent offline-export app.

    # Neither an OpenAPI consumer nor a cached schema may mutate the engine owner.
    schema["x-atlas-requirements-contract"]["list_fields"].append("consumer_only")
    schema["x-atlas-requirements-contract"]["availability_tiers"].append("consumer_only")
    schema["x-atlas-requirements-contract"]["vlan_id"]["maximum"] = -1
    assert design_advisor.requirements_contract() == expected
    assert client.app.openapi()["x-atlas-requirements-contract"] == expected
    assert client.app.openapi() is schema
    assert schema["components"]["schemas"] is native_schemas
    assert json.dumps(native_schemas, sort_keys=True) == native_bytes
    assert len(owner_calls) == 2  # Fresh metadata must not rebuild the cached native schema.

    # A new owner domain must reach runtime/export schemas, including after cache creation.
    monkeypatch.setattr(design_advisor, "REQUIREMENTS_AVAILABILITY_TIERS", ("platinum", "standard"))
    monkeypatch.setattr(design_advisor, "REQUIREMENTS_VLAN_MIN", 7)
    monkeypatch.setattr(design_advisor, "REQUIREMENTS_VLAN_MAX", 12)
    changed = design_advisor.requirements_contract()
    assert changed != expected
    assert client.app.openapi()["x-atlas-requirements-contract"] == changed
    assert export_schema()["x-atlas-requirements-contract"] == changed
    assert schema["components"]["schemas"] is native_schemas
    assert json.dumps(native_schemas, sort_keys=True) == native_bytes
    assert len(owner_calls) == 3  # Only the second offline app needs a new native schema.


def test_protocol_sidecar_dispatch_uses_one_live_registry_for_both_download_routes(client, monkeypatch):
    from cisco_toolkit import docmeta

    _cid, sid = _source(client)
    plan = _save(client, sid, _state(client, sid))
    calls = []
    resolve = deliverables.resolve_writer

    def capture_writer(spec):
        writer = resolve(spec)

        def capture(*args, **kwargs):
            assert "protocol_assurance_bundle" not in kwargs
            calls.append(spec.key)
            return writer(*args, **kwargs)

        return capture

    def unexpected_sidecar(*_args, **_kwargs):
        raise AssertionError("download selector ignored the registry owner")

    # This controlled owner-policy mutation falsifies each of the former four literal sets.
    # The separate registry/interface contract keeps the production denominator non-vacuous.
    monkeypatch.setattr(docmeta, "PROTOCOL_ASSURANCE_DOCUMENT_KINDS", frozenset())
    monkeypatch.setattr(app_module.protocol_portfolio, "build_protocol_single_snapshot_bundle", unexpected_sidecar)
    monkeypatch.setattr(deliverables, "resolve_writer", capture_writer)
    baseline = client.get(f"/api/snapshots/{sid}/deliverable/mop")
    selected = client.get(f"/api/snapshots/{sid}/plans/{plan['revision']}/deliverable/mop", params=_params(plan))
    assert baseline.status_code == 200, baseline.text[:500]
    assert selected.status_code == 200, selected.text[:500]
    assert calls == ["mop", "mop"]
