"""HTTP projection must preserve engine semantics and exact store custody."""
from __future__ import annotations

from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import sys
from threading import Event
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
    with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50000)) as client:
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
    monkeypatch.setattr(client.app.state.store, "get_snapshot_blob", forbidden)
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
    monkeypatch.setattr(client.app.state.store, "get_snapshot_blob", lambda *_: pytest.fail("invalid selector read source"))
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
    from cisco_toolkit.protocol_assurance import bound_snapshot_source
    sid = seed(client)
    store = client.app.state.store
    calls = []
    parsed = []
    produced = []
    real = store.get_snapshot_blob
    bind = engine.bind_ui_projection_snapshot
    project = engine.ui_projection
    def bound(snapshot_id):
        result = real(snapshot_id)
        calls.append(result)
        return result
    def bound_bytes(raw):
        parsed.append(raw)
        assert raw is calls[-1][0]
        return bind(raw)
    def projection(snapshot, host=None):
        produced.append(bound_snapshot_source(snapshot))
        return project(snapshot, host)
    monkeypatch.setattr(store, "get_snapshot_blob", bound)
    monkeypatch.setattr(engine, "bind_ui_projection_snapshot", bound_bytes)
    monkeypatch.setattr(engine, "ui_projection", projection)
    for name in ("get_bound_snapshot", "get_snapshot", "get_section", "get_snapshot_meta"):
        if hasattr(store, name):
            monkeypatch.setattr(store, name, lambda *args: pytest.fail("projection used a legacy backfill seam"))
    assert client.get(url(sid)).status_code == 200
    assert client.get(url(sid, "trust")).status_code == 200
    assert len(calls) == 2 and len(parsed) == len(produced) == 1
    assert produced[0]["source_bound"] is True
    assert produced[0]["sha256"] == "sha256:" + hashlib.sha256(parsed[0]).hexdigest() == calls[0][1]["sha256"]
    assert produced[0]["bytes"] == len(parsed[0])


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


def test_cache_computes_and_validates_once_across_views_pages_and_exact_hosts(client, monkeypatch):
    from backend import ui_projection_api as api
    sid = seed(client, {"devices": {"edge": {}, " edge ": {}}})
    projected, bound, validated = [], [], []
    project, bind = engine.ui_projection, engine.bind_ui_projection_snapshot
    def projection(snapshot, host=None):
        projected.append(host)
        return project(snapshot, host)
    def binding(raw):
        bound.append(raw)
        return bind(raw)
    class Validator:
        def __init__(self, source, name):
            self.source, self.name = source, name
        def validate(self, value):
            validated.append(self.name)
            self.source.validate(value)
    monkeypatch.setattr(engine, "ui_projection", projection)
    monkeypatch.setattr(engine, "bind_ui_projection_snapshot", binding)
    monkeypatch.setattr(api, "_DOCUMENT_VALIDATOR", Validator(api._DOCUMENT_VALIDATOR, "document"))
    monkeypatch.setattr(api, "_DEVICE_VALIDATOR", Validator(api._DEVICE_VALIDATOR, "device"))
    for view in ("overview", "trust", "inventory", "findings", "overview"):
        assert client.get(url(sid, view), params={"limit": 1}).status_code == 200
        for pointer in api.LIST_CATALOG[view]:
            for offset in (0, 1, 100):
                assert client.get(url(sid, view) + "/lists", params={
                    "pointer": pointer, "offset": offset, "limit": 1,
                }).status_code == 200
    for host in ("edge", " edge ", "edge", "", " edge "):
        response = client.get(url(sid, "device"), params={"host": host, "limit": 1})
        assert response.status_code == 200
        assert response.json()["payload"]["host"] == host
        for pointer in api.LIST_CATALOG["device"]:
            assert client.get(url(sid, "device") + "/lists", params={
                "host": host, "pointer": pointer, "offset": 1, "limit": 1,
            }).status_code == 200
    assert projected == [None, "edge", " edge ", ""]
    assert len(bound) == 1
    assert validated == ["document", "device", "device", "device"]


