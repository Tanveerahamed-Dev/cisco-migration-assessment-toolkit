"""Hosted-only controls for the stored carriage owner (``vlan_carriage/2``).

Every interface record comes from the real producer: synthetic capture text is written to a collection directory
and read back by ``build.build_interfaces`` (``parse_show_interface_trunk_table`` and the trunk assignments in
build.py, the etherchannel and CDP joins), then ``compute_cable_map`` and ``produce_stp_topology_observation``. No
interface record is hand-built. Deliberate mutations of the producer's stored output are labelled as such; no local
test run or regenerated golden is implied by this file. The final CPU-dispatch controls use the existing PURE
in-memory bundle fixture and real STP/carriage owners; they make no additional CLI/parser or capture claim.
"""
from copy import deepcopy
from dataclasses import asdict
import json

import pytest

from cisco_toolkit import build
from cisco_toolkit import vlan_carriage as vc
from cisco_toolkit.analyze import _canon_host, _link_carries, compute_cable_map
from cisco_toolkit.parse import parse_show_interface_trunk_table
from cisco_toolkit.ssot import ABSTENTION_STATES
from cisco_toolkit.stp_topology import (
    ROLE_EVIDENCE_INTEGRITY_CODES, _FINDING_CODES, produce_stp_topology_observation,
    validate_stp_topology_observation,
)
from cisco_toolkit.textutils import normalize_ifname
from cisco_toolkit.vlan_carriage import (
    CODE_ALPHABET, END_CODES, STATES, VERDICT_CODES, _Inputs, carriage_host_identity, carriage_join_interface,
    carriage_observation_admission, carriage_port_identity, carriage_role_rows, carriage_row_cables,
    compute_vlan_carriage, validate_vlan_carriage, vlan_row_identity,
)

import synthetic_fixtures as fx

A, B = "switch-a", "switch-b"
PORT = "Gi1/0/1"
LONG = "GigabitEthernet1/0/1"


# ---------------------------------------------------------------------------------------------------------------
# capture text and the real producer
# ---------------------------------------------------------------------------------------------------------------
def _ios_trunk(rows):
    """IOS 'show interfaces trunk'. rows: (port, allowed or None, native, live). A live row is listed in the status
    table (so build promotes the port to mode Trunk); a None allowance is not listed in the allowed table."""
    top = "".join(f"{port:<11} on               802.1q         trunking      {native}\n"
                  for port, _allowed, native, live in rows if live)
    allowed = "".join(f"{port:<11} {value}\n" for port, value, _native, _live in rows if value is not None)
    return ("Port        Mode             Encapsulation  Status        Native vlan\n" + top
            + "\nPort        Vlans allowed on trunk\n" + allowed)


def _nexus_trunk(rows, forwarding=None):
    """NX-OS 'show interface trunk' with its two-line header. rows: (port, native, status, channel, allowed). A
    later 'STP Forwarding' table follows, as on a real Nexus (the allowed section must end at its header)."""
    top = "".join(f"{port:<13} {native:<7} {status:<13} {channel or '--'}\n" for port, native, status, channel, _ in rows)
    allowed = "".join(f"{port:<13} {value}\n" for port, _n, _s, _c, value in rows)
    stp = "".join(f"{port:<13} {(forwarding or {}).get(port, 'none')}\n" for port, *_rest in rows)
    rule = "-" * 80 + "\n"
    return ("\n" + rule + "Port          Native  Status        Port\n              Vlan                  Channel\n" + rule
            + top + "\n" + rule + "Port          Vlans Allowed on Trunk\n" + rule + allowed
            + "\n" + rule + "Port          Vlans Err-disabled on Trunk\n" + rule
            + "".join(f"{port:<13} none\n" for port, *_rest in rows)
            + "\n" + rule + "Port          STP Forwarding\n" + rule + stp)


def _cdp(rows, platform="cisco WS-C3850-24T"):
    """'show cdp neighbors detail'. rows: (local port, peer device id, peer port)."""
    return "".join(f"-------------------------\nDevice ID: {peer}\nEntry address(es):\n  IP address: 192.0.2.1\n"
                   f"Platform: {platform},  Capabilities: Router Switch\n"
                   f"Interface: {local},  Port ID (outgoing port): {remote}\nHoldtime : 150 sec\n"
                   for local, peer, remote in rows)


def _etherchannel(groups):
    """IOS 'show etherchannel summary'. groups: (channel number, member ports)."""
    return ("Group  Port-channel  Protocol    Ports\n------+-------------+-----------+---------------------------\n"
            + "".join(f"{n:<6} Po{n}(SU)         LACP      " + "    ".join(m + "(P)" for m in members) + "\n"
                      for n, members in groups))


def _portchannel(groups):
    """NX-OS 'show port-channel summary'."""
    return ("Group Port-       Type     Protocol  Member Ports\n      Channel\n" + "-" * 80 + "\n"
            + "".join(f"{n:<5} Po{n}(SU)     Eth      LACP      " + "    ".join(m + "(P)" for m in members) + "\n"
                      for n, members in groups))


def _switchport_access(port):
    return (f"Name: {port}\nSwitchport: Enabled\nAdministrative Mode: static access\n"
            "Operational Mode: static access\nAccess Mode VLAN: 10 (USERS)\n")


def _built(tmp_path, host, outputs, platform="ios"):
    """One device through the real producer: capture text on disk, read back by build.build_interfaces."""
    directory = tmp_path / f"device-{sum(1 for _ in tmp_path.iterdir())}"
    directory.mkdir()
    c2f = {}
    for cmd, text in outputs.items():
        path = directory / fx.cmd_filename(cmd)
        path.write_text(text, encoding="utf-8", newline="\n")
        c2f[cmd] = str(path)
    return build.build_interfaces(host, platform, c2f)


def _link(tmp_path, a=("10", True), b=("10", True), *, native=("1", "1"), cdp=(True, True), extra=None,
          names=(A, B), b_port=PORT):
    """Two IOS switches joined by one trunk on Gi1/0/1. a/b: (allowed or None, live)."""
    fleet = {}
    for i, (host, peer, (allowed, live)) in enumerate(((names[0], names[1], a), (names[1], names[0], b))):
        local, remote = (PORT, b_port) if i == 0 else (b_port, PORT)
        outputs = {"show interfaces trunk": _ios_trunk([(local, allowed, native[i], live)])}
        if cdp[i]:
            outputs["show cdp neighbors detail"] = _cdp([(local, peer, remote)])
        outputs.update((extra or {}).get(host, {}))
        fleet[host] = _built(tmp_path, host, outputs)
    return fleet


def _parallel(tmp_path, *, first="10", second="20"):
    """Two parallel unbundled trunks, Gi1/0/1 and Gi1/0/2, each with its own allowance."""
    fleet = {}
    for host, peer in ((A, B), (B, A)):
        fleet[host] = _built(tmp_path, host, {
            "show interfaces trunk": _ios_trunk([(PORT, first, "1", True), ("Gi1/0/2", second, "1", True)]),
            "show cdp neighbors detail": _cdp([(PORT, peer, PORT), ("Gi1/0/2", peer, "Gi1/0/2")])})
    return fleet


def _bundle(tmp_path, *, a_groups=((1, ("Gi1/0/1", "Gi1/0/2")),), b_groups=((20, ("Gi1/0/1", "Gi1/0/2")),),
            allowed=("10", "10"), cdp=(True, True)):
    """Two IOS switches joined by a two-member LACP bundle. IOS lists only the port channel in 'show interfaces
    trunk'; its members come from 'show etherchannel summary'."""
    fleet = {}
    for i, (host, peer, groups) in enumerate(((A, B, a_groups), (B, A, b_groups))):
        outputs = {"show interfaces trunk": _ios_trunk([(f"Po{n}", allowed[i], "1", True) for n, _m in groups]),
                   "show etherchannel summary": _etherchannel(groups)}
        if cdp[i]:
            outputs["show cdp neighbors detail"] = _cdp([(p, peer, p) for p in ("Gi1/0/1", "Gi1/0/2")])
        fleet[host] = _built(tmp_path, host, outputs)
    return fleet


def _nexus(tmp_path, *, po_allowed="10,20", member_allowed="1-4094"):
    """Two NX-OS switches joined by Po10 (Eth1/1, Eth1/2). NX-OS lists members as trnk-bndl with their own allowed
    list (1-4094 here) beside the channel's narrower one."""
    fleet = {}
    for host, peer in ((A, B), (B, A)):
        fleet[host] = _built(tmp_path, host, {
            "show interface trunk": _nexus_trunk([("Eth1/1", "1", "trnk-bndl", "Po10", member_allowed),
                                                  ("Eth1/2", "1", "trnk-bndl", "Po10", member_allowed),
                                                  ("Po10", "1", "trunking", "", po_allowed)],
                                                 forwarding={"Po10": "1,10,20,30"}),
            "show port-channel summary": _portchannel([(10, ("Eth1/1", "Eth1/2"))]),
            "show cdp neighbors detail": _cdp([("Ethernet1/1", peer, "Ethernet1/1"), ("Ethernet1/2", peer, "Ethernet1/2")],
                                              platform="cisco N9K-C93180YC-EX")}, platform="nxos")
    return fleet


def _stp(rows):
    """One host's typed STP observation through its real producer. rows: {vid: [(port, role, state)]}."""
    body, detail = [], []
    for vid, ports in rows.items():
        body.append(f"VLAN{vid:04d}\n  Root ID Priority 32778\n          Address aaaa.0001.0001\n"
                    "          This bridge is the root\n  Bridge ID Priority 32778\n          Address aaaa.0001.0001\n"
                    "Interface Role Sts Cost Prio.Nbr Type\n---------------- ---- --- --------- -------- ----------------\n"
                    + "".join(f"{port} {role} {state} 4 128.1 P2p\n" for port, role, state in ports))
        detail.append(f"VLAN{vid:04d}\n  Number of topology changes 0 last change occurred 00:00:00 ago\n")
    observation = produce_stp_topology_observation("".join(body), "".join(detail),
                                                   state_capture_state="usable", detail_capture_state="usable")
    assert observation["role_candidate_count"] == observation["role_parsed_count"], observation
    assert "role_row_malformed" not in observation["finding_codes"], observation
    return observation


def _observation(state="FWD", *, port=PORT, namespace="VLAN", vid=10):
    role = "Altn" if state == "BLK" else "Desg"
    body = f"""{namespace}{vid:04d}
  Root ID Priority 32778
          Address aaaa.0001.0001
          This bridge is the root
  Bridge ID Priority 32778
          Address aaaa.0001.0001
Interface Role Sts Cost Prio.Nbr Type
---------------- ---- --- --------- -------- ----------------
{port} {role} {state} 4 128.1 P2p
"""
    detail = f"{namespace}{vid:04d}\n  Number of topology changes 0 last change occurred 00:00:00 ago\n"
    observation = produce_stp_topology_observation(
        body, detail, state_capture_state="usable", detail_capture_state="usable")
    assert observation["role_candidate_count"] == observation["role_parsed_count"] == 1, observation
    assert "role_row_malformed" not in observation["finding_codes"], observation
    return observation


def _stored(interfaces):
    """The snapshot's stored interface records: the producer's dataclasses as JSON dicts."""
    return {host: {port: asdict(record) for port, record in records.items()} for host, records in interfaces.items()}


def _compute(interfaces, *, observation=None, vlans=None, cables=None, failed=(), stored=None):
    cables = compute_cable_map(interfaces) if cables is None else cables
    return compute_vlan_carriage(cables, _stored(interfaces) if stored is None else stored, observation,
                                 [{"vlan": 10}] if vlans is None else vlans, failed_sources=failed)


def _decoded(doc, vi=0):
    """Every assessed cable of one VLAN row through the owner's decoder, end evidence beside its stored end."""
    out = []
    for cable, verdict, members in carriage_row_cables(doc, vi):
        out.append({"cable": cable, **verdict, "members": [
            {"stored": member, **member_verdict, "a": {**member["a"], **a}, "b": {**member["b"], **b}}
            for member, member_verdict, a, b in members]})
    return out


def _row(document, vi=0):
    assert validate_vlan_carriage(document) == (True, "ok")
    assert document["coverage"]["capture_completeness_claim"] is False
    pairs = _decoded(document, vi)
    assert len(pairs) == 1, pairs
    return pairs[0]


# ---------------------------------------------------------------------------------------------------------------
# vocabulary, code tables and identities
# ---------------------------------------------------------------------------------------------------------------
def test_carriage_states_keep_the_stored_order_and_the_canonical_owner_membership():
    assert STATES == ("published", "collected_but_empty", "not_collected", "unverified", "analysis_unavailable")
    assert set(STATES) == set(ABSTENTION_STATES) | {"unverified"}
    assert tuple(state for state in STATES if state != "unverified") == ABSTENTION_STATES


def test_code_tables_are_closed_owner_alphabets_whose_state_and_shape_follow_the_code():
    published = [code for code in VERDICT_CODES if ":" in code]
    assert published == ["forwarding:typed_pvst", "forwarding:stored_trunk_allowance", "forwarding:member_consensus",
                         "stp_blocked:typed_pvst", "stp_blocked:member_consensus",
                         "not_carried:stored_trunk_allowance", "not_carried:member_consensus"]
    assert END_CODES[:4] == vc.END_SIGNALS
    assert len(set(VERDICT_CODES)) == len(VERDICT_CODES) and len(set(END_CODES)) == len(END_CODES)
    assert max(len(VERDICT_CODES), len(END_CODES)) <= len(CODE_ALPHABET) == len(set(CODE_ALPHABET))
    for i, code in enumerate(VERDICT_CODES):
        decoded = vc.decode_verdict(CODE_ALPHABET[i])
        if ":" in code:
            assert (decoded["state"], decoded["relation"], decoded["basis"], decoded["reason"]) == (
                "published", *code.split(":"), None)
        else:
            assert decoded["state"] != "published" and decoded["reason"] == vc._ISSUES[code]
            assert decoded["state"] == {"not collected": "not_collected", "unverified": "unverified",
                                        "analysis unavailable": "analysis_unavailable"}[decoded["reason"].split(":")[0]]
    for i, code in enumerate(END_CODES):
        decoded = vc.decode_end(CODE_ALPHABET[i])
        assert (decoded["signal"] == code) is (code in vc.END_SIGNALS)
        assert (decoded["state"] == "published") is (code in vc.END_SIGNALS)


