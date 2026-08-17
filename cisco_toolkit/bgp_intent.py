"""Bounded configured-peer truth for default/global IPv4-unicast BGP.

The older routing projection answers only "which peers were printed by the
summary?".  It cannot answer the cutover question "did every peer configured
for this scope appear?".  This module owns that missing denominator without
pretending to cover VRFs, other address families, templates, dynamic peers, or
policy correctness.

Only normalized facts are returned.  Raw configuration, capture paths, and
arbitrary configuration text never enter the snapshot contract.
"""
from __future__ import annotations

import copy
import hashlib
import ipaddress
import json
import re
from collections import Counter
from typing import Any, Dict, Iterable, List, Optional, Tuple

from cisco_toolkit.input_custody import read_text as read_custodied_text


BGP_CONFIGURED_PEER_SCHEMA = "bgp_configured_peer_baseline/1"
_SCOPE = {
    "routing_instance": "default",
    "afi": "ipv4",
    "safi": "unicast",
    "peer_kind": "direct_static_literal",
}
_STATUS_ORDER = {
    "degraded": 0,
    "review": 1,
    "not_verified": 2,
    "assessed": 3,
    "administratively_disabled": 4,
}
_COVERAGE_STATUS_ORDER = {
    "degraded": 0,
    "review": 1,
    "not_verified": 2,
    "assessed": 3,
    "not_applicable": 4,
}
_FSM_STATES = {
    "IDLE", "ACTIVE", "CONNECT", "OPENSENT", "OPENCONFIRM", "ADMIN-DOWN",
    "IDLE (ADMIN)", "IDLE (ADMIN-DOWN)", "SHUTDOWN",
}
_RUNTIME_VARIANTS = (
    "show bgp ipv4 unicast summary",
    "show bgp ip unicast summary",
    "show ip bgp summary",
    "show bgp summary",
)
_MAX_HOSTS = 4096
_MAX_LINES = 100_000
_MAX_PEERS = 10_000
_SAFE_CAPTURE_STATUSES = {
    "ok", "incomplete", "error", "empty", "unverified_prompt", "unreadable",
    "not_observed", "inspection_missing", "inspection_duplicate",
}
_ROW_KEYS = {
    "switch", "peer", "peer_key", "scope", "local_as", "configured_remote_as",
    "activation", "runtime_observed", "runtime_remote_as", "runtime_state_raw",
    "runtime_state", "status", "command", "acceptance", "source_key",
    "projection_custody", "findings",
}
_COVERAGE_KEYS = {
    "switch", "platform", "subject", "status", "config_command", "config_capture_status",
    "config_parser_status", "runtime_command", "runtime_capture_status",
    "runtime_parser_status", "bgp_stanza_count", "neighbor_candidate_count",
    "supported_peer_count", "rejected_candidate_count", "excluded_scope_count",
    "unsupported_relevant_count", "runtime_candidate_count", "runtime_parsed_count",
    "runtime_rejected_count", "runtime_local_as", "config_sha256", "runtime_sha256",
    "projection_sha256", "finding_codes",
}
_SUMMARY_KEYS = {
    "n_hosts", "n_subject_hosts", "n_configured_peers", "n_active_peers",
    "n_established", "n_degraded", "n_review", "n_not_verified", "n_disabled",
    "by_status", "by_coverage_status", "baseline_sha256",
}
_PARSER_STATUSES = {"complete", "review", "not_verified", "rejected"}
_COVERAGE_STATUSES = set(_COVERAGE_STATUS_ORDER)


class _CurrentRunBgpConfiguredPeerBaseline(dict):
    """Process-local marker; JSON serialization deliberately loses this type."""


def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def _sha(value: Any) -> str:
    try:
        return hashlib.sha256(_json_bytes(value)).hexdigest()
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError):
        return ""


def _text(value: Any, limit: int = 160) -> str:
    if not isinstance(value, str):
        return ""
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return ""
    return value.strip()[:limit]


def _ipv4(value: Any) -> str:
    token = _text(value, 64)
    try:
        address = ipaddress.ip_address(token)
    except ValueError:
        return ""
    return str(address) if address.version == 4 else ""


def _asn(value: Any) -> str:
    token = _text(value, 32)
    try:
        if re.fullmatch(r"\d+", token):
            number = int(token)
        elif re.fullmatch(r"\d+\.\d+", token):
            high, low = (int(part) for part in token.split(".", 1))
            if high > 65535 or low > 65535:
                return ""
            number = high * 65536 + low
        else:
            return ""
    except (TypeError, ValueError):
        return ""
    return str(number) if 0 < number <= 4294967295 else ""


def _platforms(devices: Any) -> Dict[str, str]:
    out: Dict[str, str] = {}
    if isinstance(devices, list):
        rows: Iterable[Any] = devices
    elif isinstance(devices, dict):
        rows = [dict(value, hostname=key) if isinstance(value, dict) else
                {"hostname": key, "platform": value}
                for key, value in devices.items() if isinstance(key, str)]
    else:
        rows = ()
    for row in rows:
        if not isinstance(row, dict):
            continue
        host = _text(row.get("hostname") or row.get("switch"), 128)
        platform = _text(row.get("platform"), 80)
        if host:
            out[host] = platform
    return out


def _is_nxos(platform: str) -> bool:
    token = (platform or "").casefold()
    return "nx" in token or "nexus" in token


def _inspection_index(capture_integrity: Any) -> Tuple[Dict[Tuple[str, str], str], set]:
    index: Dict[Tuple[str, str], str] = {}
    duplicates: set = set()
    source = capture_integrity if isinstance(capture_integrity, dict) else {}
    rows = source.get("inspections")
    if not isinstance(rows, list) or len(rows) > 1_000_000:
        return {}, set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        host = _text(row.get("host"), 128)
        command = _text(row.get("command"), 128)
        status = _text(row.get("status"), 32)
        if not host or not command or status not in _SAFE_CAPTURE_STATUSES:
            continue
        key = (host, command)
        if key in index:
            duplicates.add(key)
        else:
            index[key] = status
    return index, duplicates


def _capture_status(index: Dict[Tuple[str, str], str], duplicates: set,
                    host: str, command: str) -> str:
    key = (host, command)
    if key in duplicates:
        return "inspection_duplicate"
    return index.get(key, "inspection_missing")


