"""Independent, fail-closed verification for Atlas shareable redaction output.

This module deliberately does not import the engine's redaction implementation.  A postcondition
implemented with the same matcher as the producer inherits the same blind spots.  Instead, it
recognises only the producer's documented pseudonym spaces and scans:

* every key and value in the redacted snapshot;
* visible text and attributes in generated OOXML documents; and
* the complete generated HTML source, including its embedded snapshot.

All reads are bounded, regular-file-only, and container members are never extracted.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import ipaddress
import json
import os
import re
import stat
import unicodedata
import zipfile
from functools import lru_cache
from pathlib import Path
from typing import Any, BinaryIO, Iterable, Iterator
from xml.etree import ElementTree

MAX_ARTIFACT_BYTES = 128 * 1024 * 1024
MAX_CONTAINER_ENTRIES = 10_000
MAX_CONTAINER_UNCOMPRESSED_BYTES = 256 * 1024 * 1024
MAX_CONTAINER_MEMBER_BYTES = 64 * 1024 * 1024
MAX_JSON_NODES = 2_000_000
MAX_JSON_DEPTH = 128
MAX_LEAKS_REPORTED = 24

_HTML_SUFFIXES = frozenset({".html", ".htm"})
_OOXML_SUFFIXES = frozenset({".xlsx", ".docx", ".pptx"})

#: A RAW CAPTURE is defined by STRUCTURE, not by one file extension.
#:
#: The producer (``cisco_toolkit.html.redact_collection_dir``), this verifier and the ingest census
#: all used to test ``name.endswith(".txt")``. Three agreeing matchers are one matcher: a device
#: folder holding ``show_version.txt`` PLUS ``backup-config.cfg`` / ``show_tech-support.log`` was
#: accepted by ``_find_collection_root``, the two extra files were never scrubbed, never scanned and
#: never counted, and the run still printed "Raw captures: SCRUBBED" and exited 0. Measured: both
#: kept cleartext ``enable secret``, ``snmp-server community`` and ``username ... password`` values.
#:
#: The rule below is deliberately INCLUSIVE by default so an unknown extension is protected rather
#: than skipped -- that is the whole point of fixing the shape instead of lengthening a list:
#:
#: * a capture is any regular file under the collection root;
#: * whose bytes contain no NUL, i.e. it is text and not a binary container (content, not name);
#: * except a serialisation format whose payload is not the line-oriented device-config text this
#:   grammar reads (``_STRUCTURED_CAPTURE_SUFFIXES``), and except the producer's own rewrite
#:   scratch file.
#:
#: Everything the rule EXCLUDES is counted and returned under ``uncovered`` -- "we did not look
#: here" must never render as "there is nothing here".
#:
#: The exclusions are all one class: a STRUCTURED DOCUMENT, whose payload is not config lines and
#: whose bytes another gate already owns. Substituting a value inside one is how a capture stops
#: parsing, and rewriting a generated ``.html`` deliverable that happens to sit in the collection
#: folder would break the run manifest that already sealed it.
_STRUCTURED_CAPTURE_SUFFIXES = frozenset({".json", ".xml", ".yml", ".yaml", ".html", ".htm"})

#: The scratch name ``redact_collection_dir`` writes beside a capture while rewriting it.
_SCRUB_TEMP_SUFFIX = ".redacting"
_TEXT_MEMBER_SUFFIXES = frozenset(
    {".xml", ".rels", ".vml", ".txt", ".json", ".html", ".htm", ".csv"}
)
_OPAQUE_MEDIA_SUFFIXES = frozenset(
    {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".emf", ".wmf"}
)

# OOXML parts that are BINARY but must still be proven clean. python-pptx writes
# ``ppt/printerSettings/printerSettings1.bin`` (a Windows DEVMODE) into every deck, so rejecting
# ".bin" outright failed independent verification on EVERY executive deck and took the whole
# pipeline down with it ("[INCOMPLETE] Mandatory finalization failed").
#
# The two easy answers are both wrong. Rejecting a legitimate part blocks a valid delivery; adding
# it to _OPAQUE_MEDIA_SUFFIXES would wave through unscanned bytes, which is the silent-degrade this
# module exists to prevent. A redaction verifier does not need to PARSE a format -- it needs to
# prove no secret bytes survive -- so these are decoded leniently and scanned, in UTF-8 AND
# UTF-16: a DEVMODE stores its device/port strings as UTF-16, where a UTF-8-only scan reads them
# as interleaved NULs and would miss exactly the identifiers that matter.
_SCANNED_BINARY_SUFFIXES = frozenset({".bin"})

_IPV4_CANDIDATE_RE = re.compile(
    r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?:/\d{1,2})?(?![\d.])"
)
_IPV6_CANDIDATE_RE = re.compile(
    r"(?<![0-9A-Za-z:.])(?:[0-9A-Fa-f]{0,4}:){2,7}"
    r"[0-9A-Fa-f]{0,4}(?:%[0-9A-Za-z_.-]+)?(?:/\d{1,3})?"
    r"(?![0-9A-Za-z:.])"
)
_MAC_RE = re.compile(
    r"(?<![0-9A-Fa-f])(?:(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}"
    r"|(?:[0-9A-Fa-f]{4}\.){2}[0-9A-Fa-f]{4})(?![0-9A-Fa-f])"
)
_CISCO_SERIAL_RE = re.compile(
    r"(?<![A-Z0-9])[A-Z]{3}\d{4}[A-Z0-9]{2,6}(?![A-Z0-9])",
    re.IGNORECASE,
)
# A GUID's final group is 12 hex characters, which can satisfy the Cisco-serial shape by
# coincidence. {D31A062A-798A-4329-ABDD-BBA856620510} is a FIXED OOXML constant that
# python-pptx writes into ppt/presProps.xml of every deck, and its tail BBA856620510
# parses as [A-Z]{3}\d{4}[A-Z0-9]{2,6}. So this verifier reported a "Cisco serial" leak
# on every .pptx it has ever checked, in a file the redactor cannot make cleaner.
#
# The fix is a CONTEXT rule, not a looser serial pattern: narrowing _CISCO_SERIAL_RE to
# reject hex-only tokens would also stop matching real serials that happen to be
# hex-shaped, which is the check defanging itself to silence its own noise. Requiring the
# entire 36-character 8-4-4-4-12 structure keeps the exclusion to things that genuinely
# are GUIDs — a serial sitting inside one is not reachable, because the surrounding
# groups would have to be hex and hyphen-aligned too.
_GUID_RE = re.compile(
    r"(?<![0-9A-Fa-f-])[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-"
    r"[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}(?![0-9A-Fa-f-])"
)
_SYNTH_DOMAIN = "assesshub-redacted.invalid"
_SYNTH_MARKER_RE = re.compile(
    r"(?:v4-n\d{5}-h\d{3}|v6-\d{8}|mac-\d{12}|serial-\d{6})\."
    + re.escape(_SYNTH_DOMAIN)
    + r"\Z",
    re.IGNORECASE,
)
_SERIAL_PSEUDONYM_RE = re.compile(
    r"serial-\d{6}\." + re.escape(_SYNTH_DOMAIN) + r"\Z",
    re.IGNORECASE,
)
_EMAIL_PSEUDONYM_RE = re.compile(
    r"contact-\d{6}@" + re.escape(_SYNTH_DOMAIN) + r"\Z",
    re.IGNORECASE,
)
_EMAIL_RE = re.compile(
    r"(?<![\w.+-])[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"(?:[A-Z0-9-]+\.)+[A-Z]{2,63}(?![\w.-])",
    re.IGNORECASE,
)
_PLACEHOLDER = "<redacted>"
_SERIAL_KEYS = frozenset(
    {
        "serialnumber", "chassisserial", "currentswitchserial", "neighborswitchserial",
        "serial", "psserials", "sn",
    }
)
_SECRET_KEYS = frozenset(
    {
        "password", "passwd", "pwd", "passphrase", "secret", "psksecret", "presharedkey",
        "psk", "token", "authtoken", "accesstoken", "apikey", "apisecret", "community",
        "snmpcommunity", "credential", "credentials", "privatekey", "sharedsecret",
        "clientsecret",
    }
)
_SECRET_KEY_TOKENS = (
    "password", "passwd", "passphrase", "secret", "community", "psk", "presharedkey",
    "sharedsecret", "token", "apikey", "apisecret", "privatekey", "privkey", "credential",
)
_SECRET_VALUE = r"""(?:"(?:\\.|[^"\\\r\n])*"|'(?:\\.|[^'\\\r\n])*'|\S+)"""
_INLINE_SECRET_RES = tuple(
    re.compile(pattern, re.IGNORECASE | re.MULTILINE)
    for pattern in (
        rf"^\s*snmp-server\s+community\s+(?P<secret>{_SECRET_VALUE})",
        rf"^\s*community\s+(?P<secret>{_SECRET_VALUE})",
        r"^\s*snmp-server\s+host\s+\S+\s+(?:vrf\s+\S+\s+)?"
        rf"(?:(?:traps?|informs?)\s+)?version\s+(?:1|2c)\s+(?P<secret>{_SECRET_VALUE})",
        rf"^\s*(?:enable\s+)?(?:password|secret)\s+(?:(?:ENC|\d+)\s+)?"
        rf"(?P<secret>{_SECRET_VALUE})",
        r"^\s*(?:username|user)\s+\S+\s+(?:password|secret)\s+(?:\d+\s+)?"
        rf"(?P<secret>{_SECRET_VALUE})",
        r"^\s*(?:tacacs-server|radius-server)\s+.+?\bkey\s+(?:\d+\s+)?"
        rf"(?P<secret>{_SECRET_VALUE})",
        r"^\s*(?:key-string|pre-shared-key|crypto\s+isakmp\s+key)\s+"
        r"(?:(?:local|remote|ascii-text|hexadecimal|ENC|\d+)\s+)*"
        rf"(?P<secret>{_SECRET_VALUE})",
        r"^\s*set\s+(?:passwd|psksecret|password|private-key|passphrase)\s+"
        rf"(?:ENC\s+)?(?P<secret>{_SECRET_VALUE})",
    )
)
_STRICT_SECRET_LINE_RES = (
    re.compile(
        r"^\s*set\s+(?:passwd|psksecret|password|private-key|passphrase)\s+"
        r"(?:ENC\s+)?(?P<value>.*?)\s*$",
        re.IGNORECASE | re.MULTILINE,
    ),
)


