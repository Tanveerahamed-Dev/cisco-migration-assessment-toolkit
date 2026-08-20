"""Canonical traffic-assurance contract and coverage-honesty counterexamples."""

from __future__ import annotations

import copy
import json
import textwrap
from hashlib import sha256

import pytest

from cisco_toolkit import cutover_sim, fib, parse, traffic_assurance
from cisco_toolkit.build import ScopedRouteProjection, scope_routes
from cisco_toolkit.textutils import safe_fs_name


ANY = {"ip": "0.0.0.0", "wild": "255.255.255.255"}


def _rule(action: str, *, sport: int | None = None, dport: int | None = None) -> dict:
    return {
        "action": action,
        "proto": "tcp",
        "src": ANY,
        "dst": ANY,
        "sport": {"op": "eq", "val": sport} if sport is not None else None,
        "dport": {"op": "eq", "val": dport} if dport is not None else None,
        "raw": f"{action} tcp any any",
    }


def _capture_integrity_for(inventory: dict, findings: list[dict] | None = None) -> dict:
    rows = findings or []
    statuses = {(row["host"], row["command"]): row["status"] for row in rows}
    return {
        "findings": rows,
        "inspections": [
            {"host": host, "command": command,
             "status": statuses.get((host, command), "ok")}
            for host, commands in sorted(inventory.items())
            for command in sorted(commands)
        ],
        "summary": {"n_findings": len(rows)},
    }


def _empty_binding_sections(*hosts: str) -> dict:
    return {
        section: {host: {} for host in hosts}
        for section in ("interfaces", "acls", "object_groups", "nat")
    }


