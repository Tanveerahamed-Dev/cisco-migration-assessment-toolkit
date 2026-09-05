"""Preflight an unsigned Atlas tree and emit its exact external signing manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from portable.release_contract import (
    PortableReleaseError,
    canonical_json,
    collect_members,
    member_manifest,
    source_identity,
    toolchain_receipt,
)


ROOT = Path(__file__).resolve().parents[1]


def prepare(
    bundle_path: str | Path,
    output_path: str | Path,
    toolchain_output_path: str | Path,
    *,
    repository_root: str | Path = ROOT,
) -> dict:
    repository_root = Path(repository_root).resolve(strict=True)
    bundle = Path(bundle_path).resolve(strict=True)
    output = Path(output_path).resolve(strict=False)
    toolchain_output = Path(toolchain_output_path).resolve(strict=False)
    if output == toolchain_output:
        raise PortableReleaseError("signing manifest and toolchain outputs must be distinct")
    if output.exists() or toolchain_output.exists():
        raise PortableReleaseError("signing evidence outputs must be fresh paths")
    if any(path == bundle or bundle in path.parents for path in (output, toolchain_output)):
        raise PortableReleaseError("signing evidence must be outside the bundle it describes")
    if any(
        path == repository_root or repository_root in path.parents
        for path in (output, toolchain_output)
    ):
        raise PortableReleaseError("signing evidence must be outside the clean source repository")
    manifest = member_manifest(source_identity(repository_root), collect_members(bundle))
    toolchain = toolchain_receipt(repository_root)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(canonical_json(manifest))
    toolchain_output.parent.mkdir(parents=True, exist_ok=True)
    toolchain_output.write_bytes(canonical_json(toolchain))
    return {
        "schema": "atlas.portable-signing-preflight/1",
        "manifest": str(output),
        "manifest_sha256": hashlib.sha256(canonical_json(manifest)).hexdigest(),
        "toolchain": str(toolchain_output),
        "toolchain_sha256": hashlib.sha256(canonical_json(toolchain)).hexdigest(),
        "member_set_digest": manifest["summary"]["member_set_digest"],
        "executable_member_count": sum(item["executable"] for item in manifest["members"]),
        "authority_effect": "NONE",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--toolchain-out", required=True)
    args = parser.parse_args(argv)
    try:
        result = prepare(args.bundle, args.out, args.toolchain_out)
    except (OSError, PortableReleaseError) as exc:
        print(f"portable signing preflight REFUSED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
