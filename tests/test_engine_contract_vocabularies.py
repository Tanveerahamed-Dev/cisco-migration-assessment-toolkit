"""The closed vocabularies Atlas Scope recognises -- severity, health band, node kind -- are ENGINE facts (ADR 0007
D9: facts live in Python, the browser only renders). ``analyze.engine_contract_projection`` publishes them in
``atlas-scope/contracts/engine-contract.v1.json``; Atlas Scope's recognisers read them from there
(atlas-scope/src/core/vocab.ts, pinned against its TypeScript unions by src/core/vocab.contract.test.ts).

Each projected list is read from its owner constant, and each owner constant is pinned here against what the
PRODUCERS actually write -- so the projection cannot be a third hand-kept copy that agrees with neither:

* severities  -- ``_APP_SEV_RANK`` (most severe first); the punch-list's narrower ``_SEV_RANK`` is a subset, and
  EVERY severity the whole pipeline writes (the golden snapshot and the engine-owned sample, walked whole) is a
  member, except in the sections declared to carry a foreign vocabulary (``_FOREIGN_SEVERITY_SECTIONS``).
* health_bands.scored -- the labels of ``_HEALTH_BANDS`` (the default ``SCORING.bands``), highest first.
* health_bands.not_measured -- ``HEALTH_BAND_NOT_MEASURED``, exactly what ``compute_health_scores`` writes for a
  host it could not measure; marked separately because it is a stated ABSENCE of a measurement, never a band.
* node_kinds.collected -- ``CABLE_MAP_COLLECTED_KIND``, what ``compute_cable_map`` writes for a collected node.
* node_kinds.classified -- ``_KIND_RANK``, the only kinds ``_node_kind`` can return for an uncollected node.
"""
import json
import os

from cisco_toolkit import analyze
from cisco_toolkit import parse as _parse
from cisco_toolkit.model import InterfaceData

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _doc():
    return json.loads(analyze.render_engine_contract())


def test_severities_are_the_app_severity_rank_most_severe_first():
    doc = _doc()
    assert doc["severities"] == sorted(analyze._APP_SEV_RANK, key=analyze._APP_SEV_RANK.__getitem__)
    assert doc["severities"] == ["Critical", "High", "Medium", "Low", "Info"]
    # the punch-list's own rank table names no severity the published vocabulary lacks
    assert set(analyze._SEV_RANK) <= set(doc["severities"])


def test_health_bands_are_the_scored_bands_plus_the_marked_not_measured_band():
    doc = _doc()
    hb = doc["health_bands"]
    assert list(hb) == ["scored", "not_measured"]
    assert hb["scored"] == [label for _thr, label, _fill in analyze._HEALTH_BANDS]
    assert hb["scored"] == [label for _thr, label, _fill in analyze.SCORING.bands]
    assert hb["not_measured"] == analyze.HEALTH_BAND_NOT_MEASURED == "Insufficient Data"
    assert hb["not_measured"] not in hb["scored"]
    # every engine table keyed by band names exactly these (scored + not-measured), no more, no less
    every = set(hb["scored"]) | {hb["not_measured"]}
    assert set(analyze._APP_BAND_RANK) == every
    assert set(analyze._CRIT_WEIGHTS["band"]) == every


def test_not_measured_band_is_what_the_health_producer_writes_for_an_unmeasured_host():
    ifaces = {"measured": {"Gi0/1": InterfaceData(port="Gi0/1")},
              "unmeasured": {"Gi0/1": InterfaceData(port="Gi0/1")},
              "empty_parse": {}}
    by = {r["switch"]: r for r in analyze.compute_health_scores(
        ifaces, [], [], [], [], data_quality={"measured": 1.0, "empty_parse": 1.0})}
    nm = _doc()["health_bands"]["not_measured"]
    assert by["unmeasured"]["band"] == nm          # never measured
    assert by["empty_parse"]["band"] == nm         # measured, but the parse yielded nothing
    assert by["measured"]["band"] in _doc()["health_bands"]["scored"]


def test_node_kinds_are_the_collected_kind_plus_the_classifier_rank():
    nk = _doc()["node_kinds"]
    assert list(nk) == ["collected", "classified"]
    assert nk["collected"] == analyze.CABLE_MAP_COLLECTED_KIND == "device"
    assert nk["classified"] == list(analyze._KIND_RANK)
    assert nk["collected"] not in nk["classified"]
    # the classifier's inputs can only produce a ranked kind
    assert set(analyze._EPTYPE_TO_KIND.values()) <= set(analyze._KIND_RANK)
    assert {k for k, _toks in analyze._PLATFORM_KIND_TOKENS} <= set(analyze._KIND_RANK)


