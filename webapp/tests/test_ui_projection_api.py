"""HTTP projection must preserve engine semantics and exact store custody."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import sys
from pathlib import Path

import pytest
from jsonschema.exceptions import ValidationError as SchemaValidationError
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.app import create_app  # noqa: E402
from backend import engine  # noqa: E402
from cisco_toolkit import ui_projection as owner  # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.delenv("ASSESSHUB_TOKEN", raising=False)
    monkeypatch.delenv("ASSESSHUB_ALLOWED_HOSTS", raising=False)
    app = create_app(db_path=str(tmp_path / "projection.db"), scope_dist_dir=None)
    with TestClient(app, base_url="http://localhost") as client:
        yield client


def seed(client, snapshot=None):
    store = client.app.state.store
    campaign = store.create_campaign("Projection contract")
    return store.add_snapshot(campaign["id"], "Fixture", snapshot or {}, {})["id"]


def url(sid, view="overview"):
    return f"/api/snapshots/{sid}/ui-projection/{view}"


def test_unknown_snapshot_and_selectors(client):
    assert client.get(url(991)).status_code == 404
    assert client.get(url(991, "invented")).status_code == 422
    assert client.get(url(2**80)).status_code == 422
    assert client.get(url(991, "device")).status_code == 422


def test_guard_runs_before_snapshot_or_projection(client, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("guard must precede source read")
    monkeypatch.setattr(client.app.state.store, "get_bound_snapshot", forbidden)
    for path in (url(991), url(991, "inventory") + "/lists?pointer=/devices/rows"):
        assert client.get(path, headers={"sec-fetch-site": "cross-site"}).status_code == 403
        assert client.get(path, headers={"host": "evil.example"}).status_code == 403


def test_routes_declare_response_models(client):
    paths = [r for r in client.app.routes if "ui-projection" in getattr(r, "path", "")]
    assert len(paths) == 2
    assert all(r.response_model is not None for r in paths)


def test_openapi_refs_resolve_and_owner_definitions_are_lossless(client):
    from backend.ui_projection_api import openapi_owner_definitions
    api = client.app.openapi()
    components = api["components"]["schemas"]
    expected = openapi_owner_definitions()
    assert expected
    for name, value in expected.items():
        assert components[name] == value
    def walk(value):
        if isinstance(value, dict):
            if "$ref" in value:
                ref = value["$ref"]
                assert ref.startswith("#/components/schemas/")
                assert ref.removeprefix("#/components/schemas/") in components
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    walk(api)


def test_adapter_uses_exact_owner_context():
    snapshot = {"devices": {"edge/a~b": {}}, "script_version": "3.23.0"}
    assert engine.ui_projection(snapshot) == owner.project(snapshot)
    assert engine.ui_projection(snapshot, " edge/a~b ") == owner.project_device(snapshot, " edge/a~b ")
    assert engine.ui_projection_schema() == owner.ui_projection_schema()


@pytest.fixture(scope="module")
def sample():
    return json.loads((Path(__file__).resolve().parents[1] / "sample_data/sample_fleet.snapshot.json").read_text())


def resolve(value, pointer):
    for part in pointer[1:].split("/"):
        value = value[part.replace("~1", "/").replace("~0", "~")]
    return value


@pytest.mark.parametrize("view", ["overview", "trust", "inventory", "findings", "device"])
def test_view_preserves_owner_data_and_exact_store_identity(client, sample, view):
    from backend.ui_projection_api import LIST_CATALOG
    sid = seed(client, sample)
    params = {"limit": 2}
    if view == "device":
        params["host"] = next(iter(sample["devices"]))
    response = client.get(url(sid, view), params=params)
    assert response.status_code == 200, response.text[:200]
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    blob, binding = client.app.state.store.get_snapshot_blob(sid)
    assert body["identity"] == {"snapshot_id": sid, "sha256": "sha256:" + hashlib.sha256(blob).hexdigest(),
                                "bytes": len(blob), "digest_form": "assesshub-store-blob"}
    assert body["identity"]["sha256"] == binding["sha256"]
    snapshot = json.loads(blob)
    document = owner.project_device(snapshot, params["host"]) if view == "device" else owner.project(snapshot)
    assert body["projection_schema"] == document["schema"]
    assert body["engine"] == document["engine"]
    assert body["limitations"] == (document["device"]["limitations"] if view == "device" else document["trust"]["limitations"])
    rebuilt = deepcopy(body["payload"])
    for pointer in LIST_CATALOG[view]:
        original = resolve(document[view], pointer)
        paged = resolve(rebuilt, pointer)
        assert paged["source_list"] == {k: v for k, v in original.items() if k != "items"}
        assert paged["page"] == {"offset": 0, "limit": 2, "returned": min(2, len(original["items"])),
                                  "total": len(original["items"]), "has_more": len(original["items"]) > 2,
                                  "items": original["items"][:2]}
        parent, _, last = pointer.rpartition("/")
        (resolve(rebuilt, parent) if parent else rebuilt)[last] = original
    assert rebuilt == document[view]


def test_all_pages_preserve_original_indices_and_pointers(client, sample):
    sid = seed(client, sample)
    original = owner.project(sample)["findings"]["rows"]
    assert len(original["items"]) > 4
    collected = []
    for offset in (0, 2, 4, len(original["items"]), len(original["items"]) + 1):
        response = client.get(url(sid, "findings") + "/lists", params={"pointer": "/rows", "offset": offset, "limit": 2})
        assert response.status_code == 200
        part = response.json()["list"]
        assert part["source_list"] == {k: v for k, v in original.items() if k != "items"}
        assert part["page"]["items"] == original["items"][offset:offset + 2]
        assert part["page"]["returned"] == len(part["page"]["items"])
        assert part["page"]["total"] == len(original["items"])
        assert part["page"]["has_more"] == (offset + len(part["page"]["items"]) < len(original["items"]))
        collected.extend(part["page"]["items"])
    assert collected == original["items"][:6]


@pytest.mark.parametrize("state", owner.STATES)
def test_all_six_states_and_withheld_nonempty_lists_survive(client, sample, monkeypatch, state):
    sid = seed(client)
    document = owner.project(sample)
    rows = document["findings"]["rows"]
    rows["state"] = state
    if state == "published":
        rows.pop("reason", None)
    else:
        rows["reason"] = "Explicit synthetic owner state"
    Draft202012Validator(owner.ui_projection_schema()).validate(document)
    monkeypatch.setattr(engine, "ui_projection", lambda *args: document)
    response = client.get(url(sid, "findings") + "/lists", params={"pointer": "/rows", "limit": 1})
    assert response.status_code == 200, response.text[:200]
    part = response.json()["list"]
    assert part["source_list"]["state"] == state
    assert part["source_list"] == {k: v for k, v in rows.items() if k != "items"}
    assert part["page"]["items"] == rows["items"][:1]


def test_source_document_is_validated_before_paging_even_outside_selected_view(client, sample, monkeypatch):
    sid = seed(client)
    document = owner.project(sample)
    del document["findings"]["rows"]["items"][-1]["severity"]["basis"]
    monkeypatch.setattr(engine, "ui_projection", lambda *args: document)
    with pytest.raises(SchemaValidationError, match="is not valid under any of the given schemas"):
        client.get(url(sid, "overview"), params={"limit": 1})
    with pytest.raises(SchemaValidationError, match="is not valid under any of the given schemas"):
        client.get(url(sid, "findings") + "/lists", params={"pointer": "/rows", "offset": 0, "limit": 1})


@pytest.mark.parametrize("params", [
    {"pointer": "/rows", "offset": -1}, {"pointer": "/rows", "offset": 2**53},
    {"pointer": "/rows", "offset": "1.5"}, {"pointer": "/rows", "limit": 0},
    {"pointer": "/rows", "limit": 201}, {"pointer": "/rows", "limit": "many"},
    {"pointer": "rows"}, {"pointer": "/rows/items/0"}, {"pointer": "/~2rows"},
])
def test_invalid_paging_rejected_before_source_read(client, monkeypatch, params):
    monkeypatch.setattr(client.app.state.store, "get_bound_snapshot", lambda *_: pytest.fail("invalid selector read source"))
    assert client.get(url(1, "findings") + "/lists", params=params).status_code == 422


def test_unknown_host_is_exact_owner_withheld_page_and_query_is_unchanged(client):
    from backend.ui_projection_api import LIST_CATALOG
    sid = seed(client, {"devices": {"known": {}}})
    host = " missing/edge~a "
    response = client.get(url(sid, "device"), params={"host": host})
    assert response.status_code == 200
    body = response.json()
    source, _binding = client.app.state.store.get_bound_snapshot(sid)
    expected = owner.project_device(source, host)
    actual = body["payload"]
    for pointer in LIST_CATALOG["device"]:
        wrapper = resolve(actual, pointer)
        parent, _, last = pointer.rpartition("/")
        (resolve(actual, parent) if parent else actual)[last] = {**wrapper["source_list"], "items": wrapper["page"]["items"]}
    assert actual == expected["device"]
    assert body["engine"] == expected["engine"]
    assert actual["host"] == host
    assert client.get(url(sid), params={"host": host}).status_code == 422


def test_response_model_rejects_malformed_transport_without_coercion(client):
    from backend.ui_projection_api import UiProjectionViewResponse
    from pydantic import ValidationError
    body = client.get(url(seed(client))).json()
    original = deepcopy(body)
    result = UiProjectionViewResponse.model_validate(body)
    assert result.model_dump() == original
    for path, value in [("bytes", "10"), ("bytes", True), ("bytes", float("nan")), ("sha256", "not-a-digest")]:
        broken = deepcopy(body)
        broken["identity"][path] = value
        with pytest.raises(ValidationError):
            UiProjectionViewResponse.model_validate(broken)
    result.root["engine"]["unexpected"] = "must not be silently removed"
    with pytest.raises(ValidationError):
        UiProjectionViewResponse.model_validate(result)


def test_openapi_owner_equivalence_is_independent_of_api_schema_helper(client):
    api = client.app.openapi()
    def rewrite(node):
        if isinstance(node, dict):
            result = {k: rewrite(v) for k, v in node.items()}
            if "$ref" in result:
                result["$ref"] = result["$ref"].replace("#/$defs/", "#/components/schemas/UiProjection1_")
            return result
        if isinstance(node, list):
            return [rewrite(v) for v in node]
        return node
    for name, schema in owner.ui_projection_schema()["$defs"].items():
        assert api["components"]["schemas"]["UiProjection1_" + name] == rewrite(schema)
    for model in ("UiProjectionViewResponse", "UiProjectionListResponse"):
        assert api["components"]["schemas"][model]["x-engine-schema-id"] == owner.SCHEMA_ID
    for path in ("/api/snapshots/{snapshot_id}/ui-projection/{view}",
                 "/api/snapshots/{snapshot_id}/ui-projection/{view}/lists"):
        assert "$ref" in api["paths"][path]["get"]["responses"]["200"]["content"]["application/json"]["schema"]


@pytest.mark.parametrize("change", ["returned", "has_more", "total", "pointer"])
def test_response_model_rejects_forged_page_metadata(client, change):
    from backend.ui_projection_api import UiProjectionViewResponse
    from pydantic import ValidationError
    body = client.get(url(seed(client))).json()
    wrapper = body["payload"]["axes"]
    if change == "pointer":
        wrapper["pointer"] = "/wrong"
    elif change == "has_more":
        wrapper["page"][change] = not wrapper["page"][change]
    else:
        wrapper["page"][change] += 1
    with pytest.raises(ValidationError):
        UiProjectionViewResponse.model_validate(body)


def test_http_boundary_really_validates_response(client, monkeypatch):
    from backend import ui_projection_api
    from fastapi.exceptions import ResponseValidationError
    sid = seed(client)
    real = ui_projection_api._page_view
    def broken(*args):
        result = real(*args)
        result["posture_statement"]["state"] = "invented"
        return result
    monkeypatch.setattr(ui_projection_api, "_page_view", broken)
    with pytest.raises(ResponseValidationError):
        client.get(url(sid))


def test_projection_reads_one_bound_source_and_no_legacy_backfill(client, monkeypatch):
    sid = seed(client)
    store = client.app.state.store
    calls = []
    real = store.get_bound_snapshot
    def bound(snapshot_id):
        calls.append(snapshot_id)
        return real(snapshot_id)
    monkeypatch.setattr(store, "get_bound_snapshot", bound)
    for name in ("get_snapshot", "get_section", "get_snapshot_meta"):
        if hasattr(store, name):
            monkeypatch.setattr(store, name, lambda *args: pytest.fail("projection used a legacy backfill seam"))
    assert client.get(url(sid)).status_code == 200
    assert calls == [sid]


def test_openapi_can_be_reversed_to_exact_fresh_owner_schema(client):
    api = client.app.openapi()
    def unhoist(node):
        if isinstance(node, dict):
            return {key: (value.replace("#/components/schemas/UiProjection1_", "#/$defs/")
                          if key == "$ref" else unhoist(value)) for key, value in node.items()}
        if isinstance(node, list):
            return [unhoist(item) for item in node]
        return node
    owner_defs = owner.ui_projection_schema()["$defs"]
    assert {name: unhoist(api["components"]["schemas"]["UiProjection1_" + name]) for name in owner_defs} == owner_defs
    # Every derived source_list differs from the owner only by removal of items.
    for name, source in api["components"]["schemas"].items():
        if name.startswith("UiProjection1_Source_"):
            original = deepcopy(owner_defs[name.removeprefix("UiProjection1_Source_")])
            for branch in original["oneOf"]:
                branch["properties"].pop("items")
                branch["required"].remove("items")
            assert unhoist(source) == original


def test_openapi_export_is_deterministic_offline_and_check_never_writes(tmp_path, monkeypatch):
    from backend import export_ui_projection_openapi as exporter
    forbidden = tmp_path / "do-not-open" / "user.db"
    monkeypatch.setenv("ASSESSHUB_DB", str(forbidden))
    target = tmp_path / "generated" / "openapi.json"
    assert exporter.main(["--output", str(target), "--check"]) == 1
    assert not target.parent.exists()
    assert exporter.main(["--output", str(target)]) == 0
    original = target.read_bytes()
    assert exporter.main(["--output", str(target)]) == 0
    assert target.read_bytes() == original
    assert exporter.main(["--output", str(target), "--check"]) == 0
    target.write_bytes(b"stale")
    assert exporter.main(["--output", str(target), "--check"]) == 1
    assert target.read_bytes() == b"stale"
    assert not forbidden.parent.exists()


@pytest.mark.parametrize("selection", ["other_view", "off_page", "selected_page"])
def test_nonfinite_producer_score_is_rejected_before_any_selection(client, sample, monkeypatch, selection):
    sid = seed(client, sample)
    document = owner.project(sample)
    final_index = len(document["inventory"]["devices"]["rows"]["items"]) - 1
    document["inventory"]["devices"]["rows"]["items"][final_index]["health_score"]["value"] = float("nan")
    # Python's JSON Schema number checks accept NaN. HTTP must still refuse the complete
    # invalid JSON source, including a row not visible on this requested view/page.
    Draft202012Validator(owner.ui_projection_schema()).validate(document)
    monkeypatch.setattr(engine, "ui_projection", lambda *args: document)
    path, params = (url(sid), {"limit": 1}) if selection == "other_view" else (
        url(sid, "inventory") + "/lists",
        {"pointer": "/devices/rows", "limit": 1, "offset": final_index if selection == "selected_page" else 0},
    )
    transport = TestClient(client.app, base_url="http://localhost", client=("127.0.0.1", 50000), raise_server_exceptions=False)
    try:
        response = transport.get(path, params=params)
        assert response.status_code == 500
        assert response.content == b"Internal Server Error"
    finally:
        transport.close()


def test_http_response_boundary_rejects_forged_nan_before_serializing_it_to_null(client, sample, monkeypatch):
    from backend import ui_projection_api
    sid = seed(client, sample)
    original = ui_projection_api._page_view
    def forged(*args):
        payload = original(*args)
        payload["facts"]["avg_health"]["fact"]["value"] = float("nan")
        return payload
    monkeypatch.setattr(ui_projection_api, "_page_view", forged)
    transport = TestClient(client.app, base_url="http://localhost", client=("127.0.0.1", 50000), raise_server_exceptions=False)
    try:
        response = transport.get(url(sid))
        assert response.status_code == 500
        assert response.content == b"Internal Server Error"
    finally:
        transport.close()


@pytest.mark.parametrize("boundary", ["producer", "response"])
@pytest.mark.parametrize("invalid", ["infinity", "negative_infinity", "tuple", "set", "decimal", "non_string_key", "cycle"])
def test_json_native_boundary_rejects_invalid_python_values(client, sample, monkeypatch, boundary, invalid):
    from backend import ui_projection_api
    from decimal import Decimal
    sid = seed(client, sample)
    def corrupt(payload):
        fact = payload["facts"]["avg_health"]["fact"]
        if invalid == "non_string_key":
            fact[1] = "not a JSON key"
        elif invalid == "cycle":
            value = []
            value.append(value)
            fact["value"] = value
        else:
            fact["value"] = {"infinity": float("inf"), "negative_infinity": float("-inf"),
                             "tuple": (50,), "set": {50}, "decimal": Decimal("50.25")}[invalid]
    if boundary == "producer":
        document = owner.project(sample)
        corrupt(document["overview"])
        monkeypatch.setattr(engine, "ui_projection", lambda *args: document)
        # The malformed overview must also block a different requested view.
        path = url(sid, "trust")
    else:
        original = ui_projection_api._page_view
        def forged(*args):
            payload = original(*args)
            corrupt(payload)
            return payload
        monkeypatch.setattr(ui_projection_api, "_page_view", forged)
        path = url(sid)
    transport = TestClient(client.app, base_url="http://localhost", client=("127.0.0.1", 50000), raise_server_exceptions=False)
    try:
        response = transport.get(path)
        assert response.status_code == 500
        assert response.content == b"Internal Server Error"
    finally:
        transport.close()


def test_json_native_check_preserves_native_values_and_shared_aliases():
    from backend.ui_projection_api import _require_json_native
    shared = [None, False, True, 0, 2**100, -0.0, 1.25, "unchanged"]
    value = {"second": shared, "first": shared}
    before = json.dumps(value, allow_nan=False)
    _require_json_native(value)
    assert json.dumps(value, allow_nan=False) == before
    assert value["second"] is value["first"] is shared
    assert list(value) == ["second", "first"]
    assert type(shared[3]) is int and type(shared[5]) is float