def test_cache_single_flight_on_concurrent_views(client, monkeypatch):
    sid = seed(client)
    project = engine.ui_projection
    entered, release = Event(), Event()
    calls = []
    def slow(snapshot, host=None):
        calls.append(host)
        entered.set()
        assert release.wait(10)
        return project(snapshot, host)
    monkeypatch.setattr(engine, "ui_projection", slow)
    with ThreadPoolExecutor(max_workers=4) as pool:
        first = pool.submit(client.get, url(sid))
        assert entered.wait(10)
        rest = [pool.submit(client.get, url(sid, view)) for view in ("trust", "inventory", "findings")]
        release.set()
        assert all(result.result().status_code == 200 for result in [first, *rest])
    assert calls == [None]


def test_cached_core_and_device_http_reads_finish_while_another_device_build_is_held(client, monkeypatch):
    sid = seed(client, {"devices": {"cached": {}, "cold": {}}})
    assert client.get(url(sid)).status_code == 200
    assert client.get(url(sid, "device"), params={"host": "cached"}).status_code == 200
    project = engine.ui_projection
    entered, release = Event(), Event()
    calls = []
    def held(snapshot, host=None):
        calls.append(host)
        assert host == "cold", "already-cached documents must not be recomputed"
        entered.set()
        assert release.wait(30), "test must release the held producer"
        return project(snapshot, host)
    monkeypatch.setattr(engine, "ui_projection", held)
    with ThreadPoolExecutor(max_workers=3) as pool:
        cold = pool.submit(client.get, url(sid, "device"), params={"host": "cold"})
        try:
            assert entered.wait(10)
            core = pool.submit(client.get, url(sid, "inventory"))
            cached_device = pool.submit(client.get, url(sid, "device"), params={"host": "cached"})
            # These generous deadlines detect dependence on the held producer, not
            # hardware speed. Both responses must finish BEFORE its release event.
            assert core.result(timeout=10).status_code == 200
            assert cached_device.result(timeout=10).status_code == 200
            assert not cold.done()
            assert not release.is_set()
        finally:
            release.set()
        assert cold.result(timeout=10).status_code == 200
    assert calls == ["cold"]


def test_cache_has_no_small_lru_and_versions_are_namespaced(client, monkeypatch):
    from backend import ui_projection_api as api
    calls = []
    project = engine.ui_projection
    def counted(snapshot, host=None):
        calls.append(snapshot.get("generated_at"))
        return project(snapshot, host)
    monkeypatch.setattr(engine, "ui_projection", counted)
    snapshots = [seed(client, {"generated_at": str(index)}) for index in range(12)]
    for sid in [*snapshots, *reversed(snapshots)]:
        assert client.get(url(sid)).status_code == 200
    assert len(calls) == len(snapshots)
    monkeypatch.setattr(api, "_PROJECTION_VERSION", (*api._PROJECTION_VERSION, "changed-projection"))
    assert client.get(url(snapshots[0])).status_code == 200
    assert len(calls) == len(snapshots) + 1


def test_cache_reuses_equal_bytes_but_identity_and_store_lifetime_are_separate(client, tmp_path, monkeypatch):
    calls = []
    project = engine.ui_projection
    def counted(snapshot, host=None):
        calls.append(host)
        return project(snapshot, host)
    monkeypatch.setattr(engine, "ui_projection", counted)
    first, duplicate, different = seed(client), seed(client), seed(client, {"devices": {"other": {}}})
    bodies = [client.get(url(sid)).json() for sid in (first, duplicate, different)]
    assert [body["identity"]["snapshot_id"] for body in bodies] == [first, duplicate, different]
    assert bodies[0]["identity"]["sha256"] == bodies[1]["identity"]["sha256"]
    assert bodies[1]["identity"]["sha256"] != bodies[2]["identity"]["sha256"]
    assert len(calls) == 2
    app = create_app(db_path=str(tmp_path / "other.db"), scope_dist_dir=None)
    with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50001)) as other:
        assert other.get(url(seed(other))).status_code == 200
    assert len(calls) == 3


