"""Governed unknown-evidence aggregation: honesty, privacy and determinism."""
from __future__ import annotations

import json
from pathlib import Path
from types import MappingProxyType

from cisco_toolkit import cmdio
from cisco_toolkit.design_advisor import _ARCH_COVERAGE_REGISTRY
from cisco_toolkit.unknown_evidence import (
    CLASSIFICATIONS,
    DISPOSITIONS,
    EVENT_SCHEMA,
    SCHEMA,
    compute_unknown_evidence,
    unavailable_unknown_evidence,
)


ROOT = Path(__file__).resolve().parent.parent


def _complete_architecture() -> dict:
    classes = [
        {
            "key": axis,
            "label": label,
            "channel": channel,
            "detectors": list(detectors),
            "observed": False,
            "n_hosts": 0,
            "hosts": [],
            "status": "not-observed",
            "findings": [],
        }
        for axis, label, channel, detectors in _ARCH_COVERAGE_REGISTRY
    ]
    return {
        "classes": classes,
        "summary": {
            "n_classes": len(classes),
            "n_observed": 0,
            "n_with_findings": 0,
            "n_clean": 0,
            "n_not_observed": len(classes),
        },
    }


def _complete_coverage() -> dict:
    first_arch = _ARCH_COVERAGE_REGISTRY[0][0]
    rows = [
        {"device": "discard-me", "axis": axis, "dimension": axis,
         "state": "covered", "verdict_source": "fixture", "is_abstention": False}
        for axis in ("collection", "capture", "parse")
    ]
    rows.append(
        {"device": "(fleet)", "axis": first_arch, "dimension": "architecture",
         "state": "not_observed", "verdict_source": "fixture", "is_abstention": True}
    )
    return {"rows": rows, "by_device": {}, "summary": {"n_rows": len(rows)}}


def _parse_source(per_parser: dict, events: list, *, truncated: bool = False) -> dict:
    suspect = 0
    expected = 0
    errors = 0
    for parser, counts in per_parser.items():
        zero = counts["zero_yield"]
        if parser in cmdio.MAY_BE_EMPTY_PARSERS:
            expected += zero
        else:
            suspect += zero
        errors += counts["errors"]
    return {
        "summary": {
            "parsers_called": len(per_parser),
            "zero_yield_suspect": suspect,
            "zero_yield_expected": expected,
            "parse_errors": errors,
        },
        "per_parser": per_parser,
        "events": events,
        "events_truncated": truncated,
    }


def _snapshot(parse_yield: dict) -> dict:
    return {
        "parse_yield": parse_yield,
        "coverage_matrix": _complete_coverage(),
        "architecture_coverage": _complete_architecture(),
    }


def _stats(calls: int, with_content: int, zero_yield: int, errors: int) -> dict:
    return {
        "calls": calls,
        "with_content": with_content,
        "zero_yield": zero_yield,
        "errors": errors,
        "may_be_empty": False,
    }


