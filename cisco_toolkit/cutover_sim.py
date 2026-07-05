"""The cutover dry-run simulator (MASTER_PLAN 2026-07-05 §4.2) — offline, read-only, coverage-honest.

A cutover wave is an ordered list of graph mutations. This models each, applies it step-by-step on a
COPY of the snapshot, and at each step runs the L2 failover twin (failover.py) + the FIB reachability
delta (fib.reachability_delta) — producing a per-step impact report so a change author can see, before any
device is touched, exactly which flows a step strands and which a later step restores ('after step 3, VLAN
40 loses its only path until step 5').

The engine already owns the two half-twins:
  * L3 forwarding — fib.reachability_delta over snap['routes'] (what whatif.py drives);
  * L2 resilience — failover.compute_failover_twin over snap['stp_roots'] + snap['fhrp_detail'].
This simulator sequences them: it accumulates the wave's mutations on a running snapshot and diffs each
step against the state just before it, so 'newly lost' / 'recovered' are the marginal effect of THAT step.

COVERAGE-HONEST (inherited from fib/whatif): a lost flow is 'path lost (inconclusive)' — a flow that WAS
computed-reached and is now unprovable because its next-hop went off-scan — never a fabricated definitive
block. Only fib's own definitive `newly_blocked` verdict is reported as a hard drop.

The input snapshot is NEVER mutated: every step works on a deep copy. Pure stdlib + existing fib/failover.
"""
from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional

from . import failover, fib, whatif

# Supported step actions. A step is {action, ...params}; an unknown action is a coverage-honest no-op that
# is REPORTED (never silently dropped) so a typo in a wave plan surfaces rather than passing green.
_ACTIONS = ("fail_node", "fail_site", "shut_link", "move_fhrp_active")


# --------------------------------------------------------------------- step mutations ---

def _apply_step(before: Dict[str, Any], step: Dict[str, Any]) -> Dict[str, Any]:
    """Return a DEEP COPY of `before` with `step` applied. Never mutates `before`. Unknown/malformed steps
    return an untouched deep copy (a no-op) — the caller flags them so nothing is silently skipped."""
    after = copy.deepcopy(before)
    action = str((step or {}).get("action") or "").strip()
    if action == "fail_node":
        _remove_hosts(after, [{"type": "node", "id": step.get("id")}])
    elif action == "fail_site":
        _remove_hosts(after, [{"type": "site", "id": step.get("id")}])
    elif action == "shut_link":
        _shut_link(after, step.get("host"), step.get("interface"))
    elif action == "move_fhrp_active":
        _move_fhrp_active(after, step.get("ifname"), step.get("group"), step.get("to_host"))
    return after


def _remove_hosts(snap: Dict[str, Any], failures: List[dict]) -> List[str]:
    """Remove the resolved hosts from EVERY L2/L3 section the twins read (routes, stp_roots, fhrp_detail),
    so both half-twins see the node as gone. Returns the sorted removed-host list. Mutates `snap` in place
    (the caller already deep-copied)."""
    hosts: set = set()
    for section in ("routes", "stp_roots", "fhrp_detail"):
        sec = snap.get(section)
        if isinstance(sec, dict):
            hosts.update(sec.keys())
    removed = sorted(whatif._match_failures(sorted(hosts), failures))
    rem = set(removed)
    for section in ("routes", "stp_roots", "fhrp_detail"):
        sec = snap.get(section)
        if isinstance(sec, dict):
            snap[section] = {h: v for h, v in sec.items() if h not in rem}
    return removed


def _shut_link(snap: Dict[str, Any], host: Any, interface: Any) -> None:
    """Model a link shutdown deterministically: drop every collected route on `host` whose egress interface
    is `interface` (case-insensitive, whitespace-normalized). Coverage-honest — removing the collected
    forwarding route makes flows that used it resolve to a lost trail (lower_bound), never a fabricated
    block. A blank host/interface, or a host not in routes, is a no-op."""
    h = str(host or "").strip()
    want = _norm_intf(interface)
    if not h or not want:
        return
    routes = snap.get("routes")
    if not isinstance(routes, dict) or h not in routes:
        return
    host_routes = routes.get(h)
    if not isinstance(host_routes, list):
        return
    routes[h] = [r for r in host_routes
                 if not (isinstance(r, dict) and _norm_intf(r.get("out_intf")) == want)]


