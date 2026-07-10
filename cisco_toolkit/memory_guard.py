"""Protected-constraint memory tier — the *never-compressible* safety store (D12).

Decision D12 of ``docs/autonomous-brain-plan-v4-final-2026-07-06.md``: memory consolidation
("compression") silently deletes rare-but-vital facts over repeated passes — the consolidation
skill (the out-of-repo ``anthropic-skills:consolidate-memory`` plugin) literally "delete[s] facts
that are now wrong or superseded". A rarely-referenced *safety constraint* is exactly the kind of rare-but-
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

Plus **the runtime arms** (P0-1 / DEC-005): store resolution (:func:`resolve_store_dir` — one owner,
shared with ``selfcheck.check_protected_artifact``) and the pre/post-consolidation wrapper
(:func:`snapshot_store` / :func:`verify_snapshot` + the ``snapshot|verify`` CLI), so a LIVE
consolidation pass — which runs out-of-repo and never routes through
:func:`compact_preserving_protected` — is bracketed by a mechanical before/after reconcile.

Coverage-honest: absence is reported as absence — :func:`missing_protected` names what was lost; a
store that pins nothing yields the full unpinned list, never a green "ok"; a vacuous baseline is
refused, never verified. Pure stdlib, offline, no egress, total on bad input.
"""
from __future__ import annotations

import dataclasses
import hashlib
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


# --- the runtime arms (P0-1 / DEC-005; gap G-001, evidence BLK-1) ---------------------------------
# The real store lives OUTSIDE the repo (Claude Code auto-memory for this project), so its location
# cannot be derived from the repo root: the known per-machine path is pinned literally BY DESIGN,
# $AGENT_MEMORY_DIR relocates it on any other machine, and every consumer (selfcheck's
# check_protected_artifact, the snapshot/verify wrapper below) resolves through here — one owner.
PROTECTED_ARTIFACT = "protected-constraints.md"
AGENT_MEMORY_DIR_ENV = "AGENT_MEMORY_DIR"
DEFAULT_AGENT_MEMORY_DIR = r"C:\Users\jajch\.claude\projects\C--Users-jajch-Desktop-Enhancements\memory"


def resolve_store_dir(explicit: Optional[str] = None) -> str:
    """The agent-memory store location: explicit arg > ``$AGENT_MEMORY_DIR`` > the known per-machine
    path. Pure resolution — existence is the CALLER's coverage-honest signal to report."""
    return explicit or os.environ.get(AGENT_MEMORY_DIR_ENV) or DEFAULT_AGENT_MEMORY_DIR


def _sha256_file(path: str) -> Optional[str]:
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return None


def snapshot_store(memory_dir: Optional[str] = None) -> Dict[str, Any]:
    """PRE-consolidation baseline (first half of the DEC-005 wrapper): every memory file's name,
    protected flag and full-file sha256 — D12 demands protected entries survive *verbatim*, so the
    hash pins rewrites (including a frontmatter flip), not just deletions. Total: an absent store
    yields ``store_present: False``, which :func:`verify_snapshot` REFUSES as vacuous — a baseline
    of nothing must never become a green verify."""
    mdir = resolve_store_dir(memory_dir)
    snap: Dict[str, Any] = {"store": mdir, "store_present": os.path.isdir(mdir), "entries": []}
    if not snap["store_present"]:
        return snap
    try:
        names = sorted(os.listdir(mdir))
    except OSError:
        snap["store_present"] = False
        return snap
    for fn in names:
        if not fn.endswith(".md") or fn == "MEMORY.md":
            continue
        path = os.path.join(mdir, fn)
        e = load_entry(path)
        snap["entries"].append({"name": e.name, "file": fn,
                                "protected": e.protected, "sha256": _sha256_file(path)})
    return snap


