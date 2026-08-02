"""Tests for KEV Phase-B upgrade-targets (cisco_toolkit.upgrade_targets).

Security-critical: the comparator must be TRAIN-AWARE and FAIL-CLOSED. The core properties under test:
  * within-train ordering is numeric, not lexical (the 15.2(2)E7 < 15.2(2)E10 trap);
  * cosmetic format variants are equal (03.06.06E == 03.06.06.E; 17.03.04 == 17.3.4);
  * cross-train comparison is REFUSED (returns None → the join yields MANUAL-VERIFY, never a guessed target);
  * unparseable input → MANUAL-VERIFY; no fixed intel → TARGET-PENDING (never "already patched");
  * platform-correct not-applicability (NX-OS under an IOS CVE) is positively confirmed, not inferred;
  * the whole pipeline (openVuln JSON → map_psirt_advisories → build_feed → load_feeds → join) round-trips.
"""
import json

import pytest

from cisco_toolkit import upgrade_targets as UT
from cisco_toolkit.upgrade_targets import (MANUAL_VERIFY, TARGET_PENDING, choose_target, compare_same_train,
                                           parse_version)
from cisco_toolkit import intel_feed as IF
from research_lane.sources import map_psirt_advisories


# ===================================================================================================
# Part 1 — the version parser: every train's format
# ===================================================================================================

@pytest.mark.parametrize("raw,platform,family,normalized", [
    # IOS-XE 16/17 (dotted triplet, zero-pad + rebuild letter)
    ("17.9.4a", "ios-xe", "ios-xe", "17.9.4a"),
    ("17.03.04", "ios-xe", "ios-xe", "17.3.4"),
    ("16.12.10a", "ios-xe", "ios-xe", "16.12.10a"),
    # IOS-XE 3.x (converged access; dotted vs attached E)
    ("03.06.06E", "ios", "ios-xe", "03.06.06.E"),
    ("03.06.06.E", "ios", "ios-xe", "03.06.06.E"),
    ("03.11.03a.E", "ios", "ios-xe", "03.11.03a.E"),
    # IOS classic
    ("15.2(2)E7", "ios", "ios", "15.2(2)E7"),
    ("12.2(55)SE12", "ios", "ios", "12.2(55)SE12"),
    # NX-OS
    ("6.0(2)N2(3)", "nxos", "nxos", "6.0(2)N2(3)"),
    ("7.0(3)I7(9)", "nxos", "nxos", "7.0(3)I7(9)"),
    ("9.3(10)", "nxos", "nxos", "9.3(10)"),
])
def test_parse_each_family(raw, platform, family, normalized):
    v = parse_version(raw, platform_hint=platform)
    assert v is not None, f"failed to parse {raw!r}"
    assert v.family == family
    assert v.normalized == normalized


@pytest.mark.parametrize("raw", ["", None, "garbage", "Version 12.2", "1.2.3.4.5", "(not captured)",
                                 "cat9k_iosxe.17.09.04a.SPA.bin"])
def test_unparseable_returns_none(raw):
    assert parse_version(raw) is None


def test_zero_pad_and_dotted_E_equivalence():
    # cosmetic format variants must compare EQUAL (same normalized, same train, rebuild_key equal)
    assert parse_version("17.03.04").normalized == parse_version("17.3.4").normalized
    a, b = parse_version("03.06.06E", platform_hint="ios"), parse_version("03.06.06.E", platform_hint="ios")
    assert compare_same_train(a, b) == 0


# ===================================================================================================
# Part 2 — within-train ordering (numeric, not lexical) and cross-train refusal
# ===================================================================================================

def test_ios_classic_rebuild_is_numeric_not_lexical():
    # THE trap: lexically "E7" > "E10"; numerically rebuild 7 < 10. Must be numeric.
    a, b = parse_version("15.2(2)E7", platform_hint="ios"), parse_version("15.2(2)E10", platform_hint="ios")
    assert compare_same_train(a, b) == -1


