"""W59 PR-1: SSH session disclosure -- the owner (`cisco_toolkit.ssh_session`) and its collector seams.

Design: docs/w59-legacy-ssh-design-2026-10-09.md (sections 4.2-4.4, 5, 6 and the test plan in section 8). Every
test names the regression it catches. Nothing here opens a network connection to anything but a socketpair;
the loopback interop tests against an independent SSH server live in tests/test_ssh_session_interop.py.

Versions are NEVER asserted against the floating test environment (design section 8, critique P2-7): exact
versions are read only from the lock file's text. In the floating environment every seam is tested by
behaviour.
"""
from __future__ import annotations

import ast
import json
import re
import socket
import subprocess
import threading
import warnings
from pathlib import Path

import pytest

import COLLECT_PARSE_V3_23_0 as C
from cisco_toolkit import ssh_session as S

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "COLLECT_PARSE_V3_23_0.py"


# ------------------------------------------------------------------------------------------- helpers ---
def _lib(permits=False, paramiko="5.0.0", netmiko="4.8.0"):
    return S.library_block(paramiko_version=paramiko, netmiko_version=netmiko, transport_class="ObservedTransport",
                           default_permits_sha1=permits)


_DEFAULT_CONSENT = S.consent_for({"hostname": "sw1", "ip": "192.0.2.10"})
_LEGACY_CONSENT = {"device_profile": S.LEGACY_SHA1_PROFILE, "run_flag_profile": S.LEGACY_SHA1_PROFILE,
                   "named_on_run_flag": True, "effective_profile": S.LEGACY_SHA1_PROFILE}
_G14_SHA1, _GEX_SHA1 = S.LEGACY_SHA1_TIER_KEX
_RSA_SHA1 = S.LEGACY_SHA1_TIER_HOST_KEYS[0]
_HMAC_SHA1 = sorted(n for n in S.SHA1_MACS if "etm" not in n)[0]


def _observation(kex, hash_bytes, bits, host_key, mac="hmac-sha2-256", cipher="aes128-ctr", *,
                 engine_agrees=True, group_agrees=None, newkeys=True):
    server = {"kex": [kex], "host_key": [host_key], "cipher_c2s": [cipher], "cipher_s2c": [cipher],
              "mac_c2s": [mac], "mac_s2c": [mac]}
    client = {"kex": [kex, "ecdh-sha2-nistp256"], "host_key": [host_key, "rsa-sha2-512"], "cipher": [cipher],
              "mac": [mac, "hmac-sha2-512"]}
    return {"kexinit": True, "newkeys": newkeys, "server": server, "client": client,
            "negotiated": {"kex": kex, "kex_hash_bytes": hash_bytes, "dh_group_bits": bits,
                           "host_key_algorithm": host_key, "cipher_c2s": cipher, "cipher_s2c": cipher,
                           "mac_c2s": mac, "mac_s2c": mac, "strict_kex": False,
                           "server_software": "SSH-2.0-Cisco-1.25"} if newkeys else None,
            "engine_name_agrees": engine_agrees, "group_size_agrees": group_agrees, "dropped": 0}


def _row(record, *, live=True, eligible=()):
    return S.derive_row("sw1", S.render_record(record), evidence="sw1/_ssh_session.json", live=live,
                        eligible_hosts=eligible)


class _IncompatiblePeer(Exception):
    """paramiko's class NAME (the classifier matches by name and never imports paramiko)."""


_IncompatiblePeer.__name__ = "IncompatiblePeer"


class _WeakGroupRefused(_IncompatiblePeer):
    """W59 PR-2's GEX floor refusal, by NAME."""

    def __init__(self, offered_bits):
        super().__init__("weak group")
        self.offered_bits = offered_bits


_WeakGroupRefused.__name__ = "WeakGroupRefused"


class NetmikoTimeoutException(Exception):
    pass


def _wrapped(inner):
    """What netmiko 4.8 actually raises: its own timeout, with paramiko's exception as __context__."""
    try:
        try:
            raise inner
        except Exception:
            raise NetmikoTimeoutException("A paramiko SSHException occurred during connection creation")
    except NetmikoTimeoutException as outer:
        return outer


def _obs_with_lists(server, client):
    obs = S.SessionObservation()
    obs.server, obs.client, obs.kexinit_seen = server, client, True
    return obs


_P5_CLIENT = {"kex": ["curve25519-sha256@libssh.org", "ecdh-sha2-nistp256", "diffie-hellman-group14-sha256"],
              "host_key": ["ssh-ed25519", "rsa-sha2-512", "rsa-sha2-256"], "cipher": ["aes128-ctr"],
              "mac": ["hmac-sha2-256", _HMAC_SHA1]}


# =================================================================== T1: pristine tables, pure observer ===
_TABLE_ATTRS = ("_preferred_kex", "_kex_info", "_preferred_keys", "_key_info", "_preferred_pubkeys",
                "_preferred_ciphers", "_preferred_macs")


def _stock_snapshot():
    import paramiko
    from paramiko import kex_gex, kex_group14

    snap = {a: getattr(paramiko.Transport, a) for a in _TABLE_ATTRS}
    snap["RSAKey.HASHES"] = paramiko.RSAKey.HASHES
    snap["KexGexSHA256.min_bits"] = kex_gex.KexGexSHA256.min_bits
    snap["KexGroup14SHA256.hash_algo"] = kex_group14.KexGroup14SHA256.hash_algo
    return {k: (v, (dict(v) if isinstance(v, dict) else v)) for k, v in snap.items()}


def test_t1_observed_transport_leaves_every_stock_table_pristine():
    """T1 (observer half). Catches: a table written into an inherited class dict
    (`Transport._kex_info[...] = ...`), which would change negotiation for EVERY device and thread."""
    before = _stock_snapshot()
    a, b = socket.socketpair()
    try:
        t = C.ObservedTransport(a)
        assert isinstance(t, C._paramiko.Transport)
        t.close()
    finally:
        a.close()
        b.close()
    after = _stock_snapshot()
    for key, (obj, value) in before.items():
        assert after[key][0] is obj, f"{key} was replaced"
        assert after[key][1] == value, f"{key} was mutated"


