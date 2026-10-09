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
    for path in (url(991), url(991, "inventory") + "/lists?pointer=/devices/rows",
                 url(991, "topology") + "/path?src_ip=192.0.2.1&dst_ip=198.51.100.1"):
        assert client.get(path, headers={"sec-fetch-site": "cross-site"}).status_code == 403
        assert client.get(path, headers={"host": "evil.example"}).status_code == 403


def test_routes_declare_response_models(client):
    paths = [r for r in client.app.routes if "ui-projection" in getattr(r, "path", "")]
    assert len(paths) == 3
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


@pytest.mark.parametrize("view", ["overview", "trust", "inventory", "findings", "topology", "device"])
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
    for view in ("overview", "trust", "inventory", "findings", "topology", "overview"):
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


@pytest.mark.parametrize("flavor", ["properties", "unique_oneof"])
def test_compiled_invalid_depth_does_not_multiply_validation_work(flavor, monkeypatch):
    from backend.ui_projection_api import _compiled_validator

    originals = {name: Draft202012Validator.VALIDATORS[name] for name in ("properties", "type")}
    counting = False
    calls = {}

    def count_keyword(name, original):
        # An ordinary function counts invocation once, then returns the unchanged
        # keyword generator. Generator resumes/cleanup cannot inflate the count.
        def counted(validator, constraint, instance, schema):
            if counting:
                calls[name] += 1
            return original(validator, constraint, instance, schema)
        return counted

    for name, original in originals.items():
        monkeypatch.setitem(Draft202012Validator.VALIDATORS, name, count_keyword(name, original))

    for depth in (4, 8, 12):
        schema, value = {"type": "integer"}, "invalid leaf"
        for _ in range(depth):
            if flavor == "properties":
                schema = {"type": "object", "properties": {"child": schema}, "required": ["child"]}
                value = {"child": value}
            else:
                schema = {"oneOf": [
                    {"type": "object", "required": ["kind", "child"], "additionalProperties": False,
                     "properties": {"kind": {"const": "a"}, "child": schema}},
                    {"type": "object", "required": ["kind"], "additionalProperties": False,
                     "properties": {"kind": {"const": "b"}}},
                ]}
                value = {"kind": "a", "child": value}
        compiled = _compiled_validator(schema)
        calls = dict.fromkeys(originals, 0)
        counting = True
        try:
            actual = _validation_errors(compiled, value)
        finally:
            counting = False
        assert actual == _validation_errors(Draft202012Validator(schema), value)
        assert actual and actual[0]["path"] == (["child"] * depth if flavor == "properties" else [])
        # One private traversal plus public stock diagnostics is bounded by depth.
        # A per-child probe followed by stock retry fails already at depth four.
        assert 0 < calls["properties"] <= 3 * depth
        assert 0 < calls["type"] <= 3 * (depth + 1)


@pytest.mark.parametrize("schema,valid,invalid", [
    ({"type": "object", "properties": {"free": True, "never": False}},
     [{}, {"free": [1, None]}], [{"never": None}, {"never": 1}]),
    ({"type": "object", "required": ["mode"],
      "properties": {"mode": {"type": "string"}, "x": {"type": "integer"}},
      "dependentRequired": {"x": ["mode"]},
      "dependentSchemas": {"x": {"properties": {"y": {"type": "string"}}, "required": ["y"]}},
      "if": {"properties": {"mode": {"const": "a"}}},
      "then": {"properties": {"x": {"minimum": 1}}}, "else": {"not": {"required": ["x"]}}},
     [{"mode": "a", "x": 1, "y": "ok"}, {"mode": "b"}],
     [{"mode": "a", "x": 0, "y": 3}, {"mode": "b", "x": 1, "y": "ok"}, {"x": 1}]),
    ({"$defs": {"Record": {"type": "object", "properties": {"x": {"type": "integer"}},
                            "required": ["x"]}},
      "allOf": [{"$ref": "#/$defs/Record"}, {"anyOf": [
          {"properties": {"y": {"type": "string"}}, "required": ["y"]},
          {"properties": {"z": {"type": "boolean"}}, "required": ["z"]},
      ]}], "unevaluatedProperties": False},
     [{"x": 1, "y": "ok"}, {"x": 1, "z": True}],
     [{"x": "bad", "y": 0}, {"x": 1, "y": "ok", "extra": 1}, {"x": 1, "y": 9, "z": True}]),
    ({"properties": {"value": {"allOf": [
        {"anyOf": [{"type": "integer"}, {"type": "string"}]},
        {"oneOf": [{"type": "integer", "minimum": 0}, {"type": "integer", "maximum": 10},
                   {"type": "string"}]}, {"not": {"const": "forbidden"}},
    ]}}, "required": ["value"]},
     [{"value": 11}, {"value": -1}, {"value": "ok"}],
     [{"value": 5}, {"value": "forbidden"}, {"value": None}]),
    ({"type": "array", "prefixItems": [{"type": "integer"}],
      "contains": {"type": "string", "minLength": 2}, "minContains": 1, "maxContains": 2,
      "unevaluatedItems": False},
     [[1, "ok"], [1, "ok", "yes"]], [[1, "x"], [1, "ok", True], [1, "ok", "yes", "more"]]),
], ids=["boolean-children", "conditional-dependencies", "ref-evaluated-properties",
        "composed-branches", "contains-evaluated-items"])
def test_compiled_private_descents_preserve_composed_validity_and_public_diagnostics(schema, valid, invalid):
    from backend.ui_projection_api import _compiled_validator

    stock, compiled = Draft202012Validator(schema), _compiled_validator(schema)
    for expected, values in ((True, valid), (False, invalid)):
        for value in values:
            assert stock.is_valid(value) is expected
            assert compiled.is_valid(value) is expected
            assert _validation_errors(compiled, value) == _validation_errors(stock, value)


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


