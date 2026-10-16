"""EVPN migration guardrails — evidence-grounded brownfield -> NX-OS VXLAN BGP-EVPN cutover doctrine.

When the design blueprint's target fabric is (or defaults to) standalone NX-OS VXLAN BGP-EVPN, a brownfield
migration carries a small set of load-bearing, primary-source-documented guardrails that a generic move-group
plan misses. This module turns those into concrete pre-cutover / cutover-gate / rollback items GROUNDED in the
fleet's OWN observed evidence (NX-OS release per device, first-hop-gateway state, vPC / STP), so the MOP and the
NRFU acceptance plan carry them automatically -- and stays COVERAGE-HONEST: it is silent unless a VXLAN-EVPN
fabric is genuinely the target (the same gate compute_target_state §1b uses), and it cites observed counts
rather than asserting state it did not see.

Sources (primary Cisco, verified 2025-2026):
- Cisco NX-OS Nexus 9000 VXLAN Config Guide, "Default Gateway Coexistence of HSRP and Anycast Gateway"
  (releases 10.2(x)-10.6(x)) -- the NX-OS 10.2(3) HSRP<->DAG coexistence gate.
- Cisco Live BRKDCN-2951 (2025), "Migrating to VXLAN EVPN" -- the 3-step vPC back-to-back method + the
  mandatory HSRP-vMAC-to-DAG-MAC pre-step + forced GARP.
- Cisco white papers "Migrating Classic Ethernet to VXLAN BGP EVPN" and "Migrating a FabricPath environment
  to VXLAN BGP EVPN" -- double-sided vPC loop-safety (the overlay neither forwards nor blocks STP BPDUs).
"""
import re
from typing import Optional

from cisco_toolkit.design_advisor import _as_dict, _as_list, _norm_fabric_model, _signals, _LARGE_L2_VLANS

# The release at which a single NX-OS switch can run a legacy FHRP/HSRP gateway AND the fabric Distributed
# Anycast Gateway for the SAME subnet simultaneously (the coexistence required during a seamless migration).
_DAG_COEXIST_MIN = (10, 2, 3)


def _nxos_version_tuple(sw_version: str) -> Optional[tuple]:
    """Leading MAJOR.MINOR(MAINT) of an NX-OS release string -> (major, minor, maint), or None if unparseable.
    NX-OS prints e.g. '10.2(3)', '10.3(4a)', '9.3(10)', '7.0(3)I7(9)', '6.0(2)N2(3)' -- only the leading
    numeric major.minor(maint) is needed to compare against the 10.2(3) coexistence gate (the I7/N2 platform
    sub-trains and a letter rebuild suffix do not change the major.minor(maint) ordering for this gate)."""
    m = re.match(r"\s*(\d+)\.(\d+)\((\d+)", str(sw_version or ""))
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))


def _nxos_below_coexist(sw_version: str) -> Optional[bool]:
    """True if an NX-OS release is BELOW 10.2(3) (cannot run HSRP + DAG on one subnet), False if >=, None if
    the version string did not parse (coverage-honest: an unparseable version is NOT asserted either way)."""
    vt = _nxos_version_tuple(sw_version)
    if vt is None:
        return None
    return vt < _DAG_COEXIST_MIN


def _is_nxos(platform: str, model: str) -> bool:
    """Best-effort NX-OS / Nexus identification from the lifecycle platform label or the PID, without coupling
    to analyze.py internals. 'Nexus 6001' / 'NX-OS' in the platform, or an N<digit>K-style Nexus PID."""
    blob = f"{platform or ''} {model or ''}".lower()
    return bool(re.search(r"nexus|nx-?os", blob) or re.match(r"\s*n\d+k", (model or "").strip().lower()))


def _gw(id, phase, severity, title, basis, detail, source):
    return {"id": id, "phase": phase, "severity": severity, "title": title,
            "basis": basis, "detail": detail, "source": source}


