"""Repository-review regressions for the web ingest/redaction/upload trust boundaries."""

from __future__ import annotations

import asyncio
import builtins
import io
import json
import stat
import sys
import threading
import warnings
import zipfile
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import backend.app as app_module  # noqa: E402
import backend.ingest as ingest  # noqa: E402
import backend.redaction_verify as verifier  # noqa: E402
import backend.summary as summary  # noqa: E402


def _zip(entries: list[tuple[str | zipfile.ZipInfo, bytes | str]]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, payload in entries:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                archive.writestr(name, payload)
    return buffer.getvalue()


def test_unc_member_is_rejected_before_any_destination_lookup_or_write(monkeypatch, tmp_path):
    dest = tmp_path / "dest"
    dest.mkdir()
    archive = _zip([("//attacker/share/show_version.txt", "secret")])
    effects: list[str] = []

    def side_effect(*_args, **_kwargs):
        effects.append("called")
        raise AssertionError("destination filesystem was touched before lexical preflight completed")

    monkeypatch.setattr(Path, "resolve", side_effect)
    monkeypatch.setattr(Path, "mkdir", side_effect)
    monkeypatch.setattr(builtins, "open", side_effect)
    monkeypatch.setattr(zipfile.ZipFile, "open", side_effect)
    with pytest.raises(ingest.IngestError, match="rooted|remote"):
        ingest._safe_extract(archive, dest)
    assert effects == []


@pytest.mark.parametrize(
    "left,right,namespace",
    [
        ("core/show.txt", "core/show.txt", "exact"),
        # On Windows, zipfile canonicalizes the backslash before exposing ZipInfo.filename.
        ("core/show.txt", r"core\show.txt", "(?:slash|exact)"),
        ("core/SHOW.txt", "core/show.txt", "casefold"),
        ("core/café.txt", "core/cafe\u0301.txt", "nfc"),
        ("core/K.txt", "core/\uff2b.txt", "nfkc"),
    ],
)
def test_archive_duplicate_alias_names_are_rejected(tmp_path, left, right, namespace):
    dest = tmp_path / "dest"
    dest.mkdir()
    with pytest.raises(ingest.IngestError, match=rf"duplicate aliases under {namespace}"):
        ingest._safe_extract(_zip([(left, "a"), (right, "b")]), dest)
    assert list(dest.iterdir()) == []


@pytest.mark.parametrize(
    "name",
    [
        "/rooted/show.txt",
        r"C:\fleet\show.txt",
        r"\\?\C:\fleet\show.txt",
        "https://attacker.invalid/show.txt",
        "core/show.txt:secret",
        "core/\x00bad.txt",
        "core/show\u202etxt",
        "core/show.txt.",
        "core/CONIN$",
        "core/conout$.txt",
        "core/CLOCK$",
        "core/COM\u00b9",
        "core/LPT\u00b9.log",
    ],
)
def test_archive_ambiguous_absolute_device_scheme_control_and_ads_names_are_rejected(
    tmp_path, name,
):
    dest = tmp_path / "dest"
    dest.mkdir()
    with pytest.raises(ingest.IngestError):
        ingest._safe_extract(_zip([(name, "x")]), dest)
    assert list(dest.iterdir()) == []


def test_archive_device_name_calibration_accepts_non_device_prefixes(tmp_path):
    dest = tmp_path / "dest"
    dest.mkdir()
    assert ingest._safe_extract(
        _zip([("console/show.txt", "a"), ("auxiliary/show.txt", "b")]),
        dest,
    ) == 2
    assert (dest / "console" / "show.txt").read_text() == "a"
    assert (dest / "auxiliary" / "show.txt").read_text() == "b"


def test_archive_symlink_and_file_parent_conflicts_are_rejected(tmp_path):
    dest = tmp_path / "dest"
    dest.mkdir()
    link = zipfile.ZipInfo("core/link")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    with pytest.raises(ingest.IngestError, match="symlink|special"):
        ingest._safe_extract(_zip([(link, "target")]), dest)

    with pytest.raises(ingest.IngestError, match="descends through another file"):
        ingest._safe_extract(
            _zip([("core", "file"), ("core/show_version.txt", "version")]),
            dest,
        )


def test_archive_accepts_a_seekable_stream_without_copying_to_raw_bytes(tmp_path):
    dest = tmp_path / "dest"
    dest.mkdir()
    stream = io.BytesIO(_zip([("core/show_version.txt", "version")]))
    assert ingest._safe_extract(stream, dest) == 1
    assert (dest / "core" / "show_version.txt").read_text() == "version"


def test_archive_count_cap_includes_directory_only_entries(monkeypatch, tmp_path):
    monkeypatch.setattr(ingest, "MAX_FILES", 1)
    dest = tmp_path / "dest"
    dest.mkdir()
    archive = _zip([("core/", b""), ("core/show_version.txt", b"version")])
    with pytest.raises(ingest.IngestError, match="2 entries"):
        ingest._safe_extract(archive, dest)
    assert list(dest.iterdir()) == []


def test_folder_scan_fails_closed_on_scandir_error(monkeypatch, tmp_path):
    folder = tmp_path / "fleet"
    folder.mkdir()
    (folder / "capture.txt").write_text("x", encoding="utf-8")

    def broken_scandir(_path):
        raise PermissionError("fault injected")

    monkeypatch.setattr(ingest.os, "scandir", broken_scandir)
    with pytest.raises(ingest.IngestError, match="completely enumerated"):
        ingest._resolve_and_scan(folder)


def test_folder_scan_fails_closed_on_entry_stat_error(monkeypatch, tmp_path):
    folder = tmp_path / "fleet"
    folder.mkdir()

    class Entry:
        name = "capture.txt"
        path = str(folder / name)

        @staticmethod
        def stat(*, follow_symlinks):
            assert follow_symlinks is False
            raise PermissionError("fault injected")

    class Scan:
        def __enter__(self):
            return iter([Entry()])

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(ingest.os, "scandir", lambda _path: Scan())
    with pytest.raises(ingest.IngestError, match="could not be statted"):
        ingest._resolve_and_scan(folder)


def test_folder_scan_streams_and_caps_directory_entries_before_enqueue(monkeypatch, tmp_path):
    folder = tmp_path / "fleet"
    folder.mkdir()
    monkeypatch.setattr(ingest, "MAX_FILES", 2)
    stat_calls: list[str] = []
    real_lstat = ingest.os.lstat

    class Entry:
        def __init__(self, index):
            self.name = f"dir-{index}"
            self.path = str(folder / self.name)
            self.index = index

        def stat(self, *, follow_symlinks):
            assert follow_symlinks is False
            stat_calls.append(self.name)

            class EntryStat:
                st_mode = stat.S_IFDIR | 0o755
                st_size = 0
                st_dev = 1

                @property
                def st_ino(self):
                    return self_outer.index

            self_outer = self
            return EntryStat()

    class Scan:
        def __init__(self):
            self.index = 0

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def __iter__(self):
            return self

        def __next__(self):
            self.index += 1
            if self.index <= 3:
                return Entry(self.index)
            raise AssertionError("the scanner was materialized beyond the enforced entry cap")

    def fake_lstat(path):
        candidate = Path(path)
        if candidate.parent == folder and candidate.name.startswith("dir-"):
            index = int(candidate.name.rsplit("-", 1)[1])

            class EntryStat:
                st_mode = stat.S_IFDIR | 0o755
                st_size = 0
                st_dev = 1
                st_ino = index

            return EntryStat()
        return real_lstat(path)

    monkeypatch.setattr(ingest.os, "lstat", fake_lstat)
    monkeypatch.setattr(ingest.os, "scandir", lambda _path: Scan())
    with pytest.raises(ingest.IngestError, match="2-entry limit"):
        ingest._resolve_and_scan(folder)
    assert stat_calls == ["dir-1", "dir-2"]


def test_folder_scan_rechecks_queued_directory_identity_before_scanning(monkeypatch, tmp_path):
    folder = tmp_path / "fleet"
    child = folder / "core"
    child.mkdir(parents=True)
    (child / "capture.txt").write_text("x", encoding="utf-8")
    real_lstat = ingest.os.lstat
    real_scandir = ingest.os.scandir
    scanned: list[Path] = []
    child_lstats = 0

    class SwappedStat:
        def __init__(self, original):
            self.st_mode = stat.S_IFLNK | 0o777
            self.st_size = original.st_size
            self.st_dev = original.st_dev
            self.st_ino = original.st_ino + 1
            self.st_file_attributes = 0

    def swapped_lstat(path):
        nonlocal child_lstats
        original = real_lstat(path)
        if Path(path) == child:
            child_lstats += 1
            if child_lstats >= 2:
                return SwappedStat(original)
        return original

    def guarded_scandir(path):
        scanned.append(Path(path))
        if Path(path) == child:
            raise AssertionError("a swapped queued directory was scanned")
        return real_scandir(path)

    monkeypatch.setattr(ingest.os, "lstat", swapped_lstat)
    monkeypatch.setattr(ingest.os, "scandir", guarded_scandir)
    with pytest.raises(ingest.IngestError, match="changed identity|became a link"):
        ingest._resolve_and_scan(folder)
    assert scanned == [folder]


def _authority(source_authoritative: bool = True, integrity_verified=True) -> dict:
    return {
        "source_authoritative": source_authoritative,
        "integrity_verified": integrity_verified,
        "status": "verified" if source_authoritative else "integrity-only",
    }


def _verified_snapshot() -> dict:
    return {
        "script_version": "V-current",
        "devices": {"sw1": {}},
        "data_authorities": {
            "oui": _authority(),
            "ports": _authority(),
            "eol": _authority(),
        },
    }


def _stamp_test_origin(snap: dict, origin: str) -> dict:
    stamp = {"origin": origin}
    if origin == summary.LOCAL_ENGINE_ORIGIN:
        stamp["integrity_verified"] = True
    snap[summary.SNAPSHOT_PROVENANCE_KEY] = stamp
    return snap


def test_snapshot_verification_distinguishes_verified_partial_and_legacy_unverified():
    verified = summary.snapshot_verification(
        _stamp_test_origin(_verified_snapshot(), summary.LOCAL_ENGINE_ORIGIN)
    )
    assert verified["status"] == "verified" and verified["verified"] is True
    assert verified["origin"] == summary.LOCAL_ENGINE_ORIGIN

    failed = _stamp_test_origin(_verified_snapshot(), summary.LOCAL_ENGINE_ORIGIN)
    failed["assessment_integrity"] = {"failed_phases": ["Migration readiness"]}
    partial = summary.snapshot_verification(failed)
    assert partial["status"] == "partial"
    assert partial["failed_phases"] == ["Migration readiness"]

    degraded = _stamp_test_origin(_verified_snapshot(), summary.LOCAL_ENGINE_ORIGIN)
    degraded["data_authorities"]["ports"] = _authority(False)
    partial = summary.snapshot_verification(degraded)
    assert partial["status"] == "partial"
    assert partial["non_authoritative_authorities"] == ["ports"]

    legacy = {
        "devices": {"sw1": {}},
        "data_authorities": {
            "oui": {"authoritative": True},
            "ports": {"authoritative": True},
        },
    }
    unverified = summary.snapshot_verification(legacy)
    assert unverified["status"] == "unverified"
    assert unverified["origin"] == "legacy-or-unknown"
    assert unverified["missing_authorities"] == ["oui", "ports", "eol"]

    unknown = _stamp_test_origin(_verified_snapshot(), summary.LOCAL_ENGINE_ORIGIN)
    unknown[summary.SNAPSHOT_PROVENANCE_KEY].pop("integrity_verified")
    status = summary.snapshot_verification(unknown)
    assert status["status"] == "unverified"
    assert status["integrity_status"] == "unknown"
    assert any("integrity is unknown" in reason for reason in status["reasons"])


def test_uploaded_legacy_snapshot_persists_unverified_summary(tmp_path, monkeypatch):
    monkeypatch.delenv("ASSESSHUB_TOKEN", raising=False)
    app = app_module.create_app(db_path=str(tmp_path / "status.db"))
    with TestClient(app, base_url="http://localhost") as client:
        campaign = client.post("/api/campaigns", json={"name": "legacy"}).json()
        response = client.post(
            f"/api/campaigns/{campaign['id']}/snapshots",
            files={"file": ("legacy.json", json.dumps({"devices": {"sw1": {}}}), "application/json")},
        )
        assert response.status_code == 201, response.text
        assert response.json()["summary"]["verification"]["status"] == "unverified"
        assert response.json()["summary"]["verification"]["origin"] == summary.DIRECT_UPLOAD_ORIGIN
        persisted = app.state.store.get_snapshot(response.json()["id"])
        assert persisted[summary.SNAPSHOT_PROVENANCE_KEY] == {
            "origin": summary.DIRECT_UPLOAD_ORIGIN
        }
        stored = client.get(f"/api/snapshots/{response.json()['id']}").json()
        assert stored["summary"]["verification"]["status"] == "unverified"


def test_direct_upload_cannot_spoof_local_origin_or_authority_attestation(tmp_path):
    app = app_module.create_app(db_path=str(tmp_path / "origin.db"))
    with TestClient(app, base_url="http://localhost") as client:
        campaign = client.post("/api/campaigns", json={"name": "origin"}).json()
        spoof = _stamp_test_origin(_verified_snapshot(), summary.LOCAL_ENGINE_ORIGIN)
        rejected = client.post(
            f"/api/campaigns/{campaign['id']}/snapshots",
            files={"file": ("spoof.json", json.dumps(spoof), "application/json")},
        )
        assert rejected.status_code == 400
        assert "reserved for server provenance" in rejected.json()["detail"]

        accepted = client.post(
            f"/api/campaigns/{campaign['id']}/snapshots",
            files={
                "file": (
                    "claims.json",
                    json.dumps(_verified_snapshot()),
                    "application/json",
                )
            },
        )
        assert accepted.status_code == 201, accepted.text
        snapshot_id = accepted.json()["id"]
        verification = accepted.json()["summary"]["verification"]
        assert verification["status"] == "unverified"
        assert verification["verified"] is False
        assert verification["origin"] == summary.DIRECT_UPLOAD_ORIGIN

        # A cached pre-contract "verified" summary must be freshened from persisted server-owned
        # provenance rather than preserving the old false attestation.
        app.state.store.update_summary(
            snapshot_id,
            {
                "engine_schema": app_module.engine.ENGINE_SCHEMA_VERSION,
                "verification": {"status": "verified", "verified": True},
            },
        )
        fresh = client.get(f"/api/snapshots/{snapshot_id}").json()["summary"]["verification"]
        assert fresh["contract_version"] == summary.VERIFICATION_CONTRACT_VERSION
        assert fresh["status"] == "unverified"
        assert fresh["origin"] == summary.DIRECT_UPLOAD_ORIGIN


def _safe_redacted_snapshot() -> dict:
    return {
        "devices": {
            "sw1": {
                "ipv4": "v4-n00001-h001.assesshub-redacted.invalid",
                "ipv6": "v6-00000001.assesshub-redacted.invalid",
                "mac": "mac-000000000001.assesshub-redacted.invalid",
                "serial_number": "serial-000001.assesshub-redacted.invalid",
                "contact": "contact-000001@assesshub-redacted.invalid",
                "password": "<redacted>",
            }
        }
    }


@pytest.mark.parametrize(
    "field,value,expected",
    [
        ("ipv4", "10.20.30.40", "IPv4"),
        ("ipv6", "2001:4860::1", "IPv6"),
        ("mac", "00:11:22:33:44:55", "MAC"),
        ("serial_number", "FOC1830R1QS", "serial"),
        ("contact", "operator@real-customer.test", "email"),
        ("password", "hunter2", "secret-bearing"),
        ("config", "enable secret 5 hunter2", "credential"),
    ],
)
def test_snapshot_scanner_detects_each_sensitive_class(tmp_path, field, value, expected):
    snapshot = _safe_redacted_snapshot()
    snapshot["devices"]["sw1"][field] = value
    path = tmp_path / "redacted.snapshot.json"
    path.write_text(json.dumps(snapshot), encoding="utf-8")
    with pytest.raises(verifier.RedactionVerificationError, match=expected):
        verifier.verify_shareable_artifacts(path, ())


def test_snapshot_scanner_covers_keys_and_keeps_narrow_documented_cidr_example(tmp_path):
    snapshot = _safe_redacted_snapshot()
    snapshot["design_blueprint"] = {
        "requirements_model": {
            "fields": [
                {"label": "Target address space (supernet, e.g. 10.0.0.0/16)"}
            ]
        }
    }
    path = tmp_path / "safe.snapshot.json"
    path.write_text(json.dumps(snapshot), encoding="utf-8")
    assert verifier.verify_shareable_artifacts(path, ()) == 0

    snapshot["notes"] = "e.g. 10.20.30.0/24"
    path.write_text(json.dumps(snapshot), encoding="utf-8")
    with pytest.raises(verifier.RedactionVerificationError, match="IPv4"):
        verifier.verify_shareable_artifacts(path, ())
    del snapshot["notes"]

    snapshot["evidence_10.9.8.7"] = "survived in a key"
    path.write_text(json.dumps(snapshot), encoding="utf-8")
    with pytest.raises(verifier.RedactionVerificationError, match="IPv4"):
        verifier.verify_shareable_artifacts(path, ())


def test_snapshot_scanner_limits_reserved_ipv6_example_to_design_documentation(tmp_path):
    snapshot = _safe_redacted_snapshot()
    snapshot["design_blueprint"] = {
        "decisions": [{"evidence": {"summary": "Internet-wide source (or ::/0)."}}]
    }
    path = tmp_path / "ipv6-example.snapshot.json"
    path.write_text(json.dumps(snapshot), encoding="utf-8")
    assert verifier.verify_shareable_artifacts(path, ()) == 0

    snapshot["devices"]["sw1"]["observed_prefix"] = "::/0"
    path.write_text(json.dumps(snapshot), encoding="utf-8")
    with pytest.raises(verifier.RedactionVerificationError, match="IPv6"):
        verifier.verify_shareable_artifacts(path, ())


def test_snapshot_scanner_accepts_serial_pseudonyms_but_catches_serials_in_keys(tmp_path):
    snapshot = _safe_redacted_snapshot()
    snapshot["devices"]["sw1"]["serial"] = "serial-000042.assesshub-redacted.invalid"
    path = tmp_path / "serial-key.snapshot.json"
    path.write_text(json.dumps(snapshot), encoding="utf-8")
    assert verifier.verify_shareable_artifacts(path, ()) == 0

    snapshot["device_fdo12345abc"] = "serial survived in a key"
    path.write_text(json.dumps(snapshot), encoding="utf-8")
    with pytest.raises(verifier.RedactionVerificationError, match="Cisco serial"):
        verifier.verify_shareable_artifacts(path, ())


def test_email_redaction_is_stable_non_lossy_and_independently_verifiable(tmp_path):
    from cisco_toolkit.html import redact_snapshot

    real = "Alice.Network@customer.test"
    snapshot = {
        "devices": {
            "sw1": {
                "contact_email": real,
                "banner": f"Escalate to {real}",
                "example": "operator@example.com",
            }
        },
        f"owner:{real}": 1,
        f"owner:{real.upper()}": 2,
        "owner:contact-000001@assesshub-redacted.invalid": 3,
    }

    redacted = redact_snapshot(snapshot)
    pseudonym = redacted["devices"]["sw1"]["contact_email"]
    assert pseudonym == "contact-000002@assesshub-redacted.invalid"
    assert redacted["devices"]["sw1"]["banner"] == f"Escalate to {pseudonym}"
    assert redacted["devices"]["sw1"]["example"] == "contact-000003@assesshub-redacted.invalid"
    assert list(redacted)[1:] == [
        "owner:contact-000002@assesshub-redacted.invalid",
        "owner:contact-000002@assesshub-redacted.invalid~2",
        "owner:contact-000001@assesshub-redacted.invalid",
    ]
    assert list(redacted.values())[1:] == [1, 2, 3]
    assert real.casefold() not in json.dumps(redacted).casefold()
    assert redact_snapshot(redacted) == redacted

    path = tmp_path / "email-redacted.snapshot.json"
    path.write_text(json.dumps(redacted), encoding="utf-8")
    assert verifier.verify_shareable_artifacts(path, ()) == 0


def test_all_identity_classes_are_redacted_in_dictionary_keys_without_loss():
    from cisco_toolkit.html import redact_snapshot

    source = {
        "10.20.30.40": "ipv4",
        "fd00::1": "ipv6",
        "02:00:00:00:00:01": "mac",
        "FOC1234ABCD": "serial",
        "owner@customer.test": "email",
        "v4-n00001-h040.assesshub-redacted.invalid": "pre-existing marker",
    }
    redacted = redact_snapshot(source)
    blob = json.dumps(redacted)
    for real in source:
        if not real.endswith(".assesshub-redacted.invalid"):
            assert real not in blob
    assert len(redacted) == len(source)
    assert set(redacted.values()) == set(source.values())
    assert all(
        "assesshub-redacted.invalid" in key
        for key in redacted
    )
    assert "fd00::" not in blob and "02:00:" not in blob and "240." not in blob
    assert redact_snapshot(redacted) == redacted


def test_quoted_secret_is_consumed_whole_and_placeholder_residue_is_rejected(tmp_path):
    from cisco_toolkit.html import redact_snapshot

    redacted = redact_snapshot({
        "config": 'set passphrase "correct horse battery staple"'
    })
    assert redacted["config"] == "set passphrase <redacted>"

    unsafe = _safe_redacted_snapshot()
    unsafe["config"] = 'set passphrase <redacted> horse battery staple"'
    path = tmp_path / "quoted.snapshot.json"
    path.write_text(json.dumps(unsafe), encoding="utf-8")
    with pytest.raises(verifier.RedactionVerificationError, match="credential residue"):
        verifier.verify_shareable_artifacts(path, ())

    collection = tmp_path / "collection"
    collection.mkdir()
    (collection / "show_run.txt").write_text(unsafe["config"], encoding="utf-8")
    with pytest.raises(verifier.RedactionVerificationError, match="residue"):
        verifier.verify_collection_secret_scrub(collection)


def test_pseudonym_allocator_collision_checks_and_fails_closed_on_exhaustion():
    from cisco_toolkit.html import RedactionPseudonymExhausted, _SyntheticAllocator

    allocator = _SyntheticAllocator({"marker-1"}, limit=2)
    assert allocator.issue(lambda value: f"marker-{value}") == "marker-2"
    with pytest.raises(RedactionPseudonymExhausted, match="exhausted"):
        allocator.issue(lambda value: f"marker-{value}")


def test_phase_success_requires_literal_json_boolean_true():
    assert ingest._phase_ok(True) is True
    for value in (False, 1, "true", "yes", "ok", None, [], {}):
        assert ingest._phase_ok(value) is False


def test_campaign_and_campaign_list_freshen_stale_summary_contracts(tmp_path):
    app = app_module.create_app(db_path=str(tmp_path / "fresh-campaign.db"))
    store = app.state.store
    campaign = store.create_campaign("freshness")
    snap = _stamp_test_origin(_verified_snapshot(), summary.LOCAL_ENGINE_ORIGIN)
    meta = store.add_snapshot(
        campaign["id"], "baseline", snap, summary.summarize(snap)
    )
    stale = {
        "engine_schema": app_module.engine.ENGINE_SCHEMA_VERSION,
        "verification": {
            "contract_version": summary.VERIFICATION_CONTRACT_VERSION - 1,
            "status": "verified",
            "verified": True,
        },
    }
    store.update_summary(meta["id"], stale)

    with TestClient(app, base_url="http://localhost") as client:
        detail = client.get(f"/api/campaigns/{campaign['id']}").json()
        assert detail["snapshots"][0]["summary"]["verification"]["contract_version"] == (
            summary.VERIFICATION_CONTRACT_VERSION
        )
        store.update_summary(meta["id"], stale)
        listed = client.get("/api/campaigns").json()
        assert listed[0]["latest_summary"]["verification"]["contract_version"] == (
            summary.VERIFICATION_CONTRACT_VERSION
        )


def test_folder_engine_reads_private_custody_copy_not_post_scan_source(tmp_path, monkeypatch):
    source = tmp_path / "fleet"
    device = source / "sw1"
    device.mkdir(parents=True)
    capture = device / "show_version.txt"
    capture.write_text("ORIGINAL", encoding="utf-8")
    seen = {}

    def assess(tree, n_files, workdir):
        capture.write_text("SWAPPED-AFTER-CUSTODY", encoding="utf-8")
        seen["tree"] = tree
        seen["bytes"] = (tree / "sw1" / "show_version.txt").read_text(encoding="utf-8")
        return {"devices": {}}, {"n": n_files}

    monkeypatch.setattr(ingest, "_assess_tree", assess)
    ingest.run_collection_folder(source)
    assert seen["tree"] != source
    assert seen["bytes"] == "ORIGINAL"


def test_output_lock_refuses_a_concurrent_run_without_entering_worker(tmp_path, monkeypatch):
    import threading

    source = tmp_path / "fleet"
    source.mkdir()
    out = tmp_path / "share"
    entered = threading.Event()
    release = threading.Event()
    calls = []

    def worker(*args, **kwargs):
        calls.append("entered")
        entered.set()
        release.wait(2)
        return {"files": []}

    monkeypatch.setattr(ingest, "_run_redaction_folder_locked", worker)
    monkeypatch.setattr(ingest, "OUTPUT_LOCK_TIMEOUT_S", 0.1)
    thread = threading.Thread(
        target=ingest.run_redaction_folder, args=(source, out), daemon=True
    )
    thread.start()
    assert entered.wait(1)
    try:
        with pytest.raises(ingest.EngineRunError, match="Another redaction run"):
            ingest.run_redaction_folder(source, out)
    finally:
        release.set()
        thread.join(2)
    assert calls == ["entered"]


def test_verified_digest_mismatch_blocks_promotion(tmp_path):
    stage = tmp_path / "stage"
    out = tmp_path / "out"
    stage.mkdir()
    snap = stage / "Assessment_redacted.snapshot.json"
    snap.write_text(json.dumps(_safe_redacted_snapshot()), encoding="utf-8")
    proof = verifier.certify_shareable_artifacts(snap, ())
    snap.write_text(json.dumps({"leak": "10.20.30.40"}), encoding="utf-8")
    with pytest.raises(ingest.EngineRunError, match="independently verified"):
        ingest._promote_verified_delivery(
            stage,
            out,
            [snap],
            frozenset({snap.name}),
            proof,
        )
    assert not (out / snap.name).exists()


def test_snapshot_scanner_allows_only_schema_exact_contiguous_acl_wildcards(tmp_path):
    snapshot = _safe_redacted_snapshot()
    snapshot["acls"] = {"core": {"MGMT": [{"src": {"wild": "0.0.0.255"}}]}}
    path = tmp_path / "wildcard.snapshot.json"
    path.write_text(json.dumps(snapshot), encoding="utf-8")
    assert verifier.verify_shareable_artifacts(path, ()) == 0

    snapshot["acls"]["core"]["MGMT"][0]["src"]["wild"] = "10.20.30.40"
    path.write_text(json.dumps(snapshot), encoding="utf-8")
    with pytest.raises(verifier.RedactionVerificationError, match="IPv4"):
        verifier.verify_shareable_artifacts(path, ())


def test_snapshot_parser_turns_excessive_json_nesting_into_a_closed_failure(tmp_path):
    path = tmp_path / "deep.snapshot.json"
    depth = 2_000
    path.write_text(
        '{"devices":' + ("[" * depth) + "0" + ("]" * depth) + "}",
        encoding="utf-8",
    )
    # EITHER refusal layer satisfies the property. On 3.12+ the module's own depth budget fires
    # ("depth verification budget"); on 3.11 stdlib json's recursion ceiling fires FIRST and the
    # wrapper reports the file unreadable -- measured on the first py3.11 CI leg. Both are CLOSED
    # failures of the same input; pinning the layer made the test assert an implementation detail
    # that legitimately varies by Python version. A 500/crash would fail both branches.
    with pytest.raises(verifier.RedactionVerificationError,
                       match="depth verification budget|unreadable snapshot JSON"):
        verifier.verify_shareable_artifacts(path, ())


def _ooxml(path: Path, text: str, member: str = "word/document.xml") -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(member, f'<root evidence="{text}"><t>{text}</t></root>')


@pytest.mark.parametrize(
    "suffix,member",
    [
        (".xlsx", "xl/sharedStrings.xml"),
        (".docx", "word/document.xml"),
        (".pptx", "ppt/slides/slide1.xml"),
    ],
)
def test_each_ooxml_family_scans_text_and_attributes(tmp_path, suffix, member):
    snapshot = tmp_path / "safe.snapshot.json"
    snapshot.write_text(json.dumps(_safe_redacted_snapshot()), encoding="utf-8")
    artifact = tmp_path / f"deliverable{suffix}"
    _ooxml(artifact, "10.21.22.23", member)
    with pytest.raises(verifier.RedactionVerificationError, match="IPv4"):
        verifier.verify_shareable_artifacts(snapshot, [artifact])


def test_ooxml_joined_runs_and_html_embedded_payload_are_scanned(tmp_path):
    snapshot = tmp_path / "safe.snapshot.json"
    snapshot.write_text(json.dumps(_safe_redacted_snapshot()), encoding="utf-8")
    document = tmp_path / "split.docx"
    with zipfile.ZipFile(document, "w") as archive:
        archive.writestr(
            "word/document.xml",
            "<root><p><r><t>10.</t></r><r><t>31.32.33</t></r></p></root>",
        )
    with pytest.raises(verifier.RedactionVerificationError, match="IPv4"):
        verifier.verify_shareable_artifacts(snapshot, [document])

    html = tmp_path / "explorer.html"
    html.write_text(
        '<html><script>window.EMBEDDED_SNAPSHOT={"mac":"00:11:22:33:44:55"}</script></html>',
        encoding="utf-8",
    )
    with pytest.raises(verifier.RedactionVerificationError, match="MAC"):
        verifier.verify_shareable_artifacts(snapshot, [html])


def test_ooxml_dtd_or_entity_declarations_are_rejected_before_parsing(tmp_path):
    snapshot = tmp_path / "safe.snapshot.json"
    snapshot.write_text(json.dumps(_safe_redacted_snapshot()), encoding="utf-8")
    document = tmp_path / "entity.docx"
    with zipfile.ZipFile(document, "w") as archive:
        archive.writestr(
            "word/document.xml",
            '<!DOCTYPE root [<!ENTITY x "expanded">]><root>&x;</root>',
        )
    with pytest.raises(verifier.RedactionVerificationError, match="DTD/entity"):
        verifier.verify_shareable_artifacts(snapshot, [document])


def test_unsupported_or_corrupt_current_run_artifact_fails_closed(tmp_path):
    snapshot = tmp_path / "safe.snapshot.json"
    snapshot.write_text(json.dumps(_safe_redacted_snapshot()), encoding="utf-8")
    unsupported = tmp_path / "unsupported.docx"
    with zipfile.ZipFile(unsupported, "w") as archive:
        archive.writestr("word/embeddings/client.bin", b"opaque")
    with pytest.raises(verifier.RedactionVerificationError, match="unsupported"):
        verifier.verify_shareable_artifacts(snapshot, [unsupported])

    corrupt = tmp_path / "corrupt.xlsx"
    corrupt.write_bytes(b"not a zip")
    with pytest.raises(verifier.RedactionVerificationError, match="corrupt"):
        verifier.verify_shareable_artifacts(snapshot, [corrupt])


def test_ingest_route_passes_upload_spool_not_bytes_to_zip_runner(tmp_path, monkeypatch):
    monkeypatch.delenv("ASSESSHUB_TOKEN", raising=False)
    seen: dict[str, object] = {}

    def fake_runner(stream):
        seen["is_bytes"] = isinstance(stream, (bytes, bytearray))
        seen["seekable"] = stream.seekable()
        seen["prefix"] = stream.read(2)
        snap = _verified_snapshot()
        snap["interfaces"] = [{"switch": "sw1", "port": "Gi1"}]
        return snap, {
            "n_archive_files": 1,
            "n_device_dirs": 1,
            "devices": ["sw1"],
            "skipped_dirs": [],
            "devices_json": "synthesized",
            "engine_seconds": 0.01,
            "engine_log_tail": "",
            "verification": summary.snapshot_verification(snap),
        }

    monkeypatch.setattr(ingest, "run_collection_zip", fake_runner)
    app = app_module.create_app(db_path=str(tmp_path / "stream.db"))
    with TestClient(app, base_url="http://localhost") as client:
        campaign = client.post("/api/campaigns", json={"name": "stream"}).json()
        response = client.post(
            f"/api/campaigns/{campaign['id']}/ingest",
            files={"file": ("fleet.zip", b"PKstreamed", "application/zip")},
        )
    assert response.status_code == 201, response.text
    assert seen == {"is_bytes": False, "seekable": True, "prefix": b"PK"}
    verification = response.json()["summary"]["verification"]
    assert verification["status"] == "verified"
    assert verification["origin"] == summary.LOCAL_ENGINE_ORIGIN
    persisted = app.state.store.get_snapshot(response.json()["id"])
    assert persisted[summary.SNAPSHOT_PROVENANCE_KEY] == {
        "origin": summary.LOCAL_ENGINE_ORIGIN,
        "integrity_verified": True,
    }
    assert response.json()["ingest"]["verification"] == verification


def test_snapshot_route_does_not_call_uploadfile_read(tmp_path, monkeypatch):
    from starlette.datastructures import UploadFile

    async def forbidden_read(self, *_args, **_kwargs):
        raise AssertionError("handler copied UploadFile through read()")

    monkeypatch.setattr(UploadFile, "read", forbidden_read)
    app = app_module.create_app(db_path=str(tmp_path / "no-read.db"))
    with TestClient(app, base_url="http://localhost") as client:
        campaign = client.post("/api/campaigns", json={"name": "stream"}).json()
        response = client.post(
            f"/api/campaigns/{campaign['id']}/snapshots",
            files={"file": ("snapshot.json", json.dumps(_verified_snapshot()), "application/json")},
        )
    assert response.status_code == 201, response.text


def test_snapshot_parsers_reject_duplicate_object_keys_on_both_paths():
    with pytest.raises(HTTPException, match="duplicate JSON object key"):
        app_module._parse_snapshot_bytes(b'{"devices":{},"devices":{"sw1":{}}}')

    stream = io.BytesIO(
        b'{"devices":{},"data_authorities":{"oui":{"source_authoritative":false,'
        b'"source_authoritative":true}}}'
    )
    with pytest.raises(HTTPException, match="duplicate JSON object key"):
        app_module._parse_snapshot_stream(stream)


def test_snapshot_upload_route_rejects_duplicate_keys_before_storage(tmp_path):
    app = app_module.create_app(db_path=str(tmp_path / "duplicate.db"))
    with TestClient(app, base_url="http://localhost") as client:
        campaign = client.post("/api/campaigns", json={"name": "duplicates"}).json()
        response = client.post(
            f"/api/campaigns/{campaign['id']}/snapshots",
            files={
                "file": (
                    "duplicate.json",
                    '{"devices":{},"devices":{"sw1":{}}}',
                    "application/json",
                )
            },
        )
    assert response.status_code == 400
    assert "duplicate JSON object key" in response.json()["detail"]


def test_snapshot_upload_rejects_excessive_json_nesting_without_a_500(tmp_path):
    app = app_module.create_app(db_path=str(tmp_path / "deep-upload.db"))
    depth = 2_000
    payload = '{"devices":' + ("[" * depth) + "0" + ("]" * depth) + "}"
    with TestClient(app, base_url="http://localhost") as client:
        campaign = client.post("/api/campaigns", json={"name": "deep"}).json()
        response = client.post(
            f"/api/campaigns/{campaign['id']}/snapshots",
            files={"file": ("snapshot.json", payload, "application/json")},
        )
    assert response.status_code == 400
    # The PROPERTY is refusal-closed with a depth-shaped reason and no 500 -- which layer refused
    # varies by Python version: 3.12+ reaches the app's own guard ("nesting-depth limit"); on 3.11
    # stdlib json's recursion ceiling fires first ("maximum recursion depth exceeded while
    # decoding"). Both are the same fail-closed outcome; measured on the first py3.11 CI leg.
    detail = response.json()["detail"]
    assert ("nesting-depth limit" in detail) or ("recursion depth" in detail), detail


def test_request_body_spool_io_runs_off_the_event_loop(monkeypatch):
    io_threads: list[int] = []
    holder: dict[str, io.BytesIO] = {}

    class RecordingSpool(io.BytesIO):
        def _record(self):
            io_threads.append(threading.get_ident())

        def write(self, value):
            self._record()
            return super().write(value)

        def read(self, size=-1):
            self._record()
            return super().read(size)

        def seek(self, *args):
            self._record()
            return super().seek(*args)

        def tell(self):
            self._record()
            return super().tell()

        def close(self):
            self._record()
            return super().close()

    def spool_factory(*_args, **_kwargs):
        spool = RecordingSpool()
        holder["spool"] = spool
        return spool

    monkeypatch.setattr(app_module.tempfile, "SpooledTemporaryFile", spool_factory)

    async def inner(scope, receive, send):
        while True:
            message = await receive()
            if not message.get("more_body", False):
                break
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    middleware = app_module._RequestBodyLimitMiddleware(inner)

    async def exercise():
        loop_thread = threading.get_ident()
        sent = False

        async def receive():
            nonlocal sent
            if sent:
                return {"type": "http.disconnect"}
            sent = True
            return {"type": "http.request", "body": b'{"x":1}', "more_body": False}

        async def send(_message):
            return None

        scope = {
            "type": "http",
            "method": "POST",
            "path": "/api/example",
            "headers": [(b"content-type", b"application/json")],
            "query_string": b"",
            "server": ("localhost", 80),
            "client": ("127.0.0.1", 1234),
            "scheme": "http",
        }
        await middleware(scope, receive, send)
        return loop_thread

    loop_thread = asyncio.run(exercise())
    assert io_threads
    assert loop_thread not in io_threads


@pytest.mark.parametrize(
    "total_memory,expected",
    [
        (2 * 1024**3, 1),
        (4 * 1024**3, 1),
        (8 * 1024**3, 3),
        (64 * 1024**3, 4),
    ],
)
def test_heavy_concurrency_cap_is_memory_derived_and_hard_bounded(total_memory, expected):
    assert app_module._memory_safe_generation_cap(total_memory) == expected


def test_concurrency_env_override_cannot_exceed_memory_safe_cap(monkeypatch):
    monkeypatch.setattr(app_module, "_physical_memory_bytes", lambda: 8 * 1024**3)
    monkeypatch.setenv("ASSESSHUB_MAX_CONCURRENT_GENERATIONS", "999")
    assert app_module._max_concurrent_generations() == 3
    monkeypatch.setenv("ASSESSHUB_MAX_CONCURRENT_GENERATIONS", "1")
    assert app_module._max_concurrent_generations() == 1
    monkeypatch.setenv("ASSESSHUB_MAX_CONCURRENT_GENERATIONS", "not-a-number")
    assert app_module._max_concurrent_generations() == 3
