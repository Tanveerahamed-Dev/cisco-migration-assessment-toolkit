"""Offline NRFU (Network Ready For Use) verification-command export — orchestration-roadmap frontier.

compute_nrfu_commands(snap) turns the collected pre-cutover snapshot into the canonical FOUR-PHASE NRFU
certification pack a cutover team executes to certify a wave: every case carries the exact READ-ONLY
command to run plus the observed baseline / acceptance text pre-filled from snapshot evidence and
cites the snapshot key the expectation came from (source_key). An observed degraded baseline is an
explicit blocker, never a successful target. Missing evidence is NEVER fabricated: the expected value
is the explicit NOT_OBSERVED abstention marker (coverage-honesty doctrine — absence of evidence is
never health, and a baseline the collection did not capture is recorded at execution, not invented
here).

The canonical four phases:
  I    device-level — show version (expect the collected version), module/inventory presence,
                      environment (where collected)
  II   logical      — interface status for the known-up ports, port-channel member counts,
                      spanning-tree root per VLAN, HSRP/VRRP/GLBP elections, OSPF/EIGRP/BGP
                      and OSPFv3/BGPv6 neighbor sets, CDP adjacency set
  III  service      — ping/traceroute between gateway SVIs within a move-group,
                      DHCP-snooping binding presence (where collected)
  IV   application  — HUMAN-EXECUTED placeholder rows referencing application_intelligence domains

COMPLEMENTS compute_validation_plan (cisco_toolkit/analyze.py): that generator emits the per-wave
POST-cutover spot-check items; this module emits the full four-phase acceptance/certification pack
(NRFU/ATP) with per-device command files. Platform-dialect aware (IOS vs NX-OS) through the same
_is_nxos helper the remediation/validation generators use — no duplicated dialect tables.

READ-ONLY by construction: every emitted command is a show/ping/traceroute-class read;
tests/test_nrfu_export.py re-derives the doctrine read-only grammar and asserts every command matches.
No network egress: pure synthesis over the already-collected snapshot (stdlib only).

Result shape:
  {schema: 'nrfu_commands/1', banner, waves: [{wave_id, devices: [{host, platform_dialect,
   cases: [{id: 'NRFU-W<w>-P<phase>-NNN', phase: 1..4, scope: 'per-site'|'end-to-end',
            command, expected, source_key, evidence_family?, evidence_state?,
            projection_custody?}]}]}], summary}

write_nrfu_pack(snap, out_dir) emits the per-device .txt command files per wave (pure function of the
snapshot). A --nrfu-pack CLI flag is DEFERRED — call write_nrfu_pack directly or consume the published
snap['nrfu_commands'] section.
"""
import os
import re
from collections import Counter
from typing import Dict, List, Optional

from cisco_toolkit.analyze import (
    _bgp_configured_peer_acceptance,
    _fhrp_redundancy_domain_consumer_view,
    _fhrp_configured_group_acceptance,
    _fhrp_configured_group_command,
    _ipv6_routing_consumer_view,
    _uncovered_fhrp_election_blockers,
    _is_nxos,
    summarize_etherchannel_baseline,
    summarize_fhrp_elections,
    summarize_routing_baseline,
    summarize_stp_consistency_baseline,
    _vtp_safety_consumer_view,
    validate_etherchannel_baseline,
)
from cisco_toolkit.bgp_intent import validate_bgp_configured_peer_baseline
from cisco_toolkit.fhrp_intent import validate_fhrp_configured_group_baseline
from cisco_toolkit.parse import _parse_fhrp

NRFU_SCHEMA = "nrfu_commands/1"

# The abstention marker (coverage-honesty): evidence the collection did not capture is recorded at
# execution time by the engineer — never pre-filled with a guess.
NOT_OBSERVED = "[NOT OBSERVED — record baseline at execution]"

UNSCHEDULED_WAVE = "(unscheduled)"

NRFU_BANNER = ("Four-phase NRFU certification pack: run each READ-ONLY command and evaluate the output "
               "against the pre-filled observed baseline / acceptance text; the source key cites the embedded "
               "snapshot evidence. An unexplained deviation is a regression to investigate before sign-off. "
               "A PRE-CUTOVER DEGRADED, PRE-CUTOVER REVIEW, BGP CONFIGURED PEER NOT VERIFIED, or "
               "FHRP CONFIGURED GROUP NOT VERIFIED, or an FHRP REDUNDANCY DOMAIN NOT VERIFIED — "
               "BLOCKER: marker is a blocker to resolve or explicitly "
               "disposition before the window; reproducing a degraded state is not acceptance, and a review "
               "row requires live simultaneous verification. A ROUTING BASELINE NOT VERIFIED, "
               "ETHERCHANNEL BASELINE NOT VERIFIED or VTP SAFETY BASELINE NOT VERIFIED row "
               "requires re-collection before an exact observed baseline can be accepted. An "
               "IPV6 ROUTING BASELINE NOT VERIFIED — BLOCKER: marker likewise requires scoped "
               "OSPFv3/IPv6-unicast BGP re-collection before acceptance. An "
               "STP CONSISTENCY BASELINE NOT VERIFIED row requires re-collection before an exact "
               "observed baseline can be accepted. STP consistency, Routing, IPv6 Routing, FHRP, "
               "EtherChannel, and VTP cases carry evidence_family, "
               "evidence_state, and projection_custody; embedded_unverified means the published receipt "
               "does not cryptographically bind projected peers, FHRP groups, EtherChannel member-state "
               "projections, or STP health projections "
               "to raw captures. "
               "'[NOT OBSERVED …]' rows are honest abstentions — record the baseline at execution. "
               "Phase IV rows are HUMAN-EXECUTED with the application owner.")

_PHASE_ROMAN = {1: "I", 2: "II", 3: "III", 4: "IV"}

_FHRP_PROTOCOLS = ("HSRP", "VRRP", "GLBP")
_ROUTING_PROTOCOLS = ("OSPF", "BGP", "EIGRP")

# Locally observed roles that are unambiguously non-forwarding/faulted even without the peer view.
# Election-wide faults (duplicate/missing leaders, inconsistent identity) come from the shared
# ``summarize_fhrp_elections`` owner below.  A lone Standby/Backup observation is deliberately not
# listed: one device's local view cannot prove the overall election lacks its peer.
_FHRP_DEGRADED_ROLES = {
    "HSRP": frozenset({"INIT", "LEARN"}),
    "VRRP": frozenset({"INIT"}),
    "GLBP": frozenset({"INIT", "DISABLED"}),
}


def _fhrp_command(protocol: str, nxos: bool) -> str:
    """The read-only summary command for the protocol that was actually observed.

    ``fhrp_detail`` is produced only from HSRP detail output, while the per-interface
    ``hsrp_behavior`` compatibility field can carry HSRP, VRRP, or GLBP.  Treating every record as
    HSRP sent VRRP/GLBP operators to the wrong command during the acceptance window.
    """
    if protocol == "VRRP":
        return "show vrrp brief"
    if protocol == "GLBP":
        return "show glbp brief"
    return "show hsrp brief" if nxos else "show standby brief"


def _as_dict(v) -> dict:
    return v if isinstance(v, dict) else {}


def _as_list(v) -> list:
    """The list twin of _as_dict. `x or []` guards None/empty but keeps a TRUTHY non-list (a bare
    `5`/`True`, or the `float('inf')` json.loads makes of a bare JSON `Infinity`), and the next
    `for ... in` raises `TypeError: 'float' object is not iterable` -- aborting the whole NRFU pack
    for one malformed leaf. A malformed list-shaped block reads as absent (its cases abstain), never
    a crash."""
    return v if isinstance(v, list) else []


def _fld(rec, name: str) -> str:
    """Field access tolerant of both the snapshot's dict-shaped interface records and live
    InterfaceData objects (and of sparse snapshots, where empty fields are omitted entirely)."""
    v = rec.get(name, "") if isinstance(rec, dict) else getattr(rec, name, "")
    return str(v).strip() if v is not None else ""


def _port_key(p: str):
    """Natural port ordering: 'Gi1/0/2' before 'Gi1/0/10'."""
    return (p[:2].lower(), [int(x) for x in re.findall(r"\d+", p)])


