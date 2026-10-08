"""G43 -- the ``vocab`` block: the engine-owned display rank and severity class of every closed vocabulary.

The set of vocabularies is derived from the schema itself (every string enum it publishes), never from a
hand list, so a vocabulary added to the schema fails these tests until it is classified. Every rank that an
engine owner fixes is held against that owner -- its private rank table, or the function-local literal the
owner folds with, read by AST -- and every absence token is held to ``undetermined``.
"""
from __future__ import annotations

import ast
import copy
import inspect
import textwrap

import pytest
from jsonschema import Draft202012Validator

from cisco_toolkit import analyze, coverage_matrix, ssot
from cisco_toolkit import parse as parse_mod
from cisco_toolkit import ui_projection as uip
from test_ui_projection_inventory import _minimal, _roster_hosts, _sample

UND = "undetermined"


@pytest.fixture(scope="module")
def schema():
    return uip.ui_projection_schema()


@pytest.fixture(scope="module")
def vocab():
    return uip.project(_minimal())["vocab"]


def _walk_enums(node, path, found):
    """Every string enum in a schema tree, as (path, tuple(enum)); an integer enum is not a token vocabulary."""
    if isinstance(node, dict):
        if node.get("type") == "string" and isinstance(node.get("enum"), list):
            found.append((path, tuple(node["enum"])))
        for key, child in node.items():
            _walk_enums(child, f"{path}/{key}", found)
    elif isinstance(node, list):
        for index, child in enumerate(node):
            _walk_enums(child, f"{path}/{index}", found)


def _refs(node, out):
    if isinstance(node, dict):
        if "$ref" in node:
            out.append(node["$ref"].removeprefix("#/$defs/"))
        for child in node.values():
            _refs(child, out)
    elif isinstance(node, list):
        for child in node:
            _refs(child, out)
    return out


def _vocab_closure(schema):
    """The definitions the vocab block itself introduces: everything reachable from the root's ``vocab``."""
    pending = [schema["properties"]["vocab"]["$ref"].removeprefix("#/$defs/")]
    seen = set()
    while pending:
        name = pending.pop()
        if name not in seen:
            seen.add(name)
            pending.extend(_refs(schema["$defs"][name], []))
    return seen


def _published_enums(schema):
    """Every string enum the payload publishes outside the vocab block (root and every other definition)."""
    closure = _vocab_closure(schema)
    found = []
    _walk_enums({k: v for k, v in schema.items() if k != "$defs"}, "", found)
    for name, definition in schema["$defs"].items():
        if name not in closure:
            _walk_enums(definition, f"/$defs/{name}", found)
    return found


def _ranks(vocab, name):
    return {item["token"]: item["rank"] for item in vocab["ranked"][name]["items"]}


def _classes(vocab, name):
    return {item["token"]: item["class"] for item in vocab["ranked"][name]["items"]}


def _function_ast(fn):
    return ast.parse(textwrap.dedent(inspect.getsource(fn)))


def _local_dict_literals(fn, target):
    """Every ``target = {...}`` literal assigned inside ``fn`` (nested scopes included), as a plain dict."""
    out = []
    for node in ast.walk(_function_ast(fn)):
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == target for t in node.targets):
            assert isinstance(node.value, ast.Dict), ast.dump(node)[:160]
            out.append({key.value: value.value for key, value in zip(node.value.keys, node.value.values)})
    return out


