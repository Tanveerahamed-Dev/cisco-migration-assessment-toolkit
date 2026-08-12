from __future__ import annotations

import base64
import json
import sys
from pathlib import Path


MASTER_REFERENCE = Path(__file__).resolve().parents[2]
if str(MASTER_REFERENCE) not in sys.path:
    sys.path.insert(0, str(MASTER_REFERENCE))

from release.sbom import NPM_LOCKFILES, PYTHON_DECLARATIONS, build_cyclonedx  # noqa: E402


def _lock(
    name: str,
    *,
    dependency: str | None = None,
    dependency_license: str | None = "MIT",
    dependency_resolved: str | None = "https://registry.npmjs.org/locked-leaf/-/locked-leaf-1.2.3.tgz",
    dependency_integrity: str | None = None,
    dependency_link: bool = False,
    dependency_path: str | None = None,
) -> bytes:
    root: dict[str, object] = {"name": name, "version": "0.1.0"}
    packages: dict[str, object] = {"": root}
    if dependency is not None:
        root["dependencies"] = {dependency: "1.2.3"}
        package: dict[str, object] = {
            "name": dependency,
            "version": "1.2.3",
        }
        if dependency_resolved is not None:
            package["resolved"] = dependency_resolved
        if dependency_integrity is None:
            dependency_integrity = "sha512-" + base64.b64encode(b"x" * 64).decode("ascii")
        if dependency_integrity:
            package["integrity"] = dependency_integrity
        if dependency_link:
            package["link"] = True
        if dependency_license is not None:
            package["license"] = dependency_license
        packages[dependency_path or f"node_modules/{dependency}"] = package
    return json.dumps(
        {
            "name": name,
            "version": "0.1.0",
            "lockfileVersion": 3,
            "packages": packages,
        },
        sort_keys=True,
    ).encode("utf-8")


def _local_link_lock(name: str) -> bytes:
    return json.dumps(
        {
            "name": name,
            "version": "0.1.0",
            "lockfileVersion": 3,
            "packages": {
                "": {
                    "name": name,
                    "version": "0.1.0",
                    "dependencies": {"local-library": "file:packages/local-library"},
                },
                "node_modules/local-library": {
                    "resolved": "packages/local-library",
                    "link": True,
                },
                "packages/local-library": {
                    "name": "local-library",
                    "version": "1.2.3",
                    "license": "MIT",
                },
            },
        },
        sort_keys=True,
    ).encode("utf-8")


def _sources(
    *,
    project_license: str | None = "LicenseRef-Proprietary",
    project_dependencies: tuple[str, ...] = (),
    requirement_lines: dict[str, str] | None = None,
    npm_dependency: str | None = "locked-leaf",
    npm_dependency_license: str | None = "MIT",
    npm_dependency_resolved: str | None = "https://registry.npmjs.org/locked-leaf/-/locked-leaf-1.2.3.tgz",
    npm_dependency_integrity: str | None = None,
) -> dict[str, bytes]:
    project_lines = [
        "[project]",
        'name = "fixture-project"',
        'version = "1.0.0"',
    ]
    if project_license is not None:
        project_lines.append(f'license = "{project_license}"')
    rendered_dependencies = ", ".join(json.dumps(value) for value in project_dependencies)
    project_lines.append(f"dependencies = [{rendered_dependencies}]")
    source_files = {
        "pyproject.toml": ("\n".join(project_lines) + "\n").encode("utf-8"),
        NPM_LOCKFILES[0]: _lock(
            "first-workspace",
            dependency=npm_dependency,
            dependency_license=npm_dependency_license,
            dependency_resolved=npm_dependency_resolved,
            dependency_integrity=npm_dependency_integrity,
        ),
        NPM_LOCKFILES[1]: _lock(
            "second-workspace",
            dependency=npm_dependency,
            dependency_license=npm_dependency_license,
            dependency_resolved=npm_dependency_resolved,
            dependency_integrity=npm_dependency_integrity,
        ),
    }
    lines = requirement_lines or {}
    for relative in PYTHON_DECLARATIONS[1:]:
        source_files[relative] = lines.get(relative, "").encode("utf-8")
    return source_files


def _properties(value: dict[str, object]) -> dict[str, str]:
    return {
        str(item["name"]): str(item["value"])
        for item in value.get("properties", [])  # type: ignore[union-attr]
    }


def _component_properties(sbom: dict[str, object]) -> list[tuple[dict[str, object], dict[str, str]]]:
    return [
        (component, _properties(component))
        for component in sbom["components"]  # type: ignore[index]
    ]


