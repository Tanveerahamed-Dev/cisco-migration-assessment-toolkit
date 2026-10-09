"""The portable HTTP smoke proves the frozen owner-validated projection, not just startup."""

from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path

import pytest

from cisco_toolkit.protocol_assurance import bind_snapshot_json_bytes
from cisco_toolkit.ui_projection import project
from portable import build_atlas
from webapp.backend.ui_projection_api import _page, _page_view


@pytest.fixture(scope="module")
def projection_responses():
    snapshot = json.loads((Path(__file__).resolve().parents[1] / "webapp/sample_data/sample_fleet.snapshot.json").read_text(encoding="utf-8"))
    raw = json.dumps(snapshot, separators=(",", ":")).encode()
    # The served engine block names the exact served bytes (G41), so the owner expectation binds those bytes too.
    source = project(bind_snapshot_json_bytes(raw))
    assert len(source["overview"]["axes"]["items"]) > 1
    assert source["engine"]["snapshot_sha256"]["state"] == source["engine"]["snapshot_bytes"]["state"] == "published"
    assert source["engine"]["snapshot_sha256"]["value"] == "sha256:" + hashlib.sha256(raw).hexdigest()
    assert source["engine"]["snapshot_bytes"]["value"] == len(raw)
    context = {"schema": "ui_projection_transport/1", "projection_schema": source["schema"],
               "identity": {"snapshot_id": 7, "sha256": "sha256:" + hashlib.sha256(raw).hexdigest(),
                            "bytes": len(raw), "digest_form": "assesshub-store-blob"},
               "view": "overview", "engine": source["engine"], "limitations": source["trust"]["limitations"]}
    # Exercise the real transport adapter against the independently built smoke
    # expectation, so a shared omission of a newly pageable list cannot pass.
    overview = _page_view(source["overview"], "overview", 1)
    return raw, context, overview, _page(source["overview"]["axes"], "/axes", 1, 1)


def run_projection_smoke(monkeypatch, projection_responses, mutate=None):
    raw, context, overview, later = deepcopy(projection_responses)
    responses = [
        [{"snapshot": {"id": 7}}, {}],
        [raw, {"x-snapshot-sha256": hashlib.sha256(raw).hexdigest(), "x-snapshot-bytes": str(len(raw)),
               "x-snapshot-digest-form": "assesshub-store-blob", "cache-control": "no-store"}],
        [{**context, "payload": overview}, {"cache-control": "no-store",
                                            "x-atlas-native-validation": "jsonschema-rs/0.58.5"}],
        [{**context, "list": later}, {"cache-control": "no-store",
                                      "x-atlas-native-validation": "jsonschema-rs/0.58.5"}],
    ]
    if mutate:
        mutate(responses)
    calls = []
    def request(req, *, timeout):
        calls.append((req.full_url, req.get_method(), dict(req.header_items()), timeout))
        body, headers = responses[len(calls) - 1]
        result = io.BytesIO(body if isinstance(body, bytes) else json.dumps(body).encode())
        result.status = 200
        result.headers = headers
        return result
    monkeypatch.setattr(build_atlas.urllib.request, "urlopen", request)
    build_atlas._smoke_ui_projection("http://127.0.0.1:8479", "one-use-smoke-nonce")
    return calls


def test_projection_smoke_checks_exact_blob_and_owner_rows_on_two_pages(monkeypatch, projection_responses):
    groups = projection_responses[2]["readiness"]["groups"]
    assert groups["pointer"] == "/readiness/groups"
    assert groups["page"]["total"] > groups["page"]["returned"] == 1
    assert groups["page"]["has_more"] is True
    calls = run_projection_smoke(monkeypatch, projection_responses)
    assert [call[:2] for call in calls] == [
        ("http://127.0.0.1:8479/api/demo/seed", "POST"),
        ("http://127.0.0.1:8479/api/snapshots/7/raw", "GET"),
        ("http://127.0.0.1:8479/api/snapshots/7/ui-projection/overview?limit=1", "GET"),
        ("http://127.0.0.1:8479/api/snapshots/7/ui-projection/overview/lists?pointer=/axes&offset=1&limit=1", "GET"),
    ]
    assert all(call[2]["Origin"] == "http://127.0.0.1:8479" for call in calls)
    assert all(call[2]["X-atlas-native-smoke-nonce"] == "one-use-smoke-nonce" for call in calls)


def test_projection_smoke_requires_nonce_before_any_request(monkeypatch):
    def refuse(*_args, **_kwargs):
        pytest.fail("missing nonce must fail before HTTP")
    monkeypatch.setattr(build_atlas.urllib.request, "urlopen", refuse)
    with pytest.raises(SystemExit, match="frozen UI projection smoke failed"):
        build_atlas._smoke_ui_projection("http://127.0.0.1:8479", "")


