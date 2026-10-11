"""G14 v2 size and latency budgets for stored VLAN carriage on a synthetic 300-device fleet.

The fleet is built through the real producers from synthetic capture text: build.build_interfaces (the trunk
parser and its build.py assignments, the etherchannel and CDP joins), compute_cable_map and the typed STP producer.
300 devices, 200 VLAN rows, 1,500 cables: 600 assessed (150 of them two-member bundles) and 900 edge cables to
unscanned access points. Bytes are exact everywhere; the millisecond ceilings apply on hosted Linux Python 3.12,
where the first hosted run is a finding. Every measurement is printed as one ``VLAN-CARRIAGE-BUDGET`` JSON line.
"""
from copy import deepcopy
from dataclasses import asdict
import gc
import json
import os
import sys
import time

import pytest

from cisco_toolkit import build
from cisco_toolkit import ui_projection as uip
from cisco_toolkit.analyze import compute_cable_map
from cisco_toolkit.stp_topology import produce_stp_topology_observation
from cisco_toolkit.vlan_carriage import compute_vlan_carriage, validate_vlan_carriage

import synthetic_fixtures as fx

N_DEVICES, N_EDGES, N_VLANS, N_STP_VLANS = 300, 3, 200, 100
VLANS = list(range(2, 2 + N_VLANS))


def _timed_leg():
    """The millisecond ceilings are hosted Linux Python 3.12 figures, never a coverage-traced or other leg."""
    coverage = sys.modules.get("coverage")
    traced = sys.gettrace() is not None or (
        coverage is not None and getattr(getattr(coverage, "Coverage", None), "current", lambda: None)() is not None)
    return sys.platform.startswith("linux") and sys.version_info[:2] == (3, 12) and not traced


BUDGET = {"section_bytes": 6_000_000, "section_growth_v100_v200": 600_000, "summary_bytes": 4_096,
          "inventory_growth_bytes": 1_000_000, "compute_ms": 3_000, "validate_ms": 1_500,
          "document_growth_ms": 2_000, "page_ms": 300, "page_bytes": 3_000_000}


def _natural_gc_counters():
    """Observe natural collections only; telemetry refusal cannot change an original call."""
    try:
        counts = gc.get_count()
        collections = tuple(item["collections"] for item in gc.get_stats())
        if (type(counts) is tuple and len(counts) == len(collections) == 3
                and all(type(value) is int for value in (*counts, *collections))):
            return {"counts": counts, "collections": collections}
    except Exception:
        pass
    return None


def _copy_shape(args):
    # Only classify known exact dictionaries; never inspect caller attributes or values.
    if not args or type(args[0]) is not dict:
        return "other"
    value = args[0]
    if len(value) > 64:
        return "wide_mapping"
    if not all(type(key) is str for key in value):
        return "non_plain_keys"
    if "carriage" in value and "engine" in value:
        return "carriage_document"
    if "inventory" in value and "engine" in value:
        return "projection_document"
    return "plain_mapping"


def _budget_trace(name, original, current_phase, stages, copies):
    """One original call inside the unchanged outer timer, with bounded best-effort metadata."""
    def call(*args, **kwargs):
        phase = current_phase()
        if phase is None:
            return original(*args, **kwargs)
        started = time.perf_counter()
        before = _natural_gc_counters() if name == "owned_copy" else None
        try:
            return original(*args, **kwargs)
        finally:
            after = _natural_gc_counters() if name == "owned_copy" else None
            elapsed = 1000 * (time.perf_counter() - started)
            try:
                stage = stages.setdefault(phase, {}).setdefault(name, {"count": 0, "ms": 0.0})
                stage["count"] += 1
                stage["ms"] += elapsed
                if name == "owned_copy" and len(copies) < 32:
                    copies.append({"phase": phase, "shape": _copy_shape(args), "ms": round(elapsed, 1),
                                   "gc_before": before, "gc_after": after})
            except Exception:
                pass  # A diagnostic failure never replaces the original return or exception.
    return call