def _with_custody(snap: dict, findings: list[dict] | None = None) -> dict:
    for section in ("interfaces", "acls", "object_groups", "nat"):
        snap.setdefault(section, {})
    for ports in (snap.get("interfaces") or {}).values():
        for record in (ports or {}).values():
            if isinstance(record, dict):
                record.setdefault("run_config_observed", True)
                if record.get("mtu") not in (None, "") and record.get("ip_mtu") in (None, "") \
                        and record.get("link_mtu") in (None, ""):
                    record.setdefault("mtu_semantics", "effective_ipv4_mtu")
    for host, rows in list((snap.get("routes") or {}).items()):
        if isinstance(rows, ScopedRouteProjection) \
                and isinstance(rows.projection_receipt.get("source_parse_receipt"), dict) \
                and traffic_assurance._route_projection_cell(rows).get("status") in {
                    "ok", "route_parse_incomplete",
                }:
            continue
        route_db: dict = {}
        scope: set[str] = set()
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict) or not isinstance(row.get("prefix"), str):
                continue
            prefix = row["prefix"]
            route_db.setdefault(prefix, {"entries": []})["entries"].append(dict(row))
            scope.add(prefix)
        parsed_route_db = parse.ParsedRouteTable(route_db)
        n_entries = sum(len(info["entries"]) for info in route_db.values())
        encoded = json.dumps(
            dict(parsed_route_db), ensure_ascii=True, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        parsed_route_db.parse_receipt = {
            "schema": "route_parse_receipt/1",
            "complete": True,
            "candidate_rows": n_entries,
            "parsed_rows": n_entries,
            "unparsed_candidate_rows": 0,
            "malformed_candidate_rows": 0,
            "unexplained_candidate_rows": 0,
            "ios_candidate_rows": n_entries,
            "ios_parsed_rows": n_entries,
            "ios_unparsed_rows": 0,
            "nxos_prefix_blocks": 0,
            "nxos_expected_ubest_rows": 0,
            "nxos_via_candidate_rows": 0,
            "nxos_parsed_via_rows": 0,
            "nxos_unparsed_via_rows": 0,
            "nxos_denominator_mismatch_blocks": 0,
            "nxos_malformed_prefix_blocks": 0,
            "ios_malformed_subnet_headers": 0,
            "route_prefix_count": len(parsed_route_db),
            "route_entry_count": n_entries,
            "routes_sha256": sha256(encoded).hexdigest(),
            "incomplete_reasons": [],
        }
        snap["routes"][host] = scope_routes(parsed_route_db, scope)
    hosts = sorted(set((snap.get("routes") or {})) | set((snap.get("interfaces") or {})))
    # Production builders publish an explicit per-host owner map even when a parser yields no rows. Preserve that
    # distinction in synthetic custody: a missing or non-dict host envelope is malformed, not proven empty.
    for section in ("interfaces", "acls", "object_groups", "nat"):
        owner = snap.get(section)
        if isinstance(owner, dict):
            for host in hosts:
                owner.setdefault(host, {})
    inventory = {
        host: {"show running-config": "synthetic.cfg",
               "show running-config | section ^interface": "synthetic.interfaces",
               "show ip route": "synthetic.route"}
        for host in hosts
    }
    n = len(hosts)
    parser_names = (
        "parse_run_config_interfaces", "parse_acls", "parse_object_groups", "parse_nat",
        "parse_ip_routes",
    )
    parse_yield = {
        "per_parser": {
            name: {
                "calls": 2 * n if name == "parse_run_config_interfaces" else n,
                "with_content": 2 * n if name == "parse_run_config_interfaces" else n,
                "zero_yield": 0,
                "errors": 0,
            }
            for name in parser_names
        },
        "events": [],
        "events_truncated": False,
        "receipts": [
            {"parser": parser, "device": safe_fs_name(host), "cmd": command,
             "calls": 1, "with_entities": 1, "zero_yield": 0, "errors": 0}
            for host in hosts
            for parser, command in (
                ("parse_acls", "show running-config"),
                ("parse_object_groups", "show running-config"),
                ("parse_nat", "show running-config"),
                ("parse_run_config_interfaces", "show running-config"),
                ("parse_run_config_interfaces", "show running-config | section ^interface"),
                ("parse_ip_routes", "show ip route"),
            )
        ],
    }
    snap["traffic_evidence_custody"] = traffic_assurance.build_traffic_evidence_custody(
        inventory, _capture_integrity_for(inventory, findings), parse_yield, snap.get("routes"),
        {"interfaces": snap.get("interfaces") or {}, "acls": snap.get("acls") or {},
         "object_groups": snap.get("object_groups") or {}, "nat": snap.get("nat") or {}},
    )
    return snap


def _symmetric_snapshot() -> dict:
    """Two routed access networks with an exact, observed return path and interface evidence."""
    return _with_custody({
        "routes": {
            "R1": [
                {"prefix": "10.1.1.0/24", "source": "connected", "out_intf": "Vlan10"},
                {"prefix": "10.0.12.0/30", "source": "connected", "out_intf": "Gi0/1"},
                {"prefix": "10.2.2.0/24", "source": "static", "next_hop": "10.0.12.2", "out_intf": "Gi0/1"},
            ],
            "R2": [
                {"prefix": "10.0.12.0/30", "source": "connected", "out_intf": "Gi0/1"},
                {"prefix": "10.2.2.0/24", "source": "connected", "out_intf": "Vlan20"},
                {"prefix": "10.1.1.0/24", "source": "static", "next_hop": "10.0.12.1", "out_intf": "Gi0/1"},
            ],
        },
        "interfaces": {
            "R1": {
                "Vlan10": {"mtu": 1500, "acl_in": "CLIENT-IN", "acl_out": "",
                           "run_config_observed": True},
                "Gi0/1": {"mtu": 1500, "acl_in": "", "acl_out": "",
                          "run_config_observed": True, "svi_ip": "10.0.12.1/30"},
            },
            "R2": {
                "Gi0/1": {"mtu": 1500, "acl_in": "", "acl_out": "",
                          "run_config_observed": True, "svi_ip": "10.0.12.2/30"},
                "Vlan20": {"mtu": 1500, "acl_in": "", "acl_out": "",
                           "run_config_observed": True},
            },
        },
        "acls": {"R1": {"CLIENT-IN": [_rule("permit", dport=443)]}},
        "object_groups": {},
    })


def _intent(**overrides) -> dict:
    row = {
        "id": "traffic.web",
        "src": "10.1.1.10",
        "dst": "10.2.2.20",
        "protocol": "tcp",
        "src_port": 40000,
        "dst_port": 443,
        "expected": "permit",
        "return_required": True,
        "required_mtu": 1500,
    }
    row.update(overrides)
    return row


def test_exact_symmetric_flow_is_proven_from_one_canonical_result():
    result = traffic_assurance.assess_flow(_symmetric_snapshot(), _intent())

    assert result["schema"] == "traffic_assurance/1"
    assert result["owner"] == "cisco_toolkit.traffic_assurance.assess_flow"
    assert result["valid"] is True and result["supported"] is True
    assert result["verdict"] == "proven"
    assert result["dimensions"]["path"]["forward"]["state"] == "reached"
    assert result["dimensions"]["path"]["reverse"]["state"] == "reached"
    assert result["dimensions"]["policy"]["forward"]["verdict"] == "proven"
    assert result["dimensions"]["policy"]["reverse"]["verdict"] == "proven"
    assert result["dimensions"]["mtu"]["forward"]["observed_min"] == 1500
    assert result["dimensions"]["ecmp"]["forward"]["native_verdict"] == "not_ecmp"
    assert result["nrfu_test_ids"] == ["NRFU-traffic.web-FORWARD", "NRFU-traffic.web-RETURN"]


def test_stateless_acl_deny_refutes_a_requested_permit():
    snap = _symmetric_snapshot()
    snap["acls"]["R1"]["CLIENT-IN"] = [_rule("deny", dport=443)]
    _with_custody(snap)

    result = traffic_assurance.assess_flow(snap, _intent())

    assert result["verdict"] == "refuted"
    stage = result["dimensions"]["policy"]["forward"]["stages"][0]
    assert stage["acl"] == "CLIENT-IN"
    assert stage["native_result"] == "PROVEN_NONE"
    assert stage["verdict"] == "refuted"


def test_sparse_interface_record_does_not_invent_an_observed_absent_acl():
    snap = _symmetric_snapshot()
    snap["interfaces"]["R1"]["Gi0/1"].pop("acl_out")
    _with_custody(snap)

    result = traffic_assurance.assess_flow(snap, _intent())

    assert result["verdict"] == "indeterminate"
    stage = next(
        row for row in result["dimensions"]["policy"]["forward"]["stages"]
        if row["host"] == "R1" and row["interface"] == "Gi0/1" and row["direction"] == "out"
    )
    assert stage["verdict"] == "not_observed"

    unobserved = _symmetric_snapshot()
    unobserved["interfaces"]["R1"]["Vlan10"]["run_config_observed"] = False
    _with_custody(unobserved)
    unobserved_result = traffic_assurance.assess_flow(unobserved, _intent())
    unobserved_stage = unobserved_result["dimensions"]["policy"]["forward"]["stages"][0]
    assert unobserved_result["verdict"] == "indeterminate"
    assert unobserved_stage["verdict"] == "not_observed"
    assert "not positively observed" in unobserved_stage["detail"]
    assert stage["detail"] == "acl_out attachment field was not collected"

    for malformed in (False, True, 17, 4.5):
        broken = _symmetric_snapshot()
        broken["interfaces"]["R1"]["Gi0/1"]["acl_out"] = malformed
        _with_custody(broken)
        assessed = traffic_assurance.assess_flow(broken, _intent())
        assert assessed["verdict"] == "indeterminate"
        bad_stage = next(
            row for row in assessed["dimensions"]["policy"]["forward"]["stages"]
            if row["host"] == "R1" and row["interface"] == "Gi0/1" and row["direction"] == "out"
        )
        assert bad_stage["detail"] == "ACL attachment value is malformed"


def test_conflicting_normalized_interface_aliases_abstain_independent_of_order():
    base = _symmetric_snapshot()
    blank = {"mtu": 1500, "acl_in": "", "acl_out": ""}
    blocked = {"mtu": 1500, "acl_in": "", "acl_out": "BLOCK"}
    base["acls"]["R1"]["BLOCK"] = [_rule("deny", dport=443)]

    verdicts = []
    for records in (
        {"Gi0/1": blank, "GigabitEthernet0/1": blocked},
        {"GigabitEthernet0/1": blocked, "Gi0/1": blank},
    ):
        snap = copy.deepcopy(base)
        snap["interfaces"]["R1"].update(records)
        _with_custody(snap)
        result = traffic_assurance.assess_flow(snap, _intent())
        stage = next(
            row for row in result["dimensions"]["policy"]["forward"]["stages"]
            if row["host"] == "R1" and row["direction"] == "out"
        )
        assert "multiple conflicting interface records" in stage["detail"]
        verdicts.append(result["verdict"])
    assert verdicts == ["indeterminate", "indeterminate"]


def test_stateful_return_acl_abstains_without_observed_connection_state():
    snap = _symmetric_snapshot()
    snap["interfaces"]["R2"]["Vlan20"]["acl_in"] = "RETURN-IN"
    snap["acls"]["R2"] = {
        "RETURN-IN": [{**_rule("permit", sport=443), "established": True}]
    }
    _with_custody(snap)

    result = traffic_assurance.assess_flow(snap, _intent())

    assert result["verdict"] == "indeterminate"
    reverse = result["dimensions"]["policy"]["reverse"]
    assert reverse["verdict"] == "indeterminate"
    stage = next(row for row in reverse["stages"] if row["acl"] == "RETURN-IN")
    assert stage["native_result"] == "INDETERMINATE"
    assert "connection state was not observed" in stage["detail"]


def test_observed_discard_can_prove_denial_but_scoped_absence_cannot():
    observed = _symmetric_snapshot()
    observed["routes"]["R1"][-1] = {
        "prefix": "10.2.2.0/24", "source": "static", "next_hop": "", "out_intf": "Null0"
    }
    _with_custody(observed)
    denied = traffic_assurance.assess_flow(
        observed, _intent(expected="deny", return_required=False, required_mtu=None)
    )
    assert denied["verdict"] == "proven"
    assert denied["dimensions"]["path"]["forward"]["drop_evidence"] == "observed_discard"

    scoped = _symmetric_snapshot()
    scoped["routes"]["R1"] = scoped["routes"]["R1"][:-1]
    _with_custody(scoped)
    unknown = traffic_assurance.assess_flow(
        scoped, _intent(expected="deny", return_required=False, required_mtu=None)
    )
    assert unknown["verdict"] == "indeterminate"
    assert unknown["dimensions"]["path"]["forward"]["state"] == "no_route_in_scoped_projection"
    assert unknown["dimensions"]["path"]["forward"]["drop_evidence"] == "no_route_observed"


def test_ambiguous_owner_drop_evidence_is_weakened_by_any_absence_derived_candidate():
    snap = {
        "routes": {
            "A": [
                {"prefix": "10.1.1.0/24", "source": "connected", "out_intf": "Vlan10"},
                {"prefix": "10.9.9.0/24", "source": "static", "next_hop": "", "out_intf": "Null0"},
            ],
            "B": [
                {"prefix": "10.1.1.0/24", "source": "connected", "out_intf": "Vlan10"},
                {"prefix": "192.0.2.0/30", "source": "connected", "out_intf": "Gi0/1"},
            ],
        },
        "interfaces": {}, "acls": {}, "object_groups": {},
    }
    trace = fib.trace_fib_path(snap, "10.1.1.10", "10.9.9.20", disclose=True)
    assert trace["status"] == "computed:unreachable"
    assert trace["drop_evidence"] == "no_route_observed"

    result = traffic_assurance.assess_flow(
        _with_custody(snap),
        _intent(dst="10.9.9.20", expected="deny", return_required=False, required_mtu=None)
    )
    assert result["verdict"] == "indeterminate"


def test_scoped_reverse_absence_cannot_become_definitive_asymmetry_or_a_proven_path_claim():
    snap = _symmetric_snapshot()
    snap["routes"]["R2"] = snap["routes"]["R2"][:-1]
    _with_custody(snap)

    trace = fib.trace_bidirectional(snap, "10.1.1.10", "10.2.2.20", disclose=True)
    assert trace["forward"]["reached"] is True
    assert trace["reverse"]["drop_evidence"] == "no_route_observed"
    assert trace["rpf_verdict"] == "INDETERMINATE"
    assert "not positive drop evidence" in trace["asymmetry"][0]

    result = traffic_assurance.assess_flow(snap, _intent())
    assert result["verdict"] == "indeterminate"
    path_claim = next(
        claim for claim in result["claims"]
        if claim["predicate"] == "selected_rib_forwarding_projection"
    )
    assert path_claim["directions"] == ["forward", "reverse"]
    assert path_claim["verdict"] == "not_observed"


def test_ambiguous_reaching_next_hop_candidates_force_branch_incomplete_assurance():
    snap = {
        "routes": {
            "S": [
                {"prefix": "10.1.1.0/24", "source": "connected", "out_intf": "Vlan10"},
                {"prefix": "10.0.0.0/24", "source": "connected", "out_intf": "Gi0/1"},
                {"prefix": "10.9.9.0/24", "source": "static", "next_hop": "10.0.0.2", "out_intf": "Gi0/1"},
            ],
            "A": [
                {"prefix": "10.0.0.0/24", "source": "connected", "out_intf": "Gi0/1"},
                {"prefix": "10.9.9.0/24", "source": "connected", "out_intf": "Vlan90"},
            ],
            "B": [
                {"prefix": "10.0.0.0/24", "source": "connected", "out_intf": "Gi0/1"},
                {"prefix": "10.9.9.0/24", "source": "connected", "out_intf": "Vlan90"},
            ],
        },
        "interfaces": {
            "S": {
                "Vlan10": {"mtu": 1500, "acl_in": "", "acl_out": ""},
                "Gi0/1": {"mtu": 1500, "acl_in": "", "acl_out": "", "svi_ip": "10.0.0.1/24"},
            },
            "A": {
                "Gi0/1": {"mtu": 1500, "acl_in": "", "acl_out": "", "svi_ip": "10.0.0.2/24"},
                "Vlan90": {"mtu": 1500, "acl_in": "", "acl_out": ""},
            },
            "B": {
                "Gi0/1": {"mtu": 1500, "acl_in": "BLOCK", "acl_out": "", "svi_ip": "10.0.0.2/24"},
                "Vlan90": {"mtu": 1500, "acl_in": "", "acl_out": ""},
            },
        },
        "acls": {"B": {"BLOCK": [_rule("deny", dport=443)]}},
        "object_groups": {},
    }
    result = traffic_assurance.assess_flow(
        _with_custody(snap), _intent(dst="10.9.9.20", return_required=False, required_mtu=None)
    )
    assert result["dimensions"]["path"]["forward"]["ambiguous_candidate_sets"] == [
        {"kind": "ambiguous_next_hop", "candidate_hosts": ["A", "B"]}
    ]
    assert result["dimensions"]["policy"]["forward"]["branch_complete"] is False
    assert result["dimensions"]["ecmp"]["forward"]["verdict"] == "indeterminate"
    assert result["verdict"] == "indeterminate"

    selected_denied = copy.deepcopy(snap)
    selected_denied["interfaces"]["B"]["Gi0/1"]["acl_in"] = ""
    selected_denied["interfaces"]["A"]["Gi0/1"]["acl_in"] = "BLOCK"
    selected_denied["acls"] = {"A": {"BLOCK": [_rule("deny", dport=443)]}}
    _with_custody(selected_denied)
    selected_result = traffic_assurance.assess_flow(
        selected_denied, _intent(dst="10.9.9.20", return_required=False, required_mtu=None)
    )
    selected_policy = selected_result["dimensions"]["policy"]["forward"]
    assert selected_policy["selected_path_verdict"] == "refuted"
    assert selected_policy["verdict"] == "indeterminate"
    assert selected_result["verdict"] == "indeterminate"


def _ecmp_blackhole_snapshot() -> dict:
    snap = {
        "routes": {
            "R1": [
                {"prefix": "10.1.1.0/24", "source": "connected", "out_intf": "Vlan10"},
                {"prefix": "10.0.12.0/30", "source": "connected", "out_intf": "Gi0/1"},
                {"prefix": "10.0.13.0/30", "source": "connected", "out_intf": "Gi0/2"},
                {"prefix": "10.2.2.0/24", "source": "ospf", "next_hop": "10.0.12.2", "out_intf": "Gi0/1"},
                {"prefix": "10.2.2.0/24", "source": "ospf", "next_hop": "10.0.13.2", "out_intf": "Gi0/2"},
            ],
            "R2": [
                {"prefix": "10.0.12.0/30", "source": "connected", "out_intf": "Gi0/1"},
                {"prefix": "10.2.2.0/24", "source": "connected", "out_intf": "Vlan20"},
            ],
            "R3": [
                {"prefix": "10.0.13.0/30", "source": "connected", "out_intf": "Gi0/1"},
                {"prefix": "10.2.2.0/24", "source": "static", "next_hop": "", "out_intf": "Null0"},
            ],
        },
        "interfaces": {
            "R1": {
                "Vlan10": {"mtu": 1500, "acl_in": "", "acl_out": ""},
                "Gi0/1": {"mtu": 1500, "acl_in": "", "acl_out": "", "svi_ip": "10.0.12.1/30"},
                "Gi0/2": {"mtu": 1500, "acl_in": "", "acl_out": "", "svi_ip": "10.0.13.1/30"},
            },
            "R2": {
                "Gi0/1": {"mtu": 1500, "acl_in": "", "acl_out": "", "svi_ip": "10.0.12.2/30"},
                "Vlan20": {"mtu": 1500, "acl_in": "", "acl_out": ""},
            },
            "R3": {"Gi0/1": {"mtu": 1500, "acl_in": "", "acl_out": "", "svi_ip": "10.0.13.2/30"}},
        },
        "acls": {},
        "object_groups": {},
    }
    return _with_custody(snap)


def _downstream_ecmp_snapshot(*, alternate_drop: bool = False, alternate_absence: bool = False,
                              alternate_acl_deny: bool = False) -> dict:
    r4_destination = None if alternate_absence else (
        {"prefix": "10.9.9.0/24", "source": "static", "next_hop": "", "out_intf": "Null0"}
        if alternate_drop else
        {"prefix": "10.9.9.0/24", "source": "connected", "out_intf": "Vlan90"}
    )
    snap = {
        "routes": {
            "R1": [
                {"prefix": "10.1.1.0/24", "source": "connected", "out_intf": "Vlan10"},
                {"prefix": "10.0.12.0/30", "source": "connected", "out_intf": "Gi0/1"},
                {"prefix": "10.9.9.0/24", "source": "static", "next_hop": "10.0.12.2", "out_intf": "Gi0/1"},
            ],
            "R2": [
                {"prefix": "10.0.12.0/30", "source": "connected", "out_intf": "Gi0/1"},
                {"prefix": "10.0.23.0/30", "source": "connected", "out_intf": "Gi0/2"},
                {"prefix": "10.0.24.0/30", "source": "connected", "out_intf": "Gi0/3"},
                {"prefix": "10.9.9.0/24", "source": "ospf", "next_hop": "10.0.23.2", "out_intf": "Gi0/2"},
                {"prefix": "10.9.9.0/24", "source": "ospf", "next_hop": "10.0.24.2", "out_intf": "Gi0/3"},
            ],
            "R3": [
                {"prefix": "10.0.23.0/30", "source": "connected", "out_intf": "Gi0/1"},
                {"prefix": "10.9.9.0/24", "source": "connected", "out_intf": "Vlan90"},
            ],
            "R4": [
                {"prefix": "10.0.24.0/30", "source": "connected", "out_intf": "Gi0/1"},
            ] + ([r4_destination] if r4_destination is not None else []),
        },
        "interfaces": {
            "R1": {
                "Vlan10": {"mtu": 1500, "acl_in": "", "acl_out": ""},
                "Gi0/1": {"mtu": 1500, "acl_in": "", "acl_out": "", "svi_ip": "10.0.12.1/30"},
            },
            "R2": {
                "Gi0/1": {"mtu": 1500, "acl_in": "", "acl_out": "", "svi_ip": "10.0.12.2/30"},
                "Gi0/2": {"mtu": 1500, "acl_in": "", "acl_out": "", "svi_ip": "10.0.23.1/30"},
                "Gi0/3": {"mtu": 1500, "acl_in": "", "acl_out": "", "svi_ip": "10.0.24.1/30"},
            },
            "R3": {
                "Gi0/1": {"mtu": 1500, "acl_in": "", "acl_out": "", "svi_ip": "10.0.23.2/30"},
                "Vlan90": {"mtu": 1500, "acl_in": "", "acl_out": ""},
            },
            "R4": {
                "Gi0/1": {"mtu": 1500, "acl_in": "ALT-DENY" if alternate_acl_deny else "", "acl_out": "",
                          "svi_ip": "10.0.24.2/30"},
                "Vlan90": {"mtu": 1500, "acl_in": "", "acl_out": ""},
            },
        },
        "acls": {"R4": {"ALT-DENY": [_rule("deny", dport=443)]}} if alternate_acl_deny else {},
        "object_groups": {},
    }
    return _with_custody(snap)


def test_ecmp_blackhole_and_mtu_shortfall_are_hard_refutations():
    ecmp = traffic_assurance.assess_flow(
        _ecmp_blackhole_snapshot(), _intent(return_required=False, required_mtu=None)
    )
    assert ecmp["dimensions"]["path"]["forward"]["verdict"] == "proven"
    assert ecmp["dimensions"]["ecmp"]["forward"]["native_verdict"] == "inconsistent"
    path_claim = next(claim for claim in ecmp["claims"] if claim["id"].endswith(".path"))
    assert path_claim["verdict"] == "refuted"
    assert ecmp["verdict"] == "refuted"

    narrow = _symmetric_snapshot()
    narrow["interfaces"]["R2"]["Vlan20"]["mtu"] = 1400
    _with_custody(narrow)
    mtu = traffic_assurance.assess_flow(narrow, _intent())
    assert mtu["dimensions"]["mtu"]["forward"]["verdict"] == "refuted"
    assert mtu["verdict"] == "refuted"


def test_missing_egress_interface_withholds_the_canonical_mtu_verdict():
    snap = _symmetric_snapshot()
    snap["routes"]["R1"][2]["out_intf"] = ""
    _with_custody(snap)

    result = traffic_assurance.assess_flow(
        snap, _intent(return_required=False, required_mtu=1400),
    )
    forward = result["dimensions"]["mtu"]["forward"]

    assert forward["verdict"] == "not_observed"
    assert {
        "host": "R1", "out_intf": "", "reason": "egress_interface_not_observed",
    } in forward["unobserved_hops"]
    assert forward["provenance_gaps"] == [{
        "host": "R1", "interface": None,
        "reason": "egress interface was not observed for this routed hop",
    }]
    assert result["verdict"] == "indeterminate"


@pytest.mark.parametrize("more_specific_out,covering_out", [("Null0", "Gi0/1"), ("Gi0/1", "Null0")])
def test_malformed_route_preference_cannot_invert_a_hard_path_verdict(
        more_specific_out, covering_out):
    snap = _symmetric_snapshot()
    snap["routes"]["R1"] = [
        {"prefix": "10.1.1.0/24", "source": "connected", "out_intf": "Vlan10"},
        {"prefix": "10.0.12.0/30", "source": "connected", "out_intf": "Gi0/1"},
        {"prefix": "10.2.2.0/24", "source": "static", "next_hop": "10.0.12.2",
         "out_intf": covering_out, "admin_distance": 1},
        {"prefix": "10.2.2.0/25", "source": "static",
         "next_hop": "10.0.12.2" if more_specific_out != "Null0" else "",
         "out_intf": more_specific_out, "admin_distance": {"malformed": True}},
    ]
    _with_custody(snap)

    result = traffic_assurance.assess_flow(
        snap, _intent(return_required=False, required_mtu=None),
    )

    assert result["dimensions"]["path"]["forward"]["status"] == (
        "lower_bound:malformed_route_evidence"
    )
    assert result["dimensions"]["path"]["forward"]["verdict"] == "not_observed"
    assert result["verdict"] == "indeterminate"


@pytest.mark.parametrize("valid_out,unknown_out", [("Gi0/1", "Null0"), ("Null0", "Gi0/1")])
def test_unknown_route_source_without_observed_distance_cannot_invert_verdict(
        valid_out, unknown_out):
    snap = _symmetric_snapshot()
    snap["routes"]["R1"] = [
        {"prefix": "10.1.1.0/24", "source": "connected", "out_intf": "Vlan10"},
        {"prefix": "10.0.12.0/30", "source": "connected", "out_intf": "Gi0/1"},
        {"prefix": "10.2.2.0/24", "source": "static",
         "next_hop": "10.0.12.2" if valid_out != "Null0" else "", "out_intf": valid_out},
        {"prefix": "10.2.2.0/24", "source": "unknown-new-code",
         "next_hop": "10.0.12.2" if unknown_out != "Null0" else "", "out_intf": unknown_out},
    ]
    _with_custody(snap)

    result = traffic_assurance.assess_flow(
        snap, _intent(return_required=False, required_mtu=None),
    )

    assert result["dimensions"]["path"]["forward"]["status"] == (
        "lower_bound:malformed_route_evidence"
    )
    assert result["verdict"] == "indeterminate"


@pytest.mark.parametrize(
    ("host", "interface", "field"),
    [
        ("R3", "Gi0/1", "pbr_policy"),
        ("R3", "Gi0/1", "acl_in_unmodeled"),
        ("R3", "Gi0/1", "crypto_map"),
        ("R3", "Gi0/1", "tunnel_protection"),
        ("R3", "Gi0/1", "vacl_policy"),
        ("R1", "Gi0/2", "crypto_map"),
        ("R1", "Gi0/2", "tunnel_protection"),
    ],
)
def test_ecmp_drop_abstains_when_an_alternate_leg_has_an_unmodeled_forwarding_override(
        host, interface, field):
    snap = _ecmp_blackhole_snapshot()
    snap["interfaces"][host][interface][field] = "CONFIGURED"
    _with_custody(snap)

    result = traffic_assurance.assess_flow(
        snap, _intent(return_required=False, required_mtu=None)
    )

    ecmp = result["dimensions"]["ecmp"]["forward"]
    assert ecmp["native_verdict"] == "inconsistent"
    assert ecmp["selected_rib_observed_dropping_legs"]
    assert ecmp["observed_dropping_legs"] == []
    assert ecmp["dropping_leg_gate_gaps"]
    assert ecmp["verdict"] == "indeterminate"
    path_claim = next(claim for claim in result["claims"] if claim["id"].endswith(".path"))
    assert path_claim["verdict"] == "indeterminate"
    assert result["verdict"] == "indeterminate"


def test_ecmp_drop_is_not_globally_tainted_by_an_unrelated_interface_gate():
    snap = _ecmp_blackhole_snapshot()
    snap["interfaces"]["R1"]["Loopback99"] = {
        "mtu": 1500, "acl_in": "", "acl_out": "", "pbr_policy": "UNRELATED",
        "run_config_observed": True,
    }
    _with_custody(snap)

    result = traffic_assurance.assess_flow(
        snap, _intent(return_required=False, required_mtu=None)
    )

    assert result["dimensions"]["ecmp"]["forward"]["verdict"] == "refuted"
    assert result["dimensions"]["ecmp"]["forward"]["dropping_leg_gate_gaps"] == []
    assert result["verdict"] == "refuted"


@pytest.mark.parametrize("expected", ["permit", "deny"])
def test_all_ecmp_drops_abstain_when_an_alternate_branch_can_override_the_rib(expected):
    snap = _ecmp_blackhole_snapshot()
    snap["routes"]["R2"][-1] = {
        "prefix": "10.2.2.0/24", "source": "static", "next_hop": "", "out_intf": "Null0",
    }
    snap["interfaces"]["R3"]["Gi0/1"]["pbr_policy"] = "DIVERT"
    _with_custody(snap)

    result = traffic_assurance.assess_flow(
        snap,
        _intent(expected=expected, return_required=False, required_mtu=None),
    )

    path = result["dimensions"]["path"]["forward"]
    assert path["selected_projection_verdict"] == "refuted"
    assert path["verdict"] == "indeterminate"
    assert result["dimensions"]["ecmp"]["forward"]["verdict"] == "indeterminate"
    path_claim = next(claim for claim in result["claims"] if claim["id"].endswith(".path"))
    assert path_claim["verdict"] == "indeterminate"
    assert result["verdict"] == "indeterminate"


@pytest.mark.parametrize(
    "command",
    ["show running-config", "show running-config | section ^interface"],
)
def test_selected_rib_reachability_requires_full_and_scoped_forwarding_config_custody(command):
    snap = _symmetric_snapshot()
    _with_custody(snap, findings=[{
        "host": "R1", "command": command, "status": "incomplete",
    }])

    result = traffic_assurance.assess_flow(
        snap, _intent(return_required=False, required_mtu=None)
    )

    path = result["dimensions"]["path"]["forward"]
    ecmp = result["dimensions"]["ecmp"]["forward"]
    claim = next(claim for claim in result["claims"] if claim["id"].endswith(".path"))
    assert path["selected_projection_verdict"] == "proven"
    assert path["verdict"] == "indeterminate"
    assert ecmp["selected_rib_verdict"] == "proven"
    assert ecmp["verdict"] == "indeterminate"
    assert claim["verdict"] == "indeterminate"
    assert result["verdict"] == "indeterminate"


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("show running-config", "permit"),
        ("show running-config", "deny"),
        ("show running-config | section ^interface", "permit"),
        ("show running-config | section ^interface", "deny"),
    ],
)
def test_selected_null_route_cannot_decide_either_expectation_without_config_custody(
        command, expected):
    snap = _symmetric_snapshot()
    snap["routes"]["R1"][-1] = {
        "prefix": "10.2.2.0/24", "source": "static", "next_hop": "", "out_intf": "Null0",
    }
    _with_custody(snap, findings=[{
        "host": "R1", "command": command, "status": "incomplete",
    }])

    result = traffic_assurance.assess_flow(
        snap,
        _intent(
            expected=expected,
            return_required=False,
            required_mtu=None,
        ),
    )

    path = result["dimensions"]["path"]["forward"]
    claim = next(claim for claim in result["claims"] if claim["id"].endswith(".path"))
    assert path["selected_projection_verdict"] == "refuted"
    assert path["verdict"] == "indeterminate"
    assert claim["verdict"] == "indeterminate"
    assert result["verdict"] == "indeterminate"


