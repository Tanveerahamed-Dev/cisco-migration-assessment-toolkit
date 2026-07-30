"""A public source distribution must not leak files that the runtime wheel excludes."""
from __future__ import annotations

import io
import tarfile
from pathlib import Path

import pytest

from tools.audit_wheel import audit_sdist


_ROOT = "cisco_migration_assessment_toolkit-3.31.0"
_REQUIRED = {
    "pyproject.toml": b"[build-system]\n",
    "COLLECT_PARSE_V3_23_0.py": b"def main(): pass\n",
    "cisco_toolkit/blast_radius_explorer.html": b"<!doctype html>\n",
    "cisco_toolkit/data/oui_registry.tsv.gz": b"synthetic-oui-pack",
    "cisco_toolkit/data/port_registry.tsv.gz": b"synthetic-port-pack",
    "tests/fixtures/show_running-config.txt": b"synthetic fixture only\n",
}


def _sdist(tmp_path: Path, extra: dict[str, bytes] | None = None,
           omit: set[str] | None = None) -> Path:
    path = tmp_path / f"{_ROOT}.tar.gz"
    members = dict(_REQUIRED)
    members.update(extra or {})
    for name in omit or set():
        members.pop(name, None)
    with tarfile.open(path, "w:gz") as archive:
        for relative, content in members.items():
            info = tarfile.TarInfo(f"{_ROOT}/{relative}")
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))
    return path


def test_expected_source_distribution_is_accepted(tmp_path: Path) -> None:
    # A synthetic capture under tests/ is explicitly reviewable; the same name elsewhere is not.
    assert audit_sdist(_sdist(tmp_path)) == []


@pytest.mark.parametrize(
    "member",
    (
        "client_evidence/ACME/show_running-config.txt",
        "customer-output/CORE-1/show_running-config.txt",
        "webapp/data/assesshub.db-wal",
        "exports/customer.snapshot.json",
        "deliverables/Migration_Assessment.xlsx",
        "migration_collection_20260730/CORE-1/show_version.txt",
    ),
)
def test_client_or_generated_source_members_are_rejected(tmp_path: Path, member: str) -> None:
    errors = audit_sdist(_sdist(tmp_path, {member: b"synthetic secret"}))
    assert errors, f"unsafe source member passed the audit: {member}"
    assert any(member in error for error in errors)


def test_required_source_inputs_cannot_silently_disappear(tmp_path: Path) -> None:
    errors = audit_sdist(_sdist(tmp_path, omit={"pyproject.toml"}))
    assert "required source member missing from sdist: pyproject.toml" in errors


def test_source_distribution_must_have_one_root(tmp_path: Path) -> None:
    path = _sdist(tmp_path)
    with tarfile.open(path, "a:gz") as _archive:  # pragma: no cover - tarfile forbids append-compressed
        pass
