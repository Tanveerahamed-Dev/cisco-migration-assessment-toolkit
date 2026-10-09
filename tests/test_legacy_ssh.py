"""W59 PR-2: the opt-in legacy SSH transport tier (``cisco_toolkit/legacy_ssh.py``).

Design: ``docs/w59-legacy-ssh-design-2026-10-09.md`` §4.1, §7 and the §8 test plan. Each test names the
design row it implements and the regression it must catch:

* T1 (legacy half)  -- pristine stock tables (in this process AND in a fresh interpreter that snapshots them
                       BEFORE the tier is imported); frozen legacy tables; SHA-1 appended LAST; nothing global;
                       every tier name the vocabulary owner's own object, never rebuilt.
* T2                -- isolation: a default-only run never imports the tier; a mixed concurrent run
                       gives each connection its own transport class.
* T3 (legacy half)  -- interop with a SHA-1-only server establishes over the SHA-1 exchange hash.
* T4                -- preference: a server offering SHA-1 AND SHA-2 negotiates SHA-2 even when opted in.
* T5                -- the 2048-bit group-exchange floor refuses BEFORE ``KEXDH_GEX_INIT``, once.
* T10               -- SSH SHA-1 identifiers stay confined among every shipped ``.py`` file.

Independent peers. T5 needs no third-party server: a raw RFC 4419 responder in this interpreter speaks
the cleartext half of the handshake (version, KEXINIT, GEX request/group), built on W59 PR-1's stdlib wire helpers
(``tests/ssh_fixture/raw_peer.py``), and records everything the client sends after the group. T2/T3/T4 interoperate
with W59 PR-1's fixture: an asyncssh server run as a SUBPROCESS from its own hash-pinned virtualenv
(``tools/requirements-ssh-fixture-test.txt``), launched by PR-1's ``fixture_server`` (``tests/ssh_fixture/launcher.py``,
a helper module, not a test module) with PR-1's contract
(``ATLAS_SSH_FIXTURE_PYTHON``; ``ATLAS_SSH_FIXTURE_REQUIRED=1`` on the hosted legs makes a missing fixture FAIL
rather than skip). This module never imports asyncssh, and every fixture profile it relies on is proven on the wire
(``probe_kexinit``) first.

The legacy tier refuses an environment whose STOCK paramiko already permits SHA-1 (paramiko older than 5). The
tests that drive it therefore require the paramiko-5 floating environment: on the hosted test job they assert,
anywhere else (a workstation holding the bundle's paramiko 4.0.0) they skip visibly, naming what they saw.

Never run locally (standing hosted-only rule); every algorithm list a test relies on is pinned exactly.
"""
import ast
import json
import os
import socket
import struct
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import MappingProxyType

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import paramiko                                                    # noqa: E402
from paramiko.kex_gex import KexGexSHA256                          # noqa: E402
from paramiko.kex_group14 import KexGroup14SHA256                  # noqa: E402
from paramiko.rsakey import RSAKey                                 # noqa: E402
from paramiko.transport import Transport                           # noqa: E402

import COLLECT_PARSE_V3_23_0 as C                                  # noqa: E402
from cisco_toolkit import legacy_ssh as L                          # noqa: E402
from cisco_toolkit import ssh_session as S                         # noqa: E402
from cisco_toolkit.attestation import SSH_SHA1_ALGORITHM, ssh_sha1_literals  # noqa: E402
from ssh_fixture.raw_peer import (                                 # noqa: E402
    kexinit_names, kexinit_payload, packet, parse_kexinit, probe_kexinit, read_payload, read_version_line)
from ssh_fixture.launcher import fixture_server                   # noqa: E402
from ssh_structural_support import parse_source, shipped_python_files  # noqa: E402

#: RFC 2409 §6.2 Second Oakley Group: the 1024-bit MODP prime (a published RFC constant). A server that
#: answers group exchange with it is exactly the weak group the legacy floor exists to refuse.
RFC2409_GROUP2_PRIME = int(
    "FFFFFFFFFFFFFFFFC90FDAA22168C234C4C6628B80DC1CD129024E088A67CC74020BBEA63B139B22514A08798E3404DD"
    "EF9519B3CD3A431B302B0A6DF25F14374FE1356D6D51C245E485B576625E7EC6F44C42E9A637ED6B0BFF5CB6F406B7ED"
    "EE386BFB5A899FA5AE9F24117C4B1FE649286651ECE65381FFFFFFFFFFFFFFFF", 16)

_G14_SHA1, _GEX_SHA1 = S.LEGACY_SHA1_TIER_KEX
_RSA_SHA1, _RSA_SHA1_CERT = S.LEGACY_SHA1_TIER_HOST_KEYS
#: The hosted test job's flag (.github/workflows/ci.yml): set there, and only there, on the provisioned
#: paramiko-5 floating environment (W59 PR-1's T7 holds that environment to "stock tables permit no SHA-1").
_HOSTED_FLOATING_ENV_FLAG = "ATLAS_SSH_FIXTURE_REQUIRED"
_LEGACY_CONSENT = {"device_profile": S.LEGACY_SHA1_PROFILE, "run_flag_profile": S.LEGACY_SHA1_PROFILE,
                   "named_on_run_flag": True, "effective_profile": S.LEGACY_SHA1_PROFILE}


def _require_sha2_only_paramiko():
    """The tier refuses a paramiko whose stock tables already permit SHA-1. Assert the paramiko-5 floating
    environment on the hosted job; skip visibly anywhere else."""
    if not L.default_permits_sha1():
        return
    if os.environ.get(_HOSTED_FLOATING_ENV_FLAG) == "1":
        pytest.fail("the hosted floating environment's stock paramiko permits SHA-1; the legacy tier refuses it")
    pytest.skip(f"this paramiko {getattr(paramiko, '__version__', '?')} already permits SHA-1, so the legacy "
                f"tier refuses it by design; asserted on the hosted job ({_HOSTED_FLOATING_ENV_FLAG}=1)")


