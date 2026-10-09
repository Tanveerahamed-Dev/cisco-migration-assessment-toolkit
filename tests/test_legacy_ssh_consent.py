"""W59 PR-2: two-level legacy-SSH consent, the one connection factory, and the run-level refusals.

Design: ``docs/w59-legacy-ssh-design-2026-10-09.md`` §4.2, §5, §6.2 and the §8 test plan:

* T6 (consent matrix) -- every (row profile, run flag) pair gives the right effective profile; a
  non-string or unknown profile, a legacy row with an empty hostname and a legacy row whose MAPPED platform is
  auto-detection are load errors; a run-flag host matching no row (or several) stops the run before any
  connection; the eligible and mismatch lists are printed, and written to disk, before the first connection; the
  flag is refused offline.
* T8 (legacy half) -- ``_open_connection`` is the only constructor of a device session (W59 PR-1's structural
  scan, shared), and patching it intercepts the legacy path.
* T16 (legacy half) -- an authorized-legacy session record that was never completed stays EXPOSED on a
  ``--no-collect`` re-analysis (``legacy_unrecorded``), never rendered as unrecorded-and-harmless.
* The paramiko < 5 refusal, the manifest consent block, the re-run advice and the AssessHub boundary.

The consent fields and block have ONE owner (``cisco_toolkit.ssh_session``); the collector validates the two
levels and calls it. Never run locally (standing hosted-only rule).
"""
import ast
import hashlib
import json
import logging
import os
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import COLLECT_PARSE_V3_23_0 as C                                  # noqa: E402
from cisco_toolkit import ssh_session as S                         # noqa: E402
from ssh_structural_support import (                               # noqa: E402
    CONNECTION_ARGUMENT_SITES, CONNECTION_CONSTRUCTOR_SITES, ENGINE, connection_constructor_calls, engine_tree,
    qualified_owners)

DEFAULT, LEGACY = S.DEFAULT_PROFILE, S.LEGACY_SHA1_PROFILE
_G14_SHA1 = S.LEGACY_SHA1_TIER_KEX[0]
_RSA_SHA1 = S.LEGACY_SHA1_TIER_HOST_KEYS[0]
_P5_CLIENT = {"kex": ["curve25519-sha256@libssh.org", "ecdh-sha2-nistp256", "diffie-hellman-group14-sha256"],
              "host_key": ["ssh-ed25519", "rsa-sha2-512", "rsa-sha2-256"], "cipher": ["aes128-ctr"],
              "mac": ["hmac-sha2-256"]}
_LEGACY_CONSENT = {"device_profile": LEGACY, "run_flag_profile": LEGACY, "named_on_run_flag": True,
                   "effective_profile": LEGACY}


def _rows(**overrides):
    base = [
        {"hostname": "lab-sw1", "ip": "192.0.2.11", "username": "u", "password": "p", "platform": "ios"},
        {"hostname": "lab-sw2", "ip": "192.0.2.12", "username": "u", "password": "p", "platform": "nxos"},
    ]
    for i, extra in overrides.items():
        base[int(i[1:])].update(extra)
    return base


def _load(rows, **kw):
    return C.load_devices("devices.json", _bound_bytes=json.dumps(rows).encode("utf-8"), **kw)


def _lib():
    return S.library_block(paramiko_version="5.0.0", netmiko_version="4.8.0", transport_class="LegacySHA1Transport",
                           default_permits_sha1=False)


@pytest.fixture(autouse=True)
def _no_backoff(monkeypatch):
    monkeypatch.setattr(C, "CONNECT_BACKOFF_BASE", 0)


# ==================================================================== T6: the device level ===
def test_t6_missing_profile_means_default_and_valid_strings_pass():
    devices = _load(_rows(r0={"ssh_profile": LEGACY}, r1={"ssh_profile": DEFAULT}))
    assert [d["ssh_profile"] for d in devices] == [LEGACY, DEFAULT]
    assert _load(_rows())[0]["ssh_profile"] == DEFAULT


@pytest.mark.parametrize("bad", [True, 1, None, [LEGACY], {"profile": LEGACY}, "yes", "LEGACY-SHA1",
                                 " " + LEGACY, ""])