def _read_capture(mapping: dict, command: str) -> Tuple[str, str]:
    path = mapping.get(command)
    if not isinstance(path, (str, bytes)):
        return "", "not_observed"
    try:
        body = read_custodied_text(path, encoding="utf-8", errors="ignore")
    except Exception:
        return "", "unreadable"
    return body, "ok"


def _selected_runtime_command(mapping: dict, platform: str,
                              inspections: Optional[Dict[Tuple[str, str], str]] = None,
                              duplicates: Optional[set] = None, host: str = "") -> str:
    variants = _RUNTIME_VARIANTS
    if not _is_nxos(platform):
        variants = (
            "show ip bgp summary", "show bgp ipv4 unicast summary",
            "show bgp ip unicast summary", "show bgp summary",
        )
    present = [command for command in variants if command in mapping]
    # Some NX-OS trains support only one of the two explicitly scoped spellings.
    # Prefer the first integrity-ok capture, just as the legacy loader skips a CLI
    # error before trying its fallback.  If none is usable, retain the first
    # observed command so the exact failed evidence remains disclosed.
    if inspections is not None:
        for command in present:
            if _capture_status(inspections, duplicates or set(), host, command) == "ok":
                return command
    return present[0] if present else ""


def _finding(kind: str, code: str, issue: str) -> dict:
    return {"kind": kind, "code": code, "issue": issue}


def _line_indent(raw: str) -> int:
    expanded = raw.expandtabs(8)
    return len(expanded) - len(expanded.lstrip())


