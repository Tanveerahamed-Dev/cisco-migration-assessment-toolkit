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
import bisect
import hashlib
import io
import itertools
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
#: W60 -- THE CREDENTIAL CHECKS, stated independently of the producer.
#:
#: The producer (``cisco_toolkit.html._redact_config_values``) runs two passes over every line of a
#: raw capture: a credential GRAMMAR that replaces the value of each known form, and a RESIDUAL SWEEP
#: that, after the first credential keyword or credential field name of a line, replaces EVERY token
#: that is not in a closed structural allowlist (plus private-key blocks, URL userinfo, credential
#: headers, shell arguments, table and CSV columns, credential blocks, terminal wraps and high-entropy
#: tokens). This module restates both guarantees -- it may not import them -- and a raw capture is
#: certified only if every line satisfies BOTH:
#:
#: * grammar: the value slot of every recognised form is the placeholder ("credential value"); and
#: * sweep: after the first non-void credential keyword or credential field name, every token is the
#:   placeholder or structural ("credential residue"), and no private-key body, URL secret, shell
#:   credential argument, credential column, credential block line, wrapped value or high-entropy
#:   token survives.
#:
#: The sweep's allowlist is CLOSED and exact: an unknown word after a keyword REFUSES. That is the
#: deliberate failure direction -- a refused scrub is re-checked by a person, a certified leak is not.
#: The lexical model (separators, line ends) is the producer's, restated: lines end ONLY at CR/LF; VT,
#: FF, FS..US, NEL, NBSP and every Unicode space, LINE/PARAGRAPH SEPARATOR, a BOM and a non-UTF-8 byte
#: (U+DC80..U+DCFF after surrogateescape) separate tokens. tests/test_redaction_grammar_corpus.py pins
#: every closed list below EQUAL to the producer's and runs the shared adversarial corpus through both.
#:
#: Two further checks are this verifier's OWN and have no counterpart list in the producer, so a gap
#: in the producer's lists fails closed instead of being certified by its restatement
#: (`_independent_credential_findings`): every JSON object embedded in a capture is PARSED and every
#: string or number under a credential-named key (``_is_secret_key``, the snapshot rule) must be the
#: placeholder or structure; and every ``name: value`` / ``name=value`` / ``"name": value`` field whose
#: name ``_is_secret_key`` calls a credential must carry the placeholder or structure.
_CRED_WS = (" \t\x0b\x0c\x1c-\x1f\x85\xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff"
            "\udc80-\udcff")
_CRED_H1 = "[" + _CRED_WS + "]"
_CRED_HWS = _CRED_H1 + "+"
_CRED_NWS = "[^" + _CRED_WS + "\r\n]"
_CRED_NWSQ = "[^" + _CRED_WS + "\r\n\"']"
_CRED_WS_RE = re.compile(_CRED_HWS)
_CRED_WS_CHARS = (" \t\x0b\x0c\x1c\x1d\x1e\x1f\x85\xa0\u1680\u2028\u2029\u202f\u205f\u3000\ufeff"
                  + "".join(map(chr, range(0x2000, 0x200b))) + "".join(map(chr, range(0xdc80, 0xdd00))))
_CRED_EDGE_WS_RE = re.compile("^" + _CRED_HWS + "|" + _CRED_HWS + r"\Z")
_CRED_LINE_BREAK_RE = re.compile(r"\r\n|\r|\n")
#: Lines longer than this are not read by the GRAMMAR (the producer's own bound); the sweep reads all.
_CRED_GRAMMAR_MAX_LINE = 2048


def _v(pattern: str) -> str:
    """``{H}`` a separator run, ``{h}`` one separator, ``{S}`` a token character, ``{Q}`` a token
    character that is not a quote -- the lexical model above."""
    return (pattern.replace("{H}", _CRED_HWS).replace("{h}", _CRED_H1)
            .replace("{S}", _CRED_NWS).replace("{Q}", _CRED_NWSQ))


def _cred_lines(text: str) -> list[str]:
    return _CRED_LINE_BREAK_RE.split(text)


def _cred_has_next(lines: list[str]) -> list[bool]:
    """``has_next[i]``: a non-blank line follows line ``i`` (the producer's terminal-wrap input)."""
    out, seen = [False] * len(lines), False
    for i in range(len(lines) - 1, -1, -1):
        out[i] = seen
        seen = seen or bool(_CRED_WS_RE.sub("", lines[i]))
    return out


_CRED_HASH = (r"(?:(?:hmac-|keyed-|ietf-)?(?:md5|sha(?:-?(?:1|224|256|384|512))?)"
              r"|(?:hmac-)?sha2-(?:224|256|384|512)|cmac-aes(?:-?(?:128|256))?|aes-(?:128|256)-cmac)")
_CRED_TYPE = r"(?:10|[0-9])"
_CRED_TYPE_THEN_VALUE = r"(?:10|[0-9])(?={H}{S})"
_CRED_TYPE_DIGIT_RE = re.compile(r"(?:10|[0-9])")
_CRED_PROSE_STOPS = frozenset({
    "a", "an", "the", "to", "for", "with", "of", "in", "on", "at", "by", "from", "and", "or", "not", "no",
    "is", "are", "was", "were", "be", "been", "being", "must", "should", "shall", "will", "can", "cannot",
    "may", "might", "has", "have", "had", "this", "that", "these", "those", "it", "its", "as", "if", "when",
    "which", "who", "you", "your", "our", "their", "all", "any", "every", "each", "only", "also", "here",
    "there", "than", "so", "but", "into", "via", "per", "without", "within", "none", "configured",
    "enabled", "disabled", "required", "expired", "failed", "failure", "mismatch", "changed", "set",
})
_CRED_PROSE_START_RE = re.compile(_v(r'"?{h}*(?:=>|[:=]){h}*|{H}'))
_CRED_PLAIN_START_RE = re.compile(_CRED_HWS)
#: A value token; a bare value never runs through the banner delimiter '^C'.
_CRED_TOKEN_RE = re.compile(_v(r""""(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|(?:(?!\^C){S})+"""))
_CRED_PEM_ARMOR_RE = re.compile(_v(r"""["']?-{4,5}{h}?BEGIN{h}"""))
_CRED_ACCESS_NEXT = r"(?:ro|rw|view)(?:{h}|\Z)"
_CRED_PEER_NEXT = r"(?:address|hostname)(?:{h}|\Z)"
#: Round 3: a qualifier (type digit aside) or a soft stop word that ends the clause -- the end of the line,
#: or directly before one of these clause-continuing words -- IS the value (the producer's
#: ``_REDACT_CLAUSE_END``), and a YAML block-scalar indicator is never one.
_CRED_CLAUSE_END = r"(?:privilege|role|authorization){H}{S}"
_CRED_KEY_ENDS = r"address|hostname"
_CRED_BLOCK_INDICATOR_RE = re.compile(r"[|>][-+0-9]{0,3}")
#: FortiGate's encrypted-value marker, exactly so: like a type digit, it starts a WRAPPED value when it
#: ends a line that more lines follow.
_CRED_WRAP_ENC = "ENC"
_CRED_FOLLOW_RE = re.compile(_v(r"{H}(?!{h})(?={S})"))


def _cred_clause_end(ends: str = "") -> str:
    return r"(?:(?:" + ends + r"){H}{S}|" + _CRED_CLAUSE_END + r")" if ends else _CRED_CLAUSE_END


def _cred_step(step: str, ends: str = "") -> str:
    """One qualifier of a run: it counts only when another, non-clause-continuing token follows it."""
    return r"(?:" + step + r"){H}(?={S})(?!" + _cred_clause_end(ends) + r")"


#: The families a terminal wrap is followed across: exactly the forms whose origin/main 6390b66c pattern
#: crossed a line end (the producer's ``_REDACT_SECRET_CROSS``, restated by name).
_CRED_CROSS_FAMILIES = frozenset({"fortigate set", "snmp host community", "snmp community", "community block",
                                  "community prose", "password", "tacacs/radius key", "key-string", "pre-shared-key",
                                  "set-key", "key", "nhrp authentication", "fhrp authentication text",
                                  "aireos radius/tacacs", "aireos user"})


class _CredFamily:
    """One keyword family of the GRAMMAR: where it starts, what may stand between keyword and value
    (an alternation repeated, or an ORDERED ``run``), and which values are structural.

    ``artifact`` lists the LINE-START anchors under which the family is also read in shareable
    artifacts (snapshot strings, OOXML text, HTML), where authored prose shares the surface.
    ``stop_unless``: a stop word followed by this is the VALUE ('community all RO'). ``stops`` are HARD
    (structural even at the end of the line); the prose stop words and ``soft`` are SOFT (a stop only
    when another token that does not continue the clause follows). ``ends``: the family's own
    clause-continuing words besides ``_CRED_CLAUSE_END``."""

    __slots__ = ("name", "anchor", "artifact", "qualifiers", "stops", "soft", "prose", "address_is_structural",
                 "value_guard", "stop_unless", "cross", "clause_end")

    def __init__(self, name: str, anchor: str, qualifiers: Iterable[str] = (), stops: Iterable[str] = (),
                 *, prose: bool = False, artifact: Iterable[str] = (), address_is_structural: bool = False,
                 run: str = "", value_guard: str = "", stop_unless: str = "", soft: Iterable[str] = (),
                 ends: str = ""):
        steps = list(qualifiers) + ([r"=>|[:=]|is"] if prose else [])
        self.name = name
        #: followed across a terminal wrap (`_cred_cross_line_findings`)
        self.cross = name in _CRED_CROSS_FAMILIES
        self.anchor = re.compile(_v(anchor), re.IGNORECASE)
        self.artifact = tuple(re.compile(pattern, re.IGNORECASE) for pattern in artifact)
        if not run:
            run = r"(?:" + _cred_step("|".join(steps), ends) + r")*" if steps else r""
        self.qualifiers = re.compile(_v(run), re.IGNORECASE)
        soft_words = frozenset(word.casefold() for word in soft)
        self.stops = frozenset(word.casefold() for word in stops) - soft_words
        self.soft = (soft_words | _CRED_PROSE_STOPS) - self.stops
        self.prose = prose
        self.address_is_structural = address_is_structural
        self.value_guard = re.compile(_v(value_guard), re.IGNORECASE) if value_guard else None
        self.stop_unless = re.compile(_v(r"{H}" + stop_unless), re.IGNORECASE) if stop_unless else None
        self.clause_end = re.compile(_v(_cred_clause_end(ends)), re.IGNORECASE)


_CRED_COMMUNITY_QUALIFIERS = (
    r"strings?", r"read", r"write", r"cipher", r"plain", r"clear", r"encrypted",
    r"(?:name|index|securityname){h}*:", r"accessmode{H}(?:ro|rw)", r"ipaddr{H}{S}+{H}{S}+",
    r"mode{H}(?:enable|disable)", r"[08](?={H}{S})",
)
_CRED_COMMUNITY_STOPS = ("name", "names", "list", "complexity-check", "attribute")


def _cred_community_run(prose: bool) -> str:
    steps = list(_CRED_COMMUNITY_QUALIFIERS) + ([r"(?:=>|[:=]|is)"] if prose else [])
    return (r"(?:(?:create|delete|(?<=snmp-agent{h}community{h})(?:read|write)){H}(?={S})"
            + r"|(?:" + "|".join(steps) + r")(?={H}(?!" + _CRED_ACCESS_NEXT + r"){S}){H})*")


_CRED_KEY_ENCODINGS = r"(?:ENC|encrypted|clear|ascii|hex|cipher|plain|text|--|config-key|password-encrypt)"
_CRED_KEY_RUN = (
    r"(?:\d{1,10}{H}(?=" + _CRED_HASH + r"(?:{H}|\Z)|--(?:{H}|\Z)))?"
    r"(?:" + _cred_step(_CRED_HASH, _CRED_KEY_ENDS) + r")?"
    r"(?:" + _cred_step(_CRED_KEY_ENCODINGS, _CRED_KEY_ENDS) + r")*"
    r"(?:" + _CRED_TYPE_THEN_VALUE + r"{H}(?!" + _cred_clause_end(_CRED_KEY_ENDS) + r"))?"
    r"(?:" + _cred_step(_CRED_KEY_ENCODINGS, _CRED_KEY_ENDS) + r")*")
_CRED_AUTH_MODE_RUN = (
    r"(?:" + _cred_step(_CRED_HASH + r"|simple|hmac-sha256") + r")?"
    r"(?:key-id{H}\d{1,10}{H}|\d{1,10}{H}(?={S}))?"
    r"(?:" + _cred_step(r"cipher|plain|usual|nonstandard") + r")*")
_CRED_IPV6_TEXT = (
    r"(?<![:.\w])(?:(?:[0-9A-Fa-f]{1,4}:){7}[0-9A-Fa-f]{1,4}|(?:[0-9A-Fa-f]{1,4}:){1,7}:"
    r"|(?:[0-9A-Fa-f]{1,4}:){1,6}:[0-9A-Fa-f]{1,4}|(?:[0-9A-Fa-f]{1,4}:){1,5}(?::[0-9A-Fa-f]{1,4}){1,2}"
    r"|(?:[0-9A-Fa-f]{1,4}:){1,4}(?::[0-9A-Fa-f]{1,4}){1,3}|(?:[0-9A-Fa-f]{1,4}:){1,3}(?::[0-9A-Fa-f]{1,4}){1,4}"
    r"|(?:[0-9A-Fa-f]{1,4}:){1,2}(?::[0-9A-Fa-f]{1,4}){1,5}|[0-9A-Fa-f]{1,4}:(?::[0-9A-Fa-f]{1,4}){1,6}"
    r"|:(?::[0-9A-Fa-f]{1,4}){1,7})(?:%[0-9A-Za-z]+)?(?![:.\w])")