@pytest.mark.parametrize(("raw", "expected"), [
    ("Switch-A.example.net (SERIAL)", "switch-a"), (" switch-A ", "switch-a"),
    ("switch/a~b", "switch/a~b"), ("", ""), (None, ""),
])
def test_public_carriage_host_identity_keeps_existing_cable_normalization(raw, expected):
    assert carriage_host_identity(raw) == _canon_host(raw) == expected


@pytest.mark.parametrize(("raw", "expected"), [
    ("GigabitEthernet1/0/1", "Gi1/0/1"), (" Ethernet1/1 ", "Eth1/1"),
    ("Port-channel001", "Po001"), ("Vl10", "Vlan10"),
    ("Gi1/0/1", "Gi1/0/1"), ("not-an-interface", "not-an-interface"), ("", ""),
])
def test_public_carriage_port_identity_is_normalization_not_a_new_admission_rule(raw, expected):
    assert carriage_port_identity(raw) == normalize_ifname(raw) == expected


def test_a_channel_joins_by_channel_number_on_both_sides_never_by_port_spelling():
    # _port keeps the leading zeros a channel name was written with; the PVST join must not.
    assert vc._port("port-channel015") == "Po015"
    assert carriage_join_interface("port-channel015") == carriage_join_interface("Po15") == "Po15"
    assert carriage_join_interface(PORT) == PORT and carriage_join_interface("not-an-interface") is None
    observation = _stp({15: [("Port-channel015", "Desg", "FWD")]})
    assert [i for i, _row in carriage_role_rows(observation, "Po15", 15)] == [0]
    assert carriage_role_rows(observation, "Po015", 15) == carriage_role_rows(observation, "Po15", 15)
    assert carriage_role_rows(observation, "Po15", 16) == [] and carriage_role_rows(observation, "Po15", "15") == []


# ---------------------------------------------------------------------------------------------------------------
# (a) a bundled member reads PVST, allowance and mode through its logical port channel
# ---------------------------------------------------------------------------------------------------------------
def test_nexus_members_follow_the_blocked_port_channel_not_their_own_allowance(tmp_path):
    interfaces = _nexus(tmp_path)
    assert interfaces[A]["Eth1/1"].trunk_allowed_vlans == "1-4094" and interfaces[A]["Eth1/1"].port_channel == "Po10"
    cables = compute_cable_map(interfaces)
    assert len(cables["cables"]) == 1 and len(cables["cables"][0]["members"]) == 2
    observations = {A: _stp({10: [("Po10", "Altn", "BLK")]}), B: _stp({10: [("Po10", "Desg", "FWD")]})}
    row = _row(_compute(interfaces, observation=observations, cables=cables))
    assert row["relation"] in ("stp_blocked", None) and row["relation"] != "forwarding"
    assert (row["state"], row["relation"], row["basis"]) == ("published", "stp_blocked", "member_consensus")
    for member in row["members"]:
        assert (member["a"]["signal"], member["b"]["signal"]) == ("blocked", "forwarding")
        assert member["a"]["stp_interface"] == member["b"]["stp_interface"] == "Po10"
        assert member["a"]["allowance_pointer"] == f"/interfaces/{A}/Po10"


def test_ios_members_follow_a_forwarding_port_channel_on_both_ends_as_typed_forwarding(tmp_path):
    interfaces = _bundle(tmp_path, allowed=(None, None))
    assert interfaces[A][PORT].port_channel == "Po1" and interfaces[B][PORT].port_channel == "Po20"
    observations = {A: _stp({10: [("Po1", "Desg", "FWD")]}), B: _stp({10: [("Po20", "Root", "FWD")]})}
    row = _row(_compute(interfaces, observation=observations))
    assert (row["state"], row["relation"], row["basis"]) == ("published", "forwarding", "member_consensus")
    assert [(m["relation"], m["basis"]) for m in row["members"]] == [("forwarding", "typed_pvst")] * 2
    assert {m["a"]["stp_interface"] for m in row["members"]} == {"Po1"}
    assert {m["b"]["stp_interface"] for m in row["members"]} == {"Po20"}


def test_a_nexus_channel_allowance_excludes_a_vlan_its_members_would_allow(tmp_path):
    interfaces = _nexus(tmp_path, po_allowed="10,20", member_allowed="1-4094")
    observations = {host: _stp({10: [("Po10", "Desg", "FWD")], 20: [("Po10", "Desg", "FWD")]}) for host in (A, B)}
    doc = _compute(interfaces, observation=observations, vlans=[{"vlan": 10}, {"vlan": 30}])
    assert validate_vlan_carriage(doc) == (True, "ok")
    assert _decoded(doc, 0)[0]["relation"] == "forwarding"
    vlan30 = _decoded(doc, 1)[0]
    assert (vlan30["state"], vlan30["relation"], vlan30["basis"]) == ("published", "not_carried", "member_consensus")
    assert all((m["a"]["signal"], m["b"]["signal"]) == ("excluded", "excluded") for m in vlan30["members"])


def test_a_member_row_beside_its_channel_row_is_ambiguous_not_a_member_fallback(tmp_path):
    interfaces = _bundle(tmp_path, allowed=("1-4094", "1-4094"))
    observations = {A: _stp({10: [("Po1", "Desg", "FWD"), ("Gi1/0/2", "Altn", "BLK")]}),
                    B: _stp({10: [("Po20", "Desg", "FWD")]})}
    row = _row(_compute(interfaces, observation=observations))
    assert row["state"] == "unverified" and row["relation"] is None
    assert row["members"][0]["relation"] == "forwarding"
    held = row["members"][1]["a"]
    assert held["signal"] is None and "one normalized" in held["reason"]


@pytest.mark.parametrize("damage", ["incompatible", "unpublished"])
def test_a_held_channel_observation_never_falls_back_to_member_allowance(tmp_path, damage):
    interfaces = _nexus(tmp_path, po_allowed="10", member_allowed="1-4094")
    a = (_stp({10: [("Po10", "Desg", "LRN")]}) if damage == "incompatible" else {})  # {}: labelled malformed record
    row = _row(_compute(interfaces, observation={A: a, B: _stp({10: [("Po10", "Desg", "FWD")]})}))
    assert row["state"] == "unverified" and row["relation"] is None
    for member in row["members"]:
        assert member["a"]["signal"] is None and member["a"]["basis"] == "none"


def test_a_bundled_member_without_its_channel_record_is_not_collected_for_every_vlan(tmp_path):
    interfaces = _nexus(tmp_path)
    stored = _stored(interfaces)
    del stored[A]["Po10"]  # Labelled damage: the channel record is gone; the members still allow 1-4094.
    doc = _compute(interfaces, stored=stored, vlans=[{"vlan": 10}, {"vlan": 30}])
    for vi in (0, 1):
        row = _row(doc, vi)
        assert row["state"] in ("not_collected", "unverified") and row["relation"] is None
        assert all(m["a"]["hold"] == "no_evidence" and m["a"]["signal"] is None for m in row["members"])


def test_role_rows_are_indexed_once_per_host_not_scanned_per_end(tmp_path, monkeypatch):
    interfaces = _nexus(tmp_path)
    observations = {host: _stp({10: [("Po10", "Desg", "FWD")], 20: [("Po10", "Desg", "FWD")]}) for host in (A, B)}
    calls = []
    original = vc.carriage_role_index

    def counted(observation):
        calls.append(id(observation))
        return original(observation)

    monkeypatch.setattr(vc, "carriage_role_index", counted)
    doc = _compute(interfaces, observation=observations, vlans=[{"vlan": 10}, {"vlan": 20}])
    assert validate_vlan_carriage(doc) == (True, "ok")
    assert sorted(calls) == sorted({id(observations[A]), id(observations[B])})


# ---------------------------------------------------------------------------------------------------------------
# relations and holds over one trunk
# ---------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize(("malformed_tail", "failed", "expected"), [
    (False, (), "not_collected"),
    (True, (), "unverified"),
    (True, ("interfaces",), "analysis_unavailable"),
])
def test_owner_backed_hold_precedence_keeps_missing_malformed_and_failed_evidence(tmp_path, malformed_tail, failed, expected):
    interfaces = _link(tmp_path, (None, True), (None, True))
    cables = compute_cable_map(interfaces)
    if malformed_tail:
        cables["cables"].append(None)  # Retain a real NC cable beside an explicitly malformed row.
    doc = compute_vlan_carriage(cables, _stored(interfaces), None, [{"vlan": 10}], failed_sources=failed)
    assert validate_vlan_carriage(doc) == (True, "ok")
    assert doc["state"] == expected and doc["rows"][0]["state"] == expected
    if failed:
        assert doc["rows"][0]["hold"] == "failed_source" and doc["rows"][0]["codes"] == ""
    else:
        assert _decoded(doc)[0]["state"] == "not_collected" and _decoded(doc)[0]["relation"] is None
    if malformed_tail:
        assert doc["cables"][1]["scope"] == "unreadable" and doc["cables"][1]["hold"] == "cable_unreadable"
        assert doc["coverage"]["unreadable_cables"] == 1


def test_typed_pvst_forwarding_cites_the_observation_and_joins_its_role_row(tmp_path):
    interfaces = _link(tmp_path, (None, True), (None, True))
    observations = {A: _observation(), B: _observation()}
    stored = _stored(interfaces)
    stored[A][PORT]["stp_blk_vlans"] = "10"  # Labelled legacy perturbation: namespace-free ranges never substitute.
    doc = _compute(interfaces, observation=observations, stored=stored)
    row = _row(doc)
    assert (row["state"], row["relation"], row["basis"]) == ("published", "forwarding", "typed_pvst")
    assert doc["rows"][0]["vlan_pointer"] == "/vlan_cutover/0" and row["cable"]["pointer"] == "/cable_map/cables/0"
    member = row["members"][0]
    assert member["stored"]["pointer"] == "/cable_map/cables/0/members/0"
    for side, host in (("a", A), ("b", B)):
        end = member[side]
        assert (end["host"], end["port"], end["signal"]) == (host, PORT, "forwarding")
        assert end["interface_pointer"] == f"/interfaces/{host}/Gi1~10~11"
        assert end["stp_pointer"] == f"/stp_topology_observations/{host}"
        assert carriage_role_rows(observations[host], end["stp_interface"], 10) == [(0, observations[host]["roles"][0])]


def test_blocking_requires_both_ends_evidence_not_just_the_legacy_block_token(tmp_path):
    interfaces = _link(tmp_path, (None, True), (None, True))
    interfaces[A][PORT].stp_blk_vlans = "10"  # Labelled legacy-only perturbation of the built record.
    # The old simulation predicate is unchanged and still says blk. New display evidence is stricter.
    assert _link_carries({"da": interfaces[A][PORT], "db": interfaces[B][PORT]}, 10) == "blk"
    one = _row(_compute(interfaces, observation={A: _observation("BLK")}))
    assert (one["state"], one["relation"], one["evidence_shape"]) == ("not_collected", None, "one_end_only")
    assert one["members"][0]["a"]["signal"] == "blocked"
    complete = _row(_compute(interfaces, observation={A: _observation("BLK"), B: _observation()}))
    assert (complete["state"], complete["relation"]) == ("published", "stp_blocked")


def test_missing_interface_does_not_become_blocked_even_with_an_observation_for_that_host(tmp_path):
    interfaces = _link(tmp_path, (None, True), (None, True))
    stored = _stored(interfaces)
    del stored[B][PORT]  # Explicit stored-input damage after the cable was recorded.
    row = _row(_compute(interfaces, stored=stored, observation={A: _observation("BLK"), B: _observation()}))
    assert (row["state"], row["relation"]) == ("not_collected", None)
    assert row["members"][0]["b"]["interface_pointer"] is None and row["members"][0]["b"]["hold"] == "missing_interface"


def test_blank_or_legacy_only_evidence_is_not_carried_neither_forwarding_nor_negative(tmp_path):
    interfaces = _link(tmp_path, (None, True), (None, True))
    stored = _stored(interfaces)
    for records in stored.values():
        records[PORT]["stp_fwd_vlans"] = "10"  # Labelled legacy-only perturbation.
    row = _row(_compute(interfaces, stored=stored))
    assert (row["state"], row["relation"], row["evidence_shape"]) == ("not_collected", None, "no_evidence")


@pytest.mark.parametrize("allowed, relation", [("all", "forwarding"), ("1-4094", "forwarding"),
                                                ("10,20-23", "forwarding"), ("none", "not_carried"),
                                                ("20-23", "not_carried")])
def test_mutual_explicit_trunk_allowance_has_only_the_configured_model_basis(tmp_path, allowed, relation):
    interfaces = _link(tmp_path, (allowed, True), (allowed, True))
    if allowed == "none":
        assert (interfaces[A][PORT].trunk_allowed_vlans, interfaces[A][PORT].trunk_allowed_none) == ("", "none")
    doc = _compute(interfaces)
    row = _row(doc)
    assert (row["state"], row["relation"], row["basis"]) == ("published", relation, "stored_trunk_allowance")
    assert "not observed STP forwarding or traffic" in " ".join(doc["limitations"])
    assert row["members"][0]["a"]["allowance_pointer"] == f"/interfaces/{A}/Gi1~10~11"