def test_ios_xe_3x_rebuild_ordering():
    a = parse_version("03.06.03.E", platform_hint="ios")
    b = parse_version("03.06.06.E", platform_hint="ios")
    assert compare_same_train(a, b) == -1


def test_ios_xe_rebuild_letter_orders_after_base():
    a, b = parse_version("17.3.4"), parse_version("17.3.4a")
    assert compare_same_train(a, b) == -1                      # 17.3.4 precedes the 17.3.4a respin


def test_nxos_rebuild_ordering():
    a = parse_version("6.0(2)N2(3)", platform_hint="nxos")
    b = parse_version("6.0(2)N2(4)", platform_hint="nxos")
    assert compare_same_train(a, b) == -1


@pytest.mark.parametrize("a_raw,b_raw,hint", [
    ("03.06.06E", "17.9.4a", "ios"),          # 3.x epoch vs 17.x epoch — a migration, not a bump
    ("03.06.06E", "03.08.08E", "ios"),        # different 3.x minor train
    ("15.2(2)E7", "15.2(4)E10", "ios"),       # different maintenance build (2) vs (4)
    ("15.2(2)E7", "15.2(2)M7", "ios"),        # different train letters (E vs M)
    ("6.0(2)N2(3)", "7.0(3)I7(9)", "nxos"),   # different NX-OS train
    ("16.12.4", "17.9.4a", "ios-xe"),         # different XE major train
])
def test_cross_train_comparison_refused(a_raw, b_raw, hint):
    a, b = parse_version(a_raw, platform_hint=hint), parse_version(b_raw, platform_hint=hint)
    assert a is not None and b is not None
    assert compare_same_train(a, b) is None                    # NOT an ordering → caller must MANUAL-VERIFY


# ===================================================================================================
# Part 3 — choose_target: the tri-state+ decision
# ===================================================================================================

def test_same_train_bump_is_a_confident_target():
    d = choose_target("6.0(2)N2(3)", ["6.0(2)N2(4)"], platform_hint="nxos")
    assert d["needs_upgrade"] is True and d["target"] == "6.0(2)N2(4)"


def test_already_current_when_at_or_above_fix():
    d = choose_target("17.9.5", ["17.9.4a"], platform_hint="ios-xe")
    assert d["needs_upgrade"] is False and d["target"] == "17.9.5"


def test_cross_train_only_fix_is_manual_verify():
    # EOL 3.x device, fix only on 17.x → migration, not a mechanical target
    d = choose_target("03.06.06E", ["17.9.4a", "16.12.10a"], platform_hint="ios")
    assert d["needs_upgrade"] == MANUAL_VERIFY and d["target"] is None
    assert set(d["cross_train_fixes"]) == {"17.9.4a", "16.12.10a"}


def test_unparseable_current_is_manual_verify():
    d = choose_target("frobozz-1.2", ["17.9.4a"], platform_hint="ios-xe")
    assert d["needs_upgrade"] == MANUAL_VERIFY and d["target"] is None


def test_no_fixed_intel_is_target_pending():
    d = choose_target("03.06.06E", [], platform_hint="ios")
    assert d["needs_upgrade"] == TARGET_PENDING and d["target"] is None


def test_choose_target_never_raises_on_nonstring_fix():
    # Contract (module docstring): choose_target(fixed: List[Any]) never raises on bad input -> MANUAL-VERIFY,
    # the safe direction. Regression (refuter R9): a non-string unparseable fix element used to crash the
    # `', '.join(unparsed)` error-message build with TypeError instead of degrading. `fixed` is declared List[Any].
    d = choose_target("17.9.1", [12345], platform_hint="ios-xe")
    assert d["needs_upgrade"] == MANUAL_VERIFY and d["target"] is None


