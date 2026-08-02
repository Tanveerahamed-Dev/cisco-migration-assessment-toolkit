"""Plan-A #19: the offline OUI-registry regenerator. Proves parse_manuf produces an
ouidb-COMPATIBLE pack (round-tripped through the REAL loader, MA-L/MA-M/MA-S longest-prefix),
and that it stays offline (refuses a URL — never fetches)."""
import json
from pathlib import Path

import pytest

from cisco_toolkit import gen_oui_registry as G
from cisco_toolkit.registry_integrity import (
    PackIntegrityError,
    verify_retained_source_chain,
)

# A tiny synthetic Wireshark `manuf`: one MA-L (24), one MA-S (36), one MA-M (28), plus noise.
_SAMPLE = "\n".join([
    "# Wireshark manuf — synthetic fixture",
    "",
    "00:00:0C\tCisco\tCisco Systems, Inc",                       # MA-L, 24-bit
    "00:1B:C5:00:00:00/36\tIeeeReg\tIEEE Registration Authority",  # MA-S, 36-bit
    "8C:1F:64:80:00:00/28\tSpecific\tSpecific Vendor Inc",         # MA-M, 28-bit
    "AA:BB:CC:00:00:00/40\tTooWide\tOut-of-family mask (dropped)",  # /40 -> skipped
    "malformed-no-tab-line",
])