def test_a_native_vlan_only_witnesses_a_conflict_and_never_makes_a_blank_list_allowed(tmp_path):
    blank = _link(tmp_path, (None, True), (None, True), native=("10", "10"))
    assert (blank[A][PORT].trunk_native_vlan, blank[A][PORT].trunk_allowed_vlans) == ("10", "")
    row = _row(_compute(blank))
    assert (row["state"], row["relation"], row["evidence_shape"]) == ("not_collected", None, "no_evidence")
    excluded = _link(tmp_path, ("20", True), ("20", True), native=("10", "1"))
    conflict = _row(_compute(excluded))
    assert conflict["state"] == "unverified" and conflict["relation"] is None
    assert "disagree" in conflict["members"][0]["a"]["reason"]
    assert _row(_compute(blank, vlans=[{"vlan": 20}]))["state"] == "not_collected"


@pytest.mark.parametrize("mode, state", [("", "not_collected"), ("Access", "unverified"), ("Routed", "unverified")])
def test_allowance_does_not_imply_an_unobserved_or_contradictory_trunk_mode(tmp_path, mode, state):
    extra = {A: {"show interfaces switchport": _switchport_access(PORT)}} if mode == "Access" else None
    interfaces = _link(tmp_path, ("10", False), ("10", True), extra=extra)
    assert interfaces[A][PORT].switchport_mode == ("Access" if mode == "Access" else "")
    stored = _stored(interfaces)
    if mode == "Routed":
        stored[A][PORT]["switchport_mode"] = "Routed"  # Labelled: no parser emits this mode; stored damage.
    row = _row(_compute(interfaces, stored=stored))
    assert row["state"] == state and row["relation"] is None


@pytest.mark.parametrize("mode", ["Trunk", "dynamic trunk", "trunk (802.1q)"])
def test_carriage_uses_the_shared_trunk_mode_predicate_for_supplied_records(tmp_path, mode):
    interfaces = _link(tmp_path, ("10", True), ("10", True))
    stored = _stored(interfaces)
    for host in (A, B):
        stored[host][PORT]["switchport_mode"] = mode  # Declared alternate supplied-snapshot spelling.
    row = _row(_compute(interfaces, stored=stored))
    assert row["state"] == "published" and row["relation"] == "forwarding"


@pytest.mark.parametrize("value", [True, None, 10, [10], "10,broken", "10-foo", "40-10", "4095", "0",
                                   "10,,20", "10," + "9" * 5000])
def test_malformed_mixed_ranges_and_wrong_types_never_become_a_false_exclusion(tmp_path, value):
    stored = None
    if isinstance(value, str):
        interfaces = _link(tmp_path, (value, True), ("10", True))
        assert interfaces[A][PORT].trunk_allowed_vlans == value
    else:
        interfaces = _link(tmp_path)
        stored = _stored(interfaces)
        stored[A][PORT]["trunk_allowed_vlans"] = value  # Labelled wrong-type damage; no parser emits it.
    row = _row(_compute(interfaces, stored=stored))
    assert row["state"] == "unverified" and row["relation"] is None


def test_explicit_trunk_exclusion_conflicting_with_pvst_forwarding_is_held(tmp_path):
    row = _row(_compute(_link(tmp_path, ("20", True), ("10", True)), observation={A: _observation(), B: _observation()}))
    assert row["state"] == "unverified" and row["relation"] is None
    assert "disagree" in row["reason"]


def test_two_different_positive_bases_do_not_silently_make_a_shared_forwarding_claim(tmp_path):
    row = _row(_compute(_link(tmp_path, (None, True), ("10", True)), observation={A: _observation()}))
    assert row["state"] == "unverified" and row["relation"] is None
    assert row["members"][0]["a"]["signal"] == "forwarding"
    assert row["members"][0]["b"]["signal"] == "allowed"


def test_mst_instance_ten_is_not_vlan_ten_even_when_legacy_ranges_and_config_are_positive(tmp_path):
    interfaces = _link(tmp_path)
    stored = _stored(interfaces)
    stored[A][PORT]["stp_fwd_vlans"] = "10"  # Labelled legacy perturbation.
    doc = _compute(interfaces, stored=stored, observation={A: _observation(namespace="MST"), B: _observation()})
    row = _row(doc)
    assert row["state"] == "unverified" and row["relation"] is None
    assert "MST" in row["members"][0]["a"]["reason"]
    assert doc["issues"] and doc["coverage"]["input_census_complete"] is False


def test_normalized_duplicate_pvst_port_rows_are_ambiguous_not_first_row_wins(tmp_path):
    observation = _observation()
    extra = {**observation["roles"][0], "interface": LONG}
    observation["roles"].append(extra)  # Labelled stored perturbation: a second spelling of the same port.
    observation["role_candidate_count"] = observation["role_parsed_count"] = 2
    row = _row(_compute(_link(tmp_path, (None, True), (None, True)), observation={A: observation, B: _observation()}))
    assert row["state"] == "unverified" and row["relation"] is None
    assert "one normalized" in row["members"][0]["a"]["reason"]


def test_transitional_pvst_state_is_not_forwarding_from_trunk_fallback(tmp_path):
    row = _row(_compute(_link(tmp_path), observation={A: _observation("LRN"), B: _observation()}))
    assert row["state"] == "unverified" and row["relation"] is None


def test_stp_capture_failure_and_an_unreferenced_malformed_observation_stay_visible(tmp_path):
    failed = produce_stp_topology_observation("", "", state_capture_state="error", detail_capture_state="missing")
    interfaces = _link(tmp_path)
    doc = _compute(interfaces, observation={A: failed})
    assert _row(doc)["state"] == "analysis_unavailable"
    orphan = _compute(interfaces, observation={"synthetic-orphan": {}})
    assert orphan["state"] == "unverified"
    assert orphan["issues"][0]["pointer"] == "/stp_topology_observations/synthetic-orphan"
    assert orphan["coverage"]["input_census_complete"] is False


def test_missing_role_table_separator_remains_unverified_with_its_observation_witness(tmp_path):
    # Deliberately retain the malformed bootstrap fixture shape: the legacy parser
    # reads this row, but the strict candidate census requires the real table frame.
    body = """VLAN0010
  Root ID Priority 32778
          Address aaaa.0001.0001
          This bridge is the root
  Bridge ID Priority 32778
          Address aaaa.0001.0001
Interface Role Sts Cost Prio.Nbr Type
Gi1/0/1 Altn BLK 4 128.1 P2p
"""
    malformed = produce_stp_topology_observation(
        body, "VLAN0010\n  Number of topology changes 0 last change occurred 00:00:00 ago\n",
        state_capture_state="usable", detail_capture_state="usable")
    assert malformed["role_candidate_count"] == 0 and malformed["role_parsed_count"] == 1, malformed
    assert "role_row_malformed" in malformed["finding_codes"]
    admission = carriage_observation_admission(malformed)
    assert admission[:2] == ("unverified", "stp_unreadable")
    assert admission[2] is malformed
    doc = _compute(_link(tmp_path, (None, True), (None, True)), observation={A: malformed, B: _observation()})
    row = _row(doc)
    assert row["state"] == "unverified" and row["relation"] is None
    end = row["members"][0]["a"]
    assert end["state"] == "unverified" and end["signal"] is None
    assert f"/stp_topology_observations/{A}" in end["refs"] and end["stp_pointer"] is None
    assert any(issue["state"] == "unverified" and issue["pointer"] == f"/stp_topology_observations/{A}"
               for issue in doc["issues"])


@pytest.mark.parametrize(("case", "state", "reason", "retained"), [
    ("pvst", "published", None, True),
    ("no_roles", "published", None, True),
    ("empty", "not_collected", None, True),
    ("missing", "not_collected", None, True),
    ("error", "analysis_unavailable", "stp_failed", True),
    ("mst", "unverified", "mst_unmapped", True),
    ("role_census", "unverified", "stp_unreadable", True),
    ("duplicate_finding", "unverified", "stp_unreadable", True),
    ("role_evidence_missing", "unverified", "stp_unreadable", True),
    ("state_instance_missing", "unverified", "stp_unreadable", True),
    ("blank_dict", "unverified", "stp_unreadable", False),
    ("null", "unverified", "stp_unreadable", False),
    ("malformed_capture", "unverified", "stp_unreadable", False),
])
def test_shared_stp_admission_preserves_exact_existing_record_and_producer_end_semantics(
        tmp_path, case, state, reason, retained):
    if case in {"empty", "missing", "error"}:
        observation = produce_stp_topology_observation(
            "", "", state_capture_state=case, detail_capture_state="missing")
    elif case == "blank_dict":
        observation = {}
    elif case == "null":
        observation = None
    else:
        observation = _observation(namespace="MST" if case == "mst" else "VLAN")
        # These are explicit stored-record perturbations, not asserted parser outputs.
        if case == "no_roles":
            observation["roles"] = []
            observation["role_candidate_count"] = observation["role_parsed_count"] = 0
        elif case == "role_census":
            observation["role_candidate_count"] += 1
            observation["finding_codes"] = sorted(set(observation["finding_codes"]) | {"role_row_malformed"})
        elif case in ("duplicate_finding", "role_evidence_missing", "state_instance_missing"):
            code = "state_instance_duplicate" if case == "duplicate_finding" else case
            observation["finding_codes"] = sorted(set(observation["finding_codes"]) | {code})
        elif case == "malformed_capture":
            observation["state_capture_state"] = []
    before = deepcopy(observation)
    interfaces = _link(tmp_path)
    direct = carriage_observation_admission(observation)
    through_owner = _Inputs(_stored(interfaces), {A: observation}, set()).observation(A)
    assert direct[:2] == through_owner[:2] == (state, reason)
    assert direct[2] is (observation if retained else None)
    assert through_owner[2] is direct[2]
    end = _row(_compute(interfaces, observation={A: observation}))["members"][0]["a"]
    if state in {"unverified", "analysis_unavailable"}:
        assert end["state"] == state and end["signal"] is None
    else:
        # An absent PVST role/capture can still use the explicitly disclosed
        # configured-trunk model; the extraction must not change that old boundary.
        assert end["state"] == "published"
        assert end["basis"] == ("typed_pvst" if case == "pvst" else "stored_trunk_allowance")
    assert observation == before


def test_shared_stp_admission_does_not_replace_environment_absence_or_failed_source_precedence():
    assert _Inputs({}, None, set()).observation(A) == ("not_collected", None, None)
    assert _Inputs({}, {}, set()).observation(A) == ("not_collected", None, None)
    assert _Inputs({}, {A: None}, set()).observation(A) == ("unverified", "stp_unreadable", None)
    assert _Inputs({}, {A: _observation()}, {"stp_topology_observations"}).observation(A) == (
        "analysis_unavailable", "failed_source", None)


#: Every stp_topology finding code, classified for the carriage owner's role-row join. ``role`` codes leave the role
#: census unable to stand for each observed port and instance, so the whole observation is held; ``capture`` codes
#: are tied to the capture states admission already reads; ``counter`` codes concern detail counters; ``root`` concerns
#: root fields; ``baseline`` codes are the derived baseline's findings, whose role/state stability the carriage owner
#: checks per row itself. Enforced: role == stp_topology.ROLE_EVIDENCE_INTEGRITY_CODES.
_ROLE_INTEGRITY_CLASSES = {
    "state_capture_missing": "capture", "state_capture_empty": "capture", "state_capture_error": "capture",
    "detail_capture_missing": "capture", "detail_capture_empty": "capture", "detail_capture_error": "capture",
    "state_instance_missing": "role", "state_instance_duplicate": "role", "mixed_namespace": "role",
    "role_row_malformed": "role", "role_subject_duplicate": "role", "role_evidence_missing": "role",
    "root_evidence_incomplete": "root",
    "detail_instance_missing": "counter", "detail_instance_extra": "counter", "detail_instance_duplicate": "counter",
    "topology_counter_malformed": "counter", "topology_counter_duplicate": "counter",
    "topology_counter_missing": "counter",
    "observation_malformed": "baseline", "invalid_role_state": "baseline", "transitional_port_state": "baseline",
    "no_forwarding_path": "baseline", "root_path_missing": "baseline", "unexpected_root_path": "baseline",
}


@pytest.mark.parametrize("code", sorted(_ROLE_INTEGRITY_CLASSES))
def test_every_stp_finding_code_is_classified_for_the_role_row_join(code):
    assert set(_ROLE_INTEGRITY_CLASSES) == set(_FINDING_CODES)
    assert {c for c, kind in _ROLE_INTEGRITY_CLASSES.items() if kind == "role"} == set(ROLE_EVIDENCE_INTEGRITY_CODES)
    observation = _observation()
    observation["finding_codes"] = sorted(set(observation["finding_codes"]) | {code})  # Labelled perturbation.
    admission = carriage_observation_admission(observation)
    if _ROLE_INTEGRITY_CLASSES[code] == "role":
        assert admission[:2] == ("unverified", "stp_unreadable")
    elif code in ("topology_counter_malformed",) or _ROLE_INTEGRITY_CLASSES[code] == "capture":
        # A bare code that contradicts its counts or capture state is refused by the shape validator itself.
        assert validate_stp_topology_observation(observation)[0] is False
        assert admission[:2] == ("unverified", "stp_unreadable")
    else:
        assert admission[:2] == ("published", None)


# ---------------------------------------------------------------------------------------------------------------
# the input census
# ---------------------------------------------------------------------------------------------------------------
def test_a_valid_unjoined_interface_record_does_not_invent_an_extra_cable(tmp_path):
    interfaces = _link(tmp_path)
    cables = compute_cable_map(interfaces)
    stored = _stored(interfaces)
    stored["orphan"] = {PORT: deepcopy(stored[B][PORT])}  # Labelled: a copied record under an unjoined host.
    doc = _compute(interfaces, cables=cables, stored=stored)
    assert _row(doc)["relation"] == "forwarding"
    assert doc["state"] == "published" and doc["issues"] == []
    assert doc["coverage"]["input_census_complete"] is True
    assert doc["coverage"]["cable_rows"] == doc["coverage"]["emitted_pairs"] == 1