@pytest.mark.parametrize("failure", ["deleted", "bytes_changed", "authority_changed"])
def test_warm_cache_still_checks_live_store_authority(client, failure):
    sid = seed(client)
    assert client.get(url(sid)).status_code == 200
    store = client.app.state.store
    if failure == "deleted":
        assert store.delete_snapshot(sid)
        assert client.get(url(sid)).status_code == 404
        return
    with store._lock:
        if failure == "bytes_changed":
            store._conn.execute("UPDATE snapshots SET snapshot_json = ? WHERE id = ?", ('{"changed":true}', sid))
        else:
            store._conn.execute("DELETE FROM snapshot_authority WHERE snapshot_id = ?", (sid,))
        store._conn.commit()
    response = client.get(url(sid))
    assert response.status_code == 409
    assert "payload" not in response.json()


def test_failed_cache_admission_is_retried_and_does_not_poison_other_hosts(client, monkeypatch):
    sid = seed(client)
    project = engine.ui_projection
    calls = []
    def initially_broken(snapshot, host=None):
        calls.append(host)
        result = project(snapshot, host)
        if len(calls) == 1:
            result["overview"]["posture_statement"]["state"] = "invented"
        return result
    monkeypatch.setattr(engine, "ui_projection", initially_broken)
    with pytest.raises(SchemaValidationError):
        client.get(url(sid))
    assert client.get(url(sid)).status_code == 200
    assert client.get(url(sid, "trust")).status_code == 200
    assert calls == [None, None]


def test_cache_owns_producer_values_and_copies_only_selected_rows(client, sample, monkeypatch):
    from backend import ui_projection_api as api
    document = owner.project(sample)
    original = deepcopy(document)
    monkeypatch.setattr(engine, "ui_projection", lambda *args: document)
    sid = seed(client)
    assert client.get(url(sid)).status_code == 200
    document["engine"].clear()
    document["findings"]["rows"]["items"].clear()
    response = client.get(url(sid, "findings") + "/lists", params={"pointer": "/rows", "limit": 1})
    assert response.status_code == 200
    assert response.json()["list"]["page"]["items"] == original["findings"]["rows"]["items"][:1]
    assert response.json()["engine"] == original["engine"]
    # Copying a whole list before pagination is both an alias and scaling regression.
    copied = []
    real_copy = api.deepcopy
    def counted(value):
        if isinstance(value, list):
            copied.append(len(value))
        return real_copy(value)
    monkeypatch.setattr(api, "deepcopy", counted)
    page = api._page_view(original["findings"], "findings", 1)
    assert len(original["findings"]["rows"]["items"]) not in copied
    page["rows"]["page"]["items"][0].clear()
    page["rows"]["source_list"]["refs"].append({"mutated": True})
    assert original["findings"]["rows"]["items"][0]
    assert {"mutated": True} not in original["findings"]["rows"]["refs"]


def test_cache_owns_bound_source_when_producer_retains_and_mutates_its_input(client, monkeypatch):
    from backend.ui_projection_api import LIST_CATALOG
    sid = seed(client, {"devices": {"edge": {}}})
    snapshot, _binding = client.app.state.store.get_bound_snapshot(sid)
    expected = owner.project_device(snapshot, "edge")
    retained = []
    project = engine.ui_projection
    def retaining(source, host=None):
        retained.append(source)
        return project(source, host)
    monkeypatch.setattr(engine, "ui_projection", retaining)
    assert client.get(url(sid)).status_code == 200
    retained[0]["devices"].clear()
    response = client.get(url(sid, "device"), params={"host": "edge", "limit": 200})
    assert response.status_code == 200
    body = response.json()
    rebuilt = body["payload"]
    for pointer in LIST_CATALOG["device"]:
        wrapper = resolve(rebuilt, pointer)
        parent, _, last = pointer.rpartition("/")
        (resolve(rebuilt, parent) if parent else rebuilt)[last] = {
            **wrapper["source_list"], "items": wrapper["page"]["items"],
        }
    assert rebuilt == expected["device"]
    assert body["engine"] == expected["engine"]
    assert retained[0] is not retained[1]