def _move_fhrp_active(snap: Dict[str, Any], ifname: Any, group: Any, to_host: Any) -> None:
    """Deterministically move the forwarding role of one first-hop-redundancy group. On the group keyed by
    (ifname, group): demote the current forwarding member to a non-forwarding state and promote the target
    (an explicit `to_host`, else the highest-priority OTHER collected member) to the forwarding role. Only
    the fhrp_detail state is adjusted — the virtual IP does not move, so this is L2-only (routes unchanged).
    A group/target that can't be resolved is a no-op (reported by the caller as a no-effect step)."""
    fd = snap.get("fhrp_detail")
    if not isinstance(fd, dict):
        return
    want_if = str(ifname or "").strip()
    want_grp = str(group or "").strip()
    # collect (host, member_dict) for the target group across all hosts
    members = []
    for host, mlist in fd.items():
        if not isinstance(mlist, list):
            continue
        for m in mlist:
            if isinstance(m, dict) and str(m.get("ifname", "")) == want_if and str(m.get("group", "")) == want_grp:
                members.append((host, m))
    if len(members) < 2:
        return                                       # nothing to move to (single-homed / not found) — no-op
    cur = failover._current_active([{**m, "host": h} for h, m in members])
    cur_host = str(cur.get("host")) if cur else None
    target_host = str(to_host or "").strip()
    if not target_host:                              # default: the highest-priority member that isn't current
        cands = [(h, m) for h, m in members if h != cur_host]
        target_host = max(cands, key=lambda hm: failover._int_or(hm[1].get("priority"), -1))[0] if cands else ""
    if not target_host or target_host == cur_host:
        return
    for host, m in members:
        if host == cur_host:
            m["state"] = "Listen"                    # the incumbent yields the forwarding role
        elif host == target_host:
            m["state"] = "Active"                    # the target assumes the forwarding role


def _norm_intf(name: Any) -> str:
    return str(name or "").strip().lower().replace(" ", "")


# ------------------------------------------------------------------ step failure set ---

def _step_failures(step: Dict[str, Any]) -> List[dict]:
    """The whatif-shaped failures a step implies for the L2 failover twin. fail_node/fail_site map to a
    node/site removal; shut_link and move_fhrp_active remove no HOST, so they imply no twin re-election
    input on their own (their L2 effect is captured by re-running the twin over the mutated snapshot with
    an empty failure set, which yields no reroots — correct, since no bridge disappeared)."""
    action = str((step or {}).get("action") or "").strip()
    if action == "fail_node":
        return [{"type": "node", "id": step.get("id")}]
    if action == "fail_site":
        return [{"type": "site", "id": step.get("id")}]
    return []


# ------------------------------------------------------------------- narrative maker ---

def _narrative(action: str, step: Dict[str, Any], removed: List[str], n_lost: int, n_recovered: int,
               stp: List[dict], fhrp: List[dict], is_noop: bool) -> str:
    """A plain-English one-liner for a step. Coverage-honest wording: 'path lost (inconclusive)' phrasing,
    never a claimed hard block unless fib returned one."""
    if is_noop:
        return f"step had no effect ({action or 'unknown action'} matched nothing) — no change to reachability or L2"
    parts: List[str] = []
    if action in ("fail_node", "fail_site"):
        who = ", ".join(removed) if removed else "(no host matched)"
        parts.append(f"failing {who}")
    elif action == "shut_link":
        parts.append(f"shutting {step.get('host')} {step.get('interface')}")
    elif action == "move_fhrp_active":
        parts.append(f"moving FHRP group {step.get('group')} on {step.get('ifname')}"
                     + (f" to {step.get('to_host')}" if step.get("to_host") else ""))
    else:
        parts.append(f"{action or 'unknown action'}")
    impact: List[str] = []
    if n_lost:
        impact.append(f"{n_lost} flow(s) lose their path (inconclusive)")
    if n_recovered:
        impact.append(f"{n_recovered} flow(s) recover")
    n_reroot = sum(1 for r in stp if not r.get("indeterminate"))
    if n_reroot:
        impact.append(f"{n_reroot} VLAN(s) re-root")
    n_take = sum(1 for r in fhrp if not r.get("indeterminate") and r.get("new_active"))
    if n_take:
        impact.append(f"{n_take} FHRP group(s) take over")
    n_sb = sum(1 for r in fhrp if r.get("split_brain_risk"))
    if n_sb:
        impact.append(f"{n_sb} split-brain/stranded risk(s)")
    if not impact:
        impact.append("no reachability or L2 change proven")
    return f"After {parts[0]}: " + "; ".join(impact) + "."


