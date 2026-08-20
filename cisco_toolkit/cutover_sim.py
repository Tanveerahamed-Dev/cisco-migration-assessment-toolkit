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
import json
import math
from typing import Any, Dict, List, Optional, Tuple

from . import failover, fib, whatif

# Supported step actions. A step is {action, ...params}; an unknown action is a coverage-honest invalid no-op
# reported under a fixed category (never echoed or silently dropped), so a typo cannot pass green.
_ACTIONS = ("fail_node", "fail_site", "shut_link", "move_fhrp_active")
_ACTION_PARAMS = {
    "fail_node": ("id",),
    "fail_site": ("id",),
    "shut_link": ("host", "interface"),
    "move_fhrp_active": ("ifname", "group", "to_host"),
}
_INVALID_STEP_ACTION = "invalid_step"
_UNSUPPORTED_ACTION = "unsupported_action"
_MAX_SNAPSHOT_DEPTH = 128
_MAX_SNAPSHOT_NODES = 100_000
_MAX_STEPS = 1_000
_MAX_STEP_TOKEN_LENGTH = 256
_SNAPSHOT_CONTRACT_ERROR = (
    "snapshot exceeds the safe JSON mutation depth, size, or strict-scalar contract"
)


# --------------------------------------------------------------------- step mutations ---

def _step_token(value: Any) -> str:
    """Return a deterministic JSON-safe step token without stringifying arbitrary external objects."""
    if isinstance(value, str):
        if len(value) > _MAX_STEP_TOKEN_LENGTH:
            return ""
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            return ""
        value = value.strip()
        if any(ord(char) < 32 for char in value):
            return ""
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    return ""


def _normalize_step(step: Any) -> Tuple[Dict[str, str], int]:
    if type(step) is not dict:
        return {"action": _INVALID_STEP_ACTION}, 0
    raw = step
    supplied_action = _step_token(raw.get("action"))
    action = supplied_action if supplied_action in _ACTIONS else _UNSUPPORTED_ACTION
    allowed = _ACTION_PARAMS.get(action, ())
    normalized = {"action": action}
    for key in allowed:
        if key in raw:
            normalized[key] = _step_token(raw.get(key))
    recognized = ("action",) + allowed
    ignored = max(0, len(raw) - sum(1 for key in recognized if key in raw))
    return normalized, ignored