def test_current_exactly_at_fix_is_not_an_upgrade():
    # A device on the EXACT fixed release must not be told to upgrade to its own version (the `>=` boundary,
    # previously unpinned — refuter R9 mutation M2).
    d = choose_target("17.9.4a", ["17.9.4a"], platform_hint="ios-xe")
    assert d["needs_upgrade"] is False and d["target"] == "17.9.4a"


def test_single_same_train_fix_is_the_confident_target():
    d = choose_target("17.9.1", ["17.9.4a"], platform_hint="ios-xe")
    assert d["needs_upgrade"] is True and d["target"] == "17.9.4a"


# --- C1 regression: >=2 DISTINCT same-train fixes are AMBIGUOUS → MANUAL-VERIFY, never MIN/false-current ---
# A wrong MIN would under-target (leave the box vulnerable); a MAX could force a needless upgrade. The
# comparator must fail CLOSED here, not open. (Found by the independent verifier.)

def test_multiple_distinct_same_train_fixes_is_manual_verify_not_min():
    d = choose_target("17.9.1", ["17.9.6", "17.9.2"], platform_hint="ios-xe")
    assert d["needs_upgrade"] == MANUAL_VERIFY and d["target"] is None    # NOT 17.9.2 (would under-target)
    assert set(d["same_train_fixes"]) == {"17.9.2", "17.9.6"}


def test_unparseable_entry_in_a_fixed_list_is_never_silently_dropped():
    """C2 regression (review 2026-07-28 #26): an entry the comparator cannot read VANISHED the moment a
    sibling entry parsed onto the device's train. A CVE fixed on 17.9.6 — spelled 'Cisco IOS XE 17.9.6' by
    the feed — shipped TARGET_RELEASE 17.9.4, a release that is STILL VULNERABLE, and nothing in the row,
    the reason or same_train_fixes disclosed the dropped release. It also defeated the >=2-same-train-fixes
    ambiguity guard, because only one fix was left to count. Fail closed and NAME the unread entry."""
    d = choose_target("17.9.2", ["17.9.4", "Cisco IOS XE 17.9.6"], platform_hint="ios-xe")
    assert d["needs_upgrade"] == MANUAL_VERIFY and d["target"] is None     # NOT 17.9.4 (still vulnerable)
    assert d["unparsed_fixes"] == ["Cisco IOS XE 17.9.6"]
    assert "Cisco IOS XE 17.9.6" in d["reason"]
    # and it survives the per-host merge + the join, into the row an engineer actually reads
    res = UT.build_upgrade_targets(
        [{"id": "CVE-2023-20198", "fixed": ["17.9.4", "Cisco IOS XE 17.9.6"]}],
        {"H": {"sw_version": "17.9.2", "platform": "ios-xe"}}, {"http_server_flagged": ["H"]},
        cve_map={"CVE-2023-20198": {"group": "http_server_flagged", "applies_to": ("ios", "ios-xe"),
                                    "surface": "web"}})
    row = next(r for r in res["rows"] if r["host"] == "H")
    assert row["needs_upgrade"] == MANUAL_VERIFY and row["target"] is None
    assert row["unparsed_fixes"] == ["Cisco IOS XE 17.9.6"]


def test_a_fully_parseable_fixed_list_still_yields_a_confident_target():
    """The fail-closed gate must not swallow the confident cases it is not about."""
    d = choose_target("17.9.1", ["17.9.4a"], platform_hint="ios-xe")
    assert d["needs_upgrade"] is True and d["target"] == "17.9.4a" and d["unparsed_fixes"] == []


def test_multiple_same_train_fixes_never_reports_false_current():
    # device between two listed fixes must NOT be called "already current" while a higher fix exists
    d = choose_target("17.9.4", ["17.9.6", "17.9.2"], platform_hint="ios-xe")
    assert d["needs_upgrade"] == MANUAL_VERIFY and d["needs_upgrade"] is not False


# ===================================================================================================
# Part 4 — per-host aggregation across CVEs
# ===================================================================================================

