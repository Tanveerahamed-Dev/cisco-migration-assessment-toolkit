"""Build, externally sign, or verify a Master Reference release family."""

from __future__ import annotations

import argparse
import getpass
import json
import sys
from pathlib import Path
from typing import Sequence

from release.pipeline import ReleaseError, build_release
from release.signing import SigningUnavailable, sign_manifest, verify_artifact_family, verify_manifest


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m cli",
        description="Deterministic, offline Atlas Master Reference release tooling.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    build = commands.add_parser("build", help="build one exact-source unsigned release preview")
    build.add_argument("--repo-root", type=Path, required=True)
    build.add_argument("--compiler-output", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--pdf", type=Path, help="use an existing externally rendered PDF instead of the deterministic renderer")
    build.add_argument(
        "--no-pdf",
        action="store_true",
        help="emit an explicitly incomplete structural preview without the mandatory PDF",
    )
    build.add_argument("--enhancement-gap", help="pre-fill the enhancement brief with one catalog gap id")

    sign = commands.add_parser("sign", help="sign exact manifest bytes with an existing external Ed25519 key")
    sign.add_argument("--manifest", type=Path, required=True)
    sign.add_argument("--private-key", type=Path, required=True)
    sign.add_argument("--signature", type=Path, required=True)
    sign.add_argument(
        "--prompt-passphrase",
        action="store_true",
        help="read an encrypted-key passphrase from the terminal without echo or argument logging",
    )

    verify = commands.add_parser("verify", help="verify manifest signature using a separately trusted public key")
    verify.add_argument("--manifest", type=Path, required=True)
    verify.add_argument("--signature", type=Path, required=True)
    verify.add_argument("--public-key", type=Path, required=True)

    verify_family = commands.add_parser(
        "verify-family",
        help="verify canonical manifest syntax and every artifact receipt without asserting signature trust",
    )
    verify_family.add_argument("--manifest", type=Path, required=True)
    return parser


def main(arguments: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(arguments)
    try:
        if args.command == "build":
            manifest = build_release(
                args.repo_root,
                args.compiler_output,
                args.output,
                pdf_path=args.pdf,
                generate_pdf=not args.no_pdf and args.pdf is None,
                enhancement_gap=args.enhancement_gap,
            )
            result = {
                "ok": True,
                "release_status": manifest["release_status"],
                "source_commit": manifest["source_binding"]["source_commit"],
                "source_tree_digest": manifest["source_binding"]["source_tree_digest"],
                "output": str(args.output.resolve(strict=True)),
                "next_gate": "externally sign release-manifest.json only after independent review",
            }
        elif args.command == "sign":
            password = None
            if args.prompt_passphrase:
                entered = getpass.getpass("Ed25519 key passphrase: ")
                password = entered.encode("utf-8")
            envelope = sign_manifest(
                args.manifest,
                args.private_key,
                args.signature,
                password=password,
            )
            result = {
                "ok": True,
                "status": envelope["status"],
                "target_sha256": envelope["target_sha256"],
                "public_key_fingerprint": envelope["public_key_fingerprint"],
                "next_gate": "verify with the separately trusted owner public key",
            }
        elif args.command == "verify":
            result = verify_manifest(args.manifest, args.signature, args.public_key)
            result["ok"] = True
        else:
            result = verify_artifact_family(args.manifest)
            result.update(
                {
                    "ok": True,
                    "integrity_only": True,
                    "trust_note": "Artifact receipts verified; signature trust, semantic approval, and publication authority remain separate gates.",
                }
            )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
        return 0
    except (ReleaseError, SigningUnavailable, RuntimeError, OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
