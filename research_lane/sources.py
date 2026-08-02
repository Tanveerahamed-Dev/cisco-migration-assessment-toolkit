"""Real advisory sources for the research lane (egress). Each returns advisory dicts in the intel-feed shape.

The **fetch** does egress and is isolated here in the fenced lane. Every adapter uses the shared guarded
public-HTTPS path: validated/pinned DNS, no environment proxy, host-confined redirects, and bounded response
bytes/count/time. The **mapping** (:func:`map_kev_vulnerabilities`) is pure and unit-tested without a network.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit

# CISA Known Exploited Vulnerabilities — a public, no-auth JSON catalog of ACTIVELY-EXPLOITED CVEs.
CISA_KEV_URL = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"


def map_kev_vulnerabilities(vulns: List[Dict[str, Any]], *, vendor: Optional[str] = "Cisco",
                            limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """Pure: filter KEV entries to ``vendor`` and map to the intel-feed advisory shape. Being in KEV means
    actively exploited, so severity is High (Critical when tied to a ransomware campaign). No I/O."""
    if not isinstance(vulns, list):
        raise ValueError("CISA KEV vulnerabilities must be a list")
    if limit is not None and limit <= 0:
        raise ValueError("CISA KEV limit must be positive")
    out: List[Dict[str, Any]] = []
    for index, v in enumerate(vulns, 1):
        if not isinstance(v, dict):
            raise ValueError(f"CISA KEV item {index} is not an object")
        if vendor and str(v.get("vendorProject", "")).lower() != vendor.lower():
            continue
        if not isinstance(v.get("cveID"), str) or not v["cveID"].strip():
            raise ValueError(f"CISA KEV item {index} has no CVE id")
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
    """LIVE EGRESS: fetch the CISA KEV catalog and map it through the bounded public-HTTPS guard.
    Public, no-auth, read-only GET (fenced)."""
    from research_lane.http_guard import FetchBudget, guarded_urlopen, read_json_response
    budget = FetchBudget(max_responses=1, deadline_seconds=timeout)
    with guarded_urlopen(url, timeout=budget.timeout(timeout)) as resp:
        data = read_json_response(resp, budget=budget)
    if not isinstance(data, dict) or not isinstance(data.get("vulnerabilities"), list):
        raise ValueError("CISA KEV response is missing its vulnerabilities list")
    return map_kev_vulnerabilities(data.get("vulnerabilities", []), vendor=vendor, limit=limit)


# --- Cisco PSIRT openVuln (the fixed-version source — CREDENTIAL-gated, unlike CISA KEV) --------------
# The authoritative Cisco-fixed-release data KEV lacks. Requires an openVuln OAuth2 API client
# (https://apiconsole.cisco.com/) — so this source CANNOT run without creds (no creds -> no egress).
CISCO_PSIRT_TOKEN_URL = "https://id.cisco.com/oauth2/default/v1/token"
CISCO_PSIRT_API_BASE = "https://apix.cisco.com/security/advisories/v2"
_CISCO_TOKEN_HOST = "id.cisco.com"
_CISCO_API_HOST = "apix.cisco.com"
_CVE_ID = re.compile(r"^CVE-\d{4}-\d{4,7}$", re.IGNORECASE)


def map_psirt_advisories(advisories: List[Dict[str, Any]], *,
                         limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """Pure: map Cisco PSIRT openVuln advisory JSON to the intel-feed shape **plus a ``fixed`` field** — the
    fixed release(s), i.e. the Phase-B upgrade target the feed exists to supply. No I/O. Defensive across
    openVuln field-name variants (``firstFixed``/``fixedReleases``; ``sir``/``severity``) so a schema tweak
    degrades gracefully rather than dropping data. One entry per (advisory, CVE) so each CVE carries its fix."""
    if not isinstance(advisories, list):
        raise ValueError("Cisco PSIRT advisories must be a list")
    if limit is not None and limit <= 0:
        raise ValueError("Cisco PSIRT limit must be positive")
    out: List[Dict[str, Any]] = []
    for index, a in enumerate(advisories, 1):
        if not isinstance(a, dict):
            raise ValueError(f"Cisco PSIRT advisory {index} is not an object")
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
        identifiers = cves or [a.get("advisoryId")]
        if not isinstance(identifiers, list):
            raise ValueError(f"Cisco PSIRT advisory {index} has a malformed CVE list")
        identifiers = [cve for cve in identifiers if cve]
        if not identifiers:
            raise ValueError(f"Cisco PSIRT advisory {index} has no identifier")
        for cve in identifiers:
            if not isinstance(cve, str) or not cve.strip():
                raise ValueError(f"Cisco PSIRT advisory {index} has a non-string identifier")
            out.append({"id": cve, **base, "title": base["title"] or cve})
    out.sort(key=lambda x: x.get("published", ""))
    return out[-limit:] if limit else out


def _oauth_token(client_id: str, client_secret: str, *, token_url: str = CISCO_PSIRT_TOKEN_URL,
                 timeout: int = 25, budget=None) -> str:
    """OAuth2 client-credentials → access token through the host-pinned HTTPS guard. Raises on failure."""
    import urllib.parse
    import urllib.request
    from research_lane.http_guard import FetchBudget, guarded_urlopen, read_json_response
    if (urlsplit(token_url).hostname or "").lower() != _CISCO_TOKEN_HOST:
        raise ValueError(f"Cisco OAuth endpoint must remain pinned to {_CISCO_TOKEN_HOST}")
    budget = budget or FetchBudget(max_bytes=1024 * 1024, max_responses=1, deadline_seconds=timeout)
    body = urllib.parse.urlencode({"grant_type": "client_credentials",
                                   "client_id": client_id, "client_secret": client_secret}).encode()
    req = urllib.request.Request(token_url, data=body,
                                 headers={"Content-Type": "application/x-www-form-urlencoded",
                                          "Accept": "application/json"})
    with guarded_urlopen(
        req,
        timeout=budget.timeout(timeout),
        allowed_hosts={_CISCO_TOKEN_HOST},
    ) as resp:
        payload = read_json_response(resp, max_bytes=1024 * 1024, budget=budget)
    token = payload.get("access_token") if isinstance(payload, dict) else None
    if not isinstance(token, str) or not token.strip() or "\r" in token or "\n" in token:
        raise ValueError("Cisco OAuth response did not contain a safe access token")
    return token


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
    whole-source failure returned ``[]`` and got hash-sealed and published as a legitimate zero-advisory feed.
    Only :data:`PSIRT_NO_ADVISORY_CODES` are benign skips; any other failure counts as *unreachable* and
    raises :class:`SourceUnavailable` at the end of the sweep (after every CVE is attempted, so the error
    reports the full split rather than the first symptom). ``stats`` — an optional dict — is filled with
    ``queried / advisories / no_advisory / unreachable / errors`` on BOTH paths, so the caller can report
    what was skipped instead of silently dropping it."""
    if not (client_id and client_secret):
        raise ValueError("cisco_psirt_source requires openVuln client_id + client_secret — no creds, no egress")
    import urllib.error
    import urllib.request
    from research_lane.http_guard import FetchBudget, guarded_urlopen, read_json_response
    if (urlsplit(api_base).hostname or "").lower() != _CISCO_API_HOST:
        raise ValueError(f"Cisco advisory endpoint must remain pinned to {_CISCO_API_HOST}")
    normalized_cves: List[str] = []
    for raw_cve in cve_ids or []:
        cve = str(raw_cve).strip().upper()
        if not _CVE_ID.fullmatch(cve):
            raise ValueError(f"invalid CVE identifier refused: {raw_cve!r}")
        if cve not in normalized_cves:
            normalized_cves.append(cve)
    if len(normalized_cves) > 500:
        raise ValueError("refusing more than 500 CVE lookups in one Cisco PSIRT sweep")
    safe_api_base = api_base.rstrip("/")
    budget = FetchBudget(
        max_bytes=64 * 1024 * 1024,
        max_responses=len(normalized_cves) + 1,
        deadline_seconds=300,
    )
    counts: Dict[str, Any] = {"queried": 0, "advisories": 0, "no_advisory": 0, "unreachable": 0,
                              "errors": []}

    def _publish() -> None:
        if stats is not None:
            stats.update(counts)

    try:
        token = _oauth_token(
            client_id,
            client_secret,
            token_url=token_url,
            timeout=timeout,
            budget=budget,
        )
    except Exception as ex:                                 # the token IS the source: no token, no data
        counts["unreachable"] = len(normalized_cves)
        counts["errors"] = [f"oauth token: {type(ex).__name__}: {ex}"]
        _publish()
        raise SourceUnavailable(
            f"Cisco openVuln unreachable: the OAuth2 token request failed ({type(ex).__name__}: {ex}). "
            f"No advisory was fetched — this is NOT 'zero advisories'.", counts) from ex
    out: List[Dict[str, Any]] = []
    for cve in normalized_cves:
        counts["queried"] += 1
        req = urllib.request.Request(f"{safe_api_base}/cve/{cve}",  # noqa: S310
                                     headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
        try:
            with guarded_urlopen(
                req,
                timeout=budget.timeout(timeout),
                allowed_hosts={_CISCO_API_HOST},
            ) as resp:
                data = read_json_response(resp, budget=budget)
            if isinstance(data, dict):
                if "advisories" not in data or not isinstance(data["advisories"], list):
                    raise ValueError(
                        "Cisco openVuln response is missing its advisories list"
                    )
                advisory_rows = data["advisories"]
            elif isinstance(data, list):
                # Retained for the documented legacy response shape; rows remain strictly mapped.
                advisory_rows = data
            else:
                raise ValueError("Cisco openVuln response must be an object or list")
            out.extend(map_psirt_advisories(advisory_rows))
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
    out.sort(key=lambda item: item.get("published", ""))
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
