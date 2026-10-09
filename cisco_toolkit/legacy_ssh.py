"""W59 PR-2: the opt-in legacy SSH transport tier (tier 1 only).

Design: ``docs/w59-legacy-ssh-design-2026-10-09.md`` §4.1 (mechanism), §5 (consent) and §7 (the
``legacy_ssh_confined`` published claim). This module is the ONLY place in the product that lets a
paramiko 5 client negotiate a SHA-1 exchange hash or a SHA-1 RSA host-key signature, and it does so
only for a device whose EFFECTIVE profile is the legacy one: the device row requests it AND the run's
``--allow-legacy-ssh`` names it. The collector imports this module lazily, inside its one transport
resolver (``_transport_for_profile``) and its consent preflight, for such a device only, so a run with no
effective-legacy device never loads it.

What it is:

* frozen paramiko subclasses whose algorithm tables are NEW mappings (``MappingProxyType``) or tuples;
  every SHA-1 entry is APPENDED after every stock algorithm of its kind, so an opted-in device that offers
  any SHA-2 algorithm still negotiates SHA-2 (RFC 4253 §7.1: the client's first mutually supported entry
  wins), and the SHA-1 order follows RFC 9142 Table 12 (the MAY group before the SHOULD NOT exchange);
* a group-exchange floor checked BEFORE the client answers the server's group: an offered prime below
  ``DH_FLOOR_BITS`` raises :class:`WeakGroupRefused` (an ``IncompatiblePeer``) before ``KEXDH_GEX_INIT``,
  so no key share and no password ever crosses a group below the floor;
* :data:`WEAKNESS_DECLARATION`, the first-party CWE-327 declaration pip-audit cannot see.

What it never does (each rule is re-derived on every run by ``cisco_toolkit.attestation``'s
``legacy_ssh_confined`` claim and pinned by ``tests/test_legacy_ssh.py``):

* use a stock paramiko table except to COPY it (``tuple(...)``, a ``+`` chain, a ``{**...}`` display or
  ``MappingProxyType(...)``): no store into, mutating call on, alias of or method call on anything it imports
  from paramiko, so it cannot open SHA-1 for every thread and every device;
* register anything globally (paramiko's ``key_classes`` is an explicit list, so defining a key subclass
  registers nothing);
* make a command, channel or authentication call of its own: the collector's one factory opens and drives
  every session;
* restate an SSH algorithm name, or build one: every name, the certificate variant included, comes from
  ``cisco_toolkit.ssh_session``'s vocabulary.

It imports ``__future__``, ``hashlib``, ``types``, ``cryptography``'s ``hashes`` and paramiko only (plus the
network-free vocabulary owner) -- a closed allowlist the published claim enforces. It imports no netmiko: the
collector owns driver construction for both paths.
"""
from __future__ import annotations

import hashlib
from types import MappingProxyType, SimpleNamespace

from cryptography.hazmat.primitives import hashes
from paramiko.kex_gex import KexGexSHA256
from paramiko.kex_group14 import KexGroup14SHA256
from paramiko.rsakey import RSAKey
from paramiko.ssh_exception import IncompatiblePeer
from paramiko.transport import Transport

from cisco_toolkit.ssh_session import (
    DEFAULT_PROFILE,
    DH_FLOOR_BITS,
    LEGACY_SHA1_PROFILE,
    LEGACY_SHA1_TIER_HOST_KEYS,
    LEGACY_SHA1_TIER_KEX,
    SSH_PROFILES,
    ObservingTransportMixin,
    permits_sha1,
)

# -------------------------------------------------------------------------------- vocabulary ---
# Tier 1 only (design §11, decision 1): exactly one non-default profile. A second profile in the owner
# vocabulary needs its own design delta and owner approval, so it fails loudly here instead of silently
# mapping onto this tier's transport.
if tuple(SSH_PROFILES) != (DEFAULT_PROFILE, LEGACY_SHA1_PROFILE):
    raise ImportError(
        "cisco_toolkit.legacy_ssh implements exactly one legacy profile (tier 1); "
        f"the vocabulary now declares {len(SSH_PROFILES)} profiles")

# RFC 9142 Table 12 order, as the vocabulary owner states it: the fixed 2048-bit group first (MAY), the
# group exchange second (SHOULD NOT). Unpacking pins the tier's size as well as its order.
_KEX_GROUP14_SHA1, _KEX_GEX_SHA1 = LEGACY_SHA1_TIER_KEX

# The owner's host-key tier is (the plain RSA SHA-1 signature name, its OpenSSH host-certificate variant), both
# taken from the owner as they are. Only the plain name joins `_preferred_keys`: paramiko's `preferred_keys`
# property appends the certificate variant of every plain name itself. Both names key `_key_info`.
_HOST_KEY_RSA_SHA1, _HOST_KEY_RSA_SHA1_CERT = LEGACY_SHA1_TIER_HOST_KEYS
if _HOST_KEY_RSA_SHA1_CERT == _HOST_KEY_RSA_SHA1 or not _HOST_KEY_RSA_SHA1_CERT.startswith(_HOST_KEY_RSA_SHA1):
    raise ImportError(
        "cisco_toolkit.legacy_ssh expects the vocabulary's host-key tier as (plain name, its certificate variant)")