def compute_evpn_migration_guardrails(snap, requirements=None, design_blueprint=None, sig=None) -> dict:
    """Gated, evidence-grounded brownfield->EVPN migration guardrails.

    APPLICABLE only when a VXLAN-EVPN fabric is genuinely the target -- the same condition compute_target_state
    §1b uses to put the DC fabric operating-model decision in scope (wide-L2 / many-VLANs / >=30 devices / a
    stated model) AND the model is not ACI (ACI migration is a different playbook). Returns
    {applicable, model_basis, summary, guardrails:[{id, phase, severity, title, basis, detail, source}]};
    {applicable: False, guardrails: []} when out of scope, so the MOP / NRFU render nothing on a non-EVPN
    engagement. `design_blueprint` is accepted for symmetry/future use but the gate is recomputed from the
    snapshot + requirements so the result is correct even if called standalone."""
    snap = _as_dict(snap)
    req = _as_dict(requirements) if requirements else {}
    sig = _signals(snap) if sig is None else sig

    fm = _norm_fabric_model(req.get("fabric_operating_model"))
    fabric_candidate = bool(sig.get("l2_wide_vlans") or sig.get("vlans", 0) >= _LARGE_L2_VLANS
                            or sig.get("inventory", 0) >= 30 or fm)
    if not (fabric_candidate and fm != "aci"):
        return {"applicable": False, "model_basis": "", "summary": "", "guardrails": []}

    model_basis = ("requirement-confirmed (fabric_operating_model = nxos-evpn)" if fm == "nxos-evpn"
                   else "engine-default — NX-OS VXLAN-EVPN assumed; supply fabric_operating_model to confirm")

    # ---- observed evidence to ground the guardrails (never inferred) ----
    below = []   # NX-OS devices on a release below the 10.2(3) coexistence gate
    nxos_total = 0
    for d in _as_list((_as_dict(snap.get("lifecycle_risk")).get("per_device"))):
        d = _as_dict(d)
        if not _is_nxos(d.get("platform"), d.get("model")):
            continue
        nxos_total += 1
        if _nxos_below_coexist(d.get("sw_version")) is True:
            below.append((d.get("host", "?"), str(d.get("sw_version") or "?")))
    below.sort()

    l3f = _as_list(snap.get("l3_forwarding"))
    n_gw = len(l3f)
    n_gw_fhrp = sum(1 for g in l3f if str(_as_dict(g).get("fhrp") or "none").lower() != "none")
    vpc_domains = int(sig.get("vpc_domains") or 0)
    vpc_hosts = sorted(_as_dict(snap.get("vpc")).keys())[:6]
    _stp = snap.get("stp_roots")                      # parse_*_roots publishes a {host: {...}} dict, not a list
    n_stp = len(_stp) if isinstance(_stp, (dict, list)) else 0

    guardrails = []

    # PRE-1 — NX-OS 10.2(3) HSRP<->DAG coexistence version gate (evidence: per-device NX-OS release)
    if below:
        sample = "; ".join(f"{h} {v}" for h, v in below[:6]) + (" …" if len(below) > 6 else "")
        basis = f"{len(below)} of {nxos_total} NX-OS device(s) run a release below 10.2(3) — e.g. {sample}"
        sev = "High"
    elif nxos_total:
        basis = f"all {nxos_total} NX-OS device(s) parsed at or above 10.2(3) (re-verify the fabric-border nodes)"
        sev = "Info"
    else:
        basis = "no NX-OS release evidence collected — verify the train on the legacy and fabric-border nodes"
        sev = "Info"
    guardrails.append(_gw(
        "evpn-pre-nxos-1023-gateway-coexistence", "pre-cutover", sev,
        "NX-OS 10.2(3) HSRP↔Anycast-Gateway coexistence gate",
        basis,
        "Before NX-OS 10.2(3) a switch CANNOT run a legacy FHRP/HSRP gateway and the fabric Distributed "
        "Anycast Gateway for the SAME subnet at once. Any node that must hold both during seamless coexistence "
        "(the border/anchor leaf, and any legacy device keeping its gateway through transition) needs NX-OS "
        ">= 10.2(3); otherwise keep the default gateway in the legacy network until the subnet's workloads have "
        "fully migrated, or move the gateway to the fabric first. Verify the running train on BOTH the legacy "
        "and the fabric-border nodes.",
        "Cisco NX-OS VXLAN Config Guide 'Default Gateway Coexistence of HSRP and Anycast Gateway'; BRKDCN-2951"))

    # PRE-2 — first-hop gateway / virtual-MAC transition (evidence: gateway count + FHRP presence)
    if n_gw_fhrp:
        basis = f"{n_gw_fhrp} of {n_gw} gateway(s) run FHRP/HSRP — their virtual MAC must be aligned to the DAG MAC"
        detail = (
            "In a maintenance window, BEFORE any workload moves, reconfigure each legacy HSRP virtual MAC to "
            "MATCH the fabric Distributed-Anycast-Gateway MAC (e.g. 2020.0000.00aa), then force hosts to refresh "
            "their ARP cache by failing the HSRP standby to active (gratuitous ARP). Not all hosts honour GARP "
            "(static entries / GARP-ignoring stacks need a manual ARP flush) — a vMAC mismatch at cutover "
            "black-holes the subnet until ARP caches expire.")
    else:
        basis = (f"{n_gw} gateway(s), 0 running FHRP/HSRP — hosts hold the PHYSICAL gateway MAC, not an HSRP vMAC"
                 if n_gw else "no L3 gateway evidence collected")
        detail = (
            "With no FHRP/HSRP, each subnet's hosts ARP the physical SVI MAC of a single gateway, so there is no "
            "HSRP virtual MAC to pre-align — but the SAME risk applies: when the gateway moves to the fabric DAG "
            "the gateway MAC changes, so plan a forced ARP refresh (GARP from the new DAG, or a host-side ARP "
            "flush) in the cutover window. A gateway-MAC change with stale host ARP black-holes the subnet.")
    guardrails.append(_gw(
        "evpn-pre-gateway-vmac-transition", "pre-cutover", "High",
        "First-hop gateway / virtual-MAC transition (mandatory pre-step)",
        basis, detail,
        "BRKDCN-2951 (2025); Cisco 'Migrating Classic Ethernet to VXLAN BGP EVPN' white paper"))

    # CUT-1 — single active L2 interconnect / loop safety (evidence: vPC domains + STP roots)
    guardrails.append(_gw(
        "evpn-cut-single-active-l2-interconnect", "cutover-gate", "Critical",
        "Exactly ONE active L2 interconnect (the overlay will NOT break a loop)",
        f"{vpc_domains} vPC domain(s); STP present on {n_stp} device(s) in the brownfield",
        "The VXLAN overlay neither forwards nor blocks STP BPDUs, so loop protection across the legacy↔fabric "
        "boundary is NOT automatic. Permit exactly ONE active Layer-2 connection between the brownfield and the "
        "new fabric — a double-sided vPC (vPC+ for a FabricPath brownfield) at the L2/L3 demarcation that keeps "
        "all links forwarding with no loop. Keep the classic network as the STP root, BPDU-filter the "
        "interconnect, and decommission the L2 interconnect once it is no longer needed.",
        "Cisco 'Migrating Classic Ethernet / FabricPath to VXLAN BGP EVPN' white papers; BRKDCN-2951"))

    # CUT-2 — vPC back-to-back coexistence method (evidence: available vPC pairs)
    anchor = (f"available vPC anchor pair(s): {', '.join(vpc_hosts)}" if vpc_hosts
              else "no vPC pair observed — a vPC pair (any fabric VTEP pair) is required for the L2 interconnect")
    guardrails.append(_gw(
        "evpn-cut-vpc-back-to-back-method", "method", "Info",
        "vPC back-to-back coexistence (the documented seamless-migration method)",
        anchor,
        "Cisco's documented method for seamless workload migration: (1) deploy the VXLAN BGP-EVPN fabric "
        "alongside the legacy network; (2) build BOTH a Layer-2 and a Layer-3 interconnect at the legacy L2/L3 "
        "demarcation via a double-sided vPC; (3) migrate workloads — traffic between migrated and not-yet-"
        "migrated endpoints traverses the step-2 interconnects during transition. (A non-seamless per-VLAN/"
        "subnet approach and EVPN Multi-Site / VRF-lite handoffs are documented alternatives.)",
        "BRKDCN-2951 (2025); Cisco classic-Ethernet / FabricPath migration white papers"))

    # ROLL-1 — rollback triggers (derived from the documented failure modes)
    guardrails.append(_gw(
        "evpn-rollback-triggers", "rollback", "High",
        "Rollback triggers (abort conditions for a migrated subnet/wave)",
        "the step-2 L2+L3 interconnect remains in place until the wave is accepted, enabling per-subnet rollback",
        "Abort the wave and move the affected subnet's gateway + VLAN back to the legacy network (across the "
        "still-present interconnect) if ANY of: a gateway-MAC mismatch black-holes a migrated subnet (host ARP "
        "not refreshed); a Layer-2 loop forms (the overlay will not break it); the EVPN control plane (underlay "
        "IGP or iBGP-EVPN) is not Established on a migrated leg; or post-cutover reachability / NRFU fails.",
        "derived from the documented loop / gateway-MAC / control-plane failure modes (migration white papers)"))

    n_high = sum(1 for g in guardrails if g["severity"] in ("Critical", "High"))
    summary = (f"{len(guardrails)} EVPN-migration guardrail(s) ({n_high} High/Critical) — "
               f"target fabric {model_basis}.")
    return {"applicable": True, "model_basis": model_basis, "summary": summary, "guardrails": guardrails}