@pytest.fixture()
def native_body(client, sample):
    from backend import ui_projection_api as api
    body = client.get(url(seed(client, sample))).json()
    assert api._native_instance_allowed(body)
    return body


def test_native_transport_pins_provider_schema_and_preserves_public_errors(native_body):
    from backend import ui_projection_api as api
    assert api.version("jsonschema-rs") == "0.58.5"
    assert api._native_schema_hash(api._VIEW_SCHEMA) == api._NATIVE_SCHEMA_HASHES["view"]
    assert api._native_schema_hash(api._LIST_SCHEMA) == api._NATIVE_SCHEMA_HASHES["list"]
    schema = deepcopy(api._VIEW_SCHEMA)
    validator = api._NativeTransportValidator(schema, "view")
    native = validator._NativeTransportValidator__native
    assert native is not None
    calls = []

    class Observed:
        def is_valid(self, value):
            calls.append(True)
            return native.is_valid(value)

    validator._NativeTransportValidator__native = Observed()
    assert validator.is_valid(native_body)
    assert len(calls) == 1
    for removed in (("engine_state",), ("engine_state_owner",), ("engine_state", "engine_state_owner")):
        changed = deepcopy(native_body)
        fact = changed["payload"]["facts"]["avg_health"]["fact"]
        assert {"engine_state", "engine_state_owner"} <= fact.keys()
        for key in removed:
            del fact[key]
        assert validator.is_valid(changed) is (len(removed) == 2)
        assert _validation_errors(validator, changed) == _validation_errors(api._stock_validator(schema), changed)
    bad = {**native_body, "view": "invented"}
    error = next(validator.iter_errors(bad))
    assert error.schema is schema
    assert _validation_errors(validator, bad) == _validation_errors(api._stock_validator(schema), bad)
    assert not hasattr(api._DOCUMENT_VALIDATOR, "_NativeTransportValidator__native")
    assert not hasattr(api._DEVICE_VALIDATOR, "_NativeTransportValidator__native")


def test_native_refuses_unsupported_instances_before_acceptance(native_body):
    from backend import ui_projection_api as api
    validator = api._NativeTransportValidator(deepcopy(api._VIEW_SCHEMA), "view")

    class Forbidden:
        def is_valid(self, _value):
            pytest.fail("unsupported instance reached native acceptance")

    validator._NativeTransportValidator__native = Forbidden()
    for value in (1.0, 2**53, -(2**53), "line\n", "line\r", "\u2028", "\u2029", "\ud800", "\udfff"):
        body = deepcopy(native_body)
        if type(value) in (float, int):
            body["identity"]["snapshot_id"] = value
        else:
            body["engine"]["code_schema_version"] = value
        assert not api._native_instance_allowed(body)
        assert _validation_errors(validator, body) == _validation_errors(api._stock_validator(validator.schema), body)
    for value in ((1,), {1: "key"}, {"\ud800": 1}, float("nan"), float("inf")):
        assert not api._native_instance_allowed(value)
        assert validator.is_valid(value) == api._stock_validator(validator.schema).is_valid(value)
    cyclic = []
    cyclic.append(cyclic)
    assert not api._native_instance_allowed(cyclic)
    deep = 1
    for _ in range(129):
        deep = [deep]
    assert not api._native_instance_allowed(deep)
    assert not api._native_instance_allowed(type("ForeignDict", (dict,), {})())
    assert api._native_instance_allowed({"okay": [True, False, None, 2**53 - 1, -(2**53 - 1), "\U0001f600"]})


@pytest.mark.parametrize("mutation", ["missing_readiness", "boolean_count", "host_not_list", "missing_band",
                                     "extra_group_field", "unknown_check_status", "missing_check_phase"])
def test_native_w12a_closed_rollups_match_stock_on_valid_and_rejected_shapes(native_body, mutation):
    """Exercise every new readiness level and health bucket through the audited transport schema."""
    from backend import ui_projection_api as api

    def fact(value):
        return {"state": "published", "value": value, "subject": None, "refs": [], "basis": "synthetic.owner"}

    check = {"index": 0, "pointer": "/migration_readiness/0/checks/0", "check": fact("synthetic check"),
             "status": fact("pass"), "note": fact("synthetic bounded observation"), "phase": fact("Pre-change")}
    checks = {"state": "published", "subject": "/migration_readiness/0/checks", "refs": [],
              "basis": "synthetic.owner", "items": [check]}
    group = {"index": 0, "pointer": "/migration_readiness/0", "group": fact("synthetic group"),
             "readiness": fact("READY"), "switches": fact(["synthetic-host"]), "endpoints": fact(0),
             "n_fail": fact(0), "n_warn": fact(0), "checks": checks}
    body = deepcopy(native_body)
    body["payload"]["readiness"] = {"groups": {"pointer": "/readiness/groups",
        "source_list": {"state": "published", "subject": "/migration_readiness", "refs": [], "basis": "synthetic.owner"},
        "page": {"offset": 0, "limit": 25, "returned": 1, "total": 1, "has_more": False, "items": [group]}}}
    schema = deepcopy(api._VIEW_SCHEMA)
    native = api._NativeTransportValidator(schema, "view")
    assert native._NativeTransportValidator__native is not None
    stock = api._stock_validator(schema)
    assert native.is_valid(body) and stock.is_valid(body)
    altered = deepcopy(body)
    changed_group = altered["payload"]["readiness"]["groups"]["page"]["items"][0]
    changed_check = changed_group["checks"]["items"][0]
    band = altered["payload"]["fleet_health"]["bands"][0]
    if mutation == "missing_readiness":
        del altered["payload"]["readiness"]
    elif mutation == "boolean_count":
        band["n"] = fact(True)
    elif mutation == "host_not_list":
        band["hosts"] = fact("synthetic-host")
    elif mutation == "missing_band":
        altered["payload"]["fleet_health"]["bands"].pop()
    elif mutation == "extra_group_field":
        changed_group["invented"] = 1
    elif mutation == "unknown_check_status":
        changed_check["status"] = fact("PASS")
    else:
        del changed_check["phase"]
    assert not native.is_valid(altered) and not stock.is_valid(altered)
    assert _validation_errors(native, altered) == _validation_errors(stock, altered)