def _vlan_key(v) -> tuple:
    s = str(v)
    return (0, int(s), "") if s.isdigit() else (1, 0, s)


def _fhrp_group_key(group: str) -> tuple:
    return _vlan_key(group)


def _fhrp_record_key(record: dict) -> tuple:
    return (_port_key(str(record.get("ifname") or "")),
            _fhrp_group_key(str(record.get("group") or "")),
            str(record.get("vip") or ""), str(record.get("state") or "").casefold())


def _fhrp_records(host: str, ifaces: dict, detail) -> Dict[str, List[dict]]:
    """Return observed FHRP rows grouped by their actual subtype.

    The interface projection is the only current source for VRRP/GLBP.  HSRP detail is richer, so a
    complete detail row replaces the matching compatibility-field row; missing detail leaves are
    filled only from that exact matching interface/group observation.  No peer, role, or group count
    is inferred.
    """
    records: Dict[tuple, dict] = {}

    for ifname, iface in sorted(ifaces.items(), key=lambda item: _port_key(str(item[0]))):
        protocol, state, vip, group = _parse_fhrp(_fld(iface, "hsrp_behavior"))
        if protocol not in _FHRP_PROTOCOLS:
            continue
        row = {"protocol": protocol, "ifname": str(ifname), "group": group,
               "state": state, "vip": vip, "source": "interface"}
        records[(protocol, str(ifname).casefold(), group)] = row

    for raw in _as_list(detail):
        if not isinstance(raw, dict):
            continue
        explicit_protocol = _fld(raw, "protocol").upper()
        protocol = explicit_protocol or "HSRP"  # current detail producer parses show standby/HSRP only
        if protocol not in _FHRP_PROTOCOLS:
            continue
        ifname = _fld(raw, "ifname")
        group = _fld(raw, "group")
        if not ifname and not group:
            continue
        key = (protocol, ifname.casefold(), group)
        prior = records.get(key)
        row = {"protocol": protocol, "ifname": ifname, "group": group,
               "state": _fld(raw, "state"), "vip": _fld(raw, "vip"), "source": "detail"}
        if prior:
            used_interface = False
            for field in ("ifname", "group", "state", "vip"):
                if not row[field] and prior.get(field):
                    row[field] = prior[field]
                    used_interface = True
            if used_interface:
                row["source"] = "detail+interface"
        records[key] = row

    grouped = {protocol: [] for protocol in _FHRP_PROTOCOLS}
    for row in records.values():
        grouped[row["protocol"]].append(row)
    for rows in grouped.values():
        rows.sort(key=_fhrp_record_key)
    return grouped


def _fhrp_expected(protocol: str, rows: List[dict], election_findings=()) -> str:
    """Render observed roles and keep every known fault/review gap out of acceptance."""
    if not any(str(row.get("state") or "").strip() for row in rows):
        return NOT_OBSERVED
    rendered = []
    for row in rows:
        ifname = str(row.get("ifname") or "interface not observed")
        group = str(row.get("group") or "group not observed")
        state = str(row.get("state") or "").strip()
        if state:
            expected = f"{protocol} {ifname} grp {group} observed state {state}"
            if row.get("vip"):
                expected += f" (VIP {row['vip']})"
        else:
            expected = f"{protocol} {ifname} grp {group} state {NOT_OBSERVED}"
        rendered.append(expected)

    local_faults = [
        f"{row.get('ifname') or 'interface not observed'} grp "
        f"{row.get('group') or 'group not observed'} state {row.get('state')}"
        for row in rows
        if str(row.get("state") or "").strip().upper()
        in _FHRP_DEGRADED_ROLES.get(protocol, frozenset())
    ]
    structured = [finding for finding in _as_list(election_findings) if isinstance(finding, dict)]
    issues = sorted({str(finding.get("issue") or "").strip() for finding in structured
                     if str(finding.get("issue") or "").strip()})
    faults = local_faults + [issue for issue in issues if issue not in local_faults]
    baseline = "; ".join(rendered)
    if not faults:
        return baseline
    definite = bool(local_faults) or any(finding.get("kind") == "degraded" for finding in structured)
    if definite:
        return ("PRE-CUTOVER DEGRADED — BLOCKER: " + "; ".join(faults)
                + ". Resolve or explicitly disposition before cutover; matching this degraded state "
                  "after cutover is NOT ACCEPTANCE. Observed baseline: " + baseline)
    return ("PRE-CUTOVER REVIEW — BLOCKER: " + "; ".join(faults)
            + ". The one-record-per-SVI, sequential-capture evidence cannot prove a broken pair or a healthy "
              "independent election. Verify intended members simultaneously before acceptance. Observed "
              "baseline: " + baseline)


def _fhrp_source_key(host: str, rows: List[dict], election_findings=()) -> str:
    sources = {str(row.get("source") or "") for row in rows}
    parts = []
    if sources & {"detail", "detail+interface"}:
        parts.append(f"fhrp_detail.{host}")
    if election_findings:
        # Election faults join every observed member on the VLAN, not only this device's row.
        parts.append("interfaces.*.*.hsrp_behavior")
    elif sources & {"interface", "detail+interface"}:
        parts.append(f"interfaces.{host}.*.hsrp_behavior")
    return " + ".join(parts)


def _fhrp_election_issue_index(elections) -> Dict[tuple, List[dict]]:
    """Index shared election findings by the exact observed host/subtype they affect.

    ``summarize_fhrp_elections`` owns cross-device semantics and publishes structured
    ``kind/protocols/hosts`` scope.  That prevents a local degraded HSRP role from contaminating a
    healthy VRRP case in the same review domain.  A malformed row abstains rather than manufacturing
    a blocker.
    """
    index: Dict[tuple, List[dict]] = {}
    for election in _as_list(elections):
        if not isinstance(election, dict) or election.get("status") not in ("review", "degraded"):
            continue
        for finding in _as_list(election.get("findings")):
            if not isinstance(finding, dict):
                continue
            kind = str(finding.get("kind") or "").strip().lower()
            issue = str(finding.get("issue") or "").strip()
            protocols = [str(value or "").strip().upper()
                         for value in _as_list(finding.get("protocols"))]
            hosts = [str(value or "").strip() for value in _as_list(finding.get("hosts"))]
            if kind not in ("review", "degraded") or not issue:
                continue
            for protocol in protocols:
                if protocol not in _FHRP_PROTOCOLS:
                    continue
                for host in hosts:
                    if not host:
                        continue
                    scoped = {"kind": kind, "issue": issue}
                    bucket = index.setdefault((host, protocol), [])
                    if scoped not in bucket:
                        bucket.append(scoped)
    return index


# READ-ONLY enforcement (adversarial-review finding, 2026-07-05): snapshot strings are
# ATTACKER-CONTROLLABLE on the --no-collect path (a JSON value carries \n freely), and an embedded
# newline in an interpolated value would otherwise emit EXECUTABLE continuation lines into the
# .txt pack (a value like '10' + newline + a config-mode verb -> a device write pasted during a
# window). Two layers: every case field is collapsed to ONE physical line at the case() chokepoint,
# and the pack writer independently refuses any command line that is not a single-line
# show/ping/traceroute (it may be fed a pre-published, possibly tampered snap['nrfu_commands'] that
# never passed through case()). The read-only-floor doctrine test greps module source for config-sink
# strings, so this comment deliberately avoids spelling the literal verb.
_READ_ONLY_LINE = re.compile(r"^(show|ping|traceroute)\b[^\r\n]*$", re.IGNORECASE)


def _one_line(v) -> str:
    """Collapse any whitespace run (incl. \\n / \\r / \\t) to a single space — a case field can never
    span physical lines, so no snapshot value can smuggle an executable line into the pack."""
    return re.sub(r"\s+", " ", str(v)).strip()


