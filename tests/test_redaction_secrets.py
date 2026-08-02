"""Secret deny-list scrub in redact_snapshot (--redact): credentials, SNMP community
strings, TACACS/RADIUS keys, and pre-shared keys must never reach the embedded snapshot.

These complement the IP/MAC/serial pseudonymization tested in test_package.py: here we
plant known credential-bearing strings in plausible string fields and assert the secret
literals do not survive anywhere in the serialized output, while non-secret structure
(hostnames, dict keys, surrounding keywords) is preserved and the pass is idempotent.
"""
import json

from cisco_toolkit import html


def _planted_snapshot() -> dict:
    """A snapshot whose free-text string fields carry assorted IOS / NX-OS secrets."""
    return {
        "devices": {"core1": {
            "hostname": "core1",
            "snmp": "snmp-server community S3cr3t-RO RO",
            "aaa": "tacacs-server key MyTacKey",
        }},
        "interfaces": {"core1": {
            "Gi1/0/1": {
                "port": "Gi1/0/1",
                "user_line": "username admin password 7 070C285F4D06",
            },
            "Tu0": {
                "port": "Tu0",
                "crypto": "crypto isakmp key MyPSK address 0.0.0.0",
            },
        }},
        "raw_config": [
            "enable secret 5 $1$mERr$EnableHashValue",
            "radius-server key 7 1234ABCD",
            "key-string MyKeyStringSecret",
            "pre-shared-key local MyPSK4",
        ],
    }


# Literals that must NOT survive anywhere in the redacted, serialized snapshot.
_SECRET_LITERALS = [
    "S3cr3t-RO", "MyTacKey", "070C285F4D06", "MyPSK",
    "EnableHashValue", "1234ABCD", "MyKeyStringSecret", "MyPSK4",
]


def test_secrets_are_scrubbed_from_snapshot():
    snap = _planted_snapshot()
    r = html.redact_snapshot(snap)
    blob = json.dumps(r)
    for secret in _SECRET_LITERALS:
        assert secret not in blob, f"secret leaked into snapshot: {secret!r}"
    # the placeholder is present where secrets were removed
    assert "<redacted>" in blob


def test_non_secret_structure_is_preserved():
    snap = _planted_snapshot()
    r = html.redact_snapshot(snap)
    dev = r["devices"]["core1"]
    # hostnames / dict keys survive (only the secret token is swapped)
    assert dev["hostname"] == "core1"
    assert set(r) == {"devices", "interfaces", "raw_config"}
    assert "core1" in r["interfaces"]
    # surrounding credential keywords are kept as context, only the value is gone
    assert dev["snmp"].startswith("snmp-server community ") and dev["snmp"].endswith(" RO")
    assert dev["aaa"] == "tacacs-server key <redacted>"
    ifs = r["interfaces"]["core1"]
    assert ifs["Gi1/0/1"]["port"] == "Gi1/0/1"
    assert ifs["Gi1/0/1"]["user_line"] == "username admin password 7 <redacted>"
    # the PSK is gone but the trailing 'address ...' context (with its IP pseudonymized) remains
    assert ifs["Tu0"]["crypto"].startswith("crypto isakmp key <redacted> address ")
    assert "MyPSK" not in ifs["Tu0"]["crypto"]


def test_secret_scrub_is_idempotent():
    snap = _planted_snapshot()
    once = html.redact_snapshot(snap)
    twice = html.redact_snapshot(once)
    assert json.dumps(once, sort_keys=True) == json.dumps(twice, sort_keys=True)
    # input is not mutated by either pass
    assert snap["devices"]["core1"]["snmp"] == "snmp-server community S3cr3t-RO RO"


