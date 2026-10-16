"""Protocol expected-vs-abnormal-state doctrine  (NEW-V3.23.100).

A small, offline knowledge base that turns an *observed* control-plane state into operator-grade
intelligence: what it means, the most likely cause, and the remediation. The observed state is a
**fact** (read from the device); the cause is **Inferred** (the most likely per Cisco doctrine /
field experience -- not a guarantee). `compute_protocol_intelligence` (analyze.py) joins the
per-(switch,protocol) `protocol_health` rows against this table.

Grounding (research, 2026-06; HSRP state refresh 2026-08): OSPF EXSTART/EXCHANGE -> interface MTU
mismatch (Cisco doc 13684-12); EtherChannel member flags s/D/I/w/H (Cisco `show etherchannel
summary`); VTP higher-revision overwrite of the VLAN DB (Cisco VTP guide); BGP Active/Connect =
TCP/L3 to :179, OpenSent/OpenConfirm = ASN/auth (Cisco Press BGP Fundamentals); HSRP Init/Learn
semantics -> Cisco IOS XE Network Services Configuration Guide, "Configuring HSRP"
(https://www.cisco.com/c/en/us/td/docs/routers/ios-xe/network-services/network-services/m_fhp-hsrp-0.html)."""
from typing import Optional

# severity here is the *advisory* severity (how much the operator should care), independent of the
# protocol_health row severity. confidence: the observed state is fact; the cause is Inferred.
_FACT_STATE = "observed state = fact; likely cause = Inferred (Cisco doctrine)"

