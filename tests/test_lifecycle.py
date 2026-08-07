"""Deterministic hardware lifecycle lookup and risk-band tests."""

import json

from cisco_toolkit import eoldb
from cisco_toolkit.analyze import compute_executive_brief, compute_lifecycle_risk

ASOF = "2026-06-07"


def test_eoldb_bounded_family_and_exact_matching():
    assert eoldb.lifecycle_for("WS-C4948E-F")["platform"] == "Catalyst 4948E"
    assert eoldb.lifecycle_for("WS-C4948")["platform"] == "Catalyst 4948"
    assert eoldb.lifecycle_for("N5K-C5596UP")["platform"] == "Nexus 5500"
    assert eoldb.lifecycle_for("WS-C4948-10GE") is None
    assert eoldb.lifecycle_for("N5K-C56128P") is None
    assert eoldb.lifecycle_for("C9300-48T") is None
    assert eoldb.lifecycle_for("N9K-C93180YC-EX") is None
    assert eoldb.lifecycle_for("") is None
    assert eoldb.lifecycle_for("TOTALLY-MADE-UP") is None


def _dev(model, sw="x"):
    return {"sw1": {"model": model, "sw_version": sw}}


def test_bands_use_bulletin_dates_and_unknown_means_abstention():
    def band(model):
        return compute_lifecycle_risk(_dev(model), asof=ASOF)["per_device"][0][
            "band"
        ]

    assert band("WS-C4948E-F") == "Past-LDoS"
    assert band("WS-C3650-48P") == "Near-LDoS"
    assert band("C9300-48T") == "Unknown"
    assert band("WS-C2960X-48FPD-L") == "Past-EoS"
    assert band("WeirdModel-X") == "Unknown"


def test_confirmed_tag_and_status_string():
    result = compute_lifecycle_risk(_dev("WS-C4948E-F"), asof=ASOF)[
        "per_device"
    ][0]
    assert result["conf"] == "confirmed"
    assert "Past end-of-support" in result["status"]
    assert result["source"]
    assert result["ldos"] == "2022-10-31"


def test_risks_and_summary_rollup():
    devices = {
        "a": {"model": "WS-C4948E-F"},
        "b": {"model": "WS-C3650-48P"},
        "c": {"model": "C9300-48T"},
        "d": {"model": ""},
    }
    output = compute_lifecycle_risk(devices, asof=ASOF)
    summary = output["summary"]
    assert summary["n_devices"] == 4
    assert (
        summary["n_past_ldos"],
        summary["n_near"],
        summary["n_active"],
        summary["n_unknown"],
    ) == (1, 1, 0, 2)
    kinds = {risk["severity"]: risk for risk in output["risks"]}
    assert kinds["Critical"]["devices"] == ["a"]
    assert kinds["High"]["devices"] == ["b"]
    assert output["asof"] == ASOF and output["note"]
    assert summary["by_platform"][0]["band"] == "Past-LDoS"


def test_uncovered_family_is_unknown_not_healthy():
    output = compute_lifecycle_risk(_dev("C9300-48T"), asof=ASOF)
    row = output["per_device"][0]
    assert row["citation_status"] == "missing"
    assert row["band"] == "Unknown"
    assert "No retained Cisco EoX bulletin match" in row["status"]
    assert "support state undetermined" in row["status"]
    assert output["summary"]["n_active"] == 0
    assert output["summary"]["n_unknown"] == 1


def test_active_band_is_date_position_not_a_negative_eol_or_entitlement_claim():
    """The public ``Active`` band name is retained for schema compatibility, but the row must say
    only what the bulletin dates establish. A future LDoS does not prove support entitlement, and
    an unmatched negative search never proves that Cisco has announced no EoL."""
    output = compute_lifecycle_risk(_dev("WS-C2960X-48FPD-L"), asof="2021-01-01")
    row = output["per_device"][0]
    assert row["band"] == "Active"
    assert "EoS not yet passed as of assessment" in row["status"]
    assert "support entitlement not assessed" in row["status"]
    assert "no end-of-life announced" not in row["status"].lower()
    assert "in support" not in row["status"].lower()