def test_an_unjoined_malformed_range_is_a_source_issue_without_a_fabricated_vlan_query(tmp_path):
    interfaces = _link(tmp_path)
    stored = _stored(interfaces)
    stored["orphan"] = {PORT: {**deepcopy(stored[B][PORT]), "trunk_allowed_vlans": "10 \t 20"}}  # Labelled damage.
    doc = _compute(interfaces, stored=stored)
    assert _row(doc)["relation"] == "forwarding"
    assert doc["state"] == "unverified" and doc["coverage"]["input_census_complete"] is False
    assert doc["rows"][0]["state"] == "unverified"
    assert any(issue["pointer"] == "/interfaces/orphan/Gi1~10~11/trunk_allowed_vlans" for issue in doc["issues"])


@pytest.mark.parametrize("bad", [None, [], "unreadable", {"trunk_allowed_vlans": False},
                                 {"neighbor_port": []}, {"port_channel": None}, {"port": "Gi1/0/99"}])
@pytest.mark.parametrize("joined", [False, True])
def test_malformed_interface_values_are_censused_whether_or_not_a_cable_joins_them(tmp_path, bad, joined):
    interfaces = _link(tmp_path)
    stored = _stored(interfaces)
    host = A if joined else "orphan"
    stored[host] = {PORT: deepcopy(bad)}  # Explicit stored damage after real cable construction.
    doc = _compute(interfaces, stored=stored)
    row = _row(doc)
    assert doc["state"] == "unverified" and doc["coverage"]["input_census_complete"] is False
    assert any(issue["pointer"] == f"/interfaces/{host}/Gi1~10~11" for issue in doc["issues"])
    assert doc["coverage"]["emitted_pairs"] == 1
    if joined:
        assert row["state"] == "unverified" and row["relation"] is None
    else:
        assert row["state"] == "published" and row["relation"] == "forwarding"
        assert all(end["state"] == "published" for end in (row["members"][0]["a"], row["members"][0]["b"]))


def test_aliases_resolve_exactly_and_keep_original_interface_pointer(tmp_path):
    interfaces = _link(tmp_path)
    cables = compute_cable_map(interfaces)
    stored = _stored(interfaces)
    stored[A][LONG] = stored[A].pop(PORT)  # Labelled: an equivalent stored spelling of the same port.
    row = _row(_compute(interfaces, cables=cables, stored=stored))
    assert row["relation"] == "forwarding"
    assert row["members"][0]["a"]["interface_pointer"] == f"/interfaces/{A}/GigabitEthernet1~10~11"
    stored[A][PORT] = deepcopy(stored[A][LONG])
    duplicate = _compute(interfaces, cables=cables, stored=stored)
    assert _row(duplicate)["state"] == "unverified" and duplicate["coverage"]["input_census_complete"] is False


def test_host_canonical_collision_is_refused_without_selecting_a_sibling(tmp_path):
    interfaces = _link(tmp_path)
    stored = _stored(interfaces)
    stored[A + ".example"] = deepcopy(stored[A])  # Labelled: a second host under the same canonical name.
    doc = _compute(interfaces, stored=stored)
    assert _row(doc)["state"] == "unverified"
    assert doc["coverage"]["input_census_complete"] is False
    assert any(issue["pointer"] == f"/interfaces/{A}.example" for issue in doc["issues"])


# ---------------------------------------------------------------------------------------------------------------
# cables, orientation and identity
# ---------------------------------------------------------------------------------------------------------------
def test_parallel_cables_keep_distinct_port_identities_and_the_supplied_vlan_row_order(tmp_path):
    doc = _compute(_parallel(tmp_path), vlans=[{"vlan": 20}, {"vlan": "0010"}])
    assert validate_vlan_carriage(doc) == (True, "ok")
    seen = [(vi, doc["rows"][vi]["vlan"], pair["cable"]["index"], pair["relation"])
            for vi in (0, 1) for pair in _decoded(doc, vi)]
    assert seen == [(0, 20, 0, "not_carried"), (0, 20, 1, "forwarding"),
                    (1, 10, 0, "forwarding"), (1, 10, 1, "not_carried")]
    assert doc["coverage"]["requested_pairs"] == doc["coverage"]["emitted_pairs"] == 4


def test_reversed_cable_orientation_preserves_member_ends_and_does_not_change_relation(tmp_path):
    interfaces = _link(tmp_path, b_port="Gi1/0/24")
    cables = compute_cable_map(interfaces)
    row = cables["cables"][0]
    row["a"], row["b"] = row["b"], row["a"]  # Labelled: the stored cable written from the other end.
    row["a_port"], row["b_port"] = row["b_port"], row["a_port"]
    for member in row["members"]:
        member["a_port"], member["b_port"] = member["b_port"], member["a_port"]
    result = _row(_compute(interfaces, cables=cables))
    assert result["relation"] == "forwarding"
    assert result["members"][0]["a"]["host"] == B and result["members"][0]["b"]["host"] == A
    assert result["members"][0]["a"]["interface_pointer"] == f"/interfaces/{B}/Gi1~10~124"
    assert result["members"][0]["b"]["interface_pointer"] == f"/interfaces/{A}/Gi1~10~11"


def test_host_and_interface_witnesses_use_original_rfc6901_tokens(tmp_path):
    escaped = "switch/a~b"
    row = _row(_compute(_link(tmp_path, names=(escaped, B))))
    end = next(e for e in (row["members"][0]["a"], row["members"][0]["b"]) if e["host"] == escaped)
    assert end["interface_pointer"] == "/interfaces/switch~1a~0b/Gi1~10~11"
    assert row["relation"] == "forwarding"


def test_bundle_requires_every_member_agreement_and_consistent_local_port_channels(tmp_path):
    consensus = _row(_compute(_bundle(tmp_path)))
    assert (consensus["relation"], consensus["basis"], len(consensus["members"])) == ("forwarding", "member_consensus", 2)
    observations = {A: _stp({10: [("Po1", "Desg", "FWD"), ("Gi1/0/2", "Desg", "FWD")]}),
                    B: _stp({10: [("Po20", "Desg", "FWD")]})}
    mixed = _row(_compute(_bundle(tmp_path), observation=observations))
    assert mixed["state"] == "unverified" and mixed["relation"] is None
    assert [m["relation"] for m in mixed["members"]] == ["forwarding", None]
    ambiguous = _row(_compute(_bundle(tmp_path, a_groups=((1, ("Gi1/0/1",)), (2, ("Gi1/0/2",))))))
    assert ambiguous["state"] == "unverified" and "consistent local bundle" in ambiguous["reason"]


def test_real_bundle_accepts_port_channel_spelling_and_different_local_numbers(tmp_path):
    interfaces = _bundle(tmp_path)
    cables = compute_cable_map(interfaces)
    assert len(cables["cables"]) == 1 and cables["cables"][0]["is_pc"] is True
    stored = _stored(interfaces)
    for member in ("Gi1/0/1", "Gi1/0/2"):  # Labelled: equivalent stored spellings of each local channel.
        stored[A][member]["port_channel"] = "Port-channel001"
        stored[B][member]["port_channel"] = "Po020"
    row = _row(_compute(interfaces, cables=cables, stored=stored))
    assert len(row["members"]) == 2
    assert (row["state"], row["relation"], row["basis"]) == ("published", "forwarding", "member_consensus")
    assert {m["a"]["stp_interface"] for m in row["members"]} == {"Po1"}


@pytest.mark.parametrize("bad", ["Gi1/0/8", "Vlan10", "Loopback1", "Po1.10", "Po0", "", None, 7])
def test_real_cable_builder_does_not_make_a_non_channel_member_identity_admissible(tmp_path, bad):
    interfaces = _bundle(tmp_path)
    for record in interfaces[A].values():
        record.port_channel = bad  # Labelled perturbation of the built records before the cable map runs.
    # The other end still names a channel, so the real legacy builder groups both links.
    cables = compute_cable_map(interfaces)
    assert len(cables["cables"]) == 1 and cables["cables"][0]["is_pc"] is True
    row = _row(_compute(interfaces, cables=cables))
    assert len(row["members"]) == 2 and row["state"] == "unverified" and row["relation"] is None


def test_physical_port_tokens_on_both_sides_cannot_certify_a_bundle(tmp_path):
    interfaces = _bundle(tmp_path)
    for host, token in ((A, "Gi1/0/8"), (B, "Gi1/0/9")):
        for record in interfaces[host].values():
            record.port_channel = token  # Labelled perturbation before the cable map runs.
    cables = compute_cable_map(interfaces)
    assert len(cables["cables"]) == 1 and len(cables["cables"][0]["members"]) == 2
    row = _row(_compute(interfaces, cables=cables))
    assert row["relation"] is None and row["state"] == "unverified"


def test_duplicate_cables_and_malformed_tail_are_retained_in_the_census(tmp_path):
    interfaces = _link(tmp_path)
    cables = compute_cable_map(interfaces)
    cables["cables"].append(deepcopy(cables["cables"][0]))  # Labelled: a repeated stored cable.
    cables["cables"].append(None)  # Unreadable stored row, not an absent cable.
    doc = _compute(interfaces, cables=cables)
    assert validate_vlan_carriage(doc) == (True, "ok")
    cov = doc["coverage"]
    assert (cov["cable_rows"], cov["assessed_cables"], cov["unreadable_cables"], cov["requested_pairs"]) == (3, 2, 1, 2)
    assert [pair["state"] for pair in _decoded(doc)] == ["unverified", "unverified"]
    assert all(pair["relation"] is None and "repeated" in pair["reason"] for pair in _decoded(doc))
    assert doc["cables"][2]["pointer"] == "/cable_map/cables/2" and doc["cables"][2]["scope"] == "unreadable"
    assert doc["issues"]


@pytest.mark.parametrize("damage", ["outer_port", "extra_member_key"])
@pytest.mark.parametrize("vlans", [[{"vlan": 10}], [{"vlan": 10}, {"vlan": 20}]])
def test_readable_duplicate_inside_a_refused_tail_withholds_both_and_the_result_validates(tmp_path, damage, vlans):
    interfaces = _link(tmp_path)
    cables = compute_cable_map(interfaces)
    cables["cables"].append(deepcopy(cables["cables"][0]))  # Labelled damage of the stored cable map.
    if damage == "outer_port":
        cables["cables"][1]["a_port"] = "Gi1/0/2"
    else:
        cables["cables"][1]["members"][0]["extra"] = "malformed stored member"
    before = deepcopy(cables)
    doc = _compute(interfaces, cables=cables, vlans=vlans)
    assert validate_vlan_carriage(doc) == (True, "ok")
    assert cables == before
    assert doc["state"] == "unverified" and doc["coverage"]["input_census_complete"] is False
    assert doc["coverage"]["cable_rows"] == 2 and len(doc["rows"]) == len(vlans)
    for vi in range(len(vlans)):
        pairs = _decoded(doc, vi)
        assert pairs and all(pair["state"] == "unverified" and pair["relation"] is None for pair in pairs)
        assert all(member["state"] == "unverified" for pair in pairs for member in pair["members"])
    assert {cable["members"][0]["pointer"] for cable in doc["cables"]} == {
        "/cable_map/cables/0/members/0", "/cable_map/cables/1/members/0"}
    assert any(issue["pointer"].startswith("/cable_map/cables/1") for issue in doc["issues"])


@pytest.mark.parametrize("damage", ["outer_port", "extra_member_key"])
def test_a_non_overlapping_refused_tail_keeps_the_unrelated_positive_and_validates(tmp_path, damage):
    interfaces = _parallel(tmp_path, second="10")
    cables = compute_cable_map(interfaces)
    assert len(cables["cables"]) == 2
    if damage == "outer_port":
        cables["cables"][1]["a_port"] = "Gi1/0/99"  # Labelled damage.
    else:
        cables["cables"][1]["members"][0]["extra"] = True  # Labelled damage.
    doc = _compute(interfaces, cables=cables)
    assert validate_vlan_carriage(doc) == (True, "ok")
    assert doc["state"] == "unverified" and doc["rows"][0]["state"] == "unverified"
    pairs = _decoded(doc)
    assert (pairs[0]["state"], pairs[0]["relation"]) == ("published", "forwarding")
    if damage == "outer_port":
        assert len(pairs) == 1 and doc["cables"][1]["scope"] == "unreadable"
    else:
        assert pairs[1]["state"] == "unverified" and pairs[1]["relation"] is None