class RedactionVerificationError(ValueError):
    """A current-run shareable artifact could not be positively certified as scrubbed."""


def _norm_key(value: Any) -> str:
    return re.sub(r"[_\-\s]", "", str(value or "").casefold())


def _is_secret_key(value: Any) -> bool:
    key = _norm_key(value)
    if not key or key in {"key", "pass"}:
        return False
    return key in _SECRET_KEYS or any(token in key for token in _SECRET_KEY_TOKENS)


def _is_serial_key(value: Any) -> bool:
    return _norm_key(value) in _SERIAL_KEYS


def _file_identity(st: os.stat_result) -> tuple[int, int, int, int]:
    return (int(st.st_dev), int(st.st_ino), int(st.st_size), int(st.st_mtime_ns))


def _is_link_or_reparse(st: os.stat_result) -> bool:
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return stat.S_ISLNK(st.st_mode) or bool(getattr(st, "st_file_attributes", 0) & reparse)


@contextlib.contextmanager
def _verified_open(path: Path) -> Iterator[BinaryIO]:
    """Open a bounded regular file without following a link, checking identity around the read."""
    try:
        before = os.lstat(path)
    except OSError as exc:
        raise RedactionVerificationError(
            f"{path.name}: cannot be read back ({type(exc).__name__})"
        ) from exc
    if _is_link_or_reparse(before) or not stat.S_ISREG(before.st_mode):
        raise RedactionVerificationError(f"{path.name}: not a physical regular file")
    if before.st_size > MAX_ARTIFACT_BYTES:
        raise RedactionVerificationError(
            f"{path.name}: {before.st_size} bytes exceeds the "
            f"{MAX_ARTIFACT_BYTES // (1024 * 1024)} MiB verification budget"
        )
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise RedactionVerificationError(
            f"{path.name}: cannot be opened safely ({type(exc).__name__})"
        ) from exc
    handle = os.fdopen(fd, "rb")
    try:
        opened = os.fstat(handle.fileno())
        if _file_identity(opened) != _file_identity(before):
            raise RedactionVerificationError(f"{path.name}: changed while it was being opened")
        yield handle
        after = os.fstat(handle.fileno())
        if _file_identity(after) != _file_identity(opened):
            raise RedactionVerificationError(f"{path.name}: changed while it was being verified")
        try:
            after_path = os.lstat(path)
        except OSError as exc:
            raise RedactionVerificationError(
                f"{path.name}: disappeared while it was being verified"
            ) from exc
        if _is_link_or_reparse(after_path) or _file_identity(after_path) != _file_identity(opened):
            raise RedactionVerificationError(
                f"{path.name}: path identity changed while it was being verified"
            )
    finally:
        handle.close()


def _read_all_bounded(handle: BinaryIO, limit: int, label: str) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = handle.read(min(1024 * 1024, limit + 1 - total))
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise RedactionVerificationError(f"{label}: verification read exceeded its byte budget")
        chunks.append(chunk)
    return b"".join(chunks)


def _json_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise RedactionVerificationError(f"snapshot JSON repeats key {key!r}")
        out[key] = value
    return out


def _path_tokens(where: str) -> set[str]:
    return {token.casefold() for token in re.findall(r"[A-Za-z_]+", where)}