@pytest.fixture(autouse=True)
def _no_backoff(monkeypatch):
    monkeypatch.setattr(C, "CONNECT_BACKOFF_BASE", 0)


def _recorder(profile, path=None):
    consent = _LEGACY_CONSENT if profile == S.LEGACY_SHA1_PROFILE else S.consent_for({"hostname": "lab-sw1"})
    return S.SessionRecorder(path, consent=consent, library=C._ssh_library_block(profile))


# ======================================================== T5: a raw RFC 4419 group-exchange responder ===
def _mpint(n):
    raw = n.to_bytes((n.bit_length() + 8) // 8, "big")
    return struct.pack(">I", len(raw)) + raw


class _GexResponder:
    """A raw RFC 4419 group-exchange responder: version, KEXINIT (group-exchange-SHA-1 only), and a
    KEXDH_GEX_GROUP carrying ``prime``. It then records the type of every packet the client sends, so a
    test can prove that nothing (no ``KEXDH_GEX_INIT`` = 32, no service/auth request) followed the group.
    No cryptography is needed: the floor refusal happens before anything is encrypted.

    W59 PR-2 review (P1-b): COMPOSITION, not a ``threading.Thread`` subclass. The subclass set ``self._stop`` to
    an Event, shadowing ``Thread._stop`` (a method ``join()`` calls on Python 3.10-3.12), so ``join()`` raised
    TypeError. The serving loop now runs on a plain ``threading.Thread(target=...)`` and the stop signal is a
    separately named Event, the shape W59 PR-1's ``RawResponder`` uses."""

    def __init__(self, prime):
        self.prime = prime
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(8)
        self.listener.settimeout(0.2)
        self.port = self.listener.getsockname()[1]
        self.accepts = 0
        self.client_kexinit = None
        self.gex_request = None
        self.after_group = []
        self.served = threading.Event()      # set once a connection has been read to its end
        self._halt = threading.Event()
        self._thread = threading.Thread(target=self._run, name="w59-gex-responder", daemon=True)

    def start(self):
        self._thread.start()
        return self

    def _run(self):
        while not self._halt.is_set():
            try:
                conn, _ = self.listener.accept()
            except (socket.timeout, OSError):
                continue
            self.accepts += 1
            with conn:
                self._serve(conn)
            self.served.set()

    def _serve(self, conn):
        conn.settimeout(15)
        try:
            conn.sendall(b"SSH-2.0-W59GexResponder_1.0\r\n")
            read_version_line(conn)
            self.client_kexinit = parse_kexinit(read_payload(conn))
            conn.sendall(packet(kexinit_payload([_GEX_SHA1], [_RSA_SHA1], ["aes128-ctr"], ["hmac-sha2-256"])))
            request = read_payload(conn)
            if request[0] == 34:                            # SSH_MSG_KEX_DH_GEX_REQUEST
                self.gex_request = struct.unpack(">III", request[1:13])
            conn.sendall(packet(bytes([31]) + _mpint(self.prime) + _mpint(2)))   # KEX_DH_GEX_GROUP
            while True:
                self.after_group.append(read_payload(conn)[0])
        except (EOFError, OSError, ValueError, struct.error):
            return

    def stop(self):
        self._halt.set()
        self._thread.join(timeout=5)
        self.listener.close()


@pytest.fixture
def gex_responder():
    responder = _GexResponder(RFC2409_GROUP2_PRIME).start()
    try:
        yield responder
    finally:
        responder.stop()


def test_p1b_the_gex_responder_starts_and_stops_cleanly():
    """W59 PR-2 review (P1-b). Catches: the responder shadowing ``threading.Thread._stop`` again (``join()`` then
    raised TypeError on Python 3.10-3.12, and every T5 wire test errored in teardown)."""
    responder = _GexResponder(RFC2409_GROUP2_PRIME).start()
    responder.stop()
    assert not responder._thread.is_alive()
    assert not isinstance(responder, threading.Thread)
    assert "_stop" not in vars(responder)


# ======================================================================== shared interop helpers ===
def _transport_of(dev):
    transport = dev.remote_conn.get_transport()
    assert transport is not None and transport.is_active()
    return transport


def _connect(port, profile):
    """The collector's REAL connection path (`connect_device` -> `_open_connection`) under ``profile``."""
    recorder = _recorder(profile)
    dev, _platform = C.connect_device("127.0.0.1", "lab-sw1", "lab", "lab", "ios", session=recorder, port=port)
    return dev, recorder


def _probe(port, kex, host_keys):
    """Non-vacuity: the fixture's OWN cleartext KEXINIT, so "SHA-1-only" is proven, not assumed (as sets: the
    server's advertised order is its own business; the client's order decides, RFC 4253 section 7.1)."""
    lists = probe_kexinit("127.0.0.1", port)
    assert set(kexinit_names(lists, "kex")) == set(kex), lists
    assert set(lists["host_key"]) == set(host_keys), lists


# =============================================================== T1: pristine, frozen, appended ===
_STOCK_TABLES = (
    (Transport, "_preferred_kex"), (Transport, "_kex_info"), (Transport, "_preferred_keys"),
    (Transport, "_key_info"), (Transport, "_preferred_pubkeys"), (Transport, "_preferred_ciphers"),
    (Transport, "_preferred_macs"), (RSAKey, "HASHES"), (KexGexSHA256, "min_bits"),
    (KexGroup14SHA256, "hash_algo"),
)


def _snapshot_stock():
    return {(owner.__name__, attr): (id(owner.__dict__[attr]) if attr in owner.__dict__ else None,
                                     _frozen_copy(getattr(owner, attr)))
            for owner, attr in _STOCK_TABLES}


def _frozen_copy(value):
    return dict(value) if hasattr(value, "items") else value


def test_t1_stock_tables_stay_pristine_when_legacy_transports_are_built():
    """Mutation caught: any write into an inherited table (``Transport._kex_info[...] = ...``,
    ``t._kex_info.update(...)``), which would open SHA-1 for every thread and every device."""
    _require_sha2_only_paramiko()
    before = _snapshot_stock()
    a, b = socket.socketpair()
    try:
        transport = L.LegacySHA1Transport(a)
        cls = L.transport_for(L.LEGACY_SHA1_PROFILE)
        assert cls is L.LegacySHA1Transport and isinstance(transport, Transport)
        # the instance reads the CLASS tables; nothing is copied per instance
        for attr in ("_preferred_kex", "_kex_info", "_preferred_keys", "_key_info"):
            assert attr not in vars(transport), f"{attr} was copied onto the instance"
        transport.close()
    finally:
        a.close()
        b.close()
    assert L.default_permits_sha1() is False
    assert _snapshot_stock() == before, "a legacy transport mutated a stock paramiko table"


_FRESH_INTERPRETER_T1 = r"""
import json, socket, sys
sys.path.insert(0, sys.argv[1])
import paramiko
from paramiko.kex_gex import KexGexSHA256
from paramiko.kex_group14 import KexGroup14SHA256
from paramiko.rsakey import RSAKey
from paramiko.transport import Transport

OWNERS = {"Transport": Transport, "RSAKey": RSAKey, "KexGexSHA256": KexGexSHA256,
          "KexGroup14SHA256": KexGroup14SHA256}
ATTRS = [("Transport", a) for a in ("_preferred_kex", "_kex_info", "_preferred_keys", "_key_info",
                                     "_preferred_pubkeys", "_preferred_ciphers", "_preferred_macs",
                                     "_cipher_info", "_mac_info", "_compression_info")]
ATTRS += [("RSAKey", "HASHES"), ("KexGexSHA256", "min_bits"), ("KexGexSHA256", "hash_algo"),
          ("KexGroup14SHA256", "hash_algo")]


def snap():
    out = {}
    for owner, attr in ATTRS:
        cls = OWNERS[owner]
        value = getattr(cls, attr, None)
        shown = repr(sorted(value.items(), key=repr)) if hasattr(value, "items") else repr(value)
        out[owner + "." + attr] = [id(value), shown, attr in vars(cls)]
    out["paramiko.key_classes"] = [id(getattr(paramiko, "key_classes", None)),
                                   repr(getattr(paramiko, "key_classes", None)), True]
    return out


before = snap()
assert "cisco_toolkit.legacy_ssh" not in sys.modules
import cisco_toolkit.legacy_ssh as L
a, b = socket.socketpair()
t = L.LegacySHA1Transport(a)
t.close()
a.close()
b.close()
L.default_permits_sha1()
after = snap()
print(json.dumps({"file": L.__file__, "changed": sorted(k for k in before if before[k] != after[k])}))
"""


def test_t1_fresh_interpreter_stock_tables_are_identical_before_and_after_the_tier_loads():
    """W59 PR-2 review (P2-c). In a FRESH interpreter, snapshot the identity and the equality of every stock table
    BEFORE ``cisco_toolkit.legacy_ssh`` is imported, then import it, build a ``LegacySHA1Transport`` and run its
    probe, and compare. Catches what an in-process snapshot cannot: a mutation made at IMPORT time (this test
    session imported the tier long before any snapshot), including through an alias, an unbound ``dict.update``,
    ``operator.setitem`` or ``type.__setattr__``."""
    out = subprocess.run([sys.executable, "-c", _FRESH_INTERPRETER_T1, str(ROOT)], capture_output=True,
                         text=True, cwd=str(ROOT), timeout=300)
    assert out.returncode == 0, out.stderr[-4000:]
    result = json.loads(out.stdout.strip().splitlines()[-1])
    assert Path(result["file"]).resolve().is_relative_to(ROOT), result["file"]
    assert result["changed"] == [], f"importing or using the legacy tier changed stock tables: {result['changed']}"


def test_t1_legacy_tables_are_new_frozen_and_append_sha1_last():
    """Mutations caught: a table defined as a plain dict/list (mutable shared state); SHA-1 entries
    PREPENDED (they would then win against a device that also offers SHA-2); the certificate name listed in
    ``_preferred_keys`` (paramiko's ``preferred_keys`` property appends every plain name's certificate variant
    itself, so it belongs to ``_key_info`` only)."""
    _require_sha2_only_paramiko()
    T = L.LegacySHA1Transport
    assert type(T._kex_info) is MappingProxyType and type(T._key_info) is MappingProxyType
    assert type(L.LegacySHA1RSAKey.HASHES) is MappingProxyType
    assert type(T._preferred_kex) is tuple and type(T._preferred_keys) is tuple
    assert T._kex_info is not Transport._kex_info and T._key_info is not Transport._key_info

    stock_kex, stock_keys = Transport._preferred_kex, Transport._preferred_keys
    assert not set(S.LEGACY_SHA1_TIER_KEX) & set(stock_kex), "stock paramiko already offers the tier"
    assert T._preferred_kex == tuple(stock_kex) + tuple(S.LEGACY_SHA1_TIER_KEX)
    assert T._preferred_keys == tuple(stock_keys) + (_RSA_SHA1,)
    assert _RSA_SHA1_CERT not in T._preferred_keys
    # RFC 9142 Table 12 order inside the tier: the fixed group (MAY) before the exchange (SHOULD NOT)
    assert T._kex_info[_G14_SHA1] is L.LegacyKexGroup14SHA1
    assert T._kex_info[_GEX_SHA1] is L.LegacyKexGexSHA1
    for name in stock_kex:
        assert T._kex_info[name] is Transport._kex_info[name], f"stock kex {name} was replaced"
    assert T._key_info[_RSA_SHA1] is L.LegacySHA1RSAKey
    assert T._key_info[_RSA_SHA1_CERT] is L.LegacySHA1RSAKey
    for name, key_cls in Transport._key_info.items():
        if name not in S.LEGACY_SHA1_TIER_HOST_KEYS:
            assert T._key_info[name] is key_cls, f"stock host-key {name} was replaced"
    assert set(RSAKey.HASHES.items()) < set(L.LegacySHA1RSAKey.HASHES.items())
    # ciphers, MACs and client-auth algorithms stay stock (inherited, not redefined)
    for attr in ("_preferred_pubkeys", "_preferred_ciphers", "_preferred_macs", "_cipher_info",
                 "_mac_info"):
        assert attr not in vars(T) and getattr(T, attr) is getattr(Transport, attr)
    # and the client OFFERS the certificate variant after every plain name (paramiko's own property)
    a, b = socket.socketpair()
    try:
        transport = L.LegacySHA1Transport(a)
        offered = transport.preferred_keys
        transport.close()
    finally:
        a.close()
        b.close()
    assert offered.index(_RSA_SHA1) < offered.index(_RSA_SHA1_CERT)


def test_p3i_every_tier_name_is_the_vocabulary_owners_own_object():
    """W59 PR-2 review (P3-i). Catches: a SHA-1 name REBUILT inside the tier (``plain + "-cert-v01@openssh.com"``,
    an f-string, a join): every name the tier adds to a table must be the very string object the vocabulary owner
    holds, and the module source carries no fragment such a name could be built from."""
    def added(tier_table, stock_table):
        return [n for n in tier_table if n not in stock_table]

    T = L.LegacySHA1Transport
    names = (added(T._preferred_kex, Transport._preferred_kex) + added(T._kex_info, Transport._kex_info)
             + added(T._preferred_keys, Transport._preferred_keys) + added(T._key_info, Transport._key_info)
             + added(L.LegacySHA1RSAKey.HASHES, RSAKey.HASHES))
    owned = S.LEGACY_SHA1_TIER_KEX + S.LEGACY_SHA1_TIER_HOST_KEYS
    if not L.default_permits_sha1():
        assert names, "the tier added nothing; this identity check proves nothing"
    for name in names:
        assert any(name is o for o in owned), f"{name!r} is not the vocabulary owner's own object"
    tree = parse_source(ROOT / "cisco_toolkit" / "legacy_ssh.py")
    fragments = ("cert-v01", "openssh.com", "-sha1", "diffie-hellman-", "ssh-rsa", "ssh-dss", "x509v3-")
    built = [(n.lineno, f) for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)
             for f in fragments if f in n.value]
    assert built == [], f"name fragments in cisco_toolkit/legacy_ssh.py: {built}"


