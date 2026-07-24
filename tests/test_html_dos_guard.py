"""[stored-availability DoS -- cisco_toolkit/html.py] A snapshot value that is a TRUTHY non-dict/non-list
must degrade, not raise, on every path the web layer reaches.

The bug class: a section is read as ``X.get("k") or {}`` / ``or []``. ``or`` catches only FALSY values, so a
truthy wrong-typed value (an int ``5``, a string) survives the guard and crashes the NEXT dereference --
``.items()``, ``.get()``, ``len()``, iteration, slicing, ``set()``. Three granularities are covered here:

  * G1 SECTION      -- ``snap["health_scores"] = 5``            -> ``for r in 5``
  * G2 ROW-INNER    -- a well-formed row holding a scalar        -> ``finding["devices"] = 5``
  * G3 PER-ELEMENT  -- a core map whose element is a scalar      -> ``interfaces = {"sw1": 5}``

Why it is a STORED DoS rather than a one-shot error: AssessHub accepts the upload -- the only validation is
``isinstance(snap, dict) and "devices" in snap`` (webapp/backend/app.py) -- and stores it verbatim; the entry
sanitizer ``textutils.xml_safe_deep`` passes int/float/bool/None through unchanged. ``html.py`` is then reached
via ``webapp/backend/engine.py`` on THREE routes that carry NO ``try`` wrapper, so a raise becomes an unhandled
HTTP 500 on every later read:

  * ``GET  /api/snapshots/{id}/explorer``   -> ``write_html_explorer`` -> ``_slim_for_embed``
  * ``POST /api/compare``                   -> ``compute_snapshot_delta``
  * ``GET  /api/campaigns/{id}/trend``      -> ``compute_campaign_trend`` (which re-enters
    ``compute_snapshot_delta`` per consecutive pair and ``_trend_point`` per snapshot)

One poisoned upload therefore knocks out the explorer / diff / trend for that snapshot -- and, for the trend,
for the whole CAMPAIGN it sits in -- permanently.

The fix routes each read through an isinstance coercion (``_as_dict`` / the new ``_as_list`` / ``str(...)``),
the module's own existing discipline: ``sparsify_interfaces`` and ``_trend_point._d()`` already do exactly this;
the sites guarded here were simply missed. ``_as_list(x)`` is IDENTICAL to ``(x or [])`` for every list/None
input, so well-formed output is unchanged -- pinned by the ``*_well_formed_*`` tests below.

Non-vacuity: EVERY malformed case in this file raises (unit) / 500s (route) against the pre-fix module. Proven
by dumping ``git show origin/main:cisco_toolkit/html.py`` and importing it via importlib -- all 13 unit cases
raise, all 11 route cases return 500.
"""
import json

import pytest

from cisco_toolkit.html import (_slim_for_embed, _trend_point, compute_campaign_trend,
                                compute_snapshot_delta, write_html_explorer)

# --------------------------------------------------------------------------------------------------
# Fixtures -- well-typed literals, exactly like tests/test_snapshot_delta.py::_snap and
# tests/test_campaign_trend.py::_snap. Each test poisons ONE value, so a survival is attributable.
# --------------------------------------------------------------------------------------------------


def _snap(**over) -> dict:
    """A minimal well-formed snapshot; keyword args replace one section with the poison."""
    snap = {
        "devices": {"sw1": {"hostname": "sw1"}},
        "interfaces": {"sw1": {"Gi1/0/1": {"status": "connected", "vlan": "10"}}},
        "health_scores": [{"switch": "sw1", "band": "Good", "score": 80}],
        "punchlist": [{"severity": "High", "category": "STP", "title": "Accidental root",
                       "devices": ["sw1"]}],
        "generated_at": "2026-01-01T00:00:00",
        "script_version": "V3.23.0",
        "executive_brief": {"scale": {"n_devices": 1}, "posture": {"avg_health": 80}},
        "lifecycle_risk": {"summary": {"n_past_ldos": 0, "n_past_eos": 0}},
        "migration_readiness": [{"readiness": "READY", "switches": ["sw1"]}],
    }
    snap.update(over)
    return snap