# Engine-authored doctrine copy embeds protocol constants whose meaning pseudonymization would
# destroy: "a DAD failure on fe80:: silently kills OSPFv3/EIGRPv6" is advice, while "a DAD failure
# on v6-01234567.assesshub-redacted.invalid silently kills OSPFv3/EIGRPv6" is noise. This maps each
# such constant to the EXACT sentences the generators write around it.
#
# The anchor is the SENTENCE, not the surface. The previous gate additionally required the schema
# path to contain `design_blueprint` or `design_nrfu`, which is where these sentences live in the
# snapshot JSON -- but the identical copy is also rendered into out_design.docx, out_crd.docx and
# out_archreview.docx, whose paths carry no such token. So every `--redact` run failed mandatory
# finalization on 24 "leak" indicators that were protocol constants in the engine's own prose, and
# the fleet-wide effect was that a redacted deliverable set could not be produced at all.
#
# Enumerating the surfaces instead would rot the moment a new deliverable renders the same copy --
# which is exactly how crd and archreview came to be missed. A sentence the engine authored is the
# structural class; the artifact it lands in is an implementation detail of that class.
_AUTHORED_CONSTANT_PHRASES: dict[str, tuple[str, ...]] = {
    "fe80::": (
        "a DAD failure on fe80:: silently kills OSPFv3/EIGRPv6",
    ),
    "224.0.0.2": (
        "the HSRP transport (multicast 224.0.0.2 / UDP 1985, or IPv6 FF02::66)",
    ),
    "FF02::66": (
        "the HSRP transport (multicast 224.0.0.2 / UDP 1985, or IPv6 FF02::66)",
    ),
    "::/0": (
        "A security group that allows inbound from 0.0.0.0/0 (or ::/0) to an admin port",
    ),
    "0.0.0.0/0": (
        "no security group allows ingress from 0.0.0.0/0 to port 22 / 3389",
        "Never expose an admin / database port (or all ports) to 0.0.0.0/0 "
        "in a cloud security group",
        "never 0.0.0.0/0 to classify",
        "A security group that allows inbound from 0.0.0.0/0 (or ::/0) to an admin port",
        "Cloud exposure: a security group open from 0.0.0.0/0 to an admin / DB / all port",
    ),
    "10.0.0.0/16": (
        "Target address space (supernet, e.g. 10.0.0.0/16)",
        "Supply an address_space (supernet, e.g. 10.0.0.0/16) to allocate target subnets;",
        "supply e.g. 10.0.0.0/16.",
    ),
    # A SENTENCE-FINAL constant is reported under a DIFFERENT token than the one registered above,
    # so the `10.0.0.0/16` entry alone leaves it unexempted. `_IPV4_CANDIDATE_RE` ends with
    # `(?![\d.])`; in "…supply e.g. 10.0.0.0/16." the trailing period fails that lookahead, the match
    # backtracks, and what is offered to `_documented_example` is the bare `10.0.0.0`. Measured: the
    # real producer string at cisco_toolkit/design_advisor.py:4240 —
    # f"address_space '{space}' is not a valid network; supply e.g. 10.0.0.0/16." — still reported a
    # leak, i.e. the "every --redact run fails mandatory finalization" class was still live on that
    # branch while the phrase registered to cover it never fired.
    #
    # Registered against the SAME sentences, so containment does the work: `10.0.0.0` is exempt only
    # inside engine-authored copy that already contains it, never on its own.
    "10.0.0.0": (
        "Target address space (supernet, e.g. 10.0.0.0/16)",
        "Supply an address_space (supernet, e.g. 10.0.0.0/16) to allocate target subnets;",
        "supply e.g. 10.0.0.0/16.",
    ),
}


@lru_cache(maxsize=None)
def _phrase_pattern(phrase: str) -> re.Pattern[str]:
    """The phrase with every run of whitespace made elastic.

    OOXML splits a sentence across runs, so the same authored copy that is one string in the
    snapshot JSON arrives here with newlines and doubled spaces at the run boundaries. A literal
    ``find`` matches the JSON and silently misses the DOCX -- the two surfaces this must treat
    alike.
    """
    return re.compile(r"\s+".join(re.escape(part) for part in phrase.split()), re.IGNORECASE)


def _token_within_authored_phrase(text: str, start: int, end: int,
                                  phrases: Iterable[str]) -> bool:
    """True when [start, end) lies wholly INSIDE an occurrence of one of `phrases`.

    Containment is the point. Asking only whether the phrase occurs SOMEWHERE in the document
    exempts every other occurrence of that constant in the same document -- so one sentence of
    boilerplate would whitelist the token document-wide, including a genuinely leaked instance of
    it. Half of this function's callers already worked that way; the other half did not.
    """
    for phrase in phrases:
        for match in _phrase_pattern(phrase).finditer(text):
            if match.start() <= start and end <= match.end():
                return True
    return False


def _documented_example(text: str, start: int, end: int, where: str) -> bool:
    """Allow a protocol constant only where engine-authored copy demonstrably surrounds it."""
    candidate = text[start:end]
    # The design advisor documents the IPv6 all-internet prefix as the exact parenthetical
    # alternative ``(or ::/0)``. It is a protocol constant, not observed addressing. Keep this
    # exception pinned to that one generated documentation field and spelling.
    if (
        candidate == "::/0"
        and {"design_blueprint", "decisions", "evidence", "summary"} <= _path_tokens(where)
        and re.fullmatch(r"\(\s*or\s+::/0\s*\)", text[max(0, start - 4):min(len(text), end + 1)],
                         re.IGNORECASE)
    ):
        return True
    return _token_within_authored_phrase(
        text, start, end, _AUTHORED_CONSTANT_PHRASES.get(candidate, ())
    )


def _inside_guid(text: str, start: int, end: int) -> bool:
    """True when [start, end) lies wholly inside a full 8-4-4-4-12 GUID. See _GUID_RE."""
    for guid in _GUID_RE.finditer(text):
        if guid.start() <= start and end <= guid.end():
            return True
        if guid.start() > end:
            break               # finditer is ordered; no later GUID can contain this span
    return False


def _append(leaks: list[str], kind: str, where: str) -> None:
    if len(leaks) < MAX_LEAKS_REPORTED:
        leaks.append(f"{kind} at {where}")


def _is_schema_wildcard(text: str, token: str, where: str) -> bool:
    """Recognize a contiguous ACL wildcard mask, which is metadata rather than an address.

    The producer intentionally preserves ``wild`` fields so its post-redaction ACL algebra stays
    correct. Keep this exception schema- and value-exact, and reject non-contiguous masks because
    they cannot be distinguished safely from a real address.
    """
    if not where.casefold().endswith(".wild") or text.strip() != token:
        return False
    try:
        bits = int(ipaddress.IPv4Address(token))
    except ipaddress.AddressValueError:
        return False
    return bits & (bits + 1) == 0


