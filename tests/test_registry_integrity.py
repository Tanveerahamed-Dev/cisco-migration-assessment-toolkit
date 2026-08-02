"""The offline registries are authoritative only as complete, manifested packs."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from cisco_toolkit import ouidb, portdb
from cisco_toolkit import registry_integrity as registry
from cisco_toolkit.data import gen_port_registry


def _write_manifest(
    pack: Path,
    payload: bytes,
    *,
    row_count: int,
    provenance_status: str = "synthetic-test",
    source: dict | None = None,
    extra: dict | None = None,
    generator: str = "synthetic-test",
    generated_at: str = "2026-07-30T00:00:00Z",
) -> None:
    compressed = pack.read_bytes()
    entry = {
        "compressed_bytes": len(compressed),
        "compressed_sha256": hashlib.sha256(compressed).hexdigest(),
        "decompressed_sha256": hashlib.sha256(payload).hexdigest(),
        "row_count": row_count,
        "generated_at": generated_at,
        "generator": generator,
        "provenance_status": provenance_status,
        "source": source or {},
    }
    entry.update(extra or {})
    manifest = {
        "schema_version": 1,
        "packs": {
            pack.name: entry,
        },
    }
    pack.with_name("registry_manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )


_IANA_HEADER = [
    "Service Name",
    "Port Number",
    "Transport Protocol",
    "Description",
    "Assignee",
    "Contact",
    "Registration Date",
    "Modification Date",
    "Reference",
    "Service Code",
    "Unauthorized Use Reported",
    "Assignment Notes",
]


def _write_retained_iana_repo(
    root: Path,
    raw: bytes,
    *,
    expected_header: list[str],
    expected_rows: int,
) -> None:
    source_path = root / (
        "reference-data/official-sources/iana/service-names-port-numbers.csv"
    )
    source_path.parent.mkdir(parents=True)
    source_path.write_bytes(raw)
    inventory_path = root / registry.SOURCE_INVENTORY_RELATIVE_PATH
    inventory_path.parent.mkdir(parents=True, exist_ok=True)
    inventory = {
        "schema_version": 1,
        "retrieved_at": "2026-07-30T00:00:00Z",
        "sources": {
            "iana-service-names-port-numbers": {
                "name": "IANA Service Name and Transport Protocol Port Number Registry",
                "url": (
                    "https://www.iana.org/assignments/"
                    "service-names-port-numbers/"
                    "service-names-port-numbers.csv"
                ),
                "path": (
                    "reference-data/official-sources/iana/"
                    "service-names-port-numbers.csv"
                ),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "bytes": len(raw),
                "encoding": "utf-8",
                "media_type": "text/csv",
                "expected_header": expected_header,
                "expected_rows": expected_rows,
            }
        },
    }
    inventory_path.write_text(json.dumps(inventory), encoding="utf-8")


def _trust_test_iana_snapshot(
    monkeypatch,
    raw: bytes,
    *,
    expected_header: list[str],
    expected_rows: int,
) -> None:
    """Keep parser tests downstream of the production snapshot trust anchor."""

    source_id = "iana-service-names-port-numbers"
    contract = dict(registry._PRIMARY_SOURCE_CONTRACTS[source_id])
    contract.update(
        {
            "sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw),
            "record_count": expected_rows,
            "retrieved_at": "2026-07-30T00:00:00Z",
            "expected_header": tuple(expected_header),
        }
    )
    monkeypatch.setitem(registry._PRIMARY_SOURCE_CONTRACTS, source_id, contract)


def test_shipped_registries_are_verified_through_retained_primary_sources():
    portdb._registry.cache_clear()
    ouidb._registry.cache_clear()
    port_health = portdb.registry_health()
    oui_health = ouidb.registry_health()
    assert port_health["integrity_verified"] is True
    assert port_health["source_authoritative"] is False
    assert port_health["official_source_authoritative"] is True
    assert port_health["curated_overlay_authoritative"] is False
    assert port_health["curated_multicast_authoritative"] is False
    assert port_health["authoritative"] is False
    assert port_health["error"] == (
        "pack contains non-authoritative curated overlay and multicast semantics"
    )
    assert port_health["build_provenance_verified"] is True
    assert port_health["retained_source_bytes_verified"] is True
    assert port_health["source_fresh"] is True
    assert port_health["provenance_status"] == (
        "generated-from-retained-iana-primary-source"
    )
    assert port_health["row_count"] == 12_373
    assert port_health["iana_assignment_count"] == 12_341
    assert port_health["iana_duplicate_key_count"] == 226
    assert port_health["iana_alias_record_count"] == 232
    assert port_health["overlay_conflict_count"] == 3
    assert port_health["multicast_count"] == 21
    assert oui_health["integrity_verified"] is True
    assert oui_health["source_authoritative"] is True
    assert oui_health["authoritative"] is True
    assert oui_health["source_fresh"] is True
    assert oui_health["provenance_status"] == (
        "generated-from-retained-ieee-primary-sources"
    )
    assert oui_health["row_count"] == 53_486

    root = Path(__file__).resolve().parent.parent
    port_chain = registry.verify_retained_source_chain(str(Path(portdb._DATA)))
    oui_chain = registry.verify_retained_source_chain(str(Path(ouidb._DATA)))
    assert port_chain["verified"] is True
    assert port_chain["artifact_count"] == 1
    assert port_chain["source_fresh"] is True
    assert oui_chain["verified"] is True
    assert oui_chain["artifact_count"] == 3
    assert oui_chain["source_fresh"] is True
    assert root.joinpath(registry.SOURCE_INVENTORY_RELATIVE_PATH).is_file()


def test_wheel_runtime_reports_build_proof_without_source_authority(
    tmp_path, monkeypatch
):
    """A wheel keeps usable, pinned pack bytes but omits retained raw sources."""

    monkeypatch.setattr(registry, "_repository_root", lambda _root: tmp_path)
    ouidb._registry.cache_clear()
    ouidb.vendor_for_mac.cache_clear()
    try:
        assert ouidb.vendor_for_mac("00:00:0c:11:22:33")
        health = ouidb.registry_health(load=False)
        assert health["integrity_verified"] is True
        assert health["build_provenance_verified"] is True
        assert health["retained_source_bytes_verified"] is False
        assert health["source_authoritative"] is False
        assert health["authoritative"] is False
        assert health["source_fresh"] is True
        assert health["status"] == "integrity-verified-build-provenance"
    finally:
        ouidb._registry.cache_clear()
        ouidb.vendor_for_mac.cache_clear()


def test_source_authority_binds_generator_and_one_retrieval_batch():
    _, entry = registry.verified_text(portdb._DATA)
    allowed = {"generated-from-retained-iana-primary-source"}
    assert registry.source_authority(
        entry, allowed_provenance_states=allowed
    ) == (True, "")

    wrong_generator = dict(entry)
    wrong_generator["generator"] = "another.generator"
    ok, reason = registry.source_authority(
        wrong_generator, allowed_provenance_states=allowed
    )
    assert ok is False
    assert "generator" in reason

    wrong_batch = dict(entry)
    wrong_batch["source"] = dict(entry["source"])
    wrong_batch["source"]["artifacts"] = [
        dict(artifact) for artifact in entry["source"]["artifacts"]
    ]
    wrong_batch["source"]["artifacts"][0]["retrieved_at"] = (
        "2026-07-29T00:00:00Z"
    )
    ok, reason = registry.source_authority(
        wrong_batch, allowed_provenance_states=allowed
    )
    assert ok is False
    assert "code-pinned trusted snapshot" in reason


@pytest.mark.parametrize(
    ("now", "status"),
    [
        (datetime(2027, 2, 1, tzinfo=timezone.utc), "stale"),
        (datetime(2026, 7, 29, tzinfo=timezone.utc), "future-dated"),
    ],
)
def test_source_authority_requires_a_fresh_non_future_snapshot(now, status):
    _, entry = registry.verified_text(ouidb._DATA)
    authority = registry.source_authority_details(
        entry,
        allowed_provenance_states={
            "generated-from-retained-ieee-primary-sources"
        },
        now=now,
    )
    assert authority["build_provenance_verified"] is True
    assert authority["retained_source_bytes_verified"] is True
    assert authority["source_authoritative"] is False
    assert authority["source_fresh"] is False
    assert authority["freshness_status"] == status
    assert status in authority["authority_error"]


def test_oui_rejects_a_fully_readable_but_unmanifested_substitution(tmp_path, monkeypatch):
    pack = tmp_path / "oui_registry.tsv.gz"
    pack.write_bytes(gzip.compress(b"00000C\t24\tSubstituted Vendor\n", mtime=0))
    monkeypatch.setattr(ouidb, "_DATA", str(pack))
    ouidb._registry.cache_clear()
    ouidb.vendor_for_mac.cache_clear()
    try:
        assert ouidb.vendor_for_mac("00:00:0c:11:22:33") == ""
        assert ouidb.registry_health(load=False)["authoritative"] is False
    finally:
        ouidb._registry.cache_clear()
        ouidb.vendor_for_mac.cache_clear()


def test_port_registry_rejects_one_bad_row_instead_of_caching_a_partial_pack(
    tmp_path, monkeypatch
):
    payload = (
        b"443\ttcp\thttps\t[]\tWeb\t0\tsecure\tiana\tiana\t\t\tnone\n"
        b"not-a-valid-row\n"
    )
    pack = tmp_path / "port_registry.tsv.gz"
    pack.write_bytes(gzip.compress(payload, mtime=0))
    _write_manifest(
        pack,
        payload,
        row_count=2,
        extra={"port_schema_version": 2},
    )
    monkeypatch.setattr(portdb, "_DATA", str(pack))
    portdb._registry.cache_clear()
    try:
        assert portdb.service_for_port(443, "tcp") is None
        assert portdb.registry_health(load=False)["authoritative"] is False
    finally:
        portdb._registry.cache_clear()


def test_vendor_lookup_refuses_any_locally_administered_prefix(monkeypatch):
    monkeypatch.setattr(
        ouidb,
        "_registry",
        lambda: {24: {"020000": "Must Not Resolve"}, 28: {}, 36: {}},
    )
    ouidb.vendor_for_mac.cache_clear()
    try:
        assert ouidb.vendor_for_mac("02:00:00:11:22:33") == ""
    finally:
        ouidb.vendor_for_mac.cache_clear()


def test_failed_iana_refresh_never_overwrites_existing_pack(tmp_path):
    destination = tmp_path / "port_registry.tsv.gz"
    destination.write_bytes(b"preserve-me")

    with pytest.raises(RuntimeError, match="was not modified"):
        gen_port_registry.build(
            out_path=str(destination),
            repository_root=str(tmp_path),
        )
    assert destination.read_bytes() == b"preserve-me"


def test_overlay_only_requires_explicit_non_authoritative_destination(tmp_path):
    destination = tmp_path / "overlay.tsv.gz"
    with pytest.raises(ValueError, match="allow-overlay-only"):
        gen_port_registry.build(offline=True, out_path=str(destination))
    count = gen_port_registry.build(
        offline=True,
        out_path=str(destination),
        allow_overlay_only=True,
    )
    assert count == 83
    manifest = json.loads((tmp_path / "registry_manifest.json").read_text(encoding="utf-8"))
    assert manifest["packs"]["overlay.tsv.gz"]["provenance_status"] == (
        "overlay-only-non-authoritative"
    )
    assert manifest["packs"]["overlay.tsv.gz"]["source_authoritative"] is False


def test_official_iana_build_is_byte_deterministic(tmp_path):
    destination = tmp_path / "port_registry.tsv.gz"
    count = gen_port_registry.build(out_path=str(destination))
    assert count == 12_352
    # PAYLOAD-determinism, deliberately not compressed-byte determinism. The committed pack was
    # built on Windows; CI rebuilds on ubuntu, and the two zlib builds emit DIFFERENT deflate
    # streams for the same input at the same level -- deflate is not canonical across
    # implementations. Proven by this test's own first ubuntu run (2026-08-02): the compressed
    # bytes differed while the gzip CRC32/ISIZE trailers matched, i.e. identical payload, different
    # encoding. The properties a cross-platform rebuild CAN promise, and which matter: the
    # decompressed TSV is byte-identical, the gzip header is canonical (mtime pinned to 0, so the
    # archive carries no build-time), and rebuilding TWICE ON ONE PLATFORM is byte-stable.
    import gzip as _gz
    rebuilt, shipped = destination.read_bytes(), Path(portdb._DATA).read_bytes()
    assert _gz.decompress(rebuilt) == _gz.decompress(shipped), (
        "the rebuilt pack PAYLOAD differs from the shipped pack -- a real content regression")
    assert rebuilt[4:8] == bytes(4), "gzip mtime is no longer pinned to 0"
    second = tmp_path / "port_registry.2.tsv.gz"
    assert gen_port_registry.build(out_path=str(second)) == 12_352
    assert second.read_bytes() == rebuilt, "same-platform rebuild is not byte-stable"
    proof = registry.verify_retained_source_chain(str(destination))
    assert proof["verified"] is True
    assert proof["artifact_count"] == 1


def test_arbitrary_one_row_inventory_cannot_claim_iana_authority(tmp_path):
    raw = (
        ",".join(_IANA_HEADER)
        + "\nsynthetic,1,tcp,one,,,,,,,,\n"
    ).encode()
    destination = tmp_path / "candidate.tsv.gz"
    destination.write_bytes(b"preserve")
    _write_retained_iana_repo(
        tmp_path,
        raw,
        expected_header=_IANA_HEADER,
        expected_rows=1,
    )

    with pytest.raises(RuntimeError, match="code-pinned trusted snapshot"):
        gen_port_registry.build(
            out_path=str(destination),
            repository_root=str(tmp_path),
        )
    assert destination.read_bytes() == b"preserve"
    assert not destination.with_name("registry_manifest.json").exists()


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        (
            (
                ",".join(_IANA_HEADER)
                + "\nonly-one,1,tcp,one,,,,,,,,\n"
            ).encode(),
            "non-regression",
        ),
        (
            b"wrong,header,shape,here\nhttp,80,tcp,web\n",
            "header/schema",
        ),
            (
                (",".join(_IANA_HEADER) + "\nhttp,80\n").encode(),
                "truncated.*row",
            ),
        (
            (",".join(_IANA_HEADER) + "\n").encode()
            + b"bad,\xff,tcp,x,,,,,,,,\n",
            "UTF-8",
        ),
    ],
)
def test_iana_refresh_rejects_tiny_bad_header_truncated_and_invalid_utf8(
    tmp_path, monkeypatch, raw, message
):
    destination = tmp_path / "candidate.tsv.gz"
    destination.write_bytes(b"preserve")
    first_line = raw.splitlines()[0]
    try:
        expected_header = first_line.decode("utf-8").split(",")
    except UnicodeDecodeError:
        expected_header = _IANA_HEADER
    _write_retained_iana_repo(
        tmp_path,
        raw,
        expected_header=expected_header,
        expected_rows=1,
    )
    _trust_test_iana_snapshot(
        monkeypatch,
        raw,
        expected_header=expected_header,
        expected_rows=1,
    )
    with pytest.raises(RuntimeError, match=message):
        gen_port_registry.build(
            out_path=str(destination),
            repository_root=str(tmp_path),
        )
    assert destination.read_bytes() == b"preserve"
    assert not destination.with_name("registry_manifest.json").exists()


def test_windows_case_alias_cannot_bypass_overlay_destination_guard(tmp_path, monkeypatch):
    shipped = tmp_path / "Port_Registry.tsv.gz"
    shipped.write_bytes(b"existing")
    monkeypatch.setattr(gen_port_registry, "_OUT", str(shipped))
    real_normcase = registry.os.path.normcase
    monkeypatch.setattr(
        registry.os.path,
        "normcase",
        lambda path: real_normcase(os.fspath(path)).lower(),
    )
    alias = str(shipped).swapcase()
    assert registry.paths_refer_to_same_file(str(shipped), alias)
    with pytest.raises(ValueError, match="refusing to replace"):
        gen_port_registry.build(
            offline=True,
            out_path=alias,
            allow_overlay_only=True,
        )


def test_pack_and_manifest_publication_rolls_back_on_manifest_replace_failure(
    tmp_path, monkeypatch
):
    pack = tmp_path / "pack.tsv.gz"
    old_payload = b"old\n"
    old_compressed = gzip.compress(old_payload, mtime=0)
    pack.write_bytes(old_compressed)
    _write_manifest(pack, old_payload, row_count=1)
    manifest_path = pack.with_name("registry_manifest.json")
    old_manifest = manifest_path.read_bytes()

    new_compressed = gzip.compress(b"new\n", mtime=0)
    entry = registry.metadata_for_bytes(
        new_compressed,
        source={
            "name": "synthetic",
            "input_sha256": "b" * 64,
            "hash_scope": "raw-source-bytes",
        },
        generator="test",
        provenance_status="generated-from-local-source",
    )
    real_replace = registry.os.replace
    injected = {"done": False}

    def fail_manifest_once(source, destination):
        if (
            not injected["done"]
            and os.path.normcase(os.path.abspath(destination))
            == os.path.normcase(os.path.abspath(manifest_path))
        ):
            injected["done"] = True
            raise OSError("injected manifest publication failure")
        return real_replace(source, destination)

    monkeypatch.setattr(registry.os, "replace", fail_manifest_once)
    with pytest.raises(OSError, match="injected manifest"):
        registry.publish_pack_and_manifest(str(pack), new_compressed, entry)
    assert pack.read_bytes() == old_compressed
    assert manifest_path.read_bytes() == old_manifest
    assert not Path(registry.transaction_marker_path_for(str(pack))).exists()


def test_loader_fails_closed_while_publication_marker_exists(tmp_path):
    payload = b"row\n"
    pack = tmp_path / "pack.tsv.gz"
    pack.write_bytes(gzip.compress(payload, mtime=0))
    _write_manifest(pack, payload, row_count=1)
    marker = Path(registry.transaction_marker_path_for(str(pack)))
    marker.write_text('{"state":"pending"}\n', encoding="utf-8")

    with pytest.raises(registry.PackIntegrityError, match="transaction is incomplete"):
        registry.verified_text(str(pack))


def test_manifest_update_refuses_to_overwrite_corrupt_existing_evidence(tmp_path):
    pack = tmp_path / "pack.tsv.gz"
    pack.write_bytes(gzip.compress(b"row\n", mtime=0))
    manifest = tmp_path / "registry_manifest.json"
    manifest.write_text("{not-json", encoding="utf-8")

    with pytest.raises(
        registry.PackIntegrityError,
        match="registry manifest is invalid JSON",
    ):
        registry.update_manifest(pack, {"row_count": 1})
    assert manifest.read_text(encoding="utf-8") == "{not-json"


def test_registry_size_contract_is_bounded_before_decompression(tmp_path, monkeypatch):
    payload = b"row\n"
    pack = tmp_path / "pack.tsv.gz"
    pack.write_bytes(gzip.compress(payload, mtime=0))
    _write_manifest(pack, payload, row_count=1)
    monkeypatch.setattr(registry, "MAX_COMPRESSED_BYTES", 1)

    with pytest.raises(registry.PackIntegrityError, match="size contract"):
        registry.verified_text(str(pack))


def test_generated_metadata_cannot_override_integrity_fields():
    compressed = gzip.compress(b"row\n", mtime=0)
    with pytest.raises(registry.PackIntegrityError, match="protected field"):
        registry.metadata_for_bytes(
            compressed,
            source={"name": "synthetic"},
            generator="test",
            provenance_status="test",
            extra={"row_count": 999},
        )


def test_pack_usability_distinguishes_cannot_check_here_from_checked_and_failed(tmp_path):
    """The Atlas self-test's first-ever run from an installed WHEEL failed oui-kb and port-kb:
    the wheel ships without reference-data/official-sources/** (deliberately — handoff 5.5, sdist
    only), so every source-chain verification died with [Errno 2], and the gate read that ABSENCE
    of the ability to check as a failed check. Predicted, unverified, by the port-authority
    refuter's F7; confirmed by CI on 2026-08-02.

    `official_sources_available` is the structured fact that separates the two states — a stat of
    the inventory path, deliberately NOT a parse, so a present-but-corrupt inventory keeps
    reporting available=True and its verification failure stays a real refusal. Consumers key on
    `is False`, so a stale health dict without the field keeps the strict behaviour (fail-closed).
    """
    import json
    from pathlib import Path

    from cisco_toolkit import portdb
    from cisco_toolkit.registry_integrity import (
        official_sources_available,
        pack_is_usable,
        source_authority_details,
    )

    # REAL producer, both roots — not a hand-shaped dict.
    assert official_sources_available() is True, "repo checkout must see the retained sources"
    assert official_sources_available(repository_root=tmp_path) is False

    manifest = json.loads(
        (Path(portdb._DATA).parent / "registry_manifest.json").read_text(encoding="utf-8"))
    details = source_authority_details(
        manifest["packs"]["port_registry.tsv.gz"],
        allowed_provenance_states={"generated-from-retained-iana-primary-source"},
        repository_root=tmp_path)
    assert details["official_sources_available"] is False
    assert details["build_provenance_verified"] is True
    assert details["source_authoritative"] is False, "absence must never claim authority"

    # the owner predicate, across the whole matrix, from the real repo health dict
    h = portdb.registry_health()
    assert pack_is_usable(h) is True                                   # repo: fully proven
    wheel = dict(h, official_sources_available=False, official_source_authoritative=False)
    assert pack_is_usable(wheel) is True, "a wheel install read as a DEAD registry (the CI failure)"
    checked_failed = dict(wheel, official_sources_available=True)
    assert pack_is_usable(checked_failed) is False, "a PRESENT-but-failing chain must stay refused"
    assert pack_is_usable(dict(wheel, integrity_verified=False)) is False
    assert pack_is_usable(dict(wheel, build_provenance_verified=False)) is False
    stale = {k: v for k, v in wheel.items() if k != "official_sources_available"}
    assert pack_is_usable(stale) is False, "an old producer without the field must stay strict"


def test_provenance_accepts_a_faithful_rebuild_from_a_foreign_zlib_and_refuses_a_tampered_payload():
    """The code pin was a COMPRESSED digest, so a byte-faithful rebuild of the reviewed content on
    another platform was refused as "not the code-pinned deterministic build" — proven on CI
    2026-08-02, where every ubuntu leg's rebuild produced different deflate bytes with an identical
    payload (gzip CRC32/ISIZE trailers matched). Deflate is not canonical across zlib builds, so a
    compressed-only pin means pack regeneration is blessable on exactly one zlib build, ever.

    The payload anchor closes that: the manifest's `decompressed_sha256` — which `verified_text`
    checks against the actual decompressed bytes, so it is never trusted bare — may match
    `_TRUSTED_PAYLOAD_SHA256_BY_STATE` instead. Simulated here with a real foreign framing
    (compresslevel=1, mtime=0) rather than a hand-edited digest.
    """
    import gzip as _gz
    import io
    import json
    from pathlib import Path

    from cisco_toolkit import portdb
    from cisco_toolkit.registry_integrity import _build_provenance_authority

    shipped = Path(portdb._DATA).read_bytes()
    payload = _gz.decompress(shipped)
    buf = io.BytesIO()
    with _gz.GzipFile(fileobj=buf, mode="wb", compresslevel=1, mtime=0) as handle:
        handle.write(payload)
    foreign = buf.getvalue()
    assert foreign != shipped, "the simulation failed to produce a different deflate framing"
    assert _gz.decompress(foreign) == payload

    manifest = json.loads(
        (Path(portdb._DATA).parent / "registry_manifest.json").read_text(encoding="utf-8"))
    states = {"generated-from-retained-iana-primary-source"}

    rebuilt = dict(manifest["packs"]["port_registry.tsv.gz"])
    rebuilt["compressed_sha256"] = registry._sha256(foreign)
    rebuilt["compressed_bytes"] = len(foreign)
    ok, reason, _ = _build_provenance_authority(rebuilt, allowed_provenance_states=states)
    assert ok is True, f"a faithful rebuild was refused: {reason}"

    # NON-VACUITY in both directions: a tampered PAYLOAD fails both anchors...
    tampered = dict(rebuilt)
    tampered["decompressed_sha256"] = registry._sha256(payload + b"x")
    ok2, reason2, _ = _build_provenance_authority(tampered, allowed_provenance_states=states)
    assert ok2 is False and "code-pinned" in reason2
    # ...and the SHIPPED pack still verifies through the compressed anchor, unchanged.
    ok3, _r, _ = _build_provenance_authority(
        dict(manifest["packs"]["port_registry.tsv.gz"]), allowed_provenance_states=states)
    assert ok3 is True