def test_scoped_projection_preserves_more_specific_lpm_in_both_polarities():
    scope = {"10.1.1.0/24", "10.0.12.0/30", "10.2.2.0/24"}

    live_specific = _symmetric_snapshot()
    live_specific["routes"]["R1"] = scope_routes({
        "10.1.1.0/24": {"entries": [
            {"prefix": "10.1.1.0/24", "source": "connected", "out_intf": "Vlan10"},
        ]},
        "10.0.12.0/30": {"entries": [
            {"prefix": "10.0.12.0/30", "source": "connected", "out_intf": "Gi0/1"},
        ]},
        "10.2.2.0/24": {"entries": [
            {"prefix": "10.2.2.0/24", "source": "static", "out_intf": "Null0"},
        ]},
        "10.2.2.0/25": {"entries": [
            {"prefix": "10.2.2.0/25", "source": "static", "next_hop": "10.0.12.2",
             "out_intf": "Gi0/1"},
        ]},
    }, scope)
    live_specific = _with_custody(live_specific)
    live_result = traffic_assurance.assess_flow(live_specific, _intent())
    assert live_result["dimensions"]["path"]["forward"]["verdict"] == "proven"
    assert live_result["verdict"] == "proven"

    discard_specific = _symmetric_snapshot()
    discard_specific["routes"]["R1"] = scope_routes({
        "10.1.1.0/24": {"entries": [
            {"prefix": "10.1.1.0/24", "source": "connected", "out_intf": "Vlan10"},
        ]},
        "10.0.12.0/30": {"entries": [
            {"prefix": "10.0.12.0/30", "source": "connected", "out_intf": "Gi0/1"},
        ]},
        "10.2.2.0/24": {"entries": [
            {"prefix": "10.2.2.0/24", "source": "static", "next_hop": "10.0.12.2",
             "out_intf": "Gi0/1"},
        ]},
        "10.2.2.0/25": {"entries": [
            {"prefix": "10.2.2.0/25", "source": "static", "out_intf": "Null0"},
        ]},
    }, scope)
    discard_specific = _with_custody(discard_specific)
    discard_result = traffic_assurance.assess_flow(discard_specific, _intent())
    assert discard_result["dimensions"]["path"]["forward"]["verdict"] == "refuted"
    assert discard_result["verdict"] == "refuted"


def test_canonical_assurance_selects_observed_ospf_ad_over_ibgp_default_family_guess():
    parsed = parse.parse_ip_routes("""
B 10.2.2.0/24 [200/0] via 10.0.13.3, Gi0/2
O 10.2.2.0/24 [110/20] via 10.0.12.2, Gi0/1
""")["10.2.2.0/24"]["entries"]
    snap = _symmetric_snapshot()
    snap["routes"]["R1"] = [
        {"prefix": "10.1.1.0/24", "source": "connected", "out_intf": "Vlan10"},
        {"prefix": "10.0.12.0/30", "source": "connected", "out_intf": "Gi0/1"},
        {"prefix": "10.0.13.0/30", "source": "connected", "out_intf": "Gi0/2"},
        *parsed,
    ]
    snap["routes"]["R3"] = [
        {"prefix": "10.0.13.0/30", "source": "connected", "out_intf": "Gi0/1"},
        {"prefix": "10.2.2.0/24", "source": "static", "out_intf": "Null0"},
    ]
    snap["interfaces"]["R1"]["Gi0/2"] = {
        "mtu": 1500, "acl_in": "", "acl_out": "", "run_config_observed": True,
        "svi_ip": "10.0.13.1/30",
    }
    snap["interfaces"]["R3"] = {
        "Gi0/1": {"mtu": 1500, "acl_in": "", "acl_out": "", "run_config_observed": True,
                  "svi_ip": "10.0.13.3/30"},
    }
    snap = _with_custody(snap)

    result = traffic_assurance.assess_flow(snap, _intent(return_required=False))

    forward = result["dimensions"]["path"]["forward"]
    assert forward["verdict"] == "proven", json.dumps(forward, indent=2)
    assert forward["hops"][0]["source"] == "ospf"
    assert forward["hops"][0]["next_hop"] == "10.0.12.2"
    assert result["verdict"] == "proven"


def test_embedded_or_forged_custody_cannot_self_certify_a_reassessment():
    current = _symmetric_snapshot()
    current_result = traffic_assurance.assess_flow(current, _intent())
    assert current_result["custody_trust"] == "current_run_verified"
    assert current_result["verdict"] == "proven"

    persisted = json.loads(json.dumps(current))
    persisted_result = traffic_assurance.assess_flow(persisted, _intent())
    assert persisted_result["custody_trust"] == "embedded_unverified"
    assert persisted_result["verdict"] == "indeterminate"
    assert any(
        gap["status"] == "embedded_unverified"
        for gap in persisted_result["dimensions"]["ecmp"]["forward"]["route_custody"]["gaps"]
    )

    forged = copy.deepcopy(persisted)
    for host in forged["traffic_evidence_custody"]["hosts"].values():
        for cell in host.values():
            cell["status"] = "ok"
            cell["complete"] = True
            if isinstance(cell.get("projection"), dict):
                cell["projection"]["status"] = "ok"
                cell["projection"]["complete"] = True
    forged_result = traffic_assurance.assess_flow(forged, _intent())
    assert forged_result["custody_trust"] == "embedded_unverified"
    assert forged_result["verdict"] == "indeterminate"


@pytest.mark.parametrize(
    "mutation",
    [
        ("route", "source"),
        ("route", "next_hop"),
        ("route", "out_intf"),
        ("interface", "acl_in"),
        ("interface", "acl_out"),
    ],
)
def test_native_evidence_with_non_unicode_scalar_is_sanitized_and_abstains(mutation):
    snap = _symmetric_snapshot()
    section, field = mutation
    if section == "route":
        snap["routes"]["R1"][2][field] = "bad-\ud800"
    else:
        snap["interfaces"]["R1"]["Gi0/1"][field] = "bad-\ud800"
    _with_custody(snap)

    first = traffic_assurance.assess_flow(snap, _intent())
    second = traffic_assurance.assess_flow(snap, _intent())
    encoded = json.dumps(first, ensure_ascii=False).encode("utf-8")

    assert first == second
    assert first["verdict"] == "indeterminate"
    if section == "route":
        assert "serialization_safety" not in first
        assert first["dimensions"]["path"]["forward"]["status"] == "lower_bound:malformed_route_evidence"
        assert b"INVALID UNICODE TEXT" not in encoded
    else:
        assert "serialization_safety" not in first
        stages = [
            stage
            for direction in ("forward", "reverse")
            for stage in first["dimensions"]["policy"][direction]["stages"]
        ]
        assert any(
            stage.get("provenance_gap") == "forwarding_gate_scalar_value_malformed"
            for stage in stages
        )
        assert b"INVALID UNICODE TEXT" not in encoded


def test_ecmp_mtu_shortfall_requires_exact_interface_provenance_before_refuting():
    snap = _ecmp_blackhole_snapshot()
    snap["routes"]["R3"][-1] = {
        "prefix": "10.2.2.0/24", "source": "connected", "out_intf": "Vlan20",
    }
    snap["interfaces"]["R3"]["Vlan20"] = {
        "mtu": 1500, "acl_in": "", "acl_out": "", "run_config_observed": True,
    }
    snap["interfaces"]["R1"]["Gi0/2"]["mtu"] = 1400
    snap["interfaces"]["R1"]["Gi0/2"]["run_config_observed"] = False
    _with_custody(snap)

    result = traffic_assurance.assess_flow(
        snap, _intent(return_required=False, required_mtu=1500)
    )

    ecmp = result["dimensions"]["ecmp"]["forward"]
    assert ecmp["native_verdict"] == "inconsistent"
    assert ecmp["mtu_below_required_legs"] == []
    assert ecmp["mtu_provenance_gaps"][0]["interface"] == "Gi0/2"
    assert ecmp["verdict"] == "indeterminate"
    assert result["verdict"] == "indeterminate"


@pytest.mark.parametrize("gate_field", ["crypto_map", "tunnel_protection"])
def test_ecmp_mtu_shortfall_abstains_when_the_adverse_leg_crosses_a_header_boundary(gate_field):
    snap = _ecmp_blackhole_snapshot()
    snap["routes"]["R3"][-1] = {
        "prefix": "10.2.2.0/24", "source": "connected", "out_intf": "Vlan20",
    }
    snap["interfaces"]["R3"]["Vlan20"] = {
        "mtu": 1500, "acl_in": "", "acl_out": "", "run_config_observed": True,
    }
    snap["interfaces"]["R1"]["Gi0/2"]["mtu"] = 1300
    snap["interfaces"]["R1"]["Gi0/2"][gate_field] = "BOUNDARY"
    _with_custody(snap)

    result = traffic_assurance.assess_flow(
        snap, _intent(return_required=False, required_mtu=1400)
    )

    ecmp = result["dimensions"]["ecmp"]["forward"]
    assert ecmp["selected_rib_mtu_below_required_legs"]
    assert ecmp["mtu_below_required_legs"] == []
    assert ecmp["mtu_leg_gate_gaps"]
    assert ecmp["verdict"] == "indeterminate"
    assert result["verdict"] == "indeterminate"


def test_ecmp_mtu_shortfall_is_not_tainted_by_an_unrelated_header_boundary():
    snap = _ecmp_blackhole_snapshot()
    snap["routes"]["R3"][-1] = {
        "prefix": "10.2.2.0/24", "source": "connected", "out_intf": "Vlan20",
    }
    snap["interfaces"]["R3"]["Vlan20"] = {
        "mtu": 1500, "acl_in": "", "acl_out": "", "run_config_observed": True,
    }
    snap["interfaces"]["R1"]["Gi0/2"]["mtu"] = 1300
    snap["interfaces"]["R1"]["Loopback99"] = {
        "mtu": 1500, "acl_in": "", "acl_out": "", "crypto_map": "UNRELATED",
        "run_config_observed": True,
    }
    _with_custody(snap)

    result = traffic_assurance.assess_flow(
        snap, _intent(return_required=False, required_mtu=1400)
    )

    ecmp = result["dimensions"]["ecmp"]["forward"]
    assert ecmp["mtu_below_required_legs"]
    assert ecmp["mtu_leg_gate_gaps"] == []
    assert ecmp["verdict"] == "refuted"
    assert result["verdict"] == "refuted"


def test_downstream_ecmp_is_never_certified_from_one_selected_branch():
    intent = _intent(dst="10.9.9.20", return_required=False, required_mtu=None)
    alternate_policy = traffic_assurance.assess_flow(
        _downstream_ecmp_snapshot(alternate_acl_deny=True), intent
    )
    forward_ecmp = alternate_policy["dimensions"]["ecmp"]["forward"]
    assert forward_ecmp["native_verdict"] == "not_ecmp"
    assert forward_ecmp["verdict"] == "indeterminate"
    assert forward_ecmp["unassessed_branch_points"][0]["host"] == "R2"
    assert alternate_policy["dimensions"]["policy"]["forward"]["branch_complete"] is False
    assert alternate_policy["verdict"] == "indeterminate"

    # Equal-cost row ordering can change the representative trace, but it cannot change the canonical verdict.
    # A selected denying branch is evidence, not proof that this exact flow hashes to that leg.
    swapped = _downstream_ecmp_snapshot(alternate_acl_deny=True)
    equal_cost = [index for index, row in enumerate(swapped["routes"]["R2"])
                  if row.get("prefix") == "10.9.9.0/24"]
    assert len(equal_cost) == 2
    first, second = equal_cost
    swapped["routes"]["R2"][first], swapped["routes"]["R2"][second] = (
        swapped["routes"]["R2"][second], swapped["routes"]["R2"][first]
    )
    _with_custody(swapped)
    selected_deny = traffic_assurance.assess_flow(swapped, intent)
    deny_policy = selected_deny["dimensions"]["policy"]["forward"]
    assert deny_policy["selected_path_verdict"] == "refuted"
    assert deny_policy["verdict"] == "indeterminate"
    assert selected_deny["dimensions"]["ecmp"]["forward"]["branch_complete"] is False
    assert selected_deny["verdict"] == alternate_policy["verdict"] == "indeterminate"

    alternate_drop = traffic_assurance.assess_flow(
        _downstream_ecmp_snapshot(alternate_drop=True), intent
    )
    assert alternate_drop["dimensions"]["path"]["forward"]["ecmp_dropping_legs"]
    assert alternate_drop["dimensions"]["ecmp"]["forward"]["verdict"] == "refuted"
    assert alternate_drop["verdict"] == "refuted"
    path_claim = next(claim for claim in alternate_drop["claims"] if claim["id"].endswith(".path"))
    assert path_claim["verdict"] == "refuted"
    assert path_claim["ecmp_observed_verdict"] == "refuted"

    scoped_absence = traffic_assurance.assess_flow(
        _downstream_ecmp_snapshot(alternate_absence=True), intent
    )
    assert scoped_absence["dimensions"]["ecmp"]["forward"]["observed_dropping_legs"] == []
    assert scoped_absence["dimensions"]["ecmp"]["forward"]["scoped_absence_legs"]
    assert scoped_absence["dimensions"]["ecmp"]["forward"]["verdict"] == "not_observed"
    assert scoped_absence["verdict"] == "indeterminate"


def test_failure_slice_is_receipted_and_never_mutates_the_snapshot():
    snap = _symmetric_snapshot()
    before = copy.deepcopy(snap)

    result = traffic_assurance.assess_flow(snap, _intent(), failure={"action": "fail_node", "id": "R2"})

    assert snap == before
    assert result["failure"]["mutation"]["removed_hosts"] == ["R2"]
    assert result["failure"]["baseline_verdict"] == "proven"
    assert result["failure"]["status"] == "l2_failover_not_proven"
    assert result["failure"]["post_verdict"] == "indeterminate"
    assert result["verdict"] == "indeterminate"
    assert all(claim["verdict"] == "indeterminate" for claim in result["claims"])
    assert all(claim.get("scenario_scope") == "baseline_plus_requested_failure"
               for claim in result["claims"][:2])


def test_failure_assurance_refuses_unproven_l2_failover_evidence():
    snap = _symmetric_snapshot()
    snap["stp_roots"] = {
        "L2ONLY": {"10": {"root_priority": 4096, "root_address": "aaaa.0000.0001",
                            "is_root": True, "bridge_priority": 4096}}
    }
    result = traffic_assurance.assess_flow(
        snap, _intent(), failure={"action": "fail_node", "id": "L2ONLY"}
    )
    assert result["failure"]["cutover_gate"]["verdict"] == "indeterminate"
    assert result["failure"]["status"] == "l2_failover_not_proven"
    assert result["failure"]["verdict"] == "indeterminate"
    assert result["verdict"] == "indeterminate"

    # A uniquely observed lower-priority survivor proves only an election candidate. Without an explicit
    # topology/client-attachment/convergence receipt it still cannot prove application-flow preservation.
    with_candidate = _symmetric_snapshot()
    with_candidate["stp_roots"] = {
        "L2ROOT": {"10": {"root_priority": 4096, "root_address": "aaaa.0000.0001",
                              "is_root": True, "bridge_priority": 4096}},
        "L2ALT": {"10": {"root_priority": 4096, "root_address": "aaaa.0000.0001",
                             "is_root": False, "bridge_priority": 8192}},
    }
    candidate = traffic_assurance.assess_flow(
        with_candidate, _intent(), failure={"action": "fail_node", "id": "L2ROOT"}
    )
    reroot = candidate["failure"]["cutover_evidence"]["steps"][0]["stp_reroots"][0]
    assert reroot["new_root"] == "L2ALT"
    assert reroot["election_candidate_only"] is True
    assert reroot["continuity_assessed"] is False
    assert candidate["failure"]["cutover_gate"]["continuity_assessed"] is False
    assert candidate["failure"]["status"] == "l2_failover_not_proven"
    assert candidate["failure"]["verdict"] == "indeterminate"
    assert candidate["verdict"] == "indeterminate"

    non_root = _symmetric_snapshot()
    non_root["stp_roots"] = {
        "L2ROOT": {"10": {"root_priority": 4096, "root_address": "aaaa.0000.0001",
                              "is_root": True, "bridge_priority": 4096}},
        "L2ACCESS": {"10": {"root_priority": 4096, "root_address": "aaaa.0000.0001",
                                "is_root": False, "bridge_priority": 32768}},
    }
    member_loss = traffic_assurance.assess_flow(
        non_root, _intent(), failure={"action": "fail_node", "id": "L2ACCESS"}
    )
    continuity = member_loss["failure"]["cutover_evidence"]["steps"][0]["l2_continuity"]
    assert continuity["election_projection_count"] == 0
    assert continuity["affected_member_hosts"] == ["L2ACCESS"]
    assert continuity["assessed"] is False
    assert member_loss["failure"]["status"] == "l2_failover_not_proven"
    assert member_loss["verdict"] == "indeterminate"

    route_only = _symmetric_snapshot()
    route_only["routes"]["R3"] = [
        {"prefix": "10.2.2.0/24", "source": "static", "next_hop": "", "out_intf": "Null0"},
        {"prefix": "10.1.1.0/24", "source": "static", "next_hop": "", "out_intf": "Null0"},
    ]
    _with_custody(route_only)
    absent_role = traffic_assurance.assess_flow(
        route_only, _intent(), failure={"action": "fail_node", "id": "R3"}
    )
    continuity = absent_role["failure"]["cutover_evidence"]["steps"][0]["l2_continuity"]
    assert continuity["applicable"] is True
    assert continuity["assessed"] is False
    assert absent_role["failure"]["status"] == "l2_failover_not_proven"
    assert absent_role["verdict"] == "indeterminate"