def test_t1_legacy_classes_override_only_their_declared_members():
    """Mutation caught: a second overridden protocol method sneaking into the tier (anything beyond
    the tables, the two kex attributes, the floor and the one floor check)."""
    def own(cls):
        return {k for k in vars(cls) if not (k.startswith("__") and k.endswith("__"))}

    assert own(L.LegacySHA1Transport) == {"_preferred_kex", "_kex_info", "_preferred_keys", "_key_info"}
    assert own(L.LegacyKexGroup14SHA1) == {"name", "hash_algo"}
    assert own(L.LegacyKexGexSHA1) == {"name", "hash_algo", "floor_bits", "_parse_kexdh_gex_group"}
    assert own(L.LegacySHA1RSAKey) == {"HASHES"}
    assert L.LegacyKexGroup14SHA1.P == KexGroup14SHA256.P, "the RFC 3526 group 14 prime must be inherited"
    assert L.LegacyKexGexSHA1.floor_bits == L.DH_FLOOR_BITS == S.DH_FLOOR_BITS == 2048
    assert issubclass(L.LegacySHA1Transport, S.ObservingTransportMixin), "the legacy path must be observed"
    # defining the key subclass registered nothing globally
    assert L.LegacySHA1RSAKey not in getattr(paramiko, "key_classes", [])


