## buildable
needs-collection

## unit_tests_green
True

## firing_condition
A storm-control rule is CONFIGURED (a real Upper threshold is present in 'show storm-control', i.e. configured==True) AND its action is exactly 'None'. Fires per (host, interface, traffic-class). Silent when: the rule is properly actioned (Trap/Shutdown), the row is not configured (no threshold), the older no-Action output form is in use (action ''), or the storm_control axis was not collected. This is a broken/ineffective STATE on present config, never blanket absence -> no cry-wolf.

## collection_command
show storm-control

## snapshot_axis
storm_control

## fixture_device
access1

## notes
WORKTREE STATE: The prompt said HEAD is fa9739e, but this worktree was actually checked out at the OLD commit 1a7f889 (branch worktree-wf_b61a3107-d35-5) where design_advisor.py / build_fhrp_detail / parse_hsrp_detail do NOT exist. I `git reset --hard fa9739e` (worktree was clean, no changes lost) so I worked against the correct reference base that the orchestrator will integrate into. All my edits are on top of fa9739e.

VALIDATION: Full engine suite = 576 passed, exit 0 (157s), AFTER regenerating the golden with UPDATE_GOLDEN=1. The ONLY golden change is the new top-level key 'storm_control' (44 lines added to tests/golden/snapshot.json) -- expected golden-drift from publishing a new axis, which the prompt says the orchestrator owns. test_pipeline_inprocess passed unchanged. End-to-end proof: COLLECT_PARSE imports clean with the new build import wired; the access1 fixture parses to 4 rows; _d_storm_control_action fires on exactly the 2 action=None rows and is silent on the Shutdown/Trap rows.

BUILDABLE = needs-collection: 'show storm-control' is NOT in either base command list (COMMANDS_NXOS / COMMANDS_IOS) at fa9739e -- I added it to both (same command string on IOS and NX-OS). Once collected, the Action column gives a clean, dedicated, non-cry-wolf signal. I chose to parse the dedicated 'show storm-control' (gives the live Filter State + Action directly) rather than regex the running-config interface stanzas (which would require inferring platform-default action -- IOS default None/silent vs NX-OS default trap-on -- and is noisier).

COVERAGE-HONESTY DECISIONS: (1) Fire only on configured==True rows, so a port with NO storm-control never appears -> never flagged (avoids the blanket-absence cry-wolf the prompt warns against). (2) Parse the LIVE Action rather than infer platform defaults. (3) The older no-Action output form yields action '' -> detector stays silent (a 2nd parser test pins this). (4) Detector returns None on absent axis and on all-actioned fleets.

KB PRINCIPLE: I used a self-descriptive pid 'storm-control-action-on-edge'. There is no matching principle in design_kb.DOCTRINE yet (storm-control appears only in Multi-Site BUM doctrine text). The _decision() helper degrades gracefully on an unknown pid (title falls back to the pid, empty citation), and I supply explicit driver/priority, so the decision is fully populated except the formal citation. RECOMMENDATION for the orchestrator: add a design_kb principle id 'storm-control-action-on-edge' (domain campus-access or dc-switching, engine_actionable=True, priority Medium, citing the Cisco storm-control config guide) so the decision carries a formal citation like the FHRP/NVE detectors do.

PRIORITY: Medium (operations-visibility + availability). A toothless storm-control rule is a gap, not an active outage -- it still drops the storm; it just hides it. Deliberately below the High/Critical FHRP and VTEP-down detectors.

FILES TOUCHED (all under the worktree root): cisco_toolkit/parse.py (parse_storm_control + _STORM_TYPE_WORD), cisco_toolkit/build.py (build_storm_control + import), cisco_toolkit/design_advisor.py (signal block + _d_storm_control_action + _DETECTORS entry), COLLECT_PARSE_V3_23_0.py (show storm-control in both base lists, build import, accumulator, loop accumulate, snap publish), tests/synthetic_fixtures.py (access1 fixture), tests/test_parsers.py (2 parser tests), tests/test_design_blueprint.py (1 detector test), tests/golden/snapshot.json (regenerated).

