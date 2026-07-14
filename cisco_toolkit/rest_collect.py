"""Read-only REST collectors for controller-based fabrics — Cisco ACI / APIC and Catalyst SD-WAN / vManage.

The engine's primary ingestion is offline SSH ``show``-text; a controller fabric exposes its state only via a
northbound REST API, so this module is the LIVE collection front door for those fabrics. It authenticates with a
read-only credential, GETs the managed objects / dataservice endpoints the OFFLINE parsers already understand
(``parse_aci_*`` / ``parse_sdwan_*``), and writes one raw JSON file per query into a device directory using the
SAME filename transform ``--no-collect`` reads (``cmd.replace(" ","_")…replace("/","_")+".txt"``). Collection and
analysis stay fully decoupled: this writes the evidence files; ``build_aci`` / ``build_sdwan`` + the detectors
analyse them unchanged. So the whole downstream — snapshot, design_blueprint, deliverables, dashboards — is reused.

SAFETY DOCTRINE (read this before pointing it at a fabric):
  * **GET-only.** The only POST is the login; every fabric query is a GET. This module cannot create, modify or
    delete a fabric object — it cannot change device state.
  * **The read-only guarantee is CREDENTIAL-enforced, not command-enforced.** On a controller the SAME token that
    GETs can POST, so unlike the SSH ``show``-only collector there is no protocol-level read-only floor. Use a
    DEDICATED AAA account bound to a read-only RBAC role. The password is used once for login and is NEVER written
    to the snapshot, the collection dir, or any log.
  * **Opt-in only.** Nothing here runs on import or as part of ``cisco-assess``; a human invokes ``collect_apic`` /
    ``collect_vmanage`` (or the ``__main__`` CLI) with the controller URL + credentials + engagement authorization.
    Mirrors the SSH collector's 'never run a live collection unless explicitly asked' doctrine.
  * **TLS** verifies by default; pass ``verify_tls=False`` only for a lab/sandbox with a self-signed cert (logged).
"""
import base64
import http.cookiejar
import json
import logging
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)


