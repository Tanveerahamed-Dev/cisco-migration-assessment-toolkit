"""[audit-5 false-health batch] absence or weakness of a control must NOT read as healthy/clean/pass. Each test
plants the real-shaped insecure-but-present case and asserts it is surfaced, not silently passed."""
from cisco_toolkit import parse


def _ins(cfg):
    return {f["id"]: f for f in parse.parse_security(cfg)["findings"]}["insecure-snmp"]


def test_parse_security_snmpv3_noauth_and_weak():
    """[#2 HIGH / #20] The SNMPv3 check PASSed on the mere PRESENCE of an 'snmp-server user/group' line, so a
    noAuthNoPriv user (no auth -> no security) false-PASSed, and md5/des weak auth read as a clean 'auth/priv'
    PASS. Now noAuthNoPriv -> FAIL(high); weak md5/des -> PASS but disclosed."""
    f = _ins("feature ssh\nsnmp-server user OPER network-operator\n")     # no auth keyword -> noAuthNoPriv
    assert f["status"] == "fail" and f["severity"] == "high"
    fw = _ins("snmp-server user admin network-admin auth md5 0xabc priv 0xabc localizedkey\n")
    assert fw["status"] == "pass" and ("md5" in fw["detail"].lower() or "weak" in fw["detail"].lower())
    assert _ins("snmp-server user U vdc-operator auth sha 0xabc priv aes-128 0xdef localizedkey\n")["status"] == "pass"


def test_build_network_model_skips_no_ip_svi_gateway():
    """[#1 HIGH] build_network_model registered EVERY 'VlanN' SVI as a gateway regardless of an IP, so the
    universal no-IP Vlan1 interface became a phantom gateway on 243 devices -> 60 false 'VLAN 1: Hard partition'
    High failure_impact records (stranded:0). Only an SVI WITH an svi_ip is a real L3 gateway."""
    from cisco_toolkit import analyze
    from cisco_toolkit.model import InterfaceData
    ai = {"SW1": {
        "Vlan1":  InterfaceData(port="Vlan1"),                       # no svi_ip -> NOT a gateway
        "Vlan10": InterfaceData(port="Vlan10", svi_ip="10.0.10.1"),  # real gateway
    }}
    gw = analyze.build_network_model(ai)["gw"]
    assert 1 not in gw and 10 in gw


def test_wave_sequencing_uncollected_is_unknown_homing_not_single_homed():
    """[#7 HIGH] compute_wave_sequencing classified a switch single-homed (hard cutover) when its topology
    adjacency was empty -- but a NEVER-COLLECTED device has empty adjacency from absence of evidence, not from
    being single-homed. 50 uncollected Meridian devices were labeled 'single-homed -> hard cutover'. Uncollected ->
    homing UNKNOWN."""
    from cisco_toolkit import analyze
    from cisco_toolkit.model import InterfaceData
    ai = {"collected1": {"Gi0/1": InterfaceData(port="Gi0/1")}}   # collected, no 2nd uplink -> single-homed
    out = analyze.compute_wave_sequencing(ai, [{"switches": ["collected1", "uncollected1"]}])
    row = out[0]
    assert "uncollected1" in row["homing_unknown"]               # never collected -> UNKNOWN
    assert "uncollected1" not in row["hard_cutover"]
    assert "collected1" in row["hard_cutover"]                   # genuinely single-homed (collected, no 2nd uplink)
    assert "UNKNOWN" in row["sequence"]


def test_syslog_intelligence_catalyst_sev4_psu_failure_surfaced():
    """[#11 HIGH] The environment-event classifier gated on 'sev <= 3', so the Catalyst 4500/4948 PSU-failure
    syslog '%...-4-POWERSUPPLYBAD' (severity 4) was silently dropped -- a real hardware failure read as healthy.
    A sev-4 FAILURE mnemonic now surfaces; benign sev-4 env info (FANOK) still skipped (no cry-wolf)."""
    from cisco_toolkit import analyze
    bad = "*Mar  1 00:00:00.000: %C4K_IOSMODPORTMAN-4-POWERSUPPLYBAD: Power supply 1 has failed or been turned off\n"
    assert any(d["kind"] == "environment" for d in analyze.compute_syslog_intelligence({"sw1": bad})["detections"])
    ok = "%PLATFORM-4-FANOK: Fan module 1 is OK\n"
    assert not any(d["kind"] == "environment" for d in analyze.compute_syslog_intelligence({"sw1": ok})["detections"])


