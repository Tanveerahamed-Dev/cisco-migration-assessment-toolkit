from __future__ import annotations

import copy
import hashlib
import json
import pickle
from pathlib import Path

import pytest

import COLLECT_PARSE_V3_23_0 as pipeline
from cisco_toolkit import input_custody
from cisco_toolkit.build import build_multichassis_lag_typed_observation
from cisco_toolkit.multichassis_lag import (
    compute_multichassis_lag_domain_baseline,
    produce_multichassis_lag_typed_observation,
    validate_multichassis_lag_domain_baseline,
)
from cisco_toolkit.parse import (
    parse_arista_lacp_peer,
    parse_arista_mlag_interfaces,
    parse_nxos_lacp_neighbors,
    parse_vpc_role,
)


def _nxos_vpc(
        *, domain: str = "10", peer_status: str = "peer adjacency formed ok",
        keepalive: str = "peer is alive", include_leg: bool = True) -> bytes:
    leg = "20   Po20   up   success   success   10-20\n" if include_leg else ""
    count = "1" if include_leg else "0"
    return f"""vPC domain id                     : {domain}
Peer status                       : {peer_status}
vPC keep-alive status             : {keepalive}
Configuration consistency status : success
vPC role                          : primary
Number of vPCs configured         : {count}

vPC Peer-link status
id   Port   Status Active vlans
1    Po100  up     1-4094

vPC status
id   Port   Status Consistency Reason   Active vlans
{leg}""".encode()


def _nxos_role(local_mac: str, peer_mac: str) -> bytes:
    return f"""vPC Role status
----------------------------------------------------
vPC role                        : primary
Dual Active Detection Status    : 0
vPC system-mac                  : 00:00:5e:00:01:01
vPC local system-mac            : {local_mac}
vPC local role-priority         : 32667
vPC peer system-mac             : {peer_mac}
vPC peer role-priority          : 32667
""".encode()


def _nxos_lacp(*, partner_mac: str = "00-11-22-33-44-55", key: str = "0x2a") -> bytes:
    return f"""switch# show lacp neighbor
Flags:  S - Device is sending Slow LACPDUs F - Device is sending Fast LACPDUs
        A - Device is in Active mode       P - Device is in Passive mode
port-channel20 neighbors
Partner's information
            Partner                Partner                     Partner
Port        System ID              Port Number     Age         Flags
Eth1/31     32768,{partner_mac}0x11f           24965       SA

            LACP Partner           Partner                     Partner
            Port Priority          Oper Key                    Port State
            32768                  {key}                       0x3d
""".encode()


def _nxos_commands(
        local_mac: str, peer_mac: str, *, include_role: bool = True,
        include_lacp: bool = True, include_orphan_ports: bool = True,
        include_running_config: bool = True, **vpc_kwargs) -> dict[str, bytes]:
    commands = {"show vpc": _nxos_vpc(**vpc_kwargs)}
    if include_role:
        commands["show vpc role"] = _nxos_role(local_mac, peer_mac)
    if include_lacp:
        commands["show lacp neighbor"] = _nxos_lacp()
    if include_orphan_ports:
        commands["show vpc orphan-ports"] = (
            b"VLAN           Orphan Ports\n"
            b"-------        -------------------------\n"
        )
    if include_running_config:
        commands["show running-config"] = (
            b"hostname leaf\ninterface Eth1/1\n description test\nend\n"
        )
    return commands


def _nxos_pair(mode: str = "live") -> dict:
    a = produce_multichassis_lag_typed_observation(
        "leaf-a", vendor="cisco", platform="nxos", collection_mode=mode,
        command_bytes=_nxos_commands("00:00:00:00:00:0a", "00:00:00:00:00:0b"),
    )
    b = produce_multichassis_lag_typed_observation(
        "leaf-b", vendor="cisco", platform="nxos", collection_mode=mode,
        command_bytes=_nxos_commands("00:00:00:00:00:0b", "00:00:00:00:00:0a"),
    )
    assert a is not None and b is not None
    return {"observations": [a, b]}