def test_legacy_incomplete_or_nonconfirmed_row_abstains(monkeypatch):
    """A legacy ``conf=active`` row once reached an impossible ``bulletin-id`` branch and could
    manufacture 'no EoL announced'. The current KB forbids such rows; the consumer also abstains
    defensively if one is ever returned across that boundary."""
    legacy = {
        "platform": "Legacy family",
        "eos": "",
        "ldos": "",
        "source": "",
        "conf": "active",
        "matched_pattern": "LEGACY-",
        "match_kind": "family-prefix",
        "reviewed_at": eoldb._EOL_REVIEWED,
        "citation_status": "retained-primary-fixture",
        "source_authoritative": True,
    }
    monkeypatch.setattr(eoldb, "lifecycle_for", lambda _model: dict(legacy))
    output = compute_lifecycle_risk(_dev("LEGACY-1"), asof=ASOF)
    row = output["per_device"][0]
    assert row["band"] == "Unknown"
    assert "support state undetermined" in row["status"]
    assert "no end-of-life announced" not in row["status"].lower()
    assert output["summary"]["n_active"] == 0
    assert output["risks"][0]["evidence_confidence"] == "not-assessed"


def test_unverified_retained_source_chain_withholds_a_dated_band(monkeypatch):
    """The inline row can still be returned when retained fixture verification fails. Its citation
    diagnostics remain visible, but its unverified dates must neither publish nor drive a band/risk."""
    cited = eoldb.lifecycle_for("WS-C4948E-F")
    assert cited and cited["source_authoritative"] is True
    cited["source_authoritative"] = False
    cited["citation_status"] = "primary-url-unverified"
    monkeypatch.setattr(eoldb, "lifecycle_for", lambda _model: dict(cited))

    output = compute_lifecycle_risk(_dev("WS-C4948E-F"), asof=ASOF)
    row = output["per_device"][0]
    assert row["band"] == "Unknown"
    assert row["eos"] == "" and row["ldos"] == ""
    assert row["citation_status"] == "primary-url-unverified"
    assert "lifecycle band withheld" in row["status"]
    assert output["summary"]["n_past_ldos"] == 0
    assert output["summary"]["n_unknown"] == 1
    assert output["summary"]["by_platform"][0]["ldos"] == ""
    assert [risk["evidence_confidence"] for risk in output["risks"]] == ["not-assessed"]
    assert "matched an offline row whose source authority" in output["risks"][0]["detail"]
    assert "no retained exact Cisco EoX bulletin match" not in output["risks"][0]["detail"]


def test_lifecycle_note_discloses_bulletin_dates_are_not_generically_derived():
    note = compute_lifecycle_risk(_dev("WS-C4948E-F"), asof=ASOF)["note"]
    assert "no lifecycle date is derived from a generic support-window rule" in note
    assert "only when the retained source chain verifies" in note
    assert "often derived" not in note
    assert "+ 5yr" not in note


def test_confirmed_dates_can_create_a_critical_past_support_risk():
    output = compute_lifecycle_risk(_dev("WS-C4948E-F"), asof=ASOF)
    assert output["risks"]
    assert output["risks"][0]["severity"] == "Critical"
    assert output["risks"][0]["evidence_confidence"] == "confirmed"
    assert output["kb_reviewed_at"] == eoldb._EOL_REVIEWED


def test_past_eos_creates_a_medium_refresh_risk_without_inferring_entitlement():
    output = compute_lifecycle_risk(_dev("WS-C2960X-48FPD-L"), asof=ASOF)
    assert output["summary"]["n_past_eos"] == 1
    assert [risk["severity"] for risk in output["risks"]] == ["Medium"]
    risk = output["risks"][0]
    assert "LDoS still future" in risk["title"]
    assert "does not establish" in risk["remediation"]
    assert "entitlement" in risk["remediation"]


