# slice: cts -> cts-environment-data-not-downloaded
arch: Cisco TrustSec / CTS group-based segmentation (SGT/SGACL). show cts environment-data (IOS-XE) reports the device's environment-data download state machine: the SGT-to-name table, the Server List, and the Lifetime/refresh timers it pulls from Cisco ISE. The env-data download is the prerequisite for ANY SGACL enforcement -- without a valid, current environment-data set the switch has no SGT->name/policy map, so group-based segmentation is blind/unenforced (default-permit) even though CTS is configured.
viable: True | fixture_device: core1 | snap_key: cts
commands: show cts environment-data[ios]
firing: snap['cts'][host]['environment_data']['state'] is present and != 'COMPLETE' (e.g. START, WAITING_RESPONSE, WAITING_PAC). Such a device has not finished downloading the SGT->name/SGACL set from ISE, so group-based segmentation has no policy map to enforce. Fires once per affected device.
coverage_honesty: Two-layer silence. (1) ABSENT: a device that runs no TrustSec prints no env-data block ('% ...' or empty), so parse_cts_environment_data returns {} -> build_cts omits the key -> snap['cts'] has no entry -> the signal list is empty -> the detector returns None. A non-TrustSec fleet (e.g. the Meridian campus) therefore never fires. (2) HEALTHY: 'Current state = COMPLETE' yields state=='COMPLETE', which is excluded from cts_env_stale, so a fully-downloaded device is silent. Critically, the parser reads ONLY the env-data 'Current state' line, never the per-server 'Status = DEAD' line -- verified against Cisco field output where a COMPLETE (cached) env-data set coexists with DEAD RADIUS servers -- so transient server death does NOT cry wolf. The detector fires on exactly one unambiguous, genuinely-broken condition: env-data observed but not COMPLETE.
confidence: HIGH / viable=true. The broken-state is clean and unambiguous: the env-data state machine reports a single 'Current state' whose only valid/complete terminal value is COMPLETE; every other value (START, WAITING_RESPONSE, WAITING_PAC) means the SGT->name/SGACL set is stale or never downloaded -> group-based segmentation is blind. Coverage-honesty is strong on both axes: absent CTS -> {} -> silent (proven by access1 carrying no command and by the empty-input parser test); COMPLETE -> silent. The one real false-positive trap -- a COMPLETE, cached env-data set coexisting with DEAD RADIUS servers -- is explicitly designed out: the parser reads ONLY the env-data 'Current state', never the per-server 'Status' line, a distinction verified against Cisco field output (TheNetworkDNA example shows COMPLETE with both servers DEAD) and the CSCwe06881 bug (server/PAC issues surface as a non-COMPLETE state, which IS what we fire on -- correctly). Caveats for the integrator: (1) the exact set of non-COMPLETE state strings varies slightly by IOS-XE train (START / WAITING_RESPONSE / WAITING_PAC / DONE on some releases) -- the detector is robust because it fires on 'present and != COMPLETE' rather than enumerating bad states, but if a future train renames the healthy terminal state away from 'COMPLETE' this would over-fire; grep a target-train command reference to confirm 'COMPLETE' is still the success token before trusting at scale. (2) Cisco's official command-reference pages return HTTP 403 to the fetch tool, so the verbatim COMPLETE block + Security Group Name Table format were captured from a primary-grade community reproduction (TheNetworkDNA) and the failed-state from Cisco's own bug DB; the field NAMES (Current state / Last status / Security Group Name Table / Environment Data Lifetime) are corroborated across all five sources and match the doc page titles/snippets returned by search. (3) NX-OS prints 'TS Environment Data' rather than 'CTS Environment Data' -- the parser header anchor accepts both, but the primary target is IOS-XE as specified. The regex is grounded exactly in parser_sample_input; sgt_count uses the documented 'tag-generation:name' token form ('4-04:Employees').
sources: https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9300/software/release/17-3/command_reference/b_173_9300_cr/cisco_trustsec_commands.html (Cisco Catalyst 9300 IOS-XE 17.3.x Cisco TrustSec command reference -- 'show cts environment-data': Current state / Last status / Local Device SGT / Server List Info / Security Group Name Table / Environment Data Lifetime / Last update / Env-data expires-refreshes / Cache data applied / State Machine fields) | https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9600/software/release/17-9/command_reference/b_179_9600_cr/cisco_trustsec_commands.html (Cisco Catalyst 9600 IOS-XE 17.9.x Cisco TrustSec command reference -- same 'show cts environment-data' output schema) | https://www.thenetworkdna.com/2022/03/trustsec-troubleshooting-on-edge-node.html (verbatim COMPLETE-state output: 'Current state = COMPLETE / Last status = Successful', Local Device SGT, Server List with Status = DEAD coexisting with COMPLETE, Security Group Name Table '0-07:Unknown 3-00:Network_Services 4-04:Employees ...') | https://www.findbugzero.com/operational-defect-database/vendors/cisco/defects/CSCwe06881 (Cisco bug CSCwe06881 -- failed download field state: 'Current state = WAITING_RESPONSE' with 'Environment data is empty', confirming the non-COMPLETE broken state and that it is the env-data state machine, not server liveness, that gates enforcement) | https://community.cisco.com/t5/security-knowledge-base/trustsec-troubleshooting-guide/ta-p/3647576 (Cisco TrustSec Troubleshooting Guide -- START/Failed env-data state and Retry_timer semantics)

