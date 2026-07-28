"""Tests for the intel-feed consumer (cisco_toolkit.intel_feed) — Phase 5, the NO-EGRESS half.

The load-bearing property is the PROVENANCE GATE: a feed is consumed only if it is sanitized-attested,
hash-intact, and free of forbidden identifiers — a tampered / unsanitized / poisoned feed is REFUSED whole
(the no-egress invariant enforced on intake). Plus: fleet-matching produces PSIRT hits, and those hits flow
into the Phase-4 self_healing loop routed to the security auditor (closing the eyes->self-healing loop).
"""
import json

from cisco_toolkit import intel_feed as IF
from cisco_toolkit import self_healing as SH


def _adv(id_, title="Some advisory", severity="High", affected=("ios",), source="cisco-psirt"):
    return {"id": id_, "title": title, "severity": severity, "affected": list(affected), "source": source}


# --- the provenance gate -----------------------------------------------------------------------

def test_build_and_verify_roundtrip():
    text = IF.build_feed([_adv("cisco-sa-a"), _adv("cisco-sa-b")], generated="2026-07-07")
    res = IF.verify_feed(text)
    assert res["ok"] and len(res["entries"]) == 2 and res["manifest"]["sanitized"] is True


def test_tampered_feed_is_refused():
    text = IF.build_feed([_adv("cisco-sa-a", title="orig")])
    lines = text.splitlines()
    lines[1] = lines[1].replace("orig", "tampered")          # mutate an entry after signing
    res = IF.verify_feed("\n".join(lines))
    assert res["ok"] is False and "hash mismatch" in res["reason"] and res["entries"] == []


def test_unsanitized_feed_is_refused():
    text = IF.build_feed([_adv("cisco-sa-a")], sanitized=False)
    res = IF.verify_feed(text)
    assert res["ok"] is False and "sanitized" in res["reason"]


def test_forbidden_identifier_is_refused_even_if_sanitized_flag_set():
    text = IF.build_feed([_adv("cisco-sa-a", title="issue at AcmeCorp core")])
    res = IF.verify_feed(text, forbidden=("AcmeCorp",))
    assert res["ok"] is False and "forbidden identifier" in res["reason"]


def test_missing_manifest_is_refused():
    res = IF.verify_feed(json.dumps(_adv("cisco-sa-a")))     # an advisory line with no manifest header
    assert res["ok"] is False and "manifest" in res["reason"]


# --- loading + coverage honesty ----------------------------------------------------------------

def test_load_feeds_empty_dir_is_honest(tmp_path):
    loaded = IF.load_feeds(str(tmp_path))
    assert loaded["advisories"] == [] and "egress research lane is not wired" in loaded["note"]


def test_load_feeds_reads_good_and_refuses_bad(tmp_path):
    d = tmp_path / "intel"
    d.mkdir()
    (d / "feed-2026-07-07.jsonl").write_text(IF.build_feed([_adv("cisco-sa-a")]), encoding="utf-8")
    (d / "feed-2026-07-08.jsonl").write_text(IF.build_feed([_adv("cisco-sa-b")], sanitized=False),
                                             encoding="utf-8")
    loaded = IF.load_feeds(str(d))
    assert len(loaded["advisories"]) == 1 and loaded["advisories"][0]["id"] == "cisco-sa-a"
    assert len(loaded["refused"]) == 1 and "feed-2026-07-08.jsonl" == loaded["refused"][0]["feed"]


# --- fleet matching + the self_healing loop ----------------------------------------------------

def test_fleet_platforms_and_match():
    snap = {"devices": {"r1": {"platform": "ios-xe"}, "r2": {"platform": "nxos"}}}
    assert IF.fleet_platforms(snap) == {"ios-xe", "nxos"}
    hits = IF.match_fleet([_adv("cisco-sa-a", affected=["ios"]), _adv("cisco-sa-b", affected=["asa"])],
                          IF.fleet_platforms(snap))
    assert len(hits) == 1 and hits[0]["id"] == "cisco-sa-a" and hits[0]["matched_platforms"] == ["ios-xe"]


def test_no_platforms_no_hits():
    assert IF.match_fleet([_adv("cisco-sa-a")], set()) == []      # can't match without inventory; don't guess


