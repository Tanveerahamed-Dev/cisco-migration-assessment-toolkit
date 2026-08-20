"""The L2 failover twin (MASTER_PLAN 2026-07-05 §4.1) — offline, read-only, coverage-honest.

Batfish/Forward are L3-centric; STP root re-election and FHRP (HSRP/VRRP/GLBP) master takeover are
DETERMINISTICALLY recomputable from data already collected (snap['stp_roots'], snap['fhrp_detail']). This
is the market-gap capability whatif.py (L3 routes only) does NOT cover: when a core/distribution switch
fails, WHO becomes the new spanning-tree root per VLAN, and WHO takes over each first-hop-redundancy virtual
IP — and whether that takeover is provable from the collected evidence at all.

COVERAGE-HONEST by construction (the doctrine's Law 3): absence of evidence is never health.
  * If only ONE bridge is observed for a VLAN, a re-election cannot be proven -> abstain (INDETERMINATE).
  * If the incumbent root is itself off-scan (not observed as a bridge in that VLAN) -> abstain.
  * A new root that would win only by the default bridge priority (>= 32768) is FLAGGED as the same smell the
    explorer already surfaces (an unmanaged election, not an engineered backup).
  * If only ONE first-hop-redundancy member is collected for a group, single-homed cannot be disproven ->
    abstain. If NO surviving member is observed after the failure, the virtual IP is STRANDED (flagged), not
    silently reported as a clean takeover.

The input snapshot is NEVER mutated (this module only reads). `failures` uses the SAME shape whatif.py
accepts ({type:'node'|'site', id}); the host-resolution is reused from whatif._match_failures.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from . import whatif

# Cisco default bridge priority (32768). A root that only wins because every candidate sits at (or above) the
# default is an UNMANAGED election, not an engineered backup — flagged, per the explorer's existing smell.
_DEFAULT_BRIDGE_PRIORITY = 32768


# --------------------------------------------------------------------------- helpers ---

def _failed_host_set(snap: Dict[str, Any], failures: Any) -> List[str]:
    """Resolve `failures` ({type:'node'|'site', id}) against ALL hosts observed in the snapshot's L2 sections
    (stp_roots + fhrp_detail) — the union, so a site-code substring match reaches a switch that appears in only
    one of the two sections. Returns a sorted list. Reuses whatif's resolver so the two engines agree."""
    hosts: set = set()
    for section in ("stp_roots", "fhrp_detail"):
        sec = (snap or {}).get(section)
        if isinstance(sec, dict):
            hosts.update(sec.keys())
    return sorted(whatif._match_failures(sorted(hosts), _as_failure_list(failures)))


def _as_failure_list(failures: Any) -> List[dict]:
    """Accept either a bare failures list or a scenario dict ({failures:[…]}) — mirrors whatif's flexibility."""
    if isinstance(failures, dict):
        failures = failures.get("failures")
    return failures if isinstance(failures, list) else []


def _int_or(v: Any, default: Optional[int]) -> Optional[int]:
    """Strict non-negative integer coercion for an untrusted election-priority leaf.

    ``int`` silently truncates fractional floats and treats booleans as 0/1. Either would certify an
    election against a different priority than the snapshot declared. Integral finite numbers and integer
    strings are accepted; every malformed value returns ``default`` so callers abstain.
    """
    if isinstance(v, bool):
        return default
    if isinstance(v, int):
        return v if v >= 0 else default
    if isinstance(v, float):
        if not math.isfinite(v) or not v.is_integer():
            return default
        parsed = int(v)
        return parsed if parsed >= 0 else default
    if isinstance(v, str):
        token = v.strip()
        unsigned = token[1:] if token[:1] in ("+", "-") else token
        if not unsigned.isdigit():
            return default
        parsed = int(token)
        return parsed if parsed >= 0 else default
    return default


# ---------------------------------------------------------------------- STP failover ---