## parser_sample_input
```
core1# show cts environment-data
CTS Environment Data
====================
Current state = COMPLETE
Last status = Successful
Local Device SGT:
  SGT tag = 216-22:TrustSec_Devices
Server List Info:
Installed list: CTSServerList1-000B, 2 server(s):
 *Server: 10.0.0.10, port 1812, A-ID 3X0P672A296F212FUEC21S27E4A2579N
          Status = ALIVE
          auto-test = TRUE, keywrap-enable = FALSE, idle-time = 60 mins, deadtime = 20 secs
 *Server: 10.0.0.11, port 1812, A-ID 3X08674A806S217FUEC21C24E4A3549N
          Status = ALIVE
Security Group Name Table:
    0-07:Unknown    3-00:Network_Services    4-04:Employees    5-00:Contractors    7-00:Production_Users    8-00:Developers    9-01:Auditors
Environment Data Lifetime = 86400 secs
Last update time = 07:48:41 UTC Mon Jun 1 2026
Env-data expires in   0:23:56:02 (dd:hr:mm:sec)
Env-data refreshes in 0:23:56:02 (dd:hr:mm:sec)
Cache data applied           = NONE
State Machine is running

--- broken companion (a SECOND device / capture; the env-data download never completed) ---
core9# show cts environment-data
CTS Environment Data
====================
Current state = WAITING_RESPONSE
Last status = Failed
Environment Data is empty
State Machine is running
Retry_timer (60 secs) is running
```