def test_node_kinds_are_what_the_cable_map_producer_writes():
    """Drive compute_cable_map: a collected node is the collected kind; an uncollected neighbour is classified
    from whatever platform / endpoint-type evidence it carries, and every result is a published kind."""
    platforms = ["", "Cisco IP Phone 8865", "AIR-AP3802I", "ASA5516", "camera x", "ISR4451", "WS-C3850", "mystery"]
    ep_types = ["Switch", "Router", "Firewall", "Access Point", "IP Phone", "Server", "Printer", "", "weird"]
    ifaces = {"COLL": {}}
    i = 0
    for plat in platforms:
        for ep in ep_types:
            i += 1
            port = f"Gi1/0/{i}"
            ifaces["COLL"][port] = InterfaceData(port=port, status="connected", cdp_neighbor=f"N{i}",
                                                 neighbor_port="Gi0/0", endpoint_type=ep,
                                                 neighbor_platform=plat)
    nodes = {n["host"]: n for n in analyze.compute_cable_map(ifaces, None)["nodes"]}
    nk = _doc()["node_kinds"]
    assert nodes["COLL"]["kind"] == nk["collected"]
    seen = {n["kind"] for h, n in nodes.items() if h != "COLL"}
    assert seen <= set(nk["classified"]), seen
    assert len(seen) > 1, f"the probe exercised only {seen}"


def test_projection_reads_each_vocabulary_from_its_owner_not_a_copy(monkeypatch):
    """Mutate each owner constant: the projection follows it (nothing is hand-listed in the projection)."""
    monkeypatch.setattr(analyze, "_APP_SEV_RANK", {"Info": 1, "Grave": 0})
    monkeypatch.setattr(analyze, "_HEALTH_BANDS", [(50, "Fine", "000000"), (0, "Bad", "111111")])
    monkeypatch.setattr(analyze, "HEALTH_BAND_NOT_MEASURED", "Unmeasured")
    monkeypatch.setattr(analyze, "CABLE_MAP_COLLECTED_KIND", "box")
    monkeypatch.setattr(analyze, "_KIND_RANK", ("thing", "unknown"))
    doc = analyze.engine_contract_projection()
    assert doc["severities"] == ["Grave", "Info"]
    assert doc["health_bands"] == {"scored": ["Fine", "Bad"], "not_measured": "Unmeasured"}
    assert doc["node_kinds"] == {"collected": "box", "classified": ["thing", "unknown"]}


# --- severities, against what the PRODUCERS write (verifier S-VOCAB V5) -------------------------------------------
# The rank-table checks above compare constants only. Severity has many writers (the punch list, cross-layer,
# failure impact, physical/protocol health, the remediation and validation plans, ...), so the producer evidence is
# the engine's own whole-pipeline output: tests/golden/snapshot.json (pinned to a real offline pipeline run by
# tests/test_pipeline_golden.py) and webapp/sample_data/sample_fleet.snapshot.json (the engine-owned sample Atlas
# Scope compiles; `build_sample.py --check` pins it fresh). EVERY `severity` string anywhere in either document must
# be a published severity -- the class is "every severity the engine writes", not a list of sections.
#
# The only exceptions are sections that carry a DIFFERENT, foreign severity vocabulary. They are named here with the
# vocabulary each carries (pinned below), so a new section -- or a new writer in an existing one -- is inside the
# class by default and fails until it is either published or declared foreign with its own owner.
_FOREIGN_SEVERITY_SECTIONS = {
    # cisco_toolkit/parse.py security audit `add()`: the lowercase _SEC_CHECKS severity on a fail, "info" otherwise.
    "security": lambda: {sev for _t, sev, _r, _rem in _parse._SEC_CHECKS.values()} | {"info"},
    # cisco_toolkit/build.py build_aci: the APIC faultInst severity carried verbatim from the controller (Cisco's
    # own fault vocabulary, lowercase), never re-graded by the engine.
    "aci": lambda: {"critical", "major", "minor", "warning", "info", "cleared"},
}
_ENGINE_OUTPUTS = ("tests/golden/snapshot.json", "webapp/sample_data/sample_fleet.snapshot.json")