def test_t1_the_mixin_defines_no_table_and_overrides_exactly_two_methods():
    """T1. Catches: an algorithm table (or any other override) added to the observer, which would make the
    default path's negotiation differ from stock paramiko."""
    for cls in (S.ObservingTransportMixin, C.ObservedTransport):
        keys = set(vars(cls))
        assert not {k for k in keys if k.startswith("_preferred_") or k.endswith("_info") or k == "HASHES"}, cls
        methods = {k for k, v in vars(cls).items() if callable(v) and not k.startswith("__")}
        assert methods == ({"_parse_kex_init", "_parse_newkeys"} if cls is S.ObservingTransportMixin else set()), \
            (cls, methods)
    assert C.ObservedTransport.__mro__[1:3] == (S.ObservingTransportMixin, C._paramiko.Transport)


def test_t1_the_observer_module_imports_no_network_library():
    """Catches: `import paramiko` (or socket) creeping into the owner, which would drop it out of the
    no-egress walk the attestation publishes."""
    from cisco_toolkit.attestation import NETWORK_IMPORTS, imported_names

    tree = ast.parse((ROOT / "cisco_toolkit" / "ssh_session.py").read_text(encoding="utf-8"))
    names = imported_names(tree)
    assert not {n for n in names if n in NETWORK_IMPORTS or n.split(".")[0] in NETWORK_IMPORTS}, names


# =================================================================== T7: the netmiko / paramiko seam ===
def test_t7_handler_table_binds_the_observing_parse_newkeys():
    """T7. Catches: paramiko no longer dispatching NEWKEYS through `self._parse_newkeys` (simulated upstream
    change) -- the record would silently stop being captured."""
    from paramiko.common import MSG_NEWKEYS

    a, b = socket.socketpair()
    try:
        t = C.ObservedTransport(a)
        handler = t._handler_table[MSG_NEWKEYS]
        assert handler.__func__ is S.ObservingTransportMixin._parse_newkeys
        t.close()
    finally:
        a.close()
        b.close()


def test_t7_netmiko_builds_its_client_through_the_overridden_hook():
    """T7. Catches: netmiko's `_build_ssh_client` no longer calling `_get_ssh_client_instance` (the hook renamed
    upstream) -- the observed client, and with it the whole record, would silently disappear."""
    driver = C._observed_driver_for("ios", C.ObservedTransport)
    base = C._NETMIKO_CLASS_MAPPER["cisco_ios"]
    assert driver.__mro__[1:3] == (C._ObservedClientMixin, base)
    inst = object.__new__(driver)
    inst.system_host_keys = False
    inst.alt_host_keys = False
    inst.alt_key_file = ""
    inst.key_policy = C._paramiko.AutoAddPolicy()
    recorder = S.SessionRecorder(None, consent=_DEFAULT_CONSENT, library=_lib())
    C._SESSION_HANDOFF.value = (recorder, C.ObservedTransport)
    try:
        client = inst._build_ssh_client()
    finally:
        C._SESSION_HANDOFF.value = None
    assert isinstance(client, C._ObservedSSHClient)
    assert client._ssh_recorder is recorder and client._ssh_transport_cls is C.ObservedTransport


def test_t7_observed_driver_refuses_construction_outside_the_factory():
    """Catches: an observed driver built without the hand-off (an unrecorded session would open)."""
    driver = C._observed_driver_for("nxos", C.ObservedTransport)
    inst = object.__new__(driver)
    C._SESSION_HANDOFF.value = None
    with pytest.raises(RuntimeError, match="outside _open_connection"):
        inst._get_ssh_client_instance()


def test_t7_observed_client_forces_its_transport_factory_and_binds_the_sink(monkeypatch):
    """T7. Catches: `connect()` honouring a caller's transport_factory (or none), which would build an
    unobserved stock transport; and a sink bound to the class or a thread-local instead of the instance."""
    captured = {}

    def fake_connect(self, *args, **kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(C._paramiko.SSHClient, "connect", fake_connect)
    recorder = S.SessionRecorder(None, consent=_DEFAULT_CONSENT, library=_lib())
    obs = recorder.begin_attempt()
    client = C._ObservedSSHClient(recorder, C.ObservedTransport)
    client.connect("127.0.0.1", transport_factory=lambda *a, **k: None)
    factory = captured["transport_factory"]
    a, b = socket.socketpair()
    try:
        t = factory(a, disabled_algorithms=None)
        assert type(t) is C.ObservedTransport
        assert getattr(t, S.SINK_ATTRIBUTE) is obs
        assert not hasattr(C.ObservedTransport, S.SINK_ATTRIBUTE)
        t.close()
    finally:
        a.close()
        b.close()
    assert recorder.record and recorder.record["outcome"] == "established"   # written before connect() returned


def test_t7_floating_environment_stock_tables_contain_no_sha1():
    """T7 / design section 3: the floating test environment resolves paramiko 5, whose stock tables cannot
    negotiate SHA-1 in the exchange hash or the host-key signature. Behavioural: the probe reads the live
    classes, never a version string. Catches: the environment silently regressing to a SHA-1-permitting
    paramiko (e.g. a netmiko[par4] cap), which would make every 'default path' claim here false."""
    import paramiko

    assert S.permits_sha1(paramiko.Transport, paramiko.RSAKey) is False


def test_t7_the_probe_reads_tables_not_versions():
    """Catches: `permits_sha1` reduced to a constant or a version comparison."""
    class Old:
        _preferred_kex = ("ecdh-sha2-nistp256", _G14_SHA1)
        _kex_info = {}

    class New:
        _preferred_kex = ("ecdh-sha2-nistp256",)
        _preferred_keys = ("rsa-sha2-512",)

    class RSAOld:
        HASHES = {_RSA_SHA1: object}

    assert S.permits_sha1(Old) is True
    assert S.permits_sha1(New) is False
    assert S.permits_sha1(New, RSAOld) is True


def test_t7_exact_versions_are_read_only_from_the_lock_text():
    """Design section 8: the only exact-version assertion, against the shipped lock's TEXT (PR-3 re-locks)."""
    lock = (ROOT / "portable" / "windows-x64-requirements.lock").read_text(encoding="utf-8")
    assert re.search(r"(?m)^paramiko==4\.0\.0 \\$", lock)
    assert re.search(r"(?m)^netmiko==4\.7\.0 \\$", lock)


# ================================================================== T8: one patchable connection factory ===
def _engine_tree():
    return ast.parse(ENGINE.read_text(encoding="utf-8"))


def test_t8_open_connection_is_the_only_constructor_of_a_netmiko_connection():
    """T8 (default half). Catches: a direct `ConnectHandler(...)`, `CLASS_MAPPER[...](...)` or
    `_observed_driver_for(...)(...)` call anywhere but `_open_connection`, which would bypass both the
    observer and the live-safety patch point."""
    tree = _engine_tree()
    owner_of = {}
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for node in ast.walk(fn):
                owner_of.setdefault(id(node), fn.name)
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == "ConnectHandler":
            offenders.append(("ConnectHandler", node.lineno))
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if isinstance(f, ast.Call) and isinstance(f.func, ast.Name) and f.func.id == "_observed_driver_for":
            offenders.append(("_observed_driver_for(...)(...)", node.lineno))
        if isinstance(f, ast.Subscript) and isinstance(f.value, ast.Name) and f.value.id == "_NETMIKO_CLASS_MAPPER":
            offenders.append(("CLASS_MAPPER[...](...)", node.lineno))
        if isinstance(f, ast.Name) and f.id == "driver" and owner_of.get(id(node)) != "_open_connection":
            offenders.append(("driver(...)", node.lineno))
    assert not offenders, offenders
    opens = [owner_of.get(id(n)) for n in ast.walk(tree) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name) and n.func.id == "_open_connection"]
    assert opens == ["connect_device"], opens
    assert not hasattr(C, "ConnectHandler"), "a stale `C.ConnectHandler` patch must fail loudly, not pass silently"