class _NoDowngradeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Refuse a credential-leaking redirect on BOTH vectors. urllib's stock handler follows a 30x and, on the
    redirect, re-sends the request -- carrying the session cookie (CookieJar) or the
    'Authorization: Basic <b64(user:pass)>' header (stripping only content-length/content-type) -- to the new
    location. Two ways that leaks the read-only credential, both reachable via a single 302 from a controller /
    MITM / poisoned DNS:
      1. **scheme downgrade** (https->http): the credential goes on the wire in CLEARTEXT -- the exact failure
         ``_require_https`` prevents on the FIRST hop, reachable again via a redirect.
      2. **cross-host** (https://a -> https://attacker): the credential is delivered, still encrypted, straight
         to an ATTACKER-controlled host (TLS just guarantees it is encrypted *to the attacker*). Stock urllib
         does NO cross-host Authorization stripping, so there is no library backstop.
    A read-only collector is pointed at ONE controller and has no reason to follow an auth redirect to a
    different host, so both are refused (the raise is caught by the fail-soft GET/POST wrappers -> the query
    returns None; the credential is never transmitted to an unintended endpoint). Only a SAME-HOST https->https
    redirect (a different path/port on the same controller) is delegated to urllib unchanged."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlparse(newurl).scheme.lower() != "https":
            logger.error("  [rest] refusing an HTTPS->non-HTTPS redirect to %r -- a downgrade would leak the "
                         "credential/session cookie in cleartext", newurl)
            raise urllib.error.HTTPError(newurl, code, "refused HTTPS->non-HTTPS redirect downgrade", headers, fp)
        old_host = (urllib.parse.urlparse(req.get_full_url()).hostname or "").lower()
        new_host = (urllib.parse.urlparse(newurl).hostname or "").lower()
        if old_host and new_host and new_host != old_host:
            logger.error("  [rest] refusing a cross-host redirect (%s -> %s) -- urllib re-sends the "
                         "'Authorization: Basic' header / session cookie to the new host, so a 302 to a foreign "
                         "host would deliver the read-only credential to it", old_host, new_host)
            raise urllib.error.HTTPError(newurl, code, "refused cross-host redirect (credential-leak vector)",
                                         headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _safe_close(resp) -> None:
    """Close an HTTP response object best-effort (no dangling socket/fd from the login response)."""
    try:
        if resp is not None:
            resp.close()
    except Exception:                                                # noqa: BLE001
        pass


def _cmd_filename(cmd: str) -> str:
    """The engine's offline command->filename transform (so the parsers' _load_cmd_output finds the file)."""
    return cmd.replace(" ", "_").replace("|", "_").replace("^", "").replace("/", "_") + ".txt"


def _require_https(base_url: str, fabric: str) -> bool:
    """Refuse to send credentials over a non-HTTPS URL (the login would leak the password in cleartext). Real
    APIC / vManage controllers are HTTPS-only, so this is a safe secure-default, not a limitation."""
    if not base_url.lower().startswith("https://"):
        logger.error("  [%s] refusing to authenticate over a non-HTTPS URL (%r) -- credentials would be sent "
                     "in cleartext. Use an https:// controller URL.", fabric, base_url)
        return False
    return True


def _http_session(verify_tls: bool = True):
    """A urllib opener with a cookie jar (carries the session cookie across requests). With verify_tls False a
    CERT_NONE context is used — controller fabrics often ship a self-signed cert; opt out EXPLICITLY (logged)."""
    handlers = [urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
                _NoDowngradeRedirectHandler()]   # block an https->http redirect downgrade (cleartext-cred leak)
    if not verify_tls:
        logger.warning("  [rest] TLS verification DISABLED (verify_tls=False) — only acceptable for a lab/sandbox")
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        handlers.append(urllib.request.HTTPSHandler(context=ctx))
    return urllib.request.build_opener(*handlers)


def _safe_url(url) -> str:
    """A URL with any userinfo (user:pass@) stripped, for logging. Credentials embedded in --url
    (https://user:pass@host) must NEVER reach a log line / disk / console (audit-2 L3). Never raises."""
    try:
        p = urllib.parse.urlsplit(str(url))
        if p.username or p.password:
            host = p.hostname or ""
            if ":" in host:                              # IPv6 literal -> urlsplit strips the []; restore them
                host = f"[{host}]"
            netloc = host + (f":{p.port}" if p.port else "")
            return urllib.parse.urlunsplit((p.scheme, netloc, p.path, p.query, p.fragment))
    except Exception:                                                # noqa: BLE001
        pass
    return str(url)


def _post(opener, url: str, data, headers=None, timeout: int = 30):
    """POST (login only). Returns the response object (caller drains it) or None on error (fail-soft)."""
    body = data.encode("utf-8") if isinstance(data, str) else json.dumps(data).encode("utf-8")
    try:
        return opener.open(urllib.request.Request(url, data=body, headers=headers or {}, method="POST"), timeout=timeout)
    except Exception as e:                                            # noqa: BLE001 (collection is best-effort)
        logger.warning("  [rest] POST %s failed: %s", _safe_url(url), e)
        return None


def _get_text(opener, url: str, headers=None, timeout: int = 30):
    """GET a URL through the session opener and return the raw text body (or None on error)."""
    try:
        with opener.open(urllib.request.Request(url, headers=headers or {}, method="GET"), timeout=timeout) as r:
            return r.read().decode("utf-8", "ignore")
    except Exception as e:                                            # noqa: BLE001
        logger.warning("  [rest] GET %s failed: %s", _safe_url(url), e)
        return None


def _get_json(opener, url: str, headers=None, timeout: int = 30):
    """GET a URL and parse JSON. Returns the parsed object, or None on any transport / parse error (fail-soft —
    a single failed query never aborts the whole collection)."""
    txt = _get_text(opener, url, headers=headers, timeout=timeout)
    if txt is None:
        return None
    try:
        return json.loads(txt)
    except (ValueError, TypeError) as e:
        logger.warning("  [rest] GET %s returned non-JSON: %s", _safe_url(url), e)
        return None


def _write(out_dir: str, cmd: str, obj) -> str:
    """Write one raw JSON export to out_dir/<offline-filename(cmd)> so --no-collect reads it like a show-file."""
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, _cmd_filename(cmd))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2)
    return path