# --------------------------------------------------------------------------------------------------
# V1 -- the vocabulary set is the schema's own: every string enum is classified exactly once
# --------------------------------------------------------------------------------------------------
def test_v1_every_string_enum_the_schema_publishes_is_classified_exactly_once(schema, vocab):
    found = _published_enums(schema)
    assert len(found) > 40                                     # the walk really swept the schema
    closure = _vocab_closure(schema)
    assert {"Vocab", "VocabClass", "VocabRanked", "VocabUnranked"} <= closure
    assert all(name.startswith("Vocab") for name in closure), closure
    published = {}
    for name, entry in vocab["ranked"].items():
        published.setdefault(frozenset(item["token"] for item in entry["items"]), []).append(name)
    for name, entry in vocab["unranked"].items():
        published.setdefault(frozenset(entry["tokens"]), []).append(name)
    doubled = {tuple(names) for names in published.values() if len(names) != 1}
    assert not doubled, doubled                                # one token set, one classification
    schema_sets = {}
    for path, enum in found:
        schema_sets.setdefault(frozenset(enum), []).append(path)
    unclassified = {tuple(paths) for tokens, paths in schema_sets.items() if tokens not in published}
    assert not unclassified, unclassified
    invented = {names[0] for tokens, names in published.items() if tokens not in schema_sets}
    assert not invented, invented
    assert set(vocab["ranked"]).isdisjoint(vocab["unranked"])
    assert set(vocab) == {"schema", "classes", "ranked", "unranked"}
    assert vocab["schema"] == uip.VOCAB_SCHEMA == "ui_projection_vocab/1"
    assert vocab["classes"] == list(uip.VOCAB_CLASSES) == ["pass", "watch", "risk", "critical", "undetermined"]
    # the one integer enum (an address family) is a number, not a token vocabulary, and is not swept
    assert schema["$defs"]["AddressFamilyFact"]["oneOf"][0]["properties"]["value"] == {"type": "integer",
                                                                                      "enum": [4, 6]}


# --------------------------------------------------------------------------------------------------
# V2 -- each token list is its vocabulary, in rank order, with a closed item schema of its own
# --------------------------------------------------------------------------------------------------
def test_v2_ranked_items_are_the_vocabulary_in_rank_order_under_their_own_item_schema(schema, vocab):
    d = schema["$defs"]
    schema_enums = {enum for _path, enum in _published_enums(schema)}
    specs = {spec[0]: spec for spec in uip._VOCAB_RANKED}
    assert set(vocab["ranked"]) == set(specs)
    for name, entry in vocab["ranked"].items():
        assert set(entry) == {"owner", "basis", "items"} and entry["owner"] and entry["basis"]
        tokens = specs[name][1]
        assert tokens in schema_enums, name                   # the schema publishes exactly this enum, this order
        item = d[uip._vocab_title(name) + "Item"]
        assert item["additionalProperties"] is False and item["required"] == ["token", "rank", "class"]
        assert item["properties"]["token"] == {"type": "string", "enum": list(tokens)}
        assert item["properties"]["class"] == {"$ref": "#/$defs/VocabClass"}
        listed = [i["token"] for i in entry["items"]]
        assert sorted(listed) == sorted(tokens) and len(set(listed)) == len(tokens), name
        ranks = [i["rank"] for i in entry["items"]]
        assert ranks == sorted(ranks) and ranks[0] == 0 and set(ranks) == set(range(max(ranks) + 1)), name
        assert item["properties"]["rank"] == {"type": "integer", "minimum": 0, "maximum": max(ranks)}
        for rank in set(ranks):                                # tied tokens keep the schema order
            tied = [t for t, r in zip(listed, ranks) if r == rank]
            assert tied == [t for t in tokens if t in tied], name
        assert all(i["class"] in uip.VOCAB_CLASSES for i in entry["items"])
        block = d["VocabRanked"]["properties"][name]["properties"]["items"]
        assert block["minItems"] == block["maxItems"] == len(tokens) and block["items"] == {
            "$ref": f"#/$defs/{uip._vocab_title(name)}Item"}
    assert d["VocabRanked"]["required"] == list(vocab["ranked"]) and d["VocabRanked"]["additionalProperties"] is False
    unranked = {spec[0]: spec for spec in uip._VOCAB_UNRANKED}
    assert set(vocab["unranked"]) == set(unranked)
    for name, entry in vocab["unranked"].items():
        assert set(entry) == {"basis", "tokens"} and entry["basis"]
        tokens = unranked[name][1]
        assert tuple(entry["tokens"]) == tokens and tokens in schema_enums, name
        prop = d["VocabUnranked"]["properties"][name]
        assert prop["required"] == ["basis", "tokens"] and prop["additionalProperties"] is False
        assert prop["properties"]["tokens"] == {"type": "array", "uniqueItems": True,
                                                "items": {"type": "string", "enum": list(tokens)}}
    assert d["VocabUnranked"]["required"] == list(vocab["unranked"])
    assert d["Vocab"]["required"] == ["schema", "classes", "ranked", "unranked"]
    assert d["VocabClass"] == {"title": "VocabClass", "type": "string", "enum": list(uip.VOCAB_CLASSES)}


