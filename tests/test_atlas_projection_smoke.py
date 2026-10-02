"""The portable HTTP smoke proves the frozen owner-validated projection, not just startup."""

from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path

import pytest

from cisco_toolkit.ui_projection import project
from portable import build_atlas


@pytest.fixture(scope="module")
def projection_responses():
    snapshot = json.loads((Path(__file__).resolve().parents[1] / "webapp/sample_data/sample_fleet.snapshot.json").read_text(encoding="utf-8"))
    raw = json.dumps(snapshot, separators=(",", ":")).encode()
    source = project(snapshot)
    assert len(source["overview"]["axes"]["items"]) > 1
    context = {"schema": "ui_projection_transport/1", "projection_schema": source["schema"],
               "identity": {"snapshot_id": 7, "sha256": "sha256:" + hashlib.sha256(raw).hexdigest(),
                            "bytes": len(raw), "digest_form": "assesshub-store-blob"},
               "view": "overview", "engine": source["engine"], "limitations": source["trust"]["limitations"]}
    def page(name, offset):
        value = source["overview"][name]
        selected = value["items"][offset:offset + 1]
        return {"pointer": "/" + name, "source_list": {k: v for k, v in value.items() if k != "items"},
                "page": {"offset": offset, "limit": 1, "returned": len(selected), "total": len(value["items"]),
                         "has_more": offset + len(selected) < len(value["items"]), "items": selected}}
    overview = deepcopy(source["overview"])
    for name in ("axes", "top_gating"):
        overview[name] = page(name, 0)
    return raw, context, overview, page("axes", 1)


def run_projection_smoke(monkeypatch, projection_responses, mutate=None):
    raw, context, overview, later = deepcopy(projection_responses)
    responses = [
        [{"snapshot": {"id": 7}}, {}],
        [raw, {"x-snapshot-sha256": hashlib.sha256(raw).hexdigest(), "x-snapshot-bytes": str(len(raw)),
               "x-snapshot-digest-form": "assesshub-store-blob", "cache-control": "no-store"}],
        [{**context, "payload": overview}, {"cache-control": "no-store"}],
        [{**context, "list": later}, {"cache-control": "no-store"}],
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
    build_atlas._smoke_ui_projection("http://127.0.0.1:8479")
    return calls


def test_projection_smoke_checks_exact_blob_and_owner_rows_on_two_pages(monkeypatch, projection_responses):
    calls = run_projection_smoke(monkeypatch, projection_responses)
    assert [call[:2] for call in calls] == [
        ("http://127.0.0.1:8479/api/demo/seed", "POST"),
        ("http://127.0.0.1:8479/api/snapshots/7/raw", "GET"),
        ("http://127.0.0.1:8479/api/snapshots/7/ui-projection/overview?limit=1", "GET"),
        ("http://127.0.0.1:8479/api/snapshots/7/ui-projection/overview/lists?pointer=/axes&offset=1&limit=1", "GET"),
    ]
    assert all(call[2]["Origin"] == "http://127.0.0.1:8479" for call in calls)


@pytest.mark.parametrize("mutation", [
    "raw_digest", "raw_bytes", "raw_form", "view_binding", "view_schema", "owner_value",
    "source_state", "source_metadata", "page_total", "page_items", "later_rows", "cache",
])
def test_projection_smoke_refuses_drift(monkeypatch, projection_responses, mutation):
    def mutate(responses):
        headers = responses[1][1]
        body = responses[2][0]
        axes = body["payload"]["axes"]
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
    with pytest.raises(SystemExit, match="frozen UI projection smoke failed"):
        run_projection_smoke(monkeypatch, projection_responses, mutate)