# ------------------------------------------------------------------------------- refusal type ---
class WeakGroupRefused(IncompatiblePeer):
    """The server offered a group-exchange prime below :data:`DH_FLOOR_BITS`.

    Raised in the transport thread from :meth:`LegacyKexGexSHA1._parse_kexdh_gex_group` BEFORE the client
    sends ``KEXDH_GEX_INIT``; paramiko saves it and ``start_client`` re-raises it in the caller. It
    subclasses ``IncompatiblePeer`` so the collector's negotiation classifier
    (``cisco_toolkit.ssh_session.classify_failure``, which recognises it by NAME) records a deterministic
    ``refused_weak_dh`` refusal with one attempt, never retried (netmiko wraps every ``SSHException`` as a
    timeout, so the original survives only in ``__context__``). The offered size travels on the exception
    (``offered_bits``) for the session record's ``refusal.offered_group_bits``.
    """

    category = "kex"

    def __init__(self, offered_bits: int, floor_bits: int):
        self.offered_bits = int(offered_bits)
        self.floor_bits = int(floor_bits)
        super().__init__(
            f"Incompatible ssh peer (kex: the offered Diffie-Hellman group of {self.offered_bits} bits "
            f"is below the {self.floor_bits}-bit floor of the {LEGACY_SHA1_PROFILE} profile; refused "
            f"before the client sent its key share)")


# ------------------------------------------------------------------------- key exchange tier ---
class LegacyKexGroup14SHA1(KexGroup14SHA256):
    """The RFC 3526 2048-bit group 14 (``P``/``G`` inherited unchanged) with a SHA-1 exchange hash.

    paramiko 5's group-14 engine reads ``self.hash_algo`` for the exchange hash, and the transport's
    ``_compute_key`` reads the same attribute for key derivation, so these two class attributes are the
    whole difference."""

    name = _KEX_GROUP14_SHA1
    hash_algo = hashlib.sha1


class LegacyKexGexSHA1(KexGexSHA256):
    """RFC 4419 group exchange with a SHA-1 exchange hash and an enforced 2048-bit floor.

    paramiko 5's client REQUESTS ``min_bits`` 2048 but only rejects a server prime below 1024 bits, and its
    own ``_parse_kexdh_gex_group`` sends ``KEXDH_GEX_INIT`` in the same method that reads the prime. The floor
    is therefore checked on a COPY of the message, before delegating, so the refusal happens with nothing
    sent. This is the only paramiko protocol method the module overrides; it copies no paramiko code."""

    name = _KEX_GEX_SHA1
    hash_algo = hashlib.sha1
    floor_bits = DH_FLOOR_BITS

    def _parse_kexdh_gex_group(self, m):
        # A copy, so the original's read position is untouched for paramiko's own parse below.
        probe = type(m)(m.asbytes())
        prime = probe.get_mpint()
        offered = prime.bit_length() if prime > 0 else 0
        if offered < self.floor_bits:
            raise WeakGroupRefused(offered, self.floor_bits)
        return super()._parse_kexdh_gex_group(m)


# --------------------------------------------------------------------------- host-key tier ---
class LegacySHA1RSAKey(RSAKey):
    """An RSA host key that also verifies the SHA-1 PKCS#1 v1.5 signature.

    ``RSAKey.verify_ssh_sig`` returns False for any signature name absent from ``HASHES``; this class
    adds the SHA-1 entries to a NEW frozen mapping. It is reachable only through the legacy transport's
    ``_key_info``, which is keyed by the negotiated host-key type, so only a negotiation of that type can
    reach it. It is never registered in ``paramiko.key_classes``."""

    HASHES = MappingProxyType({
        **RSAKey.HASHES,
        _HOST_KEY_RSA_SHA1: hashes.SHA1,
        _HOST_KEY_RSA_SHA1_CERT: hashes.SHA1,
    })


# ------------------------------------------------------------------------------ transport ---
class LegacySHA1Transport(ObservingTransportMixin, Transport):
    """The legacy-tier transport: stock paramiko 5 tables with the tier APPENDED, plus the observer.

    One instance is created per connection by the collector's factory; the class itself is frozen, so a
    ``ThreadPoolExecutor`` run that mixes default and legacy devices shares no mutable algorithm state.
    Ciphers, MACs and the client-authentication algorithms (``_preferred_pubkeys``) stay stock: the collector
    authenticates by password and never signs anything.

    Host-key order, precisely: the tier's plain name follows every stock PLAIN host-key name; paramiko's
    ``preferred_keys`` property then appends a certificate variant of each plain name after all of them, so the
    tier's certificate name is offered without ever being listed here (it is a ``_key_info`` key only).

    Each table is a NEW tuple or a NEW frozen mapping COPIED from the stock one; nothing is written into
    ``Transport``. ``dict.fromkeys`` keeps the first occurrence of a name, so a name the stock table already holds
    (paramiko older than 5) is not listed twice; that environment is refused before any connection anyway
    (:func:`default_permits_sha1`)."""

    _preferred_kex = tuple(dict.fromkeys(tuple(Transport._preferred_kex) + LEGACY_SHA1_TIER_KEX))
    _kex_info = MappingProxyType({
        **Transport._kex_info,
        _KEX_GROUP14_SHA1: LegacyKexGroup14SHA1,
        _KEX_GEX_SHA1: LegacyKexGexSHA1,
    })
    _preferred_keys = tuple(dict.fromkeys(tuple(Transport._preferred_keys) + (_HOST_KEY_RSA_SHA1,)))
    _key_info = MappingProxyType({
        **Transport._key_info,
        _HOST_KEY_RSA_SHA1: LegacySHA1RSAKey,
        _HOST_KEY_RSA_SHA1_CERT: LegacySHA1RSAKey,
    })