def test_authentication_key_digest_scrub_preserves_algorithm_context():
    """NTP/OSPF/EIGRP 'authentication-key|message-digest-key N md5|sha|hmac-sha <SECRET>' digest forms.
    The generic '\\bkey' deny-list pattern used to capture the *algorithm* token ('md5'/'sha') and leave
    the real digest EXPOSED in a --redact deliverable (offline-crackable). The key prefix now absorbs the
    hash-algorithm label so only the secret AFTER it is redacted, while the 'md5'/'sha' context survives.
    Conservative: anchored on 'key', so a bare 'hash md5' algorithm choice is never corrupted."""
    from cisco_toolkit.html import _scrub_secrets
    assert _scrub_secrets("ntp authentication-key 1 md5 NtpMd5DigestXYZ") == \
        "ntp authentication-key 1 md5 <redacted>"
    assert _scrub_secrets("ip ospf message-digest-key 7 md5 7 OspfMd5DigestABC") == \
        "ip ospf message-digest-key 7 md5 7 <redacted>"
    assert _scrub_secrets("authentication-key 1 hmac-sha-256 ShaDigest256Val") == \
        "authentication-key 1 hmac-sha-256 <redacted>"
    # regression: standalone keychain 'key 7 <hex>' (no algorithm token) still redacts the value
    assert _scrub_secrets("key 7 02050D480809") == "key 7 <redacted>"
    # conservative — 'hash md5' as an IKE/ISAKMP algorithm choice (no key-id + secret) must NOT corrupt
    # the following structured token (this is what a broad '\\bmd5 <next>' rule would have broken)
    assert _scrub_secrets("hash md5\n encryption aes-256") == "hash md5\n encryption aes-256"
    # idempotent
    once = _scrub_secrets("ntp authentication-key 1 md5 NtpMd5DigestXYZ")
    assert _scrub_secrets(once) == once
    # end-to-end: the digest must not survive a full redact_snapshot
    snap = {"raw_config": ["ntp authentication-key 1 md5 NtpMd5DigestXYZ"]}
    assert "NtpMd5DigestXYZ" not in json.dumps(html.redact_snapshot(snap))


def test_secret_scrub_preserves_acl_wildcard_and_ip_redaction():
    # the secret pass must not disturb the existing IP/MAC/serial + ACL 'wild' behavior
    snap = {
        "acls": {"core1": {"PROTECT": [
            {"action": "permit", "proto": "tcp",
             "src": {"ip": "10.0.10.0", "wild": "0.0.0.255"},
             "raw": "permit tcp 10.0.10.0 0.0.0.255 any eq 443"},
        ]}},
        "devices": {"core1": {"serial_number": "FOC1234X"}},
    }
    r = html.redact_snapshot(snap)
    acl = r["acls"]["core1"]["PROTECT"][0]
    assert acl["src"]["wild"] == "0.0.0.255"          # mask preserved
    assert acl["src"]["ip"] != "10.0.10.0"            # IP still pseudonymized
    assert r["devices"]["core1"]["serial_number"].startswith("serial-")
    assert "FOC1234X" not in json.dumps(r)


def test_json_value_and_vendor_secrets_are_redacted():
    """The controller-REST channels (ACI / ISE / FMC / vManage) and IaC exports store a secret as a VALUE under
    a credential-named key, with NO inline keyword for the CLI deny-list to anchor on; and FortiGate uses
    'set passwd|psksecret' (not the whole words 'password'/'secret'). Both must be scrubbed by --redact. A
    generic structural 'key' field (a causal-flow id) must be PRESERVED -- it is not a secret, and a pass/fail
    COUNT keyed 'pass' must survive too."""
    snap = {
        "aci": {"login": {"token": "AABB-LeakToken-1234", "password": "Sup3rSecret!"}},
        "creds": {"apiKey": "sk-live-9f8e7d6c", "community": "PrivateRO-COMM", "client_secret": "cs-zzzz"},
        "fortigate": {"raw": ["set passwd ENC AABBenchashvalue==", "set psksecret MyVpnPreSharedKey99"]},
        "causal": [{"key": "struct-0", "title": "ok"}],
        "security": {"core1": {"summary": {"fail": 0, "pass": 9, "na": 1}}},
    }
    r = html.redact_snapshot(snap)
    blob = json.dumps(r)
    for secret in ("AABB-LeakToken-1234", "Sup3rSecret!", "sk-live-9f8e7d6c", "PrivateRO-COMM",
                   "cs-zzzz", "AABBenchashvalue==", "MyVpnPreSharedKey99"):
        assert secret not in blob, f"secret leaked into the redacted snapshot: {secret!r}"
    assert r["aci"]["login"]["token"] == "<redacted>" and r["aci"]["login"]["password"] == "<redacted>"
    assert r["creds"]["apiKey"] == "<redacted>" and r["creds"]["community"] == "<redacted>"
    assert r["creds"]["client_secret"] == "<redacted>"
    # structural 'key' field and the pass/fail COUNT must NOT be redacted
    assert r["causal"][0]["key"] == "struct-0" and r["causal"][0]["title"] == "ok"
    assert r["security"]["core1"]["summary"]["pass"] == 9


