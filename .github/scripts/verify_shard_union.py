"""Prove the sharded full gate ran the whole suite (.github/workflows/portable-release.yml `gate`).

The `gate_shard` matrix runs the Windows Python suite as parallel jobs. Each keeps the test files the
root conftest.py ``--atlas-shard I/N`` option assigns it (tests/atlas_shard_partition.py owns the
partition and the evidence formats) and uploads one directory of evidence:

* ``selected.txt`` -- the node ids it SELECTED (``--atlas-shard-manifest``);
* ``executed.txt`` -- the node ids that COMPLETED WITHOUT FAILURE, read from pytest's own test reports
  (``--atlas-shard-executed``): a teardown was reported, no report failed or carried an outcome
  pytest does not define, and the test's call passed or its setup or call skipped.

The required `gate` job downloads every shard's directory, collects the whole suite once, in its own
job, with ``--collect-only --atlas-shard-manifest``, and runs this script, which refuses unless:

* the evidence directory holds exactly ``--expected-shards`` entries -- a count given by the workflow,
  never inferred from whatever arrived -- each a real directory (no link) holding exactly the two
  regular files above and nothing else;
* every file is a well-formed manifest: UTF-8 without a byte-order mark, no carriage return, one
  non-blank row per line, every row LF-terminated, rows sorted, no node id repeated;
* SELECTION COVER: the full collection and every selection are non-empty, no node id is in two
  selections, and the selections together are exactly the full collection; and
* EXECUTION WITHOUT FAILURE: in every shard, the executed node ids are exactly the selected ones -- so a
  failure whose exit status a step swallowed, a ``--collect-only`` or ``--setup-plan`` run, and a run
  cut short all leave a row missing, and a test that ran without being selected is an extra row.

What that proves: the shards' selections are an exact disjoint cover of one full collection, and
every test of every shard completed without failure. A skipped, cancelled or failed shard never
reaches this script: the `gate` job's first step refuses any `gate_shard` result but success. Each
refusal names the shard directory, its counts and a sample.

What this does NOT prove: that the full collection is the right suite (it is what the repository's
pytest configuration and the gate's pinned invocation collect -- a change to pytest.ini, a conftest
hook or the workflow changes both sides alike; tests/test_portable_release_workflow.py pins the
invocation and refuses interpreter and pytest environment controls); that the evidence came from the
runs it describes (the files are unsigned artifacts of this workflow run); that every job ran the
same dependency versions -- an ACCEPTED residual: each job resolves requirements-dev.txt's ranges
itself when it starts, exactly as ci.yml's independently installing legs do, so an in-range release
or a runner-image difference between them can skew one shard's versions from another's or from the
full collection's (a skew that changes what is collected still fails the cover); or cross-file
interference on this toolchain: each shard runs only its own files in one interpreter. ci.yml's
required "Tests" legs (five Linux interpreters and "Tests · py3.12 · windows-latest") and its
required "Coverage" job each run the whole suite in one interpreter -- on Windows only that one leg
does, with its own interpreter resolution and floating dependency install, not this gate's pinned
toolchain.

Read-only and stdlib-only by design: it reads its inputs, prints, and exits 0 (verified), 1 (refused)
or 2 (usage). It imports no repository module, so it adds no static import edge to the
release_distribution component (master-reference/governance/architecture.json).
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections import Counter, namedtuple

#: How many examples each refusal names.
SAMPLE = 10

#: The evidence files every shard directory holds, and nothing else.
SELECTED = "selected.txt"
EXECUTED = "executed.txt"
SHARD_FILES = (EXECUTED, SELECTED)

#: One shard's evidence: its directory and the rows of its two files.
Shard = namedtuple("Shard", ["directory", "selected", "executed"])


class ManifestError(ValueError):
    """A manifest, or the evidence layout, that cannot be read as the gate's evidence."""


def read_manifest(path: str) -> list[str]:
    """The rows of one node id manifest, refusing every malformed spelling instead of normalizing it,
    and any repeated node id."""
    with open(path, "rb") as handle:
        data = handle.read()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ManifestError(f"{path} is not UTF-8 ({error.reason} at byte {error.start})") from None
    if text.startswith("\ufeff"):
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
    repeated = sorted(row for row, count in Counter(rows).items() if count > 1)
    if repeated:
        raise ManifestError(f"{path} repeats {len(repeated)} node id(s): {repeated[:SAMPLE]}")
    return rows


def _is_link(path: str) -> bool:
    # A Windows junction is not a symlink to os.path.islink; Python 3.12 can name it.
    isjunction = getattr(os.path, "isjunction", None)
    return os.path.islink(path) or (isjunction is not None and isjunction(path))


