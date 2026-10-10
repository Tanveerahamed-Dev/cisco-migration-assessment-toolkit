"""W59 PR-1 interop: the collector's REAL connection path against an independent SSH peer on 127.0.0.1.

The peer is asyncssh (tests/ssh_fixture/server.py), run as a SUBPROCESS from its own virtualenv built from the
hash-pinned tools/requirements-ssh-fixture-test.txt by tests/ssh_fixture/launcher.py; this module never imports
asyncssh (design section 8). The fixture interpreter's path is read from ATLAS_SSH_FIXTURE_PYTHON. On the legs that
provision it the workflow also sets ATLAS_SSH_FIXTURE_REQUIRED=1, and then a missing fixture FAILS rather than skips,
so the interop gate cannot pass vacuously; any other run skips visibly with the reason.

The disconnect-race tests (T17) need no third-party peer: tests/ssh_fixture/raw_peer.py is a stdlib RFC 4253
responder for the cleartext phase. Every fixture profile is proven on the wire (`probe_kexinit`) before a test
relies on it.

Behaviour, never versions (design section 8): whether this paramiko's stock tables permit SHA-1 is read from
the live classes with `ssh_session.permits_sha1`; T7 (tests/test_ssh_session.py) holds the floating test
environment to the paramiko-5 answer.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import COLLECT_PARSE_V3_23_0 as C
from cisco_toolkit import ssh_session as S
# The fixture launcher lives in a non-test helper module (W59 PR-2 review round 3), shared with test_legacy_ssh.py.
from ssh_fixture.launcher import fixture_server
from ssh_fixture.raw_peer import RawResponder, kexinit_names, probe_kexinit

_G14_SHA1 = S.LEGACY_SHA1_TIER_KEX[0]
_RSA_SHA1 = S.LEGACY_SHA1_TIER_HOST_KEYS[0]


# --------------------------------------------------------------------------------------------- fixture ---
def _events(log: Path, kind: str | None = None) -> list:
    if not log.exists():
        return []
    rows = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [r for r in rows if kind is None or r["event"] == kind]


def _recorder(dev_dir: Path, writer=None) -> S.SessionRecorder:
    dev_dir.mkdir(parents=True, exist_ok=True)
    rec = S.SessionRecorder(str(dev_dir / S.SIDECAR_FILENAME),
                            consent=S.consent_for({"hostname": "lab-sw1", "ip": "127.0.0.1"}),
                            library=C._ssh_library_block(), writer=writer)
    rec.write_pending()
    return rec


def _sidecar(dev_dir: Path) -> dict:
    return json.loads((dev_dir / S.SIDECAR_FILENAME).read_bytes())


def _row(dev_dir: Path, *, live: bool = True) -> dict:
    return S.derive_row("lab-sw1", (dev_dir / S.SIDECAR_FILENAME).read_bytes(), evidence="lab-sw1/x", live=live)


def _library_permits_sha1() -> bool:
    import paramiko

    return S.permits_sha1(paramiko.Transport, paramiko.RSAKey)


@pytest.fixture(autouse=True)
def _no_backoff(monkeypatch):
    monkeypatch.setattr(C, "CONNECT_BACKOFF_BASE", 0)


# ================================================================ non-vacuity: the profiles, on the wire ===
def test_every_fixture_profile_is_what_it_claims_on_the_wire(tmp_path):
    """Design section 8. Catches: a fixture that silently offers asyncssh's DEFAULT lists (which still enable
    SHA-1) -- every SHA-1-only assertion below would then rest on an assumption."""
    with fixture_server(tmp_path, "sha1-only") as (port, _log):
        lists = probe_kexinit("127.0.0.1", port)
        assert kexinit_names(lists, "kex") == [_G14_SHA1]
        assert lists["host_key"] == [_RSA_SHA1]
    with fixture_server(tmp_path, "modern") as (port, _log):
        lists = probe_kexinit("127.0.0.1", port)
        assert set(kexinit_names(lists, "kex")) == {"ecdh-sha2-nistp256", "diffie-hellman-group14-sha256"}
        assert not set(lists["host_key"]) & S.SHA1_HOST_KEY_NAMES


# ========================================================== T3 (default half): a SHA-1-only server ===
def test_t3_default_path_against_a_sha1_only_server(tmp_path):
    """T3 (PR-1 half). Floating paramiko 5: the default path is REFUSED as refused_legacy_only after exactly
    ONE attempt, before any password is sent, and the record holds the server's lists. A SHA-1-permitting
    paramiko (the frozen bundle's 4.0.0) instead establishes and records legacy_sha1 WITHOUT opt-in -- T14's
    frozen assertion. Catches: classification removed (three attempts), and the group size read after NEWKEYS
    (null)."""
    dev_dir = tmp_path / "lab-sw1"
    with fixture_server(tmp_path, "sha1-only") as (port, log):
        wire = probe_kexinit("127.0.0.1", port)
        recorder = _recorder(dev_dir)
        dev, _ = C.connect_device("127.0.0.1", "lab-sw1", "lab", "lab", "ios", session=recorder, port=port)
        try:
            record, row = _sidecar(dev_dir), _row(dev_dir)
            if _library_permits_sha1():
                assert dev is not None and record["outcome"] == "established"
                neg = record["negotiated"]
                assert (neg["kex"], neg["kex_hash_bytes"], neg["dh_group_bits"], neg["host_key_algorithm"]) == \
                    (_G14_SHA1, 20, 2048, _RSA_SHA1)
                assert row["status"] == "legacy_sha1" and "without opt-in" in row["label"]
                assert row["library_permits_sha1"] is True
            else:
                assert dev is None and record["outcome"] == "negotiation_refused" and record["attempts"] == 1
                assert record["refusal"]["classification"] == "refused_legacy_only"
                assert kexinit_names(record["server_offered"], "kex") == kexinit_names(wire, "kex")
                assert row["status"] == "refused_legacy_only" and row["severity"] == "Medium"
                assert len(_events(log, "connection")) == 1 + 1      # the probe's connection + ONE attempt
                assert _events(log, "auth") == [], "no password may cross a refused negotiation"
        finally:
            if dev is not None:
                dev.disconnect()


# =========================================================== T7: what a real handshake records ===
@pytest.mark.parametrize("profile, kex, bits, host_key", [
    ("modern", "ecdh-sha2-nistp256", None, "rsa-sha2-512"),
    ("sha1-and-sha2", "diffie-hellman-group14-sha256", 2048, "rsa-sha2-256"),
])
def test_t7_a_real_handshake_records_lists_engine_and_group_size(tmp_path, profile, kex, bits, host_key):
    """T7. After a real handshake the record holds the server lists, the agreed key exchange, the MODP group
    size (read from the fixed group's class constant `P`) and the exchange-hash length; SHA-2 is preferred when
    the device offers both. Catches: the private parse hooks no longer reached; `P` vs `p` confused; SHA-1
    entries preferred over SHA-2."""
    dev_dir = tmp_path / "lab-sw1"
    with fixture_server(tmp_path, profile) as (port, _log):
        recorder = _recorder(dev_dir)
        dev, _ = C.connect_device("127.0.0.1", "lab-sw1", "lab", "lab", "ios", session=recorder, port=port)
        try:
            assert dev is not None
            record = _sidecar(dev_dir)
            assert record["outcome"] == "established" and record["observation"]["kexinit"] is True
            neg = record["negotiated"]
            assert (neg["kex"], neg["dh_group_bits"], neg["host_key_algorithm"]) == (kex, bits, host_key)
            assert neg["kex_hash_bytes"] == 32 and neg["server_software"].startswith("SSH-2.0-")
            assert record["server_offered"]["kex"] and record["client_offered"]["kex"]
            if bits is not None:
                assert record["observation"]["group_size_agrees"] is True
            row = _row(dev_dir)
            assert (row["status"], row["finding"], row["legacy_mac_or_cipher"]) == ("modern", "closed", False)
        finally:
            if dev is not None:
                dev.disconnect()


# ========================================================= T16 (default half): record before first command ===
def test_t16_the_completed_record_is_on_disk_before_the_first_command(tmp_path):
    """T16. The fake shell looks for the device's sidecar when the shell opens and when its first input line
    arrives. Catches: the record written after netmiko's session preparation or after the first command."""
    dev_dir = tmp_path / "lab-sw1"
    sidecar = dev_dir / S.SIDECAR_FILENAME
    with fixture_server(tmp_path, "modern", expect_file=sidecar) as (port, log):
        recorder = _recorder(dev_dir)
        dev, _ = C.connect_device("127.0.0.1", "lab-sw1", "lab", "lab", "ios", session=recorder, port=port)
        try:
            assert dev is not None
            starts, lines = _events(log, "shell_start"), _events(log, "line")
            assert starts and starts[0]["expect_file_exists"] is True
            assert starts[0]["expect_file_outcome"] == "established"
            assert lines and lines[0]["expect_file_outcome"] == "established"
        finally:
            if dev is not None:
                dev.disconnect()


def test_t16_a_failed_post_auth_write_closes_the_session_with_no_command_sent(tmp_path):
    """T16. Catches: a write failure after authentication ignored (commands sent over an unrecorded session),
    the device retried, or the sealed record rendered as anything but an incomplete record."""
    dev_dir = tmp_path / "lab-sw1"

    def established_fails(path, record):
        if record["outcome"] == "established":
            raise OSError("simulated disk full")
        S.write_record_atomic(path, record)

    with fixture_server(tmp_path, "modern") as (port, log):
        recorder = _recorder(dev_dir, writer=established_fails)
        dev, _ = C.connect_device("127.0.0.1", "lab-sw1", "lab", "lab", "ios", session=recorder, port=port)
        assert dev is None
        assert [e["ok"] for e in _events(log, "auth")] == [True]          # the session did authenticate
        assert _events(log, "shell_start") == [] and _events(log, "line") == [], "no command may be sent"
        assert len(_events(log, "connection")) == 1                       # never retried
    assert _sidecar(dev_dir)["outcome"] == "pending"
    assert [f["stage"] for f in recorder.write_failures] == ["established"]
    assert _row(dev_dir, live=False)["status"] == "unknown"              # default profile: verify, never health


def test_auth_failure_keeps_the_negotiated_posture(tmp_path):
    """Design section 6.1: the password crossed the negotiated session, so an authentication failure keeps its
    negotiated fields. Catches: the record depending on netmiko keeping a transport object."""
    dev_dir = tmp_path / "lab-sw1"
    with fixture_server(tmp_path, "modern", password="something-else") as (port, log):
        recorder = _recorder(dev_dir)
        dev, _ = C.connect_device("127.0.0.1", "lab-sw1", "lab", "lab", "ios", session=recorder, port=port)
        assert dev is None and len(_events(log, "connection")) == 1        # auth failures are never retried
    record = _sidecar(dev_dir)
    assert record["outcome"] == "auth_failed" and record["negotiated"]["kex"] == "ecdh-sha2-nistp256"
    assert _row(dev_dir)["status"] == "modern"


# ======================================================================== T17: the disconnect race ===
def test_t17a_a_disconnect_before_any_kexinit_keeps_the_same_profile_retry(tmp_path):
    """T17 (a). No server lists exist, so there is no evidence of what the server offers: an ordinary connection
    failure, retried on the SAME profile. Catches: every disconnect classified as a refusal."""
    dev_dir = tmp_path / "lab-sw1"
    with RawResponder("disconnect_before_kexinit") as peer:
        recorder = _recorder(dev_dir)
        dev, _ = C.connect_device("127.0.0.1", "lab-sw1", "lab", "lab", "ios", session=recorder, port=peer.port)
        assert dev is None
        assert peer.connections == C.CONNECT_MAX_ATTEMPTS
    record = _sidecar(dev_dir)
    assert record["outcome"] == "connect_failed" and record["attempts"] == C.CONNECT_MAX_ATTEMPTS
    assert record["refusal"] is None and _row(dev_dir)["status"] == "unknown"


def test_t17b_a_kexinit_then_disconnect_is_classified_from_the_lists_without_retry(tmp_path):
    """T17 (b), library independent: a KEXINIT whose host-key list no paramiko implements (DSA and the RFC 6187
    SHA-1 X.509 name), followed at once by DISCONNECT. Catches: classification by exception type only (the
    surfaced error is not IncompatiblePeer-shaped after the disconnect) and any retry."""
    dev_dir = tmp_path / "lab-sw1"
    with RawResponder("kexinit_then_disconnect", kex=["diffie-hellman-group14-sha256"],
                      host_key=["ssh-dss", "x509v3-ssh-rsa"]) as peer:
        recorder = _recorder(dev_dir)
        dev, _ = C.connect_device("127.0.0.1", "lab-sw1", "lab", "lab", "ios", session=recorder, port=peer.port)
        assert dev is None and peer.connections == 1
        # Whatever the responder managed to read before the client closed: nothing past the client's own KEXINIT
        # (20) -- no KEXDH_INIT (30), no service request, no password. (A close racing the read may leave the
        # list empty; it can never hold another message type.)
        assert {t for seen in peer.client_payload_types for t in seen} <= {20}
    record = _sidecar(dev_dir)
    assert record["refusal"]["category"] == "host_key"
    assert record["refusal"]["classification"] == "refused_legacy_only"
    row = _row(dev_dir)
    assert row["status"] == "refused_legacy_only" and "no profile of this collector implements" in row["label"]


def test_t17b_sha1_only_kex_list_then_disconnect_on_a_sha2_only_library(tmp_path):
    """T17 (b) as designed: a KEXINIT with no common kex (SHA-1 only), then DISCONNECT -> refused_legacy_only,
    one attempt. Meaningful only where the library cannot negotiate SHA-1 (T7 holds the floating environment
    there)."""
    if _library_permits_sha1():
        pytest.skip("this paramiko's stock tables negotiate SHA-1; T7 fails the floating environment for it")
    dev_dir = tmp_path / "lab-sw1"
    with RawResponder("kexinit_then_disconnect", kex=[_G14_SHA1], host_key=[_RSA_SHA1]) as peer:
        recorder = _recorder(dev_dir)
        dev, _ = C.connect_device("127.0.0.1", "lab-sw1", "lab", "lab", "ios", session=recorder, port=peer.port)
        assert dev is None and peer.connections == 1
    record = _sidecar(dev_dir)
    assert (record["refusal"]["category"], record["refusal"]["classification"]) == ("kex", "refused_legacy_only")
    assert "requires the legacy-sha1 opt-in" in _row(dev_dir)["label"]
