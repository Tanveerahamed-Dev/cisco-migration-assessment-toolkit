"""Exact-source authority guards for the inline Cisco lifecycle table."""

import datetime as _dt
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from cisco_toolkit import eoldb
from cisco_toolkit.registry_integrity import PackIntegrityError

# The exact 2026-07-30 fixture bytes, frozen by three hash pins (the
# official-sources manifest, eoldb._EOL_FIXTURE_SHA256, and the repository
# privacy guard). Deliberately a LITERAL, not a read of eoldb's constant: a
# future refresh that re-pins new bytes must not inherit the tolerance below.
_FIXTURE_2026_07_30_SHA256 = (
    "7683b29e66d3e5b39d89407e60a5f08ffbf8ef9f19ab029279ffc9d0861349c3"
)

# Verification-implying provenance phrasing. Under the no-egress doctrine no
# offline process can check a claim against a live Cisco URL, so registry
# provenance prose must state transcription, never verification (handoff
# 2026-07-30 §13.15).
_VERIFICATION_OVERCLAIM_PHRASES = (
    "checked against",
    "verified against",
    "validated against",
)


def _normalized_prose(text: str) -> str:
    """Lowercase, comment-marker-stripped, whitespace-collapsed prose, so a
    re-wrap or comment reflow cannot hide a reintroduced phrase."""

    return " ".join(text.replace("#", " ").split()).lower()


def test_provenance_prose_is_transcription_not_live_verification():
    """§13.15 wording guard: eoldb and the reference-data docs state
    transcription provenance and never claim live-URL verification."""

    root = Path(__file__).resolve().parent.parent
    eoldb_path = Path(eoldb.__file__).resolve()
    assert "transcribed from its named cisco bulletin" in _normalized_prose(
        eoldb_path.read_text(encoding="utf-8")
    )
    for path in (
        eoldb_path,
        root / "reference-data" / "README.md",
        root / "reference-data" / "official-sources" / "README.md",
    ):
        prose = _normalized_prose(path.read_text(encoding="utf-8"))
        for phrase in _VERIFICATION_OVERCLAIM_PHRASES:
            assert phrase not in prose, (path.name, phrase)


def test_fixture_refresh_must_drop_the_live_verification_sentence():
    """The retained fixture's `evidence_method` still carries the pre-§13.15
    sentence "checked against its exact HTTPS Cisco source URL"; its bytes are
    hash-frozen, so the sentence is tolerated ONLY at exactly those bytes (and
    asserted present there, so silent drift is caught). Any other fixture
    content — i.e. the next sanctioned evidence refresh — must state
    transcription provenance with no verification-implying phrasing."""

    root = Path(__file__).resolve().parent.parent
    raw = (root / Path(eoldb._EOL_FIXTURE_RELATIVE_PATH)).read_bytes()
    method = json.loads(raw.decode("utf-8"))["evidence_method"]
    if hashlib.sha256(raw).hexdigest() == _FIXTURE_2026_07_30_SHA256:
        assert "checked against its exact HTTPS Cisco source URL" in method
        return
    normalized = _normalized_prose(method)
    for phrase in _VERIFICATION_OVERCLAIM_PHRASES:
        assert phrase not in normalized, phrase


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


def test_bundled_eol_fixture_is_the_exact_retained_evidence_bytes():
    root = Path(__file__).resolve().parent.parent
    retained = root / Path(eoldb._EOL_FIXTURE_RELATIVE_PATH)
    bundled = root / Path(eoldb._EOL_BUNDLED_FIXTURE_RELATIVE_PATH)
    assert bundled.read_bytes() == retained.read_bytes()
    assert bundled.stat().st_size == eoldb._EOL_FIXTURE_BYTES
    assert hashlib.sha256(bundled.read_bytes()).hexdigest() == eoldb._EOL_FIXTURE_SHA256


def _lay_out_wheel_eol_fixture(tmp_path: Path, raw: bytes) -> Path:
    package = tmp_path / "cisco_toolkit"
    fixture = package / "data" / "eol-bulletins.json"
    fixture.parent.mkdir(parents=True)
    fixture.write_bytes(raw)
    module = package / "eoldb.py"
    module.write_text("# installed-wheel path probe\n", encoding="utf-8")
    return module


