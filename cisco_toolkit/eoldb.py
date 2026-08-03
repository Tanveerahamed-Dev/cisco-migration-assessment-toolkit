"""Offline Cisco hardware lifecycle knowledge base.

This deliberately small table contains only claims bound to an exact Cisco
End-of-Life bulletin. End-of-sale (EoS) and last-date-of-support (LDoS) are
copied from the bulletin; no date is derived from a generic support-window
rule. Broad family claims and negative claims such as "no EoL announced" are
not evidence and therefore are not represented. An uncovered PID returns
``None`` so callers report ``Unknown`` and ask for Cisco EoX verification.

The table remains inline so every supported PID scope, date, bulletin ID, and
primary Cisco URL is reviewable in the same change.
"""

import functools
import hashlib
import json
import os
import re
from datetime import date, datetime
from pathlib import Path, PurePosixPath
from typing import Optional
from urllib.parse import urlsplit

from .registry_integrity import (
    MAX_MANIFEST_BYTES,
    PackIntegrityError,
    SOURCE_INVENTORY_RELATIVE_PATH,
    source_freshness,
)

# Date every row below was transcribed from its named Cisco bulletin and
# bound to the retained semantic primary-source fixture. Bulletin IDs and
# URLs are provenance recorded at transcription time; under the no-egress
# doctrine nothing offline can re-confirm a claim at its live Cisco URL,
# and no such re-confirmation is claimed (handoff 2026-07-30 §13.15).
_EOL_REVIEWED = "2026-07-30"
_EOL_FIXTURE_SOURCE_ID = "cisco-eol-bulletin-semantic-fixture"
_EOL_FIXTURE_RELATIVE_PATH = (
    "reference-data/official-sources/cisco/eol-bulletins.json"
)
_EOL_FIXTURE_SHA256 = (
    "7683b29e66d3e5b39d89407e60a5f08ffbf8ef9f19ab029279ffc9d0861349c3"
)
_EOL_FIXTURE_BYTES = 13_261
_EOL_FIXTURE_RETRIEVED_AT = "2026-07-30T13:48:46Z"
_EOL_EXPECTED_BULLETIN_COUNT = 17
_EOL_EXPECTED_CLAIM_COUNT = 44
_EOL_EXPECTED_URL_COUNT = 17
# Filled from the canonical 44-row semantic contract below. Unlike a URL-shape
# check, this binds every runtime date and PID scope to the retained fixture.
_EOL_SEMANTIC_SHA256 = (
    "dbbd00ce46789baeb62fee6abf56fbd366ca51d190d33c63603093cb61d2af5b"
)

_BULLETIN_ID_RE = re.compile(r"EOL\d{4,6}")
_DOCUMENT_ID_RE = re.compile(r"c51-\d{6}", re.IGNORECASE)


def _notice(
    patterns: tuple[str, ...],
    *,
    platform: str,
    eos: str,
    ldos: str,
    bulletin_id: str,
    source_url: str,
    document_id: str | None,
    match: str = "prefix",
) -> list[dict]:
    """Expand one Cisco bulletin into its deliberately bounded PID scopes."""

    source = f"Cisco EOL {bulletin_id}"
    if document_id:
        source += f" ({document_id})"
    return [
        {
            "pat": pattern,
            "match": match,
            "platform": platform,
            "eos": eos,
            "ldos": ldos,
            "source": source,
            "bulletin_id": bulletin_id,
            "document_id": document_id,
            "source_url": source_url,
            "conf": "confirmed",
        }
        for pattern in patterns
    ]