def verify_snapshot(before: Dict[str, Any], memory_dir: Optional[str] = None) -> Dict[str, Any]:
    """POST-consolidation check (second half of the wrapper): reconcile the live store against the
    pre-pass baseline. Failures are NAMED, never silent — ``dropped``: protected entries gone
    (:func:`missing_protected`, the guard's own loss detector); ``rewritten``: protected files whose
    bytes changed (a D12 verbatim violation); ``unpinned``: canonical anchors no longer pinned by any
    protected entry after the pass; ``unindexed``: surviving protected files MEMORY.md no longer
    references (an index prune orphans them from session-start re-surfacing — BLK-1 route d).
    ``vacuous``: the baseline itself pinned nothing (or had no store) — REFUSED, not a pass.
    Ordinary entries may be freely compressed; only the protected tier is judged. ``ok`` iff clean."""
    before = before or {}
    baseline = [e for e in (before.get("entries") or []) if isinstance(e, dict)]
    protected_before = [e for e in baseline if _truthy(e.get("protected"))]
    mdir = resolve_store_dir(memory_dir or before.get("store"))
    out: Dict[str, Any] = {"store": mdir, "dropped": [], "rewritten": [], "unpinned": [],
                           "unindexed": [], "vacuous": False, "ok": False}
    if not before.get("store_present") or not protected_before:
        out["vacuous"] = True          # nothing was pinned at baseline: refusing beats a vacuous green
        return out
    after = load_store(mdir)
    out["dropped"] = missing_protected(baseline, after)
    for e in protected_before:
        if e.get("name") in out["dropped"]:
            continue                   # already reported as dropped, not rewritten
        if _sha256_file(os.path.join(mdir, str(e.get("file") or ""))) != e.get("sha256"):
            out["rewritten"].append(e.get("name"))
    out["unpinned"] = unpinned_constraints(after)
    try:
        idx = open(os.path.join(mdir, "MEMORY.md"), encoding="utf-8", errors="replace").read()
    except OSError:
        idx = ""
    out["unindexed"] = [e.get("name") for e in protected_before
                        if e.get("name") not in out["dropped"] and str(e.get("file")) not in idx]
    out["ok"] = not (out["dropped"] or out["rewritten"] or out["unpinned"] or out["unindexed"])
    return out


def main(argv: Optional[List[str]] = None) -> int:
    """CLI — the DEC-005 pre/post-consolidation wrapper. Bracket ANY memory-consolidation pass:

        python -m cisco_toolkit.memory_guard snapshot [--store DIR] [--out FILE]
        ... run the consolidation ...
        python -m cisco_toolkit.memory_guard verify BASELINE.json [--store DIR]

    Exit 0 = protected tier intact; 4 = loss/drift/vacuous baseline (matches selfcheck's RED)."""
    import argparse
    import json
    import sys
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(prog="python -m cisco_toolkit.memory_guard")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("snapshot", help="record the pre-consolidation baseline")
    s.add_argument("--store", help="store dir (default: $AGENT_MEMORY_DIR or the known location)")
    s.add_argument("--out", help="write the baseline JSON here (default: stdout)")
    v = sub.add_parser("verify", help="reconcile the live store against a baseline")
    v.add_argument("baseline", help="baseline JSON written by `snapshot`")
    v.add_argument("--store", help="store dir (default: the baseline's recorded store)")
    a = ap.parse_args(argv)
    if a.cmd == "snapshot":
        snap = snapshot_store(a.store)
        text = json.dumps(snap, indent=1)
        if a.out:
            with open(a.out, "w", encoding="utf-8") as f:
                f.write(text)
        else:
            print(text)
        if not snap["store_present"]:
            print(f"[RED] store absent at {snap['store']} — nothing to guard (baseline is vacuous)",
                  file=sys.stderr)
            return 4
        n_prot = sum(1 for e in snap["entries"] if e["protected"])
        print(f"[OK ] baseline: {len(snap['entries'])} entr(ies), {n_prot} protected — {snap['store']}",
              file=sys.stderr)
        if not n_prot:
            print("[RED] baseline pins NO protected entries — a later verify would be vacuous",
                  file=sys.stderr)
            return 4
        return 0
    try:
        with open(a.baseline, encoding="utf-8") as f:
            before = json.load(f)
    except (OSError, ValueError) as e:
        print(f"[RED] cannot read baseline {a.baseline}: {e!r}", file=sys.stderr)
        return 4
    rep = verify_snapshot(before, a.store)
    if rep["vacuous"]:
        print("[RED] vacuous baseline (no store / nothing protected at snapshot time) — refused, not a pass",
              file=sys.stderr)
        return 4
    for key, label in (("dropped", "protected entries DROPPED"),
                       ("rewritten", "protected entries REWRITTEN (D12 verbatim violated)"),
                       ("unpinned", "canonical anchors UNPINNED after the pass"),
                       ("unindexed", "MEMORY.md index lost (orphaned from re-surfacing)")):
        if rep[key]:
            print(f"[RED] {label}: {', '.join(str(x) for x in rep[key])}", file=sys.stderr)
    if rep["ok"]:
        print(f"[OK ] protected tier survived the pass verbatim — {rep['store']}", file=sys.stderr)
        return 0
    return 4


if __name__ == "__main__":
    raise SystemExit(main())
