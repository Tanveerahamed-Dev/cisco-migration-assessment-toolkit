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
import math
import os
import re
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


# The ceilings need the runner to themselves, so CI runs this module in its serial `unshared` pass
# (pytest.ini). The mark is unconditional: a mark that followed _timed_leg() would depend on when each
# process starts coverage tracing, and a module marked in one pass but not the other runs in neither.
pytestmark = pytest.mark.unshared


BUDGET = {"section_bytes": 6_000_000, "section_growth_v100_v200": 600_000, "summary_bytes": 4_096,
          "inventory_growth_bytes": 1_000_000, "compute_ms": 3_000, "validate_ms": 1_500,
          "document_growth_ms": 2_000, "page_ms": 300, "page_bytes": 3_000_000}


def _profile_need(condition, label):
    if not condition:
        raise AssertionError("Admission diagnostic: " + label)  # Never render a payload or a source identity.


def _profile_same(left, right):
    from types import MappingProxyType

    if type(left) is not type(right):
        return False
    kind = type(left)
    if kind in (dict, MappingProxyType):
        return _profile_same(tuple(left.items()), tuple(right.items()))
    if kind in (tuple, list):
        return len(left) == len(right) and all(_profile_same(a, b) for a, b in zip(left, right))
    if kind is float:
        return math.isfinite(left) and math.isfinite(right) and left.hex() == right.hex()
    return kind in (type(None), str, int, bool) and left == right


def _profile_admission_equal(snapshot, baseline, result):
    slots = ("source", "section", "failed", "gaps", "offsets", "observations")
    _profile_need(uip._CarriageAdmission.__slots__ == slots, "slot census")
    _profile_need(type(baseline) is type(result) is uip._CarriageAdmission and result is not baseline, "owner class")
    _profile_need(_profile_same(result.source, baseline.source), "complete source metadata")
    _profile_need(result.section is baseline.section, "section alias")
    if baseline.section is not None:
        _profile_need(baseline.section is snapshot.get("vlan_carriage"), "current section alias")
    _profile_need(_profile_same(result.failed, baseline.failed), "failure tuple")
    _profile_need(_profile_same(result.gaps, baseline.gaps), "ordered gaps")
    _profile_need(_profile_same(result.offsets, baseline.offsets), "offsets")
    _profile_need(type(result.observations) is type(baseline.observations), "observation mapping type")
    _profile_need(_profile_same(tuple(result.observations), tuple(baseline.observations)), "ordered host census")
    supplied = snapshot.get("stp_topology_observations")
    for host, pair in result.observations.items():
        original = baseline.observations[host]
        _profile_need(type(pair) is type(original) is tuple and len(pair) == len(original) == 2, "observation pair")
        record, index = pair
        _profile_need(record is original[0], "host observation alias")
        if record is not None:
            _profile_need(type(supplied) is dict and record is supplied.get(host), "current host record")
        _profile_need(_profile_same(index, original[1]), "complete ordered index")


def _profile_original_admission(snapshot, profiler):
    failed = False
    try:
        profiler.enable()
        return uip.carriage_admission(snapshot)  # ONE ordinary original call with fresh invocation-local maps.
    except BaseException:
        failed = True
        raise
    finally:
        try:
            profiler.disable()
        except BaseException:
            if not failed:
                raise  # Cleanup must not mask an original admission error; otherwise it is a real failure.


def _safe_profile_rows(stats, repo):
    _profile_need(type(stats) is dict, "stats mapping")
    prefix = str(repo).replace("\\", "/").rstrip("/") + "/"
    rows = []
    for key, value in stats.items():
        _profile_need(type(key) is tuple and len(key) == 3 and type(value) is tuple and len(value) == 5,
                      "stats entry")
        filename, line, function = key
        calls, total, own, cumulative, _callers = value
        _profile_need(type(filename) is type(function) is str and len(filename) <= 4096, "stats labels")
        _profile_need(type(line) is int and 0 <= line <= 10_000_000
                      and type(calls) is type(total) is int and 0 <= calls <= total <= 2**53 - 1, "stats integers")
        _profile_need(type(own) in (int, float) and type(cumulative) in (int, float)
                      and math.isfinite(own) and math.isfinite(cumulative)
                      and 0 <= own <= cumulative <= 1_000_000, "stats times")
        path = filename.replace("\\", "/")
        components = path.split("/")
        safe = (path not in ("~", "") and not any(p in (".", "..") for p in components)
                and not any(ord(c) < 32 or ord(c) == 127 for c in path))
        label = path[len(prefix):] if safe and path.startswith(prefix) else path.rsplit("/", 1)[-1]
        if not safe or not label or len(label) > 200 or not re.fullmatch(r"[A-Za-z0-9_./-]+", label):
            label = "<external>"
        if len(function) > 160 or not re.fullmatch(r"[A-Za-z_<>][A-Za-z0-9_.<>]*", function):
            builtin = re.fullmatch(r"<built-in method ([A-Za-z_][A-Za-z0-9_.]*)>", function)
            method = re.fullmatch(r"<method '([A-Za-z_][A-Za-z0-9_]*)' of '([A-Za-z_][A-Za-z0-9_]*)' objects>", function)
            function = builtin[1] if builtin else (method[2] + "." + method[1] if method else "<function>")
        rows.append({"file": label, "line": line, "function": function, "primitive_calls": calls,
                     "total_calls": total, "self_ms": round(1000 * own, 3),
                     "cumulative_ms": round(1000 * cumulative, 3)})
    return sorted(rows, key=lambda row: (-row["self_ms"], row["file"], row["line"], row["function"]))[:40]


def _profile_factory():
    import cProfile
    return cProfile.Profile()


def _render_profile_rows(profiler, repo):
    import pstats
    return _safe_profile_rows(pstats.Stats(profiler).stats, repo)


def _post_timer_admission_profile(cache, raw, binding, version, repo, phase):
    if os.environ.get("GITHUB_ACTIONS") != "true" or not _timed_leg():
        return None
    _profile_need(phase is None, "measured phase still active")
    _profile_need(type(raw) is bytes and type(binding) is dict, "raw subject type")
    key = (*version, binding["sha256"])
    entry = cache.entries.get(key)
    _profile_need(entry is not None and entry.snapshot is not None and entry.carriage is not None, "cached subject")
    pinned_snapshot, pinned_admission = entry.snapshot, entry.carriage
    documents = entry.documents
    document_items = tuple(documents.items())
    snapshot, baseline = cache.carriage_source(raw, binding["sha256"])
    _profile_need(snapshot is pinned_snapshot and baseline is pinned_admission
                  and cache.entries.get(key) is entry
                  and entry.snapshot is pinned_snapshot and entry.carriage is pinned_admission,
                  "cache lookup regenerated subject")
    _profile_need(entry.documents is documents
                  and _profile_same(tuple(documents), tuple(host for host, _doc in document_items))
                  and all(documents[host] is doc for host, doc in document_items), "lookup documents replaced")
    before = uip.bound_snapshot_source(snapshot)
    _profile_need(before.get("source_bound") is True and type(before.get("sha256")) is str
                  and type(binding.get("sha256")) is str
                  and type(before.get("bytes")) is int and type(binding.get("bytes")) is int
                  and before["sha256"] == binding["sha256"]
                  and before["bytes"] == binding["bytes"] == len(raw), "complete source/raw binding")
    profiler = _profile_factory()
    result = _profile_original_admission(snapshot, profiler)
    _profile_admission_equal(snapshot, baseline, result)
    after = uip.bound_snapshot_source(snapshot)
    _profile_need(after.get("source_bound") is True and _profile_same(after, before), "complete source purity")
    _profile_need(cache.entries.get(key) is entry
                  and entry.snapshot is pinned_snapshot and entry.carriage is pinned_admission,
                  "cache subject replaced")
    _profile_need(entry.documents is documents
                  and _profile_same(tuple(documents), tuple(host for host, _doc in document_items))
                  and all(documents[host] is doc for host, doc in document_items), "cache documents replaced")
    output = {"status": "DIAGNOSTIC_ONLY_AFTER_TIMERS", "complete_equivalence": True, "source_purity": True,
              "not_acceptance_latency": True, "inclusive_not_additive": True, "instrumented_profile": True}
    try:  # ONLY rendering: no admission, source, cache, alias or equivalence refusal is hidden here.
        output["rows"] = _render_profile_rows(profiler, repo)
    except Exception as error:
        name = type(error).__name__
        output.update(render_status="UNAVAILABLE", rows=[],
                      error_class=name if len(name) <= 160 and re.fullmatch(r"[A-Za-z_]\w*", name) else "Error")
    return output


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


def test_a_timed_call_starts_after_a_collection_outside_its_timer_with_the_collector_enabled(monkeypatch):
    events = []
    ticks = [10.0, 10.25]
    monkeypatch.setitem(globals(), "_timed_leg", lambda: True)
    monkeypatch.setattr(gc, "collect", lambda *_args, **_kwargs: events.append("collect") or 0)
    monkeypatch.setattr(time, "perf_counter", lambda: events.append("clock") or (ticks.pop(0) if ticks else 10.25))

    def call():
        events.append(("call", gc.isenabled()))
        return "result"

    assert _timed(call) == ("result", 250.0)
    assert events == ["collect", "clock", ("call", True), "clock"]


