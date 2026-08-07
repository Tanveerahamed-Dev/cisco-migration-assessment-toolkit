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
    "cisco_toolkit/data/eol-bulletins.json": b"synthetic-eol-evidence",
    "cisco_toolkit/data/oui_registry.tsv.gz": b"synthetic-oui-pack",
    "cisco_toolkit/data/port_registry.tsv.gz": b"synthetic-port-pack",
    "cisco_toolkit/data/registry_manifest.json": b"{}\n",
    "tests/fixtures/show_version.txt": b"synthetic fixture only\n",
    "tests/fixtures/device_info.json": b'{"synthetic": true}\n',
}


def _add(archive: tarfile.TarFile, name: str, content: bytes) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(content)
    archive.addfile(info, io.BytesIO(content))


def _sdist(
    tmp_path: Path,
    extra: dict[str, bytes] | None = None,
    omit: set[str] | None = None,
) -> Path:
    path = tmp_path / f"{_ROOT}.tar.gz"
    members = dict(_REQUIRED)
    members.update(extra or {})
    for name in omit or set():
        members.pop(name, None)
    with tarfile.open(path, "w:gz") as archive:
        for relative, content in members.items():
            _add(archive, f"{_ROOT}/{relative}", content)
    return path


def test_expected_source_distribution_is_accepted(tmp_path: Path) -> None:
    # Synthetic captures/sidecars under tests/ are reviewable; the same names elsewhere are not.
    assert audit_sdist(_sdist(tmp_path)) == []


@pytest.mark.parametrize(
    "member",
    (
        "client_evidence/ACME/show_running-config.txt",
        "customer-output/CORE-1/show_version.txt",
        "customer-output/APIC/moquery_-c_faultInst.txt",
        "customer-output/ISE/api_v1_deployment_node.txt",
        "customer-output/FMC/api_fmc_config_v1_devices_devicerecords.txt",
        "customer-output/ISE/ers_config_node.txt",
        "customer-output/SDWAN/dataservice_device.txt",
        "customer-output/AWS/aws_ec2_describe-security-groups.txt",
        "customer-output/FORTIGATE/get_system_ha_status.txt",
        "customer-output/CORE-1/device_info.json",
        "customer-output/CORE-1/command_index.json",
        "customer-output/CORE-1/_capture_meta.json",
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


@pytest.mark.parametrize(
    "required",
    (
        "pyproject.toml",
        "cisco_toolkit/data/eol-bulletins.json",
        "cisco_toolkit/data/registry_manifest.json",
    ),
)
def test_required_source_inputs_cannot_silently_disappear(
    tmp_path: Path, required: str
) -> None:
    errors = audit_sdist(_sdist(tmp_path, omit={required}))
    assert f"required source member missing from sdist: {required}" in errors


def test_source_distribution_must_have_one_root(tmp_path: Path) -> None:
    path = tmp_path / "multi-root.tar.gz"
    with tarfile.open(path, "w:gz") as archive:
        for relative, content in _REQUIRED.items():
            _add(archive, f"{_ROOT}/{relative}", content)
        _add(archive, "unexpected-second-root/README.md", b"not allowed\n")
    errors = audit_sdist(path)
    assert any("expected one source-distribution root" in error for error in errors)