def test_copy_diagnostic_observes_natural_gc_without_replacing_the_copy(monkeypatch):
    calls = []
    stages, copies = {}, []
    source = {"engine": {}, "carriage": {"items": [True, None]}}

    def original(value):
        calls.append(value)
        return deepcopy(value)

    def forbidden(*_args, **_kwargs):
        pytest.fail("Diagnostic changed collection policy")

    for name in ("collect", "disable", "enable", "freeze", "unfreeze", "set_threshold"):
        monkeypatch.setattr(gc, name, forbidden)
    monkeypatch.setattr(gc, "get_count", lambda: (1, 2, 3))
    monkeypatch.setattr(gc, "get_stats", lambda: [{"collections": value} for value in (4, 5, 6)])
    traced = _budget_trace("owned_copy", original, lambda: "first_page", stages, copies)
    result = traced(source)
    assert calls == [source] and result == source and result is not source
    assert result["carriage"] is not source["carriage"]
    assert stages["first_page"]["owned_copy"]["count"] == 1
    assert len(copies) == 1 and copies[0]["shape"] == "carriage_document"
    assert copies[0]["gc_before"] == copies[0]["gc_after"] == {
        "counts": (1, 2, 3), "collections": (4, 5, 6)}


@pytest.mark.parametrize("original_failure", [False, True])
def test_copy_telemetry_failure_preserves_the_original_result_or_exception(monkeypatch, original_failure):
    calls = []

    def unavailable():
        raise RuntimeError("GC telemetry unavailable")

    def original(value):
        calls.append(value)
        if original_failure:
            raise ValueError("Original copy refusal")
        return value

    class UnavailableRecords(list):
        def append(self, _value):
            raise RuntimeError("Record telemetry unavailable")

    monkeypatch.setattr(gc, "get_count", unavailable)
    traced = _budget_trace("owned_copy", original, lambda: "first_page", {}, UnavailableRecords())
    source = {"plain": True}
    if original_failure:
        with pytest.raises(ValueError, match="Original copy refusal"):
            traced(source)
    else:
        assert traced(source) is source
    assert calls == [source]


def test_copy_diagnostic_has_no_activity_outside_the_original_measurement(monkeypatch):
    def forbidden():
        pytest.fail("Inactive diagnostic read collector counters")

    monkeypatch.setattr(gc, "get_count", forbidden)
    monkeypatch.setattr(gc, "get_stats", forbidden)
    calls, stages, copies = [], {}, []
    traced = _budget_trace("owned_copy", lambda value: calls.append(value) or value,
                          lambda: None, stages, copies)
    marker = object()
    assert traced(marker) is marker
    assert calls == [marker] and stages == {} and copies == []


def test_copy_diagnostic_does_not_probe_a_custom_collision_key(monkeypatch):
    hooks = []

    class CollisionKey:
        def __hash__(self):
            hooks.append("hash")
            return hash("carriage")

        def __eq__(self, _other):
            hooks.append("equality")
            raise AssertionError("Metadata probed a custom key")

        def __deepcopy__(self, _memo):
            return self

    key = CollisionKey()
    source = {key: True}
    hooks.clear()
    expected = deepcopy(source)
    original_hooks = list(hooks)
    hooks.clear()
    calls, stages, copies = [], {}, []

    def original(value):
        calls.append(value)
        return deepcopy(value)

    monkeypatch.setattr(gc, "get_count", lambda: (0, 0, 0))
    monkeypatch.setattr(gc, "get_stats", lambda: [{"collections": 0}] * 3)
    result = _budget_trace("owned_copy", original, lambda: "first_page", stages, copies)(source)
    assert calls == [source] and hooks == original_hooks == ["hash"]
    assert list(result) == list(expected) == [key]
    assert copies[0]["shape"] == "non_plain_keys"
    assert stages["first_page"]["owned_copy"]["count"] == 1