def test_a_call_on_a_leg_without_millisecond_ceilings_is_timed_without_a_collection(monkeypatch):
    ticks = [1.0, 1.5]
    monkeypatch.setitem(globals(), "_timed_leg", lambda: False)
    monkeypatch.setattr(gc, "collect", lambda *_args, **_kwargs: pytest.fail("collected on an untimed leg"))
    monkeypatch.setattr(time, "perf_counter", lambda: ticks.pop(0) if ticks else 1.5)
    assert _timed(lambda: 7) == (7, 500.0)


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
    return len(json.dumps(value, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8"))


def _timed(call):
    """Time one call against its budget. On a timed leg the cyclic collector first runs to completion OUTSIDE the
    timer and stays enabled during the call, so the window pays for every collection the call's own allocations
    trigger but not for collection debt left by earlier, unrelated tests in the same process. Without this, one
    generation-2 collection of the whole default-suite process (a 2.7-3.0 GB heap on hosted Linux) can land
    inside the window: every recorded full-suite first-page failure (744.7 to 997.5 ms) had exactly one inside it,
    and every passing run had none. Budgets, assertions and timed legs are unchanged."""
    if _timed_leg():
        gc.collect()
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
            (uip, "_carriage_role_query", "role_owner_query"),
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
    without_id, ingest_without_ms = _timed(
        lambda: store.add_snapshot(campaign["id"], "without carriage", dict(fleet), {})["id"])
    with_id, ingest_with_ms = _timed(
        lambda: store.add_snapshot(campaign["id"], "with carriage", {**fleet, "vlan_carriage": section}, {})["id"])
    warm_id = store.add_snapshot(campaign["id"], "warm-up", {"vlan_cutover": []}, {})["id"]
    cache = api._ProjectionCache(store)
    if diagnostics:
        for name in ("get_carriage_document", "verify_carriage_document", "get_carriage_page_bundle"):
            monkeypatch.setattr(store, name, traced(name, getattr(store, name)))

    def no_request_preparation(*_args, **_kwargs):
        raise AssertionError("A first document or lazy page performed ingestion/full-carriage work")

    # Actual ingestion above must prepare both samples once. The original first-use stub below
    # is unchanged; no target snapshot/document/page is read or warmed before its real timer.
    request_owners = []
    for module, names in (
        (api.engine, ("bind_ui_projection_snapshot", "ui_projection_carriage_admission", "ui_projection",
                      "prepare_carriage_projection")),
        (uip, ("carriage_admission", "_carriage_gaps", "validate_vlan_carriage", "carriage_row_counts",
               "carriage_row_cables", "_carriage_page_item", "_carriage_refs", "_carriage_role_query")),
    ):
        for name in names:
            request_owners.append((module, name, getattr(module, name)))
            monkeypatch.setattr(module, name, no_request_preparation)
    warm_raw, warm_binding = store.get_snapshot_blob(warm_id)
    cache.document(warm_raw, warm_binding["sha256"], None, snapshot_id=warm_id)  # original first-use stub only
    raw0, binding0 = store.get_snapshot_blob(without_id)
    raw1, binding1 = store.get_snapshot_blob(with_id)
    phase = "document_without"
    _document, without_ms = _timed(lambda: cache.document(raw0, binding0["sha256"], None, snapshot_id=without_id))
    phase = "document_with"
    document, with_ms = _timed(lambda: cache.document(raw1, binding1["sha256"], None, snapshot_id=with_id))
    assert all(entry.snapshot is None and entry.carriage is None and entry.prepared_document
               for entry in cache.entries.values())

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
                "page_ms": page_ms, "page_bytes": _bytes(response), "page_items": len(response["payload"]["page"]["items"]),
                "ingest_ms_without": ingest_without_ms, "ingest_ms_with": ingest_with_ms,
                "stored_derivative_bytes_v200": store.get_carriage_projection_payload_bytes(with_id)}
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
                "prepared_documents": {key[-1]: entry.prepared_document for key, entry in cache.entries.items()},
                "phases": {key: {name: {"count": value["count"], "ms": round(value["ms"], 1)}
                                 for name, value in sorted(stage.items())}
                           for key, stage in stages.items()},
            }, sort_keys=True))
    # The old after-timer full-admission comparison remains covered by its standalone controls.
    # It is no longer the HTTP path. Current requests above instead fail if they try that work.
    assert store.get_snapshot_blob(with_id) == (raw1, binding1)
    assert all(entry.snapshot is None and entry.carriage is None and entry.prepared_document
               for entry in cache.entries.values())
    assert measured["page_bytes"] <= BUDGET["page_bytes"]
    assert 0 < measured["stored_derivative_bytes_v200"] <= uip.CARRIAGE_DERIVATIVE_BYTE_LIMIT
    if _timed_leg():
        assert measured["document_growth_ms"] <= BUDGET["document_growth_ms"]
        assert measured["page_ms"] <= BUDGET["page_ms"]
        assert measured["first_page_ms"] <= BUDGET["page_ms"]

    # Disclose the additional persisted derivative's real growth AFTER every timed operation and gate.
    # This cannot warm the target document/page; it restores ingestion owners solely for a new snapshot.
    for module, name, original in request_owners:
        monkeypatch.setattr(module, name, original)
    smaller = {**fleet, "vlan_cutover": fleet["vlan_cutover"][:100]}
    smaller["vlan_carriage"] = compute_vlan_carriage(
        smaller["cable_map"], smaller["interfaces"], smaller["stp_topology_observations"], smaller["vlan_cutover"])
    smaller_id = store.add_snapshot(campaign["id"], "100 VLAN derivative census", smaller, {})["id"]
    smaller_bytes = store.get_carriage_projection_payload_bytes(smaller_id)
    assert 0 < smaller_bytes <= uip.CARRIAGE_DERIVATIVE_BYTE_LIMIT
    _report(capsys, "materialized-derivative", {
        "stored_payload_bytes_v100": smaller_bytes,
        "stored_payload_bytes_v200": measured["stored_derivative_bytes_v200"],
        "growth_bytes_v100_v200": measured["stored_derivative_bytes_v200"] - smaller_bytes,
        "payload_byte_limit": uip.CARRIAGE_DERIVATIVE_BYTE_LIMIT,
        "includes_sqlite_file_overhead": False,
    })


def _round2_record(port, peer="", remote="", channel=""):
    """The refuter's exact pure interface fields; no captures, CLI, filesystem or new relation implementation."""
    return dict(port=port, cdp_neighbor=peer, neighbor_port=remote, switchport_mode="Trunk",
                trunk_allowed_vlans="10-209", trunk_native_vlan="1", trunk_allowed_none="", port_channel=channel)


def _round2_scale(member_count):
    """Exact6113983469 construction, parameterized only between the original2 and hostile8 bundle members."""
    hosts = [f"switch-{i:03d}" for i in range(300)]
    interfaces, cables = {h: {} for h in hosts}, []

    def put(host, port, peer, remote, channel=""):
        interfaces[host][port] = _round2_record(port, peer, remote, channel)

    def link(i, delta, ap, bp, bundled=False):
        a, b = hosts[i], hosts[(i + delta) % 300]
        members = [dict(a_port=ap, b_port=bp)]
        if bundled:
            members.extend(dict(a_port=f"Gi1/0/{100 + 2 * n}", b_port=f"Gi1/0/{101 + 2 * n}")
                           for n in range(member_count - 1))
        for member in members:
            put(a, member["a_port"], b, member["b_port"], "Po10" if bundled else "")
            put(b, member["b_port"], a, member["a_port"], "Po20" if bundled else "")
        if bundled:
            put(a, "Po10", "", "")
            put(b, "Po20", "", "")
        cables.append(dict(a=a, a_port=ap, b=b, b_port=bp, is_pc=bundled, members=members))

    for i in range(300):
        link(i, 1, "Gi1/0/1", "Gi1/0/2", i < 150)
        for n in range(3):
            host, port, far = hosts[i], f"Gi1/0/{7 + n}", f"edge-{i:03d}-{n}"
            put(host, port, far, "Port 1")
            cables.append(dict(a=host, a_port=port, b=far, b_port="Port 1", is_pc=False,
                               members=[dict(a_port=port, b_port="Port 1")]))
        link(i, 2, "Gi1/0/3", "Gi1/0/4")
    snap = dict(interfaces=interfaces, cable_map=dict(cables=cables), stp_topology_observations={},
                vlan_cutover=[dict(vlan=v) for v in range(10, 210)])
    snap["vlan_carriage"] = compute_vlan_carriage(
        snap["cable_map"], interfaces, {}, snap["vlan_cutover"])
    assert validate_vlan_carriage(snap["vlan_carriage"]) == (True, "ok")
    return snap


@pytest.fixture(scope="module", params=[2, 8])
def round2_scale(request):
    return _round2_scale(request.param)


@pytest.mark.parametrize("vlan_index", [0, 199])
@pytest.mark.parametrize("limit", [25, 137, 199, 200])
def test_round2_every_pure_owner_page_is_bounded_complete_and_deterministic(round2_scale, vlan_index, limit, capsys):
    from jsonschema import Draft202012Validator

    snap = round2_scale
    before = deepcopy(snap)
    section = snap["vlan_carriage"]
    coverage = section["coverage"]
    assert len(snap["interfaces"]) == 300 and len(section["rows"]) == 200
    assert (coverage["cable_rows"], coverage["assessed_cables"], coverage["edge_cables"]) == (1500, 600, 900)
    assert coverage["requested_pairs"] == coverage["emitted_pairs"] == 120000
    expected = [c for c in section["cables"] if c["scope"] == "assessed"]
    assert sum(c["ends"]["is_pc"] for c in expected) == 150
    schema = uip.ui_projection_schema()
    validator = Draft202012Validator({"$ref": "#/$defs/CarriageDocument", "$defs": schema["$defs"]})
    admission = uip.carriage_admission(snap)
    offset, seen, maximum = 0, [], 0
    while True:
        document = uip.project_vlan_carriage(snap, vlan_index, offset, limit, admission=admission)
        assert document == uip.project_vlan_carriage(snap, vlan_index, offset, limit, admission=admission)
        validator.validate(document)
        page = document["carriage"]["page"]
        maximum = max(maximum, _bytes(document))
        assert _bytes(document) <= BUDGET["page_bytes"] == page["byte_limit"]
        assert page["state"] == "published" and page["reason"] is None
        assert page["offset"] == offset and 1 <= page["limit"] <= limit
        assert page["total"] == 600 and page["returned"] == len(page["items"])
        assert page["returned"] == min(page["limit"], 600 - offset)
        for projected, stored in zip(page["items"], expected[offset:offset + page["returned"]], strict=True):
            assert projected["index"] == stored["index"]
            assert [m["index"] for m in projected["members"]["items"]] == [m["index"] for m in stored["members"]]
        seen.extend(item["index"] for item in page["items"])
        offset += page["returned"]
        if not page["has_more"]:
            break
        assert page["returned"] > 0
    assert seen == [c["index"] for c in expected] and offset == 600
    beyond = uip.project_vlan_carriage(snap, vlan_index, 601, limit, admission=admission)["carriage"]["page"]
    assert beyond["returned"] == 0 and beyond["total"] == 600 and beyond["has_more"] is False
    assert snap == before
    with capsys.disabled():
        print("ROUND2-PURE-CARRIAGE-PAGES " + json.dumps({"members": len(expected[0]["members"]),
              "vlan_index": vlan_index, "requested_limit": limit, "cables": len(seen), "maximum_owner_bytes": maximum}))


def test_round2_eight_member_full_http_envelope_stays_within_the_unchanged_budget(
        round2_scale, capsys, monkeypatch, tmp_path):
    from pathlib import Path
    webapp = str(Path(__file__).resolve().parents[1] / "webapp")
    if webapp not in sys.path:
        sys.path.insert(0, webapp)
    from backend import ui_projection_api as api
    from backend.storage import Store

    snap = round2_scale
    store = Store(tmp_path / "round2-pages.db")
    campaign = store.create_campaign("Synthetic complete carriage pages")
    snapshot_id = store.add_snapshot(campaign["id"], "prepared", snap, {})["id"]
    raw, binding = store.get_snapshot_blob(snapshot_id)
    cache = api._ProjectionCache(store)
    offset, indices, maximum = 0, [], 0
    while True:
        response = api.carriage_page(cache, raw, binding, snapshot_id, 0, offset, 200)
        api.UiProjectionCarriageResponse.model_validate(response)
        maximum = max(maximum, _bytes(response))
        assert _bytes(response) <= BUDGET["page_bytes"]
        page = response["payload"]["page"]
        assert page["state"] == "published" and page["returned"] > 0
        indices.extend(item["index"] for item in page["items"])
        offset += page["returned"]
        if not page["has_more"]:
            break
    assert indices == [c["index"] for c in snap["vlan_carriage"]["cables"] if c["scope"] == "assessed"]
    oversized = deepcopy(response)
    oversized["limitations"][0]["text"] = "x" * BUDGET["page_bytes"]
    # Structural schema acceptance cannot waive the distinct complete-wire resource guard.
    api._CARRIAGE_VALIDATOR.validate(oversized)
    with pytest.raises(ValueError, match="complete response exceeds"):
        api.UiProjectionCarriageResponse.model_validate(oversized)
    original = api.engine.ui_projection_carriage
    for damage in ("offset", "limit"):
        def forged(*args, **kwargs):
            document = original(*args, **kwargs)
            if damage == "limit":
                document["carriage"]["page"][damage] = 201  # attack the requested200 upper bound, not effective+1
            else:
                document["carriage"]["page"][damage] += 1
            return document
        with monkeypatch.context() as changed:
            changed.setattr(api.engine, "ui_projection_carriage", forged)
            with pytest.raises(ValueError, match="changed its source, VLAN row or summary"):
                api.carriage_page(cache, raw, binding, snapshot_id, 0, 0, 200)
    with capsys.disabled():
        print("ROUND2-PURE-CARRIAGE-HTTP " + json.dumps({"cables": len(indices), "maximum_wire_bytes": maximum}))


