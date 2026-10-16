"""Canonical, offline traffic-assurance composition over the existing evidence engines.

This module does not create a second forwarding, ACL, ECMP, MTU, or failure model.  It composes the live
owners in :mod:`cisco_toolkit.fib`, :mod:`cisco_toolkit.aclcheck`, and
:mod:`cisco_toolkit.cutover_sim` into one serializable result that every delivery surface can reuse.

The result is deliberately bounded.  Version 1 assesses an explicitly declared IPv4 TCP/UDP flow over the
collected, scoped RIB; stateless interface ACLs; observed per-hop MTU; ECMP leg consistency; and optionally one
synthetic node/site/link cutover step.  It is not a packet capture, session-table query, NAT/firewall model,
VRF-aware FIB, application-identity engine, or field validation.  Unsupported dimensions remain explicit and do
not silently become a pass.
"""
from __future__ import annotations

import ipaddress
import json
import math
from collections import Counter
from dataclasses import asdict, is_dataclass
from hashlib import sha256
from typing import Any, Dict, Iterable, List, Optional, Tuple

from . import aclcheck, cutover_sim, fib
from .build import ScopedRouteProjection
from .model import Verdict
from .parse import forwarding_gate_candidate_projection_incomplete
from .textutils import normalize_ifname, safe_fs_name


TRAFFIC_ASSURANCE_SCHEMA = "traffic_assurance/1"
TRAFFIC_ASSURANCE_SET_SCHEMA = "traffic_assurance_set/1"
TRAFFIC_EVIDENCE_CUSTODY_SCHEMA = "traffic_evidence_custody/1"
TRAFFIC_ASSURANCE_OWNER = "cisco_toolkit.traffic_assurance.assess_flow"

_SUPPORTED_PROTOCOLS = frozenset({"tcp", "udp"})
_SUPPORTED_EXPECTATIONS = frozenset({"permit", "deny"})
_SUPPORTED_FAILURE_ACTIONS = frozenset({"fail_node", "fail_site", "shut_link"})
_BASE_LIMITATIONS = (
    "synthetic control-plane analysis over the collected snapshot; not observed packets or application success",
    "routing evidence is a scoped RIB projection and is not VRF-aware",
    "path results stop at collected L3-owner boundaries; endpoint attachment, ARP/ND, access VLAN and L2 delivery are not assessed",
    "tunnel interfaces prove only the selected overlay RIB projection; tunnel state, encapsulation and recursive underlay delivery are not assessed",
    "route and ACL completeness require affirmative per-command custody; missing or non-ok capture custody abstains",
    "policy-based routing and configured unicast RPF are detected but not modeled; an affected ingress abstains",
    "stateful firewall sessions, NAT/PAT translation, zones, IPsec/crypto attachments, identity policy, load balancers and service chains are not modeled",
    "policy proof covers only ACL attachments whose ingress/egress interface can be resolved from collected routes",
)

_CUSTODY_COMMAND_VARIANTS = {
    "acl_definitions": ("show running-config",),
    "global_forwarding_config": ("show running-config",),
    "interface_attachments": ("show running-config interface", "show running-config | section ^interface"),
    "routing_table": ("show ip route", "show ip route vrf all"),
}
_CUSTODY_SKIPPABLE_STATUSES = frozenset({"empty", "error", "unreadable"})
_CUSTODY_PARSERS = {
    "acl_definitions": ("parse_acls", "parse_object_groups"),
    "global_forwarding_config": (
        "parse_run_config_interfaces", "parse_acls", "parse_object_groups", "parse_nat",
    ),
    "interface_attachments": ("parse_run_config_interfaces",),
    "routing_table": ("parse_ip_routes",),
}
_ZERO_YIELD_IS_GAP = frozenset({"parse_run_config_interfaces", "parse_ip_routes"})


class _CurrentRunTrafficCustody(dict):
    """In-memory proof that custody was derived from live current-run inputs, not loaded JSON.

    The marker is intentionally not serialized. A JSON round-trip produces an ordinary ``dict`` and therefore
    cannot self-certify its embedded ``complete: true`` fields at an API/reassessment boundary.
    """


def _as_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _nonnegative_count(value: Any) -> Optional[int]:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return ""
    return value.strip()


def _json_safe_value(value: Any, *, _depth: int = 0, _budget: Optional[List[int]] = None,
                     _active: Optional[set[int]] = None) -> Tuple[Any, int]:
    """Return a bounded deterministic UTF-8/JSON-safe copy and the rejected scalar count."""
    budget = _budget if _budget is not None else [0]
    active = _active if _active is not None else set()
    budget[0] += 1
    if _depth > 128 or budget[0] > 50_000:
        return "[EVIDENCE STRUCTURE LIMIT]", 1
    if isinstance(value, str):
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            return "[INVALID UNICODE TEXT]", 1
        return value, 0
    if value is None or isinstance(value, (bool, int)):
        return value, 0
    if isinstance(value, float):
        return (value, 0) if math.isfinite(value) else (None, 1)
    if isinstance(value, (list, tuple)):
        identity = id(value)
        if identity in active:
            return "[CYCLIC EVIDENCE]", 1
        active.add(identity)
        rows, changes = [], 0
        try:
            for item in value:
                safe, count = _json_safe_value(
                    item, _depth=_depth + 1, _budget=budget, _active=active)
                rows.append(safe)
                changes += count
        finally:
            active.remove(identity)
        return rows, changes
    if isinstance(value, dict):
        identity = id(value)
        if identity in active:
            return "[CYCLIC EVIDENCE]", 1
        active.add(identity)
        safe_dict, changes = {}, 0
        try:
            for index, (key, item) in enumerate(value.items()):
                if isinstance(key, str):
                    try:
                        key.encode("utf-8")
                        safe_key = key
                    except UnicodeEncodeError:
                        safe_key = "invalid_unicode_key_" + sha256(
                            key.encode("utf-8", errors="surrogatepass")
                        ).hexdigest()[:12]
                        changes += 1
                else:
                    # JSON object member names are strings. Never stringify an arbitrary key or retain a mixed
                    # key type that makes ``json.dumps(sort_keys=True)`` non-total.
                    safe_key = f"invalid_json_key_{index}"
                    changes += 1
                while safe_key in safe_dict:
                    safe_key = f"invalid_json_key_{index}_{changes}"
                    changes += 1
                safe_item, count = _json_safe_value(
                    item, _depth=_depth + 1, _budget=budget, _active=active)
                safe_dict[safe_key] = safe_item
                changes += count
        finally:
            active.remove(identity)
        return safe_dict, changes
    return "[NON-JSON VALUE]", 1


def _evidence_content_sha256(value: Any) -> str:
    """Digest a current-run evidence structure without retaining or stringifying rejected content."""
    try:
        def _dataclass_only(item: Any) -> dict:
            if is_dataclass(item) and not isinstance(item, type):
                return asdict(item)
            raise TypeError("unsupported evidence value")

        payload = json.dumps(
            value,
            default=_dataclass_only,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError):
        return ""
    return sha256(payload).hexdigest()


def _content_binding_payload(sections: Any, host: str, kind: str) -> Optional[Any]:
    """Select the exact current-run structures consumed by one custody cell."""
    source = _as_dict(sections)
    if kind == "interface_attachments":
        interfaces = source.get("interfaces")
        if (not isinstance(interfaces, dict) or host not in interfaces
                or not isinstance(interfaces.get(host), dict)):
            return None
        scoped_fields = (
            "svi_ip", "svi_ips", "acl_in", "acl_out", "acl_in_unmodeled", "acl_out_unmodeled",
            "run_config_observed", "mtu", "link_mtu", "ip_mtu", "mtu_semantics", "pbr_policy", "urpf_mode",
            "security_zone", "service_policy_in", "service_policy_out", "inspection_policy_in",
            "inspection_policy_out", "crypto_map", "tunnel_protection", "trustsec_sgacl",
            "wccp_redirection_in", "wccp_redirection_out", "tcp_intercept", "mpls_forwarding",
            "mpls_mtu", "flowspec_policy", "ips_policy_in", "ips_policy_out", "admission_policy",
            "forwarding_gate_candidates", "forwarding_gate_unmodeled",
        )
        return {
            interface: {field: _field(record, field) for field in scoped_fields}
            for interface, record in interfaces[host].items()
        }
    if kind == "acl_definitions":
        if any(not isinstance(source.get(section), dict)
               for section in ("acls", "object_groups", "nat")):
            return None
        if any(section not in source or host not in source[section]
               or not isinstance(source[section].get(host), dict)
               for section in ("acls", "object_groups", "nat")):
            return None
        return {
            "acls": source["acls"][host],
            "object_groups": source["object_groups"][host],
            "nat": source["nat"][host],
        }
    if kind == "global_forwarding_config":
        if any(not isinstance(source.get(section), dict)
               for section in ("interfaces", "acls", "object_groups", "nat")):
            return None
        if any(host not in source[section] or not isinstance(source[section].get(host), dict)
               for section in ("interfaces", "acls", "object_groups", "nat")):
            return None
        interfaces = source["interfaces"][host]
        global_fields = (
            "vacl_policy", "global_acl_in", "global_acl_out", "global_policy_gates",
            "trustsec_sgacl", "tcp_intercept", "flowspec_policy",
            "forwarding_gate_candidates", "forwarding_gate_unmodeled",
        )
        global_gates_by_interface = {
            interface: {
                field: _field(record, field)
                for field in global_fields
            }
            for interface, record in interfaces.items()
        }
        return {
            "global_gates_by_interface": global_gates_by_interface,
            "acls": source["acls"][host],
            "object_groups": source["object_groups"][host],
            "nat": source["nat"][host],
        }
    return None


def _finalize_result(result: dict) -> dict:
    """Seal the canonical boundary: unsafe native evidence can only produce an explicit abstention."""
    safe, changes = _json_safe_value(result)
    if not changes:
        return safe

    def _downgrade(value: Any) -> None:
        if isinstance(value, dict):
            if value.get("verdict") in (Verdict.PROVEN.value, Verdict.REFUTED.value):
                value["pre_serialization_safety_verdict"] = value["verdict"]
                value["verdict"] = Verdict.INDETERMINATE.value
            for child in value.values():
                _downgrade(child)
        elif isinstance(value, list):
            for child in value:
                _downgrade(child)

    _downgrade(safe)
    safe["verdict"] = Verdict.INDETERMINATE.value
    safe["verdict_reasons"] = [
        "relevant evidence contained a non-UTF-8 or non-JSON scalar and was rejected at the canonical boundary"
    ]
    safe["serialization_safety"] = {
        "verdict": Verdict.INDETERMINATE.value,
        "rejected_scalar_count": changes,
        "disclosure": "invalid scalar values were replaced with fixed non-sensitive markers",
    }
    limitations = safe.get("limitations") if isinstance(safe.get("limitations"), list) else []
    safe["limitations"] = limitations + [
        "a malformed evidence scalar forced canonical abstention; no raw rejected value was retained"
    ]
    return safe


