"""SSH session disclosure (W59 PR-1): what each live SSH session actually negotiated, and under which consent.

This module is the ONE owner of:

* the SSH profile vocabulary (``SSH_PROFILES``) and the per-device consent fields;
* the SSH algorithm vocabulary -- every algorithm name the disclosure grades. **SSH SHA-1 algorithm
  literals appear in no other shipped source file**; the collector, the analysis layer and the workbook
  import the names or the grades from here and restate none;
* the observation-only transport mixin (:class:`ObservingTransportMixin`) and its per-connection sink
  (:class:`SessionObservation`);
* the closed sidecar schema ``ssh_session/1`` (``<device dir>/_ssh_session.json``), its writer and its
  validator;
* the negotiation-failure classifier (:func:`classify_failure`) and the library probe
  (:func:`permits_sha1`);
* the snapshot block ``ssh_session_set/1`` (:func:`compute_ssh_sessions`), the per-row status, severity
  and finding, and the two-fact disclosure wording (:func:`disclosure_sentence`).

It imports NO network library (the attestation's ``NETWORK_IMPORTS`` walk covers it): the mixin is
duck-typed and is composed with ``paramiko.Transport`` by the collector, and :func:`classify_failure`
recognises paramiko's exception classes by name.

Why an observer at all (design §4.3): paramiko's ``Transport._parse_newkeys`` sets ``kex_engine``,
``K`` and both KEXINIT copies to ``None`` before ``connect()`` returns, in 4.0.0 and 5.0.0 alike, so
reading the negotiated key exchange "after connect" yields nothing on every established session. The
mixin records what it needs BEFORE delegating to ``super()``, and records only names, sizes and booleans
-- never key material.

Absence is never health: a device without a sealed record is ``not_recorded`` / ``unknown`` and is
rendered ``verify``, never ``modern``.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

# --------------------------------------------------------------------------------------------------------
# Schemas, owner, file name
# --------------------------------------------------------------------------------------------------------
SIDECAR_SCHEMA = "ssh_session/1"
SET_SCHEMA = "ssh_session_set/1"
OWNER = "cisco_toolkit.ssh_session"
#: The per-device sidecar basename. ``capture_integrity.COLLECTION_SIDECAR_BASENAMES`` is the owner tuple
#: of every collection sidecar basename and includes this one.
SIDECAR_FILENAME = "_ssh_session.json"
#: Custody role of the sidecar in the run's raw-evidence records.
CUSTODY_ROLE = "<ssh-session-metadata>"
#: Instance attribute through which the collector binds one connection's sink to one transport instance.
SINK_ATTRIBUTE = "_ssh_session_observation"

# --------------------------------------------------------------------------------------------------------
# Profiles and consent
# --------------------------------------------------------------------------------------------------------
DEFAULT_PROFILE = "default"
LEGACY_SHA1_PROFILE = "legacy-sha1"
SSH_PROFILES: Tuple[str, ...] = (DEFAULT_PROFILE, LEGACY_SHA1_PROFILE)

PLATFORM_SOURCES = ("device_row", "autodetect")

# --------------------------------------------------------------------------------------------------------
# Algorithm vocabulary
# --------------------------------------------------------------------------------------------------------
GRADE_LEGACY = "legacy"      # SHA-1 class (exchange hash or host-key signature) -- a device weakness
GRADE_MODERN = "modern"      # SHA-256 or better


@dataclass(frozen=True)
class KexGrade:
    """One key-exchange method: its exchange-hash size, whether it is a MODP (finite-field DH) group, and
    the fixed group size when the method names one (``None`` for group exchange and non-MODP methods)."""
    grade: str
    hash_bytes: int
    modp: bool
    fixed_bits: Optional[int] = None


#: Every key-exchange name the disclosure grades. RFC 9142 Table 12 grades ``diffie-hellman-group14-sha1``
#: MAY and the other two SHA-1 methods SHOULD NOT; all three are SHA-1 in the exchange hash.
KEX_VOCABULARY: Mapping[str, KexGrade] = MappingProxyType({
    "diffie-hellman-group1-sha1": KexGrade(GRADE_LEGACY, 20, True, 1024),
    "diffie-hellman-group14-sha1": KexGrade(GRADE_LEGACY, 20, True, 2048),
    "diffie-hellman-group-exchange-sha1": KexGrade(GRADE_LEGACY, 20, True, None),
    "diffie-hellman-group14-sha256": KexGrade(GRADE_MODERN, 32, True, 2048),
    "diffie-hellman-group15-sha512": KexGrade(GRADE_MODERN, 64, True, 3072),
    "diffie-hellman-group16-sha512": KexGrade(GRADE_MODERN, 64, True, 4096),
    "diffie-hellman-group17-sha512": KexGrade(GRADE_MODERN, 64, True, 6144),
    "diffie-hellman-group18-sha512": KexGrade(GRADE_MODERN, 64, True, 8192),
    "diffie-hellman-group-exchange-sha256": KexGrade(GRADE_MODERN, 32, True, None),
    "ecdh-sha2-nistp256": KexGrade(GRADE_MODERN, 32, False),
    "ecdh-sha2-nistp384": KexGrade(GRADE_MODERN, 48, False),
    "ecdh-sha2-nistp521": KexGrade(GRADE_MODERN, 64, False),
    "curve25519-sha256": KexGrade(GRADE_MODERN, 32, False),
    "curve25519-sha256@libssh.org": KexGrade(GRADE_MODERN, 32, False),
    "curve448-sha512": KexGrade(GRADE_MODERN, 64, False),
    "sntrup761x25519-sha512": KexGrade(GRADE_MODERN, 64, False),
    "sntrup761x25519-sha512@openssh.com": KexGrade(GRADE_MODERN, 64, False),
    "mlkem768x25519-sha256": KexGrade(GRADE_MODERN, 32, False),
    "mlkem768nistp256-sha256": KexGrade(GRADE_MODERN, 32, False),
    "mlkem1024nistp384-sha384": KexGrade(GRADE_MODERN, 48, False),
})

#: Host-key (server signature) algorithms. ``ssh-rsa`` signs with SHA-1 (RFC 8332 replaces it with
#: ``rsa-sha2-256/512``); ``ssh-dss`` is DSA over SHA-1; ``x509v3-ssh-rsa`` (RFC 6187) signs with SHA-1.
HOST_KEY_VOCABULARY: Mapping[str, str] = MappingProxyType({
    "ssh-rsa": GRADE_LEGACY,
    "ssh-rsa-cert-v01@openssh.com": GRADE_LEGACY,
    "ssh-dss": GRADE_LEGACY,
    "ssh-dss-cert-v01@openssh.com": GRADE_LEGACY,
    "x509v3-ssh-rsa": GRADE_LEGACY,
    "x509v3-ssh-dss": GRADE_LEGACY,
    "rsa-sha2-256": GRADE_MODERN,
    "rsa-sha2-512": GRADE_MODERN,
    "rsa-sha2-256-cert-v01@openssh.com": GRADE_MODERN,
    "rsa-sha2-512-cert-v01@openssh.com": GRADE_MODERN,
    "ecdsa-sha2-nistp256": GRADE_MODERN,
    "ecdsa-sha2-nistp384": GRADE_MODERN,
    "ecdsa-sha2-nistp521": GRADE_MODERN,
    "ecdsa-sha2-nistp256-cert-v01@openssh.com": GRADE_MODERN,
    "ecdsa-sha2-nistp384-cert-v01@openssh.com": GRADE_MODERN,
    "ecdsa-sha2-nistp521-cert-v01@openssh.com": GRADE_MODERN,
    "ssh-ed25519": GRADE_MODERN,
    "ssh-ed25519-cert-v01@openssh.com": GRADE_MODERN,
    "ssh-ed448": GRADE_MODERN,
    "x509v3-rsa2048-sha256": GRADE_MODERN,
    "x509v3-ecdsa-sha2-nistp256": GRADE_MODERN,
    "x509v3-ecdsa-sha2-nistp384": GRADE_MODERN,
    "x509v3-ecdsa-sha2-nistp521": GRADE_MODERN,
    "sk-ssh-ed25519@openssh.com": GRADE_MODERN,
    "sk-ecdsa-sha2-nistp256@openssh.com": GRADE_MODERN,
})

#: MACs whose underlying hash is SHA-1 or MD5. HMAC-SHA-1 does not rest on collision resistance (RFC 6194
#: §3.3), so these are DISCLOSED per session (``legacy_mac_or_cipher``) and raise no finding (§11, decision 5).
SHA1_MACS = frozenset({
    "hmac-sha1", "hmac-sha1-96", "hmac-sha1-etm@openssh.com", "hmac-sha1-96-etm@openssh.com",
})
MD5_MACS = frozenset({
    "hmac-md5", "hmac-md5-96", "hmac-md5-etm@openssh.com", "hmac-md5-96-etm@openssh.com",
})
MODERN_MACS = frozenset({
    "hmac-sha2-256", "hmac-sha2-512", "hmac-sha2-256-etm@openssh.com", "hmac-sha2-512-etm@openssh.com",
    "umac-64@openssh.com", "umac-128@openssh.com", "umac-64-etm@openssh.com", "umac-128-etm@openssh.com",
})
#: CBC-mode and stream ciphers disclosed per session (no finding).
LEGACY_CIPHERS = frozenset({
    "aes128-cbc", "aes192-cbc", "aes256-cbc", "3des-cbc", "blowfish-cbc", "cast128-cbc",
    "rijndael-cbc@lysator.liu.se", "arcfour", "arcfour128", "arcfour256",
})
MODERN_CIPHERS = frozenset({
    "aes128-ctr", "aes192-ctr", "aes256-ctr", "aes128-gcm@openssh.com", "aes256-gcm@openssh.com",
    "chacha20-poly1305@openssh.com", "AEAD_AES_128_GCM", "AEAD_AES_256_GCM",
})

#: Pseudo-algorithms carried in the kex list (RFC 8308 ``ext-info-*``; strict kex ``kex-strict-*``).
#: Ignored when grading. Only the exact names below are ever STORED (a prefix match would let a crafted name such as
#: ``ext-info-<anything>`` carry free text into the record).
PSEUDO_KEX_PREFIXES = ("ext-info-", "kex-strict-")
PSEUDO_KEX_NAMES = frozenset({
    "ext-info-s", "ext-info-c", "ext-info-in-auth@openssh.com",
    "kex-strict-s-v00@openssh.com", "kex-strict-c-v00@openssh.com",
})

#: The SHA-1-class names the key-exchange hash and the host-key signature can carry -- the boundary of the
#: default path ("no SHA-1 in the key-exchange hash or the host-key signature"). MACs are outside it.
SHA1_KEX_NAMES = frozenset(n for n, g in KEX_VOCABULARY.items() if g.hash_bytes == 20)
SHA1_HOST_KEY_NAMES = frozenset(n for n, g in HOST_KEY_VOCABULARY.items() if g == GRADE_LEGACY)
SHA1_BOUNDARY_NAMES = SHA1_KEX_NAMES | SHA1_HOST_KEY_NAMES
#: Every SSH SHA-1 algorithm literal (the T10 identifier-scope scan's denominator).
SSH_SHA1_ALGORITHM_NAMES = SHA1_BOUNDARY_NAMES | SHA1_MACS

#: W59 PR-1 review (P3-e): every algorithm name a session record may STORE -- the graded vocabularies above plus the
#: exact pseudo-algorithm names. A name the device offers outside them (a vendor extension, or a crafted name that
#: carries an organisation or host name) is COUNTED in ``dropped_names`` and never stored, so the record holds no
#: device-controlled free text. ``validate_record`` enforces it, which is what lets the redaction verifiers report a
#: valid record as covered by schema.
RECORDABLE_ALGORITHM_NAMES = (frozenset(KEX_VOCABULARY) | frozenset(HOST_KEY_VOCABULARY) | SHA1_MACS | MD5_MACS
                              | MODERN_MACS | LEGACY_CIPHERS | MODERN_CIPHERS | PSEUDO_KEX_NAMES)

#: The names W59 PR-2's ``legacy-sha1`` profile appends after every stock algorithm of the same kind (tier 1
#: only: no 1024-bit group, no DSA). Defined here so the vocabulary has one owner; ``cisco_toolkit.legacy_ssh``
#: (PR-2) is the only other module that may import them. A refusal whose offered names fall OUTSIDE this
#: tier is not collectable by any profile, and the disclosure says so rather than pointing at the opt-in.
LEGACY_SHA1_TIER_KEX: Tuple[str, ...] = ("diffie-hellman-group14-sha1", "diffie-hellman-group-exchange-sha1")
LEGACY_SHA1_TIER_HOST_KEYS: Tuple[str, ...] = ("ssh-rsa", "ssh-rsa-cert-v01@openssh.com")

#: Exchange-hash size (bytes) -> hash family. ``len(Transport.session_id)`` is the hook-free witness.
HASH_FAMILY_BY_BYTES: Mapping[int, str] = MappingProxyType({20: "sha1", 32: "sha256", 48: "sha384", 64: "sha512"})
DH_FLOOR_BITS = 2048

# --------------------------------------------------------------------------------------------------------
# Status / outcome / finding vocabularies (design §6.2)
# --------------------------------------------------------------------------------------------------------
OUTCOMES = ("pending", "established", "auth_failed", "negotiation_refused", "connect_failed")
REFUSAL_CLASSES = ("refused_weak_dh", "refused_legacy_only", "refused_unsupported_modern",
                   "refused_cipher_mac", "unclassified")
REFUSAL_CATEGORIES = ("kex", "host_key", "cipher", "mac", "compression", "version", "unknown")
REFUSAL_DETAILS = ("no_common_kex", "no_common_host_key", "no_common_cipher", "no_common_mac",
                   "weak_group_refused", "incompatible_peer")

STATUS_LEGACY_UNRECORDED = "legacy_unrecorded"
STATUS_NOT_RECORDED = "not_recorded"
STATUS_UNKNOWN = "unknown"
STATUS_WEAK_DH = "weak_dh"
STATUS_LEGACY_SHA1 = "legacy_sha1"
STATUS_MODERN = "modern"
STATUSES: Tuple[str, ...] = (
    STATUS_LEGACY_UNRECORDED, STATUS_NOT_RECORDED, STATUS_UNKNOWN, STATUS_WEAK_DH, STATUS_LEGACY_SHA1,
    STATUS_MODERN, "refused_weak_dh", "refused_legacy_only", "refused_unsupported_modern",
    "refused_cipher_mac",
)
FINDING_EXPOSED = "exposed"
FINDING_VERIFY = "verify"
FINDING_CLOSED = "closed"
#: status -> (finding, severity). Severity follows §11 decision 3: Medium for SHA-1, High below 2048 bits.
STATUS_FINDING: Mapping[str, Tuple[str, Optional[str]]] = MappingProxyType({
    STATUS_LEGACY_UNRECORDED: (FINDING_EXPOSED, "Medium"),
    STATUS_NOT_RECORDED: (FINDING_VERIFY, None),
    STATUS_UNKNOWN: (FINDING_VERIFY, None),
    STATUS_WEAK_DH: (FINDING_EXPOSED, "High"),
    STATUS_LEGACY_SHA1: (FINDING_EXPOSED, "Medium"),
    STATUS_MODERN: (FINDING_CLOSED, None),
    "refused_weak_dh": (FINDING_EXPOSED, "High"),
    "refused_legacy_only": (FINDING_EXPOSED, "Medium"),
    "refused_unsupported_modern": (FINDING_VERIFY, None),
    "refused_cipher_mac": (FINDING_VERIFY, None),
})

# --------------------------------------------------------------------------------------------------------
# Software-risk surface wording (analyze._SWRISK_SURFACE_KB reads these; the kind is owned here)
# --------------------------------------------------------------------------------------------------------
SURFACE_KIND = "ssh-legacy-transport"
SURFACE_LABEL = "Legacy SSH transport (SHA-1 key exchange or host-key signature, or a DH group below 2048 bits)"
SURFACE_WHY = (
    "The collector's own SSH session to this device used, or could only use, a SHA-1 key exchange or a "
    "SHA-1 host-key signature, or a Diffie-Hellman group below 2048 bits. RFC 9142 says the SHA-1 key "
    "exchanges should be deprecated and phased out; OpenSSH 8.8 disabled SHA-1 RSA signatures because a "
    "SHA-1 chosen-prefix collision costs under USD 50K; and a group below 2048 bits exposes the session, "
    "including the login password, to a precomputation-capable adversary. The finding is about the device's "
    "management plane, which every migration tool and operator will also use.")
SURFACE_RECOMMENDATION = (
    "Enable SHA-2 key exchange (diffie-hellman-group14-sha256, ECDH or curve25519) and RSA SHA-2 host-key "
    "signatures (rsa-sha2-256 / rsa-sha2-512, RFC 8332) on the device's SSH server, following the platform's "
    "SSHv2 configuration guide for its release. Where the release cannot negotiate SHA-2 SSH at all, plan a "
    "management-plane modernization or replacement before the migration. Below 2048 bits: treat the "
    "collection account's password as exposed and rotate it.")
#: W59 PR-1 review (P3-h): how every collection-integrity and software-risk summary names the session-evidenced
#: findings, apart from the configuration-screened advisory surfaces they share ``software_risk.findings`` with.
SURFACE_COUNT_NOUN = (f"legacy SSH transport finding(s) ({SURFACE_KIND}; session-evidenced, needs no "
                      "running-config)")
SURFACE_NO_PSIRT = ("Legacy SSH transport is the collector's own negotiated SSH session, not a release advisory: it "
                    "has no PSIRT step. Enable SHA-2 SSH on the device; where a Diffie-Hellman group below 2048 bits "
                    "was negotiated, rotate the collection account's password.")


def partition_software_findings(findings: Any) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """``(configuration findings, session-evidenced findings)`` of a ``software_risk.findings`` list: the second holds
    every :data:`SURFACE_KIND` row, the first every other object row, each in its stored order. A summary that counts
    the two together calls the collector's own SSH session an advisory surface to validate with the PSIRT checker.
    Total on hostile input (a non-list is empty, a non-object row is skipped)."""
    rows = [f for f in findings if isinstance(f, dict)] if isinstance(findings, list) else []
    return ([f for f in rows if f.get("kind") != SURFACE_KIND], [f for f in rows if f.get("kind") == SURFACE_KIND])

# --------------------------------------------------------------------------------------------------------
# Name grammar (RFC 4251 §6) and privacy screens
# --------------------------------------------------------------------------------------------------------
MAX_NAME_LENGTH = 64
MAX_LIST_LENGTH = 64
#: Printable US-ASCII without whitespace or comma (RFC 4251 §6). ``:`` is also refused: no algorithm name
#: in the vocabulary carries one, and refusing it keeps IPv6 literals out of the record by construction.
_NAME_RE = re.compile(r"^[\x21-\x2b\x2d-\x39\x3b-\x7e]{1,64}$")
_IPV4_IN_TEXT = re.compile(r"(?<![0-9])(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?![0-9])")
_MAC_IN_TEXT = re.compile(r"(?i)(?<![0-9a-f])(?:[0-9a-f]{4}\.){2}[0-9a-f]{4}(?![0-9a-f])")
_VERSION_RE = re.compile(r"^[0-9]{1,4}\.[0-9]{1,4}(?:\.[0-9]{1,4})?(?:(?:a|b|rc)[0-9]{1,4})?"
                         r"(?:\.post[0-9]{1,4})?(?:\.dev[0-9]{1,4})?$")
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")

#: W59 PR-1 review (P3-e): the server banner's ``SSH-protoversion-softwareversion`` is stored only when the software
#: version is a known SSH implementation's product token followed by a numeric version (``SSH-2.0-Cisco-1.25``,
#: ``SSH-2.0-OpenSSH_9.6p1``). Any other softwareversion -- a custom banner, which a device owner can set to an
#: organisation or host name -- is counted in ``dropped_names`` and stored as null.
SERVER_SOFTWARE_VENDORS: Tuple[str, ...] = (
    "Cisco", "OpenSSH", "dropbear", "libssh", "AsyncSSH", "paramiko", "RomSShell", "Comware", "HUAWEI", "ROSSSH")
SERVER_SOFTWARE_RE = re.compile(
    r"^SSH-(?:2\.0|1\.99)-(?:" + "|".join(re.escape(v) for v in SERVER_SOFTWARE_VENDORS) + r")[-_]"
    r"[0-9]{1,6}(?:\.[0-9]{1,6}){0,3}(?:p[0-9]{1,3})?$")


def conforming_name(value: Any) -> Optional[str]:
    """``value`` when it is a storable SSH name (RFC 4251 §6 grammar, no IP/MAC-shaped text), else None."""
    if not isinstance(value, str) or not _NAME_RE.match(value):
        return None
    if _IPV4_IN_TEXT.search(value) or _MAC_IN_TEXT.search(value):
        return None
    return value


def recordable_name(value: Any) -> Optional[str]:
    """``value`` when a session record may store it: a grammar-conforming name of the recordable vocabulary."""
    name = conforming_name(value)
    return name if name is not None and name in RECORDABLE_ALGORITHM_NAMES else None


def recordable_names(values: Any) -> Tuple[List[str], int]:
    """(stored names, dropped count) for a list about to enter a record: only vocabulary names are kept, in order;
    every other entry is counted and never stored."""
    if isinstance(values, (str, bytes)) or values is None:
        return [], 0
    try:
        items = list(values)
    except TypeError:
        return [], 1
    kept = [n for n in items if recordable_name(n) is not None][:MAX_LIST_LENGTH]
    return kept, len(items) - len(kept)


def server_software_token(value: Any) -> Optional[str]:
    """``value`` when it is a storable server software token (the vendor-banner grammar), else None."""
    if not isinstance(value, str) or not SERVER_SOFTWARE_RE.match(value):
        return None
    return conforming_name(value)


def conforming_version(value: Any) -> Optional[str]:
    """A library version string (``5.0.0``, ``4.8.0``), or None. Never four dotted numbers."""
    return value if isinstance(value, str) and _VERSION_RE.match(value) else None


def conforming_identifier(value: Any) -> Optional[str]:
    return value if isinstance(value, str) and _IDENTIFIER_RE.match(value) else None


def _sanitize_names(values: Any) -> Tuple[List[str], int]:
    """(stored names, dropped count). At most ``MAX_LIST_LENGTH`` names; a non-conforming name is dropped
    and counted, never stored."""
    out: List[str] = []
    dropped = 0
    if isinstance(values, (str, bytes)) or values is None:
        return out, 0
    try:
        items = list(values)
    except TypeError:
        return out, 1
    for item in items:
        name = conforming_name(item)
        if name is None or len(out) >= MAX_LIST_LENGTH:
            dropped += 1
            continue
        out.append(name)
    return out, dropped


def server_software_from_banner(banner: Any) -> Tuple[Optional[str], int]:
    """``SSH-protoversion-softwareversion`` only: the free-text comment after the first space
    (RFC 4253 §4.2) is dropped, so it cannot carry identifying text, and the softwareversion is kept only when it
    matches the vendor-banner grammar (:data:`SERVER_SOFTWARE_RE`) -- a custom banner is dropped and counted.
    Returns (value, dropped count)."""
    if not isinstance(banner, str) or not banner:
        return None, 0
    head = banner.strip().split(" ", 1)[0].split("\t", 1)[0]
    value = server_software_token(head)
    return (value, 0) if value is not None else (None, 1)


def is_pseudo_kex(name: str) -> bool:
    return isinstance(name, str) and name.startswith(PSEUDO_KEX_PREFIXES)


def kex_grade(name: Any) -> Optional[KexGrade]:
    return KEX_VOCABULARY.get(name) if isinstance(name, str) else None


def host_key_grade(name: Any) -> Optional[str]:
    return HOST_KEY_VOCABULARY.get(name) if isinstance(name, str) else None


# --------------------------------------------------------------------------------------------------------
# Library probe
# --------------------------------------------------------------------------------------------------------
def _names_in(container: Any) -> List[str]:
    if isinstance(container, Mapping):
        return [k for k in container if isinstance(k, str)]
    if isinstance(container, (tuple, list, frozenset, set)):
        return [k for k in container if isinstance(k, str)]
    return []


def permits_sha1(transport_cls: Any, rsakey_cls: Any = None) -> bool:
    """True when this SSH library's STOCK tables can negotiate SHA-1 in the key-exchange hash or the host-key
    signature: ``Transport._preferred_kex`` / ``_kex_info`` / ``_preferred_keys`` / ``_key_info`` and
    ``RSAKey.HASHES``. True on paramiko 4.0.0 (which ships ``diffie-hellman-group14-sha1`` and ``ssh-rsa``),
    false on paramiko 5.0.0. Recorded per session as ``library.default_permits_sha1``; a manifest floor does
    not bind an environment that already holds paramiko 4, so this reads the live classes, never a version."""
    names: set = set()
    for attr in ("_preferred_kex", "_preferred_keys", "_kex_info", "_key_info"):
        names.update(_names_in(getattr(transport_cls, attr, None)))
    if rsakey_cls is not None:
        names.update(_names_in(getattr(rsakey_cls, "HASHES", None)))
    return bool(names & SHA1_BOUNDARY_NAMES)


def library_block(*, paramiko_version: Any, netmiko_version: Any, transport_class: Any,
                  default_permits_sha1: Any) -> Dict[str, Any]:
    return {
        "paramiko": conforming_version(paramiko_version),
        "netmiko": conforming_version(netmiko_version),
        "transport_class": conforming_identifier(transport_class),
        "default_permits_sha1": default_permits_sha1 if isinstance(default_permits_sha1, bool) else None,
    }


# --------------------------------------------------------------------------------------------------------
# Consent (PR-1: recorded; the run-level flag arrives with W59 PR-2)
# --------------------------------------------------------------------------------------------------------
def requested_profile(row: Any) -> str:
    """The profile a devices.json row requests. Only an exact member of ``SSH_PROFILES`` is honoured; anything
    else reads as ``default`` (the strict load-time validation is W59 PR-2's)."""
    value = row.get("ssh_profile") if isinstance(row, Mapping) else None
    return value if isinstance(value, str) and value in SSH_PROFILES else DEFAULT_PROFILE


def consent_for(row: Any, run_flag: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """The per-device consent fields. The effective profile is non-default only when BOTH the row requests it
    and the run flag names the device (two-level consent, §5)."""
    requested = requested_profile(row)
    flag_profile = None
    named = False
    if isinstance(run_flag, Mapping):
        fp = run_flag.get("profile")
        flag_profile = fp if isinstance(fp, str) and fp in SSH_PROFILES and fp != DEFAULT_PROFILE else None
        hosts = run_flag.get("hosts_named") or ()
        if flag_profile and isinstance(row, Mapping):
            idents = {str(row.get("hostname") or ""), str(row.get("ip") or "")} - {""}
            named = any(isinstance(h, str) and h in idents for h in hosts)
    effective = requested if (requested != DEFAULT_PROFILE and named and flag_profile == requested) \
        else DEFAULT_PROFILE
    return {"device_profile": requested, "run_flag_profile": flag_profile,
            "named_on_run_flag": bool(named), "effective_profile": effective}


_CONSENT_FIELDS = ("run_flag", "devices_requesting_legacy", "devices_eligible", "named_not_requested",
                   "requested_not_named", "devices_negotiated_sha1", "record_failures")


def offline_consent_block() -> Dict[str, Any]:
    """The manifest/snapshot consent block of a ``--no-collect`` run: a re-analysis never states a consent it
    did not observe, so every consent field is ``null``."""
    block: Dict[str, Any] = {"mode": "offline"}
    block.update({k: None for k in _CONSENT_FIELDS})
    return block


def live_consent_block(devices: Iterable[Mapping[str, Any]],
                       run_flag: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """The live run's consent block, built BEFORE the first connection. Hosts are keyed by ``hostname``.

    ``devices_negotiated_sha1`` is ``None`` here: nothing has been negotiated yet, and an empty list would state
    "no device negotiated SHA-1" before any session ran. :func:`compute_ssh_sessions` fills it from the sealed
    records; if that phase fails, the run manifest keeps ``None`` (not computed), never ``[]``."""
    requesting, eligible, named_not_req, req_not_named = [], [], [], []
    for row in devices or ():
        if not isinstance(row, Mapping):
            continue
        host = str(row.get("hostname") or "")
        c = consent_for(row, run_flag)
        if c["device_profile"] != DEFAULT_PROFILE:
            requesting.append(host)
            if c["effective_profile"] != DEFAULT_PROFILE:
                eligible.append(host)
            else:
                req_not_named.append(host)
        elif c["named_on_run_flag"]:
            named_not_req.append(host)
    flag = None
    if isinstance(run_flag, Mapping):
        hosts = [h for h in (run_flag.get("hosts_named") or ()) if isinstance(h, str)]
        flag = {"profile": run_flag.get("profile"), "hosts_named": sorted(hosts)}
    return {"mode": "live", "run_flag": flag or {"profile": None, "hosts_named": []},
            "devices_requesting_legacy": sorted(requesting), "devices_eligible": sorted(eligible),
            "named_not_requested": sorted(named_not_req), "requested_not_named": sorted(req_not_named),
            "devices_negotiated_sha1": None, "record_failures": []}


def consent_summary_lines(block: Mapping[str, Any]) -> List[str]:
    """Human lines printed before the first connection of a live run (design §5: printed and recorded)."""
    flag = block.get("run_flag") or {}
    lines = [
        "SSH transport consent: run flag "
        + (f"{flag.get('profile')} for {', '.join(flag.get('hosts_named') or []) or '(none)'}"
           if flag.get("profile") else "not given (this build has no legacy-SSH opt-in)"),
        "  devices eligible for a legacy profile: " + (", ".join(block.get("devices_eligible") or []) or "none"),
    ]
    if block.get("requested_not_named"):
        lines.append("  row requests legacy-sha1 but the run did not name it (collected on the default path): "
                     + ", ".join(block["requested_not_named"]))
    if block.get("named_not_requested"):
        lines.append("  named on the run flag but not requested by its row (default path): "
                     + ", ".join(block["named_not_requested"]))
    return lines


# --------------------------------------------------------------------------------------------------------
# The observation sink and the observation-only transport mixin (design §4.3)
# --------------------------------------------------------------------------------------------------------
class SessionObservation:
    """What ONE connection attempt's transport observed. Written only from that transport's own thread, through
    the instance-bound attribute ``SINK_ATTRIBUTE``; read by the caller after ``start_client`` returns or the
    attempt fails. Holds names, sizes and booleans -- never key material."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.kexinit_seen = False
        self.newkeys_seen = False
        self.server: Optional[Dict[str, List[str]]] = None
        self.client: Optional[Dict[str, List[str]]] = None
        self.agreed_kex: Optional[str] = None
        self.negotiated: Optional[Dict[str, Any]] = None
        self.engine_name_agrees: Optional[bool] = None
        self.group_size_agrees: Optional[bool] = None
        self.dropped = 0
        self.errors = 0

    # -- writers (transport thread) ---------------------------------------------------------------------
    def record_kexinit(self, parsed: Mapping[str, Any], transport: Any) -> None:
        server: Dict[str, List[str]] = {}
        dropped = 0
        for key, src in (("kex", "kex_algo_list"), ("host_key", "server_key_algo_list"),
                         ("cipher_c2s", "client_encrypt_algo_list"), ("cipher_s2c", "server_encrypt_algo_list"),
                         ("mac_c2s", "client_mac_algo_list"), ("mac_s2c", "server_mac_algo_list")):
            names, d = _sanitize_names(parsed.get(src))
            server[key] = names
            dropped += d
        client: Dict[str, List[str]] = {}
        for key, attr in (("kex", "preferred_kex"), ("host_key", "preferred_keys"),
                          ("cipher", "preferred_ciphers"), ("mac", "preferred_macs")):
            try:
                raw = getattr(transport, attr)
            except Exception:                                   # noqa: BLE001 - observation must never break
                raw = ()
                self.errors += 1
            names, d = _sanitize_names(raw)
            client[key] = names
            dropped += d
        with self._lock:
            self.server, self.client = server, client
            self.kexinit_seen = True
            self.dropped += dropped

    def record_agreed(self, transport: Any) -> None:
        """After paramiko accepted the KEXINIT: the agreed method is the first CLIENT name the server offered
        (RFC 4253 §7.1 client rule). Cross-checked against the engine's own ``name`` when it has one."""
        with self._lock:
            server, client = self.server, self.client
        if not server or not client:
            return
        offered = {n for n in server.get("kex", []) if not is_pseudo_kex(n)}
        agreed = next((n for n in client.get("kex", []) if n in offered), None)
        eng_name = getattr(getattr(transport, "kex_engine", None), "name", None)
        agrees = None if not isinstance(eng_name, str) else (eng_name == agreed)
        with self._lock:
            self.agreed_kex = agreed
            self.engine_name_agrees = agrees

    def record_newkeys(self, transport: Any) -> None:
        kex = self.agreed_kex
        grade = kex_grade(kex)
        bits = None
        group_agrees = None
        if grade is not None and grade.modp:
            eng = getattr(transport, "kex_engine", None)
            p = getattr(eng, "p", None)                 # group exchange: the server's prime
            if not _plain_int(p):
                p = getattr(eng, "P", None)             # fixed group: the class constant
            if _plain_int(p) and p > 1:
                bits = int(p).bit_length()
                if grade.fixed_bits is not None:
                    group_agrees = bits == grade.fixed_bits
        sid = getattr(transport, "session_id", None)
        hash_bytes = len(sid) if isinstance(sid, (bytes, bytearray)) else None
        server_mode = bool(getattr(transport, "server_mode", False))
        local_c, remote_c = getattr(transport, "local_cipher", None), getattr(transport, "remote_cipher", None)
        local_m, remote_m = getattr(transport, "local_mac", None), getattr(transport, "remote_mac", None)
        c2s_cipher, s2c_cipher = (remote_c, local_c) if server_mode else (local_c, remote_c)
        c2s_mac, s2c_mac = (remote_m, local_m) if server_mode else (local_m, remote_m)
        software, sw_dropped = server_software_from_banner(getattr(transport, "remote_version", None))
        dropped = sw_dropped
        fields: Dict[str, Any] = {}
        for key, value in (("kex", kex), ("host_key_algorithm", getattr(transport, "host_key_type", None)),
                           ("cipher_c2s", c2s_cipher), ("cipher_s2c", s2c_cipher),
                           ("mac_c2s", c2s_mac), ("mac_s2c", s2c_mac)):
            name = conforming_name(value)
            if value not in (None, "") and name is None:
                dropped += 1
            fields[key] = name
        negotiated = {
            "kex": fields["kex"], "kex_hash_bytes": hash_bytes, "dh_group_bits": bits,
            "host_key_algorithm": fields["host_key_algorithm"],
            "cipher_c2s": fields["cipher_c2s"], "cipher_s2c": fields["cipher_s2c"],
            "mac_c2s": fields["mac_c2s"], "mac_s2c": fields["mac_s2c"],
            "strict_kex": bool(getattr(transport, "agreed_on_strict_kex", False)),
            "server_software": software,
        }
        with self._lock:
            self.negotiated = negotiated
            self.group_size_agrees = group_agrees
            self.newkeys_seen = True
            self.dropped += dropped

    def note_error(self) -> None:
        with self._lock:
            self.errors += 1

    # -- readers (caller thread) -------------------------------------------------------------------------
    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "kexinit": self.kexinit_seen, "newkeys": self.newkeys_seen,
                "server": {k: list(v) for k, v in self.server.items()} if self.server else None,
                "client": {k: list(v) for k, v in self.client.items()} if self.client else None,
                "negotiated": dict(self.negotiated) if self.negotiated else None,
                "engine_name_agrees": self.engine_name_agrees,
                "group_size_agrees": self.group_size_agrees,
                "dropped": self.dropped, "errors": self.errors,
            }


def _plain_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def bind_observation(transport: Any, observation: SessionObservation) -> Any:
    """Bind one connection's sink to ONE transport instance (never the class, never a thread-local)."""
    setattr(transport, SINK_ATTRIBUTE, observation)
    return transport


class ObservingTransportMixin:
    """Observation-only ``paramiko.Transport`` mixin: defines NO algorithm table and overrides exactly two
    methods, each of which records and then calls ``super()``. Composed with ``paramiko.Transport`` by the
    collector (``ObservedTransport``), so the negotiation is byte-for-byte what stock paramiko does.

    * ``_parse_kex_init`` -- before ``super()``, parse a COPY of the server's KEXINIT with paramiko's own
      pure parser and record both sides' lists; if ``super()`` raises ``IncompatiblePeer`` the lists are
      already in the sink, so the refusal is classified from evidence (§4.4).
    * ``_parse_newkeys`` -- before ``super()`` frees the key-exchange engine, record the negotiated names,
      the MODP group size and ``len(session_id)``; first key exchange only.

    Both run in paramiko's transport thread and write only to the sink bound to their own instance."""

    def _parse_kex_init(self, m):  # noqa: D401 - paramiko protocol hook
        obs = getattr(self, SINK_ATTRIBUTE, None)
        first = not getattr(self, "initial_kex_done", False)
        if isinstance(obs, SessionObservation) and first:
            try:
                parsed = self._really_parse_kex_init(type(m)(m.asbytes()))
                obs.record_kexinit(parsed, self)
            except Exception:                                   # noqa: BLE001 - never break the handshake
                obs.note_error()
        result = super()._parse_kex_init(m)
        if isinstance(obs, SessionObservation) and first:
            try:
                obs.record_agreed(self)
            except Exception:                                   # noqa: BLE001
                obs.note_error()
        return result

    def _parse_newkeys(self, m):  # noqa: D401 - paramiko protocol hook
        obs = getattr(self, SINK_ATTRIBUTE, None)
        if isinstance(obs, SessionObservation) and not getattr(self, "initial_kex_done", False):
            try:
                obs.record_newkeys(self)
            except Exception:                                   # noqa: BLE001
                obs.note_error()
        return super()._parse_newkeys(m)


# --------------------------------------------------------------------------------------------------------
# Failure classification (design §4.4): deterministic refusals are never retried
# --------------------------------------------------------------------------------------------------------
class SessionRecordError(RuntimeError):
    """The established-session record could not be written after authentication. Deliberately NOT an
    ``SSHException`` and NOT an ``OSError``: netmiko converts both into a retried timeout, and a device whose
    record cannot be written must be neither collected nor retried."""


_MAX_CHAIN = 16


def exception_chain(exc: BaseException) -> List[BaseException]:
    """``exc`` and its ``__cause__`` / ``__context__`` ancestors, bounded and cycle-safe."""
    out: List[BaseException] = []
    seen = set()
    stack = [exc]
    while stack and len(out) < _MAX_CHAIN:
        e = stack.pop(0)
        if e is None or id(e) in seen:
            continue
        seen.add(id(e))
        out.append(e)
        stack.extend([getattr(e, "__cause__", None), getattr(e, "__context__", None)])
    return out


def _is_named(exc: BaseException, name: str) -> bool:
    return any(c.__name__ == name for c in type(exc).__mro__)


def _names(container: Any, key: str) -> List[str]:
    values = container.get(key) if isinstance(container, Mapping) else None
    return [v for v in values if isinstance(v, str)] if isinstance(values, (list, tuple)) else []


def empty_categories(server: Any, client: Any) -> List[str]:
    """EVERY category with no common algorithm, in paramiko's own order: kex, host key, cipher, MAC (a cipher or MAC
    category is empty when either direction is). Pseudo-algorithms never make a kex category common."""
    out: List[str] = []
    skex = [n for n in _names(server, "kex") if not is_pseudo_kex(n)]
    if not set(skex) & set(_names(client, "kex")):
        out.append("kex")
    if not set(_names(server, "host_key")) & set(_names(client, "host_key")):
        out.append("host_key")
    for cat in ("cipher", "mac"):
        mine = set(_names(client, cat))
        if not (set(_names(server, f"{cat}_c2s")) & mine) or not (set(_names(server, f"{cat}_s2c")) & mine):
            out.append(cat)
    return out


def _first_empty_category(server: Mapping[str, List[str]], client: Mapping[str, List[str]]) -> Optional[str]:
    """The first category with no common algorithm (paramiko's order): the category paramiko itself refuses on."""
    cats = empty_categories(server, client)
    return cats[0] if cats else None


def legacy_tier_closes(server: Any, client: Any) -> bool:
    """True when the ``legacy-sha1`` tier (:data:`LEGACY_SHA1_TIER_KEX` / :data:`LEGACY_SHA1_TIER_HOST_KEYS`), appended
    to the client's own lists, leaves NO category empty -- i.e. the opt-in would let this device negotiate. A refusal
    that also lacks a common cipher or MAC, or whose other SHA-1-class category offers names outside the tier (DSA),
    is not closed by it, so its advice must not point at the opt-in (design section 4.4)."""
    widened = {k: _names(client, k) for k in _CLIENT_KEYS}
    widened["kex"] = widened["kex"] + [n for n in LEGACY_SHA1_TIER_KEX if n not in widened["kex"]]
    widened["host_key"] = widened["host_key"] + [n for n in LEGACY_SHA1_TIER_HOST_KEYS if n not in widened["host_key"]]
    return not empty_categories(server, widened)


def _kex_is_modern(name: str) -> bool:
    grade = kex_grade(name)
    return grade is not None and grade.grade == GRADE_MODERN


def _grade_kex_refusal(offered: Sequence[str]) -> Tuple[str, Optional[int]]:
    names = [n for n in offered if not is_pseudo_kex(n)]
    grades = [kex_grade(n) for n in names]
    if names and all(g is not None and g.modp and g.fixed_bits is not None and g.fixed_bits < DH_FLOOR_BITS
                     for g in grades):
        return "refused_weak_dh", max(g.fixed_bits for g in grades if g is not None)
    if any(g is not None and g.grade == GRADE_MODERN for g in grades):
        return "refused_unsupported_modern", None
    if not names or any(g is None for g in grades):
        return "unclassified", None
    return "refused_legacy_only", None


def _grade_host_key_refusal(offered: Sequence[str]) -> str:
    grades = [host_key_grade(n) for n in offered]
    if any(g == GRADE_MODERN for g in grades):
        return "refused_unsupported_modern"
    if not offered or any(g is None for g in grades):
        return "unclassified"
    return "refused_legacy_only"


def _category_from_message(text: str) -> str:
    t = (text or "").lower()
    for needle, cat in (("kex", "kex"), ("host key", "host_key"), ("cipher", "cipher"), ("mac", "mac"),
                        ("compression", "compression"), ("version", "version")):
        if needle in t:
            return cat
    return "unknown"


#: paramiko's deterministic group-exchange refusal (``kex_gex._parse_kexdh_gex_group``, 4.0.0 and 5.0.0): the
#: server's GEX prime is outside paramiko's 1024-8192-bit window. It is raised as a plain ``SSHException`` (netmiko
#: then wraps it in a timeout), and the same server answers the same way on every attempt.
_GEX_OUT_OF_RANGE_RE = re.compile(r"gex p \(don't ask\) is out of range \(([0-9]{1,6}) bits\)")


def _gex_out_of_range_bits(chain: Sequence[BaseException]) -> Optional[int]:
    for e in chain:
        if not _is_named(e, "SSHException"):
            continue
        try:
            text = str(e)
        except Exception:                                       # noqa: BLE001 - a hostile __str__ is no evidence
            continue
        m = _GEX_OUT_OF_RANGE_RE.search(text)
        if m:
            return int(m.group(1))
    return None


def _list_evidence_usable(snap: Mapping[str, Any]) -> bool:
    """The recorded KEXINIT lists may decide a refusal only when the observation is complete: both sides' lists
    recorded, every client list non-empty (an empty one would read as "no common algorithm"), no observation error,
    and no server name dropped or truncated (the dropped name could have been the common one)."""
    server, client = snap.get("server"), snap.get("client")
    if not server or not client:
        return False
    if snap.get("errors") != 0 or snap.get("dropped") != 0:
        return False
    return all(isinstance(client.get(k), list) and client.get(k) for k in _CLIENT_KEYS)


def classify_failure(exc: BaseException, observation: Optional[SessionObservation]) -> Optional[Dict[str, Any]]:
    """Classify a connection failure as a NEGOTIATION REFUSAL (returned dict; never retried) or ``None`` (an
    ordinary connection failure: the existing same-profile retry applies).

    Evidence first: when the sink holds the server's KEXINIT lists AND the observation is complete
    (:func:`_list_evidence_usable`: no observation error, no dropped server name, every client list non-empty), the
    first category with no common algorithm decides, whatever exception surfaced (netmiko 4.8 turns every
    ``SSHException`` into ``NetmikoTimeoutException``; a server that sends KEXINIT and then DISCONNECT surfaces as
    ``EOFError``). Otherwise the exception chain: ``WeakGroupRefused`` or paramiko's deterministic GEX out-of-range
    ``SSHException`` below 2048 bits -> ``refused_weak_dh``; that GEX refusal above the window or
    ``IncompatiblePeer`` -> ``unclassified``. A disconnect before any server KEXINIT carries no evidence and
    returns ``None``."""
    chain = exception_chain(exc)
    weak = next((e for e in chain if _is_named(e, "WeakGroupRefused")), None)
    if weak is not None:
        bits = getattr(weak, "offered_bits", None)
        return _refusal("kex", "refused_weak_dh", "weak_group_refused",
                        bits if _plain_int(bits) and 0 < bits <= 65536 else None, [])
    gex_bits = _gex_out_of_range_bits(chain)
    if gex_bits is not None:
        stored_bits = gex_bits if 0 < gex_bits <= 65536 else None
        if gex_bits < DH_FLOOR_BITS:
            return _refusal("kex", "refused_weak_dh", "weak_group_refused", stored_bits, [])
        return _refusal("kex", "unclassified", "incompatible_peer", stored_bits, [])
    snap = observation.snapshot() if isinstance(observation, SessionObservation) else {}
    server, client = snap.get("server"), snap.get("client")
    if _list_evidence_usable(snap):
        cat = _first_empty_category(server, client)
        if cat == "kex":
            offered = [n for n in server.get("kex", []) if not is_pseudo_kex(n)]
            cls, bits = _grade_kex_refusal(offered)
            if cls == "refused_unsupported_modern":
                offered = [n for n in offered if _kex_is_modern(n) and n not in client.get("kex", [])]
            return _refusal("kex", cls, "no_common_kex", bits, offered)
        if cat == "host_key":
            offered = list(server.get("host_key", []))
            cls = _grade_host_key_refusal(offered)
            names = offered if cls != "refused_unsupported_modern" else \
                [n for n in offered if host_key_grade(n) == GRADE_MODERN and n not in client.get("host_key", [])]
            return _refusal("host_key", cls, "no_common_host_key", None, names)
        if cat in ("cipher", "mac"):
            mine = set(client.get(cat, []))
            names = sorted({n for key in (f"{cat}_c2s", f"{cat}_s2c") for n in server.get(key, [])} - mine)
            return _refusal(cat, "refused_cipher_mac", f"no_common_{cat}", None, names)
    incompatible = next((e for e in chain if _is_named(e, "IncompatiblePeer")), None)
    if incompatible is not None:
        return _refusal(_category_from_message(str(incompatible)), "unclassified", "incompatible_peer", None, [])
    return None


def _refusal(category: str, classification: str, detail: str, bits: Optional[int],
             names: Sequence[str]) -> Dict[str, Any]:
    stored, _dropped = _sanitize_names(names)
    return {"category": category, "classification": classification, "detail": detail,
            "offered_group_bits": bits, "names": stored}


def refusal_message(refusal: Mapping[str, Any], consent: Mapping[str, Any],
                    observation: Optional[Mapping[str, Any]] = None) -> str:
    """The actionable log line for a refusal (§4.4): the device row's profile, whether the run named it, and
    what would be needed. ``observation`` is the attempt's sink snapshot (:meth:`SessionObservation.snapshot`): its
    full server and client lists decide whether the opt-in would close EVERY empty category
    (:func:`_within_legacy_tier`), so the advice never points at an opt-in that cannot collect the device."""
    cls = refusal.get("classification")
    names = ", ".join(refusal.get("names") or []) or "(none recorded)"
    who = (f"device row profile {consent.get('device_profile')}, "
           f"{'named' if consent.get('named_on_run_flag') else 'not named'} on the run flag")
    snap = observation if isinstance(observation, Mapping) else {}
    if cls == "refused_legacy_only" and not _within_legacy_tier(refusal, snap.get("server"), snap.get("client")):
        tail = (f"the device offers only SHA-1-class SSH ({names}), which no profile of this collector "
                "implements")
    elif cls == "refused_legacy_only":
        tail = ("the device offers only SHA-1-class SSH (%s); collecting it requires the legacy-sha1 opt-in "
                "(device row and run flag)" % names)
        if consent.get("device_profile") == LEGACY_SHA1_PROFILE and not consent.get("named_on_run_flag"):
            tail += "; the device row requests legacy-sha1, but this run's --allow-legacy-ssh did not name it"
    elif cls == "refused_weak_dh":
        tail = (f"the device offered only a {refusal.get('offered_group_bits') or '?'}-bit Diffie-Hellman "
                f"group, below the {DH_FLOOR_BITS}-bit floor")
    elif cls in ("refused_unsupported_modern", "refused_cipher_mac"):
        tail = (f"the device requires {names}, which this collector's SSH library does not implement "
                "(a collector gap, not a device weakness)")
    else:
        tail = f"incompatible SSH peer ({refusal.get('category')}); not classifiable from the observed lists"
    return f"{tail} [{who}]"


# --------------------------------------------------------------------------------------------------------
# The sidecar: closed schema, writer, recorder
# --------------------------------------------------------------------------------------------------------
_TOP_KEYS = ("schema", "outcome", "attempts", "platform_source", "consent", "library", "client_offered",
             "server_offered", "negotiated", "observation", "host_key", "refusal", "failure_class",
             "dropped_names")
_CONSENT_KEYS = ("device_profile", "run_flag_profile", "named_on_run_flag", "effective_profile")
_LIBRARY_KEYS = ("paramiko", "netmiko", "transport_class", "default_permits_sha1")
_CLIENT_KEYS = ("kex", "host_key", "cipher", "mac")
_SERVER_KEYS = ("kex", "host_key", "cipher_c2s", "cipher_s2c", "mac_c2s", "mac_s2c")
_NEGOTIATED_KEYS = ("kex", "kex_hash_bytes", "dh_group_bits", "host_key_algorithm", "cipher_c2s",
                    "cipher_s2c", "mac_c2s", "mac_s2c", "strict_kex", "server_software")
_NEGOTIATED_NAME_KEYS = ("kex", "host_key_algorithm", "cipher_c2s", "cipher_s2c", "mac_c2s", "mac_s2c")
_OBSERVATION_KEYS = ("kexinit", "newkeys", "engine_name_agrees", "group_size_agrees")
_HOST_KEY_KEYS = ("policy", "verified")
_REFUSAL_KEYS = ("category", "classification", "detail", "offered_group_bits", "names")
_HOST_KEY_BLOCK = {"policy": "auto-add", "verified": False}


def build_record(*, outcome: str, consent: Mapping[str, Any], library: Mapping[str, Any],
                 platform_source: str = "device_row", attempts: int = 0,
                 observation: Optional[Mapping[str, Any]] = None,
                 refusal: Optional[Mapping[str, Any]] = None,
                 failure_class: Optional[str] = None) -> Dict[str, Any]:
    """Assemble one sidecar record from the sink's snapshot. Every string is an enum, a version, an identifier,
    an algorithm name of the recordable vocabulary (:data:`RECORDABLE_ALGORITHM_NAMES`) or a vendor-grammar server
    banner token; the record holds no hostname, no address, no fingerprint and no device-controlled free text. A
    name or banner outside those is counted in ``dropped_names`` (with the sink's own grammar drops), never stored.
    The classifier reads the sink's full lists, so a refusal is still graded on every name the server offered."""
    snap = dict(observation or {})
    server, client, negotiated = snap.get("server"), snap.get("client"), snap.get("negotiated")
    dropped = [int(snap.get("dropped") or 0)]

    def stored(values: Any) -> List[str]:
        kept, n = recordable_names(values)
        dropped[0] += n
        return kept

    def stored_negotiated(neg: Mapping[str, Any]) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for k in _NEGOTIATED_KEYS:
            value = neg.get(k)
            if k in _NEGOTIATED_NAME_KEYS:
                out[k] = recordable_name(value)
                dropped[0] += int(value is not None and out[k] is None)
            elif k == "server_software":
                out[k] = server_software_token(value)
                dropped[0] += int(value is not None and out[k] is None)
            else:
                out[k] = value
        return out

    def stored_refusal(ref: Mapping[str, Any]) -> Dict[str, Any]:
        out = {k: ref.get(k) for k in _REFUSAL_KEYS}
        out["names"] = stored(ref.get("names") or [])
        return out

    rec: Dict[str, Any] = {
        "schema": SIDECAR_SCHEMA,
        "outcome": outcome,
        "attempts": int(attempts),
        "platform_source": platform_source if platform_source in PLATFORM_SOURCES else "device_row",
        "consent": {k: consent.get(k) for k in _CONSENT_KEYS},
        "library": {k: library.get(k) for k in _LIBRARY_KEYS},
        "client_offered": {k: stored((client or {}).get(k) or []) for k in _CLIENT_KEYS} if client else None,
        "server_offered": {k: stored((server or {}).get(k) or []) for k in _SERVER_KEYS} if server else None,
        "negotiated": (stored_negotiated(negotiated) if negotiated and snap.get("newkeys") else None),
        "observation": {
            "kexinit": bool(snap.get("kexinit")), "newkeys": bool(snap.get("newkeys")),
            "engine_name_agrees": snap.get("engine_name_agrees"),
            "group_size_agrees": snap.get("group_size_agrees"),
        },
        "host_key": dict(_HOST_KEY_BLOCK),
        "refusal": (stored_refusal(refusal) if refusal else None),
        "failure_class": conforming_identifier(failure_class),
    }
    rec["dropped_names"] = dropped[0]
    return rec


def render_record(record: Mapping[str, Any]) -> bytes:
    """Canonical bytes: sorted keys, ASCII, LF, trailing newline -- host-independent."""
    return (json.dumps(record, sort_keys=True, indent=2, ensure_ascii=True) + "\n").encode("ascii")


#: W59 PR-1 review (P3-i): the bounded exponential backoff between ``os.replace`` attempts. On Windows the replace
#: must delete the destination, so it fails while any process (an on-access AV scan, the search indexer, a viewer)
#: holds it; four tries 0.1 s apart (0.3 s in all) was shorter than an ordinary scan. Seven attempts, 0.05 s doubling
#: to 1.6 s between them: 3.15 s in all, never unbounded. The attempt count reaches the record failure.
REPLACE_BACKOFF_S: Tuple[float, ...] = (0.05, 0.1, 0.2, 0.4, 0.8, 1.6)
#: The attribute a failed write's exception carries: how many ``os.replace`` attempts were made (0 = the failure
#: came before the first replace, e.g. the temp file could not be written).
REPLACE_ATTEMPTS_ATTRIBUTE = "ssh_record_replace_attempts"

#: The ``stage`` of a record failure (``SessionRecorder.write_failures`` and the run manifest's
#: ``ssh_transport_consent.record_failures``). The two PRE-CONNECT stages leave the device NOT connected: the
#: ``pending`` write before connecting (design section 6.1 step 1), and the removal of a record an earlier run left in
#: the folder, which precedes it. A device with a pre-connect failure negotiated nothing, so on a live run its missing
#: record is ``not_recorded`` -- exactly what an offline re-analysis of the same folder says -- never
#: ``legacy_unrecorded`` (:func:`compute_ssh_sessions`).
RECORD_STAGE_PENDING = "pending"
RECORD_STAGE_STALE_UNLINK = "stale_record_unlink"
PRE_CONNECT_RECORD_STAGES = frozenset({RECORD_STAGE_PENDING, RECORD_STAGE_STALE_UNLINK})


def write_record_atomic(path: str, record: Mapping[str, Any], *,
                        replace: Optional[Callable[[str, str], None]] = None,
                        sleep: Optional[Callable[[float], None]] = None) -> None:
    """Validate, then publish ``path`` atomically (same-directory temp, fsync, ``os.replace`` retried over the
    bounded exponential :data:`REPLACE_BACKOFF_S` for a transient Windows sharing violation). Raises on any failure
    -- a sidecar that cannot be written must stop the device, never degrade to a silent in-place write -- and the
    raised exception carries :data:`REPLACE_ATTEMPTS_ATTRIBUTE` so the record failure can disclose the retries.
    ``replace`` / ``sleep`` default to ``os.replace`` / ``time.sleep`` (injectable for tests)."""
    replace = replace or os.replace
    sleep = sleep or time.sleep
    errors = validate_record(record)
    if errors:
        raise ValueError("ssh session record fails its closed schema: " + "; ".join(errors[:4]))
    data = render_record(record)
    tmp = "%s.%d.%d.tmp" % (path, os.getpid(), threading.get_ident())
    attempts = 0
    try:
        with open(tmp, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        for delay in REPLACE_BACKOFF_S + (None,):
            attempts += 1
            try:
                replace(tmp, path)
                return
            except OSError:
                if delay is None:
                    raise
                sleep(delay)
    except BaseException as exc:
        try:
            setattr(exc, REPLACE_ATTEMPTS_ATTRIBUTE, attempts)
        except Exception:                                       # noqa: BLE001 - an exception without __dict__
            pass
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _enum(v: Any, allowed: Iterable[Any]) -> bool:
    return isinstance(v, str) and v in tuple(allowed)


def _opt_bool(v: Any) -> bool:
    return v is None or isinstance(v, bool)


def _int_range(v: Any, lo: int, hi: int, *, nullable: bool = False) -> bool:
    if v is None:
        return nullable
    return _plain_int(v) and lo <= v <= hi


def _name_list(v: Any) -> bool:
    # every element a STRING of the vocabulary: ``recordable_name(None) == None`` must not admit a null element
    return isinstance(v, list) and len(v) <= MAX_LIST_LENGTH and all(
        isinstance(x, str) and recordable_name(x) == x for x in v)


def _opt_name(v: Any) -> bool:
    return v is None or recordable_name(v) == v


def _exact_keys(obj: Any, keys: Sequence[str], where: str, errors: List[str]) -> bool:
    if not isinstance(obj, dict):
        errors.append(f"{where}: not an object")
        return False
    if set(obj) != set(keys):
        errors.append(f"{where}: keys differ from the closed schema")
        return False
    return True


def validate_record(record: Any) -> List[str]:
    """Every violation of the closed ``ssh_session/1`` schema (field paths only, never values). An empty list
    means the record holds only enums, library versions, identifiers, small integers, booleans, algorithm names of
    the recordable vocabulary (:data:`RECORDABLE_ALGORITHM_NAMES`) and a server banner token of the vendor grammar
    (:data:`SERVER_SOFTWARE_RE`) -- no device-controlled free text. That, and only that, is what the redaction
    verifiers vouch for when they report a valid record as covered by schema."""
    errors: List[str] = []
    if not _exact_keys(record, _TOP_KEYS, "record", errors):
        return errors
    if record["schema"] != SIDECAR_SCHEMA:
        errors.append("schema")
    if not _enum(record["outcome"], OUTCOMES):
        errors.append("outcome")
    if not _int_range(record["attempts"], 0, 100):
        errors.append("attempts")
    if not _enum(record["platform_source"], PLATFORM_SOURCES):
        errors.append("platform_source")
    if not _int_range(record["dropped_names"], 0, 1_000_000):
        errors.append("dropped_names")
    if record["failure_class"] is not None and conforming_identifier(record["failure_class"]) is None:
        errors.append("failure_class")
    c = record["consent"]
    if _exact_keys(c, _CONSENT_KEYS, "consent", errors):
        if not _enum(c["device_profile"], SSH_PROFILES):
            errors.append("consent.device_profile")
        if not (c["run_flag_profile"] is None or _enum(c["run_flag_profile"], SSH_PROFILES)):
            errors.append("consent.run_flag_profile")
        if not isinstance(c["named_on_run_flag"], bool):
            errors.append("consent.named_on_run_flag")
        if not _enum(c["effective_profile"], SSH_PROFILES):
            errors.append("consent.effective_profile")
    lib = record["library"]
    if _exact_keys(lib, _LIBRARY_KEYS, "library", errors):
        for k in ("paramiko", "netmiko"):
            if not (lib[k] is None or conforming_version(lib[k]) == lib[k]):
                errors.append(f"library.{k}")
        if not (lib["transport_class"] is None or conforming_identifier(lib["transport_class"]) == lib["transport_class"]):
            errors.append("library.transport_class")
        if not _opt_bool(lib["default_permits_sha1"]):
            errors.append("library.default_permits_sha1")
    for key, keys in (("client_offered", _CLIENT_KEYS), ("server_offered", _SERVER_KEYS)):
        block = record[key]
        if block is None:
            continue
        if _exact_keys(block, keys, key, errors):
            for k in keys:
                if not _name_list(block[k]):
                    errors.append(f"{key}.{k}")
    neg = record["negotiated"]
    if neg is not None and _exact_keys(neg, _NEGOTIATED_KEYS, "negotiated", errors):
        for k in _NEGOTIATED_NAME_KEYS:
            if not _opt_name(neg[k]):
                errors.append(f"negotiated.{k}")
        if not (neg["server_software"] is None or server_software_token(neg["server_software"]) == neg["server_software"]):
            errors.append("negotiated.server_software")
        if not _int_range(neg["kex_hash_bytes"], 1, 128, nullable=True):
            errors.append("negotiated.kex_hash_bytes")
        if not _int_range(neg["dh_group_bits"], 1, 65536, nullable=True):
            errors.append("negotiated.dh_group_bits")
        if not isinstance(neg["strict_kex"], bool):
            errors.append("negotiated.strict_kex")
    ob = record["observation"]
    if _exact_keys(ob, _OBSERVATION_KEYS, "observation", errors):
        for k in ("kexinit", "newkeys"):
            if not isinstance(ob[k], bool):
                errors.append(f"observation.{k}")
        for k in ("engine_name_agrees", "group_size_agrees"):
            if not _opt_bool(ob[k]):
                errors.append(f"observation.{k}")
    hk = record["host_key"]
    if _exact_keys(hk, _HOST_KEY_KEYS, "host_key", errors):
        # exact values, never ``==`` on the block: ``False == 0 == 0.0`` would admit a number as "not verified"
        if hk["policy"] != _HOST_KEY_BLOCK["policy"] or hk["verified"] is not False:
            errors.append("host_key")
    ref = record["refusal"]
    if ref is not None and _exact_keys(ref, _REFUSAL_KEYS, "refusal", errors):
        if not _enum(ref["category"], REFUSAL_CATEGORIES):
            errors.append("refusal.category")
        if not _enum(ref["classification"], REFUSAL_CLASSES):
            errors.append("refusal.classification")
        if not _enum(ref["detail"], REFUSAL_DETAILS):
            errors.append("refusal.detail")
        if not _int_range(ref["offered_group_bits"], 1, 65536, nullable=True):
            errors.append("refusal.offered_group_bits")
        if not _name_list(ref["names"]):
            errors.append("refusal.names")
    # Cross-field shape: a refusal only on a refused outcome; a pending record negotiated nothing.
    outcome = record.get("outcome")
    if (ref is not None) != (outcome == "negotiation_refused"):
        errors.append("refusal: present iff outcome is negotiation_refused")
    if outcome == "pending" and (neg is not None or record["server_offered"] is not None):
        errors.append("pending: a pending record holds no observation")
    return errors


def parse_record(data: bytes) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """(record, None) for a valid sidecar, or (None, reason). Strict JSON: duplicate keys and non-standard
    constants are refused; the reason names the field path only."""
    def _pairs(pairs):
        out: Dict[str, Any] = {}
        for k, v in pairs:
            if k in out:
                raise ValueError("duplicate key")
            out[k] = v
        return out

    def _const(_v):
        raise ValueError("non-standard JSON constant")

    try:
        obj = json.loads(data.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_const)
    except (UnicodeDecodeError, ValueError) as exc:
        return None, f"malformed session record ({type(exc).__name__})"
    errors = validate_record(obj)
    if errors:
        return None, "session record fails its closed schema: " + "; ".join(errors[:4])
    return obj, None


class SessionRecorder:
    """One device's session record across its connection attempts.

    Write timing (design §6.1): ``write_pending`` BEFORE connecting (a failure means the device is not
    connected); ``complete_established`` inside the client's ``connect()`` after authentication and BEFORE
    ``connect()`` returns, i.e. before netmiko prepares the session or the collector sends the first command
    (a failure raises :class:`SessionRecordError`); ``finish_failure`` after a failed final attempt. A record
    that stays ``pending`` is evidence that a session was started and its record never completed.

    ``path=None`` records in memory only (direct library callers and tests that drive ``connect_device``)."""

    def __init__(self, path: Optional[str], *, consent: Mapping[str, Any], library: Mapping[str, Any],
                 platform_source: str = "device_row",
                 writer: Optional[Callable[[str, Mapping[str, Any]], None]] = None) -> None:
        self.path = path
        self.consent = dict(consent)
        self.library = dict(library)
        self.platform_source = platform_source
        self.attempts = 0
        self.observation: Optional[SessionObservation] = None
        self._negotiated_snapshot: Optional[Dict[str, Any]] = None
        self.record: Optional[Dict[str, Any]] = None
        self.write_failures: List[Dict[str, Any]] = []
        self._writer = writer or write_record_atomic

    @property
    def effective_profile(self) -> str:
        return self.consent.get("effective_profile") or DEFAULT_PROFILE

    def _write(self, record: Dict[str, Any], stage: str) -> None:
        self.record = record
        if self.path is None:
            return
        try:
            self._writer(self.path, record)
        except Exception as exc:
            attempts = getattr(exc, REPLACE_ATTEMPTS_ATTRIBUTE, 0)
            self.write_failures.append({
                "stage": stage, "error_class": type(exc).__name__,
                # P3-i: how many atomic-replace attempts the writer made before giving up (0: none was reached)
                "replace_attempts": attempts if _plain_int(attempts) and attempts >= 0 else 0})
            raise

    def write_pending(self) -> None:
        self._write(build_record(outcome="pending", consent=self.consent, library=self.library,
                                 platform_source=self.platform_source, attempts=0), RECORD_STAGE_PENDING)

    def begin_attempt(self) -> SessionObservation:
        self.attempts += 1
        self.observation = SessionObservation()
        return self.observation

    def _best_snapshot(self) -> Dict[str, Any]:
        snap = self.observation.snapshot() if self.observation is not None else {}
        if snap.get("newkeys"):
            self._negotiated_snapshot = snap
            return snap
        # The profile never changes between attempts, so an earlier attempt's negotiation is what this
        # device negotiates; a later attempt that failed before NEWKEYS must not erase it.
        if self._negotiated_snapshot is not None and not snap.get("kexinit"):
            return self._negotiated_snapshot
        return snap

    def complete_established(self) -> None:
        snap = self._best_snapshot()
        try:
            self._write(build_record(outcome="established", consent=self.consent, library=self.library,
                                     platform_source=self.platform_source, attempts=self.attempts,
                                     observation=snap), "established")
        except Exception as exc:
            raise SessionRecordError(f"session record could not be written ({type(exc).__name__})") from exc

    def finish_failure(self, outcome: str, exc: Optional[BaseException],
                       refusal: Optional[Mapping[str, Any]] = None) -> bool:
        """Replace the pending record by the failure record. Returns False (and keeps ``write_failures``)
        when the write fails; the sealed sidecar then stays ``pending``."""
        snap = self._best_snapshot()
        try:
            self._write(build_record(outcome=outcome, consent=self.consent, library=self.library,
                                     platform_source=self.platform_source, attempts=self.attempts,
                                     observation=snap, refusal=refusal,
                                     failure_class=type(exc).__name__ if exc is not None else None),
                        outcome)
            return True
        except Exception:                                       # noqa: BLE001 - recorded in write_failures
            return False


# --------------------------------------------------------------------------------------------------------
# Derivation: sidecar -> snapshot row (design §6.2)
# --------------------------------------------------------------------------------------------------------
def _sha1_flags(neg: Mapping[str, Any]) -> Dict[str, bool]:
    kex = kex_grade(neg.get("kex"))
    return {
        "kex": bool(neg.get("kex_hash_bytes") == 20 or (kex is not None and kex.hash_bytes == 20)),
        "host_key_signature": neg.get("host_key_algorithm") in SHA1_HOST_KEY_NAMES,
        "mac": neg.get("mac_c2s") in SHA1_MACS or neg.get("mac_s2c") in SHA1_MACS,
    }


def _legacy_mac_or_cipher(neg: Mapping[str, Any]) -> bool:
    macs = {neg.get("mac_c2s"), neg.get("mac_s2c")}
    ciphers = {neg.get("cipher_c2s"), neg.get("cipher_s2c")}
    return bool(macs & (SHA1_MACS | MD5_MACS)) or bool(ciphers & LEGACY_CIPHERS)


def _negotiated_status(record: Mapping[str, Any]) -> Tuple[str, Optional[str]]:
    """(status, unknown-reason) for a session whose key exchange was observed."""
    neg = record.get("negotiated") or {}
    obs = record.get("observation") or {}
    kex = neg.get("kex")
    grade = kex_grade(kex)
    hash_bytes = neg.get("kex_hash_bytes")
    host_key = neg.get("host_key_algorithm")
    if not kex or hash_bytes is None:
        return STATUS_UNKNOWN, "key exchange not observed"
    if obs.get("engine_name_agrees") is False or obs.get("group_size_agrees") is False:
        return STATUS_UNKNOWN, "inconsistent observation"
    if grade is None:
        return STATUS_UNKNOWN, "negotiated key exchange is not in the graded vocabulary"
    if grade.hash_bytes != hash_bytes:
        return STATUS_UNKNOWN, "inconsistent observation"
    bits = neg.get("dh_group_bits")
    if grade.modp and bits is None:
        return STATUS_UNKNOWN, "MODP group size not observed"
    if grade.modp and bits < DH_FLOOR_BITS:
        return STATUS_WEAK_DH, None
    hk = host_key_grade(host_key)
    if hash_bytes == 20 or hk == GRADE_LEGACY:
        return STATUS_LEGACY_SHA1, None
    if hk is None:
        return STATUS_UNKNOWN, "negotiated host-key algorithm is not in the graded vocabulary"
    if hash_bytes >= 32 and hk == GRADE_MODERN:
        return STATUS_MODERN, None
    return STATUS_UNKNOWN, "inconsistent observation"


#: W59 PR-1 review: the reason a live run gives a device with no record because a PRE-CONNECT record failure
#: (:data:`PRE_CONNECT_RECORD_STAGES`) left it unconnected. Nothing was negotiated, so it is ``not_recorded`` -- the
#: status an offline re-analysis of the same folder derives -- even for a device the run authorized for a legacy
#: profile (design section 6.1 step 1 and section 6.2 agree).
REASON_NOT_CONNECTED = ("the session record could not be written before connecting, so the device was not connected "
                        "and nothing was negotiated")


def derive_row(host: str, data: Optional[bytes], *, evidence: str, live: bool,
               eligible_hosts: Iterable[str] = (), read_error: Optional[str] = None,
               not_connected: bool = False) -> Dict[str, Any]:
    """One ``ssh_sessions`` row. Consent fields are read ONLY from the sealed sidecar, never from the current
    devices.json or command line. ``not_connected`` marks a live-run device whose pre-connect record write failed (the
    manifest's ``record_failures``): with no record it is ``not_recorded`` (:data:`REASON_NOT_CONNECTED`), never
    ``legacy_unrecorded``."""
    eligible = set(eligible_hosts or ())
    row: Dict[str, Any] = {
        "host": host, "recorded": False, "outcome": None, "attempts": None, "platform_source": None,
        "device_profile": None, "named_on_run_flag": None, "effective_profile": None,
        "negotiated": None, "sha1": {"kex": False, "host_key_signature": False, "mac": False},
        "dh_group_bits": None, "dh_below_2048": False, "legacy_mac_or_cipher": False, "strict_kex": None,
        "host_key_verified": False, "library_permits_sha1": None, "library": None, "refusal": None,
        "client_offered": None, "server_offered": None,
        "status": None, "reason": None, "severity": None, "finding": None, "label": None,
        "evidence": evidence,
    }
    if data is None and read_error is None:
        row["evidence"] = None
        if not_connected:
            row["status"], row["reason"] = STATUS_NOT_RECORDED, REASON_NOT_CONNECTED
            return _finish(row)
        row["status"] = STATUS_LEGACY_UNRECORDED if (live and host in eligible) else STATUS_NOT_RECORDED
        row["reason"] = ("authorized for a legacy profile by this run but no session record exists"
                         if row["status"] == STATUS_LEGACY_UNRECORDED else "no session record")
        return _finish(row)
    record, reason = (None, read_error) if read_error else parse_record(data)  # type: ignore[arg-type]
    if record is None:
        row["status"], row["reason"] = STATUS_UNKNOWN, reason
        return _finish(row)
    consent = record["consent"]
    neg = record.get("negotiated")
    row.update({
        "recorded": True, "outcome": record["outcome"], "attempts": record["attempts"],
        "platform_source": record["platform_source"],
        "device_profile": consent["device_profile"], "named_on_run_flag": consent["named_on_run_flag"],
        "effective_profile": consent["effective_profile"],
        "library_permits_sha1": record["library"]["default_permits_sha1"],
        "library": dict(record["library"]),
        "refusal": dict(record["refusal"]) if record.get("refusal") else None,
        "client_offered": dict(record["client_offered"]) if record.get("client_offered") else None,
        "server_offered": dict(record["server_offered"]) if record.get("server_offered") else None,
    })
    if neg:
        row["negotiated"] = dict(neg)
        row["sha1"] = _sha1_flags(neg)
        row["dh_group_bits"] = neg.get("dh_group_bits")
        row["dh_below_2048"] = bool(neg.get("dh_group_bits") is not None and neg["dh_group_bits"] < DH_FLOOR_BITS)
        row["legacy_mac_or_cipher"] = _legacy_mac_or_cipher(neg)
        row["strict_kex"] = neg.get("strict_kex")
    outcome = record["outcome"]
    if outcome == "pending":
        if consent["effective_profile"] != DEFAULT_PROFILE:
            row["status"] = STATUS_LEGACY_UNRECORDED
            row["reason"] = "the session record was never completed under a legacy profile"
        else:
            row["status"], row["reason"] = STATUS_UNKNOWN, "the session record was never completed"
    elif outcome == "negotiation_refused":
        cls = (record.get("refusal") or {}).get("classification")
        if cls in STATUS_FINDING:
            row["status"] = cls
        else:
            row["status"], row["reason"] = STATUS_UNKNOWN, "unclassified negotiation refusal"
    elif neg and (record.get("observation") or {}).get("newkeys"):
        # established, auth_failed, or a connection that failed after key exchange: the negotiated session
        # is the device's posture -- for auth_failed the password crossed it.
        row["status"], row["reason"] = _negotiated_status(record)
    else:
        row["status"] = STATUS_UNKNOWN
        row["reason"] = ("authentication failed before any key exchange was observed"
                         if outcome == "auth_failed" else "negotiation never observed")
    return _finish(row)


def _finish(row: Dict[str, Any]) -> Dict[str, Any]:
    finding, severity = STATUS_FINDING.get(row["status"], (FINDING_VERIFY, None))
    row["finding"], row["severity"] = finding, severity
    row["label"] = disclosure_sentence(row)
    return row


def disclosure_sentence(row: Mapping[str, Any]) -> Optional[str]:
    """The ONE owner of the disclosure wording: what was negotiated, and under which consent (§6.3). ``None``
    for ``modern`` (the Collection Transport sheet still shows the algorithms and "host key not verified")."""
    status = row.get("status")
    legacy = row.get("effective_profile") not in (None, DEFAULT_PROFILE)
    refusal = row.get("refusal") or {}
    names = ", ".join(refusal.get("names") or []) or "unrecorded algorithms"
    if status == STATUS_LEGACY_SHA1:
        if legacy:
            return ("collected over SHA-1 SSH by explicit opt-in (device row and run flag); session integrity "
                    "weakened; host key not verified")
        lib = row.get("library") or {}
        clause = (f" (the collector permitted SHA-1: paramiko {lib.get('paramiko')})"
                  if row.get("library_permits_sha1") is True and lib.get("paramiko") else "")
        return (f"negotiated SHA-1 SSH without opt-in{clause}; session integrity weakened; "
                "host key not verified")
    if status == STATUS_WEAK_DH:
        return (f"negotiated a {row.get('dh_group_bits')}-bit Diffie-Hellman group, below {DH_FLOOR_BITS} "
                f"({'with opt-in' if legacy else 'without opt-in'}); treat the collection account's password as "
                "exposed and rotate it; host key not verified")
    if status == STATUS_LEGACY_UNRECORDED:
        return ("authorized for SHA-1 SSH by its run, but the session record was never completed; treated as "
                "collected over SHA-1")
    if status == "refused_legacy_only":
        if _within_legacy_tier(refusal, row.get("server_offered"), row.get("client_offered")):
            return (f"not collected: the device offers only SHA-1-class SSH ({names}); collecting it requires "
                    "the legacy-sha1 opt-in")
        return (f"not collected: the device offers only SHA-1-class SSH ({names}), which no profile of this "
                "collector implements")
    if status == "refused_weak_dh":
        return (f"not collected: the device offered only a {refusal.get('offered_group_bits') or '?'}-bit "
                f"Diffie-Hellman group, below the {DH_FLOOR_BITS}-bit floor")
    if status in ("refused_unsupported_modern", "refused_cipher_mac"):
        return (f"not collected: the device requires {names}, which this collector's SSH library does not "
                "implement (a collector gap, not a device weakness)")
    if status in (STATUS_UNKNOWN, STATUS_NOT_RECORDED):
        return "SSH session posture not recorded"
    return None


def _within_legacy_tier(refusal: Mapping[str, Any], server: Any = None, client: Any = None) -> bool:
    """True when the ``legacy-sha1`` opt-in would collect a legacy-only refusal's device, so its advice may say the
    device "requires the legacy-sha1 opt-in" (design section 4.4). The refused category's offered names must include
    one the tier adds; and when both sides' recorded lists are given, the tier must close EVERY category with no
    common algorithm (:func:`legacy_tier_closes`), not only the first one paramiko refused on -- a device that also
    lacks a common cipher, or whose host keys are DSA-only while its kex is SHA-1, is not collectable by any profile.
    A legacy-only refusal is classified only from recorded lists, so a real record always supplies them; without them
    (a hand-built row) only the refused category is judged."""
    names = set(refusal.get("names") or [])
    tier = LEGACY_SHA1_TIER_KEX if refusal.get("category") == "kex" else LEGACY_SHA1_TIER_HOST_KEYS
    if not names & set(tier):
        return False
    if isinstance(server, Mapping) and isinstance(client, Mapping):
        return legacy_tier_closes(server, client)
    return True


#: W59 PR-1 review (P2-a): the reason a live run gives a sidecar it did not write itself -- a record an earlier run
#: left in the folder, or one this run wrote for ANOTHER devices.json row that resolves to the same folder. Read as
#: current posture, a stale ``modern`` record would be absence rendered as health.
REASON_NOT_WRITTEN_BY_THIS_RUN = "session record not written by this run"


def compute_ssh_sessions(hosts: Iterable[str], read_sidecar: Callable[[str], Tuple[Optional[bytes], Optional[str]]],
                         *, live: bool, consent: Optional[Mapping[str, Any]],
                         evidence_path: Callable[[str], str],
                         run_written: Optional[Iterable[str]] = None) -> Dict[str, Any]:
    """The ``ssh_sessions`` snapshot block (``ssh_session_set/1``): one row per device. ``read_sidecar(host)``
    returns ``(bytes, None)``, ``(None, None)`` when no sidecar exists, or ``(None, reason)`` when one exists
    but could not be read through custody. Pure on its inputs; never raises for a row.

    On a LIVE run a row is derived ONLY from a sidecar this run wrote: ``run_written`` is the set of hosts whose
    ``pending`` record this run published (and that no second devices.json row claimed). Any other sidecar present
    in the folder is ``unknown`` with :data:`REASON_NOT_WRITTEN_BY_THIS_RUN`, never its stale posture; an absent one
    is ``not_recorded`` (or ``legacy_unrecorded`` for a device the run authorized, unless the consent block's
    ``record_failures`` show a PRE-CONNECT failure for it: that device was never connected, so it is ``not_recorded``
    with :data:`REASON_NOT_CONNECTED`, the status an offline re-analysis derives). ``None`` on a live run means
    nothing was written (fail closed). An offline re-analysis (``live=False``) reads every sealed sidecar."""
    consent_block = dict(consent) if isinstance(consent, Mapping) else (
        offline_consent_block() if not live else live_consent_block(()))
    eligible = consent_block.get("devices_eligible") or ()
    failures = consent_block.get("record_failures")
    not_connected = {f.get("host") for f in (failures if isinstance(failures, list) else ())
                     if isinstance(f, Mapping) and isinstance(f.get("host"), str)
                     and f.get("stage") in PRE_CONNECT_RECORD_STAGES} if live else set()
    written = {str(h) for h in (run_written or ()) if isinstance(h, str)}
    rows: List[Dict[str, Any]] = []
    for host in sorted({str(h) for h in hosts or () if str(h)}):
        try:
            data, err = read_sidecar(host)
        except Exception as exc:                                # noqa: BLE001 - one row never breaks the block
            data, err = None, f"session record unreadable ({type(exc).__name__})"
        if live and host not in written and (data is not None or err is not None):
            data, err = None, REASON_NOT_WRITTEN_BY_THIS_RUN
        rows.append(derive_row(host, data, evidence=evidence_path(host), live=live,
                               eligible_hosts=eligible, read_error=err, not_connected=host in not_connected))
    by_status = {s: 0 for s in STATUSES}
    for r in rows:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
    negotiated_sha1 = sorted(r["host"] for r in rows if r["sha1"]["kex"] or r["sha1"]["host_key_signature"])
    if consent_block.get("mode") == "live":
        consent_block["devices_negotiated_sha1"] = negotiated_sha1
    summary = {
        "n_devices": len(rows),
        "mode": "live" if live else "offline",
        "by_status": by_status,
        "n_exposed": sum(1 for r in rows if r["finding"] == FINDING_EXPOSED),
        "n_verify": sum(1 for r in rows if r["finding"] == FINDING_VERIFY),
        "n_closed": sum(1 for r in rows if r["finding"] == FINDING_CLOSED),
        "n_legacy_mac_or_cipher": sum(1 for r in rows if r["legacy_mac_or_cipher"]),
        "run_flag": consent_block.get("run_flag"),
        "host_key_verified": False,
    }
    note = ("What each live SSH session negotiated, read from the sealed per-device session record. A device "
            "without a record is not recorded -- never modern. Host keys are not verified on any path (netmiko "
            "auto-adds them); host-key pinning is a separate follow-up. CI-validated, not field-validated.")
    return {"schema": SET_SCHEMA, "owner": OWNER, "rows": rows, "summary": summary,
            "consent": consent_block, "note": note}


def software_risk_projection(block: Any) -> Dict[str, Dict[str, Any]]:
    """``{host: {status, finding, severity, label, evidence}}`` for the ``ssh-legacy-transport`` surface,
    projected from the ONE owner (``ssh_sessions``). A block that is absent or malformed projects nothing; a row
    whose finding is not one of the three tokens projects ``verify``. Total on hostile input (a re-loaded
    snapshot is untrusted): every field is type-checked before use, and nothing here raises."""
    rows = block.get("rows") if isinstance(block, Mapping) else None
    out: Dict[str, Dict[str, Any]] = {}
    for r in rows if isinstance(rows, list) else []:
        if not isinstance(r, Mapping) or not isinstance(r.get("host"), str):
            continue
        raw_finding = r.get("finding")
        finding = raw_finding if isinstance(raw_finding, str) and raw_finding in (
            FINDING_EXPOSED, FINDING_VERIFY, FINDING_CLOSED) else FINDING_VERIFY
        raw_sev = r.get("severity")
        severity = raw_sev if isinstance(raw_sev, str) and raw_sev in ("Medium", "High") else None
        status = r.get("status") if isinstance(r.get("status"), str) else None
        label = r.get("label") if isinstance(r.get("label"), str) else None
        neg = r.get("negotiated") if isinstance(r.get("negotiated"), Mapping) else {}
        parts = [label or ("SSH session negotiated SHA-256 or better" if status == STATUS_MODERN
                           else "SSH session posture not recorded")]
        kex, host_key = neg.get("kex"), neg.get("host_key_algorithm")
        if isinstance(kex, str) or isinstance(host_key, str):
            parts.append(f"negotiated kex {kex if isinstance(kex, str) else '?'}, "
                         f"host key {host_key if isinstance(host_key, str) else '?'}")
        if isinstance(r.get("evidence"), str) and r.get("evidence"):
            parts.append(f"session record {r['evidence']}")
        offered_lacked = _collector_offered_device_lacked(r)
        if offered_lacked:
            parts.append("stronger algorithms the collector offered and the device lacked: "
                         + ", ".join(offered_lacked))
        out[r["host"]] = {"status": status, "finding": finding, "severity": severity,
                          "label": label, "evidence": "; ".join(parts)}
    return out


_FINDING_ORDER = {FINDING_EXPOSED: 0, FINDING_VERIFY: 1}
_SEVERITY_ORDER = {"High": 0, "Medium": 1}


def disclosure_groups(block: Any) -> List[Dict[str, Any]]:
    """Design section 6.3, the per-device disclosure the collection-integrity deliverables carry (runbook, operations
    handbook, executive deck): every ``ssh_sessions`` row whose status is not ``modern``, grouped by its owned label
    (:func:`disclosure_sentence`, never re-worded by a renderer), worst first: exposed High, exposed Medium, then
    verify. Each group is ``{finding, severity, label, statuses, hosts}``; ``hosts`` is complete and sorted, so a
    renderer that shows fewer must say how many it left out. ``[]`` for an absent or malformed block (the caller
    words that as "not in this snapshot", never as "every session modern"). Total on hostile input: every field is
    type-checked and nothing here raises."""
    rows = block.get("rows") if isinstance(block, Mapping) else None
    groups: Dict[Tuple[str, Optional[str], str], Dict[str, Any]] = {}
    for r in rows if isinstance(rows, list) else []:
        if not isinstance(r, Mapping) or not isinstance(r.get("host"), str) or not r.get("host"):
            continue
        status = r.get("status") if isinstance(r.get("status"), str) else None
        if status == STATUS_MODERN:
            continue
        raw_finding = r.get("finding")
        finding = raw_finding if isinstance(raw_finding, str) and raw_finding == FINDING_EXPOSED else FINDING_VERIFY
        raw_sev = r.get("severity")
        severity = raw_sev if finding == FINDING_EXPOSED and isinstance(raw_sev, str) and raw_sev in _SEVERITY_ORDER \
            else None
        raw_label = r.get("label")
        label = raw_label if isinstance(raw_label, str) and raw_label else "SSH session posture not recorded"
        g = groups.setdefault((finding, severity, label), {"statuses": set(), "hosts": set()})
        g["statuses"].add(status or STATUS_UNKNOWN)
        g["hosts"].add(r["host"])
    out: List[Dict[str, Any]] = []
    for key in sorted(groups, key=lambda k: (_FINDING_ORDER.get(k[0], 2), _SEVERITY_ORDER.get(k[1] or "", 2), k[2])):
        finding, severity, label = key
        out.append({"finding": finding, "severity": severity, "label": label,
                    "statuses": sorted(groups[key]["statuses"]), "hosts": sorted(groups[key]["hosts"])})
    return out


def _str_names(container: Any, key: str) -> List[str]:
    values = container.get(key) if isinstance(container, Mapping) else None
    return [v for v in values if isinstance(v, str)] if isinstance(values, list) else []


def _collector_offered_device_lacked(row: Mapping[str, Any]) -> List[str]:
    """For a SHA-1 / weak-DH row: the modern kex and host-key names the collector offered that the device's
    recorded lists did not. Empty when either side's lists were not recorded."""
    status = row.get("status")
    if not isinstance(status, str) or status not in (STATUS_LEGACY_SHA1, STATUS_WEAK_DH, "refused_legacy_only",
                                                     "refused_weak_dh"):
        return []
    client, server = row.get("client_offered"), row.get("server_offered")
    if not isinstance(client, Mapping) or not isinstance(server, Mapping):
        return []
    server_kex, server_hk = set(_str_names(server, "kex")), set(_str_names(server, "host_key"))
    lacked = [n for n in _str_names(client, "kex") if _kex_is_modern(n) and n not in server_kex]
    lacked += [n for n in _str_names(client, "host_key")
               if host_key_grade(n) == GRADE_MODERN and n not in server_hk]
    return lacked                     # bounded by construction: each recorded list holds at most MAX_LIST_LENGTH