def test_v2_the_engine_vocabularies_the_register_names_are_all_ranked(vocab):
    # The G43 register: health band, lifecycle band, risk band, VLAN readiness, exposure state, security
    # grade and check status, coverage state, unknown-evidence state, link op status, plus the punch-list
    # and impact severities. Each must be ranked, never parked in the unranked catalogue.
    named = {"health_band": uip.HEALTH_BANDS, "lifecycle_band": uip.LIFECYCLE_BAND_ORDER,
             "risk_band": uip.DOSSIER_BANDS, "vlan_readiness": uip.VLAN_READINESS,
             "exposure_state": uip.EXPOSURE_STATES, "security_grade": uip.SEC_GRADES,
             "security_check_status": uip.SEC_STATUSES, "coverage_state": uip.COVERAGE_STATE_ORDER,
             "unknown_evidence_state": uip.UNKNOWN_EVIDENCE_STATES, "link_op_status": uip.OP_STATUSES,
             "severity": uip.SEVERITIES, "impact_severity": uip.IMPACT_SEVERITIES}
    for name, tokens in named.items():
        assert set(_ranks(vocab, name)) == set(tokens), name


# --------------------------------------------------------------------------------------------------
# V3 -- every rank an engine owner fixes equals that owner's; never a restated number
# --------------------------------------------------------------------------------------------------
def test_v3_ranks_follow_their_engine_owners(vocab):
    assert _ranks(vocab, "lifecycle_band") == analyze._LIFECYCLE_BAND_RANK
    assert _ranks(vocab, "risk_band") == analyze._DOSSIER_BAND_RANK
    assert _ranks(vocab, "vlan_readiness") == analyze._VLAN_CUTOVER_READY_RANK
    assert _ranks(vocab, "severity") == analyze._APP_SEV_RANK
    punch = sorted(analyze._PUNCH_RANK, key=analyze._PUNCH_RANK.get, reverse=True)
    assert [i["token"] for i in vocab["ranked"]["severity"]["items"]] == punch + ["Info"]
    assert _ranks(vocab, "health_band") == {band: i for i, band in enumerate(ssot._HEALTH_BAND_ORDER)}
    assert _ranks(vocab, "health_band_partition") == analyze._APP_BAND_RANK
    assert set(analyze._APP_BAND_RANK) == set(ssot._HEALTH_BAND_VOCABULARY)
    assert _ranks(vocab, "coverage_state") == {s: i for i, s in enumerate(coverage_matrix.COVERAGE_STATE_ORDER)}
    top = max(analyze._EP_CONF)
    assert _ranks(vocab, "endpoint_confidence") == {label: top - score for score, label in analyze._EP_CONF.items()}
    (impact,) = _local_dict_literals(analyze.compute_failure_impact, "sev_rank")
    assert _ranks(vocab, "impact_severity") == impact
    statuses = _local_dict_literals(analyze.compute_migration_readiness, "status_rank")
    assert statuses and all(table == statuses[0] for table in statuses)
    worst = max(statuses[0].values())
    assert _ranks(vocab, "readiness_check_status") == {t: worst - r for t, r in statuses[0].items()}
    assert _ranks(vocab, "readiness_check_status")["pass"] == _ranks(vocab, "readiness_check_status")["info"]
    (order,) = _local_dict_literals(analyze.compute_collection_completeness, "order")
    assert _ranks(vocab, "collection_status") == order
    grade = [node for node in ast.walk(_function_ast(parse_mod.parse_security))
             if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "grade" for t in node.targets)]
    assert len(grade) == 1
    chain, expr = [], grade[0].value
    while isinstance(expr, ast.IfExp):                         # the owner's precedence, first branch first
        chain.append(expr.body.value)
        expr = expr.orelse
    chain.append(expr.value)
    assert [i["token"] for i in vocab["ranked"]["security_grade"]["items"]] == chain
    owners = {name: entry["owner"] for name, entry in vocab["ranked"].items()}
    engine_owned = {name for name, owner in owners.items() if owner != uip._PRESENTATION_OWNER}
    assert engine_owned == {"health_band", "health_band_partition", "lifecycle_band", "risk_band", "vlan_readiness",
                            "readiness_check_status", "endpoint_confidence", "collection_status", "severity",
                            "impact_severity", "security_grade", "coverage_state"}
    for name in set(owners) - engine_owned:                    # a presentation-owned order says so in its basis
        assert "this projection shows" in vocab["ranked"][name]["basis"], name