_CRED_FAMILIES: tuple[_CredFamily, ...] = (
    _CredFamily("fortigate set", r"\bset{H}(?:passwd|password|psksecret|psksecret-remote|secret|"
                r"secondary-secret|tertiary-secret|private-key|passphrase|auth-pwd|priv-pwd|sae-password|key|"
                r"authentication-key|auth-string|ppk-secret|eap-password|api-key|secret-key|key-string)\d{0,2}",
                (r"ENC",), artifact=(r"^\s*set\s+(?:passwd|psksecret|password|private-key|passphrase)",)),
    _CredFamily("snmp user auth", r"\bsnmp-server{H}user{H}[^\r\n]{0,200}?{h}auth",
                (_CRED_HASH, r"clear", r"encrypted"), value_guard=r"\d{1,3}{h}*\Z", ends=r"priv"),
    _CredFamily("snmp user priv", r"\bsnmp-server{H}user{H}[^\r\n]{0,200}?{h}priv",
                (r"3?des(?:56)?", r"aes(?:-?(?:128|192|256))?", r"128", r"192", r"256", r"clear", r"encrypted"),
                value_guard=r"\d{1,3}{h}*\Z"),
    _CredFamily("aireos v3user auth", r"\bconfig{H}snmp{H}v3user{H}create{H}{S}+{H}(?:ro|rw)"
                r"{H}(?:none|hmacmd5|hmacsha){H}(?:none|des|aescfb128|aes)"),
    _CredFamily("aireos v3user priv", r"\bconfig{H}snmp{H}v3user{H}create{H}{S}+{H}(?:ro|rw)"
                r"{H}(?:none|hmacmd5|hmacsha){H}(?:none|des|aescfb128|aes){H}{S}+"),
    _CredFamily("snmp host community", r"\bsnmp-server{H}host{H}{S}+",
                (r"vrf{H}{S}+", r"traps?", r"informs?", r"version{H}(?:1|2c)", r"clear", r"encrypted"),
                ("version", "use-vrf", "filter-vrf", "source-interface", "vrf", "community", "poll",
                 "udp-port"), address_is_structural=True, artifact=(r"^\s*snmp-server\s+host\s+\S+",),
                soft=("version", "use-vrf", "filter-vrf", "source-interface", "vrf", "community", "poll",
                      "udp-port")),
    _CredFamily("snmp community", r"\b(?:snmp-server|snmp-agent|snmp)(?:{H}[^\r\n]{0,200}?)?{H}community",
                (), _CRED_COMMUNITY_STOPS, prose=True, run=_cred_community_run(True),
                stop_unless=_CRED_ACCESS_NEXT, artifact=(r"^\s*snmp-server\s+community",)),
    # Junos 'community X {'. Not prose: a bare 'Community:' is the BGP path-attribute label.
    _CredFamily("community block", r"^{h}*community", (), _CRED_COMMUNITY_STOPS, run=_cred_community_run(False),
                stop_unless=_CRED_ACCESS_NEXT, artifact=(r"^\s*community",)),
    _CredFamily("community prose", r"\bcommunity(?={H}strings?\b|{H}(?:name|index|securityname){h}*:)",
                (), _CRED_COMMUNITY_STOPS, prose=True, run=_cred_community_run(True),
                stop_unless=_CRED_ACCESS_NEXT),
    _CredFamily("named community", r"\b(?:community-map|community-name|snmp-community-string|trap-group)"),
    # The port may already be the placeholder: the sweep replaces it (it is no closed-list word).
    _CredFamily("aireos radius/tacacs", r"\bconfig{H}(?:radius|tacacs){H}(?:auth|acct|athr){H}add"
                r"{H}\d+{H}{S}+{H}(?:\d+|<redacted>)", (r"ascii", r"hex")),
    _CredFamily("aireos user", r"\bconfig{H}(?:mgmtuser|netuser){H}(?:add|password){H}{S}+"),
    _CredFamily("password", r"\b(?:password|passwd|secret|passphrase|pass-phrase|enablesecret)"
                r"(?<!mgmtuser password)(?<!netuser password)",
                (r"level{H}\d+", _CRED_TYPE_THEN_VALUE, _CRED_HASH, r"scrypt", r"ENC", r"encrypted", r"clear",
                 r"cipher", r"plain", r"simple", r"irreversible-cipher", r"hashed", r"text", r"fallback"),
                ("encryption", "encrypt", "expiration", "expiry", "policy", "recovery", "min-length",
                 "max-length", "minimum-length", "maximum-length", "prompt", "history", "change-type",
                 "format", "aging", "complexity", "strength-check", "keychain", "key-chain", "management",
                 "encryption-key", "keyboard", "publickey", "option", "rollover", "authentication", "strength",
                 "reset", "required"),
                prose=True,
                artifact=(r"^\s*(?:enable\s+)?(?:password|secret)",
                          r"^\s*(?:username|user)\s+\S+(?:\s+(?:privilege\s+\d+|role\s+\S+|algorithm-type\s+\S+"
                          r"|view\s+\S+))*\s+(?:password|secret)")),
    _CredFamily("huawei securityname", r"\bsecurityname", (r"cipher", r"plain")),
    _CredFamily("tacacs/radius key", r"\b(?:tacacs-server|radius-server){H}(?:[^\r\n]{0,200}?{h})?key",
                run=r"(?:" + _CRED_TYPE_THEN_VALUE + r"{H})?",
                artifact=(r"^\s*(?:tacacs-server|radius-server)\s+(?:.*?\s)?key",)),
    _CredFamily("key-string", r"\bkey-string",
                run=(r"(?:" + _cred_step(r"password|clear|encrypted|ENC") + r")*(?:" + _CRED_TYPE_THEN_VALUE
                     + r"{H}(?!" + _CRED_CLAUSE_END + r"))?"),
                artifact=(r"^\s*key-string",)),
    _CredFamily("key-octet-string", r"\bkey-octet-string", run=r"(?:" + _CRED_TYPE_THEN_VALUE + r"{H})?"),
    _CredFamily("pre-shared-key", r"\bpre-shared-key",
                (r"local", r"remote", r"ascii-text", r"hexadecimal", r"cipher", r"simple", r"plain", r"key",
                 _CRED_TYPE_THEN_VALUE),
                ("address", "hostname", "key-chain", "keychain", "ckn", "cak", "keyring"),
                artifact=(r"^\s*pre-shared-key",), soft=("address", "hostname")),
    _CredFamily("shared-key", r"(?<![\w-])shared-key", (r"cipher", r"simple", r"plain", _CRED_TYPE_THEN_VALUE)),
    _CredFamily("macsec cak/ckn", r"\b(?:cak|ckn)"),
    _CredFamily("wpa-psk", r"\bwpa2?-psk", (r"ascii", r"hex", _CRED_TYPE_THEN_VALUE)),
    _CredFamily("set-key", r"\bset-key", (r"ascii", r"hex", _CRED_TYPE_THEN_VALUE)),
    _CredFamily("nhrp authentication", r"\bnhrp{H}authentication", run=r"(?:" + _CRED_TYPE_THEN_VALUE + r"{H})?"),
    _CredFamily("fhrp authentication", r"\b(?:standby|vrrp|glbp)(?:{H}\d+)?(?:{H}peer)?{H}"
                r"authentication", (), ("key-chain", "key-string", "keychain", "key"),
                run=r"(?:(?:text|md5|ietf-md5)(?:{H}|\Z))*"),
    _CredFamily("block authentication text", r"^{h}*authentication(?={H}text{h})", (r"text",)),
    _CredFamily("authentication-mode", r"\b(?:area-|domain-)?authentication-mode", run=_CRED_AUTH_MODE_RUN,
                stops=("keychain", "key-chain", "hwtacacs", "radius", "local", "aaa", "password", "scheme",
                       "none")),
    _CredFamily("privacy-mode", r"\bprivacy-mode", (r"des56", r"3des", r"aes\d*", r"cipher", r"plain")),
    _CredFamily("ospfv3 ipsec", r"\b(?:authentication|encryption){H}ipsec{H}spi{H}\d+",
                (r"md5", r"sha1", r"esp", r"aes-cbc", r"3des", r"des", r"null", r"128", r"192", r"256",
                 _CRED_TYPE_THEN_VALUE)),
    _CredFamily("eigrp hmac-sha-256", r"\bauthentication{H}mode{H}hmac-sha-256",
                run=r"(?:" + _CRED_TYPE_THEN_VALUE + r"{H})?"),
    _CredFamily("show standby text", r"\bauthentication{H}text,{H}string"),
    # Not a prose family: 'Key: U - Unicast, B - Broadcast' is the 'show storm-control' legend. A bare
    # 'key N' (0-15) ending its line is a key ID unless it follows 'authentication-'/'message-digest-'.
    _CredFamily("key", r"\bkey(?<!private-key)(?<!shared-key)(?<!public-key)(?<!ssh-key)"
                r"(?:(?<=authentication-key)|(?<=digest-key)|(?!{H}(?:1[0-5]|[0-9]){h}*\Z))", run=_CRED_KEY_RUN,
                stops=("chain", "local", "remote", "generate", "zeroize", "import", "export", "id", "name", "data",
                       "change", "type", "usage", "exchange", "pair", "length", "size", "sizes", "lifetime",
                       "rollover", "hash", "label", "storage", "ring", "management", "encryption", "mode",
                       "mypubkey", "pubkey", "pubkey-chain", "server", "algorithm", "algorithms", "recovery",
                       "string", "prefer", "source", "version", "minpoll", "maxpoll", "burst", "iburst", "vrf",
                       "use-vrf", "rsa", "dsa", "ecdsa", "ed25519", "inbound", "outbound", "format",
                       "password-encrypt", "ascii"),
                value_guard=r"\d{1,10}[,;](?={h}|\Z)|-{3,}(?:{h}|\Z)", stop_unless=_CRED_PEER_NEXT,
                artifact=(r"^\s*crypto\s+isakmp\s+key",), soft=("version", "local", "remote"),
                ends=_CRED_KEY_ENDS),
    _CredFamily("fhrp authentication text",
                r"\b(?:standby|vrrp|glbp)(?:{H}\d+)?(?:{H}peer)?{H}authentication{H}text"),
)
#: A literal every match of a family's anchor contains (compared casefolded, a superset of the anchors'
#: IGNORECASE matching): a family is skipped on a line holding none of its needles. Speed only.
_CRED_FAMILY_NEEDLES = {
    "fortigate set": ("set",), "snmp user auth": ("snmp-server",), "snmp user priv": ("snmp-server",),
    "aireos v3user auth": ("v3user",), "aireos v3user priv": ("v3user",),
    "snmp host community": ("snmp-server",), "snmp community": ("community",),
    "community block": ("community",), "community prose": ("community",),
    "named community": ("community-map", "community-name", "snmp-community-string", "trap-group"),
    "aireos radius/tacacs": ("config",), "aireos user": ("config",),
    "password": ("password", "passwd", "secret", "passphrase", "pass-phrase"),
    "huawei securityname": ("securityname",), "tacacs/radius key": ("-server",), "key-string": ("key-string",),
    "key-octet-string": ("key-octet-string",), "pre-shared-key": ("pre-shared-key",),
    "shared-key": ("shared-key",), "macsec cak/ckn": ("cak", "ckn"), "wpa-psk": ("-psk",),
    "set-key": ("set-key",), "nhrp authentication": ("nhrp",), "fhrp authentication": ("standby", "vrrp", "glbp"),
    "block authentication text": ("authentication",), "authentication-mode": ("authentication-mode",),
    "privacy-mode": ("privacy-mode",), "ospfv3 ipsec": ("ipsec",),
    "eigrp hmac-sha-256": ("hmac-sha-256",), "show standby text": ("string",), "key": ("key",),
    "fhrp authentication text": ("standby", "vrrp", "glbp"),
}
#: Cheap prefilter: a line that names none of these words cannot start any grammar family above.
_CRED_PREFILTER_RE = re.compile(
    r"password|passwd|secret|passphrase|pass-phrase|community|key|auth|priv|psk|cak|ckn|config|snmp|"
    r"securityname|trap-group|encryption")                 # searched in the CASEFOLDED line

# ---- THE RESIDUAL-SWEEP GUARANTEE, restated (every list CLOSED and equal to the producer's). ----
_SWEEP_KEYWORDS = (
    r"(?:proxy-)?authorization(?=\"?{h}*:)", r"(?:set-)?cookie(?=\"?{h}*:)",
    r"x-[a-z0-9-]{0,64}?(?:token|api-?key|auth[a-z0-9-]{0,32}|secret|password)(?=\"?{h}*:)",
    r"snmp-server{H}host", r"nhrp{H}authentication",
    r"(?:standby|vrrp|glbp)(?:{H}\d+)?(?:{H}peer)?{H}authentication",
    r"authentication{H}(?:text|mode)", r"(?:authentication|encryption){H}ipsec{H}spi",
    r"rmon{H}event", r"event{H}manager{H}environment", r"cli{H}command",
    r"(?:user|groupname):(?=[^\r\n]*?security)",
    r"ldap-server{H}authentication{H}manager", r"lte{H}profile{H}create",
    r"(?:login|enable|pap|chap|arap|opap|ms-chap|global){h}*={h}*(?:cleartext|des|crypt)",
    r"^{h}*\d{1,5}{H}(?:md5|sha1|sha|sha256|sha384|sha512|aes128cmac|aes-128-cmac)(?={h}|\Z)",
    r"pin(?={H}(?:\d{1,16}|<redacted>)(?:{h}|\Z))",
    r"[a-z0-9]{0,64}_(?:pw|pwd|pass|passwd|password|secret|token|key|community|communities|psk|credentials?"
    r"|authtok)",
    r"(?:area-|domain-)?authentication-(?:key(?:id)?|mode)", r"message-digest-key", r"server-key",
    r"encrypted[-_]?password", r"plain-text-password(?:-value)?", r"hello-authentication",
    r"text-authentication", r"rootpw", r"bindpw",
    r"priv(?={H}(?:3?des(?:56)?|aes(?:-?(?:128|192|256))?|aes-cbc)(?:{h}|\Z))",
    r"^{h}*(?-i:authentication)(?={H}(?:(?![:=]){S})+{h}*\Z)",
    r"[a-z0-9]{1,32}(?:-[a-z0-9]{1,32}){0,6}-pwd?",
    r"private[-_]?key", r"secret[-_]?key", r"api[-_]?key", r"pre-?shared-?key", r"key[-_]?string",
    r"key-octet-string", r"community[-_]?(?:string|name|map)", r"pass-phrase", r"privacy-mode",
    r"password", r"passwd", r"passphrase", r"passcode", r"enablesecret", r"secret", r"psksecret", r"psk",
    r"phash", r"(?:auth|priv)-?pwd", r"community", r"rocommunity6?", r"rwcommunity6?",
    r"com2sec6?", r"trapcommunity", r"trap2?sink", r"informsink", r"trap-group", r"securityname",
    r"createuser", r"key", r"token", r"idtoken", r"bearer", r"ssws", r"auth", r"authkey", r"cipher",
    r"plain", r"ascii", r"hex", r"set-key", r"cak", r"ckn", r"v3user", r"mgmtuser", r"netuser", r"pkcs12",
    r"cvauth", r"ingestauth", r"credentials?",
)
_SWEEP_KW_RE = re.compile(_v(
    r"(?:(?<![A-Za-z0-9])|(?-i:(?<=[a-z0-9])(?=[A-Z])))(?P<kw>" + "|".join(_SWEEP_KEYWORDS)
    + r")(?:\d{1,3})?(?![0-9_-]|(?-i:[a-z])|(?-i:(?<=[A-Z])[A-Z]))"),
    re.IGNORECASE)
_SWEEP_VOID_NEXT = {
    "key": frozenset({"chain", "generate", "zeroize", "mypubkey", "pubkey-chain", "pair", "name", "data", "id",
                      "storage", "type", "usage", "change", "size", "lifetime", "identifier", "encipherment",
                      "agreement", "link", "uplink", "vlan"}),
    "password": frozenset({"encryption", "strength-check", "strength", "policy", "expiry", "expiration",
                           "minimum-length", "maximum-length", "min-length", "max-length", "complexity",
                           "history", "aging", "recovery", "prompt", "change-type", "format", "management",
                           "keyboard", "reset"}),
    "community": frozenset({"complexity-check", "attribute"}),
    "pre-shared-key": frozenset({"key-chain", "keychain"}),
    **dict.fromkeys(("authentication-mode", "area-authentication-mode", "domain-authentication-mode"),
                    frozenset({"hwtacacs", "radius", "local", "aaa", "password", "scheme", "keychain",
                               "key-chain", "none"})),
    # the engine security check ID that spells a keyword, before a severity or a check status (the
    # producer derives it from parse._SEC_CHECKS; the restatement is pinned equal)
    "weak-user-pw": frozenset({"high", "medium", "low", "fail", "pass", "na"}),
    "auth": frozenset({"sign", "verify", "via", "add", "priv(enforce"}),
    "credentials": frozenset({"caching"}),
    "psk": frozenset({"tunnel"}),
    "authentication": frozenset({
        "open", "periodic", "chap", "pap", "ms-chap", "ms-chap-v2", "eap", "message-digest", "null", "none",
        "md5", "text", "sha", "sha1", "mode", "key-chain", "keychain", "local", "radius", "tacacs", "tacacs+",
        "enable", "enabled", "disable", "disabled", "required", "optional", "ipsec", "list", "default",
        "dot1x", "mab", "peer", "failure", "success", "priority", "order", "keyed-md5", "hmac-md5",
        "hmac-sha-1", "simple", "plain", "cipher", "level-1", "level-2", "send-only", "check", "multi-auth",
        "multi-host", "single-host", "multi-domain", "fallback", "event", "timer", "violation",
        "control-direction", "port-control", "host-mode", "sequence", "authorize", "server", "type",
        "protocol", "callin", "callout", "optional-auto", "required-auto"}),
}
_SWEEP_VOID_PREV = {"community": frozenset({"set", "match", "policy-options", "then", "from"}),
                    "key": frozenset({"trusted-", "public-", "ssh-", "host-"}),
                    "cipher": frozenset({"crypto"}),
                    "psk": frozenset({"sign", "verify"})}
