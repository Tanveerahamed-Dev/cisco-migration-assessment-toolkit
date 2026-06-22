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
import http.cookiejar
import json
import logging
import os
import ssl
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)


def _cmd_filename(cmd: str) -> str:
    """The engine's offline command->filename transform (so the parsers' _load_cmd_output finds the file)."""
    return cmd.replace(" ", "_").replace("|", "_").replace("^", "").replace("/", "_") + ".txt"


def _http_session(verify_tls: bool = True):
    """A urllib opener with a cookie jar (carries the session cookie across requests). With verify_tls False a
    CERT_NONE context is used — controller fabrics often ship a self-signed cert; opt out EXPLICITLY (logged)."""
    handlers = [urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())]
    if not verify_tls:
        logger.warning("  [rest] TLS verification DISABLED (verify_tls=False) — only acceptable for a lab/sandbox")
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        handlers.append(urllib.request.HTTPSHandler(context=ctx))
    return urllib.request.build_opener(*handlers)


def _post(opener, url: str, data, headers=None, timeout: int = 30):
    """POST (login only). Returns the response object (caller drains it) or None on error (fail-soft)."""
    body = data.encode("utf-8") if isinstance(data, str) else json.dumps(data).encode("utf-8")
    try:
        return opener.open(urllib.request.Request(url, data=body, headers=headers or {}, method="POST"), timeout=timeout)
    except Exception as e:                                            # noqa: BLE001 (collection is best-effort)
        logger.warning("  [rest] POST %s failed: %s", url, e)
        return None


def _get_text(opener, url: str, headers=None, timeout: int = 30):
    """GET a URL through the session opener and return the raw text body (or None on error)."""
    try:
        with opener.open(urllib.request.Request(url, headers=headers or {}, method="GET"), timeout=timeout) as r:
            return r.read().decode("utf-8", "ignore")
    except Exception as e:                                            # noqa: BLE001
        logger.warning("  [rest] GET %s failed: %s", url, e)
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
        logger.warning("  [rest] GET %s returned non-JSON: %s", url, e)
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
}


def collect_apic(base_url: str, username: str, password: str, out_dir: str, verify_tls: bool = True) -> list:
    """Read-only ACI/APIC collection: aaaLogin -> APIC-cookie session, then GET each managed-object class as
    JSON and write it into ``out_dir`` under the offline command-filename (build_aci -> parse_aci_*). Returns the
    list of files written. GET-only after the login POST; never changes fabric state; requires a read-only RBAC
    account (see the module doctrine). The password is used once for login and never persisted."""
    base = base_url.rstrip("/")
    opener = _http_session(verify_tls)
    if _post(opener, f"{base}/api/aaaLogin.json",
             {"aaaUser": {"attributes": {"name": username, "pwd": password}}},
             headers={"Content-Type": "application/json"}) is None:
        logger.error("  [APIC] login failed — no collection")
        return []
    written = []
    for cmd, mo in APIC_CLASSES.items():
        obj = _get_json(opener, f"{base}/api/class/{mo}.json")
        if obj is not None:
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
    opener = _http_session(verify_tls)
    login = _post(opener, f"{base}/j_security_check",
                  urllib.parse.urlencode({"j_username": username, "j_password": password}),
                  headers={"Content-Type": "application/x-www-form-urlencoded"})
    if login is None:
        logger.error("  [vManage] login failed — no collection")
        return []
    body = login.read().decode("utf-8", "ignore") if hasattr(login, "read") else ""
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


if __name__ == "__main__":                                           # opt-in CLI; never runs on import
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    p = argparse.ArgumentParser(description="Read-only REST collector for ACI/APIC + Catalyst SD-WAN/vManage. "
                                            "Writes JSON exports a `cisco-assess --no-collect` run then analyses. "
                                            "Use a DEDICATED READ-ONLY account; opt-in only.")
    p.add_argument("fabric", choices=["apic", "vmanage"])
    p.add_argument("--url", required=True, help="https://<controller>")
    p.add_argument("--user", required=True)
    p.add_argument("--password", required=True, help="read-only RBAC account; used once for login, never stored")
    p.add_argument("--out-dir", required=True, help="the controller's device directory under the collection dir")
    p.add_argument("--insecure", action="store_true", help="disable TLS verification (lab/sandbox self-signed cert only)")
    a = p.parse_args()
    fn = collect_apic if a.fabric == "apic" else collect_vmanage
    files = fn(a.url, a.user, a.password, a.out_dir, verify_tls=not a.insecure)
    print(f"wrote {len(files)} export file(s):")
    for f in files:
        print("  " + f)
