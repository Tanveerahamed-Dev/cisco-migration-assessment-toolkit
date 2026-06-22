## buildable
needs-collection

## unit_tests_green
True

## firing_condition
Per egress QoS class on 'show policy-map interface': total drops = queue total-drops (drop_pkts) + policer exceeded/violated drops (police_drop_pkts). A PRIORITY/LLQ class fires when drops >= 100 (real-time traffic must never be congestion-dropped). A non-priority class fires only when drops >= 1000 AND drops/(drops+output_pkts) >= 1% (so normal tail-drop on a busy data class does NOT fire). Detector emits when >=1 class qualifies; priority => High, data-only => Medium. Only the OUTPUT (egress) direction is scored. Silent when the axis is absent or all classes clean.

## collection_command
show policy-map interface

## snapshot_axis
qos_runtime

## fixture_device
core1

## notes
RESEARCH GROUNDING (primary Cisco sources + Cisco's own genieparser golden corpus):
- IOS/IOS-XE egress class layout (verbatim from genieparser issue #158 + Cisco LLQ guide): 'Class-map: NAME (match-any)' then 'Queueing' then '(queue depth/total drops/no-buffer drops) D/T/N' then '(pkts output/bytes output) P/B'. Priority classes print 'priority level N' and on modern IOS-XE use the SAME drops line (confirmed example: '(queue depth/total drops/no-buffer drops) 49476/44577300/0' on a priority class). Older strict-priority form prints '(total drops/bytes drops) T/B' — handled by _PM_PRIDROPS_RE.
- Policer drops (Cisco class-based policing guide + 10107-showpolicy): 'police: ...' then 'exceeded N packets, M bytes; action: drop' / 'violated N packets...'. Counted into police_drop_pkts (only inside a police block, so 'conformed ... transmit' is never mis-counted).
- NX-OS queuing form (Nexus 7000/9000 QoS guide): 'Class-map (queuing): NAME' with 'queue dropped pkts: N' / 'queue dropped bytes: N' / 'queue transmit pkts: N'. Verified parser against all three real formats + the input-vs-output direction split + empty/'% Incomplete command' (all -> []).
- genieparser regexes used as the authoritative reference for field labels (p18 queue-drops, p19 pkts-output, p9/p10 conformed/exceeded).

WHY THIS IS A CLEAN, NON-CRY-WOLF FINDING (the senior judgment): a QoS queue tail-dropping a few packets on a momentary burst is NORMAL and is literally the policy doing its job (it sheds the right traffic). Firing on ANY drop would be cry-wolf. The senior failure is (a) a PRIORITY/LLQ class being congestion-dropped at all (real-time traffic — RFC 4594 / Cisco LLQ — must never be congestion-dropped; if it is, the priority bandwidth/policer is undersized or the class is misclassified), or (b) a data class shedding a MATERIAL share of its own traffic (>=1% ratio AND >=1000 absolute). The drop RATIO guard is the key cry-wolf defense: a class that forwards 3,000,000 pkts and drops 250 (0.008%) stays silent; one that drops 44M of 47M fires. Proven by two dedicated refutation cases in the detector test (tiny tail-drop; floor-met-but-below-ratio) — both silent.

BUILDABLE = needs-collection: 'show policy-map interface' is NOT in COMMANDS_NXOS/COMMANDS_IOS today (grep-confirmed). The same command string works on both platforms (lists all interfaces with an attached policy). Adding it is required to populate snap['qos_runtime']; this is the ONLY new device read. Everything else (parse/build/detector/signals/tests) is wired exactly like the build_overlay reference. The orchestrator must: (1) add the command to both COMMANDS lists, (2) import build_qos_runtime + init all_qos_runtime={} + accumulate per-device + snap_dict['qos_runtime']=all_qos_runtime, (3) add parse_policymap_drops to build.py's parse import. Because the synthetic golden pipeline does not yet publish qos_runtime, the detector is silent there and the frozen golden is unaffected (verified: test_pipeline_golden green); once wired, the core1 fixture makes it fire HIGH (VOICE 1,840,521 drops @ 6.9%/LLQ + BULK-DATA 512,000 @ 5.8%; class-default clean) — confirmed by directly running build path on the fixture.

PATTERN FIDELITY: principle id 'qos-runtime-egress-queue-drops' is intentionally NOT a design_kb DOCTRINE entry — byte-for-byte the same choice as the two reference detectors I was told to mirror (_d_fhrp_resilience -> 'fhrp-resilience-tracking-and-preempt' and _d_nve_peer_health -> 'vxlan-nve-peer-down', both verified MISSING from DOCTRINE via design_kb.by_id). _decision() degrades gracefully (title=pid, empty citation/action). Consequently the axis is deliberately NOT seeded in tests/_maximal_snap() (matching how overlay/fhrp_detail are omitted there) so the 'emitted <= _KB_IDS' coverage-honesty lock continues to hold; the detector is exercised by its own fire/refute test instead. If the orchestrator instead prefers a KB-backed principle, it must add a DOCTRINE entry with engine_actionable:True AND seed qos_runtime in _maximal_snap — but that diverges from the reference slices and risks the engine_actionable emit-invariant, so I followed the reference.

VALIDATION: ran the two parser tests + the detector test green in isolation; ran the full design_blueprint + parsers modules green; ran the FULL suite = 576 passed in 108s. All 6 modified files py_compile clean. Diff = 6 files / +369 / -1.

## sources
['https://www.cisco.com/c/en/us/support/docs/quality-of-service-qos/qos-congestion-avoidance/10107-showpolicy.html', 'https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/qos_conmgt/configuration/xe-17/qos-conmgt-xe-17-book/qos-conmgt-llq-pps.html', 'https://www.cisco.com/c/en/us/support/docs/switches/catalyst-9300-switch/216236-troubleshoot-output-drops-on-catalyst-90.html', 'https://www.cisco.com/c/en/us/td/docs/switches/datacenter/nexus7000/sw/qos/config/cisco_nexus7000_qos_config_guide_8x/monitoring_qos_statistics.html', 'https://github.com/CiscoTestAutomation/genieparser/issues/158', 'https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/qos_plcshp/configuration/xe-3s/qos-plcshp-xe-3s-book/qos-plcshp-class-plc.html']

## parser_code
```python
def parse_policymap_drops(output: str) -> list:
    """'show policy-map interface' RUNTIME stats -> one record per EGRESS class/queue that has data:
    [{interface, policy, class, priority(bool), drop_pkts, drop_bytes, output_pkts, police_drop_pkts,
    police_drop_bytes}]. This is the QoS-RUNTIME complement to parse_qos_config (which only proves a
    policy EXISTS): it proves whether the configured QoS is actually PROTECTING traffic -- a class with
    significant egress drops means the queue/policer is shedding the very traffic the intent classified.

    Coverage scope: only the OUTPUT (egress) direction is recorded (the input/queuing-in direction is
    rate/marking, not the protect-at-runtime signal). Both dialects are parsed:
      * IOS / IOS-XE: '(queue depth/total drops/no-buffer drops) D/T/N' (+ strict-priority
        '(total drops/bytes drops) T/B') and '(pkts output/bytes output) P/B'; a 'police: / exceeded /
        violated' block contributes policer drops; priority detected from 'priority [level N]'.
      * NX-OS: 'Class-map (queuing): ...' with 'queue dropped pkts/bytes:' and 'queue transmit pkts:'.
    Tolerant: [] on empty / non-policy-map input; never raises. Drop/output counters default to 0 so a
    class that is present but idle reads as zero-drop, not missing."""
    out: list = []
    iface = ""
    egress = False                     # inside an OUTPUT service-policy (the only direction we score)
    policy = ""
    cur: Optional[dict] = None         # the class record currently being filled
    in_police = False                  # inside this class's 'police:' block (exceeded/violated => drops)

    def _flush():
        if cur is not None and egress and iface:
            out.append(cur)

    for raw in (output or "").splitlines():
        s = raw.strip()
        if not s:
            continue
        mi = _PM_IFACE_RE.match(s)
        if mi and not s.lower().startswith(("class-map", "service-policy", "police", "queueing",
                                            "queue", "match", "priority", "bandwidth", "exceeded",
                                            "conformed", "violated")):
            _flush(); cur = None; in_police = False
            iface = normalize_ifname(mi.group(1)); egress = False; policy = ""
            continue
        msp = _PM_SVCPOL_RE.match(s)
        if msp:
            _flush(); cur = None; in_police = False
            egress = msp.group("dir").lower() == "output"
            policy = msp.group("name")
            continue
        mnc = _PM_NX_CLASS_RE.match(s)                   # NX-OS queuing class (more specific -> test first)
        mc = mnc or _PM_CLASS_RE.match(s)
        if mc:
            _flush(); in_police = False
            cur = {"interface": iface, "policy": policy, "class": mc.group("name"),
                   "priority": False, "drop_pkts": 0, "drop_bytes": 0, "output_pkts": 0,
                   "police_drop_pkts": 0, "police_drop_bytes": 0}
            continue
        if cur is None:
            continue
        if _PM_PRIORITY_RE.match(s):
            cur["priority"] = True
            # NX-OS prints 'priority' as a class attribute; IOS prints 'priority level N' -- both => LLQ
            continue
        if _PM_POLICE_RE.match(s):
            in_police = True
            continue
        m = _PM_QDROPS_RE.search(s)
        if m:
            cur["drop_pkts"] = int(m.group(2)); continue
        m = _PM_PRIDROPS_RE.search(s)
        if m:
            cur["priority"] = True
            cur["drop_pkts"] = int(m.group(1)); cur["drop_bytes"] = int(m.group(2)); continue
        m = _PM_OUTPUT_RE.search(s)
        if m:
            cur["output_pkts"] = int(m.group(1)); continue
        if in_police:
            m = _PM_EXCEEDED_RE.match(s)
            if m:
                cur["police_drop_pkts"] += int(m.group(1)); cur["police_drop_bytes"] += int(m.group(2)); continue
            m = _PM_VIOLATED_RE.match(s)
            if m:
                cur["police_drop_pkts"] += int(m.group(1)); cur["police_drop_bytes"] += int(m.group(2)); continue
        # NX-OS queuing counters
        m = _PM_NX_DROP_RE.match(s)
        if m:
            cur["drop_pkts"] = int(m.group(1)); continue
        m = _PM_NX_DROPB_RE.match(s)
        if m:
            cur["drop_bytes"] = int(m.group(1)); continue
        m = _PM_NX_TX_RE.match(s)
        if m:
            cur["output_pkts"] = int(m.group(1)); continue
    _flush()
    return out

# ---- module-level regexes, place ABOVE parse_policymap_drops in parse.py ----
# 'show policy-map interface' header / statistics lines, validated against Cisco's own genieparser
# golden output + the IOS-XE / NX-OS QoS configuration guides. The drops line is identical for
# bandwidth and priority (LLQ) classes on modern IOS-XE; the priority/policer context is tracked
# separately by the line-driven state machine in parse_policymap_drops.
_PM_IFACE_RE   = re.compile(r"^([A-Za-z][\w./-]*\d[\w./-]*)\s*$")                 # a bare interface token line
_PM_SVCPOL_RE  = re.compile(r"^Service-policy\s+(?:\((?P<kind>[^)]*)\)\s+)?(?P<dir>input|output)\s*:\s*(?P<name>\S+)",
                            re.IGNORECASE)
_PM_CLASS_RE   = re.compile(r"^Class-map(?:\s+\((?P<kind>[^)]*)\))?\s*:\s*(?P<name>\S+)", re.IGNORECASE)
_PM_QDROPS_RE  = re.compile(r"\(queue depth/total drops/no-buffer drops\)\s+(\d+)/(\d+)/(\d+)", re.IGNORECASE)
_PM_PRIDROPS_RE= re.compile(r"\(total drops/bytes drops\)\s+(\d+)/(\d+)", re.IGNORECASE)        # strict-priority form
_PM_OUTPUT_RE  = re.compile(r"\(pkts output/bytes output\)\s+(\d+)/(\d+)", re.IGNORECASE)
_PM_PRIORITY_RE= re.compile(r"^(?:priority(?:\s+level\s+\d+)?\b|Strict Priority|Priority:)", re.IGNORECASE)
_PM_POLICE_RE  = re.compile(r"^police\b", re.IGNORECASE)
_PM_EXCEEDED_RE= re.compile(r"^exceeded\s+(\d+)\s+packets,\s+(\d+)\s+bytes", re.IGNORECASE)
_PM_VIOLATED_RE= re.compile(r"^violated\s+(\d+)\s+packets,\s+(\d+)\s+bytes", re.IGNORECASE)
# NX-OS queuing form
_PM_NX_CLASS_RE= re.compile(r"^Class-map\s+\(queuing\)\s*:\s*(?P<name>\S+)", re.IGNORECASE)
_PM_NX_DROP_RE = re.compile(r"^queue\s+dropped\s+pkts\s*:\s*(\d+)", re.IGNORECASE)
_PM_NX_DROPB_RE= re.compile(r"^queue\s+dropped\s+bytes\s*:\s*(\d+)", re.IGNORECASE)
_PM_NX_TX_RE   = re.compile(r"^queue\s+transmit\s+pkts\s*:\s*(\d+)", re.IGNORECASE)
```

## build_code
```python
def build_qos_runtime(cmd_to_file: Dict[str, str]) -> list:
    """QoS RUNTIME health for THIS device from 'show policy-map interface' (parse_policymap_drops):
    [{interface, policy, class, priority, drop_pkts, drop_bytes, output_pkts, police_drop_pkts,
    police_drop_bytes}] -- one row per EGRESS class/queue. [] when no service-policy is attached (or the
    command was not collected). This is the runtime complement to build/parse_qos_config (which only
    proves a policy EXISTS): a class with significant egress drops means the configured QoS is shedding
    the very traffic its intent classified -- the policy is not protecting traffic at runtime. Fail-soft
    via _safe_parse."""
    return _safe_parse(parse_policymap_drops,
                       _load_cmd_output(cmd_to_file, "show policy-map interface")) or []

# Add to build.py's `from cisco_toolkit.parse import (...)` block:
#     parse_policymap_drops,                                            # QoS runtime: egress queue/policer drops
```

## signal_code
```python
# Module constants (place near _LARGE_L2_VLANS at top of design_advisor.py):
_QOS_DROP_FLOOR = 1000           # min egress drops on a non-priority class before it can fire
_QOS_DROP_RATIO = 0.01           # ... AND drops must be >=1% of (drops + output) on that class
_QOS_PRIORITY_DROP_FLOOR = 100   # any priority/LLQ class above this many drops fires (stricter bar)

# _signals block (place inside _signals(snap), after the voice_noqos signals):
    # QoS RUNTIME (snap['qos_runtime'] from build_qos_runtime / 'show policy-map interface'): an EGRESS
    # class taking SIGNIFICANT drops means the configured QoS is shedding the traffic its intent
    # classified -- the policy is not protecting traffic at runtime. CRY-WOLF GUARD: tail-dropping a few
    # packets on a busy data class is NORMAL (that is QoS doing its job), so a non-priority class fires
    # ONLY when drops clear an absolute floor AND are >=1% of (drops+output). A PRIORITY/LLQ class is
    # held to a stricter bar: real-time traffic must never be congestion-dropped, so any drops above a
    # small floor count (RFC 4594 / Cisco LLQ). Policer 'exceeded/violated' drops count the same as a
    # queue drop. Coverage-honest: empty when the axis is absent (command not collected) or all classes
    # are clean. _QOS_DROP_FLOOR/_QOS_DROP_RATIO are module constants so the threshold is one source.
    sig["qos_drop_classes"] = []
    _qr = snap.get("qos_runtime")
    for _h, _rows in (_qr.items() if isinstance(_qr, dict) else []):
        for _c in _as_list(_rows):
            _drop = _as_int(_c.get("drop_pkts")) + _as_int(_c.get("police_drop_pkts"))
            if _drop <= 0:
                continue
            _outp = _as_int(_c.get("output_pkts"))
            _denom = _drop + _outp
            _ratio = (_drop / _denom) if _denom > 0 else 1.0
            _is_pri = bool(_c.get("priority"))
            _fires = (_drop >= _QOS_PRIORITY_DROP_FLOOR) if _is_pri else \
                     (_drop >= _QOS_DROP_FLOOR and _ratio >= _QOS_DROP_RATIO)
            if _fires:
                sig["qos_drop_classes"].append({
                    "host": _h, "interface": _c.get("interface", "?"), "policy": _c.get("policy", ""),
                    "class": _c.get("class", "?"), "priority": _is_pri, "drops": _drop,
                    "ratio": round(_ratio, 4)})
    sig["qos_drop_priority"] = sum(1 for x in sig["qos_drop_classes"] if x["priority"])
    sig["qos_drop_hosts"] = sorted({x["host"] for x in sig["qos_drop_classes"]})
```

## detector_code
```python
def _d_qos_runtime_drops(snap, sig):
    """QoS RUNTIME failure (the complement to _d_qos/_d_voice_qos, which only check a policy EXISTS): an
    EGRESS class/queue is actually SHEDDING traffic at runtime (snap['qos_runtime'] from
    parse_policymap_drops / 'show policy-map interface'). The configured intent is not protecting traffic.
    Coverage-honest + NO cry-wolf: a busy data class tail-dropping a few packets is normal and stays
    silent (it must clear an absolute floor AND a >=1% drop ratio); a PRIORITY/LLQ class dropping at all
    above a small floor fires HIGH (real-time traffic must never be congestion-dropped -- the priority
    bandwidth/policer is undersized or the class is misclassified). Silent when the axis is absent."""
    classes = sig.get("qos_drop_classes") or []
    if not classes:
        return None
    npri = sig.get("qos_drop_priority", 0)
    examples = ", ".join(
        f"{c['host']} {c['interface']} class {c['class']} "
        f"{c['drops']:,} drops ({c['ratio']*100:.1f}%{'/LLQ' if c['priority'] else ''})"
        for c in sorted(classes, key=lambda c: (not c["priority"], -c["drops"]))[:6])
    pri_clause = (f"{npri} of these are PRIORITY/LLQ class(es) -- real-time traffic is being "
                  f"congestion-dropped, which a priority queue must never do. " if npri else "")
    return _decision(
        "qos-runtime-egress-queue-drops",
        f"{len(classes)} egress QoS class/queue(s) are dropping traffic at runtime ({examples}). "
        f"{pri_clause}A class shedding a material share of its traffic means the configured QoS is not "
        f"protecting the traffic its intent classified -- the queue/policer is undersized, the class is "
        f"misclassified, or the link is oversubscribed. Right-size the priority bandwidth / queue-limit "
        f"(and the policer) for the real load, and re-verify the drop counters are flat before cutover.",
        len(classes), ["availability", "convergence"],
        ["qos_runtime[].drop_pkts (parse_policymap_drops / show policy-map interface)",
         "qos_runtime[].police_drop_pkts", "qos_runtime[].priority"],
        priority="High" if npri else "Medium",
        driver="Application performance at runtime: a QoS class dropping its own traffic (especially the "
               "LLQ) proves the policy is mis-sized -- the intent exists on paper but fails under load.",
        devices=sig.get("qos_drop_hosts") or [])

# Register in _DETECTORS (next to _d_voice_qos):
#   _d_timesync, _d_voice_qos, _d_qos_runtime_drops, _d_phased, _d_l2_faildomain,
```

## fixture_block
```python
# Add to core1 (IOS) in tests/synthetic_fixtures.py (after the 'show standby all' block).
# ALSO add "show policy-map interface" to BOTH COMMANDS_NXOS and COMMANDS_IOS in COLLECT_PARSE_V3_23_0.py
# so the fixture is collected and snap['qos_runtime'] is published (init all_qos_runtime / accumulate in
# the per-device loop / snap_dict["qos_runtime"] = all_qos_runtime), mirroring build_overlay's wiring.
    # QoS RUNTIME (universality): core1 has a configured egress policy whose PRIORITY (LLQ) class is
    # congestion-dropping real-time traffic, and a data class shedding >1% of its load -> _d_qos_runtime_drops
    # fires. The class-default queue is clean (no cry-wolf). This proves the engine assesses whether the
    # QoS INTENT is actually protecting traffic at runtime, not merely that a policy exists.
    "show policy-map interface": """\
GigabitEthernet1/0/24

  Service-policy output: WAN-EDGE-OUT

    Class-map: VOICE (match-any)
      24817400 packets, 4765747200 bytes
      Match: dscp ef (46)
      Queueing
      priority level 1
      queue limit 512 packets
      (queue depth/total drops/no-buffer drops) 511/1840521/0
      (pkts output/bytes output) 24817400/4765747200

    Class-map: BULK-DATA (match-any)
      8400000 packets, 6048000000 bytes
      Match: dscp af11 (10)
      Queueing
      queue limit 2000 packets
      (queue depth/total drops/no-buffer drops) 1998/512000/0
      (pkts output/bytes output) 8400000/6048000000
      bandwidth remaining 30%

    Class-map: class-default (match-any)
      150000 packets, 18000000 bytes
      Queueing
      queue limit 416 packets
      (queue depth/total drops/no-buffer drops) 0/0/0
      (pkts output/bytes output) 150000/18000000
""",
```

## test_code
```python
# ---- parser tests (tests/test_parsers.py; `import textwrap`, `from cisco_toolkit import parse` already present) ----
def test_parse_policymap_drops_iosxe_priority_data_and_policer(cp):
    """QoS RUNTIME: parse_policymap_drops reads 'show policy-map interface' so a class actually SHEDDING
    traffic at runtime is detectable (the complement to parse_qos_config, which only proves a policy
    exists). Covers the IOS-XE dialect: a priority (LLQ) class with queue drops, a bandwidth class, a
    policer 'exceeded' block, and a clean class -- and proves only the EGRESS direction is scored."""
    out = textwrap.dedent("""\
        GigabitEthernet0/0/0

          Service-policy input: MARK-IN

            Class-map: SCAVENGER-IN (match-any)
              Queueing
              (queue depth/total drops/no-buffer drops) 0/999999/0
              (pkts output/bytes output) 1/1

          Service-policy output: WAN-EDGE-OUT

            Class-map: VOICE (match-any)
              2348138 packets, 1202246656 bytes
              Match: dscp ef (46)
              Queueing
              priority level 1
              queue limit 512 packets
              (queue depth/total drops/no-buffer drops) 49476/44577300/0
              (pkts output/bytes output) 2348138/1202246656

            Class-map: BULK (match-any)
              3000453 packets, 262033259 bytes
              Match: dscp af11 (10)
              Queueing
              queue limit 525000 bytes
              (queue depth/total drops/no-buffer drops) 0/250/0
              (pkts output/bytes output) 3000454/262033337
              bandwidth remaining 30%

            Class-map: SCAVENGER (match-any)
              9000 packets, 8000 bytes
              police: cir 1000000 bps, bc 31250 bytes
                conformed 5000 packets, 4000 bytes; action: transmit
                exceeded 4000 packets, 3500 bytes; action: drop
                violated 0 packets, 0 bytes; action: drop

            Class-map: class-default (match-any)
              100 packets, 9000 bytes
              Queueing
              queue limit 416 packets
              (queue depth/total drops/no-buffer drops) 0/0/0
              (pkts output/bytes output) 100/9000
    """)
    r = parse.parse_policymap_drops(out)
    # only the FOUR egress classes are recorded; the input-direction class (999999 drops) is ignored
    assert [c["class"] for c in r] == ["VOICE", "BULK", "SCAVENGER", "class-default"]
    assert all(c["interface"] == "Gi0/0/0" and c["policy"] == "WAN-EDGE-OUT" for c in r)
    voice = r[0]
    assert voice["priority"] is True and voice["drop_pkts"] == 44577300 and voice["output_pkts"] == 2348138
    bulk = r[1]
    assert bulk["priority"] is False and bulk["drop_pkts"] == 250 and bulk["output_pkts"] == 3000454
    scav = r[2]
    assert scav["police_drop_pkts"] == 4000 and scav["police_drop_bytes"] == 3500 and scav["drop_pkts"] == 0
    assert r[3]["drop_pkts"] == 0 and r[3]["output_pkts"] == 100         # class-default clean
    assert parse.parse_policymap_drops("") == [] and parse.parse_policymap_drops("% Incomplete command") == []


def test_parse_policymap_drops_nxos_queuing(cp):
    """QoS RUNTIME (NX-OS dialect): the queuing form uses 'Class-map (queuing):' with 'queue dropped
    pkts/bytes:' and 'queue transmit pkts:'. A priority class with queue drops must be captured, and a
    'Service-policy (queuing) output:' header must NOT be mistaken for an interface line."""
    out = textwrap.dedent("""\
        port-channel6
        Service-policy (queuing) output: out-q-policy

        Class-map (queuing): q1 (match-any)
        priority level 1
        queue dropped pkts: 12345
        queue dropped bytes: 678900
        queue transmit pkts: 2175032764
        queue transmit bytes: 1051188564890

        Class-map (queuing): q-default (match-any)
        bandwidth percent 49
        queue dropped pkts: 0
        queue dropped bytes: 0
        queue transmit pkts: 518903560636
    """)
    r = parse.parse_policymap_drops(out)
    assert [c["class"] for c in r] == ["q1", "q-default"]
    assert all(c["interface"] == "Po6" for c in r)                       # normalize_ifname(port-channel6)
    assert r[0]["priority"] is True and r[0]["drop_pkts"] == 12345 and r[0]["output_pkts"] == 2175032764
    assert r[1]["drop_pkts"] == 0 and r[1]["priority"] is False


# ---- detector test (tests/test_design_blueprint.py; uses the module's existing _snap helper) ----
def test_qos_runtime_drops_detector_fires_and_refutes():
    """QoS-RUNTIME health (the complement to _d_qos, which only checks a policy EXISTS): an egress class
    actually SHEDDING traffic at runtime means the configured intent is not protecting traffic. Fires on
    a priority/LLQ class dropping above the small floor (HIGH) or a data class over the absolute floor AND
    >=1% ratio (MEDIUM). CRY-WOLF GUARD: a busy data class tail-dropping a handful of packets stays
    silent. Remove the drops and the decision disappears (refutation); absent axis stays silent."""
    # priority class dropping 1.8M (95%/LLQ) + a data class shedding 9% -> fires HIGH
    bad = {"wan1": [
        {"interface": "Gi0/0/0", "policy": "WAN", "class": "VOICE", "priority": True,
         "drop_pkts": 1840521, "output_pkts": 24817400, "police_drop_pkts": 0},
        {"interface": "Gi0/0/0", "policy": "WAN", "class": "BULK", "priority": False,
         "drop_pkts": 50000, "output_pkts": 500000, "police_drop_pkts": 0},
    ]}
    by = {d["id"]: d for d in compute_design_blueprint(_snap(qos_runtime=bad))["decisions"]}
    d = by.get("qos-runtime-egress-queue-drops")
    assert d is not None and d["status"] == "recommended" and d["priority"] == "High"
    assert "VOICE" in d["evidence"]["summary"] and "LLQ" in d["evidence"]["summary"]
    assert "wan1" in d["evidence"]["devices"]
    # a data-only over-threshold class (no priority) downgrades the finding to Medium
    data_only = {"sw1": [{"interface": "Gi1", "policy": "P", "class": "D", "priority": False,
                          "drop_pkts": 20000, "output_pkts": 200000, "police_drop_pkts": 0}]}
    dm = {x["id"]: x for x in compute_design_blueprint(_snap(qos_runtime=data_only))["decisions"]}
    assert dm["qos-runtime-egress-queue-drops"]["priority"] == "Medium"
    # CRY-WOLF refutation 1: a busy data class with tiny tail-drop (0.008% < 1%) emits NOTHING
    noisy = {"sw1": [
        {"interface": "Gi1", "policy": "P", "class": "BULK", "priority": False,
         "drop_pkts": 250, "output_pkts": 3000000, "police_drop_pkts": 0},
        {"interface": "Gi1", "policy": "P", "class": "VOICE", "priority": True,
         "drop_pkts": 0, "output_pkts": 99, "police_drop_pkts": 0}]}
    assert "qos-runtime-egress-queue-drops" not in {
        d["id"] for d in compute_design_blueprint(_snap(qos_runtime=noisy))["decisions"]}
    # CRY-WOLF refutation 2: a data class just above the floor but below the ratio (0.0999%) stays silent
    edge = {"sw1": [{"interface": "Gi1", "policy": "P", "class": "D", "priority": False,
                     "drop_pkts": 1000, "output_pkts": 1000000, "police_drop_pkts": 0}]}
    assert "qos-runtime-egress-queue-drops" not in {
        d["id"] for d in compute_design_blueprint(_snap(qos_runtime=edge))["decisions"]}
    # policer 'exceeded' drops on a priority class count the same as a queue drop -> fires
    pol = {"sw1": [{"interface": "Gi1", "policy": "P", "class": "EF", "priority": True,
                    "drop_pkts": 0, "output_pkts": 50000, "police_drop_pkts": 5000}]}
    assert "qos-runtime-egress-queue-drops" in {
        d["id"] for d in compute_design_blueprint(_snap(qos_runtime=pol))["decisions"]}
    # coverage-honest: no qos_runtime axis at all -> silent
    assert "qos-runtime-egress-queue-drops" not in {
        d["id"] for d in compute_design_blueprint(_snap())["decisions"]}
```