def _parse_config(body: str, platform: str) -> dict:
    """Parse only the explicitly bounded configured-peer subset."""
    lines = (body or "").splitlines()
    findings: List[dict] = []
    if len(lines) > _MAX_LINES:
        return {
            "status": "rejected", "rows": [], "findings": [
                _finding("review", "resource_limit", "Configuration exceeded the bounded parser line limit.")],
            "bgp_stanza_count": 0, "neighbor_candidate_count": 0,
            "supported_peer_count": 0, "rejected_candidate_count": 1,
            "excluded_scope_count": 0, "unsupported_relevant_count": 1,
        }

    router_blocks: List[Tuple[int, str, List[Tuple[int, int, str]]]] = []
    current: Optional[Tuple[int, str, List[Tuple[int, int, str]]]] = None
    for line_no, raw in enumerate(lines, 1):
        stripped = raw.strip()
        match = re.match(r"^router\s+bgp\s+(\S+)\s*$", stripped, re.IGNORECASE)
        if match and _line_indent(raw) == 0:
            if current is not None:
                router_blocks.append(current)
            current = (line_no, match.group(1), [])
            continue
        if current is None:
            continue
        indent = _line_indent(raw)
        if stripped.lower() == "end" or (
                stripped and indent == 0 and stripped != "!" and
                not stripped.lower().startswith("router bgp ")):
            router_blocks.append(current)
            current = None
            continue
        if stripped and stripped != "!":
            current[2].append((line_no, indent, stripped))
    if current is not None:
        router_blocks.append(current)

    if not router_blocks:
        return {
            "status": "complete", "rows": [], "findings": [],
            "bgp_stanza_count": 0, "neighbor_candidate_count": 0,
            "supported_peer_count": 0, "rejected_candidate_count": 0,
            "excluded_scope_count": 0, "unsupported_relevant_count": 0,
        }
    if len(router_blocks) != 1:
        return {
            "status": "review", "rows": [], "findings": [
                _finding("review", "multiple_bgp_processes",
                         "Multiple BGP process stanzas cannot be reconciled to the bounded default instance.")],
            "bgp_stanza_count": len(router_blocks), "neighbor_candidate_count": 0,
            "supported_peer_count": 0, "rejected_candidate_count": 1,
            "excluded_scope_count": 0, "unsupported_relevant_count": 1,
        }

    _router_line, local_raw, block = router_blocks[0]
    local_as = _asn(local_raw)
    if not local_as:
        findings.append(_finding("review", "local_as_invalid", "The BGP local AS is not a bounded numeric ASN."))

    default_ipv4_disabled = any(
        text.casefold() == "no bgp default ipv4-unicast" for _n, _i, text in block)
    peers: Dict[str, dict] = {}
    rejected = 0
    excluded = 0
    unsupported = 0
    candidates = 0
    nxos = _is_nxos(platform)
    platform_token = (platform or "").casefold()
    ios_family = any(token in platform_token for token in ("ios", "ios-xe", "iosxe", "catalyst"))

    # Stack the two nested contexts NX-OS uses. IOS address-family commands are handled by the same AF stack.
    vrf_ctx: Optional[Tuple[int, str]] = None
    af_ctx: Optional[Tuple[int, str]] = None
    neighbor_ctx: Optional[Tuple[int, str]] = None

    def peer_row(peer: str, line_no: int) -> dict:
        return peers.setdefault(peer, {
            "peer": peer, "peer_key": peer, "local_as": local_as,
            "configured_remote_as": "", "explicit_activate": False,
            "explicit_deactivate": False, "shutdown": False,
            "source_line": line_no, "findings": [],
        })

    for line_no, indent, text in block:
        low = text.casefold()
        if vrf_ctx and indent <= vrf_ctx[0]:
            vrf_ctx = None
        if af_ctx and indent <= af_ctx[0]:
            af_ctx = None
        if neighbor_ctx and indent <= neighbor_ctx[0]:
            neighbor_ctx = None

        vrf_match = re.match(r"^vrf\s+(\S+)", text, re.IGNORECASE)
        if vrf_match:
            vrf_ctx = (indent, vrf_match.group(1))
            excluded += 1
            continue
        af_match = re.match(r"^address-family\s+(.+)$", text, re.IGNORECASE)
        if af_match:
            af = " ".join(af_match.group(1).casefold().split())
            af_ctx = (indent, af)
            if af not in ("ipv4", "ipv4 unicast"):
                excluded += 1
            elif neighbor_ctx:
                peer_row(neighbor_ctx[1], line_no)["explicit_activate"] = True
            continue
        if low == "exit-address-family":
            af_ctx = None
            continue

        # NX-OS nested-neighbor properties.
        if neighbor_ctx and indent > neighbor_ctx[0]:
            peer = neighbor_ctx[1]
            row = peer_row(peer, line_no)
            if vrf_ctx:
                excluded += 1
                continue
            remote = re.match(r"^remote-as\s+(\S+)\s*$", text, re.IGNORECASE)
            if remote:
                asn = _asn(remote.group(1))
                if not asn:
                    rejected += 1
                    row["findings"].append(_finding("review", "remote_as_invalid", "Remote AS is not numeric."))
                elif row["configured_remote_as"] and row["configured_remote_as"] != asn:
                    rejected += 1
                    row["findings"].append(_finding("review", "remote_as_conflict", "Conflicting remote AS values were configured."))
                else:
                    row["configured_remote_as"] = asn
                continue
            if low == "shutdown":
                row["shutdown"] = True
                continue
            if low == "no shutdown":
                row["shutdown"] = False
                continue
            if low in ("address-family ipv4", "address-family ipv4 unicast"):
                row["explicit_activate"] = True
                continue

        neighbor = re.match(r"^(no\s+)?neighbor\s+(\S+)(?:\s+(.*))?$", text, re.IGNORECASE)
        if not neighbor:
            if any(token in low for token in ("listen range", "template peer", "peer-session", "peer-policy")):
                unsupported += 1
                findings.append(_finding("review", "unsupported_dynamic_or_template_peer",
                                         "Dynamic/template BGP peers are outside the configured-peer denominator."))
            continue

        negative = bool(neighbor.group(1))
        token = neighbor.group(2)
        tail = (neighbor.group(3) or "").strip()
        peer = _ipv4(token)
        candidates += 1
        if not peer:
            # IPv6 in another AF is an explicit exclusion; named/interface/template peers can affect
            # the default IPv4 denominator and therefore withhold CLEAR.
            try:
                is_ipv6 = ipaddress.ip_address(token).version == 6
            except ValueError:
                is_ipv6 = False
            if is_ipv6 or vrf_ctx or (af_ctx and af_ctx[1] not in ("ipv4", "ipv4 unicast")):
                excluded += 1
            else:
                unsupported += 1
                rejected += 1
                findings.append(_finding("review", "unsupported_peer_identity",
                                         "A non-literal or inherited peer may affect default IPv4 scope."))
            continue
        if vrf_ctx or (af_ctx and af_ctx[1] not in ("ipv4", "ipv4 unicast")):
            excluded += 1
            continue

        row = peer_row(peer, line_no)
        if not tail:
            neighbor_ctx = (indent, peer)
            continue
        remote = re.match(r"^remote-as\s+(\S+)\s*$", tail, re.IGNORECASE)
        if remote:
            asn = _asn(remote.group(1))
            if not asn:
                rejected += 1
                row["findings"].append(_finding("review", "remote_as_invalid", "Remote AS is not numeric."))
            elif row["configured_remote_as"] and row["configured_remote_as"] != asn:
                rejected += 1
                row["findings"].append(_finding("review", "remote_as_conflict", "Conflicting remote AS values were configured."))
            else:
                row["configured_remote_as"] = asn
            continue
        if tail.casefold() == "activate":
            row["explicit_deactivate" if negative else "explicit_activate"] = True
            continue
        if tail.casefold() == "shutdown":
            row["shutdown"] = not negative
            continue
        if any(word in tail.casefold() for word in ("peer-group", "inherit", "listen", "remote-as external", "remote-as internal")):
            unsupported += 1
            findings.append(_finding("review", "unsupported_peer_inheritance",
                                     "Peer-group, inherited, or dynamic remote-AS syntax is outside scope."))

    rows: List[dict] = []
    for peer, row in sorted(peers.items()):
        if not row["configured_remote_as"]:
            rejected += 1
            row["findings"].append(_finding("review", "remote_as_missing",
                                             "No direct numeric remote-as was resolved for this peer."))
        if row["shutdown"] or row["explicit_deactivate"]:
            activation = "disabled"
        elif row["explicit_activate"]:
            activation = "active"
        elif nxos or default_ipv4_disabled or not ios_family:
            activation = "ambiguous"
        else:
            activation = "active"
        rows.append({
            "peer": peer, "peer_key": peer, "local_as": local_as,
            "configured_remote_as": row["configured_remote_as"],
            "activation": activation, "source_line": int(row["source_line"]),
            "findings": row["findings"],
        })

    if unsupported:
        findings.append(_finding("review", "unsupported_relevant_syntax",
                                 "One or more relevant peer/template constructs are outside this bounded parser."))
    parser_status = "complete"
    if findings or rejected or not local_as:
        parser_status = "review"
    return {
        "status": parser_status, "rows": rows, "findings": findings,
        "bgp_stanza_count": 1, "neighbor_candidate_count": candidates,
        "supported_peer_count": len(rows), "rejected_candidate_count": rejected,
        "excluded_scope_count": excluded, "unsupported_relevant_count": unsupported,
    }


def _runtime_scope_authorized(command: str, body: str, platform: str) -> bool:
    low = (body or "").casefold()
    scoped = command in ("show bgp ipv4 unicast summary", "show bgp ip unicast summary")
    if scoped:
        return not re.search(r"vrf\s+(?!default\b)\S+", low)
    if command == "show ip bgp summary" and not _is_nxos(platform):
        return not re.search(r"vrf\s+(?!default\b)\S+", low)
    return bool(re.search(
        r"bgp\s+summary\s+information\s+for\s+vrf\s+default\s*,\s*"
        r"address\s+family\s+ipv4\s+unicast", low))