def test_vrrp_abbreviated_vlan_iface_not_dropped():
    """[#8 HIGH] is_valid_iface rejected the abbreviated SVI form 'Vl10' (only 'Vlan10' passed) and
    normalize_ifname kept them distinct, so a VRRP/GLBP gateway shown on 'Vl10' in 'show vrrp brief' was silently
    dropped -> the VLAN read as no-FHRP (a redundant gateway hidden). 'Vl10' now canonicalizes to 'Vlan10'."""
    assert parse.normalize_ifname("Vl10") == "Vlan10"
    assert parse.normalize_ifname("Vlan10") == "Vlan10"    # canonical form unchanged
    assert parse.is_valid_iface("Vl10")
    out = ("Interface  Grp Pri Time  Own Pre State   Master addr     Group addr\n"
           "Vl10       1   100 3609   Y   Y   Master  10.10.10.1      10.10.10.254\n")
    r = parse.parse_vrrp_summary(out)
    assert "Vlan10" in r and "VRRP" in r["Vlan10"]         # keyed canonically -> matches the Vlan10 SVI


def test_parse_ptp_clock_ignores_deprecated_command_banner():
    """[#13] 'show ptp clock' on NX-OS can return '% Unavailable command (deprecated by show ptp local-clock)' --
    that banner mentions 'ptp', so parse_ptp_clock parsed it into a (mostly empty) dict and the device read as
    PTP-present. An error/deprecation banner -> {} (no PTP); a real clock still parses."""
    assert parse.parse_ptp_clock("% Unavailable command (deprecated by show ptp local-clock)\n") == {}
    real = parse.parse_ptp_clock("PTP Device Type: boundary-clock\nPTP Device Profile: smpte-2059-2\n")
    assert real and real["device_type"] == "boundary-clock"


def test_trunk_native_sheet_no_mismatch_discloses_coverage():
    """[#6] When there are no native-VLAN mismatches the sheet printed an unqualified 'clean -- No native-VLAN
    mismatches on inter-switch trunks', reading absence-of-collection as health. It must instead disclose the
    basis (collected devices only; uncollected not assessed)."""
    import pytest
    openpyxl = pytest.importorskip("openpyxl")
    from cisco_toolkit import excel
    from cisco_toolkit.model import InterfaceData
    wb = openpyxl.Workbook()
    excel.write_trunk_native_sheet(wb, {"sw1": {"Gi0/1": InterfaceData(port="Gi0/1")}})   # no trunks -> no mismatch
    ws = wb[excel.TRUNK_NATIVE_SHEET_NAME]
    banner = " ".join(str(ws.cell(2, c).value or "") for c in (1, 2)).lower()
    assert "not assessed" in banner and ("uncollected" in banner or "collected" in banner)
    assert banner.strip() != "clean no native-vlan mismatches on inter-switch trunks"


def _trunk_native_banner(all_interfaces):
    """Render the sheet and return its no-mismatch banner cell."""
    import pytest
    openpyxl = pytest.importorskip("openpyxl")
    from cisco_toolkit import excel
    wb = openpyxl.Workbook()
    excel.write_trunk_native_sheet(wb, all_interfaces)
    return str(wb[excel.TRUNK_NATIVE_SHEET_NAME].cell(2, 2).value or "")


def _if(port, **kw):
    from cisco_toolkit.model import InterfaceData
    return InterfaceData(port=port, **kw)