def test_lifecycle_risk_rows_follow_canonical_urgency_order():
    output = compute_lifecycle_risk(
        {
            "ldos": {"model": "WS-C4948E-F"},
            "near": {"model": "WS-C3650-48P"},
            "eos": {"model": "WS-C2960X-48FPD-L"},
            "unknown": {"model": "TOTALLY-MADE-UP"},
        },
        asof=ASOF,
    )
    assert [risk["severity"] for risk in output["risks"]] == [
        "Critical", "High", "Medium", "Medium"
    ]
    assert output["risks"][2]["title"].startswith("Hardware past end-of-sale")
    assert output["risks"][3]["evidence_confidence"] == "not-assessed"


def test_empty_and_deterministic():
    assert compute_lifecycle_risk(None)["per_device"] == []
    assert compute_lifecycle_risk({})["summary"]["n_devices"] == 0
    first = compute_lifecycle_risk(_dev("WS-C4948E-F"), asof=ASOF)
    second = compute_lifecycle_risk(_dev("WS-C4948E-F"), asof=ASOF)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_broad_6500_claims_abstain_without_an_exact_bulletin_scope():
    for pid in (
        "WS-C6503-E",
        "WS-C6504-E",
        "WS-C6506-E",
        "WS-C6509-E",
        "WS-C6509-V-E",
        "WS-C6513-E",
    ):
        assert eoldb.lifecycle_for(pid) is None
    output = compute_lifecycle_risk(
        {"core6500": {"model": "WS-C6509-V-E", "sw_version": "15.1(2)SY"}},
        asof=ASOF,
    )
    assert output["per_device"][0]["band"] == "Unknown"
    assert output["summary"]["n_past_ldos"] == 0


def test_compact_and_nexus_scope_collisions_are_coverage_honest():
    selected = eoldb.lifecycle_for("WS-C3560CX-12PC-S")
    assert selected["platform"] == "Catalyst 3560-CX (selected models)"
    assert selected["match_kind"] == "exact"
    assert eoldb.lifecycle_for("WS-C3560CX-8XPD-S") is None
    assert eoldb.lifecycle_for("WS-C2960CX-8PC-L") is None
    assert eoldb.lifecycle_for("N3K-C3048TP-1GE")["platform"] == "Nexus 3048"
    assert eoldb.lifecycle_for("N3K-C3064-X")["platform"] == "Nexus 3064-X"
    assert eoldb.lifecycle_for("N3K-C3064-T") is None

    output = compute_lifecycle_risk(
        {
            "a": {"model": "WS-C3560CX-12PC-S"},
            "b": {"model": "WS-C2960CX-8PC-L"},
            "c": {"model": "N3K-C3048TP-1GE"},
        },
        asof=ASOF,
    )
    bands = {device["host"]: device["band"] for device in output["per_device"]}
    assert bands == {"a": "Past-EoS", "b": "Unknown", "c": "Past-LDoS"}


def test_unbanded_platforms_raise_a_coverage_risk_instead_of_an_empty_risk_list():
    """An empty `risks` list read as "no lifecycle risk" on a fleet nothing could be banded on.

    `risks` was built by looping over the two ADVERSE bands only (Past-LDoS, Near-LDoS). A fleet whose
    platforms matched no EoX bulletin therefore produced `risks == []`, and every downstream consumer --
    punch-list, workbook, explorer -- renders an empty risk list as a clean lifecycle posture. The
    support state was never determined, which is not determined-to-be-fine.
    """
    out = compute_lifecycle_risk({"sw1": {"model": "TOTALLY-MADE-UP", "sw_version": "x"},
                                  "sw2": {"model": "C9300-48T", "sw_version": "x"}}, asof=ASOF)
    assert out["summary"]["n_unknown"] == 2
    assert out["risks"], "an all-unbanded fleet produced no lifecycle risk at all"
    r = out["risks"][0]
    assert r["evidence_confidence"] == "not-assessed"
    assert r["devices"] == ["sw1", "sw2"] and r["severity"] == "Medium", r
    # NOT Critical: nothing observed says these are out of support, only that we cannot say they are in it.
    assert r["severity"] != "Critical"


