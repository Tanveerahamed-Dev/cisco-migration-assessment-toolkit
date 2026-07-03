"""Plan-A #19: the offline OUI-registry regenerator. Proves parse_manuf produces an
ouidb-COMPATIBLE pack (round-tripped through the REAL loader, MA-L/MA-M/MA-S longest-prefix),
and that it stays offline (refuses a URL — never fetches)."""
import pytest

from cisco_toolkit import gen_oui_registry as G

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