def test_round2_an_indivisible_cable_that_cannot_fit_is_explicitly_unsupported(round2_scale, monkeypatch):
    snap = round2_scale
    original = uip.project_vlan_carriage(snap, 0, 0, 1)
    item_bytes = _bytes(original["carriage"]["page"]["items"][0])
    empty = deepcopy(original)
    empty["carriage"]["page"]["items"] = []
    # Tighten a synthetic bound below one complete item but above the ordinary context; never raise3M.
    tighter = _bytes(empty) + item_bytes // 2
    assert tighter < BUDGET["page_bytes"]
    monkeypatch.setattr(uip, "CARRIAGE_PAGE_BYTE_LIMIT", tighter)
    held = uip.project_vlan_carriage(snap, 0, 0, 200)
    page = held["carriage"]["page"]
    assert page["state"] == "unverified" and page["reason"].startswith("unsupported:")
    assert "/vlan_carriage/cables/0" in page["reason"]
    assert page["offset"] == 0 and page["total"] == 600 and page["returned"] == 0
    assert page["items"] == [] and page["has_more"] is True
    assert held["carriage"]["summary"] == original["carriage"]["summary"]
    assert _bytes(held) <= tighter


def test_round2_more_than_one_page_of_members_is_held_without_partial_cable_output(round2_scale):
    snap = deepcopy(round2_scale)
    cable = snap["cable_map"]["cables"][0]
    for n in range(len(cable["members"]), 401):
        ap, bp = f"Gi2/0/{500 + 2 * n}", f"Gi2/0/{501 + 2 * n}"
        snap["interfaces"][cable["a"]][ap] = _round2_record(ap, cable["b"], bp, "Po10")
        snap["interfaces"][cable["b"]][bp] = _round2_record(bp, cable["a"], ap, "Po20")
        cable["members"].append(dict(a_port=ap, b_port=bp))
    snap["vlan_carriage"] = compute_vlan_carriage(snap["cable_map"], snap["interfaces"], {}, snap["vlan_cutover"])
    assert validate_vlan_carriage(snap["vlan_carriage"]) == (True, "ok")
    before = deepcopy(snap)
    result = uip.project_vlan_carriage(snap, 0, 0, 200)
    page = result["carriage"]["page"]
    assert page["state"] == "unverified" and page["reason"].startswith("unsupported:")
    assert page["total"] == 600 and page["offset"] == 0 and page["returned"] == 0
    assert page["items"] == [] and page["has_more"] is True
    assert _bytes(result) <= BUDGET["page_bytes"]
    assert snap == before and len(snap["vlan_carriage"]["cables"][0]["members"]) == 401


def test_round2_unrepresentable_transport_context_fails_closed_without_a_page(round2_scale):
    with pytest.raises(ValueError, match="unsupported: carriage page context exceeds"):
        uip.project_vlan_carriage(round2_scale, 0, 0, 200, transport_overhead=BUDGET["page_bytes"] - 1)


def test_round2_byte_accounting_refuses_non_finite_context_instead_of_emitting_non_json(round2_scale, monkeypatch):
    monkeypatch.setattr(uip, "_engine", lambda _ctx: {"synthetic_non_finite": float("nan")})
    with pytest.raises(ValueError, match="Out of range float"):
        uip.project_vlan_carriage(round2_scale, 0, 0, 200)


def _profile_control_subject(monkeypatch, *, prefix=True):
    from types import SimpleNamespace
    from cisco_toolkit.protocol_assurance import bind_snapshot_json_bytes
    from test_ui_projection_vlan_carriage import _round2_bundle
    from test_vlan_carriage import _stp

    observations = {host: _stp({10: [("Po10", "Desg", "FWD")],
                               20: [("Po10", "Desg", "FWD")]}) for host in ("switch-a", "switch-b")}
    value = _round2_bundle(observations)  # PURE interface/cable dictionary; no capture or filesystem producer.
    value["vlan_cutover"] = [{"vlan": 10}, {"vlan": 20}]
    for records in value["interfaces"].values():
        for record in records.values():
            record["trunk_allowed_vlans"] = "10,20"
    value["vlan_carriage"] = compute_vlan_carriage(value["cable_map"], value["interfaces"], observations,
                                                  value["vlan_cutover"])
    value["stp_topology_observations"]["switch-b"]["state_capture_state"] = "error"  # Held gap-order control.
    raw = json.dumps(value).encode("utf-8")
    subject = bind_snapshot_json_bytes(raw)
    monkeypatch.setattr(uip, "_CARRIAGE_NATIVE_ROLE_PREFIX_ENABLED", prefix)  # BEFORE the genuine baseline.
    baseline = uip.carriage_admission(subject)
    binding = {key: uip.bound_snapshot_source(subject)[key] for key in ("sha256", "bytes")}
    entry = SimpleNamespace(snapshot=subject, carriage=baseline, documents={None: {"declared": "owned document"}})
    version = ("declared-profile-control",)

    class Cache:
        entries = {(*version, binding["sha256"]): entry}

        def carriage_source(self, _raw, _digest):
            return entry.snapshot, entry.carriage

    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setattr(sys.modules[__name__], "_timed_leg", lambda: True)
    return Cache(), raw, binding, version, subject, baseline


def test_post_timer_profile_uses_one_real_admission_complete_source_and_safe_stats(monkeypatch):
    cache, raw, binding, version, subject, baseline = _profile_control_subject(monkeypatch)
    original, calls = uip.carriage_admission, []

    def observed(value):
        calls.append(value)
        return original(value)

    monkeypatch.setattr(uip, "carriage_admission", observed)
    output = _post_timer_admission_profile(cache, raw, binding, version, "declared-repository", None)
    assert calls == [subject] and cache.entries[(*version, binding["sha256"])].carriage is baseline
    assert output["complete_equivalence"] is output["source_purity"] is True
    assert output["not_acceptance_latency"] is True and 0 < len(output["rows"]) <= 40
    assert all(not row["file"].startswith(("/", "\\")) and ":" not in row["file"] for row in output["rows"])


@pytest.mark.parametrize("where", ["nonhosted", "nontimed", "active-phase", "absent-entry"])
def test_profile_gate_and_existing_subject_refusal_do_not_import_or_call_profiler(monkeypatch, where):
    cache, raw, binding, version, _subject, _baseline = _profile_control_subject(monkeypatch)

    def forbidden():
        pytest.fail("Ineligible diagnostic imported or constructed a profiler")

    monkeypatch.setattr(sys.modules[__name__], "_profile_factory", forbidden)
    if where == "nonhosted":
        monkeypatch.delenv("GITHUB_ACTIONS")
    elif where == "nontimed":
        monkeypatch.setattr(sys.modules[__name__], "_timed_leg", lambda: False)
    elif where == "absent-entry":
        cache.entries.clear()
    if where in ("active-phase", "absent-entry"):
        with pytest.raises(AssertionError, match="Admission diagnostic"):
            _post_timer_admission_profile(cache, raw, binding, version, "repo", "page" if where == "active-phase" else None)
    else:
        assert _post_timer_admission_profile(cache, raw, binding, version, "repo", None) is None


@pytest.mark.parametrize("replace", ["source-and-admission", "document-map", "document-object"])
def test_profile_lookup_cannot_replace_cached_objects_then_return_their_new_aliases(monkeypatch, replace):
    from cisco_toolkit.protocol_assurance import bind_snapshot_json_bytes
    cache, raw, binding, version, _subject, _baseline = _profile_control_subject(monkeypatch)
    entry = cache.entries[(*version, binding["sha256"])]

    def regenerated(_raw, _digest):
        if replace == "source-and-admission":
            entry.snapshot = bind_snapshot_json_bytes(raw)  # Real new equal-content source/admission, not a stub.
            entry.carriage = uip.carriage_admission(entry.snapshot)
        elif replace == "document-map":
            entry.documents = dict(entry.documents)
        else:
            entry.documents[None] = dict(entry.documents[None])
        return entry.snapshot, entry.carriage

    def forbidden():
        pytest.fail("Cache replacement reached profiling")

    monkeypatch.setattr(cache, "carriage_source", regenerated)
    monkeypatch.setattr(sys.modules[__name__], "_profile_factory", forbidden)
    with pytest.raises(AssertionError, match="Admission diagnostic"):
        _post_timer_admission_profile(cache, raw, binding, version, "repo", None)


@pytest.mark.parametrize("slot", ["source", "source-subclass", "section", "failed", "gaps-order", "gaps-bool",
                                  "offsets-list", "offsets-subclass", "offsets-bool", "observations-order", "observation-copy", "index-bool",
                                  "index-list", "index-order"])
def test_profile_equivalence_refuses_each_owner_slot_type_order_or_foreign_alias(monkeypatch, slot):
    from types import MappingProxyType
    _cache, _raw, _binding, _version, subject, baseline = _profile_control_subject(monkeypatch)
    result = uip.carriage_admission(subject)
    if slot == "source":
        result.source["refs"] = list(reversed(result.source["refs"]))
    elif slot == "source-subclass":
        class ForeignSource(dict):
            pass
        result.source = ForeignSource(result.source)
    elif slot == "section":
        result.section = deepcopy(result.section)
    elif slot == "failed":
        result.failed = ("unverified", "declared failure")
    elif slot == "gaps-order":
        result.gaps = MappingProxyType(dict(reversed(tuple(result.gaps.items()))))
    elif slot == "gaps-bool":
        result.gaps = MappingProxyType({False if key == 0 else key: value for key, value in result.gaps.items()})
    elif slot == "offsets-list":
        result.offsets = list(result.offsets)
    elif slot == "offsets-subclass":
        class ForeignOffsets(tuple):
            pass
        result.offsets = ForeignOffsets(result.offsets)
    elif slot == "offsets-bool":
        result.offsets = ((False, *result.offsets[0][1:]), *result.offsets[1:])
    elif slot == "observations-order":
        result.observations = MappingProxyType(dict(reversed(tuple(result.observations.items()))))
    else:
        values = dict(result.observations)
        host = next(key for key, (_record, index) in values.items() if index)
        record, index = values[host]
        if slot == "observation-copy":
            record = deepcopy(record)
        else:
            entries = dict(index)
            first = next(iter(entries))
            if slot == "index-bool":
                entries[first] = (bool(entries[first][0]), *entries[first][1:])
            elif slot == "index-list":
                entries[first] = list(entries[first])
            else:
                entries = dict(reversed(tuple(entries.items())))
            index = MappingProxyType(entries)
        values[host] = (record, index)
        result.observations = MappingProxyType(values)
    with pytest.raises(AssertionError, match="Admission diagnostic"):
        _profile_admission_equal(subject, baseline, result)