def test_coverage_risk_never_outranks_a_real_end_of_support_finding():
    """Non-vacuity + ordering: a genuine Past-LDoS device must still lead, and a fully-banded fleet
    must NOT gain a coverage risk -- otherwise the new entry is always-on and proves nothing."""
    mixed = compute_lifecycle_risk({"sw1": {"model": "WS-C4948E-F", "sw_version": "x"},
                                    "sw2": {"model": "TOTALLY-MADE-UP", "sw_version": "x"}}, asof=ASOF)
    assert [r["severity"] for r in mixed["risks"]] == ["Critical", "Medium"]
    assert mixed["risks"][1]["devices"] == ["sw2"], "the coverage risk absorbed the real finding"

    banded = compute_lifecycle_risk(_dev("WS-C4948E-F"), asof=ASOF)
    assert banded["summary"]["n_unknown"] == 0
    assert all(r["evidence_confidence"] != "not-assessed" for r in banded["risks"]), \
        "a fully-banded fleet gained a spurious coverage risk"


# ------------------------------------------------------- the coverage risk names the platforms it means
def test_coverage_risk_detail_never_renders_a_blank_where_the_platforms_belong():
    """The detail joined `per_device[].platform`, which is "" for EXACTLY the devices this risk is
    about (no EoX bulletin matched, so there is no bulletin platform family to name). It rendered
    "2 device(s) on  could not be matched" -- a blank where the platform list belongs, in the one
    sentence that tells the engineer WHAT to resolve on Cisco's EoX portal."""
    out = compute_lifecycle_risk({"sw1": {"model": "TOTALLY-MADE-UP", "sw_version": "x"},
                                  "sw2": {"model": "ALSO-MADE-UP", "sw_version": "x"}}, asof=ASOF)
    cov = next(r for r in out["risks"] if r["evidence_confidence"] == "not-assessed")
    assert "device(s) on  could" not in cov["detail"], f"blank platform list: {cov['detail']!r}"
    assert "TOTALLY-MADE-UP" in cov["detail"] and "ALSO-MADE-UP" in cov["detail"], cov["detail"]

    # NON-VACUITY: a device with no model string at all must say so explicitly rather than print
    # nothing -- the fallback must not become a second silent blank.
    out2 = compute_lifecycle_risk({"sw9": {"model": "", "sw_version": ""}}, asof=ASOF)
    cov2 = next(r for r in out2["risks"] if r["evidence_confidence"] == "not-assessed")
    assert "device(s) on  could" not in cov2["detail"], cov2["detail"]
    assert "not collected" in cov2["detail"] or "(unknown)" in cov2["detail"], cov2["detail"]


# --------------------------------------------- the EoL axis severity is a COVERAGE claim, not a finding
def _eol_axis(**lc_summary):
    """The executive brief's Hardware-lifecycle axis for a fleet with these band counts."""
    b = compute_executive_brief(health_scores=[{"band": "Good", "score": 85}],
                                lifecycle_risk={"summary": dict(n_devices=10, **lc_summary)})
    return b, next(a for a in b["axes"] if a["axis"] == "Hardware lifecycle (EoL)")