def test_t8_patching_the_factory_intercepts_the_default_path(monkeypatch):
    """T8 (default half). Catches: `connect_device` reaching the network by any route the patch misses."""
    seen = []

    class _Dev:
        def send_command(self, cmd, read_timeout=None):
            return "ok\n"

    def fake_open(kwargs, platform, profile, recorder):
        seen.append((kwargs["host"], kwargs.get("port"), platform, profile, recorder.effective_profile))
        return _Dev()

    monkeypatch.setattr(C, "_open_connection", fake_open)
    dev, resolved = C.connect_device("192.0.2.10", "SW1", "u", "p", "ios", port=2222)
    assert isinstance(dev, _Dev) and resolved == "ios"
    assert seen == [("192.0.2.10", 2222, "ios", S.DEFAULT_PROFILE, S.DEFAULT_PROFILE)]


def test_t8_a_non_default_profile_fails_closed_in_this_build():
    """PR-1 ships no legacy transport: a non-default profile must never silently fall back to a default one."""
    with pytest.raises(ValueError, match="not available in this build"):
        C._transport_for_profile(S.LEGACY_SHA1_PROFILE)


# ======================================================= section 4.4: refusals are classified, never retried ===
def test_refusal_from_lists_is_classified_whatever_exception_surfaced():
    """Catches: classification by exception type only -- netmiko turns IncompatiblePeer into a timeout, and a
    KEXINIT followed by DISCONNECT surfaces as EOFError."""
    server = {"kex": [_G14_SHA1, "ext-info-s"], "host_key": [_RSA_SHA1], "cipher_c2s": ["aes128-ctr"],
              "cipher_s2c": ["aes128-ctr"], "mac_c2s": [_HMAC_SHA1], "mac_s2c": [_HMAC_SHA1]}
    obs = _obs_with_lists(server, _P5_CLIENT)
    for exc in (_wrapped(_IncompatiblePeer("no acceptable kex algorithm")), EOFError(), OSError("reset")):
        ref = S.classify_failure(exc, obs)
        assert ref["classification"] == "refused_legacy_only" and ref["category"] == "kex", (exc, ref)
        assert ref["names"] == [_G14_SHA1]                     # the pseudo-algorithm is not graded


@pytest.mark.parametrize("server_kex, expected, bits", [
    (["diffie-hellman-group1-sha1"], "refused_weak_dh", 1024),
    (["curve25519-sha256", "mlkem768x25519-sha256"], "refused_unsupported_modern", None),
    (["diffie-hellman-group1-sha1", _G14_SHA1], "refused_legacy_only", None),
    (["some-vendor-kex@example.org"], "unclassified", None),
    ([_G14_SHA1, "curve25519-sha256"], "refused_unsupported_modern", None),
])
def test_kex_refusal_grades(server_kex, expected, bits):
    """Catches: a weakness inferred from absence (an ungraded name read as legacy), and a modern-but-
    unimplemented offer graded as a device weakness."""
    server = {"kex": server_kex, "host_key": ["rsa-sha2-512"], "cipher_c2s": ["aes128-ctr"],
              "cipher_s2c": ["aes128-ctr"], "mac_c2s": ["hmac-sha2-256"], "mac_s2c": ["hmac-sha2-256"]}
    ref = S.classify_failure(EOFError(), _obs_with_lists(server, _P5_CLIENT))
    assert ref["classification"] == expected and ref["offered_group_bits"] == bits, ref


