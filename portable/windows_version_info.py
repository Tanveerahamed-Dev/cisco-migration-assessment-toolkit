"""Source-bound Windows VERSIONINFO for the frozen Atlas executable."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from packaging.version import InvalidVersion, Version

from cisco_toolkit.brand_tokens import APP_BYLINE, APP_NAME


_COMPANY_NAME = "Tanveerahamed-Dev"
_COPYRIGHT = "Copyright (c) 2026 Tanveerahamed-Dev. All rights reserved."
_ORIGINAL_FILENAME = f"{APP_NAME}.exe"


def project_version(repository_root: str | Path) -> str:
    """Read the exact product version from its tracked owner."""
    try:
        import tomllib
    except ModuleNotFoundError:  # pragma: no cover - release builds use Python 3.12
        import tomli as tomllib  # type: ignore[no-redef]

    root = Path(repository_root)
    with (root / "pyproject.toml").open("rb") as stream:
        value = tomllib.load(stream).get("project", {}).get("version")
    if not isinstance(value, str) or not value:
        raise ValueError("pyproject product version is missing")
    try:
        parsed = Version(value)
    except InvalidVersion as exc:
        raise ValueError(f"pyproject product version is invalid: {value!r}") from exc
    if str(parsed) != value:
        raise ValueError(
            f"pyproject product version is not canonical PEP 440: {value!r} != {str(parsed)!r}"
        )
    return value


def fixed_file_version(value: str) -> tuple[int, int, int, int]:
    """Map canonical PEP 440 into an ordered four-word Windows file version.

    String metadata retains the exact PEP 440 value.  The fourth numeric word keeps
    prereleases below the final build so FilePublisher/SignedVersion rules have a
    monotonic value for the supported ``X.Y.Z[pre]`` release family.
    """
    try:
        parsed = Version(value)
    except InvalidVersion as exc:
        raise ValueError(f"invalid product version: {value!r}") from exc
    release = parsed.release
    if len(release) > 3:
        raise ValueError("Windows VERSIONINFO supports at most three release components")
    major, minor, patch = (*release, *([0] * (3 - len(release))))
    if any(not 0 <= item <= 0xFFFF for item in (major, minor, patch)):
        raise ValueError("Windows VERSIONINFO release component exceeds 16 bits")

    if parsed.post is not None:
        if parsed.post > 5_535:
            raise ValueError("post-release serial exceeds the Windows VERSIONINFO budget")
        build = 60_000 + parsed.post
    elif parsed.pre is not None:
        label, serial = parsed.pre
        bases = {"a": 10_000, "b": 20_000, "rc": 30_000}
        if label not in bases or serial > 9_999:
            raise ValueError("prerelease cannot be represented in Windows VERSIONINFO")
        build = bases[label] + serial
    elif parsed.dev is not None:
        if parsed.dev > 9_999:
            raise ValueError("development serial exceeds the Windows VERSIONINFO budget")
        build = parsed.dev
    else:
        build = 50_000
    return int(major), int(minor), int(patch), int(build)


def version_strings(repository_root: str | Path) -> dict[str, str]:
    """Return the closed Windows string-table values used by the build and smoke."""
    version = project_version(repository_root)
    return {
        "CompanyName": _COMPANY_NAME,
        "FileDescription": f"{APP_NAME} - {APP_BYLINE}",
        "FileVersion": version,
        "InternalName": APP_NAME,
        "LegalCopyright": _COPYRIGHT,
        "OriginalFilename": _ORIGINAL_FILENAME,
        "ProductName": APP_NAME,
        "ProductVersion": version,
    }


def version_expectations(repository_root: str | Path) -> dict[str, str]:
    """Expected Windows API projection, including the policy-facing numeric versions."""
    strings = version_strings(repository_root)
    numeric = ".".join(str(item) for item in fixed_file_version(strings["ProductVersion"]))
    return {**strings, "FixedFileVersion": numeric, "FixedProductVersion": numeric}


def pyinstaller_version_info(repository_root: str | Path) -> Any:
    """Build PyInstaller's in-memory VERSIONINFO object without a generated source file."""
    from PyInstaller.utils.win32.versioninfo import (
        FixedFileInfo,
        StringFileInfo,
        StringStruct,
        StringTable,
        VarFileInfo,
        VarStruct,
        VSVersionInfo,
    )

    strings = version_strings(repository_root)
    numeric = fixed_file_version(strings["ProductVersion"])
    return VSVersionInfo(
        ffi=FixedFileInfo(
            filevers=numeric,
            prodvers=numeric,
            mask=0x3F,
            flags=0x0,
            OS=0x40004,
            fileType=0x1,
            subtype=0x0,
            date=(0, 0),
        ),
        kids=[
            StringFileInfo(
                [
                    StringTable(
                        "040904B0",
                        [StringStruct(key, value) for key, value in strings.items()],
                    )
                ]
            ),
            VarFileInfo([VarStruct("Translation", [1033, 1200])]),
        ],
    )