def test_eol_axis_severity_does_not_go_green_on_a_partly_unassessed_fleet():
    """`"Info" if not lc_known else "Low"` made the CLEAN-FLEET severity return the instant ONE device
    became bandable.

    Measured before the fix: 2 Active / 8 Unknown scored "Low" -- byte-identical to a fully verified
    fleet -- while an all-Unknown fleet correctly scored "Info". Severity is the machine-readable
    field: it drives the axis colour, the `_APP_SEV_RANK` sort and `top_gating`. The headline TEXT
    disclosed the 8; the severity contradicted it. `Low` must require COMPLETE coverage.
    """
    _b, partial = _eol_axis(n_unknown=8, n_active=2)
    assert partial["severity"] == "Info", (
        f"an 80%-unassessed fleet took the clean-fleet severity: {partial}")
    _b, none_assessed = _eol_axis(n_unknown=10)
    assert none_assessed["severity"] == "Info", none_assessed

    # NON-VACUITY (both directions):
    #  - a genuinely complete, clean fleet must KEEP the green value, or the guard is always-on;
    _b, clean = _eol_axis(n_unknown=0, n_active=10)
    assert clean["severity"] == "Low", f"a fully-assessed clean fleet lost its clean severity: {clean}"
    #  - a real adverse finding must still outrank the coverage value, or the fix buries findings.
    _b, bad = _eol_axis(n_unknown=8, n_past_ldos=2)
    assert bad["severity"] == "Critical", bad
    _b, near = _eol_axis(n_unknown=8, n_near=2)
    assert near["severity"] == "High", near


def test_posture_statement_does_not_say_no_blockers_for_an_unassessed_fleet():
    """`posture_statement` read only n_past_ldos/n_near, so an 89%-unassessed fleet produced
    "no top-tier blockers flagged across the assessed axes - proceed with the standard wave plan"
    -- the posture headline of every deliverable, on a fleet whose hardware support state is unknown."""
    b, _ax = _eol_axis(n_unknown=8, n_active=2)
    ps = b["posture_statement"]
    assert "no top-tier blockers" not in ps, ps
    assert "UNDETERMINED" in ps and "8 device(s)" in ps, ps

    # NON-VACUITY: a fully-assessed clean fleet must keep the clean sentence.
    b2, _ax2 = _eol_axis(n_unknown=0, n_active=10)
    assert "no top-tier blockers" in b2["posture_statement"], b2["posture_statement"]
    assert "UNDETERMINED" not in b2["posture_statement"]


def test_the_lifecycle_coverage_risk_row_has_a_real_consumer():
    """`lifecycle_risk["risks"]` carried the NOT-ASSESSED disclosure and a repo-wide sweep found ZERO
    readers of it -- an honesty record nothing consumes is not a disclosure. The executive brief now
    reads it: a snapshot whose SUMMARY was hand-edited to hide the unknowns (n_unknown 0) but which
    still carries the producer's not-assessed risk row must NOT score the clean-fleet severity."""
    b = compute_executive_brief(
        health_scores=[{"band": "Good", "score": 85}],
        lifecycle_risk={"summary": {"n_devices": 10, "n_active": 10, "n_unknown": 0},
                        "risks": [{"severity": "Medium", "devices": ["sw1"],
                                   "evidence_confidence": "not-assessed",
                                   "title": "Hardware lifecycle NOT ASSESSED"}]})
    ax = next(a for a in b["axes"] if a["axis"] == "Hardware lifecycle (EoL)")
    assert ax["severity"] == "Info", f"the not-assessed risk row was ignored: {ax}"
    assert "UNDETERMINED" in b["posture_statement"], b["posture_statement"]

    # NON-VACUITY: an ADVERSE risk row (the ordinary case) must not trip the coverage gate.
    b2 = compute_executive_brief(
        health_scores=[{"band": "Good", "score": 85}],
        lifecycle_risk={"summary": {"n_devices": 10, "n_active": 10, "n_unknown": 0},
                        "risks": [{"severity": "Critical", "devices": ["sw1"],
                                   "evidence_confidence": "confirmed", "title": "past LDoS"}]})
    ax2 = next(a for a in b2["axes"] if a["axis"] == "Hardware lifecycle (EoL)")
    assert ax2["severity"] == "Low", ax2


