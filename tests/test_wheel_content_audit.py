"""The distribution-content gate must inspect the built artifact, not just pyproject.toml."""
from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from tools.audit_wheel import audit_wheel, discover_artifacts


_REQUIRED = {
    "COLLECT_PARSE_V3_23_0.py": "def main(): pass\n",
    "cisco_toolkit/__init__.py": "\n",
    "cisco_toolkit/blast_radius_explorer.html": "<!doctype html>\n",
    "cisco_toolkit/data/eol-bulletins.json": "synthetic-eol-evidence",
    "cisco_toolkit/data/oui_registry.tsv.gz": "synthetic-oui-pack",
    "cisco_toolkit/data/port_registry.tsv.gz": "synthetic-port-pack",
    "cisco_toolkit/data/registry_manifest.json": "{}\n",
    "cisco_toolkit/data/qcp-001.experimental.json": "{}\n",
    "cisco_toolkit/data/atlas-r1-executable-bundle.json": "{}\n",
    "cisco_toolkit/data/atlas-r1-source-bundle.json": "{}\n",
    "cisco_toolkit/data/atlas-r1-retrospective-after.json": "{}\n",
    "cisco_toolkit/data/atlas-r1-retrospective-before.json": "{}\n",
    "cisco_toolkit/data/atlas-r1-retrospective-comparison.json": "{}\n",
    "cisco_toolkit/data/atlas-r2-structural-tcb-census.v1.json": "{}\n",
    "cisco_toolkit/data/traffic-intents.example.json": '{"intents": []}\n',
    "cisco_toolkit/schemas/atlas-transition-contract-v1.schema.json": "{}\n",
    "cisco_toolkit/schemas/atlas-r2-structural-tcb-census-v1.schema.json": "{}\n",
    "cisco_toolkit/transition_contract.py": "\n",
    "cisco_toolkit/transition_pack.py": "\n",
    "cisco_toolkit/transition_verifier.py": "\n",
    "cisco_toolkit/transition_legacy.py": "\n",
    "webapp/backend/__init__.py": "\n",
    "cisco_migration_assessment_toolkit-3.31.0.dist-info/METADATA": "Name: test\n",
    "cisco_migration_assessment_toolkit-3.31.0.dist-info/WHEEL": "Wheel-Version: 1.0\n",
    "cisco_migration_assessment_toolkit-3.31.0.dist-info/RECORD": "\n",
}


def _wheel(
    tmp_path: Path,
    extra: dict[str, str] | None = None,
    omit: set[str] | None = None,
    name: str = "toolkit-3.31.0-py3-none-any.whl",
) -> Path:
    path = tmp_path / name
    members = dict(_REQUIRED)
    members.update(extra or {})
    for member in omit or set():
        members.pop(member, None)
    with zipfile.ZipFile(path, "w") as archive:
        for member, content in members.items():
            archive.writestr(member, content)
    return path


def test_expected_runtime_wheel_is_accepted(tmp_path: Path) -> None:
    assert audit_wheel(_wheel(tmp_path)) == []


@pytest.mark.parametrize(
    "member",
    (
        "cisco_toolkit/client_evidence/ACME/show_running-config.txt",
        "webapp/data/assesshub.db",
        "migration_collection_20260730/CORE-1/show_version.txt",
        "cisco_toolkit/data/show_version.txt",
        "cisco_toolkit/data/moquery_-c_faultInst.txt",
        "cisco_toolkit/data/api_v1_deployment_node.txt",
        "cisco_toolkit/data/api_fmc_config_v1_devices_devicerecords.txt",
        "cisco_toolkit/data/ers_config_node.txt",
        "cisco_toolkit/data/dataservice_device.txt",
        "cisco_toolkit/data/aws_ec2_describe-security-groups.txt",
        "cisco_toolkit/data/get_system_ha_status.txt",
        "cisco_toolkit/data/device_info.json",
        "cisco_toolkit/data/command_index.json",
        "cisco_toolkit/data/_capture_meta.json",
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
        "cisco_toolkit/data/eol-bulletins.json",
        "cisco_toolkit/data/oui_registry.tsv.gz",
        "cisco_toolkit/data/port_registry.tsv.gz",
        "cisco_toolkit/data/registry_manifest.json",
        "cisco_toolkit/data/qcp-001.experimental.json",
        "cisco_toolkit/data/atlas-r1-executable-bundle.json",
        "cisco_toolkit/data/atlas-r1-source-bundle.json",
        "cisco_toolkit/data/atlas-r1-retrospective-after.json",
        "cisco_toolkit/data/atlas-r1-retrospective-before.json",
        "cisco_toolkit/data/atlas-r1-retrospective-comparison.json",
        "cisco_toolkit/data/atlas-r2-structural-tcb-census.v1.json",
        "cisco_toolkit/data/traffic-intents.example.json",
        "cisco_toolkit/schemas/atlas-transition-contract-v1.schema.json",
        "cisco_toolkit/schemas/atlas-r2-structural-tcb-census-v1.schema.json",
        "cisco_toolkit/transition_contract.py",
        "cisco_toolkit/transition_pack.py",
        "cisco_toolkit/transition_verifier.py",
        "cisco_toolkit/transition_legacy.py",
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


def test_artifact_directory_is_discovered_without_shell_globbing(tmp_path: Path) -> None:
    wheel = _wheel(tmp_path)
    sdist = tmp_path / "toolkit-3.31.0.tar.gz"
    sdist.write_bytes(b"synthetic archive placeholder")
    artifacts, errors = discover_artifacts([tmp_path])
    assert errors == []
    assert artifacts == [wheel, sdist]


def test_artifact_directory_requires_one_wheel_and_one_sdist(tmp_path: Path) -> None:
    first = _wheel(tmp_path)
    artifacts, errors = discover_artifacts([tmp_path])
    assert artifacts == [first]
    assert any("exactly one source distribution" in error for error in errors)

    second = _wheel(tmp_path, name="toolkit-3.31.1-py3-none-any.whl")
    (tmp_path / "toolkit-3.31.0.tar.gz").write_bytes(b"synthetic archive placeholder")
    artifacts, errors = discover_artifacts([tmp_path])
    assert artifacts == [first, second, tmp_path / "toolkit-3.31.0.tar.gz"]
    assert any("exactly one wheel" in error for error in errors)


def test_artifact_directory_rejects_unexpected_entries(tmp_path: Path) -> None:
    _wheel(tmp_path)
    (tmp_path / "toolkit-3.31.0.tar.gz").write_bytes(b"synthetic archive placeholder")
    (tmp_path / "unreviewed.zip").write_bytes(b"not part of the audited release pair")
    _, errors = discover_artifacts([tmp_path])
    assert any("unexpected entries" in error and "unreviewed.zip" in error for error in errors)