# (poison snapshot, site, why) -- the DELTA sites, reached by BOTH /api/compare and /trend.
_DELTA_POISON = [
    (_snap(health_scores=5), "html.py:94",
     "G1 (old.get('health_scores') or []) -- `for r in 5` -> TypeError"),
    (_snap(punchlist=5), "html.py:125",
     "G1 (old.get('punchlist') or []) -- `for f in 5` -> TypeError"),
    (_snap(punchlist=[{"severity": "High", "category": "STP", "title": "T", "devices": 5}]),
     "html.py:71",
     "G2 _finding_key -- a well-formed finding row whose 'devices' is a scalar -> `for d in 5`"),
    (_snap(executive_brief=5), "html.py:207",
     "G1 _scn -- (s.get('executive_brief') or {}).get(...) on a truthy non-dict -> AttributeError"),
    (_snap(executive_brief={"scale": 5}), "html.py:207",
     "G2 _scn -- the INNER 'scale' subsection is a scalar -> AttributeError"),
    (_snap(interfaces={"sw1": 5}), "html.py:211",
     "G3 -- interfaces IS _as_dict-coerced, but a per-host element scalar hits len(5) -> TypeError"),
]
_DELTA_IDS = ["health_scores_int", "punchlist_int", "finding_devices_int",
              "executive_brief_int", "brief_scale_int", "interfaces_element_int"]


# --------------------------------------------------------------------------------------------------
# UNIT -- _slim_for_embed (the explorer route's only html.py-side crash surface)
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("intf, why", [
    ({"sw1": {"Gi1/0/1": 5}}, "html.py:827 -- (rec or {}).items() on a truthy non-dict port record"),
    ({"sw1": 5}, "html.py:828 -- (ports or {}).items() on a truthy non-dict per-host map"),
    ({"sw1": {"Gi1/0/1": "up"}}, "a STRING port record -- truthy, .items() still absent"),
], ids=["port_record_int", "host_map_int", "port_record_str"])
def test_slim_for_embed_survives_per_element_scalar(intf, why):
    out = _slim_for_embed({"devices": {"sw1": {}}, "interfaces": intf})
    assert isinstance(out["interfaces"], dict), why
    # degrade, never invent: the malformed subtree collapses to an empty mapping, it is not fabricated
    assert all(isinstance(v, dict) for v in out["interfaces"].values()), why
    json.dumps(out)          # the explorer embeds this verbatim -- it must stay serializable


def test_slim_for_embed_well_formed_output_unchanged():
    """The guard must be display-neutral: a well-formed interfaces subtree slims EXACTLY as before
    (empty/placeholder field values dropped, port entries kept)."""
    snap = {"devices": {"sw1": {}},
            "interfaces": {"sw1": {"Gi1/0/1": {"status": "connected", "vlan": "10", "svi_ip": "",
                                               "port_channel": "--", "descr": None,
                                               "macs": [], "extra": {}}}},
            "physical_health": [{"severity": "Info", "msg": "x"}, {"severity": "High", "msg": "y"}]}
    out = _slim_for_embed(snap)
    assert out["interfaces"] == {"sw1": {"Gi1/0/1": {"status": "connected", "vlan": "10"}}}
    assert out["physical_health"] == [{"severity": "High", "msg": "y"}]


def test_write_html_explorer_survives_poisoned_interfaces(tmp_path):
    """End of the explorer chain: the file is still written (a 500 here is the /explorer route's 500)."""
    out = tmp_path / "explorer.html"
    write_html_explorer(str(out), {"devices": {"sw1": {}}, "interfaces": {"sw1": 5}}, "poison")
    assert out.exists() and "EMBEDDED_SNAPSHOT" in out.read_text(encoding="utf-8")


# --------------------------------------------------------------------------------------------------
# UNIT -- compute_snapshot_delta
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("poison, site, why", _DELTA_POISON, ids=_DELTA_IDS)
def test_delta_survives_poison_in_old(poison, site, why):
    d = compute_snapshot_delta(poison, _snap())
    assert d["verdict"] in ("CLEAN", "REVIEW", "REGRESSED"), f"{site} -- {why}"


@pytest.mark.parametrize("poison, site, why", _DELTA_POISON, ids=_DELTA_IDS)
def test_delta_survives_poison_in_new(poison, site, why):
    """Both operands must be guarded -- html.py:95 / :126 are the `new` twins of :94 / :125, and a fix
    applied to only one side leaves the other reachable from the same route."""
    d = compute_snapshot_delta(_snap(), poison)
    assert d["verdict"] in ("CLEAN", "REVIEW", "REGRESSED"), f"{site} -- {why}"