def _route_projection_cell(value: Any) -> dict:
    """Verify the non-serializable projection receipt produced by ``build.scope_routes``."""
    if not isinstance(value, ScopedRouteProjection):
        return {"status": "projection_not_current_run_verified", "complete": False,
                "scope_networks": []}
    receipt = _as_dict(getattr(value, "projection_receipt", None))

    def _scope_networks(raw_scope: Any) -> Optional[List[str]]:
        if not isinstance(raw_scope, list) or len(raw_scope) > 4096:
            return None
        result = []
        for token in raw_scope:
            if not isinstance(token, str) or not token or len(token) > 64:
                return None
            try:
                token.encode("utf-8")
                network = ipaddress.ip_network(token, strict=False)
            except (UnicodeEncodeError, ValueError):
                return None
            canonical = str(network)
            if token != canonical:
                return None
            result.append(canonical)
        return result

    def _parse_receipt_summary(raw_receipt: Any) -> Tuple[Optional[dict], bool]:
        source = _as_dict(raw_receipt)
        count_fields = (
            "candidate_rows", "parsed_rows", "unparsed_candidate_rows",
            "malformed_candidate_rows", "unexplained_candidate_rows", "ios_candidate_rows",
            "ios_parsed_rows", "ios_unparsed_rows", "nxos_prefix_blocks",
            "nxos_expected_ubest_rows", "nxos_via_candidate_rows", "nxos_parsed_via_rows",
            "nxos_unparsed_via_rows", "nxos_denominator_mismatch_blocks",
            "nxos_malformed_prefix_blocks", "ios_malformed_subnet_headers",
            "route_prefix_count", "route_entry_count",
        )
        counts = {field: _nonnegative_count(source.get(field)) for field in count_fields}
        reasons = source.get("incomplete_reasons")
        digest_token = source.get("routes_sha256")
        structurally_valid = (
            source.get("schema") == "route_parse_receipt/1"
            and source.get("complete") in (True, False)
            and all(value is not None for value in counts.values())
            and isinstance(digest_token, str)
            and len(digest_token) == 64
            and all(ch in "0123456789abcdef" for ch in digest_token)
            and isinstance(reasons, list)
            and len(reasons) <= 16
            and all(isinstance(reason, str) and len(reason) <= 96 and reason.isascii()
                    for reason in reasons)
        )
        if not structurally_valid:
            return None, False
        clean = {field: int(value) for field, value in counts.items() if value is not None}
        equations_valid = (
            clean["candidate_rows"] == clean["parsed_rows"] + clean["unparsed_candidate_rows"]
            and clean["candidate_rows"]
            == clean["ios_candidate_rows"] + clean["nxos_via_candidate_rows"]
            and clean["parsed_rows"]
            == clean["ios_parsed_rows"] + clean["nxos_parsed_via_rows"]
            and clean["unparsed_candidate_rows"]
            == clean["ios_unparsed_rows"] + clean["nxos_unparsed_via_rows"]
            and clean["unparsed_candidate_rows"]
            == clean["malformed_candidate_rows"] + clean["unexplained_candidate_rows"]
        )
        expected_reasons = []
        if clean["unparsed_candidate_rows"]:
            expected_reasons.append("candidate_rows_unparsed")
        if clean["malformed_candidate_rows"]:
            expected_reasons.append("malformed_candidate_rows")
        if clean["unexplained_candidate_rows"]:
            expected_reasons.append("unexplained_candidate_rows")
        if clean["nxos_denominator_mismatch_blocks"]:
            expected_reasons.append("nxos_ubest_via_denominator_mismatch")
        if clean["nxos_malformed_prefix_blocks"]:
            expected_reasons.append("nxos_malformed_prefix_block")
        if clean["ios_malformed_subnet_headers"]:
            expected_reasons.append("ios_malformed_subnet_header")
        expected_complete = (
            equations_valid
            and clean["unparsed_candidate_rows"] == 0
            and clean["nxos_expected_ubest_rows"] == clean["nxos_via_candidate_rows"]
            and clean["nxos_via_candidate_rows"] == clean["nxos_parsed_via_rows"]
            and clean["nxos_denominator_mismatch_blocks"] == 0
            and clean["nxos_malformed_prefix_blocks"] == 0
            and clean["ios_malformed_subnet_headers"] == 0
        )
        if reasons != expected_reasons or source.get("complete") is not expected_complete:
            return None, False
        return {
            "schema": "route_parse_receipt/1",
            "complete": expected_complete,
            **clean,
            "routes_sha256": digest_token,
            "incomplete_reasons": expected_reasons,
        }, True

    try:
        digest = sha256(json.dumps(
            list(value), ensure_ascii=True, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")).hexdigest()
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError):
        digest = ""
    scope = _scope_networks(receipt.get("scope_networks"))
    source_prefix_count = _nonnegative_count(receipt.get("source_prefix_count"))
    source_entry_count = _nonnegative_count(receipt.get("source_entry_count"))
    scoped_row_count = _nonnegative_count(receipt.get("scoped_row_count"))
    projection_digest = receipt.get("scoped_rows_sha256")
    base_valid = (
        receipt.get("schema") == "scoped_route_projection/1"
        and receipt.get("algorithm") == "overlap_and_next_hop_closure_v1"
        and receipt.get("complete") is True
        and scope is not None
        and source_prefix_count is not None
        and source_entry_count is not None
        and scoped_row_count is not None
        and isinstance(projection_digest, str)
        and len(projection_digest) == 64
        and all(ch in "0123456789abcdef" for ch in projection_digest)
    )
    if not base_valid:
        return {"status": "invalid_projection_receipt", "complete": False,
                "scope_networks": []}
    assert scope is not None and scoped_row_count is not None
    assert source_prefix_count is not None and source_entry_count is not None
    if scoped_row_count != len(value) or not digest or projection_digest != digest:
        return {"status": "projection_receipt_mismatch", "complete": False,
                "scope_networks": scope, "source_prefix_count": source_prefix_count,
                "source_entry_count": source_entry_count, "scoped_row_count": scoped_row_count}

    raw_parse_receipt = receipt.get("source_parse_receipt")
    if raw_parse_receipt is None:
        return {"status": "route_parse_receipt_missing", "complete": False,
                "scope_networks": scope, "source_prefix_count": source_prefix_count,
                "source_entry_count": source_entry_count, "scoped_row_count": scoped_row_count}
    parse_summary, parse_valid = _parse_receipt_summary(raw_parse_receipt)
    if not parse_valid or parse_summary is None \
            or receipt.get("source_parse_receipt_verified") is not True:
        return {"status": "invalid_projection_receipt", "complete": False,
                "scope_networks": scope, "source_prefix_count": source_prefix_count,
                "source_entry_count": source_entry_count, "scoped_row_count": scoped_row_count}
    if parse_summary["route_prefix_count"] != source_prefix_count \
            or parse_summary["route_entry_count"] != source_entry_count:
        return {"status": "invalid_projection_receipt", "complete": False,
                "scope_networks": scope, "source_prefix_count": source_prefix_count,
                "source_entry_count": source_entry_count, "scoped_row_count": scoped_row_count}
    status = "ok" if parse_summary["complete"] else "route_parse_incomplete"
    return {
        "status": status,
        "complete": status == "ok",
        "scope_networks": scope,
        "source_prefix_count": source_prefix_count,
        "source_entry_count": source_entry_count,
        "scoped_row_count": scoped_row_count,
        "scoped_rows_sha256": projection_digest,
        "source_routes_sha256": parse_summary["routes_sha256"],
        "parse_receipt": parse_summary,
    }


def build_traffic_evidence_custody(command_inventory: Any, capture_integrity: Any,
                                   parse_yield: Any = None, route_projection: Any = None,
                                   evidence_sections: Any = None) -> dict:
    """Build the compact command-custody denominator consumed by traffic assurance.

    ``command_inventory`` is the pipeline's already-resolved ``{host: {command: path}}`` map. Paths and command
    bodies are deliberately discarded. ``capture_integrity`` lists only non-ok captures, so a present command
    absent from that finding set is the capture-level ``ok`` case. ``parse_yield`` then proves that the relevant
    parser denominator ran over that exact host+command representation without an error or suspicious zero-yield.
    ``route_projection`` is the current-run ``{host: ScopedRouteProjection}`` mapping produced from each full
    parsed RIB. Its non-serializable marker and row digest prove that longest-prefix-match coverage was not lost
    between parsing and this custody boundary. Missing evidence stays distinct.
    ``evidence_sections`` binds the exact interface and config-derived structures assessed later in this same
    process. A digest mismatch or omitted binding can never inherit the current-run trust marker.
    """
    inventory = _as_dict(command_inventory)
    integrity = _as_dict(capture_integrity)
    integrity_available = isinstance(integrity.get("findings"), list) \
        and isinstance(integrity.get("summary"), dict) \
        and isinstance(integrity.get("inspections"), list)
    inspection_status: Dict[Tuple[str, str], str] = {}
    if integrity_available:
        for inspection in integrity["inspections"]:
            row = _as_dict(inspection)
            host = _text(row.get("host"))
            command = _text(row.get("command"))
            status = _text(row.get("status"))
            if host and command and status:
                inspection_status[(host, command)] = status

    yield_report = _as_dict(parse_yield)
    per_parser = _as_dict(yield_report.get("per_parser"))
    yield_receipts = [_as_dict(receipt) for receipt in _as_list(yield_report.get("receipts"))]

    hosts = sorted(set(str(host) for host in inventory) |
                   {host for host, _command in inspection_status})
    records: Dict[str, dict] = {}
    for host in hosts:
        commands = _as_dict(inventory.get(host))
        evidence: Dict[str, dict] = {}
        for kind, variants in _CUSTODY_COMMAND_VARIANTS.items():
            observed: List[Tuple[str, str]] = []
            selected: Optional[Tuple[str, str]] = None
            for command in variants:
                if command not in commands:
                    continue
                status = (inspection_status.get((host, command), "inspection_missing")
                          if integrity_available else "capture_integrity_unavailable")
                observed.append((command, status))
                # The loader can skip an empty/error/unreadable capture and use its next declared variant. It
                # does consume an incomplete/unverified body, which must remain selected but unproven.
                if status not in _CUSTODY_SKIPPABLE_STATUSES:
                    selected = (command, status)
                    break
            if selected is None and observed:
                selected = observed[0]
            command, status = selected if selected is not None else (variants[0], "not_collected")
            evidence[kind] = {
                "status": status,
                "complete": status == "ok",
                "source_command": command,
            }
        records[host] = evidence

    projections = _as_dict(route_projection)
    for host, evidence in records.items():
        evidence["routing_table"]["projection"] = _route_projection_cell(projections.get(host))

    selected_counts = {
        kind: sum(1 for host in records.values() if host[kind]["status"] == "ok")
        for kind in _CUSTODY_COMMAND_VARIANTS
    }
    for host, evidence in records.items():
        for kind, parsers in _CUSTODY_PARSERS.items():
            cell = evidence[kind]
            if cell["status"] != "ok":
                continue
            parser_status = "ok"
            for parser in parsers:
                counts = _as_dict(per_parser.get(parser))
                calls = _nonnegative_count(counts.get("calls"))
                with_content = _nonnegative_count(counts.get("with_content"))
                if calls is None or calls < selected_counts[kind]:
                    parser_status = "parser_denominator_incomplete"
                    break
                if with_content is None or with_content < selected_counts[kind]:
                    parser_status = "parser_input_not_observed"
                    break
                host_tokens = {host.casefold(), safe_fs_name(host).casefold()}
                matching = [receipt for receipt in yield_receipts
                            if _text(receipt.get("parser")) == parser
                            and _text(receipt.get("device")).casefold() in host_tokens
                            and _text(receipt.get("cmd")) == cell["source_command"]]
                if not matching:
                    parser_status = "parser_receipt_missing"
                    break
                if len(matching) != 1:
                    parser_status = "parser_receipt_duplicate"
                    break
                receipt = matching[0]
                receipt_calls = _nonnegative_count(receipt.get("calls"))
                receipt_entities = _nonnegative_count(receipt.get("with_entities"))
                receipt_errors = _nonnegative_count(receipt.get("errors"))
                receipt_zero = _nonnegative_count(receipt.get("zero_yield"))
                if None in (receipt_calls, receipt_entities, receipt_errors, receipt_zero):
                    parser_status = "parser_receipt_malformed"
                    break
                assert receipt_calls is not None and receipt_entities is not None
                assert receipt_errors is not None and receipt_zero is not None
                if receipt_calls < 1 or receipt_calls != receipt_entities + receipt_errors + receipt_zero:
                    parser_status = "parser_receipt_malformed"
                    break
                if receipt_errors > 0:
                    parser_status = "parser_error"
                    break
                if parser in _ZERO_YIELD_IS_GAP and receipt_zero > 0:
                    parser_status = "zero_yield"
                    break
            if parser_status != "ok":
                cell["status"] = parser_status
                cell["complete"] = False

    for host, evidence in records.items():
        for kind in ("acl_definitions", "global_forwarding_config", "interface_attachments"):
            cell = evidence[kind]
            payload = _content_binding_payload(evidence_sections, host, kind)
            digest = _evidence_content_sha256(payload) if payload is not None else ""
            cell["content_sha256"] = digest or None
            if cell["status"] == "ok" and not digest:
                cell["status"] = "content_binding_unavailable"
                cell["complete"] = False

    cells = [cell for host in records.values() for cell in host.values()]
    return _CurrentRunTrafficCustody({
        "schema": TRAFFIC_EVIDENCE_CUSTODY_SCHEMA,
        "owner": "cisco_toolkit.traffic_assurance.build_traffic_evidence_custody",
        "content_binding": "sha256-canonical-json-v1",
        "content_binding_scope": "producer_input_before_optional_global_redaction",
        "hosts": records,
        "summary": {
            "n_hosts": len(records),
            "n_cells": len(cells),
            "n_complete": sum(1 for cell in cells if cell["complete"]),
            "n_unproven": sum(1 for cell in cells if not cell["complete"]),
        },
        "limitations": [
            "command presence, capture-integrity and exact host/command/parser receipts; no raw path or command body is published",
            "configuration/interface content hashes bind the exact in-process structures used by the producer; persisted hashes are audit-only after redaction or JSON load",
            "global forwarding-gate custody covers only parse.FORWARDING_GATE_SYNTAX_REGISTRY plus the current ACL/ABF, object-group and NAT projections; it is not an open-ended proof that every vendor syntax is modeled",
            "ok proves the captured representation passed current integrity checks, not device truth or freshness",
        ],
    })


_SAFE_CUSTODY_STATUSES = frozenset({
    "ok", "empty", "error", "unreadable", "incomplete", "not_observed", "unverified_prompt",
    "inspection_missing", "capture_integrity_unavailable", "not_collected",
    "parser_denominator_incomplete", "parser_input_not_observed", "parser_receipt_missing",
    "parser_receipt_duplicate", "parser_receipt_malformed", "parser_error", "zero_yield",
    "content_binding_unavailable", "content_changed_after_custody",
})
_SAFE_PROJECTION_STATUSES = frozenset({
    "ok", "projection_not_current_run_verified", "projection_receipt_mismatch",
    "route_parse_receipt_missing", "route_parse_incomplete", "invalid_projection_receipt",
})


def _sha256_token(value: Any) -> str:
    return (value if isinstance(value, str) and len(value) == 64
            and all(character in "0123456789abcdef" for character in value) else "")


def _sanitized_projection_cell(value: Any) -> dict:
    """Return only bounded projection receipt scalars; never reflect malformed attacker-controlled values."""
    raw = _as_dict(value)
    status = raw.get("status")
    complete = raw.get("complete")
    scope_raw = raw.get("scope_networks")
    counts = {
        field: _nonnegative_count(raw.get(field))
        for field in ("source_prefix_count", "source_entry_count", "scoped_row_count")
    }
    counts_valid = all(field not in raw or count is not None for field, count in counts.items())
    scoped_digest = _sha256_token(raw.get("scoped_rows_sha256"))
    source_digest = _sha256_token(raw.get("source_routes_sha256"))
    digests_valid = status != "ok" or bool(scoped_digest and source_digest)
    valid = (
        isinstance(status, str)
        and status in _SAFE_PROJECTION_STATUSES
        and type(complete) is bool
        and complete is (status == "ok")
        and isinstance(scope_raw, list)
        and len(scope_raw) <= 4096
        and counts_valid
        and digests_valid
    )
    scope = []
    if valid:
        for token in scope_raw:
            if not isinstance(token, str) or not token or len(token) > 64:
                valid = False
                break
            try:
                token.encode("utf-8")
                network = ipaddress.ip_network(token, strict=False)
            except (UnicodeEncodeError, ValueError):
                valid = False
                break
            if token != str(network):
                valid = False
                break
            scope.append(token)
    if not valid:
        return {"status": "invalid_projection_receipt", "complete": False,
                "scope_networks": []}
    return {
        "status": status,
        "complete": complete,
        "scope_networks": scope,
        **({"scoped_rows_sha256": scoped_digest,
            "source_routes_sha256": source_digest} if scoped_digest and source_digest else {}),
        **{field: int(count) for field, count in counts.items() if count is not None},
    }


def _custody_cell(snap: dict, host: str, kind: str) -> dict:
    raw_custody = snap.get("traffic_evidence_custody")
    custody = _as_dict(raw_custody)
    if custody.get("schema") != TRAFFIC_EVIDENCE_CUSTODY_SCHEMA:
        return {"status": "not_observed", "complete": False, "source_command": None,
                "projection": {"status": "not_observed", "complete": False, "scope_networks": []}}
    if not isinstance(raw_custody, _CurrentRunTrafficCustody):
        return {"status": "embedded_unverified", "complete": False, "source_command": None,
                "projection": {"status": "embedded_unverified", "complete": False,
                               "scope_networks": []}}
    cell = _as_dict(_as_dict(_as_dict(custody.get("hosts")).get(host)).get(kind))
    status = cell.get("status")
    complete = cell.get("complete")
    source_command = cell.get("source_command")
    valid = (
        isinstance(status, str)
        and status in _SAFE_CUSTODY_STATUSES
        and type(complete) is bool
        and complete is (status == "ok")
        and isinstance(source_command, str)
        and source_command in _CUSTODY_COMMAND_VARIANTS.get(kind, ())
    )
    if not valid:
        return {"status": "invalid_custody_receipt", "complete": False, "source_command": None,
                "projection": {"status": "invalid_projection_receipt", "complete": False,
                               "scope_networks": []}}
    content_digest = _sha256_token(cell.get("content_sha256"))
    if kind in ("acl_definitions", "global_forwarding_config", "interface_attachments") and complete:
        if custody.get("content_binding") != "sha256-canonical-json-v1" or not content_digest:
            return {"status": "invalid_custody_receipt", "complete": False,
                    "source_command": source_command, "content_sha256": None,
                    "projection": {"status": "not_observed", "complete": False,
                                   "scope_networks": []}}
        current_payload = _content_binding_payload(snap, host, kind)
        current_digest = (_evidence_content_sha256(current_payload)
                          if current_payload is not None else "")
        if not current_digest:
            return {"status": "content_binding_unavailable", "complete": False,
                    "source_command": source_command, "content_sha256": content_digest,
                    "projection": {"status": "not_observed", "complete": False,
                                   "scope_networks": []}}
        if current_digest != content_digest:
            return {"status": "content_changed_after_custody", "complete": False,
                    "source_command": source_command, "content_sha256": content_digest,
                    "projection": {"status": "not_observed", "complete": False,
                                   "scope_networks": []}}
    return {
        "status": status,
        "complete": complete,
        "source_command": source_command,
        "content_sha256": content_digest or None,
        "projection": (_sanitized_projection_cell(cell.get("projection"))
                       if kind == "routing_table"
                       else {"status": "not_observed", "complete": False,
                             "scope_networks": []}),
    }


def _route_custody(snap: dict, destination: str) -> dict:
    """Affirm completeness across every observed or potentially-L3 host in this snapshot."""
    hosts = set(str(host) for host in _as_dict(snap.get("routes")))
    for host, ports in _as_dict(snap.get("interfaces")).items():
        if any(_text(_field(record, "svi_ip")) for record in _as_dict(ports).values()):
            hosts.add(str(host))
    gaps = []
    for host in sorted(hosts):
        cell = _custody_cell(snap, host, "routing_table")
        if not cell["complete"]:
            gaps.append({"host": host, "status": cell["status"], "source_command": cell["source_command"]})
            continue
        if cell["source_command"] == "show ip route vrf all":
            gaps.append({"host": host, "status": "vrf_aggregate_not_modeled",
                         "source_command": cell["source_command"]})
            continue
        projection = _sanitized_projection_cell(cell.get("projection"))
        current_projection = _sanitized_projection_cell(_route_projection_cell(
            _as_dict(snap.get("routes")).get(host)
        ))
        if projection.get("status") == "invalid_projection_receipt":
            gaps.append({"host": host, "status": "invalid_projection_receipt",
                         "source_command": cell["source_command"]})
            continue
        if current_projection.get("complete") is not True \
                or current_projection.get("status") != "ok":
            gaps.append({"host": host,
                         "status": current_projection.get("status") or "invalid_projection_receipt",
                         "source_command": cell["source_command"]})
            continue
        if projection != current_projection:
            gaps.append({"host": host, "status": "projection_changed_after_custody",
                         "source_command": cell["source_command"]})
            continue
        if projection.get("complete") is not True or projection.get("status") != "ok":
            gaps.append({"host": host, "status": projection.get("status") or "projection_not_observed",
                         "source_command": cell["source_command"]})
            continue
        try:
            target = ipaddress.ip_address(destination)
        except ValueError:
            target = None
        scope = []
        for token in _as_list(projection.get("scope_networks")):
            try:
                scope.append(ipaddress.ip_network(str(token), strict=False))
            except ValueError:
                continue
        if target is None or not any(target.version == net.version and target in net for net in scope):
            gaps.append({"host": host, "status": "destination_outside_projection_scope",
                         "source_command": cell["source_command"]})
    return {
        "verdict": Verdict.PROVEN.value if hosts and not gaps else Verdict.NOT_OBSERVED.value,
        "hosts_checked": sorted(hosts),
        "destination": destination,
        "gaps": gaps,
        "basis": ("traffic_evidence_custody.hosts.*.routing_table + live reconciliation against "
                  "scoped_route_projection/1"),
    }


def _interface_custody(snap: dict, trace: dict) -> dict:
    hosts = sorted({_text(hop.get("host")) for hop in _as_list(trace.get("hops"))
                    if isinstance(hop, dict) and _text(hop.get("host"))})
    gaps = []
    for host in hosts:
        for kind in ("interface_attachments", "global_forwarding_config"):
            cell = _custody_cell(snap, host, kind)
            if not cell["complete"]:
                gaps.append({
                    "host": host,
                    "kind": kind,
                    "status": cell["status"],
                    "source_command": cell["source_command"],
                })
    return {
        "verdict": Verdict.PROVEN.value if hosts and not gaps else Verdict.NOT_OBSERVED.value,
        "hosts_checked": hosts,
        "gaps": gaps,
        "basis": (
            "traffic_evidence_custody.hosts.*.interface_attachments + "
            "traffic_evidence_custody.hosts.*.global_forwarding_config"
        ),
    }


def _custody_trust(snap: dict) -> str:
    return ("current_run_verified"
            if isinstance(snap.get("traffic_evidence_custody"), _CurrentRunTrafficCustody)
            else "embedded_unverified")


def _id_token(value: str) -> str:
    raw = value or "ad-hoc"
    token = "".join(ch if (ch.isalnum() or ch in "._-") else "-" for ch in raw).strip("-") or "ad-hoc"
    if token != raw or len(token) > 96:
        token = f"{token[:83].rstrip('-')}-{sha256(raw.encode('utf-8', errors='surrogatepass')).hexdigest()[:12]}"
    return token


def _port(value: Any, field: str, errors: List[str]) -> Optional[int]:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        errors.append(f"{field} must be an integer from 0 through 65535")
        return None
    if isinstance(value, float):
        if not value.is_integer():
            errors.append(f"{field} must be an integer from 0 through 65535")
            return None
        parsed = int(value)
    elif isinstance(value, int):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = int(value.strip())
        except ValueError:
            errors.append(f"{field} must be an integer from 0 through 65535")
            return None
    else:
        errors.append(f"{field} must be an integer from 0 through 65535")
        return None
    if not 0 <= parsed <= 65535:
        errors.append(f"{field} must be an integer from 0 through 65535")
        return None
    return parsed


def _positive_int(value: Any, field: str, errors: List[str]) -> Optional[int]:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        errors.append(f"{field} must be a positive integer")
        return None
    if isinstance(value, float):
        if not value.is_integer():
            errors.append(f"{field} must be a positive integer")
            return None
        parsed = int(value)
    elif isinstance(value, int):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = int(value.strip())
        except ValueError:
            errors.append(f"{field} must be a positive integer")
            return None
    else:
        errors.append(f"{field} must be a positive integer")
        return None
    if parsed <= 0:
        errors.append(f"{field} must be a positive integer")
        return None
    return parsed


def _snapshot_host_key_errors(snap: dict) -> List[str]:
    """Reject malformed per-host map identities before any engine sorts or serializes them."""
    for section in ("routes", "interfaces", "acls", "object_groups", "nat"):
        value = snap.get(section)
        if not isinstance(value, dict):
            continue
        if any(not isinstance(host, str) or not _text(host) for host in value):
            return ["snapshot per-host evidence keys must be nonempty Unicode-scalar strings"]
    for ports in _as_dict(snap.get("interfaces")).values():
        if not isinstance(ports, dict):
            continue
        if any(not isinstance(interface, str) or not _text(interface) for interface in ports):
            return ["snapshot interface evidence keys must be nonempty Unicode-scalar strings"]
    return []


def _snapshot_intent_constraints(snap: dict, intent: dict) -> Tuple[List[str], List[str]]:
    """Validate endpoint semantics that require the snapshot's connected-prefix denominator."""
    host_key_errors = _snapshot_host_key_errors(snap)
    if host_key_errors:
        return host_key_errors, []
    errors: List[str] = []
    unsupported: List[str] = []
    parsed: Dict[str, Any] = {}
    for field in ("src", "dst"):
        try:
            parsed[field] = ipaddress.ip_address(str(intent.get(field) or "").split("%", 1)[0])
        except ValueError:
            continue
        address = parsed[field]
        if address.is_unspecified or address.is_multicast or str(address) == "255.255.255.255":
            errors.append(f"{field} must be a usable unicast endpoint")

    connected = []
    for host, routes in _as_dict(snap.get("routes")).items():
        for network, admin_distance, _route in fib.compute_fib(routes):
            if admin_distance == 0:
                connected.append((str(host), network))
    interface_addresses = set()
    for ports in _as_dict(snap.get("interfaces")).values():
        for record in _as_dict(ports).values():
            tokens = [_text(_field(record, "svi_ip"))]
            tokens.extend(part.strip() for part in _text(_field(record, "svi_ips")).split(";") if part.strip())
            for token in tokens:
                if not token:
                    continue
                candidate = token.split()[0].split("/", 1)[0]
                try:
                    interface_addresses.add(ipaddress.ip_address(candidate))
                except ValueError:
                    continue
    # A configured first-hop virtual address terminates in a collected router's local stack regardless of which
    # member is currently forwarding. Ambiguous/missing Active state still abstains safely instead of inventing a
    # data-plane egress ACL stage for the VIP.
    for members in _as_dict(snap.get("fhrp_detail")).values():
        for member in _as_list(members):
            if not isinstance(member, dict):
                continue
            try:
                interface_addresses.add(ipaddress.ip_address(_text(member.get("vip"))))
            except ValueError:
                continue
    ownership = fib._connected_index(_as_dict(snap.get("routes")), _as_dict(snap.get("interfaces")))
    for address in parsed.values():
        if fib._hosts_owning_ip(ownership, str(address), exact=True):
            interface_addresses.add(address)
    for field, address in parsed.items():
        for _host, network in connected:
            if network.version != address.version or address not in network or network.prefixlen > 30:
                continue
            if address in (network.network_address, network.broadcast_address):
                errors.append(f"{field} is not a usable host in collected connected prefix {network}")
                break

    if parsed.get("src") == parsed.get("dst") and parsed.get("src") is not None:
        unsupported.append("same_subnet_l2_forwarding")
    elif parsed.get("src") is not None and parsed.get("dst") is not None:
        if any(network.version == parsed["src"].version
               and parsed["src"] in network and parsed["dst"] in network
               for _host, network in connected):
            unsupported.append("same_subnet_l2_forwarding")
    if any(address in interface_addresses for address in parsed.values()):
        unsupported.append("infrastructure_local_endpoint")
    # NAT changes the tuple observed by downstream policy and return routing. Version 1 does not model a
    # translation stage, so even a static one-to-one rule cannot coexist with a hard end-to-end verdict. Keep
    # this deliberately conservative until applicability can be proven per rule and per traced interface.
    if _has_configured_nat(snap.get("nat")):
        unsupported.append("network_address_translation_not_modeled")
    return list(dict.fromkeys(errors)), sorted(set(unsupported))


def _has_configured_nat(value: Any) -> bool:
    """Return whether the snapshot contains any positive NAT configuration evidence.

    Empty per-host parser envelopes remain absence-of-config.  Once the top-level owner map exists, every host
    envelope must be the dict produced by ``parse_nat``; a falsey list/scalar is malformed evidence, not an empty
    parse result.  Nested parser values are then inspected conservatively without assuming a more specific NAT
    schema than the parser currently publishes.
    """
    if isinstance(value, dict):
        host_values = list(value.values())
        if any(not isinstance(host_value, dict) for host_value in host_values):
            return True
        stack = [(host_value, 0) for host_value in host_values]
    else:
        # Legacy callers can omit the top-level owner entirely. Current-run custody independently rejects that
        # shape; retain the historical absence behavior here so this semantic probe does not invent NAT by itself.
        stack = [(value, 0)]
    seen: set[int] = set()
    inspected = 0
    while stack:
        current, depth = stack.pop()
        inspected += 1
        if inspected > 10_000 or depth > 256:
            return True
        if isinstance(current, (dict, list)):
            identity = id(current)
            if identity in seen:
                return True
            seen.add(identity)
            children = current.values() if isinstance(current, dict) else current
            stack.extend((child, depth + 1) for child in children)
            continue
        if current not in (None, "", False, 0):
            return True
    return False


def _normalize_intent(intent: Any) -> Tuple[dict, List[str], List[str]]:
    raw = _as_dict(intent)
    errors: List[str] = []
    unsupported: List[str] = []
    src, dst = _text(raw.get("src")), _text(raw.get("dst"))
    parsed_ips = []
    for field, value in (("src", src), ("dst", dst)):
        if not value:
            errors.append(f"{field} is required")
            parsed_ips.append(None)
            continue
        try:
            parsed_ips.append(ipaddress.ip_address(value.split("%", 1)[0]))
        except ValueError:
            errors.append(f"{field} is not an IP address")
            parsed_ips.append(None)
    if all(ip is not None for ip in parsed_ips) and parsed_ips[0].version != parsed_ips[1].version:
        errors.append("src and dst must use the same address family")
    if any(ip is not None and ip.version != 4 for ip in parsed_ips):
        unsupported.append("ipv6_flow")

    proto_value = raw.get("protocol") if "protocol" in raw else raw.get("proto")
    if proto_value is not None and not isinstance(proto_value, str):
        errors.append("protocol must be a string")
    proto = _text(proto_value).lower()
    if not proto:
        errors.append("protocol is required for traffic_assurance/1")
    elif proto not in _SUPPORTED_PROTOCOLS:
        unsupported.append(f"protocol:{proto}")
    src_port = _port(raw.get("src_port", raw.get("sport")), "src_port", errors)
    dst_port = _port(raw.get("dst_port", raw.get("dport")), "dst_port", errors)
    if proto in _SUPPORTED_PROTOCOLS:
        if src_port is None and dst_port is None:
            errors.append("src_port and dst_port are required for traffic_assurance/1")
        elif (src_port is None) != (dst_port is None):
            errors.append("src_port and dst_port must be declared together for an exact L4 tuple")

    if "expected" in raw and not isinstance(raw.get("expected"), str):
        errors.append("expected must be a string")
    expected = _text(raw.get("expected")).lower() if "expected" in raw else "permit"
    if expected not in _SUPPORTED_EXPECTATIONS:
        errors.append("expected must be 'permit' or 'deny'")
    return_required = raw.get("return_required", True)
    if not isinstance(return_required, bool):
        errors.append("return_required must be a boolean")
        return_required = True
    required_mtu = _positive_int(raw.get("required_mtu"), "required_mtu", errors)
    if expected == "deny" and return_required:
        errors.append(
            "return_required=true cannot be combined with expected='deny'; "
            "declare each denied direction as a separate intent"
        )
    if expected == "deny" and required_mtu is not None:
        errors.append("required_mtu cannot be combined with expected='deny' in traffic_assurance/1")
    if "vrf" in raw and raw.get("vrf") not in (None, "") and not isinstance(raw.get("vrf"), str):
        errors.append("vrf must be a string when declared")
    vrf = _text(raw.get("vrf")) or None
    if vrf:
        unsupported.append("vrf_scoped_forwarding")

    if "id" in raw:
        if not isinstance(raw.get("id"), str):
            errors.append("id must be a string when declared")
        else:
            try:
                raw["id"].encode("utf-8")
            except UnicodeEncodeError:
                errors.append("id must contain only Unicode scalar values")
    if "title" in raw:
        if not isinstance(raw.get("title"), str):
            errors.append("title must be a string when declared")
        else:
            try:
                raw["title"].encode("utf-8")
            except UnicodeEncodeError:
                errors.append("title must contain only Unicode scalar values")
    flow_id = _text(raw.get("id")) or "traffic.assurance.ad-hoc"
    title = _text(raw.get("title"))
    normalized = {
        "id": flow_id,
        "title": title,
        "src": src,
        "dst": dst,
        "protocol": proto or None,
        "src_port": src_port,
        "dst_port": dst_port,
        "expected": expected,
        "return_required": return_required,
        "required_mtu": required_mtu,
        "vrf": vrf,
    }
    return normalized, list(dict.fromkeys(errors)), sorted(set(unsupported))


def _connected_interface(snap: dict, host: str, address: str) -> Tuple[Optional[str], str]:
    """Resolve the connected interface that owns ``address`` on ``host`` from the FIB owner's route records."""
    try:
        ip = ipaddress.ip_address(str(address).split("%", 1)[0])
    except ValueError:
        return None, "address is not parseable"
    routes = _as_dict(snap.get("routes")).get(host)
    candidates: List[Tuple[int, str]] = []
    for network, admin_distance, route in fib.compute_fib(routes):
        if admin_distance != 0 or network.version != ip.version or ip not in network:
            continue
        interface = _text(_as_dict(route).get("out_intf"))
        if interface:
            candidates.append((network.prefixlen, interface))
    if not candidates:
        return None, "no connected interface for the address was collected"
    longest = max(prefix for prefix, _interface in candidates)
    interfaces = sorted({normalize_ifname(interface) for prefix, interface in candidates if prefix == longest})
    if len(interfaces) != 1:
        return None, "connected interface is ambiguous: " + ", ".join(interfaces)
    return interfaces[0], ""


def _interface_record(snap: dict, host: str, interface: str) -> Tuple[Optional[Any], str]:
    ports = _as_dict(_as_dict(snap.get("interfaces")).get(host))
    if not isinstance(interface, str) or not _text(interface):
        return None, "interface identity is malformed"
    want = normalize_ifname(interface)
    matches = [record for name, record in ports.items()
               if isinstance(name, str) and _text(name) and normalize_ifname(name) == want]
    if not matches:
        return None, "interface record not collected"
    first = matches[0]
    try:
        equivalent = all(record == first for record in matches[1:])
    except Exception:
        equivalent = False
    if not equivalent:
        return None, "multiple conflicting interface records normalize to the requested interface"
    return first, ""


def _field(record: Any, name: str) -> Any:
    return record.get(name) if isinstance(record, dict) else getattr(record, name, None)


def _has_field(record: Any, name: str) -> bool:
    return name in record if isinstance(record, dict) else hasattr(record, name)


_COMMON_FORWARDING_GATE_SCALARS = (
    "security_zone", "crypto_map", "tunnel_protection", "vacl_policy", "global_policy_gates",
    "trustsec_sgacl", "tcp_intercept", "mpls_forwarding", "mpls_mtu", "flowspec_policy",
    "forwarding_gate_candidates", "forwarding_gate_unmodeled",
)
_DIRECTIONAL_FORWARDING_GATE_SCALARS = {
    "in": (
        "acl_in", "global_acl_in", "acl_in_unmodeled", "pbr_policy", "urpf_mode",
        "service_policy_in", "inspection_policy_in", "wccp_redirection_in", "ips_policy_in",
        "admission_policy",
    ),
    "out": (
        "acl_out", "global_acl_out", "acl_out_unmodeled", "service_policy_out",
        "inspection_policy_out", "wccp_redirection_out", "ips_policy_out",
    ),
}
FORWARDING_GATE_SCALAR_FIELDS = frozenset(
    _COMMON_FORWARDING_GATE_SCALARS
    + _DIRECTIONAL_FORWARDING_GATE_SCALARS["in"]
    + _DIRECTIONAL_FORWARDING_GATE_SCALARS["out"]
)
_PATH_CHANGING_GATE_NAMES = frozenset({
    "policy_based_routing", "multiple_or_common_acl_chain", "crypto_map", "tunnel_protection",
    "vlan_access_map", "asa_global_policy", "wccp_redirection", "tcp_intercept",
    "mpls_forwarding", "bgp_flowspec", "service_chaining", "unmodeled_forwarding_candidate",
    "malformed_forwarding_gate_evidence",
    "candidate_projection_incomplete",
})
_SAME_STAGE_ORDER_UNKNOWN_GATES = frozenset({
    "vlan_access_map", "asa_global_policy", "wccp_redirection", "tcp_intercept",
    "mpls_forwarding", "bgp_flowspec", "service_chaining", "unmodeled_forwarding_candidate",
    "malformed_forwarding_gate_evidence",
    "candidate_projection_incomplete",
})


def _validated_gate_scalars(record: Any, direction: str) -> Tuple[Dict[str, str], List[str]]:
    """Classify bounded gate scalars without collapsing malformed evidence into absence.

    Only ``None`` and the exact empty string mean absent. Every other valid Unicode-scalar string is a
    configured token, including whitespace-only strings; non-strings and lone-surrogate strings are fixed
    provenance gaps. Values are returned only for internal lookup and are never copied into gap text.
    """
    values: Dict[str, str] = {}
    malformed: List[str] = []
    # Validate the whole recognized record before stage ordering. A malformed opposite-direction field still
    # means the parser/build projection is not trustworthy enough to issue a hard verdict at this boundary.
    _ = direction
    fields = (
        _COMMON_FORWARDING_GATE_SCALARS
        + _DIRECTIONAL_FORWARDING_GATE_SCALARS["in"]
        + _DIRECTIONAL_FORWARDING_GATE_SCALARS["out"]
    )
    for field in fields:
        value = _field(record, field)
        if value is None or value == "":
            continue
        if not isinstance(value, str):
            malformed.append(field)
            continue
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            malformed.append(field)
            continue
        values[field] = value
    return values, sorted(set(malformed))


def _configured_gate_names(values: Dict[str, str], direction: str) -> List[str]:
    """Map validated parser fields to fixed assurance categories; never expose configured policy names."""
    gates: List[str] = []
    directional = {
        "in": {
            "pbr_policy": "policy_based_routing",
            "urpf_mode": "unicast_rpf",
            "inspection_policy_in": "stateful_inspection",
            "acl_in_unmodeled": "multiple_or_common_acl_chain",
            "wccp_redirection_in": "wccp_redirection",
            "ips_policy_in": "intrusion_prevention",
            "admission_policy": "network_admission",
        },
        "out": {
            "inspection_policy_out": "stateful_inspection",
            "acl_out_unmodeled": "multiple_or_common_acl_chain",
            "wccp_redirection_out": "wccp_redirection",
            "ips_policy_out": "intrusion_prevention",
        },
    }
    for field, gate in directional.get(direction, {}).items():
        if field in values:
            gates.append(gate)
    service_field = "service_policy_in" if direction == "in" else "service_policy_out"
    if service_field in values:
        gates.append(
            "service_chaining"
            if values[service_field].casefold().startswith("service-chain:")
            else ("input_service_policy" if direction == "in" else "output_service_policy")
        )
    for field, gate in (
            ("security_zone", "zone_based_firewall"),
            ("crypto_map", "crypto_map"),
            ("tunnel_protection", "tunnel_protection"),
            ("vacl_policy", "vlan_access_map"),
            ("global_policy_gates", "asa_global_policy"),
            ("trustsec_sgacl", "identity_policy"),
            ("tcp_intercept", "tcp_intercept"),
            ("mpls_forwarding", "mpls_forwarding"),
            ("mpls_mtu", "mpls_forwarding"),
            ("flowspec_policy", "bgp_flowspec"),
            ("forwarding_gate_unmodeled", "unmodeled_forwarding_candidate")):
        if field in values:
            gates.append(gate)
    global_tokens = set()
    if "global_policy_gates" in values:
        global_tokens = {token.strip() for token in values["global_policy_gates"].split(",") if token.strip()}
    if "asa_stateful_firewall" in global_tokens:
        gates.append("stateful_inspection")
    if "tcp_intercept" in values or "bgp_flowspec" in gates:
        gates.append("stateful_inspection")
    if forwarding_gate_candidate_projection_incomplete(values):
        gates.append("candidate_projection_incomplete")
    return sorted(set(gates))


def _policy_stage(snap: dict, headers: dict, host: str, interface: Optional[str], direction: str,
                  role: str, reason: str = "") -> dict:
    row = {
        "host": host,
        "interface": interface,
        "direction": direction,
        "role": role,
        "acl": None,
        "verdict": Verdict.NOT_OBSERVED.value,
        "native_result": "NOT_OBSERVED",
        "matched_by": None,
        "detail": reason,
        "basis": None,
    }
    if not interface:
        return row
    definition_custody = _custody_cell(snap, host, "acl_definitions")
    global_custody = _custody_cell(snap, host, "global_forwarding_config")
    attachment_custody = _custody_cell(snap, host, "interface_attachments")
    if (not definition_custody["complete"] or not global_custody["complete"]
            or not attachment_custody["complete"]):
        gaps = [f"ACL definitions={definition_custody['status']}" if not definition_custody["complete"] else "",
                (f"global forwarding config={global_custody['status']}"
                 if not global_custody["complete"] else ""),
                f"interface attachments={attachment_custody['status']}" if not attachment_custody["complete"] else ""]
        row["detail"] = (
            "configuration custody is not proven for this host ("
            + "; ".join(gap for gap in gaps if gap)
            + "); ACL attachment absence cannot be inferred"
        )
        row["basis"] = "traffic_evidence_custody.hosts.%s" % host
        return row
    record, record_reason = _interface_record(snap, host, interface)
    if record is None:
        row["detail"] = record_reason
        return row
    if _field(record, "run_config_observed") is not True:
        row["detail"] = "this interface's running-config block was not positively observed"
        row["basis"] = f"interfaces.{host}.{interface}.run_config_observed"
        return row
    gate_values, malformed_gate_fields = _validated_gate_scalars(record, direction)
    if malformed_gate_fields:
        row["verdict"] = Verdict.INDETERMINATE.value
        row["native_result"] = "INDETERMINATE"
        row["detail"] = (
            "ACL attachment value is malformed"
            if set(malformed_gate_fields) <= {"acl_in", "acl_out", "global_acl_in", "global_acl_out"}
            else "recognized forwarding-gate scalar evidence is malformed"
        )
        row["provenance_gap"] = "forwarding_gate_scalar_value_malformed"
        row["malformed_gate_fields"] = malformed_gate_fields
        row["unmodeled_forwarding_gates"] = ["malformed_forwarding_gate_evidence"]
        return row
    forwarding_gates = _configured_gate_names(gate_values, direction)
    if forwarding_gates:
        row["unmodeled_forwarding_gates"] = forwarding_gates
    acl_field = "acl_in" if direction == "in" else "acl_out"
    global_acl_field = "global_acl_in" if direction == "in" else "global_acl_out"
    if not _has_field(record, acl_field):
        row["detail"] = f"{acl_field} attachment field was not collected"
        return row
    scoped_present = acl_field in gate_values
    global_present = global_acl_field in gate_values
    scoped_acl_name = gate_values.get(acl_field, "").strip()
    global_acl_name = gate_values.get(global_acl_field, "").strip()
    if (scoped_present and not scoped_acl_name) or (global_present and not global_acl_name):
        row["native_result"] = "INDETERMINATE"
        row["verdict"] = Verdict.INDETERMINATE.value
        row["detail"] = "configured ACL attachment token is not usable for exact lookup"
        row["unmodeled_forwarding_gates"] = sorted(set(
            forwarding_gates + ["malformed_forwarding_gate_evidence"]
        ))
        return row
    if scoped_acl_name and global_acl_name:
        row["native_result"] = "INDETERMINATE"
        row["verdict"] = Verdict.INDETERMINATE.value
        row["detail"] = "multiple interface/global ACL attachment stages are not compositionally modeled"
        forwarding_gates.append("multiple_or_common_acl_chain")
        row["unmodeled_forwarding_gates"] = sorted(set(forwarding_gates))
        return row
    acl_name = scoped_acl_name or global_acl_name
    attachment_field = global_acl_field if global_acl_name else acl_field
    row["basis"] = f"interfaces.{host}.{interface}.{attachment_field}"
    if not acl_name:
        row.update({
            "verdict": Verdict.PROVEN.value,
            "native_result": "NO_ACL_ATTACHED",
            "matched_by": "collected interface attachment",
            "detail": "no stateless ACL is attached in this direction",
        })
        if forwarding_gates:
            row.update({
                "verdict": Verdict.INDETERMINATE.value,
                "native_result": "INDETERMINATE",
                "detail": "configured ingress forwarding gate(s) are outside traffic_assurance/1: "
                          + ", ".join(forwarding_gates),
            })
        return row

    row["acl"] = acl_name
    per_host = _as_dict(_as_dict(snap.get("acls")).get(host))
    if acl_name not in per_host:
        row["detail"] = "ACL is attached but its ordered rules were not collected"
        return row
    rules = per_host.get(acl_name)
    if not isinstance(rules, list):
        row["verdict"] = Verdict.INDETERMINATE.value
        row["native_result"] = "INDETERMINATE"
        row["detail"] = "collected ACL rule set is malformed"
        return row
    if direction == "in" and any(
            "acl_based_forwarding" in _as_list(_as_dict(rule).get("unmodeled_qualifiers"))
            for rule in rules):
        forwarding_gates.append("acl_based_forwarding")
        row["unmodeled_forwarding_gates"] = sorted(set(forwarding_gates))
    object_groups = _as_dict(_as_dict(snap.get("object_groups")).get(host))
    result = aclcheck.search_filters(
        rules, headers, action="permit", object_groups=object_groups, host=host,
        connection_state="unknown",
    )
    native = str(result.get("result") or "INDETERMINATE")
    if native == "WITNESS":
        verdict = Verdict.PROVEN.value
        detail = "the exact tuple is permitted by first-match ACL evaluation"
    elif native == "PROVEN_NONE":
        verdict = Verdict.REFUTED.value
        detail = "the exact tuple is denied (the implicit deny is included)"
    else:
        verdict = Verdict.INDETERMINATE.value
        detail = str(result.get("detail") or "ACL evaluation could not decide")
    row.update({
        "verdict": verdict,
        "native_result": native,
        "matched_by": result.get("matched_by"),
        "detail": detail,
        "basis": f"acls.{host}.{acl_name}",
    })
    dynamic_acl_order = (
        "network_admission" in forwarding_gates
        and row["verdict"] in (Verdict.PROVEN.value, Verdict.REFUTED.value)
    )
    if forwarding_gates and (
            row["verdict"] == Verdict.PROVEN.value
            or "asa_global_policy" in forwarding_gates
            or dynamic_acl_order):
        if dynamic_acl_order:
            # IOS admission/auth-proxy can prepend dynamic ACEs ahead of the configured interface ACL. Preserve
            # the static first-match result as evidence, but never present it as the effective same-stage order.
            row["selected_static_acl_verdict"] = row["verdict"]
        else:
            row["selected_stage_verdict"] = row["verdict"]
        row.update({
            "verdict": Verdict.INDETERMINATE.value,
            "native_result": "INDETERMINATE",
            "detail": "the selected ACL stage cannot decide the tuple while configured forwarding gate(s) "
                      "remain outside traffic_assurance/1: " + ", ".join(forwarding_gates),
        })
    return row


def _policy_direction(snap: dict, trace: dict, headers: dict, direction: str, requested: bool) -> dict:
    if not requested:
        return {
            "direction": direction,
            "requested": False,
            "verdict": "not_requested",
            "stages": [],
            "reason": "an exact IPv4 TCP/UDP five-tuple was not declared",
        }
    hops = [hop for hop in _as_list(trace.get("hops")) if isinstance(hop, dict)]
    if not hops:
        return {
            "direction": direction,
            "requested": True,
            "verdict": Verdict.NOT_OBSERVED.value,
            "stages": [],
            "reason": "no resolved forwarding hops exist on which to locate ACL attachments",
        }

    stages: List[dict] = []
    seen = set()
    for index, hop in enumerate(hops):
        host = _text(hop.get("host"))
        if not host:
            continue
        incoming_address = headers["src"] if index == 0 else _text(hops[index - 1].get("next_hop"))
        incoming, incoming_reason = _connected_interface(snap, host, incoming_address)
        for interface, acl_direction, role, reason in (
                (incoming, "in", "source_ingress" if index == 0 else "transit_ingress", incoming_reason),
                (_text(hop.get("out_intf")) or None, "out", "destination_egress" if index == len(hops) - 1 else "transit_egress", "")):
            key = (host, normalize_ifname(interface or ""), acl_direction)
            if key in seen:
                continue
            seen.add(key)
            stages.append(_policy_stage(snap, headers, host, interface, acl_direction, role, reason))

    verdicts = [row["verdict"] for row in stages]
    if Verdict.REFUTED.value in verdicts:
        verdict = Verdict.REFUTED.value
    elif Verdict.INDETERMINATE.value in verdicts:
        verdict = Verdict.INDETERMINATE.value
    elif Verdict.NOT_OBSERVED.value in verdicts or not verdicts:
        verdict = Verdict.NOT_OBSERVED.value
    else:
        verdict = Verdict.PROVEN.value
    return {
        "direction": direction,
        "requested": True,
        "verdict": verdict,
        "stages": stages,
        "reason": "",
        "summary": {
            "n_stages": len(stages),
            "n_attached": sum(1 for row in stages if row.get("acl")),
            "n_denied": sum(1 for row in stages if row["verdict"] == Verdict.REFUTED.value),
            "n_unresolved": sum(1 for row in stages if row["verdict"] in (
                Verdict.NOT_OBSERVED.value, Verdict.INDETERMINATE.value)),
        },
    }


def _path_direction(trace: dict) -> dict:
    status = str(trace.get("status") or "")
    if not trace.get("computed"):
        verdict = Verdict.NOT_OBSERVED.value
        state = "unresolved"
    elif trace.get("reached"):
        verdict = Verdict.PROVEN.value
        state = "reached"
    elif trace.get("drop_evidence") == "observed_discard":
        verdict = Verdict.REFUTED.value
        state = "observed_drop"
    else:
        # A no-route result is computed against a deliberately scoped route set.  It is a useful finding but not
        # positive evidence that the real device has no route, so it cannot become a hard traffic denial here.
        verdict = Verdict.NOT_OBSERVED.value
        state = "no_route_in_scoped_projection"
    hops = _as_list(trace.get("hops"))
    tunnel_overlay = any(
        normalize_ifname(_text(_as_dict(hop).get("out_intf"))).lower().startswith("tu")
        for hop in hops if isinstance(hop, dict)
    )
    return {
        "verdict": verdict,
        "state": state,
        "scope": "selected_rib_forwarding_projection",
        "endpoint_attachment": "not_assessed",
        "l2_delivery": "not_assessed",
        "overlay_tunnel_forwarding": tunnel_overlay,
        "tunnel_underlay": "not_assessed" if tunnel_overlay else "not_applicable",
        "status": status,
        "reached": bool(trace.get("reached")),
        "drop_evidence": trace.get("drop_evidence"),
        "ecmp_dropping_legs": _as_list(trace.get("ecmp_dropping_legs")),
        "ambiguous_candidate_sets": _as_list(trace.get("ambiguous_candidate_sets")),
        "hops": hops,
    }


def _mtu_direction(snap: dict, trace: dict, required_mtu: Optional[int]) -> dict:
    native = str(trace.get("mtu_verdict") or "INDETERMINATE")
    provenance_gaps = []
    for hop in _as_list(trace.get("hops")):
        row = _as_dict(hop)
        host, interface = _text(row.get("host")), _text(row.get("out_intf"))
        if not host:
            continue
        if not interface:
            provenance_gaps.append({
                "host": host, "interface": None,
                "reason": "egress interface was not observed for this routed hop",
            })
            continue
        record, reason = _interface_record(snap, host, interface)
        if record is None or _field(record, "run_config_observed") is not True:
            provenance_gaps.append({
                "host": host, "interface": interface,
                "reason": reason or "running-config block not positively observed",
            })
    if required_mtu is None:
        verdict = "not_requested"
    elif provenance_gaps:
        verdict = Verdict.NOT_OBSERVED.value
    elif native.startswith("below_required"):
        verdict = Verdict.REFUTED.value
    elif native.startswith("INDETERMINATE"):
        verdict = Verdict.NOT_OBSERVED.value
    else:
        verdict = Verdict.PROVEN.value
    return {
        "verdict": verdict,
        "native_verdict": native,
        "required_mtu": required_mtu,
        "observed_min": trace.get("mtu_min"),
        "bottleneck_hop": trace.get("mtu_bottleneck_hop"),
        "unobserved_hops": _as_list(trace.get("mtu_unobserved_hops")),
        "below_required_hops": _as_list(trace.get("jumbo_blackhole")),
        "provenance_gaps": provenance_gaps,
    }


def _branch_points(snap: dict, trace: dict, dst: str) -> List[dict]:
    points = []
    routes_by_host = _as_dict(snap.get("routes"))
    for hop in _as_list(trace.get("hops")):
        if not isinstance(hop, dict):
            continue
        host = _text(hop.get("host"))
        legs = fib.fib_lookup_all(fib.compute_fib(routes_by_host.get(host)), dst)
        if len(legs) > 1:
            points.append({
                "kind": "installed_ecmp",
                "host": host,
                "leg_count": len(legs),
                "selected_out_intf": _text(hop.get("out_intf")),
                "reason": "all ECMP branches are not traversed for downstream ACL and MTU assurance",
            })
    return points


def _ecmp_interface_provenance(snap: dict, host: str, rows: List[dict]) -> Tuple[List[dict], List[dict]]:
    """Partition ECMP interface facts into positively-custodied rows and explicit gaps."""
    proven, gaps = [], []
    custody = _custody_cell(snap, host, "interface_attachments") if host else {
        "status": "not_observed", "complete": False,
    }
    for row in rows:
        interface = _text(row.get("out_intf")) if isinstance(row, dict) else ""
        record, reason = _interface_record(snap, host, interface) if host and interface else (
            None, "host or interface is not observed")
        if record is not None and _field(record, "run_config_observed") is True and custody["complete"]:
            proven.append(row)
            continue
        if not reason:
            reason = (
                "interface evidence custody is not complete" if not custody["complete"]
                else "running-config block not positively observed"
            )
        gaps.append({
            "host": host or None,
            "interface": interface or None,
            "reason": reason,
            "custody_status": custody.get("status") or "not_observed",
        })
    return proven, gaps


def _forwarding_override_state(
        snap: dict, host: str, interface: str, direction: str) -> Tuple[List[str], str]:
    """Return configured path-changing gates, or a categorical provenance gap, for one interface stage.

    This deliberately excludes gates such as uRPF and ordinary service policies that can permit/drop but cannot
    make a later selected-RIB discard interface reachable.  PBR, ABF/common ACL chains, crypto/tunnel boundaries,
    and VACLs can replace the path or packet headers before that discard and therefore prevent a hard ECMP-drop
    conclusion until their semantics are modeled.
    """
    global_custody = _custody_cell(snap, host, "global_forwarding_config")
    if not global_custody["complete"]:
        return [], "global_forwarding_config_custody_incomplete"
    custody = _custody_cell(snap, host, "interface_attachments")
    if not custody["complete"]:
        return [], "interface_attachment_custody_incomplete"
    record, _reason = _interface_record(snap, host, interface)
    if record is None:
        return [], "interface_record_not_observed"
    if _field(record, "run_config_observed") is not True:
        return [], "interface_running_config_not_observed"

    gate_values, malformed_gate_fields = _validated_gate_scalars(record, direction)
    if malformed_gate_fields:
        return ["malformed_forwarding_gate_evidence"], "forwarding_gate_scalar_value_malformed"
    gates = [
        gate for gate in _configured_gate_names(gate_values, direction)
        if gate in _PATH_CHANGING_GATE_NAMES
    ]
    if direction == "in":
        acl_field = "acl_in"
        global_acl_field = "global_acl_in"
    else:
        acl_field = "acl_out"
        global_acl_field = "global_acl_out"

    # A single attached XR ACL can carry ABF without using the multi/common-chain attachment marker.  Proving
    # its absence therefore requires the bound ACL-definition evidence as well as the interface attachment.
    acl_names = []
    for field in (acl_field, global_acl_field):
        if field not in gate_values:
            continue
        name = gate_values[field].strip()
        if not name:
            return sorted(set(gates + ["malformed_forwarding_gate_evidence"])), (
                "acl_attachment_token_unusable"
            )
        acl_names.append(name)
    if len(acl_names) > 1:
        gates.append("multiple_or_common_acl_chain")
    if acl_names:
        definition_custody = _custody_cell(snap, host, "acl_definitions")
        if not definition_custody["complete"]:
            return sorted(set(gates)), "acl_definition_custody_incomplete"
        definitions = _as_dict(_as_dict(snap.get("acls")).get(host))
        for acl_name in acl_names:
            rules = definitions.get(acl_name)
            if not isinstance(rules, list):
                return sorted(set(gates)), "attached_acl_definition_not_observed"
            if any(
                    "acl_based_forwarding" in _as_list(_as_dict(rule).get("unmodeled_qualifiers"))
                    for rule in rules):
                gates.append("acl_based_forwarding")
    return sorted(set(gates)), ""


def _ecmp_leg_gate_gaps(
        snap: dict, src: str, trace: dict, rows: List[dict]) -> Tuple[List[dict], List[dict]]:
    """Partition resolved ECMP legs by whether every path-changing override boundary was assessed."""
    proven: List[dict] = []
    gaps: List[dict] = []
    selected_hops = [hop for hop in _as_list(trace.get("hops")) if isinstance(hop, dict)]
    for leg_index, row in enumerate(rows):
        hops = [hop for hop in _as_list(row.get("resolved_hops")) if isinstance(hop, dict)]
        branch_host = _text(row.get("host"))
        if not hops or not branch_host or _text(hops[0].get("host")) != branch_host:
            gaps.append({
                "leg_index": leg_index,
                "status": "ecmp_leg_resolution_not_observed",
                "host": branch_host or None,
            })
            continue
        branch_positions = [
            index for index, hop in enumerate(selected_hops) if _text(hop.get("host")) == branch_host
        ]
        if len(branch_positions) != 1:
            gaps.append({
                "leg_index": leg_index,
                "status": "ecmp_leg_ingress_not_localized",
                "host": branch_host,
            })
            continue
        branch_position = branch_positions[0]
        branch_ingress_address = (
            src if branch_position == 0 else _text(selected_hops[branch_position - 1].get("next_hop"))
        )
        leg_gaps: List[dict] = []
        for hop_index, hop in enumerate(hops):
            host = _text(hop.get("host"))
            if not host:
                leg_gaps.append({"status": "ecmp_leg_host_not_observed"})
                continue
            incoming_address = (
                branch_ingress_address if hop_index == 0 else _text(hops[hop_index - 1].get("next_hop"))
            )
            incoming, _incoming_reason = _connected_interface(snap, host, incoming_address)
            stages: List[Tuple[Optional[str], str]] = [(incoming, "in")]
            outgoing = _text(hop.get("out_intf"))
            if outgoing and not fib._is_discard(outgoing):
                stages.append((outgoing, "out"))
            for interface, direction in stages:
                if not interface:
                    leg_gaps.append({
                        "status": "ecmp_leg_interface_not_observed",
                        "host": host,
                        "direction": direction,
                    })
                    continue
                gates, status = _forwarding_override_state(snap, host, interface, direction)
                if status or gates:
                    leg_gaps.append({
                        "status": status or "unmodeled_forwarding_override",
                        "host": host,
                        "interface": normalize_ifname(interface),
                        "direction": direction,
                        "gates": gates,
                    })
        if leg_gaps:
            gaps.extend({"leg_index": leg_index, **gap} for gap in leg_gaps)
        else:
            proven.append(row)
    return proven, gaps


def _ecmp_direction(snap: dict, src: str, dst: str, trace: dict,
                    required_mtu: Optional[int]) -> dict:
    result = fib.ecmp_consistency(snap, src, dst)
    native = str(result.get("verdict") or "INDETERMINATE")
    points = _branch_points(snap, trace, dst)
    points.extend({
        "kind": str(row.get("kind") or "ambiguous_owner"),
        "candidate_hosts": sorted(str(host) for host in _as_list(row.get("candidate_hosts"))),
        "reason": "one representative path cannot prove policy and MTU across ambiguous forwarding owners",
    } for row in _as_list(trace.get("ambiguous_candidate_sets")) if isinstance(row, dict))
    dropping_legs = _as_list(trace.get("ecmp_dropping_legs"))
    forwarding_divergence = [
        {**row, "host": _text(row.get("host")) or _text(result.get("host"))}
        for row in _as_list(result.get("forwarding_divergence")) if isinstance(row, dict)
    ]
    candidate_observed_dropping = [
        row for row in dropping_legs + forwarding_divergence
        if isinstance(row, dict) and row.get("drop_evidence") == "observed_discard"
    ]
    observed_dropping, dropping_leg_gate_gaps = _ecmp_leg_gate_gaps(
        snap, src, trace, candidate_observed_dropping)
    candidate_reached_legs = [
        {**row, "host": _text(row.get("host")) or _text(result.get("host"))}
        for row in _as_list(result.get("forwarding_reached_legs")) if isinstance(row, dict)
    ]
    _proven_reached_legs, reached_leg_gate_gaps = _ecmp_leg_gate_gaps(
        snap, src, trace, candidate_reached_legs)
    scoped_absence = [row for row in dropping_legs + forwarding_divergence
                      if isinstance(row, dict) and row.get("drop_evidence") != "observed_discard"]
    mtu_below_candidates = [
        {**row, "host": _text(row.get("host")) or _text(result.get("host"))}
        for row in _as_list(result.get("mtu_divergence"))
        if required_mtu is not None and isinstance(row, dict)
        and isinstance(row.get("mtu"), int) and row["mtu"] < required_mtu
    ]
    mtu_with_provenance, mtu_provenance_gaps = _ecmp_interface_provenance(
        snap, _text(result.get("host")), mtu_below_candidates)
    mtu_below, mtu_leg_gate_gaps = _ecmp_leg_gate_gaps(
        snap, src, trace, mtu_with_provenance)
    _acl_rows = [row for row in _as_list(result.get("acl_divergence")) if isinstance(row, dict)]
    _acl_proven, acl_provenance_gaps = _ecmp_interface_provenance(
        snap, _text(result.get("host")), _acl_rows)
    custody = _route_custody(snap, dst)
    if custody["verdict"] != Verdict.PROVEN.value:
        verdict = Verdict.NOT_OBSERVED.value
    elif observed_dropping or mtu_below:
        verdict = Verdict.REFUTED.value
    elif (native == "inconsistent" or scoped_absence or points or dropping_leg_gate_gaps
          or reached_leg_gate_gaps or mtu_leg_gate_gaps):
        verdict = Verdict.INDETERMINATE.value
    elif native == "INDETERMINATE":
        verdict = Verdict.NOT_OBSERVED.value
    else:  # consistent or not_ecmp
        verdict = Verdict.PROVEN.value
    # Preserve the engine's native token separately; the canonical ADT verdict must win the merge.
    return {
        **result,
        "native_verdict": native,
        "verdict": verdict,
        "scope": "source-owner ECMP consistency plus selected-path branch-point census",
        "route_custody": custody,
        "branch_complete": not points,
        "unassessed_branch_points": points,
        "selected_rib_observed_dropping_legs": candidate_observed_dropping,
        "observed_dropping_legs": observed_dropping,
        "dropping_leg_gate_gaps": dropping_leg_gate_gaps,
        "reached_leg_gate_gaps": reached_leg_gate_gaps,
        "scoped_absence_legs": scoped_absence,
        "selected_rib_mtu_below_required_legs": mtu_below_candidates,
        "mtu_below_required_legs": mtu_below,
        "mtu_provenance_gaps": mtu_provenance_gaps,
        "mtu_leg_gate_gaps": mtu_leg_gate_gaps,
        "acl_provenance_gaps": acl_provenance_gaps,
    }


def _decision(intent: dict, path: dict, policy: dict, mtu: dict, ecmp: dict) -> Tuple[str, List[str]]:
    expected = intent["expected"]
    required_directions = ["forward"] + (["reverse"] if intent["return_required"] else [])
    reasons: List[str] = []

    if expected == "deny":
        if path["forward"]["verdict"] == Verdict.REFUTED.value:
            if ecmp["forward"]["verdict"] == Verdict.PROVEN.value:
                return Verdict.PROVEN.value, ["forward path has positive drop evidence across the required branch denominator"]
            return Verdict.INDETERMINATE.value, [
                "the selected forward path drops, but all installed forwarding branches were not proven"
            ]
        if ecmp["forward"]["verdict"] != Verdict.PROVEN.value:
            return Verdict.INDETERMINATE.value, [
                "all installed forwarding branches were not proven to enforce the requested denial"
            ]
        if policy["forward"]["verdict"] == Verdict.REFUTED.value:
            return Verdict.PROVEN.value, ["forward stateless policy denies the exact tuple"]
        if path["forward"]["verdict"] == Verdict.PROVEN.value and (
                not policy["forward"]["requested"] or
                policy["forward"]["verdict"] == Verdict.PROVEN.value):
            return Verdict.REFUTED.value, ["forward path reaches and no requested stateless policy stage denies it"]
        return Verdict.INDETERMINATE.value, ["the available path/policy evidence cannot prove or refute denial"]

    for direction in required_directions:
        if (path[direction]["verdict"] == Verdict.REFUTED.value
                and ecmp[direction]["verdict"] == Verdict.PROVEN.value):
            reasons.append(f"{direction} path has positive drop evidence")
        if policy[direction]["requested"] and policy[direction]["verdict"] == Verdict.REFUTED.value:
            reasons.append(f"{direction} stateless policy denies the exact tuple")
        if mtu[direction]["verdict"] == Verdict.REFUTED.value:
            reasons.append(f"{direction} path is below the declared MTU")
        if ecmp[direction]["verdict"] == Verdict.REFUTED.value:
            reasons.append(f"{direction} ECMP legs are inconsistent")
    if reasons:
        return Verdict.REFUTED.value, reasons

    unresolved: List[str] = []
    for direction in required_directions:
        if path[direction]["verdict"] != Verdict.PROVEN.value:
            unresolved.append(f"{direction} path is not proven")
        if policy[direction]["requested"] and policy[direction]["verdict"] != Verdict.PROVEN.value:
            unresolved.append(f"{direction} stateless policy is not proven")
        if mtu[direction]["verdict"] not in ("not_requested", Verdict.PROVEN.value):
            unresolved.append(f"{direction} MTU requirement is not proven")
        if ecmp[direction]["verdict"] != Verdict.PROVEN.value:
            unresolved.append(f"{direction} ECMP consistency is not proven")
    if unresolved:
        return Verdict.INDETERMINATE.value, unresolved
    return Verdict.PROVEN.value, ["every requested synthetic dimension passed within the declared scope"]


def _required_verdict(intent: dict, dimension: dict) -> Tuple[str, List[str]]:
    directions = ["forward"] + (["reverse"] if intent["return_required"] else [])
    verdicts = [str(_as_dict(dimension.get(direction)).get("verdict") or Verdict.NOT_OBSERVED.value)
                for direction in directions]
    if Verdict.REFUTED.value in verdicts:
        verdict = Verdict.REFUTED.value
    elif all(value == Verdict.PROVEN.value for value in verdicts):
        verdict = Verdict.PROVEN.value
    elif Verdict.INDETERMINATE.value in verdicts:
        verdict = Verdict.INDETERMINATE.value
    else:
        verdict = Verdict.NOT_OBSERVED.value
    return verdict, directions


def _requested_claim_verdict(expected: str, observed: str, axis: str) -> str:
    """Translate a raw reach/permit observation into conformance with the requested expectation."""
    if expected != "deny":
        return observed
    if observed == Verdict.REFUTED.value:
        return Verdict.PROVEN.value
    if observed == Verdict.PROVEN.value:
        # A reachable path alone does not refute a requested deny because policy can still enforce it. A proven
        # permit disposition, however, positively refutes the requested stateless-policy outcome.
        return Verdict.REFUTED.value if axis == "policy" else Verdict.INDETERMINATE.value
    return observed


def _conjunctive_verdict(*observed: str) -> str:
    """Conjoin required evidence dimensions without letting one selected-path success hide a bad branch."""
    if Verdict.REFUTED.value in observed:
        return Verdict.REFUTED.value
    if observed and all(value == Verdict.PROVEN.value for value in observed):
        return Verdict.PROVEN.value
    if Verdict.INDETERMINATE.value in observed:
        return Verdict.INDETERMINATE.value
    return Verdict.NOT_OBSERVED.value


def _invalid_result(intent: dict, errors: List[str], unsupported: List[str]) -> dict:
    return {
        "schema": TRAFFIC_ASSURANCE_SCHEMA,
        "owner": TRAFFIC_ASSURANCE_OWNER,
        "intent": intent,
        "valid": False,
        "validation_errors": errors,
        "supported": not unsupported,
        "unsupported_semantics": unsupported,
        "custody_trust": "not_evaluated",
        "verdict": Verdict.INDETERMINATE.value,
        "verdict_reasons": ["intent validation failed"],
        "dimensions": {},
        "failure": {"requested": False, "verdict": "not_requested"},
        "claims": [],
        "nrfu_test_ids": [],
        "sources": [
            "routes", "interfaces", "acls", "object_groups", "nat", "stp_roots", "fhrp_detail",
            "traffic_evidence_custody",
        ],
        "limitations": list(_BASE_LIMITATIONS),
    }


def _assess_core(snap: dict, intent: dict, unsupported: List[str]) -> dict:
    exact_l4 = (intent["protocol"] in _SUPPORTED_PROTOCOLS and intent["src_port"] is not None
                and intent["dst_port"] is not None and not unsupported)
    bidirectional = fib.trace_bidirectional(
        snap, intent["src"], intent["dst"], required_mtu=intent["required_mtu"], disclose=True)
    forward_trace, reverse_trace = bidirectional["forward"], bidirectional["reverse"]
    path = {"forward": _path_direction(forward_trace), "reverse": _path_direction(reverse_trace),
            "rpf_verdict": bidirectional.get("rpf_verdict"),
            "symmetric": bool(bidirectional.get("symmetric")),
            "asymmetry": _as_list(bidirectional.get("asymmetry"))}
    forward_headers = {"src": intent["src"], "dst": intent["dst"], "proto": intent["protocol"],
                       "sport": intent["src_port"], "dport": intent["dst_port"]}
    reverse_headers = {"src": intent["dst"], "dst": intent["src"], "proto": intent["protocol"],
                       "sport": intent["dst_port"], "dport": intent["src_port"]}
    policy = {
        "forward": _policy_direction(snap, forward_trace, forward_headers, "forward", exact_l4),
        "reverse": _policy_direction(snap, reverse_trace, reverse_headers, "reverse", exact_l4),
    }
    mtu = {
        "forward": _mtu_direction(snap, forward_trace, intent["required_mtu"]),
        "reverse": _mtu_direction(snap, reverse_trace, intent["required_mtu"]),
    }
    ecmp = {
        "forward": _ecmp_direction(
            snap, intent["src"], intent["dst"], forward_trace, intent["required_mtu"]),
        "reverse": _ecmp_direction(
            snap, intent["dst"], intent["src"], reverse_trace, intent["required_mtu"]),
    }
    for direction in ("forward", "reverse"):
        trace = forward_trace if direction == "forward" else reverse_trace
        destination = intent["dst"] if direction == "forward" else intent["src"]
        route_custody = _route_custody(snap, destination)
        interface_custody = _interface_custody(snap, trace)
        stages = [stage for stage in _as_list(policy[direction].get("stages")) if isinstance(stage, dict)]
        routing_override_indexes = [
            index for index, stage in enumerate(stages)
            if (_PATH_CHANGING_GATE_NAMES | {"acl_based_forwarding"}).intersection(
                _as_list(stage.get("unmodeled_forwarding_gates"))
            )
        ]
        if routing_override_indexes:
            first_override = min(routing_override_indexes)
            first_override_gates = set(_as_list(stages[first_override].get("unmodeled_forwarding_gates")))
            # An interface ACL's order relative to a globally bound VACL is not represented.  For VACL, a deny
            # on the same synthesized stage is not known to occur before a possible redirect; only a strictly
            # earlier stage can remain definitive.  PBR/ABF keep their existing same-stage ordering contract.
            deny_prefix_end = (
                first_override
                if _SAME_STAGE_ORDER_UNKNOWN_GATES.intersection(first_override_gates)
                else first_override + 1
            )
            pre_override_deny = any(
                stage.get("verdict") == Verdict.REFUTED.value for stage in stages[:deny_prefix_end]
            )
            override_gates = sorted({
                gate for index in routing_override_indexes
                for gate in _as_list(stages[index].get("unmodeled_forwarding_gates"))
                if gate in (_PATH_CHANGING_GATE_NAMES | {"acl_based_forwarding"})
            })
            for stage in stages[first_override + 1:]:
                stage["selected_rib_applicability"] = "not_established_after_unmodeled_pbr"
            if not pre_override_deny and policy[direction]["verdict"] != Verdict.INDETERMINATE.value:
                policy[direction]["selected_path_verdict"] = policy[direction]["verdict"]
                policy[direction]["verdict"] = Verdict.INDETERMINATE.value
                policy[direction]["reason"] = (
                    "configured forwarding overrides can replace the selected RIB path before downstream stages: "
                    + ", ".join(override_gates)
                )
            for dimension, label in (
                    (path[direction], "path"), (mtu[direction], "MTU"), (ecmp[direction], "ECMP")):
                if dimension.get("verdict") != Verdict.INDETERMINATE.value:
                    dimension["selected_rib_verdict"] = dimension.get("verdict")
                dimension["verdict"] = Verdict.INDETERMINATE.value
                dimension["applicability"] = (
                    "unmodeled_policy_based_routing"
                    if override_gates == ["policy_based_routing"] else "unmodeled_forwarding_override"
                )
                dimension["reason"] = (
                    f"selected-RIB {label} evidence cannot decide a flow whose ingress applies: "
                    + ", ".join(override_gates)
                )
        packet_gate_names = sorted({
            gate
            for stage in stages
            for gate in _as_list(stage.get("unmodeled_forwarding_gates"))
            if gate in {
                "unicast_rpf", "zone_based_firewall", "input_service_policy", "output_service_policy",
                "multiple_or_common_acl_chain", "stateful_inspection", "crypto_map", "tunnel_protection",
                "vlan_access_map", "asa_global_policy", "identity_policy", "wccp_redirection",
                "tcp_intercept", "mpls_forwarding", "bgp_flowspec", "intrusion_prevention",
                "network_admission", "service_chaining", "unmodeled_forwarding_candidate",
                "malformed_forwarding_gate_evidence", "candidate_projection_incomplete",
            }
        })
        if packet_gate_names:
            for dimension, label in (
                    (path[direction], "path"), (mtu[direction], "MTU"), (ecmp[direction], "ECMP")):
                if dimension.get("verdict") != Verdict.INDETERMINATE.value:
                    dimension["selected_rib_verdict"] = dimension.get("verdict")
                dimension["verdict"] = Verdict.INDETERMINATE.value
                dimension["applicability"] = "unmodeled_configured_packet_gate"
                dimension["reason"] = (
                    f"selected-RIB {label} evidence cannot establish delivery through configured, unmodeled "
                    "packet gates: " + ", ".join(packet_gate_names)
                )
        if not (trace.get("computed") is True and trace.get("reached") is True):
            if policy[direction]["verdict"] == Verdict.PROVEN.value:
                policy[direction]["selected_prefix_verdict"] = Verdict.PROVEN.value
                policy[direction]["verdict"] = Verdict.NOT_OBSERVED.value
                policy[direction]["reason"] = (
                    "observed prefix ACL stages permit the tuple, but the end-to-end forwarding path is incomplete"
                )
            positive_discard = (
                trace.get("computed") is True
                and trace.get("drop_evidence") == "observed_discard"
            )
            if ecmp[direction]["verdict"] == Verdict.PROVEN.value and not positive_discard:
                ecmp[direction]["selected_prefix_verdict"] = Verdict.PROVEN.value
                ecmp[direction]["verdict"] = Verdict.NOT_OBSERVED.value
                ecmp[direction]["reason"] = (
                    "source-prefix ECMP evidence cannot establish branch completeness on an unresolved path"
                )
        points = ecmp[direction]["unassessed_branch_points"]
        ambiguous_owners = any(str(point.get("kind") or "").startswith("ambiguous_")
                               for point in points if isinstance(point, dict))
        if ambiguous_owners and policy[direction]["verdict"] in (
                Verdict.PROVEN.value, Verdict.REFUTED.value):
            policy[direction]["selected_path_verdict"] = policy[direction]["verdict"]
            policy[direction]["verdict"] = Verdict.INDETERMINATE.value
            policy[direction]["reason"] = (
                "the selected candidate's ACL result cannot decide among ambiguous forwarding owners"
            )
            policy[direction]["branch_complete"] = False
        elif points and policy[direction]["verdict"] in (
                Verdict.PROVEN.value, Verdict.REFUTED.value):
            policy[direction]["selected_path_verdict"] = policy[direction]["verdict"]
            policy[direction]["verdict"] = Verdict.INDETERMINATE.value
            policy[direction]["reason"] = (
                "the selected-path ACL result cannot decide the exact flow while installed forwarding "
                "branches remain unevaluated"
            )
            policy[direction]["branch_complete"] = False
        if ambiguous_owners and mtu[direction]["verdict"] in (
                Verdict.PROVEN.value, Verdict.REFUTED.value):
            mtu[direction]["selected_path_verdict"] = mtu[direction]["verdict"]
            mtu[direction]["verdict"] = Verdict.INDETERMINATE.value
            mtu[direction]["reason"] = (
                "the selected candidate's MTU cannot decide among ambiguous forwarding owners"
            )
            mtu[direction]["branch_complete"] = False
        elif points and mtu[direction]["verdict"] in (
                Verdict.PROVEN.value, Verdict.REFUTED.value):
            mtu[direction]["selected_path_verdict"] = mtu[direction]["verdict"]
            mtu[direction]["verdict"] = Verdict.INDETERMINATE.value
            mtu[direction]["reason"] = (
                "the selected-path MTU result cannot decide the exact flow while installed forwarding "
                "branches remain unevaluated"
            )
            mtu[direction]["branch_complete"] = False

        # Selected-path evidence is useful but cannot establish complete policy or MTU assurance while the
        # route-table denominator is missing or non-ok. Preserve it under selected_path_verdict.
        if route_custody["verdict"] != Verdict.PROVEN.value:
            if path[direction]["verdict"] in (Verdict.PROVEN.value, Verdict.REFUTED.value):
                path[direction]["selected_projection_verdict"] = path[direction]["verdict"]
                path[direction]["verdict"] = Verdict.INDETERMINATE.value
                path[direction]["reason"] = (
                    "the selected route chain exists in the scoped projection, but route-table custody is incomplete"
                )
            path[direction]["route_custody"] = route_custody
            for dimension, label in ((policy[direction], "policy"), (mtu[direction], "MTU")):
                if dimension["verdict"] in (Verdict.PROVEN.value, Verdict.REFUTED.value):
                    dimension["selected_path_verdict"] = dimension["verdict"]
                    dimension["verdict"] = Verdict.INDETERMINATE.value
                    dimension["reason"] = (
                        f"selected-path {label} evidence exists, but route-table custody is incomplete"
                    )
            policy[direction]["route_custody"] = route_custody
            mtu[direction]["route_custody"] = route_custody
        if interface_custody["verdict"] != Verdict.PROVEN.value:
            for dimension, label, evidence_field in (
                    (path[direction], "selected-RIB path", "selected_projection_verdict"),
                    (policy[direction], "stateless policy", "selected_path_verdict"),
                    (mtu[direction], "selected-path MTU", "selected_path_verdict"),
                    (ecmp[direction], "ECMP", "selected_rib_verdict")):
                if dimension.get("verdict") in (Verdict.PROVEN.value, Verdict.REFUTED.value):
                    dimension.setdefault(evidence_field, dimension["verdict"])
                    dimension["verdict"] = Verdict.INDETERMINATE.value
                    dimension["reason"] = (
                        f"{label} evidence exists, but scoped-interface or modeled global-forwarding-config "
                        "custody is incomplete"
                    )
                dimension["forwarding_config_custody"] = interface_custody
        mtu[direction]["interface_custody"] = interface_custody
        if (path[direction].get("verdict") == Verdict.REFUTED.value
                and ecmp[direction].get("verdict") != Verdict.PROVEN.value):
            path[direction].setdefault("selected_projection_verdict", Verdict.REFUTED.value)
            path[direction]["verdict"] = Verdict.INDETERMINATE.value
            path[direction]["reason"] = (
                "the selected RIB branch has positive discard evidence, but the installed branch denominator "
                "is not proven"
            )

    # A stateful inspection policy couples the forward and return dispositions.  Static evaluation of the
    # opposite direction cannot refute or prove a paired flow because the unobserved session may dynamically
    # admit it.  Until connection-state/order semantics are modeled, abstain across both requested directions.
    requested_directions = ["forward"] + (["reverse"] if intent["return_required"] else [])
    stateful_directions = [
        direction for direction in requested_directions
        if any(
            "stateful_inspection" in _as_list(stage.get("unmodeled_forwarding_gates"))
            for stage in _as_list(policy[direction].get("stages"))
            if isinstance(stage, dict)
        )
    ]
    if stateful_directions:
        for direction in requested_directions:
            if policy[direction].get("verdict") != Verdict.INDETERMINATE.value:
                policy[direction]["selected_session_independent_verdict"] = policy[direction].get("verdict")
            policy[direction]["verdict"] = Verdict.INDETERMINATE.value
            policy[direction]["applicability"] = "paired_stateful_session_not_modeled"
            policy[direction]["reason"] = (
                "stateful inspection in the requested paired flow makes static forward/return ACL disposition "
                "insufficient: " + ", ".join(stateful_directions)
            )

    path_scope_unsupported = sorted(set(unsupported) & {
        "ipv6_flow", "vrf_scoped_forwarding", "same_subnet_l2_forwarding", "infrastructure_local_endpoint",
        "network_address_translation_not_modeled",
    })
    if path_scope_unsupported:
        reason = "requested forwarding scope is unsupported: " + ", ".join(path_scope_unsupported)
        for direction in ("forward", "reverse"):
            for dimension in (path[direction], mtu[direction], ecmp[direction]):
                dimension["scoped_projection_verdict"] = dimension.get("verdict")
                dimension["verdict"] = Verdict.INDETERMINATE.value
                dimension["applicability"] = "unsupported_request"
                dimension["reason"] = reason
        path["scoped_rpf_verdict"] = path.get("rpf_verdict")
        path["rpf_verdict"] = "INDETERMINATE"
        path["symmetric"] = False
    if unsupported:
        reason = "exact stateless policy is outside the requested supported scope: " + ", ".join(unsupported)
        for direction in ("forward", "reverse"):
            policy[direction]["selected_scope_verdict"] = policy[direction].get("verdict")
            policy[direction]["verdict"] = Verdict.INDETERMINATE.value
            policy[direction]["applicability"] = "unsupported_request"
            policy[direction]["reason"] = reason
    verdict, reasons = _decision(intent, path, policy, mtu, ecmp)
    return {
        "path": path,
        "policy": policy,
        "mtu": mtu,
        "ecmp": ecmp,
        "verdict": verdict,
        "verdict_reasons": reasons,
        "exact_l4_evaluated": exact_l4,
    }


def _failure_assurance(snap: dict, intent: dict, failure: Any, baseline: dict,
                       unsupported: List[str]) -> Tuple[dict, Optional[dict]]:
    if failure is None:
        return {"requested": False, "verdict": "not_requested"}, None
    step = _as_dict(failure)
    after, receipt = cutover_sim.apply_cutover_step(snap, step)
    action = _text(receipt.get("action")) or "invalid_step"
    evidence = (
        cutover_sim.simulate_cutover(
            snap, [step], pairs=[(intent["src"], intent["dst"]), (intent["dst"], intent["src"])]
            if intent["return_required"] else [(intent["src"], intent["dst"])])
        if receipt["valid"] else {
            "schema": "cutover_sim/1", "steps": [], "worst_step": None,
            "summary": {"status": "not_evaluated_invalid_mutation"},
        }
    )
    result = {
        "requested": True,
        "action": action,
        "mutation": receipt,
        "cutover_evidence": evidence,
        "verdict": Verdict.INDETERMINATE.value,
        "status": "invalid" if not receipt["valid"] else ("no_effect" if receipt["is_noop"] else "evaluated"),
        "baseline_verdict": baseline["verdict"],
        "post_verdict": None,
        "post_dimensions": None,
    }
    if unsupported:
        result["status"] = "unsupported_semantics"
        result["baseline_verdict"] = Verdict.INDETERMINATE.value
        return result, None
    if action not in _SUPPORTED_FAILURE_ACTIONS:
        result["status"] = "unsupported_action_for_traffic_assurance"
        return result, None
    if not receipt["valid"] or receipt["is_noop"]:
        return result, None
    post = _assess_core(after, intent, unsupported)
    result["post_verdict"] = post["verdict"]
    result["post_dimensions"] = {k: post[k] for k in ("path", "policy", "mtu", "ecmp")}
    cutover_summary = _as_dict(evidence.get("summary"))
    l2_indeterminate = int(cutover_summary.get("total_indeterminate") or 0)
    split_brain = int(cutover_summary.get("total_split_brain_risks") or 0)
    l2_continuity_gaps = [
        {
            "step_index": row.get("step_index"),
            "election_projection_count": _as_dict(row.get("l2_continuity")).get(
                "election_projection_count", 0),
            "reason": _as_dict(row.get("l2_continuity")).get("reason"),
        }
        for row in _as_list(evidence.get("steps"))
        if isinstance(row, dict)
        and _as_dict(row.get("l2_continuity")).get("applicable") is True
        and _as_dict(row.get("l2_continuity")).get("assessed") is not True
    ]
    result["cutover_gate"] = {
        "verdict": Verdict.PROVEN.value if not l2_indeterminate and not split_brain
        and not l2_continuity_gaps
        else Verdict.INDETERMINATE.value,
        "n_indeterminate": l2_indeterminate,
        "n_split_brain_risks": split_brain,
        "continuity_assessed": not l2_continuity_gaps,
        "continuity_gaps": l2_continuity_gaps,
    }
    if baseline["verdict"] != Verdict.PROVEN.value:
        result["status"] = "baseline_not_proven"
    elif l2_indeterminate or split_brain or l2_continuity_gaps:
        result["status"] = "l2_failover_not_proven"
    elif post["verdict"] == Verdict.PROVEN.value:
        result["verdict"] = Verdict.PROVEN.value
        result["status"] = "preserved"
    elif post["verdict"] == Verdict.REFUTED.value:
        result["verdict"] = Verdict.REFUTED.value
        result["status"] = "failed"
    else:
        result["status"] = "coverage_lost"
    return result, post


def assess_flow(snap: Dict[str, Any], intent: Dict[str, Any], failure: Optional[Dict[str, Any]] = None) -> dict:
    """Return one canonical :data:`TRAFFIC_ASSURANCE_SCHEMA` result.

    The function is total on malformed external input, performs no I/O, never mutates the snapshot, and returns
    native engine evidence rather than reducing uncertainty to a green/red headline.
    """
    normalized, errors, unsupported = _normalize_intent(intent)
    snapshot_errors, snapshot_unsupported = _snapshot_intent_constraints(_as_dict(snap), normalized)
    errors = list(dict.fromkeys(errors + snapshot_errors))
    unsupported = sorted(set(unsupported) | set(snapshot_unsupported))
    if errors:
        return _finalize_result(_invalid_result(normalized, errors, unsupported))
    core = _assess_core(_as_dict(snap), normalized, unsupported)
    failure_result, _post = _failure_assurance(_as_dict(snap), normalized, failure, core, unsupported)
    verdict, reasons = core["verdict"], list(core["verdict_reasons"])
    if unsupported:
        verdict = Verdict.INDETERMINATE.value
        reasons = ["requested semantics fall outside traffic_assurance/1: " + ", ".join(unsupported)]
    if failure_result["requested"] and verdict == Verdict.PROVEN.value:
        if failure_result["verdict"] == Verdict.REFUTED.value:
            verdict = Verdict.REFUTED.value
            reasons = ["the requested synthetic failure refutes the baseline assurance"]
        elif failure_result["verdict"] != Verdict.PROVEN.value:
            verdict = Verdict.INDETERMINATE.value
            reasons = ["the requested synthetic failure is invalid, unmatched, or loses assurance coverage"]

    flow_id = normalized["id"]
    flow_token = _id_token(flow_id)
    limitations = list(_BASE_LIMITATIONS)
    if unsupported:
        limitations.append("unsupported requested semantics: " + ", ".join(unsupported))
    if not core["exact_l4_evaluated"]:
        limitations.append("stateless ACL policy was not evaluated because an exact supported five-tuple was not declared")
    selected_path_claim, directions = _required_verdict(normalized, core["path"])
    observed_ecmp_claim, _ecmp_directions = _required_verdict(normalized, core["ecmp"])
    observed_path_claim = _conjunctive_verdict(selected_path_claim, observed_ecmp_claim)
    observed_policy_claim, _policy_directions = _required_verdict(normalized, core["policy"])
    if normalized["expected"] == "deny":
        path_claim = (
            Verdict.PROVEN.value
            if selected_path_claim == Verdict.REFUTED.value and observed_ecmp_claim == Verdict.PROVEN.value
            else Verdict.INDETERMINATE.value
        )
    else:
        path_claim = observed_path_claim
    policy_claim = _requested_claim_verdict(normalized["expected"], observed_policy_claim, "policy")
    applicability = "unsupported_request" if unsupported else "applicable"
    if unsupported:
        path_claim = policy_claim = Verdict.INDETERMINATE.value
    projection_boundaries = {}
    for direction in directions:
        hops = [hop for hop in _as_list(core["path"][direction].get("hops")) if isinstance(hop, dict)]
        projection_boundaries[direction] = {
            "first_collected_l3_owner": _text(hops[0].get("host")) if hops else None,
            "last_collected_l3_owner": _text(hops[-1].get("host")) if hops else None,
            "endpoint_attachment": "not_assessed",
            "l2_delivery": "not_assessed",
        }
    claims = [
        {"id": f"{flow_id}.path", "subject": flow_id,
         "predicate": "selected_rib_forwarding_projection",
         "verdict": path_claim, "observed_verdict": observed_path_claim,
         "selected_path_observed_verdict": selected_path_claim,
         "ecmp_observed_verdict": observed_ecmp_claim,
         "basis": "fib.trace_bidirectional", "directions": directions,
         "projection_boundaries": projection_boundaries,
         "endpoint_delivery_assessed": False,
         "applicability": applicability},
        {"id": f"{flow_id}.policy", "subject": flow_id, "predicate": "stateless_acl_assurance",
         "verdict": policy_claim, "observed_verdict": observed_policy_claim,
         "basis": "aclcheck.search_filters", "directions": directions,
         "applicability": applicability},
        {"id": f"{flow_id}.overall", "subject": flow_id, "predicate": "declared_scope_assurance",
         "verdict": verdict, "basis": TRAFFIC_ASSURANCE_OWNER},
    ]
    if failure_result["requested"]:
        for claim in claims[:2]:
            claim["scenario_scope"] = "baseline_plus_requested_failure"
            claim["baseline_verdict"] = claim["verdict"]
            if failure_result["verdict"] != Verdict.PROVEN.value:
                claim["verdict"] = Verdict.INDETERMINATE.value
                claim["applicability"] = "requested_failure_not_proven"
        claims.append({
            "id": f"{flow_id}.failure", "subject": flow_id,
            "predicate": "requested_failure_assurance", "verdict": failure_result["verdict"],
            "basis": "cisco_toolkit.cutover_sim.apply_cutover_step",
            "applicability": "applicable" if failure_result["requested"] else "not_requested",
        })
    return _finalize_result({
        "schema": TRAFFIC_ASSURANCE_SCHEMA,
        "owner": TRAFFIC_ASSURANCE_OWNER,
        "intent": normalized,
        "valid": True,
        "validation_errors": [],
        "supported": not unsupported,
        "unsupported_semantics": unsupported,
        "custody_trust": _custody_trust(_as_dict(snap)),
        "verdict": verdict,
        "verdict_reasons": reasons,
        "dimensions": {k: core[k] for k in ("path", "policy", "mtu", "ecmp")},
        "failure": failure_result,
        "claims": claims,
        "nrfu_test_ids": [f"NRFU-{flow_token}-FORWARD"] + (
            [f"NRFU-{flow_token}-RETURN"] if normalized["return_required"] else []),
        "sources": [
            "routes", "interfaces", "acls", "object_groups", "nat", "stp_roots", "fhrp_detail",
            "traffic_evidence_custody",
        ],
        "limitations": limitations,
    })


def assess_flows(snap: Dict[str, Any], intents: Iterable[Any]) -> dict:
    """Assess a finite intent list without dropping malformed or duplicate records."""
    if intents is None:
        rows = []
    elif isinstance(intents, dict) or isinstance(intents, (str, bytes)):
        rows = [intents]
    else:
        try:
            rows = list(intents)
        except TypeError:
            rows = [intents]
    ids = [_text(row.get("id")) for row in rows if isinstance(row, dict) and _text(row.get("id"))]
    duplicates = {item for item, count in Counter(ids).items() if count > 1}
    results = []
    for row in rows:
        # ``failure`` belongs to the set envelope, not the five-tuple intent.  Consume it exactly once
        # here so every downstream surface receives the same producer-owned result rather than rerunning
        # the synthetic mutation.  Unknown row extensions remain inside assess_flow's strict input
        # normalization boundary and are never echoed into the result.
        failure = row.get("failure") if isinstance(row, dict) else None
        result = assess_flow(snap, row, failure=failure)
        explicit_id = _text(row.get("id")) if isinstance(row, dict) else ""
        if not explicit_id:
            result = _invalid_result(
                result["intent"], ["id is required in a traffic assurance set"],
                result.get("unsupported_semantics") or [])
        elif result["intent"]["id"] in duplicates:
            result = _invalid_result(
                result["intent"], [f"duplicate traffic-assurance id {result['intent']['id']!r}"],
                result.get("unsupported_semantics") or [])
        results.append(result)
    summary = {key: 0 for key in (
        Verdict.PROVEN.value, Verdict.REFUTED.value, Verdict.NOT_OBSERVED.value, Verdict.INDETERMINATE.value)}
    for result in results:
        summary[result["verdict"]] = summary.get(result["verdict"], 0) + 1
    summary["invalid"] = sum(1 for result in results if not result["valid"])
    summary["n"] = len(results)
    return {"schema": TRAFFIC_ASSURANCE_SET_SCHEMA, "owner": TRAFFIC_ASSURANCE_OWNER,
            "results": results, "summary": summary}
