"""ONE contract, ONE owner: the engine vocabularies the Atlas Scope compiler validates against.

The owner is ``cisco_toolkit/analyze.py`` (the PUNCH_EVIDENCE_* constants, PUNCH_EVIDENCE_RULES and the
protocol-assessability state vocabulary). ``atlas-scope/contracts/engine-contract.v1.json`` is a GENERATED
projection of those constants for the app -- never hand-edited. This test fails when the committed file
differs from what the constants produce, byte for byte (LF, 2-space indent, trailing newline).

Regenerate deliberately (after reviewing the constant change) with:

    UPDATE_ENGINE_CONTRACT=1 python -m pytest tests/test_engine_contract_projection.py
"""
import json
import os

from cisco_toolkit import analyze

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTRACT = os.path.join(ROOT, *analyze.ENGINE_CONTRACT_PATH.split("/"))
REGENERATE = ("regenerate it from the engine constants with:  "
              "UPDATE_ENGINE_CONTRACT=1 python -m pytest tests/test_engine_contract_projection.py")


def test_committed_projection_is_byte_identical_to_what_the_engine_constants_produce():
    expected = analyze.render_engine_contract().encode("utf-8")
    if os.environ.get("UPDATE_ENGINE_CONTRACT") == "1":
        os.makedirs(os.path.dirname(CONTRACT), exist_ok=True)
        with open(CONTRACT, "wb") as fh:          # binary: the projection is LF on every platform
            fh.write(expected)
    assert os.path.isfile(CONTRACT), f"{analyze.ENGINE_CONTRACT_PATH} is missing -- {REGENERATE}"
    with open(CONTRACT, "rb") as fh:
        actual = fh.read()
    assert actual == expected, (
        f"{analyze.ENGINE_CONTRACT_PATH} has drifted from cisco_toolkit/analyze.py -- {REGENERATE}")


def test_projection_has_exactly_the_agreed_shape_and_mirrors_every_owner_constant():
    """The shape cluster R3's compiler imports: fixed keys, sorted arrays, every value read from its owner
    (a constant added to an owner tuple appears here; nothing is hand-listed in the projection)."""
    doc = json.loads(analyze.render_engine_contract())
    assert list(doc) == ["schema", "owner", "punch_evidence", "protocol_assessability_states"]
    assert doc["schema"] == "atlas-engine-contract/1"
    assert doc["owner"] == "cisco_toolkit/analyze.py"
    pe = doc["punch_evidence"]
    assert list(pe) == ["kinds", "record_kinds", "roles", "bases", "cap", "total_only_when_capped",
                        "absence_forbids_record_kinds", "record_requires_record_kind", "row_requires_ref",
                        "host_must_be_row_device_or_null"]
    assert pe["kinds"] == sorted(analyze.PUNCH_EVIDENCE_REF_KINDS)
    assert pe["record_kinds"] == sorted(analyze.PUNCH_EVIDENCE_RECORD_KINDS)
    assert set(pe["record_kinds"]) <= set(pe["kinds"])
    assert pe["roles"] == sorted(analyze.PUNCH_EVIDENCE_ROLES)
    assert pe["bases"] == sorted(analyze.PUNCH_EVIDENCE_BASES)
    assert pe["cap"] == analyze.PUNCH_EVIDENCE_REFS_CAP == 64
    assert all(pe[rule] is True for rule in analyze.PUNCH_EVIDENCE_RULES)
    assert doc["protocol_assessability_states"] == sorted(analyze.PROTOCOL_ASSESSABILITY_STATES)
    assert "not_running" in doc["protocol_assessability_states"]
    text = analyze.render_engine_contract()
    assert text.endswith("}\n") and "\r" not in text and '\n  "punch_evidence": {\n    "kinds"' in text


