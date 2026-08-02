"""Integrity and provenance helpers for the shipped offline registry packs.

The OUI and port registries are security-relevant inputs: their absence or silent
truncation changes assessment conclusions. Byte integrity and upstream source
authority are separate claims. Callers receive the integrity-verified UTF-8
payload or a loud ``PackIntegrityError``; loaders then apply their own explicit
provenance allow-list before describing the source as authoritative.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import math
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Collection, Mapping

MANIFEST_NAME = "registry_manifest.json"
TRANSACTION_MARKER_NAME = ".registry-publication.pending"
MANIFEST_SCHEMA_VERSION = 1
MAX_COMPRESSED_BYTES = 64 * 1024 * 1024
MAX_DECOMPRESSED_BYTES = 256 * 1024 * 1024
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
MAX_RETAINED_SOURCE_BYTES = 64 * 1024 * 1024
SOURCE_MAX_AGE_DAYS = 180
SOURCE_MAX_FUTURE_SKEW_SECONDS = 300
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SOURCE_INVENTORY_RELATIVE_PATH = "reference-data/official-sources/manifest.json"

_IEEE_CSV_HEADER = (
    "Registry",
    "Assignment",
    "Organization Name",
    "Organization Address",
)
_IANA_SERVICE_CSV_HEADER = (
    "Service Name",
    "Port Number",
    "Transport Protocol",
    "Description",
    "Assignee",
    "Contact",
    "Registration Date",
    "Modification Date",
    "Reference",
    "Service Code",
    "Unauthorized Use Reported",
    "Assignment Notes",
)

# These immutable contracts are the review anchor that a mutable JSON inventory
# cannot provide by itself. Updating an official snapshot therefore requires an
# explicit code review of its retrieval time, byte count, record count, and
# digest; an arbitrary one-row file plus a matching self-written inventory can
# never acquire authority.
_PRIMARY_SOURCE_CONTRACTS: dict[str, dict[str, Any]] = {
    "ieee-ma-l": {
        "url": "https://standards-oui.ieee.org/oui/oui.csv",
        "path": "reference-data/official-sources/ieee/oui.csv",
        "sha256": "0c1a4c437089029dbb08ff16f4a2960238611ba0587e912e5f4ae2e754ceb442",
        "bytes": 3_805_373,
        "record_count": 39_859,
        "retrieved_at": "2026-07-30T12:47:53Z",
        "expected_header": _IEEE_CSV_HEADER,
    },
    "ieee-ma-m": {
        "url": "https://standards-oui.ieee.org/oui28/mam.csv",
        "path": "reference-data/official-sources/ieee/mam.csv",
        "sha256": "ae5a9c2a4b44d7694a1071b905b1a28dc8fec5dd6cb7c0575eba8cee63efedba",
        "bytes": 742_311,
        "record_count": 6_516,
        "retrieved_at": "2026-07-30T12:47:53Z",
        "expected_header": _IEEE_CSV_HEADER,
    },
    "ieee-ma-s": {
        "url": "https://standards-oui.ieee.org/oui36/oui36.csv",
        "path": "reference-data/official-sources/ieee/oui36.csv",
        "sha256": "a209d197af77cf82235af104d785f24309a357e783955b21fe31089e26120e5d",
        "bytes": 659_624,
        "record_count": 7_114,
        "retrieved_at": "2026-07-30T12:47:53Z",
        "expected_header": _IEEE_CSV_HEADER,
    },
    "iana-service-names-port-numbers": {
        "url": (
            "https://www.iana.org/assignments/service-names-port-numbers/"
            "service-names-port-numbers.csv"
        ),
        "path": (
            "reference-data/official-sources/iana/"
            "service-names-port-numbers.csv"
        ),
        "sha256": "466e31f9db1eba0d193b86a8c94e0c7d9027678cf0c2d7280b726ab1b0eeee4a",
        "bytes": 1_156_064,
        "record_count": 14_529,
        "retrieved_at": "2026-07-30T12:47:53Z",
        "expected_header": _IANA_SERVICE_CSV_HEADER,
    },
}
_AUTHORITATIVE_STATE_SOURCE_IDS: dict[str, tuple[str, ...]] = {
    "generated-from-retained-ieee-primary-sources": (
        "ieee-ma-l",
        "ieee-ma-m",
        "ieee-ma-s",
    ),
    "generated-from-retained-iana-primary-source": (
        "iana-service-names-port-numbers",
    ),
}
_AUTHORITATIVE_STATE_GENERATORS = {
    "generated-from-retained-ieee-primary-sources": (
        "cisco_toolkit.gen_oui_registry"
    ),
    "generated-from-retained-iana-primary-source": (
        "cisco_toolkit.data.gen_port_registry"
    ),
}
_KNOWN_SOURCE_AUTHORITATIVE_STATES = frozenset(
    _AUTHORITATIVE_STATE_SOURCE_IDS
)
#: PAYLOAD (decompressed) digests of the reviewed deterministic builds. The compressed pins below
#: bind the exact shipped artifact; these bind the CONTENT. Both are code-review anchors, but they
#: answer different questions and fail differently: deflate is not canonical across zlib builds, so
#: a byte-for-byte-faithful REBUILD of the same reviewed content on another platform produces
#: different compressed bytes with an identical payload — proven on CI 2026-08-02, where every
#: ubuntu leg refused a rebuild whose gzip CRC32/ISIZE trailers matched the shipped pack ("pack
#: digest ... is not the code-pinned deterministic build"). Pinning ONLY compressed bytes meant
#: pack regeneration was blessable on exactly one zlib build, ever. The manifest's
#: `decompressed_sha256` is verified against the actual decompressed bytes by `verified_text`
#: (never trusted bare), so accepting it against these pins is sound: provenance is only ever
#: consumed after integrity.
_TRUSTED_PAYLOAD_SHA256_BY_STATE = {
    "generated-from-retained-ieee-primary-sources": (
        "5bae084489f21916c573d7159907ab9c4543b0f6bd786a7a40c7abe2655cca19"
    ),
    "generated-from-retained-iana-primary-source": (
        "b45b87bcdf9a63363163fd8c1d002bea03a0ca1e557bea01c9c88bceeb1f9c68"
    ),
}
_TRUSTED_PACK_SHA256_BY_STATE = {
    "generated-from-retained-ieee-primary-sources": (
        "2120d5ca8a07cd320d480c6b5bcb5cd810c877cb70a5c949e2d635891e48a51a"
    ),
    # Updated whenever the deterministic generator or its reviewed overlay
    # changes. This independently binds the packaged output to reviewed code.
    "generated-from-retained-iana-primary-source": (
        "3fcfa1c38e5cb7b7acf6a740f75214a3c8bfa000cb7df422593682045dea8519"
    ),
}


#: Which provenance state each packaged registry is ALLOWED to declare, keyed by its filename.
#:
#: Without this the trusted digest is selected by the pack's own SELF-DECLARED `provenance_status`,
#: and nothing binds `oui_registry.tsv.gz` to the IEEE state or the filename to a digest. Measured:
#: exchanging the two files' contents AND their manifest entries verbatim yields
#: `verified: true` for BOTH — the packs are interchangeable and the release proof certifies the
#: swap. The runtime loaders never had this hole: `ouidb` and `portdb` each pass a single-element
#: `_AUTHORITATIVE_PROVENANCE_STATES`, so they would reject it. The instrument that gates the
#: RELEASE was the loose one, which is the wrong way round.
#:
#: An unrecognised pack name falls back to the union rather than hard-failing, so a future pack is
#: not blocked by an unrelated table — but the two real packs are now pinned by name.
_EXPECTED_STATE_BY_PACK = {
    "oui_registry.tsv.gz": "generated-from-retained-ieee-primary-sources",
    "port_registry.tsv.gz": "generated-from-retained-iana-primary-source",
}


class PackIntegrityError(RuntimeError):
    """The registry pack cannot be trusted as an authoritative input."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _strict_json_loads(text: str, *, label: str) -> Any:
    def reject_duplicates(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise PackIntegrityError(f"{label} contains duplicate key {key!r}")
            result[key] = value
        return result

    try:
        return json.loads(text, object_pairs_hook=reject_duplicates)
    except json.JSONDecodeError as exc:
        raise PackIntegrityError(f"{label} is invalid JSON: {exc}") from exc


def _decompress_bounded(compressed: bytes, *, label: str) -> bytes:
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(compressed), mode="rb") as stream:
            decompressed = stream.read(MAX_DECOMPRESSED_BYTES + 1)
    except (OSError, EOFError) as exc:
        raise PackIntegrityError(f"cannot fully decompress {label}: {exc}") from exc
    if len(decompressed) > MAX_DECOMPRESSED_BYTES:
        raise PackIntegrityError(
            f"decompressed {label} exceeds the {MAX_DECOMPRESSED_BYTES}-byte safety limit"
        )
    return decompressed