_EOL = [
    *_notice(
        ("WS-C4948E",),
        platform="Catalyst 4948E",
        eos="2017-10-31",
        ldos="2022-10-31",
        bulletin_id="EOL11273",
        document_id="c51-738116",
        source_url=(
            "https://www.cisco.com/c/en/us/products/collateral/switches/"
            "catalyst-4900-series-switches/eos-eol-notice-c51-738116.html"
        ),
    ),
    # EOL8529 does not cover the separately announced 4948-10GE family.
    *_notice(
        ("WS-C4948", "WS-C4948-BDL", "WS-C4948-E", "WS-C4948-S"),
        match="exact",
        platform="Catalyst 4948",
        eos="2013-08-01",
        ldos="2018-07-31",
        bulletin_id="EOL8529",
        document_id="c51-712223",
        source_url=(
            "https://www.cisco.com/c/en/us/products/collateral/switches/"
            "catalyst-4900-series-switches/eol_C51-712223.html"
        ),
    ),
    *_notice(
        ("WS-C4900M",),
        platform="Catalyst 4900M",
        eos="2016-10-30",
        ldos="2021-10-31",
        bulletin_id="EOL10530",
        document_id="c51-736182",
        source_url=(
            "https://www.cisco.com/c/en/us/products/collateral/switches/"
            "catalyst-4900-series-switches/eos-eol-notice-c51-736182.html"
        ),
    ),
    *_notice(
        ("WS-C4500X",),
        platform="Catalyst 4500-X",
        eos="2020-10-30",
        ldos="2025-10-31",
        bulletin_id="EOL13216",
        document_id="c51-743098",
        source_url=(
            "https://www.cisco.com/c/en/us/products/collateral/switches/"
            "catalyst-4500-x-series-switches/eos-eol-notice-c51-743098.pdf"
        ),
    ),
    *_notice(
        ("WS-C3560X-", "WS-C3750X-"),
        platform="Catalyst 3560-X / 3750-X",
        eos="2016-10-30",
        ldos="2021-10-31",
        bulletin_id="EOL10623",
        document_id="c51-736139",
        source_url=(
            "https://www.cisco.com/c/en/us/products/collateral/switches/"
            "catalyst-3560-x-series-switches/eos-eol-notice-c51-736139.html"
        ),
    ),
    *_notice(
        ("WS-C3850",),
        platform="Catalyst 3850",
        eos="2020-10-30",
        ldos="2025-10-31",
        bulletin_id="EOL13188",
        document_id="c51-743072",
        source_url=(
            "https://www.cisco.com/c/en/us/products/collateral/switches/"
            "catalyst-3850-series-switches/eos-eol-notice-c51-743072.pdf"
        ),
    ),
    *_notice(
        ("WS-C3650",),
        platform="Catalyst 3650",
        eos="2021-10-31",
        ldos="2026-10-31",
        bulletin_id="EOL13617",
        document_id="c51-744426",
        source_url=(
            "https://www.cisco.com/c/en/us/products/collateral/switches/"
            "catalyst-3650-series-switches/eos-eol-notice-c51-744426-b.html"
        ),
    ),
    # EOL10691 names these exact compact product stems. It does not cover CX.
    *_notice(
        (
            "WS-C3560C-12PC-",
            "WS-C3560C-8PC-",
            "WS-C3560CG-8PC-",
            "WS-C3560CG-8TC-",
            "WS-C3560CPD-8PT-",
        ),
        platform="Catalyst 3560-C",
        eos="2016-10-30",
        ldos="2021-10-31",
        bulletin_id="EOL10691",
        document_id="c51-736180",
        source_url=(
            "https://www.cisco.com/c/en/us/products/collateral/switches/"
            "catalyst-3560-c-series-switches/eos-eol-notice-c51-736180.html"
        ),
    ),
    *_notice(
        ("WS-C2960CG-8TC-L",),
        match="exact",
        platform="Catalyst 2960-C",
        eos="2016-10-30",
        ldos="2021-10-31",
        bulletin_id="EOL10691",
        document_id="c51-736180",
        source_url=(
            "https://www.cisco.com/c/en/us/products/collateral/switches/"
            "catalyst-3560-c-series-switches/eos-eol-notice-c51-736180.html"
        ),
    ),
    # EOL13189 covers C2960C/CPD, but not CG (above) or the CX family.
    *_notice(
        ("WS-C2960C-", "WS-C2960CPD-"),
        platform="Catalyst 2960-C",
        eos="2020-10-30",
        ldos="2025-10-31",
        bulletin_id="EOL13189",
        document_id="c51-743071",
        source_url=(
            "https://www.cisco.com/c/en/us/products/switches/"
            "catalyst-2960-c-series-switches/eos-eol-notice-c51-743071.html"
        ),
    ),
    # EOL15072 is explicitly a selected-model notice. Exact matching prevents
    # other 3560-CX models from inheriting dates that Cisco did not publish for them.
    *_notice(
        (
            "WS-C3560CX-8TC-S",
            "WS-C3560CX-8TCS++",
            "WS-C3560CX-8PC-S",
            "WS-C3560CX-8PCS++",
            "WS-C3560CX-12TC-S",
            "WS-C3560CX-12TCS++",
            "WS-C3560CX-12PC-S",
            "WS-C3560CX-12PCS++",
            "WS-C3560CX-12PD-S",
            "WS-C3560CX-12PDS++",
            "NAL-C3560CX-12TC-S",
            "NAL-C3560CX-12PC-S",
            "NAL-C3560CX-12PD-S",
            "NAL-C3560CX-8TC-S",
            "NAL-C3560CX-8PC-S",
        ),
        match="exact",
        platform="Catalyst 3560-CX (selected models)",
        eos="2024-04-30",
        ldos="2029-04-30",
        bulletin_id="EOL15072",
        document_id=None,
        source_url=(
            "https://www.cisco.com/c/en/us/products/collateral/switches/"
            "catalyst-3560-cx-series-switches/"
            "catalyst-3560-cx-serie-switche-eol.html"
        ),
    ),
    *_notice(
        ("WS-C2960X-",),
        platform="Catalyst 2960-X",
        eos="2022-10-31",
        ldos="2027-10-31",
        bulletin_id="EOL13603",
        document_id="c51-744432",
        source_url=(
            "https://www.cisco.com/c/en/us/products/collateral/switches/"
            "catalyst-2960-x-series-switches/eos-eol-notice-c51-744432.html"
        ),
    ),
    # The hyphen is material: it excludes 2960-C/CX/X/XR/Plus PIDs.
    *_notice(
        ("WS-C2960-",),
        platform="Catalyst 2960",
        eos="2014-10-31",
        ldos="2019-10-31",
        bulletin_id="EOL9449",
        document_id="c51-730121",
        source_url=(
            "https://www.cisco.com/c/en/us/products/collateral/switches/"
            "catalyst-2960-series-switches/eos-eol-notice-c51-730121.html"
        ),
    ),
    # EOL6926 covers only these 24/48-port 10/100 product stems.
    *_notice(
        (
            "WS-C3560-24PS-",
            "WS-C3560-24TS-",
            "WS-C3560-48PS-",
            "WS-C3560-48TS-",
        ),
        platform="Catalyst 3560 24/48-port 10/100",
        eos="2010-07-05",
        ldos="2015-07-31",
        bulletin_id="EOL6926",
        document_id="c51-574778",
        source_url=(
            "https://www.cisco.com/c/en/us/products/collateral/switches/"
            "catalyst-3750-series-switches/end_of_life_notice_c51-574778.html"
        ),
    ),
    *_notice(
        ("N6K-C600",),
        platform="Nexus 6000",
        eos="2017-04-30",
        ldos="2022-04-30",
        bulletin_id="EOL10891",
        document_id="c51-737195",
        source_url=(
            "https://www.cisco.com/c/en/us/products/collateral/switches/"
            "nexus-6000-series-switches/eos-eol-notice-c51-737195.html"
        ),
    ),
    *_notice(
        ("N5K-C55",),
        platform="Nexus 5500",
        eos="2019-05-05",
        ldos="2024-05-31",
        bulletin_id="EOL12308",
        document_id="c51-740720",
        source_url=(
            "https://www.cisco.com/c/en/us/products/collateral/switches/"
            "nexus-5000-series-switches/eos-eol-notice-c51-740720.html"
        ),
    ),
    *_notice(
        ("N3K-C3048",),
        platform="Nexus 3048",
        eos="2020-08-03",
        ldos="2025-08-31",
        bulletin_id="EOL13329",
        document_id="c51-743427",
        source_url=(
            "https://www.cisco.com/c/en/us/products/collateral/switches/"
            "nexus-3000-series-switches/eos-eol-notice-c51-743427.html"
        ),
    ),
    # This notice is specifically for 3064-X, not every 3064 generation.
    *_notice(
        ("N3K-C3064-X",),
        platform="Nexus 3064-X",
        eos="2017-04-28",
        ldos="2022-04-30",
        bulletin_id="EOL11097",
        document_id="c51-738099",
        source_url=(
            "https://www.cisco.com/c/en/us/products/collateral/switches/"
            "nexus-3000-series-switches/eos-eol-notice-c51-738099.html"
        ),
    ),
]

