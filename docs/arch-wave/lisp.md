# slice: lisp -> lisp-fabric-session-down
arch: Cisco SD-Access — LISP fabric control-plane (reliable-transport session to map-server / map-resolver)
viable: True | fixture_device: core1 | snap_key: lisp
commands: show lisp session[ios]
firing: A device's `show lisp session` output contains a per-VRF block whose summary line reports `total >= 1` (LISP reliable-transport sessions to the control-plane node(s) ARE configured) but `established == 0` (not one of them reached the Up/established state). That means every map-server / map-resolver session for that VRF is down, so the fabric edge/border can neither register its EIDs nor resolve any EID-to-RLOC mapping = control-plane partition for that VRF. The detector returns one decision counting all such VRFs across all devices; otherwise None.
coverage_honesty: Three distinct silence guarantees, all keyed off the device's OWN per-VRF summary counts (never inferred, never cross-axis): (1) ABSENT — a device running no SD-Access/LISP produces no `Sessions for VRF` line, so parse_lisp_sessions returns [], build_lisp returns {}, snap['lisp'] has no entry, and the signal list is empty → None. (2) HEALTHY — any VRF with established>=1 contributes nothing. (3) BENIGN PARTIAL-DOWN (the cry-wolf trap, explicit in Cisco's Catalyst 9000 LISP-VXLAN troubleshooting guide): a Down peer is NORMAL/expected on a border that imports no routes or an edge with no endpoints connected (nothing to register on that one session) — but that node still has established>=1, so total>=1/established==0 is false and it stays silent. The detector deliberately keys off `established == 0` (the whole-VRF count), NOT off any single peer's Down state, precisely so a lone benign Down row can never fire it. Down-peer IPs are carried only as descriptive evidence inside an already-firing decision.
confidence: HIGH confidence; viable=true. Output format is cross-verified across THREE primary Cisco source classes that agree exactly: the Catalyst 9400/9500 SD-Access command references, the IOS LISP command reference (`show lisp session`/`show lisp session all`), and the official Catalyst 9000 LISP-VXLAN troubleshooting guide (doc 220361) — every example shows the same shape: a `Sessions for VRF <name>, total: N, established: M` summary line, a `Peer State Up/Down In/Out Users` header, and `IP[:port] State ...` rows with State in {Up, Down} (Listening appears only under `show lisp session all`; the parser capitalizes whatever 2nd-column word it sees, so Listening would parse as state="Listening" and never trip the count-based detector). Port 4342 is the confirmed map-server/map-resolver control-plane port.

The decisive design choice is the firing key. A naive "any peer not Up -> partition" is NOT coverage-honest: Cisco's own TS guide (220361) states a Down session is NORMAL/expected on a border importing no routes or an edge with no endpoints (nothing to register on that session). Firing on a lone Down row would cry wolf on healthy fabrics. I therefore key strictly off the device's self-reported per-VRF summary: total>=1 AND established==0 (every CP session in the VRF is down) — an unambiguous, single-command, no-cross-axis partition signal that is provably silent on absent, healthy, and benign-partial-Down inputs (the detector test exercises all three). Down-peer IPs are surfaced only as evidence inside an already-firing decision, never as the trigger.

Caveats for the integrator: (1) Parser returns a LIST of per-VRF blocks (not the LDP-style flat list) because the established-count lives on the per-VRF summary line, which is the whole point of the signal — confirm this matches your snap['lisp'] consumers. (2) `Sessions for VRF default` uses a regex `(\S+?),?\s+total:` that tolerates the comma being absent; verified against the `default`/`red`/named-VRF examples. (3) The VRF name 'red' in the fixture is illustrative of a fabric VN; swap to a real [HISTORY-REDACTED] VN name if preferred, but it has no bearing on firing. (4) Fixture peer IPs reuse the existing 10.0.255.x loopback scheme (core1 already an MPLS PE on 10.0.255.1) for consistency, though real SD-Access CP loopbacks would typically be a distinct underlay block — cosmetic only.
sources: https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9500/software/release/17-10/command_reference/b_1710_9500_cr/cisco_sd_access_commands.html | https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9400/software/release/17-3/command_reference/b_173_9400_cr/m9-173-cf-cr.html | https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/iproute_lisp/command/ip-lisp-cr-book/ip-lisp-cr-book_chapter_01011.html | https://www.cisco.com/c/en/us/support/docs/troubleshooting/220361-troubleshoot-lisp-vxlan-fabric-issues.html | https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9300/software/release/17-9/configuration_guide/lisp_vxlan/b-179-lisp-vxlan-fabric-cg/configure-edge-node-lisp-vxlan.html

