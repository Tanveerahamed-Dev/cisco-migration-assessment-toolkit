"""Plan-A #3: the Verdict ADT -- abstention as a TYPE, not a per-module string convention.

Pins the str-mixin serialization that makes a Verdict-typed field golden-safe (it equals the
hand-written string it replaces), the aclcheck reason -> Verdict mapping, and the additive
`verdict` field now on every aclcheck finding (DERIVED from the reason, never drifting)."""
import dataclasses
import json

import pytest

from cisco_toolkit import aclcheck
from cisco_toolkit.model import Judgment, Verdict

ANY = {"ip": "0.0.0.0", "wild": "255.255.255.255"}


def _net(ip, wild):
    return {"ip": ip, "wild": wild}


def _rule(action, proto="ip", src=None, dst=None, dport=None):
    return {"action": action, "proto": proto, "src": src or ANY, "dst": dst or ANY,
            "sport": None, "dport": dport, "raw": f"{action} {proto}"}


def test_verdict_serializes_as_a_bare_string():
    """str-mixin: json-serializes to the plain value, so a Verdict field is byte-identical to
    the hand-written string it replaces -- what makes wiring it into the snapshot purely additive."""
    assert Verdict.PROVEN.value == "proven" and Verdict.NOT_OBSERVED.value == "not_observed"
    assert json.dumps({"v": Verdict.REFUTED}) == '{"v": "refuted"}'
    assert Verdict("indeterminate") is Verdict.INDETERMINATE          # round-trips from the string


def test_from_acl_reason_mapping():
    assert Verdict.from_acl_reason("BLOCKING_LINES") is Verdict.REFUTED
    assert Verdict.from_acl_reason("INDEPENDENTLY_UNMATCHABLE") is Verdict.REFUTED
    assert Verdict.from_acl_reason("INDETERMINATE") is Verdict.INDETERMINATE
    assert Verdict.from_acl_reason("UNDEFINED_REFERENCE") is Verdict.INDETERMINATE
    assert Verdict.from_acl_reason("CYCLICAL_REFERENCE") is Verdict.INDETERMINATE
    assert Verdict.from_acl_reason("") is Verdict.INDETERMINATE       # unknown -> cannot decide


def test_aclcheck_findings_carry_a_derived_verdict():
    """Every finding gains a `verdict` == from_acl_reason(reason) while the original reason is
    untouched (additive). A provably-dead (BLOCKING_LINES) line is REFUTED."""
    rules = [
        _rule("deny", "ip", ANY, _net("10.1.1.0", "0.0.0.255")),
        _rule("permit", "tcp", ANY, _net("10.1.1.0", "0.0.0.255"), dport={"op": "eq", "val": 22}),
    ]
    findings = aclcheck.analyze_acl(rules)
    assert findings, "expected at least one shadow finding"
    verdicts = {v.value for v in Verdict}
    for f in findings:
        assert "reason" in f and "verdict" in f
        assert f["verdict"] in verdicts
        assert f["verdict"] == Verdict.from_acl_reason(f["reason"]).value   # derived, not drifting
    shadowed = next(f for f in findings if f["reason"] == "BLOCKING_LINES")
    assert shadowed["verdict"] == Verdict.REFUTED.value


def test_judgment_is_a_frozen_evidence_payload():
    j = Judgment(Verdict.REFUTED, reason="BLOCKING_LINES", citation="acl_line_reachability")
    assert j.verdict is Verdict.REFUTED and j.reason == "BLOCKING_LINES"
    with pytest.raises(dataclasses.FrozenInstanceError):
        j.reason = "x"                                               # frozen -> immutable
