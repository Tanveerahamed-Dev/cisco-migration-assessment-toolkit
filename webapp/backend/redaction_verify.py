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
#: W60 -- THE CREDENTIAL-LINE GRAMMAR, stated independently of the producer.
#:
#: The rule used to be "the token right after a credential keyword must be the placeholder". The
#: producer obeyed it by redacting whatever token stood there -- often a QUALIFIER -- so
#: ``enable password <redacted> 15 Plain99pw`` and ``set-key <redacted> Wlc99psk 1`` certified clean
#: while the credential sat one token further on. Now each keyword family is parsed as KEYWORD,
#: QUALIFIER RUN, VALUE, TAIL:
#:
#: * the qualifier run (``level N``, type digits, cipher/plain/ascii/hex/ENC, hash labels, read/write,
#:   vrf X, traps/informs, version 1|2c, ...) is consumed greedily; the VALUE is the next token;
#: * a value that is a structural/prose follow-word (``key chain``, ``password encryption``,
#:   ``Key name:``, ``password for user``) means the line carries no credential;
#: * any other value must be the placeholder ("credential value" otherwise); and
#: * after the placeholder, every token must come from a CLOSED allowlist of structural follow-words
#:   (``_CRED_TAIL_WORDS``), a slot keyword plus its one operand (``_CRED_TAIL_SLOTS``), an address,
#:   another placeholder, or a family's own positional operand ("credential residue" otherwise).
#:
#: An allowlist, not a denylist of secret shapes: an unknown follow-word REFUSES. That is the
#: deliberate failure direction -- a refused scrub is re-checked by a person, a certified leak is not.
#: The producer (``cisco_toolkit.html._REDACT_SECRET_RES``) restates the same grammar; neither imports
#: the other, and tests/test_redaction_grammar_corpus.py pins them against the same adversarial corpus.
_CRED_HASH = (r"(?:(?:hmac-|keyed-|ietf-)?(?:md5|sha(?:-?(?:1|224|256|384|512))?)"
              r"|cmac-aes(?:-?(?:128|256))?|aes-(?:128|256)-cmac)")
_CRED_TYPE = r"(?:10|[0-9])"
_CRED_PROSE_STOPS = frozenset({
    "a", "an", "the", "to", "for", "with", "of", "in", "on", "at", "by", "from", "and", "or", "not", "no",
    "is", "are", "was", "were", "be", "been", "being", "must", "should", "shall", "will", "can", "cannot",
    "may", "might", "has", "have", "had", "this", "that", "these", "those", "it", "its", "as", "if", "when",
    "which", "who", "you", "your", "our", "their", "all", "any", "every", "each", "only", "also", "here",
    "there", "than", "so", "but", "into", "via", "per", "without", "within", "none", "configured",
    "enabled", "disabled", "required", "expired", "failed", "failure", "mismatch", "changed", "set",
})
_CRED_PROSE_START_RE = re.compile(r'"?[ \t]*(?:=>|[:=])[ \t]*|[ \t]+')
_CRED_PLAIN_START_RE = re.compile(r"[ \t]+")
_CRED_TOKEN_RE = re.compile(r""""(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|\S+""")
_CRED_PLACEHOLDER_RE = re.compile(re.escape(_PLACEHOLDER), re.IGNORECASE)
_CRED_URL_PASSWORD_RE = re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s/:@]+:(?P<value>[^\s/]+)(?=@)", re.IGNORECASE)