def test_t6_profile_must_be_an_exact_vocabulary_string(bad):
    """Mutation caught: truthiness coercion (``true``/``"yes"`` accepted) or a fuzzy/alias match."""
    with pytest.raises(ValueError, match="ssh_profile") as info:
        _load(_rows(r0={"ssh_profile": bad}))
    assert "lab-sw1" in str(info.value) and "password" not in str(info.value)


@pytest.mark.parametrize("platform", ["asa", "auto", "", "autodetect", "junos"])
def test_t6_legacy_row_needs_a_platform_that_maps_to_ios_or_nxos(platform):
    """Mutation caught: the platform checked BEFORE ``plat_map`` (``"asa"`` silently maps to
    auto-detection, and netmiko's SSHDetect cannot take the legacy transport)."""
    with pytest.raises(ValueError, match="explicit platform"):
        _load(_rows(r0={"ssh_profile": LEGACY, "platform": platform}))
    # offline: the field's shape is validated and the platform rule (a live-only rule) is not applied
    devices = _load(_rows(r0={"ssh_profile": LEGACY, "platform": platform}), check_ssh_platform=False)
    assert devices[0]["ssh_profile"] == LEGACY and devices[0]["platform"] == "auto"


@pytest.mark.parametrize("check_ssh_platform", [True, False])
@pytest.mark.parametrize("hostname", ["", "   "])
def test_p3j_a_legacy_row_with_an_empty_hostname_is_refused(hostname, check_ssh_platform):
    """W59 PR-2 review (P3-j). Catches: a legacy request on a row with no hostname, which the consent lists, the run
    flag's recorded hosts and the session record's folder could neither name nor disclose. A default row with an
    empty hostname is not this rule's business and still loads."""
    with pytest.raises(ValueError, match="hostname") as info:
        _load(_rows(r0={"ssh_profile": LEGACY, "hostname": hostname}), check_ssh_platform=check_ssh_platform)
    assert "192.0.2.11" in str(info.value) and "password" not in str(info.value)
    assert _load(_rows(r0={"hostname": hostname}), check_ssh_platform=check_ssh_platform)[0]["ssh_profile"] == DEFAULT


# ======================================================================= T6: the run level ===
@pytest.mark.parametrize("value", [f"{LEGACY}=", f"{LEGACY}", f"{LEGACY}=a,,b", f"{LEGACY}= ,a",
                                   f"{DEFAULT}=lab-sw1", "nope=lab-sw1", f"{LEGACY.upper()}=lab-sw1", ""])
def test_t6_run_flag_needs_a_legacy_profile_and_a_non_empty_host_list(value):
    """Mutation caught: a flag without a host list accepted (a standing, unscoped grant)."""
    with pytest.raises(ValueError):
        C._parse_allow_legacy_ssh(value)


def test_t6_run_flag_parses_strips_and_collapses_repeats():
    assert C._parse_allow_legacy_ssh(f"{LEGACY}= lab-sw1 ,192.0.2.12,lab-sw1") == (
        LEGACY, ("lab-sw1", "192.0.2.12"))


_MATRIX = [
    # (row profile, run-flag names it?, expected effective profile, list it lands in)
    (None, False, DEFAULT, None),
    (None, True, DEFAULT, "named_not_requested"),
    (DEFAULT, True, DEFAULT, "named_not_requested"),
    (LEGACY, False, DEFAULT, "requested_not_named"),
    (LEGACY, True, LEGACY, "devices_eligible"),
]


