"""External-key Ed25519 signing and verification hooks.

There is intentionally no key-generation, rotation, recovery-copy, secret
storage, network, or key-discovery function in this module.  The owner supplies
an existing key path and controls its custody outside the repository.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path, PurePosixPath
from typing import Any

from .model import ReleaseInputError, canonical_json, safe_input, safe_relative, sha256_bytes


class SigningUnavailable(RuntimeError):
    """The optional standards implementation is unavailable."""


def _crypto() -> tuple[Any, Any, Any]:
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
    except ImportError as exc:  # pragma: no cover - depends on the owner environment
        raise SigningUnavailable(
            "Ed25519 signing requires the optional 'cryptography' package; no fallback algorithm is permitted"
        ) from exc
    return serialization, Ed25519PrivateKey, Ed25519PublicKey


def _regular_bytes(path: Path, label: str) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ReleaseInputError(f"{label} must be an existing regular non-symlink file")
    before = path.stat(follow_symlinks=False)
    value = path.read_bytes()
    after = path.stat(follow_symlinks=False)
    if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
        raise ReleaseInputError(f"{label} changed while read")
    return value


def _load_private(value: bytes, password: bytes | None) -> Any:
    serialization, Ed25519PrivateKey, _ = _crypto()
    loaders = (serialization.load_pem_private_key, serialization.load_ssh_private_key)
    errors: list[str] = []
    for loader in loaders:
        try:
            key = loader(value, password=password)
            if not isinstance(key, Ed25519PrivateKey):
                raise ReleaseInputError("owner private key is not Ed25519")
            return key
        except (TypeError, ValueError) as exc:
            errors.append(type(exc).__name__)
    raise ReleaseInputError(f"could not load owner Ed25519 private key ({'/'.join(errors)})")


def _load_public(value: bytes) -> Any:
    serialization, _, Ed25519PublicKey = _crypto()
    loaders = (serialization.load_pem_public_key, serialization.load_ssh_public_key)
    errors: list[str] = []
    for loader in loaders:
        try:
            key = loader(value)
            if not isinstance(key, Ed25519PublicKey):
                raise ReleaseInputError("owner public key is not Ed25519")
            return key
        except (TypeError, ValueError) as exc:
            errors.append(type(exc).__name__)
    raise ReleaseInputError(f"could not load owner Ed25519 public key ({'/'.join(errors)})")


def verify_artifact_family(manifest_path: Path) -> dict[str, Any]:
    """Verify every artifact receipt in a canonical release manifest offline."""

    absolute = manifest_path.resolve(strict=True)
    raw = _regular_bytes(absolute, "release manifest")
    try:
        manifest = json.loads(raw.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReleaseInputError("release manifest is invalid UTF-8 JSON") from exc
    if not isinstance(manifest, dict) or manifest.get("schema_version") != "1.0.0":
        raise ReleaseInputError("release manifest schema is unsupported")
    if raw != canonical_json(manifest):
        raise ReleaseInputError("release manifest is not canonical JSON")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise ReleaseInputError("release manifest contains no artifact inventory")
    seen: set[str] = set()
    for item in artifacts:
        if not isinstance(item, dict):
            raise ReleaseInputError("release manifest artifact is not an object")
        relative = safe_relative(str(item.get("path", "")))
        if relative in seen:
            raise ReleaseInputError(f"duplicate artifact receipt: {relative}")
        seen.add(relative)
        value = _regular_bytes(safe_input(absolute.parent, relative), f"release artifact {relative}")
        if len(value) != item.get("bytes") or sha256_bytes(value) != item.get("sha256"):
            raise ReleaseInputError(f"release artifact receipt mismatch: {relative}")
    inventory_receipts = [item for item in artifacts if item.get("path") == "artifact-inventory.json"]
    if len(inventory_receipts) != 1:
        raise ReleaseInputError("release manifest must bind exactly one artifact-inventory.json")
    inventory_raw = _regular_bytes(
        safe_input(absolute.parent, "artifact-inventory.json"),
        "artifact inventory",
    )
    try:
        inventory = json.loads(inventory_raw.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReleaseInputError("artifact inventory is invalid UTF-8 JSON") from exc
    if not isinstance(inventory, dict) or inventory.get("schema_version") != "1.0.0":
        raise ReleaseInputError("artifact inventory schema is unsupported")
    if inventory_raw != canonical_json(inventory):
        raise ReleaseInputError("artifact inventory is not canonical JSON")
    binding = manifest.get("source_binding", {})
    if (
        inventory.get("source_commit") != binding.get("source_commit")
        or inventory.get("source_tree_digest") != binding.get("source_tree_digest")
        or inventory.get("status") != manifest.get("release_status")
    ):
        raise ReleaseInputError("artifact inventory source/status binding differs from release manifest")
    intended_inventory = sorted(
        (item for item in artifacts if item.get("path") != "artifact-inventory.json"),
        key=lambda item: item["path"],
    )
    if inventory.get("artifacts") != intended_inventory:
        raise ReleaseInputError("artifact inventory receipts differ from release manifest intent")
    expected_exclusions = ["artifact-inventory.json", "release-manifest.json", "release-manifest.sig.json"]
    if inventory.get("self_exclusions") != expected_exclusions:
        raise ReleaseInputError("artifact inventory self-exclusions are malformed")

    signing = manifest.get("signing")
    if not isinstance(signing, dict):
        raise ReleaseInputError("release manifest signing declaration is missing")
    signature_name = safe_relative(str(signing.get("signature_envelope", "")))
    if PurePosixPath(signature_name).parent != PurePosixPath("."):
        raise ReleaseInputError("signature envelope must be a sibling of the release manifest")
    allowed = seen | {absolute.name, signature_name}
    actual = {
        path.relative_to(absolute.parent).as_posix()
        for path in absolute.parent.rglob("*")
        if path.is_file()
    }
    undeclared = sorted(actual - allowed)
    if undeclared:
        raise ReleaseInputError(f"release family contains undeclared sibling files: {undeclared}")
    missing = sorted((seen | {absolute.name}) - actual)
    if missing:
        raise ReleaseInputError(f"release family is missing declared files: {missing}")
    return {
        "artifacts_verified": len(artifacts),
        "source_commit": manifest.get("source_binding", {}).get("source_commit"),
        "source_tree_digest": manifest.get("source_binding", {}).get("source_tree_digest"),
        "release_status": manifest.get("release_status"),
    }


def sign_manifest(
    manifest_path: Path,
    private_key_path: Path,
    signature_path: Path,
    *,
    password: bytes | None = None,
) -> dict[str, Any]:
    """Sign exact manifest bytes with an existing external Ed25519 key."""

    family = verify_artifact_family(manifest_path)
    manifest = _regular_bytes(manifest_path.resolve(strict=True), "release manifest")
    private_value = _regular_bytes(private_key_path.resolve(strict=True), "owner private key")
    key = _load_private(private_value, password)
    serialization, _, _ = _crypto()
    public_raw = key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    signature = key.sign(manifest)
    envelope = {
        "schema_version": "1.0.0",
        "algorithm": "Ed25519",
        "status": "signed",
        "target": manifest_path.name,
        "target_sha256": sha256_bytes(manifest),
        "public_key_fingerprint": f"sha256:{sha256_bytes(public_raw)}",
        "public_key_raw_base64": base64.b64encode(public_raw).decode("ascii"),
        "signature_base64": base64.b64encode(signature).decode("ascii"),
        "trust_note": "Verify the fingerprint against the separately trusted owner public key.",
        "artifacts_verified_before_signing": family["artifacts_verified"],
    }
    target = signature_path.resolve(strict=False)
    declared_signature = json.loads(manifest.decode("utf-8", errors="strict"))["signing"]["signature_envelope"]
    if target.parent != manifest_path.resolve(strict=True).parent or target.name != declared_signature:
        raise ReleaseInputError("signature output must be the manifest-declared sibling envelope")
    if target.exists() or target.is_symlink():
        raise ReleaseInputError("signature output already exists")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(canonical_json(envelope))
    return envelope


def verify_manifest(manifest_path: Path, signature_path: Path, public_key_path: Path) -> dict[str, Any]:
    """Verify the exact manifest and independently supplied owner public key."""

    manifest = _regular_bytes(manifest_path.resolve(strict=True), "release manifest")
    signature_value = _regular_bytes(signature_path.resolve(strict=True), "signature envelope")
    public_value = _regular_bytes(public_key_path.resolve(strict=True), "owner public key")
    try:
        envelope = json.loads(signature_value.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReleaseInputError("signature envelope is invalid UTF-8 JSON") from exc
    if (
        not isinstance(envelope, dict)
        or envelope.get("schema_version") != "1.0.0"
        or envelope.get("algorithm") != "Ed25519"
        or envelope.get("status") != "signed"
    ):
        raise ReleaseInputError("signature envelope is not Ed25519")
    if envelope.get("target") != manifest_path.name:
        raise ReleaseInputError("signature envelope target does not name this manifest")
    if envelope.get("target_sha256") != sha256_bytes(manifest):
        raise ReleaseInputError("manifest digest does not match signature envelope")
    key = _load_public(public_value)
    serialization, _, _ = _crypto()
    public_raw = key.public_bytes(encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw)
    fingerprint = f"sha256:{sha256_bytes(public_raw)}"
    if envelope.get("public_key_fingerprint") != fingerprint:
        raise ReleaseInputError("trusted public key fingerprint does not match signature envelope")
    try:
        embedded_public = base64.b64decode(str(envelope.get("public_key_raw_base64", "")), validate=True)
        if embedded_public != public_raw:
            raise ReleaseInputError("trusted public key does not match embedded signature key")
        signature = base64.b64decode(str(envelope.get("signature_base64", "")), validate=True)
        key.verify(signature, manifest)
    except Exception as exc:
        raise ReleaseInputError("Ed25519 signature verification failed") from exc
    family = verify_artifact_family(manifest_path)
    return {
        "verified": True,
        "algorithm": "Ed25519",
        "target_sha256": sha256_bytes(manifest),
        "public_key_fingerprint": fingerprint,
        "artifacts_verified": family["artifacts_verified"],
        "release_status": family["release_status"],
        "trust_note": "Cryptographic integrity verified; approval, correctness, and publication authority remain separate gates.",
    }