class _CredFamily:
    """One keyword family: where it starts, what may stand between keyword and value, and how its
    tail is read. Plain data; the parse lives in `_credential_line_findings`.

    ``artifact`` lists the LINE-START anchors under which the family is also read in shareable
    artifacts (snapshot strings, OOXML text, HTML), where authored prose shares the surface. They
    restate the line-start coverage this module always had there, and nothing wider; a raw capture
    is device text and is read with ``anchor`` anywhere in the line."""

    __slots__ = ("name", "anchor", "artifact", "qualifiers", "stops", "prose", "address_is_structural",
                 "trailing_integer", "integers", "positional_acl")

    def __init__(self, name: str, anchor: str, qualifiers: Iterable[str] = (), stops: Iterable[str] = (),
                 *, prose: bool = False, artifact: Iterable[str] = (), address_is_structural: bool = False,
                 trailing_integer: bool = False, integers: bool = False, positional_acl: bool = False):
        steps = list(qualifiers) + ([r"=>|[:=]|is"] if prose else [])
        self.name = name
        self.anchor = re.compile(anchor, re.IGNORECASE)
        self.artifact = tuple(re.compile(pattern, re.IGNORECASE) for pattern in artifact)
        self.qualifiers = re.compile(
            r"(?:(?:" + "|".join(steps) + r")(?:[ \t]+|\Z))*" if steps else r"", re.IGNORECASE)
        self.stops = frozenset(word.casefold() for word in stops) | _CRED_PROSE_STOPS
        self.prose = prose
        self.address_is_structural = address_is_structural
        self.trailing_integer = trailing_integer
        self.integers = integers
        self.positional_acl = positional_acl