def test_delta_well_formed_result_unchanged():
    """Behaviour pin: the coercions are no-ops on well-typed input. Values chosen so every guarded
    site contributes -- switches (:207 _scn), interfaces (:211), health (:94/:95), findings
    (:125/:126 + :71 device-set keying)."""
    old = _snap()
    new = _snap(health_scores=[{"switch": "sw1", "band": "Poor", "score": 55}],
                punchlist=[{"severity": "High", "category": "STP", "title": "Accidental root",
                            "devices": ["sw1"]},
                           {"severity": "Critical", "category": "FHRP", "title": "Fake redundancy",
                            "devices": ["sw1"]}])
    d = compute_snapshot_delta(old, new)
    assert d["switches"] == {"old": 1, "new": 1, "added": [], "removed": []}
    assert d["interfaces"] == {"old": 1, "new": 1}
    assert d["health"]["n_regressed"] == 1 and d["health"]["n_improved"] == 0
    assert d["health"]["regressed"][0] == {"switch": "sw1", "old_band": "Good", "new_band": "Poor",
                                           "old_score": 80, "new_score": 55}
    assert d["findings"]["n_opened"] == 1 and d["findings"]["n_resolved"] == 0
    assert d["findings"]["opened"][0]["title"] == "Fake redundancy"
    assert d["findings"]["n_opened_high"] == 1
    assert d["verdict"] == "REGRESSED"


def test_delta_scn_still_prefers_the_canonical_scale():
    """SSOT pin: _scn reads executive_brief.scale.n_devices and only falls back to len(devices)."""
    a = _snap(devices={"sw1": {}}, executive_brief={"scale": {"n_devices": 303}})
    b = _snap(devices={"sw1": {}}, executive_brief={})
    d = compute_snapshot_delta(a, b)
    assert d["switches"]["old"] == 303           # canonical count wins over len(devices)==1
    assert d["switches"]["new"] == 1             # no brief -> len() fallback, unchanged


def test_delta_finding_devices_list_still_keys_the_finding():
    """_finding_key must still see a well-formed device LIST (order-normalized), so the coercion did
    not silently blank the device-set component of the key."""
    old = _snap(punchlist=[{"severity": "High", "category": "X", "title": "T", "devices": ["b", "a"]}])
    new = _snap(punchlist=[{"severity": "High", "category": "X", "title": "T", "devices": ["a", "b"]}])
    assert compute_snapshot_delta(old, new)["findings"]["n_opened"] == 0
    other = _snap(punchlist=[{"severity": "High", "category": "X", "title": "T", "devices": ["c"]}])
    assert compute_snapshot_delta(old, other)["findings"]["n_opened"] == 1


# --------------------------------------------------------------------------------------------------
# UNIT -- _trend_point / compute_campaign_trend
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("ts", [5, 5.5, True, {"a": 1}, ["2026-01-01"]],
                         ids=["int", "float", "bool", "dict", "list"])
def test_trend_point_survives_non_string_generated_at(ts):
    """html.py:572/:574 -- the SLICING variant: `ts[:10]` on a truthy non-str. int/dict are not
    subscriptable at all; a LIST slices to a list, which then poisons the timeline's 'date' column."""
    p = _trend_point(_snap(generated_at=ts))
    assert isinstance(p["date"], str) and isinstance(p["generated_at"], str)


def test_trend_point_well_formed_output_unchanged():
    p = _trend_point(_snap())
    assert p["date"] == "2026-01-01" and p["generated_at"] == "2026-01-01T00:00:00"
    assert p["n_switches"] == 1 and p["avg_health"] == 80 and p["n_punchlist"] == 1
    assert p["n_crit_high"] == 1 and p["n_not_ready"] == 0 and p["past_ldos"] == 0
    # falsy generated_at keeps degrading to '' exactly as before
    assert _trend_point(_snap(generated_at=None))["date"] == ""


@pytest.mark.parametrize("poison, site, why", [
    (_snap(health_scores=5), "html.py:637",
     "G1 _bands -- (s.get('health_scores') or []) iterated for the went-dark band scan"),
    (_snap(devices=5), "html.py:640",
     "G1 -- set(snaps[i].get('devices') or {}) on a truthy non-iterable -> TypeError"),
    (_snap(generated_at=5), "html.py:572/:574", "G1 slicing -- `5[:10]`"),
], ids=["bands_health_scores_int", "devices_int", "generated_at_int"])
def test_campaign_trend_survives_poison(poison, site, why):
    """Needs >= 2 snapshots: the went-dark scan at :637/:640 sits under `if len(timeline) >= 2`."""
    t = compute_campaign_trend([poison, _snap(generated_at="2026-02-01T00:00:00")])
    assert t["verdict"] in ("IMPROVING", "MIXED", "REGRESSING", "FLAT", "INSUFFICIENT"), f"{site} -- {why}"
    assert len(t["timeline"]) == 2, f"{site} -- {why}"