def test_v3_impact_info_is_the_owners_indeterminate_result_not_a_clean_bill():
    tree = _function_ast(analyze.compute_failure_impact)
    hits = [node for node in ast.walk(tree) if isinstance(node, ast.If) and any(
        isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "sev" for t in n.targets)
        and isinstance(n.value, ast.Constant) and n.value.value == "Info" for n in ast.walk(node))]
    assert hits
    texts = " ".join(c.value for c in ast.walk(hits[0]) if isinstance(c, ast.Constant) and isinstance(c.value, str))
    assert "INDETERMINATE" in texts and "not a clean bill" in texts


# --------------------------------------------------------------------------------------------------
# V4 -- coverage honesty: every absence, unknown or informational token is undetermined, never pass
# --------------------------------------------------------------------------------------------------
#: The tokens each owner itself names as an absence, an unknown or an informational result.
ABSENCE = {
    "lifecycle_band": {"Unknown"},                                            # analyze._LIFECYCLE_BAND_RANK
    "risk_band": {"Unassessed"},                                              # analyze.compute_device_dossiers
    "health_band_partition": {ssot._HEALTH_BAND_NOT_SCORED},                  # ssot: never a band
    "coverage_state": set(coverage_matrix.COVERAGE_STATE_ORDER) - {"covered", "partial"},
    "unknown_evidence_state": set(uip.UNKNOWN_EVIDENCE_STATES) - set(uip.UE_COMPLETE_STATES),
    "unknown_evidence_source_state": {"not_collected", "malformed", "observed_empty"},   # not source_complete
    "link_op_status": {"unknown"},                                            # analyze.compute_cable_map
    "exposure_state": {"na"},                                                 # ax(): not assessable
    "security_check_status": {"na"},                                          # parse.parse_security
    "security_check_severity": {"info"},
    "readiness_check_status": {"info"},
    "severity": {"Info"},                                                     # the Coverage row
    "impact_severity": {"Info"},                                              # INDETERMINATE / none in scan
    "collection_status": {"not collected"},
    "stp_root_election_state": {"not_observed"},                              # stp_topology
    "endpoint_confidence": {"Unknown"},                                       # analyze._EP_CONF[0]
}


def test_v4_absence_tokens_are_undetermined_and_nothing_else_is(vocab):
    for name, entry in vocab["ranked"].items():
        classes = _classes(vocab, name)
        undetermined = {token for token, cls in classes.items() if cls == UND}
        assert undetermined == ABSENCE.get(name, set()), name
        assert not any(cls == "pass" for token, cls in classes.items() if token in ABSENCE.get(name, set()))
    assert set(vocab["ranked"]) - set(ABSENCE) == {"health_band", "vlan_readiness", "security_grade"}
    # the summary states the owner reaches without every source observed completely never vouch for a level
    assert {t for t in uip.UNKNOWN_EVIDENCE_STATES if t not in uip.UE_COMPLETE_STATES} <= ABSENCE["unknown_evidence_state"]
    assert _classes(vocab, "unknown_evidence_state")["observed_no_unknowns"] == "pass"
    assert _classes(vocab, "severity")["Low"] != "pass"            # a Low finding is still a finding
    assert _classes(vocab, "risk_band")["Unassessed"] == UND != _classes(vocab, "risk_band")["Low"]