_CRED_COMMUNITY_QUALIFIERS = (
    r"strings?", r"create", r"delete", r"read", r"write", r"cipher", r"plain",
    r"(?:name|index|securityname)[ \t]*:", r"accessmode[ \t]+(?:ro|rw)", r"ipaddr[ \t]+\S+[ \t]+\S+",
    r"mode[ \t]+(?:enable|disable)",
)
_CRED_COMMUNITY_STOPS = ("name", "names", "list", "complexity-check")
_CRED_FAMILIES: tuple[_CredFamily, ...] = (
    _CredFamily("fortigate set", r"\bset[ \t]+(?:passwd|password|psksecret|psksecret-remote|secret|"
                r"secondary-secret|tertiary-secret|private-key|passphrase|auth-pwd|priv-pwd|sae-password|key|"
                r"authentication-key|auth-string|ppk-secret|eap-password)", (r"ENC",),
                artifact=(r"^\s*set\s+(?:passwd|psksecret|password|private-key|passphrase)",)),
    _CredFamily("snmp user auth", r"\bsnmp-server[ \t]+user[ \t]+.*?[ \t]auth", (_CRED_HASH,)),
    _CredFamily("snmp user priv", r"\bsnmp-server[ \t]+user[ \t]+.*?[ \t]priv",
                (r"3?des", r"aes(?:-?(?:128|192|256))?", r"128", r"192", r"256")),
    _CredFamily("aireos v3user auth", r"\bconfig[ \t]+snmp[ \t]+v3user[ \t]+create[ \t]+\S+[ \t]+(?:ro|rw)"
                r"[ \t]+(?:none|hmacmd5|hmacsha)[ \t]+(?:none|des|aescfb128|aes)"),
    _CredFamily("aireos v3user priv", r"\bconfig[ \t]+snmp[ \t]+v3user[ \t]+create[ \t]+\S+[ \t]+(?:ro|rw)"
                r"[ \t]+(?:none|hmacmd5|hmacsha)[ \t]+(?:none|des|aescfb128|aes)[ \t]+\S+"),
    _CredFamily("snmp host community", r"\bsnmp-server[ \t]+host[ \t]+\S+",
                (r"vrf[ \t]+\S+", r"traps?", r"informs?", r"version[ \t]+(?:1|2c)"),
                ("version", "use-vrf", "filter-vrf", "source-interface", "vrf", "community", "poll",
                 "udp-port"), address_is_structural=True, artifact=(r"^\s*snmp-server\s+host\s+\S+",)),
    _CredFamily("snmp community", r"\b(?:snmp-server|snmp-agent|snmp)(?:[ \t]+.*?)?[ \t]+community",
                _CRED_COMMUNITY_QUALIFIERS, _CRED_COMMUNITY_STOPS, prose=True, integers=True,
                positional_acl=True, artifact=(r"^\s*snmp-server\s+community",)),
    # Junos 'community X {'. Not prose: a bare 'Community:' is the BGP path-attribute label in
    # 'show ip bgp <prefix>' ('Community: 65000:100 no-export'), never a credential.
    _CredFamily("community block", r"^[ \t]*community", _CRED_COMMUNITY_QUALIFIERS, _CRED_COMMUNITY_STOPS,
                integers=True, positional_acl=True, artifact=(r"^\s*community",)),
    # 'SNMP community string : X' / 'Community name: X'.
    _CredFamily("community prose", r"\bcommunity(?=[ \t]+strings?\b|[ \t]+(?:name|index|securityname)"
                r"[ \t]*:)", _CRED_COMMUNITY_QUALIFIERS, _CRED_COMMUNITY_STOPS, prose=True, integers=True,
                positional_acl=True),
    _CredFamily("aireos radius/tacacs", r"\bconfig[ \t]+(?:radius|tacacs)[ \t]+(?:auth|acct|athr)[ \t]+add"
                r"[ \t]+\d+[ \t]+\S+[ \t]+\d+", (r"ascii", r"hex")),
    _CredFamily("aireos user", r"\bconfig[ \t]+(?:mgmtuser|netuser)[ \t]+(?:add|password)[ \t]+\S+"),
    _CredFamily("password", r"\b(?:password|passwd|secret|passphrase)(?<!mgmtuser password)(?<!netuser password)",
                (r"level[ \t]+\d+", _CRED_TYPE, _CRED_HASH, r"scrypt", r"ENC", r"encrypted", r"clear",
                 r"cipher", r"plain", r"simple", r"irreversible-cipher", r"hashed", r"text"),
                ("encryption", "encrypt", "expiration", "expiry", "policy", "recovery", "min-length",
                 "max-length", "minimum-length", "maximum-length", "prompt", "history", "change-type",
                 "format", "aging", "complexity", "strength-check", "keychain", "key-chain", "management",
                 "encryption-key", "keyboard", "publickey"),
                prose=True,
                artifact=(r"^\s*(?:enable\s+)?(?:password|secret)",
                          r"^\s*(?:username|user)\s+\S+(?:\s+(?:privilege\s+\d+|role\s+\S+|algorithm-type\s+\S+"
                          r"|view\s+\S+))*\s+(?:password|secret)")),
    _CredFamily("huawei securityname", r"\bsecurityname", (r"cipher", r"plain")),
    _CredFamily("tacacs/radius key", r"\b(?:tacacs-server|radius-server)[ \t]+(?:.*?[ \t])?key", (r"[0-9]",),
                artifact=(r"^\s*(?:tacacs-server|radius-server)\s+(?:.*?\s)?key",)),
    _CredFamily("key-string", r"\bkey-string", (r"[0-9]", r"password", r"clear", r"encrypted"),
                artifact=(r"^\s*key-string",)),
    _CredFamily("key-octet-string", r"\bkey-octet-string", (r"[0-9]",)),
    _CredFamily("pre-shared-key", r"\bpre-shared-key",
                (r"local", r"remote", r"ascii-text", r"hexadecimal", r"cipher", r"simple", r"plain",
                 r"[0-9]"),
                ("address", "hostname", "key-chain", "keychain", "ckn", "cak", "keyring"),
                artifact=(r"^\s*pre-shared-key",)),
    _CredFamily("shared-key", r"(?<![\w-])shared-key", (r"cipher", r"simple", r"plain", r"[0-9]")),
    _CredFamily("macsec cak/ckn", r"\b(?:cak|ckn)"),
    _CredFamily("wpa-psk", r"\bwpa2?-psk", (r"ascii", r"hex", r"[0-9]")),
    _CredFamily("set-key", r"\bset-key", (r"ascii", r"hex", r"[0-9]"), trailing_integer=True),
    _CredFamily("nhrp authentication", r"\bnhrp[ \t]+authentication", (r"[0-9]",)),
    _CredFamily("fhrp authentication", r"\b(?:standby|vrrp|glbp)(?:[ \t]+\d+)?(?:[ \t]+peer)?[ \t]+"
                r"authentication", (r"text", r"md5", r"ietf-md5"), ("key-chain", "key-string", "keychain", "key")),
    _CredFamily("block authentication text", r"^[ \t]*authentication(?=[ \t]+text[ \t])", (r"text",)),
    _CredFamily("authentication-mode", r"\b(?:area-|domain-)?authentication-mode",
                (_CRED_HASH, r"simple", r"plain", r"cipher", r"usual", r"nonstandard", r"key-id", r"\d+"),
                ("keychain", "key-chain", "hwtacacs", "radius", "local", "aaa", "password", "scheme")),
    _CredFamily("privacy-mode", r"\bprivacy-mode", (r"des56", r"3des", r"aes\d*", r"cipher", r"plain")),
    _CredFamily("ospfv3 ipsec authentication", r"\bauthentication[ \t]+ipsec[ \t]+spi[ \t]+\d+",
                (r"md5", r"sha1", r"[0-9]")),
    _CredFamily("eigrp hmac-sha-256", r"\bauthentication[ \t]+mode[ \t]+hmac-sha-256", (r"[0-9]",)),
    _CredFamily("show standby text", r"\bauthentication[ \t]+text,[ \t]+string"),
    # Not a prose family: 'Key: U - Unicast, B - Broadcast' is the 'show storm-control' legend. An EOS
    # 'ssh-key ssh-rsa <PUBLIC KEY>' is not a secret.
    _CredFamily("key", r"\bkey(?<!private-key)(?<!shared-key)(?<!public-key)(?<!ssh-key)",
                (r"\d+", _CRED_HASH, r"ENC", r"encrypted", r"clear", r"ascii", r"hex", r"cipher", r"plain",
                 r"text", r"--", r"config-key", r"password-encrypt"),
                ("chain", "local", "remote", "generate", "zeroize", "import", "export", "id", "name", "data",
                 "change", "type", "usage", "exchange", "pair", "length", "size", "sizes", "lifetime",
                 "rollover", "hash", "label", "storage", "ring", "management", "encryption", "mode",
                 "mypubkey", "pubkey", "pubkey-chain", "server", "algorithm", "algorithms", "recovery",
                 "string", "prefer", "source", "version", "minpoll", "maxpoll", "burst", "iburst", "vrf",
                 "use-vrf", "rsa", "dsa", "ecdsa", "ed25519"),
                trailing_integer=True, artifact=(r"^\s*crypto\s+isakmp\s+key",)),
)
#: A literal every match of a family's raw-capture anchor contains (compared casefolded, a superset of
#: the anchors' IGNORECASE matching): a family is skipped on a line holding none of its needles. Speed
#: only -- the anchor still decides -- and a family with no entry here is never skipped.
_CRED_FAMILY_NEEDLES = {
    "fortigate set": ("set",), "snmp user auth": ("snmp-server",), "snmp user priv": ("snmp-server",),
    "aireos v3user auth": ("v3user",), "aireos v3user priv": ("v3user",),
    "snmp host community": ("snmp-server",), "snmp community": ("community",),
    "community block": ("community",), "community prose": ("community",),
    "aireos radius/tacacs": ("config",), "aireos user": ("config",),
    "password": ("password", "passwd", "secret", "passphrase"), "huawei securityname": ("securityname",),
    "tacacs/radius key": ("-server",), "key-string": ("key-string",),
    "key-octet-string": ("key-octet-string",), "pre-shared-key": ("pre-shared-key",),
    "shared-key": ("shared-key",), "macsec cak/ckn": ("cak", "ckn"), "wpa-psk": ("-psk",),
    "set-key": ("set-key",), "nhrp authentication": ("nhrp",), "fhrp authentication": ("standby", "vrrp", "glbp"),
    "block authentication text": ("authentication",), "authentication-mode": ("authentication-mode",),
    "privacy-mode": ("privacy-mode",), "ospfv3 ipsec authentication": ("ipsec",),
    "eigrp hmac-sha-256": ("hmac-sha-256",), "show standby text": ("string",), "key": ("key",),
}
#: Cheap prefilter: a line that names none of these words cannot start any family above.
_CRED_PREFILTER_RE = re.compile(
    r"password|passwd|secret|passphrase|community|key|auth|priv|psk|cak|ckn|config|snmp|securityname|://",
    re.IGNORECASE)