def _fold_identifier_text(value: str) -> str:
    """NFKC-normalise and drop invisible format characters before any pattern runs.

    Every identifier pattern in this module is written in ASCII, so ONE invisible character made a
    real leak invisible to the whole verifier. Measured before this, each reporting 0 leaks while the
    byte-identical ASCII form reported 1: a ZWSP or SOFT HYPHEN inside a Cisco serial, a ZWSP inside
    a MAC or an email, and a ZWSP or FULLWIDTH FULL STOP inside an IPv4. Five of five identifier
    classes, on the gate that decides whether a deliverable is safe to send a client.

    These are not exotic. A soft hyphen arrives from Word, a ZWSP from wrapped terminal output pasted
    into a note, fullwidth punctuation from a CJK IME — all of which reach a device description or a
    hostname and from there into a generated document.

    Folding at the single entry point rather than per-pattern is deliberate: every caller
    (`[key]`, values, OOXML element text and attributes, joined runs, zip comments, member names,
    `.bin` decodes, HTML) is covered by construction, so a future pattern cannot miss it. Offsets
    stay internally consistent because everything downstream — `_documented_example`,
    `_inside_guid`, `_token_within_authored_phrase` — reads this same folded text. NFKC of ASCII is
    ASCII, so the authored-constant sentences match exactly as before.

    Direction is one-way: this can only make MORE input report as a leak, never less. A verifier that
    over-reports is a delivery someone re-checks; one that under-reports is a client identifier in a
    document that was certified safe.
    """
    folded = unicodedata.normalize("NFKC", value)
    return "".join(ch for ch in folded if unicodedata.category(ch) != "Cf")


def _scan_text(text: str, where: str, leaks: list[str]) -> None:
    text = _fold_identifier_text(text)
    for match in _IPV4_CANDIDATE_RE.finditer(text):
        token = match.group(0)
        address_text = token.split("/", 1)[0]
        try:
            ipaddress.IPv4Address(address_text)
        except ipaddress.AddressValueError:
            continue
        if _is_schema_wildcard(text, token, where):
            continue
        if _documented_example(text, match.start(), match.end(), where):
            continue
        _append(leaks, "non-pseudonym IPv4", where)

    for match in _IPV6_CANDIDATE_RE.finditer(text):
        token = match.group(0)
        address_text = token.split("/", 1)[0].split("%", 1)[0]
        try:
            ipaddress.IPv6Address(address_text)
        except ipaddress.AddressValueError:
            continue
        if _documented_example(text, match.start(), match.end(), where):
            continue
        _append(leaks, "non-pseudonym IPv6", where)

    for match in _MAC_RE.finditer(text):
        _append(leaks, "non-pseudonym MAC", where)

    for match in _CISCO_SERIAL_RE.finditer(text):
        if _SERIAL_PSEUDONYM_RE.fullmatch(match.group(0)):
            continue
        if _inside_guid(text, match.start(), match.end()):
            continue
        _append(leaks, "Cisco serial", where)

    for match in _EMAIL_RE.finditer(text):
        if _EMAIL_PSEUDONYM_RE.fullmatch(match.group(0)):
            continue
        _append(leaks, "email address", where)

    for pattern in _INLINE_SECRET_RES:
        for match in pattern.finditer(text):
            secret = match.group("secret").strip("\"'")
            if secret.casefold() != _PLACEHOLDER:
                _append(leaks, "credential value", where)
    for pattern in _STRICT_SECRET_LINE_RES:
        for match in pattern.finditer(text):
            value = match.group("value").strip()
            if value[:1] in {'"', "'"} and value[-1:] == value[:1]:
                value = value[1:-1].strip()
            if value.casefold() != _PLACEHOLDER:
                _append(leaks, "credential residue", where)


def _scan_secret_tree(
    value: Any,
    where: str,
    leaks: list[str],
    budget: list[int],
    depth: int = 0,
) -> None:
    budget[0] += 1
    if budget[0] > MAX_JSON_NODES:
        raise RedactionVerificationError(
            "secret-bearing snapshot values exceed the node verification budget"
        )
    if depth > MAX_JSON_DEPTH:
        raise RedactionVerificationError("secret-bearing snapshot value exceeds the depth budget")
    if isinstance(value, dict):
        for key, child in value.items():
            _scan_secret_tree(child, f"{where}.{key}", leaks, budget, depth + 1)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _scan_secret_tree(child, f"{where}[{index}]", leaks, budget, depth + 1)
    elif value not in (None, ""):
        if not (isinstance(value, str) and value.casefold() == _PLACEHOLDER):
            _append(leaks, "unredacted secret-bearing key", where)


def _scan_json_tree(root: Any, leaks: list[str]) -> None:
    stack: list[tuple[Any, str, Any, int]] = [(root, "$", None, 0)]
    visited = 0
    secret_budget = [0]
    while stack:
        value, where, parent_key, depth = stack.pop()
        visited += 1
        if visited > MAX_JSON_NODES:
            raise RedactionVerificationError("snapshot exceeds the node verification budget")
        if depth > MAX_JSON_DEPTH:
            raise RedactionVerificationError("snapshot exceeds the depth verification budget")
        if isinstance(value, dict):
            for key, child in value.items():
                key_text = str(key)
                _scan_text(key_text, f"{where}.[key]", leaks)
                child_where = f"{where}.{key_text}"
                if _is_secret_key(key):
                    _scan_secret_tree(child, child_where, leaks, secret_budget)
                stack.append((child, child_where, key, depth + 1))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                stack.append((child, f"{where}[{index}]", parent_key, depth + 1))
        elif isinstance(value, str):
            if _is_serial_key(parent_key):
                if value and value.casefold() != _PLACEHOLDER and not _SERIAL_PSEUDONYM_RE.fullmatch(value):
                    _append(leaks, "unredacted serial-bearing key", where)
            _scan_text(value, where, leaks)


def _safe_member_name(name: str) -> str:
    normalized = name.replace("\\", "/")
    if (
        not normalized
        or normalized.startswith("/")
        or "\x00" in normalized
        or any(unicodedata.category(char) in {"Cc", "Cf", "Cs"} for char in normalized)
    ):
        raise RedactionVerificationError("OOXML container has an unsafe member name")
    parts = normalized.rstrip("/").split("/")
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise RedactionVerificationError("OOXML container has an ambiguous member name")
    return "/".join(parts)