@pytest.mark.parametrize("row_profile,named,effective,bucket", _MATRIX)
@pytest.mark.parametrize("name_by", ["hostname", "ip"])
def test_t6_consent_matrix(row_profile, named, effective, bucket, name_by):
    """Mutation caught: either level alone granting the legacy profile."""
    rows = _rows(r0={} if row_profile is None else {"ssh_profile": row_profile})
    devices = _load(rows)
    flag = (LEGACY, (rows[0][name_by],)) if named else None
    block = C._resolve_ssh_consent(devices, flag)
    consent = devices[0]["ssh_consent"]
    assert consent == {"device_profile": row_profile or DEFAULT,
                       "run_flag_profile": LEGACY if named else None,
                       "named_on_run_flag": named, "effective_profile": effective}
    assert consent == S.consent_for(devices[0], {"profile": LEGACY, "hosts_named": [rows[0][name_by]]}
                                    if named else None), "the per-device consent must come from the owner"
    for key in ("devices_eligible", "named_not_requested", "requested_not_named"):
        assert ("lab-sw1" in block[key]) == (key == bucket), (key, block)
    assert devices[1]["ssh_consent"]["effective_profile"] == DEFAULT
    # hosts are recorded by hostname, even when the operator named the device by IP (no address in the block)
    assert block["run_flag"]["hosts_named"] == (["lab-sw1"] if named else [])
    assert "192.0.2.11" not in json.dumps(block)
    assert block["mode"] == "live" and block["devices_negotiated_sha1"] is None and block["record_failures"] == []


@pytest.mark.parametrize("item", ["lab-sw9", "192.0.2.99", "LAB-SW1", "lab"])
def test_t6_run_flag_host_matching_no_row_stops_the_run(item):
    """Mutation caught: an unmatched (stale or mistyped) name silently ignored."""
    with pytest.raises(ValueError, match="matches no devices.json row"):
        C._resolve_ssh_consent(_load(_rows(r0={"ssh_profile": LEGACY})), (LEGACY, (item,)))


def test_t6_run_flag_host_matching_two_rows_is_ambiguous():
    rows = _rows(r1={"ip": "192.0.2.11"})
    with pytest.raises(ValueError, match="matches 2 devices.json rows"):
        C._resolve_ssh_consent(_load(rows), (LEGACY, ("192.0.2.11",)))


def test_the_flag_constant_is_the_spelling_argparse_registers():
    """The messages and AssessHub boundary use ALLOW_LEGACY_SSH_FLAG; argparse registers the literal
    (so the README-FIELD flag reconciliation can read it). They must be one spelling."""
    source = ENGINE.read_text(encoding="utf-8")
    assert C.ALLOW_LEGACY_SSH_FLAG == "--allow-legacy-ssh"
    assert f'ap.add_argument("{C.ALLOW_LEGACY_SSH_FLAG}"' in source


def test_p2d_the_consent_block_has_one_writer():
    """W59 PR-2 review (P2-d). Catches: a second consent-block writer in the collector (PR-2 once built its own live
    and offline blocks beside PR-1's, with different keys). The collector builds no block itself: it calls the
    owner, and it puts the block in custody at exactly ONE site."""
    assert not hasattr(C, "_offline_ssh_consent_block")
    offline = S.offline_consent_block()
    assert offline["mode"] == "offline" and all(v is None for k, v in offline.items() if k != "mode"), offline
    tree = engine_tree()
    owners = qualified_owners(tree)
    writers = [owners.get(id(n)) for n in ast.walk(tree) if isinstance(n, ast.Subscript)
               and isinstance(n.ctx, ast.Store) and isinstance(n.slice, ast.Constant)
               and n.slice.value == "ssh_transport_consent"]
    # main() puts the resolved block in custody once, and replaces it once with the block compute_ssh_sessions
    # completed (devices_negotiated_sha1); the manifest builder copies it into the sealed metadata.
    assert sorted(writers) == ["build_run_manifest", "main", "main"], writers
    built = [owners.get(id(n)) for n in ast.walk(tree) if isinstance(n, ast.Dict)
             and any(isinstance(k, ast.Constant) and k.value == "devices_requesting_legacy" for k in n.keys)]
    assert built == [], f"a consent block is still built outside the owner: {built}"


# ================================================ T6: printed and recorded before connecting ===
class _StopAtFirstConnection(BaseException):
    """BaseException, so connect_device's `except Exception` cannot swallow it: the run stops at the
    first connection attempt with no device ever contacted."""


def _make_template(path):
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "Interface Data"
    ws.append(["Hostname", "Port", "Status"])
    wb.save(path)