## sources
['https://www.cisco.com/c/en/us/td/docs/switches/lan/c9000/lyr2-fwd/flowcontrol-stormcontrol/flow-control-and-storm-control-configuration-guide/m-storm-control.html', 'https://www.cisco.com/c/en/us/td/docs/dcn/nx-os/nexus9000/104x/configuration/security/cisco-nexus-9000-series-nx-os-security-configuration-guide-release-104x/m_configuring_traffic_storm_control.html', 'https://www.cisco.com/c/dam/en/us/td/docs/ios-xml/ios/sec_data_acl/configuration/xe-3s/asr903/sec-storm-control-xe-3s-asr903-book.html', 'https://www.cellstream.com/2014/10/07/switch-storm-control-ciscoios/', 'https://packetlife.net/blog/2008/nov/27/storm-control/']

## parser_code
```python
_STORM_TYPE_WORD = {"B": "broadcast", "M": "multicast", "U": "unicast",
                    "BCAST": "broadcast", "MCAST": "multicast", "UCAST": "unicast",
                    "BROADCAST": "broadcast", "MULTICAST": "multicast", "UNICAST": "unicast"}


def parse_storm_control(output: str) -> list:
    """'show storm-control' -> [{interface, traffic, filter_state, upper, lower, current, action, configured}].
    Traffic-storm-control caps ingress broadcast/multicast/unicast at a threshold; the per-traffic ACTION
    decides what happens when the storm crosses the rising threshold -- 'Shutdown' err-disables the port,
    'Trap' raises an SNMP notification, and the IOS/IOS-XE default 'None' SILENTLY drops the excess with no
    operator visibility (NX-OS enables the trap action by default). The senior gap (-> _d_storm_control_action)
    is a configured rule whose action is None: it protects the fabric from a broadcast storm but never tells
    anyone it fired, so a storming access port is invisible until users complain.

    Tolerant of both the modern column form 'Interface | Filter State | Upper | Lower | Current | Action |
    Type(B/M/U)' AND the older 'Interface | Type(Bcast) | Filter State | Upper | Lower | Current' form (which
    carries NO action column -> action ''). `configured` is True when a real Upper threshold is present (the
    rule exists), so a port simply ABSENT from the output -- i.e. no storm-control at all -- never appears and
    is never flagged. [] on empty / non-storm-control input; never raises."""
    out = []
    for raw in (output or "").splitlines():
        s = raw.strip()
        if not s or s.lower().startswith(("key:", "interface", "---")):
            continue
        toks = s.split()
        if len(toks) < 2 or not is_valid_iface(toks[0]):
            continue
        ifname = normalize_ifname(toks[0])
        rest = toks[1:]
        # Trailing single-letter traffic class (modern form): '... Action B|M|U'
        traffic = ""
        if rest and rest[-1].upper() in _STORM_TYPE_WORD and len(rest[-1]) == 1:
            traffic = _STORM_TYPE_WORD[rest.pop().upper()]
        # Leading traffic class (older form): 'Iface Bcast Blocking ...'
        if not traffic and rest and rest[0].upper() in _STORM_TYPE_WORD:
            traffic = _STORM_TYPE_WORD[rest.pop(0).upper()]
        # Filter State is one or two words ('Forwarding' / 'Link Down' / 'Below rising'); the action (modern
        # form only) is the last remaining token when it is one of the known keywords.
        action = ""
        if rest and rest[-1].lower() in ("none", "trap", "shutdown"):
            action = rest.pop().capitalize()
        # Numeric-ish run = Upper, Lower, Current (each may itself be '50.00%' or '2g bps' / '100 pps').
        nums = [t for t in rest if re.match(r"^[\d.]+[a-z%]*$", t, re.IGNORECASE)]
        upper = nums[0] if len(nums) >= 1 else ""
        lower = nums[1] if len(nums) >= 2 else ""
        current = nums[2] if len(nums) >= 3 else (nums[-1] if nums else "")
        # Filter state = the leading non-numeric words before the first threshold.
        state_words = []
        for t in rest:
            if re.match(r"^[\d.]+[a-z%]*$", t, re.IGNORECASE):
                break
            state_words.append(t)
        out.append({"interface": ifname, "traffic": traffic,
                    "filter_state": " ".join(state_words), "upper": upper, "lower": lower,
                    "current": current, "action": action, "configured": bool(upper)})
    return out
```

## build_code
```python
def build_storm_control(cmd_to_file: Dict[str, str]) -> list:
    """Per-interface traffic-storm-control state for THIS device from 'show storm-control' (parse_storm_control):
    [{interface, traffic, filter_state, upper, lower, current, action, configured}]. [] when the device runs no
    storm-control (the command is absent or empty). The senior gap (-> _d_storm_control_action) is a CONFIGURED
    rule whose action is None -- it drops a broadcast/multicast storm silently with no trap and no err-disable,
    so a storming edge port stays invisible until users complain. Fail-soft via _safe_parse."""
    return _safe_parse(parse_storm_control, _load_cmd_output(cmd_to_file, "show storm-control")) or []
```