@pytest.mark.parametrize("mutation", [
    "raw_digest", "raw_bytes", "raw_form", "view_binding", "view_schema", "owner_value",
    "source_state", "source_metadata", "page_total", "page_items", "later_rows", "cache",
    "native_missing_view", "native_missing_list", "native_wrong_version", "native_stock",
    "native_previous_version_view", "native_previous_version_list",
    "engine_source_digest", "engine_source_bytes", "engine_source_withheld", "list_engine_source_digest",
])
def test_projection_smoke_refuses_drift(monkeypatch, projection_responses, mutation):
    def mutate(responses):
        headers = responses[1][1]
        body = responses[2][0]
        axes = body["payload"]["axes"]
        source = body["engine"]
        if mutation == "raw_digest": headers["x-snapshot-sha256"] = "0" * 64
        elif mutation == "raw_bytes": headers["x-snapshot-bytes"] = "0"
        elif mutation == "raw_form": headers["x-snapshot-digest-form"] = "invented"
        elif mutation == "view_binding": body["identity"]["sha256"] = "sha256:" + "0" * 64
        elif mutation == "view_schema": body["projection_schema"] = "invented"
        elif mutation == "owner_value": body["payload"]["posture_statement"] = {"state": "published", "value": "invented"}
        elif mutation == "source_state": axes["source_list"]["state"] = "invented"
        elif mutation == "source_metadata": axes["source_list"]["invented"] = True
        elif mutation == "page_total": axes["page"]["total"] = 1
        elif mutation == "page_items": axes["page"]["items"] = []
        elif mutation == "later_rows": responses[3][0]["list"]["page"]["items"] = axes["page"]["items"]
        elif mutation == "cache": responses[2][1]["cache-control"] = "public"
        elif mutation == "native_missing_view": responses[2][1].pop("x-atlas-native-validation")
        elif mutation == "native_missing_list": responses[3][1].pop("x-atlas-native-validation")
        elif mutation == "native_wrong_version": responses[2][1]["x-atlas-native-validation"] = "jsonschema-rs/0.58.3"
        elif mutation == "native_previous_version_view": responses[2][1]["x-atlas-native-validation"] = "jsonschema-rs/0.58.4"
        elif mutation == "native_previous_version_list": responses[3][1]["x-atlas-native-validation"] = "jsonschema-rs/0.58.4"
        elif mutation == "native_stock": responses[2][1]["x-atlas-native-validation"] = "jsonschema/4.26.0"
        # G41: a served engine block naming other bytes, or none, is not the owner's block over the served bytes.
        elif mutation == "engine_source_digest": source["snapshot_sha256"]["value"] = "sha256:" + "0" * 64
        elif mutation == "engine_source_bytes": source["snapshot_bytes"]["value"] += 1
        elif mutation == "engine_source_withheld":
            source["snapshot_sha256"] = {"state": "not_collected", "value": None, "subject": None, "refs": [],
                                         "basis": source["snapshot_sha256"]["basis"], "reason": "withheld"}
        elif mutation == "list_engine_source_digest":
            # The view and list contexts share one engine object; change only the later page's copy.
            listed = deepcopy(responses[3][0]["engine"])
            listed["snapshot_sha256"]["value"] = "sha256:" + "0" * 64
            responses[3][0]["engine"] = listed
    with pytest.raises(SystemExit, match="frozen UI projection smoke failed"):
        run_projection_smoke(monkeypatch, projection_responses, mutate)


@pytest.mark.parametrize("mutation", [
    "unpaged", "pointer", "row_value", "row_pointer", "source_state", "source_metadata",
    "offset", "limit", "returned", "total", "has_more", "items", "extra_row",
])
def test_projection_smoke_refuses_readiness_page_drift(monkeypatch, projection_responses, mutation):
    def mutate(responses):
        readiness = responses[2][0]["payload"]["readiness"]
        groups = readiness["groups"]
        page = groups["page"]
        if mutation == "unpaged":
            readiness["groups"] = {**groups["source_list"], "items": page["items"]}
        elif mutation == "pointer": groups["pointer"] = "/axes"
        elif mutation == "row_value": page["items"][0]["group"]["value"] = "invented"
        elif mutation == "row_pointer": page["items"][0]["pointer"] = "/migration_readiness/999"
        elif mutation == "source_state": groups["source_list"]["state"] = "invented"
        elif mutation == "source_metadata": groups["source_list"]["invented"] = True
        elif mutation == "offset": page["offset"] = 1
        elif mutation == "limit": page["limit"] = 2
        elif mutation == "returned": page["returned"] = 0
        elif mutation == "total": page["total"] += 1
        elif mutation == "has_more": page["has_more"] = False
        elif mutation == "items": page["items"] = []
        elif mutation == "extra_row": page["items"].append(deepcopy(page["items"][0]))
    with pytest.raises(SystemExit, match="frozen UI projection smoke failed"):
        run_projection_smoke(monkeypatch, projection_responses, mutate)