def test_sbom_scopes_first_party_records_and_unresolved_python_declarations() -> None:
    sbom = build_cyclonedx(
        _sources(
            project_dependencies=("alpha>=1",),
            requirement_lines={
                "requirements.txt": "alpha>=1\n",
                "requirements-dev.txt": "beta==2\n",
            },
        ),
        "a" * 40,
        "b" * 64,
    )
    records = _component_properties(sbom)
    by_kind: dict[str, list[dict[str, object]]] = {}
    for component, properties in records:
        by_kind.setdefault(properties["atlas:recordKind"], []).append(component)

    assert len(by_kind["first-party-workspace"]) == 2
    assert all("licenses" not in component for component in by_kind["first-party-workspace"])
    workspace_properties = [
        properties for _, properties in records if properties["atlas:recordKind"] == "first-party-workspace"
    ]
    assert {properties["atlas:licenseScope"] for properties in workspace_properties} == {
        "repository-governed-first-party-no-expression-in-lockfile"
    }
    assert len(by_kind["first-party-project"]) == 1
    assert by_kind["first-party-project"][0]["licenses"] == [{"expression": "LicenseRef-Proprietary"}]
    project_properties = next(
        properties for _, properties in records if properties["atlas:recordKind"] == "first-party-project"
    )
    assert project_properties["atlas:licenseEvidence"] == "pyproject.toml:[project].license"
    assert len(by_kind["resolved-third-party-component"]) == 2
    assert len(by_kind["dependency-declaration"]) == 3
    assert all("version" not in component for component in by_kind["dependency-declaration"])
    assert all("licenses" not in component for component in by_kind["dependency-declaration"])

    properties = _properties(sbom)
    assert properties["atlas:recordDenominator"] == "8"
    assert properties["atlas:resolvedThirdPartyComponentDenominator"] == "2"
    assert properties["atlas:resolvedThirdPartyLicenseDeclared"] == "2"
    assert properties["atlas:resolvedThirdPartyLicenseUnknown"] == "0"
    assert properties["atlas:resolvedThirdPartyLicenseStatus"] == (
        "declared-complete-for-distribution-bound-npm-components"
    )
    assert properties["atlas:resolvedThirdPartyLicenseEvidence"] == (
        "package-lock-license-fields-only-no-license-file-verification"
    )
    assert properties["atlas:firstPartyRecordDenominator"] == "3"
    assert properties["atlas:firstPartyLicenseDeclared"] == "1"
    assert properties["atlas:firstPartyRepositoryGovernedWithoutExpression"] == "2"
    assert properties["atlas:pythonDeclarationRecords"] == "3"
    assert properties["atlas:pythonDeclarationUniqueNames"] == "2"
    assert properties["atlas:licenseDeclared"] == "3"
    assert properties["atlas:licenseUnknown"] == "5"
    assert properties["atlas:legacyLicenseCountScope"] == ("all-component-records-including-unresolved-declarations")
    assert properties["atlas:releaseGate"].startswith("BLOCK:")


def test_missing_project_license_stays_explicitly_unknown() -> None:
    sbom = build_cyclonedx(
        _sources(project_license=None, npm_dependency=None),
        "a" * 40,
        "b" * 64,
    )
    project, properties = next(
        (component, component_properties)
        for component, component_properties in _component_properties(sbom)
        if component_properties["atlas:recordKind"] == "first-party-project"
    )

    assert "licenses" not in project
    assert properties["atlas:licenseEvidence"] == (
        "pyproject.toml:[project].license-missing-or-not-the-owned-LicenseRef-Proprietary-expression"
    )
    denominators = _properties(sbom)
    assert denominators["atlas:firstPartyLicenseDeclared"] == "0"
    assert denominators["atlas:firstPartyRepositoryGovernedWithoutExpression"] == "3"
    assert denominators["atlas:licenseUnknown"] == "3"


def test_unknown_resolved_third_party_license_is_not_a_vacuous_pass() -> None:
    sbom = build_cyclonedx(
        _sources(npm_dependency_license=None),
        "a" * 40,
        "b" * 64,
    )
    properties = _properties(sbom)

    assert properties["atlas:resolvedThirdPartyComponentDenominator"] == "2"
    assert properties["atlas:resolvedThirdPartyLicenseDeclared"] == "0"
    assert properties["atlas:resolvedThirdPartyLicenseUnknown"] == "2"
    assert properties["atlas:resolvedThirdPartyLicenseStatus"] == ("declared-incomplete-unknowns-present")


def test_empty_and_prose_npm_license_values_remain_unknown() -> None:
    cases = (
        ("", "atlas:npmLicenseDeclarationsRejectedEmpty"),
        ("All rights reserved proprietary software", "atlas:npmLicenseDeclarationsRejectedSyntax"),
    )
    for raw_license, rejected_property in cases:
        sbom = build_cyclonedx(
            _sources(npm_dependency_license=raw_license),
            "a" * 40,
            "b" * 64,
        )
        resolved = [
            (component, properties)
            for component, properties in _component_properties(sbom)
            if properties["atlas:recordKind"] == "resolved-third-party-component"
        ]
        properties = _properties(sbom)

        assert len(resolved) == 2
        assert all("licenses" not in component for component, _ in resolved)
        assert {component_properties["atlas:npmLicenseDeclarationStatus"] for _, component_properties in resolved} <= {
            "rejected-empty",
            "rejected-unvalidated-syntax",
        }
        assert properties["atlas:resolvedThirdPartyLicenseDeclared"] == "0"
        assert properties["atlas:resolvedThirdPartyLicenseUnknown"] == "2"
        assert properties[rejected_property] == "2"


