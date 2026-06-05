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
    assert r["devices"]["core1"]["serial_number"].startswith("SN")
    assert "FOC1234X" not in json.dumps(r)