def test_v4_owner_aligned_vocabularies_keep_each_tokens_rank_and_class(vocab):
    # ui_projection states these four by position against their owner tuples (their tokens share spellings with
    # the protocol-assessability receipt's states, which a section dependency must not name); a reordered owner
    # tuple must not shift a rank or a class onto a neighbouring token.
    pinned = {
        "collection_status": [("not collected", 0, UND), ("partial", 1, "watch")],
        "security_grade": [("weak", 0, "risk"), ("partial", 1, "watch"), ("hardened", 2, "pass")],
        "coverage_state": [("not_collected", 0, UND), ("unverified", 1, UND), ("unparsed", 2, UND),
                           ("partial", 3, "watch"), ("not_observed", 4, UND), ("covered", 5, "pass")],
        "unknown_evidence_source_state": [("not_collected", 0, UND), ("malformed", 1, UND), ("partial", 2, "watch"),
                                          ("observed_empty", 3, UND), ("observed", 4, "pass")],
    }
    for name, items in pinned.items():
        assert [(i["token"], i["rank"], i["class"]) for i in vocab["ranked"][name]["items"]] == items, name


def test_v4_class_semantics_cohere_with_the_legend_and_the_gating_rule(vocab):
    legend = {entry["token"]: entry for entry in uip._topology_legend()["entries"]}
    tone_class = {("info", "normal"): "pass", ("warning", "normal"): "watch", ("danger", "normal"): "risk",
                  ("danger", "strong"): "critical", ("muted", "normal"): UND}
    op, impact = _classes(vocab, "link_op_status"), _classes(vocab, "impact_severity")
    for token, cls in (("link_up", op["up"]), ("link_down", op["down"]), ("link_unknown", op["unknown"]),
                       ("impact_high", impact["High"]), ("impact_medium", impact["Medium"])):
        entry = legend[token]
        assert tone_class[(entry["tone"], entry["weight"])] == cls, token
    assert legend["impact_info"]["tone"] == "neutral" and impact["Info"] == UND
    severity = _classes(vocab, "severity")
    assert {s for s, cls in severity.items() if cls in ("critical", "risk")} == set(uip._AXIS_GATING)
    for name, entry in vocab["ranked"].items():
        classes = [item["class"] for item in entry["items"]]
        critical = [item for item in entry["items"] if item["class"] == "critical"]
        assert len(critical) <= 1 and all(item["rank"] == 0 for item in critical), name
        assert set(classes) <= set(uip.VOCAB_CLASSES) and set(classes) != {UND}, name
    assert {name for name, entry in vocab["ranked"].items()
            if any(i["class"] == "critical" for i in entry["items"])} == {
        "health_band", "health_band_partition", "lifecycle_band", "risk_band", "severity", "impact_severity"}


# --------------------------------------------------------------------------------------------------
# V5 -- every standalone document carries the one constant block and still validates
# --------------------------------------------------------------------------------------------------
def test_v5_fleet_device_and_path_documents_validate_and_carry_the_constant_block(schema):
    validator = Draft202012Validator(schema)
    sample, minimal = _sample(), _minimal()
    constant = uip._vocab()
    for snap in (sample, minimal, {}, {"devices": []}):
        payload = uip.project(snap)
        validator.validate(payload)
        assert list(payload)[-1] == "vocab" and payload["vocab"] == constant
    assert schema["required"][-1] == "vocab" and schema["properties"]["vocab"] == {"$ref": "#/$defs/Vocab"}
    host = _roster_hosts(sample)[0]
    document = uip.project_device(sample, host)
    Draft202012Validator({"$schema": schema["$schema"], "$defs": schema["$defs"],
                          "$ref": "#/$defs/DeviceDocument"}).validate(document)
    assert list(document) == ["schema", "engine", "device", "vocab"] and document["vocab"] == constant
    assert uip.project_devices(sample, [host]) == [document]
    assert uip.project_device(sample, "no-such-host")["vocab"] == constant
    path = uip.project_path(sample, "192.0.2.1", "198.51.100.1")
    Draft202012Validator({"$schema": schema["$schema"], "$defs": schema["$defs"],
                          "$ref": "#/$defs/PathDocument"}).validate(path)
    assert list(path) == ["schema", "engine", "path", "vocab"] and path["vocab"] == constant
    assert schema["$defs"]["PathDocument"]["required"] == ["schema", "engine", "path", "vocab"]