def _eos_commands() -> dict[str, bytes]:
    return {
        "show mlag": b"""{
  "domainId": "MLAG-DC1",
  "peerAddress": "10.255.0.8",
  "peerLink": "Port-Channel1000",
  "state": "active",
  "negStatus": "connected",
  "peerLinkStatus": "up",
  "localIntfStatus": "up",
  "configSanity": "consistent",
  "systemId": "02:1c:73:00:13:19",
  "mlagPorts": {"Active-full": 1, "Active-partial": 0, "Inactive": 0, "Configured": 0}
}""",
        "show mlag interfaces detail": b"""                                local/remote
mlag       state local remote   oper   config          last change  changes
----------------------------------------------------------------------------
  20 active-full  Po20   Po20  up/up  ena/ena  6 days, 1:19:26 ago        5
""",
        "show lacp peer": b"""State: A = Active, P = Passive
             |                          Partner
Port Status  | Sys-id                  Port# State OperKey PortPri
----------------------------------------------------------------------------
Port Channel Port-Channel20*:
Et31 Bundled | 8000,00-11-22-33-44-55    31 ALGs+CD 0x002a 32768
""",
    }


def _write_commands(root: Path, commands: dict[str, bytes]) -> dict[str, str]:
    result = {}
    for index, (command, payload) in enumerate(commands.items()):
        path = root / f"capture-{index}.txt"
        path.write_bytes(payload)
        result[command] = str(path)
    return result


def _bind_paths(cmd_to_file: dict[str, str]) -> None:
    bindings = []
    for command, raw_path in cmd_to_file.items():
        payload = Path(raw_path).read_bytes()
        bindings.append({
            "path": raw_path,
            "name": command,
            "size": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        })
    input_custody.reset()
    input_custody.bind_files(bindings)


def test_real_shaped_parsers_project_only_explicit_identity_leaves() -> None:
    role = parse_vpc_role(
        _nxos_role("00:00:00:00:00:0a", "00:00:00:00:00:0b").decode())
    assert role == {
        "local_system_mac": "00:00:00:00:00:0a",
        "peer_system_mac": "00:00:00:00:00:0b",
        "dual_active_status": "0",
    }
    assert parse_nxos_lacp_neighbors(_nxos_lacp().decode()) == [{
        "port_channel": "Po20",
        "local_member": "Eth1/31",
        "partner_system_id": "00-11-22-33-44-55",
        "partner_oper_key": "0x2a",
    }]
    assert parse_arista_mlag_interfaces(
        _eos_commands()["show mlag interfaces detail"].decode())[0]["mlag_id"] == "20"
    assert parse_arista_lacp_peer(
        _eos_commands()["show lacp peer"].decode())[0]["partner_oper_key"] == "0x002a"


@pytest.mark.parametrize("mode", ["live", "offline"])
def test_nxos_real_raw_chain_can_reconcile_pair_and_attachment(mode: str) -> None:
    baseline = compute_multichassis_lag_domain_baseline(_nxos_pair(mode))

    assert validate_multichassis_lag_domain_baseline(
        baseline, require_current_run=True)["valid"] is True
    assert baseline["projection_custody"] == "current_run_source_bound"
    assert len(baseline["reciprocal_peer_pairs"]) == 1
    assert len(baseline["reconciled_attachments"]) == 1
    assert baseline["reconciled_attachments"][0]["health_state"] == "healthy"
    assert baseline["reconciled_attachments"][0]["lacp_partner_system_id"] == (
        "00:11:22:33:44:55")
    assert baseline["reconciled_attachments"][0]["lacp_partner_aggregation_id"] == "42"
    assert {
        row["local_identity"] for row in baseline["local_observations"]
    } == {"00:00:00:00:00:0a", "00:00:00:00:00:0b"}


def test_eos_offline_real_raw_chain_is_source_bound_but_local_only() -> None:
    observation = produce_multichassis_lag_typed_observation(
        "eos-a", vendor="arista", platform="eos", collection_mode="offline",
        command_bytes=_eos_commands(),
    )
    assert observation is not None
    baseline = compute_multichassis_lag_domain_baseline({"observations": [observation]})

    assert baseline["projection_custody"] == "current_run_source_bound"
    assert baseline["reciprocal_peer_pairs"] == []
    assert baseline["reconciled_attachments"] == []
    assert len(baseline["local_legs"]) == 1
    assert baseline["local_legs"][0]["health_state"] == "not_verified"
    local = baseline["local_observations"][0]
    assert local["local_identity"] == "" and local["peer_identity"] == ""
    assert local["health_state"] == "not_verified"
    assert {finding["code"] for finding in local["findings"]} >= {
        "local_identity_missing", "peer_identity_missing",
    }


