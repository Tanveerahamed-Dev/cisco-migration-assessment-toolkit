"""Runtime protocol assessability: exact denominator, abstentions, and projections."""

from __future__ import annotations

import json

import pytest

openpyxl = pytest.importorskip("openpyxl")
from openpyxl import Workbook  # noqa: E402

from cisco_toolkit.analyze import (  # noqa: E402
    PROTOCOL_ASSESSABILITY_FAMILIES,
    PROTOCOL_ASSESSABILITY_STATES,
    compute_protocol_assessability,
    compute_protocol_health,
)
from cisco_toolkit.excel import (  # noqa: E402
    write_collection_completeness_sheet,
    write_protocol_health_sheet,
)


EXPECTED_FAMILIES = ("STP", "EtherChannel", "VTP", "OSPF", "BGP", "EIGRP", "FHRP")


def _capture(tmp_path, name: str, body: str) -> str:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return str(path)


def _receipt(tmp_path) -> dict:
    usable = _capture(tmp_path, "usable.txt", "bounded protocol state\n")
    empty = _capture(tmp_path, "empty.txt", "\n")
    error = _capture(tmp_path, "error.txt", "% Invalid input detected at '^' marker.\n")
    command_files = {
        "sw1": {
            "show spanning-tree": usable,
            "show spanning-tree blockedports": empty,
            "show spanning-tree detail": error,
            "show etherchannel summary": usable,
            "show vtp status": empty,
            "show ip ospf neighbor": error,
            "show ip eigrp neighbors": usable,
            "show standby brief": usable,
            "show vrrp brief": empty,
            "show glbp brief": empty,
        }
    }
    health = [
        {"switch": "sw1", "protocol": "STP"},
        {"switch": "sw1", "protocol": "EIGRP"},
        {"switch": "sw1", "protocol": "FHRP"},
    ]
    return compute_protocol_assessability(
        ("sw2", "sw1"), {"sw1": {}}, command_files, health
    )


def test_protocol_assessability_is_exact_deterministic_and_capture_honest(tmp_path):
    receipt = _receipt(tmp_path)

    assert receipt["schema"] == "protocol_assessability/1"
    assert tuple(family["protocol"] for family in PROTOCOL_ASSESSABILITY_FAMILIES) == EXPECTED_FAMILIES
    assert tuple(family["protocol"] for family in receipt["families"]) == EXPECTED_FAMILIES
    assert {
        item["id"]: item["required"]
        for family in receipt["families"] if family["protocol"] == "STP"
        for item in family["inputs"]
    } == {
        "state": True,
        "blocked_ports": True,
        "inconsistent_ports": True,
        "topology_changes": False,
    }
    assert tuple(PROTOCOL_ASSESSABILITY_STATES) == (
        "assessed", "partial", "captured_no_record", "captured_empty", "not_running",
        "capture_error", "not_collected", "analysis_unavailable",
    )
    assert [(row["switch"], row["protocol"]) for row in receipt["rows"]] == [
        (host, protocol) for host in ("sw1", "sw2") for protocol in EXPECTED_FAMILIES
    ]

    sw1 = {row["protocol"]: row for row in receipt["rows"] if row["switch"] == "sw1"}
    assert sw1["STP"]["state"] == "partial"
    assert sw1["STP"]["input_states"] == {
        "state": "usable",
        "blocked_ports": "empty",
        "inconsistent_ports": "missing",
        "topology_changes": "error",
    }
    assert sw1["EtherChannel"]["state"] == "captured_no_record"
    assert sw1["VTP"]["state"] == "captured_empty"
    assert sw1["OSPF"]["state"] == "capture_error"
    assert sw1["BGP"]["state"] == "not_collected"
    assert sw1["EIGRP"]["state"] == "assessed"
    assert sw1["FHRP"]["state"] == "partial"
    assert sw1["FHRP"]["input_states"] == {
        "hsrp_groups": "usable", "vrrp_groups": "empty", "glbp_groups": "empty"
    }
    assert all(row["state"] == "not_collected" for row in receipt["rows"] if row["switch"] == "sw2")

    assert receipt["summary"] == {
        "n_devices": 2,
        "n_families": 7,
        "n_cells": 14,
        "n_health_rows": 3,
        "n_complete_devices": 0,
        "by_state": {
            "assessed": 1,
            "partial": 2,
            "captured_no_record": 1,
            "captured_empty": 1,
            "not_running": 0,
            "capture_error": 1,
            "not_collected": 8,
            "analysis_unavailable": 0,
        },
    }
    # The receipt is safe to publish: neither raw bodies nor source paths cross the boundary.
    rendered = json.dumps(receipt, sort_keys=True)
    assert str(tmp_path) not in rendered
    assert "% Invalid input" not in rendered
    assert receipt == _receipt(tmp_path)


def test_protocol_assessability_unions_all_host_sources_and_fails_closed(tmp_path):
    usable = _capture(tmp_path, "bgp-good.txt", "Neighbor V AS MsgRcvd MsgSent State/PfxRcd\n")
    error = _capture(tmp_path, "bgp-error.txt", "% Command not found\n")
    receipt = compute_protocol_assessability(
        ["inventory-only"],
        {"interfaces-only": {}},
        {"captures-only": {"show ip bgp summary": error, "show bgp summary": usable,
                           "show standby brief": usable}},
        [{"switch": "health-only", "protocol": "BGP"}],
    )
    assert {row["switch"] for row in receipt["rows"]} == {
        "inventory-only", "interfaces-only", "captures-only", "health-only"
    }
    assert receipt["summary"]["n_cells"] == 4 * 7
    by_key = {(row["switch"], row["protocol"]): row for row in receipt["rows"]}
    assert by_key[("captures-only", "BGP")]["capture_state"] == "usable"
    assert by_key[("captures-only", "BGP")]["state"] == "captured_no_record"
    assert by_key[("captures-only", "FHRP")]["state"] == "partial"
    assert by_key[("captures-only", "FHRP")]["input_states"] == {
        "hsrp_groups": "usable", "vrrp_groups": "missing", "glbp_groups": "missing"
    }
    # A sparse row that cannot be reconciled to current-run evidence is never called assessed.
    assert by_key[("health-only", "BGP")]["state"] == "partial"

    unavailable = compute_protocol_assessability(
        ["inventory-only"], {}, {}, [], analysis_available=False
    )
    assert unavailable["summary"]["by_state"]["analysis_unavailable"] == 7
    assert {row["state"] for row in unavailable["rows"]} == {"analysis_unavailable"}


def test_protocol_assessability_never_lets_empty_secondary_inputs_complete_or_mask_error(tmp_path):
    usable = _capture(tmp_path, "stp-usable.txt", "Spanning tree enabled protocol rstp\n")
    empty = _capture(tmp_path, "stp-empty.txt", "\n")
    error = _capture(tmp_path, "stp-error.txt", "% Invalid input detected at '^' marker.\n")

    partial = compute_protocol_assessability(
        ["sw-partial"], {"sw-partial": {}}, {"sw-partial": {
            "show spanning-tree": usable,
            "show spanning-tree blockedports": empty,
            "show spanning-tree inconsistentports": empty,
            "show spanning-tree detail": empty,
        }}, [{"switch": "sw-partial", "protocol": "STP"}],
    )
    stp_partial = next(row for row in partial["rows"] if row["protocol"] == "STP")
    assert stp_partial["capture_state"] == "usable"
    assert stp_partial["state"] == "partial"
    assert "blocked_ports, inconsistent_ports" in stp_partial["reason"]
    assert "topology_changes" not in stp_partial["reason"]

    failed_primary = compute_protocol_assessability(
        ["sw-error"], {"sw-error": {}}, {"sw-error": {
            "show spanning-tree": error,
            "show spanning-tree blockedports": empty,
        }}, [],
    )
    stp_error = next(row for row in failed_primary["rows"] if row["protocol"] == "STP")
    assert stp_error["input_states"]["state"] == "error"
    assert stp_error["input_states"]["blocked_ports"] == "empty"
    assert stp_error["capture_state"] == "error"
    assert stp_error["state"] == "capture_error"