def test_v5_the_block_is_fresh_closed_and_rejects_forgeries(schema):
    first, second = uip._vocab(), uip._vocab()
    assert first == second and first is not second and first["ranked"] is not second["ranked"]
    first["ranked"]["health_band"]["items"][0]["class"] = "pass"
    first["unranked"]["ref_role"]["tokens"].clear()
    assert uip._vocab() == second                              # no shared container reached the output
    validator = Draft202012Validator({"$schema": schema["$schema"], "$defs": schema["$defs"],
                                      "$ref": "#/$defs/Vocab"})
    assert validator.is_valid(second)
    forgeries = {
        "extra_key": lambda v: v.update(extra=1),
        "wrong_schema": lambda v: v.update(schema="ui_projection_vocab/2"),
        "classes_short": lambda v: v["classes"].pop(),
        "classes_foreign": lambda v: v["classes"].__setitem__(0, "green"),
        "bad_class": lambda v: v["ranked"]["health_band"]["items"][0].update({"class": "green"}),
        "foreign_token": lambda v: v["ranked"]["health_band"]["items"][0].update(token="Severe"),
        "short_list": lambda v: v["ranked"]["health_band"]["items"].pop(),
        "long_list": lambda v: v["ranked"]["health_band"]["items"].append(
            dict(v["ranked"]["health_band"]["items"][0])),
        "rank_out_of_range": lambda v: v["ranked"]["health_band"]["items"][0].update(rank=99),
        "negative_rank": lambda v: v["ranked"]["health_band"]["items"][0].update(rank=-1),
        "fractional_rank": lambda v: v["ranked"]["health_band"]["items"][0].update(rank=0.5),
        "item_extra_key": lambda v: v["ranked"]["health_band"]["items"][0].update(tone="danger"),
        "empty_basis": lambda v: v["ranked"]["severity"].update(basis=""),
        "empty_owner": lambda v: v["ranked"]["severity"].update(owner=""),
        "missing_vocabulary": lambda v: v["ranked"].pop("severity"),
        "unknown_vocabulary": lambda v: v["ranked"].update(mood={"owner": "x", "basis": "y", "items": []}),
        "duplicate_unranked_token": lambda v: v["unranked"]["ref_role"]["tokens"].append(
            v["unranked"]["ref_role"]["tokens"][0]),
        "foreign_unranked_token": lambda v: v["unranked"]["ref_role"]["tokens"].append("owner"),
        "unranked_extra_key": lambda v: v["unranked"]["ref_role"].update(rank=0),
        "missing_unranked": lambda v: v["unranked"].pop("limitation_id"),
    }
    for name, forge in forgeries.items():
        forged = copy.deepcopy(second)
        forge(forged)
        assert not validator.is_valid(forged), name


def test_v5_schema_build_refuses_an_inconsistent_spec(monkeypatch):
    broken = list(uip._VOCAB_RANKED)
    name, tokens, owner, basis, order, classes = broken[0]
    broken[0] = (name, tokens, owner, basis, order[:-1], classes)             # the order drops a token
    monkeypatch.setattr(uip, "_VOCAB_RANKED", tuple(broken))
    with pytest.raises(ValueError):
        uip.ui_projection_schema()
    broken[0] = (name, tokens, owner, basis, order, {**classes, tokens[0]: "green"})   # a class outside the set
    monkeypatch.setattr(uip, "_VOCAB_RANKED", tuple(broken))
    with pytest.raises(ValueError):
        uip.ui_projection_schema()
    broken[0] = (name, tokens, owner, basis, order + (tokens[0],), classes)   # a token ranked twice
    monkeypatch.setattr(uip, "_VOCAB_RANKED", tuple(broken))
    with pytest.raises(ValueError):
        uip.ui_projection_schema()
