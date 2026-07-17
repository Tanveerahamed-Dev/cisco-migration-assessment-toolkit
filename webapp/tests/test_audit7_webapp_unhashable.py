"""[audit-7 webapp] The dict-poison UNHASHABLE class (tests/test_audit7_totality.py) driven through the ACTUAL
unauthenticated endpoints. An uploaded snapshot whose scalar leaves (vlan/vid/host/switch/id/tenant/...) are
dict-poisoned must make /design, /architecture_coverage and /archreview DEGRADE (HTTP 200), never 500. Pre-fix
these endpoints ran the engine over the upload and a set/dict comprehension raised
`TypeError: unhashable type: 'dict'`, which FastAPI surfaced as an HTTP 500. Distinct from the audit-6
leaf-COERCION webapp batch (int()/float()/.strip() on a wrong-type scalar)."""
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))          # make `backend` importable
_ENGINE_TESTS = str(Path(__file__).resolve().parents[2] / "tests")
if _ENGINE_TESTS not in sys.path:
    sys.path.append(_ENGINE_TESTS)

from backend.app import create_app  # noqa: E402

_D = {"x": 1}   # a dict where a scalar leaf is expected -> unhashable set member / dict key


@pytest.fixture()
def client(tmp_path):
    app = create_app(db_path=str(tmp_path / "test.db"))
    with TestClient(app) as c:
        yield c


def _upload(client, snap):
    cid = client.post("/api/campaigns", json={"name": "audit7"}).json()["id"]
    up = client.post(f"/api/campaigns/{cid}/snapshots",
                     files={"file": ("snap.json", json.dumps(snap).encode(), "application/json")},
                     data={"label": "poison"})
    assert up.status_code == 201, up.text
    return up.json()["id"]


def test_untrusted_endpoints_degrade_on_dict_poisoned_snapshot(client):
    """Only sections whose dict-poison is the UNHASHABLE class are planted (health_scores/routes/shadow_infra/
    segmentation are left clean -- those are the audit-6 string-op/float class, a separate PR)."""
    snap = {
        "script_version": "test",
        "devices": {"c": {}},
        "health_scores": [],
        "l3_forwarding": [
            {"vlan": _D, "risk": "single-gateway"},                    # single_gw set
            {"vlan": 7, "primary_subnet": "10.0.0.0/24", "switch": _D},  # v2gw switch set + archreview membership
        ],
        "fhrp": [{"vid": _D, "issues": ["split-brain"], "members": [{"host": _D}]}],  # broken-FHRP vid + host sets
        "physical_health": [{"switch": _D, "crc_errors": 9}],          # phy-dirty switch set
        "protocol_intelligence": [{"protocol": "EtherChannel", "severity": "High", "switch": _D}],  # bundle set
        "security": {"c": {"findings": [{"status": "fail", "id": _D}]}},  # fail-host map KEY
        "aci": {"apic1": {"vrfs": [{"tenant": _D, "name": _D, "dn": _D, "pc_enf_pref": "unenforced"}]}},  # ACI KEY + set
        "move_groups": [{"switches": ["realsw", _D]}],                 # wave-plan sorted()
    }
    sid = _upload(client, snap)
    for path in ("design", "architecture_coverage", "archreview"):
        r = client.get(f"/api/snapshots/{sid}/{path}")
        assert r.status_code == 200, f"/{path} -> {r.status_code}: {r.text[:200]}"
        assert isinstance(r.json(), dict)