def test_eos_offline_import_paths_reach_the_same_typed_local_leg(tmp_path: Path) -> None:
    cmd_to_file = _write_commands(tmp_path, _eos_commands())
    _bind_paths(cmd_to_file)
    observation = build_multichassis_lag_typed_observation(
        "eos-a", "ios", "offline", cmd_to_file)
    assert observation is not None

    baseline = compute_multichassis_lag_domain_baseline({"observations": [observation]})
    assert baseline["local_observations"][0]["platform"] == "eos"
    assert baseline["local_observations"][0]["source_receipt"]["source_bound"] is True
    assert len(baseline["local_legs"]) == 1
    assert baseline["reciprocal_peer_pairs"] == []


def test_receipt_strings_and_digests_cannot_self_authorize() -> None:
    raw = _nxos_pair()
    forged = {"observations": [copy.deepcopy(dict(row)) for row in raw["observations"]]}
    for row in forged["observations"]:
        row["source"]["projection_custody"] = "current_run_source_bound"
    baseline = compute_multichassis_lag_domain_baseline(forged)

    assert baseline["projection_custody"] == "embedded_unverified"
    assert all(not row["source_receipt"]["source_bound"] for row in baseline["local_observations"])
    assert validate_multichassis_lag_domain_baseline(
        baseline, require_current_run=True)["reason"] == "baseline_not_current_run_source_bound"

    mutated = _nxos_pair()
    mutated["observations"][0]["domain_id"] = "999"
    mutated_baseline = compute_multichassis_lag_domain_baseline(mutated)
    assert mutated_baseline["projection_custody"] == "embedded_unverified"

    authentic = _nxos_pair()["observations"][0]
    for clone in (
        copy.copy(authentic),
        copy.deepcopy(authentic),
        json.loads(json.dumps(authentic)),
        pickle.loads(pickle.dumps(authentic)),
    ):
        clone_baseline = compute_multichassis_lag_domain_baseline(
            {"observations": [clone]})
        assert clone_baseline["projection_custody"] == "embedded_unverified"


def test_domain_vpc_and_peer_ip_without_explicit_reciprocal_system_macs_do_not_pair() -> None:
    observations = []
    for switch in ("leaf-a", "leaf-b"):
        observation = produce_multichassis_lag_typed_observation(
            switch, vendor="cisco", platform="nxos", collection_mode="offline",
            command_bytes=_nxos_commands(
                "00:00:00:00:00:0a", "00:00:00:00:00:0b", include_role=False),
        )
        assert observation is not None
        observation["peer_address"] = "192.0.2.10"
        observations.append(observation)
    baseline = compute_multichassis_lag_domain_baseline({"observations": observations})

    assert baseline["reciprocal_peer_pairs"] == []
    assert baseline["reconciled_attachments"] == []
    assert {row["health_state"] for row in baseline["local_observations"]} == {"not_verified"}


def test_one_sided_peer_and_matching_vpc_without_lacp_identity_fail_closed() -> None:
    a = produce_multichassis_lag_typed_observation(
        "leaf-a", vendor="cisco", platform="nxos", collection_mode="live",
        command_bytes=_nxos_commands("00:00:00:00:00:0a", "00:00:00:00:00:0b"),
    )
    b = produce_multichassis_lag_typed_observation(
        "leaf-b", vendor="cisco", platform="nxos", collection_mode="live",
        command_bytes=_nxos_commands(
            "00:00:00:00:00:0b", "00:00:00:00:00:0c", include_lacp=False),
    )
    assert a is not None and b is not None
    one_sided = compute_multichassis_lag_domain_baseline({"observations": [a, b]})
    assert one_sided["reciprocal_peer_pairs"] == []
    assert one_sided["reconciled_attachments"] == []

    pair_without_lacp = []
    for switch, local, peer in (
        ("leaf-a", "00:00:00:00:00:0a", "00:00:00:00:00:0b"),
        ("leaf-b", "00:00:00:00:00:0b", "00:00:00:00:00:0a"),
    ):
        observation = produce_multichassis_lag_typed_observation(
            switch, vendor="cisco", platform="nxos", collection_mode="offline",
            command_bytes=_nxos_commands(local, peer, include_lacp=False),
        )
        assert observation is not None
        pair_without_lacp.append(observation)
    no_lacp = compute_multichassis_lag_domain_baseline(
        {"observations": pair_without_lacp})
    assert len(no_lacp["reciprocal_peer_pairs"]) == 1
    assert no_lacp["reconciled_attachments"] == []
    assert {row["health_state"] for row in no_lacp["local_legs"]} == {"not_verified"}