def test_transport_for_refuses_the_default_and_unknown_profiles():
    for bad in (L.DEFAULT_PROFILE, "nope", "", None, True):
        with pytest.raises(ValueError):
            L.transport_for(bad)


def test_transport_for_refuses_when_stock_paramiko_already_permits_sha1(monkeypatch):
    """Under paramiko < 5 (or netmiko[par4]) the opt-in would add nothing and blur what consent means."""
    monkeypatch.setattr(L, "default_permits_sha1", lambda: True)
    with pytest.raises(L.LegacyTransportUnavailable):
        L.transport_for(L.LEGACY_SHA1_PROFILE)


def test_p2d_default_permits_sha1_hands_the_owner_only_names_with_its_real_signature(monkeypatch):
    """W59 PR-2 review (P2-d), tightened in review round 3 (P2). Catches: the wrapper calling
    ``ssh_session.permits_sha1`` with a signature it does not have (three positional tables; it takes
    ``(transport_cls, rsakey_cls=None)``); the stock classes themselves handed out; and -- round 3 -- any class a
    stock table maps a name to (a key-exchange engine, a key class) handed out inside a copy. Only the NAMES leave
    the tier, as frozen tuples, and the owner's answer is the one it gives on the real classes."""
    seen = []

    def spy(transport_cls, rsakey_cls=None):
        seen.append((transport_cls, rsakey_cls))
        return S.permits_sha1(transport_cls, rsakey_cls)

    monkeypatch.setattr(L, "permits_sha1", spy)
    answer = L.default_permits_sha1()
    assert answer is S.permits_sha1(Transport, RSAKey)
    ((stock_transport, stock_rsakey),) = seen
    assert stock_transport is not Transport and stock_rsakey is not RSAKey
    handed = {attr: getattr(stock_transport, attr)
              for attr in ("_preferred_kex", "_preferred_keys", "_kex_info", "_key_info")}
    handed["HASHES"] = stock_rsakey.HASHES
    for attr, names in handed.items():
        stock = RSAKey.HASHES if attr == "HASHES" else getattr(Transport, attr)
        assert type(names) is tuple and names == tuple(stock), attr       # the names, in the stock order
        assert all(type(n) is str for n in names), attr                    # no class or callable crosses
    assert set(vars(stock_transport)) == {"_preferred_kex", "_preferred_keys", "_kex_info", "_key_info"}
    assert set(vars(stock_rsakey)) == {"HASHES"}