# ------------------------------------------------------------------------- simulator ---

def simulate_cutover(snap: Dict[str, Any], steps: List[Dict[str, Any]],
                     pairs: Optional[list] = None, limit: int = 24, max_pairs: int = 400) -> Dict[str, Any]:
    """Dry-run an ordered cutover wave. `steps` is an ordered list of graph mutations, each a dict:
        {action:'fail_node', id:<host>}
        {action:'fail_site', id:<site-code-substring>}
        {action:'shut_link', host:<host>, interface:<egress ifname>}
        {action:'move_fhrp_active', ifname:<Vlan..>, group:<n>, to_host:<host>?}

    Applies each step step-by-step on a running deep COPY of `snap`, and at each step reports the MARGINAL
    effect vs the state just before it: the fib reachability delta (newly-lost / recovered flows) and the
    L2 failover twin (STP reroots, FHRP takeovers, split-brain risks). The flow-test pairs are derived ONCE
    from the ORIGINAL snapshot (so 'lost' and 'recovered' reference the same fixed flow set across steps).

    Returns {schema:'cutover_sim/1', steps:[…], worst_step, summary}. Each step row:
        {step_index, action, params, removed_hosts, newly_lost_flows, recovered_flows, stp_reroots,
         fhrp_takeovers, split_brain_risks, indeterminate, is_noop, narrative}.
    worst_step = the index of the step with the most newly-lost flows (ties -> the earliest); None if the
    wave loses nothing. summary tallies totals across the wave.

    COVERAGE-HONEST: a lost flow is 'path lost (inconclusive)', never a fabricated block; only fib's own
    definitive newly_blocked is a hard drop. The input snapshot is NEVER mutated (deep copy per step)."""
    if pairs is None:
        pairs = fib.default_pairs(snap, limit, max_pairs)   # fixed flow set from the ORIGINAL topology

    current = copy.deepcopy(snap)                            # the running post-wave state; snap stays untouched
    step_rows: List[Dict[str, Any]] = []
    total_lost = total_recovered = total_reroots = total_takeovers = total_split = total_indet = 0

    for idx, step in enumerate(steps or []):
        step = step if isinstance(step, dict) else {}
        action = str(step.get("action") or "").strip()
        before = current
        after = _apply_step(before, step)

        # L3: marginal reachability change from this step (before -> after), over the fixed flow set.
        delta = fib.reachability_delta(before, after, pairs=pairs)
        newly_lost = _lost_flows(before, after, delta)
        recovered = _recovered_flows(before, after, delta)

        # L2: the failover twin for this step's implied host removals, evaluated on the PRE-step topology.
        twin = failover.compute_failover_twin(before, _step_failures(step))
        stp, fhrp = twin["stp"], twin["fhrp"]

        removed = _removed_by_step(before, after) if action in ("fail_node", "fail_site") else []
        is_noop = (action not in _ACTIONS) or _step_is_noop(before, after, action)

        n_reroot = sum(1 for r in stp if not r.get("indeterminate"))
        n_take = sum(1 for r in fhrp if not r.get("indeterminate") and r.get("new_active"))
        n_split = sum(1 for r in fhrp if r.get("split_brain_risk"))
        n_indet = (sum(1 for r in stp if r.get("indeterminate"))
                   + sum(1 for r in fhrp if r.get("indeterminate")))

        step_rows.append({
            "step_index": idx,
            "action": action,
            "params": {k: v for k, v in step.items() if k != "action"},
            "removed_hosts": removed,
            "newly_lost_flows": newly_lost,
            "recovered_flows": recovered,
            "stp_reroots": stp,
            "fhrp_takeovers": [r for r in fhrp if r.get("new_active") and not r.get("indeterminate")],
            "split_brain_risks": [r for r in fhrp if r.get("split_brain_risk")],
            "indeterminate": n_indet,
            "is_noop": is_noop,
            "narrative": _narrative(action, step, removed, len(newly_lost), len(recovered), stp, fhrp, is_noop),
        })
        total_lost += len(newly_lost)
        total_recovered += len(recovered)
        total_reroots += n_reroot
        total_takeovers += n_take
        total_split += n_split
        total_indet += n_indet
        current = after                                     # accumulate the wave

    worst_step = _worst_step(step_rows)
    return {
        "schema": "cutover_sim/1",
        "steps": step_rows,
        "worst_step": worst_step,
        "summary": {
            "n_steps": len(step_rows),
            "total_newly_lost": total_lost,
            "total_recovered": total_recovered,
            "total_stp_reroots": total_reroots,
            "total_fhrp_takeovers": total_takeovers,
            "total_split_brain_risks": total_split,
            "total_indeterminate": total_indet,
            "n_noop_steps": sum(1 for r in step_rows if r["is_noop"]),
        },
    }