## parser_sample_input
```
Sessions for VRF default, total: 2, established: 2
Peer                           State      Up/Down        In/Out    Users
172.16.1.66:4342               Up         1d04h          27/9      14
172.16.1.67:4342               Up         1d03h          19/9      14
Sessions for VRF red, total: 2, established: 0
Peer                           State      Up/Down        In/Out    Users
172.16.1.66:4342               Down       never          0/0       0
172.16.1.67:4342               Down       never          0/0       0
```

## parser_code
```
def parse_lisp_sessions(output: str) -> list:
    """'show lisp session' (IOS-XE SD-Access fabric) -> [{vrf, total, established, peers:[{peer, port, state}]}]
    per VRF block. Each fabric node opens a LISP reliable-transport (TCP) session to every control-plane node
    (map-server / map-resolver, port 4342); registrations and EID-to-RLOC resolution ride those sessions. The
    summary line 'Sessions for VRF <name>, total: N, established: M' is the device's OWN count of configured vs
    established sessions, and each peer row is 'IP[:port] State Up/Down In/Out Users' with State Up or Down.
    COVERAGE-HONESTY: a lone Down peer is NORMAL on a border that imports no routes or an edge with no endpoints
    (nothing to register on that session) -- so the down-peer list is carried as raw evidence, NOT a verdict;
    the detector keys off the summary counts (total>=1 & established==0 = every CP session down), never off a
    single Down row. [] when no LISP session output is present. Tolerant; never raises."""
    out = []
    cur = None
    for raw in (output or "").splitlines():
        s = raw.strip()
        if not s:
            continue
        m = re.match(r"^Sessions\s+for\s+VRF\s+(\S+?),?\s+total:\s*(\d+),\s*established:\s*(\d+)",
                     s, re.IGNORECASE)
        if m:
            cur = {"vrf": m.group(1), "total": int(m.group(2)),
                   "established": int(m.group(3)), "peers": []}
            out.append(cur)
            continue
        if cur is None:
            continue
        if re.match(r"^Peer\b", s, re.IGNORECASE):   # column header
            continue
        # data row: 'IP[:port]  State  Up/Down  In/Out  Users' -- State is the 2nd column.
        pm = re.match(r"^(\d+\.\d+\.\d+\.\d+)(?::(\d+))?\s+(\w+)\b", s)
        if pm:
            cur["peers"].append({"peer": pm.group(1), "port": pm.group(2) or "",
                                 "state": pm.group(3).capitalize()})
    return out
```

## build_code
```
def build_lisp(cmd_to_file: Dict[str, str]) -> dict:
    """Cisco SD-Access LISP fabric control-plane state for THIS device -> {sessions:[per-VRF blocks]}. Reads
    'show lisp session' (IOS-XE): each fabric edge/border opens a reliable-transport session to every control-
    plane node (map-server / map-resolver, port 4342) over which it registers and resolves EID-to-RLOC mappings.
    The published per-VRF summary (total / established) lets _d_lisp_fabric_session_down fire ONLY when a VRF has
    sessions configured (total>=1) yet ZERO established -- a genuine fabric control-plane partition for that node
    -- while a benign single Down peer (idle border/edge) keeps established>=1 and stays silent. {} when the
    device runs no SD-Access / LISP. Fail-soft via _safe_parse."""
    sessions = _safe_parse(parse_lisp_sessions,
                           _load_cmd_output(cmd_to_file, "show lisp session"), _default=[]) or []
    out = {}
    if sessions:
        out["sessions"] = sessions
    return out
```

## signal_code
```
    # Cisco SD-Access LISP fabric control-plane (snap['lisp'] from build_lisp). FIRING STATE: a VRF whose
    # 'show lisp session' summary reports sessions CONFIGURED (total >= 1) but ZERO established -- every reliable-
    # transport session to the map-server / map-resolver is down, so that fabric node can neither register nor
    # resolve any EID-to-RLOC (control-plane partition). COVERAGE-HONEST: a device with no LISP publishes {} and
    # never fires; a healthy node (established >= 1) and the BENIGN partial-Down case (an idle border/edge with
    # nothing to register shows a Down peer but still keeps established >= 1) both stay silent -- we key off the
    # device's OWN summary counts, never off a single Down peer row (Cisco TS guide: a lone Down session is normal).
    _lisp = _as_dict(snap.get("lisp"))
    _lisp_part = []
    for _lh, _lf in sorted(_lisp.items()):
        for _vb in _as_list(_as_dict(_lf).get("sessions")):
            _vb = _as_dict(_vb)
            if _as_int(_vb.get("total")) >= 1 and _as_int(_vb.get("established")) == 0:
                _peers = [str(_as_dict(_p).get("peer", "?")) for _p in _as_list(_vb.get("peers"))]
                _lisp_part.append(f"{_lh} VRF {_vb.get('vrf', '?')} "
                                  f"({_as_int(_vb.get('total'))} session(s), 0 established"
                                  + (f"; CP {', '.join(_peers[:4])}" if _peers else "") + ")")
    sig["lisp_fabric_partition"] = _lisp_part
    sig["lisp_fabric_partition_devices"] = sorted({d.split()[0] for d in _lisp_part})[:12]
```