#: Structural follow-words that may stand after the placeholder. CLOSED: a word missing here makes the
#: verifier refuse the line, which is the safe direction (docs/w60-redaction-grammar-2026-10-09.md).
_CRED_TAIL_WORDS = frozenset({
    # access levels and owners (IOS/IOS-XR/Junos/AireOS)
    "read-only", "read-write", "sdrowner", "systemowner", "lobby-admin",
    # hash/storage markers that FOLLOW the value (ASA, NX-OS SNMPv3)
    "encrypted", "pbkdf2", "nt-encrypted", "mschap", "hashed", "localizedkey", "localizedv2key", "auto",
    # SNMPv3 privacy protocols and key sizes
    "priv", "des", "3des", "aes", "aes-128", "aes-192", "aes-256", "aes128", "aes192", "aes256",
    "128", "192", "256",
    # NX-OS RADIUS/TACACS+ host roles, IS-IS levels, crypto isakmp, MACsec
    "authentication", "accounting", "single-connection", "level-1", "level-2", "level-1-2", "no-xauth",
    "cak", "ckn",
    # Junos hierarchy punctuation and the SECRET-DATA annotation
    "##", "secret-data", "{", "}", "[", "]", ";",
    # Huawei SNMP target-host security model after the securityname
    "v1", "v2c", "v3", "private-netmanager", "ext-vb",
    # SNMP notification types after a trap-host community (IOS-XE, NX-OS)
    "traps", "informs", "aaa_server", "adslline", "alarms", "atm", "auth-framework", "bfd", "bgp",
    "bgp4-mib", "bridge", "bstun", "bulkstat", "call-home", "casa", "cbgp2", "ccme", "cef", "cluster",
    "cnpd", "config", "config-copy", "config-ctid", "cpu", "cts", "dhcp", "dial", "dlsw", "dot1x", "ds1",
    "dsp", "eigrp", "energywise", "entity", "entity-diag", "entity-qfp", "entity-sensor", "entity-state",
    "envmon", "errdisable", "ethernet", "ethernet-cfm", "event-manager", "firewall", "flash",
    "flex-links", "flowmon", "frame-relay", "fru-ctrl", "hsrp", "ike", "ipmobile", "ipmulticast", "ipsec",
    "ipsla", "isakmp", "isdn", "isis", "l2tun", "l2tun-pseudowire-status", "l2tun-session", "license",
    "llc2", "local-auth", "mac-notification", "memory", "mpls", "mpls-ldp", "mpls-traffic-eng",
    "mpls-vpn", "msdp", "mvpn", "nhrp", "ospf", "ospfv3", "pim", "pki", "port-security",
    "power-ethernet", "pppoe", "pw", "rep", "resource-policy", "rf", "rmon", "rsvp", "rtr", "sdlc",
    "smart-license", "snmp", "sonet", "srp", "stackwise", "storm-control", "stpx", "stun", "syslog",
    "transceiver", "trustsec", "tty", "vlan-membership", "vlancreate", "vlandelete", "voice", "vrfmib",
    "vrrp", "vstack", "vtp", "wireless", "x25", "xgcp",
})
#: Structural keywords that own exactly ONE following operand (a name, ACL, address, number or level).
_CRED_TAIL_SLOTS = frozenset({
    "level", "privilege", "role", "view", "group", "ipv4", "ipv6", "use-acl", "use-ipv4acl",
    "use-ipv6acl", "access", "address", "hostname", "vrf", "udp-port", "port", "timeout", "engineid",
    "authorization", "cryptographic-algorithm", "version", "context", "clients", "community", "members",
    "auth-port", "acct-port", "source-interface", "use-vrf", "filter-vrf", "key-id", "privacy-mode",
    "authentication-mode",
})
_CRED_ACCESS_WORDS = frozenset({"ro", "rw"})
#: A whole line of free text, a syslog record or a comment: only the cleartext test applies there,
#: never the tail allowlist (prose follows a credential word in English). A banner body is tracked
#: separately by `_raw_capture_credential_findings`.
_CRED_FREE_TEXT_RE = re.compile(
    r"^\s*(?:[!#]|(?:description|remark|alias|comments?)\b|set\s+(?:description|comments?)\b)"
    r"|%[A-Z][A-Z0-9_]*-\d-[A-Z0-9_]+:", re.IGNORECASE)