# ========================================================================== T5: the GEX floor ===
class _RecordingKexTransport:
    """The slice of a Transport a group-exchange engine touches while parsing the server's group."""
    server_mode = False

    def __init__(self):
        self.sent, self.expected = [], []

    def _log(self, *_args):
        pass

    def _send_message(self, m):
        self.sent.append(m.asbytes()[0])

    def _expect_packet(self, *ptypes):
        self.expected.append(ptypes)


def _group_message(prime):
    m = paramiko.Message()
    m.add_mpint(prime)
    m.add_mpint(2)
    m.rewind()
    return m


def test_t5_floor_refuses_a_1024_bit_group_before_sending_the_key_share():
    """Mutations caught: the floor removed; the check placed AFTER ``super()`` (paramiko's own parse
    sends KEXDH_GEX_INIT in the same method); a plain SSHException instead of IncompatiblePeer."""
    transport = _RecordingKexTransport()
    engine = L.LegacyKexGexSHA1(transport)
    with pytest.raises(L.WeakGroupRefused) as info:
        engine._parse_kexdh_gex_group(_group_message(RFC2409_GROUP2_PRIME))
    assert transport.sent == [], f"the client answered a weak group: sent packet types {transport.sent}"
    assert info.value.offered_bits == 1024 and info.value.floor_bits == 2048
    assert isinstance(info.value, paramiko.ssh_exception.IncompatiblePeer)
    assert engine.p is None, "the weak prime was adopted before the refusal"
    # PR-1's classifier recognises it by NAME and records refused_weak_dh with the offered size
    refusal = S.classify_failure(info.value, None)
    assert (refusal["classification"], refusal["offered_group_bits"]) == ("refused_weak_dh", 1024)


def test_t5_floor_accepts_a_2048_bit_group_and_delegates_to_paramiko():
    """Negative control: at the floor, paramiko's own parse runs and sends KEXDH_GEX_INIT (32)."""
    transport = _RecordingKexTransport()
    engine = L.LegacyKexGexSHA1(transport)
    engine._parse_kexdh_gex_group(_group_message(KexGroup14SHA256.P))
    assert transport.sent == [32] and engine.p.bit_length() == 2048


def test_t5_wire_refusal_is_one_attempt_with_nothing_sent_after_the_group(gex_responder, monkeypatch):
    """Over a real loopback socket through the collector's own retry loop: exactly ONE connection,
    the client requested at least 2048 bits, offered the SHA-1 tier LAST, and after the 1024-bit group
    sent no KEXDH_GEX_INIT (32), no service request (5) and no authentication (50). The record holds the
    classified ``refused_weak_dh`` refusal (PR-1's classifier), never a retried timeout."""
    _require_sha2_only_paramiko()
    original = C._open_connection
    calls = []

    def _counting(kwargs, platform, profile, recorder):
        calls.append(profile)
        return original(kwargs, platform, profile, recorder)

    monkeypatch.setattr(C, "_open_connection", _counting)
    dev, recorder = _connect(gex_responder.port, L.LEGACY_SHA1_PROFILE)
    assert dev is None
    assert calls == [L.LEGACY_SHA1_PROFILE], f"a deterministic refusal was retried: {calls}"
    assert gex_responder.served.wait(20), "the responder never saw the client close the connection"
    assert gex_responder.accepts == 1
    assert gex_responder.gex_request is not None and gex_responder.gex_request[0] >= 2048
    assert not {32, 5, 50} & set(gex_responder.after_group), gex_responder.after_group
    offered_kex = kexinit_names(gex_responder.client_kexinit, "kex")
    assert offered_kex[-len(S.LEGACY_SHA1_TIER_KEX):] == list(S.LEGACY_SHA1_TIER_KEX), offered_kex
    assert offered_kex[:-len(S.LEGACY_SHA1_TIER_KEX)] == list(Transport._preferred_kex)
    record = recorder.record
    assert record["outcome"] == "negotiation_refused" and record["attempts"] == 1
    assert (record["refusal"]["classification"], record["refusal"]["offered_group_bits"]) == ("refused_weak_dh", 1024)


