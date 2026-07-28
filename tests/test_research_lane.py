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


def test_map_cisa_kev_filters_and_maps():
    """The KEV -> advisory mapper is pure (no egress) and testable. Filters to vendor, maps fields,
    severity Critical iff ransomware-linked, sorted by date."""
    from research_lane.sources import map_kev_vulnerabilities
    vulns = [
        {"cveID": "CVE-1", "vendorProject": "Cisco", "product": "ASA", "vulnerabilityName": "ASA DoS",
         "dateAdded": "2021-01-01", "shortDescription": "x", "knownRansomwareCampaignUse": "Unknown"},
        {"cveID": "CVE-2", "vendorProject": "Microsoft", "product": "Windows", "vulnerabilityName": "y",
         "dateAdded": "2021-02-01"},
        {"cveID": "CVE-3", "vendorProject": "Cisco", "product": "IOS XE", "vulnerabilityName": "z",
         "dateAdded": "2022-01-01", "knownRansomwareCampaignUse": "Known"},
    ]
    out = map_kev_vulnerabilities(vulns, vendor="Cisco")
    assert [a["id"] for a in out] == ["CVE-1", "CVE-3"]        # Microsoft filtered; sorted by date
    assert out[0]["affected"] == ["ASA"] and out[0]["severity"] == "High" and out[0]["source"] == "CISA KEV"
    assert out[1]["severity"] == "Critical"                   # ransomware-linked -> Critical


def test_map_psirt_advisories_extracts_fixed_versions():
    """The openVuln -> advisory mapper is pure (no egress): one entry per CVE, carrying the `fixed`
    release(s) — the Phase-B target — and defensive across field-name variants."""
    from research_lane.sources import map_psirt_advisories
    advisories = [
        {"advisoryId": "cisco-sa-x", "advisoryTitle": "Smart Install RCE", "cves": ["CVE-2018-0171"],
         "sir": "High", "firstPublished": "2018-03-28T16:00:00", "productNames": ["Cisco IOS", "IOS XE"],
         "firstFixed": ["12.2(55)SE12", "15.2(4)E"], "cvssBaseScore": "9.8"},
        {"advisoryId": "cisco-sa-y", "advisoryTitle": "Web UI RCE", "cves": ["CVE-2023-20198", "CVE-2023-20273"],
         "severity": "critical", "firstPublished": "2023-10-16", "productNames": ["IOS XE"],
         "fixedReleases": "17.9.4a, 17.6.6a"},
    ]
    by = {a["id"]: a for a in map_psirt_advisories(advisories)}
    assert by["CVE-2018-0171"]["fixed"] == ["12.2(55)SE12", "15.2(4)E"]      # list preserved (sorted-uniq)
    assert by["CVE-2018-0171"]["severity"] == "High" and by["CVE-2018-0171"]["source"] == "Cisco PSIRT openVuln"
    assert by["CVE-2018-0171"]["cvss"] == "9.8" and by["CVE-2018-0171"]["published"] == "2018-03-28"
    # a multi-CVE advisory fans out to one entry per CVE, each carrying the fix (string form parsed + sorted)
    assert by["CVE-2023-20198"]["fixed"] == ["17.6.6a", "17.9.4a"] == by["CVE-2023-20273"]["fixed"]
    assert by["CVE-2023-20198"]["severity"] == "Critical"                    # 'critical' -> title-cased


def test_psirt_source_refuses_without_creds():
    """Credential-gated: no client_id/secret -> raises before any egress."""
    import pytest
    from research_lane.sources import cisco_psirt_source
    with pytest.raises(ValueError):
        cisco_psirt_source(["CVE-2018-0171"], client_id=None, client_secret=None)
    with pytest.raises(ValueError):
        cisco_psirt_source(["CVE-2018-0171"], client_id="x", client_secret="")


# --- "could not reach the source" is never "the source had nothing" (finding #78) ----------------
# The per-CVE fetch used a bare `except Exception: continue`, so an expired/revoked token, an HTTP 403
# rate limit and a DNS/proxy outage all returned [] — the SAME answer as the documented benign case
# ("Cisco has no advisory for this CVE") — and producer.run then SIGNED and published a
# `sanitized: true`, zero-advisory feed the air-gapped consumer accepts as valid-and-current.
# These stay hermetic: urlopen is faked, so no test ever egresses.

def _fake_urlopen(monkeypatch, per_cve):
    """Fake urlopen: the OAuth token always succeeds; ``per_cve(cve)`` decides each advisory GET
    (return a payload dict, or raise)."""
    import io
    import json as _json
    import urllib.request

    class _Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake(req, timeout=None):
        url = req if isinstance(req, str) else req.full_url
        if "token" in url:
            return _Resp(_json.dumps({"access_token": "t"}).encode())
        return _Resp(_json.dumps(per_cve(url.rsplit("/", 1)[-1])).encode())

    monkeypatch.setattr(urllib.request, "urlopen", fake)