@pytest.mark.parametrize("when", ["before", "after", "binding-bytes", "raw-bytes", "cache-replaced"])
def test_profile_current_source_purity_and_cache_identity_refuse_real_mutation(monkeypatch, when):
    cache, raw, binding, version, subject, baseline = _profile_control_subject(monkeypatch)
    original = uip.carriage_admission
    if when == "before":
        subject["declared mutation"] = True
    elif when == "binding-bytes":
        binding["bytes"] += 1
    elif when == "raw-bytes":
        raw += b" "

    def changed(value):
        result = original(value)
        if when == "after":
            value["declared mutation"] = True
        elif when == "cache-replaced":
            cache.entries[(*version, binding["sha256"])].carriage = result
        return result

    monkeypatch.setattr(uip, "carriage_admission", changed)
    with pytest.raises(AssertionError, match="Admission diagnostic"):
        _post_timer_admission_profile(cache, raw, binding, version, "repo", None)
    assert baseline.section is subject["vlan_carriage"]


@pytest.mark.parametrize("error,cleanup_error", [(RuntimeError, False), (TypeError, False), (RuntimeError, True),
                                              (None, True)])
def test_profile_one_original_call_and_cleanup_preserve_exact_errors(monkeypatch, error, cleanup_error):
    _cache, _raw, _binding, _version, subject, _baseline = _profile_control_subject(monkeypatch)
    original, events = uip.carriage_admission, []

    class Profiler:
        def enable(self):
            events.append("enable")

        def disable(self):
            events.append("disable")
            if cleanup_error:
                raise OSError("declared cleanup failure")

    def refused(value):
        events.append("original")
        result = original(value)
        if error:
            raise error("declared admission failure")
        return result

    monkeypatch.setattr(uip, "carriage_admission", refused)
    expected, message = (error, "declared admission failure") if error else (OSError, "declared cleanup failure")
    with pytest.raises(expected) as caught:
        _profile_original_admission(subject, Profiler())
    assert type(caught.value) is expected and caught.value.args == (message,)
    assert events == ["enable", "original", "disable"]


def test_profile_rows_are_bounded_path_safe_and_formatting_never_hides_budget_failure(monkeypatch):
    stats = {(f"/home/hidden-person/private/function-{i}.py", i, "safe_name"): (1, 1, 0.01, 0.02, {})
             for i in range(45)}
    stats[("C:\\Users\\hidden-person\\private.py", 1, "<method 'get' of 'dict' objects>")] = (1, 1, 0.02, 0.03, {})
    rows = _safe_profile_rows(stats, "/known/repository")
    assert len(rows) == 40 and "hidden-person" not in json.dumps(rows)
    assert rows[0]["file"] == "private.py" and rows[0]["function"] == "dict.get"
    owned = _safe_profile_rows({("/known/repository/cisco_toolkit/ui_projection.py", 1, "_carriage_gaps"):
                               (1, 1, 0.1, 0.2, {})}, "/known/repository")
    assert owned[0]["file"] == "cisco_toolkit/ui_projection.py"
    unsafe = _safe_profile_rows({("/private/../sensitive.py", 1, "unsafe\nfunction"):
                                (1, 1, 0.1, 0.2, {})}, "/known/repository")
    assert unsafe[0]["file"] == "<external>" and unsafe[0]["function"] == "<function>"
    with pytest.raises(AssertionError, match="Admission diagnostic"):
        _safe_profile_rows({("file.py", False, "function"): (1, 1, 0.1, 0.2, {})}, "repo")

    class Hidden:
        def __repr__(self):
            pytest.fail("Diagnostic rendered a foreign payload")

    with pytest.raises(AssertionError, match="Admission diagnostic"):
        _safe_profile_rows({("file.py", 1, Hidden()): (1, 1, 0.1, 0.2, {})}, "repo")
    cache, raw, binding, version, _subject, _baseline = _profile_control_subject(monkeypatch)

    def refused(*_args):
        raise ValueError("/home/hidden-person/private/payload")

    monkeypatch.setattr(sys.modules[__name__], "_render_profile_rows", refused)
    output = _post_timer_admission_profile(cache, raw, binding, version, "repo", None)
    assert output["render_status"] == "UNAVAILABLE" and output["error_class"] == "ValueError"
    assert "hidden-person" not in json.dumps(output) and output["complete_equivalence"] is True
    with pytest.raises(AssertionError):
        assert BUDGET["document_growth_ms"] + 1 <= BUDGET["document_growth_ms"]  # Original decision still fails.


def _comparison_value(value):
    """Immutable diagnostic metadata seal; neither a source digest nor a produced answer."""
    from types import MappingProxyType

    kind = type(value)
    if kind in (dict, MappingProxyType):
        return kind, tuple((_comparison_value(key), _comparison_value(item)) for key, item in value.items())
    if kind in (tuple, list):
        return kind, tuple(_comparison_value(item) for item in value)
    if kind is float:
        _profile_need(math.isfinite(value), "baseline non-finite metadata")
        return kind, value.hex()
    _profile_need(kind in (type(None), str, int, bool), "baseline metadata type")
    return kind, value


def _comparison_baseline(baseline):
    slots = ("source", "section", "failed", "gaps", "offsets", "observations")
    _profile_need(type(baseline) is uip._CarriageAdmission and uip._CarriageAdmission.__slots__ == slots,
                  "comparison baseline owner")
    references = tuple(getattr(baseline, name) for name in slots)
    observations, records = [], []
    for host, pair in baseline.observations.items():
        _profile_need(type(pair) is tuple and len(pair) == 2, "baseline observation pair")
        record, index = pair
        observations.append((_comparison_value(host), _comparison_value(index)))
        records.append(record)
    metadata = tuple(_comparison_value(value) for value in
                     (baseline.source, baseline.failed, baseline.gaps, baseline.offsets))
    return references, metadata, type(baseline.observations), tuple(observations), tuple(records)


def _comparison_baseline_unchanged(baseline, seal):
    current = _comparison_baseline(baseline)
    _profile_need(all(a is b for a, b in zip(current[0], seal[0])), "baseline slots replaced")
    _profile_need(current[1:4] == seal[1:4], "baseline metadata mutated")
    _profile_need(len(current[4]) == len(seal[4])
                  and all(a is b for a, b in zip(current[4], seal[4])), "baseline source aliases replaced")


def _comparison_restore(owner, flag, hook):
    """Attempt every owned restoration; never short circuit on a first failure."""
    errors = []
    for restore, args in ((setattr, (uip, "carriage_admission", owner)),
                          (setattr, (uip, "_CARRIAGE_NATIVE_ROLE_PREFIX_ENABLED", flag)),
                          (sys.setprofile, (hook,))):
        try:
            restore(*args)
        except BaseException as error:
            errors.append(error)
    return errors


def _post_timer_prefix_comparison(cache, raw, binding, version, repo, phase, *, expected_default=True):
    """Two unchanged one-call diagnostics, pinned across both; never acceptance latency."""
    if os.environ.get("GITHUB_ACTIONS") != "true" or not _timed_leg():
        return None
    _profile_need(phase is None, "measured phase still active")
    _profile_need(type(raw) is bytes and type(binding) is dict, "raw subject type")
    key = (*version, binding["sha256"])
    entry = cache.entries.get(key)
    _profile_need(entry is not None and entry.snapshot is not None and entry.carriage is not None, "cached subject")
    snapshot, baseline, documents = entry.snapshot, entry.carriage, entry.documents
    document_items, seal = tuple(documents.items()), _comparison_baseline(baseline)
    document_values = _comparison_value(documents)  # Complete typed/order seal, not merely root object pins.
    before = uip.bound_snapshot_source(snapshot)
    _profile_need(before.get("source_bound") is True and type(before.get("sha256")) is str
                  and type(binding.get("sha256")) is str and type(before.get("bytes")) is int
                  and type(binding.get("bytes")) is int and before["sha256"] == binding["sha256"]
                  and before["bytes"] == binding["bytes"] == len(raw), "complete source/raw binding")
    owner, flag, hook = uip.carriage_admission, uip._CARRIAGE_NATIVE_ROLE_PREFIX_ENABLED, sys.getprofile()
    _profile_need(type(expected_default) is bool and flag is expected_default,
                  "comparison requires declared prefix default")
    _profile_need(hook is None or callable(hook), "comparison profile hook form")
    names = ("_CARRIAGE_CPU_ROUTING_ENABLED", "_CARRIAGE_ROUTING_TOKEN_ENABLED",
             "_CARRIAGE_ROLE_CELLS_ENABLED", "_CARRIAGE_LOOP_DISPATCH_ENABLED")
    old_flags = tuple(getattr(uip, name) for name in names)
    calls, results, reports, expected, latched = [], [], [], True, []

    def retained():
        _profile_need(cache.entries.get(key) is entry and entry.snapshot is snapshot
                      and entry.carriage is baseline, "comparison cache subject replaced")
        _profile_need(entry.documents is documents
                      and _profile_same(tuple(documents), tuple(host for host, _doc in document_items))
                      and all(documents[host] is doc for host, doc in document_items), "comparison documents replaced")
        _profile_need(_comparison_value(documents) == document_values, "comparison document values mutated")
        _comparison_baseline_unchanged(baseline, seal)
        source = uip.bound_snapshot_source(snapshot)
        _profile_need(source.get("source_bound") is True and _profile_same(source, before), "comparison source purity")
        _profile_need(all(getattr(uip, name) is value for name, value in zip(names, old_flags)), "old flags changed")

    def observed(value):
        try:
            actual = uip._CARRIAGE_NATIVE_ROLE_PREFIX_ENABLED
            _profile_need(value is snapshot and actual is expected and len(calls) < 2 and len(calls) == len(reports),
                          "comparison actual admission call")
            calls.append(actual)
            result = owner(value)  # EXACT genuine owner and subject, no fabricated diagnostic answer.
            results.append(result)
            return result
        except BaseException as error:
            if not latched:
                latched.append(error)  # A renderer/helper may catch it; never let formatting erase a refusal.
            raise

    primary = None
    try:
        uip.carriage_admission = observed
        for expected in (True, False):
            retained()
            uip._CARRIAGE_NATIVE_ROLE_PREFIX_ENABLED = expected
            try:
                report = _post_timer_admission_profile(cache, raw, binding, version, repo, phase)
            except BaseException:
                if latched:
                    raise latched[0]
                raise
            if latched:
                raise latched[0]  # OUTSIDE the unchanged helper's formatting-only fallback catch.
            _profile_need(uip._CARRIAGE_NATIVE_ROLE_PREFIX_ENABLED is expected
                          and uip.carriage_admission is observed and len(calls) == len(reports) + 1
                          and len(results) == len(calls), "comparison mode or real call changed")
            retained()
            _profile_need(type(report) is dict and report.get("complete_equivalence") is True
                          and report.get("source_purity") is True and type(report.get("rows")) is list
                          and len(report["rows"]) <= 40, "comparison original report")
            reports.append(report)
        _profile_need(calls == [True, False], "comparison call order")
        _profile_admission_equal(snapshot, results[0], results[1])
        retained()
    except BaseException as error:
        primary = error
        raise
    finally:
        errors = _comparison_restore(owner, flag, hook)
        if errors and primary is None and not latched:
            raise errors[0]
    if latched:
        raise latched[0]
    _profile_need(uip.carriage_admission is owner and uip._CARRIAGE_NATIVE_ROLE_PREFIX_ENABLED is flag
                  and sys.getprofile() is hook, "comparison restoration")
    retained()
    return {"status": "DIAGNOSTIC_ONLY_AFTER_TIMERS", "order": calls, "complete_equivalence": True,
            "source_purity": True, "not_acceptance_latency": True, "inclusive_not_additive": True,
            "instrumented_profile": True, "row_limit_per_mode": 40, "row_limit_total": 80,
            "profiles": [{"prefix_enabled": enabled, "profile": report}
                         for enabled, report in zip(calls, reports)]}