def test_merge_takes_max_target_across_cves_on_same_train():
    merged = UT._merge_host_decision([
        choose_target("17.9.1", ["17.9.3"], platform_hint="ios-xe"),
        choose_target("17.9.1", ["17.9.6"], platform_hint="ios-xe"),
    ])
    assert merged["needs_upgrade"] is True and merged["target"] == "17.9.6"  # clears the higher fix


def test_merge_any_manual_verify_makes_host_manual_verify():
    merged = UT._merge_host_decision([
        choose_target("17.9.1", ["17.9.3"], platform_hint="ios-xe"),      # confident
        choose_target("17.9.1", ["18.1.1"], platform_hint="ios-xe"),      # cross-train → MANUAL-VERIFY
    ])
    assert merged["needs_upgrade"] == MANUAL_VERIFY


# ===================================================================================================
# Part 5 — device current-version extraction (both channels)
# ===================================================================================================

def test_device_versions_from_devices_json_parses_inline_versions():
    groups = {"replace_upgrade_train": [
        "MERIDIAN-SW-001 [NX-OS 6.x 6.0(2)N2(3)]",
        "MERIDIAN-SW-051 [IOS XE 3.x 03.06.06E]",
        "MERIDIAN-SW-STORAGE-179 [IOS XE 3.x 03.11.03a.E]",
    ]}
    dv = UT.device_versions_from_devices_json(groups)
    assert dv["MERIDIAN-SW-001"]["sw_version"] == "6.0(2)N2(3)"
    assert dv["MERIDIAN-SW-001"]["platform"] == "nxos"
    assert dv["MERIDIAN-SW-051"]["sw_version"] == "03.06.06E"
    assert dv["MERIDIAN-SW-051"]["platform"] == "ios-xe"    # "IOS XE 3.x" label → ios-xe, not classic ios
    assert dv["MERIDIAN-SW-STORAGE-179"]["sw_version"] == "03.11.03a.E"


def test_device_versions_from_snapshot():
    snap = {"devices": {"r1": {"sw_version": "17.9.4a", "model": "C9300", "platform": "ios-xe"}},
            "software_risk": {"per_device": [{"host": "r1", "train": "IOS XE 17.x",
                                              "train_band": "Current-era", "platform": "ios-xe"}]}}
    dv = UT.device_versions_from_snapshot(snap)
    assert dv["r1"]["sw_version"] == "17.9.4a" and dv["r1"]["train_band"] == "Current-era"


def test_every_real_replace_upgrade_version_parses_or_is_declared(tmp_path):
    """Coverage-honesty on the REAL roster: every inline version in the committed devices JSON must either
    parse cleanly OR (if any doesn't) be surfaced — we never silently mis-handle a real release string."""
    import os
    path = os.path.join("docs", "security", "kev-exposure-2026-07-07-devices.json")
    if not os.path.exists(path):
        pytest.skip("devices JSON not present in this checkout")
    groups = json.load(open(path, encoding="utf-8"))
    dv = UT.device_versions_from_devices_json(groups)
    unparsed = {h: m["sw_version"] for h, m in dv.items()
                if parse_version(m["sw_version"], platform_hint=m["platform"]) is None}
    assert not unparsed, f"real roster versions the comparator does not recognize: {unparsed}"


# ===================================================================================================
# Part 6 — the join, and platform-correct not-applicability
# ===================================================================================================

_GROUPS = {
    "smart_install_flagged": ["IOS-A", "IOS-XE-B", "NXOS-C"],
    "http_server_flagged": ["IOS-XE-B", "NXOS-C"],
    "replace_upgrade_train": [],
}
_DV = {
    "IOS-A": {"sw_version": "15.2(2)E7", "platform": "ios", "model": "WS-C4948E"},
    "IOS-XE-B": {"sw_version": "03.06.06E", "platform": "ios-xe", "model": "WS-C3850-48T"},
    "NXOS-C": {"sw_version": "6.0(2)N2(3)", "platform": "nxos", "model": "N6K-C6001-64P"},
}