def test_stp_health_requires_parsed_primary_evidence_and_optional_detail_does_not_block_assessment(tmp_path):
    unknown = _capture(
        tmp_path,
        "stp-unknown.txt",
        "VLAN0010\nbounded but unrecognized command output\n",
    )
    supplemental = _capture(tmp_path, "stp-supplemental.txt", "No affected ports observed\n")
    unknown_commands = {"sw-unknown": {
        "show spanning-tree": unknown,
        "show spanning-tree blockedports": supplemental,
        "show spanning-tree inconsistentports": supplemental,
    }}
    unknown_health = compute_protocol_health({"sw-unknown": {}}, unknown_commands)
    assert not [row for row in unknown_health if row["protocol"] == "STP"]

    unknown_receipt = compute_protocol_assessability(
        ["sw-unknown"], {"sw-unknown": {}}, unknown_commands, unknown_health
    )
    unknown_stp = next(row for row in unknown_receipt["rows"] if row["protocol"] == "STP")
    assert unknown_stp["health_row_emitted"] is False
    assert unknown_stp["state"] == "captured_no_record"

    nxos_stp = _capture(tmp_path, "stp-nxos.txt", """\
VLAN0010
  Spanning tree enabled protocol rstp
  Root ID    Priority    24586
             Address     aaaa.0001.0001
             This bridge is the root
  Bridge ID  Priority    24586
             Address     aaaa.0001.0001
Interface        Role Sts Cost      Prio.Nbr Type
Eth1/1           Desg FWD 4         128.1    P2p
""")
    nxos_commands = {"sw-nxos": {
        "show spanning-tree": nxos_stp,
        "show spanning-tree blockedports": supplemental,
        "show spanning-tree inconsistentports": supplemental,
    }}
    nxos_health = compute_protocol_health({"sw-nxos": {}}, nxos_commands)
    assert [row for row in nxos_health if row["protocol"] == "STP"]

    nxos_receipt = compute_protocol_assessability(
        ["sw-nxos"], {"sw-nxos": {}}, nxos_commands, nxos_health
    )
    nxos_stp_row = next(row for row in nxos_receipt["rows"] if row["protocol"] == "STP")
    assert nxos_stp_row["input_states"] == {
        "state": "usable",
        "blocked_ports": "usable",
        "inconsistent_ports": "usable",
        "topology_changes": "missing",
    }
    assert nxos_stp_row["health_row_emitted"] is True
    assert nxos_stp_row["state"] == "assessed"


def test_protocol_assessability_projects_explicitly_into_workbook(tmp_path):
    receipt = _receipt(tmp_path)
    wb = Workbook()
    write_protocol_health_sheet(wb, [])
    write_collection_completeness_sheet(
        wb,
        {"summary": {"inventory": 2, "complete": 1, "partial": 1, "not_collected": 0},
         "devices": []},
        {"summary": {"parsers_called": 0}, "events": []},
        protocol_assessability=receipt,
    )
    protocol_health_text = "\n".join(
        str(cell.value or "") for row in wb["Protocol Health"].iter_rows() for cell in row
    )
    completeness_text = "\n".join(
        str(cell.value or "") for row in wb["Collection Completeness"].iter_rows() for cell in row
    )
    assert "absence is not healthy" in protocol_health_text
    assert "Protocol assessability — runtime family × device receipt" in completeness_text
    assert "3 of 14 host-family cells" in completeness_text
    assert "PARTIAL" in completeness_text and "NOT COLLECTED" in completeness_text
    assert ("All inventory devices satisfy the baseline essential command groups — no baseline "
            "collection blind spots." in completeness_text)
    assert ("Protocol-specific evidence gaps may remain; review the Protocol assessability receipt "
            "below." in completeness_text)
    assert "All inventory devices fully collected — no blind spots." not in completeness_text

    wb2 = Workbook()
    write_protocol_health_sheet(wb2, [{
        "switch": "sw1", "protocol": "EIGRP", "summary": "1 neighbor(s) up",
        "detail": "Gi1/0/1", "severity": "Info",
    }])
    health_values = [cell.value for row in wb2["Protocol Health"].iter_rows() for cell in row]
    assert "OBSERVED · NO SUPPORTED ISSUE" in health_values
    assert "OK" not in health_values


# ---------------------------------------------------------------------------------------------------
# "Protocol not running" is POSITIVE evidence (owner decision c): the vendor no-process banner, cited.
# ---------------------------------------------------------------------------------------------------
import ast  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402

