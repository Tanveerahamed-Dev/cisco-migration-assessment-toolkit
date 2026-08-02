"""Tests for the intel-feed consumer (cisco_toolkit.intel_feed) — Phase 5, the NO-EGRESS half.

The load-bearing property is the PROVENANCE GATE: a feed is consumed only if it is sanitized-attested,
hash-intact, and free of forbidden identifiers — a tampered / unsanitized / poisoned feed is REFUSED whole
(the no-egress invariant enforced on intake). Plus: fleet-matching produces PSIRT hits, and those hits flow
into the Phase-4 self_healing loop routed to the security auditor (closing the eyes->self-healing loop).
"""
import json

import pytest

from cisco_toolkit import intel_feed as IF
from cisco_toolkit import self_healing as SH


def _adv(id_, title="Some advisory", severity="High", affected=("ios",), source="cisco-psirt"):
    return {"id": id_, "title": title, "severity": severity, "affected": list(affected), "source": source}


# --- the provenance gate -----------------------------------------------------------------------

def test_build_and_verify_roundtrip():
    text = IF.build_feed([_adv("cisco-sa-a"), _adv("cisco-sa-b")], generated="2026-07-07")
    res = IF.verify_feed(text)
    assert res["ok"] and len(res["entries"]) == 2 and res["manifest"]["sanitized"] is True
    assert res["manifest"]["manifest_version"] == 2
    assert res["manifest"]["integrity"] == "sha256"
    assert res["authenticated"] is False
    assert "authenticity not established" in res["reason"]


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


def test_manifest_count_mismatch_and_malformed_entries_are_refused_whole():
    valid = IF.build_feed([_adv("cisco-sa-a")])
    lines = valid.splitlines()
    manifest = json.loads(lines[0])
    manifest["n"] = 2
    wrong_count = "\n".join([json.dumps(manifest), *lines[1:]]) + "\n"
    assert IF.verify_feed(wrong_count)["ok"] is False

    malformed_lines = ["not-json"]
    malformed_manifest = {
        "kind": "intel-feed-manifest",
        "sha256": IF._sha256_of(malformed_lines),
        "sanitized": True,
        "producer": "test",
        "generated": "",
        "n": 1,
    }
    malformed = json.dumps(malformed_manifest) + "\nnot-json\n"
    result = IF.verify_feed(malformed)
    assert result["ok"] is False and result["entries"] == []


def test_forbidden_identifier_is_refused_even_if_sanitized_flag_set():
    text = IF.build_feed([_adv("cisco-sa-a", title="issue at AcmeCorp core")])
    res = IF.verify_feed(text, forbidden=("AcmeCorp",))
    assert res["ok"] is False and "forbidden identifier" in res["reason"]


@pytest.mark.parametrize(
    ("literal", "kind"),
    [
        ("203.0.113.9", "IPv4"),
        ("2001:db8::9", "IPv6"),
        ("00:1a:2b:3c:4d:5e", "MAC"),
        ("FDO2145A1BC", "serial"),
        ("engineer@example.net", "email"),
    ],
)
def test_standard_identifiers_are_refused_without_caller_denylist(literal, kind):
    feed = IF.build_feed([
        _adv("cisco-sa-a", title=f"forged sanitized entry containing {literal}")
    ])
    result = IF.verify_feed(feed)
    assert result["ok"] is False
    assert kind in result["reason"]
    assert result["entries"] == []


def test_engagement_intake_requires_and_enforces_a_derived_denylist():
    clean = IF.build_feed([_adv("cisco-sa-a", title="generic platform advisory")])
    missing = IF.verify_feed(clean, require_forbidden=True)
    assert missing["ok"] is False
    assert "denylist is required" in missing["reason"]

    snap = {
        "devices": {
            "MERIDIAN-CORE-01": {"hostname": "MERIDIAN-CORE-01", "platform": "ios-xe"}
        },
        "engagement": {"client_name": "Meridian Reference"},
    }
    denylist = IF.engagement_identifiers(snap)
    assert {"MERIDIAN-CORE-01", "Meridian Reference"}.issubset(set(denylist))
    assert IF.verify_feed(
        clean,
        forbidden=denylist,
        require_forbidden=True,
    )["ok"] is True

    leaked = IF.build_feed([
        _adv("cisco-sa-b", title="finding observed on MERIDIAN-CORE-01")
    ])
    refused = IF.verify_feed(
        leaked,
        forbidden=denylist,
        require_forbidden=True,
    )
    assert refused["ok"] is False
    assert "forbidden identifier" in refused["reason"]


def test_forbidden_scan_operates_on_decoded_json_not_escape_spelling():
    entry_lines = [
        '{"id":"field-note-1","title":"issue at Ac\\u006de core"}'
    ]
    manifest = {
        "kind": "intel-feed-manifest",
        "sha256": IF._sha256_of(entry_lines),
        "sanitized": True,
        "producer": "legacy-test",
        "generated": "",
        "n": 1,
    }
    feed = json.dumps(manifest) + "\n" + entry_lines[0] + "\n"
    result = IF.verify_feed(feed, forbidden=("Acme",))
    assert result["ok"] is False
    assert "forbidden identifier" in result["reason"]


