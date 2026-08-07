"""CycloneDX 1.5 inventory from repository-owned dependency declarations.

NPM package-lock v3 files provide direct and transitive resolution.  Python
dependencies are explicitly marked as declarations because this repository has
no hash-locked Python resolution file; the SBOM never invents transitive or
installed-environment versions.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote

from .model import ReleaseInputError, read_json, safe_input, stable_id


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


def _npm_components(repo_root: Path) -> tuple[list[dict[str, Any]], dict[str, set[str]], list[dict[str, Any]]]:
    components: list[dict[str, Any]] = []
    dependency_map: dict[str, set[str]] = {}
    roots: list[dict[str, Any]] = []
    for relative in NPM_LOCKFILES:
        lock = read_json(repo_root, relative)
        if not isinstance(lock, dict) or lock.get("lockfileVersion") not in {2, 3} or not isinstance(lock.get("packages"), dict):
            raise ReleaseInputError(f"unsupported or malformed npm lockfile: {relative}")
        packages: dict[str, Any] = lock["packages"]
        refs: dict[str, str] = {}
        for node_path, item in sorted(packages.items()):
            if not isinstance(item, dict):
                raise ReleaseInputError(f"malformed package entry in {relative}: {node_path}")
            name = _npm_name(node_path, item)
            version = item.get("version")
            if not name or not isinstance(version, str) or not version:
                if node_path == "":
                    name = str(lock.get("name") or "unnamed-npm-workspace")
                    version = str(lock.get("version") or "0.0.0")
                else:
                    # Link/workspace entries without resolved identity are retained as evidence,
                    # but cannot be represented as resolved external packages.
                    continue
            bom_ref = stable_id("npm-component", relative, node_path, name, version)
            refs[node_path] = bom_ref
            properties = [
                {"name": "atlas:lockfile", "value": relative},
                {"name": "atlas:lockfilePath", "value": node_path or "<root>"},
                {"name": "atlas:resolution", "value": "lockfile-resolved"},
                {"name": "atlas:developmentOnly", "value": str(bool(item.get("dev"))).lower()},
            ]
            component: dict[str, Any] = {
                "type": "application" if node_path == "" else "library",
                "bom-ref": bom_ref,
                "group": name.split("/", 1)[0] if name.startswith("@") else "",
                "name": name.split("/", 1)[-1],
                "version": version,
                "purl": _purl_npm(name, version),
                "properties": properties,
            }
            if isinstance(item.get("license"), str):
                component["licenses"] = [{"expression": item["license"]}]
            if isinstance(item.get("integrity"), str):
                component["externalReferences"] = [
                    {"type": "distribution", "url": str(item.get("resolved") or "urn:atlas:undisclosed-distribution")}
                ]
                component["properties"].append({"name": "atlas:npmIntegrity", "value": item["integrity"]})
            components.append(component)
            dependency_map.setdefault(bom_ref, set())
            if node_path == "":
                roots.append({"lockfile": relative, "bom-ref": bom_ref})

        for node_path, item in sorted(packages.items()):
            source_ref = refs.get(node_path)
            if not source_ref or not isinstance(item, dict):
                continue
            names: set[str] = set()
            for field in ("dependencies", "optionalDependencies", "peerDependencies"):
                value = item.get(field)
                if isinstance(value, dict):
                    names.update(str(name) for name in value)
            for name in sorted(names):
                resolved_path = _resolve_npm(packages, node_path, name)
                target_ref = refs.get(resolved_path or "")
                if target_ref:
                    dependency_map[source_ref].add(target_ref)
    return components, dependency_map, roots


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


def _python_components(repo_root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    components: list[dict[str, Any]] = []
    declarations: list[dict[str, Any]] = []
    pyproject = safe_input(repo_root, "pyproject.toml")
    try:
        import tomllib  # type: ignore[attr-defined]
    except ImportError:  # pragma: no cover - Python 3.10 compatibility
        import tomli as tomllib  # type: ignore[no-redef]
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
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
        "properties": [{"name": "atlas:resolution", "value": "project-metadata"}],
    }
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
        path = safe_input(repo_root, relative)
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError) as exc:
            raise ReleaseInputError(f"could not read dependency declaration {relative}: {exc}") from exc
        for raw in lines:
            component = _requirement_component(raw, relative, "declared")
            if component:
                components.append(component)
        declarations.append({"manifest": relative, "bom-ref": root_ref})
    return components, declarations


def build_cyclonedx(repo_root: Path, source_commit: str, source_tree_digest: str) -> dict[str, Any]:
    npm_components, npm_edges, npm_roots = _npm_components(repo_root)
    python_components, python_roots = _python_components(repo_root)
    components = sorted(npm_components + python_components, key=lambda item: item["bom-ref"])
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

    serial_seed = hashlib.sha256(f"{source_commit}\x1f{source_tree_digest}".encode()).hexdigest()
    license_declared = sum(1 for component in components if component.get("licenses"))
    license_unknown = len(components) - license_declared
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
        "dependencies": [
            {"ref": key, "dependsOn": sorted(values)} for key, values in sorted(dependency_map.items())
        ],
        "properties": [
            {"name": "atlas:npmRoots", "value": str(len(npm_roots))},
            {"name": "atlas:pythonManifestRoots", "value": str(len(python_roots))},
            {"name": "atlas:componentDenominator", "value": str(len(components))},
            {"name": "atlas:licenseDeclared", "value": str(license_declared)},
            {"name": "atlas:licenseUnknown", "value": str(license_unknown)},
            {"name": "atlas:vulnerabilityAssessed", "value": "0"},
            {"name": "atlas:vulnerabilityNotAssessed", "value": str(len(components))},
            {"name": "atlas:pythonDeclaredUnlocked", "value": str(python_unlocked)},
            {
                "name": "atlas:releaseGate",
                "value": (
                    "BLOCK: Python transitive lock and vulnerability assessment remain incomplete; "
                    f"components with unknown license={license_unknown}"
                ),
            },
            {"name": "atlas:coverageHonesty", "value": "npm direct/transitive locked; Python direct declarations only"},
        ],
    }
