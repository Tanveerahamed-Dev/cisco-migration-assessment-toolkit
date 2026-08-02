"""Intel-feed consumer — the NO-EGRESS half of Phase 5 "eyes" (the recall/advisory intake).

Phase 5 of ``docs/autonomous-brain-plan-v4-final-2026-07-06.md`` puts an egress-fenced research lane in a
separate worktree; it emits **frozen, Rule-3-sanitized, hash-sealed** ``docs/intel/feed-*.jsonl`` and the
air-gapped repo **consumes them read-only**. This module is that consumer — it does **no egress**: it reads,
integrity-checks, and fleet-matches feeds the gated producer drops in. Building it defines the
**contract the producer must meet** and closes the loop the Phase-4 nerve already anticipates
(:mod:`cisco_toolkit.self_healing` triggers on "an intel-feed PSIRT hit").

**The intake gate is load-bearing.** A feed is consumed **only if**: (1) its first line records
``sanitized: true`` (Rule-3), (2) the
SHA-256 of the entry lines matches the manifest (tamper/corruption-evident), and (3) no configured forbidden
identifier appears despite the sanitized flag (defense-in-depth). Any failure → the feed is **refused**, with
the reason recorded — never silently half-consumed. The unkeyed hash establishes neither origin nor
authenticity; version-2 manifests therefore state ``authentication: none`` explicitly.

Coverage-honest: no feed files means no feed is present, never "no advisories affect the fleet".
Pure-stdlib (``hashlib``); :func:`build_feed` is the deterministic writer contract shared with the producer.
"""
from __future__ import annotations

import glob
import hashlib
import ipaddress
import json
import os
import re
import stat
import unicodedata
from typing import Any, Dict, List, Optional, Set, Tuple

from cisco_toolkit.textutils import forbidden_token_pattern as _forbidden_token_pattern

INTEL_DIR = os.path.join("docs", "intel")
_MANIFEST_KIND = "intel-feed-manifest"
_MANIFEST_VERSION = 2
_MAX_FEED_BYTES = 32 * 1024 * 1024
_MAX_FEED_FILES = 100
_MAX_FEED_TOTAL_BYTES = 64 * 1024 * 1024
# A token that is empty or all separators compiles to None. It must then match NOTHING — compiling
# "" instead would match at every position and refuse every feed.
_NEVER_MATCHES = re.compile(r"(?!)")
_IPV4_CANDIDATE_RE = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
_IPV6_CANDIDATE_RE = re.compile(
    r"(?<![:.\w])(?=[0-9A-Fa-f:]*::|(?:[0-9A-Fa-f]{1,4}:){7})"
    r"[0-9A-Fa-f:]{2,45}(?![:.\w])"
)
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_MAC_RE = re.compile(
    r"(?<![0-9A-Fa-f])(?:"
    r"[0-9A-Fa-f]{2}(?P<sep>[:-])"
    r"[0-9A-Fa-f]{2}(?P=sep)[0-9A-Fa-f]{2}(?P=sep)"
    r"[0-9A-Fa-f]{2}(?P=sep)[0-9A-Fa-f]{2}(?P=sep)[0-9A-Fa-f]{2}"
    r"|(?:[0-9A-Fa-f]{4}\.){2}[0-9A-Fa-f]{4}"
    r")(?![0-9A-Fa-f])"
)
_SERIAL_RE = re.compile(r"\b[A-Z]{3}[0-9]{4}[0-9A-Z]{4}\b", re.IGNORECASE)


def _read_feed_text(path: str) -> Tuple[str, int]:
    """Read one bounded regular feed while pinning its filesystem identity.

    A size-check followed by ``open(path)`` has a check/use window and follows
    symlinks or Windows reparse points. Feed files are an intake boundary, so
    they receive the same non-link/same-file treatment as vault digests and run
    manifests.
    """
    before = os.lstat(path)
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)

    def unsafe(file_stat: os.stat_result) -> bool:
        return (
            stat.S_ISLNK(file_stat.st_mode)
            or bool(reparse and getattr(file_stat, "st_file_attributes", 0) & reparse)
            or not stat.S_ISREG(file_stat.st_mode)
        )

    if unsafe(before):
        raise ValueError("feed path is not a regular non-link file")
    if before.st_size > _MAX_FEED_BYTES:
        raise ValueError(f"file exceeds the {_MAX_FEED_BYTES}-byte intake limit")

    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        opened = os.fstat(fd)
        after = os.lstat(path)
        if (
            unsafe(opened)
            or unsafe(after)
            or (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino)
            or (after.st_dev, after.st_ino) != (opened.st_dev, opened.st_ino)
        ):
            raise ValueError("feed file identity changed during verification")
        with os.fdopen(fd, "rb") as handle:
            fd = -1
            raw = handle.read(_MAX_FEED_BYTES + 1)
    finally:
        if fd >= 0:
            os.close(fd)
    if len(raw) > _MAX_FEED_BYTES:
        raise ValueError(f"file exceeds the {_MAX_FEED_BYTES}-byte intake limit")
    return raw.decode("utf-8"), len(raw)