def test_prefix_comparison_uses_two_real_calls_same_subject_and_keeps_baseline(monkeypatch):
    cache, raw, binding, version, subject, baseline = _profile_control_subject(monkeypatch)
    owner, calls, hook = uip.carriage_admission, [], sys.getprofile()

    def genuine(value):
        calls.append((value, uip._CARRIAGE_NATIVE_ROLE_PREFIX_ENABLED))
        return owner(value)

    monkeypatch.setattr(uip, "carriage_admission", genuine)
    output = _post_timer_prefix_comparison(cache, raw, binding, version, "declared-repository", None)
    assert calls == [(subject, True), (subject, False)]
    assert cache.entries[(*version, binding["sha256"])].carriage is baseline
    assert uip.carriage_admission is genuine and uip._CARRIAGE_NATIVE_ROLE_PREFIX_ENABLED is True
    assert sys.getprofile() is hook and output["complete_equivalence"] is output["source_purity"] is True
    assert output["order"] == [True, False] and output["row_limit_total"] == 80
    assert all(0 < len(row["profile"]["rows"]) <= 40 for row in output["profiles"])


@pytest.mark.parametrize("when", ["first", "second"])
@pytest.mark.parametrize("damage", ["entry", "snapshot", "baseline", "metadata", "documents", "document-object",
                                      "source", "result-index", "old-flag"])
def test_prefix_comparison_refuses_real_pair_mutation_or_replacement(monkeypatch, when, damage):
    from types import MappingProxyType

    cache, raw, binding, version, subject, baseline = _profile_control_subject(monkeypatch)
    owner, calls = uip.carriage_admission, []
    entry = cache.entries[(*version, binding["sha256"])]

    def genuine(value):
        result = owner(value)
        calls.append(value)
        if len(calls) == (1 if when == "first" else 2):
            if damage == "entry":
                cache.entries[(*version, binding["sha256"])] = type(entry)(
                    snapshot=entry.snapshot, carriage=entry.carriage, documents=entry.documents)
            elif damage == "snapshot":
                entry.snapshot = deepcopy(subject)
            elif damage == "baseline":
                entry.carriage = result
            elif damage == "metadata":
                baseline.source["comparison mutation"] = True
                result.source["comparison mutation"] = True  # Old helper equality alone would bless both.
            elif damage == "documents":
                entry.documents = deepcopy(entry.documents)
            elif damage == "document-object":
                entry.documents[None] = deepcopy(entry.documents[None])
            elif damage == "source":
                subject["comparison mutation"] = True
            elif damage == "result-index":
                result.gaps = MappingProxyType(dict(reversed(tuple(result.gaps.items()))))
                assert tuple(result.gaps) != tuple(baseline.gaps)
            else:
                monkeypatch.setattr(uip, "_CARRIAGE_CPU_ROUTING_ENABLED", False)
        return result

    monkeypatch.setattr(uip, "carriage_admission", genuine)
    with pytest.raises(AssertionError, match="Admission diagnostic"):
        _post_timer_prefix_comparison(cache, raw, binding, version, "repo", None)
    assert uip.carriage_admission is genuine and uip._CARRIAGE_NATIVE_ROLE_PREFIX_ENABLED is True
    monkeypatch.setattr(uip, "_CARRIAGE_CPU_ROUTING_ENABLED", True)


@pytest.mark.parametrize("where", ["nonhosted", "nontimed", "active-phase", "fake-helper"])
def test_prefix_comparison_gates_and_fake_reports_cannot_replace_genuine_calls(monkeypatch, where):
    cache, raw, binding, version, _subject, _baseline = _profile_control_subject(monkeypatch)
    owner = uip.carriage_admission
    if where == "nonhosted":
        monkeypatch.setenv("GITHUB_ACTIONS", "false")
    elif where == "nontimed":
        monkeypatch.setattr(sys.modules[__name__], "_timed_leg", lambda: False)
    elif where == "fake-helper":
        monkeypatch.setattr(sys.modules[__name__], "_post_timer_admission_profile",
                            lambda *_args: {"complete_equivalence": True, "source_purity": True, "rows": []})
    if where in ("nonhosted", "nontimed"):
        assert _post_timer_prefix_comparison(cache, raw, binding, version, "repo", None) is None
    else:
        with pytest.raises(AssertionError, match="Admission diagnostic"):
            _post_timer_prefix_comparison(cache, raw, binding, version, "repo",
                                         "page" if where == "active-phase" else None)
    assert uip.carriage_admission is owner and uip._CARRIAGE_NATIVE_ROLE_PREFIX_ENABLED is True


@pytest.mark.parametrize("failed_mode", [True, False])
@pytest.mark.parametrize("error", [RuntimeError, TypeError])
def test_prefix_comparison_restores_both_bindings_and_profile_after_real_error(monkeypatch, failed_mode, error):
    cache, raw, binding, version, _subject, _baseline = _profile_control_subject(monkeypatch)
    owner, calls, hook = uip.carriage_admission, [], sys.getprofile()

    def genuine(value):
        calls.append(uip._CARRIAGE_NATIVE_ROLE_PREFIX_ENABLED)
        if calls[-1] is failed_mode:
            raise error("declared original admission error")
        return owner(value)

    monkeypatch.setattr(uip, "carriage_admission", genuine)
    with pytest.raises(error) as raised:
        _post_timer_prefix_comparison(cache, raw, binding, version, "repo", None)
    assert raised.value.args == ("declared original admission error",)
    assert calls == ([True] if failed_mode else [True, False])
    assert uip.carriage_admission is genuine and uip._CARRIAGE_NATIVE_ROLE_PREFIX_ENABLED is True
    assert sys.getprofile() is hook


@pytest.mark.parametrize("primary_error", [True, False])
def test_prefix_comparison_attempts_all_restorations_and_preserves_primary_error(monkeypatch, primary_error):
    cache, raw, binding, version, _subject, _baseline = _profile_control_subject(monkeypatch)
    real_setattr, owner, events, hook = setattr, uip.carriage_admission, [], sys.getprofile()

    def genuine(value):
        if primary_error:
            raise RuntimeError("primary admission refusal")
        return owner(value)

    def restoration(target, name, value):
        events.append(name)
        if name == "carriage_admission":
            raise TypeError("declared owner restoration failure")
        return real_setattr(target, name, value)

    monkeypatch.setattr(uip, "carriage_admission", genuine)
    monkeypatch.setattr(sys.modules[__name__], "setattr", restoration, raising=False)
    try:
        with pytest.raises(RuntimeError if primary_error else TypeError) as raised:
            _post_timer_prefix_comparison(cache, raw, binding, version, "repo", None)
        assert raised.value.args == (("primary admission refusal",) if primary_error
                                     else ("declared owner restoration failure",))
        assert events == ["carriage_admission", "_CARRIAGE_NATIVE_ROLE_PREFIX_ENABLED"]
        assert uip._CARRIAGE_NATIVE_ROLE_PREFIX_ENABLED is True and sys.getprofile() is hook
    finally:
        real_setattr(uip, "carriage_admission", owner)


def test_prefix_comparison_safe_rendering_does_not_hide_real_equality_or_budget(monkeypatch):
    cache, raw, binding, version, _subject, _baseline = _profile_control_subject(monkeypatch)

    def refused(*_args):
        raise ValueError("/private/person/payload")

    monkeypatch.setattr(sys.modules[__name__], "_render_profile_rows", refused)
    output = _post_timer_prefix_comparison(cache, raw, binding, version, "repo", None)
    assert all(row["profile"]["render_status"] == "UNAVAILABLE" for row in output["profiles"])
    assert "private/person" not in json.dumps(output) and output["complete_equivalence"] is True
    with pytest.raises(AssertionError):
        assert BUDGET["document_growth_ms"] + 1 <= BUDGET["document_growth_ms"]


def test_prefix_comparison_does_not_repin_a_regenerated_second_helper_subject(monkeypatch):
    from types import SimpleNamespace

    cache, raw, binding, version, subject, _baseline = _profile_control_subject(monkeypatch)
    helper, owner, calls = _post_timer_admission_profile, uip.carriage_admission, []

    def genuine(value):
        calls.append((value, uip._CARRIAGE_NATIVE_ROLE_PREFIX_ENABLED))
        return owner(value)

    def replacement(*args):
        report = helper(*args)
        copied = deepcopy(subject)
        cache.entries[(*version, binding["sha256"])] = SimpleNamespace(
            snapshot=copied, carriage=owner(copied), documents={None: {"declared": "replacement document"}})
        cache.carriage_source = lambda _raw, _digest: (
            cache.entries[(*version, binding["sha256"])].snapshot,
            cache.entries[(*version, binding["sha256"])].carriage)
        return report

    monkeypatch.setattr(uip, "carriage_admission", genuine)
    monkeypatch.setattr(sys.modules[__name__], "_post_timer_admission_profile", replacement)
    with pytest.raises(AssertionError, match="comparison cache subject replaced"):
        _post_timer_prefix_comparison(cache, raw, binding, version, "repo", None)
    assert calls == [(subject, True)]  # Refuse BEFORE a second helper can pin the replacement.
    assert uip.carriage_admission is genuine and uip._CARRIAGE_NATIVE_ROLE_PREFIX_ENABLED is True


@pytest.mark.parametrize("failed_mode", [True, False])
@pytest.mark.parametrize("subject_kind", ["wrong", "extra"])
def test_prefix_comparison_renderer_cannot_swallow_an_observer_refusal(monkeypatch, failed_mode, subject_kind):
    cache, raw, binding, version, subject, _baseline = _profile_control_subject(monkeypatch)
    owner, renderer, saved, calls, hook = uip.carriage_admission, _render_profile_rows, [], [], sys.getprofile()

    def genuine(value):
        calls.append((value, uip._CARRIAGE_NATIVE_ROLE_PREFIX_ENABLED))
        return owner(value)

    def hostile(profiler, repo):
        if uip._CARRIAGE_NATIVE_ROLE_PREFIX_ENABLED is failed_mode:
            try:
                uip.carriage_admission(deepcopy(subject) if subject_kind == "wrong" else subject)
            except AssertionError as error:
                saved.append(error)
                raise  # The ORIGINAL helper catches it as formatting failure; the wrapper must not.
        return renderer(profiler, repo)

    monkeypatch.setattr(uip, "carriage_admission", genuine)
    monkeypatch.setattr(sys.modules[__name__], "_render_profile_rows", hostile)
    with pytest.raises(AssertionError) as raised:
        _post_timer_prefix_comparison(cache, raw, binding, version, "repo", None)
    assert len(saved) == 1 and raised.value is saved[0]
    assert calls == ([(subject, True)] if failed_mode else [(subject, True), (subject, False)])
    assert uip.carriage_admission is genuine and uip._CARRIAGE_NATIVE_ROLE_PREFIX_ENABLED is True
    assert sys.getprofile() is hook