def test_compiled_oneof_matches_stock_for_constraints_ambiguity_and_ref_domains():
    from backend.ui_projection_api import _compiled_validator
    schema = {
        "$defs": {"other": {"type": "string", "enum": ["withheld", "missing"]}},
        "oneOf": [
            {"type": "object", "required": ["state", "value"], "additionalProperties": False,
             "properties": {"state": {"const": "published"}, "value": {"type": "integer", "minimum": 1},
                            "paired": {"type": "boolean"}}, "dependentRequired": {"paired": ["absent"]}},
            {"type": "object", "required": ["state", "value", "reason"], "additionalProperties": False,
             "properties": {"state": {"$ref": "#/$defs/other"}, "value": {"type": "null"},
                            "reason": {"type": "string", "minLength": 1}}},
            # Overlap requires oneOf's exact-one check, even with discriminator narrowing.
            {"type": "object", "required": ["state", "value"],
             "properties": {"state": {"const": "published"}, "value": {"const": 2}}},
        ],
    }
    before = deepcopy(schema)
    stock, compiled = Draft202012Validator(schema), _compiled_validator(schema)
    for state in ("published", "withheld", "missing", "invented", None, 3, [], {}):
        for value in (None, True, 0, 1, 2, 2.5, "1", [], {}):
            for extra in ({}, {"reason": ""}, {"reason": "because"}, {"paired": True}, {"unknown": 1}):
                document = {"state": state, "value": value, **extra}
                assert compiled.is_valid(document) == stock.is_valid(document), document
    for document in (None, True, [], "published", {}, {"value": 1}, {"state": "published"}):
        assert compiled.is_valid(document) == stock.is_valid(document)
    assert schema == before


@pytest.mark.parametrize("reference,definitions", [
    ("#/$defs/a~1b", {"a/b": {"enum": ["a"]}, "a~1b": {"enum": ["b"]}}),
    ("#/$defs/%6bind", {"kind": {"enum": ["a"]}, "%6bind": {"enum": ["b"]}}),
    ("#/$defs/a/b", {"a": {"b": {"enum": ["a"]}}, "a/b": {"enum": ["b"]}}),
    ("#/$defs/kind", {"kind": True}),
    ("#/$defs/kind", {"kind": False}),
])
def test_compiled_oneof_leaves_complex_and_boolean_refs_to_stock(reference, definitions):
    from backend.ui_projection_api import _compiled_validator
    schema = {"$defs": definitions, "oneOf": [
        {"type": "object", "required": ["kind"], "properties": {"kind": {"$ref": reference}}},
        {"type": "object", "required": ["kind"], "properties": {"kind": {"const": "a"}}},
    ]}
    stock, compiled = Draft202012Validator(schema), _compiled_validator(schema)
    for document in ({"kind": "a"}, {"kind": "b"}, {"kind": None}, {}, []):
        assert compiled.is_valid(document) == stock.is_valid(document)


def test_compiled_oneof_does_not_resolve_nested_resource_refs_against_root():
    from backend.ui_projection_api import _compiled_validator
    schema = {"$id": "urn:outer", "$defs": {"kind": {"enum": ["b"]}}, "type": "object", "properties": {
        "inner": {"$id": "urn:inner", "$defs": {"kind": {"enum": ["a"]}}, "oneOf": [
            {"type": "object", "required": ["kind"], "properties": {"kind": {"$ref": "#/$defs/kind"}}},
            {"type": "object", "required": ["kind"], "properties": {"kind": {"const": "a"}}},
        ]},
    }}
    stock, compiled = Draft202012Validator(schema), _compiled_validator(schema)
    for document in ({"inner": {"kind": "a"}}, {"inner": {"kind": "b"}}, {"inner": {"kind": None}}, {}):
        assert compiled.is_valid(document) == stock.is_valid(document)
    assert not compiled.is_valid({"inner": {"kind": "a"}})