def _argv(tmp_path, *extra, rows=None, no_collect=False):
    devices = tmp_path / "devices.json"
    devices.write_text(json.dumps(rows if rows is not None else _rows(r0={"ssh_profile": LEGACY})),
                       encoding="utf-8")
    template = tmp_path / "template.xlsx"
    _make_template(str(template))
    argv = ["cisco-assess", "--devices-file", str(devices), "--template", str(template),
            "--output", str(tmp_path / "out" / "run.xlsx"), "--workers", "1",
            "--collection-dir", str(tmp_path / "collection")]
    if no_collect:
        (tmp_path / "collection").mkdir(exist_ok=True)
        argv.append("--no-collect")
    return argv + list(extra)


def test_t6_eligible_hosts_are_printed_and_recorded_on_disk_before_the_first_connection(
        tmp_path, monkeypatch, caplog):
    """W59 PR-2 review (P3-h). Catches: the consent "recorded before the first connection" only in memory (a run
    that dies mid-collection then leaves no record of the consent it contacted devices under). At the first
    connection the run's `.incomplete.json` marker is already on disk, stage ``collection_started``, carrying the
    custody block; the run dies there, and the marker is still on disk afterwards."""
    from cisco_toolkit import legacy_ssh

    monkeypatch.setattr(legacy_ssh, "default_permits_sha1", lambda: False)   # environment-independent preflight
    marker = tmp_path / "out" / "run.incomplete.json"
    seen = {}

    def _first_connection(kwargs, platform, profile, recorder):
        seen["profile"] = profile
        seen["recorder_profile"] = recorder.effective_profile
        seen["consent"] = json.loads(json.dumps(C._RUN_CUSTODY.get("ssh_transport_consent")))
        seen["log"] = [(r.levelno, r.getMessage()) for r in caplog.records]
        seen["marker"] = json.loads(marker.read_text(encoding="utf-8")) if marker.is_file() else None
        raise _StopAtFirstConnection()

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(C, "_open_connection", _first_connection)
    monkeypatch.setattr(sys, "argv", _argv(tmp_path, C.ALLOW_LEGACY_SSH_FLAG, f"{LEGACY}=lab-sw1"))
    with caplog.at_level(logging.INFO, logger=C.logger.name), pytest.raises(_StopAtFirstConnection):
        C.main()
    assert seen["profile"] == LEGACY == seen["recorder_profile"], "the eligible device was not routed to legacy"
    assert seen["consent"]["devices_eligible"] == ["lab-sw1"]
    assert seen["consent"]["run_flag"] == {"profile": LEGACY, "hosts_named": ["lab-sw1"]}
    assert any(level >= logging.WARNING and "eligible" in m and "lab-sw1" in m for level, m in seen["log"]), \
        seen["log"]
    on_disk = seen["marker"]
    assert on_disk is not None, "the consent was not on disk before the first connection"
    assert on_disk["status"] == "incomplete" and on_disk["stage"] == C.INCOMPLETE_STAGE_COLLECTION_STARTED
    assert on_disk["ssh_transport_consent"] == seen["consent"]
    after = json.loads(marker.read_text(encoding="utf-8"))
    assert after["stage"] == C.INCOMPLETE_STAGE_COLLECTION_STARTED, "the crash left no durable consent record"