def _host(i):
    return f"sw{i % N_DEVICES:03d}"


def _links(i):
    """(local port, peer host, peer port, channel) of device i: a bundle or a single trunk to i+1 and from i-1,
    single trunks to i+2 and from i-2."""
    rows = []
    if i % 2 == 0:
        rows += [("Gi1/0/1", _host(i + 1), "Gi1/0/3", "Po1"), ("Gi1/0/2", _host(i + 1), "Gi1/0/4", "Po1")]
    else:
        rows += [("Gi1/0/1", _host(i + 1), "Gi1/0/3", "")]
    if (i - 1) % 2 == 0:
        rows += [("Gi1/0/3", _host(i - 1), "Gi1/0/1", "Po2"), ("Gi1/0/4", _host(i - 1), "Gi1/0/2", "Po2")]
    else:
        rows += [("Gi1/0/3", _host(i - 1), "Gi1/0/1", "")]
    return rows + [("Gi1/0/5", _host(i + 2), "Gi1/0/6", ""), ("Gi1/0/6", _host(i - 2), "Gi1/0/5", "")]


def _logical(i):
    names = []
    for local, _peer, _remote, channel in _links(i):
        if (channel or local) not in names:
            names.append(channel or local)
    return names


def _captures(i):
    names = _logical(i)
    # Two allowance shapes, so VLANs above 120 resolve to forwarding on some trunks and not_carried on others.
    allowed = {name: "1-4094" if (i + int(name[-1])) % 3 else "2-120" for name in names}
    trunk = ("Port        Mode             Encapsulation  Status        Native vlan\n"
             + "".join(f"{name:<11} on               802.1q         trunking      1\n" for name in names)
             + "\nPort        Vlans allowed on trunk\n" + "".join(f"{name:<11} {allowed[name]}\n" for name in names))
    groups = {}
    for local, _peer, _remote, channel in _links(i):
        if channel:
            groups.setdefault(channel, []).append(local)
    etherchannel = "Group  Port-channel  Protocol    Ports\n------+-------------+-----------+--------------\n" + "".join(
        f"{channel[2:]:<6} {channel}(SU)         LACP      " + "    ".join(m + "(P)" for m in members) + "\n"
        for channel, members in groups.items())
    neighbors = [(local, peer, remote, "cisco WS-C3850-24T") for local, peer, remote, _c in _links(i)]
    neighbors += [(f"Gi1/0/{10 + k}", f"AP-{i:03d}-{k}", "Gi0", "cisco AIR-AP2802I") for k in range(N_EDGES)]
    cdp = "".join(f"-------------------------\nDevice ID: {peer}\nEntry address(es):\n  IP address: 192.0.2.1\n"
                  f"Platform: {platform},  Capabilities: Router Switch\n"
                  f"Interface: {local},  Port ID (outgoing port): {remote}\nHoldtime : 150 sec\n"
                  for local, peer, remote, platform in neighbors)
    return {"show interfaces trunk": trunk, "show etherchannel summary": etherchannel if groups else "",
            "show cdp neighbors detail": cdp}


def _observation(i):
    body, detail = [], []
    for vid in VLANS[:N_STP_VLANS]:
        body.append(f"VLAN{vid:04d}\n  Root ID Priority 32778\n          Address aaaa.0001.0001\n"
                    "          This bridge is the root\n  Bridge ID Priority 32778\n          Address aaaa.0001.0001\n"
                    "Interface Role Sts Cost Prio.Nbr Type\n---------------- ---- --- --------- -------- -------\n"
                    + "".join(f"{name} {'Altn BLK' if (i + vid + n) % 7 == 0 else 'Desg FWD'} 4 128.{n + 1} P2p\n"
                              for n, name in enumerate(_logical(i))) + "\n")
        detail.append(f"VLAN{vid:04d}\n  Number of topology changes 0 last change occurred 00:00:00 ago\n")
    return produce_stp_topology_observation("".join(body), "".join(detail),
                                            state_capture_state="usable", detail_capture_state="usable")