def _is_unicode_scalar_string(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    return not any(0xD800 <= ord(char) <= 0xDFFF for char in value)


def _snapshot_within_clone_limits(value: Any) -> bool:
    """Validate the bounded strict-JSON domain before recursive consumers touch a snapshot.

    This intentionally rejects Python-only mapping keys, containers, aliases with cycles, non-finite floats,
    and lone UTF-16 surrogates.  All can enter through an in-process caller even though a conforming JSON
    decoder would not produce them; several downstream twins recurse or stringify leaves and therefore must
    never see those values at the public cutover boundary.
    """
    if not isinstance(value, dict):
        return False
    stack = [("enter", value, 0)]
    active: set[int] = set()
    nodes = 0
    while stack:
        phase, current, depth = stack.pop()
        if phase == "exit":
            active.discard(id(current))
            continue
        nodes += 1
        if nodes > _MAX_SNAPSHOT_NODES or depth > _MAX_SNAPSHOT_DEPTH:
            return False
        if isinstance(current, dict):
            identity = id(current)
            if identity in active or len(current) > _MAX_SNAPSHOT_NODES - nodes:
                return False
            active.add(identity)
            stack.append(("exit", current, depth))
            for key, child in current.items():
                if not _is_unicode_scalar_string(key):
                    return False
                nodes += 1
                if nodes > _MAX_SNAPSHOT_NODES:
                    return False
                stack.append(("enter", child, depth + 1))
        elif isinstance(current, list):
            identity = id(current)
            if identity in active or len(current) > _MAX_SNAPSHOT_NODES - nodes:
                return False
            active.add(identity)
            stack.append(("exit", current, depth))
            stack.extend(("enter", child, depth + 1) for child in current)
        elif isinstance(current, str):
            if not _is_unicode_scalar_string(current):
                return False
        elif isinstance(current, float):
            if not math.isfinite(current):
                return False
        elif isinstance(current, int):
            # Keep JSON serialization total even for Python-created integers that exceed the interpreter's
            # integer-to-decimal safety limit. This is far above any plausible network counter or identifier.
            if current.bit_length() > 4096:
                return False
        elif current is not None:
            return False
    return True


def _strict_json_serializable(value: Any) -> bool:
    """Prove that a public result has one finite, Unicode-scalar strict-JSON representation."""
    try:
        json.dumps(value, allow_nan=False, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    except (MemoryError, OverflowError, RecursionError, TypeError, UnicodeEncodeError, ValueError):
        return False
    return True


def _l2_input_malformed(snap: Dict[str, Any]) -> bool:
    """Detect L2 shapes whose leaves a legacy twin might stringify into public evidence.

    The simulator does not need to reject unrelated snapshot extensions.  It does need to abstain before
    passing a mapping/list masquerading as an STP/FHRP identifier into ``failover.py``: doing so both invents
    an election key and can echo an external nested value through ``str(value)``.
    """
    stp = snap.get("stp_roots")
    if stp is not None:
        if not isinstance(stp, dict):
            return True
        for host, per_vlan in stp.items():
            if not _step_token(host):
                return True
            if not isinstance(per_vlan, dict):
                return True
            for vlan, record in per_vlan.items():
                if not _step_token(vlan):
                    return True
                if not isinstance(record, dict):
                    return True
                for field in ("root_priority", "root_address", "is_root", "bridge_priority", "is_mst"):
                    if isinstance(record.get(field), (dict, list)):
                        return True
    fhrp = snap.get("fhrp_detail")
    if fhrp is not None:
        if not isinstance(fhrp, dict):
            return True
        for host, members in fhrp.items():
            if not _step_token(host):
                return True
            if not isinstance(members, list):
                return True
            for member in members:
                if not isinstance(member, dict):
                    return True
                for field in ("ifname", "group", "state", "priority", "preempt", "vip", "version"):
                    if isinstance(member.get(field), (dict, list)):
                        return True
                for field in ("ifname", "group", "state", "vip"):
                    if field in member and member.get(field) is not None and not _step_token(member.get(field)):
                        return True
    return False


def _fhrp_members(snap: Dict[str, Any], ifname: Any, group: Any) -> List[tuple]:
    """Collected members of one exact (interface, group) tuple, with normalized interface matching."""
    fd = snap.get("fhrp_detail")
    if not isinstance(fd, dict):
        return []
    want_if = _norm_intf(ifname)
    want_grp = _step_token(group)
    members: List[tuple] = []
    for host, mlist in fd.items():
        if not isinstance(mlist, list):
            continue
        for member in mlist:
            if isinstance(member, dict) and _norm_intf(member.get("ifname")) == want_if \
                    and _step_token(member.get("group")) == want_grp:
                members.append((host, member))
    return members


def _validate_fhrp_move(snap: Dict[str, Any], step: Dict[str, Any]) -> List[str]:
    """Validate the group and target before changing either member's state."""
    errors: List[str] = []
    if not _norm_intf(step.get("ifname")):
        errors.append("ifname is required")
    if not _step_token(step.get("group")):
        errors.append("group is required")
    if errors:
        return errors
    members = _fhrp_members(snap, step.get("ifname"), step.get("group"))
    if len(members) < 2:
        return ["FHRP group not found with at least two collected members"]
    hosts = [host for host, _member in members]
    if len(set(hosts)) != len(hosts):
        errors.append("FHRP group contains duplicate member records for a host")
    actives = [(host, member) for host, member in members
               if _step_token(member.get("state")).lower() in ("active", "master")]
    if len(actives) != 1:
        errors.append(f"FHRP group must have exactly one observed forwarding member (found {len(actives)})")
    vips = {_step_token(m.get("vip")) for _h, m in members}
    versions = {_step_token(m.get("version")) for _h, m in members}
    if "" in vips or len(vips) != 1:
        errors.append("FHRP group members do not share one non-empty virtual IP")
    if len(versions - {""}) > 1:
        errors.append("FHRP group members use inconsistent protocol versions")
    target = _step_token(step.get("to_host"))
    if target:
        if target not in hosts:
            errors.append("target host is not a member of the requested FHRP group")
        elif actives and target == actives[0][0]:
            errors.append("target host is already the active member")
    elif actives:
        candidates = [(h, m) for h, m in members if h != actives[0][0]]
        priorities = [failover._int_or(m.get("priority"), None) for _h, m in candidates]
        if not candidates:
            errors.append("FHRP group has no alternate target")
        elif any(p is None for p in priorities):
            errors.append("default target cannot be proven because an alternate priority is missing")
        elif priorities.count(max(priorities)) > 1:
            errors.append("default target is ambiguous because alternate priorities tie; specify to_host")
    return errors


def _validate_step(snap: Dict[str, Any], step: Dict[str, Any]) -> List[str]:
    action = _step_token((step or {}).get("action"))
    if action == _INVALID_STEP_ACTION:
        return ["step must be an object"]
    if action not in _ACTIONS:
        return ["unsupported action"]
    if action in ("fail_node", "fail_site"):
        malformed = 0
        for section in ("routes", "stp_roots", "fhrp_detail"):
            rows = snap.get(section)
            if not isinstance(rows, dict):
                continue
            for host in rows:
                if not isinstance(host, str) or not _step_token(host):
                    malformed += 1
        if malformed:
            return [f"snapshot contains {malformed} malformed host key(s)"]
    if action in ("fail_node", "fail_site") and not _step_token(step.get("id")):
        return ["id is required"]
    if action == "shut_link":
        errors = []
        if not _step_token(step.get("host")):
            errors.append("host is required")
        if not _norm_intf(step.get("interface")):
            errors.append("interface is required")
        return errors
    if action == "move_fhrp_active":
        if _l2_input_malformed(snap):
            return ["FHRP evidence contains malformed fields"]
        return _validate_fhrp_move(snap, step)
    return []

def _apply_step(before: Dict[str, Any], step: Dict[str, Any]) -> Dict[str, Any]:
    """Return a DEEP COPY of `before` with `step` applied. Never mutates `before`. Unknown/malformed steps
    return an untouched deep copy (a no-op) — the caller flags them so nothing is silently skipped."""
    after = copy.deepcopy(before)
    if _validate_step(before, step):
        return after
    action = _step_token((step or {}).get("action"))
    if action == "fail_node":
        _remove_hosts(after, [{"type": "node", "id": step.get("id")}])
    elif action == "fail_site":
        _remove_hosts(after, [{"type": "site", "id": step.get("id")}])
    elif action == "shut_link":
        _shut_link(after, step.get("host"), step.get("interface"))
    elif action == "move_fhrp_active":
        _move_fhrp_active(after, step.get("ifname"), step.get("group"), step.get("to_host"))
    return after


def apply_cutover_step(snap: Dict[str, Any], step: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Apply one supported synthetic cutover mutation and return ``(after, receipt)``.

    This is the public, read-only mutation boundary shared by the ordered cutover simulator and any
    higher-level assurance composer.  Keeping it here prevents consumers from reimplementing node/site/link
    mutation semantics.  ``after`` is always a deep copy; ``snap`` is never mutated.  The receipt is exhaustive
    and fail-closed: malformed/unsupported steps are invalid no-ops, while a valid step that matches no collected
    state is a disclosed no-op rather than a claimed resilience pass.

    Receipt shape::

        {action, params, valid, validation_errors, is_noop, removed_hosts}
    """
    normalized, ignored_field_count = _normalize_step(step)
    action = normalized["action"]
    if not _snapshot_within_clone_limits(snap):
        return {}, {
            "action": action,
            "params": {k: v for k, v in normalized.items() if k != "action"},
            "valid": False,
            "validation_errors": [_SNAPSHOT_CONTRACT_ERROR],
            "is_noop": True,
            "removed_hosts": [],
            "ignored_field_count": ignored_field_count,
        }
    before = snap
    validation_errors = _validate_step(before, normalized)
    try:
        after = _apply_step(before, normalized)
    except (RecursionError, MemoryError):
        return {}, {
            "action": action,
            "params": {k: v for k, v in normalized.items() if k != "action"},
            "valid": False,
            "validation_errors": ["snapshot could not be copied within the safe mutation boundary"],
            "is_noop": True,
            "removed_hosts": [],
            "ignored_field_count": ignored_field_count,
        }
    removed = _removed_by_step(before, after) if action in ("fail_node", "fail_site") else []
    is_noop = (action not in _ACTIONS) or _step_is_noop(before, after, action)
    return after, {
        "action": action,
        "params": {k: v for k, v in normalized.items() if k != "action"},
        "valid": not validation_errors,
        "validation_errors": validation_errors,
        "is_noop": is_noop,
        "removed_hosts": removed,
        "ignored_field_count": ignored_field_count,
    }


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
    h = _step_token(host)
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
    probe = {"ifname": ifname, "group": group, "to_host": to_host}
    if _validate_fhrp_move(snap, probe):
        return
    fd = snap.get("fhrp_detail")
    if not isinstance(fd, dict):
        return
    want_if = _norm_intf(ifname)
    want_grp = _step_token(group)
    # collect (host, member_dict) for the target group across all hosts
    members = []
    for host, mlist in fd.items():
        if not isinstance(mlist, list):
            continue
        for m in mlist:
            if isinstance(m, dict) and _norm_intf(m.get("ifname")) == want_if \
                    and _step_token(m.get("group")) == want_grp:
                members.append((host, m))
    if len(members) < 2:
        return                                       # nothing to move to (single-homed / not found) — no-op
    cur = failover._current_active([{**m, "host": h} for h, m in members])
    cur_host = _step_token(cur.get("host")) if cur else None
    target_host = _step_token(to_host)
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
    return _step_token(name).lower().replace(" ", "")


# ------------------------------------------------------------------ step failure set ---

def _step_failures(step: Dict[str, Any]) -> List[dict]:
    """The whatif-shaped failures a step implies for the L2 failover twin. fail_node/fail_site map to a
    node/site removal; shut_link and move_fhrp_active remove no HOST, so they imply no twin re-election
    input on their own (their L2 effect is captured by re-running the twin over the mutated snapshot with
    an empty failure set, which yields no reroots — correct, since no bridge disappeared)."""
    action = _step_token((step or {}).get("action"))
    if action == "fail_node":
        return [{"type": "node", "id": step.get("id")}]
    if action == "fail_site":
        return [{"type": "site", "id": step.get("id")}]
    return []


def _fhrp_moves(before: Dict[str, Any], after: Dict[str, Any]) -> List[dict]:
    """Groups whose PROVABLE forwarding member changed between `before` and `after` — the takeover a
    move_fhrp_active step actually performs (which `_step_failures` implies no host removal for, so the
    twin alone never reports it). Diffs failover._current_active per group (coverage-honest: only groups
    with an explicitly-observed Active/Master on one side or the other produce a row)."""
    def _actives(snap: Dict[str, Any]) -> Dict[str, dict]:
        out: Dict[str, dict] = {}
        for key, members in failover._fhrp_groups(snap).items():
            a = failover._current_active(members)
            if a is not None:
                out[key] = a
        return out
    b, a = _actives(before), _actives(after)
    rows: List[dict] = []
    for key in sorted(set(b) | set(a)):
        bh = str(b[key].get("host")) if key in b else None
        ah = str(a[key].get("host")) if key in a else None
        if bh == ah:
            continue
        m = a.get(key) or b.get(key)
        rows.append({
            "group": str(m.get("group", "")), "ifname": str(m.get("ifname", "")), "vip": m.get("vip", ""),
            "version": m.get("version"), "old_active": bh, "new_active": ah, "new_active_priority": None,
            "split_brain_risk": False, "indeterminate": False,
            "reason": "FHRP forwarding role moved by the cutover step (intentional)",
        })
    return rows


# ------------------------------------------------------------------- narrative maker ---

def _narrative(action: str, step: Dict[str, Any], removed: List[str], n_lost: int, n_recovered: int,
               stp: List[dict], fhrp: List[dict], is_noop: bool,
               validation_errors: Optional[List[str]] = None,
               l2_continuity: Optional[Dict[str, Any]] = None) -> str:
    """A plain-English one-liner for a step. Coverage-honest wording: 'path lost (inconclusive)' phrasing,
    never a claimed hard block unless fib returned one."""
    if validation_errors:
        return ("step rejected as INVALID - no topology mutation was applied: "
                + "; ".join(x for x in validation_errors if isinstance(x, str)))
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
    n_reroot = sum(1 for r in stp if not r.get("indeterminate") and r.get("new_root"))
    if n_reroot:
        impact.append(f"{n_reroot} STP election candidate(s) projected")
    n_take = sum(1 for r in fhrp if not r.get("indeterminate") and r.get("new_active"))
    if n_take:
        impact.append(f"{n_take} FHRP election candidate(s) projected")
    n_sb = sum(1 for r in fhrp if r.get("split_brain_risk"))
    if n_sb:
        impact.append(f"{n_sb} split-brain/stranded risk(s)")
    if isinstance(l2_continuity, dict) and l2_continuity.get("applicable") is True \
            and l2_continuity.get("assessed") is not True:
        impact.append("L2 continuity not assessed")
    if not impact:
        impact.append("no reachability or L2 change proven")
    return f"After {parts[0]}: " + "; ".join(impact) + "."


# ------------------------------------------------------------------------- simulator ---

def _bounded_count(value: Any, default: int, maximum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        return default
    return min(max(value, 0), maximum)


def _normalize_pairs(pairs: Any, maximum: int) -> Tuple[Optional[List[tuple]], Optional[str]]:
    if not isinstance(pairs, (list, tuple)):
        return None, "pairs must be an array of source/destination pairs"
    if len(pairs) > maximum:
        return None, "pairs exceed the bounded cutover simulation limit"
    normalized: List[tuple] = []
    for pair in pairs:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            return None, "pairs contain a malformed source/destination entry"
        src, dst = _step_token(pair[0]), _step_token(pair[1])
        if not src or not dst:
            return None, "pairs contain a malformed source/destination entry"
        normalized.append((src, dst))
    return normalized, None


def _invalid_simulation(error: str) -> Dict[str, Any]:
    """Return one fixed, strict-JSON fail-closed envelope for a malformed simulator-level input."""
    return {
        "schema": "cutover_sim/1",
        "valid": False,
        "validation_errors": [error],
        "steps": [],
        "worst_step": None,
        "summary": {
            "n_steps": 0,
            "total_newly_lost": 0,
            "total_recovered": 0,
            "total_stp_reroots": 0,
            "total_fhrp_takeovers": 0,
            "total_stp_election_candidates": 0,
            "total_fhrp_election_candidates": 0,
            "total_split_brain_risks": 0,
            "total_indeterminate": 1,
            "n_noop_steps": 0,
            "n_invalid_steps": 0,
            "n_input_errors": 1,
        },
    }

def simulate_cutover(snap: Dict[str, Any], steps: List[Dict[str, Any]],
                     pairs: Optional[list] = None, limit: int = 24, max_pairs: int = 400) -> Dict[str, Any]:
    """Dry-run an ordered cutover wave. `steps` is an ordered list of graph mutations, each a dict:
        {action:'fail_node', id:<host>}
        {action:'fail_site', id:<site-code-substring>}
        {action:'shut_link', host:<host>, interface:<egress ifname>}
        {action:'move_fhrp_active', ifname:<Vlan..>, group:<n>, to_host:<host>?}

    Applies each step step-by-step on a running deep COPY of `snap`, and at each step reports the MARGINAL
    effect vs the state just before it: the fib reachability delta (newly-lost / recovered flows) and the
    L2 election twin (STP/FHRP candidates and split-brain risks). The flow-test pairs are derived ONCE
    from the ORIGINAL snapshot (so 'lost' and 'recovered' reference the same fixed flow set across steps).

    Returns {schema:'cutover_sim/1', steps:[…], worst_step, summary}. Each step row:
        {step_index, action, params, removed_hosts, newly_lost_flows, recovered_flows, stp_reroots,
         fhrp_takeovers, split_brain_risks, indeterminate, is_noop, narrative}.
    worst_step = the index of the step with the most newly-lost flows (ties -> the earliest); None if the
    wave loses nothing. Summary distinguishes election candidates from completed continuity outcomes.

    COVERAGE-HONEST: a lost flow is 'path lost (inconclusive)', never a fabricated block; only fib's own
    definitive newly_blocked is a hard drop. The input snapshot is NEVER mutated (deep copy per step)."""
    if not _snapshot_within_clone_limits(snap):
        return _invalid_simulation(_SNAPSHOT_CONTRACT_ERROR)
    if steps is None:
        safe_steps: List[Any] = []
    elif isinstance(steps, (list, tuple)):
        if len(steps) > _MAX_STEPS:
            return _invalid_simulation("steps exceed the bounded cutover simulation limit")
        safe_steps = list(steps)
    else:
        return _invalid_simulation("steps must be an array")
    safe_limit = _bounded_count(limit, 24, 10_000)
    safe_max_pairs = _bounded_count(max_pairs, 400, 10_000)
    try:
        if pairs is None:
            safe_pairs = fib.default_pairs(snap, safe_limit, safe_max_pairs)
        else:
            safe_pairs, pair_error = _normalize_pairs(pairs, safe_max_pairs)
            if pair_error:
                return _invalid_simulation(pair_error)
        current = copy.deepcopy(snap)                       # running state; the caller's snapshot stays untouched
    except (Exception, MemoryError):
        return _invalid_simulation("snapshot shape is unsupported for cutover simulation")

    step_rows: List[Dict[str, Any]] = []
    total_lost = total_recovered = total_split = total_indet = 0
    total_stp_candidates = total_fhrp_candidates = 0

    for idx, step in enumerate(safe_steps):
        before = current
        try:
            after, mutation = apply_cutover_step(before, step)
        except (Exception, MemoryError):
            normalized, ignored_field_count = _normalize_step(step)
            try:
                after = copy.deepcopy(before)
            except (Exception, MemoryError):
                return _invalid_simulation("snapshot could not be copied within the safe mutation boundary")
            mutation = {
                "action": normalized["action"],
                "params": {k: v for k, v in normalized.items() if k != "action"},
                "valid": False,
                "validation_errors": ["step could not be evaluated from the provided snapshot shape"],
                "is_noop": True,
                "removed_hosts": [],
                "ignored_field_count": ignored_field_count,
            }
        action = mutation["action"]
        safe_step = {"action": action, **mutation["params"]}
        validation_errors = list(mutation["validation_errors"])
        newly_lost: List[dict] = []
        recovered: List[dict] = []
        stp: List[dict] = []
        fhrp: List[dict] = []
        l2_input_malformed = _l2_input_malformed(before)

        if not validation_errors:
            try:
                # L3: marginal reachability change from this step, over the fixed original flow set.
                delta = fib.reachability_delta(before, after, pairs=safe_pairs)
                newly_lost = _lost_flows(before, after, delta)
                recovered = _recovered_flows(before, after, delta)

                # L2 election projection is evaluated on the pre-step topology.
                if not l2_input_malformed:
                    twin = failover.compute_failover_twin(before, _step_failures(safe_step))
                    stp, fhrp = twin["stp"], twin["fhrp"]
                    if action == "move_fhrp_active":
                        # A move has no failed host, so disclose its projected candidate explicitly.
                        fhrp = fhrp + _fhrp_moves(before, after)
            except (Exception, MemoryError):
                validation_errors.append("step evidence could not be evaluated from the provided snapshot shape")
                newly_lost, recovered, stp, fhrp = [], [], [], []
                mutation["removed_hosts"] = []
                mutation["is_noop"] = True
                try:
                    after = copy.deepcopy(before)
                except (Exception, MemoryError):
                    return _invalid_simulation("snapshot could not be copied within the safe mutation boundary")

        # These twins project an election candidate from the collected state. They do not observe L2
        # component continuity, client attachment, convergence, or surviving-gateway reachability, so a
        # candidate winner must never be mistaken for proof that an application flow is preserved.
        stp = [{**row, "election_candidate_only": True, "continuity_assessed": False}
               for row in stp if isinstance(row, dict)]
        fhrp = [{**row, "election_candidate_only": True, "continuity_assessed": False}
                for row in fhrp if isinstance(row, dict)]
        removed = mutation["removed_hosts"]
        is_noop = mutation["is_noop"]
        stp_hosts = set(before["stp_roots"]) if isinstance(before.get("stp_roots"), dict) else set()
        fhrp_hosts = set(before["fhrp_detail"]) if isinstance(before.get("fhrp_detail"), dict) else set()
        l2_member_hosts = stp_hosts | fhrp_hosts
        affected_member_hosts = sorted(set(removed) & l2_member_hosts)
        l2_projection_count = len(stp) + len(fhrp)
        # Absence from STP/FHRP rows is not proof that a failed node/site has no client attachment or first-hop
        # role. Until a positive non-L2 role receipt exists, node/site/link mutations require an L2 continuity
        # disposition and therefore abstain rather than silently treating missing membership as not applicable.
        l2_applicable = bool(l2_projection_count or affected_member_hosts or (
            not is_noop and action in ("fail_node", "fail_site", "shut_link", "move_fhrp_active")
        ))
        l2_continuity = {
            "applicable": l2_applicable,
            "assessed": False if l2_applicable else None,
            "verdict": "INDETERMINATE" if l2_applicable else "not_applicable",
            "election_projection_count": l2_projection_count,
            "affected_member_count": len(affected_member_hosts),
            "affected_member_hosts": affected_member_hosts,
            "reason": (
                "L2 election evidence contains malformed fields; continuity was not assessed"
                if l2_applicable and l2_input_malformed else
                "affected L2 membership or link mutation is present, but election candidates do not prove "
                "client attachment, component continuity, convergence, or surviving-gateway reachability"
                if l2_applicable else "no L2-affecting mutation or election projection was requested"
            ),
        }

        n_stp_candidates = sum(1 for r in stp if not r.get("indeterminate") and r.get("new_root"))
        n_fhrp_candidates = sum(1 for r in fhrp if not r.get("indeterminate") and r.get("new_active"))
        n_split = sum(1 for r in fhrp if r.get("split_brain_risk"))
        n_indet = (sum(1 for r in stp if r.get("indeterminate"))
                   + sum(1 for r in fhrp if r.get("indeterminate"))
                   + (1 if l2_applicable else 0)
                   + (1 if validation_errors else 0))

        step_rows.append({
            "step_index": idx,
            "action": action,
            "params": mutation["params"],
            "ignored_field_count": mutation["ignored_field_count"],
            "removed_hosts": removed,
            "newly_lost_flows": newly_lost,
            "recovered_flows": recovered,
            "stp_reroots": stp,
            "fhrp_takeovers": [r for r in fhrp if r.get("new_active") and not r.get("indeterminate")],
            "split_brain_risks": [r for r in fhrp if r.get("split_brain_risk")],
            "l2_continuity": l2_continuity,
            "n_stp_election_candidates": n_stp_candidates,
            "n_fhrp_election_candidates": n_fhrp_candidates,
            "indeterminate": n_indet,
            "valid": not validation_errors,
            "validation_errors": validation_errors,
            "is_noop": is_noop,
            "narrative": _narrative(
                action, safe_step, removed, len(newly_lost), len(recovered), stp, fhrp, is_noop,
                validation_errors, l2_continuity),
        })
        total_lost += len(newly_lost)
        total_recovered += len(recovered)
        total_stp_candidates += n_stp_candidates
        total_fhrp_candidates += n_fhrp_candidates
        total_split += n_split
        total_indet += n_indet
        current = after                                     # accumulate the wave

    worst_step = _worst_step(step_rows)
    result = {
        "schema": "cutover_sim/1",
        "valid": not any(not row["valid"] for row in step_rows),
        "validation_errors": [],
        "steps": step_rows,
        "worst_step": worst_step,
        "summary": {
            "n_steps": len(step_rows),
            "total_newly_lost": total_lost,
            "total_recovered": total_recovered,
            # Election projections are not completed continuity outcomes. Preserve the legacy counters but
            # leave them at zero; publish the candidate census under explicit names.
            "total_stp_reroots": 0,
            "total_fhrp_takeovers": 0,
            "total_stp_election_candidates": total_stp_candidates,
            "total_fhrp_election_candidates": total_fhrp_candidates,
            "total_split_brain_risks": total_split,
            "total_indeterminate": total_indet,
            "n_noop_steps": sum(1 for r in step_rows if r["is_noop"]),
            "n_invalid_steps": sum(1 for r in step_rows if not r["valid"]),
            "n_input_errors": 0,
        },
    }
    if not _strict_json_serializable(result):
        return _invalid_simulation("cutover evidence could not be represented as strict JSON")
    return result


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
    """Which twin-owned hosts a fail_node/fail_site step removed across the L2/L3 evidence union."""
    def hosts(snap: Dict[str, Any]) -> set:
        out = set()
        for section in ("routes", "stp_roots", "fhrp_detail"):
            rows = snap.get(section)
            if isinstance(rows, dict):
                out.update(host for host in rows if isinstance(host, str) and _step_token(host))
        return out

    b = hosts(before)
    a = hosts(after)
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