@pytest.mark.parametrize("failed_mode", [True, False])
@pytest.mark.parametrize("subject_kind", ["wrong", "extra"])
@pytest.mark.parametrize("secondary_error", [False, True])
def test_prefix_comparison_catching_helper_cannot_relabel_first_observer_error(
        monkeypatch, failed_mode, subject_kind, secondary_error):
    cache, raw, binding, version, subject, _baseline = _profile_control_subject(monkeypatch)
    owner, helper, saved, calls, hook = uip.carriage_admission, _post_timer_admission_profile, [], [], sys.getprofile()

    def genuine(value):
        calls.append((value, uip._CARRIAGE_NATIVE_ROLE_PREFIX_ENABLED))
        return owner(value)

    def catching(*args):
        report = helper(*args)  # GENUINE first/second owner call and complete old-helper assertions.
        if uip._CARRIAGE_NATIVE_ROLE_PREFIX_ENABLED is failed_mode:
            try:
                uip.carriage_admission(deepcopy(subject) if subject_kind == "wrong" else subject)
            except AssertionError as error:
                saved.append(error)
            if secondary_error:
                raise TypeError("secondary helper error must not replace original refusal")
        return report

    monkeypatch.setattr(uip, "carriage_admission", genuine)
    monkeypatch.setattr(sys.modules[__name__], "_post_timer_admission_profile", catching)
    with pytest.raises(AssertionError) as raised:
        _post_timer_prefix_comparison(cache, raw, binding, version, "repo", None)
    assert len(saved) == 1 and raised.value is saved[0]
    assert calls == ([(subject, True)] if failed_mode else [(subject, True), (subject, False)])
    assert uip.carriage_admission is genuine and uip._CARRIAGE_NATIVE_ROLE_PREFIX_ENABLED is True
    assert sys.getprofile() is hook


@pytest.mark.parametrize("failed_mode", [True, False])
def test_prefix_comparison_catching_helper_cannot_mask_genuine_owner_error(monkeypatch, failed_mode):
    cache, raw, binding, version, _subject, _baseline = _profile_control_subject(monkeypatch)
    owner, helper, calls, hook = uip.carriage_admission, _post_timer_admission_profile, [], sys.getprofile()
    declared = RuntimeError("declared genuine admission refusal")

    def genuine(value):
        calls.append(uip._CARRIAGE_NATIVE_ROLE_PREFIX_ENABLED)
        if calls[-1] is failed_mode:
            raise declared
        return owner(value)

    def catching(*args):
        try:
            return helper(*args)
        except RuntimeError as error:
            assert error is declared
            return {"complete_equivalence": True, "source_purity": True, "rows": []}

    monkeypatch.setattr(uip, "carriage_admission", genuine)
    monkeypatch.setattr(sys.modules[__name__], "_post_timer_admission_profile", catching)
    with pytest.raises(RuntimeError) as raised:
        _post_timer_prefix_comparison(cache, raw, binding, version, "repo", None)
    assert raised.value is declared and raised.value.args == ("declared genuine admission refusal",)
    assert calls == ([True] if failed_mode else [True, False])
    assert uip.carriage_admission is genuine and uip._CARRIAGE_NATIVE_ROLE_PREFIX_ENABLED is True
    assert sys.getprofile() is hook


def test_prefix_comparison_latches_a_caught_third_call_during_owned_cleanup(monkeypatch):
    cache, raw, binding, version, subject, _baseline = _profile_control_subject(monkeypatch)
    owner, restore, calls, saved, hook = uip.carriage_admission, _comparison_restore, [], [], sys.getprofile()

    def genuine(value):
        calls.append((value, uip._CARRIAGE_NATIVE_ROLE_PREFIX_ENABLED))
        return owner(value)

    def cleanup(original_owner, flag, original_hook):
        try:
            uip.carriage_admission(subject)  # The two real helper calls are already complete.
        except AssertionError as error:
            saved.append(error)
        return restore(original_owner, flag, original_hook)

    monkeypatch.setattr(uip, "carriage_admission", genuine)
    monkeypatch.setattr(sys.modules[__name__], "_comparison_restore", cleanup)
    with pytest.raises(AssertionError) as raised:
        _post_timer_prefix_comparison(cache, raw, binding, version, "repo", None)
    assert len(saved) == 1 and raised.value is saved[0]
    assert calls == [(subject, True), (subject, False)]
    assert uip.carriage_admission is genuine and uip._CARRIAGE_NATIVE_ROLE_PREFIX_ENABLED is True
    assert sys.getprofile() is hook


@pytest.mark.parametrize("failed_mode", [True, False])
def test_prefix_comparison_refuses_in_place_document_values_after_real_owner_call(monkeypatch, failed_mode):
    cache, raw, binding, version, subject, _baseline = _profile_control_subject(monkeypatch)
    owner, calls, hook = uip.carriage_admission, [], sys.getprofile()
    entry = cache.entries[(*version, binding["sha256"])]
    documents, document = entry.documents, entry.documents[None]

    def genuine(value):
        result = owner(value)
        calls.append((value, uip._CARRIAGE_NATIVE_ROLE_PREFIX_ENABLED))
        if calls[-1][1] is failed_mode:
            document["declared"] = "mutated in place by real owner callback"
        return result

    monkeypatch.setattr(uip, "carriage_admission", genuine)
    with pytest.raises(AssertionError, match="comparison document values mutated"):
        _post_timer_prefix_comparison(cache, raw, binding, version, "repo", None)
    assert entry.documents is documents and documents[None] is document
    assert calls == ([(subject, True)] if failed_mode else [(subject, True), (subject, False)])
    assert uip.carriage_admission is genuine and uip._CARRIAGE_NATIVE_ROLE_PREFIX_ENABLED is True
    assert sys.getprofile() is hook


@pytest.mark.parametrize("failed_mode", [True, False])
def test_prefix_comparison_refuses_in_place_document_values_during_real_rendering(monkeypatch, failed_mode):
    cache, raw, binding, version, subject, _baseline = _profile_control_subject(monkeypatch)
    owner, renderer, calls, hook = uip.carriage_admission, _render_profile_rows, [], sys.getprofile()
    entry = cache.entries[(*version, binding["sha256"])]
    documents, document = entry.documents, entry.documents[None]

    def genuine(value):
        calls.append((value, uip._CARRIAGE_NATIVE_ROLE_PREFIX_ENABLED))
        return owner(value)

    def hostile(profiler, repo):
        if uip._CARRIAGE_NATIVE_ROLE_PREFIX_ENABLED is failed_mode:
            document["declared"] = "mutated in place after old-helper equality/source checks"
        return renderer(profiler, repo)

    monkeypatch.setattr(uip, "carriage_admission", genuine)
    monkeypatch.setattr(sys.modules[__name__], "_render_profile_rows", hostile)
    with pytest.raises(AssertionError, match="comparison document values mutated"):
        _post_timer_prefix_comparison(cache, raw, binding, version, "repo", None)
    assert entry.documents is documents and documents[None] is document
    assert calls == ([(subject, True)] if failed_mode else [(subject, True), (subject, False)])
    assert uip.carriage_admission is genuine and uip._CARRIAGE_NATIVE_ROLE_PREFIX_ENABLED is True
    assert sys.getprofile() is hook


def _page_alias_graph(value):
    """Private ordinal topology AND strong original mutable references; never rendered."""
    seen, occurrences, objects = {}, [], []

    def visit(node, path):
        if type(node) not in (dict, list):
            return
        identity = id(node)
        ordinal = seen.get(identity)
        if ordinal is not None:
            occurrences.append((path, ordinal))
            return
        ordinal = len(objects)
        seen[identity] = ordinal
        objects.append(node)
        occurrences.append((path, ordinal))
        children = node.items() if type(node) is dict else enumerate(node)
        for key, child in children:
            visit(child, path + (key,))

    visit(value, ())
    return tuple(occurrences), tuple(objects)


def _page_source_mutables(*values):
    """Retain source containers, including the binder's dict subclass; never invoke a foreign copy hook."""
    from types import MappingProxyType

    seen, objects = set(), []

    def visit(node):
        if isinstance(node, (dict, list)):
            if id(node) in seen:
                return
            seen.add(id(node))
            objects.append(node)
            children = dict.values(node) if isinstance(node, dict) else list.__iter__(node)
        elif type(node) is MappingProxyType:
            children = node.values()
        elif type(node) is tuple:
            children = node
        else:
            return
        for child in children:
            visit(child)

    for value in values:
        visit(value)
    return tuple(objects)


def _page_profile_pin(api, cache, raw, binding, version, query, response, phase):
    _profile_need(phase is None and type(raw) is bytes and type(binding) is dict, "page pin phase or raw type")
    _profile_need(type(query) is tuple and len(query) == 4 and all(type(value) is int for value in query), "page query")
    key = (*version, binding["sha256"])
    entry = cache.entries.get(key)
    _profile_need(entry is not None and entry.snapshot is not None and entry.carriage is not None, "page cached subject")
    snapshot, admission, documents = entry.snapshot, entry.carriage, entry.documents
    document_items = tuple(documents.items())
    source = uip.bound_snapshot_source(snapshot)
    _profile_need(source.get("source_bound") is True and type(source.get("sha256")) is str
                  and type(source.get("bytes")) is int and _profile_same(source["sha256"], binding.get("sha256"))
                  and _profile_same(source["bytes"], binding.get("bytes")) and source["bytes"] == len(raw), "page raw binding")
    slots = _comparison_baseline(admission)
    names = ("_CARRIAGE_CPU_ROUTING_ENABLED", "_CARRIAGE_ROUTING_TOKEN_ENABLED", "_CARRIAGE_ROLE_CELLS_ENABLED",
             "_CARRIAGE_LOOP_DISPATCH_ENABLED", "_CARRIAGE_NATIVE_ROLE_PREFIX_ENABLED")
    owners = [(api, "carriage_page", api.carriage_page), (api, "_CARRIAGE_VALIDATOR", api._CARRIAGE_VALIDATOR),
              (api, "_require_carriage_page", api._require_carriage_page)]
    regen = [(api.engine, name, getattr(api.engine, name)) for name in
             ("bind_ui_projection_snapshot", "ui_projection_carriage_admission", "ui_projection")]
    regen.append((uip, "carriage_admission", uip.carriage_admission))
    schema = api._CARRIAGE_VALIDATOR.schema
    return {"api": api, "cache": cache, "raw": raw, "binding": binding, "binding_values": _comparison_value(binding),
            "key": key, "entry": entry, "snapshot": snapshot, "admission": admission, "slots": slots,
            "documents": documents, "document_items": document_items, "doc_values": _comparison_value(documents),
            "main_document": next(value for host, value in document_items if host is None),
            "source": source, "query": query, "response": response, "wire_values": _comparison_value(response),
            "wire_graph": _page_alias_graph(response), "wire_bytes": _bytes(response),
            "source_objects": _page_source_mutables(snapshot, documents, *slots[0], schema),
            "owners": owners, "regen": regen, "flag_names": names, "flags": tuple(getattr(uip, name) for name in names),
            "lookups": (cache.document, cache.carriage_source),
            "lookup_attributes": tuple((name, name in vars(cache), vars(cache).get(name))
                                       for name in ("document", "carriage_source")),
            "validator_call": api._CARRIAGE_VALIDATOR.validate,
            "schema": schema, "schema_values": _comparison_value(schema)}