# --- Cisco ACI / APIC ---------------------------------------------------------------------------------------
# Maps the offline 'command' (what build_aci asks _load_cmd_output for) -> the APIC class query path.
APIC_CLASSES = {
    "moquery -c faultInst": "faultInst",
    "moquery -c fabricNode": "fabricNode",
    "moquery -c fabricHealthTotal": "fabricHealthTotal",
    "moquery -c fvCtx": "fvCtx",
    "moquery -c fvTenant": "fvTenant",
    "moquery -c fvBD": "fvBD",
    "moquery -c fvAEPg": "fvAEPg",
}


def collect_apic(base_url: str, username: str, password: str, out_dir: str, verify_tls: bool = True) -> list:
    """Read-only ACI/APIC collection: aaaLogin -> APIC-cookie session, then GET each managed-object class as
    JSON and write it into ``out_dir`` under the offline command-filename (build_aci -> parse_aci_*). Returns the
    list of files written. GET-only after the login POST; never changes fabric state; requires a read-only RBAC
    account (see the module doctrine). The password is used once for login and never persisted."""
    base = base_url.rstrip("/")
    if not _require_https(base, "APIC"):
        return []
    opener = _http_session(verify_tls)
    login = _post(opener, f"{base}/api/aaaLogin.json",
                  {"aaaUser": {"attributes": {"name": username, "pwd": password}}},
                  headers={"Content-Type": "application/json"})
    if login is None:
        logger.error("  [APIC] login failed — no collection")
        return []
    _safe_close(login)                              # session is carried by the cookie jar; close the login fd
    written = []
    for cmd, mo in APIC_CLASSES.items():
        obj = _get_json(opener, f"{base}/api/class/{mo}.json")
        if obj is None:
            continue
        # an APIC response whose imdata carries an {'error': ...} MO is a fault / RBAC-denied envelope, NOT class
        # data -- writing it would let the offline parser read a denied class as collected-but-empty (audit-5 #17).
        _imdata = obj.get("imdata") if isinstance(obj, dict) else None
        if isinstance(_imdata, list) and any(isinstance(m, dict) and "error" in m for m in _imdata):
            logger.warning("  [APIC] %s returned a fault / RBAC-denied envelope -- not written", mo)
            continue
        written.append(_write(out_dir, cmd, obj))
    logger.info("  [APIC] collected %d class export(s) into %s", len(written), out_dir)
    return written


# --- Cisco Catalyst SD-WAN / vManage ------------------------------------------------------------------------
VMANAGE_ENDPOINTS = {
    "dataservice/device": "/dataservice/device",
    "dataservice/device/control/connections": "/dataservice/device/control/connections",
    "dataservice/device/counters": "/dataservice/device/counters",
}


