"""Build, qualify, package, and reverify one exact Atlas Windows x64 release candidate."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

from portable import build_atlas, qualify_atlas
from portable.release_contract import (
    PortableReleaseError,
    build_portable_release,
    canonical_json,
    source_identity,
    verify_release_set,
)


ROOT = Path(__file__).resolve().parents[1]
TOOLCHAIN = ROOT / "portable" / "toolchain.json"


def _distribution_name(value: object) -> str:
    return re.sub(r"[-_.]+", "-", str(value).casefold())


def _output(command: list[str]) -> str:
    process = subprocess.run(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        check=False,
    )
    if process.returncode:
        raise PortableReleaseError(f"toolchain probe failed: {command[0]}")
    return process.stdout.strip()


def verify_toolchain() -> dict:
    contract = json.loads(TOOLCHAIN.read_text(encoding="utf-8"))
    node = shutil.which("node")
    npm = shutil.which("npm.cmd") or shutil.which("npm")
    observed = {
        "platform": "windows-x64" if os.name == "nt" and platform.machine().upper() in {"AMD64", "X86_64"} else "unsupported",
        "python": platform.python_version(),
        "pip": importlib.metadata.version("pip"),
        "pyinstaller": importlib.metadata.version("pyinstaller"),
        "node": _output([node, "--version"]) if node else None,
        "npm": _output([npm, "--version"]) if npm else None,
    }
    expected = {key: contract[key] for key in observed}
    if observed != expected:
        raise PortableReleaseError(f"portable build toolchain mismatch: expected {expected}, observed {observed}")
    lock = (ROOT / "portable" / "windows-x64-requirements.lock").read_text(encoding="utf-8")
    locked_rows = [
        (_distribution_name(match.group(1)), match.group(2))
        for match in re.finditer(r"^([A-Za-z0-9_.-]+)==([^\s\\]+)", lock, flags=re.MULTILINE)
    ]
    locked = dict(locked_rows)
    if len(locked) != len(locked_rows):
        raise PortableReleaseError("reviewed lock contains duplicate normalized distribution names")
    installed_rows = [
        (_distribution_name(distribution.metadata.get("Name") or ""), str(distribution.version))
        for distribution in importlib.metadata.distributions()
        if distribution.metadata.get("Name")
    ]
    installed = dict(installed_rows)
    if len(installed) != len(installed_rows):
        raise PortableReleaseError("build environment contains duplicate normalized distributions")
    extras = set(installed) - set(locked)
    missing = set(locked) - set(installed)
    wrong = {
        name: {"expected": locked[name], "observed": installed[name]}
        for name in set(installed) & set(locked)
        if installed[name] != locked[name]
    }
    if extras or missing or wrong:
        raise PortableReleaseError(
            "isolated build environment differs from the reviewed lock: "
            f"extras={sorted(extras)}, missing={sorted(missing)}, wrong={wrong}"
        )
    if set(installed) & {"openai", "graphify", "graphifyy", "obsidian"}:
        raise PortableReleaseError("isolated build environment contains a forbidden runtime")
    npm_tarball_path = os.environ.get("ATLAS_NPM_TARBALL", "")
    if not npm_tarball_path:
        raise PortableReleaseError("verified npm tarball path is missing from the build environment")
    npm_tarball = Path(npm_tarball_path).resolve(strict=True)
    npm_tarball_sha512 = hashlib.sha512(npm_tarball.read_bytes()).hexdigest()
    if npm_tarball_sha512 != contract.get("npm_tarball", {}).get("sha512_hex"):
        raise PortableReleaseError("verified npm tarball differs from the toolchain contract")
    return {
        "contract": contract,
        "observed": observed,
        "npm_tarball": {
            "name": npm_tarball.name,
            "bytes": npm_tarball.stat().st_size,
            "sha512": npm_tarball_sha512,
        },
    }


def build_release(output: str | Path) -> dict:
    before = source_identity(ROOT)
    verify_toolchain()
    build_atlas.build()
    build_atlas.smoke(8479)
    if source_identity(ROOT) != before:
        raise PortableReleaseError("PyInstaller build changed the exact source identity")
    qualification = qualify_atlas.qualify(ROOT, build_atlas.DIST)
    index = build_portable_release(
        ROOT,
        build_atlas.DIST,
        output,
        qualification,
    )
    verified = verify_release_set(
        output,
        expected_source=before,
        expected_material_root=ROOT,
    )
    if source_identity(ROOT) != before:
        raise PortableReleaseError("qualification or packaging changed the exact source identity")
    if verified["status"] != "SELF_CONSISTENCY_PASS":
        raise PortableReleaseError("final portable release-set verification did not pass")
    return {"index": index, "verification": verified}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, help="fresh directory outside the repository")
    parser.add_argument("--json-out", help="optional final controller receipt")
    args = parser.parse_args(argv)
    try:
        if args.json_out:
            output = Path(args.output).resolve(strict=False)
            json_out = Path(args.json_out).resolve(strict=False)
            if (
                json_out == output
                or output in json_out.parents
                or json_out == ROOT
                or ROOT in json_out.parents
                or json_out == build_atlas.DIST
                or build_atlas.DIST in json_out.parents
            ):
                raise PortableReleaseError(
                    "controller receipt must be outside the release set, source, and bundle"
                )
        result = build_release(args.output)
    except (OSError, PortableReleaseError, subprocess.SubprocessError) as exc:
        print(f"portable release REFUSED: {exc}", file=sys.stderr)
        return 1
    if args.json_out:
        Path(args.json_out).write_bytes(canonical_json(result))
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