def _page_profile_bindings(pin, *, observers=None):
    from types import MethodType

    _profile_need(pin["owners"][1][2].schema is pin["schema"], "page schema replaced")
    current, owner = pin["owners"][1][2].validate, pin["validator_call"]
    _profile_need(current is owner or (type(current) is type(owner) is MethodType
                  and current.__self__ is owner.__self__ and current.__func__ is owner.__func__), "page validator method replaced")
    for target, name, owner in pin["owners"] + pin["regen"]:
        expected = observers.get((target, name), owner) if observers is not None else owner
        _profile_need(getattr(target, name) is expected, "page owner binding mutated")
    for name, owner in zip(("document", "carriage_source"), pin["lookups"]):
        current = getattr(pin["cache"], name)
        expected = observers.get((pin["cache"], name), owner) if observers is not None else owner
        _profile_need(current is expected or (type(current) is type(expected) is MethodType
                      and current.__self__ is expected.__self__ and current.__func__ is expected.__func__), "page cache lookup binding mutated")


def _page_profile_retained(pin, *, observers=None):
    entry, documents, response = pin["entry"], pin["documents"], pin["response"]
    _profile_need(pin["cache"].entries.get(pin["key"]) is entry and entry.snapshot is pin["snapshot"]
                  and entry.carriage is pin["admission"] and entry.documents is documents, "page cache replaced")
    _profile_need(_comparison_value(documents) == pin["doc_values"]
                  and _profile_same(tuple(documents), tuple(key for key, _ in pin["document_items"]))
                  and all(documents[key] is value for key, value in pin["document_items"]), "page documents mutated")
    _comparison_baseline_unchanged(pin["admission"], pin["slots"])
    _profile_need(_comparison_value(pin["binding"]) == pin["binding_values"], "page binding mutated")
    source = uip.bound_snapshot_source(pin["snapshot"])
    _profile_need(source.get("source_bound") is True and _profile_same(source, pin["source"]), "page current source mutated")
    _profile_need(_comparison_value(response) == pin["wire_values"], "original page values mutated")
    graph = _page_alias_graph(response)
    _profile_need(graph[0] == pin["wire_graph"][0] and len(graph[1]) == len(pin["wire_graph"][1])
                  and all(a is b for a, b in zip(graph[1], pin["wire_graph"][1])), "original page containers replaced")
    current_objects = _page_source_mutables(pin["snapshot"], documents, *pin["slots"][0], pin["schema"])
    _profile_need(len(current_objects) == len(pin["source_objects"])
                  and all(a is b for a, b in zip(current_objects, pin["source_objects"])), "page source aliases replaced")
    _profile_need(_comparison_value(pin["schema"]) == pin["schema_values"], "page schema mutated")
    _profile_need(all(getattr(uip, name) is value for name, value in zip(pin["flag_names"], pin["flags"])), "page flags mutated")
    _page_profile_bindings(pin, observers=observers)


def _post_timer_page_profile(pin, warm, repo, phase):
    if os.environ.get("GITHUB_ACTIONS") != "true" or not _timed_leg():
        return None
    _profile_need(phase is None, "page measured phase still active")
    _page_profile_retained(pin)  # Pins precede the EARLIER admission pair and its renderer.
    hook, calls, lookup_calls, returned, latched, observers = sys.getprofile(), [], [], [], [], {}
    _profile_need(hook is None or callable(hook), "page profile hook form")
    page_owner, validator, metadata_owner = (item[2] for item in pin["owners"])

    def observe(name, owner, *args, **kwargs):
        try:
            _page_profile_bindings(pin, observers=observers)  # Cheap fresh bindings, not full source/value scans.
            _profile_need(not kwargs and len(calls) < 3 and name == ("page", "schema", "metadata")[len(calls)],
                          "page exact call sequence")
            if name == "page":
                _profile_need(len(args) == 7 and args[0] is pin["cache"] and args[1] is pin["raw"]
                              and args[2] is pin["binding"] and _profile_same(tuple(args[3:]), pin["query"]), "page exact query")
            else:
                _profile_need(len(returned) == 1 and type(returned[0]) is dict and len(args) == 1
                              and args[0] is (returned[0] if name == "schema" else returned[0]["payload"]), "page validator subject")
            calls.append(name)
            result = owner(*args, **kwargs)
            if name == "page":
                returned.append(result)
            return result
        except BaseException as error:
            if not latched:
                latched.append(error)
            raise

    def forbidden(*_args, **_kwargs):
        try:
            _profile_need(False, "page diagnostic attempted genuine regeneration")
        except BaseException as error:
            if not latched:
                latched.append(error)
            raise

    def lookup(name, owner, *args, **kwargs):
        try:
            _page_profile_bindings(pin, observers=observers)
            expected = ("document", "carriage_source")
            _profile_need(not kwargs and len(lookup_calls) < 2 and name == expected[len(lookup_calls)]
                          and len(args) == (3 if name == "document" else 2) and args[0] is pin["raw"]
                          and _profile_same(args[1], pin["binding"]["sha256"])
                          and (name != "document" or args[2] is None), "page exact cached lookup")
            lookup_calls.append(name)
            value = owner(*args, **kwargs)  # Saved genuine lookup, not a repinned replacement.
            if name == "document":
                _profile_need(value is pin["main_document"], "page cached document return replaced")
            else:
                _profile_need(type(value) is tuple and len(value) == 2 and value[0] is pin["snapshot"]
                              and value[1] is pin["admission"], "page cached source return replaced")
            return value
        except BaseException as error:
            if not latched:
                latched.append(error)
            raise

    class ObservedValidator:
        def validate(self, *args, **kwargs):
            return observe("schema", pin["validator_call"], *args, **kwargs)

        def __getattr__(self, name):
            return getattr(validator, name)

    api = pin["api"]
    observers[(api, "carriage_page")] = lambda *a, **kw: observe("page", page_owner, *a, **kw)
    observers[(api, "_CARRIAGE_VALIDATOR")] = ObservedValidator()
    observers[(api, "_require_carriage_page")] = lambda *a, **kw: observe("metadata", metadata_owner, *a, **kw)
    for target, name, _owner in pin["regen"]:
        observers[(target, name)] = forbidden
    def cached_observer(name, owner):
        def cached(*args, **kwargs):
            return lookup(name, owner, *args, **kwargs)
        return cached

    for name, owner in zip(("document", "carriage_source"), pin["lookups"]):
        observers[(pin["cache"], name)] = cached_observer(name, owner)
    primary = None
    try:
        for (target, name), observed in observers.items():
            setattr(target, name, observed)
        profiler, failed = _profile_factory(), False
        try:
            profiler.enable()
            result = warm()  # ONE unchanged warm closure and its TWO original validators.
        except BaseException:
            failed = True
            raise
        finally:
            try:
                profiler.disable()
            except BaseException:
                if not failed:
                    raise
        if latched:
            raise latched[0]
        _profile_need(calls == ["page", "schema", "metadata"] and lookup_calls == ["document", "carriage_source"]
                      and len(returned) == 1 and result is returned[0], "page genuine calls")
        _page_profile_retained(pin, observers=observers)
        _profile_need(_comparison_value(result) == pin["wire_values"] and _bytes(result) == pin["wire_bytes"], "page complete wire equality")
        graph = _page_alias_graph(result)
        forbidden_ids = {id(value) for value in (*pin["source_objects"], *pin["wire_graph"][1])}
        _profile_need(graph[0] == pin["wire_graph"][0] and all(id(value) not in forbidden_ids for value in graph[1]), "page owned alias topology")

        def result_unchanged():
            current = _page_alias_graph(result)
            _profile_need(_comparison_value(result) == pin["wire_values"] and _bytes(result) == pin["wire_bytes"]
                          and current[0] == graph[0] and len(current[1]) == len(graph[1])
                          and all(a is b for a, b in zip(current[1], graph[1])), "profiled page mutated after validation")

        report = {"status": "POST_TIMER_PAGE_DIAGNOSTIC_ONLY", "complete_equivalence": True, "source_purity": True,
                  "not_acceptance_latency": True, "inclusive_not_additive": True, "instrumented_profile": True,
                  "page_calls": 1, "schema_calls": 1, "metadata_calls": 1, "admission_calls": 0, "row_limit": 40}
        try:
            report["rows"] = _render_profile_rows(profiler, repo)
        except Exception as error:
            name = type(error).__name__
            report.update(render_status="UNAVAILABLE", rows=[],
                          error_class=name if len(name) <= 160 and re.fullmatch(r"[A-Za-z_]\w*", name) else "Error")
        if latched:
            raise latched[0]
        _profile_need(type(report["rows"]) is list and len(report["rows"]) <= 40, "page report row bound")
        _page_profile_retained(pin, observers=observers)
        result_unchanged()
    except BaseException as error:
        primary = latched[0] if latched else error
        raise primary
    finally:
        errors = []
        for target, name, owner in pin["owners"] + pin["regen"]:
            try:
                setattr(target, name, owner)
            except BaseException as error:
                errors.append(error)
        for name, present, own_value in pin["lookup_attributes"]:
            try:
                if present:
                    setattr(pin["cache"], name, own_value)
                else:
                    delattr(pin["cache"], name)  # Restore descriptor lookup, not a new permanent method shadow.
            except BaseException as error:
                errors.append(error)
        try:
            sys.setprofile(hook)
        except BaseException as error:
            errors.append(error)
        if errors and primary is None and not latched:
            raise errors[0]
    if latched:
        raise latched[0]
    _page_profile_retained(pin)
    result_unchanged()
    _profile_need(sys.getprofile() is hook, "page profiler restoration")
    return report


def test_prefix_comparison_false_default_uses_true_false_real_calls_and_restores_false(monkeypatch):
    cache, raw, binding, version, subject, _baseline = _profile_control_subject(monkeypatch, prefix=False)
    owner, calls = uip.carriage_admission, []

    def genuine(value):
        calls.append((value, uip._CARRIAGE_NATIVE_ROLE_PREFIX_ENABLED))
        return owner(value)

    monkeypatch.setattr(uip, "carriage_admission", genuine)
    report = _post_timer_prefix_comparison(cache, raw, binding, version, "repo", None, expected_default=False)
    assert calls == [(subject, True), (subject, False)] and report["order"] == [True, False]
    assert report["complete_equivalence"] is report["source_purity"] is True
    assert uip.carriage_admission is genuine and uip._CARRIAGE_NATIVE_ROLE_PREFIX_ENABLED is False


@pytest.mark.parametrize("declared", [True, 0])
def test_prefix_comparison_keeps_exact_declared_default_and_bool_type_guard(monkeypatch, declared):
    cache, raw, binding, version, _subject, _baseline = _profile_control_subject(monkeypatch, prefix=False)
    calls = []

    def forbidden(*_args):
        calls.append(True)
        raise AssertionError("wrong default reached owner or profiler")

    monkeypatch.setattr(uip, "carriage_admission", forbidden)
    monkeypatch.setattr(sys.modules[__name__], "_profile_factory", forbidden)
    with pytest.raises(AssertionError, match="declared prefix default"):
        _post_timer_prefix_comparison(cache, raw, binding, version, "repo", None, expected_default=declared)
    assert calls == [] and uip._CARRIAGE_NATIVE_ROLE_PREFIX_ENABLED is False