def test_join_nxos_is_not_applicable_to_ios_cves():
    res = UT.build_upgrade_targets([], _DV, _GROUPS)
    # NXOS-C is in the smart_install/http_server groups but the CVEs are IOS/IOS-XE → positively N/A
    assert "NXOS-C" in res["coverage"]["not_applicable"]
    assert all(r["host"] != "NXOS-C" for r in res["rows"])


# --- H2 regression: an UNKNOWN platform must NOT be silently dropped as not-applicable (guardrail 3:
# "not observed" is never "not vulnerable"). Only a POSITIVELY-known excluded family (NX-OS) is dropped.
# (Found by the independent verifier.)

def test_join_unknown_platform_sentinel_is_not_dropped_as_na():
    # '?' is the engine's own empty-platform sentinel (analyze.py: "platform": platform or "?")
    dv = {"H": {"sw_version": "15.2(2)E7", "platform": "?"}}
    res = UT.build_upgrade_targets([{"id": "CVE-2018-0171", "fixed": ["15.2(2)E10"]}], dv,
                                   {"smart_install_flagged": ["H"]})
    assert "H" not in res["coverage"]["not_applicable"]        # NOT silently dropped
    assert "H" in res["coverage"]["unknown_platform"]          # flagged as unknown-but-applicable
    assert any(r["host"] == "H" for r in res["rows"])          # still assessed


@pytest.mark.parametrize("plat", ["ios-xe", "iosxe", "ios xe", "IOS XE", "Cisco IOS", "ios"])
def test_join_ios_family_platform_variants_all_applicable(plat):
    dv = {"H": {"sw_version": "17.9.1", "platform": plat}}
    cve_map = {"CVE-2023-20198": {"group": "http_server_flagged", "applies_to": ("ios", "ios-xe"),
                                  "surface": "web"}}                # isolate to one CVE (merge precedence aside)
    res = UT.build_upgrade_targets([{"id": "CVE-2023-20198", "fixed": ["17.9.4a"]}], dv,
                                   {"http_server_flagged": ["H"]}, cve_map=cve_map)
    assert "H" not in res["coverage"]["not_applicable"]        # every IOS-family spelling is applicable
    assert any(r["host"] == "H" and r["needs_upgrade"] is True for r in res["rows"])


def test_join_no_fixed_intel_all_target_pending():
    res = UT.build_upgrade_targets([], _DV, _GROUPS)     # empty feed = the real state until the sweep runs
    ios_rows = [r for r in res["rows"] if r["host"] in ("IOS-A", "IOS-XE-B")]
    assert ios_rows and all(r["needs_upgrade"] == TARGET_PENDING for r in ios_rows)
    assert res["summary"]["cves_without_fixed"]        # honestly names the CVEs lacking a fix


def test_join_with_fixed_yields_migration_manual_verify_for_eol_3x():
    advisories = [{"id": "CVE-2023-20198", "fixed": ["17.9.4a", "16.12.10a"]}]
    res = UT.build_upgrade_targets(advisories, _DV, _GROUPS)
    b = next(r for r in res["rows"] if r["host"] == "IOS-XE-B")
    assert b["needs_upgrade"] == MANUAL_VERIFY            # 3.x → 17.x is a migration, not a target
    assert set(b["cross_train_fixes"]) == {"17.9.4a", "16.12.10a"}


def test_join_same_train_nxos_cve_yields_concrete_target():
    # a hypothetical NX-OS-applicable CVE with a same-train fix → concrete, confident target
    cve_map = {"CVE-XXXX-NXOS": {"group": "smart_install_flagged", "applies_to": ("nxos",),
                                 "surface": "NX-OS"}}
    advisories = [{"id": "CVE-XXXX-NXOS", "fixed": ["6.0(2)N2(4)"]}]
    res = UT.build_upgrade_targets(advisories, _DV, _GROUPS, cve_map=cve_map)
    c = next(r for r in res["rows"] if r["host"] == "NXOS-C")
    assert c["needs_upgrade"] is True and c["target"] == "6.0(2)N2(4)"