## signal_code
```python
    # STORM-CONTROL ACTION (snap['storm_control'] from build_storm_control / show storm-control): an edge port
    # with a CONFIGURED storm-control rule whose action is 'None' drops a broadcast/multicast storm SILENTLY --
    # no SNMP trap, no err-disable -- so the operator never learns the port stormed. Coverage-honest: a port
    # with NO storm-control at all never appears here (configured=False is skipped), so this is the toothless-
    # rule STATE, never blanket absence. Empty when the storm-control axis is absent.
    sig["storm_noaction"] = []
    _sc = snap.get("storm_control")
    for _h, _rows in (_sc.items() if isinstance(_sc, dict) else []):
        for _r in _as_list(_rows):
            if _r.get("configured") and str(_r.get("action", "")).strip().lower() == "none":
                sig["storm_noaction"].append(f"{_h} {_r.get('interface', '?')} "
                                             f"{_r.get('traffic', 'storm')}")
    sig["storm_noaction_devices"] = sorted({x.split()[0] for x in sig["storm_noaction"]})[:12]
```

## detector_code
```python
def _d_storm_control_action(snap, sig):
    """Storm-control configured but TOOTHLESS: an edge port with a storm-control threshold whose action is
    'None' (snap['storm_control'][].action == None from show storm-control). It still drops a broadcast /
    multicast storm, but raises NO SNMP trap and does NOT err-disable -- the storm is invisible to operations
    until users complain, and the offending host is never quarantined. Coverage-honest: fires ONLY on a
    CONFIGURED rule (a port with no storm-control at all is silent -- that is a config-absence design choice,
    not a broken state) and stays silent when the storm-control axis was not collected. Distinct from blanket
    'enable storm-control everywhere' advice -- this is a present-but-ineffective control the operator already
    intended to act."""
    bad = sig.get("storm_noaction") or []
    if not bad:
        return None
    return _decision(
        "storm-control-action-on-edge",
        f"{len(bad)} storm-control rule(s) are configured with action 'None' ({', '.join(bad[:8])}). The "
        f"control caps the storm but sends no trap and does not err-disable the port, so a broadcast/multicast "
        f"storm is dropped SILENTLY -- operations never learns it fired and the storming host is never "
        f"quarantined. Add 'storm-control action trap' (visibility) and/or 'storm-control action shutdown' "
        f"(containment) on the access edge so a storm is observable and self-isolating.",
        len(bad), ["availability", "operations"],
        ["storm_control[].action (parse_storm_control / show storm-control)", "storm_control[].configured"],
        priority="Medium",
        driver="Broadcast-storm containment must be OBSERVABLE: a storm-control rule that only drops (action "
               "None) hides the event from operations and leaves the storming host attached; trap/shutdown make "
               "it visible and self-isolating.",
        devices=sig.get("storm_noaction_devices") or [])
```

## fixture_block
```python
    # Storm-control action audit (universality): Gi0/2 has a configured broadcast/multicast threshold but the
    # action is 'None' -- a storm is dropped SILENTLY (no trap, no err-disable) so operations never learns it
    # fired -> _d_storm_control_action fires. Gi0/3 is correctly actioned (Shutdown/Trap) and Gi0/1 has no
    # storm-control at all (absent from the table) -- both must stay silent (coverage-honest: configured rule
    # with a real action, and config-absence, are NOT flagged).
    "show storm-control": """\
Key: U - Unicast, B - Broadcast, M - Multicast
Interface Filter State   Upper       Lower       Current    Action    Type
--------- ------------- ----------- ----------- ---------- --------- ----
Gi0/2     Forwarding    5.00%       5.00%       0.12%      None      B
Gi0/2     Forwarding    5.00%       5.00%       0.00%      None      M
Gi0/3     Forwarding    2.00%       2.00%       0.05%      Shutdown  B
Gi0/3     Forwarding    2.00%       2.00%       0.00%      Trap      M
""",
```