def test_a_folded_bundle_member_cannot_borrow_an_unwitnessed_orientation(tmp_path):
    # Source order makes the first physical link A:1 -> B:11, while only B reports
    # the second as B:22 -> A:2. The legacy builder folds by unordered host pair.
    interfaces = {
        A: _built(tmp_path, A, {"show interfaces trunk": _ios_trunk([("Po1", "10", "1", True)]),
                                "show etherchannel summary": _etherchannel([(1, ("Gi1/0/1", "Gi1/0/2", "Gi1/0/22"))]),
                                "show cdp neighbors detail": _cdp([("Gi1/0/1", B, "Gi1/0/11")])}),
        B: _built(tmp_path, B, {"show interfaces trunk": _ios_trunk([("Po20", "10", "1", True)]),
                                "show etherchannel summary": _etherchannel([(20, ("Gi1/0/11", "Gi1/0/22", "Gi1/0/2"))]),
                                "show cdp neighbors detail": _cdp([("Gi1/0/22", A, "Gi1/0/2")])}),
    }
    cables = compute_cable_map(interfaces)
    assert len(cables["cables"]) == 1
    cable = cables["cables"][0]
    assert (cable["a"], cable["b"]) == (A, B)
    assert cable["members"] == [{"a_port": "Gi1/0/1", "b_port": "Gi1/0/11"},
                                {"a_port": "Gi1/0/22", "b_port": "Gi1/0/2"}]
    before = deepcopy(cables)
    row = _row(_compute(interfaces, cables=cables))
    assert cables == before  # No hidden orientation repair of the cable owner.
    assert row["state"] == "unverified" and row["relation"] is None
    assert row["members"][0]["relation"] == "forwarding"
    refused = row["members"][1]
    assert refused["state"] == "unverified" and refused["relation"] is None
    assert (refused["a"]["port"], refused["b"]["port"]) == ("Gi1/0/22", "Gi1/0/2")
    for end in (refused["a"], refused["b"]):
        assert end["state"] == "unverified" and end["signal"] is None and end["hold"] == "bundle_orientation"
        assert "no stored neighbor observation" in end["reason"]
        assert "/cable_map/cables/0/members/1" in end["refs"]


def test_correctly_oriented_one_direction_bundle_keeps_its_positive_without_inventing_reciprocity(tmp_path):
    interfaces = _bundle(tmp_path, cdp=(True, False))
    cables = compute_cable_map(interfaces)
    assert len(cables["cables"]) == 1 and cables["cables"][0]["confirmation"] == f"One end ({A})"
    row = _row(_compute(interfaces, cables=cables))
    assert row["relation"] == "forwarding" and row["basis"] == "member_consensus"
    for member in row["members"]:
        assert member["a"]["interface_pointer"] + "/cdp_neighbor" in member["a"]["refs"]
        assert member["a"]["interface_pointer"] + "/neighbor_port" in member["a"]["refs"]
        assert not any(ref.endswith("/cdp_neighbor") or ref.endswith("/neighbor_port") for ref in member["b"]["refs"])


def test_one_direction_nonbundled_physical_observation_remains_admissible(tmp_path):
    interfaces = _link(tmp_path, cdp=(True, False))
    cables = compute_cable_map(interfaces)
    assert cables["cables"][0]["is_pc"] is False and cables["cables"][0]["confirmation"] == f"One end ({A})"
    assert _row(_compute(interfaces, cables=cables))["relation"] == "forwarding"


def test_published_bundle_record_requires_its_stored_orientation_witnesses(tmp_path):
    doc = _compute(_bundle(tmp_path))
    assert validate_vlan_carriage(doc) == (True, "ok")
    member = doc["cables"][0]["members"][0]
    for end in (member["a"], member["b"]):  # Labelled mutation of the stored result.
        end["refs"] = [ref for ref in end["refs"] if not ref.endswith(("/cdp_neighbor", "/neighbor_port"))]
    assert validate_vlan_carriage(doc) == (False, "bundle_orientation_witness")


@pytest.mark.parametrize("bad", [None, [], {"a_port": PORT}, {"a_port": PORT, "b_port": PORT, "extra": True}])
def test_malformed_bundle_member_is_not_dropped_or_executed_as_another_shape(tmp_path, bad):
    interfaces = _bundle(tmp_path)
    cables = compute_cable_map(interfaces)
    cables["cables"][0]["members"][1] = bad  # Labelled damage of the stored cable map.
    row = _row(_compute(interfaces, cables=cables))
    assert len(row["members"]) == 2 and row["members"][1]["state"] == "unverified"
    assert row["state"] == "unverified" and row["relation"] is None


# ---------------------------------------------------------------------------------------------------------------
# (b) edges, unreadable cables, held rows and per-VLAN state
# ---------------------------------------------------------------------------------------------------------------
def test_edge_cables_keep_their_far_port_text_and_are_counted_blind_spots_never_issues(tmp_path):
    interfaces = _link(tmp_path)
    interfaces[A].update(_built(tmp_path, A, {"show cdp neighbors detail": _cdp(
        [("GigabitEthernet1/0/9", "AP-floor1", "Gi0")], platform="cisco AIR-AP2802I")
        + _cdp([("GigabitEthernet1/0/10", "SEP00112233AABB", "Port 1")], platform="Cisco IP Phone 8845")}))
    cables = compute_cable_map(interfaces)
    edges = [c for c in cables["cables"] if "AP-floor1" in (c["a"], c["b"]) or "SEP00112233AABB" in (c["a"], c["b"])]
    assert len(edges) == 2 and {c["b_port"] for c in edges} == {"Gi0", "Port"}
    doc = _compute(interfaces, cables=cables)
    assert validate_vlan_carriage(doc) == (True, "ok")
    stored = [c for c in doc["cables"] if c["scope"] == "edge"]
    assert len(stored) == doc["coverage"]["edge_cables"] == 2
    assert {c["ends"]["b_port"] for c in stored} == {"Gi0", "Port"} and {c["hold"] for c in stored} == {"edge_uncollected"}
    assert all(c["members"][0]["b"]["hold"] == "missing_interface" for c in stored)
    assert doc["issues"] == [] and doc["coverage"]["input_census_complete"] is True
    assert doc["coverage"]["assessed_cables"] == 1 and doc["coverage"]["requested_pairs"] == 1
    assert len(doc["rows"][0]["codes"]) == 4  # One assessed single-member cable: cable, member, a-end, b-end.
    assert doc["rows"][0]["state"] == "published"  # No VLAN state is derived from an edge cable.
    assert doc["state"] == "not_collected" and "blind spot" in doc["reason"]


def test_an_unreadable_cable_carries_one_verdict_and_no_codes(tmp_path):
    interfaces = _link(tmp_path)
    cables = compute_cable_map(interfaces)
    cables["cables"].insert(0, {"a": A})  # Labelled damage: an incomplete stored cable before the real one.
    doc = _compute(interfaces, cables=cables)
    assert validate_vlan_carriage(doc) == (True, "ok")
    assert (doc["cables"][0]["scope"], doc["cables"][0]["hold"]) == ("unreadable", "cable_unreadable")
    assert len(doc["rows"][0]["codes"]) == 4 and _decoded(doc)[0]["cable"]["index"] == 1
    assert doc["rows"][0]["state"] == "unverified"


def test_a_vlan_state_is_its_own_never_inherited_from_another_vlans_cable(tmp_path):
    interfaces = _link(tmp_path, (None, True), (None, True))
    observations = {A: _stp({10: [(PORT, "Desg", "FWD")], 20: [(PORT, "Desg", "LRN")]}),
                    B: _stp({10: [(PORT, "Desg", "FWD")], 20: [(PORT, "Desg", "FWD")]})}
    doc = _compute(interfaces, observation=observations, vlans=[{"vlan": 10}, {"vlan": 20}])
    assert validate_vlan_carriage(doc) == (True, "ok")
    assert [row["state"] for row in doc["rows"]] == ["published", "unverified"]
    assert doc["rows"][0]["reason"] is None and doc["state"] == "unverified"


@pytest.mark.parametrize("damage", ["missing_members", "missing_pc", "bad_scanned_port", "outer_mismatch"])
def test_off_scan_identity_does_not_hide_a_malformed_cable_as_an_ordinary_edge(tmp_path, damage):
    interfaces = _link(tmp_path)
    cables = compute_cable_map(interfaces)
    stored = _stored(interfaces)
    del stored[B]  # The real cable now addresses an off-scan peer.
    cable = cables["cables"][0]
    if damage == "missing_members":
        cable["members"] = []
    elif damage == "missing_pc":
        del cable["is_pc"]
    elif damage == "bad_scanned_port":
        cable["a_port"] = cable["members"][0]["a_port"] = "not-a-port"
    else:
        cable["a_port"] = "Gi1/0/2"
    doc = _compute(interfaces, cables=cables, stored=stored)
    assert validate_vlan_carriage(doc) == (True, "ok")
    assert doc["cables"][0]["scope"] == "unreadable"
    assert doc["coverage"]["edge_cables"] == 0 and doc["coverage"]["unreadable_cables"] == 1
    assert doc["rows"][0]["state"] == "unverified"
    assert "unverified" in doc["rows"][0]["reason"] and doc["state"] == "unverified"


def test_an_edge_keeps_equivalent_scanned_port_aliases_and_exact_far_port_text(tmp_path):
    interfaces = _link(tmp_path)
    cables = compute_cable_map(interfaces)
    stored = _stored(interfaces)
    del stored[B]
    cable = cables["cables"][0]
    cable["a_port"] = LONG  # Declared equivalent supplied-cable spelling, not a new port.
    cable["b_port"] = cable["members"][0]["b_port"] = "Gi0"
    doc = _compute(interfaces, cables=cables, stored=stored)
    assert validate_vlan_carriage(doc) == (True, "ok")
    assert doc["cables"][0]["scope"] == "edge" and doc["coverage"]["edge_cables"] == 1
    assert doc["cables"][0]["ends"]["a_port"] == LONG
    assert doc["cables"][0]["ends"]["b_port"] == "Gi0"
    assert doc["rows"][0]["codes"] == "" and doc["state"] == "not_collected"


def test_every_unheld_row_stores_one_character_per_cable_and_three_per_member_from_the_owner_alphabets(tmp_path):
    interfaces = {**_bundle(tmp_path)}
    doc = _compute(interfaces, vlans=[{"vlan": 10}, {"vlan": 20}, {"vlan": None}])
    assert validate_vlan_carriage(doc) == (True, "ok")
    assert doc["code_tables"] == {"verdict": list(VERDICT_CODES), "end": list(END_CODES)}
    width = sum(1 + 3 * len(c["members"]) for c in doc["cables"] if c["scope"] == "assessed")
    assert [len(row["codes"]) for row in doc["rows"]] == [width, width, 0]
    assert doc["rows"][2]["hold"] == "vlan_unreadable" and doc["rows"][2]["state"] == "unverified"
    assert set("".join(row["codes"] for row in doc["rows"])) <= set(CODE_ALPHABET)
    assert doc["coverage"]["emitted_pairs"] == 2 and doc["coverage"]["requested_pairs"] == 3
    for mutated in ("x" + doc["rows"][0]["codes"][1:], doc["rows"][0]["codes"][:-1]):
        damaged = deepcopy(doc)
        damaged["rows"][0]["codes"] = mutated  # Labelled mutation of the stored result.
        assert validate_vlan_carriage(damaged)[0] is False


# ---------------------------------------------------------------------------------------------------------------
# VLAN rows
# ---------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("bad", [True, 0, 4095, "10x", None])
def test_invalid_vlan_never_borrows_vlan_one_evidence(tmp_path, bad):
    doc = _compute(_link(tmp_path), vlans=[{"vlan": bad}])
    assert validate_vlan_carriage(doc) == (True, "ok")
    row = doc["rows"][0]
    assert row["vlan"] is None and row["hold"] == "vlan_unreadable" and row["codes"] == ""
    assert row["state"] == "unverified" and carriage_row_cables(doc, 0) == []


def test_vlan_alias_collision_keeps_both_rows_and_refuses_a_definite_relation(tmp_path):
    doc = _compute(_link(tmp_path), vlans=[{"vlan": 10}, {"vlan": "0010"}])
    assert validate_vlan_carriage(doc) == (True, "ok")
    assert [(r["hold"], r["state"], r["codes"]) for r in doc["rows"]] == [("vlan_duplicate", "unverified", "")] * 2
    assert doc["issues"] == [] and doc["coverage"]["input_census_complete"] is False


@pytest.mark.parametrize(("selector", "expected"), [
    (1, 1), (10, 10), (4094, 4094), ("0010", 10), ("0000000000000010", 10),
    (True, None), (False, None), (10.0, None), (0, None), (4095, None),
    ("10.0", None), (" 10", None), ("+10", None), ("00000000000000010", None),
    (None, None), ([], None), ({}, None),
])
def test_public_vlan_row_selector_and_producer_share_exact_admission(tmp_path, selector, expected):
    source = {"vlan": selector}
    before = deepcopy(source)
    assert vlan_row_identity(source) == expected
    doc = _compute(_link(tmp_path), vlans=[source])
    assert validate_vlan_carriage(doc) == (True, "ok")
    assert doc["rows"][0]["vlan"] == expected and source == before
    if expected is None:
        assert doc["rows"][0]["state"] == "unverified" and doc["rows"][0]["hold"] == "vlan_unreadable"


@pytest.mark.parametrize("row", [None, [], "10", 10, {}, {"other": 10}])
def test_public_vlan_row_selector_does_not_invent_a_missing_row_identity(row):
    assert vlan_row_identity(row) is None


@pytest.mark.parametrize("source", ["cable_map", "interfaces", "stp_topology_observations", "vlan_cutover"])
def test_failed_input_is_not_an_empty_or_successful_carriage_section(tmp_path, source):
    doc = _compute(_link(tmp_path), failed=(source,))
    assert validate_vlan_carriage(doc) == (True, "ok")
    assert doc["state"] == "analysis_unavailable"
    assert doc["rows"][0]["hold"] == "failed_source" and doc["rows"][0]["codes"] == ""
    assert any(issue["pointer"] == "/" + source for issue in doc["issues"])


def test_missing_empty_and_malformed_sources_remain_distinct(tmp_path):
    interfaces = _link(tmp_path)
    stored = _stored(interfaces)
    missing = compute_vlan_carriage(None, stored, None, [{"vlan": 10}])
    empty = compute_vlan_carriage(compute_cable_map({}), {}, {}, [{"vlan": 10}])
    malformed = compute_vlan_carriage({"cables": "unreadable"}, stored, {}, [{"vlan": 10}])
    for doc in (missing, empty, malformed):
        assert validate_vlan_carriage(doc) == (True, "ok")
        assert doc["coverage"]["capture_completeness_claim"] is False
    assert missing["state"] == "not_collected" and missing["coverage"]["cable_rows"] is None
    assert missing["rows"][0]["hold"] == "missing_source"
    assert empty["state"] == "collected_but_empty" and empty["coverage"]["requested_pairs"] == 0
    assert empty["rows"][0]["state"] == "collected_but_empty" and empty["rows"][0]["hold"] is None
    assert malformed["state"] == "unverified" and malformed["rows"][0]["hold"] == "malformed_source"
    assert _compute(interfaces, vlans=[])["state"] == "collected_but_empty"