def _routing_expected(row: dict) -> str:
    """Render the shared routing-baseline verdict without weakening its blocker state.

    The analyzer owns receipt validation, peer/state semantics, and projection custody.  NRFU only
    projects that result into executable read-only cases; it must not reconstruct a healthier target
    from the peer list (the former implementation rewrote OSPF EXSTART and BGP Idle as FULL and
    Established).  Baseline and acceptance text are retained verbatim after whitespace collapsing.
    """
    status = _one_line(row.get("status") or "not_verified").lower()
    baseline = _one_line(row.get("baseline") or "No verified routing baseline was available.")
    acceptance = _one_line(
        row.get("acceptance") or
        "Re-collect and establish a verified baseline before acceptance."
    )
    # The owner deliberately includes the baseline in its acceptance sentence.  Reuse it intact so
    # NRFU cannot drift from validation-plan wording.  The only consumer-owned prefix is the stronger
    # custody label for a missing legacy receipt; REVIEW and DEGRADED already carry their exact marker.
    if status == "not_verified" and not acceptance.startswith(
            "ROUTING BASELINE NOT VERIFIED — BLOCKER:"):
        return f"ROUTING BASELINE NOT VERIFIED — BLOCKER: {acceptance}"
    if acceptance:
        return acceptance
    return baseline


def _etherchannel_expected(row: dict) -> str:
    """Project the producer-owned EtherChannel acceptance text without reclassifying member state."""
    status = _one_line(row.get("status") or "not_verified").lower()
    acceptance = _one_line(
        row.get("acceptance") or
        "Re-collect the platform bundle summary and establish a verified member-state baseline before acceptance."
    )
    if status == "not_verified" and not acceptance.startswith(
            "ETHERCHANNEL BASELINE NOT VERIFIED — BLOCKER:"):
        return f"ETHERCHANNEL BASELINE NOT VERIFIED — BLOCKER: {acceptance}"
    return acceptance


def _bundle_associations(ifaces: dict) -> Dict[str, int]:
    """Return apparent physical-member associations, never an operational ``(P)`` verdict.

    ``interfaces.*.*.port_channel`` is populated from both the summary table and interface
    configuration.  It scopes a subject when the producer-owned EtherChannel baseline is missing,
    but it cannot prove a member is forwarding or bundled.
    """
    bundles: Dict[str, int] = {}
    for port, record in ifaces.items():
        bundle = _fld(record, "port_channel")
        if bundle and not re.match(r"^(Po|Port-?channel)\d+$", str(port), re.IGNORECASE):
            bundles[bundle] = bundles.get(bundle, 0) + 1
    return bundles