_CRED_BANNER_RE = re.compile(
    r"^\s*banner\s+(?:motd|login|exec|incoming|slip-ppp|prompt-timeout|config-save)\b[ \t]*(?P<delim>\^C|\S)?",
    re.IGNORECASE)
_CRED_BANNER_MAX_LINES = 400


def _cred_token(line: str, pos: int) -> tuple[str, int] | None:
    match = _CRED_TOKEN_RE.match(line, pos)
    return (match.group(0), match.end()) if match else None


def _cred_value_is_structural(value: str, family: _CredFamily) -> bool:
    """A follow-word, label or punctuation where the value would stand: the line has no credential."""
    if value[:1] in {'"', "'"}:
        return False                                     # a quoted token is always a value
    head = re.split(r"[;,.]", value, maxsplit=1)[0].casefold()
    if head in family.stops:
        return True
    if value.endswith(":") and '"' not in value and "'" not in value:   # 'Key name:', 'Data:'
        return True
    if not value.strip("{}[];"):
        return True
    # 'snmp-server host <ifname> <ip> community X' (ASA): an address -- or, in a redacted snapshot,
    # its synthetic pseudonym -- in the value slot is the host, not a community.
    return family.address_is_structural and _cred_is_address(value)


def _cred_is_address(token: str) -> bool:
    try:
        ipaddress.ip_network(token, strict=False)
    except ValueError:
        return bool(_SYNTH_MARKER_RE.fullmatch(token))
    return True