@pytest.mark.parametrize("surface", ["inventory", "inventory_list", "device"])
@pytest.mark.parametrize("mutation", ["missing_rollup", "missing_severity", "extra_severity", "bool_count",
                                     "fractional_count", "negative_count", "oversized_count", "unknown_worst", "extra_rollup",
                                     "withheld_value", "missing_reason", "engine_state_pair", "unknown_caveat",
                                     "unknown_engine_owner", "global_limitation_count"])
def test_native_w12b_device_rollups_match_stock_on_views_lists_and_refusals(client, monkeypatch, surface, mutation):
    """The new nested record is admitted natively on real transport shapes, including list rows."""
    from backend import ui_projection_api as api
    # Independently selected prospective pins let parity run before production pins change.
    prospective = {"view": "9bfad9b410781bc9a3a9fe6a7fc84e4341d97d6c1f2a6b0b4dcaad7146e04e80",
                   "list": "b493aa84163f3f76b632e75f625be3a595f03814af727725698b83f58bd2ff6c"}
    assert {kind: api._native_schema_hash(schema) for kind, schema in
            (("view", api._VIEW_SCHEMA), ("list", api._LIST_SCHEMA))} == prospective
    monkeypatch.setattr(api, "_NATIVE_SCHEMA_HASHES", prospective)

    def fact(value):
        return {"state": "published", "value": value, "subject": None, "refs": [], "basis": "synthetic.owner"}

    from cisco_toolkit.parse import parse_security
    host = "native-device"
    snapshot = {section: [] for section in owner.PUNCHLIST_INPUTS}
    snapshot.update({
        "devices": {host: {"hostname": host}},
        "interfaces": {host: {"Gi1/0/1": {"switchport_mode": "Access", "vlan": "10"}}},
        "punchlist": [{"severity": "High", "devices": [host]}],
        "security": {host: parse_security("hostname " + host + "\n")},
        "software_risk": {"per_device": [{"host": host, "config_assessable": True}]},
        "qos_audit": {"per_device": []}, "syslog_intelligence": {"per_device": []},
        "platform_health": {"per_device": []}, "device_dossiers": {"per_device": []},
        "protocol_assessability": {}, "vtp_safety_baseline": {}, "ipv6_routing_adjacency_baseline": {},
        "collection_completeness": {"devices": [], "summary": {"inventory": 1, "collected": 1}},
        "stp_roots": {}, "vlan_cutover": [],
    })
    sid = seed(client, snapshot)
    inventory = client.get(url(sid, "inventory"), params={"limit": 1}).json()
    first = inventory["payload"]["devices"]["rows"]["page"]["items"][0]
    if surface == "device":
        body = client.get(url(sid, "device"), params={"host": first["host"], "limit": 1}).json()
        target, field, kind = body["payload"], "findings_rollup", "view"
    elif surface == "inventory_list":
        body = client.get(url(sid, "inventory") + "/lists", params={"pointer": "/devices/rows", "limit": 1}).json()
        target, field, kind = body["list"]["page"]["items"][0], "findings", "list"
    else:
        body = inventory
        target, field, kind = first, "findings", "view"
    target[field] = {"worst": fact("High"),
                     "by_severity": fact({"Critical": 0, "High": 1, "Medium": 0, "Low": 0, "Info": 0})}
    schema = deepcopy(api._VIEW_SCHEMA if kind == "view" else api._LIST_SCHEMA)
    native = api._NativeTransportValidator(schema, kind)
    assert native._NativeTransportValidator__native is not None
    stock = api._stock_validator(schema)
    assert api._native_instance_allowed(body)
    assert native.is_valid(body) and stock.is_valid(body)

    def selected(document):
        if surface == "device":
            return document["payload"]["findings_rollup"]
        if surface == "inventory_list":
            return document["list"]["page"]["items"][0]["findings"]
        return document["payload"]["devices"]["rows"]["page"]["items"][0]["findings"]

    for state in ("not_collected", "unverified", "collected_but_empty"):
        held = deepcopy(body)
        declared = selected(held)
        if state == "collected_but_empty":
            declared["by_severity"]["value"] = dict.fromkeys(("Critical", "High", "Medium", "Low", "Info"), 0)
            declared["by_severity"]["engine_state"] = "collected_but_empty"
            declared["by_severity"]["engine_state_owner"] = "ssot.abstention_reason"
            declared["by_severity"]["caveats"] = ["device_findings_scope"]
            declared["worst"].update(state=state, value=None, reason="synthetic stored selection empty")
        else:
            for envelope in declared.values():
                envelope.update(state=state, value=None, reason="synthetic capture custody withheld")
        assert native.is_valid(held) and stock.is_valid(held)
    rollup = target[field]
    counts = rollup["by_severity"]
    if mutation == "missing_rollup":
        del target[field]
    elif mutation == "missing_severity":
        counts["value"].pop("Info")
    elif mutation == "extra_severity":
        counts["value"]["Unknown"] = 0
    elif mutation == "bool_count":
        counts["value"]["High"] = True
    elif mutation == "fractional_count":
        counts["value"]["High"] = 0.5
    elif mutation == "negative_count":
        counts["value"]["High"] = -1
    elif mutation == "oversized_count":
        counts["value"]["High"] = 2**53
    elif mutation == "unknown_worst":
        rollup["worst"] = fact("Poor")
    elif mutation == "extra_rollup":
        rollup["invented"] = True
    elif mutation == "withheld_value":
        counts.update(state="not_collected", reason="synthetic capture absent")
    elif mutation == "missing_reason":
        counts.update(state="not_collected", value=None)
    elif mutation == "engine_state_pair":
        counts["engine_state"] = "collected_but_empty"
    elif mutation == "unknown_caveat":
        counts["caveats"] = ["unregistered_scope"]
    elif mutation == "unknown_engine_owner":
        counts.update(engine_state="collected_but_empty", engine_state_owner="synthetic.owner")
    else:
        body["limitations"].pop()
    assert not native.is_valid(body) and not stock.is_valid(body)
    assert _validation_errors(native, body) == _validation_errors(stock, body)


