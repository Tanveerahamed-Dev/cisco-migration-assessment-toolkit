"""AxisSpec registry (Plan A / Tier-2 #8) — the wiring-tax killer at its root.

The drift generator: adding a per-device axis used to mean 3-4 HAND-PARALLEL sites
(accumulator decl + build-loop stanza + snap assign + webapp label), and the exact miss
kept recurring (the months-dead NOS quartet). This slice collapses the first two sites
into ONE registry entry — `_PER_DEVICE_AXES` in the entry module, following the
`_DETECTORS` precedent — driven by a single loop; the snap-assign site is PINNED by a
conformance test here (every registry key must ship in the golden snapshot), and the
webapp SECTION_LABELS derivation is deferred (a parallel session is editing that file).

Contract guarded here:
- registry integrity: unique keys, callable builders, sane shapes;
- every registry axis actually ships (key present in the frozen golden snapshot);
- driver semantics: truthy-keep by default, keep_always records every host,
  custom keep predicates (pim / routing_neighbors) honored, log lines only when kept.
Behavior preservation is proven by the golden suite passing with NO UPDATE_GOLDEN."""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import COLLECT_PARSE_V3_23_0 as cp  # noqa: E402


def test_registry_shape_and_uniqueness():
    axes = cp._PER_DEVICE_AXES
    assert len(axes) >= 40, f"expected the full per-device axis roster, got {len(axes)}"
    keys = [sp.key for sp in axes]
    assert len(keys) == len(set(keys)), "duplicate axis keys in the registry"
    builders = [sp.builder for sp in axes]
    assert len(builders) == len(set(builders)), "two axes share one builder — a paste error"
    for sp in axes:
        assert callable(sp.builder), f"{sp.key}: builder not callable"
        assert isinstance(sp.key, str) and sp.key
        assert sp.log is None or callable(sp.log)
        assert sp.keep is None or callable(sp.keep)


def test_every_registry_axis_ships_in_the_snapshot():
    """The snap-assign site is still hand-keyed — this is the conformance pin that makes
    forgetting it IMPOSSIBLE to miss: every registry key must exist as a top-level key
    of the frozen golden snapshot. Three deliberate exceptions are TRANSIENT FEEDS that
    ship only through their downstream computes (raw configs -> golden_drift/capture
    integrity; raw syslogs -> syslog_intelligence; platform metrics -> platform_health)."""
    golden = json.load(open(os.path.join(ROOT, "tests", "golden", "snapshot.json"),
                            encoding="utf-8"))
    unshipped_by_design = {"run_configs", "syslogs", "platform_metrics"}
    missing = [sp.key for sp in cp._PER_DEVICE_AXES
               if sp.key not in unshipped_by_design and sp.key not in golden]
    assert not missing, f"registry axis(es) never reach the snapshot: {missing}"


def test_driver_semantics(tmp_path, caplog):
    """Drive _run_per_device_axes with a synthetic mini-registry: default truthy-keep,
    keep_always, custom keep, and log-only-when-kept."""
    import logging
    calls = []

    def b_truthy(c2f):
        calls.append("truthy"); return {"x": 1}

    def b_empty(c2f):
        calls.append("empty"); return {}

    def b_always(c2f):
        calls.append("always"); return ""

    def b_custom(c2f):
        calls.append("custom"); return {"rp_mapping": {}, "neighbors": []}

    specs = [
        cp._AxisSpec("t", b_truthy, "T", lambda v: f"{len(v)} thing(s)", None, False),
        cp._AxisSpec("e", b_empty, "E", lambda v: "never logged", None, False),
        cp._AxisSpec("a", b_always, "A", None, None, True),
        cp._AxisSpec("c", b_custom, "C", None,
                     lambda v: bool(v.get("rp_mapping") or v.get("neighbors")), False),
    ]
    stores = {sp.key: {} for sp in specs}
    with caplog.at_level(logging.INFO, logger=cp.logger.name):
        cp._run_per_device_axes(stores, "SW1", {}, specs)
    assert stores["t"] == {"SW1": {"x": 1}}          # truthy kept
    assert stores["e"] == {}                          # empty dropped
    assert stores["a"] == {"SW1": ""}                 # keep_always records every host
    assert stores["c"] == {}                          # custom keep says no (both empty)
    assert calls == ["truthy", "empty", "always", "custom"]   # registry order preserved
    assert "1 thing(s)" in caplog.text and "never logged" not in caplog.text


def test_registry_covers_the_known_axis_roster():
    """The registry must carry the axes the old hand-wired loop carried — spot-pin the
    families whose loss would be silent (the multi-vendor + controller-REST + hardening
    frontiers), plus the custom-keep pair."""
    keys = {sp.key for sp in cp._PER_DEVICE_AXES}
    for k in ("acls", "object_groups", "nat", "security", "config_hygiene", "stp_roots",
              "vpc", "fhrp_detail", "overlay", "copp", "mpls", "lisp", "cts", "dmvpn",
              "crypto", "bfd", "aci", "sdwan", "firewall", "ise", "fmc", "arista",
              "juniper", "cloud", "fortigate", "mroute", "ipv6_nd", "ipv6_routing",
              "pim", "ipv6_fhs", "ntp", "port_security", "storm_control", "qos_runtime",
              "shadow_infra", "routing_neighbors", "redistribution",
              "run_configs", "syslogs", "platform_metrics"):
        assert k in keys, f"axis {k!r} fell out of the registry"