def test_posture_statement_discloses_its_own_four_flag_display_cap():
    """The sentence renders `flags[:4]` and states no flag total anywhere else, so a fifth and sixth
    blocker vanished silently from the posture headline."""
    b = compute_executive_brief(
        health_scores=[{"band": "Critical", "score": 10}],
        migration_readiness=[{"readiness": "NOT READY"}],
        lifecycle_risk={"summary": {"n_devices": 10, "n_past_ldos": 3, "n_unknown": 2}},
        segmentation={"summary": {"n_gateways": 5, "flat": True}},
        multicast_intelligence={"summary": {"n_groups": 2, "n_mac_clashes": 1,
                                            "n_ptp_clocks": 1, "n_ptp_dormant": 1}})
    ps = b["posture_statement"]
    assert "further flag(s) not shown" in ps, f"the display cap is undisclosed: {ps}"
    # NON-VACUITY: nothing cut -> no cut notice.
    b2 = compute_executive_brief(health_scores=[{"band": "Critical", "score": 10}])
    assert "further flag(s) not shown" not in b2["posture_statement"], b2["posture_statement"]


# ── R8/F1: the posture flag stated a DEVICE count it had not measured ───────────
def test_the_undetermined_flag_counts_devices_not_disclosure_rows():
    """`{lc_unknown or len(lc_coverage_risks)} device(s)` — `lc_coverage_risks` is a list of RISK
    ROWS, so when the summary's own `n_unknown` was 0 (an older/hand-edited snapshot that hides the
    unknowns) the sentence printed the number of DISCLOSURES and called them devices.

    Measured on the pre-fix code with one not-assessed row naming three hosts: "hardware support
    state is UNDETERMINED on 1 device(s)" — a count the run never took, in the posture headline of
    every deliverable."""
    b = compute_executive_brief(
        health_scores=[{"band": "Good", "score": 85}],
        lifecycle_risk={"summary": {"n_devices": 10, "n_active": 10, "n_unknown": 0},
                        "risks": [{"severity": "Medium", "devices": ["sw1", "sw2", "sw3"],
                                   "evidence_confidence": "not-assessed",
                                   "title": "Hardware lifecycle NOT ASSESSED"}]})
    ps = b["posture_statement"]
    assert "3 device(s)" in ps, ps
    assert "1 device(s)" not in ps, f"a risk-row count was rendered as a device count: {ps}"

    # A row that names NO devices must not borrow the row count either — it says what the number IS.
    b2 = compute_executive_brief(
        health_scores=[{"band": "Good", "score": 85}],
        lifecycle_risk={"summary": {"n_devices": 10, "n_active": 10, "n_unknown": 0},
                        "risks": [{"severity": "Medium", "evidence_confidence": "not-assessed",
                                   "title": "Hardware lifecycle NOT ASSESSED"}]})
    ps2 = b2["posture_statement"]
    assert "device(s)" not in ps2.split("UNDETERMINED")[1].split(";")[0], ps2
    assert "disclosure(s)" in ps2, ps2

    # NON-VACUITY: the ordinary case (the summary DOES carry a device count) is unchanged, and a
    # fully-assessed fleet still gains no flag at all.
    b3 = compute_executive_brief(health_scores=[{"band": "Good", "score": 85}],
                                 lifecycle_risk={"summary": {"n_devices": 10, "n_unknown": 8,
                                                             "n_active": 2}})
    assert "8 device(s)" in b3["posture_statement"], b3["posture_statement"]
    b4 = compute_executive_brief(health_scores=[{"band": "Good", "score": 85}],
                                 lifecycle_risk={"summary": {"n_devices": 10, "n_active": 10}})
    assert "UNDETERMINED" not in b4["posture_statement"], b4["posture_statement"]