@pytest.mark.parametrize("surface", ["inventory", "inventory_list", "device"])
@pytest.mark.parametrize("mutation", ["missing_rollup", "extra_rollup", "unknown_worst", "bool_count", "negative_count",
                                     "oversized_count", "withheld_value", "missing_dimension", "bad_dimension",
                                     "bad_source", "integer_flag", "extra_metadata"])
def test_native_w13_coverage_matches_stock_on_real_views_lists_and_refusals(client, surface, mutation):
    from backend import ui_projection_api as api
    from cisco_toolkit.coverage_matrix import compute_coverage_matrix
    host = "native-coverage"
    snapshot = {
        "devices": {host: {"hostname": host}},
        "collection_completeness": {"devices": [], "summary": {"inventory": 1, "collected": 1}},
        "capture_integrity": {"findings": [{"host": host, "status": "empty", "reason": "synthetic"}]},
        "parse_yield": {"events": []}, "architecture_coverage": {"classes": []},
    }
    snapshot["coverage_matrix"] = compute_coverage_matrix(snapshot)
    sid = seed(client, snapshot)
    inventory = client.get(url(sid, "inventory"), params={"limit": 1}).json()
    if surface == "device":
        body = client.get(url(sid, "device"), params={"host": host, "limit": 1}).json()
        target, field, kind = body["payload"], "coverage_rollup", "view"
    elif surface == "inventory_list":
        body = client.get(url(sid, "inventory") + "/lists", params={"pointer": "/devices/rows", "limit": 1}).json()
        target, field, kind = body["list"]["page"]["items"][0], "coverage", "list"
    else:
        body = inventory
        target, field, kind = body["payload"]["devices"]["rows"]["page"]["items"][0], "coverage", "view"
    rollup = target[field]
    assert rollup["worst"]["value"] == "unverified"
    assert rollup["n_abstained"]["value"] == 1
    schema = deepcopy(api._VIEW_SCHEMA if kind == "view" else api._LIST_SCHEMA)
    native = api._NativeTransportValidator(schema, kind)
    assert native._NativeTransportValidator__native is not None
    stock = api._stock_validator(schema)
    assert api._native_instance_allowed(body)
    assert native.is_valid(body) and stock.is_valid(body)
    # Metadata shape controls use a real, paged device coverage response, even when the
    # rollup surface being checked is Inventory or its list transport.
    if mutation in ("missing_dimension", "bad_dimension", "bad_source", "integer_flag", "extra_metadata"):
        body = client.get(url(sid, "device"), params={"host": host, "limit": 1}).json()
        native = api._NativeTransportValidator(deepcopy(api._VIEW_SCHEMA), "view")
        stock = api._stock_validator(deepcopy(api._VIEW_SCHEMA))
        item = body["payload"]["coverage"]["page"]["items"][0]
        if mutation == "missing_dimension":
            del item["dimension"]
        elif mutation == "bad_dimension":
            item["dimension"]["value"] = "risk"
        elif mutation == "bad_source":
            item["verdict_source"]["value"] = "foreign"
        elif mutation == "integer_flag":
            item["is_abstention"]["value"] = 0
        else:
            item["assurance"] = True
    elif mutation == "missing_rollup":
        del target[field]
    elif mutation == "extra_rollup":
        rollup["assurance"] = True
    elif mutation == "unknown_worst":
        rollup["worst"]["value"] = "healthy"
    elif mutation == "bool_count":
        rollup["n_abstained"]["value"] = True
    elif mutation == "negative_count":
        rollup["n_abstained"]["value"] = -1
    elif mutation == "oversized_count":
        rollup["n_abstained"]["value"] = 2**53
    else:
        rollup["worst"].update(state="not_collected", reason="synthetic withheld")
    assert not native.is_valid(body) and not stock.is_valid(body)
    assert _validation_errors(native, body) == _validation_errors(stock, body)


@pytest.mark.parametrize("mutation", ["missing_dimension", "extra_metadata", "bad_dimension", "bad_source",
                                     "integer_flag", "withheld_value", "missing_reason"])
