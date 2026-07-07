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


def cisco_psirt_source(cve_ids: List[str], *, client_id: Optional[str], client_secret: Optional[str],
                       timeout: int = 25, token_url: str = CISCO_PSIRT_TOKEN_URL,
                       api_base: str = CISCO_PSIRT_API_BASE) -> List[Dict[str, Any]]:
    """LIVE EGRESS (**credential-gated**): OAuth2, then GET the openVuln advisory (incl. fixed releases) per
    CVE, mapped to the feed shape + ``fixed``. **Refuses without creds → no egress.** A CVE with no Cisco
    advisory is skipped (coverage-honest). Verify field names against your openVuln API version before trust."""
    if not (client_id and client_secret):
        raise ValueError("cisco_psirt_source requires openVuln client_id + client_secret — no creds, no egress")
    import urllib.request
    token = _oauth_token(client_id, client_secret, token_url=token_url, timeout=timeout)
    raw: List[Dict[str, Any]] = []
    for cve in cve_ids or []:
        req = urllib.request.Request(f"{api_base}/cve/{cve}",  # noqa: S310 (fenced, opt-in egress)
                                     headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception:
            continue                                        # no Cisco advisory for this CVE -> skip
        raw += data.get("advisories", data if isinstance(data, list) else [])
    return map_psirt_advisories(raw)