from cisco_toolkit import analyze, bgp_intent, cmdio, excel  # noqa: E402
from cisco_toolkit.analyze import (  # noqa: E402
    PROTOCOL_ASSESSABILITY_AUTHORIZING_STATES,
    PROTOCOL_ASSESSABILITY_CONCLUSIONS,
    PROTOCOL_ASSESSABILITY_NO_HEALTH_ROW_STATES,
    _validate_protocol_assessability_receipt,
    summarize_routing_baseline,
)
from cisco_toolkit.cmdio import (  # noqa: E402
    PROTOCOL_NOT_RUNNING_BANNERS,
    cmd_capture_state,
    cmd_not_running_banner,
    not_running_banner,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IOS_BGP_BANNER = "% BGP not active"     # cited in cmdio.PROTOCOL_NOT_RUNNING_BANNERS


def _bgp_receipt(tmp_path, body, command="show ip bgp summary", host="dist1"):
    path = _capture(tmp_path, f"{host}-bgp.txt", body)
    return compute_protocol_assessability([host], {host: {}}, {host: {command: path}}, [])


def _cell(receipt, host, protocol):
    return next(r for r in receipt["rows"] if (r["switch"], r["protocol"]) == (host, protocol))


def test_banner_registry_holds_only_cited_bgp_commands_and_matches_the_whole_capture_only():
    # Only the evidenced platform/commands are registered (see the source comment in cmdio): IOS BGP.
    assert set(PROTOCOL_NOT_RUNNING_BANNERS) == {"show ip bgp summary", "show bgp summary",
                                                 "show bgp all summary"}
    assert all(banners == (IOS_BGP_BANNER,) for banners in PROTOCOL_NOT_RUNNING_BANNERS.values())
    assert not any("ospf" in c or "eigrp" in c for c in PROTOCOL_NOT_RUNNING_BANNERS)
    assert not_running_banner("show ip bgp summary", "% BGP not active\n") == IOS_BGP_BANNER
    assert not_running_banner("show ip bgp summary", "\r\n  % BGP not active  \r\n\r\n") == IOS_BGP_BANNER
    # anything else in the capture -> ordinary output, never the banner
    assert not_running_banner("show ip bgp summary", "% BGP not active\nNeighbor V AS\n") == ""
    assert not_running_banner("show ip bgp summary", "BGP not active") == ""
    assert not_running_banner("show ip bgp summary", "% bgp NOT active") == ""
    # a banner under a command it was never evidenced for is not a banner
    assert not_running_banner("show ip ospf neighbor", "% BGP not active") == ""
    assert not_running_banner("show bgp ipv4 unicast summary", "% BGP not active") == ""


def test_banner_capture_stays_usable_for_every_existing_capture_consumer(tmp_path):
    """The banner does not change cmd_capture_state's meaning (not an error, not empty); only
    cmd_not_running_banner names it, following the SAME first-usable-variant resolution."""
    banner = _capture(tmp_path, "b.txt", "% BGP not active\n")
    table = _capture(tmp_path, "t.txt", "Neighbor V AS MsgRcvd MsgSent State/PfxRcd\n")
    err = _capture(tmp_path, "e.txt", "% Invalid input detected at '^' marker.\n")
    assert cmd_capture_state({"show ip bgp summary": banner}, "show ip bgp summary") == "usable"
    assert cmd_not_running_banner({"show ip bgp summary": banner}, "show ip bgp summary") == (
        "show ip bgp summary", IOS_BGP_BANNER)
    # first usable variant wins (the one _load_cmd_output hands the parser)
    assert cmd_not_running_banner({"show ip bgp summary": table, "show bgp summary": banner},
                                  "show ip bgp summary", "show bgp summary") == ("", "")
    assert cmd_not_running_banner({"show ip bgp summary": err, "show bgp summary": banner},
                                  "show ip bgp summary", "show bgp summary") == (
        "show bgp summary", IOS_BGP_BANNER)
    assert cmd_not_running_banner({}, "show ip bgp summary") == ("", "")


def test_bgp_no_process_banner_is_not_running_cited_never_assessed_or_healthy(tmp_path):
    receipt = _bgp_receipt(tmp_path, "% BGP not active\r\n")
    bgp = _cell(receipt, "dist1", "BGP")
    assert bgp["state"] == "not_running"
    assert bgp["capture_state"] == "usable" and bgp["input_states"] == {"peers": "usable"}
    assert bgp["health_row_emitted"] is False
    assert bgp["banner_evidence"] == [
        {"input": "peers", "command": "show ip bgp summary", "banner": IOS_BGP_BANNER}]
    assert IOS_BGP_BANNER in bgp["reason"] and "not running" in bgp["reason"]
    assert "neither an assessment nor a health verdict" in bgp["reason"]
    assert receipt["summary"]["by_state"]["not_running"] == 1
    assert receipt["summary"]["n_complete_devices"] == 0          # not_running never completes a device
    assert "not_running" not in PROTOCOL_ASSESSABILITY_AUTHORIZING_STATES
    assert "not_running" in PROTOCOL_ASSESSABILITY_NO_HEALTH_ROW_STATES
    # only the not_running cell carries banner evidence; no raw path crosses the boundary
    assert [r["protocol"] for r in receipt["rows"] if "banner_evidence" in r] == ["BGP"]
    assert str(tmp_path) not in json.dumps(receipt)
    view = _validate_protocol_assessability_receipt(receipt)
    assert (view["valid"], view["reason"]) == (True, "")


@pytest.mark.parametrize("body, command, expected", [
    ("% BGP not active\nBGP router identifier 10.0.0.1, local AS number 65001\n", "show ip bgp summary",
     "captured_no_record"),                                 # banner plus anything else: ordinary output
    ("BGP not active\n", "show ip bgp summary", "captured_no_record"),   # not the exact vendor text
    ("% BGP not active\n", "show bgp ipv4 unicast summary", "captured_no_record"),  # never evidenced
    ("", "show ip bgp summary", "captured_empty"),          # empty stays ambiguous, never 'not running'
])
def test_anything_but_the_exact_registered_banner_keeps_its_ordinary_state(tmp_path, body, command, expected):
    assert _cell(_bgp_receipt(tmp_path, body, command), "dist1", "BGP")["state"] == expected


def test_a_health_row_or_an_ospf_capture_never_becomes_not_running(tmp_path):
    path = _capture(tmp_path, "b.txt", "% BGP not active\n")
    emitted = compute_protocol_assessability(
        ["r1"], {"r1": {}}, {"r1": {"show ip bgp summary": path}}, [{"switch": "r1", "protocol": "BGP"}])
    assert _cell(emitted, "r1", "BGP")["state"] == "assessed"
    ospf = compute_protocol_assessability(
        ["r1"], {"r1": {}}, {"r1": {"show ip ospf neighbor": path}}, [])
    assert _cell(ospf, "r1", "OSPF")["state"] == "captured_no_record"


def _reseal_by_state(receipt):
    counts = {state: 0 for state in PROTOCOL_ASSESSABILITY_STATES}
    for row in receipt["rows"]:
        counts[row["state"]] += 1
    receipt["summary"]["by_state"] = counts


@pytest.mark.parametrize("forge", [
    "strip_evidence", "wrong_banner", "wrong_command", "evidence_on_other_state", "extra_key",
    "emitted_row",
])
def test_validator_refuses_a_not_running_cell_it_cannot_reconcile_to_a_registered_banner(tmp_path, forge):
    receipt = _bgp_receipt(tmp_path, "% BGP not active\n")
    bgp = _cell(receipt, "dist1", "BGP")
    if forge == "strip_evidence":
        del bgp["banner_evidence"]
    elif forge == "wrong_banner":
        bgp["banner_evidence"][0]["banner"] = "% OSPF not active"
    elif forge == "wrong_command":
        bgp["banner_evidence"][0]["command"] = "show ip ospf neighbor"
    elif forge == "evidence_on_other_state":
        bgp["state"] = "captured_no_record"
    elif forge == "extra_key":
        bgp["banner_evidence"][0]["body"] = "raw"
    elif forge == "emitted_row":
        bgp["health_row_emitted"] = True
        receipt["summary"]["n_health_rows"] = 1
    _reseal_by_state(receipt)
    assert _validate_protocol_assessability_receipt(receipt)["valid"] is False


def test_a_receipt_published_before_not_running_existed_still_validates_but_only_while_it_has_none(tmp_path):
    """Stored / compared snapshots (AssessHub uploads, --compare OLD) carry the 7-counter by_state of the
    same protocol_assessability/1 schema. Omitting the additive state's counter is exact only while no row
    carries it; otherwise every receipt-gated owner would read an old snapshot as an invalid receipt."""
    legacy = _receipt(tmp_path)
    del legacy["summary"]["by_state"]["not_running"]
    assert _validate_protocol_assessability_receipt(legacy)["valid"] is True
    legacy["summary"]["by_state"]["not_running"] = 1                    # a counter must still reconcile
    assert _validate_protocol_assessability_receipt(legacy)["valid"] is False
    banner = _bgp_receipt(tmp_path, "% BGP not active\n")
    del banner["summary"]["by_state"]["not_running"]                    # a not_running row needs its counter
    assert _validate_protocol_assessability_receipt(banner)["valid"] is False
    other = _receipt(tmp_path)
    del other["summary"]["by_state"]["captured_empty"]                  # only additive states are omissible
    assert _validate_protocol_assessability_receipt(other)["valid"] is False


def test_routing_owner_reads_not_running_as_no_row_state_never_as_an_assessed_subject(tmp_path):
    receipt = _bgp_receipt(tmp_path, "% BGP not active\n")
    # No peers observed: a not_running cell is not a routing subject at all (nothing to preserve).
    quiet = summarize_routing_baseline({"dist1": {"bgp": []}}, receipt)
    assert not [r for r in quiet["rows"] if r.get("switch") == "dist1" and r.get("protocol") == "BGP"]
    # Peers observed although the banner says BGP has no process: a contradiction, never assessed.
    noisy = summarize_routing_baseline(
        {"dist1": {"bgp": [{"neighbor": "10.0.0.2", "state": "Established", "as": "65002"}]}}, receipt)
    (row,) = [r for r in noisy["rows"] if r.get("switch") == "dist1" and r.get("protocol") == "BGP"]
    codes = {f["code"] for f in row["findings"]}
    assert "projection_receipt_contradiction" in codes, row
    assert row.get("status") != "assessed"


def test_every_consumer_covers_every_state_of_the_one_vocabulary():
    """Owner decision (c): each consumer's set/map is DERIVED from analyze's one state table."""
    traits = analyze._PROTOCOL_ASSESSABILITY_STATE_TRAITS
    assert tuple(traits) == PROTOCOL_ASSESSABILITY_STATES
    assert {t["conclusion"] for t in traits.values()} <= set(PROTOCOL_ASSESSABILITY_CONCLUSIONS)
    assert {t["health_row"] for t in traits.values()} <= {"emitted", "none", "either"}
    # excel colour map: exactly the vocabulary, not_running neither green (assessed) nor red (blind)
    assert set(excel.PROTOCOL_ASSESSABILITY_FILL) == set(PROTOCOL_ASSESSABILITY_STATES)
    assert excel.PROTOCOL_ASSESSABILITY_FILL["not_running"] not in (
        excel.PROTOCOL_ASSESSABILITY_FILL["assessed"], excel.PROTOCOL_ASSESSABILITY_FILL["not_collected"])
    # receipt-gated owners: every state is either authorizing or not; the no-row set is exact
    assert PROTOCOL_ASSESSABILITY_AUTHORIZING_STATES == {"assessed", "partial"}
    assert PROTOCOL_ASSESSABILITY_NO_HEALTH_ROW_STATES == {
        s for s in PROTOCOL_ASSESSABILITY_STATES if traits[s]["health_row"] == "none"}
    # the published engine contract projects the same vocabulary
    assert analyze.engine_contract_projection()["protocol_assessability_states"] == sorted(
        PROTOCOL_ASSESSABILITY_STATES)


_STATE_NAMES = frozenset(PROTOCOL_ASSESSABILITY_STATES) - {"assessed", "partial"}   # the distinctive names

# The coverage census (ssot.compute_schema_census) owns a DIFFERENT vocabulary that shares two names with the
# receipt ('not_collected', 'analysis_unavailable'). A collection is the census's, not a hand-list of receipt
# states, when every name in it is a census state AND at least one is census-only. Both sets derive from their
# owners, so this can never drift into a hand-kept exemption; a collection of only the SHARED names stays
# ambiguous and is still flagged (merge of main's #575, 2026-09-30).
from cisco_toolkit.ssot import ABSTENTION_STATES as _CENSUS_STATES  # noqa: E402

_CENSUS_ONLY = frozenset(_CENSUS_STATES) - frozenset(PROTOCOL_ASSESSABILITY_STATES)


def _is_census_collection(literals):
    names = set(literals)
    return bool(names) and names <= set(_CENSUS_STATES) and bool(names & _CENSUS_ONLY)


def _site_label(path):
    """A scanned file's name in a hit: its repository path when it is inside the repository, else its own path.
    A file outside the repository (a test's tmp_path) can sit on another Windows drive, where `relpath` raises
    (the hosted runners check out on D: and keep the temp directory on C:)."""
    full = os.path.abspath(path)
    try:
        rel = os.path.relpath(full, ROOT)
    except ValueError:                                   # another drive: not in the repository
        return full.replace(os.sep, "/")
    outside = rel == os.pardir or rel.startswith(os.pardir + os.sep)
    return (full if outside else rel).replace(os.sep, "/")


def _hand_listed_state_collections(path):
    """(file, line) of every site that ENUMERATES >=2 receipt states outside the one owner table.

    Three shapes, in every language the scan covers: a literal collection (set / tuple / list / dict keys /
    array), an equality chain or ladder (`s == "a" or s == "b"`, `s==="a"||s==="b"`, a conditional ladder),
    and a switch / match whose cases name the states. R1V1-4: the collection shape alone missed the
    explorer's `_paTok` ladder, which keeps giving an unlisted state the 'watch' tone after its Sets are
    fixed."""
    rel = _site_label(path)
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    hits = []
    if path.endswith(".py"):
        tree = ast.parse(text)
        owner = None
        for node in ast.walk(tree):
            if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", "") == \
                    "_PROTOCOL_ASSESSABILITY_STATE_TRAITS":
                owner = node.value

        def _consts(nodes):
            return {e.value for e in nodes if isinstance(e, ast.Constant) and e.value in _STATE_NAMES}

        for node in ast.walk(tree):
            if node is owner:
                continue
            names = set()
            if isinstance(node, ast.Dict):
                lits = [k.value for k in node.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)]
                names = set() if _is_census_collection(lits) else _consts(node.keys)
            elif isinstance(node, (ast.Set, ast.Tuple, ast.List)):
                lits = [e.value for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
                names = set() if _is_census_collection(lits) else _consts(node.elts)
            elif isinstance(node, ast.BoolOp):                      # s == "a" or s == "b"
                for v in node.values:
                    if isinstance(v, ast.Compare) and all(isinstance(o, (ast.Eq, ast.NotEq)) for o in v.ops):
                        names |= _consts([v.left, *v.comparators])
            elif isinstance(node, ast.IfExp):                       # "x" if s == "a" else ... if s == "b"
                arm = node
                while isinstance(arm, ast.IfExp):
                    if isinstance(arm.test, ast.Compare):
                        names |= _consts([arm.test.left, *arm.test.comparators])
                    arm = arm.orelse
            elif isinstance(node, ast.Match):
                names = {c.pattern.value.value for c in node.cases
                         if isinstance(c.pattern, ast.MatchValue) and isinstance(c.pattern.value, ast.Constant)
                         and c.pattern.value.value in _STATE_NAMES}
            if len(names) >= 2:
                hits.append((rel, node.lineno))
        return sorted(set(hits))

    def _line(pos):
        return text.count("\n", 0, pos) + 1

    for m in re.finditer(r"[\[{(][^\[\]{}()]*[\]})]", text):                     # literal collections
        # a collection holds only literals and separators; a block with code in it (`?`, `===`, `return`,
        # `case`) is not one -- the ladder / switch shapes below own those, so no site is counted twice
        if not re.fullmatch(r"[\s,:\w.+\-]*", re.sub(r"\"[^\"\n]*\"|'[^'\n]*'", "", m.group(0)[1:-1])):
            continue
        lits = re.findall(r"[\"']([a-z_]+)[\"']", m.group(0))
        if not _is_census_collection(lits) and len(set(lits) & _STATE_NAMES) >= 2:
            hits.append((rel, _line(m.start())))
    for m in re.finditer(r"[^;{}]+", text):                                        # equality chains / ladders
        chunk = m.group(0)
        names = set(re.findall(r"[=!]==?\s*[\"']([a-z_]+)[\"']", chunk)) | \
            set(re.findall(r"[\"']([a-z_]+)[\"']\s*[=!]==?", chunk))
        if len(names & _STATE_NAMES) >= 2:
            hits.append((rel, _line(m.start() + len(chunk) - len(chunk.lstrip()))))
    for m in re.finditer(r"\bswitch\s*\(", text):                                  # switch / case
        body_at = text.find("{", m.end())
        depth, i = 0, body_at
        while 0 <= i < len(text):
            depth += {"{": 1, "}": -1}.get(text[i], 0)
            if depth == 0:
                break
            i += 1
        cases = set(re.findall(r"\bcase\s+[\"']([a-z_]+)[\"']\s*:", text[body_at:i + 1]))
        if len(cases & _STATE_NAMES) >= 2:
            hits.append((rel, _line(m.start())))
    return sorted(set(hits))


# Where a consumer of the vocabulary can live: the engine and the AssessHub backend (Python, plus the explorer
# HTML the engine renders), the AssessHub frontend and the Atlas Scope app and compiler (TS/TSX/MJS -- they read
# atlas-scope/contracts/engine-contract.v1.json). Test files are excluded: enumerating the states is their job.
_SCAN_ROOTS = (("cisco_toolkit", (".py", ".html")), (os.path.join("webapp", "backend"), (".py",)),
               (os.path.join("webapp", "frontend", "src"), (".ts", ".tsx")),
               (os.path.join("atlas-scope", "src"), (".ts", ".tsx")),
               (os.path.join("atlas-scope", "tools"), (".mjs", ".ts")))
_SCAN_SKIP_DIRS = {"node_modules", "dist", "__pycache__", "build", "coverage"}


def _scanned_files():
    for base, exts in _SCAN_ROOTS:
        for dirpath, dirnames, filenames in os.walk(os.path.join(ROOT, base)):
            dirnames[:] = sorted(d for d in dirnames if d not in _SCAN_SKIP_DIRS)
            for name in sorted(filenames):
                if name.endswith(exts) and not re.search(r"\.(test|spec)\.[a-z]+$", name):
                    yield os.path.join(dirpath, name)


# Consumers OUTSIDE this cluster's files that still enumerate the vocabulary by hand, with the number of
# enumerating sites each holds (routed to their owners via needsFromOthers: derive from
# analyze.PROTOCOL_ASSESSABILITY_STATES in Python, from the engine-contract JSON elsewhere). A RATCHET keyed by
# file AND site count: a new site anywhere fails, and so does fixing one without lowering its count here.
_KNOWN_FOREIGN_HAND_LISTS: dict = {}     # emptied by the engine gate (R1V-5): html.py, the explorer and the
                                         # AssessHub portfolio now derive from analyze


_CONTRACT_IMPORT = re.compile(r"""\bimport\b[^;]*?\bfrom\s*["'][^"']*contracts/engine-contract\.v1\.json["']""")


def _binds_engine_contract(path):
    """A TS/JS consumer that IMPORTS the engine-contract projection reads the live vocabulary (it can refuse a
    state the engine no longer declares and see one it does not map); its per-state phrasing is then a
    mapping over the contract, not a free-standing copy. Python / the engine-rendered HTML have no such
    binding: they derive from the analyze tuple."""
    if not path.endswith((".ts", ".tsx", ".mjs")):
        return False
    with open(path, encoding="utf-8") as fh:
        return bool(_CONTRACT_IMPORT.search(fh.read()))


def test_no_consumer_hand_lists_the_state_vocabulary():
    hits = [hit for path in _scanned_files() if not _binds_engine_contract(path)
            for hit in _hand_listed_state_collections(path)]
    counts = {}
    for rel, _line in hits:
        counts[rel] = counts.get(rel, 0) + 1
    new = sorted(h for h in hits if h[0] not in _KNOWN_FOREIGN_HAND_LISTS)
    assert not new, ("derive the set/map from analyze.PROTOCOL_ASSESSABILITY_STATES (or its derived sets), or "
                     f"from atlas-scope/contracts/engine-contract.v1.json, instead of enumerating states: {new}")
    assert counts == _KNOWN_FOREIGN_HAND_LISTS, (
        "the hand-enumerated sites changed -- a new site in a known file is a regression; a fixed one must "
        f"lower (or remove) its entry in _KNOWN_FOREIGN_HAND_LISTS. Now: {counts}; sites: {hits}")


def test_the_hand_list_scanner_sees_every_enumeration_shape(tmp_path):
    """The scanner is not decoration: each shape it claims is detected, in Python and in JS/TS."""
    py = tmp_path / "consumer.py"
    py.write_text(
        "A = {'capture_error', 'not_collected'}\n"
        "def f(s):\n    return s == 'capture_error' or s == 'not_collected'\n"
        "def g(s):\n    return 'x' if s == 'capture_error' else 'y' if s == 'not_collected' else 'z'\n"
        "def h(s):\n    match s:\n        case 'capture_error':\n            return 1\n"
        "        case 'not_collected':\n            return 2\n"
        "B = {'assessed', 'capture_error'}\n", encoding="utf-8")
    ts = tmp_path / "consumer.ts"
    ts.write_text(
        'const A = new Set(["capture_error", "not_collected"]);\n'
        'function t(s){return s==="assessed"?"ok":s==="capture_error"||s==="not_collected"?"crit":"watch";}\n'
        'function u(s){\n  switch (s) {\n    case "captured_empty": return 1;\n'
        '    case "not_running": return 2;\n    default: return 0;\n  }\n}\n', encoding="utf-8")
    py_lines = sorted(line for _f, line in _hand_listed_state_collections(str(py)))
    ts_lines = sorted(line for _f, line in _hand_listed_state_collections(str(ts)))
    # set, BoolOp chain, IfExp ladder, match -- and NOT B (one distinctive name only)
    assert py_lines == [1, 3, 5, 7], py_lines
    # Set literal, ===/|| ladder, switch/case
    assert ts_lines == [1, 2, 4], ts_lines
    assert not _binds_engine_contract(str(ts))
    bound = tmp_path / "bound.ts"
    bound.write_text('import engineContract from "../../contracts/engine-contract.v1.json";\n'
                     + ts.read_text(encoding="utf-8"), encoding="utf-8")
    assert _binds_engine_contract(str(bound))


# ---------------------------------------------------------------------------------------------------------
# R1V-2: the enumeration scanner above cannot see a BINARY split (`state != "assessed"`), which is exactly how a
# consumer silently files not_running under "evidence gap". So the class is defined by what a module READS,
# not by what syntax it uses: every module that names the receipt (discovered, never hand-listed) must be
# classified, and each class carries a mechanical proof. A new reader fails until it is classified.
# ---------------------------------------------------------------------------------------------------------
_RECEIPT_NAME = re.compile(r"protocol_assessability|protocolAssessability")
_DERIVED_NAMES = re.compile(r"\b(PROTOCOL_ASSESSABILITY_(STATES|AUTHORIZING_STATES|NO_HEALTH_ROW_STATES|FILL|"
                            r"CONCLUSIONS)|_protocol_assessability_conclusion|_PROTOCOL_ASSESSABILITY_STATE_TRAITS)\b")
_ALL_STATES = frozenset(PROTOCOL_ASSESSABILITY_STATES)


def _receipt_readers():
    paths = list(_scanned_files()) + [os.path.join(ROOT, "COLLECT_PARSE_V3_23_0.py")]
    out = {}
    for path in paths:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        if _RECEIPT_NAME.search(text):
            out[os.path.relpath(path, ROOT).replace(os.sep, "/")] = text
    return out


def _python_state_interpretations(text):
    """Sites where Python code interprets a receipt state itself: a string constant that IS a receipt state used
    as a comparison operand, a subscript/get key, or a collection member (docstrings/comments never count)."""
    tree = ast.parse(text)
    hits = []
    for node in ast.walk(tree):
        operands = []
        if isinstance(node, ast.Compare):
            operands = [node.left, *node.comparators]
        elif isinstance(node, ast.Subscript):
            operands = [node.slice]
        elif isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "get" and node.args:
            operands = [node.args[0]]
        elif isinstance(node, (ast.Set, ast.Tuple, ast.List)):
            operands = list(node.elts)
        if any(isinstance(o, ast.Constant) and o.value in _ALL_STATES for o in operands):
            hits.append(node.lineno)
    return hits


def _state_interpreting_lines_near_receipt(text):
    """A carrier may use the word 'assessed' for its OWN vocabulary (other receipts' statuses); what it must not
    do is interpret a receipt ROW state. Count only interpretations of a DISTINCTIVE receipt state, or of any
    receipt state on a `state` key (the receipt rows' field)."""
    lines = text.splitlines()
    out = []
    for n in _python_state_interpretations(text):
        line = lines[n - 1]
        if re.search(r"[\"'](%s)[\"']" % "|".join(sorted(_STATE_NAMES)), line) or \
                re.search(r"[\"']state[\"']", line):
            out.append(n)
    return out


def _assert_section_dependency_reader(text):
    """A section dependency delegates absence to SSOT; it cannot interpret receipt row states.

    Only the two exact unknown-evidence owner vocabularies may account for the carrier scanner's
    overlapping tokens. This does not exempt receipt access or any other declaration/comparison.
    """
    from cisco_toolkit import unknown_evidence

    tree = ast.parse(text)
    declarations = {n.target.id: n for n in tree.body
                    if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)}
    dependency = declarations["PUNCHLIST_INPUTS"].value
    assert isinstance(dependency, ast.Tuple) and all(
        isinstance(n, ast.Constant) and isinstance(n.value, str) for n in dependency.elts)
    receipt_mentions = [n for n in ast.walk(tree)
                        if (isinstance(n, ast.Constant) and isinstance(n.value, str)
                            and _RECEIPT_NAME.search(n.value))
                        or (isinstance(n, ast.Name) and _RECEIPT_NAME.search(n.id))
                        or (isinstance(n, ast.Attribute) and _RECEIPT_NAME.search(n.attr))]
    assert len(receipt_mentions) == 1 and receipt_mentions[0] in dependency.elts, (
        "receipt access outside the literal section-dependency registry")
    # The registry itself may only flow to these section/rollup arguments. Indexing it to hide a
    # raw receipt read behind an alias, iterating it elsewhere, or adding another use fails here.
    # These normal Python bindings keep their name in a string field, not a Name(Store) node.
    binding_fields = {"arg": "arg", "FunctionDef": "name", "AsyncFunctionDef": "name", "ClassDef": "name",
                      "ExceptHandler": "name", "MatchAs": "name", "MatchStar": "name", "MatchMapping": "rest",
                      "TypeVar": "name", "ParamSpec": "name", "TypeVarTuple": "name"}
    for node in ast.walk(tree):
        field = binding_fields.get(type(node).__name__)
        bound = getattr(node, field, None) if field else None
        if isinstance(node, ast.alias):
            bound = node.asname or node.name.split(".")[0]
        assert bound != "PUNCHLIST_INPUTS", "dependency registry was shadowed or rebound"
        if isinstance(node, (ast.Global, ast.Nonlocal)):
            assert "PUNCHLIST_INPUTS" not in node.names, "dependency registry scope was redirected"
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    uses = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Name) or node.id != "PUNCHLIST_INPUTS":
            continue
        if not isinstance(node.ctx, ast.Load):
            assert node is declarations["PUNCHLIST_INPUTS"].target, "dependency registry was rebound"
            continue
        enclosing, call = node, None
        while enclosing in parents:
            enclosing = parents[enclosing]
            if isinstance(enclosing, ast.Call) and call is None:
                call = enclosing
            if isinstance(enclosing, ast.FunctionDef):
                break
        assert (call is not None and isinstance(call.func, ast.Name)
                and isinstance(enclosing, ast.FunctionDef)), "indirect dependency-registry use"
        arguments = [(str(i), value) for i, value in enumerate(call.args)]
        arguments += [(kw.arg, kw.value) for kw in call.keywords]
        uses.extend((enclosing.name, call.func.id, slot, ast.unparse(value))
                    for slot, value in arguments if node in ast.walk(value))
    assert sorted(uses) == sorted([
        ("_findings", "_listing", "rollup", "PUNCHLIST_INPUTS"),
        ("_findings", "_total", "sections", "toks + PUNCHLIST_INPUTS"),
        ("_device_page", "_rolled", "4", "PUNCHLIST_INPUTS"),
        ("_device_page", "_selection_rows", "sections", "('punchlist',) + PUNCHLIST_INPUTS"),
    ]), "dependency registry must only be forwarded to the declared section-state consumers"
    owned = {"COVERAGE_STATES": unknown_evidence._COVERAGE_STATES,
             "UE_SOURCE_STATES": unknown_evidence._SOURCE_STATES}
    for name, vocabulary in owned.items():
        copied = ast.literal_eval(declarations[name].value)
        assert isinstance(copied, tuple) and len(copied) == len(vocabulary) and set(copied) == vocabulary, (
            f"{name} must equal its unknown-evidence owner")
    tree.body = [n for n in tree.body if n not in [declarations[name] for name in owned]]
    foreign = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant)
               and isinstance(n.value, str) and n.value in _STATE_NAMES - set(_CENSUS_STATES)]
    assert not foreign, f"section dependency interprets receipt-only tokens: {foreign}"
    assert not _state_interpreting_lines_near_receipt(ast.unparse(tree)), (
        "section dependency interprets receipt row states")