def test_native_w13_coverage_metadata_list_matches_stock_and_retains_withheld_values(client, mutation):
    from backend import ui_projection_api as api
    from cisco_toolkit.coverage_matrix import compute_coverage_matrix
    host = "native-coverage-list"
    snapshot = {"devices": {host: {"hostname": host}},
                "collection_completeness": {"devices": [], "summary": {"inventory": 1, "collected": 1}},
                "capture_integrity": {"findings": [{"host": host, "status": "empty", "reason": "synthetic"}]},
                "parse_yield": {"events": []}, "architecture_coverage": {"classes": []}}
    snapshot["coverage_matrix"] = compute_coverage_matrix(snapshot)
    sid = seed(client, snapshot)
    body = client.get(url(sid, "device") + "/lists",
                      params={"host": host, "pointer": "/coverage", "limit": 1}).json()
    schema = deepcopy(api._LIST_SCHEMA)
    native = api._NativeTransportValidator(schema, "list")
    stock = api._stock_validator(schema)
    assert native._NativeTransportValidator__native is not None
    assert api._native_instance_allowed(body)
    assert native.is_valid(body) and stock.is_valid(body)
    item = body["list"]["page"]["items"][0]
    assert item["axis"] == "capture" and item["dimension"]["value"] == "capture"
    # A duplicate exact join returns withheld cells on the real list route, not a fabricated
    # shape. Retain the same native LIST validator; a view verdict cannot certify this branch.
    duplicate = next(row for row in snapshot["coverage_matrix"]["rows"]
                     if row["device"] == host and row["axis"] == item["axis"])
    snapshot["coverage_matrix"]["rows"].append(deepcopy(duplicate))
    held_sid = seed(client, snapshot)
    held_body = client.get(url(held_sid, "device") + "/lists",
                           params={"host": host, "pointer": "/coverage", "limit": 1}).json()
    held_item = held_body["list"]["page"]["items"][0]
    for field in ("fact", "dimension", "verdict_source", "is_abstention"):
        assert held_item[field]["state"] == "unverified" and held_item[field]["value"] is None
    assert api._native_instance_allowed(held_body)
    assert native.is_valid(held_body) and stock.is_valid(held_body)
    if mutation == "missing_dimension":
        del item["dimension"]
    elif mutation == "extra_metadata":
        item["assurance"] = True
    elif mutation == "bad_dimension":
        item["dimension"]["value"] = "risk"
    elif mutation == "bad_source":
        item["verdict_source"]["value"] = "foreign"
    elif mutation == "integer_flag":
        item["is_abstention"]["value"] = 0
    elif mutation == "withheld_value":
        item["dimension"].update(state="unverified", reason="synthetic withheld")
    else:
        item["dimension"].update(state="unverified", value=None)
    assert not native.is_valid(body) and not stock.is_valid(body)
    assert _validation_errors(native, body) == _validation_errors(stock, body)


def test_native_schema_version_and_owned_copy_are_checked_before_compilation(monkeypatch):
    from backend import ui_projection_api as api
    provider = api._native_provider()
    assert provider is not None
    calls = []
    real = provider.Draft202012Validator

    def observed(schema, **options):
        calls.append(options)
        assert options == {"offline": True, "validate_formats": False, "ignore_unknown_formats": True}
        return real(schema, **options)

    monkeypatch.setattr(provider, "Draft202012Validator", observed)
    changed = deepcopy(api._VIEW_SCHEMA)
    changed["title"] = "not audited"
    assert api._NativeTransportValidator(changed, "view")._NativeTransportValidator__native is None
    assert api._NativeTransportValidator(api._OWNER, "view")._NativeTransportValidator__native is None
    assert api._NativeTransportValidator(api._VIEW_SCHEMA, "list")._NativeTransportValidator__native is None
    for refused_version in ("0.58.3", "0.58.4"):
        with monkeypatch.context() as altered:
            altered.setattr(api, "version", lambda _name: refused_version)
            assert api._native_provider() is None
            assert api._NativeTransportValidator(api._VIEW_SCHEMA, "view")._NativeTransportValidator__native is None
            assert api._NativeTransportValidator(api._LIST_SCHEMA, "list")._NativeTransportValidator__native is None
    assert calls == []
    assert api._native_schema_hash({"const": "\ud83d\ude00"}) is None
    copied = api.deepcopy
    schema = deepcopy(api._VIEW_SCHEMA)

    def changed_copy(value):
        result = copied(value)
        if value is schema:
            result["title"] = "changed during copy"
        return result

    with monkeypatch.context() as altered:
        altered.setattr(api, "deepcopy", changed_copy)
        assert api._NativeTransportValidator(schema, "view")._NativeTransportValidator__native is None
    assert calls == []
    assert api._NativeTransportValidator(schema, "view")._NativeTransportValidator__native is not None
    assert len(calls) == 1


def test_native_failure_and_mutation_never_publish_private_diagnostics(native_body):
    from backend import ui_projection_api as api
    schema = deepcopy(api._VIEW_SCHEMA)
    validator = api._NativeTransportValidator(schema, "view")

    class Failing:
        def is_valid(self, _value):
            raise ValueError("private native sentinel")

    validator._NativeTransportValidator__native = Failing()
    assert validator.is_valid(native_body)
    bad = {**native_body, "view": "invented"}
    error = next(validator.iter_errors(bad))
    assert error.__context__ is None
    assert "private native sentinel" not in str(error)
    assert _validation_errors(validator, bad) == _validation_errors(api._stock_validator(schema), bad)

    class Mutating:
        def is_valid(self, _value):
            schema["required"] = ["not_present"]
            return True

    validator._NativeTransportValidator__native = Mutating()
    assert not validator.is_valid(native_body)
    validator.schema = {"type": "integer"}
    assert validator.is_valid(1) and not validator.is_valid("1")
    assert type(validator.evolve()) is Draft202012Validator
    for outcome in (True, False, "exception"):
        replaced = api._NativeTransportValidator(deepcopy(api._VIEW_SCHEMA), "view")

        class Replacing:
            def is_valid(self, _value):
                replaced.schema = {"type": "integer"}
                if outcome == "exception":
                    raise ValueError("private native sentinel")
                return outcome

        replaced._NativeTransportValidator__native = Replacing()
        assert not replaced.is_valid(native_body)
        assert next(replaced.iter_errors(native_body)).schema is replaced.schema