def test_json_roundtrip_sparse_records_and_input_purity_preserve_identical_output(tmp_path):
    interfaces = _link(tmp_path, (None, True), (None, True))
    observations = {A: _observation(), B: _observation()}
    cables, vlans = compute_cable_map(interfaces), [{"vlan": "0010"}]
    stored = _stored(interfaces)
    before = deepcopy((stored, observations, cables, vlans))
    doc = compute_vlan_carriage(cables, interfaces, observations, vlans)
    round_trip = json.loads(json.dumps([cables, stored, observations, vlans]))
    sparse = {h: {p: {k: v for k, v in r.items() if v != ""} for p, r in ports.items()}
              for h, ports in round_trip[1].items()}
    assert compute_vlan_carriage(round_trip[0], round_trip[1], round_trip[2], round_trip[3]) == doc
    assert compute_vlan_carriage(round_trip[0], sparse, round_trip[2], round_trip[3]) == doc
    assert (stored, observations, cables, vlans) == before
    assert validate_vlan_carriage(json.loads(json.dumps(doc))) == (True, "ok")
    doc["cables"][0]["ends"]["a"] = "changed-output"
    assert (stored, observations, cables, vlans) == before


@pytest.mark.parametrize("value", ["10 \t 20", "10 \n 20", "10, \t ,20"])
def test_internal_mixed_whitespace_tokens_are_refused_with_the_actual_field_witness(tmp_path, value):
    interfaces = _link(tmp_path)
    stored = _stored(interfaces)
    stored[A][PORT]["trunk_allowed_vlans"] = value  # Labelled stored damage (a capture line cannot hold \n).
    row = _row(_compute(interfaces, stored=stored))
    assert row["state"] == "unverified" and row["relation"] is None
    assert f"/interfaces/{A}/Gi1~10~11/trunk_allowed_vlans" in row["members"][0]["a"]["refs"]
    assert "expression is malformed" in row["members"][0]["a"]["reason"]


@pytest.mark.parametrize("value", ["10 20", "10 , 20-23", "10,20 30"])
def test_the_same_range_separator_grammar_keeps_valid_space_and_comma_lists(tmp_path, value):
    row = _row(_compute(_link(tmp_path, (value, True), (value, True))))
    assert row["state"] == "published" and row["relation"] == "forwarding"


# ---------------------------------------------------------------------------------------------------------------
# (d) blank allowance and the literal 'none'
# ---------------------------------------------------------------------------------------------------------------
def test_the_trunk_parser_keeps_a_literal_none_beside_a_blank_allowed_list():
    parsed = parse_show_interface_trunk_table(_ios_trunk([(PORT, "none", "1", True), ("Gi1/0/2", "10", "1", True)]))
    assert (parsed[PORT]["allowed_vlans"], parsed[PORT]["allowed_literal"]) == ("", "none")
    assert (parsed["Gi1/0/2"]["allowed_vlans"], parsed["Gi1/0/2"]["allowed_literal"]) == ("10", "")


def test_a_later_nexus_table_header_closes_the_allowed_section():
    text = _nexus_trunk([("Eth1/1", "1", "trnk-bndl", "Po10", "1-4094"), ("Po10", "1", "trunking", "", "none")],
                        forwarding={"Po10": "1,20"})
    parsed = parse_show_interface_trunk_table(text)
    # Before W52 v2 the Err-disabled and STP Forwarding rows kept writing allowed_vlans (Po10 read 1,20).
    assert (parsed["Po10"]["allowed_vlans"], parsed["Po10"]["allowed_literal"]) == ("", "none")
    assert parsed["Eth1/1"]["allowed_vlans"] == "1-4094" and parsed["Eth1/1"]["port_channel"] == "Po10"


def test_build_stores_the_literal_none_in_its_own_interface_field(tmp_path):
    interfaces = _link(tmp_path, ("none", True), ("10", True))
    assert (interfaces[A][PORT].trunk_allowed_vlans, interfaces[A][PORT].trunk_allowed_none) == ("", "none")
    assert interfaces[B][PORT].trunk_allowed_none == ""
    assert "trunk_allowed_none" in vc.CARRIAGE_INTERFACE_FIELDS


@pytest.mark.parametrize("damage", ["both", "unknown_literal"])
def test_two_answers_to_one_allowance_question_are_unreadable(tmp_path, damage):
    interfaces = _link(tmp_path)
    stored = _stored(interfaces)
    # Labelled stored damage: no parser writes both fields, or another literal.
    stored[A][PORT]["trunk_allowed_none"] = "none" if damage == "both" else "maybe"
    doc = _compute(interfaces, stored=stored)
    row = _row(doc)
    assert row["state"] == "unverified" and row["relation"] is None
    end = row["members"][0]["a"]
    assert "expression is malformed" in end["reason"]
    assert f"/interfaces/{A}/Gi1~10~11/trunk_allowed_none" in end["refs"]
    assert any(issue["pointer"] == f"/interfaces/{A}/Gi1~10~11/trunk_allowed_none" for issue in doc["issues"])


def test_a_blank_allowed_list_falls_through_to_no_evidence_even_with_a_native_match(tmp_path):
    interfaces = _link(tmp_path, (None, True), (None, True), native=("10", "10"))
    end = _row(_compute(interfaces))["members"][0]["a"]
    assert end["state"] == "not_collected" and "no admitted PVST state or explicit trunk allowance" in end["reason"]


# ---------------------------------------------------------------------------------------------------------------
# the closed stored contract
# ---------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("mutation", ["outer_port", "member_and_outer_port", "pointer_port", "pointer_host"])
def test_one_closed_record_cannot_contradict_its_member_interface_identity(tmp_path, mutation):
    doc = _compute(_link(tmp_path))
    assert validate_vlan_carriage(doc) == (True, "ok")
    cable, end = doc["cables"][0], doc["cables"][0]["members"][0]["a"]
    if mutation == "outer_port":
        cable["ends"]["a_port"] = "Gi1/0/2"
    elif mutation == "member_and_outer_port":
        cable["ends"]["a_port"] = end["port"] = "Gi1/0/2"
    else:
        old = end["interface_pointer"]
        new = f"/interfaces/{A}/Gi1~10~12" if mutation == "pointer_port" else "/interfaces/unrelated/Gi1~10~11"
        end["interface_pointer"] = new
        end["refs"] = [new if ref == old else ref for ref in end["refs"]]
    assert validate_vlan_carriage(doc)[0] is False, mutation


def test_duplicate_stored_vlan_identity_cannot_keep_two_published_relations(tmp_path):
    interfaces = _link(tmp_path)
    doc = _compute(interfaces, vlans=[{"vlan": 10}, {"vlan": 20}])
    assert validate_vlan_carriage(doc) == (True, "ok")
    doc["rows"][1]["vlan"] = 10  # Labelled mutation of the stored result.
    assert validate_vlan_carriage(doc) == (False, "row_hold")
    # Actual duplicate selectors are retained as explicitly held rows.
    genuine = _compute(interfaces, vlans=[{"vlan": 10}, {"vlan": "0010"}])
    assert validate_vlan_carriage(genuine) == (True, "ok")
    assert all(row["hold"] == "vlan_duplicate" and row["codes"] == "" for row in genuine["rows"])


@pytest.mark.parametrize("mutation", ["extra", "schema", "code_tables", "false_census", "capture_promotion", "alphabet",
                                      "end_hold", "member_contradiction", "cable_contradiction", "row_identity",
                                      "missing_limitation", "cable_census", "held_without_cause", "edge_hold"])
def test_closed_stored_contract_refuses_inconsistent_or_promoting_mutations(tmp_path, mutation):
    doc = _compute(_link(tmp_path), vlans=[{"vlan": 10}, {"vlan": 20}])
    assert validate_vlan_carriage(doc) == (True, "ok")
    row = doc["rows"][0]
    published_blocked = CODE_ALPHABET[VERDICT_CODES.index("stp_blocked:typed_pvst")]
    if mutation == "extra":
        row["healthy"] = True
    elif mutation == "schema":
        doc["schema"] = "vlan_carriage/future"
    elif mutation == "code_tables":
        doc["code_tables"]["end"] = list(reversed(doc["code_tables"]["end"]))
    elif mutation == "false_census":
        doc["coverage"]["by_state"]["published"] = True
    elif mutation == "capture_promotion":
        doc["coverage"]["capture_completeness_claim"] = True
    elif mutation == "alphabet":
        row["codes"] = "~" + row["codes"][1:]
    elif mutation == "end_hold":
        doc["cables"][0]["members"][0]["a"]["hold"] = "missing_interface"
    elif mutation == "member_contradiction":
        row["codes"] = row["codes"][0] + published_blocked + row["codes"][2:]
    elif mutation == "cable_contradiction":
        row["codes"] = published_blocked + row["codes"][1:]
    elif mutation == "row_identity":
        row["vlan_pointer"] = "/vlan_cutover/1"
    elif mutation == "missing_limitation":
        doc["limitations"].pop(2)
    elif mutation == "cable_census":
        doc["coverage"]["edge_cables"] += 1
    elif mutation == "held_without_cause":
        row["hold"], row["codes"] = "vlan_unreadable", ""
    else:
        doc["cables"][0]["hold"] = "edge_uncollected"
    assert validate_vlan_carriage(doc)[0] is False, mutation


# PURE dispatch controls follow ALL original owner controls; no capture writer or timed call is introduced.
def _cpu_routing_subject(*, first_vid=10):
    from test_ui_projection_vlan_carriage import _round2_bundle

    observations = {
        A: _stp({first_vid: [("Po10", "Desg", "FWD")], 20: [("Po10", "Altn", "BLK")]}),
        B: _stp({first_vid: [("Po10", "Altn", "BLK")], 20: [("Po10", "Desg", "FWD")]}),
    }
    snap = _round2_bundle(observations)
    snap["vlan_cutover"] = [{"vlan": vid} for vid in (first_vid, 20, 30)]
    for records in snap["interfaces"].values():
        for record in records.values():
            record["trunk_allowed_vlans"] = f"{first_vid},20,30"
    snap["vlan_carriage"] = compute_vlan_carriage(
        snap["cable_map"], snap["interfaces"], observations, snap["vlan_cutover"])
    assert validate_vlan_carriage(snap["vlan_carriage"]) == (True, "ok")
    # DISTINCT valid records are necessary: complete-value sharing must not skip the real peer callback.
    assert observations[A] != observations[B]
    return snap


def _cpu_routing_outputs(snap, *, admission=None):
    from cisco_toolkit import ui_projection as uip

    admission = uip.carriage_admission(snap) if admission is None else admission
    complete = (deepcopy(admission.source), admission.section is snap["vlan_carriage"], admission.failed,
                tuple(admission.gaps.items()), admission.offsets,
                tuple((str(host), type(host), record is snap["stp_topology_observations"].get(str(host)),
                       type(index), None if index is None else tuple(index.items()))
                      for host, (record, index) in admission.observations.items()))
    document = uip.project(snap, carriage=admission)
    pages = [uip.project_vlan_carriage(snap, vi, offset, limit, admission=admission)
             for vi in range(len(snap["vlan_cutover"])) for offset, limit in ((0, 200), (0, 1), (1, 1))]
    return complete, document, pages


@pytest.mark.parametrize("damage", ["none", "new-role", "error", "logical-alias", "source-port", "beside",
                                     "key-order"])
def test_cpu_dispatch_keeps_real_complete_admission_documents_and_pages(monkeypatch, damage):
    from cisco_toolkit import ui_projection as uip

    snap = _cpu_routing_subject()
    if damage == "new-role":
        snap["stp_topology_observations"][B] = _stp({30: [("Po10", "Desg", "FWD")]})
    elif damage == "error":
        snap["stp_topology_observations"][B] = produce_stp_topology_observation(
            "", "", state_capture_state="error", detail_capture_state="error")
    elif damage == "logical-alias":
        snap["interfaces"][B]["Po010"] = {**snap["interfaces"][B]["Po10"], "port": "Po010"}
    elif damage == "source-port":
        snap["interfaces"][B]["Po10"]["port"] = "Po99"
    elif damage == "beside":
        snap["stp_topology_observations"][B] = _stp(
            {10: [("Po10", "Altn", "BLK"), (PORT, "Desg", "FWD")]})
    elif damage == "key-order":
        snap["stp_topology_observations"][B] = dict(reversed(tuple(
            snap["stp_topology_observations"][B].items())))
    before, results = deepcopy(snap), []
    for mode in ("enabled", "old-cpu", "old-token", "unplanned"):
        with monkeypatch.context() as patch:
            if mode == "old-cpu":
                patch.setattr(uip, "_CARRIAGE_CPU_ROUTING_ENABLED", False)
            elif mode == "old-token":
                patch.setattr(uip, "_CARRIAGE_ROUTING_TOKEN_ENABLED", False)
            elif mode == "unplanned":
                patch.setattr(uip, "_carriage_routing_plan", lambda: None)
            results.append(_cpu_routing_outputs(snap))
    assert all(result == results[0] for result in results) and snap == before
    if damage not in ("none", "key-order"):
        assert results[0][1]["inventory"]["vlans"]["rows"]["items"][0]["selections"]["carriage"]["state"] == "unverified"