def _member_is_special(info: zipfile.ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0xFFFF
    kind = stat.S_IFMT(mode)
    if not kind:
        return False
    expected = stat.S_IFDIR if info.is_dir() else stat.S_IFREG
    return kind != expected


def _scan_xml_member(raw: bytes, where: str, leaks: list[str]) -> None:
    if re.search(br"<!\s*(?:DOCTYPE|ENTITY)\b", raw, re.IGNORECASE):
        raise RedactionVerificationError(f"{where}: DTD/entity declarations are not supported")
    try:
        root = ElementTree.fromstring(raw)
    except (ElementTree.ParseError, ValueError) as exc:
        raise RedactionVerificationError(f"{where}: malformed XML") from exc
    for element in root.iter():
        if element.text:
            _scan_text(element.text, where, leaks)
        if element.tail:
            _scan_text(element.tail, where, leaks)
        for key, value in element.attrib.items():
            _scan_text(str(key), f"{where}.[attribute]", leaks)
            _scan_text(str(value), f"{where}.@{key}", leaks)
    # Word/PowerPoint/Excel can split one visible token across styled runs. Reconstruct text only
    # inside a semantic paragraph/shared-string container. Joining every XML text node fabricates
    # tokens across unrelated metadata fields (for example two application-version values).
    for container in root.iter():
        local = str(container.tag).rsplit("}", 1)[-1]
        if local not in {"p", "si", "is"}:
            continue
        fragments = [
            child.text
            for child in container.iter()
            if str(child.tag).rsplit("}", 1)[-1] == "t" and child.text
        ]
        if len(fragments) > 1:
            _scan_text("".join(fragments), f"{where}.[joined-runs]", leaks)
            _scan_text(" ".join(fragments), f"{where}.[spaced-runs]", leaks)


def _scan_ooxml(path: Path, leaks: list[str]) -> str:
    with _verified_open(path) as handle:
        raw_container = _read_all_bounded(handle, MAX_ARTIFACT_BYTES, path.name)
        try:
            container = zipfile.ZipFile(io.BytesIO(raw_container))
        except (zipfile.BadZipFile, OSError, ValueError) as exc:
            raise RedactionVerificationError(f"{path.name}: corrupt OOXML container") from exc
        with container:
            infos = container.infolist()
            if not infos or len(infos) > MAX_CONTAINER_ENTRIES:
                raise RedactionVerificationError(
                    f"{path.name}: empty or over-budget OOXML container"
                )
            if container.comment:
                try:
                    _scan_text(container.comment.decode("utf-8", "strict"),
                               f"{path.name}.[zip-comment]", leaks)
                except UnicodeDecodeError as exc:
                    raise RedactionVerificationError(
                        f"{path.name}: unreadable ZIP comment"
                    ) from exc
            total = 0
            seen: set[str] = set()
            for info in infos:
                member = _safe_member_name(info.filename)
                folded = unicodedata.normalize("NFKC", member).casefold()
                if folded in seen:
                    raise RedactionVerificationError(
                        f"{path.name}: duplicate/aliased OOXML member"
                    )
                seen.add(folded)
                if info.flag_bits & 0x1 or _member_is_special(info):
                    raise RedactionVerificationError(
                        f"{path.name}: encrypted or special OOXML member"
                    )
                if info.is_dir():
                    continue
                if info.file_size < 0 or info.file_size > MAX_CONTAINER_MEMBER_BYTES:
                    raise RedactionVerificationError(
                        f"{path.name}: OOXML member exceeds its byte budget"
                    )
                total += info.file_size
                if total > MAX_CONTAINER_UNCOMPRESSED_BYTES:
                    raise RedactionVerificationError(
                        f"{path.name}: OOXML container exceeds its expansion budget"
                    )
                _scan_text(member, f"{path.name}.[member-name]", leaks)
                lower = member.casefold()
                member_leaf = Path(lower).name
                # ``.rels`` is a complete OPC part name, not a pathlib suffix on Windows.
                suffix = ".rels" if member_leaf == ".rels" else Path(lower).suffix
                if any(part in lower for part in ("/embeddings/", "/oleobjects/", "/activex/")):
                    raise RedactionVerificationError(
                        f"{path.name}: unsupported embedded executable/package content"
                    )
                if suffix in _OPAQUE_MEDIA_SUFFIXES:
                    continue
                if suffix not in _TEXT_MEMBER_SUFFIXES | _SCANNED_BINARY_SUFFIXES:
                    raise RedactionVerificationError(
                        f"{path.name}: unsupported OOXML member type {suffix or '<none>'}"
                    )
                try:
                    raw = container.read(info)
                except (OSError, RuntimeError, NotImplementedError, ValueError, zipfile.BadZipFile) as exc:
                    raise RedactionVerificationError(
                        f"{path.name}: unreadable OOXML member"
                    ) from exc
                if len(raw) != info.file_size:
                    raise RedactionVerificationError(
                        f"{path.name}: OOXML member size changed while reading"
                    )
                member_where = f"{path.name}:{member}"
                if suffix in {".xml", ".rels", ".vml"}:
                    _scan_xml_member(raw, member_where, leaks)
                elif suffix in _SCANNED_BINARY_SUFFIXES:
                    # Lenient decode on purpose: a strict one would raise on the first non-text
                    # byte and never reach the identifiers.
                    #
                    # UTF-16 is scanned at BOTH byte alignments, and that is not defensive
                    # over-engineering -- it was measured. Decoding a blob as UTF-16 assumes the
                    # text starts on an even offset; when the preceding binary run has odd length
                    # the characters straddle the boundary and decode to CJK noise. A planted
                    # `10.44.7.219` was caught in UTF-8 and MISSED in UTF-16 until the odd
                    # alignment was added, i.e. the very encoding this branch exists for was the
                    # one silently passing.
                    for _encoding, _offset in (("utf-8", 0), ("utf-16-le", 0), ("utf-16-le", 1)):
                        _scan_text(raw[_offset:].decode(_encoding, "ignore"), member_where, leaks)
                else:
                    try:
                        text = raw.decode("utf-8", "strict")
                    except UnicodeDecodeError as exc:
                        raise RedactionVerificationError(
                            f"{member_where}: text payload is not UTF-8"
                        ) from exc
                    _scan_text(text, member_where, leaks)
    return hashlib.sha256(raw_container).hexdigest()


def _scan_html(path: Path, leaks: list[str]) -> str:
    with _verified_open(path) as handle:
        raw = _read_all_bounded(handle, MAX_ARTIFACT_BYTES, path.name)
    try:
        text = raw.decode("utf-8", "strict")
    except UnicodeDecodeError as exc:
        raise RedactionVerificationError(f"{path.name}: generated HTML is not UTF-8") from exc
    # The explorer embeds the canonical JSON object. Parse that object so schema-specific
    # non-identity values (notably an ACL wildcard under ``.wild``) retain their narrow exception;
    # scanning the opaque script text would lose the path and falsely call 0.0.0.255 an address.
    embedded_re = re.compile(
        r"const\s+EMBEDDED_SNAPSHOT=(?P<payload>.*?);\s*"
        r"load\(EMBEDDED_SNAPSHOT,",
        re.DOTALL,
    )
    embedded = embedded_re.search(text)
    if embedded:
        try:
            payload = json.loads(
                embedded.group("payload"), object_pairs_hook=_json_no_duplicates
            )
        except (json.JSONDecodeError, ValueError, TypeError, RecursionError) as exc:
            raise RedactionVerificationError(
                f"{path.name}: embedded snapshot JSON is malformed"
            ) from exc
        _scan_json_tree(payload, leaks)
        # Everything before this final bootstrap is the package's immutable demo/template.  The
        # only run-derived bytes are the embedded object and the label in the short suffix.
        _scan_text(text[embedded.end("payload"):], f"{path.name}.[bootstrap]", leaks)
    else:
        _scan_text(text, path.name, leaks)
    return hashlib.sha256(raw).hexdigest()


def _scan_snapshot(path: Path, leaks: list[str]) -> str:
    with _verified_open(path) as handle:
        raw = _read_all_bounded(handle, MAX_ARTIFACT_BYTES, path.name)
    try:
        value = json.loads(raw.decode("utf-8", "strict"), object_pairs_hook=_json_no_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError, RecursionError) as exc:
        if isinstance(exc, RedactionVerificationError):
            raise
        raise RedactionVerificationError(f"{path.name}: unreadable snapshot JSON") from exc
    _scan_json_tree(value, leaks)
    return hashlib.sha256(raw).hexdigest()


def _scan_plain_text_artifact(path: Path, leaks: list[str]) -> str:
    """Scan a run artifact that is plain text in its own right (Mermaid, Graphviz, CSV, a log).

    The engine registers ``topology.mmd`` and ``topology.dot`` as run artifacts, seals them into
    the run manifest and ships them beside the deliverables; they carry the same hostnames,
    addresses and interface labels as the explorer. They are decoded STRICTLY: a byte sequence
    this verifier cannot read is a byte sequence it cannot certify, and guessing would be the
    silent-degrade this module exists to prevent."""
    with _verified_open(path) as handle:
        raw = _read_all_bounded(handle, MAX_ARTIFACT_BYTES, path.name)
    try:
        text = raw.decode("utf-8", "strict")
    except UnicodeDecodeError as exc:
        raise RedactionVerificationError(
            f"{path.name}: text artifact is not UTF-8, so its bytes cannot be certified"
        ) from exc
    _scan_text(text, path.name, leaks)
    return hashlib.sha256(raw).hexdigest()


def certify_shareable_artifacts(
    snapshot_path: Path, artifacts: Iterable[Path]
) -> dict[str, str]:
    """Verify shareable bytes and return the SHA-256 of the exact bytes that were inspected.

    EVERY artifact handed in is verified or REFUSED; none is dropped. The pre-filter that used to
    stand here kept only a hand-listed suffix set (``.json/.html/.xlsx/.docx/.pptx``) and discarded
    the rest in silence, so the returned proof advertised coverage it did not have: the CLI path
    registers ``topology.mmd`` and ``topology.dot`` as run artifacts, seals them into the run
    manifest, ships them beside the deliverables and hands them to this function, which threw both
    away and then reported ``status="verified"`` with a ``verified_artifacts`` count that did not
    include them. A shareable-redaction claim over a set the caller chose is not something this
    module may narrow on the caller's behalf without saying so.

    Structured formats are parsed by their own scanners; anything else is scanned as text, which
    covers the diagram/CSV/log class and any future text artifact by construction. A format that
    can be neither parsed nor decoded raises -- the loud disclosure -- because certifying "no
    secrets survive" over bytes nobody read is exactly the claim this module refuses to make."""
    candidates: dict[str, Path] = {snapshot_path.name: snapshot_path}
    for candidate in artifacts:
        candidates[candidate.name] = candidate
    leaks: list[str] = []
    proof: dict[str, str] = {}
    for path in candidates.values():
        suffix = path.suffix.casefold()
        if suffix == ".json":
            proof[path.name] = _scan_snapshot(path, leaks)
        elif suffix in _HTML_SUFFIXES:
            proof[path.name] = _scan_html(path, leaks)
        elif suffix in _OOXML_SUFFIXES:
            proof[path.name] = _scan_ooxml(path, leaks)
        else:
            proof[path.name] = _scan_plain_text_artifact(path, leaks)
    if leaks:
        shown = "; ".join(leaks[:8])
        more = f"; plus {len(leaks) - 8} more" if len(leaks) > 8 else ""
        raise RedactionVerificationError(
            f"independent redaction verification found {len(leaks)} leak indicator(s): "
            f"{shown}{more}"
        )
    return proof


def verify_shareable_artifacts(snapshot_path: Path, artifacts: Iterable[Path]) -> int:
    """Verify the current run's snapshot and every current-run shareable document.

    Returns zero on success (matching the former ``_assert_scrubbed`` contract).  Any ambiguity,
    unsupported artifact, read error, budget overrun, or leak raises ``RedactionVerificationError``.
    """
    certify_shareable_artifacts(snapshot_path, artifacts)
    return 0


#: W59 PR-1: the collector's per-device SSH session record. It is a ``.json`` serialisation, so the capture
#: grammar cannot read it; instead it is recognised by its CLOSED schema and reported as covered by schema
#: when (1) every key is one of the schema's own field names and every leaf is a bounded integer, a boolean,
#: null, or a short printable token carrying no address-, MAC- or serial-shaped text; (2) every algorithm-name
#: position (the offered lists, the negotiated names, a refusal's names) holds a member of the producer's closed
#: recordable vocabulary; and (3) the server banner token matches the vendor-banner grammar. (2) and (3) are what
#: keep device-controlled free text -- a crafted name or banner carrying an organisation or host name -- out of a
#: file this verifier vouches for (review P3-e). Stated HERE, not imported: like the capture rule above, this
#: verifier never imports the producer side (``cisco_toolkit.ssh_session`` owns the schema);
#: ``webapp/tests/test_ssh_session_ingest_redaction.py`` holds the two statements in agreement over generated and
#: mutated records, and holds the restated vocabulary and grammar equal to the owner's.
SSH_SESSION_RECORD_BASENAME = "_ssh_session.json"
_SSH_SESSION_RECORD_SCHEMA = "ssh_session/1"
_SSH_SESSION_RECORD_MAX_BYTES = 1024 * 1024
_SSH_SESSION_RECORD_KEYS = frozenset({
    "schema", "outcome", "attempts", "platform_source", "consent", "library", "client_offered",
    "server_offered", "negotiated", "observation", "host_key", "refusal", "failure_class", "dropped_names",
    "device_profile", "run_flag_profile", "named_on_run_flag", "effective_profile", "paramiko", "netmiko",
    "transport_class", "default_permits_sha1", "kex", "cipher", "mac", "cipher_c2s", "cipher_s2c", "mac_c2s",
    "mac_s2c", "kex_hash_bytes", "dh_group_bits", "host_key_algorithm", "strict_kex", "server_software",
    "kexinit", "newkeys", "engine_name_agrees", "group_size_agrees", "policy", "verified", "category",
    "classification", "detail", "offered_group_bits", "names",
})
_SSH_SESSION_TOKEN_RE = re.compile(r"^[\x21-\x2b\x2d-\x39\x3b-\x7e]{1,64}$")
#: The producer's recordable algorithm vocabulary (``ssh_session.RECORDABLE_ALGORITHM_NAMES``), restated as the first
#: 16 hex digits of each name's SHA-256: membership without importing the producer, and without spelling any SSH
#: SHA-1 algorithm name in this module (T10 confines those literals to the vocabulary owner).
_SSH_SESSION_ALGORITHM_NAME_DIGESTS = frozenset({
    "052e633bab95ab7c", "06ccf5519261a5d9", "06d2fe6718730f6c", "06ed1e256cf053df", "07a7d2fef2151ca6",
    "07f7ecc094ced89d", "0ab6e4f85bad6fb6", "0f0b1c11008aa4b6", "139ccd8054309b29", "1728423eac104368",
    "18e1a44535d94365", "1f5890b6aa46f912", "28f9c6dfabef74a1", "2b1f3daf74925668", "2dd9d81de1bc8bd0",
    "2f92fb0d3ff61a58", "34a41b7a8ace050c", "352a257ca16e1c69", "36825a9d63f0174d", "3ae88fad759947bf",
    "3b4fb0d8f7e034f6", "4339ee9b2e7eda53", "4c3b6ec495b627d4", "4f7bdc40914020cf", "505021cfd9762d75",
    "552be8efb772b40a", "5611f4df0d41e7cf", "571f8ff4c960d22d", "5b414b9e55bf3805", "607b352d76231a39",
    "61c6e04b0f0e4a4a", "6acb92dd0df36e24", "6ca5bff5de161f62", "6ce848a76fc0393a", "6f5a890134440ca7",
    "723c420de5b63b34", "75992c6f09343f18", "791dfd9b08bbcec4", "79c1319324266d4f", "79eb90d3d4f91349",
    "858d3a47332a3525", "8b377874513a5631", "8bed3c65de0c6eb3", "8eeec122750083f6", "8f79c1903a4d970f",
    "9621b539252016e6", "9855948d54208a21", "99384fc07864bfdd", "9c0b246b5aad396a", "9d6a70936b09404a",
    "9d8d9476e7eae5b3", "a562aedda7c10eb1", "a59ba8d433e2d869", "a7516e29b4cf13f7", "ac7b34741296ec29",
    "ae0f73b5ee49d482", "ae19ade8f42f02fa", "af65cc47f824b0a4", "b7b50879c4a0fd90", "b972f8c9f1792ede",
    "c0098481ed39ac60", "c214a9af6f654186", "c3024ba2369e34bf", "c420090876195eba", "c68dd1bc9a0ec67a",
    "d12abb2bc14c29ad", "d39bf6f51c148b9a", "d3d305e5d443bd4b", "d3f6c8fa4b29c49f", "d4d73b2a25cc9a0e",
    "d4f6d4172f0271d4", "d689292e28b92b6d", "d8752d00f20ea071", "db422b652b3a4a32", "df519158c8932fe8",
    "e82862770b20eaa5", "ea1d65a52e1258e6", "ec40975d606b2b55", "ed5ddf4d46cbef7a", "f336e7c1b054c312",
    "f678454a70734c0c", "fc444b6670ceb6df", "fcea75daab120b43", "fe0b23d2ce52ab25",
})
#: The producer's vendor-banner grammar for ``negotiated.server_software`` (``ssh_session.SERVER_SOFTWARE_RE``).
_SSH_SESSION_SERVER_SOFTWARE_RE = re.compile(
    r"^SSH-(?:2\.0|1\.99)-(?:Cisco|OpenSSH|dropbear|libssh|AsyncSSH|paramiko|RomSShell|Comware|HUAWEI|ROSSSH)[-_]"
    r"[0-9]{1,6}(?:\.[0-9]{1,6}){0,3}(?:p[0-9]{1,3})?$")
_SSH_SESSION_NAME_LIST_SECTIONS = ("client_offered", "server_offered")
_SSH_SESSION_NEGOTIATED_NAMES = ("kex", "host_key_algorithm", "cipher_c2s", "cipher_s2c", "mac_c2s", "mac_s2c")


def _ssh_session_known_name(value: Any) -> bool:
    """True when `value` is a name of the producer's recordable algorithm vocabulary (by digest)."""
    if not isinstance(value, str) or not _SSH_SESSION_TOKEN_RE.match(value):
        return False
    return hashlib.sha256(value.encode("ascii")).hexdigest()[:16] in _SSH_SESSION_ALGORITHM_NAME_DIGESTS


def _ssh_session_positions_conform(doc: dict) -> bool:
    """The record's device-controlled positions: offered lists, negotiated names and refusal names hold only
    vocabulary names, and the banner token matches the vendor grammar. Every other leaf is the walk's business."""
    for section in _SSH_SESSION_NAME_LIST_SECTIONS:
        block = doc.get(section)
        if block is None:
            continue
        if not isinstance(block, dict):
            return False
        for names in block.values():
            if not isinstance(names, list) or not all(_ssh_session_known_name(n) for n in names):
                return False
    negotiated = doc.get("negotiated")
    if negotiated is not None:
        if not isinstance(negotiated, dict):
            return False
        for key in _SSH_SESSION_NEGOTIATED_NAMES:
            value = negotiated.get(key)
            if value is not None and not _ssh_session_known_name(value):
                return False
        banner = negotiated.get("server_software")
        if banner is not None and not (isinstance(banner, str) and _SSH_SESSION_SERVER_SOFTWARE_RE.match(banner)):
            return False
    refusal = doc.get("refusal")
    if refusal is not None:
        if not isinstance(refusal, dict):
            return False
        names = refusal.get("names")
        if names is not None and (not isinstance(names, list)
                                  or not all(_ssh_session_known_name(n) for n in names)):
            return False
    return True


def _ssh_session_record_conforms(raw: bytes) -> bool:
    """True only when ``raw`` is an SSH session record that carries nothing the capture grammar would have
    to scrub: strict JSON, the declared schema, only the schema's field names, only safe leaves, and only
    vocabulary names and a vendor-grammar banner at the device-controlled positions."""
    def _no_constants(_value: str) -> Any:
        raise ValueError("non-standard JSON constant")

    try:
        # _json_no_duplicates raises RedactionVerificationError, a ValueError subclass.
        doc = json.loads(raw.decode("utf-8"), object_pairs_hook=_json_no_duplicates,
                         parse_constant=_no_constants)
    except (UnicodeDecodeError, ValueError, RecursionError):
        return False
    if not isinstance(doc, dict) or doc.get("schema") != _SSH_SESSION_RECORD_SCHEMA:
        return False
    stack: list[tuple[Any, int]] = [(doc, 0)]
    while stack:
        node, depth = stack.pop()
        if depth > 4:
            return False
        if isinstance(node, dict):
            for key, value in node.items():
                if key not in _SSH_SESSION_RECORD_KEYS:
                    return False
                stack.append((value, depth + 1))
        elif isinstance(node, list):
            if len(node) > 64:
                return False
            stack.extend((value, depth + 1) for value in node)
        elif node is None or isinstance(node, bool):
            continue
        elif isinstance(node, int):
            if not 0 <= node <= 1_000_000:
                return False
        elif isinstance(node, str):
            if not _SSH_SESSION_TOKEN_RE.match(node):
                return False
            if (_IPV4_CANDIDATE_RE.search(node) or _IPV6_CANDIDATE_RE.search(node)
                    or _MAC_RE.search(node) or _CISCO_SERIAL_RE.search(node)):
                return False
        else:
            return False                       # floats and anything else are outside the schema
    return _ssh_session_positions_conform(doc)


def is_uncoverable_capture(filename: str) -> str:
    """Why ``filename`` is outside the raw-capture secret grammar, or "" if it is a capture.

    NAME-only half of the rule (see ``_STRUCTURED_CAPTURE_SUFFIXES``); the content half (a NUL
    byte means binary) lives at the read. Public because the ingest census and the copy-back must
    enumerate the SAME set this verifier certifies - three matchers that drift are three holes -
    while the module still refuses to import the producer's implementation.

    THIS FUNCTION IS THE OWNER OF RECORD for the raw-capture name rule. ``ingest._is_raw_capture``
    and ``ingest._copy_back_scrubbed_collection`` CALL it; the producer
    (``cisco_toolkit.html._is_raw_capture``) cannot - ``cisco_toolkit`` must not depend on
    ``webapp``, and this module's independence forbids importing the producer - so it RESTATES this
    body and ``tests/test_redact_collection.py`` pins the two over a generated corpus.

    Which means the PRIMITIVE below is part of the contract, not an implementation detail:
    ``Path(...).suffix`` and ``os.path.splitext(...)[1]`` are NOT interchangeable (``splitext``
    skips every leading dot of the basename, ``suffix`` only the first, so they classify ``..json``
    differently), and ``str.endswith`` is not either (it calls a bare ``.json`` structured, which
    this rule does not). Both wrong restatements have already shipped on the producer side. Change
    the expression here only together with the producer's ``_capture_suffix``."""
    suffix = Path(filename).suffix.casefold()
    if suffix == _SCRUB_TEMP_SUFFIX:
        return "an interrupted rewrite's scratch file, not a capture"
    if suffix in _STRUCTURED_CAPTURE_SUFFIXES:
        return (f"a {suffix.lstrip('.')} serialisation - the raw-capture grammar reads "
                f"line-oriented device config, not structured data")
    return ""


def verify_collection_secret_scrub(root: Path) -> dict[str, Any]:
    """Independently prove every physical raw capture is free of recognised secret residue.

    A producer log count is not a postcondition: a skipped/unreadable file can still make the
    counts look plausible.  This walks the actual tree, rejects links/special files, scans the exact
    bytes through the verifier's grammar, and returns a content-bound root digest.

    "Capture" is decided STRUCTURALLY (``_STRUCTURED_CAPTURE_SUFFIXES``): every text file under the
    root, not only ``*.txt``. The ``.txt`` test that used to stand here was the PRODUCER's own
    selector copied verbatim, which is precisely what this module's docstring forbids - and it cost
    a measured leak, ``backup-config.cfg`` and ``show_tech-support.log`` sitting beside a scrubbed
    ``show_version.txt`` with cleartext ``enable secret`` / ``snmp-server community`` /
    ``username ... password`` values while the run reported SCRUBBED and exited 0.

    Two coverage-honesty rules, because an empty proof used to be indistinguishable from a complete
    one (a tree with zero ``.txt`` files returned ``{"files": 0}`` = success, and the caller's
    ``proof["files"] != census`` equality was 0 != 0, so certifying NOTHING passed every gate):

    * a run that certified NO capture at all RAISES rather than returning an empty success; and
    * every file the rule excluded is returned under ``uncovered`` and bound into the digest, so
      "not examined" can never be read as "examined and clean".
    """
    root = Path(root)
    try:
        root_stat = os.lstat(root)
    except OSError as exc:
        raise RedactionVerificationError("raw capture root cannot be read back") from exc
    if _is_link_or_reparse(root_stat) or not stat.S_ISDIR(root_stat.st_mode):
        raise RedactionVerificationError("raw capture root is not a physical directory")

    rows: list[tuple[str, int, str]] = []
    uncovered: list[tuple[str, str]] = []
    schema_covered: list[str] = []

    def walk_error(exc: OSError) -> None:
        raise RedactionVerificationError(
            "raw capture tree could not be completely enumerated"
        ) from exc

    for dirpath, dirnames, filenames in os.walk(root, onerror=walk_error, followlinks=False):
        directory = Path(dirpath)
        for dirname in list(dirnames):
            child = directory / dirname
            try:
                child_stat = os.lstat(child)
            except OSError as exc:
                raise RedactionVerificationError(
                    "raw capture directory disappeared during verification"
                ) from exc
            if _is_link_or_reparse(child_stat) or not stat.S_ISDIR(child_stat.st_mode):
                raise RedactionVerificationError(
                    "raw capture tree contains a link or non-directory entry"
                )
        for filename in filenames:
            path = directory / filename
            rel = path.relative_to(root).as_posix()
            why = is_uncoverable_capture(filename)
            if why and filename == SSH_SESSION_RECORD_BASENAME:
                # W59 PR-1: covered by its closed schema, or NOT COVERED exactly like any other file.
                with _verified_open(path) as handle:
                    record = _read_all_bounded(handle, _SSH_SESSION_RECORD_MAX_BYTES, path.name)
                if _ssh_session_record_conforms(record):
                    schema_covered.append(rel)
                    continue
                why = ("an SSH session record that does not conform to its closed schema - the capture "
                       "grammar cannot read it and its schema cannot vouch for it")
            if why:
                uncovered.append((rel, why))
                continue
            with _verified_open(path) as handle:
                raw = _read_all_bounded(handle, MAX_ARTIFACT_BYTES, path.name)
            if b"\x00" in raw:
                # Content, not name: a NUL byte means this is a binary container, and the
                # line-oriented grammar below would read noise out of it. Disclosed, never dropped.
                uncovered.append((rel, "binary content (a NUL byte), not a text capture"))
                continue
            text = raw.decode("utf-8", "surrogateescape")
            leaks: list[str] = []
            for pattern in _INLINE_SECRET_RES:
                for match in pattern.finditer(text):
                    secret = match.group("secret").strip("\"'")
                    if secret.casefold() != _PLACEHOLDER:
                        _append(leaks, "credential value", str(path.relative_to(root)))
            for pattern in _STRICT_SECRET_LINE_RES:
                for match in pattern.finditer(text):
                    value = match.group("value").strip()
                    if value[:1] in {'"', "'"} and value[-1:] == value[:1]:
                        value = value[1:-1].strip()
                    if value.casefold() != _PLACEHOLDER:
                        _append(leaks, "credential residue", str(path.relative_to(root)))
            if leaks:
                raise RedactionVerificationError(
                    "raw capture secret verification found residue: " + "; ".join(leaks[:8])
                )
            rows.append((rel, len(raw), hashlib.sha256(raw).hexdigest()))
    if not rows:
        raise RedactionVerificationError(
            "raw capture verification certified NOTHING: no text capture file was found under the "
            "collection root, so this proof is empty and an empty proof must not be reported as a "
            "clean result"
            + (f" ({len(uncovered)} file(s) were outside the verifier's scope: "
               + ", ".join(rel for rel, _why in sorted(uncovered)[:8]) + ")" if uncovered else "")
        )
    uncovered.sort()
    schema_covered.sort()
    # The schema-covered list joins the digest only when non-empty, so a proof over a collection without
    # session records keeps its pre-W59 digest.
    payload: list[Any] = [rows, uncovered] + ([schema_covered] if schema_covered else [])
    encoded = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    return {
        "files": len(rows),
        "sha256": hashlib.sha256(encoded).hexdigest(),
        # Coverage honesty travels WITH the proof: a caller that reads only `files` still cannot
        # print "verified" over a folder where N files were never looked at, because `uncovered`
        # is bound into `sha256` and is right there in the same dict.
        "uncovered": [{"file": rel, "reason": why} for rel, why in uncovered],
        # W59 PR-1: SSH session records the closed schema vouches for (not scanned as captures, not
        # NOT COVERED either). Bound into `sha256` above.
        "schema_covered": list(schema_covered),
    }