# ── R8/F8: the repaired coverage-risk sentence had no reader ────────────────────
def test_the_coverage_risk_detail_reaches_a_RENDERED_surface():
    """`lifecycle_risk["risks"]` gained a not-assessed row whose detail names the model strings to
    resolve on Cisco's EoX portal — and the only consumer was a severity gate that reads the row's
    EXISTENCE. The repaired platform list was therefore visible solely in the snapshot JSON, which
    is not a disclosure. The EoL axis detail (workbook / deck / explorer / brief) now carries it."""
    lc = compute_lifecycle_risk({"sw1": {"model": "TOTALLY-MADE-UP", "sw_version": "x"},
                                 "sw2": {"model": "ALSO-MADE-UP", "sw_version": "x"}}, asof=ASOF)
    b = compute_executive_brief(health_scores=[{"band": "Good", "score": 85}], lifecycle_risk=lc)
    ax = next(a for a in b["axes"] if a["axis"] == "Hardware lifecycle (EoL)")
    assert "NOT ASSESSED" in ax["detail"], ax["detail"]
    assert "retained source chain verified" in ax["detail"]
    assert "no EoS/LDoS date is derived from a generic support-window rule" in ax["detail"]
    assert "end-of-sale + 5yr" not in ax["detail"]
    assert "TOTALLY-MADE-UP" in ax["detail"] and "ALSO-MADE-UP" in ax["detail"], ax["detail"]

    # NON-VACUITY: a fully-banded fleet must gain no not-assessed clause, or the sentence is
    # always-on and stops meaning anything.
    clean = compute_lifecycle_risk(_dev("WS-C4948E-F"), asof=ASOF)
    b2 = compute_executive_brief(health_scores=[{"band": "Good", "score": 85}], lifecycle_risk=clean)
    ax2 = next(a for a in b2["axes"] if a["axis"] == "Hardware lifecycle (EoL)")
    assert "NOT ASSESSED" not in ax2["detail"], ax2["detail"]


# ── R8/F2: the multicast axis presented a CURATED judgement as a measurement ────
def _mcast_axis(**summary):
    b = compute_executive_brief(health_scores=[{"band": "Good", "score": 85}],
                                multicast_intelligence={"summary": dict(n_groups=10, **summary)})
    return next(a for a in b["axes"] if a["axis"] == "Multicast / timing")


def test_the_av_group_headline_states_the_basis_of_its_on_air_classification():
    """"44 broadcast/AV group(s)." — `n_av_groups` counts groups whose on-air label comes from this
    repo's CURATED overlay; on the shipped pack NONE of them rest on an authoritative registry
    source. The sibling exit (the multicast MAC-overlap risk row) was taught to say so a round
    earlier and this one, the same fact in the executive brief, was left stating a judgement in the
    voice of a measurement."""
    ax = _mcast_axis(n_av_groups=44, n_av_groups_authoritative=0, n_mcast_vlans=3)
    assert ax["detail"] != "44 broadcast/AV group(s).", "the bare count survived"
    assert "44 broadcast/AV group(s)" in ax["detail"]
    assert "curated" in ax["detail"].lower(), ax["detail"]

    # A snapshot that never recorded the basis must ABSTAIN, not assert "0 authoritative": absent
    # is "not recorded", and a 0 that means not-measured must not read as a measured zero.
    old = _mcast_axis(n_av_groups=44, n_mcast_vlans=3)
    assert "not recorded" in old["detail"], old["detail"]
    assert "0 classified" not in old["detail"], old["detail"]

    # NON-VACUITY (both directions): a genuinely authoritative classification says so, and a fleet
    # with no AV groups gains no caveat.
    auth = _mcast_axis(n_av_groups=4, n_av_groups_authoritative=4, n_mcast_vlans=3)
    assert "4 classified on-air by an authoritative" in auth["detail"], auth["detail"]
    none = _mcast_axis(n_av_groups=0, n_av_groups_authoritative=0, n_mcast_vlans=3)
    assert none["detail"] == "0 broadcast/AV group(s).", none["detail"]
