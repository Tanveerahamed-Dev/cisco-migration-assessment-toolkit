"""Tests for the offline state-assertion check-pack evaluator (roadmap A1 proof spike).

Pins the coverage-honest contract: a committed check-pack is evaluated deterministically over the
snapshot with NO LLM and NO network; an assertion whose subject was never collected returns
NOT_OBSERVED (a blind spot) and is EXCLUDED from the pass/fail denominator -- "not observed" never
silently becomes a pass.
"""
from cisco_toolkit import assertions


SNAP = {
    "executive_brief": {"scale": {"n_devices": 253, "n_vlans": 202}},
    "security_grade": "F",
    "fhrp": [],  # present but empty == collected, nothing of this kind found
    "collection_completeness": {"devices": [{"host": "core1", "status": "not collected"}]},
    # 'vpc' key absent entirely -> a not-collected blind spot
}


def _run(a):
    return assertions.evaluate_assertion(SNAP, a)


def test_comparison_pass():
    r = _run({"id": "dev-count", "title": "fleet >= 200", "subject": "executive_brief.scale.n_devices",
              "all_of": [{"type": "comparison", "op": ">=", "value": 200}]})
    assert r["status"] == assertions.PASS
    assert r["citation"] == "executive_brief.scale.n_devices"


def test_contains_fail_is_not_silent():
    r = _run({"id": "grade-a", "title": "grade is A", "subject": "security_grade",
              "all_of": [{"type": "contains", "value": "A"}]})
    assert r["status"] == assertions.FAIL  # 'F' does not contain 'A'


def test_absent_subject_is_not_observed():
    r = _run({"id": "vpc", "title": "vPC present", "subject": "vpc",
              "all_of": [{"type": "contains", "value": "up"}]})
    assert r["status"] == assertions.NOT_OBSERVED
    assert r["abstention"] == "not_collected"


def test_collected_but_empty_fails_not_passes():
    # 'not observed never becomes healthy': an empty FHRP block must FAIL a 'must contain hsrp'
    # assertion (an observed negative), NOT pass and NOT abstain.
    r = _run({"id": "fhrp", "title": "FHRP configured", "subject": "fhrp",
              "all_of": [{"type": "contains", "value": "hsrp"}]})
    assert r["status"] == assertions.FAIL


def test_device_scoped_uncollected_is_not_observed():
    # The fleet value is published, but the assertion is scoped to a device that was never collected.
    r = _run({"id": "core1", "title": "core1 fact", "subject": "executive_brief.scale.n_devices",
              "device": "core1", "all_of": [{"type": "comparison", "op": ">=", "value": 1}]})
    assert r["status"] == assertions.NOT_OBSERVED


def test_any_of_semantics():
    r = _run({"id": "any", "title": "any-of", "subject": "security_grade",
              "any_of": [{"type": "contains", "value": "A"}, {"type": "contains", "value": "F"}]})
    assert r["status"] == assertions.PASS


def test_not_regex_and_ignorecase():
    r = _run({"id": "nr", "title": "no telnet", "subject": "security_grade",
              "all_of": [{"type": "not_regex", "value": "^a$", "ignorecase": True}]})
    assert r["status"] == assertions.PASS  # 'F' !~ /^a$/i


def test_pack_summary_excludes_not_observed_from_denominator():
    pack = {"assertions": [
        {"id": "a", "title": "x", "subject": "executive_brief.scale.n_devices",
         "all_of": [{"type": "comparison", "op": ">=", "value": 200}]},                 # pass
        {"id": "b", "title": "y", "subject": "security_grade",
         "all_of": [{"type": "contains", "value": "A"}]},                               # fail
        {"id": "c", "title": "z", "subject": "vpc",
         "all_of": [{"type": "contains", "value": "up"}]},                              # not_observed
    ]}
    out = assertions.evaluate_pack(SNAP, pack)
    s = out["summary"]
    assert s["n_pass"] == 1
    assert s["n_fail"] == 1
    assert s["n_not_observed"] == 1
    assert s["n_assessed"] == 2          # NOT_OBSERVED excluded -> coverage-honest denominator
    assert s["grade"] == "fail"          # any fail -> fail
    assert len(out["results"]) == 3


# --- v2 (AUTO-1): two-operand extract-and-compare + the % utilization operator -------------------