def _vlan_bridges(snap: Dict[str, Any]) -> Dict[str, Dict[str, dict]]:
    """Invert snap['stp_roots'] to {vlan: {host: bridge_record}} — every bridge observed to participate in each
    VLAN, so a re-election can enumerate the surviving candidates. Coverage-honest: only bridges actually
    collected appear (a VLAN with one collected bridge yields one candidate -> the caller abstains)."""
    out: Dict[str, Dict[str, dict]] = {}
    stp = (snap or {}).get("stp_roots")
    if not isinstance(stp, dict):
        return out
    for host, per_vlan in stp.items():
        if not isinstance(per_vlan, dict):
            continue
        for vlan, rec in per_vlan.items():
            if not isinstance(rec, dict):
                continue
            out.setdefault(str(vlan), {})[host] = rec
    return out


def _current_root(bridges: Dict[str, dict]) -> Optional[str]:
    """The collected host that is PROVABLY the current STP root for a VLAN — the one that reports itself as
    root (is_root=True). Returns None when no collected bridge is the root: in that case the real root is
    off-scan (every collected non-root bridge advertises the SAME off-scan root_address, so electing one by
    the advertised vector would just pick an arbitrary non-root switch — a fabricated incumbent). Coverage-
    honesty (Law 3): the root is named only when the evidence proves it, never inferred from the identical
    root vector the non-root bridges all carry. Also None if two+ bridges ambiguously claim root."""
    flagged = [h for h, r in bridges.items() if r.get("is_root") is True]
    return flagged[0] if len(flagged) == 1 else None


def compute_stp_failover(snap: Dict[str, Any], failed_hosts: List[str]) -> List[Dict[str, Any]]:
    """Per-VLAN spanning-tree root re-election when `failed_hosts` are removed.

    For each VLAN whose current root is in `failed_hosts`, the NEW root is the surviving bridge with the min
    (bridge_priority, root_address/mac). Returns one row per AFFECTED VLAN (the current root failed):
        {vlan, old_root, new_root, new_root_won_by, is_default_election, is_mst,
         ports_expected_to_transition, indeterminate, reason}
    where new_root_won_by is 'lower-priority' | 'lower-mac-tiebreak' | 'default-election(>=32768)'.

    COVERAGE-HONEST abstention (indeterminate=True, new_root=None):
      * only one bridge observed for the VLAN (a re-election is not provable — single-homed L2 not disproven);
      * the current root is off-scan (not observed as a bridge in that VLAN — the incumbent is uncollected).
    A default-election new root (min bridge_priority >= 32768) is FLAGGED (is_default_election=True) as the
    unmanaged-election smell, but is still reported as the deterministic winner.

    ports_expected_to_transition is always the honest lower-bound sentinel '(topology-scan-bound — lower
    bound)': the collected data proves WHO re-roots, not the exact per-port transition count (that needs a
    full topology port scan the snapshot does not carry)."""
    failed = {str(h) for h in (failed_hosts or [])}
    rows: List[Dict[str, Any]] = []
    for vlan, bridges in sorted(_vlan_bridges(snap).items(), key=lambda kv: _vlan_sort_key(kv[0])):
        old_root = _current_root(bridges)
        if old_root is None:
            if failed.intersection(bridges):
                flagged = sorted(h for h, record in bridges.items() if record.get("is_root") is True)
                reason = ("INDETERMINATE — multiple collected bridges claim to be the current root: "
                          + ", ".join(flagged)) if flagged else (
                              "INDETERMINATE — no collected bridge uniquely proves the current root"
                          )
                rows.append(_stp_indeterminate(vlan, None, False, reason))
            continue
        if old_root not in failed:
            continue                                    # this VLAN's proven root survives
        survivors = {h: r for h, r in bridges.items() if h not in failed}
        is_mst = bool(bridges.get(old_root, {}).get("is_mst"))
        if len(bridges) < 2:
            rows.append(_stp_indeterminate(vlan, old_root, is_mst,
                                           "INDETERMINATE — root or alternates not collected "
                                           "(only one bridge observed for this VLAN)"))
            continue
        if not survivors:
            rows.append(_stp_indeterminate(vlan, old_root, is_mst,
                                           "INDETERMINATE — every observed bridge for this VLAN is in the "
                                           "failed set (no surviving root candidate collected)"))
            continue
        # The re-election is provable ONLY from each survivor's OWN bridge_priority. A survivor whose own
        # priority was not collected could hold any value (an uncollected priority could undercut the apparent
        # winner), so a missing priority on ANY survivor makes the winner unprovable -> abstain (kills the old
        # 1<<30 sentinel that laundered a missing priority into a fabricated default-election).
        priced = {h: _int_or(r.get("bridge_priority"), None) for h, r in survivors.items()}
        if any(p is None for p in priced.values()):
            missing = sorted(h for h, p in priced.items() if p is None)
            rows.append(_stp_indeterminate(vlan, old_root, is_mst,
                                           "INDETERMINATE — surviving bridge(s) without a collected "
                                           "bridge priority (winner not provable): " + ", ".join(missing)))
            continue
        min_prio = min(priced.values())
        winners = sorted(h for h, p in priced.items() if p == min_prio)
        if len(winners) > 1:
            # A genuine bridge_priority tie is broken by the contending bridge's OWN bridge MAC (802.1D), which
            # is NOT collected (root_address is the OLD root's MAC — identical across these survivors). Abstain
            # rather than pick arbitrarily / on the wrong field.
            rows.append(_stp_indeterminate(vlan, old_root, is_mst,
                                           "INDETERMINATE — bridge-priority tie among surviving candidates at "
                                           "priority {}; the tiebreak needs each bridge's own MAC (not "
                                           "collected): {}".format(min_prio, ", ".join(winners))))
            continue
        new_root = winners[0]
        rows.append({
            "vlan": vlan,
            "old_root": old_root,
            "new_root": new_root,
            "new_root_priority": min_prio,
            "new_root_won_by": ("default-election(>=32768)" if min_prio >= _DEFAULT_BRIDGE_PRIORITY
                                else "lower-priority"),
            "is_default_election": min_prio >= _DEFAULT_BRIDGE_PRIORITY,
            "is_mst": is_mst,
            "ports_expected_to_transition": "(topology-scan-bound — lower bound)",
            "indeterminate": False,
            "reason": "",
        })
    return rows