def _sha256_of(entry_lines: List[str]) -> str:
    """Hash the deterministic entry-line representation used by both sides."""
    h = hashlib.sha256()
    for line in entry_lines:
        h.update(line.encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


def _strict_json(line: str, *, label: str) -> Any:
    """Decode one JSON line while rejecting duplicate keys and non-finite numbers."""
    def object_pairs(pairs):
        out = {}
        for key, value in pairs:
            if key in out:
                raise ValueError(f"{label} contains duplicate key {key!r}")
            out[key] = value
        return out

    def reject_constant(value):
        raise ValueError(f"{label} contains non-standard JSON constant {value}")

    try:
        return json.loads(
            line,
            object_pairs_hook=object_pairs,
            parse_constant=reject_constant,
        )
    except RecursionError as exc:
        # `json.loads` raises RecursionError on deeply nested input, and RecursionError is NOT a
        # ValueError — so it escaped the tuple below and propagated out of `load_feeds`, which calls
        # `verify_feed` outside any try. Measured: ONE hostile file in the feed directory aborted the
        # whole intake with a traceback, and the sibling GOOD feed was never consumed. Depth limits
        # cannot help: they are checked after the parse. Converted to the same ValueError this
        # function raises for every other malformed input, so a bad file is REPORTED, not fatal.
        raise ValueError(f"{label} is nested too deeply to parse safely: {exc}") from exc
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ValueError(f"{label} is not strict JSON: {exc}") from exc


def _walk_strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _walk_strings(item)
    elif isinstance(value, dict):
        for key, item in value.items():
            yield str(key)
            yield from _walk_strings(item)


def _fold_for_matching(value: str) -> str:
    """NFKC-normalise and drop invisible format characters, for MATCHING only.

    This gate exists to catch what the producer missed, so a spelling the producer's redactor cannot
    see must not also be invisible here — otherwise "independent of producer claims" is only true of
    the token LIST, never of the matching itself. Measured before this: an advisory carrying
    ``10.0.0<U+FF0E>5``, ``FDO2145<ZWSP>A1BC`` and ``bob@ac<ZWSP>me.example`` was reported clean by
    BOTH sides, while the byte-identical ASCII form was redacted six times over. Ordinary
    provenance — Word paste, a wrapped terminal, a CJK IME — not a crafted attack.

    NFKC folds fullwidth forms onto ASCII (``＠``→``@``, ``．``→``.``, ``：``→``:``); the `Cf` sweep
    removes ZWSP/ZWNJ/ZWJ/word-joiner/soft-hyphen, which render as nothing and split an identifier
    without a reader ever seeing it. Applied to a SHADOW copy: nothing stored or emitted changes,
    the only effect is that more input is REFUSED. Deliberately one-directional — this gate may
    over-refuse (a refusal is loud and recoverable), never under-refuse.
    """
    folded = unicodedata.normalize("NFKC", value)
    return "".join(ch for ch in folded if unicodedata.category(ch) != "Cf")


def _standard_identifier_hit(values: List[str]) -> Optional[Tuple[str, str]]:
    """Find a standard client-resolving identifier independently of producer claims."""
    # Check the folded spelling ALONGSIDE the original: an identifier hidden by invisible characters
    # is still an identifier, and the original is kept so a hit reports what actually appears.
    values = [v for value in values for v in (value, _fold_for_matching(value))]
    for value in values:
        for label, pattern in (
            ("email address", _EMAIL_RE),
            ("MAC address", _MAC_RE),
            ("chassis serial", _SERIAL_RE),
        ):
            match = pattern.search(value)
            if match:
                return label, match.group(0)
        for match in _IPV4_CANDIDATE_RE.finditer(value):
            try:
                ipaddress.IPv4Address(match.group(0))
            except ValueError:
                continue
            return "IPv4 address", match.group(0)
        for match in _IPV6_CANDIDATE_RE.finditer(value):
            try:
                ipaddress.IPv6Address(match.group(0))
            except ValueError:
                continue
            return "IPv6 address", match.group(0)
    return None


def build_feed(entries: List[Dict[str, Any]], *, sanitized: bool = True,
               producer: str = "research-lane", generated: str = "") -> str:
    """Serialize a deterministic, hash-sealed feed envelope.

    The SHA-256 digest detects accidental entry corruption; it is deliberately
    labelled ``authentication: none`` because an unkeyed digest is not a digital
    signature and does not prove who produced the feed.
    """
    if not isinstance(entries, list):
        raise ValueError("feed entries must be a list")
    entry_lines: List[str] = []
    seen_ids = set()
    for index, entry in enumerate(entries, 1):
        if not isinstance(entry, dict):
            raise ValueError(f"feed entry {index} is not an object")
        entry_id = entry.get("id")
        if not isinstance(entry_id, str) or not entry_id.strip():
            raise ValueError(f"feed entry {index} has no non-empty string id")
        if entry_id in seen_ids:
            raise ValueError(f"feed contains duplicate advisory id {entry_id!r}")
        seen_ids.add(entry_id)
        entry_lines.append(
            json.dumps(
                entry,
                ensure_ascii=True,
                sort_keys=True,
                allow_nan=False,
                separators=(",", ":"),
            )
        )
    manifest = {
        "kind": _MANIFEST_KIND,
        "manifest_version": _MANIFEST_VERSION,
        "integrity": "sha256",
        "hash_scope": "entry-lines",
        "authentication": "none",
        "sha256": _sha256_of(entry_lines),
        "sanitized": bool(sanitized),
        "producer": str(producer),
        "generated": str(generated),
        "n": len(entry_lines),
    }
    return "\n".join([json.dumps(manifest, ensure_ascii=True, sort_keys=True)] + entry_lines) + "\n"


def verify_feed(
    text: str,
    *,
    forbidden: Tuple[str, ...] = (),
    require_forbidden: bool = False,
) -> Dict[str, Any]:
    """The intake-integrity gate. Returns ``{ok, reason, manifest, entries}``. ``ok`` only when the feed has
    a sanitization claim, an intact entry hash, and no forbidden identifiers — otherwise ``ok=False`` with the
    reason and **no entries** (a bad feed is refused whole, never partially consumed)."""
    lines = (text or "").splitlines()
    if not lines:
        return {"ok": False, "reason": "empty feed", "manifest": None, "entries": []}
    if any(not line.strip() for line in lines):
        return {"ok": False, "reason": "blank JSONL line refused", "manifest": None, "entries": []}
    try:
        manifest = _strict_json(lines[0], label="manifest")
    except ValueError as exc:
        return {
            "ok": False,
            "reason": f"unparseable manifest (first line): {exc}",
            "manifest": None,
            "entries": [],
        }
    if not isinstance(manifest, dict) or manifest.get("kind") != _MANIFEST_KIND:
        return {"ok": False, "reason": "missing/invalid manifest header", "manifest": manifest, "entries": []}
    version = manifest.get("manifest_version")
    legacy_manifest = version is None
    if not legacy_manifest:
        if type(version) is not int or version != _MANIFEST_VERSION:
            return {"ok": False, "reason": f"unsupported manifest version {version!r}",
                    "manifest": manifest, "entries": []}
        expected_contract = {
            "integrity": "sha256",
            "hash_scope": "entry-lines",
            "authentication": "none",
        }
        for field, expected in expected_contract.items():
            if manifest.get(field) != expected:
                return {"ok": False, "reason": f"invalid manifest {field} contract",
                        "manifest": manifest, "entries": []}
    if manifest.get("sanitized") is not True:
        return {"ok": False, "reason": "feed not attested sanitized (Rule-3) — refused",
                "manifest": manifest, "entries": []}
    entry_lines = lines[1:]
    if type(manifest.get("n")) is not int or manifest.get("n") < 0:
        return {"ok": False, "reason": "manifest entry count is not a non-negative integer",
                "manifest": manifest, "entries": []}
    if manifest.get("n") != len(entry_lines):
        return {"ok": False, "reason": "manifest entry count mismatch; refused",
                "manifest": manifest, "entries": []}
    expected_hash = manifest.get("sha256")
    if (
        not isinstance(expected_hash, str)
        or not re.fullmatch(r"[0-9a-f]{64}", expected_hash)
        or _sha256_of(entry_lines) != expected_hash
    ):
        return {"ok": False, "reason": "content hash mismatch — tamper/corruption, refused",
                "manifest": manifest, "entries": []}
    entries: List[Dict[str, Any]] = []
    seen_ids = set()
    for index, el in enumerate(entry_lines, 1):
        try:
            o = _strict_json(el, label=f"entry {index}")
        except ValueError as exc:
            return {"ok": False, "reason": str(exc), "manifest": manifest, "entries": []}
        if not isinstance(o, dict) or not isinstance(o.get("id"), str) or not o["id"].strip():
            return {"ok": False, "reason": f"entry {index} is not an advisory object with a string id",
                    "manifest": manifest, "entries": []}
        if o["id"] in seen_ids:
            return {"ok": False, "reason": f"duplicate advisory id {o['id']!r}; refused",
                    "manifest": manifest, "entries": []}
        seen_ids.add(o["id"])
        entries.append(o)

    # The CONSUMING half of the Rule-3 gate. This was a literal `t.lower() in blob`, which shared
    # the producing side's exact blind spots: an operator-supplied "Acme Bank" never matched the
    # device spelling ACME-BANK-CORE-01, and a whitespace-padded token from `--forbidden "A, B"` was
    # inert. Two gates, one blind spot, so the second could not catch what the first had missed.
    # Both now go through the one owner (cisco_toolkit.textutils.forbidden_token_pattern).
    decoded_strings = list(_walk_strings(manifest))
    for entry in entries:
        decoded_strings.extend(_walk_strings(entry))
    standard_hit = _standard_identifier_hit(decoded_strings)
    if standard_hit:
        kind, literal = standard_hit
        return {
            "ok": False,
            "reason": (
                f"standard client identifier ({kind}: {literal!r}) present despite "
                "sanitized flag - refused"
            ),
            "manifest": manifest,
            "entries": [],
        }
    effective_forbidden = tuple(
        token for token in forbidden if _forbidden_token_pattern(token) is not None
    )
    if require_forbidden and not effective_forbidden:
        return {
            "ok": False,
            "reason": (
                "engagement-specific denylist is required for this intake but no usable "
                "client/site/device identifier was supplied"
            ),
            "manifest": manifest,
            "entries": [],
        }
    hit = next(
        (
            token
            for token in effective_forbidden
            if token
            and any(
                (_forbidden_token_pattern(token) or _NEVER_MATCHES).search(value)
                for value in decoded_strings
            )
        ),
        None,
    )
    if hit:
        return {"ok": False, "reason": f"forbidden identifier '{hit}' present despite sanitized flag — refused",
                "manifest": manifest, "entries": []}
    return {
        "ok": True,
        "reason": (
            "verified (sanitization claim + entry hash intact; source authenticity not established)"
        ),
        "manifest": manifest,
        "entries": entries,
        "authenticated": False,
        "legacy_manifest": legacy_manifest,
        "denylist_enforced": bool(effective_forbidden),
    }


def load_feeds(
    intel_dir: str = INTEL_DIR,
    *,
    forbidden: Tuple[str, ...] = (),
    require_forbidden: bool = False,
) -> Dict[str, Any]:
    """Verify every ``feed-*.jsonl`` in ``intel_dir``. Returns verified advisories, the refused feeds (with
    reasons — surfaced, not hidden), and a coverage-honest note when there is no feed at all."""
    paths = sorted(glob.glob(os.path.join(intel_dir, "feed-*.jsonl")))
    advisories: List[Dict[str, Any]] = []
    refused: List[Dict[str, str]] = []
    verified_feeds: List[Tuple[str, List[Dict[str, Any]]]] = []
    total_bytes = 0
    if len(paths) > _MAX_FEED_FILES:
        reason = (
            f"{len(paths)} feed files exceed the {_MAX_FEED_FILES}-file intake limit; "
            "refused whole"
        )
        return {
            "advisories": [],
            "refused": [{"feed": "*", "reason": reason}],
            "note": reason,
            "n_feeds": len(paths),
        }
    for p in paths:
        try:
            text, byte_count = _read_feed_text(p)
        except (OSError, UnicodeError, ValueError) as e:
            refused.append({"feed": os.path.basename(p), "reason": f"unreadable: {e!r}"})
            continue
        total_bytes += byte_count
        if total_bytes > _MAX_FEED_TOTAL_BYTES:
            reason = (
                "aggregate feeds exceed the "
                f"{_MAX_FEED_TOTAL_BYTES}-byte intake limit; refused whole"
            )
            return {
                "advisories": [],
                "refused": [*refused, {"feed": "*", "reason": reason}],
                "note": reason,
                "n_feeds": len(paths),
            }
        res = verify_feed(
            text,
            forbidden=forbidden,
            require_forbidden=require_forbidden,
        )
        if res["ok"]:
            verified_feeds.append((os.path.basename(p), res["entries"]))
        else:
            refused.append({"feed": os.path.basename(p), "reason": res["reason"]})
    id_sources: Dict[str, List[str]] = {}
    for feed_name, entries in verified_feeds:
        for entry in entries:
            id_sources.setdefault(entry["id"], []).append(feed_name)
    conflicting = {
        feed_name
        for sources in id_sources.values()
        if len(sources) > 1
        for feed_name in sources
    }
    conflict_ids_by_feed: Dict[str, List[str]] = {}
    for advisory_id, sources in id_sources.items():
        if len(sources) > 1:
            for feed_name in sources:
                conflict_ids_by_feed.setdefault(feed_name, []).append(advisory_id)
    for feed_name, entries in verified_feeds:
        if feed_name in conflicting:
            identifiers = ", ".join(sorted(conflict_ids_by_feed[feed_name])[:5])
            refused.append({
                "feed": feed_name,
                "reason": (
                    "duplicate advisory id across feed files; ambiguous feeds refused whole: "
                    + identifiers
                ),
            })
            continue
        for entry in entries:
            advisories.append({**entry, "_feed": feed_name})
    note = (f"{len(advisories)} advisory(ies) from {len(paths)} feed(s)"
            + (f"; {len(refused)} refused" if refused else "")) if paths else \
        "no intel feed present (absence is absence, not 'no advisories')"
    return {"advisories": advisories, "refused": refused, "note": note, "n_feeds": len(paths)}


def engagement_identifiers(*values: Any) -> Tuple[str, ...]:
    """Derive the explicit client/site/device denylist available in engagement inputs.

    This intentionally does not treat every string as an identifier: platform names and advisory
    terms are expected to occur in a public feed.  Device-map keys and fields explicitly named as
    host/client/customer/site identifiers are the privacy boundary.
    """
    found = set()
    identifier_keys = {
        "client",
        "client_name",
        "customer",
        "customer_name",
        "device",
        "device_name",
        "host",
        "hostname",
        "site",
        "site_name",
    }

    def add(value: Any) -> None:
        if isinstance(value, str):
            token = value.strip()
            if (
                len(token) >= 2
                and token.lower() not in {"unknown", "(unknown)", "n/a", "none"}
                and _forbidden_token_pattern(token) is not None
            ):
                found.add(token)

    def walk(value: Any, parent_key: str = "") -> None:
        if isinstance(value, dict):
            if parent_key.lower() == "devices":
                for device_key in value:
                    add(str(device_key))
            for key, item in value.items():
                normalized = str(key).strip().lower().replace("-", "_")
                if normalized in identifier_keys:
                    if isinstance(item, list):
                        for member in item:
                            add(member)
                    else:
                        add(item)
                walk(item, normalized)
        elif isinstance(value, list):
            for item in value:
                walk(item, parent_key)

    for value in values:
        walk(value)
    return tuple(sorted(found, key=lambda item: item.casefold()))


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
    hits = None
    snap = None
    if snap_path:
        try:
            with open(snap_path, encoding="utf-8") as handle:
                snap = json.load(handle)
        except Exception as e:
            print(f"could not read snapshot: {e!r}")
            return 2
    denylist = engagement_identifiers(snap) if snap is not None else ()
    loaded = load_feeds(
        intel_dir,
        forbidden=denylist,
        require_forbidden=snap is not None,
    )
    if snap is not None:
        hits = match_fleet(loaded["advisories"], fleet_platforms(snap))
    print(render(loaded, hits))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