def collect_vmanage(base_url: str, username: str, password: str, out_dir: str, verify_tls: bool = True) -> list:
    """Read-only Catalyst SD-WAN (vManage) collection: j_security_check -> JSESSIONID, fetch the XSRF token,
    then GET each /dataservice endpoint as JSON and write it under the offline command-filename (build_sdwan ->
    parse_sdwan_*). GET-only after login; read-only RBAC account; password never persisted."""
    base = base_url.rstrip("/")
    if not _require_https(base, "vManage"):
        return []
    opener = _http_session(verify_tls)
    login = _post(opener, f"{base}/j_security_check",
                  urllib.parse.urlencode({"j_username": username, "j_password": password}),
                  headers={"Content-Type": "application/x-www-form-urlencoded"})
    if login is None:
        logger.error("  [vManage] login failed — no collection")
        return []
    try:                                                             # a truncated login body (IncompleteRead /
        body = login.read().decode("utf-8", "ignore") if hasattr(login, "read") else ""   # ConnectionReset /
    except Exception as _e:                                          # timeout) must fail soft, not crash the
        logger.error(f"  [vManage] login response read failed ({type(_e).__name__}) — no collection")  # whole
        _safe_close(login)                                           # collection (audit-4 #18 — the sibling
        return []                                                    # collectors all return [] here)
    _safe_close(login)                                               # drained; release the login fd
    if "<html" in (body or "").lower():                              # vManage serves an HTML login page on auth failure
        logger.error("  [vManage] authentication rejected — no collection")
        return []
    token = _get_text(opener, f"{base}/dataservice/client/token")    # the XSRF token is returned as plain text
    headers = {"X-XSRF-TOKEN": token.strip()} if isinstance(token, str) and token.strip() else {}
    written = []
    for cmd, ep in VMANAGE_ENDPOINTS.items():
        obj = _get_json(opener, f"{base}{ep}", headers=headers)
        if obj is not None:
            written.append(_write(out_dir, cmd, obj))
    logger.info("  [vManage] collected %d endpoint export(s) into %s", len(written), out_dir)
    return written


# --- Cisco ISE (Identity Services Engine) ---------------------------------------------------------------
# ISE deployment state via TWO read-only REST channels:
#   * Open API (ISE 3.1+, HTTPS/443): GET /api/v1/deployment/node -- personas (roles/services) + nodeStatus.
#   * ERS (HTTPS/9060, closed by default): GET /ers/config/node (SearchResult) -> per-id GET
#     /ers/config/node/{id} (boolean personas + nodeServiceTypes; NO reachability). The ERS "External RESTful
#     Services Operator" group is GET-only (read-only); Open API needs a read-only RBAC admin.
# Both use HTTP Basic auth (no token login). build_ise prefers the Open API list (richer) and falls back to
# the consolidated ERS export.
ISE_ENDPOINTS = {
    "api/v1/deployment/node": "/api/v1/deployment/node",
}