@pytest.mark.parametrize(
    ("section", "malformed"),
    [
        ("stp_roots", [{}]),
        ("stp_roots", "invalid"),
        ("fhrp_detail", [{}]),
        ("fhrp_detail", 7),
    ],
)
def test_malformed_l2_top_level_never_crashes_failure_composition(section, malformed):
    snap = _symmetric_snapshot()
    snap[section] = malformed

    result = traffic_assurance.assess_flow(
        snap, _intent(), failure={"action": "fail_node", "id": "R2"}
    )

    assert result["failure"]["requested"] is True
    assert result["verdict"] in {"refuted", "not_observed", "indeterminate"}
    json.dumps(result, ensure_ascii=False).encode("utf-8")


def test_unsupported_semantics_and_fhrp_role_move_cannot_claim_preserved_traffic():
    unsupported = traffic_assurance.assess_flow(
        _symmetric_snapshot(),
        _intent(protocol="icmp", src_port=None, dst_port=None),
        failure={"action": "shut_link", "host": "R1", "interface": "Gi0/1"},
    )
    assert unsupported["failure"]["status"] == "unsupported_semantics"
    assert unsupported["failure"]["verdict"] == "indeterminate"
    assert unsupported["failure"]["baseline_verdict"] == "indeterminate"

    snap = _symmetric_snapshot()
    snap["fhrp_detail"] = {
        "R1": [{"ifname": "Vlan10", "group": "10", "state": "Active", "priority": 110,
                "preempt": True, "vip": "10.1.1.1", "version": 2}],
        "R2": [{"ifname": "Vlan10", "group": "10", "state": "Standby", "priority": 100,
                "preempt": True, "vip": "10.1.1.1", "version": 2}],
    }
    moved = traffic_assurance.assess_flow(
        snap, _intent(),
        failure={"action": "move_fhrp_active", "ifname": "Vlan10", "group": "10", "to_host": "R2"},
    )
    assert moved["failure"]["mutation"]["is_noop"] is False
    assert moved["failure"]["status"] == "unsupported_action_for_traffic_assurance"
    assert moved["failure"]["verdict"] == "indeterminate"
    assert moved["verdict"] == "indeterminate"


@pytest.mark.parametrize(
    ("overrides", "error"),
    [
        ({"src": "garbage"}, "src is not an IP address"),
        ({"src_port": True}, "src_port must be an integer"),
        ({"src_port": float("inf")}, "src_port must be an integer"),
        ({"src_port": 1.9}, "src_port must be an integer"),
        ({"dst_port": 443.8}, "dst_port must be an integer"),
        ({"required_mtu": float("inf")}, "required_mtu must be a positive integer"),
        ({"required_mtu": 1500.9}, "required_mtu must be a positive integer"),
        ({"expected": "deny", "required_mtu": None}, "return_required=true cannot be combined"),
        ({"expected": "deny"}, "required_mtu cannot be combined with expected='deny'"),
        ({"protocol": "tcp", "dst_port": None}, "src_port and dst_port must be declared together"),
        ({"protocol": "icmp", "src_port": None, "dst_port": None}, None),
        ({"src": "0.0.0.0", "dst": "2001:db8::1"}, "src and dst must use the same address family"),
        ({"expected": False}, "expected must be a string"),
        ({"vrf": 123}, "vrf must be a string"),
    ],
)
def test_invalid_and_unsupported_intents_abstain(overrides, error):
    result = traffic_assurance.assess_flow(_symmetric_snapshot(), _intent(**overrides))
    assert result["verdict"] == "indeterminate"
    if error:
        assert any(message.startswith(error) for message in result["validation_errors"])
        assert result["valid"] is False
    else:
        assert result["valid"] is True
        assert result["supported"] is False
        assert result["unsupported_semantics"] == ["protocol:icmp"]


def test_ipv6_vrf_missing_tuple_and_duplicate_ids_are_explicit():
    ipv6 = traffic_assurance.assess_flow(
        {}, _intent(src="2001:db8::1", dst="2001:db8::2", vrf="BLUE")
    )
    assert ipv6["valid"] is True and ipv6["supported"] is False
    assert ipv6["unsupported_semantics"] == ["ipv6_flow", "vrf_scoped_forwarding"]
    assert ipv6["verdict"] == "indeterminate"
    assert all(claim["verdict"] == "indeterminate" for claim in ipv6["claims"])
    assert all(claim.get("applicability") == "unsupported_request" for claim in ipv6["claims"][:2])
    assert ipv6["dimensions"]["path"]["forward"]["verdict"] == "indeterminate"
    assert ipv6["dimensions"]["ecmp"]["forward"]["verdict"] == "indeterminate"

    missing_tuple = traffic_assurance.assess_flow(
        _symmetric_snapshot(), _intent(protocol=None, src_port=None, dst_port=None)
    )
    assert missing_tuple["valid"] is False
    assert missing_tuple["verdict"] == "indeterminate"
    assert missing_tuple["dimensions"] == {}
    assert missing_tuple["validation_errors"] == [
        "protocol is required for traffic_assurance/1"
    ]

    batch = traffic_assurance.assess_flows(_symmetric_snapshot(), [_intent(), _intent(dst_port=8443)])
    assert batch["summary"] == {
        "proven": 0, "refuted": 0, "not_observed": 0, "indeterminate": 2, "invalid": 2, "n": 2
    }
    assert all("duplicate traffic-assurance id" in row["validation_errors"][0] for row in batch["results"])

    anonymous = traffic_assurance.assess_flows(_symmetric_snapshot(), [_intent(id=""), _intent(id="")])
    assert anonymous["summary"]["invalid"] == 2
    assert all(row["validation_errors"] == ["id is required in a traffic assurance set"]
               for row in anonymous["results"])

    generated = traffic_assurance.assess_flows(
        _symmetric_snapshot(), (_intent(id=value) for value in ("a/b", "a?b"))
    )
    assert generated["summary"]["n"] == 2
    tokens = {tuple(row["nrfu_test_ids"]) for row in generated["results"]}
    assert len(tokens) == 2

    with_failure = traffic_assurance.assess_flows(
        _symmetric_snapshot(),
        [_intent(id="node-failure", failure={"action": "fail_node", "id": "R2"})],
    )
    assert with_failure["summary"]["n"] == 1
    assert with_failure["results"][0]["failure"]["requested"] is True
    assert with_failure["results"][0]["failure"]["action"] == "fail_node"

    surrogate = traffic_assurance.assess_flow(
        _symmetric_snapshot(), _intent(id="bad-\ud800/id")
    )
    assert surrogate["valid"] is False
    assert surrogate["verdict"] == "indeterminate"
    assert "id must contain only Unicode scalar values" in surrogate["validation_errors"]
    assert "\ud800" not in json.dumps(surrogate, ensure_ascii=False).encode("utf-8").decode("utf-8")

    unsafe_failure = traffic_assurance.assess_flow(
        _symmetric_snapshot(), _intent(), failure={"action": "fail_node", "id": "bad-\ud800"}
    )
    assert unsafe_failure["failure"]["mutation"]["valid"] is False
    json.dumps(unsafe_failure, ensure_ascii=False).encode("utf-8")


def test_same_subnet_and_non_host_endpoints_never_enter_routed_assurance():
    for dst in ("10.1.1.5", "10.1.1.6"):
        result = traffic_assurance.assess_flow(_symmetric_snapshot(), _intent(dst=dst))
        assert result["valid"] is True
        assert result["supported"] is False
        assert result["unsupported_semantics"] == ["same_subnet_l2_forwarding"]
        assert result["verdict"] == "indeterminate"
        assert result["dimensions"]["path"]["forward"]["verdict"] == "indeterminate"

    for field, value in (("src", "10.1.1.0"), ("src", "10.1.1.255"), ("dst", "10.2.2.255"),
                         ("src", "0.0.0.0"), ("dst", "224.0.0.1")):
        result = traffic_assurance.assess_flow(_symmetric_snapshot(), _intent(**{field: value}))
        assert result["valid"] is False
        assert result["verdict"] == "indeterminate"
        assert any("usable" in message for message in result["validation_errors"])


@pytest.mark.parametrize(("field", "address"), [("src", "10.1.1.1"), ("dst", "10.2.2.1")])
def test_locally_originated_or_terminated_endpoint_never_uses_gateway_acl_model(field, address):
    snap = _symmetric_snapshot()
    snap["interfaces"]["R1"]["Vlan10"]["svi_ip"] = "10.1.1.1/24"
    snap["interfaces"]["R2"]["Vlan20"]["svi_ip"] = "10.2.2.1 255.255.255.0"
    _with_custody(snap)
    result = traffic_assurance.assess_flow(snap, _intent(**{field: address}))
    assert result["valid"] is True
    assert result["supported"] is False
    assert "infrastructure_local_endpoint" in result["unsupported_semantics"]
    assert result["verdict"] == "indeterminate"
    assert all(claim["verdict"] == "indeterminate" for claim in result["claims"][:2])


def test_command_custody_is_positive_explicit_and_parser_bound():
    snap = _symmetric_snapshot()
    del snap["traffic_evidence_custody"]
    absent = traffic_assurance.assess_flow(snap, _intent())
    assert absent["verdict"] == "indeterminate"
    assert absent["dimensions"]["ecmp"]["forward"]["route_custody"]["gaps"]

    incomplete_config = _with_custody(
        _symmetric_snapshot(),
        [{"host": "R1", "command": "show running-config", "status": "incomplete"}],
    )
    assessed_config = traffic_assurance.assess_flow(incomplete_config, _intent())
    stage = assessed_config["dimensions"]["policy"]["forward"]["stages"][0]
    assert stage["verdict"] == "not_observed"
    assert "custody is not proven" in stage["detail"]

    incomplete_route = _with_custody(
        _symmetric_snapshot(),
        [{"host": "R1", "command": "show ip route", "status": "incomplete"}],
    )
    assessed_route = traffic_assurance.assess_flow(incomplete_route, _intent())
    assert assessed_route["dimensions"]["ecmp"]["forward"]["verdict"] == "not_observed"
    assert assessed_route["verdict"] == "indeterminate"

    inventory = {"R1": {"show running-config": "a", "show ip route": "b"}}
    zero_yield = traffic_assurance.build_traffic_evidence_custody(
        inventory,
        _capture_integrity_for(inventory),
        {"per_parser": {
            "parse_run_config_interfaces": {"calls": 1, "with_content": 1, "errors": 0},
            "parse_acls": {"calls": 1, "with_content": 1, "errors": 0},
            "parse_object_groups": {"calls": 1, "with_content": 1, "errors": 0},
            "parse_ip_routes": {"calls": 1, "with_content": 1, "zero_yield": 1, "errors": 0},
         }, "events": [{"parser": "parse_ip_routes", "device": "R1", "cmd": "show ip route",
                          "file": "route.txt", "lines_in": 10, "error": False}],
         "events_truncated": False,
         "receipts": [
             {"parser": "parse_acls", "device": "R1", "cmd": "show running-config",
              "calls": 1, "with_entities": 0, "zero_yield": 1, "errors": 0},
             {"parser": "parse_object_groups", "device": "R1", "cmd": "show running-config",
              "calls": 1, "with_entities": 0, "zero_yield": 1, "errors": 0},
             {"parser": "parse_ip_routes", "device": "R1", "cmd": "show ip route",
              "calls": 1, "with_entities": 0, "zero_yield": 1, "errors": 0},
         ]},
        evidence_sections=_empty_binding_sections("R1"),
    )
    assert zero_yield["hosts"]["R1"]["acl_definitions"]["complete"] is True
    assert zero_yield["hosts"]["R1"]["routing_table"]["status"] == "zero_yield"

    safe_inventory = {"R:1": {"show running-config": "a", "show running-config interface": "b",
                                "show ip route": "c"}}
    safe_name_yield = traffic_assurance.build_traffic_evidence_custody(
        safe_inventory,
        _capture_integrity_for(safe_inventory),
        {"per_parser": {
            "parse_run_config_interfaces": {"calls": 1, "with_content": 1, "errors": 0},
            "parse_acls": {"calls": 1, "with_content": 1, "errors": 0},
            "parse_object_groups": {"calls": 1, "with_content": 1, "errors": 0},
            "parse_ip_routes": {"calls": 1, "with_content": 1, "zero_yield": 1, "errors": 0},
         }, "events": [{"parser": "parse_ip_routes", "device": "R_1", "cmd": "show ip route",
                          "file": "route.txt", "lines_in": 10, "error": False}],
         "events_truncated": False,
         "receipts": [
             {"parser": parser, "device": "R_1", "cmd": command, "calls": 1,
              "with_entities": 0 if parser == "parse_ip_routes" else 1,
              "zero_yield": 1 if parser == "parse_ip_routes" else 0, "errors": 0}
             for parser, command in (
                 ("parse_acls", "show running-config"),
                 ("parse_object_groups", "show running-config"),
                 ("parse_run_config_interfaces", "show running-config interface"),
                 ("parse_ip_routes", "show ip route"),
             )
         ]},
        evidence_sections=_empty_binding_sections("R:1"),
    )
    assert safe_name_yield["hosts"]["R:1"]["routing_table"]["status"] == "zero_yield"

    malformed_receipt = traffic_assurance.build_traffic_evidence_custody(
        safe_inventory,
        _capture_integrity_for(safe_inventory),
        {"per_parser": {
            name: {"calls": 1, "with_content": 1, "zero_yield": 0, "errors": 0}
            for name in ("parse_run_config_interfaces", "parse_acls", "parse_object_groups", "parse_ip_routes")
         }, "receipts": [
             {"parser": parser, "device": "R_1", "cmd": command,
              "calls": 1, "with_entities": 1, "zero_yield": 0,
              "errors": "private malformed counter" if parser == "parse_ip_routes" else 0}
             for parser, command in (
                 ("parse_acls", "show running-config"),
                 ("parse_object_groups", "show running-config"),
                 ("parse_run_config_interfaces", "show running-config interface"),
                 ("parse_ip_routes", "show ip route"),
             )
         ]},
        {"R:1": scope_routes({
            "10.0.0.0/24": {"entries": [
                {"prefix": "10.0.0.0/24", "source": "connected", "out_intf": "Vlan1"},
            ]},
        }, {"10.0.0.0/24"})},
        _empty_binding_sections("R:1"),
    )
    assert malformed_receipt["hosts"]["R:1"]["routing_table"]["status"] == "parser_receipt_malformed"

    full_only = _symmetric_snapshot()
    hosts = sorted(full_only["routes"])
    full_inventory = {
        host: {"show running-config": "cfg", "show ip route": "route"} for host in hosts
    }
    full_only["traffic_evidence_custody"] = traffic_assurance.build_traffic_evidence_custody(
        full_inventory,
        _capture_integrity_for(full_inventory),
        {"per_parser": {
            name: {"calls": len(hosts), "with_content": len(hosts), "zero_yield": 0, "errors": 0}
            for name in ("parse_run_config_interfaces", "parse_acls", "parse_object_groups", "parse_ip_routes")
         }, "events": [], "events_truncated": False,
         "receipts": [
             {"parser": parser, "device": safe_fs_name(host), "cmd": command,
              "calls": 1, "with_entities": 1, "zero_yield": 0, "errors": 0}
             for host in hosts
             for parser, command in (
                 ("parse_acls", "show running-config"),
                 ("parse_object_groups", "show running-config"),
                 ("parse_ip_routes", "show ip route"),
             )
         ]},
        full_only["routes"],
        {"interfaces": full_only.get("interfaces") or {}, "acls": full_only.get("acls") or {},
         "object_groups": full_only.get("object_groups") or {}, "nat": full_only.get("nat") or {}},
    )
    full_only_result = traffic_assurance.assess_flow(full_only, _intent())
    assert full_only_result["verdict"] == "indeterminate"
    assert any("interface attachments=not_collected" in stage["detail"]
               for stage in full_only_result["dimensions"]["policy"]["forward"]["stages"])

    route_inventory = {"R1": {"show ip route": "route.txt"}}
    unavailable_integrity = traffic_assurance.build_traffic_evidence_custody(
        route_inventory, {}, {}
    )
    assert unavailable_integrity["hosts"]["R1"]["routing_table"]["status"] == \
        "capture_integrity_unavailable"
    missing_inspection = traffic_assurance.build_traffic_evidence_custody(
        route_inventory, {"findings": [], "inspections": [], "summary": {}}, {}
    )
    assert missing_inspection["hosts"]["R1"]["routing_table"]["status"] == "inspection_missing"
    no_parser_content = traffic_assurance.build_traffic_evidence_custody(
        route_inventory, _capture_integrity_for(route_inventory),
        {"per_parser": {"parse_ip_routes": {
            "calls": 1, "with_content": 0, "zero_yield": 0, "errors": 0,
        }}, "receipts": [], "events": [], "events_truncated": False},
    )
    assert no_parser_content["hosts"]["R1"]["routing_table"]["status"] == \
        "parser_input_not_observed"

    cross_host_inventory = {
        "R1": {"show ip route": "r1.txt"},
        "R2": {"show ip route": "r2.txt"},
    }
    cross_host = traffic_assurance.build_traffic_evidence_custody(
        cross_host_inventory,
        _capture_integrity_for(cross_host_inventory),
        {"per_parser": {"parse_ip_routes": {
            "calls": 2, "with_content": 2, "zero_yield": 0, "errors": 0,
        }}, "receipts": [
            {"parser": "parse_ip_routes", "device": "R1", "cmd": "show ip route",
             "calls": 1, "with_entities": 1, "zero_yield": 0, "errors": 0},
            {"parser": "parse_ip_routes", "device": "R2", "cmd": "show ip route",
             "calls": 0, "with_entities": 0, "zero_yield": 0, "errors": 0},
        ]},
    )
    assert cross_host["hosts"]["R1"]["routing_table"]["status"] == "ok"
    assert cross_host["hosts"]["R2"]["routing_table"]["status"] == "parser_receipt_malformed"