def test_trunk_native_no_mismatch_states_compared_links_not_a_device_count():
    """QA row 15 + its refutation. The banner rendered len(all_interfaces) labelled "collected device(s)" --
    on M0 "across the 303 collected device(s)" when 253 were collected. NO device count derived from that map
    is honest: it holds an entry per in-scope device only on --no-collect (a LIVE run DROPS an unreachable
    device), and even a correct collected count credits devices that sat on no compared link (M0: 253 with
    ports, 149 on a both-ends-collected link). The banner must state what the check actually COMPARED -- links
    with both ends collected -- and disclose the uncompared remainder.

    Fixture is deliberately ASYMMETRIC (compared=1, gap=3, observed=4, devices=2): every number differs, so an
    implementation that swaps them, or reverts to any device count, cannot render this string."""
    banner = _trunk_native_banner({
        "sw1": {"Gi0/1": _if("Gi0/1", cdp_neighbor="sw2", neighbor_port="Gi0/1", endpoint_type="Switch"),
                # three links to switches that were NEVER collected -> far end unresolvable, NOT comparable
                "Gi0/2": _if("Gi0/2", cdp_neighbor="ghostA", neighbor_port="Gi0/9", endpoint_type="Switch"),
                "Gi0/3": _if("Gi0/3", cdp_neighbor="ghostB", neighbor_port="Gi0/9", endpoint_type="Switch"),
                "Gi0/4": _if("Gi0/4", cdp_neighbor="ghostC", neighbor_port="Gi0/9", endpoint_type="Switch")},
        "sw2": {"Gi0/1": _if("Gi0/1", cdp_neighbor="sw1", neighbor_port="Gi0/1", endpoint_type="Switch")},
    })
    # EXACT equality, not substring: an unanchored "3 of 4" check is satisfied by "-3 of 4" (a sign-flipped
    # gap) and by "13 of 4" (a prefixed figure) -- a refuter proved a sign-flip mutant shipping a NEGATIVE
    # link count survived the substring form. Equality pins every digit, both figures, and the wording.
    assert banner == (
        "No native-VLAN mismatch found. 1 inter-switch link(s) with both ends collected were compared; "
        "3 of 4 observed link(s) had an uncollected far end and were NOT compared. Uncollected devices, "
        "and any trunk whose far end was not collected, are NOT assessed -- this is not a fleet-wide "
        "guarantee."), banner
    # and no device-count framing may return in ANY form (the defect and its first, also-wrong fix)
    for forbidden in ("device(s) with collected interface data", "collected device(s)", "in-scope device(s)"):
        assert forbidden not in banner, f"device-count framing returned: {banner}"


def test_trunk_native_no_mismatch_omits_gap_clause_when_everything_compared():
    """The other branch of the conditional (gap == 0) -- unpinned branches are how a mutant survives. With
    every link's far end collected there is no uncompared remainder to disclose, so the parenthetical must be
    ABSENT (not rendered as a vacuous '0 of N'), while the coverage-honest tail still stands."""
    banner = _trunk_native_banner({
        "sw1": {"Gi0/1": _if("Gi0/1", cdp_neighbor="sw2", neighbor_port="Gi0/1", endpoint_type="Switch")},
        "sw2": {"Gi0/1": _if("Gi0/1", cdp_neighbor="sw1", neighbor_port="Gi0/1", endpoint_type="Switch")},
    })
    assert banner == (
        "No native-VLAN mismatch found. 1 inter-switch link(s) with both ends collected were compared. "
        "Uncollected devices, and any trunk whose far end was not collected, are NOT assessed -- this is "
        "not a fleet-wide guarantee."), banner
    assert "NOT compared" not in banner, f"vacuous gap clause rendered: {banner}"
    assert "0 of" not in banner, banner