# =================================================================== T3 / T4 / T5: interop ===
def test_t3_legacy_profile_establishes_with_a_sha1_only_server(tmp_path):
    """Mutations caught: the SHA-1 entries dropped from the tier (no common kex); the exchange hash not
    actually SHA-1 (the independent server would reject the signature over a different hash); the session
    not observed or not disclosed as an opted-in SHA-1 session."""
    _require_sha2_only_paramiko()
    with fixture_server(tmp_path, "sha1-only") as (port, _log):
        _probe(port, [_G14_SHA1], [_RSA_SHA1])
        dev, recorder = _connect(port, L.LEGACY_SHA1_PROFILE)
        try:
            assert dev is not None
            transport = _transport_of(dev)
            assert isinstance(transport, L.LegacySHA1Transport)
            assert transport.host_key_type == _RSA_SHA1
            assert len(transport.session_id) == 20, "the exchange hash was not SHA-1"
            neg = recorder.record["negotiated"]
            assert (neg["kex"], neg["kex_hash_bytes"], neg["dh_group_bits"], neg["host_key_algorithm"]) == \
                (_G14_SHA1, 20, 2048, _RSA_SHA1)
            assert recorder.record["library"]["transport_class"] == "LegacySHA1Transport"
            row = S.derive_row("lab-sw1", S.render_record(recorder.record), evidence="lab-sw1/x", live=True)
            assert row["status"] == "legacy_sha1" and "by explicit opt-in" in row["label"]
        finally:
            if dev is not None:
                dev.disconnect()


def test_t4_opted_in_device_offering_sha2_negotiates_sha2(tmp_path):
    """Mutation caught: the SHA-1 tier PREPENDED to the stock list."""
    _require_sha2_only_paramiko()
    with fixture_server(tmp_path, "sha1-and-sha2") as (port, _log):
        _probe(port, ["diffie-hellman-group14-sha256", _G14_SHA1], ["rsa-sha2-256", _RSA_SHA1])
        dev, recorder = _connect(port, L.LEGACY_SHA1_PROFILE)
        try:
            assert dev is not None
            transport = _transport_of(dev)
            assert isinstance(transport, L.LegacySHA1Transport)
            assert len(transport.session_id) == 32, "SHA-1 was chosen although SHA-2 was offered"
            assert transport.host_key_type == "rsa-sha2-256"
            row = S.derive_row("lab-sw1", S.render_record(recorder.record), evidence="lab-sw1/x", live=True)
            assert row["status"] == "modern"
        finally:
            if dev is not None:
                dev.disconnect()


def test_t5_stock_2048_bit_group_exchange_is_accepted_under_the_legacy_profile(tmp_path):
    """Negative control for the floor over a real independent server: group exchange at 2048 bits or more
    negotiates and the exchange hash is SHA-1."""
    _require_sha2_only_paramiko()
    with fixture_server(tmp_path, "sha1-gex-only") as (port, _log):
        _probe(port, [_GEX_SHA1], [_RSA_SHA1])
        dev, recorder = _connect(port, L.LEGACY_SHA1_PROFILE)
        try:
            assert dev is not None
            assert len(_transport_of(dev).session_id) == 20
            neg = recorder.record["negotiated"]
            assert neg["kex"] == _GEX_SHA1 and neg["dh_group_bits"] >= S.DH_FLOOR_BITS
        finally:
            if dev is not None:
                dev.disconnect()


# ============================================================================== T2: isolation ===
def test_t2_default_only_run_never_imports_the_legacy_tier():
    """Mutation caught: an eager ``import cisco_toolkit.legacy_ssh`` anywhere on the default path
    (collector, consent resolution, preflight, the real connection factory, attestation). Run in a
    FRESH interpreter so this test session's own import of the tier cannot mask it. Every socket
    connect is refused in-process (TEST-NET-1 addresses, never a reachable host), so the real factory and
    netmiko run their default path to the first connect and stop there."""
    script = f"""
import json, socket, sys
sys.path.insert(0, {str(ROOT)!r})

def _refuse(self, address):
    raise ConnectionRefusedError("blocked by test_t2 (no network in this test)")

socket.socket.connect = _refuse
import COLLECT_PARSE_V3_23_0 as C

C.CONNECT_MAX_ATTEMPTS = 1
rows = [dict(hostname="lab-sw1", ip="192.0.2.1", username="u", password="p", platform="ios",
             ssh_profile="legacy-sha1"),
        dict(hostname="lab-sw2", ip="192.0.2.2", username="u", password="p", platform="nxos")]
devices = C.load_devices("devices.json", _bound_bytes=json.dumps(rows).encode())
block = C._resolve_ssh_consent(devices, None)          # row requests it, run does not name it
assert block["devices_eligible"] == [] and block["requested_not_named"] == ["lab-sw1"], block
assert C._legacy_ssh_preflight(block) is None
C._log_ssh_consent(block)
for d in devices:
    assert d["ssh_consent"]["effective_profile"] == "default", d["ssh_consent"]
    recorder = C._session_recorder_for(d, None)
    dev, _ = C.connect_device(d["ip"], d["hostname"], "u", "p", d["platform"], session=recorder)
    assert dev is None
from cisco_toolkit.attestation import compute_attestation
compute_attestation()
leaked = sorted(m for m in sys.modules if m.endswith("legacy_ssh"))
print(json.dumps(leaked))
"""
    out = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, cwd=str(ROOT),
                         timeout=600)
    assert out.returncode == 0, out.stderr[-4000:]
    assert json.loads(out.stdout.strip().splitlines()[-1]) == [], "the default path imported the tier"