def _lost_flows(before: Dict[str, Any], after: Dict[str, Any], delta: Dict[str, Any]) -> List[dict]:
    """Flows this step took OFFLINE: fib's definitive newly_blocked PLUS the coverage-honest 'path lost'
    (was computed-reached in `before`, now inconclusive because the trail went off-scan). Mirrors whatif's
    lost-vs-blocked discipline: a lost flow is never a fabricated block, but IS surfaced, not swallowed."""
    out = [{**p, "kind": "blocked"} for p in delta.get("newly_blocked", [])]
    for p in delta.get("inconclusive_pairs", []):
        if str(p.get("old_status", "")).startswith("computed:reached"):
            out.append({**p, "kind": "path_lost"})
    return out


def _recovered_flows(before: Dict[str, Any], after: Dict[str, Any], delta: Dict[str, Any]) -> List[dict]:
    """Flows this step brought back: fib's newly_reachable (was not computed-reached, now is). A later step
    restoring a path a middle step stranded shows up here."""
    return [{**p, "kind": "recovered"} for p in delta.get("newly_reachable", [])]


def _removed_by_step(before: Dict[str, Any], after: Dict[str, Any]) -> List[str]:
    """Which route-owning hosts a fail_node/fail_site step removed (before minus after in snap['routes'])."""
    b = set((before.get("routes") or {}).keys()) if isinstance(before.get("routes"), dict) else set()
    a = set((after.get("routes") or {}).keys()) if isinstance(after.get("routes"), dict) else set()
    return sorted(b - a)


def _step_is_noop(before: Dict[str, Any], after: Dict[str, Any], action: str) -> bool:
    """Did a KNOWN action actually change anything the twins read? A fail_* that matched no host, a
    shut_link on an unknown interface, or a move that couldn't resolve a target leaves the relevant sections
    identical — a genuine no-op the report must flag (never a silent skip)."""
    if action in ("fail_node", "fail_site"):
        return _removed_by_step(before, after) == []
    if action == "shut_link":
        return (before.get("routes") == after.get("routes"))
    if action == "move_fhrp_active":
        return (before.get("fhrp_detail") == after.get("fhrp_detail"))
    return True


def _worst_step(step_rows: List[Dict[str, Any]]) -> Optional[int]:
    """The step_index that took the most flows offline (newly-lost). Ties resolve to the EARLIEST step (the
    first time the damage peaks). None if the whole wave loses nothing."""
    worst_idx, worst_n = None, 0
    for r in step_rows:
        n = len(r["newly_lost_flows"])
        if n > worst_n:
            worst_idx, worst_n = r["step_index"], n
    return worst_idx
