"""The SPA's receipt-export allowlists equal what the real trend producer returns.

``webapp/frontend/src/receiptExport.ts`` builds the Export Trend JSON file from three hand-kept
allowlists: the trend's own fields (TREND_EXPORT_FIELDS), each adjacent pair's bound fields
(TREND_PAIR_EXPORT_FIELDS) and the display-only readings served beside a pair (DISPLAY_ONLY_FIELDS).
The route returns ``Dict[str, Any]``, so the TypeScript exhaustiveness check in that file only sees
the hand-written ``api.ts`` type: a bound key the engine starts returning (webapp/backend/engine.py
``campaign_trend``, cisco_toolkit/html.py ``compute_campaign_trend``) would be silently dropped from
the export while the type-check and the Vitest suite stay green.

This test ties the allowlists to the real producer instead: a real campaign, two uploads of the
golden snapshot through the real upload route, and the real trend route. Each allowlist must EQUAL
the producer's keys, so a new key fails here until it is classified as bound or display-only, and a
key the producer stops returning fails here too.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "webapp"))

from backend.app import create_app  # noqa: E402

RECEIPT_EXPORT_TS = _REPO / "webapp" / "frontend" / "src" / "receiptExport.ts"
_ALLOWLIST = re.compile(
    r"^export const (?P<name>[A-Z_]+) = \[(?P<body>[^\]]*)\] as const\b",
    re.MULTILINE,
)
_STRING = re.compile(r'"([a-z_]+)"')


def _allowlist(source: str, name: str) -> list[str]:
    """One `export const NAME = [ "a", "b", ... ] as const` array, read as source text.

    The body must be string literals and commas only: a spread, an identifier or a computed entry
    would make the parsed list differ from what the module evaluates, so it fails here loudly."""
    found = [m for m in _ALLOWLIST.finditer(source) if m.group("name") == name]
    assert len(found) == 1, f"receiptExport.ts must declare `{name}` exactly once as a literal array"
    body = found[0].group("body")
    residue = _STRING.sub("", body)
    assert re.fullmatch(r"[\s,]*", residue), f"`{name}` holds a non-literal entry: {residue.strip()!r}"
    values = _STRING.findall(body)
    assert values and len(values) == len(set(values)), f"`{name}` is empty or repeats an entry"
    return values


def _parsed() -> dict[str, list[str]]:
    source = RECEIPT_EXPORT_TS.read_text(encoding="utf-8")
    return {name: _allowlist(source, name)
            for name in ("TREND_EXPORT_FIELDS", "TREND_PAIR_EXPORT_FIELDS", "DISPLAY_ONLY_FIELDS")}


def test_the_allowlist_reader_refuses_a_non_literal_entry():
    """Negative control: the source reader is not satisfied by a spread or an identifier."""
    with pytest.raises(AssertionError):
        _allowlist('export const X = ["a", ...OTHER] as const;\n', "X")
    with pytest.raises(AssertionError):
        _allowlist('export const X = ["a", b] as const;\n', "X")
    assert _allowlist('export const X = [\n  "a", "b_c",\n] as const satisfies Y;\n', "X") == ["a", "b_c"]


def test_receipt_export_allowlists_equal_the_real_trend_producer(tmp_path):
    lists = _parsed()
    raw = (_REPO / "tests" / "golden" / "snapshot.json").read_bytes()
    app = create_app(db_path=str(tmp_path / "receipt-export.db"))
    with TestClient(app, base_url="http://localhost") as client:
        campaign = client.post("/api/campaigns", json={"name": "export allowlist", "engagement_id": "ENG-EXPORT"})
        assert campaign.status_code == 201, campaign.text
        campaign_id = campaign.json()["id"]
        for label in ("before", "after"):
            uploaded = client.post(
                f"/api/campaigns/{campaign_id}/snapshots",
                files={"file": (f"{label}.json", raw, "application/json")},
                data={"label": label},
            )
            assert uploaded.status_code == 201, uploaded.text
        response = client.get(f"/api/campaigns/{campaign_id}/trend")
    assert response.status_code == 200, response.text
    trend = response.json()

    # The producer reached the bound path: one verified adjacent pair, not the fail-closed shape.
    assert trend["adjacent_comparison_status"]["status"] == "verified"
    pairs = trend["adjacent_comparisons"]
    assert len(pairs) == 1

    assert sorted(lists["TREND_EXPORT_FIELDS"]) == sorted(trend), (
        "Export Trend JSON's trend allowlist differs from the trend route's keys: classify each new key in "
        "receiptExport.ts (bound -> TREND_EXPORT_FIELDS) or remove a key the producer no longer returns"
    )
    assert sorted(lists["TREND_PAIR_EXPORT_FIELDS"] + lists["DISPLAY_ONLY_FIELDS"]) == sorted(pairs[0]), (
        "an adjacent pair's keys differ from TREND_PAIR_EXPORT_FIELDS + DISPLAY_ONLY_FIELDS: classify each new "
        "pair key in receiptExport.ts as bound or display-only"
    )
    assert not set(lists["TREND_PAIR_EXPORT_FIELDS"]) & set(lists["DISPLAY_ONLY_FIELDS"])
    # Every display-only reading the producer serves beside a pair is really there (and so really stripped).
    for field in lists["DISPLAY_ONLY_FIELDS"]:
        assert pairs[0][field]["display_only"] is True