def test_t2_concurrent_mixed_run_gives_each_connection_its_own_transport(tmp_path):
    """Mutation caught: a transport class or binding shared through mutable state, so one worker's
    profile leaks into the other's connection."""
    _require_sha2_only_paramiko()
    with fixture_server(tmp_path, "sha1-only") as (old_port, _l1), \
            fixture_server(tmp_path, "modern") as (new_port, _l2):
        jobs = [(old_port, L.LEGACY_SHA1_PROFILE), (new_port, L.DEFAULT_PROFILE)] * 2

        def _one(job):
            port, profile = job
            dev, recorder = _connect(port, profile)
            try:
                assert dev is not None
                t = _transport_of(dev)
                return profile, isinstance(t, L.LegacySHA1Transport), len(t.session_id), \
                    recorder.record["consent"]["effective_profile"]
            finally:
                if dev is not None:
                    dev.disconnect()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(_one, jobs))
    for profile, is_legacy, hash_len, recorded in results:
        assert recorded == profile
        if profile == L.LEGACY_SHA1_PROFILE:
            assert is_legacy and hash_len == 20
        else:
            assert not is_legacy and hash_len == 32


# ============================================================== T10: identifier confinement ===
_DECLARED_GIT_BLOB_SHA1_SITES = {
    # git-blob object identities (SHA-1 is git's object format), not SSH cryptography
    "webapp/backend/observe_ui_projection_contract.py",
    "portable/release_contract.py",
}
_VOCABULARY = "cisco_toolkit/ssh_session.py"
_LEGACY = "cisco_toolkit/legacy_ssh.py"


def _module_aliases(tree, module):
    """Every local name bound to ``module`` itself (``import hashlib``, ``import hashlib as h``)."""
    return {alias.asname or alias.name for node in ast.walk(tree) if isinstance(node, ast.Import)
            for alias in node.names if alias.name == module}


def _tier_names():
    names = {n for n in vars(S) if n.startswith("LEGACY_SHA1_TIER_")}
    assert names == {"LEGACY_SHA1_TIER_KEX", "LEGACY_SHA1_TIER_HOST_KEYS"}, names   # non-vacuity
    return names


def _tier_sites(tree, tier):
    """Every read of a tier name, BY NAME, whatever owner alias reads it (W59 PR-2 review P3-f): an attribute
    (``S.LEGACY_SHA1_TIER_KEX``, ``vocab.LEGACY_SHA1_TIER_KEX``), an import from the vocabulary module (or a star
    import), a bare name, or the name as a string (``getattr(ssh_session, "LEGACY_SHA1_TIER_KEX")``)."""
    hits = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Attribute) and n.attr in tier:
            hits.append(n.lineno)
        elif isinstance(n, ast.Name) and n.id in tier:
            hits.append(n.lineno)
        elif isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value in tier:
            hits.append(n.lineno)
        elif isinstance(n, ast.ImportFrom) and (n.module or "").endswith("ssh_session") \
                and any(a.name in tier or a.name == "*" for a in n.names):
            hits.append(n.lineno)
    return hits


def test_t10_sha1_ssh_identifiers_are_confined_among_shipped_files():
    """Mutation caught: ``"ssh-rsa"`` (or any SHA-1 SSH algorithm name) added to a default-path
    module; the legacy-tier tuples read outside the tier, through any owner alias; SHA-1 hashing reached for
    outside it. The file set is W59 PR-1's shipped-source denominator (wheel runtime inventory plus the Atlas
    bundle's import closure), shared through ``tests/ssh_structural_support.py``."""
    files = shipped_python_files()
    assert _LEGACY in files and _VOCABULARY in files and "COLLECT_PARSE_V3_23_0.py" in files
    tier = _tier_names()
    literal_sites, tier_sites, sha1_attr_sites, hashlib_sites = {}, {}, {}, {}
    n_vocab = 0
    for rel in files:
        try:
            tree = parse_source(ROOT / rel)
        except (SyntaxError, UnicodeDecodeError):
            continue
        literals = ssh_sha1_literals(tree)
        if rel == _VOCABULARY:
            n_vocab = len(literals)
        elif literals:
            literal_sites[rel] = literals
        if rel not in (_VOCABULARY, _LEGACY):
            hits = _tier_sites(tree, tier)
            if hits:
                tier_sites[rel] = hits
        if rel != _LEGACY:
            # cryptography's SHA1 by attribute NAME, whatever the owner is called; hashlib.sha1 through any alias
            sha1 = [n.lineno for n in ast.walk(tree) if isinstance(n, ast.Attribute) and n.attr == "SHA1"]
            sha1 += [n.lineno for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)
                     and any(a.name == "SHA1" for a in n.names)]
            if sha1:
                sha1_attr_sites[rel] = sha1
            aliases = _module_aliases(tree, "hashlib")
            uses = [n.lineno for n in ast.walk(tree) if isinstance(n, ast.Attribute) and n.attr == "sha1"
                    and isinstance(n.value, ast.Name) and n.value.id in aliases]
            uses += [n.lineno for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module == "hashlib"
                     and any(a.name == "sha1" for a in n.names)]
            if uses and rel not in _DECLARED_GIT_BLOB_SHA1_SITES:
                hashlib_sites[rel] = uses
    assert not literal_sites, f"SSH SHA-1 algorithm literals outside the vocabulary owner: {literal_sites}"
    assert not tier_sites, f"legacy-tier vocabulary read outside cisco_toolkit/legacy_ssh.py: {tier_sites}"
    assert not sha1_attr_sites, f"cryptography SHA1 outside the legacy tier: {sha1_attr_sites}"
    assert not hashlib_sites, f"hashlib.sha1 outside the tier and the git-blob sites: {hashlib_sites}"
    # Non-vacuity: the shared grammar must recognise the very names it confines.
    assert n_vocab >= len(S.LEGACY_SHA1_TIER_KEX) + len(S.LEGACY_SHA1_TIER_HOST_KEYS), (
        "the SHA-1 SSH algorithm grammar no longer recognises the vocabulary's own names")
    planted = ast.parse('DEFAULT_KEYS = ("rsa-sha2-256", "ssh-rsa")\n')
    assert ssh_sha1_literals(planted) == [(1, "ssh-rsa")]
    assert ssh_sha1_literals(ast.parse('X = ("hmac-sha1", "diffie-hellman-group14-sha256")\n')) == []
    aliased = ast.parse("import cisco_toolkit.ssh_session as vocab\nX = vocab.LEGACY_SHA1_TIER_KEX\n"
                        "Y = getattr(vocab, 'LEGACY_SHA1_TIER_HOST_KEYS')\n")
    assert sorted(_tier_sites(aliased, tier)) == [2, 3]