def _stp_indeterminate(vlan: str, old_root: Optional[str], is_mst: bool, reason: str) -> Dict[str, Any]:
    return {
        "vlan": vlan, "old_root": old_root, "new_root": None, "new_root_priority": None,
        "new_root_won_by": None, "is_default_election": False, "is_mst": is_mst,
        "ports_expected_to_transition": "(topology-scan-bound — lower bound)",
        "indeterminate": True, "reason": reason,
    }


def _vlan_sort_key(vlan: str):
    """Numeric VLANs sort numerically, then any non-numeric labels (e.g. an MST instance name) lexically."""
    s = str(vlan)
    return (0, int(s)) if s.isdigit() else (1, s)


# --------------------------------------------------------------------- FHRP failover ---

def _fhrp_groups(snap: Dict[str, Any]) -> Dict[str, List[dict]]:
    """Invert snap['fhrp_detail'] to {group_key: [member_record_with_host]} where group_key keys on
    (ifname, group) so two independent groups that reuse the same group number on different SVIs don't merge.
    Each member record is augmented with its owning host. Coverage-honest: only collected members appear."""
    out: Dict[str, List[dict]] = {}
    fd = (snap or {}).get("fhrp_detail")
    if not isinstance(fd, dict):
        return out
    for host, members in fd.items():
        if not isinstance(members, list):
            continue
        for m in members:
            if not isinstance(m, dict):
                continue
            key = "{}|{}".format(str(m.get("ifname", "")), str(m.get("group", "")))
            out.setdefault(key, []).append({**m, "host": host})
    return out


def _current_active(members: List[dict]) -> Optional[dict]:
    """The PROVABLE current forwarding member of a group: the one whose state reads 'Active'/'Master'
    (case-insensitive). Returns None unless exactly one collected member claims that state. Zero claims may
    mean the forwarder is off-scan; multiple claims are split-brain/ambiguous. In either case guessing from
    priority would fabricate an incumbent that is not proved to serve the VIP."""
    active = [m for m in members
              if str(m.get("state", "")).strip().lower() in ("active", "master")]
    return active[0] if len(active) == 1 else None