def test_not_formed_and_not_alive_are_closed_bad_states() -> None:
    observation = produce_multichassis_lag_typed_observation(
        "leaf-a", vendor="cisco", platform="nxos", collection_mode="live",
        command_bytes=_nxos_commands(
            "00:00:00:00:00:0a", "00:00:00:00:00:0b",
            peer_status="peer adjacency not formed", keepalive="peer is not alive"),
    )
    assert observation is not None
    baseline = compute_multichassis_lag_domain_baseline({"observations": [observation]})
    local = baseline["local_observations"][0]
    assert local["health_state"] == "degraded"
    assert {finding["code"] for finding in local["findings"]} >= {
        "peer_status_degraded", "keepalive_status_degraded",
    }


def test_build_reads_bound_exact_bytes_and_malformed_or_renamed_leaves_abstain(
        tmp_path: Path) -> None:
    cmd_to_file = _write_commands(
        tmp_path, _nxos_commands("00:00:00:00:00:0a", "00:00:00:00:00:0b"))
    _bind_paths(cmd_to_file)
    observation = build_multichassis_lag_typed_observation(
        "leaf-a", "nxos", "offline", cmd_to_file)
    assert observation is not None
    baseline = compute_multichassis_lag_domain_baseline({"observations": [observation]})
    assert baseline["local_observations"][0]["source_receipt"]["source_bound"] is True

    # Renaming the role command is not an alias and cannot fill either identity leaf.
    renamed = dict(cmd_to_file)
    renamed["show vpc roles"] = renamed.pop("show vpc role")
    observation = build_multichassis_lag_typed_observation(
        "leaf-a", "nxos", "offline", renamed)
    assert observation is not None
    baseline = compute_multichassis_lag_domain_baseline({"observations": [observation]})
    assert baseline["local_observations"][0]["health_state"] == "not_verified"
    assert baseline["reciprocal_peer_pairs"] == []

    malformed = _nxos_commands("00:00:00:00:00:0a", "00:00:00:00:00:0b")
    malformed["show vpc role"] = b"\xff\xfe\xfd"
    bad = produce_multichassis_lag_typed_observation(
        "leaf-a", vendor="cisco", platform="nxos", collection_mode="offline",
        command_bytes=malformed,
    )
    assert bad is not None
    bad_baseline = compute_multichassis_lag_domain_baseline({"observations": [bad]})
    assert bad_baseline["local_observations"][0]["health_state"] == "not_verified"


def test_bound_path_mutation_is_not_parsed_and_remains_in_the_custody_ledger(
        tmp_path: Path) -> None:
    cmd_to_file = _write_commands(
        tmp_path, _nxos_commands("00:00:00:00:00:0a", "00:00:00:00:00:0b"))
    _bind_paths(cmd_to_file)
    Path(cmd_to_file["show vpc role"]).write_bytes(
        _nxos_role("00:00:00:00:00:0a", "00:00:00:00:00:ff"))

    observation = build_multichassis_lag_typed_observation(
        "leaf-a", "nxos", "offline", cmd_to_file)
    assert observation is not None
    baseline = compute_multichassis_lag_domain_baseline({"observations": [observation]})
    local = baseline["local_observations"][0]

    assert local["local_identity"] == "" and local["peer_identity"] == ""
    assert local["health_state"] == "not_verified"
    assert local["source_receipt"]["capture_status"] == "incomplete"
    assert input_custody.failures() == [{
        "name": "show vpc role",
        "reason": (
            "BoundInputMutationError: bytes differ from the pre-analysis custody binding"
        ),
    }]


def test_declared_collection_manifests_do_not_infer_eos_live_support() -> None:
    assert {
        "show vpc", "show vpc role", "show lacp neighbor",
        "show vpc orphan-ports", "show running-config",
    } <= set(
        pipeline.COMMANDS_NXOS)
    assert {"show mlag", "show mlag interfaces detail", "show lacp peer"} <= set(
        pipeline.COMMANDS_ARISTA)
    assert "show mlag" not in pipeline.COMMANDS_NXOS
    assert "show lacp peer" not in pipeline.COMMANDS_NXOS
    assert produce_multichassis_lag_typed_observation(
        "eos-a", vendor="arista", platform="eos", collection_mode="live",
        command_bytes=_eos_commands(),
    ) is None