# The owner (analyze.py) aside, every module that names the receipt, by class. The proofs:
#   derives   -- imports one of analyze's derived names (its sets/maps are the owner's, not a copy);
#   contract  -- reads protocol_assessability_states from atlas-scope/contracts/engine-contract.v1.json;
#   validator -- hands the receipt to the owner's validator and reads only its index, never a row state;
#   carrier   -- holds / forwards the receipt (to an owner function) and interprets no row state at all;
#   section_dependency -- names the receipt only in its dependency registry, delegates section states
#                to SSOT, and stays invariant across receipt row states (behavioral proof below);
#   rendered  -- the engine-rendered explorer template: it holds NO vocabulary of its own, only the one slot
#                html._render_engine_vocabulary fills from analyze at render time, and derives every state
#                set / tone from that map;
#   routed    -- still interprets states itself and misreads not_running; its fix is routed through
#                needsFromOthers and pinned by the ratchets below.
_RECEIPT_READER_CLASS = {
    "cisco_toolkit/analyze.py": "owner",
    "cisco_toolkit/excel.py": "derives",
    "cisco_toolkit/protocol_deltas.py": "validator",
    "cisco_toolkit/bgp_intent.py": "carrier",
    "cisco_toolkit/context.py": "carrier",
    "cisco_toolkit/l2_rehearsal.py": "carrier",
    "cisco_toolkit/nrfu_export.py": "carrier",
    "cisco_toolkit/protocol_assurance.py": "carrier",
    "webapp/backend/app.py": "carrier",
    "COLLECT_PARSE_V3_23_0.py": "carrier",
    "atlas-scope/tools/lib/compile-model.mjs": "contract",
    "atlas-scope/src/forwarding/rib-completeness.ts": "contract",
    "cisco_toolkit/runbook.py": "derives",
    "cisco_toolkit/html.py": "derives",
    "cisco_toolkit/blast_radius_explorer.html": "rendered",
    "webapp/backend/protocol_portfolio.py": "derives",
    "cisco_toolkit/ssot.py": "census",
    "cisco_toolkit/ui_projection.py": "section_dependency",
}