def test_controller_and_inventory_serials_are_redacted():
    """HTML_-02: ACI fabric-node 'serial' (parse_aci_fabric_nodes -> snap['aci'].nodes) and the power-supply
    'ps_serials' LIST (parse_show_inventory) reach the snapshot under key names that were not in the serial-key
    set, so they leaked verbatim under --redact. Both must now use explicit synthetic serial markers."""
    snap = {"aci": {"apic1": {"nodes": [{"name": "leaf-101", "serial": "FDO12345REAL"}]}},
            "inventory": {"sw1": {"ps_serials": ["POW1111SECRET", "POW2222SECRET"]}}}
    r = html.redact_snapshot(snap)
    blob = json.dumps(r)
    for s in ("FDO12345REAL", "POW1111SECRET", "POW2222SECRET"):
        assert s not in blob, f"serial leaked under --redact: {s}"
    assert r["aci"]["apic1"]["nodes"][0]["serial"].startswith("serial-")
    assert all(v.startswith("serial-") for v in r["inventory"]["sw1"]["ps_serials"])


def test_ipv6_addresses_are_pseudonymized():
    """HTML_-01: redact_snapshot pseudonymized IPv4 dotted-quad ONLY -- IPv6 (global, link-local, ::-compressed,
    embedded in descriptions) passed through --redact untouched, breaking the share-safe contract for any
    dual-stack / IPv6 fleet. Every IPv6 textual form must be remapped to an explicit synthetic marker,
    consistently, WITHOUT corrupting MAC remap or IPv4 remap."""
    snap = {"a": "2001:db8:10::1", "b": "2001:DB8:10::/64", "c": "FE80::200:FF:FE00:10",
            "d": "neighbor 2001:db8:10::1 remote-as 65001",
            "mixed": "host ip 10.20.30.40 mac 00:11:22:33:44:55 v6 2001:db8:abcd::99"}
    r = html.redact_snapshot(snap)
    blob = json.dumps(r)
    for leak in ("2001:db8", "2001:DB8", "FE80::200", "db8:abcd"):
        assert leak.lower() not in blob.lower(), f"IPv6 survived --redact: {leak}"
    assert "00:11:22:33:44:55" not in blob          # MAC still redacted (no IPv6/MAC collision)
    assert "10.20.30.40" not in blob                # IPv4 still redacted
    assert r["a"].startswith("v6-") and r["a"].endswith(
        ".assesshub-redacted.invalid"
    )
    assert r["a"] == r["d"].split()[1]              # same address -> same pseudonym across fields


def test_bare_key_rule_preserves_structural_follow_words():
    """HTML_-05: the generic bare-'key <secret>' rule treated the token after 'key' as a secret even when it is
    STRUCTURAL -- 'key chain <NAME>' declares a keychain (the name is not a secret), and because the rules run
    sequentially over the accumulating string the bare-key rule re-fired on the pre-shared-key rule's output and
    mangled the 'local'/'remote' direction qualifier. Those structural words must survive; a genuine key still
    redacts."""
    from cisco_toolkit.html import _scrub_secrets
    assert _scrub_secrets("key chain OSPF-KC") == "key chain OSPF-KC"          # 'chain' + name preserved
    assert _scrub_secrets("pre-shared-key local THEKEY") == "pre-shared-key local <redacted>"   # 'local' kept
    assert _scrub_secrets("pre-shared-key remote OTHERKEY") == "pre-shared-key remote <redacted>"
    assert "13061E010803" not in _scrub_secrets("key 7 13061E010803")          # genuine key still redacted


