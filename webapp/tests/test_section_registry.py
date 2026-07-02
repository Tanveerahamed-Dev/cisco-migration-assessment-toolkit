"""Plan-A Tier-2 #8 (remainder): the webapp section allowlist <-> engine/registry conformance gate.

The '#8' AxisSpec slice pinned that every per-device axis ships in the snapshot
(tests/test_axis_registry.py). Its deferred half -- the WEBAPP side -- is pinned here.

The web UI advertises a fixed set of fetchable detail sections: `_ALLOWED_SECTIONS` in
backend.app, built from `summary.SECTION_LABELS` plus a hand-kept extras set. This test
stops that allowlist from drifting away from what the engine actually emits (a section
advertised but never produced = a dead / 404 tab -- the exact "months-dead NOS quartet"
bug class that motivated #8) and ties the webapp's axis-backed sections to the live
`_PER_DEVICE_AXES` registry (a renamed axis => a stale webapp tab).

Ground truth is the RICH sample the webapp ships and serves (`sample_fleet.snapshot.json`,
94 keys) -- NOT the older engine golden -- because that is the snapshot the section
endpoint slices in the demo, and it carries every always-on section (the golden is a
smaller, older fixture missing several).

Note: deriving SECTION_LABELS *literally* from the axis registry would be wrong -- it is
mostly COMPUTED-aggregate sections (punchlist, health_scores, causality, ...), not
per-device evidence axes. So this is a conformance PIN, not a runtime derivation; it adds
no import coupling to the running app.
"""
import json
import sys
from pathlib import Path

import pytest

_WEBAPP = Path(__file__).resolve().parents[1]
_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_WEBAPP), str(_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from backend import summary                 # noqa: E402
from backend.app import _ALLOWED_SECTIONS    # noqa: E402
import COLLECT_PARSE_V3_23_0 as cp           # noqa: E402

_RICH = _WEBAPP / "sample_data" / "sample_fleet.snapshot.json"

# The four OPT-IN engines appear in a snapshot only when a CLI flag supplies their input
# (--assert-pack / --path-intents / --import-inventory / --scenario), so the demo sample
# legitimately omits them; they are still valid fetchable sections. This mirrors the THREE
# transient-feed exemptions in tests/test_axis_registry.py -- the same coverage-honesty.
_OPT_IN_SECTIONS = {"state_assertions", "path_intents", "external_reconcile", "whatif"}

# The sections the webapp hard-codes as fetchable extras that ARE per-device axes (as
# opposed to computed aggregates / raw inventory). If any is renamed or removed in the
# registry, the webapp's hardcoded name goes stale -- caught by the registry test below.
_WEBAPP_AXIS_SECTIONS = {"security", "config_hygiene", "stp_roots", "routing_neighbors"}


def _rich_keys():
    if not _RICH.exists():
        pytest.skip(f"rich demo snapshot not present: {_RICH}")
    return set(json.load(open(_RICH, encoding="utf-8")).keys())


def test_no_advertised_section_is_a_phantom():
    """Every section the web UI will let a client fetch must actually be emitted by the
    engine -- otherwise the tab 404s. Checked against the rich demo snapshot, minus the
    opt-in engines that need a CLI flag to appear."""
    keys = _rich_keys()
    phantom = sorted((_ALLOWED_SECTIONS - _OPT_IN_SECTIONS) - keys)
    assert not phantom, (
        f"webapp _ALLOWED_SECTIONS advertises section(s) the engine never emits: {phantom}. "
        f"Either the section was renamed/removed in the engine (update the webapp allowlist), "
        f"or it is a new opt-in engine (add it to _OPT_IN_SECTIONS with its enabling flag).")


def test_opt_in_exemptions_are_really_absent_and_allowed():
    """Guard the guard: the opt-in exemptions must (a) be real advertised sections and
    (b) genuinely be the ones absent by default -- so the exemption set cannot rot into a
    blanket that hides a real phantom."""
    assert _OPT_IN_SECTIONS <= _ALLOWED_SECTIONS, (
        f"opt-in exemption names not in the allowlist: {sorted(_OPT_IN_SECTIONS - _ALLOWED_SECTIONS)}")
    leaked = sorted(_OPT_IN_SECTIONS & _rich_keys())
    assert not leaked, (
        f"exempted section(s) ARE present in the sample -- drop them from _OPT_IN_SECTIONS: {leaked}")


def test_webapp_axis_sections_are_live_registry_axes():
    """The webapp exposes a few per-device AXES directly (security, config_hygiene, ...).
    Tie each to the live _PER_DEVICE_AXES registry so an axis rename cannot silently leave
    a dead webapp tab pointing at a key the engine no longer produces."""
    axis_keys = {sp.key for sp in cp._PER_DEVICE_AXES}
    stale = sorted(_WEBAPP_AXIS_SECTIONS - axis_keys)
    assert not stale, (
        f"webapp advertises axis-backed section(s) absent from _PER_DEVICE_AXES: {stale}. "
        f"An axis was renamed/removed -- update backend.app._ALLOWED_SECTIONS to match.")
    assert _WEBAPP_AXIS_SECTIONS <= _ALLOWED_SECTIONS, (
        f"this test's axis-section list drifted from the webapp allowlist: "
        f"{sorted(_WEBAPP_AXIS_SECTIONS - _ALLOWED_SECTIONS)}")


def test_section_labels_hygiene():
    """SECTION_LABELS (the ordered UI tabs) must have unique keys, non-empty labels, and
    every key must be fetchable (present in _ALLOWED_SECTIONS)."""
    labels = summary.SECTION_LABELS
    keys = [k for k, _ in labels]
    dupes = sorted({k for k in keys if keys.count(k) > 1})
    assert not dupes, f"duplicate SECTION_LABELS keys: {dupes}"
    for k, lbl in labels:
        assert isinstance(k, str) and k, f"empty section key: {k!r}"
        assert isinstance(lbl, str) and lbl.strip(), f"section {k!r} has an empty label"
    not_fetchable = sorted(set(keys) - _ALLOWED_SECTIONS)
    assert not not_fetchable, (
        f"SECTION_LABELS advertises tab(s) the section endpoint would reject: {not_fetchable}")