## test_code
```python
# --- in tests/test_parsers.py (after test_parse_nve_vni_states) ---

def test_parse_storm_control_actions(cp):
    """Universality (storm-control action audit): parse_storm_control reads 'show storm-control' so the senior
    gap -- a CONFIGURED storm-control rule whose action is 'None' (drops a storm silently, no trap / no
    err-disable) -- is detectable, while a properly-actioned rule (Trap/Shutdown) is distinguishable. Handles
    the modern 'Action + Type(B/M/U)' column form."""
    out = (
        "Key: U - Unicast, B - Broadcast, M - Multicast\n"
        "Interface Filter State   Upper       Lower       Current    Action    Type\n"
        "--------- ------------- ----------- ----------- ---------- --------- ----\n"
        "Gi0/2     Forwarding    5.00%       5.00%       0.12%      None      B\n"
        "Gi0/3     Forwarding    2.00%       2.00%       0.05%      Shutdown  B\n"
        "Gi0/4     Link Down     50k bps     40k bps     0 bps      Trap      M\n")
    r = parse.parse_storm_control(out)
    assert len(r) == 3
    g2 = r[0]
    assert g2 == {"interface": "Gi0/2", "traffic": "broadcast", "filter_state": "Forwarding",
                  "upper": "5.00%", "lower": "5.00%", "current": "0.12%", "action": "None", "configured": True}
    assert r[1]["action"] == "Shutdown" and r[1]["traffic"] == "broadcast"
    # two-word filter state + 'bps'-suffixed thresholds are tolerated
    assert r[2]["filter_state"] == "Link Down" and r[2]["action"] == "Trap" and r[2]["upper"] == "50k"
    assert parse.parse_storm_control("") == []


def test_parse_storm_control_legacy_leading_type_no_action(cp):
    """Tolerant of the older form 'Interface | Type(Bcast) | Filter State | Upper | Lower | Current' which
    carries NO action column -> action '' (so the detector, which fires only on action == 'None', correctly
    stays silent on this form rather than crying wolf)."""
    out = (
        "Interface Type    Filter State    Upper       Lower       Current\n"
        "--------- ------  -------------   ----------- ----------- ----------\n"
        "Gi0/0/1   Bcast   Blocking        50k bps     40k bps     362.25k bps\n"
        "Gi0/0/1   Ucast   Forwarding      1.00%       0.50%       1.28%\n")
    r = parse.parse_storm_control(out)
    assert len(r) == 2
    assert r[0]["traffic"] == "broadcast" and r[0]["filter_state"] == "Blocking"
    assert r[0]["upper"] == "50k" and r[0]["action"] == "" and r[0]["configured"] is True
    assert r[1]["traffic"] == "unicast" and r[1]["action"] == ""


# --- in tests/test_design_blueprint.py (after test_d_fhrp_resilience...) ---

def test_d_storm_control_action_flags_configured_noaction_only():
    """Universality (storm-control): a CONFIGURED storm-control rule whose action is 'None' (drops a storm
    silently -- no trap, no err-disable) fires _d_storm_control_action. Refutation / coverage-honesty: a rule
    with a real action (Shutdown/Trap), an UN-configured row (no threshold), and an absent storm_control axis
    are all silent -- so this is the toothless-rule STATE, never blanket absence (no cry-wolf)."""
    import cisco_toolkit.design_advisor as da
    snap = {"storm_control": {"access1": [
        {"interface": "Gi0/2", "traffic": "broadcast", "action": "None", "configured": True},   # toothless -> fire
        {"interface": "Gi0/2", "traffic": "multicast", "action": "None", "configured": True},    # toothless -> fire
        {"interface": "Gi0/3", "traffic": "broadcast", "action": "Shutdown", "configured": True},  # actioned -> silent
        {"interface": "Gi0/4", "traffic": "broadcast", "action": "None", "configured": False},   # not configured -> silent
    ]}}
    sig = da._signals(snap)
    assert sig["storm_noaction"] == ["access1 Gi0/2 broadcast", "access1 Gi0/2 multicast"]
    assert sig["storm_noaction_devices"] == ["access1"]
    dec = da._d_storm_control_action(snap, sig)
    assert dec is not None and "action 'None'" in str(dec) and "Gi0/2" in str(dec)
    assert dec["priority"] == "Medium"
    # all actioned -> silent
    ok = {"storm_control": {"access1": [{"interface": "Gi0/2", "traffic": "broadcast", "action": "Trap", "configured": True}]}}
    assert da._d_storm_control_action(ok, da._signals(ok)) is None
    # absent axis -> silent (coverage-honest)
    assert da._d_storm_control_action({}, da._signals({})) is None
```