## parser_code
```
def parse_cts_environment_data(output: str) -> dict:
    """'show cts environment-data' (IOS-XE TrustSec) -> {} when CTS is not configured / the command is absent,
    else {state, last_status, sgt_count, server_count, lifetime}. The environment-data download is the
    state machine that pulls the SGT->name table (and SGACL policy) from Cisco ISE; 'Current state =
    COMPLETE' (with 'Last status = Successful') is the only fully-downloaded/valid state. Any other state
    (START, WAITING_RESPONSE, WAITING_PAC, ...) means the SGT-to-policy data is stale or was never
    downloaded, so group-based segmentation has no map to enforce (default-permit) -- the device is blind.

    Read ONLY the env-data 'Current state' / 'Last status' lines and the size of the 'Security Group Name
    Table'. The per-server 'Status = DEAD' line is deliberately IGNORED: a device can hold a COMPLETE,
    cached environment-data set while its RADIUS/ISE servers later go DEAD (verified against Cisco docs /
    field output), so server liveness is NOT an env-data-validity signal and must not drive this detector.
    Tolerant: returns {} when no env-data block is present; never raises."""
    text = output or ""
    # Anchor on the env-data block header; a box with no CTS env-data prints neither this nor 'Current state'.
    if not re.search(r"^\s*(?:CTS|TS)\s+Environment\s+Data\b", text, re.IGNORECASE | re.MULTILINE) \
            and not re.search(r"^\s*Current state\s*=", text, re.IGNORECASE | re.MULTILINE):
        return {}
    res = {"state": "", "last_status": "", "sgt_count": 0, "server_count": 0, "lifetime": None}
    m = re.search(r"^\s*Current state\s*=\s*(\S+)", text, re.IGNORECASE | re.MULTILINE)
    if m:
        res["state"] = m.group(1).strip().upper()
    m = re.search(r"^\s*Last status\s*=\s*(.+?)\s*$", text, re.IGNORECASE | re.MULTILINE)
    if m:
        res["last_status"] = m.group(1).strip()
    m = re.search(r"Lifetime\s*=\s*(\d+)", text, re.IGNORECASE)
    if m:
        res["lifetime"] = int(m.group(1))
    # SGT->name entries look like '0-07:Unknown' / '4-04:Employees' (tag '-' generation ':' name), one or
    # more per line in the 'Security Group Name Table'. Count distinct leading SGT tags actually present.
    sgts = set(re.findall(r"(?:^|\s)(\d+)-[0-9a-fA-F]+:\S+", text))
    res["sgt_count"] = len(sgts)
    # RADIUS server lines: ' *Server: 10.10.10.1, port 1812, A-ID ...'. Count them (informational only).
    res["server_count"] = len(re.findall(r"^\s*\*?Server:\s*\d+\.\d+\.\d+\.\d+", text, re.MULTILINE))
    # A state line with no recognizable value is not a usable signal -> treat as absent.
    if not res["state"]:
        return {}
    return res
```

## build_code
```
def build_cts(cmd_to_file: Dict[str, str]) -> dict:
    """Cisco TrustSec environment-data download state for THIS device -> {environment_data: {...}} or {}.
    'show cts environment-data' reports the state machine that pulls the SGT->name table / SGACL policy from
    Cisco ISE; the env-data download is the prerequisite for ANY group-based (SGT/SGACL) enforcement. {} when
    the device runs no CTS (command absent / not configured) -- coverage-honest, so a non-TrustSec fleet never
    fires. A 'Current state' that is not COMPLETE means the SGT-to-policy data is stale or was never
    downloaded, so segmentation is blind/unenforced. Fail-soft via _safe_parse."""
    env = _safe_parse(parse_cts_environment_data,
                      _load_cmd_output(cmd_to_file, "show cts environment-data")) or {}
    out = {}
    if env:
        out["environment_data"] = env
    return out
```

## signal_code
```
    # Cisco TrustSec / CTS group-based segmentation (snap['cts'] from build_cts): the env-data download is the
    # prerequisite for SGT/SGACL enforcement. FIRING STATE: CTS env-data WAS collected here but its 'Current
    # state' is not COMPLETE (START / WAITING_RESPONSE / WAITING_PAC / ...), i.e. the SGT-to-policy map is
    # stale or never downloaded -> group-based segmentation is blind/unenforced (default-permit). Coverage-
    # honest: a device with no CTS publishes {} and never fires; a COMPLETE state is silent EVEN WHEN its
    # RADIUS servers show Status=DEAD (a COMPLETE set can be cached after the servers die -- not an env-data
    # fault), because the parser reads only the env-data state, never per-server status.
    _cts = _as_dict(snap.get("cts"))
    _cts_stale = []
    for _ch, _cf in sorted(_cts.items()):
        _env = _as_dict(_as_dict(_cf).get("environment_data"))
        _state = str(_env.get("state", "")).strip().upper()
        if _state and _state != "COMPLETE":
            _cts_stale.append(f"{_ch} ({_state or '?'})")
    sig["cts_env_stale"] = _cts_stale
```