def test_installed_wheel_fixture_preserves_full_eol_authority(monkeypatch, tmp_path):
    root = Path(__file__).resolve().parent.parent
    raw = (root / Path(eoldb._EOL_FIXTURE_RELATIVE_PATH)).read_bytes()
    module = _lay_out_wheel_eol_fixture(tmp_path, raw)
    monkeypatch.setattr(eoldb, "__file__", str(module))

    proof = eoldb.verify_retained_eol_source_chain()
    assert proof["verified"] is True
    assert proof["fixture_path"] == "cisco_toolkit/data/eol-bulletins.json"
    assert proof["evidence_distribution"] == "bundled-authoritative-evidence"
    assert proof["inventory_verified"] is False
    assert proof["code_pinned_contract_verified"] is True
    assert proof["semantic_sha256"] == eoldb._EOL_SEMANTIC_SHA256

    monkeypatch.setattr(eoldb, "_runtime_source_proof", lambda: proof)
    health = eoldb.registry_health()
    assert health["integrity_verified"] is True
    assert health["retained_source_bytes_verified"] is True
    assert health["build_provenance_verified"] is True
    assert health["source_authoritative"] is True
    assert health["authoritative"] is True
    assert health["fixture_bound_rows"] == 44


def test_installed_wheel_fixture_tamper_fails_closed(monkeypatch, tmp_path):
    root = Path(__file__).resolve().parent.parent
    raw = (root / Path(eoldb._EOL_FIXTURE_RELATIVE_PATH)).read_bytes()
    module = _lay_out_wheel_eol_fixture(tmp_path, raw + b"\n")
    monkeypatch.setattr(eoldb, "__file__", str(module))

    with pytest.raises(PackIntegrityError, match="byte-size mismatch"):
        eoldb.verify_retained_eol_source_chain()


def test_partial_repository_evidence_never_falls_back_to_bundle(
    monkeypatch, tmp_path
):
    root = Path(__file__).resolve().parent.parent
    raw = (root / Path(eoldb._EOL_FIXTURE_RELATIVE_PATH)).read_bytes()
    module = _lay_out_wheel_eol_fixture(tmp_path, raw)
    inventory = tmp_path / Path(eoldb.SOURCE_INVENTORY_RELATIVE_PATH)
    inventory.parent.mkdir(parents=True)
    inventory.write_bytes(
        (root / Path(eoldb.SOURCE_INVENTORY_RELATIVE_PATH)).read_bytes()
    )
    monkeypatch.setattr(eoldb, "__file__", str(module))

    with pytest.raises(PackIntegrityError, match="fixture is unavailable"):
        eoldb.verify_retained_eol_source_chain()


def test_repository_layout_with_both_evidence_files_missing_never_falls_back_to_bundle(
    monkeypatch, tmp_path
):
    root = Path(__file__).resolve().parent.parent
    raw = (root / Path(eoldb._EOL_FIXTURE_RELATIVE_PATH)).read_bytes()
    module = _lay_out_wheel_eol_fixture(tmp_path, raw)
    (tmp_path / "setup.py").write_text("# repository layout marker\n", encoding="utf-8")
    monkeypatch.setattr(eoldb, "__file__", str(module))

    with pytest.raises(PackIntegrityError, match="official-source inventory unavailable"):
        eoldb.verify_retained_eol_source_chain()


def test_atlas_layout_uses_bundled_fixture_even_with_release_pyproject(
    monkeypatch, tmp_path
):
    """Atlas carries pyproject solely as its release-version source; it is not a checkout marker."""
    root = Path(__file__).resolve().parent.parent
    raw = (root / Path(eoldb._EOL_FIXTURE_RELATIVE_PATH)).read_bytes()
    module = _lay_out_wheel_eol_fixture(tmp_path, raw)
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "atlas"\nversion = "3.31.0"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(eoldb, "__file__", str(module))

    proof = eoldb.verify_retained_eol_source_chain()
    assert proof["verified"] is True
    assert proof["fixture_path"] == "cisco_toolkit/data/eol-bulletins.json"
    assert proof["evidence_distribution"] == "bundled-authoritative-evidence"


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


def test_missing_or_invalid_runtime_fixture_never_claims_eol_source_authority(
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
