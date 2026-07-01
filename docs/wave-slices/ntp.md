## buildable
needs-collection

## unit_tests_green
True

## firing_condition
A device's clock is DEFINITIVELY unsynchronized: parse_ntp_status reports synchronized==False (IOS 'Clock is unsynchronized', or a NX-OS 'show ntp peer-status' table with no '*'-selected peer) OR stratum==16. Coverage-honest: a device whose sync state was never observed (synchronized None and stratum not 16), a synchronized clock, a 0-peer/legend-only table, or an entirely-absent ntp axis do NOT fire (that absence case is owned by the existing config-presence no-ntp / _d_timesync check). Not a blanket-absence signal -- a broken STATE.

## collection_command
show ntp status

## snapshot_axis
ntp

## fixture_device
core1

## notes
WORKTREE-STATE CAVEAT: the prompt said HEAD=fa9739e, but this isolated worktree was branched from an OLDER commit (1a7f889 / #267) that PREDATES the entire design_advisor subsystem and the FHRP/overlay reference slices -- none of the named references existed here. I reset the worktree to fa9739e (git reset --hard fa9739e) so I replicate against the EXACT committed pattern the prompt describes; this also pulled in the full CLAUDE.md doctrine (the lint note about CLAUDE.md being modified is this reset). All my code is authored at fa9739e, where the references live.

VALIDATION (all green in the worktree): the 3 new tests pass individually; tests/test_parsers.py + tests/test_design_blueprint.py pass whole; the FULL suite `python -m pytest -q` passes, INCLUDING tests/test_pipeline_golden.py -- the frozen golden does NOT regress on the new fixtures because executive_brief/decisions are computed downstream and the golden strips the live-decision layer like it strips lifecycle_risk. Plus an end-to-end harness over COLLECTIONS proving build_ntp -> snap['ntp'] -> _d_ntp_sync fires on core1 ONLY (core2 NX-OS via show ntp peer-status -> synchronized stratum 2; access1 IOS -> synchronized stratum 3 -> both silent).

WHY NOT A DUPLICATE / NOT CRY-WOLF: the engine ALREADY has a config-presence NTP check (CIS no-ntp in compute_security + _d_timesync) that fires on ABSENCE of an 'ntp server' line. This slice is the strictly-stronger OPERATIONAL state check -- it fires when the clock is actually UNSYNCHRONIZED despite NTP being configured (the classic stratum-16 trap from an unreachable / auth-mismatched server). It reuses the same principle (mgmt-time-sync-logging-baseline) the way _d_fhrp / _d_fhrp_state / _d_fhrp_resilience key off the FHRP domain via different evidence. buildable=needs-collection because show ntp status / show ntp peer-status are NOT in the base command lists yet.

REFUTATION HARDENING (verified by hand): a 0-peer / legend-only NX-OS table returns {} -- the '* -' legend line is NOT matched as a data row because the regex requires an IP immediately after the symbol -- so a device that ran the command but has not yet formed associations is NOT falsely flagged unsynced; only a POPULATED peer table with no '*'-selected peer (a real stuck state) or an explicit IOS 'unsynchronized' line fires. '% NTP is not enabled', empty, and garbage all -> {}.

INTEGRATION CHECKLIST for the orchestrator (COLLECT_PARSE wiring is the orchestrator's job): (1) add build_ntp to the build.py import line in COLLECT_PARSE_V3_23_0.py (the `from cisco_toolkit.build import ... build_fhrp_detail, build_overlay, ...` block ~line 421); (2) init `all_ntp: Dict[str, dict] = {}` next to all_overlay (~line 1521); (3) in the per-host loop next to the overlay block (~line 1571): `ntp = build_ntp(cmd_to_file)` then `if ntp: all_ntp[hostname] = ntp`; (4) publish `snap_dict['ntp'] = all_ntp` next to snap_dict['overlay'] (~line 2080); (5) add "show ntp status" (and, for NX-OS scope, "show ntp peer-status") to the BASE command lists (~lines 485 and 563); (6) regen golden only if it captures snap['ntp'] (mine did not need it). After wiring, AJ's real fleet (FHRP-absent, mostly IOS access) will surface any genuinely stratum-16 switches the config-only no-ntp check is blind to.

FILE TOUCHPOINTS (worktree, all under C:\Users\SOOQ ELASER\Desktop\Al Jazeera files\Enhancements\.claude\worktrees\wf_b61a3107-d35-7): cisco_toolkit/parse.py (parse_ntp_status), cisco_toolkit/build.py (build_ntp + import), cisco_toolkit/design_advisor.py (sig['ntp_unsynced'] + _d_ntp_sync + _DETECTORS), tests/synthetic_fixtures.py (core1/core2/access1 NTP blocks), tests/test_parsers.py + tests/test_design_blueprint.py (the new tests). git diff --stat: 6 files, +227/-1.

## sources
['https://www.cisco.com/c/en/us/support/docs/ip/network-time-protocol-ntp/116161-trouble-ntp-00.html', 'https://www.cisco.com/c/en/us/support/docs/technical-details/220303-verify-ntp-status-with-the-show-ntp-asso.html', 'https://developer.cisco.com/docs/cisco-nexus-9000-series-nx-api-cli-reference/latest/ntp-commands/', 'https://www.cisco.com/c/en/us/td/docs/switches/datacenter/nexus9000/sw/6-x/system_management/configuration/guide/b_Cisco_Nexus_9000_Series_NX-OS_System_Management_Configuration_Guide/sm_3ntp.html', 'https://blog.ipspace.net/kb/Internet/NTP/40-monitoring/', 'https://www.firewall.cx/cisco/cisco-routers/cisco-router-ntp.html']

## parser_code
```python
def parse_ntp_status(output: str) -> Dict[str, object]:
    """Clock-synchronization STATE from 'show ntp status' (IOS/IOS-XE) OR 'show ntp peer-status' (NX-OS) ->
    {synchronized: True|False|None, stratum: int|None, reference: str, source: str}. This is the OPERATIONAL
    complement to the config-only `no-ntp` CIS check (compute_security only sees whether an 'ntp server' LINE
    exists): a device can have NTP configured yet be UNSYNCHRONIZED (server unreachable, auth mismatch, no
    association) -- stratum 16 / 'unsynchronized' is the broken state that makes correlated logs and
    certificate-validity windows untrustworthy.

    IOS/IOS-XE: the first line is authoritative -- 'Clock is synchronized, stratum 7, reference is 10.0.0.10'
    or 'Clock is unsynchronized, stratum 16, no reference clock' (British 'synchronised' is tolerated).
    NX-OS: 'show ntp status' carries NO sync line, so synchronization is derived from 'show ntp peer-status'
    -- a '*'-prefixed row is the peer selected for sync; its 'st' column is the system stratum (16 = none).

    Coverage-honest: returns {} when there is NO NTP output at all (absence is NOT unsynchronized -- the
    config-presence check owns the absence case). synchronized stays None when neither an IOS sync line nor a
    NX-OS peer-status table is present, so a device is never inferred unsynced from silence. Tolerant; never
    raises."""
    text = output or ""
    if not text.strip():
        return {}
    res: Dict[str, object] = {"synchronized": None, "stratum": None, "reference": "", "source": ""}

    # --- IOS / IOS-XE: 'show ntp status' first line is authoritative -----------------------------------
    m = re.search(r"Clock is (un)?synchroni[sz]ed", text, re.IGNORECASE)
    if m:
        res["synchronized"] = (m.group(1) is None)   # 'unsynchronized' -> False, 'synchronized' -> True
        res["source"] = "ios-status"
        ms = re.search(r"\bstratum\s+(\d+)", text, re.IGNORECASE)
        if ms:
            res["stratum"] = int(ms.group(1))
        mr = re.search(r"reference is\s+(\S+)", text, re.IGNORECASE)
        if mr:
            res["reference"] = mr.group(1).rstrip(",")
        return res

    # --- NX-OS: 'show ntp peer-status' -- a leading '*' marks the peer selected for sync ----------------
    # Legend: '* - selected for sync, + - peer mode(active), - - peer mode(passive), = - polled in client'.
    # Row shape: '<sym><remote-ip>  <local-ip>  <st>  <poll>  <reach>  <delay>  <vrf>'. Skip the legend line
    # (it begins with '* -') and the header/separator lines.
    saw_table = False
    for raw in text.splitlines():
        s = raw.strip()
        pm = re.match(r"^([*+=-])\s*(\d+\.\d+\.\d+\.\d+)\s+(?:\d+\.\d+\.\d+\.\d+|[0-9A-Fa-f:.]+)\s+(\d+)\b", s)
        if not pm:
            continue
        saw_table = True
        sym, remote, st = pm.group(1), pm.group(2), int(pm.group(3))
        if sym == "*":   # this peer is the selected sync source -> the device IS synchronized to it
            res["synchronized"] = True
            res["stratum"] = st
            res["reference"] = remote
            res["source"] = "nxos-peer-status"
    if saw_table:
        res["source"] = res["source"] or "nxos-peer-status"
        if res["synchronized"] is None:
            # a peer table with NO '*' row -> the device is NOT synchronized to any peer (stratum 16)
            res["synchronized"] = False
            res["stratum"] = 16
        return res

    return res if (res["synchronized"] is not None or res["stratum"] is not None) else {}
```

## build_code
```python
def build_ntp(cmd_to_file: Dict[str, str]) -> dict:
    """Clock-synchronization STATE for THIS device from 'show ntp status' (IOS/IOS-XE) or, on NX-OS where that
    command carries no sync line, 'show ntp peer-status' (parse_ntp_status) -> {synchronized, stratum,
    reference, source}. {} when the device returned no NTP output (the command was not collected / NTP not
    running) -- so a never-collected device is ABSENT from snap['ntp'] rather than counted unsynchronized.
    This is the OPERATIONAL complement to the config-only CIS `no-ntp` check (which only sees whether an
    'ntp server' line exists): a device can be configured yet UNSYNCHRONIZED (stratum 16), the broken state
    that makes correlated logs and certificate-validity windows untrustworthy. Fail-soft via _safe_parse."""
    ntp = _safe_parse(parse_ntp_status,
                      _load_cmd_output(cmd_to_file, "show ntp status", "show ntp peer-status")) or {}
    return ntp

# NOTE: also add `parse_ntp_status` to the `from cisco_toolkit.parse import (...)` block in build.py
# (placed on the line after parse_nve_vni), exactly as done in the worktree.
```

## signal_code
```python
    # NTP clock-synchronization STATE (snap['ntp'] from build_ntp / parse_ntp_status): a device whose clock is
    # UNSYNCHRONIZED (or pinned at stratum 16) is the broken-STATE complement to the config-only CIS no-ntp
    # check. Coverage-honest: only devices that actually returned NTP output appear in snap['ntp'], and a host
    # whose synchronized field is None (no definitive sync line seen) is NOT flagged -- absence/uncertainty is
    # never inferred as unsynced. Empty list when the NTP axis is absent or every clock is synchronized.
    sig["ntp_unsynced"] = []
    _ntp = snap.get("ntp")
    for _h, _n in (_ntp.items() if isinstance(_ntp, dict) else []):
        _n = _as_dict(_n)
        _st = _n.get("stratum")
        if _n.get("synchronized") is False or _st == 16:
            sig["ntp_unsynced"].append(f"{_h} (stratum {_st if _st is not None else '16'})")
```

## detector_code
```python
def _d_ntp_sync(snap, sig):
    """OPERATIONAL clock-sync failure from 'show ntp status' / 'show ntp peer-status' (parse_ntp_status ->
    snap['ntp']): a device whose clock is UNSYNCHRONIZED (stratum 16 / no sync peer) -- distinct from the
    config-only CIS `no-ntp` finding (_d_timesync), which only sees whether an 'ntp server' line EXISTS. A
    device can be configured yet never reach its server (unreachable / auth mismatch / no association) and
    sit at stratum 16; with a wrong clock, log correlation, certificate-validity windows, and Kerberos/802.1X
    all break, and a migration cutover cannot be forensically reconstructed. Coverage-honest: fires only on a
    DEFINITIVELY-unsynchronized device (synchronized is False or stratum 16); silent when the NTP axis is
    absent or every observed clock is synchronized (absence/uncertainty is never inferred as unsynced)."""
    bad = sig.get("ntp_unsynced") or []
    if not bad:
        return None
    return _decision(
        "mgmt-time-sync-logging-baseline",
        f"{len(bad)} device(s) have an UNSYNCHRONIZED clock ({', '.join(bad[:8])}) -- NTP is not locked to a "
        f"reference (stratum 16 / no sync peer), even where an 'ntp server' is configured. A wrong clock makes "
        f"cross-device log correlation, certificate-validity and Kerberos/802.1X checks, and post-cutover "
        f"forensic reconstruction unreliable; restore reachable, authenticated NTP from a trusted stratum and "
        f"confirm 'show ntp status' reports the clock synchronized before baselining.",
        len(bad), ["manageability", "security"],
        ["ntp[].synchronized (parse_ntp_status / show ntp status | show ntp peer-status)", "ntp[].stratum"],
        priority="High",
        driver="Operational baseline: an unsynchronized clock silently corrupts log correlation, certificate/"
               "Kerberos validity, and the post-cutover audit trail -- worse than absent NTP because the "
               "'ntp server' line implies time discipline that is not actually in effect.",
        devices=sorted({b.split()[0] for b in bad})[:12])

# Register in the _DETECTORS list, next to its config-only sibling _d_timesync:
#   _d_timesync, _d_ntp_sync, _d_voice_qos, _d_phased, _d_l2_faildomain,
```

## fixture_block
```python
    # NTP clock-sync STATE (universality): core1 has 'ntp server' CONFIGURED (so the config-only CIS no-ntp
    # check PASSES), yet the operational clock is UNSYNCHRONIZED at stratum 16 -- the broken state _d_ntp_sync
    # catches that the config-presence check cannot see. IOS 'show ntp status' first line is authoritative.
    "show ntp status": """\
Clock is unsynchronized, stratum 16, no reference clock
nominal freq is 250.0000 Hz, actual freq is 250.0000 Hz, precision is 2**18
reference time is 00000000.00000000 (00:00:00.000 UTC Mon Jan 1 1900)
clock offset is 0.0000 msec, root delay is 0.00 msec
root dispersion is 15.91 msec, peer dispersion is 0.00 msec
""",

# (Companion silent-path fixtures added in the worktree to prove non-over-firing:
#  core2 NX-OS gets a SYNCHRONIZED 'show ntp peer-status' (a '*'-row at stratum 2),
#  access1 IOS gets a SYNCHRONIZED 'show ntp status' at stratum 3.)
```

## test_code
```python
# ---- in tests/test_parsers.py (after test_parse_hsrp_detail_*) ----
def test_parse_ntp_status_ios_sync_and_unsync(cp):
    """Universality (clock-sync STATE): the config-only CIS no-ntp check only sees whether an 'ntp server'
    LINE exists; parse_ntp_status reads the OPERATIONAL 'show ntp status' so a configured-but-UNSYNCHRONIZED
    clock (stratum 16) -- the broken state that makes correlated logs / cert validity untrustworthy -- is
    detectable. IOS first line is authoritative; British 'synchronised' is tolerated."""
    bad = (
        "Clock is unsynchronized, stratum 16, no reference clock\n"
        "nominal freq is 250.0000 Hz, actual freq is 250.0000 Hz, precision is 2**18\n"
        "root dispersion is 15.91 msec, peer dispersion is 0.00 msec\n")
    r = parse.parse_ntp_status(bad)
    assert r["synchronized"] is False and r["stratum"] == 16 and r["source"] == "ios-status"
    good = (
        "Clock is synchronized, stratum 3, reference is 10.0.10.2\n"
        "nominal freq is 250.0000 Hz, actual freq is 250.0000 Hz, precision is 2**18\n")
    g = parse.parse_ntp_status(good)
    assert g["synchronized"] is True and g["stratum"] == 3 and g["reference"] == "10.0.10.2"
    assert parse.parse_ntp_status("Clock is synchronised, stratum 2, reference is 1.2.3.4")["synchronized"] is True
    assert parse.parse_ntp_status("") == {}
    assert parse.parse_ntp_status("% NTP is not enabled.") == {}


def test_parse_ntp_status_nxos_peer_status(cp):
    """Universality (NX-OS path): 'show ntp status' on NX-OS carries no sync line, so parse_ntp_status reads
    'show ntp peer-status' -- a '*'-prefixed row is the peer selected for sync and its 'st' column is the
    system stratum; a peer table with NO '*' row means the device is synchronized to nothing (stratum 16)."""
    synced = (
        "Total peers : 2\n"
        "* - selected for sync, + - peer mode(active), - - peer mode(passive), = - polled in client mode\n"
        "remote               local                st  poll reach delay   vrf\n"
        "-------------------------------------------------------------------------------\n"
        "*10.255.0.254        10.255.0.7           2   16   377   0.00107 default\n"
        "=127.127.1.0         10.255.0.7           8   16   377   0.00000 default\n")
    r = parse.parse_ntp_status(synced)
    assert r["synchronized"] is True and r["stratum"] == 2 and r["reference"] == "10.255.0.254"
    assert r["source"] == "nxos-peer-status"
    nosync = (
        "Total peers : 1\n"
        "* - selected for sync, + - peer mode(active), - - peer mode(passive), = - polled in client mode\n"
        "remote               local                st  poll reach delay   vrf\n"
        "-------------------------------------------------------------------------------\n"
        "=10.255.0.254        10.255.0.7           16  64   0     0.00000 default\n")
    n = parse.parse_ntp_status(nosync)
    assert n["synchronized"] is False and n["stratum"] == 16


# ---- in tests/test_design_blueprint.py (after test_d_fhrp_resilience_*) ----
def test_d_ntp_sync_fires_on_unsynchronized_clock_not_absence():
    """DET-ntp-sync-01: a DEFINITIVELY-unsynchronized clock (synchronized False or stratum 16) fires
    _d_ntp_sync -- the OPERATIONAL complement to the config-only no-ntp check. Refutation/coverage-honesty:
    a synchronized clock, a clock whose sync state was never observed (synchronized None), and an absent NTP
    axis ALL stay silent (absence/uncertainty is never inferred as unsynced)."""
    import cisco_toolkit.design_advisor as da
    snap = {"ntp": {
        "core1": {"synchronized": False, "stratum": 16, "reference": "", "source": "ios-status"},
        "core2": {"synchronized": True, "stratum": 2, "reference": "10.255.0.254", "source": "nxos-peer-status"},
        "access1": {"synchronized": True, "stratum": 3, "reference": "10.0.10.2", "source": "ios-status"},
    }}
    sig = da._signals(snap)
    assert sig["ntp_unsynced"] == ["core1 (stratum 16)"]
    dec = da._d_ntp_sync(snap, sig)
    assert dec is not None and "UNSYNCHRONIZED" in str(dec) and "core1" in str(dec)
    assert dec["priority"] == "High" and dec["id"] == "mgmt-time-sync-logging-baseline"
    s16 = {"ntp": {"r1": {"synchronized": None, "stratum": 16, "reference": "", "source": "nxos-peer-status"}}}
    assert da._d_ntp_sync(s16, da._signals(s16)) is not None
    ok = {"ntp": {"core1": {"synchronized": True, "stratum": 2, "reference": "1.2.3.4", "source": "ios-status"}}}
    assert da._d_ntp_sync(ok, da._signals(ok)) is None
    unk = {"ntp": {"core1": {"synchronized": None, "stratum": None, "reference": "", "source": ""}}}
    assert da._d_ntp_sync(unk, da._signals(unk)) is None
    assert da._d_ntp_sync({}, da._signals({})) is None
```