def manifest_path_for(pack_path: str) -> str:
    return os.path.join(os.path.dirname(os.path.abspath(pack_path)), MANIFEST_NAME)


def transaction_marker_path_for(pack_path: str) -> str:
    return os.path.join(
        os.path.dirname(os.path.abspath(pack_path)), TRANSACTION_MARKER_NAME
    )


def paths_refer_to_same_file(left: str, right: str) -> bool:
    """Return whether two path spellings identify the same destination.

    ``abspath`` alone is not a sufficient safety boundary on Windows: case
    aliases, junction/symlink parents, and hard links can all spell the shipped
    registry differently.  Resolve lexical and filesystem identity, while
    remaining useful when one of the candidate paths does not exist yet.
    """

    def canonical(path: str) -> str:
        return os.path.normcase(os.path.realpath(os.path.abspath(os.fspath(path))))

    if canonical(left) == canonical(right):
        return True
    try:
        return os.path.samefile(left, right)
    except (OSError, ValueError):
        return False


def _load_manifest(path: str) -> dict[str, Any]:
    try:
        if os.path.getsize(path) > MAX_MANIFEST_BYTES:
            raise PackIntegrityError(
                f"registry manifest exceeds the {MAX_MANIFEST_BYTES}-byte safety limit"
            )
        with open(path, encoding="utf-8") as handle:
            manifest = _strict_json_loads(
                handle.read(),
                label="registry manifest",
            )
    except PackIntegrityError:
        raise
    except (OSError, UnicodeDecodeError) as exc:
        raise PackIntegrityError(f"registry manifest unavailable or invalid: {exc}") from exc
    if not isinstance(manifest, dict) or manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise PackIntegrityError("registry manifest schema is unsupported")
    if not isinstance(manifest.get("packs"), dict):
        raise PackIntegrityError("registry manifest has no pack inventory")
    return manifest