@pytest.mark.parametrize("kind", ["host", "interface", "vid"])
@pytest.mark.parametrize("effect", ["observe", "runtime-error", "type-error"])
def test_cpu_role_key_history_keeps_foreign_seed_then_plain_lookup_callbacks(monkeypatch, kind, effect):
    from cisco_toolkit import ui_projection as uip

    owner_index, owner_query, results, traces = uip.carriage_role_index, uip._carriage_role_query, [], []
    state = {}

    class ForeignText(str):
        def __hash__(self):
            state["trace"].append(("hash-text", str(self)))
            return str.__hash__(self)

        def __eq__(self, other):
            state["trace"].append(("eq-text", type(other)))
            if state["armed"] and type(other) is str and effect != "observe":
                raise (RuntimeError if effect == "runtime-error" else TypeError)("foreign stored role key")
            return str.__eq__(self, other)

    class ForeignVid(int):
        def __hash__(self):
            state["trace"].append(("hash-vid", int(self)))
            return int.__hash__(self)

        def __eq__(self, other):
            state["trace"].append(("eq-vid", type(other)))
            if state["armed"] and type(other) is int and effect != "observe":
                raise (RuntimeError if effect == "runtime-error" else TypeError)("foreign stored role key")
            return int.__eq__(self, other)

    for enabled in (False, True):
        snap = _cpu_routing_subject()
        end, row = snap["vlan_carriage"]["cables"][0]["members"][0]["a"], snap["vlan_carriage"]["rows"][0]
        state.update(trace=[], armed=False, changed=False, restored=False)

        def index(record):
            result = owner_index(record)
            if not state["changed"]:
                assert record is snap["stp_topology_observations"][A]
                if kind == "vid":
                    row["vlan"] = ForeignVid(10)
                else:
                    field = "host" if kind == "host" else "stp_interface"
                    end[field] = ForeignText(end[field])
                state["changed"] = True
            return result

        def query(record, interface, vid, *, index):
            result = owner_query(record, interface, vid, index=index)
            if not state["restored"]:
                if kind == "vid":
                    assert type(vid) is ForeignVid
                    row["vlan"] = 10
                else:
                    field = "host" if kind == "host" else "stp_interface"
                    assert type(end[field]) is ForeignText
                    end[field] = str(end[field])
                state["restored"], state["armed"] = True, True
            return result

        with monkeypatch.context() as patch:
            patch.setattr(uip, "_CARRIAGE_CPU_ROUTING_ENABLED", enabled)
            patch.setattr(uip, "carriage_role_index", index)
            patch.setattr(uip, "_carriage_role_query", query)
            if effect == "runtime-error":
                with pytest.raises(RuntimeError) as raised:
                    uip.carriage_admission(snap)
                result = type(raised.value), raised.value.args
                admission = None
            else:
                admission = uip.carriage_admission(snap)
                result = None
        assert state["changed"] and state["restored"]
        traces.append(tuple(state["trace"]))
        state["armed"] = False  # Restore the separate, unguarded lazy-render owner domain.
        results.append(result if admission is None else _cpu_routing_outputs(snap, admission=admission))
        if effect == "type-error":
            assert admission.source["state"] == "unverified" and list(admission.gaps) == [0, 1, 2]
    assert traces[0] == traces[1] and results[0] == results[1]
    assert any(event[0].startswith("eq-") for event in traces[0])


@pytest.mark.parametrize("effect", ["observe", "runtime-error", "type-error"])
def test_cpu_host_proof_history_keeps_unsafe_admission_then_plain_index_callbacks(monkeypatch, effect):
    from cisco_toolkit import ui_projection as uip

    admission_owner, query_owner, index_owner = (uip.carriage_observation_admission,
                                                 uip._carriage_role_query, uip.carriage_role_index)
    state, results, traces = {}, [], []

    class ForeignHost(str):
        def __hash__(self):
            state["trace"].append(("hash", str(self)))
            return str.__hash__(self)

        def __eq__(self, other):
            state["trace"].append(("eq", type(other)))
            if state["armed"] and type(other) is str and effect != "observe":
                raise (RuntimeError if effect == "runtime-error" else TypeError)("foreign stored host proof key")
            return str.__eq__(self, other)

    for token_enabled in (False, True):
        snap = _cpu_routing_subject()
        peer = snap["vlan_carriage"]["cables"][0]["members"][0]["b"]
        state.update(trace=[], armed=False)
        callbacks, indexes, queries = [], [], []

        def admitted(record):
            result = admission_owner(record)
            if record is snap["stp_topology_observations"][A]:
                callbacks.append(A)
                peer["host"] = ForeignHost(B)
            elif record is snap["stp_topology_observations"][B]:
                callbacks.append(B)
                assert type(peer["host"]) is ForeignHost
                peer["host"] = B
            return result

        def index(record):
            assert callbacks == [A, B] and type(peer["host"]) is str and peer["host"] == B
            indexes.append(record)
            return index_owner(record)

        def query(record, interface, vid, *, index):
            assert callbacks == [A, B] and type(peer["host"]) is str
            queries.append((record, interface, vid))
            result = query_owner(record, interface, vid, index=index)
            if record is snap["stp_topology_observations"][B] and interface == "Po10":
                state["armed"] = True  # The next physical-beside empty join must retain the old proof-key hooks.
            return result

        with monkeypatch.context() as patch:
            patch.setattr(uip, "_CARRIAGE_ROUTING_TOKEN_ENABLED", token_enabled)
            patch.setattr(uip, "carriage_observation_admission", admitted)
            patch.setattr(uip, "carriage_role_index", index)
            patch.setattr(uip, "_carriage_role_query", query)
            if effect == "runtime-error":
                with pytest.raises(RuntimeError) as raised:
                    uip.carriage_admission(snap)
                result, admission = (type(raised.value), raised.value.args), None
            else:
                admission = uip.carriage_admission(snap)
                result = None
        assert callbacks == [A, B] and indexes and queries
        assert any(record is snap["stp_topology_observations"][B] for record, _interface, _vid in queries)
        traces.append(tuple(state["trace"]))
        state["armed"] = False
        results.append(result if admission is None else _cpu_routing_outputs(snap, admission=admission))
        if effect == "type-error":
            assert admission.source["state"] == "unverified" and list(admission.gaps) == [0, 1, 2]
    assert traces[0] == traces[1] and results[0] == results[1]


@pytest.mark.parametrize("fallback", ["zero", "saturated", "noninteger", "factory", "constructor", "foreign-index",
                                       "copied-observation"])
def test_cpu_token_optional_fallbacks_keep_existing_real_owner_outputs(monkeypatch, fallback):
    from cisco_toolkit import ui_projection as uip

    snap = _cpu_routing_subject()
    index_owner, admission_owner = uip.carriage_role_index, uip.carriage_observation_admission
    results, constructor_calls = [], []

    class ForeignIndex(dict):
        pass

    def foreign_admission(record):
        state, reason, admitted = admission_owner(record)
        return state, reason, deepcopy(admitted) if admitted is not None else None

    def constructor(*args):
        constructor_calls.append(args)
        return object()  # No token-like return can supply a source or join certificate.

    for enabled in (False, True):
        with monkeypatch.context() as patch:
            patch.setattr(uip, "_CARRIAGE_ROUTING_TOKEN_ENABLED", enabled)
            if fallback in ("zero", "saturated", "noninteger"):
                patch.setattr(uip, "_CARRIAGE_ROUTING_TOKEN_LIMIT", {"zero": 0, "saturated": 1, "noninteger": True}[fallback])
            elif fallback == "factory":
                patch.setattr(uip, "_carriage_routing_token", constructor)
            elif fallback == "constructor":
                patch.setattr(uip, "_CarriageRoutingToken", constructor)
            elif fallback == "foreign-index":
                patch.setattr(uip, "carriage_role_index", lambda record: ForeignIndex(index_owner(record)))
            else:
                patch.setattr(uip, "carriage_observation_admission", foreign_admission)
            results.append(_cpu_routing_outputs(snap))
    assert results[0] == results[1] and constructor_calls == []


@pytest.mark.parametrize("answer_kind", ["falsey-list", "none", "global-missing"])
def test_cpu_one_probe_keeps_falsey_and_foreign_owner_returns(monkeypatch, answer_kind):
    from cisco_toolkit import ui_projection as uip

    owner, results, counts = uip.carriage_role_rows, [], []

    class FalseyRows(list):
        def __bool__(self):
            return False

    for enabled in (False, True):
        snap, calls, delegated = _cpu_routing_subject(), [], []

        def query(record, interface, vid, *, index=None):
            genuine = owner(record, interface, vid, index=index)
            calls.append((record, interface, vid, index))
            delegated.append(genuine)
            if answer_kind == "none":
                return None
            if answer_kind == "global-missing":
                return uip._MISSING
            return FalseyRows(genuine)

        with monkeypatch.context() as patch:
            patch.setattr(uip, "_CARRIAGE_CPU_ROUTING_ENABLED", enabled)
            patch.setattr(uip, "carriage_role_rows", query)
            admission = uip.carriage_admission(snap)
        counts.append(len(calls))
        results.append(_cpu_routing_outputs(snap, admission=admission))
        if answer_kind != "falsey-list":
            assert admission.source["state"] == "unverified" and list(admission.gaps) == [0, 1, 2]
            # ORIGINAL typed routing asks logical PoN then the physical member BEFORE len(rows) can refuse.
            # Verify both real current domains and their exact order, not just an arbitrary two-call total.
            current = snap["stp_topology_observations"][A]
            assert len(calls) == 2 and all(record is current for record, _interface, _vid, _index in calls)
            assert [(interface, type(vid), vid) for _record, interface, vid, _index in calls] == [
                ("Po10", int, 10), (PORT, int, 10)]
            assert calls[0][3] is calls[1][3] and dict(calls[0][3]) == vc.carriage_role_index(current)
            assert len(delegated[0]) == 1 and delegated[0][0][1] is current["roles"][delegated[0][0][0]]
            assert type(delegated[1]) is list and delegated[1] == []
    assert results[0] == results[1] and counts[0] == counts[1]


def test_cpu_bool_query_then_plain_vid_keeps_original_typed_hold(monkeypatch):
    from cisco_toolkit import ui_projection as uip

    index_owner, query_owner, outputs, domains = uip.carriage_role_index, uip._carriage_role_query, [], []
    for enabled in (False, True):
        snap, changed, calls = _cpu_routing_subject(first_vid=1), [], []
        row = snap["vlan_carriage"]["rows"][0]

        def index(record):
            result = index_owner(record)
            if not changed:
                row["vlan"] = True  # Labelled callback mutation AFTER the genuine producer's strict integer row.
                changed.append(True)
            return result

        def query(record, interface, vid, *, index):
            result = query_owner(record, interface, vid, index=index)
            calls.append((record is snap["stp_topology_observations"][A], interface, type(vid)))
            row["vlan"] = 1
            return result

        with monkeypatch.context() as patch:
            patch.setattr(uip, "_CARRIAGE_CPU_ROUTING_ENABLED", enabled)
            patch.setattr(uip, "carriage_role_index", index)
            patch.setattr(uip, "_carriage_role_query", query)
            admission = uip.carriage_admission(snap)
        assert changed == [True] and calls[0][2] is bool and 0 in admission.gaps
        domains.append(calls)
        outputs.append(_cpu_routing_outputs(snap, admission=admission))
    assert outputs[0] == outputs[1] and domains[0] == domains[1]


def test_cpu_unsafe_host_after_first_token_permanently_stops_later_token_mints(monkeypatch):
    from cisco_toolkit import ui_projection as uip

    snap, minted, changed = _cpu_routing_subject(), [], []
    real_new, real_index, real_query = (uip._CarriageRoutingToken.__new__, uip.carriage_role_index,
                                      uip._carriage_role_query)
    end = snap["vlan_carriage"]["cables"][0]["members"][0]["a"]

    class ForeignHost(str):
        pass

    def token_new(cls, host, identity, observation, index):
        minted.append(host)
        return real_new(cls, host, identity, observation, index)

    def index(record):
        result = real_index(record)
        if not changed:
            end["host"] = ForeignHost(A)
            changed.append(True)
        return result

    def query(record, interface, vid, *, index):
        result = real_query(record, interface, vid, index=index)
        end["host"] = A
        return result

    before = deepcopy(snap)
    with monkeypatch.context() as patch:
        patch.setattr(uip._CarriageRoutingToken, "__new__", staticmethod(token_new))
        patch.setattr(uip, "carriage_role_index", index)
        patch.setattr(uip, "_carriage_role_query", query)
        actual = _cpu_routing_outputs(snap)
    assert changed == [True] and minted == [A] and snap == before
    with monkeypatch.context() as patch:
        patch.setattr(uip, "_CARRIAGE_ROUTING_TOKEN_ENABLED", False)
        assert _cpu_routing_outputs(snap) == actual


@pytest.mark.parametrize("damage", ["identity", "record", "index", "lookalike", "allocation-refusal"])
def test_cpu_token_constructor_outputs_cannot_bless_wrong_joins(monkeypatch, damage):
    from cisco_toolkit import ui_projection as uip

    snap, calls = _cpu_routing_subject(), []
    with monkeypatch.context() as original:
        original.setattr(uip, "_CARRIAGE_ROUTING_TOKEN_ENABLED", False)
        expected = _cpu_routing_outputs(snap)
    real_new = uip._CarriageRoutingToken.__new__

    def constructor(cls, host, identity, observation, index):
        calls.append(host)
        if damage == "allocation-refusal":
            raise MemoryError("optional token allocation refused")
        if damage == "lookalike":
            return (host, identity, observation, index)
        if damage == "identity":
            identity += 100
        elif damage == "record":
            observation = deepcopy(observation)
        else:
            index = dict(index)
        return real_new(cls, host, identity, observation, index)

    monkeypatch.setattr(uip._CarriageRoutingToken, "__new__", staticmethod(constructor))
    assert _cpu_routing_outputs(snap) == expected and calls