def test_missing_or_malformed_sri_is_not_distribution_bound() -> None:
    for integrity in ("", "sha512-A"):
        sbom = build_cyclonedx(
            _sources(npm_dependency_integrity=integrity),
            "a" * 40,
            "b" * 64,
        )
        properties = _properties(sbom)
        evidence_rows = [
            component_properties
            for _, component_properties in _component_properties(sbom)
            if component_properties["atlas:recordKind"] == "versioned-lock-record-missing-distribution-evidence"
        ]

        assert properties["atlas:npmNonRootRecordDenominator"] == "2"
        assert properties["atlas:npmDistributionBoundThirdPartyRecords"] == "0"
        assert properties["atlas:npmVersionedMissingDistributionEvidenceRecords"] == "2"
        assert properties["atlas:resolvedThirdPartyComponentDenominator"] == "0"
        assert properties["atlas:resolvedThirdPartyLicenseStatus"] == ("not-assessed-empty-denominator")
        assert len(evidence_rows) == 2
        assert {row["atlas:distributionEvidenceStatus"] for row in evidence_rows} == {"missing-or-invalid-integrity"}


def test_local_package_and_link_records_are_separate_from_distribution_bound_rows() -> None:
    sources = _sources(npm_dependency=None)
    sources[NPM_LOCKFILES[0]] = _local_link_lock("first-workspace")
    sources[NPM_LOCKFILES[1]] = _local_link_lock("second-workspace")
    sbom = build_cyclonedx(sources, "a" * 40, "b" * 64)
    properties = _properties(sbom)
    kinds = [component_properties["atlas:recordKind"] for _, component_properties in _component_properties(sbom)]

    assert kinds.count("local-link-record") == 2
    assert kinds.count("local-package-record") == 2
    assert properties["atlas:npmNonRootRecordDenominator"] == "4"
    assert properties["atlas:npmLocalLinkRecords"] == "2"
    assert properties["atlas:npmLocalPackageRecords"] == "2"
    assert properties["atlas:npmDistributionBoundThirdPartyRecords"] == "0"
    assert properties["atlas:resolvedThirdPartyComponentDenominator"] == "0"
    assert properties["atlas:componentGraphDisconnected"] == "0"


def test_non_expression_project_license_stays_explicitly_unknown() -> None:
    sources = _sources(npm_dependency=None)
    sources["pyproject.toml"] = sources["pyproject.toml"].replace(
        b'license = "LicenseRef-Proprietary"',
        b'license = {text = "legacy prose is not an SPDX expression"}',
    )
    sbom = build_cyclonedx(sources, "a" * 40, "b" * 64)
    project, properties = next(
        (component, component_properties)
        for component, component_properties in _component_properties(sbom)
        if component_properties["atlas:recordKind"] == "first-party-project"
    )

    assert "licenses" not in project
    assert properties["atlas:licenseEvidence"] == (
        "pyproject.toml:[project].license-missing-or-not-the-owned-LicenseRef-Proprietary-expression"
    )


def test_prose_project_license_string_is_not_serialized_as_an_spdx_expression() -> None:
    sbom = build_cyclonedx(
        _sources(project_license="All rights reserved proprietary software", npm_dependency=None),
        "a" * 40,
        "b" * 64,
    )
    project, properties = next(
        (component, component_properties)
        for component, component_properties in _component_properties(sbom)
        if component_properties["atlas:recordKind"] == "first-party-project"
    )

    assert "licenses" not in project
    assert properties["atlas:licenseEvidence"] == (
        "pyproject.toml:[project].license-missing-or-not-the-owned-LicenseRef-Proprietary-expression"
    )


def test_zero_declarations_never_promotes_python_lock_status() -> None:
    sbom = build_cyclonedx(
        _sources(npm_dependency=None),
        "a" * 40,
        "b" * 64,
    )
    properties = _properties(sbom)

    assert properties["atlas:pythonDeclarationRecords"] == "0"
    assert properties["atlas:pythonDeclarationUniqueNames"] == "0"
    assert properties["atlas:pythonDeclaredUnlocked"] == "0"
    assert properties["atlas:pythonTransitiveLockStatus"] == "blocked-no-transitive-lock"
    assert properties["atlas:resolvedThirdPartyComponentDenominator"] == "0"
    assert properties["atlas:resolvedThirdPartyLicenseStatus"] == "not-assessed-empty-denominator"
    assert properties["atlas:releaseGate"].startswith("BLOCK:")
    metadata_properties = _properties(sbom["metadata"]["component"])  # type: ignore[index]
    assert metadata_properties["atlas:pythonResolution"] == ("declarations-only-no-transitive-lock")