_SWEEP_EDGE = "\"'`()[]{}<>;:,."
_SWEEP_KEEP = "\"'`()[]{};:,."
_SWEEP_ALLOW = frozenset({
    *(str(n) for n in range(16)), "128", "192", "256", "2c",
    "level", "type", "enc", "encrypted", "clear", "cipher", "plain", "simple", "ascii", "hex", "text",
    "irreversible-cipher", "hashed", "scrypt", "pbkdf2", "nt-encrypted", "mschap", "localizedkey",
    "localizedv2key", "auto", "config-key", "password-encrypt", "ascii-text", "hexadecimal", "usual",
    "nonstandard", "key-id", "md5", "sha", "sha1", "sha-1", "sha2", "sha224", "sha256", "sha384", "sha512",
    "sha-224", "sha-256", "sha-384", "sha-512", "sha2-224", "sha2-256", "sha2-384", "sha2-512", "hmac-md5",
    "hmac-sha", "hmac-sha1", "hmac-sha-1", "hmac-sha256", "hmac-sha-256", "hmac-sha384", "hmac-sha-384",
    "hmac-sha512", "hmac-sha-512", "hmac-sha2-224", "hmac-sha2-256", "hmac-sha2-384", "hmac-sha2-512",
    "keyed-md5", "ietf-md5", "cmac-aes", "aes", "aes128", "aes192", "aes256",
    "aes-128", "aes-192", "aes-256", "aes-cbc", "aescfb128", "des", "des56", "3des", "hmacmd5", "hmacsha",
    "none", "null", "esp", "ah", "ah-md5", "inbound", "outbound", "authenticator", "auth", "priv", "key",
    "set-key", "key-string", "key-chain", "keychain", "fallback", "--", "authentication-mode", "privacy-mode",
    "cryptographic-algorithm", "aes-128-cmac", "aes-256-cmac", "aes_128_cmac", "aes_256_cmac", "spi",
    "lifetime", "bit", "chain", "format",
    "ro", "rw", "read", "write", "read-only", "read-write", "view", "access", "acl", "ipv4", "ipv6",
    "version", "v1", "v2c", "v3", "noauth", "authpriv", "authnopriv", "traps", "informs", "trap", "inform",
    "udp-port", "context", "group", "user", "security", "model", "security-model", "create", "delete",
    "accessmode", "ipaddr", "mode", "enable", "disable", "string", "strings", "name", "index", "notify",
    "sdrowner", "systemowner", "lobby-admin", "private-netmanager", "ext-vb", "targets", "clients",
    "authorization", "members", "description", "owner", "log",
    "aaa_server", "adslline", "alarms", "atm", "auth-framework", "bfd", "bgp", "bgp4-mib", "bridge",
    "bstun", "bulkstat", "call-home", "casa", "cbgp2", "ccme", "cef", "cluster", "cnpd", "config",
    "config-copy", "config-ctid", "cpu", "cts", "dhcp", "dial", "dlsw", "dot1x", "ds1", "dsp", "eigrp",
    "energywise", "entity", "entity-diag", "entity-qfp", "entity-sensor", "entity-state", "envmon",
    "errdisable", "ethernet", "ethernet-cfm", "event-manager", "firewall", "flash", "flex-links",
    "flowmon", "frame-relay", "fru-ctrl", "hsrp", "ike", "ipmobile", "ipmulticast", "ipsec", "ipsla",
    "isakmp", "isdn", "isis", "l2tun", "l2tun-pseudowire-status", "l2tun-session", "license", "llc2",
    "local-auth", "mac-notification", "memory", "mpls", "mpls-ldp", "mpls-traffic-eng", "mpls-vpn", "msdp",
    "mvpn", "nhrp", "ospf", "ospfv3", "pim", "pki", "port-security", "power-ethernet", "pppoe", "pw", "rep",
    "resource-policy", "rf", "rmon", "rsvp", "rtr", "sdlc", "smart-license", "snmp", "sonet", "srp",
    "stackwise", "storm-control", "stpx", "stun", "syslog", "transceiver", "trustsec", "tty",
    "vlan-membership", "vlancreate", "vlandelete", "voice", "vrfmib", "vrrp", "vstack", "vtp", "wireless",
    "x25", "xgcp",
    "address", "host", "hostname", "vrf", "use-vrf", "filter-vrf", "source-interface", "interface", "port",
    "auth-port", "acct-port", "timeout", "retransmit", "prefer", "minpoll", "maxpoll", "burst", "iburst",
    "source", "local", "remote", "any", "all", "both", "extended", "standard", "large", "additive",
    "new-format", "privilege", "role", "network-admin", "network-operator", "vdc-admin", "vdc-operator",
    "level-1", "level-2", "level-1-2", "authentication", "accounting", "single-connection", "no-xauth",
    "cak", "ckn", "add", "algorithm", "size", "bits", "secret-data", "##", "value", "import", "export",
    "rsa", "ec", "ecdsa", "ed25519", "pem", "terminal", "general-keys", "modulus", "id", "set",
    "a", "an", "the", "to", "for", "of", "in", "on", "at", "by", "from", "and", "or", "not", "no", "is",
    "are", "was", "were", "be", "been", "with", "as", "if", "this", "that", "it", "its", "has", "have",
    "must", "should", "will", "can", "cannot", "may", "each", "only", "also", "configured", "enabled",
    "disabled", "required", "expired", "changed", "failed", "failure", "mismatch", "invalid", "missing",
    "present", "true", "false", "yes", "off", "unknown", "hidden", "neighbor", "peer", "used", "supplied",
    "management", "available", "*", "via",
    "fatal(1", "critical(2", "error(3", "warning(4", "information(5", "pmon@fatal", "pmon@critical",
    "pmon@error", "pmon@warning", "pmon@info",
    # value-required keywords: a later clause's keyword in a swept tail stays, so its value is still
    # recognised -- and a wrap after it still dangles ('mgmtuser ... password' / '<value>')
    "password", "passwd", "passphrase", "pass-phrase", "secret", "enablesecret", "community", "psk",
    "pre-shared-key", "authentication-key", "message-digest-key", "server-key",
    "bearer", "basic", "digest", "negotiate", "ntlm", "ssws",
})
_SWEEP_SCHEMES = frozenset({"bearer", "basic", "ssws", "negotiate", "ntlm"})
_SWEEP_SLOTS = frozenset({
    "udp-port", "auth-port", "acct-port", "port", "timeout", "retransmit", "level", "privilege", "access",
    "acl", "ro", "rw", "context", "key-id", "spi", "lifetime", "index", "eigrp",
})
#: ... and these own ONE following NAME (a keychain or VRF name is not a credential).
_SWEEP_NAME_SLOTS = frozenset({"key-chain", "keychain", "chain", "vrf", "use-vrf", "filter-vrf"})
_SWEEP_NAME_OPERAND_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,63}")
_SWEEP_SLOT_OPERAND_RE = re.compile(r"\d{1,5}")
_SWEEP_ESCAPES = frozenset({"\\n", "\\r", "\\r\\n", "\\t", "\\n\\n"})
_SWEEP_IFACE_RE = re.compile(
    r"(?:(?:Hundred|Forty|TwentyFive|Ten|Two|Five|Fifty|FourHundred)?Gig(?:abit)?(?:Ethernet|E)"
    r"|GigabitEthernet|FastEthernet|Ethernet|AppGigabitEthernet|Port-?channel|Bundle-Ether|Loopback"
    r"|Tunnel|Vlan|Serial|Dialer|BDI|BVI|nve|Virtual-(?:Template|Access)|Management|MgmtEth|mgmt"
    r"|Gi|Te|Tw|Twe|Fo|Hu|Fa|Eth|Et|Po|Lo|Tu|Vl|Se|Ap"
    r"|(?:ge|xe|et|fe|gr|lt|irb|ae|lo|fxp|em|me|reth|vlan)-?)\d+(?:[/.:]\d+)*",
    re.IGNORECASE)
_SWEEP_IPV4_RE = re.compile(r"\d{1,3}(?:\.\d{1,3}){3}(?:/\d{1,2})?")
_SWEEP_IPV6_RE = re.compile(r"[0-9A-Fa-f:.]*:[0-9A-Fa-f:.]*(?:%[\w.-]+)?(?:/\d{1,3})?")
_SWEEP_SYNTH_RE = re.compile(
    r"(?:(?:v4-n\d{5}-h\d{3}|v6-\d{8}|mac-\d{12}|serial-\d{6})\.assesshub-redacted\.invalid(?:/\d{1,3})?"
    r"|contact-\d{6}@assesshub-redacted\.invalid)", re.IGNORECASE)
_SWEEP_MASK_RE = re.compile(_v(
    r"(?!<redacted>)</?[A-Za-z_][\w.:-]*(?:{H}[^<>\r\n]*)?/?>"
    r"|-{4,5}{h}?(?:BEGIN|END){h}[ A-Z0-9]*?{h}?-{4,5}"
    r"|(?<![A-Za-z0-9+.-])[a-z][a-z0-9+.-]*://{S}+"
    r"|\^C"
    r"|%(?:2[0267cC]|3[aAbBdDfF]|5[bBdD]|7[bBdD])"), re.IGNORECASE)
_SWEEP_IGNORABLE_RE = re.compile(
    "[\u00ad\u034f\u061c\u115f\u1160\u17b4\u17b5\u180b-\u180f\u200b-\u200f\u202a-\u202e\u2060-\u2064"
    "\u2066-\u206f\ufe00-\ufe0f\ufff9-\ufffb]")
_SWEEP_TOKEN_RE = re.compile("[^" + _CRED_WS + "\r\n=,]+")
_SWEEP_ROW_TOKEN_RE = re.compile(_CRED_NWS + "+")
_SWEEP_LEAD_RE = re.compile(_CRED_H1 + "*")
_SWEEP_XML_RE = re.compile(_v(r"<(?P<tag>[A-Za-z_][\w.:-]*)(?:{H}[^<>\r\n]*)?>(?P<v>(?:<redacted>|[^<\r\n])*)"))
_SWEEP_XML_TAG_RE = re.compile(_v(r"<[A-Za-z_][\w.:-]*(?P<a>{H}[^<>\r\n]*?)/?>"))
_SWEEP_XML_ATTR_RE = re.compile(_v(
    r"""(?<![\w.:-])(?P<n>[A-Za-z_][\w.:-]{0,127}){h}*={h}*(?P<q>["'])(?P<v>[^"'\r\n]*)(?P=q)"""))
_SWEEP_XML_ANY_TAG_RE = re.compile(r"<(?P<close>/)?(?P<t>[A-Za-z_][\w.:-]*)[^<>]*?(?P<self>/)?>")
_SWEEP_XML_STRUCT_CHILD = frozenset({
    "permission", "access", "view", "acl", "acl-name", "access-list", "ipv4-acl", "ipv6-acl", "mode", "type",
    "encryption", "encryption-type", "version", "level", "privilege", "vrf", "context", "index"})
_SWEEP_URL_RE = re.compile(_v(r"(?<![A-Za-z0-9+.-])[a-z][a-z0-9+.-]*://{S}+"), re.IGNORECASE)
_SWEEP_QUERY_RE = re.compile(r"(?<=[?&;])(?P<name>[A-Za-z0-9_.-]+)=(?P<v>[^&#;\"'\s]*)")
_SWEEP_QUERY_NAMES = frozenset({
    "sig", "signature", "token", "access_token", "refresh_token", "id_token", "auth", "auth_token",
    "apikey", "api_key", "api-key", "key", "password", "passwd", "pwd", "pass", "secret", "client_secret",
    "code", "credential", "x-amz-signature", "x-amz-credential", "x-amz-security-token",
})
_SWEEP_PCT_RE = re.compile(r"%([0-9A-Fa-f]{2})")
_SWEEP_SECRET_DATA_RE = re.compile(_v(r"##{h}*SECRET-DATA"), re.IGNORECASE)
_SWEEP_FIRST_TOKEN_RE = re.compile(_v(r"{h}*{S}+"))
#: Credential field names (restated; the producer derives them from the snapshot owner lists).
_SWEEP_RAW_TOKEN_EXTRAS = ("pwd", "passcode", "communities", "authkey")
_SWEEP_RAW_QUOTED_EXACT = frozenset({"pass", "pw", "pin", "key", "auth", "authentication"})
_SWEEP_RAW_UNQUOTED_EXACT = frozenset({"pass", "pw", "pin"})
_SWEEP_NAME_STRIP_RE = re.compile(r"[\s_.\-]")
_SWEEP_QKEY_RE = re.compile(_v(r"""(?P<q>["'])(?P<k>[^"'\\\r\n]{1,128})(?P<c>(?P=q)){h}*:"""))
_SWEEP_UKEY_RE = re.compile(_v(r"(?<![\w.:/@$-])(?P<k>[A-Za-z_][\w.-]{0,127}){h}*(?:=(?![=>])|:(?![:/]))"))
_SWEEP_NAME_HINT_RE = re.compile(r"pass|pwd|secret|communit|psk|token|credential|api|priv|key|auth|pin|pw")
_SWEEP_PROSE_KW_RE = re.compile(_v(
    r"(?<![A-Za-z0-9])(?P<kw>pw|pwd|pass|creds?|account"
    r"|string(?={h}*:|{H}is(?:{h}|\Z))|(?:login|username)(?={H}{S}+{h}*/))(?![A-Za-z0-9_-])"), re.IGNORECASE)
_SWEEP_PROSE_LINE_RE = re.compile(_v(r"^{h}*(?:description(?={h}|\Z)|remark(?={h}|\Z)|!|#|//|/\*)"),
                                  re.IGNORECASE)
_SWEEP_BANNER_RE = re.compile(_v(
    r"^{h}*banner{H}(?:motd|login|exec|incoming|slip-ppp|prompt-timeout|config-save|enable){H}"
    r"(?P<d>\^C|{S})"), re.IGNORECASE)
_SWEEP_ARGV_CMD_RE = re.compile(_v(
    r"(?<![\w.-])(?:[\w.~/-]{0,128}/)?(?P<cmd>curl|sshpass|mysql|mysqldump|mysqladmin|mysqlimport"
    r"|snmp(?:bulk)?(?:walk|get|getnext|set|trap|inform|table|delta|status|df|netstat|test|usm|vacm)"
    # net-snmp-create-v3-user(1) / net-snmp-config --create-snmpv3-user: '-a AUTHPASS -x PRIVPASS';
    # encode_keychange(1): '-O OLDPASS -N NEWPASS' (round 4)
    r"|net-snmp-create-v3-user|net-snmp-config|encode_keychange"
    r"|ipmitool|smbclient|net{H}use)"
    r"(?={h}|\Z)"), re.IGNORECASE)
_SWEEP_ARGV_OPTIONS = {
    "curl": (("-u", "userinfo"), ("--user", "userinfo"), ("-U", "userinfo"), ("--proxy-user", "userinfo")),
    "sshpass": (("-p", "value"),),
    "mysql": (("-p", "attached"),),
    "snmp": (("-c", "value"), ("-A", "value"), ("-X", "value"), ("-3m", "value"), ("-3M", "value"),
             ("-3k", "value"), ("-3K", "value"), ("-a", "protocol"), ("-x", "protocol")),
    "encode_keychange": (("-O", "value"), ("-N", "value")),
    "ipmitool": (("-P", "value"),),
    "smbclient": (("-U", "userpct"), ("--user", "userpct")),
    "net": (),
}
#: net-snmp argument vectors by STRUCTURE, SNMPCMD_ARGS directives, and net-snmp positional credentials
#: (the producer's ``_REDACT_SNMP_*`` rules, restated; round 4).
_SWEEP_SNMP_PROTOCOLS = frozenset({
    "md5", "sha", "sha1", "sha-1", "sha224", "sha-224", "sha256", "sha-256", "sha384", "sha-384", "sha512",
    "sha-512", "des", "3des", "aes", "aes128", "aes-128", "aes192", "aes-192", "aes256", "aes-256", "aes192c",
    "aes-192c", "aes256c", "aes-256c"})
_SWEEP_SNMP_SHAPE_STRONG_RE = re.compile(_v(
    r"(?<!{S})(?:-v{h}*2c|-l{h}*(?i:noauthnopriv|authnopriv|authpriv)|-3[mMkK]{h}*(?:0x)?[0-9A-Fa-f]+)(?!{S})"))
_SWEEP_SNMP_SHAPE_WEAK_RE = re.compile(_v(
    r"(?<!{S})(?:-v{h}*(?:1|3)|-[ax]{h}*(?i:"
    + "|".join(sorted(map(re.escape, _SWEEP_SNMP_PROTOCOLS), key=lambda p: (-len(p), p)))
    + r"))(?!{S})"))
