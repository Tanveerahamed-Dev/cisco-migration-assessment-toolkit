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
               "MAX_JSON_STRING_CHARS", "MAX_JSON_NUMBER_BYTES")


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