def test_every_module_that_reads_the_receipt_is_classified_with_a_mechanical_proof():
    readers = _receipt_readers()
    unclassified = sorted(set(readers) - set(_RECEIPT_READER_CLASS))
    assert not unclassified, (
        "a new module reads protocol_assessability: derive its state handling from analyze "
        f"(PROTOCOL_ASSESSABILITY_STATES / _protocol_assessability_conclusion) and classify it here: {unclassified}")
    gone = sorted(set(_RECEIPT_READER_CLASS) - set(readers))
    assert not gone, f"classified modules that no longer read the receipt -- drop them: {gone}"
    for rel, cls in sorted(_RECEIPT_READER_CLASS.items()):
        text = readers[rel]
        if cls == "owner":
            assert rel == analyze.engine_contract_projection()["owner"], rel
        elif cls == "derives":
            assert _DERIVED_NAMES.search(text), f"{rel} is classified 'derives' but imports no derived name"
        elif cls == "contract":
            assert "protocol_assessability_states" in text, f"{rel} does not read the engine-contract states"
        elif cls == "validator":
            assert "_validate_protocol_assessability_receipt" in text, rel
            assert not _state_interpreting_lines_near_receipt(text), (rel, _state_interpreting_lines_near_receipt(text))
        elif cls == "rendered":
            from cisco_toolkit.html import ENGINE_PA_CONCLUSIONS_MARKER
            assert text.count(ENGINE_PA_CONCLUSIONS_MARKER) == 1, f"{rel} lost its engine vocabulary slot"
            assert "new Set(Object.keys(ENGINE_PA_CONCLUSIONS))" in text, rel
            assert not _hand_listed_state_collections(os.path.join(ROOT, rel)), rel
        elif cls == "census":
            # the schema-census owner NAMES the section among every section and interprets only its OWN census
            # vocabulary (which shares two names with the receipt): it must own that vocabulary, and every
            # receipt-state name it interprets must be a census state -- never a receipt-only state
            assert "ABSTENTION_STATES" in text, f"{rel} is classified 'census' but no longer owns ABSTENTION_STATES"
            lines = text.splitlines()
            receipt_only = _ALL_STATES - set(_CENSUS_STATES)
            foreign = [n for n in _python_state_interpretations(text)
                       if set(re.findall(r"[\"']([a-z_]+)[\"']", lines[n - 1])) & receipt_only]
            assert not foreign, f"{rel} interprets receipt-only states at lines {foreign} -- derive from analyze"
        elif cls == "carrier":
            if rel.endswith(".py"):
                assert not _state_interpreting_lines_near_receipt(text), (
                    f"{rel} is classified 'carrier' but interprets receipt states itself at lines "
                    f"{_state_interpreting_lines_near_receipt(text)} -- derive from analyze and reclassify")
        elif cls == "section_dependency":
            _assert_section_dependency_reader(text)
        else:
            assert cls == "routed", (rel, cls)