## detector_code
```
def _d_lisp_fabric_session_down(snap, sig):
    """Cisco SD-Access LISP fabric control-plane partition: a VRF whose 'show lisp session' reports sessions
    configured (total>=1) but ZERO established (parse_lisp_sessions -> snap['lisp'].sessions). Every fabric
    edge/border holds a reliable-transport session to each control-plane node (map-server / map-resolver, port
    4342); when none in a VRF is established that node can neither register its EIDs nor resolve any EID-to-RLOC
    mapping, so the fabric overlay for that VRF cannot forward (border/edge fall to control-plane partition).
    Coverage-honest: fires ONLY on an OBSERVED total>=1 / established==0 VRF; a box with no LISP, a healthy node
    (established>=1), and the benign single-Down-peer case (idle border/edge, still established>=1) stay silent --
    a lone Down session is normal per Cisco's LISP-VXLAN troubleshooting guide and must NOT cry wolf."""
    part = sig.get("lisp_fabric_partition") or []
    if not part:
        return None
    return _decision(
        "lisp-fabric-session-down",
        f"{len(part)} LISP fabric VRF(s) have control-plane sessions configured but NONE established "
        f"(e.g. {', '.join(part[:6])}). Each SD-Access fabric node opens a reliable-transport session to every "
        "control-plane node (map-server / map-resolver, port 4342) to register its EIDs and resolve EID-to-RLOC "
        "mappings; with zero established sessions in a VRF the node cannot register or resolve, so the fabric "
        "overlay for that VRF is partitioned (the border/edge blackholes silently rather than erroring). Confirm "
        "underlay reachability to the control-plane loopback, the device's map-server/map-resolver configuration, "
        "and any LISP authentication-key mismatch before the fabric is trusted at cutover. (A lone Down peer on an "
        "idle border/edge is normal and is NOT flagged -- this fires only when a VRF has total>=1 yet established==0.)",
        len(part), ["availability"],
        ["lisp.sessions[].total / lisp.sessions[].established (parse_lisp_sessions / show lisp session)"],
        priority="High",
        driver="SD-Access LISP control plane: a fabric node with sessions configured but none established to the "
               "map-server / map-resolver cannot register or resolve EID-to-RLOC -- the overlay for that VRF is "
               "partitioned, independent of underlay link state.",
        devices=sig.get("lisp_fabric_partition_devices") or [])
```

## fixture_block
```
    # Cisco SD-Access LISP fabric control-plane (universality): core1 is an IOS-XE fabric node. VRF 'red' has
    # 2 reliable-transport sessions to the control-plane nodes (map-server/map-resolver, port 4342) but ZERO
    # established (both peers Down) -> _d_lisp_fabric_session_down FIRES (red overlay partitioned: cannot register
    # or resolve EID-to-RLOC). The healthy companion VRF 'default' (2 sessions, 2 established, both peers Up) in
    # the SAME output proves coverage-honest silence -- a node with established>=1 is NOT flagged, so the single
    # firing comes only from the all-down VRF, not from any individual Down row.
    "show lisp session": """\
Sessions for VRF default, total: 2, established: 2
Peer                           State      Up/Down        In/Out    Users
10.0.255.2:4342                Up         1d04h          27/9      14
10.0.255.3:4342                Up         1d03h          19/9      14
Sessions for VRF red, total: 2, established: 0
Peer                           State      Up/Down        In/Out    Users
10.0.255.2:4342                Down       never          0/0       0
10.0.255.3:4342                Down       never          0/0       0
""",
```