def test_redact_catches_compound_credential_key_names():
    """[multi-domain audit #6] --redact must catch COMPOUND controller/config credential field names (the real
    ISE/ACI/SNMP/wireless field names), not only exact-match keys. A secret stored as a JSON value under
    tacacsSharedSecret / roCommunity / authPassword / wpaPassphrase etc. must not survive."""
    snap = {"ise_networkdevice": {"name": "agg-1", "tacacsSharedSecret": "TAC-REAL-001", "radiusSharedSecret": "RAD-REAL-002"},
            "ise_snmp": {"roCommunity": "ROCOMM-REAL", "readCommunity": "RDCOMM-REAL"},
            "aci_snmpUserP": {"authPassword": "AUTHPW-REAL", "privPassword": "PRIVPW-REAL"},
            "device_admin": {"enablePassword": "ENABLEPW-REAL", "enableSecret": "ENSEC-REAL"},
            "wlan": {"wpaPassphrase": "WIFIPSK-REAL"}}
    blob = json.dumps(html.redact_snapshot(snap))
    for s in ("TAC-REAL-001", "RAD-REAL-002", "ROCOMM-REAL", "RDCOMM-REAL", "AUTHPW-REAL",
              "PRIVPW-REAL", "ENABLEPW-REAL", "ENSEC-REAL", "WIFIPSK-REAL"):
        assert s not in blob, f"{s} leaked through --redact"


def test_redact_catches_secret_nested_under_credential_key():
    """[multi-domain audit #7] a secret one level below a credential-named key ({'apikey':{'value':...}},
    {'password':{'data':...}}) must be redacted -- the whole subtree under a secret-named key is scrubbed."""
    snap = {"cfg": {"apikey": {"value": "NESTED-APIKEY-REAL"}},
            "creds": {"password": {"enc": "type6", "data": "NESTED-PW-REAL"}}}
    blob = json.dumps(html.redact_snapshot(snap))
    assert "NESTED-APIKEY-REAL" not in blob and "NESTED-PW-REAL" not in blob


def test_redact_preserves_generic_key_and_pass_count():
    """Regression guard: the generic 'key' structural field and pass/fail COUNT keys must NOT be over-redacted."""
    out = html.redact_snapshot({"design": {"key": "vlan-100-decision"}, "security": {"pass": 42, "passed": 7}})
    assert out["design"]["key"] == "vlan-100-decision"
    assert out["security"]["pass"] == 42 and out["security"]["passed"] == 7


def test_redact_collected_inplace_pseudonymizes_workbook_dataclasses():
    """[audit-3 #8 HIGH security] --redact pseudonymized the snapshot.json + explorer.html but the always-produced
    .xlsx (built from the raw InterfaceData/DevicePhysical dataclasses BEFORE redact_snapshot) leaked real serials,
    mgmt IPs and MACs. redact_collected_inplace must scrub them in place."""
    from cisco_toolkit.html import redact_collected_inplace
    from cisco_toolkit.model import InterfaceData, DevicePhysical
    dp = DevicePhysical(hostname="AAS13-BC", model="WS-C4948E-F", serial_number="CAT1852S14M",
                        chassis_serial="CAT1852S14M", system_mac="0000.5e00.0108")
    d = InterfaceData(port="Gi1/0/1", end_host_mac="aabb.ccdd.eeff", svi_ip="10.200.200.1",
                      current_switch_serial="FOC1949S411")
    ai = {"AAS13-BC": {"Gi1/0/1": d}}
    redact_collected_inplace(ai, [dp])
    blob = " ".join([dp.serial_number, dp.chassis_serial, dp.system_mac,
                     d.end_host_mac, d.svi_ip, d.current_switch_serial])
    for real in ("CAT1852S14M", "FOC1949S411", "10.200.200.1", "0000.5e00.0108", "aabb.ccdd.eeff", "aabb:ccdd:eeff"):
        assert real not in blob, f"real value {real!r} leaked after redaction"
    assert (
        dp.serial_number.startswith("serial-")
        and d.current_switch_serial.startswith("serial-")
    )
    assert dp.model == "WS-C4948E-F"          # non-PII fields preserved (model is not an IP/MAC/serial)
    assert dp.hostname == "AAS13-BC"          # hostnames kept (topology survives), same as redact_snapshot


