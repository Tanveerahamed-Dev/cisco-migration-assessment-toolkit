"""Qualify and package an already-built, already-signed Atlas candidate without rebuilding it.

The signing receipt must describe the exact current PE bytes. This controller deliberately does
not call PyInstaller: signing changes the executable member hashes, so the signed tree must be
qualified and packaged as one post-signing byte set.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from portable import qualify_atlas
from portable.build_release import verify_toolchain
from portable.release_contract import (
    PortableReleaseError,
    build_portable_release,
    canonical_json,
    collect_members,
    member_manifest,
    source_identity,
    toolchain_receipt,
    validate_member_manifest,
    verify_release_set,
)


ROOT = Path(__file__).resolve().parents[1]


def _independent_authenticode(bundle: Path, source: dict) -> dict:
    if os.name != "nt":
        raise PortableReleaseError("signed portable packaging requires Windows Authenticode policy")
    members = collect_members(bundle)
    manifest = member_manifest(source, members)
    powershell = (
        Path(os.environ.get("SystemRoot", r"C:\Windows"))
        / "System32"
        / "WindowsPowerShell"
        / "v1.0"
        / "powershell.exe"
    ).resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix="atlas-authenticode-verification-") as temporary:
        temporary_path = Path(temporary)
        manifest_path = temporary_path / "portable-member-manifest.json"
        receipt_path = temporary_path / "authenticode.json"
        manifest_path.write_bytes(canonical_json(manifest))
        process = subprocess.run(
            [
                str(powershell),
                "-NoProfile",
                "-NonInteractive",
                "-File",
                str(ROOT / "portable" / "verify_signatures.ps1"),
                "-Bundle",
                str(bundle),
                "-Manifest",
                str(manifest_path),
                "-OutReceipt",
                str(receipt_path),
            ],
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=900,
            check=False,
        )
        if process.returncode or not receipt_path.is_file():
            raise PortableReleaseError(
                "independent Authenticode verification failed: "
                + (process.stdout + process.stderr)[-1200:].strip()
            )
        receipt = json.loads(receipt_path.read_text(encoding="utf-8", errors="strict"))
    subject = receipt.get("subject", {})
    expected_pe = [
        {"path": item["path"], "sha256": item["sha256"]}
        for item in members
        if item["executable"]
    ]
    observed_pe = [
        {"path": item.get("path"), "sha256": item.get("sha256")}
        for item in receipt.get("members", [])
        if isinstance(item, dict)
    ]
    if (
        receipt.get("schema") != "atlas.portable-authenticode-verification/1"
        or receipt.get("status") != "pass"
        or subject.get("source") != source
        or subject.get("manifest_sha256") != hashlib.sha256(canonical_json(manifest)).hexdigest()
        or subject.get("member_set_digest") != manifest["summary"]["member_set_digest"]
        or subject.get("executable_member_count") != len(expected_pe)
        or observed_pe != expected_pe
    ):
        raise PortableReleaseError("independent Authenticode receipt differs from signed bundle")
    return receipt


def package_signed(
    bundle: str | Path,
    receipt_path: str | Path,
    pre_sign_manifest_path: str | Path,
    pre_sign_toolchain_path: str | Path,
    output: str | Path,
) -> dict:
    before = source_identity(ROOT)
    bundle = Path(bundle).resolve(strict=True)
    if bundle == ROOT or ROOT in bundle.parents:
        raise PortableReleaseError("signed bundle staging must be outside the source repository")
    receipt_file = Path(receipt_path).resolve(strict=True)
    pre_sign_file = Path(pre_sign_manifest_path).resolve(strict=True)
    pre_sign_toolchain_file = Path(pre_sign_toolchain_path).resolve(strict=True)
    if any(
        bundle in path.parents
        for path in (receipt_file, pre_sign_file, pre_sign_toolchain_file)
    ):
        raise PortableReleaseError("signing receipts/manifests must remain outside the bundle")
    signing = json.loads(receipt_file.read_text(encoding="utf-8", errors="strict"))
    pre_sign_raw = pre_sign_file.read_bytes()
    pre_sign_manifest = json.loads(pre_sign_raw.decode("utf-8", errors="strict"))
    if canonical_json(pre_sign_manifest) != pre_sign_raw:
        raise PortableReleaseError("pre-sign manifest is not canonical JSON")
    pre_sign_source, prior_members = validate_member_manifest(pre_sign_manifest)
    final_members = collect_members(bundle)
    if (
        pre_sign_source != before
        or [item.get("path") for item in prior_members] != [item["path"] for item in final_members]
    ):
        raise PortableReleaseError("pre-sign manifest source/member denominator differs")
    for prior, final in zip(prior_members, final_members):
        if prior.get("executable") is True:
            for key in (
                "path",
                "role",
                "pe_machine",
                "executable",
            ):
                if prior.get(key) != final[key]:
                    raise PortableReleaseError("signing changed a PE identity/classification field")
            if set(prior.get("authenticode_content_sha256_variants") or []).isdisjoint(
                final.get("authenticode_content_sha256_variants") or []
            ):
                raise PortableReleaseError("signing changed executable content outside Authenticode fields")
        elif prior != final:
            raise PortableReleaseError("signing changed a non-PE runtime member")
    pre_sign_subject = signing.get("pre_sign_subject", {})
    if (
        pre_sign_subject.get("source") != before
        or pre_sign_subject.get("manifest_sha256") != hashlib.sha256(pre_sign_raw).hexdigest()
        or pre_sign_subject.get("member_set_digest")
        != pre_sign_manifest.get("summary", {}).get("member_set_digest")
        or pre_sign_subject.get("executable_member_count")
        != sum(item.get("executable") is True for item in prior_members)
    ):
        raise PortableReleaseError("signing receipt is not bound to the exact pre-sign manifest")
    pre_sign_toolchain_raw = pre_sign_toolchain_file.read_bytes()
    pre_sign_toolchain = json.loads(pre_sign_toolchain_raw.decode("utf-8", errors="strict"))
    if canonical_json(pre_sign_toolchain) != pre_sign_toolchain_raw:
        raise PortableReleaseError("pre-sign toolchain receipt is not canonical JSON")
    verify_toolchain()
    if toolchain_receipt(ROOT) != pre_sign_toolchain:
        raise PortableReleaseError("packaging toolchain/Analysis differs from pre-sign build evidence")
    signing["pre_sign_manifest"] = pre_sign_manifest
    signing["independent_authenticode_verification"] = _independent_authenticode(bundle, before)
    qualification = qualify_atlas.qualify(ROOT, bundle)
    index = build_portable_release(
        ROOT,
        bundle,
        output,
        qualification,
        signing=signing,
        expected_toolchain=pre_sign_toolchain,
    )
    verification = verify_release_set(
        output,
        expected_source=before,
        expected_material_root=ROOT,
    )
    if source_identity(ROOT) != before:
        raise PortableReleaseError("post-signing qualification changed the exact source identity")
    if verification["status"] != "SELF_CONSISTENCY_PASS":
        raise PortableReleaseError("signed portable release-set verification did not pass")
    return {"index": index, "verification": verification}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True, help="already-signed Atlas directory")
    parser.add_argument("--signing-receipt", required=True)
    parser.add_argument("--pre-sign-manifest", required=True)
    parser.add_argument("--pre-sign-toolchain", required=True)
    parser.add_argument("--output", required=True, help="fresh release-set directory")
    parser.add_argument("--json-out", help="controller receipt outside the release-set directory")
    args = parser.parse_args(argv)
    try:
        if args.json_out:
            output = Path(args.output).resolve(strict=False)
            json_out = Path(args.json_out).resolve(strict=False)
            bundle = Path(args.bundle).resolve(strict=True)
            if (
                json_out == output
                or output in json_out.parents
                or json_out == ROOT
                or ROOT in json_out.parents
                or json_out == bundle
                or bundle in json_out.parents
            ):
                raise PortableReleaseError(
                    "controller receipt must be outside the release set, source, and bundle"
                )
        result = package_signed(
            args.bundle,
            args.signing_receipt,
            args.pre_sign_manifest,
            args.pre_sign_toolchain,
            args.output,
        )
    except (OSError, json.JSONDecodeError, PortableReleaseError, subprocess.SubprocessError) as exc:
        print(f"signed portable release REFUSED: {exc}", file=sys.stderr)
        return 1
    if args.json_out:
        Path(args.json_out).write_bytes(canonical_json(result))
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