def test_compiled_oneof_rejects_reusing_an_aliased_branch_proof_in_another_resource():
    from backend.ui_projection_api import _compiled_validator
    branches = [
        {"type": "object", "required": ["kind"], "properties": {"kind": {"$ref": "#/$defs/kind"}}},
        {"type": "object", "required": ["kind"], "properties": {"kind": {"const": "a"}}},
    ]
    schema = {"$id": "urn:outer", "$defs": {"kind": {"enum": ["b"]}}, "type": "object", "properties": {
        "outer": {"oneOf": branches},
        "inner": {"$id": "urn:inner", "$defs": {"kind": {"enum": ["a"]}}, "oneOf": branches},
    }}
    stock, compiled = Draft202012Validator(schema), _compiled_validator(schema)
    for document in ({"outer": {"kind": "a"}}, {"inner": {"kind": "a"}}, {"inner": {"kind": "b"}}):
        assert compiled.is_valid(document) == stock.is_valid(document)
    assert not compiled.is_valid({"inner": {"kind": "a"}})


def test_compiled_oneof_leaves_nested_dialect_keywords_to_stock():
    from backend.ui_projection_api import _compiled_validator
    schema = {"oneOf": [
        {"type": "object", "required": ["kind"], "properties": {
            "kind": {"$schema": "http://json-schema.org/draft-04/schema#", "const": "b"},
        }},
        {"type": "object", "required": ["kind"], "properties": {"kind": {"const": "a"}}},
    ]}
    stock, compiled = Draft202012Validator(schema), _compiled_validator(schema)
    for document in ({"kind": "a"}, {"kind": "b"}, {"kind": None}, {}, []):
        assert compiled.is_valid(document) == stock.is_valid(document)
    assert not compiled.is_valid({"kind": "a"})


def test_compiled_direct_refs_preserve_siblings_nested_constraints_and_error_paths():
    from backend.ui_projection_api import _compiled_validator
    schema = {
        "$defs": {
            "Score": {"type": "integer", "minimum": 1},
            "Row": {"type": "object", "required": ["score"], "additionalProperties": False,
                    "properties": {"score": {"$ref": "#/$defs/Score"}}},
            "Rows": {"type": "array", "items": {"$ref": "#/$defs/Row"}},
            "Alias": {"$ref": "#/$defs/Rows"},
            "Any": True, "Never": False,
        },
        "type": "object", "required": ["rows"], "additionalProperties": False,
        "properties": {"rows": {"$ref": "#/$defs/Alias", "minItems": 1},
                       "positive": {"$ref": "#/$defs/Any", "type": "integer", "minimum": 1},
                       "impossible": {"$ref": "#/$defs/Never"}},
    }
    stock, compiled = Draft202012Validator(schema), _compiled_validator(schema)
    def failures(validator, value):
        return [(error.validator, list(error.absolute_path), list(error.absolute_schema_path), error.message)
                for error in validator.iter_errors(value)]
    for document in (
        {"rows": [{"score": 1}]}, {"rows": []}, {"rows": [{"score": 0}]}, {"rows": [{}]},
        {"rows": [{"score": 1, "extra": True}]}, {"rows": ["bad"]}, {},
        {"rows": [{"score": 1}], "positive": 0}, {"rows": [{"score": 1}], "impossible": None},
    ):
        assert failures(compiled, document) == failures(stock, document)


