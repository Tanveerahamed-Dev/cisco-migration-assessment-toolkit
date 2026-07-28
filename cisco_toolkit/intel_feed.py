"""Intel-feed consumer — the NO-EGRESS half of Phase 5 "eyes" (the recall/advisory intake).

Phase 5 of ``docs/autonomous-brain-plan-v4-final-2026-07-06.md`` puts an egress-fenced research lane in a
separate worktree; it emits **frozen, Rule-3-sanitized, signed** ``docs/intel/feed-*.jsonl`` and the
air-gapped repo **consumes them read-only**. This module is that consumer — it does **no egress**: it reads,
provenance-verifies, and fleet-matches feeds the (gated) producer drops in. Building it now defines the
**contract the producer must meet** and closes the loop the Phase-4 nerve already anticipates
(:mod:`cisco_toolkit.self_healing` triggers on "an intel-feed PSIRT hit").

**The provenance gate is load-bearing** — it is where the no-egress invariant is enforced on intake. A feed
is consumed **only if**: (1) its first line is a manifest attesting ``sanitized: true`` (Rule-3), and (2) the
SHA-256 of the entry lines matches the manifest (tamper/corruption-evident), and (3) no configured forbidden
identifier appears despite the sanitized flag (defense-in-depth). Any failure → the feed is **refused**, with
the reason recorded — never silently half-consumed. "Only frozen sanitized signed artifacts cross in."

Coverage-honest: no feed files → "no intel feed (the egress research lane is not wired — gated)"; absence is
absence, never "no advisories affect the fleet". Pure-stdlib (``hashlib``); :func:`build_feed` is the writer
contract, so the consumer and the future producer sign/verify identically.
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from cisco_toolkit.textutils import forbidden_token_pattern as _forbidden_token_pattern

INTEL_DIR = os.path.join("docs", "intel")
_MANIFEST_KIND = "intel-feed-manifest"
# A token that is empty or all separators compiles to None. It must then match NOTHING — compiling
# "" instead would match at every position and refuse every feed.
_NEVER_MATCHES = re.compile(r"(?!)")


def _sha256_of(entry_lines: List[str]) -> str:
    """Hash over the exact entry-line strings (newline-terminated) — the same bytes the producer signs."""
    h = hashlib.sha256()
    for line in entry_lines:
        h.update(line.encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


def build_feed(entries: List[Dict[str, Any]], *, sanitized: bool = True,
               producer: str = "research-lane", generated: str = "") -> str:
    """Serialize a feed the way the (gated) producer must — a manifest line + one JSON advisory per line,
    signed by the SHA-256 of the entry lines. The consumer verifies against exactly this. Deterministic
    (sorted keys) so the signature is reproducible."""
    entry_lines = [json.dumps(e, ensure_ascii=True, sort_keys=True) for e in entries]
    manifest = {"kind": _MANIFEST_KIND, "sha256": _sha256_of(entry_lines), "sanitized": bool(sanitized),
                "producer": producer, "generated": generated, "n": len(entry_lines)}
    return "\n".join([json.dumps(manifest, ensure_ascii=True, sort_keys=True)] + entry_lines) + "\n"


def verify_feed(text: str, *, forbidden: Tuple[str, ...] = ()) -> Dict[str, Any]:
    """The provenance gate. Returns ``{ok, reason, manifest, entries}``. ``ok`` only when the feed is
    sanitized-attested, hash-intact, and free of forbidden identifiers — otherwise ``ok=False`` with the
    reason and **no entries** (a bad feed is refused whole, never partially consumed)."""
    lines = [ln for ln in (text or "").splitlines() if ln.strip()]
    if not lines:
        return {"ok": False, "reason": "empty feed", "manifest": None, "entries": []}
    try:
        manifest = json.loads(lines[0])
    except Exception:
        return {"ok": False, "reason": "unparseable manifest (first line)", "manifest": None, "entries": []}
    if not isinstance(manifest, dict) or manifest.get("kind") != _MANIFEST_KIND:
        return {"ok": False, "reason": "missing/invalid manifest header", "manifest": manifest, "entries": []}
    if manifest.get("sanitized") is not True:
        return {"ok": False, "reason": "feed not attested sanitized (Rule-3) — refused",
                "manifest": manifest, "entries": []}
    entry_lines = lines[1:]
    if _sha256_of(entry_lines) != manifest.get("sha256"):
        return {"ok": False, "reason": "content hash mismatch — tamper/corruption, refused",
                "manifest": manifest, "entries": []}
    # The CONSUMING half of the Rule-3 gate. This was a literal `t.lower() in blob`, which shared
    # the producing side's exact blind spots: an operator-supplied "Acme Bank" never matched the
    # device spelling ACME-BANK-CORE-01, and a whitespace-padded token from `--forbidden "A, B"` was
    # inert. Two gates, one blind spot, so the second could not catch what the first had missed.
    # Both now go through the one owner (cisco_toolkit.textutils.forbidden_token_pattern).
    blob = " ".join(entry_lines)
    hit = next((t for t in forbidden
                if t and (_forbidden_token_pattern(t) or _NEVER_MATCHES).search(blob)), None)
    if hit:
        return {"ok": False, "reason": f"forbidden identifier '{hit}' present despite sanitized flag — refused",
                "manifest": manifest, "entries": []}
    entries: List[Dict[str, Any]] = []
    for el in entry_lines:
        try:
            o = json.loads(el)
        except Exception:
            continue
        if isinstance(o, dict) and o.get("id"):
            entries.append(o)
    return {"ok": True, "reason": "verified (sanitized + hash-intact)", "manifest": manifest, "entries": entries}


def load_feeds(intel_dir: str = INTEL_DIR, *, forbidden: Tuple[str, ...] = ()) -> Dict[str, Any]:
    """Verify every ``feed-*.jsonl`` in ``intel_dir``. Returns verified advisories, the refused feeds (with
    reasons — surfaced, not hidden), and a coverage-honest note when there is no feed at all."""
    paths = sorted(glob.glob(os.path.join(intel_dir, "feed-*.jsonl")))
    advisories: List[Dict[str, Any]] = []
    refused: List[Dict[str, str]] = []
    for p in paths:
        try:
            text = open(p, encoding="utf-8").read()
        except OSError as e:
            refused.append({"feed": os.path.basename(p), "reason": f"unreadable: {e!r}"})
            continue
        res = verify_feed(text, forbidden=forbidden)
        if res["ok"]:
            for a in res["entries"]:
                a.setdefault("_feed", os.path.basename(p))
                advisories.append(a)
        else:
            refused.append({"feed": os.path.basename(p), "reason": res["reason"]})
    note = (f"{len(advisories)} advisory(ies) from {len(paths)} feed(s)"
            + (f"; {len(refused)} refused" if refused else "")) if paths else \
        "no intel feed (the egress research lane is not wired — gated; absence is absence, not 'no advisories')"
    return {"advisories": advisories, "refused": refused, "note": note, "n_feeds": len(paths)}


def fleet_platforms(snap: Any) -> Set[str]:
    """Best-effort set of platform strings present in the fleet (snap['devices'][*]['platform'])."""
    out: Set[str] = set()
    devices = snap.get("devices") if isinstance(snap, dict) else None
    if isinstance(devices, dict):
        for d in devices.values():
            if isinstance(d, dict) and d.get("platform"):
                out.add(str(d["platform"]))
    return out


def match_fleet(advisories: List[Dict[str, Any]], platforms: Set[str]) -> List[Dict[str, Any]]:
    """Advisories whose ``affected`` product/platform tokens intersect the fleet's platforms (case-insensitive
    substring either way). Each hit records which fleet platforms it matched. No platforms -> no hits (honest:
    we can't match without inventory, and we do not guess)."""
    hits: List[Dict[str, Any]] = []
    for a in advisories:
        affected = a.get("affected") or []
        if isinstance(affected, str):
            affected = [affected]
        matched = sorted({p for p in platforms
                          for tok in affected
                          if isinstance(tok, str) and (tok.lower() in p.lower() or p.lower() in tok.lower())})
        if matched:
            hits.append({**a, "matched_platforms": matched})
    return hits


def advisory_drift_items(hits: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Project matched advisories into :mod:`cisco_toolkit.self_healing`-shaped drift items (``kind`` =
    'advisory'), so a PSIRT hit flows into the same propose-only remediation loop as a snapshot regression."""
    sev_map = {"critical": "Critical", "high": "High", "medium": "Medium", "low": "Low"}
    items: List[Dict[str, Any]] = []
    for h in hits:
        sev = sev_map.get(str(h.get("severity", "")).lower(), "Medium")
        items.append({"kind": "advisory", "subject": h.get("id"), "severity": sev,
                      "detail": f"{h.get('title', h.get('id'))} — affects {', '.join(h.get('matched_platforms', []))}"
                                f" (source: {h.get('source', 'intel feed')})"})
    return items


def render(loaded: Dict[str, Any], hits: Optional[List[Dict[str, Any]]] = None) -> str:
    L = [f"Intel feed — {loaded['note']}"]
    for r in loaded["refused"]:
        L.append(f"  [REFUSED] {r['feed']}: {r['reason']}")
    if hits is not None:
        if hits:
            L.append(f"  {len(hits)} advisory(ies) affect the fleet:")
            for h in hits:
                L.append(f"    [{h.get('severity', '?')}] {h.get('id')} — {h.get('title', '')} "
                         f"({', '.join(h.get('matched_platforms', []))})")
        else:
            L.append("  no loaded advisory matches the fleet's platforms")
    return "\n".join(L)


def main(argv: List[str] = None) -> int:
    """CLI: ``python -m cisco_toolkit.intel_feed [--dir docs/intel] [<snapshot.json>]`` — verify the feeds
    and (if a snapshot is given) show which advisories affect the fleet. Read-only, no egress."""
    import sys
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    intel_dir = INTEL_DIR
    if "--dir" in argv:
        i = argv.index("--dir")
        intel_dir = argv[i + 1] if i + 1 < len(argv) else INTEL_DIR
    snap_path = next((a for a in argv if not a.startswith("-") and a != intel_dir), None)
    loaded = load_feeds(intel_dir)
    hits = None
    if snap_path:
        try:
            snap = json.load(open(snap_path, encoding="utf-8"))
            hits = match_fleet(loaded["advisories"], fleet_platforms(snap))
        except Exception as e:
            print(f"could not read snapshot: {e!r}")
    print(render(loaded, hits))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