## detector_code
```
def _d_cts_environment_data_health(snap, sig):
    """Cisco TrustSec / CTS group-based segmentation: a device whose CTS environment-data 'Current state' is
    NOT COMPLETE (parse_cts_environment_data -> snap['cts'].environment_data.state). The environment-data
    download pulls the SGT->name table and SGACL policy from Cisco ISE; until it reaches COMPLETE the switch
    has no SGT-to-policy map, so group-based segmentation is blind and SGACLs cannot be enforced (the fabric
    falls back to default-permit) even though TrustSec is configured. Coverage-honest: fires ONLY on an
    OBSERVED non-COMPLETE state -- a box running no CTS (snap['cts'] absent / {}) stays silent, and a
    COMPLETE state stays silent even when its RADIUS servers are DEAD (a COMPLETE env-data set can be cached
    after the servers die; server liveness is not read here)."""
    stale = sig.get("cts_env_stale") or []
    if not stale:
        return None
    return _decision(
        "cts-environment-data-not-downloaded",
        f"{len(stale)} device(s) have CTS TrustSec environment-data that is NOT in the COMPLETE/valid "
        f"downloaded state (e.g. {', '.join(stale[:6])}). The environment-data download distributes the "
        "SGT-to-name table and SGACL policy from Cisco ISE; until it reaches COMPLETE the switch holds no "
        "group-to-policy map, so group-based (SGT/SGACL) segmentation is blind and unenforced -- traffic "
        "between security groups is default-permitted even though TrustSec is configured. Confirm "
        "PAC provisioning, RADIUS/ISE (CTS) server reachability and the 'cts authorization list' / "
        "'cts refresh environment-data' before the segmentation policy is trusted at cutover.",
        len(stale), ["security", "segmentation"],
        ["cts.environment_data.state (parse_cts_environment_data / show cts environment-data)"],
        priority="High",
        driver="TrustSec segmentation: a CTS environment-data set that is not COMPLETE leaves the device with "
               "no SGT-to-policy map, so group-based access control is silently unenforced (default-permit).",
        devices=sorted({s.split(" (")[0] for s in stale})[:12])
```

## fixture_block
```
    # Cisco TrustSec / CTS universality: core1 (IOS-XE) is a TrustSec node whose environment-data download
    # never completed -> _d_cts_environment_data_health FIRES (Current state = WAITING_RESPONSE, not
    # COMPLETE; SGT/SGACL map absent -> group-based segmentation blind). The healthy COMPLETE companion +
    # the absent-CTS case are proved in test_d_cts_environment_data_health_fires_on_non_complete_only and in
    # access1 (which carries no 'show cts environment-data' at all -> snap['cts'] omits it -> silent).
    "show cts environment-data": """\
CTS Environment Data
====================
Current state = WAITING_RESPONSE
Last status = Failed
Environment Data is empty
State Machine is running
Retry_timer (60 secs) is running
""",
```

