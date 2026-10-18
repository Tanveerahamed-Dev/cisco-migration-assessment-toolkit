"""The maintenance source view admits only manifest-owned code before copying."""

from __future__ import annotations

import hashlib
from pathlib import Path
import zipfile

import pytest

from portable import release_contract as subject
from test_portable_release_contract import _bundle, _qualification, _repository


@pytest.fixture
def installed(tmp_path: Path) -> Path:
    repository = _repository(tmp_path)
    bundle = _bundle(tmp_path)
    source = subject.source_identity(repository)
    output = tmp_path / "release"
    index = subject.build_portable_release(repository, bundle, output, _qualification(source, bundle))
    with zipfile.ZipFile(output / index["zip"]["name"]) as archive:
        archive.extractall(tmp_path / "installed")
    return tmp_path / "installed" / "Atlas"


def test_verified_code_view_never_stats_or_traverses_live_client_data(installed, monkeypatch):
    data = installed / "data"
    data.mkdir()
    (data / "client.bin").write_bytes(b"synthetic client evidence")
    original = Path.lstat

    def guarded(path, *args, **kwargs):
        assert path != data and data not in path.parents, "maintenance touched client data"
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", guarded)
    rows = subject.verified_application_entries(installed)
    assert rows and all(name.split("/", 1)[0].casefold() != "data" for name, *_ in rows)
    for _name, path, _metadata, digest in rows:
        if digest is not None:
            assert hashlib.sha256(path.read_bytes()).hexdigest() == digest


@pytest.mark.parametrize("unexpected", ["raw-capture.bin", "nested/capture.bin", "unowned-empty/"])
def test_source_census_refuses_unowned_content_before_returning_any_allowlist(installed, unexpected):
    path = installed / unexpected
    if unexpected.endswith("/"):
        path.mkdir()
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"synthetic client bytes outside data")
    captured = []
    with pytest.raises(subject.PortableReleaseError):
        subject.verify_installed_bundle(installed, _maintenance_entries=captured)
    assert captured == []


def test_default_staged_verification_still_refuses_client_data(installed):
    data = installed / "data"
    data.mkdir()
    (data / "client.bin").write_bytes(b"retained client bytes")
    with pytest.raises(subject.PortableReleaseError, match="client data"):
        subject.verify_installed_bundle(installed)
    assert subject.verified_application_entries(installed)


def test_code_only_view_keeps_manifest_and_checksum_integrity_checks(installed):
    payload = installed / "_internal" / "runtime.bin"
    payload.write_bytes(b"changed code")
    with pytest.raises(subject.PortableReleaseError, match="checksum differs"):
        subject.verified_application_entries(installed)