_SWEEP_SNMP_DIRECTIVES = frozenset({"trapsess", "informsess", "proxy"})
_SWEEP_SNMP_POSITIONAL = {"usmuser": (7, 9), "smuxpeer": (1,)}
_SWEEP_SNMP_LINE_WORD_RE = re.compile(_v(
    r"(?<![A-Za-z0-9_.])(?:trapsess|informsess|proxy|(?i:usmuser|smuxpeer))(?={H})"))
_SWEEP_SNMP_FIELD_RE = re.compile(_v(r"\"[^\"\r\n]*\"|{S}+"))
_SWEEP_SNMP_OID_RE = re.compile(r"\.?\d{1,10}(?:\.\d{1,10}){0,127}")
_SWEEP_LINE_WORD_LEADS = "#+>:=(|"
#: Argument words (the producer's ``_REDACT_ARGV_WORD_RE``): a quoted run is part of its word, an unterminated
#: quote runs to the line end, and a non-UTF-8 byte is inside the word it touches.
_SWEEP_ARGV_WS = _CRED_WS.replace("\udc80-\udcff", "")
_SWEEP_ARGV_WORD_RE = re.compile(
    "(?:[^" + _SWEEP_ARGV_WS + "\r\n\"'\\\\]|\\\\[^\r\n]|\\\\\\Z"
    "|\"(?:[^\"\\\\\r\n]|\\\\[^\r\n])*(?:\"|\\Z)|'(?:[^'\\\\\r\n]|\\\\[^\r\n])*(?:'|\\Z))+")
_SWEEP_CHPASSWD_RE = re.compile(_v(
    r"(?<![\w.-])[A-Za-z0-9_.-]{1,64}:(?P<v>[^\s:'\"|]+)(?=['\"]?{h}*\|{h}*(?:sudo{H})?chpasswd(?:{h}|\Z))"))
_SWEEP_PGPASS_RE = re.compile(_v(
    r"^{h}*(?=[^:\s]*[A-Za-z.*])[^:\s]{1,253}:(?:\d{1,5}|\*):[^:\s]{1,128}:[^:\s]{1,128}:(?P<v>[^:\s]+){h}*\Z"))
_SWEEP_EXPECT_PROMPT_RE = re.compile(r"^\s*expect\b.*(?:assword|passphrase|secret|community|pin)", re.IGNORECASE)
_SWEEP_EXPECT_SEND_RE = re.compile(_v(r"^{h}*send(?:{H}--)?{H}\"(?P<v>(?:\\.|[^\"\\\r\n])*?)(?:\\[rn])*\""))
_SWEEP_CRYPT_RE = re.compile(
    r"(?<![\w$])\$(?:1|2[abxy]?|5|6|7|8|9|y|gy|apr1|sha1|md5|pbkdf2(?:-sha\d{1,3})?|scrypt)\$[A-Za-z0-9./+=$-]{2,}"
    r"|(?<![\w}])\{(?:S?SHA(?:256|384|512)?|S?MD5|CRYPT|PBKDF2(?:-SHA\d{1,3})?|ARGON2[a-z]{0,2})\}[A-Za-z0-9./+=$-]{4,}",
    re.IGNORECASE)
_SWEEP_B64_RE = re.compile(r"(?<![A-Za-z0-9+/_-])[A-Za-z0-9+/_-]{24,}={0,2}(?![A-Za-z0-9+/_=-])")
_SWEEP_HEX_RE = re.compile(r"(?<![A-Za-z0-9])[0-9A-Fa-f]{32,}(?![A-Za-z0-9])")
#: ... and any token in a CLOSED list of credential token formats, whatever its letters
#: (GitHub, GitLab, Slack, Stripe, OpenAI-style, AWS access key IDs, Google API keys, OAuth access, JWT).
_SWEEP_TOKEN_FORMAT_RE = re.compile(
    r"(?<![A-Za-z0-9_-])(?:github_pat_[A-Za-z0-9_]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|glpat-[A-Za-z0-9_-]{20,}"
    r"|xox[abposr]-[A-Za-z0-9-]{10,}|xapp-[A-Za-z0-9-]{10,}|[sr]k_live_[A-Za-z0-9]{10,}|sk-[A-Za-z0-9_-]{20,}"
    r"|A[KS]IA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{35}|ya29\.[A-Za-z0-9_.-]{20,}"
    r"|eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}(?:\.[A-Za-z0-9_-]*)?)")


def _sweep_entropy_part(part: str) -> bool:
    """A base64 segment that looks RANDOM: 16+ characters mixing upper case, lower case and digits,
    whose character classes change at least every 2.5 characters on average. A camelCase identifier
    ('HDfabricOverallHealth5min', an ACI class in a DN) runs whole words of one case and is not one."""
    if len(part) < 16 or not (any(c.isupper() for c in part) and any(c.islower() for c in part)
                              and any(c.isdigit() for c in part)):
        return False
    kinds = ["u" if c.isupper() else "l" if c.islower() else "d" if c.isdigit() else "o" for c in part]
    changes = sum(1 for a, b in zip(kinds, kinds[1:]) if a != b)
    return len(part) <= 2.5 * (changes + 1)
_SWEEP_DIGEST_LABEL_RE = re.compile(
    r"(?:md5|sha-?1|sha-?224|sha-?256|sha-?384|sha-?512|sha2|digest|hash|fingerprint|checksum|thumbprint)"
    r"[^A-Za-z0-9]{0,4}\Z", re.IGNORECASE)
_SWEEP_PUBKEY_LABEL_RE = re.compile(
    r"(?:ssh-rsa|ssh-dss|ssh-ed25519|ssh-ed448|ecdsa-sha2-nistp(?:256|384|521)|sk-ssh-ed25519@openssh\.com"
    r"|sk-ecdsa-sha2-nistp256@openssh\.com)" + _CRED_HWS + r"\Z", re.IGNORECASE)
_SWEEP_DANGLE_KWS = frozenset({
    "password", "passwd", "passphrase", "passcode", "enablesecret", "secret", "psksecret", "psk", "community",
    "key", "keystring", "keyoctetstring", "presharedkey", "setkey", "authenticationkey",
    "areaauthenticationkey", "domainauthenticationkey", "messagedigestkey", "serverkey", "encryptedpassword",
    "plaintextpassword", "plaintextpasswordvalue", "secretkey", "apikey", "communitystring", "communityname",
    "communitymap", "trapcommunity", "authkey", "authpwd", "privpwd",
})
_SWEEP_DANGLE_QUALIFIERS = frozenset({
    *(str(n) for n in range(16)), "level", "algorithm-type", "scrypt", "pbkdf2", "md5", "sha", "sha1", "sha-1",
    "sha224", "sha256", "sha384", "sha512", "sha-256", "sha-384", "sha-512", "sha2-256", "sha2-384", "sha2-512",
    "hmac-md5", "hmac-sha", "hmac-sha1", "hmac-sha-1", "hmac-sha256", "hmac-sha-256", "hmac-sha2-224",
    "hmac-sha2-256", "hmac-sha2-384", "hmac-sha2-512", "cipher", "plain", "ascii",
    "hex", "encrypted", "clear", "enc", "simple", "text", "irreversible-cipher", "hashed", "aes", "aes128",
    "aes192", "aes256", "aes-128", "aes-192", "aes-256", "des", "des56", "3des", "aescfb128", "hmacmd5", "hmacsha",
    "local", "remote", "ascii-text", "hexadecimal", "128", "192", "256", "--",
})
_SWEEP_SIZE_WORDS = frozenset({"aes", "des", "3des", "aes-cbc"})
_SWEEP_DANGLE_HINT_RE = re.compile(r"pass|secret|communit|key|psk|auth|priv|-pw|snmp-server")
_SWEEP_NAME_OPEN_RE = re.compile(_v(r"""(?P<q>["'])(?P<k>[^"'\\\r\n]{1,128})(?P=q){h}*:{h}*\Z"""))
#: A credential header whose value a wrap cut (the producer's ``_REDACT_SCHEME_OPEN_RE``): the next non-blank
#: line's first argument word must be the placeholder.
_SWEEP_SCHEME_OPEN_RE = re.compile(_v(
    r"(?<![A-Za-z0-9_-])(?:(?:proxy-)?authorization[\"']?{h}*:{h}*[\"']?[A-Za-z][A-Za-z0-9!#$%&*+.^_`|~-]*"
    r"|x-[a-z0-9-]{0,64}?(?:token|api-?key|secret|password)[\"']?{h}*:{h}*(?:[\"']?(?:"
    + "|".join(sorted(_SWEEP_SCHEMES)) + r"))?){h}*\Z"), re.IGNORECASE)
_SWEEP_SNMP_HOST_OPEN_RE = re.compile(_v(r"\bsnmp-server{H}host(?P<rest>(?:{H}{S}+)*){h}*\Z"), re.IGNORECASE)
#: Closed configuration command words (the producer's ``_REDACT_COMMAND_WORDS``) and clause-trailing
#: words (``_REDACT_CONT_TRAILERS``): exact words, never a shape -- any other word is a wrapped value.
_SWEEP_COMMAND_WORDS = frozenset({
    "ntp", "key", "key-string", "key-chain", "accept-lifetime", "send-lifetime", "cryptographic-algorithm",
    "ip", "ipv6", "interface", "router", "line", "logging", "clock", "aaa", "crypto", "snmp-server", "banner",
    "hostname", "service", "username", "enable", "end", "exit", "no", "description", "spanning-tree", "vlan",
    "access-list", "control-plane", "boot", "version", "license", "archive", "alias", "event", "track",
    "route-map", "policy-map", "class-map", "monitor", "mpls", "vrf", "address-family", "exit-address-family",
    "neighbor", "network", "redistribute", "shutdown", "switchport", "standby", "vrrp", "tacacs-server",
    "radius-server", "tacacs", "radius", "login", "transport", "exec-timeout", "privilege", "password",
    "secret", "authentication", "server", "address", "timeout", "single-connection", "source-interface",
    "redundancy", "boot-start-marker", "boot-end-marker", "netconf-yang", "restconf", "multilink", "config"})
_SWEEP_CONT_TRAILERS = frozenset({
    "ro", "rw", "view", "address", "hostname", "privilege", "role", "encrypted", "pbkdf2", "version",
    "udp-port", "level", "ipv4", "ipv6", "read-only", "read-write", "authorization", "level-1", "level-2",
    "priv", "auth", "access", "acl", "vrf"})
_SWEEP_SNMP_HOST_WORDS = frozenset({"traps", "trap", "informs", "inform", "version", "1", "2c", "clear",
                                    "encrypted", "vrf"})
_SWEEP_SNMP_USER_RE = re.compile(_v(r"\bsnmp-server{H}user{H}"), re.IGNORECASE)
_SWEEP_SNMP_AUTHPRIV_RE = re.compile(r"(?<![\w-])(?:auth|priv)(?![\w-])", re.IGNORECASE)
_SWEEP_DANGLE_VOID_LINE_RE = re.compile(_v(r"^{h}*(?:no|config){H}"), re.IGNORECASE)
_SWEEP_PROSE_COMMA_RE = re.compile("," + _CRED_H1 + r"+\Z")
_CRED_CLAUSE_LEAD = ":;,(\"'`<>{["
_SWEEP_PROSE_PREV = frozenset({
    "and", "or", "the", "a", "an", "your", "my", "our", "their", "his", "her", "its", "this", "that", "with",
    "for", "of", "new", "old", "invalid", "wrong", "bad", "incorrect", "expired"})


def _sweep_prose_before(text: str, pos: int, index=None) -> bool:
    if _SWEEP_PROSE_COMMA_RE.search(text, max(0, pos - 64), pos):
        return True
    if index is None:
        index = _sweep_token_index(text[:pos], _SWEEP_ROW_TOKEN_RE)
    return _sweep_last_token(text, index, pos).strip(_SWEEP_EDGE).casefold() in _SWEEP_PROSE_PREV
_SWEEP_WORD_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")
_CRED_JOIN_TAIL = 300
_CRED_CROSS_NEEDLE_RE = re.compile("|".join(map(re.escape, dict.fromkeys(
    needle for family in _CRED_FAMILIES if family.cross for needle in _CRED_FAMILY_NEEDLES.get(family.name, ())))))
_SWEEP_DANGLE_NORM_RE = re.compile(r"[-_]")
#: A bare 'key' followed only by an integer 0-15 is a key ID unless the line is a TACACS+/RADIUS or
#: ISAKMP key line (the grammar's own 'key' guard).
_SWEEP_KEY_ID_RE = re.compile(_v(r"{H}(?:1[0-5]|[0-9]){h}*\Z"))
_SWEEP_KEY_SECRET_LINE_RE = re.compile(r"\b(?:tacacs-server|radius-server|isakmp)\b", re.IGNORECASE)
_SWEEP_CONT_EXEMPT = frozenset({
    "!", "end", "exit", "quit", "exit-address-family", "exit-af-interface", "exit-af-topology",
    "exit-peer-policy", "exit-peer-session", "exit-service-insertion", "exit-vrf", "}", "]", ")", "^c", "#",
    "--more--", "edit", "next", "snmp-server", "snmp-agent",
})
_PEM_BEGIN_RE = re.compile(r"-{4,5} ?BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY(?: BLOCK)? ?-{4,5}", re.IGNORECASE)
_PEM_END_RE = re.compile(r"-{4,5} ?END (?:[A-Z0-9]+ )*PRIVATE KEY(?: BLOCK)? ?-{4,5}", re.IGNORECASE)
_PUTTY_PRIVATE_RE = re.compile(_v(r"^{h}*Private-Lines:{h}*(?P<n>\d{1,5}){h}*\Z"), re.IGNORECASE)
_B64_LINE_RE = re.compile(r"[A-Za-z0-9+/=]+|<redacted>")
_CREDENTIAL_SHAPE_RE = re.compile(r"(?=[^\r\n]*[A-Za-z])(?=[^\r\n]*\d)")
_TABLE_HEADERS = tuple((re.compile(_v(pattern), re.IGNORECASE), nxt, kind) for pattern, nxt, kind in (
    (r"^{h}*(?P<c>Community){h}+(?P<n>Group){h}*/{h}*Access\b", "n", "first"),
    (r"^{h}*Keyring{h}+Hostname/Address{h}+(?P<c>Preshared{h}Key)\b", None, "isakmp"),
    (r"^{h}*Host{h}+Port{h}+Version{h}+Level{h}+Type{h}+(?P<c>SecName)\b", None, "host"),
    (r"^{h}*(?P<c>SNMP{h}Community{h}Name){h}+(?P<n>Client{h}IP{h}Address)\b", "n", "aireos"),
))
_TABLE_GROUP_RE = re.compile(r"[^ \t\r\n]+(?: [^ \t\r\n]+)*")
_TABLE_WORD_RE = re.compile(r"[A-Z][A-Za-z]*(?:[/_-][A-Za-z]+)*")
_TABLE_CRED_COLUMNS = frozenset({
    "password", "passwd", "secret", "community", "psk", "presharedkey", "preshared", "key", "passphrase",
    "enablesecret", "enablepassword", "sharedsecret", "snmpcommunity", "communitystring", "communityname"})
_TABLE_ALSO_COLUMNS = frozenset({"enable"})
_TABLE_END_RE = re.compile(_v(r"^{h}*-{3,}{h}*show{h}"), re.IGNORECASE)
_DASHES_RE = re.compile(r"-+\Z")
_FORTI_CONFIG_RE = re.compile(_v(r"^{h}*config{H}(?P<path>[^\r\n]*?){h}*\Z"), re.IGNORECASE)
_FORTI_END_RE = re.compile(_v(r"^{h}*end{h}*\Z"), re.IGNORECASE)
_FORTI_SET_NAME_RE = re.compile(_v(r"^{h}*set{H}name(?={h}|\Z)"), re.IGNORECASE)
_CHAP_HEADER_RE = re.compile(_v(r"^{h}*#{h}*client{H}server{H}secret(?={h}|\Z)"), re.IGNORECASE)
_JSON_OPEN_RE = re.compile(_v(r"""(?P<q>["'])(?P<k>[^"'\\\r\n]{1,128})(?P=q){h}*:{h}*(?P<b>(?:[\[{]{h}*)+)\Z"""))
_JSON_STRING_RE = re.compile(r'"(?:\\.|[^"\\\r\n])*"')
_XML_OPEN_RE = re.compile(_v(r"^{h}*<(?P<t>[A-Za-z_][\w.:-]{0,127})(?:{H}[^<>\r\n]*)?(?<!/)>{h}*\Z"))
_YAML_OPEN_RE = re.compile(_v(
    r"^{h}*(?:-{H})?(?P<k>[A-Za-z_][\w.-]{0,127}){h}*:{h}*(?:[|>][-+0-9]{0,3}{h}*)?\Z"))
