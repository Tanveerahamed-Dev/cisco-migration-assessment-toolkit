"""Unit tests for the platform-health axis (NEW-V3.23.167):
parse_cpu_utilization / parse_memory_stats / parse_system_resources (parse layer)
+ compute_platform_health (analyze layer) — the control-plane capacity screening
(single point-in-time sample, declared-not-collected honesty)."""
from cisco_toolkit.analyze import compute_platform_health
from cisco_toolkit.parse import (
    parse_cpu_utilization,
    parse_memory_stats,
    parse_system_resources,
)


_IOS_CPU = "CPU utilization for five seconds: 71%/12%; one minute: 66%; five minutes: 63%\n"
_IOS_MEM = "Processor Pool Total:  690885376 Used:  168148848 Free:  522736528\n"
_NXOS_SYSRES = """\
Load average:   1 minute: 0.28   5 minutes: 0.31   15 minutes: 0.32
Processes   :   720 total, 1 running
CPU states  :   3.5% user,   4.1% kernel,   92.4% idle
Memory usage:   16400932K total,   7322120K used,   9078812K free
"""


def _m(cpu=None, mem=None, sysr=None):
    return {"cpu": cpu or {}, "memory": mem or {}, "system": sysr or {}}


# --------------------------------------------------------------------------- #
# parsers
# --------------------------------------------------------------------------- #
def test_parse_cpu_utilization_with_and_without_interrupt():
    assert parse_cpu_utilization(_IOS_CPU) == {
        "five_sec": 71, "interrupt": 12, "one_min": 66, "five_min": 63}
    no_int = "CPU utilization for five seconds: 9%; one minute: 8%; five minutes: 7%\n"
    assert parse_cpu_utilization(no_int) == {
        "five_sec": 9, "interrupt": 0, "one_min": 8, "five_min": 7}
    assert parse_cpu_utilization("") == {} and parse_cpu_utilization(None) == {}


def test_parse_memory_stats_and_system_resources():
    assert parse_memory_stats(_IOS_MEM) == {
        "total": 690885376, "used": 168148848, "free": 522736528}
    assert parse_memory_stats("garbage\n") == {}
    sr = parse_system_resources(_NXOS_SYSRES)
    assert sr == {"cpu_idle": 92.4, "mem_total_kb": 16400932,
                  "mem_used_kb": 7322120, "mem_free_kb": 9078812, "load_1m": 0.28}
    assert parse_system_resources("") == {}


# --------------------------------------------------------------------------- #
# bands & findings
# --------------------------------------------------------------------------- #
def test_cpu_bands_at_thresholds():
    hot = compute_platform_health({"sw": _m(cpu={"five_sec": 90, "interrupt": 0,
                                                 "one_min": 85, "five_min": 80})})
    assert hot["per_device"][0]["band"] == "Hot"
    assert [f["kind"] for f in hot["findings"]] == ["hot-cpu"]
    assert hot["findings"][0]["severity"] == "High"
    elev = compute_platform_health({"sw": _m(cpu={"five_sec": 65, "interrupt": 0,
                                                  "one_min": 62, "five_min": 60})})
    assert elev["per_device"][0]["band"] == "Elevated"
    assert [f["kind"] for f in elev["findings"]] == ["elevated-cpu"]
    ok = compute_platform_health({"sw": _m(cpu={"five_sec": 70, "interrupt": 0,
                                                "one_min": 65, "five_min": 59})})
    assert ok["per_device"][0]["band"] == "OK" and ok["findings"] == []


def test_memory_bands_at_thresholds():
    low = compute_platform_health({"sw": _m(mem={"total": 1000, "used": 950, "free": 50})})
    assert [f["kind"] for f in low["findings"]] == ["low-memory"]
    assert low["per_device"][0]["band"] == "Hot"
    watch = compute_platform_health({"sw": _m(mem={"total": 1000, "used": 820, "free": 180})})
    assert [f["kind"] for f in watch["findings"]] == ["memory-watch"]
    assert watch["per_device"][0]["band"] == "Elevated"
    ok = compute_platform_health({"sw": _m(mem={"total": 1000, "used": 700, "free": 300})})
    assert ok["findings"] == [] and ok["per_device"][0]["mem_free_pct"] == 30.0


def test_nxos_fallback_is_labeled_instantaneous():
    ph = compute_platform_health({"nx": _m(sysr=parse_system_resources(_NXOS_SYSRES))})
    d = ph["per_device"][0]
    assert d["cpu_5min"] == 7.6                       # 100 - 92.4
    assert "instantaneous" in d["cpu_source"]
    assert d["mem_free_pct"] == 55.4 and d["mem_total_mb"] == 16017
    assert d["band"] == "OK"
    # the 5-min average wins over the instantaneous figure when both exist
    both = compute_platform_health({"nx": _m(cpu={"five_sec": 10, "interrupt": 0,
                                                  "one_min": 9, "five_min": 8},
                                             sysr={"cpu_idle": 10.0})})
    assert both["per_device"][0]["cpu_5min"] == 8
    assert "5-min avg" in both["per_device"][0]["cpu_source"]


# --------------------------------------------------------------------------- #
# honesty & shapes
# --------------------------------------------------------------------------- #
def test_not_collected_declared_and_band_sort():
    ph = compute_platform_health({
        "quiet": _m(),                                            # not collected
        "hot": _m(cpu={"five_sec": 95, "interrupt": 0, "one_min": 92, "five_min": 90}),
        "fine": _m(cpu={"five_sec": 5, "interrupt": 0, "one_min": 5, "five_min": 5}),
    })
    s = ph["summary"]
    assert s["n_devices"] == 3 and s["n_collected"] == 2
    assert s["hosts_not_collected"] == ["quiet"]
    assert [d["host"] for d in ph["per_device"]] == ["hot", "fine", "quiet"]  # worst band first
    by_host = {d["host"]: d for d in ph["per_device"]}
    assert by_host["quiet"]["collected"] is False and by_host["quiet"]["band"] == "Unknown"
    assert not [f for f in ph["findings"] if f["host"] == "quiet"]
    assert s["bands"] == {"Hot": 1, "OK": 1, "Unknown": 1}


def test_note_says_single_sample_and_empty_shapes():
    ph = compute_platform_health({})
    assert ph["per_device"] == [] and ph["findings"] == []
    assert ph["summary"]["n_devices"] == 0
    assert "point-in-time" in ph["note"]
    assert compute_platform_health(None)["summary"]["n_findings"] == 0