def test_host_key_and_cipher_mac_refusals():
    base = {"kex": ["ecdh-sha2-nistp256"], "host_key": ["rsa-sha2-512"], "cipher_c2s": ["aes128-ctr"],
            "cipher_s2c": ["aes128-ctr"], "mac_c2s": ["hmac-sha2-256"], "mac_s2c": ["hmac-sha2-256"]}
    hk = S.classify_failure(EOFError(), _obs_with_lists(dict(base, host_key=[_RSA_SHA1]), _P5_CLIENT))
    assert (hk["category"], hk["classification"]) == ("host_key", "refused_legacy_only")
    dss = S.classify_failure(EOFError(), _obs_with_lists(dict(base, host_key=["ssh-dss"]), _P5_CLIENT))
    assert dss["classification"] == "refused_legacy_only" and not S._within_legacy_tier(dss)
    mac = S.classify_failure(EOFError(), _obs_with_lists(dict(base, mac_s2c=["hmac-md5"]), _P5_CLIENT))
    assert (mac["category"], mac["classification"], mac["names"]) == ("mac", "refused_cipher_mac", ["hmac-md5"])


def test_exception_chain_evidence_when_no_lists_were_recorded():
    """Catches: a weak-group refusal raised as a plain SSHException being retried as `unknown` (critique P2-3),
    and a disconnect before any KEXINIT being treated as a refusal (T17's no-evidence case)."""
    weak = S.classify_failure(_wrapped(_WeakGroupRefused(1024)), S.SessionObservation())
    assert (weak["classification"], weak["offered_group_bits"]) == ("refused_weak_dh", 1024)
    inc = S.classify_failure(_wrapped(_IncompatiblePeer("Incompatible version (1.5 instead of 2.0)")), None)
    assert (inc["classification"], inc["category"]) == ("unclassified", "version")
    assert S.classify_failure(EOFError(), S.SessionObservation()) is None
    assert S.classify_failure(_wrapped(OSError("timed out")), None) is None


def test_connect_device_never_retries_a_refusal(monkeypatch):
    """Catches: a refusal retried CONNECT_MAX_ATTEMPTS times (three failed logins' worth of noise on a device
    that will refuse identically), and a refusal recorded as a plain connection failure."""
    calls = []
    server = {"kex": [_G14_SHA1], "host_key": [_RSA_SHA1], "cipher_c2s": ["aes128-ctr"],
              "cipher_s2c": ["aes128-ctr"], "mac_c2s": [_HMAC_SHA1], "mac_s2c": [_HMAC_SHA1]}

    def refusing_open(kwargs, platform, profile, recorder):
        calls.append(1)
        recorder.observation.server = server
        recorder.observation.client = _P5_CLIENT
        recorder.observation.kexinit_seen = True
        raise _wrapped(_IncompatiblePeer("Incompatible ssh peer (no acceptable kex algorithm)"))

    monkeypatch.setattr(C, "_open_connection", refusing_open)
    monkeypatch.setattr(C, "CONNECT_BACKOFF_BASE", 0)
    recorder = S.SessionRecorder(None, consent=_DEFAULT_CONSENT, library=_lib())
    dev, _ = C.connect_device("192.0.2.10", "SW1", "u", "p", "ios", session=recorder)
    assert dev is None and len(calls) == 1 and recorder.attempts == 1
    assert recorder.record["outcome"] == "negotiation_refused"
    assert recorder.record["refusal"]["classification"] == "refused_legacy_only"


def test_connect_device_keeps_the_same_profile_retry_for_an_unevidenced_failure(monkeypatch):
    """Catches: every disconnect classified as a refusal (no retry at all for a transient drop)."""
    calls = []

    def flaky_open(kwargs, platform, profile, recorder):
        calls.append(profile)
        raise _wrapped(EOFError())

    monkeypatch.setattr(C, "_open_connection", flaky_open)
    monkeypatch.setattr(C, "CONNECT_BACKOFF_BASE", 0)
    recorder = S.SessionRecorder(None, consent=_DEFAULT_CONSENT, library=_lib())
    dev, _ = C.connect_device("192.0.2.10", "SW1", "u", "p", "ios", session=recorder)
    assert dev is None and calls == [S.DEFAULT_PROFILE] * C.CONNECT_MAX_ATTEMPTS
    assert recorder.record["outcome"] == "connect_failed" and recorder.record["attempts"] == C.CONNECT_MAX_ATTEMPTS


def test_session_record_error_is_neither_retried_nor_an_sshexception(monkeypatch):
    """Catches: a post-authentication record failure converted by netmiko into a retried timeout (it must not
    subclass SSHException or OSError)."""
    import paramiko

    assert not issubclass(S.SessionRecordError, (paramiko.SSHException, OSError))
    calls = []

    def failing_open(kwargs, platform, profile, recorder):
        calls.append(1)
        raise S.SessionRecordError("session record could not be written (OSError)")

    monkeypatch.setattr(C, "_open_connection", failing_open)
    dev, _ = C.connect_device("192.0.2.10", "SW1", "u", "p", "ios",
                              session=S.SessionRecorder(None, consent=_DEFAULT_CONSENT, library=_lib()))
    assert dev is None and calls == [1]


# ========================================================== T12: the offline owner (sidecar -> row) ===
def test_t12_every_established_status_and_its_label():
    """T12. Catches: one label for both consent states (critique P2-1) and weak-DH losing to SHA-1."""
    cases = [
        (_observation(_G14_SHA1, 20, 2048, _RSA_SHA1, mac=_HMAC_SHA1), _DEFAULT_CONSENT, _lib(True, "4.0.0"),
         "legacy_sha1", "Medium", "negotiated SHA-1 SSH without opt-in (the collector permitted SHA-1: paramiko 4.0.0)"),
        (_observation(_G14_SHA1, 20, 2048, _RSA_SHA1), _LEGACY_CONSENT, _lib(), "legacy_sha1", "Medium",
         "collected over SHA-1 SSH by explicit opt-in (device row and run flag)"),
        (_observation("diffie-hellman-group1-sha1", 20, 1024, _RSA_SHA1), _DEFAULT_CONSENT, _lib(True, "4.0.0"),
         "weak_dh", "High", "negotiated a 1024-bit Diffie-Hellman group, below 2048 (without opt-in)"),
        (_observation("diffie-hellman-group-exchange-sha256", 32, 1536, "rsa-sha2-512"), _DEFAULT_CONSENT, _lib(),
         "weak_dh", "High", "1536-bit"),
        (_observation("curve25519-sha256@libssh.org", 32, None, "ssh-ed25519"), _DEFAULT_CONSENT, _lib(),
         "modern", None, None),
        (_observation("diffie-hellman-group14-sha256", 32, 2048, "rsa-sha2-256"), _DEFAULT_CONSENT, _lib(),
         "modern", None, None),
    ]
    for obs, consent, lib, status, severity, label_part in cases:
        rec = S.build_record(outcome="established", consent=consent, library=lib, attempts=1, observation=obs)
        assert S.validate_record(rec) == []
        row = _row(rec)
        assert (row["status"], row["severity"]) == (status, severity), (obs["negotiated"], row)
        if label_part is None:
            assert row["label"] is None and row["finding"] == "closed"
        else:
            assert label_part in row["label"] and "host key not verified" in row["label"]
        assert row["host_key_verified"] is False


