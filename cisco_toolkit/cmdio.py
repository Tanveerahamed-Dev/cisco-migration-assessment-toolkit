"""Command-output I/O glue: load a collected show-command's output from disk
(skipping empty/error captures via _CISCO_ERRORS) and run section parsers
fail-soft. Leaf layer: depends only on stdlib (os, logging, threading, typing).
Extracted verbatim from COLLECT_PARSE_V3_23_0.py in PHASE 2.7 step 14 (behaviour
byte-identical). This is the helper nearly every build_* / compute_* / write_*
leans on to read collected output, so it's homed before the I/O-fed analyze
functions move.

Zero-parse yield telemetry (Plan A / Tier-1 #3) also lives here, at the one
chokepoint every builder already goes through. The #1 recurring bug class: an
unseen platform variant parses to []/{} — byte-identical to "feature absent"
everywhere downstream (a real NX-OS ubest/mbest RIB once zeroed this way and
survived four audit waves). The ledger records every parser call whose input had
REAL CONTENT but whose output carried 0 entities. Coverage-honest by design: an
event means "collected-but-unparsed evidence — possible parser format gap",
NEVER a device state verdict; absent / error captures are the Collection
Completeness axis's domain and are not counted here."""
import logging
import os
import threading
from typing import Dict, List

logger = logging.getLogger(__name__)

_CISCO_ERRORS = (
    "% invalid", "% command not found",
    "% incomplete command", "% unknown command",
    "% ambiguous command", "% ip routing not enabled",
    "% routing not enabled", "invalid input detected",
    "error: invalid", "% requires vrf", "% vrf does not exist",
)

# --- zero-parse yield ledger ------------------------------------------------------
MIN_CONTENT_LINES = 3      # a 1-2 line banner / prompt echo is not "content" ...
MIN_CONTENT_CHARS = 200    # ... but a single-line controller-REST JSON blob is
_YIELD_EVENT_CAP = 500     # verbatim events kept; counters always keep the full truth

# Parsers for which zero-entities-on-real-content is a NORMAL healthy state. Their
# events stay visible in the ledger but OUT of the suspect count, so the red row never
# cries wolf. Two classes, seeded empirically from the synthetic-fixture run:
MAY_BE_EMPTY_PARSERS = frozenset({
    # 1) run-config-scoped parsers: a running-config always has CONTENT, but the specific
    #    feature section (ACLs / NAT / object-groups / redistribution / hygiene or
    #    hardening findings) is legitimately absent on many healthy devices — zero out of
    #    a real config is not a format-gap signal by itself. (parse_run_config_interfaces
    #    is deliberately NOT here: every real config has interface blocks, so zero IS
    #    suspect for it.)
    "parse_acls", "parse_object_groups", "parse_nat", "parse_security",
    "parse_config_hygiene", "parse_redistribution",
    # 2) state commands that print a header / legend even when empty-healthy:
    "parse_spanning_tree_blockedports",   # no blocked ports is the healthy state
    "parse_acl_hitcounts",                # ACLs defined but never matched print 0 rows
    "parse_policymap_drops",              # zero egress drops is the goal state
    "parse_copp_drops",                   # zero CoPP drops likewise
    "parse_igmp_groups",                  # no receivers joined is normal off-hours
})

_YIELD_LOCK = threading.Lock()
_PER_PARSER: Dict[str, Dict[str, int]] = {}
_EVENTS: List[dict] = []
_EVENTS_TRUNCATED = False
_TL = threading.local()    # .last_load = (cmd, path, chars, lines) — load→parse pairing

_UNATTRIBUTED = "[unattributed]"


def reset_parse_ledger() -> None:
    """Start-of-run reset (also clears this thread's pairing stash)."""
    global _EVENTS_TRUNCATED
    with _YIELD_LOCK:
        _PER_PARSER.clear()
        _EVENTS.clear()
        _EVENTS_TRUNCATED = False
    if hasattr(_TL, "last_load"):
        del _TL.last_load