def test_t10_every_sha1_boundary_name_of_the_owner_matches_the_independent_pattern():
    """W59 PR-2 review (P3-f). The attestation's pattern is deliberately independent of the vocabulary owner
    (proposer != verifier), so it must be HELD to the owner: every name in the owner's SHA-1 boundary (the
    key-exchange and host-key names, the RFC 6187 X.509 ones included) matches it, and so do the draft-era
    ``x509v3-sign-*`` names. Catches: a boundary name the confinement scan could not see."""
    missed = sorted(n for n in S.SHA1_BOUNDARY_NAMES if not SSH_SHA1_ALGORITHM.match(n))
    assert missed == [], f"SHA-1 boundary names the confinement pattern does not recognise: {missed}"
    assert {n for n in S.SHA1_HOST_KEY_NAMES if n.startswith("x509v3-")}, "no X.509 name left to hold it to"
    for name in ("x509v3-sign-rsa", "x509v3-sign-dss", "x509v3-ssh-rsa", "x509v3-ssh-dss"):
        assert SSH_SHA1_ALGORITHM.match(name), name
    for modern in ("x509v3-rsa2048-sha256", "rsa-sha2-256", "diffie-hellman-group14-sha256", "hmac-sha1"):
        assert not SSH_SHA1_ALGORITHM.match(modern), modern


@pytest.mark.parametrize("text,names", [
    # joined to a neighbour by any non-name character: each was missed by the round-2 delimiter list
    ("kex=diffie-hellman-group14-sha1", ["diffie-hellman-group14-sha1"]),
    ("ssh-rsa/ssh-dss", ["ssh-dss", "ssh-rsa"]),
    ("HostKeyAlgorithms:ssh-rsa", ["ssh-rsa"]),
    ("HostKeyAlgorithms=+ssh-rsa", ["ssh-rsa"]),
    ("#ssh-dss*", ["ssh-dss"]),
    ("kex=gss-gex-sha1-ab/cd==:next", ["gss-gex-sha1-ab/cd=="]),      # a GSS name's base64 tail is part of it
    # still found where round 2 found it
    ("negotiated ssh-rsa.", ["ssh-rsa"]),
    ("ssh-rsa-cert-v01@openssh.com", ["ssh-rsa-cert-v01@openssh.com"]),
    ("x509v3-ssh-rsa", ["x509v3-ssh-rsa"]),
    # controls: a longer word that contains a name, and the modern and MAC names, are not SHA-1 SSH names
    ("rsa-sha2-256", []), ("hmac-sha1", []), ("diffie-hellman-group14-sha256", []), ("id_ssh-rsa", []),
    ("ssh-rsa.pub", []), ("ssh-rsa2", []), ("x509v3-ssh-rsa2", []), ("ssh-rsa@example.com", []), ("mssh-rsa", []),
])
def test_t10_a_sha1_name_is_found_whatever_non_name_character_joins_it(text, names):
    """W59 PR-2 review round 3 (P3). Mutation caught: the shared SHA-1 name scan splitting string constants on a
    hand-kept delimiter class, so a name joined to its neighbour by '=', '/', ':' or any other character outside
    that class was never a literal (``"kex=diffie-hellman-group14-sha1"`` passed T10 and the published claim). A
    name is now matched as an anchored token bounded by any character that cannot continue it, and a longer word
    that merely contains one is still not a match."""
    assert [token for _line, token in ssh_sha1_literals(ast.parse(repr(text)))] == names


# ======================================================================= weakness declaration ===
def test_weakness_declaration_is_frozen_scoped_and_complete():
    """The first-party declaration pip-audit cannot produce: CWE-327, the upstream class, scope =
    the legacy profile only, the consent rule and the disclosure surfaces."""
    d = L.WEAKNESS_DECLARATION
    assert type(d) is MappingProxyType and type(d["scope"]) is MappingProxyType
    assert d["cwe"] == "CWE-327" and d["upstream_class_reference"] == "PYSEC-2026-2858"
    assert d["scope"]["profile"] == L.LEGACY_SHA1_PROFILE != L.DEFAULT_PROFILE
    assert tuple(d["scope"]["kex"]) == tuple(S.LEGACY_SHA1_TIER_KEX)
    assert tuple(d["scope"]["host_key"]) == tuple(S.LEGACY_SHA1_TIER_HOST_KEYS)
    assert d["scope"]["dh_floor_bits"] == L.DH_FLOOR_BITS == S.DH_FLOOR_BITS
    assert "--allow-legacy-ssh" in d["consent_rule"] and "ssh_profile" in d["consent_rule"]
    assert any("legacy_ssh_confined" in item for item in d["disclosure"])
    assert d["validation"] == "CI-validated, not field-validated"