def test_ratio_percent_operator_pass_and_fail():
    snap = {"cap": "interface load: 170 used of 200 total"}
    a = {"id": "util", "title": "port util <= 90%", "subject": "cap",
         "all_of": [{"type": "ratio", "numerator": r"(\d+) used", "denominator": r"(\d+) total",
                     "op": "<=", "value": 90}]}
    assert assertions.evaluate_assertion(snap, a)["status"] == assertions.PASS   # 100*170/200 = 85 <= 90
    a["all_of"][0]["value"] = 80
    assert assertions.evaluate_assertion(snap, a)["status"] == assertions.FAIL   # 85 <= 80 is false


def test_ratio_zero_denominator_abstains_not_passes():
    snap = {"cap": "0 used of 0 total"}
    a = {"id": "u", "title": "u", "subject": "cap",
         "all_of": [{"type": "ratio", "numerator": r"(\d+) used", "denominator": r"(\d+) total",
                     "op": "<=", "value": 90}]}
    assert assertions.evaluate_assertion(snap, a)["status"] == assertions.NOT_OBSERVED  # den 0 -> abstain


def test_contains1_exactly_once():
    a = {"id": "c1", "title": "exactly one ssh", "subject": "v", "all_of": [{"type": "contains1", "value": "ssh"}]}
    assert assertions.evaluate_assertion({"v": "transport input ssh"}, a)["status"] == assertions.PASS
    assert assertions.evaluate_assertion({"v": "transport input ssh telnet ssh"}, a)["status"] == assertions.FAIL


# --- H2: per-OBJECT for_each grammar (model -> rows + per-field predicates + uniqueness) -----------

FOR_EACH_ROWS = [
    {"host": "sw1", "ifname": "Gi1", "mtu": 1500},
    {"host": "sw2", "ifname": "Gi1", "mtu": 9000},
    {"host": "sw3", "ifname": "Gi1"},                 # mtu not collected -> NOT_OBSERVED, never a silent pass
]


def test_for_each_per_field_predicate():
    out = assertions.evaluate_for_each(FOR_EACH_ROWS, {"id": "mtu", "field_rules": [{"field": "mtu", "op": "max", "value": 1500}]})
    by = {r["key"]: r for r in out["rows"]}
    assert by["sw1::Gi1"]["status"] == assertions.PASS      # 1500 <= 1500
    assert by["sw2::Gi1"]["status"] == assertions.FAIL      # 9000 > 1500
    assert by["sw3::Gi1"]["status"] == assertions.NOT_OBSERVED   # mtu missing -> abstain
    assert out["summary"]["n_pass"] == 1 and out["summary"]["n_fail"] == 1 and out["summary"]["n_not_observed"] == 1


def test_for_each_required_and_prohibited():
    rows = [{"host": "a", "x": "y"}, {"host": "b"}]
    req = assertions.evaluate_for_each(rows, {"id": "r", "field_rules": [{"field": "x", "op": "required"}]})
    assert [r["status"] for r in req["rows"]] == [assertions.PASS, assertions.FAIL]


def test_for_each_uniqueness():
    rows = [{"host": "a", "ip": "10.0.0.1"}, {"host": "b", "ip": "10.0.0.1"}, {"host": "c", "ip": "10.0.0.2"}]
    out = assertions.evaluate_for_each(rows, {"id": "u", "unique_by": "ip"})
    viol = out["uniqueness_violations"]
    assert len(viol) == 1 and viol[0]["value"] == "10.0.0.1" and sorted(viol[0]["keys"]) == ["a#0", "b#1"]


# --- review-wave-1 regression tests --------------------------------------------------------------

def test_unknown_rule_type_abstains_and_does_not_abort_pack():
    out = assertions.evaluate_pack({"a": 253, "x": "hello"}, {"assertions": [
        {"id": "good", "subject": "a", "all_of": [{"type": "comparison", "op": ">=", "value": 1}]},
        {"id": "typo", "subject": "x", "all_of": [{"type": "contain", "value": "z"}]}]})   # 'contain' is a typo
    by = {r["id"]: r for r in out["results"]}
    assert by["good"]["status"] == assertions.PASS              # the good assertion still produced its verdict
    assert by["typo"]["status"] == assertions.NOT_OBSERVED      # unknown type -> abstain (was: ValueError aborts the pack)