def parse_yield_report() -> dict:
    """The deterministic, snapshot-ready ledger view (published as snap['parse_yield']).
    Wording is deliberately coverage-honest — see the module docstring."""
    with _YIELD_LOCK:
        per_parser = {
            name: dict(counts, may_be_empty=(name in MAY_BE_EMPTY_PARSERS))
            for name, counts in sorted(_PER_PARSER.items())
        }
        events = sorted(_EVENTS, key=lambda e: (e["parser"], e["device"], e["cmd"], e["file"]))
        suspect = sum(c["zero_yield"] for n, c in _PER_PARSER.items()
                      if n not in MAY_BE_EMPTY_PARSERS)
        expected = sum(c["zero_yield"] for n, c in _PER_PARSER.items()
                       if n in MAY_BE_EMPTY_PARSERS)
        errors = sum(c["errors"] for c in _PER_PARSER.values())
        return {
            "summary": {
                "parsers_called": len(per_parser),
                "zero_yield_suspect": suspect,
                "zero_yield_expected": expected,
                "parse_errors": errors,
                "note": ("Zero-yield = the command returned CONTENT but its parser produced 0 "
                         "entities: collected-but-unparsed evidence, a possible platform-variant "
                         "format gap in the parser — never a device state verdict. Absent or "
                         "error-captured commands are the Collection Completeness axis's domain "
                         "and are not counted here."),
            },
            "per_parser": per_parser,
            "events": events,
            "events_truncated": _EVENTS_TRUNCATED,
        }


def _record_yield(fn, args, result, error: bool) -> None:
    """Telemetry only — must NEVER raise into the fail-soft parse path."""
    global _EVENTS_TRUNCATED
    try:
        name = getattr(fn, "__name__", repr(fn))
        text = next((a for a in args if isinstance(a, str)), None)
        chars = len(text) if text else 0
        lines = (text.count("\n") + 1) if text else 0
        with_content = text is not None and bool(text.strip()) and (
            lines >= MIN_CONTENT_LINES or chars >= MIN_CONTENT_CHARS)
        entities = len(result) if isinstance(result, (dict, list, tuple, set)) else None
        with _YIELD_LOCK:
            pp = _PER_PARSER.setdefault(
                name, {"calls": 0, "with_content": 0, "zero_yield": 0, "errors": 0})
            pp["calls"] += 1
            if not with_content:
                return                      # absent/trivial input: Collection Completeness's domain
            pp["with_content"] += 1
            if error:
                pp["errors"] += 1
            elif entities == 0:
                pp["zero_yield"] += 1
            else:
                return                      # entities came out (or an unsized result): no event
            last = getattr(_TL, "last_load", None)
            if last is not None and last[2] == chars:   # len-verified: same text this thread loaded
                cmd, path = last[0], last[1]
                device = os.path.basename(os.path.dirname(path)) or _UNATTRIBUTED
                fname = os.path.basename(path)
            else:
                cmd, device, fname = _UNATTRIBUTED, _UNATTRIBUTED, ""
            if len(_EVENTS) >= _YIELD_EVENT_CAP:
                _EVENTS_TRUNCATED = True
                return
            _EVENTS.append({"parser": name, "device": device, "cmd": cmd, "file": fname,
                            "lines_in": lines, "error": error})
    except Exception:
        pass


def _load_cmd_output(cmd_to_file: Dict[str, str], *cmd_variants: str) -> str:
    for cmd in cmd_variants:
        p = cmd_to_file.get(cmd)
        if p and os.path.isfile(p):
            try:
                with open(p, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                stripped = content.strip()
                if not stripped: continue
                first_chunk = stripped[:200].lower()
                if any(pat in first_chunk for pat in _CISCO_ERRORS): continue
                try:  # pairing stash for the yield ledger — never let telemetry break a load
                    _TL.last_load = (cmd, p, len(content), content.count("\n") + 1)
                except Exception:
                    pass
                return content
            except Exception as e:
                logger.debug(f"_load_cmd_output: failed reading {p} for '{cmd}': {e}")  # NEW-V3.23.1
    return ""

def _safe_parse(fn, *args, _default=None):
    """FIX-V3.23.6 (P1): run a section parser fail-soft. If it raises on a
    malformed/unexpected block, log a breadcrumb and return _default ({} unless
    given) so build_interfaces keeps the rest of the device's data instead of
    losing the whole device to one bad section. Happy path is unchanged - the
    parsers already return {} on empty input, so wrapping is value-preserving."""
    try:
        result = fn(*args)
    except Exception as e:
        logger.warning(f"  [parse] {getattr(fn, '__name__', repr(fn))} failed: {e!r}; section skipped")
        result = {} if _default is None else _default
        _record_yield(fn, args, result, error=True)
        return result
    _record_yield(fn, args, result, error=False)
    return result