@pytest.fixture(scope="module")
def fleet(tmp_path_factory):
    root = tmp_path_factory.mktemp("carriage-fleet")
    interfaces = {}
    for i in range(N_DEVICES):
        directory = root / _host(i)
        directory.mkdir()
        c2f = {}
        for cmd, text in _captures(i).items():
            if text:
                path = directory / fx.cmd_filename(cmd)
                path.write_text(text, encoding="utf-8", newline="\n")
                c2f[cmd] = str(path)
        interfaces[_host(i)] = build.build_interfaces(_host(i), "ios", c2f)
    cables = compute_cable_map(interfaces)
    observations = {_host(i): _observation(i) for i in range(N_DEVICES)}
    stored = {host: {port: asdict(record) for port, record in records.items()} for host, records in interfaces.items()}
    rows = [{"vlan": vid} for vid in VLANS]
    return {"interfaces": stored, "cable_map": cables, "stp_topology_observations": observations, "vlan_cutover": rows}


def _bytes(value):
    return len(json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


def _timed(call):
    start = time.perf_counter()
    result = call()
    return result, round(1000 * (time.perf_counter() - start), 1)


def _report(capsys, kind, measured):
    with capsys.disabled():
        print("VLAN-CARRIAGE-BUDGET " + json.dumps({"kind": kind, "timed": _timed_leg(), **measured}, sort_keys=True))


def _zeroed(summary):
    out = deepcopy(summary)
    for name in uip.CARRIAGE_SUMMARY_COUNTS:
        if out[name]["state"] == "published":
            out[name]["value"] = 0
    return out


def test_the_stored_section_and_its_summary_stay_within_their_size_and_latency_budgets(fleet, capsys):
    cables = fleet["cable_map"]["cables"]
    assert len(fleet["interfaces"]) == N_DEVICES and len(cables) == 1_500
    assessed = [c for c in cables if c["b"] in fleet["interfaces"] and c["a"] in fleet["interfaces"]]
    assert len(assessed) == 600 and sum(1 for c in assessed if len(c["members"]) == 2) == 150
    args = (fleet["cable_map"], fleet["interfaces"], fleet["stp_topology_observations"])
    section, compute_ms = _timed(lambda: compute_vlan_carriage(*args, fleet["vlan_cutover"]))
    verdict, validate_ms = _timed(lambda: validate_vlan_carriage(section))
    half = compute_vlan_carriage(*args, fleet["vlan_cutover"][:N_VLANS // 2])
    assert verdict == (True, "ok") and validate_vlan_carriage(half) == (True, "ok")
    cov = section["coverage"]
    assert (cov["vlan_rows"], cov["cable_rows"], cov["assessed_cables"], cov["edge_cables"]) == (200, 1_500, 600, 900)
    assert cov["requested_pairs"] == cov["emitted_pairs"] == 200 * 600
    snap = {**fleet, "vlan_carriage": section}
    with_carriage = uip.project_inventory(snap)
    without = uip.project_inventory({key: value for key, value in snap.items() if key != "vlan_carriage"})
    summaries = [row["selections"]["carriage"] for row in with_carriage["vlans"]["rows"]["items"]]
    # C' = 300: the same fleet's stored cable map with every other assessed cable removed (labelled reduction).
    kept, every = {id(c) for c in assessed[::2]}, {id(c) for c in assessed}
    smaller = {**fleet["cable_map"], "cables": [c for c in cables if id(c) in kept or id(c) not in every]}
    small_section = compute_vlan_carriage(smaller, fleet["interfaces"], fleet["stp_topology_observations"],
                                          fleet["vlan_cutover"])
    small = uip.project_inventory({**fleet, "cable_map": smaller, "vlan_carriage": small_section})
    small_summary = small["vlans"]["rows"]["items"][0]["selections"]["carriage"]
    assert small_section["coverage"]["assessed_cables"] == 300
    measured = {
        "section_bytes": _bytes(section), "section_bytes_v100": _bytes(half),
        "section_growth_v100_v200": _bytes(section) - _bytes(half),
        "summary_bytes_max": max(_bytes(s) for s in summaries), "summary_bytes_c300": _bytes(small_summary),
        "summary_bytes_c600": _bytes(summaries[0]),
        "inventory_bytes": _bytes(with_carriage), "inventory_bytes_without": _bytes(without),
        "inventory_growth_bytes": _bytes(with_carriage) - _bytes(without),
        "compute_ms": compute_ms, "validate_ms": validate_ms, "section_state": section["state"],
        "summary_states": sorted({s["state"] for s in summaries}),
    }
    _report(capsys, "engine", measured)
    assert measured["section_bytes"] <= BUDGET["section_bytes"]
    assert measured["section_growth_v100_v200"] <= BUDGET["section_growth_v100_v200"]
    assert measured["summary_bytes_max"] <= BUDGET["summary_bytes"]
    assert measured["summary_bytes_c300"] <= BUDGET["summary_bytes"]
    # O(1) summary: its shape and refs do not grow with the assessed cable count; only the counted numbers differ.
    assert _bytes(_zeroed(small_summary)) == _bytes(_zeroed(summaries[0]))
    assert small_summary["refs"] == summaries[0]["refs"]
    assert measured["inventory_growth_bytes"] <= BUDGET["inventory_growth_bytes"]
    if _timed_leg():
        assert measured["compute_ms"] <= BUDGET["compute_ms"]
        assert measured["validate_ms"] <= BUDGET["validate_ms"]


def test_the_first_document_and_one_full_page_stay_within_their_api_budgets(fleet, tmp_path, capsys, monkeypatch):
    pytest.importorskip("fastapi")
    from pathlib import Path
    webapp = str(Path(__file__).resolve().parents[1] / "webapp")
    if webapp not in sys.path:
        sys.path.insert(0, webapp)
    from backend import ui_projection_api as api
    from backend.app import create_app
    from cisco_toolkit import protocol_assurance as pa

    # Transparent hosted diagnostics: the unchanged outer timers and ceilings still decide. Times are inclusive
    # (admission includes gaps, validation includes schema fingerprinting), so these figures must not be summed.
    phase = None
    stages = {}
    copies = []

    def traced(name, original):
        return _budget_trace(name, original, lambda: phase, stages, copies)

    diagnostics = os.environ.get("GITHUB_ACTIONS") == "true" and _timed_leg()
    if diagnostics:
        for module, name, label in (
            (api.engine, "bind_ui_projection_snapshot", "snapshot_bind"),
            (api.engine, "ui_projection_carriage_admission", "carriage_admission"),
            (uip, "_carriage_gaps", "basis_gaps"),
            (api.engine, "ui_projection", "document_production"),
            (api.engine, "ui_projection_carriage", "page_production"),
            (uip, "bound_snapshot_source", "mutation_sensitive_identity"),
            (pa, "_matches_snapshot_content_proof", "identity_proof"),
            (pa, "_snapshot_identity_text", "identity_full_encoding"),
            (pa, "_snapshot_identity_binary", "identity_full_binary_encoding"),
            (pa, "canonical_sha256", "canonical_content_guard"),
            (uip, "carriage_observation_admission", "observation_owner_admission"),
            (uip, "_carriage_observation_key", "complete_observation_key"),
            (uip, "carriage_role_index", "role_owner_index"),
            (uip, "carriage_allowance_admission", "allowance_owner_admission"),
            (api, "deepcopy", "owned_copy"),
            (api, "_require_json_native", "json_native"),
            (api, "_schema_fingerprint", "schema_fingerprint"),
            (api, "_require_engine_source", "engine_source_guard"),
            (api, "_require_carriage_page", "page_metadata_guard"),
        ):
            monkeypatch.setattr(module, name, traced(label, getattr(module, name)))

        class TracedValidator:
            """Retain the complete original validator, schema and behavior; only its outer validate is timed."""
            def __init__(self, original, label):
                self.original = original
                self.validate = traced(label, original.validate)

            def __getattr__(self, name):
                return getattr(self.original, name)

        for name, label in (("_DOCUMENT_VALIDATOR", "document_validation"),
                            ("_CARRIAGE_VALIDATOR", "page_validation")):
            monkeypatch.setattr(api, name, TracedValidator(getattr(api, name), label))

    section = compute_vlan_carriage(fleet["cable_map"], fleet["interfaces"], fleet["stp_topology_observations"],
                                    fleet["vlan_cutover"])
    app = create_app(db_path=str(tmp_path / "budget.db"), scope_dist_dir=None)
    store = app.state.store
    campaign = store.create_campaign("Synthetic carriage budget")
    without_id = store.add_snapshot(campaign["id"], "without carriage", dict(fleet), {})["id"]
    with_id = store.add_snapshot(campaign["id"], "with carriage", {**fleet, "vlan_carriage": section}, {})["id"]
    warm_id = store.add_snapshot(campaign["id"], "warm-up", {"vlan_cutover": []}, {})["id"]
    cache = api._ProjectionCache()
    warm_raw, warm_binding = store.get_snapshot_blob(warm_id)
    cache.document(warm_raw, warm_binding["sha256"], None)  # first-use imports and code paths, outside the timing
    raw0, binding0 = store.get_snapshot_blob(without_id)
    raw1, binding1 = store.get_snapshot_blob(with_id)
    phase = "document_without"
    _document, without_ms = _timed(lambda: cache.document(raw0, binding0["sha256"], None))
    phase = "document_with"
    document, with_ms = _timed(lambda: cache.document(raw1, binding1["sha256"], None))

    def warm():
        response = api.carriage_page(cache, raw1, binding1, with_id, 0, 0, api.MAX_PAGE_SIZE)
        api._CARRIAGE_VALIDATOR.validate(response)
        api._require_carriage_page(response["payload"])
        return response

    phase = "first_page"
    first, first_page_ms = _timed(warm)
    phase = "page"
    response, page_ms = _timed(warm)
    phase = None
    assert response == first and response["payload"]["page"]["returned"] == api.MAX_PAGE_SIZE
    assert response["payload"]["summary"] == document["inventory"]["vlans"]["rows"]["items"][0]["selections"]["carriage"]
    measured = {"document_ms_without": without_ms, "document_ms_with": with_ms,
                "document_growth_ms": round(with_ms - without_ms, 1), "first_page_ms": first_page_ms,
                "page_ms": page_ms, "page_bytes": _bytes(response), "page_items": len(response["payload"]["page"]["items"])}
    _report(capsys, "api", measured)
    if diagnostics:
        with capsys.disabled():
            print("VLAN-CARRIAGE-STAGES " + json.dumps({
                "inclusive_not_additive": True,
                "document_native_domain_eligible": api._native_instance_allowed(document),
                "owned_copy_calls": copies,
                "bound_proof_present": {
                    key[-1]: type(getattr(entry.snapshot, "_bound_content_proof", None))
                    is pa._BoundSnapshotContentProof for key, entry in cache.entries.items()
                },
                "phases": {key: {name: {"count": value["count"], "ms": round(value["ms"], 1)}
                                 for name, value in sorted(stage.items())}
                           for key, stage in stages.items()},
            }, sort_keys=True))
    assert measured["page_bytes"] <= BUDGET["page_bytes"]
    if _timed_leg():
        assert measured["document_growth_ms"] <= BUDGET["document_growth_ms"]
        assert measured["page_ms"] <= BUDGET["page_ms"]
        assert measured["first_page_ms"] <= BUDGET["page_ms"]
