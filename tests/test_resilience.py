"""Tests for the resilience guards added alongside the audit fixes:
- _run_phase / _empty_dep_map  (C1: one phase failure can't sink the run)
- send_cmd                     (C2: pattern-based read with timing fallback)
"""


# --------------------------------------------------------------------------- #
# C1: _run_phase + _empty_dep_map
# --------------------------------------------------------------------------- #
def test_run_phase_returns_value_on_success(cp):
    assert cp._run_phase("ok", lambda a, b: a + b, 40, 2) == 42


def test_run_phase_swallows_exception_and_returns_default(cp):
    def boom():
        raise RuntimeError("kaboom")
    assert cp._run_phase("explode", boom, _default=[]) == []
    assert cp._run_phase("explode", boom) is None   # default default


def test_empty_dep_map_satisfies_consumers(cp):
    dep = cp._empty_dep_map()
    # every key the cross-layer + readiness consumers read must be present
    for k in ("single_fiber", "uplink_ports", "sole_gw", "access_by_vlan",
              "articulation", "fhrp_vlans", "tracked_down", "errored_up",
              "halfdup_up", "single_member_pc", "errdis", "gw_switches",
              "orphan", "model"):
        assert k in dep
    assert dep["model"]["hosts"] == set()
    # the fallback must let downstream analysis run without raising
    assert cp.compute_cross_layer_correlations(dep) == []
    mr = cp.compute_migration_readiness({}, [], [], [], [], [], [], dep)
    assert mr == []


# --------------------------------------------------------------------------- #
# C2: send_cmd prefers send_command, falls back to timing, then "".
# --------------------------------------------------------------------------- #
class _FakeDev:
    def __init__(self, pattern=None, timing=None,
                 pattern_exc=None, timing_exc=None):
        self._pattern, self._timing = pattern, timing
        self._pe, self._te = pattern_exc, timing_exc
        self.calls = []

    def send_command(self, cmd, read_timeout=None):
        self.calls.append(("send_command", cmd, read_timeout))
        if self._pe:
            raise self._pe
        return self._pattern

    def send_command_timing(self, cmd, read_timeout=None):
        self.calls.append(("send_command_timing", cmd, read_timeout))
        if self._te:
            raise self._te
        return self._timing


def test_send_cmd_prefers_pattern_based(cp):
    dev = _FakeDev(pattern="OUTPUT")
    assert cp.send_cmd(dev, "show version") == "OUTPUT"
    assert dev.calls[0][0] == "send_command"          # pattern-based used first
    assert all(c[0] != "send_command_timing" for c in dev.calls)


def test_send_cmd_falls_back_to_timing(cp):
    dev = _FakeDev(pattern_exc=RuntimeError("no prompt match"), timing="TIMING")
    assert cp.send_cmd(dev, "show running-config") == "TIMING"
    assert [c[0] for c in dev.calls] == ["send_command", "send_command_timing"]


def test_send_cmd_returns_empty_when_both_fail(cp):
    dev = _FakeDev(pattern_exc=RuntimeError("a"), timing_exc=RuntimeError("b"))
    assert cp.send_cmd(dev, "show nonsense") == ""


def test_send_cmd_slow_command_gets_longer_timeout(cp):
    dev = _FakeDev(pattern="x")
    cp.send_cmd(dev, "show running-config")           # in _SLOW_CMDS
    assert dev.calls[0][2] == 300
    dev2 = _FakeDev(pattern="x")
    cp.send_cmd(dev2, "show version")                 # not slow
    assert dev2.calls[0][2] == 120
