"""Protected-constraint memory tier — the *never-compressible* safety store (D12).

Decision D12 of ``docs/autonomous-brain-plan-v4-final-2026-07-06.md``: memory consolidation
("compression") silently deletes rare-but-vital facts over repeated passes — step 2 of the monthly
``.claude/scheduled-tasks/monthly-memory-consolidation`` skill literally "delete[s] facts that are
now wrong or superseded". A rarely-referenced *safety constraint* is exactly the kind of rare-but-
vital fact that pass can drop. So the non-negotiable guardrails get a **protected tier**: memory
entries the compression pass must retain verbatim, exempt from pruning and merging.

Two halves, both here:

* **The mechanism** — :func:`is_protected` (reads the ``protected: true`` / ``type: constraint``
  frontmatter marker) and :func:`compact_preserving_protected` (a *simulated* consolidation pass that
  applies any lossy retention policy to ordinary entries but ALWAYS keeps protected ones).
* **The guard** — :data:`CANONICAL_SAFETY_CONSTRAINTS` (the invariants that MUST be pinned, each an
  ASCII anchor that is a verbatim substring of the doctrine owner ``CLAUDE.md``) plus
  :func:`reconcile_constraints` / :func:`missing_protected`, so a dropped or drifted constraint is a
  RED test, never a silent loss.

Coverage-honest: absence is reported as absence — :func:`missing_protected` names what was lost; a
store that pins nothing yields the full unpinned list, never a green "ok". Pure stdlib, offline, no
egress, total on bad input.
"""
from __future__ import annotations

import dataclasses
import os
import re
from typing import Any, Callable, Dict, List, Optional

# The non-negotiable safety invariants that MUST survive every consolidation pass. Each is
# (id, anchor): `anchor` is a verbatim ASCII substring of the doctrine OWNER (CLAUDE.md guardrails),
# so the pinned set is mechanically reconciled against the owner and cannot silently drift from it.
# (ASCII anchors only — the doctrine's "proposer != verifier" uses a non-ASCII glyph, so we anchor on
# its adjacent prose instead.)
CANONICAL_SAFETY_CONSTRAINTS: List[tuple] = [
    ("SC1-read-only",         "Read-only by default"),
    ("SC1-no-device-writes",  "No writes to devices, ever"),
    ("SC2-proposer-verifier", "independent pass checks every consequential output"),
    ("SC3-coverage-honest",   "coverage-honest"),
    ("SC4-one-source",        "one source of truth"),
    ("SC5-no-egress",         "no-egress"),
    ("SC6-permission-mode",   "bypassPermissions"),
    ("SC7-human-pr-cab",      "PR + CAB"),
]

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.S)


@dataclasses.dataclass
class MemoryEntry:
    """One memory file: its slug ``name``, the ``body`` after the frontmatter, and the parsed
    ``meta`` mapping (top-level keys + a nested ``metadata`` block)."""
    name: str
    body: str
    meta: Dict[str, Any]

    @property
    def protected(self) -> bool:
        return is_protected(self.meta)


def _truthy(v: Any) -> bool:
    return v is True or (isinstance(v, str) and v.strip().lower() in ("true", "yes", "1", "on"))


def parse_frontmatter(text: str) -> Dict[str, Any]:
    """Parse a memory file's leading ``--- ... ---`` block into a dict. Handles top-level
    ``key: value`` and a single nested ``metadata:`` block (2-space-indented ``key: value``).
    Stdlib only (no YAML dependency — the MASTER_PLAN no-new-deps trap). Total: no frontmatter -> {}."""
    m = _FRONTMATTER_RE.match(text or "")
    if not m:
        return {}
    meta: Dict[str, Any] = {}
    nested_key: Optional[str] = None
    for line in m.group(1).splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indented = line[0] in " \t"
        if indented and nested_key:
            k, _, v = line.strip().partition(":")
            if _:
                meta.setdefault(nested_key, {})[k.strip()] = v.strip()
            continue
        k, sep, v = line.partition(":")
        if not sep:
            continue
        k, v = k.strip(), v.strip()
        if v == "":                       # a bare "metadata:" opens a nested block
            meta[k] = {}
            nested_key = k
        else:
            meta[k] = v
            nested_key = None
    return meta