def test_cross_parser_aggregate_is_canonical_and_coverage_honest():
    per_parser = {
        "parse_ip_routes": _stats(4, 4, 3, 1),
        "parse_nat": _stats(2, 2, 2, 0),
        "client-owned-parser-token": _stats(2, 2, 1, 1),
    }
    events = [
        {"parser": "parse_ip_routes", "device": "site-a-core-1", "cmd": "show ip route",
         "file": "show_ip_route.txt", "lines_in": 40, "error": True},
        {"parser": "parse_ip_routes", "device": "site-a-core-1", "cmd": "show ip route",
         "file": "show_ip_route.txt", "lines_in": 40, "error": False},
        {"parser": "parse_ip_routes", "device": "site-a-core-2", "cmd": "show ip route",
         "file": "show_ip_route.txt", "lines_in": 42, "error": False},
        {"parser": "parse_ip_routes", "device": "site-a-core-3", "cmd": "show ip route",
         "file": "show_ip_route.txt", "lines_in": 44, "error": False},
        {"parser": "parse_nat", "device": "site-a-core-1", "cmd": "show running-config",
         "file": "show_running-config.txt", "lines_in": 90, "error": False},
        {"parser": "parse_nat", "device": "site-a-core-2", "cmd": "show running-config",
         "file": "show_running-config.txt", "lines_in": 91, "error": False},
        {"parser": "client-owned-parser-token", "device": "site-a-core-1",
         "cmd": "show customer-private-value", "file": "private.txt", "lines_in": 12, "error": True},
        {"parser": "client-owned-parser-token", "device": "site-a-core-2",
         "cmd": "show customer-private-value", "file": "private.txt", "lines_in": 13, "error": False},
    ]

    report = compute_unknown_evidence(_snapshot(_parse_source(per_parser, events)))

    assert report["schema"] == SCHEMA
    assert report["event_schema"] == EVENT_SCHEMA
    assert report["summary"]["state"] == "observed_with_unresolved"
    assert report["summary"]["source_coverage_complete"] is True
    assert report["summary"]["n_events"] == 3
    assert report["summary"]["n_occurrences"] == 6
    assert report["summary"]["n_unresolved"] == 3

    by_kind = {event["kind"]: event for event in report["events"]}
    assert set(by_kind) == {"parser_exception", "suspicious_zero_yield", "unregistered_parser"}
    assert by_kind["parser_exception"]["observations"]["occurrences"] == 1
    assert by_kind["suspicious_zero_yield"]["observations"]["occurrences"] == 3
    assert by_kind["suspicious_zero_yield"]["observations"]["affected_devices_lower_bound"] == 3
    assert by_kind["unregistered_parser"]["observations"]["occurrences"] == 2
    assert by_kind["unregistered_parser"]["subject"]["parser"] == "[unregistered]"
    assert "parse_nat" not in {event["subject"].get("parser") for event in report["events"]}, (
        "the owner-declared may-be-empty parser must not become an unknown signal"
    )

    for event in report["events"]:
        assert event["schema"] == EVENT_SCHEMA
        assert event["id"].startswith("urn:cisco-toolkit:unknown-evidence:")
        assert event["classification"] in CLASSIFICATIONS
        assert event["classification_confidence"] == "candidate"
        assert event["disposition"] in DISPOSITIONS
        assert event["disposition"] == "needs_triage"
        assert event["privacy"] == {
            "mode": "aggregate_only",
            "raw_identifiers_included": False,
            "raw_payload_included": False,
        }


def test_raw_client_identifiers_payloads_and_unknown_tokens_never_enter_output():
    hostile_parser = "ACME-parser-admin@example.com-10.20.30.40"
    raw = _parse_source(
        {hostile_parser: _stats(1, 1, 0, 1)},
        [{
            "parser": hostile_parser,
            "device": "ACME-CORE-SECRET-01",
            "cmd": "show tenant ACME password SuperSecret 10.20.30.40",
            "file": r"C:\\Clients\\ACME\\credential-dump.txt",
            "lines_in": 99,
            "error": True,
            "exception": "SuperSecret",
        }],
    )
    report = compute_unknown_evidence(_snapshot(raw))
    encoded = json.dumps(report, sort_keys=True).casefold()

    for forbidden in (
        "acme",
        "admin@example.com",
        "10.20.30.40",
        "supersecret",
        "credential-dump",
        "clients\\\\acme",
        hostile_parser.casefold(),
    ):
        assert forbidden not in encoded
    assert report["summary"]["raw_identifiers_included"] is False
    assert report["events"][0]["subject"]["parser"] == "[unregistered]"

    # The opaque event ID must not be a hidden hash of the raw unknown token. Two
    # unrelated private tokens deliberately collapse to the same governed bucket.
    other = compute_unknown_evidence(_snapshot(_parse_source(
        {"GLOBEX-private-parser": _stats(1, 1, 0, 1)},
        [{"parser": "GLOBEX-private-parser", "device": "different-private-host",
          "cmd": "different private command", "file": "different-private-file",
          "lines_in": 7, "error": True}],
    )))
    assert report["events"][0]["id"] == other["events"][0]["id"]


