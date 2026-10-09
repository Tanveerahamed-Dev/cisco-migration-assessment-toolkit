"""W59 PR-1, T15: AssessHub ingest and collection redaction of the per-device SSH session record.

A device whose SSH negotiation was REFUSED at collection has a folder holding only `_ssh_session.json` and no
`show_*.txt`. Ingest must keep that device (and with it the refusal finding), the synthesized devices.json must
never carry consent (`ssh_profile`), and `--redact-collection` must report a VALID record as covered by its
closed schema -- while a record that does not conform stays NOT COVERED, exactly like any unknown file.

The redaction verifier restates the record's schema independently (it never imports the producer side); the
agreement test below holds the owner (`cisco_toolkit.ssh_session.validate_record`) and the verifier's
statement (`redaction_verify._ssh_session_record_conforms`) together over generated and mutated records.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from cisco_toolkit import ssh_session as S
from webapp.backend import ingest as ing
from webapp.backend import redaction_verify as rv

_G14_SHA1 = S.LEGACY_SHA1_TIER_KEX[0]
_RSA_SHA1 = S.LEGACY_SHA1_TIER_HOST_KEYS[0]


def _refused_record() -> dict:
    """A refused_legacy_only record built by the REAL producer path (sink snapshot -> classify -> build)."""
    lib = S.library_block(paramiko_version="5.0.0", netmiko_version="4.8.0", transport_class="ObservedTransport",
                          default_permits_sha1=False)
    obs = S.SessionObservation()
    obs.server = {"kex": [_G14_SHA1, "ext-info-s"], "host_key": [_RSA_SHA1], "cipher_c2s": ["aes128-ctr"],
                  "cipher_s2c": ["aes128-ctr"], "mac_c2s": ["hmac-sha2-256"], "mac_s2c": ["hmac-sha2-256"]}
    obs.client = {"kex": ["curve25519-sha256@libssh.org", "ecdh-sha2-nistp256"],
                  "host_key": ["ssh-ed25519", "rsa-sha2-512"], "cipher": ["aes128-ctr"], "mac": ["hmac-sha2-256"]}
    obs.kexinit_seen = True
    refusal = S.classify_failure(EOFError(), obs)
    assert refusal and refusal["classification"] == "refused_legacy_only"
    return S.build_record(outcome="negotiation_refused", consent=S.consent_for({}), library=lib, attempts=1,
                          observation=obs.snapshot(), refusal=refusal, failure_class="NetmikoTimeoutException")


def _established_record() -> dict:
    lib = S.library_block(paramiko_version="4.0.0", netmiko_version="4.7.0", transport_class="ObservedTransport",
                          default_permits_sha1=True)
    neg = {"kex": "ecdh-sha2-nistp256", "kex_hash_bytes": 32, "dh_group_bits": None,
           "host_key_algorithm": "rsa-sha2-512", "cipher_c2s": "aes128-ctr", "cipher_s2c": "aes128-ctr",
           "mac_c2s": "hmac-sha2-256", "mac_s2c": "hmac-sha2-256", "strict_kex": True,
           "server_software": "SSH-2.0-Cisco-1.25"}
    snap = {"kexinit": True, "newkeys": True, "negotiated": neg,
            "server": {"kex": ["ecdh-sha2-nistp256"], "host_key": ["rsa-sha2-512"], "cipher_c2s": ["aes128-ctr"],
                       "cipher_s2c": ["aes128-ctr"], "mac_c2s": ["hmac-sha2-256"], "mac_s2c": ["hmac-sha2-256"]},
            "client": {"kex": ["ecdh-sha2-nistp256"], "host_key": ["rsa-sha2-512"], "cipher": ["aes128-ctr"],
                       "mac": ["hmac-sha2-256"]},
            "engine_name_agrees": True, "group_size_agrees": None, "dropped": 0}
    return S.build_record(outcome="established", consent=S.consent_for({}), library=lib, attempts=1,
                          observation=snap)


def _write_record(folder: Path, record: dict) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / S.SIDECAR_FILENAME
    path.write_bytes(S.render_record(record))
    return path


# =================================================================================== ingest (section 6.4) ===
def test_a_session_record_only_folder_is_a_device_not_a_dropped_folder(tmp_path):
    """T15. Catches: `_find_collection_root` counting only folders with show_*.txt, which silently dropped a
    refused device -- and its refusal finding -- from the assessed fleet."""
    fleet = tmp_path / "export" / "fleet"
    (fleet / "core1").mkdir(parents=True)
    (fleet / "core1" / "show_version.txt").write_text("Cisco IOS XE Software\n", encoding="utf-8")
    _write_record(fleet / "edge1", _refused_record())
    root, devices = ing._find_collection_root(tmp_path)
    assert root == fleet and devices == ["core1", "edge1"]


def test_a_session_record_at_the_archive_root_gets_the_actionable_message(tmp_path):
    _write_record(tmp_path, _refused_record())
    with pytest.raises(ing.IngestError, match="own folder"):
        ing._find_collection_root(tmp_path)


def test_the_synthesized_devices_file_never_carries_consent(tmp_path):
    """T15 / design section 6.4. Catches: consent re-derived from a bundled or synthesized devices.json (the
    snapshot's consent fields come only from the sealed record)."""
    fleet = tmp_path / "fleet"
    (fleet / "core1").mkdir(parents=True)
    (fleet / "core1" / "show_version.txt").write_text("x\n", encoding="utf-8")
    _write_record(fleet / "edge1", _refused_record())
    (fleet / "devices.json").write_text(json.dumps([
        {"hostname": "core1", "platform": "ios", "ssh_profile": S.LEGACY_SHA1_PROFILE},
        {"hostname": "edge1", "ssh_profile": S.LEGACY_SHA1_PROFILE}]), encoding="utf-8")
    devices, provenance, skipped = ing._load_or_synthesize_devices(fleet, tmp_path, ["core1", "edge1"])
    assert provenance == "bundled" and skipped == []
    assert sorted(d["hostname"] for d in devices) == ["core1", "edge1"]
    assert all("ssh_profile" not in d for d in devices), devices


def test_ingest_keeps_a_refused_device_and_its_finding(tmp_path):
    """T15, end to end through the real engine child (--no-collect). Catches: a sidecar-only folder dropped at
    ingest, the record not read through custody, or the refusal not projected into Software Risk."""
    import synthetic_fixtures as fx

    src = tmp_path / "fleet"
    fx.write_collection(str(src))
    _write_record(src / "edge1", _refused_record())
    snap, report = ing.run_collection_folder(str(src))
    assert "edge1" in report["devices"]
    rows = {r["host"]: r for r in snap["ssh_sessions"]["rows"]}
    assert rows["edge1"]["status"] == "refused_legacy_only" and rows["edge1"]["finding"] == "exposed"
    assert rows["edge1"]["evidence"] == f"edge1/{S.SIDECAR_FILENAME}"
    assert {rows[h]["status"] for h in ("core1", "core2", "access1")} == {"not_recorded"}
    assert snap["ssh_sessions"]["consent"]["mode"] == "offline"
    findings = [f for f in snap["software_risk"]["findings"] if f["kind"] == S.SURFACE_KIND]
    assert [(f["host"], f["severity"]) for f in findings] == [("edge1", "Medium")]


# ================================================================================ redaction (section 6.4) ===
def test_a_valid_record_is_covered_by_schema_not_reported_not_covered(tmp_path):
    """T15. Catches: every W59 collection adding one permanent NOT COVERED file per device (noise that buries
    the signal), on the verifier AND the producer."""
    from cisco_toolkit import html

    fleet = tmp_path / "fleet"
    (fleet / "core1").mkdir(parents=True)
    (fleet / "core1" / "show_version.txt").write_text("Cisco IOS XE Software\n", encoding="utf-8")
    _write_record(fleet / "core1", _established_record())
    _write_record(fleet / "edge1", _refused_record())
    proof = rv.verify_collection_secret_scrub(fleet)
    assert proof["files"] == 1 and proof["uncovered"] == []
    assert proof["schema_covered"] == [f"core1/{S.SIDECAR_FILENAME}", f"edge1/{S.SIDECAR_FILENAME}"]
    produced = html.redact_collection_dir(str(fleet))
    assert tuple(produced) == (1, 0) and produced.uncovered == ()
    assert sorted(produced.schema_covered) == proof["schema_covered"]


def test_a_non_conforming_record_stays_not_covered(tmp_path):
    """T15. Catches: the file NAME alone vouching for a record that carries identifying text."""
    fleet = tmp_path / "fleet"
    (fleet / "core1").mkdir(parents=True)
    (fleet / "core1" / "show_version.txt").write_text("Cisco IOS XE Software\n", encoding="utf-8")
    bad = _established_record()
    bad["negotiated"]["server_software"] = "SSH-2.0-core1.example.net_10.20.30.40"
    (fleet / "core1" / S.SIDECAR_FILENAME).write_text(json.dumps(bad), encoding="utf-8")
    proof = rv.verify_collection_secret_scrub(fleet)
    assert proof["schema_covered"] == []
    assert [row["file"] for row in proof["uncovered"]] == [f"core1/{S.SIDECAR_FILENAME}"]
    assert "closed schema" in proof["uncovered"][0]["reason"]


def _mutations():
    yield "hostname key", lambda r: r.update(hostname="core1")
    yield "fingerprint key", lambda r: r["host_key"].update(fingerprint="aa")
    yield "ip in a name", lambda r: r["server_offered"]["kex"].append("x-10.1.2.3")
    yield "mac in a name", lambda r: r["server_offered"]["kex"].append("x-0011.2233.4455")
    yield "space in a name", lambda r: r["server_offered"]["kex"].append("a b")
    yield "colon in a name", lambda r: r["server_offered"]["kex"].append("SHA256:abc")
    yield "float", lambda r: r.update(attempts=1.5)
    yield "deep nesting", lambda r: r.update(library={"a": {"b": {"c": {"d": {"e": 1}}}}})
    yield "wrong schema", lambda r: r.update(schema="ssh_session/2")
    # W59 PR-1 review (P3-e): grammar-conforming device-controlled text -- an organisation or host name in an offered
    # name, a refusal name, a negotiated name or a custom banner -- is outside the vocabulary and the banner grammar
    yield "org name in an offered name", lambda r: r["server_offered"]["kex"].append("acme-corp-hq")
    yield "org name in a client list", lambda r: r["client_offered"]["mac"].append("acme-mac")
    yield "org name in a negotiated name", lambda r: r.update(negotiated=dict(
        r["negotiated"] or _established_record()["negotiated"], cipher_c2s="acme-cipher"))
    yield "org name in the banner", lambda r: r.update(negotiated=dict(
        r["negotiated"] or _established_record()["negotiated"], server_software="SSH-2.0-AcmeCorp_1.0"))
    yield "org name in a refusal name", lambda r: r.update(refusal=dict(
        r["refusal"] or {"category": "kex", "classification": "unclassified", "detail": "incompatible_peer",
                         "offered_group_bits": None, "names": []}, names=["acme-corp-hq"]))


@pytest.mark.parametrize("label, mutate", list(_mutations()))
def test_the_owner_schema_and_the_verifier_statement_agree(label, mutate):
    """The verifier restates the schema independently; a drift must break a test, not open a hole. Every
    generated record conforms to both statements, and every identifying mutation is refused by both."""
    for make in (_refused_record, _established_record):
        good = make()
        assert S.validate_record(good) == []
        assert rv._ssh_session_record_conforms(S.render_record(good))
        bad = json.loads(json.dumps(good))
        mutate(bad)
        raw = json.dumps(bad).encode("utf-8")
        assert S.validate_record(bad), label
        assert not rv._ssh_session_record_conforms(raw), label


# ================================================ the whole closed schema, every leaf (design re-check P2) ===
def _producer_records() -> dict:
    """One record per shape the producer writes, each through its REAL path: a list-classified refusal, an
    established session, a ``pending`` record from ``SessionRecorder.write_pending`` (legacy consent), an
    authentication failure and a connection failure with no key exchange (autodetect), and a weak-group refusal
    classified from the exception chain alone."""
    lib = S.library_block(paramiko_version="5.0.0", netmiko_version="4.8.0", transport_class="ObservedTransport",
                          default_permits_sha1=False)
    recorder = S.SessionRecorder(None, consent={"device_profile": S.LEGACY_SHA1_PROFILE,
                                                "run_flag_profile": S.LEGACY_SHA1_PROFILE,
                                                "named_on_run_flag": True,
                                                "effective_profile": S.LEGACY_SHA1_PROFILE}, library=lib)
    recorder.write_pending()

    class _WeakGroupRefused(Exception):
        def __init__(self, bits):
            super().__init__("weak group")
            self.offered_bits = bits

    _WeakGroupRefused.__name__ = "WeakGroupRefused"
    weak = S.classify_failure(_WeakGroupRefused(1024), S.SessionObservation())
    return {
        "refused": _refused_record(),
        "established": _established_record(),
        "pending": recorder.record,
        "auth_failed": S.build_record(outcome="auth_failed", consent=S.consent_for({}), library=lib, attempts=2,
                                      failure_class="NetmikoAuthenticationException"),
        "connect_failed": S.build_record(outcome="connect_failed", consent=S.consent_for({}), library=lib, attempts=3,
                                         platform_source="autodetect", failure_class="NetmikoTimeoutException"),
        "weak_group": S.build_record(outcome="negotiation_refused", consent=S.consent_for({}), library=lib,
                                     attempts=1, refusal=weak, failure_class="NetmikoTimeoutException"),
    }


#: The values every leaf is replaced by: device-controlled text (an organisation, a host and an address), an empty
#: string, an identifier, a version, a custom banner, numbers at and beyond every range edge, both booleans (and the
#: numbers that compare equal to them), null, a float, empty and non-empty containers -- plus, below, EVERY member of
#: every enum the owner publishes, so an enum value moved to the wrong position and both cross-field rules are hit.
_LEAF_VALUES = ("acme-corp-hq", "core1.example.net", "10.20.30.40", "", "AcmeCorp", "5.0.0", "SSH-2.0-AcmeCorp_1.0",
                "SSH-2.0-Cisco-1.2.3.4", 0, 1, 7, 100, 101, 128, 129, 65536, 65537, 1_000_001, -1, True, False, None,
                1.5, 0.0, [], {}, ["acme-corp-hq"], [None], {"hostname": "core1"})


def _owner_enum_values() -> list:
    return sorted(set(S.OUTCOMES) | set(S.PLATFORM_SOURCES) | set(S.SSH_PROFILES) | set(S.REFUSAL_CLASSES)
                  | set(S.REFUSAL_CATEGORIES) | set(S.REFUSAL_DETAILS) | {S.SIDECAR_SCHEMA, "auto-add"})


def _paths(node, path=()):
    """Every position of a record: each object member and list element, recursively (the root excluded)."""
    if path:
        yield path
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _paths(value, path + (key,))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _paths(value, path + (index,))


def _objects(node, path=()):
    if isinstance(node, dict):
        yield path
        for key, value in node.items():
            yield from _objects(value, path + (key,))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _objects(value, path + (index,))


def _at(doc, path):
    for step in path:
        doc = doc[step]
    return doc


def _generated_mutations(record):
    """Every leaf and container of `record` replaced by every value above, every member of every object removed, and
    a foreign member added to every object -- generated by walking the record, never a hand-kept list of positions."""
    values = list(_LEAF_VALUES) + _owner_enum_values()
    for path in _paths(record):
        for value in values:
            mutated = json.loads(json.dumps(record))
            _at(mutated, path[:-1])[path[-1]] = json.loads(json.dumps(value))
            yield ("set", path, value), mutated
    for path in _objects(record):
        for key in list(_at(record, path)):
            mutated = json.loads(json.dumps(record))
            del _at(mutated, path)[key]
            yield ("del", path, key), mutated
        mutated = json.loads(json.dumps(record))
        _at(mutated, path)["hostname"] = "core1"
        yield ("add", path, "hostname"), mutated


@pytest.mark.parametrize("shape", sorted(_producer_records()))
def test_the_verifier_restates_the_whole_closed_schema_at_every_leaf(shape):
    """Design re-check P2. Catches: a verifier that checks only the algorithm-name and banner positions, so a record
    the owner's validator refuses -- an enum value that is not one (outcome, platform source, a consent profile, a
    refusal's category / classification / detail), a missing or foreign member of any object, a bool where a number
    belongs (or a number equal to ``False`` in the fixed host-key block), a null inside a name list, or a refusal on an
    outcome that is not refused -- was still reported COVERED BY SCHEMA. The owner and the verifier must agree on
    every generated mutation, whichever way."""
    record = _producer_records()[shape]
    assert S.validate_record(record) == [] and rv._ssh_session_record_conforms(S.render_record(record))
    disagreements, refused, accepted = [], 0, 0
    for label, mutated in _generated_mutations(record):
        owner_ok = not S.validate_record(mutated)
        verifier_ok = rv._ssh_session_record_conforms(json.dumps(mutated).encode("utf-8"))
        if owner_ok != verifier_ok:
            disagreements.append((label, owner_ok, verifier_ok))
        refused += not owner_ok
        accepted += owner_ok
    assert not disagreements, disagreements[:10]
    # non-vacuity: the walk reached positions both refuse AND positions where a value is legitimately accepted
    assert refused > 500 and accepted > 20, (refused, accepted)


def test_every_restated_set_and_grammar_equals_the_owners():
    """Design re-check P2. Catches: an enum member, an object member, a range or a grammar changed on the producer
    without the verifier's restatement (it never imports the producer)."""
    assert rv._SSH_SESSION_TOP_KEYS == frozenset(S._TOP_KEYS)
    assert rv._SSH_SESSION_CONSENT_KEYS == frozenset(S._CONSENT_KEYS)
    assert rv._SSH_SESSION_LIBRARY_KEYS == frozenset(S._LIBRARY_KEYS)
    assert rv._SSH_SESSION_CLIENT_KEYS == frozenset(S._CLIENT_KEYS)
    assert rv._SSH_SESSION_SERVER_KEYS == frozenset(S._SERVER_KEYS)
    assert rv._SSH_SESSION_NEGOTIATED_KEYS == frozenset(S._NEGOTIATED_KEYS)
    assert rv._SSH_SESSION_OBSERVATION_KEYS == frozenset(S._OBSERVATION_KEYS)
    assert rv._SSH_SESSION_REFUSAL_KEYS == frozenset(S._REFUSAL_KEYS)
    assert rv._SSH_SESSION_HOST_KEY_BLOCK == S._HOST_KEY_BLOCK
    assert rv._SSH_SESSION_OUTCOMES == S.OUTCOMES
    assert rv._SSH_SESSION_PLATFORM_SOURCES == S.PLATFORM_SOURCES
    assert rv._SSH_SESSION_PROFILES == S.SSH_PROFILES
    assert rv._SSH_SESSION_REFUSAL_CLASSES == S.REFUSAL_CLASSES
    assert rv._SSH_SESSION_REFUSAL_CATEGORIES == S.REFUSAL_CATEGORIES
    assert rv._SSH_SESSION_REFUSAL_DETAILS == S.REFUSAL_DETAILS
    assert rv._SSH_SESSION_MAX_LIST == S.MAX_LIST_LENGTH
    assert rv._SSH_SESSION_RECORD_SCHEMA == S.SIDECAR_SCHEMA
    assert rv._SSH_SESSION_VERSION_RE.pattern == S._VERSION_RE.pattern
    assert rv._SSH_SESSION_IDENTIFIER_RE.pattern == S._IDENTIFIER_RE.pattern
    assert rv._SSH_SESSION_TOKEN_RE.pattern == S._NAME_RE.pattern
    assert rv._SSH_SESSION_IPV4_IN_TEXT.pattern == S._IPV4_IN_TEXT.pattern
    assert rv._SSH_SESSION_MAC_IN_TEXT.pattern == S._MAC_IN_TEXT.pattern
    # every key the walk admits is a member of some object's exact key set, and no more
    assert rv._SSH_SESSION_RECORD_KEYS == frozenset().union(
        S._TOP_KEYS, S._CONSENT_KEYS, S._LIBRARY_KEYS, S._CLIENT_KEYS, S._SERVER_KEYS, S._NEGOTIATED_KEYS,
        S._OBSERVATION_KEYS, S._HOST_KEY_KEYS, S._REFUSAL_KEYS)


def test_the_generated_walk_catches_a_dropped_enum_and_a_dropped_cross_field_rule(monkeypatch):
    """Falsifier for the agreement test above: with the verifier's outcome enum widened, or its pending rule dropped,
    the generated walk finds a disagreement (it is not vacuous over the positions it claims to cover)."""
    record = _producer_records()["established"]

    def disagreements():
        return [label for label, mutated in _generated_mutations(record)
                if (not S.validate_record(mutated)) != rv._ssh_session_record_conforms(
                    json.dumps(mutated).encode("utf-8"))]

    assert disagreements() == []
    monkeypatch.setattr(rv, "_SSH_SESSION_OUTCOMES", rv._SSH_SESSION_OUTCOMES + ("acme-corp-hq",))
    assert any(label[1] == ("outcome",) for label in disagreements())
    monkeypatch.undo()
    real = rv._ssh_session_closed_schema
    monkeypatch.setattr(rv, "_ssh_session_closed_schema",
                        lambda doc: real(dict(doc, negotiated=None, server_offered=None)
                                         if isinstance(doc, dict) and doc.get("outcome") == "pending" else doc))
    assert any(label[1] == ("outcome",) and label[2] == "pending" for label in disagreements())


def test_no_record_carries_a_host_key_fingerprint():
    """T15 / design section 7, threat 1. Catches: a fingerprint written into the collection tree, where the
    redacted-collection path would leak it. The schema has no field for one and refuses the ':' every OpenSSH
    fingerprint spelling carries."""
    for record in (_refused_record(), _established_record()):
        text = S.render_record(record).decode("ascii")
        values = []

        def walk(node):
            if isinstance(node, dict):
                for v in node.values():
                    walk(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)
            elif isinstance(node, str):
                values.append(node)

        walk(json.loads(text))
        assert not [v for v in values if ":" in v or v.upper().startswith(("SHA256", "MD5"))]
        assert set(record["host_key"]) == {"policy", "verified"}


def test_the_verifier_restates_the_owners_vocabulary_and_banner_grammar_exactly():
    """W59 PR-1 review (P3-e). The verifier never imports the producer, so its restated vocabulary (as digests: the
    SSH SHA-1 names stay in their one owner) and banner grammar are held equal to the owner's here. Catches: a name
    added to the producer's vocabulary (or removed) without the verifier, which would either vouch for a name it does
    not know or refuse a record the producer writes."""
    import hashlib

    assert rv._SSH_SESSION_ALGORITHM_NAME_DIGESTS == frozenset(
        hashlib.sha256(n.encode("ascii")).hexdigest()[:16] for n in S.RECORDABLE_ALGORITHM_NAMES)
    assert rv._SSH_SESSION_SERVER_SOFTWARE_RE.pattern == S.SERVER_SOFTWARE_RE.pattern
    assert rv._SSH_SESSION_NEGOTIATED_NAMES == S._NEGOTIATED_NAME_KEYS
    for name in S.RECORDABLE_ALGORITHM_NAMES:
        assert rv._ssh_session_known_name(name), name
    assert not rv._ssh_session_known_name("acme-corp-hq")


def test_the_producer_never_writes_what_the_verifier_would_refuse():
    """W59 PR-1 review (P3-e), the producer side of the agreement: a device that offers a crafted name and a custom
    banner yields a record that stores neither (both counted) and that both statements accept."""
    obs = S.SessionObservation()
    obs.server = {"kex": ["ecdh-sha2-nistp256", "acme-corp-hq"], "host_key": ["rsa-sha2-512"],
                  "cipher_c2s": ["aes128-ctr"], "cipher_s2c": ["aes128-ctr"], "mac_c2s": ["hmac-sha2-256"],
                  "mac_s2c": ["hmac-sha2-256"]}
    obs.client = {"kex": ["ecdh-sha2-nistp256"], "host_key": ["rsa-sha2-512"], "cipher": ["aes128-ctr"],
                  "mac": ["hmac-sha2-256"]}
    obs.kexinit_seen = True
    snap = obs.snapshot()
    snap.update(newkeys=True, negotiated=dict(_established_record()["negotiated"],
                                              server_software="SSH-2.0-AcmeCorp_1.0"))
    lib = S.library_block(paramiko_version="5.0.0", netmiko_version="4.8.0", transport_class="ObservedTransport",
                          default_permits_sha1=False)
    record = S.build_record(outcome="established", consent=S.consent_for({}), library=lib, attempts=1,
                            observation=snap)
    raw = S.render_record(record)
    assert b"acme" not in raw.lower() and record["dropped_names"] == 2
    assert S.validate_record(record) == [] and rv._ssh_session_record_conforms(raw)