_TRANSPORT_BY_PROFILE = MappingProxyType({LEGACY_SHA1_PROFILE: LegacySHA1Transport})


class LegacyTransportUnavailable(RuntimeError):
    """The legacy tier cannot honour consent in this environment (see :func:`default_permits_sha1`)."""


def default_permits_sha1() -> bool:
    """True when this environment's STOCK paramiko already negotiates SHA-1 for every device.

    That is paramiko older than 5, an install that requested ``netmiko[par4]``, or one installed with
    ``--no-deps``. The one owner of the test is ``cisco_toolkit.ssh_session.permits_sha1(transport_cls,
    rsakey_cls)``; this wrapper hands it frozen COPIES of paramiko's stock tables (the network-free owner cannot
    import paramiko itself, and the stock classes are never passed anywhere)."""
    stock_transport = SimpleNamespace(
        _preferred_kex=tuple(Transport._preferred_kex),
        _preferred_keys=tuple(Transport._preferred_keys),
        _kex_info=MappingProxyType({**Transport._kex_info}),
        _key_info=MappingProxyType({**Transport._key_info}),
    )
    stock_rsakey = SimpleNamespace(HASHES=MappingProxyType({**RSAKey.HASHES}))
    return bool(permits_sha1(stock_transport, stock_rsakey))


def transport_for(profile: str) -> type:
    """The frozen transport class for a NON-default effective profile.

    The collector's resolver calls this only for an effective-legacy device; the default profile is the
    collector's own observed stock transport, so asking this module for it is a programming error. Refuses
    when the stock tables already permit SHA-1: a legacy profile would then add nothing and would blur what
    consent means (the run-level preflight refuses that environment before any connection; this is the
    same rule at the last seam)."""
    if not isinstance(profile, str) or profile not in _TRANSPORT_BY_PROFILE:
        raise ValueError(
            f"no legacy transport for SSH profile {profile!r}; "
            f"legacy profiles: {sorted(_TRANSPORT_BY_PROFILE)}")
    if default_permits_sha1():
        raise LegacyTransportUnavailable(
            "this environment's paramiko already permits SHA-1 for every device (paramiko older than 5, "
            "or netmiko[par4]); the legacy profile would add nothing, so it is refused until the "
            "paramiko 5 re-lock")
    return _TRANSPORT_BY_PROFILE[profile]


# ------------------------------------------------------------------- weakness declaration ---
#: First-party declaration of the one cryptographic weakness this module exists to permit. pip-audit
#: matches distributions against advisories and cannot see first-party code, so the weakness is declared
#: here, registered in ``docs/ssot.md``, and kept confined by the ``legacy_ssh_confined`` claim.
WEAKNESS_DECLARATION = MappingProxyType({
    "schema": "first_party_weakness_declaration/1",
    "cwe": "CWE-327",
    "weakness": ("SHA-1 in the SSH key-exchange hash and in the RSA host-key signature "
                 "(collision-sensitive uses)"),
    "upstream_class_reference": "PYSEC-2026-2858",
    "upstream_aliases": ("CVE-2026-44405", "GHSA-r374-rxx8-8654"),
    "scope": MappingProxyType({
        "module": "cisco_toolkit/legacy_ssh.py",
        "profile": LEGACY_SHA1_PROFILE,
        "kex": LEGACY_SHA1_TIER_KEX,
        "host_key": LEGACY_SHA1_TIER_HOST_KEYS,
        "dh_floor_bits": DH_FLOOR_BITS,
        "default_path": "never: the default profile uses the stock paramiko 5 tables",
    }),
    "consent_rule": ("both levels must name the device: its devices.json row sets ssh_profile to the "
                     "legacy profile AND the run's --allow-legacy-ssh names its hostname or IP; the "
                     "eligible hosts are printed and recorded before the first connection; never "
                     "inferred from a failure and never retried"),
    "disclosure": ("snapshot ssh_sessions row (sha1, status, effective_profile)",
                   "ssh-legacy-transport software-risk finding",
                   "Collection Transport workbook sheet",
                   "run manifest ssh_transport_consent block",
                   "published attestation claim legacy_ssh_confined"),
    "validation": "CI-validated, not field-validated",
})
