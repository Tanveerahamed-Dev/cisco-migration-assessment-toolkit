"""Prove the sharded full gate dropped nothing (.github/workflows/portable-release.yml `gate`).

The `gate_shard` matrix runs the Windows Python suite as parallel jobs. Each keeps the test files
the root conftest.py ``--atlas-shard I/N`` option assigns it (tests/atlas_shard_partition.py owns the
partition) and uploads the node ids it SELECTED (``--atlas-shard-manifest``). The required `gate`
job then collects the whole suite once, in the same environment, with ``--collect-only
--atlas-shard-manifest`` and runs this script, which refuses unless:

* the shard directory holds exactly ``--expected-shards`` regular files -- a count given by the
  workflow, never inferred from whatever arrived;
* every manifest is well formed: UTF-8 without a byte-order mark, no carriage return, one non-blank
  row per line, every row LF-terminated, rows sorted;
* the full collection and every shard are non-empty;
* no node id is in more than one shard; and
* the shards together equal the full collection exactly, as a multiset (nothing missing, nothing
  extra, no surplus copy).

A skipped, cancelled or failed shard never reaches this script: the `gate` job's first step refuses
any `gate_shard` result but success. Each refusal names its counts and a sample.

Read-only and stdlib-only by design: it reads its inputs, prints, and exits 0 (verified), 1 (refused)
or 2 (usage). It imports no repository module, so it adds no static import edge to the
release_distribution component (master-reference/governance/architecture.json).
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections import Counter

#: How many examples each refusal names.
SAMPLE = 10


class ManifestError(ValueError):
    """A manifest, or the manifest set, that cannot be read as the gate's evidence."""


def read_manifest(path: str) -> list[str]:
    """The rows of one manifest, refusing every malformed spelling instead of normalizing it."""
    with open(path, "rb") as handle:
        data = handle.read()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ManifestError(f"{path} is not UTF-8 ({error.reason} at byte {error.start})") from None
    if text.startswith("﻿"):
        raise ManifestError(f"{path} starts with a byte-order mark")
    if "\r" in text:
        raise ManifestError(f"{path} carries a carriage return")
    if not text:
        return []
    if not text.endswith("\n"):
        raise ManifestError(f"{path} does not end its last row with a line feed")
    rows = text[:-1].split("\n")
    blank = sum(1 for row in rows if not row)
    if blank:
        raise ManifestError(f"{path} carries {blank} blank row(s)")
    if rows != sorted(rows):
        raise ManifestError(f"{path} is not sorted")
    return rows


def shard_manifest_paths(directory: str, expected: int) -> list[str]:
    """The shard manifests: exactly ``expected`` regular files, and nothing else, in ``directory``."""
    names = sorted(os.listdir(directory))
    irregular = [name for name in names
                 if os.path.islink(os.path.join(directory, name))
                 or not os.path.isfile(os.path.join(directory, name))]
    if irregular:
        raise ManifestError(f"{directory} holds entries that are not regular files: {irregular[:SAMPLE]}")
    if len(names) != expected:
        raise ManifestError(f"expected exactly {expected} shard manifest(s) in {directory}, "
                            f"found {len(names)}: {names[:SAMPLE]}")
    return [os.path.join(directory, name) for name in names]


def union_problems(full: list[str], shards: list[list[str]]) -> list[str]:
    """Every way the shards fail to be an exact, disjoint cover of the full collection (empty: sound)."""
    problems = []
    if not full:
        problems.append("the full collection is empty")
    if not shards:
        problems.append("there are no shard manifests")
    for position, rows in enumerate(shards):
        if not rows:
            problems.append(f"shard manifest {position} is empty")
    holders: dict[str, set[int]] = {}
    for position, rows in enumerate(shards):
        for row in rows:
            holders.setdefault(row, set()).add(position)
    shared = sorted(row for row, owners in holders.items() if len(owners) > 1)
    if shared:
        problems.append(f"{len(shared)} node id(s) are in more than one shard: {shared[:SAMPLE]}")
    expected = Counter(full)
    observed: Counter = Counter()
    for rows in shards:
        observed.update(rows)
    missing = sorted((expected - observed).elements())
    surplus = observed - expected
    extra = sorted(row for row in surplus.elements() if row not in expected)
    duplicated = sorted(row for row in surplus.elements() if row in expected)
    if missing:
        problems.append(f"{len(missing)} collected node id(s) are in no shard: {missing[:SAMPLE]}")
    if extra:
        problems.append(f"{len(extra)} shard node id(s) are not in the full collection: {extra[:SAMPLE]}")
    if duplicated:
        problems.append(f"{len(duplicated)} surplus duplicate shard row(s) beyond the full collection: "
                        f"{duplicated[:SAMPLE]}")
    return problems


def _shard_count(text: str) -> int:
    if re.fullmatch(r"[1-9][0-9]*", text, re.ASCII) is None:
        raise argparse.ArgumentTypeError(f"must be a positive decimal integer, got {text!r}")
    return int(text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Refuse unless the gate's shard manifests are an exact disjoint cover of one full collection.")
    parser.add_argument("--expected-shards", type=_shard_count, required=True,
                        help="how many shard manifests the workflow ran (its matrix size)")
    parser.add_argument("--full", required=True, help="the full --collect-only manifest")
    parser.add_argument("--shard-dir", required=True, help="the directory holding only the shard manifests")
    args = parser.parse_args(argv)
    try:
        full = read_manifest(args.full)
        shards = [read_manifest(path) for path in shard_manifest_paths(args.shard_dir, args.expected_shards)]
    except (OSError, ManifestError) as error:
        print(f"shard union refused: {error}", file=sys.stderr)
        return 1
    problems = union_problems(full, shards)
    for problem in problems:
        print(f"shard union refused: {problem}", file=sys.stderr)
    if problems:
        return 1
    sizes = " + ".join(str(len(rows)) for rows in shards)
    print(f"shard union verified: {len(full)} collected node ids = {sizes} across "
          f"{len(shards)} disjoint shard(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