_YAML_VALUE_RE = re.compile(_v(r"^{h}*(?:-{H})?(?P<k>[A-Za-z_][\w.-]{0,127}){h}*:{H}{S}"))
_CSV_DELIMS = (",", "\t", ";", "|")
_CSV_FIELD_RE = re.compile(r"[A-Za-z][A-Za-z0-9 _.-]{0,63}")
_CSV_HEADER_CHARS_RE = re.compile(r"[A-Za-z0-9 _.\-\"'<>,\t;|]+")
#: Speed only: a line holding none of these substrings has no keyword, URL, XML element, armor or
#: long token, so neither guarantee has anything to read on it (the producer skips it the same way).
_SWEEP_PREFILTER = re.compile(
    r"pass|secret|communit|key|auth|psk|cipher|plain|ascii|hex|token|bearer|ssws|phash|pwd|cak|ckn|priv|"
    r"cookie|trap|securityname|snmp|nhrp|standby|vrrp|glbp|rmon|environment|command|spi|user|"
    r"groupname:|com2sec|_pw|-pw|credential|pkcs12|----|://|<|sink|cleartext|=\s*des|ldap|lte|pin|"
    r"curl|mysql|md5|sha|cmac|api|cred|account|crypt|\$|%|\"pw|'pw|"
    r"rootpw|bindpw|authtok|chpasswd|ipmitool|smbclient|net\s+use|:(?:\d{1,5}|\*):|pw|"
    # round 4: net-snmp argument vectors, directives and positional lines (`_SWEEP_SNMP_ARGV_SHAPE_RE`)
    + _v(r"informsess|proxy|smuxpeer|usmuser|-v{h}*(?:1|2c|3)|-x{h}*(?:3?des|aes)|-3[mk]"))   # CASEFOLDED
_SWEEP_RUN_RE = re.compile(r"[A-Za-z0-9+/_=-]{24}")    # ... or a run long enough to be high-entropy

#: Compatibility for readers that fingerprint "the verifier grammar" (the D10 evidence-retention branch
#: digests this tuple at import): every compiled pattern of both restated guarantees, in a fixed order.
_INLINE_SECRET_RES = tuple(
    [family.anchor for family in _CRED_FAMILIES] + [family.qualifiers for family in _CRED_FAMILIES]
    + [_SWEEP_KW_RE, _SWEEP_MASK_RE, _SWEEP_TOKEN_RE, _SWEEP_XML_RE, _SWEEP_XML_TAG_RE, _SWEEP_XML_ATTR_RE,
       _SWEEP_URL_RE, _SWEEP_QUERY_RE, _SWEEP_QKEY_RE, _SWEEP_UKEY_RE, _SWEEP_PROSE_KW_RE, _SWEEP_PROSE_LINE_RE,
       _SWEEP_BANNER_RE, _SWEEP_ARGV_CMD_RE, _SWEEP_CRYPT_RE, _SWEEP_B64_RE, _SWEEP_HEX_RE,
       _SWEEP_DIGEST_LABEL_RE, _SWEEP_PUBKEY_LABEL_RE, _PEM_BEGIN_RE, _PEM_END_RE, _PUTTY_PRIVATE_RE,
       _TABLE_END_RE, _FORTI_CONFIG_RE, _FORTI_END_RE, _FORTI_SET_NAME_RE, _CHAP_HEADER_RE, _JSON_OPEN_RE,
       _XML_OPEN_RE, _YAML_OPEN_RE]
    + [header[0] for header in _TABLE_HEADERS]
    + [_SWEEP_SNMP_SHAPE_STRONG_RE, _SWEEP_SNMP_SHAPE_WEAK_RE, _SWEEP_SNMP_LINE_WORD_RE, _SWEEP_SNMP_FIELD_RE,
       _SWEEP_SNMP_OID_RE, _SWEEP_ARGV_WORD_RE, _SWEEP_SCHEME_OPEN_RE])


def _cred_token(line: str, pos: int) -> tuple[str, int] | None:
    match = _CRED_TOKEN_RE.match(line, pos)
    return (match.group(0), match.end()) if match else None


_CRED_ADDRESS_RE = re.compile(_v(r"(?:\d{1,3}(?:\.\d{1,3}){3}|" + _CRED_IPV6_TEXT
                                   + r"|{S}+\.assesshub-redacted\.invalid)(?:/\d{1,3})?"), re.IGNORECASE)


def _cred_is_address(token: str) -> bool:
    """An address -- or, in a redacted snapshot, its synthetic pseudonym -- in the value slot of
    'snmp-server host <ifname> <ip> community X' (ASA) is the host. The producer's exact shape."""
    return bool(_CRED_ADDRESS_RE.fullmatch(token))


def _cred_value_is_structural(value: str, end: int, family: _CredFamily, line: str, position: int) -> bool:
    """A follow-word, label, punctuation or armor where the value would stand: no credential here."""
    if family.value_guard is not None and family.value_guard.match(line, position):
        return True
    if _CRED_PEM_ARMOR_RE.match(line, position):
        return True                                      # a private-key block: the PEM rule owns it
    if _CRED_BLOCK_INDICATOR_RE.fullmatch(value):
        return True                                      # a YAML block scalar: the block rule owns it
    if value[:1] in {'"', "'"}:
        return False                                     # a quoted token is always a value
    head = re.split(r"[;,.]", value, maxsplit=1)[0].casefold()
    if head in family.stops:
        # ... unless what follows makes the stop word the value ('community all RO').
        return not (family.stop_unless is not None and value.casefold() == head
                    and family.stop_unless.match(line, end))
    if head in family.soft:
        if value.casefold() != head:
            return True                                  # punctuation directly after: a stop
        follow = _CRED_FOLLOW_RE.match(line, end)
        if follow is None:
            return False                                 # it ends the line: the value
        if family.stop_unless is not None and family.stop_unless.match(line, end):
            return False
        return not family.clause_end.match(line, follow.end())
    if value.endswith(":") and '"' not in value and "'" not in value:   # 'Key name:', 'Data:'
        return True
    if not value.strip("{}[];"):
        return True
    return family.address_is_structural and _cred_is_address(value)


def _cred_is_placeholder(token: str, delim: str = "") -> bool:
    """The placeholder, allowing the punctuation a config or JSON line closes it with (and, inside a
    banner, the banner delimiter the scrub keeps after it)."""
    token = token.rstrip(";,)}]\"'")
    if delim and token.endswith(delim) and token != delim:
        token = token[:len(token) - len(delim)]
    return token.casefold() == _PLACEHOLDER


def _cred_clauses(line: str, artifact: bool,
                  has_next: bool = False) -> list[tuple[_CredFamily, int, str, int]]:
    """Every GRAMMAR clause on the line: (family, keyword start, value token, value end).

    A clause whose grammar ends after its qualifiers, or whose value slot holds a structural
    follow-word, carries no credential and is not returned. A lone type digit that ends the line while
    more lines follow is the type of a WRAPPED value, not the value (the line dangles instead)."""
    clauses = []
    folded = line.casefold()
    for family in _CRED_FAMILIES:
        if artifact:
            matches = [found for found in (anchor.match(line) for anchor in family.artifact) if found]
        else:
            needles = _CRED_FAMILY_NEEDLES.get(family.name)
            if needles is not None and not any(needle in folded for needle in needles):
                continue
            matches = list(family.anchor.finditer(line))
        for match in matches:
            start = (_CRED_PROSE_START_RE if family.prose else _CRED_PLAIN_START_RE).match(line, match.end())
            if start is None:
                continue                                  # 'password-encryption': not this keyword
            position = family.qualifiers.match(line, start.end()).end()
            token = _cred_token(line, position)
            if token is None:
                continue                                  # the grammar ended after its qualifiers
            value, end = token
            if _cred_value_is_structural(value, end, family, line, position):
                continue
            if (has_next and (_CRED_TYPE_DIGIT_RE.fullmatch(value) or value == _CRED_WRAP_ENC)
                    and not _CRED_WS_RE.sub("", line[end:])):
                continue                                  # a wrapped value's type digit (or 'ENC')
            anchor_text = match.group(0)
            keyword_start = match.start() + len(anchor_text) - len(_CRED_WS_RE.split(anchor_text)[-1])
            clauses.append((family, keyword_start, value, end))
    return clauses


def _credential_line_findings(line: str, *, artifact: bool, has_next: bool = False,
                              delim: str = "") -> list[str]:
    """Every GRAMMAR violation on one line: a recognised value slot that is not the placeholder.

    ``artifact`` reads only the families' line-start ``artifact`` anchors (a shareable artifact also
    carries authored prose and generated code); otherwise every family anchor anywhere in the line."""
    if len(line) > _CRED_GRAMMAR_MAX_LINE or not _CRED_PREFILTER_RE.search(line.casefold()):
        return []
    return [f"credential value ({family.name})"
            for family, _start, value, _end in _cred_clauses(line, artifact, has_next)
            if not _cred_is_placeholder(value, delim)]


# ---- the sweep guarantee, line by line ----
def _sweep_is_address(core: str) -> bool:
    if _SWEEP_IPV4_RE.fullmatch(core) or (":" in core and _SWEEP_IPV6_RE.fullmatch(core)):
        try:
            ipaddress.ip_network(re.sub(r"%[\w.-]+", "", core), strict=False)
        except ValueError:
            return False
        return True
    return False


def _sweep_token_core(token: str, delim: str = "") -> str:
    core = token.strip(_SWEEP_EDGE)
    while delim and core and (core.startswith(delim) or core.endswith(delim)):
        if core.startswith(delim):
            core = core[len(delim):]
        if core.endswith(delim):
            core = core[:len(core) - len(delim)]
        core = core.strip(_SWEEP_EDGE)
    return core


def _sweep_token_ok(token: str, delim: str = "") -> bool:
    if _PLACEHOLDER in token:
        return not _sweep_token_core(token.replace(_PLACEHOLDER, ""), delim)
    core = _sweep_token_core(token, delim)
    if not core or core in _SWEEP_ESCAPES or _DASHES_RE.match(core):
        return True
    folded = core.casefold()
    return (folded in _SWEEP_ALLOW or _sweep_is_address(core) or _sweep_value_required(folded)
            or bool(_SWEEP_IFACE_RE.fullmatch(core)) or bool(_SWEEP_SYNTH_RE.fullmatch(core)))


def _sweep_masked(line: str) -> str:
    return _SWEEP_MASK_RE.sub(lambda m: " " * len(m.group(0)), line)


def _sweep_credential_name(name: str, quoted: bool) -> bool:
    folded = name.casefold()
    if quoted:
        folded = folded.rpartition(":")[2]
    folded = _SWEEP_NAME_STRIP_RE.sub("", folded)
    if not folded:
        return False
    if folded in _SECRET_KEYS or any(token in folded for token in _SECRET_KEY_TOKENS + _SWEEP_RAW_TOKEN_EXTRAS):
        return True
    if not quoted:
        return folded in _SWEEP_RAW_UNQUOTED_EXACT
    return folded in _SWEEP_RAW_QUOTED_EXACT or folded.endswith("key")


def _sweep_word_end(masked: str, end: int) -> int:
    while end < len(masked) and masked[end] in _SWEEP_WORD_CHARS:
        end += 1
    return end


def _sweep_token_index(text: str, regex: re.Pattern[str]) -> tuple[list[tuple[int, int]], list[int]]:
    spans = [m.span() for m in regex.finditer(text)]
    return spans, [start for start, _end in spans]


def _sweep_last_token(text: str, index: tuple[list[tuple[int, int]], list[int]], pos: int) -> str:
    """The last token ``regex.findall(text, 0, pos)`` returns (cut at ``pos``), or "" (the producer's rule)."""
    spans, starts = index
    i = bisect.bisect_left(starts, pos) - 1
    if i < 0:
        return ""
    start, end = spans[i]
    return text[start:min(end, pos)]


def _sweep_keyword_anchor(masked: str) -> int | None:
    pos = 0
    index = None
    while True:
        found = _SWEEP_KW_RE.search(masked, pos)
        if found is None:
            return None
        word = found.group("kw").casefold().strip(_CRED_WS_CHARS)
        end = _sweep_word_end(masked, found.end())
        following = _SWEEP_TOKEN_RE.search(masked, end)
        nxt = following.group(0).strip(_SWEEP_EDGE).casefold() if following else ""
        if index is None:
            index = _sweep_token_index(masked, _SWEEP_TOKEN_RE)
        prev = _sweep_last_token(masked, index, found.start()).strip(_SWEEP_EDGE).casefold()
        if (nxt in _SWEEP_VOID_NEXT.get(word, ()) or prev in _SWEEP_VOID_PREV.get(word, ())
                or (end > found.end() and masked[found.start():end].casefold() in _SWEEP_ALLOW)):
            pos = found.end()
            continue
        return end


def _sweep_folded_anchor(masked: str, search) -> int | None:
    if not _SWEEP_IGNORABLE_RE.search(masked):
        return search(masked)
    keep = [i for i, ch in enumerate(masked) if not _SWEEP_IGNORABLE_RE.match(ch)]
    found = search("".join(masked[i] for i in keep))
    if found is None:
        return None
    return keep[found - 1] + 1 if found else 0


def _sweep_name_anchor(masked: str, low: str) -> int | None:
    if not _SWEEP_NAME_HINT_RE.search(low):
        return None
    found = []
    if '"' in masked or "'" in masked:
        for m in _SWEEP_QKEY_RE.finditer(masked):
            if _sweep_credential_name(m.group("k"), True):
                found.append(m.end("c"))
                break
    if "=" in masked or ":" in masked:
        for m in _SWEEP_UKEY_RE.finditer(masked):
            if _sweep_credential_name(m.group("k"), False):
                found.append(m.end("k"))
                break
    return min(found) if found else None


def _sweep_anchor(line: str, masked: str, forti: bool, prose: int | None = None,
                  join: int | None = None) -> int | None:
    candidates = [] if join is None else [join]
    if _SWEEP_SECRET_DATA_RE.search(line):
        first = _SWEEP_FIRST_TOKEN_RE.match(line)
        if first:
            candidates.append(first.end())
    if forti:
        name = _FORTI_SET_NAME_RE.match(line)
        if name:
            candidates.append(name.end())
    keyword = _sweep_folded_anchor(masked, _sweep_keyword_anchor)
    if keyword is not None:
        candidates.append(keyword)
    named = _sweep_name_anchor(masked, line.casefold())
    if named is not None:
        candidates.append(named)
    if prose is not None:
        informal = _SWEEP_PROSE_KW_RE.search(masked, prose)
        if informal:
            candidates.append(informal.end())
    return min(candidates) if candidates else None


def _sweep_residue(masked: str, anchor: int, delim: str = "") -> bool:
    """Is any token after the anchor neither structural nor a structural slot's one operand? (The one
    token after an authorization scheme is never structural.)"""
    slot = None
    scheme = False
    for match in _SWEEP_TOKEN_RE.finditer(masked, anchor):
        core = _sweep_token_core(match.group(0), delim)
        if slot is not None and slot.fullmatch(core):
            slot = None
            continue
        ok = _sweep_token_ok(match.group(0), delim)
        if scheme and core and _PLACEHOLDER not in match.group(0):
            ok = False
        word = core.casefold()
        if core:
            scheme = word in _SWEEP_SCHEMES
        slot = (None if not ok else _SWEEP_SLOT_OPERAND_RE if word in _SWEEP_SLOTS
                else _SWEEP_NAME_OPERAND_RE if word in _SWEEP_NAME_SLOTS else None)
        if not ok:
            return True
    return False


def _sweep_value_required(word: str) -> bool:
    return (_SWEEP_DANGLE_NORM_RE.sub("", word) in _SWEEP_DANGLE_KWS
            or word.endswith(("-pw", "-pwd", "-password", "-passwd", "-secret", "-key", "-community")))