def _cred_is_placeholder(token: str) -> bool:
    """The placeholder, allowing the punctuation a config or JSON line closes it with."""
    return token.rstrip(";,)}]").casefold() == _PLACEHOLDER


def _cred_clauses(line: str, artifact: bool) -> list[tuple[_CredFamily, int, str, int]]:
    """Every credential clause on the line: (family, keyword start, value token, value end).

    A clause whose grammar ends after its qualifiers, or whose value slot holds a structural
    follow-word, carries no credential and is not returned."""
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
            if _cred_value_is_structural(value, family):
                continue
            anchor_text = match.group(0)
            keyword_start = match.start() + max(anchor_text.rfind(" "), anchor_text.rfind("\t")) + 1
            clauses.append((family, keyword_start, value, end))
    return clauses


def _cred_tail_is_structural(line: str, start: int, family: _CredFamily,
                             nested: list[tuple[int, int]]) -> bool:
    """Is every token after the placeholder (``line[start:]``) structural?

    Structural means: a word of the closed allowlist, a slot keyword plus its one operand, an address,
    another placeholder, a family's own positional operand, or a token inside another credential clause
    on the same line whose own value is the placeholder (``nested``: C9800 'mgmtuser username u password
    0 <redacted> secret 0 <redacted>', 'auth sha <redacted> priv aes 128 <redacted>')."""
    tokens = list(_CRED_TOKEN_RE.finditer(line, start))
    acl_open = False          # one positional ACL operand may follow 'RO|RW' or an 'ipv6 <nacl>' pair
    index = 0
    while index < len(tokens):
        found = tokens[index]
        token = found.group(0).rstrip(";,").casefold()
        last = index == len(tokens) - 1
        index += 1
        if any(span_start <= found.start() < span_end for span_start, span_end in nested):
            continue
        if not token or _cred_is_placeholder(token) or token in _CRED_TAIL_WORDS or _cred_is_address(token):
            continue
        if token in _CRED_TAIL_SLOTS:
            index += 1                                    # the slot's one operand
            acl_open = family.positional_acl and token == "ipv6"
            continue
        if token in _CRED_ACCESS_WORDS:
            acl_open = family.positional_acl
            continue
        if token.isdigit() and (family.integers or (family.trailing_integer and last)):
            continue
        if acl_open:
            acl_open = False                              # the ONE positional ACL operand
            continue
        return False
    return True