def test_deterministic_under_parser_and_event_input_reordering():
    stats_a = _stats(2, 2, 2, 0)
    stats_b = _stats(1, 1, 0, 1)
    event_a = {"parser": "parse_ip_routes", "device": "z", "cmd": "ignored",
               "file": "ignored", "lines_in": 8, "error": False}
    event_b = {"parser": "parse_ip_routes", "device": "a", "cmd": "ignored",
               "file": "ignored", "lines_in": 4, "error": False}
    event_c = {"parser": "parse_bgp_table", "device": "b", "cmd": "ignored",
               "file": "ignored", "lines_in": 5, "error": True}
    first = _snapshot(_parse_source(
        {"parse_ip_routes": stats_a, "parse_bgp_table": stats_b},
        [event_a, event_b, event_c],
    ))
    second = _snapshot(_parse_source(
        {"parse_bgp_table": stats_b, "parse_ip_routes": stats_a},
        [event_c, event_b, event_a],
    ))
    second["coverage_matrix"]["rows"] = list(reversed(second["coverage_matrix"]["rows"]))
    second["architecture_coverage"]["classes"] = list(
        reversed(second["architecture_coverage"]["classes"])
    )

    assert compute_unknown_evidence(first) == compute_unknown_evidence(second)


def test_missing_empty_and_unavailable_never_render_as_observed_clean():
    missing = compute_unknown_evidence({})
    assert missing["events"] == []
    assert missing["summary"]["state"] == "incomplete"
    assert missing["summary"]["source_coverage_complete"] is False
    assert {row["state"] for row in missing["sources"]} == {"not_collected"}
    assert "universal" in missing["summary"]["note"].lower()

    no_activity = _parse_source({}, [])
    empty = compute_unknown_evidence(_snapshot(no_activity))
    assert empty["summary"]["state"] == "incomplete"
    parse_source = next(row for row in empty["sources"] if row["section"] == "parse_yield")
    assert parse_source["state"] == "observed_empty"

    healthy_parser_activity = _parse_source(
        {"parse_ip_routes": _stats(1, 0, 0, 0)},
        [],
    )
    bounded = compute_unknown_evidence(_snapshot(healthy_parser_activity))
    assert bounded["summary"]["state"] == "observed_no_unknowns"
    assert bounded["summary"]["claim_scope"] == "bounded_observed_sources_only"
    assert bounded["events"] == []

    unavailable = unavailable_unknown_evidence()
    assert unavailable["summary"]["state"] == "unavailable"
    assert unavailable["summary"]["source_coverage_complete"] is False

    # The public contract accepts any read-only Mapping, not only a mutable dict.
    readonly = compute_unknown_evidence(MappingProxyType(_snapshot(healthy_parser_activity)))
    assert readonly == bounded


def test_unregistered_axes_and_malformed_shapes_are_opaque_actionable_events():
    snap = _snapshot(_parse_source({"parse_ip_routes": _stats(1, 0, 0, 0)}, []))
    snap["architecture_coverage"]["classes"].append(
        {"key": "ACME-private-axis-10.20.30.40", "observed": True}
    )
    snap["architecture_coverage"]["summary"]["n_classes"] += 1
    snap["coverage_matrix"]["rows"].append(
        {"device": "ACME-SECRET", "axis": "private@example.com", "dimension": "architecture",
         "state": "covered", "verdict_source": "fixture", "is_abstention": False}
    )
    snap["coverage_matrix"]["rows"].append("unsupported")
    snap["coverage_matrix"]["summary"]["n_rows"] += 2

    report = compute_unknown_evidence(snap)
    kinds = {event["kind"] for event in report["events"]}
    assert {"unregistered_architecture_axis", "unregistered_coverage_axis",
            "unsupported_source_shape"} <= kinds
    encoded = json.dumps(report, sort_keys=True).casefold()
    for forbidden in ("acme", "10.20.30.40", "private@example.com", "acme-secret"):
        assert forbidden not in encoded
    assert report["summary"]["state"] == "incomplete_with_unresolved"