def test_campaign_trend_string_devices_does_not_fabricate_dark_devices():
    """html.py:640, the non-crashing half of the same bug: a STRING `devices` IS iterable, so
    `set("sw1")` succeeds and yields the CHARACTERS -- the went-dark scan then reports 3 phantom devices
    gone and downgrades the verdict on evidence that does not exist. Coercing kills the false positive
    as well as the crash."""
    t = compute_campaign_trend([_snap(devices="sw1"),
                                _snap(generated_at="2026-02-01T00:00:00")])
    assert "went DARK" not in t["verdict_note"]


def test_campaign_trend_well_formed_trajectory_unchanged():
    """Behaviour pin over the guarded trend sites: a genuinely improving campaign still reads
    IMPROVING with the same per-metric directions, and the went-dark disclosure still fires."""
    c1 = _snap(generated_at="2026-01-01T00:00:00",
               devices={"sw1": {}, "sw2": {}},
               health_scores=[{"switch": "sw1", "band": "Critical", "score": 20},
                              {"switch": "sw2", "band": "Fair", "score": 60}],
               executive_brief={"posture": {"avg_health": 40, "n_critical": 1}},
               punchlist=[{"severity": "Critical", "category": "X", "title": "A", "devices": ["sw1"]},
                          {"severity": "Low", "category": "X", "title": "B", "devices": ["sw1"]}])
    c2 = _snap(generated_at="2026-02-01T00:00:00",
               devices={"sw1": {}, "sw2": {}},
               health_scores=[{"switch": "sw1", "band": "Good", "score": 80},
                              {"switch": "sw2", "band": "Good", "score": 82}],
               executive_brief={"posture": {"avg_health": 81, "n_critical": 0}},
               punchlist=[{"severity": "Low", "category": "X", "title": "B", "devices": ["sw1"]}])
    t = compute_campaign_trend([c1, c2])
    assert t["verdict"] == "IMPROVING"
    dirs = {r["metric"]: r["direction"] for r in t["trajectory"]}
    assert dirs["Avg health / 100"] == "improving"
    assert dirs["Critical-band switches"] == "improving"
    assert dirs["Punch-list items"] == "improving"
    assert t["steps"][0]["resolved"] == 1 and t["steps"][0]["opened"] == 0
    assert [p["date"] for p in t["timeline"]] == ["2026-01-01", "2026-02-01"]


def test_campaign_trend_still_discloses_devices_that_went_dark():
    """The :640 set-difference is a FALSE-HEALTH guard (survivorship bias), not decoration -- coercing it
    must not stop it detecting a device that dropped out of the fleet."""
    c1 = _snap(generated_at="2026-01-01T00:00:00",
               devices={"sw1": {}, "sw2": {}},
               health_scores=[{"switch": "sw1", "band": "Critical", "score": 20},
                              {"switch": "sw2", "band": "Good", "score": 80}],
               executive_brief={"posture": {"avg_health": 50}})
    c2 = _snap(generated_at="2026-02-01T00:00:00",
               devices={"sw2": {}},                       # sw1 (the worst box) vanished
               health_scores=[{"switch": "sw2", "band": "Good", "score": 80}],
               executive_brief={"posture": {"avg_health": 80}})
    t = compute_campaign_trend([c1, c2])
    assert "1 device(s) went DARK" in t["verdict_note"]
    assert t["verdict"] == "MIXED"        # a lost device can never read as a clean IMPROVING


# --------------------------------------------------------------------------------------------------
# E2E -- the three unwrapped AssessHub routes. A raise inside html.py becomes an unhandled HTTP 500,
# so the unit tests above are only half the proof: these pin the real client-visible outcome.
# --------------------------------------------------------------------------------------------------

pytest.importorskip("fastapi", reason="web layer deps absent (engine-only env) -- mirrors webapp/tests/conftest.py")
pytest.importorskip("httpx", reason="web layer deps absent (engine-only env) -- mirrors webapp/tests/conftest.py")

from fastapi.testclient import TestClient           # noqa: E402  (after the importorskip guard)

from webapp.backend.app import create_app           # noqa: E402