def test_trunk_native_discloses_coverage_even_when_mismatches_are_listed():
    """The clean case disclosed its blind spot but the FINDINGS case said nothing: rows were listed with no
    statement of how many links could not be compared at all -- the same concealment, and worse, since a
    reader looking at real findings most needs to know what the check could not see. Both branches now
    emit the identical coverage sentence, built once."""
    import pytest
    openpyxl = pytest.importorskip("openpyxl")
    from cisco_toolkit import excel
    ai = {
        "sw1": {"Gi0/1": _if("Gi0/1", cdp_neighbor="sw2", neighbor_port="Gi0/1", endpoint_type="Switch",
                             trunk_native_vlan="1"),
                "Gi0/2": _if("Gi0/2", cdp_neighbor="ghostA", neighbor_port="Gi0/9", endpoint_type="Switch")},
        "sw2": {"Gi0/1": _if("Gi0/1", cdp_neighbor="sw1", neighbor_port="Gi0/1", endpoint_type="Switch",
                             trunk_native_vlan="99")},
    }
    wb = openpyxl.Workbook()
    excel.write_trunk_native_sheet(wb, ai)
    ws = wb[excel.TRUNK_NATIVE_SHEET_NAME]
    assert str(ws.cell(2, 2).value) == "1" and str(ws.cell(2, 4).value) == "99"   # the mismatch row itself
    assert ws.cell(3, 1).value == "coverage"
    assert ws.cell(3, 2).value == (
        "1 inter-switch link(s) with both ends collected were compared; 1 of 2 observed link(s) had an "
        "uncollected far end and were NOT compared. Uncollected devices, and any trunk whose far end was "
        "not collected, are NOT assessed -- this is not a fleet-wide guarantee."), ws.cell(3, 2).value


def test_trunk_native_coverage_counts_the_population_the_check_compares():
    """The banner's numbers and the mismatch rows must come from ONE walk (_trunk_link_ends), so the disclosed
    coverage can never describe a different population than the check ran on: the mismatch found here sits on
    the single comparable link, and the uncollected-far-end link is counted as observed-but-not-compared."""
    from cisco_toolkit import excel
    ai = {
        "sw1": {"Gi0/1": _if("Gi0/1", cdp_neighbor="sw2", neighbor_port="Gi0/1", endpoint_type="Switch",
                             trunk_native_vlan="1"),
                "Gi0/2": _if("Gi0/2", cdp_neighbor="ghostA", neighbor_port="Gi0/9", endpoint_type="Switch",
                             trunk_native_vlan="1")},
        "sw2": {"Gi0/1": _if("Gi0/1", cdp_neighbor="sw1", neighbor_port="Gi0/1", endpoint_type="Switch",
                             trunk_native_vlan="99")},
    }
    cov = excel.compute_trunk_native_coverage(ai)
    assert cov == {"links_observed": 2, "links_compared": 1}, cov
    rows = excel.compute_trunk_native_mismatches(ai)
    assert len(rows) == 1 and {rows[0]["a_native"], rows[0]["b_native"]} == {"1", "99"}, rows
    assert len(rows) <= cov["links_compared"]   # a mismatch can only be found on a COMPARED link


def test_config_hygiene_sheet_empty_discloses_coverage():
    """[#23] An empty Config Hygiene sheet (no undefined/unused issues) showed nothing, reading as a fleet-wide
    clean bill though only collected devices are assessed. The empty case now discloses the assessed scope."""
    import pytest
    openpyxl = pytest.importorskip("openpyxl")
    from cisco_toolkit import excel
    wb = openpyxl.Workbook()
    excel.write_config_hygiene_sheet(wb, {"sw1": {"undefined": [], "unused": [], "summary": {}}})
    ws = wb[excel.CONFIG_HYGIENE_SHEET_NAME]
    banner = " ".join(str(ws.cell(2, c).value or "") for c in (1, 2)).lower()
    assert "not assessed" in banner and "collected running-config" in banner


def test_campaign_trend_collected_switch_going_dark_is_not_clean_improving():
    """[#9 HIGH] The survivorship guard detected only devices REMOVED from 'devices', but the engine keeps an
    uncollected device as an 'Insufficient Data' STUB in 'devices'. A previously-collected switch going dark
    (real band -> 'Insufficient Data') raised avg-health (its low score drops out of the average) and read as
    IMPROVING with no disclosure. The band transition now counts as gone-dark."""
    from cisco_toolkit.html import compute_campaign_trend

    def snap(hs, avg):
        return {"devices": {h["switch"]: {} for h in hs}, "interfaces": {}, "health_scores": hs,
                "punchlist": [], "executive_brief": {"posture": {"avg_health": avg}}}
    c1 = snap([{"switch": "a", "band": "Critical", "score": 10},
               {"switch": "b", "band": "Good", "score": 80}], avg=45)
    c2 = snap([{"switch": "a", "band": "Insufficient Data", "score": 90},   # 'a' went dark, still in devices
               {"switch": "b", "band": "Good", "score": 80}], avg=85)        # avg rose -> survivorship
    t = compute_campaign_trend([c1, c2])
    assert t["verdict"] != "IMPROVING"                    # survivorship -> not a clean improvement
    assert "dark" in t["verdict_note"].lower()