def collect_ise(base_url: str, username: str, password: str, out_dir: str, verify_tls: bool = True) -> list:
    """Read-only Cisco ISE (Identity Services Engine) collection via BOTH the Open API (HTTPS/443) and ERS
    (HTTPS/9060). Open API: GET /api/v1/deployment/node (personas + nodeStatus). ERS: GET /ers/config/node
    (a SearchResult of id/name), then per-id GET /ers/config/node/{id} for the rich node, CONSOLIDATED into a
    single export so the offline build reads one file. HTTP Basic auth over HTTPS -- the credential rides the
    Authorization header on each GET and is NEVER written to any export (only the node JSON is). GET-only --
    cannot change deployment state; use a DEDICATED read-only account (ERS 'External RESTful Services
    Operator' = GET-only; Open API read-only RBAC admin). Refuses non-HTTPS (a cleartext Basic-auth leak).
    Fail-soft: a disabled/unreachable channel is skipped, never raises. Returns the files written."""
    base = base_url.rstrip("/")
    if not _require_https(base, "ISE"):
        return []
    opener = _http_session(verify_tls)
    token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    headers = {"Authorization": "Basic " + token, "Accept": "application/json"}
    written = []
    # Open API (HTTPS/443): the cleanest single source -- personas + nodeStatus reachability.
    for cmd, ep in ISE_ENDPOINTS.items():
        obj = _get_json(opener, f"{base}{ep}", headers=headers)
        if obj is not None:
            written.append(_write(out_dir, cmd, obj))
    # ERS (HTTPS/9060, closed by default): two-step list -> per-id detail, consolidated into one export. Fail-
    # soft: if ERS is disabled/unreachable the SearchResult is None and the whole block is skipped.
    host = urllib.parse.urlparse(base).hostname or base
    ers_base = f"https://{host}:9060"
    # ALL pages of the node list (ERS paginates via SearchResult.nextPage.href) -- reading only page 1 silently
    # truncated the node census on a large deployment (audit-5 #16).
    resources: list = []
    nxt = f"{ers_base}/ers/config/node"
    while nxt:
        sr = _get_json(opener, nxt, headers=headers)
        # SearchResult / nextPage must be dicts before we .get() through them: a truthy non-dict (a scalar/list
        # in a malformed or spoofed ERS envelope) slips past `or {}` and raises AttributeError -> aborts the
        # opt-in collector. isinstance-guard both, and stop paginating on anything unexpected.
        sr_result = sr.get("SearchResult") if isinstance(sr, dict) else None
        if not isinstance(sr_result, dict):
            break
        page = sr_result.get("resources")
        if not isinstance(page, list):
            break
        resources.extend(page)
        # fail-soft (audit-6): a truthy non-dict nextPage would crash `.get("href")`; guard it to a str/None,
        _next = sr_result.get("nextPage")
        nxt = _next.get("href") if isinstance(_next, dict) else None
        if nxt:
            # ... then apply the SECURITY check (PR #368): nextPage.href is attacker-influenceable (it comes from
            # the controller response body). Following it verbatim with the Basic-auth header would leak the
            # read-only credential to ANY host/scheme it names (credential exfil / SSRF / a cleartext http://
            # downgrade). Only follow a same-origin link — https on the same host:9060 as ers_base — else stop.
            try:
                _p = urllib.parse.urlsplit(nxt)
                _off_origin = (_p.scheme != "https" or _p.hostname != host or (_p.port or 9060) != 9060)
            except ValueError:            # a malformed authority/port (':9060.attacker.com', ':+9060',
                _off_origin = True        # ':9060\tx') makes .port raise -> refuse; never propagate (the
                                          # module's fail-soft 'never raises' contract, audit-2 L3)
            if _off_origin:
                logger.warning("  [ISE] refusing off-host ERS pagination link: %s", _safe_url(nxt))
                nxt = None
    if resources:
        ers_nodes = []
        for res in resources:
            rid = res.get("id") if isinstance(res, dict) else None
            if not rid:
                continue
            detail = _get_json(opener, f"{ers_base}/ers/config/node/{rid}", headers=headers)
            if isinstance(detail, dict):
                # ERS wraps a single resource one level (e.g. {"ers-node-data": {...}}); unwrap to the node.
                inner = next(iter(detail.values())) if len(detail) == 1 else None
                node = inner if isinstance(inner, dict) else detail
                ers_nodes.append(node)
            else:
                # a failed per-id detail GET must NOT silently drop the node from the census -- keep the list
                # summary so the reported node count stays truthful (audit-5 #16).
                ers_nodes.append(res)
        if ers_nodes:
            written.append(_write(out_dir, "ers/config/node", {"resources": ers_nodes}))
    logger.info("  [ISE] collected %d export(s) into %s", len(written), out_dir)
    return written


# --- Cisco Secure Firewall Management Center (FMC / Firepower Management Center) -------------------------
# FMC manages an FTD fleet; the migration-relevant state is the device inventory + HA + deploy + manager-HA.
# Auth: POST /api/fmc_platform/v1/auth/generatetoken (HTTP Basic) -> the access token AND the DOMAINS list come
# back in RESPONSE HEADERS (X-auth-access-token, DOMAINS); the config endpoints are domain-scoped. The cmd keys
# are domain-less canonical names (the collector fills the domain uuid into the live URL; build_fmc reads the key).
FMC_CONFIG_ENDPOINTS = {
    "api/fmc_config/v1/devices/devicerecords": "/devices/devicerecords?expanded=true",
    "api/fmc_config/v1/devicehapairs/ftddevicehapairs": "/devicehapairs/ftddevicehapairs?expanded=true",
    "api/fmc_config/v1/deployment/deployabledevices": "/deployment/deployabledevices?expanded=true",
    "api/fmc_config/v1/integration/fmchastatuses": "/integration/fmchastatuses",
}


