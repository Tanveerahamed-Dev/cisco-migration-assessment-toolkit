"""Reverify an Atlas portable ZIP without trusting its producer."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from portable.release_contract import (
    PortableReleaseError,
    verify_installed_bundle,
    verify_portable_release,
    verify_release_set,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--zip", dest="zip_path")
    group.add_argument("--installed")
    group.add_argument("--release-dir")
    parser.add_argument("--expected-source-json")
    parser.add_argument("--expected-sha256")
    parser.add_argument("--source-root")
    parser.add_argument("--allow-runtime-extensions", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "--stdlib-only",
        action="store_true",
        help="recheck bytes/receipts without importing the CycloneDX validator; result discloses omission",
    )
    args = parser.parse_args(argv)
    try:
        if args.allow_runtime_extensions and (
            not args.zip_path or not args.expected_sha256 or args.stdlib_only
            or args.source_root or args.expected_source_json
        ):
            raise PortableReleaseError("updater compatibility requires a ZIP, published SHA-256 and full schema validation")
        expected_source = (
            json.loads(Path(args.expected_source_json).read_text(encoding="utf-8", errors="strict"))
            if args.expected_source_json
            else None
        )
        if args.zip_path:
            result = verify_portable_release(
                args.zip_path,
                expected_source=expected_source,
                expected_zip_sha256=args.expected_sha256,
                validate_sbom_schema=not args.stdlib_only,
                expected_material_root=args.source_root,
                _allow_runtime_extensions=args.allow_runtime_extensions,
            )
        elif args.release_dir:
            result = verify_release_set(
                args.release_dir,
                expected_source=expected_source,
                expected_zip_sha256=args.expected_sha256,
                validate_sbom_schema=not args.stdlib_only,
                expected_material_root=args.source_root,
            )
        else:
            if (
                expected_source is not None
                or args.expected_sha256 is not None
                or args.stdlib_only
                or args.source_root is not None
            ):
                raise PortableReleaseError("expectation options do not apply to an installed tree")
            result = verify_installed_bundle(args.installed)
    except (OSError, json.JSONDecodeError, PortableReleaseError) as exc:
        print(f"portable release verification REFUSED: {exc}", file=sys.stderr)
        return 1
    if args.allow_runtime_extensions:
        result = {
            "schema": "atlas.portable-update-verification/1",
            "policy": "sha256_bound_runtime_extension",
            "authentication": "operator_selected_digest_not_publisher_authentication",
            "verification": result,
        }
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