# Longest scope first so a specific PID always beats a bounded family prefix.
_EOL_SORTED = sorted(
    _EOL,
    key=lambda row: (-len(row["pat"]), 0 if row["match"] == "exact" else 1),
)


def _canonical_claims(claims: list[dict]) -> list[dict]:
    return sorted(
        claims,
        key=lambda claim: (
            claim["pattern"],
            claim["bulletin_id"],
            claim["url"],
        ),
    )


def _runtime_semantic_claims() -> list[dict]:
    return _canonical_claims(
        [
            {
                "bulletin_id": row["bulletin_id"],
                "document_id": row["document_id"],
                "url": row["source_url"],
                "pattern": row["pat"],
                "match": row["match"],
                "platform": row["platform"],
                "eos": row["eos"],
                "ldos": row["ldos"],
            }
            for row in _EOL
        ]
    )


def _semantic_sha256(claims: list[dict]) -> str:
    canonical = json.dumps(
        _canonical_claims(claims),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _strict_json_loads(text: str, *, label: str) -> object:
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
        raise PackIntegrityError(f"{label} JSON is invalid: {exc}") from exc


def _validated_fixture_claims(fixture: object) -> list[dict]:
    """Validate the exact retained fixture schema and flatten its claims."""

    top_keys = {
        "schema_version",
        "purpose",
        "evidence_method",
        "retrieved_at",
        "reviewed_at",
        "sources",
    }
    if not isinstance(fixture, dict) or set(fixture) != top_keys:
        raise PackIntegrityError("Cisco EoL fixture top-level schema is unsupported")
    if fixture.get("schema_version") != 1:
        raise PackIntegrityError("Cisco EoL fixture schema version is unsupported")
    if (
        not str(fixture.get("purpose") or "").strip()
        or not str(fixture.get("evidence_method") or "").strip()
        or fixture.get("retrieved_at") != _EOL_FIXTURE_RETRIEVED_AT
        or fixture.get("reviewed_at") != _EOL_REVIEWED
    ):
        raise PackIntegrityError("Cisco EoL fixture evidence metadata is invalid")
    sources = fixture.get("sources")
    if not isinstance(sources, list) or len(sources) != _EOL_EXPECTED_BULLETIN_COUNT:
        raise PackIntegrityError("Cisco EoL fixture bulletin cardinality is invalid")

    bulletin_ids: set[str] = set()
    urls: set[str] = set()
    patterns: set[str] = set()
    flattened: list[dict] = []
    for source_number, source in enumerate(sources, 1):
        if not isinstance(source, dict) or set(source) != {
            "bulletin_id",
            "document_id",
            "url",
            "claims",
        }:
            raise PackIntegrityError(
                f"Cisco EoL fixture source {source_number} schema is invalid"
            )
        bulletin_id = source["bulletin_id"]
        document_id = source["document_id"]
        url = source["url"]
        if (
            not isinstance(bulletin_id, str)
            or not _BULLETIN_ID_RE.fullmatch(bulletin_id)
            or bulletin_id in bulletin_ids
            or not isinstance(url, str)
            or url in urls
        ):
            raise PackIntegrityError(
                f"Cisco EoL fixture source {source_number} identity is invalid"
            )
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "www.cisco.com"
            or not parsed.path.startswith("/c/en/us/products/")
            or parsed.query
            or parsed.fragment
        ):
            raise PackIntegrityError(
                f"Cisco EoL fixture source {source_number} URL is invalid"
            )
        if document_id is not None and (
            not isinstance(document_id, str)
            or not _DOCUMENT_ID_RE.fullmatch(document_id)
            or document_id.lower() not in parsed.path.lower()
        ):
            raise PackIntegrityError(
                f"Cisco EoL fixture source {source_number} document ID is invalid"
            )
        bulletin_ids.add(bulletin_id)
        urls.add(url)

        claims = source["claims"]
        if not isinstance(claims, list) or not claims:
            raise PackIntegrityError(
                f"Cisco EoL fixture source {source_number} has no claims"
            )
        for claim_number, claim in enumerate(claims, 1):
            if not isinstance(claim, dict) or set(claim) != {
                "pattern",
                "match",
                "platform",
                "eos",
                "ldos",
            }:
                raise PackIntegrityError(
                    f"Cisco EoL fixture claim {source_number}.{claim_number} "
                    "schema is invalid"
                )
            pattern = claim["pattern"]
            if (
                not isinstance(pattern, str)
                or not pattern
                or pattern != pattern.upper()
                or pattern in patterns
                or claim["match"] not in ("exact", "prefix")
                or not str(claim["platform"] or "").strip()
            ):
                raise PackIntegrityError(
                    f"Cisco EoL fixture claim {source_number}.{claim_number} "
                    "scope is invalid"
                )
            try:
                eos = date.fromisoformat(claim["eos"])
                ldos = date.fromisoformat(claim["ldos"])
            except (TypeError, ValueError) as exc:
                raise PackIntegrityError(
                    f"Cisco EoL fixture claim {source_number}.{claim_number} "
                    "date is invalid"
                ) from exc
            if eos > ldos:
                raise PackIntegrityError(
                    f"Cisco EoL fixture claim {source_number}.{claim_number} "
                    "has EoS after LDoS"
                )
            patterns.add(pattern)
            flattened.append(
                {
                    "bulletin_id": bulletin_id,
                    "document_id": document_id,
                    "url": url,
                    **claim,
                }
            )

    if (
        len(urls) != _EOL_EXPECTED_URL_COUNT
        or len(flattened) != _EOL_EXPECTED_CLAIM_COUNT
    ):
        raise PackIntegrityError("Cisco EoL fixture semantic cardinality is invalid")
    return _canonical_claims(flattened)


