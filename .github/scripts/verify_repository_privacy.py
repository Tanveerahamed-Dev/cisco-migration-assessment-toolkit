"""Reject engagement material and known client markers in the tracked source tree."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import stat
import subprocess
import sys
from datetime import date
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

_DENIED_PATHS = (
    re.compile(r"(?:^|/)private-inputs(?:/|$)", re.IGNORECASE),
    re.compile(r"(?:^|/)client-inputs(?:/|$)", re.IGNORECASE),
    re.compile(r"(?:^|/)engagements(?:/|$)", re.IGNORECASE),
    re.compile(r"^(?:AI_SESSION_CONTEXT|CHAT_SUMMARY)\.md$", re.IGNORECASE),
    re.compile(r"^compass_artifact_", re.IGNORECASE),
    re.compile(r"^requirements\.(?!sample\.json$).+\.json$", re.IGNORECASE),
    re.compile(r"^docs/(?:assessment|security)(?:/|$)", re.IGNORECASE),
    re.compile(r"^docs/universality-gap-audit-raw\.json$", re.IGNORECASE),
    re.compile(r"^docs/wave-(?:findings|triage)-.+\.md$", re.IGNORECASE),
)
_DENIED_SUFFIXES = (
    ".docx",
    ".pptx",
    ".xlsx",
    ".precert.json",
    ".precert-readiness.json",
)
_ALLOWED_SNAPSHOTS = {
    "tests/golden/snapshot.json",
    "webapp/sample_data/sample_fleet.snapshot.json",
}
_KNOWN_HOST_HASHES = PurePosixPath(
    ".github/privacy/known_client_hostname_sha256.txt"
)
_REGISTRY_MANIFEST = PurePosixPath(
    "cisco_toolkit/data/registry_manifest.json"
)
_OFFICIAL_SOURCE_MANIFEST = PurePosixPath(
    "reference-data/official-sources/manifest.json"
)
_AUTHORITATIVE_BINARY_PACKS = (
    "oui_registry.tsv.gz",
    "port_registry.tsv.gz",
)
# BEGIN GENERATED SYNTHETIC VISUAL BASELINE PINS
_SYNTHETIC_VISUAL_BASELINES = {
    "webapp/frontend/visual-e2e/__screenshots__/windows-2025-x64/ArchReviewPanel-728.png": {
        "bytes": 56_781,
        "height": 700,
        "media_type": "image/png",
        "sha256": "1d58216b730a2387a491610583891002b4c12fcb0637702cd3d880dd810f4c09",
        "width": 728,
    },
    "webapp/frontend/visual-e2e/__screenshots__/windows-2025-x64/ArchReviewPanel.png": {
        "bytes": 56_766,
        "height": 700,
        "media_type": "image/png",
        "sha256": "b3b94ce5865b073ddd456b5853e3b460e2231f34fcc784dcaf48d9e3eda0a45b",
        "width": 900,
    },
    "webapp/frontend/visual-e2e/__screenshots__/windows-2025-x64/Bars-728.png": {
        "bytes": 26_208,
        "height": 700,
        "media_type": "image/png",
        "sha256": "bfef736b3d8d33acdffbb730641f0d87a501d4b162629b7d0fe6b394b19448ab",
        "width": 728,
    },
    "webapp/frontend/visual-e2e/__screenshots__/windows-2025-x64/Bars.png": {
        "bytes": 26_744,
        "height": 700,
        "media_type": "image/png",
        "sha256": "db5630a3e42c38c7cef822ad4e40c5ce6c85b9ae104352bf25d72427c501fab5",
        "width": 900,
    },
    "webapp/frontend/visual-e2e/__screenshots__/windows-2025-x64/CableMap-728.png": {
        "bytes": 65_743,
        "height": 732,
        "media_type": "image/png",
        "sha256": "35ebefaf8adb67819508e63c06a8f7d2a6e7fc0ad30ac6d801a64ecf3d34513d",
        "width": 728,
    },
    "webapp/frontend/visual-e2e/__screenshots__/windows-2025-x64/CableMap.png": {
        "bytes": 71_784,
        "height": 802,
        "media_type": "image/png",
        "sha256": "0ecf88f77e0b20d94bbef9ea20b897e9ff226f019b3e75fd5af8037ba4eb443b",
        "width": 900,
    },
    "webapp/frontend/visual-e2e/__screenshots__/windows-2025-x64/CausalFlowPanel-728.png": {
        "bytes": 136_743,
        "height": 1367,
        "media_type": "image/png",
        "sha256": "a88892fe7b873495862ecbe448eed15faaa03c50f43c85cc5ad5f6d9caf2dc0b",
        "width": 728,
    },
    "webapp/frontend/visual-e2e/__screenshots__/windows-2025-x64/CausalFlowPanel.png": {
        "bytes": 151_538,
        "height": 1449,
        "media_type": "image/png",
        "sha256": "0a3ff7790edd9d602e44c7c228ec7edbb448d4c5476b55c48c5533b02c9e16b7",
        "width": 900,
    },
    "webapp/frontend/visual-e2e/__screenshots__/windows-2025-x64/CountUp-728.png": {
        "bytes": 19_637,
        "height": 700,
        "media_type": "image/png",
        "sha256": "773d3d22efc273c99299667ca01ea34f39a20803edb18d799c7481b5b3f2eb4a",
        "width": 728,
    },
    "webapp/frontend/visual-e2e/__screenshots__/windows-2025-x64/CountUp.png": {
        "bytes": 19_997,
        "height": 700,
        "media_type": "image/png",
        "sha256": "84cf87bd468cf6e21706a7d6f02951dc13b346a7f59ecd88abdc594920a515ef",
        "width": 900,
    },
    "webapp/frontend/visual-e2e/__screenshots__/windows-2025-x64/CutoverPlanner-728.png": {
        "bytes": 153_603,
        "height": 1794,
        "media_type": "image/png",
        "sha256": "25f6382dbba5a645b4ce78ff3d4a8d0ff88c665615e5db7b5a9f9ddad8d3f3dd",
        "width": 728,
    },
    "webapp/frontend/visual-e2e/__screenshots__/windows-2025-x64/CutoverPlanner.png": {
        "bytes": 151_773,
        "height": 1558,
        "media_type": "image/png",
        "sha256": "9f833eafc6c1eb6fd45ba8b4afb717ad81eed87bef9df6ba9e8532f3c16bb064",
        "width": 900,
    },
    "webapp/frontend/visual-e2e/__screenshots__/windows-2025-x64/DemoDataProvider-728.png": {
        "bytes": 77_349,
        "height": 986,
        "media_type": "image/png",
        "sha256": "9cd23f5fac84b6320891f84452c80d69c9f8489d6d12068784535cb85ba3ee87",
        "width": 728,
    },
    "webapp/frontend/visual-e2e/__screenshots__/windows-2025-x64/DemoDataProvider.png": {
        "bytes": 82_653,
        "height": 824,
        "media_type": "image/png",
        "sha256": "b967c8aa7fad6df56b8c561557f8d6adae64fd27fc1af2216d820bd856e1158b",
        "width": 900,
    },
    "webapp/frontend/visual-e2e/__screenshots__/windows-2025-x64/DesignBlueprintPanel-728.png": {
        "bytes": 296_560,
        "height": 3184,
        "media_type": "image/png",
        "sha256": "bf30b069e740309103cd467959e91fa17ee3c3cdd1527b7bea7ca746393d8e6e",
        "width": 728,
    },
    "webapp/frontend/visual-e2e/__screenshots__/windows-2025-x64/DesignBlueprintPanel.png": {
        "bytes": 298_856,
        "height": 3115,
        "media_type": "image/png",
        "sha256": "8af6edf9c937e67d94b55ee65840ea96e7e7ac67341ca5f49e7065b6816b5c1e",
        "width": 900,
    },
    "webapp/frontend/visual-e2e/__screenshots__/windows-2025-x64/ErrorBoundary-728.png": {
        "bytes": 26_440,
        "height": 700,
        "media_type": "image/png",
        "sha256": "b4458769d5bd665743873bd6eaeca111351d0973911bc3377a2f9776ad300981",
        "width": 728,
    },
    "webapp/frontend/visual-e2e/__screenshots__/windows-2025-x64/ErrorBoundary.png": {
        "bytes": 25_276,
        "height": 700,
        "media_type": "image/png",
        "sha256": "32b0d28b6bc0a2f49c9a396bffa5d556e5361a08f3ad53522d4a870835e2884b",
        "width": 900,
    },
    "webapp/frontend/visual-e2e/__screenshots__/windows-2025-x64/ErrorBox-728.png": {
        "bytes": 21_926,
        "height": 700,
        "media_type": "image/png",
        "sha256": "1791bc6b8849168168837b0fb6d1aa2854d4316eff80ce2dd20fdc41cb64d1a1",
        "width": 728,
    },
    "webapp/frontend/visual-e2e/__screenshots__/windows-2025-x64/ErrorBox.png": {
        "bytes": 21_573,
        "height": 700,
        "media_type": "image/png",
        "sha256": "25cc16636cf3765089df14fc317310bd5f2cb33748a9bc2c3fb1dc822b27463e",
        "width": 900,
    },
    "webapp/frontend/visual-e2e/__screenshots__/windows-2025-x64/Gauge-728.png": {
        "bytes": 42_313,
        "height": 700,
        "media_type": "image/png",
        "sha256": "c308b5e543944ee6898265fd277b22e6b78d1fc389d9975eb8bb50f87cafb2da",
        "width": 728,
    },
    "webapp/frontend/visual-e2e/__screenshots__/windows-2025-x64/Gauge.png": {
        "bytes": 42_655,
        "height": 700,
        "media_type": "image/png",
        "sha256": "da6a62279c5f63770a4985e58795c40b77cebcba1d900b67161eeb2afd657a65",
        "width": 900,
    },
    "webapp/frontend/visual-e2e/__screenshots__/windows-2025-x64/Kpi-728.png": {
        "bytes": 59_584,
        "height": 1450,
        "media_type": "image/png",
        "sha256": "853354cec5356a166e80505a1ff7470625baf2d0cf10244302e3016bd8685615",
        "width": 728,
    },
    "webapp/frontend/visual-e2e/__screenshots__/windows-2025-x64/Kpi.png": {
        "bytes": 41_270,
        "height": 700,
        "media_type": "image/png",
        "sha256": "2457f7b596486670218f8e71dbcd56edb47b075d9b8a1ee0f76b65ca7a3007c1",
        "width": 900,
    },
    "webapp/frontend/visual-e2e/__screenshots__/windows-2025-x64/Loading-728.png": {
        "bytes": 10_760,
        "height": 700,
        "media_type": "image/png",
        "sha256": "09757ecab39558054ffbd33cc1f37bea971e23702bbc0e74415c9ceb9779a571",
        "width": 728,
    },
    "webapp/frontend/visual-e2e/__screenshots__/windows-2025-x64/Loading.png": {
        "bytes": 11_110,
        "height": 700,
        "media_type": "image/png",
        "sha256": "a0c5900b9e6a4fb7c05b6c8e69ed8bab11d4d819be61c128267fbe00d2b8b822",
        "width": 900,
    },
    "webapp/frontend/visual-e2e/__screenshots__/windows-2025-x64/SegBar-728.png": {
        "bytes": 22_873,
        "height": 700,
        "media_type": "image/png",
        "sha256": "69a1e579729e1b539580a2cc66e984ea6c8f202ceb82e3de615bd03c84fdb5e0",
        "width": 728,
    },
    "webapp/frontend/visual-e2e/__screenshots__/windows-2025-x64/SegBar.png": {
        "bytes": 23_917,
        "height": 700,
        "media_type": "image/png",
        "sha256": "4c1372f610c9d95c029ddffcade2070b17fb0665f7f81d0a3bf5656858930d48",
        "width": 900,
    },
    "webapp/frontend/visual-e2e/__screenshots__/windows-2025-x64/SevChip-728.png": {
        "bytes": 35_779,
        "height": 700,
        "media_type": "image/png",
        "sha256": "50465d7dce750ff909da2678feb1d3b24450d587e7d6ffae8eadcb05b7d48301",
        "width": 728,
    },
    "webapp/frontend/visual-e2e/__screenshots__/windows-2025-x64/SevChip.png": {
        "bytes": 35_752,
        "height": 700,
        "media_type": "image/png",
        "sha256": "7b5931d70714ab74e06e02dedb265546196672d5915ced82ec77e576836633bf",
        "width": 900,
    },
    "webapp/frontend/visual-e2e/__screenshots__/windows-2025-x64/SkelLines-728.png": {
        "bytes": 11_163,
        "height": 700,
        "media_type": "image/png",
        "sha256": "0d03c73e235f131f33bed824801652dfb286b130330ba6a1d4c52ee138a9e6ac",
        "width": 728,
    },
    "webapp/frontend/visual-e2e/__screenshots__/windows-2025-x64/SkelLines.png": {
        "bytes": 11_524,
        "height": 700,
        "media_type": "image/png",
        "sha256": "40292a9c7db5223943a9884d5cc12aaf289bae4a4bff4aa10e36f102d3717741",
        "width": 900,
    },
    "webapp/frontend/visual-e2e/__screenshots__/windows-2025-x64/SkelTable-728.png": {
        "bytes": 12_267,
        "height": 700,
        "media_type": "image/png",
        "sha256": "0f92dc764b2603d0bdc533eaacf974e751022042c7f948f65adc01c3668e69c7",
        "width": 728,
    },
    "webapp/frontend/visual-e2e/__screenshots__/windows-2025-x64/SkelTable.png": {
        "bytes": 12_552,
        "height": 700,
        "media_type": "image/png",
        "sha256": "d3c1a10f0bd9ae55102189719d3102c44fe551840b27e822a4681ac66d22a8d0",
        "width": 900,
    },
    "webapp/frontend/visual-e2e/__screenshots__/windows-2025-x64/Skeleton-728.png": {
        "bytes": 7_230,
        "height": 700,
        "media_type": "image/png",
        "sha256": "72660e22c96db690ea882a4950238b3dc2b25b1d5140678caa2066bd60392947",
        "width": 728,
    },
    "webapp/frontend/visual-e2e/__screenshots__/windows-2025-x64/Skeleton.png": {
        "bytes": 7_563,
        "height": 700,
        "media_type": "image/png",
        "sha256": "cfa539eba74003d6ea0a313b133475a65d7512f0ec1224dfe3217e2b5515e7c8",
        "width": 900,
    },
    "webapp/frontend/visual-e2e/__screenshots__/windows-2025-x64/TopologyGraph-728.png": {
        "bytes": 79_046,
        "height": 700,
        "media_type": "image/png",
        "sha256": "6b354cb53bcb96bf4c0ff573fd13352cde0e7106c2d18916af0bf8ef9a835345",
        "width": 728,
    },
    "webapp/frontend/visual-e2e/__screenshots__/windows-2025-x64/TopologyGraph.png": {
        "bytes": 86_888,
        "height": 700,
        "media_type": "image/png",
        "sha256": "c5f4e6a1d68b7ff9ade6ec43b6302f6fdce3465749af621a2817b24796c034c0",
        "width": 900,
    },
    "webapp/frontend/visual-e2e/__screenshots__/windows-2025-x64/VerificationBadge-728.png": {
        "bytes": 57_399,
        "height": 950,
        "media_type": "image/png",
        "sha256": "2ea72b8f90a2f1fe1985d490d082edfc9e01aeb3fa52e36c3062bdce330dd2ba",
        "width": 728,
    },
    "webapp/frontend/visual-e2e/__screenshots__/windows-2025-x64/VerificationBadge.png": {
        "bytes": 57_976,
        "height": 950,
        "media_type": "image/png",
        "sha256": "1d7d7333a56eb46d0850f5b2b010a2e886d056c55a4ba39f39bd2712358dd7e5",
        "width": 900,
    },
    "webapp/frontend/visual-e2e/__screenshots__/windows-2025-x64/VerificationWarning-728.png": {
        "bytes": 324_505,
        "height": 1328,
        "media_type": "image/png",
        "sha256": "6630cd08f65eb9575fe9e1c41adb7248b43c353361cd73ad85dd5eb4639a9d4f",
        "width": 728,
    },
    "webapp/frontend/visual-e2e/__screenshots__/windows-2025-x64/VerificationWarning.png": {
        "bytes": 317_511,
        "height": 1203,
        "media_type": "image/png",
        "sha256": "798093a0bd0f2be18a0258b61ad7a4cf2bae73782a23c4134356b8ebac97bc26",
        "width": 900,
    },
}
# END GENERATED SYNTHETIC VISUAL BASELINE PINS
_PROJECT_BINARY_ASSETS = {
    "master-reference/public/atlas-social-card.png": {
        "bytes": 1_766_077,
        "height": 909,
        "media_type": "image/png",
        "sha256": "15854acd763600b578913cc263b3b48e56474b042f5713185e121f6f90545828",
        "width": 1731,
    },
    "master-reference/public/og.png": {
        "bytes": 2_338_417,
        "height": 909,
        "media_type": "image/png",
        "sha256": "ea17869f8f9f1a933e6d14ffed48d51fad2908c293d5eb439f4d61218b1cc208",
        "width": 1730,
    },
    **_SYNTHETIC_VISUAL_BASELINES,
}
_OFFICIAL_PUBLIC_SOURCES = {
    "iana-service-names-port-numbers": (
        "reference-data/official-sources/iana/service-names-port-numbers.csv",
        "https://www.iana.org/assignments/service-names-port-numbers/"
        "service-names-port-numbers.csv",
    ),
    "ieee-ma-l": (
        "reference-data/official-sources/ieee/oui.csv",
        "https://standards-oui.ieee.org/oui/oui.csv",
    ),
    "ieee-ma-m": (
        "reference-data/official-sources/ieee/mam.csv",
        "https://standards-oui.ieee.org/oui28/mam.csv",
    ),
    "ieee-ma-s": (
        "reference-data/official-sources/ieee/oui36.csv",
        "https://standards-oui.ieee.org/oui36/oui36.csv",
    ),
}
_EOL_SEMANTIC_SOURCE_ID = "cisco-eol-bulletin-semantic-fixture"
_EOL_SEMANTIC_SOURCE_RECORD = {
    "bytes": 13_261,
    "encoding": "utf-8",
    "expected_bulletins": 17,
    "expected_claims": 44,
    "expected_urls": 17,
    "fixture_schema_version": 1,
    "media_type": "application/json",
    "name": "Cisco EoL bulletin semantic primary-source fixture",
    "path": "reference-data/official-sources/cisco/eol-bulletins.json",
    "retrieved_at": "2026-07-30T13:48:46Z",
    "reviewed_at": "2026-07-30",
    "sha256": "7683b29e66d3e5b39d89407e60a5f08ffbf8ef9f19ab029279ffc9d0861349c3",
}
_MAX_TEXT_BYTES = 64 * 1024 * 1024
_MAX_BINARY_PACK_BYTES = 64 * 1024 * 1024
_MAX_OFFICIAL_SOURCE_BYTES = 64 * 1024 * 1024
_MAX_CANDIDATE_BYTES = 512 * 1024 * 1024
_MAX_CANDIDATE_FILES = 100_000
_MAX_CONFIG_BYTES = 1024 * 1024
_HOST_TOKEN = re.compile(
    r"(?<![A-Za-z0-9-])[A-Za-z0-9][A-Za-z0-9-]{2,}(?![A-Za-z0-9-])"
)
_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


def _metadata_identity(info: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        int(info.st_dev),
        int(info.st_ino),
        int(info.st_mode),
        int(info.st_size),
        int(info.st_mtime_ns),
    )


def _is_reparse_point(info: os.stat_result) -> bool:
    return bool(
        int(getattr(info, "st_file_attributes", 0)) & _REPARSE_POINT
    )


def _read_bounded(path: Path, maximum: int) -> bytes:
    """Read one stable ordinary file without following links or aliases."""
    before = path.lstat()
    if (
        stat.S_ISLNK(before.st_mode)
        or _is_reparse_point(before)
        or not stat.S_ISREG(before.st_mode)
    ):
        raise ValueError("path is not a regular non-link file")

    flags = os.O_RDONLY
    flags |= getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or _metadata_identity(before) != _metadata_identity(opened)
        ):
            raise ValueError("file identity changed before privacy scan")
        data = bytearray()
        while len(data) <= maximum:
            chunk = os.read(
                descriptor,
                min(1024 * 1024, maximum + 1 - len(data)),
            )
            if not chunk:
                break
            data.extend(chunk)
        after_open = os.fstat(descriptor)
    finally:
        os.close(descriptor)

    after_path = path.lstat()
    identities = {
        _metadata_identity(before),
        _metadata_identity(opened),
        _metadata_identity(after_open),
        _metadata_identity(after_path),
    }
    if (
        len(identities) != 1
        or stat.S_ISLNK(after_path.st_mode)
        or _is_reparse_point(after_path)
        or not stat.S_ISREG(after_path.st_mode)
    ):
        raise ValueError("file identity changed during privacy scan")
    if len(data) > maximum:
        raise ValueError(f"file exceeds the {maximum}-byte privacy-scan limit")
    return bytes(data)


def _git_index_entries(root: Path) -> tuple[dict[str, tuple[str, str]], list[str]]:
    """Return stage-zero index blobs and fail-closed index-shape violations."""
    result = subprocess.run(
        ["git", "ls-files", "--stage", "-z"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    entries: dict[str, tuple[str, str]] = {}
    violations: list[str] = []
    for raw in result.stdout.split(b"\0"):
        if not raw:
            continue
        if b"\t" not in raw:
            violations.append("malformed Git index entry")
            continue
        metadata, path_raw = raw.split(b"\t", 1)
        fields = metadata.split()
        path = path_raw.decode(
            "utf-8", errors="surrogateescape"
        ).replace("\\", "/")
        if len(fields) != 3:
            violations.append(f"malformed Git index metadata: {path}")
            continue
        mode = fields[0].decode("ascii", errors="replace")
        object_id = fields[1].decode("ascii", errors="replace")
        stage = fields[2].decode("ascii", errors="replace")
        if stage != "0":
            violations.append(
                f"unmerged Git index entry is forbidden: {path} (stage {stage})"
            )
            continue
        if path in entries:
            violations.append(f"duplicate Git index path is forbidden: {path}")
            continue
        entries[path] = (mode, object_id)
    return entries, violations


def _git_blob_sizes(root: Path, object_ids: list[str]) -> dict[str, int]:
    """Resolve immutable Git blob sizes without materialising blob payloads."""
    unique_ids = list(dict.fromkeys(object_ids))
    if not unique_ids:
        return {}
    result = subprocess.run(
        [
            "git",
            "cat-file",
            "--batch-check=%(objectname) %(objecttype) %(objectsize)",
        ],
        cwd=root,
        input=("".join(f"{object_id}\n" for object_id in unique_ids)).encode(
            "ascii"
        ),
        check=True,
        capture_output=True,
    )
    lines = result.stdout.splitlines()
    if len(lines) != len(unique_ids):
        raise ValueError("Git blob-size response count is inconsistent")
    sizes: dict[str, int] = {}
    for requested, raw in zip(unique_ids, lines, strict=True):
        fields = raw.decode("ascii", errors="strict").split()
        if (
            len(fields) != 3
            or fields[0] != requested
            or fields[1] != "blob"
        ):
            raise ValueError(f"Git index object is not an exact blob: {requested}")
        size = int(fields[2])
        if size < 0:
            raise ValueError(f"Git index blob has a negative size: {requested}")
        sizes[requested] = size
    return sizes


def _read_git_blob(
    root: Path,
    object_id: str,
    expected_size: int,
    maximum: int,
) -> bytes:
    """Read one immutable, pre-sized Git blob within a strict byte ceiling."""
    if expected_size > maximum:
        raise ValueError(
            f"Git blob exceeds the {maximum}-byte privacy-scan limit"
        )
    result = subprocess.run(
        ["git", "cat-file", "blob", object_id],
        cwd=root,
        check=True,
        capture_output=True,
    )
    if len(result.stdout) != expected_size:
        raise ValueError(f"Git blob size changed while reading {object_id}")
    return result.stdout


def _strict_json_object(data: bytes, label: PurePosixPath) -> dict:
    def reject_duplicate_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key in {label}: {key}")
            result[key] = value
        return result

    parsed = json.loads(
        data.decode("utf-8", errors="strict"),
        object_pairs_hook=reject_duplicate_keys,
    )
    if not isinstance(parsed, dict):
        raise ValueError(f"JSON root is not an object: {label}")
    return parsed


#: Word boundaries that treat `_` as a SEPARATOR, which `\b` does not.
#
# `\b` is defined against `\w`, and `_` is a word character — so `\bsyntys\b` never matches
# `<sidebrand>_dc_design`, and `\baj\b` never matches `<initials>_switch01`. Measured before this fix, against
# this module's own patterns: `<brand>`, `<short>-core01`, `<initials>-fleet` and `<user>` all FLAGGED, while
# `<sidebrand>_dc_design`, `<short>_core01`, `<initials>_switch01`, `<initials>_vlan_plan`, `<bid>_bid` and `<user>_home` all
# PASSED. That is not hypothetical — the working tree carries `<sidebrand>_BOQ.xlsx` and
# `<sidebrand>_DC_Design/`, so prose citing them by their real names cleared the privacy gate.
#
# The correct idiom was already in this file: the `<initials>`-qualifier pattern below ends with
# `(?![A-Za-z0-9])`. It was applied to one pattern and not the other eleven — a named subset standing
# in for the structural class, in the guard whose whole job is to be exhaustive.
_LB = r"(?<![A-Za-z0-9])"
_RB = r"(?![A-Za-z0-9])"


# The bare two-character initials pattern is the one marker that a MINIFIED bundle is
# structurally guaranteed to false-positive on eventually: bundlers emit ALPHABETICAL
# two-char export aliases (ah, ai, then the initials, then ak, ...), so any sufficiently
# large public-library bundle contains the initials as a generated identifier (first
# observed: three 0.185 via dist/assets, 2026-08-03). It is therefore excluded — ONLY this
# pattern, ONLY for built bundle assets under dist/assets — while every other marker
# (brands, users, hostnames, initials-compounds) stays active on those same files, so a
# real leak into a bundle still fails the gate. Named so the exclusion is by IDENTITY,
# never by tuple position. (The initials never appear literally in this file — §12.9.)
_BARE_INITIALS_MARKER = re.compile(_LB + re.escape("a" + "j") + _RB, re.IGNORECASE)
_MINIFIED_BUNDLE_ASSETS = re.compile(r"^webapp/frontend/dist/assets/[^/]+\.js$")


def _marker_patterns_for(
    relative: str, marker_patterns: tuple[re.Pattern[str], ...]
) -> tuple[re.Pattern[str], ...]:
    if _MINIFIED_BUNDLE_ASSETS.fullmatch(relative):
        return tuple(p for p in marker_patterns if p is not _BARE_INITIALS_MARKER)
    return marker_patterns


def _client_marker_patterns() -> tuple[re.Pattern[str], ...]:
    # Constructed from fragments so the guard does not trip over its own source.
    legacy_brand = "al" + "jazeera"
    legacy_short = "a" + "jmn"
    legacy_initials = "a" + "j"
    side_bid = "al" + "waj"
    side_brand = "syn" + "tys"
    former_user = "jaj" + "ch"
    former_machine_user = "sooq" + r"\s+" + "elaser"
    return (
        re.compile(
            re.escape(legacy_brand[:2]) + r"[\s-]*" + re.escape(legacy_brand[2:]),
            re.IGNORECASE,
        ),
        re.compile(_LB + re.escape(legacy_short) + _RB, re.IGNORECASE),
        re.compile(r"\." + re.escape(legacy_short) + _RB, re.IGNORECASE),
        _BARE_INITIALS_MARKER,
        re.compile(
            _LB
            + re.escape(legacy_initials)
            + r"(?:"
            + r"[\s_-]+(?:fleet|snapshots?|estate|engagement|collection|data|rows?|"
            + r"case|campus|shape|sdd|specific)"
            + r"|-(?:scale|style|verified|re-verified)"
            + r"|[._-](?:ftd|core|acc|assessment|local)"
            + r")(?![A-Za-z0-9])",
            re.IGNORECASE,
        ),
        re.compile(
            _LB + r"requirements\." + re.escape(legacy_initials) + r"\.json" + _RB,
            re.IGNORECASE,
        ),
        re.compile(
            _LB + r"canonical-" + re.escape(legacy_initials) + r"-fleet" + _RB,
            re.IGNORECASE,
        ),
        re.compile(_LB + re.escape(side_bid) + _RB, re.IGNORECASE),
        re.compile(_LB + re.escape(side_brand) + _RB, re.IGNORECASE),
        re.compile(_LB + r"q" + "ag" + _RB, re.IGNORECASE),
        re.compile(_LB + re.escape(former_user) + _RB, re.IGNORECASE),
        re.compile(_LB + former_machine_user + _RB, re.IGNORECASE),
    )


def _parse_known_hostname_hashes(data: bytes) -> set[str]:
    try:
        denylist_text = data.decode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise ValueError(
            f"invalid hostname hash denylist: {_KNOWN_HOST_HASHES}"
        ) from exc
    hashes: set[str] = set()
    for lineno, raw in enumerate(
        denylist_text.splitlines(), start=1
    ):
        value = raw.strip().casefold()
        if not value or value.startswith("#"):
            continue
        if not re.fullmatch(r"[0-9a-f]{64}", value):
            raise ValueError(
                f"invalid hostname hash denylist entry at "
                f"{_KNOWN_HOST_HASHES}:{lineno}"
            )
        hashes.add(value)
    if not hashes:
        raise ValueError(f"empty hostname hash denylist: {_KNOWN_HOST_HASHES}")
    return hashes


def _known_hostname_hashes(root: Path) -> set[str]:
    try:
        return _parse_known_hostname_hashes(
            _read_bounded(
                root.joinpath(*_KNOWN_HOST_HASHES.parts),
                _MAX_CONFIG_BYTES,
            )
        )
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValueError(
            f"invalid hostname hash denylist: {_KNOWN_HOST_HASHES}"
        ) from exc


def _parse_authoritative_binary_hashes(
    data: bytes,
) -> dict[str, tuple[str, int]]:
    try:
        manifest = _strict_json_object(data, _REGISTRY_MANIFEST)
        packs = manifest["packs"]
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        raise ValueError(f"invalid registry manifest: {_REGISTRY_MANIFEST}") from exc

    allowed: dict[str, tuple[str, int]] = {}
    for name in _AUTHORITATIVE_BINARY_PACKS:
        try:
            record = packs[name]
            digest = str(record["compressed_sha256"]).casefold()
            size = int(record["compressed_bytes"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(
                f"invalid binary-pack record in {_REGISTRY_MANIFEST}: {name}"
            ) from exc
        if not re.fullmatch(r"[0-9a-f]{64}", digest) or size < 1:
            raise ValueError(
                f"invalid binary-pack integrity in {_REGISTRY_MANIFEST}: {name}"
            )
        allowed[f"cisco_toolkit/data/{name}"] = (digest, size)
    return allowed


def _authoritative_binary_hashes(root: Path) -> dict[str, tuple[str, int]]:
    try:
        return _parse_authoritative_binary_hashes(
            _read_bounded(
                root.joinpath(*_REGISTRY_MANIFEST.parts),
                _MAX_CONFIG_BYTES,
            )
        )
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValueError(f"invalid registry manifest: {_REGISTRY_MANIFEST}") from exc


def _parse_official_public_source_contracts(
    data: bytes,
) -> dict[str, dict]:
    try:
        manifest = _strict_json_object(data, _OFFICIAL_SOURCE_MANIFEST)
        sources = manifest["sources"]
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        raise ValueError(
            f"invalid official-source manifest: {_OFFICIAL_SOURCE_MANIFEST}"
        ) from exc
    if (
        manifest.get("schema_version") != 1
        or not isinstance(sources, dict)
        or set(sources)
        != {*_OFFICIAL_PUBLIC_SOURCES, _EOL_SEMANTIC_SOURCE_ID}
    ):
        raise ValueError(
            f"unexpected official-source inventory: {_OFFICIAL_SOURCE_MANIFEST}"
        )

    allowed: dict[str, dict] = {}
    for source_id, (expected_path, expected_url) in (
        _OFFICIAL_PUBLIC_SOURCES.items()
    ):
        try:
            record = sources[source_id]
            relative = str(record["path"])
            url = str(record["url"])
            digest = str(record["sha256"]).casefold()
            size = int(record["bytes"])
            encoding = str(record["encoding"]).casefold()
            media_type = str(record["media_type"]).casefold()
            expected_rows = int(record["expected_rows"])
            expected_header = record["expected_header"]
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(
                f"invalid official-source record: {source_id}"
            ) from exc
        if (
            relative != expected_path
            or url != expected_url
            or encoding != "utf-8"
            or media_type != "text/csv"
            or expected_rows < 1
            or not isinstance(expected_header, list)
            or not expected_header
            or not all(
                isinstance(column, str) and column
                for column in expected_header
            )
            or not re.fullmatch(r"[0-9a-f]{64}", digest)
            or not 1 <= size <= _MAX_OFFICIAL_SOURCE_BYTES
        ):
            raise ValueError(
                f"official-source contract mismatch: {source_id}"
            )

        allowed[relative] = {
            "kind": "csv",
            "sha256": digest,
            "bytes": size,
            "expected_header": list(expected_header),
            "expected_rows": expected_rows,
        }

    if sources.get(_EOL_SEMANTIC_SOURCE_ID) != _EOL_SEMANTIC_SOURCE_RECORD:
        raise ValueError(
            "official-source contract mismatch: "
            f"{_EOL_SEMANTIC_SOURCE_ID}"
        )
    allowed[_EOL_SEMANTIC_SOURCE_RECORD["path"]] = {
        "kind": "eol-semantic-json",
        "sha256": _EOL_SEMANTIC_SOURCE_RECORD["sha256"],
        "bytes": _EOL_SEMANTIC_SOURCE_RECORD["bytes"],
        "expected_bulletins": _EOL_SEMANTIC_SOURCE_RECORD[
            "expected_bulletins"
        ],
        "expected_claims": _EOL_SEMANTIC_SOURCE_RECORD["expected_claims"],
        "expected_urls": _EOL_SEMANTIC_SOURCE_RECORD["expected_urls"],
    }
    return allowed


def _validate_official_source(
    relative: str,
    data: bytes,
    contract: dict,
) -> None:
    if (
        len(data) != contract["bytes"]
        or hashlib.sha256(data).hexdigest() != contract["sha256"]
    ):
        raise ValueError(
            f"official source fails manifest integrity: {relative}"
        )
    if contract["kind"] == "eol-semantic-json":
        _validate_eol_semantic_source(relative, data, contract)
        return

    try:
        text = data.decode("utf-8", errors="strict")
        rows = csv.reader(io.StringIO(text, newline=""))
        actual_header = next(rows)
        actual_rows = sum(1 for _ in rows)
    except (
        UnicodeError,
        ValueError,
        csv.Error,
        StopIteration,
    ) as exc:
        raise ValueError(f"official source is unreadable: {relative}") from exc
    if (
        "\x00" in text
        or actual_header != contract["expected_header"]
        or actual_rows != contract["expected_rows"]
    ):
        raise ValueError(
            f"official source fails manifest integrity: {relative}"
        )


def _validate_eol_semantic_source(
    relative: str,
    data: bytes,
    contract: dict,
) -> None:
    try:
        fixture = _strict_json_object(data, PurePosixPath(relative))
        if set(fixture) != {
            "schema_version",
            "purpose",
            "evidence_method",
            "retrieved_at",
            "reviewed_at",
            "sources",
        }:
            raise ValueError("unexpected fixture keys")
        if fixture["schema_version"] != 1:
            raise ValueError("unexpected fixture schema")
        if not all(
            isinstance(fixture[field], str) and fixture[field].strip()
            for field in (
                "purpose",
                "evidence_method",
                "retrieved_at",
                "reviewed_at",
            )
        ):
            raise ValueError("empty fixture provenance")
        date.fromisoformat(fixture["reviewed_at"])
        sources = fixture["sources"]
        if (
            not isinstance(sources, list)
            or len(sources) != contract["expected_bulletins"]
        ):
            raise ValueError("unexpected bulletin inventory")

        bulletin_ids: set[str] = set()
        urls: set[str] = set()
        model_scopes: set[tuple[str, str]] = set()
        claim_count = 0
        null_document_ids: set[str] = set()
        for source in sources:
            if not isinstance(source, dict) or set(source) != {
                "bulletin_id",
                "document_id",
                "url",
                "claims",
            }:
                raise ValueError("unexpected bulletin record")
            bulletin_id = source["bulletin_id"]
            document_id = source["document_id"]
            url = source["url"]
            claims = source["claims"]
            if (
                not isinstance(bulletin_id, str)
                or not re.fullmatch(r"EOL[0-9]+", bulletin_id)
                or bulletin_id in bulletin_ids
            ):
                raise ValueError("invalid or duplicate bulletin ID")
            if document_id is None:
                null_document_ids.add(bulletin_id)
            elif not isinstance(document_id, str) or not document_id.strip():
                raise ValueError("invalid bulletin document ID")
            parsed_url = urlsplit(url) if isinstance(url, str) else None
            if (
                parsed_url is None
                or parsed_url.scheme != "https"
                or parsed_url.netloc != "www.cisco.com"
                or not parsed_url.path.startswith("/c/en/us/")
                or parsed_url.query
                or parsed_url.fragment
                or url in urls
            ):
                raise ValueError("invalid or duplicate Cisco bulletin URL")
            if not isinstance(claims, list) or not claims:
                raise ValueError("bulletin has no semantic claims")
            bulletin_ids.add(bulletin_id)
            urls.add(url)
            for claim in claims:
                if not isinstance(claim, dict) or set(claim) != {
                    "pattern",
                    "match",
                    "platform",
                    "eos",
                    "ldos",
                }:
                    raise ValueError("unexpected semantic claim")
                pattern = claim["pattern"]
                match = claim["match"]
                platform = claim["platform"]
                if (
                    not isinstance(pattern, str)
                    or not pattern.strip()
                    or match not in {"exact", "prefix"}
                    or not isinstance(platform, str)
                    or not platform.strip()
                ):
                    raise ValueError("invalid semantic model scope")
                date.fromisoformat(claim["eos"])
                date.fromisoformat(claim["ldos"])
                scope = (pattern, match)
                if scope in model_scopes:
                    raise ValueError("duplicate semantic model scope")
                model_scopes.add(scope)
                claim_count += 1
        if (
            null_document_ids != {"EOL15072"}
            or len(urls) != contract["expected_urls"]
            or claim_count != contract["expected_claims"]
            or len(model_scopes) != contract["expected_claims"]
        ):
            raise ValueError("semantic fixture cardinality mismatch")
    except (
        KeyError,
        TypeError,
        UnicodeError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        raise ValueError(
            f"official source fails manifest integrity: {relative}"
        ) from exc


def _validate_project_binary_asset(relative: str, data: bytes) -> None:
    contract = _PROJECT_BINARY_ASSETS[relative]
    png_signature = b"\x89PNG\r\n\x1a\n"
    if (
        contract["media_type"] != "image/png"
        or len(data) != contract["bytes"]
        or hashlib.sha256(data).hexdigest() != contract["sha256"]
        or data[:8] != png_signature
        or data[8:12] != (13).to_bytes(4, "big")
        or data[12:16] != b"IHDR"
        or len(data) < 24
        or int.from_bytes(data[16:20], "big") != contract["width"]
        or int.from_bytes(data[20:24], "big") != contract["height"]
    ):
        raise ValueError(
            f"project binary asset fails exact manifest integrity: {relative}"
        )


def _official_public_source_hashes(
    root: Path,
) -> dict[str, tuple[str, int]]:
    try:
        contracts = _parse_official_public_source_contracts(
            _read_bounded(
                root.joinpath(*_OFFICIAL_SOURCE_MANIFEST.parts),
                _MAX_CONFIG_BYTES,
            )
        )
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValueError(
            f"invalid official-source manifest: {_OFFICIAL_SOURCE_MANIFEST}"
        ) from exc
    for relative, contract in contracts.items():
        try:
            data = _read_bounded(
                root.joinpath(*PurePosixPath(relative).parts),
                _MAX_OFFICIAL_SOURCE_BYTES,
            )
            _validate_official_source(relative, data, contract)
        except (OSError, UnicodeError, ValueError) as exc:
            raise ValueError(str(exc)) from exc
    return {
        relative: (contract["sha256"], contract["bytes"])
        for relative, contract in contracts.items()
    }


def _tracked_nonregular_modes(root: Path) -> dict[str, str]:
    result = subprocess.run(
        ["git", "ls-files", "--stage", "-z"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    entries: dict[str, str] = {}
    for raw in result.stdout.split(b"\0"):
        if not raw or b"\t" not in raw:
            continue
        metadata, path_raw = raw.split(b"\t", 1)
        mode = metadata.split(b" ", 1)[0].decode("ascii", errors="replace")
        if mode in {"100644", "100755"}:
            continue
        path = path_raw.decode(
            "utf-8", errors="surrogateescape"
        ).replace("\\", "/")
        entries[path] = mode
    return entries


def _candidate_files(root: Path) -> list[str]:
    result = subprocess.run(
        [
            "git",
            "ls-files",
            "-z",
            "--cached",
            "--others",
            "--exclude-standard",
        ],
        cwd=root,
        check=True,
        capture_output=True,
    )
    return sorted({
        part.decode("utf-8", errors="surrogateescape").replace("\\", "/")
        for part in result.stdout.split(b"\0")
        if part
    })


def _indexed_required_blob(
    root: Path,
    relative: PurePosixPath,
    entries: dict[str, tuple[str, str]],
    sizes: dict[str, int],
    maximum: int,
) -> bytes:
    record = entries.get(relative.as_posix())
    if record is None:
        raise ValueError(f"required Git index file is absent: {relative}")
    mode, object_id = record
    if mode not in {"100644", "100755"}:
        raise ValueError(
            f"required Git index file is non-regular: {relative} (mode {mode})"
        )
    return _read_git_blob(
        root,
        object_id,
        sizes[object_id],
        maximum,
    )


def _inspect_index_blobs(
    root: Path,
    *,
    fallback_hostname_hashes: set[str],
    fallback_authoritative_binaries: dict[str, tuple[str, int]],
    fallback_official_contracts: dict[str, dict],
) -> tuple[list[str], dict[str, tuple[str, str]]]:
    """Inspect the immutable staged bytes that the next commit would contain."""
    entries, violations = _git_index_entries(root)
    if len(entries) > _MAX_CANDIDATE_FILES:
        violations.append(
            "indexed files exceed the "
            f"{_MAX_CANDIDATE_FILES}-file privacy-scan limit"
        )
        return violations, entries

    regular_ids = [
        object_id
        for mode, object_id in entries.values()
        if mode in {"100644", "100755"}
    ]
    sizes = _git_blob_sizes(root, regular_ids)
    indexed_bytes = sum(sizes[object_id] for object_id in regular_ids)
    if indexed_bytes > _MAX_CANDIDATE_BYTES:
        violations.append(
            "indexed files exceed the "
            f"{_MAX_CANDIDATE_BYTES}-byte aggregate privacy-scan limit"
        )
        return violations, entries

    known_hostname_hashes = set(fallback_hostname_hashes)
    if _KNOWN_HOST_HASHES.as_posix() in entries:
        known_hostname_hashes.update(
            _parse_known_hostname_hashes(
                _indexed_required_blob(
                    root,
                    _KNOWN_HOST_HASHES,
                    entries,
                    sizes,
                    _MAX_CONFIG_BYTES,
                )
            )
        )
    authoritative_binaries = dict(fallback_authoritative_binaries)
    if _REGISTRY_MANIFEST.as_posix() in entries:
        authoritative_binaries = _parse_authoritative_binary_hashes(
            _indexed_required_blob(
                root,
                _REGISTRY_MANIFEST,
                entries,
                sizes,
                _MAX_CONFIG_BYTES,
            )
        )
    official_contracts = dict(fallback_official_contracts)
    if _OFFICIAL_SOURCE_MANIFEST.as_posix() in entries:
        official_contracts = _parse_official_public_source_contracts(
            _indexed_required_blob(
                root,
                _OFFICIAL_SOURCE_MANIFEST,
                entries,
                sizes,
                _MAX_CONFIG_BYTES,
            )
        )

    marker_patterns = _client_marker_patterns()
    for relative, (mode, object_id) in sorted(entries.items()):
        if mode not in {"100644", "100755"}:
            violations.append(
                f"non-regular Git entry is forbidden: {relative} (mode {mode})"
            )
            continue
        file_size = sizes[object_id]
        if any(pattern.search(relative) for pattern in _DENIED_PATHS):
            violations.append(f"denied indexed path: {relative}")
            continue
        lowered = relative.casefold()
        if lowered.endswith(_DENIED_SUFFIXES):
            violations.append(
                f"client-bearing artifact type is indexed: {relative}"
            )
            continue
        if (
            lowered.endswith(".snapshot.json")
            and relative not in _ALLOWED_SNAPSHOTS
        ):
            violations.append(f"non-synthetic snapshot is indexed: {relative}")
            continue
        if file_size > _MAX_TEXT_BYTES:
            kind = (
                "official public source"
                if relative in official_contracts
                else "authoritative binary pack"
                if relative in authoritative_binaries
                else "text file"
            )
            violations.append(
                f"indexed {kind} exceeds privacy-scan limit: {relative}"
            )
            continue
        try:
            data = _read_git_blob(
                root,
                object_id,
                file_size,
                _MAX_TEXT_BYTES,
            )
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            violations.append(f"indexed file is unreadable: {relative} ({exc})")
            continue

        if relative in official_contracts:
            try:
                _validate_official_source(
                    relative,
                    data,
                    official_contracts[relative],
                )
            except ValueError as exc:
                violations.append(f"indexed {exc}")
            continue
        if relative in authoritative_binaries:
            expected_hash, expected_size = authoritative_binaries[relative]
            if (
                len(data) != expected_size
                or hashlib.sha256(data).hexdigest() != expected_hash
            ):
                head = subprocess.run(
                    ["git", "rev-parse", "--verify", f"HEAD:{relative}"],
                    cwd=root,
                    check=False,
                    capture_output=True,
                )
                head_object = head.stdout.decode(
                    "ascii", errors="replace"
                ).strip()
                if head.returncode != 0 or head_object != object_id:
                    violations.append(
                        "indexed authoritative binary pack fails manifest "
                        f"integrity: {relative}"
                    )
            continue
        if relative in _PROJECT_BINARY_ASSETS:
            try:
                _validate_project_binary_asset(relative, data)
            except ValueError as exc:
                violations.append(f"indexed {exc}")
            continue
        try:
            text = data.decode("utf-8", errors="strict").casefold()
        except UnicodeDecodeError:
            violations.append(f"indexed binary file is not allowlisted: {relative}")
            continue
        if "\x00" in text:
            violations.append(f"indexed binary file is not allowlisted: {relative}")
            continue
        if any(
            pattern.search(text)
            for pattern in _marker_patterns_for(relative, marker_patterns)
        ):
            violations.append(
                f"known client marker appears in indexed text: {relative}"
            )
            continue
        if any(
            hashlib.sha256(token.group(0).casefold().encode("utf-8")).hexdigest()
            in known_hostname_hashes
            for token in _HOST_TOKEN.finditer(text)
        ):
            violations.append(
                f"known private hostname appears in indexed text: {relative}"
            )
    return violations, entries


def inspect_tracked_tree(
    root: Path,
    *,
    include_index: bool = True,
) -> list[str]:
    violations: list[str] = []
    try:
        known_hostname_hashes = _known_hostname_hashes(root)
        authoritative_binaries = _authoritative_binary_hashes(root)
        official_public_sources = _official_public_source_hashes(root)
        official_contracts = _parse_official_public_source_contracts(
            _read_bounded(
                root.joinpath(*_OFFICIAL_SOURCE_MANIFEST.parts),
                _MAX_CONFIG_BYTES,
            )
        )
        if include_index:
            index_violations, index_entries = _inspect_index_blobs(
                root,
                fallback_hostname_hashes=known_hostname_hashes,
                fallback_authoritative_binaries=authoritative_binaries,
                fallback_official_contracts=official_contracts,
            )
            violations.extend(index_violations)
            nonregular_modes = {
                relative: mode
                for relative, (mode, _) in index_entries.items()
                if mode not in {"100644", "100755"}
            }
        else:
            index_entries = {}
            nonregular_modes = {}
    except (OSError, UnicodeError, ValueError, subprocess.SubprocessError) as exc:
        return [f"privacy guard configuration is invalid: {exc}"]
    marker_patterns = _client_marker_patterns()
    candidate_bytes = 0
    candidates = _candidate_files(root)
    if len(candidates) > _MAX_CANDIDATE_FILES:
        return [
            "commit-visible files exceed the "
            f"{_MAX_CANDIDATE_FILES}-file privacy-scan limit"
        ]
    for relative in candidates:
        path = PurePosixPath(relative)
        disk_path = root.joinpath(*path.parts)
        if relative in nonregular_modes:
            violations.append(
                f"non-regular Git entry is forbidden: {relative} "
                f"(mode {nonregular_modes[relative]})"
            )
            continue
        try:
            file_info = disk_path.lstat()
        except FileNotFoundError:
            # The immutable index copy was scanned above; only this worktree copy is absent.
            continue
        except OSError as exc:
            violations.append(f"candidate file is unreadable: {relative} ({exc})")
            continue
        if stat.S_ISLNK(file_info.st_mode) or _is_reparse_point(file_info):
            violations.append(f"filesystem link/reparse point is forbidden: {relative}")
            continue
        if not stat.S_ISREG(file_info.st_mode):
            violations.append(f"filesystem non-regular file is forbidden: {relative}")
            continue
        file_size = file_info.st_size
        candidate_bytes += file_size
        if candidate_bytes > _MAX_CANDIDATE_BYTES:
            violations.append(
                "commit-visible files exceed the "
                f"{_MAX_CANDIDATE_BYTES}-byte aggregate privacy-scan limit"
            )
            break
        if any(pattern.search(relative) for pattern in _DENIED_PATHS):
            violations.append(f"denied tracked path: {relative}")
            continue
        lowered = relative.casefold()
        if lowered.endswith(_DENIED_SUFFIXES):
            violations.append(f"client-bearing artifact type is tracked: {relative}")
            continue
        if lowered.endswith(".snapshot.json") and relative not in _ALLOWED_SNAPSHOTS:
            violations.append(f"non-synthetic snapshot is tracked: {relative}")
            continue

        if relative in official_public_sources:
            expected_hash, expected_size = official_public_sources[relative]
            try:
                data = _read_bounded(
                    disk_path, _MAX_OFFICIAL_SOURCE_BYTES
                )
                text = data.decode("utf-8", errors="strict")
            except (OSError, UnicodeError, ValueError) as exc:
                violations.append(
                    f"official public source is unreadable: {relative} ({exc})"
                )
                continue
            if (
                "\x00" in text
                or len(data) != expected_size
                or hashlib.sha256(data).hexdigest() != expected_hash
            ):
                violations.append(
                    f"official public source fails manifest integrity: {relative}"
                )
            continue
        if relative in authoritative_binaries:
            expected_hash, expected_size = authoritative_binaries[relative]
            if expected_size > _MAX_BINARY_PACK_BYTES:
                violations.append(
                    f"authoritative binary pack exceeds scan limit: {relative}"
                )
                continue
            try:
                data = _read_bounded(disk_path, _MAX_BINARY_PACK_BYTES)
            except (OSError, ValueError) as exc:
                violations.append(f"binary pack is unreadable: {relative} ({exc})")
                continue
            actual_hash = hashlib.sha256(data).hexdigest()
            if len(data) != expected_size or actual_hash != expected_hash:
                violations.append(
                    f"authoritative binary pack fails manifest integrity: {relative}"
                )
            continue
        if relative in _PROJECT_BINARY_ASSETS:
            try:
                data = _read_bounded(disk_path, _MAX_BINARY_PACK_BYTES)
                _validate_project_binary_asset(relative, data)
            except (OSError, ValueError) as exc:
                violations.append(str(exc))
            continue
        if file_size > _MAX_TEXT_BYTES:
            violations.append(f"text file exceeds privacy-scan limit: {relative}")
            continue
        try:
            data = _read_bounded(disk_path, _MAX_TEXT_BYTES)
        except (OSError, ValueError) as exc:
            violations.append(f"candidate file is unreadable: {relative} ({exc})")
            continue
        try:
            text = data.decode("utf-8", errors="strict").casefold()
        except UnicodeDecodeError:
            violations.append(f"binary file is not allowlisted: {relative}")
            continue
        if "\x00" in text:
            violations.append(f"binary file is not allowlisted: {relative}")
            continue
        if any(
            pattern.search(text)
            for pattern in _marker_patterns_for(relative, marker_patterns)
        ):
            violations.append(
                f"known client marker appears in tracked text: {relative}"
            )
            continue
        if any(
            hashlib.sha256(token.group(0).casefold().encode("utf-8")).hexdigest()
            in known_hostname_hashes
            for token in _HOST_TOKEN.finditer(text)
        ):
            violations.append(
                f"known private hostname appears in tracked text: {relative}"
            )
    try:
        final_entries, final_index_violations = (
            _git_index_entries(root)
            if include_index
            else ({}, [])
        )
        final_candidates = _candidate_files(root)
    except (OSError, subprocess.SubprocessError) as exc:
        violations.append(f"privacy scan could not recheck repository state: {exc}")
        return violations
    if include_index and (
        final_index_violations or final_entries != index_entries
    ):
        violations.append("Git index changed during privacy scan")
    if final_candidates != candidates:
        violations.append("working-tree candidate set changed during privacy scan")
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument(
        "--worktree-only",
        action="store_true",
        help=(
            "scan stable working-tree and non-ignored untracked bytes only; "
            "this does not prove the Git index or next commit"
        ),
    )
    args = parser.parse_args(argv)
    try:
        violations = inspect_tracked_tree(
            args.root.resolve(),
            include_index=not args.worktree_only,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"privacy verification could not run: {exc}", file=sys.stderr)
        return 2
    if violations:
        scope = (
            "worktree-only privacy review"
            if args.worktree_only
            else "repository privacy verification"
        )
        print(f"{scope} failed:", file=sys.stderr)
        for violation in violations:
            print(f"- {violation}", file=sys.stderr)
        return 1
    if args.worktree_only:
        print(
            "repository worktree-only privacy review passed; "
            "the Git index and next commit were not proven"
        )
    else:
        print("repository privacy verification passed (Git index + working tree)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