def _parse_runtime(body: str, command: str, platform: str) -> dict:
    lines = (body or "").splitlines()
    findings: List[dict] = []
    if len(lines) > _MAX_LINES:
        return {"status": "rejected", "rows": [], "findings": [
            _finding("review", "resource_limit", "Runtime summary exceeded the bounded parser line limit.")],
            "candidate_count": 0, "parsed_count": 0, "rejected_count": 1,
            "local_as": "", "scope_authorized": False}
    local_as = ""
    for line in lines:
        match = re.search(r"local\s+AS\s+(?:number\s+)?(\S+)", line, re.IGNORECASE)
        if match:
            local_as = _asn(match.group(1))
            break
    header = any("neighbor" in line.casefold() and "state/pfxrcd" in line.casefold()
                 for line in lines)
    authorized = _runtime_scope_authorized(command, body, platform)
    rows: List[dict] = []
    candidates = 0
    rejected = 0
    seen = set()
    for raw in lines:
        stripped = raw.strip()
        first = stripped.split(None, 1)[0] if stripped else ""
        peer = _ipv4(first)
        if not peer:
            continue
        candidates += 1
        parts = stripped.split()
        if len(parts) < 10 or not re.fullmatch(r"\d+", parts[1] or ""):
            rejected += 1
            continue
        remote_as = _asn(parts[2])
        if not remote_as or peer in seen:
            rejected += 1
            continue
        seen.add(peer)
        state_raw = " ".join(parts[9:])[:96]
        if re.fullmatch(r"\d+", state_raw):
            state = "ESTABLISHED"
            status = "assessed"
        else:
            compact = " ".join(state_raw.upper().replace("_", "-").split())
            if compact in _FSM_STATES:
                state = compact
                status = "degraded"
            else:
                state = "UNCLASSIFIED"
                status = "review"
        rows.append({
            "peer": peer, "peer_key": peer, "remote_as": remote_as,
            "state_raw": state_raw, "state": state, "status": status,
        })
    if not authorized:
        findings.append(_finding("review", "runtime_scope_unproven",
                                 "The selected summary did not prove default/global IPv4-unicast context."))
    if not header:
        findings.append(_finding("review", "runtime_header_missing",
                                 "The BGP summary peer-table header was not recognized."))
    if rejected:
        findings.append(_finding("review", "runtime_candidate_rejected",
                                 "One or more peer-like summary rows could not be parsed completely."))
    status = "complete" if authorized and header and not rejected else "review"
    return {
        "status": status, "rows": rows, "findings": findings,
        "candidate_count": candidates, "parsed_count": len(rows),
        "rejected_count": rejected, "local_as": local_as,
        "scope_authorized": authorized,
    }


def _acceptance(row: dict) -> str:
    peer = row["peer"]
    if row["status"] == "degraded":
        if row["runtime_observed"]:
            return ("PRE-CUTOVER DEGRADED — BLOCKER: configured-active BGP peer "
                    f"{peer} in default/global IPv4 unicast was observed in "
                    f"{row['runtime_state_raw'] or 'a non-Established state'}. Restore it to "
                    "Established or explicitly disposition the baseline before the window; matching "
                    "this degraded state is NOT ACCEPTANCE.")
        return ("PRE-CUTOVER DEGRADED — BLOCKER: configured-active BGP peer "
                f"{peer} in default/global IPv4 unicast was not observed in the usable summary. "
                "Restore it to Established or explicitly disposition removal before the window.")
    if row["status"] == "review":
        return ("PRE-CUTOVER REVIEW — BLOCKER: configured BGP peer "
                f"{peer} could not be reconciled inside the bounded default/global IPv4-unicast "
                "literal-peer contract. Review configuration and runtime identity before acceptance.")
    if row["status"] == "not_verified":
        return ("BGP CONFIGURED PEER NOT VERIFIED — BLOCKER: configuration intent and operational "
                "summary could not be source-reconciled. Re-collect show running-config and the "
                "default/global IPv4-unicast BGP summary before acceptance.")
    if row["status"] == "administratively_disabled":
        return (f"Peer {peer} is explicitly disabled in the bounded configured denominator; no "
                "Established claim is made and post-change activation requires explicit intent.")
    return (f"Require configured-active peer {peer} to remain Established with the configured remote "
            "AS. Prefix count is not pinned. This proves only direct static default/global IPv4-unicast "
            "peer state, not policy, route propagation, convergence, or freshness.")


def _coverage_status(config_status: str, runtime_status: str, config: dict, runtime: dict) -> str:
    if config_status != "ok" or runtime_status != "ok":
        return "not_verified"
    if config.get("status") != "complete" or runtime.get("status") != "complete":
        return "review"
    return "assessed"


def _baseline_digest_payload(result: dict) -> dict:
    payload = copy.deepcopy(result)
    summary = payload.get("summary")
    if isinstance(summary, dict):
        summary.pop("baseline_sha256", None)
    return payload