def test_compiled_direct_static_recursive_ref_preserves_acceptance_and_paths():
    from backend.ui_projection_api import _compiled_validator
    schema = {"$defs": {"Node": {
        "type": "object", "required": ["name"], "additionalProperties": False,
        "properties": {"name": {"type": "string", "minLength": 1},
                       "children": {"type": "array", "items": {"$ref": "#/$defs/Node"}}},
    }}, "$ref": "#/$defs/Node"}
    stock, compiled = Draft202012Validator(schema), _compiled_validator(schema)
    for document in ({"name": "root"}, {"name": "root", "children": [{"name": "leaf"}]},
                     {"name": "root", "children": [{"name": ""}]},
                     {"name": "root", "children": [{"name": "middle", "children": [{}]}]}):
        actual = [(error.message, list(error.absolute_path), list(error.absolute_schema_path))
                  for error in compiled.iter_errors(document)]
        expected = [(error.message, list(error.absolute_path), list(error.absolute_schema_path))
                    for error in stock.iter_errors(document)]
        assert actual == expected


@pytest.mark.parametrize("keyword,value", [("$dynamicRef", "#"), ("$dynamicAnchor", "node"),
                                          ("$recursiveRef", "#"), ("$recursiveAnchor", True)])
def test_compiler_delegates_dynamic_and_recursive_scope_keywords_to_stock(keyword, value):
    from backend.ui_projection_api import _compiled_validator
    schema = {"$defs": {"Dynamic": {keyword: value}}, "type": "integer"}
    compiled = _compiled_validator(schema)
    assert type(compiled) is Draft202012Validator
    assert compiled.is_valid(1) and not compiled.is_valid("1")


def test_compiled_source_and_transport_match_canonical_owner(client):
    from backend import ui_projection_api as api
    sid = seed(client, {"devices": {"edge": {}}})
    for host in (None, "edge", "missing"):
        source = owner.project({}) if host is None else owner.project_device({}, host)
        schema = api._OWNER if host is None else {"$ref": "#/$defs/DeviceDocument", "$defs": api._DEFS}
        compiled = api._DOCUMENT_VALIDATOR if host is None else api._DEVICE_VALIDATOR
        stock = Draft202012Validator(schema)
        assert compiled.is_valid(source) == stock.is_valid(source) is True
        source["engine"]["code_schema_version"] = 3
        assert compiled.is_valid(source) == stock.is_valid(source) is False
    for view, pointers in api.LIST_CATALOG.items():
        params = {"host": "edge"} if view == "device" else {}
        bodies = [("view", client.get(url(sid, view), params=params).json())]
        for pointer in pointers:
            bodies.append(("list", client.get(url(sid, view) + "/lists", params={**params, "pointer": pointer}).json()))
        for kind, body in bodies:
            schema = api._VIEW_SCHEMA if kind == "view" else api._LIST_SCHEMA
            stock, compiled = Draft202012Validator(schema), api._VALIDATORS[kind]
            assert compiled.is_valid(body) == stock.is_valid(body) is True
            for key, value in (("view", "invented"), ("identity", {}), ("engine", {}), ("unexpected", 1)):
                bad = {**body, key: value}
                assert compiled.is_valid(bad) == stock.is_valid(bad) is False


def _validation_errors(validator, value):
    def record(error):
        return {"message": error.message, "validator": error.validator,
                "path": list(error.absolute_path), "schema_path": list(error.absolute_schema_path),
                "context": [record(child) for child in error.context]}
    return [record(error) for error in validator.iter_errors(value)]


@pytest.mark.parametrize("mutation", ["inline_type", "reference_type", "new_minimum", "required", "resource", "dialect"])
def test_compiled_construction_preserves_public_schema_mutations(mutation):
    from backend.ui_projection_api import _compiled_validator
    schema = {"$defs": {"Leaf": {"type": "integer"}}, "type": "object",
              "properties": {"inline": {"type": "integer"}, "ref": {"$ref": "#/$defs/Leaf"}},
              "required": ["ref"]}
    compiled = _compiled_validator(schema)
    assert compiled.is_valid({"inline": 1, "ref": 1})
    if mutation == "inline_type":
        schema["properties"]["inline"]["type"] = "string"
    elif mutation == "reference_type":
        schema["$defs"]["Leaf"]["type"] = "string"
    elif mutation == "new_minimum":
        schema["$defs"]["Leaf"]["minimum"] = 5
    elif mutation == "required":
        schema["required"] = ["missing"]
    elif mutation == "resource":
        schema["properties"]["ref"] = {"$id": "urn:changed", "$defs": {"Leaf": {"type": "string"}},
                                       "$ref": "#/$defs/Leaf"}
    else:
        schema["properties"]["inline"] = {"$schema": "http://json-schema.org/draft-04/schema#", "const": 10}
    for value in ({"inline": 1, "ref": 1}, {"inline": "a", "ref": "a"}, {"ref": 6}, {}):
        assert _validation_errors(compiled, value) == _validation_errors(Draft202012Validator(schema), value)


