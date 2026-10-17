"""The ONE owner of the full-gate test-file partition (portable-release.yml `gate_shard` / `gate`).

The required check "Full source and frontend gate (unprivileged runner)" used to run the whole
Windows Python suite (~107 minutes) and then the frontend gate in ONE job under a 120-minute limit,
so runner contention cancelled it. The suite now runs as parallel `gate_shard` jobs, each selecting
its share through the root conftest.py options this module implements:

* ``--atlas-shard I/N`` keeps the items whose TEST FILE maps to shard I of N and deselects the rest
  (through ``pytest_deselected``, so the terminal summary still reports them);
* ``--atlas-shard-manifest PATH`` writes the final selected node ids to a NEW file, sorted, one per
  line, UTF-8 and LF only.

The required `gate` job then collects the whole suite once with ``--atlas-shard-manifest`` and
``.github/scripts/verify_shard_union.py`` refuses unless the shard manifests are non-empty, pairwise
disjoint and together exactly that full collection -- so a shard can never silently drop a file.

The partition key is the test FILE (the node id before ``::``, the rootdir-relative path pytest
already spells with ``/``), never the item: every item of a file lands in one shard, so a module- or
class-scoped fixture is still built once and in-file order is unchanged. A file's shard is
``int(sha256(path).hexdigest(), 16) % N`` -- stable across runners, interpreters and processes
(``hash()`` is salted per process by PYTHONHASHSEED) and independent of collection order.

Not a test module: the root conftest.py puts tests/ on sys.path and imports this by name, and only
when one of the two options is given, so a run without them never loads it. It lives under tests/
rather than tools/ so that it stays outside the byte-custody LF policy domains, whose tracked-path
receipts (tests/fixtures/atlas-r2-byte-custody-policy.v1.json) would otherwise move with it -- the
same reason tests/client_artifact_census.py gives for itself.
"""
from __future__ import annotations

import hashlib
import os
import re
from typing import Any, Callable, Iterable, List, Sequence, Tuple, TypeVar

#: ``I/N`` in plain ASCII decimal, no sign, no padding, no blanks: ``\d`` would also admit non-ASCII
#: digits that ``int()`` silently accepts, and ``$`` would admit a trailing line feed.
_SPEC = re.compile(r"(0|[1-9][0-9]*)/([1-9][0-9]*)", re.ASCII)

_Item = TypeVar("_Item")


class ShardOptionError(ValueError):
    """A shard option the gate refuses; the root conftest.py reports it as a pytest usage error."""


def parse_spec(text: object) -> Tuple[int, int]:
    """``(index, total)`` for an ``I/N`` spec with integers ``0 <= I < N`` and ``N >= 1``."""
    match = _SPEC.fullmatch(text) if isinstance(text, str) else None
    if match is None:
        raise ShardOptionError(
            f"--atlas-shard must be I/N in plain decimal integers with 0 <= I < N, got {text!r}")
    index, total = int(match.group(1)), int(match.group(2))
    if index >= total:
        raise ShardOptionError(f"--atlas-shard index {index} is outside 0..{total - 1}, got {text!r}")
    return index, total


def file_key(nodeid: str) -> str:
    """The test file a node id belongs to: its part before the first ``::``."""
    return nodeid.split("::", 1)[0]


def _check_total(total: object) -> int:
    # `type(...) is int`, not isinstance: bool is an int subclass, and True is not a shard count.
    if type(total) is not int or total < 1:
        raise ShardOptionError(f"a shard total must be an integer >= 1, got {total!r}")
    return total


def shard_of(path: str, total: int) -> int:
    """The shard (``0 <= shard < total``) that owns test file ``path``."""
    return int(hashlib.sha256(path.encode("utf-8")).hexdigest(), 16) % _check_total(total)


def _item_nodeid(item: Any) -> str:
    return item.nodeid


def select(items: Sequence[_Item], index: int, total: int,
           nodeid: Callable[[_Item], str] = _item_nodeid) -> Tuple[List[_Item], List[_Item]]:
    """``(kept, dropped)``: the items whose file is shard ``index`` of ``total``, and the rest, each in
    the order given (a stable filter, so the suite's own order survives inside a shard)."""
    _check_total(total)
    if type(index) is not int or not 0 <= index < total:
        raise ShardOptionError(f"a shard index must be an integer in 0..{total - 1}, got {index!r}")
    owners: dict = {}
    kept: List[_Item] = []
    dropped: List[_Item] = []
    for item in items:
        path = file_key(nodeid(item))
        if path not in owners:
            owners[path] = shard_of(path, total)
        (kept if owners[path] == index else dropped).append(item)
    return kept, dropped


def manifest_text(nodeids: Iterable[str]) -> str:
    """The manifest bytes' text: every node id, sorted, each followed by one LF (empty when none)."""
    rows = list(nodeids)
    for row in rows:
        if not isinstance(row, str) or not row or "\n" in row or "\r" in row:
            raise ShardOptionError(f"a node id cannot be written as one manifest row: {row!r}")
    return "".join(row + "\n" for row in sorted(rows))


def check_manifest_target(path: str) -> None:
    """Refuse a manifest path that already exists or whose directory does not: a manifest is written
    exactly once by the run that collected it, never over a stale file from another run."""
    if not isinstance(path, str) or not path:
        raise ShardOptionError(f"--atlas-shard-manifest needs a file path, got {path!r}")
    if os.path.lexists(path):
        raise ShardOptionError(f"--atlas-shard-manifest {path!r} already exists; it is written once")
    parent = os.path.dirname(os.path.abspath(path))
    if not os.path.isdir(parent):
        raise ShardOptionError(f"--atlas-shard-manifest {path!r}: directory {parent!r} does not exist")


def write_manifest(path: str, nodeids: Iterable[str]) -> None:
    """Write the manifest to a NEW file (exclusive create: an existing file is an error, not input)."""
    text = manifest_text(nodeids)
    with open(path, "x", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