def collect_fmc(base_url: str, username: str, password: str, out_dir: str, verify_tls: bool = True) -> list:
    """Read-only Cisco Secure Firewall Management Center (FMC) collection. POST generatetoken (HTTP Basic over
    HTTPS) returns the X-auth-access-token AND the DOMAINS list in the response HEADERS; then GET each domain-
    scoped config endpoint (devicerecords / ftddevicehapairs / deployabledevices / fmchastatuses) and write it
    under the offline command-filename (build_fmc -> parse_fmc_*). GET-only after the login POST; the credential
    is used once for the Basic login header and is NEVER written to the export (only the JSON is). Refuses
    non-HTTPS. Use a DEDICATED read-only RBAC account. Returns the files written."""
    base = base_url.rstrip("/")
    if not _require_https(base, "FMC"):
        return []
    opener = _http_session(verify_tls)
    token_b64 = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    login = _post(opener, f"{base}/api/fmc_platform/v1/auth/generatetoken", "",
                  headers={"Authorization": "Basic " + token_b64})
    if login is None:
        logger.error("  [FMC] login failed -- no collection")
        return []
    token, domains = None, []
    try:
        hdrs = getattr(login, "headers", {}) or {}
        token = hdrs.get("X-auth-access-token")
        domains = json.loads(hdrs.get("DOMAINS") or "[]")
        if not isinstance(domains, list):    # 'DOMAINS: null' parses to None (no exception) -> 'for d in None' (#6)
            domains = []
    except (ValueError, TypeError, AttributeError):
        domains = []
    finally:
        _safe_close(login)                                          # token taken from the headers; close the fd
    if not token:
        logger.error("  [FMC] no X-auth-access-token in the login response -- no collection")
        return []
    # the domain UUID comes from the DOMAINS header (NOT a 'DOMAIN_UUID' header); default to Global / the first
    dom = next((d for d in domains if isinstance(d, dict) and str(d.get("name", "")).lower() == "global"),
               (domains[0] if domains and isinstance(domains[0], dict) else {}))
    dom_uuid = dom.get("uuid", "") if isinstance(dom, dict) else ""
    headers = {"X-auth-access-token": token}
    written = []
    for cmd, suffix in FMC_CONFIG_ENDPOINTS.items():
        obj = _get_json(opener, f"{base}/api/fmc_config/v1/domain/{dom_uuid}{suffix}", headers=headers)
        if obj is not None:
            written.append(_write(out_dir, cmd, obj))
    sv = _get_json(opener, f"{base}/api/fmc_platform/v1/info/serverversion", headers=headers)   # platform namespace (not domain-scoped)
    if sv is not None:
        written.append(_write(out_dir, "api/fmc_platform/v1/info/serverversion", sv))
    logger.info("  [FMC] collected %d endpoint export(s) into %s", len(written), out_dir)
    return written


if __name__ == "__main__":                                           # opt-in CLI; never runs on import
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    p = argparse.ArgumentParser(description="Read-only REST collector for ACI/APIC + Catalyst SD-WAN/vManage + "
                                            "ISE + Secure Firewall Mgmt Center (FMC). Writes JSON exports a "
                                            "`cisco-assess --no-collect` run then analyses. Use a DEDICATED "
                                            "READ-ONLY account; opt-in only.")
    p.add_argument("fabric", choices=["apic", "vmanage", "ise", "fmc"])
    p.add_argument("--url", required=True, help="https://<controller>")
    p.add_argument("--user", required=True)
    p.add_argument("--password", required=True, help="read-only RBAC account; used once for login, never stored")
    p.add_argument("--out-dir", required=True, help="the controller's device directory under the collection dir")
    p.add_argument("--insecure", action="store_true", help="disable TLS verification (lab/sandbox self-signed cert only)")
    a = p.parse_args()
    fn = {"apic": collect_apic, "vmanage": collect_vmanage, "ise": collect_ise, "fmc": collect_fmc}[a.fabric]
    files = fn(a.url, a.user, a.password, a.out_dir, verify_tls=not a.insecure)
    print(f"wrote {len(files)} export file(s):")
    for f in files:
        print("  " + f)