def test_join_version_unknown_is_a_coverage_bucket_not_a_row():
    dv = {"IOS-A": {"sw_version": "", "platform": "ios"}}
    res = UT.build_upgrade_targets([{"id": "CVE-2018-0171", "fixed": ["15.2(4)E10"]}], dv, _GROUPS)
    assert "IOS-A" in res["coverage"]["version_unknown"]
    assert all(r["host"] != "IOS-A" for r in res["rows"])


# ===================================================================================================
# Part 7 — end-to-end: openVuln JSON → feed → consumer → join (no egress; the producer contract)
# ===================================================================================================

def test_end_to_end_psirt_pipeline(tmp_path):
    # Representative openVuln advisory JSON (field names per research_lane.sources.map_psirt_advisories).
    # Fixture data — NOT an authoritative feed; it exercises the join the credential-gated sweep will feed.
    raw = [
        {"advisoryId": "cisco-sa-iosxe-webui", "cves": ["CVE-2023-20198"],
         "productNames": ["Cisco IOS XE Software"], "firstFixed": ["17.9.4a", "16.12.10a"],
         "sir": "Critical", "firstPublished": "2023-10-16"},
        {"advisoryId": "cisco-sa-nxos-si", "cves": ["CVE-XXXX-NXOS"],
         "productNames": ["Cisco NX-OS"], "fixedReleases": "6.0(2)N2(4)", "sir": "High"},
    ]
    entries = map_psirt_advisories(raw)
    assert any(e["id"] == "CVE-2023-20198" and e["fixed"] == ["16.12.10a", "17.9.4a"] for e in entries)

    d = tmp_path / "intel"
    d.mkdir()
    (d / "feed-2026-07-07.jsonl").write_text(IF.build_feed(entries, generated="2026-07-07"), encoding="utf-8")
    loaded = IF.load_feeds(str(d))
    assert loaded["advisories"], "hash-sealed feed should round-trip through the intake gate"

    cve_map = {"CVE-2023-20198": {"group": "http_server_flagged", "applies_to": ("ios-xe",), "surface": "web"},
               "CVE-XXXX-NXOS": {"group": "smart_install_flagged", "applies_to": ("nxos",), "surface": "nx"}}
    res = UT.build_upgrade_targets(loaded["advisories"], _DV, _GROUPS, cve_map=cve_map)
    b = next(r for r in res["rows"] if r["host"] == "IOS-XE-B")
    c = next(r for r in res["rows"] if r["host"] == "NXOS-C")
    assert b["needs_upgrade"] == MANUAL_VERIFY               # 3.x device, XE fix on another train
    assert c["needs_upgrade"] is True and c["target"] == "6.0(2)N2(4)"   # same-train NX-OS bump


def test_render_is_coverage_honest_when_no_fixed():
    out = UT.render(UT.build_upgrade_targets([], _DV, _GROUPS))
    assert "sweep" in out.lower() and "TARGET-PENDING" in out


def test_printed_strings_are_cp1252_console_safe():
    # L6 regression: reason + render text must encode on a legacy Windows (cp1252) console — no em-dash/arrow.
    res = UT.build_upgrade_targets([{"id": "CVE-2018-0171", "fixed": ["15.2(2)E10", "15.2(2)E12"]}],
                                   {"IOS-A": {"sw_version": "15.2(2)E7", "platform": "ios"}},
                                   {"smart_install_flagged": ["IOS-A"]})
    UT.render(res).encode("cp1252")                            # must not raise UnicodeEncodeError
    for r in res["rows"]:
        r["reason"].encode("cp1252")
