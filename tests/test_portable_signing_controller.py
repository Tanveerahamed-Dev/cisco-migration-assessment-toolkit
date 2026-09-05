from __future__ import annotations

import hashlib
import json
import os
import struct
import subprocess
from pathlib import Path

import pytest

from portable import package_signed_release, prepare_signing
from portable.release_contract import PortableReleaseError, canonical_json, collect_members


def _git(root: Path, *args: str) -> None:
    environment = dict(os.environ)
    environment.update({
        "GIT_AUTHOR_NAME": "Atlas Test",
        "GIT_AUTHOR_EMAIL": "atlas@example.invalid",
        "GIT_COMMITTER_NAME": "Atlas Test",
        "GIT_COMMITTER_EMAIL": "atlas@example.invalid",
    })
    result = subprocess.run(
        ["git", *args], cwd=root, env=environment, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr


def _pe(marker: int) -> bytes:
    value = bytearray(512)
    value[:2] = b"MZ"
    value[2] = marker
    struct.pack_into("<I", value, 0x3C, 0x80)
    value[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<H", value, 0x84, 0x8664)
    return bytes(value)


def _repo_and_bundle(tmp_path: Path) -> tuple[Path, Path]:
    repository = tmp_path / "repo"
    repository.mkdir()
    _git(repository, "init", "-q")
    _git(repository, "remote", "add", "origin", "https://example.invalid/owner/atlas.git")
    (repository / "pyproject.toml").write_text(
        '[project]\nname="atlas-test"\nversion="9.9.9"\n', encoding="utf-8"
    )
    (repository / "webapp" / "frontend").mkdir(parents=True)
    (repository / "webapp" / "frontend" / "package-lock.json").write_text("{}\n")
    (repository / "portable").mkdir()
    (repository / "portable" / "windows-x64-requirements.lock").write_text("# test\n")
    _git(repository, "add", ".")
    _git(repository, "commit", "-qm", "fixture")
    bundle = tmp_path / "bundle"
    (bundle / "_internal").mkdir(parents=True)
    (bundle / "Atlas.exe").write_bytes(_pe(1))
    (bundle / "README-FIELD.txt").write_text("guide\n")
    (bundle / "LICENSE").write_text("license\n")
    (bundle / "_internal" / "runtime.bin").write_bytes(b"runtime")
    return repository, bundle


def test_prepare_signing_emits_distinct_fresh_exact_evidence(tmp_path: Path) -> None:
    repository, bundle = _repo_and_bundle(tmp_path)
    manifest = tmp_path / "evidence" / "manifest.json"
    toolchain = tmp_path / "evidence" / "toolchain.json"
    result = prepare_signing.prepare(
        bundle,
        manifest,
        toolchain,
        repository_root=repository,
    )
    assert result["executable_member_count"] == 1
    assert manifest.read_bytes() == canonical_json(json.loads(manifest.read_bytes()))
    assert toolchain.read_bytes() == canonical_json(json.loads(toolchain.read_bytes()))
    with pytest.raises(PortableReleaseError, match="distinct"):
        prepare_signing.prepare(
            bundle,
            tmp_path / "same.json",
            tmp_path / "same.json",
            repository_root=repository,
        )
    with pytest.raises(PortableReleaseError, match="fresh"):
        prepare_signing.prepare(
            bundle,
            manifest,
            tmp_path / "new-toolchain.json",
            repository_root=repository,
        )


def test_signed_controller_binds_pre_sign_non_pe_and_toolchain_transition(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repository, bundle = _repo_and_bundle(tmp_path)
    pre_manifest_path = tmp_path / "pre-manifest.json"
    pre_toolchain_path = tmp_path / "pre-toolchain.json"
    prepare_signing.prepare(
        bundle,
        pre_manifest_path,
        pre_toolchain_path,
        repository_root=repository,
    )
    pre_manifest = json.loads(pre_manifest_path.read_bytes())
    pre_toolchain = json.loads(pre_toolchain_path.read_bytes())
    signing_path = tmp_path / "signing.json"
    signing_path.write_text(json.dumps({
        "pre_sign_subject": {
            "source": pre_manifest["source"],
            "manifest_sha256": hashlib.sha256(pre_manifest_path.read_bytes()).hexdigest(),
            "member_set_digest": pre_manifest["summary"]["member_set_digest"],
            "executable_member_count": 1,
        },
        "members": [
            {"path": row["path"], "sha256": row["sha256"]}
            for row in collect_members(bundle)
            if row["executable"]
        ],
    }))
    captured = {}
    monkeypatch.setattr(package_signed_release, "ROOT", repository)
    monkeypatch.setattr(package_signed_release, "verify_toolchain", lambda: {})
    monkeypatch.setattr(package_signed_release, "toolchain_receipt", lambda _root: pre_toolchain)
    monkeypatch.setattr(
        package_signed_release,
        "_independent_authenticode",
        lambda _bundle, _source: {"schema": "test-auth"},
    )
    monkeypatch.setattr(package_signed_release.qualify_atlas, "qualify", lambda *_args: {})

    def package(*args, **kwargs):
        captured["signing"] = kwargs["signing"]
        captured["toolchain"] = kwargs["expected_toolchain"]
        return {"zip": {"name": "synthetic.zip"}}

    monkeypatch.setattr(package_signed_release, "build_portable_release", package)
    monkeypatch.setattr(
        package_signed_release,
        "verify_release_set",
        lambda *_args, **_kwargs: {"status": "SELF_CONSISTENCY_PASS"},
    )
    result = package_signed_release.package_signed(
        bundle,
        signing_path,
        pre_manifest_path,
        pre_toolchain_path,
        tmp_path / "release",
    )
    assert result["verification"]["status"] == "SELF_CONSISTENCY_PASS"
    assert captured["signing"]["pre_sign_manifest"] == pre_manifest
    assert captured["toolchain"] == pre_toolchain

    (bundle / "_internal" / "runtime.bin").write_bytes(b"changed")
    with pytest.raises(PortableReleaseError, match="non-PE"):
        package_signed_release.package_signed(
            bundle,
            signing_path,
            pre_manifest_path,
            pre_toolchain_path,
            tmp_path / "other-release",
        )