@pytest.mark.parametrize("mutation", ["acl_definition", "interface_attachment"])
def test_configuration_content_cannot_change_after_current_run_custody(mutation):
    snap = _symmetric_snapshot()
    snap["acls"]["R1"]["CLIENT-IN"] = [_rule("deny", dport=443)]
    _with_custody(snap)
    assert traffic_assurance.assess_flow(
        snap, _intent(return_required=False)
    )["verdict"] == "refuted"

    if mutation == "acl_definition":
        snap["acls"]["R1"]["CLIENT-IN"] = [_rule("permit", dport=443)]
    else:
        snap["interfaces"]["R1"]["Vlan10"]["acl_in"] = ""

    result = traffic_assurance.assess_flow(snap, _intent(return_required=False))
    stage = result["dimensions"]["policy"]["forward"]["stages"][0]

    assert result["custody_trust"] == "current_run_verified"
    assert result["verdict"] == "indeterminate"
    assert stage["verdict"] == "not_observed"
    assert "content_changed_after_custody" in stage["detail"]


def test_same_shape_valid_route_projection_swap_cannot_inherit_prior_custody():
    snap = _symmetric_snapshot()
    replacement_rows = [dict(row) for row in snap["routes"]["R1"]]
    replacement_rows[-1] = {
        "prefix": "10.2.2.0/24", "source": "static", "next_hop": "", "out_intf": "Null0",
    }
    replacement = {
        "routes": {"R1": replacement_rows},
        "interfaces": {"R1": copy.deepcopy(snap["interfaces"]["R1"])},
        "acls": {"R1": copy.deepcopy(snap["acls"]["R1"])},
        "object_groups": {"R1": {}},
    }
    _with_custody(replacement)
    assert len(replacement["routes"]["R1"]) == len(snap["routes"]["R1"])
    assert replacement["routes"]["R1"].projection_receipt["scope_networks"] == \
        snap["routes"]["R1"].projection_receipt["scope_networks"]

    snap["routes"]["R1"] = replacement["routes"]["R1"]
    result = traffic_assurance.assess_flow(snap, _intent(return_required=False, required_mtu=None))
    gaps = result["dimensions"]["path"]["forward"]["route_custody"]["gaps"]

    assert result["verdict"] == "indeterminate"
    assert any(gap["host"] == "R1" and gap["status"] == "projection_changed_after_custody"
               for gap in gaps)


def test_truncated_route_capture_cannot_turn_a_selected_null_route_into_device_truth():
    snap = _symmetric_snapshot()
    snap["routes"]["R1"][-1] = {
        "prefix": "10.2.2.0/24", "source": "static", "next_hop": "", "out_intf": "Null0",
    }
    _with_custody(snap, [{"host": "R1", "command": "show ip route", "status": "incomplete"}])
    result = traffic_assurance.assess_flow(
        snap, _intent(return_required=False, required_mtu=None)
    )
    forward = result["dimensions"]["path"]["forward"]
    assert forward["selected_projection_verdict"] == "refuted"
    assert forward["verdict"] == "indeterminate"
    assert result["dimensions"]["ecmp"]["forward"]["verdict"] == "not_observed"
    assert result["verdict"] == "indeterminate"


def test_unparsed_plausible_more_specific_route_makes_broader_null0_abstain():
    parsed = parse.parse_ip_routes(textwrap.dedent("""\
        C 10.1.1.0/24 is directly connected, Vlan10
        C 10.0.12.0/30 is directly connected, GigabitEthernet0/1
        S 10.2.2.0/24 is directly connected, Null0
        O E3 10.2.2.0/25 [110/20] via 10.0.12.2, GigabitEthernet0/1
    """))
    assert parsed.parse_receipt["complete"] is False
    assert parsed.parse_receipt["unexplained_candidate_rows"] == 1

    snap = _symmetric_snapshot()
    snap["routes"]["R1"] = scope_routes(
        parsed, {"10.1.1.0/24", "10.0.12.0/30", "10.2.2.0/24"}
    )
    _with_custody(snap)
    projection = snap["traffic_evidence_custody"]["hosts"]["R1"]["routing_table"]["projection"]
    assert projection["status"] == "route_parse_incomplete"
    assert projection["complete"] is False
    assert projection["parse_receipt"]["unexplained_candidate_rows"] == 1

    result = traffic_assurance.assess_flow(
        snap, _intent(return_required=False, required_mtu=None)
    )
    forward = result["dimensions"]["path"]["forward"]
    assert forward["selected_projection_verdict"] == "refuted"
    assert forward["verdict"] == "indeterminate"
    assert result["verdict"] == "indeterminate"
    assert any(
        gap["status"] == "route_parse_incomplete"
        for gap in forward["route_custody"]["gaps"]
    )


def test_route_row_mutated_after_custody_cannot_reuse_cached_projection_proof():
    snap = _symmetric_snapshot()
    selected = next(
        row for row in snap["routes"]["R1"] if row["prefix"] == "10.2.2.0/24"
    )
    selected["next_hop"] = ""
    selected["out_intf"] = "Null0"

    result = traffic_assurance.assess_flow(
        snap, _intent(return_required=False, required_mtu=None)
    )
    forward = result["dimensions"]["path"]["forward"]
    assert forward["selected_projection_verdict"] == "refuted"
    assert forward["verdict"] == "indeterminate"
    assert result["verdict"] == "indeterminate"
    assert any(
        gap["status"] == "projection_receipt_mismatch"
        for gap in forward["route_custody"]["gaps"]
    )


def test_malformed_projection_status_and_source_command_are_fixed_non_echoing_gaps():
    secret = "private-route-receipt-secret"
    deep_status: object = secret
    for _ in range(1200):
        deep_status = [deep_status]
    malformed_status = _symmetric_snapshot()
    malformed_status["traffic_evidence_custody"]["hosts"]["R1"]["routing_table"][
        "projection"
    ]["status"] = deep_status

    status_result = traffic_assurance.assess_flow(
        malformed_status, _intent(return_required=False, required_mtu=None)
    )
    status_encoded = json.dumps(status_result, sort_keys=True)
    assert secret not in status_encoded
    assert any(
        gap["status"] == "invalid_projection_receipt"
        for gap in status_result["dimensions"]["path"]["forward"]["route_custody"]["gaps"]
    )

    malformed_command = _symmetric_snapshot()
    malformed_command["traffic_evidence_custody"]["hosts"]["R1"]["routing_table"][
        "source_command"
    ] = secret
    command_result = traffic_assurance.assess_flow(
        malformed_command, _intent(return_required=False, required_mtu=None)
    )
    command_encoded = json.dumps(command_result, sort_keys=True)
    assert secret not in command_encoded
    assert any(
        gap["status"] == "invalid_custody_receipt" and gap["source_command"] is None
        for gap in command_result["dimensions"]["path"]["forward"]["route_custody"]["gaps"]
    )


def test_disclosed_rpf_abstains_on_ambiguous_owners_and_two_blocked_directions():
    ambiguous = {
        "routes": {
            "A": [
                {"prefix": "10.1.1.0/24", "source": "connected", "out_intf": "Vlan10"},
                {"prefix": "192.0.2.0/30", "source": "connected", "out_intf": "Gi0/1"},
                {"prefix": "10.2.2.0/24", "source": "static", "next_hop": "192.0.2.2", "out_intf": "Gi0/1"},
            ],
            "B": [
                {"prefix": "10.1.1.0/24", "source": "connected", "out_intf": "Vlan10"},
                {"prefix": "198.51.100.0/30", "source": "connected", "out_intf": "Gi0/1"},
                {"prefix": "10.2.2.0/24", "source": "static", "next_hop": "198.51.100.2", "out_intf": "Gi0/1"},
            ],
            "D": [
                {"prefix": "192.0.2.0/30", "source": "connected", "out_intf": "Gi0/1"},
                {"prefix": "198.51.100.0/30", "source": "connected", "out_intf": "Gi0/2"},
                {"prefix": "10.2.2.0/24", "source": "connected", "out_intf": "Vlan20"},
                {"prefix": "10.1.1.0/24", "source": "static", "next_hop": "198.51.100.1", "out_intf": "Gi0/2"},
            ],
        },
        "interfaces": {
            "A": {"Gi0/1": {"svi_ip": "192.0.2.1/30"}},
            "B": {"Gi0/1": {"svi_ip": "198.51.100.1/30"}},
            "D": {
                "Gi0/1": {"svi_ip": "192.0.2.2/30"},
                "Gi0/2": {"svi_ip": "198.51.100.2/30"},
            },
        },
    }
    ambiguous_trace = fib.trace_bidirectional(
        ambiguous, "10.1.1.10", "10.2.2.20", disclose=True
    )
    assert ambiguous_trace["forward"]["ambiguous_candidate_sets"]
    assert ambiguous_trace["rpf_verdict"] == "INDETERMINATE"
    assert ambiguous_trace["symmetric"] is False

    blocked = {"routes": {
        "A": [{"prefix": "10.1.1.0/24", "source": "connected", "out_intf": "Vlan10"},
              {"prefix": "10.2.2.0/24", "source": "static", "out_intf": "Null0"}],
        "B": [{"prefix": "10.2.2.0/24", "source": "connected", "out_intf": "Vlan20"},
              {"prefix": "10.1.1.0/24", "source": "static", "out_intf": "Null0"}],
    }}
    blocked_trace = fib.trace_bidirectional(blocked, "10.1.1.10", "10.2.2.20", disclose=True)
    assert blocked_trace["forward"]["drop_evidence"] == "observed_discard"
    assert blocked_trace["reverse"]["drop_evidence"] == "observed_discard"
    assert blocked_trace["rpf_verdict"] == "INDETERMINATE"
    assert blocked_trace["symmetric"] is False


def test_disclosed_rpf_never_confuses_equal_host_sets_with_parallel_link_symmetry():
    parallel = {
        "routes": {
            "R1": [
                {"prefix": "10.1.1.0/24", "source": "connected", "out_intf": "Vlan10"},
                {"prefix": "10.0.12.0/30", "source": "connected", "out_intf": "Gi0/1"},
                {"prefix": "10.0.13.0/30", "source": "connected", "out_intf": "Gi0/2"},
                {"prefix": "10.2.2.0/24", "source": "static", "next_hop": "10.0.12.2",
                 "out_intf": "Gi0/1"},
            ],
            "R2": [
                {"prefix": "10.0.12.0/30", "source": "connected", "out_intf": "Gi0/1"},
                {"prefix": "10.0.13.0/30", "source": "connected", "out_intf": "Gi0/2"},
                {"prefix": "10.2.2.0/24", "source": "connected", "out_intf": "Vlan20"},
                {"prefix": "10.1.1.0/24", "source": "static", "next_hop": "10.0.13.1",
                 "out_intf": "Gi0/2"},
            ],
        },
        "interfaces": {
            "R1": {
                "Gi0/1": {"svi_ip": "10.0.12.1/30"},
                "Gi0/2": {"svi_ip": "10.0.13.1/30"},
            },
            "R2": {
                "Gi0/1": {"svi_ip": "10.0.12.2/30"},
                "Gi0/2": {"svi_ip": "10.0.13.2/30"},
            },
        },
    }
    trace = fib.trace_bidirectional(parallel, "10.1.1.10", "10.2.2.20", disclose=True)
    assert trace["forward"]["reached"] is True and trace["reverse"]["reached"] is True
    assert trace["path_relation"] == "host_set_aligned"
    assert trace["rpf_scope"] == "strict_u_rpf_not_assessed"
    assert trace["rpf_verdict"] == "INDETERMINATE"
    assert trace["symmetric"] is False


def test_malformed_acl_actions_and_raw_text_abstain_without_leaking():
    import json

    for action in (None, "allow", 1):
        snap = _symmetric_snapshot()
        rule = _rule("permit", dport=443)
        rule["action"] = action
        snap["acls"]["R1"]["CLIENT-IN"] = [rule]
        _with_custody(snap)
        result = traffic_assurance.assess_flow(snap, _intent())
        assert result["verdict"] == "indeterminate"
        assert result["dimensions"]["policy"]["forward"]["stages"][0]["native_result"] == "INDETERMINATE"
        assert result["dimensions"]["policy"]["forward"]["stages"][0]["native_result"] == "INDETERMINATE"

    snap = _symmetric_snapshot()
    unsafe = _rule("permit", dport=443)
    unsafe.update({"unevaluable": True, "raw": "password SUPERSECRET"})
    snap["acls"]["R1"]["CLIENT-IN"] = [unsafe]
    _with_custody(snap)
    encoded = json.dumps(traffic_assurance.assess_flow(snap, _intent()))
    assert "SUPERSECRET" not in encoded and "password" not in encoded.lower()


def test_malformed_acl_protocols_and_object_group_bodies_abstain():
    for proto in (None, [], {}, 1, False):
        snap = _symmetric_snapshot()
        rule = _rule("permit", dport=443)
        if proto is None:
            rule.pop("proto")
        else:
            rule["proto"] = proto
        snap["acls"]["R1"]["CLIENT-IN"] = [rule]
        _with_custody(snap)
        result = traffic_assurance.assess_flow(snap, _intent())
        assert result["verdict"] == "indeterminate"


def test_deep_object_group_chain_cannot_escape_totality_or_become_a_verdict():
    groups = {
        f"G{index}": {"kind": "network", "members": [{"group": f"G{index + 1}"}]}
        for index in range(1_200)
    }
    groups["G1200"] = {"kind": "network", "members": [{"ip": "10.1.1.10", "wild": "0.0.0.0"}]}
    snap = _symmetric_snapshot()
    snap["object_groups"] = {"R1": groups}
    snap["acls"]["R1"]["CLIENT-IN"] = [
        {**_rule("permit", dport=443), "src": {"group": "G0"}, "unevaluable": True}
    ]
    _with_custody(snap)

    result = traffic_assurance.assess_flow(snap, _intent(return_required=False))

    assert result["dimensions"]["policy"]["forward"]["verdict"] == "indeterminate"
    assert result["verdict"] == "indeterminate"
    json.dumps(result, ensure_ascii=False).encode("utf-8")


@pytest.mark.parametrize(
    "config",
    [
        "ip access-list extended CLIENT-IN\n"
        " permit tcp any any eq 443 dscp ef\n deny ip any any\n",
        "ip access-list extended CLIENT-IN\n"
        " deny tcp any any eq 443 dscp ef\n permit ip any any\n",
        "ip access-list extended CLIENT-IN\n evaluate REFLECTED\n deny ip any any\n",
        "object-group service WEB_SVC\n tcp eq 443\n"
        "ip access-list extended CLIENT-IN\n"
        " permit tcp any any object-group WEB_SVC\n deny ip any any\n",
    ],
)
def test_parser_retains_unmodeled_acl_semantics_as_canonical_abstentions(config):
    from cisco_toolkit import parse

    snap = _symmetric_snapshot()
    snap["acls"]["R1"]["CLIENT-IN"] = parse.parse_acls(config)["CLIENT-IN"]
    snap["object_groups"] = {"R1": parse.parse_object_groups(config)}
    _with_custody(snap)

    result = traffic_assurance.assess_flow(snap, _intent())

    assert result["dimensions"]["policy"]["forward"]["verdict"] == "indeterminate"
    assert result["verdict"] == "indeterminate"


