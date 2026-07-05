"""Offline NRFU (Network Ready For Use) verification-command export — orchestration-roadmap frontier.

compute_nrfu_commands(snap) turns the collected pre-cutover snapshot into the canonical FOUR-PHASE NRFU
certification pack a cutover team executes to certify a wave: every case carries the exact READ-ONLY
command to run plus the EXPECTED value pre-filled from the snapshot evidence (ASSERTIVE, not
informational) and cites the snapshot key the expectation came from (source_key). Missing evidence is
NEVER fabricated: the expected value is the explicit NOT_OBSERVED abstention marker (coverage-honesty
doctrine — absence of evidence is never health, and a baseline the collection did not capture is
recorded at execution, not invented here).

The canonical four phases:
  I    device-level — show version (expect the collected version), module/inventory presence,
                      environment (where collected)
  II   logical      — interface status for the known-up ports, port-channel member counts,
                      spanning-tree root per VLAN, HSRP/standby active-standby, OSPF/EIGRP/BGP
                      neighbor sets, CDP adjacency set
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
            command, expected, source_key}]}]}], summary}

write_nrfu_pack(snap, out_dir) emits the per-device .txt command files per wave (pure function of the
snapshot). A --nrfu-pack CLI flag is DEFERRED — call write_nrfu_pack directly or consume the published
snap['nrfu_commands'] section.
"""
import os
import re
from collections import Counter
from typing import Dict, List, Optional

from cisco_toolkit.analyze import _is_nxos

NRFU_SCHEMA = "nrfu_commands/1"

# The abstention marker (coverage-honesty): evidence the collection did not capture is recorded at
# execution time by the engineer — never pre-filled with a guess.
NOT_OBSERVED = "[NOT OBSERVED — record baseline at execution]"

UNSCHEDULED_WAVE = "(unscheduled)"

NRFU_BANNER = ("Four-phase NRFU certification pack: run each READ-ONLY command and confirm the output "
               "MATCHES the pre-filled EXPECTED value (captured from the pre-cutover snapshot; the source "
               "key cites the evidence). A deviation is a regression to investigate before sign-off. "
               "'[NOT OBSERVED …]' rows are honest abstentions — record the baseline at execution. "
               "Phase IV rows are HUMAN-EXECUTED with the application owner.")

_PHASE_ROMAN = {1: "I", 2: "II", 3: "III", 4: "IV"}


def _as_dict(v) -> dict:
    return v if isinstance(v, dict) else {}


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

    hosts = sorted(set(devices) | set(interfaces))

    # host -> wave label ("Group N", enumerated exactly like compute_validation_plan /
    # compute_migration_readiness). A host in no multi-switch group still gets its certification
    # cases under "(unscheduled)" so nothing is silently skipped (coverage-honesty).
    wave_of: Dict[str, str] = {}
    for gi, g in enumerate(move_groups, 1):
        for h in (g.get("switches") or []) if isinstance(g, dict) else []:
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

        def case(host, phase, scope, command, expected, source_key):
            nonlocal seq
            seq += 1
            cases_by_host.setdefault(host, []).append(
                {"id": f"NRFU-W{wno}-P{phase}-{seq:03d}", "phase": phase, "scope": scope,
                 "command": command, "expected": expected, "source_key": source_key})

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
            bundles: Dict[str, int] = {}
            for p, d in ifaces.items():
                b = _fld(d, "port_channel")
                if b:
                    bundles[b] = bundles.get(b, 0) + 1
            if bundles:      # no bundle configured = feature absent, not missing evidence -> no case
                case(h, 2, "per-site", "show port-channel summary" if nx else "show etherchannel summary",
                     "; ".join(f"{b}: {n} member(s) bundled (P)" for b, n in sorted(bundles.items())),
                     f"interfaces.{h}.*.port_channel")
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
                case(h, 2, "per-site", f"show spanning-tree vlan {vlan}", exp, f"stp_roots.{h}.{vlan}")
            recs = fhrp_detail.get(h)
            fhrp_cmd = "show hsrp brief" if nx else "show standby brief"
            if isinstance(recs, list) and recs:
                exp = "; ".join(
                    f"{_fld(r, 'ifname') or '?'} grp {_fld(r, 'group') or '?'} {_fld(r, 'state') or '?'}"
                    + (f" (VIP {_fld(r, 'vip')})" if _fld(r, "vip") else "")
                    for r in recs if isinstance(r, dict))
                if exp:
                    case(h, 2, "per-site", fhrp_cmd, exp, f"fhrp_detail.{h}")
            else:            # fallback: the per-SVI FHRP behavior string (NX-OS hosts lack fhrp_detail)
                beh = sorted(((p, _fld(d, "hsrp_behavior")) for p, d in ifaces.items()
                              if _fld(d, "hsrp_behavior")), key=lambda t: _port_key(t[0]))
                if beh:
                    case(h, 2, "per-site", fhrp_cmd,
                         "; ".join(f"{p}: {b}" for p, b in beh),
                         f"interfaces.{h}.*.hsrp_behavior")
            nb = _as_dict(rn.get(h))
            for proto, cmd, verb in (("ospf", "show ip ospf neighbor", "in FULL"),
                                     ("eigrp", "show ip eigrp neighbors", "present"),
                                     ("bgp", "show ip bgp summary", "Established")):
                peers = sorted({str(n.get("neighbor")) for n in (nb.get(proto) or [])
                                if isinstance(n, dict) and n.get("neighbor")})
                if peers:
                    case(h, 2, "per-site", cmd,
                         f"{len(peers)} {proto.upper()} neighbor(s) {verb}: {', '.join(peers)}",
                         f"routing_neighbors.{h}.{proto}")
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
            touch = sorted({str(x) for x in (dom.get("switches") or [])} & wave_set)
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
    summary = {"n_waves": len(waves),
               "n_devices": sum(len(w["devices"]) for w in waves),
               "n_cases": len(all_cases),
               "by_phase": dict(Counter(c["phase"] for c in all_cases)),
               "n_not_observed": sum(1 for c in all_cases if c["expected"] == NOT_OBSERVED),
               "n_human_executed": sum(1 for c in all_cases if c["phase"] == 4)}
    return {"schema": NRFU_SCHEMA, "banner": NRFU_BANNER, "waves": waves, "summary": summary}


def _safe_name(s) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", str(s)).strip("_") or "unnamed"


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
    for w in nc.get("waves") or []:
        wdir = os.path.join(out_dir, _safe_name(w.get("wave_id", "wave")))
        for dev in w.get("devices") or []:
            host = str(dev.get("host") or "device")
            os.makedirs(wdir, exist_ok=True)
            lines = [f"! NRFU verification commands — wave {w.get('wave_id')} — device {host} "
                     f"({dev.get('platform_dialect', 'ios')})",
                     f"! {NRFU_BANNER}",
                     "! READ-ONLY: show/ping/traceroute class only; '!' lines are comments.",
                     ""]
            for c in dev.get("cases") or []:
                lines += [f"! {c.get('id')}  [Phase {_PHASE_ROMAN.get(c.get('phase'), c.get('phase'))}]"
                          f" [{c.get('scope')}]",
                          f"!   expect: {c.get('expected')}",
                          f"!   source: {c.get('source_key')}",
                          str(c.get("command") or ""),
                          ""]
            path = os.path.join(wdir, f"{_safe_name(host)}.txt")
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
            written.append(path)
    return sorted(written)
