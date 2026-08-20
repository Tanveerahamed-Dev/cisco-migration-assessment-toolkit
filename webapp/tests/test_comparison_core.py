"""Parity contract for the shared canonical comparison composer."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient


_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "webapp"))

from backend import engine  # noqa: E402
from backend.app import create_app  # noqa: E402
from cisco_toolkit.comparison import compare_bound_pair as compose_bound_pair  # noqa: E402


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def test_core_web_compare_and_execution_store_the_exact_same_comparison(tmp_path):
    app = create_app(db_path=str(tmp_path / "comparison-core.db"))
    raw = (_REPO / "tests" / "golden" / "snapshot.json").read_bytes()

    with TestClient(app, base_url="http://localhost") as client:
        campaign = client.post(
            "/api/campaigns",
            json={"name": "core parity", "engagement_id": "ENG-CORE-PARITY"},
        )
        assert campaign.status_code == 201, campaign.text
        campaign_id = campaign.json()["id"]

        uploaded = client.post(
            f"/api/campaigns/{campaign_id}/snapshots",
            files={"file": ("before.json", raw, "application/json")},
            data={"label": "before"},
        )
        assert uploaded.status_code == 201, uploaded.text
        before_id = uploaded.json()["id"]

        started = client.post(
            f"/api/snapshots/{before_id}/executions",
            json={"label": "core parity", "operator": "test"},
        )
        assert started.status_code == 201, started.text
        execution_id = started.json()["id"]
        actioned = started.json()
        for wave in list(actioned["waves"]):
            for index, step in enumerate(list(wave["steps"])):
                if step["status"] == "pending":
                    response = client.post(
                        f"/api/executions/{execution_id}/step",
                        json={"wave": wave["group"], "index": index, "status": "done"},
                    )
                    assert response.status_code == 200, response.text
                    actioned = response.json()
        action_times = [
            datetime.fromisoformat(step["at"])
            for wave in actioned["waves"]
            for step in wave["steps"]
        ]
        assert action_times

        after_snapshot = json.loads(raw)
        after_snapshot["collected_at"] = (
            max(action_times) + timedelta(microseconds=1)
        ).isoformat()
        after_raw = json.dumps(after_snapshot, separators=(",", ":"), allow_nan=False).encode()
        uploaded = client.post(
            f"/api/campaigns/{campaign_id}/snapshots",
            files={"file": ("after.json", after_raw, "application/json")},
            data={"label": "after"},
        )
        assert uploaded.status_code == 201, uploaded.text
        after_id = uploaded.json()["id"]

        before_pair = app.state.store.get_bound_snapshot(before_id)
        after_pair = app.state.store.get_bound_snapshot(after_id)
        assert before_pair is not None and after_pair is not None
        before, before_binding = before_pair
        after, after_binding = after_pair

        direct = compose_bound_pair(
            before,
            after,
            before_binding=before_binding,
            after_binding=after_binding,
        )
        adapted = engine.compare_bound_pair(
            before,
            after,
            before_binding=before_binding,
            after_binding=after_binding,
        )
        compared = client.post(
            "/api/compare", json={"old_id": before_id, "new_id": after_id}
        )
        assert compared.status_code == 200, compared.text
        api_comparison = compared.json()

        assert adapted == direct
        direct_wire = json.loads(_canonical_bytes(direct))
        assert api_comparison == direct_wire
        assert _canonical_bytes(adapted) == _canonical_bytes(direct)
        assert _canonical_bytes(api_comparison) == _canonical_bytes(direct)

        execution_compare = client.post(
            f"/api/executions/{execution_id}/compare",
            json={"after_snapshot_id": after_id},
        )
        assert execution_compare.status_code == 200, execution_compare.text
        stored_comparison = execution_compare.json()["comparison_receipts"][-1]["receipt"][
            "comparison"
        ]

        assert stored_comparison == direct_wire
        assert stored_comparison == api_comparison
        assert _canonical_bytes(stored_comparison) == _canonical_bytes(direct)