def test_ios_network_object_member_is_not_silently_dropped():
    from cisco_toolkit import parse

    config = (
        "object-group network CLIENTS\n network-object host 10.1.1.10\n"
        "ip access-list extended CLIENT-IN\n"
        " permit tcp object-group CLIENTS any eq 443\n deny ip any any\n"
    )
    snap = _symmetric_snapshot()
    snap["acls"]["R1"]["CLIENT-IN"] = parse.parse_acls(config)["CLIENT-IN"]
    snap["object_groups"] = {"R1": parse.parse_object_groups(config)}
    _with_custody(snap)

    result = traffic_assurance.assess_flow(snap, _intent())

    assert result["dimensions"]["policy"]["forward"]["verdict"] == "proven"
    assert result["verdict"] == "proven"

    malformed_addresses = (
        {"ip": 0, "wild": 4294967295},
        {"ip": 167837706, "wild": 0},
        {"ip": True, "wild": False},
        {"rangeStart": 167837697, "rangeEnd": 167837706},
    )
    for address in malformed_addresses:
        snap = _symmetric_snapshot()
        rule = _rule("permit", dport=443)
        rule["src"] = address
        snap["acls"]["R1"]["CLIENT-IN"] = [rule]
        _with_custody(snap)
        result = traffic_assurance.assess_flow(snap, _intent())
        assert result["verdict"] == "indeterminate"
        assert result["dimensions"]["policy"]["forward"]["stages"][0]["native_result"] == "INDETERMINATE"

    for malformed_members in (None, "bad", [1]):
        snap = _symmetric_snapshot()
        rule = _rule("permit", dport=443)
        rule["src"] = {"group": "G"}
        snap["acls"]["R1"]["CLIENT-IN"] = [rule]
        snap["object_groups"] = {"R1": {"G": {"kind": "network", "members": malformed_members}}}
        _with_custody(snap)
        result = traffic_assurance.assess_flow(snap, _intent())
        assert result["verdict"] == "indeterminate"
        assert result["dimensions"]["policy"]["forward"]["stages"][0]["native_result"] == "INDETERMINATE"


def test_malformed_mtu_and_discard_tokens_never_become_positive_evidence():
    assert fib._parse_mtu("9216 bytes") == 9216
    for malformed in ("-1500", "+1500", "mtu 1500", "1500.5", False):
        assert fib._parse_mtu(malformed) is None
    assert fib._is_discard("Null0") is True
    assert fib._is_discard("Nu0.100") is True
    assert fib._is_discard("discard") is True
    assert fib._is_discard("numbered-uplink") is False

    snap = _symmetric_snapshot()
    for ports in snap["interfaces"].values():
        for record in ports.values():
            record["mtu"] = "-1500"
    _with_custody(snap)
    result = traffic_assurance.assess_flow(snap, _intent())
    assert result["dimensions"]["mtu"]["forward"]["verdict"] == "not_observed"
    assert result["verdict"] == "indeterminate"


@pytest.mark.parametrize(
    ("gate_line", "gate_token"),
    [
        ("ip policy route-map BLACKHOLE", "policy_based_routing"),
        ("ip verify unicast source reachable-via rx", "unicast_rpf"),
        ("ipv4 verify unicast source reachable-via rx allow-default", "unicast_rpf"),
        ("service-policy type pbr input DIVERT", "policy_based_routing"),
        ("zone-member security INSIDE", "zone_based_firewall"),
        ("service-policy type access-control input DROP-HTTPS", "input_service_policy"),
        ("ipv4 access-group common COMMON IFACE ingress", "multiple_or_common_acl_chain"),
        ("ip inspect FIREWALL in", "stateful_inspection"),
        ("crypto map WAN-MAP", "crypto_map"),
    ],
)
def test_configured_ingress_forwarding_gates_force_canonical_abstention(gate_line, gate_token):
    from cisco_toolkit import parse

    parsed = parse.parse_run_config_interfaces(
        "interface Vlan10\n " + gate_line + "\n"
    )["Vlan10"]
    snap = _symmetric_snapshot()
    snap["interfaces"]["R1"]["Vlan10"].update(parsed)
    snap["interfaces"]["R1"]["Vlan10"]["run_config_observed"] = True
    _with_custody(snap)

    result = traffic_assurance.assess_flow(snap, _intent())
    ingress = next(
        stage for stage in result["dimensions"]["policy"]["forward"]["stages"]
        if stage["role"] == "source_ingress"
    )
    assert gate_token in ingress["unmodeled_forwarding_gates"]
    assert ingress["verdict"] == "indeterminate"
    assert result["verdict"] == "indeterminate"


def test_global_vlan_access_map_is_a_visible_packet_gate_and_abstains():
    config = (
        "interface Vlan10\n ip address 10.1.1.1 255.255.255.0\n"
        "ip access-list extended WEB\n permit tcp any any eq 443\n"
        "vlan access-map BLOCK_HTTPS 10\n match ip address WEB\n action drop\n"
        "vlan access-map BLOCK_HTTPS 20\n action forward\n"
        "vlan filter BLOCK_HTTPS vlan-list 10\n"
    )
    parsed = parse.parse_run_config_interfaces(config)["Vlan10"]
    snap = _symmetric_snapshot()
    snap["interfaces"]["R1"]["Vlan10"].update(parsed)
    snap["interfaces"]["R1"]["Vlan10"]["run_config_observed"] = True
    _with_custody(snap)

    result = traffic_assurance.assess_flow(snap, _intent(return_required=False))
    ingress = next(
        stage for stage in result["dimensions"]["policy"]["forward"]["stages"]
        if stage["role"] == "source_ingress"
    )

    assert parsed["vacl_policy"] == "BLOCK_HTTPS"
    assert "vlan_access_map" in ingress["unmodeled_forwarding_gates"]
    for dimension in ("path", "policy", "mtu", "ecmp"):
        assert result["dimensions"][dimension]["forward"]["verdict"] == "indeterminate"
    assert result["verdict"] == "indeterminate"


def test_vlan_access_map_invalidates_a_later_selected_rib_acl_deny():
    snap = _symmetric_snapshot()
    snap["interfaces"]["R1"]["Vlan10"]["vacl_policy"] = "BLOCK_OR_REDIRECT"
    snap["interfaces"]["R1"]["Gi0/1"]["acl_out"] = "BLOCK"
    snap["acls"]["R1"]["BLOCK"] = [_rule("deny", dport=443)]
    _with_custody(snap)

    result = traffic_assurance.assess_flow(snap, _intent(return_required=False))

    assert result["dimensions"]["policy"]["forward"]["selected_path_verdict"] == "refuted"
    assert result["dimensions"]["policy"]["forward"]["verdict"] == "indeterminate"
    assert result["claims"][1]["verdict"] == "indeterminate"
    assert result["verdict"] == "indeterminate"


def test_vlan_access_map_does_not_invent_order_before_an_acl_on_the_same_svi():
    snap = _symmetric_snapshot()
    snap["interfaces"]["R1"]["Vlan10"]["vacl_policy"] = "DROP_OR_REDIRECT"
    snap["acls"]["R1"]["CLIENT-IN"] = [_rule("deny", dport=443)]
    _with_custody(snap)

    result = traffic_assurance.assess_flow(snap, _intent(return_required=False))

    forward = result["dimensions"]["policy"]["forward"]
    assert forward["selected_path_verdict"] == "refuted"
    assert forward["verdict"] == "indeterminate"
    assert result["claims"][1]["verdict"] == "indeterminate"
    assert result["verdict"] == "indeterminate"


def test_stateful_inspection_abstention_propagates_across_the_requested_flow_pair():
    snap = _symmetric_snapshot()
    snap["interfaces"]["R1"]["Vlan10"]["inspection_policy_in"] = "FIREWALL"
    snap["interfaces"]["R1"]["Gi0/1"]["acl_in"] = "RETURN-BLOCK"
    snap["acls"]["R1"]["RETURN-BLOCK"] = [_rule("deny", dport=40000)]
    _with_custody(snap)

    result = traffic_assurance.assess_flow(snap, _intent(return_required=True))

    assert result["dimensions"]["policy"]["forward"]["verdict"] == "indeterminate"
    assert result["dimensions"]["policy"]["reverse"]["selected_session_independent_verdict"] == "refuted"
    assert result["dimensions"]["policy"]["reverse"]["verdict"] == "indeterminate"
    assert result["claims"][1]["verdict"] == "indeterminate"
    assert result["verdict"] == "indeterminate"


def test_tunnel_routes_are_labeled_as_overlay_rib_projection_not_endpoint_delivery():
    snap = _with_custody({
        "routes": {
            "R1": [
                {"prefix": "10.1.1.0/24", "source": "connected", "out_intf": "Vlan10"},
                {"prefix": "172.16.0.0/30", "source": "connected", "out_intf": "Tu0"},
                {"prefix": "10.2.2.0/24", "source": "ospf", "next_hop": "172.16.0.2",
                 "out_intf": "Tu0"},
            ],
            "R2": [
                {"prefix": "172.16.0.0/30", "source": "connected", "out_intf": "Tu0"},
                {"prefix": "10.2.2.0/24", "source": "connected", "out_intf": "Vlan20"},
                {"prefix": "10.1.1.0/24", "source": "ospf", "next_hop": "172.16.0.1",
                 "out_intf": "Tu0"},
            ],
        },
        "interfaces": {
            "R1": {
                "Vlan10": {"mtu": 1500, "acl_in": "", "acl_out": "",
                           "run_config_observed": True},
                "Tu0": {"mtu": 1476, "acl_in": "", "acl_out": "", "svi_ip": "172.16.0.1/30",
                        "run_config_observed": True},
            },
            "R2": {
                "Tu0": {"mtu": 1476, "acl_in": "", "acl_out": "", "svi_ip": "172.16.0.2/30",
                        "run_config_observed": True},
                "Vlan20": {"mtu": 1500, "acl_in": "", "acl_out": "",
                           "run_config_observed": True},
            },
        },
        "acls": {},
        "object_groups": {},
    })

    result = traffic_assurance.assess_flow(snap, _intent(required_mtu=1400))
    claim = next(claim for claim in result["claims"] if claim["id"] == "traffic.web.path")

    assert result["verdict"] == "proven"
    assert result["dimensions"]["path"]["forward"]["overlay_tunnel_forwarding"] is True
    assert result["dimensions"]["path"]["forward"]["tunnel_underlay"] == "not_assessed"
    assert claim["predicate"] == "selected_rib_forwarding_projection"
    assert claim["endpoint_delivery_assessed"] is False
    assert claim["projection_boundaries"]["forward"] == {
        "first_collected_l3_owner": "R1",
        "last_collected_l3_owner": "R2",
        "endpoint_attachment": "not_assessed",
        "l2_delivery": "not_assessed",
    }
    assert any("tunnel state" in limitation for limitation in result["limitations"])


def test_output_service_policy_is_a_visible_packet_gate_and_abstains():
    parsed = parse.parse_run_config_interfaces(
        "interface GigabitEthernet0/1\n service-policy output POLICE-HTTPS\n"
    )["Gi0/1"]
    snap = _symmetric_snapshot()
    snap["interfaces"]["R1"]["Gi0/1"].update(parsed)
    snap["interfaces"]["R1"]["Gi0/1"]["run_config_observed"] = True
    _with_custody(snap)

    result = traffic_assurance.assess_flow(snap, _intent(return_required=False))
    stage = next(
        row for row in result["dimensions"]["policy"]["forward"]["stages"]
        if row["host"] == "R1" and row["direction"] == "out"
    )
    assert "output_service_policy" in stage["unmodeled_forwarding_gates"]
    assert stage["verdict"] == "indeterminate"
    for dimension in ("path", "mtu", "ecmp"):
        assert result["dimensions"][dimension]["forward"]["verdict"] == "indeterminate"
    assert result["verdict"] == "indeterminate"


def test_fhrp_vip_is_an_infrastructure_local_endpoint_without_a_local_host_route():
    snap = _symmetric_snapshot()
    snap["fhrp_detail"] = {
        "R2": [{"ifname": "Vlan20", "group": "20", "state": "Active", "priority": 110,
                "preempt": True, "vip": "10.2.2.254", "version": 2}],
    }
    snap["interfaces"]["R2"]["Vlan20"]["acl_out"] = "BLOCK"
    snap["acls"].setdefault("R2", {})["BLOCK"] = [_rule("deny", dport=443)]
    _with_custody(snap)

    result = traffic_assurance.assess_flow(
        snap, _intent(dst="10.2.2.254", return_required=False)
    )
    assert "infrastructure_local_endpoint" in result["unsupported_semantics"]
    assert result["verdict"] == "indeterminate"


def test_malformed_mixed_host_keys_fail_before_any_engine_sort_or_serialization():
    snap = _symmetric_snapshot()
    snap["routes"][1] = copy.deepcopy(snap["routes"]["R1"])
    result = traffic_assurance.assess_flow(snap, _intent(return_required=False))
    assert result["valid"] is False
    assert result["validation_errors"] == [
        "snapshot per-host evidence keys must be nonempty Unicode-scalar strings"
    ]
    json.dumps(result, ensure_ascii=False).encode("utf-8")


def test_malformed_interface_identity_fails_before_normalization():
    snap = _symmetric_snapshot()
    snap["interfaces"]["R1"][1] = {"acl_in": "", "acl_out": ""}
    result = traffic_assurance.assess_flow(snap, _intent(return_required=False))
    assert result["valid"] is False
    assert result["validation_errors"] == [
        "snapshot interface evidence keys must be nonempty Unicode-scalar strings"
    ]


def test_policy_based_routing_invalidates_later_selected_rib_deny():
    snap = _symmetric_snapshot()
    snap["interfaces"]["R1"]["Vlan10"]["pbr_policy"] = "DIVERT"
    snap["interfaces"]["R1"]["Gi0/1"]["acl_out"] = "BLOCK"
    snap["acls"]["R1"]["BLOCK"] = [_rule("deny", dport=443)]
    _with_custody(snap)

    result = traffic_assurance.assess_flow(snap, _intent(return_required=False))

    assert result["dimensions"]["policy"]["forward"]["selected_path_verdict"] == "refuted"
    assert result["dimensions"]["policy"]["forward"]["verdict"] == "indeterminate"
    for dimension in ("path", "mtu", "ecmp"):
        assert result["dimensions"][dimension]["forward"]["applicability"] == (
            "unmodeled_policy_based_routing"
        )
        assert result["dimensions"][dimension]["forward"]["verdict"] == "indeterminate"
    assert result["verdict"] == "indeterminate"


def test_common_acl_chain_invalidates_a_later_selected_rib_deny():
    snap = _symmetric_snapshot()
    parsed = parse.parse_run_config_interfaces(
        "interface Vlan10\n ipv4 access-group common COMMON IFACE ingress\n"
    )["Vlan10"]
    snap["interfaces"]["R1"]["Vlan10"].update(parsed)
    snap["interfaces"]["R1"]["Vlan10"]["run_config_observed"] = True
    snap["interfaces"]["R1"]["Gi0/1"]["acl_out"] = "BLOCK"
    snap["acls"]["R1"]["BLOCK"] = [_rule("deny", dport=443)]
    _with_custody(snap)

    result = traffic_assurance.assess_flow(snap, _intent(return_required=False))

    assert result["dimensions"]["policy"]["forward"]["selected_path_verdict"] == "refuted"
    assert result["dimensions"]["policy"]["forward"]["verdict"] == "indeterminate"
    assert result["dimensions"]["path"]["forward"]["verdict"] == "indeterminate"
    assert result["verdict"] == "indeterminate"


@pytest.mark.parametrize("field", ["crypto_map", "tunnel_protection"])
def test_header_transform_boundary_invalidates_later_inner_tuple_acl_deny(field):
    snap = _symmetric_snapshot()
    snap["interfaces"]["R1"]["Gi0/1"][field] = "BOUNDARY"
    snap["interfaces"]["R2"]["Gi0/1"]["acl_in"] = "BLOCK"
    snap["acls"].setdefault("R2", {})["BLOCK"] = [_rule("deny", dport=443)]
    _with_custody(snap)

    result = traffic_assurance.assess_flow(snap, _intent(return_required=False))

    policy = result["dimensions"]["policy"]["forward"]
    assert policy["selected_path_verdict"] == "refuted"
    assert policy["verdict"] == "indeterminate"
    assert result["dimensions"]["path"]["forward"]["verdict"] == "indeterminate"
    assert result["verdict"] == "indeterminate"


def test_ios_xr_acl_is_enforced_end_to_end_in_canonical_assurance():
    from cisco_toolkit import parse

    config = (
        "interface Vlan10\n ipv4 access-group BLOCK ingress\n"
        "ipv4 access-list BLOCK\n 10 deny tcp any any eq 443\n 20 permit ipv4 any any\n"
    )
    snap = _symmetric_snapshot()
    snap["interfaces"]["R1"]["Vlan10"].update(parse.parse_run_config_interfaces(config)["Vlan10"])
    snap["interfaces"]["R1"]["Vlan10"]["run_config_observed"] = True
    snap["acls"]["R1"]["BLOCK"] = parse.parse_acls(config)["BLOCK"]
    _with_custody(snap)

    denied = traffic_assurance.assess_flow(snap, _intent(return_required=False))
    assert denied["dimensions"]["policy"]["forward"]["verdict"] == "refuted"
    assert denied["verdict"] == "refuted"

    allowed = traffic_assurance.assess_flow(
        snap, _intent(dst_port=80, return_required=False)
    )
    assert allowed["dimensions"]["policy"]["forward"]["verdict"] == "proven"


def test_ios_xr_acl_attachment_suffix_keeps_the_enforced_acl():
    config = (
        "interface Vlan10\n ipv4 access-group BLOCK ingress interface-statistics hardware-count\n"
        "ipv4 access-list BLOCK\n 10 deny tcp any any eq 443\n 20 permit ipv4 any any\n"
    )
    snap = _symmetric_snapshot()
    snap["interfaces"]["R1"]["Vlan10"].update(parse.parse_run_config_interfaces(config)["Vlan10"])
    snap["interfaces"]["R1"]["Vlan10"]["run_config_observed"] = True
    snap["acls"]["R1"]["BLOCK"] = parse.parse_acls(config)["BLOCK"]
    _with_custody(snap)

    result = traffic_assurance.assess_flow(snap, _intent(return_required=False))
    assert result["dimensions"]["policy"]["forward"]["verdict"] == "refuted"
    assert result["verdict"] == "refuted"


