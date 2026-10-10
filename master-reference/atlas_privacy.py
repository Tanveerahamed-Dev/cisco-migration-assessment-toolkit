"""Shared high-confidence privacy scan for Atlas compiler and release outputs.

The scanner deliberately reports only rule, path, and line. Matched values are
never retained in a ledger, exception, or generated artifact.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any


FORBIDDEN_CONTENT_RULES = (
    ("private_key_material", re.compile("-----BEGIN " + r"(?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("aws_access_key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("github_access_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("openai_api_key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{32,}\b")),
    ("slack_access_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
)

_GENERIC_WINDOWS_USER_HOME = re.compile(
    r"(?:^|[^a-z0-9])(?:[a-z]:|[\\/]{2,}[^\\/\r\n]+)[\\/]+users[\\/]+[^\\/\x00-\x1f<>:\"|?*']{1,128}(?=[\\/]|$|[\"'])"
)
_GENERIC_POSIX_USER_HOME = re.compile(r"(?:^|[^a-z0-9])/(?:home|users)/[^/\x00-\x1f\"']{1,128}(?=/|$|[\"'])")
_GENERIC_COLLAPSED_USER_HOME = re.compile(
    r"(?:^|_)(?:[a-z]_users|home|users)_[a-z0-9][a-z0-9_]{0,127}_"
    r"(?:appdata|build|cache|checkout|checkouts|code|config|desktop|documents|downloads|git|onedrive|project|projects|repo|repos|source|src|work|workspace)(?:_|$)"
)


def collapsed_ascii_identity(value: str) -> str:
    """Normalize a potential local identity without retaining it in findings."""

    folded = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"[^a-z0-9]+", "_", folded).strip("_")


def generic_local_identity_rule(value: str) -> str | None:
    """Return a categorical generic home-path rule without echoing the value."""

    folded = unicodedata.normalize("NFKC", value).casefold()
    collapsed = collapsed_ascii_identity(folded)
    if _GENERIC_WINDOWS_USER_HOME.search(folded):
        return "generic_windows_user_home_path"
    if _GENERIC_POSIX_USER_HOME.search(folded):
        return "generic_posix_user_home_path"
    if _GENERIC_COLLAPSED_USER_HOME.search(collapsed):
        return "generic_collapsed_user_home_path"
    return None


def forbidden_content_findings(path: str, text: str) -> list[dict[str, Any]]:
    """Return high-confidence findings without copying the matched value."""

    findings: list[dict[str, Any]] = []
    for rule, pattern in FORBIDDEN_CONTENT_RULES:
        for match in pattern.finditer(text):
            findings.append(
                {
                    "path": path,
                    "line": text.count("\n", 0, match.start()) + 1,
                    "rule": rule,
                }
            )
    return findings


# Bounded scanning (W64a).  A document may be scanned in segments instead of as
# one decoded string, with findings identical to ``forbidden_content_findings``
# over the whole text, provided every segment boundary falls immediately after
# a character that (1) no rule can ever match and (2) is not a regular-expression
# word character.  Then no match can straddle a boundary, and every ``\b``
# decision sees the same neighbouring character class on both sides of it.
# The separators below satisfy both for exactly the reviewed rule sources
# pinned beside them; if the rules change, segmenting is switched off (the
# whole text is buffered and scanned once, as before) until this proof is
# redone and the pin updated.
_SCAN_SEGMENT_SEPARATORS = '\n"{}[],:'
_SCAN_REVIEWED_RULE_SOURCES = (
    ("private_key_material", "-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    ("aws_access_key", r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    ("github_access_token", r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
    ("openai_api_key", r"\bsk-(?:proj-)?[A-Za-z0-9_-]{32,}\b"),
    ("slack_access_token", r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    ("google_api_key", r"\bAIza[0-9A-Za-z_-]{35}\b"),
)
_SCAN_SLICE_BYTES = 8 * 1024 * 1024


def _segmenting_reviewed() -> bool:
    return (
        tuple((rule, pattern.pattern, pattern.flags) for rule, pattern in FORBIDDEN_CONTENT_RULES)
        == tuple((rule, source, re.UNICODE) for rule, source in _SCAN_REVIEWED_RULE_SOURCES)
    )


class ForbiddenContentScan:
    """``forbidden_content_findings`` over text supplied in pieces.

    ``feed`` accepts pieces cut anywhere.  Each is joined to the unscanned
    remainder of the previous one, and only the text up to the last segment
    separator is scanned; the rest waits for more text or for ``finish``.
    ``finish`` returns exactly the findings, in exactly the order, that
    ``forbidden_content_findings(path, "".join(pieces))`` returns: rule by rule,
    each rule's matches in text order, with the same line numbers.
    """

    def __init__(self, path: str) -> None:
        self.path = path
        self._segmenting = _segmenting_reviewed()
        self._pending: list[str] = []
        self._newlines = 0
        self._lines: dict[str, list[int]] = {rule: [] for rule, _ in FORBIDDEN_CONTENT_RULES}

    def feed(self, text: str) -> None:
        if not text:
            return
        if not self._segmenting:
            self._pending.append(text)
            return
        cut = max(text.rfind(separator) for separator in _SCAN_SEGMENT_SEPARATORS) + 1
        if cut == 0:
            self._pending.append(text)
            return
        start = 0
        if self._pending:
            # Close the pending segment at this piece's first separator, so the
            # rest of the piece is scanned in place without being copied.
            first = min(
                index for index in (text.find(separator) for separator in _SCAN_SEGMENT_SEPARATORS) if index >= 0
            )
            self._pending.append(text[: first + 1])
            pending = "".join(self._pending)
            self._pending = []
            self._scan(pending, 0, len(pending))
            start = first + 1
        if start < cut:
            # ``text[start - 1]`` is a separator (or ``start`` is 0), so a
            # ``\b`` at ``start`` sees a non-word character either way.
            self._scan(text, start, cut)
        if cut < len(text):
            self._pending.append(text[cut:])

    def finish(self) -> list[dict[str, Any]]:
        if self._pending:
            pending = "".join(self._pending)
            self._pending = []
            self._scan(pending, 0, len(pending))
        return [
            {"path": self.path, "line": line, "rule": rule}
            for rule, _ in FORBIDDEN_CONTENT_RULES
            for line in self._lines[rule]
        ]

    def _scan(self, text: str, start: int, end: int) -> None:
        for rule, pattern in FORBIDDEN_CONTENT_RULES:
            for match in pattern.finditer(text, start, end):
                self._lines[rule].append(self._newlines + text.count("\n", start, match.start()) + 1)
        self._newlines += text.count("\n", start, end)


def forbidden_byte_findings(path: str, value: bytes) -> list[dict[str, Any]]:
    """Scan UTF-8-compatible spans in generated bytes, including text archives.

    The bytes are decoded in bounded slices instead of as one string.  Each
    slice ends immediately after an ASCII byte, where a UTF-8 decoder (also
    with ``errors="ignore"``) is always between characters, so the decoded
    slices concatenate to exactly ``value.decode("utf-8", errors="ignore")``,
    and ``ForbiddenContentScan`` returns exactly the whole-text findings.
    """

    scan = ForbiddenContentScan(path)
    start = 0
    total = len(value)
    while start < total:
        end = min(start + _SCAN_SLICE_BYTES, total)
        if end < total:
            cut = end
            while cut > start and value[cut - 1] >= 0x80:
                cut -= 1
            if cut == start:
                cut = end
                while cut < total and value[cut - 1] >= 0x80:
                    cut += 1
            end = cut
        scan.feed(value[start:end].decode("utf-8", errors="ignore"))
        start = end
    return scan.finish()