def compute_bgp_configured_peer_baseline(all_cmd_to_files: Any, capture_integrity: Any,
                                         devices: Any = None) -> dict:
    """Build the current-run configured-peer denominator from exact capture paths."""
    mappings = all_cmd_to_files if isinstance(all_cmd_to_files, dict) else {}
    platforms = _platforms(devices)
    inspections, duplicates = _inspection_index(capture_integrity)
    host_names = sorted(
        {host for host in mappings if isinstance(host, str) and _text(host, 128)} |
        set(platforms), key=lambda value: (value.casefold(), value))
    if len(host_names) > _MAX_HOSTS:
        host_names = host_names[:_MAX_HOSTS]

    rows: List[dict] = []
    coverage: List[dict] = []
    global_findings: List[dict] = []
    for host in host_names:
        mapping = mappings.get(host)
        mapping = mapping if isinstance(mapping, dict) else {}
        platform = platforms.get(host, "")
        config_command = "show running-config"
        runtime_command = _selected_runtime_command(
            mapping, platform, inspections, duplicates, host)
        config_capture = _capture_status(inspections, duplicates, host, config_command)
        runtime_capture = (_capture_status(inspections, duplicates, host, runtime_command)
                           if runtime_command else "not_observed")
        config_body, config_read = _read_capture(mapping, config_command)
        runtime_body, runtime_read = (_read_capture(mapping, runtime_command)
                                      if runtime_command else ("", "not_observed"))
        if config_read != "ok" and config_capture == "ok":
            config_capture = config_read
        if runtime_read != "ok" and runtime_capture == "ok":
            runtime_capture = runtime_read

        config = (_parse_config(config_body, platform) if config_capture == "ok" else {
            "status": "not_verified", "rows": [], "findings": [],
            "bgp_stanza_count": 0, "neighbor_candidate_count": 0,
            "supported_peer_count": 0, "rejected_candidate_count": 0,
            "excluded_scope_count": 0, "unsupported_relevant_count": 0,
        })
        runtime = (_parse_runtime(runtime_body, runtime_command, platform)
                   if runtime_capture == "ok" else {
                       "status": "not_verified", "rows": [], "findings": [],
                       "candidate_count": 0, "parsed_count": 0, "rejected_count": 0,
                       "local_as": "", "scope_authorized": False,
                   })
        runtime_by_peer = {row["peer_key"]: row for row in runtime["rows"]}
        configured = {row["peer_key"]: row for row in config["rows"]}
        host_rows: List[dict] = []
        trustworthy = config_capture == runtime_capture == "ok"
        parsers_complete = config["status"] == runtime["status"] == "complete"
        for peer in sorted(set(configured) | set(runtime_by_peer), key=ipaddress.ip_address):
            cfg = configured.get(peer)
            run = runtime_by_peer.get(peer)
            findings: List[dict] = []
            activation = cfg["activation"] if cfg else "ambiguous"
            status = "review"
            if not trustworthy:
                status = "not_verified"
                findings.append(_finding("not_verified", "capture_not_verified",
                                         "Configuration and runtime captures were not both integrity-ok."))
            elif cfg is None:
                status = "review"
                findings.append(_finding("review", "runtime_peer_not_in_bounded_config",
                                         "Observed peer is not present in the bounded direct-static config set."))
            elif cfg.get("findings"):
                status = "review"
                findings.extend(cfg["findings"])
            elif activation == "disabled":
                status = "administratively_disabled"
                if run:
                    status = "review"
                    findings.append(_finding("review", "disabled_peer_observed",
                                             "An explicitly disabled peer was nevertheless observed at runtime."))
            elif activation == "ambiguous" and not run:
                status = "review"
                findings.append(_finding("review", "activation_ambiguous",
                                         "Activation in default IPv4 unicast was not proven."))
            elif run is not None and run["remote_as"] != cfg["configured_remote_as"]:
                status = "review"
                findings.append(_finding("review", "remote_as_mismatch",
                                         "Configured and runtime remote AS values differ."))
            elif run is not None and run["status"] == "degraded":
                # A directly configured peer that is positively observed in a bounded BGP FSM
                # failure state is a real blocker even if some unrelated peer/template construct
                # elsewhere in the same capture still requires review.
                status = "degraded"
                findings.append(_finding("degraded", "peer_not_established",
                                         "Configured-active peer was observed outside Established state."))
            elif not parsers_complete:
                status = "review"
                findings.append(_finding("review", "parser_scope_incomplete",
                                         "Configuration or runtime candidate denominator was incomplete."))
            elif run is None:
                status = "degraded"
                findings.append(_finding("degraded", "configured_peer_not_observed",
                                         "Configured-active peer was not observed in the complete summary."))
            elif run["status"] == "review":
                status = "review"
                findings.append(_finding("review", "runtime_state_unclassified",
                                         "Runtime peer state was not in the bounded BGP state vocabulary."))
            else:
                status = "assessed"

            row = {
                "switch": host, "peer": peer, "peer_key": peer,
                "scope": "default/ipv4-unicast",
                "local_as": (cfg or {}).get("local_as") or runtime.get("local_as") or "",
                "configured_remote_as": (cfg or {}).get("configured_remote_as") or "",
                "activation": activation, "runtime_observed": run is not None,
                "runtime_remote_as": (run or {}).get("remote_as") or "",
                "runtime_state_raw": (run or {}).get("state_raw") or "",
                "runtime_state": (run or {}).get("state") or "NOT_OBSERVED",
                "status": status, "command": runtime_command or "show ip bgp summary",
                "acceptance": "", "source_key": (
                    f"show running-config#line:{(cfg or {}).get('source_line', 0)} + "
                    f"{runtime_command or 'default/global IPv4-unicast summary'}"),
                "projection_custody": "current_run_source_bound", "findings": findings,
            }
            row["acceptance"] = _acceptance(row)
            host_rows.append(row)

        # A valid but unsupported relevant BGP subject needs a host-level review even when no literal
        # peer identity can safely be emitted. Coverage carries that subject for validation consumers.
        # A BGP process with no direct literal peer is not, by itself, a configured-peer
        # subject (it may exist only for redistribution/origination).  Scope the gate only
        # when a peer candidate or operational peer actually exists; this preserves the
        # no-cry-wolf boundary for a peerless process while still publishing its coverage.
        subject = bool(
            config["neighbor_candidate_count"]
            or config["unsupported_relevant_count"]
            or runtime["candidate_count"]
            or host_rows
            # A recognized runtime BGP process plus an unverified config capture cannot prove
            # that the configured-peer denominator is empty.  Keep that scoped uncertainty
            # INDETERMINATE; a complete peerless config remains neutral below.
            or (config_capture != "ok" and runtime.get("local_as"))
        )
        cov_status = _coverage_status(config_capture, runtime_capture, config, runtime)
        if not subject and config_capture == "ok" and config["status"] == "complete":
            cov_status = "not_applicable"
        elif any(row["status"] == "degraded" for row in host_rows):
            cov_status = "degraded"
        elif any(row["status"] == "review" for row in host_rows) or config["unsupported_relevant_count"]:
            cov_status = "review"
        elif any(row["status"] == "not_verified" for row in host_rows):
            cov_status = "not_verified"

        config_hash = hashlib.sha256(config_body.encode("utf-8", errors="surrogatepass")).hexdigest() if config_body else ""
        runtime_hash = hashlib.sha256(runtime_body.encode("utf-8", errors="surrogatepass")).hexdigest() if runtime_body else ""
        projection_hash = _sha({"config": config["rows"], "runtime": runtime["rows"]})
        coverage.append({
            "switch": host, "platform": platform, "subject": subject, "status": cov_status,
            "config_command": config_command, "config_capture_status": config_capture,
            "config_parser_status": config["status"], "runtime_command": runtime_command,
            "runtime_capture_status": runtime_capture, "runtime_parser_status": runtime["status"],
            "bgp_stanza_count": int(config["bgp_stanza_count"]),
            "neighbor_candidate_count": int(config["neighbor_candidate_count"]),
            "supported_peer_count": int(config["supported_peer_count"]),
            "rejected_candidate_count": int(config["rejected_candidate_count"]),
            "excluded_scope_count": int(config["excluded_scope_count"]),
            "unsupported_relevant_count": int(config["unsupported_relevant_count"]),
            "runtime_candidate_count": int(runtime["candidate_count"]),
            "runtime_parsed_count": int(runtime["parsed_count"]),
            "runtime_rejected_count": int(runtime["rejected_count"]),
            "runtime_local_as": runtime.get("local_as") or "",
            "config_sha256": config_hash, "runtime_sha256": runtime_hash,
            "projection_sha256": projection_hash,
            "finding_codes": sorted({f["code"] for f in config["findings"] + runtime["findings"]}),
        })
        global_findings.extend(
            dict(finding, switch=host) for finding in config["findings"] + runtime["findings"])
        rows.extend(host_rows)

    rows.sort(key=lambda row: (row["switch"].casefold(), row["switch"],
                               ipaddress.ip_address(row["peer"])))
    coverage.sort(key=lambda row: (row["switch"].casefold(), row["switch"]))
    global_findings.sort(key=lambda row: (row.get("switch", "").casefold(), row["code"]))
    counts = Counter(row["status"] for row in rows)
    coverage_counts = Counter(row["status"] for row in coverage)
    subject_cov = [row for row in coverage if row["subject"]]
    if counts["degraded"]:
        verdict = "BLOCKED"
    elif counts["review"] or counts["not_verified"] or any(
            row["status"] in ("review", "not_verified") for row in subject_cov):
        verdict = "INDETERMINATE"
    elif counts["assessed"]:
        verdict = "CLEAR"
    else:
        verdict = "NOT_APPLICABLE"
    assessed = verdict in ("CLEAR", "BLOCKED") and not (
        counts["review"] or counts["not_verified"])
    result = {
        "schema": BGP_CONFIGURED_PEER_SCHEMA, "scope": dict(_SCOPE),
        "verdict": verdict, "assessed": bool(assessed),
        "projection_custody": "current_run_source_bound",
        "rows": rows, "coverage": coverage, "findings": global_findings,
        "summary": {
            "n_hosts": len(coverage), "n_subject_hosts": len(subject_cov),
            "n_configured_peers": sum(1 for row in rows if row["configured_remote_as"]),
            "n_active_peers": sum(1 for row in rows if row["activation"] == "active"),
            "n_established": counts["assessed"], "n_degraded": counts["degraded"],
            "n_review": counts["review"], "n_not_verified": counts["not_verified"],
            "n_disabled": counts["administratively_disabled"],
            "by_status": {status: int(counts[status]) for status in _STATUS_ORDER},
            "by_coverage_status": {
                status: int(coverage_counts[status]) for status in _COVERAGE_STATUS_ORDER
            },
            "baseline_sha256": "",
        },
        "limitations": [
            "Scope is default/global IPv4 unicast and direct static literal IPv4 peers only.",
            "VRFs, IPv6, VPNv4/VPNv6, EVPN, multicast, flowspec, templates, peer-groups, dynamic/listen peers, and interface peers are not validated.",
            "Established peer state does not prove policy, route propagation, best path, RPKI, convergence, simultaneous sampling, or freshness.",
            "A configured peer missing from a complete usable summary is reported as not observed; it is not asserted administratively or physically down.",
        ],
    }
    result["summary"]["baseline_sha256"] = _sha(_baseline_digest_payload(result))
    return _CurrentRunBgpConfiguredPeerBaseline(result)