def compute_fhrp_failover(snap: Dict[str, Any], failed_hosts: List[str]) -> List[Dict[str, Any]]:
    """Per first-hop-redundancy group (HSRP/VRRP/GLBP) takeover when `failed_hosts` are removed.

    For each group whose current forwarding member is on a failed host, the NEW forwarding member is the
    highest-priority SURVIVING member. Returns one row per AFFECTED group:
        {group, ifname, vip, version, old_active, new_active, new_active_priority,
         split_brain_risk, indeterminate, reason}

    split_brain_risk = True when either:
      * the takeover member has preempt disabled — a returning higher-priority incumbent will NOT reclaim, so a
        dual-forwarding window opens when it comes back (an operational smell, flagged); OR
      * no surviving member is observed — the virtual IP is STRANDED (no proven backup gateway).

    COVERAGE-HONEST abstention (indeterminate=True):
      * only ONE member collected for the group (single-homed first-hop redundancy cannot be proven — the
        peer may simply be uncollected).
    A stranded VIP is reported (split_brain_risk=True, new_active=None) rather than silently dropped."""
    failed = {str(h) for h in (failed_hosts or [])}
    rows: List[Dict[str, Any]] = []
    for _key, members in sorted(_fhrp_groups(snap).items()):
        active = _current_active(members)
        if active is None:
            member_hosts = {str(member.get("host")) for member in members}
            if failed.intersection(member_hosts):
                exemplar = members[0] if members else {}
                flagged = sorted(str(member.get("host")) for member in members
                                 if str(member.get("state", "")).strip().lower() in ("active", "master"))
                reason = ("INDETERMINATE — multiple collected members claim Active/Master: "
                          + ", ".join(flagged)) if flagged else (
                              "INDETERMINATE — no collected member uniquely proves Active/Master"
                          )
                rows.append(_fhrp_row(
                    str(exemplar.get("group", "")), str(exemplar.get("ifname", "")),
                    exemplar.get("vip", ""), exemplar.get("version"), None, None, None,
                    split_brain=len(flagged) > 1, indeterminate=True, reason=reason,
                ))
            continue
        if str(active.get("host")) not in failed:
            continue                                    # this group's proven forwarding member survives
        ifname = str(active.get("ifname", ""))
        group = str(active.get("group", ""))
        vip = active.get("vip", "")
        version = active.get("version")
        member_hosts = [str(member.get("host")) for member in members]
        if len(set(member_hosts)) != len(member_hosts):
            rows.append(_fhrp_row(
                group, ifname, vip, version, active.get("host"), None, None,
                split_brain=False, indeterminate=True,
                reason="INDETERMINATE — duplicate member records exist for one or more hosts",
            ))
            continue
        active_vip = vip.strip() if isinstance(vip, str) else ""
        active_version = _int_or(version, None)
        incompatible = []
        for member in members:
            member_vip = member.get("vip")
            member_version = _int_or(member.get("version"), None)
            if not active_vip or not isinstance(member_vip, str) or member_vip.strip() != active_vip \
                    or active_version is None or member_version != active_version:
                incompatible.append(str(member.get("host")))
        if incompatible:
            rows.append(_fhrp_row(
                group, ifname, active_vip, active_version, active.get("host"), None, None,
                split_brain=False, indeterminate=True,
                reason="INDETERMINATE — member VIP/version contract is missing or inconsistent: "
                       + ", ".join(sorted(incompatible)),
            ))
            continue
        if len(members) < 2:
            rows.append(_fhrp_row(group, ifname, vip, version, active.get("host"), None, None,
                                  split_brain=False, indeterminate=True,
                                  reason="INDETERMINATE — single member collected for this group "
                                         "(single-homed first-hop redundancy not provable — a peer may be "
                                         "uncollected)"))
            continue
        survivors = [m for m in members if str(m.get("host")) not in failed]
        if not survivors:
            rows.append(_fhrp_row(group, ifname, vip, version, active.get("host"), None, None,
                                  split_brain=True, indeterminate=False,
                                  reason="VIP STRANDED — no surviving member observed for this group after the "
                                         "failure (no proven backup gateway)"))
            continue
        priced = [(member, _int_or(member.get("priority"), None)) for member in survivors]
        if any(priority is None for _member, priority in priced):
            missing = sorted(str(member.get("host")) for member, priority in priced if priority is None)
            rows.append(_fhrp_row(
                group, ifname, vip, version, active.get("host"), None, None,
                split_brain=False, indeterminate=True,
                reason="INDETERMINATE — surviving member(s) without a valid collected priority: "
                       + ", ".join(missing),
            ))
            continue
        ineligible = sorted(
            str(member.get("host")) for member in survivors
            if str(member.get("state", "")).strip().lower() not in ("standby", "backup")
        )
        if ineligible:
            rows.append(_fhrp_row(
                group, ifname, active_vip, active_version, active.get("host"), None, None,
                split_brain=False, indeterminate=True,
                reason="INDETERMINATE — surviving member state is not an eligible Standby/Backup: "
                       + ", ".join(ineligible),
            ))
            continue
        max_priority = max(priority for _member, priority in priced)
        winners = [member for member, priority in priced if priority == max_priority]
        if len(winners) != 1:
            rows.append(_fhrp_row(
                group, ifname, vip, version, active.get("host"), None, None,
                split_brain=False, indeterminate=True,
                reason="INDETERMINATE — equal-priority surviving candidates require an uncollected "
                       "protocol tiebreak: "
                       + ", ".join(sorted(str(member.get("host")) for member in winners)),
            ))
            continue
        new_active = winners[0]
        no_reclaim = new_active.get("preempt") is False
        reason = ("split-brain risk — takeover member does not reclaim on a returning higher-priority "
                  "incumbent (dual-forwarding window)") if no_reclaim else ""
        rows.append(_fhrp_row(group, ifname, vip, version, active.get("host"), new_active.get("host"),
                              max_priority, split_brain=bool(no_reclaim),
                              indeterminate=False, reason=reason))
    return rows


