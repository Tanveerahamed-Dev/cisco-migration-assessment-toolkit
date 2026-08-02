"""Exact-source authority guards for the inline Cisco lifecycle table."""

import datetime as _dt
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from cisco_toolkit import eoldb
from cisco_toolkit.registry_integrity import PackIntegrityError


def test_review_vintage_is_a_valid_iso_date():
    _dt.date.fromisoformat(eoldb._EOL_REVIEWED)


def test_every_row_is_confirmed_by_an_exact_official_cisco_bulletin():
    for row in eoldb._EOL:
        assert row["conf"] == "confirmed"
        assert row["bulletin_id"].startswith("EOL")
        parsed = urlsplit(row["source_url"])
        assert parsed.scheme == "https"
        assert parsed.hostname == "www.cisco.com"
        assert parsed.path.startswith("/c/en/us/products/")
        assert not parsed.query and not parsed.fragment
        assert eoldb._citation_status(row) == "retained-primary-fixture"
        assert _dt.date.fromisoformat(row["eos"]) <= _dt.date.fromisoformat(
            row["ldos"]
        )


def test_negative_active_and_broad_unproven_claims_are_not_in_the_table():
    assert all(row["conf"] != "active" for row in eoldb._EOL)
    for model in (
        "C9300-48T",
        "N9K-C93180YC-EX",
        "N5K-C5672UP",
        "N7K-C7010",
        "WS-C2960CX-8PC-L",
        "WS-C6509-E",
    ):
        assert eoldb.lifecycle_for(model) is None


def test_selected_model_notice_does_not_leak_to_unlisted_3560cx_models():
    cited = eoldb.lifecycle_for("WS-C3560CX-12PC-S")
    assert cited is not None
    assert cited["bulletin_id"] == "EOL15072"
    assert cited["match_kind"] == "exact"
    assert cited["source_authoritative"] is True
    assert eoldb.lifecycle_for("WS-C3560CX-8XPD-S") is None


def test_lookup_discloses_review_vintage_match_scope_and_primary_url():
    record = eoldb.lifecycle_for("WS-C4948E-F")
    assert record["reviewed_at"] == eoldb._EOL_REVIEWED
    assert record["matched_pattern"] == "WS-C4948E"
    assert record["match_kind"] == "family-prefix"
    assert record["citation_status"] == "retained-primary-fixture"
    assert record["source_authoritative"] is True
    assert record["source_fresh"] is True
    assert record["fixture_sha256"] == eoldb._EOL_FIXTURE_SHA256
    assert record["bulletin_id"] == "EOL11273"
    assert record["document_id"] == "c51-738116"
    assert record["source_url"].endswith("eos-eol-notice-c51-738116.html")


def test_retained_eol_fixture_is_byte_and_semantically_bound():
    proof = eoldb.verify_retained_eol_source_chain()
    assert proof["verified"] is True
    assert proof["fixture_path"] == (
        "reference-data/official-sources/cisco/eol-bulletins.json"
    )
    assert proof["fixture_sha256"] == eoldb._EOL_FIXTURE_SHA256
    assert proof["fixture_bytes"] == eoldb._EOL_FIXTURE_BYTES
    assert proof["bulletin_count"] == 17
    assert proof["model_scope_count"] == 44
    assert proof["exact_url_count"] == 17
    assert proof["semantic_sha256"] == eoldb._EOL_SEMANTIC_SHA256
    assert proof["source_fresh"] is True


def test_eol_health_requires_retained_bytes_and_exact_semantic_binding():
    health = eoldb.registry_health()
    assert health["schema_verified"] is True
    assert health["integrity_verified"] is True
    assert health["integrity_scope"] == (
        "retained-fixture-sha256-plus-exact-runtime-semantic-binding"
    )
    assert health["build_provenance_verified"] is True
    assert health["retained_source_bytes_verified"] is True
    assert health["source_authoritative"] is True
    assert health["authoritative"] is True
    assert health["source_fresh"] is True
    assert health["fixture_bound_rows"] == 44
    assert health["bulletin_cited_rows"] == health["row_count"]
    assert health["unresolved_reference_rows"] == 0
    assert health["active_unresolved_rows"] == 0
    assert health["error"] == ""


def test_tampered_eol_fixture_bytes_are_rejected(tmp_path):
    repository_root = Path(__file__).resolve().parent.parent
    fixture_relative = Path(eoldb._EOL_FIXTURE_RELATIVE_PATH)
    inventory_relative = Path(eoldb.SOURCE_INVENTORY_RELATIVE_PATH)
    fixture = tmp_path / fixture_relative
    inventory = tmp_path / inventory_relative
    fixture.parent.mkdir(parents=True)
    inventory.parent.mkdir(parents=True, exist_ok=True)
    fixture.write_bytes(
        (repository_root / fixture_relative)
        .read_bytes()
        .replace(b'"eos": "2017-10-31"', b'"eos": "2018-10-31"', 1)
    )
    inventory.write_bytes((repository_root / inventory_relative).read_bytes())

    with pytest.raises(PackIntegrityError, match="SHA-256 mismatch"):
        eoldb.verify_retained_eol_source_chain(tmp_path)


def test_runtime_eol_date_or_pid_scope_drift_breaks_fixture_binding(monkeypatch):
    drifted = [dict(row) for row in eoldb._EOL]
    drifted[0]["eos"] = "2099-01-01"
    monkeypatch.setattr(eoldb, "_EOL", drifted)

    with pytest.raises(
        PackIntegrityError,
        match="dates/PID scopes do not exactly match runtime code",
    ):
        eoldb.verify_retained_eol_source_chain()


@pytest.mark.parametrize(
    ("now", "status"),
    [
        (_dt.datetime(2027, 2, 1, tzinfo=_dt.timezone.utc), "stale"),
        (_dt.datetime(2026, 7, 29, tzinfo=_dt.timezone.utc), "future-dated"),
    ],
)
def test_eol_source_authority_requires_freshness(now, status):
    with pytest.raises(PackIntegrityError, match=status):
        eoldb.verify_retained_eol_source_chain(now=now)


def test_wheel_without_retained_fixture_never_claims_eol_source_authority(
    monkeypatch,
):
    def unavailable():
        raise PackIntegrityError("Cisco EoL fixture is unavailable")

    monkeypatch.setattr(eoldb, "_runtime_source_proof", unavailable)
    health = eoldb.registry_health()
    assert health["schema_verified"] is True
    assert health["build_provenance_verified"] is True
    assert health["integrity_verified"] is False
    assert health["retained_source_bytes_verified"] is False
    assert health["source_authoritative"] is False
    assert health["authoritative"] is False
    assert "unavailable" in health["error"]
    assert eoldb._citation_status(eoldb._EOL[0]) == "primary-url-unverified"
