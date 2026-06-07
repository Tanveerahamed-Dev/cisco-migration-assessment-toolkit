"""NEW-V3.23.109: the pre-assessment collection-completeness / blind-spot report. Every finding is only
as trustworthy as the data behind it, so un-/partially-collected inventory devices are made explicit."""
from cisco_toolkit.analyze import compute_collection_completeness


def test_tiers_inventory_into_complete_partial_not_collected(tmp_path):
    # build real-ish cmd files: full device, partial device (missing CDP/LLDP), empty device
    good = tmp_path / "good"; good.mkdir()
    for name in ("show_interface_status.txt", "show_interface_switchport.txt",
                 "show_version.txt", "show_cdp_neighbors_detail.txt"):
        (good / name).write_text("data\n", encoding="utf-8")
    part = tmp_path / "part"; part.mkdir()
    for name in ("show_interface_status.txt", "show_interface_switchport.txt", "show_version.txt"):
        (part / name).write_text("data\n", encoding="utf-8")
    empty = tmp_path / "empty"; empty.mkdir()
    (empty / "show_version.txt").write_text("", encoding="utf-8")     # present but empty -> not usable

    def c2f(d, *names):       # key by the full "show ..." command, as the real all_cmd_to_files does
        return {f"show {n}": str(d / f"show_{n.replace(' ', '_')}.txt") for n in names}

    acf = {
        "sw-good": c2f(good, "interface status", "interface switchport", "version", "cdp neighbors detail"),
        "sw-part": c2f(part, "interface status", "interface switchport", "version", "cdp neighbors detail"),
        "sw-empty": c2f(empty, "version"),
    }
    inventory = ["sw-good", "sw-part", "sw-empty", "sw-no-dir"]     # sw-no-dir absent from acf entirely
    cc = compute_collection_completeness(inventory, acf)
    s = cc["summary"]
    assert s == {"inventory": 4, "complete": 1, "partial": 1, "not_collected": 2}
    by = {d["host"]: d for d in cc["devices"]}
    assert "sw-good" not in by                                       # complete devices are omitted (blind spots only)
    assert by["sw-part"]["status"] == "partial" and by["sw-part"]["missing"] == ["CDP/LLDP neighbors"]
    assert by["sw-part"]["data_quality"] == 75
    assert by["sw-no-dir"]["status"] == "not collected" and by["sw-no-dir"]["data_quality"] == 0
    assert len(by["sw-no-dir"]["missing"]) == 4
    # not-collected sorts before partial
    assert cc["devices"][0]["status"] == "not collected"


def test_empty_and_all_complete():
    assert compute_collection_completeness([], {}) == {
        "summary": {"inventory": 0, "complete": 0, "partial": 0, "not_collected": 0}, "devices": []}
