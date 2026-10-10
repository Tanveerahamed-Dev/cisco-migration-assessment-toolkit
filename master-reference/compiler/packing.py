"""Canonical compiler chunk packing: the one owner of records per chunk.

Every compiler record group is written as ``chunks/<group>/<index>.json``
envelopes. A group holds ``chunk_size`` records per chunk (the manifest's
shared ``chunk_size``, 2,000 by default) except the groups named in
``GROUP_CHUNK_RECORD_CAPS``, whose records per chunk are capped lower because
each record is large:

- ``source_text`` holds the full text of one file per record, so it packs one
  record per chunk.
- ``symbols`` records average about 12 KB. At 2,000 per chunk the largest
  ``symbols`` chunk reached 30,814,894 B, 91.83 % of the release intake's
  32 MiB per-file bound (W64c; capacity guard, Master reference run
  38015120458). At 500 per chunk it falls to about a quarter of that.

Packing is canonical: a group of ``n`` records has ``ceil(n / size)`` chunks,
every chunk but the last holds exactly ``size`` records, and ``size`` is
``effective_chunk_size(group, chunk_size)``. The manifest records only the
shared ``chunk_size``; the caps are part of the reader contract, so output
packed under an earlier rule (for example ``symbols`` at 2,000 per chunk) is
refused as non-canonical rather than accepted. Readers that enforce packing:

- ``compiler/compiler.py :: _write_success`` (the writer);
- ``release/compiler_bundle.py :: load_compiler_bundle`` (release intake);
- ``build/projection/build.mjs :: compilerEffectiveChunkSize`` (projection),
  which restates this table as ``COMPILER_GROUP_CHUNK_RECORD_CAPS``.
  ``tests/compiler/test_chunk_packing.py`` reads that restatement as text and
  requires it to equal this table.

``continuity/corpus.py`` and ``cli/capacity.py`` verify receipts and counts
but do not re-derive packing.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Mapping

# Highest records per chunk for the groups that pack below the shared
# ``chunk_size``. A group absent here packs at ``chunk_size``.
GROUP_CHUNK_RECORD_CAPS: Mapping[str, int] = MappingProxyType(
    {
        "source_text": 1,
        "symbols": 500,
    }
)


def effective_chunk_size(group: str, chunk_size: int) -> int:
    """Return the canonical records per chunk for ``group``.

    ``chunk_size`` is the manifest's shared records per chunk. A capped group
    packs at ``min(chunk_size, cap)``, so a smaller shared size still applies
    to it and every other group is unchanged.
    """

    if type(chunk_size) is not int or chunk_size < 1:
        raise ValueError("chunk_size must be a positive integer")
    cap = GROUP_CHUNK_RECORD_CAPS.get(group)
    return chunk_size if cap is None else min(chunk_size, cap)


__all__ = ["GROUP_CHUNK_RECORD_CAPS", "effective_chunk_size"]
