"""Source-bound single-snapshot Protocol Assurance receipt and export contracts."""

from __future__ import annotations

import hashlib
import io
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app import create_app  # noqa: E402
from backend.protocol_portfolio import (  # noqa: E402
    SUBJECT_RENDER_CAP,
    build_protocol_single_snapshot_bundle,
)
from cisco_toolkit.protocol_assurance import canonical_sha256  # noqa: E402
from tests.test_multichassis_snapshot_reconciliation import _persisted_pair  # noqa: E402


@pytest.fixture()
def client(tmp_path):
    app = create_app(db_path=str(tmp_path / "portfolio.db"))
    with TestClient(app, base_url="http://localhost") as value:
        yield value


def _campaign(client: TestClient) -> int:
    response = client.post("/api/campaigns", json={"name": "protocol portfolio"})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _upload(client: TestClient, snapshot: dict, *, pretty: bool = False) -> tuple[int, bytes]:
    campaign_id = _campaign(client)
    raw = json.dumps(snapshot, indent=2 if pretty else None).encode("utf-8")
    response = client.post(
        f"/api/campaigns/{campaign_id}/snapshots",
        files={"file": ("snapshot.json", raw, "application/json")},
        data={"label": "portfolio source"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"], raw


def _minimal(**extra) -> dict:
    return {"script_version": "portfolio-test/1", "devices": {"sw1": {}}, **extra}


def _docx_text(payload: bytes) -> str:
    from docx import Document

    document = Document(io.BytesIO(payload))
    parts = [paragraph.text for paragraph in document.paragraphs]
    parts.extend(
        cell.text
        for table in document.tables
        for row in table.rows
        for cell in row.cells
    )
    return "\n".join(parts)


def _embedded_protocol_assurance(html: str) -> dict:
    encoded = html.split("const EMBEDDED_PROTOCOL_ASSURANCE=", 1)[1].split(
        ";\nconst EMBEDDED_SNAPSHOT=", 1
    )[0]
    return json.loads(encoded)


def test_single_snapshot_receipt_binds_exact_persisted_blob_and_script_owner(client):
    snapshot_id, upload_bytes = _upload(client, _minimal(), pretty=True)
    response = client.get(f"/api/snapshots/{snapshot_id}/section/protocol_assurance")
    assert response.status_code == 200, response.text
    receipt = response.json()["data"]["receipt"]

    store = client.app.state.store
    with store._lock:
        row = store._conn.execute(
            "SELECT CAST(snapshot_json AS BLOB) AS blob FROM snapshots WHERE id=?",
            (snapshot_id,),
        ).fetchone()
    persisted = bytes(row["blob"])

    source = receipt["source_binding"]
    assert receipt["schema"] == "protocol_single_snapshot_receipt/1"
    assert receipt["owns_score"] is False and receipt["owns_verdict"] is False
    assert receipt["custody_status"] == "bound"
    assert source["source"] == "persisted snapshots.snapshot_json blob"
    assert source["bytes"] == len(persisted)
    assert source["sha256"] == "sha256:" + hashlib.sha256(persisted).hexdigest()
    assert persisted != upload_bytes  # upload bytes are normalized/stamped and are not retained
    assert receipt["script_owner"] == {
        "source": "snapshot.script_version + snapshots.script_version column",
        "snapshot_value": "portfolio-test/1",
        "stored_value": "portfolio-test/1",
        "status": "bound",
    }
    assert "does not retain or claim the original upload bytes" in receipt["custody_note"]
    unsigned = dict(receipt)
    claimed = unsigned.pop("receipt_sha256")
    assert claimed == canonical_sha256(unsigned)

    meta = client.get(f"/api/snapshots/{snapshot_id}").json()
    section = next(row for row in meta["summary"]["sections"] if row["key"] == "protocol_assurance")
    assert section["label"] == "Protocol Assurance"
    assert section["count"] == receipt["summary"]["n_families"] == len(receipt["support_profiles"])


def test_offline_explorer_embeds_the_same_bound_receipt_and_names_complete_export(client):
    snapshot_id, _ = _upload(client, _minimal(), pretty=True)
    receipt = client.get(
        f"/api/snapshots/{snapshot_id}/section/protocol_assurance"
    ).json()["data"]["receipt"]

    response = client.get(f"/api/snapshots/{snapshot_id}/explorer")
    assert response.status_code == 200, response.text
    surface = _embedded_protocol_assurance(response.text)

    assert surface["receipt_valid"] is True
    assert surface["status"] == "BOUND"
    assert surface["source_binding"] == receipt["source_binding"]
    assert surface["receipt_sha256"] == receipt["receipt_sha256"]
    assert surface["complete_export"]["sha256"] == receipt["complete_export"]["sha256"]
    assert surface["complete_export"]["reference"] == (
        f"/api/snapshots/{snapshot_id}/protocol-assurance/export"
    )
    assert surface["subject_cap"] == {
        field: sum(family["subjects"][field] for family in receipt["families"])
        for field in ("total", "rendered", "omitted")
    }


def test_missing_and_malformed_family_evidence_remain_neutral_not_verified(client):
    snapshot_id, _ = _upload(
        client,
        _minimal(bgp_configured_peer_baseline="malformed", protocol_assessability=5),
    )
    response = client.get(f"/api/snapshots/{snapshot_id}/section/protocol_assurance")
    assert response.status_code == 200, response.text
    receipt = response.json()["data"]["receipt"]
    families = {row["family"]: row for row in receipt["families"]}

    bgp = families["bgp_configured_peer"]
    assert bgp["evidence_status"] == "not_verified"
    assert bgp["subject_total"] == 0
    assert bgp["subjects"] == {"total": 0, "rendered": 0, "omitted": 0, "rows": []}
    assert "malformed" in bgp["status_reason"].lower() or "invalid" in bgp["status_reason"].lower()

    # No family is upgraded merely because its executable support profile exists.
    assert all(row["evidence_status"] != "observed" for row in receipt["families"])
    assert receipt["summary"]["by_evidence_status"]["not_verified"] >= 1
    assert all(profile["implementation_state"] == "implemented" for profile in receipt["support_profiles"])


@pytest.mark.parametrize(
    "family",
    [
        "ipv4_routing_adjacency",
        "ipv6_routing_adjacency",
        "bgp_configured_peer",
        "stp_consistency",
        "stp_topology",
        "etherchannel",
        "vtp_safety",
        "fhrp_configured_group",
        "fhrp_redundancy_domain",
    ],
)
@pytest.mark.parametrize(
    "device_roster",
    [{}, {"other-site-reused-domain": {}}],
    ids=("empty-roster", "cross-site-roster"),
)
def test_exact_bound_portfolio_withholds_native_family_on_roster_mismatch(
        client, family, device_roster):
    golden = Path(__file__).resolve().parents[2] / "tests" / "golden" / "snapshot.json"
    snapshot = json.loads(golden.read_text(encoding="utf-8"))
    snapshot["devices"] = device_roster
    snapshot_id, _ = _upload(client, snapshot)

    receipt = client.get(
        f"/api/snapshots/{snapshot_id}/section/protocol_assurance"
    ).json()["data"]["receipt"]
    projected = next(row for row in receipt["families"] if row["family"] == family)

    # Exact storage custody is real, but it cannot repair an owner denominator from another estate.
    assert receipt["custody_status"] == "bound"
    assert projected["evidence_status"] == "not_verified"
    assert projected["subject_total"] == 0
    assert projected["subjects"] == {
        "total": 0, "rendered": 0, "omitted": 0, "rows": [],
    }
    assert "snapshot devices" in projected["status_reason"].lower()


def test_portfolio_rejects_stale_multichassis_baseline_over_truncated_typed_rows(client):
    snapshot = _persisted_pair()
    snapshot["multichassis_lag_typed_observations"]["observations"].pop()
    snapshot_id, _ = _upload(client, snapshot)

    receipt = client.get(
        f"/api/snapshots/{snapshot_id}/section/protocol_assurance"
    ).json()["data"]["receipt"]
    multichassis = next(
        row for row in receipt["families"] if row["family"] == "multichassis_lag"
    )

    assert multichassis["evidence_status"] == "not_verified"
    assert multichassis["subject_total"] == 0
    assert multichassis["subjects"] == {
        "total": 0, "rendered": 0, "omitted": 0, "rows": [],
    }
    assert "typed observation count does not reconcile" in multichassis[
        "status_reason"
    ].lower()


def test_portfolio_owner_withholds_custody_from_a_detached_parsed_snapshot(client):
    snapshot_id, _ = _upload(client, _minimal())
    bound, binding = client.app.state.store.get_bound_snapshot(snapshot_id)
    assert build_protocol_single_snapshot_bundle(bound, binding)["receipt"]["custody_status"] == "bound"

    detached = build_protocol_single_snapshot_bundle(dict(bound), binding)["receipt"]
    assert detached["custody_status"] == "not_verified"
    assert "exact persisted snapshot byte authority is unavailable" in detached["custody_failures"]
    assert all(family["evidence_status"] == "not_verified" for family in detached["families"])


def test_subject_cap_is_disclosed_and_complete_export_is_uncapped(client):
    golden = Path(__file__).resolve().parents[2] / "tests" / "golden" / "snapshot.json"
    snapshot = json.loads(golden.read_text(encoding="utf-8"))
    snapshot["routing_neighbors"] = {
        "core1": {
            "ospf": [
                {
                    "neighbor": f"10.200.{index // 254}.{index % 254 + 1}",
                    "address": f"10.200.{index // 254}.{index % 254 + 1}",
                    "interface": f"Vlan{index + 1}",
                    "state": "FULL/DR",
                }
                for index in range(SUBJECT_RENDER_CAP + 5)
            ],
            "bgp": [],
            "eigrp": [],
        }
    }
    snapshot_id, _ = _upload(client, snapshot)

    section = client.get(f"/api/snapshots/{snapshot_id}/section/protocol_assurance").json()["data"]
    receipt = section["receipt"]
    ipv4 = next(row for row in receipt["families"] if row["family"] == "ipv4_routing_adjacency")
    assert ipv4["subjects"]["total"] == SUBJECT_RENDER_CAP + 5
    assert ipv4["subjects"]["rendered"] == SUBJECT_RENDER_CAP
    assert ipv4["subjects"]["omitted"] == 5
    assert len(ipv4["subjects"]["rows"]) == SUBJECT_RENDER_CAP
    assert section["complete_export"]["url"].endswith(
        f"/snapshots/{snapshot_id}/protocol-assurance/export"
    )

    exported = client.get(section["complete_export"]["url"])
    assert exported.status_code == 200, exported.text
    assert exported.headers["content-disposition"].endswith(
        f'protocol-assurance-snapshot-{snapshot_id}.json"'
    )
    payload = exported.json()
    assert payload["schema"] == "protocol_single_snapshot_export/1"
    complete_ipv4 = next(row for row in payload["families"] if row["family"] == "ipv4_routing_adjacency")
    assert complete_ipv4["subject_total"] == SUBJECT_RENDER_CAP + 5
    assert len(complete_ipv4["subjects"]) == SUBJECT_RENDER_CAP + 5
    assert canonical_sha256(payload) == receipt["complete_export"]["sha256"]
    assert exported.headers["x-atlas-content-sha256"] == receipt["complete_export"]["sha256"]

    document = client.get(f"/api/snapshots/{snapshot_id}/deliverable/nrfu")
    assert document.status_code == 200, document.text
    text = _docx_text(document.content)
    assert f"{SUBJECT_RENDER_CAP} / {SUBJECT_RENDER_CAP + 5} / 5" in text
    totals = {
        field: sum(family["subjects"][field] for family in receipt["families"])
        for field in ("total", "rendered", "omitted")
    }
    assert (
        "Signed receipt payload cap (rendered / total / omitted): "
        f"{totals['rendered']} / {totals['total']} / {totals['omitted']}"
    ) in text
    assert f"subject-detail display is 0 / {totals['total']} / {totals['total']}" in text
    assert receipt["complete_export"]["sha256"] in text
    assert f"all {totals['total']} subject row(s), uncapped" in text


@pytest.mark.parametrize("kind", ["runbook", "mop", "nrfu"])
def test_operator_documents_project_one_source_bound_portfolio_receipt(client, kind):
    snapshot_id, _ = _upload(client, _minimal(generated_at="2026-08-20T00:00:00Z"))
    receipt = client.get(
        f"/api/snapshots/{snapshot_id}/section/protocol_assurance"
    ).json()["data"]["receipt"]

    response = client.get(f"/api/snapshots/{snapshot_id}/deliverable/{kind}")
    assert response.status_code == 200, response.text
    text = _docx_text(response.content)
    totals = {
        field: sum(family["subjects"][field] for family in receipt["families"])
        for field in ("total", "rendered", "omitted")
    }

    assert "protocol_single_snapshot_receipt/1" in text
    assert "owns no score and no verdict" in text
    assert receipt["source_binding"]["sha256"] in text
    assert receipt["receipt_sha256"] in text
    assert receipt["complete_export"]["sha256"] in text
    assert (
        "Signed receipt payload cap (rendered / total / omitted): "
        f"{totals['rendered']} / {totals['total']} / {totals['omitted']}"
    ) in text
    assert f"subject-detail display is 0 / {totals['total']} / {totals['total']}" in text
    assert (
        f"/api/snapshots/{snapshot_id}/protocol-assurance/export"
    ) in text
    assert "This renderer did not hash the parsed snapshot or mint source custody" not in text


@pytest.mark.parametrize("kind", ["runbook", "mop", "nrfu"])
def test_direct_document_renderer_never_mints_receipt_from_snapshot_claims(tmp_path, kind):
    fake_digest = "sha256:" + "f" * 64
    snapshot = _minimal(
        protocol_assurance={"schema": "protocol_single_snapshot_receipt/1", "sha256": fake_digest},
        protocol_single_snapshot_receipt={
            "schema": "protocol_single_snapshot_receipt/1",
            "receipt_sha256": fake_digest,
        },
    )
    output = tmp_path / f"{kind}.docx"
    if kind == "runbook":
        from cisco_toolkit.runbook import write_runbook_docx as writer
    elif kind == "mop":
        from cisco_toolkit.mop import write_mop_docx as writer
    else:
        from backend.nrfu_docx import write_nrfu_docx as writer

    writer(str(output), snapshot, "Detached receipt fixture")
    text = _docx_text(output.read_bytes())
    assert "Source-bound protocol_single_snapshot_receipt/1 unavailable" in text
    assert "This renderer did not hash the parsed snapshot or mint source custody" in text
    assert fake_digest not in text


def test_document_renderer_rejects_a_tampered_portfolio_sidecar(client, tmp_path):
    snapshot_id, _ = _upload(client, _minimal())
    bound, binding = client.app.state.store.get_bound_snapshot(snapshot_id)
    bundle = build_protocol_single_snapshot_bundle(bound, binding)
    original_digest = bundle["receipt"]["receipt_sha256"]
    bundle["receipt"]["source_binding"]["bytes"] += 1

    from backend.nrfu_docx import write_nrfu_docx

    output = tmp_path / "tampered-nrfu.docx"
    write_nrfu_docx(
        str(output),
        bound,
        "Tampered receipt fixture",
        protocol_assurance_bundle=bundle,
    )
    text = _docx_text(output.read_bytes())
    assert "Status: NOT VERIFIED (receipt digest does not reconcile)" in text
    assert original_digest not in text


def test_protocol_assurance_export_404s_for_unknown_snapshot(client):
    assert client.get("/api/snapshots/999999/section/protocol_assurance").status_code == 404
    assert client.get("/api/snapshots/999999/protocol-assurance/export").status_code == 404
