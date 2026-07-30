"""The distribution-content gate must inspect the built artifact, not just pyproject.toml."""
from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from tools.audit_wheel import audit_wheel


_REQUIRED = {
    "COLLECT_PARSE_V3_23_0.py": "def main(): pass\n",
    "cisco_toolkit/__init__.py": "\n",
    "cisco_toolkit/blast_radius_explorer.html": "<!doctype html>\n",
    "cisco_toolkit/data/oui_registry.tsv.gz": "synthetic-oui-pack",
    "cisco_toolkit/data/port_registry.tsv.gz": "synthetic-port-pack",
    "webapp/backend/__init__.py": "\n",
    "cisco_migration_assessment_toolkit-3.31.0.dist-info/METADATA": "Name: test\n",
    "cisco_migration_assessment_toolkit-3.31.0.dist-info/WHEEL": "Wheel-Version: 1.0\n",
    "cisco_migration_assessment_toolkit-3.31.0.dist-info/RECORD": "\n",
}


def _wheel(tmp_path: Path, extra: dict[str, str] | None = None,
           omit: set[str] | None = None) -> Path:
    path = tmp_path / "toolkit-3.31.0-py3-none-any.whl"
    members = dict(_REQUIRED)
    members.update(extra or {})
    for name in omit or set():
        members.pop(name, None)
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in members.items():
            archive.writestr(name, content)
    return path


def test_expected_runtime_wheel_is_accepted(tmp_path: Path) -> None:
    assert audit_wheel(_wheel(tmp_path)) == []


@pytest.mark.parametrize(
    "member",
    (
        "cisco_toolkit/client_evidence/ACME/show_running-config.txt",
        "webapp/data/assesshub.db",
        "migration_collection_20260730/CORE-1/show_version.txt",
        "cisco_toolkit/data/customer.snapshot.json",
        "cisco_toolkit/data/migration_runbook.docx",
        "notes.txt",
        "../devices.json",
    ),
)
def test_client_generated_or_unexpected_members_are_rejected(tmp_path: Path, member: str) -> None:
    errors = audit_wheel(_wheel(tmp_path, {member: "synthetic secret"}))
    assert errors, f"unsafe member passed the wheel audit: {member}"
    assert any(member in error for error in errors)


@pytest.mark.parametrize(
    "required",
    (
        "COLLECT_PARSE_V3_23_0.py",
        "cisco_toolkit/blast_radius_explorer.html",
        "cisco_toolkit/data/oui_registry.tsv.gz",
        "cisco_toolkit/data/port_registry.tsv.gz",
    ),
)
def test_required_runtime_assets_cannot_silently_disappear(tmp_path: Path, required: str) -> None:
    errors = audit_wheel(_wheel(tmp_path, omit={required}))
    assert f"required runtime asset missing from wheel: {required}" in errors


def test_exactly_one_distribution_metadata_directory_is_required(tmp_path: Path) -> None:
    errors = audit_wheel(
        _wheel(
            tmp_path,
            {"another_project-1.0.dist-info/METADATA": "Name: another\n"},
        )
    )
    assert any("exactly one .dist-info" in error for error in errors)