def test_all_python_fallbacks_and_evolved_contexts_refuse_external_retrieval(tmp_path):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread
    from referencing import Registry, Resource
    from backend import ui_projection_api as api
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"type":"integer"}')

        def log_message(self, *_args):
            pass

    fixture = tmp_path / "reference.json"
    fixture.write_text('{"type":"integer"}')
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        for reference in (f"http://127.0.0.1:{server.server_port}/schema", fixture.as_uri()):
            for factory in (api._compiled_validator, lambda schema: api._NativeTransportValidator(schema, "view")):
                unknown = factory({"$ref": reference})
                with pytest.raises(Exception, match="Unresolvable"):
                    unknown.validate(1)
                mutated = factory(deepcopy(api._VIEW_SCHEMA))
                mutated.schema.clear()
                mutated.schema["$ref"] = reference
                with pytest.raises(Exception, match="Unresolvable"):
                    mutated.validate(1)

                def retrieve(uri):
                    pytest.fail(f"custom retrieval invoked: {uri}")

                registry = Registry(retrieve=retrieve)
                evolved = factory({"type": "integer"}).evolve(
                    schema={"$ref": reference}, registry=registry, _resolver=None,
                )
                with pytest.raises(Exception, match="Unresolvable"):
                    evolved.validate(1)
                resolved = factory({"type": "integer"}).evolve(
                    schema={"$ref": reference}, _resolver=registry.resolver(),
                )
                with pytest.raises(Exception, match="Unresolvable"):
                    resolved.validate(1)
                from jsonschema.validators import _RefResolver
                legacy = _RefResolver.from_schema({"$ref": reference}, handlers={"http": retrieve, "file": retrieve})
                legacy_evolved = factory({"type": "integer"}).evolve(schema={"$ref": reference}, resolver=legacy)
                with pytest.raises(Exception):
                    legacy_evolved.validate(1)
        resource = Resource.from_contents({"$schema": Draft202012Validator.META_SCHEMA["$id"], "type": "integer"})
        registered = api._NativeTransportValidator({}, "view").evolve(
            schema={"$ref": "urn:local"}, registry=Registry().with_resource("urn:local", resource), _resolver=None,
        )
        assert registered.is_valid(1) and not registered.is_valid("1")
        assert requests == []
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


@pytest.mark.parametrize("installed", ["4.25.0", "4.26.1", "4.27.0", None])
def test_private_legacy_resolver_version_guard_precedes_import_and_use(monkeypatch, installed):
    import builtins
    from backend import ui_projection_api as api
    assert api._LEGACY_RESOLVER_REVIEWED_VERSION == "4.26.0"
    original_import = builtins.__import__

    def forbidden_private_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "jsonschema.validators" and "_RefResolver" in fromlist:
            pytest.fail("unaudited private resolver was imported")
        return original_import(name, globals, locals, fromlist, level)

    def observed_version(name):
        assert name == "jsonschema"
        if installed is None:
            raise api.PackageNotFoundError(name)
        return installed

    monkeypatch.setattr(builtins, "__import__", forbidden_private_import)
    monkeypatch.setattr(api, "version", observed_version)
    with pytest.raises(RuntimeError, match=r"reviewed jsonschema 4\.26\.0"):
        api._offline_context({"resolver": object()})


@pytest.mark.parametrize("failure", ["missing", "import_failure"])
def test_private_legacy_resolver_missing_interface_refuses(monkeypatch, failure):
    import builtins
    import jsonschema.validators as validators_module
    from backend import ui_projection_api as api
    assert api.version("jsonschema") == "4.26.0"
    if failure == "missing":
        monkeypatch.delattr(validators_module, "_RefResolver")
    else:
        original_import = builtins.__import__

        def unavailable(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "jsonschema.validators" and "_RefResolver" in fromlist:
                raise ImportError("private import sentinel")
            return original_import(name, globals, locals, fromlist, level)

        monkeypatch.setattr(builtins, "__import__", unavailable)
    with pytest.raises(RuntimeError, match="legacy resolver is unavailable") as result:
        api._reviewed_legacy_resolver_type()
    assert result.value.__suppress_context__


def test_reviewed_legacy_resolver_retains_in_memory_context_without_retrieval():
    from backend import ui_projection_api as api
    assert api.version("jsonschema") == "4.26.0"
    legacy_type = api._reviewed_legacy_resolver_type()
    legacy = legacy_type.from_schema({"$defs": {"Leaf": {"type": "integer"}}})
    validator = api._compiled_validator({"$ref": "#/$defs/Leaf"}).evolve(resolver=legacy)
    assert validator.is_valid(1) and not validator.is_valid("1")
    assert validator._ref_resolver is not legacy
    assert validator._ref_resolver.store == legacy.store


def test_native_smoke_proof_is_request_local_and_requires_complete_validation(tmp_path, monkeypatch, sample):
    from backend import ui_projection_api as api
    monkeypatch.setenv("ASSESSHUB_NATIVE_VALIDATION_SMOKE", "1")
    monkeypatch.setenv("ASSESSHUB_INSTANCE_NONCE", "native-smoke-test")
    monkeypatch.delenv("ASSESSHUB_TOKEN", raising=False)
    app = create_app(db_path=str(tmp_path / "native-smoke.db"), scope_dist_dir=None)
    proof = "x-atlas-native-validation"
    headers = {"X-Atlas-Native-Smoke-Nonce": "native-smoke-test"}
    with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50000),
                    raise_server_exceptions=False) as client:
        sid = seed(client, sample)
        path = url(sid)
        assert client.get(path, headers=headers).headers[proof] == "jsonschema-rs/0.58.5"
        assert client.get(url(sid, "findings") + "/lists?pointer=/rows&limit=200", headers=headers).headers[proof] == "jsonschema-rs/0.58.5"
        assert proof not in client.get(path).headers
        assert proof not in client.get(path, headers={"X-Atlas-Native-Smoke-Nonce": "wrong"}).headers
        assert proof not in client.get(path, headers=[*headers.items(), *headers.items()]).headers
        with ThreadPoolExecutor(max_workers=4) as pool:
            modes = [True, False] * 6
            responses = list(pool.map(lambda mode: client.get(path, headers=headers if mode else {}), modes))
        assert [proof in response.headers for response in responses] == modes
        native = api._VALIDATORS["view"]

        class Declined:
            def is_valid(self, _instance):
                return False

        with monkeypatch.context() as changed:
            changed.setattr(native, "_NativeTransportValidator__native", Declined())
            response = client.get(path, headers=headers)
            assert response.status_code == 200 and proof not in response.headers
        original = api._page_view

        def malformed_page(*args):
            payload = original(*args)
            payload["axes"]["page"]["has_more"] = not payload["axes"]["page"]["has_more"]
            return payload

        monkeypatch.setattr(api, "_page_view", malformed_page)
        response = client.get(path, headers=headers)
        assert response.status_code == 500 and proof not in response.headers
    monkeypatch.delenv("ASSESSHUB_NATIVE_VALIDATION_SMOKE")
    with TestClient(create_app(db_path=str(tmp_path / "normal.db"), scope_dist_dir=None),
                    base_url="http://localhost", client=("127.0.0.1", 50000)) as normal:
        monkeypatch.setattr(api, "_page_view", original)
        assert proof not in normal.get(url(seed(normal, sample)), headers=headers).headers