def test_malformed_and_contradictory_source_records_remain_visible_and_total():
    report = compute_unknown_evidence({
        "parse_yield": {
            "per_parser": {
                "parse_ip_routes": {"calls": 0, "with_content": 3,
                                    "zero_yield": 2, "errors": True},
                7: "not-a-counter-record",
            },
            "events": [
                5,
                {"parser": [], "device": "private-host"},
                {"parser": "parse_bgp_table", "device": "private-host",
                 "lines_in": -1, "error": True},
            ],
            "summary": {"parsers_called": 99, "zero_yield_suspect": -1,
                        "zero_yield_expected": 0, "parse_errors": 0},
            "events_truncated": "yes",
        },
        "coverage_matrix": "wrong-shape",
        "architecture_coverage": {"classes": [], "summary": {"n_classes": 0}},
    })
    assert report["summary"]["state"] == "incomplete_with_unresolved"
    unsupported = [event for event in report["events"]
                   if event["kind"] == "unsupported_source_shape"]
    assert {event["source"]["section"] for event in unsupported} >= {
        "parse_yield", "coverage_matrix"
    }
    parse_source = next(row for row in report["sources"] if row["section"] == "parse_yield")
    assert parse_source["state"] == "malformed"
    assert parse_source["events_truncated"] is True
    arch_source = next(row for row in report["sources"] if row["section"] == "architecture_coverage")
    assert arch_source["state"] == "partial"
    assert arch_source["registered_missing"] == len(_ARCH_COVERAGE_REGISTRY)

    # Total on every non-snapshot input; none may read as a bounded clean observation.
    for malformed in (None, [], "snapshot", 7, True):
        total = compute_unknown_evidence(malformed)
        assert total["summary"]["state"] == "incomplete"
        assert total["events"] == []


def test_uncapped_parser_counters_cannot_claim_complete_when_event_detail_is_missing():
    report = compute_unknown_evidence(_snapshot(_parse_source(
        {"parse_bgp_table": _stats(1, 1, 0, 1)},
        [],
        truncated=False,
    )))
    parse_source = next(row for row in report["sources"] if row["section"] == "parse_yield")
    assert parse_source["state"] == "malformed"
    assert parse_source["detail_complete"] is False
    kinds = {event["kind"] for event in report["events"]}
    assert {"parser_exception", "unsupported_source_shape"} <= kinds
    exception = next(event for event in report["events"] if event["kind"] == "parser_exception")
    assert exception["observations"]["detail_complete"] is False
    assert report["summary"]["source_coverage_complete"] is False


def test_catalog_and_gap_references_resolve_to_current_owners():
    report = compute_unknown_evidence(
        _snapshot(_parse_source({"parse_ip_routes": _stats(1, 1, 1, 0)}, [
            {"parser": "parse_ip_routes", "device": "discard", "cmd": "discard",
             "file": "discard", "lines_in": 3, "error": False}
        ]))
    )
    catalog = json.loads((ROOT / "master-reference/content/capability-catalog.json").read_text(encoding="utf-8"))
    governance = json.loads((ROOT / "master-reference/content/delivery-governance.json").read_text(encoding="utf-8"))
    capability_ids = {
        entry["id"]
        for domain in catalog["domains"]
        for entry in domain["entries"]
    }
    gap_ids = {gap["id"] for gap in governance["gaps"]}
    assert report["events"], "fixture must produce a real event before checking its references"
    for event in report["events"]:
        assert set(event["capability_refs"]) <= capability_ids
        assert set(event["gap_refs"]) <= gap_ids