def test_redact_vendor_enc_passphrase_and_junos_psk_not_stranded():
    """[audit-5 sec HIGH/MED] The deny-list runs SEQUENTIALLY, so the broad Cisco `password` and bare-`key`
    rules pre-empted the FortiGate `set password|private-key ENC <x>` and Junos `pre-shared-key ascii-text
    "<x>"` forms -- capturing the `ENC`/`ascii-text` token as the 'secret' and STRANDING the real hash / blob /
    PSK after it. `set passphrase <x>` (FortiOS WPA / SSL-VPN) was uncovered entirely. None of the encrypted
    material may survive, and the surrounding keyword context is preserved."""
    from cisco_toolkit.html import _scrub_secrets
    assert _scrub_secrets("set password ENC SH2KpL9mNvBxHash==") == "set password ENC <redacted>"
    assert _scrub_secrets("set private-key ENC AKxBlob9876") == "set private-key ENC <redacted>"
    assert _scrub_secrets("set passphrase CorpWiFiP@ssw0rd2026") == "set passphrase <redacted>"
    assert "MyJunosPSK2026" not in _scrub_secrets('pre-shared-key ascii-text "MyJunosPSK2026"')
    # regression: the digest forms that RELY on `\\bkey` matching inside the hyphenated keyword must still redact
    assert _scrub_secrets("ntp authentication-key 1 md5 NtpMd5DigestXYZ") == \
        "ntp authentication-key 1 md5 <redacted>"
    assert _scrub_secrets("ip ospf message-digest-key 7 md5 7 OspfMd5DigestABC") == \
        "ip ospf message-digest-key 7 md5 7 <redacted>"
    # end-to-end through redact_snapshot
    snap = {"raw_config": [
        "set password ENC SH2KpL9mNvBxHash==", "set private-key ENC AKxBlob9876",
        "set passphrase CorpWiFiP@ssw0rd2026", 'pre-shared-key ascii-text "MyJunosPSK2026"']}
    blob = json.dumps(html.redact_snapshot(snap))
    for s in ("SH2KpL9mNvBxHash==", "AKxBlob9876", "CorpWiFiP@ssw0rd2026", "MyJunosPSK2026"):
        assert s not in blob, f"secret leaked through --redact: {s}"


def test_redact_cdp_neighbor_chassis_serial():
    """[audit-5 sec HIGH] `show cdp neighbors detail` stores 'Device ID: <host>(<SERIAL>)' verbatim in the
    free-text cdp_neighbor field, which is NOT a serial-named key, so --redact left the real neighbor chassis
    serial in 564 cells (55 distinct). The parenthesized Cisco serial must be pseudonymized -- and consistently
    with the SAME serial under serial_number -- while the hostname (topology) is preserved."""
    snap = {
        "devices": {"AS01": {"serial_number": "FOC1830R1QS"}},
        "interfaces": {"AS01": {"Te1/1/3": {
            "port": "Te1/1/3",
            "cdp_neighbor": "MERIDIAN-SW-192.broadcast.example.net(FOC1830R1QS)"}}},
    }
    r = html.redact_snapshot(snap)
    cdp = r["interfaces"]["AS01"]["Te1/1/3"]["cdp_neighbor"]
    assert "FOC1830R1QS" not in json.dumps(r), "real chassis serial leaked via cdp_neighbor"
    assert cdp.startswith("MERIDIAN-SW-192.broadcast.example.net(")   # hostname kept (topology survives)
    sn = r["devices"]["AS01"]["serial_number"]
    assert sn.startswith("serial-") and sn in cdp


# ── W1/F2: the raw-capture scrub covered ONE extension, not the class ───────────
# `redact_collection_dir` (the producer), `redaction_verify.verify_collection_secret_scrub` (the
# "independent" verifier) and `ingest._count_txt_captures` (the census) all tested
# `endswith(".txt")`. Three matchers that agree with each other are one matcher, and
# `ingest._find_collection_root` only requires ONE `show_*.txt` per device dir -- so a folder
# holding `show_version.txt` PLUS `backup-config.cfg` / `show_tech-support.log` was fully accepted
# and the extra two were never scrubbed, never scanned and never counted, under a run that printed
# "Raw captures (--redact-collection): SCRUBBED" and exited 0.
_CAPTURE_SECRETS = (
    "enable secret 5 $1$abc$W1SuperSecretHash\n"
    "snmp-server community W1PublicSecret123 RO\n"
    "username admin password 7 070C285F4D06\n"
)
_CAPTURE_LITERALS = ("W1SuperSecretHash", "W1PublicSecret123", "070C285F4D06")