def test_asa_access_group_resolves_nameif_but_base_stateful_policy_abstains():
    config = (
        "interface Vlan10\n"
        " nameif outside\n"
        " security-level 0\n"
        " ip address 10.1.1.1 255.255.255.0\n"
        "access-list BLOCK extended deny tcp any any eq 443\n"
        "access-list BLOCK extended permit ip any any\n"
        "access-group BLOCK in interface outside\n"
    )
    parsed_interfaces = parse.parse_run_config_interfaces(config)
    parsed_acls = parse.parse_acls(config)
    assert parsed_interfaces["Vlan10"]["global_acl_in"] == "BLOCK"
    assert "asa_stateful_firewall" in parsed_interfaces["Vlan10"]["global_policy_gates"]
    assert [row["action"] for row in parsed_acls["BLOCK"]] == ["deny", "permit"]

    snap = _symmetric_snapshot()
    snap["interfaces"]["R1"]["Vlan10"].update(parsed_interfaces["Vlan10"])
    snap["interfaces"]["R1"]["Vlan10"]["run_config_observed"] = True
    snap["acls"]["R1"]["BLOCK"] = parsed_acls["BLOCK"]
    _with_custody(snap)

    result = traffic_assurance.assess_flow(snap, _intent(return_required=False))
    ingress = next(
        stage for stage in result["dimensions"]["policy"]["forward"]["stages"]
        if stage["role"] == "source_ingress"
    )
    assert ingress["acl"] == "BLOCK"
    assert ingress["selected_stage_verdict"] == "refuted"
    assert {"asa_global_policy", "stateful_inspection"}.issubset(
        ingress["unmodeled_forwarding_gates"]
    )
    for dimension in ("path", "policy", "mtu", "ecmp"):
        assert result["dimensions"][dimension]["forward"]["verdict"] == "indeterminate"
    assert result["verdict"] == "indeterminate"


def test_asa_security_level_default_policy_never_becomes_no_acl_proof():
    parsed = parse.parse_run_config_interfaces(
        "interface Vlan10\n"
        " nameif outside\n"
        " security-level 0\n"
        " ip address 10.1.1.1 255.255.255.0\n"
    )["Vlan10"]
    snap = _symmetric_snapshot()
    snap["interfaces"]["R1"]["Vlan10"].update(parsed)
    snap["interfaces"]["R1"]["Vlan10"]["run_config_observed"] = True
    _with_custody(snap)

    result = traffic_assurance.assess_flow(snap, _intent(return_required=False))
    ingress = next(
        stage for stage in result["dimensions"]["policy"]["forward"]["stages"]
        if stage["role"] == "source_ingress"
    )
    assert ingress["native_result"] == "INDETERMINATE"
    assert "stateful_inspection" in ingress["unmodeled_forwarding_gates"]
    assert result["dimensions"]["policy"]["forward"]["verdict"] == "indeterminate"
    assert result["verdict"] == "indeterminate"


def test_asa_global_access_group_and_service_policy_are_fixed_unmodeled_gates():
    config = (
        "interface Vlan10\n"
        " nameif outside\n"
        " security-level 0\n"
        "access-group PRIVATE_FILTER global\n"
        "service-policy PRIVATE_POLICY global\n"
    )
    parsed = parse.parse_run_config_interfaces(config)["Vlan10"]
    assert set(parsed["global_policy_gates"].split(",")) == {
        "asa_global_access_group", "asa_global_service_policy", "asa_stateful_firewall",
    }
    assert "PRIVATE" not in parsed["global_policy_gates"]

    snap = _symmetric_snapshot()
    snap["interfaces"]["R1"]["Vlan10"].update(parsed)
    snap["interfaces"]["R1"]["Vlan10"]["run_config_observed"] = True
    _with_custody(snap)
    result = traffic_assurance.assess_flow(snap, _intent(return_required=False))
    assert result["dimensions"]["path"]["forward"]["verdict"] == "indeterminate"
    assert result["dimensions"]["policy"]["forward"]["verdict"] == "indeterminate"
    assert result["verdict"] == "indeterminate"


def test_acl_based_forwarding_invalidates_selected_rib_dimensions_and_path_claim():
    config = (
        "ip access-list extended CLIENT-IN\n"
        " permit tcp any any eq 443 nexthop1 ipv4 192.0.2.2\n"
        " deny ip any any\n"
    )
    snap = _symmetric_snapshot()
    snap["acls"]["R1"]["CLIENT-IN"] = parse.parse_acls(config)["CLIENT-IN"]
    _with_custody(snap)

    result = traffic_assurance.assess_flow(snap, _intent(return_required=False))
    ingress = next(
        stage for stage in result["dimensions"]["policy"]["forward"]["stages"]
        if stage["role"] == "source_ingress"
    )
    assert "acl_based_forwarding" in ingress["unmodeled_forwarding_gates"]
    for dimension in ("path", "mtu", "ecmp"):
        assert result["dimensions"][dimension]["forward"]["verdict"] == "indeterminate"
    path_claim = next(claim for claim in result["claims"] if claim["id"].endswith(".path"))
    assert path_claim["verdict"] == "indeterminate"
    assert result["verdict"] == "indeterminate"


@pytest.mark.parametrize(
    ("route_line", "source"),
    [
        ("l 10.2.2.0/24 [115/10] via 192.0.2.2, Gi0/1", "lisp"),
        ("H 10.2.2.0/24 [250/0] via 192.0.2.2, Tunnel0", "nhrp"),
    ],
)
def test_lisp_and_nhrp_next_hops_are_not_fabricated_as_local_reachability(route_line, source):
    from cisco_toolkit import parse

    snap = _symmetric_snapshot()
    parsed = parse.parse_ip_routes(route_line)["10.2.2.0/24"]["entries"][0]
    assert parsed["source"] == source
    snap["routes"]["R1"] = [
        {"prefix": "10.1.1.0/24", "source": "connected", "out_intf": "Vlan10"},
        parsed,
    ]
    snap = _with_custody(snap)

    result = traffic_assurance.assess_flow(snap, _intent(return_required=False))
    assert result["dimensions"]["path"]["forward"]["verdict"] != "proven"
    assert result["verdict"] == "indeterminate"


def test_unverified_next_hop_owner_downgrades_path_policy_and_ecmp():
    snap = _symmetric_snapshot()
    snap["routes"]["R1"] = [
        {"prefix": "10.1.1.0/24", "source": "connected", "out_intf": "Vlan10"},
        {"prefix": "192.0.2.0/24", "source": "connected", "out_intf": "Gi0/1"},
        {"prefix": "10.2.2.0/24", "source": "static", "next_hop": "192.0.2.254", "out_intf": "Gi0/1"},
    ]
    snap["routes"]["R2"] = [
        {"prefix": "192.0.2.0/24", "source": "connected", "out_intf": "Gi0/1"},
        {"prefix": "10.2.2.0/24", "source": "connected", "out_intf": "Vlan20"},
    ]
    snap["interfaces"]["R1"]["Gi0/1"]["svi_ip"] = "192.0.2.1/24"
    snap["interfaces"]["R2"]["Gi0/1"]["svi_ip"] = "192.0.2.2/24"
    snap = _with_custody(snap)

    result = traffic_assurance.assess_flow(snap, _intent(return_required=False))
    assert result["dimensions"]["path"]["forward"]["verdict"] == "not_observed"
    assert result["dimensions"]["policy"]["forward"]["verdict"] == "not_observed"
    assert result["dimensions"]["ecmp"]["forward"]["verdict"] == "not_observed"
    assert result["claims"][0]["verdict"] != "proven"
    assert result["claims"][1]["verdict"] != "proven"
    assert result["verdict"] == "indeterminate"


def test_secondary_interface_address_is_treated_as_infrastructure_local():
    snap = _symmetric_snapshot()
    snap["interfaces"]["R1"]["Vlan10"].update({
        "svi_ip": "10.1.1.1 255.255.255.0",
        "svi_ips": "10.1.1.1 255.255.255.0;10.1.1.2 255.255.255.0",
    })
    _with_custody(snap)
    result = traffic_assurance.assess_flow(
        snap, _intent(src="10.1.1.2", return_required=False)
    )
    assert "infrastructure_local_endpoint" in result["unsupported_semantics"]
    assert result["dimensions"]["policy"]["forward"]["verdict"] == "indeterminate"
    assert result["verdict"] == "indeterminate"


def test_fhrp_local_host_route_marks_virtual_ip_as_infrastructure_local():
    snap = _symmetric_snapshot()
    snap["routes"]["R1"].append({
        "prefix": "10.1.1.254/32", "source": "hsrp", "next_hop": "10.1.1.254", "out_intf": "Vlan10",
    })
    snap = _with_custody(snap)
    result = traffic_assurance.assess_flow(
        snap, _intent(dst="10.1.1.254", return_required=False)
    )
    assert "infrastructure_local_endpoint" in result["unsupported_semantics"]
    assert result["verdict"] == "indeterminate"


def test_recursive_next_hop_is_not_certified_or_used_as_a_transit_acl_interface():
    snap = _symmetric_snapshot()
    snap["routes"] = {
        "R1": [
            {"prefix": "10.1.1.0/24", "source": "connected", "out_intf": "Vlan10"},
            {"prefix": "192.0.12.0/30", "source": "connected", "out_intf": "Gi0/1"},
            {"prefix": "3.3.3.3/32", "source": "static", "next_hop": "192.0.12.2", "out_intf": "Gi0/1"},
            {"prefix": "10.9.9.0/24", "source": "bgp", "next_hop": "3.3.3.3"},
        ],
        "R2": [
            {"prefix": "192.0.12.0/30", "source": "connected", "out_intf": "Gi0/1"},
            {"prefix": "10.9.9.0/24", "source": "static", "out_intf": "Null0"},
        ],
        "R3": [
            {"prefix": "3.3.3.3/32", "source": "local", "out_intf": "Lo0"},
            {"prefix": "10.9.9.0/24", "source": "connected", "out_intf": "Vlan99"},
        ],
    }
    snap["interfaces"] = {
        "R1": {
            "Vlan10": {"run_config_observed": True, "acl_in": "CLIENT-IN", "acl_out": "", "mtu": 1500},
            "Gi0/1": {"run_config_observed": True, "acl_in": "", "acl_out": "", "mtu": 1500,
                      "svi_ip": "192.0.12.1/30"},
        },
        "R2": {"Gi0/1": {"run_config_observed": True, "acl_in": "", "acl_out": "", "mtu": 1500,
                            "svi_ip": "192.0.12.2/30"}},
        "R3": {
            "Lo0": {"run_config_observed": True, "acl_in": "BLOCK", "acl_out": "", "mtu": 1500,
                    "svi_ip": "3.3.3.3/32"},
            "Vlan99": {"run_config_observed": True, "acl_in": "", "acl_out": "", "mtu": 1500},
        },
    }
    snap["acls"]["R3"] = {"BLOCK": [_rule("deny", dport=443)]}
    snap = _with_custody(snap)

    result = traffic_assurance.assess_flow(
        snap, _intent(dst="10.9.9.9", return_required=False)
    )
    assert result["dimensions"]["path"]["forward"]["status"] == (
        "lower_bound:recursive_next_hop_not_modeled"
    )
    assert all(stage["host"] != "R3" for stage in result["dimensions"]["policy"]["forward"]["stages"])
    assert result["verdict"] == "indeterminate"


def test_malformed_host_keys_make_requested_failure_invalid_without_crashing():
    snap = _symmetric_snapshot()
    snap["stp_roots"] = {1: {}, "R1": {}}
    result = traffic_assurance.assess_flow(
        snap, _intent(), failure={"action": "fail_node", "id": "R1"}
    )
    assert result["failure"]["mutation"]["valid"] is False
    assert result["failure"]["mutation"]["validation_errors"] == [
        "snapshot exceeds the safe JSON mutation depth, size, or strict-scalar contract"
    ]
    assert result["verdict"] == "indeterminate"


def test_explicit_ipv4_mtu_overrides_larger_link_mtu_for_assurance():
    from cisco_toolkit import parse

    snap = _symmetric_snapshot()
    for ports in snap["interfaces"].values():
        for record in ports.values():
            record["mtu"] = "9216"
    parsed = parse.parse_run_config_interfaces(
        "interface Gi0/1\n mtu 9216\n ip mtu 1500\n"
    )["Gi0/1"]
    snap["interfaces"]["R1"]["Gi0/1"].update(parsed)
    snap["interfaces"]["R1"]["Gi0/1"]["run_config_observed"] = True
    _with_custody(snap)

    result = traffic_assurance.assess_flow(
        snap, _intent(required_mtu=1600, return_required=False)
    )

    assert snap["interfaces"]["R1"]["Gi0/1"]["link_mtu"] == "9216"
    assert snap["interfaces"]["R1"]["Gi0/1"]["ip_mtu"] == "1500"
    assert result["dimensions"]["mtu"]["forward"]["verdict"] == "refuted"
    assert result["verdict"] == "refuted"


def test_ios_xr_explicit_ipv4_mtu_is_used_and_bare_frame_mtu_abstains():
    def base() -> dict:
        snap = _symmetric_snapshot()
        for ports in snap["interfaces"].values():
            for record in ports.values():
                record["mtu"] = "9216"
        return snap

    explicit = base()
    parsed = parse.parse_run_config_interfaces(
        "interface Gi0/1\n mtu 1514\n ipv4 mtu 1500\n"
    )["Gi0/1"]
    explicit["interfaces"]["R1"]["Gi0/1"].update(parsed)
    explicit["interfaces"]["R1"]["Gi0/1"]["run_config_observed"] = True
    _with_custody(explicit)
    explicit_result = traffic_assurance.assess_flow(
        explicit, _intent(required_mtu=1508, return_required=False),
    )
    assert explicit_result["dimensions"]["mtu"]["forward"]["verdict"] == "refuted"
    assert explicit_result["verdict"] == "refuted"

    ambiguous = base()
    bare = parse.parse_run_config_interfaces(
        "interface Gi0/1\n mtu 1514\n"
    )["Gi0/1"]
    ambiguous["interfaces"]["R1"]["Gi0/1"].update(bare)
    ambiguous["interfaces"]["R1"]["Gi0/1"]["run_config_observed"] = True
    _with_custody(ambiguous)
    ambiguous_result = traffic_assurance.assess_flow(
        ambiguous, _intent(required_mtu=1508, return_required=False),
    )
    assert ambiguous_result["dimensions"]["mtu"]["forward"]["verdict"] == "not_observed"
    assert ambiguous_result["verdict"] == "indeterminate"


@pytest.mark.parametrize(
    "rule",
    [
        "ip nat inside source static 10.1.1.10 203.0.113.10",
        "ip nat inside source static tcp 10.1.1.10 443 203.0.113.10 8443",
    ],
)
def test_configured_static_nat_abstains_instead_of_certifying_the_pretranslation_tuple(rule):
    snap = _symmetric_snapshot()
    snap["nat"] = {
        "R1": parse.parse_nat(
            "interface Vlan10\n"
            " ip nat inside\n"
            "interface GigabitEthernet0/1\n"
            " ip nat outside\n"
            f"{rule}\n"
        )
    }
    _with_custody(snap)

    result = traffic_assurance.assess_flow(
        snap, _intent(return_required=False)
    )

    assert result["supported"] is False
    assert result["unsupported_semantics"] == ["network_address_translation_not_modeled"]
    assert result["verdict"] == "indeterminate"
    for dimension in ("path", "policy", "mtu", "ecmp"):
        assert result["dimensions"][dimension]["forward"]["verdict"] == "indeterminate"
    assert all(claim["verdict"] == "indeterminate" for claim in result["claims"])
    assert "nat" in result["sources"]
    assert any("NAT/PAT translation" in limitation for limitation in result["limitations"])


def test_deep_or_cyclic_nat_evidence_abstains_without_recursive_failure():
    nested: dict = {}
    cursor = nested
    for _index in range(1_200):
        child: dict = {}
        cursor["child"] = child
        cursor = child
    snap = _symmetric_snapshot()
    snap["nat"] = {"R1": nested}
    _with_custody(snap)
    result = traffic_assurance.assess_flow(snap, _intent(return_required=False))
    assert result["verdict"] == "indeterminate"
    assert "network_address_translation_not_modeled" in result["unsupported_semantics"]
    json.dumps(result, ensure_ascii=False).encode("utf-8")


def test_deep_unrelated_snapshot_branch_makes_requested_failure_invalid_without_deepcopy_crash():
    nested: dict = {}
    cursor = nested
    for _index in range(1_200):
        child: dict = {}
        cursor["child"] = child
        cursor = child
    snap = _symmetric_snapshot()
    snap["extra"] = nested

    result = traffic_assurance.assess_flow(
        snap, _intent(), failure={"action": "fail_node", "id": "R2"}
    )

    assert result["failure"]["mutation"]["valid"] is False
    assert result["failure"]["verdict"] == "indeterminate"
    assert result["verdict"] == "indeterminate"
    json.dumps(result, ensure_ascii=False).encode("utf-8")