def test_t12_auth_failure_keeps_its_negotiated_posture():
    """The password crossed the negotiated session either way (design section 6.2)."""
    rec = S.build_record(outcome="auth_failed", consent=_DEFAULT_CONSENT, library=_lib(True, "4.0.0"), attempts=1,
                         observation=_observation(_G14_SHA1, 20, 2048, _RSA_SHA1), failure_class="NetmikoAuthenticationException")
    assert _row(rec)["status"] == "legacy_sha1"
    no_kex = S.build_record(outcome="auth_failed", consent=_DEFAULT_CONSENT, library=_lib(), attempts=1)
    assert _row(no_kex)["status"] == "unknown"


def test_t12_inconsistent_observation_is_unknown_never_modern():
    """T12. Catches: a broken observer reporting `modern` (engine name SHA-256, exchange hash 20 bytes)."""
    obs = _observation("diffie-hellman-group14-sha256", 20, 2048, "rsa-sha2-512")
    row = _row(S.build_record(outcome="established", consent=_DEFAULT_CONSENT, library=_lib(), attempts=1,
                              observation=obs))
    assert (row["status"], row["reason"], row["finding"]) == ("unknown", "inconsistent observation", "verify")
    disagreeing = _observation("ecdh-sha2-nistp256", 32, None, "rsa-sha2-512", engine_agrees=False)
    row = _row(S.build_record(outcome="established", consent=_DEFAULT_CONSENT, library=_lib(), attempts=1,
                              observation=disagreeing))
    assert row["status"] == "unknown"


def test_t12_pending_records_on_each_profile():
    """T12 / T16 offline half. Catches: a `pending` record rendered `not_recorded` (absence as health) and a
    legacy-authorized device with no completed record falling back to `verify` (critique P2-6)."""
    default = _row(S.build_record(outcome="pending", consent=_DEFAULT_CONSENT, library=_lib()), live=False)
    assert (default["status"], default["finding"]) == ("unknown", "verify")
    legacy = _row(S.build_record(outcome="pending", consent=_LEGACY_CONSENT, library=_lib()), live=False)
    assert (legacy["status"], legacy["finding"], legacy["severity"]) == ("legacy_unrecorded", "exposed", "Medium")
    assert "never completed" in legacy["label"]


def test_t12_absent_sidecar_live_and_offline():
    """Catches: an absent record rendered modern; an eligible live device with no record not exposed."""
    off = S.derive_row("sw1", None, evidence="sw1/_ssh_session.json", live=False)
    assert (off["status"], off["finding"], off["evidence"]) == ("not_recorded", "verify", None)
    live_eligible = S.derive_row("sw1", None, evidence="x", live=True, eligible_hosts={"sw1"})
    assert (live_eligible["status"], live_eligible["finding"]) == ("legacy_unrecorded", "exposed")
    live_other = S.derive_row("sw1", None, evidence="x", live=True, eligible_hosts={"sw2"})
    assert live_other["status"] == "not_recorded"


@pytest.mark.parametrize("cls, status, finding", [
    ("refused_legacy_only", "refused_legacy_only", "exposed"),
    ("refused_weak_dh", "refused_weak_dh", "exposed"),
    ("refused_unsupported_modern", "refused_unsupported_modern", "verify"),
    ("refused_cipher_mac", "refused_cipher_mac", "verify"),
    ("unclassified", "unknown", "verify"),
])
def test_t12_each_refusal_class_maps_to_its_status(cls, status, finding):
    ref = {"category": "kex", "classification": cls, "detail": "no_common_kex",
           "offered_group_bits": 1024 if cls == "refused_weak_dh" else None, "names": [_G14_SHA1]}
    obs = _observation(_G14_SHA1, 20, 2048, _RSA_SHA1, newkeys=False)
    rec = S.build_record(outcome="negotiation_refused", consent=_DEFAULT_CONSENT, library=_lib(), attempts=1,
                         observation=obs, refusal=ref, failure_class="NetmikoTimeoutException")
    assert S.validate_record(rec) == []
    row = _row(rec)
    assert (row["status"], row["finding"]) == (status, finding), row


def test_t12_refusal_wording_follows_what_the_opt_in_can_reach():
    """Catches: 'requires the legacy-sha1 opt-in' printed for a device (DSA-only) that no profile can collect."""
    rsa = {"category": "host_key", "classification": "refused_legacy_only", "names": [_RSA_SHA1]}
    dsa = {"category": "host_key", "classification": "refused_legacy_only", "names": ["ssh-dss"]}
    assert "requires the legacy-sha1 opt-in" in S.disclosure_sentence({"status": "refused_legacy_only", "refusal": rsa})
    assert "no profile of this collector implements" in S.disclosure_sentence(
        {"status": "refused_legacy_only", "refusal": dsa})


def test_t12_malformed_sidecars_are_unknown_with_their_reason():
    for data in (b"not json", b'{"schema": "ssh_session/1"}', b'{"a": 1, "a": 2}', b"[NaN]"):
        row = S.derive_row("sw1", data, evidence="e", live=False)
        assert row["status"] == "unknown" and row["reason"], data
    row = S.derive_row("sw1", None, evidence="e", live=False, read_error="session record failed its custody read")
    assert row["status"] == "unknown" and "custody" in row["reason"]


