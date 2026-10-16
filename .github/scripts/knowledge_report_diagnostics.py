"""Nonpromoting, content-free observation of the exact RC7 report auditor.

Called only by the hosted handoff after its decisive, unchanged audit failed.
This probe neither changes auditor source/constants nor authorizes an export.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import stat
import sys
import types

SCHEMA = "atlas-knowledge-report-diagnostic/1"
AUDITOR_SHA256 = "29eb9bc5ee065647a80d3b56ae2c6cd8fb957d2a0b3c825f468b6ec0f6c2ae67"
AUDITOR_SOURCE_MAX_BYTES = 128 * 1024
BOUND_NAMES = ("MAX_GRAPH_BYTES", "MAX_JSON_VALUES", "MAX_JSON_DEPTH",
               "MAX_JSON_STRING_CHARS", "MAX_JSON_NUMBER_BYTES", "MAX_REPORT_LINES")
# Exact _fail call sites in AUDITOR_SHA256, including the shared lexical scanner.
# This is observation metadata: no auditor source, predicates or bounds are changed.
GRAPH_REFUSAL_SITES = {
    ("_object_no_duplicates", 220): "json_duplicate_object_key",
    ("count_value", 248): "json_lexical_value_or_depth_limit",
    ("_preflight_json_bytes", 266): "json_container_close_mismatch",
    ("_preflight_json_bytes", 280): "json_string_control_character",
    ("_preflight_json_bytes", 284): "json_string_escape_truncated",
    ("_preflight_json_bytes", 290): "json_unicode_escape_invalid",
    ("_preflight_json_bytes", 295): "json_string_escape_invalid",
    ("_preflight_json_bytes", 299): "json_string_token_limit_during_scan",
    ("_preflight_json_bytes", 301): "json_string_unterminated",
    ("_preflight_json_bytes", 303): "json_string_token_limit_after_scan",
    ("_preflight_json_bytes", 311): "json_number_minus_truncated",
    ("_preflight_json_bytes", 315): "json_number_leading_zero",
    ("_preflight_json_bytes", 321): "json_number_integer_invalid",
    ("_preflight_json_bytes", 325): "json_number_fraction_invalid",
    ("_preflight_json_bytes", 333): "json_number_exponent_invalid",
    ("_preflight_json_bytes", 337): "json_number_token_limit",
    ("_preflight_json_bytes", 339): "json_number_delimiter_invalid",
    ("_preflight_json_bytes", 347): "json_literal_delimiter_invalid",
    ("_preflight_json_bytes", 352): "json_token_unrecognized",
    ("_preflight_json_bytes", 354): "json_document_incomplete_or_empty",
    ("_validate_json_bounds", 364): "json_decoded_value_or_depth_limit",
    ("_validate_json_bounds", 367): "json_decoded_object_capacity",
    ("_validate_json_bounds", 370): "json_decoded_object_key_invalid",
    ("_validate_json_bounds", 374): "json_decoded_array_capacity",
    ("_validate_json_bounds", 378): "json_decoded_string_limit",
    ("_validate_json_bounds", 383): "json_decoded_integer_limit",
    ("_validate_json_bounds", 386): "json_decoded_float_not_finite",
    ("_validate_json_bounds", 388): "json_decoded_type_invalid",
    ("<lambda>", 398): "json_nonstandard_constant",
    ("_parse_graph", 403): "json_decode_or_resource_failure",
    ("_parse_graph", 406): "json_root_not_object",
    ("_identifier", 412): "graph_identifier_invalid",
    ("_community_id", 418): "graph_community_id_invalid",
    ("_is_file_node", 436): "graph_node_label_type_invalid",
    ("_is_file_node", 441): "graph_source_file_type_invalid",
    ("partition_graph", 452): "graph_min_community_size_invalid",
    ("partition_graph", 454): "graph_directed_or_multigraph_flags_invalid",
    ("partition_graph", 458): "graph_nodes_or_links_type_invalid",
    ("partition_graph", 460): "graph_node_or_link_count_limit",
    ("partition_graph", 471): "graph_node_type_invalid",
    ("partition_graph", 474): "graph_duplicate_node_id",
    ("partition_graph", 488): "graph_link_type_invalid",
    ("partition_graph", 492): "graph_edge_endpoint_missing",
    ("partition_graph", 495): "graph_duplicate_edge",
    ("partition_graph", 513): "graph_partition_invariant_invalid",
}


def refusal_sub_reason(function, line, code, counters, auditor):
    if code != "graph_report_graph_invalid":
        return "non_graph_refusal"
    reason = GRAPH_REFUSAL_SITES.get((function, line), "unmapped_graph_refusal")
    # Disambiguate the two OR predicates using only their observed integer counts.
    for family, value_key, depth_key in (("lexical", "values", "container_depth"),
                                        ("decoded", "seen", "depth")):
        if reason == f"json_{family}_value_or_depth_limit":
            if counters.get(value_key, -1) > auditor.MAX_JSON_VALUES:
                return f"json_{family}_value_limit"
            if counters.get(depth_key, -1) > auditor.MAX_JSON_DEPTH:
                return f"json_{family}_depth_limit"
    return reason


class ProbeUnavailable(Exception):
    """A fixed refusal code, never source content or an audit waiver."""


def load_auditor(path):
    path = Path(path).absolute()
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise ProbeUnavailable("auditor_not_regular")
    with path.open("rb") as handle:
        raw = handle.read(AUDITOR_SOURCE_MAX_BYTES + 1)
    if len(raw) > AUDITOR_SOURCE_MAX_BYTES or hashlib.sha256(raw).hexdigest() != AUDITOR_SHA256:
        raise ProbeUnavailable("auditor_revision_mismatch")
    module = types.ModuleType("atlas_pinned_graph_report_audit")
    module.__file__ = str(path)
    sys.modules[module.__name__] = module
    # Execute the verified bytes, not a second filesystem read or cached bytecode.
    exec(compile(raw, str(path), "exec"), module.__dict__)
    return module


def observe(auditor, graph_path, report_path):
    first_refusal, probe_graph = {}, {}

    def trace_calls(frame, event, _argument):
        if event != "call" or frame.f_code.co_filename != auditor.__file__:
            return None
        frame.f_trace_lines = False
        frame.f_trace_opcodes = False
        if frame.f_code.co_name == "_parse_graph":
            payload = frame.f_locals.get("payload")
            if type(payload) is bytes and len(payload) <= auditor.MAX_GRAPH_BYTES:
                probe_graph.update(bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest())
        if frame.f_code.co_name == "_fail" and not first_refusal:
            caller = frame.f_back
            code = frame.f_locals.get("code")
            if caller is not None and caller.f_code.co_filename == auditor.__file__:
                name = caller.f_code.co_name
                first_refusal.update(
                    function=name if re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]{0,63}", name) else "expression",
                    line=caller.f_lineno,
                    code=code if isinstance(code, str) and re.fullmatch(r"graph_report_[a-z_]{1,96}", code)
                    else "unclassified_refusal",
                )
                counters = {key: caller.f_locals[key] for key in ("values", "seen", "depth")
                            if type(caller.f_locals.get(key)) is int
                            and 0 <= caller.f_locals[key] <= (1 << 53) - 1}
                if name == "count_value" and type(caller.f_locals.get("stack")) is list:
                    counters["container_depth"] = len(caller.f_locals["stack"]) + 1
                first_refusal["counters"] = counters
                first_refusal["sub_reason"] = refusal_sub_reason(name, caller.f_lineno, code, counters, auditor)
        return None  # Calls only; never trace the scanner's millions of line/opcode events.

    previous = sys.gettrace()
    try:
        sys.settrace(trace_calls)
        result = auditor.audit_graph_report(graph_path, report_path)
    finally:
        sys.settrace(previous)
    return {"schema": SCHEMA, "status": "observed_block" if result.status == "block" else "not_reproduced",
            "auditor_sha256": AUDITOR_SHA256, "audit_status": result.status,
            "audit_error_codes": list(result.error_codes), "first_refusal": first_refusal,
            "probe_audited_graph": probe_graph,
            "bounds": {name: getattr(auditor, name) for name in BOUND_NAMES},
            "promotes_export": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--auditor", required=True, type=Path)
    parser.add_argument("graph_json", type=Path)
    parser.add_argument("graph_report", type=Path)
    args = parser.parse_args(argv)
    try:
        result = observe(load_auditor(args.auditor), args.graph_json, args.graph_report)
    except Exception as exc:
        reason = str(exc) if isinstance(exc, ProbeUnavailable) else "probe_failed"
        result = {"schema": SCHEMA, "status": "unavailable", "reason": reason, "promotes_export": False}
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0  # Diagnostic transport only. The parent must retain its original failure.


if __name__ == "__main__":
    raise SystemExit(main())