def _fhrp_row(group, ifname, vip, version, old_active, new_active, new_prio,
              split_brain: bool, indeterminate: bool, reason: str) -> Dict[str, Any]:
    return {
        "group": group, "ifname": ifname, "vip": vip, "version": version,
        "old_active": old_active, "new_active": new_active, "new_active_priority": new_prio,
        "split_brain_risk": split_brain, "indeterminate": indeterminate, "reason": reason,
    }


# ----------------------------------------------------------------------- orchestrator ---

def compute_failover_twin(snap: Dict[str, Any], failures: Any) -> Dict[str, Any]:
    """Orchestrate the L2 failover twin for a failure scenario. `failures` uses the whatif shape
    ({type:'node'|'site', id}); a bare list or a {failures:[…]} scenario dict are both accepted.

    Returns {schema:'failover_twin/1', failed_hosts, stp:[…], fhrp:[…], summary} where summary reconciles:
        {n_vlans_rerooted, n_default_election_roots, n_fhrp_takeovers, n_split_brain_risks, n_indeterminate}
    n_indeterminate counts BOTH abstaining STP rows and abstaining FHRP rows (the coverage-honest blind spots).
    Read-only: the snapshot is never mutated."""
    failed_hosts = _failed_host_set(snap, failures)
    stp = compute_stp_failover(snap, failed_hosts)
    fhrp = compute_fhrp_failover(snap, failed_hosts)
    n_reroot = sum(1 for r in stp if not r["indeterminate"])
    n_default = sum(1 for r in stp if r.get("is_default_election"))
    n_takeover = sum(1 for r in fhrp if not r["indeterminate"] and r.get("new_active"))
    n_split = sum(1 for r in fhrp if r.get("split_brain_risk"))
    n_indet = sum(1 for r in stp if r["indeterminate"]) + sum(1 for r in fhrp if r["indeterminate"])
    return {
        "schema": "failover_twin/1",
        "failed_hosts": failed_hosts,
        "stp": stp,
        "fhrp": fhrp,
        "summary": {
            "n_vlans_rerooted": n_reroot,
            "n_default_election_roots": n_default,
            "n_fhrp_takeovers": n_takeover,
            "n_split_brain_risks": n_split,
            "n_indeterminate": n_indet,
        },
    }


