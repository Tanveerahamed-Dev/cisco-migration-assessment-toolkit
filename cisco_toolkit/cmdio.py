"""Command-output I/O glue: load a collected show-command's output from disk
(skipping empty/error captures via _CISCO_ERRORS) and run section parsers
fail-soft. Leaf layer: depends only on stdlib (os, logging, typing). Extracted
verbatim from COLLECT_PARSE_V3_23_0.py in PHASE 2.7 step 14 (behaviour
byte-identical). This is the helper nearly every build_* / compute_* / write_*
leans on to read collected output, so it's homed before the I/O-fed analyze
functions move."""
import logging
import os
from typing import Dict

logger = logging.getLogger(__name__)

_CISCO_ERRORS = (
    "% invalid", "% command not found",
    "% incomplete command", "% unknown command",
    "% ambiguous command", "% ip routing not enabled",
    "% routing not enabled", "invalid input detected",
    "error: invalid", "% requires vrf", "% vrf does not exist",
)

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
        return fn(*args)
    except Exception as e:
        logger.warning(f"  [parse] {getattr(fn, '__name__', repr(fn))} failed: {e!r}; section skipped")
        return {} if _default is None else _default