def _structural_validation(value: Any) -> Tuple[bool, str]:
    if not isinstance(value, dict):
        return False, "baseline_not_object"
    required = {"schema", "scope", "verdict", "assessed", "projection_custody", "rows",
                "coverage", "findings", "summary", "limitations"}
    if set(value) != required or value.get("schema") != BGP_CONFIGURED_PEER_SCHEMA:
        return False, "baseline_schema_or_keys_invalid"
    if value.get("scope") != _SCOPE or value.get("verdict") not in {
            "CLEAR", "BLOCKED", "INDETERMINATE", "NOT_APPLICABLE"}:
        return False, "baseline_scope_or_verdict_invalid"
    if type(value.get("assessed")) is not bool:
        return False, "baseline_assessed_invalid"
    custody = value.get("projection_custody")
    if custody not in {"current_run_source_bound", "embedded_unverified"}:
        return False, "baseline_custody_invalid"
    rows = value.get("rows")
    coverage = value.get("coverage")
    summary = value.get("summary")
    if not isinstance(rows, list) or len(rows) > _MAX_PEERS or not isinstance(coverage, list) or \
            len(coverage) > _MAX_HOSTS or not isinstance(summary, dict) or set(summary) != _SUMMARY_KEYS:
        return False, "baseline_denominator_invalid"
    digest = summary.get("baseline_sha256")
    if not isinstance(digest, str) or digest != _sha(_baseline_digest_payload(value)):
        return False, "baseline_digest_mismatch"

    def safe_string(item: Any, limit: int) -> bool:
        return isinstance(item, str) and len(item) <= limit and _text(item, limit) == item.strip()

    def sha_token(item: Any, *, empty_ok: bool = True) -> bool:
        return bool(
            isinstance(item, str)
            and ((empty_ok and item == "") or re.fullmatch(r"[0-9a-f]{64}", item))
        )

    def valid_finding(item: Any, *, global_row: bool = False) -> bool:
        keys = {"kind", "code", "issue"} | ({"switch"} if global_row else set())
        return bool(
            isinstance(item, dict) and set(item) == keys
            and item.get("kind") in {"degraded", "review", "not_verified"}
            and safe_string(item.get("code"), 96)
            and safe_string(item.get("issue"), 500)
            and (not global_row or safe_string(item.get("switch"), 128))
        )

    identities = set()
    rows_by_host: Dict[str, List[dict]] = {}
    for row in rows:
        if not isinstance(row, dict) or set(row) != _ROW_KEYS:
            return False, "baseline_row_invalid"
        host = _text(row.get("switch"), 128)
        peer = _ipv4(row.get("peer"))
        if not host or not peer or row.get("peer_key") != peer or row.get("status") not in _STATUS_ORDER:
            return False, "baseline_row_identity_or_status_invalid"
        identity = (host, peer)
        if identity in identities:
            return False, "baseline_duplicate_peer"
        identities.add(identity)
        if row.get("activation") not in {"active", "disabled", "ambiguous"} or \
                type(row.get("runtime_observed")) is not bool or not isinstance(row.get("findings"), list):
            return False, "baseline_row_semantics_invalid"
        if row.get("scope") != "default/ipv4-unicast" or row.get("projection_custody") != custody:
            return False, "baseline_row_scope_or_custody_invalid"
        if not all(safe_string(row.get(field), limit) for field, limit in (
                ("switch", 128), ("peer", 64), ("peer_key", 64), ("scope", 64),
                ("local_as", 32), ("configured_remote_as", 32), ("runtime_remote_as", 32),
                ("runtime_state_raw", 96), ("runtime_state", 96), ("command", 128),
                ("acceptance", 1400), ("source_key", 400), ("projection_custody", 40))):
            return False, "baseline_row_text_invalid"
        if row["local_as"] and not _asn(row["local_as"]):
            return False, "baseline_row_local_as_invalid"
        if row["configured_remote_as"] and not _asn(row["configured_remote_as"]):
            return False, "baseline_row_configured_as_invalid"
        if row["runtime_remote_as"] and not _asn(row["runtime_remote_as"]):
            return False, "baseline_row_runtime_as_invalid"
        if len(row["findings"]) > 64 or not all(valid_finding(item) for item in row["findings"]):
            return False, "baseline_row_findings_invalid"
        status = row["status"]
        if status == "assessed" and not (
                row["activation"] == "active" and row["runtime_observed"] is True
                and row["runtime_state"] == "ESTABLISHED"
                and row["configured_remote_as"]
                and row["configured_remote_as"] == row["runtime_remote_as"]):
            return False, "baseline_assessed_row_contradiction"
        if status == "administratively_disabled" and row["activation"] != "disabled":
            return False, "baseline_disabled_row_contradiction"
        if status == "degraded" and row["activation"] != "active":
            return False, "baseline_degraded_row_contradiction"
        rows_by_host.setdefault(host, []).append(row)

    coverage_hosts = set()
    coverage_by_host: Dict[str, dict] = {}
    for cell in coverage:
        if not isinstance(cell, dict) or set(cell) != _COVERAGE_KEYS:
            return False, "baseline_coverage_invalid"
        host = _text(cell.get("switch"), 128)
        if not host or host in coverage_hosts:
            return False, "baseline_coverage_host_invalid"
        coverage_hosts.add(host)
        coverage_by_host[host] = cell
        if type(cell.get("subject")) is not bool or cell.get("status") not in _COVERAGE_STATUSES:
            return False, "baseline_coverage_status_invalid"
        if cell["subject"] is True and cell["status"] == "not_applicable":
            return False, "baseline_coverage_subject_status_invalid"
        if cell.get("config_command") != "show running-config" or \
                cell.get("runtime_command") not in {"", *_RUNTIME_VARIANTS}:
            return False, "baseline_coverage_command_invalid"
        if cell.get("config_capture_status") not in _SAFE_CAPTURE_STATUSES or \
                cell.get("runtime_capture_status") not in _SAFE_CAPTURE_STATUSES or \
                cell.get("config_parser_status") not in _PARSER_STATUSES or \
                cell.get("runtime_parser_status") not in _PARSER_STATUSES:
            return False, "baseline_coverage_receipt_invalid"
        if not all(safe_string(cell.get(field), limit) for field, limit in (
                ("switch", 128), ("platform", 80), ("config_command", 128),
                ("config_capture_status", 32), ("config_parser_status", 32),
                ("runtime_command", 128), ("runtime_capture_status", 32),
                ("runtime_parser_status", 32), ("runtime_local_as", 32))):
            return False, "baseline_coverage_text_invalid"
        if cell["runtime_local_as"] and not _asn(cell["runtime_local_as"]):
            return False, "baseline_coverage_local_as_invalid"
        count_fields = (
            "bgp_stanza_count", "neighbor_candidate_count", "supported_peer_count",
            "rejected_candidate_count", "excluded_scope_count", "unsupported_relevant_count",
            "runtime_candidate_count", "runtime_parsed_count", "runtime_rejected_count",
        )
        if any(type(cell.get(field)) is not int or not 0 <= cell[field] <= _MAX_LINES
               for field in count_fields):
            return False, "baseline_coverage_count_invalid"
        host_rows = rows_by_host.get(host, [])
        configured_count = sum(bool(row["configured_remote_as"]) for row in host_rows)
        runtime_count = sum(row["runtime_observed"] is True for row in host_rows)
        if cell["supported_peer_count"] != configured_count or \
                cell["runtime_parsed_count"] != runtime_count or \
                cell["runtime_candidate_count"] != (
                    cell["runtime_parsed_count"] + cell["runtime_rejected_count"]):
            return False, "baseline_coverage_count_mismatch"
        if cell["supported_peer_count"] > cell["neighbor_candidate_count"]:
            return False, "baseline_config_candidate_mismatch"
        if not sha_token(cell.get("config_sha256")) or not sha_token(cell.get("runtime_sha256")) or \
                not sha_token(cell.get("projection_sha256"), empty_ok=False):
            return False, "baseline_coverage_hash_invalid"
        codes = cell.get("finding_codes")
        if not isinstance(codes, list) or len(codes) > 128 or codes != sorted(set(codes)) or \
                not all(safe_string(code, 96) for code in codes):
            return False, "baseline_coverage_findings_invalid"
        expected_subject = bool(
            cell["neighbor_candidate_count"] or cell["unsupported_relevant_count"]
            or cell["runtime_candidate_count"] or host_rows
            or (cell["config_capture_status"] != "ok" and cell["runtime_local_as"])
        )
        if cell["subject"] is not expected_subject:
            return False, "baseline_coverage_subject_mismatch"
        host_statuses = Counter(row["status"] for row in host_rows)
        if not expected_subject:
            if cell["config_capture_status"] != "ok" or cell["runtime_capture_status"] not in {
                    "ok", "not_observed"}:
                expected_status = "not_verified"
            elif cell["config_parser_status"] not in {"complete"} or cell["runtime_parser_status"] not in {
                    "complete", "not_verified"}:
                expected_status = "review"
            else:
                expected_status = "not_applicable"
        elif host_statuses["degraded"]:
            expected_status = "degraded"
        elif host_statuses["review"] or cell["unsupported_relevant_count"]:
            expected_status = "review"
        elif host_statuses["not_verified"] or cell["config_capture_status"] != "ok" or \
                cell["runtime_capture_status"] != "ok":
            expected_status = "not_verified"
        elif cell["config_parser_status"] != "complete" or cell["runtime_parser_status"] != "complete":
            expected_status = "review"
        else:
            expected_status = "assessed"
        if cell["status"] != expected_status:
            return False, "baseline_coverage_status_mismatch"

    if set(rows_by_host) - coverage_hosts:
        return False, "baseline_row_without_coverage"
    findings = value.get("findings")
    limitations = value.get("limitations")
    if not isinstance(findings, list) or len(findings) > 4096 or \
            not all(valid_finding(item, global_row=True) for item in findings):
        return False, "baseline_findings_invalid"
    if not isinstance(limitations, list) or not 1 <= len(limitations) <= 32 or \
            not all(safe_string(item, 800) for item in limitations):
        return False, "baseline_limitations_invalid"
    finding_codes_by_host: Dict[str, set] = {}
    for finding in findings:
        finding_codes_by_host.setdefault(finding["switch"], set()).add(finding["code"])
    for host, cell in coverage_by_host.items():
        if cell["finding_codes"] != sorted(finding_codes_by_host.get(host, set())):
            return False, "baseline_finding_code_mismatch"

    coverage_census = summary.get("by_coverage_status")
    if not isinstance(coverage_census, dict) or set(coverage_census) != set(
            _COVERAGE_STATUS_ORDER) or any(
                type(coverage_census.get(status)) is not int
                or not 0 <= coverage_census[status] <= _MAX_HOSTS
                for status in _COVERAGE_STATUS_ORDER
            ) or sum(coverage_census.values()) != len(coverage):
        return False, "baseline_coverage_census_invalid"

    counts = Counter(row["status"] for row in rows)
    coverage_counts = Counter(cell["status"] for cell in coverage)
    expected = {
        "n_hosts": len(coverage),
        "n_subject_hosts": sum(1 for row in coverage if isinstance(row, dict) and row.get("subject") is True),
        "n_configured_peers": sum(1 for row in rows if row.get("configured_remote_as")),
        "n_active_peers": sum(1 for row in rows if row.get("activation") == "active"),
        "n_established": counts["assessed"], "n_degraded": counts["degraded"],
        "n_review": counts["review"], "n_not_verified": counts["not_verified"],
        "n_disabled": counts["administratively_disabled"],
        "by_status": {status: int(counts[status]) for status in _STATUS_ORDER},
        "by_coverage_status": {
            status: int(coverage_counts[status]) for status in _COVERAGE_STATUS_ORDER
        },
    }
    if any(summary.get(key) != expected_value for key, expected_value in expected.items()):
        return False, "baseline_summary_mismatch"
    subject_cells = [cell for cell in coverage if cell["subject"]]
    if counts["degraded"]:
        expected_verdict = "BLOCKED"
    elif counts["review"] or counts["not_verified"] or any(
            cell["status"] in {"review", "not_verified"} for cell in subject_cells):
        expected_verdict = "INDETERMINATE"
    elif counts["assessed"]:
        expected_verdict = "CLEAR"
    else:
        expected_verdict = "NOT_APPLICABLE"
    expected_assessed = expected_verdict in {"CLEAR", "BLOCKED"} and not (
        counts["review"] or counts["not_verified"])
    if value.get("verdict") != expected_verdict or value.get("assessed") is not expected_assessed:
        return False, "baseline_verdict_mismatch"
    return True, "ok"


