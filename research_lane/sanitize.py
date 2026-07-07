"""Rule-3 sanitizer — strip client identifiers before any research-lane artifact crosses into the repo.

The load-bearing safety of the whole lane (D2/D3): nothing leaves this fenced worktree for the air-gapped
repo until client identity is scrubbed. Conservative — it redacts (1) every configured forbidden token
(client / site / device names), (2) IPv4 literals, and (3) email addresses, from the text-ish fields of each
advisory. It returns what it redacted so the producer can *prove* the scrub ran before attesting
``sanitized: true`` (a feed is only signed sanitized if this actually executed).

Pure-stdlib, no I/O — unit-testable. Reused by the vault-digest pipeline too (same Rule-3 contract as the
repo→vault bridge in ADR-0001)."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

_IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
# The advisory fields that may carry free text (and thus an accidental client identifier).
_TEXT_FIELDS = ("title", "summary", "detail", "source", "notes")


def sanitize_text(text: str, *, forbidden: Tuple[str, ...] = (), redact_ips: bool = True) -> Tuple[str, List[str]]:
    """Return ``(scrubbed, redactions)``. Forbidden tokens are matched case-insensitively; IPs and emails
    are pattern-redacted. ``redactions`` lists every literal removed (for the producer's proof-of-scrub)."""
    out = text or ""
    redactions: List[str] = []
    for tok in forbidden:
        if not tok:
            continue
        pat = re.compile(re.escape(tok), re.IGNORECASE)
        if pat.search(out):
            redactions.append(tok)
            out = pat.sub("[redacted]", out)
    if redact_ips:
        def _ip(m: "re.Match") -> str:
            redactions.append(m.group(0))
            return "[ip]"
        out = _IP_RE.sub(_ip, out)

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