def verify_retained_eol_source_chain(
    repository_root: str | os.PathLike[str] | None = None,
    *,
    now: datetime | None = None,
) -> dict:
    """Verify retained Cisco evidence and its exact 44-row runtime binding."""

    root = (
        Path(__file__).resolve().parent.parent
        if repository_root is None
        else Path(repository_root).resolve()
    )
    inventory_path = root / PurePosixPath(SOURCE_INVENTORY_RELATIVE_PATH)
    try:
        if inventory_path.stat().st_size > MAX_MANIFEST_BYTES:
            raise PackIntegrityError("official-source inventory exceeds its size limit")
        inventory = _strict_json_loads(
            inventory_path.read_text(encoding="utf-8"),
            label="official-source inventory",
        )
    except PackIntegrityError:
        raise
    except (OSError, UnicodeDecodeError) as exc:
        raise PackIntegrityError(
            f"official-source inventory unavailable or invalid: {exc}"
        ) from exc
    record = (
        inventory.get("sources", {}).get(_EOL_FIXTURE_SOURCE_ID)
        if isinstance(inventory, dict)
        and isinstance(inventory.get("sources"), dict)
        else None
    )
    expected_record = {
        "name": "Cisco EoL bulletin semantic primary-source fixture",
        "path": _EOL_FIXTURE_RELATIVE_PATH,
        "sha256": _EOL_FIXTURE_SHA256,
        "bytes": _EOL_FIXTURE_BYTES,
        "encoding": "utf-8",
        "media_type": "application/json",
        "fixture_schema_version": 1,
        "expected_bulletins": _EOL_EXPECTED_BULLETIN_COUNT,
        "expected_claims": _EOL_EXPECTED_CLAIM_COUNT,
        "expected_urls": _EOL_EXPECTED_URL_COUNT,
        "retrieved_at": _EOL_FIXTURE_RETRIEVED_AT,
        "reviewed_at": _EOL_REVIEWED,
    }
    if not isinstance(record, dict) or {
        key: record.get(key) for key in expected_record
    } != expected_record:
        raise PackIntegrityError(
            "Cisco EoL fixture inventory record violates its code-pinned contract"
        )

    fixture_path = root / PurePosixPath(_EOL_FIXTURE_RELATIVE_PATH)
    try:
        if fixture_path.stat().st_size != _EOL_FIXTURE_BYTES:
            raise PackIntegrityError("Cisco EoL fixture byte-size mismatch")
        raw = fixture_path.read_bytes()
    except PackIntegrityError:
        raise
    except OSError as exc:
        raise PackIntegrityError(f"Cisco EoL fixture is unavailable: {exc}") from exc
    if (
        len(raw) != _EOL_FIXTURE_BYTES
        or hashlib.sha256(raw).hexdigest() != _EOL_FIXTURE_SHA256
    ):
        raise PackIntegrityError("Cisco EoL fixture SHA-256 mismatch")
    try:
        fixture = _strict_json_loads(
            raw.decode("utf-8", "strict"),
            label="Cisco EoL fixture",
        )
    except UnicodeDecodeError as exc:
        raise PackIntegrityError(f"Cisco EoL fixture JSON is invalid: {exc}") from exc

    fixture_claims = _validated_fixture_claims(fixture)
    runtime_claims = _runtime_semantic_claims()
    if fixture_claims != runtime_claims:
        raise PackIntegrityError(
            "Cisco EoL fixture dates/PID scopes do not exactly match runtime code"
        )
    semantic_hash = _semantic_sha256(runtime_claims)
    if semantic_hash != _EOL_SEMANTIC_SHA256:
        raise PackIntegrityError(
            "Cisco EoL runtime semantic digest violates its code-pinned contract"
        )
    freshness = source_freshness(_EOL_FIXTURE_RETRIEVED_AT, now=now)
    if not freshness["source_fresh"]:
        raise PackIntegrityError(
            f"Cisco EoL fixture is {freshness['freshness_status']}"
        )
    return {
        "verified": True,
        "fixture_path": _EOL_FIXTURE_RELATIVE_PATH,
        "fixture_sha256": _EOL_FIXTURE_SHA256,
        "fixture_bytes": _EOL_FIXTURE_BYTES,
        "reviewed_at": _EOL_REVIEWED,
        "bulletin_count": len({claim["bulletin_id"] for claim in runtime_claims}),
        "model_scope_count": len(runtime_claims),
        "exact_url_count": len({claim["url"] for claim in runtime_claims}),
        "semantic_sha256": semantic_hash,
        **freshness,
    }