def path_url(sid):
    return url(sid, "topology") + "/path"


_PATH_QUERY = {"src_ip": "192.0.2.1", "dst_ip": "198.51.100.9"}


def test_path_transport_preserves_owner_result_and_topology_context(client, sample):
    sid = seed(client, sample)
    response = client.get(path_url(sid), params=_PATH_QUERY)
    assert response.status_code == 200, response.text[:200]
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    topology = client.get(url(sid, "topology")).json()
    raw, _ = client.app.state.store.get_snapshot_blob(sid)
    expected = owner.project_path(engine.bind_ui_projection_snapshot(raw), **_PATH_QUERY)
    assert body["view"] == "path"
    assert body["payload"] == expected["path"]
    assert body["engine"] == expected["engine"] == topology["engine"]
    assert body["identity"] == topology["identity"]
    assert body["limitations"] == topology["limitations"]
    assert body["projection_schema"] == expected["schema"]
    assert "X-Atlas-Native-Validation" not in response.headers


@pytest.mark.parametrize("params", [
    {}, {"src_ip": "192.0.2.1"}, {"dst_ip": "198.51.100.9"},
    {"src_ip": "", "dst_ip": "198.51.100.9"},
    {"src_ip": "a" * 129, "dst_ip": "198.51.100.9"},
    {"src_ip": "192.0.2.1", "dst_ip": "a" * 129},
])
def test_path_query_bounds_precede_store_access(client, monkeypatch, params):
    def forbidden(*_args):
        pytest.fail("Malformed query reached the store")
    monkeypatch.setattr(client.app.state.store, "get_snapshot_blob", forbidden)
    assert client.get(path_url(991), params=params).status_code == 422


@pytest.mark.parametrize("view", ["topology", "topology/path"])
@pytest.mark.parametrize("failure", ["deleted", "bytes_changed", "authority_changed"])
def test_topology_and_path_reread_authority_after_warming(client, view, failure):
    sid = seed(client)
    path = url(sid, view)
    params = _PATH_QUERY if view.endswith("/path") else {}
    assert client.get(path, params=params).status_code == 200
    store = client.app.state.store
    if failure == "deleted":
        assert store.delete_snapshot(sid)
        expected = 404
    else:
        with store._lock:
            if failure == "bytes_changed":
                store._conn.execute("UPDATE snapshots SET snapshot_json = ? WHERE id = ?", ('{"changed":true}', sid))
            else:
                store._conn.execute("DELETE FROM snapshot_authority WHERE snapshot_id = ?", (sid,))
            store._conn.commit()
        expected = 409
    response = client.get(path, params=params)
    assert response.status_code == expected
    assert "payload" not in response.json()


def test_path_queries_are_not_cached_and_cannot_poison_private_source(client, monkeypatch):
    sid = seed(client, {"devices": {"edge": {}}, "script_version": "3.23.0"})
    original = engine.ui_projection_path
    inputs, outputs = [], []
    def retained(snapshot, src_ip, dst_ip):
        inputs.append(snapshot)
        result = original(snapshot, src_ip, dst_ip)
        outputs.append(result)
        return result
    monkeypatch.setattr(engine, "ui_projection_path", retained)
    first = client.get(path_url(sid), params=_PATH_QUERY)
    assert first.status_code == 200
    pristine = deepcopy(inputs[0])
    inputs[0]["script_version"] = "changed retained query input"
    outputs[0]["path"]["query"]["src_ip"] = "changed retained result"
    second = client.get(path_url(sid), params=_PATH_QUERY)
    assert second.status_code == 200 and second.content == first.content
    assert len(inputs) == 2 and inputs[1] == pristine
    assert inputs[1] is not inputs[0]


def test_cached_views_finish_while_path_computation_is_held(client, monkeypatch):
    sid = seed(client)
    assert client.get(url(sid, "topology")).status_code == 200
    original = engine.ui_projection_path
    entered, release = Event(), Event()
    def held(*args):
        entered.set()
        assert release.wait(20)
        return original(*args)
    monkeypatch.setattr(engine, "ui_projection_path", held)
    with ThreadPoolExecutor(max_workers=3) as pool:
        pending = pool.submit(client.get, path_url(sid), params=_PATH_QUERY)
        try:
            assert entered.wait(20)
            for view in ("overview", "topology"):
                assert pool.submit(client.get, url(sid, view)).result(timeout=10).status_code == 200
        finally:
            release.set()
        assert pending.result(timeout=20).status_code == 200


def test_path_admits_complete_source_before_query_selection(client, monkeypatch):
    sid = seed(client)
    document = owner.project({})
    document["overview"]["facts"]["avg_health"]["fact"]["value"] = float("nan")
    monkeypatch.setattr(engine, "ui_projection", lambda *_args: document)
    def forbidden(*_args):
        pytest.fail("Path ran before invalid source admission was refused")
    monkeypatch.setattr(engine, "ui_projection_path", forbidden)
    transport = TestClient(client.app, base_url="http://localhost", client=("127.0.0.1", 50000),
                           raise_server_exceptions=False)
    try:
        response = transport.get(path_url(sid), params=_PATH_QUERY)
        assert response.status_code == 500 and response.content == b"Internal Server Error"
    finally:
        transport.close()