def test_t12_consent_fields_come_only_from_the_sidecar():
    """Catches: consent re-derived from the current devices.json / command line at analysis time."""
    rec = S.build_record(outcome="established", consent=_LEGACY_CONSENT, library=_lib(), attempts=1,
                         observation=_observation(_G14_SHA1, 20, 2048, _RSA_SHA1))
    block = S.compute_ssh_sessions(["sw1"], lambda h: (S.render_record(rec), None), live=False,
                                   consent=S.offline_consent_block(), evidence_path=lambda h: f"{h}/x")
    row = block["rows"][0]
    assert (row["device_profile"], row["named_on_run_flag"], row["effective_profile"]) == \
        (S.LEGACY_SHA1_PROFILE, True, S.LEGACY_SHA1_PROFILE)
    assert block["consent"] == S.offline_consent_block()
    assert all(block["consent"][k] is None for k in block["consent"] if k != "mode")


def test_t12_closed_schema_rejects_identifying_content():
    """T12 / critique P2-5. Catches: a hostname, an address, a fingerprint or an out-of-grammar name entering
    the record (which the redacted-collection path would then leak)."""
    good = S.build_record(outcome="established", consent=_DEFAULT_CONSENT, library=_lib(), attempts=1,
                          observation=_observation("ecdh-sha2-nistp256", 32, None, "rsa-sha2-512"))
    assert S.validate_record(good) == []
    for mutate in (
        lambda r: r.update(hostname="core1"),
        lambda r: r["negotiated"].update(server_software="10.1.2.3"),
        lambda r: r["negotiated"].update(server_software="SSH-2.0-x 10.1.2.3"),
        lambda r: r["host_key"].update(fingerprint="SHA256:abc"),
        lambda r: r["server_offered"]["kex"].append("has space"),
        lambda r: r["server_offered"]["kex"].append("a,b"),
        lambda r: r["server_offered"]["kex"].append("x" * 65),
        lambda r: r["library"].update(paramiko="10.0.0.1"),
        lambda r: r["negotiated"].update(kex_hash_bytes=True),
        lambda r: r.update(refusal={"category": "kex"}),
    ):
        r = json.loads(json.dumps(good))
        mutate(r)
        assert S.validate_record(r), mutate


def test_t12_banner_comment_is_stripped_and_names_are_screened():
    assert S.server_software_from_banner("SSH-2.0-Cisco-1.25 core1.example 10.1.2.3") == ("SSH-2.0-Cisco-1.25", 0)
    assert S.server_software_from_banner("SSH-2.0-0011.2233.4455") == (None, 1)
    names, dropped = S._sanitize_names(["aes128-ctr", "10.0.0.1", "a b", "ok@example.org"])
    assert names == ["aes128-ctr", "ok@example.org"] and dropped == 2


def test_t12_offline_block_shape_and_software_risk_projection():
    rec = S.build_record(outcome="established", consent=_DEFAULT_CONSENT, library=_lib(True, "4.0.0"), attempts=1,
                         observation=_observation(_G14_SHA1, 20, 2048, _RSA_SHA1))
    store = {"sw1": S.render_record(rec)}
    block = S.compute_ssh_sessions(["sw1", "sw2"], lambda h: (store.get(h), None), live=False, consent=None,
                                   evidence_path=lambda h: f"{h}/{S.SIDECAR_FILENAME}")
    assert block["schema"] == S.SET_SCHEMA and block["owner"] == S.OWNER
    assert [r["status"] for r in block["rows"]] == ["legacy_sha1", "not_recorded"]
    assert block["summary"]["by_status"]["legacy_sha1"] == 1 and block["summary"]["mode"] == "offline"
    proj = S.software_risk_projection(block)
    assert proj["sw1"]["finding"] == "exposed" and proj["sw1"]["severity"] == "Medium"
    assert proj["sw2"]["finding"] == "verify"


def test_software_risk_surface_is_a_projection_of_the_owner():
    """Catches: the surface computed from config text (it is session evidence), or an absent row read closed."""
    from cisco_toolkit.analyze import compute_software_risk

    rec = S.build_record(outcome="established", consent=_DEFAULT_CONSENT, library=_lib(True, "4.0.0"), attempts=1,
                         observation=_observation("diffie-hellman-group1-sha1", 20, 1024, _RSA_SHA1))
    block = S.compute_ssh_sessions(["sw1", "sw2"], lambda h: ((S.render_record(rec) if h == "sw1" else None), None),
                                   live=False, consent=None, evidence_path=lambda h: h)
    sr = compute_software_risk({}, {}, {}, ["sw1", "sw2", "sw3"], ssh_sessions=block)
    surf = {d["host"]: d["surfaces"].get(S.SURFACE_KIND) for d in sr["per_device"]}
    assert surf == {"sw1": "exposed", "sw2": "verify", "sw3": "verify"}
    [finding] = [f for f in sr["findings"] if f["kind"] == S.SURFACE_KIND]
    assert finding["host"] == "sw1" and finding["severity"] == "High" and finding["evidence_verbatim"] is False
    assert "1024-bit" in finding["detail"]
    # direct callers that pass no block see no surface at all (backward compatible)
    assert S.SURFACE_KIND not in str(compute_software_risk({}, {}, {}, ["sw1"]))
    # a failed block ({}) reads verify for every host, never closed
    failed = compute_software_risk({}, {}, {}, ["sw1"], ssh_sessions={})
    assert failed["per_device"][0]["surfaces"][S.SURFACE_KIND] == "verify"


# ================================================================ recorder write timing (section 6.1) ===
def test_recorder_write_failures_are_recorded_and_raised(tmp_path):
    def broken(path, record):
        raise PermissionError("denied")

    rec = S.SessionRecorder(str(tmp_path / S.SIDECAR_FILENAME), consent=_DEFAULT_CONSENT, library=_lib(),
                            writer=broken)
    with pytest.raises(PermissionError):
        rec.write_pending()
    rec.begin_attempt()
    with pytest.raises(S.SessionRecordError):
        rec.complete_established()
    assert rec.finish_failure("connect_failed", EOFError()) is False
    assert [f["stage"] for f in rec.write_failures] == ["pending", "established", "connect_failed"]