@functools.lru_cache(maxsize=1)
def _runtime_source_proof() -> dict:
    return verify_retained_eol_source_chain()


def _citation_shape_valid(row: object) -> bool:
    if not isinstance(row, dict):
        return False
    bulletin_id = row.get("bulletin_id")
    source_url = row.get("source_url")
    document_id = row.get("document_id")
    if (
        not isinstance(bulletin_id, str)
        or not _BULLETIN_ID_RE.fullmatch(bulletin_id)
        or not isinstance(source_url, str)
    ):
        return False

    parsed = urlsplit(source_url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "www.cisco.com"
        or not parsed.path.startswith("/c/en/us/products/")
        or parsed.query
        or parsed.fragment
    ):
        return False
    if document_id is not None:
        if (
            not isinstance(document_id, str)
            or not _DOCUMENT_ID_RE.fullmatch(document_id)
            or document_id.lower() not in parsed.path.lower()
        ):
            return False
    source = str(row.get("source") or "")
    if bulletin_id not in source or (
        document_id is not None and document_id.lower() not in source.lower()
    ):
        return False
    return True


def _citation_status(row: object) -> str:
    """Return whether this exact citation is retained and runtime-bound."""

    if not _citation_shape_valid(row):
        return "unresolved-reference"
    try:
        _runtime_source_proof()
    except (PackIntegrityError, OSError, ValueError):
        return "primary-url-unverified"
    return "retained-primary-fixture"


