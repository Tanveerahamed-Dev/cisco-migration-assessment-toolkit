"""Rule-3 sanitizer — strip client identifiers before any research-lane artifact crosses into the repo.

The load-bearing safety of the whole lane (D2/D3): nothing leaves this fenced worktree for the air-gapped
repo until client identity is scrubbed. Conservative — it redacts (1) every configured forbidden token
(client / site / device names) **and its identifier spellings**, (2) IPv4 and IPv6 literals, (3) Cisco
chassis serials, and (4) email addresses, from the text-ish fields of each advisory. It returns what it
redacted so the producer can *prove* the scrub ran before attesting
``sanitized: true`` (a feed is only signed sanitized if this actually executed).

Pure-stdlib, no I/O — unit-testable. Reused by the vault-digest pipeline too (same Rule-3 contract as the
repo→vault bridge in ADR-0001)."""
from __future__ import annotations

import ipaddress
import re
from typing import Any, Dict, List, Tuple

_IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
# IPv6 CANDIDATES only — every hit is then validated by :mod:`ipaddress`, which is what keeps a MAC
# (``00:1a:2b:3c:4d:5e``, six groups, no ``::``) and a timestamp (``10:30:00``) out of the redactor.
# The lookaround requires either a ``::`` or a full eight-group form; ``std::vector`` is safe because
# the lookbehind rejects a word character before the ``::``. NOT claimed: zero false positives — an
# all-hex scope like ``abc::def`` IS a valid IPv6 literal and is redacted. This gate over-redacts by
# design (D2/D3); a mangled advisory line costs less than a client's management address crossing.
_IP6_RE = re.compile(r"(?<![:.\w])(?=[0-9A-Fa-f:]*::|(?:[0-9A-Fa-f]{1,4}:){7})[0-9A-Fa-f:]{2,45}(?![:.\w])")
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
# Cisco chassis serial: 3-letter site code + 4-digit year/week + 4 alphanumerics (FDO2145A1BC). A
# serial resolves to a support contract, i.e. to the CUSTOMER, so it is a client identifier even
# though it names no client. Narrow on purpose — the leading THREE letters followed by FOUR DIGITS
# keeps bug ids (CSCvk12345), PIDs (C9300-48U) and versions out of it.
_SERIAL_RE = re.compile(r"\b[A-Z]{3}[0-9]{4}[0-9A-Z]{4}\b")
# The advisory fields that may carry free text (and thus an accidental client identifier).
_TEXT_FIELDS = ("title", "summary", "detail", "source", "notes")
#: Separators a client/site name is re-spelt with once it becomes an identifier.
#: Re-exported from the owner so this module's local reads keep working.
from cisco_toolkit.textutils import (                                          # noqa: E402
    FORBIDDEN_TOKEN_SEPARATORS as _SEPARATORS,
    forbidden_token_pattern as _token_pattern,
)

# _token_pattern is deliberately NOT defined here. It is the PRODUCING half of a two-sided gate
# whose consuming half is cisco_toolkit.intel_feed.verify_feed, and when the two carried separate
# literal-match implementations they shared the same blind spots — so the consumer could never
# catch what the producer missed, and a feed signed `sanitized: true` with an EMPTY redaction list
# was accepted. One owner now (cisco_toolkit.textutils, SSOT Law 1); see its docstring for the two
# shapes this closes. tests/test_research_lane.py pins the behaviour from this side.


def sanitize_text(text: str, *, forbidden: Tuple[str, ...] = (), redact_ips: bool = True) -> Tuple[str, List[str]]:
    """Return ``(scrubbed, redactions)``. Forbidden tokens are matched case-insensitively and across
    separator spellings (see :func:`_token_pattern`); IPv4/IPv6 literals, chassis serials and emails
    are pattern-redacted. ``redactions`` lists every literal removed (the producer's proof-of-scrub).

    NOT covered, and deliberately named so the caller's mental model is right: MAC addresses, and any
    client identifier that is neither a configured token nor one of the patterns above. ``sanitized:
    true`` attests that THIS ran, not that the text is anonymous."""
    out = text or ""
    redactions: List[str] = []
    for tok in forbidden:
        pat = _token_pattern(tok)
        if pat is None:
            continue
        if pat.search(out):
            redactions.append(tok)
            out = pat.sub("[redacted]", out)
    if redact_ips:
        def _ip(m: "re.Match") -> str:
            redactions.append(m.group(0))
            return "[ip]"
        out = _IP_RE.sub(_ip, out)

        def _ip6(m: "re.Match") -> str:
            try:
                ipaddress.IPv6Address(m.group(0))
            except ValueError:                    # a MAC / timestamp / hex run — leave it alone
                return m.group(0)
            redactions.append(m.group(0))
            return "[ip]"
        out = _IP6_RE.sub(_ip6, out)

    def _serial(m: "re.Match") -> str:
        redactions.append(m.group(0))
        return "[serial]"
    out = _SERIAL_RE.sub(_serial, out)

    def _email(m: "re.Match") -> str:
        redactions.append(m.group(0))
        return "[email]"
    out = _EMAIL_RE.sub(_email, out)
    return out, redactions


def sanitize_advisory(adv: Dict[str, Any], *, forbidden: Tuple[str, ...] = (),
                      redact_ips: bool = True) -> Tuple[Dict[str, Any], List[str]]:
    clean = dict(adv)
    redactions: List[str] = []
    for k in _TEXT_FIELDS:
        if isinstance(clean.get(k), str):
            clean[k], r = sanitize_text(clean[k], forbidden=forbidden, redact_ips=redact_ips)
            redactions += r
    return clean, redactions


def sanitize_advisories(advisories: List[Dict[str, Any]], *, forbidden: Tuple[str, ...] = (),
                        redact_ips: bool = True) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Scrub a whole batch. Returns ``(clean_advisories, all_redactions)``."""
    clean: List[Dict[str, Any]] = []
    redactions: List[str] = []
    for a in advisories:
        if isinstance(a, dict):
            c, r = sanitize_advisory(a, forbidden=forbidden, redact_ips=redact_ips)
            clean.append(c)
            redactions += r
    return clean, redactions