def test_section_dependency_proof_rejects_receipt_reads_and_owner_vocabulary_drift():
    text = _receipt_readers()["cisco_toolkit/ui_projection.py"]
    _assert_section_dependency_reader(text)
    mutants = (
        text + "\ndef bad(s):\n    return s['protocol_assessability']['rows']\n",
        text + "\ndef bad(row):\n    return row.get('state') != 'assessed'\n",
        text + "\nRECEIPT_STATE_ALIAS = 'not_running'\n",
        text + "\ndef bad(s):\n    return s[PUNCHLIST_INPUTS[-3]]['rows'][-1]['state']\n",
        text + "\nDEPENDENCY_ALIAS = PUNCHLIST_INPUTS\n",
        text + "\ndef bad(s):\n    return [s[key] for key in PUNCHLIST_INPUTS]\n",
        text.replace("def _findings(ctx: _Ctx)", "def _findings(ctx: _Ctx, PUNCHLIST_INPUTS=())"),
        text + "\ndef PUNCHLIST_INPUTS():\n    pass\n",
        text + "\nclass PUNCHLIST_INPUTS:\n    pass\n",
        text + "\nfrom other_module import value as PUNCHLIST_INPUTS\n",
        text + "\nimport PUNCHLIST_INPUTS\n",
        text + "\ntry:\n    pass\nexcept Exception as PUNCHLIST_INPUTS:\n    pass\n",
        text + "\nmatch value:\n    case PUNCHLIST_INPUTS:\n        pass\n",
        text.replace('("covered", "not_collected", "partial",', '("covered", "not_collected", "wrong",'),
        text.replace('("observed", "observed_empty", "partial",', '("observed", "observed_empty", "wrong",'),
    )
    for mutant in mutants:
        assert mutant != text
        with pytest.raises(AssertionError):
            _assert_section_dependency_reader(mutant)