def _credential_line_findings(line: str, *, artifact: bool, tail_exempt: bool) -> list[str]:
    """Every credential-grammar violation on one line, as finding kinds (empty = clean).

    ``artifact`` reads only the families' line-start ``artifact`` anchors (a shareable artifact also
    carries authored prose and generated code); otherwise every family anchor anywhere in the line is
    read, plus URL userinfo (a raw capture is device text)."""
    placeholders = [found.start() for found in _CRED_PLACEHOLDER_RE.finditer(line)]
    if not placeholders and not _CRED_PREFILTER_RE.search(line):
        return []
    kinds: list[str] = []
    explained: set[int] = set()
    if not artifact:
        for match in _CRED_URL_PASSWORD_RE.finditer(line):
            if match.group("value").casefold() != _PLACEHOLDER:
                kinds.append("credential value (URL userinfo)")
            else:
                explained.add(match.start("value"))
    clauses = _cred_clauses(line, artifact)
    nested = [(keyword_start, end) for _family, keyword_start, value, end in clauses
              if _cred_is_placeholder(value)]
    for family, _keyword_start, value, end in clauses:
        if not _cred_is_placeholder(value):
            kinds.append(f"credential value ({family.name})")
            continue
        explained.add(end - len(value))
        if not tail_exempt and not _cred_tail_is_structural(line, end, family, nested):
            kinds.append(f"credential residue after the placeholder ({family.name})")
    if not artifact and any(position not in explained for position in placeholders):
        # CLOSED WORLD on raw captures: the scrub is the only author of the placeholder there, so a
        # placeholder that no clause of this grammar explains is a producer/verifier disagreement --
        # e.g. a pre-W60 'enable password <redacted> 15 X' whose qualifier was taken as the value.
        kinds.append("placeholder outside the credential grammar")
    return kinds


def _raw_capture_credential_findings(text: str) -> list[str]:
    """The credential grammar over a whole raw capture, line by line.

    A banner body, a description/remark/comment line and a syslog record are free text: their
    credential VALUES are still checked, but prose may follow the placeholder there, so the tail
    allowlist is not applied. A banner whose delimiter never closes stops being exempt after
    `_CRED_BANNER_MAX_LINES` lines -- a missing delimiter must not switch the tail check off for the
    rest of the file."""
    kinds: list[str] = []
    banner_delim: str | None = None
    banner_lines = 0
    for line in text.splitlines():
        exempt = False
        if banner_delim is not None:
            exempt = True
            banner_lines += 1
            if banner_delim in line or banner_lines > _CRED_BANNER_MAX_LINES:
                banner_delim = None
        else:
            banner = _CRED_BANNER_RE.match(line)
            if banner:
                exempt = True
                delim = banner.group("delim")
                # '^C' or one punctuation character opens a multi-line body; an alphanumeric first
                # character is a one-line banner (ASA 'banner motd <text>').
                if delim and not delim.isalnum() and delim not in line[banner.end():]:
                    banner_delim, banner_lines = delim, 0
        if not exempt and _CRED_FREE_TEXT_RE.search(line):
            exempt = True
        kinds.extend(_credential_line_findings(line, artifact=False, tail_exempt=exempt))
    return kinds


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

    # Authored prose, generated code and free-text device fields (an interface description that
    # begins with "password reset ...") share these surfaces, so the grammar reads only lines that
    # OPEN like the configuration forms (each family's `artifact` anchors), and checks their VALUE
    # only: the tail allowlist would refuse ordinary prose after a redacted word. The full grammar,
    # tails included, runs on raw captures in `verify_collection_secret_scrub`; the producer's own
    # grammar is what closes the residue class here (docs/w60-redaction-grammar-2026-10-09.md).
    for line in text.splitlines():
        for kind in _credential_line_findings(line, artifact=True, tail_exempt=True):
            _append(leaks, kind, where)
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