def _severities_by_section(doc):
    found = {}

    def walk(o, section):
        if isinstance(o, dict):
            for k, v in o.items():
                if k == "severity" and isinstance(v, str):
                    found.setdefault(section, set()).add(v)
                walk(v, section)
        elif isinstance(o, list):
            for x in o:
                walk(x, section)

    for section, value in doc.items():
        walk(value, section)
    return found


def _engine_output(rel):
    with open(os.path.join(_ROOT, *rel.split("/")), encoding="utf-8") as fh:
        return json.load(fh)


def test_every_severity_the_engine_writes_is_a_published_severity():
    published = set(_doc()["severities"])
    seen_foreign = set()
    for rel in _ENGINE_OUTPUTS:
        by_section = _severities_by_section(_engine_output(rel))
        assert {"punchlist", "cross_layer", "failure_impact"} <= set(by_section), (rel, sorted(by_section))
        for section, values in sorted(by_section.items()):
            if section in _FOREIGN_SEVERITY_SECTIONS:
                seen_foreign.add(section)
                foreign = _FOREIGN_SEVERITY_SECTIONS[section]()
                assert values <= foreign, (rel, section, sorted(values - foreign))
                # a foreign term never collides with a published one, so it cannot be read as an engine grade
                assert not (values & published), (rel, section, sorted(values & published))
                continue
            assert values <= published, (
                f"{rel}: section {section!r} writes severity {sorted(values - published)} that the engine contract "
                f"does not publish -- add it to _APP_SEV_RANK, or declare the section's foreign vocabulary here")
    # every declared exception is exercised; a stale exception would silently widen the hole
    assert seen_foreign == set(_FOREIGN_SEVERITY_SECTIONS), sorted(set(_FOREIGN_SEVERITY_SECTIONS) - seen_foreign)


def test_the_severity_walk_is_live():
    """The walk sees a severity at any depth, and a section writing an unpublished grade is attributed to it."""
    doc = {"punchlist": [{"severity": "High"}], "deep": {"a": [{"b": {"severity": "Grave"}}]},
           "security": {"h": {"findings": [{"severity": "low"}]}}}
    assert _severities_by_section(doc) == {"punchlist": {"High"}, "deep": {"Grave"}, "security": {"low"}}


def test_the_producers_write_the_owner_constants_not_a_literal_copy(monkeypatch):
    """W5b (S-VOCAB V6 / D4): the producers WRITE the owner constants, so the constant is the one owner and a
    literal beside it cannot drift. Mutate each constant and drive its producer: what is written follows it."""
    monkeypatch.setattr(analyze, "HEALTH_BAND_NOT_MEASURED", "not-measured-probe")
    monkeypatch.setattr(analyze, "CABLE_MAP_COLLECTED_KIND", "collected-probe")
    ifaces = {"unmeasured": {"Gi0/1": InterfaceData(port="Gi0/1")}, "empty_parse": {}}
    by = {r["switch"]: r for r in analyze.compute_health_scores(
        ifaces, [], [], [], [], data_quality={"empty_parse": 1.0})}
    assert by["unmeasured"]["band"] == "not-measured-probe"
    assert by["empty_parse"]["band"] == "not-measured-probe"
    nodes = analyze.compute_cable_map({"COLL": {"Gi0/1": InterfaceData(port="Gi0/1", status="connected")}},
                                      None)["nodes"]
    assert [n["kind"] for n in nodes if n["host"] == "COLL"] == ["collected-probe"]


def test_the_not_measured_band_is_spelled_once_in_its_owner_module():
    """W5b (S-VOCAB V6 / D4): every writer AND reader of the not-measured band in analyze.py names
    HEALTH_BAND_NOT_MEASURED; the literal appears exactly once, in that constant's own assignment. Derived from
    the module's AST (every string constant equal to the band), not from a list of known sites."""
    import ast

    path = os.path.join(_ROOT, "cisco_toolkit", "analyze.py")
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    owner = [node for node in ast.walk(tree) if isinstance(node, ast.Assign)
             and [getattr(t, "id", None) for t in node.targets] == ["HEALTH_BAND_NOT_MEASURED"]]
    assert len(owner) == 1
    literal = owner[0].value
    assert isinstance(literal, ast.Constant) and literal.value == analyze.HEALTH_BAND_NOT_MEASURED
    copies = sorted(node.lineno for node in ast.walk(tree)
                    if isinstance(node, ast.Constant) and node.value == analyze.HEALTH_BAND_NOT_MEASURED
                    and node is not literal)
    assert copies == [], f"analyze.py spells the not-measured band as a literal at lines {copies}"