@pytest.mark.parametrize("corruption", ["query", "engine", "extra", "nan", "tuple"])
def test_path_refuses_corrupt_or_wrong_context_results_and_retries(client, monkeypatch, corruption):
    sid = seed(client)
    original = engine.ui_projection_path
    def corrupt(*args):
        result = original(*args)
        if corruption == "query":
            result["path"]["query"]["src_ip"] = "203.0.113.10"
        elif corruption == "engine":
            result["engine"]["code_schema_version"] = "different engine"
        elif corruption == "extra":
            result["path"]["unowned"] = True
        elif corruption == "nan":
            result["path"]["result"]["value"] = float("nan")
        else:
            result["path"]["hop_evidence"]["items"] = ()
        return result
    transport = TestClient(client.app, base_url="http://localhost", client=("127.0.0.1", 50000),
                           raise_server_exceptions=False)
    try:
        with monkeypatch.context() as changed:
            changed.setattr(engine, "ui_projection_path", corrupt)
            refused = transport.get(path_url(sid), params=_PATH_QUERY)
            assert refused.status_code == 500 and refused.content == b"Internal Server Error"
        accepted = transport.get(path_url(sid), params=_PATH_QUERY)
        assert accepted.status_code == 200
        assert accepted.json()["payload"]["query"]["src_ip"] == _PATH_QUERY["src_ip"]
    finally:
        transport.close()


def test_path_response_has_its_own_complete_python_validation(client):
    from backend import ui_projection_api as api
    from pydantic import ValidationError as ModelValidationError
    sid = seed(client)
    body = client.get(path_url(sid), params=_PATH_QUERY).json()
    trace = {"native": True, "complete": True}
    token = api._NATIVE_SMOKE_TRACE.set(trace)
    try:
        assert api.UiProjectionPathResponse.model_validate(body).root == body
        assert trace == {"native": False, "complete": False}
        forged = deepcopy(body)
        forged["payload"]["query"]["disclose"] = False
        with pytest.raises(ModelValidationError):
            api.UiProjectionPathResponse.model_validate(forged)
    finally:
        api._NATIVE_SMOKE_TRACE.reset(token)


def test_reaudited_topology_lists_use_native_and_float_views_stay_python(tmp_path, sample, monkeypatch):
    monkeypatch.setenv("ASSESSHUB_NATIVE_VALIDATION_SMOKE", "1")
    monkeypatch.setenv("ASSESSHUB_INSTANCE_NONCE", "topology-schema-delta-proof")
    headers = {"X-Atlas-Native-Smoke-Nonce": "topology-schema-delta-proof"}
    proof = "X-Atlas-Native-Validation"
    app = create_app(db_path=str(tmp_path / "native-topology.db"), scope_dist_dir=None)
    with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50000)) as client:
        sid = seed(client, sample)
        for pointer in ("/nodes", "/cables", "/failure_impact", "/source_addresses"):
            response = client.get(url(sid, "topology") + "/lists", params={"pointer": pointer, "limit": 50},
                                  headers=headers)
            assert response.status_code == 200
            assert response.headers.get(proof) == "jsonschema-rs/0.58.5", pointer
        topology = client.get(url(sid, "topology"), params={"limit": 200}, headers=headers)
        structural = client.get(url(sid, "topology") + "/lists", params={"pointer": "/structural_links"},
                                headers=headers)
        assert topology.status_code == structural.status_code == 200
        assert proof not in topology.headers and proof not in structural.headers
        path = client.get(path_url(sid), params=_PATH_QUERY, headers=headers)
        assert path.status_code == 200 and proof not in path.headers


def test_owner_vocab_stays_in_engine_documents_and_out_of_every_transport_envelope(client, sample):
    """G43: the constant vocab block is an engine-document member only. Every view, path and list envelope keeps
    exactly its pre-G43 key set, which Atlas Scope's contract-mode loader requires, and refuses a vocab member.
    Exposing the block through the transport is a recorded follow-up, not an envelope member."""
    from backend import ui_projection_api as api
    from pydantic import ValidationError as ModelValidationError
    sid = seed(client, sample)
    host = next(iter(sample["devices"]))
    vocab = owner.project(sample)["vocab"]
    assert vocab == owner.project({})["vocab"] == owner.project_device(sample, host)["vocab"]
    raw, _ = client.app.state.store.get_snapshot_blob(sid)
    assert vocab == owner.project_path(engine.bind_ui_projection_snapshot(raw), **_PATH_QUERY)["vocab"]
    envelope = {"schema", "projection_schema", "identity", "view", "engine", "limitations"}
    bodies = {}
    for view in api.VIEWS:
        params = {"limit": 2, **({"host": host} if view == "device" else {})}
        response = client.get(url(sid, view), params=params)
        assert response.status_code == 200, response.text[:200]
        bodies[view] = response.json()
        assert set(bodies[view]) == envelope | {"payload"}, view
    path = client.get(path_url(sid), params=_PATH_QUERY)
    assert path.status_code == 200, path.text[:200]
    assert set(path.json()) == envelope | {"payload"}
    pointer = next(iter(api.LIST_CATALOG["findings"]))
    listed = client.get(url(sid, "findings") + "/lists", params={"pointer": pointer, "limit": 2})
    assert listed.status_code == 200 and set(listed.json()) == envelope | {"list"}
    assert all("vocab" not in branch["properties"] for branch in api._VIEW_SCHEMA["oneOf"])
    assert all("vocab" not in branch["properties"] for branch in api._LIST_SCHEMA["oneOf"])
    assert "vocab" not in api._PATH_SCHEMA["properties"]
    with pytest.raises(ModelValidationError):
        api.UiProjectionViewResponse.model_validate({**bodies["overview"], "vocab": deepcopy(vocab)})
    with pytest.raises(ModelValidationError):
        api.UiProjectionPathResponse.model_validate({**path.json(), "vocab": deepcopy(vocab)})