def test_advisory_hits_flow_into_self_healing_routed_to_security():
    hits = IF.match_fleet([_adv("cisco-sa-crit", severity="critical", affected=["ios"])], {"ios-xe"})
    items = IF.advisory_drift_items(hits)
    assert items and items[0]["kind"] == "advisory" and items[0]["severity"] == "Critical"
    res = SH.propose_remediation({}, {}, extra_items=items)       # no snapshot drift; advisory is the driver
    assert res["plan"] and res["plan"][0]["kind"] == "advisory"
    assert res["plan"][0]["root_cause_owner"] == "config-security-auditor"
    assert res["plan"][0]["mop_author"] == "mop-change-author"    # still propose-only


def test_verify_feed_empty_and_unparseable_manifest_are_refused():
    """The front of the provenance gate: an empty feed or a non-JSON first line is refused whole,
    with NO entries consumed (intel_feed.py:58,61-62)."""
    empty = IF.verify_feed("")
    assert empty["ok"] is False and empty["reason"] == "empty feed" and empty["entries"] == []
    bad = IF.verify_feed("not-json-line\n")
    assert bad["ok"] is False and "unparseable manifest" in bad["reason"] and bad["entries"] == []


def test_match_fleet_coerces_a_scalar_affected_field():
    """Real advisories often carry `affected` as a scalar; the list-coercion (intel_feed.py:132) must
    still match the fleet platform — an uncovered branch."""
    hits = IF.match_fleet([{"id": "x", "affected": "ios"}], {"ios-xe"})
    assert hits, "a scalar 'affected' must coerce to a list and still match the fleet"


def test_render_shows_refused_feeds_and_no_match():
    loaded = {"note": "1 feed", "refused": [{"feed": "bad.jsonl", "reason": "unreadable"}], "advisories": []}
    out = IF.render(loaded, hits=[])
    assert "[REFUSED] bad.jsonl: unreadable" in out
    assert "no loaded advisory matches" in out


def test_main_verifies_feeds_and_matches_the_fleet(tmp_path, capsys):
    d = tmp_path / "intel"
    d.mkdir()
    (d / "junk-feed.jsonl").write_text("not a manifest\n", encoding="utf-8")     # refused by the gate
    snap = tmp_path / "snap.json"
    snap.write_text(json.dumps({"devices": {"r1": {"platform": "ios-xe"}}}), encoding="utf-8")
    assert IF.main(["--dir", str(d), str(snap)]) == 0                            # read-only, no egress
    assert "Intel feed" in capsys.readouterr().out


def test_forbidden_identifier_is_caught_in_its_device_spelling():
    """The consuming half of the Rule-3 gate must not share the producing half's blind spots.

    An operator configures the CLIENT's name ("Acme Bank") — that is what they know. What is
    actually written in a note is the DEVICE's name, ACME-BANK-CORE-01. Under the old literal
    `t.lower() in blob` this gate saw neither that, nor a whitespace-padded token from the natural
    `--forbidden "Acme Bank, SiteA"` spelling. Since research_lane's sanitizer had the SAME blind
    spot, the defense-in-depth check could never catch what the scrub had missed: the feed arrived
    attested `sanitized: true` with an empty redaction list and was consumed whole.
    """
    feed = IF.build_feed(
        [{"title": "uplink flap", "detail": "ACME-BANK-CORE-01 lost its uplink", "source": "note"}],
        sanitized=True)
    # sanity: the feed is otherwise well-formed, so a refusal below is the identifier check firing
    # and not a manifest/hash problem.
    assert IF.verify_feed(feed, forbidden=("Nonmatching Corp",))["ok"] is True
    for tok in ("Acme Bank",          # multi-word: the client name, hyphenated on the device
                " Acme Bank ",        # whitespace-padded, as `--forbidden "A, B"` produces
                "Acme_Bank",          # a different separator than the text uses
                "acme bank"):         # case-insensitive
        r = IF.verify_feed(feed, forbidden=(tok,))
        assert r["ok"] is False, f"forbidden token {tok!r} did not refuse the feed"
        assert r["entries"] == [], "a refused feed must never be partially consumed"
    # A degenerate token compiles to None and must match NOTHING — compiling "" instead would match
    # at every position and refuse every feed that was ever offered.
    for degenerate in ("", "   ", "-", " . "):
        assert IF.verify_feed(feed, forbidden=(degenerate,))["ok"] is True, \
            f"degenerate token {degenerate!r} refused a clean feed"