# --------------------------------------------------- always-on readiness rollup (surface) ---

def compute_failover_readiness(snap: Dict[str, Any]) -> Dict[str, Any]:
    """A target-free rollup for an MCP surface: for EVERY observed STP root and FHRP forwarding member, is
    there a PROVABLE backup if it alone fails? Runs the twin once per observed root/active host and tallies
    where the backup is proven, where it is only a default-election smell, and where the evidence is
    INDETERMINATE (single-homed / uncollected peer). Coverage-honest: an unprovable backup is counted as a
    blind spot, never as 'has a backup'.

    Returns {schema:'failover_readiness/1', n_stp_roots, n_stp_roots_with_backup, n_stp_default_election,
    n_stp_indeterminate, n_fhrp_actives, n_fhrp_with_backup, n_fhrp_split_brain, n_fhrp_indeterminate,
    at_risk:[…]} where at_risk names each root/active whose single failure has no proven clean backup."""
    stp_roots_hosts: set = set()
    for vlan, bridges in _vlan_bridges(snap).items():
        r = _current_root(bridges)
        if r is not None:
            stp_roots_hosts.add((vlan, r))
    fhrp_actives: List[dict] = []
    for _key, members in _fhrp_groups(snap).items():
        a = _current_active(members)
        if a is not None:
            fhrp_actives.append(a)

    n_stp = len(stp_roots_hosts)
    stp_backup = stp_default = stp_indet = 0
    at_risk: List[Dict[str, Any]] = []
    for vlan, host in sorted(stp_roots_hosts, key=lambda t: (_vlan_sort_key(t[0]), t[1])):
        rows = compute_stp_failover(snap, [host])
        row = next((x for x in rows if x["vlan"] == vlan), None)
        if row is None or row["indeterminate"]:
            stp_indet += 1
            at_risk.append({"kind": "stp", "vlan": vlan, "host": host,
                            "reason": (row or {}).get("reason") or "no re-election row produced"})
        elif row.get("is_default_election"):
            stp_default += 1
            at_risk.append({"kind": "stp", "vlan": vlan, "host": host,
                            "reason": "backup wins only by default bridge priority (>=32768) — unmanaged election"})
        else:
            stp_backup += 1

    n_fhrp = len(fhrp_actives)
    fhrp_backup = fhrp_split = fhrp_indet = 0
    for a in fhrp_actives:
        rows = compute_fhrp_failover(snap, [str(a.get("host"))])
        key = (str(a.get("ifname", "")), str(a.get("group", "")))
        row = next((x for x in rows if (str(x["ifname"]), str(x["group"])) == key), None)
        if row is None or row["indeterminate"]:
            fhrp_indet += 1
            at_risk.append({"kind": "fhrp", "ifname": a.get("ifname"), "group": a.get("group"),
                            "vip": a.get("vip"), "host": a.get("host"),
                            "reason": (row or {}).get("reason") or "no takeover row produced"})
        elif row.get("split_brain_risk"):
            fhrp_split += 1
            at_risk.append({"kind": "fhrp", "ifname": a.get("ifname"), "group": a.get("group"),
                            "vip": a.get("vip"), "host": a.get("host"),
                            "reason": row.get("reason") or "split-brain / stranded on single failure"})
        else:
            fhrp_backup += 1

    return {
        "schema": "failover_readiness/1",
        "n_stp_roots": n_stp,
        "n_stp_roots_with_backup": stp_backup,
        "n_stp_default_election": stp_default,
        "n_stp_indeterminate": stp_indet,
        "n_fhrp_actives": n_fhrp,
        "n_fhrp_with_backup": fhrp_backup,
        "n_fhrp_split_brain": fhrp_split,
        "n_fhrp_indeterminate": fhrp_indet,
        "at_risk": at_risk,
    }
