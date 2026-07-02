"""Plan-A Tier-2 #13 (K4): an adversarial redaction leak corpus.

Multi-vendor config lines, each seeded with a UNIQUE sentinel secret value; `_scrub_secrets` must
leave ZERO sentinel surviving. This is the regression gate the share-safe promise lacked — two prior
audit waves found real misses (55 serials survived --redact once). A survivor is unambiguous because
every secret is a distinct SENTINEL token.
"""
from cisco_toolkit.html import _scrub_secrets

# (label, config line, the secret SENTINEL that must NOT survive after scrubbing)
CORPUS = [
    ("enable secret type-5", "enable secret 5 $1$mERr$SENTINELhash5xx", "SENTINELhash5xx"),
    ("enable secret type-9", "enable secret 9 $9$SENTINELscrypt9zz", "SENTINELscrypt9zz"),
    ("enable password cleartext", "enable password SENTINELenablepw", "SENTINELenablepw"),
    ("username password type-7", "username admin password 7 SENTINEL7hex0A1B", "SENTINEL7hex0A1B"),
    ("username secret type-5", "username bob secret 5 $1$aa$SENTINELusersec", "SENTINELusersec"),
    ("line password type-7", "password 7 SENTINELlinepw77", "SENTINELlinepw77"),
    ("snmp community ro", "snmp-server community SENTINELsnmpRO ro", "SENTINELsnmpRO"),
    ("snmp community rw", "snmp-server community SENTINELsnmpRW rw", "SENTINELsnmpRW"),
    ("bare community (trap host)", "snmp-server host 10.0.0.9 version 2c SENTINELtrapcomm", "SENTINELtrapcomm"),
    ("tacacs key type-7", "tacacs-server key 7 SENTINELtacacs7", "SENTINELtacacs7"),
    ("radius host key", "radius-server host 10.0.0.1 key SENTINELradiuskey", "SENTINELradiuskey"),
    ("crypto isakmp psk", "crypto isakmp key SENTINELikepsk address 0.0.0.0", "SENTINELikepsk"),
    ("ikev2 pre-shared-key", "pre-shared-key local SENTINELpsklocal", "SENTINELpsklocal"),
    ("ospf md5 auth key", "ip ospf message-digest-key 1 md5 SENTINELospfmd5", "SENTINELospfmd5"),
    ("eigrp key-string", "key-string 7 SENTINELkeystring7", "SENTINELkeystring7"),
    ("bgp neighbor password", "neighbor 10.0.0.2 password SENTINELbgppw", "SENTINELbgppw"),
    ("ppp chap password", "ppp chap password SENTINELchappw", "SENTINELchappw"),
    ("fortigate psksecret", "set psksecret SENTINELfortipsk", "SENTINELfortipsk"),
    ("fortigate passwd ENC", "set passwd ENC SENTINELfortienc", "SENTINELfortienc"),
    ("junos authentication-key", 'authentication-key "SENTINELjunoskey"', "SENTINELjunoskey"),
]


def test_no_seeded_secret_survives_scrub():
    survivors = [(label, line, out) for label, line, sentinel in CORPUS
                 for out in [_scrub_secrets(line)] if sentinel in out]
    assert not survivors, "secrets survived _scrub_secrets:\n" + "\n".join(
        f"  [{lbl}] {ln!r} -> {o!r}" for lbl, ln, o in survivors)


def test_scrub_preserves_context_and_is_idempotent():
    line = "snmp-server community SENTINELx ro"
    once = _scrub_secrets(line)
    assert "SENTINELx" not in once and "<redacted>" in once
    assert once.startswith("snmp-server community ")   # keyword context preserved, only the value replaced
    assert once.rstrip().endswith("ro")                # the trailing 'ro' access-level is NOT eaten
    assert _scrub_secrets(once) == once                # idempotent — re-scrubbing an already-scrubbed line is a no-op


def test_non_secret_structural_fields_are_untouched():
    """Conservative by design: a bare 'key chain NAME' / 'crypto ... hash md5' must not be corrupted."""
    for line in ("key chain OSPF-KEYS", "crypto isakmp policy 10", "ip address 10.0.0.1 255.255.255.0"):
        assert _scrub_secrets(line) == line