def compute_nrfu_commands(snap: Optional[dict] = None) -> dict:
    """The four-phase NRFU certification pack synthesized from the snapshot (see module docstring).
    Deterministic; read-only; tolerant of empty / oddly-typed snapshot sections. Every expected value
    either carries collected evidence (with its source_key) or is the NOT_OBSERVED abstention."""
    s = snap if isinstance(snap, dict) else {}
    devices = _as_dict(s.get("devices"))
    interfaces = _as_dict(s.get("interfaces"))
    move_groups = s.get("move_groups") if isinstance(s.get("move_groups"), list) else []
    stp_roots = _as_dict(s.get("stp_roots"))
    rn = _as_dict(s.get("routing_neighbors"))
    fhrp_detail = _as_dict(s.get("fhrp_detail"))
    app = _as_dict(s.get("application_intelligence"))
    # DHCP-snooping bindings are collected ('show ip dhcp snooping binding') but not published as a
    # snapshot section today — read the forward-compatible key so a future publish pre-fills the
    # expected count; until then the case abstains honestly.
    dhcp = _as_dict(s.get("dhcp_snooping"))

    # One neutral routing owner validates the exact assessability receipt, normalizes peer states,
    # and preserves the embedded projection's custody boundary.  Index its bounded rows once; every
    # output below is a projection of that owner rather than a second health implementation.
    routing_baseline = summarize_routing_baseline(rn, s.get("protocol_assessability"))
    routing_view = _as_dict(routing_baseline)
    routing_rows = _as_list(routing_view.get("rows"))
    routing_custody = _fld(routing_view, "projection_custody")
    routing_by_host: Dict[str, List[dict]] = {}
    observed_bgp_by_host: Dict[str, List[dict]] = {}
    for row in routing_rows:
        if not isinstance(row, dict):
            continue
        host = _fld(row, "switch")
        if host:
            if _fld(row, "protocol") == "BGP":
                observed_bgp_by_host.setdefault(host, []).append(row)
            else:
                routing_by_host.setdefault(host, []).append(row)

    # STP root placement and STP consistency are independent claims.  Root rows below retain the
    # exact observed bridge identity from ``stp_roots``; this shared owner separately decides whether
    # the primary and inconsistent-port evidence can authorize a consistency acceptance target.
    # Project its row verbatim so NRFU cannot recreate a zero count from display prose.
    stp_consistency = summarize_stp_consistency_baseline(
        s.get("protocol_health"), s.get("protocol_assessability"),
        all_interfaces=s.get("interfaces"), stp_roots=s.get("stp_roots"),
    )
    stp_consistency_by_host: Dict[str, List[dict]] = {}
    for row in _as_list(_as_dict(stp_consistency).get("rows")):
        if not isinstance(row, dict):
            continue
        host = _fld(row, "switch")
        if host:
            stp_consistency_by_host.setdefault(host, []).append(row)

    # VTP safety is current-run authority only.  Persisted or failed receipts contribute no
    # mode/domain/revision leaves; the shared consumer scopes only an independently evidenced VTP
    # subject and emits static NOT VERIFIED copy.
    vtp_key_present = "vtp_safety_baseline" in s
    vtp_by_host: Dict[str, List[dict]] = {}
    if vtp_key_present:
        vtp_view = _vtp_safety_consumer_view(
            s.get("vtp_safety_baseline"),
            s.get("protocol_health"),
            s.get("protocol_assessability"),
            s.get("vtp_safety_subject_scope"),
        )
        for row in _as_list(vtp_view.get("rows")):
            if not isinstance(row, dict):
                continue
            host = _fld(row, "switch")
            if host:
                vtp_by_host.setdefault(host, []).append(row)

    # OSPFv3 and IPv6-unicast BGP have a distinct current-run authority
    # boundary.  The shared consumer returns either validated owner rows or
    # fixed, leaf-free scope abstentions; this exporter never reads an
    # unvalidated peer, state, command, acceptance, source, or custody leaf.
    ipv6_routing_key_present = "ipv6_routing_adjacency_baseline" in s
    ipv6_routing_by_host: Dict[str, List[dict]] = {}
    if ipv6_routing_key_present:
        ipv6_routing_view = _ipv6_routing_consumer_view(
            s.get("ipv6_routing_adjacency_baseline"),
            s.get("ipv6_routing_subject_scope"),
        )
        for row in _as_list(ipv6_routing_view.get("rows")):
            if not isinstance(row, dict):
                continue
            host = _fld(row, "switch")
            if host:
                ipv6_routing_by_host.setdefault(host, []).append(row)

    # Positive BGP acceptance requires the producer's source-bound current-run marker.  A legacy,
    # absent, phase-failed, or tampered baseline may scope a NOT VERIFIED case but can never reuse an
    # observed numeric prefix count as an Established acceptance target.
    bgp_key_present = "bgp_configured_peer_baseline" in s
    bgp_view = validate_bgp_configured_peer_baseline(
        s.get("bgp_configured_peer_baseline"), require_current_run=True)
    bgp_authorized = (
        bgp_view.get("valid") is True
        and bgp_view.get("source_bound") is True
        and isinstance(bgp_view.get("index"), dict)
    )
    bgp_contract = _as_dict(bgp_view.get("baseline")) if bgp_authorized else {}
    bgp_by_host: Dict[str, List[dict]] = {}
    if bgp_authorized:
        for row in _as_list(bgp_view.get("rows")):
            if not isinstance(row, dict):
                continue
            host = _fld(row, "switch")
            if host:
                bgp_by_host.setdefault(host, []).append(row)

    bgp_blocker_states = {"degraded", "review", "not_verified"}
    bgp_verdict = _fld(bgp_contract, "verdict").upper()
    bgp_has_blocker = any(
        _fld(row, "status") in bgp_blocker_states
        for rows in bgp_by_host.values() for row in rows
    )
    bgp_contract_unattributed = (
        bgp_authorized and bgp_verdict in {"BLOCKED", "INDETERMINATE"}
        and not bgp_has_blocker
    )
    bgp_subject_coverage_hosts = {
        _fld(row, "switch")
        for row in _as_list(bgp_contract.get("coverage"))
        if isinstance(row, dict) and row.get("subject") is True
        and _fld(row, "status").lower() in {"degraded", "review", "not_verified"}
        and _fld(row, "switch")
    }

    # Configured FHRP groups have the same process-local authorization boundary as configured BGP
    # peers.  Only validator-owned current-run rows can become acceptance targets; persisted,
    # phase-failed, or tampered artifacts contribute no group/VIP/state leaves.
    fhrp_key_present = "fhrp_configured_group_baseline" in s
    fhrp_view = validate_fhrp_configured_group_baseline(
        s.get("fhrp_configured_group_baseline"), require_current_run=True)
    fhrp_authorized = (
        fhrp_view.get("valid") is True
        and fhrp_view.get("source_bound") is True
        and isinstance(fhrp_view.get("index"), dict)
    )
    fhrp_contract = _as_dict(fhrp_view.get("baseline")) if fhrp_authorized else {}
    fhrp_by_host: Dict[str, List[dict]] = {}
    if fhrp_authorized:
        for row in _as_list(fhrp_view.get("rows")):
            if not isinstance(row, dict):
                continue
            host = _fld(row, "switch")
            if host:
                fhrp_by_host.setdefault(host, []).append(row)

    fhrp_blocker_states = {"degraded", "review", "not_verified"}
    fhrp_verdict = _fld(fhrp_contract, "verdict").upper()
    fhrp_has_blocker = any(
        _fld(row, "status") in fhrp_blocker_states
        for rows in fhrp_by_host.values() for row in rows
    )
    fhrp_contract_unattributed = (
        fhrp_authorized and fhrp_verdict in {"BLOCKED", "INDETERMINATE"}
        and not fhrp_has_blocker
    )
    fhrp_blocking_coverage = {
        (_fld(row, "switch"), _fld(row, "protocol").upper())
        for row in _as_list(fhrp_contract.get("coverage"))
        if isinstance(row, dict)
        and _fld(row, "status").lower() in {"degraded", "review", "not_verified"}
        and _fld(row, "switch")
        and _fld(row, "protocol").upper() in _FHRP_PROTOCOLS
    }

    # Cross-switch redundancy domains are a separate evidence family from local configured groups.
    # Current-run rows are projected exactly; a present-but-rejected/embedded/phase-failed receipt is
    # replaced only by safe current-interface scope identities and static NOT VERIFIED leaves.
    fhrp_domain_key_present = "fhrp_redundancy_domain_baseline" in s
    fhrp_domain_by_host: Dict[str, List[dict]] = {}
    if fhrp_domain_key_present:
        fhrp_domain_view = _fhrp_redundancy_domain_consumer_view(
            s.get("fhrp_redundancy_domain_baseline"),
            interfaces,
            s.get("fhrp_configured_group_baseline"),
        )
        for row in _as_list(fhrp_domain_view.get("rows")):
            if not isinstance(row, dict):
                continue
            host = _fld(row, "switch")
            if host:
                fhrp_domain_by_host.setdefault(host, []).append(row)

    # EtherChannel acceptance rows are caller-controlled snapshot content until the shared owner
    # recomputes them from BOTH published sources.  Only the validator's index is authorized: a forged
    # ``assessed`` label or healthy acceptance string must never outrank SD/D member evidence, and a
    # structurally valid baseline copied from a different projection must fail the same closed gate.
    etherchannel_view = validate_etherchannel_baseline(
        s.get("etherchannel_baseline"),
        projection=s.get("etherchannel_projection"),
        protocol_assessability=s.get("protocol_assessability"),
        devices=devices,
    )
    etherchannel_authorized = (
        etherchannel_view.get("valid") is True
        and etherchannel_view.get("source_bound") is True
        and isinstance(etherchannel_view.get("index"), dict)
    )
    etherchannel_by_host: Dict[str, dict] = (
        etherchannel_view["index"] if etherchannel_authorized else {}
    )
    # Artifact rejection must not erase a real source-owned subject.  Recompute the total producer
    # from the separately published projection+receipt solely to scope a static NOT VERIFIED case;
    # no acceptance, status, source locator, or other leaf from the rejected baseline is reused.
    etherchannel_fallback_by_host: Dict[str, dict] = {}
    if not etherchannel_authorized:
        source_owner = summarize_etherchannel_baseline(
            s.get("etherchannel_projection"),
            s.get("protocol_assessability"),
            devices=devices,
        )
        for row in _as_list(_as_dict(source_owner).get("rows")):
            if not isinstance(row, dict):
                continue
            host = _fld(row, "switch")
            if host and host not in etherchannel_fallback_by_host:
                etherchannel_fallback_by_host[host] = row

    apparent_bundles = {
        str(host): _bundle_associations(_as_dict(ifaces))
        for host, ifaces in interfaces.items()
    }
    apparent_bundles = {host: bundles for host, bundles in apparent_bundles.items() if bundles}

    # One shared, cross-device election view.  A supplied configured-group contract retains only
    # uncovered legacy blocker members; exact source-bound configured blockers own their duplicate,
    # while mixed protocol/group/VIP and wider domain review remains additive.
    fhrp_elections = summarize_fhrp_elections(interfaces)
    fhrp_election_issues = _fhrp_election_issue_index(fhrp_elections)
    fhrp_legacy_blockers_by_host: Dict[str, List[tuple]] = {}
    if fhrp_key_present:
        configured_fhrp_rows = [
            row for rows in fhrp_by_host.values() for row in rows
            if isinstance(row, dict)
        ]
        for election, member in _uncovered_fhrp_election_blockers(
                fhrp_elections, configured_fhrp_rows):
            host = _fld(member, "host")
            if host:
                fhrp_legacy_blockers_by_host.setdefault(host, []).append(
                    (election, member)
                )

    hosts = sorted(
        set(devices) | set(interfaces) | set(routing_by_host)
        | set(observed_bgp_by_host) | set(bgp_by_host)
        | set(fhrp_by_host) | {host for host, _protocol in fhrp_blocking_coverage}
        | set(fhrp_domain_by_host)
        | set(etherchannel_by_host) | set(etherchannel_fallback_by_host) | set(apparent_bundles)
        | set(stp_consistency_by_host) | set(vtp_by_host) | set(ipv6_routing_by_host)
    )
    if bgp_key_present and not bgp_authorized:
        # A persisted projection cannot prove *absence* either: the process-local current-run marker is
        # the only positive authorization boundary.  Scope one static blocker to every known host rather
        # than copying peer/AS/state/acceptance leaves from an unbound or tampered artifact.
        bgp_fallback_hosts = set(hosts)
    elif bgp_contract_unattributed:
        # Valid global INDETERMINATE is scoped by the producer's per-host subject coverage; never
        # turn an unrelated pure-L2 host into a BGP blocker.
        bgp_fallback_hosts = set(bgp_subject_coverage_hosts)
    elif not bgp_authorized:
        # Pre-feature snapshots remain useful, but every actually observed BGP subject fails closed.
        bgp_fallback_hosts = set(observed_bgp_by_host)
    else:
        bgp_fallback_hosts = set()

    if fhrp_key_present and not fhrp_authorized:
        # The present-but-rejected artifact cannot prove absence.  Scope a static blocker to known
        # hosts without copying any unvalidated protocol/group/VIP/runtime leaf.
        fhrp_fallback_subjects = {(host, "FHRP") for host in hosts}
    elif fhrp_contract_unattributed:
        fhrp_fallback_subjects = set(fhrp_blocking_coverage)
    else:
        fhrp_fallback_subjects = set()

    # host -> wave label ("Group N", enumerated exactly like compute_validation_plan /
    # compute_migration_readiness). A host in no multi-switch group still gets its certification
    # cases under "(unscheduled)" so nothing is silently skipped (coverage-honesty).
    wave_of: Dict[str, str] = {}
    for gi, g in enumerate(move_groups, 1):
        for h in _as_list(g.get("switches")) if isinstance(g, dict) else []:
            wave_of.setdefault(str(h), f"Group {gi}")
    wave_hosts: Dict[str, List[str]] = {}
    for h in hosts:
        wave_hosts.setdefault(wave_of.get(h, UNSCHEDULED_WAVE), []).append(h)
    ordered = [f"Group {gi}" for gi in range(1, len(move_groups) + 1) if f"Group {gi}" in wave_hosts]
    if UNSCHEDULED_WAVE in wave_hosts:
        ordered.append(UNSCHEDULED_WAVE)

    def _dialect(host: str) -> str:
        plat = _fld(_as_dict(devices.get(host)), "platform") or "ios"
        return "nxos" if _is_nxos(plat) else "ios"

    waves: List[dict] = []
    for label in ordered:
        wno = int(re.search(r"(\d+)", label).group(1)) if label != UNSCHEDULED_WAVE else 0
        whosts = wave_hosts[label]
        cases_by_host: Dict[str, List[dict]] = {}
        seq = 0

        def case(host, phase, scope, command, expected, source_key, *,
                 evidence_family="", evidence_state="", projection_custody="",
                 bgp_metadata: Optional[dict] = None,
                 fhrp_metadata: Optional[dict] = None,
                 fhrp_domain_metadata: Optional[dict] = None,
                 vtp_metadata: Optional[dict] = None):
            nonlocal seq
            seq += 1
            record = {"id": f"NRFU-W{wno}-P{phase}-{seq:03d}", "phase": phase, "scope": scope,
                      "command": _one_line(command), "expected": _one_line(expected),
                      "source_key": _one_line(source_key)}
            if evidence_family:
                record["evidence_family"] = _one_line(evidence_family)
            if evidence_state:
                record["evidence_state"] = _one_line(evidence_state)
            if projection_custody:
                record["projection_custody"] = _one_line(projection_custody)
            if bgp_metadata is not None:
                record.update({
                    "peer": _one_line(bgp_metadata.get("peer")),
                    "peer_key": _one_line(bgp_metadata.get("peer_key")),
                    "local_as": _one_line(bgp_metadata.get("local_as")),
                    "configured_remote_as": _one_line(
                        bgp_metadata.get("configured_remote_as")),
                    "activation": _one_line(bgp_metadata.get("activation")),
                    "runtime_observed": bgp_metadata.get("runtime_observed") is True,
                    "runtime_remote_as": _one_line(bgp_metadata.get("runtime_remote_as")),
                    "runtime_state_raw": _one_line(bgp_metadata.get("runtime_state_raw")),
                    "runtime_state": _one_line(bgp_metadata.get("runtime_state")),
                    "bgp_scope": _one_line(bgp_metadata.get("scope")),
                })
            if fhrp_metadata is not None:
                record.update({
                    "protocol": _one_line(fhrp_metadata.get("protocol")),
                    "interface": _one_line(fhrp_metadata.get("interface")),
                    "group": _one_line(fhrp_metadata.get("group")),
                    "group_key": _one_line(fhrp_metadata.get("group_key")),
                    "configured": fhrp_metadata.get("configured") is True,
                    "configured_vip": _one_line(fhrp_metadata.get("configured_vip")),
                    "activation": _one_line(fhrp_metadata.get("activation")),
                    "runtime_observed": fhrp_metadata.get("runtime_observed") is True,
                    "runtime_vip": _one_line(fhrp_metadata.get("runtime_vip")),
                    "runtime_state_raw": _one_line(fhrp_metadata.get("runtime_state_raw")),
                    "runtime_state": _one_line(fhrp_metadata.get("runtime_state")),
                    "fhrp_scope": _one_line(fhrp_metadata.get("scope")),
                })
            if fhrp_domain_metadata is not None:
                # Preserve every producer-owned flat leaf verbatim.  The NRFU envelope adds only its
                # case identity/phase/scope and the standard evidence aliases.
                record.update(dict(fhrp_domain_metadata))
                record["expected"] = fhrp_domain_metadata.get("acceptance", "")
                record["evidence_family"] = "FHRP Domain"
                record["evidence_state"] = fhrp_domain_metadata.get("status", "not_verified")
                record["projection_custody"] = fhrp_domain_metadata.get(
                    "projection_custody", "embedded_unverified")
            if vtp_metadata is not None:
                record.update({
                    "vtp_mode": _one_line(vtp_metadata.get("mode")),
                    "vtp_mode_present": vtp_metadata.get("mode_present") is True,
                    "vtp_domain": _one_line(vtp_metadata.get("domain")),
                    "vtp_domain_present": vtp_metadata.get("domain_present") is True,
                    "vtp_revision": vtp_metadata.get("revision", 0),
                    "vtp_revision_present": vtp_metadata.get("revision_present") is True,
                    "vtp_version": _one_line(vtp_metadata.get("version")),
                    "vtp_version_present": vtp_metadata.get("version_present") is True,
                })
            cases_by_host.setdefault(host, []).append(record)

        for h in whosts:
            dev = _as_dict(devices.get(h))
            ifaces = _as_dict(interfaces.get(h))
            nx = _dialect(h) == "nxos"

            # ---- Phase I: device level -------------------------------------------------------
            ver = _fld(dev, "sw_version")
            case(h, 1, "per-site", "show version",
                 f"Software version {ver} (unchanged from baseline)" if ver else NOT_OBSERVED,
                 f"devices.{h}.sw_version")
            inv = [p for p in (f"chassis {_fld(dev, 'model')}" if _fld(dev, "model") else "",
                               f"serial {_fld(dev, 'serial_number')}" if _fld(dev, "serial_number") else "")
                   if p]
            case(h, 1, "per-site", "show module" if nx else "show inventory",
                 (", ".join(inv) + " present") if inv else NOT_OBSERVED,
                 f"devices.{h}.model")
            envp = [f"{lbl} {_fld(dev, key)}" for lbl, key in
                    (("PS", "ps_status"), ("fans", "fan_status"), ("temp", "temperature_status"))
                    if _fld(dev, key)]
            case(h, 1, "per-site", "show environment" if nx else "show environment all",
                 "; ".join(envp) if envp else NOT_OBSERVED,
                 f"devices.{h}.ps_status")

            # ---- Phase II: logical topology --------------------------------------------------
            up = sorted((p for p, d in ifaces.items()
                         if _fld(d, "status").lower() in ("connected", "up")), key=_port_key)
            shown = ", ".join(up[:12]) + (f", … +{len(up) - 12} more" if len(up) > 12 else "")
            case(h, 2, "per-site", "show interface status",
                 f"{len(up)} known-up port(s) connected: {shown}" if up else NOT_OBSERVED,
                 f"interfaces.{h}")
            etherchannel = etherchannel_by_host.get(h)
            if etherchannel:
                ec_status = _fld(etherchannel, "status") or "not_verified"
                ec_command = _fld(etherchannel, "command") or (
                    "show port-channel summary" if nx else "show etherchannel summary"
                )
                ec_source = _fld(etherchannel, "source_key") or f"etherchannel_baseline.rows[{h}]"
                case(
                    h, 2, "per-site", ec_command, _etherchannel_expected(etherchannel), ec_source,
                    evidence_family="EtherChannel", evidence_state=ec_status,
                    projection_custody=_fld(etherchannel, "projection_custody"),
                )
            elif apparent_bundles.get(h) or h in etherchannel_fallback_by_host:
                # Legacy/malformed snapshots can still carry apparent interface associations.  They
                # scope an operator check, but cannot authorize an operational member-state target.
                # A valid source owner also scopes a subject when the artifact itself was forged and
                # the interface association projection is empty; its acceptance leaves remain unused.
                if apparent_bundles.get(h):
                    subject = "apparent interface association: " + "; ".join(
                        f"{bundle}: {count} associated physical member(s)"
                        for bundle, count in sorted(apparent_bundles[h].items())
                    )
                    boundary = "Association is not proof of (P)/bundled state."
                else:
                    subject = "projection/receipt-owned EtherChannel subject"
                    boundary = "The rejected baseline's acceptance and source leaves were not used."
                fallback_row = etherchannel_fallback_by_host.get(h, {})
                fallback_command = _fld(fallback_row, "command")
                if fallback_command not in {
                        "show etherchannel summary", "show port-channel summary"}:
                    fallback_command = "show port-channel summary" if nx else "show etherchannel summary"
                case(
                    h, 2, "per-site",
                    fallback_command,
                    "ETHERCHANNEL BASELINE NOT VERIFIED — BLOCKER: "
                    f"{subject} on {h}. No producer-owned "
                    "source-bound etherchannel_baseline/1 row authorizes an operational member-state "
                    "baseline. "
                    f"Re-collect the platform summary before acceptance. {boundary}",
                    (f"interfaces.{h}.*.port_channel + etherchannel_baseline + "
                     "etherchannel_projection + protocol_assessability"),
                    evidence_family="EtherChannel", evidence_state="not_verified",
                    projection_custody="embedded_unverified",
                )
            for stp_consistency_row in stp_consistency_by_host.get(h, []):
                case(
                    h, 2, "per-site",
                    _fld(stp_consistency_row, "command"),
                    _fld(stp_consistency_row, "acceptance"),
                    _fld(stp_consistency_row, "source_key"),
                    evidence_family="STP",
                    evidence_state=_fld(stp_consistency_row, "status"),
                    projection_custody=_fld(stp_consistency_row, "projection_custody"),
                )
            for vtp_row in vtp_by_host.get(h, []):
                case(
                    h, 2, "per-site",
                    _fld(vtp_row, "command") or "show vtp status",
                    _fld(vtp_row, "acceptance"),
                    _fld(vtp_row, "source_key") or "vtp_safety_baseline",
                    evidence_family="VTP",
                    evidence_state=_fld(vtp_row, "status") or "not_verified",
                    projection_custody=_fld(vtp_row, "projection_custody"),
                    vtp_metadata=vtp_row,
                )
            for ipv6_routing_row in ipv6_routing_by_host.get(h, []):
                case(
                    h, 2, "per-site",
                    _fld(ipv6_routing_row, "command"),
                    _fld(ipv6_routing_row, "acceptance"),
                    _fld(ipv6_routing_row, "source_key"),
                    evidence_family="IPv6 Routing",
                    evidence_state=_fld(ipv6_routing_row, "status"),
                    projection_custody=_fld(
                        ipv6_routing_row, "projection_custody"),
                )
            for vlan, info in sorted(_as_dict(stp_roots.get(h)).items(), key=lambda kv: _vlan_key(kv[0])):
                if not isinstance(info, dict):
                    continue
                prio = info.get("root_priority")
                root = str(info.get("root_address") or "").strip()
                if info.get("is_root"):
                    exp = (f"This bridge is the root for VLAN {vlan}"
                           + (f" (priority {prio})" if prio not in (None, "") else ""))
                elif root:
                    exp = (f"Root bridge {root} for VLAN {vlan}"
                           + (f" (priority {prio})" if prio not in (None, "") else "") + " — unchanged")
                else:
                    exp = NOT_OBSERVED
                # the VLAN token rides a COMMAND template: restrict it to identifier characters (a
                # key that sanitizes differently is snapshot corruption, not a VLAN — skip, don't guess)
                vtok = re.sub(r"[^\w.-]", "", str(vlan))
                if not vtok or vtok != str(vlan):
                    continue
                case(h, 2, "per-site", f"show spanning-tree vlan {vtok}", exp, f"stp_roots.{h}.{vtok}")
            if not fhrp_key_present:
                # Legacy snapshots retain their full observed subtype projection.  With a configured
                # contract, the branch below emits configured rows plus only uncovered observed
                # blockers, so healthy compatibility rows cannot duplicate acceptance targets.
                for protocol, rows in _fhrp_records(h, ifaces, fhrp_detail.get(h)).items():
                    if not rows:
                        continue
                    election_findings = fhrp_election_issues.get((h, protocol), ())
                    case(h, 2, "per-site", _fhrp_command(protocol, nx),
                         _fhrp_expected(protocol, rows, election_findings),
                         _fhrp_source_key(h, rows, election_findings))
            else:
                for fhrp in fhrp_by_host.get(h, []):
                    status = _fld(fhrp, "status")
                    protocol = _fld(fhrp, "protocol").upper()
                    command = _fld(fhrp, "command") or _fhrp_configured_group_command(
                        protocol, nx)
                    case(
                        h, 2, "per-site", command,
                        _fhrp_configured_group_acceptance(fhrp),
                        _fld(fhrp, "source_key") or "fhrp_configured_group_baseline",
                        evidence_family="FHRP", evidence_state=status,
                        projection_custody=_fld(fhrp, "projection_custody"),
                        fhrp_metadata=fhrp,
                    )
                for election, member in fhrp_legacy_blockers_by_host.get(h, []):
                    protocol = _fld(member, "protocol").upper()
                    interface = _fld(member, "interface")
                    group = _fld(member, "group")
                    state = _fld(member, "role")
                    vip = _fld(member, "vip")
                    status = _fld(member, "status").lower()
                    applicable_findings = []
                    for finding in _as_list(election.get("findings")):
                        if not isinstance(finding, dict):
                            continue
                        protocols = {
                            str(value or "").strip().upper()
                            for value in _as_list(finding.get("protocols"))
                        }
                        hosts = {
                            str(value or "").strip()
                            for value in _as_list(finding.get("hosts"))
                        }
                        if protocol in protocols and h in hosts:
                            applicable_findings.append({
                                "kind": _fld(finding, "kind").lower(),
                                "issue": _fld(finding, "issue"),
                            })
                    observed = {
                        "protocol": protocol,
                        "ifname": interface,
                        "group": group,
                        "state": state,
                        "vip": vip,
                        "source": "interface",
                    }
                    metadata = {
                        "protocol": protocol,
                        "interface": interface,
                        "group": group,
                        "group_key": f"observed-election:{protocol}:{interface}:{group}",
                        "configured": False,
                        "configured_vip": "",
                        "activation": "observed",
                        "runtime_observed": True,
                        "runtime_vip": vip,
                        "runtime_state_raw": state,
                        "runtime_state": state.upper(),
                        "scope": "observed one-record-per-SVI election",
                    }
                    case(
                        h, 2, "per-site", _fhrp_command(protocol, nx),
                        _fhrp_expected(protocol, [observed], applicable_findings),
                        f"interfaces.{h}.{interface}.hsrp_behavior",
                        evidence_family="FHRP", evidence_state=status,
                        projection_custody="embedded_unverified",
                        fhrp_metadata=metadata,
                    )
                fallback_protocols = sorted(
                    protocol for host, protocol in fhrp_fallback_subjects if host == h
                )
                for protocol in fallback_protocols:
                    command_protocol = protocol if protocol in _FHRP_PROTOCOLS else "HSRP"
                    placeholder = {
                        "protocol": protocol, "interface": "", "group": "", "group_key": "",
                        "configured": False, "configured_vip": "", "activation": "not_verified",
                        "runtime_observed": False, "runtime_vip": "", "runtime_state_raw": "",
                        "runtime_state": "NOT_VERIFIED",
                        "scope": "default IPv4 direct-literal local configured group",
                        "status": "not_verified",
                    }
                    case(
                        h, 2, "per-site",
                        _fhrp_configured_group_command(command_protocol, nx),
                        "FHRP CONFIGURED GROUP NOT VERIFIED — BLOCKER: No validated, "
                        "source-bound current-run configured-group baseline authorizes a positive "
                        "FHRP acceptance target. Re-collect running-config and the matching "
                        "HSRP/VRRP/GLBP summary before cutover.",
                        "fhrp_configured_group_baseline",
                        evidence_family="FHRP", evidence_state="not_verified",
                        projection_custody="embedded_unverified",
                        fhrp_metadata=placeholder,
                    )
            for domain_row in fhrp_domain_by_host.get(h, []):
                case(
                    h, 2, "per-site",
                    domain_row.get("command"),
                    domain_row.get("acceptance"),
                    domain_row.get("source_key"),
                    evidence_family="FHRP Domain",
                    evidence_state=domain_row.get("status"),
                    projection_custody=domain_row.get("projection_custody"),
                    fhrp_domain_metadata=domain_row,
                )
            for routing in routing_by_host.get(h, []):
                case(h, 2, "per-site", routing.get("command"), _routing_expected(routing),
                     routing.get("source_key"), evidence_family=routing.get("protocol"),
                     evidence_state=routing.get("status"),
                     projection_custody=routing.get("projection_custody") or routing_custody)
            for bgp in bgp_by_host.get(h, []):
                status = _fld(bgp, "status")
                command = _fld(bgp, "command") or (
                    "show bgp ipv4 unicast summary" if nx else "show ip bgp summary"
                )
                case(
                    h, 2, "per-site", command, _bgp_configured_peer_acceptance(bgp),
                    _fld(bgp, "source_key") or "bgp_configured_peer_baseline",
                    evidence_family="BGP", evidence_state=status,
                    projection_custody=_fld(bgp, "projection_custody"),
                    bgp_metadata=bgp,
                )
            if h in bgp_fallback_hosts:
                fallback_rows: List[dict] = []
                # Only the absence of a baseline key (a legacy snapshot) permits the already validated
                # observed-routing owner to scope individual peer identities.  A present-but-rejected
                # configured-peer artifact contributes no leaves whatsoever.
                if not bgp_key_present and not bgp_contract_unattributed:
                    for observed in observed_bgp_by_host.get(h, []):
                        peers = _as_list(observed.get("peers"))
                        for peer in peers:
                            if not isinstance(peer, dict):
                                continue
                            fallback_rows.append({
                                "peer": _fld(peer, "peer"),
                                "peer_key": _fld(peer, "peer_key"),
                                "local_as": "",
                                "configured_remote_as": "",
                                "activation": "not_verified",
                                "runtime_observed": True,
                                "runtime_remote_as": _fld(peer, "remote_as"),
                                "runtime_state_raw": _fld(peer, "state_raw"),
                                "runtime_state": _fld(peer, "state"),
                                "scope": "default/global IPv4-unicast literal-peer",
                                "status": "not_verified",
                            })
                if not fallback_rows:
                    fallback_rows = [{
                        "peer": "", "peer_key": "", "local_as": "",
                        "configured_remote_as": "", "activation": "not_verified",
                        "runtime_observed": False, "runtime_remote_as": "",
                        "runtime_state_raw": "", "runtime_state": "NOT_VERIFIED",
                        "scope": "default/global IPv4-unicast literal-peer",
                        "status": "not_verified",
                    }]
                for fallback in fallback_rows:
                    peer_text = _fld(fallback, "peer")
                    subject = f" for observed peer {peer_text}" if peer_text else ""
                    case(
                        h, 2, "per-site",
                        "show bgp ipv4 unicast summary" if nx else "show ip bgp summary",
                        "BGP CONFIGURED PEER NOT VERIFIED — BLOCKER: No validated, source-bound "
                        f"current-run configured-peer denominator authorizes a BGP acceptance target{subject}. "
                        "Re-collect running-config and the scoped default/global IPv4-unicast summary; do "
                        "not infer Established from a numeric summary token.",
                        (f"routing_neighbors.{h}.bgp + bgp_configured_peer_baseline"
                         if peer_text else "bgp_configured_peer_baseline"),
                        evidence_family="BGP", evidence_state="not_verified",
                        projection_custody="embedded_unverified", bgp_metadata=fallback,
                    )
            adj = sorted(((p, _fld(d, "cdp_neighbor"), _fld(d, "neighbor_port"))
                          for p, d in ifaces.items() if _fld(d, "cdp_neighbor")),
                         key=lambda t: _port_key(t[0]))
            case(h, 2, "per-site", "show cdp neighbors",
                 (f"{len(adj)} adjacency(ies): "
                  + ", ".join(f"{p} -> {n}" + (f" ({np})" if np else "") for p, n, np in adj))
                 if adj else NOT_OBSERVED,
                 f"interfaces.{h}.*.cdp_neighbor")

            # ---- Phase III (per-site half): DHCP-snooping binding presence -------------------
            if any(_fld(d, "switchport_mode").lower() == "access" for d in ifaces.values()):
                n_bind = dhcp.get(h)
                case(h, 3, "per-site", "show ip dhcp snooping binding",
                     f"{n_bind} DHCP-snooping binding(s) re-learned"
                     if isinstance(n_bind, int) else NOT_OBSERVED,
                     f"dhcp_snooping.{h}")

        # ---- Phase III (end-to-end half): gateway-SVI reachability within the move-group ----
        svis: List[tuple] = []
        for h in whosts:
            for p, d in _as_dict(interfaces.get(h)).items():
                m = re.match(r"^Vlan(\d+)$", str(p), re.IGNORECASE)
                ip = (_fld(d, "svi_ip").split() or [""])[0]
                if m and ip:
                    svis.append((h, int(m.group(1)), ip))
        svis.sort()
        if len(svis) >= 2:
            hub_h, hub_v, hub_ip = svis[0]     # hub-and-spoke keeps the case count linear in SVIs
            hub_key = f"interfaces.{hub_h}.Vlan{hub_v}.svi_ip"
            need_trace = True
            for h2, v2, ip2 in svis[1:]:
                case(h2, 3, "end-to-end", f"ping {hub_ip}",
                     f"Success rate is 100 percent — gateway SVI Vlan{hub_v} on {hub_h} ({hub_ip}) "
                     f"reachable from Vlan{v2}", hub_key)
                if need_trace and h2 != hub_h:  # one representative path proof per wave
                    case(h2, 3, "end-to-end", f"traceroute {hub_ip}",
                         f"Completes; final hop {hub_ip} (gateway SVI Vlan{hub_v} on {hub_h})", hub_key)
                    need_trace = False

        # ---- Phase IV: application domains (HUMAN-EXECUTED placeholders) --------------------
        domains = app.get("domains") if isinstance(app.get("domains"), list) else []
        wave_set = set(whosts)
        for dom in domains:
            if not isinstance(dom, dict):
                continue
            touch = sorted({str(x) for x in _as_list(dom.get("switches"))} & wave_set)
            if not touch:
                continue
            name = str(dom.get("domain") or dom.get("id") or "application domain")
            tier = str(dom.get("tier") or "").strip()
            case(touch[0], 4, "end-to-end",
                 f"ping <representative '{name}' application endpoint>",
                 f"[HUMAN-EXECUTED] Application owner certifies '{name}'"
                 + (f" (tier {tier})" if tier else "")
                 + " end-to-end after cutover; attach the evidence to the wave sign-off",
                 f"application_intelligence.domains[{dom.get('id', '')}]")

        waves.append({"wave_id": label,
                      "devices": [{"host": h, "platform_dialect": _dialect(h),
                                   "cases": cases_by_host[h]}
                                  for h in whosts if h in cases_by_host]})

    all_cases = [c for w in waves for d in w["devices"] for c in d["cases"]]
    routing_cases = [
        case for case in all_cases
        if case.get("evidence_family") in _ROUTING_PROTOCOLS
    ]
    routing_states = Counter(case["evidence_state"] for case in routing_cases)
    routing_custody = Counter(
        case.get("projection_custody") or "not_disclosed" for case in routing_cases
    )
    fhrp_cases = [
        case for case in all_cases if case.get("evidence_family") == "FHRP"
    ]
    fhrp_states = Counter(case["evidence_state"] for case in fhrp_cases)
    fhrp_projection_custody = Counter(
        case.get("projection_custody") or "not_disclosed" for case in fhrp_cases
    )
    fhrp_domain_cases = [
        case for case in all_cases if case.get("evidence_family") == "FHRP Domain"
    ]
    fhrp_domain_states = Counter(case["evidence_state"] for case in fhrp_domain_cases)
    fhrp_domain_projection_custody = Counter(
        case.get("projection_custody") or "not_disclosed" for case in fhrp_domain_cases
    )
    etherchannel_cases = [
        case for case in all_cases if case.get("evidence_family") == "EtherChannel"
    ]
    etherchannel_states = Counter(case["evidence_state"] for case in etherchannel_cases)
    etherchannel_projection_custody = Counter(
        case.get("projection_custody") or "not_disclosed" for case in etherchannel_cases
    )
    stp_consistency_cases = [
        case for case in all_cases if case.get("evidence_family") == "STP"
    ]
    stp_consistency_states = Counter(
        case["evidence_state"] for case in stp_consistency_cases
    )
    stp_consistency_projection_custody = Counter(
        case.get("projection_custody") or "not_disclosed" for case in stp_consistency_cases
    )
    vtp_safety_cases = [
        case for case in all_cases if case.get("evidence_family") == "VTP"
    ]
    vtp_safety_states = Counter(
        case["evidence_state"] for case in vtp_safety_cases
    )
    vtp_safety_projection_custody = Counter(
        case.get("projection_custody") or "not_disclosed" for case in vtp_safety_cases
    )
    ipv6_routing_cases = [
        case for case in all_cases if case.get("evidence_family") == "IPv6 Routing"
    ]
    ipv6_routing_states = Counter(
        case["evidence_state"] for case in ipv6_routing_cases
    )
    ipv6_routing_projection_custody = Counter(
        case.get("projection_custody") or "not_disclosed"
        for case in ipv6_routing_cases
    )
    summary = {"n_waves": len(waves),
               "n_devices": sum(len(w["devices"]) for w in waves),
               "n_cases": len(all_cases),
               "by_phase": dict(Counter(c["phase"] for c in all_cases)),
               "n_not_observed": sum(1 for c in all_cases if c["expected"] == NOT_OBSERVED),
               "n_human_executed": sum(1 for c in all_cases if c["phase"] == 4),
               "n_routing_cases": len(routing_cases),
               "n_routing_blockers": sum(
                   case["evidence_state"] not in {"assessed", "administratively_disabled"}
                   for case in routing_cases
               ),
               "routing_by_evidence_state": dict(routing_states),
               "routing_by_projection_custody": dict(routing_custody),
               "n_fhrp_cases": len(fhrp_cases),
               "n_fhrp_blockers": sum(
                   case["evidence_state"] not in {"assessed", "administratively_disabled"}
                   for case in fhrp_cases
               ),
               "fhrp_by_evidence_state": dict(fhrp_states),
               "fhrp_by_projection_custody": dict(fhrp_projection_custody),
               "n_fhrp_domain_cases": len(fhrp_domain_cases),
               "n_fhrp_domain_blockers": sum(
                   case["evidence_state"] != "assessed" for case in fhrp_domain_cases
               ),
               "fhrp_domain_by_evidence_state": dict(fhrp_domain_states),
               "fhrp_domain_by_projection_custody": dict(
                   fhrp_domain_projection_custody),
               "n_etherchannel_cases": len(etherchannel_cases),
               "n_etherchannel_blockers": sum(
                   case["evidence_state"] != "assessed" for case in etherchannel_cases
               ),
               "etherchannel_by_evidence_state": dict(etherchannel_states),
               "etherchannel_by_projection_custody": dict(etherchannel_projection_custody),
               "n_stp_consistency_cases": len(stp_consistency_cases),
               "n_stp_consistency_blockers": sum(
                   case["evidence_state"] != "assessed" for case in stp_consistency_cases
               ),
               "stp_consistency_by_evidence_state": dict(stp_consistency_states),
               "stp_consistency_by_projection_custody": dict(
                   stp_consistency_projection_custody
               ),
               "n_vtp_safety_cases": len(vtp_safety_cases),
               "n_vtp_safety_blockers": sum(
                   case["evidence_state"] != "assessed" for case in vtp_safety_cases
               ),
               "vtp_safety_by_evidence_state": dict(vtp_safety_states),
               "vtp_safety_by_projection_custody": dict(
                   vtp_safety_projection_custody
               ),
               "n_ipv6_routing_cases": len(ipv6_routing_cases),
               "n_ipv6_routing_blockers": sum(
                   case["evidence_state"] != "assessed"
                   for case in ipv6_routing_cases
               ),
               "ipv6_routing_by_evidence_state": dict(ipv6_routing_states),
               "ipv6_routing_by_projection_custody": dict(
                   ipv6_routing_projection_custody
               )}
    return {"schema": NRFU_SCHEMA, "banner": NRFU_BANNER, "waves": waves, "summary": summary}


