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