def test_the_raw_capture_scrub_covers_the_class_not_one_extension(tmp_path):
    """Run through the REAL producer, not a re-implementation of its selector.

    Non-vacuity is built in: the fixture plants the SAME three secret literals in every file, so
    the .txt column proves the scrub genuinely runs while the .cfg / .log / extensionless columns
    prove it is no longer name-gated. A `.json` controller dump is deliberately NOT rewritten (the
    deny-list is a grammar over line-oriented config text and mutating a serialised document is how
    a capture stops parsing) -- and that exclusion is DISCLOSED by the verifier below rather than
    passed off as coverage."""
    dev = tmp_path / "core1"
    dev.mkdir()
    for name in ("show_version.txt", "backup-config.cfg", "show_tech-support.log",
                 "running-config", "vendor.CFG"):
        (dev / name).write_text("hostname CORE-1\n" + _CAPTURE_SECRETS, encoding="utf-8")
    (dev / "api_dump.json").write_text(
        json.dumps({"cfg": "snmp-server community W1PublicSecret123 RO"}), encoding="utf-8")
    binary = dev / "capture.pcap"
    binary.write_bytes(b"\xd4\xc3\xb2\xa1\x00\x00enable secret 5 W1SuperSecretHash\x00\x00")
    binary_before = binary.read_bytes()

    scanned, changed = html.redact_collection_dir(str(tmp_path))

    for name in ("show_version.txt", "backup-config.cfg", "show_tech-support.log",
                 "running-config", "vendor.CFG"):
        body = (dev / name).read_text(encoding="utf-8")
        for secret in _CAPTURE_LITERALS:
            assert secret not in body, f"{name} kept cleartext {secret} after the scrub"
        assert html._REDACT_PLACEHOLDER in body, f"{name} was not actually scrubbed"
        assert "hostname CORE-1" in body, f"{name} lost non-secret context"
    assert (scanned, changed) == (5, 5), (scanned, changed)
    # A genuinely binary file is neither rewritten nor counted -- "did not protect it" must not
    # inflate the coverage number it reports.
    assert binary.read_bytes() == binary_before, "a binary capture was rewritten"


def test_the_verifier_does_not_reuse_the_producers_selector(tmp_path):
    """The postcondition must fail where the producer failed, or it is the same matcher twice.

    Fed the pre-scrub bytes the producer would have skipped, the independent verifier must REFUSE;
    fed the post-scrub bytes it must certify. Both directions, because a verifier that always
    raises proves as little as one that never does."""
    from webapp.backend import redaction_verify as rv

    dev = tmp_path / "core1"
    dev.mkdir()
    (dev / "show_version.txt").write_text("Cisco IOS XE Software\n", encoding="utf-8")
    (dev / "backup-config.cfg").write_text(_CAPTURE_SECRETS, encoding="utf-8")
    try:
        rv.verify_collection_secret_scrub(tmp_path)
    except rv.RedactionVerificationError as exc:
        assert "residue" in str(exc) and "backup-config.cfg" in str(exc), str(exc)
    else:                                            # pragma: no cover - the pre-fix behaviour
        raise AssertionError("the verifier certified a .cfg holding cleartext credentials")

    html.redact_collection_dir(str(tmp_path))
    proof = rv.verify_collection_secret_scrub(tmp_path)
    assert proof["files"] == 2, proof            # BOTH captures are inside the proof, not just .txt
    assert proof["uncovered"] == []


