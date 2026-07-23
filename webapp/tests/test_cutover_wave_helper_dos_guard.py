"""Stored-DoS guard: a malformed per-item value INSIDE the cutover wave helpers must not 500 the read route.

Sibling to test_stored_dos_read_route_guard.py (branch fix/webapp-read-route-500-guard), which guarded the
SECTION-level reads in cutover._rows / build_plan. This covers the two REMAINING per-item iterations inside
the wave helpers, which that guard does not reach:
  * cutover._wave_remediation -- ``for it in (items or [])``, where ``items`` is a per-device value taken from
    ``remediation_plan.by_device``; and
  * cutover._wave_validation -- ``for it in (val_by_wave.get(group) or [])``.
Both keep the SECTION (remediation_plan / validation_plan) a well-formed dict, so the section-level guard is
not what's under test -- only the inner value is a truthy NON-list. ``or []`` guards only falsy values, so an
int/str/dict from a malformed --no-collect upload flows into ``for it in ...`` and raises TypeError, which
escapes as an HTTP 500 on GET /api/snapshots/{id}/cutover. The POST is accepted (201) first, so this is a
STORED availability DoS. The fix coerces via summary._as_list (the module's own discipline).
"""
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # make `backend` importable

from backend.app import create_app  # noqa: E402


@pytest.fixture()
def client(tmp_path):
    app = create_app(db_path=str(tmp_path / "test.db"))
    # base_url=localhost so the default Host passes the no-token guard, matching the emulated loopback dev server.
    with TestClient(app, base_url="http://localhost") as c:
        yield c


def _upload(client, snap):
    cid = client.post("/api/campaigns", json={"name": "c"}).json()["id"]
    r = client.post(
        f"/api/campaigns/{cid}/snapshots",
        files={"file": ("s.json", json.dumps(snap).encode(), "application/json")},
        data={"label": "s"},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


_POISON_REMEDIATION = {
    "devices": {"sw1": {}},
    "wave_sequencing": [{"group": "W1", "hard_cutover": ["sw1"]}],
    "remediation_plan": {"by_device": {"sw1": 5}},   # inner per-device value a truthy non-list
}
_POISON_VALIDATION = {
    "devices": {"sw1": {}},
    "wave_sequencing": [{"group": "W1", "hard_cutover": ["sw1"]}],
    "validation_plan": {"by_wave": {"W1": 5}},        # inner per-wave value a truthy non-list
}


@pytest.mark.parametrize(
    "snap",
    [_POISON_REMEDIATION, _POISON_VALIDATION],
    ids=["remediation_by_device_scalar", "validation_by_wave_scalar"],
)
def test_cutover_read_route_survives_truthy_nonlist_wave_helper_value(client, snap):
    """POST the poison (201), then GET the cutover plan: it must render (200), never 500."""
    sid = _upload(client, snap)
    r = client.get(f"/api/snapshots/{sid}/cutover")
    assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text[:200]}"
