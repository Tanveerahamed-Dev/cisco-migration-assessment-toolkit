"""Run the frontend npm audit with one narrow, fail-closed exception.

``GHSA-qwww-vcr4-c8h2`` affects only React Router's unstable React Server
Components (RSC) APIs.  AssessHub is a browser-only SPA and does not use those
APIs, but npm still reports the direct ``react-router@7.18.2`` dependency as a
high-severity finding.  This verifier preserves the high/critical audit gate
while accepting only the exact npm advisory record reviewed on 2026-08-06.
The exception must be re-reviewed by 2026-11-06; it fails closed after that
date even if the dependency and advisory records are otherwise unchanged.

The exception is deliberately coupled to the current dependency and SPA
contracts.  Delete this verifier and restore a plain ``npm audit
--audit-level=high`` step as part of the planned migration to Node 24 LTS,
React >=19.2.7, Vite >=7, and React Router >=8.3.0.  Any earlier React Router
version change, RSC adoption, advisory-shape change, additional high/critical
finding, npm execution error, or malformed report fails closed and requires a
fresh review.  Never replace this policy with ``npm audit fix --force``: that
would perform the multi-major migration without its required compatibility
work.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import subprocess
import sys
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any, Mapping, NamedTuple, Sequence


_AUDIT_REPORT_VERSION = 2
_MAX_AUDIT_BYTES = 8 * 1024 * 1024
_MAX_JSON_BYTES = 4 * 1024 * 1024
_NPM_REGISTRY = "https://registry.npmjs.org/"
_EXPECTED_NODE_VERSION = "v20.20.2"
_EXPECTED_NPM_VERSION = "10.8.2"
_AUDIT_LEVELS = ("info", "low", "moderate", "high", "critical")
_BLOCKING_LEVELS = {"high", "critical"}
_EXEMPT_PACKAGE = "react-router"
_EXEMPT_VERSION = "7.18.2"
_EXCEPTION_REVIEWED_ON = date(2026, 8, 6)
_EXCEPTION_REVIEW_BY = date(2026, 11, 6)
_EXEMPT_ADVISORY = {
    "source": 1124282,
    "name": "react-router",
    "dependency": "react-router",
    "title": (
        "React Router: RSC Mode CSRF Bypass Allows Action Execution Before "
        "400 Response"
    ),
    "url": "https://github.com/advisories/GHSA-qwww-vcr4-c8h2",
    "severity": "high",
    "cwe": ["CWE-352"],
    "cvss": {"score": 0, "vectorString": None},
    "range": ">=7.12.0 <8.3.0",
}
_EXEMPT_VULNERABILITY = {
    "name": "react-router",
    "severity": "high",
    "isDirect": True,
    "via": [_EXEMPT_ADVISORY],
    "effects": [],
    "range": "7.12.0 - 8.2.0",
    "nodes": ["node_modules/react-router"],
    "fixAvailable": {
        "name": "react-router",
        "version": "8.3.0",
        "isSemVerMajor": True,
    },
}
_CURRENT_FRONTEND_CONTRACT = {
    "react": "18.3.1",
    "react-dom": "18.3.1",
    "react-router": _EXEMPT_VERSION,
}
_CURRENT_DEV_CONTRACT = {"vite": "6.4.3"}
_CURRENT_NODE_CONTRACT = ">=20.0.0"
_FORBIDDEN_RSC_DEPENDENCIES = {
    "@react-router/dev",
    "@react-router/node",
    "@react-router/serve",
    "@vitejs/plugin-rsc",
    "react-server-dom-webpack",
    "react-server-dom-parcel",
    "react-server-dom-turbopack",
}
_RSC_USAGE = re.compile(
    r"(?:\bRSC\b"
    r"|\bReact Server Components?\b"
    r"|\bunstable_[A-Za-z0-9_]*RSC[A-Za-z0-9_]*\b"
    r"|\bRSCStaticRouter\b"
    r"|\b(?:match|route)RSCServerRequest\b"
    r"|\bentry\.rsc(?:\.[cm]?[jt]sx?)?\b"
    r"|\breact-server-dom(?:-[A-Za-z0-9_-]+)?\b)",
    re.IGNORECASE,
)
_SOURCE_SUFFIXES = {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx"}
_REVIEWED_EXTERNAL_SOURCE_ROOTS = (".design-sync",)
_IGNORED_SOURCE_DIRS = {
    "node_modules",
    "dist",
    "coverage",
    "test-results",
    "playwright-report",
}
_RELATIVE_MODULE_SPECIFIER = re.compile(
    r"""(?:\bfrom\s*|\bimport\s*(?:\(\s*)?|\brequire\s*\(\s*)
        (?P<quote>["'])
        (?P<specifier>\.{1,2}/[^"'?#\r\n]+)
        (?:[?#][^"'\r\n]*)?
        (?P=quote)
    """,
    re.VERBOSE,
)
_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


class FrontendAuditError(ValueError):
    """The npm report or the temporary exception contract is unsafe."""


class AuditDecision(NamedTuple):
    """Result of applying the high/critical policy to a validated report."""

    exemption_used: bool
    message: str


def _is_reparse_point(info: os.stat_result) -> bool:
    return bool(int(getattr(info, "st_file_attributes", 0)) & _REPARSE_POINT)


def _read_regular_bounded(
    path: Path, maximum: int, *, allow_empty: bool = False
) -> bytes:
    try:
        info = path.lstat()
    except OSError as exc:
        raise FrontendAuditError(f"required file is unreadable: {path}") from exc
    if (
        stat.S_ISLNK(info.st_mode)
        or _is_reparse_point(info)
        or not stat.S_ISREG(info.st_mode)
    ):
        raise FrontendAuditError(f"required file is not an ordinary file: {path}")
    minimum = 0 if allow_empty else 1
    if info.st_size < minimum or info.st_size > maximum:
        raise FrontendAuditError(
            f"required file size is outside {minimum}..{maximum} bytes: {path}"
        )
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise FrontendAuditError(f"required file is unreadable: {path}") from exc
    if len(data) != info.st_size:
        raise FrontendAuditError(f"required file changed while reading: {path}")
    return data


def _load_json_file(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(
            _read_regular_bounded(path, _MAX_JSON_BYTES).decode(
                "utf-8", errors="strict"
            )
        )
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise FrontendAuditError(f"required JSON is malformed: {path}") from exc
    if not isinstance(value, dict):
        raise FrontendAuditError(f"required JSON root must be an object: {path}")
    return value


def _exact_keys(value: Mapping[str, Any], expected: set[str], context: str) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise FrontendAuditError(
            f"unexpected {context} keys (missing={missing}, extra={extra})"
        )


def _nonnegative_int(value: Any, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise FrontendAuditError(f"{context} must be a non-negative integer")
    return value


def _validate_via_entry(value: Any, context: str) -> None:
    if isinstance(value, str):
        if not value:
            raise FrontendAuditError(f"{context} package reference must not be empty")
        return
    if not isinstance(value, dict):
        raise FrontendAuditError(f"{context} must be an advisory object or package name")
    _exact_keys(
        value,
        {
            "source",
            "name",
            "dependency",
            "title",
            "url",
            "severity",
            "cwe",
            "cvss",
            "range",
        },
        context,
    )
    _nonnegative_int(value["source"], f"{context}.source")
    for field in ("name", "dependency", "title", "url", "range"):
        if not isinstance(value[field], str) or not value[field]:
            raise FrontendAuditError(f"{context}.{field} must be a non-empty string")
    if value["severity"] not in _AUDIT_LEVELS:
        raise FrontendAuditError(f"{context}.severity is invalid")
    if (
        not isinstance(value["cwe"], list)
        or any(not isinstance(item, str) or not item for item in value["cwe"])
    ):
        raise FrontendAuditError(f"{context}.cwe must be a string list")
    cvss = value["cvss"]
    if not isinstance(cvss, dict):
        raise FrontendAuditError(f"{context}.cvss must be an object")
    _exact_keys(cvss, {"score", "vectorString"}, f"{context}.cvss")
    score = cvss["score"]
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        raise FrontendAuditError(f"{context}.cvss.score must be numeric")
    if not 0 <= score <= 10:
        raise FrontendAuditError(f"{context}.cvss.score is outside 0..10")
    vector = cvss["vectorString"]
    if vector is not None and not isinstance(vector, str):
        raise FrontendAuditError(f"{context}.cvss.vectorString is invalid")


def _validate_fix_available(value: Any, context: str) -> None:
    if isinstance(value, bool):
        return
    if not isinstance(value, dict):
        raise FrontendAuditError(f"{context}.fixAvailable has an invalid type")
    _exact_keys(value, {"name", "version", "isSemVerMajor"}, f"{context}.fixAvailable")
    if not isinstance(value["name"], str) or not value["name"]:
        raise FrontendAuditError(f"{context}.fixAvailable.name is invalid")
    if not isinstance(value["version"], str) or not value["version"]:
        raise FrontendAuditError(f"{context}.fixAvailable.version is invalid")
    if not isinstance(value["isSemVerMajor"], bool):
        raise FrontendAuditError(f"{context}.fixAvailable.isSemVerMajor is invalid")


def _validate_vulnerability(name: str, value: Any) -> Mapping[str, Any]:
    context = f"vulnerabilities.{name}"
    if not isinstance(value, dict):
        raise FrontendAuditError(f"{context} must be an object")
    _exact_keys(
        value,
        {
            "name",
            "severity",
            "isDirect",
            "via",
            "effects",
            "range",
            "nodes",
            "fixAvailable",
        },
        context,
    )
    if value["name"] != name:
        raise FrontendAuditError(f"{context}.name does not match its package key")
    if value["severity"] not in _AUDIT_LEVELS:
        raise FrontendAuditError(f"{context}.severity is invalid")
    if not isinstance(value["isDirect"], bool):
        raise FrontendAuditError(f"{context}.isDirect must be boolean")
    via = value["via"]
    if not isinstance(via, list) or not via:
        raise FrontendAuditError(f"{context}.via must be a non-empty list")
    for index, item in enumerate(via):
        _validate_via_entry(item, f"{context}.via[{index}]")
    for field in ("effects", "nodes"):
        items = value[field]
        if (
            not isinstance(items, list)
            or any(not isinstance(item, str) or not item for item in items)
        ):
            raise FrontendAuditError(f"{context}.{field} must be a string list")
    if not isinstance(value["range"], str):
        raise FrontendAuditError(f"{context}.range must be a string")
    _validate_fix_available(value["fixAvailable"], context)
    return value


def parse_audit_report(raw: bytes) -> dict[str, Any]:
    """Decode and validate npm audit report v2 without accepting schema drift."""
    if not raw or len(raw) > _MAX_AUDIT_BYTES:
        raise FrontendAuditError(
            f"npm audit output size is outside 1..{_MAX_AUDIT_BYTES} bytes"
        )
    try:
        report = json.loads(raw.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise FrontendAuditError("npm audit did not return valid UTF-8 JSON") from exc
    if not isinstance(report, dict):
        raise FrontendAuditError("npm audit report root must be an object")
    _exact_keys(
        report,
        {"auditReportVersion", "vulnerabilities", "metadata"},
        "audit report",
    )
    if report["auditReportVersion"] != _AUDIT_REPORT_VERSION:
        raise FrontendAuditError(
            f"unsupported npm audit report version: {report['auditReportVersion']!r}"
        )

    vulnerabilities = report["vulnerabilities"]
    if not isinstance(vulnerabilities, dict):
        raise FrontendAuditError("audit vulnerabilities must be an object")
    severity_counts: Counter[str] = Counter()
    for name, value in vulnerabilities.items():
        if not isinstance(name, str) or not name:
            raise FrontendAuditError("audit vulnerability keys must be package names")
        record = _validate_vulnerability(name, value)
        severity_counts[record["severity"]] += 1

    metadata = report["metadata"]
    if not isinstance(metadata, dict):
        raise FrontendAuditError("audit metadata must be an object")
    _exact_keys(metadata, {"vulnerabilities", "dependencies"}, "audit metadata")
    metadata_vulnerabilities = metadata["vulnerabilities"]
    if not isinstance(metadata_vulnerabilities, dict):
        raise FrontendAuditError("audit metadata.vulnerabilities must be an object")
    _exact_keys(
        metadata_vulnerabilities,
        {*_AUDIT_LEVELS, "total"},
        "audit metadata.vulnerabilities",
    )
    for level in _AUDIT_LEVELS:
        count = _nonnegative_int(
            metadata_vulnerabilities[level],
            f"audit metadata.vulnerabilities.{level}",
        )
        if count != severity_counts[level]:
            raise FrontendAuditError(
                f"audit metadata count disagrees for {level}: "
                f"{count} != {severity_counts[level]}"
            )
    total = _nonnegative_int(
        metadata_vulnerabilities["total"],
        "audit metadata.vulnerabilities.total",
    )
    if total != len(vulnerabilities) or total != sum(severity_counts.values()):
        raise FrontendAuditError("audit metadata total disagrees with vulnerabilities")

    dependencies = metadata["dependencies"]
    if not isinstance(dependencies, dict):
        raise FrontendAuditError("audit metadata.dependencies must be an object")
    _exact_keys(
        dependencies,
        {"prod", "dev", "optional", "peer", "peerOptional", "total"},
        "audit metadata.dependencies",
    )
    for name, value in dependencies.items():
        _nonnegative_int(value, f"audit metadata.dependencies.{name}")
    return report


def evaluate_audit_report(
    report: Mapping[str, Any], npm_exit_code: int
) -> AuditDecision:
    """Apply the threshold and exact exception to an already validated report."""
    vulnerabilities = report["vulnerabilities"]

    def is_blocking(record: Mapping[str, Any]) -> bool:
        if record["severity"] in _BLOCKING_LEVELS:
            return True
        return any(
            isinstance(item, dict) and item["severity"] in _BLOCKING_LEVELS
            for item in record["via"]
        )

    blocking = {
        name: record
        for name, record in vulnerabilities.items()
        if is_blocking(record)
    }
    expected_exit = 1 if blocking else 0
    if npm_exit_code != expected_exit:
        raise FrontendAuditError(
            "npm audit exit status disagrees with its high/critical report: "
            f"got {npm_exit_code}, expected {expected_exit}"
        )
    if not blocking:
        return AuditDecision(False, "frontend npm audit passed without an exception")
    if set(blocking) != {_EXEMPT_PACKAGE}:
        packages = ", ".join(sorted(blocking))
        raise FrontendAuditError(
            f"unapproved high/critical npm vulnerabilities: {packages}"
        )
    if blocking[_EXEMPT_PACKAGE] != _EXEMPT_VULNERABILITY:
        raise FrontendAuditError(
            "react-router audit record no longer exactly matches the reviewed "
            "GHSA-qwww-vcr4-c8h2 exception"
        )
    return AuditDecision(
        True,
        "frontend npm audit passed with the reviewed SPA-only exception for "
        "GHSA-qwww-vcr4-c8h2",
    )


def assert_exception_review_current(today: date | None = None) -> None:
    """Fail closed once the temporary exception's review window has elapsed."""
    current = today or date.today()
    if current > _EXCEPTION_REVIEW_BY:
        raise FrontendAuditError(
            "temporary npm exception review expired on "
            f"{_EXCEPTION_REVIEW_BY.isoformat()}; remove it via the Node 24 / "
            "React 19.2.7 / Vite 7 / React Router 8.3 migration, or perform "
            "and document a fresh security review"
        )


def _read_tool_version(command: Sequence[str], label: str) -> str:
    """Read one small, exact tool version without accepting shell mediation."""
    try:
        result = subprocess.run(
            list(command),
            check=False,
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise FrontendAuditError(f"{label} version could not be read: {exc}") from exc
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        detail = f": {stderr}" if stderr else ""
        raise FrontendAuditError(
            f"{label} version command failed with exit {result.returncode}{detail}"
        )
    if not result.stdout or len(result.stdout) > 256:
        raise FrontendAuditError(f"{label} version output is empty or oversized")
    try:
        version = result.stdout.decode("utf-8", errors="strict").strip()
    except UnicodeError as exc:
        raise FrontendAuditError(f"{label} version output is not UTF-8") from exc
    if not version or any(character.isspace() for character in version):
        raise FrontendAuditError(f"{label} version output is malformed")
    return version


def assert_audit_toolchain() -> None:
    """Bind the exact reviewed npm JSON contract to its producing runtime."""
    npm = "npm.cmd" if os.name == "nt" else "npm"
    node_version = _read_tool_version(("node", "--version"), "Node")
    npm_version = _read_tool_version((npm, "--version"), "npm")
    if node_version != _EXPECTED_NODE_VERSION or npm_version != _EXPECTED_NPM_VERSION:
        raise FrontendAuditError(
            "temporary npm exception requires the reviewed audit toolchain "
            f"Node {_EXPECTED_NODE_VERSION} / npm {_EXPECTED_NPM_VERSION}; got "
            f"Node {node_version} / npm {npm_version}"
        )


def _dependency_groups(package: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    groups = []
    for field in (
        "dependencies",
        "devDependencies",
        "optionalDependencies",
        "peerDependencies",
    ):
        value = package.get(field, {})
        if not isinstance(value, dict):
            raise FrontendAuditError(f"package.json {field} must be an object")
        groups.append(value)
    return groups


def _assert_exact_dependency_contract(
    package: Mapping[str, Any], lock: Mapping[str, Any]
) -> None:
    dependencies = package.get("dependencies")
    dev_dependencies = package.get("devDependencies")
    engines = package.get("engines")
    if not isinstance(dependencies, dict) or not isinstance(dev_dependencies, dict):
        raise FrontendAuditError("frontend dependency groups are malformed")
    if not isinstance(engines, dict):
        raise FrontendAuditError("frontend engines contract is malformed")
    for name, expected in _CURRENT_FRONTEND_CONTRACT.items():
        if dependencies.get(name) != expected:
            raise FrontendAuditError(
                f"temporary npm exception expired: expected {name}@{expected}"
            )
    for name, expected in _CURRENT_DEV_CONTRACT.items():
        if dev_dependencies.get(name) != expected:
            raise FrontendAuditError(
                f"temporary npm exception expired: expected {name}@{expected}"
            )
    if engines.get("node") != _CURRENT_NODE_CONTRACT:
        raise FrontendAuditError(
            "temporary npm exception expired: Node engine contract changed"
        )

    packages = lock.get("packages")
    if lock.get("lockfileVersion") != 3 or not isinstance(packages, dict):
        raise FrontendAuditError("package-lock.json must use lockfileVersion 3")
    root = packages.get("")
    if not isinstance(root, dict):
        raise FrontendAuditError("package-lock.json is missing its root package")
    root_dependencies = root.get("dependencies")
    root_dev_dependencies = root.get("devDependencies")
    if not isinstance(root_dependencies, dict) or not isinstance(
        root_dev_dependencies, dict
    ):
        raise FrontendAuditError("package-lock.json root dependency groups are malformed")
    for name, expected in _CURRENT_FRONTEND_CONTRACT.items():
        if root_dependencies.get(name) != expected:
            raise FrontendAuditError(
                f"package-lock root does not pin {name}@{expected}"
            )
        installed = packages.get(f"node_modules/{name}")
        if not isinstance(installed, dict) or installed.get("version") != expected:
            raise FrontendAuditError(
                f"package-lock does not resolve {name}@{expected}"
            )
    for name, expected in _CURRENT_DEV_CONTRACT.items():
        if root_dev_dependencies.get(name) != expected:
            raise FrontendAuditError(
                f"package-lock root does not pin {name}@{expected}"
            )
        installed = packages.get(f"node_modules/{name}")
        if not isinstance(installed, dict) or installed.get("version") != expected:
            raise FrontendAuditError(
                f"package-lock does not resolve {name}@{expected}"
            )


def _assert_ordinary_directory(path: Path, label: str) -> None:
    try:
        info = path.lstat()
    except OSError as exc:
        raise FrontendAuditError(f"{label} source root is unreadable: {path}") from exc
    if (
        stat.S_ISLNK(info.st_mode)
        or _is_reparse_point(info)
        or not stat.S_ISDIR(info.st_mode)
    ):
        raise FrontendAuditError(f"{label} source root is not an ordinary directory")


def _reviewed_source_roots(frontend_root: Path) -> tuple[Path, ...]:
    if frontend_root.name != "frontend" or frontend_root.parent.name != "webapp":
        raise FrontendAuditError(
            "frontend root must retain the reviewed webapp/frontend layout"
        )
    _assert_ordinary_directory(frontend_root, "frontend")
    repository_root = frontend_root.parents[1]
    roots = [frontend_root]
    for relative in _REVIEWED_EXTERNAL_SOURCE_ROOTS:
        root = repository_root / relative
        _assert_ordinary_directory(root, relative)
        roots.append(root)
    return tuple(roots)


def _iter_source_files(root: Path, *, ignore_generated_roots: bool):
    """Yield ordinary source files without traversing links or generated roots."""
    for current, directory_names, file_names in os.walk(
        root, topdown=True, followlinks=False
    ):
        directory = Path(current)
        retained_directories = []
        for name in sorted(directory_names):
            if (
                ignore_generated_roots
                and directory == root
                and name in _IGNORED_SOURCE_DIRS
            ):
                continue
            candidate = directory / name
            try:
                info = candidate.lstat()
            except OSError as exc:
                raise FrontendAuditError(
                    f"source directory is unreadable: {candidate}"
                ) from exc
            if stat.S_ISLNK(info.st_mode) or _is_reparse_point(info):
                raise FrontendAuditError(
                    f"source directory links are outside the reviewed contract: {candidate}"
                )
            if not stat.S_ISDIR(info.st_mode):
                raise FrontendAuditError(f"source path is not a directory: {candidate}")
            retained_directories.append(name)
        directory_names[:] = retained_directories

        for name in sorted(file_names):
            path = directory / name
            if path.suffix.casefold() not in _SOURCE_SUFFIXES:
                continue
            # The bounded reader repeats the lstat immediately before reading,
            # so a source-file link or mid-scan replacement still fails closed.
            yield path


def _assert_relative_modules_stay_reviewed(
    path: Path, text: str, source_roots: tuple[Path, ...]
) -> None:
    resolved_roots = tuple(root.resolve(strict=True) for root in source_roots)
    for match in _RELATIVE_MODULE_SPECIFIER.finditer(text):
        specifier = match.group("specifier")
        try:
            target = (path.parent / specifier).resolve(strict=False)
        except OSError as exc:
            raise FrontendAuditError(
                f"relative module path cannot be resolved in {path}: {specifier}"
            ) from exc
        if not any(target == root or target.is_relative_to(root) for root in resolved_roots):
            raise FrontendAuditError(
                "relative module import escapes the reviewed frontend source roots: "
                f"{path} -> {specifier}"
            )


def assert_spa_only_exception_contract(frontend_root: Path) -> None:
    """Prove that the reviewed RSC-only non-applicability remains true."""
    try:
        (frontend_root / ".npmrc").lstat()
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise FrontendAuditError("frontend .npmrc cannot be inspected") from exc
    else:
        raise FrontendAuditError(
            "frontend .npmrc is outside the reviewed audit configuration contract"
        )
    package = _load_json_file(frontend_root / "package.json")
    lock = _load_json_file(frontend_root / "package-lock.json")
    _assert_exact_dependency_contract(package, lock)

    dependency_names = {
        name for group in _dependency_groups(package) for name in group
    }
    forbidden = sorted(dependency_names & _FORBIDDEN_RSC_DEPENDENCIES)
    if forbidden:
        raise FrontendAuditError(
            "temporary npm exception is invalid after RSC-capable dependencies "
            f"were added: {', '.join(forbidden)}"
        )

    source_roots = _reviewed_source_roots(frontend_root)
    repository_root = frontend_root.parents[1]
    for source_root in source_roots:
        for path in _iter_source_files(
            source_root, ignore_generated_roots=source_root == frontend_root
        ):
            try:
                relative = path.relative_to(repository_root)
                text = _read_regular_bounded(
                    path, _MAX_JSON_BYTES, allow_empty=True
                ).decode("utf-8", errors="strict")
            except UnicodeError as exc:
                raise FrontendAuditError(
                    f"frontend source is not UTF-8: {relative}"
                ) from exc
            _assert_relative_modules_stay_reviewed(path, text, source_roots)
            if _RSC_USAGE.search(relative.as_posix()) or _RSC_USAGE.search(text):
                raise FrontendAuditError(
                    "temporary npm exception is invalid after React Router RSC usage "
                    f"appeared in {relative.as_posix()}"
                )


def _run_npm_audit(frontend_root: Path) -> tuple[bytes, int]:
    npm = "npm.cmd" if os.name == "nt" else "npm"
    # Do not inherit a user/project-supplied npm_config_* registry, omit, offline,
    # or audit setting. CLI flags are duplicated in the clean environment so the
    # audit always queries the public registry and includes the complete lock.
    audit_env = {
        name: value
        for name, value in os.environ.items()
        if not name.casefold().startswith("npm_config_")
    }
    audit_env.update(
        {
            "NPM_CONFIG_USERCONFIG": os.devnull,
            "NPM_CONFIG_GLOBALCONFIG": os.devnull,
            "NPM_CONFIG_REGISTRY": _NPM_REGISTRY,
        }
    )
    command = [
        npm,
        "audit",
        "--audit-level=high",
        "--json",
        f"--registry={_NPM_REGISTRY}",
        "--offline=false",
        "--include=prod",
        "--include=dev",
        "--include=optional",
        "--include=peer",
    ]
    try:
        result = subprocess.run(
            command,
            cwd=frontend_root,
            check=False,
            capture_output=True,
            env=audit_env,
            timeout=180,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise FrontendAuditError(f"npm audit could not run: {exc}") from exc
    if result.returncode not in {0, 1}:
        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        detail = f": {stderr}" if stderr else ""
        raise FrontendAuditError(
            f"npm audit failed operationally with exit {result.returncode}{detail}"
        )
    return result.stdout, result.returncode


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--frontend-root",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "webapp" / "frontend",
    )
    args = parser.parse_args(argv)
    frontend_root = Path(os.path.abspath(args.frontend_root))
    try:
        assert_spa_only_exception_contract(frontend_root)
        # The review deadline applies while this old dependency contract is
        # pinned even if a registry temporarily withdraws or suppresses the GHSA.
        assert_exception_review_current()
        assert_audit_toolchain()
        raw, exit_code = _run_npm_audit(frontend_root)
        report = parse_audit_report(raw)
        decision = evaluate_audit_report(report, exit_code)
    except FrontendAuditError as exc:
        print(f"frontend npm audit policy failed: {exc}", file=sys.stderr)
        return 1
    print(decision.message)
    if decision.exemption_used:
        print(
            "temporary exception was reviewed on "
            f"{_EXCEPTION_REVIEWED_ON.isoformat()}, must be re-reviewed by "
            f"{_EXCEPTION_REVIEW_BY.isoformat()}, and must be deleted with "
            "the Node 24 / React 19.2.7 / Vite 7 / React Router 8.3 migration"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