# (protocol, normalized-state-token) -> advisory
_PROTOCOL_STATES = {
    # ---- OSPF neighbor states ----
    ("OSPF", "EXSTART"): {
        "severity": "High",
        "meaning": "Adjacency stuck negotiating the DB-descriptor exchange; it never reaches FULL.",
        "likely_cause": "Interface MTU mismatch between the neighbors (the classic cause); also blocked "
                        "unicast (ACL/NAT) or a duplicate OSPF router-id.",
        "remediation": "Match the IP MTU on both interfaces (or `ip ospf mtu-ignore` as a stopgap); "
                       "verify unicast reachability and unique router-ids."},
    ("OSPF", "EXCHANGE"): {
        "severity": "High",
        "meaning": "Stuck exchanging LSA headers (DBD packets); will not progress to FULL.",
        "likely_cause": "Same family as EXSTART -- almost always an interface MTU mismatch.",
        "remediation": "Match interface MTU on both ends; confirm unicast is not filtered."},
    ("OSPF", "INIT"): {
        "severity": "High",
        "meaning": "Hellos are seen in one direction only -- the neighbor is not hearing this router.",
        "likely_cause": "One-way communication: ACL/firewall, OSPF authentication mismatch, area-id / "
                        "hello-dead-timer / subnet-mask mismatch, or 224.0.0.5 multicast filtered.",
        "remediation": "Check OSPF auth, hello/dead timers, area id and mask; permit 224.0.0.5 both ways."},
    ("OSPF", "2WAY"): {
        "severity": "Info",
        "meaning": "Stable 2-WAY on a broadcast/NBMA segment -- normal between DROther routers.",
        "likely_cause": "By design: non-DR/BDR routers only form FULL adjacency with the DR and BDR.",
        "remediation": "No action -- expected. Only investigate if this link should be point-to-point."},
    ("OSPF", "DOWN"): {
        "severity": "High",
        "meaning": "No hellos received / dead-timer expired -- the neighbor is gone.",
        "likely_cause": "L1/L2 down, the neighbor is down, or a mis-set NBMA static neighbor.",
        "remediation": "Check interface/line-protocol, peer reachability and the OSPF network type."},
    ("OSPF", "ATTEMPT"): {
        "severity": "Medium",
        "meaning": "NBMA: hellos are being sent to a configured neighbor but none received back.",
        "likely_cause": "Wrong neighbor address or unicast hellos blocked on the NBMA cloud.",
        "remediation": "Verify the `neighbor` statement and unicast reachability on the NBMA segment."},
    ("OSPF", "LOADING"): {
        "severity": "Medium",
        "meaning": "Requesting/loading LSAs -- normally transient; persistent = a problem.",
        "likely_cause": "If stuck: retransmitting LSA requests (MTU) or a malformed/corrupt LSA.",
        "remediation": "If persistent, check MTU and look for a malformed LSA in the area."},
# ---- EtherChannel bundle/member flags (show etherchannel / port-channel summary) ----
    ("EtherChannel", "s"): {
        "severity": "High",
        "meaning": "Member is suspended -- it is NOT forwarding traffic.",
        "likely_cause": "LACP is configured but the partner is not responding (no LACP on the far end), "
                        "or the bundle's min-links threshold is not met.",
        "remediation": "Confirm `channel-group N mode active/passive` on BOTH ends; check the peer "
                       "port-channel and any `lacp min-links`."},
    ("EtherChannel", "I"): {
        "severity": "High",
        "meaning": "Member is stand-alone (individual) -- running on its own, NOT bundled into the channel.",
        "likely_cause": "Port settings incompatible with the bundle (speed/duplex/trunk mode/allowed or "
                        "native VLAN), or no LACP partner.",
        "remediation": "Make the member config identical to the bundle and verify LACP on the peer. Risk: "
                       "silent half-bandwidth and a possible bridging loop if it forwards independently."},
    ("EtherChannel", "D"): {
        "severity": "High",
        "meaning": "Member port is down.",
        "likely_cause": "Cable/SFP fault, peer port down, or err-disabled.",
        "remediation": "Check the transceiver, cabling and the peer interface; clear any err-disable."},
    ("EtherChannel", "w"): {
        "severity": "Medium",
        "meaning": "Member is waiting to be aggregated (LACP negotiation in progress).",
        "likely_cause": "Transient during bring-up; if it persists, treat it like a suspended member.",
        "remediation": "Usually clears on its own; if persistent, check LACP on the peer."},
    ("EtherChannel", "H"): {
        "severity": "Info",
        "meaning": "LACP hot-standby member (max-bundle exceeded) -- standby, not a fault.",
        "likely_cause": "By design: more members than `lacp max-bundle` allows; extras are hot-standby.",
        "remediation": "No action unless you expected this member to be active."},
    ("EtherChannel", "M"): {
        "severity": "High",
        "meaning": "The bundle is not in use because its minimum-links requirement is not met.",
        "likely_cause": "Too few eligible member links are bundled, or the configured min-links threshold "
                        "exceeds the currently available members.",
        "remediation": "Restore and re-bundle the missing members; then reconcile `port-channel min-links` "
                       "with the intended failure tolerance before acceptance."},
    ("EtherChannel", "m"): {
        "severity": "High",
        "meaning": "This member is not aggregated because the bundle's minimum-links requirement is not met.",
        "likely_cause": "The channel lacks enough eligible links to activate the aggregator.",
        "remediation": "Restore the failed or incompatible members and verify the min-links policy on both ends."},
    ("EtherChannel", "N"): {
        "severity": "High",
        "meaning": "The port-channel is not in use and no aggregation is active.",
        "likely_cause": "No member has successfully joined the aggregator, or the channel is administratively "
                        "or operationally unavailable.",
        "remediation": "Inspect every member state and the channel protocol; restore at least the intended "
                       "eligible members before accepting the bundle."},
    ("EtherChannel", "f"): {
        "severity": "High",
        "meaning": "The member failed to allocate an aggregator and is not bundled.",
        "likely_cause": "The local channel cannot place the link into a compatible aggregator, commonly because "
                        "of member configuration or partner negotiation differences.",
        "remediation": "Compare the member and port-channel configuration, then verify the LACP/PAgP partner view."},
    ("EtherChannel", "u"): {
        "severity": "High",
        "meaning": "The member is unsuitable for bundling and is not part of the forwarding channel.",
        "likely_cause": "A member attribute differs from the aggregator, such as switchport mode, VLAN, speed, "
                        "duplex, or channel protocol parameters.",
        "remediation": "Reconcile the member's operational and configured attributes with the port-channel and peer."},
    ("EtherChannel", "r"): {
        "severity": "High",
        "meaning": "The NX-OS member's module is removed, so the link cannot forward in the port-channel.",
        "likely_cause": "The line card or fabric extender that owns the member is absent or unavailable.",
        "remediation": "Restore the owning hardware and confirm the member returns to the intended bundled state."},
    ("EtherChannel", "b"): {
        "severity": "Medium",
        "meaning": "The NX-OS member is waiting for its BFD session and is not yet a proven active member.",
        "likely_cause": "BFD-assisted LACP convergence is incomplete or the BFD session is not establishing.",
        "remediation": "Verify BFD and LACP state on both ends; treat a persistent wait as a cutover blocker."},
    ("EtherChannel", "d"): {
        "severity": "Medium",
        "meaning": "The member remains in the default state; the summary does not prove it is bundled.",
        "likely_cause": "Negotiation or member initialization has not produced a forwarding channel state.",
        "remediation": "Inspect the detailed channel state and peer negotiation before accepting this member."},
    ("EtherChannel", "p"): {
        "severity": "Info",
        "meaning": "The NX-OS member is up in delay-LACP mode.",
        "likely_cause": "Delay-LACP is active by design for this member.",
        "remediation": "Preserve the observed mode; investigate only if ordinary active bundling was intended."},
    # ---- BGP neighbor states ----
    ("BGP", "ACTIVE"): {
        "severity": "High",
        "meaning": "Session not establishing -- BGP is actively trying but the TCP setup keeps failing.",
        "likely_cause": "TCP to port 179 failing: a firewall/ACL blocking 179, wrong neighbor IP, no "
                        "route to the peer, or an MTU issue silently dropping the TCP SYN.",
        "remediation": "Ping/traceroute the peer; confirm 179 is permitted; verify neighbor IP, "
                       "update-source interface and path MTU."},
    ("BGP", "CONNECT"): {
        "severity": "High",
        "meaning": "Waiting on the TCP three-way handshake to the peer.",
        "likely_cause": "L3/TCP reachability to :179 (same family as Active).",
        "remediation": "Verify reachability to the peer and that TCP/179 is open end to end."},
    ("BGP", "IDLE"): {
        "severity": "High",
        "meaning": "BGP is not attempting a session at all.",
        "likely_cause": "No route to the neighbor, the neighbor is administratively shut, or repeated "
                        "failures have backed the session off.",
        "remediation": "Check for a route to the peer, `no shutdown` the neighbor, and read the "
                       "last-error in `show ip bgp neighbor`."},
    ("BGP", "OPENSENT"): {
        "severity": "Medium",
        "meaning": "TCP is up and an OPEN was sent, but the peers have not agreed.",
        "likely_cause": "AS-number mismatch, router-id conflict, or an MD5/auth mismatch.",
        "remediation": "Verify remote-as, unique router-ids and the neighbor password/auth."},
    ("BGP", "OPENCONFIRM"): {
        "severity": "Medium",
        "meaning": "OPEN exchanged; waiting on the peer's keepalive to reach Established.",
        "likely_cause": "Often an auth/keepalive-timer mismatch or an unstable peer.",
        "remediation": "Check auth and timers; watch for the peer flapping."},
    # ---- VTP ----
    ("VTP", "HIGH-REVISION"): {
        "severity": "High",
        "meaning": "A VTP server is carrying a high configuration-revision number.",
        "likely_cause": "Any switch inserted with a HIGHER revision (even an old/stale one) overwrites "
                        "the whole domain's VLAN database -- a classic, sudden campus outage.",
        "remediation": "Prefer VTP transparent/off (manage VLANs manually); before adding ANY switch reset "
                       "its revision (set mode transparent then back, or change+revert the domain name); "
                       "back up the VLAN database."},
    # ---- STP ----
    ("STP", "INCONSISTENT"): {
        "severity": "High",
        "meaning": "Spanning-tree has inconsistent (blocked) ports -- root-/loop-/PVST-inconsistency.",
        "likely_cause": "Root-guard reacting to a superior BPDU, loop-guard/UDLD, or a PVST+ per-VLAN "
                        "mismatch on a trunk.",
        "remediation": "Identify the neighbor sending the offending BPDU and the VLAN involved; fix the "
                       "trunk/STP mismatch. The port stays blocked until the inconsistency clears."},
    # ---- First-hop redundancy (subtype retained so HSRP doctrine is not generalized to VRRP/GLBP) ----
    ("FHRP", "HSRP:INIT"): {
        "severity": "Medium",
        "meaning": "The HSRP group is not ready or able to participate in gateway redundancy.",
        "likely_cause": "The associated interface is not up, the group has no usable interface IP, or "
                        "the state is transient immediately after configuration or interface bring-up.",
        "remediation": "Verify the SVI/interface and line protocol are up, confirm a usable primary IP "
                       "and the HSRP group configuration, then re-check that the group leaves Init."},
    ("FHRP", "HSRP:LEARN"): {
        "severity": "Medium",
        "meaning": "The HSRP router is waiting to learn the virtual IP and has not heard an "
                   "authenticated hello from the active router.",
        "likely_cause": "The active peer is absent or its hellos are not being accepted because of an "
                        "authentication, VLAN/L2 reachability, group, or version mismatch.",
        "remediation": "Confirm the virtual IP/group/version/authentication on both peers, verify the "
                       "shared VLAN can carry HSRP hellos, and inspect the active peer before cutover."},
}

# OSPF composite states like '2WAY/DROTHER' or 'FULL/BDR' -> take the leading token.
_HEALTHY_OSPF = {"FULL"}


def advise(protocol: str, state_token: str) -> Optional[dict]:
    """Return the advisory {severity, meaning, likely_cause, remediation, confidence} for a
    (protocol, observed-state) pair, or None when the state is healthy / unknown to the KB."""
    if not protocol or not state_token:
        return None
    proto = protocol.strip()
    tok = state_token.strip().upper().split("/")[0]   # 'FULL/BDR' -> 'FULL', '2WAY/DROTHER' -> '2WAY'
    if proto == "OSPF" and tok in _HEALTHY_OSPF:
        return None
    # EtherChannel flags are single-letter and case-sensitive (s vs S) -- key by the raw flag.
    key = (proto, state_token.strip()) if proto == "EtherChannel" else (proto, tok)
    rec = _PROTOCOL_STATES.get(key)
    if rec is None:
        return None
    out = dict(rec)
    out["confidence"] = _FACT_STATE
    return out