def provenance_health() -> dict:
    """Return schema, retained-byte, semantic-binding, and freshness health."""

    errors: list[str] = []
    try:
        date.fromisoformat(_EOL_REVIEWED)
    except ValueError:
        errors.append("reviewed_at is not an ISO date")

    seen: set[str] = set()
    cited = 0
    for row_number, row in enumerate(_EOL, 1):
        pat = row.get("pat")
        if not isinstance(pat, str) or not pat or pat != pat.upper():
            errors.append(f"row {row_number} has an invalid model scope")
        elif pat in seen:
            errors.append(f"row {row_number} duplicates model scope {pat}")
        else:
            seen.add(pat)
        if row.get("match") not in ("exact", "prefix"):
            errors.append(f"row {row_number} has an invalid match rule")
        if not str(row.get("platform") or "").strip():
            errors.append(f"row {row_number} has no platform")
        if row.get("conf") != "confirmed":
            errors.append(f"row {row_number} is not bulletin-confirmed")

        parsed_dates = {}
        for field in ("eos", "ldos"):
            value = row.get(field)
            if not isinstance(value, str) or not value:
                errors.append(f"row {row_number} has no {field}")
                continue
            try:
                parsed_dates[field] = date.fromisoformat(value)
            except ValueError:
                errors.append(f"row {row_number} has an invalid {field}")
        if (
            parsed_dates.get("eos")
            and parsed_dates.get("ldos")
            and parsed_dates["eos"] > parsed_dates["ldos"]
        ):
            errors.append(f"row {row_number} has EoS after LDoS")

        if _citation_shape_valid(row):
            cited += 1
        else:
            errors.append(f"row {row_number} has no exact official Cisco bulletin")

    schema_ok = not errors
    unresolved = len(_EOL) - cited
    semantic_hash = _semantic_sha256(_runtime_semantic_claims())
    build_provenance_ok = (
        semantic_hash == _EOL_SEMANTIC_SHA256
        and len(_EOL) == _EOL_EXPECTED_CLAIM_COUNT
    )
    proof: dict = {}
    proof_error = ""
    try:
        proof = _runtime_source_proof()
    except (PackIntegrityError, OSError, ValueError) as exc:
        proof_error = str(exc)
    retained_ok = bool(proof.get("verified"))
    freshness = (
        {
            key: value
            for key, value in proof.items()
            if key
            in {
                "source_retrieved_at",
                "source_age_days",
                "source_max_age_days",
                "source_max_future_skew_seconds",
                "source_future_dated",
                "source_stale",
                "source_fresh",
                "freshness_status",
            }
        }
        if retained_ok
        else source_freshness(_EOL_FIXTURE_RETRIEVED_AT)
    )
    source_ok = bool(
        schema_ok
        and unresolved == 0
        and build_provenance_ok
        and retained_ok
        and freshness["source_fresh"]
    )
    return {
        "status": (
            "verified-authoritative"
            if source_ok
            else (
                "semantic-build-provenance-source-unverified"
                if schema_ok and build_provenance_ok
                else "invalid"
            )
        ),
        "integrity_verified": retained_ok,
        "integrity_scope": (
            "retained-fixture-sha256-plus-exact-runtime-semantic-binding"
        ),
        "schema_verified": schema_ok,
        "build_provenance_verified": build_provenance_ok,
        "retained_source_bytes_verified": retained_ok,
        "source_authoritative": source_ok,
        "authoritative": source_ok,
        "path": os.path.abspath(__file__),
        "fixture_path": (
            proof.get("fixture_path")
            or _EOL_FIXTURE_RELATIVE_PATH
        ),
        "fixture_sha256": _EOL_FIXTURE_SHA256,
        "semantic_sha256": semantic_hash,
        "reviewed_at": _EOL_REVIEWED,
        "row_count": len(_EOL),
        "bulletin_count": _EOL_EXPECTED_BULLETIN_COUNT,
        "exact_url_count": _EOL_EXPECTED_URL_COUNT,
        "bulletin_cited_rows": cited,
        "fixture_bound_rows": len(_EOL) if retained_ok else 0,
        "unresolved_reference_rows": unresolved,
        "active_unresolved_rows": 0,
        "error": "; ".join((errors + ([proof_error] if proof_error else []))[:5]),
        **freshness,
    }


def registry_health(load: bool = True) -> dict:
    """Compatibility-shaped authority health for the pipeline authority map."""

    del load
    return provenance_health()


def lifecycle_for(model: str) -> Optional[dict]:
    """Return a bulletin-backed record for ``model``, or ``None`` to abstain."""

    normalized = str(model or "").strip().upper()
    if not normalized:
        return None
    for record in _EOL_SORTED:
        pattern = record["pat"]
        matched = (
            normalized == pattern
            if record["match"] == "exact"
            else normalized.startswith(pattern)
        )
        if not matched:
            continue
        result = dict(record)
        result["matched_pattern"] = pattern
        result["match_kind"] = (
            "exact"
            if record["match"] == "exact" or normalized == pattern
            else "family-prefix"
        )
        result["reviewed_at"] = _EOL_REVIEWED
        result["citation_status"] = _citation_status(record)
        result["source_authoritative"] = (
            result["citation_status"] == "retained-primary-fixture"
        )
        if result["source_authoritative"]:
            proof = _runtime_source_proof()
            result["source_fresh"] = proof["source_fresh"]
            result["fixture_sha256"] = proof["fixture_sha256"]
        else:
            result["source_fresh"] = False
        return result
    return None