def test_compiled_construction_never_exposes_private_schema_through_error_context():
    from backend.ui_projection_api import _compiled_validator
    schema = {"$defs": {"Leaf": {"type": "integer"}}, "oneOf": [
        {"type": "object", "required": ["kind", "value"],
         "properties": {"kind": {"const": "integer"}, "value": {"$ref": "#/$defs/Leaf"}}},
        {"type": "object", "required": ["kind", "value"],
         "properties": {"kind": {"const": "null"}, "value": {"type": "null"}}},
    ]}
    compiled = _compiled_validator(schema)
    bad = {"kind": "integer", "value": "changed"}
    assert _validation_errors(compiled, bad) == _validation_errors(Draft202012Validator(schema), bad)
    error = next(compiled.iter_errors(bad))
    leaf_error = next(child for child in error.context if child.validator == "type" and child.instance == "changed")
    assert error.schema is schema
    assert leaf_error.schema is schema["$defs"]["Leaf"]
    leaf_error.schema["type"] = "string"
    assert compiled.is_valid(bad)
    assert not compiled.is_valid({"kind": "integer", "value": 1})


def test_compiled_construction_schema_reassignment_and_type_exact_fingerprint():
    from backend.ui_projection_api import _compiled_validator
    schema = {"const": True}
    compiled = _compiled_validator(schema)
    schema["const"] = 1
    assert compiled.is_valid(1) and not compiled.is_valid(True)
    unicode_schema = {"const": "\U0001f600"}
    unicode_compiled = _compiled_validator(unicode_schema)
    assert unicode_compiled.is_valid("\U0001f600")
    unicode_schema["const"] = "\ud83d\ude00"
    assert unicode_compiled.is_valid("\ud83d\ude00") and not unicode_compiled.is_valid("\U0001f600")
    compiled.schema = {"type": "string"}
    assert compiled.is_valid("new") and not compiled.is_valid(1)


def test_compiled_construction_changed_format_resolver_registry_and_legacy_contexts_are_stock():
    from backend.ui_projection_api import _compiled_validator
    from jsonschema import FormatChecker
    from referencing import Registry, Resource
    schema = {"$defs": {"Leaf": {"type": "string", "format": "date"}}, "$ref": "#/$defs/Leaf"}
    compiled = _compiled_validator(schema)
    assert compiled.is_valid("not-a-date")
    formatted = compiled.evolve(format_checker=FormatChecker())
    assert type(formatted) is Draft202012Validator
    assert not formatted.is_valid("not-a-date") and formatted.is_valid("2026-10-02")
    alternate = Draft202012Validator({"$defs": {"Leaf": {"type": "integer"}}})._resolver
    changed = compiled.evolve(_resolver=alternate)
    stock = Draft202012Validator(schema).evolve(_resolver=alternate)
    for value in (1, "2026-10-02", None):
        assert _validation_errors(changed, value) == _validation_errors(stock, value)
    resource = Resource.from_contents({"$schema": Draft202012Validator.META_SCHEMA["$id"], "type": "integer"})
    registry = Registry().with_resource("urn:external-test", resource)
    registered = compiled.evolve(schema={"$ref": "urn:external-test"}, registry=registry, _resolver=None)
    assert registered.is_valid(1) and not registered.is_valid("1")
    with pytest.warns(DeprecationWarning):
        from jsonschema import RefResolver
    legacy = RefResolver.from_schema({"$defs": {"Leaf": {"type": "integer"}}})
    evolved = compiled.evolve(resolver=legacy)
    assert evolved.is_valid(1) and not evolved.is_valid("1")