def test_invalid_regex_abstains_not_raises():
    r = assertions.evaluate_assertion({"x": "hello"}, {"id": "b", "subject": "x", "all_of": [{"type": "regex", "value": "*bad"}]})
    assert r["status"] == assertions.NOT_OBSERVED
    r2 = assertions.evaluate_assertion({"x": "hello"}, {"id": "b2", "subject": "x", "all_of": [{"type": "not_regex", "value": "(unterminated"}]})
    assert r2["status"] == assertions.NOT_OBSERVED              # a bad not_regex must abstain, never a fabricated pass


def test_ratio_negative_denominator_abstains():
    r = assertions.evaluate_assertion({"v": "u 150 d -100"}, {"id": "r", "subject": "v",
        "all_of": [{"type": "ratio", "numerator": r"u (-?\d+)", "denominator": r"d (-?\d+)", "op": "<=", "value": 90}]})
    assert r["status"] == assertions.NOT_OBSERVED              # was: pass (100*150/-100 = -150 <= 90)


def test_subjectless_assertion_abstains_not_vacuous_pass():
    r = assertions.evaluate_assertion({}, {"id": "u", "all_of": [{"type": "contains", "value": "telnet"}]})
    assert r["status"] == assertions.NOT_OBSERVED and r["citation"] is None
    r2 = assertions.evaluate_assertion({}, {"id": "u2", "all_of": [{"type": "not_contains", "value": "telnet"}]})
    assert r2["status"] == assertions.NOT_OBSERVED            # was: a vacuous PASS against the empty string


# --- review-wave-2 regression tests (for_each + numeric coercion) ---------------------------------

def test_as_number_only_coerces_clean_tokens():
    assert assertions._as_number("253") == 253.0
    assert assertions._as_number("1.5e3") == 1500.0
    assert assertions._as_number("GigabitEthernet0/1 is up, 5 input errors") is None   # ambiguous -> abstain
    assert assertions._as_number("100/1000") is None


def test_comparison_on_messy_multinumber_string_abstains():
    r = assertions.evaluate_assertion({"iface": "GigabitEthernet0/1 is up, 5 input errors, 0 CRC"},
        {"id": "e", "subject": "iface", "all_of": [{"type": "comparison", "op": "<=", "value": 0}]})
    assert r["status"] == assertions.NOT_OBSERVED            # was: PASS (read the leading 0 of 0/1, not the 5 errors)


def test_for_each_eq_compares_numerically():
    out = assertions.evaluate_for_each([{"host": "sw1", "ifname": "Gi1", "mtu": 1500.0}],
        {"field_rules": [{"field": "mtu", "op": "eq", "value": 1500}]})
    assert out["rows"][0]["status"] == assertions.PASS       # 1500.0 == 1500 (was: FAIL on '1500.0' != '1500')


def test_for_each_keys_never_collide():
    rows = [{"host": "CS01", "vlan": 100, "mtu": 9216}, {"host": "CS01", "vlan": 200, "mtu": 1500}, {"host": "CS01", "vlan": 300, "mtu": 9216}]
    out = assertions.evaluate_for_each(rows, {"field_rules": [{"field": "mtu", "op": "max", "value": 1500}]})
    assert len({r["key"] for r in out["rows"]}) == 3          # was: all keyed 'CS01' -> 2 verdicts vanished
    assert out["summary"]["n_fail"] == 2


def test_for_each_nonnumeric_minmax_fails_ambiguous_abstains():
    fail = assertions.evaluate_for_each([{"host": "h", "mtu": "unknown"}], {"field_rules": [{"field": "mtu", "op": "min", "value": 1500}]})
    assert fail["rows"][0]["status"] == assertions.FAIL      # collected non-numeric -> observed negative
    amb = assertions.evaluate_for_each([{"host": "h", "mtu": "100/1000"}], {"field_rules": [{"field": "mtu", "op": "min", "value": 1500}]})
    assert amb["rows"][0]["status"] == assertions.NOT_OBSERVED   # ambiguous multi-number -> abstain


def test_for_each_bad_regex_abstains_not_raises():
    out = assertions.evaluate_for_each([{"host": "a", "x": "hi"}], {"field_rules": [{"field": "x", "op": "regex", "value": "["}]})
    assert out["rows"][0]["status"] == assertions.NOT_OBSERVED


def test_for_each_unique_by_observed_rows_disclosed():
    out = assertions.evaluate_for_each([{"host": "a"}, {"host": "b"}], {"unique_by": "ip"})
    assert out["summary"]["unique_by_observed_rows"] == 0    # 0 rows carried 'ip' -> not 'verified unique'
