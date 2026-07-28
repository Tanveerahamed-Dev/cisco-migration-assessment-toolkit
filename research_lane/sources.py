"""Real advisory sources for the research lane (egress). Each returns advisory dicts in the intel-feed shape.

The **fetch** does egress (public, no-auth, read-only GET) and is isolated here in the fenced lane; the
**mapping** (:func:`map_kev_vulnerabilities`) is a pure function so it is unit-tested without a network.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

# CISA Known Exploited Vulnerabilities — a public, no-auth JSON catalog of ACTIVELY-EXPLOITED CVEs.
CISA_KEV_URL = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"


def map_kev_vulnerabilities(vulns: List[Dict[str, Any]], *, vendor: Optional[str] = "Cisco",
                            limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """Pure: filter KEV entries to ``vendor`` and map to the intel-feed advisory shape. Being in KEV means
    actively exploited, so severity is High (Critical when tied to a ransomware campaign). No I/O."""
    out: List[Dict[str, Any]] = []
    for v in vulns or []:
        if not isinstance(v, dict):
            continue
        if vendor and str(v.get("vendorProject", "")).lower() != vendor.lower():
            continue
        ransom = str(v.get("knownRansomwareCampaignUse", "")).lower() == "known"
        out.append({
            "id": v.get("cveID"),
            "title": v.get("vulnerabilityName") or v.get("cveID"),
            "affected": [v["product"]] if v.get("product") else [],
            "severity": "Critical" if ransom else "High",
            "source": "CISA KEV",
            "published": v.get("dateAdded", ""),
            "summary": v.get("shortDescription", ""),
        })
    out.sort(key=lambda a: a.get("published", ""))          # oldest -> newest (deterministic)
    return out[-limit:] if limit else out


def cisa_kev_source(*, url: str = CISA_KEV_URL, vendor: Optional[str] = "Cisco",
                    limit: Optional[int] = None, timeout: int = 25) -> List[Dict[str, Any]]:
    """LIVE EGRESS: fetch the CISA KEV catalog and map it. Public, no-auth, read-only GET (fenced)."""
    import urllib.request                                    # lazy: egress import stays inside the fenced call
    with urllib.request.urlopen(url, timeout=timeout) as resp:   # noqa: S310 (fenced, opt-in egress)
        data = json.loads(resp.read().decode("utf-8"))
    return map_kev_vulnerabilities(data.get("vulnerabilities", []), vendor=vendor, limit=limit)


# --- Cisco PSIRT openVuln (the fixed-version source — CREDENTIAL-gated, unlike CISA KEV) --------------
# The authoritative Cisco-fixed-release data KEV lacks. Requires an openVuln OAuth2 API client
# (https://apiconsole.cisco.com/) — so this source CANNOT run without creds (no creds -> no egress).
CISCO_PSIRT_TOKEN_URL = "https://id.cisco.com/oauth2/default/v1/token"
CISCO_PSIRT_API_BASE = "https://apix.cisco.com/security/advisories/v2"


def map_psirt_advisories(advisories: List[Dict[str, Any]], *,
                         limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """Pure: map Cisco PSIRT openVuln advisory JSON to the intel-feed shape **plus a ``fixed`` field** — the
    fixed release(s), i.e. the Phase-B upgrade target the feed exists to supply. No I/O. Defensive across
    openVuln field-name variants (``firstFixed``/``fixedReleases``; ``sir``/``severity``) so a schema tweak
    degrades gracefully rather than dropping data. One entry per (advisory, CVE) so each CVE carries its fix."""
    out: List[Dict[str, Any]] = []
    for a in advisories or []:
        if not isinstance(a, dict):
            continue
        cves = a.get("cves") or ([a["cve"]] if a.get("cve") else [])
        fixed = a.get("firstFixed") or a.get("fixedReleases") or a.get("fixed") or []
        if isinstance(fixed, str):
            fixed = [x.strip() for x in fixed.replace(";", ",").split(",") if x.strip()]
        sir = str(a.get("sir") or a.get("severity") or "").strip().title() or "High"
        base = {
            "title": a.get("advisoryTitle") or a.get("title") or "",
            "affected": a.get("productNames") or a.get("affected") or [],
            "severity": sir,
            "source": "Cisco PSIRT openVuln",
            "published": str(a.get("firstPublished") or a.get("published") or "")[:10],
            "summary": a.get("summary") or a.get("advisoryTitle") or "",
            "fixed": sorted({f for f in fixed if f}),
            "cvss": a.get("cvssBaseScore"),
        }
        for cve in (cves or [a.get("advisoryId")]):
            if cve:
                out.append({"id": cve, **base, "title": base["title"] or cve})
    out.sort(key=lambda x: x.get("published", ""))
    return out[-limit:] if limit else out


def _oauth_token(client_id: str, client_secret: str, *, token_url: str = CISCO_PSIRT_TOKEN_URL,
                 timeout: int = 25) -> str:
    """OAuth2 client-credentials → access token (fenced egress). Raises on failure."""
    import urllib.parse
    import urllib.request
    body = urllib.parse.urlencode({"grant_type": "client_credentials",
                                   "client_id": client_id, "client_secret": client_secret}).encode()
    req = urllib.request.Request(token_url, data=body,  # noqa: S310 (fenced, opt-in egress)
                                 headers={"Content-Type": "application/x-www-form-urlencoded",
                                          "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))["access_token"]


class SourceUnavailable(RuntimeError):
    """The SOURCE could not be reached (or refused us) — categorically different from "this CVE has no
    Cisco advisory". Raised so the caller cannot publish a coverage claim it never measured: an expired /
    revoked OAuth token, an HTTP 403 rate limit and a DNS/proxy outage all yield zero advisories, exactly
    like a clean run over CVEs Cisco never published on. Absence of a fetch is not absence of advisories.
    Carries the per-CVE outcome counts so the operator sees the split."""

    def __init__(self, message: str, stats: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.stats: Dict[str, Any] = dict(stats or {})


#: openVuln answers "no advisory for this CVE" with a 404 (and, on some deployments, a 406 on the
#: same empty-result path). Every OTHER status is a source-level failure, never a benign skip.
PSIRT_NO_ADVISORY_CODES = frozenset({404, 406})


def cisco_psirt_source(cve_ids: List[str], *, client_id: Optional[str], client_secret: Optional[str],
                       timeout: int = 25, token_url: str = CISCO_PSIRT_TOKEN_URL,
                       api_base: str = CISCO_PSIRT_API_BASE,
                       stats: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """LIVE EGRESS (**credential-gated**): OAuth2, then GET the openVuln advisory (incl. fixed releases) per
    CVE, mapped to the feed shape + ``fixed``. **Refuses without creds → no egress.** A CVE with no Cisco
    advisory is skipped (coverage-honest). Verify field names against your openVuln API version before trust.

    **Reachability is distinguished from emptiness** (2026-07-28): a bare ``except Exception: continue``
    scored an expired token, a 403 rate limit and a DNS outage as "no advisory for this CVE", so a
    whole-source failure returned ``[]`` and got SIGNED and published as a legitimate zero-advisory feed.
    Only :data:`PSIRT_NO_ADVISORY_CODES` are benign skips; any other failure counts as *unreachable* and
    raises :class:`SourceUnavailable` at the end of the sweep (after every CVE is attempted, so the error
    reports the full split rather than the first symptom). ``stats`` — an optional dict — is filled with
    ``queried / advisories / no_advisory / unreachable / errors`` on BOTH paths, so the caller can report
    what was skipped instead of silently dropping it."""
    if not (client_id and client_secret):
        raise ValueError("cisco_psirt_source requires openVuln client_id + client_secret — no creds, no egress")
    import urllib.error
    import urllib.request
    counts: Dict[str, Any] = {"queried": 0, "advisories": 0, "no_advisory": 0, "unreachable": 0,
                              "errors": []}

    def _publish() -> None:
        if stats is not None:
            stats.update(counts)

    try:
        token = _oauth_token(client_id, client_secret, token_url=token_url, timeout=timeout)
    except Exception as ex:                                 # the token IS the source: no token, no data
        counts["unreachable"] = len(list(cve_ids or []))
        counts["errors"] = [f"oauth token: {type(ex).__name__}: {ex}"]
        _publish()
        raise SourceUnavailable(
            f"Cisco openVuln unreachable: the OAuth2 token request failed ({type(ex).__name__}: {ex}). "
            f"No advisory was fetched — this is NOT 'zero advisories'.", counts) from ex
    raw: List[Dict[str, Any]] = []
    for cve in cve_ids or []:
        counts["queried"] += 1
        req = urllib.request.Request(f"{api_base}/cve/{cve}",  # noqa: S310 (fenced, opt-in egress)
                                     headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as ex:
            if ex.code in PSIRT_NO_ADVISORY_CODES:
                counts["no_advisory"] += 1                  # documented benign case: Cisco has none
                continue
            counts["unreachable"] += 1                      # 401/403/429/5xx: the SOURCE failed us
            counts["errors"].append(f"{cve}: HTTP {ex.code} {ex.reason}")
            continue
        except Exception as ex:                             # URLError (DNS/proxy), timeout, bad JSON
            counts["unreachable"] += 1
            counts["errors"].append(f"{cve}: {type(ex).__name__}: {ex}")
            continue
        raw += data.get("advisories", data if isinstance(data, list) else [])
    out = map_psirt_advisories(raw)
    counts["advisories"] = len(out)
    _publish()
    if counts["unreachable"]:
        raise SourceUnavailable(
            f"Cisco openVuln could not be reached for {counts['unreachable']} of {counts['queried']} CVE(s) "
            f"(fetched {counts['advisories']} advisory(ies); {counts['no_advisory']} CVE(s) genuinely have "
            f"none). First failures: {'; '.join(counts['errors'][:3])}. The advisory surface would be short "
            f"by an UNKNOWN amount — refusing to report it as measured; retry when the source is reachable.",
            counts)
    return out