def shard_directories(directory: str, expected: int) -> list[str]:
    """The shard evidence directories: exactly ``expected`` real directories in ``directory``, each
    holding exactly the two regular evidence files, and nothing else at either level."""
    names = sorted(os.listdir(directory))
    irregular = [name for name in names
                 if _is_link(os.path.join(directory, name)) or not os.path.isdir(os.path.join(directory, name))]
    if irregular:
        raise ManifestError(f"{directory} holds {len(irregular)} entr(ies) that are not real shard "
                            f"evidence directories: {irregular[:SAMPLE]}")
    if len(names) != expected:
        raise ManifestError(f"expected exactly {expected} shard evidence director(ies) in {directory}, "
                            f"found {len(names)}: {names[:SAMPLE]}")
    shards = []
    for name in names:
        shard = os.path.join(directory, name)
        entries = sorted(os.listdir(shard))
        if entries != sorted(SHARD_FILES):
            raise ManifestError(f"shard directory {shard} must hold exactly {list(SHARD_FILES)}, "
                                f"found {len(entries)} entr(ies): {entries[:SAMPLE]}")
        irregular = [entry for entry in entries
                     if _is_link(os.path.join(shard, entry)) or not os.path.isfile(os.path.join(shard, entry))]
        if irregular:
            raise ManifestError(f"shard directory {shard} holds entries that are not regular files: {irregular}")
        shards.append(shard)
    return shards


def read_shard(directory: str) -> Shard:
    """One shard's evidence, every file read as a manifest."""
    return Shard(directory,
                 read_manifest(os.path.join(directory, SELECTED)),
                 read_manifest(os.path.join(directory, EXECUTED)))


def union_problems(full: list[str], shards: list[list[str]], names: list[str] | None = None) -> list[str]:
    """Every way the shards' selections fail to be an exact, disjoint cover of the full collection
    (empty: sound). Counted as multisets, so it stays exact even for input the readers would refuse.
    ``names`` labels each shard in a refusal (default: its position)."""
    labels = [str(position) for position in range(len(shards))] if names is None else names
    problems = []
    if not full:
        problems.append("the full collection is empty")
    if not shards:
        problems.append("there are no shard manifests")
    for label, rows in zip(labels, shards):
        if not rows:
            problems.append(f"shard manifest {label} is empty")
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


def execution_problems(shards: list[Shard]) -> list[str]:
    """Every shard whose executed node ids are not exactly its selected ones (empty: sound)."""
    problems = []
    for shard in shards:
        selected, executed = set(shard.selected), set(shard.executed)
        missing = sorted(selected - executed)
        extra = sorted(executed - selected)
        if missing:
            problems.append(f"shard {shard.directory}: {len(missing)} of its {len(selected)} selected node "
                            f"id(s) did not complete without failure: {missing[:SAMPLE]}")
        if extra:
            problems.append(f"shard {shard.directory}: {len(extra)} node id(s) completed that it did not "
                            f"select: {extra[:SAMPLE]}")
    return problems


def _shard_count(text: str) -> int:
    if re.fullmatch(r"[1-9][0-9]*", text, re.ASCII) is None:
        raise argparse.ArgumentTypeError(f"must be a positive decimal integer, got {text!r}")
    return int(text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Refuse unless the gate's shards selected an exact disjoint cover of one full "
                    "collection and each executed its whole selection without failure.")
    parser.add_argument("--expected-shards", type=_shard_count, required=True,
                        help="how many shards the workflow ran (its matrix size)")
    parser.add_argument("--full", required=True, help="the full --collect-only selection manifest")
    parser.add_argument("--shard-dir", required=True,
                        help="the directory holding one evidence directory per shard, and nothing else")
    args = parser.parse_args(argv)
    try:
        full = read_manifest(args.full)
        shards = [read_shard(path) for path in shard_directories(args.shard_dir, args.expected_shards)]
    except (OSError, ManifestError) as error:
        print(f"shard union refused: {error}", file=sys.stderr)
        return 1
    problems = (union_problems(full, [shard.selected for shard in shards],
                               [shard.directory for shard in shards])
                + execution_problems(shards))
    for problem in problems:
        print(f"shard union refused: {problem}", file=sys.stderr)
    if problems:
        return 1
    sizes = " + ".join(str(len(shard.selected)) for shard in shards)
    print(f"shard union verified: {len(full)} collected node ids = {sizes} across {len(shards)} disjoint "
          "shard(s); every shard completed its whole selection without failure "
          "(passed, or skipped/xfailed as pytest reports them)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