@pytest.mark.parametrize("attribute", ["format_checker", "_resolver", "_registry"])
def test_compiled_facade_rejects_unsupported_direct_context_assignment(attribute):
    from backend.ui_projection_api import _compiled_validator
    compiled = _compiled_validator({"type": "integer"})
    with pytest.raises(AttributeError):
        setattr(compiled, attribute, object())


def test_compiled_facade_preserves_deprecated_schema_overloads_and_reference_exceptions():
    from backend.ui_projection_api import _compiled_validator
    compiled = _compiled_validator({"type": "integer"})
    with pytest.warns(DeprecationWarning):
        assert compiled.is_valid("x", {"type": "string"})
    with pytest.warns(DeprecationWarning):
        assert list(compiled.iter_errors("x", {"type": "string"})) == []
    schema = {"$ref": "#/$defs/absent"}
    with pytest.raises(Exception) as stock:
        Draft202012Validator(schema).validate(1)
    with pytest.raises(type(stock.value)) as actual:
        _compiled_validator(schema).validate(1)
    assert str(actual.value) == str(stock.value)


def test_compiled_construction_cache_is_bounded_strongly_retained_and_read_only(monkeypatch):
    from backend import ui_projection_api as api
    import inspect
    schema = {"type": "object", "properties": {"value": {"type": "integer"}}, "required": ["value"]}
    compiled = api._compiled_validator(schema)
    private = compiled._OwnedSchemaValidator__compiled
    retained = inspect.getclosurevars(type(private).evolve).nonlocals["constructions"]
    owned_context = inspect.getclosurevars(type(private).evolve).nonlocals["owned_context"]
    contexts = inspect.getclosurevars(owned_context).nonlocals["contexts"]
    count = len(retained)
    context_count = len(contexts)
    assert 0 < count <= api._MAX_CONSTRUCTION_NODES
    assert all(identity == id(node) and validator.schema is node for identity, (node, validator) in retained.items())
    with pytest.raises(TypeError):
        retained[0] = ({}, None)
    with pytest.raises(TypeError):
        contexts[0] = private
    assert all(identity == id(validator) and owned_context(validator) for identity, validator in contexts.items())
    unknown = type(private)(schema=private.schema, _resolver=private._resolver)
    assert not owned_context(unknown)
    assert unknown.is_valid({"value": 1}) and not unknown.is_valid({"value": "1"})
    assert not owned_context(compiled.evolve())
    with ThreadPoolExecutor(max_workers=6) as pool:
        values = [{"value": n if n % 2 else str(n)} for n in range(60)]
        assert list(pool.map(compiled.is_valid, values)) == [bool(n % 2) for n in range(60)]
    assert len(retained) == count
    assert len(contexts) == context_count
    monkeypatch.setattr(api, "_MAX_CONSTRUCTION_NODES", 1)
    bounded = api._compiled_validator(schema)
    bounded_private = bounded._OwnedSchemaValidator__compiled
    assert "constructions" not in inspect.getclosurevars(type(bounded_private).evolve).nonlocals
    assert bounded.is_valid({"value": 1}) and not bounded.is_valid({"value": "1"})


def test_compiled_schema_unsupported_python_values_remain_stock():
    from backend.ui_projection_api import _compiled_validator
    schema = {"enum": [(1,)]}
    assert type(_compiled_validator(schema)) is Draft202012Validator
    cyclic = {}
    cyclic["$defs"] = {"Cycle": cyclic}
    assert type(_compiled_validator(cyclic)) is Draft202012Validator
    schema = {"const": []}
    compiled = _compiled_validator(schema)
    schema["const"] = ()
    assert compiled.is_valid(()) == Draft202012Validator(schema).is_valid(())