def test_recorder_writes_canonical_lf_bytes(tmp_path):
    path = tmp_path / S.SIDECAR_FILENAME
    rec = S.SessionRecorder(str(path), consent=_DEFAULT_CONSENT, library=_lib())
    rec.write_pending()
    data = path.read_bytes()
    assert b"\r" not in data and data.endswith(b"\n")
    assert json.loads(data)["outcome"] == "pending"
    assert not [p for p in tmp_path.iterdir() if p.name != S.SIDECAR_FILENAME], "a temp file was left behind"


def test_t16_pending_write_failure_leaves_the_device_unconnected(monkeypatch, tmp_path):
    """T16 (default half). Catches: a device connected although its record could not be written first."""
    opened = []
    monkeypatch.setattr(C, "_open_connection", lambda *a, **k: opened.append(a) or None)
    original = C._session_recorder_for

    def failing_recorder(devinfo, dev_dir):
        r = original(devinfo, dev_dir)
        r._writer = lambda path, record: (_ for _ in ()).throw(PermissionError("denied"))
        return r

    monkeypatch.setattr(C, "_session_recorder_for", failing_recorder)
    failures = []
    platform, cmd = C._collect_live_device(
        {"hostname": "SW1", "ip": "192.0.2.10", "username": "u", "password": "p", "platform": "ios"},
        str(tmp_path / "SW1"), claimed=set(), lock=threading.Lock(),
        on_record_failure=lambda *a: failures.append(a))
    assert cmd is None and opened == []
    assert failures == [("SW1", "pending", "PermissionError")]


def test_duplicate_device_folders_cannot_share_one_record(monkeypatch, tmp_path):
    """Catches: two devices.json rows resolving to one folder silently overwriting each other's record."""
    monkeypatch.setattr(C, "_open_connection", lambda *a, **k: None)
    monkeypatch.setattr(C, "CONNECT_MAX_ATTEMPTS", 1)
    claimed, failures = set(), []
    dev = {"hostname": "SW1", "ip": "192.0.2.10", "username": "u", "password": "p", "platform": "ios"}
    C._collect_live_device(dev, str(tmp_path / "SW1"), claimed=claimed, lock=threading.Lock(),
                           on_record_failure=lambda *a: failures.append(a))
    C._collect_live_device(dict(dev), str(tmp_path / "SW1"), claimed=claimed, lock=threading.Lock(),
                           on_record_failure=lambda *a: failures.append(a))
    assert failures == [("SW1", "pending", "FileExistsError")]


@pytest.mark.parametrize("port", ["22", 0, 70000, True, 2.5])
def test_an_invalid_port_is_refused_not_replaced_by_22(port):
    with pytest.raises(ValueError, match="port"):
        C._ssh_port({"hostname": "SW1", "port": port})
    assert C._ssh_port({"hostname": "SW1"}) is None and C._ssh_port({"port": 2222}) == 2222


# ======================================================================= consent block (section 5) ===
def test_pr1_consent_is_recorded_and_never_effective():
    """PR-1 has no run flag: a row that requests legacy-sha1 is recorded as requested-not-named and collected
    on the default path. Catches: a row request alone enabling a legacy profile (a stale standing grant)."""
    rows = [{"hostname": "a", "ip": "192.0.2.1", "ssh_profile": S.LEGACY_SHA1_PROFILE},
            {"hostname": "b", "ip": "192.0.2.2", "ssh_profile": True},
            {"hostname": "c", "ip": "192.0.2.3"}]
    block = S.live_consent_block(rows, None)
    assert block["devices_requesting_legacy"] == ["a"] and block["requested_not_named"] == ["a"]
    assert block["devices_eligible"] == [] and block["run_flag"] == {"profile": None, "hosts_named": []}
    assert S.consent_for(rows[0])["effective_profile"] == S.DEFAULT_PROFILE
    assert S.consent_for(rows[1])["device_profile"] == S.DEFAULT_PROFILE     # no truthiness coercion
    flagged = S.consent_for(rows[0], {"profile": S.LEGACY_SHA1_PROFILE, "hosts_named": ["a"]})
    assert flagged["effective_profile"] == S.LEGACY_SHA1_PROFILE


# ===================================================================== T10: SHA-1 identifier scope ===
def _parse(path):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SyntaxWarning)
        return ast.parse(path.read_text(encoding="utf-8"))


def _shipped_python_files():
    out = subprocess.run(["git", "ls-files", "-z", "--", "*.py"], cwd=ROOT, capture_output=True, check=True,
                         timeout=60).stdout.decode("utf-8")
    keep = ("cisco_toolkit/", "webapp/backend/", "portable/")
    return [p for p in out.split("\0") if p and (p.startswith(keep) or p in (
        "COLLECT_PARSE_V3_23_0.py", "webapp/__init__.py"))]


def test_t10_ssh_sha1_algorithm_literals_appear_only_in_the_vocabulary_owner():
    """T10 (vocabulary half). Catches: an SSH SHA-1 algorithm name (e.g. the RSA SHA-1 host-key name) added to
    any other shipped module -- a forgotten allowlist re-creating the advisory class with no scanner signal."""
    files = _shipped_python_files()
    assert "cisco_toolkit/ssh_session.py" in files and "COLLECT_PARSE_V3_23_0.py" in files
    pattern = re.compile(r"(?<![A-Za-z0-9@.\-])(?:" + "|".join(
        re.escape(n) for n in sorted(S.SSH_SHA1_ALGORITHM_NAMES, key=len, reverse=True)) + r")(?![A-Za-z0-9@.\-])")
    offenders = []
    for rel in files:
        if rel == "cisco_toolkit/ssh_session.py":
            continue
        try:
            tree = _parse(ROOT / rel)
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and pattern.search(node.value):
                offenders.append((rel, node.lineno))
    assert not offenders, offenders