## parser_test
```
def test_parse_lisp_sessions_states(cp):
    """Universality (SD-Access LISP fabric): parse_lisp_sessions reads 'show lisp session', keying each
    'Sessions for VRF <name>, total: N, established: M' block and its 'IP:port State ...' peer rows. The Down
    VRF (established 0) is distinguishable from the Up VRF by the summary counts, so the all-sessions-down
    fabric partition is detectable while the indented column header never creates a phantom peer."""
    out = (
        "Sessions for VRF default, total: 2, established: 2\n"
        "Peer                           State      Up/Down        In/Out    Users\n"
        "10.0.255.2:4342                Up         1d04h          27/9      14\n"
        "10.0.255.3:4342                Up         1d03h          19/9      14\n"
        "Sessions for VRF red, total: 2, established: 0\n"
        "Peer                           State      Up/Down        In/Out    Users\n"
        "10.0.255.2:4342                Down       never          0/0       0\n"
        "10.0.255.3:4342                Down       never          0/0       0\n")
    r = parse.parse_lisp_sessions(out)
    assert len(r) == 2
    assert r[0]["vrf"] == "default" and r[0]["total"] == 2 and r[0]["established"] == 2
    assert len(r[0]["peers"]) == 2
    assert r[0]["peers"][0] == {"peer": "10.0.255.2", "port": "4342", "state": "Up"}
    assert r[1]["vrf"] == "red" and r[1]["total"] == 2 and r[1]["established"] == 0
    assert all(p["state"] == "Down" for p in r[1]["peers"])
    assert parse.parse_lisp_sessions("") == []
```

## detector_test
```
def test_d_lisp_fabric_session_down_fires_on_zero_established_vrf_only():
    """Universality (SD-Access LISP fabric control plane): a VRF with sessions configured (total>=1) but ZERO
    established fires _d_lisp_fabric_session_down (the node cannot register/resolve EID-to-RLOC -> overlay
    partition). Refutation -- ALL THREE must stay silent: (a) a healthy VRF (established>=1); (b) the BENIGN
    partial-Down case (an idle border/edge: one peer Down but established>=1 -- a lone Down session is normal
    per Cisco's TS guide and must not cry wolf); (c) the absent lisp axis."""
    import cisco_toolkit.design_advisor as da
    fire = {"lisp": {"edge1": {"sessions": [
        {"vrf": "default", "total": 2, "established": 2,
         "peers": [{"peer": "10.0.255.2", "port": "4342", "state": "Up"},
                   {"peer": "10.0.255.3", "port": "4342", "state": "Up"}]},
        {"vrf": "red", "total": 2, "established": 0,
         "peers": [{"peer": "10.0.255.2", "port": "4342", "state": "Down"},
                   {"peer": "10.0.255.3", "port": "4342", "state": "Down"}]},
    ]}}}
    sig = da._signals(fire)
    assert any("VRF red" in x for x in sig.get("lisp_fabric_partition", []))
    dec = da._d_lisp_fabric_session_down(fire, sig)
    assert dec is not None and dec["priority"] == "High" and "LISP" in str(dec)
    assert "edge1" in dec["evidence"]["devices"]
    # (a) healthy: every VRF has established >= 1
    healthy = {"lisp": {"edge1": {"sessions": [
        {"vrf": "default", "total": 2, "established": 2,
         "peers": [{"peer": "10.0.255.2", "port": "4342", "state": "Up"},
                   {"peer": "10.0.255.3", "port": "4342", "state": "Up"}]}]}}}
    assert da._d_lisp_fabric_session_down(healthy, da._signals(healthy)) is None
    # (b) benign partial-Down: a Down peer but established >= 1 -> must NOT fire (no cry-wolf)
    benign = {"lisp": {"border1": {"sessions": [
        {"vrf": "default", "total": 2, "established": 1,
         "peers": [{"peer": "10.0.255.2", "port": "4342", "state": "Up"},
                   {"peer": "10.0.255.3", "port": "4342", "state": "Down"}]}]}}}
    assert da._d_lisp_fabric_session_down(benign, da._signals(benign)) is None
    # (c) absent axis
    assert da._d_lisp_fabric_session_down({}, da._signals({})) is None
```

## pipeline_assertion
```
    # UNIVERSALITY (SD-Access LISP fabric control plane): core1 is an IOS-XE fabric node whose VRF 'red' has
    # 2 control-plane (map-server/map-resolver) sessions configured but ZERO established (both peers Down),
    # while the healthy VRF 'default' (2/2 established, peers Up) in the same output proves no over-firing.
    assert isinstance(snap.get("lisp"), dict) and snap["lisp"].get("core1", {}).get("sessions"), \
        "snapshot must publish per-device LISP fabric state (build_lisp -> parse_lisp_sessions)"
    assert any(d.get("id") == "lisp-fabric-session-down" for d in _bp.get("decisions", [])), \
        "engine must assess SD-Access LISP control plane: a VRF with total>=1/established==0 must fire _d_lisp_fabric_session_down"
```