@pytest.fixture()
def client(tmp_path):
    app = create_app(db_path=str(tmp_path / "test.db"))
    # base_url=localhost so the default Host passes the no-token DNS-rebinding guard (app.py
    # _request_host_allowed); raise_server_exceptions=False so a stored DoS surfaces as the 500
    # RESPONSE a real client sees rather than a re-raised traceback.
    with TestClient(app, base_url="http://localhost", raise_server_exceptions=False) as c:
        yield c


def _campaign(client) -> int:
    r = client.post("/api/campaigns", json={"name": "dos"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _upload(client, cid: int, snap: dict) -> int:
    """The poison must be ACCEPTED (201) -- that is what makes this a STORED DoS. A 400 here would be a
    different, safer outcome and would make the read-route assertion vacuous."""
    r = client.post(f"/api/campaigns/{cid}/snapshots",
                    files={"file": ("s.json", json.dumps(snap).encode(), "application/json")},
                    data={"label": "s"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.mark.parametrize("snap, why", [
    ({"devices": {"sw1": {}}, "interfaces": {"sw1": 5}},
     "html.py:828 -- (ports or {}).items() on a truthy non-dict per-host map"),
    ({"devices": {"sw1": {}}, "interfaces": {"sw1": {"Gi1/0/1": 5}}},
     "html.py:827 -- (rec or {}).items() on a truthy non-dict port record"),
], ids=["host_map_int", "port_record_int"])
def test_explorer_route_survives_poisoned_interfaces(client, snap, why):
    sid = _upload(client, _campaign(client), snap)
    r = client.get(f"/api/snapshots/{sid}/explorer")
    assert r.status_code == 200, f"{why}\n{r.text[:400]}"
    assert "EMBEDDED_SNAPSHOT" in r.text


@pytest.mark.parametrize("poison, site, why", _DELTA_POISON, ids=_DELTA_IDS)
def test_compare_route_survives_poison(client, poison, site, why):
    cid = _campaign(client)
    good_id = _upload(client, cid, _snap())
    bad_id = _upload(client, cid, poison)
    for old, new in ((good_id, bad_id), (bad_id, good_id)):   # both operands, both directions
        r = client.post("/api/compare", json={"old_id": old, "new_id": new})
        assert r.status_code == 200, f"{site} -- {why}\n{r.text[:400]}"
        assert r.json()["verdict"] in ("CLEAN", "REVIEW", "REGRESSED")


@pytest.mark.parametrize("poison, site, why", [
    ({"devices": {"sw1": {}}, "generated_at": 5}, "html.py:572/:574", "`5[:10]` -> TypeError"),
    ({"devices": {"sw1": {}}, "health_scores": 5}, "html.py:637/:94", "_bands + the delta re-entry"),
    ({"devices": 5}, "html.py:640", "set(5) -> TypeError"),
    ({"devices": {"sw1": {}}, "punchlist": 5}, "html.py:125", "the trend's per-pair delta re-entry"),
    ({"devices": {"sw1": {}}, "executive_brief": {"scale": 5}}, "html.py:207", "inner scale scalar"),
], ids=["generated_at_int", "health_scores_int", "devices_int", "punchlist_int", "brief_scale_int"])
def test_trend_route_survives_poison(client, poison, site, why):
    """The trend needs >= 2 snapshots in the campaign to reach the went-dark scan, and it re-enters
    compute_snapshot_delta per consecutive pair -- so this route reaches the delta sites too."""
    cid = _campaign(client)
    _upload(client, cid, poison)
    _upload(client, cid, _snap(generated_at="2026-02-01T00:00:00"))
    r = client.get(f"/api/campaigns/{cid}/trend")
    assert r.status_code == 200, f"{site} -- {why}\n{r.text[:400]}"
    body = r.json()
    assert len(body["timeline"]) == 2 and "verdict" in body


def test_routes_still_serve_a_well_formed_snapshot(client):
    """Regression through the real routes: nothing about the well-formed path changed."""
    cid = _campaign(client)
    a = _upload(client, cid, _snap())
    b = _upload(client, cid, _snap(generated_at="2026-02-01T00:00:00",
                                   health_scores=[{"switch": "sw1", "band": "Poor", "score": 55}]))
    assert client.get(f"/api/snapshots/{a}/explorer").status_code == 200
    cmp_body = client.post("/api/compare", json={"old_id": a, "new_id": b}).json()
    assert cmp_body["verdict"] == "REGRESSED" and cmp_body["health"]["n_regressed"] == 1
    trend = client.get(f"/api/campaigns/{cid}/trend").json()
    assert [p["date"] for p in trend["timeline"]] == ["2026-01-01", "2026-02-01"]