def test_psirt_unreachable_source_raises_instead_of_reporting_zero(monkeypatch):
    import urllib.error
    from research_lane.sources import SourceUnavailable, cisco_psirt_source

    def forbidden(cve):
        raise urllib.error.HTTPError(f"https://x/{cve}", 403, "Forbidden", {}, None)

    _fake_urlopen(monkeypatch, forbidden)
    stats = {}
    import pytest
    with pytest.raises(SourceUnavailable) as ex:
        cisco_psirt_source(["CVE-1", "CVE-2"], client_id="i", client_secret="s", stats=stats)
    assert stats == {"queried": 2, "advisories": 0, "no_advisory": 0, "unreachable": 2,
                     "errors": ["CVE-1: HTTP 403 Forbidden", "CVE-2: HTTP 403 Forbidden"]}
    assert ex.value.stats["unreachable"] == 2 and "403" in str(ex.value)


def test_psirt_404_stays_the_benign_skip_and_is_counted(monkeypatch):
    """The documented coverage-honest case must still work — and be REPORTED, not silently dropped."""
    import urllib.error
    from research_lane.sources import cisco_psirt_source

    def mixed(cve):
        if cve == "CVE-none":
            raise urllib.error.HTTPError(f"https://x/{cve}", 404, "Not Found", {}, None)
        return {"advisories": [{"advisoryId": "cisco-sa-x", "advisoryTitle": "t", "cves": [cve],
                                "sir": "High", "firstFixed": ["17.9.4a"]}]}

    _fake_urlopen(monkeypatch, mixed)
    stats = {}
    out = cisco_psirt_source(["CVE-real", "CVE-none"], client_id="i", client_secret="s", stats=stats)
    assert [a["id"] for a in out] == ["CVE-real"] and out[0]["fixed"] == ["17.9.4a"]
    assert stats["no_advisory"] == 1 and stats["unreachable"] == 0 and stats["advisories"] == 1


def test_psirt_partial_unreachability_still_refuses(monkeypatch):
    """A feed short by an UNKNOWN amount is the same defect as an empty one: one advisory arriving
    does not license publishing the sweep as measured."""
    import urllib.error
    from research_lane.sources import SourceUnavailable, cisco_psirt_source

    def flaky(cve):
        if cve == "CVE-dead":
            raise urllib.error.URLError("getaddrinfo failed")
        return {"advisories": [{"advisoryId": "a", "cves": [cve], "sir": "High"}]}

    _fake_urlopen(monkeypatch, flaky)
    import pytest
    with pytest.raises(SourceUnavailable, match="1 of 2"):
        cisco_psirt_source(["CVE-ok", "CVE-dead"], client_id="i", client_secret="s")


def test_run_refuses_to_sign_an_empty_feed(tmp_path):
    """The publish-side gate: a signed `sanitized: true` feed with zero advisories is, to the consumer,
    a positive attestation that the source was read and had nothing — which a failed fetch cannot make."""
    import pytest
    with pytest.raises(ValueError, match="zero advisories"):
        P.run([], out_dir=str(tmp_path), generated="2026-07-28")
    assert list(tmp_path.iterdir()) == []                     # nothing written on the refusal path
    path, _red = P.run([], out_dir=str(tmp_path), generated="2026-07-28", allow_empty=True)
    assert os.path.exists(path)                               # ...and the deliberate escape still works


def test_producer_cli_refuses_when_the_source_is_unreachable(monkeypatch, tmp_path, capsys):
    """End-to-end: --source cisco-psirt on an unreachable source exits non-zero and writes NOTHING."""
    import urllib.error
    from research_lane import sources as S

    monkeypatch.setenv("CISCO_OPENVULN_CLIENT_ID", "i")
    monkeypatch.setenv("CISCO_OPENVULN_CLIENT_SECRET", "s")
    cve_file = tmp_path / "cves.txt"
    cve_file.write_text("CVE-2018-0171\n", encoding="utf-8")

    def boom(cves, **kw):
        stats = kw.get("stats")
        if stats is not None:
            stats.update({"queried": 1, "advisories": 0, "no_advisory": 0, "unreachable": 1,
                          "errors": ["CVE-2018-0171: HTTP 403 Forbidden"]})
        raise S.SourceUnavailable("Cisco openVuln could not be reached for 1 of 1 CVE(s)", stats)

    monkeypatch.setattr(S, "cisco_psirt_source", boom)
    out_dir = tmp_path / "intel"
    rc = P.main(["--source", "cisco-psirt", "--cve-file", str(cve_file), "--out", str(out_dir),
                 "--generated", "2026-07-28"])
    assert rc == 3
    assert "REFUSED" in capsys.readouterr().out
    assert not out_dir.exists()                               # no signed feed on disk
    _ = urllib.error                                          # (imported to pin the failure shape)