def test_strict_json_duplicate_keys_nonfinite_values_and_duplicate_ids_are_refused():
    duplicate_key_lines = ['{"id":"a","id":"b"}']
    duplicate_key_manifest = {
        "kind": "intel-feed-manifest",
        "sha256": IF._sha256_of(duplicate_key_lines),
        "sanitized": True,
        "n": 1,
    }
    duplicate_key_feed = (
        json.dumps(duplicate_key_manifest) + "\n" + duplicate_key_lines[0] + "\n"
    )
    assert "duplicate key" in IF.verify_feed(duplicate_key_feed)["reason"]

    nonfinite_lines = ['{"id":"a","score":NaN}']
    nonfinite_manifest = {
        "kind": "intel-feed-manifest",
        "sha256": IF._sha256_of(nonfinite_lines),
        "sanitized": True,
        "n": 1,
    }
    nonfinite_feed = json.dumps(nonfinite_manifest) + "\n" + nonfinite_lines[0] + "\n"
    assert "non-standard JSON constant" in IF.verify_feed(nonfinite_feed)["reason"]

    with pytest.raises(ValueError, match="duplicate advisory id"):
        IF.build_feed([_adv("same"), _adv("same")])
    with pytest.raises(ValueError, match="string id"):
        IF.build_feed([{"id": 123, "title": "bad"}])


def test_missing_manifest_is_refused():
    res = IF.verify_feed(json.dumps(_adv("cisco-sa-a")))     # an advisory line with no manifest header
    assert res["ok"] is False and "manifest" in res["reason"]


# --- loading + coverage honesty ----------------------------------------------------------------

def test_load_feeds_empty_dir_is_honest(tmp_path):
    loaded = IF.load_feeds(str(tmp_path))
    assert loaded["advisories"] == [] and "no intel feed present" in loaded["note"]


def test_load_feeds_reads_good_and_refuses_bad(tmp_path):
    d = tmp_path / "intel"
    d.mkdir()
    (d / "feed-2026-07-07.jsonl").write_text(IF.build_feed([_adv("cisco-sa-a")]), encoding="utf-8")
    (d / "feed-2026-07-08.jsonl").write_text(IF.build_feed([_adv("cisco-sa-b")], sanitized=False),
                                             encoding="utf-8")
    loaded = IF.load_feeds(str(d))
    assert len(loaded["advisories"]) == 1 and loaded["advisories"][0]["id"] == "cisco-sa-a"
    assert len(loaded["refused"]) == 1 and "feed-2026-07-08.jsonl" == loaded["refused"][0]["feed"]


def test_duplicate_advisory_ids_across_files_refuse_every_ambiguous_feed(tmp_path):
    d = tmp_path / "intel"
    d.mkdir()
    (d / "feed-a.jsonl").write_text(
        IF.build_feed([_adv("same-id"), _adv("only-a")]),
        encoding="utf-8",
    )
    (d / "feed-b.jsonl").write_text(
        IF.build_feed([_adv("same-id"), _adv("only-b")]),
        encoding="utf-8",
    )
    (d / "feed-c.jsonl").write_text(
        IF.build_feed([_adv("only-c")]),
        encoding="utf-8",
    )
    loaded = IF.load_feeds(str(d))
    assert [item["id"] for item in loaded["advisories"]] == ["only-c"]
    assert {item["feed"] for item in loaded["refused"]} == {
        "feed-a.jsonl",
        "feed-b.jsonl",
    }
    assert all("duplicate advisory id" in item["reason"] for item in loaded["refused"])


def test_feed_reparse_attribute_is_refused_before_open(tmp_path, monkeypatch):
    feed = tmp_path / "feed-a.jsonl"
    feed.write_text(IF.build_feed([_adv("a")]), encoding="utf-8")
    actual = feed.stat()
    marker = 0x400
    monkeypatch.setattr(IF.stat, "FILE_ATTRIBUTE_REPARSE_POINT", marker, raising=False)

    class ReparseStat:
        st_mode = actual.st_mode
        st_file_attributes = marker
        st_dev = actual.st_dev
        st_ino = actual.st_ino
        st_size = actual.st_size

    monkeypatch.setattr(IF.os, "lstat", lambda _path: ReparseStat())

    def opened_anyway(*_args, **_kwargs):
        pytest.fail("a reparse-point feed was opened before it was refused")

    monkeypatch.setattr(IF.os, "open", opened_anyway)
    with pytest.raises(ValueError, match="regular non-link"):
        IF._read_feed_text(str(feed))


def test_feed_identity_change_between_check_and_open_is_refused(tmp_path, monkeypatch):
    feed = tmp_path / "feed-a.jsonl"
    feed.write_text(IF.build_feed([_adv("a")]), encoding="utf-8")
    actual = feed.stat()

    class Before:
        st_mode = actual.st_mode
        st_dev = actual.st_dev
        st_ino = actual.st_ino
        st_size = actual.st_size

    class After(Before):
        st_ino = actual.st_ino + 1

    stats = iter((Before(), After()))
    monkeypatch.setattr(IF.os, "lstat", lambda _path: next(stats))
    with pytest.raises(ValueError, match="identity changed"):
        IF._read_feed_text(str(feed))


def test_feed_aggregate_budget_refuses_the_set_whole(tmp_path, monkeypatch):
    (tmp_path / "feed-a.jsonl").write_text(
        IF.build_feed([_adv("a")]),
        encoding="utf-8",
    )
    monkeypatch.setattr(IF, "_MAX_FEED_TOTAL_BYTES", 1)
    loaded = IF.load_feeds(str(tmp_path))
    assert loaded["advisories"] == []
    assert loaded["note"].startswith("aggregate feeds exceed")
    assert loaded["refused"][-1]["feed"] == "*"


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
        [{"id": "field-note-1", "title": "uplink flap",
          "detail": "ACME-BANK-CORE-01 lost its uplink", "source": "note"}],
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