def test_vlan_affinity_includes_unknown_no_minority_label():
    """[#24] Per-VLAN affinity excluded 'Unknown' endpoints from vlan_cls, so a VLAN that is mostly unclassified
    with a tiny KNOWN minority was labelled with that minority's app tier. Unknown is now counted, so the
    dominant reflects the true majority and the total is honest."""
    from cisco_toolkit import analyze
    ident = [{"host": "sw1", "mac": f"0000.0000.{i:04x}", "ip": "", "vlan": "100", "vendor": "v",
              "endpoint_class": ("Server" if i == 0 else "Unknown")} for i in range(10)]
    v100 = next(a for a in analyze.compute_endpoint_dependencies(ident)["affinity"] if a["vlan"] == "100")
    assert v100["total"] == 10                   # all 10 counted (9 Unknown + 1 Server), not just the minority
    assert v100["dominant"] == "Unknown"          # the 90% majority, not the 10% Server minority


def test_ssot_reconcile_flags_n_domains_drift():
    """[audit-5 scale-ssot #1/#2] executive_brief.scale.n_domains was published + served via SSOT but had NO
    reconcile check, so a drift vs its raw basis (len(application_intelligence.domains)) went undetected."""
    from cisco_toolkit import ssot
    drift = {"executive_brief": {"scale": {"n_domains": 7}},
             "application_intelligence": {"domains": [{"id": "d1"}, {"id": "d2"}]}}   # basis 2 != published 7
    assert any("n_domains" in s for s in ssot.reconcile(drift))
    ok = {"executive_brief": {"scale": {"n_domains": 2}},
          "application_intelligence": {"domains": [{"id": "d1"}, {"id": "d2"}]}}
    assert not any("n_domains" in s for s in ssot.reconcile(ok))


def test_inventory_num_power_supplies_excludes_fex():
    """[audit-5 scale-ssot #3] num_power_supplies counted FEX/child fabric-extender PSUs INTO the parent Nexus
    -> an over-count. A FEX-named PSU belongs to the FEX, not the parent chassis."""
    inv = ('NAME: "Chassis", DESCR: "Nexus5548 Chassis"\nPID: N5K-C5548UP , VID: V01 , SN: SSI1\n\n'
           'NAME: "Power Supply 1", DESCR: "Power Supply"\nPID: N55-PAC-1100W , VID: V01 , SN: PS1\n\n'
           'NAME: "Fex 101 Power Supply 1", DESCR: "Fabric Extender Power Supply"\n'
           'PID: NXA-PAC-650W , VID: V01 , SN: FX1\n')
    r = parse.parse_show_inventory(inv)
    assert r["num_power_supplies"] == 1     # only the parent PSU, not the FEX's


def test_endpoint_cluster_counts_distinct_macs_not_rows():
    """[audit-5 scale-ssot #0] The endpoint cluster 'count' incremented per (host,port) ROW, so the SAME MAC
    seen on multiple ports/switches inflated the cluster size. It must count DISTINCT MACs."""
    from cisco_toolkit import analyze
    rows1 = [{"host": f"sw{i}", "mac": "0000.0000.0001", "ip": "", "vlan": "10", "vendor": "Acme",
              "endpoint_class": "Server"} for i in range(4)]            # 4 rows, ONE MAC
    assert not any(c["vendor"] == "Acme" for c in analyze.compute_endpoint_dependencies(rows1)["clusters"])
    rows2 = [{"host": "sw1", "mac": f"0000.0000.000{i}", "ip": "", "vlan": "10", "vendor": "Acme",
              "endpoint_class": "Server"} for i in range(3)]            # 3 DISTINCT MACs
    acme = next(c for c in analyze.compute_endpoint_dependencies(rows2)["clusters"] if c["vendor"] == "Acme")
    assert acme["count"] == 3
