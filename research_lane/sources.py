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