def _page_control_subject(monkeypatch, *, effect=None, error=None):
    from pathlib import Path
    webapp = str(Path(__file__).resolve().parents[1] / "webapp")
    if webapp not in sys.path:
        monkeypatch.syspath_prepend(webapp)
    from backend import ui_projection_api as api

    _fake, raw, binding, _version, _subject, _baseline = _profile_control_subject(monkeypatch, prefix=False)
    cache = api._ProjectionCache()
    cache.document(raw, binding["sha256"], None)  # REAL pure document producer/admission, before diagnostic pins.
    query, events, active, responses, method_restore, document_restore = (37, 0, 0, api.MAX_PAGE_SIZE), [], [False], [], [], []
    owners = (api.carriage_page, api._CARRIAGE_VALIDATOR, api._require_carriage_page)

    def page(*args, **kwargs):
        events.append("page")
        result = owners[0](*args, **kwargs)
        if active[0]:
            if effect == "doc-value":
                cache.entries[(*api._PROJECTION_VERSION, binding["sha256"])].documents[None]["schema"] += "-mutated"
            elif effect == "result-alias":
                result["payload"]["page"]["items"] = responses[0]["payload"]["page"]["items"]
            elif effect == "page-error":
                raise error
            elif effect == "validator-late-restore":
                method_restore.append(control_validator.validate)
                control_validator.validate = lambda _response: None
        return result

    class Validator:
        def validate(self, *args, **kwargs):
            events.append("schema")
            result = owners[1].validate(*args, **kwargs)
            if active[0] and effect == "schema-error":
                raise error
            return result

        def __getattr__(self, name):
            return getattr(owners[1], name)

    def metadata(*args, **kwargs):
        events.append("metadata")
        result = owners[2](*args, **kwargs)
        if active[0] and effect == "metadata-error":
            raise error
        if active[0] and effect == "validator-late-restore":
            control_validator.validate = method_restore[0]  # Would erase the drift before a post-only pin check.
        if active[0] and effect == "lookup-document":
            cache.entries[(*api._PROJECTION_VERSION, binding["sha256"])].documents[None] = document_restore[0]
        return result

    monkeypatch.setattr(api, "carriage_page", page)
    control_validator = Validator()
    monkeypatch.setattr(api, "_CARRIAGE_VALIDATOR", control_validator)
    monkeypatch.setattr(api, "_require_carriage_page", metadata)

    def warm():
        response = api.carriage_page(cache, raw, binding, *query)
        api._CARRIAGE_VALIDATOR.validate(response)
        api._require_carriage_page(response["payload"])
        return response

    responses.append(warm())  # GENUINE original response for THIS small query; not a copied payload.
    events.clear()
    if effect == "regeneration":
        document_owner = cache.document

        def regenerate(*args):
            if active[0]:
                cache.entries[(*api._PROJECTION_VERSION, binding["sha256"])].documents.clear()
            return document_owner(*args)  # Its genuine complete-document producer MUST be refused.

        monkeypatch.setattr(cache, "document", regenerate)
    elif effect in ("lookup-document", "lookup-admission"):
        name = "document" if effect == "lookup-document" else "carriage_source"
        lookup_owner = getattr(cache, name)

        def equal_replacement(*args):
            value = lookup_owner(*args)  # Delegate the REAL lookup before replacing only its return.
            if not active[0]:
                return value
            if effect == "lookup-document":
                document_restore.append(value)
                replacement = deepcopy(value)
                cache.entries[(*api._PROJECTION_VERSION, binding["sha256"])].documents[None] = replacement
                return replacement  # CURRENT map and return agree; only the PRE-pinned object can refute it.
            snapshot, admission = value
            same_slots = (getattr(admission, slot) for slot in uip._CarriageAdmission.__slots__)
            return snapshot, uip._CarriageAdmission(*same_slots)  # Genuine owner constructor; not a dataclass.

        monkeypatch.setattr(cache, name, equal_replacement)
    pin = _page_profile_pin(api, cache, raw, binding, api._PROJECTION_VERSION, query, responses[0], None)
    active[0] = True
    return pin, warm, events


def test_post_timer_page_profile_uses_genuine_small_query_and_allows_unused_cache_constructors(monkeypatch):
    pin, warm, events = _page_control_subject(monkeypatch)
    api, constructed, constructor = pin["api"], [], pin["api"]._SnapshotProjection

    def ordinary_default():
        constructed.append(True)
        return constructor()

    monkeypatch.setattr(api, "_SnapshotProjection", ordinary_default)
    before = sys.getprofile()
    cache_attributes = tuple(vars(pin["cache"]).items())
    report = _post_timer_page_profile(pin, warm, "repo", None)
    assert events == ["page", "schema", "metadata"] and constructed == [True, True]
    assert pin["response"]["payload"]["page"]["returned"] < pin["query"][3]
    assert report["page_calls"] == report["schema_calls"] == report["metadata_calls"] == 1
    assert report["admission_calls"] == 0 and report["complete_equivalence"] is report["source_purity"] is True
    assert 0 < len(report["rows"]) <= 40 and sys.getprofile() is before
    _page_profile_retained(pin)
    assert tuple(vars(pin["cache"])) == tuple(name for name, _value in cache_attributes)
    assert all(vars(pin["cache"])[name] is value for name, value in cache_attributes)


@pytest.mark.parametrize("step", ["page", "schema", "metadata"])
def test_post_timer_page_profile_preserves_genuine_late_error_object_and_all_bindings(monkeypatch, step):
    declared = RuntimeError("declared real " + step + " refusal")
    pin, warm, events = _page_control_subject(monkeypatch, effect=step + "-error", error=declared)
    hook = sys.getprofile()
    with pytest.raises(RuntimeError) as raised:
        _post_timer_page_profile(pin, warm, "repo", None)
    assert raised.value is declared and raised.value.args == ("declared real " + step + " refusal",)
    assert events == ["page", "schema", "metadata"][:("page", "schema", "metadata").index(step) + 1]
    assert sys.getprofile() is hook
    _page_profile_retained(pin)


@pytest.mark.parametrize("effect", ["original-equal-replacement", "doc-value", "result-alias", "regeneration"])
def test_post_timer_page_profile_refuses_original_replacement_mutation_alias_and_real_regeneration(monkeypatch, effect):
    pin, warm, events = _page_control_subject(monkeypatch, effect=effect)
    if effect == "original-equal-replacement":
        renderer = _render_profile_rows

        def earlier(profiler, repo):
            items = pin["response"]["payload"]["page"]["items"]
            pin["response"]["payload"]["page"]["items"] = deepcopy(items)
            return renderer(profiler, repo)

        with monkeypatch.context() as pair:
            pair.setattr(sys.modules[__name__], "_render_profile_rows", earlier)
            _post_timer_prefix_comparison(pin["cache"], pin["raw"], pin["binding"], pin["api"]._PROJECTION_VERSION,
                                          "repo", None, expected_default=False)
    with pytest.raises(AssertionError, match="Admission diagnostic"):
        _post_timer_page_profile(pin, warm, "repo", None)
    if effect == "original-equal-replacement":
        assert events == []  # Strong refs refuse BEFORE the later helper can freshly bless equal containers.
    for target, name, owner in pin["owners"] + pin["regen"]:
        assert getattr(target, name) is owner


@pytest.mark.parametrize("format_only", [True, False])
def test_post_timer_page_profile_formatting_fallback_never_swallows_an_extra_real_call(monkeypatch, format_only):
    pin, warm, events = _page_control_subject(monkeypatch)
    saved = []

    def renderer(*_args):
        if format_only:
            raise ValueError("/private/person/payload")
        try:
            warm()  # Attempts a SECOND genuine page call after all three required operations.
        except AssertionError as error:
            saved.append(error)
            raise

    monkeypatch.setattr(sys.modules[__name__], "_render_profile_rows", renderer)
    if format_only:
        report = _post_timer_page_profile(pin, warm, "repo", None)
        assert report["render_status"] == "UNAVAILABLE" and report["rows"] == []
        assert "private/person" not in json.dumps(report)
    else:
        with pytest.raises(AssertionError) as raised:
            _post_timer_page_profile(pin, warm, "repo", None)
        assert len(saved) == 1 and raised.value is saved[0]
    assert events == ["page", "schema", "metadata"]
    _page_profile_retained(pin)


def test_post_timer_page_profile_attempts_all_restorations_without_replacing_a_real_error(monkeypatch):
    declared = RuntimeError("primary real page refusal")
    pin, warm, _events = _page_control_subject(monkeypatch, effect="page-error", error=declared)
    owner, actual_setattr, restored = pin["owners"][0][2], setattr, []

    def restoration(target, name, value):
        if any(target is expected and name == slot and value is original for expected, slot, original in pin["owners"] + pin["regen"]):
            restored.append(name)
            if name == "carriage_page":
                raise TypeError("declared restoration refusal")
        return actual_setattr(target, name, value)

    monkeypatch.setattr(sys.modules[__name__], "setattr", restoration, raising=False)
    try:
        with pytest.raises(RuntimeError) as raised:
            _post_timer_page_profile(pin, warm, "repo", None)
        assert raised.value is declared
        assert restored == [name for _target, name, _owner in pin["owners"] + pin["regen"]]
    finally:
        actual_setattr(pin["api"], "carriage_page", owner)


def test_post_timer_page_profile_copied_answer_cannot_replace_genuine_warm_calls(monkeypatch):
    pin, _warm, events = _page_control_subject(monkeypatch)
    with pytest.raises(AssertionError, match="page genuine calls"):
        _post_timer_page_profile(pin, lambda: deepcopy(pin["response"]), "repo", None)
    assert events == []
    _page_profile_retained(pin)


def test_post_timer_page_profile_refuses_a_validator_method_replaced_by_earlier_renderer(monkeypatch):
    pin, warm, events = _page_control_subject(monkeypatch)
    renderer = _render_profile_rows

    def earlier(profiler, repo):
        pin["owners"][1][2].validate = lambda _response: None  # SAME instance/schema, wrong actual callable.
        return renderer(profiler, repo)

    with monkeypatch.context() as pair:
        pair.setattr(sys.modules[__name__], "_render_profile_rows", earlier)
        _post_timer_prefix_comparison(pin["cache"], pin["raw"], pin["binding"], pin["api"]._PROJECTION_VERSION,
                                      "repo", None, expected_default=False)
    with pytest.raises(AssertionError, match="page validator method replaced"):
        _post_timer_page_profile(pin, warm, "repo", None)
    assert events == []  # Refuse BEFORE any later warm call can bless a silently bypassed validator.


def test_post_timer_page_profile_checks_live_binding_before_schema_even_if_metadata_would_restore_it(monkeypatch):
    pin, warm, events = _page_control_subject(monkeypatch, effect="validator-late-restore")
    with pytest.raises(AssertionError, match="page validator method replaced"):
        _post_timer_page_profile(pin, warm, "repo", None)
    assert events == ["page"]  # Neither a saved schema call nor the late restoration may conceal the swap.
    assert pin["owners"][1][2].validate is not pin["validator_call"]


@pytest.mark.parametrize("replacement", ["document", "admission"])
def test_post_timer_page_profile_refuses_equal_real_lookup_return_replacements(monkeypatch, replacement):
    pin, warm, events = _page_control_subject(monkeypatch, effect="lookup-" + replacement)
    owned_attributes = tuple(vars(pin["cache"]).items())
    with pytest.raises(AssertionError, match="page cached .* return replaced"):
        _post_timer_page_profile(pin, warm, "repo", None)
    assert events == ["page"]  # Stop BEFORE the page producer/schema/metadata can bless the different objects.
    assert tuple(vars(pin["cache"])) == tuple(name for name, _value in owned_attributes)
    assert all(vars(pin["cache"])[name] is value for name, value in owned_attributes)
    if replacement == "document":
        assert pin["documents"][None] is not pin["main_document"]  # Late metadata restoration was not reached.
        pin["documents"][None] = pin["main_document"]  # Restore ONLY this authored mutation for the pin assertion.
    _page_profile_retained(pin)
