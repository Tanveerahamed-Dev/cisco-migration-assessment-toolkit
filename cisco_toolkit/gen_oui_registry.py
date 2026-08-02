"""Deterministically regenerate the offline OUI registry from retained IEEE CSVs.

The authoritative path reads the repository's hash-pinned official IEEE
Registration Authority MA-L, MA-M, and MA-S CSV inputs. It never fetches a URL.
The emitted ``PREFIX<TAB>bits<TAB>vendor`` gzip has ``mtime=0`` and is published
transactionally with its integrity/source manifest.

    python -m cisco_toolkit.gen_oui_registry

The legacy positional ``manuf`` parser remains available only for custom,
non-authoritative outputs and cannot replace the shipped pack.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import os
import re
from typing import Iterator, Tuple

from .registry_integrity import (
    PackIntegrityError,
    SOURCE_INVENTORY_RELATIVE_PATH,
    enforce_non_regression,
    load_retained_source,
    manifest_path_for,
    metadata_for_bytes,
    paths_refer_to_same_file,
    publish_pack_and_manifest,
)

_DEFAULT_OUT = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "data",
    "oui_registry.tsv.gz",
)
_VALID_BITS = (24, 28, 36)
_MINIMUM_RETAINED_RATIO = 0.90
_MAX_SOURCE_BYTES = 64 * 1024 * 1024
_IEEE_HEADER = (
    "Registry",
    "Assignment",
    "Organization Name",
    "Organization Address",
)
_IEEE_SOURCES = (
    ("ieee-ma-l", "MA-L", 24),
    ("ieee-ma-m", "MA-M", 28),
    ("ieee-ma-s", "MA-S", 36),
)


def parse_manuf(lines) -> Iterator[Tuple[str, int, str]]:
    """Yield rows from a legacy Wireshark ``manuf`` input.

    This compatibility parser is not an authoritative source path. Authoritative
    shipped output is generated only by :func:`build_authoritative`.
    """

    for raw in lines:
        line = raw.rstrip("\n")
        if not line or line.lstrip().startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        macfield, short = parts[0], parts[1]
        long_ = parts[2] if len(parts) >= 3 else ""
        if "/" in macfield:
            mac, _, bits_s = macfield.partition("/")
            try:
                bits = int(bits_s)
            except ValueError:
                continue
        else:
            mac, bits = macfield, 24
        if bits not in _VALID_BITS:
            continue
        if not re.fullmatch(
            r"[0-9A-Fa-f]{2}(?:[:-][0-9A-Fa-f]{2}){2,5}",
            mac,
        ):
            continue
        hexp = re.sub(r"[:-]", "", mac).upper()
        nibble_count = bits // 4
        if len(hexp) < nibble_count:
            continue
        vendor = (long_ or short).strip()
        if vendor:
            yield hexp[:nibble_count], bits, vendor


def parse_ieee_csv(
    text: str,
    *,
    expected_registry: str,
    bits: int,
) -> Iterator[Tuple[str, int, str]]:
    """Yield strict OUI rows from one official IEEE Registration Authority CSV."""

    if bits not in _VALID_BITS:
        raise ValueError(f"unsupported IEEE assignment width {bits!r}")
    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    header = next(reader, None)
    if tuple(header or ()) != _IEEE_HEADER:
        raise ValueError("IEEE CSV header/schema is unsupported")
    expected_width = bits // 4
    for row_number, row in enumerate(reader, 2):
        if not row or not any(cell for cell in row):
            continue
        if len(row) != len(_IEEE_HEADER):
            raise ValueError(f"IEEE CSV contains a truncated row at line {row_number}")
        registry_name, assignment, organization, _address = (
            value.strip() for value in row
        )
        if registry_name != expected_registry:
            raise ValueError(
                f"IEEE CSV registry mismatch at line {row_number}: "
                f"expected {expected_registry!r}, got {registry_name!r}"
            )
        if not re.fullmatch(rf"[0-9A-F]{{{expected_width}}}", assignment):
            raise ValueError(
                f"IEEE CSV assignment is invalid at line {row_number}: "
                f"{assignment!r}"
            )
        if not organization:
            raise ValueError(
                f"IEEE CSV organization is absent at line {row_number}"
            )
        yield assignment, bits, organization


def write_registry(
    rows: Iterator[Tuple[str, int, str]],
    out_path: str,
    *,
    source: dict | None = None,
    baseline_path: str | None = None,
    provenance_status: str = "legacy-local-input-non-authoritative",
    generated_at: str | None = None,
    extra: dict | None = None,
) -> int:
    """Transactionally write a schema-valid registry and integrity manifest."""

    out_path = os.path.abspath(out_path)
    out_dir = os.path.dirname(out_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    records: dict[tuple[int, str], str] = {}
    for hexp, bits, vendor in rows:
        if (
            type(bits) is not int
            or bits not in _VALID_BITS
            or not isinstance(hexp, str)
            or not re.fullmatch(rf"[0-9A-F]{{{bits // 4}}}", hexp)
            or not isinstance(vendor, str)
            or not vendor.strip()
            or any(ord(char) < 32 or ord(char) == 127 for char in vendor)
        ):
            raise ValueError(
                f"invalid OUI generator record: {(hexp, bits, vendor)!r}"
            )
        vendor = vendor.strip()
        key = (bits, hexp)
        previous = records.get(key)
        if previous is not None and previous != vendor:
            raise ValueError(f"conflicting duplicate OUI prefix {hexp}/{bits}")
        records[key] = vendor
    if not records:
        raise ValueError("refusing to write an empty OUI registry")

    payload = "".join(
        f"{hexp}\t{bits}\t{records[(bits, hexp)]}\n"
        for bits, hexp in sorted(records)
    ).encode("utf-8")
    compressed = gzip.compress(payload, compresslevel=9, mtime=0)

    comparison = baseline_path
    if comparison is None and os.path.exists(out_path) and os.path.exists(
        manifest_path_for(out_path)
    ):
        comparison = out_path
    if comparison is not None:
        enforce_non_regression(
            {"row_count": len(records)},
            baseline_pack_path=comparison,
            minimum_ratios={"row_count": _MINIMUM_RETAINED_RATIO},
        )

    entry = metadata_for_bytes(
        compressed,
        source=source
        or {
            "name": "unattested local registry input",
            "inventory": None,
            "inventory_schema_version": None,
            "artifacts": [],
        },
        generator="cisco_toolkit.gen_oui_registry",
        provenance_status=provenance_status,
        generated_at=generated_at,
        extra=extra,
    )
    publish_pack_and_manifest(out_path, compressed, entry)
    return len(records)


def build_authoritative(
    *,
    out_path: str = _DEFAULT_OUT,
    repository_root: str | None = None,
    inventory_path: str | None = None,
) -> int:
    """Build from all three retained official IEEE primary-source artifacts."""

    source_rows: list[Tuple[str, int, str]] = []
    artifacts = []
    per_registry_counts: dict[str, int] = {}
    for source_id, registry_name, bits in _IEEE_SOURCES:
        _raw, text, artifact = load_retained_source(
            source_id,
            repository_root=repository_root,
            inventory_path=inventory_path,
        )
        parsed = list(
            parse_ieee_csv(
                text,
                expected_registry=registry_name,
                bits=bits,
            )
        )
        if len(parsed) != artifact["record_count"]:
            raise PackIntegrityError(
                f"{source_id} parsed row count does not match retained evidence"
            )
        source_rows.extend(parsed)
        artifacts.append(artifact)
        per_registry_counts[registry_name] = len(parsed)

    # IEEE's current MA-L publication contains a small number of duplicate
    # assignment keys with different organization names. A single-value
    # runtime lookup cannot represent those as separate records. Preserve all
    # published claimants in a deterministic combined value instead of
    # silently selecting one organization.
    claimants: dict[tuple[int, str], set[str]] = {}
    for assignment, bits, organization in source_rows:
        claimants.setdefault((bits, assignment), set()).add(organization)
    conflicting_prefix_count = sum(
        1 for organizations in claimants.values() if len(organizations) > 1
    )
    rows = [
        (
            assignment,
            bits,
            " / ".join(sorted(organizations, key=str.casefold)),
        )
        for (bits, assignment), organizations in claimants.items()
    ]

    retrieved_at = {artifact["retrieved_at"] for artifact in artifacts}
    if len(retrieved_at) != 1:
        raise PackIntegrityError(
            "retained IEEE artifacts do not share one retrieval batch timestamp"
        )
    return write_registry(
        iter(rows),
        out_path,
        source={
            "name": (
                "IEEE Registration Authority MA-L, MA-M, and MA-S "
                "public listings"
            ),
            "inventory": SOURCE_INVENTORY_RELATIVE_PATH,
            "inventory_schema_version": 1,
            "artifacts": artifacts,
        },
        baseline_path=_DEFAULT_OUT,
        provenance_status="generated-from-retained-ieee-primary-sources",
        generated_at=next(iter(retrieved_at)),
        extra={
            "ma_l_count": per_registry_counts["MA-L"],
            "ma_m_count": per_registry_counts["MA-M"],
            "ma_s_count": per_registry_counts["MA-S"],
            "source_row_count": len(source_rows),
            "conflicting_prefix_count": conflicting_prefix_count,
        },
    )


def _legacy_main(manuf: str, out_path: str) -> int:
    if re.match(r"^\s*[a-zA-Z][a-zA-Z0-9+.-]*://", manuf):
        raise SystemExit(
            "refusing a URL — pass retained local evidence (no-egress doctrine)"
        )
    if paths_refer_to_same_file(out_path, _DEFAULT_OUT):
        raise ValueError(
            "legacy manuf input cannot replace the authoritative shipped registry"
        )
    with open(manuf, "rb") as source_file:
        raw_source = source_file.read(_MAX_SOURCE_BYTES + 1)
    if len(raw_source) > _MAX_SOURCE_BYTES:
        raise PackIntegrityError(
            f"local manuf source exceeds the {_MAX_SOURCE_BYTES}-byte safety limit"
        )
    source_text = raw_source.decode("utf-8", "strict")
    return write_registry(
        parse_manuf(source_text.splitlines()),
        out_path,
        source={
            "name": "legacy local Wireshark manuf input",
            "inventory": None,
            "inventory_schema_version": None,
            "artifacts": [
                {
                    "id": "legacy-manuf",
                    "name": os.path.basename(manuf),
                    "url": None,
                    "retained_path": None,
                    "retrieved_at": None,
                    "sha256": hashlib.sha256(raw_source).hexdigest(),
                    "bytes": len(raw_source),
                    "hash_scope": "raw-source-bytes",
                    "media_type": "text/plain",
                    "encoding": "utf-8",
                    "record_count": sum(
                        1 for _ in parse_manuf(source_text.splitlines())
                    ),
                }
            ],
        },
        provenance_status="legacy-local-input-non-authoritative",
    )


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(
        prog="cisco-gen-oui-registry",
        description=__doc__,
    )
    parser.add_argument(
        "manuf",
        nargs="?",
        help=(
            "legacy local Wireshark manuf input; custom non-authoritative "
            "output only"
        ),
    )
    parser.add_argument(
        "--out",
        default=_DEFAULT_OUT,
        help="output tsv.gz (default: shipped pack)",
    )
    parser.add_argument(
        "--repository-root",
        help="repository root containing retained official sources",
    )
    parser.add_argument(
        "--inventory",
        help="override retained-source inventory path (verification/testing)",
    )
    args = parser.parse_args(argv)
    if args.manuf:
        count = _legacy_main(args.manuf, args.out)
    else:
        count = build_authoritative(
            out_path=args.out,
            repository_root=args.repository_root,
            inventory_path=args.inventory,
        )
    print(f"wrote {count} OUI rows -> {args.out}")


if __name__ == "__main__":
    main()