def test_a_proof_over_nothing_refuses_instead_of_reading_as_clean(tmp_path):
    """The empty-set corollary. A tree with no capture returned `{"files": 0}` = success, and the
    caller's `proof["files"] != census` equality was `0 != 0`, so certifying NOTHING passed every
    gate identically to certifying everything."""
    from webapp.backend import redaction_verify as rv

    dev = tmp_path / "core1"
    dev.mkdir()
    (dev / "_capture_meta.json").write_text("{}", encoding="utf-8")
    try:
        rv.verify_collection_secret_scrub(tmp_path)
    except rv.RedactionVerificationError as exc:
        assert "certified NOTHING" in str(exc), str(exc)
        assert "_capture_meta.json" in str(exc), "the skipped file must be named, not implied"
    else:                                            # pragma: no cover - the pre-fix behaviour
        raise AssertionError("an empty proof was returned as a success")

    # Non-vacuity: one real capture beside it and the same tree certifies -- while still DISCLOSING
    # the file it did not look at.
    (dev / "show_version.txt").write_text("Cisco IOS XE Software\n", encoding="utf-8")
    proof = rv.verify_collection_secret_scrub(tmp_path)
    assert proof["files"] == 1
    assert [row["file"] for row in proof["uncovered"]] == ["core1/_capture_meta.json"]


def test_the_producer_and_the_verifier_exclude_exactly_the_same_set():
    """The verifier deliberately does NOT import the producer, so the rule is stated twice — and
    two statements of one rule is the defect shape this whole fix exists to remove.

    They may not share code, but they must agree, and a drift has to break a test rather than open
    a hole: a suffix the producer stops scrubbing while the verifier still scans it turns every run
    into a false residue alarm, and the reverse ships an unscrubbed capture under a clean proof."""
    from webapp.backend import redaction_verify as rv

    producer = set(html._REDACT_SKIP_CAPTURE_SUFFIXES)
    assert producer == set(rv._STRUCTURED_CAPTURE_SUFFIXES), (
        "the scrub and its verifier disagree about what a raw capture is: "
        f"producer-only={sorted(producer - set(rv._STRUCTURED_CAPTURE_SUFFIXES))}, "
        f"verifier-only={sorted(set(rv._STRUCTURED_CAPTURE_SUFFIXES) - producer)}")
    assert html._REDACT_SCRUB_TEMP_SUFFIX == rv._SCRUB_TEMP_SUFFIX
    # ...and both really do reject every one of them, rather than merely naming them.
    for suffix in sorted(producer):
        assert not html._is_raw_capture("show_running-config" + suffix), suffix
        assert rv.is_uncoverable_capture("show_running-config" + suffix), suffix
    # Non-vacuity: the shapes the class is FOR are still captures on both sides.
    for name in ("show_version.txt", "backup-config.cfg", "show_tech-support.log",
                 "running-config", "device.out"):
        assert html._is_raw_capture(name), name
        assert rv.is_uncoverable_capture(name) == "", name


def test_the_producer_restates_the_owners_suffix_PRIMITIVE_not_a_lookalike():
    """Agreeing on the suffix SET is not enough — the two must extract the suffix the same way.

    ``is_uncoverable_capture`` is the owner of this rule and computes ``Path(name).suffix``. The
    producer restated it as ``os.path.splitext(name)[1]`` under a comment asserting the two were
    byte-for-byte identical. They are not: ``splitext`` skips EVERY leading dot of the basename and
    ``suffix`` skips only the first, so ``..json`` was a capture to one and a structured document
    to the other — the producer rewrote it in place until it stopped parsing, and the run then died
    reconciling the two counts. The set-equality test above passes either way, which is why this
    one exists."""
    import os
    from pathlib import Path

    # generated from the axes that make a suffix ambiguous, not a list of remembered examples
    names = sorted({dots + stem + tail
                    for dots in ("", ".", "..", "...")
                    for stem in ("", "show_run", "a.b", "CFG", "café")
                    for tail in ("", ".", ".txt", ".json", ".JSON", ".redacting", ".yml",
                                 ".html", ".tar.gz")} - {"", ".", ".."})

    mismatched = [n for n in names if html._capture_suffix(n) != Path(n).suffix.casefold()]
    assert mismatched == [], (
        "the producer's suffix primitive has drifted from the owner's on "
        f"{len(mismatched)} name(s): {ascii(mismatched[:12])}")

    # ANTI-TAUTOLOGY: the assertion above is only meaningful because the lookalike really does
    # answer differently — if this list is ever empty the corpus has stopped covering the class.
    lookalike = [n for n in names if os.path.splitext(n)[1].casefold() != Path(n).suffix.casefold()]
    assert lookalike, "the corpus no longer contains a name os.path.splitext reads differently"