def test_p3h_the_marker_carries_the_consent_and_commits_to_an_oversized_one(tmp_path, monkeypatch):
    """W59 PR-2 review (P3-h). The marker writer itself: the stage and the custody consent block are written; a
    block that would outgrow the marker's bound is replaced by a SHA-256 commitment to its canonical bytes rather
    than failing the run or dropping the record."""
    block = S.live_consent_block(_load(_rows(r0={"ssh_profile": LEGACY})), None)
    custody = {"run_id": "r", "generated_at": "t", "base": str(tmp_path / "run"), "inputs": [], "evidence": {},
               "mandatory_failures": {}, "ssh_transport_consent": block}
    monkeypatch.setattr(C, "_RUN_CUSTODY", custody)
    path = tmp_path / "run.incomplete.json"
    C._write_incomplete_marker(str(path), str(tmp_path / "run.run_manifest.json"), False,
                               stage=C.INCOMPLETE_STAGE_COLLECTION_STARTED)
    marker = json.loads(path.read_text(encoding="utf-8"))
    assert marker["stage"] == "collection_started" and marker["ssh_transport_consent"] == block
    big = dict(block, devices_requesting_legacy=[f"lab-sw{i:05d}" for i in range(9000)])
    custody["ssh_transport_consent"] = big
    C._write_incomplete_marker(str(path), str(tmp_path / "run.run_manifest.json"), False)
    marker = json.loads(path.read_text(encoding="utf-8"))
    assert marker["stage"] == C.INCOMPLETE_STAGE_FINALIZATION
    canonical = json.dumps(big, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    assert marker["ssh_transport_consent"] == {"mode": "live", "omitted": "exceeds the marker's size bound",
                                               "sha256": hashlib.sha256(canonical).hexdigest()}
    assert path.stat().st_size <= 64 * 1024


def test_t6_unmatched_run_flag_host_stops_before_any_connection(tmp_path, monkeypatch):
    def _never(*_a, **_k):
        raise AssertionError("a device was contacted although the run flag named an unknown host")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(C, "_open_connection", _never)
    monkeypatch.setattr(sys, "argv", _argv(tmp_path, C.ALLOW_LEGACY_SSH_FLAG, f"{LEGACY}=lab-sw9"))
    with pytest.raises(SystemExit) as info:
        C.main()
    assert info.value.code == 2
    assert not (tmp_path / "out").exists(), "outputs were created before the consent was resolved"


@pytest.mark.parametrize("mode", [["--no-collect"], []])
def test_t6_run_flag_is_refused_offline_and_when_repeated(tmp_path, monkeypatch, mode):
    monkeypatch.chdir(tmp_path)
    extra = [C.ALLOW_LEGACY_SSH_FLAG, f"{LEGACY}=lab-sw1"]
    if not mode:      # given twice on a live run
        extra += [C.ALLOW_LEGACY_SSH_FLAG, f"{LEGACY}=lab-sw2"]
    monkeypatch.setattr(sys, "argv", _argv(tmp_path, *extra, no_collect=bool(mode)))
    with pytest.raises(SystemExit) as info:
        C.main()
    assert info.value.code == 2


# ============================================================ paramiko < 5: refuse to start ===
def test_legacy_run_refuses_to_start_when_stock_paramiko_permits_sha1(tmp_path, monkeypatch):
    """Under paramiko < 5 (or netmiko[par4]) every device negotiates SHA-1 anyway, so the opt-in would
    add nothing; the run stops before any connection, and before any output, and names the fix."""
    from cisco_toolkit import legacy_ssh
    monkeypatch.setattr(legacy_ssh, "default_permits_sha1", lambda: True)
    devices = _load(_rows(r0={"ssh_profile": LEGACY}))
    block = C._resolve_ssh_consent(devices, (LEGACY, ("lab-sw1",)))
    reason = C._legacy_ssh_preflight(block)
    assert reason and "paramiko" in reason and "no device was contacted" in reason

    def _never(*_a, **_k):
        raise AssertionError("a device was contacted although the preflight must refuse")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(C, "_open_connection", _never)
    monkeypatch.setattr(sys, "argv", _argv(tmp_path, C.ALLOW_LEGACY_SSH_FLAG, f"{LEGACY}=lab-sw1"))
    with pytest.raises(SystemExit) as info:
        C.main()
    assert info.value.code == 2
    assert not (tmp_path / "out").exists()


def test_preflight_is_silent_for_a_default_only_run(monkeypatch):
    """A run with no effective-legacy device never consults (or imports) the tier."""
    devices = _load(_rows(r0={"ssh_profile": LEGACY}))           # requested, not named
    block = C._resolve_ssh_consent(devices, None)
    assert C._legacy_ssh_preflight(block) is None


# ================================================================ T8: the one factory seam ===
def test_t8_open_connection_is_the_only_constructor_of_a_device_session():
    """W59 PR-2 review (P3-e): the SAME structural taint scan as W59 PR-1's T8 (``tests/ssh_structural_support.py``),
    replacing a named-subset spelling match that ``_netmiko.ConnectHandler(...)``, ``CLASS_MAPPER[...](...)`` or an
    aliased class map walked past. Every connection-capable callee is called only at the four named sites
    (``_open_connection``; the platform auto-detection probe's SSHDetect, the one named exception; the factory's
    two internal hooks), with the legacy branch adding none; a connection-capable value is handed to other code only
    at W59 PR-1's three named argument sites, with the legacy branch adding none; and ``cisco_toolkit.legacy_ssh`` is
    imported only, lazily, by the transport resolver and the consent preflight."""
    tree = engine_tree()
    found, passes, _tainted, factories = connection_constructor_calls(tree)
    assert found == CONNECTION_CONSTRUCTOR_SITES, found
    assert passes == CONNECTION_ARGUMENT_SITES, passes
    assert {"_observed_driver_for", "_transport_for_profile"} <= factories, factories
    owners = qualified_owners(tree)
    importers = sorted(owners.get(id(n)) for n in ast.walk(tree)
                       if (isinstance(n, ast.ImportFrom) and any(a.name == "legacy_ssh" for a in n.names))
                       or (isinstance(n, ast.ImportFrom) and (n.module or "").endswith("legacy_ssh"))
                       or (isinstance(n, ast.Import) and any(a.name.endswith("legacy_ssh") for a in n.names)))
    assert importers == ["_legacy_ssh_preflight", "_transport_for_profile"], importers
    # the collector's own comment names the exception the structural guard allows
    source = ENGINE.read_text(encoding="utf-8")
    assert "with ONE named exception: the\n# platform auto-detection probe (`autodetect_platform`), whose netmiko SSHDetect" \
        in source


def test_t8_patching_the_factory_intercepts_the_legacy_path(monkeypatch):
    calls = []

    class _Dev:
        def send_command(self, cmd, read_timeout=None):
            return "ok"

    def _fake(kwargs, platform, profile, recorder):
        calls.append((kwargs["host"], platform, profile, recorder.effective_profile))
        return _Dev()

    monkeypatch.setattr(C, "_open_connection", _fake)
    recorder = S.SessionRecorder(None, consent=_LEGACY_CONSENT, library=_lib())
    dev, platform = C.connect_device("192.0.2.11", "lab-sw1", "u", "p", "ios", session=recorder)
    assert dev is not None and platform == "ios"
    assert calls == [("192.0.2.11", "ios", LEGACY, LEGACY)]


def test_legacy_profile_with_auto_platform_is_refused_at_the_last_seam(monkeypatch):
    """Defence in depth behind the load-time rule: no autodetect session for a legacy device, and the refusal is
    recorded (``connect_failed``, ``SshProfileRefused``), never silent."""
    monkeypatch.setattr(C, "_open_connection", lambda *a, **k: pytest.fail("connected"))
    monkeypatch.setattr(C, "SSHDetect", lambda **k: pytest.fail("autodetected"))
    recorder = S.SessionRecorder(None, consent=_LEGACY_CONSENT, library=_lib())
    dev, _ = C.connect_device("192.0.2.11", "lab-sw1", "u", "p", "auto", session=recorder)
    assert dev is None
    assert (recorder.record["outcome"], recorder.record["failure_class"], recorder.record["attempts"]) == \
        ("connect_failed", "SshProfileRefused", 0)


def test_a_profile_the_tier_cannot_honour_is_never_retried(monkeypatch):
    attempts = []

    def _refusing(kwargs, platform, profile, recorder):
        attempts.append(profile)
        raise C.SshProfileRefused("unavailable")

    monkeypatch.setattr(C, "_open_connection", _refusing)
    recorder = S.SessionRecorder(None, consent=_LEGACY_CONSENT, library=_lib())
    dev, _ = C.connect_device("192.0.2.11", "lab-sw1", "u", "p", "ios", session=recorder)
    assert dev is None and attempts == [LEGACY] and recorder.attempts == 1
    assert (recorder.record["outcome"], recorder.record["failure_class"]) == ("connect_failed", "SshProfileRefused")


def test_p2d_the_legacy_record_names_the_legacy_transport_class(monkeypatch):
    """W59 PR-2 review (P2-d). Catches: an effective-legacy device's session record claiming the DEFAULT observed
    transport (the library block is per profile), or the class name built anywhere but from the class itself."""
    from cisco_toolkit import legacy_ssh

    monkeypatch.setattr(legacy_ssh, "default_permits_sha1", lambda: False)
    devices = _load(_rows(r0={"ssh_profile": LEGACY}))
    C._resolve_ssh_consent(devices, (LEGACY, ("lab-sw1",)))
    legacy_rec, default_rec = (C._session_recorder_for(d, None) for d in devices)
    assert legacy_rec.effective_profile == LEGACY and default_rec.effective_profile == DEFAULT
    assert legacy_rec.library["transport_class"] == legacy_ssh.LegacySHA1Transport.__name__
    assert default_rec.library["transport_class"] == C.ObservedTransport.__name__
    monkeypatch.setattr(legacy_ssh, "default_permits_sha1", lambda: True)
    assert C._session_recorder_for(devices[0], None).library["transport_class"] is None


# ===================================================== P3-g: re-run advice only for a classified refusal ===
def _record(outcome, refusal=None, consent=None):
    consent = consent or {"device_profile": LEGACY, "run_flag_profile": None, "named_on_run_flag": False,
                          "effective_profile": DEFAULT}

    class _Rec:
        pass

    rec = _Rec()
    rec.consent = consent
    rec.record = S.build_record(outcome=outcome, consent=consent, library=_lib(), attempts=1, refusal=refusal)
    return rec


_WITHIN = {"category": "kex", "classification": "refused_legacy_only", "detail": "no_common_kex",
           "offered_group_bits": None, "names": [_G14_SHA1]}


@pytest.mark.parametrize("outcome,refusal,consent,advised", [
    ("negotiation_refused", _WITHIN, None, True),
    ("auth_failed", None, None, False),
    ("connect_failed", None, None, False),                     # a timeout or an unreachable host
    ("negotiation_refused", dict(_WITHIN, names=["ssh-dss"], category="host_key", detail="no_common_host_key"),
     None, False),                                             # outside the tier: no profile implements it
    ("negotiation_refused", dict(_WITHIN, classification="refused_weak_dh", detail="weak_group_refused",
                                 offered_group_bits=1024, names=[]), None, False),
    ("negotiation_refused", dict(_WITHIN, classification="refused_unsupported_modern"), None, False),
    ("negotiation_refused", _WITHIN, _LEGACY_CONSENT, False),  # already effective: the opt-in was given
    ("negotiation_refused", _WITHIN, {"device_profile": DEFAULT, "run_flag_profile": None,
                                      "named_on_run_flag": False, "effective_profile": DEFAULT}, False),
])
def test_p3g_rerun_advice_only_for_a_classified_refusal_within_the_tier(outcome, refusal, consent, advised):
    """W59 PR-2 review (P3-g). Catches: the ``[LEGACY-SSH]`` re-run advice given on an authentication failure, a
    timeout or an unreachable host (the old rule fired on ANY failure of a legacy-requesting row), or pointing at
    the opt-in for a refusal it cannot change."""
    advice = C._legacy_ssh_rerun_advice("lab-sw1", _record(outcome, refusal, consent))
    assert bool(advice) is advised, advice
    if advised:
        assert advice.startswith("[LEGACY-SSH] lab-sw1:") and f"{C.ALLOW_LEGACY_SSH_FLAG} {LEGACY}=lab-sw1" in advice


@pytest.mark.parametrize("failure", ["refusal", "auth", "timeout"])
def test_p3g_the_live_device_path_advises_only_on_the_refusal(failure, monkeypatch, tmp_path, caplog):
    """The same rule through the collector's real per-device path (`_collect_live_device`), with the factory patched
    to fail the way each case does."""
    def _open(kwargs, platform, profile, recorder):
        if failure == "refusal":
            obs = recorder.observation
            obs.server = {"kex": [_G14_SHA1], "host_key": [_RSA_SHA1], "cipher_c2s": ["aes128-ctr"],
                          "cipher_s2c": ["aes128-ctr"], "mac_c2s": ["hmac-sha2-256"], "mac_s2c": ["hmac-sha2-256"]}
            obs.client, obs.kexinit_seen = _P5_CLIENT, True
            raise EOFError("disconnected after KEXINIT")
        if failure == "auth":
            raise RuntimeError("Authentication failed.")
        raise TimeoutError("timed out")

    monkeypatch.setattr(C, "_open_connection", _open)
    monkeypatch.setattr(C, "CONNECT_MAX_ATTEMPTS", 2)
    devices = _load(_rows(r0={"ssh_profile": LEGACY}))
    C._resolve_ssh_consent(devices, None)                       # requested by the row, not named by the run
    with caplog.at_level(logging.INFO, logger=C.logger.name):
        _platform, cmd = C._collect_live_device(devices[0], str(tmp_path / "lab-sw1"), claimed=set(),
                                                lock=threading.Lock(), on_record_failure=lambda *a: None)
    assert cmd is None
    advice = [r.getMessage() for r in caplog.records if "[LEGACY-SSH]" in r.getMessage()]
    assert bool(advice) is (failure == "refusal"), advice


# ===================================================================== manifest consent block ===
def test_run_manifest_seals_the_consent_block(tmp_path):
    devices = _load(_rows(r0={"ssh_profile": LEGACY}))
    block = C._resolve_ssh_consent(devices, (LEGACY, ("lab-sw1",)))
    out = tmp_path / "run.xlsx"
    custody = {"base": os.path.splitext(str(out))[0], "inputs": [], "ssh_transport_consent": block}
    man = C.build_run_manifest(str(out), {}, artifact_registry={}, custody=custody)
    assert man["metadata"]["ssh_transport_consent"] == block
    sealed = next(r for r in man["chain"] if r.get("stage") == "seal_metadata")
    assert sealed["metadata"]["ssh_transport_consent"] == block, "the consent block must be inside the seal"


# ======================================================================= AssessHub boundary ===
def test_assesshub_has_no_opt_in_surface():
    """AssessHub never collects live: it must never pass the run-level flag (design §5)."""
    offenders = [p.relative_to(ROOT).as_posix() for p in (ROOT / "webapp" / "backend").rglob("*.py")
                 if C.ALLOW_LEGACY_SSH_FLAG in p.read_text(encoding="utf-8")]
    assert not offenders, f"{C.ALLOW_LEGACY_SSH_FLAG} appears in the AssessHub backend: {offenders}"


# =============================================== T16 (legacy half): an unfinished record stays exposed ===
def test_t16_pending_legacy_record_is_exposed_on_offline_reanalysis(tmp_path, monkeypatch):
    """A device the run AUTHORIZED for SHA-1 whose session record was never completed is
    ``legacy_unrecorded`` and EXPOSED on every later ``--no-collect`` re-analysis: the design cannot show
    it was not collected over SHA-1. Mutation caught: a ``pending`` legacy record rendered
    ``not_recorded``/``unknown`` (absence rendered as health). The record is built and rendered by the PR-1 owner
    (closed ``ssh_session/1`` schema, written at step 1 of §6.1)."""
    import synthetic_fixtures as fx

    collection = Path(fx.write_collection(str(tmp_path / "collection")))
    host = fx.DEVICES[0]["hostname"]
    pending = S.build_record(outcome="pending", consent=_LEGACY_CONSENT, library=_lib())
    assert S.validate_record(pending) == []
    (collection / host / S.SIDECAR_FILENAME).write_bytes(S.render_record(pending))
    devices = tmp_path / "devices.json"
    devices.write_text(json.dumps(fx.DEVICES), encoding="utf-8")
    template = tmp_path / "template.xlsx"
    _make_template(str(template))
    out = tmp_path / "out.xlsx"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", [
        "cisco-assess", "--no-collect", "--collection-dir", str(collection),
        "--devices-file", str(devices), "--template", str(template), "--output", str(out),
        "--workers", "1", "--no-html", "--no-docx", "--no-pptx", "--no-design", "--no-mop", "--no-crd",
        "--no-engagement", "--no-opshandbook", "--no-archreview"])
    C.main()
    snap = json.loads((tmp_path / "out.snapshot.json").read_text(encoding="utf-8"))
    rows = {r["host"]: r for r in snap["ssh_sessions"]["rows"]}
    row = rows[host]
    assert row["status"] == "legacy_unrecorded" and row["severity"] == "Medium", row
    assert row["effective_profile"] == LEGACY, "consent must come from the sealed sidecar"
    manifest = json.loads((tmp_path / "out.run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["metadata"]["ssh_transport_consent"] == S.offline_consent_block()
    assert not (tmp_path / "out.incomplete.json").exists(), "an offline run writes no pre-collection marker"