def test_t10_sha1_hash_primitives_stay_at_their_declared_sites():
    """T10. `hashlib.sha1` only at the declared git-blob identity sites; `hashes.SHA1` nowhere yet (W59 PR-2's
    legacy module will be its only site). Catches: a SHA-1 primitive added to a default-path module."""
    allowed_hashlib = {"portable/release_contract.py", "webapp/backend/observe_ui_projection_contract.py"}
    found_hashlib, found_crypto = set(), set()
    for rel in _shipped_python_files():
        try:
            tree = _parse(ROOT / rel)
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                if node.value.id == "hashlib" and node.attr == "sha1":
                    found_hashlib.add(rel)
                if node.value.id == "hashes" and node.attr == "SHA1":
                    found_crypto.add(rel)
    assert found_hashlib <= allowed_hashlib, found_hashlib
    assert found_crypto == set(), found_crypto


# ======================================================= sidecar basename owner and its restatements ===
def test_collection_sidecar_owner_and_restatements_agree():
    """Design section 6.1 custody. Catches: a new collection sidecar left out of the wheel auditor (it would
    ship client evidence) or the verifier's statement."""
    from cisco_toolkit.capture_integrity import COLLECTION_SIDECAR_BASENAMES
    from tools.audit_wheel import _COLLECTION_SIDECAR_BASENAMES
    from webapp.backend.redaction_verify import SSH_SESSION_RECORD_BASENAME

    assert S.SIDECAR_FILENAME in COLLECTION_SIDECAR_BASENAMES
    assert set(_COLLECTION_SIDECAR_BASENAMES) == set(COLLECTION_SIDECAR_BASENAMES)
    assert SSH_SESSION_RECORD_BASENAME == S.SIDECAR_FILENAME


def test_evidence_records_seal_a_refused_devices_record(tmp_path):
    """Design section 6.1. Catches: the record of a REFUSED device (absent from the command map) left unsealed,
    so the evidence its finding rests on could change unnoticed."""
    root = tmp_path / "collection"
    (root / "edge1").mkdir(parents=True)
    rec = S.build_record(outcome="pending", consent=_DEFAULT_CONSENT, library=_lib())
    (root / "edge1" / S.SIDECAR_FILENAME).write_bytes(S.render_record(rec))
    sealed = C._evidence_records({}, str(root), session_hosts=["edge1"])
    assert [(f["path"], f["commands"]) for f in sealed["files"]] == \
        [(f"edge1/{S.SIDECAR_FILENAME}", [S.CUSTODY_ROLE])]
    assert C._evidence_records({}, str(root))["files"] == []        # not named -> not sealed (explicit denominator)


# ======================================================== asyncssh stays a test-only, isolated peer ===
def test_asyncssh_is_absent_from_every_shipped_or_installed_declaration():
    """Design section 8. Catches: the EPL/GPL test peer leaking into the bundle lock or any pyproject extra."""
    lock = (ROOT / "portable" / "windows-x64-requirements.lock").read_text(encoding="utf-8").lower()
    assert "asyncssh" not in lock
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8").lower()
    assert "asyncssh" not in pyproject
    for name in ("requirements.txt", "requirements-dev.txt"):
        p = ROOT / name
        if p.exists():
            assert "asyncssh" not in p.read_text(encoding="utf-8").lower(), name
    fixture = (ROOT / "tools" / "requirements-ssh-fixture-test.txt").read_text(encoding="utf-8")
    pins = re.findall(r"(?m)^([A-Za-z0-9_.\-]+)==([^\s\\]+) \\$", fixture)
    assert ("asyncssh", "2.24.1") in pins
    for name, _version in pins:
        block = fixture.split(f"{name}==", 1)[1].split("\n# ", 1)[0]
        assert "--hash=sha256:" in block, name


def test_no_test_module_imports_asyncssh_or_the_fixture_server():
    """Design section 8. Catches: collection depending on asyncssh (the test interpreter never has it)."""
    offenders = []
    for path in sorted((ROOT / "tests").rglob("*.py")) + sorted((ROOT / "webapp" / "tests").rglob("*.py")):
        if path == ROOT / "tests" / "ssh_fixture" / "server.py":
            continue
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)      # an unrelated file's escape-sequence warning
            tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""] + [f"{node.module}.{a.name}" for a in node.names]
            if any(n == "asyncssh" or n.startswith("asyncssh.") or n.endswith("ssh_fixture.server")
                   or n == "ssh_fixture.server" for n in names):
                offenders.append((str(path.relative_to(ROOT)), node.lineno))
    assert not offenders, offenders


def test_ci_provisions_the_fixture_and_fails_closed_on_the_required_legs():
    """Design section 8. Catches: the interop gate passing vacuously (fixture never provisioned, or its absence
    allowed to skip on the legs that are supposed to run it), and the fixture file left unaudited."""
    import yaml

    ci = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    steps = ci["jobs"]["test"]["steps"]
    provision = [s for s in steps if "requirements-ssh-fixture-test.txt" in str(s.get("run", ""))]
    assert len(provision) == 1 and "--require-hashes" in provision[0]["run"]
    assert "ATLAS_SSH_FIXTURE_PYTHON" in provision[0]["run"]
    suite = [s for s in steps if s.get("name") == "Run the complete default suite"]
    assert suite and suite[0]["env"].get("ATLAS_SSH_FIXTURE_REQUIRED") == "1"
    assert steps.index(provision[0]) < steps.index(suite[0])
    audit_runs = [s.get("run", "") for s in ci["jobs"]["dependency-audit"]["steps"]]
    assert any("--disable-pip -r tools/requirements-ssh-fixture-test.txt" in r for r in audit_runs)


def test_assesshub_never_carries_the_legacy_ssh_opt_in():
    """Design section 5: AssessHub never collects live, so the run-level opt-in may never appear in its
    sources (it arrives in the engine with W59 PR-2). Catches: a webapp path that could pass it."""
    hits = [str(p.relative_to(ROOT)) for p in (ROOT / "webapp" / "backend").rglob("*.py")
            if "--allow-legacy-ssh" in p.read_text(encoding="utf-8")]
    assert hits == []
