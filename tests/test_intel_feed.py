"""Tests for the intel-feed consumer (cisco_toolkit.intel_feed) — Phase 5, the NO-EGRESS half.

The load-bearing property is the PROVENANCE GATE: a feed is consumed only if it is sanitized-attested,
hash-intact, and free of forbidden identifiers — a tampered / unsanitized / poisoned feed is REFUSED whole
(the no-egress invariant enforced on intake). Plus: fleet-matching produces PSIRT hits, and those hits flow
into the Phase-4 self_healing loop routed to the security auditor (closing the eyes->self-healing loop).
"""
import json
import os

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
