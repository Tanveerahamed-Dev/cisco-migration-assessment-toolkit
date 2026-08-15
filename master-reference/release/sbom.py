"""CycloneDX 1.5 inventory from source-bound dependency declaration bytes.

NPM lock records are classified by their actual distribution evidence; a name
and version alone are not called resolved. Python dependencies are explicitly
marked as declarations because this repository has no hash-locked Python
resolution file; the SBOM never invents transitive or installed-environment
versions. Callers supply raw selected-commit Git-blob bytes so checkout filters
cannot change parsing or provenance.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from collections import Counter
from pathlib import PurePosixPath
from typing import Any, Mapping
from urllib.parse import quote, urlsplit

from .model import ReleaseInputError, stable_id


NPM_LOCKFILES = (
    "master-reference/package-lock.json",
    "webapp/frontend/package-lock.json",
)
PYTHON_DECLARATIONS = (
    "pyproject.toml",
    "requirements.txt",
    "requirements-dev.txt",
    "master-reference/requirements-release.txt",
    "webapp/requirements.txt",
)
# This release builder is repository-specific.  Fail closed if the PEP 621 owner
# changes instead of treating an arbitrary string as a validated SPDX expression.
PROJECT_LICENSE_EXPRESSION = "LicenseRef-Proprietary"
_NPM_LICENSE_ATOMS = frozenset(
    {
        "0BSD",
        "Apache-2.0",
        "BSD-2-Clause",
        "BSD-3-Clause",
        "BlueOak-1.0.0",
        "CC-BY-4.0",
        "CC0-1.0",
        "ISC",
        "LGPL-3.0-or-later",
        "MIT",
        "MIT-0",
        "MPL-2.0",
    }
)


def _local_package_source_receipt(
    source_files: Mapping[str, bytes],
    lockfile: str,
    node_path: str,
) -> tuple[str, int, int] | None:
    lock_parent = PurePosixPath(lockfile).parent
    package_root = (lock_parent / PurePosixPath(node_path)).as_posix()
    if package_root.startswith("./"):
        package_root = package_root[2:]
    prefix = f"{package_root}/"
    rows = [
        {
            "bytes": len(value),
            "path": path,
            "sha256": hashlib.sha256(value).hexdigest(),
        }
        for path, value in sorted(source_files.items())
        if path.startswith(prefix)
    ]
    if not rows:
        return None
    encoded = json.dumps(rows, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8") + b"\n"
    return hashlib.sha256(encoded).hexdigest(), len(rows), sum(int(row["bytes"]) for row in rows)
_NPM_LICENSE_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9.-]*")
_NPM_SRI = re.compile(
    r"(?:sha256|sha384|sha512)-[A-Za-z0-9+/]+={0,2}"
    r"(?:\s+(?:sha256|sha384|sha512)-[A-Za-z0-9+/]+={0,2})*"
)


def _npm_license_declaration(raw: object) -> tuple[str | None, str]:
    if raw is None:
        return None, "absent"
    if not isinstance(raw, str):
        return None, "rejected-non-string"
    value = raw.strip()
    if not value:
        return None, "rejected-empty"

    tokens: list[str] = []
    offset = 0
    while offset < len(value):
        if value[offset].isspace():
            offset += 1
            continue
        if value[offset] in "()":
            tokens.append(value[offset])
            offset += 1
            continue
        match = _NPM_LICENSE_TOKEN.match(value, offset)
        if match is None:
            return None, "rejected-unvalidated-syntax"
        tokens.append(match.group(0))
        offset = match.end()

    index = 0

    def primary() -> bool:
        nonlocal index
        if index >= len(tokens):
            return False
        token = tokens[index]
        if token in _NPM_LICENSE_ATOMS:
            index += 1
            return True
        if token != "(":
            return False
        index += 1
        if not disjunction() or index >= len(tokens) or tokens[index] != ")":
            return False
        index += 1
        return True

    def conjunction() -> bool:
        nonlocal index
        if not primary():
            return False
        while index < len(tokens) and tokens[index] == "AND":
            index += 1
            if not primary():
                return False
        return True

    def disjunction() -> bool:
        nonlocal index
        if not conjunction():
            return False
        while index < len(tokens) and tokens[index] == "OR":
            index += 1
            if not conjunction():
                return False
        return True

    if not tokens or not disjunction() or index != len(tokens):
        return None, "rejected-unvalidated-syntax"
    return value, "accepted-bounded-spdx-syntax"


def _npm_integrity(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if _NPM_SRI.fullmatch(cleaned) is None:
        return None
    expected_sizes = {"sha256": 32, "sha384": 48, "sha512": 64}
    for token in cleaned.split():
        algorithm, encoded = token.split("-", 1)
        try:
            digest = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError):
            return None
        if len(digest) != expected_sizes[algorithm]:
            return None
    return cleaned


def _npm_distribution_url(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    cleaned = value.strip()
    try:
        parsed = urlsplit(cleaned)
    except ValueError:
        return None
    return cleaned if parsed.scheme.lower() == "https" and bool(parsed.netloc) else None


def _is_local_npm_reference(value: object) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    cleaned = value.strip()
    if re.match(r"^[A-Za-z]:[\\/]", cleaned):
        return True
    try:
        parsed = urlsplit(cleaned)
    except ValueError:
        return False
    return parsed.scheme.lower() in {"file", "link", "workspace"} or not parsed.scheme


def _npm_local_link_target(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    cleaned = value.strip().replace("\\", "/")
    while cleaned.startswith("./"):
        cleaned = cleaned[2:]
    path = PurePosixPath(cleaned)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        return None
    return path.as_posix()


def _npm_record_evidence(
    node_path: str,
    item: dict[str, Any],
    version: str | None,
) -> tuple[str, str, str]:
    if node_path == "":
        return "first-party-workspace", "lockfile-workspace-root", "not-applicable-workspace-root"
    if item.get("link") is True:
        return "local-link-record", "lockfile-local-link", "local-link"
    if "node_modules" not in PurePosixPath(node_path).parts or _is_local_npm_reference(item.get("resolved")):
        return "local-package-record", "lockfile-local-package", "local-package"

    distribution_url = _npm_distribution_url(item.get("resolved"))
    integrity = _npm_integrity(item.get("integrity"))
    if version and distribution_url and integrity:
        return (
            "resolved-third-party-component",
            "lockfile-distribution-bound",
            "https-distribution-url-and-valid-sri",
        )
    if not version:
        return "unversioned-non-root-lock-record", "lockfile-unversioned", "unversioned"
    if distribution_url and not integrity:
        evidence = "missing-or-invalid-integrity"
    elif integrity and not distribution_url:
        evidence = "missing-or-invalid-https-distribution-url"
    else:
        evidence = "missing-or-invalid-url-and-integrity"
    return (
        "versioned-lock-record-missing-distribution-evidence",
        "lockfile-version-only-not-resolved",
        evidence,
    )


def _npm_name(node_path: str, item: dict[str, Any]) -> str | None:
    explicit = item.get("name")
    if isinstance(explicit, str) and explicit:
        return explicit
    parts = PurePosixPath(node_path).parts
    if "node_modules" not in parts:
        return None
    index = len(parts) - 1 - list(reversed(parts)).index("node_modules")
    tail = parts[index + 1 :]
    if not tail:
        return None
    return "/".join(tail[:2]) if tail[0].startswith("@") and len(tail) >= 2 else tail[0]


def _resolve_npm(packages: dict[str, Any], parent_path: str, dependency: str) -> str | None:
    parent = PurePosixPath(parent_path)
    base = parent if parent_path else PurePosixPath(".")
    while True:
        candidate = (base / "node_modules" / dependency).as_posix()
        if candidate.startswith("./"):
            candidate = candidate[2:]
        if candidate in packages:
            return candidate
        if str(base) in {"", "."}:
            return None
        base = base.parent


def _purl_npm(name: str, version: str) -> str:
    if name.startswith("@") and "/" in name:
        scope, package = name.split("/", 1)
        encoded_name = f"{quote(scope, safe='')}/{quote(package, safe='')}"
    else:
        encoded_name = quote(name, safe="")
    return f"pkg:npm/{encoded_name}@{quote(version, safe='')}"


def _npm_components(
    source_files: Mapping[str, bytes],
) -> tuple[
    list[dict[str, Any]],
    dict[str, set[str]],
    list[dict[str, Any]],
    int,
    dict[str, int],
]:
    components: list[dict[str, Any]] = []
    components_by_ref: dict[str, dict[str, Any]] = {}
    dependency_map: dict[str, set[str]] = {}
    roots: list[dict[str, Any]] = []
    unresolved_optional_declarations = 0
    evidence_counts: Counter[str] = Counter()
    for relative in NPM_LOCKFILES:
        try:
            lock = json.loads(source_files[relative].decode("utf-8", errors="strict"))
        except KeyError as exc:
            raise ReleaseInputError(f"missing npm lockfile source bytes: {relative}") from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ReleaseInputError(f"could not parse npm lockfile: {relative}") from exc
        if (
            not isinstance(lock, dict)
            or lock.get("lockfileVersion") not in {2, 3}
            or not isinstance(lock.get("packages"), dict)
        ):
            raise ReleaseInputError(f"unsupported or malformed npm lockfile: {relative}")
        packages: dict[str, Any] = lock["packages"]
        refs: dict[str, str] = {}
        for node_path, item in sorted(packages.items()):
            if not isinstance(item, dict):
                raise ReleaseInputError(f"malformed package entry in {relative}: {node_path}")
            name = _npm_name(node_path, item)
            raw_version = item.get("version")
            version = raw_version.strip() if isinstance(raw_version, str) and raw_version.strip() else None
            if node_path == "":
                name = name or str(lock.get("name") or "unnamed-npm-workspace")
                version = version or str(lock.get("version") or "0.0.0")
            else:
                name = name or PurePosixPath(node_path).name or "unnamed-npm-lock-record"
            record_kind, resolution, distribution_evidence = _npm_record_evidence(
                node_path,
                item,
                version,
            )
            bom_ref = stable_id(
                "npm-component",
                relative,
                node_path,
                name,
                version or "<unversioned>",
            )
            refs[node_path] = bom_ref
            properties = [
                {"name": "atlas:lockfile", "value": relative},
                {"name": "atlas:lockfilePath", "value": node_path or "<root>"},
                {"name": "atlas:resolution", "value": resolution},
                {"name": "atlas:developmentOnly", "value": str(bool(item.get("dev"))).lower()},
                {"name": "atlas:recordKind", "value": record_kind},
                {"name": "atlas:distributionEvidenceStatus", "value": distribution_evidence},
            ]
            local_source: tuple[str, int, int] | None = None
            if record_kind == "local-package-record":
                local_source = _local_package_source_receipt(source_files, relative, node_path)
                if local_source is not None:
                    source_digest, source_count, source_bytes = local_source
                    properties.extend(
                        [
                            {"name": "atlas:localPackageSourceDigest", "value": source_digest},
                            {"name": "atlas:localPackageSourceFiles", "value": str(source_count)},
                            {"name": "atlas:localPackageSourceBytes", "value": str(source_bytes)},
                        ]
                    )
            if node_path == "":
                properties.append(
                    {
                        "name": "atlas:licenseScope",
                        "value": "repository-governed-first-party-no-expression-in-lockfile",
                    }
                )
            component: dict[str, Any] = {
                "type": "application" if node_path == "" else "library",
                "bom-ref": bom_ref,
                "group": name.split("/", 1)[0] if name.startswith("@") else "",
                "name": name.split("/", 1)[-1],
                "properties": properties,
            }
            if version is not None:
                component["version"] = version
                component["purl"] = _purl_npm(name, version)
            license_expression, license_declaration_status = _npm_license_declaration(item.get("license"))
            if (
                record_kind == "local-package-record"
                and local_source is not None
                and item.get("license") == PROJECT_LICENSE_EXPRESSION
            ):
                license_expression = PROJECT_LICENSE_EXPRESSION
                license_declaration_status = "accepted-repository-governed-license-ref"
            component["properties"].append(
                {
                    "name": "atlas:npmLicenseDeclarationStatus",
                    "value": license_declaration_status,
                }
            )
            if license_expression is not None:
                component["licenses"] = [{"expression": license_expression}]
            distribution_url = _npm_distribution_url(item.get("resolved"))
            integrity = _npm_integrity(item.get("integrity"))
            if distribution_url is not None:
                component["externalReferences"] = [{"type": "distribution", "url": distribution_url}]
            if integrity is not None:
                component["properties"].append({"name": "atlas:npmIntegrity", "value": integrity})
            components.append(component)
            components_by_ref[bom_ref] = component
            dependency_map.setdefault(bom_ref, set())
            if node_path == "":
                roots.append({"lockfile": relative, "bom-ref": bom_ref})
            else:
                evidence_counts["non_root_records"] += 1
                evidence_counts[f"record_kind:{record_kind}"] += 1
                evidence_counts[f"license:{license_declaration_status}"] += 1

        for node_path, item in sorted(packages.items()):
            source_ref = refs.get(node_path)
            if not source_ref or not isinstance(item, dict):
                continue
            if item.get("link") is True:
                target_path = _npm_local_link_target(item.get("resolved"))
                target_ref = refs.get(target_path) if target_path is not None else None
                if target_ref is None:
                    raise ReleaseInputError(f"unresolved npm local link in {relative}: {node_path}")
                dependency_map[source_ref].add(target_ref)
            for field in (
                "dependencies",
                "devDependencies",
                "optionalDependencies",
                "peerDependencies",
            ):
                value = item.get(field)
                if not isinstance(value, dict):
                    continue
                for name, constraint in sorted(value.items()):
                    if not isinstance(name, str) or not isinstance(constraint, str):
                        raise ReleaseInputError(f"malformed {field} declaration in {relative}: {node_path}")
                    resolved_path = _resolve_npm(packages, node_path, name)
                    target_ref = refs.get(resolved_path) if resolved_path is not None else None
                    if target_ref:
                        dependency_map[source_ref].add(target_ref)
                        continue
                    peer_meta = item.get("peerDependenciesMeta")
                    peer_declaration = peer_meta.get(name) if isinstance(peer_meta, dict) else None
                    optional = field == "optionalDependencies" or (
                        field == "peerDependencies"
                        and isinstance(peer_declaration, dict)
                        and peer_declaration.get("optional") is True
                    )
                    if not optional:
                        raise ReleaseInputError(
                            f"unresolved npm dependency in {relative}: "
                            f"{node_path or '<root>'} {field} {name}@{constraint}"
                        )
                    components_by_ref[source_ref]["properties"].append(
                        {
                            "name": "atlas:unresolvedOptionalNpmDeclaration",
                            "value": f"{field}:{name}@{constraint}",
                        }
                    )
                    unresolved_optional_declarations += 1
    return (
        components,
        dependency_map,
        roots,
        unresolved_optional_declarations,
        dict(evidence_counts),
    )


_REQUIREMENT = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[([^\]]+)\])?\s*(.*)$")


def _requirement_component(raw: str, origin: str, scope: str) -> dict[str, Any] | None:
    cleaned = raw.split("#", 1)[0].strip()
    if not cleaned or cleaned.startswith(("-r", "--requirement", "-e", "--editable")):
        return None
    match = _REQUIREMENT.match(cleaned)
    if not match:
        return None
    name, extras, constraint = match.groups()
    normalized = re.sub(r"[-_.]+", "-", name).lower()
    bom_ref = stable_id("python-declaration", origin, scope, cleaned)
    properties = [
        {"name": "atlas:declarationOrigin", "value": origin},
        {"name": "atlas:declarationScope", "value": scope},
        {"name": "atlas:declaredConstraint", "value": constraint.strip() or "unconstrained"},
        {"name": "atlas:resolution", "value": "declared-unlocked"},
        {"name": "atlas:recordKind", "value": "dependency-declaration"},
        {
            "name": "atlas:licenseScope",
            "value": "not-assessed-until-version-and-distribution-are-locked",
        },
    ]
    if extras:
        properties.append({"name": "atlas:extras", "value": extras})
    return {
        "type": "library",
        "bom-ref": bom_ref,
        "name": normalized,
        "purl": f"pkg:pypi/{quote(normalized, safe='')}",
        "properties": properties,
    }


def _python_components(
    source_files: Mapping[str, bytes],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    components: list[dict[str, Any]] = []
    declarations: list[dict[str, Any]] = []
    try:
        import tomllib  # type: ignore[attr-defined]
    except ImportError:  # pragma: no cover - Python 3.10 compatibility
        import tomli as tomllib  # type: ignore[no-redef]
    try:
        data = tomllib.loads(source_files["pyproject.toml"].decode("utf-8", errors="strict"))
    except KeyError as exc:
        raise ReleaseInputError("missing pyproject.toml source bytes") from exc
    except (UnicodeDecodeError, ValueError) as exc:
        raise ReleaseInputError(f"could not parse pyproject.toml: {exc}") from exc
    project = data.get("project", {})
    project_name = str(project.get("name") or "python-project")
    project_version = str(project.get("version") or "0.0.0")
    root_ref = stable_id("python-project", project_name, project_version)
    root_component = {
        "type": "application",
        "bom-ref": root_ref,
        "name": project_name,
        "version": project_version,
        "purl": f"pkg:pypi/{quote(project_name, safe='')}@{quote(project_version, safe='')}",
        "properties": [
            {"name": "atlas:resolution", "value": "project-metadata"},
            {"name": "atlas:recordKind", "value": "first-party-project"},
            {"name": "atlas:licenseScope", "value": "repository-governed-first-party"},
        ],
    }
    project_license = project.get("license")
    if project_license == PROJECT_LICENSE_EXPRESSION:
        root_component["licenses"] = [{"expression": PROJECT_LICENSE_EXPRESSION}]
        root_component["properties"].append(
            {
                "name": "atlas:licenseEvidence",
                "value": "pyproject.toml:[project].license",
            }
        )
    else:
        root_component["properties"].append(
            {
                "name": "atlas:licenseEvidence",
                "value": (
                    f"pyproject.toml:[project].license-missing-or-not-the-owned-{PROJECT_LICENSE_EXPRESSION}-expression"
                ),
            }
        )
    components.append(root_component)
    declarations.append({"manifest": "pyproject.toml", "bom-ref": root_ref})
    for raw in project.get("dependencies", []):
        component = _requirement_component(str(raw), "pyproject.toml", "runtime")
        if component:
            components.append(component)
    for extra, requirements in sorted((project.get("optional-dependencies") or {}).items()):
        for raw in requirements:
            component = _requirement_component(str(raw), "pyproject.toml", f"optional:{extra}")
            if component:
                components.append(component)

    for relative in PYTHON_DECLARATIONS[1:]:
        try:
            lines = source_files[relative].decode("utf-8", errors="strict").splitlines()
        except KeyError as exc:
            raise ReleaseInputError(f"missing dependency declaration source bytes: {relative}") from exc
        except UnicodeDecodeError as exc:
            raise ReleaseInputError(f"could not read dependency declaration {relative}: {exc}") from exc
        for raw in lines:
            component = _requirement_component(raw, relative, "declared")
            if component:
                components.append(component)
        declarations.append({"manifest": relative, "bom-ref": root_ref})
    return components, declarations


def build_cyclonedx(
    source_files: Mapping[str, bytes],
    source_commit: str,
    source_tree_digest: str,
) -> dict[str, Any]:
    (
        npm_components,
        npm_edges,
        npm_roots,
        npm_unresolved_optional,
        npm_evidence_counts,
    ) = _npm_components(source_files)
    python_components, python_roots = _python_components(source_files)
    components = sorted(npm_components + python_components, key=lambda item: item["bom-ref"])
    component_ref_list = [str(component["bom-ref"]) for component in components]
    seen_refs: set[str] = set()
    duplicate_refs: set[str] = set()
    for component_ref in component_ref_list:
        if component_ref in seen_refs:
            duplicate_refs.add(component_ref)
        seen_refs.add(component_ref)
    if duplicate_refs:
        raise ReleaseInputError(
            f"SBOM contains {len(duplicate_refs)} duplicate component refs: " + ", ".join(sorted(duplicate_refs)[:5])
        )
    component_refs = set(component_ref_list)
    for component in components:
        properties = component.setdefault("properties", [])
        license_status = "declared" if component.get("licenses") else "unknown"
        properties.extend(
            [
                {"name": "atlas:licenseStatus", "value": license_status},
                {"name": "atlas:vulnerabilityStatus", "value": "not_assessed"},
            ]
        )
    dependency_map = {key: set(value) for key, value in npm_edges.items()}
    for component in python_components:
        dependency_map.setdefault(component["bom-ref"], set())
    python_root_refs = {str(item["bom-ref"]) for item in python_roots}
    python_leaf_refs = {
        str(component["bom-ref"])
        for component in python_components
        if str(component["bom-ref"]) not in python_root_refs
    }
    for root_ref in python_root_refs:
        dependency_map[root_ref].update(python_leaf_refs)

    atlas_ref = stable_id("atlas-release", source_commit, source_tree_digest)
    dependency_map[atlas_ref] = {
        *(str(item["bom-ref"]) for item in npm_roots),
        *python_root_refs,
    }

    unknown_targets = sorted({target for targets in dependency_map.values() for target in targets} - component_refs)
    if unknown_targets:
        raise ReleaseInputError(
            f"SBOM dependency graph contains {len(unknown_targets)} unknown component refs: "
            + ", ".join(unknown_targets[:5])
        )
    reachable = {atlas_ref}
    pending = [atlas_ref]
    while pending:
        source_ref = pending.pop()
        for target_ref in sorted(dependency_map.get(source_ref, set())):
            if target_ref not in reachable:
                reachable.add(target_ref)
                pending.append(target_ref)
    disconnected = sorted(component_refs - reachable)
    if disconnected:
        raise ReleaseInputError(
            f"SBOM dependency graph contains {len(disconnected)} disconnected components: "
            + ", ".join(disconnected[:5])
        )
    dependency_edges = sum(len(targets) for targets in dependency_map.values())

    serial_seed = hashlib.sha256(f"{source_commit}\x1f{source_tree_digest}".encode()).hexdigest()
    properties_by_ref = {
        str(component["bom-ref"]): {
            str(item.get("name")): str(item.get("value"))
            for item in component.get("properties", [])
            if isinstance(item, dict)
        }
        for component in components
    }
    resolved_third_party = [
        component
        for component in components
        if properties_by_ref[str(component["bom-ref"])].get("atlas:recordKind") == "resolved-third-party-component"
    ]
    first_party_records = [
        component
        for component in components
        if properties_by_ref[str(component["bom-ref"])].get("atlas:recordKind")
        in {"first-party-project", "first-party-workspace"}
    ]
    python_declaration_records = [
        component
        for component in components
        if properties_by_ref[str(component["bom-ref"])].get("atlas:recordKind") == "dependency-declaration"
    ]
    python_declaration_names = {str(component["name"]) for component in python_declaration_records}
    license_declared = sum(1 for component in components if component.get("licenses"))
    license_unknown = len(components) - license_declared
    resolved_third_party_license_declared = sum(1 for component in resolved_third_party if component.get("licenses"))
    resolved_third_party_license_unknown = len(resolved_third_party) - resolved_third_party_license_declared
    if not resolved_third_party:
        resolved_third_party_license_status = "not-assessed-empty-denominator"
    elif resolved_third_party_license_unknown:
        resolved_third_party_license_status = "declared-incomplete-unknowns-present"
    else:
        resolved_third_party_license_status = "declared-complete-for-distribution-bound-npm-components"
    first_party_license_declared = sum(1 for component in first_party_records if component.get("licenses"))
    first_party_repository_governed_without_expression = len(first_party_records) - first_party_license_declared
    python_unlocked = sum(
        1
        for component in python_components
        if any(
            item.get("name") == "atlas:resolution" and item.get("value") == "declared-unlocked"
            for item in component.get("properties", [])
        )
    )
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": f"urn:uuid:{serial_seed[:8]}-{serial_seed[8:12]}-{serial_seed[12:16]}-{serial_seed[16:20]}-{serial_seed[20:32]}",
        "version": 1,
        "metadata": {
            "component": {
                "type": "application",
                "bom-ref": atlas_ref,
                "name": "Atlas Master Reference",
                "version": source_commit[:12],
                "properties": [
                    {"name": "atlas:sourceCommit", "value": source_commit},
                    {"name": "atlas:sourceTreeDigest", "value": source_tree_digest},
                    {"name": "atlas:pythonResolution", "value": "declarations-only-no-transitive-lock"},
                    {"name": "atlas:licenseStatus", "value": "repository-license-governed-separately"},
                    {"name": "atlas:vulnerabilityStatus", "value": "not_assessed"},
                ],
            },
            "properties": [
                {"name": "atlas:npmLockfiles", "value": ",".join(NPM_LOCKFILES)},
                {"name": "atlas:pythonDeclarations", "value": ",".join(PYTHON_DECLARATIONS)},
            ],
        },
        "components": components,
        "dependencies": [{"ref": key, "dependsOn": sorted(values)} for key, values in sorted(dependency_map.items())],
        "properties": [
            {"name": "atlas:npmRoots", "value": str(len(npm_roots))},
            {"name": "atlas:pythonManifestRoots", "value": str(len(python_roots))},
            {"name": "atlas:componentDenominator", "value": str(len(components))},
            {"name": "atlas:recordDenominator", "value": str(len(components))},
            {"name": "atlas:componentGraphReachable", "value": str(len(component_refs))},
            {"name": "atlas:componentGraphDisconnected", "value": "0"},
            {"name": "atlas:dependencyEdges", "value": str(dependency_edges)},
            {
                "name": "atlas:unresolvedOptionalNpmDeclarations",
                "value": str(npm_unresolved_optional),
            },
            {
                "name": "atlas:npmNonRootRecordDenominator",
                "value": str(npm_evidence_counts.get("non_root_records", 0)),
            },
            {
                "name": "atlas:npmDistributionBoundThirdPartyRecords",
                "value": str(
                    npm_evidence_counts.get(
                        "record_kind:resolved-third-party-component",
                        0,
                    )
                ),
            },
            {
                "name": "atlas:npmLocalLinkRecords",
                "value": str(npm_evidence_counts.get("record_kind:local-link-record", 0)),
            },
            {
                "name": "atlas:npmLocalPackageRecords",
                "value": str(npm_evidence_counts.get("record_kind:local-package-record", 0)),
            },
            {
                "name": "atlas:npmVersionedMissingDistributionEvidenceRecords",
                "value": str(
                    npm_evidence_counts.get(
                        "record_kind:versioned-lock-record-missing-distribution-evidence",
                        0,
                    )
                ),
            },
            {
                "name": "atlas:npmUnversionedRecords",
                "value": str(
                    npm_evidence_counts.get(
                        "record_kind:unversioned-non-root-lock-record",
                        0,
                    )
                ),
            },
            {
                "name": "atlas:npmLicenseDeclarationsAcceptedBoundedSyntax",
                "value": str(
                    npm_evidence_counts.get(
                        "license:accepted-bounded-spdx-syntax",
                        0,
                    )
                ),
            },
            {
                "name": "atlas:npmLicenseDeclarationsRejectedEmpty",
                "value": str(npm_evidence_counts.get("license:rejected-empty", 0)),
            },
            {
                "name": "atlas:npmLicenseDeclarationsRejectedSyntax",
                "value": str(
                    npm_evidence_counts.get(
                        "license:rejected-unvalidated-syntax",
                        0,
                    )
                ),
            },
            {
                "name": "atlas:npmLicenseDeclarationsRejectedNonString",
                "value": str(npm_evidence_counts.get("license:rejected-non-string", 0)),
            },
            {
                "name": "atlas:npmLicenseDeclarationsAbsent",
                "value": str(npm_evidence_counts.get("license:absent", 0)),
            },
            {"name": "atlas:licenseDeclared", "value": str(license_declared)},
            {"name": "atlas:licenseUnknown", "value": str(license_unknown)},
            {
                "name": "atlas:legacyLicenseCountScope",
                "value": "all-component-records-including-unresolved-declarations",
            },
            {
                "name": "atlas:resolvedThirdPartyComponentDenominator",
                "value": str(len(resolved_third_party)),
            },
            {
                "name": "atlas:resolvedThirdPartyLicenseDeclared",
                "value": str(resolved_third_party_license_declared),
            },
            {
                "name": "atlas:resolvedThirdPartyLicenseUnknown",
                "value": str(resolved_third_party_license_unknown),
            },
            {
                "name": "atlas:resolvedThirdPartyLicenseStatus",
                "value": resolved_third_party_license_status,
            },
            {
                "name": "atlas:resolvedThirdPartyLicenseEvidence",
                "value": "package-lock-license-fields-only-no-license-file-verification",
            },
            {
                "name": "atlas:firstPartyRecordDenominator",
                "value": str(len(first_party_records)),
            },
            {
                "name": "atlas:firstPartyLicenseDeclared",
                "value": str(first_party_license_declared),
            },
            {
                "name": "atlas:firstPartyRepositoryGovernedWithoutExpression",
                "value": str(first_party_repository_governed_without_expression),
            },
            {"name": "atlas:vulnerabilityAssessed", "value": "0"},
            {"name": "atlas:vulnerabilityNotAssessed", "value": str(len(components))},
            {"name": "atlas:pythonDeclaredUnlocked", "value": str(python_unlocked)},
            {
                "name": "atlas:pythonDeclarationRecords",
                "value": str(len(python_declaration_records)),
            },
            {
                "name": "atlas:pythonDeclarationUniqueNames",
                "value": str(len(python_declaration_names)),
            },
            {
                "name": "atlas:pythonTransitiveLockStatus",
                "value": "blocked-no-transitive-lock",
            },
            {
                "name": "atlas:releaseGate",
                "value": (
                    "BLOCK: Python transitive lock and vulnerability assessment remain incomplete; "
                    f"unresolved Python declaration records={len(python_declaration_records)} "
                    f"across unique names={len(python_declaration_names)}; "
                    f"legacy full-record components with unknown license={license_unknown}"
                ),
            },
            {
                "name": "atlas:coverageHonesty",
                "value": (
                    "npm runtime/development direct/transitive locked; unresolved optional npm "
                    "declarations retained on their source components; Python direct declarations only"
                ),
            },
        ],
    }