def test_published_rules_are_the_rules_the_row_constructor_enforces():
    """The five rule flags are not decoration: drive the ONE row constructor and observe each."""
    where = [("sw1", f"Gi1/0/{i}", None) for i in range(1, 91)]
    l2 = {"addressing": {"dup_ip": [{"ip": "10.1.1.1", "where": where}], "dup_subnet": []}}
    sec = {"a1": {"findings": [{"id": "no-ntp", "status": "fail", "severity": "low", "title": "NTP"}]}}
    rows = analyze.compute_migration_punchlist(
        [{"id": "CL-03", "severity": "High", "title": "t", "detail": "d", "hosts": ["gw1"],
          "evidence_refs": [{"kind": "interface", "host": "other", "ref": "/interfaces/other/Gi1",
                             "role": "subject", "cite": "other Gi1"}]}],
        sec, {}, [], [], [], {}, [], [], l2=l2)
    by_cat = {r["category"]: r for r in rows}
    capped, cl, ntp = by_cat["Addressing"], by_cat["Cross-layer"], by_cat["Security"]
    # total_only_when_capped
    assert len(capped["evidence_refs"]) == analyze.PUNCH_EVIDENCE_REFS_CAP and capped["evidence_refs_total"] == 91
    assert "evidence_refs_total" not in cl and "evidence_refs_total" not in ntp
    # host_must_be_row_device_or_null: the carried ref about 'other' (not a row device) was dropped
    assert all(r["host"] in (None, *cl["devices"]) for r in cl["evidence_refs"])
    assert not any(r["host"] == "other" for r in cl["evidence_refs"])
    # record_requires_record_kind / row_requires_ref / absence_forbids_record_kinds
    for row in rows:
        kinds = {r["kind"] for r in row["evidence_refs"]}
        assert (row["evidence_basis"] == "record") == bool(kinds & analyze.PUNCH_EVIDENCE_RECORD_KINDS) or \
            row["evidence_basis"] == "absence"
        if row["evidence_basis"] == "row":
            assert row["evidence_refs"]
        if row["evidence_basis"] == "absence":
            assert not kinds & analyze.PUNCH_EVIDENCE_RECORD_KINDS


def test_absence_forbids_record_kinds_even_when_a_record_ref_is_offered():
    """R1V-3: the loop above only observes absence rows that were never OFFERED a record ref, so removing the
    constructor's absence filter survived it. Offer one: an absence-basis drift row carrying one ref of EVERY
    record kind (all about a device the row names, so only the absence rule can drop them) plus a witness. The
    record refs are dropped, the witness survives, and the basis stays 'absence' -- a record never turns a
    'this is MISSING' finding into a 'this line says so' finding."""
    offered = [{"kind": kind, "host": "sw1", "ref": f"/offered/{kind}", "role": "subject", "cite": f"sw1 {kind}"}
               for kind in sorted(analyze.PUNCH_EVIDENCE_RECORD_KINDS)]
    witness = {"kind": "absence_witness", "host": "sw1", "ref": "/security/sw1/findings/0", "role": "witness",
               "cite": "sw1 line looked for and not present"}
    drift = [{"severity": "High", "category": "False-health", "devices": ["sw1"], "title": "absent thing",
              "detail": "d", "evidence_basis": "absence", "evidence_refs": [*offered, witness]},
             {"severity": "High", "category": "False-health", "devices": ["sw1"], "title": "present thing",
              "detail": "d", "evidence_refs": list(offered)}]
    rows = {r["title"]: r for r in analyze.compute_migration_punchlist(
        [], {}, {}, [], [], [], {}, [], [], drift=drift)}
    absent, present = rows["absent thing"], rows["present thing"]
    assert absent["evidence_basis"] == "absence"
    assert not {r["kind"] for r in absent["evidence_refs"]} & analyze.PUNCH_EVIDENCE_RECORD_KINDS, absent
    assert any(r["kind"] == "absence_witness" for r in absent["evidence_refs"])
    # control: the SAME offered refs on a non-absence row are kept (so the drop above is the absence rule)
    assert {r["kind"] for r in present["evidence_refs"]} >= set(analyze.PUNCH_EVIDENCE_RECORD_KINDS)
    assert present["evidence_basis"] == "record"