def test_requested_deny_claims_are_expectation_aware_and_preserve_raw_observations():
    acl_snap = _symmetric_snapshot()
    acl_snap["acls"]["R1"]["CLIENT-IN"] = [_rule("deny", dport=443)]
    _with_custody(acl_snap)
    acl_result = traffic_assurance.assess_flow(
        acl_snap, _intent(expected="deny", return_required=False, required_mtu=None)
    )
    policy_claim = next(claim for claim in acl_result["claims"] if claim["id"].endswith(".policy"))
    assert acl_result["verdict"] == "proven"
    assert policy_claim["observed_verdict"] == "refuted"
    assert policy_claim["verdict"] == "proven"

    drop_snap = _symmetric_snapshot()
    drop_snap["routes"]["R1"] = list(drop_snap["routes"]["R1"])
    drop_snap["routes"]["R1"][-1] = {
        "prefix": "10.2.2.0/24", "source": "static", "next_hop": "", "out_intf": "Null0",
    }
    _with_custody(drop_snap)
    drop_result = traffic_assurance.assess_flow(
        drop_snap, _intent(expected="deny", return_required=False, required_mtu=None)
    )
    path_claim = next(claim for claim in drop_result["claims"] if claim["id"].endswith(".path"))
    assert drop_result["verdict"] == "proven"
    assert path_claim["observed_verdict"] == "refuted"
    assert path_claim["verdict"] == "proven"


def test_disclosure_is_additive_and_cutover_step_has_one_public_mutation_owner():
    snap = _symmetric_snapshot()
    default = fib.trace_bidirectional(snap, "10.1.1.10", "10.2.2.20")
    disclosed = fib.trace_bidirectional(snap, "10.1.1.10", "10.2.2.20", disclose=True)
    assert "drop_evidence" not in default["forward"]
    assert disclosed["forward"]["drop_evidence"] == ""
    assert disclosed["forward"]["ecmp_dropping_legs"] == []

    before = copy.deepcopy(snap)
    after, receipt = cutover_sim.apply_cutover_step(
        snap, {"action": "shut_link", "host": "R1", "interface": "Gi0/1"}
    )
    assert snap == before
    assert receipt == {
        "action": "shut_link",
        "params": {"host": "R1", "interface": "Gi0/1"},
        "valid": True,
        "validation_errors": [],
        "is_noop": False,
        "removed_hosts": [],
        "ignored_field_count": 0,
    }
    assert len(after["routes"]["R1"]) < len(snap["routes"]["R1"])


def test_cutover_receipt_accounts_for_an_l2_only_removed_host():
    snap = {
        "routes": {},
        "stp_roots": {"L2ONLY": {"10": {"is_root": True}}},
        "fhrp_detail": {"L2ONLY": []},
    }
    after, receipt = cutover_sim.apply_cutover_step(snap, {"action": "fail_node", "id": "L2ONLY"})
    assert receipt["valid"] is True
    assert receipt["is_noop"] is False
    assert receipt["removed_hosts"] == ["L2ONLY"]
    assert "L2ONLY" not in after["stp_roots"]
    assert snap["stp_roots"]["L2ONLY"] == {"10": {"is_root": True}}


def test_cutover_step_never_echoes_or_serializes_unknown_external_values():
    import json

    secret_object = object()
    _after, receipt = cutover_sim.apply_cutover_step(
        _symmetric_snapshot(),
        {"action": "fail_node", "id": "R2", "credential": secret_object},
    )
    assert receipt["params"] == {"id": "R2"}
    assert receipt["ignored_field_count"] == 1
    assert "credential" not in json.dumps(receipt)

    result = traffic_assurance.assess_flow(
        _symmetric_snapshot(), _intent(),
        failure={"action": "fail_node", "id": "R2", "credential": secret_object},
    )
    encoded = json.dumps(result)
    assert "credential" not in encoded
    assert "object at" not in encoded

    sentinel = "CUTOVER_PRIVATE_ACTION_SENTINEL"
    unsupported = traffic_assurance.assess_flow(
        _symmetric_snapshot(), _intent(), failure={"action": sentinel},
    )
    unsupported_encoded = json.dumps(unsupported)
    assert unsupported["failure"]["action"] == "unsupported_action"
    assert unsupported["failure"]["mutation"]["validation_errors"] == ["unsupported action"]
    assert sentinel not in unsupported_encoded


@pytest.mark.parametrize(
    ("host", "interface", "field"),
    [
        ("R1", "Vlan10", "pbr_policy"),
        ("R1", "Vlan10", "urpf_mode"),
        ("R1", "Vlan10", "security_zone"),
        ("R1", "Vlan10", "inspection_policy_in"),
        ("R1", "Vlan10", "acl_in_unmodeled"),
        ("R1", "Vlan10", "service_policy_in"),
        ("R1", "Gi0/1", "service_policy_out"),
        ("R1", "Gi0/1", "inspection_policy_out"),
        ("R1", "Vlan10", "crypto_map"),
        ("R1", "Vlan10", "tunnel_protection"),
        ("R1", "Vlan10", "vacl_policy"),
        ("R1", "Vlan10", "trustsec_sgacl"),
        ("R1", "Vlan10", "wccp_redirection_in"),
        ("R1", "Vlan10", "mpls_forwarding"),
        ("R1", "Vlan10", "flowspec_policy"),
        ("R1", "Vlan10", "ips_policy_in"),
        ("R1", "Vlan10", "admission_policy"),
    ],
)
def test_malformed_recognized_gate_scalar_precedes_downstream_deny_and_taints_every_dimension(
        host, interface, field):
    snap = _symmetric_snapshot()
    snap["interfaces"][host][interface][field] = {"private": "DO_NOT_ECHO"}
    snap["interfaces"]["R2"]["Gi0/1"]["acl_in"] = "DOWNSTREAM-DENY"
    snap["acls"].setdefault("R2", {})["DOWNSTREAM-DENY"] = [_rule("deny", dport=443)]
    _with_custody(snap)

    result = traffic_assurance.assess_flow(snap, _intent(return_required=False))
    stages = result["dimensions"]["policy"]["forward"]["stages"]
    malformed = next(stage for stage in stages if stage.get("provenance_gap"))

    assert malformed["provenance_gap"] == "forwarding_gate_scalar_value_malformed"
    assert malformed["unmodeled_forwarding_gates"] == ["malformed_forwarding_gate_evidence"]
    for dimension in ("path", "policy", "mtu", "ecmp"):
        assert result["dimensions"][dimension]["forward"]["verdict"] == "indeterminate"
    assert result["verdict"] == "indeterminate"
    assert "DO_NOT_ECHO" not in json.dumps(result)


def test_invalid_unicode_and_whitespace_gate_tokens_never_collapse_to_absence():
    for value in ("\ud800", "   "):
        snap = _symmetric_snapshot()
        snap["interfaces"]["R1"]["Vlan10"]["pbr_policy"] = value
        _with_custody(snap)
        result = traffic_assurance.assess_flow(snap, _intent(return_required=False))
        assert result["dimensions"]["policy"]["forward"]["verdict"] == "indeterminate"
        assert result["dimensions"]["path"]["forward"]["verdict"] == "indeterminate"
        assert result["verdict"] == "indeterminate"


@pytest.mark.parametrize(
    ("config", "gate"),
    [
        ("interface Vlan10\n cts role-based enforcement\n", "identity_policy"),
        ("interface Vlan10\n ip wccp 61 redirect in\n", "wccp_redirection"),
        ("interface Vlan10\n mpls ip\n mpls mtu 1600\n", "mpls_forwarding"),
        ("interface Vlan10\n ip ips SENSOR in\n", "intrusion_prevention"),
        ("interface Vlan10\n ip admission NAC\n", "network_admission"),
        ("interface Vlan10\n ip auth-proxy AUTHRULE http\n", "network_admission"),
        (
            "interface Vlan10\n service-policy type service-chain input dynamic\n",
            "service_chaining",
        ),
        (
            "ip tcp intercept list TCP-ACL\n"
            "ip tcp intercept mode intercept\n"
            "interface Vlan10\n ip address 10.1.1.1 255.255.255.0\n",
            "tcp_intercept",
        ),
        (
            "router bgp 65000\n address-family ipv4 flowspec\n"
            "  local-install interface-all\n"
            "interface Vlan10\n ip address 10.1.1.1 255.255.255.0\n",
            "bgp_flowspec",
        ),
    ],
)
def test_new_bounded_registry_gates_reach_canonical_composer(config, gate):
    parsed = parse.parse_run_config_interfaces(config)["Vlan10"]
    snap = _symmetric_snapshot()
    snap["interfaces"]["R1"]["Vlan10"].update(parsed)
    snap["interfaces"]["R1"]["Vlan10"]["run_config_observed"] = True
    _with_custody(snap)

    result = traffic_assurance.assess_flow(snap, _intent(return_required=False))
    ingress = next(
        stage for stage in result["dimensions"]["policy"]["forward"]["stages"]
        if stage["role"] == "source_ingress"
    )

    assert gate in ingress["unmodeled_forwarding_gates"]
    for dimension in ("path", "policy", "mtu", "ecmp"):
        assert result["dimensions"][dimension]["forward"]["verdict"] == "indeterminate"
    assert result["verdict"] == "indeterminate"


def test_wccp_redirection_precedes_and_invalidates_a_downstream_exact_tuple_deny():
    snap = _symmetric_snapshot()
    snap["interfaces"]["R1"]["Vlan10"]["wccp_redirection_in"] = "configured"
    snap["interfaces"]["R2"]["Gi0/1"]["acl_in"] = "DOWNSTREAM-DENY"
    snap["acls"].setdefault("R2", {})["DOWNSTREAM-DENY"] = [_rule("deny", dport=443)]
    _with_custody(snap)

    result = traffic_assurance.assess_flow(snap, _intent(return_required=False))

    assert result["dimensions"]["policy"]["forward"]["selected_path_verdict"] == "refuted"
    assert result["dimensions"]["policy"]["forward"]["verdict"] == "indeterminate"
    assert result["claims"][1]["verdict"] == "indeterminate"
    assert result["verdict"] == "indeterminate"


def test_ambiguous_candidate_only_wccp_receipt_is_not_discharged_by_opposite_direction_field():
    snap = _symmetric_snapshot()
    snap["interfaces"]["R1"]["Vlan10"]["forwarding_gate_candidates"] = "wccp_redirection"
    snap["interfaces"]["R1"]["Vlan10"]["wccp_redirection_out"] = "configured"
    snap["interfaces"]["R2"]["Gi0/1"]["acl_in"] = "DOWNSTREAM-DENY"
    snap["acls"].setdefault("R2", {})["DOWNSTREAM-DENY"] = [_rule("deny", dport=443)]
    _with_custody(snap)

    result = traffic_assurance.assess_flow(snap, _intent(return_required=False))
    ingress = result["dimensions"]["policy"]["forward"]["stages"][0]

    assert ingress["unmodeled_forwarding_gates"] == ["candidate_projection_incomplete"]
    assert result["dimensions"]["policy"]["forward"]["selected_path_verdict"] == "refuted"
    for dimension in ("path", "policy", "mtu", "ecmp"):
        assert result["dimensions"][dimension]["forward"]["verdict"] == "indeterminate"
    assert result["verdict"] == "indeterminate"


def test_network_admission_dynamic_acl_order_weakens_same_stage_but_not_later_deny():
    same_stage = _symmetric_snapshot()
    same_stage["interfaces"]["R1"]["Vlan10"]["admission_policy"] = "configured"
    same_stage["acls"]["R1"]["CLIENT-IN"] = [_rule("deny", dport=443)]
    _with_custody(same_stage)

    same_result = traffic_assurance.assess_flow(
        same_stage, _intent(return_required=False),
    )
    ingress = same_result["dimensions"]["policy"]["forward"]["stages"][0]
    assert ingress["selected_static_acl_verdict"] == "refuted"
    assert ingress["verdict"] == "indeterminate"
    assert same_result["dimensions"]["policy"]["forward"]["verdict"] == "indeterminate"
    assert same_result["verdict"] == "indeterminate"

    downstream = _symmetric_snapshot()
    downstream["interfaces"]["R1"]["Vlan10"]["admission_policy"] = "configured"
    downstream["interfaces"]["R2"]["Gi0/1"]["acl_in"] = "DOWNSTREAM-DENY"
    downstream["acls"].setdefault("R2", {})["DOWNSTREAM-DENY"] = [_rule("deny", dport=443)]
    _with_custody(downstream)

    downstream_result = traffic_assurance.assess_flow(
        downstream, _intent(return_required=False),
    )
    assert downstream_result["dimensions"]["policy"]["forward"]["verdict"] == "refuted"
    assert downstream_result["dimensions"]["path"]["forward"]["verdict"] == "indeterminate"
    assert downstream_result["verdict"] == "refuted"


def test_service_chain_redirection_invalidates_a_downstream_selected_rib_acl_deny():
    snap = _symmetric_snapshot()
    parsed = parse.parse_run_config_interfaces(
        "interface Vlan10\n service-policy type service-chain input dynamic\n"
    )["Vlan10"]
    snap["interfaces"]["R1"]["Vlan10"].update(parsed)
    snap["interfaces"]["R1"]["Vlan10"]["run_config_observed"] = True
    snap["interfaces"]["R2"]["Gi0/1"]["acl_in"] = "DOWNSTREAM-DENY"
    snap["acls"].setdefault("R2", {})["DOWNSTREAM-DENY"] = [_rule("deny", dport=443)]
    _with_custody(snap)

    result = traffic_assurance.assess_flow(snap, _intent(return_required=False))

    assert parsed["service_policy_in"] == "service-chain:dynamic"
    assert result["dimensions"]["policy"]["forward"]["selected_path_verdict"] == "refuted"
    assert result["dimensions"]["policy"]["forward"]["verdict"] == "indeterminate"
    for dimension in ("path", "mtu", "ecmp"):
        assert result["dimensions"][dimension]["forward"]["verdict"] == "indeterminate"
    assert result["verdict"] == "indeterminate"


@pytest.mark.parametrize(
    "mutation",
    ["vacl", "nat", "acls", "object_groups", "trustsec", "wccp"],
)
def test_malformed_global_and_gate_type_mutations_cannot_collide_with_absence_digest(mutation):
    snap = _symmetric_snapshot()
    if mutation == "vacl":
        target_kind = "global_forwarding_config"
        snap["interfaces"]["R1"]["Vlan10"]["vacl_policy"] = {"private": "REDIRECT"}
    elif mutation == "nat":
        target_kind = "global_forwarding_config"
        snap["nat"]["R1"] = [{"private": "NAT"}]
    elif mutation == "acls":
        target_kind = "acl_definitions"
        snap["acls"]["R1"] = [{"private": "ACL"}]
    elif mutation == "object_groups":
        target_kind = "acl_definitions"
        snap["object_groups"]["R1"] = [{"private": "GROUP"}]
    elif mutation == "trustsec":
        target_kind = "interface_attachments"
        snap["interfaces"]["R1"]["Vlan10"]["trustsec_sgacl"] = {"private": "SGACL"}
    else:
        target_kind = "interface_attachments"
        snap["interfaces"]["R1"]["Vlan10"]["wccp_redirection_in"] = {"private": "WCCP"}
    status = traffic_assurance._custody_cell(snap, "R1", target_kind)["status"]
    if mutation in {"nat", "acls", "object_groups"}:
        assert status == "content_binding_unavailable"
    else:
        assert status == "content_changed_after_custody"
    result = traffic_assurance.assess_flow(snap, _intent(return_required=False))
    assert result["verdict"] == "indeterminate"
    assert "private" not in json.dumps(result).lower()


@pytest.mark.parametrize("section", ["interfaces", "acls", "object_groups", "nat"])
@pytest.mark.parametrize("malformed", [[], "", 0, False, None])
def test_current_run_per_host_evidence_envelopes_require_explicit_dicts(section, malformed):
    snap = _symmetric_snapshot()
    snap[section]["R1"] = malformed
    _with_custody(snap)

    affected_kinds = (
        ("interface_attachments", "global_forwarding_config")
        if section == "interfaces"
        else ("acl_definitions", "global_forwarding_config")
    )
    for kind in affected_kinds:
        assert traffic_assurance._custody_cell(snap, "R1", kind)["status"] == (
            "content_binding_unavailable"
        )
    result = traffic_assurance.assess_flow(snap, _intent(return_required=False))
    assert result["verdict"] == "indeterminate"
    if section == "nat":
        assert traffic_assurance._has_configured_nat(snap["nat"]) is True
        assert "network_address_translation_not_modeled" in result["unsupported_semantics"]


def test_explicit_empty_per_host_owner_maps_remain_valid_absence_evidence():
    snap = _symmetric_snapshot()
    for section in ("acls", "object_groups", "nat"):
        snap[section]["R2"] = {}
    _with_custody(snap)

    for kind in ("acl_definitions", "global_forwarding_config", "interface_attachments"):
        assert traffic_assurance._custody_cell(snap, "R2", kind)["status"] == "ok"
    assert traffic_assurance._has_configured_nat(snap["nat"]) is False