## parser_test
```
def test_parse_cts_environment_data_states(cp):
    """Universality (Cisco TrustSec / CTS segmentation): parse_cts_environment_data reads the env-data
    'Current state' so a download that is not COMPLETE (no SGT->policy map -> segmentation blind) is
    detectable, while a COMPLETE set is recognized as healthy. Critically, a COMPLETE state with DEAD
    RADIUS servers stays COMPLETE (server status is NOT read), and absent / non-CTS output yields {}."""
    complete = (
        "CTS Environment Data\n"
        "====================\n"
        "Current state = COMPLETE\n"
        "Last status = Successful\n"
        "Local Device SGT:\n"
        "  SGT tag = 216-22:TrustSec_Devices\n"
        "Server List Info:\n"
        "Installed list: CTSServerList1-000B, 2 server(s):\n"
        " *Server: 10.0.0.10, port 1812, A-ID 3X0P672A296F212FUEC21S27E4A2579N\n"
        "          Status = DEAD\n"
        " *Server: 10.0.0.11, port 1812, A-ID 3X08674A806S217FUEC21C24E4A3549N\n"
        "          Status = DEAD\n"
        "Security Group Name Table:\n"
        "    0-07:Unknown    3-00:Network_Services    4-04:Employees    5-00:Contractors\n"
        "Environment Data Lifetime = 86400 secs\n"
        "State Machine is running\n")
    r = cp.parse_cts_environment_data(complete)
    assert r["state"] == "COMPLETE" and r["last_status"] == "Successful"
    assert r["sgt_count"] == 4 and r["server_count"] == 2 and r["lifetime"] == 86400
    broken = (
        "CTS Environment Data\n"
        "====================\n"
        "Current state = WAITING_RESPONSE\n"
        "Last status = Failed\n"
        "Environment Data is empty\n"
        "State Machine is running\n"
        "Retry_timer (60 secs) is running\n")
    b = cp.parse_cts_environment_data(broken)
    assert b["state"] == "WAITING_RESPONSE" and b["last_status"] == "Failed" and b["sgt_count"] == 0
    # Absent / non-CTS -> {} (coverage-honest: nothing to assess).
    assert cp.parse_cts_environment_data("") == {}
    assert cp.parse_cts_environment_data("% Invalid input detected at '^' marker.") == {}
```

## detector_test
```
def test_d_cts_environment_data_health_fires_on_non_complete_only():
    """Universality (Cisco TrustSec / CTS segmentation): a device whose CTS environment-data 'Current state'
    is not COMPLETE fires _d_cts_environment_data_health (no SGT->policy map downloaded -> group-based
    segmentation blind/unenforced). Refutation (coverage-honest): a COMPLETE state -- EVEN WITH dead RADIUS
    servers -- stays silent, and an absent cts axis stays silent."""
    import cisco_toolkit.design_advisor as da
    fire = {"cts": {"core1": {"environment_data": {
        "state": "WAITING_RESPONSE", "last_status": "Failed", "sgt_count": 0, "server_count": 0}}}}
    sig = da._signals(fire)
    assert "core1" in " ".join(sig.get("cts_env_stale", []))
    dec = da._d_cts_environment_data_health(fire, sig)
    assert dec is not None and dec["priority"] == "High" and "TrustSec" in str(dec)
    assert "core1" in dec["evidence"]["devices"]
    # Healthy COMPLETE (servers DEAD on purpose) must NOT fire -- a cached COMPLETE set survives dead servers.
    clean = {"cts": {"core1": {"environment_data": {
        "state": "COMPLETE", "last_status": "Successful", "sgt_count": 7, "server_count": 2}}}}
    assert da._d_cts_environment_data_health(clean, da._signals(clean)) is None
    # Absent CTS axis must NOT fire (coverage-honest).
    assert da._d_cts_environment_data_health({}, da._signals({})) is None
```

## pipeline_assertion
```
    # UNIVERSALITY (Cisco TrustSec / CTS segmentation): core1 is a TrustSec node whose environment-data
    # download is stuck in WAITING_RESPONSE (not COMPLETE) -> the SGT/SGACL policy map is never downloaded,
    # so _d_cts_environment_data_health must fire end-to-end. A non-CTS device publishes no cts entry and
    # stays silent (coverage-honest).
    assert isinstance(snap.get("cts"), dict) and snap["cts"].get("core1", {}).get("environment_data"), \
        "snapshot must publish per-device CTS state (build_cts -> parse_cts_environment_data)"
    assert snap["cts"]["core1"]["environment_data"].get("state") == "WAITING_RESPONSE", \
        "core1 CTS env-data 'Current state' must be the observed non-COMPLETE value"
    assert any(d.get("id") == "cts-environment-data-not-downloaded" for d in _bp.get("decisions", [])), \
        "engine must assess TrustSec segmentation: a non-COMPLETE CTS env-data download must fire _d_cts_environment_data_health"
```