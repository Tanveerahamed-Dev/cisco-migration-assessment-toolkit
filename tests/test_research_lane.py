"""Tests for the egress-fenced research lane (research_lane.*) — Phase 5, D2.

All OFFLINE — the live ``http_source`` (real egress) is deliberately not exercised. What's pinned: the
Rule-3 sanitizer scrubs client identifiers (forbidden tokens, IPs, emails); and the producer's
sanitize→sign pipeline emits a feed the air-gapped consumer (cisco_toolkit.intel_feed) accepts — so the
producer↔consumer signing contract holds and nothing crosses in unscrubbed.
"""
import os

from cisco_toolkit import intel_feed as IF
from research_lane import producer as P
from research_lane import sanitize as SAN


# --- the Rule-3 sanitizer ----------------------------------------------------------------------

def test_sanitize_text_redacts_forbidden_ip_and_email():
    out, red = SAN.sanitize_text("AcmeCorp at 10.0.0.1 (admin@acme.com)", forbidden=("AcmeCorp",))
    assert "AcmeCorp" not in out and "10.0.0.1" not in out and "acme.com" not in out
    assert "[redacted]" in out and "[ip]" in out and "[email]" in out
    assert set(red) == {"AcmeCorp", "10.0.0.1", "admin@acme.com"}


def test_sanitize_advisory_leaves_structural_fields():
    clean, red = SAN.sanitize_advisory({"id": "cisco-sa-x", "severity": "High",
                                        "title": "fault at 10.0.0.1", "affected": ["ios"]})
    assert clean["id"] == "cisco-sa-x" and clean["severity"] == "High" and clean["affected"] == ["ios"]
    assert clean["title"] == "fault at [ip]" and "10.0.0.1" in red


# --- producer -> consumer roundtrip ------------------------------------------------------------

def test_produce_feed_is_accepted_by_the_consumer():
    raw = [{"id": "cisco-sa-a", "title": "issue", "severity": "High", "affected": ["ios"]}]
    feed, _red = P.produce_feed(raw, generated="2026-07-07")
    res = IF.verify_feed(feed)
    assert res["ok"] and res["manifest"]["sanitized"] is True
    assert res["entries"][0]["id"] == "cisco-sa-a"


def test_producer_scrubs_client_identity_before_signing():
    raw = [{"id": "x", "title": "AcmeCorp core at 10.1.2.3 (noc@acme.com)", "severity": "High",
            "affected": ["ios"]}]
    feed, red = P.produce_feed(raw, forbidden=("AcmeCorp",), generated="d")
    title = IF.verify_feed(feed)["entries"][0]["title"]
    assert "AcmeCorp" not in title and "10.1.2.3" not in title and "acme.com" not in title
    assert set(red) >= {"AcmeCorp", "10.1.2.3", "noc@acme.com"}


def test_run_writes_feed_the_consumer_loads(tmp_path):
    raw = [{"id": "cisco-sa-a", "title": "t", "severity": "Medium", "affected": ["nxos"]}]
    path, _red = P.run(raw, out_dir=str(tmp_path), generated="2026-07-07")
    assert path.endswith(os.path.join(str(tmp_path), "feed-2026-07-07.jsonl")) or path.endswith("feed-2026-07-07.jsonl")
    assert os.path.exists(path)
    loaded = IF.load_feeds(str(tmp_path))
    assert len(loaded["advisories"]) == 1 and loaded["refused"] == []


def test_scrubbed_feed_passes_even_consumer_forbidden_scan(tmp_path):
    # the producer scrubbed "Acme", so the consumer's own forbidden scan finds nothing -> accepted.
    raw = [{"id": "x", "title": "Acme site issue", "severity": "Low", "affected": ["ios"]}]
    P.run(raw, out_dir=str(tmp_path), forbidden=("Acme",), generated="d")
    loaded = IF.load_feeds(str(tmp_path), forbidden=("Acme",))
    assert len(loaded["advisories"]) == 1 and loaded["refused"] == []