def _sweep_snmp_host_tail(tokens: list[str]) -> bool:
    after_vrf = False
    for token in tokens:
        core = token.strip(_SWEEP_EDGE)
        if after_vrf:
            after_vrf = False
            continue
        folded = core.casefold()
        if not (folded in _SWEEP_SNMP_HOST_WORDS or _sweep_is_address(core) or _SWEEP_SYNTH_RE.fullmatch(core)):
            return False
        after_vrf = folded == "vrf"
    return True


def _sweep_dangle(line: str, carry: tuple[str, str | None] | None = None) -> tuple[str, list[Any], bool] | None:
    """``(kind, tail, key_id)`` when the line DANGLES (the producer's rule, restated)."""
    if "snmp-server" in line.casefold():
        masked = _sweep_masked(line)
        found = _SWEEP_SNMP_HOST_OPEN_RE.search(masked)
        if found is not None:
            tokens = _SWEEP_TOKEN_RE.findall(found.group("rest"))
            if not any(_PLACEHOLDER in token for token in tokens) and _sweep_snmp_host_tail(tokens):
                return ("snmp-host", [token.strip(_SWEEP_EDGE).casefold() for token in tokens], False)
    if ":" in line and ('"' in line or "'" in line):
        found = _SWEEP_NAME_OPEN_RE.search(_sweep_masked(line))
        if found is not None and _sweep_credential_name(found.group("k"), True):
            return ("value", [], False)
    if ":" in line and _SWEEP_SCHEME_OPEN_RE.search(_sweep_masked(line)):
        return ("scheme", [], False)
    if carry is not None or "-" in line or "net" in line.casefold():
        pending = _sweep_argv_walk(line, carry)[1]
        if pending is not None:
            return ("argv", list(pending), False)
    dangle = _sweep_dangle_tail(line)
    return None if dangle is None else ("value", dangle[0], dangle[1])


def _sweep_dangle_tail(line: str) -> tuple[list[str], bool] | None:
    """``(tail, key_id)`` when the line DANGLES -- the next non-blank line then continues its open
    clause -- or None (the producer's rule, restated)."""
    low = line.casefold()
    if not _SWEEP_DANGLE_HINT_RE.search(low) or _SWEEP_DANGLE_VOID_LINE_RE.match(line):
        return None
    masked = _sweep_masked(line)
    last, key_id = None, False
    tokens = rows = None
    for found in _SWEEP_KW_RE.finditer(masked):
        start = run = found.start()
        if start and masked[start - 1] not in _CRED_WS_CHARS and masked[start - 1] not in "-_":
            continue
        while run and masked[run - 1] in _SWEEP_WORD_CHARS:
            run -= 1
        if run and masked[run - 1] not in _CRED_WS_CHARS:
            continue
        end = _sweep_word_end(masked, found.end())
        if end > found.end():
            continue
        if masked[end:].lstrip(_CRED_WS_CHARS)[:1] in (":", "="):
            continue
        word = found.group("kw").casefold()
        if not _sweep_value_required(word):
            continue
        following = _SWEEP_TOKEN_RE.search(masked, end)
        nxt = following.group(0).strip(_SWEEP_EDGE).casefold() if following else ""
        if tokens is None:
            tokens = _sweep_token_index(masked, _SWEEP_TOKEN_RE)
            rows = _sweep_token_index(masked, _SWEEP_ROW_TOKEN_RE)
        prev = _sweep_last_token(masked, tokens, start).strip(_SWEEP_EDGE).casefold()
        if (nxt in _SWEEP_VOID_NEXT.get(word, ()) or prev in _SWEEP_VOID_PREV.get(word, ())
                or word in _SWEEP_VOID_NEXT.get(prev, ())):
            continue
        if _sweep_prose_before(masked, start, rows):
            continue
        last = end
        key_id = (word == "key" and bool(_SWEEP_KEY_ID_RE.match(masked, end))
                  and not _SWEEP_KEY_SECRET_LINE_RE.search(line))
    if _SWEEP_SNMP_USER_RE.search(line):
        for found in _SWEEP_SNMP_AUTHPRIV_RE.finditer(masked):
            if last is None or found.end() > last:
                last, key_id = found.end(), False
    if last is None:
        return None
    tokens = _SWEEP_TOKEN_RE.findall(masked, last)
    if any(_PLACEHOLDER in token for token in tokens):
        return None
    if any(not token.strip(_SWEEP_EDGE) and any(ch in token for ch in "])};") for token in tokens):
        return None
    cores = [token.strip(_SWEEP_EDGE).casefold() for token in tokens]
    cores = [core for core in cores if core]
    return (cores, key_id) if all(core in _SWEEP_DANGLE_QUALIFIERS for core in cores) else None