def _safe_name(s) -> str:
    """One path COMPONENT from untrusted snapshot text. The whitelist rewrites every separator
    (`/`, `\\`, `:`) to `_`, but it KEEPS `.` — and `.`/`..` are themselves path components, so
    `_safe_name("..")` returned `".."` and `os.path.join(out_dir, "..")` resolved to the PARENT of
    `--out`: a crafted `wave_id` wrote the command pack outside the directory the operator named.
    write_nrfu_pack already treats snap['nrfu_commands'] as possibly tampered (it refuses non-read-only
    command text); the path components need the same treatment. An all-dot name is never a real wave
    or host, so it degrades to the same 'unnamed' sentinel an empty name already used."""
    n = re.sub(r"[^A-Za-z0-9._-]+", "_", str(s)).strip("_")
    if not n or set(n) <= {"."}:          # "", ".", "..", "..." -> traversal / self-reference
        return "unnamed"
    return n


def write_nrfu_pack(snap: Optional[dict] = None, out_dir: str = ".") -> List[str]:
    """Emit the per-device NRFU command files: <out_dir>/<wave>/<host>.txt — one file per device per
    wave, the READ-ONLY commands as executable lines and the expected baseline / evidence citation as
    '!' comment lines (paste-safe: Cisco CLIs ignore '!' lines). Pure function of the snapshot: reuses
    the published snap['nrfu_commands'] when present (one source of truth), else computes it. Returns
    the sorted list of written file paths. (A --nrfu-pack CLI flag is deferred; call this directly.)"""
    s = snap if isinstance(snap, dict) else {}
    nc = s.get("nrfu_commands")
    if not (isinstance(nc, dict) and isinstance(nc.get("waves"), list)):
        nc = compute_nrfu_commands(s)
    written: List[str] = []
    for w in _as_list(nc.get("waves")):
        wdir = os.path.join(out_dir, _safe_name(w.get("wave_id", "wave")))
        for dev in _as_list(w.get("devices")):
            host = str(dev.get("host") or "device")
            os.makedirs(wdir, exist_ok=True)
            lines = [f"! NRFU verification commands — wave {w.get('wave_id')} — device {host} "
                     f"({dev.get('platform_dialect', 'ios')})",
                     f"! {NRFU_BANNER}",
                     "! READ-ONLY: show/ping/traceroute class only; '!' lines are comments.",
                     ""]
            for c in _as_list(dev.get("cases")):
                # belt-and-braces vs a tampered pre-published snap['nrfu_commands']: comment fields
                # are re-collapsed to one line, and a command that is not a single-line
                # show/ping/traceroute is REFUSED into a comment — never an executable line.
                cmd = _one_line(c.get("command") or "")
                cmd_line = cmd if _READ_ONLY_LINE.match(cmd) else \
                    f"! [REFUSED — not a read-only command] {cmd}"
                lines += [f"! {_one_line(c.get('id'))}  "
                          f"[Phase {_PHASE_ROMAN.get(c.get('phase'), c.get('phase'))}]"
                          f" [{_one_line(c.get('scope'))}]",
                          f"!   expect: {_one_line(c.get('expected'))}",
                          f"!   source: {_one_line(c.get('source_key'))}"]
                if c.get("evidence_family"):
                    lines.append(f"!   evidence_family: {_one_line(c.get('evidence_family'))}")
                if c.get("evidence_state"):
                    lines.append(f"!   evidence_state: {_one_line(c.get('evidence_state'))}")
                if c.get("projection_custody"):
                    lines.append(f"!   projection_custody: {_one_line(c.get('projection_custody'))}")
                lines += [cmd_line, ""]
            path = os.path.join(wdir, f"{_safe_name(host)}.txt")
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
            written.append(path)
    return sorted(written)