def test_parse_manuf_shapes_and_widths():
    rows = list(G.parse_manuf(_SAMPLE.splitlines()))
    assert ("00000C", 24, "Cisco Systems, Inc") in rows
    assert ("001BC5000", 36, "IEEE Registration Authority") in rows     # 9 nibbles
    assert ("8C1F648", 28, "Specific Vendor Inc") in rows               # 7 nibbles
    # out-of-family mask + malformed line dropped; every emitted prefix is width == bits/4, uppercase
    assert len(rows) == 3
    assert all(len(p) == b // 4 and p == p.upper() for p, b, _ in rows)


def test_generated_pack_resolves_end_to_end_in_ouidb(tmp_path, monkeypatch):
    """The real contract: a pack this tool writes must load in ouidb and resolve MACs by
    longest-prefix across all three block sizes."""
    out = tmp_path / "oui_registry.tsv.gz"
    n = G.write_registry(G.parse_manuf(_SAMPLE.splitlines()), str(out))
    assert n == 3

    from cisco_toolkit import ouidb
    monkeypatch.setattr(ouidb, "_DATA", str(out))
    ouidb._registry.cache_clear()
    ouidb.vendor_for_mac.cache_clear()
    try:
        assert ouidb.vendor_for_mac("00:00:0C:11:22:33") == "Cisco Systems, Inc"          # MA-L
        assert ouidb.vendor_for_mac("00:1B:C5:00:0A:BC") == "IEEE Registration Authority"  # MA-S block
        assert ouidb.vendor_for_mac("8C:1F:64:8F:11:22") == "Specific Vendor Inc"          # MA-M block
        assert ouidb.vendor_for_mac("DE:AD:BE:EF:00:11") == ""                             # unknown -> ''
        health = ouidb.registry_health(load=False)
        assert health["integrity_verified"] is True
        assert health["source_authoritative"] is False
    finally:
        ouidb._registry.cache_clear()
        ouidb.vendor_for_mac.cache_clear()


def test_main_refuses_a_url():
    for url in ("https://www.wireshark.org/download/automated/data/manuf", "http://x/manuf", "ftp://h/f"):
        with pytest.raises(SystemExit):
            G.main([url])


def test_main_refuses_a_url_with_leading_whitespace():
    """The no-egress refusal must not be defeated by a leading space in the argument."""
    with pytest.raises(SystemExit):
        G.main(["   https://www.wireshark.org/download/automated/data/manuf"])


def test_write_registry_tolerates_a_bare_filename_out(tmp_path, monkeypatch):
    """A bare-filename --out (no directory component) must not crash on os.makedirs('') -- a plausible
    first invocation writing to the CWD."""
    monkeypatch.chdir(tmp_path)
    n = G.write_registry(G.parse_manuf(_SAMPLE.splitlines()), "oui_registry.tsv.gz")
    assert n == 3 and (tmp_path / "oui_registry.tsv.gz").exists()


def test_one_row_refresh_cannot_replace_a_manifested_registry(tmp_path):
    out = tmp_path / "oui_registry.tsv.gz"
    baseline = ((f"{number:06X}", 24, f"Vendor {number}") for number in range(20))
    assert G.write_registry(baseline, str(out)) == 20
    old_pack = out.read_bytes()
    old_manifest = out.with_name("registry_manifest.json").read_bytes()

    with pytest.raises(PackIntegrityError, match="non-regression floor"):
        G.write_registry(iter([("000001", 24, "Only one")]), str(out))
    assert out.read_bytes() == old_pack
    assert out.with_name("registry_manifest.json").read_bytes() == old_manifest


@pytest.mark.parametrize(
    "record",
    [
        ("00000c", 24, "lowercase prefix"),
        ("00000C", 25, "bad width"),
        ("00000C", 24, "vendor\twith tab"),
        ("00000C", 24, ""),
    ],
)
def test_write_registry_rejects_records_outside_loader_schema(tmp_path, record):
    with pytest.raises(ValueError, match="invalid OUI generator record"):
        G.write_registry(iter([record]), str(tmp_path / "oui_registry.tsv.gz"))


def test_main_rejects_invalid_utf8_before_publishing(tmp_path):
    source = tmp_path / "manuf"
    source.write_bytes(b"00:00:0C\tCisco\tCisco Systems\xff\n")
    out = tmp_path / "oui_registry.tsv.gz"
    with pytest.raises(UnicodeDecodeError):
        G.main([str(source), "--out", str(out)])
    assert not out.exists()


def test_legacy_generator_records_raw_source_artifact_but_not_authority(tmp_path):
    source_path = tmp_path / "manuf"
    source_path.write_text(_SAMPLE, encoding="utf-8")
    out = tmp_path / "oui_registry.tsv.gz"
    G.main([str(source_path), "--out", str(out)])
    manifest = json.loads(out.with_name("registry_manifest.json").read_text(encoding="utf-8"))
    entry = manifest["packs"][out.name]
    artifact = entry["source"]["artifacts"][0]
    assert artifact["hash_scope"] == "raw-source-bytes"
    assert artifact["bytes"] == source_path.stat().st_size
    assert entry["provenance_status"] == "legacy-local-input-non-authoritative"
    assert entry["source_authoritative"] is False


def test_official_ieee_build_is_byte_deterministic_and_full_chain(tmp_path):
    out = tmp_path / "oui_registry.tsv.gz"
    assert G.build_authoritative(out_path=str(out)) == 53_486
    shipped = (
        Path(G.__file__).resolve().parent / "data" / "oui_registry.tsv.gz"
    )
    # PAYLOAD-determinism, deliberately not compressed-byte determinism. The committed pack was
    # built on Windows; CI rebuilds on ubuntu, and the two zlib builds emit DIFFERENT deflate
    # streams for the same input at the same level -- deflate is not canonical across
    # implementations. Proven by this test's own first ubuntu run (2026-08-02): the compressed
    # bytes differed while the gzip CRC32/ISIZE trailers matched, i.e. identical payload, different
    # encoding. The properties a cross-platform rebuild CAN promise, and which matter: the
    # decompressed TSV is byte-identical, the gzip header is canonical (mtime pinned to 0, so the
    # archive carries no build-time), and rebuilding TWICE ON ONE PLATFORM is byte-stable.
    import gzip as _gz
    rebuilt = out.read_bytes()
    assert _gz.decompress(rebuilt) == _gz.decompress(shipped.read_bytes()), (
        "the rebuilt pack PAYLOAD differs from the shipped pack -- a real content regression")
    assert rebuilt[4:8] == bytes(4), "gzip mtime is no longer pinned to 0"
    manifest = json.loads(
        out.with_name("registry_manifest.json").read_text(encoding="utf-8")
    )
    entry = manifest["packs"][out.name]
    assert entry["source_row_count"] == 53_489
    assert entry["conflicting_prefix_count"] == 2
    # The manifest proves the deterministic build. Runtime authority additionally
    # requires the separately retained raw IEEE bytes.
    assert entry["build_provenance_verified"] is True
    assert entry["runtime_source_verification_required"] is True
    assert entry["source_authoritative"] is False
    assert entry["source_fresh"] is True
    proof = verify_retained_source_chain(str(out))
    assert proof["verified"] is True
    assert proof["artifact_count"] == 3