# ---------------------------------------------------------------------------------------------------------
# R1V1-3: `row_requires_ref` is published as a RULE, so it must hold by construction -- not only on the inputs
# the real producers happen to give. Poison the host / port names of every folded section of the committed
# golden (a real pipeline snapshot) so no row-level pointer can be formed, and every non-absence row must
# still name what it was derived from: its row where addressable, else the published SECTION it was folded
# from (cited as exactly that -- never as a row).
# ---------------------------------------------------------------------------------------------------------
_NAME_KEYS = ("switch", "host", "hostname", "port", "interface", "a_port", "b_port", "hosts", "devices")
_POSITIONAL = ("cross_layer", "security", "config_hygiene", "physical_health", "l3_forwarding", "protocol_health",
               "stp_findings", "health_scores", "move_groups")
_KEYWORD = {"drift": "operational_drift", "syslog_intelligence": "syslog_intelligence", "qos_audit": "qos_audit",
            "software_risk": "software_risk", "platform_health": "platform_health",
            "device_dossiers": "device_dossiers", "protocol_assessability": "protocol_assessability"}


def _golden():
    with open(os.path.join(ROOT, "tests", "golden", "snapshot.json"), encoding="utf-8") as fh:
        return json.load(fh)


def _poison_names(node, value):
    if isinstance(node, dict):
        return {k: (value if k in _NAME_KEYS else _poison_names(v, value)) for k, v in node.items()}
    if isinstance(node, list):
        return [_poison_names(v, value) for v in node]
    return node


def _punchlist_with(golden, poisoned=None, value=None):
    args = [golden.get(k) or ({} if k in ("security", "config_hygiene", "stp_findings") else [])
            for k in _POSITIONAL]
    kwargs = {param: golden.get(section) for param, section in _KEYWORD.items()}
    if poisoned in _POSITIONAL:
        args[_POSITIONAL.index(poisoned)] = _poison_names(args[_POSITIONAL.index(poisoned)], value)
    elif poisoned in _KEYWORD:
        kwargs[poisoned] = _poison_names(kwargs[poisoned], value)
    return analyze.compute_migration_punchlist(*args, **kwargs)


def _pointer_resolves(doc, pointer):
    node = doc
    for tok in pointer[1:].split("/"):
        tok = tok.replace("~1", "/").replace("~0", "~")
        if isinstance(node, dict) and tok in node:
            node = node[tok]
        elif isinstance(node, list) and tok.isdigit() and int(tok) < len(node):
            node = node[int(tok)]
        else:
            return False
    return node is not None


def test_row_requires_ref_holds_by_construction_even_when_no_row_is_addressable():
    golden = _golden()
    for value in (7, None, 3.5, ["x"], {"a": 1}, "", "(fleet)"):
        for name in (*_POSITIONAL, *_KEYWORD):
            for row in _punchlist_with(golden, name, value):
                if row["evidence_basis"] == "absence":
                    continue
                assert row["evidence_refs"], (name, repr(value), row["category"], row["title"])
                for ref in row["evidence_refs"]:
                    assert ref["kind"] == "interface" or _pointer_resolves(golden, ref["ref"]), ref


def test_the_section_fallback_names_the_published_section_each_category_folds():
    """Coverage + publication of the one fallback map: every category whose policy allows a non-absence basis
    has a section, and every section is a key a real pipeline run publishes (the committed golden)."""
    golden = _golden()
    needs = {c for c, bases in analyze._PUNCH_EVIDENCE_POLICY.items() if set(bases) - {"absence"}}
    assert needs <= set(analyze._PUNCH_CATEGORY_SECTION), sorted(needs - set(analyze._PUNCH_CATEGORY_SECTION))
    assert set(analyze._PUNCH_CATEGORY_SECTION) <= set(analyze._PUNCH_EVIDENCE_POLICY)
    unpublished = {c: s for c, s in analyze._PUNCH_CATEGORY_SECTION.items() if s not in golden}
    assert not unpublished, unpublished
    # an L1 row whose ports are unaddressable points at physical_health, cited as a section, never as a row
    rows = _punchlist_with(golden, "physical_health", 7)
    (l1,) = [r for r in rows if r["category"] == "L1"][:1]
    assert l1["evidence_basis"] == "row"
    assert [(r["kind"], r["host"], r["ref"], r["role"]) for r in l1["evidence_refs"]] == [
        ("analysis_row", None, "/physical_health", "derived_from")]
    assert "section" in l1["evidence_refs"][0]["cite"] and "no addressable" in l1["evidence_refs"][0]["cite"]