@pytest.mark.parametrize("damage", ["none", "new-role", "error", "logical-alias", "source-port", "beside"])
def test_caller_loop_preserves_complete_current_cpu_outputs(monkeypatch, damage):
    from cisco_toolkit import ui_projection as uip

    snap = _cpu_routing_subject()
    if damage == "new-role":
        snap["stp_topology_observations"][B] = _stp({30: [("Po10", "Desg", "FWD")]})
    elif damage == "error":
        snap["stp_topology_observations"][B] = produce_stp_topology_observation(
            "", "", state_capture_state="error", detail_capture_state="error")
    elif damage == "logical-alias":
        snap["interfaces"][B]["Po010"] = {**snap["interfaces"][B]["Po10"], "port": "Po010"}
    elif damage == "source-port":
        snap["interfaces"][B]["Po10"]["port"] = "Po99"
    elif damage == "beside":
        snap["stp_topology_observations"][B] = _stp(
            {10: [("Po10", "Altn", "BLK"), (PORT, "Desg", "FWD")]})
    before, outputs = deepcopy(snap), []
    for enabled in (False, True):
        with monkeypatch.context() as patch:
            patch.setattr(uip, "_CARRIAGE_CPU_ROUTING_ENABLED", True)
            patch.setattr(uip, "_CARRIAGE_ROUTING_TOKEN_ENABLED", True)
            patch.setattr(uip, "_CARRIAGE_LOOP_DISPATCH_ENABLED", enabled)
            outputs.append(_cpu_routing_outputs(snap))
    assert outputs[0] == outputs[1] and snap == before


@pytest.mark.parametrize("shape", ["foreign-enum", "collision", "foreign-signal", "missing-signal"])
def test_caller_loop_keeps_original_enum_construction_and_foreign_probe_effects(monkeypatch, shape):
    from cisco_toolkit import ui_projection as uip

    enum_owner, decode_owner, traces, outputs, trace = uip.carriage_end_char, uip.decode_carriage_end, [], [], []

    class ForeignText(str):
        def __hash__(self):
            trace.append(("hash", str(self)))
            return str.__hash__(self)

        def __eq__(self, other):
            trace.append(("eq", str(self), type(other)))
            return str.__eq__(self, other)

        def __bool__(self):
            raise AssertionError("extra foreign enum/signal truth evaluation")

    def enum(name, *args, **kwargs):
        value = enum_owner(name, *args, **kwargs)
        trace.append(("enum", name))
        if shape == "foreign-enum" and name == "forwarding":
            return ForeignText(value)
        return enum_owner("forwarding") if shape == "collision" and name == "allowed" else value

    def decode(value):
        result = decode_owner(value)
        trace.append(("decode", str(value)))
        if shape == "missing-signal":
            result = {key: field for key, field in result.items() if key != "signal"}
        elif shape == "foreign-signal" and type(result.get("signal")) is str:
            result = {**result, "signal": ForeignText(result["signal"])}
        return result

    for enabled in (False, True):
        snap, trace = _cpu_routing_subject(), []
        with monkeypatch.context() as patch:
            patch.setattr(uip, "_CARRIAGE_LOOP_DISPATCH_ENABLED", enabled)
            patch.setattr(uip, "carriage_end_char", enum)
            patch.setattr(uip, "decode_carriage_end", decode)
            admission = uip.carriage_admission(snap)
        traces.append(tuple(trace))
        outputs.append(_cpu_routing_outputs(snap, admission=admission))
        if shape == "missing-signal":
            assert admission.source["state"] == "unverified" and list(admission.gaps) == [0, 1, 2]
    assert traces[0] == traces[1] and outputs[0] == outputs[1]
    assert [event[1] for event in traces[0] if event[0] == "enum"] == ["forwarding", "blocked", "allowed", "excluded"]


@pytest.mark.parametrize("refuse", [False, True])
def test_caller_loop_foreign_current_codes_keep_index_hash_and_error_order(monkeypatch, refuse):
    from cisco_toolkit import ui_projection as uip

    binding_owner, query_owner, traces, outputs, trace = uip.carriage_cable_binding, uip._carriage_role_query, [], [], []

    class ForeignChar(str):
        def __hash__(self):
            trace.append(("hash", str(self)))
            return str.__hash__(self)

        def __eq__(self, other):
            trace.append(("eq", str(self)))
            return str.__eq__(self, other)

    class CurrentCodes(str):
        def __getitem__(self, index):
            trace.append(("index", index))
            if refuse and index == 3:
                raise RuntimeError("current next-end index refusal")
            return ForeignChar(str.__getitem__(self, index))

    for enabled in (False, True):
        snap, trace, installed = _cpu_routing_subject(), [], []

        def binding(*args, **kwargs):
            result = binding_owner(*args, **kwargs)
            if not installed:
                for row in snap["vlan_carriage"]["rows"]:
                    row["codes"] = CurrentCodes(row["codes"])
                installed.append(True)  # AFTER genuine closed-section admission/selector joins.
            return result

        def query(record, interface, vid, *, index):
            trace.append(("query", interface, vid))
            return query_owner(record, interface, vid, index=index)

        with monkeypatch.context() as patch:
            patch.setattr(uip, "_CARRIAGE_LOOP_DISPATCH_ENABLED", enabled)
            patch.setattr(uip, "carriage_cable_binding", binding)
            patch.setattr(uip, "_carriage_role_query", query)
            if refuse:
                with pytest.raises(RuntimeError) as raised:
                    uip.carriage_admission(snap)
                result, admission = (type(raised.value), raised.value.args), None
            else:
                admission, result = uip.carriage_admission(snap), None
        traces.append(tuple(trace))
        for row in snap["vlan_carriage"]["rows"]:
            row["codes"] = str(row["codes"])
        outputs.append(result if admission is None else _cpu_routing_outputs(snap, admission=admission))
        assert installed == [True]
        if refuse:
            assert traces[-1][-1] == ("index", 3)
            assert [(event[1], event[2]) for event in traces[-1] if event[0] == "query"] == [("Po10", 10), (PORT, 10)]
    assert traces[0] == traces[1] and outputs[0] == outputs[1]


@pytest.mark.parametrize("mutate_vid", [False, True])
def test_caller_loop_flip_compatibility_truth_keeps_late_current_signal_and_vid(monkeypatch, mutate_vid):
    from cisco_toolkit import ui_projection as uip

    binding_owner, query_owner, compat_owner, matches_owner = (uip.carriage_cable_binding, uip._carriage_role_query,
                                                               uip.carriage_role_compatible, uip.carriage_allowance_matches)
    traces, outputs, trace, snap = [], [], [], None

    class CurrentRow(dict):
        def __getitem__(self, name):
            result = dict.__getitem__(self, name)
            if name == "vlan":
                trace.append(("vid", result))
            return result

    class CurrentRole(dict):
        def __getitem__(self, name):
            result = dict.__getitem__(self, name)
            if name == "state":
                trace.append(("state", result))
            return result

    class FlipTruth:
        def __init__(self):
            self.count = 0

        def __bool__(self):
            self.count += 1
            value = self.count % 2 == 0
            trace.append(("bool", self.count, value))
            if mutate_vid and value:
                snap["vlan_carriage"]["rows"][0]["vlan"] = 30
            return value

    for enabled in (False, True):
        snap, trace = _cpu_routing_subject(), []
        saved_vlans = [row["vlan"] for row in snap["vlan_carriage"]["rows"]]

        def binding(*args, **kwargs):
            result = binding_owner(*args, **kwargs)
            snap["vlan_carriage"]["rows"] = [CurrentRow(row) for row in snap["vlan_carriage"]["rows"]]
            return result

        def query(record, interface, vid, *, index):
            rows = query_owner(record, interface, vid, index=index)
            if record is snap["stp_topology_observations"][B]:
                for position, row in rows:
                    if type(row) is dict:
                        record["roles"][position] = CurrentRole(row)
                rows = [(position, record["roles"][position]) for position, _row in rows]
            return rows

        def compatibility(row):
            valid = compat_owner(dict(row))  # Genuine values through the REAL owner before the declared foreign return.
            if any(row is current for current in snap["stp_topology_observations"][B]["roles"]):
                assert valid is True
                trace.append(("compat", dict.__getitem__(row, "state")))
                return FlipTruth()
            return valid

        def matches(admission, vid, signal):
            trace.append(("helper", vid, signal))
            return matches_owner(admission, vid, signal)

        with monkeypatch.context() as patch:
            patch.setattr(uip, "_CARRIAGE_LOOP_DISPATCH_ENABLED", enabled)
            patch.setattr(uip, "carriage_cable_binding", binding)
            patch.setattr(uip, "_carriage_role_query", query)
            patch.setattr(uip, "carriage_role_compatible", compatibility)
            patch.setattr(uip, "carriage_allowance_matches", matches)
            admission = uip.carriage_admission(snap)
        traces.append(tuple(trace))
        for row, vid in zip(snap["vlan_carriage"]["rows"], saved_vlans):
            row["vlan"] = vid
        for record in snap["stp_topology_observations"].values():
            record["roles"] = [dict(row) for row in record["roles"]]
        outputs.append(_cpu_routing_outputs(snap, admission=admission))
        first = next(i for i, event in enumerate(trace) if event == ("compat", "blocked"))
        assert trace[first + 1:first + 3] == [("bool", 1, False), ("bool", 2, True)]
        helper = next(i for i in range(first + 3, len(trace)) if trace[i][0] == "helper")
        assert trace[helper] == ("helper", 30 if mutate_vid else 10, "blocked")
        assert any(event == ("vid", 30 if mutate_vid else 10) for event in trace[first + 3:helper])
        assert not any(event[0] == "state" for event in trace[first:helper])
        assert ("helper", 10, "forwarding") in trace[:first]  # Prior-end DIFFERENT signal cannot leak.
    assert traces[0] == traces[1] and outputs[0] == outputs[1]


def test_caller_loop_private_plan_presence_never_adds_truth_or_property_reads(monkeypatch):
    from cisco_toolkit import ui_projection as uip

    trace, traces, outputs = [], [], []

    class ObservedPlan(uip._CarriageRoutingPlan):
        def __bool__(self):
            raise AssertionError("plan presence evaluated foreign truth")

        def __getattribute__(self, name):
            if name in ("host", "observation", "index"):
                trace.append(name)
            return super().__getattribute__(name)

    for enabled in (False, True):
        trace = []
        with monkeypatch.context() as patch:
            patch.setattr(uip, "_CARRIAGE_LOOP_DISPATCH_ENABLED", enabled)
            patch.setattr(uip, "_carriage_routing_plan", ObservedPlan)
            outputs.append(_cpu_routing_outputs(_cpu_routing_subject()))
        traces.append(tuple(trace))
    assert traces[0] == traces[1] and outputs[0] == outputs[1] and traces[0]


def test_caller_loop_foreign_static_key_retains_missing_configured_error_at_late_helper(monkeypatch):
    from cisco_toolkit import ui_projection as uip

    binding_owner, query_owner, outputs, traces, trace = uip.carriage_cable_binding, uip._carriage_role_query, [], [], []

    for enabled in (False, True):
        snap, trace, changed = _cpu_routing_subject(), [], []
        member = snap["vlan_carriage"]["cables"][0]["members"][0]

        class ForeignIndex(int):
            def __hash__(self):
                trace.append(("hash-index", len(trace)))
                member["index"] = 0
                # First configured write differs; static write and later plain position retain real index0.
                return 1000000 if len([event for event in trace if event[0] == "hash-index"]) == 1 else int.__hash__(self)

        def binding(*args, **kwargs):
            result = binding_owner(*args, **kwargs)
            if not changed:
                member["index"] = ForeignIndex(0)
                changed.append(True)
            return result

        def query(record, interface, vid, *, index):
            trace.append(("query", interface, vid))
            return query_owner(record, interface, vid, index=index)

        with monkeypatch.context() as patch:
            patch.setattr(uip, "_CARRIAGE_LOOP_DISPATCH_ENABLED", enabled)
            patch.setattr(uip, "carriage_cable_binding", binding)
            patch.setattr(uip, "_carriage_role_query", query)
            admission = uip.carriage_admission(snap)
        traces.append(tuple(trace))
        assert changed == [True] and admission.source["state"] == "unverified"
        assert list(admission.gaps) == [0, 1, 2]
        assert [(event[1], event[2]) for event in trace if event[0] == "query"] == [("Po10", 10), (PORT, 10)]
        outputs.append(_cpu_routing_outputs(snap, admission=admission))
    assert traces[0] == traces[1] and outputs[0] == outputs[1]


@pytest.mark.parametrize("shape", ["list", "foreign-iterable"])
def test_caller_loop_gap_extension_fallback_preserves_real_witness_order_and_hooks(monkeypatch, shape):
    from cisco_toolkit import ui_projection as uip

    snap = _cpu_routing_subject()
    snap["interfaces"][B]["Po10"]["port"] = "Po99"
    gaps = list(uip.carriage_admission(snap).gaps[0])
    assert gaps  # Actual current source contradiction supplies the witnesses, not a copied gap algorithm.
    trace, traces, outputs = [], [], []

    class ForeignGaps:
        def __iter__(self):
            trace.append("iter")
            return iter(gaps)

        def __len__(self):
            trace.append("len")
            return len(gaps)

        def __bool__(self):
            raise AssertionError("extra gap truth hook")

    for use_fallback in (False, True):
        trace, found = [], []
        values = gaps if shape == "list" else ForeignGaps()
        if use_fallback:
            uip._carriage_extend_gap_fallback(found, values)
        else:
            found.extend(values)
        traces.append(tuple(trace))
        outputs.append(found)
    assert traces[0] == traces[1] and outputs[0] == outputs[1] == gaps