def _sweep_core_bounds(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text[start] in _SWEEP_EDGE:
        start += 1
    while end > start and text[end - 1] in _SWEEP_EDGE:
        end -= 1
    return start, end


def _sweep_starts_clause(line: str, masked: str, start: int, end: int) -> bool:
    """The token ``line[start:end]`` IS a clause start of its own -- never a wrapped value: XML/JSON
    structure, or an anchor / keyword that begins at the token's core and covers all of it. POSITIONAL
    (round 3): a keyword INSIDE the token ('Secret99Qz', 'md5KeyQ') does not exempt it."""
    if line[start:start + 1] in ("<", "{", "["):
        return True
    cs, ce = _sweep_core_bounds(line, start, end)
    if cs >= ce:
        return False
    for family in _CRED_FAMILIES:
        found = family.anchor.match(line, cs)
        if found is not None and found.end() >= ce:
            return True
    found = _SWEEP_KW_RE.match(masked, cs)
    if found is not None and found.end() >= ce:
        return True
    return bool(_SWEEP_ARGV_CMD_RE.match(line, start))


def _sweep_clause_continuation_violation(line: str, kind: str, tail: list[str], start: int = 0,
                                          key_id: bool = False) -> bool:
    """The first value token a dangling clause continues into must be the placeholder (after a dangling
    authorization scheme its first blank-delimited token, whatever it spells)."""
    if kind == "scheme":
        for match in _SWEEP_ROW_TOKEN_RE.finditer(line, start):
            if not match.group(0).strip(_SWEEP_EDGE):
                continue
            return not (_PLACEHOLDER in match.group(0) and _sweep_token_ok(match.group(0)))
        return False
    masked = _sweep_masked(line)
    size_cut = len(tail) >= 2 and tail[-2] in _SWEEP_SIZE_WORDS and tail[-1].isdigit()
    after_vrf = kind == "snmp-host" and tail[-1:] == ["vrf"]
    for match in _SWEEP_TOKEN_RE.finditer(masked, start):
        token = match.group(0)
        core = token.strip(_SWEEP_EDGE)
        if not core:
            continue
        if _PLACEHOLDER in token:
            return not _sweep_token_ok(token)            # residue beside it ('BgpSecret<redacted>')
        folded = core.casefold()
        if kind == "snmp-host":
            if after_vrf:
                after_vrf = False
                continue
            if folded in _SWEEP_SNMP_HOST_WORDS or _sweep_is_address(core) or _SWEEP_SYNTH_RE.fullmatch(core):
                after_vrf = folded == "vrf"
                continue
        elif folded in _SWEEP_DANGLE_QUALIFIERS:
            continue
        if size_cut and core.isdigit() and len(core) <= 3:
            size_cut = False
            continue
        return not (_sweep_value_required(folded) or _sweep_starts_clause(line, masked, match.start(), match.end())
                    or folded in _SWEEP_CONT_EXEMPT or (key_id and folded in _SWEEP_COMMAND_WORDS))
    return False


def _sweep_snmp_host_split(prev: str, line: str) -> int | None:
    head = _SWEEP_ROW_TOKEN_RE.findall(prev)
    first = _SWEEP_ROW_TOKEN_RE.search(line)
    if head and first is not None and head[-1].casefold() == "snmp-server" and first.group(0).casefold() == "host":
        return first.end()
    return None


def _cred_cross_line_findings(prev: str, line: str) -> list[str]:
    """A grammar clause that starts on the previous non-blank line and whose value slot falls on this
    line (a terminal wrap) must carry the placeholder there."""
    tail = prev[-_CRED_JOIN_TAIL:]
    tail_folded = tail.casefold()
    if not _CRED_CROSS_NEEDLE_RE.search(tail_folded):
        return []                                            # speed only
    joined = tail + " " + line
    folded = joined.casefold()
    if len(joined) > _CRED_GRAMMAR_MAX_LINE or not _CRED_PREFILTER_RE.search(folded):
        return []
    offset = len(tail) + 1
    masked = _sweep_masked(line)
    kinds = []
    for family in _CRED_FAMILIES:
        if not family.cross:
            continue
        needles = _CRED_FAMILY_NEEDLES.get(family.name)
        if needles is not None and not any(needle in folded for needle in needles):
            continue
        for match in family.anchor.finditer(joined, 0, len(tail)):
            if _sweep_prose_before(joined, match.start()):
                continue
            if match.start() and joined[match.start() - 1] not in _CRED_WS_CHARS + _CRED_CLAUSE_LEAD:
                continue                                     # an anchor inside a token ('S3cret$Key')
            start = (_CRED_PROSE_START_RE if family.prose else _CRED_PLAIN_START_RE).match(joined, match.end())
            if start is None:
                continue
            position = family.qualifiers.match(joined, start.end()).end()
            if position < offset:
                continue
            token = _cred_token(joined, position)
            if token is None:
                continue
            value, end = token
            if ":" in joined[match.start():offset] or "=" in joined[match.start():offset]:
                continue
            if _cred_value_is_structural(value, end, family, joined, position):
                continue
            if _PLACEHOLDER in value:
                if not _sweep_token_ok(value):
                    kinds.append(f"credential value ({family.name}, wrapped onto the next line)")
                continue
            core = value.strip(_SWEEP_EDGE).casefold()
            if (_sweep_value_required(core) or core in _SWEEP_CONT_EXEMPT
                    or _sweep_starts_clause(line, masked, position - offset, end - offset)):
                continue
            kinds.append(f"credential value ({family.name}, wrapped onto the next line)")
    return kinds


def _sweep_continuation_violation(prev: str, line: str) -> bool:
    """A column-0 line after a line that holds more than the placeholder and ends with it: its one token
    (or its first token before a clause-trailing word, ``_SWEEP_CONT_TRAILERS``) must be redacted unless
    it is structure, a closed command word, a 'key=value' / 'key:' field or a clause of its own."""
    if not line or line[0] in _CRED_WS_CHARS:
        return False
    if not prev.rstrip(_CRED_WS_CHARS + _SWEEP_KEEP).endswith(_PLACEHOLDER):
        return False
    lone = len(_SWEEP_ROW_TOKEN_RE.findall(prev)) < 2
    tokens = _SWEEP_ROW_TOKEN_RE.findall(line)
    if not tokens or (len(tokens) > 1 and tokens[1].strip(_SWEEP_EDGE).casefold() not in _SWEEP_CONT_TRAILERS):
        return False
    token = tokens[0]
    folded = token.casefold()
    if lone and not _CREDENTIAL_SHAPE_RE.search(token):
        return False
    return not (_PLACEHOLDER in token or folded in _SWEEP_CONT_EXEMPT or folded in _SWEEP_COMMAND_WORDS
                or token.endswith(("#", ">", ":")) or _sweep_token_ok(token)
                or _SWEEP_UKEY_RE.match(token) or _SWEEP_QKEY_RE.match(token)
                or (len(tokens) > 1 and _sweep_starts_clause(line, _sweep_masked(line), 0, len(token))))


def _sweep_join_anchor(prev: str, line: str) -> int | None:
    if not prev or not line or prev[-1] in _CRED_WS_CHARS or line[0] in _CRED_WS_CHARS:
        return None
    head = _SWEEP_ROW_TOKEN_RE.findall(prev)
    tail = _SWEEP_ROW_TOKEN_RE.match(line)
    if not head or tail is None:
        return None
    left, right = head[-1].casefold(), tail.group(0).casefold()
    joined = _SWEEP_DANGLE_NORM_RE.sub("", left + right)
    if joined not in _SWEEP_DANGLE_KWS or _SWEEP_DANGLE_NORM_RE.sub("", left) in _SWEEP_DANGLE_KWS:
        return None
    return tail.end()


def _sweep_pct_decode(value: str) -> str:
    return _SWEEP_PCT_RE.sub(lambda m: chr(int(m.group(1), 16)), value)


def _sweep_url_findings(line: str) -> list[str]:
    kinds = []
    for match in _SWEEP_URL_RE.finditer(line):
        rest = match.group(0).partition("://")[2]
        at = rest.rfind("@")
        if at > 0:
            userinfo = rest[:at]
            secret = userinfo.partition(":")[2] if ":" in userinfo else userinfo
            if secret != _PLACEHOLDER:
                kinds.append("credential value (URL userinfo)")
        for query in _SWEEP_QUERY_RE.finditer(rest):
            if query.group("v") not in ("", _PLACEHOLDER) and (
                    query.group("name").casefold() in _SWEEP_QUERY_NAMES
                    or _SWEEP_KW_RE.search(_sweep_pct_decode(query.group("v")))):
                kinds.append("credential value (URL query parameter)")
    return kinds


def _sweep_xml_names_credential(tag: str) -> bool:
    return bool(_SWEEP_KW_RE.search(tag)) or _sweep_credential_name(tag.rpartition(":")[2], True)


def _sweep_xml_parent(line: str, pos: int) -> str | None:
    stack: list[str] = []
    for tag in _SWEEP_XML_ANY_TAG_RE.finditer(line, 0, pos):
        if tag.group("self"):
            continue
        name = tag.group("t")
        if tag.group("close"):
            if name in stack:
                del stack[len(stack) - 1 - stack[::-1].index(name):]
        else:
            stack.append(name)
    return stack[-1] if stack else None


def _sweep_xml_findings(line: str) -> list[str]:
    kinds = []
    for match in _SWEEP_XML_RE.finditer(line):
        value = _CRED_WS_RE.sub("", match.group("v"))
        tag = match.group("tag")
        if not value or value == _PLACEHOLDER:
            continue
        parent = _sweep_xml_parent(line, match.start())
        if _sweep_xml_names_credential(tag) or (
                parent is not None and _sweep_xml_names_credential(parent)
                and tag.rpartition(":")[2].casefold() not in _SWEEP_XML_STRUCT_CHILD):
            kinds.append("credential value (XML element)")
    if "=" in line:
        for tag in _SWEEP_XML_TAG_RE.finditer(line):
            for attr in _SWEEP_XML_ATTR_RE.finditer(tag.group("a")):
                if attr.group("v") not in ("", _PLACEHOLDER) and _sweep_credential_name(
                        attr.group("n").rpartition(":")[2], True):
                    kinds.append("credential value (XML attribute)")
    return kinds


def _sweep_argv_kind(name: str) -> str:
    folded = name.casefold()
    return ("snmp" if "snmp" in folded else "mysql" if folded.startswith("mysql")
            else "net" if folded.startswith("net") else folded)


def _sweep_netuse_structural(token: str) -> bool:
    core = token.strip(_SWEEP_KEEP)
    return (not core or core.startswith(("\\\\", "/")) or core == "*" or core == _PLACEHOLDER
            or bool(re.fullmatch(r"[A-Za-z]:", core)))


def _sweep_shell_violation(line: str) -> bool:
    """'echo user:PASSWORD | chpasswd' and a .pgpass line must carry the placeholder as the password."""
    if "chpasswd" in line and any(m.group("v") != _PLACEHOLDER for m in _SWEEP_CHPASSWD_RE.finditer(line)):
        return True
    if line.count(":") >= 4:
        found = _SWEEP_PGPASS_RE.match(line)
        if (found and found.group("v") != _PLACEHOLDER
                and not _sweep_is_address(line.strip(_CRED_WS_CHARS))):
            return True
    return False


def _sweep_line_word_lead(line: str, pos: int) -> bool:
    """Does a line WORD at ``pos`` (a directive or a positional keyword) start its statement? It does at the
    line start, or after a structural prefix: a comment '#', a quote '>', a grep 'path:' / 'path:N:', an
    '(item=' echo, a pipe (``_SWEEP_LINE_WORD_LEADS``), a diff '+' / '-', or a 'cat -n' line number. Scans back
    over the separators and digits before the word only, so a line of many words stays linear."""
    j = pos - 1
    while j >= 0 and line[j] in _CRED_WS_CHARS:
        j -= 1
    if j < 0 or line[j] in _SWEEP_LINE_WORD_LEADS:
        return True
    k = j
    while k >= 0 and line[k].isdigit() and j - k < 9:
        k -= 1
    if k == j and line[j] == "-":
        k = j - 1
    elif k == j:
        return False
    while k >= 0 and line[k] in _CRED_WS_CHARS:
        k -= 1
    return k < 0


def _sweep_line_words(line: str) -> list[re.Match[str]]:
    return [m for m in _SWEEP_SNMP_LINE_WORD_RE.finditer(line) if _sweep_line_word_lead(line, m.start())]


def _sweep_snmp_shape(line: str) -> bool:
    if _SWEEP_SNMP_SHAPE_STRONG_RE.search(line):
        return True
    return len({m.group(0)[1] for m in _SWEEP_SNMP_SHAPE_WEAK_RE.finditer(line)}) >= 2


def _sweep_argv_runs(line: str) -> list[tuple[str, int, bool]]:
    """``(kind, start, shape_only)`` of every shell-argument run, by start (the producer's rule restated):
    each listed command from its end, an SNMPCMD_ARGS directive that starts a statement, or else a net-snmp
    vector by its shape from the line start. Each run ends where the next one starts."""
    runs = [(_sweep_argv_kind(m.group("cmd")), m.end(), False) for m in _SWEEP_ARGV_CMD_RE.finditer(line)]
    if "-" in line:
        directive = next((m for m in _sweep_line_words(line) if m.group(0) in _SWEEP_SNMP_DIRECTIVES), None)
        if directive is not None:
            runs.append(("snmp", directive.end(), False))
        elif _sweep_snmp_shape(line):
            runs.append(("snmp", 0, True))
    return sorted(runs, key=lambda run: run[1])


def _sweep_argv_option(text: str, options: tuple[tuple[str, str], ...],
                       shape_only: bool) -> tuple[str, int | None] | None:
    for option, kind in options:
        if text == option:
            return kind, None
        if option.startswith("--"):
            if text.startswith(option + "="):
                return kind, len(option) + 1
        elif text.startswith(option) and len(text) > len(option):
            rest = text[len(option):]
            if shape_only and not (option in ("-c", "-A", "-X")
                                   or (option.startswith("-3") and re.fullmatch(r"(?:0x)?[0-9A-Fa-f]+", rest))):
                continue
            return kind, len(option)
    return None


def _sweep_operand_bad(text: str, kind: str) -> bool:
    """An operand word that does not hold the placeholder where the producer's ``_redact_operand_span`` puts it."""
    core = text.strip(_SWEEP_KEEP)
    if kind in ("userinfo", "userpct"):
        sep = ":" if kind == "userinfo" else "%"
        if sep not in core:
            return False
        core = core.partition(sep)[2]
    if kind == "protocol" and core.casefold() in _SWEEP_SNMP_PROTOCOLS:
        return False
    return bool(core) and core != _PLACEHOLDER and bool(core.strip(_SWEEP_KEEP))


def _sweep_argv_walk(line: str, carry: tuple[str, str | None] | None = None
                     ) -> tuple[list[tuple[int, int, str]], tuple[str, str | None] | None]:
    """The producer's ``_redact_argv_walk`` restated: every credential operand word span, and the run kind and
    expected operand kind when the vector continues on the next line (``carry``: this line continues one)."""
    runs = _sweep_argv_runs(line)
    if carry is not None:
        runs = [(carry[0], 0, False)] + [run for run in runs if run[1] > 0]
    if not runs:
        return [], None
    words = [m.span() for m in _SWEEP_ARGV_WORD_RE.finditer(line)]
    starts = [a for a, _b in words]
    operands: list[tuple[int, int, str]] = []
    pending: tuple[str, str | None] | None = None
    for index, (kind_name, run, shape_only) in enumerate(runs):
        stop = runs[index + 1][1] if index + 1 < len(runs) else len(line) + 1
        options = _SWEEP_ARGV_OPTIONS[kind_name]
        expect: str | None = carry[1] if (carry is not None and index == 0) else None
        position = bisect.bisect_left(starts, run)
        while position < len(words) and words[position][0] < stop:
            a, b = words[position]
            position += 1
            text = line[a:b]
            if kind_name == "net":
                if not _sweep_netuse_structural(text):
                    operands.append((a, b, "value"))
                continue
            option = _sweep_argv_option(text, options, shape_only)
            if expect is not None:
                operands.append((a, b, expect))
                expect = None
                if option is None:
                    continue
            if option is not None:
                kind, offset = option
                if offset is None:
                    expect = None if kind == "attached" else kind
                else:
                    operands.append((a + offset, b, kind))
        if index + 1 == len(runs) and (expect is not None or line.rstrip(_CRED_WS_CHARS).endswith(chr(92))):
            pending = (kind_name, expect)
    return operands, pending


def _sweep_positional_violation(line: str) -> bool:
    """A net-snmp positional credential ('usmUser' keys by field index, everything after a 'smuxpeer' OID)
    that is neither empty ('""') nor the placeholder."""
    end = None
    for word in _sweep_line_words(line):
        name = word.group(0).casefold()
        if name not in _SWEEP_SNMP_POSITIONAL:
            continue
        fields = list(itertools.islice(_SWEEP_SNMP_FIELD_RE.finditer(line, word.end()),
                                       max(_SWEEP_SNMP_POSITIONAL[name]) + 1))
        if name == "usmuser":
            if len(fields) < 2 or not (fields[0].group(0).isdigit() and fields[1].group(0).isdigit()):
                continue
            targets = [fields[i].group(0) for i in _SWEEP_SNMP_POSITIONAL[name] if i < len(fields)]
        else:
            if len(fields) < 2 or not _SWEEP_SNMP_OID_RE.fullmatch(fields[0].group(0)):
                continue
            if end is None:
                end = len(line.rstrip(_CRED_WS_CHARS))
            targets = [line[fields[1].start():end]]
        for text in targets:
            core = text.strip(_SWEEP_KEEP)
            if core and core != _PLACEHOLDER:
                return True
    return False


def _sweep_argv_violation(line: str, carry: tuple[str, str | None] | None = None) -> bool:
    """A credential operand of the closed shell-argument list that is not the placeholder."""
    return any(_sweep_operand_bad(line[a:b], kind) for a, b, kind in _sweep_argv_walk(line, carry)[0])


def _sweep_entropy(line: str) -> bool:
    if ("$" in line or "{" in line) and _SWEEP_CRYPT_RE.search(line):
        return True
    for regex in (_SWEEP_B64_RE, _SWEEP_HEX_RE, _SWEEP_TOKEN_FORMAT_RE):
        for match in regex.finditer(line):
            text = match.group(0)
            if regex is _SWEEP_B64_RE and not any(
                    _sweep_entropy_part(part) for part in re.split(r"[-_/]", text)):
                continue
            head = line[:match.start()]
            if (_SWEEP_IFACE_RE.fullmatch(text) or _SWEEP_SYNTH_RE.fullmatch(text)
                    or _SWEEP_DIGEST_LABEL_RE.search(head) or _SWEEP_PUBKEY_LABEL_RE.search(head)):
                continue
            return True
    return False


def _sweep_plan(lines: list[str]):
    """The stateful roles -- private-key blocks, credential table columns, FortiGate SNMP blocks --
    restated from the producer's rules; each is decided by text the scrub never alters."""
    pem: list[Any] = [None] * len(lines)
    table: list[Any] = [None] * len(lines)
    forti = [False] * len(lines)
    inside = False
    putty, putty_tail = 0, False
    depth, snmp_depth = 0, None
    for i, line in enumerate(lines):
        spans, pos = [], 0
        if putty:
            pem[i] = "body"
            putty -= 1
            putty_tail = putty == 0
        elif putty_tail and _B64_LINE_RE.fullmatch(_CRED_WS_RE.sub("", line)):
            pem[i] = "body"
        elif inside:
            end = _PEM_END_RE.search(line)
            if end is None:
                pem[i] = "body"
            else:
                spans.append((0, end.start()))
                pos, inside = end.end(), False
        low = line.casefold()                      # the substring gates below are speed only
        while pem[i] != "body" and "----" in line:
            begin = _PEM_BEGIN_RE.search(line, pos)
            if begin is None:
                break
            end = _PEM_END_RE.search(line, begin.end())
            if end is not None:
                spans.append((begin.end(), end.start()))
                pos = end.end()
                continue
            if _CRED_WS_RE.sub("", line[begin.end():]).strip("\"'"):
                spans.append((begin.end(), len(line)))
            else:
                inside = True
            break
        if spans:
            pem[i] = spans
        if pem[i] != "body":
            putty_tail = False
        if pem[i] != "body" and "private-lines" in low:
            found = _PUTTY_PRIVATE_RE.match(line)
            if found:
                putty = int(found.group("n"))
                pem[i] = "header"
        header = None
        for pattern, nxt, kind in (_TABLE_HEADERS if ("community" in low or "keyring" in low
                                                    or "secname" in low) else ()):
            found = pattern.match(line)
            if found:
                header = (kind, ((found.start("c"), found.start(nxt) if nxt else None),), None, ())
                break
        if header is None and pem[i] is None:
            header = _generic_table_header(line)
        table[i] = header
        config = _FORTI_CONFIG_RE.match(line) if "config" in low else None
        if config:
            depth += 1
            if snmp_depth is None and " ".join(config.group("path").split()).casefold() == "system snmp community":
                snmp_depth = depth
        elif "end" in low and _FORTI_END_RE.match(line):
            if snmp_depth is not None and depth == snmp_depth:
                snmp_depth = None
            depth = max(0, depth - 1)
        forti[i] = snmp_depth is not None
    return pem, table, forti


def _generic_table_header(line: str):
    """A generic credential table header (the producer's strict rule), as a plan entry, or None."""
    low = line.casefold()
    if not any(word in low for word in ("pass", "secret", "communit", "psk", "key", "preshared")):
        return None
    groups = list(_TABLE_GROUP_RE.finditer(line))
    if len(groups) < 3:
        return None
    names = []
    for group in groups:
        words = group.group(0).split(" ")
        if len(words) > 3 or not all(_TABLE_WORD_RE.fullmatch(word) for word in words):
            return None
        names.append(re.sub(r"[/_-]", "", "".join(words)).casefold())
    strong = [i for i, name in enumerate(names) if name in _TABLE_CRED_COLUMNS]
    if not strong:
        return None
    columns = sorted(set(strong) | {i for i, name in enumerate(names) if name in _TABLE_ALSO_COLUMNS})
    regions = tuple((groups[i].start(), groups[i + 1].start() if i + 1 < len(groups) else None) for i in columns)
    return ("generic", regions, len(groups), tuple(columns))


def _table_shape(tokens: list[tuple[int, int, str]], table) -> tuple[int, ...] | None:
    """The credential fields a row's SHAPE selects (the producer's rule, restated), or None."""
    kind, regions, count, columns = table
    n = len(tokens)
    if n < 2:
        return None
    if kind == "first":
        nxt = regions[0][1]
        if n > 4 or not (tokens[1][0] - tokens[0][1] >= 2
                         or (nxt is not None and tokens[0][0] < nxt <= tokens[1][0] + 2)):
            return None
        return (0,)
    if kind == "aireos":
        return (0,) if _SWEEP_IPV4_RE.fullmatch(tokens[1][2]) else None
    if kind == "isakmp":
        if n == 3 and (_sweep_is_address(tokens[1][2]) or "." in tokens[1][2]):
            return (2,)
        if n == 4 and _sweep_is_address(tokens[1][2]) and _sweep_is_address(tokens[2][2]):
            return (3,)
        return None
    if kind == "host":
        return tuple(range(5, n)) if n >= 6 and tokens[1][2].isdigit() else None
    return columns if n == count else None


def _table_fields(line: str, tokens: list[tuple[int, int, str]], table):
    """``(shape, cells)`` -- the producer's rule restated: the shape's fields plus every field overlapping a
    credential column; a line whose credential column holds the placeholder is a row whatever its shape."""
    regions = table[1]
    width = len(line)
    overlap = [i for i, (a, b, _text) in enumerate(tokens)
               if any(a < (width if e is None else e) and b > start for start, e in regions)]
    shape = _table_shape(tokens, table)
    if shape is None:
        if not any(_PLACEHOLDER in tokens[i][2] for i in overlap):
            return None
        shape = ()
    return shape, tuple(sorted(set(shape) | set(overlap)))


def _table_tokens(line: str) -> list[tuple[int, int, str]]:
    return [(m.start(), m.end(), m.group(0)) for m in _SWEEP_ROW_TOKEN_RE.finditer(line)]


def _table_row(line: str, banner: str, forti: bool, table) -> bool:
    """A row of the open credential table: its row shape (or a placeholder in its credential column), and no
    credential anchor OUTSIDE the fields its shape selects."""
    if _TABLE_END_RE.match(line) or _block_open(line) is not None or _CHAP_HEADER_RE.match(line):
        return False
    if not banner and _SWEEP_BANNER_RE.match(line):
        return False
    if any(d in line for d in _CSV_DELIMS) and _csv_header(line) is not None:
        return False
    tokens = _table_tokens(line)
    found = _table_fields(line, tokens, table)
    if found is None:
        return False
    rest = line
    for i in found[0]:
        a, b, _text = tokens[i]
        rest = rest[:a] + " " * (b - a) + rest[b:]
    return _sweep_anchor(rest, _sweep_masked(rest), forti) is None


def _csv_row(line: str, csv) -> bool:
    delim, count = csv[0], csv[1]
    if delim not in line:
        return False
    fields = len(_csv_split(line, delim))
    if not count - 1 <= fields <= count + 3:
        return False
    return fields == count or _csv_header(line) is None


def _pem_findings(lines: list[str], pem: list[Any]) -> list[str]:
    kinds = []
    for line, role in zip(lines, pem):
        if role == "body":
            if _CRED_WS_RE.sub("", line) not in ("", _PLACEHOLDER):
                kinds.append("private-key material")
        elif role and role != "header":
            for start, end in role:
                if _CRED_WS_RE.sub("", line[start:end]) not in ("", _PLACEHOLDER):
                    kinds.append("private-key material")
    return kinds


def _block_open(line: str):
    tail = line.rstrip(_CRED_WS_CHARS)
    if tail[-1:] in ("[", "{"):
        found = _JSON_OPEN_RE.search(line)
        if found and _sweep_credential_name(found.group("k"), True):
            return ("json", sum(1 for ch in found.group("b") if ch in "[{"))
    if tail[-1:] == ">":
        found = _XML_OPEN_RE.match(line)
        if found and _sweep_credential_name(found.group("t").rpartition(":")[2], True):
            return ("xml", found.group("t"), 1)
    if ":" in line:
        found = _YAML_OPEN_RE.match(line) or _YAML_VALUE_RE.match(line)
        if found and _sweep_credential_name(found.group("k"), False):
            return ("yaml", found.start("k"))
    return None


def _block_holds(block, line: str) -> bool:
    if block[0] != "yaml":
        return True
    lead = len(_SWEEP_LEAD_RE.match(line).group(0))
    if lead == len(line) or lead > block[1]:
        return True
    rest = line[lead:]
    return lead == block[1] and rest[:1] == "-" and (len(rest) == 1 or rest[1] in _CRED_WS_CHARS)


def _block_step(block, line: str):
    if block[0] == "json":
        bare = _JSON_STRING_RE.sub("", line)
        depth = block[1] + bare.count("{") + bare.count("[") - bare.count("}") - bare.count("]")
        return ("json", depth) if depth > 0 else None
    if block[0] == "xml":
        tag = block[1]
        opened = len(re.findall("<" + re.escape(tag) + r"(?=[\s/>])(?![^<>]*/>)", line))
        depth = block[2] + opened - line.count("</" + tag + ">")
        return ("xml", tag, depth) if depth > 0 else None
    return block


def _csv_split(line: str, delim: str) -> list[tuple[int, int]]:
    if '"' not in line:
        spans, start = [], 0
        for part in line.split(delim):
            spans.append((start, start + len(part)))
            start += len(part) + 1
        return spans
    spans, start, quoted = [], 0, False
    for i, ch in enumerate(line):
        if ch == '"':
            quoted = not quoted
        elif ch == delim and not quoted:
            spans.append((start, i))
            start = i + 1
    spans.append((start, len(line)))
    return spans


def _csv_core(field: str) -> str:
    return _CRED_WS_RE.sub(" ", field).strip(" \"'")


def _csv_header(line: str) -> tuple[str, int, frozenset[int]] | None:
    """A CSV/TSV header (two or more short identifier fields, one naming a credential or redacted): the
    rows that follow must carry the placeholder in those columns."""
    if not _CSV_HEADER_CHARS_RE.fullmatch(line):
        return None
    for delim in _CSV_DELIMS:
        if delim not in line:
            continue
        cores = [_csv_core(line[a:b]) for a, b in _csv_split(line, delim)]
        if len(cores) < 2 or not all(core == _PLACEHOLDER or _CSV_FIELD_RE.fullmatch(core) for core in cores):
            continue
        columns = frozenset(i for i, core in enumerate(cores)
                            if core == _PLACEHOLDER or _SWEEP_KW_RE.search(core)
                            or _sweep_credential_name(core, True))
        if columns:
            return (delim, len(cores), columns)
    return None


def _csv_violation(line: str, csv) -> bool:
    delim, count, columns = csv
    return any((i in columns or i >= count) and _csv_core(line[a:b]) not in ("", _PLACEHOLDER)
               for i, (a, b) in enumerate(_csv_split(line, delim)))


def _chap_row(line: str, banner: str) -> bool:
    fields = list(_SWEEP_ROW_TOKEN_RE.finditer(line))
    if len(fields) < 3:
        return False
    if _block_open(line) is not None or (not banner and _SWEEP_BANNER_RE.match(line)) or _CHAP_HEADER_RE.match(line):
        return False
    if any(d in line for d in _CSV_DELIMS) and _csv_header(line) is not None:
        return False
    a, b = fields[2].span()
    rest = line[:a] + " " * (b - a) + line[b:]
    return _sweep_anchor(rest, _sweep_masked(rest), False) is None


def _chap_violation(line: str) -> bool:
    """The secret (third) field of a chap-secrets row, by position, must be the placeholder."""
    if line.lstrip(_CRED_WS_CHARS).startswith("#"):
        return False
    fields = _SWEEP_ROW_TOKEN_RE.findall(line)
    return (len(fields) >= 3 and not (_PLACEHOLDER in fields[2] and _sweep_token_ok(fields[2]))
            and bool(fields[2].strip(_SWEEP_KEEP)))


def _raw_capture_credential_findings(text: str) -> list[str]:
    """Both guarantees over a whole raw capture, line by line (see the block comment above), plus this
    verifier's own independent checks (`_independent_credential_findings`).

    No line is exempt: a banner body, a description, a comment and a syslog record are swept like
    any other line, because a credential pasted into prose is still a credential. Every multi-line
    state (wraps, blocks, banners, CSV, chap-secrets) is advanced from the scrubbed lines, as the
    producer advances it from its own output."""
    lines = _cred_lines(text)
    pem, table, forti = _sweep_plan(lines)
    has_next = _cred_has_next(lines)
    kinds = _pem_findings(lines, pem)
    pending: Any = None
    region: Any = None
    prev_nb: str | None = None
    block: Any = None
    csv: Any = None
    chap = False
    expect = False
    banner = ""
    prev: str | None = None
    for index, line in enumerate(lines):
        blank = not _CRED_WS_RE.sub("", line)
        if table[index] is not None or pem[index] in ("body", "header"):
            if table[index] is not None:
                region = table[index]
            pending, block, csv, prev_nb = None, None, None, None
            prev = line
            continue
        in_block = block is not None and _block_holds(block, line)
        if not in_block:
            block = None
        opener = pending is not None and not blank and not in_block and (
            _block_open(line) is not None or (not banner and bool(_SWEEP_BANNER_RE.match(line)))
            or bool(_CHAP_HEADER_RE.match(line)))
        forced = not blank and in_block
        cont = pending if (pending is not None and not blank and not opener) else None
        csv_row = False
        if csv is not None and not blank:
            if _csv_row(line, csv):
                csv_row = True
            else:
                csv = None
        gate = None
        if csv is None and not blank and any(d in line for d in _CSV_DELIMS):
            gate = _csv_header(line)
        states = (not blank and not csv_row and gate is None
                  and not (_block_open(line) is not None or (not banner and bool(_SWEEP_BANNER_RE.match(line)))
                           or bool(_CHAP_HEADER_RE.match(line))))
        wraps = states and not in_block
        if wraps and prev_nb is not None:
            kinds.extend(_cred_cross_line_findings(prev_nb, line))
        carry = tuple(cont[1]) if (states and cont is not None and cont[0] == "argv") else None
        if carry is not None:
            if _sweep_argv_violation(line, carry):
                kinds.append("credential value (shell argument, continued from the previous line)")
        elif states and cont is not None and _sweep_clause_continuation_violation(line, cont[0], cont[1], 0, cont[2]):
            kinds.append("credential value (wrapped onto the next line)")
        if wraps and prev_nb is not None:
            split = _sweep_snmp_host_split(prev_nb, line)
            if split is not None and _sweep_clause_continuation_violation(line, "snmp-host", [], split):
                kinds.append("credential value (snmp-server host, wrapped onto the next line)")
        start = None if (banner or forced) else _SWEEP_BANNER_RE.match(line)
        delim = banner or (start.group("d") if start else "")
        prose = (0 if banner else start.end() if start else
                 0 if not forced and _SWEEP_PROSE_LINE_RE.match(line) else None)
        join = None if prev is None or forced else _sweep_join_anchor(prev, line)
        row = None
        if region is not None and not blank and not all(
                _DASHES_RE.match(cell) for cell in _SWEEP_ROW_TOKEN_RE.findall(line)):
            if _table_row(line, banner, forti[index], region):
                row = region
            else:
                region = None
        low = line.casefold()
        if (forced or prose is not None or join is not None or row is not None or forti[index]
                or _SWEEP_PREFILTER.search(low) or _SWEEP_RUN_RE.search(line) or _CRED_PREFILTER_RE.search(low)
                or _SWEEP_IGNORABLE_RE.search(line)):
            kinds.extend(_sweep_url_findings(line))
            if "<" in line:
                kinds.extend(_sweep_xml_findings(line))
            masked = _sweep_masked(line)
            anchor = 0 if forced else _sweep_anchor(line, masked, forti[index], prose, join)
            if anchor is not None and _sweep_residue(masked, anchor, delim):
                kinds.append("credential residue after a credential keyword")
            if ("-" in line or "net" in low) and _sweep_argv_violation(line):
                kinds.append("credential value (shell argument)")
            if _sweep_positional_violation(line):
                kinds.append("credential value (net-snmp positional field)")
            if ":" in line and _sweep_shell_violation(line):
                kinds.append("credential value (shell argument)")
            if _sweep_entropy(line):
                kinds.append("high-entropy token")
            kinds.extend(_credential_line_findings(line, artifact=False, has_next=has_next[index], delim=delim))
        if row is not None and any(not (_PLACEHOLDER in text and _sweep_token_ok(text)) and not _DASHES_RE.match(text)
                                   for i, (_a, _b, text) in enumerate(_table_tokens(line))
                                   if i in (_table_fields(line, _table_tokens(line), row) or ((), ()))[1]):
            kinds.append("credential table column")       # by position, whatever the cell spells
        if wraps and prev is not None and _sweep_continuation_violation(prev, line):
            kinds.append("credential value (wrapped value)")
        if expect and not blank:
            sent = _SWEEP_EXPECT_SEND_RE.match(line)
            if sent and sent.group("v") not in ("", _PLACEHOLDER):
                kinds.append("credential value (expect send)")
        if chap and not blank and not line.lstrip(_CRED_WS_CHARS).startswith("#"):
            if _chap_row(line, banner):
                if _chap_violation(line):
                    kinds.append("credential table column (chap-secrets)")
            else:
                chap = False
        if csv_row and _csv_violation(line, csv):
            kinds.append("credential table column (CSV)")
        header = None
        if csv is None and not blank and any(d in line for d in _CSV_DELIMS):
            csv = header = _csv_header(line)
        if not chap and "client" in low and _CHAP_HEADER_RE.match(line):
            chap = True
        if not blank and header is None:
            dangle = _sweep_dangle(line, carry)
            if dangle is not None and not has_next[index]:
                kind, tail, key_id = dangle
                if kind == "value" and len(tail) == 1 and _CRED_TYPE_DIGIT_RE.fullmatch(tail[0]) and not key_id:
                    kinds.append("credential value (terminal type digit)")
                dangle = None
            pending = dangle
        elif not blank:
            pending = None
        if banner:
            if banner in line:
                banner = ""
        elif start is not None and delim not in line[start.end():]:
            banner = delim
        if in_block:
            block = _block_step(block, line)
        elif block is None and not blank:
            block = _block_open(line)
        prev = line
        if not blank:
            prev_nb = line
            expect = bool(_SWEEP_EXPECT_PROMPT_RE.match(line))
    kinds.extend(_independent_credential_findings(text, lines))
    return kinds


# ---- THIS VERIFIER'S OWN CHECKS (no producer list restates them; see the block comment above) ----
_INDEPENDENT_JSON_START_RE = re.compile(r"[{\[]")


def _independent_value_ok(value: Any) -> bool:
    """A leaf under a credential-named key: the placeholder, structure, a small integer, or nothing."""
    if value is None or isinstance(value, bool):
        return True
    if isinstance(value, (int, float)):
        return value == int(value) and 0 <= value <= 15
    if isinstance(value, str):
        return all(_sweep_token_ok(token) for token in _SWEEP_TOKEN_RE.findall(value))
    return True


def _independent_json_findings(value: Any, secret: bool, kinds: list[str], depth: int = 0) -> None:
    if depth > MAX_JSON_DEPTH:
        kinds.append("credential JSON nesting beyond the verification depth")
        return
    if isinstance(value, dict):
        for key, child in value.items():
            name = str(key).rpartition(":")[2]
            _independent_json_findings(child, secret or _is_secret_key(name), kinds, depth + 1)
    elif isinstance(value, list):
        for child in value:
            _independent_json_findings(child, secret, kinds, depth + 1)
    elif secret and not _independent_value_ok(value):
        kinds.append("credential value (parsed JSON field)")


def _independent_credential_findings(text: str, lines: list[str]) -> list[str]:
    """Checks with NO counterpart list in the producer, so a producer gap fails closed.

    1. Every JSON document embedded in the capture (the whole text, and the first object or array on
       each line) is PARSED, and every leaf under a key ``_is_secret_key`` names must be the
       placeholder, structure or a small integer -- whatever line it sits on.
    2. Every ``name: value`` / ``name=value`` / ``"name": value`` field whose name ``_is_secret_key``
       calls a credential must carry the placeholder or structure as its first value token."""
    kinds: list[str] = []
    decoder = json.JSONDecoder()
    documents = []
    stripped = text.lstrip()
    if stripped[:1] in ("{", "["):
        try:
            documents.append(json.loads(stripped))
        except ValueError:
            pass
    for line in lines:
        if not ("{" in line or "[" in line) or '"' not in line:
            continue
        start = _INDEPENDENT_JSON_START_RE.search(line)
        if start is None:
            continue
        try:
            document, _end = decoder.raw_decode(line, start.start())
        except ValueError:
            continue
        if isinstance(document, (dict, list)):
            documents.append(document)
    for document in documents:
        _independent_json_findings(document, False, kinds)
    for line in lines:
        if not ("=" in line or ":" in line) or not _SWEEP_NAME_HINT_RE.search(line.casefold()):
            continue
        masked = _sweep_masked(line)
        for regex, quoted in ((_SWEEP_QKEY_RE, True), (_SWEEP_UKEY_RE, False)):
            for match in regex.finditer(masked):
                name = match.group("k").rpartition(":")[2] if quoted else match.group("k")
                if not _is_secret_key(name):
                    continue
                value = _SWEEP_TOKEN_RE.search(masked, match.end())
                if value is None or _SWEEP_LEAD_RE.fullmatch(masked[match.end():value.start()]) is None:
                    continue                              # no value on this line, or not right after the name
                token = value.group(0)
                if token.strip(_SWEEP_EDGE + "|>-+") and not _sweep_token_ok(token):
                    kinds.append("credential value (credential-named field)")
    return kinds


#: FortiGate secret attributes must carry NOTHING but the placeholder after the attribute (and ENC), or
#: open a private-key block whose body the PEM rule verifies. Matched per line of `_cred_lines`. In a raw
#: capture an EMPTY value is a terminal wrap: the next non-blank line must then be all placeholder or
#: structure (the producer sweeps it whole).
_STRICT_SECRET_LINE_RES = (
    re.compile(_v(r"{h}*set{H}(?:passwd|psksecret|password|private-key|passphrase)\d{0,2}{H}"
                  r"(?:ENC{H})?(?P<value>.*?){h}*\Z"), re.IGNORECASE),
)


def _strict_value_ok(value: str) -> bool:
    value = _CRED_EDGE_WS_RE.sub("", value)
    if value[:1] in {'"', "'"} and value[-1:] == value[:1] and len(value) > 1:
        value = value[1:-1]
    if _PEM_BEGIN_RE.fullmatch(_CRED_EDGE_WS_RE.sub("", value).strip("\"'")):
        return True
    tokens = [token for token in _CRED_WS_RE.split(value) if token]
    return bool(tokens) and all(token.strip("\"'").casefold() == _PLACEHOLDER for token in tokens)


def _strict_findings(lines: list[str], *, wrap: bool = False) -> list[str]:
    kinds = []
    for index, line in enumerate(lines):
        for pattern in _STRICT_SECRET_LINE_RES:
            match = pattern.match(line)
            if match is None or _strict_value_ok(match.group("value")):
                continue
            if wrap and not _CRED_EDGE_WS_RE.sub("", match.group("value")).replace("ENC", "").strip():
                following = next((other for other in lines[index + 1:] if _CRED_WS_RE.sub("", other)), None)
                if following is not None and all(_sweep_token_ok(token)
                                                  for token in _SWEEP_TOKEN_RE.findall(following)):
                    continue
            kinds.append("credential residue")
    return kinds


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

    # Authored prose, generated code and free-text device fields (an interface description that
    # begins with "password reset ...") share these surfaces, and the engine writes some of them
    # AFTER the producer's scrub (the design blueprint is computed from the redacted snapshot), so the
    # residual-sweep guarantee does not hold here and is not asserted. What is asserted: the grammar's
    # VALUE slot on lines that OPEN like a configuration form (each family's `artifact` anchors), and
    # no private-key material -- authored copy never carries private-key armor. The full sweep
    # guarantee runs on raw captures in `verify_collection_secret_scrub`
    # (docs/w60-redaction-grammar-2026-10-09.md).
    lines = _cred_lines(text)
    for line in lines:
        for kind in _credential_line_findings(line, artifact=True):
            _append(leaks, kind, where)
    for kind in _pem_findings(lines, _sweep_plan(lines)[0]):
        _append(leaks, kind, where)
    for kind in _strict_findings(lines):
        _append(leaks, kind, where)


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
            for kind in _raw_capture_credential_findings(text):
                _append(leaks, kind, str(path.relative_to(root)))
            for kind in _strict_findings(_cred_lines(text), wrap=True):
                _append(leaks, kind, str(path.relative_to(root)))
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
    encoded = json.dumps([rows, uncovered], separators=(",", ":"),
                         ensure_ascii=True).encode("ascii")
    return {
        "files": len(rows),
        "sha256": hashlib.sha256(encoded).hexdigest(),
        # Coverage honesty travels WITH the proof: a caller that reads only `files` still cannot
        # print "verified" over a folder where N files were never looked at, because `uncovered`
        # is bound into `sha256` and is right there in the same dict.
        "uncovered": [{"file": rel, "reason": why} for rel, why in uncovered],
    }