def is_protected(meta: Dict[str, Any]) -> bool:
    """True iff this entry is in the protected tier: ``protected: true`` (top-level or under
    ``metadata``) or ``type: constraint``. Reading the marker, never guessing."""
    if not isinstance(meta, dict):
        return False
    md = meta.get("metadata") if isinstance(meta.get("metadata"), dict) else {}
    return (_truthy(meta.get("protected")) or _truthy(md.get("protected"))
            or str(meta.get("type") or md.get("type") or "").strip().lower() == "constraint")


def _is_protected_entry(e: Any) -> bool:
    if isinstance(e, MemoryEntry):
        return e.protected
    if isinstance(e, dict):
        return is_protected(e.get("meta", e))
    return False


def _name_of(e: Any) -> str:
    if isinstance(e, MemoryEntry):
        return e.name
    if isinstance(e, dict):
        return str(e.get("name") or (e.get("meta") or {}).get("name") or "")
    return ""


def load_entry(path: str) -> MemoryEntry:
    """Load one memory file into a MemoryEntry. Total: an unreadable file yields an empty entry
    (its ``name`` is the filename stem) rather than raising."""
    name = os.path.splitext(os.path.basename(path))[0]
    try:
        text = open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        return MemoryEntry(name=name, body="", meta={})
    m = _FRONTMATTER_RE.match(text)
    body = m.group(2) if m else text
    meta = parse_frontmatter(text)
    return MemoryEntry(name=meta.get("name") or name, body=body, meta=meta)


def load_store(memory_dir: str) -> List[MemoryEntry]:
    """Every memory file in ``memory_dir`` (excluding the ``MEMORY.md`` index), as MemoryEntry list.
    Total: a missing directory yields [] (coverage-honest — absence is absence, never an error)."""
    out: List[MemoryEntry] = []
    try:
        names = sorted(os.listdir(memory_dir))
    except OSError:
        return out
    for fn in names:
        if not fn.endswith(".md") or fn == "MEMORY.md":
            continue
        out.append(load_entry(os.path.join(memory_dir, fn)))
    return out


def compact_preserving_protected(entries: List[Any],
                                 keep: Optional[Callable[[Any], bool]] = None) -> List[Any]:
    """Simulate a memory-consolidation / compression pass. ``keep(entry) -> bool`` is the (lossy)
    retention policy for ORDINARY entries — the caller models "the consolidation decided to drop
    this" (default ``None`` keeps everything, a no-op pass). **Protected entries are ALWAYS retained
    verbatim**, exempt from the policy: that exemption is the never-compressible tier. Order-stable."""
    survivors: List[Any] = []
    for e in entries:
        if _is_protected_entry(e) or keep is None or keep(e):
            survivors.append(e)
    return survivors


def missing_protected(before: List[Any], after: List[Any]) -> List[str]:
    """Names of protected entries present in ``before`` but absent from ``after`` — i.e. safety
    constraints a compression pass DROPPED. Empty == the protected tier survived intact."""
    after_names = {_name_of(e) for e in after}
    return [_name_of(e) for e in before if _is_protected_entry(e) and _name_of(e) not in after_names]


def reconcile_constraints(doctrine_text: str) -> List[str]:
    """Canonical safety constraints whose anchor is NOT a verbatim substring of the doctrine owner
    (``CLAUDE.md``). Empty == every pinned constraint is still grounded in the doctrine (no drift)."""
    text = doctrine_text or ""
    return [f"{cid}: anchor {anchor!r} not found in the doctrine owner"
            for cid, anchor in CANONICAL_SAFETY_CONSTRAINTS if anchor not in text]


def unpinned_constraints(entries: List[Any]) -> List[str]:
    """Canonical constraint ids whose anchor is not covered by ANY protected entry's body — i.e.
    safety invariants the store fails to pin. Empty == the store pins every canonical constraint.
    Coverage-honest: a store with no protected entries returns the full list, never a green ok."""
    pinned = "\n".join(
        (e.body if isinstance(e, MemoryEntry) else str((e or {}).get("body", "")))
        for e in entries if _is_protected_entry(e))
    return [cid for cid, anchor in CANONICAL_SAFETY_CONSTRAINTS if anchor not in pinned]
