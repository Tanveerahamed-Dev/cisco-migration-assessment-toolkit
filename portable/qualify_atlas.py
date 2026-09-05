"""Run the automated Windows qualification available on the build host."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import shutil
import socket
import sqlite3
import stat
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from portable import build_atlas
from portable.release_contract import (
    QUALIFICATION_SCHEMA,
    INTERNET_ABSENCE_BOUNDARY,
    PYTHON_ABSENCE_BOUNDARY,
    WARNING_LOG_BOUNDARY,
    PortableReleaseError,
    collect_members,
    digest_object,
    source_identity,
)


_REDACTION_CANARIES = (
    "10.203.113.47",
    "0a1b.2c3d.4e5f",
    "0a:1b:2c:3d:4e:5f",
    "FOC1234ABCD",
    "AtlasCanaryCommunity7f4c29",
)
_PSEUDONYM_MARKER = "assesshub-redacted.invalid"
_RAW_SECRET_CANARIES = (
    "AtlasCanaryCommunity7f4c29",
    "AtlasCanaryBackupSecret91",
)


def _run(command: list[str], *, environment: dict[str, str], timeout: int = 600) -> subprocess.CompletedProcess:
    working_directory = Path(environment["TEMP"]).resolve(strict=True)
    return subprocess.run(
        command,
        env=environment,
        cwd=str(working_directory),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )


def _port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _offline_environment(profile: Path) -> dict[str, str]:
    environment = dict(os.environ)
    system_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    environment["PATH"] = str(system_root / "System32")
    for key in (
        "PYTHONHOME",
        "PYTHONPATH",
        "VIRTUAL_ENV",
        "CONDA_PREFIX",
        "ATLAS_PORTABLE_ALLOW_LIVE_NETWORK",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
    ):
        environment.pop(key, None)
    environment["NO_PROXY"] = "127.0.0.1,localhost,::1"
    environment["USERPROFILE"] = str(profile)
    environment["TEMP"] = str(profile / "Temp")
    environment["TMP"] = str(profile / "Temp")
    Path(environment["TEMP"]).mkdir(parents=True, exist_ok=True)
    return environment


def _sanitize_warning_report(raw: bytes, private_roots: set[str]) -> str:
    text = raw.decode("utf-8", errors="strict")
    for private_root in private_roots:
        for spelling in {private_root, private_root.replace("\\", "/")}:
            text = re.sub(re.escape(spelling), "<BUILD_ROOT>", text, flags=re.IGNORECASE)
    text = "\n".join(text.splitlines()) + "\n"
    if (
        re.search(r"(?i)\b[A-Z]:[\\/]", text)
        or re.search(r"(?:^|\s)\\\\(?:\?|\.|[^\\\s]+)\\", text)
        or re.search(r"(?<!:)(?:^|\s)//[^/\s]+/", text)
    ):
        raise PortableReleaseError("PyInstaller warning report retains an absolute Windows path")
    return text


def _python_absent(environment: dict[str, str]) -> bool:
    where = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "where.exe"
    if not where.is_file():
        return False
    for name in ("python.exe", "python3.exe", "pythonw.exe", "py.exe", "pip.exe", "pip3.exe"):
        result = _run([str(where), name], environment=environment, timeout=20)
        if result.returncode == 0:
            return False
        if result.returncode != 1:
            return False
    return True


def _drive_letters(parent: Path, bundle_name: str, environment: dict[str, str]) -> list[dict[str, Any]]:
    if os.name != "nt":
        return [{"status": "not_run_non_windows"}]
    subst = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "subst.exe"
    available = [letter for letter in "RSTUVWXYZ" if not Path(f"{letter}:\\").exists()][:2]
    if len(available) < 2:
        raise PortableReleaseError("two free drive letters are unavailable for replay")
    results = []
    for letter in available:
        mapped = f"{letter}:"
        create = subprocess.run([str(subst), mapped, str(parent)], capture_output=True, check=False)
        if create.returncode:
            raise PortableReleaseError(f"could not create SUBST drive {mapped}")
        try:
            exe = Path(mapped + "\\") / bundle_name / "Atlas.exe"
            db = Path(mapped + "\\") / bundle_name / f"qualification-{letter}" / "hub.db"
            version = _run([str(exe), "--version"], environment=environment, timeout=120)
            selftest = _run(
                [str(exe), "--selftest", "--db", str(db)],
                environment=environment,
                timeout=300,
            )
            if version.returncode or selftest.returncode or "SELFTEST: PASS" not in selftest.stdout:
                raise PortableReleaseError(f"portable replay failed on drive {mapped}")
            results.append({"drive": mapped, "version": "pass", "selftest": "pass"})
        finally:
            removed = subprocess.run(
                [str(subst), mapped, "/D"], capture_output=True, check=False
            )
            if removed.returncode or Path(mapped + "\\").exists():
                raise PortableReleaseError(f"SUBST drive {mapped} teardown was not verified")
    return results


def _scan_redaction_canaries(output: Path, canaries: tuple[str, ...]) -> dict[str, Any]:
    payload_count = 0
    marker_seen = False
    total = 0

    def inspect(value: bytes, where: str) -> None:
        nonlocal marker_seen, payload_count, total
        total += len(value)
        if total > 512 * 1024 * 1024:
            raise PortableReleaseError("redaction canary scan exceeded its 512 MiB total bound")
        payload_count += 1
        for index, canary in enumerate(canaries, start=1):
            encoded = canary.encode("utf-8")
            if encoded in value or canary.encode("utf-16-le") in value:
                raise PortableReleaseError(
                    f"redaction canary #{index} survived in {where}"
                )
        marker = _PSEUDONYM_MARKER.encode("ascii")
        marker_seen = marker_seen or marker in value or _PSEUDONYM_MARKER.encode("utf-16-le") in value

    for path in sorted(
        output.rglob("*"), key=lambda candidate: candidate.relative_to(output).as_posix().casefold()
    ):
        if path.is_symlink():
            raise PortableReleaseError("redaction output canary scan refuses symbolic links")
        if not path.is_file():
            continue
        relative = path.relative_to(output).as_posix()
        raw = path.read_bytes()
        if len(raw) > 128 * 1024 * 1024:
            raise PortableReleaseError(f"redaction output exceeds 128 MiB canary bound: {path.name}")
        inspect(raw, relative)
        if path.suffix.casefold() not in {".docx", ".pptx", ".xlsx"}:
            continue
        try:
            with zipfile.ZipFile(path) as archive:
                infos = archive.infolist()
                if len(infos) > 10_000:
                    raise PortableReleaseError(f"redaction container has too many members: {path.name}")
                for info in infos:
                    if info.is_dir():
                        continue
                    if info.file_size < 0 or info.file_size > 64 * 1024 * 1024:
                        raise PortableReleaseError(
                            f"redaction container member exceeds 64 MiB: {path.name}:{info.filename}"
                        )
                    inspect(archive.read(info), f"{relative}:{info.filename}")
        except zipfile.BadZipFile as exc:
            raise PortableReleaseError(f"redaction OOXML container is invalid: {path.name}") from exc
    if not marker_seen:
        raise PortableReleaseError("redaction output contains no expected pseudonym namespace marker")
    return {
        "canary_literal_count": len(canaries),
        "payload_count": payload_count,
        "canary_literals_absent": True,
        "pseudonym_namespace_present": True,
    }


def _redaction(exe: Path, root: Path, environment: dict[str, str]) -> dict[str, Any]:
    collection = root / "synthetic-collection" / "core1"
    collection.mkdir(parents=True)
    (collection / "show_version.txt").write_text(
        "Cisco IOS XE Software, Version 17.12.1\nProcessor board ID FOC1234ABCD\n",
        encoding="utf-8",
    )
    (collection / "show_running_config.txt").write_text(
        "hostname SYNTHETIC-CORE1\ninterface GigabitEthernet1/0/1\n description TEST-ONLY\n"
        " ip address 10.203.113.47 255.255.255.0\n mac-address 0a1b.2c3d.4e5f\n"
        " switchport access vlan 10\nsnmp-server community AtlasCanaryCommunity7f4c29 RO\n!\n",
        encoding="utf-8",
    )
    (collection / "show_ip_arp.txt").write_text(
        "Internet  10.203.113.47  1  0a1b.2c3d.4e5f  ARPA  Vlan10\n",
        encoding="utf-8",
    )
    (collection / "show_inventory.txt").write_text(
        'NAME: "Chassis", DESCR: "Synthetic"\nPID: C9300-24T, VID: V01, SN: FOC1234ABCD\n',
        encoding="utf-8",
    )
    (collection / "backup-config.cfg").write_text(
        "username synthetic privilege 1 secret AtlasCanaryBackupSecret91\n",
        encoding="utf-8",
    )
    output = root / "redacted-output"
    result = _run(
        [
            str(exe),
            "--redact-folder",
            str(collection.parent),
            "--out",
            str(output),
            "--redact-collection",
        ],
        environment=environment,
        timeout=1800,
    )
    if result.returncode != 0:
        raise PortableReleaseError(
            f"frozen redaction failed ({result.returncode}): {(result.stdout + result.stderr)[-1000:]}"
        )
    manifest = next(output.glob("*.run_manifest.json"), None)
    if manifest is None:
        raise PortableReleaseError("frozen redaction produced no run manifest")
    verify = _run(
        [str(exe), "--verify-manifest", str(manifest)],
        environment=environment,
        timeout=300,
    )
    if verify.returncode or "manifest OK" not in verify.stdout:
        raise PortableReleaseError("frozen redaction manifest verification failed")
    files = []
    for path in sorted(output.rglob("*"), key=lambda item: item.relative_to(output).as_posix()):
        metadata = path.lstat()
        reparse = int(getattr(metadata, "st_file_attributes", 0)) & int(
            getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        )
        relative = path.relative_to(output)
        if path.is_symlink() or reparse:
            raise PortableReleaseError("frozen redaction output contains a link/reparse member")
        if path.is_dir():
            raise PortableReleaseError("frozen redaction output contains an unowned nested directory")
        if len(relative.parts) != 1 or not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise PortableReleaseError("frozen redaction output contains an unowned physical member")
        files.append(path)
    from cisco_toolkit import manifest as manifest_module
    from webapp.backend import ingest as ingest_module
    from webapp.backend import redaction_verify

    expected_names = ingest_module.redaction_delivery_filenames()
    observed_names = {path.name for path in files}
    if observed_names != expected_names:
        raise PortableReleaseError(
            "frozen redaction artifact denominator differs: "
            f"missing={sorted(expected_names - observed_names)}, "
            f"extra={sorted(observed_names - expected_names)}"
        )
    independent_manifest = manifest_module.verify_file(str(manifest))
    if (
        independent_manifest.get("ok") is not True
        or any(row.get("state") != "ok" for row in independent_manifest.get("artifacts", []))
    ):
        raise PortableReleaseError("source-side independent manifest verification failed")
    snapshot = output / "Assessment_redacted.snapshot.json"
    shareable = [
        path
        for path in files
        if path != snapshot
        and not path.name.endswith((".run_manifest.json", ".phase_timings.json"))
    ]
    independent_redaction = redaction_verify.certify_shareable_artifacts(snapshot, shareable)
    if set(independent_redaction) != {snapshot.name, *(path.name for path in shareable)}:
        raise PortableReleaseError("source-side redaction proof denominator differs")
    canary_evidence = _scan_redaction_canaries(output, _REDACTION_CANARIES)
    raw_secret_proof = redaction_verify.verify_collection_secret_scrub(collection.parent)
    if raw_secret_proof.get("files") != 5 or raw_secret_proof.get("uncovered") != []:
        raise PortableReleaseError("source-side raw secret proof denominator differs")
    for capture in collection.parent.rglob("*"):
        if capture.is_file():
            raw_capture = capture.read_bytes()
            if any(canary.encode("ascii") in raw_capture for canary in _RAW_SECRET_CANARIES):
                raise PortableReleaseError("raw secret canary survived outside the shareable output")
    return {
        "status": "pass",
        "artifact_count": len(files),
        "manifest_verified": True,
        "independent_manifest_artifact_count": len(independent_manifest["artifacts"]),
        "independent_redaction_artifact_count": len(independent_redaction),
        "independent_redaction_proof_digest": digest_object(independent_redaction),
        "raw_secret_canary_scrubbed": True,
        "raw_capture_secret_file_count": raw_secret_proof["files"],
        "raw_secret_canary_count": len(_RAW_SECRET_CANARIES),
        "raw_capture_secret_proof_digest": raw_secret_proof["sha256"],
        **canary_evidence,
    }


def _database_preflight_case(
    exe: Path,
    source: Path,
    copy: Path,
    environment: dict[str, str],
    *,
    expected_counts: dict[str, int],
    expect_migration: bool,
) -> dict[str, Any]:
    from portable.database_preflight import census, verify_migrated_copy

    source_bytes = source.read_bytes()
    source_sha256 = hashlib.sha256(source_bytes).hexdigest()
    copy.parent.mkdir()
    shutil.copy2(source, copy)
    copy_bytes = copy.read_bytes()
    copy_sha256 = hashlib.sha256(copy_bytes).hexdigest()
    if copy_sha256 != source_sha256 or len(copy_bytes) != len(source_bytes):
        raise PortableReleaseError("database preflight copy differs from its source")
    before_census = census(copy)
    nonce = secrets.token_hex(16)
    request = {
        "schema": "atlas.database-preflight-request/1",
        "nonce": nonce,
        "database_name": copy.name,
        "input_copy_sha256": copy_sha256,
        "input_copy_bytes": len(copy_bytes),
        "requested_action": "open_migrate_copy_and_report",
    }
    request_bytes = (
        json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    (copy.parent / "atlas-db-preflight.json").write_bytes(request_bytes)
    preflight_env = dict(environment)
    preflight_env["ATLAS_PORTABLE_DATABASE_PREFLIGHT"] = nonce
    result = _run(
        [str(exe), "--database-preflight", str(copy)],
        environment=preflight_env,
        timeout=300,
    )
    if result.returncode:
        raise PortableReleaseError(f"database preflight failed: {(result.stdout + result.stderr)[-800:]}")
    try:
        receipt = json.loads(result.stdout.splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as exc:
        raise PortableReleaseError("database preflight emitted no machine receipt") from exc
    binding = receipt.get("input_copy_binding", {})
    row_counts = receipt.get("row_counts", {})
    logical = receipt.get("logical_migration", {})
    preservation = logical.get("prior_table_preservation", [])
    if (
        receipt.get("status") != "pass"
        or receipt.get("request_nonce") != nonce
        or receipt.get("request_sha256") != hashlib.sha256(request_bytes).hexdigest()
        or binding.get("database_name") != copy.name
        or binding.get("sha256") != copy_sha256
        or binding.get("bytes") != len(copy_bytes)
        or receipt.get("quick_check") != "ok"
        or not isinstance(row_counts, dict)
        or any(row_counts.get(table) != count for table, count in expected_counts.items())
        or logical.get("schema") != "atlas.database-logical-migration/1"
        or logical.get("status") != "pass"
        or logical.get("before", {}).get("quick_check") != "ok"
        or logical.get("after", {}).get("quick_check") != "ok"
        or not isinstance(preservation, list)
        or len(preservation) != logical.get("before", {}).get("table_count")
        or any(item.get("status") != "preserved" for item in preservation)
        or receipt.get("caller_supplied_database_modified") is not expect_migration
        or receipt.get("authority_effect") != "NONE"
    ):
        raise PortableReleaseError("database preflight row census differs")
    migrated_bytes = copy.read_bytes()
    if (
        hashlib.sha256(migrated_bytes).hexdigest() != receipt.get("migrated_copy_sha256")
        or len(migrated_bytes) != receipt.get("migrated_copy_bytes")
    ):
        raise PortableReleaseError("database preflight migrated-copy byte identity differs")
    independent_logical = verify_migrated_copy(copy, before_census)
    if independent_logical != logical:
        raise PortableReleaseError("database preflight logical receipt differs from independent census")
    if hashlib.sha256(source.read_bytes()).hexdigest() != source_sha256:
        raise PortableReleaseError("database preflight modified its source store")
    return {
        "status": "pass",
        "copy_migrated": receipt["caller_supplied_database_modified"],
        "source_store_unchanged": True,
        "row_counts": row_counts,
        "before_table_count": logical["before"]["table_count"],
        "after_table_count": logical["after"]["table_count"],
        "before_table_set_digest": logical["before"]["table_set_digest"],
        "after_table_set_digest": logical["after"]["table_set_digest"],
        "prior_table_preservation_digest": logical["prior_table_preservation_digest"],
        "request_sha256": receipt["request_sha256"],
        "source_sha256": source_sha256,
        "migrated_copy_sha256": receipt["migrated_copy_sha256"],
    }


def _database_preflight(
    exe: Path,
    root: Path,
    environment: dict[str, str],
    repository: Path,
) -> dict[str, Any]:
    from webapp.backend.storage import Store

    active = root / "active-data" / "assesshub.db"
    store = Store(active)
    store.create_campaign("Portable qualification", "synthetic")
    store.close()
    current = _database_preflight_case(
        exe,
        active,
        root / "db-copy" / "assesshub.db",
        environment,
        expected_counts={
            "campaigns": 1,
            "snapshots": 0,
            "executions": 0,
            "execution_comparisons": 0,
        },
        expect_migration=False,
    )

    fixture = repository / "tests" / "fixtures" / "assesshub-v3.32.1.sql"
    fixture_bytes = fixture.read_bytes()
    fixture_text = fixture_bytes.decode("utf-8", errors="strict")
    for required in (
        "-- atlas.prior-database-fixture/1\n",
        "-- source_commit=47a1ff993f3bb9c9b2e4a138be6f073c8614498e\n",
        "-- source_tree=d4f9db52c0703ab02f25c3f4913d53baac8ddb60\n",
        "-- storage_git_blob_sha256=f1d8f829c129db35763763b05e05c1220907f5ec851983cd3a4ba3e3208ca976\n",
        "-- synthetic_data_only=true\n",
    ):
        if required not in fixture_text:
            raise PortableReleaseError("prior-release database fixture provenance differs")
    if hashlib.sha256(fixture_bytes).hexdigest() != (
        "2f47480d06ec6b87dfd42b88f61f6f7d4d2db7dccc7384ac0e255f3dd2b05382"
    ):
        raise PortableReleaseError("prior-release database fixture bytes differ")
    prior = root / "prior-release-source" / "assesshub.db"
    prior.parent.mkdir()
    connection = sqlite3.connect(prior)
    try:
        connection.executescript(fixture_text)
    finally:
        connection.close()
    prior_result = _database_preflight_case(
        exe,
        prior,
        root / "prior-release-copy" / "assesshub.db",
        environment,
        expected_counts={
            "campaigns": 1,
            "snapshots": 1,
            "executions": 1,
            "execution_comparisons": 0,
        },
        expect_migration=True,
    )
    prior_result["fixture_sha256"] = hashlib.sha256(fixture_bytes).hexdigest()
    prior_result["fixture_source_commit"] = "47a1ff993f3bb9c9b2e4a138be6f073c8614498e"
    prior_result["fixture_source_tree"] = "d4f9db52c0703ab02f25c3f4913d53baac8ddb60"
    return {"same_version": current, "prior_release_v3_32_1": prior_result}


def qualify(repository_root: str | Path, bundle_root: str | Path, *, run_redaction: bool = True) -> dict[str, Any]:
    repository = Path(repository_root).resolve(strict=True)
    bundle = Path(bundle_root).resolve(strict=True)
    if os.name != "nt":
        raise PortableReleaseError("portable qualification requires Windows")
    source = source_identity(repository)
    members = collect_members(bundle)
    warning_report = repository / "portable" / "build" / "atlas" / "warn-atlas.txt"
    if not warning_report.is_file():
        raise PortableReleaseError("PyInstaller warning report is missing")
    warning_bytes = warning_report.read_bytes()
    warning_text = _sanitize_warning_report(
        warning_bytes,
        {
            str(repository),
            str(Path(sys.prefix).resolve()),
            str(Path(sys.base_prefix).resolve()),
            str(Path(sys.executable).resolve().parent),
        },
    )
    sanitized_warning = warning_text.encode("utf-8")
    with tempfile.TemporaryDirectory(prefix="atlas-portable-qualification-") as temporary:
        root = Path(temporary)
        profile = root / "profile-شبكة"
        environment = _offline_environment(profile)
        if not _python_absent(environment):
            raise PortableReleaseError("qualification PATH still exposes Python or pip")
        relocated_parent = root / "relocated-路径"
        relocated = relocated_parent / "Atlas-unicode"
        shutil.copytree(bundle, relocated)
        if collect_members(relocated) != members:
            raise PortableReleaseError("relocated qualification bundle differs before execution")
        smoke = build_atlas.smoke(_port(), dist=relocated, environment=environment)
        drives = _drive_letters(relocated_parent, relocated.name, environment)
        database = _database_preflight(
            relocated / "Atlas.exe", root, environment, repository,
        )
        redaction = (
            _redaction(relocated / "Atlas.exe", root, environment)
            if run_redaction
            else {"status": "not_run"}
        )
        if collect_members(relocated) != members:
            raise PortableReleaseError("relocated qualification bundle changed during execution")
    checks = [
        {"id": key, "status": value} for key, value in sorted(smoke.items())
    ] + [
        {"id": "python_tools_absent_from_path", "status": "pass"},
        {"id": "non_ascii_profile_and_install_path", "status": "pass"},
        {"id": "drive_letter_replay", "status": "pass", "evidence": drives},
        {
            "id": "same_version_database_copy_integrity",
            "status": database["same_version"]["status"],
            "evidence": database["same_version"],
        },
        {
            "id": "prior_release_database_forward_compatibility",
            "status": database["prior_release_v3_32_1"]["status"],
            "evidence": database["prior_release_v3_32_1"],
        },
        {"id": "frozen_redaction_and_manifest", "status": redaction["status"], "evidence": redaction},
    ]
    if any(item["status"] != "pass" for item in checks):
        raise PortableReleaseError("automated portable qualification did not pass every requested check")
    return {
        "schema": QUALIFICATION_SCHEMA,
        "status": "AUTOMATED_PASS_EXTERNAL_GATES_PENDING",
        "source": source,
        "bundle_member_set_digest": digest_object(members),
        "checks": checks,
        "pyinstaller_warning_report": {
            "raw_bytes": len(warning_bytes),
            "raw_sha256": hashlib.sha256(warning_bytes).hexdigest(),
            "sanitized_content": warning_text,
            "sanitized_bytes": len(sanitized_warning),
            "sanitized_sha256": hashlib.sha256(sanitized_warning).hexdigest(),
            "nonblank_lines": sum(1 for line in sanitized_warning.splitlines() if line.strip()),
            "status": "disclosed_optional_import_report_not_silently_discarded",
            "sanitization": "known build roots replaced; LF-normalized; remaining drive paths refused",
            "builder_console_log": WARNING_LOG_BOUNDARY,
        },
        "python_absence_evidence": PYTHON_ABSENCE_BOUNDARY,
        "internet_absence_evidence": INTERNET_ABSENCE_BOUNDARY,
        "field_qualified": False,
        "external_pending": [
            "production_authenticode_certificate_and_rfc3161_timestamp",
            "clean_managed_windows_smartscreen_smart_app_control_policy_run",
            "managed_applocker_or_app_control_policy_run",
            "physical_usb_full_and_read_only_media_tests",
            "physical_unplug_during_update_and_database_write",
            "bitlocker_to_go_recovery_key_custody_and_restore_drill",
            "actual_host_with_python_not_installed_and_nic_disconnected",
            "display_scaling_100_and_150_percent",
            "live_aaa_credential_rotation_confirmation",
            "independent_human_peer_review",
            "third_party_dataset_redistribution_legal_review",
            "physical_drive_unicode_and_full_workflow_pilot",
            "physical_database_recovery_and_rollback_drill",
            "field_operator_acceptance",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=str(build_atlas.ROOT))
    parser.add_argument("--bundle", default=str(build_atlas.DIST))
    parser.add_argument("--out", required=True)
    parser.add_argument("--skip-redaction", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        receipt = qualify(args.repo, args.bundle, run_redaction=not args.skip_redaction)
        Path(args.out).write_bytes(json.dumps(receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8") + b"\n")
    except (OSError, PortableReleaseError, subprocess.SubprocessError) as exc:
        print(f"portable qualification REFUSED: {exc}")
        return 1
    print(f"portable qualification: {receipt['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