def _assert_section_projection_delegates(project_findings, monkeypatch):
    """Hold SSOT's answer fixed while varying every receipt token, including an unknown future token."""
    from cisco_toolkit import ssot, ui_projection

    snap = {name: [] for name in ui_projection.PUNCHLIST_INPUTS}
    snap.update(devices={}, interfaces={}, punchlist=[{
        "priority": 1, "rank": 1, "severity": "Low", "category": "Protocol",
        "title": "existing engine finding", "detail": "kept", "devices": [], "wave": "",
        "remediation": "", "evidence_basis": "absence", "evidence_refs": [],
    }])
    receipt = compute_protocol_assessability(["sw1"], {"sw1": {}}, {"sw1": {}}, [])
    receipt["rows"][0]["state"] = "assessed"
    snap["protocol_assessability"] = receipt
    original = ssot.abstention_reason
    assert project_findings(snap)["rows"]["state"] == "published"  # no unrelated gap can mask a mutant
    for owner_state in ssot.ABSTENTION_STATES:
        calls = []

        def section_state(value, subject, *args, **kwargs):
            if subject == "protocol_assessability":
                calls.append(subject)
                return owner_state
            return original(value, subject, *args, **kwargs)

        with monkeypatch.context() as scoped:
            scoped.setattr(ssot, "abstention_reason", section_state)
            expected = None
            probes = [(row,) for row in receipt["rows"]] + [tuple(receipt["rows"])]
            for rows in probes:
                baseline_states = [row["state"] for row in rows]
                for receipt_state in (*PROTOCOL_ASSESSABILITY_STATES, "future_unknown_state"):
                    for row in rows:
                        row["state"] = receipt_state
                    actual = project_findings(snap)
                    assert calls, "the projection must consult the SSOT section owner"
                    calls.clear()
                    assert actual["rows"]["state"] == (
                        "published" if owner_state == "collected_but_empty" else owner_state), (
                            "projection ignored SSOT section state")
                    if expected is None:
                        expected = actual
                    assert actual == expected, f"projection interpreted receipt row state {receipt_state}"
                for row, baseline_state in zip(rows, baseline_states):
                    row["state"] = baseline_state


def test_section_dependency_projection_follows_ssot_not_receipt_states(monkeypatch):
    from cisco_toolkit import ui_projection

    _assert_section_projection_delegates(ui_projection.project_findings, monkeypatch)

    # An alias avoids a second receipt literal and the existing same-line scanner. The behavioral
    # proof must still reject a binary row-state split, so this new class is not an exemption.
    def aliased_receipt_reader(snap):
        result = ui_projection.project_findings(snap)
        row = snap[ui_projection.PUNCHLIST_INPUTS[-3]]["rows"][0]
        token = row["state"]
        if token != "assessed":
            result["rows"]["state"] = "unverified"
        return result

    with pytest.raises(AssertionError, match="projection ignored SSOT section state"):
        _assert_section_projection_delegates(aliased_receipt_reader, monkeypatch)


    # Varying only the first family would miss an equally indirect read of a later family.
    def later_family_reader(snap):
        result = ui_projection.project_findings(snap)
        row = snap[ui_projection.PUNCHLIST_INPUTS[-3]]["rows"][-1]
        token = row["state"]
        if token == "assessed":
            result["rows"]["state"] = "unverified"
        return result

    with pytest.raises(AssertionError, match="projection ignored SSOT section state"):
        _assert_section_projection_delegates(later_family_reader, monkeypatch)


    # Per-family probes alone cannot refute an aggregate comparison across the full receipt.
    def aggregate_receipt_reader(snap):
        result = ui_projection.project_findings(snap)
        tokens = [row["state"] for row in snap[ui_projection.PUNCHLIST_INPUTS[-3]]["rows"]]
        if all(token == "assessed" for token in tokens):
            result["rows"]["state"] = "unverified"
        return result

    with pytest.raises(AssertionError, match="projection ignored SSOT section state"):
        _assert_section_projection_delegates(aggregate_receipt_reader, monkeypatch)