def validate_bgp_configured_peer_baseline(value: Any, *, require_current_run: bool = False) -> dict:
    """Validate the closed snapshot shape and, optionally, its process-local source marker."""
    present = value is not None
    valid, reason = _structural_validation(value)
    source_bound = valid and isinstance(value, _CurrentRunBgpConfiguredPeerBaseline)
    if require_current_run and not source_bound:
        valid = False
        reason = "baseline_not_current_run_source_bound"
    if not valid:
        return {"present": present, "valid": False, "reason": reason,
                "source_bound": False, "rows": [], "index": {}, "baseline": {}}
    baseline = copy.deepcopy(dict(value))
    rows = baseline["rows"]
    return {
        "present": True, "valid": True, "reason": "ok", "source_bound": source_bound,
        "rows": rows, "index": {(row["switch"], row["peer_key"]): row for row in rows},
        "baseline": baseline,
    }


def embedded_bgp_configured_peer_baseline(value: Any) -> dict:
    """Return a JSON-safe audit projection that cannot self-certify current-run custody."""
    view = validate_bgp_configured_peer_baseline(value)
    if not view["valid"]:
        return {
            "schema": BGP_CONFIGURED_PEER_SCHEMA, "scope": dict(_SCOPE),
            "verdict": "INDETERMINATE", "assessed": False,
            "projection_custody": "embedded_unverified", "rows": [], "coverage": [],
            "findings": [], "summary": {
                "n_hosts": 0, "n_subject_hosts": 0, "n_configured_peers": 0,
                "n_active_peers": 0, "n_established": 0, "n_degraded": 0,
                "n_review": 0, "n_not_verified": 0, "n_disabled": 0,
                "by_status": {status: 0 for status in _STATUS_ORDER},
                "by_coverage_status": {
                    status: 0 for status in _COVERAGE_STATUS_ORDER
                },
                "baseline_sha256": "",
            },
            "limitations": ["The current-run BGP configured-peer baseline was unavailable."],
        }
    result = view["baseline"]
    result["projection_custody"] = "embedded_unverified"
    for row in result["rows"]:
        row["projection_custody"] = "embedded_unverified"
    result["summary"]["baseline_sha256"] = ""
    result["summary"]["baseline_sha256"] = _sha(_baseline_digest_payload(result))
    return result


__all__ = [
    "BGP_CONFIGURED_PEER_SCHEMA", "compute_bgp_configured_peer_baseline",
    "validate_bgp_configured_peer_baseline", "embedded_bgp_configured_peer_baseline",
]