def _parse_utc_timestamp(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PackIntegrityError(f"{label} is absent")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PackIntegrityError(f"{label} is invalid") from exc
    if parsed.tzinfo is None:
        raise PackIntegrityError(f"{label} has no timezone")
    return value


def source_freshness(
    value: object,
    *,
    now: datetime | None = None,
    max_age_days: int = SOURCE_MAX_AGE_DAYS,
    max_future_skew_seconds: int = SOURCE_MAX_FUTURE_SKEW_SECONDS,
) -> dict[str, Any]:
    """Evaluate one source timestamp against the explicit registry policy.

    Freshness is deliberately separate from byte integrity. A snapshot can be
    byte-perfect and still be too old (or implausibly future-dated) to support
    an authoritative runtime claim.
    """

    timestamp = _parse_utc_timestamp(value, label="source retrieval timestamp")
    parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("freshness reference time must include a timezone")
    if type(max_age_days) is not int or max_age_days <= 0:
        raise ValueError("source freshness max age must be a positive integer")
    if type(max_future_skew_seconds) is not int or max_future_skew_seconds < 0:
        raise ValueError("source future-skew tolerance must be a non-negative integer")

    age_seconds = (current.astimezone(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds()
    future_dated = age_seconds < -max_future_skew_seconds
    stale = age_seconds > max_age_days * 86_400
    fresh = not future_dated and not stale
    if future_dated:
        status = "future-dated"
    elif stale:
        status = "stale"
    else:
        status = "fresh"
    return {
        "source_retrieved_at": timestamp,
        "source_age_days": round(age_seconds / 86_400, 6),
        "source_max_age_days": max_age_days,
        "source_max_future_skew_seconds": max_future_skew_seconds,
        "source_future_dated": future_dated,
        "source_stale": stale,
        "source_fresh": fresh,
        "freshness_status": status,
    }


def _repository_root(repository_root: str | os.PathLike[str] | None) -> Path:
    if repository_root is None:
        return Path(__file__).resolve().parent.parent
    return Path(repository_root).resolve()


def _load_source_inventory(
    *,
    repository_root: str | os.PathLike[str] | None = None,
    inventory_path: str | os.PathLike[str] | None = None,
) -> tuple[dict[str, Any], Path]:
    root = _repository_root(repository_root)
    path = (
        Path(inventory_path).resolve()
        if inventory_path is not None
        else root / PurePosixPath(SOURCE_INVENTORY_RELATIVE_PATH)
    )
    try:
        size = path.stat().st_size
        if size > MAX_MANIFEST_BYTES:
            raise PackIntegrityError(
                f"official-source inventory exceeds the {MAX_MANIFEST_BYTES}-byte safety limit"
            )
        raw = path.read_bytes()
        text = raw.decode("utf-8", "strict")
        inventory = _strict_json_loads(
            text,
            label="official-source inventory",
        )
    except PackIntegrityError:
        raise
    except (OSError, UnicodeDecodeError) as exc:
        raise PackIntegrityError(
            f"official-source inventory unavailable or invalid: {exc}"
        ) from exc
    if (
        not isinstance(inventory, dict)
        or inventory.get("schema_version") != 1
        or not isinstance(inventory.get("sources"), dict)
    ):
        raise PackIntegrityError("official-source inventory schema is unsupported")
    _parse_utc_timestamp(
        inventory.get("retrieved_at"),
        label="official-source retrieval timestamp",
    )
    return inventory, path


def load_retained_source(
    source_id: str,
    *,
    repository_root: str | os.PathLike[str] | None = None,
    inventory_path: str | os.PathLike[str] | None = None,
) -> tuple[bytes, str, dict[str, Any]]:
    """Load one hash-pinned primary-source CSV and return its manifest artifact.

    The exact bytes are bounded and hashed before strict UTF-8 decoding. The
    inventory cannot redirect a known source ID to another URL or repository
    path, and its CSV header and row count are part of the retained contract.
    """

    contract = _PRIMARY_SOURCE_CONTRACTS.get(source_id)
    if contract is None:
        raise PackIntegrityError(f"unknown retained primary source {source_id!r}")
    inventory, _ = _load_source_inventory(
        repository_root=repository_root,
        inventory_path=inventory_path,
    )
    record = inventory["sources"].get(source_id)
    if not isinstance(record, dict):
        raise PackIntegrityError(
            f"retained primary source {source_id!r} is absent from the inventory"
        )
    if record.get("url") != contract["url"] or record.get("path") != contract["path"]:
        raise PackIntegrityError(
            f"retained primary source {source_id!r} violates its URL/path contract"
        )
    if record.get("encoding") != "utf-8" or record.get("media_type") != "text/csv":
        raise PackIntegrityError(
            f"retained primary source {source_id!r} has an unsupported media contract"
        )
    expected_hash = record.get("sha256")
    expected_bytes = record.get("bytes")
    expected_rows = record.get("expected_rows")
    expected_header = record.get("expected_header")
    trusted_snapshot = {
        "sha256": contract["sha256"],
        "bytes": contract["bytes"],
        "expected_rows": contract["record_count"],
        "expected_header": list(contract["expected_header"]),
    }
    manifested_snapshot = {
        "sha256": expected_hash,
        "bytes": expected_bytes,
        "expected_rows": expected_rows,
        "expected_header": expected_header,
    }
    if manifested_snapshot != trusted_snapshot:
        raise PackIntegrityError(
            f"retained primary source {source_id!r} does not match the "
            "code-pinned trusted snapshot contract"
        )
    if inventory.get("retrieved_at") != contract["retrieved_at"]:
        raise PackIntegrityError(
            f"retained primary source {source_id!r} retrieval timestamp does "
            "not match the code-pinned trusted snapshot"
        )
    if not isinstance(expected_hash, str) or not _SHA256_RE.fullmatch(expected_hash):
        raise PackIntegrityError(
            f"retained primary source {source_id!r} has no valid SHA-256"
        )
    if (
        type(expected_bytes) is not int
        or expected_bytes <= 0
        or expected_bytes > MAX_RETAINED_SOURCE_BYTES
    ):
        raise PackIntegrityError(
            f"retained primary source {source_id!r} has an invalid byte-size contract"
        )
    if type(expected_rows) is not int or expected_rows <= 0:
        raise PackIntegrityError(
            f"retained primary source {source_id!r} has an invalid row-count contract"
        )
    if (
        not isinstance(expected_header, list)
        or not expected_header
        or any(not isinstance(value, str) or not value for value in expected_header)
    ):
        raise PackIntegrityError(
            f"retained primary source {source_id!r} has an invalid CSV-header contract"
        )

    root = _repository_root(repository_root)
    retained_path = root / PurePosixPath(contract["path"])
    try:
        actual_size = retained_path.stat().st_size
        if actual_size != expected_bytes:
            raise PackIntegrityError(
                f"retained primary source {source_id!r} byte-size mismatch"
            )
        raw = retained_path.read_bytes()
    except PackIntegrityError:
        raise
    except OSError as exc:
        raise PackIntegrityError(
            f"retained primary source {source_id!r} is unavailable: {exc}"
        ) from exc
    if len(raw) != expected_bytes or _sha256(raw) != expected_hash:
        raise PackIntegrityError(
            f"retained primary source {source_id!r} SHA-256 mismatch"
        )
    try:
        text = raw.decode("utf-8", "strict")
        reader = csv.reader(io.StringIO(text, newline=""), strict=True)
        header = next(reader, None)
        row_count = sum(1 for row in reader if row and any(cell for cell in row))
    except (UnicodeDecodeError, csv.Error) as exc:
        raise PackIntegrityError(
            f"retained primary source {source_id!r} is not strict UTF-8 CSV: {exc}"
        ) from exc
    if header != expected_header:
        raise PackIntegrityError(
            f"retained primary source {source_id!r} CSV header mismatch"
        )
    if row_count != expected_rows:
        raise PackIntegrityError(
            f"retained primary source {source_id!r} row-count mismatch"
        )

    artifact = {
        "id": source_id,
        "name": record.get("name"),
        "url": contract["url"],
        "retained_path": contract["path"],
        "retrieved_at": inventory["retrieved_at"],
        "sha256": expected_hash,
        "bytes": expected_bytes,
        "hash_scope": "raw-source-bytes",
        "media_type": "text/csv",
        "encoding": "utf-8",
        "record_count": expected_rows,
    }
    if not isinstance(artifact["name"], str) or not artifact["name"].strip():
        raise PackIntegrityError(
            f"retained primary source {source_id!r} has no display name"
        )
    return raw, text, artifact


def _build_provenance_authority(
    entry: Mapping[str, Any],
    *,
    allowed_provenance_states: Collection[str],
    now: datetime | None = None,
) -> tuple[bool, str, dict[str, Any]]:
    """Verify the packaged build proof without pretending raw sources exist."""

    state = entry.get("provenance_status")
    if not isinstance(state, str) or state not in set(allowed_provenance_states):
        return False, f"provenance state {state!r} is not explicitly allowed", {}
    expected_ids = _AUTHORITATIVE_STATE_SOURCE_IDS.get(state)
    if expected_ids is None:
        return (
            False,
            f"provenance state {state!r} is not a retained-primary-source state",
            {},
        )
    expected_generator = _AUTHORITATIVE_STATE_GENERATORS[state]
    if entry.get("generator") != expected_generator:
        return (
            False,
            f"generator for provenance state {state!r} is unexpected",
            {},
        )
    trusted_pack_hash = _TRUSTED_PACK_SHA256_BY_STATE[state]
    trusted_payload_hash = _TRUSTED_PAYLOAD_SHA256_BY_STATE[state]
    # Either anchor establishes the reviewed build: the compressed pin is exact for the SHIPPED
    # artifact; the payload pin admits a faithful rebuild whose deflate framing differs (deflate is
    # not canonical across zlib implementations — see _TRUSTED_PAYLOAD_SHA256_BY_STATE). A pack
    # matching NEITHER is refused exactly as before.
    if (
        entry.get("compressed_sha256") != trusted_pack_hash
        and entry.get("decompressed_sha256") != trusted_payload_hash
    ):
        return (
            False,
            f"pack digest for provenance state {state!r} is not the "
            "code-pinned deterministic build (neither the shipped compressed bytes nor the "
            "reviewed payload)",
            {},
        )
    try:
        generated_at = _parse_utc_timestamp(
            entry.get("generated_at"),
            label="registry generation timestamp",
        )
        freshness = source_freshness(generated_at, now=now)
    except (PackIntegrityError, ValueError) as exc:
        return False, str(exc), {}
    source = entry.get("source")
    if not isinstance(source, Mapping):
        return False, "source provenance is absent", freshness
    if not str(source.get("name") or "").strip():
        return False, "source name is absent", freshness
    if source.get("inventory") != SOURCE_INVENTORY_RELATIVE_PATH:
        return (
            False,
            "official-source inventory path is absent or unexpected",
            freshness,
        )
    if source.get("inventory_schema_version") != 1:
        return False, "official-source inventory schema is unsupported", freshness
    artifacts = source.get("artifacts")
    if not isinstance(artifacts, list):
        return False, "retained source artifact inventory is absent", freshness
    artifact_ids = tuple(
        artifact.get("id") if isinstance(artifact, Mapping) else None
        for artifact in artifacts
    )
    if artifact_ids != expected_ids:
        return (
            False,
            "retained source artifact membership/order is unexpected",
            freshness,
        )
    artifact_timestamps = set()
    for artifact in artifacts:
        assert isinstance(artifact, Mapping)
        source_id = artifact["id"]
        contract = _PRIMARY_SOURCE_CONTRACTS[source_id]
        if not str(artifact.get("name") or "").strip():
            return False, f"retained source {source_id!r} name is absent", freshness
        if artifact.get("url") != contract["url"]:
            return False, f"retained source {source_id!r} URL is unexpected", freshness
        if artifact.get("retained_path") != contract["path"]:
            return False, f"retained source {source_id!r} path is unexpected", freshness
        expected_artifact = {
            "sha256": contract["sha256"],
            "bytes": contract["bytes"],
            "record_count": contract["record_count"],
            "retrieved_at": contract["retrieved_at"],
        }
        manifested_artifact = {
            field: artifact.get(field) for field in expected_artifact
        }
        if manifested_artifact != expected_artifact:
            return (
                False,
                f"retained source {source_id!r} does not match the "
                "code-pinned trusted snapshot",
                freshness,
            )
        if artifact.get("hash_scope") != "raw-source-bytes":
            return (
                False,
                f"retained source {source_id!r} hash scope is invalid",
                freshness,
            )
        if (
            artifact.get("encoding") != "utf-8"
            or artifact.get("media_type") != "text/csv"
        ):
            return (
                False,
                f"retained source {source_id!r} media contract is invalid",
                freshness,
            )
        try:
            artifact_timestamps.add(
                _parse_utc_timestamp(
                    artifact.get("retrieved_at"),
                    label=f"retained source {source_id!r} retrieval timestamp",
                )
            )
        except PackIntegrityError as exc:
            return False, str(exc), freshness
    if artifact_timestamps != {generated_at}:
        return (
            False,
            "retained source batch timestamp does not match generation timestamp",
            freshness,
        )
    return True, "", freshness


def official_sources_available(
    *,
    repository_root: str | os.PathLike[str] | None = None,
    inventory_path: str | os.PathLike[str] | None = None,
) -> bool:
    """Is the retained official-source inventory PRESENT at this install root at all?

    A structured fact, so consumers can distinguish CANNOT-CHECK-HERE from CHECKED-AND-FAILED
    without sniffing error prose. The retained sources ship in the repository and the sdist ONLY
    (handoff 5.5) -- a wheel or frozen bundle structurally cannot carry them, so in those install
    forms every source-chain verification fails with "[Errno 2] No such file or directory", which
    is the ABSENCE of the ability to check, not a failed check. Before this field existed the two
    states were the same `PackIntegrityError` differing only in wording, and the Atlas self-test's
    first-ever run from an installed wheel (CI, 2026-08-02) failed oui-kb and port-kb on exactly
    that conflation -- a failure the port-authority refuter had predicted (its F7) and could not
    verify without a real frozen install.

    Deliberately a bare existence probe, not a parse: a PRESENT-but-corrupt inventory must keep
    reporting available=True so its verification failure stays a real failure.
    """
    root = _repository_root(repository_root)
    path = (
        Path(inventory_path).resolve()
        if inventory_path is not None
        else root / PurePosixPath(SOURCE_INVENTORY_RELATIVE_PATH)
    )
    try:
        return path.is_file()
    except OSError:
        return False


def source_authority_details(
    entry: Mapping[str, Any],
    *,
    allowed_provenance_states: Collection[str],
    repository_root: str | os.PathLike[str] | None = None,
    inventory_path: str | os.PathLike[str] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return build, retained-byte, freshness, and authority decisions.

    A wheel can verify its code-pinned deterministic pack and report
    ``build_provenance_verified``. It cannot report ``source_authoritative``
    unless the separately retained official bytes are present and exactly
    verified at runtime.
    """

    build_ok, build_reason, freshness = _build_provenance_authority(
        entry,
        allowed_provenance_states=allowed_provenance_states,
        now=now,
    )
    details: dict[str, Any] = {
        "build_provenance_verified": build_ok,
        "retained_source_bytes_verified": False,
        "source_authoritative": False,
        "authority_error": build_reason,
        # present on EVERY return path, so a consumer can always tell an install form that cannot
        # carry the retained sources apart from a real verification failure
        "official_sources_available": official_sources_available(
            repository_root=repository_root, inventory_path=inventory_path
        ),
        **freshness,
    }
    if not build_ok:
        return details

    source = entry["source"]
    verified_artifacts: list[dict[str, Any]] = []
    try:
        for manifested_artifact in source["artifacts"]:
            _, _, retained_artifact = load_retained_source(
                manifested_artifact["id"],
                repository_root=repository_root,
                inventory_path=inventory_path,
            )
            if manifested_artifact != retained_artifact:
                raise PackIntegrityError(
                    f"pack source artifact {manifested_artifact['id']!r} "
                    "does not match the retained inventory"
                )
            verified_artifacts.append(dict(retained_artifact))
    except PackIntegrityError as exc:
        details["authority_error"] = str(exc)
        return details

    details["retained_source_bytes_verified"] = True
    details["verified_artifacts"] = verified_artifacts
    if not details.get("source_fresh"):
        details["authority_error"] = (
            f"source snapshot is {details.get('freshness_status', 'not fresh')}"
        )
        return details
    details["source_authoritative"] = True
    details["authority_error"] = ""
    return details


def source_authority(
    entry: Mapping[str, Any],
    *,
    allowed_provenance_states: Collection[str],
    repository_root: str | os.PathLike[str] | None = None,
    inventory_path: str | os.PathLike[str] | None = None,
    now: datetime | None = None,
) -> tuple[bool, str]:
    """Evaluate source authority independently from pack-byte integrity."""

    details = source_authority_details(
        entry,
        allowed_provenance_states=allowed_provenance_states,
        repository_root=repository_root,
        inventory_path=inventory_path,
        now=now,
    )
    return bool(details["source_authoritative"]), str(details["authority_error"])


def pack_is_usable(health: Any) -> bool:
    """Is a registry pack intact AND is its OFFICIAL component source-proven?

    THE one predicate every consumer of a `registry_health()` dict must ask. It exists because
    each consumer previously re-implemented it and they did not agree:

      * `webapp/backend/summary.py` tested `source_authoritative is not True`
      * `COLLECT_PARSE_V3_23_0.py`'s workbook tested `not health.get("authoritative", True)`
      * `webapp/backend/serve.py` tested the scoped pair (correct)

    The port pack is DELIBERATELY mixed: official IANA assignment records plus clearly-labelled
    curated hints, so its whole-pack `source_authoritative` is honestly **false** and must stay
    false -- relabelling curated facts as official is the one thing the authority model forbids.
    The first two consumers read that honest false as total registry failure, so a pack whose
    bytes, schema and IANA source chain had all verified was reported broken on EVERY clean run.

    Scope precisely: this asks whether the pack can be RELIED ON, not whether every row in it is
    official. A caller wanting the latter must read the per-record `assignment_authoritative` /
    `semantics_authoritative` fields, which this deliberately does not collapse.

    Structural, not a name list: a pack that publishes `official_source_authoritative` is judged
    on that; one that does not (a wholly-official pack such as OUI or EoL) is judged on its
    whole-pack flag. No consumer needs to know which packs are mixed, so a future mixed pack is
    handled without editing anything here. Unknown/absent integrity is NOT usable -- missing
    integrity is blocking, never implicitly healthy.

    Freshness needs no separate term: `source_authority_details` only sets an authoritative flag
    when the retained source bytes verify AND satisfy the max-age / future-skew bounds.
    """
    if not isinstance(health, Mapping):
        return False
    if health.get("integrity_verified") is not True:
        return False
    # CANNOT-CHECK-HERE is not CHECKED-AND-FAILED. The retained official sources ship in the
    # repository and sdist only (handoff 5.5), so a wheel or frozen bundle structurally cannot
    # verify the source chain -- its first-ever self-test run (CI, 2026-08-02) failed on exactly
    # that. Where the inventory is genuinely ABSENT (`official_sources_available is False` -- a
    # REAL False from the current producer; an older health dict without the field keeps today's
    # strict behaviour), a byte-intact pack whose BUILD provenance verified is usable, and the
    # caller is expected to disclose the degraded form. A PRESENT inventory that fails to verify
    # stays a hard refusal.
    sources_absent = (
        health.get("official_sources_available") is False
        and health.get("build_provenance_verified") is True
    )
    official = health.get("official_source_authoritative")
    if official is not None:
        return official is True or sources_absent
    return health.get("source_authoritative") is True or sources_absent


def verify_retained_source_chain(
    pack_path: str,
    *,
    repository_root: str | os.PathLike[str] | None = None,
    inventory_path: str | os.PathLike[str] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Verify a generated pack back through its retained primary-source bytes.

    Wheels intentionally do not need the large raw CSVs at runtime. This
    repository/CI check is the complementary build-time proof that the
    manifest's source artifacts exactly equal the separately retained,
    hash-pinned official inputs.
    """

    _, entry = verified_text(pack_path)
    state = entry.get("provenance_status")
    # Bind the declared state to the pack's IDENTITY, not merely to the set of states that exist.
    # See _EXPECTED_STATE_BY_PACK: accepting the union let the two packs be exchanged and still
    # verify, because each one's manifest entry vouched for whichever state it happened to name.
    _expected = _EXPECTED_STATE_BY_PACK.get(os.path.basename(str(pack_path)))
    _allowed = frozenset({_expected}) if _expected else _KNOWN_SOURCE_AUTHORITATIVE_STATES
    if _expected and state != _expected:
        raise PackIntegrityError(
            f"pack {os.path.basename(str(pack_path))!r} declares provenance {state!r}, but that "
            f"filename is bound to {_expected!r} — the pack is not the registry it claims to be"
        )
    authority = source_authority_details(
        entry,
        allowed_provenance_states=_allowed,
        repository_root=repository_root,
        inventory_path=inventory_path,
        now=now,
    )
    if not authority["source_authoritative"]:
        raise PackIntegrityError(
            "pack source authority is invalid: "
            f"{authority.get('authority_error') or 'unknown authority failure'}"
        )
    verified_artifacts = authority.pop("verified_artifacts")
    authority.pop("authority_error", None)
    authority.pop("source_authoritative", None)
    return {
        "verified": True,
        "provenance_status": state,
        "pack_sha256": entry["compressed_sha256"],
        "artifact_count": len(verified_artifacts),
        "artifacts": verified_artifacts,
        **authority,
    }


def verified_text(pack_path: str) -> tuple[str, dict[str, Any]]:
    """Return integrity-verified UTF-8 text and its immutable manifest entry.

    This proves only the bytes named by the manifest.  It does *not* prove that
    the upstream source was retained or authoritative; loaders must separately
    call :func:`source_authority`.
    """

    marker_path = transaction_marker_path_for(pack_path)
    if os.path.exists(marker_path):
        raise PackIntegrityError(
            "registry publication transaction is incomplete; refusing a possibly split pack"
        )
    manifest_path = manifest_path_for(pack_path)
    manifest = _load_manifest(manifest_path)
    name = os.path.basename(pack_path)
    entry = manifest["packs"].get(name)
    if not isinstance(entry, dict):
        raise PackIntegrityError(f"{name!r} is absent from {MANIFEST_NAME}")

    expected_size = entry.get("compressed_bytes")
    if (
        type(expected_size) is not int
        or expected_size < 0
        or expected_size > MAX_COMPRESSED_BYTES
    ):
        raise PackIntegrityError(f"invalid compressed size contract for {name}: {expected_size!r}")
    try:
        actual_size = os.path.getsize(pack_path)
        if actual_size != expected_size:
            raise PackIntegrityError(
                f"compressed size mismatch for {name}: expected {expected_size}, got {actual_size}"
            )
        with open(pack_path, "rb") as handle:
            compressed = handle.read(MAX_COMPRESSED_BYTES + 1)
    except OSError as exc:
        raise PackIntegrityError(f"registry pack unavailable: {exc}") from exc
    if len(compressed) != expected_size:
        raise PackIntegrityError(
            f"compressed size mismatch for {name}: expected {expected_size}, got {len(compressed)}"
        )
    compressed_hash = _sha256(compressed)
    if compressed_hash != entry.get("compressed_sha256"):
        raise PackIntegrityError(f"compressed SHA-256 mismatch for {name}")

    try:
        decompressed = _decompress_bounded(compressed, label=name)
        text = decompressed.decode("utf-8", "strict")
    except (PackIntegrityError, UnicodeDecodeError) as exc:
        raise PackIntegrityError(f"cannot fully decode {name}: {exc}") from exc

    if _sha256(decompressed) != entry.get("decompressed_sha256"):
        raise PackIntegrityError(f"decompressed SHA-256 mismatch for {name}")
    row_count = sum(1 for line in text.splitlines() if line)
    if row_count != entry.get("row_count"):
        raise PackIntegrityError(
            f"row-count mismatch for {name}: expected {entry.get('row_count')}, got {row_count}"
        )
    return text, dict(entry)


def enforce_non_regression(
    candidate_counts: Mapping[str, int],
    *,
    baseline_pack_path: str,
    minimum_ratios: Mapping[str, float],
) -> dict[str, Any]:
    """Refuse a candidate that materially shrinks the current verified pack.

    Floors are computed from the current manifest/pack pair, never from a tiny
    hard-coded constant that a truncated upstream download could still exceed.
    """

    _, baseline = verified_text(baseline_pack_path)
    for field, ratio in minimum_ratios.items():
        old = baseline.get(field)
        new = candidate_counts.get(field)
        if type(old) is not int or old <= 0:
            raise PackIntegrityError(
                f"baseline {field} contract is absent or invalid for "
                f"{os.path.basename(baseline_pack_path)}"
            )
        if type(new) is not int or new < 0:
            raise PackIntegrityError(f"candidate {field} is absent or invalid: {new!r}")
        if not isinstance(ratio, (int, float)) or not 0 < float(ratio) <= 1:
            raise ValueError(f"minimum ratio for {field} must be in (0, 1]")
        minimum = math.ceil(old * float(ratio))
        if new < minimum:
            raise PackIntegrityError(
                f"candidate {field} {new} is below the non-regression floor "
                f"{minimum} ({float(ratio):.0%} of current verified {old})"
            )
    return baseline


def metadata_for_bytes(
    compressed: bytes,
    *,
    source: Mapping[str, Any],
    generator: str,
    provenance_status: str,
    generated_at: str | None = None,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a manifest entry for already-generated gzip bytes."""

    try:
        if len(compressed) > MAX_COMPRESSED_BYTES:
            raise PackIntegrityError("generated pack exceeds the compressed-byte safety limit")
        decompressed = _decompress_bounded(compressed, label="generated pack")
        text = decompressed.decode("utf-8", "strict")
    except (PackIntegrityError, UnicodeDecodeError) as exc:
        raise PackIntegrityError(f"generated pack cannot be fully decoded: {exc}") from exc
    timestamp = (
        generated_at
        if generated_at is not None
        else datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    )
    _parse_utc_timestamp(timestamp, label="generated-at timestamp")
    entry: dict[str, Any] = {
        "compressed_bytes": len(compressed),
        "compressed_sha256": _sha256(compressed),
        "decompressed_sha256": _sha256(decompressed),
        "row_count": sum(1 for line in text.splitlines() if line),
        "generated_at": timestamp,
        "generator": generator,
        "provenance_status": provenance_status,
        "source": dict(source),
    }
    build_ok, _, freshness = _build_provenance_authority(
        entry,
        allowed_provenance_states=_KNOWN_SOURCE_AUTHORITATIVE_STATES,
    )
    # A packaged manifest must not self-promote to source authority. It can
    # attest only that its bytes match a code-pinned deterministic build.
    # Runtime source authority additionally requires retained source bytes.
    entry["source_authoritative"] = False
    entry["build_provenance_verified"] = build_ok
    entry["runtime_source_verification_required"] = (
        provenance_status in _KNOWN_SOURCE_AUTHORITATIVE_STATES
    )
    for field in (
        "source_retrieved_at",
        "source_max_age_days",
        "source_max_future_skew_seconds",
        "source_future_dated",
        "source_stale",
        "source_fresh",
        "freshness_status",
    ):
        if field in freshness:
            entry[field] = freshness[field]
    if extra:
        reserved = set(entry)
        overlap = reserved.intersection(extra)
        if overlap:
            raise PackIntegrityError(
                f"extra registry metadata cannot replace protected field(s): {sorted(overlap)}"
            )
        entry.update(dict(extra))
    return entry


def _manifest_with_entry(pack_path: str, entry: Mapping[str, Any]) -> dict[str, Any]:
    manifest_path = manifest_path_for(pack_path)
    if os.path.exists(manifest_path):
        manifest = _load_manifest(manifest_path)
    else:
        manifest = {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "purpose": "Integrity and source-provenance contract for offline registry packs",
            "packs": {},
        }
    manifest["packs"][os.path.basename(pack_path)] = dict(entry)
    updated_at = entry.get("generated_at")
    if not isinstance(updated_at, str):
        updated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    manifest["updated_at"] = updated_at
    return manifest


def _manifest_bytes(pack_path: str, entry: Mapping[str, Any]) -> bytes:
    manifest = _manifest_with_entry(pack_path, entry)
    return (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _write_temp_bytes(destination: str, data: bytes) -> str:
    directory = os.path.dirname(os.path.abspath(destination)) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=f".{os.path.basename(destination)}.",
        suffix=".tmp",
        dir=directory,
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise
    return tmp_path


def _existing_bytes(path: str, *, maximum: int) -> tuple[bool, bytes]:
    if not os.path.exists(path):
        return False, b""
    size = os.path.getsize(path)
    if size > maximum:
        raise PackIntegrityError(f"existing {os.path.basename(path)} exceeds its safety limit")
    with open(path, "rb") as handle:
        data = handle.read(maximum + 1)
    if len(data) > maximum:
        raise PackIntegrityError(f"existing {os.path.basename(path)} exceeds its safety limit")
    return True, data


def _restore_snapshot(path: str, existed: bool, data: bytes) -> None:
    if existed:
        restore_tmp = _write_temp_bytes(path, data)
        try:
            os.replace(restore_tmp, path)
        finally:
            if os.path.exists(restore_tmp):
                os.unlink(restore_tmp)
    elif os.path.exists(path):
        os.unlink(path)


def publish_pack_and_manifest(
    pack_path: str,
    compressed: bytes,
    entry: Mapping[str, Any],
) -> None:
    """Publish a pack and its manifest together, rolling both back on failure.

    Filesystems do not offer a portable two-file atomic rename. This routine
    therefore prepares and fsyncs both complete replacements first, publishes
    a marker that makes concurrent/crash-interrupted reads fail closed,
    snapshots the old pair, and restores that pair if either replace fails.
    Readers get a self-consistent pair or a loud refusal, including during an
    injected manifest-publication failure.
    """

    pack_path = os.path.abspath(pack_path)
    manifest_path = manifest_path_for(pack_path)
    marker_path = transaction_marker_path_for(pack_path)
    if os.path.exists(marker_path):
        raise PackIntegrityError(
            "an unresolved registry publication transaction marker already exists"
        )
    if len(compressed) > MAX_COMPRESSED_BYTES:
        raise PackIntegrityError("generated pack exceeds the compressed-byte safety limit")
    if entry.get("compressed_bytes") != len(compressed):
        raise PackIntegrityError("generated pack size disagrees with its manifest entry")
    if entry.get("compressed_sha256") != _sha256(compressed):
        raise PackIntegrityError("generated pack hash disagrees with its manifest entry")

    manifest_data = _manifest_bytes(pack_path, entry)
    old_pack_exists, old_pack = _existing_bytes(pack_path, maximum=MAX_COMPRESSED_BYTES)
    old_manifest_exists, old_manifest = _existing_bytes(
        manifest_path, maximum=MAX_MANIFEST_BYTES
    )
    pack_tmp = _write_temp_bytes(pack_path, compressed)
    manifest_tmp = _write_temp_bytes(manifest_path, manifest_data)
    marker_tmp = _write_temp_bytes(
        marker_path,
        (
            json.dumps(
                {
                    "schema_version": 1,
                    "pack": os.path.basename(pack_path),
                    "candidate_sha256": entry["compressed_sha256"],
                },
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8"),
    )
    marker_active = False
    try:
        os.replace(marker_tmp, marker_path)
        marker_tmp = ""
        marker_active = True
        os.replace(pack_tmp, pack_path)
        pack_tmp = ""
        os.replace(manifest_tmp, manifest_path)
        manifest_tmp = ""
        os.unlink(marker_path)
        marker_active = False
    except BaseException as exc:
        rollback_errors = []
        for target, existed, data in (
            (pack_path, old_pack_exists, old_pack),
            (manifest_path, old_manifest_exists, old_manifest),
        ):
            try:
                _restore_snapshot(target, existed, data)
            except BaseException as rollback_exc:  # pragma: no cover - catastrophic filesystem failure
                rollback_errors.append(f"{os.path.basename(target)}: {rollback_exc}")
        if rollback_errors:
            raise PackIntegrityError(
                "registry publication failed and rollback was incomplete: "
                + "; ".join(rollback_errors)
            ) from exc
        if marker_active and os.path.exists(marker_path):
            os.unlink(marker_path)
            marker_active = False
        raise
    finally:
        for tmp_path in (pack_tmp, manifest_tmp, marker_tmp):
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)


def update_manifest(pack_path: str, entry: Mapping[str, Any]) -> None:
    """Atomically update only ``pack_path``'s entry in its adjacent manifest.

    Registry generators must use :func:`publish_pack_and_manifest`; this helper
    remains for metadata-only callers and tests.
    """

    manifest_path = manifest_path_for(pack_path)
    manifest_data = _manifest_bytes(pack_path, entry)
    os.makedirs(os.path.dirname(manifest_path) or ".", exist_ok=True)
    tmp_path = _write_temp_bytes(manifest_path, manifest_data)
    try:
        os.replace(tmp_path, manifest_path)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