def test_the_census_vocabulary_is_told_apart_from_the_receipt_vocabulary(tmp_path):
    """A census map is not a receipt hand-list; a collection of only the SHARED names, or one holding any
    receipt-only name, still is -- in Python and in JS/TS alike."""
    py = tmp_path / "census.py"
    py.write_text(
        "A = {'published': 1, 'collected_but_empty': 2, 'not_collected': 3, 'analysis_unavailable': 4}\n"
        "B = ('not_collected', 'analysis_unavailable')\n"
        "C = {'published', 'not_collected', 'captured_empty'}\n", encoding="utf-8")
    assert sorted(line for _f, line in _hand_listed_state_collections(str(py))) == [2, 3]
    ts = tmp_path / "census.ts"
    ts.write_text(
        'const A = {"published": 1, "not_collected": 2, "analysis_unavailable": 3};\n'
        'const B = ["not_collected", "analysis_unavailable"];\n', encoding="utf-8")
    assert sorted(line for _f, line in _hand_listed_state_collections(str(ts))) == [2]
    assert _is_census_collection(list(_CENSUS_STATES)) and _CENSUS_ONLY


def test_the_reader_proofs_see_a_binary_split():
    """The carrier proof is the one the enumeration scanner lacked: a lone `row.get("state") != "assessed"`."""
    assert _state_interpreting_lines_near_receipt(
        "def f(rows):\n    return [r for r in rows if r.get('state') != 'assessed']\n") == [2]
    assert _state_interpreting_lines_near_receipt("def f(c):\n    return c['captured_empty']\n") == [2]
    assert _state_interpreting_lines_near_receipt(
        "def f(v):\n    '''assessed partial not_running'''\n    return v.get('status') == 'assessed'\n") == []


def _render_not_running_surfaces(tmp_path):
    """Render the two document consumers that interpret states themselves with a receipt holding one cited
    not_running cell, and return the misreadings observed (the owner's semantics: not_running is positive
    evidence the protocol contributes nothing on the host -- never a collection gap, never a recollect)."""
    from docx import Document

    from cisco_toolkit.runbook import write_runbook_docx

    receipt = _bgp_receipt(tmp_path, "% BGP not active\n")
    assert _cell(receipt, "dist1", "BGP")["state"] == "not_running"
    recollect = next(f["recollect"] for f in receipt["families"] if f["protocol"] == "BGP")
    found = set()

    wb = Workbook()
    write_collection_completeness_sheet(
        wb, {"summary": {"inventory": 1, "complete": 1, "partial": 0, "not_collected": 0}, "devices": []},
        {"summary": {"parsers_called": 0}, "events": []}, protocol_assessability=receipt)
    ws = wb["Collection Completeness"]
    (cell,) = [row[0] for row in ws.iter_rows() if row[0].value == "NOT RUNNING"]
    if recollect and recollect in str(ws.cell(cell.row, 5).value or ""):
        found.add(("workbook", "a not_running row carries the family's 'Next: recollect' action"))
    summary = next(str(c.value) for row in ws.iter_rows() for c in row
                   if isinstance(c.value, str) and "host-family cells" in c.value)
    if "not running" not in summary.lower():
        found.add(("workbook", "the summary counts not_running inside abstained/unassessed"))

    out = tmp_path / "runbook.docx"
    write_runbook_docx(str(out), {"devices": {"dist1": {}}, "protocol_assessability": receipt}, "t")
    doc = Document(str(out))
    paras = [p.text for p in doc.paragraphs]
    counts = next((p for p in paras if p.startswith("Runtime assessability:")), "")
    if "not running" not in counts.lower():
        found.add(("runbook", "the counts file not_running under 'not assessable'"))
    gap_rows = [[c.text for c in row.cells] for t in doc.tables for row in t.rows
                if t.rows and [c.text for c in t.rows[0].cells][:3] == ["State", "Switch", "Protocol"]]
    if any(r[0] == "NOT RUNNING" for r in gap_rows):
        found.add(("runbook", "the 'evidence gaps requiring collection' table lists not_running"))
    return found


# Misreadings still present in document consumers. A RATCHET: a new misreading fails, and so does a fixed one
# until its entry is removed here. Empty since the engine gate threaded not_running through runbook.py and
# excel.py's collection-completeness writer (R1V-2).
_KNOWN_NOT_RUNNING_MISREADINGS: set = set()


def test_document_consumers_do_not_misread_not_running_beyond_the_routed_ratchet(tmp_path):
    pytest.importorskip("docx")
    found = _render_not_running_surfaces(tmp_path)
    assert found == _KNOWN_NOT_RUNNING_MISREADINGS, (
        "not_running misreadings changed -- a NEW one is a regression; a FIXED one must be removed from "
        f"_KNOWN_NOT_RUNNING_MISREADINGS. Observed: {sorted(found)}")


def test_workbook_renders_not_running_as_its_own_cited_state(tmp_path):
    receipt = _bgp_receipt(tmp_path, "% BGP not active\n")
    wb = Workbook()
    write_collection_completeness_sheet(
        wb, {"summary": {"inventory": 1, "complete": 1, "partial": 0, "not_collected": 0}, "devices": []},
        {"summary": {"parsers_called": 0}, "events": []}, protocol_assessability=receipt)
    ws = wb["Collection Completeness"]
    (cell,) = [row[0] for row in ws.iter_rows() if row[0].value == "NOT RUNNING"]
    assert cell.fill.fgColor.rgb.endswith(excel.PROTOCOL_ASSESSABILITY_FILL["not_running"])
    reason = ws.cell(cell.row, 5).value
    assert IOS_BGP_BANNER in reason and "not running" in reason


def test_bgp_configured_peer_baseline_reads_the_same_banner_the_receipt_calls_not_running(tmp_path):
    """Producer consistency: the ONE banner owner (cmdio) drives both the receipt's not_running and the
    configured-peer baseline's runtime parser, which reads it as a complete, empty peer summary."""
    from cisco_toolkit.capture_integrity import compute_capture_integrity_from_paths
    host_dir = tmp_path / "dist1"
    host_dir.mkdir()
    cfg = host_dir / "show_running-config.txt"
    cfg.write_text("version 17.9\nhostname dist1\nend\n", encoding="utf-8")
    run = host_dir / "show_ip_bgp_summary.txt"
    run.write_text("% BGP not active\n", encoding="utf-8")
    mapping = {"dist1": {"show running-config": str(cfg), "show ip bgp summary": str(run)}}
    receipt = compute_protocol_assessability(["dist1"], {"dist1": {}}, mapping, [])
    assert _cell(receipt, "dist1", "BGP")["state"] == "not_running"
    integrity = compute_capture_integrity_from_paths(mapping)
    baseline = bgp_intent.compute_bgp_configured_peer_baseline(mapping, integrity, {"dist1": "IOS-XE"})
    (cov,) = baseline["coverage"]
    assert (cov["runtime_capture_status"], cov["runtime_parser_status"]) == ("ok", "complete")
    assert cov["finding_codes"] == [] and not baseline["findings"]
    assert (cov["subject"], cov["status"], baseline["verdict"]) == (False, "not_applicable", "NOT_APPLICABLE")
    assert bgp_intent.validate_bgp_configured_peer_baseline(baseline)["valid"] is True
    assert cmdio.not_running_banner is bgp_intent.not_running_banner     # one owner, imported
